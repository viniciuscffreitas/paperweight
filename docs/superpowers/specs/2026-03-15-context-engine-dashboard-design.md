# Context Engine + Dashboard — Design Spec

## Problem

The Background Agent Runner (Phase 1) works but is "blind" — it dispatches static prompts from YAML without gathering context from the tools and services the developer already uses. There's also no visibility into what an agent is doing during execution, and no visual interface for monitoring.

## Vision

Evolve the Runner into a **Context Engine** with a **live Dashboard**:
- **Intent + context hints** replace static prompts — the agent is guided to gather context via MCP servers it already has access to (Sentry, Linear, Figma, GitHub, etc.)
- **Streaming execution** shows what the agent is doing in real-time
- **NiceGUI dashboard** provides visual monitoring, manual triggers, and run history
- **Multi-project configs** cover all developer projects, not just one

## Architecture

```
EVENTO (GitHub/Linear/Cron/Manual)
    │
    ▼
┌──────────────┐
│ Event Router │  (existing webhooks + scheduler)
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Prompt       │  intent + context_hints + event_data
│ Builder      │  (new build_prompt, keeps render_prompt as internal helper)
└──────┬───────┘
       │
       ▼
┌──────────────┐     ┌──────────────┐
│ Streaming    │────▶│ Dashboard    │  NiceGUI (live stream)
│ Executor     │     │ (WebSocket)  │
│              │     └──────────────┘
│ claude -p    │
│ stream-json  │────▶ Slack notification
│ worktree     │────▶ History (SQLite)
└──────────────┘────▶ PR / merge
```

**Core principle:** The Claude session is the Context Assembler. It already has MCP servers (Sentry, Linear, Figma, etc.) configured. The Runner provides the intent and hints about where to look — Claude does the deep work.

## What Changes vs. What Stays

**Untouched (6 files):**
- `history.py` — SQLite CRUD
- `budget.py` — cost tracking
- `notifier.py` — Slack notifications
- `scheduler.py` — APScheduler cron
- `webhooks/github.py` — event matching + HMAC
- `webhooks/linear.py` — event matching

**Evolves (4 files, surgical changes):**
- `models.py` — TaskConfig gets `intent` + `context_hints`
- `config.py` — new `build_prompt()`, `render_prompt()` kept as internal helper
- `executor.py` — stream-json + on_event callback
- `main.py` — WebSocket endpoints + NiceGUI integration

**New (2 files):**
- `streaming.py` — parses stream-json lines, emits typed events
- `dashboard.py` — NiceGUI UI integrated with FastAPI

## Component 1: Intent Model

### TaskConfig Evolution

```python
class TaskConfig(BaseModel):
    description: str
    intent: str = ""                      # What the agent should do
    context_hints: list[str] = []         # Hints for MCP-based context gathering
    prompt: str | None = None             # Backwards compat — used as intent if intent is empty
    schedule: str | None = None
    trigger: TriggerConfig | None = None
    model: str = "sonnet"
    max_cost_usd: float = 5.00
    autonomy: str = "pr-only"

    @model_validator(mode="after")
    def validate_has_intent_or_prompt(self) -> "TaskConfig":
        if not self.intent and not self.prompt:
            msg = "Either intent or prompt must be non-empty"
            raise ValueError(msg)
        return self
```

**Backwards compatibility details:**
- `prompt` changes from `str` (required) to `str | None = None` (optional)
- Existing YAML configs with `prompt: "..."` still work — `prompt` gets the value, `intent` stays `""`
- Existing tests that pass `prompt="..."` still work — the validator accepts either being non-empty
- The `validate_schedule_or_trigger` validator remains unchanged
- All 56 existing tests continue passing without modification

### Prompt Builder

New function `build_prompt()` in `config.py`. The existing `render_prompt()` is **kept as an internal helper** (not removed) because it's used by existing code and tests.

```python
def build_prompt(task: TaskConfig, variables: dict[str, str]) -> str:
    """Build a complete prompt from intent/prompt + variables + context hints."""
    raw_intent = task.intent or task.prompt or ""

    # Apply {{variable}} substitution (uses existing render_prompt)
    intent = render_prompt(raw_intent, variables)

    parts = [intent]

    if variables:
        parts.append("\n## Event Data")
        for key, value in variables.items():
            if value:
                parts.append(f"- {key}: {value}")

    if task.context_hints:
        parts.append("\n## Before starting, gather context:")
        for hint in task.context_hints:
            parts.append(f"- {hint}")

    return "\n".join(parts)
```

**What changes in executor.py:** Line 117 changes from `render_prompt(task.prompt, ...)` to `build_prompt(task, ...)`. The import changes but `render_prompt` is not removed from `config.py`.

### YAML Format

```yaml
tasks:
  ci-fix:
    intent: "Investigue e corrija o CI failure neste projeto."
    context_hints:
      - "Use o Sentry MCP pra buscar erros recentes neste projeto"
      - "Verifique issues abertas no Linear relacionadas a bugs"
      - "Analise o git log dos últimos commits pra entender o que mudou"
    trigger:
      type: github
      events: [check_suite.completed]
      filter: { conclusion: failure }
    model: sonnet
    max_cost_usd: 3.00
    autonomy: pr-only
```

## Component 2: Streaming Executor

### Stream-JSON Format Discovery

**IMPORTANT:** The exact `stream-json` event format from Claude Code CLI is not fully documented and may vary between versions. The `_parse_line()` implementation MUST be built empirically by capturing real output:

```bash
claude -p "Say hello" --output-format stream-json 2>/dev/null
```

The first implementation task must capture real stream-json output and build the parser against actual event shapes. The event types described below are based on observed patterns but must be verified:

- `{"type": "system", ...}` — session init
- `{"type": "assistant", "message": {...}}` — agent text
- Tool use events (format TBD — may use `content_block_start`/`content_block_delta` pattern)
- `{"type": "result", "total_cost_usd": ..., ...}` — final result (same schema as json output)

### Stream Event Model

```python
from typing import Literal

StreamEventType = Literal["assistant", "tool_use", "tool_result", "result", "system", "unknown"]

class StreamEvent(BaseModel):
    type: StreamEventType
    content: str = ""
    tool_name: str = ""
    timestamp: float
```

### RunStream

New module `streaming.py`:

```python
class RunStream:
    def __init__(self, run_id: str, on_event: Callable, raw_lines: list[str] | None = None) -> None:
        self.run_id = run_id
        self.on_event = on_event
        # Accumulate raw lines for history file preservation
        self.raw_lines: list[str] = raw_lines if raw_lines is not None else []

    async def process_stream(self, proc: asyncio.subprocess.Process) -> ClaudeOutput:
        """Read stdout line by line, parse JSON, emit events, return final result."""
        last_result: ClaudeOutput | None = None

        async for line in proc.stdout:
            text = line.decode().strip()
            if not text:
                continue
            self.raw_lines.append(text)
            event = self._parse_line(text)
            if event:
                await self.on_event(self.run_id, event)
                if event.type == "result":
                    last_result = parse_claude_output(text)

        await proc.wait()
        return last_result or ClaudeOutput(is_error=True, result="No result received")

    def get_raw_output(self) -> str:
        """Return all accumulated lines as a single string for history storage."""
        return "\n".join(self.raw_lines)

    def _parse_line(self, line: str) -> StreamEvent | None:
        # Built empirically against real CLI output — see task 1 of implementation plan
        ...
```

**Key design decisions:**
- `raw_lines` accumulates all output lines so the full raw output can be saved to `data/runs/<id>.json` for history (fixes Issue #6 — raw output preservation)
- `_extract_result` is removed — uses existing `parse_claude_output()` from `executor.py` instead (avoids code duplication)
- The `_parse_line` implementation is deferred to implementation phase after capturing real stream-json output

### Executor Changes

In `executor.py`:

**`_run_claude` evolves** — returns `tuple[ClaudeOutput, str]` (parsed result + raw output):

```python
async def _run_claude(self, cmd: list[str], cwd: str, run_id: str, timeout: int) -> tuple[ClaudeOutput, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    self._running_processes[run_id] = proc

    stream = RunStream(run_id=run_id, on_event=self.on_stream_event)
    try:
        result = await asyncio.wait_for(stream.process_stream(proc), timeout=timeout)
        return result, stream.get_raw_output()
    except TimeoutError:
        proc.terminate()
        raise
```

**`run_task` updates** — receives tuple, saves raw output:

```python
output, raw_output = await self._run_claude(...)

# Save raw output for history
output_file = output_dir / f"{run_id}.json"
output_file.write_text(raw_output)
```

**CLI flag change:** `--output-format json` → `--output-format stream-json`

**New `__init__` parameter:**

```python
def __init__(self, ..., on_stream_event: Callable | None = None) -> None:
    ...
    self.on_stream_event = on_stream_event or self._noop_event

async def _noop_event(self, run_id: str, event: StreamEvent) -> None:
    pass
```

The `on_stream_event` default is `_noop_event`, so all existing tests pass without changes (they don't provide the callback).

### WebSocket Broadcasting

In `main.py`:

```python
class AppState:
    ...
    ws_clients: dict[str, set[WebSocket]] = {}
    ws_global_clients: set[WebSocket] = set()

async def broadcast_event(run_id: str, event: StreamEvent) -> None:
    msg = event.model_dump_json()

    # Send to run-specific subscribers — handle disconnected clients
    dead: set[WebSocket] = set()
    for ws in state.ws_clients.get(run_id, set()):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    state.ws_clients.get(run_id, set()).difference_update(dead)

    # Send to global subscribers — handle disconnected clients
    dead_global: set[WebSocket] = set()
    for ws in state.ws_global_clients:
        try:
            await ws.send_text(json.dumps({"run_id": run_id, **event.model_dump()}))
        except Exception:
            dead_global.add(ws)
    state.ws_global_clients.difference_update(dead_global)
```

**WebSocket lifecycle cleanup:** When a run completes, its entry in `ws_clients` is removed.

WebSocket endpoints:

```
WS /ws/runs/{run_id}    → events for a specific run
WS /ws/runs              → events for ALL active runs
```

## Component 3: Dashboard (NiceGUI)

### Integration Strategy

NiceGUI integrates with FastAPI via `ui.run_with(app)`.

**Known compatibility issues and mitigations:**
1. **Lifespan conflict:** NiceGUI may conflict with FastAPI's `lifespan` parameter in some versions. Mitigation: test with NiceGUI >= 2.5. If lifespan breaks, fallback to mounting NiceGUI on a sub-application (`sub_app = FastAPI(); ui.run_with(sub_app); app.mount("/dashboard", sub_app)`).
2. **app.state isolation:** NiceGUI pages cannot access `app.state.app_state`. Mitigation: `setup_dashboard()` receives `state: AppState` directly via closure — it does NOT use `app.state`. This is already reflected in the function signature.

**Dependency:** `nicegui>=2.5,<3` in `pyproject.toml` (pinned to tested range).

### Module: `dashboard.py`

```python
def setup_dashboard(app: FastAPI, state: AppState, config: GlobalConfig) -> None:
    """Mount NiceGUI dashboard. State passed via closure, NOT via app.state."""

    @ui.page("/")
    async def index():
        # All UI components access `state` directly from closure scope
        ...

    ui.run_with(app)
```

### Layout

Single page with these sections (top to bottom):

**1. Header Bar**
- Title: "Agent Runner"
- Budget progress bar: spent/limit with percentage

**2. Stats Cards (row of 4)**
- Total runs today
- Successful runs
- Failed runs
- Total cost today

**3. Live Run Panel** (only visible when a run is active)
- Run info: project/task, model, duration timer
- Stream log: scrolling text area connected to WebSocket
  - Assistant messages in normal text
  - Tool uses highlighted (tool name + truncated input)
  - Tool results in muted text

**4. Run History Table**
- Columns: Project, Task, Status, Cost, Duration, PR link
- Last 20 runs from SQLite history
- Click on a row to see full output (loads from `data/runs/<id>.json`)

**5. Manual Trigger Section**
- Project dropdown (populated from loaded configs)
- Task dropdown (updates based on selected project)
- "Run" button → POST to `/tasks/{project}/{task}/run`

**6. Scheduled Tasks**
- List of upcoming scheduled tasks with next run time

### Real-time Updates

- **Stats + history**: `ui.timer(5.0, refresh)` — polls every 5 seconds
- **Live run stream**: JavaScript WebSocket in the page connecting to `/ws/runs` — updates on every event
- **Budget bar**: updates with stats timer

### Testing

Dashboard tests are **integration tests** that verify the NiceGUI pages render and the API endpoints respond correctly. They use `httpx.AsyncClient` against the ASGI app (same pattern as `test_main.py`), NOT browser-based testing. The live WebSocket/streaming features are tested separately in `test_streaming.py`.

## Component 4: Project Configs

YAML configs for all developer projects. Created during implementation after verifying each repo's structure:

```
projects/
├── sekit.yaml          # Next.js + Rails + Python monorepo
├── fintech.yaml        # iOS + Backend
├── momease.yaml        # App + Backend + Theme Manager
├── primeleague.yaml    # Kotlin/Gradle game server
├── jarvis.yaml         # Python WhatsApp bot
└── devscout.yaml       # Tauri + Next.js + Python desktop app
```

Each config follows the intent + context_hints format. Tasks are tailored to each project's stack and common needs (dep-update, lint-fix, ci-fix at minimum).

## Updated Project Structure

```
src/agents/
├── __init__.py
├── main.py             # EVOLVES: +WebSocket endpoints, +NiceGUI mount, +broadcast_event
├── models.py           # EVOLVES: +intent, +context_hints, +validate_has_intent_or_prompt
├── config.py           # EVOLVES: +build_prompt() (render_prompt kept as helper)
├── executor.py         # EVOLVES: +stream mode, +on_stream_event, _run_claude returns tuple
├── streaming.py        # NEW: RunStream, StreamEvent, stream-json parser
├── dashboard.py        # NEW: NiceGUI dashboard UI via closure-based state access
├── scheduler.py        # unchanged
├── budget.py           # unchanged
├── notifier.py         # unchanged
├── history.py          # unchanged
└── webhooks/
    ├── __init__.py
    ├── github.py       # unchanged
    └── linear.py       # unchanged
```

## Updated Dependencies

Add to `pyproject.toml`:
```toml
"nicegui>=2.5,<3",
```

## Testing Strategy

- **Existing 56 tests continue passing** — backwards compatibility via `prompt: str | None = None` default
- **New tests for streaming.py**: parse real stream-json lines (captured during task 1), handle malformed input, verify ClaudeOutput extraction via `parse_claude_output`, verify raw line accumulation
- **New tests for build_prompt()**: intent + hints + variables assembly, backwards compat with `prompt:` only, `{{var}}` substitution in intent
- **New tests for dashboard.py**: ASGI-level tests (page returns 200, endpoints respond)
- **Updated tests for executor.py**: stream mode returns `tuple[ClaudeOutput, str]`, on_event callback invocation, noop default
- **New tests for WebSocket**: connect, receive events, handle disconnect gracefully

## Non-Goals (this iteration)

- Pre-fetching context via direct API calls (Claude uses MCP servers directly)
- Custom MCP client in the Runner
- Multi-page dashboard (single page is sufficient)
- User authentication on dashboard (single-user, local network)
- Mobile-responsive layout (desktop monitoring only)
- Browser-based dashboard testing (ASGI-level tests sufficient for MVP)
