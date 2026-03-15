from datetime import UTC, datetime

import pytest


@pytest.fixture
def budget_deps(tmp_path):
    from agents.budget import BudgetManager
    from agents.config import BudgetConfig
    from agents.history import HistoryDB

    db = HistoryDB(tmp_path / "test.db")
    config = BudgetConfig(daily_limit_usd=10.0, warning_threshold_usd=7.0, pause_on_limit=True)
    return BudgetManager(config=config, history=db), db


def test_budget_status_empty(budget_deps):
    manager, _ = budget_deps
    status = manager.get_status()
    assert status.spent_today_usd == 0.0
    assert status.remaining_usd == 10.0
    assert status.is_exceeded is False


def test_budget_status_after_spending(budget_deps):
    from agents.models import RunRecord, RunStatus, TriggerType

    manager, db = budget_deps
    now = datetime.now(UTC)
    db.insert_run(
        RunRecord(
            id="r1",
            project="p",
            task="t",
            trigger_type=TriggerType.MANUAL,
            started_at=now,
            status=RunStatus.SUCCESS,
            model="s",
            cost_usd=4.50,
        )
    )
    status = manager.get_status()
    assert status.spent_today_usd == pytest.approx(4.50)
    assert status.remaining_usd == pytest.approx(5.50)


def test_can_afford_yes(budget_deps):
    manager, _ = budget_deps
    assert manager.can_afford(max_cost_usd=5.0) is True


def test_can_afford_no(budget_deps):
    from agents.models import RunRecord, RunStatus, TriggerType

    manager, db = budget_deps
    now = datetime.now(UTC)
    db.insert_run(
        RunRecord(
            id="r1",
            project="p",
            task="t",
            trigger_type=TriggerType.MANUAL,
            started_at=now,
            status=RunStatus.SUCCESS,
            model="s",
            cost_usd=8.00,
        )
    )
    assert manager.can_afford(max_cost_usd=5.0) is False


def test_can_afford_when_paused(budget_deps):
    from agents.models import RunRecord, RunStatus, TriggerType

    manager, db = budget_deps
    now = datetime.now(UTC)
    db.insert_run(
        RunRecord(
            id="r1",
            project="p",
            task="t",
            trigger_type=TriggerType.MANUAL,
            started_at=now,
            status=RunStatus.SUCCESS,
            model="s",
            cost_usd=10.50,
        )
    )
    assert manager.can_afford(max_cost_usd=0.01) is False
