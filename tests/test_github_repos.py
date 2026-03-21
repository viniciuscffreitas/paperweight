"""Tests for GitHub OAuth Phase 2 — token storage, repo discovery, enable/disable."""

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-oauth-tests")

from agents.auth import AuthDB

# -----------------------------------------------------------------------
# Token storage on User
# -----------------------------------------------------------------------


@pytest.fixture
def db(tmp_path: Path) -> AuthDB:
    return AuthDB(tmp_path / "auth.db")


def test_github_user_has_no_token_by_default(db: AuthDB) -> None:
    user = db.create_github_user(github_id="123", username="octocat")
    assert user.github_token == ""


def test_store_github_token(db: AuthDB) -> None:
    user = db.create_github_user(github_id="123", username="octocat")
    db.update_github_token(user.id, "gho_abc123secret")
    refreshed = db.get_user(user.id)
    assert refreshed.github_token == "gho_abc123secret"


def test_github_token_encrypted_at_rest(db: AuthDB) -> None:
    """Raw DB value should NOT be the plaintext token."""
    user = db.create_github_user(github_id="123", username="octocat")
    db.update_github_token(user.id, "gho_plaintext")
    with db._conn() as conn:
        row = conn.execute(
            "SELECT github_token_enc FROM users WHERE id = ?", (user.id,)
        ).fetchone()
    assert row is not None
    assert row["github_token_enc"] != "gho_plaintext"
    assert row["github_token_enc"] != ""


def test_regular_user_github_token_empty(db: AuthDB) -> None:
    user = db.create_user("alice", "password")
    fetched = db.get_user(user.id)
    assert fetched.github_token == ""


# -----------------------------------------------------------------------
# OAuth callback stores token
# -----------------------------------------------------------------------


def _make_app(tmp_path: Path) -> tuple:
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
    register_github_oauth_routes(app, auth_db, "test-id", "test-secret")
    return app, auth_db


def test_oauth_callback_stores_token(tmp_path: Path) -> None:
    """OAuth callback should persist the access token on the user."""
    app, auth_db = _make_app(tmp_path)
    client = TestClient(app, follow_redirects=False)

    token_payload = {"access_token": "gho_stored_token", "token_type": "bearer"}
    user_payload = {"id": 42, "login": "octocat"}

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
        resp = client.get("/auth/github/callback?code=abc123")

    assert resp.status_code == 303
    user = auth_db.find_user_by_github_id("42")
    assert user is not None
    assert user.github_token == "gho_stored_token"


def test_oauth_callback_updates_token_on_relogin(tmp_path: Path) -> None:
    """Re-login should update the stored token."""
    app, auth_db = _make_app(tmp_path)
    auth_db.create_github_user(github_id="42", username="octocat")
    auth_db.update_github_token(
        auth_db.find_user_by_github_id("42").id, "gho_old_token"
    )
    client = TestClient(app, follow_redirects=False)

    token_payload = {"access_token": "gho_new_token", "token_type": "bearer"}
    user_payload = {"id": 42, "login": "octocat"}

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
        client.get("/auth/github/callback?code=abc123")

    user = auth_db.find_user_by_github_id("42")
    assert user.github_token == "gho_new_token"


# -----------------------------------------------------------------------
# Repo discovery endpoint
# -----------------------------------------------------------------------


def test_github_repos_endpoint_returns_repos(tmp_path: Path) -> None:
    """GET /api/github/repos lists user repos from GitHub API."""
    app, auth_db = _make_app(tmp_path)
    user = auth_db.create_github_user(github_id="42", username="octocat")
    auth_db.update_github_token(user.id, "gho_test_token")
    token = auth_db.create_session(user.id)

    mock_repos = [
        {"id": 1, "full_name": "octocat/hello", "private": False},
        {"id": 2, "full_name": "octocat/secret", "private": True},
    ]

    from agents.github_oauth_routes import register_github_repo_routes

    register_github_repo_routes(app, auth_db)

    client = TestClient(app)
    with patch(
        "agents.github_oauth_routes.fetch_github_repos",
        new_callable=AsyncMock,
        return_value=mock_repos,
    ):
        resp = client.get(
            "/api/github/repos", cookies={"pw_session": token}
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["full_name"] == "octocat/hello"


def test_github_repos_requires_token(tmp_path: Path) -> None:
    """Endpoint returns 401 if user has no GitHub token."""
    app, auth_db = _make_app(tmp_path)
    user = auth_db.create_user("alice", "password")
    token = auth_db.create_session(user.id)

    from agents.github_oauth_routes import register_github_repo_routes

    register_github_repo_routes(app, auth_db)

    client = TestClient(app)
    resp = client.get(
        "/api/github/repos", cookies={"pw_session": token}
    )
    assert resp.status_code == 401
