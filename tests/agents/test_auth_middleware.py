"""Tests for auth_middleware — session-cookie enforcement."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.auth_middleware import register_auth_middleware


def _make_app(auth_db=None) -> FastAPI:
    app = FastAPI()
    app.state.auth_db = auth_db

    register_auth_middleware(app)

    @app.get("/dashboard")
    async def dashboard():
        return {"page": "dashboard"}

    @app.get("/api/runs")
    async def api_runs():
        return {"runs": []}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/login")
    async def login():
        return {"page": "login"}

    return app


# ---------------------------------------------------------------------------
# Auth disabled (auth_db = None)
# ---------------------------------------------------------------------------

def test_auth_disabled_allows_all_paths():
    app = _make_app(auth_db=None)
    client = TestClient(app, follow_redirects=False)
    assert client.get("/dashboard").status_code == 200
    assert client.get("/api/runs").status_code == 200
    assert client.get("/health").status_code == 200


# ---------------------------------------------------------------------------
# Auth enabled — skip paths pass through
# ---------------------------------------------------------------------------

class _FakeAuthDB:
    def __init__(self, user=None):
        self._user = user

    def get_session_user(self, token: str):
        return self._user if token == "valid-token" else None


class _FakeUser:
    pass


def test_skip_paths_bypass_auth():
    db = _FakeAuthDB(user=None)  # no valid sessions
    app = _make_app(auth_db=db)
    client = TestClient(app, follow_redirects=False)
    # These should pass through even without a cookie
    assert client.get("/health").status_code == 200
    assert client.get("/login").status_code == 200
    assert client.get("/api/runs").status_code == 200


def test_protected_path_no_cookie_redirects_to_login():
    db = _FakeAuthDB(user=None)
    app = _make_app(auth_db=db)
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/dashboard")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_protected_path_invalid_token_redirects_to_login():
    db = _FakeAuthDB(user=None)
    app = _make_app(auth_db=db)
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/dashboard", cookies={"pw_session": "bad-token"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_protected_path_valid_token_passes_through():
    user = _FakeUser()
    db = _FakeAuthDB(user=user)
    app = _make_app(auth_db=db)

    # Capture request.state.user inside the route to verify injection
    captured = {}

    from fastapi import Request as _Request

    @app.get("/profile")
    async def profile(request: _Request):
        captured["user"] = getattr(request.state, "user", None)
        return {"ok": True}

    client = TestClient(app, follow_redirects=False)
    resp = client.get("/profile", cookies={"pw_session": "valid-token"})
    assert resp.status_code == 200
    assert captured["user"] is user
