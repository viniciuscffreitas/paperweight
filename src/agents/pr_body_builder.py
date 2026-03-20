"""Build rich PR descriptions for agent-created pull requests."""


def build_pr_body(
    project_name: str,
    task_name: str,
    variables: dict[str, str],
    diff_stat: str = "",
    commit_log: str = "",
    cost_usd: float = 0.0,
) -> str:
    sections: list[str] = []
    identifier = variables.get("issue_identifier", "")
    title = variables.get("issue_title", "")
    description = variables.get("issue_description", "")
    if identifier:
        sections.append(f"## Issue: {identifier} — {title}")
        if description:
            desc = description[:500] + ("..." if len(description) > 500 else "")
            sections.append(f"\n{desc}")
    if diff_stat:
        sections.append(f"\n## Changes\n```\n{diff_stat}\n```")
    if commit_log:
        sections.append(f"\n## Commits\n```\n{commit_log}\n```")
    meta = f"\n---\n🤖 Automated by Paperweight | Task: `{task_name}` | Project: `{project_name}` | Cost: ${cost_usd:.2f}"
    sections.append(meta)
    return "\n".join(sections)
