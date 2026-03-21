"""GitHub OAuth 2.0 routes — /auth/github and /auth/github/callback."""

import logging
import urllib.parse

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse

from agents.auth import AuthDB

logger = logging.getLogger(__name__)

_COOKIE_NAME = "pw_session"
_COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"


async def exchange_code_for_token(code: str, client_id: str, client_secret: str) -> dict:
    """Exchange OAuth authorization code for an access token."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            GITHUB_TOKEN_URL,
            json={"client_id": client_id, "client_secret": client_secret, "code": code},
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_github_user(access_token: str) -> dict:
    """Fetch authenticated user info from GitHub API."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            GITHUB_USER_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        resp.raise_for_status()
        return resp.json()


def register_github_oauth_routes(
    app: FastAPI,
    auth_db: AuthDB,
    client_id: str,
    client_secret: str,
) -> None:
    """Register GitHub OAuth routes on *app*."""

    @app.get("/auth/github")
    async def github_login() -> Response:
        params = urllib.parse.urlencode(
            {
                "client_id": client_id,
                "scope": "read:user",
                "state": "paperweight",
            }
        )
        return RedirectResponse(f"{GITHUB_AUTHORIZE_URL}?{params}", status_code=302)

    @app.get("/auth/github/callback")
    async def github_callback(request: Request, code: str = "", state: str = "") -> Response:
        if not code:
            return RedirectResponse("/login?error=oauth_missing_code", status_code=303)

        try:
            token_data = await exchange_code_for_token(code, client_id, client_secret)
            access_token = token_data.get("access_token", "")
            if not access_token:
                raise ValueError("No access_token in response")

            gh_user = await fetch_github_user(access_token)
        except Exception as exc:
            logger.warning("GitHub OAuth failed: %s", exc)
            return RedirectResponse("/login?error=oauth_failed", status_code=303)

        github_id = str(gh_user.get("id", ""))
        login = gh_user.get("login", f"github_{github_id}")

        if not github_id:
            return RedirectResponse("/login?error=oauth_no_id", status_code=303)

        user = auth_db.find_user_by_github_id(github_id)
        if user is None:
            # New user — ensure username is unique by appending a suffix if needed
            base_username = login
            username = base_username
            suffix = 1
            while True:
                try:
                    user = auth_db.create_github_user(github_id=github_id, username=username)
                    break
                except Exception:
                    username = f"{base_username}{suffix}"
                    suffix += 1
                    if suffix > 10:
                        logger.error("Could not find unique username for GitHub user %s", github_id)
                        return RedirectResponse(
                            "/login?error=oauth_username_conflict", status_code=303,
                        )

        token = auth_db.create_session(user.id)
        response = RedirectResponse("/dashboard", status_code=303)
        response.set_cookie(
            _COOKIE_NAME,
            token,
            max_age=_COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
        )
        return response
