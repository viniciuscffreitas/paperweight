"""Tests for executor_utils: ID generation, output parsing, progress logs."""

import json

import pytest

from agents.executor_utils import (
    ClaudeOutput,
    append_progress_log,
    delete_progress_log,
    generate_branch_name,
    generate_run_id,
    parse_claude_output,
    write_progress_log,
)

# ---------------------------------------------------------------------------
# generate_run_id
# ---------------------------------------------------------------------------


def test_generate_run_id_basic_format():
    run_id = generate_run_id("myproject", "lint")
    parts = run_id.split("-")
    # project-task-YYYYMMDD-HHMMSS-uuid8  → at least 4 dash-segments
    assert parts[0] == "myproject"
    assert parts[1] == "lint"
    assert len(parts) >= 4


def test_generate_run_id_includes_issue_id():
    run_id = generate_run_id("proj", "task", issue_id="ABC-123")
    assert "ABC-123" in run_id


def test_generate_run_id_unique():
    a = generate_run_id("proj", "task")
    b = generate_run_id("proj", "task")
    assert a != b


# ---------------------------------------------------------------------------
# generate_branch_name
# ---------------------------------------------------------------------------


def test_generate_branch_name_prefix_and_task():
    branch = generate_branch_name("agents/", "fix-bug")
    assert branch.startswith("agents/fix-bug-")


def test_generate_branch_name_unique():
    import time

    a = generate_branch_name("agents/", "task")
    time.sleep(1.01)  # ensure different timestamp second
    b = generate_branch_name("agents/", "task")
    assert a != b


# ---------------------------------------------------------------------------
# parse_claude_output
# ---------------------------------------------------------------------------


def test_parse_claude_output_valid_json():
    raw = json.dumps({"result": "ok", "is_error": False, "total_cost_usd": 0.05, "num_turns": 3})
    out = parse_claude_output(raw)
    assert out.result == "ok"
    assert out.is_error is False
    assert out.cost_usd == pytest.approx(0.05)
    assert out.num_turns == 3


def test_parse_claude_output_error_flag():
    raw = json.dumps({"result": "boom", "is_error": True, "total_cost_usd": 0.0, "num_turns": 1})
    out = parse_claude_output(raw)
    assert out.is_error is True


def test_parse_claude_output_invalid_json_fallback():
    out = parse_claude_output("not json at all")
    assert out.is_error is True
    assert out.result == "not json at all"


def test_parse_claude_output_missing_fields_default():
    raw = json.dumps({"result": "partial"})
    out = parse_claude_output(raw)
    assert out.cost_usd == 0.0
    assert out.num_turns == 0
    assert out.is_error is False


# ---------------------------------------------------------------------------
# progress log helpers
# ---------------------------------------------------------------------------


def test_write_progress_log_creates_file(tmp_path):
    path = write_progress_log(tmp_path, "ISS-1", attempt=1, issue_title="Fix it")
    assert path.exists()
    content = path.read_text()
    assert "ISS-1" in content
    assert "Fix it" in content
    assert "Attempt 1" in content


def test_write_progress_log_creates_dir(tmp_path):
    nested = tmp_path / "deep" / "dir"
    write_progress_log(nested, "X-9", attempt=2)
    assert (nested / "X-9.txt").exists()


def test_append_progress_log_adds_failure(tmp_path):
    write_progress_log(tmp_path, "ISS-2", attempt=1)
    append_progress_log(tmp_path, "ISS-2", attempt=1, error="timeout")
    content = (tmp_path / "ISS-2.txt").read_text()
    assert "FAILED" in content
    assert "timeout" in content


def test_append_progress_log_noop_if_missing(tmp_path):
    # Should not raise even if file doesn't exist
    append_progress_log(tmp_path, "MISSING-1", attempt=1, error="x")


def test_delete_progress_log_removes_file(tmp_path):
    write_progress_log(tmp_path, "ISS-3", attempt=1)
    delete_progress_log(tmp_path, "ISS-3")
    assert not (tmp_path / "ISS-3.txt").exists()


def test_delete_progress_log_noop_if_missing(tmp_path):
    # Should not raise
    delete_progress_log(tmp_path, "GHOST-99")


# ---------------------------------------------------------------------------
# ClaudeOutput model
# ---------------------------------------------------------------------------


def test_claude_output_defaults():
    out = ClaudeOutput()
    assert out.result == ""
    assert out.is_error is False
    assert out.cost_usd == 0.0
    assert out.num_turns == 0
    assert out.session_id == ""
