import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agents.session_manager import AgentSession, SessionManager


@pytest.fixture
def session_mgr(tmp_path: Path) -> SessionManager:
    db_path = tmp_path / "sessions.db"
    return SessionManager(db_path)


def test_create_session(session_mgr: SessionManager) -> None:
    session = session_mgr.create_session(
        project="my-project",
        model="claude-sonnet-4-6",
        max_cost_usd=1.50,
    )
    assert session.id
    assert len(session.id) == 12
    assert session.project == "my-project"
    assert session.model == "claude-sonnet-4-6"
    assert session.max_cost_usd == 1.50
    assert session.status == "active"
    assert session.worktree_path.endswith(f"session-{session.id}")
    assert session.claude_session_id is None
    assert isinstance(session.created_at, datetime)
    assert isinstance(session.updated_at, datetime)


def test_get_session(session_mgr: SessionManager) -> None:
    created = session_mgr.create_session(
        project="proj-a", model="claude-sonnet-4-6", max_cost_usd=2.00
    )
    fetched = session_mgr.get_session(created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.project == "proj-a"
    assert fetched.status == "active"


def test_get_session_not_found(session_mgr: SessionManager) -> None:
    result = session_mgr.get_session("nonexistent12")
    assert result is None


def test_update_session(session_mgr: SessionManager) -> None:
    session = session_mgr.create_session(
        project="proj-b", model="claude-sonnet-4-6", max_cost_usd=2.00
    )
    session_mgr.update_session(session.id, claude_session_id="claude-abc-123")
    updated = session_mgr.get_session(session.id)
    assert updated is not None
    assert updated.claude_session_id == "claude-abc-123"
    # updated_at should be at least as recent as created_at
    assert updated.updated_at >= session.created_at


def test_close_session(session_mgr: SessionManager) -> None:
    session = session_mgr.create_session(
        project="proj-c", model="claude-sonnet-4-6", max_cost_usd=2.00
    )
    # Acquire run first so we can verify it's released on close
    assert session_mgr.try_acquire_run(session.id) is True

    session_mgr.close_session(session.id)

    closed = session_mgr.get_session(session.id)
    assert closed is not None
    assert closed.status == "closed"
    # Lock should be released — can acquire again
    assert session_mgr.try_acquire_run(session.id) is True


def test_get_active_session(session_mgr: SessionManager) -> None:
    s1 = session_mgr.create_session(
        project="proj-d", model="claude-sonnet-4-6", max_cost_usd=2.00
    )
    s2 = session_mgr.create_session(
        project="proj-d", model="claude-sonnet-4-6", max_cost_usd=2.00
    )
    active = session_mgr.get_active_session("proj-d")
    assert active is not None
    # Should return the most recent one
    assert active.id == s2.id
    _ = s1  # suppress unused warning


def test_get_active_session_none_when_closed(session_mgr: SessionManager) -> None:
    session = session_mgr.create_session(
        project="proj-e", model="claude-sonnet-4-6", max_cost_usd=2.00
    )
    session_mgr.close_session(session.id)
    active = session_mgr.get_active_session("proj-e")
    assert active is None


def test_cleanup_stale_sessions(session_mgr: SessionManager) -> None:
    session = session_mgr.create_session(
        project="proj-f", model="claude-sonnet-4-6", max_cost_usd=2.00
    )
    # Force updated_at to 31 minutes ago via raw SQL
    old_time = (datetime.now(UTC) - timedelta(minutes=31)).isoformat()
    with sqlite3.connect(session_mgr.db_path) as conn:
        conn.execute(
            "UPDATE agent_sessions SET updated_at = ? WHERE id = ?",
            (old_time, session.id),
        )
    count = session_mgr.cleanup_stale_sessions(timeout_minutes=30)
    assert count == 1
    closed = session_mgr.get_session(session.id)
    assert closed is not None
    assert closed.status == "closed"


def test_concurrency_guard(session_mgr: SessionManager) -> None:
    session = session_mgr.create_session(
        project="proj-g", model="claude-sonnet-4-6", max_cost_usd=2.00
    )
    # First acquire should succeed
    assert session_mgr.try_acquire_run(session.id) is True
    # Second acquire for same session should fail
    assert session_mgr.try_acquire_run(session.id) is False
    # After release, should succeed again
    session_mgr.release_run(session.id)
    assert session_mgr.try_acquire_run(session.id) is True
    session_mgr.release_run(session.id)


def test_list_sessions(session_mgr: SessionManager) -> None:
    session_mgr.create_session(
        project="proj-h", model="claude-sonnet-4-6", max_cost_usd=2.00
    )
    session_mgr.create_session(
        project="proj-h", model="claude-sonnet-4-6", max_cost_usd=2.00
    )
    session_mgr.create_session(
        project="other-proj", model="claude-sonnet-4-6", max_cost_usd=2.00
    )
    sessions = session_mgr.list_sessions("proj-h")
    assert len(sessions) == 2
    assert all(s.project == "proj-h" for s in sessions)

    other_sessions = session_mgr.list_sessions("other-proj")
    assert len(other_sessions) == 1
