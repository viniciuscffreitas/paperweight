from agents.models import (
    TaskConfig,
    TaskRecord,
    TaskStatus,
    TaskTemplate,
    TaskTemplateRecord,
    WorkItem,
)


def test_task_template_is_alias_for_task_config():
    assert TaskTemplate is TaskConfig


def test_task_template_record_is_alias():
    assert TaskTemplateRecord is TaskRecord


def test_task_status_values():
    assert TaskStatus.DRAFT == "draft"
    assert TaskStatus.PENDING == "pending"
    assert TaskStatus.READY == "ready"
    assert TaskStatus.RUNNING == "running"
    assert TaskStatus.REVIEW == "review"
    assert TaskStatus.DONE == "done"
    assert TaskStatus.FAILED == "failed"


def test_task_status_ready_roundtrip():
    assert TaskStatus("ready") == TaskStatus.READY


def test_task_status_ordering():
    # draft → ready → running is the brainstorming lifecycle
    statuses = [s.value for s in TaskStatus]
    assert statuses.index("draft") < statuses.index("ready")
    assert statuses.index("ready") < statuses.index("running")


def test_work_item_creation():
    item = WorkItem(
        id="abc123def456",
        project="paperweight",
        title="Fix the tests",
        description="Tests are flaky",
        source="manual",
    )
    assert item.status == TaskStatus.PENDING
    assert item.source_id == ""
    assert item.session_id is None
    assert item.pr_url is None
    assert item.template is None


def test_work_item_with_all_fields():
    item = WorkItem(
        id="abc123def456",
        project="paperweight",
        template="issue-resolver",
        title="Fix bug PW-42",
        description="Login broken",
        source="linear",
        source_id="uuid-123",
        source_url="https://linear.app/pw/issue/PW-42",
        status=TaskStatus.RUNNING,
        session_id="session-abc",
        pr_url="https://github.com/user/repo/pull/1",
    )
    assert item.template == "issue-resolver"
    assert item.source == "linear"
