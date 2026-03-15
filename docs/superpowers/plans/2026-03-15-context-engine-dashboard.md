# Context Engine + Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve the Background Agent Runner into a Context Engine with live Dashboard — intent-driven prompts with context hints, streaming execution via WebSocket, and a NiceGUI visual dashboard.

**Architecture:** Surgical evolution of 4 existing files + 2 new files. The Claude CLI `stream-json` output is parsed line-by-line and broadcast via WebSocket to a NiceGUI dashboard. The YAML config evolves from static `prompt:` to `intent:` + `context_hints:` that guide Claude to gather context via its MCP servers.

**Tech Stack:** Existing stack + NiceGUI >= 2.5, WebSocket (FastAPI built-in)

**Spec:** `docs/superpowers/specs/2026-03-15-context-engine-dashboard-design.md`

**Critical discovery:** `--output-format stream-json` requires `--verbose` flag. The stream format uses these event types:
- `system.init` — session start
- `system.hook_*` — devflow hooks (ignore)
- `assistant` with `content[].type` = `thinking` | `tool_use` | `text`
- `user` with `content[].type` = `tool_result`
- `rate_limit_event` — ignore
- `result.success` / `result.error_*` — final result with `total_cost_usd`, `num_turns`

---

## Chunk 1: Model Evolution + Prompt Builder

### Task 1: Evolve TaskConfig (intent + context_hints)

**Files:**
- Modify: `src/agents/models.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write failing tests for new intent model**

Add to `tests/test_models.py`:

```python
def test_task_config_with_intent():
    from agents.models import TaskConfig

    task = TaskConfig(
        description="fix ci",
        intent="Investigate and fix CI failure",
        context_hints=["Check Sentry for recent errors"],
        schedule="0 3 * * *",
    )
    assert task.intent == "Investigate and fix CI failure"
    assert task.context_hints == ["Check Sentry for recent errors"]
    assert task.prompt is None


def test_task_config_backwards_compat_prompt_only():
    from agents.models import TaskConfig

    task = TaskConfig(
        description="test",
        prompt="do something",
        schedule="0 3 * * MON",
    )
    assert task.prompt == "do something"
    assert task.intent == ""


def test_task_config_requires_intent_or_prompt():
    from agents.models import TaskConfig

    with pytest.raises(ValueError, match="intent.*prompt"):
        TaskConfig(
            description="test",
            schedule="0 3 * * MON",
        )
```

- [ ] **Step 2: Run tests — verify new tests fail, existing tests pass**

```bash
uv run python -m pytest tests/test_models.py -v
```

Expected: 3 new tests FAIL (no `intent` field), 8 existing tests PASS.

- [ ] **Step 3: Evolve TaskConfig in models.py**

Replace the `TaskConfig` class in `src/agents/models.py`:

```python
class TaskConfig(BaseModel):
    description: str
    intent: str = ""
    context_hints: list[str] = []
    prompt: str | None = None
    schedule: str | None = None
    trigger: TriggerConfig | None = None
    model: str = "sonnet"
    max_cost_usd: float = 5.00
    autonomy: str = "pr-only"

    @model_validator(mode="after")
    def validate_schedule_or_trigger(self) -> "TaskConfig":
        if self.schedule and self.trigger:
            msg = "schedule and trigger are mutually exclusive"
            raise ValueError(msg)
        if not self.schedule and not self.trigger:
            msg = "Either schedule or trigger must be set"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def validate_has_intent_or_prompt(self) -> "TaskConfig":
        if not self.intent and not self.prompt:
            msg = "Either intent or prompt must be non-empty"
            raise ValueError(msg)
        return self
```

- [ ] **Step 4: Run ALL tests — verify all pass**

```bash
uv run python -m pytest tests/ -v
```

Expected: ALL tests pass (56 existing + 3 new = 59).

- [ ] **Step 5: Lint**

```bash
uv run ruff check src/agents/models.py tests/test_models.py && uv run ruff format src/agents/models.py tests/test_models.py
```

- [ ] **Step 6: Commit**

```bash
git add src/agents/models.py tests/test_models.py
git commit -m "feat: add intent + context_hints to TaskConfig with backwards compat"
```

---

### Task 2: Add build_prompt to config.py

**Files:**
- Modify: `src/agents/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for build_prompt**

Add to `tests/test_config.py`:

```python
def test_build_prompt_with_intent_and_hints():
    from agents.config import build_prompt
    from agents.models import TaskConfig

    task = TaskConfig(
        description="fix ci",
        intent="Investigate CI failure on branch {{branch}}",
        context_hints=["Check Sentry for errors", "Look at Linear issues"],
        schedule="0 * * * *",
    )
    result = build_prompt(task, {"branch": "main"})
    assert "Investigate CI failure on branch main" in result
    assert "## Event Data" in result
    assert "- branch: main" in result
    assert "## Before starting, gather context:" in result
    assert "- Check Sentry for errors" in result
    assert "- Look at Linear issues" in result


def test_build_prompt_backwards_compat_prompt_only():
    from agents.config import build_prompt
    from agents.models import TaskConfig

    task = TaskConfig(
        description="test",
        prompt="Run the linter and fix issues",
        schedule="0 * * * *",
    )
    result = build_prompt(task, {})
    assert "Run the linter and fix issues" in result
    assert "## Before starting" not in result


def test_build_prompt_substitutes_variables_in_intent():
    from agents.config import build_prompt
    from agents.models import TaskConfig

    task = TaskConfig(
        description="fix",
        intent="Fix CI on {{branch}} (sha: {{sha}})",
        schedule="0 * * * *",
    )
    result = build_prompt(task, {"branch": "feat/x", "sha": "abc123"})
    assert "Fix CI on feat/x (sha: abc123)" in result
```

- [ ] **Step 2: Run tests — verify new tests fail**

```bash
uv run python -m pytest tests/test_config.py -v
```

- [ ] **Step 3: Implement build_prompt**

Add to `src/agents/config.py` (after the existing `render_prompt` function):

```python
def build_prompt(task: "TaskConfig", variables: dict[str, str]) -> str:
    """Build complete prompt from intent/prompt + variables + context hints."""
    from agents.models import TaskConfig  # avoid circular import

    raw_intent = task.intent or task.prompt or ""
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

- [ ] **Step 4: Run ALL tests**

```bash
uv run python -m pytest tests/ -v
```

- [ ] **Step 5: Lint**

```bash
uv run ruff check src/agents/config.py tests/test_config.py && uv run ruff format src/agents/config.py tests/test_config.py
```

- [ ] **Step 6: Commit**

```bash
git add src/agents/config.py tests/test_config.py
git commit -m "feat: add build_prompt with intent + context hints assembly"
```

---

### Task 3: Update Executor to use build_prompt

**Files:**
- Modify: `src/agents/executor.py`

- [ ] **Step 1: Update import and call in executor.py**

In `src/agents/executor.py`, change:

```python
# Before (line 11):
from agents.config import ExecutionConfig, render_prompt

# After:
from agents.config import ExecutionConfig, build_prompt
```

And in `run_task`, change:

```python
# Before (around line 117):
prompt = render_prompt(task.prompt, variables or {})

# After:
prompt = build_prompt(task, variables or {})
```

- [ ] **Step 2: Run ALL tests**

```bash
uv run python -m pytest tests/ -v
```

Expected: ALL pass (executor tests use `prompt=` which is backwards compatible).

- [ ] **Step 3: Commit**

```bash
git add src/agents/executor.py
git commit -m "refactor: executor uses build_prompt instead of render_prompt"
```

---

## Chunk 2: Streaming

### Task 4: Create streaming.py

**Files:**
- Create: `src/agents/streaming.py`
- Create: `tests/test_streaming.py`

- [ ] **Step 1: Write failing tests for stream parsing**

```python
# tests/test_streaming.py
import json
import pytest


def test_parse_assistant_text():
    from agents.streaming import parse_stream_line

    line = json.dumps({
        "type": "assistant",
        "message": {
            "content": [{"type": "text", "text": "Hello world"}],
        },
    })
    event = parse_stream_line(line)
    assert event is not None
    assert event.type == "assistant"
    assert event.content == "Hello world"


def test_parse_assistant_tool_use():
    from agents.streaming import parse_stream_line

    line = json.dumps({
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la"}},
            ],
        },
    })
    event = parse_stream_line(line)
    assert event is not None
    assert event.type == "tool_use"
    assert event.tool_name == "Bash"
    assert "ls -la" in event.content


def test_parse_tool_result():
    from agents.streaming import parse_stream_line

    line = json.dumps({
        "type": "user",
        "message": {
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_123", "content": "file1.txt\nfile2.txt"},
            ],
        },
    })
    event = parse_stream_line(line)
    assert event is not None
    assert event.type == "tool_result"
    assert "file1.txt" in event.content


def test_parse_result_success():
    from agents.streaming import parse_stream_line

    line = json.dumps({
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "total_cost_usd": 0.45,
        "num_turns": 8,
        "result": "Done!",
    })
    event = parse_stream_line(line)
    assert event is not None
    assert event.type == "result"
    assert event.content == "Done!"


def test_parse_thinking_returns_none():
    from agents.streaming import parse_stream_line

    line = json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "thinking", "thinking": "hmm..."}]},
    })
    event = parse_stream_line(line)
    assert event is None


def test_parse_system_hook_returns_none():
    from agents.streaming import parse_stream_line

    line = json.dumps({"type": "system", "subtype": "hook_started"})
    event = parse_stream_line(line)
    assert event is None


def test_parse_system_init():
    from agents.streaming import parse_stream_line

    line = json.dumps({"type": "system", "subtype": "init", "session_id": "abc"})
    event = parse_stream_line(line)
    assert event is not None
    assert event.type == "system"


def test_parse_malformed_json():
    from agents.streaming import parse_stream_line

    event = parse_stream_line("not json at all")
    assert event is None


def test_parse_rate_limit_returns_none():
    from agents.streaming import parse_stream_line

    line = json.dumps({"type": "rate_limit_event"})
    event = parse_stream_line(line)
    assert event is None


def test_extract_result_from_line():
    from agents.streaming import extract_result_from_line

    line = json.dumps({
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "total_cost_usd": 1.23,
        "num_turns": 5,
        "result": "All done",
    })
    output = extract_result_from_line(line)
    assert output.cost_usd == pytest.approx(1.23)
    assert output.num_turns == 5
    assert output.is_error is False
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
uv run python -m pytest tests/test_streaming.py -v
```

- [ ] **Step 3: Implement streaming.py**

```python
# src/agents/streaming.py
import json
import time
from typing import Literal

from pydantic import BaseModel

from agents.executor import ClaudeOutput

StreamEventType = Literal[
    "assistant", "tool_use", "tool_result", "result", "system", "unknown"
]


class StreamEvent(BaseModel):
    type: StreamEventType
    content: str = ""
    tool_name: str = ""
    timestamp: float


def parse_stream_line(line: str) -> StreamEvent | None:
    """Parse a single stream-json line. Returns None for irrelevant events."""
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None

    event_type = data.get("type", "")

    # Filter out noise
    if event_type == "rate_limit_event":
        return None
    if event_type == "system":
        subtype = data.get("subtype", "")
        if subtype.startswith("hook_"):
            return None
        if subtype == "init":
            return StreamEvent(type="system", content="session started", timestamp=time.time())
        return None

    # Assistant messages — may contain text, tool_use, or thinking
    if event_type == "assistant":
        message = data.get("message", {})
        content_blocks = message.get("content", []) if isinstance(message, dict) else []
        if not isinstance(content_blocks, list):
            return None

        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")

            if block_type == "text":
                return StreamEvent(
                    type="assistant",
                    content=block.get("text", ""),
                    timestamp=time.time(),
                )
            if block_type == "tool_use":
                return StreamEvent(
                    type="tool_use",
                    tool_name=block.get("name", ""),
                    content=json.dumps(block.get("input", {}))[:200],
                    timestamp=time.time(),
                )
            if block_type == "thinking":
                return None

        return None

    # Tool results come as "user" messages with tool_result content
    if event_type == "user":
        message = data.get("message", {})
        content_blocks = message.get("content", []) if isinstance(message, dict) else []
        if not isinstance(content_blocks, list):
            return None

        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                raw_content = block.get("content", "")
                content_str = raw_content if isinstance(raw_content, str) else json.dumps(raw_content)
                return StreamEvent(
                    type="tool_result",
                    content=content_str[:500],
                    timestamp=time.time(),
                )
        return None

    # Final result
    if event_type == "result":
        return StreamEvent(
            type="result",
            content=data.get("result", ""),
            timestamp=time.time(),
        )

    return None


def extract_result_from_line(line: str) -> ClaudeOutput:
    """Extract ClaudeOutput from a result event line."""
    data = json.loads(line)
    return ClaudeOutput(
        result=data.get("result", ""),
        is_error=data.get("is_error", False),
        cost_usd=data.get("total_cost_usd", 0.0),
        num_turns=data.get("num_turns", 0),
    )
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run python -m pytest tests/test_streaming.py -v
```

- [ ] **Step 5: Lint**

```bash
uv run ruff check src/agents/streaming.py tests/test_streaming.py && uv run ruff format src/agents/streaming.py tests/test_streaming.py
```

- [ ] **Step 6: Commit**

```bash
git add src/agents/streaming.py tests/test_streaming.py
git commit -m "feat: add stream-json parser for real-time Claude output"
```

---

### Task 5: Evolve Executor to streaming mode

**Files:**
- Modify: `src/agents/executor.py`
- Modify: `tests/test_executor.py`

- [ ] **Step 1: Write failing test for streaming executor**

Add to `tests/test_executor.py`:

```python
@pytest.mark.asyncio
async def test_executor_accepts_stream_callback(tmp_path):
    from agents.budget import BudgetManager
    from agents.config import BudgetConfig, ExecutionConfig
    from agents.executor import Executor
    from agents.history import HistoryDB
    from agents.notifier import Notifier

    events_received = []

    async def on_event(run_id, event):
        events_received.append((run_id, event))

    db = HistoryDB(tmp_path / "test.db")
    budget = BudgetManager(config=BudgetConfig(), history=db)
    notifier = Notifier(webhook_url="")
    exec_config = ExecutionConfig(worktree_base=str(tmp_path / "wt"), dry_run=True)
    executor = Executor(
        config=exec_config, budget=budget, history=db,
        notifier=notifier, data_dir=tmp_path / "data",
        on_stream_event=on_event,
    )
    assert executor.on_stream_event is on_event
```

- [ ] **Step 2: Run test — verify it fails**

```bash
uv run python -m pytest tests/test_executor.py::test_executor_accepts_stream_callback -v
```

- [ ] **Step 3: Update Executor.__init__ to accept on_stream_event**

In `src/agents/executor.py`, update `__init__`:

```python
def __init__(
    self,
    config: ExecutionConfig,
    budget: BudgetManager,
    history: HistoryDB,
    notifier: Notifier,
    data_dir: Path,
    on_stream_event: Callable | None = None,
) -> None:
    self.config = config
    self.budget = budget
    self.history = history
    self.notifier = notifier
    self.data_dir = data_dir
    self._running_processes: dict[str, asyncio.subprocess.Process] = {}
    self.on_stream_event = on_stream_event or self._noop_event

async def _noop_event(self, run_id: str, event: Any) -> None:
    pass
```

Add import at top: `from collections.abc import Callable` and `from typing import Any`.

- [ ] **Step 4: Update _run_claude for streaming**

Replace `_run_claude` method:

```python
async def _run_claude(
    self, cmd: list[str], cwd: str, run_id: str, timeout: int
) -> tuple[ClaudeOutput, str]:
    from agents.streaming import RunStream

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
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

Wait — we need `RunStream` class in `streaming.py`. Add it:

```python
# Add to src/agents/streaming.py
class RunStream:
    def __init__(self, run_id: str, on_event: Callable) -> None:
        self.run_id = run_id
        self.on_event = on_event
        self.raw_lines: list[str] = []

    async def process_stream(self, proc: asyncio.subprocess.Process) -> ClaudeOutput:
        last_result: ClaudeOutput | None = None

        async for line in proc.stdout:
            text = line.decode().strip()
            if not text:
                continue
            self.raw_lines.append(text)
            event = parse_stream_line(text)
            if event:
                await self.on_event(self.run_id, event)
                if event.type == "result":
                    last_result = extract_result_from_line(text)

        await proc.wait()
        return last_result or ClaudeOutput(is_error=True, result="No result received")

    def get_raw_output(self) -> str:
        return "\n".join(self.raw_lines)
```

Add imports at top of streaming.py: `import asyncio` and `from collections.abc import Callable`.

- [ ] **Step 5: Update run_task to handle tuple return + --verbose flag**

In `run_task`, update the claude_cmd to add `--verbose` and change `json` to `stream-json`:

```python
claude_cmd = [
    "claude", "-p", prompt,
    "--model", task.model,
    "--max-budget-usd", str(task.max_cost_usd),
    "--output-format", "stream-json",
    "--verbose",
    "--permission-mode", "auto",
    "--no-session-persistence",
]
```

And update the section that calls `_run_claude` and saves output:

```python
# Before:
stdout = await self._run_claude(claude_cmd, cwd=str(worktree_path), run_id=run_id, timeout=...)
output = parse_claude_output(stdout)
...
output_file.write_text(stdout)

# After:
output, raw_output = await self._run_claude(claude_cmd, cwd=str(worktree_path), run_id=run_id, timeout=...)
...
output_file.write_text(raw_output)
```

Remove the `parse_claude_output(stdout)` call since `_run_claude` now returns parsed `ClaudeOutput` directly.

- [ ] **Step 6: Run ALL tests**

```bash
uv run python -m pytest tests/ -v
```

- [ ] **Step 7: Lint**

```bash
uv run ruff check src/ tests/ && uv run ruff format src/ tests/
```

- [ ] **Step 8: Commit**

```bash
git add src/agents/executor.py src/agents/streaming.py tests/test_executor.py tests/test_streaming.py
git commit -m "feat: streaming executor with real-time event parsing"
```

---

## Chunk 3: Dashboard + WebSocket + Project Configs

### Task 6: Add NiceGUI dependency and WebSocket to main.py

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/agents/main.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Add nicegui dependency**

In `pyproject.toml`, add to `dependencies`:

```toml
"nicegui>=2.5,<3",
```

Then install:

```bash
uv sync --all-extras
```

- [ ] **Step 2: Write failing test for WebSocket endpoint**

Add to `tests/test_main.py`:

```python
@pytest.mark.asyncio
async def test_websocket_runs(test_app):
    from httpx import ASGITransport, AsyncClient

    # WebSocket test — just verify the endpoint exists by checking it's not 404
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # We can't do a real WebSocket test with httpx, but we can verify
        # the app has the route by checking it doesn't 404 on GET
        # (WebSocket routes return 403 on non-upgrade GET requests)
        response = await client.get("/ws/runs")
        assert response.status_code in (403, 426)  # WebSocket upgrade required
```

- [ ] **Step 3: Add WebSocket endpoints and broadcast to main.py**

Add imports at top of `main.py`:

```python
import json
from fastapi import WebSocket, WebSocketDisconnect
from agents.streaming import StreamEvent
```

Add to `AppState.__init__`:

```python
self.ws_clients: dict[str, set[WebSocket]] = {}
self.ws_global_clients: set[WebSocket] = set()
```

Add broadcast function inside `create_app`:

```python
async def broadcast_event(run_id: str, event: StreamEvent) -> None:
    msg = event.model_dump_json()
    dead: set[WebSocket] = set()
    for ws in set(state.ws_clients.get(run_id, set())):  # copy to avoid mutation during iteration
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    if run_id in state.ws_clients:
        state.ws_clients[run_id].difference_update(dead)

    dead_global: set[WebSocket] = set()
    for ws in set(state.ws_global_clients):  # copy to avoid mutation during iteration
        try:
            await ws.send_text(json.dumps({"run_id": run_id, **event.model_dump()}))
        except Exception:
            dead_global.add(ws)
    state.ws_global_clients.difference_update(dead_global)
```

Update executor creation to pass broadcast:

```python
executor = Executor(
    config=config.execution, budget=budget, history=history,
    notifier=notifier, data_dir=data_dir,
    on_stream_event=broadcast_event,
)
```

Add WebSocket routes:

```python
@app.websocket("/ws/runs/{run_id}")
async def ws_run(websocket: WebSocket, run_id: str) -> None:
    await websocket.accept()
    state.ws_clients.setdefault(run_id, set()).add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        state.ws_clients.get(run_id, set()).discard(websocket)

@app.websocket("/ws/runs")
async def ws_all_runs(websocket: WebSocket) -> None:
    await websocket.accept()
    state.ws_global_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        state.ws_global_clients.discard(websocket)
```

- [ ] **Step 4: Run ALL tests**

```bash
uv run python -m pytest tests/ -v
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/agents/main.py tests/test_main.py
git commit -m "feat: add WebSocket endpoints for real-time streaming"
```

---

### Task 7: Create Dashboard (NiceGUI)

**Files:**
- Create: `src/agents/dashboard.py`
- Modify: `src/agents/main.py`

- [ ] **Step 1: Create dashboard.py**

```python
# src/agents/dashboard.py
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from fastapi import FastAPI

    from agents.config import GlobalConfig
    from agents.main import AppState

logger = logging.getLogger(__name__)


def setup_dashboard(app: FastAPI, state: AppState, config: GlobalConfig) -> None:
    """Mount NiceGUI dashboard on the existing FastAPI app."""

    @ui.page("/dashboard")
    async def dashboard_page() -> None:
        ui.dark_mode(True)

        # Header
        with ui.header().classes("items-center justify-between"):
            ui.label("Agent Runner").classes("text-h5 font-bold")
            budget = state.budget.get_status()
            budget_label = ui.label(
                f"Budget: ${budget.spent_today_usd:.2f} / ${budget.daily_limit_usd:.2f}"
            )
            budget_bar = ui.linear_progress(
                value=budget.spent_today_usd / budget.daily_limit_usd if budget.daily_limit_usd > 0 else 0,
                show_value=False,
            ).classes("w-48")

        # Stats cards
        with ui.row().classes("w-full gap-4 p-4"):
            runs = state.history.list_runs_today()
            success = sum(1 for r in runs if r.status == "success")
            failed = sum(1 for r in runs if r.status in ("failure", "timeout"))
            running = sum(1 for r in runs if r.status == "running")
            total_cost = sum(r.cost_usd or 0 for r in runs)

            for label, value, color in [
                ("Runs Today", str(len(runs)), "blue"),
                ("Success", str(success), "green"),
                ("Failed", str(failed), "red"),
                ("Cost", f"${total_cost:.2f}", "orange"),
            ]:
                with ui.card().classes(f"p-4 min-w-[120px]"):
                    ui.label(label).classes("text-sm text-gray-400")
                    ui.label(value).classes(f"text-2xl font-bold text-{color}")

        # Live run panel
        live_container = ui.column().classes("w-full px-4")

        # Run history table
        with ui.card().classes("w-full mx-4"):
            ui.label("Run History").classes("text-h6 mb-2")
            columns = [
                {"name": "project", "label": "Project", "field": "project"},
                {"name": "task", "label": "Task", "field": "task"},
                {"name": "status", "label": "Status", "field": "status"},
                {"name": "cost", "label": "Cost", "field": "cost"},
                {"name": "duration", "label": "Duration", "field": "duration"},
                {"name": "pr", "label": "PR", "field": "pr"},
            ]
            rows = []
            for r in runs[:20]:
                duration = ""
                if r.started_at and r.finished_at:
                    delta = r.finished_at - r.started_at
                    minutes, seconds = divmod(int(delta.total_seconds()), 60)
                    duration = f"{minutes}m{seconds:02d}s"
                status_icon = {"success": "✅", "failure": "❌", "running": "🔄", "timeout": "⏰"}.get(r.status, r.status)
                rows.append({
                    "project": r.project,
                    "task": r.task,
                    "status": status_icon,
                    "cost": f"${r.cost_usd:.2f}" if r.cost_usd else "—",
                    "duration": duration,
                    "pr": r.pr_url or "—",
                })
            ui.table(columns=columns, rows=rows, row_key="project").classes("w-full")

        # Manual trigger
        with ui.card().classes("w-full mx-4"):
            ui.label("Manual Trigger").classes("text-h6 mb-2")
            project_names = list(state.projects.keys())
            project_select = ui.select(project_names, label="Project").classes("w-48")
            task_select = ui.select([], label="Task").classes("w-48")

            def on_project_change(e: object) -> None:
                project = state.projects.get(project_select.value, None)
                if project:
                    task_select.options = list(project.tasks.keys())
                    task_select.update()

            project_select.on_value_change(on_project_change)

            async def trigger_run() -> None:
                if project_select.value and task_select.value:
                    import httpx

                    async with httpx.AsyncClient() as client:
                        await client.post(
                            f"http://localhost:{config.server.port}/tasks/{project_select.value}/{task_select.value}/run"
                        )
                    ui.notify(f"Triggered {project_select.value}/{task_select.value}", type="positive")

            ui.button("Run", on_click=trigger_run).classes("mt-2")

        # Scheduled tasks
        with ui.card().classes("w-full mx-4 mb-4"):
            ui.label("Scheduled Tasks").classes("text-h6 mb-2")
            for project in state.projects.values():
                for task_name, task in project.tasks.items():
                    if task.schedule:
                        ui.label(f"{project.name}/{task_name} — {task.schedule}").classes("text-sm")

        # Auto-refresh stats
        async def refresh_stats() -> None:
            budget = state.budget.get_status()
            budget_label.text = f"Budget: ${budget.spent_today_usd:.2f} / ${budget.daily_limit_usd:.2f}"
            ratio = budget.spent_today_usd / budget.daily_limit_usd if budget.daily_limit_usd > 0 else 0
            budget_bar.value = min(ratio, 1.0)

        ui.timer(5.0, refresh_stats)

    ui.run_with(app)
```

- [ ] **Step 2: Mount dashboard in main.py**

Add at the end of `create_app()`, before `return app`:

```python
# Mount NiceGUI dashboard
from agents.dashboard import setup_dashboard
setup_dashboard(app, state, config)
```

- [ ] **Step 3: Test the dashboard renders**

```bash
uv run uvicorn agents.main:create_app --factory --host 127.0.0.1 --port 8080 &
sleep 3
echo "=== HEALTH ===" && curl -s http://127.0.0.1:8080/health
echo "" && echo "=== DASHBOARD ===" && curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/dashboard
kill %1 2>/dev/null
```

Expected: health returns 200, dashboard returns 200.

- [ ] **Step 4: Run ALL tests**

```bash
uv run python -m pytest tests/ -v
```

- [ ] **Step 5: Lint**

```bash
uv run ruff check src/ tests/ && uv run ruff format src/ tests/
```

- [ ] **Step 6: Commit**

```bash
git add src/agents/dashboard.py src/agents/main.py
git commit -m "feat: add NiceGUI dashboard with stats, history, and manual trigger"
```

---

### Task 8: Project Configs for All Projects

**Files:**
- Modify: `projects/sekit.yaml`
- Create: `projects/fintech.yaml`
- Create: `projects/momease.yaml`
- Create: `projects/primeleague.yaml`
- Create: `projects/jarvis.yaml`
- Create: `projects/devscout.yaml`

- [ ] **Step 1: Update sekit.yaml to intent format**

```yaml
# projects/sekit.yaml
name: sekit
repo: /Users/vini/Developer/sekit
base_branch: main
branch_prefix: agents/
notify: slack

tasks:
  ci-fix:
    description: "Investigate and fix CI failure"
    intent: "Investigue e corrija o CI failure neste monorepo."
    context_hints:
      - "Use o Sentry pra buscar erros recentes no projeto sekit"
      - "Verifique issues abertas no Linear com label bug"
      - "Rode `just check-all` pra validar o fix"
    trigger:
      type: github
      events: [check_suite.completed]
      filter: { conclusion: failure }
    model: sonnet
    max_cost_usd: 3.00
    autonomy: pr-only

  dep-update:
    description: "Update all dependencies and run tests"
    intent: "Atualize todas as dependências e valide com testes."
    context_hints:
      - "Rode o update pra cada app: web (pnpm), api (bundle), agents (uv)"
      - "Rode `just check-all` — só commite se todos passarem"
    schedule: "0 3 * * MON"
    model: haiku
    max_cost_usd: 1.00
    autonomy: auto-merge

  lint-fix:
    description: "Fix lint issues across all apps"
    intent: "Corrija issues de lint em todos os apps."
    context_hints:
      - "Rode `just lint-web`, `just lint-api`, `just lint-agents`"
      - "Corrija issues auto-fixáveis e commite"
    schedule: "0 4 * * FRI"
    model: haiku
    max_cost_usd: 0.50
    autonomy: auto-merge
```

- [ ] **Step 2: Create configs for other projects**

Create `projects/jarvis.yaml`:
```yaml
name: jarvis
repo: /Users/vini/Developer/jarvis-whatschat
base_branch: main
branch_prefix: agents/
notify: slack

tasks:
  dep-update:
    description: "Update Python dependencies and run tests"
    intent: "Atualize as dependências Python e rode os testes."
    context_hints:
      - "Use pip ou requirements.txt pra atualizar"
      - "Rode os testes pra validar"
    schedule: "0 3 * * MON"
    model: haiku
    max_cost_usd: 0.50
    autonomy: auto-merge

  lint-fix:
    description: "Run ruff check --fix and format"
    intent: "Rode ruff check --fix e ruff format no projeto."
    schedule: "0 4 * * FRI"
    model: haiku
    max_cost_usd: 0.30
    autonomy: auto-merge
```

Create similar configs for `fintech.yaml`, `momease.yaml`, `primeleague.yaml`, `devscout.yaml` — each tailored to the project's stack. Use `prompt:` for projects without complex needs, `intent:` + `context_hints:` for projects with Sentry/Linear integration.

- [ ] **Step 3: Verify configs load correctly**

```bash
uv run python -c "
from pathlib import Path
from agents.config import load_project_configs
projects = load_project_configs(Path('projects'))
for name, p in projects.items():
    tasks = list(p.tasks.keys())
    print(f'{name}: {tasks}')
"
```

- [ ] **Step 4: Commit**

```bash
git add projects/
git commit -m "feat: add project configs for all repos with intent + context hints"
```

---

### Task 9: Final Verification

- [ ] **Step 1: Run full test suite**

```bash
uv run python -m pytest tests/ -v --tb=short
```

All tests must pass.

- [ ] **Step 2: Lint and type check**

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```

- [ ] **Step 3: Smoke test — server + dashboard**

```bash
uv run uvicorn agents.main:create_app --factory --host 127.0.0.1 --port 8080 &
sleep 3
curl -s http://127.0.0.1:8080/health
curl -s -o /dev/null -w "Dashboard: %{http_code}\n" http://127.0.0.1:8080/dashboard
curl -s http://127.0.0.1:8080/status | python3 -m json.tool
kill %1 2>/dev/null
```

- [ ] **Step 4: Commit any final fixes**

```bash
git add -A && git commit -m "chore: final verification and cleanup"
```
