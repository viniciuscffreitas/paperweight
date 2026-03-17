def test_match_linear_event():
    from agents.models import TaskConfig, TriggerConfig
    from agents.webhooks.linear import match_linear_event

    task = TaskConfig(
        description="handle issue",
        prompt="work on {{issue_title}}",
        trigger=TriggerConfig(
            type="linear", events=["Issue.update"], filter={"status": "In Progress"}
        ),
    )
    assert (
        match_linear_event(
            event_type="Issue", action="update", payload={"status": "In Progress"}, task=task
        )
        is True
    )


def test_match_linear_event_wrong_action():
    from agents.models import TaskConfig, TriggerConfig
    from agents.webhooks.linear import match_linear_event

    task = TaskConfig(
        description="t", prompt="p", trigger=TriggerConfig(type="linear", events=["Issue.create"])
    )
    assert match_linear_event(event_type="Issue", action="update", payload={}, task=task) is False


def test_extract_linear_variables():
    from agents.webhooks.linear import extract_linear_variables

    payload = {
        "data": {
            "id": "ISS-123",
            "title": "Fix login bug",
            "description": "Users can't log in",
            "assignee": {"name": "Vini"},
            "state": {"name": "In Progress"},
        }
    }
    variables = extract_linear_variables(payload)
    assert variables["issue_id"] == "ISS-123"
    assert variables["issue_title"] == "Fix login bug"
    assert variables["assignee"] == "Vini"
    assert variables["status"] == "In Progress"


def test_match_agent_issue_with_agent_label():
    from agents.webhooks.linear import match_agent_issue
    payload = {
        "action": "create", "type": "Issue",
        "data": {"id": "i-1", "labels": [{"name": "agent"}, {"name": "bug"}]},
    }
    assert match_agent_issue(payload) is True

def test_match_agent_issue_without_agent_label():
    from agents.webhooks.linear import match_agent_issue
    payload = {
        "action": "create", "type": "Issue",
        "data": {"id": "i-1", "labels": [{"name": "bug"}]},
    }
    assert match_agent_issue(payload) is False

def test_match_agent_issue_ignores_non_issue_types():
    from agents.webhooks.linear import match_agent_issue
    payload = {
        "action": "create", "type": "Comment",
        "data": {"id": "c-1", "labels": [{"name": "agent"}]},
    }
    assert match_agent_issue(payload) is False

def test_extract_agent_issue_variables():
    from agents.webhooks.linear import extract_agent_issue_variables
    payload = {
        "data": {
            "id": "i-abc", "identifier": "SEK-147",
            "title": "Add pagination", "description": "Add to user list",
            "teamId": "team-xyz",
        }
    }
    v = extract_agent_issue_variables(payload)
    assert v["issue_id"] == "i-abc"
    assert v["issue_identifier"] == "SEK-147"
    assert v["issue_title"] == "Add pagination"
    assert v["team_id"] == "team-xyz"
