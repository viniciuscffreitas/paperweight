import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path


class ProjectStore:
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
                CREATE INDEX IF NOT EXISTS idx_aggregated_events_project_timestamp
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
                    rule_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    sent_at TIMESTAMP NOT NULL,
                    channel TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT ''
                )
            """)

    # --- Projects ---

    def create_project(
        self,
        id: str,
        name: str,
        repo_path: str,
        default_branch: str = "main",
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO projects
                   (id, name, repo_path, default_branch, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (id, name, repo_path, default_branch, now, now),
            )

    def get_project(self, project_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def list_projects(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def update_project(self, project_id: str, **kwargs: object) -> None:
        allowed = {"name", "repo_path", "default_branch"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        now = datetime.now(UTC).isoformat()
        updates["updated_at"] = now
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = [*list(updates.values()), project_id]
        with self._conn() as conn:
            conn.execute(
                f"UPDATE projects SET {set_clause} WHERE id = ?", values
            )

    def delete_project(self, project_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    # --- Sources ---

    def create_source(
        self,
        project_id: str,
        source_type: str,
        source_id: str,
        source_name: str,
        config: dict | None = None,
        enabled: bool = True,
    ) -> str:
        sid = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO project_sources
                   (id, project_id, source_type, source_id, source_name,
                    config, enabled, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    sid,
                    project_id,
                    source_type,
                    source_id,
                    source_name,
                    json.dumps(config or {}),
                    1 if enabled else 0,
                    now,
                    now,
                ),
            )
        return sid

    def list_sources(self, project_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM project_sources WHERE project_id = ? ORDER BY created_at ASC",
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_source(self, source_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM project_sources WHERE id = ?", (source_id,)
            ).fetchone()
        return dict(row) if row else None

    def delete_source(self, source_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM project_sources WHERE id = ?", (source_id,))

    # --- Tasks ---

    def create_task(
        self,
        project_id: str,
        name: str,
        intent: str,
        trigger_type: str,
        trigger_config: dict | None = None,
        model: str = "sonnet",
        max_budget: float = 5.0,
        autonomy: str = "pr-only",
        enabled: bool = True,
    ) -> str:
        tid = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO tasks
                   (id, project_id, name, intent, trigger_type, trigger_config,
                    model, max_budget, autonomy, enabled, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    tid,
                    project_id,
                    name,
                    intent,
                    trigger_type,
                    json.dumps(trigger_config or {}),
                    model,
                    max_budget,
                    autonomy,
                    1 if enabled else 0,
                    now,
                    now,
                ),
            )
        return tid

    def get_task(self, task_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def list_tasks(self, project_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE project_id = ? ORDER BY created_at ASC",
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_task(self, task_id: str, **kwargs: object) -> None:
        allowed = {
            "name", "intent", "trigger_type", "trigger_config",
            "model", "max_budget", "autonomy", "enabled",
        }
        updates: dict[str, object] = {}
        for k, v in kwargs.items():
            if k not in allowed:
                continue
            if k == "trigger_config" and isinstance(v, dict):
                updates[k] = json.dumps(v)
            elif k == "enabled" and isinstance(v, bool):
                updates[k] = 1 if v else 0
            else:
                updates[k] = v
        if not updates:
            return
        now = datetime.now(UTC).isoformat()
        updates["updated_at"] = now
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = [*list(updates.values()), task_id]
        with self._conn() as conn:
            conn.execute(
                f"UPDATE tasks SET {set_clause} WHERE id = ?", values
            )

    def delete_task(self, task_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    # --- Events ---

    def upsert_event(
        self,
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
                   (id, project_id, source, event_type, title, body, author, url,
                    priority, timestamp, source_item_id, raw_data)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source, source_item_id) DO UPDATE SET
                       event_type = excluded.event_type,
                       title = excluded.title,
                       body = excluded.body,
                       author = excluded.author,
                       url = excluded.url,
                       priority = excluded.priority,
                       timestamp = excluded.timestamp,
                       raw_data = excluded.raw_data""",
                (
                    eid,
                    project_id,
                    source,
                    event_type,
                    title,
                    body,
                    author,
                    url,
                    priority,
                    timestamp,
                    source_item_id,
                    json.dumps(raw_data or {}),
                ),
            )
        return eid

    def list_events(
        self,
        project_id: str,
        source: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        query = "SELECT * FROM aggregated_events WHERE project_id = ?"
        params: list[object] = [project_id]
        if source is not None:
            query += " AND source = ?"
            params.append(source)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def cleanup_old_events(self, days: int = 90) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM aggregated_events WHERE timestamp < ?", (cutoff,)
            )
        return cursor.rowcount

    # --- Notification Rules ---

    def create_notification_rule(
        self,
        project_id: str,
        rule_type: str,
        channel: str,
        channel_target: str,
        config: dict | None = None,
        enabled: bool = True,
    ) -> str:
        rid = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO notification_rules
                   (id, project_id, rule_type, channel, channel_target, config, enabled)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    rid,
                    project_id,
                    rule_type,
                    channel,
                    channel_target,
                    json.dumps(config or {}),
                    1 if enabled else 0,
                ),
            )
        return rid

    def list_notification_rules(self, project_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM notification_rules WHERE project_id = ?",
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_notification_rule(self, rule_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM notification_rules WHERE id = ?", (rule_id,))

    # --- Notification Log ---

    def log_notification(
        self,
        project_id: str,
        rule_id: str,
        event_id: str,
        channel: str,
        content: str = "",
    ) -> str:
        lid = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO notification_log
                   (id, project_id, rule_id, event_id, sent_at, channel, content)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (lid, project_id, rule_id, event_id, now, channel, content),
            )
        return lid

    def was_recently_notified(
        self,
        project_id: str,
        rule_id: str,
        event_id: str,
        cooldown_minutes: int = 60,
    ) -> bool:
        cutoff = (datetime.now(UTC) - timedelta(minutes=cooldown_minutes)).isoformat()
        with self._conn() as conn:
            row = conn.execute(
                """SELECT COUNT(*) as cnt FROM notification_log
                   WHERE project_id = ? AND rule_id = ? AND event_id = ? AND sent_at >= ?""",
                (project_id, rule_id, event_id, cutoff),
            ).fetchone()
        return row["cnt"] > 0
