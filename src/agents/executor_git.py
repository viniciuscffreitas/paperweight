"""Git / GitHub helpers for the Executor — PR creation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from agents.pr_body_builder import build_pr_body

if TYPE_CHECKING:
    from agents.models import ProjectConfig

logger = logging.getLogger(__name__)


async def create_pr(
    run_cmd_fn: Callable,
    cwd: str,
    project: ProjectConfig,
    task_name: str,
    branch: str,
    autonomy: str,
    variables: dict[str, str] | None = None,
    cost_usd: float = 0.0,
) -> str | None:
    """Create a GitHub PR for the agent's branch.

    Returns the PR URL, or None if there are no commits to push.
    """
    log_output = await run_cmd_fn(
        ["git", "log", f"{project.base_branch}..HEAD", "--oneline"],
        cwd=cwd,
    )
    if not log_output.strip():
        return None

    diff_stat = await run_cmd_fn(
        ["git", "diff", "--stat", f"{project.base_branch}..HEAD"],
        cwd=cwd,
    )

    body = build_pr_body(
        project_name=project.name,
        task_name=task_name,
        variables=variables or {},
        diff_stat=diff_stat.strip(),
        commit_log=log_output.strip(),
        cost_usd=cost_usd,
    )

    await run_cmd_fn(["git", "push", "-u", "origin", branch], cwd=cwd)
    pr_cmd = [
        "gh",
        "pr",
        "create",
        "--title",
        f"[agents] {project.name}/{task_name}",
        "--body",
        body,
        "--base",
        project.base_branch,
    ]
    pr_output = await run_cmd_fn(pr_cmd, cwd=cwd)
    pr_url = pr_output.strip()
    if autonomy == "auto-merge":
        try:
            await run_cmd_fn(
                ["gh", "pr", "merge", "--auto", "--squash", pr_url],
                cwd=cwd,
            )
        except RuntimeError:
            logger.warning("Failed to enable auto-merge for %s", pr_url)
    return pr_url
