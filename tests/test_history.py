from datetime import UTC, datetime

import pytest


@pytest.fixture
def history_db(tmp_path):
    from agents.history import HistoryDB

    db_path = tmp_path / "test.db"
    return HistoryDB(db_path)


def test_create_tables(history_db):
    import sqlite3

    conn = sqlite3.connect(history_db.db_path)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()
    assert "runs" in tables


def test_insert_and_get_run(history_db):
    from agents.models import RunRecord, RunStatus, TriggerType

    run = RunRecord(
        id="run-001",
        project="sekit",
        task="dep-update",
        trigger_type=TriggerType.SCHEDULE,
        started_at=datetime(2026, 3, 14, 3, 0, 0, tzinfo=UTC),
        status=RunStatus.RUNNING,
        model="sonnet",
    )
    history_db.insert_run(run)
    fetched = history_db.get_run("run-001")
    assert fetched is not None
    assert fetched.id == "run-001"
    assert fetched.project == "sekit"
    assert fetched.status == RunStatus.RUNNING


def test_update_run_completion(history_db):
    from agents.models import RunRecord, RunStatus, TriggerType

    run = RunRecord(
        id="run-002",
        project="sekit",
        task="ci-fix",
        trigger_type=TriggerType.GITHUB,
        started_at=datetime(2026, 3, 14, 3, 0, 0, tzinfo=UTC),
        status=RunStatus.RUNNING,
        model="sonnet",
    )
    history_db.insert_run(run)
    history_db.update_run(
        run_id="run-002",
        status=RunStatus.SUCCESS,
        finished_at=datetime(2026, 3, 14, 3, 5, 0, tzinfo=UTC),
        cost_usd=0.45,
        num_turns=8,
        pr_url="https://github.com/org/repo/pull/1",
    )
    fetched = history_db.get_run("run-002")
    assert fetched is not None
    assert fetched.status == RunStatus.SUCCESS
    assert fetched.cost_usd == 0.45
    assert fetched.pr_url == "https://github.com/org/repo/pull/1"


def test_list_runs_today(history_db):
    from agents.models import RunRecord, RunStatus, TriggerType

    now = datetime.now(UTC)
    for i in range(3):
        history_db.insert_run(
            RunRecord(
                id=f"run-{i}",
                project="sekit",
                task="test",
                trigger_type=TriggerType.MANUAL,
                started_at=now,
                status=RunStatus.SUCCESS,
                model="sonnet",
                cost_usd=1.0 + i,
            )
        )
    runs = history_db.list_runs_today()
    assert len(runs) == 3


def test_total_cost_today(history_db):
    from agents.models import RunRecord, RunStatus, TriggerType

    now = datetime.now(UTC)
    history_db.insert_run(
        RunRecord(
            id="run-a",
            project="p",
            task="t",
            trigger_type=TriggerType.MANUAL,
            started_at=now,
            status=RunStatus.SUCCESS,
            model="s",
            cost_usd=2.50,
        )
    )
    history_db.insert_run(
        RunRecord(
            id="run-b",
            project="p",
            task="t",
            trigger_type=TriggerType.MANUAL,
            started_at=now,
            status=RunStatus.SUCCESS,
            model="s",
            cost_usd=1.25,
        )
    )
    history_db.insert_run(
        RunRecord(
            id="run-c",
            project="p",
            task="t",
            trigger_type=TriggerType.MANUAL,
            started_at=now,
            status=RunStatus.RUNNING,
            model="s",
        )
    )
    assert history_db.total_cost_today() == pytest.approx(3.75)


def test_get_nonexistent_run(history_db):
    assert history_db.get_run("nonexistent") is None


def test_mark_running_as_cancelled(history_db):
    from agents.models import RunRecord, RunStatus, TriggerType

    now = datetime.now(UTC)
    history_db.insert_run(
        RunRecord(
            id="run-x",
            project="p",
            task="t",
            trigger_type=TriggerType.MANUAL,
            started_at=now,
            status=RunStatus.RUNNING,
            model="s",
        )
    )
    history_db.insert_run(
        RunRecord(
            id="run-y",
            project="p",
            task="t",
            trigger_type=TriggerType.MANUAL,
            started_at=now,
            status=RunStatus.SUCCESS,
            model="s",
        )
    )
    history_db.mark_running_as_cancelled()
    assert history_db.get_run("run-x").status == RunStatus.CANCELLED
    assert history_db.get_run("run-y").status == RunStatus.SUCCESS
