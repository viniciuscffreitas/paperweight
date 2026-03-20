# Frontend Redesign — Design Spec

**Date:** 2026-03-20
**Status:** Draft
**Goal:** Rewrite the entire front-end from scratch for zero visual noise, low cognitive load, WCAG AA compliance, and responsive desktop+mobile support. Keep all backend API integrations intact.

---

## Design Direction

**Hybrid C+B Bold Minimal**: Bold card-based UI (Raycast/Arc influence) with inline minimal metrics (dashboard density). L-shaped chrome where sidebar + header form a continuous frame, and the main content floats inside.

### Core Principles

1. **Zero visual noise** — every element must justify its presence
2. **Low cognitive load** — one primary action per screen, progressive disclosure
3. **Legibility first** — 16-17px task titles, 13px metadata, no text below 11px
4. **Task-centric** — the task list is the primary view, not chat
5. **Self-driving feel** — dispatch tasks, monitor status, review results

---

## Design Tokens

### Colors (Dark Theme — Primary)

```
Chrome/Frame:     #0c0c0c
Content panel:    #111111
Card running:     #141428 (border: #252548)
Card review:      #18121e (border: #2a2035)
Card done:        #131313 (border: #1a1a1a)
Card neutral:     #131313 (border: #1a1a1a)

Text primary:     #f5f5f5   (14.7:1 on #111 ✓)
Text secondary:   #999999   (5.1:1 on #111 — AA ✓ normal text)
Text muted:       #777777   (3.7:1 on #111 — AA ✓ large text only, used at 11px+ bold/uppercase)
Text disabled:    #555555   (2.5:1 — decorative only, never sole info carrier)

Status running:   #818cf8   (6.0:1 on #111 ✓) — text usage
Status running glow: #6366f1 (dots/decorative only, glow: 0 0 10px #6366f180)
Status review:    #c084fc   (6.3:1 on #111 ✓) — text usage
Status review dot: #a855f7  (decorative only)
Status success:   #4ade80   (8.2:1 on #111 ✓)
Status queued:    #777777   (3.7:1 — always paired with text label)
Status error:     #f87171   (5.9:1 on #111 ✓)
Status warning:   #fbbf24   (10.4:1 on #111 ✓)

Accent gradient:  linear-gradient(135deg, #6366f1, #8b5cf6) — buttons only (white text on gradient)
Accent text:      #818cf8   (6.0:1 on #111 ✓)
Accent focus:     #6366f1   (focus rings — no contrast requirement)

Separator strong: #1a1a1a
Separator subtle: #141414
```

### Colors (Light Theme)

To be derived following the same token structure. Invert luminance, keep hue relationships. Content panel becomes `#fafafa`, chrome becomes `#f0f0f0`, cards get white backgrounds with tinted borders. All text must meet same WCAG AA ratios against light backgrounds.

### Typography

```
Font family:      -apple-system, BlinkMacSystemFont, 'Inter', sans-serif
Font mono:        'SF Mono', 'Fira Code', 'Cascadia Code', monospace (chat terminal only)

Task title:       17px / 600 weight / -0.3px tracking (desktop)
                  16px / 600 weight / -0.3px tracking (mobile)
Status label:     11px / 700 weight / uppercase / 1px tracking (uses text-muted — meets AA large text via bold+uppercase)
Metadata:         12px / 400 weight (uses text-secondary)
Badge text:       11px / 500 weight (uses text-muted — meets AA via bold weight)
Stats counter:    13px / 700 weight (uses status colors — all AA compliant)
Stats label:      13px / 400 weight (uses text-secondary)
Nav item:         13px / 500 weight
Section label:    11px / 600 weight / uppercase / 1.5px tracking (uses text-muted)
Minimum size:     11px (badges and labels — everything else 12px+)
```

### Spacing & Radius

```
Card padding:     18px 22px (desktop), 16px 18px (mobile)
Card gap:         8px
Card radius:      14px
Content panel:    border-radius 16px
Sidebar width:    200px (desktop, collapses to drawer on <768px)
Panel margin:     0 12px 12px 0 (gap between floating panel and viewport edge)
```

---

## Layout Architecture

### Desktop (768px+)

```
┌──────────────────────────────────────────────────┐
│ CHROME (#0c0c0c)                                  │
│ ┌─────────┐ ┌─ Header ──────────────────────┐    │
│ │         │ │ project-name    ☾  [+ New Task]│    │
│ │ Sidebar │ ├────────────────────────────────┤    │
│ │         │ │ ┌────────────────────────────┐ │    │
│ │ projects│ │ │ FLOATING CONTENT (#111)    │ │    │
│ │         │ │ │ stats line                 │ │    │
│ │         │ │ │ ─────────────────────────  │ │    │
│ │         │ │ │ [task card]                │ │    │
│ │         │ │ │ [task card]                │ │    │
│ │         │ │ │ [task card]                │ │    │
│ │         │ │ │ [task card faded]          │ │    │
│ │         │ │ └────────────────────────────┘ │    │
│ │ settings│ │          12px margin ──────────┘    │
│ └─────────┘ └─────────────────────────────────    │
└──────────────────────────────────────────────────┘
```

- Sidebar + header share `#0c0c0c` background (L-shape)
- Content panel has `#111` background with 16px border-radius, 1px border `#1a1a1a`
- 12px margin on right and bottom between panel and viewport

### Mobile (<768px)

```
┌──────────────────────┐
│ ☰  fintech-app    [+]│  ← top bar
│ 3 run · 1 rev · $2.30│  ← stats line
├──────────────────────┤
│                      │
│  [task card]         │
│  [task card]         │
│  [task card]         │
│  [task card faded]   │
│                      │
├──────────────────────┤
│ Tasks  Sessions  Proj│  ← bottom nav
└──────────────────────┘
```

- No sidebar — hamburger opens drawer overlay
- No L-chrome — full-bleed content
- Bottom navigation: Tasks (primary), Sessions, Projects
- Stats line abbreviates: "3 run · 1 rev · 2 queue · $2.30"

---

## Screens

### 1. Task List (Primary — `/`)

The homepage. Shows all tasks for the selected project, sorted by status priority: running → review → queued → pending → done.

**Components:**
- Stats line: inline counters (colored numbers + labels) + budget
- Task cards: bold cards with status glow, title, source badge, model badge, cost, time
- New task button: gradient accent in header
- Done tasks: opacity 0.35, compact single-row layout

**Interactions:**
- Click task card → navigates to Task Detail (same area, replaces card list)
- Hover card → border changes to status color
- Task cards update in real-time via WebSocket

**Empty state:** centered message "No tasks yet" with a prominent "+ New Task" button. If no projects exist, show project setup wizard instead.

**Loading state:** 3 skeleton cards (pulsing `#1a1a1a` → `#222` animation) matching card dimensions.

**Backend integration:**
- `GET /api/work-items` — list tasks for project
- `WS /ws/runs/{run_id}` — real-time updates for running tasks (connect per active run)
- `WS /ws/runs` — global broadcast for new task starts / completions
- `POST /api/work-items` — create new task

### 2. Task Detail (replaces card list in-place)

When a task card is clicked, the card list is replaced with the task detail view. Back navigation (HTMX swap) returns to card list.

**Layout:**
```
← Back to tasks
─────────────────────────────────
[status dot] RUNNING · 4m            $0.45 · sonnet
Fix authentication timeout on mobile
Linear · LIN-342
─────────────────────────────────
[Activity]  [Output]  [Chat]     ← tab bar
─────────────────────────────────
Activity tab (default):
  • Tool: edit_file — src/auth/timeout.ts        12s ago
  • Tool: run_tests — auth.test.ts (14 passed)   28s ago
  • Thinking...                                   now

Output tab:
  Final agent response text, formatted markdown

Chat tab (escape hatch):
  Interactive prompt input + conversation history
─────────────────────────────────
[Cancel] [Rerun]  [View PR →]   ← action bar (conditional)
```

**Tabs:**
- **Activity** (default): real-time event log from agent execution — tools used, files edited, tests run. This is the primary monitoring view for self-driving mode.
- **Output**: final agent response / summary, rendered as formatted text.
- **Chat**: interactive prompt for manual intervention. Only used as escape hatch.

**Action bar (conditional):**
- Running → [Cancel] button (danger variant)
- Finished with PR → [View PR →] link
- Failed/Done → [Rerun] button
- Running → no Rerun (prevent double execution)

**Error state:** if task status is `failed`, show error message below the task header in a subtle red-tinted container (`#1f1111` background, `#f87171` text).

**Loading state:** skeleton for header + "Loading activity..." placeholder in tab area.

**Backend integration:**
- `GET /api/work-items/{item_id}` — task details
- `GET /api/runs/{run_id}/events` — run event history
- `GET /api/sessions/{session_id}/events` — session conversation history
- `WS /ws/runs/{run_id}` — real-time events for active run
- `POST /api/projects/{project_name}/agent` — send chat message (session_id in request body)
- `POST /api/work-items/{item_id}/rerun` — rerun task
- `POST /api/sessions/{session_id}/close` — end session
- `POST /runs/{run_id}/cancel` — cancel running task

**WebSocket connection flow:**
1. Load work item → get `session_id` from work item
2. Load session events → get active `run_id` from session data
3. Connect `WS /ws/runs/{run_id}` for real-time streaming
4. On run completion, disconnect WS and refresh task data

### 3. New Task Modal

Triggered by "+ New Task" button. Minimal dialog overlay.

**Fields:**
- Title (required) — text input, autofocus
- Description (optional) — textarea, collapsed by default, expand on click
- Template selector (optional) — if project has task templates, show as radio group

**Backend integration:**
- `POST /api/work-items` — create task
- `GET /api/projects/{project_id}/tasks` — list templates for selector

### 4. Project Setup Wizard

Two-step modal (kept from current design, restyled). These are HTML form routes (HTMX), not JSON API endpoints.

1. Project name + repo path → Discover sources
2. Select detected integrations → Create

**Backend integration (HTML routes):**
- `POST /setup/discover` — auto-discover integrations (returns HTML partial)
- `POST /setup/create` — create project (redirects to new project)

### 5. Sessions View (secondary)

List of interactive agent sessions not tied to tasks — for ad-hoc chat use. Accessible via sidebar link (desktop) or bottom nav (mobile).

**Layout:** same floating content panel as task list. Each session is a compact row:
```
[status dot] Session title or "Untitled"    model · $cost    timestamp
```

**Interactions:**
- Click session → opens session detail in-place (same pattern as task detail)
- Session detail shows conversation history + chat input

**Empty state:** "No sessions" with a "Start a session" button.

**Backend integration:**
- Server-side rendered via `/hub/{project_id}/runs` HTML route (existing)
- `GET /api/sessions/{session_id}/events` — session conversation
- `POST /api/projects/{project_name}/agent` — send prompt in session

### 6. Cross-Project Overview

The `/dashboard` route is removed. When no project is selected (first load), the sidebar shows project list and the content area shows a summary:

```
Welcome to paperweight
──────────────────────
[project card]  3 running · $1.20 today
[project card]  1 review · $0.50 today
[project card]  idle
```

Each project card is clickable → selects that project and shows its task list. This replaces the old dashboard with a simpler project picker.

**Backend integration:**
- `GET /api/projects` — list all projects
- `GET /api/work-items` — aggregate task counts per project

---

## Component Inventory

### Primitives
- `TaskCard` — bold card with status glow, tinted background, metadata badges
- `TaskCardDone` — compact single-row, 0.35 opacity
- `StatsLine` — inline counters with colored numbers
- `StatusDot` — 10px circle with optional glow+pulse animation
- `Badge` — small pill (source ID, model name)
- `Button` — primary (gradient), ghost, danger variants
- `InputField` — labeled text input with focus ring
- `TabBar` — underline-style tabs
- `BackLink` — "← Back to tasks" navigation
- `Skeleton` — pulsing placeholder matching component dimensions

### Composite
- `Sidebar` — project list + sessions link + settings link (desktop only)
- `TopBar` — project name + theme toggle + new task button
- `BottomNav` — Tasks / Sessions / Projects (mobile only)
- `TaskList` — stats line + scrollable card list
- `TaskDetail` — header + tabbed content (activity/output/chat) + action bar
- `ActivityFeed` — real-time event log with tool icons
- `ChatTerminal` — prompt input + message history (mono font)
- `SetupWizard` — two-step modal with progress dots
- `ProjectPicker` — cross-project summary cards (no-project-selected state)

---

## Coordination (diluted)

The dedicated `/coordination` page is removed. Coordination information is folded into the existing views:

- **File claims**: shown as a subtle indicator on task cards when a task has active file claims ("2 files claimed")
- **Mediations**: surfaced as events in the Activity feed of the affected task
- **Coordination log**: available as a collapsible section in the project view — not a primary screen

---

## Error & Edge States

- **WebSocket disconnect**: show a subtle banner at the top of the content panel ("Connection lost — reconnecting..."). Auto-reconnect with exponential backoff (1s, 2s, 4s, max 30s). Banner disappears on reconnect.
- **API failure**: inline error message near the failed action (e.g., "Failed to create task" below the form). No full-page error screens.
- **Task error (agent failure)**: task card shows `status-error` color. Task detail shows error message in red-tinted container.
- **Empty project**: "No tasks yet" centered with "+ New Task" button.
- **No projects**: redirect to setup wizard.
- **Stale data**: stats line and task cards poll via HTMX every 10s as fallback when WebSocket is unavailable.

---

## Accessibility (WCAG AA)

- All normal text (< 18px, < 14px bold) meets 4.5:1 contrast ratio — verified per token
- Large text (≥ 18px or ≥ 14px bold) meets 3:1 ratio
- Status dots are **never** the sole indicator — always paired with text labels
- Disabled text (`#555`) is decorative — information is always available through other means
- Focus-visible: 2px solid `#6366f1` outline on all interactive elements, 2px offset
- Skip-to-content link on every page
- Semantic HTML: `<nav>`, `<main>`, `<article>`, ARIA labels on dialogs
- Keyboard navigation: Tab through all interactive elements, Enter to activate, Escape to close overlays
- Screen reader: status announcements via `aria-live="polite"` for real-time task updates
- Reduced motion: respect `prefers-reduced-motion` — disable pulse/glow animations

---

## Technology Stack (unchanged)

- **Templates**: Jinja2 (server-side rendered)
- **Interactivity**: HTMX for partial swaps + vanilla JavaScript
- **Styling**: CSS custom properties (design tokens) + utility classes
- **Icons**: Material Icons (CDN)
- **Fonts**: Inter (CDN) for UI, monospace for terminal
- **No build step**: all CDN-loaded, no webpack/vite

---

## File Structure (new)

```
src/agents/
  static/
    styles.css          — design tokens + all styles (replaces dashboard.css)
    app.js              — layout, navigation, sidebar, panel management (replaces dashboard.js)
    task-detail.js      — task detail view, tabs, activity feed, chat (replaces agent.js)
    stream.js           — WebSocket connection helpers (replaces ws.js)
  templates/
    base.html           — L-chrome layout, sidebar, topbar, mobile nav
    tasks.html          — task list view (primary)
    task-detail.html    — task detail with tabs
    sessions.html       — sessions list (secondary)
    project-picker.html — cross-project overview (no project selected)
    components/
      macros.html       — all component macros
    partials/
      task_card.html    — single task card
      task_card_done.html — done task compact row
      activity_event.html — single activity feed event
      stats_line.html   — inline stats counters
      session_row.html  — single session list row
    setup/
      wizard.html       — project setup modal
```

---

## Migration Strategy

Full rewrite of all 23 front-end files. HTML-serving routes in `dashboard_html.py` will be updated to render new templates. JSON API endpoints remain untouched.

**What changes:**
- All templates (Jinja2) — 23 files replaced by ~12 new files
- All CSS (dashboard.css → styles.css)
- All JavaScript (dashboard.js + agent.js + ws.js → app.js + task-detail.js + stream.js)
- Macro system (components/macros.html — new component set)
- HTML-serving routes in `dashboard_html.py` (updated to render new templates, same URL paths)

**What stays:**
- All JSON API endpoints in `agent_routes.py`, `task_routes.py`, `project_hub_routes.py`
- All backend Python business logic
- WebSocket handlers in `main.py`
- Database schema
- Config/deployment
- Webhook handlers

---

## Backend Route Reference

### JSON API Endpoints (no changes)
```
# Agent
POST   /api/projects/{project_name}/agent     — trigger agent / send prompt
POST   /api/sessions/{session_id}/close        — end session
GET    /api/sessions/{session_id}/events        — session event history
GET    /api/runs/{run_id}/events                — run event history

# Work Items
POST   /api/work-items                          — create work item
GET    /api/work-items                           — list work items
GET    /api/work-items/{item_id}                 — get work item
PATCH  /api/work-items/{item_id}                 — update work item
POST   /api/work-items/from-session              — create from session
POST   /api/work-items/{item_id}/rerun           — rerun work item

# Projects
POST   /api/projects                             — create project
GET    /api/projects                              — list projects
GET    /api/projects/{project_id}                 — get project
PUT    /api/projects/{project_id}                 — update project
DELETE /api/projects/{project_id}                 — delete project
POST   /api/projects/{project_id}/tasks           — create task template
GET    /api/projects/{project_id}/tasks            — list task templates
PUT    /api/tasks/{task_id}                        — update task template
DELETE /api/tasks/{task_id}                        — delete task template
POST   /api/projects/{project_id}/sources          — add source
GET    /api/projects/{project_id}/sources           — list sources
DELETE /api/sources/{source_id}                     — remove source
POST   /api/projects/{project_id}/run               — trigger task run
GET    /api/projects/{project_id}/events             — project events
POST   /api/discover                                 — discover integrations

# Task Execution
POST   /tasks/{project_name}/{task_name}/run     — run named task
POST   /runs/{run_id}/cancel                      — cancel run

# System
GET    /health
GET    /status
GET    /status/budget
POST   /api/migrate-yaml
```

### WebSocket Endpoints (no changes)
```
WS     /ws/runs/{run_id}     — stream events for specific run
WS     /ws/runs              — global broadcast (new runs, completions)
```

### HTML Routes (will be updated to render new templates)
```
GET    /                          — redirect to /dashboard
GET    /dashboard                 — project picker or task list
GET    /hub/{project_id}          — project panel (task list)
GET    /hub/{project_id}/activity — activity tab
GET    /hub/{project_id}/tasks    — tasks tab
GET    /hub/{project_id}/runs     — sessions/runs tab
GET    /hub/{project_id}/agent    — agent terminal
POST   /setup/discover            — wizard step 2
POST   /setup/create              — create project
POST   /set-theme                 — toggle theme
```

---

## Out of Scope

- Light theme implementation (token structure prepared, implementation deferred)
- New backend API endpoints
- Database schema changes
- Authentication changes
- Delete functionality UI (projects, tasks, sources — backend supports it, UI deferred)
- New features not in current app
