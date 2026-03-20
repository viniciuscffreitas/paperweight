import pytest
from datetime import UTC, datetime


@pytest.fixture
def adhoc_deps(tmp_path):
    from agents.budget import BudgetManager
    from agents.config import BudgetConfig, ExecutionConfig
    from agents.executor import Executor
    from agents.history import HistoryDB
    from agents.notifier import Notifier
    from agents.session_manager import AgentSession

    db = HistoryDB(tmp_path / "test.db")
    budget_config = BudgetConfig(daily_limit_usd=10.0)
    budget = BudgetManager(config=budget_config, history=db)
    notifier = Notifier(webhook_url="")
    exec_config = ExecutionConfig(
        worktree_base=str(tmp_path / "worktrees"), dry_run=True, timeout_minutes=1
    )
    executor = Executor(
        config=exec_config,
        budget=budget,
        history=db,
        notifier=notifier,
        data_dir=tmp_path / "data",
    )
    session = AgentSession(
        id="test-sess",
        project="paperweight",
        worktree_path=str(tmp_path / "worktrees" / "session-test-sess"),
        model="sonnet",
        max_cost_usd=2.0,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    return executor, db, session


@pytest.mark.asyncio
async def test_run_adhoc_creates_run_record(adhoc_deps):
    executor, db, session = adhoc_deps
    from agents.models import ProjectConfig, TaskConfig

    project = ProjectConfig(
        name="paperweight",
        repo="/tmp/fake-repo",
        tasks={"dummy": TaskConfig(description="x", intent="x")},
    )
    run = await executor.run_adhoc(project, "test prompt", session)
    assert run.task == "test prompt"
    assert run.trigger_type == "agent"
    assert run.session_id == "test-sess"
    assert run.project == "paperweight"


@pytest.mark.asyncio
async def test_run_adhoc_budget_exceeded(adhoc_deps):
    executor, db, session = adhoc_deps
    from agents.models import ProjectConfig, RunStatus, TaskConfig

    executor.budget.config.daily_limit_usd = 0.0
    project = ProjectConfig(
        name="paperweight",
        repo="/tmp/fake-repo",
        tasks={"dummy": TaskConfig(description="x", intent="x")},
    )
    run = await executor.run_adhoc(project, "test prompt", session)
    assert run.status == RunStatus.FAILURE
    assert "Budget" in (run.error_message or "")


@pytest.mark.asyncio
async def test_run_adhoc_dry_run_returns_success(adhoc_deps):
    executor, db, session = adhoc_deps
    from agents.models import ProjectConfig, RunStatus, TaskConfig

    project = ProjectConfig(
        name="paperweight",
        repo="/tmp/fake-repo",
        tasks={"dummy": TaskConfig(description="x", intent="x")},
    )
    # dry_run=True is already set in the fixture
    run = await executor.run_adhoc(project, "hello session", session)
    assert run.status == RunStatus.SUCCESS
    assert run.cost_usd == 0.0
    assert run.finished_at is not None


@pytest.mark.asyncio
async def test_run_adhoc_accepts_custom_run_id(adhoc_deps):
    executor, db, session = adhoc_deps
    from agents.models import ProjectConfig, TaskConfig

    project = ProjectConfig(
        name="paperweight",
        repo="/tmp/fake-repo",
        tasks={"dummy": TaskConfig(description="x", intent="x")},
    )
    custom_id = "custom-run-001"
    run = await executor.run_adhoc(project, "prompt", session, run_id=custom_id)
    assert run.id == custom_id


@pytest.mark.asyncio
async def test_run_adhoc_persisted_in_history(adhoc_deps):
    executor, db, session = adhoc_deps
    from agents.models import ProjectConfig, TaskConfig

    project = ProjectConfig(
        name="paperweight",
        repo="/tmp/fake-repo",
        tasks={"dummy": TaskConfig(description="x", intent="x")},
    )
    run = await executor.run_adhoc(project, "check history", session)
    record = db.get_run(run.id)
    assert record is not None
    assert record.session_id == "test-sess"


@pytest.mark.asyncio
async def test_run_adhoc_resume_missing_worktree_raises(adhoc_deps, tmp_path):
    executor, db, session = adhoc_deps
    from agents.models import ProjectConfig, TaskConfig

    # dry_run is True but we are testing resume validation path,
    # so disable dry_run to reach worktree validation
    executor.config.dry_run = False

    project = ProjectConfig(
        name="paperweight",
        repo="/tmp/fake-repo",
        tasks={"dummy": TaskConfig(description="x", intent="x")},
    )
    # Worktree does NOT exist — should return FAILURE with error message
    run = await executor.run_adhoc(project, "resume test", session, is_resume=True)
    assert run.status.value == "failure"
    assert "orktree" in (run.error_message or "")  # "Worktree not found" or similar
