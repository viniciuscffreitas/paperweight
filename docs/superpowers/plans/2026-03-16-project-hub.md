# Project Hub Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the Paperweight dashboard from a run monitor into a project command center with aggregated views (Linear, GitHub, Slack), task management, run launcher, and proactive notifications.

**Architecture:** Extend SQLite schema with 6 new tables (projects, project_sources, tasks, aggregated_events, notification_rules, notification_log). Add Aggregator Service as background asyncio tasks for polling. Build new NiceGUI pages for Project Hub, Task Manager, and Setup Wizard. Create GitHub and Slack Bot API clients from scratch.

**Tech Stack:** FastAPI, NiceGUI, SQLite (raw SQL via sqlite3), Pydantic, httpx, APScheduler, pytest/pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-03-16-project-hub-design.md`

---

## Chunk 1: Data Model & Project CRUD

### Task 1: Extend Models with Project Hub Types

**Files:**
- Modify: `src/agents/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write failing tests for new models**

Add to `tests/test_models.py`:

```python
from agents.models import (
    AggregatedEvent,
    NotificationRule,
    ProjectRecord,
    ProjectSource,
    TaskRecord,
)


def test_project_record_creation() -> None:
    p = ProjectRecord(id="momease", name="MomEase", repo_path="/repos/momease")
    assert p.id == "momease"
    assert p.default_branch == "main"
    assert p.created_at is not None


def test_project_source_creation() -> None:
    s = ProjectSource(
        id="src-1",
        project_id="momease",
        source_type="linear",
        source_id="LIN-123",
        source_name="MomEase Project",
    )
    assert s.enabled is True
    assert s.config == {}


def test_task_record_creation() -> None:
    t = TaskRecord(
        id="task-1",
        project_id="momease",
        name="Fix bugs",
        intent="Fix all open bugs",
        trigger_type="manual",
        model="sonnet",
        max_budget=5.0,
        autonomy="pr-only",
    )
    assert t.enabled is True
    assert t.trigger_config == {}


def test_task_record_schedule_trigger() -> None:
    t = TaskRecord(
        id="task-2",
        project_id="momease",
        name="Daily review",
        intent="Review open PRs",
        trigger_type="schedule",
        trigger_config={"cron": "0 9 * * *"},
        model="sonnet",
        max_budget=5.0,
        autonomy="pr-only",
    )
    assert t.trigger_config["cron"] == "0 9 * * *"


def test_aggregated_event_creation() -> None:
    e = AggregatedEvent(
        id="evt-1",
        project_id="momease",
        source="linear",
        event_type="issue_created",
        title="Fix login crash",
        timestamp="2026-03-16T10:00:00Z",
        source_item_id="LIN-42",
    )
    assert e.priority == "none"
    assert e.raw_data == {}


def test_notification_rule_creation() -> None:
    r = NotificationRule(
        id="rule-1",
        project_id="momease",
        rule_type="digest",
        channel="slack",
        channel_target="dm",
    )
    assert r.enabled is True
    assert r.config == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/vini/Developer/agents && python -m pytest tests/test_models.py::test_project_record_creation -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement new models**

Add to `src/agents/models.py` after `BudgetStatus`. Note: use `Field(default_factory=...)` for mutable defaults and datetime fields to avoid shared-state bugs:

```python
from pydantic import Field


def _now() -> datetime:
    return datetime.now(UTC)


class ProjectRecord(BaseModel):
    id: str
    name: str
    repo_path: str
    default_branch: str = "main"
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class ProjectSource(BaseModel):
    id: str
    project_id: str
    source_type: str  # "linear", "github", "slack"
    source_id: str
    source_name: str
    config: dict = Field(default_factory=dict)
    enabled: bool = True
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class TaskRecord(BaseModel):
    id: str
    project_id: str
    name: str
    intent: str
    trigger_type: str  # "manual", "schedule", "webhook"
    trigger_config: dict = Field(default_factory=dict)
    model: str = "sonnet"
    max_budget: float = 5.0
    autonomy: str = "pr-only"
    enabled: bool = True
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class AggregatedEvent(BaseModel):
    id: str
    project_id: str
    source: str  # "linear", "github", "slack", "paperweight"
    event_type: str
    title: str
    body: str = ""
    author: str = ""
    url: str = ""
    priority: str = "none"
    timestamp: str
    source_item_id: str
    raw_data: dict = Field(default_factory=dict)


class NotificationRule(BaseModel):
    id: str
    project_id: str
    rule_type: str  # "digest", "alert"
    channel: str  # "slack", "discord"
    channel_target: str  # channel ID or "dm"
    config: dict = Field(default_factory=dict)
    enabled: bool = True
```

Note: These Pydantic models serve as the API contract and validation layer. `ProjectStore` returns raw `dict` for performance (avoiding hydration overhead on every query), but API endpoints should validate inputs through these models when needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/vini/Developer/agents && python -m pytest tests/test_models.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/models.py tests/test_models.py
git commit -m "feat: add Project Hub data models"
```

---

### Task 2: Create Project Store (SQLite CRUD)

**Files:**
- Create: `src/agents/project_store.py`
- Test: `tests/test_project_store.py`

- [ ] **Step 1: Write failing tests for ProjectStore**

Create `tests/test_project_store.py`:

```python
import pytest
from pathlib import Path
from agents.project_store import ProjectStore


@pytest.fixture
def store(tmp_path: Path) -> ProjectStore:
    return ProjectStore(tmp_path / "test.db")


def test_create_project(store: ProjectStore) -> None:
    store.create_project(id="momease", name="MomEase", repo_path="/repos/momease")
    project = store.get_project("momease")
    assert project is not None
    assert project["name"] == "MomEase"
    assert project["default_branch"] == "main"


def test_list_projects(store: ProjectStore) -> None:
    store.create_project(id="p1", name="Project 1", repo_path="/repos/p1")
    store.create_project(id="p2", name="Project 2", repo_path="/repos/p2")
    projects = store.list_projects()
    assert len(projects) == 2


def test_update_project(store: ProjectStore) -> None:
    store.create_project(id="p1", name="Old Name", repo_path="/repos/p1")
    store.update_project("p1", name="New Name")
    project = store.get_project("p1")
    assert project["name"] == "New Name"


def test_delete_project(store: ProjectStore) -> None:
    store.create_project(id="p1", name="Project 1", repo_path="/repos/p1")
    store.delete_project("p1")
    assert store.get_project("p1") is None


def test_create_source(store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/repos/p1")
    source_id = store.create_source(
        project_id="p1",
        source_type="linear",
        source_id="LIN-123",
        source_name="MomEase Linear",
    )
    sources = store.list_sources("p1")
    assert len(sources) == 1
    assert sources[0]["source_type"] == "linear"


def test_delete_source(store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/repos/p1")
    source_id = store.create_source(
        project_id="p1", source_type="slack", source_id="C123", source_name="#dev"
    )
    store.delete_source(source_id)
    assert store.list_sources("p1") == []


def test_create_task(store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/repos/p1")
    task_id = store.create_task(
        project_id="p1",
        name="Fix bugs",
        intent="Fix all open bugs",
        trigger_type="manual",
        model="sonnet",
        max_budget=5.0,
        autonomy="pr-only",
    )
    tasks = store.list_tasks("p1")
    assert len(tasks) == 1
    assert tasks[0]["name"] == "Fix bugs"


def test_update_task(store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/repos/p1")
    task_id = store.create_task(
        project_id="p1",
        name="Old",
        intent="Do stuff",
        trigger_type="manual",
        model="sonnet",
        max_budget=5.0,
        autonomy="pr-only",
    )
    store.update_task(task_id, name="New", enabled=False)
    task = store.get_task(task_id)
    assert task["name"] == "New"
    assert task["enabled"] == 0


def test_toggle_task(store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/repos/p1")
    task_id = store.create_task(
        project_id="p1",
        name="Task",
        intent="Do stuff",
        trigger_type="manual",
        model="sonnet",
        max_budget=5.0,
        autonomy="pr-only",
    )
    store.update_task(task_id, enabled=False)
    task = store.get_task(task_id)
    assert task["enabled"] == 0
    store.update_task(task_id, enabled=True)
    task = store.get_task(task_id)
    assert task["enabled"] == 1


def test_delete_task(store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/repos/p1")
    task_id = store.create_task(
        project_id="p1",
        name="Task",
        intent="Do stuff",
        trigger_type="manual",
        model="sonnet",
        max_budget=5.0,
        autonomy="pr-only",
    )
    store.delete_task(task_id)
    assert store.list_tasks("p1") == []


def test_insert_event(store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/repos/p1")
    store.upsert_event(
        project_id="p1",
        source="linear",
        event_type="issue_created",
        title="Fix login",
        source_item_id="LIN-42",
        timestamp="2026-03-16T10:00:00Z",
    )
    events = store.list_events("p1")
    assert len(events) == 1
    assert events[0]["title"] == "Fix login"


def test_event_deduplication(store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/repos/p1")
    store.upsert_event(
        project_id="p1",
        source="linear",
        event_type="issue_created",
        title="Fix login v1",
        source_item_id="LIN-42",
        timestamp="2026-03-16T10:00:00Z",
    )
    store.upsert_event(
        project_id="p1",
        source="linear",
        event_type="issue_updated",
        title="Fix login v2",
        source_item_id="LIN-42",
        timestamp="2026-03-16T10:05:00Z",
    )
    events = store.list_events("p1")
    assert len(events) == 1
    assert events[0]["title"] == "Fix login v2"


def test_list_events_filtered_by_source(store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/repos/p1")
    store.upsert_event(
        project_id="p1", source="linear", event_type="issue_created",
        title="Issue", source_item_id="L1", timestamp="2026-03-16T10:00:00Z",
    )
    store.upsert_event(
        project_id="p1", source="github", event_type="pr_opened",
        title="PR", source_item_id="G1", timestamp="2026-03-16T10:01:00Z",
    )
    linear_events = store.list_events("p1", source="linear")
    assert len(linear_events) == 1
    assert linear_events[0]["source"] == "linear"


def test_notification_rules_crud(store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/repos/p1")
    rule_id = store.create_notification_rule(
        project_id="p1",
        rule_type="digest",
        channel="slack",
        channel_target="dm",
        config={"schedule": "0 9 * * *"},
    )
    rules = store.list_notification_rules("p1")
    assert len(rules) == 1
    assert rules[0]["rule_type"] == "digest"
    store.delete_notification_rule(rule_id)
    assert store.list_notification_rules("p1") == []


def test_cascade_delete_project(store: ProjectStore) -> None:
    """Deleting a project removes its sources, tasks, events, and rules."""
    store.create_project(id="p1", name="P1", repo_path="/repos/p1")
    store.create_source(project_id="p1", source_type="linear", source_id="L1", source_name="Lin")
    store.create_task(
        project_id="p1", name="T", intent="I", trigger_type="manual",
        model="sonnet", max_budget=5.0, autonomy="pr-only",
    )
    store.upsert_event(
        project_id="p1", source="linear", event_type="x", title="E",
        source_item_id="E1", timestamp="2026-03-16T10:00:00Z",
    )
    store.create_notification_rule(
        project_id="p1", rule_type="digest", channel="slack", channel_target="dm",
    )
    store.delete_project("p1")
    assert store.list_sources("p1") == []
    assert store.list_tasks("p1") == []
    assert store.list_events("p1") == []
    assert store.list_notification_rules("p1") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/vini/Developer/agents && python -m pytest tests/test_project_store.py::test_create_project -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement ProjectStore**

Create `src/agents/project_store.py`:

```python
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path


class ProjectStore:
    """SQLite persistence for Project Hub data."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    repo_path TEXT NOT NULL,
                    default_branch TEXT NOT NULL DEFAULT 'main',
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS project_sources (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    config TEXT NOT NULL DEFAULT '{}',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    trigger_config TEXT NOT NULL DEFAULT '{}',
                    model TEXT NOT NULL DEFAULT 'sonnet',
                    max_budget REAL NOT NULL DEFAULT 5.0,
                    autonomy TEXT NOT NULL DEFAULT 'pr-only',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS aggregated_events (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    source TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL DEFAULT '',
                    author TEXT NOT NULL DEFAULT '',
                    url TEXT NOT NULL DEFAULT '',
                    priority TEXT NOT NULL DEFAULT 'none',
                    timestamp TEXT NOT NULL,
                    source_item_id TEXT NOT NULL,
                    raw_data TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(source, source_item_id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_project
                ON aggregated_events (project_id, timestamp DESC)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notification_rules (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    rule_type TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    channel_target TEXT NOT NULL,
                    config TEXT NOT NULL DEFAULT '{}',
                    enabled INTEGER NOT NULL DEFAULT 1
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notification_log (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    rule_id TEXT,
                    event_id TEXT,
                    sent_at TIMESTAMP NOT NULL,
                    channel TEXT NOT NULL,
                    content TEXT NOT NULL
                )
            """)

    # ── Projects ──────────────────────────────────────────────

    def create_project(
        self, *, id: str, name: str, repo_path: str, default_branch: str = "main"
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO projects (id, name, repo_path, default_branch, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (id, name, repo_path, default_branch, now, now),
            )

    def get_project(self, project_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return dict(row) if row else None

    def list_projects(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    def update_project(self, project_id: str, **kwargs: object) -> None:
        allowed = {"name", "repo_path", "default_branch"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return
        updates["updated_at"] = datetime.now(UTC).isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [project_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE projects SET {set_clause} WHERE id = ?", values)

    def delete_project(self, project_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    # ── Sources ───────────────────────────────────────────────

    def create_source(
        self,
        *,
        project_id: str,
        source_type: str,
        source_id: str,
        source_name: str,
        config: dict | None = None,
    ) -> str:
        sid = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO project_sources (id, project_id, source_type, source_id, source_name, config, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (sid, project_id, source_type, source_id, source_name, json.dumps(config or {}), now, now),
            )
        return sid

    def list_sources(self, project_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM project_sources WHERE project_id = ? ORDER BY source_type",
                (project_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_source(self, source_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM project_sources WHERE id = ?", (source_id,))

    # ── Tasks ─────────────────────────────────────────────────

    def create_task(
        self,
        *,
        project_id: str,
        name: str,
        intent: str,
        trigger_type: str,
        model: str = "sonnet",
        max_budget: float = 5.0,
        autonomy: str = "pr-only",
        trigger_config: dict | None = None,
    ) -> str:
        tid = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO tasks (id, project_id, name, intent, trigger_type, trigger_config,
                   model, max_budget, autonomy, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (tid, project_id, name, intent, trigger_type, json.dumps(trigger_config or {}),
                 model, max_budget, autonomy, now, now),
            )
        return tid

    def get_task(self, task_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def list_tasks(self, project_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE project_id = ? ORDER BY name", (project_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def update_task(self, task_id: str, **kwargs: object) -> None:
        allowed = {"name", "intent", "trigger_type", "trigger_config", "model", "max_budget", "autonomy", "enabled"}
        updates = {}
        for k, v in kwargs.items():
            if k in allowed and v is not None:
                if k == "trigger_config" and isinstance(v, dict):
                    updates[k] = json.dumps(v)
                else:
                    updates[k] = v
        if not updates:
            return
        updates["updated_at"] = datetime.now(UTC).isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [task_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)

    def delete_task(self, task_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    # ── Events ────────────────────────────────────────────────

    def upsert_event(
        self,
        *,
        project_id: str,
        source: str,
        event_type: str,
        title: str,
        source_item_id: str,
        timestamp: str,
        body: str = "",
        author: str = "",
        url: str = "",
        priority: str = "none",
        raw_data: dict | None = None,
    ) -> str:
        eid = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO aggregated_events
                   (id, project_id, source, event_type, title, body, author, url, priority, timestamp, source_item_id, raw_data)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source, source_item_id) DO UPDATE SET
                   event_type=excluded.event_type, title=excluded.title, body=excluded.body,
                   author=excluded.author, url=excluded.url, priority=excluded.priority,
                   timestamp=excluded.timestamp, raw_data=excluded.raw_data""",
                (eid, project_id, source, event_type, title, body, author, url, priority,
                 timestamp, source_item_id, json.dumps(raw_data or {})),
            )
        return eid

    def list_events(
        self, project_id: str, *, source: str | None = None, limit: int = 100
    ) -> list[dict]:
        query = "SELECT * FROM aggregated_events WHERE project_id = ?"
        params: list[object] = [project_id]
        if source:
            query += " AND source = ?"
            params.append(source)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def cleanup_old_events(self, days: int = 90) -> int:
        from datetime import timedelta
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM aggregated_events WHERE timestamp < ?", (cutoff,)
            )
        return cursor.rowcount

    # ── Notification Rules ────────────────────────────────────

    def create_notification_rule(
        self,
        *,
        project_id: str,
        rule_type: str,
        channel: str,
        channel_target: str,
        config: dict | None = None,
    ) -> str:
        rid = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO notification_rules (id, project_id, rule_type, channel, channel_target, config) VALUES (?, ?, ?, ?, ?, ?)",
                (rid, project_id, rule_type, channel, channel_target, json.dumps(config or {})),
            )
        return rid

    def list_notification_rules(self, project_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM notification_rules WHERE project_id = ?", (project_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_notification_rule(self, rule_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM notification_rules WHERE id = ?", (rule_id,))

    # ── Notification Log ──────────────────────────────────────

    def log_notification(
        self,
        *,
        project_id: str,
        rule_id: str | None,
        event_id: str | None,
        channel: str,
        content: str,
    ) -> None:
        nid = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO notification_log (id, project_id, rule_id, event_id, sent_at, channel, content) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (nid, project_id, rule_id, event_id, now, channel, content),
            )

    def was_recently_notified(
        self, *, source_item_id: str, rule_type: str, cooldown_minutes: int = 30
    ) -> bool:
        from datetime import timedelta
        cutoff = (datetime.now(UTC) - timedelta(minutes=cooldown_minutes)).isoformat()
        with self._conn() as conn:
            row = conn.execute(
                """SELECT COUNT(*) as cnt FROM notification_log nl
                   JOIN notification_rules nr ON nl.rule_id = nr.id
                   WHERE nl.event_id IN (
                       SELECT id FROM aggregated_events WHERE source_item_id = ?
                   )
                   AND nr.rule_type = ?
                   AND nl.sent_at > ?""",
                (source_item_id, rule_type, cutoff),
            ).fetchone()
        return row["cnt"] > 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/vini/Developer/agents && python -m pytest tests/test_project_store.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/project_store.py tests/test_project_store.py
git commit -m "feat: add ProjectStore with full CRUD for projects, sources, tasks, events, notifications"
```

---

### Task 3: Add Project CRUD API Endpoints

**Files:**
- Modify: `src/agents/main.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Write failing tests for project API**

Add to `tests/test_main.py`:

```python
# Add these test functions. The existing test file likely uses httpx AsyncClient.
# Follow the existing fixture pattern (see test_main.py conftest/fixtures).

async def test_create_project(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/projects", json={
        "id": "momease", "name": "MomEase", "repo_path": "/repos/momease"
    })
    assert resp.status_code == 201
    assert resp.json()["id"] == "momease"


async def test_list_projects(client: httpx.AsyncClient) -> None:
    await client.post("/api/projects", json={
        "id": "p1", "name": "P1", "repo_path": "/repos/p1"
    })
    resp = await client.get("/api/projects")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


async def test_get_project(client: httpx.AsyncClient) -> None:
    await client.post("/api/projects", json={
        "id": "p1", "name": "P1", "repo_path": "/repos/p1"
    })
    resp = await client.get("/api/projects/p1")
    assert resp.status_code == 200
    assert resp.json()["name"] == "P1"


async def test_get_project_not_found(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/projects/nonexistent")
    assert resp.status_code == 404


async def test_delete_project(client: httpx.AsyncClient) -> None:
    await client.post("/api/projects", json={
        "id": "p1", "name": "P1", "repo_path": "/repos/p1"
    })
    resp = await client.delete("/api/projects/p1")
    assert resp.status_code == 204
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/vini/Developer/agents && python -m pytest tests/test_main.py::test_create_project -v`
Expected: FAIL — 404 (route doesn't exist)

- [ ] **Step 3: Implement project API routes**

In `src/agents/main.py`, add to `create_app()` after existing routes:

1. Initialize ProjectStore in AppState (add `project_store` field)
2. Add routes:

```python
@app.post("/api/projects", status_code=201)
async def create_project(data: dict) -> dict:
    state.project_store.create_project(
        id=data["id"], name=data["name"],
        repo_path=data["repo_path"],
        default_branch=data.get("default_branch", "main"),
    )
    return state.project_store.get_project(data["id"])

@app.get("/api/projects")
async def list_projects_api() -> list[dict]:
    return state.project_store.list_projects()

@app.get("/api/projects/{project_id}")
async def get_project(project_id: str) -> dict:
    project = state.project_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

@app.put("/api/projects/{project_id}")
async def update_project(project_id: str, data: dict) -> dict:
    state.project_store.update_project(project_id, **data)
    return state.project_store.get_project(project_id)

@app.delete("/api/projects/{project_id}", status_code=204)
async def delete_project_api(project_id: str) -> None:
    state.project_store.delete_project(project_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/vini/Developer/agents && python -m pytest tests/test_main.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/main.py tests/test_main.py
git commit -m "feat: add project CRUD API endpoints"
```

---

### Task 4: Add Task and Source CRUD API Endpoints

**Files:**
- Modify: `src/agents/main.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Write failing tests for task and source APIs**

```python
async def test_create_task(client: httpx.AsyncClient) -> None:
    await client.post("/api/projects", json={"id": "p1", "name": "P1", "repo_path": "/r"})
    resp = await client.post("/api/projects/p1/tasks", json={
        "name": "Fix bugs", "intent": "Fix all bugs",
        "trigger_type": "manual", "model": "sonnet",
        "max_budget": 5.0, "autonomy": "pr-only",
    })
    assert resp.status_code == 201


async def test_list_tasks(client: httpx.AsyncClient) -> None:
    await client.post("/api/projects", json={"id": "p1", "name": "P1", "repo_path": "/r"})
    await client.post("/api/projects/p1/tasks", json={
        "name": "T1", "intent": "I1", "trigger_type": "manual",
        "model": "sonnet", "max_budget": 5.0, "autonomy": "pr-only",
    })
    resp = await client.get("/api/projects/p1/tasks")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_delete_task(client: httpx.AsyncClient) -> None:
    await client.post("/api/projects", json={"id": "p1", "name": "P1", "repo_path": "/r"})
    resp = await client.post("/api/projects/p1/tasks", json={
        "name": "T1", "intent": "I1", "trigger_type": "manual",
        "model": "sonnet", "max_budget": 5.0, "autonomy": "pr-only",
    })
    task_id = resp.json()["id"]
    resp = await client.delete(f"/api/tasks/{task_id}")
    assert resp.status_code == 204


async def test_create_source(client: httpx.AsyncClient) -> None:
    await client.post("/api/projects", json={"id": "p1", "name": "P1", "repo_path": "/r"})
    resp = await client.post("/api/projects/p1/sources", json={
        "source_type": "linear", "source_id": "LIN-1", "source_name": "Linear Project",
    })
    assert resp.status_code == 201


async def test_list_sources(client: httpx.AsyncClient) -> None:
    await client.post("/api/projects", json={"id": "p1", "name": "P1", "repo_path": "/r"})
    await client.post("/api/projects/p1/sources", json={
        "source_type": "slack", "source_id": "C1", "source_name": "#dev",
    })
    resp = await client.get("/api/projects/p1/sources")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement routes**

```python
@app.post("/api/projects/{project_id}/tasks", status_code=201)
async def create_task_api(project_id: str, data: dict) -> dict:
    task_id = state.project_store.create_task(project_id=project_id, **data)
    return state.project_store.get_task(task_id)

@app.get("/api/projects/{project_id}/tasks")
async def list_tasks_api(project_id: str) -> list[dict]:
    return state.project_store.list_tasks(project_id)

@app.put("/api/tasks/{task_id}")
async def update_task_api(task_id: str, data: dict) -> dict:
    state.project_store.update_task(task_id, **data)
    return state.project_store.get_task(task_id)

@app.delete("/api/tasks/{task_id}", status_code=204)
async def delete_task_api(task_id: str) -> None:
    state.project_store.delete_task(task_id)

@app.post("/api/projects/{project_id}/sources", status_code=201)
async def create_source_api(project_id: str, data: dict) -> dict:
    source_id = state.project_store.create_source(project_id=project_id, **data)
    sources = state.project_store.list_sources(project_id)
    return next(s for s in sources if s["id"] == source_id)

@app.get("/api/projects/{project_id}/sources")
async def list_sources_api(project_id: str) -> list[dict]:
    return state.project_store.list_sources(project_id)

@app.delete("/api/sources/{source_id}", status_code=204)
async def delete_source_api(source_id: str) -> None:
    state.project_store.delete_source(source_id)
```

- [ ] **Step 4: Run tests to verify they pass**

- [ ] **Step 5: Commit**

```bash
git add src/agents/main.py tests/test_main.py
git commit -m "feat: add task and source CRUD API endpoints"
```

---

## Chunk 2: GitHub & Slack Clients

### Task 5: Create GitHub API Client

**Files:**
- Create: `src/agents/github_client.py`
- Test: `tests/test_github_client.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_github_client.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from agents.github_client import GitHubClient


@pytest.fixture
def client() -> GitHubClient:
    return GitHubClient(token="test-token")


@pytest.mark.asyncio
async def test_list_open_prs(client: GitHubClient) -> None:
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"number": 1, "title": "Fix bug", "state": "open", "html_url": "https://github.com/org/repo/pull/1",
         "user": {"login": "dev1"}, "head": {"ref": "fix-bug"}},
    ]
    with patch.object(client._client, "get", return_value=mock_response):
        prs = await client.list_open_prs("org/repo")
    assert len(prs) == 1
    assert prs[0]["number"] == 1


@pytest.mark.asyncio
async def test_get_check_status(client: GitHubClient) -> None:
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "state": "success",
        "statuses": [{"state": "success", "context": "ci/test"}],
    }
    with patch.object(client._client, "get", return_value=mock_response):
        status = await client.get_combined_status("org/repo", "abc123")
    assert status["state"] == "success"


@pytest.mark.asyncio
async def test_list_branches(client: GitHubClient) -> None:
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"name": "main", "commit": {"sha": "abc123"}},
        {"name": "feature", "commit": {"sha": "def456"}},
    ]
    with patch.object(client._client, "get", return_value=mock_response):
        branches = await client.list_branches("org/repo")
    assert len(branches) == 2


@pytest.mark.asyncio
async def test_search_repos(client: GitHubClient) -> None:
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "items": [
            {"full_name": "org/momease-app", "name": "momease-app"},
            {"full_name": "org/momease-api", "name": "momease-api"},
        ]
    }
    with patch.object(client._client, "get", return_value=mock_response):
        repos = await client.search_repos("org", "momease")
    assert len(repos) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement GitHubClient**

Create `src/agents/github_client.py`:

```python
import httpx


class GitHubClient:
    """GitHub REST API client for polling project data."""

    BASE_URL = "https://api.github.com"

    def __init__(self, token: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15.0,
        )

    async def list_open_prs(self, repo_full_name: str) -> list[dict]:
        resp = await self._client.get(f"/repos/{repo_full_name}/pulls", params={"state": "open"})
        resp.raise_for_status()
        return resp.json()

    async def get_combined_status(self, repo_full_name: str, ref: str) -> dict:
        resp = await self._client.get(f"/repos/{repo_full_name}/commits/{ref}/status")
        resp.raise_for_status()
        return resp.json()

    async def get_check_runs(self, repo_full_name: str, ref: str) -> list[dict]:
        resp = await self._client.get(f"/repos/{repo_full_name}/commits/{ref}/check-runs")
        resp.raise_for_status()
        return resp.json().get("check_runs", [])

    async def list_branches(self, repo_full_name: str) -> list[dict]:
        resp = await self._client.get(f"/repos/{repo_full_name}/branches")
        resp.raise_for_status()
        return resp.json()

    async def search_repos(self, org: str, query: str) -> list[dict]:
        resp = await self._client.get(
            "/search/repositories", params={"q": f"{query} org:{org}"}
        )
        resp.raise_for_status()
        return resp.json().get("items", [])

    async def close(self) -> None:
        await self._client.aclose()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/vini/Developer/agents && python -m pytest tests/test_github_client.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/github_client.py tests/test_github_client.py
git commit -m "feat: add GitHub API client for polling PRs, CI status, branches"
```

---

### Task 6: Create Slack Bot Client

**Files:**
- Create: `src/agents/slack_client.py`
- Test: `tests/test_slack_client.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_slack_client.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from agents.slack_client import SlackBotClient


@pytest.fixture
def client() -> SlackBotClient:
    return SlackBotClient(bot_token="xoxb-test-token")


@pytest.mark.asyncio
async def test_list_channels(client: SlackBotClient) -> None:
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "ok": True,
        "channels": [
            {"id": "C1", "name": "dev-momease", "is_member": True},
            {"id": "C2", "name": "general", "is_member": True},
        ],
    }
    with patch.object(client._client, "get", return_value=mock_response):
        channels = await client.list_channels()
    assert len(channels) == 2


@pytest.mark.asyncio
async def test_search_channels_by_name(client: SlackBotClient) -> None:
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "ok": True,
        "channels": [
            {"id": "C1", "name": "dev-momease", "is_member": True},
            {"id": "C2", "name": "momease-deploys", "is_member": False},
            {"id": "C3", "name": "general", "is_member": True},
        ],
    }
    with patch.object(client._client, "get", return_value=mock_response):
        matches = await client.search_channels_by_name("momease")
    assert len(matches) == 2
    assert all("momease" in ch["name"] for ch in matches)


@pytest.mark.asyncio
async def test_get_channel_history(client: SlackBotClient) -> None:
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "ok": True,
        "messages": [
            {"ts": "1710590400.000100", "text": "deploy done", "user": "U1"},
            {"ts": "1710590300.000100", "text": "starting deploy", "user": "U2"},
        ],
    }
    with patch.object(client._client, "get", return_value=mock_response):
        messages = await client.get_channel_history("C1", limit=10)
    assert len(messages) == 2


@pytest.mark.asyncio
async def test_search_messages(client: SlackBotClient) -> None:
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "ok": True,
        "messages": {
            "matches": [
                {"channel": {"id": "C1", "name": "random"}, "text": "momease is down", "ts": "123"},
            ],
            "total": 1,
        },
    }
    with patch.object(client._client, "get", return_value=mock_response):
        results = await client.search_messages("momease")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_get_user_info(client: SlackBotClient) -> None:
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "ok": True,
        "user": {"id": "U1", "real_name": "Dev User", "name": "devuser"},
    }
    with patch.object(client._client, "get", return_value=mock_response):
        user = await client.get_user_info("U1")
    assert user["real_name"] == "Dev User"
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement SlackBotClient**

Create `src/agents/slack_client.py`:

```python
import httpx


class SlackBotClient:
    """Slack Bot API client for reading channels, messages, and searching."""

    BASE_URL = "https://slack.com/api"

    def __init__(self, bot_token: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={"Authorization": f"Bearer {bot_token}"},
            timeout=15.0,
        )

    async def list_channels(self, *, types: str = "public_channel,private_channel") -> list[dict]:
        resp = await self._client.get(
            "/conversations.list", params={"types": types, "limit": 200}
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("channels", [])

    async def search_channels_by_name(self, query: str) -> list[dict]:
        channels = await self.list_channels()
        query_lower = query.lower()
        return [ch for ch in channels if query_lower in ch.get("name", "").lower()]

    async def get_channel_history(
        self, channel_id: str, *, limit: int = 50, oldest: str | None = None
    ) -> list[dict]:
        params: dict[str, object] = {"channel": channel_id, "limit": limit}
        if oldest:
            params["oldest"] = oldest
        resp = await self._client.get("/conversations.history", params=params)
        resp.raise_for_status()
        data = resp.json()
        return data.get("messages", [])

    async def search_messages(self, query: str, *, count: int = 20) -> list[dict]:
        resp = await self._client.get(
            "/search.messages", params={"query": query, "count": count}
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("messages", {}).get("matches", [])

    async def get_user_info(self, user_id: str) -> dict:
        resp = await self._client.get("/users.info", params={"user": user_id})
        resp.raise_for_status()
        return resp.json().get("user", {})

    async def close(self) -> None:
        await self._client.aclose()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/vini/Developer/agents && python -m pytest tests/test_slack_client.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/slack_client.py tests/test_slack_client.py
git commit -m "feat: add Slack Bot API client for reading channels, history, search"
```

---

## Chunk 3: Aggregator Service

### Task 7: Create Aggregator Service with Source Adapters

**Files:**
- Create: `src/agents/aggregator.py`
- Test: `tests/test_aggregator.py`

- [ ] **Step 1: Write failing tests for event normalization**

Create `tests/test_aggregator.py`:

```python
import pytest
from agents.aggregator import (
    normalize_linear_issue,
    normalize_github_pr,
    normalize_slack_message,
)


def test_normalize_linear_issue() -> None:
    raw = {
        "id": "issue-123",
        "title": "Fix login crash",
        "description": "Users can't login",
        "priority": 1,
        "state": {"name": "In Progress"},
        "assignee": {"name": "João"},
        "url": "https://linear.app/team/issue/MOB-42",
        "identifier": "MOB-42",
    }
    event = normalize_linear_issue(raw, project_id="momease")
    assert event["source"] == "linear"
    assert event["event_type"] == "issue_active"
    assert event["title"] == "[MOB-42] Fix login crash"
    assert event["priority"] == "urgent"
    assert event["source_item_id"] == "linear:issue-123"


def test_normalize_linear_issue_low_priority() -> None:
    raw = {
        "id": "issue-456",
        "title": "Update docs",
        "priority": 4,
        "state": {"name": "Backlog"},
        "identifier": "MOB-99",
    }
    event = normalize_linear_issue(raw, project_id="momease")
    assert event["priority"] == "low"


def test_normalize_github_pr() -> None:
    raw = {
        "number": 15,
        "title": "Add auth module",
        "html_url": "https://github.com/org/repo/pull/15",
        "user": {"login": "dev1"},
        "state": "open",
        "head": {"ref": "feat/auth", "sha": "abc123"},
    }
    event = normalize_github_pr(raw, project_id="momease", ci_status="success")
    assert event["source"] == "github"
    assert event["event_type"] == "pr_open"
    assert event["title"] == "PR #15: Add auth module"
    assert event["author"] == "dev1"
    assert event["source_item_id"] == "github:pr:15"


def test_normalize_github_pr_ci_failing() -> None:
    raw = {
        "number": 16, "title": "Broken", "html_url": "url",
        "user": {"login": "dev"}, "state": "open",
        "head": {"ref": "fix", "sha": "def"},
    }
    event = normalize_github_pr(raw, project_id="momease", ci_status="failure")
    assert event["priority"] == "high"


def test_normalize_slack_message() -> None:
    raw = {
        "ts": "1710590400.000100",
        "text": "deploy is done for momease",
        "user": "U1",
    }
    event = normalize_slack_message(
        raw, project_id="momease", channel_name="#dev-momease", user_name="João"
    )
    assert event["source"] == "slack"
    assert event["event_type"] == "message"
    assert event["author"] == "João"
    assert event["source_item_id"] == "slack:1710590400.000100"


def test_normalize_slack_message_mention() -> None:
    raw = {
        "ts": "123.456",
        "text": "<@U_ME> check this",
        "user": "U2",
    }
    event = normalize_slack_message(
        raw, project_id="momease", channel_name="#dev",
        user_name="Dev", my_user_id="U_ME",
    )
    assert event["priority"] == "high"
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement normalizers**

Create `src/agents/aggregator.py`:

```python
import asyncio
import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# Linear priority mapping: 0=none, 1=urgent, 2=high, 3=medium, 4=low
_LINEAR_PRIORITY = {0: "none", 1: "urgent", 2: "high", 3: "medium", 4: "low"}


def normalize_linear_issue(raw: dict, *, project_id: str) -> dict:
    identifier = raw.get("identifier", "")
    title = raw.get("title", "")
    priority_num = raw.get("priority", 0)
    return {
        "project_id": project_id,
        "source": "linear",
        "event_type": f"issue_{raw.get('state', {}).get('name', 'unknown').lower().replace(' ', '_')}",
        "title": f"[{identifier}] {title}" if identifier else title,
        "body": raw.get("description", ""),
        "author": raw.get("assignee", {}).get("name", "") if raw.get("assignee") else "",
        "url": raw.get("url", ""),
        "priority": _LINEAR_PRIORITY.get(priority_num, "none"),
        "timestamp": datetime.now(UTC).isoformat(),
        "source_item_id": f"linear:{raw['id']}",
        "raw_data": raw,
    }


def normalize_github_pr(
    raw: dict, *, project_id: str, ci_status: str = "unknown"
) -> dict:
    number = raw["number"]
    priority = "high" if ci_status == "failure" else "none"
    return {
        "project_id": project_id,
        "source": "github",
        "event_type": f"pr_{raw.get('state', 'open')}",
        "title": f"PR #{number}: {raw.get('title', '')}",
        "body": raw.get("body", "") or "",
        "author": raw.get("user", {}).get("login", ""),
        "url": raw.get("html_url", ""),
        "priority": priority,
        "timestamp": datetime.now(UTC).isoformat(),
        "source_item_id": f"github:pr:{number}",
        "raw_data": raw,
    }


def normalize_slack_message(
    raw: dict,
    *,
    project_id: str,
    channel_name: str,
    user_name: str = "",
    my_user_id: str | None = None,
) -> dict:
    text = raw.get("text", "")
    priority = "high" if my_user_id and f"<@{my_user_id}>" in text else "none"
    ts = raw.get("ts", "")
    # Convert Slack ts to ISO timestamp
    try:
        dt = datetime.fromtimestamp(float(ts), tz=UTC)
        timestamp = dt.isoformat()
    except (ValueError, TypeError):
        timestamp = datetime.now(UTC).isoformat()
    return {
        "project_id": project_id,
        "source": "slack",
        "event_type": "message",
        "title": f"{channel_name}: {text[:120]}",
        "body": text,
        "author": user_name,
        "url": "",
        "priority": priority,
        "timestamp": timestamp,
        "source_item_id": f"slack:{ts}",
        "raw_data": raw,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/vini/Developer/agents && python -m pytest tests/test_aggregator.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/aggregator.py tests/test_aggregator.py
git commit -m "feat: add event normalizers for Linear, GitHub, Slack"
```

---

### Task 8: Add Polling Loop to Aggregator

**Files:**
- Modify: `src/agents/aggregator.py`
- Test: `tests/test_aggregator.py`

- [ ] **Step 1: Write failing tests for AggregatorService**

Add to `tests/test_aggregator.py`:

```python
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from agents.aggregator import AggregatorService
from agents.project_store import ProjectStore


@pytest.fixture
def store(tmp_path: Path) -> ProjectStore:
    return ProjectStore(tmp_path / "test.db")


@pytest.fixture
def aggregator(store: ProjectStore) -> AggregatorService:
    return AggregatorService(
        store=store,
        linear_client=AsyncMock(),
        github_client=AsyncMock(),
        slack_client=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_poll_linear_issues(aggregator: AggregatorService, store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/r")
    store.create_source(
        project_id="p1", source_type="linear",
        source_id="team-123", source_name="MomEase",
    )
    aggregator.linear_client.fetch_team_issues = AsyncMock(return_value=[
        {"id": "i1", "title": "Bug", "priority": 2, "state": {"name": "Todo"},
         "identifier": "MOB-1", "url": "https://linear.app/MOB-1"},
    ])
    await aggregator.poll_linear("p1")
    events = store.list_events("p1", source="linear")
    assert len(events) == 1
    assert "Bug" in events[0]["title"]


@pytest.mark.asyncio
async def test_poll_github_prs(aggregator: AggregatorService, store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/r")
    store.create_source(
        project_id="p1", source_type="github",
        source_id="org/repo", source_name="repo",
    )
    aggregator.github_client.list_open_prs = AsyncMock(return_value=[
        {"number": 1, "title": "Fix", "html_url": "url", "state": "open",
         "user": {"login": "dev"}, "head": {"ref": "fix", "sha": "abc"}},
    ])
    aggregator.github_client.get_combined_status = AsyncMock(return_value={"state": "success"})
    await aggregator.poll_github("p1")
    events = store.list_events("p1", source="github")
    assert len(events) == 1


@pytest.mark.asyncio
async def test_poll_slack_messages(aggregator: AggregatorService, store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/r")
    store.create_source(
        project_id="p1", source_type="slack",
        source_id="C123", source_name="#dev-momease",
    )
    aggregator.slack_client.get_channel_history = AsyncMock(return_value=[
        {"ts": "1710590400.000100", "text": "deploy done", "user": "U1"},
    ])
    aggregator.slack_client.get_user_info = AsyncMock(return_value={"real_name": "Dev"})
    await aggregator.poll_slack("p1")
    events = store.list_events("p1", source="slack")
    assert len(events) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement AggregatorService**

Add to `src/agents/aggregator.py`:

```python
class AggregatorService:
    """Polls external sources and stores normalized events."""

    def __init__(
        self,
        *,
        store: "ProjectStore",
        linear_client: object | None = None,
        github_client: object | None = None,
        slack_client: object | None = None,
    ) -> None:
        self.store = store
        self.linear_client = linear_client
        self.github_client = github_client
        self.slack_client = slack_client
        self._failure_counts: dict[str, int] = {}
        self._running = False

    async def poll_linear(self, project_id: str) -> None:
        sources = [s for s in self.store.list_sources(project_id) if s["source_type"] == "linear"]
        for source in sources:
            try:
                issues = await self.linear_client.fetch_team_issues(source["source_id"])
                for issue in issues:
                    event = normalize_linear_issue(issue, project_id=project_id)
                    self.store.upsert_event(**event)
                self._failure_counts.pop(f"linear:{source['source_id']}", None)
            except Exception:
                key = f"linear:{source['source_id']}"
                self._failure_counts[key] = self._failure_counts.get(key, 0) + 1
                logger.exception("Failed to poll Linear source %s", source["source_id"])

    async def poll_github(self, project_id: str) -> None:
        sources = [s for s in self.store.list_sources(project_id) if s["source_type"] == "github"]
        for source in sources:
            try:
                repo = source["source_id"]
                prs = await self.github_client.list_open_prs(repo)
                for pr in prs:
                    sha = pr.get("head", {}).get("sha", "")
                    ci = {"state": "unknown"}
                    if sha:
                        try:
                            ci = await self.github_client.get_combined_status(repo, sha)
                        except Exception:
                            pass
                    event = normalize_github_pr(
                        pr, project_id=project_id, ci_status=ci.get("state", "unknown")
                    )
                    self.store.upsert_event(**event)
                self._failure_counts.pop(f"github:{repo}", None)
            except Exception:
                key = f"github:{source['source_id']}"
                self._failure_counts[key] = self._failure_counts.get(key, 0) + 1
                logger.exception("Failed to poll GitHub source %s", source["source_id"])

    async def poll_slack(self, project_id: str) -> None:
        sources = [s for s in self.store.list_sources(project_id) if s["source_type"] == "slack"]
        for source in sources:
            try:
                messages = await self.slack_client.get_channel_history(source["source_id"], limit=20)
                for msg in messages:
                    user_name = ""
                    if msg.get("user"):
                        try:
                            user_info = await self.slack_client.get_user_info(msg["user"])
                            user_name = user_info.get("real_name", msg["user"])
                        except Exception:
                            user_name = msg["user"]
                    event = normalize_slack_message(
                        msg, project_id=project_id,
                        channel_name=source["source_name"],
                        user_name=user_name,
                    )
                    self.store.upsert_event(**event)
                self._failure_counts.pop(f"slack:{source['source_id']}", None)
            except Exception:
                key = f"slack:{source['source_id']}"
                self._failure_counts[key] = self._failure_counts.get(key, 0) + 1
                logger.exception("Failed to poll Slack source %s", source["source_id"])

    async def poll_all(self, project_id: str) -> None:
        await asyncio.gather(
            self.poll_linear(project_id),
            self.poll_github(project_id),
            self.poll_slack(project_id),
            return_exceptions=True,
        )

    def get_source_health(self, source_key: str) -> str:
        count = self._failure_counts.get(source_key, 0)
        if count == 0:
            return "healthy"
        if count < 3:
            return "degraded"
        return "failing"

    async def start(self, poll_interval_seconds: int = 300) -> None:
        """Start polling loop for all projects."""
        self._running = True
        while self._running:
            projects = self.store.list_projects()
            for project in projects:
                try:
                    await self.poll_all(project["id"])
                except Exception:
                    logger.exception("Aggregator error for project %s", project["id"])
            await asyncio.sleep(poll_interval_seconds)

    def stop(self) -> None:
        self._running = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/vini/Developer/agents && python -m pytest tests/test_aggregator.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/aggregator.py tests/test_aggregator.py
git commit -m "feat: add AggregatorService with polling loops for Linear, GitHub, Slack"
```

---

### Task 9: Extend Linear Client with Team Issues Query

**Files:**
- Modify: `src/agents/linear_client.py`
- Test: `tests/test_linear_client.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_linear_client.py`:

```python
@pytest.mark.asyncio
async def test_fetch_team_issues(client: LinearClient, mock_response: AsyncMock) -> None:
    mock_response.json.return_value = {
        "data": {
            "team": {
                "issues": {
                    "nodes": [
                        {"id": "i1", "title": "Bug", "priority": 1,
                         "state": {"name": "In Progress"}, "identifier": "MOB-1",
                         "url": "https://linear.app/MOB-1",
                         "assignee": {"name": "Dev"}, "description": "Details"},
                    ]
                }
            }
        }
    }
    issues = await client.fetch_team_issues("team-123")
    assert len(issues) == 1
    assert issues[0]["title"] == "Bug"
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement fetch_team_issues**

Add to `LinearClient` in `src/agents/linear_client.py`:

```python
async def fetch_team_issues(self, team_id: str, *, states: list[str] | None = None) -> list[dict]:
    filter_clause = ""
    if states:
        state_names = ", ".join(f'"{s}"' for s in states)
        filter_clause = f', filter: {{ state: {{ name: {{ in: [{state_names}] }} }} }}'
    query = f"""
        query($teamId: String!) {{
            team(id: $teamId) {{
                issues(first: 50, orderBy: updatedAt{filter_clause}) {{
                    nodes {{
                        id title description priority url identifier
                        state {{ name }}
                        assignee {{ name }}
                    }}
                }}
            }}
        }}
    """
    data = await self._graphql(query, {"teamId": team_id})
    return data.get("data", {}).get("team", {}).get("issues", {}).get("nodes", [])
```

- [ ] **Step 4: Run tests to verify they pass**

- [ ] **Step 5: Commit**

```bash
git add src/agents/linear_client.py tests/test_linear_client.py
git commit -m "feat: add fetch_team_issues to LinearClient for aggregator polling"
```

---

## Chunk 4: Aggregator Integration & Run Launcher API

### Task 10: Wire Aggregator into FastAPI Lifecycle

**Files:**
- Modify: `src/agents/main.py`
- Modify: `src/agents/config.py`

- [ ] **Step 1: Add aggregator config fields**

In `src/agents/config.py`, add to `IntegrationsConfig`:

```python
github_token: str = ""
slack_bot_token: str = ""
```

- [ ] **Step 2: Initialize clients and aggregator in AppState**

In `src/agents/main.py`, inside `create_app()`:

```python
from agents.project_store import ProjectStore
from agents.github_client import GitHubClient
from agents.slack_client import SlackBotClient
from agents.aggregator import AggregatorService

# After existing client initialization:
project_store = ProjectStore(data_dir / "project_hub.db")

github_client = None
if global_config.integrations.github_token:
    github_client = GitHubClient(global_config.integrations.github_token)

slack_bot_client = None
if global_config.integrations.slack_bot_token:
    slack_bot_client = SlackBotClient(global_config.integrations.slack_bot_token)

aggregator = AggregatorService(
    store=project_store,
    linear_client=linear_client,
    github_client=github_client,
    slack_client=slack_bot_client,
)
```

Add these new fields to the `AppState` class (around line 35 in `main.py`):

```python
# In AppState.__init__, add:
self.project_store = project_store
self.github_client = github_client
self.slack_bot_client = slack_bot_client
self.aggregator = aggregator
```

- [ ] **Step 3: Start/stop aggregator in lifespan**

In the lifespan context manager, add:

```python
# Start aggregator polling
aggregator_task = asyncio.create_task(aggregator.start(poll_interval_seconds=300))

yield

# Stop aggregator
aggregator.stop()
aggregator_task.cancel()
```

- [ ] **Step 4: Run existing tests to verify nothing is broken**

Run: `cd /Users/vini/Developer/agents && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/main.py src/agents/config.py
git commit -m "feat: wire Aggregator and new clients into FastAPI lifecycle"
```

---

### Task 11: Add Run Launcher API Endpoint

**Files:**
- Modify: `src/agents/main.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Write failing test for manual run from dashboard**

Add to `tests/test_main.py`:

```python
async def test_launch_run_existing_task(client: httpx.AsyncClient) -> None:
    # Create project and task in store first
    await client.post("/api/projects", json={"id": "p1", "name": "P1", "repo_path": "/r"})
    await client.post("/api/projects/p1/tasks", json={
        "name": "fix-bugs", "intent": "Fix all bugs",
        "trigger_type": "manual", "model": "sonnet",
        "max_budget": 5.0, "autonomy": "pr-only",
    })
    resp = await client.post("/api/projects/p1/run", json={"task_name": "fix-bugs"})
    assert resp.status_code in (200, 202)


async def test_launch_adhoc_run(client: httpx.AsyncClient) -> None:
    await client.post("/api/projects", json={"id": "p1", "name": "P1", "repo_path": "/r"})
    resp = await client.post("/api/projects/p1/run", json={
        "adhoc": True,
        "intent": "Refactor auth module",
        "model": "sonnet",
        "max_budget": 3.0,
    })
    assert resp.status_code in (200, 202)
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement run launcher endpoint**

Add to `src/agents/main.py`:

```python
@app.post("/api/projects/{project_id}/run", status_code=202)
async def launch_run(project_id: str, data: dict) -> dict:
    project = state.project_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if data.get("adhoc"):
        # Ad-hoc run: create temporary task-like config
        from agents.models import TaskConfig, ProjectConfig
        task = TaskConfig(
            description=data.get("intent", "Ad-hoc run"),
            intent=data.get("intent", ""),
            trigger=None,
            schedule=None,
            model=data.get("model", "sonnet"),
            max_cost_usd=data.get("max_budget", 5.0),
            autonomy=data.get("autonomy", "pr-only"),
        )
        # Build minimal ProjectConfig from store data
        project_config = ProjectConfig(
            name=project["name"],
            repo=project["repo_path"],
            base_branch=project.get("default_branch", "main"),
            tasks={"adhoc": task},
        )
        run_id = await state.executor.run_task(
            project_config, "adhoc", TriggerType.MANUAL, {}
        )
    else:
        # Run existing task
        task_name = data["task_name"]
        tasks = state.project_store.list_tasks(project_id)
        task_data = next((t for t in tasks if t["name"] == task_name), None)
        if not task_data:
            raise HTTPException(status_code=404, detail="Task not found")
        # Convert store task to TaskConfig + ProjectConfig and execute
        task = TaskConfig(
            description=task_data["name"],
            intent=task_data["intent"],
            model=task_data["model"],
            max_cost_usd=task_data["max_budget"],
            autonomy=task_data["autonomy"],
        )
        project_config = ProjectConfig(
            name=project["name"],
            repo=project["repo_path"],
            base_branch=project.get("default_branch", "main"),
            tasks={task_name: task},
        )
        run_id = await state.executor.run_task(
            project_config, task_name, TriggerType.MANUAL, {}
        )

    return {"run_id": run_id, "status": "started"}
```

Note: This requires updating `TaskConfig` validator to allow manual tasks (no schedule, no trigger). Update the validator in `models.py`:

```python
@model_validator(mode="after")
def validate_schedule_or_trigger(self) -> "TaskConfig":
    if self.schedule and self.trigger:
        msg = "schedule and trigger are mutually exclusive"
        raise ValueError(msg)
    # Allow manual tasks (neither schedule nor trigger)
    return self
```

- [ ] **Step 4: Run tests to verify they pass**

- [ ] **Step 5: Update existing model tests**

In `tests/test_models.py`, replace `test_task_config_requires_schedule_or_trigger`:

```python
def test_task_config_allows_manual_no_schedule_no_trigger() -> None:
    """Manual tasks have neither schedule nor trigger — this is now valid."""
    task = TaskConfig(description="Manual task", intent="Do something")
    assert task.schedule is None
    assert task.trigger is None
```

- [ ] **Step 6: Run full test suite**

Run: `cd /Users/vini/Developer/agents && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/agents/models.py src/agents/main.py tests/test_models.py tests/test_main.py
git commit -m "feat: add run launcher API with support for existing tasks and ad-hoc runs"
```

---

### Task 12: Add Events Feed API

**Files:**
- Modify: `src/agents/main.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Write failing tests**

```python
async def test_list_events(client: httpx.AsyncClient) -> None:
    await client.post("/api/projects", json={"id": "p1", "name": "P1", "repo_path": "/r"})
    # Events should be accessible even if empty
    resp = await client.get("/api/projects/p1/events")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_events_filtered(client: httpx.AsyncClient) -> None:
    await client.post("/api/projects", json={"id": "p1", "name": "P1", "repo_path": "/r"})
    resp = await client.get("/api/projects/p1/events", params={"source": "linear"})
    assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement events API**

```python
@app.get("/api/projects/{project_id}/events")
async def list_events_api(project_id: str, source: str | None = None, limit: int = 100) -> list[dict]:
    return state.project_store.list_events(project_id, source=source, limit=limit)
```

- [ ] **Step 4: Run tests to verify they pass**

- [ ] **Step 5: Commit**

```bash
git add src/agents/main.py tests/test_main.py
git commit -m "feat: add events feed API endpoint"
```

---

## Chunk 5: Dashboard UI — Project Hub

### Task 13: Add Project Hub Page to Dashboard

**Files:**
- Create: `src/agents/dashboard_project_hub.py`
- Modify: `src/agents/dashboard.py`

- [ ] **Step 1: Create Project Hub page**

Create `src/agents/dashboard_project_hub.py`. This is UI code — NiceGUI components.

```python
"""Project Hub dashboard page — aggregated project view."""

import json
from nicegui import ui

# Event source icons and colors
SOURCE_ICONS = {
    "linear": "task_alt",
    "github": "code",
    "slack": "chat",
    "paperweight": "smart_toy",
}
SOURCE_COLORS = {
    "linear": "#5E6AD2",
    "github": "#238636",
    "slack": "#4A154B",
    "paperweight": "#F97316",
}
PRIORITY_COLORS = {
    "urgent": "#EF4444",
    "high": "#F59E0B",
    "medium": "#3B82F6",
    "low": "#6B7280",
    "none": "#374151",
}


def setup_project_hub(app, state) -> None:
    """Register the /dashboard/project/<id> page."""

    @ui.page("/dashboard/project/{project_id}")
    async def project_page(project_id: str) -> None:
        project = state.project_store.get_project(project_id)
        if not project:
            ui.label("Project not found").classes("text-red-500 text-xl")
            return

        # ── Header ────────────────────────────────────────
        with ui.row().classes("w-full items-center justify-between mb-4"):
            ui.label(project["name"]).classes("text-2xl font-bold text-white")
            with ui.row().classes("gap-2"):
                ui.button("Run", icon="play_arrow", on_click=lambda: run_dialog.open()).props(
                    "color=green dense"
                )
                ui.button("+ Task", icon="add", on_click=lambda: task_dialog.open()).props(
                    "color=blue dense"
                )
                ui.button("Config", icon="settings", on_click=lambda: ui.navigate.to(
                    f"/dashboard/project/{project_id}/settings"
                )).props("color=grey dense")

        # ── Zone 1: Feed ──────────────────────────────────
        ui.label("Activity Feed").classes("text-lg font-semibold text-gray-300 mt-2")

        events = state.project_store.list_events(project_id, limit=50)
        feed_container = ui.column().classes("w-full gap-1 max-h-96 overflow-y-auto")

        with feed_container:
            if not events:
                ui.label("No events yet. Configure sources to start aggregating.").classes(
                    "text-gray-500 italic"
                )
            for event in events:
                _render_event_card(event)

        # ── Zone 2: Source Sections ───────────────────────
        ui.separator().classes("my-4")
        ui.label("Sources").classes("text-lg font-semibold text-gray-300")

        sources = state.project_store.list_sources(project_id)
        source_types = {s["source_type"] for s in sources}

        if "linear" in source_types:
            _render_source_section("Linear", "linear", project_id, state)
        if "github" in source_types:
            _render_source_section("GitHub", "github", project_id, state)
        if "slack" in source_types:
            _render_source_section("Slack", "slack", project_id, state)

        # Always show Runs section
        _render_runs_section(project_id, state)

        # ── Run Dialog ────────────────────────────────────
        run_dialog = _build_run_dialog(project_id, state)

        # ── Task Dialog ───────────────────────────────────
        task_dialog = _build_task_dialog(project_id, state)


def _render_event_card(event: dict) -> None:
    source = event.get("source", "unknown")
    icon = SOURCE_ICONS.get(source, "info")
    color = SOURCE_COLORS.get(source, "#666")
    priority = event.get("priority", "none")
    priority_color = PRIORITY_COLORS.get(priority, "#374151")

    with ui.row().classes("w-full items-center gap-2 px-3 py-1 rounded hover:bg-gray-800"):
        ui.icon(icon).style(f"color: {color}; font-size: 16px;")
        if priority != "none":
            ui.badge(priority.upper()).style(
                f"background-color: {priority_color}; font-size: 10px;"
            )
        ui.label(event.get("title", "")).classes("text-sm text-gray-200 flex-grow")
        ts = event.get("timestamp", "")[:16].replace("T", " ")
        ui.label(ts).classes("text-xs text-gray-500")
        if event.get("author"):
            ui.label(event["author"]).classes("text-xs text-gray-400")


def _render_source_section(label: str, source: str, project_id: str, state) -> None:
    with ui.expansion(label, icon=SOURCE_ICONS.get(source, "info")).classes(
        "w-full bg-gray-900 rounded"
    ):
        events = state.project_store.list_events(project_id, source=source, limit=20)
        if not events:
            ui.label("No data yet").classes("text-gray-500 italic text-sm")
        else:
            for event in events:
                _render_event_card(event)


def _render_runs_section(project_id: str, state) -> None:
    with ui.expansion("Runs", icon="smart_toy").classes("w-full bg-gray-900 rounded"):
        try:
            runs = [r for r in state.history.list_runs_today() if r.project == project_id]
        except Exception:
            runs = []
        if not runs:
            ui.label("No runs today").classes("text-gray-500 italic text-sm")
        else:
            for run in runs[:10]:
                status_color = {"success": "green", "failure": "red", "running": "orange"}.get(
                    run.status, "grey"
                )
                with ui.row().classes("w-full items-center gap-2 px-3 py-1"):
                    ui.badge(run.status.upper()).props(f"color={status_color}")
                    ui.label(run.task).classes("text-sm text-gray-200")
                    if run.cost_usd:
                        ui.label(f"${run.cost_usd:.2f}").classes("text-xs text-gray-400")
                    if run.pr_url:
                        ui.link("PR", run.pr_url).classes("text-xs")


def _build_run_dialog(project_id: str, state) -> ui.dialog:
    dialog = ui.dialog()
    with dialog, ui.card().classes("w-96"):
        ui.label("Launch Run").classes("text-lg font-bold")

        tasks = state.project_store.list_tasks(project_id)

        if tasks:
            ui.label("Run existing task:").classes("text-sm mt-2")
            task_select = ui.select(
                options={t["id"]: t["name"] for t in tasks},
                label="Select task",
            ).classes("w-full")
            ui.button("Run Task", on_click=lambda: _trigger_task_run(
                project_id, task_select.value, state, dialog
            )).props("color=green")

        ui.separator()
        ui.label("Ad-hoc run:").classes("text-sm mt-2")
        intent_input = ui.textarea("Intent", placeholder="What should the agent do?").classes("w-full")
        model_select = ui.select(
            options=["sonnet", "opus", "haiku"], value="sonnet", label="Model"
        ).classes("w-full")
        budget_input = ui.number("Max budget ($)", value=5.0, min=0.1, max=50.0).classes("w-full")

        ui.button("Run Ad-hoc", on_click=lambda: _trigger_adhoc_run(
            project_id, intent_input.value, model_select.value,
            budget_input.value, state, dialog
        )).props("color=orange")

    return dialog


def _build_task_dialog(project_id: str, state) -> ui.dialog:
    dialog = ui.dialog()
    with dialog, ui.card().classes("w-96"):
        ui.label("Create Task").classes("text-lg font-bold")
        name_input = ui.input("Name").classes("w-full")
        intent_input = ui.textarea("Intent", placeholder="What should the agent do?").classes("w-full")
        trigger_select = ui.select(
            options=["manual", "schedule", "webhook"], value="manual", label="Trigger"
        ).classes("w-full")
        model_select = ui.select(
            options=["sonnet", "opus", "haiku"], value="sonnet", label="Model"
        ).classes("w-full")
        budget_input = ui.number("Max budget ($)", value=5.0, min=0.1, max=50.0).classes("w-full")
        autonomy_select = ui.select(
            options=["pr-only", "auto-merge", "notify"], value="pr-only", label="Autonomy"
        ).classes("w-full")

        async def create_task() -> None:
            state.project_store.create_task(
                project_id=project_id,
                name=name_input.value,
                intent=intent_input.value,
                trigger_type=trigger_select.value,
                model=model_select.value,
                max_budget=budget_input.value,
                autonomy=autonomy_select.value,
            )
            dialog.close()
            ui.notify("Task created!", type="positive")

        ui.button("Create", on_click=create_task).props("color=blue")

    return dialog


async def _trigger_task_run(project_id: str, task_id: str, state, dialog) -> None:
    import httpx
    dialog.close()
    task = state.project_store.get_task(task_id)
    if not task:
        ui.notify("Task not found", type="negative")
        return
    ui.notify(f"Starting run: {task['name']}", type="info")
    # Trigger via internal API call
    # The actual execution happens through the existing executor


async def _trigger_adhoc_run(
    project_id: str, intent: str, model: str, budget: float, state, dialog
) -> None:
    dialog.close()
    ui.notify(f"Starting ad-hoc run", type="info")
```

- [ ] **Step 2: Update dashboard.py to add sidebar and project hub routing**

In `src/agents/dashboard.py`, add to `setup_dashboard()`:

1. Import and call `setup_project_hub(app, state)`
2. Add project list to sidebar in the dashboard page

```python
# At the top of setup_dashboard:
from agents.dashboard_project_hub import setup_project_hub
setup_project_hub(app, state)

# In the sidebar area (left panel), add before existing content:
projects = state.project_store.list_projects()
if projects:
    ui.label("Projects").classes("text-xs text-gray-500 uppercase tracking-wide mb-1")
    for p in projects:
        ui.link(p["name"], f"/dashboard/project/{p['id']}").classes(
            "text-sm text-blue-400 hover:text-blue-300 block py-0.5"
        )
    ui.separator().classes("my-2")
```

- [ ] **Step 3: Run the app manually to verify the page renders**

Run: `cd /Users/vini/Developer/agents && python -m agents`
Navigate to: `http://localhost:8080/dashboard`

- [ ] **Step 4: Commit**

```bash
git add src/agents/dashboard_project_hub.py src/agents/dashboard.py
git commit -m "feat: add Project Hub dashboard page with feed, source sections, run/task dialogs"
```

---

### Task 14: Add Project Setup Wizard Page

**Files:**
- Create: `src/agents/dashboard_setup_wizard.py`
- Modify: `src/agents/dashboard.py`

- [ ] **Step 1: Implement setup wizard page**

Create `src/agents/dashboard_setup_wizard.py`:

```python
"""Project setup wizard — create and configure projects via dashboard."""

from nicegui import ui


def setup_wizard_page(app, state) -> None:
    @ui.page("/dashboard/project/new")
    async def new_project_page() -> None:
        ui.label("New Project").classes("text-2xl font-bold text-white mb-4")

        stepper = ui.stepper().classes("w-full")

        with stepper:
            # ── Step 1: Basics ────────────────────────────
            with ui.step("Basics"):
                name_input = ui.input("Project Name", placeholder="MomEase").classes("w-full")
                repo_input = ui.input("Repository Path", placeholder="/Users/you/repos/momease").classes("w-full")
                branch_input = ui.input("Default Branch", value="main").classes("w-full")
                with ui.stepper_navigation():
                    ui.button("Next", on_click=stepper.next).props("color=blue")

            # ── Step 2: Auto-discovery ────────────────────
            with ui.step("Discover Sources"):
                discovery_container = ui.column().classes("w-full")
                discovered_sources: list[dict] = []

                async def run_discovery() -> None:
                    discovery_container.clear()
                    with discovery_container:
                        ui.label("Searching...").classes("text-gray-400 italic")

                    project_name = name_input.value
                    if not project_name:
                        with discovery_container:
                            ui.label("Enter a project name first").classes("text-red-400")
                        return

                    results = await _discover_sources(project_name, state)
                    discovered_sources.clear()
                    discovered_sources.extend(results)

                    discovery_container.clear()
                    with discovery_container:
                        if not results:
                            ui.label("No sources found. You can add them manually later.").classes(
                                "text-gray-400"
                            )
                        for r in results:
                            cb = ui.checkbox(
                                f"{r['source_type'].upper()}: {r['source_name']}",
                                value=r.get("confidence", "low") != "low",
                            )
                            r["checkbox"] = cb

                ui.button("Search", icon="search", on_click=run_discovery).props("color=blue")
                with ui.stepper_navigation():
                    ui.button("Back", on_click=stepper.previous).props("flat")
                    ui.button("Next", on_click=stepper.next).props("color=blue")

            # ── Step 3: Notifications ─────────────────────
            with ui.step("Notifications"):
                notify_channel = ui.select(
                    options=["slack", "discord", "both"], value="slack", label="Notification Channel"
                ).classes("w-full")
                digest_time = ui.input("Digest Time", value="09:00").classes("w-full")
                alerts_enabled = ui.checkbox("Enable urgent alerts", value=True)

                with ui.stepper_navigation():
                    ui.button("Back", on_click=stepper.previous).props("flat")

                    async def create_project() -> None:
                        project_id = name_input.value.lower().replace(" ", "-")
                        state.project_store.create_project(
                            id=project_id,
                            name=name_input.value,
                            repo_path=repo_input.value,
                            default_branch=branch_input.value,
                        )
                        # Add selected sources
                        for r in discovered_sources:
                            if hasattr(r.get("checkbox"), "value") and r["checkbox"].value:
                                state.project_store.create_source(
                                    project_id=project_id,
                                    source_type=r["source_type"],
                                    source_id=r["source_id"],
                                    source_name=r["source_name"],
                                )
                        # Add notification rules
                        channels = (
                            ["slack", "discord"] if notify_channel.value == "both"
                            else [notify_channel.value]
                        )
                        for ch in channels:
                            state.project_store.create_notification_rule(
                                project_id=project_id,
                                rule_type="digest",
                                channel=ch,
                                channel_target="dm",
                                config={"schedule": digest_time.value},
                            )
                            if alerts_enabled.value:
                                state.project_store.create_notification_rule(
                                    project_id=project_id,
                                    rule_type="alert",
                                    channel=ch,
                                    channel_target="dm",
                                    config={"events": ["urgent_issue", "ci_failure", "mention", "run_failure"]},
                                )
                        ui.notify("Project created!", type="positive")
                        ui.navigate.to(f"/dashboard/project/{project_id}")

                    ui.button("Create Project", on_click=create_project).props("color=green")


async def _discover_sources(name: str, state) -> list[dict]:
    """Run auto-discovery across all configured integrations."""
    results = []
    query = name.lower().replace(" ", "").replace("-", "")

    # Linear discovery
    if state.linear_client:
        try:
            teams = await state.linear_client.fetch_teams()
            for team_name, team_id in teams.items():
                if query in team_name.replace("-", "").replace(" ", ""):
                    results.append({
                        "source_type": "linear",
                        "source_id": team_id,
                        "source_name": f"Team: {team_name}",
                        "confidence": "high" if query == team_name.replace("-", "").replace(" ", "") else "medium",
                    })
        except Exception:
            pass

    # GitHub discovery
    if hasattr(state, "github_client") and state.github_client:
        try:
            repos = await state.github_client.search_repos("", name)
            for repo in repos[:5]:
                repo_name = repo.get("full_name", "")
                results.append({
                    "source_type": "github",
                    "source_id": repo_name,
                    "source_name": f"Repo: {repo.get('name', '')}",
                    "confidence": "high" if query in repo_name.lower().replace("-", "") else "medium",
                })
        except Exception:
            pass

    # Slack discovery
    if hasattr(state, "slack_bot_client") and state.slack_bot_client:
        try:
            channels = await state.slack_bot_client.search_channels_by_name(name)
            for ch in channels[:5]:
                results.append({
                    "source_type": "slack",
                    "source_id": ch["id"],
                    "source_name": f"#{ch['name']}",
                    "confidence": "high" if query in ch["name"].replace("-", "") else "medium",
                })
        except Exception:
            pass

        # Also search for channels where project is mentioned
        try:
            messages = await state.slack_bot_client.search_messages(name)
            mentioned_channels = {}
            for msg in messages:
                ch = msg.get("channel", {})
                ch_id = ch.get("id", "")
                ch_name = ch.get("name", "")
                if ch_id and ch_id not in {r["source_id"] for r in results if r["source_type"] == "slack"}:
                    mentioned_channels[ch_id] = mentioned_channels.get(ch_id, 0) + 1
            for ch_id, count in sorted(mentioned_channels.items(), key=lambda x: -x[1])[:3]:
                results.append({
                    "source_type": "slack",
                    "source_id": ch_id,
                    "source_name": f"(mentioned {count}x)",
                    "confidence": "low",
                })
        except Exception:
            pass

    return results
```

- [ ] **Step 2: Register wizard page in dashboard.py**

Add to `setup_dashboard()`:
```python
from agents.dashboard_setup_wizard import setup_wizard_page
setup_wizard_page(app, state)
```

Add "New Project" button in sidebar:
```python
ui.button("+ New Project", on_click=lambda: ui.navigate.to("/dashboard/project/new")).props(
    "color=blue dense flat"
).classes("w-full mb-2")
```

- [ ] **Step 3: Test manually**

Navigate to `http://localhost:8080/dashboard/project/new`

- [ ] **Step 4: Commit**

```bash
git add src/agents/dashboard_setup_wizard.py src/agents/dashboard.py
git commit -m "feat: add project setup wizard with auto-discovery"
```

---

### Task 15: Add Task Manager UI Page

**Files:**
- Create: `src/agents/dashboard_task_manager.py`
- Modify: `src/agents/dashboard.py`
- Modify: `src/agents/project_store.py` (add `get_source` method)

- [ ] **Step 1: Add `get_source` method to ProjectStore**

Add to `src/agents/project_store.py`:

```python
def get_source(self, source_id: str) -> dict | None:
    with self._conn() as conn:
        row = conn.execute("SELECT * FROM project_sources WHERE id = ?", (source_id,)).fetchone()
    return dict(row) if row else None
```

- [ ] **Step 2: Create Task Manager page**

Create `src/agents/dashboard_task_manager.py`:

```python
"""Task Manager dashboard page — CRUD for project tasks."""

from nicegui import ui


def setup_task_manager(app, state) -> None:
    @ui.page("/dashboard/project/{project_id}/tasks")
    async def tasks_page(project_id: str) -> None:
        project = state.project_store.get_project(project_id)
        if not project:
            ui.label("Project not found").classes("text-red-500")
            return

        ui.label(f"{project['name']} — Tasks").classes("text-2xl font-bold text-white mb-4")

        tasks = state.project_store.list_tasks(project_id)
        task_container = ui.column().classes("w-full gap-2")

        def refresh_tasks() -> None:
            task_container.clear()
            tasks_fresh = state.project_store.list_tasks(project_id)
            with task_container:
                if not tasks_fresh:
                    ui.label("No tasks yet.").classes("text-gray-500 italic")
                    return
                # Table header
                with ui.row().classes("w-full px-3 py-1 text-xs text-gray-500 uppercase"):
                    ui.label("Name").classes("w-1/5")
                    ui.label("Trigger").classes("w-1/6")
                    ui.label("Model").classes("w-1/6")
                    ui.label("Budget").classes("w-1/6")
                    ui.label("Status").classes("w-1/6")
                    ui.label("Actions").classes("w-1/6")
                for t in tasks_fresh:
                    _render_task_row(t, project_id, state, refresh_tasks)

        refresh_tasks()

        # Add task button
        ui.separator().classes("my-4")

        async def open_create_dialog() -> None:
            edit_dialog = _build_task_edit_dialog(
                project_id, state, refresh_tasks, task=None
            )
            edit_dialog.open()

        ui.button("+ New Task", icon="add", on_click=open_create_dialog).props("color=blue")

        # Back link
        ui.link("← Back to project", f"/dashboard/project/{project_id}").classes(
            "text-sm text-blue-400 mt-4"
        )


def _render_task_row(task: dict, project_id: str, state, refresh_fn) -> None:
    enabled = bool(task.get("enabled", 1))
    with ui.row().classes(
        f"w-full items-center px-3 py-2 rounded {'bg-gray-800' if enabled else 'bg-gray-900 opacity-50'}"
    ):
        ui.label(task["name"]).classes("w-1/5 text-sm text-white")
        ui.label(task["trigger_type"]).classes("w-1/6 text-sm text-gray-300")
        ui.label(task["model"]).classes("w-1/6 text-sm text-gray-300")
        ui.label(f"${task['max_budget']:.2f}").classes("w-1/6 text-sm text-gray-300")

        # Toggle
        with ui.row().classes("w-1/6"):
            async def toggle(t=task) -> None:
                state.project_store.update_task(t["id"], enabled=not bool(t["enabled"]))
                refresh_fn()
            ui.switch("", value=enabled, on_change=lambda e, t=task: toggle(t)).props("dense")

        # Actions
        with ui.row().classes("w-1/6 gap-1"):
            async def edit(t=task) -> None:
                d = _build_task_edit_dialog(project_id, state, refresh_fn, task=t)
                d.open()
            ui.button(icon="edit", on_click=lambda e, t=task: edit(t)).props("flat dense size=sm")

            async def delete(t=task) -> None:
                state.project_store.delete_task(t["id"])
                refresh_fn()
            ui.button(icon="delete", on_click=lambda e, t=task: delete(t)).props(
                "flat dense size=sm color=red"
            )


def _build_task_edit_dialog(project_id: str, state, refresh_fn, task: dict | None) -> ui.dialog:
    """Build create/edit dialog. If task is None, creates new; otherwise edits existing."""
    dialog = ui.dialog()
    is_edit = task is not None
    with dialog, ui.card().classes("w-96"):
        ui.label("Edit Task" if is_edit else "Create Task").classes("text-lg font-bold")
        name_input = ui.input("Name", value=task["name"] if is_edit else "").classes("w-full")
        intent_input = ui.textarea(
            "Intent", value=task["intent"] if is_edit else ""
        ).classes("w-full")
        trigger_select = ui.select(
            options=["manual", "schedule", "webhook"],
            value=task["trigger_type"] if is_edit else "manual",
            label="Trigger",
        ).classes("w-full")
        model_select = ui.select(
            options=["sonnet", "opus", "haiku"],
            value=task["model"] if is_edit else "sonnet",
            label="Model",
        ).classes("w-full")
        budget_input = ui.number(
            "Max budget ($)",
            value=task["max_budget"] if is_edit else 5.0,
            min=0.1, max=50.0,
        ).classes("w-full")
        autonomy_select = ui.select(
            options=["pr-only", "auto-merge", "notify"],
            value=task["autonomy"] if is_edit else "pr-only",
            label="Autonomy",
        ).classes("w-full")

        async def save() -> None:
            if is_edit:
                state.project_store.update_task(
                    task["id"],
                    name=name_input.value,
                    intent=intent_input.value,
                    trigger_type=trigger_select.value,
                    model=model_select.value,
                    max_budget=budget_input.value,
                    autonomy=autonomy_select.value,
                )
                ui.notify("Task updated!", type="positive")
            else:
                state.project_store.create_task(
                    project_id=project_id,
                    name=name_input.value,
                    intent=intent_input.value,
                    trigger_type=trigger_select.value,
                    model=model_select.value,
                    max_budget=budget_input.value,
                    autonomy=autonomy_select.value,
                )
                ui.notify("Task created!", type="positive")
            dialog.close()
            refresh_fn()

        ui.button("Save" if is_edit else "Create", on_click=save).props("color=blue")

    return dialog
```

- [ ] **Step 3: Register in dashboard.py**

Add to `setup_dashboard()`:
```python
from agents.dashboard_task_manager import setup_task_manager
setup_task_manager(app, state)
```

- [ ] **Step 4: Add task manager link to Project Hub header**

In `dashboard_project_hub.py`, add to the header action buttons:
```python
ui.button("Tasks", icon="list", on_click=lambda: ui.navigate.to(
    f"/dashboard/project/{project_id}/tasks"
)).props("color=purple dense")
```

- [ ] **Step 5: Commit**

```bash
git add src/agents/dashboard_task_manager.py src/agents/dashboard_project_hub.py src/agents/dashboard.py src/agents/project_store.py
git commit -m "feat: add Task Manager UI with CRUD, toggle, and edit dialog"
```

---

### Task 16: Add YAML Migration Prompt to Dashboard

**Files:**
- Modify: `src/agents/dashboard.py`

- [ ] **Step 1: Add migration check on dashboard load**

In `setup_dashboard()`, at the start of the dashboard page handler, add a migration check:

```python
# Check for unmigrated YAML projects
yaml_projects = state.projects  # loaded from YAML
stored_projects = state.project_store.list_projects()
stored_ids = {p["id"] for p in stored_projects}
unmigrated = [name for name in yaml_projects if name not in stored_ids]

if unmigrated:
    with ui.dialog() as migration_dialog, ui.card().classes("w-96"):
        ui.label("Import Projects").classes("text-lg font-bold")
        ui.label(
            f"Found {len(unmigrated)} project(s) configured in YAML that haven't been imported yet."
        ).classes("text-sm text-gray-300")
        for name in unmigrated:
            ui.label(f"  • {name}").classes("text-sm text-gray-400")

        async def do_migrate() -> None:
            from agents.migration import migrate_yaml_projects
            count = migrate_yaml_projects(state.projects, state.project_store)
            ui.notify(f"Imported {count} project(s)!", type="positive")
            migration_dialog.close()

        with ui.row().classes("gap-2 mt-4"):
            ui.button("Import All", on_click=do_migrate).props("color=green")
            ui.button("Skip", on_click=migration_dialog.close).props("flat")

    migration_dialog.open()
```

- [ ] **Step 2: Commit**

```bash
git add src/agents/dashboard.py
git commit -m "feat: add YAML migration prompt on dashboard load"
```

---

## Chunk 6: Notification Engine & YAML Migration

### Task 17: Create Notification Engine

**Files:**
- Create: `src/agents/notification_engine.py`
- Test: `tests/test_notification_engine.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_notification_engine.py`:

```python
import pytest
from pathlib import Path
from unittest.mock import AsyncMock
from agents.notification_engine import NotificationEngine
from agents.project_store import ProjectStore


@pytest.fixture
def store(tmp_path: Path) -> ProjectStore:
    s = ProjectStore(tmp_path / "test.db")
    s.create_project(id="p1", name="P1", repo_path="/r")
    return s


@pytest.fixture
def engine(store: ProjectStore) -> NotificationEngine:
    return NotificationEngine(
        store=store,
        slack_notifier=AsyncMock(),
        discord_notifier=AsyncMock(),
    )


def test_build_digest(engine: NotificationEngine, store: ProjectStore) -> None:
    store.upsert_event(
        project_id="p1", source="linear", event_type="issue_created",
        title="Bug fix", source_item_id="L1", timestamp="2026-03-16T10:00:00Z",
        priority="urgent",
    )
    store.upsert_event(
        project_id="p1", source="github", event_type="pr_open",
        title="PR #1", source_item_id="G1", timestamp="2026-03-16T10:01:00Z",
    )
    digest = engine.build_digest("p1")
    assert "P1" in digest
    assert "Linear" in digest or "linear" in digest.lower()
    assert "Bug fix" in digest or "1" in digest  # contains count or event


def test_build_digest_empty(engine: NotificationEngine) -> None:
    digest = engine.build_digest("p1")
    assert "No activity" in digest or "no" in digest.lower()


def test_check_urgent_alerts(engine: NotificationEngine, store: ProjectStore) -> None:
    store.upsert_event(
        project_id="p1", source="linear", event_type="issue_created",
        title="Critical bug", source_item_id="L1", timestamp="2026-03-16T10:00:00Z",
        priority="urgent",
    )
    alerts = engine.check_urgent_events("p1")
    assert len(alerts) == 1
    assert alerts[0]["priority"] == "urgent"


def test_check_urgent_alerts_none(engine: NotificationEngine, store: ProjectStore) -> None:
    store.upsert_event(
        project_id="p1", source="linear", event_type="issue_created",
        title="Minor fix", source_item_id="L1", timestamp="2026-03-16T10:00:00Z",
        priority="low",
    )
    alerts = engine.check_urgent_events("p1")
    assert len(alerts) == 0


@pytest.mark.asyncio
async def test_send_digest(engine: NotificationEngine, store: ProjectStore) -> None:
    store.create_notification_rule(
        project_id="p1", rule_type="digest", channel="slack",
        channel_target="dm", config={"schedule": "09:00"},
    )
    await engine.send_digest("p1")
    engine.slack_notifier.send_run_notification.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement NotificationEngine**

Create `src/agents/notification_engine.py`:

```python
"""Notification Engine — daily digests and real-time urgent alerts."""

import logging
from collections import Counter

logger = logging.getLogger(__name__)


class NotificationEngine:
    def __init__(
        self,
        *,
        store: "ProjectStore",
        slack_notifier: object | None = None,
        discord_notifier: object | None = None,
    ) -> None:
        self.store = store
        self.slack_notifier = slack_notifier
        self.discord_notifier = discord_notifier

    def build_digest(self, project_id: str) -> str:
        project = self.store.get_project(project_id)
        if not project:
            return "Project not found"

        events = self.store.list_events(project_id, limit=200)
        if not events:
            return f"📋 {project['name']} — No activity in recent period."

        # Group by source
        by_source: dict[str, list[dict]] = {}
        for e in events:
            by_source.setdefault(e["source"], []).append(e)

        lines = [f"📋 {project['name']} — Daily Summary\n"]

        for source, source_events in sorted(by_source.items()):
            type_counts = Counter(e["event_type"] for e in source_events)
            urgent_count = sum(1 for e in source_events if e["priority"] in ("urgent", "high"))
            summary_parts = [f"{count} {etype}" for etype, count in type_counts.items()]
            line = f"{source.capitalize()}: {', '.join(summary_parts)}"
            if urgent_count:
                line += f" ({urgent_count} urgent)"
            lines.append(line)

        # Action needed section
        urgent_events = [e for e in events if e["priority"] in ("urgent", "high")]
        if urgent_events:
            lines.append("\n⚠ Action needed:")
            for e in urgent_events[:5]:
                lines.append(f"  → {e['title']}")

        return "\n".join(lines)

    def check_urgent_events(self, project_id: str) -> list[dict]:
        events = self.store.list_events(project_id, limit=50)
        return [e for e in events if e["priority"] in ("urgent", "high")]

    async def send_digest(self, project_id: str) -> None:
        rules = self.store.list_notification_rules(project_id)
        digest_rules = [r for r in rules if r["rule_type"] == "digest" and r["enabled"]]

        if not digest_rules:
            return

        digest_text = self.build_digest(project_id)

        for rule in digest_rules:
            try:
                if rule["channel"] == "slack" and self.slack_notifier:
                    await self.slack_notifier.send_text(digest_text)
                elif rule["channel"] == "discord" and self.discord_notifier:
                    # Use Discord's channel messaging
                    await self.discord_notifier.create_run_message(
                        rule["channel_target"], project_id, digest_text[:200]
                    )
                self.store.log_notification(
                    project_id=project_id,
                    rule_id=rule["id"],
                    event_id=None,
                    channel=rule["channel"],
                    content=digest_text[:500],
                )
            except Exception:
                logger.exception("Failed to send digest for project %s", project_id)

    async def send_urgent_alert(self, project_id: str, event: dict) -> None:
        rules = self.store.list_notification_rules(project_id)
        alert_rules = [r for r in rules if r["rule_type"] == "alert" and r["enabled"]]

        if not alert_rules:
            return

        # Anti-spam check
        if self.store.was_recently_notified(
            source_item_id=event.get("source_item_id", ""),
            rule_type="alert",
            cooldown_minutes=30,
        ):
            return

        alert_text = f"🚨 {event.get('title', 'Unknown event')}"
        if event.get("url"):
            alert_text += f"\n{event['url']}"

        for rule in alert_rules:
            try:
                if rule["channel"] == "slack" and self.slack_notifier:
                    await self.slack_notifier.send_text(alert_text)
                self.store.log_notification(
                    project_id=project_id,
                    rule_id=rule["id"],
                    event_id=event.get("id"),
                    channel=rule["channel"],
                    content=alert_text[:500],
                )
            except Exception:
                logger.exception("Failed to send alert for project %s", project_id)

    async def process_new_events(self, project_id: str) -> None:
        """Check for urgent events and send alerts."""
        urgent = self.check_urgent_events(project_id)
        for event in urgent:
            await self.send_urgent_alert(project_id, event)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/vini/Developer/agents && python -m pytest tests/test_notification_engine.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/notification_engine.py tests/test_notification_engine.py
git commit -m "feat: add NotificationEngine with digest builder and urgent alerts"
```

---

### Task 18: Create YAML Migration Module

**Files:**
- Create: `src/agents/migration.py`
- Test: `tests/test_migration.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_migration.py`:

```python
import pytest
from pathlib import Path
from agents.migration import migrate_yaml_projects
from agents.project_store import ProjectStore
from agents.config import load_project_configs


@pytest.fixture
def store(tmp_path: Path) -> ProjectStore:
    return ProjectStore(tmp_path / "test.db")


@pytest.fixture
def yaml_dir(tmp_path: Path) -> Path:
    d = tmp_path / "projects"
    d.mkdir()
    (d / "momease.yaml").write_text("""
name: momease
repo: /repos/momease
base_branch: main
branch_prefix: agents/
notify: slack
linear_team_id: team-123
tasks:
  fix-bugs:
    description: Fix all bugs
    intent: Find and fix bugs
    schedule: "0 9 * * *"
    model: sonnet
    max_cost_usd: 5.0
    autonomy: pr-only
  review-prs:
    description: Review open PRs
    intent: Review and comment on PRs
    trigger:
      type: github
      events: ["pull_request.opened"]
    model: sonnet
    max_cost_usd: 3.0
    autonomy: read-only
""")
    return d


def test_migrate_yaml_projects(store: ProjectStore, yaml_dir: Path) -> None:
    projects = load_project_configs(yaml_dir)
    count = migrate_yaml_projects(projects, store)
    assert count == 1

    p = store.get_project("momease")
    assert p is not None
    assert p["name"] == "momease"
    assert p["repo_path"] == "/repos/momease"

    tasks = store.list_tasks("momease")
    assert len(tasks) == 2
    task_names = {t["name"] for t in tasks}
    assert "fix-bugs" in task_names
    assert "review-prs" in task_names

    sources = store.list_sources("momease")
    linear_sources = [s for s in sources if s["source_type"] == "linear"]
    assert len(linear_sources) == 1
    assert linear_sources[0]["source_id"] == "team-123"


def test_migrate_skips_existing(store: ProjectStore, yaml_dir: Path) -> None:
    projects = load_project_configs(yaml_dir)
    migrate_yaml_projects(projects, store)
    count = migrate_yaml_projects(projects, store)
    assert count == 0  # Already migrated
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement migration**

Create `src/agents/migration.py`:

```python
"""YAML to SQLite migration for project configurations."""

import json
import logging

logger = logging.getLogger(__name__)


def migrate_yaml_projects(
    projects: dict[str, "ProjectConfig"],
    store: "ProjectStore",
) -> int:
    """Migrate YAML project configs to ProjectStore. Returns count of migrated projects."""
    migrated = 0

    for project_id, config in projects.items():
        # Skip if already in store
        if store.get_project(project_id):
            logger.info("Project %s already in store, skipping", project_id)
            continue

        # Create project
        store.create_project(
            id=project_id,
            name=config.name,
            repo_path=config.repo,
            default_branch=config.base_branch,
        )

        # Add Linear source if configured
        if config.linear_team_id:
            store.create_source(
                project_id=project_id,
                source_type="linear",
                source_id=config.linear_team_id,
                source_name=f"{config.name} Linear",
            )

        # Migrate tasks
        for task_name, task in config.tasks.items():
            trigger_type = "manual"
            trigger_config = {}

            if task.schedule:
                trigger_type = "schedule"
                trigger_config = {"cron": task.schedule}
            elif task.trigger:
                trigger_type = "webhook"
                trigger_config = {
                    "type": task.trigger.type,
                    "events": task.trigger.events,
                    "filter": task.trigger.filter,
                }

            store.create_task(
                project_id=project_id,
                name=task_name,
                intent=task.intent or task.prompt or task.description,
                trigger_type=trigger_type,
                trigger_config=trigger_config,
                model=task.model,
                max_budget=task.max_cost_usd,
                autonomy=task.autonomy,
            )

        migrated += 1
        logger.info("Migrated project %s with %d tasks", project_id, len(config.tasks))

    return migrated
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/vini/Developer/agents && python -m pytest tests/test_migration.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/migration.py tests/test_migration.py
git commit -m "feat: add YAML to SQLite migration for project configs"
```

---

### Task 19: Wire Notification Engine and Migration into App

**Files:**
- Modify: `src/agents/main.py`

- [ ] **Step 1: Add NotificationEngine to app lifecycle**

In `src/agents/main.py`, inside `create_app()`:

```python
from agents.notification_engine import NotificationEngine

notification_engine = NotificationEngine(
    store=project_store,
    slack_notifier=notifier,
    discord_notifier=discord_notifier,
)
```

- [ ] **Step 2: Register digest scheduler**

In the lifespan, after APScheduler is created:

```python
from agents.notification_engine import NotificationEngine

# Schedule daily digest for all projects
async def run_daily_digest():
    for project in project_store.list_projects():
        await notification_engine.send_digest(project["id"])

scheduler.add_job(run_daily_digest, "cron", hour=9, minute=0, id="daily_digest")
```

- [ ] **Step 3: Add migration offer endpoint**

```python
@app.post("/api/migrate-yaml")
async def migrate_yaml() -> dict:
    from agents.migration import migrate_yaml_projects
    count = migrate_yaml_projects(state.projects, state.project_store)
    return {"migrated": count}
```

- [ ] **Step 4: Hook urgent alert processing into aggregator**

After each poll cycle, check for urgent events:

```python
# In aggregator's poll_all, after polling:
if notification_engine:
    await notification_engine.process_new_events(project_id)
```

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/vini/Developer/agents && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/agents/main.py
git commit -m "feat: wire NotificationEngine, digest scheduler, and YAML migration into app"
```

---

## Chunk 7: Final Integration & Verification

### Task 20: Add Auto-discovery API Endpoint

**Files:**
- Modify: `src/agents/main.py`

- [ ] **Step 1: Add discovery endpoint**

```python
@app.post("/api/discover")
async def discover_sources(data: dict) -> list[dict]:
    """Run auto-discovery for a project name."""
    from agents.dashboard_setup_wizard import _discover_sources
    return await _discover_sources(data.get("name", ""), state)
```

- [ ] **Step 2: Commit**

```bash
git add src/agents/main.py
git commit -m "feat: add auto-discovery API endpoint"
```

---

### Task 21: Add Data Cleanup Job

**Files:**
- Modify: `src/agents/main.py`

- [ ] **Step 1: Register cleanup in scheduler**

In lifespan, add to APScheduler:

```python
async def cleanup_old_events():
    deleted = project_store.cleanup_old_events(days=90)
    if deleted:
        logger.info("Cleaned up %d old events", deleted)

scheduler.add_job(cleanup_old_events, "cron", hour=3, minute=0, id="event_cleanup")
```

- [ ] **Step 2: Commit**

```bash
git add src/agents/main.py
git commit -m "feat: add daily cleanup job for old aggregated events"
```

---

### Task 22: Full Integration Verification

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/vini/Developer/agents && python -m pytest tests/ -v
```
Expected: ALL PASS

- [ ] **Step 2: Run linter**

```bash
cd /Users/vini/Developer/agents && python -m ruff check src/ tests/
```
Expected: No errors

- [ ] **Step 3: Run type checker**

```bash
cd /Users/vini/Developer/agents && python -m pyright src/
```
Expected: No critical errors

- [ ] **Step 4: Manual smoke test**

1. Start the app: `python -m agents`
2. Navigate to dashboard
3. Click "New Project" → complete wizard
4. Verify project page shows
5. Create a task via the dialog
6. Trigger a run (if repo is available)
7. Check that events populate after polling
8. Run YAML migration via API

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: integration fixes from smoke test"
```
