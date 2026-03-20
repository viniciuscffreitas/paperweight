# Task-Centric Architecture — Phase 1: Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the Task entity (work_items table), TaskStore with CRUD + atomic claim, task processing loop, manual task creation API, and task_id FK on runs/sessions tables. After this phase, a user can create a task in the dashboard and have it processed autonomously.

**Architecture:** New `TaskStore` class manages a `work_items` SQLite table in the existing `agents.db`. A background processing loop polls for pending tasks and executes them via the existing `run_adhoc()` infrastructure. The `TaskConfig` class gets a `TaskTemplate` alias for forward-compatibility. New API routes enable task CRUD. The dashboard tasks tab renders live work items.

**Tech Stack:** Python 3.13, FastAPI, SQLite, Pydantic, Jinja2, HTMX

**Spec:** `docs/superpowers/specs/2026-03-20-task-centric-architecture-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `src/agents/models.py` | Add `TaskTemplate` alias, `TaskStatus` enum, `WorkItem` Pydantic model |
| `src/agents/task_store.py` | NEW — `TaskStore` class: CRUD, atomic claim, listing, dedup |
| `src/agents/task_processor.py` | NEW — Background loop: claim pending tasks, execute via `run_adhoc()`, update status |
| `src/agents/task_routes.py` | NEW — API routes: create, list, get, update status, re-run |
| `src/agents/history.py` | Migration: add `task_id` column to `runs` table |
| `src/agents/session_manager.py` | Migration: add `task_id` column to `agent_sessions` table |
| `src/agents/main.py` | Wire TaskStore, TaskProcessor, register routes, start processing loop |
| `src/agents/templates/hub/tasks.html` | Rewrite: show live WorkItems instead of static TaskTemplates |
| `src/agents/dashboard_html.py` | Update tasks tab route to query TaskStore |
| `tests/test_task_store.py` | NEW — TaskStore unit tests |
| `tests/test_task_processor.py` | NEW — TaskProcessor unit tests |
| `tests/test_task_routes.py` | NEW — API route tests |

---

### Task 1: TaskTemplate alias + TaskStatus enum + WorkItem model

**Files:**
- Modify: `src/agents/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write tests for new models**

```python
# tests/test_task_models.py
from agents.models import TaskTemplate, TaskStatus, WorkItem, TaskConfig
from datetime import datetime, UTC

def test_task_template_is_alias_for_task_config():
    """TaskTemplate and TaskConfig are the same class."""
    assert TaskTemplate is TaskConfig

def test_task_status_values():
    assert TaskStatus.DRAFT == "draft"
    assert TaskStatus.PENDING == "pending"
    assert TaskStatus.RUNNING == "running"
    assert TaskStatus.REVIEW == "review"
    assert TaskStatus.DONE == "done"
    assert TaskStatus.FAILED == "failed"

def test_work_item_creation():
    item = WorkItem(
        id="abc123def456",
        project="paperweight",
        title="Fix the tests",
        description="Tests are flaky, fix them",
        source="manual",
    )
    assert item.status == TaskStatus.PENDING
    assert item.source_id == ""
    assert item.session_id is None
    assert item.pr_url is None
    assert item.template is None

def test_work_item_with_all_fields():
    item = WorkItem(
        id="abc123def456",
        project="paperweight",
        template="issue-resolver",
        title="Fix bug PW-42",
        description="The login is broken",
        source="linear",
        source_id="uuid-123",
        source_url="https://linear.app/pw/issue/PW-42",
        status=TaskStatus.RUNNING,
        session_id="session-abc",
        pr_url="https://github.com/user/repo/pull/1",
    )
    assert item.template == "issue-resolver"
    assert item.source == "linear"
```

- [ ] **Step 2: Run tests → FAIL**

Run: `uv run python -m pytest tests/test_task_models.py -v`
Expected: FAIL — `TaskTemplate`, `TaskStatus`, `WorkItem` don't exist

- [ ] **Step 3: Add models to models.py**

At the end of `src/agents/models.py`, add:

```python
class TaskStatus(StrEnum):
    DRAFT = "draft"
    PENDING = "pending"
    RUNNING = "running"
    REVIEW = "review"
    DONE = "done"
    FAILED = "failed"


# Forward-compatible aliases — new code uses TaskTemplate, old code still works
TaskTemplate = TaskConfig
TaskTemplateRecord = TaskRecord  # alias for TaskRecord in project_hub


class WorkItem(BaseModel):
    id: str
    project: str
    template: str | None = None
    title: str
    description: str
    source: str  # "agent-tab" | "linear" | "github" | "manual" | "schedule"
    source_id: str = ""
    source_url: str = ""
    status: TaskStatus = TaskStatus.PENDING
    session_id: str | None = None
    pr_url: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
```

- [ ] **Step 4: Run tests → PASS**

Run: `uv run python -m pytest tests/test_task_models.py -v`
Expected: PASS

- [ ] **Step 5: Run full suite for regressions**

Run: `uv run python -m pytest tests/ --tb=short -q`
Expected: All pass (alias is non-breaking)

- [ ] **Step 6: Commit**

```bash
git add src/agents/models.py tests/test_task_models.py
git commit -m "feat: add TaskStatus enum, WorkItem model, TaskTemplate alias"
```

---

### Task 2: TaskStore — CRUD + atomic claim

**Files:**
- Create: `src/agents/task_store.py`
- Test: `tests/test_task_store.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_task_store.py
import pytest
from agents.task_store import TaskStore
from agents.models import TaskStatus

@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "test.db")

def test_create_and_get(store):
    task = store.create(
        project="pw", title="Fix bug", description="It's broken", source="manual",
    )
    assert task.id  # 12-char hex
    assert len(task.id) == 12
    assert task.status == TaskStatus.PENDING
    got = store.get(task.id)
    assert got is not None
    assert got.title == "Fix bug"

def test_list_by_project(store):
    store.create(project="pw", title="T1", description="D1", source="manual")
    store.create(project="pw", title="T2", description="D2", source="manual")
    store.create(project="other", title="T3", description="D3", source="manual")
    tasks = store.list_by_project("pw")
    assert len(tasks) == 2

def test_list_pending(store):
    t1 = store.create(project="pw", title="T1", description="D1", source="manual")
    t2 = store.create(project="pw", title="T2", description="D2", source="manual")
    store.update_status(t1.id, TaskStatus.RUNNING)
    pending = store.list_pending()
    assert len(pending) == 1
    assert pending[0].id == t2.id

def test_atomic_claim(store):
    t = store.create(project="pw", title="T1", description="D", source="manual")
    # First claim succeeds
    assert store.try_claim(t.id) is True
    got = store.get(t.id)
    assert got.status == TaskStatus.RUNNING
    # Second claim fails (already running)
    assert store.try_claim(t.id) is False

def test_claim_only_pending(store):
    t = store.create(project="pw", title="T1", description="D", source="manual")
    store.update_status(t.id, TaskStatus.DONE)
    assert store.try_claim(t.id) is False

def test_update_status(store):
    t = store.create(project="pw", title="T1", description="D", source="manual")
    store.update_status(t.id, TaskStatus.REVIEW, pr_url="https://github.com/pr/1")
    got = store.get(t.id)
    assert got.status == TaskStatus.REVIEW
    assert got.pr_url == "https://github.com/pr/1"

def test_exists_by_source(store):
    store.create(project="pw", title="T1", description="D", source="linear", source_id="abc")
    assert store.exists_by_source("linear", "abc") is True
    assert store.exists_by_source("linear", "xyz") is False
    assert store.exists_by_source("github", "abc") is False

def test_update_session_id(store):
    t = store.create(project="pw", title="T1", description="D", source="manual")
    store.update_session(t.id, "session-123")
    got = store.get(t.id)
    assert got.session_id == "session-123"
```

- [ ] **Step 2: Run tests → FAIL**

Run: `uv run python -m pytest tests/test_task_store.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement TaskStore**

```python
# src/agents/task_store.py
"""Task (work item) persistence — SQLite CRUD with atomic claim."""
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from agents.models import TaskStatus, WorkItem


class TaskStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS work_items (
                    id TEXT PRIMARY KEY,
                    project TEXT NOT NULL,
                    template TEXT,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL,
                    source_id TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    session_id TEXT,
                    pr_url TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_work_items_project"
                " ON work_items (project, status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_work_items_source"
                " ON work_items (source, source_id)"
            )
            # Context accumulation table (entries written in Phase 4, schema created now)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_context (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    source_run_id TEXT,
                    content TEXT NOT NULL DEFAULT '',
                    timestamp REAL NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_context_task"
                " ON task_context (task_id, timestamp)"
            )

    def _row_to_item(self, row: sqlite3.Row) -> WorkItem:
        return WorkItem(
            id=row["id"],
            project=row["project"],
            template=row["template"],
            title=row["title"],
            description=row["description"],
            source=row["source"],
            source_id=row["source_id"],
            source_url=row["source_url"],
            status=row["status"],
            session_id=row["session_id"],
            pr_url=row["pr_url"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def create(
        self,
        project: str,
        title: str,
        description: str,
        source: str,
        source_id: str = "",
        source_url: str = "",
        template: str | None = None,
        status: TaskStatus = TaskStatus.PENDING,
        session_id: str | None = None,
    ) -> WorkItem:
        item_id = uuid.uuid4().hex[:12]
        now = datetime.now(UTC)
        item = WorkItem(
            id=item_id,
            project=project,
            template=template,
            title=title,
            description=description,
            source=source,
            source_id=source_id,
            source_url=source_url,
            status=status,
            session_id=session_id,
            created_at=now,
            updated_at=now,
        )
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO work_items
                   (id, project, template, title, description, source, source_id,
                    source_url, status, session_id, pr_url, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.id, item.project, item.template, item.title,
                    item.description, item.source, item.source_id,
                    item.source_url, item.status, item.session_id,
                    item.pr_url, now.isoformat(), now.isoformat(),
                ),
            )
        return item

    def get(self, item_id: str) -> WorkItem | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM work_items WHERE id = ?", (item_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_item(row)

    def list_by_project(self, project: str) -> list[WorkItem]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM work_items WHERE project = ? ORDER BY created_at DESC",
                (project,),
            ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def list_pending(self, limit: int = 10) -> list[WorkItem]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM work_items WHERE status = ? ORDER BY created_at ASC LIMIT ?",
                (TaskStatus.PENDING, limit),
            ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def try_claim(self, item_id: str) -> bool:
        """Atomically claim a pending task. Returns True if claimed."""
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE work_items SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                (TaskStatus.RUNNING, now, item_id, TaskStatus.PENDING),
            )
            return cursor.rowcount == 1

    def update_status(
        self,
        item_id: str,
        status: TaskStatus,
        pr_url: str | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        if pr_url is not None:
            with self._conn() as conn:
                conn.execute(
                    "UPDATE work_items SET status = ?, pr_url = ?, updated_at = ? WHERE id = ?",
                    (status, pr_url, now, item_id),
                )
        else:
            with self._conn() as conn:
                conn.execute(
                    "UPDATE work_items SET status = ?, updated_at = ? WHERE id = ?",
                    (status, now, item_id),
                )

    def update_session(self, item_id: str, session_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE work_items SET session_id = ?, updated_at = ? WHERE id = ?",
                (session_id, now, item_id),
            )

    def exists_by_source(self, source: str, source_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM work_items WHERE source = ? AND source_id = ? LIMIT 1",
                (source, source_id),
            ).fetchone()
        return row is not None
```

- [ ] **Step 4: Run tests → PASS**

Run: `uv run python -m pytest tests/test_task_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/task_store.py tests/test_task_store.py
git commit -m "feat: TaskStore with CRUD, atomic claim, and source dedup"
```

---

### Task 3: DB migrations — task_id on runs and agent_sessions

**Files:**
- Modify: `src/agents/history.py:98-100` (migration block)
- Modify: `src/agents/session_manager.py:52-60` (migration block)
- Test: `tests/test_task_store.py` (append)

- [ ] **Step 1: Write migration tests**

```python
# tests/test_task_migrations.py
from agents.history import HistoryDB
from agents.session_manager import SessionManager
from agents.models import RunRecord, RunStatus, TriggerType
from datetime import datetime, UTC

def test_runs_table_has_task_id_column(tmp_path):
    db = HistoryDB(tmp_path / "test.db")
    run = RunRecord(
        id="r1", project="pw", task="test", trigger_type=TriggerType.MANUAL,
        started_at=datetime.now(UTC), status=RunStatus.RUNNING, model="sonnet",
    )
    db.insert_run(run)
    # Verify task_id column exists by updating it
    with db._conn() as conn:
        conn.execute("UPDATE runs SET task_id = ? WHERE id = ?", ("task-abc", "r1"))
        row = conn.execute("SELECT task_id FROM runs WHERE id = ?", ("r1",)).fetchone()
    assert row["task_id"] == "task-abc"

def test_sessions_table_has_task_id_column(tmp_path):
    sm = SessionManager(tmp_path / "test.db")
    session = sm.create_session("pw")
    with sm._conn() as conn:
        conn.execute(
            "UPDATE agent_sessions SET task_id = ? WHERE id = ?",
            ("task-abc", session.id),
        )
        row = conn.execute(
            "SELECT task_id FROM agent_sessions WHERE id = ?", (session.id,)
        ).fetchone()
    assert row["task_id"] == "task-abc"
```

- [ ] **Step 2: Run tests → FAIL**

Run: `uv run python -m pytest tests/test_task_migrations.py -v`
Expected: FAIL — `task_id` column doesn't exist

- [ ] **Step 3: Add migration to history.py**

In `src/agents/history.py`, in the `_init_db()` method, after the existing `session_id` migration (around line 98-100), add:

```python
try:
    conn.execute("ALTER TABLE runs ADD COLUMN task_id TEXT")
except sqlite3.OperationalError as e:
    if "duplicate column" not in str(e).lower():
        raise
```

- [ ] **Step 4: Add migration to session_manager.py**

In `src/agents/session_manager.py`, in the `_init_db()` method, add to the migrations list (around line 53-56):

```python
"ALTER TABLE agent_sessions ADD COLUMN task_id TEXT",
```

- [ ] **Step 5: Run tests → PASS**

Run: `uv run python -m pytest tests/test_task_migrations.py -v`
Expected: PASS

- [ ] **Step 6: Run full suite**

Run: `uv run python -m pytest tests/ --tb=short -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/agents/history.py src/agents/session_manager.py tests/test_task_migrations.py
git commit -m "feat: add task_id column to runs and agent_sessions tables"
```

---

### Task 4: TaskProcessor — background processing loop

**Files:**
- Create: `src/agents/task_processor.py`
- Test: `tests/test_task_processor.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_task_processor.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agents.task_processor import TaskProcessor
from agents.models import TaskStatus, WorkItem
from datetime import datetime, UTC

@pytest.fixture
def mock_deps(tmp_path):
    from agents.task_store import TaskStore
    store = TaskStore(tmp_path / "test.db")
    executor = MagicMock()
    session_manager = MagicMock()
    projects = {}
    return store, executor, session_manager, projects

def test_build_prompt_basic():
    item = WorkItem(
        id="abc", project="pw", title="Fix bug",
        description="The login page is broken.\nUsers can't sign in.",
        source="manual", created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    prompt = TaskProcessor.build_prompt(item, context_entries=[])
    assert "Fix bug" in prompt
    assert "login page is broken" in prompt

def test_build_prompt_with_context():
    item = WorkItem(
        id="abc", project="pw", title="Fix bug",
        description="Broken login",
        source="manual", created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    context = [
        {"type": "run_error", "content": "pytest failed: 3 errors in test_auth.py"},
        {"type": "user_feedback", "content": "Try using session tokens instead"},
    ]
    prompt = TaskProcessor.build_prompt(item, context_entries=context)
    assert "pytest failed" in prompt
    assert "session tokens" in prompt

def test_build_prompt_truncates_context():
    item = WorkItem(
        id="abc", project="pw", title="Fix",
        description="D", source="manual",
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    # Create context that exceeds 8KB
    big_context = [{"type": "run_error", "content": "x" * 5000} for _ in range(5)]
    prompt = TaskProcessor.build_prompt(item, context_entries=big_context)
    # Should not exceed ~9KB total (description + truncated context + overhead)
    assert len(prompt) < 10000
```

- [ ] **Step 2: Run tests → FAIL**

Run: `uv run python -m pytest tests/test_task_processor.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement TaskProcessor**

```python
# src/agents/task_processor.py
"""Background task processor — claims pending tasks and executes them."""
import asyncio
import logging
from typing import TYPE_CHECKING

from agents.models import TaskStatus

if TYPE_CHECKING:
    from agents.app_state import AppState
    from agents.config import GlobalConfig
    from agents.models import WorkItem
    from agents.task_store import TaskStore

logger = logging.getLogger(__name__)

_MAX_CONTEXT_BYTES = 8192


class TaskProcessor:
    def __init__(
        self,
        task_store: "TaskStore",
        state: "AppState",
        config: "GlobalConfig",
    ) -> None:
        self.task_store = task_store
        self.state = state
        self.config = config
        self._running = False

    @staticmethod
    def build_prompt(item: "WorkItem", context_entries: list[dict]) -> str:
        """Assemble the agent prompt from task description + context."""
        parts: list[str] = []
        parts.append(f"# Task: {item.title}\n")
        parts.append(item.description)

        if context_entries:
            parts.append("\n\n## Prior Context (newest first)")
            total = 0
            for entry in reversed(context_entries):
                content = entry.get("content", "")
                entry_type = entry.get("type", "")
                line = f"\n### [{entry_type}]\n{content}"
                if total + len(line) > _MAX_CONTEXT_BYTES:
                    parts.append("\n\n(... earlier context truncated ...)")
                    break
                parts.append(line)
                total += len(line)

        return "\n".join(parts)

    async def process_one(self, item: "WorkItem") -> None:
        """Process a single task: create/reuse session, run agent, update status."""
        project = self.state.projects.get(item.project)
        if project is None:
            logger.warning("Task %s references unknown project %s", item.id, item.project)
            self.task_store.update_status(item.id, TaskStatus.FAILED)
            return

        # Determine model and budget from template or defaults
        template_name = item.template
        template = project.tasks.get(template_name) if template_name else None
        model = template.model if template else self.config.execution.default_model
        max_cost = template.max_cost_usd if template else self.config.execution.default_max_cost_usd

        # Normalize model name
        model_map = {"sonnet": "claude-sonnet-4-6", "haiku": "claude-haiku-4-5-20251001", "opus": "claude-opus-4-6"}
        model = model_map.get(model, model)

        # Create or reuse session
        session_manager = self.state.session_manager
        if item.session_id:
            session = session_manager.get_session(item.session_id)
            if session is None or session.status != "active":
                session = session_manager.create_session(item.project, model, max_cost)
                self.task_store.update_session(item.id, session.id)
            if not session_manager.try_acquire_run(session.id):
                logger.warning("Task %s: session %s locked, will retry", item.id, item.session_id)
                self.task_store.update_status(item.id, TaskStatus.PENDING)
                return
        else:
            session = session_manager.create_session(item.project, model, max_cost)
            session_manager.try_acquire_run(session.id)
            self.task_store.update_session(item.id, session.id)

        is_resume = session.claude_session_id is not None

        # Build prompt with context
        # (context_entries will come from Phase 4; empty for now)
        prompt = self.build_prompt(item, context_entries=[])

        try:
            async with (
                self.state.get_semaphore(self.config.execution.max_concurrent),
                self.state.get_repo_semaphore(project.repo),
            ):
                from agents.executor_utils import generate_run_id
                run_id = generate_run_id(item.project, "task")

                result = await self.state.executor.run_adhoc(
                    project, prompt, session,
                    is_resume=is_resume, run_id=run_id,
                )

                # Update session for --resume on next attempt
                if result.claude_session_id:
                    session_manager.update_session(
                        session.id, claude_session_id=result.claude_session_id,
                    )

                if result.status == "success":
                    # Create PR if there are commits
                    pr_url = None
                    try:
                        from pathlib import Path
                        worktree = Path(session.worktree_path)
                        if worktree.exists():
                            log_out = await self.state.executor._run_cmd(
                                ["git", "log", f"{project.base_branch}..HEAD", "--oneline"],
                                cwd=str(worktree),
                            )
                            if log_out.strip():
                                branch = f"agents/session-{session.id}"
                                pr_url = await self.state.executor._create_pr(
                                    cwd=str(worktree), project=project,
                                    task_name=item.title[:40], branch=branch,
                                    autonomy=template.autonomy if template else "pr-only",
                                )
                    except Exception:
                        logger.warning("Failed to create PR for task %s", item.id)

                    self.task_store.update_status(
                        item.id,
                        TaskStatus.REVIEW if pr_url else TaskStatus.DONE,
                        pr_url=pr_url,
                    )
                else:
                    self.task_store.update_status(item.id, TaskStatus.FAILED)
        except Exception:
            logger.exception("Task %s failed", item.id)
            self.task_store.update_status(item.id, TaskStatus.FAILED)
        finally:
            session_manager.release_run(session.id)

    async def run_loop(self) -> None:
        """Main processing loop — polls for pending tasks every 10s."""
        self._running = True
        logger.info("TaskProcessor started")
        while self._running:
            try:
                pending = self.task_store.list_pending(limit=self.config.execution.max_concurrent)
                for item in pending:
                    if not self.state.budget.can_afford(
                        self.config.execution.default_max_cost_usd
                    ):
                        logger.info("Budget exhausted, skipping task %s", item.id)
                        continue
                    if self.task_store.try_claim(item.id):
                        asyncio.create_task(self.process_one(item))
            except Exception:
                logger.exception("TaskProcessor loop error")
            await asyncio.sleep(10)

    def stop(self) -> None:
        self._running = False
```

- [ ] **Step 4: Run tests → PASS**

Run: `uv run python -m pytest tests/test_task_processor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/task_processor.py tests/test_task_processor.py
git commit -m "feat: TaskProcessor background loop — claims and executes pending tasks"
```

---

### Task 5: API routes for task CRUD

**Files:**
- Create: `src/agents/task_routes.py`
- Test: `tests/test_task_routes.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_task_routes.py
import pytest
from fastapi.testclient import TestClient
from agents.task_store import TaskStore
from agents.models import TaskStatus

@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "test.db")

@pytest.fixture
def client(store):
    from fastapi import FastAPI
    from agents.task_routes import register_task_routes
    app = FastAPI()
    register_task_routes(app, store)
    return TestClient(app)

def test_create_task(client):
    resp = client.post("/api/work-items", json={
        "project": "pw", "title": "Fix bug", "description": "It's broken",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Fix bug"
    assert data["status"] == "pending"
    assert data["source"] == "manual"

def test_list_tasks(client):
    client.post("/api/work-items", json={
        "project": "pw", "title": "T1", "description": "D1",
    })
    client.post("/api/work-items", json={
        "project": "pw", "title": "T2", "description": "D2",
    })
    resp = client.get("/api/work-items?project=pw")
    assert resp.status_code == 200
    assert len(resp.json()) == 2

def test_get_task(client):
    create_resp = client.post("/api/work-items", json={
        "project": "pw", "title": "T1", "description": "D1",
    })
    item_id = create_resp.json()["id"]
    resp = client.get(f"/api/work-items/{item_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "T1"

def test_get_task_not_found(client):
    resp = client.get("/api/work-items/nonexistent")
    assert resp.status_code == 404

def test_update_task_status(client):
    create_resp = client.post("/api/work-items", json={
        "project": "pw", "title": "T1", "description": "D1",
    })
    item_id = create_resp.json()["id"]
    resp = client.patch(f"/api/work-items/{item_id}", json={"status": "done"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"

def test_rerun_task(client):
    create_resp = client.post("/api/work-items", json={
        "project": "pw", "title": "T1", "description": "D1",
    })
    item_id = create_resp.json()["id"]
    # Set to failed first
    client.patch(f"/api/work-items/{item_id}", json={"status": "failed"})
    # Re-run sets it back to pending
    resp = client.post(f"/api/work-items/{item_id}/rerun")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"
```

- [ ] **Step 2: Run tests → FAIL**

Run: `uv run python -m pytest tests/test_task_routes.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement task_routes.py**

```python
# src/agents/task_routes.py
"""API routes for work item (task) CRUD."""
from fastapi import FastAPI, Response

from agents.models import TaskStatus
from agents.task_store import TaskStore


def register_task_routes(app: FastAPI, task_store: TaskStore) -> None:
    @app.post("/api/work-items", status_code=201)
    async def create_work_item(data: dict) -> dict:
        item = task_store.create(
            project=data["project"],
            title=data["title"],
            description=data.get("description", ""),
            source=data.get("source", "manual"),
            source_id=data.get("source_id", ""),
            source_url=data.get("source_url", ""),
            template=data.get("template"),
        )
        return item.model_dump(mode="json")

    @app.get("/api/work-items")
    async def list_work_items(project: str | None = None) -> list[dict]:
        if project:
            items = task_store.list_by_project(project)
        else:
            items = task_store.list_pending()
        return [i.model_dump(mode="json") for i in items]

    @app.get("/api/work-items/{item_id}")
    async def get_work_item(item_id: str) -> Response | dict:
        item = task_store.get(item_id)
        if item is None:
            return Response(status_code=404, content="Work item not found")
        return item.model_dump(mode="json")

    @app.patch("/api/work-items/{item_id}")
    async def update_work_item(item_id: str, data: dict) -> Response | dict:
        item = task_store.get(item_id)
        if item is None:
            return Response(status_code=404, content="Work item not found")
        status = data.get("status")
        if status:
            task_store.update_status(item_id, TaskStatus(status), pr_url=data.get("pr_url"))
        updated = task_store.get(item_id)
        return updated.model_dump(mode="json")

    @app.post("/api/work-items/{item_id}/rerun")
    async def rerun_work_item(item_id: str) -> Response | dict:
        item = task_store.get(item_id)
        if item is None:
            return Response(status_code=404, content="Work item not found")
        task_store.update_status(item_id, TaskStatus.PENDING)
        updated = task_store.get(item_id)
        return updated.model_dump(mode="json")
```

- [ ] **Step 4: Run tests → PASS**

Run: `uv run python -m pytest tests/test_task_routes.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/task_routes.py tests/test_task_routes.py
git commit -m "feat: work item API routes — CRUD, status update, re-run"
```

---

### Task 6: Wire everything into main.py

**Files:**
- Modify: `src/agents/main.py`

- [ ] **Step 1: Add TaskStore creation alongside existing stores**

In `src/agents/main.py`, after `session_manager` creation (around line 59), add:

```python
from agents.task_store import TaskStore
task_store = TaskStore(db_path)
```

- [ ] **Step 2: Add TaskProcessor creation**

After the executor creation (around line 160), add:

```python
from agents.task_processor import TaskProcessor
task_processor = TaskProcessor(task_store=task_store, state=state, config=config)
```

Note: `state` is created at line 162. The processor needs `state`, so create it after `state`:

```python
# After state = AppState(...) at line 162
from agents.task_processor import TaskProcessor
task_processor = TaskProcessor(task_store=task_store, state=state, config=config)
state.task_store = task_store  # Add to AppState for route access
```

- [ ] **Step 3: Register task routes**

After the existing `register_agent_routes(app, state, config)` call (around line 297), add:

```python
from agents.task_routes import register_task_routes
register_task_routes(app, task_store)
```

- [ ] **Step 4: Start processing loop in lifespan**

In the `lifespan` function, after `scheduler.start()` (around line 229), add:

```python
processor_task = asyncio.create_task(task_processor.run_loop())
```

And in the shutdown section (before `yield` ends), add:

```python
task_processor.stop()
processor_task.cancel()
```

- [ ] **Step 5: Add task_store to AppState**

In `src/agents/app_state.py`, add `task_store` as an optional field (or just set it dynamically as done in step 2).

- [ ] **Step 6: Run full test suite**

Run: `uv run python -m pytest tests/ --tb=short -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/agents/main.py src/agents/app_state.py
git commit -m "feat: wire TaskStore, TaskProcessor, and task routes into main app"
```

---

### Task 7: Dashboard tasks tab — show live WorkItems

**Files:**
- Modify: `src/agents/dashboard_html.py`
- Modify: `src/agents/templates/hub/tasks.html`
- Create: `src/agents/templates/partials/work_item_row.html`

- [ ] **Step 1: Update the tasks tab route**

In `src/agents/dashboard_html.py`, find the `/hub/{project_id}/tasks` route. Currently it reads TaskConfigs from YAML. Change it to read WorkItems from TaskStore:

```python
@app.get("/hub/{project_id}/tasks", response_class=HTMLResponse)
async def hub_tasks(project_id: str) -> HTMLResponse:
    # Get live work items from TaskStore
    work_items = state.task_store.list_by_project(project_id) if hasattr(state, 'task_store') and state.task_store else []
    # Get task templates for Run buttons (existing behavior, uses project_store dicts)
    task_rows = state.project_store.list_tasks(project_id) if state.project_store else []
    return templates_env.get_template("hub/tasks.html").render(
        id=project_id, work_items=work_items, task_rows=task_rows,
    )
```

- [ ] **Step 2: Create work_item_row.html partial**

```html
{# src/agents/templates/partials/work_item_row.html #}
<div class="list-row" style="display:flex;align-items:center;gap:12px;padding:10px 12px;border-bottom:1px solid var(--border);cursor:pointer"
     hx-get="/hub/{{ item.project }}/agent?task={{ item.id }}" hx-target="#tab-content">
  <span class="status-dot {% if item.status == 'running' %}running{% elif item.status in ('done', 'review') %}success{% elif item.status == 'failed' %}failure{% endif %}" style="width:8px;height:8px;border-radius:50%"></span>
  <div style="flex:1;min-width:0">
    <div style="font-size:13px;font-weight:500;color:var(--text-primary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{{ item.title }}</div>
    <div style="font-size:11px;color:var(--text-tertiary);margin-top:2px">
      <span style="text-transform:uppercase;letter-spacing:0.5px">{{ item.source }}</span>
      {% if item.pr_url %} · <a href="{{ item.pr_url }}" target="_blank" style="color:var(--accent)">PR</a>{% endif %}
    </div>
  </div>
  <span style="font-size:11px;color:var(--text-tertiary);text-transform:uppercase;letter-spacing:0.5px;padding:2px 8px;border-radius:4px;background:var(--bg-elevated)">{{ item.status }}</span>
</div>
```

- [ ] **Step 3: Rewrite hub/tasks.html**

```html
{# src/agents/templates/hub/tasks.html #}
{% from "components/macros.html" import section_label %}

{# Work Items section #}
{{ section_label("Work Items") }}
<div style="margin-bottom:16px">
  <div style="display:flex;gap:8px;margin-bottom:12px">
    <input id="new-task-title" placeholder="New task title..." required
           style="flex:1;padding:8px 12px;border-radius:8px;border:1px solid var(--border);background:var(--bg-elevated);color:var(--text-primary);font-size:13px"
           onkeydown="if(event.key==='Enter'){createWorkItem('{{ id }}')}">
    <button onclick="createWorkItem('{{ id }}')"
            style="padding:8px 16px;border-radius:8px;background:var(--accent);color:white;border:none;font-size:13px;cursor:pointer">Create</button>
  </div>
  <script>
  function createWorkItem(project) {
    var input = document.getElementById('new-task-title');
    var title = input.value.trim();
    if (!title) return;
    fetch('/api/work-items', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({project: project, title: title, description: title})
    }).then(function() {
      input.value = '';
      htmx.ajax('GET', '/hub/' + project + '/tasks', {target: '#tab-content'});
    });
  }
  </script>
  <div id="work-items-list">
    {% for item in work_items %}
      {% include "partials/work_item_row.html" %}
    {% else %}
      <div style="text-align:center;padding:24px;color:var(--text-tertiary);font-size:13px">No tasks yet. Create one above or connect an integration.</div>
    {% endfor %}
  </div>
</div>

{# Templates section (existing Run buttons — unchanged, uses original template vars) #}
{% if task_rows %}
{{ section_label("Task Templates") }}
{% for task in task_rows %}
  {% include "partials/task_row.html" %}
{% endfor %}
{% endif %}
```

> **Note:** The `task_rows` variable is populated by the route using the existing `project_store.list_tasks()` call (which returns dicts compatible with `task_row.html`). This preserves the existing Run button behavior without modification.

- [ ] **Step 4: Run full test suite**

Run: `uv run python -m pytest tests/ --tb=short -q`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/agents/dashboard_html.py src/agents/templates/hub/tasks.html \
        src/agents/templates/partials/work_item_row.html
git commit -m "feat: dashboard tasks tab shows live work items with inline creation"
```

---

## Final Verification

- [ ] **Run full test suite**: `uv run python -m pytest tests/ -v --tb=short`
- [ ] **Type check modified files**: `uv run python -m pyright src/agents/models.py src/agents/task_store.py src/agents/task_processor.py src/agents/task_routes.py`
- [ ] **Verify server starts**: `uv run agents` (Ctrl+C after confirming no errors)
- [ ] **Manual smoke test**: Open dashboard → select project → Tasks tab → create a task → verify it appears

---

## What This Phase Delivers

After Phase 1, a user can:
1. Open the dashboard, go to a project's Tasks tab
2. Type a task title → "Create"
3. The processing loop picks it up within 10 seconds
4. Claude works in a worktree, creates a PR
5. Task status updates: pending → running → review

**Next phases** (separate plans):
- **Phase 2**: Agent Tab integration — click a task to open it in Agent Tab, "Create Task" button from conversations
- **Phase 3**: Source migration — webhooks/scheduler create Tasks instead of calling run_task directly
- **Phase 4**: Context accumulation — structured context entries, prompt assembly with prior attempt data
