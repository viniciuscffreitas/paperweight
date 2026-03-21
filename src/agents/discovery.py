from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def auto_discover_project_ids(
    projects: dict,
    linear_client: Any,  # noqa: ANN401
    discord_notifier: Any,  # noqa: ANN401
    guild_id: str,
) -> None:
    """Fill in missing linear_team_id and discord_channel_id on projects by querying APIs."""
    teams: dict[str, str] = {}
    if linear_client:
        try:
            teams = await linear_client.fetch_teams()
            logger.info("Linear teams discovered: %s", list(teams.keys()))
        except Exception:
            logger.warning("Failed to fetch Linear teams for auto-discovery")

    for project in projects.values():
        # Auto-fill linear_team_id
        if not project.linear_team_id and project.name.lower() in teams:
            project.linear_team_id = teams[project.name.lower()]
            logger.info(
                "Auto-discovered linear_team_id for %s: %s", project.name, project.linear_team_id
            )

        if not project.linear_team_id:
            for team_name, tid in teams.items():
                if project.name.lower() in team_name or team_name in project.name.lower():
                    project.linear_team_id = tid
                    logger.info(
                        "Auto-discovered linear_team_id (fuzzy) for %s: %s (team: %s)",
                        project.name,
                        tid,
                        team_name,
                    )
                    break

        # Auto-fill discord_channel_id
        if not project.discord_channel_id and discord_notifier and guild_id:
            try:
                channel_id = await discord_notifier.find_channel_by_name(
                    guild_id, f"{project.name}-dev"
                )
                if channel_id:
                    project.discord_channel_id = channel_id
                    logger.info(
                        "Auto-discovered discord_channel_id for %s: %s", project.name, channel_id
                    )
            except Exception:
                logger.warning("Failed to find Discord channel for %s", project.name)
