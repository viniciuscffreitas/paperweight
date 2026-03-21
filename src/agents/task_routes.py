"""API routes for work item (task) CRUD."""

from fastapi import FastAPI, Response

from agents.models import TaskStatus
from agents.task_store import TaskStore


def register_task_routes(app: FastAPI, task_store: TaskStore) -> None:
    @app.post("/api/work-items", status_code=201)
    async def create_work_item(data: dict) -> dict:
        status_str = data.get("status", "pending")
        status = TaskStatus(status_str)
        item = task_store.create(
            project=data["project"],
            title=data["title"],
            description=data.get("description", ""),
            source=data.get("source", "manual"),
            source_id=data.get("source_id", ""),
            source_url=data.get("source_url", ""),
            template=data.get("template"),
            status=status,
        )
        return item.model_dump(mode="json")

    @app.get("/api/work-items")
    async def list_work_items(project: str | None = None) -> list[dict]:
        items = task_store.list_by_project(project) if project else task_store.list_pending()
        return [i.model_dump(mode="json") for i in items]

    @app.get("/api/work-items/{item_id}", response_model=None)
    async def get_work_item(item_id: str) -> Response | dict:
        item = task_store.get(item_id)
        if item is None:
            return Response(status_code=404, content="Work item not found")
        return item.model_dump(mode="json")

    @app.patch("/api/work-items/{item_id}", response_model=None)
    async def update_work_item(item_id: str, data: dict) -> Response | dict:
        item = task_store.get(item_id)
        if item is None:
            return Response(status_code=404, content="Work item not found")
        status = data.get("status")
        if status:
            task_store.update_status(item_id, TaskStatus(status), pr_url=data.get("pr_url"))
        session_id = data.get("session_id")
        if session_id:
            task_store.update_session(item_id, session_id)
        title = data.get("title")
        if title:
            task_store.update_title(item_id, title)
        spec_path = data.get("spec_path")
        if spec_path is not None:
            task_store.update_spec_path(item_id, spec_path)
        updated = task_store.get(item_id)
        return updated.model_dump(mode="json")

    @app.post("/api/work-items/from-session", status_code=201, response_model=None)
    async def create_from_session(data: dict) -> dict | Response:
        """Create a work item from an active Agent Tab session."""
        title = data.get("title", "")
        description = data.get("description", title)
        project = data.get("project", "")
        session_id = data.get("session_id")
        if not title or not project:
            return Response(status_code=400, content="title and project required")
        item = task_store.create(
            project=project,
            title=title,
            description=description,
            source="agent-tab",
            session_id=session_id,
        )
        return item.model_dump(mode="json")

    @app.post("/api/work-items/{item_id}/rerun", response_model=None)
    async def rerun_work_item(item_id: str) -> Response | dict:
        item = task_store.get(item_id)
        if item is None:
            return Response(status_code=404, content="Work item not found")
        task_store.update_status(item_id, TaskStatus.PENDING)
        updated = task_store.get(item_id)
        return updated.model_dump(mode="json")
