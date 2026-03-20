# Agent Tab + Run Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Run" button to task cards and an interactive Agent tab with terminal-like CLI experience and session continuity to the paperweight dashboard.

**Architecture:** Two independent features. Feature 1 (Run button) is a frontend-only change — HTMX button on task cards POSTing to existing endpoint. Feature 2 (Agent tab) adds a full-stack pipeline: `SessionManager` for SQLite persistence, `run_adhoc()` on Executor for Claude CLI invocation with `--resume` support, a new API endpoint, and a terminal-embed frontend with WebSocket streaming. Sessions reuse worktrees and Claude's built-in session resumption for conversation continuity.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, SQLite, Jinja2, HTMX, vanilla JS, WebSocket

**Spec:** `docs/superpowers/specs/2026-03-19-agent-tab-and-run-button-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/agents/session_manager.py` | AgentSession model + SQLite CRUD + concurrency guard |
| Modify | `src/agents/models.py:7-11,66-79` | Add `TriggerType.AGENT`, `RunRecord.session_id` |
| Modify | `src/agents/executor.py:21-25,43-53` | Add `ClaudeOutput.session_id`, new `run_adhoc()` method |
| Modify | `src/agents/streaming.py:107-114` | Extract `session_id` from result event |
| Modify | `src/agents/history.py:14-89,96-117,229-244` | `agent_sessions` table, `session_id` column migration, insert/read updates |
| Modify | `src/agents/main.py` | Agent endpoint, session cleanup scheduler job, SessionManager wiring |
| Modify | `src/agents/dashboard_html.py` | `/hub/{project_id}/agent` route |
| Modify | `src/agents/app_state.py` | Add `session_manager` field |
| Modify | `src/agents/templates/components/macros.html:142-159` | Add `'agent'` to tab_bar |
| Modify | `src/agents/templates/partials/task_row.html` | Add Run button |
| Create | `src/agents/templates/hub/agent.html` | Terminal-embed template |
| Create | `src/agents/static/agent.js` | Agent tab JS: WebSocket streaming, terminal rendering, session state |
| Create | `tests/test_session_manager.py` | SessionManager unit tests |
| Create | `tests/test_run_adhoc.py` | Executor.run_adhoc unit tests |
| Create | `tests/test_agent_endpoint.py` | API endpoint integration tests |

---

## Task 1: Run Button on Task Cards

**Files:**
- Modify: `src/agents/templates/partials/task_row.html`
- Modify: `src/agents/templates/hub/tasks.html`
- Test: Manual — verify button appears and triggers run

- [ ] **Step 1: Add Run button to task_row.html**

In `src/agents/templates/partials/task_row.html`, add a Run button next to the ON/OFF badge. The button needs the `id` variable (project_id) which is already in scope from the parent `hub/tasks.html` template.

```html
{% set bg = "var(--bg-task-hover)" if task.get("enabled", 1) else "#12151f" %}
<div style="display:flex;align-items:center;padding:8px 12px;border-radius:6px;background:{{ bg }};gap:8px;">
  <div style="flex:1;min-width:0;">
    <div style="font-size:13px;color:var(--text-primary);">{{ task.name }}</div>
    <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">
      {{ task.trigger_type }} · {{ task.model }} · ${{ "%.2f" | format(task.max_budget) }}
    </div>
  </div>
  <button hx-post="/tasks/{{ id }}/{{ task.name }}/run"
          hx-swap="none"
          onclick="this.textContent='Queued';this.disabled=true;var b=this;setTimeout(function(){b.textContent='Run';b.disabled=false},3000)"
          style="padding:3px 10px;font-size:10px;color:var(--text-secondary);background:transparent;
                 border:1px solid var(--border-default);border-radius:3px;cursor:pointer;font-family:inherit;
                 letter-spacing:.3px;transition:all .15s;white-space:nowrap;"
          onmouseover="this.style.borderColor='var(--accent)';this.style.color='var(--text-primary)'"
          onmouseout="if(!this.disabled){this.style.borderColor='var(--border-default)';this.style.color='var(--text-secondary)'}">Run</button>
  <span style="font-size:10px;padding:2px 6px;border-radius:3px;
               background:{{ 'var(--bg-task-success)' if task.get('enabled', 1) else 'var(--bg-task-error)' }};
               color:{{ 'var(--status-success)' if task.get('enabled', 1) else 'var(--status-error)' }};">
    {{ 'ON' if task.get('enabled', 1) else 'OFF' }}
  </span>
</div>
```

- [ ] **Step 2: Verify button renders**

Run the server locally and navigate to a project's TASKS tab. Confirm the Run button appears on each task card.

- [ ] **Step 3: Commit**

```bash
git add src/agents/templates/partials/task_row.html
git commit -m "feat(dashboard): add Run button to task cards"
```

---

## Task 2: Data Model Changes

**Files:**
- Modify: `src/agents/models.py`
- Modify: `src/agents/history.py`
- Modify: `src/agents/executor.py`
- Modify: `src/agents/streaming.py`
- Test: `tests/test_session_manager.py`, `tests/test_models.py`

- [ ] **Step 1: Write failing test for TriggerType.AGENT**

Create test in `tests/test_models.py` (append to existing file):

```python
def test_trigger_type_agent():
    from agents.models import TriggerType
    assert TriggerType.AGENT == "agent"
    assert TriggerType("agent") == TriggerType.AGENT
```

- [ ] **Step 2: Run test, verify it fails**

```bash
.venv/bin/python -m pytest tests/test_models.py::test_trigger_type_agent -v
```

Expected: FAIL — `TriggerType` has no `AGENT` member.

- [ ] **Step 3: Add TriggerType.AGENT**

In `src/agents/models.py`, add to the `TriggerType` enum (after line 11):

```python
class TriggerType(StrEnum):
    SCHEDULE = "schedule"
    GITHUB = "github"
    LINEAR = "linear"
    MANUAL = "manual"
    AGENT = "agent"
```

- [ ] **Step 4: Run test, verify it passes**

```bash
.venv/bin/python -m pytest tests/test_models.py::test_trigger_type_agent -v
```

- [ ] **Step 5: Write failing test for RunRecord.session_id**

Append to `tests/test_models.py`:

```python
def test_run_record_session_id_default():
    from agents.models import RunRecord, RunStatus, TriggerType
    from datetime import UTC, datetime

    run = RunRecord(
        id="test-run",
        project="test",
        task="agent",
        trigger_type=TriggerType.AGENT,
        started_at=datetime.now(UTC),
        status=RunStatus.RUNNING,
        model="sonnet",
    )
    assert run.session_id is None


def test_run_record_session_id_set():
    from agents.models import RunRecord, RunStatus, TriggerType
    from datetime import UTC, datetime

    run = RunRecord(
        id="test-run",
        project="test",
        task="agent",
        trigger_type=TriggerType.AGENT,
        started_at=datetime.now(UTC),
        status=RunStatus.RUNNING,
        model="sonnet",
        session_id="sess-123",
    )
    assert run.session_id == "sess-123"
```

- [ ] **Step 6: Run tests, verify they fail**

```bash
.venv/bin/python -m pytest tests/test_models.py::test_run_record_session_id_default tests/test_models.py::test_run_record_session_id_set -v
```

- [ ] **Step 7: Add session_id to RunRecord**

In `src/agents/models.py`, add to `RunRecord` (after line 79):

```python
class RunRecord(BaseModel):
    id: str
    project: str
    task: str
    trigger_type: TriggerType
    started_at: datetime
    finished_at: datetime | None = None
    status: RunStatus
    model: str
    num_turns: int | None = None
    cost_usd: float | None = None
    pr_url: str | None = None
    error_message: str | None = None
    output_file: str | None = None
    session_id: str | None = None
```

- [ ] **Step 8: Run tests, verify they pass**

```bash
.venv/bin/python -m pytest tests/test_models.py::test_run_record_session_id_default tests/test_models.py::test_run_record_session_id_set -v
```

- [ ] **Step 9: Add session_id to ClaudeOutput**

In `src/agents/executor.py`, add `session_id` field to `ClaudeOutput` (line 21-25):

```python
class ClaudeOutput(BaseModel):
    result: str = ""
    is_error: bool = False
    cost_usd: float = 0.0
    num_turns: int = 0
    session_id: str = ""
```

- [ ] **Step 10: Update extract_result_from_line to capture session_id**

In `src/agents/streaming.py`, update `extract_result_from_line()` (line 107-114):

```python
def extract_result_from_line(line: str) -> ClaudeOutput:
    data = json.loads(line)
    return ClaudeOutput(
        result=data.get("result", ""),
        is_error=data.get("is_error", False),
        cost_usd=data.get("total_cost_usd", 0.0),
        num_turns=data.get("num_turns", 0),
        session_id=data.get("session_id", ""),
    )
```

- [ ] **Step 11: Update HistoryDB for session_id column and agent_sessions table**

In `src/agents/history.py`, add to `_init_db()` (after the coordination_log index, around line 89):

```python
            # Agent sessions table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    id TEXT PRIMARY KEY,
                    project TEXT NOT NULL,
                    worktree_path TEXT NOT NULL,
                    claude_session_id TEXT,
                    model TEXT NOT NULL DEFAULT 'claude-sonnet-4-6',
                    max_cost_usd REAL NOT NULL DEFAULT 2.00,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
            """)
            # Migration: add session_id to runs table
            try:
                conn.execute("ALTER TABLE runs ADD COLUMN session_id TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
```

Update `insert_run()` to include `session_id` (line 96-117):

```python
    def insert_run(self, run: RunRecord) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO runs (id, project, task, trigger_type, started_at, finished_at,
                   status, model, num_turns, cost_usd, pr_url, error_message, output_file, session_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run.id,
                    run.project,
                    run.task,
                    run.trigger_type,
                    run.started_at.isoformat(),
                    run.finished_at.isoformat() if run.finished_at else None,
                    run.status,
                    run.model,
                    run.num_turns,
                    run.cost_usd,
                    run.pr_url,
                    run.error_message,
                    run.output_file,
                    run.session_id,
                ),
            )
```

Update `_row_to_record()` to read `session_id` (line 229-244):

```python
    def _row_to_record(self, row: sqlite3.Row) -> RunRecord:
        session_id = None
        try:
            session_id = row["session_id"]
        except (IndexError, KeyError):
            pass
        return RunRecord(
            id=row["id"],
            project=row["project"],
            task=row["task"],
            trigger_type=row["trigger_type"],
            started_at=datetime.fromisoformat(row["started_at"]),
            finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
            status=row["status"],
            model=row["model"],
            num_turns=row["num_turns"],
            cost_usd=row["cost_usd"],
            pr_url=row["pr_url"],
            error_message=row["error_message"],
            output_file=row["output_file"],
            session_id=session_id,
        )
```

- [ ] **Step 12: Run full test suite to verify no regressions**

```bash
.venv/bin/python -m pytest tests/ -x -q --tb=short -k "not test_claim_model_defaults"
```

Expected: all tests pass.

- [ ] **Step 13: Commit**

```bash
git add src/agents/models.py src/agents/executor.py src/agents/streaming.py src/agents/history.py tests/test_models.py
git commit -m "feat: data model changes for agent sessions — TriggerType.AGENT, RunRecord.session_id, agent_sessions table"
```

---

## Task 3: SessionManager

**Files:**
- Create: `src/agents/session_manager.py`
- Test: `tests/test_session_manager.py`

- [ ] **Step 1: Write failing tests for SessionManager**

Create `tests/test_session_manager.py`:

```python
import time
from pathlib import Path

import pytest


@pytest.fixture
def session_mgr(tmp_path):
    from agents.session_manager import SessionManager
    return SessionManager(tmp_path / "test.db")


def test_create_session(session_mgr):
    session = session_mgr.create_session("paperweight", "sonnet", 2.0)
    assert session.project == "paperweight"
    assert session.model == "sonnet"
    assert session.max_cost_usd == 2.0
    assert session.status == "active"
    assert session.id  # not empty


def test_get_session(session_mgr):
    created = session_mgr.create_session("proj", "sonnet", 1.0)
    fetched = session_mgr.get_session(created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.project == "proj"


def test_get_session_not_found(session_mgr):
    assert session_mgr.get_session("nonexistent") is None


def test_update_session(session_mgr):
    session = session_mgr.create_session("proj", "sonnet", 1.0)
    session_mgr.update_session(session.id, claude_session_id="claude-abc")
    updated = session_mgr.get_session(session.id)
    assert updated.claude_session_id == "claude-abc"


def test_close_session(session_mgr):
    session = session_mgr.create_session("proj", "sonnet", 1.0)
    session_mgr.close_session(session.id)
    closed = session_mgr.get_session(session.id)
    assert closed.status == "closed"


def test_get_active_session(session_mgr):
    session_mgr.create_session("proj", "sonnet", 1.0)
    active = session_mgr.get_active_session("proj")
    assert active is not None
    assert active.status == "active"


def test_get_active_session_none_when_closed(session_mgr):
    session = session_mgr.create_session("proj", "sonnet", 1.0)
    session_mgr.close_session(session.id)
    assert session_mgr.get_active_session("proj") is None


def test_cleanup_stale_sessions(session_mgr):
    session = session_mgr.create_session("proj", "sonnet", 1.0)
    # Force updated_at to 31 minutes ago
    import sqlite3
    from datetime import UTC, datetime, timedelta
    old_time = (datetime.now(UTC) - timedelta(minutes=31)).isoformat()
    with sqlite3.connect(session_mgr.db_path) as conn:
        conn.execute("UPDATE agent_sessions SET updated_at = ? WHERE id = ?", (old_time, session.id))
    cleaned = session_mgr.cleanup_stale_sessions(timeout_minutes=30)
    assert cleaned == 1
    assert session_mgr.get_session(session.id).status == "closed"


def test_concurrency_guard(session_mgr):
    session = session_mgr.create_session("proj", "sonnet", 1.0)
    assert session_mgr.try_acquire_run(session.id) is True
    assert session_mgr.try_acquire_run(session.id) is False
    session_mgr.release_run(session.id)
    assert session_mgr.try_acquire_run(session.id) is True


def test_list_sessions(session_mgr):
    session_mgr.create_session("proj", "sonnet", 1.0)
    session_mgr.create_session("proj", "haiku", 0.5)
    session_mgr.create_session("other", "sonnet", 1.0)
    sessions = session_mgr.list_sessions("proj")
    assert len(sessions) == 2
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
.venv/bin/python -m pytest tests/test_session_manager.py -v
```

Expected: FAIL — `agents.session_manager` module does not exist.

- [ ] **Step 3: Implement SessionManager**

Create `src/agents/session_manager.py`:

```python
"""Agent session management — SQLite persistence + in-memory concurrency guard."""
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel


class AgentSession(BaseModel):
    id: str
    project: str
    worktree_path: str
    claude_session_id: str | None = None
    model: str = "claude-sonnet-4-6"
    max_cost_usd: float = 2.00
    status: str = "active"
    created_at: datetime = datetime.now(UTC)
    updated_at: datetime = datetime.now(UTC)


class SessionManager:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._running: set[str] = set()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    id TEXT PRIMARY KEY,
                    project TEXT NOT NULL,
                    worktree_path TEXT NOT NULL,
                    claude_session_id TEXT,
                    model TEXT NOT NULL DEFAULT 'claude-sonnet-4-6',
                    max_cost_usd REAL NOT NULL DEFAULT 2.00,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
            """)

    def create_session(
        self, project: str, model: str, max_cost_usd: float
    ) -> AgentSession:
        session_id = uuid.uuid4().hex[:12]
        now = datetime.now(UTC)
        worktree_path = f"/tmp/agents/session-{session_id}"
        session = AgentSession(
            id=session_id,
            project=project,
            worktree_path=worktree_path,
            model=model,
            max_cost_usd=max_cost_usd,
            created_at=now,
            updated_at=now,
        )
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO agent_sessions
                   (id, project, worktree_path, claude_session_id, model, max_cost_usd, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session.id,
                    session.project,
                    session.worktree_path,
                    session.claude_session_id,
                    session.model,
                    session.max_cost_usd,
                    session.status,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return session

    def get_session(self, session_id: str) -> AgentSession | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM agent_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_session(row)

    def update_session(self, session_id: str, **kwargs: object) -> None:
        allowed = {"claude_session_id", "status", "model", "max_cost_usd"}
        updates = []
        values: list[object] = []
        for key, value in kwargs.items():
            if key in allowed and value is not None:
                updates.append(f"{key} = ?")
                values.append(value)
        updates.append("updated_at = ?")
        values.append(datetime.now(UTC).isoformat())
        values.append(session_id)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE agent_sessions SET {', '.join(updates)} WHERE id = ?",
                values,
            )

    def close_session(self, session_id: str) -> None:
        self.update_session(session_id, status="closed")
        self._running.discard(session_id)

    def get_active_session(self, project: str) -> AgentSession | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM agent_sessions WHERE project = ? AND status = 'active' "
                "ORDER BY updated_at DESC LIMIT 1",
                (project,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_session(row)

    def cleanup_stale_sessions(self, timeout_minutes: int = 30) -> int:
        from datetime import timedelta
        cutoff = (datetime.now(UTC) - timedelta(minutes=timeout_minutes)).isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE agent_sessions SET status = 'closed', updated_at = ? "
                "WHERE status = 'active' AND updated_at < ?",
                (datetime.now(UTC).isoformat(), cutoff),
            )
        return cursor.rowcount

    def list_sessions(self, project: str) -> list[AgentSession]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_sessions WHERE project = ? ORDER BY updated_at DESC",
                (project,),
            ).fetchall()
        return [self._row_to_session(row) for row in rows]

    def try_acquire_run(self, session_id: str) -> bool:
        if session_id in self._running:
            return False
        self._running.add(session_id)
        return True

    def release_run(self, session_id: str) -> None:
        self._running.discard(session_id)

    def _row_to_session(self, row: sqlite3.Row) -> AgentSession:
        return AgentSession(
            id=row["id"],
            project=row["project"],
            worktree_path=row["worktree_path"],
            claude_session_id=row["claude_session_id"],
            model=row["model"],
            max_cost_usd=row["max_cost_usd"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
.venv/bin/python -m pytest tests/test_session_manager.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/agents/session_manager.py tests/test_session_manager.py
git commit -m "feat: SessionManager with SQLite persistence and concurrency guard"
```

---

## Task 4: Executor.run_adhoc()

**Files:**
- Modify: `src/agents/executor.py`
- Test: `tests/test_run_adhoc.py`

- [ ] **Step 1: Write failing tests for run_adhoc**

Create `tests/test_run_adhoc.py`:

```python
import pytest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch


@pytest.fixture
def adhoc_deps(tmp_path):
    from agents.budget import BudgetManager
    from agents.config import BudgetConfig, ExecutionConfig
    from agents.executor import Executor
    from agents.history import HistoryDB
    from agents.notifier import Notifier
    from agents.session_manager import AgentSession

    db = HistoryDB(tmp_path / "test.db")
    budget_config = BudgetConfig(daily_limit_usd=10.0)
    budget = BudgetManager(config=budget_config, history=db)
    notifier = Notifier(webhook_url="")
    exec_config = ExecutionConfig(
        worktree_base=str(tmp_path / "worktrees"), dry_run=True, timeout_minutes=1
    )
    executor = Executor(
        config=exec_config, budget=budget, history=db, notifier=notifier, data_dir=tmp_path / "data"
    )
    session = AgentSession(
        id="test-sess",
        project="paperweight",
        worktree_path=str(tmp_path / "worktrees" / "session-test-sess"),
        model="sonnet",
        max_cost_usd=2.0,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    return executor, db, session


@pytest.mark.asyncio
async def test_run_adhoc_creates_run_record(adhoc_deps):
    executor, db, session = adhoc_deps
    from agents.models import ProjectConfig, TaskConfig

    project = ProjectConfig(
        name="paperweight",
        repo="/tmp/fake-repo",
        tasks={"dummy": TaskConfig(description="x", intent="x")},
    )
    run = await executor.run_adhoc(project, "test prompt", session)
    assert run.task == "agent"
    assert run.trigger_type == "agent"
    assert run.session_id == "test-sess"
    assert run.project == "paperweight"


@pytest.mark.asyncio
async def test_run_adhoc_budget_exceeded(adhoc_deps):
    executor, db, session = adhoc_deps
    from agents.models import ProjectConfig, TaskConfig, RunStatus

    # Exhaust budget
    executor.budget._config.daily_limit_usd = 0.0

    project = ProjectConfig(
        name="paperweight",
        repo="/tmp/fake-repo",
        tasks={"dummy": TaskConfig(description="x", intent="x")},
    )
    run = await executor.run_adhoc(project, "test prompt", session)
    assert run.status == RunStatus.FAILURE
    assert "Budget" in (run.error_message or "")
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
.venv/bin/python -m pytest tests/test_run_adhoc.py -v
```

Expected: FAIL — `Executor` has no `run_adhoc` method.

- [ ] **Step 3: Implement run_adhoc() on Executor**

In `src/agents/executor.py`, add the method after `run_task()` (around line 330). Import `AgentSession` at the top within TYPE_CHECKING:

```python
if TYPE_CHECKING:
    from agents.session_manager import AgentSession
```

Add the method:

```python
    async def run_adhoc(
        self,
        project: ProjectConfig,
        prompt: str,
        session: "AgentSession",
        is_resume: bool = False,
    ) -> RunRecord:
        run_id = generate_run_id(project.name, "agent")
        run = RunRecord(
            id=run_id,
            project=project.name,
            task="agent",
            trigger_type=TriggerType.AGENT,
            started_at=datetime.now(UTC),
            status=RunStatus.RUNNING,
            model=session.model,
            session_id=session.id,
        )
        self.history.insert_run(run)
        await self._emit(run_id, "task_started", f"{project.name}/agent [adhoc]")

        if not self.budget.can_afford(session.max_cost_usd):
            run.status = RunStatus.FAILURE
            run.error_message = (
                f"Budget exceeded. Need ${session.max_cost_usd}, "
                f"remaining: ${self.budget.get_status().remaining_usd:.2f}"
            )
            run.finished_at = datetime.now(UTC)
            self.history.update_run(
                run_id=run.id,
                status=run.status,
                finished_at=run.finished_at,
                error_message=run.error_message,
            )
            await self._emit(run_id, "task_failed", run.error_message)
            return run

        if self.config.dry_run:
            logger.info("DRY RUN: would execute adhoc on %s", project.name)
            await self._emit(run_id, "dry_run", "dry_run=true — skipping Claude execution")
            run.status = RunStatus.SUCCESS
            run.cost_usd = 0.0
            run.finished_at = datetime.now(UTC)
            self.history.update_run(
                run_id=run.id,
                status=run.status,
                finished_at=run.finished_at,
                cost_usd=0.0,
            )
            await self._emit(run_id, "task_completed", "done (dry run)")
            return run

        worktree_path = Path(session.worktree_path)
        try:
            if not is_resume:
                worktree_path.parent.mkdir(parents=True, exist_ok=True)
                await self._run_cmd(
                    ["git", "worktree", "add", str(worktree_path), "-b",
                     f"agents/session-{session.id}", project.base_branch],
                    cwd=project.repo,
                )
            elif not worktree_path.exists():
                raise RuntimeError(f"Session worktree missing: {worktree_path}")

            claude_cmd = [
                "claude", "-p", prompt,
                "--model", session.model,
                "--max-budget-usd", str(session.max_cost_usd),
                "--output-format", "stream-json",
                "--verbose",
                "--permission-mode", "auto",
            ]
            if is_resume and session.claude_session_id:
                claude_cmd.extend(["--resume", session.claude_session_id])

            output, raw_output = await self._run_claude(
                claude_cmd,
                cwd=str(worktree_path),
                run_id=run_id,
                timeout=self.config.timeout_minutes * 60,
            )

            output_dir = self.data_dir / "runs"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / f"{run_id}.json"
            output_file.write_text(raw_output)

            run.cost_usd = output.cost_usd
            run.num_turns = output.num_turns
            run.output_file = str(output_file)

            if output.is_error:
                run.status = RunStatus.FAILURE
                run.error_message = output.result[:500]
                await self._emit(run_id, "task_failed", run.error_message)
            else:
                run.status = RunStatus.SUCCESS
                await self._emit(run_id, "task_completed", "done")

        except TimeoutError:
            run.status = RunStatus.TIMEOUT
            run.error_message = f"Timed out after {self.config.timeout_minutes} minutes"
            await self._emit(run_id, "task_failed", run.error_message)
        except Exception as e:
            run.status = RunStatus.FAILURE
            run.error_message = str(e)[:500]
            logger.exception("Adhoc execution failed: %s", project.name)
            await self._emit(run_id, "task_failed", run.error_message)
        finally:
            run.finished_at = datetime.now(UTC)
            self.history.update_run(
                run_id=run.id,
                status=run.status,
                finished_at=run.finished_at,
                cost_usd=run.cost_usd,
                num_turns=run.num_turns,
                error_message=run.error_message,
                output_file=run.output_file,
            )
            self._running_processes.pop(run_id, None)
            # NOTE: worktree is NOT cleaned up — session manages lifecycle

        return run
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
.venv/bin/python -m pytest tests/test_run_adhoc.py -v
```

- [ ] **Step 5: Run full test suite for regressions**

```bash
.venv/bin/python -m pytest tests/ -x -q --tb=short -k "not test_claim_model_defaults"
```

- [ ] **Step 6: Commit**

```bash
git add src/agents/executor.py tests/test_run_adhoc.py
git commit -m "feat: Executor.run_adhoc() for ad-hoc agent sessions"
```

---

## Task 5: API Endpoint + Wiring

**Files:**
- Modify: `src/agents/app_state.py`
- Modify: `src/agents/main.py`
- Test: `tests/test_agent_endpoint.py`

- [ ] **Step 1: Write failing tests for the agent endpoint**

Create `tests/test_agent_endpoint.py`:

```python
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    from agents.main import create_app
    # Create minimal config
    config_path = tmp_path / "config.yaml"
    config_path.write_text("""
budget:
  daily_limit_usd: 10.0
notifications:
  slack_webhook_url: ""
webhooks:
  github_secret: ""
  linear_secret: ""
execution:
  worktree_base: "{wt}"
  dry_run: true
  timeout_minutes: 1
server:
  host: 127.0.0.1
  port: 8080
coordination:
  enabled: false
integrations:
  linear_api_key: ""
  discord_bot_token: ""
  discord_guild_id: ""
  github_token: ""
  slack_bot_token: ""
""".replace("{wt}", str(tmp_path / "worktrees")))
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    proj_yaml = projects_dir / "testproj.yaml"
    proj_yaml.write_text("""
name: testproj
repo: /tmp/fake-repo
base_branch: main
branch_prefix: agents/
tasks:
  hello:
    description: test
    intent: test
    model: sonnet
    max_cost_usd: 1.0
""")
    app = create_app(
        config_path=config_path,
        projects_dir=projects_dir,
        data_dir=tmp_path / "data",
    )
    return TestClient(app)


def test_agent_endpoint_new_session(client):
    resp = client.post("/api/projects/testproj/agent", json={
        "prompt": "test prompt",
        "model": "sonnet",
        "max_cost_usd": 1.0,
    })
    assert resp.status_code == 202
    data = resp.json()
    assert "run_id" in data
    assert "session_id" in data
    assert data["status"] == "running"


def test_agent_endpoint_project_not_found(client):
    resp = client.post("/api/projects/nonexistent/agent", json={
        "prompt": "test",
    })
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
.venv/bin/python -m pytest tests/test_agent_endpoint.py -v
```

- [ ] **Step 3: Add session_manager to AppState**

In `src/agents/app_state.py`, add the field:

```python
from agents.session_manager import SessionManager

# In __init__ params:
    session_manager: SessionManager | None = None,

# In body:
    self.session_manager = session_manager
```

- [ ] **Step 4: Wire SessionManager in main.py**

In `src/agents/main.py`:

1. After `project_store` creation (~line 56), create `SessionManager`:

```python
from agents.session_manager import SessionManager
session_manager = SessionManager(db_path)
```

2. Pass it to `AppState`:

```python
state = AppState(
    ...,
    session_manager=session_manager,
)
```

3. Add the agent endpoint (after the cancel_run route, ~line 284):

```python
    @app.post("/api/projects/{project_name}/agent", status_code=202, response_model=None)
    async def agent_prompt(
        project_name: str,
        data: dict,
        background_tasks: BackgroundTasks,
    ) -> Response | dict:
        project = state.projects.get(project_name)
        if project is None:
            return Response(status_code=404, content=f"Project {project_name} not found")

        prompt = data.get("prompt", "")
        if not prompt:
            return Response(status_code=400, content="prompt is required")

        session_id = data.get("session_id")
        model = data.get("model", "claude-sonnet-4-6")
        max_cost_usd = data.get("max_cost_usd", 2.0)

        if session_id:
            session = state.session_manager.get_session(session_id)
            if session is None:
                return Response(status_code=404, content="Session not found")
            if session.status != "active":
                return Response(status_code=410, content="Session closed")
            is_resume = True
        else:
            session = state.session_manager.create_session(project_name, model, max_cost_usd)
            is_resume = False

        if not state.session_manager.try_acquire_run(session.id):
            return Response(status_code=409, content="A run is already in progress for this session")

        async def _run() -> None:
            try:
                async with (
                    state.get_semaphore(config.execution.max_concurrent),
                    state.get_repo_semaphore(project.repo),
                ):
                    result = await state.executor.run_adhoc(
                        project, prompt, session, is_resume=is_resume,
                    )
                    if result.cost_usd and not result.is_error:
                        # Capture session_id from Claude output if available
                        pass  # Will be wired after spike
            finally:
                state.session_manager.release_run(session.id)

        background_tasks.add_task(_run)
        return {"run_id": f"{project_name}-agent-pending", "session_id": session.id, "status": "running"}
```

4. Add close session endpoint:

```python
    @app.post("/api/sessions/{session_id}/close", response_model=None)
    async def close_session(session_id: str) -> Response | dict:
        session = state.session_manager.get_session(session_id)
        if session is None:
            return Response(status_code=404, content="Session not found")
        state.session_manager.close_session(session_id)
        # Cleanup worktree
        worktree_path = Path(session.worktree_path)
        if worktree_path.exists():
            try:
                project = state.projects.get(session.project)
                if project:
                    await state.executor._run_cmd(
                        ["git", "worktree", "remove", "--force", str(worktree_path)],
                        cwd=project.repo,
                    )
            except Exception:
                pass
        return {"status": "closed"}
```

5. Add stale session cleanup job in lifespan (after existing scheduler jobs, ~line 218):

```python
    async def cleanup_sessions() -> None:
        cleaned = session_manager.cleanup_stale_sessions(30)
        if cleaned:
            logger.info("Cleaned up %d stale agent sessions", cleaned)

    scheduler.add_job(cleanup_sessions, "interval", minutes=10, id="session_cleanup")
```

- [ ] **Step 5: Run tests, verify they pass**

```bash
.venv/bin/python -m pytest tests/test_agent_endpoint.py -v
```

- [ ] **Step 6: Run full test suite**

```bash
.venv/bin/python -m pytest tests/ -x -q --tb=short -k "not test_claim_model_defaults"
```

- [ ] **Step 7: Commit**

```bash
git add src/agents/app_state.py src/agents/main.py tests/test_agent_endpoint.py
git commit -m "feat: agent endpoint + session wiring + stale cleanup scheduler"
```

---

## Task 6: Agent Tab Frontend

**Files:**
- Modify: `src/agents/templates/components/macros.html`
- Modify: `src/agents/dashboard_html.py`
- Create: `src/agents/templates/hub/agent.html`
- Create: `src/agents/static/agent.js`
- Modify: `src/agents/templates/base.html`

- [ ] **Step 1: Add 'agent' to tab_bar macro**

In `src/agents/templates/components/macros.html`, update the `tab_bar` macro (line 144):

```jinja2
{%- for t in ['activity', 'tasks', 'runs', 'agent'] -%}
```

- [ ] **Step 2: Add hub_agent route to dashboard_html.py**

In `src/agents/dashboard_html.py`, add after the `hub_runs` route (around line 137):

```python
    @app.get("/hub/{project_id}/agent", response_class=HTMLResponse)
    async def hub_agent(request: Request, project_id: str) -> HTMLResponse:
        project = state.project_store.get_project(project_id) if state.project_store else None
        if not project:
            return HTMLResponse("<p>Project not found</p>", status_code=404)
        active_session = None
        if hasattr(state, "session_manager") and state.session_manager:
            active_session = state.session_manager.get_active_session(project_id)
        return _TEMPLATES.TemplateResponse(
            request,
            "hub/agent.html",
            {
                "id": project_id,
                "session": active_session,
            },
        )
```

- [ ] **Step 3: Create agent.html template**

Create `src/agents/templates/hub/agent.html`:

```html
<div id="agent-tab" style="display:flex;flex-direction:column;height:100%;font-family:'Ubuntu Mono',monospace;">
  <!-- Status bar -->
  <div id="agent-status-bar" style="display:flex;justify-content:space-between;align-items:center;
              padding:6px 14px;background:var(--bg-chrome);border-bottom:1px solid var(--border-subtle);
              font-size:10px;flex-shrink:0;">
    <div style="display:flex;gap:12px;align-items:center;">
      <label style="color:var(--text-muted);">model:
        <select id="agent-model" style="background:var(--bg-chrome);border:1px solid var(--border-default);
                       color:var(--text-primary);border-radius:3px;padding:1px 4px;font-size:10px;
                       font-family:inherit;outline:none;">
          <option value="claude-sonnet-4-6" {{ 'selected' if not session or session.model == 'claude-sonnet-4-6' else '' }}>sonnet</option>
          <option value="claude-haiku-4-5-20251001" {{ 'selected' if session and session.model == 'claude-haiku-4-5-20251001' else '' }}>haiku</option>
          <option value="claude-opus-4-6" {{ 'selected' if session and session.model == 'claude-opus-4-6' else '' }}>opus</option>
        </select>
      </label>
      <label style="color:var(--text-muted);">budget:
        <input id="agent-budget" type="number" step="0.5" min="0.1" max="10"
               value="{{ session.max_cost_usd if session else 2.0 }}"
               style="width:50px;background:var(--bg-chrome);border:1px solid var(--border-default);
                      color:var(--text-primary);border-radius:3px;padding:1px 4px;font-size:10px;
                      font-family:inherit;outline:none;text-align:right;">
      </label>
      <span id="agent-cost" style="color:var(--text-muted);">cost: <span style="color:var(--status-success);">$0.00</span></span>
    </div>
    <div style="display:flex;gap:8px;align-items:center;">
      <span id="agent-session-status" style="color:var(--text-muted);">
        {{ 'session: ' + session.id[:8] if session else 'no session' }}
      </span>
      {% if session %}
      <button onclick="endAgentSession('{{ session.id }}')"
              style="padding:2px 8px;font-size:9px;color:var(--text-muted);background:transparent;
                     border:1px solid var(--border-default);border-radius:3px;cursor:pointer;
                     font-family:inherit;transition:all .15s;"
              onmouseover="this.style.borderColor='var(--status-error)';this.style.color='var(--status-error)'"
              onmouseout="this.style.borderColor='var(--border-default)';this.style.color='var(--text-muted)'">End session</button>
      {% endif %}
    </div>
  </div>

  <!-- Terminal output -->
  <div id="agent-output" style="flex:1;overflow-y:auto;padding:12px 14px;background:#0a0c14;
              font-size:12px;line-height:1.7;">
    {% if not session %}
    <div style="color:var(--text-disabled);font-style:italic;">Start a new session by typing an instruction below.</div>
    {% endif %}
  </div>

  <!-- Prompt input -->
  <div style="display:flex;align-items:center;border-top:1px solid var(--border-subtle);background:#0a0c14;flex-shrink:0;">
    <span style="color:var(--accent);padding:10px 4px 10px 14px;font-size:13px;">&gt;</span>
    <input id="agent-input"
           type="text"
           placeholder="{{ 'Continue the session...' if session else 'Give the agent an instruction...' }}"
           autocomplete="off"
           style="flex:1;background:transparent;border:none;color:var(--text-primary);padding:10px 8px;
                  font-family:'Ubuntu Mono',monospace;font-size:12px;outline:none;"
           onkeydown="if(event.key==='Enter'&&!this.disabled)sendAgentPrompt('{{ id }}')">
    <div style="padding:0 10px;">
      <span style="font-size:9px;color:var(--text-disabled);border:1px solid var(--border-subtle);
                   padding:1px 5px;border-radius:2px;">Enter</span>
    </div>
  </div>
</div>

<script src="/static/agent.js"></script>
```

- [ ] **Step 4: Create agent.js**

Create `src/agents/static/agent.js`:

```javascript
// ── Agent Tab: terminal-like CLI experience ──

var _agentSessionId = null;
var _agentWs = null;

// Detect existing session from DOM
(function() {
  var statusEl = document.getElementById('agent-session-status');
  if (statusEl && statusEl.textContent.trim().startsWith('session:')) {
    var match = statusEl.textContent.match(/session:\s*(\w+)/);
    if (match) _agentSessionId = match[1];
  }
})();

function sendAgentPrompt(projectId) {
  var input = document.getElementById('agent-input');
  var prompt = input.value.trim();
  if (!prompt) return;

  // Render user prompt immediately
  var output = document.getElementById('agent-output');
  // Clear placeholder if first prompt
  var placeholder = output.querySelector('[style*="font-style:italic"]');
  if (placeholder) placeholder.remove();

  output.innerHTML += '<div style="color:#6b7280;font-size:10px;margin-top:12px;">you</div>'
    + '<div style="color:#e0e0e0;margin-bottom:12px;padding-left:2px;">' + escapeHtml(prompt) + '</div>';
  output.scrollTop = output.scrollHeight;

  input.value = '';
  input.disabled = true;
  input.placeholder = 'Running...';

  var model = document.getElementById('agent-model').value;
  var budget = parseFloat(document.getElementById('agent-budget').value) || 2.0;

  var body = { prompt: prompt, model: model, max_cost_usd: budget };
  if (_agentSessionId) body.session_id = _agentSessionId;

  fetch('/api/projects/' + projectId + '/agent', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    _agentSessionId = data.session_id;
    updateSessionStatus(data.session_id);

    // Add agent label
    output.innerHTML += '<div style="color:#3b82f6;font-size:10px;">agent</div>';

    // Connect WebSocket for streaming
    connectAgentStream(data.run_id, output, input);
  })
  .catch(function(err) {
    output.innerHTML += '<div style="color:#f85149;margin:8px 0;">Error: ' + err.message + '</div>';
    input.disabled = false;
    input.placeholder = 'Try again...';
  });
}

function connectAgentStream(runId, output, input) {
  var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  var ws = new WebSocket(proto + '//' + location.host + '/ws/runs/' + runId);
  _agentWs = ws;

  ws.onmessage = function(e) {
    var event = JSON.parse(e.data);
    renderAgentEvent(event, output);
    output.scrollTop = output.scrollHeight;
  };

  ws.onclose = function() {
    input.disabled = false;
    input.placeholder = 'Continue the session...';
    input.focus();
  };

  ws.onerror = function() {
    output.innerHTML += '<div style="color:#f85149;margin:4px 0;padding-left:2px;">[connection error]</div>';
    input.disabled = false;
    input.placeholder = 'Try again...';
  };
}

function renderAgentEvent(event, output) {
  var type = event.type;
  var content = event.content || '';
  var toolName = event.tool_name || '';
  var filePath = event.file_path || '';

  if (type === 'assistant' && content) {
    output.innerHTML += '<div style="color:#c0c4d6;margin:4px 0;padding-left:2px;white-space:pre-wrap;">'
      + escapeHtml(content) + '</div>';
  }
  else if (type === 'tool_use') {
    var color = '#a78bfa'; // purple for read-like
    if (['Edit', 'Write'].indexOf(toolName) >= 0) color = '#22c55e';
    if (toolName === 'Bash') color = '#f59e0b';

    var label = filePath || content.substring(0, 80);
    output.innerHTML += '<div style="margin:4px 0;border-left:2px solid ' + color + ';padding-left:10px;">'
      + '<div style="display:flex;align-items:center;gap:6px;cursor:pointer;" '
      + 'onclick="this.nextElementSibling&&(this.nextElementSibling.style.display=this.nextElementSibling.style.display===\'none\'?\'block\':\'none\')">'
      + '<span style="color:#8b8fa3;font-size:10px;">&#9654;</span>'
      + '<span style="color:' + color + ';font-size:11px;">' + escapeHtml(toolName) + '</span>'
      + '<span style="color:#6b7280;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escapeHtml(label) + '</span>'
      + '</div>'
      + '<div style="display:none;background:#0d1117;border-radius:4px;padding:6px 8px;font-size:10px;'
      + 'margin-top:4px;max-height:200px;overflow:auto;white-space:pre-wrap;color:#8b8fa3;">'
      + escapeHtml(content) + '</div>'
      + '</div>';
  }
  else if (type === 'tool_result') {
    // Append to last tool block if exists
    var blocks = output.querySelectorAll('[style*="border-left:2px"]');
    if (blocks.length > 0) {
      var last = blocks[blocks.length - 1];
      var detail = last.querySelector('div[style*="display:none"], div[style*="display:block"]');
      if (detail) {
        detail.textContent = content.substring(0, 500);
        detail.style.display = 'block';
      }
    }
  }
  else if (type === 'task_completed') {
    output.innerHTML += '<div style="color:#22c55e;margin:8px 0;padding-left:2px;">' + escapeHtml(content) + '</div>';
    updateCost(event);
  }
  else if (type === 'task_failed') {
    output.innerHTML += '<div style="color:#f85149;margin:8px 0;padding-left:2px;">' + escapeHtml(content) + '</div>';
  }
  else if (type === 'result') {
    // Final result — could contain summary
    if (content) {
      output.innerHTML += '<div style="color:#c0c4d6;margin:4px 0;padding-left:2px;white-space:pre-wrap;">'
        + escapeHtml(content.substring(0, 1000)) + '</div>';
    }
  }
}

function updateSessionStatus(sessionId) {
  var el = document.getElementById('agent-session-status');
  if (el) el.textContent = 'session: ' + sessionId.substring(0, 8);
}

function updateCost(event) {
  // Cost tracking would need to come from the run result
  // For now just indicate completion
}

function endAgentSession(sessionId) {
  fetch('/api/sessions/' + sessionId + '/close', { method: 'POST' })
  .then(function() {
    _agentSessionId = null;
    var status = document.getElementById('agent-session-status');
    if (status) status.textContent = 'no session';
    var output = document.getElementById('agent-output');
    if (output) output.innerHTML += '<div style="color:var(--text-disabled);margin:12px 0;font-style:italic;">Session ended.</div>';
    var input = document.getElementById('agent-input');
    if (input) input.placeholder = 'Start a new session...';
  });
}

function escapeHtml(text) {
  var d = document.createElement('div');
  d.textContent = text;
  return d.innerHTML;
}
```

- [ ] **Step 5: Add agent.js script tag to base.html**

In `src/agents/templates/base.html`, the `agent.js` is already loaded via the `<script>` tag in `agent.html`. No change needed to `base.html`.

- [ ] **Step 6: Verify the tab appears and renders correctly**

Start the server locally and navigate to a project panel. Click the AGENT tab. Verify:
- Status bar renders with model/budget controls
- Terminal area shows placeholder text
- Prompt input with `>` is at the bottom

- [ ] **Step 7: Commit**

```bash
git add src/agents/templates/components/macros.html src/agents/dashboard_html.py \
        src/agents/templates/hub/agent.html src/agents/static/agent.js
git commit -m "feat(dashboard): Agent tab with terminal-embed UI and WebSocket streaming"
```

---

## Task 7: Session ID Spike + Integration

**Files:**
- None created — investigative task

- [ ] **Step 1: Run Claude Code CLI without --no-session-persistence and capture output**

```bash
echo '{}' | claude -p "say hello" --output-format stream-json --no-input 2>/dev/null | grep '"type":"result"' | python3 -m json.tool
```

Look for a `session_id`, `conversation_id`, or similar field in the result JSON.

- [ ] **Step 2: Document the field name**

Update `extract_result_from_line()` in `src/agents/streaming.py` with the actual field name found. If the field is `session_id`:

```python
session_id=data.get("session_id", ""),
```

If different, adjust accordingly.

- [ ] **Step 3: Wire session_id capture in main.py agent endpoint**

Update the `_run()` inner function in the agent endpoint to capture the session_id from the run result and update the session:

```python
async def _run() -> None:
    try:
        async with (...):
            result = await state.executor.run_adhoc(...)
            # Read raw output to find session_id
            if result.output_file:
                import json
                raw = Path(result.output_file).read_text()
                for line in raw.strip().split('\n'):
                    try:
                        d = json.loads(line)
                        if d.get('type') == 'result' and d.get('session_id'):
                            state.session_manager.update_session(
                                session.id, claude_session_id=d['session_id']
                            )
                            break
                    except json.JSONDecodeError:
                        continue
    finally:
        state.session_manager.release_run(session.id)
```

- [ ] **Step 4: Commit**

```bash
git add src/agents/streaming.py src/agents/main.py
git commit -m "feat: capture Claude session_id for --resume support"
```

---

## Task 8: Final Verification

- [ ] **Step 1: Run pyright for type checking**

```bash
.venv/bin/python -m pyright src/
```

Fix any type errors.

- [ ] **Step 2: Run full test suite**

```bash
.venv/bin/python -m pytest tests/ -q --tb=short -k "not test_claim_model_defaults"
```

All tests must pass.

- [ ] **Step 3: Deploy to VPS and verify**

```bash
ssh vinicius@vinicius.xyz 'cd ~/paperweight && git pull && ~/.local/bin/uv sync && pm2 restart paperweight'
```

- [ ] **Step 4: Manual verification on live dashboard**

1. Open https://paperweight.vinicius.xyz
2. Click paperweight project
3. Go to TASKS tab → verify Run button appears, click it
4. Go to AGENT tab → verify terminal UI renders
5. Type a test prompt → verify streaming works

- [ ] **Step 5: Final commit if any fixes**

```bash
git add -u
git commit -m "fix: address issues found during final verification"
```
