from agents.history import HistoryDB
from agents.session_manager import SessionManager
from agents.models import RunRecord, RunStatus, TriggerType
from datetime import datetime, UTC


def test_runs_table_has_task_id_column(tmp_path):
    db = HistoryDB(tmp_path / "test.db")
    run = RunRecord(
        id="r1", project="pw", task="test", trigger_type=TriggerType.MANUAL,
        started_at=datetime.now(UTC), status=RunStatus.RUNNING, model="sonnet",
    )
    db.insert_run(run)
    with db._conn() as conn:
        conn.execute("UPDATE runs SET task_id = ? WHERE id = ?", ("task-abc", "r1"))
        row = conn.execute("SELECT task_id FROM runs WHERE id = ?", ("r1",)).fetchone()
    assert row["task_id"] == "task-abc"


def test_sessions_table_has_task_id_column(tmp_path):
    sm = SessionManager(tmp_path / "test.db")
    session = sm.create_session("pw")
    with sm._conn() as conn:
        conn.execute("UPDATE agent_sessions SET task_id = ? WHERE id = ?", ("task-abc", session.id))
        row = conn.execute("SELECT task_id FROM agent_sessions WHERE id = ?", (session.id,)).fetchone()
    assert row["task_id"] == "task-abc"
