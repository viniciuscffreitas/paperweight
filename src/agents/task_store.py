"""Task (work item) persistence — SQLite CRUD with atomic claim."""

import contextlib
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
                "CREATE INDEX IF NOT EXISTS idx_work_items_project ON work_items (project, status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_work_items_source ON work_items (source, source_id)"
            )
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
            for migration in [
                "ALTER TABLE work_items ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE work_items ADD COLUMN next_retry_at TEXT",
                "ALTER TABLE work_items ADD COLUMN spec_path TEXT",
            ]:
                with contextlib.suppress(sqlite3.OperationalError):
                    conn.execute(migration)

    def _row_to_item(self, row: sqlite3.Row) -> WorkItem:
        retry_count = 0
        next_retry_at = None
        with contextlib.suppress(IndexError, KeyError):
            retry_count = row["retry_count"] or 0
        with contextlib.suppress(IndexError, KeyError):
            next_retry_at = row["next_retry_at"]
        spec_path = None
        with contextlib.suppress(IndexError, KeyError):
            spec_path = row["spec_path"]
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
            retry_count=retry_count,
            next_retry_at=next_retry_at,
            spec_path=spec_path,
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
                    item.id,
                    item.project,
                    item.template,
                    item.title,
                    item.description,
                    item.source,
                    item.source_id,
                    item.source_url,
                    item.status,
                    item.session_id,
                    item.pr_url,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return item

    def get(self, item_id: str) -> WorkItem | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM work_items WHERE id = ?", (item_id,)).fetchone()
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
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE work_items SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                (TaskStatus.RUNNING, now, item_id, TaskStatus.PENDING),
            )
            return cursor.rowcount == 1

    def list_retryable(self, now_iso: str, limit: int = 5) -> list[WorkItem]:
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
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE work_items SET status = ?, updated_at = ? WHERE id = ?"
                " AND status IN (?, ?)",
                (TaskStatus.RUNNING, now, item_id, TaskStatus.PENDING, TaskStatus.RETRYING),
            )
            return cursor.rowcount == 1

    def update_status(self, item_id: str, status: TaskStatus, pr_url: str | None = None) -> None:
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

    def update_spec_path(self, item_id: str, spec_path: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE work_items SET spec_path = ?, updated_at = ? WHERE id = ?",
                (spec_path, now, item_id),
            )

    def update_title(self, item_id: str, title: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE work_items SET title = ?, updated_at = ? WHERE id = ?",
                (title, now, item_id),
            )

    def exists_by_source(self, source: str, source_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM work_items WHERE source = ? AND source_id = ? LIMIT 1",
                (source, source_id),
            ).fetchone()
        return row is not None

    def add_context(
        self,
        task_id: str,
        entry_type: str,
        content: str,
        source_run_id: str | None = None,
    ) -> None:
        """Add a context entry. Auto-prunes if over 50 entries."""
        import time

        now = time.time()
        # Truncate content to 4KB
        if len(content) > 4096:
            content = content[:4093] + "..."
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO task_context (task_id, type, source_run_id, content, timestamp)
                   VALUES (?, ?, ?, ?, ?)""",
                (task_id, entry_type, source_run_id, content, now),
            )
            # Prune oldest non-error entries if over 50
            count = conn.execute(
                "SELECT COUNT(*) as c FROM task_context WHERE task_id = ?", (task_id,)
            ).fetchone()["c"]
            if count > 50:
                conn.execute(
                    """DELETE FROM task_context WHERE id IN (
                        SELECT id FROM task_context
                        WHERE task_id = ? AND type NOT IN ('run_error', 'ci_failure')
                        ORDER BY timestamp ASC LIMIT ?
                    )""",
                    (task_id, count - 50),
                )

    def get_context(self, task_id: str, limit: int = 50) -> list[dict]:
        """Get context entries for a task, newest first."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT type, content, source_run_id, timestamp
                   FROM task_context WHERE task_id = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (task_id, limit),
            ).fetchall()
        return [
            {
                "type": row["type"],
                "content": row["content"],
                "source_run_id": row["source_run_id"],
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]
