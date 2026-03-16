import asyncio
import contextlib
import json as json_module
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Request, Response, WebSocket, WebSocketDisconnect

from agents.budget import BudgetManager
from agents.config import GlobalConfig, load_global_config, load_project_configs
from agents.executor import Executor
from agents.history import HistoryDB
from agents.models import ProjectConfig
from agents.notifier import Notifier
from agents.scheduler import create_scheduler, register_jobs
from agents.streaming import StreamEvent
from agents.webhooks.github import (
    extract_github_variables,
    match_github_event,
    verify_github_signature,
)
from agents.webhooks.linear import (
    extract_linear_variables,
    match_linear_event,
    verify_linear_signature,
)

logger = logging.getLogger(__name__)


class AppState:
    def __init__(
        self,
        projects: dict[str, ProjectConfig],
        executor: Executor,
        history: HistoryDB,
        budget: BudgetManager,
        notifier: Notifier,
        github_secret: str,
        linear_secret: str,
    ) -> None:
        self.projects = projects
        self.executor = executor
        self.history = history
        self.budget = budget
        self.notifier = notifier
        self.github_secret = github_secret
        self.linear_secret = linear_secret
        self._semaphore: asyncio.Semaphore | None = None
        self._repo_semaphores: dict[str, asyncio.Semaphore] = {}
        self.ws_clients: dict[str, set[WebSocket]] = {}
        self.ws_global_clients: set[WebSocket] = set()
        self.stream_queues: list[asyncio.Queue] = []
        self.run_events: dict[str, list[dict]] = {}

    def get_semaphore(self, max_concurrent: int) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(max_concurrent)
        return self._semaphore

    def get_repo_semaphore(self, repo: str) -> asyncio.Semaphore:
        if repo not in self._repo_semaphores:
            self._repo_semaphores[repo] = asyncio.Semaphore(2)
        return self._repo_semaphores[repo]


def create_app(
    config_path: Path | None = None,
    projects_dir: Path | None = None,
    data_dir: Path | None = None,
) -> FastAPI:
    base = Path(__file__).resolve().parent.parent.parent
    config_path = config_path or base / "config.yaml"
    projects_dir = projects_dir or base / "projects"
    data_dir = data_dir or base / "data"

    config: GlobalConfig = load_global_config(config_path)
    projects: dict[str, ProjectConfig] = load_project_configs(projects_dir)

    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "agents.db"

    history = HistoryDB(db_path)
    budget = BudgetManager(config=config.budget, history=history)
    notifier = Notifier(webhook_url=config.notifications.slack_webhook_url)

    async def broadcast_event(run_id: str, event: StreamEvent) -> None:
        msg = event.model_dump_json()
        dead: set[WebSocket] = set()
        for ws in set(state.ws_clients.get(run_id, set())):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        if run_id in state.ws_clients:
            state.ws_clients[run_id].difference_update(dead)

        dead_global: set[WebSocket] = set()
        for ws in set(state.ws_global_clients):
            try:
                await ws.send_text(json_module.dumps({"run_id": run_id, **event.model_dump()}))
            except Exception:
                dead_global.add(ws)
        state.ws_global_clients.difference_update(dead_global)

        event_data = {"run_id": run_id, **event.model_dump()}

        # Persist event to SQLite (durable across restarts)
        history.insert_event(run_id, event_data)

        # Keep in-memory cache for live streaming of active runs (cap at 500, last 100 runs)
        bucket = state.run_events.setdefault(run_id, [])
        if len(bucket) < 500:
            bucket.append(event_data)
        if len(state.run_events) > 100:
            oldest = next(iter(state.run_events))
            del state.run_events[oldest]

        for q in list(state.stream_queues):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(event_data)

    executor = Executor(
        config=config.execution,
        budget=budget,
        history=history,
        notifier=notifier,
        data_dir=data_dir,
        on_stream_event=broadcast_event,
    )

    state = AppState(
        projects=projects,
        executor=executor,
        history=history,
        budget=budget,
        notifier=notifier,
        github_secret=config.webhooks.github_secret,
        linear_secret=config.webhooks.linear_secret,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        history.mark_running_as_cancelled()
        scheduler = create_scheduler()

        async def scheduled_run(project_name: str, task_name: str) -> None:
            project = state.projects.get(project_name)
            if project and task_name in project.tasks:
                async with (
                    state.get_semaphore(config.execution.max_concurrent),
                    state.get_repo_semaphore(project.repo),
                ):
                    await state.executor.run_task(
                        project,
                        task_name,
                        trigger_type="schedule",
                        variables={
                            "date": datetime.now(UTC).strftime("%Y-%m-%d"),
                            "project_name": project_name,
                        },
                    )

        register_jobs(scheduler, state.projects, scheduled_run)
        scheduler.start()
        logger.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))
        yield
        scheduler.shutdown(wait=False)
        await state.executor.shutdown()
        logger.info("Shutdown complete")

    app = FastAPI(title="Background Agent Runner", lifespan=lifespan)
    app.state.app_state = state

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/status")
    async def status() -> dict[str, Any]:
        budget_status = state.budget.get_status()
        runs = state.history.list_runs_today()
        return {
            "budget": budget_status.model_dump(),
            "runs_today": [r.model_dump(mode="json") for r in runs],
            "projects": list(state.projects.keys()),
        }

    @app.get("/status/budget")
    async def budget_status() -> dict[str, Any]:
        s = state.budget.get_status()
        return {
            **s.model_dump(),
            "remaining_usd": s.remaining_usd,
        }

    @app.post("/tasks/{project_name}/{task_name}/run", status_code=202, response_model=None)
    async def manual_trigger(
        project_name: str,
        task_name: str,
        background_tasks: BackgroundTasks,
    ) -> Response | dict[str, str]:
        project = state.projects.get(project_name)
        if project is None:
            return Response(
                status_code=404,
                content=f"Project {project_name} not found",
            )
        if task_name not in project.tasks:
            return Response(
                status_code=404,
                content=f"Task {task_name} not found",
            )

        async def _run() -> None:
            async with (
                state.get_semaphore(config.execution.max_concurrent),
                state.get_repo_semaphore(project.repo),
            ):
                await state.executor.run_task(project, task_name, trigger_type="manual")

        background_tasks.add_task(_run)
        return {"run_id": f"{project_name}-{task_name}", "status": "enqueued"}

    @app.post("/webhooks/github", response_model=None)
    async def github_webhook(
        request: Request,
        background_tasks: BackgroundTasks,
    ) -> Response | dict[str, str]:
        body = await request.body()
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not verify_github_signature(body, signature, state.github_secret):
            return Response(status_code=401, content="Invalid signature")
        event_type = request.headers.get("X-GitHub-Event", "")
        payload = await request.json()
        action = payload.get("action")
        for project in state.projects.values():
            for task_name, task in project.tasks.items():
                if match_github_event(event_type, action, payload, task):
                    variables = extract_github_variables(event_type, payload)

                    async def _run(
                        p: ProjectConfig = project,
                        tn: str = task_name,
                        v: dict[str, str] = variables,
                    ) -> None:
                        async with (
                            state.get_semaphore(config.execution.max_concurrent),
                            state.get_repo_semaphore(p.repo),
                        ):
                            await state.executor.run_task(p, tn, trigger_type="github", variables=v)

                    background_tasks.add_task(_run)
        return {"status": "processed"}

    @app.post("/webhooks/linear", response_model=None)
    async def linear_webhook(
        request: Request,
        background_tasks: BackgroundTasks,
    ) -> Response | dict[str, str]:
        body = await request.body()
        signature = request.headers.get("Linear-Signature", "")
        if state.linear_secret and not verify_linear_signature(
            body, signature, state.linear_secret
        ):
            return Response(status_code=401, content="Invalid signature")
        payload = await request.json()
        event_type = payload.get("type", "")
        action = payload.get("action", "")
        for project in state.projects.values():
            for task_name, task in project.tasks.items():
                if match_linear_event(event_type, action, payload, task):
                    variables = extract_linear_variables(payload)

                    async def _run(
                        p: ProjectConfig = project,
                        tn: str = task_name,
                        v: dict[str, str] = variables,
                    ) -> None:
                        async with (
                            state.get_semaphore(config.execution.max_concurrent),
                            state.get_repo_semaphore(p.repo),
                        ):
                            await state.executor.run_task(p, tn, trigger_type="linear", variables=v)

                    background_tasks.add_task(_run)
        return {"status": "processed"}

    @app.post("/runs/{run_id}/cancel", response_model=None)
    async def cancel_run(run_id: str) -> Response | dict[str, str]:
        cancelled = await state.executor.cancel_run(run_id)
        if not cancelled:
            return Response(status_code=404, content="Run not found or not running")
        return {"status": "cancelled"}

    @app.websocket("/ws/runs/{run_id}")
    async def ws_run(websocket: WebSocket, run_id: str) -> None:
        await websocket.accept()
        state.ws_clients.setdefault(run_id, set()).add(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            state.ws_clients.get(run_id, set()).discard(websocket)

    @app.websocket("/ws/runs")
    async def ws_all_runs(websocket: WebSocket) -> None:
        await websocket.accept()
        state.ws_global_clients.add(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            state.ws_global_clients.discard(websocket)

    from agents.dashboard import setup_dashboard

    setup_dashboard(app, state, config)

    return app


def run() -> None:
    import uvicorn

    base = Path.cwd()
    config = load_global_config(base / "config.yaml")
    app = create_app(
        config_path=base / "config.yaml",
        projects_dir=base / "projects",
        data_dir=base / "data",
    )
    uvicorn.run(app, host=config.server.host, port=config.server.port)
