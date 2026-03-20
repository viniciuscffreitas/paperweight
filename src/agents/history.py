import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from agents.models import RunRecord, RunStatus


class HistoryDB:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    project TEXT NOT NULL,
                    task TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    started_at TIMESTAMP NOT NULL,
                    finished_at TIMESTAMP,
                    status TEXT NOT NULL,
                    model TEXT NOT NULL,
                    num_turns INTEGER,
                    cost_usd REAL,
                    pr_url TEXT,
                    error_message TEXT,
                    output_file TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS run_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    tool_name TEXT NOT NULL DEFAULT '',
                    timestamp REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_run_events_run_id ON run_events (run_id)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS file_claims (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    claim_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    claimed_at REAL NOT NULL,
                    last_activity REAL NOT NULL,
                    released_at REAL,
                    UNIQUE(run_id, file_path)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_claims_file"
                " ON file_claims (file_path, status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_claims_run"
                " ON file_claims (run_id, status)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mediations (
                    id TEXT PRIMARY KEY,
                    file_paths TEXT NOT NULL,
                    requester_run_ids TEXT NOT NULL,
                    mediator_run_id TEXT,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    completed_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS coordination_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp REAL NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_coordlog_run"
                " ON coordination_log (run_id, timestamp)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS run_variables (
                    run_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    PRIMARY KEY (run_id, key)
                )
            """)
            # Migration: add session_id to runs table
            try:
                conn.execute("ALTER TABLE runs ADD COLUMN session_id TEXT")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise
            try:
                conn.execute("ALTER TABLE runs ADD COLUMN task_id TEXT")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def insert_run(self, run: RunRecord) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO runs (id, project, task, trigger_type, started_at, finished_at,
                   status, model, num_turns, cost_usd, pr_url, error_message, output_file,
                   session_id)
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

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def update_run(
        self,
        run_id: str,
        status: RunStatus | None = None,
        finished_at: datetime | None = None,
        cost_usd: float | None = None,
        num_turns: int | None = None,
        pr_url: str | None = None,
        error_message: str | None = None,
        output_file: str | None = None,
    ) -> None:
        updates: list[str] = []
        values: list[object] = []
        for field, value in [
            ("status", status),
            ("finished_at", finished_at.isoformat() if finished_at else None),
            ("cost_usd", cost_usd),
            ("num_turns", num_turns),
            ("pr_url", pr_url),
            ("error_message", error_message),
            ("output_file", output_file),
        ]:
            if value is not None:
                updates.append(f"{field} = ?")
                values.append(value)
        if not updates:
            return
        values.append(run_id)
        with self._conn() as conn:
            conn.execute(f"UPDATE runs SET {', '.join(updates)} WHERE id = ?", values)

    def list_runs_today(self) -> list[RunRecord]:
        today = datetime.now(UTC).date().isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE started_at >= ? ORDER BY started_at DESC",
                (today,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def total_cost_today(self) -> float:
        today = datetime.now(UTC).date().isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) as total FROM runs WHERE started_at >= ?",
                (today,),
            ).fetchone()
        return float(row["total"])

    def mark_running_as_cancelled(self) -> None:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE runs SET status = ?, finished_at = ? WHERE status = ?",
                (RunStatus.CANCELLED, now, RunStatus.RUNNING),
            )

    def insert_event(self, run_id: str, event_data: dict) -> None:
        with self._conn() as conn:
            # Atomic cap check + insert in a single statement to avoid TOCTOU race
            conn.execute(
                """INSERT INTO run_events (run_id, type, content, tool_name, timestamp)
                   SELECT ?, ?, ?, ?, ?
                   WHERE (SELECT COUNT(*) FROM run_events WHERE run_id = ?) < 500""",
                (
                    run_id,
                    event_data.get("type", "unknown"),
                    event_data.get("content", ""),
                    event_data.get("tool_name", ""),
                    event_data.get("timestamp", 0.0),
                    run_id,
                ),
            )

    def list_events(self, run_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT run_id, type, content, tool_name, timestamp"
                " FROM run_events WHERE run_id = ? ORDER BY timestamp ASC, id ASC",
                (run_id,),
            ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "type": row["type"],
                "content": row["content"],
                "tool_name": row["tool_name"],
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]

    def list_runs_by_session(self, session_id: str) -> list[RunRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE session_id = ? ORDER BY started_at ASC",
                (session_id,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def find_run_by_issue_id(self, issue_id: str) -> RunRecord | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE task = 'issue-resolver'"
                " AND id LIKE ? ORDER BY started_at DESC LIMIT 1",
                (f"%{issue_id}%",),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

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

    def find_run_by_pr_url(self, pr_url: str) -> RunRecord | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE pr_url = ? ORDER BY started_at DESC LIMIT 1",
                (pr_url,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def _row_to_record(self, row: sqlite3.Row) -> RunRecord:
        # session_id column guaranteed by _init_db migration
        session_id = row["session_id"]
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
