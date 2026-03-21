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


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    cfg = tmp_path / "settings_config.yaml"
    cfg.write_text(
        "budget:\n  daily_limit_usd: 100.0\n  warning_threshold_usd: 80.0\n"
        "  pause_on_limit: false\n"
        "execution:\n  default_model: sonnet\n  max_concurrent: 3\n  timeout_minutes: 30\n"
        "  default_max_cost_usd: 5.0\n  default_autonomy: pr-only\n  dry_run: false\n"
        "integrations:\n  linear_api_key: ${LINEAR_API_KEY}\n  github_token: ${GITHUB_TOKEN}\n"
    )
    return cfg


@pytest.fixture
def admin_client(auth_db: AuthDB, config_path: Path) -> TestClient:
    app = FastAPI()
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    app.state.config_path = config_path

    @app.middleware("http")
    async def inject_projects(request: Request, call_next):
        request.state.projects = []
        return await call_next(request)

    register_auth_routes(app, auth_db, templates)

    user = auth_db.create_user("admin", "adminpass", is_admin=True)
    token = auth_db.create_session(user.id)

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
# POST /settings/account — update API key
# ---------------------------------------------------------------------------


def test_post_settings_updates_api_key(client: TestClient, auth_db: AuthDB) -> None:
    resp = client.post(
        "/settings/account", data={"api_key": "sk-ant-new-key"}, follow_redirects=False
    )
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
    resp = client.post("/settings/account", data={"api_key": ""}, follow_redirects=False)
    assert resp.status_code == 303

    user = auth_db.authenticate("testuser", "password123")
    assert user is not None
    assert user.api_key == ""


# ---------------------------------------------------------------------------
# POST /settings/password — change password
# ---------------------------------------------------------------------------


def test_post_password_change_success(client: TestClient, auth_db: AuthDB) -> None:
    resp = client.post(
        "/settings/password",
        data={"current_password": "password123", "new_password": "newpass456"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "saved=password" in resp.headers["location"]
    assert auth_db.authenticate("testuser", "newpass456") is not None


def test_post_password_change_wrong_current(client: TestClient) -> None:
    resp = client.post(
        "/settings/password",
        data={"current_password": "wrong", "new_password": "newpass"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=password" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Admin config visibility
# ---------------------------------------------------------------------------


def test_get_settings_shows_execution_config_for_admin(admin_client: TestClient) -> None:
    resp = admin_client.get("/settings")
    assert resp.status_code == 200
    assert "Execution" in resp.text
    assert "Budget" in resp.text


def test_get_settings_hides_admin_sections_for_regular_user(client: TestClient) -> None:
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "Account" in resp.text
    assert "Execution" not in resp.text


# ---------------------------------------------------------------------------
# POST /settings/config — admin config save
# ---------------------------------------------------------------------------


def test_post_config_saves_values(admin_client: TestClient, config_path: Path) -> None:
    resp = admin_client.post(
        "/settings/config",
        data={"budget.daily_limit_usd": "200.00", "execution.default_model": "opus"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    from agents.config_writer import read_raw_config
    raw = read_raw_config(config_path)
    assert raw["budget"]["daily_limit_usd"] == 200.0
    assert raw["execution"]["default_model"] == "opus"


def test_post_config_rejected_for_non_admin(client: TestClient) -> None:
    resp = client.post(
        "/settings/config",
        data={"budget.daily_limit_usd": "999"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/settings" in resp.headers["location"]
