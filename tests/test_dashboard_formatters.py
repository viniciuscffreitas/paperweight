"""Tests for dashboard formatting utilities."""

from __future__ import annotations

import time

# ── short_run_id ──────────────────────────────────────────────────────────────


def test_short_run_id_extracts_project_and_task():
    from agents.dashboard_formatters import short_run_id

    result = short_run_id("sekit-dep-update-20260316-030000-abcd1234")
    assert result == "sekit/dep-update"


def test_short_run_id_fallback_for_short_string():
    from agents.dashboard_formatters import short_run_id

    result = short_run_id("onlyone")
    assert result == "onlyone"


# ── format_event_line ─────────────────────────────────────────────────────────


def test_format_event_line_task_started():
    from agents.dashboard_formatters import format_event_line

    data = {
        "run_id": "sekit-ci-fix-20260316-120000-abcd1234",
        "type": "task_started",
        "content": "sekit/ci-fix [github]",
    }
    line = format_event_line(data)
    assert "[sekit/ci-fix]" in line
    assert "sekit/ci-fix [github]" in line
    # No emoji
    assert "🚀" not in line


def test_format_event_line_task_completed():
    from agents.dashboard_formatters import format_event_line

    data = {"run_id": "sekit-ci-fix-x", "type": "task_completed", "content": "done (dry run)"}
    line = format_event_line(data)
    assert "done (dry run)" in line


def test_format_event_line_task_failed():
    from agents.dashboard_formatters import format_event_line

    data = {"run_id": "a-b-x", "type": "task_failed", "content": "Budget exceeded"}
    line = format_event_line(data)
    assert "Budget exceeded" in line
    assert "❌" not in line


def test_format_event_line_dry_run():
    from agents.dashboard_formatters import format_event_line

    data = {"run_id": "a-b-x", "type": "dry_run", "content": "dry_run=true — skipping"}
    line = format_event_line(data)
    assert "dry_run=true" in line
    assert "⚡" not in line


def test_format_event_line_tool_use_truncates():
    from agents.dashboard_formatters import format_event_line

    data = {
        "run_id": "a-b-x",
        "type": "tool_use",
        "tool_name": "Bash",
        "content": "x" * 200,
    }
    line = format_event_line(data)
    assert "Bash" in line
    assert len(line) < 300


def test_format_event_line_tool_result():
    from agents.dashboard_formatters import format_event_line

    data = {"run_id": "a-b-x", "type": "tool_result", "content": "exit code 0"}
    line = format_event_line(data)
    assert "→" in line


def test_format_event_line_assistant():
    from agents.dashboard_formatters import format_event_line

    data = {"run_id": "a-b-x", "type": "assistant", "content": "I found the issue."}
    line = format_event_line(data)
    assert "I found the issue." in line
    assert "💬" not in line


def test_format_event_line_result():
    from agents.dashboard_formatters import format_event_line

    data = {"run_id": "a-b-x", "type": "result", "content": "some result"}
    line = format_event_line(data)
    assert "done" in line


# ── format_event_html ─────────────────────────────────────────────────────────


def test_format_event_html_contains_color_for_type():
    from agents.dashboard_formatters import EVENT_COLORS, format_event_html

    data = {"run_id": "a-b", "type": "tool_use", "tool_name": "Bash", "content": "ls"}
    html = format_event_html(data)
    assert EVENT_COLORS["tool_use"] in html
    assert "Bash" in html
    # No emoji
    assert not any(ord(c) > 0x1F000 for c in html)


def test_format_event_html_tool_use_color_is_light_gray():
    from agents.dashboard_formatters import EVENT_COLORS
    assert EVENT_COLORS["tool_use"] == "#d4d4d8"


def test_format_event_html_includes_timestamp():
    from agents.dashboard_formatters import format_event_html

    ts = time.time()
    data = {"run_id": "a-b", "type": "assistant", "content": "hello", "timestamp": ts}
    html = format_event_html(data)
    assert ":" in html  # HH:MM:SS format
    assert "hello" in html


def test_format_event_html_fallback_when_no_timestamp():
    from agents.dashboard_formatters import format_event_html

    data = {"run_id": "a-b", "type": "system", "content": ""}
    html = format_event_html(data)
    assert "--:--:--" in html


def test_format_event_html_is_valid_html_fragment():
    from agents.dashboard_formatters import format_event_html

    data = {"run_id": "a-b", "type": "task_completed", "content": "done"}
    html = format_event_html(data)
    assert html.startswith("<div")
    assert html.endswith("</div>")


# ── build_history_rows ────────────────────────────────────────────────────────


def _make_run(
    *,
    status: str = "success",
    cost: float | None = None,
    pr_url: str | None = None,
    model: str = "haiku",
) -> object:
    from datetime import UTC, datetime, timedelta

    from agents.models import RunRecord, RunStatus, TriggerType

    now = datetime.now(UTC)
    return RunRecord(
        id=f"p-t-{now.strftime('%Y%m%d-%H%M%S')}-aaaa",
        project="p",
        task="t",
        trigger_type=TriggerType.MANUAL,
        started_at=now - timedelta(seconds=65),
        finished_at=now if status != "running" else None,
        status=RunStatus(status),
        model=model,
        cost_usd=cost,
        pr_url=pr_url,
    )


def test_build_history_rows_success_has_duration():
    from agents.dashboard_formatters import build_history_rows

    rows = build_history_rows([_make_run(status="success")])
    assert len(rows) == 1
    assert "1m" in rows[0]["duration"]


def test_build_history_rows_running_shows_approximate_duration():
    from agents.dashboard_formatters import build_history_rows

    rows = build_history_rows([_make_run(status="running")])
    assert rows[0]["duration"].startswith("~")


def test_build_history_rows_cost_formatted():
    from agents.dashboard_formatters import build_history_rows

    rows = build_history_rows([_make_run(cost=0.042)])
    assert rows[0]["cost"] == "$0.042"


def test_build_history_rows_no_cost_is_dash():
    from agents.dashboard_formatters import build_history_rows

    rows = build_history_rows([_make_run(cost=None)])
    assert rows[0]["cost"] == "—"


def test_build_history_rows_pr_url_included():
    from agents.dashboard_formatters import build_history_rows

    rows = build_history_rows([_make_run(pr_url="https://github.com/org/repo/pull/42")])
    assert rows[0]["pr_url"] == "https://github.com/org/repo/pull/42"


def test_build_history_rows_capped_at_30():
    from agents.dashboard_formatters import build_history_rows

    runs = [_make_run() for _ in range(50)]
    rows = build_history_rows(runs)
    assert len(rows) == 30


# ── format_stream_html ──────────────────────────────────────────────────────

def test_format_stream_html_returns_html_div():
    from agents.dashboard_formatters import format_stream_html
    data = {"run_id": "p-t-x", "type": "tool_use", "tool_name": "Bash", "content": "ls"}
    html = format_stream_html(data)
    assert html.startswith("<div")
    assert html.endswith("</div>")


def test_format_stream_html_no_emoji():
    from agents.dashboard_formatters import format_stream_html
    data = {"run_id": "p-t-x", "type": "task_started", "content": "p/t [manual]"}
    html = format_stream_html(data)
    assert not any(ord(c) > 0x1F000 for c in html)


def test_format_stream_html_uses_correct_color_for_tool_use():
    from agents.dashboard_formatters import format_stream_html
    data = {"run_id": "p-t-x", "type": "tool_use", "tool_name": "Read", "content": '{"file_path":"src/main.py"}'}
    html = format_stream_html(data)
    assert "#d4d4d8" in html
    assert "Read src/main.py" in html


def test_format_stream_html_uses_correct_color_for_failure():
    from agents.dashboard_formatters import format_stream_html
    data = {"run_id": "p-t-x", "type": "task_failed", "content": "timeout"}
    html = format_stream_html(data)
    assert "#f87171" in html


def test_format_stream_html_includes_run_id():
    from agents.dashboard_formatters import format_stream_html
    data = {"run_id": "proj-task-20260316-120000-abcd1234", "type": "assistant", "content": "hello"}
    html = format_stream_html(data)
    assert "proj/task" in html


def test_format_stream_html_no_timestamp_column():
    from agents.dashboard_formatters import format_stream_html
    data = {"run_id": "p-t-x", "type": "system", "content": "", "timestamp": 1710590400.0}
    html = format_stream_html(data)
    assert "--:--:--" not in html
