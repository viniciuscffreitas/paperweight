"""Linear + Discord notification helpers called at the end of agent runs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.models import ProjectConfig, RunRecord

logger = logging.getLogger(__name__)


async def finalize_agent_success(
    project: ProjectConfig,
    variables: dict[str, str],
    discord_msg_id: str,
    run: RunRecord,
    linear_client: object | None,
    discord_notifier: object | None,
) -> None:
    issue_id = variables.get("issue_id", "")
    team_id = variables.get("team_id", "")
    identifier = variables.get("issue_identifier", "")
    title = variables.get("issue_title", "")
    if linear_client:
        try:
            comment = (
                f"\u2705 PR criado: {run.pr_url}"
                if run.pr_url
                else "\u2705 Concluído (sem alterações)"
            )
            await linear_client.post_comment(issue_id, comment)  # type: ignore[union-attr]
            if run.pr_url:
                await linear_client.update_status(issue_id, team_id, "In Review")  # type: ignore[union-attr]
            await linear_client.remove_label(issue_id, "agent")  # type: ignore[union-attr]
        except Exception:
            logger.warning("Failed to finalize Linear for %s", issue_id)
    if discord_notifier and discord_msg_id and project.discord_channel_id:
        try:
            duration_s = (
                (run.finished_at - run.started_at).total_seconds() if run.finished_at else 0
            )
            await discord_notifier.finalize_run_message(  # type: ignore[union-attr]
                project.discord_channel_id, discord_msg_id, identifier, title, [],
                pr_url=run.pr_url, cost=run.cost_usd or 0.0, duration_s=duration_s,
            )
        except Exception:
            logger.warning("Failed to finalize Discord for %s", issue_id)


async def fail_agent_run(
    project: ProjectConfig,
    variables: dict[str, str],
    discord_msg_id: str,
    run: RunRecord,
    attempt: int,
    max_attempts: int,
    linear_client: object | None,
    discord_notifier: object | None,
) -> None:
    issue_id = variables.get("issue_id", "")
    team_id = variables.get("team_id", "")
    identifier = variables.get("issue_identifier", "")
    title = variables.get("issue_title", "")
    if linear_client:
        try:
            await linear_client.post_comment(  # type: ignore[union-attr]
                issue_id,
                f"\u274c Falha após {max_attempts} tentativas:\n"
                f"{run.error_message or 'Unknown error'}",
            )
            await linear_client.update_status(issue_id, team_id, "Todo")  # type: ignore[union-attr]
        except Exception:
            logger.warning("Failed to report failure to Linear for %s", issue_id)
    if discord_notifier and discord_msg_id and project.discord_channel_id:
        try:
            duration_s = (
                (run.finished_at - run.started_at).total_seconds() if run.finished_at else 0
            )
            await discord_notifier.fail_run_message(  # type: ignore[union-attr]
                project.discord_channel_id, discord_msg_id, identifier, title, [],
                error=run.error_message or "", attempt=attempt, max_attempts=max_attempts,
                cost=run.cost_usd or 0.0, duration_s=duration_s,
            )
        except Exception:
            logger.warning("Failed to report failure to Discord for %s", issue_id)
