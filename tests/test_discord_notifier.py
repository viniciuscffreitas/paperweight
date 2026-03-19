"""Tests for DiscordRunNotifier."""

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

    def test_success_color(self, notifier):
        embed = notifier._build_embed("X", "Y", status="success")
        assert embed["color"] == 0x4ADE80

    def test_failure_color(self, notifier):
        embed = notifier._build_embed("X", "Y", status="failure")
        assert embed["color"] == 0xF87171

    def test_no_events_shows_placeholder(self, notifier):
        embed = notifier._build_embed("PROJ-1", "Title")
        assert "aguardando eventos" in embed["description"]

    def test_tool_name_rendered_in_event_line(self, notifier):
        events = [
            {"type": "tool_use", "content": "reading file", "timestamp": 1000, "tool_name": "Read"}
        ]
        embed = notifier._build_embed("PROJ-1", "Title", events=events)
        assert "**Read**" in embed["description"]
        assert "reading file" in embed["description"]

    def test_description_truncated_when_too_long(self, notifier):
        # Create events whose combined text would exceed MAX_EMBED_LENGTH
        events = [
            {"type": "assistant", "content": "x" * 120, "timestamp": 1000 + i}
            for i in range(50)
        ]
        embed = notifier._build_embed("PROJ-1", "Title", events=events, status="running")
        assert len(embed["description"]) <= notifier.MAX_EMBED_LENGTH + len("**Title**\n\n")

    def test_error_appended_to_description(self, notifier):
        embed = notifier._build_embed("PROJ-1", "Title", error="boom!", status="failure")
        assert "boom!" in embed["description"]

    def test_pr_url_set_on_embed(self, notifier):
        embed = notifier._build_embed(
            "PROJ-1", "Title", pr_url="https://github.com/org/repo/pull/5", status="success"
        )
        assert embed["url"] == "https://github.com/org/repo/pull/5"

    def test_footer_with_cost_and_duration(self, notifier):
        embed = notifier._build_embed("PROJ-1", "Title", cost=0.42, duration_s=90.0, status="success")
        footer_text = embed["footer"]["text"]
        assert "$0.42" in footer_text
        assert "1m30s" in footer_text

    def test_no_footer_when_no_cost_or_duration(self, notifier):
        embed = notifier._build_embed("PROJ-1", "Title")
        assert "footer" not in embed


class TestRateLimitRetry:
    @pytest.mark.asyncio
    async def test_request_retries_on_429(self, notifier):
        import asyncio

        ok_response = MagicMock()
        ok_response.status_code = 200
        ok_response.json.return_value = {"id": "msg-1"}
        ok_response.raise_for_status = MagicMock()

        rate_limited_response = MagicMock()
        rate_limited_response.status_code = 429
        rate_limited_response.json.return_value = {"retry_after": 0.01}

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=[rate_limited_response, ok_response])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agents.discord_notifier.httpx.AsyncClient", return_value=mock_client):
            with patch("agents.discord_notifier.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await notifier._request("GET", "/guilds/g1/channels")

        assert mock_client.request.call_count == 2
        mock_sleep.assert_awaited_once()
        assert result == {"id": "msg-1"}


class TestFailRunMessagePatchUrl:
    @pytest.mark.asyncio
    async def test_fail_sends_patch_to_correct_url(self, notifier):
        mock_client, _ = _mock_async_client({})
        events = []

        with patch("agents.discord_notifier.httpx.AsyncClient", return_value=mock_client):
            await notifier.fail_run_message(
                "chan-99", "msg-42", "PROJ-1", "Title", events,
                error="err", attempt=1, max_attempts=3,
            )

        call_args = mock_client.request.call_args
        assert call_args[0][0] == "PATCH"
        assert "/channels/chan-99/messages/msg-42" in call_args[0][1]


class TestFinalizeRunMessage:
    @pytest.mark.asyncio
    async def test_finalize_sets_success_color(self, notifier):
        mock_client, _ = _mock_async_client({})
        events = [{"type": "assistant", "content": "done", "timestamp": 1000}]

        with patch("agents.discord_notifier.httpx.AsyncClient", return_value=mock_client):
            await notifier.finalize_run_message(
                "chan-1", "msg-1", "PROJ-42", "Fix bug", events,
                pr_url="https://github.com/org/repo/pull/1", cost=0.15, duration_s=125.0,
            )

        call_args = mock_client.request.call_args
        embed = call_args[1]["json"]["embeds"][0]
        assert embed["color"] == 0x4ADE80
        assert embed["url"] == "https://github.com/org/repo/pull/1"

    @pytest.mark.asyncio
    async def test_finalize_includes_footer(self, notifier):
        mock_client, _ = _mock_async_client({})
        events = [{"type": "assistant", "content": "done", "timestamp": 1000}]

        with patch("agents.discord_notifier.httpx.AsyncClient", return_value=mock_client):
            await notifier.finalize_run_message(
                "chan-1", "msg-1", "PROJ-42", "Fix bug", events,
                cost=0.15, duration_s=125.0,
            )

        call_args = mock_client.request.call_args
        embed = call_args[1]["json"]["embeds"][0]
        assert "$0.15" in embed["footer"]["text"]
        assert "2m05s" in embed["footer"]["text"]


class TestFindChannelByName:
    @pytest.mark.asyncio
    async def test_find_channel_by_name_returns_channel_id(self, notifier):
        mock_client, _mock_response = _mock_async_client(
            response_json=[
                {"id": "chan-1", "name": "general", "type": 0},
                {"id": "chan-2", "name": "sekit-dev", "type": 0},
                {"id": "chan-3", "name": "voice", "type": 2},
            ]
        )
        with patch("agents.discord_notifier.httpx.AsyncClient", return_value=mock_client):
            result = await notifier.find_channel_by_name("guild-1", "sekit-dev")
        assert result == "chan-2"

    @pytest.mark.asyncio
    async def test_find_channel_by_name_returns_none_when_not_found(self, notifier):
        mock_client, _mock_response = _mock_async_client(
            response_json=[
                {"id": "chan-1", "name": "general", "type": 0},
            ]
        )
        with patch("agents.discord_notifier.httpx.AsyncClient", return_value=mock_client):
            result = await notifier.find_channel_by_name("guild-1", "nonexistent")
        assert result is None


class TestFailRunMessage:
    @pytest.mark.asyncio
    async def test_fail_sets_failure_color(self, notifier):
        mock_client, _ = _mock_async_client({})
        events = [{"type": "system", "content": "error", "timestamp": 1000}]

        with patch("agents.discord_notifier.httpx.AsyncClient", return_value=mock_client):
            await notifier.fail_run_message(
                "chan-1", "msg-1", "PROJ-42", "Fix bug", events,
                error="Process crashed", attempt=2, max_attempts=3, cost=0.05, duration_s=30.0,
            )

        call_args = mock_client.request.call_args
        embed = call_args[1]["json"]["embeds"][0]
        assert embed["color"] == 0xF87171

    @pytest.mark.asyncio
    async def test_fail_includes_error_and_attempt(self, notifier):
        mock_client, _ = _mock_async_client({})
        events = [{"type": "system", "content": "error", "timestamp": 1000}]

        with patch("agents.discord_notifier.httpx.AsyncClient", return_value=mock_client):
            await notifier.fail_run_message(
                "chan-1", "msg-1", "PROJ-42", "Fix bug", events,
                error="Process crashed", attempt=2, max_attempts=3, cost=0.05, duration_s=30.0,
            )

        call_args = mock_client.request.call_args
        embed = call_args[1]["json"]["embeds"][0]
        assert "Process crashed" in embed["description"]
        assert "Attempt 2/3" in embed["footer"]["text"]
        assert "$0.05" in embed["footer"]["text"]
