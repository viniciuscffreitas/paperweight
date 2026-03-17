"""Project Hub CRUD route registration (projects, tasks, sources)."""
from fastapi import FastAPI, HTTPException

from agents.app_state import AppState


async def _discover_sources(name: str, state: AppState) -> list[dict]:
    """Run auto-discovery across all configured integrations."""
    results: list[dict] = []
    query = name.lower().replace(" ", "").replace("-", "")

    # Linear discovery
    if hasattr(state, "linear_client") and state.linear_client:
        try:
            teams = await state.linear_client.fetch_teams()
            for team_name, team_id in teams.items():
                if query in team_name.replace("-", "").replace(" ", ""):
                    norm = team_name.replace("-", "").replace(" ", "")
                    results.append({
                        "source_type": "linear",
                        "source_id": team_id,
                        "source_name": f"Team: {team_name}",
                        "confidence": "high" if query == norm else "medium",
                    })
        except Exception:
            pass

    # GitHub discovery
    if hasattr(state, "github_client") and state.github_client:
        try:
            repos = await state.github_client.search_repos("", name)
            for repo in repos[:5]:
                full_name = repo.get("full_name", "")
                confidence = (
                    "high" if query in full_name.lower().replace("-", "") else "medium"
                )
                results.append({
                    "source_type": "github",
                    "source_id": full_name,
                    "source_name": f"Repo: {repo.get('name', '')}",
                    "confidence": confidence,
                })
        except Exception:
            pass

    # Slack discovery
    if hasattr(state, "slack_bot_client") and state.slack_bot_client:
        try:
            channels = await state.slack_bot_client.search_channels_by_name(name)
            for ch in channels[:5]:
                results.append({
                    "source_type": "slack",
                    "source_id": ch["id"],
                    "source_name": f"#{ch['name']}",
                    "confidence": "high" if query in ch["name"].replace("-", "") else "medium",
                })
        except Exception:
            pass

    return results


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

    # --- Run Launcher ---

    @app.post("/api/projects/{project_id}/run", status_code=202)
    async def launch_run(project_id: str, data: dict) -> dict:
        project = state.project_store.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        # For now, return a placeholder — full executor integration will come later
        return {
            "project_id": project_id,
            "status": "accepted",
            "mode": "adhoc" if data.get("adhoc") else "task",
        }

    # --- Events Feed ---

    @app.get("/api/projects/{project_id}/events")
    async def list_events_api(
        project_id: str, source: str | None = None, limit: int = 100
    ) -> list[dict]:
        return state.project_store.list_events(project_id, source=source, limit=limit)

    # --- Auto-discovery ---

    @app.post("/api/discover")
    async def discover_sources(data: dict) -> list[dict]:
        return await _discover_sources(data.get("name", ""), state)
