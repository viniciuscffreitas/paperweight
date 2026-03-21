"""Tests for GitHub OAuth integration."""

import os
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-oauth-tests")

from agents.auth import AuthDB

# ---------------------------------------------------------------------------
# AuthDB: GitHub user methods
# ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path: Path) -> AuthDB:
    return AuthDB(tmp_path / "auth.db")


def test_create_github_user(db: AuthDB) -> None:
    db.create_user("existing", "pass")  # so octocat is not the first user
    user = db.create_github_user(github_id="12345", username="octocat")
    assert user.id
    assert user.username == "octocat"
    assert user.github_id == "12345"
    assert not user.is_admin


def test_create_github_user_first_is_admin(db: AuthDB) -> None:
    user = db.create_github_user(github_id="99", username="first")
    assert user.is_admin


def test_create_github_user_second_not_admin(db: AuthDB) -> None:
    db.create_github_user(github_id="1", username="first")
    user = db.create_github_user(github_id="2", username="second")
    assert not user.is_admin


def test_find_user_by_github_id_exists(db: AuthDB) -> None:
    db.create_github_user(github_id="42", username="userA")
    found = db.find_user_by_github_id("42")
    assert found is not None
    assert found.username == "userA"
    assert found.github_id == "42"


def test_find_user_by_github_id_missing(db: AuthDB) -> None:
    assert db.find_user_by_github_id("nonexistent") is None


def test_github_user_session_roundtrip(db: AuthDB) -> None:
    user = db.create_github_user(github_id="77", username="ghuser")
    token = db.create_session(user.id)
    resolved = db.get_session_user(token)
    assert resolved is not None
    assert resolved.id == user.id
    assert resolved.github_id == "77"


def test_github_id_unique(db: AuthDB) -> None:
    db.create_github_user(github_id="same-id", username="userX")
    with pytest.raises(sqlite3.IntegrityError):
        db.create_github_user(github_id="same-id", username="userY")


def test_regular_user_github_id_is_none(db: AuthDB) -> None:
    user = db.create_user("alice", "password")
    fetched = db.get_user(user.id)
    assert fetched is not None
    assert fetched.github_id is None


# ---------------------------------------------------------------------------
# Config: github_oauth fields
# ---------------------------------------------------------------------------


def test_config_github_oauth_defaults() -> None:
    from agents.config import IntegrationsConfig

    cfg = IntegrationsConfig()
    assert cfg.github_oauth_client_id == ""
    assert cfg.github_oauth_client_secret == ""


# ---------------------------------------------------------------------------
# OAuth routes
# ---------------------------------------------------------------------------


def _make_app_with_oauth(
    tmp_path: Path,
    client_id: str = "test-client-id",
    client_secret: str = "test-client-secret",
) -> tuple:
    """Create a test FastAPI app with GitHub OAuth routes registered."""
    from fastapi import FastAPI
    from fastapi.templating import Jinja2Templates

    from agents.auth import AuthDB
    from agents.auth_routes import register_auth_routes
    from agents.github_oauth_routes import register_github_oauth_routes

    app = FastAPI()
    auth_db = AuthDB(tmp_path / "auth.db")
    templates_dir = Path(__file__).parent.parent / "src" / "agents" / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))

    app.state.auth_db = auth_db
    register_auth_routes(app, auth_db, templates)
    register_github_oauth_routes(app, auth_db, client_id, client_secret)

    return app, auth_db


def test_github_oauth_redirect(tmp_path: Path) -> None:
    """GET /auth/github should redirect to GitHub with correct params."""
    app, _ = _make_app_with_oauth(tmp_path)
    client = TestClient(app, follow_redirects=False)

    resp = client.get("/auth/github")
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "github.com/login/oauth/authorize" in location
    assert "client_id=test-client-id" in location
    assert "scope=" in location


def test_github_oauth_callback_new_user(tmp_path: Path) -> None:
    """Callback with valid code creates a new user and sets session cookie."""
    app, _ = _make_app_with_oauth(tmp_path)
    client = TestClient(app, follow_redirects=False)

    token_payload = {"access_token": "gho_fake", "token_type": "bearer"}
    user_payload = {"id": 12345, "login": "octocat", "name": "The Octocat"}

    with (
        patch(
            "agents.github_oauth_routes.exchange_code_for_token",
            new_callable=AsyncMock,
            return_value=token_payload,
        ),
        patch(
            "agents.github_oauth_routes.fetch_github_user",
            new_callable=AsyncMock,
            return_value=user_payload,
        ),
    ):
        resp = client.get("/auth/github/callback?code=abc123&state=xyz")

    assert resp.status_code == 303
    assert resp.headers["location"] == "/dashboard"
    assert "pw_session" in resp.cookies


def test_github_oauth_callback_existing_user(tmp_path: Path) -> None:
    """Callback for existing GitHub user reuses user without creating a new one."""
    app, auth_db = _make_app_with_oauth(tmp_path)
    existing = auth_db.create_github_user(github_id="12345", username="octocat")
    client = TestClient(app, follow_redirects=False)

    token_payload = {"access_token": "gho_fake", "token_type": "bearer"}
    user_payload = {"id": 12345, "login": "octocat"}

    with (
        patch(
            "agents.github_oauth_routes.exchange_code_for_token",
            new_callable=AsyncMock,
            return_value=token_payload,
        ),
        patch(
            "agents.github_oauth_routes.fetch_github_user",
            new_callable=AsyncMock,
            return_value=user_payload,
        ),
    ):
        resp = client.get("/auth/github/callback?code=abc123&state=xyz")

    assert resp.status_code == 303
    assert "pw_session" in resp.cookies
    # No duplicate user created
    assert auth_db.find_user_by_github_id("12345") is not None
    assert auth_db.find_user_by_github_id("12345").id == existing.id


def test_github_oauth_callback_missing_code(tmp_path: Path) -> None:
    """Callback without code returns redirect to login with error."""
    app, _ = _make_app_with_oauth(tmp_path)
    client = TestClient(app, follow_redirects=False)

    resp = client.get("/auth/github/callback")
    assert resp.status_code in (302, 303, 400)


def test_github_oauth_callback_token_failure(tmp_path: Path) -> None:
    """If GitHub token exchange fails, redirect to login with error."""
    app, _ = _make_app_with_oauth(tmp_path)
    client = TestClient(app, follow_redirects=False)

    with patch(
        "agents.github_oauth_routes.exchange_code_for_token",
        new_callable=AsyncMock,
        side_effect=Exception("GitHub API error"),
    ):
        resp = client.get("/auth/github/callback?code=bad_code")

    assert resp.status_code in (302, 303)
    assert "/login" in resp.headers.get("location", "")


# ---------------------------------------------------------------------------
# Auth middleware: /auth/github paths are public
# ---------------------------------------------------------------------------


def test_auth_middleware_skips_github_oauth_paths() -> None:
    from agents.auth_middleware import _SKIP_PREFIXES

    assert "/auth/github" in _SKIP_PREFIXES or any(
        "/auth/github".startswith(p) for p in _SKIP_PREFIXES
    )
