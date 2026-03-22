import asyncio
import logging
import os as _os
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI

from agents.aggregator import AggregatorService
from agents.app_state import AppState
from agents.coordination.broker import CoordinationBroker
from agents.discord_notifier import DiscordRunNotifier
from agents.history import HistoryDB
from agents.linear_client import LinearClient
from agents.models import RunStatus
from agents.notification_engine import NotificationEngine
from agents.notifier import Notifier
from agents.project_store import ProjectStore
from agents.session_manager import SessionManager
from agents.task_store import TaskStore

logger = logging.getLogger(__name__)


def create_lifespan(
    history: HistoryDB,
    config: object,
    projects: dict,
    task_store: TaskStore,
    state: AppState,
    session_manager: SessionManager,
    project_store: ProjectStore,
    aggregator: AggregatorService,
    notification_engine: NotificationEngine,
    notifier: Notifier,
    linear_client: LinearClient | None,
    discord_notifier_client: DiscordRunNotifier | None,
    data_dir: Path,
    broker: CoordinationBroker | None,
) -> Callable[[FastAPI], AsyncGenerator[None]]:
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
            config.integrations.discord_guild_id,  # type: ignore[union-attr]
        )

        from agents.migration import migrate_yaml_projects

        _migrated = migrate_yaml_projects(projects, project_store)
        if _migrated:
            logger.info("Auto-migrated %d YAML project(s) to SQLite", _migrated)

        from agents.scheduler import create_scheduler, register_jobs

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
                        state.get_semaphore(config.execution.max_concurrent),  # type: ignore[union-attr]
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
        if _os.environ.get("SECRET_KEY"):
            from agents.auth import AuthDB
            from agents.auth_routes import register_auth_routes
            from agents.dashboard_html import _TEMPLATES as _auth_templates
            from agents.profile_routes import register_profile_routes

            auth_db_inst = AuthDB(data_dir / "auth.db")
            auth_db_inst.bootstrap_invite()
            register_auth_routes(app, auth_db_inst, _auth_templates)
            register_profile_routes(app, auth_db_inst, _auth_templates)
            app.state.auth_db = auth_db_inst
            logger.info("Auth enabled (SECRET_KEY set)")

            gh_client_id = config.integrations.github_oauth_client_id  # type: ignore[union-attr]
            gh_client_secret = config.integrations.github_oauth_client_secret  # type: ignore[union-attr]
            if gh_client_id and gh_client_secret:
                from agents.github_oauth_routes import (
                    register_github_oauth_routes,
                    register_github_repo_routes,
                )

                register_github_oauth_routes(app, auth_db_inst, gh_client_id, gh_client_secret)
                register_github_repo_routes(app, auth_db_inst)
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

    return lifespan
