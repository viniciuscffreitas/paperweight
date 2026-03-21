"""Tests for executor PR creation and agent finalization paths."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_create_pr_no_commits_returns_none(tmp_path):
    """When there are no commits beyond base branch, PR is not created."""
    from agents.budget import BudgetManager
    from agents.config import BudgetConfig, ExecutionConfig
    from agents.executor import Executor
    from agents.history import HistoryDB
    from agents.notifier import Notifier

    db = HistoryDB(tmp_path / "test.db")
    budget = BudgetManager(config=BudgetConfig(), history=db)
    notifier = Notifier(webhook_url="")
    executor = Executor(
        config=ExecutionConfig(worktree_base=str(tmp_path / "wt")),
        budget=budget,
        history=db,
        notifier=notifier,
        data_dir=tmp_path / "data",
    )

    # Mock _run_cmd: git log returns empty (no commits)
    executor._run_cmd = AsyncMock(return_value="")
    result = await executor._create_pr(
        cwd="/tmp/wt",
        project=AsyncMock(base_branch="main"),
        task_name="test",
        branch="agents/test",
        autonomy="pr-only",
    )
    assert result is None


@pytest.mark.asyncio
async def test_create_pr_success_returns_url(tmp_path):
    """Successful PR creation returns the URL."""
    from agents.budget import BudgetManager
    from agents.config import BudgetConfig, ExecutionConfig
    from agents.executor import Executor
    from agents.history import HistoryDB
    from agents.notifier import Notifier

    db = HistoryDB(tmp_path / "test.db")
    budget = BudgetManager(config=BudgetConfig(), history=db)
    notifier = Notifier(webhook_url="")
    executor = Executor(
        config=ExecutionConfig(worktree_base=str(tmp_path / "wt")),
        budget=budget,
        history=db,
        notifier=notifier,
        data_dir=tmp_path / "data",
    )

    call_count = 0

    async def mock_run_cmd(cmd, cwd):
        nonlocal call_count
        call_count += 1
        if "log" in cmd:
            return "abc123 some commit\ndef456 another"
        if "push" in cmd:
            return ""
        if "pr" in cmd and "create" in cmd:
            return "https://github.com/org/repo/pull/99\n"
        return ""

    executor._run_cmd = mock_run_cmd
    result = await executor._create_pr(
        cwd="/tmp/wt",
        project=AsyncMock(base_branch="main", name="test"),
        task_name="task",
        branch="agents/task",
        autonomy="pr-only",
    )
    assert result == "https://github.com/org/repo/pull/99"


@pytest.mark.asyncio
async def test_create_pr_auto_merge(tmp_path):
    """When autonomy is auto-merge, gh pr merge --auto is called."""
    from agents.budget import BudgetManager
    from agents.config import BudgetConfig, ExecutionConfig
    from agents.executor import Executor
    from agents.history import HistoryDB
    from agents.notifier import Notifier

    db = HistoryDB(tmp_path / "test.db")
    budget = BudgetManager(config=BudgetConfig(), history=db)
    notifier = Notifier(webhook_url="")
    executor = Executor(
        config=ExecutionConfig(worktree_base=str(tmp_path / "wt")),
        budget=budget,
        history=db,
        notifier=notifier,
        data_dir=tmp_path / "data",
    )

    commands_run = []

    async def mock_run_cmd(cmd, cwd):
        commands_run.append(cmd)
        if "log" in cmd:
            return "abc123 commit"
        if "push" in cmd:
            return ""
        if "pr" in cmd and "create" in cmd:
            return "https://github.com/org/repo/pull/100\n"
        if "merge" in cmd:
            return ""
        return ""

    executor._run_cmd = mock_run_cmd
    result = await executor._create_pr(
        cwd="/tmp/wt",
        project=AsyncMock(base_branch="main", name="test"),
        task_name="task",
        branch="agents/task",
        autonomy="auto-merge",
    )
    assert result == "https://github.com/org/repo/pull/100"
    # Verify auto-merge was called
    merge_cmds = [c for c in commands_run if "merge" in c]
    assert len(merge_cmds) == 1
    assert "--auto" in merge_cmds[0]


@pytest.mark.asyncio
async def test_create_pr_auto_merge_failure_still_returns_url(tmp_path):
    """If auto-merge fails (branch protection), PR URL is still returned."""
    from agents.budget import BudgetManager
    from agents.config import BudgetConfig, ExecutionConfig
    from agents.executor import Executor
    from agents.history import HistoryDB
    from agents.notifier import Notifier

    db = HistoryDB(tmp_path / "test.db")
    budget = BudgetManager(config=BudgetConfig(), history=db)
    notifier = Notifier(webhook_url="")
    executor = Executor(
        config=ExecutionConfig(worktree_base=str(tmp_path / "wt")),
        budget=budget,
        history=db,
        notifier=notifier,
        data_dir=tmp_path / "data",
    )

    async def mock_run_cmd(cmd, cwd):
        if "log" in cmd:
            return "abc123 commit"
        if "push" in cmd:
            return ""
        if "pr" in cmd and "create" in cmd:
            return "https://github.com/org/repo/pull/101\n"
        if "merge" in cmd:
            raise RuntimeError("Auto-merge not allowed")
        return ""

    executor._run_cmd = mock_run_cmd
    # Should NOT raise — merge failure is caught
    result = await executor._create_pr(
        cwd="/tmp/wt",
        project=AsyncMock(base_branch="main", name="test"),
        task_name="task",
        branch="agents/task",
        autonomy="auto-merge",
    )
    assert result == "https://github.com/org/repo/pull/101"


@pytest.mark.asyncio
async def test_finalize_agent_success_posts_linear_comment(tmp_path):
    """After successful agent run, comments on Linear issue."""
    from agents.budget import BudgetManager
    from agents.config import BudgetConfig, ExecutionConfig
    from agents.executor import Executor
    from agents.history import HistoryDB
    from agents.models import ProjectConfig, RunRecord, RunStatus, TaskConfig, TriggerType
    from agents.notifier import Notifier

    db = HistoryDB(tmp_path / "test.db")
    budget = BudgetManager(config=BudgetConfig(), history=db)
    notifier = Notifier(webhook_url="")
    linear_client = AsyncMock()
    executor = Executor(
        config=ExecutionConfig(worktree_base=str(tmp_path / "wt")),
        budget=budget,
        history=db,
        notifier=notifier,
        data_dir=tmp_path / "data",
        linear_client=linear_client,
    )

    project = ProjectConfig(
        name="test",
        repo="/tmp",
        tasks={"t": TaskConfig(description="d", intent="i")},
    )
    run = RunRecord(
        id="r-1",
        project="test",
        task="t",
        trigger_type=TriggerType.LINEAR,
        started_at=datetime.now(UTC),
        status=RunStatus.SUCCESS,
        model="sonnet",
        pr_url="https://github.com/org/repo/pull/42",
    )

    await executor._finalize_agent_success(
        project,
        variables={
            "issue_id": "iss-1",
            "team_id": "team-1",
            "issue_identifier": "ENG-42",
            "issue_title": "Fix bug",
        },
        discord_msg_id="",
        run=run,
    )

    linear_client.post_comment.assert_called_once()
    comment_text = linear_client.post_comment.call_args[0][1]
    assert "PR criado" in comment_text
    assert "pull/42" in comment_text
    linear_client.update_status.assert_called_once_with("iss-1", "team-1", "In Review")
    linear_client.remove_label.assert_called_once_with("iss-1", "agent")


@pytest.mark.asyncio
async def test_fail_agent_run_posts_failure_comment(tmp_path):
    """After failed agent run, comments failure on Linear issue."""
    from agents.budget import BudgetManager
    from agents.config import BudgetConfig, ExecutionConfig
    from agents.executor import Executor
    from agents.history import HistoryDB
    from agents.models import ProjectConfig, RunRecord, RunStatus, TaskConfig, TriggerType
    from agents.notifier import Notifier

    db = HistoryDB(tmp_path / "test.db")
    budget = BudgetManager(config=BudgetConfig(), history=db)
    notifier = Notifier(webhook_url="")
    linear_client = AsyncMock()
    executor = Executor(
        config=ExecutionConfig(worktree_base=str(tmp_path / "wt")),
        budget=budget,
        history=db,
        notifier=notifier,
        data_dir=tmp_path / "data",
        linear_client=linear_client,
    )

    project = ProjectConfig(
        name="test",
        repo="/tmp",
        tasks={"t": TaskConfig(description="d", intent="i")},
    )
    run = RunRecord(
        id="r-1",
        project="test",
        task="t",
        trigger_type=TriggerType.LINEAR,
        started_at=datetime.now(UTC),
        status=RunStatus.FAILURE,
        model="sonnet",
        error_message="Claude timed out",
    )

    await executor._fail_agent_run(
        project,
        variables={
            "issue_id": "iss-1",
            "team_id": "team-1",
            "issue_identifier": "ENG-42",
            "issue_title": "Fix bug",
        },
        discord_msg_id="",
        run=run,
        attempt=1,
        max_attempts=1,
    )

    linear_client.post_comment.assert_called_once()
    comment_text = linear_client.post_comment.call_args[0][1]
    assert "Falha" in comment_text
    assert "Claude timed out" in comment_text
    linear_client.update_status.assert_called_once_with("iss-1", "team-1", "Todo")
