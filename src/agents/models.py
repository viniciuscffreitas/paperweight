from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class TriggerType(StrEnum):
    SCHEDULE = "schedule"
    GITHUB = "github"
    LINEAR = "linear"
    MANUAL = "manual"
    AGENT = "agent"


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
    intent: str = ""
    context_hints: list[str] = []
    prompt: str | None = None
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
        # Allow manual tasks (neither schedule nor trigger)
        return self

    @model_validator(mode="after")
    def validate_has_intent_or_prompt(self) -> "TaskConfig":
        if not self.intent and not self.prompt:
            msg = "Either intent or prompt must be non-empty"
            raise ValueError(msg)
        return self


class ProjectConfig(BaseModel):
    name: str
    repo: str
    base_branch: str = "main"
    branch_prefix: str = "agents/"
    notify: str = "slack"
    linear_team_id: str = ""
    discord_channel_id: str = ""
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
    session_id: str | None = None
    claude_session_id: str | None = None


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


def _now() -> datetime:
    return datetime.now(UTC)


class ProjectRecord(BaseModel):
    id: str
    name: str
    repo_path: str
    default_branch: str = "main"
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class ProjectSource(BaseModel):
    id: str
    project_id: str
    source_type: str  # "linear", "github", "slack"
    source_id: str
    source_name: str
    config: dict = Field(default_factory=dict)
    enabled: bool = True
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class TaskRecord(BaseModel):
    id: str
    project_id: str
    name: str
    intent: str
    trigger_type: str  # "manual", "schedule", "webhook"
    trigger_config: dict = Field(default_factory=dict)
    model: str = "sonnet"
    max_budget: float = 5.0
    autonomy: str = "pr-only"
    enabled: bool = True
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class AggregatedEvent(BaseModel):
    id: str
    project_id: str
    source: str  # "linear", "github", "slack", "paperweight"
    event_type: str
    title: str
    body: str = ""
    author: str = ""
    url: str = ""
    priority: str = "none"
    timestamp: str
    source_item_id: str
    raw_data: dict = Field(default_factory=dict)


class NotificationRule(BaseModel):
    id: str
    project_id: str
    rule_type: str  # "digest", "alert"
    channel: str  # "slack", "discord"
    channel_target: str  # channel ID or "dm"
    config: dict = Field(default_factory=dict)
    enabled: bool = True


class TaskStatus(StrEnum):
    DRAFT = "draft"
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    REVIEW = "review"
    DONE = "done"
    FAILED = "failed"
    RETRYING = "retrying"


# Forward-compatible aliases — new code uses TaskTemplate, old code still works
TaskTemplate = TaskConfig
TaskTemplateRecord = TaskRecord


class WorkItem(BaseModel):
    id: str
    project: str
    template: str | None = None
    title: str
    description: str
    source: str  # "agent-tab" | "linear" | "github" | "manual" | "schedule"
    source_id: str = ""
    source_url: str = ""
    status: TaskStatus = TaskStatus.PENDING
    session_id: str | None = None
    pr_url: str | None = None
    retry_count: int = 0
    next_retry_at: str | None = None
    spec_path: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
