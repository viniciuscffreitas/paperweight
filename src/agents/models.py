from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, model_validator


class TriggerType(StrEnum):
    SCHEDULE = "schedule"
    GITHUB = "github"
    LINEAR = "linear"
    MANUAL = "manual"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class TriggerConfig(BaseModel):
    type: str
    events: list[str]
    filter: dict[str, str] = {}


class TaskConfig(BaseModel):
    description: str
    prompt: str
    schedule: str | None = None
    trigger: TriggerConfig | None = None
    model: str = "sonnet"
    max_cost_usd: float = 5.00
    autonomy: str = "pr-only"

    @model_validator(mode="after")
    def validate_schedule_or_trigger(self) -> "TaskConfig":
        if self.schedule and self.trigger:
            msg = "schedule and trigger are mutually exclusive"
            raise ValueError(msg)
        if not self.schedule and not self.trigger:
            msg = "Either schedule or trigger must be set"
            raise ValueError(msg)
        return self


class ProjectConfig(BaseModel):
    name: str
    repo: str
    base_branch: str = "main"
    branch_prefix: str = "agents/"
    notify: str = "slack"
    tasks: dict[str, TaskConfig]


class RunRecord(BaseModel):
    id: str
    project: str
    task: str
    trigger_type: TriggerType
    started_at: datetime
    finished_at: datetime | None = None
    status: RunStatus
    model: str
    num_turns: int | None = None
    cost_usd: float | None = None
    pr_url: str | None = None
    error_message: str | None = None
    output_file: str | None = None


class BudgetStatus(BaseModel):
    daily_limit_usd: float
    spent_today_usd: float
    warning_threshold_usd: float = 7.00

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.daily_limit_usd - self.spent_today_usd)

    @property
    def is_warning(self) -> bool:
        return self.spent_today_usd >= self.warning_threshold_usd

    @property
    def is_exceeded(self) -> bool:
        return self.spent_today_usd >= self.daily_limit_usd
