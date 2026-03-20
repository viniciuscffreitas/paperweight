"""API routes for work item (task) CRUD."""
from fastapi import FastAPI, Response

from agents.models import TaskStatus
from agents.task_store import TaskStore


def register_task_routes(app: FastAPI, task_store: TaskStore) -> None:
    @app.post("/api/work-items", status_code=201)
    async def create_work_item(data: dict) -> dict:
        item = task_store.create(
            project=data["project"],
            title=data["title"],
            description=data.get("description", ""),
            source=data.get("source", "manual"),
            source_id=data.get("source_id", ""),
            source_url=data.get("source_url", ""),
            template=data.get("template"),
        )
        return item.model_dump(mode="json")

    @app.get("/api/work-items")
    async def list_work_items(project: str | None = None) -> list[dict]:
        if project:
            items = task_store.list_by_project(project)
        else:
            items = task_store.list_pending()
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
        updated = task_store.get(item_id)
        return updated.model_dump(mode="json")

    @app.post("/api/work-items/{item_id}/rerun", response_model=None)
    async def rerun_work_item(item_id: str) -> Response | dict:
        item = task_store.get(item_id)
        if item is None:
            return Response(status_code=404, content="Work item not found")
        task_store.update_status(item_id, TaskStatus.PENDING)
        updated = task_store.get(item_id)
        return updated.model_dump(mode="json")
