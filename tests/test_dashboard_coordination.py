"""Tests for the dashboard coordination tab."""
from __future__ import annotations

import json

import pytest

from agents.coordination.broker import CoordinationBroker
from agents.coordination.models import CoordinationConfig
from agents.streaming import StreamEvent


@pytest.fixture
def broker():
    return CoordinationBroker(CoordinationConfig(enabled=True))


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


# ---------------------------------------------------------------------------
# Chunk 1 — Broker snapshot API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_coordination_snapshot_empty(broker):
    snapshot = broker.get_coordination_snapshot()
    assert snapshot["claims"] == []
    assert snapshot["mediations"] == []
    assert snapshot["active_runs"] == 0
    assert snapshot["contested_count"] == 0
    assert snapshot["mediating_count"] == 0


@pytest.mark.asyncio
async def test_get_coordination_snapshot_with_claims(broker, wt_a, wt_b):
    await broker.register_run("run-a", wt_a, "add pagination")
    await broker.register_run("run-b", wt_b, "add auth")

    await broker.on_stream_event(
        "run-a",
        StreamEvent(type="tool_use", tool_name="Edit",
                    file_path=str(wt_a / "src/users.py"), timestamp=1.0),
        worktree_root=wt_a,
    )

    snapshot = broker.get_coordination_snapshot()
    assert len(snapshot["claims"]) == 1
    assert snapshot["claims"][0]["file"] == "src/users.py"
    assert snapshot["claims"][0]["owner"] == "run-a"
    assert snapshot["claims"][0]["status"] == "active"
    assert snapshot["claims"][0]["type"] == "hard"
    assert snapshot["active_runs"] == 2
    assert snapshot["contested_count"] == 0


@pytest.mark.asyncio
async def test_get_coordination_snapshot_contested(broker, wt_a, wt_b):
    await broker.register_run("run-a", wt_a, "add pagination")
    await broker.register_run("run-b", wt_b, "add auth")

    await broker.on_stream_event(
        "run-a",
        StreamEvent(type="tool_use", tool_name="Edit",
                    file_path=str(wt_a / "src/users.py"), timestamp=1.0),
        worktree_root=wt_a,
    )

    # B needs same file via inbox
    inbox_b = wt_b / ".paperweight" / "inbox.jsonl"
    with inbox_b.open("a") as f:
        f.write(json.dumps({"type": "need_file", "file": "src/users.py", "intent": "auth"}) + "\n")
    await broker.poll_inboxes_once()

    snapshot = broker.get_coordination_snapshot()
    assert snapshot["contested_count"] == 1
    assert snapshot["claims"][0]["status"] == "contested"


@pytest.mark.asyncio
async def test_get_coordination_snapshot_timeline(broker, wt_a):
    await broker.register_run("run-a", wt_a, "task a")

    await broker.on_stream_event(
        "run-a",
        StreamEvent(type="tool_use", tool_name="Edit",
                    file_path=str(wt_a / "src/x.py"), timestamp=1.0),
        worktree_root=wt_a,
    )

    snapshot = broker.get_coordination_snapshot()
    assert len(snapshot["timeline"]) >= 1
    # Timeline should have most recent event first
    assert snapshot["timeline"][0]["run_id"] == "run-a"


@pytest.mark.asyncio
async def test_timeline_records_register_and_deregister(broker, wt_a):
    await broker.register_run("run-a", wt_a, "task a")
    await broker.deregister_run("run-a")

    snapshot = broker.get_coordination_snapshot()
    types = [e["type"] for e in snapshot["timeline"]]
    assert "registered" in types
    assert "deregistered" in types


@pytest.mark.asyncio
async def test_timeline_capped_at_100(broker, wt_a):
    """Timeline should never grow beyond 100 entries."""
    await broker.register_run("run-a", wt_a, "task a")
    for i in range(120):
        await broker.on_stream_event(
            "run-a",
            StreamEvent(type="tool_use", tool_name="Edit",
                        file_path=str(wt_a / f"src/file{i}.py"), timestamp=float(i)),
            worktree_root=wt_a,
        )
    # Internal timeline capped at 100
    assert len(broker._timeline) <= 100
    # Snapshot returns at most 50
    snapshot = broker.get_coordination_snapshot()
    assert len(snapshot["timeline"]) <= 50
