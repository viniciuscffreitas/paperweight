import pytest
from agents.task_store import TaskStore
from agents.models import TaskStatus

@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "test.db")

def test_create_and_get(store):
    task = store.create(project="pw", title="Fix bug", description="It's broken", source="manual")
    assert task.id
    assert len(task.id) == 12
    assert task.status == TaskStatus.PENDING
    got = store.get(task.id)
    assert got is not None
    assert got.title == "Fix bug"

def test_list_by_project(store):
    store.create(project="pw", title="T1", description="D1", source="manual")
    store.create(project="pw", title="T2", description="D2", source="manual")
    store.create(project="other", title="T3", description="D3", source="manual")
    assert len(store.list_by_project("pw")) == 2

def test_list_pending(store):
    t1 = store.create(project="pw", title="T1", description="D1", source="manual")
    t2 = store.create(project="pw", title="T2", description="D2", source="manual")
    store.update_status(t1.id, TaskStatus.RUNNING)
    pending = store.list_pending()
    assert len(pending) == 1
    assert pending[0].id == t2.id

def test_atomic_claim(store):
    t = store.create(project="pw", title="T1", description="D", source="manual")
    assert store.try_claim(t.id) is True
    assert store.get(t.id).status == TaskStatus.RUNNING
    assert store.try_claim(t.id) is False  # already claimed

def test_claim_only_pending(store):
    t = store.create(project="pw", title="T1", description="D", source="manual")
    store.update_status(t.id, TaskStatus.DONE)
    assert store.try_claim(t.id) is False

def test_update_status_with_pr(store):
    t = store.create(project="pw", title="T1", description="D", source="manual")
    store.update_status(t.id, TaskStatus.REVIEW, pr_url="https://github.com/pr/1")
    got = store.get(t.id)
    assert got.status == TaskStatus.REVIEW
    assert got.pr_url == "https://github.com/pr/1"

def test_exists_by_source(store):
    store.create(project="pw", title="T1", description="D", source="linear", source_id="abc")
    assert store.exists_by_source("linear", "abc") is True
    assert store.exists_by_source("linear", "xyz") is False
    assert store.exists_by_source("github", "abc") is False

def test_update_session(store):
    t = store.create(project="pw", title="T1", description="D", source="manual")
    store.update_session(t.id, "session-123")
    assert store.get(t.id).session_id == "session-123"
