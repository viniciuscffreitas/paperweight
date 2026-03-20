"""Tests for the auth module."""
import os
import time
from pathlib import Path

import pytest

# Ensure SECRET_KEY is set so Fernet encryption works deterministically in tests
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-auth-tests")

from agents.auth import AuthDB, hash_password, verify_password


@pytest.fixture
def db(tmp_path: Path) -> AuthDB:
    return AuthDB(tmp_path / "auth.db")


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def test_hash_password_deterministic() -> None:
    h1 = hash_password("hello", "salt123")
    h2 = hash_password("hello", "salt123")
    assert h1 == h2


def test_hash_password_different_salts() -> None:
    h1 = hash_password("hello", "salt1")
    h2 = hash_password("hello", "salt2")
    assert h1 != h2


def test_verify_password_correct() -> None:
    assert verify_password("secret", "mysalt", hash_password("secret", "mysalt"))


def test_verify_password_wrong() -> None:
    assert not verify_password("wrong", "mysalt", hash_password("secret", "mysalt"))


# ---------------------------------------------------------------------------
# User creation and authentication
# ---------------------------------------------------------------------------

def test_create_user(db: AuthDB) -> None:
    user = db.create_user("alice", "password123")
    assert user.username == "alice"
    assert user.id


def test_authenticate_success(db: AuthDB) -> None:
    db.create_user("bob", "pass456")
    user = db.authenticate("bob", "pass456")
    assert user is not None
    assert user.username == "bob"


def test_authenticate_wrong_password(db: AuthDB) -> None:
    db.create_user("carol", "correct")
    assert db.authenticate("carol", "wrong") is None


def test_authenticate_unknown_user(db: AuthDB) -> None:
    assert db.authenticate("nobody", "pass") is None


def test_first_user_no_explicit_admin(db: AuthDB) -> None:
    """has_users() is false before first user, so first user gets is_admin=True in auth_routes,
    but create_user itself doesn't auto-promote — that logic is in auth_routes."""
    user = db.create_user("admin", "adminpass", is_admin=True)
    assert user.is_admin


def test_api_key_roundtrip(db: AuthDB) -> None:
    db.create_user("dave", "pass", api_key="sk-ant-test-key")
    user = db.authenticate("dave", "pass")
    assert user is not None
    assert user.api_key == "sk-ant-test-key"


def test_api_key_empty_by_default(db: AuthDB) -> None:
    db.create_user("eve", "pass")
    user = db.authenticate("eve", "pass")
    assert user is not None
    assert user.api_key == ""


def test_update_api_key(db: AuthDB) -> None:
    user = db.create_user("frank", "pass", api_key="old-key")
    db.update_api_key(user.id, "new-key")
    fetched = db.get_user(user.id)
    assert fetched is not None
    assert fetched.api_key == "new-key"


def test_username_unique(db: AuthDB) -> None:
    db.create_user("grace", "pass")
    with pytest.raises(Exception):
        db.create_user("grace", "other")


def test_has_users(db: AuthDB) -> None:
    assert not db.has_users()
    db.create_user("heidi", "pass")
    assert db.has_users()


# ---------------------------------------------------------------------------
# Invite codes
# ---------------------------------------------------------------------------

def test_create_and_validate_invite(db: AuthDB) -> None:
    code = db.create_invite()
    invite = db.validate_invite(code)
    assert invite is not None
    assert invite.code == code


def test_invalid_invite_code(db: AuthDB) -> None:
    assert db.validate_invite("nonexistent") is None


def test_invite_already_used(db: AuthDB) -> None:
    code = db.create_invite()
    user = db.create_user("ivan", "pass")
    db.consume_invite(code, user.id)
    assert db.validate_invite(code) is None


def test_invite_expired(db: AuthDB) -> None:
    code = db.create_invite(expires_hours=0)
    # expires_at = now + 0*3600 = now, so it's already expired
    time.sleep(0.01)
    assert db.validate_invite(code) is None


def test_invite_no_expiry(db: AuthDB) -> None:
    code = db.create_invite(expires_hours=None)
    invite = db.validate_invite(code)
    assert invite is not None


def test_consume_invite(db: AuthDB) -> None:
    code = db.create_invite()
    user = db.create_user("judy", "pass")
    db.consume_invite(code, user.id)
    assert db.validate_invite(code) is None  # consumed


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def test_create_and_resolve_session(db: AuthDB) -> None:
    user = db.create_user("ken", "pass")
    token = db.create_session(user.id)
    resolved = db.get_session_user(token)
    assert resolved is not None
    assert resolved.id == user.id


def test_invalid_session_token(db: AuthDB) -> None:
    assert db.get_session_user("bad-token") is None


def test_revoke_session(db: AuthDB) -> None:
    user = db.create_user("luna", "pass")
    token = db.create_session(user.id)
    db.revoke_session(token)
    assert db.get_session_user(token) is None


def test_revoke_all_sessions(db: AuthDB) -> None:
    user = db.create_user("mike", "pass")
    t1 = db.create_session(user.id)
    t2 = db.create_session(user.id)
    db.revoke_all_sessions(user.id)
    assert db.get_session_user(t1) is None
    assert db.get_session_user(t2) is None


# ---------------------------------------------------------------------------
# Bootstrap invite
# ---------------------------------------------------------------------------

def test_bootstrap_invite_on_empty_db(db: AuthDB) -> None:
    code = db.bootstrap_invite()
    assert code is not None
    assert db.validate_invite(code) is not None


def test_bootstrap_invite_noop_when_users_exist(db: AuthDB) -> None:
    db.create_user("nancy", "pass")
    result = db.bootstrap_invite()
    assert result is None
