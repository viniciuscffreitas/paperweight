import os
import time
from pathlib import Path
from agents.cleanup import (
    find_stale_run_files,
    find_orphan_worktrees,
    cleanup_run_artifacts,
    purge_old_run_events,
)


def test_find_stale_run_files(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    old_file = runs_dir / "old-run.json"
    old_file.write_text("{}")
    old_time = time.time() - (40 * 86400)
    os.utime(old_file, (old_time, old_time))
    new_file = runs_dir / "new-run.json"
    new_file.write_text("{}")
    stale = find_stale_run_files(runs_dir, max_age_days=30)
    assert len(stale) == 1
    assert stale[0].name == "old-run.json"


def test_find_orphan_worktrees(tmp_path):
    wt_base = tmp_path / "worktrees"
    wt_base.mkdir()
    (wt_base / "session-abc123").mkdir()
    (wt_base / "session-def456").mkdir()
    active_ids = {"abc123"}
    orphans = find_orphan_worktrees(wt_base, active_session_ids=active_ids)
    assert len(orphans) == 1
    assert orphans[0].name == "session-def456"


def test_cleanup_run_artifacts_deletes_files(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    old_file = runs_dir / "stale.json"
    old_file.write_text("{}")
    old_time = time.time() - (40 * 86400)
    os.utime(old_file, (old_time, old_time))
    deleted = cleanup_run_artifacts(runs_dir, max_age_days=30)
    assert deleted == 1
    assert not old_file.exists()


def test_find_stale_run_files_empty_dir(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    assert find_stale_run_files(runs_dir) == []


def test_find_stale_run_files_nonexistent_dir(tmp_path):
    assert find_stale_run_files(tmp_path / "nope") == []


def test_find_orphan_worktrees_ignores_non_session_dirs(tmp_path):
    wt_base = tmp_path / "worktrees"
    wt_base.mkdir()
    (wt_base / "some-other-dir").mkdir()
    (wt_base / "session-abc123").mkdir()
    orphans = find_orphan_worktrees(wt_base, active_session_ids={"abc123"})
    assert len(orphans) == 0


def test_purge_old_run_events(tmp_path):
    from agents.history import HistoryDB
    db = HistoryDB(tmp_path / "test.db")
    old_ts = time.time() - (40 * 86400)
    new_ts = time.time()
    db.insert_event("run-1", {"type": "assistant", "content": "old", "tool_name": "", "timestamp": old_ts})
    db.insert_event("run-1", {"type": "assistant", "content": "new", "tool_name": "", "timestamp": new_ts})
    deleted = purge_old_run_events(db, days=30)
    assert deleted == 1
    remaining = db.list_events("run-1")
    assert len(remaining) == 1
    assert remaining[0]["content"] == "new"
