"""Tests for retry policy and exponential backoff."""

from agents.retry import RetryPolicy, should_retry_error


def test_backoff_delay_exponential():
    policy = RetryPolicy(max_retries=3, base_delay_seconds=10, max_delay_seconds=300)
    assert policy.delay_for_attempt(1) == 10
    assert policy.delay_for_attempt(2) == 20
    assert policy.delay_for_attempt(3) == 40


def test_backoff_capped_at_max():
    policy = RetryPolicy(max_retries=5, base_delay_seconds=60, max_delay_seconds=120)
    assert policy.delay_for_attempt(5) == 120


def test_should_retry_true_for_retryable_errors():
    assert should_retry_error("Timed out after 30 minutes") is True
    assert should_retry_error("Command failed: git worktree add") is True
    assert should_retry_error("rate_limit_error") is True


def test_should_retry_false_for_permanent_errors():
    assert should_retry_error("Budget exceeded") is False
    assert should_retry_error("Project not found") is False
    assert should_retry_error("") is False


def test_can_retry_within_limit():
    policy = RetryPolicy(max_retries=3)
    assert policy.can_retry(attempt=1) is True
    assert policy.can_retry(attempt=3) is True
    assert policy.can_retry(attempt=4) is False


def test_task_store_retry_columns(tmp_path):
    from agents.task_store import TaskStore

    store = TaskStore(tmp_path / "test.db")
    item = store.create(project="test", title="retryable", description="", source="manual")
    store.mark_for_retry(item.id, retry_count=1, next_retry_at="2026-01-01T00:00:00")
    retryable = store.list_retryable("2026-01-02T00:00:00")
    assert len(retryable) == 1
    assert retryable[0].id == item.id


def test_task_store_retry_not_ready_yet(tmp_path):
    from agents.task_store import TaskStore

    store = TaskStore(tmp_path / "test.db")
    item = store.create(project="test", title="retryable", description="", source="manual")
    store.mark_for_retry(item.id, retry_count=1, next_retry_at="2099-01-01T00:00:00")
    retryable = store.list_retryable("2026-01-01T00:00:00")
    assert len(retryable) == 0


def test_try_claim_any_works_for_retrying(tmp_path):
    from agents.task_store import TaskStore

    store = TaskStore(tmp_path / "test.db")
    item = store.create(project="test", title="retryable", description="", source="manual")
    store.mark_for_retry(item.id, retry_count=1, next_retry_at="2026-01-01T00:00:00")
    assert store.try_claim_any(item.id) is True
    # After claiming, should be RUNNING
    updated = store.get(item.id)
    assert updated.status == "running"


def test_retry_exhausted_marks_failed(tmp_path):
    """When retries are exhausted, should_retry + can_retry returns False."""
    from agents.retry import RetryPolicy, should_retry_error

    policy = RetryPolicy(max_retries=2)
    assert should_retry_error("Timed out") is True
    assert policy.can_retry(3) is False  # attempt 3 > max_retries 2
