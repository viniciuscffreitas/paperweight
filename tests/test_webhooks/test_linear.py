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
