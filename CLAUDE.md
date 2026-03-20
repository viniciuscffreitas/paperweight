# Paperweight — Agent Instructions

## Task Execution

When you receive a task prompt (especially one saying "Implement this spec"):

1. **Read the spec file** referenced in the prompt (it's in `docs/superpowers/specs/`)
2. **Implement fully** — do NOT stop at writing tests. Complete the full cycle:
   - RED: write failing tests
   - GREEN: implement the code to make them pass
   - REFACTOR: clean up
   - COMMIT: `git add && git commit` with descriptive message
3. **Run tests** after implementing: `uv run pytest tests/ -q --tb=short`
4. **Run linter**: `uv run ruff check src/ --fix`
5. **Commit all changes** before finishing

Do NOT just write tests and stop. The task is not done until code is implemented, tests pass, and changes are committed.

## Creating Tasks

When the user asks you to create a task, use the REST API:

```bash
curl -s -X POST http://localhost:8080/api/work-items \
  -H "Content-Type: application/json" \
  -d '{"project": "paperweight", "title": "TITLE", "description": "DESC", "source": "agent"}'
```

**Do NOT modify `projects/*.yaml` to create tasks.** Those files define task TEMPLATES, not individual work items.

## Project Context

- **paperweight** is a Background Agent Runner for Claude Code
- Stack: Python 3.13, FastAPI, Jinja2, HTMX, SQLite, APScheduler
- You are running inside paperweight as an agent session in a git worktree
- The UI uses a bold-minimal design system with L-chrome layout
- Specs are in `docs/superpowers/specs/` — READ them before implementing
- Tests are in `tests/` — run with `uv run pytest tests/ -q`

## Key API Endpoints

- `POST /api/work-items` — create a task (work item)
- `PATCH /api/work-items/{id}` — update task status/session
- `POST /api/projects/{name}/agent` — trigger agent with prompt
- `GET /api/sessions/{id}/events` — get session conversation history
