"""Agent session management — SQLite persistence + DB-level concurrency guard."""
import logging
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class AgentSession(BaseModel):
    id: str
    project: str
    worktree_path: str
    claude_session_id: str | None = None
    model: str = "claude-sonnet-4-6"
    max_cost_usd: float = 2.00
    status: str = "active"  # active | closed
    created_at: datetime
    updated_at: datetime


_ALLOWED_UPDATE_FIELDS = {"claude_session_id", "status", "model", "max_cost_usd"}


class SessionManager:
    def __init__(self, db_path: Path, worktree_base: str = "/tmp/agents") -> None:
        self.db_path = db_path
        self.worktree_base = worktree_base
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    id TEXT PRIMARY KEY,
                    project TEXT NOT NULL,
                    worktree_path TEXT NOT NULL,
                    claude_session_id TEXT,
                    model TEXT NOT NULL,
                    max_cost_usd REAL NOT NULL,
                    status TEXT NOT NULL,
                    running INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            # Migration: add running column if missing
            try:
                conn.execute("ALTER TABLE agent_sessions ADD COLUMN running INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # Column already exists
            # Clear stale locks from previous process
            conn.execute("UPDATE agent_sessions SET running = 0 WHERE running = 1")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

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

    def create_session(
        self,
        project: str,
        model: str = "claude-sonnet-4-6",
        max_cost_usd: float = 2.00,
    ) -> AgentSession:
        session_id = uuid.uuid4().hex[:12]
        now = datetime.now(UTC)
        worktree_path = str(Path(self.worktree_base) / f"session-{session_id}")
        session = AgentSession(
            id=session_id,
            project=project,
            worktree_path=worktree_path,
            model=model,
            max_cost_usd=max_cost_usd,
            status="active",
            created_at=now,
            updated_at=now,
        )
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO agent_sessions
                   (id, project, worktree_path, claude_session_id, model,
                    max_cost_usd, status, running, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
                (
                    session.id,
                    session.project,
                    session.worktree_path,
                    session.claude_session_id,
                    session.model,
                    session.max_cost_usd,
                    session.status,
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
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
        unknown = set(kwargs) - _ALLOWED_UPDATE_FIELDS
        if unknown:
            logger.warning(
                "update_session called with unknown fields %s for session %s — ignored",
                unknown, session_id,
            )
        fields = {k: v for k, v in kwargs.items() if k in _ALLOWED_UPDATE_FIELDS}
        if not fields:
            return
        now = datetime.now(UTC).isoformat()
        fields["updated_at"] = now
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values())
        values.append(session_id)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE agent_sessions SET {set_clause} WHERE id = ?",
                values,
            )

    def close_session(self, session_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE agent_sessions SET status = 'closed', running = 0, updated_at = ? WHERE id = ?",
                (datetime.now(UTC).isoformat(), session_id),
            )

    def get_active_session(self, project: str) -> AgentSession | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM agent_sessions"
                " WHERE project = ? AND status = 'active'"
                " ORDER BY created_at DESC LIMIT 1",
                (project,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_session(row)

    def cleanup_stale_sessions(self, timeout_minutes: int = 30) -> int:
        cutoff = (datetime.now(UTC) - timedelta(minutes=timeout_minutes)).isoformat()
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE agent_sessions SET status = 'closed', running = 0, updated_at = ?"
                " WHERE status = 'active' AND updated_at < ?",
                (now, cutoff),
            )
        return cursor.rowcount

    def list_sessions(self, project: str) -> list[AgentSession]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_sessions WHERE project = ? ORDER BY created_at DESC",
                (project,),
            ).fetchall()
        return [self._row_to_session(row) for row in rows]

    def try_acquire_run(self, session_id: str) -> bool:
        """Atomically acquire the run lock via SQLite UPDATE. Safe across restarts."""
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE agent_sessions SET running = 1 WHERE id = ? AND running = 0",
                (session_id,),
            )
            return cursor.rowcount == 1

    def release_run(self, session_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE agent_sessions SET running = 0 WHERE id = ?",
                (session_id,),
            )
