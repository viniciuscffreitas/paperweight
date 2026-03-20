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

Add a "Run" button to each task card in `hub/tasks.html` (`task_row.html` partial). Clicking it triggers the existing manual run endpoint.

### Route resolution: `project_id` → `project_name`

The hub UI operates on `project_id` (from `project_store` SQLite), but the existing run endpoint `POST /tasks/{project_name}/{task_name}/run` uses `project_name` (from YAML-loaded `state.projects`).

**Assumption**: `project_id` in `project_store` always matches the YAML project name. This is guaranteed by `migration.py` which uses `project_id = config.name` as the key. The `task.name` from `project_store.list_tasks()` matches the YAML task key for the same reason.

Therefore the Run button can POST directly to `/tasks/{project_id}/{task.name}/run` — they are the same value.

### UI behavior

- Button appears on the right side of each task row, alongside the ON/OFF badge
- HTMX `hx-post="/tasks/{{ id }}/{{ task.name }}/run"` with `hx-swap="none"` — no DOM replacement
- On click: button text changes to "Queued" (disabled) for 3 seconds via JS, then reverts
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

#### `agent_sessions` table (in `HistoryDB` — same `agents.db`)

```sql
CREATE TABLE IF NOT EXISTS agent_sessions (
    id TEXT PRIMARY KEY,              -- UUID
    project TEXT NOT NULL,            -- project name (matches YAML config key)
    worktree_path TEXT NOT NULL,      -- /tmp/agents/session-<id>
    claude_session_id TEXT,           -- captured from Claude CLI stream-json output
    model TEXT NOT NULL DEFAULT 'claude-sonnet-4-6',
    max_cost_usd REAL NOT NULL DEFAULT 2.00,
    status TEXT NOT NULL DEFAULT 'active',  -- active | closed
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
```

The table is created in `HistoryDB._init_db()` alongside the existing `runs`, `run_events`, `file_claims` tables.

#### `RunRecord` changes

Add optional `session_id` field:

```python
class RunRecord(BaseModel):
    # ... existing fields ...
    session_id: str | None = None  # links to agent_sessions.id
```

`HistoryDB._init_db()` adds: `ALTER TABLE runs ADD COLUMN session_id TEXT` (idempotent via try/except).

#### `TriggerType` enum

Add `AGENT = "agent"` to distinguish ad-hoc agent runs from one-shot manual triggers:

```python
class TriggerType(StrEnum):
    SCHEDULE = "schedule"
    GITHUB = "github"
    LINEAR = "linear"
    MANUAL = "manual"
    AGENT = "agent"
```

### Backend

#### New endpoint: `POST /api/projects/{project_name}/agent`

Uses `project_name` to look up `ProjectConfig` from `state.projects` directly (avoids `project_store` indirection). The hub frontend passes `project_id` which equals `project_name` per the migration invariant.

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

#### `run_adhoc()` — standalone method on Executor

This is a **standalone method**, NOT a wrapper around `run_task()`. Key differences from `run_task()`:

1. **No `--no-session-persistence`**: omitted to enable `--resume`
2. **Worktree lifecycle**: NOT cleaned up on run completion — only on session close
3. **`--resume` flag**: passed when continuing an existing session
4. **No task config**: uses an ad-hoc prompt string, not a `TaskConfig`
5. **Session linking**: creates `RunRecord` with `session_id` and `trigger_type="agent"`

```python
async def run_adhoc(
    self,
    project: ProjectConfig,
    prompt: str,
    session: AgentSession,
    is_resume: bool = False,
) -> RunRecord:
    # 1. Build run_id and RunRecord (trigger_type=AGENT, session_id=session.id)
    # 2. Budget check
    # 3. If not is_resume: create worktree from project.base_branch
    #    If is_resume: validate worktree exists
    # 4. Build claude command:
    #    - claude -p <prompt> --model <model> --max-budget-usd <cost>
    #    - --output-format stream-json --verbose --permission-mode auto
    #    - If is_resume: add --resume <session.claude_session_id>
    #    - NO --no-session-persistence
    # 5. Run via _run_claude() (reuses existing streaming infra)
    # 6. Extract session_id from result (see Session ID capture)
    # 7. Update session.claude_session_id and session.updated_at
    # 8. Do NOT clean up worktree (session manages lifecycle)
    # 9. Return RunRecord
```

#### Session ID capture

The `stream-json` `result` event from Claude CLI contains session metadata. Current fields parsed in `extract_result_from_line()`: `result`, `is_error`, `total_cost_usd`, `num_turns`.

**Spike required**: Before implementation, run a sample `claude -p` WITHOUT `--no-session-persistence` and capture the raw `result` event JSON to identify the exact field name for session ID (likely `session_id` or `conversation_id`). Update `extract_result_from_line()` to extract this field.

The `ClaudeOutput` model gets a new field:
```python
class ClaudeOutput(BaseModel):
    result: str = ""
    is_error: bool = False
    cost_usd: float = 0.0
    num_turns: int = 0
    session_id: str = ""  # NEW: captured from result event
```

#### Session manager

New class `SessionManager` in `src/agents/session_manager.py` — receives the same `db_path` as `HistoryDB`:

```python
class SessionManager:
    def __init__(self, db_path: Path) -> None: ...
    def create_session(self, project: str, model: str, max_cost_usd: float) -> AgentSession: ...
    def get_session(self, session_id: str) -> AgentSession | None: ...
    def update_session(self, session_id: str, **kwargs) -> None: ...
    def close_session(self, session_id: str) -> None: ...
    def get_active_session(self, project: str) -> AgentSession | None: ...
    def cleanup_stale_sessions(self, timeout_minutes: int = 30) -> int: ...
    def list_sessions(self, project: str) -> list[AgentSession]: ...
```

#### Concurrency guard

`SessionManager` maintains an in-memory `_running: set[str]` of session IDs with active runs. Before launching a run in `run_adhoc()`:

1. Check `session_id in _running` → if yes, return 409
2. Add `session_id` to `_running`
3. In finally block: remove `session_id` from `_running`

This prevents race conditions from near-simultaneous prompts.

#### Stale session cleanup

Register a scheduler job in `main.py` lifespan (alongside existing `cleanup_old_events`):

```python
scheduler.add_job(
    cleanup_sessions,
    "interval",
    minutes=10,
    id="session_cleanup",
)
```

Where `cleanup_sessions()` calls `session_manager.cleanup_stale_sessions(30)` which:
1. Finds sessions where `status='active'` and `updated_at < now - 30min`
2. Removes their worktrees via `git worktree remove`
3. Sets `status='closed'`

#### Worktree path pattern

Agent session worktrees use the path: `/tmp/agents/session-<session_id>`

This deliberately differs from the run-based pattern (`/tmp/agents/<run_id>`) used by `run_task()` to avoid any collision. The key behavioral difference: `run_task()` cleans up worktree in its `finally` block; `run_adhoc()` does NOT — worktree cleanup is exclusively handled by `close_session()` or `cleanup_stale_sessions()`.

### Frontend

#### Tab bar

Modify the `tab_bar` macro in `components/macros.html` to include `'agent'`:

```python
{%- for t in ['activity', 'tasks', 'runs', 'agent'] -%}
```

New HTMX endpoint: `GET /hub/{project_id}/agent` in `dashboard_html.py`.

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
- Font: `Ubuntu Mono` (loaded via Google Fonts in `base.html`)
- Background: `var(--bg-chrome)` for status bar, `#0a0c14` for terminal area
- Tool call colors: Read/Grep/Glob = `#a78bfa` (purple), Edit/Write = `#22c55e` (green), Bash = `#f59e0b` (amber)
- Diff: red `#f85149` for removals, green `#3fb950` for additions
- User prompt label: `var(--text-muted)`
- Agent label: `var(--accent)` (blue)

#### User prompt rendering

User prompts are rendered **client-side** when the user submits — NOT from WebSocket events. When the user types a prompt and hits Enter:

1. JavaScript immediately appends a "you" block to the terminal output
2. Sends POST to `/api/projects/{project}/agent`
3. Connects to WebSocket `/ws/runs/{run_id}` from the response
4. Agent events stream in below the user prompt

This avoids needing a new `StreamEventType` for user messages.

#### Streaming

Reuses existing WebSocket infrastructure:
1. Frontend connects to `/ws/runs/{run_id}` after submitting prompt
2. `StreamEvent` messages arrive with `type` field: `assistant`, `tool_use`, `tool_result`, `result`
3. JavaScript renderer maps event types to terminal blocks:
   - `assistant` → plain text with agent label
   - `tool_use` → collapsible block with tool name + args
   - `tool_result` → content inside parent tool block (expand on click)
   - `result` → run complete indicator (cost, turns)
   - `task_started` → status update in status bar
   - `task_completed` → "Done" indicator + PR link
   - `task_failed` → error message in red

#### Session state in UI

- **No session**: prompt input shows placeholder "Start a new session...", model/budget selectors visible
- **Active session, idle**: prompt input enabled, "End session" button visible, previous output visible
- **Active session, running**: input disabled, streaming active, blinking cursor
- **Session closed**: output preserved, "New session" button appears

#### Controls

- **Model selector**: dropdown in status bar (haiku / sonnet / opus), defaults to sonnet
- **Budget**: small input in status bar, defaults to $2.00
- **End session**: ghost button in status bar, closes session + cleans worktree
- **New session**: appears after ending, or when no active session exists

### Error handling

- **Session not found (404)**: frontend shows "Session expired" message, prompts new session
- **Worktree missing**: close session, return error, frontend prompts new session
- **Budget exceeded**: run fails with budget error message, session stays open
- **Claude timeout**: run marked as timeout, session stays open for retry
- **Concurrent runs in same session (409)**: frontend shows "A run is already in progress", input stays disabled
- **Project not found (404)**: project missing from `state.projects`, return error

### Security

- No authentication currently (dashboard is internal/VPS)
- Session cleanup prevents worktree accumulation
- Budget limits apply per-run as usual
- `--permission-mode auto` allows Claude to operate autonomously

## Scope boundaries

**In scope:**
- Run button on task cards
- Agent tab with terminal UI
- Session management (create, resume, close, cleanup)
- Streaming rendering of tool calls
- Worktree reuse within sessions
- Stale session cleanup via scheduler

**Out of scope:**
- Authentication / multi-user sessions
- Session history browser (past closed sessions)
- File tree / workspace viewer in the tab
- Agent-to-agent coordination for ad-hoc sessions
- Mobile-optimized agent tab layout
- PR creation from agent tab (uses standard executor PR flow)
