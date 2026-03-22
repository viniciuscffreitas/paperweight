"""Profile routes — user account, API key, password, avatar."""

import base64
import logging

from fastapi import FastAPI, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from agents.auth import AuthDB, mask_api_key

logger = logging.getLogger(__name__)

_AVATAR_MAX_BYTES = 512 * 1024

# Magic-byte signatures for allowed image types.
# We detect from file content, NOT from the client-supplied Content-Type,
# to prevent trivially bypassing the check by forging the MIME header.
_MAGIC_JPEG = b"\xff\xd8\xff"
_MAGIC_PNG = b"\x89PNG\r\n\x1a\n"


def _detect_image_mime(data: bytes) -> str | None:
    """Return the MIME type inferred from magic bytes, or None if not a supported image."""
    if data[:3] == _MAGIC_JPEG:
        return "image/jpeg"
    if data[:8] == _MAGIC_PNG:
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


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
            request,
            "profile.html",
            {
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

    @app.post("/profile/avatar", response_class=HTMLResponse)
    async def profile_upload_avatar(request: Request, avatar: UploadFile) -> Response:
        user = getattr(request.state, "user", None)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        data = await avatar.read()
        if len(data) > _AVATAR_MAX_BYTES:
            return RedirectResponse("/profile?error=avatar_size", status_code=303)
        # Validate by inspecting file magic bytes, not client-supplied Content-Type.
        mime = _detect_image_mime(data)
        if mime is None:
            return RedirectResponse("/profile?error=avatar_type", status_code=303)
        encoded = base64.b64encode(data).decode()
        data_uri = f"data:{mime};base64,{encoded}"
        auth_db.update_avatar(user.id, data_uri)
        return RedirectResponse("/profile?saved=avatar", status_code=303)
