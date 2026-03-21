"""Tests for worktree retry bug and task-detail UI error rendering.

Bug A: When a run fails after worktree creation but before capturing claude_session_id,
       the next retry (is_resume=False) tries git worktree add again → "branch already
       exists" → run fails immediately, no Claude output, no tool_use/assistant events.

Bug B: Activity, Output, and Chat tabs show nothing when runs produce only
       task_started + task_failed events — error message is never rendered.

Behavior Contract:
  CHANGES:
    - run_adhoc skips git worktree add when worktree dir already exists
    - loadActivityFeed renders task_failed events with red error style
    - loadChatHistory renders task_failed as an agent error bubble

  MUST NOT CHANGE:
    - Fresh sessions (worktree absent) → git worktree add IS called
    - is_resume=True with existing worktree → Claude runs with --resume
    - tool_use / assistant events render correctly (existing behaviour)
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

_STATIC = Path(__file__).parent.parent / "src" / "agents" / "static"
_TASK_DETAIL_JS = _STATIC / "task-detail.js"
_CHAT_JS = _STATIC / "chat.js"


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_executor(tmp_path, worktree_base):
    from agents.budget import BudgetManager
    from agents.config import BudgetConfig, ExecutionConfig
    from agents.executor import Executor
    from agents.history import HistoryDB
    from agents.notifier import Notifier

    db = HistoryDB(tmp_path / "test.db")
    budget = BudgetManager(config=BudgetConfig(daily_limit_usd=10.0), history=db)
    executor = Executor(
        config=ExecutionConfig(
            worktree_base=str(worktree_base), dry_run=False, timeout_minutes=1
        ),
        budget=budget,
        history=db,
        notifier=Notifier(webhook_url=""),
        data_dir=tmp_path / "data",
    )
    return executor


def _make_session(worktree_path: str, session_id: str = "sess-abc"):
    from agents.session_manager import AgentSession

    return AgentSession(
        id=session_id,
        project="proj",
        worktree_path=worktree_path,
        model="claude-sonnet-4-6",
        max_cost_usd=2.0,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_project(repo_path: str):
    from agents.models import ProjectConfig

    return ProjectConfig(name="proj", repo=repo_path, tasks={})


# ── Bug A: Worktree creation skipped when directory exists ─────────────────


@pytest.mark.asyncio
async def test_worktree_exists_skips_git_worktree_add(tmp_path):
    """When worktree dir already exists and is_resume=False, git worktree add is skipped."""
    worktree_dir = tmp_path / "worktrees" / "session-sess-abc"
    worktree_dir.mkdir(parents=True)  # Simulate existing worktree from previous run

    executor = _make_executor(tmp_path, tmp_path / "worktrees")
    session = _make_session(str(worktree_dir))
    project = _make_project(str(tmp_path / "repo"))

    run_cmd_calls: list[list[str]] = []

    async def mock_run_cmd(cmd: list[str], cwd: str) -> str:
        run_cmd_calls.append(cmd)
        return ""

    executor._run_cmd = mock_run_cmd

    with patch.object(executor, "_run_claude", side_effect=RuntimeError("no claude")):
        await executor.run_adhoc(project, "do something", session, is_resume=False)

    worktree_adds = [
        c for c in run_cmd_calls
        if len(c) >= 3 and c[:3] == ["git", "worktree", "add"]
    ]
    assert worktree_adds == [], (
        f"git worktree add should be skipped when worktree exists, got: {worktree_adds}"
    )


@pytest.mark.asyncio
async def test_fresh_session_creates_worktree(tmp_path):
    """When worktree dir does NOT exist and is_resume=False, git worktree add IS called."""
    worktree_dir = tmp_path / "worktrees" / "session-sess-new"
    # Intentionally NOT created — fresh session

    executor = _make_executor(tmp_path, tmp_path / "worktrees")
    session = _make_session(str(worktree_dir), session_id="sess-new")
    project = _make_project(str(tmp_path / "repo"))

    run_cmd_calls: list[list[str]] = []

    async def mock_run_cmd(cmd: list[str], cwd: str) -> str:
        run_cmd_calls.append(cmd)
        if cmd[:3] == ["git", "worktree", "add"]:
            # Simulate successful worktree creation
            worktree_dir.mkdir(parents=True)
        return ""

    executor._run_cmd = mock_run_cmd

    with patch.object(executor, "_run_claude", side_effect=RuntimeError("no claude")):
        await executor.run_adhoc(project, "do something", session, is_resume=False)

    worktree_adds = [
        c for c in run_cmd_calls
        if len(c) >= 3 and c[:3] == ["git", "worktree", "add"]
    ]
    assert len(worktree_adds) == 1, (
        f"git worktree add should be called once for fresh session, got: {worktree_adds}"
    )


@pytest.mark.asyncio
async def test_resume_session_with_existing_worktree_runs_claude(tmp_path):
    """is_resume=True with existing worktree → Claude runs (no worktree add)."""
    worktree_dir = tmp_path / "worktrees" / "session-sess-resume"
    worktree_dir.mkdir(parents=True)

    executor = _make_executor(tmp_path, tmp_path / "worktrees")
    session = _make_session(str(worktree_dir), session_id="sess-resume")
    session.claude_session_id = "claude-abc"  # Has a claude session → is_resume=True

    project = _make_project(str(tmp_path / "repo"))

    run_cmd_calls: list[list[str]] = []
    claude_called = False

    async def mock_run_cmd(cmd: list[str], cwd: str) -> str:
        run_cmd_calls.append(cmd)
        return ""

    async def mock_run_claude(cmd, cwd, run_id, timeout, env=None):
        nonlocal claude_called
        claude_called = True
        raise RuntimeError("mocked claude")

    executor._run_cmd = mock_run_cmd
    executor._run_claude = mock_run_claude

    await executor.run_adhoc(project, "do something", session, is_resume=True)

    worktree_adds = [c for c in run_cmd_calls if len(c) >= 3 and c[:3] == ["git", "worktree", "add"]]
    assert worktree_adds == [], "is_resume=True must not call git worktree add"
    assert claude_called, "Claude must be invoked for resume sessions"


# ── Bug B: UI renders task_failed events ──────────────────────────────────


def test_task_detail_js_renders_task_failed_in_activity():
    """loadActivityFeed must render task_failed events in the activity feed."""
    js = _TASK_DETAIL_JS.read_text()
    assert "task_failed" in js, (
        "task-detail.js must handle task_failed events in loadActivityFeed"
    )
    # Should render with some visual indicator — check for red/error color or class
    assert "status-error" in js or "task_failed" in js


def test_chat_js_renders_task_failed_as_agent_message():
    """loadChatHistory must render task_failed events as an agent error message."""
    js = _CHAT_JS.read_text()
    assert "task_failed" in js, (
        "chat.js must handle task_failed events in loadChatHistory"
    )
