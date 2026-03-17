import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agents.slack_client import SlackBotClient


@pytest.fixture
def client() -> SlackBotClient:
    return SlackBotClient(bot_token="xoxb-test-token")


@pytest.mark.asyncio
async def test_list_channels(client):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "ok": True,
        "channels": [
            {"id": "C1", "name": "dev-momease", "is_member": True},
            {"id": "C2", "name": "general", "is_member": True},
        ],
    }
    mock_response.raise_for_status = MagicMock()
    with patch.object(client._client, "get", new_callable=AsyncMock, return_value=mock_response):
        channels = await client.list_channels()
    assert len(channels) == 2


@pytest.mark.asyncio
async def test_search_channels_by_name(client):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "ok": True,
        "channels": [
            {"id": "C1", "name": "dev-momease"},
            {"id": "C2", "name": "momease-deploys"},
            {"id": "C3", "name": "general"},
        ],
    }
    mock_response.raise_for_status = MagicMock()
    with patch.object(client._client, "get", new_callable=AsyncMock, return_value=mock_response):
        matches = await client.search_channels_by_name("momease")
    assert len(matches) == 2


@pytest.mark.asyncio
async def test_get_channel_history(client):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "ok": True,
        "messages": [
            {"ts": "1710590400.000100", "text": "deploy done", "user": "U1"},
        ],
    }
    mock_response.raise_for_status = MagicMock()
    with patch.object(client._client, "get", new_callable=AsyncMock, return_value=mock_response):
        messages = await client.get_channel_history("C1", limit=10)
    assert len(messages) == 1


@pytest.mark.asyncio
async def test_search_messages(client):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "ok": True,
        "messages": {
            "matches": [
                {"channel": {"id": "C1", "name": "random"}, "text": "momease is down", "ts": "123"},
            ],
            "total": 1,
        },
    }
    mock_response.raise_for_status = MagicMock()
    with patch.object(client._client, "get", new_callable=AsyncMock, return_value=mock_response):
        results = await client.search_messages("momease")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_get_user_info(client):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "ok": True,
        "user": {"id": "U1", "real_name": "Dev User", "name": "devuser"},
    }
    mock_response.raise_for_status = MagicMock()
    with patch.object(client._client, "get", new_callable=AsyncMock, return_value=mock_response):
        user = await client.get_user_info("U1")
    assert user["real_name"] == "Dev User"
