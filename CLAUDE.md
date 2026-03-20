# Paperweight — Agent Instructions

## Creating Tasks

When the user asks you to create a task, use the paperweight REST API:

```bash
curl -s -X POST http://localhost:8080/api/work-items \
  -H "Content-Type: application/json" \
  -d '{"project": "paperweight", "title": "TITLE", "description": "DESC", "source": "agent"}'
```

This creates a work item in the database that appears in the UI task list.

**Do NOT modify `projects/*.yaml` to create tasks.** Those files define task TEMPLATES (automated triggers), not individual work items.

## Project Context

- **paperweight** is a Background Agent Runner for Claude Code
- Stack: Python 3.13, FastAPI, Jinja2, HTMX, SQLite, APScheduler
- You are running inside paperweight as an agent session in a git worktree
- The UI uses a bold-minimal design system with L-chrome layout

## Key API Endpoints

- `POST /api/work-items` — create a task (work item)
- `GET /api/work-items` — list tasks
- `PATCH /api/work-items/{id}` — update task status/session
- `POST /api/work-items/{id}/rerun` — re-run a task
- `GET /api/sessions/{id}/events` — get session conversation history
