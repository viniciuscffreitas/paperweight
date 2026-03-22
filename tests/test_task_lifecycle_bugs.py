"""Tests for task lifecycle bugs — behavior contract.

Bug 1: READY tasks never processed
Bug 2: Rerun doesn't reset retry_count
Bug 3: Misclassified retryable errors (command not found, permission denied)
Bug 4: Tasks FAILED despite agent having committed work
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.models import (
    ProjectConfig,
    RunRecord,
    RunStatus,
    TaskStatus,
    TriggerType,
    WorkItem,
)
from agents.retry import RetryPolicy, should_retry_error
from agents.task_processor import TaskProcessor
from agents.task_store import TaskStore

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

    def test_rerun_blocked_for_running_task(self, store):
        """Cannot rerun a task that is currently RUNNING."""
        t = store.create(project="pw", title="T", description="D", source="manual")
        store.update_status(t.id, TaskStatus.RUNNING)
        assert store.reset_for_rerun(t.id) is False
        assert store.get(t.id).status == TaskStatus.RUNNING

    def test_rerun_blocked_for_pending_task(self, store):
        """Cannot rerun a task that is already PENDING."""
        t = store.create(project="pw", title="T", description="D", source="manual")
        assert store.reset_for_rerun(t.id) is False
        assert store.get(t.id).status == TaskStatus.PENDING

    def test_rerun_api_returns_409_for_running(self, client, store):
        """POST /rerun on RUNNING task returns 409."""
        resp = client.post(
            "/api/work-items",
            json={"project": "pw", "title": "T", "description": "D"},
        )
        item_id = resp.json()["id"]
        store.update_status(item_id, TaskStatus.RUNNING)
        rerun_resp = client.post(f"/api/work-items/{item_id}/rerun")
        assert rerun_resp.status_code == 409


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


# ── Shared helpers for Bug 4 ──────────────────────────────────────


class _AsyncNullCtx:
    """Async context manager that does nothing (mock semaphore)."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass


def _make_run(status, error_message=None, claude_session_id=None):
    """Create a RunRecord with minimal fields for testing."""
    return RunRecord(
        id="run-test",
        project="pw",
        task="test",
        trigger_type=TriggerType.AGENT,
        started_at=datetime.now(UTC),
        status=status,
        model="claude-sonnet-4-6",
        error_message=error_message,
        claude_session_id=claude_session_id,
    )


@pytest.fixture
def processor_mocks(tmp_path, store):
    """Minimal mocks for TaskProcessor.process_one()."""
    state = MagicMock()
    state.task_store = store
    state.get_semaphore = lambda *a: _AsyncNullCtx()
    state.get_repo_semaphore = lambda *a: _AsyncNullCtx()
    state.history.list_events.return_value = []
    state.notifier = AsyncMock()
    state.notifier.send_text = AsyncMock()
    state.budget.can_afford.return_value = True

    # Session mock with existing worktree directory
    worktree_dir = tmp_path / "worktree"
    worktree_dir.mkdir()

    session = MagicMock()
    session.id = "sess-test"
    session.worktree_path = str(worktree_dir)
    session.model = "claude-sonnet-4-6"
    session.max_cost_usd = 5.0
    session.claude_session_id = None
    session.status = "active"

    state.session_manager.create_session.return_value = session
    state.session_manager.get_session.return_value = session
    state.session_manager.try_acquire_run.return_value = True

    # Executor
    state.executor = AsyncMock()
    state.executor._run_cmd = AsyncMock(return_value="")
    state.executor._create_pr = AsyncMock(return_value=None)

    # Project
    project = ProjectConfig(
        name="pw",
        repo=str(tmp_path / "repo"),
        tasks={},
    )
    state.projects = {"pw": project}

    # Config
    config = MagicMock()
    config.execution.max_concurrent = 2
    config.execution.default_model = "claude-sonnet-4-6"
    config.execution.default_max_cost_usd = 5.0

    return state, config


# ── Bug 4: Tasks FAILED despite committed work ────────────────────


class TestFailedRunWithCommits:
    """Bug 4: TaskProcessor marks FAILED despite agent having committed work."""

    @pytest.mark.asyncio
    async def test_failed_run_with_commits_marks_review(self, store, processor_mocks):
        """CHANGES: When run fails but worktree has commits → REVIEW."""
        state, config = processor_mocks
        item = store.create(project="pw", title="Chat UX", description="D", source="agent")

        state.executor.run_adhoc = AsyncMock(
            return_value=_make_run(RunStatus.FAILURE, error_message="Budget exceeded")
        )
        # Worktree has commits
        state.executor._run_cmd = AsyncMock(
            return_value="abc123 feat: Chat UX changes"
        )

        processor = TaskProcessor(store, state, config)
        await processor.process_one(item)

        result = store.get(item.id)
        assert result.status == TaskStatus.REVIEW

    @pytest.mark.asyncio
    async def test_failed_run_no_commits_marks_failed(self, store, processor_mocks):
        """MUST NOT CHANGE: Run fails, no commits → FAILED."""
        state, config = processor_mocks
        item = store.create(project="pw", title="Broken", description="D", source="agent")

        state.executor.run_adhoc = AsyncMock(
            return_value=_make_run(RunStatus.FAILURE, error_message="Budget exceeded")
        )
        state.executor._run_cmd = AsyncMock(return_value="")

        processor = TaskProcessor(store, state, config)
        await processor.process_one(item)

        result = store.get(item.id)
        assert result.status == TaskStatus.FAILED

    @pytest.mark.asyncio
    async def test_success_with_pr_marks_review(self, store, processor_mocks):
        """MUST NOT CHANGE: Success + PR → REVIEW."""
        state, config = processor_mocks
        item = store.create(project="pw", title="Feature", description="D", source="agent")

        state.executor.run_adhoc = AsyncMock(
            return_value=_make_run(RunStatus.SUCCESS)
        )
        state.executor._create_pr = AsyncMock(
            return_value="https://github.com/test/pr/1"
        )

        processor = TaskProcessor(store, state, config)
        await processor.process_one(item)

        result = store.get(item.id)
        assert result.status == TaskStatus.REVIEW
        assert result.pr_url == "https://github.com/test/pr/1"

    @pytest.mark.asyncio
    async def test_success_no_pr_marks_done(self, store, processor_mocks):
        """MUST NOT CHANGE: Success + no PR → DONE."""
        state, config = processor_mocks
        item = store.create(project="pw", title="Simple", description="D", source="agent")

        state.executor.run_adhoc = AsyncMock(
            return_value=_make_run(RunStatus.SUCCESS)
        )
        state.executor._create_pr = AsyncMock(return_value=None)

        processor = TaskProcessor(store, state, config)
        await processor.process_one(item)

        result = store.get(item.id)
        assert result.status == TaskStatus.DONE

    @pytest.mark.asyncio
    async def test_retry_still_works_on_retryable_no_commits(self, store, processor_mocks):
        """MUST NOT CHANGE: Retryable error with no commits → RETRYING."""
        state, config = processor_mocks
        item = store.create(project="pw", title="Retry me", description="D", source="agent")

        state.executor.run_adhoc = AsyncMock(
            return_value=_make_run(
                RunStatus.FAILURE, error_message="Connection refused"
            )
        )
        state.executor._run_cmd = AsyncMock(return_value="")

        processor = TaskProcessor(store, state, config)
        await processor.process_one(item)

        result = store.get(item.id)
        assert result.status == TaskStatus.RETRYING


# ── Bug 4b: Chat errors auto-failing tasks ─────────────────────────


class TestAgentRoutesChatError:
    """Bug 4b: Interactive chat errors should NOT auto-fail linked tasks."""

    def test_chat_error_does_not_fail_task(self, store, tmp_path):
        """CHANGES: Chat run error → task status unchanged."""
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        from agents.agent_routes import register_agent_routes

        task = store.create(
            project="pw", title="My Task", description="D", source="agent",
        )
        store.update_status(task.id, TaskStatus.RUNNING)
        store.update_session(task.id, "sess-abc")

        # Worktree directory must exist so route handler keeps the session
        wt_dir = tmp_path / "wt"
        wt_dir.mkdir()

        state = MagicMock()
        state.task_store = store
        state.session_manager = MagicMock()

        session = MagicMock()
        session.id = "sess-abc"
        session.status = "active"
        session.worktree_path = str(wt_dir)
        session.model = "claude-sonnet-4-6"
        session.max_cost_usd = 5.0
        session.claude_session_id = "cs-123"
        session.title = "My Task"

        state.session_manager.get_session.return_value = session
        state.session_manager.try_acquire_run.return_value = True

        state.executor = AsyncMock()
        state.executor.run_adhoc = AsyncMock(
            return_value=_make_run(
                RunStatus.FAILURE,
                error_message="some error",
                claude_session_id="cs-123",
            )
        )
        state.get_semaphore = lambda *a: _AsyncNullCtx()
        state.get_repo_semaphore = lambda *a: _AsyncNullCtx()

        project = ProjectConfig(
            name="pw", repo=str(tmp_path / "repo"), tasks={},
        )
        state.projects = {"pw": project}

        config = MagicMock()
        config.execution.max_concurrent = 2

        app = FastAPI()
        register_agent_routes(app, state, config)

        client = TestClient(app)
        resp = client.post(
            "/api/projects/pw/agent",
            json={"prompt": "hello", "session_id": "sess-abc"},
        )
        assert resp.status_code == 202

        got = store.get(task.id)
        assert got.status == TaskStatus.RUNNING  # NOT FAILED

    def test_chat_success_does_not_mark_done(self, store, tmp_path):
        """MUST NOT CHANGE: Chat success → task status unchanged."""
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        from agents.agent_routes import register_agent_routes

        task = store.create(
            project="pw", title="My Task", description="D", source="agent",
        )
        store.update_status(task.id, TaskStatus.RUNNING)
        store.update_session(task.id, "sess-def")

        # Worktree directory must exist so route handler keeps the session
        wt_dir = tmp_path / "wt"
        wt_dir.mkdir()

        state = MagicMock()
        state.task_store = store
        state.session_manager = MagicMock()

        session = MagicMock()
        session.id = "sess-def"
        session.status = "active"
        session.worktree_path = str(wt_dir)
        session.model = "claude-sonnet-4-6"
        session.max_cost_usd = 5.0
        session.claude_session_id = "cs-456"
        session.title = "My Task"

        state.session_manager.get_session.return_value = session
        state.session_manager.try_acquire_run.return_value = True

        state.executor = AsyncMock()
        state.executor.run_adhoc = AsyncMock(
            return_value=_make_run(
                RunStatus.SUCCESS,
                claude_session_id="cs-456",
            )
        )
        state.get_semaphore = lambda *a: _AsyncNullCtx()
        state.get_repo_semaphore = lambda *a: _AsyncNullCtx()

        project = ProjectConfig(
            name="pw", repo=str(tmp_path / "repo"), tasks={},
        )
        state.projects = {"pw": project}

        config = MagicMock()
        config.execution.max_concurrent = 2

        app = FastAPI()
        register_agent_routes(app, state, config)

        client = TestClient(app)
        resp = client.post(
            "/api/projects/pw/agent",
            json={"prompt": "do things", "session_id": "sess-def"},
        )
        assert resp.status_code == 202

        got = store.get(task.id)
        assert got.status == TaskStatus.RUNNING  # NOT DONE
