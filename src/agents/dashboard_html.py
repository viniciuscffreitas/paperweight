"""HTMX + Jinja2 dashboard — replaces NiceGUI dashboard*.py files."""
from __future__ import annotations

import re
import time as _time
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

if TYPE_CHECKING:
    from fastapi import FastAPI

    from agents.app_state import AppState
    from agents.config import GlobalConfig

_BASE = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=_BASE / "templates")


def setup_dashboard(app: FastAPI, state: AppState, config: GlobalConfig) -> None:
    """Mount static files and register all HTML routes."""
    app.mount("/static", StaticFiles(directory=_BASE / "static"), name="static")

    @app.get("/")
    async def root_redirect() -> RedirectResponse:
        return RedirectResponse("/dashboard", status_code=302)

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard_page(request: Request) -> HTMLResponse:
        projects = state.project_store.list_projects() if state.project_store else []
        runs = []
        try:
            from agents.dashboard_formatters import build_history_rows
            runs = build_history_rows(state.history.list_runs_today())
        except Exception:
            pass
        return _TEMPLATES.TemplateResponse(
            request,
            "dashboard.html",
            {"projects": projects, "runs": runs},
        )

    @app.get("/hub/{project_id}", response_class=HTMLResponse)
    async def hub_panel(request: Request, project_id: str) -> HTMLResponse:
        project = state.project_store.get_project(project_id) if state.project_store else None
        if not project:
            return HTMLResponse("<p>Project not found</p>", status_code=404)
        return _TEMPLATES.TemplateResponse(
            request,
            "hub/panel.html",
            {"project": project, "id": project_id},
        )

    @app.get("/hub/{project_id}/activity", response_class=HTMLResponse)
    async def hub_activity(request: Request, project_id: str) -> HTMLResponse:
        project = state.project_store.get_project(project_id) if state.project_store else None
        if not project:
            return HTMLResponse("<p>Project not found</p>", status_code=404)
        events = state.project_store.list_events(project_id, limit=50)
        return _TEMPLATES.TemplateResponse(
            request,
            "hub/activity.html",
            {"events": events, "id": project_id},
        )

    @app.get("/hub/{project_id}/tasks", response_class=HTMLResponse)
    async def hub_tasks(request: Request, project_id: str) -> HTMLResponse:
        project = state.project_store.get_project(project_id) if state.project_store else None
        if not project:
            return HTMLResponse("<p>Project not found</p>", status_code=404)
        tasks = state.project_store.list_tasks(project_id)
        return _TEMPLATES.TemplateResponse(
            request,
            "hub/tasks.html",
            {"tasks": tasks, "id": project_id},
        )

    @app.post("/setup/discover", response_class=HTMLResponse)
    async def setup_discover(request: Request) -> HTMLResponse:
        from agents.project_hub_routes import _discover_sources
        form = await request.form()
        name = str(form.get("name", ""))
        repo_path = str(form.get("repo_path", ""))
        sources = await _discover_sources(name, state) if state.project_store else []
        return _TEMPLATES.TemplateResponse(
            request,
            "setup/step2.html",
            {"sources": sources, "name": name, "repo_path": repo_path},
        )

    @app.post("/setup/create")
    async def setup_create(request: Request) -> Response:
        if not state.project_store:
            return Response(status_code=503, content="Store unavailable")
        form = await request.form()
        name = str(form.get("name", ""))
        repo_path = str(form.get("repo_path", ""))
        project_id = re.sub(r"[^a-z0-9-]", "-", name.lower().strip()).strip("-") or "project"
        if state.project_store.get_project(project_id):
            project_id = f"{project_id}-{int(_time.time()) % 10000}"
        state.project_store.create_project(
            id=project_id,
            name=name,
            repo_path=repo_path,
        )
        for source_str in form.getlist("source"):
            parts = source_str.split("|", 2)
            if len(parts) == 3:
                state.project_store.create_source(
                    project_id=project_id,
                    source_type=parts[0],
                    source_id=parts[1],
                    source_name=parts[2],
                )
        response = Response(status_code=204)
        response.headers["HX-Redirect"] = "/dashboard"
        return response

    @app.get("/hub/{project_id}/runs", response_class=HTMLResponse)
    async def hub_runs(request: Request, project_id: str) -> HTMLResponse:
        project = state.project_store.get_project(project_id) if state.project_store else None
        if not project:
            return HTMLResponse("<p>Project not found</p>", status_code=404)
        try:
            all_runs = state.history.list_runs_today()
            runs = [r for r in all_runs if r.project == project_id][:20]
        except Exception:
            runs = []
        return _TEMPLATES.TemplateResponse(
            request,
            "hub/runs.html",
            {"runs": runs, "id": project_id},
        )

    # --- Coordination routes ---

    @app.get("/coordination", response_class=HTMLResponse)
    async def coordination_page(request: Request) -> HTMLResponse:
        if state.broker:
            snapshot = state.broker.get_coordination_snapshot()
        else:
            snapshot = {"claims": [], "mediations": [], "active_runs": 0,
                        "contested_count": 0, "mediating_count": 0, "timeline": []}
        projects = state.project_store.list_projects() if state.project_store else []
        return _TEMPLATES.TemplateResponse(
            request,
            "coordination.html",
            {
                "projects": projects,
                "snapshot": snapshot,
                "current_path": "/coordination",
            },
        )

    @app.get("/coordination/claims", response_class=HTMLResponse)
    async def coordination_claims(request: Request) -> HTMLResponse:
        claims = []
        if state.broker:
            snapshot = state.broker.get_coordination_snapshot()
            claims = snapshot["claims"]
        return _TEMPLATES.TemplateResponse(
            request,
            "coordination/claims.html",
            {"claims": claims},
        )

    @app.get("/coordination/mediations", response_class=HTMLResponse)
    async def coordination_mediations(request: Request) -> HTMLResponse:
        mediations = []
        if state.broker:
            snapshot = state.broker.get_coordination_snapshot()
            mediations = snapshot["mediations"]
        return _TEMPLATES.TemplateResponse(
            request,
            "coordination/mediations.html",
            {"mediations": mediations},
        )

    @app.get("/coordination/timeline", response_class=HTMLResponse)
    async def coordination_timeline(request: Request) -> HTMLResponse:
        timeline = []
        if state.broker:
            snapshot = state.broker.get_coordination_snapshot()
            timeline = snapshot["timeline"]
            from datetime import UTC, datetime
            for e in timeline:
                dt = datetime.fromtimestamp(e["timestamp"], tz=UTC)
                e["time_str"] = dt.strftime("%H:%M:%S")
        return _TEMPLATES.TemplateResponse(
            request,
            "coordination/timeline.html",
            {"timeline": timeline},
        )

    @app.post("/set-theme")
    async def set_theme(response: Response, theme: str = Form(...)) -> dict:
        if theme not in ("light", "dark"):
            raise HTTPException(status_code=422, detail="Invalid theme value")
        response.set_cookie(
            "theme", theme,
            max_age=31_536_000, path="/",
            httponly=True, samesite="lax",
        )
        return {"ok": True}
