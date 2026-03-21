"""E2E / integration tests for Executor error paths.

Covers:
1. Budget exhaustion before run starts (tight daily limit + pre-existing spend)
2. Timeout handling (_run_claude raises TimeoutError)
3. Generic exception during execution (RuntimeError from _run_claude)
4. Successful dry run with coordination broker
5. Run record persistence verified via HistoryDB.get_run()
6. Cancel running process via cancel_run()
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.e2e

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_executor(tmp_path, *, dry_run=False, daily_limit=10.0, broker=None):
    """Return a fully wired (Executor, HistoryDB) pair for use in tests."""
    from agents.budget import BudgetManager
    from agents.config import BudgetConfig, ExecutionConfig
    from agents.executor import Executor
    from agents.history import HistoryDB
    from agents.notifier import Notifier

    db = HistoryDB(tmp_path / "test.db")
    budget = BudgetManager(
        config=BudgetConfig(daily_limit_usd=daily_limit, pause_on_limit=True),
        history=db,
    )
    notifier = Notifier(webhook_url="")
    exec_config = ExecutionConfig(
        worktree_base=str(tmp_path / "worktrees"),
        dry_run=dry_run,
        timeout_minutes=1,
    )
    executor = Executor(
        config=exec_config,
        budget=budget,
        history=db,
        notifier=notifier,
        data_dir=tmp_path / "data",
        broker=broker,
    )
    return executor, db


def _make_project(max_cost=0.50):
    """Return a minimal ProjectConfig with one task."""
    from agents.models import ProjectConfig, TaskConfig

    return ProjectConfig(
        name="test-project",
        repo="/tmp/test-repo",
        tasks={
            "do-work": TaskConfig(
                description="test task",
                prompt="do something useful",
                schedule="0 * * * *",
                max_cost_usd=max_cost,
            )
        },
    )


def _insert_cost(db, cost_usd: float) -> None:
    """Pre-seed the DB with a completed run that consumed *cost_usd* today."""
    from agents.models import RunRecord, RunStatus, TriggerType

    db.insert_run(
        RunRecord(
            id="seed-run",
            project="other",
            task="other-task",
            trigger_type=TriggerType.MANUAL,
            started_at=datetime.now(UTC),
            status=RunStatus.SUCCESS,
            model="sonnet",
            cost_usd=cost_usd,
        )
    )


# ---------------------------------------------------------------------------
# 1. Budget exhaustion before run starts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_exhaustion_before_run(tmp_path):
    """
    Daily limit=$1, pre-existing cost=$0.90, task max_cost=$0.50.
    Remaining budget ($0.10) < max_cost ($0.50) → FAILURE with 'Budget exceeded'.
    """
    from agents.models import RunStatus

    executor, db = _make_executor(tmp_path, daily_limit=1.0)
    _insert_cost(db, 0.90)

    project = _make_project(max_cost=0.50)
    run = await executor.run_task(project, "do-work", trigger_type="manual")

    assert run.status == RunStatus.FAILURE
    assert run.error_message is not None
    assert "Budget exceeded" in run.error_message


# ---------------------------------------------------------------------------
# 2. Timeout handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_results_in_timeout_status(tmp_path):
    """
    _run_claude raises TimeoutError → status=TIMEOUT, error contains 'Timed out'.
    """
    from agents.models import RunStatus

    executor, _db = _make_executor(tmp_path, dry_run=False)
    project = _make_project()

    # We need a real git repo so worktree setup doesn't fail first.
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=str(repo),
        check=True,
        capture_output=True,
        env={
            **__import__("os").environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )
    project = project.model_copy(update={"repo": str(repo)})

    with patch.object(executor, "_run_claude", new=AsyncMock(side_effect=TimeoutError)):
        run = await executor.run_task(project, "do-work", trigger_type="manual")

    assert run.status == RunStatus.TIMEOUT
    assert run.error_message is not None
    assert "Timed out" in run.error_message


# ---------------------------------------------------------------------------
# 3. Generic exception during execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generic_exception_results_in_failure(tmp_path):
    """
    _run_claude raises RuntimeError('git worktree failed') → status=FAILURE,
    error_message contains the original exception message.
    """
    from agents.models import RunStatus

    executor, _db = _make_executor(tmp_path, dry_run=False)

    import subprocess

    repo = tmp_path / "repo2"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=str(repo),
        check=True,
        capture_output=True,
        env={
            **__import__("os").environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )
    project = _make_project()
    project = project.model_copy(update={"repo": str(repo)})

    error_msg = "git worktree failed"
    with patch.object(executor, "_run_claude", new=AsyncMock(side_effect=RuntimeError(error_msg))):
        run = await executor.run_task(project, "do-work", trigger_type="manual")

    assert run.status == RunStatus.FAILURE
    assert run.error_message is not None
    assert "git worktree" in run.error_message


# ---------------------------------------------------------------------------
# 4. Dry run with coordination broker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_with_broker_succeeds_and_no_active_worktrees(tmp_path):
    """
    dry_run=True with a broker → SUCCESS, broker has no active worktrees after run.
    """
    from agents.models import RunStatus

    broker = AsyncMock()
    # Simulate no pending mediations so cleanup is allowed
    broker.has_pending_mediations.return_value = False

    executor, _db = _make_executor(tmp_path, dry_run=True, broker=broker)
    project = _make_project()
    run = await executor.run_task(project, "do-work", trigger_type="manual")

    assert run.status == RunStatus.SUCCESS
    assert run.cost_usd == 0.0
    # In dry_run mode the worktree is never created, so the broker's
    # register/deregister cycle should NOT have been called.
    broker.register_run.assert_not_called()
    broker.deregister_run.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Run record persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_persists_run_record_to_sqlite(tmp_path):
    """
    After a dry run the RunRecord must be queryable via history.get_run(run_id)
    with correct project, task, trigger_type, status, and cost_usd.
    """
    from agents.models import RunStatus, TriggerType

    executor, db = _make_executor(tmp_path, dry_run=True)
    project = _make_project()
    run = await executor.run_task(project, "do-work", trigger_type="manual")

    persisted = db.get_run(run.id)

    assert persisted is not None
    assert persisted.id == run.id
    assert persisted.project == "test-project"
    assert persisted.task == "do-work"
    assert persisted.trigger_type == TriggerType.MANUAL
    assert persisted.status == RunStatus.SUCCESS
    assert persisted.cost_usd == 0.0
    assert persisted.finished_at is not None


# ---------------------------------------------------------------------------
# 6. Cancel running process
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_run_terminates_tracked_process(tmp_path):
    """
    cancel_run(run_id) should call proc.terminate() on the tracked subprocess
    and return True; an unknown run_id returns False.
    """
    executor, _db = _make_executor(tmp_path)

    mock_proc = MagicMock()
    mock_proc.terminate = MagicMock()

    run_id = "test-run-cancel-001"
    executor._running_processes[run_id] = mock_proc

    result = await executor.cancel_run(run_id)

    assert result is True
    mock_proc.terminate.assert_called_once()

    # Unknown run_id returns False
    result_unknown = await executor.cancel_run("nonexistent-run-id")
    assert result_unknown is False
