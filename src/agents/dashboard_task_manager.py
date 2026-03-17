"""Task Manager dashboard page — CRUD for project tasks."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from nicegui import ui

from agents.dashboard_theme import apply_dark_theme

if TYPE_CHECKING:
    from fastapi import FastAPI

    from agents.app_state import AppState


def setup_task_manager(app: FastAPI, state: AppState) -> None:
    @ui.page("/dashboard/project/{project_id}/tasks")
    async def tasks_page(project_id: str) -> None:
        apply_dark_theme()

        project = state.project_store.get_project(project_id)
        if not project:
            ui.label("Project not found").classes("text-red-500")
            return

        ui.label(f"{project['name']} — Tasks").classes("text-2xl font-bold text-white mb-4")

        task_container = ui.column().classes("w-full gap-2")

        def refresh_tasks() -> None:
            task_container.clear()
            tasks_fresh = state.project_store.list_tasks(project_id)
            with task_container:
                if not tasks_fresh:
                    ui.label("No tasks yet.").classes("text-gray-500 italic")
                    return
                with ui.row().classes("w-full px-3 py-1 text-xs text-gray-500 uppercase"):
                    ui.label("Name").classes("w-1/5")
                    ui.label("Trigger").classes("w-1/6")
                    ui.label("Model").classes("w-1/6")
                    ui.label("Budget").classes("w-1/6")
                    ui.label("Status").classes("w-1/6")
                    ui.label("Actions").classes("w-1/6")
                for t in tasks_fresh:
                    _render_task_row(t, project_id, state, refresh_tasks)

        refresh_tasks()

        ui.separator().classes("my-4")

        def open_create() -> None:
            d = _build_task_edit_dialog(project_id, state, refresh_tasks, task=None)
            d.open()

        ui.button("+ New Task", icon="add", on_click=open_create).props("color=blue")
        ui.link(
            "← Back to project", f"/dashboard/project/{project_id}"
        ).classes("text-sm text-blue-400 mt-4")


def _render_task_row(
    task: dict, project_id: str, state: AppState, refresh_fn: Callable[[], None]
) -> None:
    enabled = bool(task.get("enabled", 1))
    bg = "bg-gray-800" if enabled else "bg-gray-900 opacity-50"
    with ui.row().classes(f"w-full items-center px-3 py-2 rounded {bg}"):
        ui.label(task["name"]).classes("w-1/5 text-sm text-white")
        ui.label(task["trigger_type"]).classes("w-1/6 text-sm text-gray-300")
        ui.label(task["model"]).classes("w-1/6 text-sm text-gray-300")
        ui.label(f"${task['max_budget']:.2f}").classes("w-1/6 text-sm text-gray-300")
        with ui.row().classes("w-1/6"):
            def toggle(t: dict = task) -> None:
                state.project_store.update_task(t["id"], enabled=not bool(t["enabled"]))
                refresh_fn()
            ui.switch("", value=enabled, on_change=lambda e, t=task: toggle(t)).props("dense")
        with ui.row().classes("w-1/6 gap-1"):
            def edit(t: dict = task) -> None:
                d = _build_task_edit_dialog(project_id, state, refresh_fn, task=t)
                d.open()
            ui.button(icon="edit", on_click=lambda e, t=task: edit(t)).props("flat dense size=sm")

            def delete(t: dict = task) -> None:
                state.project_store.delete_task(t["id"])
                refresh_fn()
            ui.button(
                icon="delete", on_click=lambda e, t=task: delete(t)
            ).props("flat dense size=sm color=red")


def _build_task_edit_dialog(
    project_id: str,
    state: AppState,
    refresh_fn: Callable[[], None],
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
            min=0.1,
            max=50.0,
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
