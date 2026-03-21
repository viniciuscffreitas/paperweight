from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel

from agents.coordination.models import CoordinationConfig
from agents.models import ProjectConfig

if TYPE_CHECKING:
    from agents.models import TaskConfig


class BudgetConfig(BaseModel):
    daily_limit_usd: float = 10.00
    warning_threshold_usd: float = 7.00
    pause_on_limit: bool = True


class NotificationsConfig(BaseModel):
    slack_webhook_url: str = ""


class WebhooksConfig(BaseModel):
    github_secret: str = ""
    linear_secret: str = ""


class ExecutionConfig(BaseModel):
    worktree_base: str = "/tmp/agents"
    default_model: str = "sonnet"
    default_max_cost_usd: float = 5.00
    default_autonomy: str = "pr-only"
    max_concurrent: int = 3
    timeout_minutes: int = 15
    dry_run: bool = False


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080


class IntegrationsConfig(BaseModel):
    linear_api_key: str = ""
    discord_bot_token: str = ""
    discord_guild_id: str = ""
    github_token: str = ""
    slack_bot_token: str = ""
    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""


class GlobalConfig(BaseModel):
    budget: BudgetConfig = BudgetConfig()
    notifications: NotificationsConfig = NotificationsConfig()
    webhooks: WebhooksConfig = WebhooksConfig()
    execution: ExecutionConfig = ExecutionConfig()
    server: ServerConfig = ServerConfig()
    integrations: IntegrationsConfig = IntegrationsConfig()
    coordination: CoordinationConfig = CoordinationConfig()


def resolve_env_vars(value: str) -> str:
    def replacer(match: re.Match[str]) -> str:
        expr = match.group(1)
        if ":" in expr:
            var_name, default = expr.split(":", 1)
            return os.environ.get(var_name, default)
        return os.environ.get(expr, "")

    return re.sub(r"\$\{([^}]+)\}", replacer, value)


def _resolve_dict(data: dict) -> dict:
    resolved = {}
    for key, value in data.items():
        if isinstance(value, str):
            resolved[key] = resolve_env_vars(value)
        elif isinstance(value, dict):
            resolved[key] = _resolve_dict(value)
        else:
            resolved[key] = value
    return resolved


def load_global_config(path: Path) -> GlobalConfig:
    raw = yaml.safe_load(path.read_text())
    resolved = _resolve_dict(raw)
    return GlobalConfig(**resolved)


def load_project_configs(projects_dir: Path) -> dict[str, ProjectConfig]:
    projects: dict[str, ProjectConfig] = {}
    if not projects_dir.exists():
        return projects
    for yaml_file in sorted(projects_dir.glob("*.yaml")):
        raw = yaml.safe_load(yaml_file.read_text())
        if raw.get("name") == "example":
            continue
        resolved = _resolve_dict(raw)
        project = ProjectConfig(**resolved)
        projects[project.name] = project
    return projects


def render_prompt(template: str, variables: dict[str, str]) -> str:
    result = template
    for key, value in variables.items():
        result = result.replace("{{" + key + "}}", value)
    return result


def build_prompt(task: TaskConfig, variables: dict[str, str]) -> str:
    """Build complete prompt from intent/prompt + variables + context hints."""
    raw_intent = task.intent or task.prompt or ""
    intent = render_prompt(raw_intent, variables)

    parts = [intent]

    if variables:
        parts.append("\n## Event Data")
        for key, value in variables.items():
            if value:
                parts.append(f"- {key}: {value}")

    if task.context_hints:
        parts.append("\n## Before starting, gather context:")
        for hint in task.context_hints:
            parts.append(f"- {hint}")

    return "\n".join(parts)
