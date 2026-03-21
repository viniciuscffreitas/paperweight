from agents.models import TaskStatus
from agents.task_store import TaskStore


def test_linear_source_dedup(tmp_path):
    store = TaskStore(tmp_path / "test.db")
    store.create(project="pw", title="Issue 1", description="D", source="linear", source_id="abc")
    assert store.exists_by_source("linear", "abc") is True
    # Creating another with same source_id should be caught by exists_by_source
    assert store.exists_by_source("linear", "abc") is True


def test_schedule_source_creates_pending(tmp_path):
    store = TaskStore(tmp_path / "test.db")
    item = store.create(
        project="pw", title="pw/dep-update",
        description="Update deps", source="schedule", template="dep-update",
    )
    assert item.status == TaskStatus.PENDING
    assert item.template == "dep-update"
    assert item.source == "schedule"
