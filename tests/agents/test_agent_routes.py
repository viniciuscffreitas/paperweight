"""Tests for agent session_id capture from Claude CLI output."""

import json

import pytest


@pytest.fixture
def session_mgr(tmp_path):
    from agents.session_manager import SessionManager

    return SessionManager(tmp_path / "test.db")


def test_session_id_captured_from_output_file(tmp_path, session_mgr):
    """Verify session_id is extracted from Claude CLI result line and saved to session."""
    session = session_mgr.create_session("proj", "sonnet", 2.0)
    assert session.claude_session_id is None

    # Simulate Claude CLI output with session_id in result line
    output_file = tmp_path / "run-output.json"
    lines = [
        json.dumps(
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "hello"}]}}
        ),
        json.dumps(
            {
                "type": "result",
                "result": "hello",
                "is_error": False,
                "session_id": "ca252693-8f5f-4ace-b901-23196e57a5b8",
                "total_cost_usd": 0.05,
                "num_turns": 1,
            }
        ),
    ]
    output_file.write_text("\n".join(lines))

    # Run the same capture logic used in agent_routes._run()
    raw = output_file.read_text()
    for line in raw.strip().split("\n"):
        try:
            d = json.loads(line)
            if d.get("type") == "result" and d.get("session_id"):
                session_mgr.update_session(session.id, claude_session_id=d["session_id"])
                break
        except json.JSONDecodeError:
            continue

    updated = session_mgr.get_session(session.id)
    assert updated.claude_session_id == "ca252693-8f5f-4ace-b901-23196e57a5b8"


def test_session_id_not_captured_when_missing(tmp_path, session_mgr):
    """When output has no session_id, session remains unchanged."""
    session = session_mgr.create_session("proj", "sonnet", 2.0)

    output_file = tmp_path / "run-output.json"
    lines = [
        json.dumps(
            {
                "type": "result",
                "result": "hello",
                "is_error": False,
                "total_cost_usd": 0.01,
                "num_turns": 1,
            }
        ),
    ]
    output_file.write_text("\n".join(lines))

    raw = output_file.read_text()
    for line in raw.strip().split("\n"):
        try:
            d = json.loads(line)
            if d.get("type") == "result" and d.get("session_id"):
                session_mgr.update_session(session.id, claude_session_id=d["session_id"])
                break
        except json.JSONDecodeError:
            continue

    updated = session_mgr.get_session(session.id)
    assert updated.claude_session_id is None
