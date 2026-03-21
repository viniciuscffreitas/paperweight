"""Auth middleware factory — registers HTTP session-check middleware on the app."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse

# Paths that bypass auth unconditionally (browser navigation + all API/WS routes)
_SKIP_PREFIXES = (
    "/static/",
    "/health",
    "/status",
    "/login",
    "/register",
    "/favicon.ico",
    "/logout",
    "/admin/",
    "/api/",
    "/tasks/",
    "/runs/",
    "/webhooks/",
    "/ws/",
)


def register_auth_middleware(app: FastAPI) -> None:
    """Attach the session-cookie middleware to *app*.

    Auth is only enforced when ``app.state.auth_db`` is a live ``AuthDB``
    instance (set during lifespan when ``SECRET_KEY`` env var is present).
    All API, webhook, and WebSocket paths are skipped so programmatic callers
    are never redirected.
    """

    @app.middleware("http")
    async def auth_middleware(
        request: Request,
        call_next: Callable[[Request], Coroutine[Any, Any, Response]],
    ) -> Response:
        path = request.url.path
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            return await call_next(request)

        auth_db = getattr(app.state, "auth_db", None)
        if auth_db is None:
            return await call_next(request)

        token = request.cookies.get("pw_session")
        if not token:
            return RedirectResponse("/login", status_code=303)

        user = auth_db.get_session_user(token)
        if not user:
            return RedirectResponse("/login", status_code=303)

        request.state.user = user
        return await call_next(request)
