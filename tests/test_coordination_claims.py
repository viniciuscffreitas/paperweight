"""Tests for ClaimRegistry state machine."""
import time

import pytest


@pytest.fixture
def registry():
    from agents.coordination.claims import ClaimRegistry
    return ClaimRegistry()


def test_soft_claim(registry):
    registry.soft_claim("run-a", "src/x.py")
    claim = registry.get_claim_for_file("src/x.py")
    assert claim is not None
    assert claim.claim_type.value == "soft"
    assert claim.run_id == "run-a"


def test_hard_claim_no_conflict(registry):
    conflict = registry.hard_claim("run-a", "src/x.py")
    assert conflict is None
    claim = registry.get_claim_for_file("src/x.py")
    assert claim is not None
    assert claim.claim_type.value == "hard"


def test_hard_claim_conflict(registry):
    registry.hard_claim("run-a", "src/x.py")
    conflict = registry.hard_claim("run-b", "src/x.py")
    assert conflict is not None
    assert conflict.run_id == "run-a"


def test_hard_claim_same_owner_no_conflict(registry):
    registry.hard_claim("run-a", "src/x.py")
    conflict = registry.hard_claim("run-a", "src/x.py")
    assert conflict is None


def test_soft_claim_upgrades_to_hard(registry):
    registry.soft_claim("run-a", "src/x.py")
    conflict = registry.hard_claim("run-a", "src/x.py")
    assert conflict is None
    claim = registry.get_claim_for_file("src/x.py")
    assert claim.claim_type.value == "hard"


def test_release(registry):
    registry.hard_claim("run-a", "src/x.py")
    registry.release("run-a", "src/x.py")
    assert registry.get_claim_for_file("src/x.py") is None


def test_release_all(registry):
    registry.hard_claim("run-a", "src/x.py")
    registry.hard_claim("run-a", "src/y.py")
    registry.release_all("run-a")
    assert registry.get_claims_for_run("run-a") == []


def test_update_activity(registry):
    registry.hard_claim("run-a", "src/x.py")
    claim = registry.get_claim_for_file("src/x.py")
    old_activity = claim.last_activity
    time.sleep(0.01)
    registry.update_activity("run-a")
    claim = registry.get_claim_for_file("src/x.py")
    assert claim.last_activity > old_activity


def test_check_ttl(registry):
    registry.hard_claim("run-a", "src/x.py")
    claim = registry.get_claim_for_file("src/x.py")
    claim.last_activity = time.time() - 400
    expired = registry.check_ttl(timeout_seconds=300)
    assert len(expired) == 1
    assert expired[0].file_path == "src/x.py"
    assert registry.get_claim_for_file("src/x.py") is None


def test_mark_contested(registry):
    registry.hard_claim("run-a", "src/x.py")
    registry.mark_contested("src/x.py")
    claim = registry.get_claim_for_file("src/x.py")
    assert claim.status.value == "contested"


def test_mark_mediating(registry):
    registry.hard_claim("run-a", "src/x.py")
    registry.mark_mediating("src/x.py")
    claim = registry.get_claim_for_file("src/x.py")
    assert claim.status.value == "mediating"


def test_get_claims_for_run(registry):
    registry.hard_claim("run-a", "src/x.py")
    registry.hard_claim("run-a", "src/y.py")
    registry.hard_claim("run-b", "src/z.py")
    claims = registry.get_claims_for_run("run-a")
    assert len(claims) == 2


def test_detect_deadlock_no_cycle(registry):
    registry.hard_claim("run-a", "src/x.py")
    registry.add_need("run-b", "src/x.py")
    cycles = registry.detect_deadlock()
    assert cycles == []


def test_detect_deadlock_simple_cycle(registry):
    registry.hard_claim("run-a", "src/x.py")
    registry.hard_claim("run-b", "src/y.py")
    registry.add_need("run-a", "src/y.py")
    registry.add_need("run-b", "src/x.py")
    cycles = registry.detect_deadlock()
    assert len(cycles) == 1
    assert set(cycles[0]) == {"run-a", "run-b"}


def test_build_state_snapshot(registry):
    registry.hard_claim("run-a", "src/x.py")
    snapshot = registry.build_state_snapshot("run-b", "intent-b")
    assert "run-a" not in snapshot.get("this_run_id", "")
    assert "src/x.py" in snapshot["claims"]
