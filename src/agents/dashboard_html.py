"""HTMX + Jinja2 dashboard — replaces NiceGUI dashboard*.py files."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
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
