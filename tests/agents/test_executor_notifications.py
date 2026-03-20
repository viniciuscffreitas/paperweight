"""Tests for executor_notifications: finalize_agent_success and fail_agent_run."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.executor_notifications import fail_agent_run, finalize_agent_success
from agents.models import ProjectConfig, RunRecord, RunStatus, TaskConfig, TriggerType


def _make_project(discord_channel_id: str = "") -> ProjectConfig:
    return ProjectConfig(
        name="proj",
        repo="/tmp/repo",
        discord_channel_id=discord_channel_id,
        tasks={"t": TaskConfig(description="d", intent="i")},
    )


def _make_run(pr_url: str | None = None, error: str | None = None) -> RunRecord:
    now = datetime.now(UTC)
    return RunRecord(
        id="run-1",
        project="proj",
        task="agent",
        trigger_type=TriggerType.AGENT,
        started_at=now,
        finished_at=now,
        status=RunStatus.SUCCESS,
        model="sonnet",
        pr_url=pr_url,
        error_message=error,
        cost_usd=0.12,
    )


# ---------------------------------------------------------------------------
# finalize_agent_success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_posts_pr_comment_to_linear():
    linear = AsyncMock()
    run = _make_run(pr_url="https://github.com/org/repo/pull/42")
    variables = {"issue_id": "ISS-1", "team_id": "T1", "issue_identifier": "ISS-1", "issue_title": "Fix"}

    await finalize_agent_success(_make_project(), variables, "", run, linear, None)

    linear.post_comment.assert_awaited_once()
    call_args = linear.post_comment.call_args[0]
    assert "https://github.com/org/repo/pull/42" in call_args[1]


@pytest.mark.asyncio
async def test_finalize_posts_no_changes_comment_when_no_pr():
    linear = AsyncMock()
    run = _make_run(pr_url=None)
    variables = {"issue_id": "ISS-2", "team_id": "T1", "issue_identifier": "ISS-2", "issue_title": "x"}

    await finalize_agent_success(_make_project(), variables, "", run, linear, None)

    call_args = linear.post_comment.call_args[0]
    assert "sem alterações" in call_args[1] or "Concluído" in call_args[1]


@pytest.mark.asyncio
async def test_finalize_updates_linear_status_to_in_review_when_pr():
    linear = AsyncMock()
    run = _make_run(pr_url="https://github.com/pr/1")
    variables = {"issue_id": "ISS-3", "team_id": "T2", "issue_identifier": "", "issue_title": ""}

    await finalize_agent_success(_make_project(), variables, "", run, linear, None)

    linear.update_status.assert_awaited_once_with("ISS-3", "T2", "In Review")


@pytest.mark.asyncio
async def test_finalize_removes_agent_label():
    linear = AsyncMock()
    run = _make_run()
    variables = {"issue_id": "ISS-4", "team_id": "", "issue_identifier": "", "issue_title": ""}

    await finalize_agent_success(_make_project(), variables, "", run, linear, None)

    linear.remove_label.assert_awaited_once_with("ISS-4", "agent")


@pytest.mark.asyncio
async def test_finalize_calls_discord_when_msg_id_set():
    discord = AsyncMock()
    run = _make_run(pr_url="https://github.com/pr/2")
    variables = {"issue_id": "ISS-5", "team_id": "", "issue_identifier": "ISS-5", "issue_title": "Title"}

    await finalize_agent_success(_make_project(discord_channel_id="C1"), variables, "msg-abc", run, None, discord)

    discord.finalize_run_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_finalize_skips_discord_when_no_msg_id():
    discord = AsyncMock()
    run = _make_run()
    variables = {"issue_id": "ISS-6", "team_id": "", "issue_identifier": "", "issue_title": ""}

    await finalize_agent_success(_make_project(discord_channel_id="C1"), variables, "", run, None, discord)

    discord.finalize_run_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalize_tolerates_linear_exception():
    linear = AsyncMock()
    linear.post_comment.side_effect = RuntimeError("network error")
    run = _make_run()
    variables = {"issue_id": "ISS-7", "team_id": "", "issue_identifier": "", "issue_title": ""}

    # Must not raise
    await finalize_agent_success(_make_project(), variables, "", run, linear, None)


@pytest.mark.asyncio
async def test_finalize_skips_linear_when_none():
    run = _make_run()
    variables = {"issue_id": "ISS-8", "team_id": "", "issue_identifier": "", "issue_title": ""}

    # Must not raise with no clients
    await finalize_agent_success(_make_project(), variables, "", run, None, None)


# ---------------------------------------------------------------------------
# fail_agent_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fail_posts_error_comment_to_linear():
    linear = AsyncMock()
    run = _make_run(error="Claude timed out")
    variables = {"issue_id": "ISS-9", "team_id": "T3", "issue_identifier": "", "issue_title": ""}

    await fail_agent_run(_make_project(), variables, "", run, 1, 3, linear, None)

    linear.post_comment.assert_awaited_once()
    comment = linear.post_comment.call_args[0][1]
    assert "Claude timed out" in comment
    assert "3" in comment  # max_attempts


@pytest.mark.asyncio
async def test_fail_resets_linear_status_to_todo():
    linear = AsyncMock()
    run = _make_run(error="err")
    variables = {"issue_id": "ISS-10", "team_id": "T4", "issue_identifier": "", "issue_title": ""}

    await fail_agent_run(_make_project(), variables, "", run, 1, 1, linear, None)

    linear.update_status.assert_awaited_once_with("ISS-10", "T4", "Todo")


@pytest.mark.asyncio
async def test_fail_calls_discord_fail_message():
    discord = AsyncMock()
    run = _make_run(error="crash")
    variables = {"issue_id": "ISS-11", "team_id": "", "issue_identifier": "ISS-11", "issue_title": "Bork"}

    await fail_agent_run(_make_project(discord_channel_id="C2"), variables, "msg-xyz", run, 2, 5, None, discord)

    discord.fail_run_message.assert_awaited_once()
    kwargs = discord.fail_run_message.call_args[1]
    assert kwargs["attempt"] == 2
    assert kwargs["max_attempts"] == 5
    assert kwargs["error"] == "crash"


@pytest.mark.asyncio
async def test_fail_tolerates_linear_exception():
    linear = AsyncMock()
    linear.post_comment.side_effect = Exception("gone")
    run = _make_run(error="x")
    variables = {"issue_id": "ISS-12", "team_id": "", "issue_identifier": "", "issue_title": ""}

    # Must not raise
    await fail_agent_run(_make_project(), variables, "", run, 1, 1, linear, None)


@pytest.mark.asyncio
async def test_fail_skips_linear_when_none():
    run = _make_run(error="y")
    variables = {"issue_id": "ISS-13", "team_id": "", "issue_identifier": "", "issue_title": ""}

    await fail_agent_run(_make_project(), variables, "", run, 1, 1, None, None)
