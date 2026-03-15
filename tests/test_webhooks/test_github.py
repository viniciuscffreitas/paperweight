import hashlib
import hmac


def test_verify_signature_valid():
    from agents.webhooks.github import verify_github_signature

    secret = "test-secret"
    body = b'{"action": "completed"}'
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_github_signature(body, sig, secret) is True


def test_verify_signature_invalid():
    from agents.webhooks.github import verify_github_signature

    assert verify_github_signature(b"body", "sha256=bad", "secret") is False


def test_match_trigger_basic():
    from agents.models import TaskConfig, TriggerConfig
    from agents.webhooks.github import match_github_event

    task = TaskConfig(
        description="fix ci",
        prompt="fix it",
        trigger=TriggerConfig(
            type="github", events=["check_suite.completed"], filter={"conclusion": "failure"}
        ),
    )
    assert (
        match_github_event(
            event_type="check_suite",
            action="completed",
            payload={"conclusion": "failure"},
            task=task,
        )
        is True
    )


def test_match_trigger_wrong_event():
    from agents.models import TaskConfig, TriggerConfig
    from agents.webhooks.github import match_github_event

    task = TaskConfig(
        description="fix ci",
        prompt="fix it",
        trigger=TriggerConfig(type="github", events=["check_suite.completed"]),
    )
    assert match_github_event(event_type="push", action=None, payload={}, task=task) is False


def test_match_trigger_filter_mismatch():
    from agents.models import TaskConfig, TriggerConfig
    from agents.webhooks.github import match_github_event

    task = TaskConfig(
        description="fix ci",
        prompt="fix it",
        trigger=TriggerConfig(
            type="github", events=["check_suite.completed"], filter={"conclusion": "failure"}
        ),
    )
    assert (
        match_github_event(
            event_type="check_suite",
            action="completed",
            payload={"conclusion": "success"},
            task=task,
        )
        is False
    )


def test_extract_github_variables():
    from agents.webhooks.github import extract_github_variables

    payload = {
        "check_suite": {"head_branch": "feat/login", "head_sha": "abc123"},
        "repository": {"full_name": "org/repo"},
        "action": "completed",
    }
    variables = extract_github_variables("check_suite", payload)
    assert variables["branch"] == "feat/login"
    assert variables["sha"] == "abc123"
    assert variables["repo_full_name"] == "org/repo"
