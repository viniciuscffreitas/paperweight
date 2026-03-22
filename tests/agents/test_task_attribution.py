"""Tests for task created_by attribution."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from agents.task_routes import register_task_routes
from agents.task_store import TaskStore


@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "tasks.db")


@pytest.fixture
def client(store):
    app = FastAPI()
    register_task_routes(app, store)
    return TestClient(app)


def test_create_with_created_by(client):
    resp = client.post(
        "/api/work-items",
        json={
            "project": "proj",
            "title": "T",
            "description": "D",
            "source": "manual",
            "created_by": "alice",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["created_by"] == "alice"


def test_create_without_created_by_defaults_none(client):
    resp = client.post(
        "/api/work-items",
        json={"project": "proj", "title": "T", "description": "D", "source": "manual"},
    )
    assert resp.status_code == 201
    assert resp.json()["created_by"] is None


def test_created_by_persists_on_get(client):
    create = client.post(
        "/api/work-items",
        json={
            "project": "proj",
            "title": "T",
            "description": "D",
            "source": "manual",
            "created_by": "user-xyz",
        },
    )
    item_id = create.json()["id"]
    get = client.get(f"/api/work-items/{item_id}")
    assert get.status_code == 200
    assert get.json()["created_by"] == "user-xyz"


def test_list_includes_created_by(client):
    client.post(
        "/api/work-items",
        json={
            "project": "p",
            "title": "T",
            "description": "D",
            "source": "manual",
            "created_by": "user-list",
        },
    )
    items = client.get("/api/work-items?project=p").json()
    assert any(i["created_by"] == "user-list" for i in items)
