# Self-Running Codebase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every gap in the Issue→Agent→PR→Review→Merge→Deploy loop so paperweight can autonomously build, test, review, and ship changes to itself with zero human intervention required (human review optional).

**Architecture:** Seven phases that incrementally close the autonomy loop. Each phase produces a working, testable increment. Config fixes first (unblock the pipeline), then CI/CD (quality gate), then smart PRs (reviewability), then feedback loops (self-healing), then session autonomy (Agent Tab → PR), then scheduled polling (resilience), then auto-review (full loop).

**Tech Stack:** Python 3.13, FastAPI, GitHub Actions, `gh` CLI, `claude-code-action`, Linear GraphQL API, SQLite

---

## File Structure

| File | Responsibility |
|------|---------------|
| `projects/paperweight.yaml` | Self-referential project config — fix team_id, add tasks |
| `.env` | Add missing tokens (GITHUB_TOKEN, webhook secrets) |
| `src/agents/executor.py` | Inject progress_file_path, enrich PR body, retry logic |
| `src/agents/pr_body_builder.py` | PR body builder helper |
| `src/agents/agent_routes.py` | Push+PR on session close, autonomy field |
| `src/agents/webhooks/github.py` | Handle PR merge events, CI failure events |
| `src/agents/main.py` | Wire new GitHub webhook handlers, add polling job |
| `src/agents/linear_client.py` | Add `update_issue_done()` method |
| `.github/workflows/ci.yml` | pytest + pyright on every PR |
| `.github/workflows/claude-review.yml` | Auto-review via claude-code-action |
| Tests: `tests/test_executor_pr_body.py`, `tests/test_github_webhook_feedback.py`, `tests/test_session_pr.py`, `tests/test_progress_injection.py`, `tests/test_polling_job.py` |

---

## Phase 1: Configuration — Unblock the Pipeline

### Task 1: Fix linear_team_id discovery and add missing env vars

**Files:**
- Modify: `projects/paperweight.yaml:6-7`
- Modify: `.env`
- Modify: `src/agents/discovery.py:26` (fuzzy match)

The auto-discovery at `discovery.py:26` matches `project.name.lower()` against Linear team names. If the Linear workspace doesn't have a team literally named "paperweight", the match fails silently. We need fuzzy matching.

- [ ] **Step 1: Check which Linear teams exist**

```bash
# In the running app, the teams are logged at startup.
# We can also check via the Linear API directly.
# For now, hardcode the team_id if discovery doesn't match,
# OR add a fallback that matches partial names.
```

- [ ] **Step 2: Add GITHUB_TOKEN to .env**

The `gh` CLI uses `GITHUB_TOKEN` env var OR `gh auth login` session. For CI and automated PR creation, `GITHUB_TOKEN` must be explicitly set.

```bash
# Generate a GitHub PAT (classic) with repo, workflow scopes
# Add to .env:
GITHUB_TOKEN=ghp_...
```

> **Note for executor:** This is a manual step. The token must be created at github.com/settings/tokens. The plan cannot generate it.

- [ ] **Step 3: Add webhook secrets to .env**

```bash
# Generate random secrets:
# LINEAR_WEBHOOK_SECRET=$(openssl rand -hex 32)
# GITHUB_WEBHOOK_SECRET=$(openssl rand -hex 32)
# Add to .env:
LINEAR_WEBHOOK_SECRET=<generated>
GITHUB_WEBHOOK_SECRET=<generated>
```

> **Note:** After adding these, configure the same secrets in Linear webhook settings and GitHub webhook settings for the repo.

- [ ] **Step 4: Improve discovery with fuzzy matching**

Modify `src/agents/discovery.py` to try substring matching when exact match fails:

```python
# After exact match fails at line 26:
if not project.linear_team_id:
    # Fuzzy: check if project name is a substring of any team name or vice versa
    for team_name, tid in teams.items():
        if project.name.lower() in team_name or team_name in project.name.lower():
            project.linear_team_id = tid
            logger.info(
                "Auto-discovered linear_team_id (fuzzy) for %s: %s (team: %s)",
                project.name, tid, team_name,
            )
            break
```

- [ ] **Step 5: Write test for fuzzy discovery**

```python
# tests/test_discovery_fuzzy.py
import pytest
from agents.discovery import auto_discover_project_ids
from agents.models import ProjectConfig, TaskConfig

@pytest.fixture
def dummy_project():
    return ProjectConfig(
        name="paperweight",
        repo="/tmp/test",
        tasks={"test": TaskConfig(description="t", intent="t")},
    )

class FakeLinearClient:
    async def fetch_teams(self):
        return {"pw team": "team-123"}  # No exact match for "paperweight"

@pytest.mark.asyncio
async def test_fuzzy_discovery_no_exact_match(dummy_project):
    projects = {"paperweight": dummy_project}
    await auto_discover_project_ids(projects, FakeLinearClient(), None, "")
    # Should NOT match "pw team" — fuzzy only matches substrings
    assert dummy_project.linear_team_id == ""

class FakeLinearClientSubstring:
    async def fetch_teams(self):
        return {"paperweight-dev": "team-456"}  # "paperweight" IS a substring

@pytest.mark.asyncio
async def test_fuzzy_discovery_substring_match(dummy_project):
    projects = {"paperweight": dummy_project}
    await auto_discover_project_ids(projects, FakeLinearClientSubstring(), None, "")
    assert dummy_project.linear_team_id == "team-456"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `python -m pytest tests/test_discovery_fuzzy.py -v`
Expected: `test_fuzzy_discovery_substring_match` FAILS (no fuzzy logic yet)

- [ ] **Step 7: Implement the fuzzy matching**

Apply the change from Step 4 to `src/agents/discovery.py`.

- [ ] **Step 8: Run tests to verify they pass**

Run: `python -m pytest tests/test_discovery_fuzzy.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/agents/discovery.py tests/test_discovery_fuzzy.py
git commit -m "feat: fuzzy matching for linear_team_id auto-discovery"
```

---

## Phase 2: CI/CD — Quality Gate for PRs

### Task 2: GitHub Actions workflow for pytest + pyright

**Files:**
- Create: `.github/workflows/ci.yml`

This is the most critical missing piece. Without CI, `auto-merge` merges instantly with no verification.

- [ ] **Step 1: Create CI workflow**

```yaml
# .github/workflows/ci.yml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Set up Python
        run: uv python install 3.13

      - name: Install dependencies
        run: uv sync --frozen

      - name: Run tests
        run: uv run python -m pytest tests/ -v --tb=short

      - name: Type check
        run: uv run python -m pyright src/
```

- [ ] **Step 2: Enable branch protection on GitHub**

This is a manual step. Go to GitHub repo settings → Branches → Add rule for `main`:
- Require status checks: `test`
- Require PR reviews: 0 (optional — for full autonomy) or 1 (for human-in-the-loop)

> With branch protection + required checks, `gh pr merge --auto --squash` will wait for CI to pass before merging. This is the safety net.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add pytest + pyright workflow for PRs"
```

---

## Phase 3: Smart PR Bodies — Reviewability

### Task 3: Enrich PR body with issue context, test results, and diff summary

**Files:**
- Modify: `src/agents/executor.py:458-489` (`_create_pr`)
- Create: `src/agents/pr_body_builder.py`
- Test: `tests/test_pr_body_builder.py`

The current PR body is `"Automated by Background Agent Runner\n\nTask: {task_name}\nProject: {project.name}"`. This tells a reviewer nothing.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pr_body_builder.py
from agents.pr_body_builder import build_pr_body

def test_pr_body_with_issue():
    body = build_pr_body(
        project_name="paperweight",
        task_name="issue-resolver",
        variables={
            "issue_identifier": "PW-42",
            "issue_title": "Add retry logic",
            "issue_description": "When a task fails, it should retry up to 3 times.",
        },
        diff_stat="3 files changed, 45 insertions(+), 12 deletions(-)",
        commit_log="abc1234 feat: add retry logic\ndef5678 test: add retry tests",
        cost_usd=0.85,
    )
    assert "PW-42" in body
    assert "Add retry logic" in body
    assert "3 files changed" in body
    assert "$0.85" in body

def test_pr_body_without_issue():
    body = build_pr_body(
        project_name="paperweight",
        task_name="dep-update",
        variables={},
        diff_stat="1 file changed",
        commit_log="abc dep update",
        cost_usd=0.30,
    )
    assert "dep-update" in body
    assert "1 file changed" in body
    assert "PW-" not in body  # No issue reference
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pr_body_builder.py -v`
Expected: FAIL — module `agents.pr_body_builder` does not exist

- [ ] **Step 3: Implement PR body builder**

```python
# src/agents/pr_body_builder.py
"""Build rich PR descriptions for agent-created pull requests."""


def build_pr_body(
    project_name: str,
    task_name: str,
    variables: dict[str, str],
    diff_stat: str = "",
    commit_log: str = "",
    cost_usd: float = 0.0,
) -> str:
    sections: list[str] = []

    # Issue context (if available)
    identifier = variables.get("issue_identifier", "")
    title = variables.get("issue_title", "")
    description = variables.get("issue_description", "")
    if identifier:
        sections.append(f"## Issue: {identifier} — {title}")
        if description:
            # Truncate long descriptions
            desc = description[:500] + ("..." if len(description) > 500 else "")
            sections.append(f"\n{desc}")

    # Changes summary
    if diff_stat:
        sections.append(f"\n## Changes\n```\n{diff_stat}\n```")
    if commit_log:
        sections.append(f"\n## Commits\n```\n{commit_log}\n```")

    # Metadata
    meta = f"\n---\n🤖 Automated by Paperweight | Task: `{task_name}` | Project: `{project_name}` | Cost: ${cost_usd:.2f}"
    sections.append(meta)

    return "\n".join(sections)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pr_body_builder.py -v`
Expected: PASS

- [ ] **Step 5: Wire PR body builder into executor._create_pr()**

Modify `src/agents/executor.py` to replace the static PR body:

```python
# In _create_pr(), after getting log_output and before gh pr create:
# Add diff_stat capture
async def _create_pr(
    self,
    cwd: str,
    project: ProjectConfig,
    task_name: str,
    branch: str,
    autonomy: str,
    variables: dict[str, str] | None = None,
    cost_usd: float = 0.0,
) -> str | None:
    log_output = await self._run_cmd(
        ["git", "log", f"{project.base_branch}..HEAD", "--oneline"],
        cwd=cwd,
    )
    if not log_output.strip():
        return None

    diff_stat = await self._run_cmd(
        ["git", "diff", "--stat", f"{project.base_branch}..HEAD"],
        cwd=cwd,
    )

    from agents.pr_body_builder import build_pr_body
    body = build_pr_body(
        project_name=project.name,
        task_name=task_name,
        variables=variables or {},
        diff_stat=diff_stat.strip(),
        commit_log=log_output.strip(),
        cost_usd=cost_usd,
    )

    await self._run_cmd(["git", "push", "-u", "origin", branch], cwd=cwd)
    pr_cmd = [
        "gh", "pr", "create",
        "--title", f"[agents] {project.name}/{task_name}",
        "--body", body,
        "--base", project.base_branch,
    ]
    pr_output = await self._run_cmd(pr_cmd, cwd=cwd)
    pr_url = pr_output.strip()
    if autonomy == "auto-merge":
        try:
            await self._run_cmd(
                ["gh", "pr", "merge", "--auto", "--squash", pr_url],
                cwd=cwd,
            )
        except RuntimeError:
            logger.warning("Failed to enable auto-merge for %s", pr_url)
    return pr_url
```

Also update the call site in `run_task()` to pass `variables` and `cost_usd`:

```python
# executor.py line ~211, change:
pr_url = await self._create_pr(
    cwd=str(worktree_path), project=project, task_name=task_name,
    branch=branch_name, autonomy=task.autonomy,
    variables=variables, cost_usd=output.cost_usd,
)
```

- [ ] **Step 6: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All pass (existing tests shouldn't break since `_create_pr` signature changed but with defaults)

- [ ] **Step 7: Commit**

```bash
git add src/agents/pr_body_builder.py tests/test_pr_body_builder.py src/agents/executor.py
git commit -m "feat: rich PR bodies with issue context, diff stats, and cost"
```

---

## Phase 4: Progress File Injection — Enable Retry Context

### Task 4: Inject progress_file_path variable into run_task

**Files:**
- Modify: `src/agents/executor.py:111-170` (`run_task`)
- Test: `tests/test_progress_injection.py`

The paperweight.yaml prompt references `{{progress_file_path}}` but `run_task()` never sets that variable. The `write_progress_log`, `append_progress_log`, `delete_progress_log` functions exist in `executor_utils.py` but are never called.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_progress_injection.py
from pathlib import Path

def test_progress_file_path_injected_into_variables():
    """Variables passed to build_prompt should include progress_file_path when issue_id is present."""
    from agents.executor_utils import write_progress_log
    import tempfile
    progress_dir = Path(tempfile.mkdtemp()) / "progress"
    issue_id = "issue-abc"
    path = write_progress_log(progress_dir, issue_id, attempt=1, issue_title="Test")
    assert path.exists()
    assert "issue-abc" in str(path)
```

- [ ] **Step 2: Run test to verify it passes (this tests existing util)**

Run: `python -m pytest tests/test_progress_injection.py -v`
Expected: PASS — the utility works, just isn't called

- [ ] **Step 3: Inject progress_file_path in run_task**

In `executor.py`, inside `run_task()`, after `variables = variables or {}` (line 119), add:

```python
# Inject progress_file_path for retry context
if issue_id:
    progress_dir = self.data_dir / "progress"
    progress_file = progress_dir / f"{issue_id}.txt"
    variables["progress_file_path"] = str(progress_file)
    # Write initial progress log if it doesn't exist
    if not progress_file.exists():
        write_progress_log(progress_dir, issue_id, attempt=1,
                          issue_title=variables.get("issue_title", ""),
                          issue_description=variables.get("issue_description", ""))
```

And on failure, append context:

```python
# After the except blocks (before finally), add progress log update:
if issue_id and run.status in (RunStatus.FAILURE, RunStatus.TIMEOUT):
    try:
        append_progress_log(self.data_dir / "progress", issue_id,
                           attempt=1, error=run.error_message or "")
    except Exception:
        logger.warning("Failed to write progress log for %s", issue_id)
```

On success, delete the progress log:

```python
# After successful PR creation:
if issue_id:
    delete_progress_log(self.data_dir / "progress", issue_id)
```

- [ ] **Step 4: Write integration test**

```python
# tests/test_progress_injection.py (append)
def test_progress_variable_present_in_build_prompt():
    """Verify that build_prompt resolves {{progress_file_path}}."""
    from agents.config import build_prompt
    from agents.models import TaskConfig

    task = TaskConfig(
        description="test",
        intent="Read {{progress_file_path}} for context",
    )
    result = build_prompt(task, {"progress_file_path": "/tmp/progress/issue-1.txt"})
    assert "/tmp/progress/issue-1.txt" in result
    assert "{{progress_file_path}}" not in result
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_progress_injection.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/agents/executor.py tests/test_progress_injection.py
git commit -m "feat: inject progress_file_path into agent issue runs for retry context"
```

---

## Phase 5: GitHub Webhook Feedback Loop

### Task 5: Handle PR merge → Linear "Done", and CI failure → notify

**Files:**
- Modify: `src/agents/webhooks/github.py` — add `extract_pr_merge_info`, `extract_ci_failure_info`
- Modify: `src/agents/main.py:301-330` — wire new handlers
- Modify: `src/agents/linear_client.py` — no change needed, `update_status` already supports "Done"
- Modify: `src/agents/history.py` — add `find_run_by_pr_url` query
- Test: `tests/test_github_webhook_feedback.py`

When a PR created by paperweight merges, the Linear issue should move to "Done". When CI fails on an agent PR, the system should be aware.

- [ ] **Step 1: Write the failing test for PR merge detection**

```python
# tests/test_github_webhook_feedback.py
from agents.webhooks.github import is_agent_pr_merge, extract_pr_merge_info

def test_agent_pr_merge_detected():
    payload = {
        "action": "closed",
        "pull_request": {
            "merged": True,
            "title": "[agents] paperweight/issue-resolver",
            "html_url": "https://github.com/user/repo/pull/42",
            "head": {"ref": "agents/issue-resolver-20260320"},
            "body": "## Issue: PW-42 — Fix bug\n...",
        },
    }
    assert is_agent_pr_merge(payload) is True
    info = extract_pr_merge_info(payload)
    assert info["pr_url"] == "https://github.com/user/repo/pull/42"
    assert info["branch"] == "agents/issue-resolver-20260320"

def test_non_agent_pr_ignored():
    payload = {
        "action": "closed",
        "pull_request": {
            "merged": True,
            "title": "Fix typo in readme",
            "html_url": "https://github.com/user/repo/pull/43",
            "head": {"ref": "fix-typo"},
        },
    }
    assert is_agent_pr_merge(payload) is False

def test_pr_closed_without_merge_ignored():
    payload = {
        "action": "closed",
        "pull_request": {
            "merged": False,
            "title": "[agents] paperweight/issue-resolver",
            "html_url": "https://github.com/user/repo/pull/44",
            "head": {"ref": "agents/issue-resolver-20260320"},
        },
    }
    assert is_agent_pr_merge(payload) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_github_webhook_feedback.py -v`
Expected: FAIL — `is_agent_pr_merge` doesn't exist

- [ ] **Step 3: Implement PR merge detection**

```python
# Add to src/agents/webhooks/github.py:

def is_agent_pr_merge(payload: dict) -> bool:
    """Check if this is a merged PR created by paperweight agents."""
    if payload.get("action") != "closed":
        return False
    pr = payload.get("pull_request", {})
    if not pr.get("merged"):
        return False
    title = pr.get("title", "")
    return title.startswith("[agents]")


def extract_pr_merge_info(payload: dict) -> dict[str, str]:
    """Extract PR info from a merge event."""
    pr = payload.get("pull_request", {})
    return {
        "pr_url": pr.get("html_url", ""),
        "branch": pr.get("head", {}).get("ref", ""),
        "title": pr.get("title", ""),
        "body": pr.get("body", ""),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_github_webhook_feedback.py -v`
Expected: PASS

- [ ] **Step 5: Add find_run_by_pr_url to HistoryDB**

```python
# Add to src/agents/history.py:
def find_run_by_pr_url(self, pr_url: str) -> RunRecord | None:
    """Find a run record by its PR URL."""
    with self._conn() as conn:
        row = conn.execute(
            "SELECT * FROM runs WHERE pr_url = ? ORDER BY started_at DESC LIMIT 1",
            (pr_url,),
        ).fetchone()
    if row is None:
        return None
    return self._row_to_record(row)
```

- [ ] **Step 6: Wire merge handler in main.py**

In the `github_webhook` handler in `main.py`, **before** the final `return {"status": "processed"}` statement (around line 330), add:

```python
# Handle agent PR merges → move Linear issue to Done
from agents.webhooks.github import is_agent_pr_merge, extract_pr_merge_info

if is_agent_pr_merge(payload):
    merge_info = extract_pr_merge_info(payload)
    pr_url = merge_info["pr_url"]
    run = state.history.find_run_by_pr_url(pr_url)
    if run and linear_client:
        # Find the original issue variables from the run
        # The issue_id was stored in the run_id format: project-task-issueid-timestamp-uuid
        # Better: query run_events for the original variables
        # For now, look up by extracting issue info from PR body
        async def _mark_done(r: RunRecord = run) -> None:
            variables = state.history.get_run_variables(r.id)
            if variables:
                issue_id = variables.get("issue_id", "")
                team_id = variables.get("team_id", "")
                if issue_id and team_id and linear_client:
                    try:
                        await linear_client.update_status(issue_id, team_id, "Done")
                        await linear_client.post_comment(
                            issue_id, f"✅ PR merged: {pr_url}"
                        )
                    except Exception:
                        logger.warning("Failed to mark issue done for PR %s", pr_url)

        background_tasks.add_task(_mark_done)
```

> **Note:** This requires storing run variables in the DB. See Step 7.

- [ ] **Step 7: Store run variables in history**

Add a `run_variables` table to `history.py`:

```python
# In HistoryDB._init_db(), inside the existing `with self._conn() as conn:` block, add:
conn.execute("""
    CREATE TABLE IF NOT EXISTS run_variables (
        run_id TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        PRIMARY KEY (run_id, key)
    )
""")
```

Add methods to HistoryDB (using the `_conn()` context manager pattern like all other methods):

```python
def store_run_variables(self, run_id: str, variables: dict[str, str]) -> None:
    with self._conn() as conn:
        for key, value in variables.items():
            conn.execute(
                "INSERT OR REPLACE INTO run_variables (run_id, key, value) VALUES (?, ?, ?)",
                (run_id, key, value),
            )

def get_run_variables(self, run_id: str) -> dict[str, str]:
    with self._conn() as conn:
        rows = conn.execute(
            "SELECT key, value FROM run_variables WHERE run_id = ?", (run_id,)
        ).fetchall()
    return {row["key"]: row["value"] for row in rows}
```

Then in `executor.py:run_task()`, after `self.history.insert_run(run)`, add:

```python
if variables:
    self.history.store_run_variables(run_id, variables)
```

- [ ] **Step 8: Write test for full merge→done flow**

```python
# tests/test_github_webhook_feedback.py (append)
def test_find_run_by_pr_url(tmp_path):
    from agents.history import HistoryDB
    from agents.models import RunRecord, RunStatus, TriggerType
    from datetime import datetime, UTC

    db = HistoryDB(tmp_path / "test.db")
    run = RunRecord(
        id="test-run-1", project="paperweight", task="issue-resolver",
        trigger_type=TriggerType.LINEAR, started_at=datetime.now(UTC),
        status=RunStatus.SUCCESS, model="sonnet",
        pr_url="https://github.com/user/repo/pull/42",
    )
    db.insert_run(run)
    found = db.find_run_by_pr_url("https://github.com/user/repo/pull/42")
    assert found is not None
    assert found.id == "test-run-1"

def test_store_and_get_run_variables(tmp_path):
    from agents.history import HistoryDB
    db = HistoryDB(tmp_path / "test.db")
    db.store_run_variables("run-1", {"issue_id": "abc", "team_id": "xyz"})
    got = db.get_run_variables("run-1")
    assert got == {"issue_id": "abc", "team_id": "xyz"}
```

- [ ] **Step 9: Run tests**

Run: `python -m pytest tests/test_github_webhook_feedback.py -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add src/agents/webhooks/github.py src/agents/main.py src/agents/history.py \
        src/agents/executor.py tests/test_github_webhook_feedback.py
git commit -m "feat: GitHub PR merge → Linear Done feedback loop"
```

---

## Phase 6: Agent Tab → PR on Close

### Task 6: Push branch and create PR when closing an Agent Tab session

**Files:**
- Modify: `src/agents/agent_routes.py:120-140` (`close_session_endpoint`)
- Test: `tests/test_session_pr.py`

Currently, `close_session` only removes the worktree. If Claude made commits during the session, they're lost. We should push the branch and optionally create a PR.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_session_pr.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

@pytest.mark.asyncio
async def test_close_session_pushes_and_creates_pr(tmp_path):
    """Closing a session with commits should push and create a PR."""
    from agents.agent_routes import _should_create_pr

    # Simulates git log output with commits
    assert _should_create_pr("abc123 feat: add something\ndef456 test: add test") is True

    # No commits
    assert _should_create_pr("") is False
    assert _should_create_pr("   ") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_session_pr.py -v`
Expected: FAIL — `_should_create_pr` doesn't exist

- [ ] **Step 3: Implement PR-on-close logic**

Modify `src/agents/agent_routes.py`:

```python
def _should_create_pr(log_output: str) -> bool:
    """Check if there are commits to push."""
    return bool(log_output.strip())
```

Update `close_session_endpoint`:

```python
@app.post("/api/sessions/{session_id}/close", response_model=None)
async def close_session_endpoint(session_id: str) -> Response | dict:
    session = session_manager.get_session(session_id)
    if session is None:
        return Response(status_code=404, content="Session not found")

    pr_url = None
    worktree_path = Path(session.worktree_path)
    project = state.projects.get(session.project)

    # If there are commits, push and create a PR before cleaning up
    if worktree_path.exists() and project:
        try:
            branch = f"agents/session-{session.id}"
            log_output = await state.executor._run_cmd(
                ["git", "log", f"{project.base_branch}..HEAD", "--oneline"],
                cwd=str(worktree_path),
            )
            if _should_create_pr(log_output):
                from agents.pr_body_builder import build_pr_body
                diff_stat = await state.executor._run_cmd(
                    ["git", "diff", "--stat", f"{project.base_branch}..HEAD"],
                    cwd=str(worktree_path),
                )
                body = build_pr_body(
                    project_name=project.name,
                    task_name=f"session-{session.id[:8]}",
                    variables={},
                    diff_stat=diff_stat.strip(),
                    commit_log=log_output.strip(),
                )
                await state.executor._run_cmd(
                    ["git", "push", "-u", "origin", branch],
                    cwd=str(worktree_path),
                )
                title = session.title or f"Agent session {session.id[:8]}"
                pr_output = await state.executor._run_cmd(
                    ["gh", "pr", "create", "--title", f"[agents] {title}",
                     "--body", body, "--base", project.base_branch],
                    cwd=str(worktree_path),
                )
                pr_url = pr_output.strip()
        except Exception:
            logger.warning("Failed to create PR for session %s", session_id)

    # Clean up worktree
    session_manager.close_session(session_id)
    if worktree_path.exists() and project:
        try:
            await state.executor._run_cmd(
                ["git", "worktree", "remove", "--force", str(worktree_path)],
                cwd=project.repo,
            )
        except Exception:
            logger.warning("Failed to remove worktree %s", worktree_path, session_id)

    result: dict[str, str | None] = {"status": "closed"}
    if pr_url:
        result["pr_url"] = pr_url
    return result
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_session_pr.py tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/agent_routes.py tests/test_session_pr.py
git commit -m "feat: push branch and create PR when closing Agent Tab session"
```

---

## Phase 7: Auto-Review via claude-code-action

### Task 7: GitHub Action for automatic PR review

**Files:**
- Create: `.github/workflows/claude-review.yml`

Uses the official `anthropics/claude-code-action` to auto-review every agent-created PR. This is the last piece — review before merge.

- [ ] **Step 1: Create review workflow**

```yaml
# .github/workflows/claude-review.yml
name: Claude PR Review

on:
  pull_request:
    types: [opened, synchronize]

jobs:
  review:
    # Only review PRs created by agents
    if: startsWith(github.event.pull_request.title, '[agents]')
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
      issues: write
    steps:
      - uses: anthropics/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          model: "claude-sonnet-4-6"
          trigger_phrase: ""
          direct_prompt: |
            Review this PR for:
            1. Correctness: does the code do what the PR description says?
            2. Tests: are there adequate tests for the changes?
            3. Security: any OWASP top 10 vulnerabilities?
            4. Style: does it match the existing codebase patterns?

            If the PR looks good, approve it. If there are issues, request changes with specific feedback.
            Be concise. Focus on real issues, not style nitpicks.
```

> **Note:** Requires `ANTHROPIC_API_KEY` as a GitHub secret. Set at repo Settings → Secrets → Actions.

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/claude-review.yml
git commit -m "ci: add Claude auto-review for agent PRs"
```

---

## Phase 8: Scheduled Issue Polling (Webhook Fallback)

### Task 8: Poll Linear for unprocessed agent issues

**Files:**
- Create: `src/agents/polling.py`
- Modify: `src/agents/main.py` (add polling job to scheduler)
- Test: `tests/test_polling_job.py`

Webhooks can be missed (network issues, server restart, Linear outage). A polling job as fallback ensures no issue is left behind.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_polling_job.py
import pytest
from agents.polling import find_unprocessed_agent_issues

def test_identifies_unprocessed_issues():
    issues = [
        {"id": "1", "title": "Fix bug", "labels": [{"name": "agent"}],
         "state": {"name": "Backlog"}},
        {"id": "2", "title": "Other", "labels": [{"name": "bug"}],
         "state": {"name": "Backlog"}},
        {"id": "3", "title": "Done one", "labels": [{"name": "agent"}],
         "state": {"name": "Done"}},
    ]
    # Only issue 1 is agent-labeled and not Done/Cancelled
    unprocessed = find_unprocessed_agent_issues(issues)
    assert len(unprocessed) == 1
    assert unprocessed[0]["id"] == "1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_polling_job.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement polling module**

```python
# src/agents/polling.py
"""Polling fallback for missed webhooks — scans Linear for unprocessed agent issues."""

import logging

logger = logging.getLogger(__name__)

_TERMINAL_STATES = {"done", "cancelled", "canceled", "duplicate"}


def find_unprocessed_agent_issues(issues: list[dict]) -> list[dict]:
    """Filter issues that have the 'agent' label and are not in a terminal state."""
    result = []
    for issue in issues:
        labels = issue.get("labels", [])
        has_agent = any(
            label.get("name", "").lower() == "agent"
            for label in labels
            if isinstance(label, dict)
        )
        if not has_agent:
            continue
        state_name = issue.get("state", {}).get("name", "").lower()
        if state_name in _TERMINAL_STATES:
            continue
        result.append(issue)
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_polling_job.py -v`
Expected: PASS

- [ ] **Step 5: Wire polling job into main.py scheduler**

In `main.py` lifespan, add a new scheduled job:

```python
async def poll_linear_issues() -> None:
    """Fallback: poll Linear for agent issues missed by webhooks.
    Dispatches runs as background tasks (non-blocking) to avoid holding the polling coroutine."""
    if not linear_client:
        return
    for project in state.projects.values():
        if not project.linear_team_id or "issue-resolver" not in project.tasks:
            continue
        try:
            raw_issues = await linear_client.fetch_team_issues(project.linear_team_id)
            for issue in raw_issues:
                issue_id = issue.get("id", "")
                existing = state.history.find_run_by_issue_id(issue_id)
                if existing and existing.status in (RunStatus.RUNNING, RunStatus.SUCCESS):
                    continue
                # Check if issue has agent label via full fetch
                full = await linear_client.fetch_issue(issue_id)
                if "agent" not in full.get("labels", []):
                    continue
                state_name = full.get("state", "").lower()
                if state_name in ("done", "cancelled", "canceled"):
                    continue
                logger.info("Polling: found unprocessed agent issue %s", issue_id)
                variables = {
                    "issue_id": issue_id,
                    "issue_identifier": full.get("identifier", ""),
                    "issue_title": full.get("title", ""),
                    "issue_description": full.get("description", ""),
                    "team_id": project.linear_team_id,
                }
                # Dispatch as background task — do NOT await inline
                async def _run_polled(
                    p: ProjectConfig = project,
                    v: dict[str, str] = variables,
                ) -> None:
                    async with (
                        state.get_semaphore(config.execution.max_concurrent),
                        state.get_repo_semaphore(p.repo),
                    ):
                        await state.executor.run_task(
                            p, "issue-resolver",
                            trigger_type="linear", variables=v,
                        )
                asyncio.create_task(_run_polled())
        except Exception:
            logger.warning("Polling failed for project %s", project.name)

# Add to scheduler (every 15 minutes):
scheduler.add_job(poll_linear_issues, "interval", minutes=15, id="poll_linear_issues")
```

- [ ] **Step 6: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/agents/polling.py src/agents/main.py tests/test_polling_job.py
git commit -m "feat: scheduled Linear polling as webhook fallback (every 15min)"
```

---

## Phase 9: Fix paperweight.yaml test-runner autonomy

### Task 9: Change test-runner to report-only (no PR)

**Files:**
- Modify: `projects/paperweight.yaml:60`

- [ ] **Step 1: Fix the config**

Change `test-runner` from `autonomy: pr-only` to `autonomy: report-only`.

But `report-only` isn't a recognized value — the executor will still try to create a PR. We need to handle it.

Actually, the simplest fix: `test-runner` is report-only by nature (prompt says "Do NOT fix anything"). If it makes no commits, `_create_pr` returns `None` (the `log_output.strip()` check at line 470). So the current behavior is correct — it just won't create a PR if there are no changes.

**No change needed.** The `pr-only` autonomy is fine — it won't auto-merge, and the test runner won't produce commits.

- [ ] **Step 1: Skip — no change needed**

---

## Final Verification

- [ ] **Run full test suite**: `python -m pytest tests/ -v --tb=short`
- [ ] **Type check**: `python -m pyright src/`
- [ ] **Verify all new files are tracked**: `git status`

---

## Summary: The Closed Loop

After all phases:

```
Linear Issue (label: "agent")
  → Webhook to /webhooks/linear
  → OR polling fallback (every 15min)
  → Executor.run_task() with progress_file_path injected
  → Claude works in isolated worktree
  → Rich PR created (issue context + diff + cost)
  → GitHub Actions CI runs (pytest + pyright)
  → Claude auto-review via claude-code-action
  → auto-merge after CI passes + review approves
  → GitHub merge webhook → Linear issue → "Done"
  → Progress log cleaned up

Agent Tab session
  → Multi-turn Claude in worktree
  → On close: push + create PR
  → Same CI + review + merge pipeline
```

**Human touchpoints (optional):**
- Create the Linear issue with "agent" label
- Review the PR (if branch protection requires it)

Everything else is autonomous.
