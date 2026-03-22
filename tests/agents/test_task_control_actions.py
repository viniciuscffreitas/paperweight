"""Tests for task control actions: DELETE and Duplicate endpoints."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.models import TaskStatus
from agents.task_routes import register_task_routes
from agents.task_store import TaskStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "test.db")


@pytest.fixture
def client(store):
    app = FastAPI()
    register_task_routes(app, store)
    return TestClient(app)


def _create_task(client, project="proj", title="Test task", status="pending"):
    resp = client.post(
        "/api/work-items",
        json={"project": project, "title": title, "description": title, "source": "manual", "status": status},
    )
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# DELETE /api/work-items/{id}
# ---------------------------------------------------------------------------


def test_delete_task_returns_204(client, store):
    """DELETE an existing task returns 204 No Content."""
    task = _create_task(client)
    resp = client.delete(f"/api/work-items/{task['id']}")
    assert resp.status_code == 204


def test_delete_task_removes_from_store(client, store):
    """After DELETE, task is no longer retrievable."""
    task = _create_task(client)
    client.delete(f"/api/work-items/{task['id']}")
    assert store.get(task["id"]) is None


def test_delete_nonexistent_task_returns_404(client):
    """DELETE a task that doesn't exist returns 404."""
    resp = client.delete("/api/work-items/doesnotexist")
    assert resp.status_code == 404


def test_delete_running_task_returns_409(client, store):
    """DELETE a RUNNING task is blocked — returns 409."""
    task = _create_task(client, status="running")
    resp = client.delete(f"/api/work-items/{task['id']}")
    assert resp.status_code == 409
    # Task must still exist
    assert store.get(task["id"]) is not None


def test_delete_done_task_succeeds(client, store):
    """DELETE a DONE task succeeds (non-running state is allowed)."""
    task = _create_task(client, status="done")
    resp = client.delete(f"/api/work-items/{task['id']}")
    assert resp.status_code == 204
    assert store.get(task["id"]) is None


def test_delete_failed_task_succeeds(client, store):
    """DELETE a FAILED task succeeds."""
    task = _create_task(client, status="failed")
    resp = client.delete(f"/api/work-items/{task['id']}")
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# POST /api/work-items/{id}/duplicate
# ---------------------------------------------------------------------------


def test_duplicate_task_returns_201(client):
    """Duplicate an existing task returns 201 with a new task."""
    task = _create_task(client, title="Original task")
    resp = client.post(f"/api/work-items/{task['id']}/duplicate")
    assert resp.status_code == 201


def test_duplicate_task_copies_title_and_description(client):
    """Duplicated task has the same title and description as the original."""
    task = _create_task(client, title="Original task")
    resp = client.post(f"/api/work-items/{task['id']}/duplicate")
    new_task = resp.json()
    assert new_task["title"] == task["title"]
    assert new_task["description"] == task["description"]
    assert new_task["project"] == task["project"]


def test_duplicate_task_gets_new_id(client):
    """Duplicated task has a different ID from the original."""
    task = _create_task(client, title="Original task")
    resp = client.post(f"/api/work-items/{task['id']}/duplicate")
    new_task = resp.json()
    assert new_task["id"] != task["id"]


def test_duplicate_task_starts_as_draft(client):
    """Duplicated task always starts in DRAFT status, regardless of original."""
    task = _create_task(client, status="done")
    resp = client.post(f"/api/work-items/{task['id']}/duplicate")
    new_task = resp.json()
    assert new_task["status"] == "draft"


def test_duplicate_nonexistent_task_returns_404(client):
    """Duplicate a task that doesn't exist returns 404."""
    resp = client.post("/api/work-items/doesnotexist/duplicate")
    assert resp.status_code == 404


def test_duplicate_preserves_source_manual(client):
    """Duplicated task has source='manual' (not inheriting automation source)."""
    task = _create_task(client)
    resp = client.post(f"/api/work-items/{task['id']}/duplicate")
    new_task = resp.json()
    assert new_task["source"] == "manual"


# ---------------------------------------------------------------------------
# TaskStore.delete
# ---------------------------------------------------------------------------


def test_store_delete_returns_true_on_success(store):
    """TaskStore.delete returns True when the task exists and is deleted."""
    item = store.create(project="p", title="t", description="d", source="manual")
    assert store.delete(item.id) is True


def test_store_delete_returns_false_for_nonexistent(store):
    """TaskStore.delete returns False when the task doesn't exist."""
    assert store.delete("nonexistent") is False


def test_store_delete_blocks_running(store):
    """TaskStore.delete returns False (and does not delete) for RUNNING tasks."""
    item = store.create(
        project="p", title="t", description="d", source="manual", status=TaskStatus.RUNNING
    )
    result = store.delete(item.id)
    assert result is False
    assert store.get(item.id) is not None


# ---------------------------------------------------------------------------
# TaskStore.duplicate
# ---------------------------------------------------------------------------


def test_store_duplicate_creates_new_item(store):
    """TaskStore.duplicate creates a new work item with the same title/description."""
    original = store.create(project="p", title="My task", description="Do the thing", source="manual")
    new_item = store.duplicate(original.id)
    assert new_item is not None
    assert new_item.id != original.id
    assert new_item.title == original.title
    assert new_item.description == original.description
    assert new_item.project == original.project


def test_store_duplicate_sets_draft_status(store):
    """Duplicated task starts in DRAFT status."""
    original = store.create(
        project="p", title="t", description="d", source="manual", status=TaskStatus.DONE
    )
    new_item = store.duplicate(original.id)
    assert new_item.status == TaskStatus.DRAFT


def test_store_duplicate_returns_none_for_nonexistent(store):
    """TaskStore.duplicate returns None when the original doesn't exist."""
    result = store.duplicate("nonexistent")
    assert result is None
