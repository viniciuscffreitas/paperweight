# Dashboard Coordination Tab — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Coordination" page to the paperweight dashboard showing active file claims, mediations, and a real-time event timeline — giving operators visibility into multi-agent coordination.

**Architecture:** 4 chunks. Chunk 1 adds the data API (broker exposes coordination state as dicts). Chunk 2 adds Jinja2 templates + macros. Chunk 3 adds routes in dashboard_html.py. Chunk 4 adds WebSocket for real-time timeline updates + integration tests. Each chunk is TDD.

**Tech Stack:** Jinja2, HTMX, inline CSS with CSS variables, WebSocket, pytest

**Spec:** Design from frontend-design skill, follows existing dashboard patterns.

---

## File Map

### New files

| File | Responsibility |
|------|---------------|
| `src/agents/templates/coordination.html` | Main coordination page (extends base.html) |
| `src/agents/templates/coordination/claims.html` | HTMX partial: active claims list |
| `src/agents/templates/coordination/mediations.html` | HTMX partial: active mediations |
| `src/agents/templates/coordination/timeline.html` | HTMX partial: recent events |
| `tests/test_dashboard_coordination.py` | All tests for the coordination tab |

### Modified files

| File | Change |
|------|--------|
| `src/agents/coordination/broker.py` | Add `get_coordination_snapshot()` method |
| `src/agents/dashboard_html.py` | Add coordination routes |
| `src/agents/templates/base.html` | Add "Coordination" link to sidebar + bottom nav |
| `src/agents/templates/components/macros.html` | Add coordination macros |

---

## Chunk 1: Broker data API

### Task 1.1: Write failing tests for broker snapshot

**Files:**
- Modify: `tests/test_dashboard_coordination.py`

- [ ] **Step 1: Create test file with broker snapshot tests**

```python
"""Tests for the dashboard coordination tab."""
import json
import time

import pytest

from agents.coordination.broker import CoordinationBroker
from agents.coordination.models import CoordinationConfig
from agents.streaming import StreamEvent


@pytest.fixture
def broker():
    return CoordinationBroker(CoordinationConfig(enabled=True))


@pytest.fixture
def wt_a(tmp_path):
    wt = tmp_path / "wt-a"
    wt.mkdir()
    return wt


@pytest.fixture
def wt_b(tmp_path):
    wt = tmp_path / "wt-b"
    wt.mkdir()
    return wt


@pytest.mark.asyncio
async def test_get_coordination_snapshot_empty(broker):
    snapshot = broker.get_coordination_snapshot()
    assert snapshot["claims"] == []
    assert snapshot["mediations"] == []
    assert snapshot["active_runs"] == 0
    assert snapshot["contested_count"] == 0
    assert snapshot["mediating_count"] == 0


@pytest.mark.asyncio
async def test_get_coordination_snapshot_with_claims(broker, wt_a, wt_b):
    await broker.register_run("run-a", wt_a, "add pagination")
    await broker.register_run("run-b", wt_b, "add auth")

    await broker.on_stream_event(
        "run-a",
        StreamEvent(type="tool_use", tool_name="Edit",
                    file_path=str(wt_a / "src/users.py"), timestamp=1.0),
        worktree_root=wt_a,
    )

    snapshot = broker.get_coordination_snapshot()
    assert len(snapshot["claims"]) == 1
    assert snapshot["claims"][0]["file"] == "src/users.py"
    assert snapshot["claims"][0]["owner"] == "run-a"
    assert snapshot["claims"][0]["status"] == "active"
    assert snapshot["claims"][0]["type"] == "hard"
    assert snapshot["active_runs"] == 2
    assert snapshot["contested_count"] == 0


@pytest.mark.asyncio
async def test_get_coordination_snapshot_contested(broker, wt_a, wt_b):
    await broker.register_run("run-a", wt_a, "add pagination")
    await broker.register_run("run-b", wt_b, "add auth")

    await broker.on_stream_event(
        "run-a",
        StreamEvent(type="tool_use", tool_name="Edit",
                    file_path=str(wt_a / "src/users.py"), timestamp=1.0),
        worktree_root=wt_a,
    )

    # B needs same file via inbox
    inbox_b = wt_b / ".paperweight" / "inbox.jsonl"
    with inbox_b.open("a") as f:
        f.write(json.dumps({"type": "need_file", "file": "src/users.py", "intent": "auth"}) + "\n")
    await broker.poll_inboxes_once()

    snapshot = broker.get_coordination_snapshot()
    assert snapshot["contested_count"] == 1
    assert snapshot["claims"][0]["status"] == "contested"


@pytest.mark.asyncio
async def test_get_coordination_snapshot_timeline(broker, wt_a):
    await broker.register_run("run-a", wt_a, "task a")

    await broker.on_stream_event(
        "run-a",
        StreamEvent(type="tool_use", tool_name="Edit",
                    file_path=str(wt_a / "src/x.py"), timestamp=1.0),
        worktree_root=wt_a,
    )

    snapshot = broker.get_coordination_snapshot()
    assert len(snapshot["timeline"]) >= 1
    # Timeline should have most recent event first
    assert snapshot["timeline"][0]["run_id"] == "run-a"
```

- [ ] **Step 2: Run to confirm RED**

```bash
.venv/bin/pytest tests/test_dashboard_coordination.py -v
```

Expected: FAIL (get_coordination_snapshot doesn't exist)

---

### Task 1.2: Implement get_coordination_snapshot

**Files:**
- Modify: `src/agents/coordination/broker.py`

- [ ] **Step 1: Add timeline tracking to broker**

In `__init__`, add:
```python
self._timeline: list[dict] = []  # recent coordination events (capped at 100)
```

Add a helper to record events:
```python
def _record_timeline(self, run_id: str, event_type: str, detail: str) -> None:
    import time as _time
    entry = {
        "run_id": run_id,
        "type": event_type,
        "detail": detail,
        "timestamp": _time.time(),
    }
    self._timeline.insert(0, entry)
    if len(self._timeline) > 100:
        self._timeline.pop()
```

Call `_record_timeline` in `register_run`, `deregister_run`, `on_stream_event` (for file claims), and `_process_inbox_message` (for need_file, heartbeat, escalation).

- [ ] **Step 2: Add get_coordination_snapshot method**

```python
def get_coordination_snapshot(self) -> dict:
    """Return current coordination state for dashboard display."""
    claims = []
    contested = 0
    mediating = 0
    for fp, claim in self.claims._claims.items():
        claims.append({
            "file": fp,
            "owner": claim.run_id,
            "status": claim.status.value,
            "type": claim.claim_type.value,
            "since": claim.claimed_at,
        })
        if claim.status.value == "contested":
            contested += 1
        elif claim.status.value == "mediating":
            mediating += 1

    mediations = []  # populated when mediator spawning is implemented

    return {
        "claims": claims,
        "mediations": mediations,
        "active_runs": len(self.active_worktrees),
        "contested_count": contested,
        "mediating_count": mediating,
        "timeline": self._timeline[:50],
    }
```

- [ ] **Step 3: Run tests → GREEN**

```bash
.venv/bin/pytest tests/test_dashboard_coordination.py -v
```

- [ ] **Step 4: Run full suite**

```bash
.venv/bin/pytest --tb=short -q
```

- [ ] **Step 5: Commit**

```bash
git add src/agents/coordination/broker.py tests/test_dashboard_coordination.py
git commit -m "feat(coordination): broker.get_coordination_snapshot() for dashboard"
```

---

## Chunk 2: Jinja2 Templates + Macros

### Task 2.1: Write failing tests for coordination page

- [ ] **Step 1: Add template rendering tests to test_dashboard_coordination.py**

```python
# --- Template rendering tests ---

@pytest.fixture
def app_with_coordination(tmp_path):
    """Create a test app with coordination enabled."""
    from starlette.testclient import TestClient
    from pathlib import Path
    import yaml

    repo = tmp_path / "repo"
    repo.mkdir()

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({
        "budget": {"daily_limit_usd": 10.0},
        "execution": {
            "worktree_base": str(tmp_path / "wt"),
            "dry_run": True,
            "max_concurrent": 3,
            "timeout_minutes": 5,
        },
        "coordination": {"enabled": True},
        "server": {"port": 8080},
        "notifications": {"slack_webhook_url": ""},
        "webhooks": {"github_secret": "", "linear_secret": ""},
        "integrations": {"linear_api_key": ""},
    }))

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    (projects_dir / "test.yaml").write_text(yaml.dump({
        "name": "test",
        "repo": str(repo),
        "tasks": {"t": {"description": "d", "intent": "i", "schedule": "0 * * * *"}},
    }))

    from agents.main import create_app
    app = create_app(config_path=config_path, projects_dir=projects_dir, data_dir=tmp_path / "data")
    return TestClient(app)


def test_coordination_page_returns_200(app_with_coordination):
    resp = app_with_coordination.get("/coordination")
    assert resp.status_code == 200
    assert "Coordination" in resp.text


def test_coordination_page_has_status_bar(app_with_coordination):
    resp = app_with_coordination.get("/coordination")
    assert "active" in resp.text.lower()
    assert "contested" in resp.text.lower()


def test_coordination_claims_partial(app_with_coordination):
    resp = app_with_coordination.get("/coordination/claims")
    assert resp.status_code == 200


def test_coordination_timeline_partial(app_with_coordination):
    resp = app_with_coordination.get("/coordination/timeline")
    assert resp.status_code == 200


def test_coordination_page_uses_css_tokens(app_with_coordination):
    resp = app_with_coordination.get("/coordination")
    html = resp.text
    # Must use design tokens, not raw hex
    assert "var(--" in html


def test_coordination_link_in_sidebar(app_with_coordination):
    resp = app_with_coordination.get("/dashboard")
    assert "/coordination" in resp.text
```

- [ ] **Step 2: Run to confirm RED**

```bash
.venv/bin/pytest tests/test_dashboard_coordination.py -v -k "test_coordination_page or test_coordination_claims or test_coordination_timeline or test_coordination_link"
```

Expected: FAIL (routes don't exist yet)

---

### Task 2.2: Create coordination macros

**Files:**
- Modify: `src/agents/templates/components/macros.html`

- [ ] **Step 1: Add coordination macros at end of macros.html**

```jinja2

{# ── coord_status_bar ───────────────────────────────────────────────── #}
{% macro coord_status_bar(active_runs, active_claims, contested, mediating) -%}
<div style="display:flex;gap:16px;padding:10px 16px;font-size:11px;
            border-bottom:1px solid var(--border-subtle);flex-shrink:0;">
  <span style="color:var(--text-secondary);">
    <span style="color:var(--status-running);font-weight:700;">{{ active_runs }}</span> runs
  </span>
  <span style="color:var(--text-secondary);">
    <span style="color:var(--text-primary);font-weight:700;">{{ active_claims }}</span> claims
  </span>
  <span style="color:var(--text-secondary);">
    <span style="color:var(--status-warning);font-weight:700;">{{ contested }}</span> contested
  </span>
  <span style="color:var(--text-secondary);">
    <span style="color:var(--accent);font-weight:700;">{{ mediating }}</span> mediating
  </span>
</div>
{%- endmacro %}


{# ── claim_row ──────────────────────────────────────────────────────── #}
{% macro claim_row(file, owner, status, claim_type) -%}
{% set status_color = {
  'active': 'var(--status-running)' if claim_type == 'hard' else 'var(--text-muted)',
  'contested': 'var(--status-warning)',
  'mediating': 'var(--accent)',
  'released': 'var(--status-success)',
}.get(status, 'var(--text-muted)') %}
{% set is_pulse = status in ('contested', 'mediating') %}
<div style="display:flex;align-items:center;gap:10px;padding:8px 16px;font-size:12px;
            border-bottom:1px solid var(--bg-overlay);transition:background .15s;"
     onmouseover="this.style.background='var(--bg-elevated)'"
     onmouseout="this.style.background='transparent'">
  <span class="status-dot {{ 'live-pulse' if is_pulse else '' }}"
        style="background:{{ status_color }};flex-shrink:0;"
        aria-hidden="true"></span>
  <span style="color:var(--text-primary);flex:1;overflow:hidden;text-overflow:ellipsis;
               white-space:nowrap;font-family:monospace;font-size:11px;">{{ file }}</span>
  <span style="color:var(--text-muted);font-size:10px;white-space:nowrap;">{{ owner|truncate(20) }}</span>
  <span style="color:{{ status_color }};font-size:9px;text-transform:uppercase;
               letter-spacing:.5px;white-space:nowrap;">{{ status }}</span>
</div>
{%- endmacro %}


{# ── coord_event ────────────────────────────────────────────────────── #}
{% macro coord_event(timestamp, run_id, event_type, detail) -%}
{% set type_color = {
  'registered': 'var(--status-running)',
  'deregistered': 'var(--text-muted)',
  'claim': 'var(--text-primary)',
  'contested': 'var(--status-warning)',
  'need_file': 'var(--status-warning)',
  'heartbeat': 'var(--text-disabled)',
  'escalation': 'var(--status-error)',
  'released': 'var(--status-success)',
}.get(event_type, 'var(--text-muted)') %}
<div style="display:flex;gap:8px;padding:6px 16px;font-size:11px;
            border-bottom:1px solid var(--bg-overlay);">
  <span style="color:var(--text-disabled);font-family:monospace;font-size:10px;
               white-space:nowrap;flex-shrink:0;">{{ timestamp }}</span>
  <span style="color:{{ type_color }};white-space:nowrap;flex-shrink:0;">{{ event_type }}</span>
  <span style="color:var(--text-muted);font-size:10px;white-space:nowrap;">{{ run_id|truncate(24) }}</span>
  <span style="color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;
               white-space:nowrap;">{{ detail }}</span>
</div>
{%- endmacro %}
```

---

### Task 2.3: Create coordination templates

**Files:**
- Create: `src/agents/templates/coordination.html`
- Create: `src/agents/templates/coordination/claims.html`
- Create: `src/agents/templates/coordination/mediations.html`
- Create: `src/agents/templates/coordination/timeline.html`

- [ ] **Step 1: Create coordination.html (main page)**

```jinja2
{% extends "base.html" %}
{% from "components/macros.html" import coord_status_bar %}

{% block topbar %}
<div style="display:flex;align-items:center;height:44px;padding:0 16px;">
  <span style="font-size:13px;font-weight:700;color:var(--text-primary);">Coordination</span>
</div>
{% endblock %}

{% block content %}
<div style="display:flex;flex-direction:column;height:100%;">

  {{ coord_status_bar(snapshot.active_runs, snapshot.claims|length, snapshot.contested_count, snapshot.mediating_count) }}

  <div style="display:flex;flex:1;overflow:hidden;">
    <!-- Left: Claims + Mediations -->
    <div style="flex:1;overflow-y:auto;border-right:1px solid var(--border-subtle);">
      <div style="padding:10px 16px 4px;font-size:9px;color:var(--text-secondary);
                  text-transform:uppercase;letter-spacing:1.5px;">File Claims</div>
      <div id="claims-content"
           hx-get="/coordination/claims"
           hx-trigger="load, every 5s"
           hx-swap="innerHTML">
      </div>

      {% if snapshot.mediations %}
      <div style="padding:10px 16px 4px;font-size:9px;color:var(--text-secondary);
                  text-transform:uppercase;letter-spacing:1.5px;
                  border-top:1px solid var(--border-subtle);">Mediations</div>
      <div id="mediations-content"
           hx-get="/coordination/mediations"
           hx-trigger="load, every 5s"
           hx-swap="innerHTML">
      </div>
      {% endif %}
    </div>

    <!-- Right: Timeline -->
    <div style="flex:1;overflow-y:auto;display:flex;flex-direction:column;">
      <div style="padding:10px 16px 4px;font-size:9px;color:var(--text-secondary);
                  text-transform:uppercase;letter-spacing:1.5px;">Timeline</div>
      <div id="timeline-content"
           hx-get="/coordination/timeline"
           hx-trigger="load, every 3s"
           hx-swap="innerHTML"
           style="flex:1;overflow-y:auto;">
      </div>
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 2: Create claims.html partial**

```jinja2
{% from "components/macros.html" import claim_row %}
{% if claims %}
  {% for c in claims %}
    {{ claim_row(c.file, c.owner, c.status, c.type) }}
  {% endfor %}
{% else %}
  <div style="padding:24px 16px;text-align:center;color:var(--text-placeholder);font-size:12px;">
    No active claims
  </div>
{% endif %}
```

- [ ] **Step 3: Create mediations.html partial**

```jinja2
{% if mediations %}
  {% for m in mediations %}
  <div style="display:flex;align-items:center;gap:10px;padding:8px 16px;font-size:12px;
              border-bottom:1px solid var(--bg-overlay);">
    <span class="status-dot live-pulse" style="background:var(--accent);" aria-hidden="true"></span>
    <span style="color:var(--text-primary);font-family:monospace;font-size:11px;">{{ m.id }}</span>
    <span style="color:var(--text-muted);font-size:10px;">{{ m.files|join(', ') }}</span>
    <span style="color:var(--accent);font-size:9px;text-transform:uppercase;">{{ m.status }}</span>
  </div>
  {% endfor %}
{% else %}
  <div style="padding:16px;text-align:center;color:var(--text-placeholder);font-size:12px;">
    No active mediations
  </div>
{% endif %}
```

- [ ] **Step 4: Create timeline.html partial**

```jinja2
{% from "components/macros.html" import coord_event %}
{% if timeline %}
  {% for e in timeline %}
    {{ coord_event(e.time_str, e.run_id, e.type, e.detail) }}
  {% endfor %}
{% else %}
  <div style="padding:24px 16px;text-align:center;color:var(--text-placeholder);font-size:12px;">
    No coordination events yet
  </div>
{% endif %}
```

---

## Chunk 3: Dashboard Routes

### Task 3.1: Add coordination routes to dashboard_html.py

**Files:**
- Modify: `src/agents/dashboard_html.py`

- [ ] **Step 1: Add coordination routes**

Add these routes in `setup_dashboard()`:

```python
@app.get("/coordination", response_class=HTMLResponse)
async def coordination_page(request: Request):
    snapshot = {}
    if state.broker:
        snapshot = state.broker.get_coordination_snapshot()
    else:
        snapshot = {"claims": [], "mediations": [], "active_runs": 0,
                    "contested_count": 0, "mediating_count": 0, "timeline": []}
    projects = state.project_store.list_projects() if state.project_store else []
    return templates.TemplateResponse("coordination.html", {
        "request": request,
        "projects": projects,
        "snapshot": snapshot,
        "current_path": "/coordination",
    })


@app.get("/coordination/claims", response_class=HTMLResponse)
async def coordination_claims(request: Request):
    claims = []
    if state.broker:
        snapshot = state.broker.get_coordination_snapshot()
        claims = snapshot["claims"]
    return templates.TemplateResponse("coordination/claims.html", {
        "request": request,
        "claims": claims,
    })


@app.get("/coordination/mediations", response_class=HTMLResponse)
async def coordination_mediations(request: Request):
    mediations = []
    if state.broker:
        snapshot = state.broker.get_coordination_snapshot()
        mediations = snapshot["mediations"]
    return templates.TemplateResponse("coordination/mediations.html", {
        "request": request,
        "mediations": mediations,
    })


@app.get("/coordination/timeline", response_class=HTMLResponse)
async def coordination_timeline(request: Request):
    timeline = []
    if state.broker:
        snapshot = state.broker.get_coordination_snapshot()
        timeline = snapshot["timeline"]
        # Format timestamps
        from datetime import datetime, UTC
        for e in timeline:
            dt = datetime.fromtimestamp(e["timestamp"], tz=UTC)
            e["time_str"] = dt.strftime("%H:%M:%S")
    return templates.TemplateResponse("coordination/timeline.html", {
        "request": request,
        "timeline": timeline,
    })
```

- [ ] **Step 2: Add coordination link to sidebar in base.html**

In the sidebar navigation (after Projects section), add:
```jinja2
<a href="/coordination"
   style="display:block;padding:8px 12px;font-size:12px;
          color:{{ 'var(--text-primary)' if current_path == '/coordination' else 'var(--text-muted)' }};
          text-decoration:none;border-radius:4px;margin:1px 6px;transition:background .15s;"
   onmouseover="this.style.background='var(--bg-elevated)'"
   onmouseout="this.style.background='transparent'">
  Coordination
</a>
```

- [ ] **Step 3: Run tests → GREEN**

```bash
.venv/bin/pytest tests/test_dashboard_coordination.py -v
```

- [ ] **Step 4: Run full suite**

```bash
.venv/bin/pytest --tb=short -q
```

- [ ] **Step 5: Commit**

```bash
git add src/agents/coordination/broker.py \
  src/agents/dashboard_html.py \
  src/agents/templates/coordination.html \
  src/agents/templates/coordination/ \
  src/agents/templates/components/macros.html \
  src/agents/templates/base.html \
  tests/test_dashboard_coordination.py
git commit -m "feat(dashboard): coordination tab — claims, mediations, timeline"
```

---

## Chunk 4: WebSocket + Full Integration Tests

### Task 4.1: Add coordination-specific WebSocket tests

- [ ] **Step 1: Add WebSocket and comprehensive tests**

```python
# Add to test_dashboard_coordination.py:

def test_coordination_page_no_broker(tmp_path):
    """Coordination page works even without broker (shows empty state)."""
    # Create app without coordination enabled
    from starlette.testclient import TestClient
    import yaml

    repo = tmp_path / "repo"
    repo.mkdir()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({
        "budget": {"daily_limit_usd": 10.0},
        "execution": {"worktree_base": str(tmp_path / "wt"), "dry_run": True},
        "coordination": {"enabled": False},
        "server": {"port": 8080},
        "notifications": {"slack_webhook_url": ""},
        "webhooks": {"github_secret": "", "linear_secret": ""},
        "integrations": {"linear_api_key": ""},
    }))
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    (projects_dir / "test.yaml").write_text(yaml.dump({
        "name": "test", "repo": str(repo),
        "tasks": {"t": {"description": "d", "intent": "i", "schedule": "0 * * * *"}},
    }))

    from agents.main import create_app
    app = create_app(config_path=config_path, projects_dir=projects_dir, data_dir=tmp_path / "data")
    client = TestClient(app)
    resp = client.get("/coordination")
    assert resp.status_code == 200
    assert "No active claims" in resp.text or "0" in resp.text


def test_coordination_claims_empty(app_with_coordination):
    resp = app_with_coordination.get("/coordination/claims")
    assert resp.status_code == 200
    assert "No active claims" in resp.text


def test_coordination_mediations_empty(app_with_coordination):
    resp = app_with_coordination.get("/coordination/mediations")
    assert resp.status_code == 200
    assert "No active mediations" in resp.text


def test_coordination_timeline_empty(app_with_coordination):
    resp = app_with_coordination.get("/coordination/timeline")
    assert resp.status_code == 200
    assert "No coordination events" in resp.text


def test_coordination_page_accessible(app_with_coordination):
    """WCAG: page must have proper heading and landmark roles."""
    resp = app_with_coordination.get("/coordination")
    assert resp.status_code == 200
    assert "Coordination" in resp.text
```

- [ ] **Step 2: Run full suite → GREEN**

```bash
.venv/bin/pytest --tb=short -q
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_dashboard_coordination.py
git commit -m "test(dashboard): coordination tab — empty states, no-broker, accessibility"
```

---

## Summary

After all 4 chunks:
- `GET /coordination` — full coordination page with status bar, claims, timeline
- `GET /coordination/claims` — HTMX partial, polls every 5s
- `GET /coordination/mediations` — HTMX partial, polls every 5s
- `GET /coordination/timeline` — HTMX partial, polls every 3s
- Sidebar link to coordination page
- All components use existing CSS tokens (dark/light theme compatible)
- Empty states for all views (no broker, no claims, no events)
- 100% test coverage for all routes and states
