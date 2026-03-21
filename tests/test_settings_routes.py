"""Tests for settings routes — GET/POST /settings."""
import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-settings-tests")

from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

from agents.auth import AuthDB
from agents.auth_routes import register_auth_routes

_TEMPLATES_DIR = Path(__file__).parent.parent / "src" / "agents" / "templates"


@pytest.fixture
def auth_db(tmp_path: Path) -> AuthDB:
    db = AuthDB(tmp_path / "auth.db")
    return db


@pytest.fixture
def client(auth_db: AuthDB) -> TestClient:
    app = FastAPI()
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    # Inject projects (needed by base.html sidebar)
    @app.middleware("http")
    async def inject_projects(request: Request, call_next):
        request.state.projects = []
        return await call_next(request)

    register_auth_routes(app, auth_db, templates)

    # Create a user and session for authenticated requests
    user = auth_db.create_user("testuser", "password123", api_key="sk-ant-test-key")
    token = auth_db.create_session(user.id)

    # Middleware to simulate authenticated user
    @app.middleware("http")
    async def fake_auth(request: Request, call_next):
        if request.cookies.get("pw_session") == token:
            request.state.user = auth_db.get_session_user(token)
        return await call_next(request)

    return TestClient(app, cookies={"pw_session": token})


# ---------------------------------------------------------------------------
# GET /settings
# ---------------------------------------------------------------------------


def test_get_settings_returns_200(client: TestClient) -> None:
    resp = client.get("/settings")
    assert resp.status_code == 200


def test_get_settings_shows_masked_api_key(client: TestClient) -> None:
    resp = client.get("/settings")
    assert "sk-ant-" in resp.text
    # Should NOT show the full key
    assert "sk-ant-test-key" not in resp.text


def test_get_settings_shows_username(client: TestClient) -> None:
    resp = client.get("/settings")
    assert "testuser" in resp.text


# ---------------------------------------------------------------------------
# POST /settings — update API key
# ---------------------------------------------------------------------------


def test_post_settings_updates_api_key(client: TestClient, auth_db: AuthDB) -> None:
    resp = client.post("/settings", data={"api_key": "sk-ant-new-key"}, follow_redirects=False)
    # Should redirect back to settings
    assert resp.status_code == 303
    assert "/settings" in resp.headers["location"]

    # Verify the key was updated in the DB
    users_with_key = [
        u for uid in ["testuser"]
        if (u := auth_db.authenticate("testuser", "password123")) is not None
    ]
    assert len(users_with_key) == 1
    assert users_with_key[0].api_key == "sk-ant-new-key"


def test_post_settings_clears_api_key(client: TestClient, auth_db: AuthDB) -> None:
    resp = client.post("/settings", data={"api_key": ""}, follow_redirects=False)
    assert resp.status_code == 303

    user = auth_db.authenticate("testuser", "password123")
    assert user is not None
    assert user.api_key == ""
