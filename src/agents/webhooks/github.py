import hashlib
import hmac

from agents.models import TaskConfig


def verify_github_signature(body: bytes, signature: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def match_github_event(
    event_type: str, action: str | None, payload: dict, task: TaskConfig
) -> bool:
    if task.trigger is None or task.trigger.type != "github":
        return False
    event_key = f"{event_type}.{action}" if action else event_type
    if event_key not in task.trigger.events and event_type not in task.trigger.events:
        return False
    for filter_key, filter_value in task.trigger.filter.items():
        if str(payload.get(filter_key, "")) != filter_value:
            return False
    return True


def is_agent_pr_merge(payload: dict) -> bool:
    if payload.get("action") != "closed":
        return False
    pr = payload.get("pull_request", {})
    if not pr.get("merged"):
        return False
    return pr.get("title", "").startswith("[agents]")


def extract_pr_merge_info(payload: dict) -> dict[str, str]:
    pr = payload.get("pull_request", {})
    return {
        "pr_url": pr.get("html_url", ""),
        "branch": pr.get("head", {}).get("ref", ""),
        "title": pr.get("title", ""),
        "body": pr.get("body", ""),
    }


def extract_github_variables(event_type: str, payload: dict) -> dict[str, str]:
    variables: dict[str, str] = {}
    repo = payload.get("repository", {})
    variables["repo_full_name"] = repo.get("full_name", "")
    if event_type == "check_suite":
        suite = payload.get("check_suite", {})
        variables["branch"] = suite.get("head_branch", "")
        variables["sha"] = suite.get("head_sha", "")
        variables["conclusion"] = suite.get("conclusion", "")
    elif event_type == "pull_request":
        pr = payload.get("pull_request", {})
        variables["branch"] = pr.get("head", {}).get("ref", "")
        variables["pr_number"] = str(pr.get("number", ""))
        variables["pr_title"] = pr.get("title", "")
        variables["pr_url"] = pr.get("html_url", "")
    elif event_type == "issues":
        issue = payload.get("issue", {})
        variables["issue_number"] = str(issue.get("number", ""))
        variables["issue_title"] = issue.get("title", "")
        variables["issue_body"] = issue.get("body", "")
    return variables
