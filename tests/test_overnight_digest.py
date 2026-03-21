from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from agents.history import HistoryDB
from agents.models import RunRecord, RunStatus, TriggerType
from agents.notification_engine import NotificationEngine


def _insert_run(db, status, cost, pr_url=None, error=None, hours_ago=2):
    started = datetime.now(UTC) - timedelta(hours=hours_ago)
    run = RunRecord(
        id=f"run-{status}-{hours_ago}-{cost}",
        project="test",
        task="build",
        trigger_type=TriggerType.SCHEDULE,
        started_at=started,
        finished_at=started + timedelta(minutes=5),
        status=RunStatus(status),
        model="sonnet",
        cost_usd=cost,
        num_turns=10,
        pr_url=pr_url,
        error_message=error,
    )
    db.insert_run(run)
    db.update_run(
        run.id,
        status=run.status,
        finished_at=run.finished_at,
        cost_usd=run.cost_usd,
        pr_url=run.pr_url,
        error_message=run.error_message,
    )


def test_overnight_digest_summarizes_runs(tmp_path):
    db = HistoryDB(tmp_path / "test.db")
    _insert_run(db, "success", 1.50, pr_url="https://github.com/org/repo/pull/1")
    _insert_run(db, "failure", 0.50, error="Timed out")
    mock_store = MagicMock()
    engine = NotificationEngine(store=mock_store)
    digest = engine.build_overnight_digest(db, hours=12)
    assert "2 runs" in digest
    assert "1 succeeded" in digest
    assert "1 failed" in digest
    assert "$2.00" in digest
    assert "pull/1" in digest


def test_overnight_digest_empty_when_no_runs(tmp_path):
    db = HistoryDB(tmp_path / "test.db")
    mock_store = MagicMock()
    engine = NotificationEngine(store=mock_store)
    digest = engine.build_overnight_digest(db, hours=12)
    assert digest == ""
