# Agent Tab + Run Button — Design Spec

**Date**: 2026-03-19
**Status**: Approved
**Type**: Feature

## Problem

Paperweight has no interactive way to give ad-hoc instructions to an agent from the dashboard. Tasks must be pre-configured in YAML, triggered via Linear webhooks, or scheduled via cron. For dogfooding (paperweight building itself), users need a fast, interactive way to instruct the agent — like Claude Code CLI, but in the browser.

Additionally, pre-configured tasks in the TASKS tab have no run button — the only way to trigger them manually is via curl/API.

## Solution

Two features:

1. **Run button on task cards** — trigger pre-configured tasks from the UI
2. **Agent tab** — terminal-like interface for ad-hoc prompts with session continuity

## Feature 1: Run Button on Task Cards

### What changes

Add a "Run" button to each task card in `hub/tasks.html` (`task_row.html` partial). Clicking it POSTs to the existing `/tasks/{project}/{task}/run` endpoint via HTMX.

### UI behavior

- Button appears on the right side of each task row (where the ON/OFF badge is)
- HTMX `hx-post` with `hx-swap="none"` — no DOM replacement
- On click: button text changes to "Queued" (disabled) for 3 seconds, then reverts
- The run appears in the RUNS tab

### Backend

No changes needed — `POST /tasks/{project_name}/{task_name}/run` already exists in `main.py`.

## Feature 2: Agent Tab

### Mental model

A session in the Agent tab is a continuous conversation with Claude Code working in a single worktree — identical to opening Claude Code CLI in a directory and giving sequential instructions.

```
Session = worktree + Claude Code conversation
├── prompt 1 → new session (fresh worktree + claude -p)
├── prompt 2 → continue (same worktree + claude -p --resume)
├── prompt 3 → continue (same worktree + claude -p --resume)
└── close → cleanup worktree, mark session closed
```

### Session lifecycle

1. **Start**: User types first prompt → system creates git worktree, runs `claude -p` WITHOUT `--no-session-persistence`, captures `session_id` from output
2. **Continue**: User types follow-up → system runs `claude -p --resume <session_id>` in SAME worktree. Claude has full conversation history.
3. **End**: Session closes when:
   - User clicks "End session" explicitly
   - Inactivity timeout (30 minutes)
   - PR is created (session goal achieved)
4. **Cleanup**: Worktree is removed via `git worktree remove`

### Data model

New SQLite table `agent_sessions`:

```sql
CREATE TABLE agent_sessions (
    id TEXT PRIMARY KEY,              -- UUID
    project TEXT NOT NULL,            -- project name (matches YAML config)
    worktree_path TEXT NOT NULL,      -- /tmp/agents/session-<id>
    claude_session_id TEXT,           -- captured from Claude CLI output
    model TEXT NOT NULL DEFAULT 'claude-sonnet-4-6',
    max_cost_usd REAL NOT NULL DEFAULT 2.00,
    status TEXT NOT NULL DEFAULT 'active',  -- active | closed
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
```

Each run within a session is a normal `RunRecord` with a new optional `session_id` field linking it back.

### Backend

#### New endpoint: `POST /api/projects/{project_name}/agent`

Request body:
```json
{
    "prompt": "Fix the flaky test in test_coordination_models.py",
    "session_id": null,
    "model": "claude-sonnet-4-6",
    "max_cost_usd": 2.00
}
```

- `session_id = null` → create new session (new worktree, new Claude invocation)
- `session_id = "<uuid>"` → resume session (reuse worktree, `--resume`)

Response:
```json
{
    "run_id": "paperweight-agent-20260319-...",
    "session_id": "abc-123",
    "status": "running"
}
```

#### Executor changes

New method `run_adhoc()` on the Executor class:

1. If new session:
   - Create worktree from project's base branch
   - Build claude command WITHOUT `--no-session-persistence`
   - Run and capture `session_id` from stream-json output
2. If resume:
   - Validate worktree still exists
   - Build claude command with `--resume <claude_session_id>`
   - Run in existing worktree
3. In both cases:
   - Stream events via existing `broadcast_event` → WebSocket
   - Create a `RunRecord` linked to the session
   - Update session's `updated_at` and `claude_session_id`

#### Session ID capture

The `stream-json` output format emits a final `result` message containing session metadata. The `RunStream` parser needs to extract `session_id` from this message and expose it.

#### Session manager

New class `SessionManager` (thin layer over SQLite):
- `create_session(project, model, max_cost_usd) -> AgentSession`
- `get_session(session_id) -> AgentSession | None`
- `update_session(session_id, claude_session_id?, status?) -> None`
- `close_session(session_id) -> None`
- `cleanup_stale_sessions(timeout_minutes=30) -> int` — called periodically
- `list_sessions(project) -> list[AgentSession]`

### Frontend

#### Tab bar

Add `agent` to the tab list in the `tab_bar` macro. New HTMX endpoint: `GET /hub/{project_id}/agent`.

#### Template: `hub/agent.html`

Terminal-embed layout:

```
┌─────────────────────────────────────────────┐
│ model: sonnet  budget: $2.00  cost: $0.14   │  ← status bar
├─────────────────────────────────────────────┤
│                                             │
│ you                                         │
│ Fix the flaky test in test_coordination...  │
│                                             │
│ agent                                       │
│ ▶ Read  src/agents/coordination/models.py   │  ← collapsed tool call
│ ▼ Edit  src/agents/coordination/models.py   │  ← expanded with diff
│   - last_activity: float = Field(...)       │
│   + last_activity: float = 0.0              │
│ ▶ Bash  python -m pytest ... -x -q          │
│ 15 passed in 0.23s                          │
│ █                                           │  ← blinking cursor
│                                             │
├─────────────────────────────────────────────┤
│ > instruction...                    [Enter] │  ← prompt input
└─────────────────────────────────────────────┘
```

Design tokens:
- Font: `Ubuntu Mono` (already loaded in base.html)
- Background: `var(--bg-chrome)` for status bar, darker for terminal area
- Tool call colors: Read/Grep = `#a78bfa` (purple), Edit/Write = `#22c55e` (green), Bash = `#f59e0b` (amber)
- Diff: red `#f85149` for removals, green `#3fb950` for additions
- User prompt label: `var(--text-muted)`
- Agent label: `var(--accent)` (blue)

#### Streaming

Reuses existing WebSocket infrastructure:
1. Frontend connects to `/ws/runs/{run_id}` after submitting prompt
2. `StreamEvent` messages arrive with `type` field: `assistant`, `tool_use`, `tool_result`, `result`
3. JavaScript renderer maps event types to terminal blocks:
   - `assistant` → plain text with agent label
   - `tool_use` → collapsible block with tool name + args
   - `tool_result` with file diffs → syntax-highlighted diff block
   - `result` → session complete indicator

#### Session state in UI

- Active session: prompt input enabled, "End session" button visible in status bar
- No session: prompt input shows placeholder "Start a new session...", model/budget selectors visible
- Between runs (session active, no run in progress): input enabled, previous output visible
- Run in progress: input disabled, streaming active, blinking cursor

#### Controls

- **Model selector**: dropdown in status bar (haiku / sonnet / opus), defaults to sonnet
- **Budget**: small input in status bar, defaults to $2.00
- **End session**: ghost button in status bar, closes session + cleans worktree
- **New session**: appears after ending, or when no active session exists

### Streaming event rendering

The existing `StreamEvent` model:

```python
class StreamEvent(BaseModel):
    type: str          # assistant, tool_use, tool_result, result, etc.
    content: str
    tool_name: str = ""
    file_path: str = ""
    timestamp: float
```

Frontend rendering rules:

| Event type | Rendering |
|---|---|
| `assistant` | Plain text block under "agent" label |
| `tool_use` where `tool_name` in (Read, Grep, Glob) | Collapsed block: `▶ Read path/to/file` |
| `tool_use` where `tool_name` in (Edit, Write) | Expanded block: `▼ Edit path` + diff |
| `tool_use` where `tool_name` = Bash | `▶ Bash command...` |
| `tool_result` | Content inside parent tool block (expand on click) |
| `result` | Session summary: cost, turns, PR link if any |
| `task_started` | Status update in status bar |
| `task_completed` | "Done" indicator + PR link |
| `task_failed` | Error message in red |

### Error handling

- **Session not found**: return 404, frontend shows "Session expired"
- **Worktree missing**: close session, return error, frontend prompts new session
- **Budget exceeded**: same as existing — run fails with budget error message
- **Claude timeout**: run marked as timeout, session stays open for retry
- **Concurrent runs in same session**: reject with 409 — one run at a time per session

### Security

- No authentication currently (dashboard is internal/VPS)
- Session cleanup prevents worktree accumulation
- Budget limits apply per-run as usual
- `--permission-mode auto` allows Claude to operate autonomously

## Scope boundaries

**In scope:**
- Run button on task cards
- Agent tab with terminal UI
- Session management (create, resume, close)
- Streaming rendering of tool calls
- Worktree reuse within sessions

**Out of scope:**
- Authentication / multi-user sessions
- Session history browser (past closed sessions)
- File tree / workspace viewer in the tab
- Agent-to-agent coordination for ad-hoc sessions
- Mobile-optimized agent tab layout
