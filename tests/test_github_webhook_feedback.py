from agents.webhooks.github import extract_pr_merge_info, is_agent_pr_merge


def test_agent_pr_merge_detected():
    payload = {
        "action": "closed",
        "pull_request": {
            "merged": True,
            "title": "[agents] paperweight/issue-resolver",
            "html_url": "https://github.com/user/repo/pull/42",
            "head": {"ref": "agents/issue-resolver-20260320"},
            "body": "## Issue: PW-42 — Fix bug",
        },
    }
    assert is_agent_pr_merge(payload) is True
    info = extract_pr_merge_info(payload)
    assert info["pr_url"] == "https://github.com/user/repo/pull/42"


def test_non_agent_pr_ignored():
    payload = {
        "action": "closed",
        "pull_request": {"merged": True, "title": "Fix typo", "html_url": "url", "head": {"ref": "fix"}},
    }
    assert is_agent_pr_merge(payload) is False


def test_pr_closed_without_merge_ignored():
    payload = {
        "action": "closed",
        "pull_request": {"merged": False, "title": "[agents] pw/resolver", "html_url": "url", "head": {"ref": "a"}},
    }
    assert is_agent_pr_merge(payload) is False


def test_find_run_by_pr_url(tmp_path):
    from datetime import UTC, datetime

    from agents.history import HistoryDB
    from agents.models import RunRecord, RunStatus, TriggerType

    db = HistoryDB(tmp_path / "test.db")
    run = RunRecord(
        id="test-run-1", project="paperweight", task="issue-resolver",
        trigger_type=TriggerType.LINEAR, started_at=datetime.now(UTC),
        status=RunStatus.SUCCESS, model="sonnet",
        pr_url="https://github.com/user/repo/pull/42",
    )
    db.insert_run(run)
    found = db.find_run_by_pr_url("https://github.com/user/repo/pull/42")
    assert found is not None
    assert found.id == "test-run-1"


def test_store_and_get_run_variables(tmp_path):
    from agents.history import HistoryDB
    db = HistoryDB(tmp_path / "test.db")
    db.store_run_variables("run-1", {"issue_id": "abc", "team_id": "xyz"})
    got = db.get_run_variables("run-1")
    assert got == {"issue_id": "abc", "team_id": "xyz"}
