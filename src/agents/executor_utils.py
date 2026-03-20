"""Utility helpers for the Executor: ID generation, output parsing, progress logs."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel


class ClaudeOutput(BaseModel):
    result: str = ""
    is_error: bool = False
    cost_usd: float = 0.0
    num_turns: int = 0
    session_id: str = ""


def generate_run_id(project: str, task: str, issue_id: str = "") -> str:
    short_uuid = uuid.uuid4().hex[:8]
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    parts = [project, task]
    if issue_id:
        parts.append(issue_id)
    parts.extend([timestamp, short_uuid])
    return "-".join(parts)


def generate_branch_name(prefix: str, task: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{prefix}{task}-{timestamp}"


def parse_claude_output(raw: str) -> ClaudeOutput:
    try:
        data = json.loads(raw)
        return ClaudeOutput(
            result=data.get("result", ""),
            is_error=data.get("is_error", False),
            cost_usd=data.get("total_cost_usd", 0.0),
            num_turns=data.get("num_turns", 0),
        )
    except (json.JSONDecodeError, KeyError):
        return ClaudeOutput(result=raw, is_error=True)


def write_progress_log(
    progress_dir: Path,
    issue_id: str,
    attempt: int,
    issue_title: str = "",
    issue_description: str = "",
) -> Path:
    progress_dir.mkdir(parents=True, exist_ok=True)
    path = progress_dir / f"{issue_id}.txt"
    path.write_text(
        f"# Progress Log — {issue_id}\n\n"
        f"## Issue: {issue_title}\n{issue_description}\n\n"
        f"## Attempt {attempt}\nStarting...\n"
    )
    return path


def append_progress_log(progress_dir: Path, issue_id: str, attempt: int, error: str = "") -> None:
    path = progress_dir / f"{issue_id}.txt"
    if path.exists():
        with path.open("a") as f:
            f.write(f"\n### Attempt {attempt} — FAILED\nError: {error}\n")


def delete_progress_log(progress_dir: Path, issue_id: str) -> None:
    path = progress_dir / f"{issue_id}.txt"
    if path.exists():
        path.unlink()
