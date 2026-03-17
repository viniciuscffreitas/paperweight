# Dashboard Clean Refinement — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refine the Agent Runner dashboard to eliminate visual noise and reduce cognitive load — two panels (live stream + run history) with a compact header.

**Architecture:** NiceGUI dashboard backed by FastAPI. Two files change: `dashboard_formatters.py` (data formatting) and `dashboard.py` (UI layout + CSS). Formatters are pure functions, easy to TDD. Dashboard tests use mock patching of `ui.*`.

**Tech Stack:** Python, NiceGUI, Quasar (via NiceGUI), asyncio

**Spec:** `docs/superpowers/specs/2026-03-16-dashboard-clean-refinement-design.md`

---

## Chunk 1: Formatter Refactoring

### Task 1: Refactor `_format_tool_use` return type

Change `_format_tool_use()` from returning `(icon, label)` to returning just `str` (the label).

**Files:**
- Modify: `src/agents/dashboard_formatters.py:29-85`
- Modify: `tests/test_dashboard_formatters.py`

- [ ] **Step 1: Update tests for `_format_tool_use` callers**

Tests that check for emoji icons in `format_event_line` output need to expect no emoji. Update these tests:

```python
# tests/test_dashboard_formatters.py

# Replace test_format_event_line_task_started (line 27-33):
def test_format_event_line_task_started():
    from agents.dashboard_formatters import format_event_line
    data = {"run_id": "sekit-ci-fix-20260316-120000-abcd1234", "type": "task_started", "content": "sekit/ci-fix [github]"}
    line = format_event_line(data)
    assert "[sekit/ci-fix]" in line
    assert "sekit/ci-fix [github]" in line
    # No emoji
    assert "🚀" not in line

# Replace test_format_event_line_task_failed (line 44-50):
def test_format_event_line_task_failed():
    from agents.dashboard_formatters import format_event_line
    data = {"run_id": "a-b-x", "type": "task_failed", "content": "Budget exceeded"}
    line = format_event_line(data)
    assert "Budget exceeded" in line
    assert "❌" not in line

# Replace test_format_event_line_dry_run (line 53-58):
def test_format_event_line_dry_run():
    from agents.dashboard_formatters import format_event_line
    data = {"run_id": "a-b-x", "type": "dry_run", "content": "dry_run=true — skipping"}
    line = format_event_line(data)
    assert "dry_run=true" in line
    assert "⚡" not in line

# Replace test_format_event_line_assistant (line 83-89):
def test_format_event_line_assistant():
    from agents.dashboard_formatters import format_event_line
    data = {"run_id": "a-b-x", "type": "assistant", "content": "I found the issue."}
    line = format_event_line(data)
    assert "I found the issue." in line
    assert "💬" not in line
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dashboard_formatters.py -v -k "task_started or task_failed or dry_run or assistant"`
Expected: FAIL — tests expect no emoji but current code has emoji

- [ ] **Step 3: Refactor `_format_tool_use` and `format_event_line`**

In `src/agents/dashboard_formatters.py`:

1. Change `_format_tool_use` return type from `tuple[str, str]` to `str` — return only the label, drop the icon.
2. Update `format_event_line` to remove all `EVENT_ICONS` references. New format: `[project/task] content` (plain text, no emoji prefix).
3. Remove `EVENT_ICONS` and `TOOL_ICONS` constants. **Keep `STATUS_ICONS` for now** — it's still referenced by `build_history_rows` until Task 4 removes that reference.

```python
def _format_tool_use(tool_name: str, content: str) -> str:
    """Return formatted label for a tool_use event."""
    try:
        inp = json.loads(content) if content else {}
    except (json.JSONDecodeError, TypeError):
        inp = {}

    if tool_name == "Read":
        return f"Read {_shorten_path(inp.get('file_path', content))}"
    if tool_name == "Bash":
        cmd = inp.get("command", content)
        cmd = _shorten_path(cmd.replace("\n", " "))
        if len(cmd) > 80:
            cmd = cmd[:80] + "\u2026"
        return f"Bash: {cmd}"
    if tool_name == "Edit":
        return f"Edit {_shorten_path(inp.get('file_path', content))}"
    if tool_name == "Write":
        return f"Write {_shorten_path(inp.get('file_path', content))}"
    if tool_name == "Glob":
        return f"Glob {inp.get('pattern', content)}"
    if tool_name == "Grep":
        return f'Grep "{inp.get("pattern", content)}"'
    if tool_name == "Agent":
        desc = inp.get("description", inp.get("prompt", content))
        if len(desc) > 80:
            desc = desc[:80] + "\u2026"
        return f"Agent: {desc}"
    if tool_name == "Skill":
        return f"Skill: {inp.get('skill', content)}"
    if tool_name == "TodoWrite":
        return "TodoWrite"
    preview = _shorten_path(content)
    if len(preview) > 80:
        preview = preview[:80] + "\u2026"
    return f"{tool_name}: {preview}"
```

Update `format_event_line`:

```python
def format_event_line(data: dict) -> str:
    """Single-line plain text for logging. No emoji, no HTML."""
    short = short_run_id(data.get("run_id", "?"))
    event_type = data.get("type", "")
    content = str(data.get("content") or "")
    tool_name = data.get("tool_name") or ""

    if event_type in ("task_started", "task_completed", "task_failed", "dry_run"):
        return f"[{short}] {content}"
    if event_type == "system":
        return f"[{short}] session started"
    if event_type == "tool_use":
        return f"[{short}] {_format_tool_use(tool_name, content)}"
    if event_type == "tool_result":
        return f"[{short}] {_format_tool_result(content)}"
    if event_type == "assistant":
        preview = _shorten_path(content)
        if len(preview) > 120:
            preview = preview[:120] + "\u2026"
        return f"[{short}] {preview}"
    if event_type == "result":
        return f"[{short}] done"
    return f"[{short}] {event_type}: {_shorten_path(content)[:80]}"
```

Remove these constants (delete lines 11-21, 96-106):
- `TOOL_ICONS`
- `EVENT_ICONS`

**Do NOT remove `STATUS_ICONS` yet** — `build_history_rows` still references it. It will be removed in Task 4.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dashboard_formatters.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/dashboard_formatters.py tests/test_dashboard_formatters.py
git commit -m "refactor(formatters): remove emoji icons from event formatting"
```

---

### Task 2: Add `format_stream_html()`

New function for the colored live stream (replaces `ui.log` plain text).

**Files:**
- Modify: `src/agents/dashboard_formatters.py`
- Modify: `tests/test_dashboard_formatters.py`

- [ ] **Step 1: Write failing tests for `format_stream_html`**

```python
# tests/test_dashboard_formatters.py — append these

# ── format_stream_html ──────────────────────────────────────────────────────

STREAM_COLORS = {
    "task_started": "#22d3ee",
    "task_completed": "#4ade80",
    "task_failed": "#f87171",
    "tool_use": "#d4d4d8",
    "tool_result": "#6b7280",
    "assistant": "#a1a1aa",
    "result": "#4ade80",
    "system": "#22d3ee",
}


def test_format_stream_html_returns_html_div():
    from agents.dashboard_formatters import format_stream_html
    data = {"run_id": "p-t-x", "type": "tool_use", "tool_name": "Bash", "content": "ls"}
    html = format_stream_html(data)
    assert html.startswith("<div")
    assert html.endswith("</div>")


def test_format_stream_html_no_emoji():
    from agents.dashboard_formatters import format_stream_html
    data = {"run_id": "p-t-x", "type": "task_started", "content": "p/t [manual]"}
    html = format_stream_html(data)
    # No emoji characters (codepoints above U+1F000)
    assert not any(ord(c) > 0x1F000 for c in html)


def test_format_stream_html_uses_correct_color_for_tool_use():
    from agents.dashboard_formatters import format_stream_html
    data = {"run_id": "p-t-x", "type": "tool_use", "tool_name": "Read", "content": '{"file_path":"src/main.py"}'}
    html = format_stream_html(data)
    assert "#d4d4d8" in html
    assert "Read src/main.py" in html


def test_format_stream_html_uses_correct_color_for_failure():
    from agents.dashboard_formatters import format_stream_html
    data = {"run_id": "p-t-x", "type": "task_failed", "content": "timeout"}
    html = format_stream_html(data)
    assert "#f87171" in html


def test_format_stream_html_includes_run_id():
    from agents.dashboard_formatters import format_stream_html
    data = {"run_id": "proj-task-20260316-120000-abcd1234", "type": "assistant", "content": "hello"}
    html = format_stream_html(data)
    assert "proj/task" in html


def test_format_stream_html_no_timestamp_column():
    from agents.dashboard_formatters import format_stream_html
    data = {"run_id": "p-t-x", "type": "system", "content": "", "timestamp": 1710590400.0}
    html = format_stream_html(data)
    # Stream does NOT show HH:MM:SS timestamp (unlike drawer)
    assert "--:--:--" not in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dashboard_formatters.py -v -k "format_stream_html"`
Expected: FAIL — `format_stream_html` does not exist yet

- [ ] **Step 3: Implement `format_stream_html`**

Add to `src/agents/dashboard_formatters.py`:

```python
STREAM_COLORS: dict[str, str] = {
    "task_started": "#22d3ee",
    "task_completed": "#4ade80",
    "task_failed": "#f87171",
    "dry_run": "#fbbf24",
    "tool_use": "#d4d4d8",
    "tool_result": "#6b7280",
    "assistant": "#a1a1aa",
    "result": "#4ade80",
    "system": "#22d3ee",
    "unknown": "#6b7280",
}


def format_stream_html(data: dict) -> str:
    """Colored HTML line for the live stream panel. No emoji, no timestamp column."""
    short = short_run_id(data.get("run_id", "?"))
    event_type = data.get("type", "")
    content = str(data.get("content") or "")
    tool_name = data.get("tool_name") or ""
    color = STREAM_COLORS.get(event_type, "#6b7280")

    if event_type == "tool_use":
        label = _format_tool_use(tool_name, content)
    elif event_type == "tool_result":
        label = _format_tool_result(content)
    elif event_type == "assistant":
        label = _shorten_path(content)
        if len(label) > 120:
            label = label[:120] + "\u2026"
    elif event_type in ("task_started", "task_completed", "task_failed", "dry_run"):
        label = content
    elif event_type == "system":
        label = "session started"
    elif event_type == "result":
        label = "done"
    else:
        label = f"{event_type}: {_shorten_path(content)[:80]}"

    return (
        "<div style='display:flex;gap:6px;padding:1px 0;font-size:12px;font-family:monospace'>"
        f"<span style='color:#6b7280;flex-shrink:0'>[{short}]</span>"
        f"<span style='color:{color};word-break:break-all'>{label}</span>"
        "</div>"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dashboard_formatters.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/dashboard_formatters.py tests/test_dashboard_formatters.py
git commit -m "feat(formatters): add format_stream_html for colored live stream"
```

---

### Task 3: Update `format_event_html` (drawer consistency)

Remove emoji from drawer HTML and update `EVENT_COLORS['tool_use']` to match stream.

**Files:**
- Modify: `src/agents/dashboard_formatters.py:108-119` (EVENT_COLORS)
- Modify: `src/agents/dashboard_formatters.py:178-212` (format_event_html)
- Modify: `tests/test_dashboard_formatters.py`

- [ ] **Step 1: Update tests**

```python
# Replace test_format_event_html_contains_color_for_type:
def test_format_event_html_contains_color_for_type():
    from agents.dashboard_formatters import EVENT_COLORS, format_event_html
    data = {"run_id": "a-b", "type": "tool_use", "tool_name": "Bash", "content": "ls"}
    html = format_event_html(data)
    assert EVENT_COLORS["tool_use"] in html
    assert "Bash" in html
    # No emoji
    assert not any(ord(c) > 0x1F000 for c in html)


# Add new test:
def test_format_event_html_tool_use_color_is_light_gray():
    from agents.dashboard_formatters import EVENT_COLORS
    assert EVENT_COLORS["tool_use"] == "#d4d4d8"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dashboard_formatters.py -v -k "format_event_html"`
Expected: FAIL — emoji still present, tool_use color is still `#fbbf24`

- [ ] **Step 3: Update `EVENT_COLORS` and `format_event_html`**

Update `EVENT_COLORS`:

```python
EVENT_COLORS: dict[str, str] = {
    "task_started": "#22d3ee",
    "task_completed": "#4ade80",
    "task_failed": "#f87171",
    "dry_run": "#fbbf24",
    "tool_use": "#d4d4d8",      # changed from #fbbf24
    "tool_result": "#6b7280",
    "assistant": "#a1a1aa",      # changed from #e2e8f0
    "result": "#4ade80",
    "system": "#22d3ee",
    "unknown": "#6b7280",
}
```

Update `format_event_html` to remove emoji:

```python
def format_event_html(data: dict) -> str:
    """Rich HTML row for the run detail drawer. No emoji."""
    event_type = data.get("type", "")
    content = str(data.get("content") or "")
    tool_name = data.get("tool_name") or ""
    color = EVENT_COLORS.get(event_type, "#6b7280")
    ts = data.get("timestamp")
    time_str = datetime.fromtimestamp(ts, tz=UTC).strftime("%H:%M:%S") if ts else "--:--:--"

    if event_type == "tool_use":
        label = f"<span style='color:{color}'>{_format_tool_use(tool_name, content)}</span>"
    elif event_type == "tool_result":
        label = f"<span style='color:#6b7280'>{_format_tool_result(content)}</span>"
    elif event_type == "assistant":
        preview = _shorten_path(content)
        if len(preview) > 200:
            preview = preview[:200] + "\u2026"
        label = preview
    else:
        label = content or event_type

    return (
        "<div style='display:flex;gap:8px;padding:3px 0;border-bottom:1px solid #1e2130'>"
        f"<span style='color:#374151;font-size:10px;min-width:60px;padding-top:1px'>"
        f"{time_str}</span>"
        f"<span style='color:{color};font-size:12px;font-family:monospace;"
        f"word-break:break-all'>{label}</span>"
        "</div>"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dashboard_formatters.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/dashboard_formatters.py tests/test_dashboard_formatters.py
git commit -m "refactor(formatters): remove emoji from drawer HTML, unify color palette"
```

---

### Task 4: Update `build_history_rows` and `_HISTORY_COLS`

Status uses `raw_status` string (dot rendered via CSS), remove `model`/`cost` columns from `_HISTORY_COLS`.

**Files:**
- Modify: `src/agents/dashboard_formatters.py:215-241` (build_history_rows)
- Modify: `src/agents/dashboard.py:60-67` (_HISTORY_COLS)
- Modify: `tests/test_dashboard_formatters.py`

- [ ] **Step 1: Update tests**

```python
# Keep test_build_history_rows_success_has_duration AS-IS (don't remove duration coverage)

# Add new tests:
def test_build_history_rows_status_is_raw_string():
    from agents.dashboard_formatters import build_history_rows
    rows = build_history_rows([_make_run(status="success")])
    assert rows[0]["status"] == "success"
    # No emoji
    assert "✅" not in rows[0]["status"]


def test_build_history_rows_has_raw_status_field():
    from agents.dashboard_formatters import build_history_rows
    rows = build_history_rows([_make_run(status="failure")])
    assert rows[0]["status"] == "failure"
    assert rows[0]["raw_status"] == "failure"

# test_build_history_rows_cost_formatted and test_build_history_rows_no_cost_is_dash
# stay as-is — cost is still in the row data (used by drawer), just not in table columns.
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dashboard_formatters.py -v -k "history_rows_status"`
Expected: FAIL — status still contains emoji

- [ ] **Step 3: Update `build_history_rows` and `_HISTORY_COLS`**

In `src/agents/dashboard_formatters.py`, update `build_history_rows`:

1. Change the `"status"` field from `STATUS_ICONS.get(r.status, r.status)` to `r.status`.
2. **Remove `STATUS_ICONS` constant** — no longer referenced after this change.

```python
        rows.append(
            {
                "id": r.id,
                "project": r.project,
                "task": r.task,
                "status": r.status,
                "raw_status": r.status,
                "model": r.model or "—",
                "cost": f"${r.cost_usd:.3f}" if r.cost_usd else "—",
                "duration": duration,
                "trigger": r.trigger_type,
                "pr_url": r.pr_url or "",
            }
        )
```

In `src/agents/dashboard.py`, update `_HISTORY_COLS` — remove `model` and `cost`:

```python
_HISTORY_COLS = [
    {"name": "project", "label": "Project", "field": "project", "align": "left"},
    {"name": "task", "label": "Task", "field": "task", "align": "left"},
    {"name": "status", "label": "", "field": "status", "align": "center"},
    {"name": "duration", "label": "Time", "field": "duration", "align": "right"},
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dashboard_formatters.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/dashboard_formatters.py src/agents/dashboard.py tests/test_dashboard_formatters.py
git commit -m "refactor(formatters): use raw status string, simplify history columns"
```

---

## Chunk 2: Dashboard UI Restructure

### Task 5: Rewrite `_DASHBOARD_CSS`

Replace the CSS to support the new layout: compact header, two full-height panels, status dots, trigger popover.

**Files:**
- Modify: `src/agents/dashboard.py:25-58` (_DASHBOARD_CSS)

- [ ] **Step 1: Replace `_DASHBOARD_CSS`**

```python
_DASHBOARD_CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap"
      rel="stylesheet">
<style>
body { background: #0f1117 !important; font-family: 'JetBrains Mono', monospace; }
.nicegui-content { padding: 0 !important; }
.header-row {
    background: #1a1d27 !important;
    border-bottom: 1px solid #2d3142;
    min-height: 48px;
}
.header-divider {
    width: 1px; height: 20px; background: #2d3142;
}
.status-dot {
    display: inline-block; width: 6px; height: 6px;
    border-radius: 50%; flex-shrink: 0;
}
.status-dot.running, .status-dot.active { background: #3b82f6; }
.status-dot.success { background: #4ade80; }
.status-dot.failure, .status-dot.failed { background: #f87171; }
.status-dot.timeout { background: #fb923c; }
.status-dot.cancelled { background: #6b7280; }
.panel-divider {
    width: 1px; background: #2d3142; flex-shrink: 0;
}
.section-label {
    font-size: 9px; color: #6b7280; text-transform: uppercase;
    letter-spacing: 1px; padding: 8px 12px;
    border-bottom: 1px solid #1e2130;
}
.q-table { background: transparent !important; }
.q-table thead tr th {
    background: #0f1117 !important; color: #6b7280 !important;
    font-size: 11px; font-family: 'JetBrains Mono', monospace;
}
.q-table tbody tr { cursor: pointer; }
.q-table tbody tr:hover td { background: #1e2130 !important; }
.run-drawer .q-dialog__inner {
    position: fixed !important;
    right: 0 !important; top: 0 !important; bottom: 0 !important;
    margin: 0 !important;
    max-height: 100vh !important; height: 100vh !important;
    width: 560px !important; max-width: 560px !important;
}
.run-drawer .q-card {
    border-radius: 0 !important; height: 100% !important;
    background: #0d0f18 !important;
    border-left: 1px solid #2d3142 !important;
    box-shadow: -8px 0 32px rgba(0,0,0,0.6) !important;
}
@keyframes live-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
.live-pulse { animation: live-pulse 1.4s ease-in-out infinite; }
.trigger-menu .q-card {
    background: #1a1d27 !important;
    border: 1px solid #2d3142 !important;
}
</style>
"""
```

- [ ] **Step 2: Run existing tests to verify nothing breaks**

Run: `python -m pytest tests/test_dashboard.py tests/test_dashboard_formatters.py -v`
Expected: ALL PASS (CSS is static string, no logic change)

- [ ] **Step 3: Commit**

```bash
git add src/agents/dashboard.py
git commit -m "refactor(dashboard): rewrite CSS for compact header and two-panel layout"
```

---

### Task 6: Restructure dashboard layout

Rewrite the `dashboard_page` function body: compact header with inline stats + budget + trigger, two full-height panels (stream + history), remove stat cards / scheduled tasks / stream badge.

**Files:**
- Modify: `src/agents/dashboard.py:164-401`
- Modify: `tests/test_dashboard.py`

This is the largest task. The key changes:

1. Header: single row with title, DRY RUN badge, inline Active/Failed counts, budget, trigger button + q-menu popover
2. Body: two-panel flex layout replacing the current multi-section layout
3. Live stream: `ui.scroll_area` + `ui.column` + `ui.html` instead of `ui.log`
4. History: same `ui.table` but using simplified `_HISTORY_COLS`
5. Remove: stat cards section, scheduled tasks section, stream badge
6. `drain_queue()`: append `ui.html(format_stream_html(data))` instead of `log_area.push()`
7. `refresh()`: update only active count, failed count, budget, history table
8. Trigger: `ui.button` + `ui.element('q-menu')` with project/task selectors

- [ ] **Step 1: Update ALL dashboard tests**

The new layout uses `ui.scroll_area`, `ui.column`, `ui.element`, `ui.html` instead of `ui.log` and stat cards. **Every test that renders the page** needs updated mocks. Create a shared mock helper and update all tests:

```python
# tests/test_dashboard.py — add a shared helper at the top (after _make_state_and_config):

def _make_dashboard_ui_mock():
    """Return a MagicMock for ui that handles all new dashboard components."""
    mock_ui = MagicMock()
    # Context managers
    for attr in ("row", "column", "card", "element", "scroll_area"):
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.classes.return_value = ctx
        ctx.style.return_value = ctx
        getattr(mock_ui, attr).return_value = ctx
    # Simple returns
    mock_ui.label.return_value = MagicMock()
    mock_ui.html.return_value = MagicMock()
    mock_ui.linear_progress.return_value = MagicMock()
    mock_ui.badge.return_value = MagicMock()
    mock_table = MagicMock()
    mock_table.classes.return_value = mock_table
    mock_table.style.return_value = mock_table
    mock_ui.table.return_value = mock_table
    mock_ui.select.return_value = MagicMock()
    mock_ui.button.return_value = MagicMock()
    mock_ui.timer.return_value = MagicMock()
    mock_ui.dialog.return_value = MagicMock()
    return mock_ui
```

Then update **every test** that calls `captured_page_fn` to use `_make_dashboard_ui_mock()` instead of manual mocking. This includes:
- `test_dashboard_page_renders_budget_header` → rename to `test_dashboard_page_renders_header_with_stats`
- `test_dashboard_page_uses_dark_mode`
- `test_on_row_click_falls_back_to_sqlite_when_not_in_memory`
- `test_on_row_click_prefers_memory_events_over_sqlite`
- `test_dashboard_page_registers_auto_refresh_timer`

Each test replaces its manual `mock_ui` setup with:
```python
    with patch("agents.dashboard.ui") as mock_ui:
        helper = _make_dashboard_ui_mock()
        # Copy all attributes from helper to mock_ui
        for attr in dir(helper):
            if not attr.startswith('_'):
                try:
                    setattr(mock_ui, attr, getattr(helper, attr))
                except AttributeError:
                    pass
        # ... rest of the test
```

Or more simply, use `_make_dashboard_ui_mock` to configure the mock:
```python
    mock_ui = _make_dashboard_ui_mock()
    with patch("agents.dashboard.ui", mock_ui):
        # ... test body
```

- [ ] **Step 2: Run tests to verify current state**

Run: `python -m pytest tests/test_dashboard.py -v`
Note which tests pass/fail. Some will fail because the mock structure changed.

- [ ] **Step 3: Rewrite the `dashboard_page` function**

Replace the body of `dashboard_page` (lines 168-398) with the new layout. Key structure:

```python
@ui.page("/dashboard")
async def dashboard_page(client: Client) -> None:
    ui.dark_mode(True)
    ui.add_head_html(_DASHBOARD_CSS)

    runs = state.history.list_runs_today()
    a_count = sum(1 for r in runs if r.status == "running")
    f_count = sum(1 for r in runs if r.status in ("failure", "timeout"))

    # ── Header ──────────────────────────────────────────────────────
    with ui.row().classes("header-row w-full items-center justify-between px-4 py-2"):
        with ui.row().classes("items-center gap-3"):
            ui.label("Agent Runner").classes("text-base font-bold text-white")
            if config.execution.dry_run:
                ui.badge("DRY RUN").props("color=orange").classes("text-xs font-mono")

            ui.html('<div class="header-divider"></div>')

            # Inline stats
            with ui.row().classes("items-center gap-3"):
                active_dot = ui.html(
                    f'<span class="status-dot active{" live-pulse" if a_count > 0 else ""}"'
                    f' style="{("" if a_count > 0 else "opacity:0.4")}"></span>'
                )
                stat_active = ui.label(f"{a_count} active").classes(
                    f"text-xs font-mono {'text-gray-400' if a_count > 0 else 'text-gray-600'}"
                )
                failed_dot = ui.html(
                    f'<span class="status-dot failed"'
                    f' style="{("" if f_count > 0 else "opacity:0.4")}"></span>'
                )
                stat_failed = ui.label(f"{f_count} failed").classes(
                    f"text-xs font-mono {'text-red-300' if f_count > 0 else 'text-gray-600'}"
                )

        with ui.row().classes("items-center gap-3"):
            budget = state.budget.get_status()
            budget_label = ui.label(
                f"${budget.spent_today_usd:.2f} / ${budget.daily_limit_usd:.2f}"
            ).classes("text-xs text-gray-400 font-mono")
            ratio = (
                budget.spent_today_usd / budget.daily_limit_usd
                if budget.daily_limit_usd > 0
                else 0.0
            )
            bar_color = "red" if ratio >= 1.0 else "orange" if ratio >= 0.8 else "blue"
            budget_bar = ui.linear_progress(
                value=min(ratio, 1.0), show_value=False
            ).classes("w-24").props(f"color={bar_color} size=4px")

            # Trigger button + popover
            trigger_btn = ui.button("Run", icon="play_arrow").props(
                "flat dense size=sm color=grey"
            )
            with trigger_btn:
                with ui.element("q-menu").classes("trigger-menu"):
                    with ui.card().classes("p-3").style(
                        "background:#1a1d27;min-width:220px"
                    ):
                        project_names = sorted(state.projects.keys())
                        project_sel = ui.select(
                            project_names,
                            label="Project",
                            value=project_names[0] if project_names else None,
                        ).classes("w-full")
                        task_sel = ui.select([], label="Task").classes("w-full mt-1")
                        trigger_status = ui.label("").classes(
                            "text-xs text-gray-500 mt-1 font-mono"
                        )

                        def _init_tasks(proj_name: str | None) -> None:
                            project = state.projects.get(proj_name or "")
                            if project:
                                names = list(project.tasks.keys())
                                task_sel.options = names
                                task_sel.value = names[0] if names else None
                                task_sel.update()

                        project_sel.on_value_change(lambda e: _init_tasks(e.value))
                        _init_tasks(project_names[0] if project_names else None)

                        async def trigger_run() -> None:
                            if not project_sel.value or not task_sel.value:
                                return
                            import httpx
                            trigger_status.set_text("triggering…")
                            try:
                                async with httpx.AsyncClient() as http:
                                    resp = await http.post(
                                        f"http://localhost:{config.server.port}"
                                        f"/tasks/{project_sel.value}/{task_sel.value}/run"
                                    )
                                if resp.status_code == 202:
                                    trigger_status.set_text(
                                        f"✓ {project_sel.value}/{task_sel.value}"
                                    )
                                else:
                                    trigger_status.set_text(f"error {resp.status_code}")
                            except Exception as exc:
                                trigger_status.set_text(f"error: {exc}")

                        ui.button("Run Task", on_click=trigger_run).props(
                            "color=primary dense size=sm"
                        ).classes("w-full mt-2")

    # ── Two Panels ──────────────────────────────────────────────────
    with ui.row().classes("w-full flex-1").style(
        "height: calc(100vh - 48px); overflow: hidden"
    ):
        # Live Stream
        with ui.column().classes("flex-1 h-full").style("flex: 1.2"):
            ui.label("Live Stream").classes("section-label")
            with ui.scroll_area().classes("flex-1 px-3 pb-2").style(
                "background: #0f1117"
            ) as stream_scroll:
                stream_col = ui.column().classes("w-full gap-0")
            with stream_col:
                ui.html(
                    "<div style='color:#4b5563;font-size:11px;font-family:monospace'>"
                    "— waiting for agent activity —</div>"
                )

        ui.html('<div class="panel-divider"></div>')

        # Run History
        with ui.column().classes("flex-1 h-full"):
            with ui.row().classes(
                "items-center justify-between section-label"
            ).style("border-bottom: 1px solid #1e2130"):
                ui.label("Run History").classes(
                    "text-xs text-gray-500 uppercase tracking-widest"
                ).style("padding:0")
                ui.label("click a row to inspect").classes("text-xs text-gray-700")
            history_table = ui.table(
                columns=_HISTORY_COLS,
                rows=build_history_rows(runs),
                row_key="id",
            ).classes("w-full text-xs flex-1")
            # Render status column as colored dot instead of raw text
            history_table.add_slot(
                "body-cell-status",
                '''
                <q-td :props="props" style="text-align:center">
                    <span :class="'status-dot ' + props.row.raw_status"
                          :style="props.row.raw_status === 'running' ? 'animation:live-pulse 1.4s infinite' : ''">
                    </span>
                </q-td>
                ''',
            )

    # ── Run detail drawer ──────────────────────────────────────────
    detail_dialog = ui.dialog().props("no-backdrop-dismiss").classes("run-drawer")
    detail_queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    detail_run_id_ref: list[str] = [""]

    def on_row_click(e: object) -> None:
        try:
            row = e.args[1]
            run_id = row.get("id", "")
            if run_id:
                memory_events = state.run_events.get(run_id)
                events = (
                    memory_events
                    if memory_events is not None
                    else state.history.list_events(run_id)
                )
                _build_run_drawer(
                    dialog=detail_dialog,
                    run_id=run_id,
                    row=row,
                    existing_events=events,
                    detail_queue=detail_queue,
                    detail_run_id_ref=detail_run_id_ref,
                )
        except Exception:
            pass

    history_table.on("rowClick", on_row_click)

    # ── Global live stream queue ───────────────────────────────────
    queue: asyncio.Queue = asyncio.Queue(maxsize=500)
    state.stream_queues.append(queue)

    max_stream_lines = 200
    stream_line_count = [0]

    def drain_queue() -> None:
        while not queue.empty():
            with contextlib.suppress(asyncio.QueueEmpty):
                data = queue.get_nowait()
                if detail_run_id_ref[0] == data.get("run_id"):
                    with contextlib.suppress(asyncio.QueueFull):
                        detail_queue.put_nowait(data)
                # Clear placeholder on first real event
                if stream_line_count[0] == 0:
                    stream_col.clear()
                with stream_col:
                    ui.html(format_stream_html(data))
                stream_line_count[0] += 1
                # Cap lines by removing oldest
                if stream_line_count[0] > max_stream_lines:
                    children = list(stream_col)
                    if children:
                        stream_col.remove(children[0])
                        stream_line_count[0] -= 1
                stream_scroll.scroll_to(percent=1.0)

    ui.timer(0.15, drain_queue)

    async def refresh() -> None:
        updated = state.history.list_runs_today()
        ac = sum(1 for r in updated if r.status == "running")
        fc = sum(1 for r in updated if r.status in ("failure", "timeout"))
        stat_active.set_text(f"{ac} active")
        stat_failed.set_text(f"{fc} failed")
        b = state.budget.get_status()
        budget_label.set_text(
            f"${b.spent_today_usd:.2f} / ${b.daily_limit_usd:.2f}"
        )
        r = (
            b.spent_today_usd / b.daily_limit_usd
            if b.daily_limit_usd > 0
            else 0.0
        )
        budget_bar.set_value(min(r, 1.0))
        bar_color = "red" if r >= 1.0 else "orange" if r >= 0.8 else "blue"
        budget_bar.props(f"color={bar_color} size=4px")
        history_table.rows = build_history_rows(updated)
        history_table.update()

    ui.timer(3.0, refresh)

    def _cleanup() -> None:
        if queue in state.stream_queues:
            state.stream_queues.remove(queue)

    client.on_disconnect(_cleanup)
```

Add `format_stream_html` to the imports at the top of `dashboard.py`:

```python
from agents.dashboard_formatters import (
    STATUS_COLORS,
    build_history_rows,
    format_event_html,
    format_stream_html,
)
```

Note: `format_event_line` is removed from this import — it's no longer used in the dashboard (stream now uses `format_stream_html`). The function is kept in `dashboard_formatters.py` for potential plain-text consumers.

- [ ] **Step 4: Run all tests**

Run: `python -m pytest tests/test_dashboard.py tests/test_dashboard_formatters.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/dashboard.py tests/test_dashboard.py
git commit -m "feat(dashboard): restructure to compact header + two-panel layout"
```

---

### Task 7: Final verification

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Run linter**

Run: `python -m ruff check src/agents/dashboard.py src/agents/dashboard_formatters.py`
Expected: No errors

- [ ] **Step 3: Run type check if available**

Run: `python -m mypy src/agents/dashboard.py src/agents/dashboard_formatters.py --ignore-missing-imports 2>/dev/null || true`

- [ ] **Step 4: Verify no unused imports**

Check that `format_event_line` is still imported in `dashboard.py` only if used. After the rewrite, the stream uses `format_stream_html` — `format_event_line` may no longer be needed in dashboard.py. If so, remove it from the import.

- [ ] **Step 5: Final commit if any cleanup needed**

```bash
git add -u
git commit -m "chore: final cleanup after dashboard refinement"
```
