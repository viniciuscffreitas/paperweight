"""Webhook route registration (GitHub and Linear)."""
from __future__ import annotations

import logging
import time as _time
from typing import TYPE_CHECKING

from fastapi import BackgroundTasks, FastAPI, Request, Response

from agents.webhooks.github import (
    extract_github_issue_variables,
    extract_github_variables,
    extract_pr_merge_info,
    is_agent_pr_merge,
    match_github_event,
    match_github_issue,
    verify_github_signature,
)
from agents.webhooks.linear import (
    extract_agent_issue_variables,
    extract_linear_variables,
    match_agent_issue,
    match_linear_event,
    verify_linear_signature,
)

if TYPE_CHECKING:
    from agents.app_state import AppState
    from agents.config import GlobalConfig
    from agents.linear_client import LinearClient
    from agents.models import ProjectConfig, RunRecord

logger = logging.getLogger(__name__)


def register_webhook_routes(
    app: FastAPI,
    state: AppState,
    config: GlobalConfig,
    linear_client: LinearClient | None,
) -> None:
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

        if event_type == "issues" and match_github_issue(payload):
            issue_vars = extract_github_issue_variables(payload)
            issue_number = issue_vars.get("issue_number", "")
            repo_name = issue_vars.get("repo_full_name", "")
            source_id = f"github:{repo_name}#{issue_number}"

            if state.task_store and not state.task_store.exists_by_source("github", source_id):
                for project in state.projects.values():
                    repo_match = repo_name and repo_name in project.repo
                    if repo_match and "issue-resolver" in project.tasks:
                        state.task_store.create(
                            project=project.name,
                            title=issue_vars.get("issue_title", "GitHub issue"),
                            description=issue_vars.get("issue_body", ""),
                            source="github",
                            source_id=source_id,
                            source_url=issue_vars.get("issue_url", ""),
                            template="issue-resolver",
                        )
                        logger.info("Created task for GitHub issue %s", source_id)
                        break

        if is_agent_pr_merge(payload):
            merge_info = extract_pr_merge_info(payload)
            pr_url = merge_info["pr_url"]
            run: RunRecord | None = state.history.find_run_by_pr_url(pr_url)
            if run and linear_client:
                async def _mark_done(r: RunRecord = run) -> None:
                    variables = state.history.get_run_variables(r.id)
                    if variables:
                        issue_id = variables.get("issue_id", "")
                        team_id = variables.get("team_id", "")
                        if issue_id and team_id and linear_client:
                            try:
                                await linear_client.update_status(issue_id, team_id, "Done")
                                await linear_client.post_comment(
                                    issue_id, f"✅ PR merged: {pr_url}"
                                )
                            except Exception:
                                logger.warning("Failed to mark issue done for PR %s", pr_url)

                background_tasks.add_task(_mark_done)

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

        if match_agent_issue(payload):
            variables = extract_agent_issue_variables(payload)
            issue_id = variables.get("issue_id", "")
            team_id = variables.get("team_id", "")
            now = _time.time()
            last_seen = state._agent_issue_seen.get(issue_id, 0)
            if now - last_seen < 120:
                logger.info(
                    "Cooldown: skipping agent issue %s (seen %.0fs ago)",
                    issue_id,
                    now - last_seen,
                )
            else:
                existing = state.history.find_run_by_issue_id(issue_id)
                if existing and existing.status in ("running", "success"):
                    logger.info(
                        "Dedup: skipping agent issue %s — already %s",
                        issue_id,
                        existing.status,
                    )
                else:
                    for project in state.projects.values():
                        if project.linear_team_id == team_id and "issue-resolver" in project.tasks:
                            state._agent_issue_seen[issue_id] = now
                            store = state.task_store
                            if store and not store.exists_by_source("linear", issue_id):
                                ident = variables.get("issue_identifier", "")
                                store.create(
                                    project=project.name,
                                    title=variables.get("issue_title", "Linear issue"),
                                    description=variables.get("issue_description", ""),
                                    source="linear",
                                    source_id=issue_id,
                                    source_url=f"https://linear.app/issue/{ident}",
                                    template="issue-resolver",
                                )
                                logger.info("Created task for Linear issue %s", issue_id)
                            break

        return {"status": "processed"}
