"""Formatting utilities for the Agent Runner dashboard."""

from __future__ import annotations

from datetime import UTC, datetime

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
    icon = EVENT_ICONS.get(event_type, "•")

    if event_type in ("task_started", "task_completed", "task_failed", "dry_run"):
        return f"{icon} [{short}] {content}"
    if event_type == "system":
        return f"{icon} [{short}] session started"
    if event_type == "tool_use":
        preview = content[:80] + "…" if len(content) > 80 else content
        return f"{icon} [{short}] {tool_name}: {preview}"
    if event_type == "tool_result":
        preview = content[:80] + "…" if len(content) > 80 else content
        return f"{icon} [{short}] → {preview}"
    if event_type == "assistant":
        preview = content[:120] + "…" if len(content) > 120 else content
        return f"{icon} [{short}] {preview}"
    if event_type == "result":
        return f"{icon} [{short}] done"
    return f"• [{short}] {event_type}: {content[:80]}"


def format_event_html(data: dict) -> str:
    """Rich HTML row for the run detail drawer."""
    event_type = data.get("type", "")
    content = str(data.get("content") or "")
    tool_name = data.get("tool_name") or ""
    icon = EVENT_ICONS.get(event_type, "•")
    color = EVENT_COLORS.get(event_type, "#6b7280")
    ts = data.get("timestamp")
    time_str = datetime.fromtimestamp(ts, tz=UTC).strftime("%H:%M:%S") if ts else "--:--:--"

    if event_type == "tool_use":
        preview = content[:120] + "…" if len(content) > 120 else content
        label = f"{tool_name}: <span style='color:#9ca3af'>{preview}</span>"
    elif event_type == "tool_result":
        preview = content[:120] + "…" if len(content) > 120 else content
        label = f"→ <span style='color:#6b7280'>{preview}</span>"
    elif event_type == "assistant":
        preview = content[:200] + "…" if len(content) > 200 else content
        label = preview
    else:
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
