from datetime import datetime

import pytest

from agents.models import (
    AggregatedEvent,
    NotificationRule,
    ProjectRecord,
    ProjectSource,
    TaskRecord,
)


def test_trigger_config_creation():
    from agents.models import TriggerConfig

    trigger = TriggerConfig(
        type="github",
        events=["check_suite.completed"],
        filter={"conclusion": "failure"},
    )
    assert trigger.type == "github"
    assert trigger.events == ["check_suite.completed"]
    assert trigger.filter == {"conclusion": "failure"}


def test_task_config_defaults():
    from agents.models import TaskConfig

    task = TaskConfig(description="test", prompt="do something", schedule="0 3 * * MON")
    assert task.model == "sonnet"
    assert task.max_cost_usd == 5.00
    assert task.autonomy == "pr-only"
    assert task.trigger is None


def test_task_config_schedule_and_trigger_mutually_exclusive():
    from agents.models import TaskConfig, TriggerConfig

    with pytest.raises(ValueError, match="mutually exclusive"):
        TaskConfig(
            description="test",
            prompt="do something",
            schedule="0 3 * * MON",
            trigger=TriggerConfig(type="github", events=["push"]),
        )


def test_task_config_allows_manual_no_schedule_no_trigger() -> None:
    """Manual tasks have neither schedule nor trigger — this is now valid."""
    from agents.models import TaskConfig

    task = TaskConfig(description="Manual task", intent="Do something")
    assert task.schedule is None
    assert task.trigger is None


def test_project_config_creation():
    from agents.models import ProjectConfig, TaskConfig

    project = ProjectConfig(
        name="sekit",
        repo="/Users/vini/Developer/sekit",
        tasks={
            "dep-update": TaskConfig(
                description="Update deps", prompt="update deps", schedule="0 3 * * MON"
            )
        },
    )
    assert project.name == "sekit"
    assert project.base_branch == "main"
    assert project.branch_prefix == "agents/"
    assert project.notify == "slack"


def test_run_record_creation():
    from agents.models import RunRecord, RunStatus, TriggerType

    run = RunRecord(
        id="run-123",
        project="sekit",
        task="dep-update",
        trigger_type=TriggerType.SCHEDULE,
        started_at=datetime(2026, 3, 14, 3, 0, 0),
        status=RunStatus.RUNNING,
        model="sonnet",
    )
    assert run.id == "run-123"
    assert run.status == RunStatus.RUNNING
    assert run.cost_usd is None


def test_budget_status():
    from agents.models import BudgetStatus

    status = BudgetStatus(daily_limit_usd=10.0, spent_today_usd=7.5)
    assert status.remaining_usd == 2.5
    assert status.is_warning is True
    assert status.is_exceeded is False


def test_budget_status_exceeded():
    from agents.models import BudgetStatus

    status = BudgetStatus(daily_limit_usd=10.0, spent_today_usd=10.5)
    assert status.remaining_usd == 0.0
    assert status.is_exceeded is True


def test_task_config_with_intent():
    from agents.models import TaskConfig

    task = TaskConfig(
        description="fix ci",
        intent="Investigate and fix CI failure",
        context_hints=["Check Sentry for recent errors"],
        schedule="0 3 * * *",
    )
    assert task.intent == "Investigate and fix CI failure"
    assert task.context_hints == ["Check Sentry for recent errors"]
    assert task.prompt is None


def test_task_config_backwards_compat_prompt_only():
    from agents.models import TaskConfig

    task = TaskConfig(description="test", prompt="do something", schedule="0 3 * * MON")
    assert task.prompt == "do something"
    assert task.intent == ""


def test_task_config_requires_intent_or_prompt():
    from agents.models import TaskConfig

    with pytest.raises(ValueError, match=r"intent.*prompt"):
        TaskConfig(description="test", schedule="0 3 * * MON")


def test_project_config_linear_and_discord_defaults():
    from agents.models import ProjectConfig, TaskConfig

    project = ProjectConfig(
        name="test",
        repo="/tmp/repo",
        tasks={"t": TaskConfig(description="test", prompt="do it", schedule="0 3 * * MON")},
    )
    assert project.linear_team_id == ""
    assert project.discord_channel_id == ""


def test_project_config_with_linear_and_discord():
    from agents.models import ProjectConfig, TaskConfig

    project = ProjectConfig(
        name="test",
        repo="/tmp/repo",
        linear_team_id="TEAM-123",
        discord_channel_id="123456789",
        tasks={"t": TaskConfig(description="test", prompt="do it", schedule="0 3 * * MON")},
    )
    assert project.linear_team_id == "TEAM-123"
    assert project.discord_channel_id == "123456789"


def test_project_record_creation() -> None:
    p = ProjectRecord(id="momease", name="MomEase", repo_path="/repos/momease")
    assert p.id == "momease"
    assert p.default_branch == "main"
    assert p.created_at is not None


def test_project_source_creation() -> None:
    s = ProjectSource(
        id="src-1",
        project_id="momease",
        source_type="linear",
        source_id="LIN-123",
        source_name="MomEase Project",
    )
    assert s.enabled is True
    assert s.config == {}


def test_task_record_creation() -> None:
    t = TaskRecord(
        id="task-1",
        project_id="momease",
        name="Fix bugs",
        intent="Fix all open bugs",
        trigger_type="manual",
        model="sonnet",
        max_budget=5.0,
        autonomy="pr-only",
    )
    assert t.enabled is True
    assert t.trigger_config == {}


def test_task_record_schedule_trigger() -> None:
    t = TaskRecord(
        id="task-2",
        project_id="momease",
        name="Daily review",
        intent="Review open PRs",
        trigger_type="schedule",
        trigger_config={"cron": "0 9 * * *"},
        model="sonnet",
        max_budget=5.0,
        autonomy="pr-only",
    )
    assert t.trigger_config["cron"] == "0 9 * * *"


def test_aggregated_event_creation() -> None:
    e = AggregatedEvent(
        id="evt-1",
        project_id="momease",
        source="linear",
        event_type="issue_created",
        title="Fix login crash",
        timestamp="2026-03-16T10:00:00Z",
        source_item_id="LIN-42",
    )
    assert e.priority == "none"
    assert e.raw_data == {}


def test_notification_rule_creation() -> None:
    r = NotificationRule(
        id="rule-1",
        project_id="momease",
        rule_type="digest",
        channel="slack",
        channel_target="dm",
    )
    assert r.enabled is True
    assert r.config == {}


def test_trigger_type_agent():
    from agents.models import TriggerType

    assert TriggerType.AGENT == "agent"
    assert TriggerType("agent") == TriggerType.AGENT


def test_run_record_session_id_default():
    from datetime import UTC, datetime

    from agents.models import RunRecord, RunStatus, TriggerType

    run = RunRecord(
        id="test-run",
        project="test",
        task="agent",
        trigger_type=TriggerType.AGENT,
        started_at=datetime.now(UTC),
        status=RunStatus.RUNNING,
        model="sonnet",
    )
    assert run.session_id is None


def test_run_record_session_id_set():
    from datetime import UTC, datetime

    from agents.models import RunRecord, RunStatus, TriggerType

    run = RunRecord(
        id="test-run",
        project="test",
        task="agent",
        trigger_type=TriggerType.AGENT,
        started_at=datetime.now(UTC),
        status=RunStatus.RUNNING,
        model="sonnet",
        session_id="sess-123",
    )
    assert run.session_id == "sess-123"
