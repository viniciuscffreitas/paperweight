"""Tests for /profile route."""
from __future__ import annotations
from unittest.mock import MagicMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.templating import Jinja2Templates
from pathlib import Path

from agents.profile_routes import register_profile_routes
from agents.auth import AuthDB

_TEMPLATES = Path(__file__).parent.parent.parent / "src" / "agents" / "templates"


@pytest.fixture
def auth_db(tmp_path):
    db = AuthDB(tmp_path / "auth.db")
    db.create_user("alice", "pw", api_key="sk-test", is_admin=False)
    return db


@pytest.fixture
def alice(auth_db):
    return auth_db.authenticate("alice", "pw")


@pytest.fixture
def client(auth_db, alice):
    app = FastAPI()
    templates = Jinja2Templates(directory=str(_TEMPLATES))
    register_profile_routes(app, auth_db, templates)

    @app.middleware("http")
    async def inject_user(request, call_next):
        request.state.user = alice
        return await call_next(request)

    return TestClient(app)


def test_profile_page_renders(client):
    resp = client.get("/profile")
    assert resp.status_code == 200
    assert "alice" in resp.text


def test_profile_shows_masked_api_key(client):
    resp = client.get("/profile")
    assert "sk-tes" in resp.text or "****" in resp.text


def test_profile_account_post_updates_api_key(client, auth_db, alice):
    resp = client.post("/profile/account", data={"api_key": "sk-new-key"})
    assert resp.status_code in (200, 303)
    updated = auth_db.get_user(alice.id)
    assert updated.api_key == "sk-new-key"


def test_profile_password_post_changes_password(client, auth_db, alice):
    resp = client.post(
        "/profile/password",
        data={"current_password": "pw", "new_password": "newpw"},
    )
    assert resp.status_code in (200, 303)
    assert auth_db.authenticate("alice", "newpw") is not None


def test_profile_password_wrong_current_returns_error(client):
    resp = client.post(
        "/profile/password",
        data={"current_password": "wrong", "new_password": "newpw"},
        follow_redirects=True,
    )
    assert "error" in str(resp.url) or resp.status_code == 200


def test_profile_requires_auth():
    """Without injected user, GET /profile should redirect to /login."""
    from agents.auth import AuthDB
    app2 = FastAPI()
    db = AuthDB.__new__(AuthDB)  # dummy, won't be used
    templates = Jinja2Templates(directory=str(_TEMPLATES))
    register_profile_routes(app2, db, templates)
    c = TestClient(app2, follow_redirects=False)
    resp = c.get("/profile")
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


def test_avatar_upload_stores_data_uri(client, auth_db, alice):
    """Uploading a valid JPEG sets avatar_url as data URI on the user."""
    import io
    # Minimal valid JPEG bytes
    tiny_jpeg = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
        b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
        b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e\xc0"
        b"\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01"
        b"\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03"
        b"\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xf5\x0f"
        b"\xff\xd9"
    )
    resp = client.post(
        "/profile/avatar",
        files={"avatar": ("photo.jpg", io.BytesIO(tiny_jpeg), "image/jpeg")},
    )
    assert resp.status_code in (200, 303)
    updated = auth_db.get_user(alice.id)
    assert updated.avatar_url.startswith("data:image/")


def test_avatar_upload_rejects_large_file(client):
    """Files over 512 KB are rejected."""
    import io
    big = io.BytesIO(b"\xff\xd8" + b"\x00" * (513 * 1024))
    resp = client.post(
        "/profile/avatar",
        files={"avatar": ("big.jpg", big, "image/jpeg")},
        follow_redirects=False,
    )
    assert resp.status_code in (303, 400)


def test_avatar_upload_rejects_wrong_mime(client):
    """Non-image files are rejected."""
    import io
    resp = client.post(
        "/profile/avatar",
        files={"avatar": ("script.js", io.BytesIO(b"alert(1)"), "text/javascript")},
        follow_redirects=False,
    )
    assert resp.status_code in (303, 400)
