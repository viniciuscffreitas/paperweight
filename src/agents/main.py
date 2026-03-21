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

from agents.app_state import AppState
from agents.budget import BudgetManager
from agents.config import GlobalConfig, load_global_config, load_project_configs
from agents.executor import Executor
from agents.history import HistoryDB
from agents.models import ProjectConfig, RunStatus
from agents.notifier import Notifier
from agents.project_store import ProjectStore
from agents.scheduler import create_scheduler, register_jobs
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

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        history.mark_running_as_cancelled()

        # Reset orphaned work items left as 'running' from a previous crash
        reset_count = task_store.reset_running_to_pending()
        if reset_count:
            logger.info("Reset %d orphaned running task(s) to pending", reset_count)

        from agents.discovery import auto_discover_project_ids

        await auto_discover_project_ids(
            projects,
            linear_client,
            discord_notifier_client,
            config.integrations.discord_guild_id,
        )

        from agents.migration import migrate_yaml_projects

        _migrated = migrate_yaml_projects(projects, project_store)
        if _migrated:
            logger.info("Auto-migrated %d YAML project(s) to SQLite", _migrated)

        scheduler = create_scheduler()

        async def scheduled_run(project_name: str, task_name: str) -> None:
            project = state.projects.get(project_name)
            if project and task_name in project.tasks:
                task = project.tasks[task_name]
                from agents.config import build_prompt

                prompt = build_prompt(
                    task,
                    {"date": datetime.now(UTC).strftime("%Y-%m-%d"), "project_name": project_name},
                )
                if state.task_store:
                    state.task_store.create(
                        project=project_name,
                        title=f"{project_name}/{task_name}",
                        description=prompt,
                        source="schedule",
                        template=task_name,
                    )
                    logger.info("Scheduled task created: %s/%s", project_name, task_name)
                else:
                    # Fallback: direct execution if TaskStore not available
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

        async def run_daily_digest() -> None:
            for project in project_store.list_projects():
                await notification_engine.send_digest(project["id"])
            # Overnight run summary
            overnight = notification_engine.build_overnight_digest(history, hours=12)
            if overnight:
                await notifier.send_text(overnight)

        async def cleanup_old_events() -> None:
            deleted = project_store.cleanup_old_events(days=90)
            if deleted:
                logger.info("Cleaned up %d old events", deleted)

        async def cleanup_sessions() -> None:
            cleaned = session_manager.cleanup_stale_sessions(30)
            if cleaned:
                logger.info("Cleaned up %d stale agent sessions", cleaned)

        async def poll_linear_issues() -> None:
            """Fallback: poll Linear for agent issues missed by webhooks."""
            if not linear_client:
                return
            for project in state.projects.values():
                if not project.linear_team_id or "issue-resolver" not in project.tasks:
                    continue
                try:
                    raw_issues = await linear_client.fetch_team_issues(project.linear_team_id)
                    for issue in raw_issues:
                        issue_id = issue.get("id", "")
                        existing = state.history.find_run_by_issue_id(issue_id)
                        if existing and existing.status in (RunStatus.RUNNING, RunStatus.SUCCESS):
                            continue
                        # Check if issue has agent label via full fetch
                        full = await linear_client.fetch_issue(issue_id)
                        if "agent" not in full.get("labels", []):
                            continue
                        state_name = full.get("state", "").lower()
                        if state_name in ("done", "cancelled", "canceled"):
                            continue
                        logger.info("Polling: found unprocessed agent issue %s", issue_id)
                        if state.task_store and not state.task_store.exists_by_source(
                            "linear", issue_id
                        ):
                            state.task_store.create(
                                project=project.name,
                                title=full.get("title", "Linear issue"),
                                description=full.get("description", ""),
                                source="linear",
                                source_id=issue_id,
                                template="issue-resolver",
                            )
                            logger.info("Polling: created task for issue %s", issue_id)
                except Exception:
                    logger.warning("Polling failed for project %s", project.name)

        register_jobs(scheduler, state.projects, scheduled_run)
        scheduler.add_job(poll_linear_issues, "interval", minutes=15, id="poll_linear_issues")
        scheduler.add_job(run_daily_digest, "cron", hour=9, minute=0, id="daily_digest")
        scheduler.add_job(cleanup_old_events, "cron", hour=3, minute=0, id="event_cleanup")
        scheduler.add_job(cleanup_sessions, "interval", minutes=10, id="session_cleanup")

        async def cleanup_run_artifacts_job() -> None:
            from agents.cleanup import cleanup_run_artifacts, purge_old_run_events

            cleanup_run_artifacts(data_dir / "runs", max_age_days=30)
            purge_old_run_events(history, days=30)

        scheduler.add_job(
            cleanup_run_artifacts_job, "cron", hour=4, minute=0, id="artifact_cleanup"
        )
        scheduler.start()
        app.state.scheduler = scheduler
        logger.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))
        aggregator_task = asyncio.create_task(aggregator.start(poll_interval_seconds=300))
        if broker:
            await broker.start()
        from agents.task_processor import TaskProcessor

        task_processor = TaskProcessor(task_store=task_store, state=state, config=config)
        processor_task = asyncio.create_task(task_processor.run_loop())

        # Auth (optional — enabled when SECRET_KEY env var is set)
        import os as _os

        if _os.environ.get("SECRET_KEY"):
            from agents.auth import AuthDB
            from agents.auth_routes import register_auth_routes
            from agents.dashboard_html import _TEMPLATES as _auth_templates

            auth_db_inst = AuthDB(data_dir / "auth.db")
            auth_db_inst.bootstrap_invite()
            register_auth_routes(app, auth_db_inst, _auth_templates)
            app.state.auth_db = auth_db_inst
            logger.info("Auth enabled (SECRET_KEY set)")

            gh_client_id = config.integrations.github_oauth_client_id
            gh_client_secret = config.integrations.github_oauth_client_secret
            if gh_client_id and gh_client_secret:
                from agents.github_oauth_routes import register_github_oauth_routes

                register_github_oauth_routes(app, auth_db_inst, gh_client_id, gh_client_secret)
                app.state.github_oauth_client_id = gh_client_id
                logger.info("GitHub OAuth enabled (client_id=%s)", gh_client_id)
        else:
            app.state.auth_db = None
            logger.info("Auth disabled (no SECRET_KEY)")

        yield
        task_processor.stop()
        processor_task.cancel()
        if broker:
            await broker.stop()
        aggregator.stop()
        aggregator_task.cancel()
        scheduler.shutdown(wait=False)
        await state.executor.shutdown()
        logger.info("Shutdown complete")

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
