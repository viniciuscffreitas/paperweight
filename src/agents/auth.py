"""Authentication — users, invite codes, and session tokens.

Strategy:
- Passwords: pbkdf2_hmac with sha256 (built-in, no extra deps)
- API key at rest: Fernet symmetric encryption keyed from SECRET_KEY env var
- Sessions: random 32-byte hex token stored in SQLite (no JWT)
- Invite codes: random 16-byte hex, optional expiry
"""

import base64
import hashlib
import logging
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fernet-compatible encryption (lazy import so cryptography is optional at
# import time — error surfaces only when encryption is actually needed)
# ---------------------------------------------------------------------------


def _fernet_key() -> bytes:
    """Derive a 32-byte Fernet key from the SECRET_KEY env var."""
    raw = os.environ.get("SECRET_KEY", "")
    if not raw:
        # Fallback: generate one per process (API keys won't survive restart!)
        logger.warning(
            "SECRET_KEY not set — API keys will be lost on restart. "
            "Set SECRET_KEY env var for persistent encryption."
        )
        raw = "insecure-dev-key-change-me"
    digest = hashlib.sha256(raw.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _encrypt(plaintext: str) -> str:
    from cryptography.fernet import Fernet

    f = Fernet(_fernet_key())
    return f.encrypt(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    from cryptography.fernet import Fernet

    f = Fernet(_fernet_key())
    return f.decrypt(ciphertext.encode()).decode()


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class User:
    id: str
    username: str
    is_admin: bool
    _api_key_enc: str  # encrypted; use .api_key property
    github_id: str | None = None
    _github_token_enc: str = ""  # encrypted; use .github_token property
    avatar_url: str = ""

    @property
    def api_key(self) -> str:
        if not self._api_key_enc:
            return ""
        try:
            return _decrypt(self._api_key_enc)
        except Exception:
            logger.warning("Failed to decrypt API key for user %s", self.id)
            return ""

    @property
    def github_token(self) -> str:
        if not self._github_token_enc:
            return ""
        try:
            return _decrypt(self._github_token_enc)
        except Exception:
            logger.warning("Failed to decrypt GitHub token for user %s", self.id)
            return ""


@dataclass
class InviteCode:
    code: str
    created_by: str | None
    expires_at: float | None
    used_by: str | None


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


def mask_api_key(key: str) -> str:
    """Show prefix + masked suffix so user can identify which key is set."""
    if not key:
        return ""
    if len(key) <= 10:
        return key[:3] + "****"
    return key[:7] + "****"


def hash_password(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return dk.hex()


def verify_password(password: str, salt: str, hashed: str) -> bool:
    return secrets.compare_digest(hash_password(password, salt), hashed)


# ---------------------------------------------------------------------------
# AuthDB
# ---------------------------------------------------------------------------

SESSION_TTL_SECONDS = 30 * 24 * 3600  # 30 days


class AuthDB:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    api_key_enc TEXT NOT NULL DEFAULT '',
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    github_id TEXT UNIQUE,
                    github_token_enc TEXT NOT NULL DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS invite_codes (
                    code TEXT PRIMARY KEY,
                    created_by TEXT,
                    created_at REAL NOT NULL,
                    expires_at REAL,
                    used_by TEXT,
                    used_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_sessions (
                    token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON user_sessions (user_id)")

        # Migration: add github_id to existing databases that predate this column.
        # Runs in a separate connection so any OperationalError doesn't taint the
        # table-creation transaction above.
        # SQLite does NOT support ADD COLUMN with UNIQUE constraint —
        # add the column plain, then create a unique index separately.
        for col_migration in [
            "ALTER TABLE users ADD COLUMN github_id TEXT",
            "ALTER TABLE users ADD COLUMN github_token_enc TEXT NOT NULL DEFAULT ''",
        ]:
            try:
                with self._conn() as mconn:
                    mconn.execute(col_migration)
            except Exception:
                pass  # Column already present
        try:
            with self._conn() as mconn:
                mconn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS"
                    " idx_users_github_id ON users (github_id)"
                )
        except Exception:
            pass
        try:
            with self._conn() as mconn:
                mconn.execute(
                    "ALTER TABLE users ADD COLUMN avatar_url TEXT NOT NULL DEFAULT ''"
                )
        except Exception:
            pass  # Column already present

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def has_users(self) -> bool:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
            return (row[0] or 0) > 0

    def create_user(
        self,
        username: str,
        password: str,
        api_key: str = "",
        is_admin: bool = False,
    ) -> User:
        uid = secrets.token_hex(8)
        salt = secrets.token_hex(32)
        hashed = hash_password(password, salt)
        api_key_enc = _encrypt(api_key) if api_key else ""
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO users"
                " (id, username, password_hash, password_salt,"
                " api_key_enc, is_admin, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (uid, username, hashed, salt, api_key_enc, int(is_admin), now),
            )
        return User(id=uid, username=username, is_admin=is_admin, _api_key_enc=api_key_enc)

    def authenticate(self, username: str, password: str) -> User | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, username, password_hash, password_salt,"
                " api_key_enc, is_admin, github_id, github_token_enc, avatar_url"
                " FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if row is None:
            return None
        if not verify_password(password, row["password_salt"], row["password_hash"]):
            return None
        return User(
            id=row["id"],
            username=row["username"],
            is_admin=bool(row["is_admin"]),
            _api_key_enc=row["api_key_enc"] or "",
            github_id=row["github_id"],
            _github_token_enc=row["github_token_enc"] or "",
            avatar_url=row["avatar_url"] or "",
        )

    def get_user(self, user_id: str) -> User | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, username, api_key_enc, is_admin, github_id,"
                " github_token_enc, avatar_url FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return User(
            id=row["id"],
            username=row["username"],
            is_admin=bool(row["is_admin"]),
            _api_key_enc=row["api_key_enc"] or "",
            github_id=row["github_id"],
            _github_token_enc=row["github_token_enc"] or "",
            avatar_url=row["avatar_url"] or "",
        )

    def find_user_by_github_id(self, github_id: str) -> User | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, username, api_key_enc, is_admin, github_id,"
                " github_token_enc, avatar_url FROM users WHERE github_id = ?",
                (github_id,),
            ).fetchone()
        if row is None:
            return None
        return User(
            id=row["id"],
            username=row["username"],
            is_admin=bool(row["is_admin"]),
            _api_key_enc=row["api_key_enc"] or "",
            github_id=row["github_id"],
            _github_token_enc=row["github_token_enc"] or "",
            avatar_url=row["avatar_url"] or "",
        )

    def create_github_user(self, github_id: str, username: str) -> User:
        uid = secrets.token_hex(8)
        now = time.time()
        is_admin = not self.has_users()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO users"
                " (id, username, password_hash, password_salt,"
                " api_key_enc, is_admin, created_at, github_id)"
                " VALUES (?, ?, '', '', '', ?, ?, ?)",
                (uid, username, int(is_admin), now, github_id),
            )
        return User(
            id=uid,
            username=username,
            is_admin=is_admin,
            _api_key_enc="",
            github_id=github_id,
        )

    def update_api_key(self, user_id: str, api_key: str) -> None:
        api_key_enc = _encrypt(api_key) if api_key else ""
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET api_key_enc = ? WHERE id = ?",
                (api_key_enc, user_id),
            )

    def update_github_token(self, user_id: str, token: str) -> None:
        token_enc = _encrypt(token) if token else ""
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET github_token_enc = ? WHERE id = ?",
                (token_enc, user_id),
            )

    def update_avatar(self, user_id: str, data_uri: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET avatar_url = ? WHERE id = ?",
                (data_uri, user_id),
            )

    def change_password(self, username: str, current_password: str, new_password: str) -> bool:
        """Change password if current_password is correct. Returns True on success."""
        user = self.authenticate(username, current_password)
        if user is None:
            return False
        salt = secrets.token_hex(32)
        hashed = hash_password(new_password, salt)
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, password_salt = ? WHERE id = ?",
                (hashed, salt, user.id),
            )
        return True

    # ------------------------------------------------------------------
    # Invite codes
    # ------------------------------------------------------------------

    def create_invite(
        self,
        created_by: str | None = None,
        expires_hours: int | None = 168,
    ) -> str:
        code = secrets.token_urlsafe(16)
        now = time.time()
        expires_at = now + expires_hours * 3600 if expires_hours is not None else None
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO invite_codes"
                " (code, created_by, created_at, expires_at)"
                " VALUES (?, ?, ?, ?)",
                (code, created_by, now, expires_at),
            )
        return code

    def validate_invite(self, code: str) -> InviteCode | None:
        """Return the invite if valid and unused; None otherwise."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT code, created_by, expires_at, used_by FROM invite_codes WHERE code = ?",
                (code,),
            ).fetchone()
        if row is None:
            return None
        if row["used_by"] is not None:
            return None  # already used
        if row["expires_at"] and time.time() > row["expires_at"]:
            return None  # expired
        return InviteCode(
            code=row["code"],
            created_by=row["created_by"],
            expires_at=row["expires_at"],
            used_by=row["used_by"],
        )

    def consume_invite(self, code: str, user_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE invite_codes SET used_by = ?, used_at = ? WHERE code = ?",
                (user_id, time.time(), code),
            )

    def list_invites(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT code, created_by, created_at, expires_at, used_by, used_at"
                " FROM invite_codes ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def create_session(self, user_id: str) -> str:
        token = secrets.token_hex(32)
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO user_sessions"
                " (token, user_id, created_at, expires_at)"
                " VALUES (?, ?, ?, ?)",
                (token, user_id, now, now + SESSION_TTL_SECONDS),
            )
        return token

    def get_session_user(self, token: str) -> User | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT user_id, expires_at FROM user_sessions WHERE token = ?",
                (token,),
            ).fetchone()
        if row is None:
            return None
        if time.time() > row["expires_at"]:
            self.revoke_session(token)
            return None
        return self.get_user(row["user_id"])

    def revoke_session(self, token: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM user_sessions WHERE token = ?", (token,))

    def revoke_all_sessions(self, user_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))

    # ------------------------------------------------------------------
    # Bootstrap: print invite on first run
    # ------------------------------------------------------------------

    def bootstrap_invite(self) -> str | None:
        """If no users exist, create and return a first-run invite code."""
        if self.has_users():
            return None
        code = self.create_invite(created_by=None, expires_hours=None)
        logger.info("=" * 60)
        logger.info("FIRST RUN — no users found.")
        logger.info("Register at: /register?invite=%s", code)
        logger.info("=" * 60)
        return code
