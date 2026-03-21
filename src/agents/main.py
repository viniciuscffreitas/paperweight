import asyncio
import contextlib
import json as json_module
import logging
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Request, Response, WebSocket, WebSocketDisconnect

from agents.app_state import AppState
from agents.budget import BudgetManager
from agents.config import GlobalConfig, load_global_config, load_project_configs
from agents.executor import Executor
from agents.history import HistoryDB
from agents.lifespan import create_lifespan
from agents.models import ProjectConfig
from agents.notifier import Notifier
from agents.project_store import ProjectStore
from agents.streaming import StreamEvent

logger = logging.getLogger(__name__)


class JSONFormatter(logging.Formatter):
    """JSON log formatter for production use. Enable via LOG_FORMAT=json."""

    def format(self, record: logging.LogRecord) -> str:
        return json_module.dumps(
            {
                "ts": self.formatTime(record),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
                "module": record.module,
                **({"exc": self.formatException(record.exc_info)} if record.exc_info else {}),
            }
        )


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
    project_store = ProjectStore(data_dir / "project_hub.db")

    from agents.session_manager import SessionManager

    session_manager = SessionManager(db_path, worktree_base=config.execution.worktree_base)

    from agents.task_store import TaskStore

    task_store = TaskStore(db_path)

    from agents.aggregator import AggregatorService
    from agents.discord_notifier import DiscordRunNotifier
    from agents.github_client import GitHubClient
    from agents.linear_client import LinearClient
    from agents.slack_client import SlackBotClient

    linear_client = None
    discord_notifier_client = None
    if config.integrations.linear_api_key:
        linear_client = LinearClient(api_key=config.integrations.linear_api_key)
    if config.integrations.discord_bot_token:
        discord_notifier_client = DiscordRunNotifier(
            bot_token=config.integrations.discord_bot_token
        )

    github_client = None
    if config.integrations.github_token:
        github_client = GitHubClient(config.integrations.github_token)

    slack_bot_client = None
    if config.integrations.slack_bot_token:
        slack_bot_client = SlackBotClient(config.integrations.slack_bot_token)

    aggregator = AggregatorService(
        store=project_store,
        linear_client=linear_client,
        github_client=github_client,
        slack_client=slack_bot_client,
    )

    from agents.notification_engine import NotificationEngine

    notification_engine = NotificationEngine(
        store=project_store,
        slack_notifier=notifier,
        discord_notifier=discord_notifier_client,
    )

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

        # Close WebSocket connections when run finishes
        if event.type in ("task_completed", "task_failed"):
            for ws in set(state.ws_clients.get(run_id, set())):
                with contextlib.suppress(Exception):
                    await ws.close()
            state.ws_clients.pop(run_id, None)
            state.run_events.pop(run_id, None)

        dead_global: set[WebSocket] = set()
        for ws in set(state.ws_global_clients):
            try:
                await ws.send_text(json_module.dumps({"run_id": run_id, **event.model_dump()}))
            except Exception:
                dead_global.add(ws)
        state.ws_global_clients.difference_update(dead_global)

        event_data = {"run_id": run_id, **event.model_dump()}

        # Persist event to SQLite without blocking the event loop
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, history.insert_event, run_id, event_data)

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

        # Coordination: forward event to broker for claim tracking
        if state.broker:
            worktree_path = Path(config.execution.worktree_base) / run_id
            await state.broker.on_stream_event(
                run_id,
                event,
                worktree_root=worktree_path if worktree_path.exists() else None,
            )

    # Coordination broker (created before executor so it can be passed)
    from agents.coordination.broker import CoordinationBroker

    broker: CoordinationBroker | None = None
    if config.coordination.enabled:
        broker = CoordinationBroker(config.coordination)

    executor = Executor(
        config=config.execution,
        budget=budget,
        history=history,
        notifier=notifier,
        data_dir=data_dir,
        on_stream_event=broadcast_event,
        linear_client=linear_client,
        discord_notifier=discord_notifier_client,
        broker=broker,
    )

    state = AppState(
        projects=projects,
        executor=executor,
        history=history,
        budget=budget,
        notifier=notifier,
        github_secret=config.webhooks.github_secret,
        linear_secret=config.webhooks.linear_secret,
        project_store=project_store,
        github_client=github_client,
        slack_bot_client=slack_bot_client,
        aggregator=aggregator,
        broker=broker,
        session_manager=session_manager,
        task_store=task_store,
    )

    lifespan = create_lifespan(
        history=history,
        config=config,
        projects=projects,
        task_store=task_store,
        state=state,
        session_manager=session_manager,
        project_store=project_store,
        aggregator=aggregator,
        notification_engine=notification_engine,
        notifier=notifier,
        linear_client=linear_client,
        discord_notifier_client=discord_notifier_client,
        data_dir=data_dir,
        broker=broker,
    )

    app = FastAPI(title="Background Agent Runner", lifespan=lifespan)
    app.state.app_state = state
    app.state.config_path = config_path
    app.state.project_store = state.project_store

    from agents.auth_middleware import register_auth_middleware

    register_auth_middleware(app)

    from agents.rate_limit import RateLimiter

    _rate_limiter = RateLimiter(max_requests=120, window_seconds=60)

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next: object) -> Response:
        path = request.url.path
        if path.startswith("/ws/") or path == "/health" or path.startswith("/static/"):
            return await call_next(request)
        client_ip = request.client.host if request.client else "unknown"
        if not _rate_limiter.is_allowed(client_ip):
            return Response(status_code=429, content="Too many requests")
        return await call_next(request)

    # --- Core routes ---

    @app.get("/health")
    async def health() -> Response:
        components: dict[str, str] = {}
        overall = "ok"

        # DB check
        try:
            history.total_cost_today()
            components["db"] = "ok"
        except Exception as e:
            components["db"] = f"error: {e}"
            overall = "degraded"

        # Disk check (data dir writable)
        try:
            probe = data_dir / ".health_probe"
            probe.write_text("ok")
            probe.unlink()
            components["disk"] = "ok"
        except Exception:
            components["disk"] = "error: data dir not writable"
            overall = "degraded"

        # Scheduler check
        try:
            sched = getattr(app.state, "scheduler", None)
            job_count = len(sched.get_jobs()) if sched else 0
            components["scheduler"] = f"ok ({job_count} jobs)"
        except Exception:
            components["scheduler"] = "error"
            overall = "degraded"

        status_code = 200 if overall == "ok" else 503
        return Response(
            content=json_module.dumps({"status": overall, "components": components}),
            status_code=status_code,
            media_type="application/json",
        )

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
        return {**s.model_dump(), "remaining_usd": s.remaining_usd}

    @app.post("/tasks/{project_name}/{task_name}/run", status_code=202, response_model=None)
    async def manual_trigger(
        project_name: str,
        task_name: str,
        background_tasks: BackgroundTasks,
    ) -> Response | dict[str, str]:
        project = state.projects.get(project_name)
        if project is None:
            return Response(status_code=404, content=f"Project {project_name} not found")
        if task_name not in project.tasks:
            return Response(status_code=404, content=f"Task {task_name} not found")

        async def _run() -> None:
            async with (
                state.get_semaphore(config.execution.max_concurrent),
                state.get_repo_semaphore(project.repo),
            ):
                await state.executor.run_task(project, task_name, trigger_type="manual")

        background_tasks.add_task(_run)
        return {"run_id": f"{project_name}-{task_name}", "status": "enqueued"}

    @app.post("/runs/{run_id}/cancel", response_model=None)
    async def cancel_run(run_id: str) -> Response | dict[str, str]:
        cancelled = await state.executor.cancel_run(run_id)
        if not cancelled:
            return Response(status_code=404, content="Run not found or not running")
        return {"status": "cancelled"}

    from agents.agent_routes import register_agent_routes

    register_agent_routes(app, state, config)

    from agents.task_routes import register_task_routes

    register_task_routes(app, task_store)

    # --- Webhook routes ---

    from agents.webhook_routes import register_webhook_routes

    register_webhook_routes(app, state, config, linear_client)

    # --- WebSocket routes ---

    @app.websocket("/ws/runs/{run_id}")
    async def ws_run(websocket: WebSocket, run_id: str) -> None:
        await websocket.accept()
        # Register BEFORE replay so live events are not missed
        state.ws_clients.setdefault(run_id, set()).add(websocket)
        # Replay cached events so client sees events emitted before connection
        for cached in state.run_events.get(run_id, []):
            try:
                await websocket.send_text(json_module.dumps(cached))
            except WebSocketDisconnect:
                state.ws_clients.get(run_id, set()).discard(websocket)
                return
            except Exception:
                logger.warning("Failed to replay cached event for run %s", run_id)
                state.ws_clients.get(run_id, set()).discard(websocket)
                return
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

    @app.get("/api/metrics")
    async def api_metrics() -> dict:
        from agents.metrics import collect_metrics

        return collect_metrics(state.history, days=7)

    @app.post("/api/migrate-yaml")
    async def migrate_yaml() -> dict[str, int]:
        from agents.migration import migrate_yaml_projects

        count = migrate_yaml_projects(state.projects, state.project_store)
        return {"migrated": count}

    from agents.project_hub_routes import register_project_hub_routes

    register_project_hub_routes(app, state)

    from agents.dashboard_html import setup_dashboard

    setup_dashboard(app, state, config)

    return app


def run() -> None:
    import uvicorn
    from dotenv import load_dotenv

    load_dotenv()

    import os as _os

    log_format = _os.environ.get("LOG_FORMAT", "text")
    log_level = _os.environ.get("LOG_LEVEL", "INFO").upper()

    if log_format == "json":
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logging.root.handlers = [handler]

    logging.root.setLevel(getattr(logging, log_level, logging.INFO))

    base = Path.cwd()
    config = load_global_config(base / "config.yaml")
    app = create_app(
        config_path=base / "config.yaml",
        projects_dir=base / "projects",
        data_dir=base / "data",
    )
    uvicorn.run(app, host=config.server.host, port=config.server.port)
