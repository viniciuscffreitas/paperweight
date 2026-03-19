"""MediatorSpawner — builds mediator prompts and coordinates mediation runs."""
from __future__ import annotations

COORDINATION_PREAMBLE = """## Coordinated Mode — Paperweight Protocol

You are running alongside other AI agents on the same repository. Each agent has
an isolated git worktree, but you share the same codebase.

### MANDATORY — Before editing ANY file:
1. Read `/.paperweight/state.json` to check `claims`
2. If the file is claimed by another agent: DO NOT edit it
3. Instead, append to `/.paperweight/inbox.jsonl`:
   {"type":"need_file","file":"<path>","intent":"<what you need to do>"}
4. Continue with OTHER files. Check `/.paperweight/outbox.jsonl` periodically.

### After editing a file:
Append to `/.paperweight/inbox.jsonl`:
{"type":"edit_complete","file":"<path>"}

### After each major step, read `/.paperweight/outbox.jsonl`:
- `file_mediated`: A mediator handled this file. SKIP it entirely.
- `file_released`: File available. You may edit it now.

### Heartbeat:
Every ~10 tool calls, append to inbox.jsonl: {"type":"heartbeat"}

### Rules:
- NEVER force-edit a claimed file
- If ALL your files are claimed, work on tests, docs, or config
- The orchestrator resolves conflicts automatically
"""


def build_coordination_preamble() -> str:
    return COORDINATION_PREAMBLE


def build_mediator_prompt(
    file_path: str,
    file_content: str,
    intent_a: str,
    intent_b: str,
    task_a_description: str,
    task_b_description: str,
    diff_a: str = "",
) -> str:
    diff_section = ""
    if diff_a:
        diff_section = f"\nChanges Agent A already made (diff):\n```\n{diff_a}\n```\n"

    basename = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path

    return f"""## Mediation Task

Two agents need changes to the same file. Apply BOTH changes coherently.

### Agent A — "{task_a_description}"
What Agent A needs in {file_path}: "{intent_a}"
{diff_section}
### Agent B — "{task_b_description}"
What Agent B needs in {file_path}: "{intent_b}"

### Current file ({file_path}):
```
{file_content}
```

### Instructions:
1. Understand what BOTH agents need for this file
2. Apply both changes coherently — they should work together
3. If the changes are incompatible, apply the most critical one and document the other as a TODO
4. Write tests if the file has associated test files
5. Commit: "mediation({basename}): <summary>"
6. Touch ONLY the contested file(s) — nothing else
"""
