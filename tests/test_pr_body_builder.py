from agents.pr_body_builder import build_pr_body


def test_pr_body_with_issue():
    body = build_pr_body(
        project_name="paperweight",
        task_name="issue-resolver",
        variables={
            "issue_identifier": "PW-42",
            "issue_title": "Add retry logic",
            "issue_description": "When a task fails, it should retry up to 3 times.",
        },
        diff_stat="3 files changed, 45 insertions(+), 12 deletions(-)",
        commit_log="abc1234 feat: add retry logic\ndef5678 test: add retry tests",
        cost_usd=0.85,
    )
    assert "PW-42" in body
    assert "Add retry logic" in body
    assert "3 files changed" in body
    assert "$0.85" in body


def test_pr_body_without_issue():
    body = build_pr_body(
        project_name="paperweight",
        task_name="dep-update",
        variables={},
        diff_stat="1 file changed",
        commit_log="abc dep update",
        cost_usd=0.30,
    )
    assert "dep-update" in body
    assert "1 file changed" in body
    assert "PW-" not in body
