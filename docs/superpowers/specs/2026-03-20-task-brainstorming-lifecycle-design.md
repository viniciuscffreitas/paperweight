# Task Brainstorming Lifecycle — Design Spec

**Date:** 2026-03-20
**Status:** Approved

## Goal

Every task starts with a brainstorming phase where the agent explores the codebase, asks questions, and produces a spec before any implementation begins.

## Task States

```
draft → ready → running → done/failed
```

- **draft**: brainstorming active, agent exploring and producing spec
- **ready**: spec approved and saved, Start button enabled
- **running**: agent implementing from spec
- **done/failed**: terminal states

## Flow

1. User clicks "+ New Task" → modal with title/idea field
2. Task created with status `draft`
3. Redirect to task detail, CHAT tab active
4. Agent auto-starts brainstorming (no user message needed)
5. Agent explores codebase, asks questions, proposes approaches
6. When user approves design, agent writes spec .md and PATCHes task to `ready`
7. Task title updated dynamically from conversation
8. User sees SPEC tab with full spec, clicks Start
9. Agent receives spec, does plan → TDD → verify → commit

## Backend Changes

### TaskStatus enum
Add `READY = "ready"` between DRAFT and PENDING.

### New Task creation (POST /api/work-items)
When `status=draft`, auto-dispatch agent session with brainstorming prompt.

### Brainstorming prompt template
```
You are brainstorming a new feature. The user's idea:

"{title}"

Follow this workflow:
1. Read CLAUDE.md for project instructions
2. Explore the codebase (src/, tests/, docs/) to understand context
3. Ask the user clarifying questions ONE AT A TIME
4. Propose 2-3 approaches with trade-offs
5. Present the design section by section
6. When the user approves, write the spec to docs/superpowers/specs/

After writing the spec file, update the task:
curl -s -X PATCH http://localhost:8080/api/work-items/{task_id} \
  -H "Content-Type: application/json" \
  -d '{{"status": "ready"}}'

Update the task title if a better name emerges:
curl -s -X PATCH http://localhost:8080/api/work-items/{task_id} \
  -H "Content-Type: application/json" \
  -d '{{"title": "Better Title"}}'

Do NOT implement anything. Only brainstorm and produce the spec.
```

## Frontend Changes

### Modal "+ New Task"
- Single field: title/idea
- On submit: POST /api/work-items with status=draft
- Redirect to /hub/{project}/task/{id} (chat tab)

### Task detail states

**draft:**
- Badge: "DRAFT" (yellow/warning color)
- Default tab: CHAT
- No Start button
- Agent auto-starts (initTaskDetail detects draft + no session → triggers agent)

**ready:**
- Badge: "READY" (blue/accent color)
- Default tab: SPEC
- Start button visible
- Start sends spec as prompt (existing behavior)

**running/done/failed:**
- No changes from current behavior

### Status colors
- draft: `--status-warning` (amber)
- ready: `--accent-text` (indigo)
- pending: `--status-queued` (grey) — kept for backward compat
- running/done/failed: unchanged

## What Does NOT Change

- Backend API structure (just add READY status)
- WebSocket streaming
- Executor/session management
- Spec finder (_find_related_docs)
- Chat rendering (chat.js)
- Activity feed
