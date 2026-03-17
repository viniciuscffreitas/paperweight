# HTMX Frontend Migration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace NiceGUI/Quasar dashboard with HTMX + Jinja2 + Tailwind CDN + vanilla JS, eliminating the persistent right-panel width bug caused by Quasar's `QDialog` teleportation.

**Architecture:** FastAPI serves HTML fragments via Jinja2 templates; HTMX handles panel swaps and tab navigation; a `position:fixed` div (not a dialog) implements the right panel with full CSS control. WebSocket streaming is handled by ~60 LOC of vanilla JS (`static/ws.js`).

**Tech Stack:** FastAPI, Jinja2, HTMX 2.x CDN, Tailwind CSS CDN, Ubuntu Mono (Google Fonts), vanilla JS WebSocket, python-multipart, httpx (TestClient)

---

## Chunk 1: Foundation

### Task 1: Add dependencies to pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add jinja2 and python-multipart**

Open `pyproject.toml` and add to the `dependencies` list (alongside existing `fastapi>=0.115`):

```toml
"jinja2>=3.1",
"python-multipart>=0.0.9",
```

> NiceGUI (`nicegui>=2.5,<3`) stays in for now — it will be removed in Chunk 4.

- [ ] **Step 2: Run uv sync**

```bash
uv sync
```

Expected: no errors, `jinja2` and `python-multipart` resolved.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add jinja2 and python-multipart for HTMX migration"
```

---

### Task 2: Create static and templates directories

**Files:**
- Create: `src/agents/static/.gitkeep`
- Create: `src/agents/templates/hub/.gitkeep`
- Create: `src/agents/templates/partials/.gitkeep`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p src/agents/static
mkdir -p src/agents/templates/hub
mkdir -p src/agents/templates/partials
touch src/agents/static/.gitkeep
touch src/agents/templates/hub/.gitkeep
touch src/agents/templates/partials/.gitkeep
```

- [ ] **Step 2: Commit**

```bash
git add src/agents/static/ src/agents/templates/
git commit -m "chore: scaffold static and templates directories"
```

---

### Task 3: Create ws.js (WebSocket streaming)

**Files:**
- Create: `src/agents/static/ws.js`

- [ ] **Step 1: Write ws.js**

Create `src/agents/static/ws.js`:

```javascript
// WebSocket streaming helpers — per-run and global broadcast
function connectRunStream(runId, targetId) {
  var el = document.getElementById(targetId);
  if (!el) return null;
  var url = runId ? '/ws/runs/' + runId : '/ws/runs';
  var ws = new WebSocket(url);
  ws.onmessage = function(e) {
    el.textContent += e.data;
    el.scrollTop = el.scrollHeight;
  };
  ws.onerror = function() {
    el.textContent += '\n[connection error]';
  };
  return ws;
}

function connectGlobalStream(targetId) {
  return connectRunStream('', targetId);
}
```

- [ ] **Step 2: Commit**

```bash
git add src/agents/static/ws.js
git commit -m "feat(htmx): add vanilla JS WebSocket streaming helper"
```

---

### Task 4: Create base.html shell

**Files:**
- Create: `src/agents/templates/base.html`

- [ ] **Step 1: Write base.html**

Create `src/agents/templates/base.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>paperweight</title>
  <script src="https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js"></script>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Ubuntu+Mono:wght@400;700&display=swap" rel="stylesheet">
  <link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
  <script src="/static/ws.js"></script>
  <script>
    tailwind.config = {
      theme: {
        extend: {
          fontFamily: { mono: ['"Ubuntu Mono"', 'monospace'] }
        }
      }
    }
  </script>
  <style>
    * { font-family: "Ubuntu Mono", monospace; }
    html, body { margin: 0; padding: 0; height: 100%; background: #0d0f18; color: #e5e7eb; }
    .status-dot { display:inline-block; width:8px; height:8px; border-radius:50%; flex-shrink:0; }
    .status-dot.running  { background: #3b82f6; }
    .status-dot.success  { background: #4ade80; }
    .status-dot.failure,
    .status-dot.failed   { background: #f87171; }
    .status-dot.timeout  { background: #fb923c; }
    .status-dot.cancelled{ background: #6b7280; }
    @keyframes live-pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
    .live-pulse { animation: live-pulse 1.4s ease-in-out infinite; }
  </style>
</head>
<body class="flex h-screen overflow-hidden">

  <!-- Sidebar -->
  <nav style="width:160px;min-width:160px;background:#0d0f18;border-right:1px solid #1e2130;display:flex;flex-direction:column;flex-shrink:0;">
    <div style="padding:16px 12px;border-bottom:1px solid #1e2130;">
      <span style="font-size:11px;font-weight:700;letter-spacing:2px;color:#6b7280;text-transform:uppercase;">paperweight</span>
    </div>
    <div style="padding:8px 0;flex:1;overflow-y:auto;">
      <div style="padding:4px 12px;font-size:9px;color:#4b5563;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:4px;">Projects</div>
      {% for p in projects %}
      <div hx-get="/hub/{{ p.id }}"
           hx-target="#panel-content"
           hx-on::after-request="openPanel()"
           style="padding:8px 12px;font-size:12px;color:#9ca3af;cursor:pointer;border-radius:4px;margin:1px 6px;transition:background .15s;"
           onmouseover="this.style.background='#1e2130';this.style.color='#e5e7eb'"
           onmouseout="this.style.background='transparent';this.style.color='#9ca3af'">
        {{ p.name }}
      </div>
      {% endfor %}
    </div>
    <div style="padding:8px 12px;border-top:1px solid #1e2130;">
      <a href="/dashboard" style="font-size:11px;color:#4b5563;text-decoration:none;letter-spacing:.5px;">Dashboard</a>
    </div>
  </nav>

  <!-- Main content -->
  <main style="flex:1;overflow:hidden;display:flex;flex-direction:column;">
    {% block content %}{% endblock %}
  </main>

  <!-- Right panel (position:fixed, full viewport height minus sidebar) -->
  <!-- Note: display:none via inline style only — no Tailwind 'hidden' class so JS style toggle works -->
  <div id="right-panel"
       style="display:none;position:fixed;top:0;bottom:0;right:0;left:160px;
              background:#0d0f18;border-left:1px solid #2d3142;
              z-index:50;flex-direction:column;">
    <div id="panel-content" style="display:flex;flex-direction:column;height:100%;"></div>
  </div>

  <script>
    function openPanel() {
      var p = document.getElementById('right-panel');
      p.style.display = 'flex';
    }
    function closePanel() {
      var p = document.getElementById('right-panel');
      p.style.display = 'none';
    }
  </script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add src/agents/templates/base.html
git commit -m "feat(htmx): add base.html shell with sidebar and fixed right panel"
```

---

### Task 5: Create dashboard_html.py skeleton

**Files:**
- Create: `src/agents/dashboard_html.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_dashboard_html.py`:

```python
"""Tests for HTMX dashboard HTML routes."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agents.app_state import AppState
from agents.config import GlobalConfig
from agents.dashboard_html import setup_dashboard
from fastapi import FastAPI


@pytest.fixture()
def app_with_dashboard(tmp_path):
    """Create a minimal FastAPI app with dashboard routes mounted."""
    from agents.config import GlobalConfig
    app = FastAPI()
    state = AppState.__new__(AppState)
    state.__init__()
    config = GlobalConfig()
    setup_dashboard(app, state, config)
    return TestClient(app)


def test_dashboard_returns_200(app_with_dashboard):
    resp = app_with_dashboard.get("/dashboard")
    assert resp.status_code == 200


def test_dashboard_contains_sidebar(app_with_dashboard):
    resp = app_with_dashboard.get("/dashboard")
    assert b"paperweight" in resp.content
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_dashboard_html.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'agents.dashboard_html'`

- [ ] **Step 3: Write minimal dashboard_html.py**

Create `src/agents/dashboard_html.py`:

```python
"""HTMX + Jinja2 dashboard — replaces NiceGUI dashboard*.py files."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

if TYPE_CHECKING:
    from fastapi import FastAPI
    from agents.app_state import AppState
    from agents.config import GlobalConfig

_BASE = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=_BASE / "templates")


def setup_dashboard(app: "FastAPI", state: "AppState", config: "GlobalConfig") -> None:
    """Mount static files and register all HTML routes."""
    app.mount("/static", StaticFiles(directory=_BASE / "static"), name="static")

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard_page(request: Request) -> HTMLResponse:
        projects = state.project_store.list_projects()
        runs = []
        try:
            from agents.dashboard_formatters import build_history_rows
            runs = build_history_rows(state.history.list_runs_today())
        except Exception:
            pass
        return _TEMPLATES.TemplateResponse(
            "dashboard.html",
            {"request": request, "projects": projects, "runs": runs},
        )

    @app.get("/hub/{project_id}", response_class=HTMLResponse)
    async def hub_panel(request: Request, project_id: str) -> HTMLResponse:
        project = state.project_store.get_project(project_id)
        if not project:
            return HTMLResponse("<p>Project not found</p>", status_code=404)
        return _TEMPLATES.TemplateResponse(
            "hub/panel.html",
            {"request": request, "project": project, "id": project_id},
        )

    @app.get("/hub/{project_id}/activity", response_class=HTMLResponse)
    async def hub_activity(request: Request, project_id: str) -> HTMLResponse:
        project = state.project_store.get_project(project_id)
        if not project:
            return HTMLResponse("<p>Project not found</p>", status_code=404)
        events = state.project_store.list_events(project_id, limit=50)
        return _TEMPLATES.TemplateResponse(
            "hub/activity.html",
            {"request": request, "events": events, "id": project_id},
        )

    @app.get("/hub/{project_id}/tasks", response_class=HTMLResponse)
    async def hub_tasks(request: Request, project_id: str) -> HTMLResponse:
        project = state.project_store.get_project(project_id)
        if not project:
            return HTMLResponse("<p>Project not found</p>", status_code=404)
        tasks = state.project_store.list_tasks(project_id)
        return _TEMPLATES.TemplateResponse(
            "hub/tasks.html",
            {"request": request, "tasks": tasks, "id": project_id},
        )

    @app.get("/hub/{project_id}/runs", response_class=HTMLResponse)
    async def hub_runs(request: Request, project_id: str) -> HTMLResponse:
        project = state.project_store.get_project(project_id)
        if not project:
            return HTMLResponse("<p>Project not found</p>", status_code=404)
        try:
            all_runs = state.history.list_runs_today()
            runs = [r for r in all_runs if r.project == project_id][:20]
        except Exception:
            runs = []
        return _TEMPLATES.TemplateResponse(
            "hub/runs.html",
            {"request": request, "runs": runs, "id": project_id},
        )
```

- [ ] **Step 4: Create placeholder templates so routes don't error**

Create `src/agents/templates/dashboard.html`:

```html
{% extends "base.html" %}
{% block content %}
<div id="dashboard-placeholder">dashboard</div>
{% endblock %}
```

Create `src/agents/templates/hub/panel.html`:

```html
<div id="hub-panel-placeholder">{{ project.name }}</div>
```

Create `src/agents/templates/hub/activity.html`:

```html
<div id="activity-placeholder">activity</div>
```

Create `src/agents/templates/hub/tasks.html`:

```html
<div id="tasks-placeholder">tasks</div>
```

Create `src/agents/templates/hub/runs.html`:

```html
<div id="runs-placeholder">runs</div>
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_dashboard_html.py -v
```

Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add src/agents/dashboard_html.py src/agents/templates/ tests/test_dashboard_html.py
git commit -m "feat(htmx): add dashboard_html.py skeleton with all routes and placeholder templates"
```

---

## Chunk 2: Dashboard Page

### Task 6: Build dashboard.html (run history + live stream)

**Files:**
- Modify: `src/agents/templates/dashboard.html`
- Modify: `tests/test_dashboard_html.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_dashboard_html.py`:

```python
def test_dashboard_contains_run_table(app_with_dashboard):
    """Dashboard page renders the run history table structure."""
    resp = app_with_dashboard.get("/dashboard")
    assert resp.status_code == 200
    assert b"run-history" in resp.content


def test_dashboard_contains_live_stream_section(app_with_dashboard):
    """Dashboard page contains the live stream pre element."""
    resp = app_with_dashboard.get("/dashboard")
    assert b"live-stream-output" in resp.content


def test_dashboard_with_project_names_in_sidebar(tmp_path):
    """Dashboard sidebar lists projects when they exist."""
    from fastapi import FastAPI
    from agents.app_state import AppState
    from agents.config import GlobalConfig
    from agents.dashboard_html import setup_dashboard

    app = FastAPI()
    state = AppState.__new__(AppState)
    state.__init__()
    # Add a project
    state.project_store.add_project("proj-1", "My Project", repo_url="https://github.com/x/y")
    config = GlobalConfig()
    setup_dashboard(app, state, config)
    client = TestClient(app)

    resp = client.get("/dashboard")
    assert b"My Project" in resp.content
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_dashboard_html.py::test_dashboard_contains_run_table tests/test_dashboard_html.py::test_dashboard_contains_live_stream_section -v
```

Expected: FAIL — response doesn't contain `run-history` or `live-stream-output`

- [ ] **Step 3: Write full dashboard.html**

Replace `src/agents/templates/dashboard.html`:

```html
{% extends "base.html" %}
{% block content %}

<!-- Dashboard header -->
<div style="padding:12px 20px;border-bottom:1px solid #1e2130;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;">
  <div style="display:flex;align-items:center;gap:8px;">
    <span class="live-pulse status-dot running"></span>
    <span style="font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:#6b7280;">Live</span>
  </div>
  <span style="font-size:11px;color:#4b5563;">today</span>
</div>

<!-- Run history table -->
<div style="flex:1;overflow-y:auto;padding:16px;" id="run-history">
  {% if runs %}
  <table style="width:100%;border-collapse:collapse;font-size:12px;">
    <thead>
      <tr style="border-bottom:1px solid #1e2130;">
        <th style="text-align:left;padding:6px 8px;color:#6b7280;font-weight:400;font-size:10px;text-transform:uppercase;letter-spacing:1px;">Status</th>
        <th style="text-align:left;padding:6px 8px;color:#6b7280;font-weight:400;font-size:10px;text-transform:uppercase;letter-spacing:1px;">Project</th>
        <th style="text-align:left;padding:6px 8px;color:#6b7280;font-weight:400;font-size:10px;text-transform:uppercase;letter-spacing:1px;">Task</th>
        <th style="text-align:left;padding:6px 8px;color:#6b7280;font-weight:400;font-size:10px;text-transform:uppercase;letter-spacing:1px;">Model</th>
        <th style="text-align:left;padding:6px 8px;color:#6b7280;font-weight:400;font-size:10px;text-transform:uppercase;letter-spacing:1px;">Duration</th>
        <th style="text-align:left;padding:6px 8px;color:#6b7280;font-weight:400;font-size:10px;text-transform:uppercase;letter-spacing:1px;">Cost</th>
        <th style="text-align:left;padding:6px 8px;color:#6b7280;font-weight:400;font-size:10px;text-transform:uppercase;letter-spacing:1px;">PR</th>
      </tr>
    </thead>
    <tbody>
      {% for r in runs %}
      <tr style="border-bottom:1px solid #1a1d27;cursor:pointer;"
          onmouseover="this.style.background='#1e2130'"
          onmouseout="this.style.background='transparent'">
        <td style="padding:8px 8px;">
          <span class="status-dot {{ r.raw_status }}"></span>
        </td>
        <td style="padding:8px 8px;color:#9ca3af;">{{ r.project }}</td>
        <td style="padding:8px 8px;color:#e5e7eb;">{{ r.task }}</td>
        <td style="padding:8px 8px;color:#6b7280;">{{ r.model }}</td>
        <td style="padding:8px 8px;color:#6b7280;">{{ r.duration }}</td>
        <td style="padding:8px 8px;color:#6b7280;">{{ r.cost }}</td>
        <td style="padding:8px 8px;">
          {% if r.pr_url %}
          <a href="{{ r.pr_url }}" target="_blank" style="color:#3b82f6;text-decoration:none;font-size:11px;">PR ↗</a>
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <div style="padding:32px;text-align:center;color:#4b5563;font-size:13px;font-style:italic;">
    No runs today
  </div>
  {% endif %}
</div>

<!-- Live stream panel -->
<div style="height:180px;flex-shrink:0;border-top:1px solid #1e2130;display:flex;flex-direction:column;">
  <div style="padding:6px 16px;font-size:9px;color:#6b7280;text-transform:uppercase;letter-spacing:1.5px;border-bottom:1px solid #1e2130;flex-shrink:0;">
    Live Stream
  </div>
  <pre id="live-stream-output"
       style="flex:1;overflow-y:auto;padding:8px 16px;margin:0;font-size:11px;color:#4ade80;background:transparent;white-space:pre-wrap;word-break:break-all;"></pre>
</div>

<script>
  // Connect to global broadcast stream on page load
  document.addEventListener('DOMContentLoaded', function() {
    connectGlobalStream('live-stream-output');
  });
</script>
{% endblock %}
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_dashboard_html.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/templates/dashboard.html tests/test_dashboard_html.py
git commit -m "feat(htmx): implement dashboard.html with run history table and live stream"
```

---

## Chunk 3: Project Hub Panel

### Task 7: Build partials (event_card, task_row, run_row)

**Files:**
- Create: `src/agents/templates/partials/event_card.html`
- Create: `src/agents/templates/partials/task_row.html`
- Create: `src/agents/templates/partials/run_row.html`

- [ ] **Step 1: Create event_card.html partial**

Create `src/agents/templates/partials/event_card.html`:

```html
{% set source_icons = {"linear": "task_alt", "github": "code", "slack": "chat", "paperweight": "smart_toy"} %}
{% set source_colors = {"linear": "#5E6AD2", "github": "#238636", "slack": "#4A154B", "paperweight": "#F97316"} %}
{% set priority_colors = {"urgent": "#EF4444", "high": "#F59E0B", "medium": "#3B82F6", "low": "#6B7280"} %}

<div style="display:flex;align-items:center;gap:8px;padding:6px 4px;border-radius:4px;cursor:default;"
     onmouseover="this.style.background='#1a1d27'"
     onmouseout="this.style.background='transparent'">
  <span class="material-icons" style="font-size:16px;color:{{ source_colors.get(event.source, '#666') }};flex-shrink:0;">
    {{ source_icons.get(event.source, 'info') }}
  </span>
  {% if event.priority and event.priority != 'none' %}
  <span style="font-size:10px;padding:1px 5px;border-radius:3px;flex-shrink:0;
               background:{{ priority_colors.get(event.priority, '#374151') }};color:#fff;">
    {{ event.priority | upper }}
  </span>
  {% endif %}
  <span style="flex:1;font-size:12px;color:#e5e7eb;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
    {{ event.title | default('') }}
  </span>
  <span style="font-size:11px;color:#4b5563;flex-shrink:0;white-space:nowrap;">
    {{ (event.timestamp | default(''))[:16] | replace('T', ' ') }}
  </span>
  {% if event.author %}
  <span style="font-size:11px;color:#6b7280;flex-shrink:0;">{{ event.author }}</span>
  {% endif %}
</div>
```

- [ ] **Step 2: Create task_row.html partial**

Create `src/agents/templates/partials/task_row.html`:

```html
{% set bg = "#1a1d27" if task.get("enabled", 1) else "#12151f" %}
<div style="display:flex;align-items:center;padding:8px 12px;border-radius:6px;background:{{ bg }};gap:8px;">
  <div style="flex:1;min-width:0;">
    <div style="font-size:13px;color:#e5e7eb;">{{ task.name }}</div>
    <div style="font-size:11px;color:#6b7280;margin-top:2px;">
      {{ task.trigger_type }} · {{ task.model }} · ${{ "%.2f" | format(task.max_budget) }}
    </div>
  </div>
  <span style="font-size:10px;padding:2px 6px;border-radius:3px;
               background:{{ '#1a3a1a' if task.get('enabled', 1) else '#2a1a1a' }};
               color:{{ '#4ade80' if task.get('enabled', 1) else '#f87171' }};">
    {{ 'ON' if task.get('enabled', 1) else 'OFF' }}
  </span>
</div>
```

- [ ] **Step 3: Create run_row.html partial**

Create `src/agents/templates/partials/run_row.html`:

```html
{% set status_colors = {"success": "#4ade80", "failure": "#f87171", "running": "#3b82f6", "timeout": "#fb923c", "cancelled": "#6b7280"} %}
<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #1e2130;">
  <span class="status-dot {{ run.status }}" style="background:{{ status_colors.get(run.status, '#6b7280') }};"></span>
  <span style="flex:1;font-size:12px;color:#e5e7eb;">{{ run.task }}</span>
  {% if run.cost_usd %}
  <span style="font-size:11px;color:#6b7280;">${{ "%.2f" | format(run.cost_usd) }}</span>
  {% endif %}
  {% if run.pr_url %}
  <a href="{{ run.pr_url }}" target="_blank" style="font-size:11px;color:#3b82f6;text-decoration:none;">PR ↗</a>
  {% endif %}
</div>
```

- [ ] **Step 4: Commit**

```bash
git add src/agents/templates/partials/
git commit -m "feat(htmx): add event_card, task_row, run_row partials"
```

---

### Task 8: Build hub panel templates

**Files:**
- Modify: `src/agents/templates/hub/panel.html`
- Modify: `src/agents/templates/hub/activity.html`
- Modify: `src/agents/templates/hub/tasks.html`
- Modify: `src/agents/templates/hub/runs.html`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_dashboard_html.py`:

```python
def test_hub_panel_404_for_missing_project(app_with_dashboard):
    resp = app_with_dashboard.get("/hub/nonexistent-id-xyz")
    assert resp.status_code == 404


def test_hub_panel_contains_project_name(tmp_path):
    from fastapi import FastAPI
    from agents.app_state import AppState
    from agents.config import GlobalConfig
    from agents.dashboard_html import setup_dashboard

    app = FastAPI()
    state = AppState.__new__(AppState)
    state.__init__()
    state.project_store.add_project("p1", "Test Project", repo_url="https://github.com/x/y")
    config = GlobalConfig()
    setup_dashboard(app, state, config)
    client = TestClient(app)

    resp = client.get("/hub/p1")
    assert resp.status_code == 200
    assert b"Test Project" in resp.content


def test_hub_panel_contains_tabs(tmp_path):
    from fastapi import FastAPI
    from agents.app_state import AppState
    from agents.config import GlobalConfig
    from agents.dashboard_html import setup_dashboard

    app = FastAPI()
    state = AppState.__new__(AppState)
    state.__init__()
    state.project_store.add_project("p1", "Test Project", repo_url="https://github.com/x/y")
    config = GlobalConfig()
    setup_dashboard(app, state, config)
    client = TestClient(app)

    resp = client.get("/hub/p1")
    assert b"ACTIVITY" in resp.content
    assert b"TASKS" in resp.content
    assert b"RUNS" in resp.content


def test_hub_activity_returns_200(tmp_path):
    from fastapi import FastAPI
    from agents.app_state import AppState
    from agents.config import GlobalConfig
    from agents.dashboard_html import setup_dashboard

    app = FastAPI()
    state = AppState.__new__(AppState)
    state.__init__()
    state.project_store.add_project("p1", "Test Project", repo_url="https://github.com/x/y")
    config = GlobalConfig()
    setup_dashboard(app, state, config)
    client = TestClient(app)

    resp = client.get("/hub/p1/activity")
    assert resp.status_code == 200


def test_hub_tasks_returns_200(tmp_path):
    from fastapi import FastAPI
    from agents.app_state import AppState
    from agents.config import GlobalConfig
    from agents.dashboard_html import setup_dashboard

    app = FastAPI()
    state = AppState.__new__(AppState)
    state.__init__()
    state.project_store.add_project("p1", "Test Project", repo_url="https://github.com/x/y")
    config = GlobalConfig()
    setup_dashboard(app, state, config)
    client = TestClient(app)

    resp = client.get("/hub/p1/tasks")
    assert resp.status_code == 200


def test_hub_runs_returns_200(tmp_path):
    from fastapi import FastAPI
    from agents.app_state import AppState
    from agents.config import GlobalConfig
    from agents.dashboard_html import setup_dashboard

    app = FastAPI()
    state = AppState.__new__(AppState)
    state.__init__()
    state.project_store.add_project("p1", "Test Project", repo_url="https://github.com/x/y")
    config = GlobalConfig()
    setup_dashboard(app, state, config)
    client = TestClient(app)

    resp = client.get("/hub/p1/runs")
    assert resp.status_code == 200
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_dashboard_html.py::test_hub_panel_contains_project_name tests/test_dashboard_html.py::test_hub_panel_contains_tabs -v
```

Expected: FAIL — placeholder templates don't have project name or tabs

- [ ] **Step 3: Write hub/panel.html**

Replace `src/agents/templates/hub/panel.html`:

```html
<!-- Hub panel: header + tabs + tab content area (loaded via HTMX) -->
<div style="display:flex;flex-direction:column;height:100%;">

  <!-- Panel header -->
  <div style="display:flex;align-items:center;justify-content:space-between;
              padding:0 20px;height:56px;min-height:56px;flex-shrink:0;
              border-bottom:1px solid #1e2130;">
    <span style="font-size:14px;font-weight:700;color:#e5e7eb;">{{ project.name }}</span>
    <div style="display:flex;align-items:center;gap:8px;">
      <button onclick="closePanel()"
              style="background:transparent;border:none;color:#6b7280;cursor:pointer;
                     padding:4px 8px;font-size:11px;font-family:inherit;
                     border-radius:3px;transition:color .15s;"
              onmouseover="this.style.color='#e5e7eb'"
              onmouseout="this.style.color='#6b7280'">✕</button>
    </div>
  </div>

  <!-- Tabs -->
  <div style="display:flex;border-bottom:1px solid #1e2130;padding:0 20px;flex-shrink:0;">
    <button hx-get="/hub/{{ id }}/activity"
            hx-target="#tab-content"
            style="padding:10px 16px;font-size:11px;text-transform:uppercase;letter-spacing:.8px;
                   color:#e5e7eb;cursor:pointer;border:none;background:transparent;
                   border-bottom:2px solid #3b82f6;margin-bottom:-1px;font-family:inherit;">
      ACTIVITY
    </button>
    <button hx-get="/hub/{{ id }}/tasks"
            hx-target="#tab-content"
            style="padding:10px 16px;font-size:11px;text-transform:uppercase;letter-spacing:.8px;
                   color:#4b5563;cursor:pointer;border:none;background:transparent;
                   border-bottom:2px solid transparent;margin-bottom:-1px;font-family:inherit;
                   transition:color .15s;"
            onmouseover="this.style.color='#9ca3af'"
            onmouseout="this.style.color='#4b5563'">
      TASKS
    </button>
    <button hx-get="/hub/{{ id }}/runs"
            hx-target="#tab-content"
            style="padding:10px 16px;font-size:11px;text-transform:uppercase;letter-spacing:.8px;
                   color:#4b5563;cursor:pointer;border:none;background:transparent;
                   border-bottom:2px solid transparent;margin-bottom:-1px;font-family:inherit;
                   transition:color .15s;"
            onmouseover="this.style.color='#9ca3af'"
            onmouseout="this.style.color='#4b5563'">
      RUNS
    </button>
  </div>

  <!-- Tab content — loaded via HTMX, defaults to activity -->
  <div id="tab-content"
       style="flex:1;overflow-y:auto;"
       hx-get="/hub/{{ id }}/activity"
       hx-trigger="load">
  </div>
</div>
```

- [ ] **Step 4: Write hub/activity.html**

Replace `src/agents/templates/hub/activity.html`:

```html
<div style="padding:16px;display:flex;flex-direction:column;gap:2px;">
  {% if events %}
    {% for event in events %}
      {% include "partials/event_card.html" %}
    {% endfor %}
  {% else %}
  <div style="padding:24px;text-align:center;color:#4b5563;font-size:13px;font-style:italic;">
    No events yet. Configure sources to start aggregating.
  </div>
  {% endif %}
</div>
```

- [ ] **Step 5: Write hub/tasks.html**

Replace `src/agents/templates/hub/tasks.html`:

```html
<div style="padding:16px;display:flex;flex-direction:column;gap:8px;">
  {% if tasks %}
    {% for task in tasks %}
      {% include "partials/task_row.html" %}
    {% endfor %}
  {% else %}
  <div style="padding:24px;text-align:center;color:#4b5563;font-size:13px;font-style:italic;">
    No tasks yet.
  </div>
  {% endif %}
</div>
```

- [ ] **Step 6: Write hub/runs.html**

Replace `src/agents/templates/hub/runs.html`:

```html
<div style="padding:16px;">
  {% if runs %}
    {% for run in runs %}
      {% include "partials/run_row.html" %}
    {% endfor %}
  {% else %}
  <div style="padding:24px;text-align:center;color:#4b5563;font-size:13px;font-style:italic;">
    No runs today.
  </div>
  {% endif %}
</div>
```

- [ ] **Step 7: Run all tests**

```bash
uv run pytest tests/test_dashboard_html.py -v
```

Expected: all tests PASS

- [ ] **Step 8: Commit**

```bash
git add src/agents/templates/hub/ tests/test_dashboard_html.py
git commit -m "feat(htmx): implement hub panel templates (panel, activity, tasks, runs)"
```

---

### Task 9: Wire main.py to dashboard_html

**Files:**
- Modify: `src/agents/main.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_dashboard_html.py`:

```python
def test_main_imports_dashboard_html_not_nicegui():
    """main.py must import from dashboard_html, not from dashboard (NiceGUI)."""
    import inspect
    from agents import main
    source = inspect.getsource(main)
    assert "from agents.dashboard_html import setup_dashboard" in source
    assert "from agents.dashboard import setup_dashboard" not in source
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_dashboard_html.py::test_main_imports_dashboard_html_not_nicegui -v
```

Expected: FAIL

- [ ] **Step 3: Update main.py**

In `src/agents/main.py`, find (around lines 402–403):

```python
from agents.dashboard import setup_dashboard
setup_dashboard(app, state, config)
```

Replace with:

```python
from agents.dashboard_html import setup_dashboard
setup_dashboard(app, state, config)
```

Also remove any `ui.run_with(app)` call if present (search with `grep -n "ui.run_with\|nicegui" src/agents/main.py`).

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_dashboard_html.py -v
```

Expected: all PASS

- [ ] **Step 5: Run full test suite (smoke check — some NiceGUI tests may fail, that's expected)**

```bash
uv run pytest tests/ -v --tb=no -q 2>&1 | tail -20
```

Note any failures — in Chunk 4 the NiceGUI tests will be deleted.

- [ ] **Step 6: Commit**

```bash
git add src/agents/main.py tests/test_dashboard_html.py
git commit -m "feat(htmx): wire main.py to dashboard_html.setup_dashboard"
```

---

## Chunk 4: Cutover

### Task 10: Remove NiceGUI and delete old dashboard files

**Files:**
- Delete: `src/agents/dashboard.py`
- Delete: `src/agents/dashboard_project_hub.py`
- Delete: `src/agents/dashboard_setup_wizard.py`
- Delete: `src/agents/dashboard_task_manager.py`
- Delete: `src/agents/dashboard_theme.py`
- Delete: `tests/test_dashboard.py` (if exists)
- Delete: `tests/agents/test_dashboard_project_hub.py`
- Delete: `tests/agents/test_dashboard_theme.py` (if exists)
- Delete: `tests/agents/test_dashboard_setup_wizard.py` (if exists)
- Delete: `tests/agents/test_dashboard_task_manager.py` (if exists)
- Modify: `pyproject.toml`

> **Before this task, verify** `uv run python -c "from agents.dashboard_html import setup_dashboard; print('ok')"` succeeds.

- [ ] **Step 1: Confirm server starts with new setup**

```bash
uv run python -c "
from fastapi import FastAPI
from agents.app_state import AppState
from agents.config import GlobalConfig
from agents.dashboard_html import setup_dashboard
app = FastAPI()
state = AppState()
config = GlobalConfig()
setup_dashboard(app, state, config)
print('dashboard_html setup OK')
"
```

Expected: prints `dashboard_html setup OK`

- [ ] **Step 2: Remove NiceGUI from pyproject.toml**

In `pyproject.toml`, delete the line:

```toml
"nicegui>=2.5,<3",
```

- [ ] **Step 3: Run uv sync**

```bash
uv sync
```

Expected: nicegui removed, no errors. If starlette version conflicts appear, uv resolves them automatically.

- [ ] **Step 4: Delete NiceGUI dashboard source files**

```bash
rm src/agents/dashboard.py
rm src/agents/dashboard_project_hub.py
rm src/agents/dashboard_setup_wizard.py
rm src/agents/dashboard_task_manager.py
rm src/agents/dashboard_theme.py
```

- [ ] **Step 5: Delete NiceGUI test files**

```bash
# Check which exist first
ls tests/test_dashboard.py tests/agents/test_dashboard_project_hub.py tests/agents/test_dashboard_theme.py tests/agents/test_dashboard_setup_wizard.py tests/agents/test_dashboard_task_manager.py 2>&1

# Delete those that exist
rm -f tests/test_dashboard.py
rm -f tests/agents/test_dashboard_project_hub.py
rm -f tests/agents/test_dashboard_theme.py
rm -f tests/agents/test_dashboard_setup_wizard.py
rm -f tests/agents/test_dashboard_task_manager.py
```

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest tests/ -v 2>&1 | tail -30
```

Expected: all remaining tests PASS. Key suites that must pass:
- `tests/test_dashboard_html.py` — all new HTML route tests
- `tests/test_dashboard_formatters.py` — kept unchanged, must PASS
- All API route tests, WebSocket tests, webhook tests

- [ ] **Step 7: Final commit**

```bash
git add -A
git commit -m "feat(htmx): complete NiceGUI → HTMX migration, remove nicegui dependency"
```

---

## Verification Checklist

After all chunks are complete, verify:

- [ ] `uv run pytest tests/ -v` — all tests pass
- [ ] `uv run python -c "from agents.main import run"` — no import errors
- [ ] `nicegui` not in `pyproject.toml` or `uv.lock`
- [ ] `dashboard_html.py` exists, old `dashboard*.py` files deleted
- [ ] `/dashboard` returns 200 with sidebar HTML
- [ ] `/hub/{id}` returns 200 with project name and ACTIVITY/TASKS/RUNS tabs
- [ ] `/hub/{id}/activity`, `/hub/{id}/tasks`, `/hub/{id}/runs` all return 200
- [ ] `/hub/nonexistent` returns 404
- [ ] `tests/test_dashboard_formatters.py` still passes (kept unchanged)
