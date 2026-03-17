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
  ├── HTMX 2.x (CDN)         — panel swaps, tab nav, form submissions
  ├── Tailwind CSS (CDN)      — utility styling, zero build step
  ├── Ubuntu Mono (Google Fonts) — terminal Linux identity
  └── static/ws.js (~60 LOC)  — WebSocket live streaming

FastAPI
  ├── GET  /dashboard          — full page (Jinja2)
  ├── GET  /hub/{id}           — right panel fragment
  ├── GET  /hub/{id}/activity  — activity tab fragment
  ├── GET  /hub/{id}/tasks     — tasks tab fragment
  ├── GET  /hub/{id}/runs      — runs tab fragment
  └── WS   /ws/runs/{id}       — live streaming (unchanged)

JSON API (/api/*, /webhooks/*)  — fully intact, no changes
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

WebSocket endpoint `/ws/runs/{run_id}` is unchanged. ~60 lines of vanilla JS in `static/ws.js`:

```js
function connectRunStream(runId, targetId) {
  const el = document.getElementById(targetId)
  const ws = new WebSocket(`/ws/runs/${runId}`)
  ws.onmessage = e => { el.textContent += e.data; el.scrollTop = el.scrollHeight }
  ws.onerror = () => { el.textContent += '\n[connection error]' }
  return ws
}
```

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
  dashboard_html.py      ← HTML routes (replaces all dashboard*.py NiceGUI files)
```

---

## Files Deleted

All 6 NiceGUI dashboard files are removed:
- `dashboard.py`
- `dashboard_project_hub.py`
- `dashboard_setup_wizard.py`
- `dashboard_task_manager.py`
- `dashboard_formatters.py`
- `dashboard_theme.py`

NiceGUI removed from `pyproject.toml` dependencies.

---

## Migration Order

1. Add `jinja2` and `python-multipart` to dependencies (if not present)
2. Create `templates/base.html` + `static/ws.js`
3. Create `dashboard_html.py` with all HTML routes
4. Wire `dashboard_html.py` into `main.py` (replace `setup_dashboard()` call)
5. Smoke test all routes
6. Remove NiceGUI from `pyproject.toml`, run `uv sync`
7. Delete 6 `dashboard*.py` files
8. Delete/rewrite tests (NiceGUI unit tests → FastAPI TestClient HTML tests)

---

## Testing Strategy

**Delete:** `tests/test_dashboard.py`, `tests/agents/test_dashboard_project_hub.py`,
`tests/agents/test_dashboard_theme.py`, `tests/agents/test_dashboard_setup_wizard.py`,
`tests/agents/test_dashboard_task_manager.py` — these tested NiceGUI internals, not behavior.

**New tests in `tests/test_dashboard_html.py`:**
- `GET /dashboard` → 200, contains sidebar HTML
- `GET /hub/{id}` → 200, contains project name
- `GET /hub/{id}/activity` → 200, contains event cards
- `GET /hub/{id}/tasks` → 200, contains task rows
- `GET /hub/{id}/runs` → 200, contains run rows
- `GET /hub/missing` → 404

**Unchanged:** all API route tests, WebSocket tests, webhook tests.

---

## Risks

| Risk | Mitigation |
|------|-----------|
| NiceGUI pins Starlette version | `uv remove nicegui` then `uv sync` resolves version conflicts |
| Missing Jinja2 in deps | Add explicitly to `pyproject.toml` |
| Static file serving | FastAPI `StaticFiles` mount for `/static` |
| CSS regression | Visual smoke test via Playwright after migration |
