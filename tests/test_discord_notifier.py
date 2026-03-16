"""Tests for DiscordRunNotifier."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.discord_notifier import DiscordRunNotifier


@pytest.fixture
def notifier():
    return DiscordRunNotifier(bot_token="test-bot-token")


def _mock_async_client(response_json=None, status_code=200):
    """Create a mock httpx.AsyncClient context manager."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = response_json or {}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    return mock_client, mock_response


class TestCreateRunMessage:
    @pytest.mark.asyncio
    async def test_create_run_message_returns_message_id(self, notifier):
        mock_client, _ = _mock_async_client({"id": "msg-123"})

        with patch("agents.discord_notifier.httpx.AsyncClient", return_value=mock_client):
            msg_id = await notifier.create_run_message("chan-1", "PROJ-42", "Fix the bug")

        assert msg_id == "msg-123"

    @pytest.mark.asyncio
    async def test_create_run_message_sends_post_with_embed(self, notifier):
        mock_client, _ = _mock_async_client({"id": "msg-1"})

        with patch("agents.discord_notifier.httpx.AsyncClient", return_value=mock_client):
            await notifier.create_run_message("chan-1", "PROJ-42", "Fix the bug")

        mock_client.request.assert_called_once()
        call_args = mock_client.request.call_args
        assert call_args[0][0] == "POST"
        assert "/channels/chan-1/messages" in call_args[0][1]
        payload = call_args[1]["json"]
        embed = payload["embeds"][0]
        assert "PROJ-42" in embed["title"]
        assert embed["color"] == 0x059669  # running color


class TestUpdateRunMessage:
    @pytest.mark.asyncio
    async def test_update_sends_patch(self, notifier):
        mock_client, _ = _mock_async_client({})
        events = [{"type": "assistant", "content": "thinking", "timestamp": 1000}]

        with patch("agents.discord_notifier.httpx.AsyncClient", return_value=mock_client):
            await notifier.update_run_message("chan-1", "msg-1", "PROJ-42", "Fix bug", events)

        mock_client.request.assert_called_once()
        call_args = mock_client.request.call_args
        assert call_args[0][0] == "PATCH"
        assert "/channels/chan-1/messages/msg-1" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_update_skips_if_within_rate_limit(self, notifier):
        mock_client, _ = _mock_async_client({})
        events = [{"type": "assistant", "content": "thinking", "timestamp": 1000}]

        with patch("agents.discord_notifier.httpx.AsyncClient", return_value=mock_client):
            # First call should go through
            await notifier.update_run_message("chan-1", "msg-1", "PROJ-42", "Fix bug", events)
            assert mock_client.request.call_count == 1

            # Second call within 2s should be skipped
            await notifier.update_run_message("chan-1", "msg-1", "PROJ-42", "Fix bug", events)
            assert mock_client.request.call_count == 1

    @pytest.mark.asyncio
    async def test_update_allows_after_interval(self, notifier):
        mock_client, _ = _mock_async_client({})
        events = [{"type": "assistant", "content": "thinking", "timestamp": 1000}]

        with patch("agents.discord_notifier.httpx.AsyncClient", return_value=mock_client):
            await notifier.update_run_message("chan-1", "msg-1", "PROJ-42", "Fix bug", events)
            assert mock_client.request.call_count == 1

            # Simulate time passing beyond interval
            notifier._last_edit_time -= 3.0
            await notifier.update_run_message("chan-1", "msg-1", "PROJ-42", "Fix bug", events)
            assert mock_client.request.call_count == 2


class TestBuildEmbed:
    def test_truncates_events_at_max(self, notifier):
        events = [
            {"type": "assistant", "content": f"event-{i}", "timestamp": 1000 + i}
            for i in range(50)
        ]
        embed = notifier._build_embed("PROJ-1", "Title", events=events, status="running")
        # Should mention omitted events
        assert "10 earlier events omitted" in embed["description"]

    def test_running_color(self, notifier):
        embed = notifier._build_embed("X", "Y", status="running")
        assert embed["color"] == 0x059669
