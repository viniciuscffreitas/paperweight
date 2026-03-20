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
    title: str = ""
    created_at: datetime
    updated_at: datetime


_ALLOWED_UPDATE_FIELDS = {"claude_session_id", "status", "model", "max_cost_usd", "title"}


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
            # Migrations
            for migration in [
                "ALTER TABLE agent_sessions ADD COLUMN running INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE agent_sessions ADD COLUMN title TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE agent_sessions ADD COLUMN task_id TEXT",
            ]:
                try:
                    conn.execute(migration)
                except sqlite3.OperationalError:
                    pass  # Column already exists
            # Clear stale locks from previous process
            conn.execute("UPDATE agent_sessions SET running = 0 WHERE running = 1")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _row_to_session(self, row: sqlite3.Row) -> AgentSession:
        title = ""
        try:
            title = row["title"] or ""
        except (IndexError, KeyError):
            pass
        return AgentSession(
            id=row["id"],
            project=row["project"],
            worktree_path=row["worktree_path"],
            claude_session_id=row["claude_session_id"],
            model=row["model"],
            max_cost_usd=row["max_cost_usd"],
            status=row["status"],
            title=title,
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

    def list_sessions_with_stats(self, project: str | None = None) -> list[dict]:
        """List sessions with aggregated run stats for dashboard display."""
        where = "WHERE s.project = ?" if project else ""
        params: list[object] = [project] if project else []
        # Join with runs to get stats — use the SAME db since runs are in agents.db
        with self._conn() as conn:
            rows = conn.execute(
                f"""SELECT s.id, s.project, s.status, s.title, s.model,
                       s.created_at, s.updated_at,
                       COUNT(r.id) as run_count,
                       COALESCE(SUM(r.cost_usd), 0) as total_cost,
                       MIN(r.started_at) as first_run_at,
                       MAX(r.finished_at) as last_run_at,
                       (SELECT task FROM runs WHERE session_id = s.id ORDER BY started_at ASC LIMIT 1) as first_prompt
                FROM agent_sessions s
                LEFT JOIN runs r ON r.session_id = s.id
                {where}
                GROUP BY s.id
                ORDER BY s.updated_at DESC""",
                params,
            ).fetchall()
        result = []
        for row in rows:
            title = row["title"] or row["first_prompt"] or "Chat sem título"
            result.append({
                "id": row["id"],
                "project": row["project"],
                "status": row["status"],
                "title": title,
                "model": row["model"],
                "run_count": row["run_count"],
                "total_cost": row["total_cost"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            })
        return result

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
