# Dashboard Clean Refinement

## Problem

The current dashboard has high cognitive load: five stat cards, emoji-heavy live stream, a manual trigger section, a scheduled tasks table, and a run history table all compete for attention at the same level of visual hierarchy. The user's primary workflows — monitoring active runs and investigating failures — are buried in noise.

## Goals

- Eliminate visual noise: remove decorative elements that don't aid comprehension
- Establish clear hierarchy: header → two content panels
- Optimize for the two primary workflows: monitoring active runs and investigating failures
- Reduce sections from 5 to 2 (live stream + run history)

## Non-Goals

- Redesigning the run detail drawer layout (only applying color consistency)
- Adding new features or data sources
- Changing the WebSocket/data flow architecture

## Design

### Header (Compact)

Single-row header replacing the current header + 5 stat cards:

```
[Agent Runner]  |  ● 1 active  ● 1 failed     $2.40 / $10.00 [━━░░░░] [▶ Run]
```

- **Left**: "Agent Runner" label + optional DRY RUN badge
- **Center-left**: Active count (blue pulsing dot) + Failed count (red dot), separated from title by a subtle vertical divider. These are the only two stats surfaced — they answer "is something running?" and "did something break?"
- **Right**: Budget label + thin progress bar + compact "▶ Run" trigger button
- The trigger button opens a **popover/dropdown** with project + task selectors and a run button — not a dedicated section

### Two Panels (Full-Height)

The body is a two-panel split occupying `calc(100vh - header height)`:

#### Live Stream (flex: 1.2, left)

- Section label: "Live Stream" in uppercase gray, small
- Plain text log, no emojis anywhere
- Color hierarchy by event type:
  - Timestamp: `#4b5563` (dark gray)
  - Run ID `[project/task]`: `#6b7280` (medium gray)
  - Lifecycle events (session started, task_started): `#22d3ee` (cyan)
  - Tool use (Read, Bash, Edit, etc.): `#d4d4d8` (light gray)
  - Assistant messages: `#a1a1aa` (muted gray)
  - Success/done: `#4ade80` (green)
  - Failure/error: `#f87171` (red)
- Tool results (`tool_result` type): `#6b7280` (medium gray) — intentionally muted as they're secondary detail
- Max 200 lines, 150ms drain interval (unchanged)

#### Run History (flex: 1, right)

- Section label: "Run History" in uppercase gray, small
- Simplified columns: **Project**, **Task**, **Status** (colored dot, no emoji), **Time**
- Removed columns: Model, Cost — this detail lives in the run detail drawer
- Row click opens the existing drawer (unchanged behavior)
- Table header: dark background, small uppercase labels

### Removed Sections

| Section | Disposition |
|---|---|
| 5 Stat Cards | Replaced by 2 inline indicators in header (Active, Failed) |
| Manual Trigger section | Collapsed into header button + popover |
| Scheduled Tasks table | Removed from dashboard view entirely |
| Stream badge ("idle"/"active") | Removed — redundant with Active indicator in header |

### Run Detail Drawer

Keeps existing layout and functionality. Changes:

- Remove emojis from event HTML rendering (same color-only treatment as live stream)
- Consistent color palette with the stream
- Header badges (model, trigger, duration, cost) remain — the drawer is the right place for detailed metadata

### Formatter Changes

**`dashboard_formatters.py`:**

- `format_event_line()`: Remove emoji prefixes. Output format becomes: `[project/task] content` (plain text, no icons)
- `format_event_html()`: Remove emoji icons. Use colored text only, consistent with stream palette
- `build_history_rows()`: Status field changes from emoji (✅/❌/🔄) to `raw_status` string — the dot is rendered via CSS/HTML in the table
- `_HISTORY_COLS`: Remove `model` and `cost` columns

**Constants that become unused:**
- `EVENT_ICONS` — no longer referenced (can be removed or kept for potential API use)
- `STATUS_ICONS` — no longer referenced
- `TOOL_ICONS` — no longer referenced (tool names are displayed as plain text)

### CSS Changes

**`_DASHBOARD_CSS`:**

- Remove `.stat-card` styles
- Remove `.panel-card` styles (panels are now borderless divisions of the viewport)
- Add `.header-stats` for inline indicators
- Add `.trigger-popover` for the run trigger dropdown
- Panels use `height: calc(100vh - <header>)` for full-height layout
- Status dots rendered via CSS classes (`.status-dot.running`, `.status-dot.failed`, etc.)

### Dashboard Structure Changes

**`dashboard.py`:**

- Header: single row with inline stats, budget, trigger button
- Body: single row with two flex children (stream panel, history panel)
- Trigger popover: NiceGUI `ui.menu` or `ui.dialog` anchored to the trigger button, containing project/task selectors
- Remove stat card creation and refresh logic for removed stats (Runs, Success, Cost)
- `refresh()` function updates: Active count, Failed count, budget, history table
- Remove `stream_badge` logic

## Testing

Existing tests mock `ui.*` calls. Changes needed:

- Update `test_dashboard_page_renders_budget_header` to verify new header structure
- Verify inline stats (active/failed counts) are created
- Verify trigger popover is wired correctly
- Formatter tests: update assertions to expect no emoji prefixes
- History row tests: update to expect `raw_status` instead of emoji in status field
