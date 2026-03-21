"""Auth routes — login, logout, register (via invite), admin invite management."""
import logging

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from agents.auth import AuthDB

logger = logging.getLogger(__name__)

_COOKIE_NAME = "pw_session"
_COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days


def register_auth_routes(app: FastAPI, auth_db: AuthDB, templates: Jinja2Templates) -> None:
    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request, error: str = "") -> HTMLResponse:
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": error},
        )

    @app.post("/login", response_class=HTMLResponse)
    async def login_submit(request: Request) -> Response:
        form = await request.form()
        username = str(form.get("username", "")).strip()
        password = str(form.get("password", ""))
        user = auth_db.authenticate(username, password)
        if user is None:
            return templates.TemplateResponse(
                "auth/login.html",
                {"request": request, "error": "Invalid username or password."},
                status_code=401,
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

    # ------------------------------------------------------------------
    # Logout
    # ------------------------------------------------------------------

    @app.get("/logout")
    async def logout(request: Request) -> Response:
        token = request.cookies.get(_COOKIE_NAME)
        if token:
            auth_db.revoke_session(token)
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(_COOKIE_NAME)
        return response

    # ------------------------------------------------------------------
    # Register (invite-gated)
    # ------------------------------------------------------------------

    @app.get("/register", response_class=HTMLResponse)
    async def register_page(request: Request, invite: str = "", error: str = "") -> HTMLResponse:
        if not invite:
            return templates.TemplateResponse(
                "auth/login.html",
                {"request": request, "error": "Invalid or missing invite link."},
                status_code=400,
            )
        valid = auth_db.validate_invite(invite)
        if valid is None:
            return templates.TemplateResponse(
                "auth/login.html",
                {"request": request, "error": "Invalid, expired, or already used invite."},
                status_code=400,
            )
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "invite": invite, "error": error},
        )

    @app.post("/register", response_class=HTMLResponse)
    async def register_submit(request: Request) -> Response:
        form = await request.form()
        invite_code = str(form.get("invite", "")).strip()
        username = str(form.get("username", "")).strip()
        password = str(form.get("password", ""))
        api_key = str(form.get("api_key", "")).strip()

        if not username or not password:
            return templates.TemplateResponse(
                "auth/register.html",
                {"request": request, "invite": invite_code,
                 "error": "Username and password are required."},
                status_code=400,
            )

        invite = auth_db.validate_invite(invite_code)
        if invite is None:
            return templates.TemplateResponse(
                "auth/register.html",
                {"request": request, "invite": invite_code,
                 "error": "Invalid or expired invite."},
                status_code=400,
            )

        # First user becomes admin
        is_admin = not auth_db.has_users()

        try:
            user = auth_db.create_user(
                username=username,
                password=password,
                api_key=api_key,
                is_admin=is_admin,
            )
        except Exception as exc:
            # Likely unique constraint on username
            logger.info("Registration failed for %r: %s", username, exc)
            return templates.TemplateResponse(
                "auth/register.html",
                {"request": request, "invite": invite_code,
                 "error": "Username already exists. Choose another."},
                status_code=400,
            )

        auth_db.consume_invite(invite_code, user.id)
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

    # ------------------------------------------------------------------
    # Admin — invite management
    # ------------------------------------------------------------------

    @app.get("/admin/invite", response_class=HTMLResponse)
    async def admin_invite_page(request: Request) -> Response:
        user = getattr(request.state, "user", None)
        if user is None or not user.is_admin:
            return RedirectResponse("/dashboard", status_code=303)
        invites = auth_db.list_invites()
        return templates.TemplateResponse(
            "auth/invite_admin.html",
            {"request": request, "invites": invites, "new_code": None},
        )

    @app.post("/admin/invite", response_class=HTMLResponse)
    async def admin_create_invite(request: Request) -> Response:
        user = getattr(request.state, "user", None)
        if user is None or not user.is_admin:
            return RedirectResponse("/dashboard", status_code=303)
        new_code = auth_db.create_invite(created_by=user.id, expires_hours=168)
        invites = auth_db.list_invites()
        return templates.TemplateResponse(
            "auth/invite_admin.html",
            {"request": request, "invites": invites, "new_code": new_code},
        )

    # ------------------------------------------------------------------
    # Settings — user profile & API key
    # ------------------------------------------------------------------

    def _mask_api_key(key: str) -> str:
        """Show prefix + masked suffix so user can identify which key is set."""
        if not key:
            return ""
        if len(key) <= 10:
            return key[:3] + "****"
        return key[:7] + "****"

    def _coerce_value(val: str) -> bool | int | float | str:
        """Coerce form string to appropriate Python type."""
        if val == "":
            return ""
        if val.lower() in ("true", "on"):
            return True
        if val.lower() in ("false", "off"):
            return False
        try:
            if "." in val:
                return float(val)
            return int(val)
        except ValueError:
            return val

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request) -> HTMLResponse:
        user = getattr(request.state, "user", None)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        projects = getattr(request.state, "projects", [])
        masked_key = _mask_api_key(user.api_key)

        config_data = {}
        integrations_status = {}
        config_path = getattr(request.app.state, "config_path", None)
        if user.is_admin and config_path:
            from agents.config import resolve_env_vars
            from agents.config_writer import is_env_var, read_raw_config
            raw = read_raw_config(config_path)
            config_data = raw
            integ = raw.get("integrations", {})
            for key, val in integ.items():
                resolved = resolve_env_vars(str(val)) if is_env_var(str(val)) else str(val)
                integrations_status[key] = bool(resolved)

        saved = request.query_params.get("saved", "")
        error = request.query_params.get("error", "")

        return templates.TemplateResponse(
            "settings.html",
            {
                "request": request,
                "user": user,
                "masked_key": masked_key,
                "projects": projects,
                "config": config_data,
                "integrations_status": integrations_status,
                "saved": saved,
                "error": error,
            },
        )

    @app.post("/settings/account", response_class=HTMLResponse)
    async def settings_save_account(request: Request) -> Response:
        user = getattr(request.state, "user", None)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        form = await request.form()
        api_key = str(form.get("api_key", "")).strip()
        auth_db.update_api_key(user.id, api_key)
        return RedirectResponse("/settings?saved=account", status_code=303)

    @app.post("/settings/password", response_class=HTMLResponse)
    async def settings_change_password(request: Request) -> Response:
        user = getattr(request.state, "user", None)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        form = await request.form()
        current = str(form.get("current_password", ""))
        new = str(form.get("new_password", ""))
        if not current or not new:
            return RedirectResponse("/settings?error=password", status_code=303)
        ok = auth_db.change_password(user.username, current, new)
        if not ok:
            return RedirectResponse("/settings?error=password", status_code=303)
        return RedirectResponse("/settings?saved=password", status_code=303)

    @app.post("/settings/config", response_class=HTMLResponse)
    async def settings_save_config(request: Request) -> Response:
        user = getattr(request.state, "user", None)
        if user is None or not user.is_admin:
            return RedirectResponse("/settings", status_code=303)
        config_path = getattr(request.app.state, "config_path", None)
        if not config_path:
            return RedirectResponse("/settings?error=config", status_code=303)
        form = await request.form()
        updates: dict = {}
        for key, value in form.items():
            parts = key.split(".")
            if len(parts) == 2:
                section, field = parts
                updates.setdefault(section, {})[field] = _coerce_value(value)
        if updates:
            from agents.config_writer import write_config_values
            write_config_values(config_path, updates)
        return RedirectResponse("/settings?saved=config", status_code=303)
