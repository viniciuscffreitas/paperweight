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


def _find_related_docs(
    item: object, session: object | None,
) -> str:
    """Search for spec/plan docs related to a task in repo and worktree."""
    title_slug = re.sub(r"[^a-z0-9]+", "-", getattr(item, "title", "").lower()).strip("-")
    search_dirs: list[Path] = []
    # Check worktree if session exists
    if session and hasattr(session, "worktree_path"):
        wt = Path(session.worktree_path)
        search_dirs.append(wt / "docs" / "superpowers" / "specs")
        search_dirs.append(wt / "docs" / "superpowers" / "plans")
    for d in search_dirs:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.md"), reverse=True):
            # Match by title slug overlap
            fname = f.stem.lower()
            words = [w for w in title_slug.split("-") if len(w) > 2]
            if any(w in fname for w in words):
                try:
                    return f.read_text(encoding="utf-8")
                except Exception:
                    continue
    return ""


def setup_dashboard(app: FastAPI, state: AppState, config: GlobalConfig) -> None:
    """Mount static files and register all HTML routes."""
    app.mount("/static", StaticFiles(directory=_BASE / "static"), name="static")

    @app.get("/")
    async def root_redirect() -> RedirectResponse:
        return RedirectResponse("/dashboard", status_code=302)

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard_page(request: Request) -> HTMLResponse:
        projects = state.project_store.list_projects() if state.project_store else []
        if projects:
            return RedirectResponse(f"/hub/{projects[0]['id']}/tasks", status_code=302)
        # No projects — show empty state with sidebar + wizard CTA
        return _TEMPLATES.TemplateResponse(
            request,
            "project-picker.html",
            {"projects": projects},
        )

    @app.get("/hub/{project_id}", response_class=HTMLResponse)
    async def hub_panel(request: Request, project_id: str) -> HTMLResponse:
        return RedirectResponse(f"/hub/{project_id}/tasks", status_code=302)

    @app.get("/hub/{project_id}/activity", response_class=HTMLResponse)
    async def hub_activity(request: Request, project_id: str) -> HTMLResponse:
        return RedirectResponse(f"/hub/{project_id}/tasks", status_code=302)

    @app.get("/hub/{project_id}/tasks", response_class=HTMLResponse)
    async def hub_tasks(request: Request, project_id: str) -> HTMLResponse:
        project = state.project_store.get_project(project_id) if state.project_store else None
        if not project:
            return HTMLResponse("<p>Project not found</p>", status_code=404)
        work_items = state.task_store.list_by_project(project_id) if state.task_store else []
        # Build counts
        counts = {'running': 0, 'review': 0, 'queued': 0, 'done': 0}
        for item in work_items:
            s = item.status
            if s == 'running':
                counts['running'] += 1
            elif s == 'review':
                counts['review'] += 1
            elif s in ('pending', 'draft'):
                counts['queued'] += 1
            elif s in ('done', 'failed'):
                counts['done'] += 1
        # Task templates (for potential use)
        tasks = []
        if state.project_store:
            tasks = state.project_store.list_tasks(project_id)
        projects = state.project_store.list_projects() if state.project_store else []
        return _TEMPLATES.TemplateResponse(
            request,
            "tasks.html",
            {
                "projects": projects,
                "selected_project": project_id,
                "project_name": project["name"],
                "id": project_id,
                "work_items": work_items,
                "tasks": tasks,
                "counts": counts,
                "budget_spent": 0,
                "budget_total": 0,
            },
        )

    @app.get("/hub/{project_id}/task/{item_id}", response_class=HTMLResponse)
    async def hub_task_detail(request: Request, project_id: str, item_id: str) -> HTMLResponse:
        item = state.task_store.get(item_id) if state.task_store else None
        if not item:
            return HTMLResponse("<p>Task not found</p>", status_code=404)
        session = None
        if item.session_id and hasattr(state, "session_manager") and state.session_manager:
            session = state.session_manager.get_session(item.session_id)
        project = state.project_store.get_project(project_id) if state.project_store else None
        projects = state.project_store.list_projects() if state.project_store else []
        # Find related spec/plan docs
        spec_content = _find_related_docs(item, session)
        return _TEMPLATES.TemplateResponse(
            request,
            "task-detail.html",
            {
                "item": item,
                "session": session,
                "id": project_id,
                "projects": projects,
                "selected_project": project_id,
                "project_name": project["name"] if project else project_id,
                "spec_content": spec_content,
            },
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
            "setup/wizard.html",
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
        sessions = []
        if hasattr(state, "session_manager") and state.session_manager:
            sessions = state.session_manager.list_sessions_with_stats(project_id)
        projects = state.project_store.list_projects() if state.project_store else []
        return _TEMPLATES.TemplateResponse(
            request,
            "sessions.html",
            {
                "projects": projects,
                "selected_project": project_id,
                "project_name": project["name"],
                "id": project_id,
                "sessions": sessions,
            },
        )

    @app.get("/hub/{project_id}/agent", response_class=HTMLResponse)
    async def hub_agent(
        request: Request, project_id: str, session: str | None = None, run: str | None = None,
    ) -> HTMLResponse:
        project = state.project_store.get_project(project_id) if state.project_store else None
        if not project:
            return HTMLResponse("<p>Project not found</p>", status_code=404)
        active_session = None
        if hasattr(state, "session_manager") and state.session_manager:
            if session:
                active_session = state.session_manager.get_session(session)
            else:
                active_session = state.session_manager.get_active_session(project_id)
        task_id = request.query_params.get("task", "")
        task = None
        if task_id and state.task_store:
            task = state.task_store.get(task_id)
            # If task has a session, use it
            has_sm = hasattr(state, "session_manager") and state.session_manager
            if task and task.session_id and has_sm:
                active_session = state.session_manager.get_session(task.session_id)
        return _TEMPLATES.TemplateResponse(
            request,
            "hub/agent.html",
            {"id": project_id, "session": active_session, "focus_run": run or "", "task": task},
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
