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
            row = conn.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
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
