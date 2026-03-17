"""Project Hub CRUD route registration (projects, tasks, sources)."""
from fastapi import FastAPI, HTTPException

from agents.app_state import AppState


def register_project_hub_routes(app: FastAPI, state: AppState) -> None:
    """Attach all /api project-hub endpoints to *app* using *state*."""

    # --- Projects ---

    @app.post("/api/projects", status_code=201)
    async def create_project(data: dict) -> dict:
        state.project_store.create_project(
            id=data["id"],
            name=data["name"],
            repo_path=data["repo_path"],
            default_branch=data.get("default_branch", "main"),
        )
        return state.project_store.get_project(data["id"])

    @app.get("/api/projects")
    async def list_projects_api() -> list[dict]:
        return state.project_store.list_projects()

    @app.get("/api/projects/{project_id}")
    async def get_project(project_id: str) -> dict:
        project = state.project_store.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    @app.put("/api/projects/{project_id}")
    async def update_project(project_id: str, data: dict) -> dict:
        state.project_store.update_project(project_id, **data)
        return state.project_store.get_project(project_id)

    @app.delete("/api/projects/{project_id}", status_code=204)
    async def delete_project_api(project_id: str) -> None:
        state.project_store.delete_project(project_id)

    # --- Tasks ---

    @app.post("/api/projects/{project_id}/tasks", status_code=201)
    async def create_task_api(project_id: str, data: dict) -> dict:
        task_id = state.project_store.create_task(project_id=project_id, **data)
        return state.project_store.get_task(task_id)

    @app.get("/api/projects/{project_id}/tasks")
    async def list_tasks_api(project_id: str) -> list[dict]:
        return state.project_store.list_tasks(project_id)

    @app.put("/api/tasks/{task_id}")
    async def update_task_api(task_id: str, data: dict) -> dict:
        state.project_store.update_task(task_id, **data)
        return state.project_store.get_task(task_id)

    @app.delete("/api/tasks/{task_id}", status_code=204)
    async def delete_task_api(task_id: str) -> None:
        state.project_store.delete_task(task_id)

    # --- Sources ---

    @app.post("/api/projects/{project_id}/sources", status_code=201)
    async def create_source_api(project_id: str, data: dict) -> dict:
        source_id = state.project_store.create_source(project_id=project_id, **data)
        sources = state.project_store.list_sources(project_id)
        return next(s for s in sources if s["id"] == source_id)

    @app.get("/api/projects/{project_id}/sources")
    async def list_sources_api(project_id: str) -> list[dict]:
        return state.project_store.list_sources(project_id)

    @app.delete("/api/sources/{source_id}", status_code=204)
    async def delete_source_api(source_id: str) -> None:
        state.project_store.delete_source(source_id)
