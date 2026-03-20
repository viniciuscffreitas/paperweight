# Frontend Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite all 23 front-end files to the bold-minimal design system with L-chrome layout, WCAG AA compliance, and responsive desktop+mobile support. Zero backend changes.

**Architecture:** Server-side rendered Jinja2 templates with HTMX for partial swaps, vanilla JS for interactivity, CSS custom properties for theming. L-shaped chrome (sidebar+header) frames a floating content panel. Task cards are the primary UI element.

**Tech Stack:** FastAPI + Jinja2, HTMX 2.0, vanilla JavaScript, CSS custom properties, Material Icons, Inter font (CDN)

**Spec:** `docs/superpowers/specs/2026-03-20-frontend-redesign-design.md`

---

## File Structure

### New files to create
```
src/agents/static/styles.css           — design tokens + all styles
src/agents/static/app.js               — layout, nav, sidebar, theme
src/agents/static/task-detail.js       — task detail, tabs, activity feed, chat
src/agents/static/stream.js            — WebSocket helpers
src/agents/templates/base.html         — L-chrome, sidebar, topbar, mobile nav (overwrite)
src/agents/templates/tasks.html        — task list primary view (new)
src/agents/templates/task-detail.html  — task detail with tabs (new)
src/agents/templates/project-picker.html — cross-project overview (new)
src/agents/templates/components/macros.html — new component macros (overwrite)
src/agents/templates/partials/task_card.html — task card partial (new)
src/agents/templates/partials/task_card_done.html — done card (new)
src/agents/templates/partials/activity_event.html — activity event (new)
src/agents/templates/partials/stats_line.html — stats counters (new)
src/agents/templates/partials/session_row.html — session row (new)
src/agents/templates/setup/wizard.html — restyled wizard (new, replaces step2.html)
```

### Files to delete after migration
```
src/agents/templates/dashboard.html
src/agents/templates/coordination.html
src/agents/templates/coordination/claims.html
src/agents/templates/coordination/mediations.html
src/agents/templates/coordination/timeline.html
src/agents/templates/hub/panel.html
src/agents/templates/hub/activity.html
src/agents/templates/hub/tasks.html
src/agents/templates/hub/runs.html
src/agents/templates/hub/agent.html
src/agents/templates/setup/step2.html
src/agents/templates/partials/event_card.html
src/agents/templates/partials/work_item_row.html
src/agents/templates/partials/task_row.html
src/agents/templates/partials/run_row.html
src/agents/templates/partials/task_run_row.html
src/agents/static/dashboard.css
src/agents/static/dashboard.js
src/agents/static/agent.js
src/agents/static/ws.js
```

### Files to modify
```
src/agents/dashboard_html.py    — update HTML routes to render new templates
tests/test_macros.py            — update macro tests for new macros
tests/test_composite_macros.py  — update composite macro tests
tests/test_dashboard_html.py    — update route tests for new templates
```

---

## Task 1: Design Tokens & Base CSS

**Files:**
- Create: `src/agents/static/styles.css`
- Delete: `src/agents/static/dashboard.css`

- [ ] **Step 1: Write test — verify CSS file has required tokens**

```python
# In tests/test_macros.py, add at top:
_STATIC_DIR = Path(__file__).parent.parent / "src" / "agents" / "static"

def test_styles_css_exists():
    assert (_STATIC_DIR / "styles.css").exists()

def test_styles_has_design_tokens():
    css = (_STATIC_DIR / "styles.css").read_text()
    for token in ["--bg-chrome", "--bg-content", "--text-primary", "--text-secondary",
                   "--status-running", "--accent-text", "--card-radius"]:
        assert token in css, f"Missing token: {token}"

def test_styles_wcag_no_old_colors():
    """Old colors that fail WCAG must not appear."""
    css = (_STATIC_DIR / "styles.css").read_text()
    for bad in ["#555555", "#444444", "#333333"]:
        # These should not be text colors (may appear in borders/decorative)
        lines = [l for l in css.split('\n') if bad in l and 'text' in l.lower()]
        assert not lines, f"WCAG fail: {bad} used as text color"
```

- [ ] **Step 2: Run tests — must fail (styles.css doesn't exist yet)**

Run: `cd /Users/vini/Developer/agents && uv run pytest tests/test_macros.py::test_styles_css_exists -v`

- [ ] **Step 3: Create styles.css with all design tokens**

Create `src/agents/static/styles.css` with:
- `:root` block with all dark theme tokens from spec (chrome, content, card, text, status, accent, spacing)
- `[data-theme="light"]` block (stub with inverted values)
- Base resets: `*, html, body` with Inter font, `--bg-chrome` background
- Status dot styles (`.status-dot`, `.status-dot.running`, etc.) — 10px circles
- Animations: `@keyframes pulse`, `@keyframes skeleton-pulse`
- `.sr-only` accessibility class
- `:focus-visible` custom outline using `--accent-focus`
- `@media (prefers-reduced-motion: reduce)` — disable animations
- Mobile breakpoint (`@media max-width: 767px`) — sidebar drawer, bottom sheet, bottom nav
- Desktop breakpoint (`@media min-width: 768px`) — hide mobile elements
- Utility classes: `.skeleton` (loading placeholder)

- [ ] **Step 4: Run tests — must pass**

Run: `cd /Users/vini/Developer/agents && uv run pytest tests/test_macros.py::test_styles_css_exists tests/test_macros.py::test_styles_has_design_tokens -v`

- [ ] **Step 5: Delete old dashboard.css**

```bash
rm src/agents/static/dashboard.css
```

- [ ] **Step 6: Commit**

```bash
git add src/agents/static/styles.css tests/test_macros.py
git add -u src/agents/static/dashboard.css
git commit -m "feat(ui): design tokens and base CSS — bold minimal system"
```

---

## Task 2: Component Macros

**Files:**
- Overwrite: `src/agents/templates/components/macros.html`
- Modify: `tests/test_macros.py`
- Modify: `tests/test_composite_macros.py`

- [ ] **Step 1: Write tests for new primitive macros**

Update `tests/test_macros.py` — replace existing tests with tests for new macros:
- `test_btn_primary_has_gradient` — btn(variant='primary') has `linear-gradient`
- `test_btn_ghost_renders` — btn(variant='ghost') has transparent background
- `test_btn_danger_renders` — btn(variant='danger') has error color
- `test_status_dot_running_has_glow` — status_dot('running') has `box-shadow`
- `test_badge_renders_pill` — badge('LIN-342') has border-radius
- `test_input_field_has_focus_ring` — input_field renders with onfocus accent border
- `test_section_label_uppercase` — section_label has text-transform:uppercase
- `test_back_link_renders` — back_link('tasks') has ← arrow

- [ ] **Step 2: Run tests — must fail**

Run: `cd /Users/vini/Developer/agents && uv run pytest tests/test_macros.py -v`

- [ ] **Step 3: Write tests for composite macros**

Update `tests/test_composite_macros.py`:
- `test_task_card_renders_title` — task_card macro renders title at 17px
- `test_task_card_running_has_glow` — running card has status glow
- `test_task_card_done_has_opacity` — done card has opacity: 0.35
- `test_stats_line_renders_counters` — stats_line renders colored numbers
- `test_tab_bar_renders_three_tabs` — tab_bar has Activity, Output, Chat

- [ ] **Step 4: Run tests — must fail**

Run: `cd /Users/vini/Developer/agents && uv run pytest tests/test_composite_macros.py -v`

- [ ] **Step 5: Implement macros.html**

Overwrite `src/agents/templates/components/macros.html` with new macros:

**Primitives:**
- `btn(label, variant='primary', onclick='', type='button', aria_label='')` — primary uses gradient, 13px font, 8px 18px padding, border-radius 8px
- `status_dot(status, pulse=false)` — 10px circle, glow for running, pulse animation optional
- `badge(text, color='')` — 11px pill with subtle border
- `input_field(name, placeholder='', required=false, label='')` — 13px input, accent focus ring
- `section_label(text)` — 11px 600weight uppercase
- `back_link(text, href='#')` — ← arrow + text, clickable
- `divider()` — 1px separator using --separator-strong

**Composites:**
- `task_card(item)` — bold card: status dot+glow, 17px title, badges (source, model), cost, time. Background tinted by status. Border hover = status color.
- `task_card_done(item)` — compact single row, opacity 0.35
- `stats_line(counts, budget_spent, budget_total)` — inline colored counters + budget
- `tab_bar(tabs, active_tab)` — underline-style tabs
- `sidebar_item(name, project_id, active=false)` — project list item with HTMX
- `panel_header(title)` — header for floating content panel

- [ ] **Step 6: Run tests — must pass**

Run: `cd /Users/vini/Developer/agents && uv run pytest tests/test_macros.py tests/test_composite_macros.py -v`

- [ ] **Step 7: Commit**

```bash
git add src/agents/templates/components/macros.html tests/test_macros.py tests/test_composite_macros.py
git commit -m "feat(ui): new component macros — bold cards, stats line, badges"
```

---

## Task 3: Base Layout (L-Chrome)

**Files:**
- Overwrite: `src/agents/templates/base.html`
- Create: `src/agents/static/app.js`
- Delete: `src/agents/static/dashboard.js`

- [ ] **Step 1: Write test — base.html renders L-chrome structure**

Add to `tests/test_dashboard_html.py`:
```python
def test_base_renders_l_chrome(app_with_dashboard):
    r = app_with_dashboard.get("/dashboard")
    assert r.status_code == 200
    assert 'id="sidebar"' in r.text
    assert 'id="content-panel"' in r.text
    assert 'styles.css' in r.text
    assert 'app.js' in r.text
```

- [ ] **Step 2: Run test — must fail**

Run: `cd /Users/vini/Developer/agents && uv run pytest tests/test_dashboard_html.py::test_base_renders_l_chrome -v`

- [ ] **Step 3: Create base.html with L-chrome layout**

Overwrite `src/agents/templates/base.html`:
- `<html lang="pt-BR" data-theme="...">` with Inter font CDN, HTMX CDN, Material Icons CDN, `styles.css`, `app.js`
- Skip-to-content link (WCAG)
- Mobile: sidebar backdrop, panel backdrop
- Sidebar `<nav>` (200px): logo "paperweight", project list via `sidebar_item` macro, Sessions link, Settings link
- Main area: hamburger bar (mobile), topbar (project name, theme toggle, + New Task button), content panel with `border-radius: 16px` and `#111` background
- Bottom nav (mobile): Tasks, Sessions, Projects
- Setup wizard modal (restyled from current)
- Theme toggle JS (reuse current `toggleTheme` logic, update to use `fetch('/set-theme', ...)`)
- Wizard open/close JS

- [ ] **Step 4: Create app.js**

Create `src/agents/static/app.js`:
- `toggleSidebar()` / `closeSidebar()` — mobile drawer with backdrop
- `openPanel()` / `closePanel()` — right panel / bottom sheet
- `openProjectsSheet()` / `closeProjectsSheet()` — mobile projects list
- `openWizard()` / `closeWizard()` — setup wizard modal
- Keyboard: Escape closes all open panels
- Touch: swipeable sheets (reuse `_makeSwipeable` pattern from current dashboard.js)

- [ ] **Step 5: Run test — must pass**

Run: `cd /Users/vini/Developer/agents && uv run pytest tests/test_dashboard_html.py::test_base_renders_l_chrome -v`

- [ ] **Step 6: Delete old dashboard.js**

```bash
rm src/agents/static/dashboard.js
```

- [ ] **Step 7: Commit**

```bash
git add src/agents/templates/base.html src/agents/static/app.js
git add -u src/agents/static/dashboard.js
git commit -m "feat(ui): L-chrome base layout with floating content panel"
```

---

## Task 4: Task List View & Partials

**Files:**
- Create: `src/agents/templates/tasks.html`
- Create: `src/agents/templates/partials/task_card.html`
- Create: `src/agents/templates/partials/task_card_done.html`
- Create: `src/agents/templates/partials/stats_line.html`
- Create: `src/agents/templates/project-picker.html`
- Modify: `src/agents/dashboard_html.py` — update routes

- [ ] **Step 1: Write tests for task list routes**

Add to `tests/test_dashboard_html.py`:
```python
def test_hub_tasks_renders_new_template(app_with_dashboard_with_project):
    r = app_with_dashboard_with_project.get("/hub/test-project/tasks")
    assert r.status_code == 200
    # Should contain stats line and task card structure
    assert 'stats-line' in r.text or 'running' in r.text

def test_project_picker_renders(app_with_dashboard):
    r = app_with_dashboard.get("/dashboard")
    assert r.status_code == 200
    # Should render project picker when no project selected
    assert 'paperweight' in r.text.lower()
```

- [ ] **Step 2: Run tests — must fail**

Run: `cd /Users/vini/Developer/agents && uv run pytest tests/test_dashboard_html.py::test_hub_tasks_renders_new_template tests/test_dashboard_html.py::test_project_picker_renders -v`

- [ ] **Step 3: Create partials**

Create `src/agents/templates/partials/task_card.html`:
- Uses `task_card(item)` macro from macros.html
- HTMX: `hx-get="/hub/{{ project_id }}/task/{{ item.id }}"` → swap into content panel

Create `src/agents/templates/partials/task_card_done.html`:
- Uses `task_card_done(item)` macro

Create `src/agents/templates/partials/stats_line.html`:
- Uses `stats_line(counts, budget_spent, budget_total)` macro
- HTMX polling: `hx-get` every 10s for fallback updates

- [ ] **Step 4: Create tasks.html**

Create `src/agents/templates/tasks.html`:
- Extends `base.html`
- Block `topbar`: project name + theme toggle + New Task button
- Block `content`: stats_line partial + loop of task_card / task_card_done partials
- Empty state: "No tasks yet" centered with + New Task button
- Loading: skeleton cards on initial HTMX swap

- [ ] **Step 5: Create project-picker.html**

Create `src/agents/templates/project-picker.html`:
- Extends `base.html`
- Shows project cards with summary counts (running, review, cost)
- Each card is clickable → navigates to project task list

- [ ] **Step 6: Update dashboard_html.py routes**

Modify `src/agents/dashboard_html.py`:
- `/dashboard` → render `project-picker.html` (was `dashboard.html`)
- `/hub/{project_id}/tasks` → render `tasks.html` (was `hub/tasks.html`)
- `/hub/{project_id}` → redirect to `/hub/{project_id}/tasks` (was `hub/panel.html`)
- Keep `/setup/discover`, `/setup/create`, `/set-theme` unchanged

- [ ] **Step 7: Run tests — must pass**

Run: `cd /Users/vini/Developer/agents && uv run pytest tests/test_dashboard_html.py -v`

- [ ] **Step 8: Commit**

```bash
git add src/agents/templates/tasks.html src/agents/templates/project-picker.html
git add src/agents/templates/partials/task_card.html src/agents/templates/partials/task_card_done.html
git add src/agents/templates/partials/stats_line.html
git add src/agents/dashboard_html.py tests/test_dashboard_html.py
git commit -m "feat(ui): task list view with bold cards and project picker"
```

---

## Task 5: Task Detail View

**Files:**
- Create: `src/agents/templates/task-detail.html`
- Create: `src/agents/templates/partials/activity_event.html`
- Create: `src/agents/static/task-detail.js`
- Create: `src/agents/static/stream.js`
- Delete: `src/agents/static/agent.js`, `src/agents/static/ws.js`
- Modify: `src/agents/dashboard_html.py` — add task detail route

- [ ] **Step 1: Write test for task detail route**

Add to `tests/test_dashboard_html.py`:
```python
def test_hub_task_detail_route(app_with_dashboard_with_project_and_task):
    r = app_with_dashboard_with_project_and_task.get("/hub/test-project/task/test-task-id")
    assert r.status_code == 200
    assert 'task-detail' in r.text or 'Back to tasks' in r.text.lower() or 'back' in r.text.lower()
```

Create the needed fixture `app_with_dashboard_with_project_and_task` that creates a project and a work item.

- [ ] **Step 2: Run test — must fail**

Run: `cd /Users/vini/Developer/agents && uv run pytest tests/test_dashboard_html.py::test_hub_task_detail_route -v`

- [ ] **Step 3: Create activity_event.html partial**

Create `src/agents/templates/partials/activity_event.html`:
- Renders a single activity event: icon (tool type), tool name, file path, timestamp
- Color-coded left border by tool type (edit=green, bash=amber, default=purple)

- [ ] **Step 4: Create task-detail.html**

Create `src/agents/templates/task-detail.html`:
- Back link: `← Back to tasks` (HTMX swap back to task list)
- Task header: status dot + label, duration, model badge, cost
- Task title (17px bold)
- Source badge + source name
- Tab bar: Activity (default), Output, Chat
- Tab content area (`#tab-content`)
- Action bar (conditional): Cancel (if running), Rerun (if done/failed), View PR (if pr_url)
- Error display: red-tinted container if status=failed
- Loads `task-detail.js` and `stream.js`

- [ ] **Step 5: Create stream.js**

Create `src/agents/static/stream.js`:
- `connectRunStream(runId, onEvent, onClose, onError)` — WebSocket to `/ws/runs/{runId}`
- `connectGlobalStream(onEvent)` — WebSocket to `/ws/runs`
- Auto-reconnect with exponential backoff (1s, 2s, 4s, max 30s)
- Disconnection banner helper

- [ ] **Step 6: Create task-detail.js**

Create `src/agents/static/task-detail.js`:
- `initTaskDetail(config)` — initialize from DOM data attributes (task_id, session_id, run_id, project_id)
- `loadActivityFeed(runId)` — fetch `/api/runs/{runId}/events`, render as activity events
- `loadSessionHistory(sessionId)` — fetch `/api/sessions/{sessionId}/events`, render conversation
- `switchTab(tabName)` — show/hide tab content (activity, output, chat)
- `sendChatPrompt(projectId)` — POST to `/api/projects/{projectId}/agent` with session_id in body
- `cancelRun(runId)` — POST to `/runs/{runId}/cancel`
- `rerunTask(taskId)` — POST to `/api/work-items/{taskId}/rerun`
- `renderActivityEvent(event)` — create DOM element for activity event
- Typewriter effect for live streaming (reuse from current agent.js)
- Thinking animation (reuse from current agent.js)

- [ ] **Step 7: Add route to dashboard_html.py**

Add new route:
```python
@app.get("/hub/{project_id}/task/{item_id}", response_class=HTMLResponse)
async def hub_task_detail(request: Request, project_id: str, item_id: str) -> HTMLResponse:
    item = state.task_store.get(item_id) if state.task_store else None
    if not item:
        return HTMLResponse("<p>Task not found</p>", status_code=404)
    session = None
    if item.session_id and hasattr(state, "session_manager") and state.session_manager:
        session = state.session_manager.get_session(item.session_id)
    return _TEMPLATES.TemplateResponse(
        request,
        "task-detail.html",
        {"item": item, "session": session, "id": project_id},
    )
```

- [ ] **Step 8: Run tests — must pass**

Run: `cd /Users/vini/Developer/agents && uv run pytest tests/test_dashboard_html.py -v`

- [ ] **Step 9: Delete old JS files**

```bash
rm src/agents/static/agent.js src/agents/static/ws.js
```

- [ ] **Step 10: Commit**

```bash
git add src/agents/templates/task-detail.html src/agents/templates/partials/activity_event.html
git add src/agents/static/task-detail.js src/agents/static/stream.js
git add src/agents/dashboard_html.py tests/test_dashboard_html.py
git add -u src/agents/static/agent.js src/agents/static/ws.js
git commit -m "feat(ui): task detail view with activity feed, chat, and WebSocket streaming"
```

---

## Task 6: Sessions View & Setup Wizard

**Files:**
- Create: `src/agents/templates/partials/session_row.html`
- Create: `src/agents/templates/setup/wizard.html`
- Modify: `src/agents/dashboard_html.py` — update runs route to sessions

- [ ] **Step 1: Write tests**

Add to `tests/test_dashboard_html.py`:
```python
def test_hub_runs_renders_sessions(app_with_dashboard_with_project):
    r = app_with_dashboard_with_project.get("/hub/test-project/runs")
    assert r.status_code == 200

def test_setup_discover_renders(app_with_dashboard):
    r = app_with_dashboard.post("/setup/discover", data={"name": "test", "repo_path": "/tmp/test"})
    assert r.status_code == 200
```

- [ ] **Step 2: Run tests — must fail (template not found)**

Run: `cd /Users/vini/Developer/agents && uv run pytest tests/test_dashboard_html.py::test_hub_runs_renders_sessions tests/test_dashboard_html.py::test_setup_discover_renders -v`

- [ ] **Step 3: Create session_row.html**

Create `src/agents/templates/partials/session_row.html`:
- Status dot + session title + model badge + cost + timestamp
- Clickable → HTMX to load session detail

- [ ] **Step 4: Update hub_runs route to render sessions with new template**

Modify the `/hub/{project_id}/runs` route in `dashboard_html.py` to render a sessions list using the new partials and base layout, styled with the new design system.

- [ ] **Step 5: Create setup/wizard.html**

Create `src/agents/templates/setup/wizard.html`:
- Restyled step 2 of the wizard with new design tokens
- Source checkboxes with confidence indicators
- Form submission to `/setup/create`

- [ ] **Step 6: Update setup_discover route to render new wizard template**

Change template reference in `setup_discover` from `"setup/step2.html"` to `"setup/wizard.html"`.

- [ ] **Step 7: Run tests — must pass**

Run: `cd /Users/vini/Developer/agents && uv run pytest tests/test_dashboard_html.py -v`

- [ ] **Step 8: Commit**

```bash
git add src/agents/templates/partials/session_row.html src/agents/templates/setup/wizard.html
git add src/agents/dashboard_html.py tests/test_dashboard_html.py
git commit -m "feat(ui): sessions view and restyled setup wizard"
```

---

## Task 7: Cleanup Old Templates & Fix All Tests

**Files:**
- Delete: all old templates listed in "Files to delete" section
- Modify: `tests/test_dashboard_html.py` — fix any remaining broken tests
- Modify: any test that references old template names

- [ ] **Step 1: Delete all old template files**

```bash
rm src/agents/templates/dashboard.html
rm src/agents/templates/coordination.html
rm -rf src/agents/templates/coordination/
rm src/agents/templates/hub/panel.html
rm src/agents/templates/hub/activity.html
rm src/agents/templates/hub/tasks.html
rm src/agents/templates/hub/runs.html
rm src/agents/templates/hub/agent.html
rm src/agents/templates/setup/step2.html
rm src/agents/templates/partials/event_card.html
rm src/agents/templates/partials/work_item_row.html
rm src/agents/templates/partials/task_row.html
rm src/agents/templates/partials/run_row.html
rm src/agents/templates/partials/task_run_row.html
```

- [ ] **Step 2: Update dashboard_html.py — remove coordination routes**

Remove these routes from `dashboard_html.py`:
- `GET /coordination`
- `GET /coordination/claims`
- `GET /coordination/mediations`
- `GET /coordination/timeline`

Also update:
- `/hub/{project_id}/activity` — either remove or redirect to tasks
- `/hub/{project_id}/agent` — redirect to task detail or keep as session chat

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/vini/Developer/agents && uv run pytest tests/ -v --tb=short`

Fix any failures related to old template references, old CSS class names, or removed routes.

- [ ] **Step 4: Run linter**

Run: `cd /Users/vini/Developer/agents && uv run ruff check src/ tests/ --fix`

- [ ] **Step 5: Commit**

```bash
git add -u
git add -A
git commit -m "chore(ui): remove old templates, fix all tests after redesign"
```

---

## Task 8: Final Verification & Deploy

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `cd /Users/vini/Developer/agents && uv run pytest tests/ -v --tb=short`

Expected: ALL PASS

- [ ] **Step 2: Run linter**

Run: `cd /Users/vini/Developer/agents && uv run ruff check src/ tests/`

Expected: No errors

- [ ] **Step 3: Run type checker**

Run: `cd /Users/vini/Developer/agents && uv run pyright src/agents/dashboard_html.py`

Expected: No new errors

- [ ] **Step 4: Manual smoke test — start server locally**

Run: `cd /Users/vini/Developer/agents && uv run agents`

Check in browser:
- `http://localhost:8080` → redirects to `/dashboard`
- Project picker shows all projects
- Click project → task list with bold cards
- Click task → task detail with tabs
- Mobile responsive (resize browser to <768px)
- Theme toggle works
- Setup wizard works

- [ ] **Step 5: Push and deploy**

```bash
git push origin main
```

Then deploy to VPS:
```bash
ssh vps "cd /opt/agents && git pull && docker compose up -d --build"
```

- [ ] **Step 6: Verify production**

Check the live URL to confirm the new UI is working.
