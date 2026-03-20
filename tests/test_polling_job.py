from agents.polling import find_unprocessed_agent_issues


def test_identifies_unprocessed_issues():
    issues = [
        {"id": "1", "title": "Fix bug", "labels": [{"name": "agent"}],
         "state": {"name": "Backlog"}},
        {"id": "2", "title": "Other", "labels": [{"name": "bug"}],
         "state": {"name": "Backlog"}},
        {"id": "3", "title": "Done one", "labels": [{"name": "agent"}],
         "state": {"name": "Done"}},
    ]
    unprocessed = find_unprocessed_agent_issues(issues)
    assert len(unprocessed) == 1
    assert unprocessed[0]["id"] == "1"

def test_empty_list():
    assert find_unprocessed_agent_issues([]) == []

def test_cancelled_state_excluded():
    issues = [
        {"id": "1", "labels": [{"name": "agent"}], "state": {"name": "Cancelled"}},
    ]
    assert find_unprocessed_agent_issues(issues) == []

def test_duplicate_state_excluded():
    issues = [
        {"id": "1", "labels": [{"name": "agent"}], "state": {"name": "Duplicate"}},
    ]
    assert find_unprocessed_agent_issues(issues) == []
