"""Tests for CoordinationBroker."""
import asyncio
import json
from pathlib import Path

import pytest

from agents.coordination.models import CoordinationConfig


@pytest.fixture
def config():
    return CoordinationConfig(enabled=True, poll_interval_ms=50)


@pytest.fixture
def broker(config):
    from agents.coordination.broker import CoordinationBroker
    return CoordinationBroker(config)


@pytest.fixture
def worktree_a(tmp_path):
    wt = tmp_path / "wt-a"
    wt.mkdir()
    return wt


@pytest.fixture
def worktree_b(tmp_path):
    wt = tmp_path / "wt-b"
    wt.mkdir()
    return wt


@pytest.mark.asyncio
async def test_register_run(broker, worktree_a):
    await broker.register_run("run-a", worktree_a, "add pagination")
    assert "run-a" in broker.active_worktrees
    state = json.loads((worktree_a / ".paperweight" / "state.json").read_text())
    assert state["this_run_id"] == "run-a"


@pytest.mark.asyncio
async def test_deregister_run(broker, worktree_a):
    await broker.register_run("run-a", worktree_a, "add pagination")
    await broker.deregister_run("run-a")
    assert "run-a" not in broker.active_worktrees


@pytest.mark.asyncio
async def test_on_stream_event_hard_claim(broker, worktree_a):
    from agents.streaming import StreamEvent

    await broker.register_run("run-a", worktree_a, "add pagination")
    abs_path = str(worktree_a / "src" / "users.py")
    event = StreamEvent(
        type="tool_use",
        tool_name="Edit",
        file_path=abs_path,
        timestamp=1.0,
    )
    await broker.on_stream_event("run-a", event, worktree_root=worktree_a)
    claim = broker.claims.get_claim_for_file("src/users.py")
    assert claim is not None
    assert claim.claim_type.value == "hard"


@pytest.mark.asyncio
async def test_on_stream_event_read_soft_claim(broker, worktree_a):
    from agents.streaming import StreamEvent

    await broker.register_run("run-a", worktree_a, "add pagination")
    abs_path = str(worktree_a / "src" / "users.py")
    event = StreamEvent(
        type="tool_use",
        tool_name="Read",
        file_path=abs_path,
        timestamp=1.0,
    )
    await broker.on_stream_event("run-a", event, worktree_root=worktree_a)
    claim = broker.claims.get_claim_for_file("src/users.py")
    assert claim is not None
    assert claim.claim_type.value == "soft"


@pytest.mark.asyncio
async def test_conflict_detection(broker, worktree_a, worktree_b):
    from agents.streaming import StreamEvent

    await broker.register_run("run-a", worktree_a, "add pagination")
    await broker.register_run("run-b", worktree_b, "add auth")

    event_a = StreamEvent(type="tool_use", tool_name="Edit",
                          file_path=str(worktree_a / "src" / "users.py"), timestamp=1.0)
    await broker.on_stream_event("run-a", event_a, worktree_root=worktree_a)

    event_b = StreamEvent(type="tool_use", tool_name="Edit",
                          file_path=str(worktree_b / "src" / "users.py"), timestamp=2.0)
    conflict = await broker.on_stream_event("run-b", event_b, worktree_root=worktree_b)
    assert conflict is not None
    assert conflict.run_id == "run-a"


@pytest.mark.asyncio
async def test_update_all_state_files(broker, worktree_a, worktree_b):
    from agents.streaming import StreamEvent

    await broker.register_run("run-a", worktree_a, "add pagination")
    await broker.register_run("run-b", worktree_b, "add auth")

    event = StreamEvent(type="tool_use", tool_name="Edit",
                        file_path=str(worktree_a / "src" / "users.py"), timestamp=1.0)
    await broker.on_stream_event("run-a", event, worktree_root=worktree_a)

    state_b = json.loads((worktree_b / ".paperweight" / "state.json").read_text())
    assert "src/users.py" in state_b["claims"]


@pytest.mark.asyncio
async def test_has_pending_mediations(broker, worktree_a):
    await broker.register_run("run-a", worktree_a, "task")
    assert not await broker.has_pending_mediations("run-a")


@pytest.mark.asyncio
async def test_process_inbox_need_file(broker, worktree_a, worktree_b):
    await broker.register_run("run-a", worktree_a, "add pagination")
    await broker.register_run("run-b", worktree_b, "add auth")

    from agents.streaming import StreamEvent
    event = StreamEvent(type="tool_use", tool_name="Edit",
                        file_path=str(worktree_a / "src" / "users.py"), timestamp=1.0)
    await broker.on_stream_event("run-a", event, worktree_root=worktree_a)

    inbox = worktree_b / ".paperweight" / "inbox.jsonl"
    with inbox.open("a") as f:
        f.write(json.dumps({"type": "need_file", "file": "src/users.py", "intent": "add auth"}) + "\n")

    await broker.poll_inboxes_once()

    claim = broker.claims.get_claim_for_file("src/users.py")
    assert claim.status.value == "contested"
