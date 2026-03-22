"""Tests for session/worktree cleanup when a task is deleted."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.session_manager import SessionManager
from agents.task_routes import register_task_routes
from agents.task_store import TaskStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "tasks.db")


@pytest.fixture
def session_mgr(tmp_path):
    return SessionManager(tmp_path / "sessions.db", worktree_base=str(tmp_path / "worktrees"))


@pytest.fixture
def client(store, session_mgr):
    app = FastAPI()
    register_task_routes(app, store, session_manager=session_mgr)
    return TestClient(app)


def _create_task(client, status="done"):
    resp = client.post(
        "/api/work-items",
        json={"project": "proj", "title": "T", "description": "D", "source": "manual", "status": status},
    )
    assert resp.status_code == 201
    return resp.json()


def _make_worktree(session) -> Path:
    """Create the worktree directory that the session points to.
    Includes a .git file (as a file, not a dir) to simulate a real git worktree.
    """
    wt = Path(session.worktree_path)
    wt.mkdir(parents=True, exist_ok=True)
    (wt / ".git").write_text("gitdir: /some/repo/.git/worktrees/session-abc")
    (wt / "file.txt").write_text("work")
    return wt


# ---------------------------------------------------------------------------
# Session cleanup on delete
# ---------------------------------------------------------------------------


def test_delete_closes_associated_session(client, store, session_mgr):
    """Deleting a task with an associated session closes that session."""
    session = session_mgr.create_session("proj")
    task = _create_task(client)
    store.update_session(task["id"], session.id)

    resp = client.delete(f"/api/work-items/{task['id']}")
    assert resp.status_code == 204
    assert session_mgr.get_session(session.id).status == "closed"


def test_delete_removes_worktree_directory(client, store, session_mgr):
    """Deleting a task removes the associated session's worktree directory."""
    session = session_mgr.create_session("proj")
    wt = _make_worktree(session)
    task = _create_task(client)
    store.update_session(task["id"], session.id)

    client.delete(f"/api/work-items/{task['id']}")

    assert not wt.exists()


def test_delete_without_session_still_returns_204(client):
    """Deleting a task with no session_id succeeds cleanly."""
    task = _create_task(client)
    resp = client.delete(f"/api/work-items/{task['id']}")
    assert resp.status_code == 204


def test_delete_with_missing_worktree_does_not_crash(client, store, session_mgr):
    """If worktree dir already gone, delete still returns 204 without error."""
    session = session_mgr.create_session("proj")
    # Deliberately do NOT create the worktree dir
    task = _create_task(client)
    store.update_session(task["id"], session.id)

    resp = client.delete(f"/api/work-items/{task['id']}")
    assert resp.status_code == 204


def test_delete_with_stale_session_id_does_not_crash(client, store, session_mgr):
    """If session_id on task points to a nonexistent session, delete still returns 204."""
    task = _create_task(client)
    store.update_session(task["id"], "stale-session-id-does-not-exist")

    resp = client.delete(f"/api/work-items/{task['id']}")
    assert resp.status_code == 204


def test_running_task_guard_unaffected(client, store, session_mgr):
    """RUNNING guard works correctly even when session_manager is present."""
    session = session_mgr.create_session("proj")
    wt = _make_worktree(session)
    task = _create_task(client, status="running")
    store.update_session(task["id"], session.id)

    resp = client.delete(f"/api/work-items/{task['id']}")
    assert resp.status_code == 409
    assert session_mgr.get_session(session.id).status == "active"
    assert wt.exists()


def test_register_without_session_manager_backward_compat(store):
    """register_task_routes works when session_manager is omitted."""
    app = FastAPI()
    register_task_routes(app, store)  # no session_manager kwarg
    c = TestClient(app)
    task = c.post(
        "/api/work-items",
        json={"project": "p", "title": "T", "description": "D", "source": "manual", "status": "done"},
    ).json()
    resp = c.delete(f"/api/work-items/{task['id']}")
    assert resp.status_code == 204
