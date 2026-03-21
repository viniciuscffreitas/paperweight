from datetime import UTC, datetime, timedelta

import pytest

from agents.history import HistoryDB
from agents.metrics import collect_metrics
from agents.models import RunRecord, RunStatus, TriggerType


def _make_run(history, project, status, cost, days_ago=0):
    started = datetime.now(UTC) - timedelta(days=days_ago)
    run = RunRecord(
        id=f"run-{project}-{days_ago}-{status}-{cost}",
        project=project,
        task="test-task",
        trigger_type=TriggerType.MANUAL,
        started_at=started,
        finished_at=started + timedelta(minutes=5),
        status=RunStatus(status),
        model="sonnet",
        cost_usd=cost,
        num_turns=10,
    )
    history.insert_run(run)
    history.update_run(
        run.id,
        status=run.status,
        finished_at=run.finished_at,
        cost_usd=run.cost_usd,
        num_turns=run.num_turns,
    )


def test_collect_metrics_cost_by_day(tmp_path):
    db = HistoryDB(tmp_path / "test.db")
    _make_run(db, "proj1", "success", 1.50)
    _make_run(db, "proj1", "success", 2.00)
    _make_run(db, "proj1", "failure", 0.50, days_ago=1)
    metrics = collect_metrics(db, days=7)
    assert metrics["total_cost_7d"] == pytest.approx(4.00)
    assert metrics["total_runs_7d"] == 3
    assert len(metrics["cost_by_day"]) >= 1


def test_collect_metrics_success_rate(tmp_path):
    db = HistoryDB(tmp_path / "test.db")
    _make_run(db, "proj1", "success", 1.0)
    _make_run(db, "proj1", "success", 1.5)
    _make_run(db, "proj1", "failure", 0.5)
    metrics = collect_metrics(db, days=7)
    assert metrics["success_rate_7d"] == pytest.approx(66.67, abs=0.1)


def test_collect_metrics_empty_db(tmp_path):
    db = HistoryDB(tmp_path / "test.db")
    metrics = collect_metrics(db, days=7)
    assert metrics["total_runs_7d"] == 0
    assert metrics["success_rate_7d"] == 0.0
    assert metrics["total_cost_7d"] == 0.0
