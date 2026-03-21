import pytest
from fastapi.testclient import TestClient

from agents.task_store import TaskStore


@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "test.db")


@pytest.fixture
def client(store):
    from fastapi import FastAPI

    from agents.task_routes import register_task_routes

    app = FastAPI()
    register_task_routes(app, store)
    return TestClient(app)


def test_create_task(client):
    resp = client.post(
        "/api/work-items",
        json={
            "project": "pw",
            "title": "Fix bug",
            "description": "It's broken",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Fix bug"
    assert data["status"] == "pending"
    assert data["source"] == "manual"


def test_list_tasks_by_project(client):
    client.post("/api/work-items", json={"project": "pw", "title": "T1", "description": "D1"})
    client.post("/api/work-items", json={"project": "pw", "title": "T2", "description": "D2"})
    resp = client.get("/api/work-items?project=pw")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_get_task(client):
    create_resp = client.post(
        "/api/work-items", json={"project": "pw", "title": "T1", "description": "D1"}
    )
    item_id = create_resp.json()["id"]
    resp = client.get(f"/api/work-items/{item_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "T1"


def test_get_task_not_found(client):
    resp = client.get("/api/work-items/nonexistent")
    assert resp.status_code == 404


def test_update_task_status(client):
    create_resp = client.post(
        "/api/work-items", json={"project": "pw", "title": "T1", "description": "D1"}
    )
    item_id = create_resp.json()["id"]
    resp = client.patch(f"/api/work-items/{item_id}", json={"status": "done"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"


def test_rerun_task(client):
    create_resp = client.post(
        "/api/work-items", json={"project": "pw", "title": "T1", "description": "D1"}
    )
    item_id = create_resp.json()["id"]
    client.patch(f"/api/work-items/{item_id}", json={"status": "failed"})
    resp = client.post(f"/api/work-items/{item_id}/rerun")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


def test_create_from_session(client):
    resp = client.post(
        "/api/work-items/from-session",
        json={
            "project": "pw",
            "title": "Fix slow tests",
            "description": "Tests take 30s, should take 5s",
            "session_id": "sess-123",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["source"] == "agent-tab"
    assert data["session_id"] == "sess-123"


def test_create_task_with_draft_status(client):
    resp = client.post(
        "/api/work-items",
        json={
            "project": "pw",
            "title": "Brainstorm idea",
            "description": "rough idea",
            "source": "manual",
            "status": "draft",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "draft"


def test_create_task_default_status_is_pending(client):
    resp = client.post(
        "/api/work-items",
        json={
            "project": "pw",
            "title": "T1",
            "description": "D1",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"


def test_patch_updates_title(client):
    create_resp = client.post(
        "/api/work-items",
        json={
            "project": "pw",
            "title": "Old Title",
            "description": "D",
        },
    )
    item_id = create_resp.json()["id"]
    resp = client.patch(f"/api/work-items/{item_id}", json={"title": "New Title"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "New Title"


def test_patch_status_to_ready(client):
    create_resp = client.post(
        "/api/work-items",
        json={
            "project": "pw",
            "title": "T1",
            "description": "D1",
            "status": "draft",
        },
    )
    item_id = create_resp.json()["id"]
    resp = client.patch(f"/api/work-items/{item_id}", json={"status": "ready"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"
