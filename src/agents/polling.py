"""Polling fallback for missed webhooks — scans Linear for unprocessed agent issues."""

import logging

logger = logging.getLogger(__name__)

_TERMINAL_STATES = {"done", "cancelled", "canceled", "duplicate"}


def find_unprocessed_agent_issues(issues: list[dict]) -> list[dict]:
    """Filter issues that have the 'agent' label and are not in a terminal state."""
    result = []
    for issue in issues:
        labels = issue.get("labels", [])
        has_agent = any(
            label.get("name", "").lower() == "agent"
            for label in labels
            if isinstance(label, dict)
        )
        if not has_agent:
            continue
        state_name = issue.get("state", {}).get("name", "").lower()
        if state_name in _TERMINAL_STATES:
            continue
        result.append(issue)
    return result
