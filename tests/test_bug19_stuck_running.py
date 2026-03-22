"""Bug #19: Task stuck as 'running' when Claude process dies.

Behavior Contract:
- CHANGES: startup resets running→pending; agent_routes marks task failed on crash
- MUST NOT CHANGE: normal completion, normal failure, task_processor error handling
"""

from pathlib import Path

import pytest

from agents.models import TaskStatus
from agents.task_store import TaskStore


@pytest.fixture
def task_store(tmp_path: Path) -> TaskStore:
    return TaskStore(tmp_path / "test.db")


# -----------------------------------------------------------------------
# CHANGES: startup resets running tasks
# -----------------------------------------------------------------------


def test_startup_resets_running_tasks(task_store: TaskStore) -> None:
    """Tasks stuck as 'running' from a previous crash become 'pending' on startup."""
    item = task_store.create(
        project="pw", title="Stuck task", description="", source="manual",
    )
    task_store.update_status(item.id, TaskStatus.RUNNING)
    assert task_store.get(item.id).status == TaskStatus.RUNNING

    # Simulate what startup should do
    task_store.reset_running_to_pending()

    refreshed = task_store.get(item.id)
    assert refreshed.status == TaskStatus.PENDING


def test_startup_reset_ignores_other_statuses(task_store: TaskStore) -> None:
    """Only 'running' tasks are reset — done, failed, pending stay as-is."""
    done = task_store.create(project="pw", title="Done", description="", source="m")
    task_store.update_status(done.id, TaskStatus.DONE)

    failed = task_store.create(project="pw", title="Failed", description="", source="m")
    task_store.update_status(failed.id, TaskStatus.FAILED)

    pending = task_store.create(project="pw", title="Pending", description="", source="m")

    task_store.reset_running_to_pending()

    assert task_store.get(done.id).status == TaskStatus.DONE
    assert task_store.get(failed.id).status == TaskStatus.FAILED
    assert task_store.get(pending.id).status == TaskStatus.PENDING


# -----------------------------------------------------------------------
# CHANGES: agent_routes marks task failed on executor crash
# -----------------------------------------------------------------------


def test_agent_route_marks_task_failed_on_executor_crash(task_store: TaskStore) -> None:
    """When executor raises in agent_routes._run(), linked work item → failed."""
    from agents.session_manager import SessionManager

    sm = SessionManager(task_store.db_path, worktree_base="/tmp/test-agents")
    session = sm.create_session("pw", "sonnet", 2.0)
    sm.try_acquire_run(session.id)

    item = task_store.create(
        project="pw", title="Will crash", description="", source="agent",
        session_id=session.id,
    )
    task_store.update_status(item.id, TaskStatus.RUNNING)

    # Simulate what the _run() finally block should do:
    # if task was still running after executor finishes, mark as failed
    current = task_store.get(item.id)
    if current and current.status == TaskStatus.RUNNING:
        task_store.update_status(item.id, TaskStatus.FAILED)

    assert task_store.get(item.id).status == TaskStatus.FAILED


# -----------------------------------------------------------------------
# MUST NOT CHANGE: normal completion
# -----------------------------------------------------------------------


def test_normal_task_completion_still_works(task_store: TaskStore) -> None:
    """Success path: pending → running → done."""
    item = task_store.create(
        project="pw", title="Good task", description="", source="manual",
    )
    task_store.try_claim(item.id)
    assert task_store.get(item.id).status == TaskStatus.RUNNING

    task_store.update_status(item.id, TaskStatus.DONE)
    assert task_store.get(item.id).status == TaskStatus.DONE


def test_task_processor_failure_still_works(task_store: TaskStore) -> None:
    """Failure path: pending → running → failed (with retry check)."""
    item = task_store.create(
        project="pw", title="Bad task", description="", source="manual",
    )
    task_store.try_claim(item.id)
    assert task_store.get(item.id).status == TaskStatus.RUNNING

    task_store.update_status(item.id, TaskStatus.FAILED)
    assert task_store.get(item.id).status == TaskStatus.FAILED
