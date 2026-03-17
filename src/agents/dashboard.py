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
from agents.dashboard_project_hub import render_hub_content, setup_project_hub
from agents.dashboard_setup_wizard import render_wizard_content, setup_wizard_page
from agents.dashboard_task_manager import setup_task_manager
from agents.dashboard_theme import apply_dark_theme

if TYPE_CHECKING:
    from fastapi import FastAPI

    from agents.config import GlobalConfig
    from agents.main import AppState

logger = logging.getLogger(__name__)

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

    # Wizard MUST be registered before hub — /project/new must match
    # before /project/{project_id} captures "new" as an ID
    setup_wizard_page(app, state)
    setup_task_manager(app, state)
    setup_project_hub(app, state)

    @ui.page("/dashboard")
    async def dashboard_page(client: Client) -> None:
        apply_dark_theme()

        # Migration prompt: only on first visit (no projects in store yet)
        if (
            hasattr(state, 'projects') and state.projects
            and hasattr(state, 'project_store') and state.project_store
            and not state.project_store.list_projects()
        ):
            with ui.dialog() as migration_dialog, ui.card().classes("w-96"):
                ui.label("Import Projects").classes("text-lg font-bold")
                ui.label(
                    f"Found {len(state.projects)} project(s) in YAML. "
                    "Import them to the dashboard?"
                ).classes("text-sm text-gray-300")
                for name in state.projects:
                    ui.label(f"  • {name}").classes("text-sm text-gray-400")

                async def do_migrate() -> None:
                    from agents.migration import migrate_yaml_projects
                    count = migrate_yaml_projects(
                        state.projects, state.project_store
                    )
                    ui.notify(
                        f"Imported {count} project(s)!",
                        type="positive",
                    )
                    migration_dialog.close()
                    ui.navigate.reload()

                with ui.row().classes("gap-2 mt-4"):
                    ui.button(
                        "Import All", on_click=do_migrate
                    ).props("color=green")
                    ui.button(
                        "Skip", on_click=migration_dialog.close
                    ).props("flat")
            migration_dialog.open()

        runs = state.history.list_runs_today()
        a_count = sum(1 for r in runs if r.status == "running")
        f_count = sum(
            1 for r in runs if r.status in ("failure", "timeout")
        )

        # ── Wizard bottom sheet (lazy — populated on open) ─
        wizard_dialog = ui.dialog().props(
            "no-backdrop-dismiss position=bottom"
        ).classes("bottom-sheet")

        def open_wizard() -> None:
            wizard_dialog.clear()
            with wizard_dialog, ui.card().style(
                "background:transparent;box-shadow:none;"
                "width:100%;height:100%;padding:0;margin:0;overflow:hidden"
            ):
                render_wizard_content(
                    state,
                    on_close=lambda: (wizard_dialog.close(), ui.navigate.reload()),
                )
            wizard_dialog.open()

        # ── Project hub right panel (lazy — populated on open)
        hub_dialog = ui.dialog().props(
            "no-backdrop-dismiss position=right "
            'content-style="width:calc(100vw - 160px);max-width:calc(100vw - 160px);'
            'min-width:480px;height:100vh;overflow:hidden;display:flex;flex-direction:column;'
            'align-items:stretch;background:#0d0f18;border-left:1px solid #2d3142"'
        ).classes("right-panel")

        def open_hub(project_id: str) -> None:
            hub_dialog.clear()
            with hub_dialog, ui.element("div").style(
                "background:#0d0f18;width:calc(100vw - 160px);height:100%;"
                "display:flex;flex-direction:column;overflow:hidden;padding:0;margin:0"
            ):
                render_hub_content(project_id, state, hub_dialog.close)
            hub_dialog.open()

        # ── L-shaped shell: sidebar + header + content ────
        with ui.element("div").style(
            "display:flex;flex-direction:row;"
            "width:100%;height:100vh;overflow:hidden"
        ):
            # ── Sidebar (left column of the L) ────────────
            with ui.element("div").style(
                "width:160px;flex-shrink:0;background:#0a0c14;"
                "overflow-y:auto;display:flex;flex-direction:column;"
                "padding:12px 8px"
            ):
                ui.label("paperweight").classes(
                    "text-sm font-bold text-white mb-4 px-1"
                )
                if config.execution.dry_run:
                    ui.badge("DRY RUN").props(
                        "color=orange"
                    ).classes("text-xs font-mono mb-2")

                ui.label("Projects").classes(
                    "text-xs text-gray-500 uppercase "
                    "tracking-wide mb-1 px-1"
                )
                projects = (
                    state.project_store.list_projects()
                    if state.project_store
                    else []
                )
                for p in projects:
                    pid = p["id"]
                    with ui.element("div").style(
                        "padding:5px 8px;border-radius:4px;cursor:pointer;"
                        "width:100%;box-sizing:border-box;"
                    ).classes(
                        "text-sm text-gray-300 hover:text-white "
                        "hover:bg-gray-800 transition-colors"
                    ).on("click", lambda _pid=pid: open_hub(_pid)):
                        ui.label(p["name"]).style(
                            "white-space:nowrap;overflow:hidden;"
                            "text-overflow:ellipsis;pointer-events:none"
                        )

                ui.space()
                ui.button(
                    "+ New Project",
                    on_click=open_wizard,
                ).props(
                    "flat dense color=blue"
                ).classes("w-full mt-2")

            # ── Right side (header + content) ─────────────
            with ui.element("div").style(
                "flex:1;display:flex;flex-direction:column;"
                "background:#0a0c14;min-height:0;overflow:hidden"
            ):
                # ── Top bar ───────────────────────────────
                with ui.element("div").style(
                    "width:100%;height:48px;min-height:48px;flex-shrink:0;"
                    "background:#0a0c14;display:flex;align-items:center;"
                    "justify-content:space-between;padding:0 20px;box-sizing:border-box"
                ):
                    with ui.row().classes("items-center gap-4"):
                        ui.html(
                            '<span class="status-dot active'
                            f'{"  live-pulse" if a_count else ""}"'
                            f' style="'
                            f'{"" if a_count else "opacity:0.4"}'
                            '"></span>'
                        )
                        stat_active = ui.label(
                            f"{a_count} active"
                        ).classes(
                            "text-xs font-mono "
                            + (
                                "text-gray-400"
                                if a_count
                                else "text-gray-600"
                            )
                        )
                        ui.html(
                            '<span class="status-dot failed"'
                            f' style="'
                            f'{"" if f_count else "opacity:0.4"}'
                            '"></span>'
                        )
                        stat_failed = ui.label(
                            f"{f_count} failed"
                        ).classes(
                            "text-xs font-mono "
                            + (
                                "text-red-300"
                                if f_count
                                else "text-gray-600"
                            )
                        )

                    with ui.row().classes("items-center gap-3"):
                        budget = state.budget.get_status()
                        budget_label = ui.label(
                            f"${budget.spent_today_usd:.2f}"
                            f" / ${budget.daily_limit_usd:.2f}"
                        ).classes(
                            "text-xs text-gray-400 font-mono"
                        )
                        ratio = (
                            budget.spent_today_usd
                            / budget.daily_limit_usd
                            if budget.daily_limit_usd > 0
                            else 0.0
                        )
                        bar_color = (
                            "red"
                            if ratio >= 1.0
                            else "orange"
                            if ratio >= 0.8
                            else "blue"
                        )
                        budget_bar = ui.linear_progress(
                            value=min(ratio, 1.0),
                            show_value=False,
                        ).classes("w-24").props(
                            f"color={bar_color} size=4px"
                        )

                # ── Main content (rounded inner panel) ────
                with ui.row().classes("flex-1 w-full p-3").style(
                    "overflow:hidden"
                ), ui.row().classes("w-full h-full").style(
                    "background:#0f1117;"
                    "border-radius:12px;"
                    "border:1px solid #1e2130;"
                    "overflow:hidden"
                ):
                    # Live Stream
                    with ui.column().classes(
                        "flex-1 h-full"
                    ).style("flex:1.2"):
                        ui.label("Live Stream").classes(
                            "section-label"
                        )
                        with ui.scroll_area().classes(
                            "flex-1 px-3 pb-2"
                        ).style(
                            "background:transparent"
                        ) as stream_scroll:
                            stream_col = ui.column().classes(
                                "w-full gap-0"
                            )
                        with stream_col:
                            ui.html(
                                "<div style='color:#4b5563;"
                                "font-size:11px;"
                                "font-family:monospace'>"
                                "— waiting for agent "
                                "activity —</div>"
                            )

                    ui.html(
                        '<div class="panel-divider"></div>'
                    )

                    # Run History
                    with ui.column().classes("flex-1 h-full"):
                        with ui.row().classes(
                            "items-center justify-between"
                        ).style(
                            "padding:8px 12px;"
                            "border-bottom:"
                            "1px solid #1e2130"
                        ):
                            ui.label("Run History").classes(
                                "text-xs text-gray-500 "
                                "uppercase tracking-widest"
                            )
                            ui.label(
                                "click a row to inspect"
                            ).classes("text-xs text-gray-700")
                        history_table = ui.table(
                            columns=_HISTORY_COLS,
                            rows=build_history_rows(runs),
                            row_key="id",
                        ).classes("w-full text-xs flex-1")
                        _pulse = (
                            "animation:live-pulse 1.4s infinite"
                        )
                        _slot = (
                            '<q-td :props="props" '
                            'style="text-align:center">'
                            "<span :class=\"'status-dot '"
                            " + props.row.raw_status\""
                            " :style=\""
                            "props.row.raw_status === "
                            f"'running' ? '{_pulse}' "
                            ': \'\'">'
                            "</span></q-td>"
                        )
                        history_table.add_slot(
                            "body-cell-status", _slot
                        )

        # ── Run detail drawer ──────────────────────────────────────────
        detail_dialog = ui.dialog().props(
            "no-backdrop-dismiss position=right"
        ).classes("run-drawer")
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
