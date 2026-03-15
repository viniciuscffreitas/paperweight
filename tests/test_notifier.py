from datetime import UTC, datetime


def test_format_success_message():
    from agents.models import RunRecord, RunStatus, TriggerType
    from agents.notifier import Notifier

    notifier = Notifier(webhook_url="https://hooks.slack.com/test")
    run = RunRecord(
        id="run-001",
        project="sekit",
        task="dep-update",
        trigger_type=TriggerType.SCHEDULE,
        started_at=datetime(2026, 3, 14, 3, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 3, 14, 3, 2, 34, tzinfo=UTC),
        status=RunStatus.SUCCESS,
        model="haiku",
        cost_usd=0.18,
        num_turns=12,
        pr_url="https://github.com/org/repo/pull/42",
    )
    msg = notifier.format_message(run)
    assert "[sekit] dep-update" in msg
    assert "$0.18" in msg
    assert "pull/42" in msg


def test_format_failure_message():
    from agents.models import RunRecord, RunStatus, TriggerType
    from agents.notifier import Notifier

    notifier = Notifier(webhook_url="https://hooks.slack.com/test")
    run = RunRecord(
        id="run-002",
        project="fintech",
        task="ci-fix",
        trigger_type=TriggerType.GITHUB,
        started_at=datetime(2026, 3, 14, 3, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 3, 14, 3, 8, 12, tzinfo=UTC),
        status=RunStatus.FAILURE,
        model="sonnet",
        cost_usd=1.23,
        num_turns=28,
        error_message="Tests failed after fix attempt",
    )
    msg = notifier.format_message(run)
    assert "[fintech] ci-fix" in msg
    assert "Tests failed" in msg


def test_format_budget_warning():
    from agents.models import BudgetStatus
    from agents.notifier import Notifier

    notifier = Notifier(webhook_url="https://hooks.slack.com/test")
    status = BudgetStatus(daily_limit_usd=10.0, spent_today_usd=7.23)
    msg = notifier.format_budget_warning(status)
    assert "$7.23" in msg
    assert "$10.00" in msg


def test_noop_notifier():
    from agents.notifier import Notifier

    notifier = Notifier(webhook_url="")
    msg = notifier.format_message(None)  # type: ignore
    assert msg == ""
