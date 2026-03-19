import json

import pytest


def test_parse_assistant_text():
    from agents.streaming import parse_stream_line

    line = json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello world"}]}}
    )
    event = parse_stream_line(line)
    assert event is not None
    assert event.type == "assistant"
    assert event.content == "Hello world"


def test_parse_assistant_tool_use():
    from agents.streaming import parse_stream_line

    line = json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls -la"}}]
            },
        }
    )
    event = parse_stream_line(line)
    assert event is not None
    assert event.type == "tool_use"
    assert event.tool_name == "Bash"
    assert "ls -la" in event.content


def test_parse_tool_result():
    from agents.streaming import parse_stream_line

    line = json.dumps(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_123",
                        "content": "file1.txt\nfile2.txt",
                    }
                ]
            },
        }
    )
    event = parse_stream_line(line)
    assert event is not None
    assert event.type == "tool_result"
    assert "file1.txt" in event.content


def test_parse_result_success():
    from agents.streaming import parse_stream_line

    line = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "total_cost_usd": 0.45,
            "num_turns": 8,
            "result": "Done!",
        }
    )
    event = parse_stream_line(line)
    assert event is not None
    assert event.type == "result"
    assert event.content == "Done!"


def test_parse_thinking_returns_none():
    from agents.streaming import parse_stream_line

    line = json.dumps(
        {
            "type": "assistant",
            "message": {"content": [{"type": "thinking", "thinking": "hmm..."}]},
        }
    )
    assert parse_stream_line(line) is None


def test_parse_system_hook_returns_none():
    from agents.streaming import parse_stream_line

    line = json.dumps({"type": "system", "subtype": "hook_started"})
    assert parse_stream_line(line) is None


def test_parse_system_init():
    from agents.streaming import parse_stream_line

    line = json.dumps({"type": "system", "subtype": "init", "session_id": "abc"})
    event = parse_stream_line(line)
    assert event is not None
    assert event.type == "system"


def test_parse_malformed_json():
    from agents.streaming import parse_stream_line

    assert parse_stream_line("not json at all") is None


def test_parse_rate_limit_returns_none():
    from agents.streaming import parse_stream_line

    assert parse_stream_line(json.dumps({"type": "rate_limit_event"})) is None


def test_extract_result_from_line():
    from agents.streaming import extract_result_from_line

    line = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "total_cost_usd": 1.23,
            "num_turns": 5,
            "result": "All done",
        }
    )
    output = extract_result_from_line(line)
    assert output.cost_usd == pytest.approx(1.23)
    assert output.num_turns == 5
    assert output.is_error is False


def test_parse_edit_tool_extracts_file_path():
    from agents.streaming import parse_stream_line

    line = json.dumps({
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use",
            "name": "Edit",
            "input": {
                "file_path": "/tmp/agents/run-1/src/api/users.py",
                "old_string": "def get_users():",
                "new_string": "def get_users(cursor=None):",
            },
        }]},
    })
    event = parse_stream_line(line)
    assert event is not None
    assert event.type == "tool_use"
    assert event.tool_name == "Edit"
    assert event.file_path == "/tmp/agents/run-1/src/api/users.py"


def test_parse_write_tool_extracts_file_path():
    from agents.streaming import parse_stream_line

    line = json.dumps({
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use",
            "name": "Write",
            "input": {"file_path": "/tmp/agents/run-1/src/new_file.py", "content": "hello"},
        }]},
    })
    event = parse_stream_line(line)
    assert event is not None
    assert event.file_path == "/tmp/agents/run-1/src/new_file.py"


def test_parse_read_tool_extracts_file_path():
    from agents.streaming import parse_stream_line

    line = json.dumps({
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use",
            "name": "Read",
            "input": {"file_path": "/tmp/agents/run-1/README.md"},
        }]},
    })
    event = parse_stream_line(line)
    assert event is not None
    assert event.file_path == "/tmp/agents/run-1/README.md"


def test_parse_bash_tool_no_file_path():
    from agents.streaming import parse_stream_line

    line = json.dumps({
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use",
            "name": "Bash",
            "input": {"command": "ls -la"},
        }]},
    })
    event = parse_stream_line(line)
    assert event is not None
    assert event.file_path == ""


def test_parse_multi_block_returns_first_only():
    """parse_stream_line returns only the first content block (text wins over tool_use)."""
    from agents.streaming import parse_stream_line

    line = json.dumps({
        "type": "assistant",
        "message": {"content": [
            {"type": "text", "text": "Let me edit that file"},
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "/tmp/x.py", "old_string": "a", "new_string": "b"}},
        ]},
    })
    event = parse_stream_line(line)
    assert event is not None
    # Documents current behavior: text block wins, tool_use is lost
    assert event.type == "assistant"
    assert event.content == "Let me edit that file"
    assert event.tool_name == ""


def test_parse_tool_use_first_when_no_text():
    """When tool_use is the only block, it's correctly returned."""
    from agents.streaming import parse_stream_line

    line = json.dumps({
        "type": "assistant",
        "message": {"content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "/tmp/x.py"}},
        ]},
    })
    event = parse_stream_line(line)
    assert event.type == "tool_use"
    assert event.tool_name == "Edit"
    assert event.file_path == "/tmp/x.py"


def test_parse_empty_content_blocks():
    """Empty content blocks list returns None."""
    from agents.streaming import parse_stream_line

    line = json.dumps({"type": "assistant", "message": {"content": []}})
    assert parse_stream_line(line) is None


def test_parse_non_list_content_blocks():
    """Non-list content returns None."""
    from agents.streaming import parse_stream_line

    line = json.dumps({"type": "assistant", "message": {"content": "just a string"}})
    assert parse_stream_line(line) is None
