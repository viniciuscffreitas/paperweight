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


@pytest.mark.asyncio
async def test_executor_dry_run_emits_lifecycle_events(tmp_path):
    """Dry run emits task_started and task_completed lifecycle events."""
    from agents.budget import BudgetManager
    from agents.config import BudgetConfig, ExecutionConfig
    from agents.executor import Executor
    from agents.history import HistoryDB
    from agents.models import ProjectConfig, TaskConfig
    from agents.notifier import Notifier

    events = []

    async def on_event(run_id, event):
        events.append((run_id, event))

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
    project = ProjectConfig(
        name="test",
        repo="/tmp/test",
        tasks={"hello": TaskConfig(description="t", prompt="hi", schedule="0 * * * *")},
    )
    await executor.run_task(project, "hello", trigger_type="manual")

    event_types = [e.type for _, e in events]
    assert "task_started" in event_types
    assert "task_completed" in event_types


@pytest.mark.asyncio
async def test_executor_budget_blocked_emits_lifecycle_event(executor_deps):
    """Budget exceeded emits task_started and task_failed events."""
    from datetime import UTC, datetime

    from agents.models import ProjectConfig, RunRecord, RunStatus, TaskConfig, TriggerType

    executor, db = executor_deps
    events = []

    async def on_event(run_id, event):
        events.append((run_id, event))

    executor.on_stream_event = on_event

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
    await executor.run_task(project, "hello", trigger_type="manual")

    event_types = [e.type for _, e in events]
    assert "task_started" in event_types
    assert "task_failed" in event_types


def test_appstate_has_run_events_store(tmp_path):
    """AppState exposes run_events dict for per-run event history."""
    from unittest.mock import AsyncMock

    from agents.budget import BudgetManager
    from agents.config import BudgetConfig, ExecutionConfig
    from agents.executor import Executor
    from agents.history import HistoryDB
    from agents.main import AppState
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
        on_stream_event=AsyncMock(),
    )
    state = AppState(
        projects={},
        executor=executor,
        history=db,
        budget=budget,
        notifier=notifier,
        github_secret="",
        linear_secret="",
    )
    assert hasattr(state, "run_events")
    assert isinstance(state.run_events, dict)


def test_executor_accepts_optional_linear_and_discord_clients(tmp_path):
    from unittest.mock import MagicMock

    from agents.config import ExecutionConfig
    from agents.executor import Executor

    executor = Executor(
        config=ExecutionConfig(dry_run=True),
        budget=MagicMock(),
        history=MagicMock(),
        notifier=MagicMock(),
        data_dir=tmp_path,
        linear_client=MagicMock(),
        discord_notifier=MagicMock(),
    )
    assert executor.linear_client is not None
    assert executor.discord_notifier is not None


def test_executor_works_without_optional_clients(tmp_path):
    from unittest.mock import MagicMock

    from agents.config import ExecutionConfig
    from agents.executor import Executor

    executor = Executor(
        config=ExecutionConfig(dry_run=True),
        budget=MagicMock(),
        history=MagicMock(),
        notifier=MagicMock(),
        data_dir=tmp_path,
    )
    assert executor.linear_client is None
    assert executor.discord_notifier is None


def test_generate_run_id_includes_issue_id():
    from agents.executor import generate_run_id

    run_id = generate_run_id("sekit", "issue-resolver", issue_id="issue-abc-123")
    assert "issue-abc-123" in run_id
    assert "sekit" in run_id


def test_generate_run_id_works_without_issue_id():
    from agents.executor import generate_run_id

    run_id = generate_run_id("sekit", "dep-update")
    assert "sekit" in run_id
    assert "dep-update" in run_id


@pytest.mark.asyncio
async def test_run_task_agent_issue_calls_linear_and_discord_on_dry_run(tmp_path):
    from unittest.mock import AsyncMock, MagicMock

    from agents.config import ExecutionConfig
    from agents.executor import Executor
    from agents.history import HistoryDB
    from agents.models import ProjectConfig, TaskConfig, TriggerConfig

    history = HistoryDB(tmp_path / "test.db")
    budget = MagicMock()
    budget.can_afford.return_value = True
    budget.get_status.return_value = MagicMock(is_warning=False)

    mock_linear = AsyncMock()
    mock_discord = AsyncMock()
    mock_discord.create_run_message.return_value = "msg-123"

    executor = Executor(
        config=ExecutionConfig(dry_run=True),
        budget=budget,
        history=history,
        notifier=AsyncMock(),
        data_dir=tmp_path,
        linear_client=mock_linear,
        discord_notifier=mock_discord,
    )

    project = ProjectConfig(
        name="testproj",
        repo="/tmp/repo",
        linear_team_id="team-1",
        discord_channel_id="chan-1",
        tasks={
            "issue-resolver": TaskConfig(
                description="Resolve issues",
                prompt="Resolve {{issue_title}}",
                trigger=TriggerConfig(type="linear", events=["Issue.create"]),
            )
        },
    )

    variables = {
        "issue_id": "issue-xyz",
        "issue_identifier": "TST-1",
        "issue_title": "Test issue",
        "issue_description": "Test description",
        "team_id": "team-1",
    }

    run = await executor.run_task(
        project, "issue-resolver", trigger_type="linear", variables=variables
    )

    assert run.status == "success"
    # Linear should have been called:
    # update_status("In Progress") + post_comment x2 + remove_label
    assert mock_linear.update_status.call_count >= 1
    assert mock_linear.post_comment.call_count >= 2
    mock_linear.remove_label.assert_called_once_with("issue-xyz", "agent")
    # Discord should have been notified
    mock_discord.create_run_message.assert_called_once_with("chan-1", "TST-1", "Test issue")
    mock_discord.finalize_run_message.assert_called_once()
    # run_id should contain issue_id for deduplication
    assert "issue-xyz" in run.id


def test_write_progress_log(tmp_path):
    from agents.executor import write_progress_log

    path = write_progress_log(
        tmp_path / "progress", "issue-abc", attempt=1,
        issue_title="Add pagination", issue_description="Add to user list",
    )
    assert path.exists()
    content = path.read_text()
    assert "Add pagination" in content
    assert "attempt 1" in content.lower()


def test_append_progress_log(tmp_path):
    from agents.executor import append_progress_log, write_progress_log

    write_progress_log(
        tmp_path / "progress", "issue-abc", attempt=1, issue_title="T", issue_description="D"
    )
    append_progress_log(
        tmp_path / "progress", "issue-abc", attempt=1, error="Tests failed: 3 assertions"
    )
    content = (tmp_path / "progress" / "issue-abc.txt").read_text()
    assert "Tests failed" in content


def test_delete_progress_log(tmp_path):
    from agents.executor import delete_progress_log, write_progress_log

    path = write_progress_log(
        tmp_path / "progress", "issue-abc", attempt=1, issue_title="T", issue_description="D"
    )
    assert path.exists()
    delete_progress_log(tmp_path / "progress", "issue-abc")
    assert not path.exists()
