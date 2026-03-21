"""Tests for coordination protocol filesystem I/O."""

import json

import pytest


@pytest.fixture
def worktree(tmp_path):
    return tmp_path / "worktree"


def test_init_coordination_dir(worktree):
    from agents.coordination.protocol import init_coordination_dir

    init_coordination_dir(worktree)
    pw = worktree / ".paperweight"
    assert pw.is_dir()
    assert (pw / "state.json").exists()
    assert (pw / "inbox.jsonl").exists()
    assert (pw / "outbox.jsonl").exists()

    state = json.loads((pw / "state.json").read_text())
    assert state["protocol_version"] == 1
    assert state["active_runs"] == {}
    assert state["claims"] == {}
    assert state["mediations"] == {}


def test_write_state_atomic(worktree):
    from agents.coordination.protocol import init_coordination_dir, write_state

    init_coordination_dir(worktree)
    state = {
        "protocol_version": 1,
        "updated_at": "2026-03-19T10:00:00Z",
        "this_run_id": "run-a",
        "active_runs": {},
        "claims": {"src/x.py": {"owner_run": "run-a", "type": "hard"}},
        "mediations": {},
    }
    write_state(worktree, state)
    result = json.loads((worktree / ".paperweight" / "state.json").read_text())
    assert result["claims"]["src/x.py"]["owner_run"] == "run-a"


def test_write_state_no_partial_reads(worktree):
    """Atomic write via tmp+rename means no .tmp file lingers."""
    from agents.coordination.protocol import init_coordination_dir, write_state

    init_coordination_dir(worktree)
    write_state(worktree, {"protocol_version": 1})
    tmp_files = list((worktree / ".paperweight").glob("*.tmp"))
    assert tmp_files == []


def test_append_outbox(worktree):
    from agents.coordination.protocol import append_outbox, init_coordination_dir

    init_coordination_dir(worktree)
    append_outbox(worktree, {"type": "file_released", "file": "x.py"})
    append_outbox(worktree, {"type": "file_mediated", "file": "y.py"})

    lines = (worktree / ".paperweight" / "outbox.jsonl").read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["type"] == "file_released"
    assert json.loads(lines[1])["type"] == "file_mediated"


def test_read_inbox_incremental(worktree):
    from agents.coordination.protocol import init_coordination_dir, read_inbox

    init_coordination_dir(worktree)
    inbox_path = worktree / ".paperweight" / "inbox.jsonl"
    inbox_path.write_text('{"type":"need_file","file":"a.py"}\n{"type":"heartbeat"}\n')

    msgs, pos = read_inbox(worktree, from_position=0)
    assert len(msgs) == 2
    assert msgs[0]["type"] == "need_file"
    assert pos > 0

    # Append more
    with inbox_path.open("a") as f:
        f.write('{"type":"edit_complete","file":"b.py"}\n')

    msgs2, pos2 = read_inbox(worktree, from_position=pos)
    assert len(msgs2) == 1
    assert msgs2[0]["type"] == "edit_complete"
    assert pos2 > pos


def test_read_inbox_empty(worktree):
    from agents.coordination.protocol import init_coordination_dir, read_inbox

    init_coordination_dir(worktree)
    msgs, pos = read_inbox(worktree, from_position=0)
    assert msgs == []
    assert pos == 0


def test_read_inbox_skips_malformed_json(worktree):
    """Malformed JSONL lines are skipped, valid ones still parsed."""
    from agents.coordination.protocol import init_coordination_dir, read_inbox

    init_coordination_dir(worktree)
    inbox_path = worktree / ".paperweight" / "inbox.jsonl"
    inbox_path.write_text(
        '{"type":"heartbeat"}\n'
        "THIS IS NOT JSON\n"
        '{"type":"edit_complete","file":"x.py"}\n'
        "{invalid json too}\n"
    )

    msgs, pos = read_inbox(worktree, from_position=0)
    assert len(msgs) == 2  # only the 2 valid lines
    assert msgs[0]["type"] == "heartbeat"
    assert msgs[1]["type"] == "edit_complete"
    assert pos > 0


def test_read_inbox_all_malformed(worktree):
    """All malformed lines results in empty list but advanced position."""
    from agents.coordination.protocol import init_coordination_dir, read_inbox

    init_coordination_dir(worktree)
    inbox_path = worktree / ".paperweight" / "inbox.jsonl"
    inbox_path.write_text("not json\nalso not json\n")

    msgs, pos = read_inbox(worktree, from_position=0)
    assert msgs == []
    assert pos > 0  # position advanced past the bad lines


def test_write_state_does_not_mutate_input(worktree):
    """write_state should not modify the caller's dict."""
    from agents.coordination.protocol import init_coordination_dir, write_state

    init_coordination_dir(worktree)
    state = {"protocol_version": 1, "claims": {}}
    original_keys = set(state.keys())
    write_state(worktree, state)
    # Caller's dict should not have "updated_at" added
    assert set(state.keys()) == original_keys


def test_append_outbox_does_not_mutate_input(worktree):
    """append_outbox should not modify the caller's dict."""
    from agents.coordination.protocol import append_outbox, init_coordination_dir

    init_coordination_dir(worktree)
    msg = {"type": "file_released", "file": "x.py"}
    original_keys = set(msg.keys())
    append_outbox(worktree, msg)
    assert set(msg.keys()) == original_keys


def test_read_inbox_nonexistent_file(tmp_path):
    """Reading inbox from a path with no .paperweight dir returns empty."""
    from agents.coordination.protocol import read_inbox

    msgs, pos = read_inbox(tmp_path / "nonexistent", from_position=0)
    assert msgs == []
    assert pos == 0
