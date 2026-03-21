"""Tests for task lifecycle bugs — behavior contract.

Bug 1: READY tasks never processed
Bug 2: Rerun doesn't reset retry_count
Bug 3: Misclassified retryable errors (command not found, permission denied)
"""

import pytest
from datetime import UTC, datetime

from agents.models import TaskStatus, WorkItem
from agents.retry import RetryPolicy, should_retry_error
from agents.task_store import TaskStore
from agents.task_processor import TaskProcessor


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "test.db")


@pytest.fixture
def client(store):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agents.task_routes import register_task_routes

    app = FastAPI()
    register_task_routes(app, store)
    return TestClient(app)


# ── Bug 1: READY tasks never processed ───────────────────────────


class TestReadyTasksProcessed:
    """READY tasks must be polled and claimed by TaskProcessor."""

    def test_ready_tasks_appear_in_actionable_list(self, store):
        """list_actionable() should return both PENDING and READY tasks."""
        store.create(project="pw", title="Pending", description="D", source="manual")
        store.create(
            project="pw", title="Ready", description="D",
            source="manual", status=TaskStatus.READY,
        )
        # list_actionable should return both
        actionable = store.list_actionable(limit=10)
        assert len(actionable) == 2
        statuses = {t.status for t in actionable}
        assert TaskStatus.PENDING in statuses
        assert TaskStatus.READY in statuses

    def test_ready_task_is_claimable(self, store):
        """try_claim() should work for READY tasks, not just PENDING."""
        t = store.create(
            project="pw", title="Ready task", description="D",
            source="manual", status=TaskStatus.READY,
        )
        assert store.try_claim(t.id) is True
        assert store.get(t.id).status == TaskStatus.RUNNING

    def test_draft_tasks_excluded_from_actionable(self, store):
        """DRAFT tasks must NOT appear in actionable list."""
        store.create(
            project="pw", title="Draft", description="D",
            source="manual", status=TaskStatus.DRAFT,
        )
        actionable = store.list_actionable(limit=10)
        assert len(actionable) == 0

    def test_done_tasks_excluded_from_actionable(self, store):
        """DONE tasks must NOT appear in actionable list."""
        t = store.create(project="pw", title="Done", description="D", source="manual")
        store.update_status(t.id, TaskStatus.DONE)
        actionable = store.list_actionable(limit=10)
        assert len(actionable) == 0

    def test_ready_task_with_spec_includes_spec_in_prompt(self, tmp_path):
        """build_prompt() should inject spec file content for READY tasks."""
        spec_dir = tmp_path / "docs" / "superpowers" / "specs"
        spec_dir.mkdir(parents=True)
        spec_file = spec_dir / "2026-03-21-feature-design.md"
        spec_file.write_text("## Spec\n\n- Build the widget\n- Add tests\n")

        item = WorkItem(
            id="abc",
            project="pw",
            title="Build widget",
            description="Original description",
            source="manual",
            status=TaskStatus.READY,
            spec_path=str(spec_file),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        prompt = TaskProcessor.build_prompt(item, context_entries=[])
        assert "Build the widget" in prompt
        assert "Add tests" in prompt
        assert "Implement the spec" in prompt or "spec" in prompt.lower()

    def test_pending_tasks_still_listed_in_actionable(self, store):
        """Regression: PENDING tasks must still work in the new query."""
        store.create(project="pw", title="P1", description="D", source="manual")
        store.create(project="pw", title="P2", description="D", source="manual")
        actionable = store.list_actionable(limit=10)
        assert len(actionable) == 2
        assert all(t.status == TaskStatus.PENDING for t in actionable)


# ── Bug 2: Rerun doesn't reset retry state ───────────────────────


class TestRerunResetsRetryState:
    """POST /api/work-items/{id}/rerun must reset retry_count, next_retry_at, session_id."""

    def test_rerun_resets_retry_count(self, store):
        """After rerun, retry_count must be 0."""
        t = store.create(project="pw", title="T", description="D", source="manual")
        store.mark_for_retry(t.id, retry_count=3, next_retry_at="2026-01-01T00:00:00")
        store.update_status(t.id, TaskStatus.FAILED)
        store.reset_for_rerun(t.id)
        got = store.get(t.id)
        assert got.status == TaskStatus.PENDING
        assert got.retry_count == 0
        assert got.next_retry_at is None

    def test_rerun_resets_session_id(self, store):
        """After rerun, session_id must be NULL for a clean start."""
        t = store.create(project="pw", title="T", description="D", source="manual")
        store.update_session(t.id, "old-session-123")
        store.update_status(t.id, TaskStatus.FAILED)
        store.reset_for_rerun(t.id)
        got = store.get(t.id)
        assert got.session_id is None

    def test_rerun_api_resets_retry_state(self, client, store):
        """POST /rerun via API must reset retry_count and session_id."""
        resp = client.post(
            "/api/work-items",
            json={"project": "pw", "title": "T", "description": "D"},
        )
        item_id = resp.json()["id"]
        # Simulate a task that failed after retries
        store.mark_for_retry(item_id, retry_count=3, next_retry_at="2026-01-01T00:00:00")
        store.update_status(item_id, TaskStatus.FAILED)
        store.update_session(item_id, "stale-session")

        rerun_resp = client.post(f"/api/work-items/{item_id}/rerun")
        assert rerun_resp.status_code == 200
        data = rerun_resp.json()
        assert data["status"] == "pending"
        assert data["retry_count"] == 0
        assert data["next_retry_at"] is None
        assert data["session_id"] is None

    def test_rerun_gives_full_retries(self, store):
        """A re-run task must get 3 fresh retry attempts."""
        t = store.create(project="pw", title="T", description="D", source="manual")
        store.mark_for_retry(t.id, retry_count=3, next_retry_at="2026-01-01T00:00:00")
        store.update_status(t.id, TaskStatus.FAILED)
        store.reset_for_rerun(t.id)

        got = store.get(t.id)
        policy = RetryPolicy()
        # First failure after rerun: retry_count goes 0+1=1, should be retryable
        assert policy.can_retry(got.retry_count + 1) is True
        # Even up to 3 attempts
        assert policy.can_retry(3) is True


# ── Bug 3: Misclassified retryable errors ─────────────────────────


class TestErrorClassification:
    """'command not found' and 'permission denied' must be permanent errors."""

    def test_command_not_found_is_permanent(self):
        assert should_retry_error("claude: command not found") is False
        assert should_retry_error("bash: claude: command not found") is False

    def test_permission_denied_is_permanent(self):
        assert should_retry_error("/usr/bin/claude: Permission denied") is False
        assert should_retry_error("permission denied while accessing repo") is False

    # ── MUST NOT CHANGE: transient errors still retryable ──

    def test_timeout_still_retryable(self):
        assert should_retry_error("Timed out after 30 minutes") is True

    def test_connection_error_still_retryable(self):
        assert should_retry_error("Connection refused") is True
        assert should_retry_error("connection reset by peer") is True

    def test_rate_limit_still_retryable(self):
        assert should_retry_error("rate_limit_error") is True

    def test_server_errors_still_retryable(self):
        assert should_retry_error("HTTP 503 Service Unavailable") is True
        assert should_retry_error("502 Bad Gateway") is True

    def test_worktree_add_still_retryable(self):
        assert should_retry_error("Command failed: git worktree add") is True

    def test_budget_exceeded_still_permanent(self):
        assert should_retry_error("Budget exceeded") is False

    def test_empty_error_still_not_retried(self):
        assert should_retry_error("") is False


# ── MUST NOT CHANGE: core lifecycle preserved ─────────────────────


class TestCoreLifecyclePreserved:
    """Ensure existing behaviors aren't broken by the fixes."""

    def test_pending_tasks_still_polled(self, store):
        t = store.create(project="pw", title="T", description="D", source="manual")
        pending = store.list_pending()
        assert len(pending) == 1
        assert pending[0].id == t.id

    def test_atomic_claim_prevents_double_exec(self, store):
        t = store.create(project="pw", title="T", description="D", source="manual")
        assert store.try_claim(t.id) is True
        assert store.try_claim(t.id) is False

    def test_retry_count_increments_on_failure(self, store):
        t = store.create(project="pw", title="T", description="D", source="manual")
        store.mark_for_retry(t.id, retry_count=1, next_retry_at="2026-01-01T00:00:00")
        got = store.get(t.id)
        assert got.retry_count == 1

    def test_exponential_backoff_preserved(self):
        policy = RetryPolicy()
        assert policy.delay_for_attempt(1) == 30
        assert policy.delay_for_attempt(2) == 60
        assert policy.delay_for_attempt(3) == 120

    def test_max_retries_then_failed(self):
        policy = RetryPolicy(max_retries=3)
        assert policy.can_retry(3) is True
        assert policy.can_retry(4) is False

    def test_retrying_tasks_still_polled_with_delay(self, store):
        t = store.create(project="pw", title="T", description="D", source="manual")
        store.mark_for_retry(t.id, retry_count=1, next_retry_at="2026-01-01T00:00:00")
        retryable = store.list_retryable("2026-01-02T00:00:00")
        assert len(retryable) == 1

    def test_crash_recovery_resets_running_to_pending(self, store):
        t = store.create(project="pw", title="T", description="D", source="manual")
        store.update_status(t.id, TaskStatus.RUNNING)
        count = store.reset_running_to_pending()
        assert count == 1
        assert store.get(t.id).status == TaskStatus.PENDING
