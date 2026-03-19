"""Tests for MediatorSpawner prompt building."""


def test_build_mediator_prompt():
    from agents.coordination.mediator import build_mediator_prompt

    prompt = build_mediator_prompt(
        file_path="src/api/users.py",
        file_content="def get_users():\n    return []",
        intent_a="Add pagination with cursor parameter",
        intent_b="Add authentication middleware",
        task_a_description="issue-resolver: ENG-142",
        task_b_description="issue-resolver: ENG-155",
    )
    assert "src/api/users.py" in prompt
    assert "pagination" in prompt.lower()
    assert "authentication" in prompt.lower()
    assert "Agent A" in prompt
    assert "Agent B" in prompt
    assert "def get_users()" in prompt


def test_build_mediator_prompt_with_diff():
    from agents.coordination.mediator import build_mediator_prompt

    prompt = build_mediator_prompt(
        file_path="src/api/users.py",
        file_content="def get_users():\n    return []",
        intent_a="Add pagination",
        intent_b="Add auth",
        task_a_description="resolver",
        task_b_description="resolver",
        diff_a="+ def get_users(cursor=None):",
    )
    assert "diff" in prompt.lower() or "Changes" in prompt


def test_build_coordination_preamble():
    from agents.coordination.mediator import build_coordination_preamble

    preamble = build_coordination_preamble()
    assert "Coordinated Mode" in preamble
    assert "state.json" in preamble
    assert "inbox.jsonl" in preamble
    assert "outbox.jsonl" in preamble
    assert "NEVER force-edit" in preamble
