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
    format_event_line,
)

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
.header-row { background: #1a1d27 !important; border-bottom: 1px solid #2d3142; }
.stat-card { background: #1a1d27 !important; border: 1px solid #2d3142 !important; }
.panel-card { background: #1a1d27 !important; border: 1px solid #2d3142 !important; }
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
</style>
"""

_HISTORY_COLS = [
    {"name": "project", "label": "Project", "field": "project", "align": "left"},
    {"name": "task", "label": "Task", "field": "task", "align": "left"},
    {"name": "status", "label": "", "field": "status", "align": "center"},
    {"name": "model", "label": "Model", "field": "model", "align": "left"},
    {"name": "cost", "label": "Cost", "field": "cost", "align": "right"},
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

    @ui.page("/dashboard")
    async def dashboard_page(client: Client) -> None:
        ui.dark_mode(True)
        ui.add_head_html(_DASHBOARD_CSS)

        # ── Header ────────────────────────────────────────────────────────────
        with ui.row().classes("header-row w-full items-center justify-between px-6 py-3"):
            with ui.row().classes("items-center gap-3"):
                ui.icon("smart_toy").classes("text-blue-400 text-2xl")
                ui.label("Agent Runner").classes("text-xl font-bold text-white")
                if config.execution.dry_run:
                    ui.badge("DRY RUN").props("color=orange").classes("text-xs font-mono")
            with ui.row().classes("items-center gap-3"):
                budget = state.budget.get_status()
                budget_label = ui.label(
                    f"${budget.spent_today_usd:.2f} / ${budget.daily_limit_usd:.2f}"
                ).classes("text-sm text-gray-300 font-mono")
                ratio = (
                    budget.spent_today_usd / budget.daily_limit_usd
                    if budget.daily_limit_usd > 0
                    else 0.0
                )
                budget_bar = ui.linear_progress(
                    value=min(ratio, 1.0), show_value=False
                ).classes("w-32").props("color=blue size=6px")
                ui.label("daily budget").classes("text-xs text-gray-500")

        # ── Stats ─────────────────────────────────────────────────────────────
        runs = state.history.list_runs_today()

        with ui.row().classes("w-full gap-3 px-6 pt-5"):
            def _stat(label: str, value: str, color: str, icon_name: str) -> ui.label:
                with ui.card().classes("stat-card p-4 min-w-[120px]"):
                    with ui.row().classes("items-center gap-1 mb-1"):
                        ui.icon(icon_name).classes(f"text-{color}-400 text-sm")
                        ui.label(label).classes("text-xs text-gray-400 uppercase tracking-widest")
                    return ui.label(value).classes(f"text-2xl font-bold text-{color}-300")

            s_count = sum(1 for r in runs if r.status == "success")
            f_count = sum(1 for r in runs if r.status in ("failure", "timeout"))
            t_cost = sum(r.cost_usd or 0 for r in runs)
            a_count = sum(1 for r in runs if r.status == "running")

            stat_runs = _stat("Runs Today", str(len(runs)), "blue", "list")
            stat_success = _stat("Success", str(s_count), "green", "check_circle")
            stat_failed = _stat("Failed", str(f_count), "red", "cancel")
            stat_cost = _stat("Cost", f"${t_cost:.2f}", "yellow", "attach_money")
            stat_active = _stat("Active", str(a_count), "cyan", "sync")

        # ── Live Stream + Run History ──────────────────────────────────────────
        with ui.row().classes("w-full gap-4 px-6 pt-4"):
            with ui.card().classes("panel-card flex-1 p-4"):
                with ui.row().classes("items-center gap-2 mb-3"):
                    ui.icon("stream").classes("text-blue-400")
                    ui.label("Live Stream").classes("text-sm font-semibold text-gray-200")
                    stream_badge = ui.badge("idle").props("color=grey").classes("text-xs font-mono")
                log_area = ui.log(max_lines=200).classes("w-full font-mono text-xs rounded")
                log_area.style(
                    "height:280px; background:#0f1117; color:#a3e635; border:1px solid #2d3142"
                )
                log_area.push("— waiting for agent activity —")

            with ui.card().classes("panel-card flex-1 p-4"):
                with ui.row().classes("items-center gap-2 mb-3"):
                    ui.icon("history").classes("text-purple-400")
                    ui.label("Run History").classes("text-sm font-semibold text-gray-200")
                    ui.label("click a row to inspect").classes("text-xs text-gray-600 ml-auto")
                history_table = ui.table(
                    columns=_HISTORY_COLS,
                    rows=build_history_rows(runs),
                    row_key="id",
                ).classes("w-full text-xs")
                history_table.style("max-height:280px; overflow-y:auto")

        # ── Manual Trigger + Scheduled Tasks ──────────────────────────────────
        with ui.row().classes("w-full gap-4 px-6 pt-4 pb-8 items-start"):
            with ui.card().classes("panel-card p-4 w-72"):
                with ui.row().classes("items-center gap-2 mb-3"):
                    ui.icon("play_circle").classes("text-green-400")
                    ui.label("Manual Trigger").classes("text-sm font-semibold text-gray-200")
                project_names = sorted(state.projects.keys())
                project_sel = ui.select(
                    project_names,
                    label="Project",
                    value=project_names[0] if project_names else None,
                ).classes("w-full")
                task_sel = ui.select([], label="Task").classes("w-full mt-2")
                trigger_status = ui.label("").classes("text-xs text-gray-500 mt-1 font-mono")

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
                                f"/tasks/{project_sel.value}/{task_sel.value}/run"
                            )
                        if resp.status_code == 202:
                            proj_task = f"{project_sel.value}/{task_sel.value}"
                            trigger_status.set_text(f"✓ enqueued {proj_task}")
                            ui.notify(
                                f"Triggered {project_sel.value}/{task_sel.value}",
                                type="positive",
                            )
                        else:
                            trigger_status.set_text(f"error {resp.status_code}")
                    except Exception as exc:
                        trigger_status.set_text(f"error: {exc}")

                ui.button("Run Task", on_click=trigger_run, icon="play_arrow").props(
                    "color=primary"
                ).classes("w-full mt-3")

            with ui.card().classes("panel-card flex-1 p-4"):
                with ui.row().classes("items-center gap-2 mb-3"):
                    ui.icon("schedule").classes("text-orange-400")
                    ui.label("Scheduled Tasks").classes("text-sm font-semibold text-gray-200")
                sched_cols = [
                    {"name": "name", "label": "Task", "field": "name", "align": "left"},
                    {"name": "schedule", "label": "Cron", "field": "schedule", "align": "left"},
                    {"name": "model", "label": "Model", "field": "model", "align": "left"},
                    {"name": "cost", "label": "Max $", "field": "cost", "align": "right"},
                    {"name": "autonomy", "label": "Autonomy", "field": "autonomy", "align": "left"},
                ]
                sched_rows = [
                    {
                        "name": f"{proj.name}/{tname}",
                        "schedule": task.schedule,
                        "model": task.model,
                        "cost": f"${task.max_cost_usd:.2f}",
                        "autonomy": task.autonomy,
                    }
                    for proj in state.projects.values()
                    for tname, task in proj.tasks.items()
                    if task.schedule
                ]
                ui.table(columns=sched_cols, rows=sched_rows, row_key="name").classes(
                    "w-full text-xs"
                )

        # ── Run detail drawer ─────────────────────────────────────────────────
        detail_dialog = ui.dialog().props("no-backdrop-dismiss").classes("run-drawer")
        detail_queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        detail_run_id_ref: list[str] = [""]

        def on_row_click(e: object) -> None:
            try:
                row = e.args[1]  # type: ignore[union-attr]
                run_id = row.get("id", "")
                if run_id:
                    _build_run_drawer(
                        dialog=detail_dialog,
                        run_id=run_id,
                        row=row,
                        existing_events=state.run_events.get(run_id, []),
                        detail_queue=detail_queue,
                        detail_run_id_ref=detail_run_id_ref,
                    )
            except Exception:
                pass

        history_table.on("rowClick", on_row_click)

        # ── Global live stream queue ──────────────────────────────────────────
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        state.stream_queues.append(queue)

        def drain_queue() -> None:
            has_active = False
            has_done = False
            while not queue.empty():
                with contextlib.suppress(asyncio.QueueEmpty):
                    data = queue.get_nowait()
                    if detail_run_id_ref[0] == data.get("run_id"):
                        with contextlib.suppress(asyncio.QueueFull):
                            detail_queue.put_nowait(data)
                    log_area.push(format_event_line(data))
                    if data.get("type") == "task_started":
                        has_active = True
                    if data.get("type") in ("task_completed", "task_failed"):
                        has_done = True
            if has_active:
                stream_badge.set_text("active")
                stream_badge.props("color=green")
            if has_done:
                stream_badge.set_text("idle")
                stream_badge.props("color=grey")

        ui.timer(0.15, drain_queue)

        async def refresh() -> None:
            updated = state.history.list_runs_today()
            sc = sum(1 for r in updated if r.status == "success")
            fc = sum(1 for r in updated if r.status in ("failure", "timeout"))
            tc = sum(r.cost_usd or 0 for r in updated)
            ac = sum(1 for r in updated if r.status == "running")
            stat_runs.set_text(str(len(updated)))
            stat_success.set_text(str(sc))
            stat_failed.set_text(str(fc))
            stat_cost.set_text(f"${tc:.2f}")
            stat_active.set_text(str(ac))
            b = state.budget.get_status()
            budget_label.set_text(f"${b.spent_today_usd:.2f} / ${b.daily_limit_usd:.2f}")
            r = b.spent_today_usd / b.daily_limit_usd if b.daily_limit_usd > 0 else 0.0
            budget_bar.set_value(min(r, 1.0))
            history_table.rows = build_history_rows(updated)
            history_table.update()

        ui.timer(3.0, refresh)

        def _cleanup() -> None:
            if queue in state.stream_queues:
                state.stream_queues.remove(queue)

        client.on_disconnect(_cleanup)

    ui.run_with(app)
