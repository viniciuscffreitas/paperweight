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


def test_run_events_table_exists(history_db):
    import sqlite3

    conn = sqlite3.connect(history_db.db_path)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()
    assert "run_events" in tables


def test_insert_and_list_events(history_db):
    event = {
        "run_id": "run-evt-1",
        "type": "task_started",
        "content": "sekit/dep-update [manual]",
        "tool_name": "",
        "timestamp": 1234567890.0,
    }
    history_db.insert_event("run-evt-1", event)
    events = history_db.list_events("run-evt-1")
    assert len(events) == 1
    assert events[0]["type"] == "task_started"
    assert events[0]["content"] == "sekit/dep-update [manual]"
    assert events[0]["run_id"] == "run-evt-1"


def test_list_events_empty_for_unknown_run(history_db):
    assert history_db.list_events("nonexistent-run") == []


def test_list_events_ordered_by_timestamp(history_db):
    for i, evt_type in enumerate(["task_started", "dry_run", "task_completed"]):
        history_db.insert_event(
            "run-ord",
            {
                "run_id": "run-ord", "type": evt_type, "content": "",
                "tool_name": "", "timestamp": float(i),
            },
        )
    events = history_db.list_events("run-ord")
    assert [e["type"] for e in events] == ["task_started", "dry_run", "task_completed"]


def test_list_events_isolated_per_run(history_db):
    history_db.insert_event(
        "run-A",
        {"run_id": "run-A", "type": "task_started", "content": "A",
         "tool_name": "", "timestamp": 1.0},
    )
    history_db.insert_event(
        "run-B",
        {"run_id": "run-B", "type": "task_started", "content": "B",
         "tool_name": "", "timestamp": 1.0},
    )
    assert len(history_db.list_events("run-A")) == 1
    assert history_db.list_events("run-A")[0]["content"] == "A"


def test_insert_event_cap_at_500(history_db):
    for i in range(510):
        history_db.insert_event(
            "run-cap",
            {
                "run_id": "run-cap", "type": "assistant",
                "content": f"msg-{i}", "tool_name": "", "timestamp": float(i),
            },
        )
    events = history_db.list_events("run-cap")
    assert len(events) == 500


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


def test_find_run_by_issue_id_returns_latest(history_db):
    from datetime import UTC, datetime

    from agents.models import RunRecord, RunStatus, TriggerType
    history_db.insert_run(RunRecord(
        id="proj-issue-resolver-issue-abc-20260316-001",
        project="proj", task="issue-resolver", trigger_type=TriggerType.LINEAR,
        started_at=datetime(2026, 3, 16, 10, 0, 0, tzinfo=UTC),
        status=RunStatus.FAILURE, model="sonnet",
    ))
    history_db.insert_run(RunRecord(
        id="proj-issue-resolver-issue-abc-20260316-002",
        project="proj", task="issue-resolver", trigger_type=TriggerType.LINEAR,
        started_at=datetime(2026, 3, 16, 11, 0, 0, tzinfo=UTC),
        status=RunStatus.SUCCESS, model="sonnet",
    ))
    result = history_db.find_run_by_issue_id("issue-abc")
    assert result is not None
    assert result.status == RunStatus.SUCCESS

def test_find_run_by_issue_id_returns_none_when_not_found(history_db):
    result = history_db.find_run_by_issue_id("nonexistent")
    assert result is None
