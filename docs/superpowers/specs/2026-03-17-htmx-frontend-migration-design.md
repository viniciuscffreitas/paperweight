# Frontend Migration: NiceGUI → HTMX + Jinja2

**Date:** 2026-03-17
**Status:** Approved
**Scope:** Replace NiceGUI dashboard with HTMX + Jinja2 + Tailwind CDN + vanilla JS

---

## Context

The paperweight dashboard is built on NiceGUI (Python UI framework backed by Quasar/Vue). After 7
consecutive commits attempting to fix a right-panel width bug rooted in Quasar's `QDialog`
teleportation behavior, it is clear that NiceGUI is the wrong tool for this use case.

The dashboard is a monitoring/ops UI — predominantly server-rendered, read-only, with simple
actions (run, create task). HTMX + Jinja2 is the correct fit: full CSS control, no framework
fighting, zero build step.

---

## Architecture

```
Browser
  ├── HTMX 2.x (CDN)            — panel swaps, tab nav, form submissions
  ├── Tailwind CSS (CDN)         — utility styling, zero build step
  ├── Ubuntu Mono (Google Fonts) — terminal Linux identity
  └── static/ws.js (~60 LOC)    — WebSocket live streaming (per-run + global)

FastAPI
  ├── GET  /dashboard            — full page (Jinja2)
  ├── GET  /hub/{id}             — right panel fragment
  ├── GET  /hub/{id}/activity    — activity tab fragment
  ├── GET  /hub/{id}/tasks       — tasks tab fragment
  ├── GET  /hub/{id}/runs        — runs tab fragment
  ├── WS   /ws/runs/{run_id}     — per-run live streaming (unchanged)
  └── WS   /ws/runs              — global all-runs stream (unchanged, used by dashboard)

JSON API (/api/*, /webhooks/*)   — fully intact, no changes
```

---

## Visual Design

- **Theme:** dark (#0d0f18 background, #1e2130 borders, #e5e7eb text)
- **Font:** Ubuntu Mono — terminal Linux aesthetic, mono everywhere
- **Badges:** priority colors (urgent=#EF4444, high=#F59E0B, medium=#3B82F6, low=#6B7280)
- **Source icons:** Material Icons CDN (task_alt, code, chat, smart_toy)
- **Direction:** refine current visual — same identity, cleaner implementation

---

## Right Panel Implementation

The panel is a `position:fixed` div — no Quasar, no dialog, no teleportation:

```html
<div id="right-panel"
     class="fixed top-0 bottom-0 right-0 hidden flex-col"
     style="left:160px; background:#0d0f18; border-left:1px solid #2d3142; z-index:50">
  <div id="panel-content" class="flex flex-col h-full"></div>
</div>
```

Open/close via 4 lines of vanilla JS:
```js
function openPanel()  { document.getElementById('right-panel').classList.replace('hidden','flex') }
function closePanel() { document.getElementById('right-panel').classList.replace('flex','hidden') }
```

HTMX loads content on project click:
```html
<div hx-get="/hub/{{ p.id }}"
     hx-target="#panel-content"
     hx-on::after-request="openPanel()">{{ p.name }}</div>
```

Tab navigation via HTMX swap:
```html
<button hx-get="/hub/{{ id }}/activity" hx-target="#tab-content">ACTIVITY</button>
```

---

## Live Streaming

Two WebSocket endpoints serve streaming — both unchanged from current implementation:

- **`/ws/runs/{run_id}`** — per-run stream (opened when user clicks a run row in the hub)
- **`/ws/runs`** — global broadcast stream (connected on `/dashboard` page load for the
  "Live Stream" panel showing all agent activity)

`static/ws.js` handles both:

```js
function connectRunStream(runId, targetId) {
  const el = document.getElementById(targetId)
  const ws = new WebSocket(`/ws/runs/${runId}`)
  ws.onmessage = e => { el.textContent += e.data; el.scrollTop = el.scrollHeight }
  ws.onerror = () => { el.textContent += '\n[connection error]' }
  return ws
}

function connectGlobalStream(targetId) {
  return connectRunStream('', targetId)  // /ws/runs (no id = global)
}
```

---

## `dashboard_formatters.py` — Kept

`dashboard_formatters.py` contains pure Python formatting helpers with no NiceGUI dependency.
It is **kept and reused** by `dashboard_html.py` route handlers to prepare data before passing
it into Jinja2 templates. `tests/test_dashboard_formatters.py` is also **kept unchanged**.

---

## `main.py` Integration Point

Current call to replace (lines 402–403):
```python
from agents.dashboard import setup_dashboard
setup_dashboard(app, state, config)
```

Replacement:
```python
from agents.dashboard_html import setup_dashboard
setup_dashboard(app, state, config)
```

`dashboard_html.setup_dashboard()` performs:
```python
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

def setup_dashboard(app: FastAPI, state: AppState, config: GlobalConfig) -> None:
    base = Path(__file__).parent
    app.mount("/static", StaticFiles(directory=base / "static"), name="static")
    templates = Jinja2Templates(directory=base / "templates")
    # ... register routes ...
```

The `ui.run_with(app)` call from NiceGUI is **removed entirely** — no equivalent needed.

---

## Form Submissions

HTMX form submissions use standard `application/x-www-form-urlencoded` encoding
(`hx-post` with `hx-include` or inside a `<form>`). FastAPI needs `python-multipart`
to parse `Form(...)` parameters. This is required for:
- Creating/editing tasks (name, trigger type, model, budget)
- Triggering a run (project id, task selection)

Forms that create entities (new project wizard) are **deferred to v1.1** — paridade
estrita covers read flows and simple actions first.

---

## File Structure

```
src/agents/
  templates/
    base.html            ← sidebar + main + right-panel shell
    dashboard.html       ← run history table + live stream section
    hub/
      panel.html         ← right panel wrapper (header + tabs + tab-content)
      activity.html      ← activity tab fragment (event cards)
      tasks.html         ← tasks tab fragment
      runs.html          ← runs tab fragment
    partials/
      event_card.html    ← reusable event card
      task_row.html      ← reusable task row
      run_row.html       ← reusable run history row
  static/
    ws.js                ← WebSocket streaming (~60 LOC)
  dashboard_formatters.py ← KEPT, pure Python, no NiceGUI
  dashboard_html.py       ← HTML routes (replaces NiceGUI dashboard*.py files)
```

---

## Files Deleted

Five NiceGUI dashboard files removed (not `dashboard_formatters.py`):
- `dashboard.py`
- `dashboard_project_hub.py`
- `dashboard_setup_wizard.py`
- `dashboard_task_manager.py`
- `dashboard_theme.py`

NiceGUI removed from `pyproject.toml` dependencies.

---

## Migration Order

1. Add `jinja2` and `python-multipart` to `pyproject.toml` explicitly
2. Create `src/agents/static/` and `src/agents/templates/` directories
3. Create `templates/base.html` + `static/ws.js`
4. Create `dashboard_html.py` with all HTML routes and `setup_dashboard()`
5. Update `main.py`: replace NiceGUI import/call with `dashboard_html.setup_dashboard()`
6. Smoke test all routes with FastAPI TestClient
7. Remove NiceGUI from `pyproject.toml`, run `uv sync`
8. Delete 5 `dashboard*.py` NiceGUI files
9. Delete NiceGUI-specific tests, add new HTML route tests

---

## Testing Strategy

**Delete** (test NiceGUI internals, not behavior):
- `tests/test_dashboard.py`
- `tests/agents/test_dashboard_project_hub.py`
- `tests/agents/test_dashboard_theme.py`
- `tests/agents/test_dashboard_setup_wizard.py`
- `tests/agents/test_dashboard_task_manager.py`

**Keep unchanged:**
- `tests/test_dashboard_formatters.py` — pure Python, no NiceGUI
- All API route tests, WebSocket tests, webhook tests

**New `tests/test_dashboard_html.py`:**
- `GET /dashboard` → 200, contains sidebar with project names
- `GET /hub/{id}` → 200, contains project name in header
- `GET /hub/{id}/activity` → 200, contains event cards HTML
- `GET /hub/{id}/tasks` → 200, contains task rows HTML
- `GET /hub/{id}/runs` → 200, contains run rows HTML
- `GET /hub/missing-id` → 404

Project creation POST flows deferred to v1.1.

---

## Risks

| Risk | Mitigation |
|------|-----------|
| NiceGUI pins Starlette version | `uv remove nicegui` then `uv sync` resolves conflicts |
| Jinja2 was transitive via NiceGUI | Add explicitly to `pyproject.toml` before removing NiceGUI |
| `python-multipart` needed for Form() | Added explicitly in step 1 |
| Static file serving | FastAPI `StaticFiles` mount in `setup_dashboard()` |
| CSS regression | Visual smoke test via Playwright after migration |
| Global live stream path | `/ws/runs` endpoint already exists, ws.js connects on page load |
