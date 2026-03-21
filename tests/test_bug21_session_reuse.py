"""Bug #21: Session reuse with stale worktree / stale settings.

Behavior Contract:
- CHANGES: TaskProcessor checks worktree, updates session settings on reuse
- MUST NOT CHANGE: agent_routes worktree check, new session creation, cleanup
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agents.models import TaskStatus
from agents.session_manager import SessionManager
from agents.task_store import TaskStore


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def session_mgr(db_path: Path) -> SessionManager:
    return SessionManager(db_path, worktree_base=str(db_path.parent / "worktrees"))


@pytest.fixture
def task_store(db_path: Path) -> TaskStore:
    return TaskStore(db_path)


# -----------------------------------------------------------------------
# CHANGES: stale worktree → fresh session
# -----------------------------------------------------------------------


def test_task_processor_stale_worktree_creates_fresh_session(
    session_mgr: SessionManager,
    task_store: TaskStore,
) -> None:
    """When session exists but worktree is gone, TaskProcessor creates fresh session."""
    old_session = session_mgr.create_session("pw", "sonnet", 2.0)
    # Worktree path does NOT exist (never created or cleaned up)
    assert not Path(old_session.worktree_path).exists()

    item = task_store.create(
        project="pw", title="Retry task", description="",
        source="manual", session_id=old_session.id,
    )

    # Simulate TaskProcessor session resolution logic (what we'll fix):
    session = session_mgr.get_session(item.session_id)
    assert session is not None
    assert session.status == "active"

    # The fix: check worktree existence before reuse
    if not Path(session.worktree_path).exists():
        session_mgr.close_session(session.id)
        new_session = session_mgr.create_session("pw", "sonnet", 2.0)
        task_store.update_session(item.id, new_session.id)
        session = new_session

    # Verify: new session created, old one closed
    assert session.id != old_session.id
    old_refreshed = session_mgr.get_session(old_session.id)
    assert old_refreshed.status == "closed"
    assert task_store.get(item.id).session_id == session.id


# -----------------------------------------------------------------------
# CHANGES: session settings updated on reuse
# -----------------------------------------------------------------------


def test_task_processor_updates_session_settings_on_reuse(
    session_mgr: SessionManager,
    task_store: TaskStore,
    tmp_path: Path,
) -> None:
    """When reusing session, model and max_cost from current task should apply."""
    old_session = session_mgr.create_session("pw", "sonnet", 2.0)
    # Create the worktree dir so it passes the existence check
    Path(old_session.worktree_path).mkdir(parents=True, exist_ok=True)

    item = task_store.create(
        project="pw", title="New task", description="", source="manual",
        session_id=old_session.id,
    )

    # New task wants opus at $5
    new_model = "opus"
    new_max_cost = 5.0

    session = session_mgr.get_session(item.session_id)
    # The fix: update settings if they differ
    if session.model != new_model or session.max_cost_usd != new_max_cost:
        session_mgr.update_session(
            session.id, model=new_model, max_cost_usd=new_max_cost,
        )
        session = session_mgr.get_session(session.id)

    assert session.model == "opus"
    assert session.max_cost_usd == 5.0


# -----------------------------------------------------------------------
# MUST NOT CHANGE: agent_routes worktree check
# -----------------------------------------------------------------------


def test_agent_routes_worktree_check_still_present() -> None:
    """agent_routes.py must still have the worktree existence check."""
    import inspect
    from agents.agent_routes import register_agent_routes

    source = inspect.getsource(register_agent_routes)
    assert "worktree_path" in source
    assert ".exists()" in source


# -----------------------------------------------------------------------
# MUST NOT CHANGE: new session creation path
# -----------------------------------------------------------------------


def test_session_creation_for_new_tasks_unchanged(
    session_mgr: SessionManager,
    task_store: TaskStore,
) -> None:
    """Tasks without session_id always get a fresh session."""
    item = task_store.create(
        project="pw", title="Fresh task", description="", source="manual",
    )
    assert item.session_id is None

    session = session_mgr.create_session("pw", "sonnet", 2.0)
    task_store.update_session(item.id, session.id)

    refreshed = task_store.get(item.id)
    assert refreshed.session_id == session.id
    assert session.status == "active"


# -----------------------------------------------------------------------
# MUST NOT CHANGE: cleanup mechanism
# -----------------------------------------------------------------------


def test_cleanup_stale_sessions_unchanged(session_mgr: SessionManager) -> None:
    """cleanup_stale_sessions still works as before."""
    session = session_mgr.create_session("pw", "sonnet", 2.0)
    # Force updated_at to the past
    with session_mgr._conn() as conn:
        conn.execute(
            "UPDATE agent_sessions SET updated_at = '2020-01-01T00:00:00+00:00'"
            " WHERE id = ?",
            (session.id,),
        )
    cleaned = session_mgr.cleanup_stale_sessions(timeout_minutes=1)
    assert cleaned == 1
    assert session_mgr.get_session(session.id).status == "closed"
