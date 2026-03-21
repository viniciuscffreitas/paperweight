# UI Refactoring — CSS Variables + Jinja2 Macros Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce CSS custom properties as SOT for all design tokens and extract reusable Jinja2 macros for UI components, making the codebase DRY and easy for Claude Code to navigate.

**Architecture:** Three independent phases each producing a working, tested, committed state. Phase 1 establishes the token layer in `dashboard.css`. Phase 2 adds primitive macros. Phase 3 adds composite macros and completes migration. Each phase uses TDD (RED → GREEN) and ends with the full 299-test suite passing.

**Spec:** `docs/superpowers/specs/2026-03-17-ui-refactoring-design.md`

**Tech Stack:** FastAPI, Jinja2, HTMX, Tailwind CDN (no build step), pytest, Python 3.13

---

## Token Reference (memorize before Phase 1)

| Token | Value | Semantic use |
|-------|-------|-------------|
| `--bg-chrome` | `#0d0f18` | Body, sidebar, topbar, right-panel, hamburger bar |
| `--bg-content` | `#111520` | Content-card, tab-content, wizard card |
| `--bg-elevated` | `#1e2130` | Hover backgrounds (table rows, sidebar items) |
| `--bg-overlay` | `#1a1d27` | Enabled task row bg, event-card hover |
| `--border-subtle` | `#1e2130` | Internal dividers (panel header, tabs, table rows) |
| `--border-default` | `#2d3142` | Cards, inputs default, mobile sheet borders |
| `--border-strong` | `#4b5563` | Button hover borders |
| `--text-primary` | `#e5e7eb` | Main content text |
| `--text-secondary` | `#9ca3af` | Section labels, project names |
| `--text-muted` | `#6b7280` | Timestamps, model, secondary info |
| `--text-disabled` | `#4b5563` | Inactive tabs, very secondary text |
| `--text-placeholder` | `#374151` | Empty states |
| `--accent` | `#3b82f6` | Links, focus, active tab, skip link, checkbox |
| `--accent-bg` | `#1e3a5f` | Primary button bg |
| `--accent-hover` | `#1d4ed8` | Primary button hover |
| `--status-running` | `#3b82f6` | Running status dot |
| `--status-success` | `#4ade80` | Success dot, task ON badge text |
| `--status-error` | `#f87171` | Failure dot, task OFF badge text |
| `--status-warning` | `#fb923c` | Timeout dot |
| `--status-neutral` | `#6b7280` | Cancelled dot |
| `--status-high` | `#34d399` | High-confidence badge (step2.html) |
| `--bg-task-success` | `#1a3a1a` | Task ON badge background |
| `--bg-task-error` | `#2a1a1a` | Task OFF badge background |
| `--bg-task-disabled` | `#12151f` | Disabled task row background |

**Out of scope (keep as literals):**
- `rgba(0,0,0,0.45)` and `rgba(0,0,0,0.65)` — transparency can't map to hex token
- Integration badge styles in `step2.html` `type_styles` dict (`#2d1b5e`, `#9d7de8`, `#1a2030`, `#8b949e`, `#0d2a35`, `#36c5f0`)
- Source/priority brand colors in `event_card.html` (`#5E6AD2`, `#238636`, `#4A154B`, `#F97316`, `#EF4444`, `#F59E0B`, `#6B7280` inside the dicts — the var there would shadow the token semantics)

---

## Chunk 1: Phase 1 — CSS Custom Properties + border-left fix

### Task 1.1: Write failing tests for Phase 1

**Files:**
- Modify: `tests/test_dashboard_html.py`

- [ ] **Step 1: Update 3 existing tests to assert `var(--token)` patterns**

In `tests/test_dashboard_html.py`, find and replace these three tests exactly:

```python
# REPLACE test_activity_tab_default_active
def test_activity_tab_default_active(app_with_project):
    """ACTIVITY tab is initially active: blue border-bottom + white text."""
    resp = app_with_project.get("/hub/p1")
    html = resp.text
    assert "border-bottom:2px solid var(--accent)" in html


# REPLACE test_panel_tab_content_background
def test_panel_tab_content_background(app_with_project):
    """#tab-content must use background:var(--bg-content) to match content-card."""
    resp = app_with_project.get("/hub/p1")
    assert b"background:var(--bg-content)" in resp.content


# REPLACE test_dashboard_chrome_label_contrast
def test_dashboard_chrome_label_contrast(app_with_dashboard):
    """Chrome labels must use var(--text-secondary) not var(--text-muted) for WCAG AA."""
    resp = app_with_dashboard.get("/dashboard")
    html = resp.content
    assert b"color:var(--text-muted);text-transform:uppercase" not in html
```

- [ ] **Step 2: Add 3 new failing tests at the end of the file**

```python
# ---------------------------------------------------------------------------
# Phase 1 — CSS custom properties
# ---------------------------------------------------------------------------

def test_css_vars_root_defined():
    """dashboard.css must define a :root block with CSS custom properties."""
    from pathlib import Path
    css_path = Path(__file__).parent.parent / "src/agents/static/dashboard.css"
    css = css_path.read_text()
    assert ":root {" in css
    assert "--bg-chrome" in css
    assert "--accent" in css
    assert "--text-primary" in css


def test_right_panel_no_border_left_desktop(app_with_dashboard):
    """#right-panel inline style must not have border-left (L-chrome by contrast only)."""
    import re
    resp = app_with_dashboard.get("/dashboard")
    match = re.search(r'id="right-panel"[^>]*style="([^"]*)"', resp.text)
    assert match, "#right-panel not found in HTML"
    assert "border-left" not in match.group(1)


def test_panel_template_uses_css_vars(app_with_project):
    """Panel fragment must use CSS vars, not raw hex for chrome colors."""
    resp = app_with_project.get("/hub/p1")
    html = resp.text
    assert "var(--" in html
    assert "#0d0f18" not in html
    assert "#111520" not in html
    assert "#1e2130" not in html
    assert "#2d3142" not in html
```

- [ ] **Step 3: Run to confirm RED**

```bash
.venv/bin/pytest tests/test_dashboard_html.py::test_activity_tab_default_active \
  tests/test_dashboard_html.py::test_panel_tab_content_background \
  tests/test_dashboard_html.py::test_dashboard_chrome_label_contrast \
  tests/test_dashboard_html.py::test_css_vars_root_defined \
  tests/test_dashboard_html.py::test_right_panel_no_border_left_desktop \
  tests/test_dashboard_html.py::test_panel_template_uses_css_vars -v
```

Expected: 6 FAILED (tests assert var(-- patterns that don't exist yet + border-left still present)

---

### Task 1.2: Add CSS custom properties to dashboard.css

**Files:**
- Modify: `src/agents/static/dashboard.css`

- [ ] **Step 1: Add `:root` block at the very top of dashboard.css (before the `*` rule)**

```css
/* ── Design tokens ── */
:root {
  /* backgrounds */
  --bg-chrome:         #0d0f18;
  --bg-content:        #111520;
  --bg-elevated:       #1e2130;
  --bg-overlay:        #1a1d27;

  /* borders */
  --border-subtle:     #1e2130;
  --border-default:    #2d3142;
  --border-strong:     #4b5563;

  /* text */
  --text-primary:      #e5e7eb;
  --text-secondary:    #9ca3af;
  --text-muted:        #6b7280;
  --text-disabled:     #4b5563;
  --text-placeholder:  #374151;

  /* accent */
  --accent:            #3b82f6;
  --accent-bg:         #1e3a5f;
  --accent-hover:      #1d4ed8;

  /* status */
  --status-running:    #3b82f6;
  --status-success:    #4ade80;
  --status-error:      #f87171;
  --status-warning:    #fb923c;
  --status-neutral:    #6b7280;
  --status-high:       #34d399;

  /* task row semantic backgrounds */
  --bg-task-success:   #1a3a1a;
  --bg-task-error:     #2a1a1a;
  --bg-task-disabled:  #12151f;
}
```

- [ ] **Step 2: Replace hardcoded hex in the rest of dashboard.css**

Apply these exact replacements:

```
html, body { ... background: #0d0f18; color: #e5e7eb; }
→ background: var(--bg-chrome); color: var(--text-primary);

.status-dot.running  { background: #3b82f6; }
→ background: var(--status-running);

.status-dot.success  { background: #4ade80; }
→ background: var(--status-success);

.status-dot.failure, .status-dot.failed { background: #f87171; }
→ background: var(--status-error);

.status-dot.timeout  { background: #fb923c; }
→ background: var(--status-warning);

.status-dot.cancelled{ background: #6b7280; }
→ background: var(--status-neutral);

:focus-visible { outline: 2px solid #3b82f6; }
→ outline: 2px solid var(--accent);

  border-top: 1px solid #2d3142 !important;   (line 55, right-panel mobile)
→ border-top: 1px solid var(--border-default) !important;

  border-top: 1px solid #2d3142 !important;   (line 73, projects-sheet mobile)
→ border-top: 1px solid var(--border-default) !important;

  background: #0d0f18 !important;             (line 94, content-card mobile)
→ background: var(--bg-chrome) !important;
```

Keep unchanged: `rgba(0,0,0,0.45)`, `rgba(0,0,0,0.65)`, all `border-radius`, `box-shadow`.

---

### Task 1.3: Tokenize base.html

**Files:**
- Modify: `src/agents/templates/base.html`

- [ ] **Step 1: Replace all hardcoded hex in base.html inline styles**

Apply this complete replacement mapping:

| Find | Replace with |
|------|-------------|
| `background:#0d0f18` (sidebar, topbar, hamburger, right-panel) | `background:var(--bg-chrome)` |
| `background:#111520` (content-card, wizard-card) | `background:var(--bg-content)` |
| `color:#9ca3af` | `color:var(--text-secondary)` |
| `color:#6b7280` | `color:var(--text-muted)` |
| `color:#4b5563` | `color:var(--text-disabled)` |
| `color:#e5e7eb` | `color:var(--text-primary)` |
| `color:#374151` | `color:var(--text-placeholder)` |
| `color:#3b82f6` | `color:var(--accent)` |
| `background:#3b82f6` (skip link) | `background:var(--accent)` |
| `background:#1e2130` (onmouseover) | `background:var(--bg-elevated)` |
| `background:#1e3a5f` | `background:var(--accent-bg)` |
| `background:#1d4ed8` | `background:var(--accent-hover)` |
| `border:1px solid #2d3142` | `border:1px solid var(--border-default)` |
| `border:1px dashed #2d3142` | `border:1px dashed var(--border-default)` |
| `border:1px solid #1e2130` | `border:1px solid var(--border-subtle)` |
| `border-bottom:1px solid #1e2130` | `border-bottom:1px solid var(--border-subtle)` |
| `border:1px solid #3b82f6` | `border:1px solid var(--accent)` |
| `border:1px solid transparent` | keep as-is |
| `border-color:'#4b5563'` (onmouseover) | `border-color:'var(--border-strong)'` |
| `border-color:'#2d3142'` (onmouseout) | `border-color:'var(--border-default)'` |
| `border-color:'#4b5563'` | `border-color:'var(--border-strong)'` |

**Special: remove `border-left:1px solid #2d3142` from `#right-panel` inline style entirely.**

The right-panel style line currently reads:
```
background:#0d0f18;border-left:1px solid #2d3142;
```
After change:
```
background:var(--bg-chrome);
```
(`border-left` removed completely — L-chrome separation by color contrast only)

**Also fix the bottom-nav template expressions** — the Jinja2 template uses `{{ '#e5e7eb' if ... else '#6b7280' }}` for dynamic colors. Replace these:
```jinja2
color:{{ '#e5e7eb' if current_path == '/dashboard' else '#6b7280' }}
→ color:{{ 'var(--text-primary)' if current_path == '/dashboard' else 'var(--text-muted)' }}

onmouseout="this.style.color='{{ '#e5e7eb' if current_path == '/dashboard' else '#6b7280' }}'"
→ onmouseout="this.style.color='{{ 'var(--text-primary)' if current_path == '/dashboard' else 'var(--text-muted)' }}'"

border-top:2px solid {{ '#3b82f6' if current_path == '/dashboard' else 'transparent' }}
→ border-top:2px solid {{ 'var(--accent)' if current_path == '/dashboard' else 'transparent' }}
```

**Also fix the wizard step dots:**
```
background:#3b82f6 → background:var(--accent)
background:#2d3142 → background:var(--border-default)
```

---

### Task 1.4: Tokenize dashboard.html

**Files:**
- Modify: `src/agents/templates/dashboard.html`

- [ ] **Step 1: Replace all hex in dashboard.html**

```
color:#6b7280 → color:var(--text-muted)
color:#9ca3af → color:var(--text-secondary)
color:#e5e7eb → color:var(--text-primary)
color:#3b82f6 (PR link) → color:var(--accent)
color:#4ade80 (live stream text) → color:var(--status-success)
border-bottom:1px solid #1e2130 → border-bottom:1px solid var(--border-subtle)
border-bottom:1px solid #1a1d27 (table row) → border-bottom:1px solid var(--bg-overlay)
border-top:1px solid #1e2130 → border-top:1px solid var(--border-subtle)
onmouseover background:#1e2130 → background:var(--bg-elevated)
```

---

### Task 1.5: Tokenize hub/panel.html

**Files:**
- Modify: `src/agents/templates/hub/panel.html`

- [ ] **Step 1: Replace all hex in panel.html**

```
color:#e5e7eb → color:var(--text-primary)
color:#6b7280 → color:var(--text-muted)
color:#4b5563 → color:var(--text-disabled)
color:#9ca3af → color:var(--text-secondary) (onmouseover hover)
border-bottom:1px solid #1e2130 → border-bottom:1px solid var(--border-subtle)
border-bottom:2px solid #3b82f6 → border-bottom:2px solid var(--accent)
border-bottom:2px solid transparent → keep as-is
background:var(--bg-content) already done in previous task (tab-content)
```

Note: `background:var(--bg-content)` was added to `#tab-content` in the previous bugfix. Verify it's already tokenized.

---

### Task 1.6: Tokenize hub fragments and partials

**Files:**
- Modify: `src/agents/templates/hub/activity.html`
- Modify: `src/agents/templates/hub/tasks.html`
- Modify: `src/agents/templates/hub/runs.html`
- Modify: `src/agents/templates/partials/task_row.html`
- Modify: `src/agents/templates/partials/run_row.html`
- Modify: `src/agents/templates/partials/event_card.html`

- [ ] **Step 1: activity.html** (1 hex value)

```
color:#6b7280 → color:var(--text-muted)
```

- [ ] **Step 2: tasks.html** (1 hex value)

```
color:#6b7280 → color:var(--text-muted)
```

- [ ] **Step 3: runs.html** (1 hex value)

```
color:#6b7280 → color:var(--text-muted)
```

- [ ] **Step 4: task_row.html** (full tokenization)

Replace:
```jinja2
{# line 1 #}
{% set bg = "#1a1d27" if task.get("enabled", 1) else "#12151f" %}
→
{% set bg = "var(--bg-overlay)" if task.get("enabled", 1) else "var(--bg-task-disabled)" %}

color:#e5e7eb → color:var(--text-primary)
color:#6b7280 → color:var(--text-muted)

{# badge background #}
background:{{ '#1a3a1a' if task.get('enabled', 1) else '#2a1a1a' }}
→
background:{{ 'var(--bg-task-success)' if task.get('enabled', 1) else 'var(--bg-task-error)' }}

{# badge text color #}
color:{{ '#4ade80' if task.get('enabled', 1) else '#f87171' }}
→
color:{{ 'var(--status-success)' if task.get('enabled', 1) else 'var(--status-error)' }}
```

- [ ] **Step 5: run_row.html** (full tokenization)

```jinja2
{# line 1: status_colors dict #}
{% set status_colors = {"success": "#4ade80", "failure": "#f87171", "running": "#3b82f6", "timeout": "#fb923c", "cancelled": "#6b7280"} %}
→
{% set status_colors = {"success": "var(--status-success)", "failure": "var(--status-error)", "running": "var(--status-running)", "timeout": "var(--status-warning)", "cancelled": "var(--status-neutral)"} %}

border-bottom:1px solid #1e2130 → border-bottom:1px solid var(--border-subtle)
color:#e5e7eb → color:var(--text-primary)
color:#6b7280 → color:var(--text-muted)
color:#3b82f6 (PR link) → color:var(--accent)
```

- [ ] **Step 6: event_card.html** (partial — skip brand colors in dicts)

```
{# onmouseover hover — tokenize #}
onmouseover="this.style.background='#1a1d27'"
→
onmouseover="this.style.background='var(--bg-overlay)'"

{# text colors — tokenize #}
color:#e5e7eb → color:var(--text-primary)
color:#4b5563 → color:var(--text-disabled)
color:#6b7280 → color:var(--text-muted)

{# DO NOT touch source_colors dict or priority_colors dict — brand colors, out of scope #}
```

---

### Task 1.7: Tokenize setup/step2.html

**Files:**
- Modify: `src/agents/templates/setup/step2.html`

- [ ] **Step 1: Replace hex in step2.html**

```
color:#4b5563 → color:var(--text-disabled)
color:#e5e7eb → color:var(--text-primary)
color:#6b7280 → color:var(--text-muted)
color:#9ca3af → color:var(--text-secondary)
color:#34d399 → color:var(--status-high)
border:1px solid #1e2130 → border:1px solid var(--border-subtle)
border-bottom:1px solid #1e2130 → border-bottom:1px solid var(--border-subtle)
border:1px dashed #1e2130 → border:1px dashed var(--border-subtle)
border:1px solid #3b82f6 → border:1px solid var(--accent)
border:1px solid #1e2130 (cancel button) → border:1px solid var(--border-subtle)
background:#1e3a5f → background:var(--accent-bg)
background:#1d4ed8 → background:var(--accent-hover)
accent-color:#3b82f6 → accent-color:var(--accent)

onmouseover borderColor '#2d3142' → 'var(--border-default)'
onmouseover color '#9ca3af' → 'var(--text-secondary)'
onmouseout borderColor '#1e2130' → 'var(--border-subtle)'
onmouseout color '#6b7280' → 'var(--text-muted)'

{# DO NOT touch type_styles dict — integration brand colors, out of scope #}
```

---

### Task 1.8: Run full test suite → GREEN

- [ ] **Step 1: Run the 6 target tests**

```bash
.venv/bin/pytest tests/test_dashboard_html.py::test_activity_tab_default_active \
  tests/test_dashboard_html.py::test_panel_tab_content_background \
  tests/test_dashboard_html.py::test_dashboard_chrome_label_contrast \
  tests/test_dashboard_html.py::test_css_vars_root_defined \
  tests/test_dashboard_html.py::test_right_panel_no_border_left_desktop \
  tests/test_dashboard_html.py::test_panel_template_uses_css_vars -v
```

Expected: 6 PASSED

- [ ] **Step 2: Run full suite**

```bash
.venv/bin/pytest --tb=short -q
```

Expected: 299 passed

- [ ] **Step 3: Commit**

```bash
git add src/agents/static/dashboard.css \
  src/agents/templates/base.html \
  src/agents/templates/dashboard.html \
  src/agents/templates/hub/panel.html \
  src/agents/templates/hub/activity.html \
  src/agents/templates/hub/tasks.html \
  src/agents/templates/hub/runs.html \
  src/agents/templates/setup/step2.html \
  src/agents/templates/partials/task_row.html \
  src/agents/templates/partials/run_row.html \
  src/agents/templates/partials/event_card.html \
  tests/test_dashboard_html.py

git commit -m "refactor(tokens): CSS custom properties como SOT + remove border-left right-panel"
```

---

## Chunk 2: Phase 2 — Primitive Macros

### Task 2.1: Write failing tests for primitive macros

**Files:**
- Modify: `tests/test_dashboard_html.py`

- [ ] **Step 1: Add failing tests at the end of test_dashboard_html.py**

```python
# ---------------------------------------------------------------------------
# Phase 2 — Primitive macros
# ---------------------------------------------------------------------------

def test_btn_primary_renders(app_with_dashboard):
    """btn macro with variant='primary' renders with accent-bg and accent border."""
    # The wizard submit button uses btn(primary) after migration
    resp = app_with_dashboard.get("/dashboard")
    html = resp.text
    # Primary buttons must use token colors, not raw hex
    assert "background:var(--accent-bg)" in html
    assert "border:1px solid var(--accent)" in html


def test_btn_ghost_renders(app_with_dashboard):
    """btn macro with variant='ghost' renders with subtle border."""
    resp = app_with_dashboard.get("/dashboard")
    html = resp.text
    # Ghost/cancel buttons use border-subtle
    assert "border:1px solid var(--border-subtle)" in html


def test_status_dot_macro_renders(app_with_dashboard):
    """status_dot macro renders a span with the correct CSS class."""
    resp = app_with_dashboard.get("/dashboard")
    html = resp.text
    assert 'class="status-dot' in html


def test_macros_file_exists():
    """templates/components/macros.html must exist."""
    from pathlib import Path
    macros_path = (Path(__file__).parent.parent /
                   "src/agents/templates/components/macros.html")
    assert macros_path.exists(), "components/macros.html not found"


def test_macros_file_has_btn():
    """macros.html must define a btn macro."""
    from pathlib import Path
    macros_path = (Path(__file__).parent.parent /
                   "src/agents/templates/components/macros.html")
    content = macros_path.read_text()
    assert "macro btn(" in content


def test_macros_file_has_input_field():
    """macros.html must define an input_field macro."""
    from pathlib import Path
    macros_path = (Path(__file__).parent.parent /
                   "src/agents/templates/components/macros.html")
    content = macros_path.read_text()
    assert "macro input_field(" in content


def test_macros_file_has_status_dot():
    """macros.html must define a status_dot macro."""
    from pathlib import Path
    macros_path = (Path(__file__).parent.parent /
                   "src/agents/templates/components/macros.html")
    content = macros_path.read_text()
    assert "macro status_dot(" in content
```

- [ ] **Step 2: Run to confirm RED**

```bash
.venv/bin/pytest tests/test_dashboard_html.py::test_macros_file_exists \
  tests/test_dashboard_html.py::test_macros_file_has_btn \
  tests/test_dashboard_html.py::test_macros_file_has_input_field \
  tests/test_dashboard_html.py::test_macros_file_has_status_dot -v
```

Expected: 4 FAILED (file doesn't exist yet)

---

### Task 2.2: Create templates/components/macros.html

**Files:**
- Create: `src/agents/templates/components/macros.html`

- [ ] **Step 1: Create the file with all 5 primitive macros**

```jinja2
{# ── Primitive UI macros ── #}
{# Import: {% from "components/macros.html" import btn, input_field, status_dot, section_label, divider %} #}


{# ── btn ────────────────────────────────────────────────────────────────── #}
{# variants: primary | ghost | dashed | danger                               #}
{% macro btn(label, variant='primary', onclick='', type='button', aria_label='') -%}
{% if variant == 'primary' %}
  {%- set _color = 'var(--text-primary)' -%}
  {%- set _bg = 'var(--accent-bg)' -%}
  {%- set _border = '1px solid var(--accent)' -%}
  {%- set _hover_bg = 'var(--accent-hover)' -%}
  {%- set _out_bg = 'var(--accent-bg)' -%}
{% elif variant == 'ghost' %}
  {%- set _color = 'var(--text-muted)' -%}
  {%- set _bg = 'transparent' -%}
  {%- set _border = '1px solid var(--border-subtle)' -%}
  {%- set _hover_bg = '' -%}
{% elif variant == 'dashed' %}
  {%- set _color = 'var(--text-muted)' -%}
  {%- set _bg = 'transparent' -%}
  {%- set _border = '1px dashed var(--border-default)' -%}
  {%- set _hover_bg = '' -%}
{% elif variant == 'danger' %}
  {%- set _color = 'var(--status-error)' -%}
  {%- set _bg = 'transparent' -%}
  {%- set _border = '1px solid var(--status-error)' -%}
  {%- set _hover_bg = '' -%}
{% endif %}
<button type="{{ type }}"
        {% if onclick %}onclick="{{ onclick }}"{% endif %}
        {% if aria_label %}aria-label="{{ aria_label }}"{% endif %}
        style="padding:7px {{ '18px' if variant == 'primary' else '14px' }};font-size:11px;
               color:{{ _color }};background:{{ _bg }};
               border:{{ _border }};border-radius:4px;cursor:pointer;font-family:inherit;
               letter-spacing:.3px;transition:all .15s;"
        {% if variant == 'primary' %}
        onmouseover="this.style.background='{{ _hover_bg }}'"
        onmouseout="this.style.background='{{ _out_bg }}'"
        {% else %}
        onmouseover="this.style.borderColor='var(--border-strong)';this.style.color='var(--text-secondary)'"
        onmouseout="this.style.borderColor='var(--{{ 'status-error' if variant == 'danger' else 'border-subtle' if variant == 'ghost' else 'border-default' }})';this.style.color='{{ _color }}'">
        {%- endif -%}
>{{ label }}</button>
{%- endmacro %}


{# ── input_field ─────────────────────────────────────────────────────────── #}
{% macro input_field(name, placeholder='', required=false, label='') -%}
{% if label %}
<label style="display:block;font-size:9px;color:var(--text-secondary);text-transform:uppercase;
              letter-spacing:1.5px;margin-bottom:6px;">{{ label }}</label>
{% endif %}
<input name="{{ name }}"
       {% if required %}required{% endif %}
       placeholder="{{ placeholder }}"
       autocomplete="off"
       style="width:100%;background:var(--bg-chrome);border:1px solid var(--border-default);
              border-radius:4px;padding:8px 12px;font-size:13px;color:var(--text-primary);
              font-family:inherit;outline:none;box-sizing:border-box;transition:border-color .15s;"
       onfocus="this.style.borderColor='var(--accent)'"
       onblur="this.style.borderColor='var(--border-default)'">
{%- endmacro %}


{# ── status_dot ──────────────────────────────────────────────────────────── #}
{# status: running | success | failure | failed | timeout | cancelled         #}
{% macro status_dot(status) -%}
<span class="status-dot {{ status }}" aria-hidden="true"></span>
{%- endmacro %}


{# ── section_label ───────────────────────────────────────────────────────── #}
{% macro section_label(text) -%}
<div style="padding:4px 12px;font-size:9px;color:var(--text-secondary);
            text-transform:uppercase;letter-spacing:1.5px;margin-bottom:4px;"
     aria-hidden="true">{{ text }}</div>
{%- endmacro %}


{# ── divider ─────────────────────────────────────────────────────────────── #}
{% macro divider() -%}
<div style="height:1px;background:var(--border-subtle);"></div>
{%- endmacro %}
```

- [ ] **Step 2: Run file-existence tests → GREEN**

```bash
.venv/bin/pytest tests/test_dashboard_html.py::test_macros_file_exists \
  tests/test_dashboard_html.py::test_macros_file_has_btn \
  tests/test_dashboard_html.py::test_macros_file_has_input_field \
  tests/test_dashboard_html.py::test_macros_file_has_status_dot -v
```

Expected: 4 PASSED

---

### Task 2.3: Migrate btn usages in base.html

**Files:**
- Modify: `src/agents/templates/base.html`

- [ ] **Step 1: Add macro import at top of base.html's `<body>` content**

In base.html, add this line immediately after `{% extends %}` or at the very top of the `<body>` section (right after the opening `<body>` tag):

```jinja2
{% from "components/macros.html" import btn, input_field, section_label %}
```

Place it before the skip link `<a>` tag.

- [ ] **Step 2: Replace the "add project" dashed button in the sidebar (empty state)**

Find:
```html
<button onclick="openWizard()"
        aria-label="Adicionar projeto"
        style="width:100%;padding:7px 0;font-size:10px;color:#6b7280;background:transparent;
               border:1px dashed #2d3142;border-radius:4px;cursor:pointer;font-family:inherit;
               letter-spacing:.5px;transition:all .15s;"
        onmouseover="this.style.color='#9ca3af';this.style.borderColor='#4b5563'"
        onmouseout="this.style.color='#6b7280';this.style.borderColor='#2d3142'">
  + add project
</button>
```

Replace with:
```jinja2
{{ btn("+ add project", variant='dashed', onclick='openWizard()', aria_label='Adicionar projeto') }}
```

- [ ] **Step 3: Replace wizard Cancel button**

Find:
```html
<button type="button" onclick="closeWizard()"
        style="padding:7px 14px;font-size:11px;color:#6b7280;background:transparent;
               border:1px solid #1e2130;border-radius:4px;cursor:pointer;font-family:inherit;
               letter-spacing:.3px;transition:all .15s;"
        onmouseover="this.style.borderColor='#2d3142';this.style.color='#9ca3af'"
        onmouseout="this.style.borderColor='#1e2130';this.style.color='#6b7280'">
  Cancel
</button>
```

Replace with:
```jinja2
{{ btn("Cancel", variant='ghost', onclick='closeWizard()', type='button') }}
```

- [ ] **Step 4: Replace wizard "Discover sources →" submit button**

Find:
```html
<button type="submit"
        style="padding:7px 18px;font-size:11px;color:#e5e7eb;background:#1e3a5f;
               border:1px solid #3b82f6;border-radius:4px;cursor:pointer;font-family:inherit;
               letter-spacing:.3px;transition:all .15s;"
        onmouseover="this.style.background='#1d4ed8'"
        onmouseout="this.style.background='#1e3a5f'">
  Discover sources →
</button>
```

Replace with:
```jinja2
{{ btn("Discover sources →", variant='primary', type='submit') }}
```

- [ ] **Step 5: Replace wizard input fields**

Find the "Project name" input block:
```html
<div style="margin-bottom:14px;">
  <label style="display:block;font-size:9px;color:#9ca3af;...">Project name</label>
  <input name="name" required placeholder="my-project" ...>
</div>
```

Replace with:
```jinja2
<div style="margin-bottom:14px;">
  {{ input_field("name", placeholder="my-project", required=true, label="Project name") }}
</div>
```

Find the "Repository path" input block similarly and replace with:
```jinja2
<div style="margin-bottom:24px;">
  {{ input_field("repo_path", placeholder="/Users/you/my-project", required=true, label="Repository path") }}
</div>
```

- [ ] **Step 6: Replace "Projects" section label in sidebar**

Find:
```html
<div style="padding:4px 12px;font-size:9px;color:#9ca3af;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:4px;"
     aria-hidden="true">Projects</div>
```

Replace with:
```jinja2
{{ section_label("Projects") }}
```

---

### Task 2.4: Migrate btn usages in setup/step2.html

**Files:**
- Modify: `src/agents/templates/setup/step2.html`

- [ ] **Step 1: Add macro import at top of step2.html**

```jinja2
{% from "components/macros.html" import btn %}
```

- [ ] **Step 2: Replace Cancel button**

```jinja2
{{ btn("Cancel", variant='ghost', onclick='closeWizard()', type='button') }}
```

- [ ] **Step 3: Replace "Create project →" submit button**

```jinja2
{{ btn("Create project →", variant='primary', type='submit') }}
```

---

### Task 2.5: Migrate status_dot in dashboard.html and run_row.html

**Files:**
- Modify: `src/agents/templates/dashboard.html`
- Modify: `src/agents/templates/partials/run_row.html`

- [ ] **Step 1: dashboard.html — add import and migrate status_dot**

Add at top (after `{% extends "base.html" %}`):
```jinja2
{% from "components/macros.html" import status_dot %}
```

In the runs table, find:
```html
<span class="status-dot {{ r.raw_status }}" aria-hidden="true"></span>
<span class="sr-only">{{ r.status }}</span>
```

Replace with:
```jinja2
{{ status_dot(r.raw_status) }}
<span class="sr-only">{{ r.status }}</span>
```

- [ ] **Step 2: run_row.html — add import and migrate status_dot**

Add at top of run_row.html:
```jinja2
{% from "components/macros.html" import status_dot %}
```

Find:
```html
<span class="status-dot {{ run.status }}" style="background:{{ status_colors.get(run.status, '#6b7280') }};"></span>
```

Replace with:
```jinja2
{{ status_dot(run.status) }}
```

Note: the inline `style="background:..."` override is no longer needed because `.status-dot.{status}` CSS classes already apply the correct token colors.

---

### Task 2.6: Verify Phase 2 GREEN

- [ ] **Step 1: Run all Phase 2 tests**

```bash
.venv/bin/pytest tests/test_dashboard_html.py::test_btn_primary_renders \
  tests/test_dashboard_html.py::test_btn_ghost_renders \
  tests/test_dashboard_html.py::test_status_dot_macro_renders \
  tests/test_dashboard_html.py::test_macros_file_exists \
  tests/test_dashboard_html.py::test_macros_file_has_btn \
  tests/test_dashboard_html.py::test_macros_file_has_input_field \
  tests/test_dashboard_html.py::test_macros_file_has_status_dot -v
```

Expected: 7 PASSED

- [ ] **Step 2: Run full suite**

```bash
.venv/bin/pytest --tb=short -q
```

Expected: 299 passed

- [ ] **Step 3: Commit**

```bash
git add src/agents/templates/components/macros.html \
  src/agents/templates/base.html \
  src/agents/templates/dashboard.html \
  src/agents/templates/setup/step2.html \
  src/agents/templates/partials/run_row.html \
  tests/test_dashboard_html.py

git commit -m "refactor(macros): primitivos btn, input_field, status_dot, section_label, divider"
```

---

## Chunk 3: Phase 3 — Composite Macros

### Task 3.1: Write failing tests for composite macros

**Files:**
- Modify: `tests/test_dashboard_html.py`

- [ ] **Step 1: Add failing tests**

```python
# ---------------------------------------------------------------------------
# Phase 3 — Composite macros
# ---------------------------------------------------------------------------

def test_macros_file_has_sidebar_item():
    """macros.html must define a sidebar_item macro."""
    from pathlib import Path
    content = (Path(__file__).parent.parent /
               "src/agents/templates/components/macros.html").read_text()
    assert "macro sidebar_item(" in content


def test_macros_file_has_panel_header():
    """macros.html must define a panel_header macro."""
    from pathlib import Path
    content = (Path(__file__).parent.parent /
               "src/agents/templates/components/macros.html").read_text()
    assert "macro panel_header(" in content


def test_macros_file_has_tab_bar():
    """macros.html must define a tab_bar macro."""
    from pathlib import Path
    content = (Path(__file__).parent.parent /
               "src/agents/templates/components/macros.html").read_text()
    assert "macro tab_bar(" in content


def test_macros_file_has_list_row():
    """macros.html must define a list_row macro."""
    from pathlib import Path
    content = (Path(__file__).parent.parent /
               "src/agents/templates/components/macros.html").read_text()
    assert "macro list_row(" in content


def test_panel_uses_panel_header_macro(app_with_project):
    """Panel fragment must not contain raw 44px header div inline styles."""
    resp = app_with_project.get("/hub/p1")
    html = resp.text
    # After macro migration, the panel renders via macros — no raw hex
    assert "#e5e7eb" not in html
    assert "#6b7280" not in html
    assert "#1e2130" not in html


def test_panel_tab_bar_has_activate_tab(app_with_project):
    """tab_bar macro must render activateTab(this) on all 3 tab buttons."""
    resp = app_with_project.get("/hub/p1")
    html = resp.text
    assert html.count("activateTab(this)") == 3


def test_no_hex_in_hub_templates(app_with_project):
    """Hub panel and its tab fragments must have zero raw hex colors."""
    for path in ["/hub/p1", "/hub/p1/activity", "/hub/p1/tasks", "/hub/p1/runs"]:
        resp = app_with_project.get(path)
        html = resp.text
        import re
        # Find raw hex colors (6-digit) that are NOT inside Jinja template variable dicts
        hex_matches = re.findall(r'(?<!["\'])#[0-9a-fA-F]{6}(?![0-9a-fA-F])', html)
        assert hex_matches == [], f"{path} still has raw hex: {hex_matches}"
```

- [ ] **Step 2: Run to confirm RED**

```bash
.venv/bin/pytest tests/test_dashboard_html.py::test_macros_file_has_sidebar_item \
  tests/test_dashboard_html.py::test_macros_file_has_panel_header \
  tests/test_dashboard_html.py::test_macros_file_has_tab_bar \
  tests/test_dashboard_html.py::test_macros_file_has_list_row -v
```

Expected: 4 FAILED

---

### Task 3.2: Add composite macros to macros.html

**Files:**
- Modify: `src/agents/templates/components/macros.html`

- [ ] **Step 1: Append composite macros to the end of macros.html**

```jinja2

{# ── sidebar_item ───────────────────────────────────────────────────────── #}
{# HTMX: loads hub panel on click, closes sidebar on mobile                  #}
{% macro sidebar_item(name, project_id) -%}
<div hx-get="/hub/{{ project_id }}"
     hx-target="#panel-content"
     hx-on::after-request="openPanel()"
     onclick="closeSidebar()"
     role="button"
     tabindex="0"
     aria-label="Abrir projeto {{ name }}"
     onkeydown="if(event.key==='Enter'||event.key===' '){this.click()}"
     style="padding:8px 12px;font-size:12px;color:var(--text-secondary);cursor:pointer;
            border-radius:4px;margin:1px 6px;transition:background .15s;"
     onmouseover="this.style.background='var(--bg-elevated)';this.style.color='var(--text-primary)'"
     onmouseout="this.style.background='transparent';this.style.color='var(--text-secondary)'">
  {{ name }}
</div>
{%- endmacro %}


{# ── panel_header ────────────────────────────────────────────────────────── #}
{# 44px header matching topbar height for L-chrome continuity                 #}
{% macro panel_header(project_name) -%}
<div style="display:flex;align-items:center;justify-content:space-between;
            padding:0 16px;height:44px;min-height:44px;flex-shrink:0;
            border-bottom:1px solid var(--border-subtle);">
  <span style="font-size:13px;font-weight:700;color:var(--text-primary);
               white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
               max-width:calc(100% - 48px);">{{ project_name }}</span>
  <div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">
    <button onclick="closePanel()"
            aria-label="Fechar painel"
            style="background:transparent;border:1px solid transparent;
                   color:var(--text-muted);cursor:pointer;padding:4px 8px;
                   font-size:11px;font-family:inherit;border-radius:3px;transition:color .15s;"
            onmouseover="this.style.color='var(--text-primary)'"
            onmouseout="this.style.color='var(--text-muted)'">✕</button>
  </div>
</div>
{%- endmacro %}


{# ── tab_bar ──────────────────────────────────────────────────────────────── #}
{# active_tab: 'activity' | 'tasks' | 'runs'                                  #}
{% macro tab_bar(project_id, active_tab='activity') -%}
{% set tabs = [('activity', 'ACTIVITY'), ('tasks', 'TASKS'), ('runs', 'RUNS')] %}
<div style="display:flex;border-bottom:1px solid var(--border-subtle);
            padding:0 12px;flex-shrink:0;">
  {% for tab_id, tab_label in tabs %}
  {% set is_active = (tab_id == active_tab) %}
  <button hx-get="/hub/{{ project_id }}/{{ tab_id }}"
          hx-target="#tab-content"
          onclick="activateTab(this)"
          {% if is_active %}data-active="true"{% endif %}
          style="padding:10px 12px;font-size:10px;text-transform:uppercase;letter-spacing:.8px;
                 color:{{ 'var(--text-primary)' if is_active else 'var(--text-disabled)' }};
                 cursor:pointer;border:none;background:transparent;
                 border-bottom:{{ '2px solid var(--accent)' if is_active else '2px solid transparent' }};
                 margin-bottom:-1px;font-family:inherit;transition:color .15s;
                 white-space:nowrap;flex-shrink:0;"
          onmouseover="if (!this.dataset.active) this.style.color='var(--text-secondary)'"
          onmouseout="if (!this.dataset.active) this.style.color='var(--text-disabled)'">
    {{ tab_label }}
  </button>
  {% endfor %}
</div>
{%- endmacro %}


{# ── list_row ─────────────────────────────────────────────────────────────── #}
{# Generic row: hover highlight + optional bottom divider                      #}
{% macro list_row(content, border=true) -%}
<div style="padding:12px 16px;font-size:13px;color:var(--text-secondary);cursor:pointer;
            {% if border %}border-bottom:1px solid var(--bg-overlay);{% endif %}
            transition:background .15s;"
     onmouseover="this.style.background='var(--bg-elevated)';this.style.color='var(--text-primary)'"
     onmouseout="this.style.background='transparent';this.style.color='var(--text-secondary)'">
  {{ content }}
</div>
{%- endmacro %}
```

- [ ] **Step 2: Run macro existence tests → GREEN**

```bash
.venv/bin/pytest tests/test_dashboard_html.py::test_macros_file_has_sidebar_item \
  tests/test_dashboard_html.py::test_macros_file_has_panel_header \
  tests/test_dashboard_html.py::test_macros_file_has_tab_bar \
  tests/test_dashboard_html.py::test_macros_file_has_list_row -v
```

Expected: 4 PASSED

---

### Task 3.3: Migrate hub/panel.html to use composite macros

**Files:**
- Modify: `src/agents/templates/hub/panel.html`

- [ ] **Step 1: Replace entire panel.html content**

```jinja2
{% from "components/macros.html" import panel_header, tab_bar %}
<!-- Hub panel: header + tabs + tab content area (loaded via HTMX) -->
<div style="display:flex;flex-direction:column;height:100%;">

  {{ panel_header(project.name) }}

  {{ tab_bar(id) }}

  <!-- Tab content — loaded via HTMX, defaults to activity -->
  <div id="tab-content"
       style="flex:1;overflow-y:auto;background:var(--bg-content);"
       hx-get="/hub/{{ id }}/activity"
       hx-trigger="load">
  </div>
</div>
```

---

### Task 3.4: Migrate base.html sidebar to use sidebar_item macro

**Files:**
- Modify: `src/agents/templates/base.html`

- [ ] **Step 1: Add sidebar_item to the import line**

Update the import line (added in Phase 2) to include `sidebar_item`:
```jinja2
{% from "components/macros.html" import btn, input_field, section_label, sidebar_item %}
```

- [ ] **Step 2: Replace the sidebar project loop**

Find:
```html
{% for p in projects %}
<div hx-get="/hub/{{ p.id }}"
     hx-target="#panel-content"
     hx-on::after-request="openPanel()"
     onclick="closeSidebar()"
     role="button"
     tabindex="0"
     aria-label="Abrir projeto {{ p.name }}"
     onkeydown="if(event.key==='Enter'||event.key===' '){this.click()}"
     style="padding:8px 12px;font-size:12px;color:#9ca3af;cursor:pointer;border-radius:4px;
            margin:1px 6px;transition:background .15s;"
     onmouseover="this.style.background='#1e2130';this.style.color='#e5e7eb'"
     onmouseout="this.style.background='transparent';this.style.color='#9ca3af'">
  {{ p.name }}
</div>
{% else %}
```

Replace with:
```jinja2
{% for p in projects %}
{{ sidebar_item(p.name, p.id) }}
{% else %}
```

- [ ] **Step 3: Replace the mobile projects-sheet loop**

Find the similar loop in the `#projects-sheet` section:
```html
{% for p in projects %}
<div hx-get="/hub/{{ p.id }}"
     hx-target="#panel-content"
     hx-on::after-request="closeProjectsSheet(); openPanel()"
     ...
```

This loop has different HTMX behavior (`closeProjectsSheet(); openPanel()`) so do NOT use sidebar_item for it — the macro doesn't cover that variant. Leave it as inline HTML but tokenize any remaining hex colors.

---

### Task 3.5: Final verification — zero hex in hub endpoints

- [ ] **Step 1: Run all Phase 3 specific tests**

```bash
.venv/bin/pytest tests/test_dashboard_html.py::test_macros_file_has_sidebar_item \
  tests/test_dashboard_html.py::test_macros_file_has_panel_header \
  tests/test_dashboard_html.py::test_macros_file_has_tab_bar \
  tests/test_dashboard_html.py::test_macros_file_has_list_row \
  tests/test_dashboard_html.py::test_panel_uses_panel_header_macro \
  tests/test_dashboard_html.py::test_panel_tab_bar_has_activate_tab \
  tests/test_dashboard_html.py::test_no_hex_in_hub_templates -v
```

Expected: 7 PASSED

- [ ] **Step 2: Run full suite**

```bash
.venv/bin/pytest --tb=short -q
```

Expected: 299 passed (all tests from all phases)

- [ ] **Step 3: Run Review Gate**

Invoke `pr-review-toolkit:review-pr` on all changed files.

- [ ] **Step 4: Commit**

```bash
git add src/agents/templates/components/macros.html \
  src/agents/templates/hub/panel.html \
  src/agents/templates/base.html \
  tests/test_dashboard_html.py

git commit -m "refactor(macros): compostos sidebar_item, panel_header, tab_bar, list_row"
```

---

## Summary

After all 3 phases:
- `dashboard.css` — SOT for all design tokens (`:root` block)
- `templates/components/macros.html` — 9 macros (5 primitive + 4 composite)
- All templates — zero hardcoded hex except documented out-of-scope literals
- `#right-panel` — no `border-left` (L-chrome by contrast)
- All 299 tests pass
