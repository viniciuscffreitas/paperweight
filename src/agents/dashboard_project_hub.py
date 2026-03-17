"""Project Hub dashboard page — aggregated project view with right-panel support."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from nicegui import ui

from agents.dashboard_theme import apply_dark_theme

if TYPE_CHECKING:
    from fastapi import FastAPI

    from agents.app_state import AppState

SOURCE_ICONS = {
    "linear": "task_alt",
    "github": "code",
    "slack": "chat",
    "paperweight": "smart_toy",
}
SOURCE_COLORS = {
    "linear": "#5E6AD2",
    "github": "#238636",
    "slack": "#4A154B",
    "paperweight": "#F97316",
}
PRIORITY_COLORS = {
    "urgent": "#EF4444",
    "high": "#F59E0B",
    "medium": "#3B82F6",
    "low": "#6B7280",
    "none": "#374151",
}


def render_hub_content(
    project_id: str, state: AppState, on_close: Callable
) -> None:
    """Render hub content inline — usable inside a right panel or a standalone page."""
    project = state.project_store.get_project(project_id)
    if not project:
        with ui.column().classes("p-8"):
            ui.label("Project not found").classes("text-red-500 text-xl")
        return

    # ── Panel header ──────────────────────────────────────
    with ui.element("div").style(
        "display:flex;align-items:center;justify-content:space-between;"
        "padding:0 20px;height:56px;min-height:56px;flex-shrink:0;"
        "border-bottom:1px solid #1e2130"
    ):
        ui.label(project["name"]).classes("text-base font-bold text-white")
        with ui.row().classes("items-center gap-2"):
            ui.button(
                "Run", icon="play_arrow",
                on_click=lambda: _build_run_dialog(project_id, state).open(),
            ).props("color=green dense flat")
            ui.button(
                icon="delete",
                on_click=lambda: _build_delete_dialog(
                    project_id, project["name"], state, on_close
                ).open(),
            ).props("flat dense color=red")
            ui.button(icon="close", on_click=on_close).props("flat dense color=grey")

    # ── Tabs ──────────────────────────────────────────────
    with ui.tabs().props(
        "indicator-color=blue dense align=left"
    ).classes("w-full").style(
        "border-bottom:1px solid #1e2130;padding:0 20px;"
        "min-height:40px;background:transparent"
    ) as tabs:
        ui.tab("activity", label="ACTIVITY").classes(
            "text-xs font-mono tracking-widest"
        )
        ui.tab("tasks", label="TASKS").classes(
            "text-xs font-mono tracking-widest"
        )
        ui.tab("runs", label="RUNS").classes(
            "text-xs font-mono tracking-widest"
        )

    with ui.tab_panels(tabs, value="activity").classes("flex-1 w-full").style(
        "overflow:hidden;background:transparent"
    ):
        # ── Activity tab ──────────────────────────────────
        with ui.tab_panel("activity").style("padding:0;height:100%;overflow:hidden"):
            with ui.scroll_area().classes("w-full h-full").style("padding:16px"):
                events = state.project_store.list_events(project_id, limit=50)
                if not events:
                    ui.label(
                        "No events yet. Configure sources to start aggregating."
                    ).classes("text-gray-500 italic text-sm")
                for event in events:
                    _render_event_card(event)

                sources = state.project_store.list_sources(project_id)
                source_types = {s["source_type"] for s in sources}
                if source_types:
                    ui.separator().classes("my-3")
                    for st in ["linear", "github", "slack"]:
                        if st in source_types:
                            _render_source_section(st.capitalize(), st, project_id, state)

        # ── Tasks tab ─────────────────────────────────────
        with ui.tab_panel("tasks").style("padding:0;height:100%;overflow:hidden"):
            _render_tasks_tab(project_id, state)

        # ── Runs tab ──────────────────────────────────────
        with ui.tab_panel("runs").style("padding:0;height:100%;overflow:hidden"):
            with ui.scroll_area().classes("w-full h-full").style("padding:16px"):
                _render_runs_content(project_id, state)


def setup_project_hub(app: FastAPI, state: AppState) -> None:
    @ui.page("/dashboard/project/{project_id}")
    async def project_page(project_id: str) -> None:
        apply_dark_theme()

        with ui.element("div").style(
            "display:flex;flex-direction:column;height:100vh;"
            "background:#0d0f18;overflow:hidden"
        ):
            render_hub_content(
                project_id, state,
                on_close=lambda: ui.navigate.to("/dashboard"),
            )


# ── Internal renderers ────────────────────────────────────────────────────────


def _render_tasks_tab(project_id: str, state: AppState) -> None:
    with ui.element("div").style(
        "display:flex;flex-direction:column;height:100%;padding:16px;gap:8px"
    ):
        task_container = ui.column().classes("w-full gap-2 flex-1").style(
            "overflow-y:auto"
        )

        def refresh_tasks() -> None:
            task_container.clear()
            tasks = state.project_store.list_tasks(project_id)
            with task_container:
                if not tasks:
                    ui.label("No tasks yet.").classes("text-gray-500 italic text-sm")
                    return
                for t in tasks:
                    _render_task_row(t, project_id, state, refresh_tasks)

        refresh_tasks()

        ui.button(
            "+ New Task", icon="add",
            on_click=lambda: _build_task_edit_dialog(
                project_id, state, refresh_tasks, task=None
            ).open(),
        ).props("color=blue dense flat")


def _render_task_row(
    task: dict, project_id: str, state: AppState, refresh_fn: Callable
) -> None:
    enabled = bool(task.get("enabled", 1))
    bg = "#1a1d27" if enabled else "#12151f"
    with ui.element("div").style(
        f"display:flex;align-items:center;padding:8px 12px;border-radius:6px;"
        f"background:{bg};gap:8px"
    ):
        with ui.element("div").style("flex:1;min-width:0"):
            ui.label(task["name"]).classes("text-sm text-white")
            ui.label(
                f"{task['trigger_type']} · {task['model']} · ${task['max_budget']:.2f}"
            ).classes("text-xs text-gray-400")
        ui.switch(
            "", value=enabled,
            on_change=lambda e, t=task: (
                state.project_store.update_task(t["id"], enabled=e.value),
                refresh_fn(),
            ),
        ).props("dense")
        ui.button(
            icon="edit",
            on_click=lambda t=task: _build_task_edit_dialog(
                project_id, state, refresh_fn, task=t
            ).open(),
        ).props("flat dense size=sm")
        ui.button(
            icon="delete",
            on_click=lambda t=task: (
                state.project_store.delete_task(t["id"]),
                refresh_fn(),
            ),
        ).props("flat dense size=sm color=red")


def _render_runs_content(project_id: str, state: AppState) -> None:
    try:
        runs = [r for r in state.history.list_runs_today() if r.project == project_id]
    except Exception:
        runs = []
    if not runs:
        ui.label("No runs today").classes("text-gray-500 italic text-sm")
        return
    for run in runs[:20]:
        status_color = {
            "success": "#4ade80",
            "failure": "#f87171",
            "running": "#fb923c",
        }.get(run.status, "#6b7280")
        with ui.element("div").style(
            "display:flex;align-items:center;gap:8px;padding:6px 0;"
            "border-bottom:1px solid #1e2130"
        ):
            ui.html(
                f'<span style="display:inline-block;width:8px;height:8px;'
                f'border-radius:50%;background:{status_color};flex-shrink:0"></span>'
            )
            ui.label(run.task).classes("text-sm text-gray-200 flex-1")
            if run.cost_usd:
                ui.label(f"${run.cost_usd:.2f}").classes("text-xs text-gray-400")
            if run.pr_url:
                ui.link("PR ↗", run.pr_url).classes("text-xs text-blue-400")


def _render_event_card(event: dict) -> None:
    source = event.get("source", "unknown")
    icon = SOURCE_ICONS.get(source, "info")
    color = SOURCE_COLORS.get(source, "#666")
    priority = event.get("priority", "none")
    with ui.row().classes(
        "w-full items-center gap-2 px-2 py-1 rounded hover:bg-gray-800"
    ):
        ui.icon(icon).style(f"color: {color}; font-size: 16px;")
        if priority != "none":
            pcolor = PRIORITY_COLORS.get(priority, "#374151")
            ui.badge(priority.upper()).style(
                f"background-color: {pcolor}; font-size: 10px;"
            )
        ui.label(event.get("title", "")).classes("text-sm text-gray-200 flex-grow")
        ts = event.get("timestamp", "")[:16].replace("T", " ")
        ui.label(ts).classes("text-xs text-gray-500")
        if event.get("author"):
            ui.label(event["author"]).classes("text-xs text-gray-400")


def _render_source_section(
    label: str, source: str, project_id: str, state: AppState
) -> None:
    with ui.expansion(label, icon=SOURCE_ICONS.get(source, "info")).classes(
        "w-full bg-gray-900 rounded"
    ):
        events = state.project_store.list_events(project_id, source=source, limit=20)
        if not events:
            ui.label("No data yet").classes("text-gray-500 italic text-sm")
        else:
            for event in events:
                _render_event_card(event)


def _build_delete_dialog(
    project_id: str, project_name: str, state: AppState, on_close: Callable
) -> ui.dialog:
    dialog = ui.dialog()
    with dialog, ui.card().classes("w-96"):
        ui.label("Remove Project").classes("text-lg font-bold text-white")
        ui.label(
            f'Remove "{project_name}" from the dashboard? '
            "This does not delete the repository."
        ).classes("text-sm text-gray-300 mt-2")
        with ui.row().classes("gap-2 mt-4 justify-end w-full"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            async def confirm_delete() -> None:
                state.project_store.delete_project(project_id)
                ui.notify("Project removed", type="positive")
                dialog.close()
                on_close()

            ui.button("Remove", on_click=confirm_delete).props("color=red")
    return dialog


def _build_run_dialog(project_id: str, state: AppState) -> ui.dialog:
    dialog = ui.dialog()
    with dialog, ui.card().classes("w-96"):
        ui.label("Launch Run").classes("text-lg font-bold")
        tasks = state.project_store.list_tasks(project_id)
        if tasks:
            ui.label("Run existing task:").classes("text-sm mt-2")
            ui.select(
                options={t["id"]: t["name"] for t in tasks}, label="Select task"
            ).classes("w-full")
            ui.button("Run Task", on_click=dialog.close).props("color=green")
        ui.separator()
        ui.label("Ad-hoc run:").classes("text-sm mt-2")
        ui.textarea("Intent", placeholder="What should the agent do?").classes("w-full")
        ui.select(options=["sonnet", "opus", "haiku"], value="sonnet", label="Model").classes(
            "w-full"
        )
        ui.number("Max budget ($)", value=5.0, min=0.1, max=50.0).classes("w-full")
        ui.button("Run Ad-hoc", on_click=dialog.close).props("color=orange")
    return dialog


def _build_task_edit_dialog(
    project_id: str,
    state: AppState,
    refresh_fn: Callable,
    task: dict | None = None,
) -> ui.dialog:
    dialog = ui.dialog()
    is_edit = task is not None
    with dialog, ui.card().classes("w-96"):
        ui.label("Edit Task" if is_edit else "Create Task").classes("text-lg font-bold")
        name_input = ui.input("Name", value=task["name"] if is_edit else "").classes("w-full")
        intent_input = ui.textarea(
            "Intent", value=task["intent"] if is_edit else ""
        ).classes("w-full")
        trigger_select = ui.select(
            ["manual", "schedule", "webhook"],
            value=task["trigger_type"] if is_edit else "manual",
            label="Trigger",
        ).classes("w-full")
        model_select = ui.select(
            ["sonnet", "opus", "haiku"],
            value=task["model"] if is_edit else "sonnet",
            label="Model",
        ).classes("w-full")
        budget_input = ui.number(
            "Max budget ($)",
            value=task["max_budget"] if is_edit else 5.0,
            min=0.1, max=50.0,
        ).classes("w-full")
        autonomy_select = ui.select(
            ["pr-only", "auto-merge", "notify"],
            value=task["autonomy"] if is_edit else "pr-only",
            label="Autonomy",
        ).classes("w-full")

        async def save() -> None:
            if is_edit:
                state.project_store.update_task(
                    task["id"],
                    name=name_input.value,
                    intent=intent_input.value,
                    trigger_type=trigger_select.value,
                    model=model_select.value,
                    max_budget=budget_input.value,
                    autonomy=autonomy_select.value,
                )
                ui.notify("Task updated!", type="positive")
            else:
                state.project_store.create_task(
                    project_id=project_id,
                    name=name_input.value,
                    intent=intent_input.value,
                    trigger_type=trigger_select.value,
                    model=model_select.value,
                    max_budget=budget_input.value,
                    autonomy=autonomy_select.value,
                )
                ui.notify("Task created!", type="positive")
            dialog.close()
            refresh_fn()

        ui.button("Save" if is_edit else "Create", on_click=save).props("color=blue")
    return dialog
