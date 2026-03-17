"""Project Hub dashboard page — aggregated project view."""
from nicegui import ui

SOURCE_ICONS = {"linear": "task_alt", "github": "code", "slack": "chat", "paperweight": "smart_toy"}
SOURCE_COLORS = {"linear": "#5E6AD2", "github": "#238636", "slack": "#4A154B", "paperweight": "#F97316"}
PRIORITY_COLORS = {"urgent": "#EF4444", "high": "#F59E0B", "medium": "#3B82F6", "low": "#6B7280", "none": "#374151"}


def setup_project_hub(app, state) -> None:
    @ui.page("/dashboard/project/{project_id}")
    async def project_page(project_id: str) -> None:
        project = state.project_store.get_project(project_id)
        if not project:
            ui.label("Project not found").classes("text-red-500 text-xl")
            return

        # Header with name and action buttons
        with ui.row().classes("w-full items-center justify-between mb-4"):
            ui.label(project["name"]).classes("text-2xl font-bold text-white")
            with ui.row().classes("gap-2"):
                ui.button("Run", icon="play_arrow", on_click=lambda: run_dialog.open()).props("color=green dense")
                ui.button("+ Task", icon="add", on_click=lambda: task_dialog.open()).props("color=blue dense")
                ui.button("Tasks", icon="list", on_click=lambda: ui.navigate.to(f"/dashboard/project/{project_id}/tasks")).props("color=purple dense")

        # Zone 1: Feed
        ui.label("Activity Feed").classes("text-lg font-semibold text-gray-300 mt-2")
        events = state.project_store.list_events(project_id, limit=50)
        with ui.column().classes("w-full gap-1 max-h-96 overflow-y-auto"):
            if not events:
                ui.label("No events yet. Configure sources to start aggregating.").classes("text-gray-500 italic")
            for event in events:
                _render_event_card(event)

        # Zone 2: Source Sections
        ui.separator().classes("my-4")
        ui.label("Sources").classes("text-lg font-semibold text-gray-300")
        sources = state.project_store.list_sources(project_id)
        source_types = {s["source_type"] for s in sources}
        for st in ["linear", "github", "slack"]:
            if st in source_types:
                _render_source_section(st.capitalize(), st, project_id, state)
        _render_runs_section(project_id, state)

        # Dialogs
        run_dialog = _build_run_dialog(project_id, state)
        task_dialog = _build_task_dialog(project_id, state)


def _render_event_card(event: dict) -> None:
    source = event.get("source", "unknown")
    icon = SOURCE_ICONS.get(source, "info")
    color = SOURCE_COLORS.get(source, "#666")
    priority = event.get("priority", "none")
    with ui.row().classes("w-full items-center gap-2 px-3 py-1 rounded hover:bg-gray-800"):
        ui.icon(icon).style(f"color: {color}; font-size: 16px;")
        if priority != "none":
            ui.badge(priority.upper()).style(f"background-color: {PRIORITY_COLORS.get(priority, '#374151')}; font-size: 10px;")
        ui.label(event.get("title", "")).classes("text-sm text-gray-200 flex-grow")
        ts = event.get("timestamp", "")[:16].replace("T", " ")
        ui.label(ts).classes("text-xs text-gray-500")
        if event.get("author"):
            ui.label(event["author"]).classes("text-xs text-gray-400")


def _render_source_section(label, source, project_id, state) -> None:
    with ui.expansion(label, icon=SOURCE_ICONS.get(source, "info")).classes("w-full bg-gray-900 rounded"):
        events = state.project_store.list_events(project_id, source=source, limit=20)
        if not events:
            ui.label("No data yet").classes("text-gray-500 italic text-sm")
        else:
            for event in events:
                _render_event_card(event)


def _render_runs_section(project_id, state) -> None:
    with ui.expansion("Runs", icon="smart_toy").classes("w-full bg-gray-900 rounded"):
        try:
            runs = [r for r in state.history.list_runs_today() if r.project == project_id]
        except Exception:
            runs = []
        if not runs:
            ui.label("No runs today").classes("text-gray-500 italic text-sm")
        else:
            for run in runs[:10]:
                status_color = {"success": "green", "failure": "red", "running": "orange"}.get(run.status, "grey")
                with ui.row().classes("w-full items-center gap-2 px-3 py-1"):
                    ui.badge(run.status.upper()).props(f"color={status_color}")
                    ui.label(run.task).classes("text-sm text-gray-200")
                    if run.cost_usd:
                        ui.label(f"${run.cost_usd:.2f}").classes("text-xs text-gray-400")
                    if run.pr_url:
                        ui.link("PR", run.pr_url).classes("text-xs")


def _build_run_dialog(project_id, state) -> ui.dialog:
    dialog = ui.dialog()
    with dialog, ui.card().classes("w-96"):
        ui.label("Launch Run").classes("text-lg font-bold")
        tasks = state.project_store.list_tasks(project_id)
        if tasks:
            ui.label("Run existing task:").classes("text-sm mt-2")
            task_select = ui.select(options={t["id"]: t["name"] for t in tasks}, label="Select task").classes("w-full")
            ui.button("Run Task", on_click=lambda: dialog.close()).props("color=green")
        ui.separator()
        ui.label("Ad-hoc run:").classes("text-sm mt-2")
        ui.textarea("Intent", placeholder="What should the agent do?").classes("w-full")
        ui.select(options=["sonnet", "opus", "haiku"], value="sonnet", label="Model").classes("w-full")
        ui.number("Max budget ($)", value=5.0, min=0.1, max=50.0).classes("w-full")
        ui.button("Run Ad-hoc", on_click=lambda: dialog.close()).props("color=orange")
    return dialog


def _build_task_dialog(project_id, state) -> ui.dialog:
    dialog = ui.dialog()
    with dialog, ui.card().classes("w-96"):
        ui.label("Create Task").classes("text-lg font-bold")
        name_input = ui.input("Name").classes("w-full")
        intent_input = ui.textarea("Intent", placeholder="What should the agent do?").classes("w-full")
        trigger_select = ui.select(options=["manual", "schedule", "webhook"], value="manual", label="Trigger").classes("w-full")
        model_select = ui.select(options=["sonnet", "opus", "haiku"], value="sonnet", label="Model").classes("w-full")
        budget_input = ui.number("Max budget ($)", value=5.0, min=0.1, max=50.0).classes("w-full")
        autonomy_select = ui.select(options=["pr-only", "auto-merge", "notify"], value="pr-only", label="Autonomy").classes("w-full")

        async def create_task() -> None:
            state.project_store.create_task(
                project_id=project_id, name=name_input.value, intent=intent_input.value,
                trigger_type=trigger_select.value, model=model_select.value,
                max_budget=budget_input.value, autonomy=autonomy_select.value,
            )
            dialog.close()
            ui.notify("Task created!", type="positive")

        ui.button("Create", on_click=create_task).props("color=blue")
    return dialog
