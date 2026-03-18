# UI Refactoring — CSS Variables + Jinja2 Macros

**Date:** 2026-03-17
**Status:** Approved
**Tracker:** Linear

## Problem

The dashboard UI (~1200 lines of HTML) has zero SOT for design tokens:
- 40+ hardcoded color values scattered across 11 template files
- Same patterns repeated 8–38 times (colors, padding, transitions, borders)
- No reusable components — every button/input/row defined inline
- `#right-panel` has `border-left:1px solid #2d3142` inconsistent with L-chrome philosophy

## Goal

1. Single source of truth for all design tokens (CSS custom properties)
2. Reusable Jinja2 macros for all UI primitives and composites
3. Fix `border-left` on `#right-panel` (desktop only) as part of Phase 1
4. Gradual migration — each phase independently testable and reviewable

## Approach

**CSS variables + Jinja2 macros, applied gradually in 3 phases.**

Rationale for Claude Code + devflow:
- CSS vars → changing a color = editing 1 file
- Macros → adding a component = using 1 pattern
- Gradual → each phase has a clear Behavior Contract + TDD + Review Gate

## Architecture

### Token Layer (dashboard.css)

Single `:root` block in `dashboard.css` defines all design tokens:

```css
:root {
  /* backgrounds */
  --bg-chrome:    #0d0f18;
  --bg-content:   #111520;
  --bg-elevated:  #1e2130;
  --bg-overlay:   #1a1d27;

  /* borders */
  --border-subtle:  #1e2130;
  --border-default: #2d3142;
  --border-strong:  #4b5563;

  /* text */
  --text-primary:     #e5e7eb;
  --text-secondary:   #9ca3af;
  --text-muted:       #6b7280;
  --text-disabled:    #4b5563;
  --text-placeholder: #374151;

  /* accent */
  --accent:       #3b82f6;
  --accent-bg:    #1e3a5f;
  --accent-hover: #1d4ed8;

  /* status */
  --status-running: #3b82f6;
  --status-success: #4ade80;
  --status-error:   #f87171;
  --status-warning: #fb923c;
  --status-neutral: #6b7280;

  /* task row semantic backgrounds */
  --bg-task-success: #1a3a1a;
  --bg-task-error:   #2a1a1a;
  --bg-task-hover:   #1a1d27;

  /* source/integration brand colors (intentionally NOT vars — brand identity) */
  /* linear: #5E6AD2, github: #238636, slack: #4A154B, paperweight: #F97316   */
  /* priority: urgent #EF4444, high #F59E0B, medium #3B82F6, low #6B7280     */

  /* semi-transparent overlays (intentionally NOT vars — rgba cannot be tokenized cleanly) */
  /* backdrop:    rgba(0,0,0,0.45) — sidebar-backdrop, panel-backdrop, projects-backdrop     */
  /* box-shadow:  rgba(0,0,0,0.65) — #sidebar.sidebar-open mobile open state                */
}
```

#### Token scope policy

- **In scope for Phase 1:** All hardcoded hex values in HTML template `style=` attributes and `dashboard.css` rules (`html/body`, `:focus-visible`, media query overrides)
- **Out of scope (kept as literals):**
  - `rgba(0,0,0,0.45)` backdrop overlays — semi-transparent, cannot map cleanly to a hex token
  - `source_colors` and `priority_colors` dicts in `event_card.html` — brand/semantic identity colors, not design system tokens. Documented here but left as literals.
  - `border-top: 1px solid #2d3142` in the mobile CSS block for `#right-panel` — this is the **intentional mobile sheet top border** and must be tokenised to `var(--border-default)` but NOT removed

### Component Layer (templates/components/macros.html)

Single file, imported per-template via `{% from "components/macros.html" import ... %}`.
The Jinja2 loader searchpath already covers `templates/` — verify before Phase 2.

**Primitives:**
- `btn(label, variant='primary', onclick='', type='button', aria_label='')` — variants: primary, ghost, danger, dashed
- `input_field(name, placeholder='', required=false, label='')` — with onfocus/onblur handlers
- `status_dot(status)` — maps status string to `--status-*` var
- `section_label(text)` — uppercase monospace label
- `divider()` — horizontal rule using `var(--border-subtle)`

**Composites:**
- `sidebar_item(name, project_id)` — project list item with hover + HTMX attrs
- `panel_header(project_name)` — 44px header with close button (calls `closePanel()`)
- `tab_bar(project_id, active_tab='activity')` — see rendering spec below
- `list_row(content, border=true)` — generic row with hover + optional divider

Note: `content_card` is NOT extracted as a macro — it appears only once in `base.html` as a structural layout element, not a reusable component.

#### `tab_bar` macro rendering spec

The macro renders 3 buttons: ACTIVITY, TASKS, RUNS. For each button `t` where `t` is one of `['activity', 'tasks', 'runs']`:

- If `t == active_tab`: render with `color:var(--text-primary)`, `border-bottom:2px solid var(--accent)`, `data-active="true"`
- If `t != active_tab`: render with `color:var(--text-disabled)`, `border-bottom:2px solid transparent`, no `data-active`
- All 3 buttons: `onclick="activateTab(this)"`, `hx-get="/hub/{{ project_id }}/{{ t }}"`, `hx-target="#tab-content"`, `onmouseover="if (!this.dataset.active) this.style.color='var(--text-secondary)'"`, `onmouseout="if (!this.dataset.active) this.style.color='var(--text-disabled)'"`

### Template Hierarchy (unchanged)

```
base.html (master layout)
└── dashboard.html (extends base.html)

hub/panel.html (HTMX fragment)
├── hub/activity.html
├── hub/tasks.html
└── hub/runs.html

partials/
├── task_row.html
├── run_row.html
└── event_card.html
```

No changes to inheritance structure. Macros are imported, not inherited.

## Phase Plan

### Phase 1 — CSS Variables + border fix

**Scope:**
- Add `:root` token block to `dashboard.css` (as specified above)
- Replace hardcoded hex values with `var(--token)` in: `base.html`, `dashboard.html`, `hub/panel.html`, `hub/activity.html`, `hub/tasks.html`, `hub/runs.html`, `setup/step2.html`, all partials, and `dashboard.css` global rules (`:focus-visible`, `html/body`, media query overrides)
- Remove `border-left:1px solid #2d3142` from `#right-panel` inline style in `base.html` (desktop-only border — mobile `border-top` in `dashboard.css` is kept and tokenised)
- Out-of-scope literals: `rgba()` backdrops, `source_colors`/`priority_colors` dicts

**Test updates required in Phase 1 (before color replacement):**
The following existing tests assert raw hex values and MUST be updated to assert `var(--token)` equivalents as part of the GREEN step — they cannot be left asserting hardcoded hex after tokenisation:
- `test_activity_tab_default_active` — update to assert `var(--accent)` instead of `#3b82f6`
- `test_panel_tab_content_background` — update to assert `var(--bg-content)` instead of `#111520`
- `test_dashboard_chrome_label_contrast` — the assertion checks absence of `color:#6b7280;text-transform:uppercase`; after tokenisation this pattern disappears naturally, but update the assertion to check `var(--text-muted)` is NOT combined with `text-transform:uppercase` in the chrome labels

All other 296 tests must pass unchanged.

**Phase 1 tests to ADD:**
- `test_css_vars_root_defined` — `dashboard.css` file contains `:root {`
- `test_right_panel_no_border_left_desktop` — `#right-panel` inline style does not contain `border-left`
- `test_templates_use_css_vars` — sampled template responses contain `var(--`

Note: "299 tests" refers to the full project test suite across all test files (`pytest --collect-only -q` → 299 collected). `test_dashboard_html.py` alone has 45 tests.

### Phase 2 — Primitive Macros

**Scope:**
- Create `templates/components/macros.html` with 5 primitive macros
- Verify Jinja2 loader searchpath covers `templates/` before implementation
- Migrate all `btn` usages in `base.html` and `setup/step2.html`
- Migrate all `input_field` usages in `base.html` and `setup/step2.html`
- Migrate `status_dot` in `dashboard.html`, `run_row.html`
- Migrate `section_label` in `base.html`

**Tests:** Rendered HTML matches expected structure per variant; macros render `var(--token)` not raw hex; button variants produce correct styles; all 299 tests pass.

### Phase 3 — Composite Macros

**Scope:**
- Add 4 composite macros to `templates/components/macros.html` (sidebar_item, panel_header, tab_bar, list_row)
- Migrate `sidebar_item` in `base.html`
- Migrate `panel_header` + `tab_bar` in `hub/panel.html`
- Migrate `list_row` in partials and hub fragments
- After migration: zero raw hex colors in template `style=` attributes (except the documented out-of-scope literals)

**Tests:**
- All composites render correct HTMX attributes
- `activateTab(this)` present on all 3 tab buttons from `tab_bar` macro
- `data-active="true"` on the initially active tab
- `onmouseover`/`onmouseout` check `this.dataset.active`
- Zero raw hex in template output (excluding documented exceptions)
- All 299 tests pass

## Invariants (MUST NOT CHANGE across all phases)

- All 299 existing tests pass after each phase (with noted updates in Phase 1)
- HTMX attributes (`hx-get`, `hx-target`, `hx-trigger`) preserved on all elements
- `aria-*` attributes preserved on all interactive elements
- Mobile CSS overrides in `dashboard.css` continue working
- Mobile `border-top` on `#right-panel` sheet is preserved (only desktop `border-left` is removed)
- `closePanel()`, `openPanel()`, `activateTab()` JS functions called correctly
- Visual appearance identical (vars resolve to same hex values)
- `source_colors`/`priority_colors` in `event_card.html` unchanged
- `rgba()` backdrop values in `dashboard.css` unchanged (`rgba(0,0,0,0.45)` and `rgba(0,0,0,0.65)` box-shadow)

## Testing Strategy

Each phase uses TDD (RED → GREEN → REFACTOR):
- Phase 1: regex assertions on rendered HTML for `var(--` and absence of `border-left` in `#right-panel`; read `dashboard.css` file directly to assert `:root` block present
- Phase 2: assert macro-generated HTML contains correct structure and `var(--token)` values
- Phase 3: assert HTMX attrs intact, `data-active` logic correct, zero raw hex in templates

Review Gate (`pr-review-toolkit:review-pr`) runs after each phase before commit.
