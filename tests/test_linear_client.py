from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def linear_client():
    from agents.linear_client import LinearClient

    return LinearClient(api_key="test-key")


@pytest.mark.asyncio
async def test_fetch_issue_returns_parsed_dict(linear_client):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": {
            "issue": {
                "id": "issue-123",
                "identifier": "ENG-42",
                "title": "Fix login bug",
                "description": "Users cannot log in",
                "state": {"name": "In Progress"},
                "labels": {"nodes": [{"name": "bug", "id": "lbl-1"}, {"name": "urgent", "id": "lbl-2"}]},
            }
        }
    }
    mock_response.raise_for_status = MagicMock()

    mock_client_instance = AsyncMock()
    mock_client_instance.post.return_value = mock_response
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    with patch("agents.linear_client.httpx.AsyncClient", return_value=mock_client_instance):
        result = await linear_client.fetch_issue("issue-123")

    assert result == {
        "id": "issue-123",
        "identifier": "ENG-42",
        "title": "Fix login bug",
        "description": "Users cannot log in",
        "state": "In Progress",
        "labels": ["bug", "urgent"],
    }

    mock_client_instance.post.assert_called_once()
    call_kwargs = mock_client_instance.post.call_args
    assert call_kwargs[1]["headers"]["Authorization"] == "test-key"


def _make_mock_client(responses):
    """Helper: returns a mock httpx.AsyncClient that yields `responses` in order."""
    mock_client_instance = AsyncMock()
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    mock_responses = []
    for resp_json in responses:
        r = MagicMock()
        r.json.return_value = resp_json
        r.raise_for_status = MagicMock()
        mock_responses.append(r)

    mock_client_instance.post.side_effect = mock_responses
    return mock_client_instance


@pytest.mark.asyncio
async def test_post_comment_calls_graphql(linear_client):
    mock_client = _make_mock_client([{"data": {"commentCreate": {"success": True}}}])

    with patch("agents.linear_client.httpx.AsyncClient", return_value=mock_client):
        await linear_client.post_comment("issue-123", "Hello from bot")

    call_kwargs = mock_client.post.call_args[1]
    payload = call_kwargs["json"]
    assert "commentCreate" in payload["query"]
    assert payload["variables"]["issueId"] == "issue-123"
    assert payload["variables"]["body"] == "Hello from bot"


@pytest.mark.asyncio
async def test_update_status_fetches_states_and_updates(linear_client):
    team_states_response = {
        "data": {"team": {"states": {"nodes": [
            {"id": "state-1", "name": "Todo"},
            {"id": "state-2", "name": "In Progress"},
            {"id": "state-3", "name": "Done"},
        ]}}}
    }
    update_response = {"data": {"issueUpdate": {"success": True}}}
    mock_client = _make_mock_client([team_states_response, update_response])

    with patch("agents.linear_client.httpx.AsyncClient", return_value=mock_client):
        await linear_client.update_status("issue-123", "team-abc", "In Progress")

    assert mock_client.post.call_count == 2
    update_call = mock_client.post.call_args_list[1][1]
    assert update_call["json"]["variables"]["stateId"] == "state-2"


@pytest.mark.asyncio
async def test_update_status_caches_team_states(linear_client):
    team_states_response = {
        "data": {"team": {"states": {"nodes": [
            {"id": "state-1", "name": "Todo"},
            {"id": "state-3", "name": "Done"},
        ]}}}
    }
    update_response = {"data": {"issueUpdate": {"success": True}}}
    # First call: fetch states + update = 2 calls
    mock_client = _make_mock_client([team_states_response, update_response, update_response])

    with patch("agents.linear_client.httpx.AsyncClient", return_value=mock_client):
        await linear_client.update_status("issue-123", "team-abc", "Done")
        await linear_client.update_status("issue-456", "team-abc", "Todo")

    # Second call should use cache: only 1 more call (the update), total = 3
    assert mock_client.post.call_count == 3


@pytest.mark.asyncio
async def test_update_status_unknown_state_logs_warning(linear_client):
    team_states_response = {
        "data": {"team": {"states": {"nodes": [
            {"id": "state-1", "name": "Todo"},
        ]}}}
    }
    mock_client = _make_mock_client([team_states_response])

    with patch("agents.linear_client.httpx.AsyncClient", return_value=mock_client), \
         patch("agents.linear_client.logger") as mock_logger:
        await linear_client.update_status("issue-123", "team-abc", "Nonexistent")

    mock_logger.warning.assert_called_once()
    # Only 1 call (fetch states), no update call
    assert mock_client.post.call_count == 1


@pytest.mark.asyncio
async def test_remove_label_queries_then_removes(linear_client):
    fetch_labels_response = {
        "data": {"issue": {"labels": {"nodes": [
            {"id": "lbl-1", "name": "bug"},
            {"id": "lbl-2", "name": "agent-trigger"},
        ]}}}
    }
    remove_response = {"data": {"issueRemoveLabel": {"success": True}}}
    mock_client = _make_mock_client([fetch_labels_response, remove_response])

    with patch("agents.linear_client.httpx.AsyncClient", return_value=mock_client):
        await linear_client.remove_label("issue-123", "agent-trigger")

    assert mock_client.post.call_count == 2
    remove_call = mock_client.post.call_args_list[1][1]
    assert remove_call["json"]["variables"]["labelId"] == "lbl-2"


@pytest.mark.asyncio
async def test_remove_label_case_insensitive(linear_client):
    fetch_labels_response = {
        "data": {"issue": {"labels": {"nodes": [
            {"id": "lbl-1", "name": "Agent-Trigger"},
        ]}}}
    }
    remove_response = {"data": {"issueRemoveLabel": {"success": True}}}
    mock_client = _make_mock_client([fetch_labels_response, remove_response])

    with patch("agents.linear_client.httpx.AsyncClient", return_value=mock_client):
        await linear_client.remove_label("issue-123", "agent-trigger")

    assert mock_client.post.call_count == 2


@pytest.mark.asyncio
async def test_fetch_teams_returns_name_to_id_mapping(linear_client):
    mock_client = _make_mock_client([{
        "data": {"teams": {"nodes": [
            {"id": "team-1", "name": "Sekit"},
            {"id": "team-2", "name": "Jarvis"},
        ]}}
    }])
    with patch("agents.linear_client.httpx.AsyncClient", return_value=mock_client):
        result = await linear_client.fetch_teams()
    assert result == {"sekit": "team-1", "jarvis": "team-2"}


@pytest.mark.asyncio
async def test_remove_label_not_found_logs_warning(linear_client):
    fetch_labels_response = {
        "data": {"issue": {"labels": {"nodes": [
            {"id": "lbl-1", "name": "bug"},
        ]}}}
    }
    mock_client = _make_mock_client([fetch_labels_response])

    with patch("agents.linear_client.httpx.AsyncClient", return_value=mock_client), \
         patch("agents.linear_client.logger") as mock_logger:
        await linear_client.remove_label("issue-123", "nonexistent")

    mock_logger.warning.assert_called_once()
    assert mock_client.post.call_count == 1
