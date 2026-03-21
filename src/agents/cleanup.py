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


def find_orphan_worktrees(worktree_base: Path, active_session_ids: set[str]) -> list[Path]:
    if not worktree_base.exists():
        return []
    orphans = []
    for d in worktree_base.iterdir():
        if not d.is_dir():
            continue
        name = d.name
        if name.startswith("session-"):
            sid = name[len("session-") :]
            if sid not in active_session_ids:
                orphans.append(d)
    return orphans


def cleanup_orphan_worktrees(worktree_base: Path, active_session_ids: set[str]) -> int:
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
    """Purge old run events. Delegates to HistoryDB.purge_old_events."""
    purge_method = getattr(history_db, "purge_old_events", None)
    if purge_method is None:
        return 0
    deleted = purge_method(days)
    if deleted:
        logger.info("Purged %d old run event(s)", deleted)
    return deleted
