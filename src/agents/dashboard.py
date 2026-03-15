from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from fastapi import FastAPI

    from agents.config import GlobalConfig
    from agents.main import AppState

logger = logging.getLogger(__name__)


def setup_dashboard(app: FastAPI, state: AppState, config: GlobalConfig) -> None:
    """Mount NiceGUI dashboard. State accessed via closure."""

    @ui.page("/dashboard")
    async def dashboard_page() -> None:
        ui.dark_mode(True)

        # Header
        with ui.header().classes("items-center justify-between"):
            ui.label("Agent Runner").classes("text-h5 font-bold")
            budget = state.budget.get_status()
            budget_label = ui.label(
                f"Budget: ${budget.spent_today_usd:.2f} / ${budget.daily_limit_usd:.2f}"
            )
            budget_ratio = (
                budget.spent_today_usd / budget.daily_limit_usd if budget.daily_limit_usd > 0 else 0
            )
            budget_bar = ui.linear_progress(
                value=min(budget_ratio, 1.0),
                show_value=False,
            ).classes("w-48")

        # Stats cards
        with ui.row().classes("w-full gap-4 p-4"):
            runs = state.history.list_runs_today()
            success_count = sum(1 for r in runs if r.status == "success")
            failed_count = sum(1 for r in runs if r.status in ("failure", "timeout"))
            total_cost = sum(r.cost_usd or 0 for r in runs)

            for label, value, color in [
                ("Runs Today", str(len(runs)), "blue"),
                ("Success", str(success_count), "green"),
                ("Failed", str(failed_count), "red"),
                ("Cost", f"${total_cost:.2f}", "orange"),
            ]:
                with ui.card().classes("p-4 min-w-[120px]"):
                    ui.label(label).classes("text-sm text-gray-400")
                    ui.label(value).classes(f"text-2xl font-bold text-{color}")

        # Live stream panel
        with ui.card().classes("w-full mx-4"):
            ui.label("Live Stream").classes("text-h6 mb-2")
            log_area = ui.log(max_lines=50).classes("w-full h-64")
            log_area.push("Waiting for agent activity...")

            # JavaScript WebSocket connection for live streaming
            ui.run_javascript("""
                const ws = new WebSocket("ws://" + window.location.host + "/ws/runs");
                ws.onmessage = function(event) {
                    const data = JSON.parse(event.data);
                    const runId = data.run_id || "unknown";
                    const type = data.type || "unknown";
                    const content = data.content || "";
                    const toolName = data.tool_name || "";

                    let line = "";
                    if (type === "tool_use") {
                        line = "[" + runId + "] \ud83d\udd27 " + toolName
                            + ": " + content.substring(0, 100);
                    } else if (type === "tool_result") {
                        line = "[" + runId + "] \ud83d\udccb " + content.substring(0, 100);
                    } else if (type === "assistant") {
                        line = "[" + runId + "] \ud83d\udcac " + content.substring(0, 150);
                    } else if (type === "result") {
                        line = "[" + runId + "] \u2705 Completed";
                    } else if (type === "system") {
                        line = "[" + runId + "] \ud83d\udd04 Session started";
                    }

                    if (line) {
                        const element = document.querySelector('[data-testid="log-area"]');
                        if (element) {
                            element.__vue__.$emit("push", line);
                        }
                    }
                };
                ws.onerror = function(error) {
                    console.error("WebSocket error:", error);
                };
            """)

        # Run history table
        with ui.card().classes("w-full mx-4"):
            ui.label("Run History").classes("text-h6 mb-2")
            columns = [
                {"name": "project", "label": "Project", "field": "project", "align": "left"},
                {"name": "task", "label": "Task", "field": "task", "align": "left"},
                {"name": "status", "label": "Status", "field": "status", "align": "center"},
                {"name": "cost", "label": "Cost", "field": "cost", "align": "right"},
                {"name": "duration", "label": "Duration", "field": "duration", "align": "right"},
                {"name": "pr", "label": "PR", "field": "pr", "align": "left"},
            ]
            rows = []
            for r in runs[:20]:
                duration = ""
                if r.started_at and r.finished_at:
                    delta = r.finished_at - r.started_at
                    minutes, seconds = divmod(int(delta.total_seconds()), 60)
                    duration = f"{minutes}m{seconds:02d}s"
                status_icon = {
                    "success": "\u2705",
                    "failure": "\u274c",
                    "running": "\ud83d\udd04",
                    "timeout": "\u23f0",
                    "cancelled": "\ud83d\udeab",
                }.get(r.status, r.status)
                rows.append(
                    {
                        "project": r.project,
                        "task": r.task,
                        "status": status_icon,
                        "cost": f"${r.cost_usd:.2f}" if r.cost_usd else "\u2014",
                        "duration": duration or "\u2014",
                        "pr": r.pr_url.split("/")[-1] if r.pr_url else "\u2014",
                    }
                )
            ui.table(columns=columns, rows=rows, row_key="project").classes("w-full")

        # Manual trigger
        with ui.card().classes("w-full mx-4"):
            ui.label("Manual Trigger").classes("text-h6 mb-2")
            with ui.row().classes("items-end gap-4"):
                project_names = list(state.projects.keys())
                project_select = ui.select(
                    project_names,
                    label="Project",
                    value=project_names[0] if project_names else None,
                ).classes("w-48")
                task_select = ui.select([], label="Task").classes("w-48")

                def on_project_change(e: object) -> None:
                    project = state.projects.get(project_select.value, None)
                    if project:
                        task_names = list(project.tasks.keys())
                        task_select.options = task_names
                        task_select.value = task_names[0] if task_names else None
                        task_select.update()

                project_select.on_value_change(on_project_change)
                # Initialize task list
                if project_names:
                    first_project = state.projects.get(project_names[0])
                    if first_project:
                        task_names = list(first_project.tasks.keys())
                        task_select.options = task_names
                        task_select.value = task_names[0] if task_names else None

                async def trigger_run() -> None:
                    if project_select.value and task_select.value:
                        import httpx

                        async with httpx.AsyncClient() as client:
                            await client.post(
                                f"http://localhost:{config.server.port}/tasks/{project_select.value}/{task_select.value}/run"
                            )
                        ui.notify(
                            f"Triggered {project_select.value}/{task_select.value}",
                            type="positive",
                        )

                ui.button("Run", on_click=trigger_run, icon="play_arrow").props("color=primary")

        # Scheduled tasks
        with ui.card().classes("w-full mx-4 mb-8"):
            ui.label("Scheduled Tasks").classes("text-h6 mb-2")
            for project in state.projects.values():
                for task_name, task in project.tasks.items():
                    if task.schedule:
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("schedule").classes("text-gray-400")
                            ui.label(f"{project.name}/{task_name}").classes("font-mono text-sm")
                            ui.label(task.schedule).classes("text-sm text-gray-400")

        # Auto-refresh
        async def refresh_stats() -> None:
            b = state.budget.get_status()
            budget_label.text = f"Budget: ${b.spent_today_usd:.2f} / ${b.daily_limit_usd:.2f}"
            ratio = b.spent_today_usd / b.daily_limit_usd if b.daily_limit_usd > 0 else 0
            budget_bar.value = min(ratio, 1.0)

        ui.timer(5.0, refresh_stats)

    ui.run_with(app)
