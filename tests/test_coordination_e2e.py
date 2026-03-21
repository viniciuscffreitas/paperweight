"""End-to-end tests for the Paperweight Coordination Protocol.

These tests simulate the full coordination lifecycle without the Claude CLI:
two agents working on the same repo, file conflicts, inbox/outbox messaging,
state propagation across worktrees, TTL expiry, and deadlock detection.
"""

import json
import time

import pytest

from agents.coordination.broker import CoordinationBroker
from agents.coordination.models import CoordinationConfig
from agents.streaming import StreamEvent


@pytest.fixture
def broker():
    return CoordinationBroker(CoordinationConfig(enabled=True, poll_interval_ms=50))


@pytest.fixture
def wt_a(tmp_path):
    wt = tmp_path / "wt-a"
    wt.mkdir()
    return wt


@pytest.fixture
def wt_b(tmp_path):
    wt = tmp_path / "wt-b"
    wt.mkdir()
    return wt


def _edit_event(worktree, rel_path):
    """Simulate an Edit tool_use stream-json event."""
    return StreamEvent(
        type="tool_use",
        tool_name="Edit",
        file_path=str(worktree / rel_path),
        timestamp=time.time(),
    )


def _read_event(worktree, rel_path):
    """Simulate a Read tool_use stream-json event."""
    return StreamEvent(
        type="tool_use",
        tool_name="Read",
        file_path=str(worktree / rel_path),
        timestamp=time.time(),
    )


def _write_event(worktree, rel_path):
    """Simulate a Write tool_use stream-json event."""
    return StreamEvent(
        type="tool_use",
        tool_name="Write",
        file_path=str(worktree / rel_path),
        timestamp=time.time(),
    )


def _text_event():
    """Simulate a non-file assistant text event."""
    return StreamEvent(type="assistant", content="thinking...", timestamp=time.time())


# ---------------------------------------------------------------------------
# E2E Scenario 1: Two agents, no conflict (different files)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_agents_no_conflict(broker, wt_a, wt_b):
    """Two agents editing different files should have zero conflicts."""
    await broker.register_run("run-a", wt_a, "add pagination to users")
    await broker.register_run("run-b", wt_b, "add auth middleware")

    # Agent A edits users.py
    conflict_a = await broker.on_stream_event(
        "run-a",
        _edit_event(wt_a, "src/api/users.py"),
        worktree_root=wt_a,
    )
    assert conflict_a is None

    # Agent B edits auth.py (different file)
    conflict_b = await broker.on_stream_event(
        "run-b",
        _edit_event(wt_b, "src/middleware/auth.py"),
        worktree_root=wt_b,
    )
    assert conflict_b is None

    # Both claims exist, no contest
    assert broker.claims.get_claim_for_file("src/api/users.py").run_id == "run-a"
    assert broker.claims.get_claim_for_file("src/middleware/auth.py").run_id == "run-b"

    # State files show each other's claims
    state_a = json.loads((wt_a / ".paperweight" / "state.json").read_text())
    state_b = json.loads((wt_b / ".paperweight" / "state.json").read_text())

    # A's state should show B's claim, not its own
    assert "src/middleware/auth.py" in state_a["claims"]
    assert "src/api/users.py" not in state_a["claims"]  # own claim filtered

    # B's state should show A's claim, not its own
    assert "src/api/users.py" in state_b["claims"]
    assert "src/middleware/auth.py" not in state_b["claims"]

    await broker.deregister_run("run-a")
    await broker.deregister_run("run-b")


# ---------------------------------------------------------------------------
# E2E Scenario 2: Two agents, same file → conflict detected via stream-json
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_agents_same_file_conflict(broker, wt_a, wt_b):
    """Agent B editing a file already claimed by Agent A triggers conflict."""
    await broker.register_run("run-a", wt_a, "add pagination")
    await broker.register_run("run-b", wt_b, "add auth")

    # Agent A claims users.py
    await broker.on_stream_event(
        "run-a",
        _edit_event(wt_a, "src/api/users.py"),
        worktree_root=wt_a,
    )

    # Agent B tries to edit same file
    conflict = await broker.on_stream_event(
        "run-b",
        _edit_event(wt_b, "src/api/users.py"),
        worktree_root=wt_b,
    )

    assert conflict is not None
    assert conflict.run_id == "run-a"
    assert conflict.file_path == "src/api/users.py"

    await broker.deregister_run("run-a")
    await broker.deregister_run("run-b")


# ---------------------------------------------------------------------------
# E2E Scenario 3: Agent reads state.json, writes need_file to inbox
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inbox_need_file_marks_contested(broker, wt_a, wt_b):
    """Simulates: Agent B reads state.json, sees A's claim, writes need_file."""
    await broker.register_run("run-a", wt_a, "add pagination")
    await broker.register_run("run-b", wt_b, "add auth")

    # Agent A claims users.py via Edit
    await broker.on_stream_event(
        "run-a",
        _edit_event(wt_a, "src/api/users.py"),
        worktree_root=wt_a,
    )

    # Agent B sees claim in state.json (verify it's there)
    state_b = json.loads((wt_b / ".paperweight" / "state.json").read_text())
    assert "src/api/users.py" in state_b["claims"]

    # Agent B writes need_file to its inbox (simulates what Claude would do)
    inbox_b = wt_b / ".paperweight" / "inbox.jsonl"
    with inbox_b.open("a") as f:
        f.write(
            json.dumps(
                {
                    "type": "need_file",
                    "file": "src/api/users.py",
                    "intent": "add authentication check to users endpoint",
                }
            )
            + "\n"
        )

    # Broker polls inboxes
    await broker.poll_inboxes_once()

    # Claim should now be CONTESTED
    claim = broker.claims.get_claim_for_file("src/api/users.py")
    assert claim.status.value == "contested"

    # Need should be registered
    assert "src/api/users.py" in broker.claims._needs.get("run-b", set())

    await broker.deregister_run("run-a")
    await broker.deregister_run("run-b")


# ---------------------------------------------------------------------------
# E2E Scenario 4: Heartbeat keeps claims alive, silence causes TTL expiry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ttl_expiry_releases_stale_claims(broker, wt_a):
    """Claims expire when agent stops sending events (TTL)."""
    broker.config.claim_timeout_seconds = 1  # 1 second for test speed

    await broker.register_run("run-a", wt_a, "some task")

    # Agent A claims a file
    await broker.on_stream_event(
        "run-a",
        _edit_event(wt_a, "src/stale.py"),
        worktree_root=wt_a,
    )
    assert broker.claims.get_claim_for_file("src/stale.py") is not None

    # Simulate inactivity — manually set last_activity to the past
    claim = broker.claims.get_claim_for_file("src/stale.py")
    claim.last_activity = time.time() - 2  # older than 1s timeout

    # TTL check should expire the claim
    expired = broker.claims.check_ttl(timeout_seconds=1)
    assert len(expired) == 1
    assert expired[0].file_path == "src/stale.py"
    assert broker.claims.get_claim_for_file("src/stale.py") is None

    await broker.deregister_run("run-a")


@pytest.mark.asyncio
async def test_heartbeat_keeps_claims_alive(broker, wt_a):
    """Heartbeat via inbox resets last_activity, preventing TTL expiry."""
    broker.config.claim_timeout_seconds = 1

    await broker.register_run("run-a", wt_a, "some task")
    await broker.on_stream_event(
        "run-a",
        _edit_event(wt_a, "src/active.py"),
        worktree_root=wt_a,
    )

    # Set claim to almost expired
    claim = broker.claims.get_claim_for_file("src/active.py")
    claim.last_activity = time.time() - 0.9

    # Agent sends heartbeat via inbox
    inbox_a = wt_a / ".paperweight" / "inbox.jsonl"
    with inbox_a.open("a") as f:
        f.write('{"type":"heartbeat"}\n')

    await broker.poll_inboxes_once()

    # Claim should still be alive (heartbeat refreshed activity)
    expired = broker.claims.check_ttl(timeout_seconds=1)
    assert len(expired) == 0
    assert broker.claims.get_claim_for_file("src/active.py") is not None

    await broker.deregister_run("run-a")


# ---------------------------------------------------------------------------
# E2E Scenario 5: Deadlock detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deadlock_detected_via_inbox(broker, wt_a, wt_b):
    """A needs B's file, B needs A's file → deadlock detected."""
    await broker.register_run("run-a", wt_a, "task-a")
    await broker.register_run("run-b", wt_b, "task-b")

    # A claims file X, B claims file Y
    await broker.on_stream_event(
        "run-a",
        _edit_event(wt_a, "src/x.py"),
        worktree_root=wt_a,
    )
    await broker.on_stream_event(
        "run-b",
        _edit_event(wt_b, "src/y.py"),
        worktree_root=wt_b,
    )

    # A needs Y (B's file), B needs X (A's file)
    inbox_a = wt_a / ".paperweight" / "inbox.jsonl"
    with inbox_a.open("a") as f:
        f.write(json.dumps({"type": "need_file", "file": "src/y.py", "intent": "need Y"}) + "\n")

    inbox_b = wt_b / ".paperweight" / "inbox.jsonl"
    with inbox_b.open("a") as f:
        f.write(json.dumps({"type": "need_file", "file": "src/x.py", "intent": "need X"}) + "\n")

    await broker.poll_inboxes_once()

    # Deadlock should be detectable
    cycles = broker.claims.detect_deadlock()
    assert len(cycles) == 1
    assert set(cycles[0]) == {"run-a", "run-b"}

    await broker.deregister_run("run-a")
    await broker.deregister_run("run-b")


# ---------------------------------------------------------------------------
# E2E Scenario 6: Multiple file operations by single agent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_multiple_file_operations(broker, wt_a):
    """Single agent reads, then edits, then writes multiple files."""
    await broker.register_run("run-a", wt_a, "refactor module")

    # Read (soft claim)
    await broker.on_stream_event(
        "run-a",
        _read_event(wt_a, "src/config.py"),
        worktree_root=wt_a,
    )
    claim = broker.claims.get_claim_for_file("src/config.py")
    assert claim.claim_type.value == "soft"

    # Edit same file (upgrade to hard)
    await broker.on_stream_event(
        "run-a",
        _edit_event(wt_a, "src/config.py"),
        worktree_root=wt_a,
    )
    claim = broker.claims.get_claim_for_file("src/config.py")
    assert claim.claim_type.value == "hard"

    # Write a new file
    await broker.on_stream_event(
        "run-a",
        _write_event(wt_a, "src/new_module.py"),
        worktree_root=wt_a,
    )

    # Non-file event (should not create claims)
    await broker.on_stream_event("run-a", _text_event(), worktree_root=wt_a)

    claims = broker.claims.get_claims_for_run("run-a")
    assert len(claims) == 2  # config.py + new_module.py

    await broker.deregister_run("run-a")


# ---------------------------------------------------------------------------
# E2E Scenario 7: State file correctness across 3 agents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_three_agents_state_isolation(broker, tmp_path):
    """Each agent's state.json shows only OTHER agents' claims."""
    wt_a = tmp_path / "wt-a"
    wt_b = tmp_path / "wt-b"
    wt_c = tmp_path / "wt-c"
    for wt in [wt_a, wt_b, wt_c]:
        wt.mkdir()

    await broker.register_run("run-a", wt_a, "task-a")
    await broker.register_run("run-b", wt_b, "task-b")
    await broker.register_run("run-c", wt_c, "task-c")

    await broker.on_stream_event(
        "run-a",
        _edit_event(wt_a, "src/a.py"),
        worktree_root=wt_a,
    )
    await broker.on_stream_event(
        "run-b",
        _edit_event(wt_b, "src/b.py"),
        worktree_root=wt_b,
    )
    await broker.on_stream_event(
        "run-c",
        _edit_event(wt_c, "src/c.py"),
        worktree_root=wt_c,
    )

    # Check A's state: should see B and C, not itself
    state_a = json.loads((wt_a / ".paperweight" / "state.json").read_text())
    assert "src/a.py" not in state_a["claims"]
    assert "src/b.py" in state_a["claims"]
    assert "src/c.py" in state_a["claims"]

    # Check B's state: should see A and C, not itself
    state_b = json.loads((wt_b / ".paperweight" / "state.json").read_text())
    assert "src/b.py" not in state_b["claims"]
    assert "src/a.py" in state_b["claims"]
    assert "src/c.py" in state_b["claims"]

    # Check C's state: should see A and B, not itself
    state_c = json.loads((wt_c / ".paperweight" / "state.json").read_text())
    assert "src/c.py" not in state_c["claims"]
    assert "src/a.py" in state_c["claims"]
    assert "src/b.py" in state_c["claims"]

    for run_id in ["run-a", "run-b", "run-c"]:
        await broker.deregister_run(run_id)


# ---------------------------------------------------------------------------
# E2E Scenario 8: Full lifecycle — register, claim, conflict, release
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_lifecycle_register_claim_conflict_release(broker, wt_a, wt_b):
    """Complete lifecycle: register → claims → conflict → deregister → clean."""
    # 1. Register both agents
    await broker.register_run("run-a", wt_a, "add pagination")
    await broker.register_run("run-b", wt_b, "add auth")
    assert len(broker.active_worktrees) == 2

    # 2. Agent A claims users.py
    await broker.on_stream_event(
        "run-a",
        _edit_event(wt_a, "src/api/users.py"),
        worktree_root=wt_a,
    )

    # 3. Agent B detects conflict (same file)
    conflict = await broker.on_stream_event(
        "run-b",
        _edit_event(wt_b, "src/api/users.py"),
        worktree_root=wt_b,
    )
    assert conflict is not None

    # 4. Agent A finishes and deregisters → claims released
    await broker.deregister_run("run-a")
    assert broker.claims.get_claim_for_file("src/api/users.py") is None
    assert len(broker.active_worktrees) == 1

    # 5. Agent B can now claim the file (no conflict)
    conflict2 = await broker.on_stream_event(
        "run-b",
        _edit_event(wt_b, "src/api/users.py"),
        worktree_root=wt_b,
    )
    assert conflict2 is None
    assert broker.claims.get_claim_for_file("src/api/users.py").run_id == "run-b"

    # 6. Cleanup
    await broker.deregister_run("run-b")
    assert len(broker.active_worktrees) == 0
    assert len(broker.claims._claims) == 0


# ---------------------------------------------------------------------------
# E2E Scenario 9: Broker start/stop lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broker_start_stop_lifecycle():
    """Broker starts poll loop and stops cleanly."""
    broker = CoordinationBroker(CoordinationConfig(enabled=True, poll_interval_ms=50))

    await broker.start()
    assert broker._poll_task is not None
    assert not broker._poll_task.done()

    await broker.stop()
    assert broker._poll_task.done()


@pytest.mark.asyncio
async def test_broker_start_disabled_no_poll():
    """Broker with enabled=False should NOT start poll loop."""
    broker = CoordinationBroker(CoordinationConfig(enabled=False))

    await broker.start()
    assert broker._poll_task is None

    await broker.stop()  # should not error


# ---------------------------------------------------------------------------
# E2E Scenario 10: Escalation message in inbox
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_escalation_message_logged(broker, wt_a, caplog):
    """Agent escalation message is processed and logged."""
    import logging

    await broker.register_run("run-a", wt_a, "stuck task")

    inbox = wt_a / ".paperweight" / "inbox.jsonl"
    with inbox.open("a") as f:
        f.write(
            json.dumps(
                {
                    "type": "escalation",
                    "message": "Cannot find the module to import",
                }
            )
            + "\n"
        )

    with caplog.at_level(logging.WARNING):
        await broker.poll_inboxes_once()

    assert "escalated" in caplog.text
    assert "Cannot find the module" in caplog.text

    await broker.deregister_run("run-a")
