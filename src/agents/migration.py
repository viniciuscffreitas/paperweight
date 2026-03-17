"""YAML to SQLite migration for project configurations."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def migrate_yaml_projects(projects: Any, store: Any) -> int:  # noqa: ANN401
    migrated = 0
    for project_id, config in projects.items():
        if store.get_project(project_id):
            continue
        store.create_project(
            id=project_id,
            name=config.name,
            repo_path=config.repo,
            default_branch=config.base_branch,
        )
        if config.linear_team_id:
            store.create_source(
                project_id=project_id,
                source_type="linear",
                source_id=config.linear_team_id,
                source_name=f"{config.name} Linear",
            )
        for task_name, task in config.tasks.items():
            trigger_type = "manual"
            trigger_config = {}
            if task.schedule:
                trigger_type = "schedule"
                trigger_config = {"cron": task.schedule}
            elif task.trigger:
                trigger_type = "webhook"
                trigger_config = {
                    "type": task.trigger.type,
                    "events": task.trigger.events,
                    "filter": task.trigger.filter,
                }
            store.create_task(
                project_id=project_id,
                name=task_name,
                intent=task.intent or task.prompt or task.description,
                trigger_type=trigger_type,
                trigger_config=trigger_config,
                model=task.model,
                max_budget=task.max_cost_usd,
                autonomy=task.autonomy,
            )
        migrated += 1
    return migrated
