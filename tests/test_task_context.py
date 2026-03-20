import time
from agents.task_store import TaskStore
from agents.models import TaskStatus


def test_add_and_get_context(tmp_path):
    store = TaskStore(tmp_path / "test.db")
    task = store.create(project="pw", title="T", description="D", source="manual")
    store.add_context(task.id, "run_error", "pytest failed: 3 errors", source_run_id="run-1")
    store.add_context(task.id, "user_feedback", "Try a different approach")
    entries = store.get_context(task.id)
    assert len(entries) == 2
    # Newest first
    assert entries[0]["type"] == "user_feedback"
    assert entries[1]["type"] == "run_error"
    assert entries[1]["source_run_id"] == "run-1"


def test_context_truncated_at_4kb(tmp_path):
    store = TaskStore(tmp_path / "test.db")
    task = store.create(project="pw", title="T", description="D", source="manual")
    big_content = "x" * 5000
    store.add_context(task.id, "run_error", big_content)
    entries = store.get_context(task.id)
    assert len(entries[0]["content"]) <= 4096


def test_context_pruned_at_50(tmp_path):
    store = TaskStore(tmp_path / "test.db")
    task = store.create(project="pw", title="T", description="D", source="manual")
    for i in range(55):
        store.add_context(task.id, "run_result", f"Entry {i}")
    entries = store.get_context(task.id, limit=100)
    assert len(entries) <= 50


def test_pruning_preserves_errors(tmp_path):
    store = TaskStore(tmp_path / "test.db")
    task = store.create(project="pw", title="T", description="D", source="manual")
    # Add 2 errors first
    store.add_context(task.id, "run_error", "Error 1")
    store.add_context(task.id, "run_error", "Error 2")
    # Add 52 regular entries to trigger pruning
    for i in range(52):
        store.add_context(task.id, "run_result", f"Entry {i}")
    entries = store.get_context(task.id, limit=100)
    error_entries = [e for e in entries if e["type"] == "run_error"]
    # Errors should be preserved
    assert len(error_entries) == 2
