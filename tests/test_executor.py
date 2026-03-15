import json
from datetime import UTC, datetime

import pytest


@pytest.fixture
def executor_deps(tmp_path):
    from agents.budget import BudgetManager
    from agents.config import BudgetConfig, ExecutionConfig
    from agents.executor import Executor
    from agents.history import HistoryDB
    from agents.notifier import Notifier

    db = HistoryDB(tmp_path / "test.db")
    budget_config = BudgetConfig(daily_limit_usd=10.0)
    budget = BudgetManager(config=budget_config, history=db)
    notifier = Notifier(webhook_url="")
    exec_config = ExecutionConfig(
        worktree_base=str(tmp_path / "worktrees"), dry_run=False, timeout_minutes=1
    )
    data_dir = tmp_path / "data" / "runs"
    data_dir.mkdir(parents=True)
    executor = Executor(
        config=exec_config, budget=budget, history=db, notifier=notifier, data_dir=tmp_path / "data"
    )
    return executor, db


def test_generate_run_id():
    from agents.executor import generate_run_id

    run_id = generate_run_id("sekit", "dep-update")
    assert run_id.startswith("sekit-dep-update-")
    assert len(run_id) > len("sekit-dep-update-")


def test_generate_branch_name():
    from agents.executor import generate_branch_name

    branch = generate_branch_name("agents/", "dep-update")
    assert branch.startswith("agents/dep-update-")


@pytest.mark.asyncio
async def test_executor_dry_run(tmp_path):
    from agents.budget import BudgetManager
    from agents.config import BudgetConfig, ExecutionConfig
    from agents.executor import Executor
    from agents.history import HistoryDB
    from agents.models import ProjectConfig, RunStatus, TaskConfig
    from agents.notifier import Notifier

    db = HistoryDB(tmp_path / "test.db")
    budget = BudgetManager(config=BudgetConfig(), history=db)
    notifier = Notifier(webhook_url="")
    exec_config = ExecutionConfig(worktree_base=str(tmp_path / "wt"), dry_run=True)
    executor = Executor(
        config=exec_config, budget=budget, history=db, notifier=notifier, data_dir=tmp_path / "data"
    )
    project = ProjectConfig(
        name="test",
        repo="/tmp/test",
        tasks={"hello": TaskConfig(description="t", prompt="hi", schedule="0 * * * *")},
    )
    result = await executor.run_task(project, "hello", trigger_type="manual")
    assert result.status == RunStatus.SUCCESS
    assert result.cost_usd == 0.0


@pytest.mark.asyncio
async def test_executor_budget_exceeded(executor_deps):
    from agents.models import ProjectConfig, RunRecord, RunStatus, TaskConfig, TriggerType

    executor, db = executor_deps
    now = datetime.now(UTC)
    db.insert_run(
        RunRecord(
            id="r-old",
            project="p",
            task="t",
            trigger_type=TriggerType.MANUAL,
            started_at=now,
            status=RunStatus.SUCCESS,
            model="s",
            cost_usd=10.0,
        )
    )
    project = ProjectConfig(
        name="test",
        repo="/tmp/test",
        tasks={"hello": TaskConfig(description="t", prompt="hi", schedule="0 * * * *")},
    )
    result = await executor.run_task(project, "hello", trigger_type="manual")
    assert result.status == RunStatus.FAILURE
    assert "budget" in result.error_message.lower()


def test_parse_claude_output():
    from agents.executor import parse_claude_output

    raw = json.dumps(
        {
            "result": "Done! Created PR.",
            "is_error": False,
            "total_cost_usd": 0.45,
            "num_turns": 8,
            "usage": {"input_tokens": 5000, "output_tokens": 1200},
        }
    )
    parsed = parse_claude_output(raw)
    assert parsed.cost_usd == pytest.approx(0.45)
    assert parsed.num_turns == 8
    assert parsed.is_error is False
    assert parsed.result == "Done! Created PR."


def test_parse_claude_output_error():
    from agents.executor import parse_claude_output

    raw = json.dumps(
        {"result": "Error occurred", "is_error": True, "total_cost_usd": 0.10, "num_turns": 3}
    )
    parsed = parse_claude_output(raw)
    assert parsed.is_error is True


@pytest.mark.asyncio
async def test_executor_accepts_stream_callback(tmp_path):
    from agents.budget import BudgetManager
    from agents.config import BudgetConfig, ExecutionConfig
    from agents.executor import Executor
    from agents.history import HistoryDB
    from agents.notifier import Notifier

    events_received = []

    async def on_event(run_id, event):
        events_received.append((run_id, event))

    db = HistoryDB(tmp_path / "test.db")
    budget = BudgetManager(config=BudgetConfig(), history=db)
    notifier = Notifier(webhook_url="")
    exec_config = ExecutionConfig(worktree_base=str(tmp_path / "wt"), dry_run=True)
    executor = Executor(
        config=exec_config,
        budget=budget,
        history=db,
        notifier=notifier,
        data_dir=tmp_path / "data",
        on_stream_event=on_event,
    )
    assert executor.on_stream_event is on_event
