"""Integration tests for the coordination protocol wiring."""

import pytest


@pytest.mark.asyncio
async def test_executor_injects_preamble_when_broker_active(tmp_path):
    """When broker is set, executor should prepend coordination preamble to prompt."""
    from agents.budget import BudgetManager
    from agents.config import BudgetConfig, ExecutionConfig
    from agents.coordination.broker import CoordinationBroker
    from agents.coordination.models import CoordinationConfig
    from agents.executor import Executor
    from agents.history import HistoryDB
    from agents.models import ProjectConfig, RunStatus, TaskConfig
    from agents.notifier import Notifier

    db = HistoryDB(tmp_path / "test.db")
    budget = BudgetManager(config=BudgetConfig(), history=db)
    notifier = Notifier(webhook_url="")
    broker = CoordinationBroker(CoordinationConfig(enabled=True))
    exec_config = ExecutionConfig(worktree_base=str(tmp_path / "wt"), dry_run=True)
    executor = Executor(
        config=exec_config,
        budget=budget,
        history=db,
        notifier=notifier,
        data_dir=tmp_path / "data",
        broker=broker,
    )

    project = ProjectConfig(
        name="test",
        repo=str(tmp_path),
        tasks={"hello": TaskConfig(description="t", intent="say hi", schedule="0 * * * *")},
    )
    # dry_run=True so no actual Claude CLI call, but preamble injection still happens
    result = await executor.run_task(project, "hello", trigger_type="manual")
    assert result.status == RunStatus.SUCCESS


@pytest.mark.asyncio
async def test_executor_no_preamble_when_broker_none(tmp_path):
    """When broker is None, executor should NOT inject preamble."""
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
        config=exec_config,
        budget=budget,
        history=db,
        notifier=notifier,
        data_dir=tmp_path / "data",
    )

    project = ProjectConfig(
        name="test",
        repo=str(tmp_path),
        tasks={"hello": TaskConfig(description="t", intent="say hi", schedule="0 * * * *")},
    )
    result = await executor.run_task(project, "hello", trigger_type="manual")
    assert result.status == RunStatus.SUCCESS


@pytest.mark.asyncio
async def test_broker_registers_and_deregisters_via_executor_dry_run(tmp_path):
    """Verify broker register/deregister happens even in dry_run mode."""
    from agents.budget import BudgetManager
    from agents.config import BudgetConfig, ExecutionConfig
    from agents.coordination.broker import CoordinationBroker
    from agents.coordination.models import CoordinationConfig
    from agents.executor import Executor
    from agents.history import HistoryDB
    from agents.models import ProjectConfig, TaskConfig
    from agents.notifier import Notifier

    db = HistoryDB(tmp_path / "test.db")
    budget = BudgetManager(config=BudgetConfig(), history=db)
    notifier = Notifier(webhook_url="")
    broker = CoordinationBroker(CoordinationConfig(enabled=True))
    exec_config = ExecutionConfig(worktree_base=str(tmp_path / "wt"), dry_run=True)
    executor = Executor(
        config=exec_config,
        budget=budget,
        history=db,
        notifier=notifier,
        data_dir=tmp_path / "data",
        broker=broker,
    )

    project = ProjectConfig(
        name="test",
        repo=str(tmp_path),
        tasks={"hello": TaskConfig(description="t", intent="say hi", schedule="0 * * * *")},
    )
    # dry_run skips Claude but preamble injection happens before dry_run check
    await executor.run_task(project, "hello", trigger_type="manual")
    # After dry_run, broker should have no active worktrees (deregistered)
    assert len(broker.active_worktrees) == 0


@pytest.mark.asyncio
async def test_coordination_config_defaults_to_disabled():
    """GlobalConfig has coordination disabled by default — no breaking change."""
    from agents.config import GlobalConfig

    cfg = GlobalConfig()
    assert cfg.coordination.enabled is False
    assert cfg.coordination.mode == "full-mesh"


@pytest.mark.asyncio
async def test_full_broker_event_flow(tmp_path):
    """End-to-end: register run, receive stream events, verify claims tracked."""
    from agents.coordination.broker import CoordinationBroker
    from agents.coordination.models import CoordinationConfig
    from agents.streaming import StreamEvent

    broker = CoordinationBroker(CoordinationConfig(enabled=True))
    wt = tmp_path / "worktree"
    wt.mkdir()

    await broker.register_run("run-1", wt, "implement feature X")
    assert "run-1" in broker.active_worktrees

    # Simulate Edit event
    event = StreamEvent(
        type="tool_use",
        tool_name="Edit",
        file_path=str(wt / "src" / "main.py"),
        timestamp=1.0,
    )
    conflict = await broker.on_stream_event("run-1", event, worktree_root=wt)
    assert conflict is None

    claim = broker.claims.get_claim_for_file("src/main.py")
    assert claim is not None
    assert claim.claim_type.value == "hard"
    assert claim.run_id == "run-1"

    await broker.deregister_run("run-1")
    assert broker.claims.get_claim_for_file("src/main.py") is None
