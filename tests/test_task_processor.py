from datetime import UTC, datetime

from agents.models import WorkItem
from agents.task_processor import TaskProcessor


def test_build_prompt_basic():
    item = WorkItem(
        id="abc", project="pw", title="Fix bug",
        description="The login page is broken.\nUsers can't sign in.",
        source="manual", created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    prompt = TaskProcessor.build_prompt(item, context_entries=[])
    assert "Fix bug" in prompt
    assert "login page is broken" in prompt

def test_build_prompt_with_context():
    item = WorkItem(
        id="abc", project="pw", title="Fix bug",
        description="Broken login", source="manual",
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    context = [
        {"type": "run_error", "content": "pytest failed: 3 errors in test_auth.py"},
        {"type": "user_feedback", "content": "Try using session tokens instead"},
    ]
    prompt = TaskProcessor.build_prompt(item, context_entries=context)
    assert "pytest failed" in prompt
    assert "session tokens" in prompt

def test_build_prompt_truncates_context():
    item = WorkItem(
        id="abc", project="pw", title="Fix",
        description="D", source="manual",
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    big_context = [{"type": "run_error", "content": "x" * 5000} for _ in range(5)]
    prompt = TaskProcessor.build_prompt(item, context_entries=big_context)
    assert len(prompt) < 10000
