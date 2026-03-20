# Paperweight — Agent Instructions

## Brainstorming Mode (DRAFT tasks)

When the prompt says "You are brainstorming" or the task is in DRAFT status:

**You are NOT allowed to implement anything.** Your ONLY job is:
1. Explore the codebase to understand context
2. Ask the user clarifying questions ONE AT A TIME
3. Propose 2-3 approaches with trade-offs
4. Present the design for user approval
5. When approved, write the spec to `docs/superpowers/specs/YYYY-MM-DD-{slug}-design.md`
6. PATCH the task status to "ready": `curl -s -X PATCH http://localhost:8080/api/work-items/{TASK_ID} -H "Content-Type: application/json" -d '{"status": "ready"}'`

**NEVER write code, create files, or edit source during brainstorming.**
**NEVER skip to implementation.** Wait for the user to click Start after the spec is approved.

## Implementation Mode (READY/RUNNING tasks)

When the prompt says "Implement the spec at" or the task is READY/RUNNING:

1. **Read the spec file** (in `docs/superpowers/specs/`)
2. **Implement fully** — RED → GREEN → REFACTOR → COMMIT
3. **Run tests**: `uv run pytest tests/ -q --tb=short`
4. **Run linter**: `uv run ruff check src/ --fix`
5. **Commit all changes** before finishing

## Time Management

You have a 30-minute timeout per run. Plan accordingly:
- Commit working code EARLY — don't wait until everything is perfect
- Use `git add -A && git commit -m "wip: partial implementation"` after each major step
- It's better to have 3 partial commits than 0 commits at timeout

## Creating Tasks

Use the REST API:
```bash
curl -s -X POST http://localhost:8080/api/work-items \
  -H "Content-Type: application/json" \
  -d '{"project": "paperweight", "title": "TITLE", "description": "DESC", "source": "agent"}'
```

**Do NOT modify `projects/*.yaml` to create tasks.**

## Project Context

- **paperweight** is a Background Agent Runner for Claude Code
- Stack: Python 3.13, FastAPI, Jinja2, HTMX, SQLite, APScheduler
- You are running inside paperweight as an agent session in a git worktree
- Specs are in `docs/superpowers/specs/`
- Tests are in `tests/` — run with `uv run pytest tests/ -q`
