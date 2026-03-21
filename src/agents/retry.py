"""Retry policy for failed task executions."""
from pydantic import BaseModel


class RetryPolicy(BaseModel):
    max_retries: int = 3
    base_delay_seconds: int = 30
    max_delay_seconds: int = 300

    def delay_for_attempt(self, attempt: int) -> int:
        delay = self.base_delay_seconds * (2 ** (attempt - 1))
        return min(delay, self.max_delay_seconds)

    def can_retry(self, attempt: int) -> bool:
        return attempt <= self.max_retries


_RETRYABLE_PATTERNS = [
    "timed out", "timeout", "rate_limit", "worktree add",
    "connection", "temporary", "503", "502", "eagain",
]
_PERMANENT_PATTERNS = [
    "budget exceeded", "project not found", "task not found",
    "invalid signature", "authentication",
]


def should_retry_error(error_message: str) -> bool:
    if not error_message:
        return False
    lower = error_message.lower()
    if any(p in lower for p in _PERMANENT_PATTERNS):
        return False
    return any(p in lower for p in _RETRYABLE_PATTERNS)
