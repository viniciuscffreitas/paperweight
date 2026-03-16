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
