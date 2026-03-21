# Paperweight Production Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every gap between what Paperweight is today and what a self-driving, observable, production-grade agent runner should be.

**Architecture:** 12 independent tasks across 5 phases. Each task produces a working, testable increment. Tasks within the same phase can run in parallel. The core principle is "less is more" — no new abstractions, no new dependencies, just filling gaps in what exists.

**Tech Stack:** Python 3.13, FastAPI, SQLite, APScheduler, pytest. No new dependencies added.

---

## File Structure

### New files
- `src/agents/retry.py` — Retry policy (backoff config, should_retry logic)
- `src/agents/cleanup.py` — Scheduled cleanup for run artifacts, worktrees, DB rows
- `src/agents/metrics.py` — Metrics collector (queries HistoryDB for trends)
- `src/agents/rate_limit.py` — Simple in-memory rate limiter middleware
- `src/agents/db_version.py` — Schema version tracking table + migration runner
- `tests/test_retry.py` — Retry policy tests
- `tests/test_cleanup.py` — Cleanup tests
- `tests/test_metrics.py` — Metrics tests
- `tests/test_rate_limit.py` — Rate limiter tests
- `tests/test_db_version.py` — DB version tests
- `tests/test_github_issues.py` — GitHub Issues trigger tests
- `tests/test_health_deep.py` — Deep health check tests

### Modified files
- `src/agents/task_processor.py` — Add retry logic to process_one
- `src/agents/task_store.py` — Add retry_count, next_retry_at columns to work_items
- `src/agents/models.py` — Add RETRYING status to TaskStatus
- `src/agents/main.py` — Wire cleanup jobs, deep health, rate limiter, GitHub Issues handler
- `src/agents/webhooks/github.py` — Add match_github_issue(), extract_github_issue_variables()
- `src/agents/history.py` — Add metrics queries (cost_by_day, success_rate, etc.)
- `src/agents/config.py` — Add RetryConfig, CleanupConfig to GlobalConfig
- `src/agents/notification_engine.py` — Add overnight digest builder
- `.github/workflows/ci.yml` — Add ruff lint step
- `config.yaml` — Add retry, cleanup sections

---

## Phase 1: Core Resilience

### Task 1: Retry with Exponential Backoff

**Files:**
- Create: `src/agents/retry.py`
- Create: `tests/test_retry.py`
- Modify: `src/agents/task_processor.py:148-158`
- Modify: `src/agents/task_store.py:21-61` (add columns)
- Modify: `src/agents/models.py:168-176` (add RETRYING status)
- Modify: `src/agents/config.py:33-40` (add RetryConfig)

- [ ] **Step 1: Write retry policy tests**

```python
# tests/test_retry.py
import time
from agents.retry import RetryPolicy, should_retry_error

def test_backoff_delay_exponential():
    policy = RetryPolicy(max_retries=3, base_delay_seconds=10, max_delay_seconds=300)
    assert policy.delay_for_attempt(1) == 10   # 10 * 2^0
    assert policy.delay_for_attempt(2) == 20   # 10 * 2^1
    assert policy.delay_for_attempt(3) == 40   # 10 * 2^2

def test_backoff_capped_at_max():
    policy = RetryPolicy(max_retries=5, base_delay_seconds=60, max_delay_seconds=120)
    assert policy.delay_for_attempt(5) == 120  # capped

def test_should_retry_true_for_retryable_errors():
    assert should_retry_error("Timed out after 30 minutes") is True
    assert should_retry_error("Command failed: git worktree add") is True
    assert should_retry_error("rate_limit_error") is True

def test_should_retry_false_for_permanent_errors():
    assert should_retry_error("Budget exceeded") is False
    assert should_retry_error("Project not found") is False
    assert should_retry_error("") is False

def test_can_retry_within_limit():
    policy = RetryPolicy(max_retries=3)
    assert policy.can_retry(attempt=1) is True
    assert policy.can_retry(attempt=3) is True
    assert policy.can_retry(attempt=4) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_retry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.retry'`

- [ ] **Step 3: Implement retry policy**

```python
# src/agents/retry.py
"""Retry policy for failed task executions."""
from pydantic import BaseModel


class RetryPolicy(BaseModel):
    max_retries: int = 3
    base_delay_seconds: int = 30
    max_delay_seconds: int = 300

    def delay_for_attempt(self, attempt: int) -> int:
        delay = self.base_delay_seconds * (2 ** (attempt - 1))
        return min(delay, self.max_delay_seconds)

    def can_retry(self, attempt: int) -> bool:
        return attempt <= self.max_retries


# Error messages that indicate transient failures worth retrying
_RETRYABLE_PATTERNS = [
    "timed out",
    "timeout",
    "rate_limit",
    "worktree add",
    "connection",
    "temporary",
    "503",
    "502",
    "EAGAIN",
]

_PERMANENT_PATTERNS = [
    "budget exceeded",
    "project not found",
    "task not found",
    "invalid signature",
    "authentication",
]


def should_retry_error(error_message: str) -> bool:
    if not error_message:
        return False
    lower = error_message.lower()
    if any(p in lower for p in _PERMANENT_PATTERNS):
        return False
    return any(p in lower for p in _RETRYABLE_PATTERNS)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_retry.py -v`
Expected: PASS

- [ ] **Step 5: Add retry_count and next_retry_at to models and TaskStore**

Add `RETRYING` to `src/agents/models.py` — TaskStatus enum:
```python
class TaskStatus(StrEnum):
    DRAFT = "draft"
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    REVIEW = "review"
    DONE = "done"
    FAILED = "failed"
    RETRYING = "retrying"
```

Add `retry_count` and `next_retry_at` as proper fields on `WorkItem`:
```python
class WorkItem(BaseModel):
    # ... existing fields ...
    retry_count: int = 0
    next_retry_at: str | None = None
```

Add migration in `src/agents/task_store.py` `_init_db` (after existing CREATE TABLE):
```python
for migration in [
    "ALTER TABLE work_items ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE work_items ADD COLUMN next_retry_at TEXT",
]:
    try:
        conn.execute(migration)
    except sqlite3.OperationalError:
        pass  # Column already exists
```

Update `_row_to_item` to read the new columns with fallback:
```python
def _row_to_item(self, row: sqlite3.Row) -> WorkItem:
    retry_count = 0
    next_retry_at = None
    try:
        retry_count = row["retry_count"] or 0
    except (IndexError, KeyError):
        pass
    try:
        next_retry_at = row["next_retry_at"]
    except (IndexError, KeyError):
        pass
    return WorkItem(
        # ... existing fields ...
        retry_count=retry_count,
        next_retry_at=next_retry_at,
    )
```

Add methods to TaskStore:
```python
def list_retryable(self, now_iso: str, limit: int = 5) -> list[WorkItem]:
    """Fetch tasks in RETRYING status whose next_retry_at has passed."""
    with self._conn() as conn:
        rows = conn.execute(
            "SELECT * FROM work_items WHERE status = ? AND next_retry_at <= ?"
            " ORDER BY next_retry_at ASC LIMIT ?",
            (TaskStatus.RETRYING, now_iso, limit),
        ).fetchall()
    return [self._row_to_item(r) for r in rows]

def mark_for_retry(self, item_id: str, retry_count: int, next_retry_at: str) -> None:
    now = datetime.now(UTC).isoformat()
    with self._conn() as conn:
        conn.execute(
            "UPDATE work_items SET status = ?, retry_count = ?, next_retry_at = ?,"
            " updated_at = ? WHERE id = ?",
            (TaskStatus.RETRYING, retry_count, next_retry_at, now, item_id),
        )

def try_claim_any(self, item_id: str) -> bool:
    """Claim a task that is either PENDING or RETRYING (retry window passed)."""
    now = datetime.now(UTC).isoformat()
    with self._conn() as conn:
        cursor = conn.execute(
            "UPDATE work_items SET status = ?, updated_at = ? WHERE id = ?"
            " AND status IN (?, ?)",
            (TaskStatus.RUNNING, now, item_id, TaskStatus.PENDING, TaskStatus.RETRYING),
        )
        return cursor.rowcount == 1
```

- [ ] **Step 6: Wire retry into TaskProcessor**

Add import at the top of `src/agents/task_processor.py`:
```python
from datetime import UTC, datetime, timedelta
```

In `src/agents/task_processor.py`, modify the failure path in `process_one`:
```python
# Replace: self.task_store.update_status(item.id, TaskStatus.FAILED)
# With:
from agents.retry import RetryPolicy, should_retry_error

retry_policy = RetryPolicy()  # defaults: 3 retries, 30s base
retry_count = item.retry_count + 1

if (result.status != RunStatus.SUCCESS
    and should_retry_error(result.error_message or "")
    and retry_policy.can_retry(retry_count)):
    delay = retry_policy.delay_for_attempt(retry_count)
    next_retry = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()
    self.task_store.mark_for_retry(item.id, retry_count, next_retry)
    logger.info("Task %s will retry (attempt %d) at %s", item.id, retry_count, next_retry)
else:
    self.task_store.update_status(item.id, TaskStatus.FAILED)
```

In `run_loop`, add retryable tasks to the pending check:
```python
# After fetching pending tasks:
now_iso = datetime.now(UTC).isoformat()
retryable = self.task_store.list_retryable(now_iso, limit=self.config.execution.max_concurrent)
for item in retryable:
    if not self.state.budget.can_afford(self.config.execution.default_max_cost_usd):
        break
    if self.task_store.try_claim_any(item.id):
        asyncio.create_task(self.process_one(item))
```

- [ ] **Step 7: Write integration test for retry flow**

```python
# Add to tests/test_retry.py
def test_task_store_retry_columns(tmp_path):
    from agents.task_store import TaskStore
    store = TaskStore(tmp_path / "test.db")
    item = store.create(project="test", title="retryable", description="", source="manual")
    store.mark_for_retry(item.id, retry_count=1, next_retry_at="2026-01-01T00:00:00")
    retryable = store.list_retryable("2026-01-02T00:00:00")
    assert len(retryable) == 1
    assert retryable[0].id == item.id

def test_task_store_retry_not_ready_yet(tmp_path):
    from agents.task_store import TaskStore
    store = TaskStore(tmp_path / "test.db")
    item = store.create(project="test", title="retryable", description="", source="manual")
    store.mark_for_retry(item.id, retry_count=1, next_retry_at="2099-01-01T00:00:00")
    retryable = store.list_retryable("2026-01-01T00:00:00")
    assert len(retryable) == 0
```

- [ ] **Step 8: Run all tests**

Run: `uv run pytest tests/test_retry.py tests/ -q --tb=short`
Expected: All pass

- [ ] **Step 9: Commit**

```bash
git add src/agents/retry.py tests/test_retry.py src/agents/task_processor.py src/agents/task_store.py src/agents/models.py
git commit -m "feat: retry with exponential backoff for failed tasks"
```

---

### Task 2: Automated Cleanup

**Files:**
- Create: `src/agents/cleanup.py`
- Create: `tests/test_cleanup.py`
- Modify: `src/agents/main.py:293-294` (register cleanup job)
- Modify: `src/agents/history.py` (add purge methods)

- [ ] **Step 1: Write cleanup tests**

```python
# tests/test_cleanup.py
import json
import time
from pathlib import Path
from datetime import UTC, datetime, timedelta
from agents.cleanup import (
    find_stale_run_files,
    find_orphan_worktrees,
    cleanup_run_artifacts,
)

def test_find_stale_run_files(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    old_file = runs_dir / "old-run.json"
    old_file.write_text("{}")
    # Set mtime to 40 days ago
    import os
    old_time = time.time() - (40 * 86400)
    os.utime(old_file, (old_time, old_time))
    new_file = runs_dir / "new-run.json"
    new_file.write_text("{}")
    stale = find_stale_run_files(runs_dir, max_age_days=30)
    assert len(stale) == 1
    assert stale[0].name == "old-run.json"

def test_find_orphan_worktrees(tmp_path):
    wt_base = tmp_path / "worktrees"
    wt_base.mkdir()
    (wt_base / "session-abc123").mkdir()
    (wt_base / "session-def456").mkdir()
    active_ids = {"abc123"}
    orphans = find_orphan_worktrees(wt_base, active_session_ids=active_ids)
    assert len(orphans) == 1
    assert orphans[0].name == "session-def456"

def test_cleanup_run_artifacts_deletes_files(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    old_file = runs_dir / "stale.json"
    old_file.write_text("{}")
    import os
    old_time = time.time() - (40 * 86400)
    os.utime(old_file, (old_time, old_time))
    deleted = cleanup_run_artifacts(runs_dir, max_age_days=30)
    assert deleted == 1
    assert not old_file.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cleanup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.cleanup'`

- [ ] **Step 3: Implement cleanup module**

```python
# src/agents/cleanup.py
"""Scheduled cleanup for run artifacts, orphan worktrees, and old DB rows."""
import logging
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def find_stale_run_files(runs_dir: Path, max_age_days: int = 30) -> list[Path]:
    if not runs_dir.exists():
        return []
    cutoff = time.time() - (max_age_days * 86400)
    return [f for f in runs_dir.iterdir() if f.is_file() and f.stat().st_mtime < cutoff]


def cleanup_run_artifacts(runs_dir: Path, max_age_days: int = 30) -> int:
    stale = find_stale_run_files(runs_dir, max_age_days)
    for f in stale:
        f.unlink(missing_ok=True)
    if stale:
        logger.info("Deleted %d stale run artifact(s)", len(stale))
    return len(stale)


def find_orphan_worktrees(
    worktree_base: Path, active_session_ids: set[str],
) -> list[Path]:
    if not worktree_base.exists():
        return []
    orphans = []
    for d in worktree_base.iterdir():
        if not d.is_dir():
            continue
        # Extract session ID from "session-{id}" pattern
        name = d.name
        if name.startswith("session-"):
            sid = name[len("session-"):]
            if sid not in active_session_ids:
                orphans.append(d)
    return orphans


def cleanup_orphan_worktrees(
    worktree_base: Path, active_session_ids: set[str], repo_path: str,
) -> int:
    orphans = find_orphan_worktrees(worktree_base, active_session_ids)
    removed = 0
    for d in orphans:
        try:
            shutil.rmtree(d)
            removed += 1
        except Exception:
            logger.warning("Failed to remove orphan worktree %s", d)
    if removed:
        logger.info("Removed %d orphan worktree(s)", removed)
    return removed


def purge_old_run_events(history_db: object, days: int = 30) -> int:
    """Delete run_events older than N days. Returns count deleted."""
    cutoff = time.time() - (days * 86400)
    conn_method = getattr(history_db, '_conn', None)
    if conn_method is None:
        return 0
    with conn_method() as conn:
        cursor = conn.execute(
            "DELETE FROM run_events WHERE timestamp < ?", (cutoff,)
        )
        deleted = cursor.rowcount
    if deleted:
        logger.info("Purged %d old run event(s)", deleted)
    return deleted
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cleanup.py -v`
Expected: PASS

- [ ] **Step 5: Wire cleanup into scheduler**

In `src/agents/main.py`, add to the lifespan function after existing cleanup jobs (~line 293):

```python
async def cleanup_run_artifacts_job() -> None:
    from agents.cleanup import cleanup_run_artifacts, purge_old_run_events
    cleanup_run_artifacts(data_dir / "runs", max_age_days=30)
    purge_old_run_events(history, days=30)

scheduler.add_job(cleanup_run_artifacts_job, "cron", hour=4, minute=0, id="artifact_cleanup")
```

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest tests/ -q --tb=short`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/agents/cleanup.py tests/test_cleanup.py src/agents/main.py
git commit -m "feat: automated cleanup for run artifacts, orphan worktrees, old events"
```

---

### Task 3: Deep Health Check

**Files:**
- Create: `tests/test_health_deep.py`
- Modify: `src/agents/main.py:340-342` (replace /health route)

- [ ] **Step 1: Write deep health check tests**

```python
# tests/test_health_deep.py
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from agents.main import create_app

@pytest.fixture
def app(tmp_path):
    config_path = Path(__file__).parent.parent / "config.yaml"
    return create_app(
        config_path=config_path,
        projects_dir=tmp_path / "projects",
        data_dir=tmp_path / "data",
    )

@pytest.fixture
def client(app):
    return TestClient(app)

def test_health_returns_component_status(client):
    """Health endpoint should report db, scheduler, disk status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "components" in data
    assert "db" in data["components"]
    assert data["components"]["db"] == "ok"

def test_health_reports_disk_status(client):
    """Health endpoint should check disk writability."""
    response = client.get("/health")
    data = response.json()
    assert data["components"]["disk"] == "ok"
```

- [ ] **Step 2: Implement deep health check**

Replace the `/health` route in `src/agents/main.py`:

```python
@app.get("/health")
async def health() -> dict:
    components = {}
    overall = "ok"

    # DB check
    try:
        history.total_cost_today()  # lightweight query
        components["db"] = "ok"
    except Exception as e:
        components["db"] = f"error: {e}"
        overall = "degraded"

    # Disk check (data dir writable)
    try:
        probe = data_dir / ".health_probe"
        probe.write_text("ok")
        probe.unlink()
        components["disk"] = "ok"
    except Exception:
        components["disk"] = "error: data dir not writable"
        overall = "degraded"

    # Scheduler check
    try:
        sched = getattr(app.state, 'scheduler', None)
        job_count = len(sched.get_jobs()) if sched else 0
        components["scheduler"] = f"ok ({job_count} jobs)"
    except Exception:
        components["scheduler"] = "error"
        overall = "degraded"

    status_code = 200 if overall == "ok" else 503
    return Response(
        content=json_module.dumps({"status": overall, "components": components}),
        status_code=status_code,
        media_type="application/json",
    )
```

Store scheduler on `app.state` for health check access — add inside `lifespan`, after `scheduler.start()`:
```python
app.state.scheduler = scheduler
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/test_health_deep.py tests/test_main.py -q --tb=short`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/agents/main.py tests/test_health_deep.py
git commit -m "feat: deep health check with db, disk, scheduler component status"
```

---

## Phase 2: Missing Integrations

### Task 4: GitHub Issues as Trigger

**Files:**
- Create: `tests/test_github_issues.py`
- Modify: `src/agents/webhooks/github.py` (add issue matching)
- Modify: `src/agents/main.py:396-447` (add issue handler in github_webhook)

- [ ] **Step 1: Write GitHub Issues matching tests**

```python
# tests/test_github_issues.py
from agents.webhooks.github import (
    match_github_issue,
    extract_github_issue_variables,
)

def test_match_github_issue_opened():
    payload = {
        "action": "opened",
        "issue": {
            "number": 42,
            "title": "Add pagination",
            "body": "We need cursor-based pagination",
            "labels": [{"name": "agent"}],
            "user": {"login": "vini"},
        },
        "repository": {"full_name": "org/repo"},
    }
    assert match_github_issue(payload) is True

def test_match_github_issue_labeled_with_agent():
    payload = {
        "action": "labeled",
        "label": {"name": "agent"},
        "issue": {
            "number": 42,
            "title": "Fix bug",
            "body": "",
            "labels": [{"name": "agent"}, {"name": "bug"}],
            "user": {"login": "vini"},
        },
        "repository": {"full_name": "org/repo"},
    }
    assert match_github_issue(payload) is True

def test_match_github_issue_no_agent_label():
    payload = {
        "action": "opened",
        "issue": {
            "number": 42,
            "labels": [{"name": "bug"}],
        },
    }
    assert match_github_issue(payload) is False

def test_match_github_issue_closed_ignored():
    payload = {
        "action": "closed",
        "issue": {"labels": [{"name": "agent"}]},
    }
    assert match_github_issue(payload) is False

def test_extract_github_issue_variables():
    payload = {
        "action": "opened",
        "issue": {
            "number": 42,
            "title": "Add pagination",
            "body": "Description here",
            "html_url": "https://github.com/org/repo/issues/42",
            "labels": [{"name": "agent"}],
            "user": {"login": "vini"},
        },
        "repository": {"full_name": "org/repo"},
    }
    variables = extract_github_issue_variables(payload)
    assert variables["issue_number"] == "42"
    assert variables["issue_title"] == "Add pagination"
    assert variables["issue_body"] == "Description here"
    assert variables["issue_url"] == "https://github.com/org/repo/issues/42"
    assert variables["repo_full_name"] == "org/repo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_github_issues.py -v`
Expected: FAIL — `ImportError: cannot import name 'match_github_issue'`

- [ ] **Step 3: Implement GitHub Issues matching**

Add to `src/agents/webhooks/github.py`:

```python
def match_github_issue(payload: dict) -> bool:
    """Check if this is a GitHub issue event that should trigger an agent run."""
    action = payload.get("action", "")
    if action not in ("opened", "labeled"):
        return False
    issue = payload.get("issue", {})
    labels = issue.get("labels", [])
    has_agent = any(
        label.get("name", "").lower() == "agent"
        for label in labels
        if isinstance(label, dict)
    )
    if not has_agent:
        return False
    # For "labeled" action, only trigger if the label being added is "agent"
    if action == "labeled":
        added_label = payload.get("label", {}).get("name", "")
        return added_label.lower() == "agent"
    return True


def extract_github_issue_variables(payload: dict) -> dict[str, str]:
    issue = payload.get("issue", {})
    repo = payload.get("repository", {})
    return {
        "issue_number": str(issue.get("number", "")),
        "issue_title": issue.get("title", ""),
        "issue_body": issue.get("body", "") or "",
        "issue_url": issue.get("html_url", ""),
        "repo_full_name": repo.get("full_name", ""),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_github_issues.py -v`
Expected: PASS

- [ ] **Step 5: Wire into github_webhook handler in main.py**

Add after the existing `is_agent_pr_merge` block in the github_webhook handler (~line 426):

```python
from agents.webhooks.github import match_github_issue, extract_github_issue_variables

if event_type == "issues" and match_github_issue(payload):
    issue_vars = extract_github_issue_variables(payload)
    issue_number = issue_vars.get("issue_number", "")
    repo_name = issue_vars.get("repo_full_name", "")
    source_id = f"github:{repo_name}#{issue_number}"

    if state.task_store and not state.task_store.exists_by_source("github", source_id):
        # Find matching project by repo
        for project in state.projects.values():
            repo_match = repo_name and repo_name in project.repo
            if repo_match and "issue-resolver" in project.tasks:
                state.task_store.create(
                    project=project.name,
                    title=issue_vars.get("issue_title", "GitHub issue"),
                    description=issue_vars.get("issue_body", ""),
                    source="github",
                    source_id=source_id,
                    source_url=issue_vars.get("issue_url", ""),
                    template="issue-resolver",
                )
                logger.info("Created task for GitHub issue %s", source_id)
                break
```

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest tests/ -q --tb=short`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/agents/webhooks/github.py src/agents/main.py tests/test_github_issues.py
git commit -m "feat: GitHub Issues as trigger — agent label creates work items"
```

---

## Phase 3: Observability

### Task 5: Structured Logging

**Files:**
- Modify: `src/agents/main.py:574-587` (configure logging in run())

- [ ] **Step 1: Configure JSON logging in production**

In `src/agents/main.py`, update the `run()` function:

```python
def run() -> None:
    import uvicorn
    from dotenv import load_dotenv

    load_dotenv()

    # Structured logging: JSON in production, human-readable in dev
    import os as _os
    log_format = _os.environ.get("LOG_FORMAT", "text")
    log_level = _os.environ.get("LOG_LEVEL", "INFO").upper()

    if log_format == "json":
        import json as _json_log

        class JSONFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                return _json_log.dumps({
                    "ts": self.formatTime(record),
                    "level": record.levelname,
                    "logger": record.name,
                    "msg": record.getMessage(),
                    "module": record.module,
                    **({"exc": self.formatException(record.exc_info)} if record.exc_info else {}),
                })

        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logging.root.handlers = [handler]

    logging.root.setLevel(getattr(logging, log_level, logging.INFO))

    base = Path.cwd()
    config = load_global_config(base / "config.yaml")
    app = create_app(
        config_path=base / "config.yaml",
        projects_dir=base / "projects",
        data_dir=base / "data",
    )
    uvicorn.run(app, host=config.server.host, port=config.server.port)
```

- [ ] **Step 2: Extract JSONFormatter to a testable location**

Move the `JSONFormatter` class out of `run()` into module scope so it can be imported by tests:

```python
# At module level in src/agents/main.py (before run()):
import json as json_module  # already imported

class JSONFormatter(logging.Formatter):
    """JSON log formatter for production use. Enable via LOG_FORMAT=json."""
    def format(self, record: logging.LogRecord) -> str:
        return json_module.dumps({
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "module": record.module,
            **({"exc": self.formatException(record.exc_info)} if record.exc_info else {}),
        })
```

- [ ] **Step 3: Write test for JSONFormatter**

```python
# Add to tests/test_main.py
def test_json_formatter_produces_valid_json():
    import json
    import logging
    from io import StringIO
    from agents.main import JSONFormatter

    handler = logging.StreamHandler(stream := StringIO())
    handler.setFormatter(JSONFormatter())
    logger = logging.getLogger("test_json_fmt")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.info("test message")
    output = stream.getvalue().strip()
    parsed = json.loads(output)
    assert parsed["level"] == "INFO"
    assert parsed["msg"] == "test message"
    assert "ts" in parsed
```

- [ ] **Step 4: Run and commit**

Run: `uv run pytest tests/test_main.py -q --tb=short`

```bash
git add src/agents/main.py tests/test_main.py
git commit -m "feat: structured JSON logging via LOG_FORMAT=json env var"
```

---

### Task 6: Metrics API

**Files:**
- Create: `src/agents/metrics.py`
- Create: `tests/test_metrics.py`
- Modify: `src/agents/history.py` (add aggregate queries)
- Modify: `src/agents/main.py` (add /api/metrics route)

- [ ] **Step 1: Write metrics query tests**

```python
# tests/test_metrics.py
import pytest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from agents.history import HistoryDB
from agents.models import RunRecord, RunStatus, TriggerType
from agents.metrics import collect_metrics

def _make_run(history, project, status, cost, days_ago=0):
    started = datetime.now(UTC) - timedelta(days=days_ago)
    run = RunRecord(
        id=f"run-{project}-{days_ago}-{status}-{cost}",
        project=project,
        task="test-task",
        trigger_type=TriggerType.MANUAL,
        started_at=started,
        finished_at=started + timedelta(minutes=5),
        status=RunStatus(status),
        model="sonnet",
        cost_usd=cost,
        num_turns=10,
    )
    history.insert_run(run)
    history.update_run(run.id, status=run.status, finished_at=run.finished_at,
                       cost_usd=run.cost_usd, num_turns=run.num_turns)

def test_collect_metrics_cost_by_day(tmp_path):
    db = HistoryDB(tmp_path / "test.db")
    _make_run(db, "proj1", "success", 1.50, days_ago=0)
    _make_run(db, "proj1", "success", 2.00, days_ago=0)
    _make_run(db, "proj1", "failure", 0.50, days_ago=1)
    metrics = collect_metrics(db, days=7)
    assert metrics["total_cost_7d"] == pytest.approx(4.00)
    assert metrics["total_runs_7d"] == 3
    assert len(metrics["cost_by_day"]) >= 1

def test_collect_metrics_success_rate(tmp_path):
    db = HistoryDB(tmp_path / "test.db")
    _make_run(db, "proj1", "success", 1.0, days_ago=0)
    _make_run(db, "proj1", "success", 1.5, days_ago=0)
    _make_run(db, "proj1", "failure", 0.5, days_ago=0)
    metrics = collect_metrics(db, days=7)
    assert metrics["success_rate_7d"] == pytest.approx(66.67, abs=0.1)

def test_collect_metrics_empty_db(tmp_path):
    db = HistoryDB(tmp_path / "test.db")
    metrics = collect_metrics(db, days=7)
    assert metrics["total_runs_7d"] == 0
    assert metrics["success_rate_7d"] == 0.0
    assert metrics["total_cost_7d"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.metrics'`

- [ ] **Step 3: Add aggregate queries to HistoryDB**

Add to `src/agents/history.py`:

```python
def cost_by_day(self, days: int = 7) -> list[dict]:
    """Return daily cost totals for the last N days."""
    from datetime import timedelta
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    with self._conn() as conn:
        rows = conn.execute(
            "SELECT DATE(started_at) as day, SUM(COALESCE(cost_usd, 0)) as total,"
            " COUNT(*) as runs"
            " FROM runs WHERE started_at >= ?"
            " GROUP BY DATE(started_at) ORDER BY day ASC",
            (cutoff,),
        ).fetchall()
    return [{"day": row["day"], "cost": row["total"], "runs": row["runs"]} for row in rows]

def runs_by_status(self, days: int = 7) -> dict[str, int]:
    """Count runs by status for the last N days."""
    from datetime import timedelta
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    with self._conn() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as count FROM runs WHERE started_at >= ?"
            " GROUP BY status",
            (cutoff,),
        ).fetchall()
    return {row["status"]: row["count"] for row in rows}

def avg_duration_seconds(self, days: int = 7) -> float:
    """Average run duration in seconds for the last N days."""
    from datetime import timedelta
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    with self._conn() as conn:
        row = conn.execute(
            "SELECT AVG(JULIANDAY(finished_at) - JULIANDAY(started_at)) * 86400 as avg_dur"
            " FROM runs WHERE started_at >= ? AND finished_at IS NOT NULL",
            (cutoff,),
        ).fetchone()
    return row["avg_dur"] or 0.0
```

- [ ] **Step 4: Implement metrics collector**

```python
# src/agents/metrics.py
"""Metrics collector — aggregates run history into trend data."""
from agents.history import HistoryDB


def collect_metrics(history: HistoryDB, days: int = 7) -> dict:
    cost_days = history.cost_by_day(days)
    status_counts = history.runs_by_status(days)
    avg_dur = history.avg_duration_seconds(days)

    total_runs = sum(status_counts.values())
    success_count = status_counts.get("success", 0)
    success_rate = (success_count / total_runs * 100) if total_runs > 0 else 0.0
    total_cost = sum(d["cost"] for d in cost_days)

    return {
        "total_runs_7d": total_runs,
        "success_rate_7d": round(success_rate, 2),
        "total_cost_7d": round(total_cost, 2),
        "avg_duration_seconds": round(avg_dur, 1),
        "cost_by_day": cost_days,
        "runs_by_status": status_counts,
    }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_metrics.py -v`
Expected: PASS

- [ ] **Step 6: Add /api/metrics route to main.py**

```python
@app.get("/api/metrics")
async def api_metrics() -> dict:
    from agents.metrics import collect_metrics
    return collect_metrics(state.history, days=7)
```

- [ ] **Step 7: Run full tests and commit**

Run: `uv run pytest tests/ -q --tb=short`

```bash
git add src/agents/metrics.py tests/test_metrics.py src/agents/history.py src/agents/main.py
git commit -m "feat: metrics API — cost trends, success rate, run duration"
```

---

### Task 7: Metrics Dashboard Widget

**Files:**
- Modify: `src/agents/templates/components/macros.html` (add metrics macro)
- Modify: `src/agents/dashboard_html.py` (inject metrics into template context)
- Modify: `src/agents/templates/tasks.html` (render metrics widget)

- [ ] **Step 1: Add metrics macro to macros.html**

Add a new macro at the end of `src/agents/templates/components/macros.html`:

```html
{% macro metrics_widget(metrics) %}
<div class="metrics-bar" style="display:flex; gap:var(--space-4); padding:var(--space-3) var(--space-4); border-bottom:1px solid var(--chrome-300); font-size:0.82rem; color:var(--chrome-600); flex-wrap:wrap;">
  <span title="Last 7 days">
    <span style="font-weight:600; color:var(--chrome-900);">{{ metrics.total_runs_7d }}</span> runs
  </span>
  <span>·</span>
  <span title="Success rate">
    <span style="font-weight:600; color:{% if metrics.success_rate_7d >= 80 %}var(--green-600){% elif metrics.success_rate_7d >= 50 %}var(--amber-600){% else %}var(--red-600){% endif %};">{{ metrics.success_rate_7d }}%</span> success
  </span>
  <span>·</span>
  <span title="Total cost last 7 days">
    $<span style="font-weight:600; color:var(--chrome-900);">{{ "%.2f"|format(metrics.total_cost_7d) }}</span> cost
  </span>
  <span>·</span>
  <span title="Average run duration">
    <span style="font-weight:600; color:var(--chrome-900);">{{ (metrics.avg_duration_seconds / 60)|round(1) }}</span>min avg
  </span>
</div>
{% endmacro %}
```

- [ ] **Step 2: Write test for metrics in template context**

```python
# Add to tests/test_dashboard_html.py
def test_tasks_page_includes_metrics(tmp_path):
    """The tasks page should include metrics data in the template context."""
    from pathlib import Path
    from agents.main import create_app
    from fastapi.testclient import TestClient
    config_path = Path(__file__).parent.parent / "config.yaml"
    app = create_app(config_path=config_path, projects_dir=tmp_path / "p", data_dir=tmp_path / "d")
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    # The metrics widget should render numbers (even if 0)
    assert "runs" in resp.text.lower() or "success" in resp.text.lower()
```

- [ ] **Step 3: Inject metrics into the tasks page**

In `src/agents/dashboard_html.py`, find the tasks page handler (the `GET /` route, around line 134). Add metrics to the template context:

```python
from agents.metrics import collect_metrics

# Inside the handler, before rendering:
metrics = collect_metrics(state.history, days=7)
# Pass metrics=metrics to the TemplateResponse context dict
```

- [ ] **Step 4: Render in tasks.html**

Add at the top of the tasks content area in `src/agents/templates/tasks.html`:

```html
{% from "components/macros.html" import metrics_widget %}
{% if metrics %}
  {{ metrics_widget(metrics) }}
{% endif %}
```

- [ ] **Step 4: Run tests and commit**

Run: `uv run pytest tests/ -q --tb=short`

```bash
git add src/agents/templates/components/macros.html src/agents/templates/tasks.html src/agents/dashboard_html.py
git commit -m "feat: metrics dashboard widget — runs, success rate, cost, avg duration"
```

---

## Phase 4: Production Hardening

### Task 8: Rate Limiting Middleware

**Files:**
- Create: `src/agents/rate_limit.py`
- Create: `tests/test_rate_limit.py`
- Modify: `src/agents/main.py` (register middleware)

- [ ] **Step 1: Write rate limiter tests**

```python
# tests/test_rate_limit.py
import time
from agents.rate_limit import RateLimiter

def test_allows_within_limit():
    limiter = RateLimiter(max_requests=5, window_seconds=60)
    for _ in range(5):
        assert limiter.is_allowed("client-1") is True

def test_blocks_over_limit():
    limiter = RateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        assert limiter.is_allowed("client-1") is True
    assert limiter.is_allowed("client-1") is False

def test_different_clients_independent():
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    assert limiter.is_allowed("client-1") is True
    assert limiter.is_allowed("client-1") is True
    assert limiter.is_allowed("client-1") is False
    assert limiter.is_allowed("client-2") is True  # different client

def test_window_expires():
    limiter = RateLimiter(max_requests=1, window_seconds=1)
    assert limiter.is_allowed("client-1") is True
    assert limiter.is_allowed("client-1") is False
    time.sleep(1.1)
    assert limiter.is_allowed("client-1") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_rate_limit.py -v`
Expected: FAIL

- [ ] **Step 3: Implement rate limiter**

```python
# src/agents/rate_limit.py
"""Simple in-memory rate limiter — no external dependencies."""
import time
from collections import defaultdict


class RateLimiter:
    def __init__(self, max_requests: int = 60, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, client_id: str) -> bool:
        now = time.time()
        cutoff = now - self.window_seconds
        # Prune old entries
        self._requests[client_id] = [
            t for t in self._requests[client_id] if t > cutoff
        ]
        if len(self._requests[client_id]) >= self.max_requests:
            return False
        self._requests[client_id].append(now)
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_rate_limit.py -v`
Expected: PASS

- [ ] **Step 5: Register as FastAPI middleware**

In `src/agents/main.py`, after `register_auth_middleware(app)`:

```python
from agents.rate_limit import RateLimiter
_rate_limiter = RateLimiter(max_requests=120, window_seconds=60)

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Skip rate limiting for WebSocket, health, and static files
    path = request.url.path
    if path.startswith("/ws/") or path == "/health" or path.startswith("/static/"):
        return await call_next(request)
    client_ip = request.client.host if request.client else "unknown"
    if not _rate_limiter.is_allowed(client_ip):
        return Response(status_code=429, content="Too many requests")
    return await call_next(request)
```

- [ ] **Step 6: Run full tests and commit**

Run: `uv run pytest tests/ -q --tb=short`

```bash
git add src/agents/rate_limit.py tests/test_rate_limit.py src/agents/main.py
git commit -m "feat: in-memory rate limiting middleware (120 req/min per IP)"
```

---

### Task 9: CI Lint Step

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Add ruff lint step to CI**

Update `.github/workflows/ci.yml`:

```yaml
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
        run: uv sync --frozen --extra dev

      - name: Lint
        run: uv run ruff check src/ tests/

      - name: Run tests
        run: uv run python -m pytest tests/ -v --tb=short

      - name: Type check
        run: uv run python -m pyright src/
        continue-on-error: true
```

- [ ] **Step 2: Verify lint passes locally**

Run: `uv run ruff check src/ tests/`
Expected: No errors (or fix any that appear)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add ruff lint step to CI pipeline"
```

---

### Task 10: DB Schema Version Tracking

**Files:**
- Create: `src/agents/db_version.py`
- Create: `tests/test_db_version.py`

- [ ] **Step 1: Write DB version tests**

```python
# tests/test_db_version.py
import sqlite3
from pathlib import Path
from agents.db_version import SchemaVersionTracker

def test_initial_version_is_zero(tmp_path):
    tracker = SchemaVersionTracker(tmp_path / "test.db")
    assert tracker.current_version() == 0

def test_apply_migration_increments_version(tmp_path):
    tracker = SchemaVersionTracker(tmp_path / "test.db")
    def migration_1(conn):
        conn.execute("CREATE TABLE test_table (id TEXT PRIMARY KEY)")
    tracker.apply(1, migration_1)
    assert tracker.current_version() == 1

def test_skip_already_applied(tmp_path):
    tracker = SchemaVersionTracker(tmp_path / "test.db")
    call_count = 0
    def migration_1(conn):
        nonlocal call_count
        call_count += 1
        conn.execute("CREATE TABLE test_table (id TEXT PRIMARY KEY)")
    tracker.apply(1, migration_1)
    tracker.apply(1, migration_1)  # should be skipped
    assert call_count == 1

def test_multiple_migrations_in_order(tmp_path):
    tracker = SchemaVersionTracker(tmp_path / "test.db")
    tracker.apply(1, lambda c: c.execute("CREATE TABLE t1 (id TEXT)"))
    tracker.apply(2, lambda c: c.execute("CREATE TABLE t2 (id TEXT)"))
    assert tracker.current_version() == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db_version.py -v`
Expected: FAIL

- [ ] **Step 3: Implement schema version tracker**

```python
# src/agents/db_version.py
"""Simple schema version tracker — alternative to Alembic for embedded SQLite."""
import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)


class SchemaVersionTracker:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
            """)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def current_version(self) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MAX(version) as v FROM schema_version"
            ).fetchone()
            return row[0] or 0

    def apply(self, version: int, migration_fn: Callable[[sqlite3.Connection], None]) -> bool:
        if version <= self.current_version():
            return False
        from datetime import UTC, datetime
        with self._conn() as conn:
            migration_fn(conn)
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, datetime.now(UTC).isoformat()),
            )
        logger.info("Applied schema migration v%d", version)
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_db_version.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/db_version.py tests/test_db_version.py
git commit -m "feat: schema version tracker for formal DB migrations"
```

---

## Phase 5: Intelligence Layer

### Task 11: Overnight Digest

**Files:**
- Modify: `src/agents/notification_engine.py` (add overnight digest)
- Modify: `src/agents/main.py` (update daily_digest job)

**Note:** This task depends on Task 6 (Metrics API) — `build_overnight_digest` imports `collect_metrics`. Execute Task 6 first.

- [ ] **Step 1: Write overnight digest tests**

```python
# tests/test_overnight_digest.py
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from agents.notification_engine import NotificationEngine
from agents.history import HistoryDB
from agents.models import RunRecord, RunStatus, TriggerType

def _insert_run(db, status, cost, pr_url=None, error=None, hours_ago=2):
    started = datetime.now(UTC) - timedelta(hours=hours_ago)
    run = RunRecord(
        id=f"run-{status}-{hours_ago}-{cost}",
        project="test", task="build",
        trigger_type=TriggerType.SCHEDULE,
        started_at=started,
        finished_at=started + timedelta(minutes=5),
        status=RunStatus(status), model="sonnet",
        cost_usd=cost, num_turns=10,
        pr_url=pr_url, error_message=error,
    )
    db.insert_run(run)
    db.update_run(run.id, status=run.status, finished_at=run.finished_at,
                  cost_usd=run.cost_usd, pr_url=run.pr_url, error_message=run.error_message)

def test_overnight_digest_summarizes_runs(tmp_path):
    db = HistoryDB(tmp_path / "test.db")
    _insert_run(db, "success", 1.50, pr_url="https://github.com/org/repo/pull/1")
    _insert_run(db, "failure", 0.50, error="Timed out")

    mock_store = MagicMock()
    engine = NotificationEngine(store=mock_store)
    digest = engine.build_overnight_digest(db, hours=12)
    assert "2 runs" in digest
    assert "1 succeeded" in digest
    assert "1 failed" in digest
    assert "$2.00" in digest
    assert "pull/1" in digest

def test_overnight_digest_empty_when_no_runs(tmp_path):
    db = HistoryDB(tmp_path / "test.db")
    mock_store = MagicMock()
    engine = NotificationEngine(store=mock_store)
    digest = engine.build_overnight_digest(db, hours=12)
    assert digest == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_overnight_digest.py -v`
Expected: FAIL — `AttributeError: 'NotificationEngine' object has no attribute 'build_overnight_digest'`

- [ ] **Step 3: Add overnight digest builder to NotificationEngine**

Add to `src/agents/notification_engine.py`:

```python
def build_overnight_digest(self, history: object, hours: int = 12) -> str:
    """Build a summary of what happened in the last N hours."""
    from datetime import UTC, datetime, timedelta
    from agents.metrics import collect_metrics

    metrics = collect_metrics(history, days=1)
    cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()

    # Get recent runs from history
    runs_today = history.list_runs_today()
    overnight_runs = [
        r for r in runs_today
        if r.started_at.isoformat() >= cutoff
    ]

    if not overnight_runs:
        return ""

    successes = [r for r in overnight_runs if r.status == "success"]
    failures = [r for r in overnight_runs if r.status in ("failure", "timeout")]
    prs = [r for r in overnight_runs if r.pr_url]
    total_cost = sum(r.cost_usd or 0 for r in overnight_runs)

    lines = ["📋 Overnight Summary\n"]
    lines.append(f"  {len(overnight_runs)} runs | {len(successes)} succeeded | {len(failures)} failed")
    lines.append(f"  Cost: ${total_cost:.2f}")

    if prs:
        lines.append(f"\n  PRs created ({len(prs)}):")
        for r in prs:
            lines.append(f"    → {r.pr_url}")

    if failures:
        lines.append(f"\n  Failures ({len(failures)}):")
        for r in failures[:5]:
            error = (r.error_message or "unknown")[:80]
            lines.append(f"    ✗ {r.project}/{r.task}: {error}")

    return "\n".join(lines)
```

- [ ] **Step 3: Update daily_digest job in main.py**

Replace the `run_daily_digest` function in `src/agents/main.py`:

```python
async def run_daily_digest() -> None:
    # Project-level digest (existing)
    for project in project_store.list_projects():
        await notification_engine.send_digest(project["id"])
    # Overnight run summary (new)
    overnight = notification_engine.build_overnight_digest(history, hours=12)
    if overnight:
        await notifier.send_text(overnight)
```

- [ ] **Step 4: Run tests and commit**

Run: `uv run pytest tests/test_overnight_digest.py tests/ -q --tb=short`

```bash
git add src/agents/notification_engine.py src/agents/main.py tests/test_overnight_digest.py
git commit -m "feat: overnight digest — summarizes runs, PRs, failures from last 12h"
```

---

### Task 12: PCP Trim — Remove Dead Code, Keep What Works

**Files:**
- Modify: `src/agents/coordination/mediator.py` (simplify)
- Remove dead mediator spawning code if any

- [ ] **Step 1: Audit PCP code for dead paths**

Read all files in `src/agents/coordination/`. Identify:
- What's tested and working (claims, broker, protocol)
- What's scaffolding (mediator spawning, rebase)

- [ ] **Step 2: Add docstring marking PCP status**

Add to `src/agents/coordination/__init__.py`:

```python
"""
Paperweight Coordination Protocol (PCP)

Status: claims + broker are functional and tested.
Mediator spawning is prompt-only (no actual agent execution).

Enable with `coordination.enabled: true` in config.yaml.
"""
```

- [ ] **Step 3: Simplify mediator.py — remove unreachable code**

The mediator.py builds prompts but never spawns agents. Clean it up:
- Keep `build_coordination_preamble()` (used by executor.py)
- Remove or comment the rebase/merge strategy portions that have no callers
- Add `# NOT YET IMPLEMENTED` markers to unfinished paths

- [ ] **Step 4: Run full test suite to verify no regressions**

Run: `uv run pytest tests/ -q --tb=short`
Expected: All pass (including coordination tests)

- [ ] **Step 5: Commit**

```bash
git add src/agents/coordination/
git commit -m "refactor: trim PCP — document status, remove dead mediator paths"
```

---

## Final Verification

After all tasks are complete:

- [ ] **Run full test suite**
```bash
uv run pytest tests/ -q --tb=short
```

- [ ] **Run linter**
```bash
uv run ruff check src/ tests/ --fix
```

- [ ] **Run type checker**
```bash
uv run pyright src/
```

- [ ] **Verify the app starts**
```bash
uv run agents &
sleep 3
curl -s http://localhost:8080/health | python -m json.tool
curl -s http://localhost:8080/api/metrics | python -m json.tool
kill %1
```

---

## Summary of Changes

| Task | What | New Files | Status |
|------|------|-----------|--------|
| 1 | Retry with exponential backoff | retry.py, test_retry.py | Pending |
| 2 | Automated cleanup | cleanup.py, test_cleanup.py | Pending |
| 3 | Deep health check | test_health_deep.py | Pending |
| 4 | GitHub Issues trigger | test_github_issues.py | Pending |
| 5 | Structured logging | — | Pending |
| 6 | Metrics API | metrics.py, test_metrics.py | Pending |
| 7 | Metrics dashboard widget | — | Pending |
| 8 | Rate limiting | rate_limit.py, test_rate_limit.py | Pending |
| 9 | CI lint step | — | Pending |
| 10 | DB schema versioning | db_version.py, test_db_version.py | Pending |
| 11 | Overnight digest | — | Pending |
| 12 | PCP trim | — | Pending |

**Parallelization:** Tasks 1-3 are independent. Tasks 4-5 are independent. Tasks 6-7 are sequential (7 depends on 6). Tasks 8-10 are independent. Task 11 depends on Task 6 (imports `collect_metrics`). Task 12 is independent. Maximize parallel execution within each phase.
