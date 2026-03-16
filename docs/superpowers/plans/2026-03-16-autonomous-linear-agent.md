# Autonomous Linear Agent — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fully autonomous pipeline where Linear issues marked with the `agent` label are picked up by Agent Runner, implemented by Claude Code, and reported back to Linear + Discord in real-time.

**Architecture:** Two new modules (`linear_client.py`, `discord_notifier.py`) integrate with the existing `Executor`, which gains retry logic and progress logging. Webhook detection in `linear.py` routes agent-labeled issues to the `issue-resolver` task. Deduplication prevents double-runs. Subagents and security hooks harden the pipeline.

**Tech Stack:** Python 3.13, FastAPI, httpx (async HTTP), SQLite, Linear GraphQL API, Discord REST API, Claude Code CLI

**Spec:** `docs/superpowers/specs/2026-03-16-autonomous-linear-agent-design.md`

---

## File Map

### New Files
| File | Responsibility |
|---|---|
| `src/agents/linear_client.py` | Linear GraphQL API wrapper: fetch issues, post comments, update status, remove labels |
| `src/agents/discord_notifier.py` | Discord REST API: create/edit/finalize run messages with rate limiting + truncation |
| `tests/test_linear_client.py` | Unit tests for LinearClient (mocked httpx) |
| `tests/test_discord_notifier.py` | Unit tests for DiscordRunNotifier (mocked httpx) |

### Modified Files
| File | What Changes |
|---|---|
| `src/agents/models.py` | Add `linear_team_id`, `discord_channel_id` to `ProjectConfig` |
| `src/agents/webhooks/linear.py` | Add `match_agent_issue()`, `extract_agent_issue_variables()` |
| `src/agents/history.py` | Add `find_run_by_issue_id()` for deduplication |
| `src/agents/executor.py` | Optional `linear_client`/`discord_notifier` params; retry loop; progress log |
| `src/agents/main.py` | Wire new clients; agent issue webhook path; deduplication |
| `src/agents/config.py` | Add `LINEAR_API_KEY`, `DISCORD_BOT_TOKEN` to `GlobalConfig` |
| `projects/*.yaml` | Add `linear_team_id`, `discord_channel_id`, `issue-resolver` task |

### Subagents & Config (per project repo, not in this repo)
| File | Purpose |
|---|---|
| `.claude/agents/issue-analyzer.md` | Codebase analysis before implementation |
| `.claude/agents/issue-reviewer.md` | Review implementation before PR |
| `.claude/settings.json` | Security hooks (PreToolUse:Bash blocking destructive commands) |

---

## Chunk 1: Models & Config Foundation

### Task 1: Add `linear_team_id` and `discord_channel_id` to ProjectConfig

**Files:**
- Modify: `src/agents/models.py:57-63`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_models.py — add at end of file
def test_project_config_has_linear_team_id():
    from agents.models import ProjectConfig, TaskConfig, TriggerConfig

    config = ProjectConfig(
        name="test",
        repo="/tmp/repo",
        linear_team_id="team-abc-123",
        discord_channel_id="1234567890",
        tasks={
            "hello": TaskConfig(
                description="Test",
                prompt="Say hello",
                trigger=TriggerConfig(type="linear", events=["Issue.create"]),
            )
        },
    )
    assert config.linear_team_id == "team-abc-123"
    assert config.discord_channel_id == "1234567890"


def test_project_config_linear_fields_default_empty():
    from agents.models import ProjectConfig, TaskConfig, TriggerConfig

    config = ProjectConfig(
        name="test",
        repo="/tmp/repo",
        tasks={
            "hello": TaskConfig(
                description="Test",
                prompt="Say hello",
                trigger=TriggerConfig(type="linear", events=["Issue.create"]),
            )
        },
    )
    assert config.linear_team_id == ""
    assert config.discord_channel_id == ""
```

- [ ] **Step 2: Run test — verify FAIL**

Run: `uv run python -m pytest tests/test_models.py::test_project_config_has_linear_team_id tests/test_models.py::test_project_config_linear_fields_default_empty -v`
Expected: FAIL — `ProjectConfig` does not accept `linear_team_id`

- [ ] **Step 3: Implement**

In `src/agents/models.py`, add to `ProjectConfig`:

```python
class ProjectConfig(BaseModel):
    name: str
    repo: str
    base_branch: str = "main"
    branch_prefix: str = "agents/"
    notify: str = "slack"
    linear_team_id: str = ""
    discord_channel_id: str = ""
    tasks: dict[str, TaskConfig]
```

- [ ] **Step 4: Run test — verify PASS**

Run: `uv run python -m pytest tests/test_models.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/models.py tests/test_models.py
git commit -m "feat(models): add linear_team_id and discord_channel_id to ProjectConfig"
```

---

### Task 2: Add `LINEAR_API_KEY` and `DISCORD_BOT_TOKEN` to GlobalConfig

**Files:**
- Modify: `src/agents/config.py:47-52`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_config.py — add at end of file
def test_global_config_has_integration_keys(tmp_path):
    from agents.config import load_global_config

    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
budget:
  daily_limit_usd: 10.00
  warning_threshold_usd: 7.00
  pause_on_limit: true
notifications:
  slack_webhook_url: ""
webhooks:
  github_secret: ""
  linear_secret: ""
execution:
  worktree_base: /tmp/test
  dry_run: true
server:
  host: 127.0.0.1
  port: 9090
integrations:
  linear_api_key: "lin_key_123"
  discord_bot_token: "discord_token_456"
""")
    config = load_global_config(config_file)
    assert config.integrations.linear_api_key == "lin_key_123"
    assert config.integrations.discord_bot_token == "discord_token_456"


def test_global_config_integrations_default_empty(tmp_path):
    from agents.config import load_global_config

    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
budget:
  daily_limit_usd: 10.00
  warning_threshold_usd: 7.00
  pause_on_limit: true
notifications:
  slack_webhook_url: ""
webhooks:
  github_secret: ""
  linear_secret: ""
execution:
  worktree_base: /tmp/test
  dry_run: true
server:
  host: 127.0.0.1
  port: 9090
""")
    config = load_global_config(config_file)
    assert config.integrations.linear_api_key == ""
    assert config.integrations.discord_bot_token == ""
```

- [ ] **Step 2: Run test — verify FAIL**

Run: `uv run python -m pytest tests/test_config.py::test_global_config_has_integration_keys tests/test_config.py::test_global_config_integrations_default_empty -v`
Expected: FAIL — `GlobalConfig` has no `integrations` field

- [ ] **Step 3: Implement**

In `src/agents/config.py`, add:

```python
class IntegrationsConfig(BaseModel):
    linear_api_key: str = ""
    discord_bot_token: str = ""


class GlobalConfig(BaseModel):
    budget: BudgetConfig = BudgetConfig()
    notifications: NotificationsConfig = NotificationsConfig()
    webhooks: WebhooksConfig = WebhooksConfig()
    execution: ExecutionConfig = ExecutionConfig()
    server: ServerConfig = ServerConfig()
    integrations: IntegrationsConfig = IntegrationsConfig()
```

- [ ] **Step 4: Run test — verify PASS**

Run: `uv run python -m pytest tests/test_config.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/config.py tests/test_config.py
git commit -m "feat(config): add IntegrationsConfig with linear_api_key and discord_bot_token"
```

---

## Chunk 2: Linear Client

### Task 3: Create `LinearClient` with `fetch_issue`

**Files:**
- Create: `src/agents/linear_client.py`
- Create: `tests/test_linear_client.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_linear_client.py
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def linear_client():
    from agents.linear_client import LinearClient
    return LinearClient(api_key="test-key")


@pytest.mark.asyncio
async def test_fetch_issue_returns_issue_data(linear_client):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "issue": {
                "id": "issue-123",
                "identifier": "SEK-147",
                "title": "Add pagination",
                "description": "Add pagination to user list",
                "state": {"name": "Todo"},
                "labels": {"nodes": [{"name": "agent"}]},
            }
        }
    }

    with patch("agents.linear_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = await linear_client.fetch_issue("issue-123")

    assert result["id"] == "issue-123"
    assert result["identifier"] == "SEK-147"
    assert result["title"] == "Add pagination"
    assert result["description"] == "Add pagination to user list"
```

- [ ] **Step 2: Run test — verify FAIL**

Run: `uv run python -m pytest tests/test_linear_client.py::test_fetch_issue_returns_issue_data -v`
Expected: FAIL — `linear_client` module does not exist

- [ ] **Step 3: Implement `LinearClient` with `fetch_issue`**

```python
# src/agents/linear_client.py
import logging

import httpx

logger = logging.getLogger(__name__)

LINEAR_API_URL = "https://api.linear.app/graphql"


class LinearClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._team_states_cache: dict[str, dict[str, str]] = {}

    async def _graphql(self, query: str, variables: dict | None = None) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                LINEAR_API_URL,
                json={"query": query, "variables": variables or {}},
                headers={
                    "Authorization": self.api_key,
                    "Content-Type": "application/json",
                },
                timeout=15.0,
            )
            response.raise_for_status()
            return response.json()

    async def fetch_issue(self, issue_id: str) -> dict:
        query = """
        query($id: String!) {
            issue(id: $id) {
                id
                identifier
                title
                description
                state { name }
                labels { nodes { name id } }
            }
        }
        """
        data = await self._graphql(query, {"id": issue_id})
        issue = data.get("data", {}).get("issue", {})
        return {
            "id": issue.get("id", ""),
            "identifier": issue.get("identifier", ""),
            "title": issue.get("title", ""),
            "description": issue.get("description", ""),
            "state": issue.get("state", {}).get("name", ""),
            "labels": [n.get("name", "") for n in issue.get("labels", {}).get("nodes", [])],
        }
```

- [ ] **Step 4: Run test — verify PASS**

Run: `uv run python -m pytest tests/test_linear_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/linear_client.py tests/test_linear_client.py
git commit -m "feat(linear_client): add LinearClient with fetch_issue"
```

---

### Task 4: Add `post_comment` and `update_status` to LinearClient

**Files:**
- Modify: `src/agents/linear_client.py`
- Modify: `tests/test_linear_client.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_linear_client.py — add

@pytest.mark.asyncio
async def test_post_comment_calls_graphql(linear_client):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": {"commentCreate": {"success": True}}}

    with patch("agents.linear_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        await linear_client.post_comment("issue-123", "Test comment")

    call_args = mock_client.post.call_args
    body = call_args.kwargs.get("json") or call_args[1].get("json")
    assert "commentCreate" in body["query"]


@pytest.mark.asyncio
async def test_update_status_fetches_and_caches_team_states(linear_client):
    # First call returns team states, second call uses cache
    states_response = AsyncMock()
    states_response.status_code = 200
    states_response.json.return_value = {
        "data": {
            "team": {
                "states": {
                    "nodes": [
                        {"id": "state-1", "name": "Todo"},
                        {"id": "state-2", "name": "In Progress"},
                        {"id": "state-3", "name": "In Review"},
                    ]
                }
            }
        }
    }

    update_response = AsyncMock()
    update_response.status_code = 200
    update_response.json.return_value = {"data": {"issueUpdate": {"success": True}}}

    with patch("agents.linear_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post.side_effect = [states_response, update_response, update_response]
        mock_client_cls.return_value = mock_client

        await linear_client.update_status("issue-123", "team-1", "In Progress")
        # Second call should use cache — only 1 more post (the update), not 2
        await linear_client.update_status("issue-456", "team-1", "In Review")

    assert mock_client.post.call_count == 3  # 1 states fetch + 2 updates


@pytest.mark.asyncio
async def test_update_status_unknown_state_logs_warning(linear_client):
    states_response = AsyncMock()
    states_response.status_code = 200
    states_response.json.return_value = {
        "data": {"team": {"states": {"nodes": [{"id": "s1", "name": "Todo"}]}}}
    }

    with patch("agents.linear_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post.return_value = states_response
        mock_client_cls.return_value = mock_client

        # Should not raise — just logs warning
        await linear_client.update_status("issue-123", "team-1", "Nonexistent State")

    # Only 1 call (states fetch) — no update call because state not found
    assert mock_client.post.call_count == 1
```

- [ ] **Step 2: Run tests — verify FAIL**

Run: `uv run python -m pytest tests/test_linear_client.py -v`
Expected: FAIL — `post_comment` and `update_status` not defined

- [ ] **Step 3: Implement**

Add to `LinearClient` in `src/agents/linear_client.py`:

```python
    async def post_comment(self, issue_id: str, body: str) -> None:
        query = """
        mutation($issueId: String!, $body: String!) {
            commentCreate(input: { issueId: $issueId, body: $body }) {
                success
            }
        }
        """
        await self._graphql(query, {"issueId": issue_id, "body": body})

    async def update_status(self, issue_id: str, team_id: str, target_state_name: str) -> None:
        states = await self._get_team_states(team_id)
        state_id = states.get(target_state_name.lower())
        if not state_id:
            logger.warning("State '%s' not found for team %s. Available: %s", target_state_name, team_id, list(states.keys()))
            return
        query = """
        mutation($issueId: String!, $stateId: String!) {
            issueUpdate(id: $issueId, input: { stateId: $stateId }) {
                success
            }
        }
        """
        await self._graphql(query, {"issueId": issue_id, "stateId": state_id})

    async def _get_team_states(self, team_id: str) -> dict[str, str]:
        if team_id in self._team_states_cache:
            return self._team_states_cache[team_id]
        query = """
        query($teamId: String!) {
            team(id: $teamId) {
                states { nodes { id name } }
            }
        }
        """
        data = await self._graphql(query, {"teamId": team_id})
        nodes = data.get("data", {}).get("team", {}).get("states", {}).get("nodes", [])
        states = {node["name"].lower(): node["id"] for node in nodes}
        self._team_states_cache[team_id] = states
        return states
```

- [ ] **Step 4: Run tests — verify PASS**

Run: `uv run python -m pytest tests/test_linear_client.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/linear_client.py tests/test_linear_client.py
git commit -m "feat(linear_client): add post_comment and update_status with team state caching"
```

---

### Task 5: Add `remove_label` to LinearClient

**Files:**
- Modify: `src/agents/linear_client.py`
- Modify: `tests/test_linear_client.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_linear_client.py — add

@pytest.mark.asyncio
async def test_remove_label_finds_and_removes_by_name(linear_client):
    # First call: query label IDs on the issue
    fetch_response = AsyncMock()
    fetch_response.status_code = 200
    fetch_response.json.return_value = {
        "data": {
            "issue": {
                "labels": {"nodes": [
                    {"name": "agent", "id": "label-agent-id"},
                    {"name": "bug", "id": "label-bug-id"},
                ]},
            }
        }
    }

    remove_response = AsyncMock()
    remove_response.status_code = 200
    remove_response.json.return_value = {"data": {"issueRemoveLabel": {"success": True}}}

    with patch("agents.linear_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post.side_effect = [fetch_response, remove_response]
        mock_client_cls.return_value = mock_client

        await linear_client.remove_label("issue-123", "agent")

    assert mock_client.post.call_count == 2
    last_call_body = mock_client.post.call_args_list[1].kwargs.get("json") or mock_client.post.call_args_list[1][1].get("json")
    assert "issueRemoveLabel" in last_call_body["query"]
```

- [ ] **Step 2: Run test — verify FAIL**

Run: `uv run python -m pytest tests/test_linear_client.py::test_remove_label_finds_and_removes_by_name -v`
Expected: FAIL — `remove_label` not defined

- [ ] **Step 3: Implement**

Add to `LinearClient`:

```python
    async def remove_label(self, issue_id: str, label_name: str) -> None:
        # Fetch label IDs directly (fetch_issue flattens them to names only)
        data = await self._graphql(
            """query($id: String!) { issue(id: $id) { labels { nodes { id name } } } }""",
            {"id": issue_id},
        )
        nodes = data.get("data", {}).get("issue", {}).get("labels", {}).get("nodes", [])
        label_id = next((n["id"] for n in nodes if n["name"].lower() == label_name.lower()), None)
        if not label_id:
            logger.warning("Label '%s' not found on issue %s", label_name, issue_id)
            return
        await self._graphql(
            """mutation($issueId: String!, $labelId: String!) {
                issueRemoveLabel(id: $issueId, labelId: $labelId) { success }
            }""",
            {"issueId": issue_id, "labelId": label_id},
        )
```

- [ ] **Step 4: Run tests — verify PASS**

Run: `uv run python -m pytest tests/test_linear_client.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/linear_client.py tests/test_linear_client.py
git commit -m "feat(linear_client): add remove_label for deduplication label cleanup"
```

---

## Chunk 3: Discord Notifier

### Task 6: Create `DiscordRunNotifier` with `create_run_message`

**Files:**
- Create: `src/agents/discord_notifier.py`
- Create: `tests/test_discord_notifier.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_discord_notifier.py
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def notifier():
    from agents.discord_notifier import DiscordRunNotifier
    return DiscordRunNotifier(bot_token="test-token")


@pytest.mark.asyncio
async def test_create_run_message_returns_message_id(notifier):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "msg-123"}

    with patch("agents.discord_notifier.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        message_id = await notifier.create_run_message("chan-1", "SEK-147", "Add pagination")

    assert message_id == "msg-123"
    call_args = mock_client.post.call_args
    assert "/channels/chan-1/messages" in call_args.args[0]
    body = call_args.kwargs.get("json")
    assert body["embeds"][0]["title"]  # embed has a title
```

- [ ] **Step 2: Run test — verify FAIL**

Run: `uv run python -m pytest tests/test_discord_notifier.py::test_create_run_message_returns_message_id -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement**

```python
# src/agents/discord_notifier.py
import asyncio
import logging
import time

import httpx

logger = logging.getLogger(__name__)

DISCORD_API_URL = "https://discord.com/api/v10"


class DiscordRunNotifier:
    EDIT_INTERVAL_SECONDS = 2.0
    MAX_EVENTS_IN_EMBED = 40
    MAX_EMBED_LENGTH = 4000  # leave margin from 4096 limit

    def __init__(self, bot_token: str) -> None:
        self.bot_token = bot_token
        self._last_edit_time: float = 0.0
        self._headers = {
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, json: dict | None = None) -> dict:
        url = f"{DISCORD_API_URL}{path}"
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method, url, json=json, headers=self._headers, timeout=10.0,
            )
            if response.status_code == 429:
                retry_after = response.json().get("retry_after", 2.0)
                logger.warning("Discord rate limited, backing off %.1fs", retry_after)
                await asyncio.sleep(retry_after)
                response = await client.request(
                    method, url, json=json, headers=self._headers, timeout=10.0,
                )
            response.raise_for_status()
            return response.json()

    def _build_embed(
        self,
        identifier: str,
        title: str,
        events: list[dict] | None = None,
        status: str = "running",
        pr_url: str | None = None,
        cost: float = 0.0,
        duration_s: float = 0.0,
        error: str | None = None,
    ) -> dict:
        color = {"running": 0x059669, "success": 0x4ade80, "failure": 0xf87171}
        status_label = {"running": "⚡ Executando issue", "success": "✅ Issue resolvida", "failure": "❌ Falha"}

        lines = []
        if events:
            display_events = events
            omitted = 0
            if len(events) > self.MAX_EVENTS_IN_EMBED:
                omitted = len(events) - self.MAX_EVENTS_IN_EMBED
                display_events = events[-self.MAX_EVENTS_IN_EMBED:]
            if omitted:
                lines.append(f"*... {omitted} earlier events omitted*")
            for evt in display_events:
                ts = time.strftime("%H:%M:%S", time.localtime(evt.get("timestamp", 0)))
                etype = evt.get("type", "unknown")
                content = evt.get("content", "")[:120]
                icon = {"assistant": "💭", "tool_use": "🔧", "tool_result": "📋", "system": "🚀"}.get(etype, "•")
                tool = evt.get("tool_name", "")
                label = f"**{tool}** {content}" if tool else content
                lines.append(f"`{ts}` {icon} {label}")

        desc_body = "\n".join(lines) if lines else "*aguardando eventos...*"
        if len(desc_body) > self.MAX_EMBED_LENGTH:
            desc_body = desc_body[-self.MAX_EMBED_LENGTH:]

        embed: dict = {
            "title": f"{status_label.get(status, status)} — {identifier}",
            "description": f"**{title}**\n\n{desc_body}",
            "color": color.get(status, 0x6b7280),
        }

        footer_parts = []
        if duration_s > 0:
            m, s = divmod(int(duration_s), 60)
            footer_parts.append(f"{'✓' if status == 'success' else '✗' if status == 'failure' else '⏱'} {m}m{s:02d}s")
        if cost > 0:
            footer_parts.append(f"${cost:.2f}")
        if pr_url:
            embed["url"] = pr_url
        if error:
            embed["description"] += f"\n\n```\n{error[:500]}\n```"
        if footer_parts:
            embed["footer"] = {"text": " · ".join(footer_parts)}

        return embed

    async def create_run_message(self, channel_id: str, identifier: str, title: str) -> str:
        embed = self._build_embed(identifier, title, status="running")
        data = await self._request("POST", f"/channels/{channel_id}/messages", json={"embeds": [embed]})
        return data["id"]
```

- [ ] **Step 4: Run test — verify PASS**

Run: `uv run python -m pytest tests/test_discord_notifier.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/discord_notifier.py tests/test_discord_notifier.py
git commit -m "feat(discord_notifier): add DiscordRunNotifier with create_run_message"
```

---

### Task 7: Add `update_run_message` with rate limiting and truncation

**Files:**
- Modify: `src/agents/discord_notifier.py`
- Modify: `tests/test_discord_notifier.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_discord_notifier.py — add (also add `import time` at top of file)
import time

@pytest.mark.asyncio
async def test_update_run_message_edits_message(notifier):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "msg-123"}

    events = [
        {"type": "tool_use", "tool_name": "Read", "content": "src/main.py", "timestamp": 1000.0},
        {"type": "tool_use", "tool_name": "Edit", "content": "src/main.py", "timestamp": 1001.0},
    ]

    with patch("agents.discord_notifier.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.request.return_value = mock_response
        mock_client_cls.return_value = mock_client

        notifier._last_edit_time = 0  # bypass rate limit
        await notifier.update_run_message("chan-1", "msg-123", "SEK-147", "Title", events)

    call_args = mock_client.request.call_args
    assert "PATCH" in call_args.args[0]
    assert "/channels/chan-1/messages/msg-123" in call_args.args[1]


@pytest.mark.asyncio
async def test_update_run_message_rate_limits(notifier):
    """Should skip edit if called within EDIT_INTERVAL_SECONDS."""
    notifier._last_edit_time = time.time()  # just edited

    with patch("agents.discord_notifier.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        await notifier.update_run_message("chan-1", "msg-1", "SEK-1", "T", [])

    # Should not have made any HTTP call
    mock_client.request.assert_not_called()


def test_build_embed_truncates_at_40_events(notifier):
    events = [{"type": "tool_use", "tool_name": "Read", "content": f"file-{i}.py", "timestamp": float(i)} for i in range(60)]
    embed = notifier._build_embed("SEK-1", "Title", events=events, status="running")
    # Should mention omitted events
    assert "20 earlier events omitted" in embed["description"]
```

- [ ] **Step 2: Run tests — verify FAIL**

Run: `uv run python -m pytest tests/test_discord_notifier.py -v`
Expected: FAIL — `update_run_message` not defined

- [ ] **Step 3: Implement**

Add to `DiscordRunNotifier`:

```python
    async def update_run_message(
        self, channel_id: str, message_id: str, identifier: str, title: str, events: list[dict],
    ) -> None:
        now = time.time()
        if now - self._last_edit_time < self.EDIT_INTERVAL_SECONDS:
            return  # throttled
        embed = self._build_embed(identifier, title, events=events, status="running")
        await self._request("PATCH", f"/channels/{channel_id}/messages/{message_id}", json={"embeds": [embed]})
        self._last_edit_time = now
```

- [ ] **Step 4: Run tests — verify PASS**

Run: `uv run python -m pytest tests/test_discord_notifier.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/discord_notifier.py tests/test_discord_notifier.py
git commit -m "feat(discord_notifier): add update_run_message with 2s rate limiting and 40-event truncation"
```

---

### Task 8: Add `finalize_run_message` and `fail_run_message`

**Files:**
- Modify: `src/agents/discord_notifier.py`
- Modify: `tests/test_discord_notifier.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_discord_notifier.py — add

@pytest.mark.asyncio
async def test_finalize_run_message_sets_success_embed(notifier):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "msg-123"}

    with patch("agents.discord_notifier.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.request.return_value = mock_response
        mock_client_cls.return_value = mock_client

        await notifier.finalize_run_message(
            "chan-1", "msg-123", "SEK-147", "Title", [],
            pr_url="https://github.com/org/repo/pull/1", cost=0.43, duration_s=301.0,
        )

    call_args = mock_client.request.call_args
    body = call_args.kwargs.get("json")
    embed = body["embeds"][0]
    assert "resolvida" in embed["title"].lower() or "✅" in embed["title"]
    assert embed["color"] == 0x4ade80


@pytest.mark.asyncio
async def test_fail_run_message_sets_failure_embed(notifier):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "msg-123"}

    with patch("agents.discord_notifier.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.request.return_value = mock_response
        mock_client_cls.return_value = mock_client

        await notifier.fail_run_message(
            "chan-1", "msg-123", "SEK-147", "Title", [],
            error="Tests failed: 3 assertions", attempt=3, max_attempts=3, cost=1.2, duration_s=180.0,
        )

    call_args = mock_client.request.call_args
    body = call_args.kwargs.get("json")
    embed = body["embeds"][0]
    assert embed["color"] == 0xf87171
    assert "Tests failed" in embed["description"]
```

- [ ] **Step 2: Run tests — verify FAIL**

Run: `uv run python -m pytest tests/test_discord_notifier.py -v`
Expected: FAIL — methods not defined

- [ ] **Step 3: Implement**

Add to `DiscordRunNotifier`:

```python
    async def finalize_run_message(
        self, channel_id: str, message_id: str, identifier: str, title: str,
        events: list[dict], pr_url: str | None = None, cost: float = 0.0, duration_s: float = 0.0,
    ) -> None:
        embed = self._build_embed(identifier, title, events=events, status="success", pr_url=pr_url, cost=cost, duration_s=duration_s)
        await self._request("PATCH", f"/channels/{channel_id}/messages/{message_id}", json={"embeds": [embed]})

    async def fail_run_message(
        self, channel_id: str, message_id: str, identifier: str, title: str,
        events: list[dict], error: str = "", attempt: int = 0, max_attempts: int = 3,
        cost: float = 0.0, duration_s: float = 0.0,
    ) -> None:
        embed = self._build_embed(identifier, title, events=events, status="failure", error=error, cost=cost, duration_s=duration_s)
        embed["footer"] = {"text": f"Attempt {attempt}/{max_attempts} · ${cost:.2f}"}
        await self._request("PATCH", f"/channels/{channel_id}/messages/{message_id}", json={"embeds": [embed]})
```

- [ ] **Step 4: Run tests — verify PASS**

Run: `uv run python -m pytest tests/test_discord_notifier.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite — verify no regressions**

Run: `uv run python -m pytest --tb=short`
Expected: ALL PASS (existing 113 + new tests)

- [ ] **Step 6: Commit**

```bash
git add src/agents/discord_notifier.py tests/test_discord_notifier.py
git commit -m "feat(discord_notifier): add finalize_run_message and fail_run_message"
```

---

## Chunk 4: Webhook Detection & Deduplication

### Task 9: Add `match_agent_issue` and `extract_agent_issue_variables` to linear webhook

**Files:**
- Modify: `src/agents/webhooks/linear.py`
- Modify: `tests/test_webhooks/test_linear.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_webhooks/test_linear.py — add at end

def test_match_agent_issue_with_agent_label():
    from agents.webhooks.linear import match_agent_issue

    payload = {
        "action": "create",
        "type": "Issue",
        "data": {
            "id": "issue-123",
            "labels": [{"name": "agent"}, {"name": "bug"}],
        },
    }
    assert match_agent_issue(payload) is True


def test_match_agent_issue_without_agent_label():
    from agents.webhooks.linear import match_agent_issue

    payload = {
        "action": "create",
        "type": "Issue",
        "data": {
            "id": "issue-123",
            "labels": [{"name": "bug"}],
        },
    }
    assert match_agent_issue(payload) is False


def test_match_agent_issue_ignores_non_issue_types():
    from agents.webhooks.linear import match_agent_issue

    payload = {
        "action": "create",
        "type": "Comment",
        "data": {"id": "c-1", "labels": [{"name": "agent"}]},
    }
    assert match_agent_issue(payload) is False


def test_extract_agent_issue_variables():
    from agents.webhooks.linear import extract_agent_issue_variables

    payload = {
        "data": {
            "id": "issue-abc",
            "identifier": "SEK-147",
            "title": "Add pagination",
            "description": "Add pagination to user list",
            "teamId": "team-xyz",
        }
    }
    variables = extract_agent_issue_variables(payload)
    assert variables["issue_id"] == "issue-abc"
    assert variables["issue_identifier"] == "SEK-147"
    assert variables["issue_title"] == "Add pagination"
    assert variables["issue_description"] == "Add pagination to user list"
    assert variables["team_id"] == "team-xyz"
```

- [ ] **Step 2: Run tests — verify FAIL**

Run: `uv run python -m pytest tests/test_webhooks/test_linear.py::test_match_agent_issue_with_agent_label tests/test_webhooks/test_linear.py::test_extract_agent_issue_variables -v`
Expected: FAIL — functions not defined

- [ ] **Step 3: Implement**

Add to `src/agents/webhooks/linear.py`:

```python
def match_agent_issue(payload: dict) -> bool:
    if payload.get("type") != "Issue":
        return False
    action = payload.get("action", "")
    if action not in ("create", "update"):
        return False
    data = payload.get("data", {})
    # Linear webhook v2 sends labels as objects with name field
    labels = data.get("labels", [])
    if any(label.get("name") == "agent" for label in labels if isinstance(label, dict)):
        return True
    # Fallback: check labelIds if labels not present (requires agent label ID config)
    # For v1, we rely on labels[] being present in the webhook payload
    return False


def extract_agent_issue_variables(payload: dict) -> dict[str, str]:
    data = payload.get("data", {})
    return {
        "issue_id": data.get("id", ""),
        "issue_identifier": data.get("identifier", ""),
        "issue_title": data.get("title", ""),
        "issue_description": data.get("description", ""),
        "team_id": data.get("teamId", ""),
    }
```

- [ ] **Step 4: Run tests — verify PASS**

Run: `uv run python -m pytest tests/test_webhooks/test_linear.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/webhooks/linear.py tests/test_webhooks/test_linear.py
git commit -m "feat(webhooks): add match_agent_issue and extract_agent_issue_variables"
```

---

### Task 10: Add deduplication query to HistoryDB

**Files:**
- Modify: `src/agents/history.py`
- Modify: `tests/test_history.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_history.py — add at end

def test_find_run_by_issue_id_returns_latest(history_db):
    from agents.models import RunRecord, RunStatus, TriggerType
    from datetime import UTC, datetime

    history_db.insert_run(RunRecord(
        id="proj-issue-resolver-issue-abc-20260316-001",
        project="proj", task="issue-resolver",
        trigger_type=TriggerType.LINEAR,
        started_at=datetime(2026, 3, 16, 10, 0, 0, tzinfo=UTC),
        status=RunStatus.FAILURE, model="sonnet",
    ))
    history_db.insert_run(RunRecord(
        id="proj-issue-resolver-issue-abc-20260316-002",
        project="proj", task="issue-resolver",
        trigger_type=TriggerType.LINEAR,
        started_at=datetime(2026, 3, 16, 11, 0, 0, tzinfo=UTC),
        status=RunStatus.SUCCESS, model="sonnet",
    ))
    result = history_db.find_run_by_issue_id("issue-abc")
    assert result is not None
    assert result.status == RunStatus.SUCCESS  # latest run


def test_find_run_by_issue_id_returns_none_when_not_found(history_db):
    result = history_db.find_run_by_issue_id("nonexistent-issue")
    assert result is None
```

- [ ] **Step 2: Run tests — verify FAIL**

Run: `uv run python -m pytest tests/test_history.py::test_find_run_by_issue_id_returns_latest tests/test_history.py::test_find_run_by_issue_id_returns_none_when_not_found -v`
Expected: FAIL — `find_run_by_issue_id` not defined

- [ ] **Step 3: Implement**

Add to `HistoryDB` in `src/agents/history.py`:

```python
    def find_run_by_issue_id(self, issue_id: str) -> RunRecord | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE task = 'issue-resolver' AND id LIKE ? ORDER BY started_at DESC LIMIT 1",
                (f"%{issue_id}%",),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)
```

- [ ] **Step 4: Run tests — verify PASS**

Run: `uv run python -m pytest tests/test_history.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/history.py tests/test_history.py
git commit -m "feat(history): add find_run_by_issue_id for webhook deduplication"
```

---

## Chunk 5: Executor Enhancements

### Task 11: Add `linear_client` and `discord_notifier` optional params to Executor

**Files:**
- Modify: `src/agents/executor.py:52-68`
- Modify: `tests/test_executor.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_executor.py — add at end

def test_executor_accepts_optional_linear_and_discord_clients(tmp_path):
    from unittest.mock import MagicMock
    from agents.config import ExecutionConfig
    from agents.executor import Executor

    executor = Executor(
        config=ExecutionConfig(dry_run=True),
        budget=MagicMock(),
        history=MagicMock(),
        notifier=MagicMock(),
        data_dir=tmp_path,
        linear_client=MagicMock(),
        discord_notifier=MagicMock(),
    )
    assert executor.linear_client is not None
    assert executor.discord_notifier is not None


def test_executor_works_without_optional_clients(tmp_path):
    from unittest.mock import MagicMock
    from agents.config import ExecutionConfig
    from agents.executor import Executor

    executor = Executor(
        config=ExecutionConfig(dry_run=True),
        budget=MagicMock(),
        history=MagicMock(),
        notifier=MagicMock(),
        data_dir=tmp_path,
    )
    assert executor.linear_client is None
    assert executor.discord_notifier is None
```

- [ ] **Step 2: Run tests — verify FAIL**

Run: `uv run python -m pytest tests/test_executor.py::test_executor_accepts_optional_linear_and_discord_clients tests/test_executor.py::test_executor_works_without_optional_clients -v`
Expected: FAIL — `Executor` doesn't accept `linear_client`

- [ ] **Step 3: Implement**

Modify `Executor.__init__` in `src/agents/executor.py`:

```python
class Executor:
    def __init__(
        self,
        config: ExecutionConfig,
        budget: BudgetManager,
        history: HistoryDB,
        notifier: Notifier,
        data_dir: Path,
        on_stream_event: Callable | None = None,
        linear_client: object | None = None,
        discord_notifier: object | None = None,
    ) -> None:
        self.config = config
        self.budget = budget
        self.history = history
        self.notifier = notifier
        self.data_dir = data_dir
        self._running_processes: dict[str, asyncio.subprocess.Process] = {}
        self.on_stream_event = on_stream_event or self._noop_event
        self.linear_client = linear_client
        self.discord_notifier = discord_notifier
```

- [ ] **Step 4: Run tests — verify PASS**

Run: `uv run python -m pytest tests/test_executor.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/executor.py tests/test_executor.py
git commit -m "feat(executor): add optional linear_client and discord_notifier constructor params"
```

---

### Task 12: Add progress log helpers to Executor

**Files:**
- Modify: `src/agents/executor.py`
- Modify: `tests/test_executor.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_executor.py — add

def test_write_progress_log(tmp_path):
    from agents.executor import write_progress_log

    progress_dir = tmp_path / "progress"
    path = write_progress_log(
        progress_dir, "issue-abc", attempt=1,
        issue_title="Add pagination", issue_description="Add to user list",
    )
    assert path.exists()
    content = path.read_text()
    assert "Add pagination" in content
    assert "attempt 1" in content.lower()


def test_append_progress_log(tmp_path):
    from agents.executor import write_progress_log, append_progress_log

    progress_dir = tmp_path / "progress"
    path = write_progress_log(progress_dir, "issue-abc", attempt=1, issue_title="T", issue_description="D")
    append_progress_log(progress_dir, "issue-abc", attempt=1, error="Tests failed: 3 assertions")
    content = path.read_text()
    assert "Tests failed" in content


def test_delete_progress_log(tmp_path):
    from agents.executor import write_progress_log, delete_progress_log

    progress_dir = tmp_path / "progress"
    path = write_progress_log(progress_dir, "issue-abc", attempt=1, issue_title="T", issue_description="D")
    assert path.exists()
    delete_progress_log(progress_dir, "issue-abc")
    assert not path.exists()
```

- [ ] **Step 2: Run tests — verify FAIL**

Run: `uv run python -m pytest tests/test_executor.py::test_write_progress_log tests/test_executor.py::test_append_progress_log tests/test_executor.py::test_delete_progress_log -v`
Expected: FAIL — functions not defined

- [ ] **Step 3: Implement**

Add to `src/agents/executor.py` (module-level functions):

```python
def write_progress_log(
    progress_dir: Path, issue_id: str, attempt: int,
    issue_title: str = "", issue_description: str = "",
) -> Path:
    progress_dir.mkdir(parents=True, exist_ok=True)
    path = progress_dir / f"{issue_id}.txt"
    path.write_text(
        f"# Progress Log — {issue_id}\n\n"
        f"## Issue: {issue_title}\n{issue_description}\n\n"
        f"## Attempt {attempt}\nStarting...\n"
    )
    return path


def append_progress_log(progress_dir: Path, issue_id: str, attempt: int, error: str = "") -> None:
    path = progress_dir / f"{issue_id}.txt"
    if path.exists():
        with path.open("a") as f:
            f.write(f"\n### Attempt {attempt} — FAILED\nError: {error}\n")


def delete_progress_log(progress_dir: Path, issue_id: str) -> None:
    path = progress_dir / f"{issue_id}.txt"
    if path.exists():
        path.unlink()
```

- [ ] **Step 4: Run tests — verify PASS**

Run: `uv run python -m pytest tests/test_executor.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/executor.py tests/test_executor.py
git commit -m "feat(executor): add progress log helpers for retry continuity"
```

---

## Chunk 6: Main App Wiring & Integration

### Task 13: Wire LinearClient and DiscordRunNotifier in `create_app`

**Files:**
- Modify: `src/agents/main.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_main.py — add at end

@pytest.mark.asyncio
async def test_app_creates_linear_client_when_configured(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
budget:
  daily_limit_usd: 10.00
  warning_threshold_usd: 7.00
  pause_on_limit: true
notifications:
  slack_webhook_url: ""
webhooks:
  github_secret: test-secret
  linear_secret: test-linear-secret
execution:
  worktree_base: /tmp/test-agents
  dry_run: true
server:
  host: 127.0.0.1
  port: 9090
integrations:
  linear_api_key: "test-linear-key"
  discord_bot_token: "test-discord-token"
""")
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    from agents.main import create_app

    app = create_app(config_path=config_file, projects_dir=projects_dir, data_dir=tmp_path / "data")
    state = app.state.app_state
    assert state.executor.linear_client is not None
    assert state.executor.discord_notifier is not None
```

- [ ] **Step 2: Run test — verify FAIL**

Run: `uv run python -m pytest tests/test_main.py::test_app_creates_linear_client_when_configured -v`
Expected: FAIL — `config.integrations` not recognized or `executor` missing clients

- [ ] **Step 3: Implement**

In `src/agents/main.py`, in `create_app()`, after creating `notifier` and before creating `executor`:

```python
    # Create optional integration clients
    from agents.linear_client import LinearClient
    from agents.discord_notifier import DiscordRunNotifier

    linear_client = None
    discord_notifier_client = None
    if config.integrations.linear_api_key:
        linear_client = LinearClient(api_key=config.integrations.linear_api_key)
    if config.integrations.discord_bot_token:
        discord_notifier_client = DiscordRunNotifier(bot_token=config.integrations.discord_bot_token)
```

Then pass them to the `Executor`:

```python
    executor = Executor(
        config=config.execution,
        budget=budget,
        history=history,
        notifier=notifier,
        data_dir=data_dir,
        on_stream_event=broadcast_event,
        linear_client=linear_client,
        discord_notifier=discord_notifier_client,
    )
```

- [ ] **Step 4: Run test — verify PASS**

Run: `uv run python -m pytest tests/test_main.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/main.py tests/test_main.py
git commit -m "feat(main): wire LinearClient and DiscordRunNotifier into create_app"
```

---

### Task 14: Add agent issue detection path in Linear webhook handler

**Files:**
- Modify: `src/agents/main.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_main.py — add

@pytest.mark.asyncio
async def test_linear_webhook_detects_agent_issue(tmp_path):
    """When a Linear webhook arrives with an agent-labeled issue, it should be detected."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
budget:
  daily_limit_usd: 10.00
  warning_threshold_usd: 7.00
  pause_on_limit: true
notifications:
  slack_webhook_url: ""
webhooks:
  github_secret: ""
  linear_secret: ""
execution:
  worktree_base: /tmp/test-agents
  dry_run: true
server:
  host: 127.0.0.1
  port: 9090
integrations:
  linear_api_key: "test-key"
  discord_bot_token: "test-token"
""")
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    (projects_dir / "testproj.yaml").write_text("""
name: testproj
repo: /tmp/test-repo
linear_team_id: team-xyz
discord_channel_id: chan-123
tasks:
  issue-resolver:
    description: "Resolve Linear issues"
    prompt: "Resolve {{issue_title}}"
    trigger:
      type: linear
      events: [Issue.create]
      filter:
        label: agent
""")
    from agents.main import create_app
    from httpx import ASGITransport, AsyncClient

    app = create_app(config_path=config_file, projects_dir=projects_dir, data_dir=tmp_path / "data")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/webhooks/linear", json={
            "action": "create",
            "type": "Issue",
            "data": {
                "id": "issue-new-1",
                "identifier": "TST-1",
                "title": "Test issue",
                "description": "Test description",
                "teamId": "team-xyz",
                "labels": [{"name": "agent"}],
            },
        })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processed"
```

- [ ] **Step 2: Run test — verify FAIL**

Run: `uv run python -m pytest tests/test_main.py::test_linear_webhook_detects_agent_issue -v`
Expected: FAIL (or 401 due to signature) — agent detection path not implemented

Note: This test may need to account for Linear webhook signature verification. If the test fails with 401, add `state.linear_secret = ""` or provide correct signature. The existing test fixture already sets `linear_secret: ""` which bypasses verification.

- [ ] **Step 3: Implement**

In `src/agents/main.py`, modify the `linear_webhook` handler. After the existing `match_linear_event` loop, add:

```python
    # Agent issue detection
    from agents.webhooks.linear import match_agent_issue, extract_agent_issue_variables

    if match_agent_issue(payload):
        variables = extract_agent_issue_variables(payload)
        team_id = variables.get("team_id", "")
        for project in state.projects.values():
            if project.linear_team_id == team_id and "issue-resolver" in project.tasks:
                # Deduplication check
                existing = state.history.find_run_by_issue_id(variables["issue_id"])
                if existing and existing.status in ("running", "success"):
                    logger.info("Skipping agent issue %s — already %s", variables["issue_id"], existing.status)
                    break

                async def _run_agent(
                    p: ProjectConfig = project,
                    v: dict[str, str] = variables,
                ) -> None:
                    async with (
                        state.get_semaphore(config.execution.max_concurrent),
                        state.get_repo_semaphore(p.repo),
                    ):
                        await state.executor.run_task(p, "issue-resolver", trigger_type="linear", variables=v)

                background_tasks.add_task(_run_agent)
                break
```

- [ ] **Step 4: Run test — verify PASS**

Run: `uv run python -m pytest tests/test_main.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run python -m pytest --tb=short`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/agents/main.py tests/test_main.py
git commit -m "feat(main): add agent issue detection path in Linear webhook with deduplication"
```

---

## Chunk 7: Project YAML Updates & Subagents

### Task 15: Update project YAMLs with `linear_team_id`, `discord_channel_id`, and `issue-resolver` task

**Files:**
- Modify: `projects/sekit.yaml` (example — repeat for each project)

- [ ] **Step 1: Add fields to one project YAML as template**

Update `projects/sekit.yaml`:

```yaml
name: sekit
repo: /Users/vini/Developer/sekit
base_branch: main
branch_prefix: agents/
notify: slack
linear_team_id: ""       # TODO: fill with actual Linear team ID
discord_channel_id: ""   # TODO: fill with actual Discord #dev channel ID

tasks:
  # ... existing tasks unchanged ...

  issue-resolver:
    description: "Resolve a Linear issue autonomously end-to-end"
    intent: "Implement the given Linear issue following devflow: TDD, lint, tests, PR"
    trigger:
      type: linear
      events: [Issue.create, Issue.update]
      filter:
        label: agent
    prompt: |
      You are an autonomous software agent. Resolve the following Linear issue.

      Issue: {{issue_identifier}} — {{issue_title}}
      Description:
      {{issue_description}}

      Instructions:
      - Follow CLAUDE.md exactly. Work autonomously — do not wait for user approval.
      - Make all decisions yourself and document them in commit messages.
      - Follow TDD: write failing tests first, then implement, then verify.
      - Run lint and the full test suite before creating the PR.
      - Before starting, read {{progress_file_path}} if it exists — it contains context from previous attempts.
      - If you cannot complete the task, write a clear explanation to {{progress_file_path}}.
      - Use the issue-analyzer subagent first to understand the codebase, then implement, then use issue-reviewer before creating the PR.
    model: claude-sonnet-4-6
    max_cost_usd: 2.00
    autonomy: pr-only
```

- [ ] **Step 2: Repeat for all project YAMLs**

Copy the `issue-resolver` task + `linear_team_id` + `discord_channel_id` fields to: `jarvis.yaml`, `momease.yaml`, `devscout.yaml`, `primeleague.yaml`, `fintech.yaml`

- [ ] **Step 3: Verify all YAMLs load correctly**

Run: `uv run python -c "from agents.config import load_project_configs; from pathlib import Path; p = load_project_configs(Path('projects')); print(f'{len(p)} projects loaded'); [print(f'  {k}: {list(v.tasks.keys())}') for k,v in p.items()]"`
Expected: All 6 projects load, each showing `issue-resolver` in task list

- [ ] **Step 4: Commit**

```bash
git add projects/*.yaml
git commit -m "feat(projects): add issue-resolver task and linear_team_id/discord_channel_id to all projects"
```

---

### Task 16: Create Claude Code subagents

**Files:**
- Create: `.claude/agents/issue-analyzer.md`
- Create: `.claude/agents/issue-reviewer.md`

Note: These files live in THIS repo (`agents`). For the subagents to be available in PROJECT repos (sekit, jarvis, etc.), they must be copied to each repo's `.claude/agents/` directory. That's a manual step per repo or can be automated later.

- [ ] **Step 1: Create issue-analyzer subagent**

```markdown
---
name: issue-analyzer
description: Analyze codebase to understand patterns and prepare implementation context for the issue-resolver agent
tools: [Read, Glob, Grep, Bash]
---

You are analyzing a codebase to prepare context for implementing a Linear issue.

Your job:
1. Read the project structure and identify relevant files for the given task
2. Understand existing test patterns and conventions
3. Identify related code that might be affected by changes
4. Check for any existing implementations of similar features

Return a structured summary:
- **Relevant files**: list of files that will need changes
- **Test patterns**: how tests are organized, what frameworks are used
- **Related code**: code that interacts with the areas being changed
- **Conventions**: naming patterns, code style, architectural patterns observed
```

- [ ] **Step 2: Create issue-reviewer subagent**

```markdown
---
name: issue-reviewer
description: Review implementation for quality, correctness, and devflow compliance before creating a PR
tools: [Read, Glob, Grep, Bash]
---

You are reviewing changes made to resolve a Linear issue, before a PR is created.

Your job:
1. Run the full test suite and lint — report any failures
2. Check for regressions in existing functionality
3. Verify TDD was followed (tests exist for all new behavior)
4. Check code quality: naming, patterns match the existing codebase
5. Verify no TODO comments were left without issue references

Return either:
- **APPROVED** — all checks pass, ready for PR
- **ISSUES** — list of specific problems to fix, with file paths and line numbers
```

- [ ] **Step 3: Create security hooks config**

Create `.claude/settings.json` (for this repo — copy to project repos):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "command": "echo \"$TOOL_INPUT\" | grep -qE '(rm -rf|git push --force|git reset --hard|DROP TABLE|git clean -fd)' && echo 'BLOCKED: destructive command in autonomous mode' && exit 1 || exit 0"
      }
    ]
  }
}
```

- [ ] **Step 4: Commit**

```bash
git add .claude/agents/issue-analyzer.md .claude/agents/issue-reviewer.md .claude/settings.json
git commit -m "feat: add Claude Code subagents (analyzer + reviewer) and security hooks"
```

---

## Chunk 8: Executor Orchestration (the wiring)

This is the most critical chunk — it connects all the pieces together inside `run_task()`.

### Task 17: Modify `generate_run_id` to embed `issue_id` for deduplication

**Files:**
- Modify: `src/agents/executor.py:28-31`
- Modify: `tests/test_executor.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_executor.py — add

def test_generate_run_id_includes_issue_id():
    from agents.executor import generate_run_id

    run_id = generate_run_id("sekit", "issue-resolver", issue_id="issue-abc-123")
    assert "issue-abc-123" in run_id
    assert "sekit" in run_id
    assert "issue-resolver" in run_id


def test_generate_run_id_works_without_issue_id():
    from agents.executor import generate_run_id

    run_id = generate_run_id("sekit", "dep-update")
    assert "sekit" in run_id
    assert "dep-update" in run_id
```

- [ ] **Step 2: Run tests — verify FAIL**

Run: `uv run python -m pytest tests/test_executor.py::test_generate_run_id_includes_issue_id -v`
Expected: FAIL — `generate_run_id` doesn't accept `issue_id`

- [ ] **Step 3: Implement**

Modify `generate_run_id` in `src/agents/executor.py`:

```python
def generate_run_id(project: str, task: str, issue_id: str = "") -> str:
    short_uuid = uuid.uuid4().hex[:8]
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    parts = [project, task]
    if issue_id:
        parts.append(issue_id)
    parts.extend([timestamp, short_uuid])
    return "-".join(parts)
```

- [ ] **Step 4: Run tests — verify PASS**

Run: `uv run python -m pytest tests/test_executor.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/executor.py tests/test_executor.py
git commit -m "feat(executor): embed issue_id in run_id for deduplication"
```

---

### Task 18: Add agent orchestration to `run_task` — Linear/Discord lifecycle + retry loop

This is the largest task. It modifies `run_task()` to call Linear/Discord at each lifecycle point and adds the retry loop.

**Files:**
- Modify: `src/agents/executor.py`
- Modify: `tests/test_executor.py`

- [ ] **Step 1: Write failing test for agent issue dry run**

```python
# tests/test_executor.py — add

@pytest.mark.asyncio
async def test_run_task_agent_issue_calls_linear_and_discord_on_dry_run(tmp_path):
    from unittest.mock import AsyncMock, MagicMock
    from agents.config import ExecutionConfig
    from agents.executor import Executor
    from agents.history import HistoryDB
    from agents.models import ProjectConfig, TaskConfig, TriggerConfig

    history = HistoryDB(tmp_path / "test.db")
    budget = MagicMock()
    budget.can_afford.return_value = True
    budget.get_status.return_value = MagicMock(is_warning=False)

    mock_linear = AsyncMock()
    mock_discord = AsyncMock()
    mock_discord.create_run_message.return_value = "msg-123"

    executor = Executor(
        config=ExecutionConfig(dry_run=True),
        budget=budget,
        history=history,
        notifier=AsyncMock(),
        data_dir=tmp_path,
        linear_client=mock_linear,
        discord_notifier=mock_discord,
    )

    project = ProjectConfig(
        name="testproj",
        repo="/tmp/repo",
        linear_team_id="team-1",
        discord_channel_id="chan-1",
        tasks={
            "issue-resolver": TaskConfig(
                description="Resolve issues",
                prompt="Resolve {{issue_title}}",
                trigger=TriggerConfig(type="linear", events=["Issue.create"]),
            )
        },
    )

    variables = {
        "issue_id": "issue-xyz",
        "issue_identifier": "TST-1",
        "issue_title": "Test issue",
        "issue_description": "Test description",
        "team_id": "team-1",
    }

    run = await executor.run_task(project, "issue-resolver", trigger_type="linear", variables=variables)

    # Linear should have been notified
    mock_linear.update_status.assert_called()
    mock_linear.post_comment.assert_called()
    # Discord should have been notified
    mock_discord.create_run_message.assert_called_once_with("chan-1", "TST-1", "Test issue")
    mock_discord.finalize_run_message.assert_called_once()
    # Remove label on success
    mock_linear.remove_label.assert_called_once_with("issue-xyz", "agent")
```

- [ ] **Step 2: Run test — verify FAIL**

Run: `uv run python -m pytest tests/test_executor.py::test_run_task_agent_issue_calls_linear_and_discord_on_dry_run -v`
Expected: FAIL — `run_task` doesn't call Linear/Discord

- [ ] **Step 3: Implement the orchestration in `run_task`**

Modify `run_task()` in `src/agents/executor.py`. The key changes:

1. At the start of `run_task`, detect if this is an agent issue run (check `variables` for `issue_id`)
2. If agent issue: update Linear status, create Discord message, pass `issue_id` to `generate_run_id`
3. On dry_run success: call Discord finalize + Linear comment + remove label
4. On real success: same + Linear "In Review" status
5. On failure: call Discord fail + Linear comment

```python
    async def run_task(
        self,
        project: ProjectConfig,
        task_name: str,
        trigger_type: str = "manual",
        variables: dict[str, str] | None = None,
    ) -> RunRecord:
        task = project.tasks[task_name]
        variables = variables or {}
        issue_id = variables.get("issue_id", "")
        is_agent_issue = bool(issue_id and self.linear_client)

        run_id = generate_run_id(project.name, task_name, issue_id=issue_id)
        run = RunRecord(
            id=run_id,
            project=project.name,
            task=task_name,
            trigger_type=TriggerType(trigger_type),
            started_at=datetime.now(UTC),
            status=RunStatus.RUNNING,
            model=task.model,
        )
        self.history.insert_run(run)
        await self._emit(run_id, "task_started", f"{project.name}/{task_name} [{trigger_type}]")

        # Agent issue: notify Linear + Discord
        discord_msg_id = ""
        if is_agent_issue:
            team_id = variables.get("team_id", "")
            identifier = variables.get("issue_identifier", "")
            title = variables.get("issue_title", "")
            try:
                await self.linear_client.update_status(issue_id, team_id, "In Progress")
                await self.linear_client.post_comment(issue_id, "🤖 Agente iniciou execução")
            except Exception:
                logger.warning("Failed to update Linear for %s", issue_id)
            if self.discord_notifier and project.discord_channel_id:
                try:
                    discord_msg_id = await self.discord_notifier.create_run_message(
                        project.discord_channel_id, identifier, title,
                    )
                except Exception:
                    logger.warning("Failed to create Discord message for %s", issue_id)

        # ... budget check (existing, unchanged) ...

        if not self.budget.can_afford(task.max_cost_usd):
            # ... existing budget exceeded logic ...
            return run

        if self.config.dry_run:
            logger.info("DRY RUN: would execute %s/%s", project.name, task_name)
            await self._emit(run_id, "dry_run", "dry_run=true — skipping Claude execution")
            run.status = RunStatus.SUCCESS
            run.cost_usd = 0.0
            run.finished_at = datetime.now(UTC)
            self.history.update_run(run_id=run.id, status=run.status, finished_at=run.finished_at, cost_usd=0.0)
            await self._emit(run_id, "task_completed", "done (dry run)")

            # Agent issue: finalize notifications
            if is_agent_issue:
                await self._finalize_agent_success(project, variables, discord_msg_id, run)
            return run

        # ... real execution (existing logic, enhanced with retry + agent calls) ...
```

Add helper methods:

```python
    async def _finalize_agent_success(
        self, project: ProjectConfig, variables: dict[str, str],
        discord_msg_id: str, run: RunRecord,
    ) -> None:
        issue_id = variables.get("issue_id", "")
        team_id = variables.get("team_id", "")
        identifier = variables.get("issue_identifier", "")
        title = variables.get("issue_title", "")
        try:
            comment = f"✅ PR criado: {run.pr_url}" if run.pr_url else "✅ Concluído (sem alterações)"
            await self.linear_client.post_comment(issue_id, comment)
            if run.pr_url:
                await self.linear_client.update_status(issue_id, team_id, "In Review")
            await self.linear_client.remove_label(issue_id, "agent")
        except Exception:
            logger.warning("Failed to finalize Linear for %s", issue_id)
        if self.discord_notifier and discord_msg_id and project.discord_channel_id:
            try:
                duration_s = (run.finished_at - run.started_at).total_seconds() if run.finished_at else 0
                await self.discord_notifier.finalize_run_message(
                    project.discord_channel_id, discord_msg_id, identifier, title, [],
                    pr_url=run.pr_url, cost=run.cost_usd or 0.0, duration_s=duration_s,
                )
            except Exception:
                logger.warning("Failed to finalize Discord for %s", issue_id)

    async def _fail_agent_run(
        self, project: ProjectConfig, variables: dict[str, str],
        discord_msg_id: str, run: RunRecord, attempt: int, max_attempts: int,
    ) -> None:
        issue_id = variables.get("issue_id", "")
        team_id = variables.get("team_id", "")
        identifier = variables.get("issue_identifier", "")
        title = variables.get("issue_title", "")
        try:
            await self.linear_client.post_comment(issue_id, f"❌ Falha após {max_attempts} tentativas:\n{run.error_message or 'Unknown error'}")
            await self.linear_client.update_status(issue_id, team_id, "Todo")
        except Exception:
            logger.warning("Failed to report failure to Linear for %s", issue_id)
        if self.discord_notifier and discord_msg_id and project.discord_channel_id:
            try:
                duration_s = (run.finished_at - run.started_at).total_seconds() if run.finished_at else 0
                await self.discord_notifier.fail_run_message(
                    project.discord_channel_id, discord_msg_id, identifier, title, [],
                    error=run.error_message or "", attempt=attempt, max_attempts=max_attempts,
                    cost=run.cost_usd or 0.0, duration_s=duration_s,
                )
            except Exception:
                logger.warning("Failed to report failure to Discord for %s", issue_id)
```

- [ ] **Step 4: Run test — verify PASS**

Run: `uv run python -m pytest tests/test_executor.py::test_run_task_agent_issue_calls_linear_and_discord_on_dry_run -v`
Expected: PASS

- [ ] **Step 5: Run full test suite — verify no regressions**

Run: `uv run python -m pytest --tb=short`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/agents/executor.py tests/test_executor.py
git commit -m "feat(executor): add Linear/Discord orchestration and retry support for agent issues"
```

---

### Task 19: Final verification and full test suite

- [ ] **Step 1: Run complete test suite**

Run: `uv run python -m pytest --tb=short -v`
Expected: ALL PASS

- [ ] **Step 2: Verify server starts**

Run: `uv run agents &` and check `curl http://localhost:8080/health`
Expected: `{"status":"ok"}`

- [ ] **Step 3: Verify project configs load**

Run: `curl http://localhost:8080/status | python -m json.tool | head -20`
Expected: All projects listed with `issue-resolver` task

- [ ] **Step 4: Final commit (if any remaining changes)**

```bash
git status
# If any remaining changes:
git add -A && git commit -m "chore: finalize autonomous linear agent implementation"
```

---

## Summary

| Chunk | Tasks | What it builds |
|---|---|---|
| 1 | 1-2 | Model + config foundation (`linear_team_id`, `discord_channel_id`, integration keys) |
| 2 | 3-5 | `LinearClient`: fetch_issue, post_comment, update_status, remove_label |
| 3 | 6-8 | `DiscordRunNotifier`: create, update (rate limited), finalize, fail messages |
| 4 | 9-10 | Webhook detection (`match_agent_issue`) + deduplication (`find_run_by_issue_id`) |
| 5 | 11-12 | Executor: optional clients + progress log helpers |
| 6 | 13-14 | Main app: wire clients + agent webhook path with deduplication |
| 7 | 15-16 | Project YAMLs + subagents + security hooks |
| 8 | 17-18 | Executor orchestration: `generate_run_id` with issue_id + Linear/Discord lifecycle + retry loop + remove_label |
| — | 19 | Final verification |

**Total:** 19 tasks, ~95 steps, estimated 2-2.5 hours of implementation time.

**Not included in this plan (separate work):**
- Paypalmafia TypeScript change (add checkbox to `/task` modal) — separate repo, separate plan
- Filling in actual `linear_team_id` and `discord_channel_id` values per project — requires looking up Linear team IDs and Discord channel IDs
- Deploying to production and testing with real Linear webhooks
