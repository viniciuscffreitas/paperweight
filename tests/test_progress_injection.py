from pathlib import Path


def test_progress_file_path_injected_into_variables():
    """write_progress_log creates a file at the expected path."""
    from agents.executor_utils import write_progress_log
    import tempfile
    progress_dir = Path(tempfile.mkdtemp()) / "progress"
    issue_id = "issue-abc"
    path = write_progress_log(progress_dir, issue_id, attempt=1, issue_title="Test")
    assert path.exists()
    assert "issue-abc" in str(path)


def test_progress_variable_present_in_build_prompt():
    """build_prompt resolves {{progress_file_path}}."""
    from agents.config import build_prompt
    from agents.models import TaskConfig

    task = TaskConfig(
        description="test",
        intent="Read {{progress_file_path}} for context",
    )
    result = build_prompt(task, {"progress_file_path": "/tmp/progress/issue-1.txt"})
    assert "/tmp/progress/issue-1.txt" in result
    assert "{{progress_file_path}}" not in result
