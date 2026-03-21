from agents.webhooks.github import extract_github_issue_variables, match_github_issue


def test_match_github_issue_opened():
    payload = {
        "action": "opened",
        "issue": {
            "number": 42,
            "title": "Add pagination",
            "body": "We need cursor-based pagination",
            "labels": [{"name": "agent"}],
            "user": {"login": "vini"},
        },
        "repository": {"full_name": "org/repo"},
    }
    assert match_github_issue(payload) is True


def test_match_github_issue_labeled_with_agent():
    payload = {
        "action": "labeled",
        "label": {"name": "agent"},
        "issue": {
            "number": 42,
            "title": "Fix bug",
            "body": "",
            "labels": [{"name": "agent"}, {"name": "bug"}],
        },
    }
    assert match_github_issue(payload) is True


def test_match_github_issue_no_agent_label():
    payload = {"action": "opened", "issue": {"number": 42, "labels": [{"name": "bug"}]}}
    assert match_github_issue(payload) is False


def test_match_github_issue_closed_ignored():
    payload = {"action": "closed", "issue": {"labels": [{"name": "agent"}]}}
    assert match_github_issue(payload) is False


def test_match_github_issue_labeled_non_agent():
    payload = {
        "action": "labeled",
        "label": {"name": "bug"},
        "issue": {"labels": [{"name": "agent"}, {"name": "bug"}]},
    }
    assert match_github_issue(payload) is False


def test_extract_github_issue_variables():
    payload = {
        "action": "opened",
        "issue": {
            "number": 42,
            "title": "Add pagination",
            "body": "Description here",
            "html_url": "https://github.com/org/repo/issues/42",
            "labels": [{"name": "agent"}],
        },
        "repository": {"full_name": "org/repo"},
    }
    variables = extract_github_issue_variables(payload)
    assert variables["issue_number"] == "42"
    assert variables["issue_title"] == "Add pagination"
    assert variables["issue_body"] == "Description here"
    assert variables["issue_url"] == "https://github.com/org/repo/issues/42"
    assert variables["repo_full_name"] == "org/repo"


def test_extract_github_issue_variables_null_body():
    payload = {
        "issue": {"number": 1, "title": "T", "body": None, "html_url": ""},
        "repository": {"full_name": "o/r"},
    }
    variables = extract_github_issue_variables(payload)
    assert variables["issue_body"] == ""
