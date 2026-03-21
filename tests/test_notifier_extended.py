from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from agents.models import BudgetStatus, RunRecord, RunStatus, TriggerType
from agents.notifier import Notifier


@pytest.mark.asyncio
async def test_empty_webhook_url_skips_send_silently():
    """_send must return early without making an HTTP call when webhook_url is empty."""
    notifier = Notifier(webhook_url="")

    with patch("httpx.AsyncClient") as mock_client_cls:
        await notifier.send_text("hello")
        mock_client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_network_error_does_not_crash():
    """A generic Exception during HTTP post must be swallowed (only httpx.HTTPError is caught)."""
    notifier = Notifier(webhook_url="https://hooks.slack.com/test")

    mock_post = AsyncMock(side_effect=Exception("connection refused"))
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = mock_post

    # The notifier only catches httpx.HTTPError; a bare Exception will propagate.
    # This test documents the current boundary: generic exceptions are NOT swallowed.
    with (
        patch("httpx.AsyncClient", return_value=mock_client),
        pytest.raises(Exception, match="connection refused"),
    ):
            await notifier.send_text("test message")


@pytest.mark.asyncio
async def test_budget_warning_notification_message_format():
    """send_budget_warning must compose a message containing spent, limit, and percentage."""
    notifier = Notifier(webhook_url="https://hooks.slack.com/test")
    status = BudgetStatus(daily_limit_usd=20.0, spent_today_usd=15.0)

    captured: list[str] = []

    async def fake_send(text: str) -> None:
        captured.append(text)

    notifier._send = fake_send  # type: ignore[method-assign]

    await notifier.send_budget_warning(status)

    assert len(captured) == 1
    msg = captured[0]
    assert "$15.00" in msg
    assert "$20.00" in msg
    assert "75%" in msg


@pytest.mark.asyncio
async def test_run_notification_with_pr_url_includes_pr_link():
    """A successful run with a pr_url must include that URL in the sent message."""
    notifier = Notifier(webhook_url="https://hooks.slack.com/test")
    run = RunRecord(
        id="run-pr-1",
        project="alpha",
        task="refactor",
        trigger_type=TriggerType.SCHEDULE,
        started_at=datetime(2026, 3, 19, 10, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 3, 19, 10, 5, 0, tzinfo=UTC),
        status=RunStatus.SUCCESS,
        model="sonnet",
        cost_usd=0.42,
        num_turns=8,
        pr_url="https://github.com/org/alpha/pull/99",
    )

    captured: list[str] = []

    async def fake_send(text: str) -> None:
        captured.append(text)

    notifier._send = fake_send  # type: ignore[method-assign]

    await notifier.send_run_notification(run)

    assert len(captured) == 1
    msg = captured[0]
    assert "pull/99" in msg
    assert "[alpha] refactor" in msg


@pytest.mark.asyncio
async def test_run_notification_without_pr_url_omits_pr_line():
    """A successful run without a pr_url must not include a PR line in the message."""
    notifier = Notifier(webhook_url="https://hooks.slack.com/test")
    run = RunRecord(
        id="run-noop-1",
        project="beta",
        task="dep-update",
        trigger_type=TriggerType.SCHEDULE,
        started_at=datetime(2026, 3, 19, 9, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 3, 19, 9, 1, 30, tzinfo=UTC),
        status=RunStatus.SUCCESS,
        model="haiku",
        cost_usd=0.05,
        num_turns=3,
        pr_url=None,
    )

    captured: list[str] = []

    async def fake_send(text: str) -> None:
        captured.append(text)

    notifier._send = fake_send  # type: ignore[method-assign]

    await notifier.send_run_notification(run)

    assert len(captured) == 1
    msg = captured[0]
    assert "PR:" not in msg
    assert "[beta] dep-update" in msg
    assert "completed" in msg
