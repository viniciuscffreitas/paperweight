"""Formatting utilities for the Agent Runner dashboard."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

_WORKTREE_RE = re.compile(r"/(?:private/)?tmp/agents/[^/]+/")

TOOL_ICONS: dict[str, str] = {
    "Read": "\U0001f4d6",
    "Bash": "\U0001f527",
    "Edit": "\u270f\ufe0f",
    "Write": "\U0001f4dd",
    "Glob": "\U0001f50d",
    "Grep": "\U0001f50d",
    "Agent": "\U0001f916",
    "Skill": "\u26a1",
    "TodoWrite": "\U0001f4cb",
}


def _shorten_path(path: str) -> str:
    """Strip worktree prefixes from absolute paths to show relative paths."""
    return _WORKTREE_RE.sub("", path)


def _format_tool_use(tool_name: str, content: str) -> tuple[str, str]:
    """Return (icon, formatted_label) for a tool_use event.

    Parses the JSON content to extract meaningful info per tool type.
    """
    icon = TOOL_ICONS.get(tool_name, "\U0001f527")

    try:
        inp = json.loads(content) if content else {}
    except (json.JSONDecodeError, TypeError):
        inp = {}

    if tool_name == "Read":
        fp = _shorten_path(inp.get("file_path", content))
        return icon, f"Read {fp}"

    if tool_name == "Bash":
        cmd = inp.get("command", content)
        cmd = _shorten_path(cmd.replace("\n", " "))
        if len(cmd) > 80:
            cmd = cmd[:80] + "\u2026"
        return icon, f"Bash: {cmd}"

    if tool_name == "Edit":
        fp = _shorten_path(inp.get("file_path", content))
        return icon, f"Edit {fp}"

    if tool_name == "Write":
        fp = _shorten_path(inp.get("file_path", content))
        return icon, f"Write {fp}"

    if tool_name == "Glob":
        pattern = inp.get("pattern", content)
        return icon, f"Glob {pattern}"

    if tool_name == "Grep":
        pattern = inp.get("pattern", content)
        return icon, f'Grep "{pattern}"'

    if tool_name == "Agent":
        desc = inp.get("description", inp.get("prompt", content))
        if len(desc) > 80:
            desc = desc[:80] + "\u2026"
        return icon, f"Agent: {desc}"

    if tool_name == "Skill":
        skill = inp.get("skill", content)
        return icon, f"Skill: {skill}"

    if tool_name == "TodoWrite":
        return icon, "TodoWrite"

    # Fallback for unknown tools
    preview = _shorten_path(content)
    if len(preview) > 80:
        preview = preview[:80] + "\u2026"
    return icon, f"{tool_name}: {preview}"


def _format_tool_result(content: str) -> str:
    """Truncate and clean tool result for display."""
    clean = _shorten_path(content.replace("\n", " ").replace("\r", ""))
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) > 120:
        clean = clean[:120] + "\u2026"
    return f"\u2192 {clean}"

EVENT_ICONS: dict[str, str] = {
    "system": "🔄",
    "assistant": "💬",
    "tool_use": "🔧",
    "tool_result": "📋",
    "result": "✅",
    "task_started": "🚀",
    "task_completed": "✅",
    "task_failed": "❌",
    "dry_run": "⚡",
}

EVENT_COLORS: dict[str, str] = {
    "task_started": "#22d3ee",
    "task_completed": "#4ade80",
    "task_failed": "#f87171",
    "dry_run": "#fbbf24",
    "tool_use": "#fbbf24",
    "tool_result": "#6b7280",
    "assistant": "#e2e8f0",
    "result": "#4ade80",
    "system": "#22d3ee",
    "unknown": "#6b7280",
}

STATUS_ICONS: dict[str, str] = {
    "success": "✅",
    "failure": "❌",
    "running": "🔄",
    "timeout": "⏰",
    "cancelled": "🚫",
}

STATUS_COLORS: dict[str, str] = {
    "success": "#4ade80",
    "running": "#3b82f6",
    "failure": "#f87171",
    "timeout": "#fb923c",
    "cancelled": "#6b7280",
}


def short_run_id(run_id: str) -> str:
    # Format: {project}-{task}-{YYYYMMDD}-{HHMMSS}-{uuid8}
    # Last 3 segments are always date/time/uuid — strip them to get project + task.
    parts = run_id.split("-")
    if len(parts) >= 5:
        project = parts[0]
        task = "-".join(parts[1:-3])
        return f"{project}/{task}"
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return run_id


def format_event_line(data: dict) -> str:
    """Single-line text for the global live stream log."""
    short = short_run_id(data.get("run_id", "?"))
    event_type = data.get("type", "")
    content = str(data.get("content") or "")
    tool_name = data.get("tool_name") or ""

    if event_type in ("task_started", "task_completed", "task_failed", "dry_run"):
        icon = EVENT_ICONS.get(event_type, "\u2022")
        return f"{icon} [{short}] {content}"
    if event_type == "system":
        return f"{EVENT_ICONS['system']} [{short}] session started"
    if event_type == "tool_use":
        icon, label = _format_tool_use(tool_name, content)
        return f"{icon} [{short}] {label}"
    if event_type == "tool_result":
        return f"{EVENT_ICONS['tool_result']} [{short}] {_format_tool_result(content)}"
    if event_type == "assistant":
        preview = _shorten_path(content)
        if len(preview) > 120:
            preview = preview[:120] + "\u2026"
        return f"{EVENT_ICONS['assistant']} [{short}] {preview}"
    if event_type == "result":
        return f"{EVENT_ICONS['result']} [{short}] done"
    return f"\u2022 [{short}] {event_type}: {_shorten_path(content)[:80]}"


def format_event_html(data: dict) -> str:
    """Rich HTML row for the run detail drawer."""
    event_type = data.get("type", "")
    content = str(data.get("content") or "")
    tool_name = data.get("tool_name") or ""
    color = EVENT_COLORS.get(event_type, "#6b7280")
    ts = data.get("timestamp")
    time_str = datetime.fromtimestamp(ts, tz=UTC).strftime("%H:%M:%S") if ts else "--:--:--"

    if event_type == "tool_use":
        icon, label_text = _format_tool_use(tool_name, content)
        label = f"<span style='color:#9ca3af'>{label_text}</span>"
    elif event_type == "tool_result":
        icon = EVENT_ICONS.get(event_type, "\u2022")
        result_text = _format_tool_result(content)
        label = f"<span style='color:#6b7280'>{result_text}</span>"
    elif event_type == "assistant":
        icon = EVENT_ICONS.get(event_type, "\u2022")
        preview = _shorten_path(content)
        if len(preview) > 200:
            preview = preview[:200] + "\u2026"
        label = preview
    else:
        icon = EVENT_ICONS.get(event_type, "\u2022")
        label = content or event_type

    return (
        "<div style='display:flex;gap:8px;padding:3px 0;border-bottom:1px solid #1e2130'>"
        f"<span style='color:#374151;font-size:10px;min-width:60px;padding-top:1px'>"
        f"{time_str}</span>"
        f"<span style='font-size:12px'>{icon}</span>"
        f"<span style='color:{color};font-size:12px;font-family:monospace;"
        f"word-break:break-all'>{label}</span>"
        "</div>"
    )


def build_history_rows(runs: list) -> list[dict]:
    from datetime import UTC, datetime

    rows = []
    for r in runs[:30]:
        duration = "—"
        if r.started_at and r.finished_at:
            secs = int((r.finished_at - r.started_at).total_seconds())
            duration = f"{secs // 60}m{secs % 60:02d}s"
        elif r.started_at and r.status == "running":
            secs = int((datetime.now(UTC) - r.started_at).total_seconds())
            duration = f"~{secs // 60}m{secs % 60:02d}s"
        rows.append(
            {
                "id": r.id,
                "project": r.project,
                "task": r.task,
                "status": STATUS_ICONS.get(r.status, r.status),
                "raw_status": r.status,
                "model": r.model or "—",
                "cost": f"${r.cost_usd:.3f}" if r.cost_usd else "—",
                "duration": duration,
                "trigger": r.trigger_type,
                "pr_url": r.pr_url or "",
            }
        )
    return rows
