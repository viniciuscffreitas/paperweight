"""Tests for executor_git: PR creation helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.executor_git import create_pr


def _make_project(base_branch: str = "main", name: str = "myproject") -> MagicMock:
    proj = MagicMock()
    proj.name = name
    proj.base_branch = base_branch
    return proj


# ---------------------------------------------------------------------------
# create_pr — no commits → returns None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_pr_returns_none_when_no_commits():
    async def run_cmd(cmd, cwd):
        if "log" in cmd:
            return ""  # empty → no commits
        return ""

    result = await create_pr(
        run_cmd_fn=run_cmd,
        cwd="/tmp/wt",
        project=_make_project(),
        task_name="lint",
        branch="agents/lint-abc",
        autonomy="manual",
    )
    assert result is None


# ---------------------------------------------------------------------------
# create_pr — with commits → pushes and creates PR
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_pr_pushes_and_returns_url():
    calls: list[list[str]] = []

    async def run_cmd(cmd, cwd):
        calls.append(cmd)
        if "log" in cmd:
            return "abc1234 fix something\n"
        if "diff" in cmd:
            return "1 file changed\n"
        if "push" in cmd:
            return ""
        if "create" in cmd:
            return "https://github.com/org/repo/pull/7\n"
        return ""

    with patch("agents.executor_git.build_pr_body", return_value="body"):
        result = await create_pr(
            run_cmd_fn=run_cmd,
            cwd="/tmp/wt",
            project=_make_project(),
            task_name="lint",
            branch="agents/lint-abc",
            autonomy="manual",
        )

    assert result == "https://github.com/org/repo/pull/7"
    push_calls = [c for c in calls if "push" in c]
    assert len(push_calls) == 1
    pr_calls = [c for c in calls if "create" in c]
    assert len(pr_calls) == 1


# ---------------------------------------------------------------------------
# create_pr — auto-merge mode → calls gh pr merge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_pr_auto_merge_calls_merge():
    merge_calls: list[list[str]] = []

    async def run_cmd(cmd, cwd):
        if "log" in cmd:
            return "abc1234 fix\n"
        if "diff" in cmd:
            return "1 file changed\n"
        if "push" in cmd:
            return ""
        if "create" in cmd:
            return "https://github.com/org/repo/pull/8\n"
        if "merge" in cmd:
            merge_calls.append(cmd)
            return ""
        return ""

    with patch("agents.executor_git.build_pr_body", return_value="body"):
        result = await create_pr(
            run_cmd_fn=run_cmd,
            cwd="/tmp/wt",
            project=_make_project(),
            task_name="deploy",
            branch="agents/deploy-xyz",
            autonomy="auto-merge",
        )

    assert result == "https://github.com/org/repo/pull/8"
    assert len(merge_calls) == 1
    assert "--squash" in merge_calls[0]


# ---------------------------------------------------------------------------
# create_pr — auto-merge failure is swallowed (warning only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_pr_auto_merge_failure_does_not_raise():
    async def run_cmd(cmd, cwd):
        if "log" in cmd:
            return "abc1234 fix\n"
        if "diff" in cmd:
            return "1 file changed\n"
        if "push" in cmd:
            return ""
        if "create" in cmd:
            return "https://github.com/org/repo/pull/9\n"
        if "merge" in cmd:
            raise RuntimeError("merge not allowed")
        return ""

    with patch("agents.executor_git.build_pr_body", return_value="body"):
        result = await create_pr(
            run_cmd_fn=run_cmd,
            cwd="/tmp/wt",
            project=_make_project(),
            task_name="deploy",
            branch="agents/deploy-xyz",
            autonomy="auto-merge",
        )

    # PR URL still returned even when auto-merge fails
    assert result == "https://github.com/org/repo/pull/9"
