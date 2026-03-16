# Autonomous Linear Agent — Design Spec

**Date:** 2026-03-16
**Status:** Approved for implementation
**Projects involved:** `agents` (Agent Runner) + `Paypalmafia` (Discord bot)

---

## 1. Overview

Build a fully autonomous loop where a developer creates a Linear issue from Discord, marks it for the agent, and the agent implements it end-to-end: reads the issue, writes code following the devflow (TDD, lint, review), creates a PR, updates Linear, and posts live progress to Discord — with zero friction after the initial task creation.

---

## 2. User Flow

```
Developer → /task modal in Discord (checkbox "resolver automaticamente")
    ↓
Paypalmafia creates Linear issue + adds label "agent"
    ↓  Linear webhook
Agent Runner detects label "agent" + maps team_id → project
    ↓
Fetches full issue via Linear API → builds dynamic prompt
Updates Linear status to "In Progress"
    ↓
Claude Code executes in isolated worktree (follows CLAUDE.md devflow)
    ↓  every tool use
Discord #dev channel message edited live (tool-by-tool)
    ↓
PR created → Linear comment + status → "In Review"
    ↓  on failure
Retry up to 3x (reads progress file between retries)
After 3 failures → Discord notification + Linear comment with error + status back to "Todo"
```

---

## 3. Architecture

### 3.1 Trigger — Paypalmafia (TypeScript, minimal change)

**File:** `src/modules/linear/index.ts`

- Add checkbox **"Resolver automaticamente com agente"** to the `/task` modal
- When checked: after creating the Linear issue, add label `agent` via Linear SDK
- No other changes — Paypalmafia has no knowledge of Agent Runner

### 3.2 Webhook Detection — Agent Runner

**File:** `src/agents/webhooks/linear.py` (enhance existing)

New function `match_agent_issue(payload: dict) -> bool`:
- Returns `True` when `payload["action"] == "create"` or `"update"` AND the issue has label `"agent"`
- Checks `payload.get("data", {}).get("labelIds", [])` or `labels[].name == "agent"`

New function `extract_agent_issue_variables(payload: dict) -> dict`:
- Returns: `issue_id`, `issue_identifier` (e.g. "SEK-147"), `issue_title`, `issue_description`, `team_id`
- Paths: `data.id`, `data.identifier`, `data.title`, `data.description`, `data.teamId`

**In `main.py`** — separate code path in the Linear webhook handler:
```python
# After existing match_linear_event loop:
if match_agent_issue(payload):
    variables = extract_agent_issue_variables(payload)
    team_id = variables["team_id"]
    # Find project with matching linear_team_id
    for project in state.projects.values():
        if project.linear_team_id == team_id:
            background_tasks.add_task(_run_agent_issue, project, variables)
            break
```

The `_run_agent_issue` coroutine calls `executor.run_task(project, "issue-resolver", trigger_type="linear", variables=variables)`.

### 3.3 Linear API Client — new module

**File:** `src/agents/linear_client.py`

```python
class LinearClient:
    def __init__(self, api_key: str) -> None: ...

    async def fetch_issue(self, issue_id: str) -> dict:
        """Returns: id, identifier, title, description, state name, labels"""

    async def post_comment(self, issue_id: str, body: str) -> None:
        """Post a comment on the issue timeline"""

    async def update_status(self, issue_id: str, team_id: str, target_state_name: str) -> None:
        """
        Fetches team workflow states once (cached per team_id).
        Finds state by name (case-insensitive).
        Logs warning and no-ops if state not found instead of raising.
        """

    async def _get_team_states(self, team_id: str) -> dict[str, str]:
        """Returns {state_name_lower: state_id}. Cached per team_id."""
```

Uses `httpx.AsyncClient` against Linear GraphQL API (`https://api.linear.app/graphql`).
`LINEAR_API_KEY` loaded from environment.
State name resolution is cached per team to avoid repeated API calls.

### 3.4 Discord Notifier — new module

**File:** `src/agents/discord_notifier.py`

Uses **Discord REST API with Bot token** (not webhook URLs — webhook URLs don't support message editing).

```python
class DiscordRunNotifier:
    def __init__(self, bot_token: str) -> None: ...

    async def create_run_message(self, channel_id: str, identifier: str, title: str) -> str:
        """POST /channels/{channel_id}/messages → returns message_id"""

    async def update_run_message(self, channel_id: str, message_id: str, events: list[dict]) -> None:
        """PATCH /channels/{channel_id}/messages/{message_id} — edits embed with accumulated events"""

    async def finalize_run_message(self, channel_id: str, message_id: str, pr_url: str | None, cost: float, duration_s: float) -> None:
        """Final edit marking run as completed"""

    async def fail_run_message(self, channel_id: str, message_id: str, error: str, attempt: int, max_attempts: int) -> None:
        """Final edit marking run as failed with error summary"""
```

Message format: single embed, green left border while running → green on success, red on failure.
One line per tool use event (`Read`, `Edit`, `Bash`, etc.) with timestamp prefix.
Footer: elapsed time + `$X.XX / $Y.YY`.
`DISCORD_BOT_TOKEN` loaded from environment (same credential as Paypalmafia, must be added to Agent Runner's `.env` separately).

### 3.5 Executor — enhancements

**File:** `src/agents/executor.py`

**Constructor additions:**
```python
def __init__(
    self,
    ...
    linear_client: LinearClient | None = None,
    discord_notifier: DiscordRunNotifier | None = None,
) -> None:
```

Both are optional to maintain backward compatibility with existing tests.

**`run_task()` additions (when `linear_client` is set and `variables` contains `issue_id`):**

1. After task starts → `linear_client.update_status(issue_id, team_id, "In Progress")` + `post_comment("🤖 Agente iniciou execução")`
2. Discord message created → `discord_notifier.create_run_message(channel_id, identifier, title)` → store `message_id`
3. On each stream event → `discord_notifier.update_run_message(channel_id, message_id, accumulated_events)`
4. After `_create_pr()` returns `pr_url` → `linear_client.post_comment(f"✅ PR criado: {pr_url}")` + `update_status("In Review")` + `discord_notifier.finalize_run_message(...)`
5. On failure after max retries → `linear_client.post_comment(error_summary)` + `update_status("Todo")` + `discord_notifier.fail_run_message(...)`

**Retry loop (inside `run_task()`):**
```python
max_attempts = variables.get("max_attempts", 3)
for attempt in range(1, max_attempts + 1):
    try:
        # existing execution logic
        return run  # success — exit retry loop
    except (TimeoutError, Exception) as e:
        _append_progress_log(issue_id, attempt, error=str(e))
        if attempt == max_attempts:
            # handle final failure
            break
        await asyncio.sleep(5 * attempt)  # backoff: 5s, 10s
```

**Progress log — persists between retries:**
- Location: `data_dir/progress/{issue_id}.txt` (NOT in worktree — worktree is deleted on each retry)
- Written before each attempt: issue context + attempt number
- Appended after each failure: what was tried + error
- Prompt template references: `"Read {progress_file_path} if it exists before starting."`
- Deleted on final success

### 3.6 `issue-resolver` Task Config

**Problem:** `TaskConfig` validator requires either `schedule` OR `trigger`. The `issue-resolver` task is triggered programmatically (not by schedule or standard trigger matching).

**Solution:** Add `trigger` block with `type: linear` and a `filter` for the `agent` label. This satisfies the validator while the webhook handler also matches it independently. For safety, the webhook handler's `match_agent_issue()` is the authoritative filter — the task config trigger is a documentation marker.

```yaml
tasks:
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
      - Before starting, read {{progress_file_path}} if it exists — it contains context
        from previous attempts on this issue.
      - If you cannot complete the task, write a clear explanation to {{progress_file_path}}.
    model: claude-sonnet-4-6
    max_cost_usd: 2.00
    autonomy: pr-only  # existing TaskConfig field (default "pr-only") — agent creates PR, human merges
```

### 3.7 Project Config — additions

**File:** `src/agents/config.py` + project YAMLs

New optional fields in `ProjectConfig`:
```python
linear_team_id: str = ""        # Linear team ID → routes webhooks to this project
discord_channel_id: str = ""    # Discord channel ID for live run updates (project's #dev channel)
```

Both default to empty string — existing projects without these fields continue to work.

### 3.8 Devflow Integration

The agent inherits the full devflow automatically:
- `CLAUDE.md` (global `~/.claude/CLAUDE.md` + per-repo) is read by `claude -p` on every invocation
- Global skills (`~/.claude/skills/`) are available: `superpowers:verification-before-completion`, `pr-review-toolkit:code-reviewer`
- The `issue-resolver` prompt explicitly instructs: *"follow CLAUDE.md, work autonomously, do not wait for user approval"*
- TDD cycle (RED → GREEN → REFACTOR → COMMIT) runs internally
- Before creating the PR, agent runs verification (lint + tests) as defined in CLAUDE.md

---

## 4. Data Flow

```
POST /webhooks/linear
    → main.py: existing match_linear_event loop (unchanged)
    → main.py: NEW — match_agent_issue(payload) check
        → extract_agent_issue_variables() → {issue_id, identifier, title, description, team_id}
        → find project where project.linear_team_id == team_id
        → background_tasks.add_task(_run_agent_issue, project, variables)

_run_agent_issue:
    → executor.run_task(project, "issue-resolver", trigger_type="linear", variables)
        → if not variables.get("issue_description"): call linear_client.fetch_issue(issue_id) and update variables
          [condition: description is None or empty string — Linear sends null for issues with no body]
        → channel_id = project.discord_channel_id  [source: ProjectConfig.discord_channel_id]
        → discord_notifier.create_run_message(channel_id, identifier, title)
        → linear_client.update_status(issue_id, team_id, "In Progress")
        → linear_client.post_comment("🤖 Agente iniciou execução")
        → write data_dir/progress/{issue_id}.txt
        → [retry loop, attempt 1..3]
            → worktree_path = data_dir/worktrees/{issue_id}-attempt-{attempt}
              [unique path per attempt — avoids "already exists" on retry]
            → git worktree add worktree_path -b {branch}-attempt-{attempt}
            → claude -p [prompt] --output-format stream-json
                → stream events → discord_notifier.update_run_message() [live]
                → stream events → dashboard broadcast [existing]
            → _create_pr() → pr_url
            → on success:
                → linear_client.post_comment(f"✅ PR: {pr_url}")
                → linear_client.update_status("In Review")
                → discord_notifier.finalize_run_message(pr_url, cost, duration)
                → delete progress file
                → return
            → on failure:
                → git worktree remove --force worktree_path  [cleanup before next attempt]
                → append to progress file
                → if attempt < 3: sleep(5 * attempt), continue
                → if attempt == 3:
                    → linear_client.post_comment(error_summary)
                    → linear_client.update_status("Todo")
                    → discord_notifier.fail_run_message(error, 3, 3)
```

---

## 5. Webhook Deduplication

Linear delivers webhooks with "at least once" guarantee. Editing an issue (e.g., adding more description) fires a new `IssueUpdate` event with the `agent` label still present. Without deduplication, this triggers a second run.

**Strategy:** Use `issue_id` as idempotency key. Before starting a new agent run:
1. Query `runs` table: `SELECT id, status FROM runs WHERE task = 'issue-resolver' AND id LIKE '%{issue_id}%' ORDER BY started_at DESC LIMIT 1`
2. If a run exists with `status = running` → skip (already in progress)
3. If a run exists with `status = success` → skip (already resolved)
4. If a run exists with `status = failure` → allow (re-attempt after manual fix)
5. If no run exists → start new run

The `run_id` format includes the `issue_id`: `{project}-issue-resolver-{issue_id}-{timestamp}-{uuid}`.

**Label removal after success:** After PR is created, remove the `agent` label from the issue via `linear_client.remove_label(issue_id, "agent")`. This prevents re-triggering on future issue edits and signals to the team that the agent has completed its work.

---

## 6. Discord Message Constraints

**Rate limiting:** Discord allows ~5 message edits per 5 seconds per channel. The `discord_notifier` must throttle edits to max 1 edit per 2 seconds. Accumulate events in a buffer and flush on the next tick.

```python
class DiscordRunNotifier:
    EDIT_INTERVAL_SECONDS = 2.0
    # Buffer events, flush every 2s via asyncio timer
```

**Message length:** Discord embed descriptions are capped at 4096 characters. The notifier keeps only the **last 40 tool-use events** in the embed body. When the list exceeds 40:
- Prepend `"... {N} earlier events omitted"` as the first line
- Drop the oldest events from the embed

This ensures the message is always readable and within limits.

---

## 7. Claude Code Subagents

Define specialized subagents in `.claude/agents/` within each project repo. The `issue-resolver` prompt instructs Claude to delegate to these subagents when available.

**`issue-analyzer.md`** — Reads the codebase to build context before implementation:
```markdown
---
name: issue-analyzer
description: Analyze codebase to understand patterns and prepare implementation context
tools: [Read, Glob, Grep, Bash]
---
Analyze the codebase to understand:
1. Relevant files and patterns for the given task
2. Existing test patterns and conventions
3. Any related code that might be affected
Return a structured summary of findings.
```

**`issue-reviewer.md`** — Reviews implementation before PR creation:
```markdown
---
name: issue-reviewer
description: Review implementation for quality, correctness, and devflow compliance
tools: [Read, Glob, Grep, Bash]
---
Review the changes made in this worktree:
1. Run the full test suite and lint
2. Check for regressions
3. Verify TDD was followed (tests exist for new behavior)
4. Check code quality and patterns match the codebase
Return APPROVED or ISSUES with specific fixes.
```

The main `issue-resolver` prompt delegates: *"Use the issue-analyzer subagent first to understand the codebase, then implement, then use issue-reviewer before creating the PR."*

---

## 8. Security Hooks

Configure Claude Code hooks to prevent destructive operations in autonomous mode. These go in the project's `.claude/settings.json` or CLAUDE.md:

**`PreToolUse:Bash`** — Block destructive commands:
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "command": "echo \"$TOOL_INPUT\" | grep -qE '(rm -rf|git push --force|git reset --hard|DROP TABLE|git clean -fd)' && echo 'BLOCKED: destructive command' && exit 1 || exit 0"
      }
    ]
  }
}
```

This prevents the agent from accidentally deleting files, force-pushing, or resetting git history — without restricting normal operations like running tests or building.

---

## 9. New Files

| File | Purpose |
|---|---|
| `src/agents/linear_client.py` | Linear GraphQL API: fetch issues, post comments, update/remove labels |
| `src/agents/discord_notifier.py` | Discord REST API: create/edit/finalize run messages with rate limiting |
| `tests/test_linear_client.py` | Unit tests (mocked httpx) |
| `tests/test_discord_notifier.py` | Unit tests (mocked httpx) |
| `.claude/agents/issue-analyzer.md` | Subagent: codebase analysis before implementation (per project repo) |
| `.claude/agents/issue-reviewer.md` | Subagent: review implementation before PR (per project repo) |

## 10. Modified Files

| File | Change |
|---|---|
| `src/agents/models.py` | Add `linear_team_id`, `discord_channel_id` to `ProjectConfig` |
| `src/agents/webhooks/linear.py` | Add `match_agent_issue()` + `extract_agent_issue_variables()` |
| `src/agents/executor.py` | Optional `linear_client` + `discord_notifier` constructor params; retry loop; progress log; deduplication check |
| `src/agents/main.py` | Add agent issue detection path in `/webhooks/linear` handler; deduplication |
| `projects/*.yaml` | Add `linear_team_id`, `discord_channel_id`, `issue-resolver` task |
| `src/modules/linear/index.ts` | Add checkbox to `/task` modal in Paypalmafia |

---

## 11. Environment Variables

| Variable | Where | Notes |
|---|---|---|
| `LINEAR_API_KEY` | Agent Runner `.env` | Same credential as Paypalmafia — must be added separately to Agent Runner's environment |
| `DISCORD_BOT_TOKEN` | Agent Runner `.env` | Same credential as Paypalmafia — must be added separately to Agent Runner's environment |

---

## 12. Error Handling

| Scenario | Behavior |
|---|---|
| Linear webhook received but no project matches `team_id` | Log warning, return 200 (ignore silently) |
| Duplicate webhook for same issue (already running/success) | Skip via deduplication check (Section 5) |
| Linear API unreachable on `fetch_issue` | Fail fast, notify Discord only (no Linear comment), retry |
| `update_status` called with unknown state name | Log warning, no-op (don't block execution) |
| Claude execution timeout | Count as failure, append to progress log, trigger retry |
| Tests fail after implementation | Count as failure, append to progress log, trigger retry |
| PR creation with no changes (`_create_pr` returns `None`) | Post "no changes needed" to Linear + Discord, mark as success, no retry |
| 3 retries exhausted | Post error summary to Linear + Discord, return issue to "Todo" |
| `discord_channel_id` not set in project config | Skip all Discord notifications, log warning |
| `linear_team_id` not set in project config | Project not eligible for agent issues |
| Discord rate limit hit (429) | Back off per `Retry-After` header, buffer events |
| Discord embed exceeds 4096 chars | Truncate oldest events, show "N earlier events omitted" |

---

## 13. Out of Scope

- Auto-merge of PRs (human reviews all — `autonomy: pr-only`)
- Picking up existing backlog issues without the `agent` label
- Modifying Paypalmafia's GitHub webhook flow (already handles PR → Linear transitions)
- Multi-repo issues (one issue = one repo = one project config)
- Issue assignment (agent does not assign itself to issues)
- Merge conflict resolution (human reviews PR — conflicts surfaced naturally)
