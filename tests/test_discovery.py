from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_auto_discover_fills_linear_team_id():
    from agents.discovery import auto_discover_project_ids

    mock_linear = AsyncMock()
    mock_linear.fetch_teams.return_value = {"sekit": "team-abc", "jarvis": "team-def"}

    project = MagicMock()
    project.name = "sekit"
    project.linear_team_id = ""
    project.discord_channel_id = ""

    await auto_discover_project_ids({"sekit": project}, mock_linear, None, "")
    assert project.linear_team_id == "team-abc"


@pytest.mark.asyncio
async def test_auto_discover_fills_discord_channel_id():
    from agents.discovery import auto_discover_project_ids

    mock_discord = AsyncMock()
    mock_discord.find_channel_by_name.return_value = "chan-456"

    project = MagicMock()
    project.name = "sekit"
    project.linear_team_id = "already-set"
    project.discord_channel_id = ""

    await auto_discover_project_ids({"sekit": project}, None, mock_discord, "guild-1")
    assert project.discord_channel_id == "chan-456"
    mock_discord.find_channel_by_name.assert_called_once_with("guild-1", "sekit-dev")


@pytest.mark.asyncio
async def test_auto_discover_skips_already_configured():
    from agents.discovery import auto_discover_project_ids

    mock_linear = AsyncMock()
    mock_linear.fetch_teams.return_value = {"sekit": "team-abc"}

    project = MagicMock()
    project.name = "sekit"
    project.linear_team_id = "already-set"
    project.discord_channel_id = "already-set"

    await auto_discover_project_ids({"sekit": project}, mock_linear, None, "")
    # Should not overwrite
    assert project.linear_team_id == "already-set"
    assert project.discord_channel_id == "already-set"


@pytest.mark.asyncio
async def test_auto_discover_handles_api_failure_gracefully():
    from agents.discovery import auto_discover_project_ids

    mock_linear = AsyncMock()
    mock_linear.fetch_teams.side_effect = Exception("API down")

    project = MagicMock()
    project.name = "sekit"
    project.linear_team_id = ""
    project.discord_channel_id = ""

    # Should not raise
    await auto_discover_project_ids({"sekit": project}, mock_linear, None, "")
    assert project.linear_team_id == ""
