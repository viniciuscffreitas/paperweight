import hashlib
import hmac

from agents.models import TaskConfig


def verify_linear_signature(body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def match_linear_event(event_type: str, action: str, payload: dict, task: TaskConfig) -> bool:
    if task.trigger is None or task.trigger.type != "linear":
        return False
    event_key = f"{event_type}.{action}"
    if event_key not in task.trigger.events:
        return False
    for filter_key, filter_value in task.trigger.filter.items():
        if str(payload.get(filter_key, "")) != filter_value:
            return False
    return True


def extract_linear_variables(payload: dict) -> dict[str, str]:
    data = payload.get("data", {})
    assignee = data.get("assignee", {})
    state = data.get("state", {})
    return {
        "issue_id": data.get("id", ""),
        "issue_title": data.get("title", ""),
        "issue_description": data.get("description", ""),
        "assignee": assignee.get("name", "") if isinstance(assignee, dict) else "",
        "status": state.get("name", "") if isinstance(state, dict) else "",
    }
