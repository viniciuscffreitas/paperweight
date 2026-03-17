from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from nicegui import Client, ui

from agents.dashboard_formatters import (
    STATUS_COLORS,
    build_history_rows,
    format_event_html,
    format_stream_html,
)
from agents.dashboard_project_hub import setup_project_hub

if TYPE_CHECKING:
    from fastapi import FastAPI

    from agents.config import GlobalConfig
    from agents.main import AppState

logger = logging.getLogger(__name__)

_DASHBOARD_CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap"
      rel="stylesheet">
<style>
body { background: #0f1117 !important; font-family: 'JetBrains Mono', monospace; }
.nicegui-content { padding: 0 !important; }
.header-row {
    background: #1a1d27 !important;
    border-bottom: 1px solid #2d3142;
    min-height: 48px;
}
.header-divider {
    width: 1px; height: 20px; background: #2d3142;
}
.status-dot {
    display: inline-block; width: 6px; height: 6px;
    border-radius: 50%; flex-shrink: 0;
}
.status-dot.running, .status-dot.active { background: #3b82f6; }
.status-dot.success { background: #4ade80; }
.status-dot.failure, .status-dot.failed { background: #f87171; }
.status-dot.timeout { background: #fb923c; }
.status-dot.cancelled { background: #6b7280; }
.panel-divider {
    width: 1px; background: #2d3142; flex-shrink: 0;
}
.section-label {
    font-size: 9px; color: #6b7280; text-transform: uppercase;
    letter-spacing: 1px; padding: 8px 12px;
    border-bottom: 1px solid #1e2130;
}
.q-table { background: transparent !important; }
.q-table thead tr th {
    background: #0f1117 !important; color: #6b7280 !important;
    font-size: 11px; font-family: 'JetBrains Mono', monospace;
}
.q-table tbody tr { cursor: pointer; }
.q-table tbody tr:hover td { background: #1e2130 !important; }
.run-drawer .q-dialog__inner {
    position: fixed !important;
    right: 0 !important; top: 0 !important; bottom: 0 !important;
    margin: 0 !important;
    max-height: 100vh !important; height: 100vh !important;
    width: 560px !important; max-width: 560px !important;
}
.run-drawer .q-card {
    border-radius: 0 !important; height: 100% !important;
    background: #0d0f18 !important;
    border-left: 1px solid #2d3142 !important;
    box-shadow: -8px 0 32px rgba(0,0,0,0.6) !important;
}
@keyframes live-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
.live-pulse { animation: live-pulse 1.4s ease-in-out infinite; }
.trigger-menu .q-card {
    background: #1a1d27 !important;
    border: 1px solid #2d3142 !important;
}
</style>
"""

_HISTORY_COLS = [
    {"name": "project", "label": "Project", "field": "project", "align": "left"},
    {"name": "task", "label": "Task", "field": "task", "align": "left"},
    {"name": "status", "label": "", "field": "status", "align": "center"},
    {"name": "duration", "label": "Time", "field": "duration", "align": "right"},
]


def _build_run_drawer(
    dialog: ui.dialog,
    run_id: str,
    row: dict,
    existing_events: list[dict],
    detail_queue: asyncio.Queue,
    detail_run_id_ref: list[str],
) -> None:
    """Populate and open the run detail drawer for a given run."""
    is_running = row.get("raw_status") == "running"
    detail_run_id_ref[0] = run_id

    dialog.clear()
    with dialog, ui.card().classes("w-full h-full bg-transparent"):

        # ── Header ──────────────────────────────────────────────────────────
        with ui.row().classes(
            "items-center justify-between px-5 py-4 border-b border-gray-800"
        ):
            with ui.column().classes("gap-1"):
                with ui.row().classes("items-center gap-2"):
                    dot_color = STATUS_COLORS.get(row.get("raw_status", ""), "#6b7280")
                    pulse = ";animation:live-pulse 1.4s infinite" if is_running else ""
                    ui.html(
                        f'<span style="display:inline-block;width:8px;height:8px;'
                        f'border-radius:50%;background:{dot_color}{pulse}"></span>'
                    )
                    ui.label(
                        f"{row.get('project','?')}/{row.get('task','?')}"
                    ).classes("text-base font-bold text-white font-mono")
                    if is_running:
                        ui.html(
                            '<span class="live-pulse" style="color:#ef4444;'
                            'font-size:10px;font-weight:700;letter-spacing:1px">● LIVE</span>'
                        )

                with ui.row().classes("gap-2 flex-wrap"):
                    for text, bg in [
                        (row.get("model", "—"), "#374151"),
                        (row.get("trigger", "—"), "#1e3a5f"),
                        (row.get("duration", "—"), "#1a2744"),
                        (row.get("cost", "—"), "#2d1b0e"),
                    ]:
                        ui.html(
                            f'<span style="background:{bg};color:#9ca3af;font-size:10px;'
                            f'padding:2px 6px;border-radius:4px;font-family:monospace">'
                            f"{text}</span>"
                        )

                pr_url = row.get("pr_url", "")
                if pr_url:
                    label = pr_url.split("/")[-1] if "/" in pr_url else pr_url
                    ui.html(
                        f'<a href="{pr_url}" target="_blank" style="color:#60a5fa;'
                        f'font-size:11px;font-family:monospace">↗ {label}</a>'
                    )

            ui.button(icon="close", on_click=dialog.close).props("flat round dense color=grey")

        # ── Events ──────────────────────────────────────────────────────────
        ui.label("Events").classes("text-xs text-gray-500 uppercase tracking-widest px-5 pt-3")

        with ui.scroll_area().classes("flex-1 px-5 pb-4").style(
            "height: calc(100vh - 160px)"
        ) as scroll:
            event_col = ui.column().classes("w-full gap-0")

        with event_col:
            if existing_events:
                for evt in existing_events:
                    ui.html(format_event_html(evt))
            else:
                ui.label("no events recorded yet").classes("text-gray-600 text-xs font-mono")

        if is_running:
            # Drain stale items from a previous open
            while not detail_queue.empty():
                with contextlib.suppress(asyncio.QueueEmpty):
                    detail_queue.get_nowait()

            def drain_detail() -> None:
                while not detail_queue.empty():
                    with contextlib.suppress(asyncio.QueueEmpty):
                        data = detail_queue.get_nowait()
                        if data.get("run_id") == detail_run_id_ref[0]:
                            with event_col:
                                ui.html(format_event_html(data))
                            scroll.scroll_to(percent=1.0)

            ui.timer(0.2, drain_detail)

    dialog.open()


def setup_dashboard(app: FastAPI, state: AppState, config: GlobalConfig) -> None:
    """Mount NiceGUI dashboard. State accessed via closure (not app.state)."""

    setup_project_hub(app, state)

    @ui.page("/dashboard")
    async def dashboard_page(client: Client) -> None:
        ui.dark_mode(True)
        ui.add_head_html(_DASHBOARD_CSS)

        runs = state.history.list_runs_today()
        a_count = sum(1 for r in runs if r.status == "running")
        f_count = sum(1 for r in runs if r.status in ("failure", "timeout"))

        # ── Header ──────────────────────────────────────────────────
        with ui.row().classes("header-row w-full items-center justify-between px-4 py-2"):
            with ui.row().classes("items-center gap-3"):
                ui.label("Agent Runner").classes("text-base font-bold text-white")
                if config.execution.dry_run:
                    ui.badge("DRY RUN").props("color=orange").classes("text-xs font-mono")

                ui.html('<div class="header-divider"></div>')

                # Inline stats
                with ui.row().classes("items-center gap-3"):
                    ui.html(
                        f'<span class="status-dot active{" live-pulse" if a_count > 0 else ""}"'
                        f' style="{("" if a_count > 0 else "opacity:0.4")}"></span>'
                    )
                    stat_active = ui.label(f"{a_count} active").classes(
                        f"text-xs font-mono {'text-gray-400' if a_count > 0 else 'text-gray-600'}"
                    )
                    ui.html(
                        f'<span class="status-dot failed"'
                        f' style="{("" if f_count > 0 else "opacity:0.4")}"></span>'
                    )
                    stat_failed = ui.label(f"{f_count} failed").classes(
                        f"text-xs font-mono {'text-red-300' if f_count > 0 else 'text-gray-600'}"
                    )

            with ui.row().classes("items-center gap-3"):
                budget = state.budget.get_status()
                budget_label = ui.label(
                    f"${budget.spent_today_usd:.2f} / ${budget.daily_limit_usd:.2f}"
                ).classes("text-xs text-gray-400 font-mono")
                ratio = (
                    budget.spent_today_usd / budget.daily_limit_usd
                    if budget.daily_limit_usd > 0
                    else 0.0
                )
                bar_color = "red" if ratio >= 1.0 else "orange" if ratio >= 0.8 else "blue"
                budget_bar = ui.linear_progress(
                    value=min(ratio, 1.0), show_value=False
                ).classes("w-24").props(f"color={bar_color} size=4px")

                # Trigger button + popover
                trigger_btn = ui.button("Run", icon="play_arrow").props(
                    "flat dense size=sm color=grey"
                )
                with trigger_btn:  # noqa: SIM117
                    with ui.element("q-menu").classes("trigger-menu"):
                        with ui.card().classes("p-3").style(
                            "background:#1a1d27;min-width:220px"
                        ):
                            project_names = sorted(state.projects.keys())
                            project_sel = ui.select(
                                project_names,
                                label="Project",
                                value=project_names[0] if project_names else None,
                            ).classes("w-full")
                            task_sel = ui.select([], label="Task").classes("w-full mt-1")
                            trigger_status = ui.label("").classes(
                                "text-xs text-gray-500 mt-1 font-mono"
                            )

                            def _init_tasks(proj_name: str | None) -> None:
                                project = state.projects.get(proj_name or "")
                                if project:
                                    names = list(project.tasks.keys())
                                    task_sel.options = names
                                    task_sel.value = names[0] if names else None
                                    task_sel.update()

                            project_sel.on_value_change(lambda e: _init_tasks(e.value))
                            _init_tasks(project_names[0] if project_names else None)

                            async def trigger_run() -> None:
                                if not project_sel.value or not task_sel.value:
                                    return
                                import httpx

                                trigger_status.set_text("triggering…")
                                try:
                                    async with httpx.AsyncClient() as http:
                                        resp = await http.post(
                                            f"http://localhost:{config.server.port}"
                                            f"/tasks/{project_sel.value}"
                                            f"/{task_sel.value}/run"
                                        )
                                    if resp.status_code == 202:
                                        trigger_status.set_text(
                                            f"ok {project_sel.value}/{task_sel.value}"
                                        )
                                    else:
                                        trigger_status.set_text(f"error {resp.status_code}")
                                except Exception as exc:
                                    trigger_status.set_text(f"error: {exc}")

                            ui.button("Run Task", on_click=trigger_run).props(
                                "color=primary dense size=sm"
                            ).classes("w-full mt-2")

        # ── Two Panels ──────────────────────────────────────────────────────
        with ui.row().classes("w-full flex-1").style(
            "height: calc(100vh - 48px); overflow: hidden"
        ):
            # Sidebar: Project List
            with ui.column().classes("h-full px-3 py-2").style(
                "width:180px;flex-shrink:0;background:#0d0f18;border-right:1px solid #1e2130;overflow-y:auto"
            ):
                ui.button("+ New Project", on_click=lambda: ui.navigate.to("/dashboard/project/new")).props("color=blue dense flat").classes("w-full mb-2")
                projects = state.project_store.list_projects() if state.project_store else []
                if projects:
                    ui.label("Projects").classes("text-xs text-gray-500 uppercase tracking-wide mb-1")
                    for p in projects:
                        ui.link(p["name"], f"/dashboard/project/{p['id']}").classes("text-sm text-blue-400 hover:text-blue-300 block py-0.5")
                    ui.separator().classes("my-2")

            ui.html('<div class="panel-divider"></div>')

            # Live Stream
            with ui.column().classes("flex-1 h-full").style("flex: 1.2"):
                ui.label("Live Stream").classes("section-label")
                with ui.scroll_area().classes("flex-1 px-3 pb-2").style(
                    "background: #0f1117"
                ) as stream_scroll:
                    stream_col = ui.column().classes("w-full gap-0")
                with stream_col:
                    ui.html(
                        "<div style='color:#4b5563;font-size:11px;font-family:monospace'>"
                        "— waiting for agent activity —</div>"
                    )

            ui.html('<div class="panel-divider"></div>')

            # Run History
            with ui.column().classes("flex-1 h-full"):
                with ui.row().classes(
                    "items-center justify-between"
                ).style("padding:8px 12px;border-bottom:1px solid #1e2130"):
                    ui.label("Run History").classes(
                        "text-xs text-gray-500 uppercase tracking-widest"
                    )
                    ui.label("click a row to inspect").classes("text-xs text-gray-700")
                history_table = ui.table(
                    columns=_HISTORY_COLS,
                    rows=build_history_rows(runs),
                    row_key="id",
                ).classes("w-full text-xs flex-1")
                # Render status column as colored dot
                _pulse = "animation:live-pulse 1.4s infinite"
                _slot = (
                    "<q-td :props=\"props\" style=\"text-align:center\">"
                    "<span :class=\"'status-dot ' + props.row.raw_status\""
                    f" :style=\"props.row.raw_status === 'running' ? '{_pulse}' : ''\">"
                    "</span></q-td>"
                )
                history_table.add_slot("body-cell-status", _slot)

        # ── Run detail drawer ──────────────────────────────────────────
        detail_dialog = ui.dialog().props("no-backdrop-dismiss").classes("run-drawer")
        detail_queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        detail_run_id_ref: list[str] = [""]

        def on_row_click(e: object) -> None:
            try:
                row = e.args[1]  # type: ignore[union-attr]
                run_id = row.get("id", "")
                if run_id:
                    memory_events = state.run_events.get(run_id)
                    events = (
                        memory_events
                        if memory_events is not None
                        else state.history.list_events(run_id)
                    )
                    _build_run_drawer(
                        dialog=detail_dialog,
                        run_id=run_id,
                        row=row,
                        existing_events=events,
                        detail_queue=detail_queue,
                        detail_run_id_ref=detail_run_id_ref,
                    )
            except Exception:
                pass

        history_table.on("rowClick", on_row_click)

        # ── Global live stream queue ───────────────────────────────────
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        state.stream_queues.append(queue)

        max_stream_lines = 200
        stream_line_count = [0]

        def drain_queue() -> None:
            while not queue.empty():
                with contextlib.suppress(asyncio.QueueEmpty):
                    data = queue.get_nowait()
                    if detail_run_id_ref[0] == data.get("run_id"):
                        with contextlib.suppress(asyncio.QueueFull):
                            detail_queue.put_nowait(data)
                    if stream_line_count[0] == 0:
                        stream_col.clear()
                    with stream_col:
                        ui.html(format_stream_html(data))
                    stream_line_count[0] += 1
                    if stream_line_count[0] > max_stream_lines:
                        children = list(stream_col)
                        if children:
                            stream_col.remove(children[0])
                            stream_line_count[0] -= 1
                    stream_scroll.scroll_to(percent=1.0)

        ui.timer(0.15, drain_queue)

        async def refresh() -> None:
            updated = state.history.list_runs_today()
            ac = sum(1 for r in updated if r.status == "running")
            fc = sum(1 for r in updated if r.status in ("failure", "timeout"))
            stat_active.set_text(f"{ac} active")
            stat_failed.set_text(f"{fc} failed")
            b = state.budget.get_status()
            budget_label.set_text(
                f"${b.spent_today_usd:.2f} / ${b.daily_limit_usd:.2f}"
            )
            r = (
                b.spent_today_usd / b.daily_limit_usd
                if b.daily_limit_usd > 0
                else 0.0
            )
            budget_bar.set_value(min(r, 1.0))
            bar_color = "red" if r >= 1.0 else "orange" if r >= 0.8 else "blue"
            budget_bar.props(f"color={bar_color} size=4px")
            history_table.rows = build_history_rows(updated)
            history_table.update()

        ui.timer(3.0, refresh)

        def _cleanup() -> None:
            if queue in state.stream_queues:
                state.stream_queues.remove(queue)

        client.on_disconnect(_cleanup)

    ui.run_with(app)
