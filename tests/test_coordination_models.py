"""Tests for coordination Pydantic models and config."""
import pytest


def test_claim_model_defaults():
    from agents.coordination.models import Claim, ClaimStatus, ClaimType

    claim = Claim(
        id="c-001",
        run_id="run-abc",
        file_path="src/api/users.py",
        claim_type=ClaimType.HARD,
    )
    assert claim.status == ClaimStatus.ACTIVE
    assert claim.intent == ""
    assert claim.last_activity == claim.claimed_at


def test_claim_type_enum():
    from agents.coordination.models import ClaimType

    assert ClaimType.SOFT == "soft"
    assert ClaimType.HARD == "hard"


def test_claim_status_enum():
    from agents.coordination.models import ClaimStatus

    assert ClaimStatus.ACTIVE == "active"
    assert ClaimStatus.CONTESTED == "contested"
    assert ClaimStatus.MEDIATING == "mediating"
    assert ClaimStatus.RELEASED == "released"
    assert ClaimStatus.COMPLETED == "completed"


def test_mediation_model_defaults():
    from agents.coordination.models import Mediation, MediationStatus

    med = Mediation(
        id="med-001",
        file_paths=["src/api/users.py"],
        requester_run_ids=["run-a", "run-b"],
    )
    assert med.status == MediationStatus.PENDING
    assert med.mediator_run_id is None


def test_mediation_status_enum():
    from agents.coordination.models import MediationStatus

    assert MediationStatus.PENDING == "pending"
    assert MediationStatus.RUNNING == "running"
    assert MediationStatus.COMPLETED == "completed"
    assert MediationStatus.FAILED == "failed"


def test_coord_message_need_file():
    from agents.coordination.models import CoordMessage

    msg = CoordMessage(type="need_file", file="src/api/users.py", intent="add auth")
    assert msg.type == "need_file"
    assert msg.file == "src/api/users.py"


def test_coordination_config_defaults():
    from agents.coordination.models import CoordinationConfig

    cfg = CoordinationConfig()
    assert cfg.enabled is False
    assert cfg.mode == "full-mesh"
    assert cfg.claim_timeout_seconds == 300
    assert cfg.poll_interval_ms == 500
    assert cfg.auto_rebase is True
    assert cfg.mediator.model == "claude-sonnet-4-6"
    assert cfg.mediator.max_cost_usd == 1.00
    assert cfg.mediator.timeout_minutes == 5
    assert cfg.mediator.max_concurrent == 2


def test_coordination_config_in_global():
    from agents.config import GlobalConfig

    cfg = GlobalConfig()
    assert hasattr(cfg, "coordination")
    assert cfg.coordination.enabled is False
