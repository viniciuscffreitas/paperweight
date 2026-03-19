from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_no_linear_client_skips_team_fetch():
    """When linear_client is None, no team fetch happens and discord still runs."""
    from agents.discovery import auto_discover_project_ids

    mock_discord = AsyncMock()
    mock_discord.find_channel_by_name.return_value = "chan-999"

    project = MagicMock()
    project.name = "jarvis"
    project.linear_team_id = ""
    project.discord_channel_id = ""

    # Should not raise; linear is None so no fetch attempt
    await auto_discover_project_ids({"jarvis": project}, None, mock_discord, "guild-42")

    # linear_team_id stays empty — no client means no discovery
    assert project.linear_team_id == ""
    # discord path still runs normally
    assert project.discord_channel_id == "chan-999"
    mock_discord.find_channel_by_name.assert_called_once_with("guild-42", "jarvis-dev")


@pytest.mark.asyncio
async def test_no_discord_notifier_skips_channel_fetch():
    """When discord_notifier is None, discord channel lookup is skipped entirely."""
    from agents.discovery import auto_discover_project_ids

    mock_linear = AsyncMock()
    mock_linear.fetch_teams.return_value = {"myapp": "team-xyz"}

    project = MagicMock()
    project.name = "myapp"
    project.linear_team_id = ""
    project.discord_channel_id = ""

    await auto_discover_project_ids({"myapp": project}, mock_linear, None, "guild-1")

    # Linear is discovered normally
    assert project.linear_team_id == "team-xyz"
    # discord_channel_id is never touched
    assert project.discord_channel_id == ""


@pytest.mark.asyncio
async def test_empty_projects_dict_does_not_crash():
    """When projects is an empty dict, the function completes without error."""
    from agents.discovery import auto_discover_project_ids

    mock_linear = AsyncMock()
    mock_linear.fetch_teams.return_value = {"orphan": "team-001"}

    # No projects — loop body never executes
    await auto_discover_project_ids({}, mock_linear, None, "guild-1")
    # No assertion needed beyond no exception; fetch_teams still called
    mock_linear.fetch_teams.assert_called_once()


@pytest.mark.asyncio
async def test_project_with_existing_linear_team_id_is_not_overwritten():
    """Discovery must skip the linear field when linear_team_id is already set."""
    from agents.discovery import auto_discover_project_ids

    mock_linear = AsyncMock()
    # API returns a different ID for the same project name
    mock_linear.fetch_teams.return_value = {"existing": "team-new"}

    project = MagicMock()
    project.name = "existing"
    project.linear_team_id = "team-original"
    project.discord_channel_id = "chan-original"

    await auto_discover_project_ids({"existing": project}, mock_linear, None, "")

    # Original value must be preserved
    assert project.linear_team_id == "team-original"
