"""Pydantic models for the coordination protocol."""
from __future__ import annotations

import time
from enum import StrEnum

from pydantic import BaseModel, Field


class ClaimType(StrEnum):
    SOFT = "soft"
    HARD = "hard"


class ClaimStatus(StrEnum):
    ACTIVE = "active"
    CONTESTED = "contested"
    MEDIATING = "mediating"
    RELEASED = "released"
    COMPLETED = "completed"


class MediationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


def _now() -> float:
    return time.time()


class Claim(BaseModel):
    id: str
    run_id: str
    file_path: str
    claim_type: ClaimType
    status: ClaimStatus = ClaimStatus.ACTIVE
    claimed_at: float = Field(default_factory=_now)
    last_activity: float = Field(default_factory=_now)
    released_at: float | None = None
    intent: str = ""


class Mediation(BaseModel):
    id: str
    file_paths: list[str]
    requester_run_ids: list[str]
    mediator_run_id: str | None = None
    status: MediationStatus = MediationStatus.PENDING
    created_at: float = Field(default_factory=_now)
    completed_at: float | None = None


class CoordMessage(BaseModel):
    type: str
    file: str = ""
    intent: str = ""
    mediation_id: str = ""
    action: str = ""
    detail: str = ""
    priority: str = ""
    reason: str = ""
    ts: float = Field(default_factory=_now)


class MediatorConfig(BaseModel):
    model: str = "claude-sonnet-4-6"
    max_cost_usd: float = 1.00
    timeout_minutes: int = 5
    max_concurrent: int = 2


class CoordinationConfig(BaseModel):
    enabled: bool = False
    mode: str = "full-mesh"
    claim_timeout_seconds: int = 300
    poll_interval_ms: int = 500
    auto_rebase: bool = True
    mediator: MediatorConfig = MediatorConfig()
