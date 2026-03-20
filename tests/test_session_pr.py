from agents.agent_routes import _should_create_pr


def test_should_create_pr_with_commits():
    assert _should_create_pr("abc123 feat: add something\ndef456 test: add test") is True


def test_should_not_create_pr_without_commits():
    assert _should_create_pr("") is False
    assert _should_create_pr("   ") is False
    assert _should_create_pr("\n\n") is False
