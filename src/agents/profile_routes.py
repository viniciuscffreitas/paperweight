"""Profile routes — user account, API key, password, avatar."""

import logging

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from agents.auth import AuthDB, mask_api_key

logger = logging.getLogger(__name__)


def register_profile_routes(
    app: FastAPI,
    auth_db: AuthDB,
    templates: Jinja2Templates,
) -> None:
    @app.get("/profile", response_class=HTMLResponse)
    async def profile_page(request: Request) -> Response:
        user = getattr(request.state, "user", None)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        return templates.TemplateResponse(
            "profile.html",
            {
                "request": request,
                "user": user,
                "masked_key": mask_api_key(user.api_key),
                "saved": request.query_params.get("saved", ""),
                "error": request.query_params.get("error", ""),
            },
        )

    @app.post("/profile/account", response_class=HTMLResponse)
    async def profile_save_account(request: Request) -> Response:
        user = getattr(request.state, "user", None)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        form = await request.form()
        api_key = str(form.get("api_key", "")).strip()
        auth_db.update_api_key(user.id, api_key)
        return RedirectResponse("/profile?saved=account", status_code=303)

    @app.post("/profile/password", response_class=HTMLResponse)
    async def profile_change_password(request: Request) -> Response:
        user = getattr(request.state, "user", None)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        form = await request.form()
        current = str(form.get("current_password", ""))
        new = str(form.get("new_password", ""))
        if not current or not new:
            return RedirectResponse("/profile?error=password", status_code=303)
        ok = auth_db.change_password(user.username, current, new)
        if not ok:
            return RedirectResponse("/profile?error=password", status_code=303)
        return RedirectResponse("/profile?saved=password", status_code=303)
