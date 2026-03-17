# Project Hub — Centro de Comando do Paperweight

## Overview

Transformar a dashboard do Paperweight de um monitor de runs para um **centro de comando** centrado em projetos. O usuário abre um projeto e vê tudo que está acontecendo: issues do Linear, PRs do GitHub, mensagens do Slack, runs do Paperweight — tudo agregado. Além de visualizar, pode disparar runs, gerenciar tasks, e receber notificações proativas.

## Architecture

```
┌─────────────────────────────────────────────┐
│              Dashboard (NiceGUI)            │
│  ┌──────────┐ ┌──────────┐ ┌─────────────┐ │
│  │ Project  │ │  Runs    │ │  Settings   │ │
│  │   Hub    │ │  (atual) │ │  (novo)     │ │
│  └──────────┘ └──────────┘ └─────────────┘ │
├─────────────────────────────────────────────┤
│           Aggregator Service                │
│  (polling + webhooks → SQLite → broadcast)  │
├─────────────────────────────────────────────┤
│         Integrations (existentes)           │
│  Linear │ GitHub │ Slack ║ Discord (notify) │
└─────────────────────────────────────────────┘
```

Three layers:
- **Dashboard UI** — NiceGUI pages for project hub, task management, settings
- **Aggregator Service** — background polling + webhook ingestion → normalized events in SQLite
- **Integrations** — Linear client exists (`linear_client.py`), Discord notifier exists (`discord_notifier.py`), Slack notifier exists (`notifier.py` — outbound only). GitHub API client and Slack read client (Bot API) are **new builds** (see Prerequisites)

## Prerequisites — New Integrations Required

### GitHub API Client (new)
The codebase only has `webhooks/github.py` for receiving webhook events. A new `github_client.py` must be built to poll: open PRs, CI/check status, branches. Uses PyGithub or httpx with GitHub REST API.

### Slack Bot Client (new)
The codebase only has `notifier.py` which sends messages via webhook URL (outbound only). A new `slack_client.py` must be built using the Slack Bot API to *read* channel messages and search. Requires a Slack Bot token with scopes: `channels:history`, `groups:history`, `search:read`, `channels:read`, `users:read`. This is a significant new integration — not an extension of the existing webhook notifier.

### Existing code to extend
- `discovery.py` — already does Linear team discovery and Discord channel discovery by name. Will be extended with GitHub and Slack discovery.
- `linear_client.py` — existing GraphQL client. Will be extended with additional queries for polling.
- `notifier.py` / `discord_notifier.py` — existing outbound notification. Will be reused by the Notification Engine.

## Data Model

### New SQLite Tables

#### `projects`
Stores project configuration. During migration, both YAML and SQLite configs are supported — the system merges both, with SQLite taking precedence on conflicts. After migration is complete, YAMLs are kept as backup but no longer read.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | Unique project identifier |
| name | TEXT | Display name (e.g., "MomEase") |
| repo_path | TEXT | Local repository path |
| default_branch | TEXT | Default git branch |
| created_at | DATETIME | Creation timestamp |
| updated_at | DATETIME | Last update timestamp |

#### `project_sources`
Maps projects to their data sources.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| project_id | TEXT FK | Reference to projects |
| source_type | TEXT | "linear", "github", "slack" |
| source_id | TEXT | Native ID (Linear project ID, repo full name, Slack channel ID) |
| source_name | TEXT | Human-readable name |
| config | JSON | Source-specific config (e.g., which events to monitor) |
| enabled | BOOLEAN | Toggle without deleting |
| created_at | DATETIME | When the source was linked |
| updated_at | DATETIME | Last modification |

#### `tasks`
Stores task definitions (replaces task entries in YAML project files).

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| project_id | TEXT FK | Reference to projects |
| name | TEXT | Task display name |
| intent | TEXT | What the agent should do |
| trigger_type | TEXT | "manual", "schedule", "webhook" |
| trigger_config | JSON | Cron expression, webhook event filters, etc. |
| model | TEXT | "opus", "sonnet", "haiku" |
| max_budget | REAL | Max cost per run |
| autonomy | TEXT | "pr-only", "auto-merge", "notify" |
| enabled | BOOLEAN | Active/paused toggle |
| created_at | DATETIME | Creation timestamp |
| updated_at | DATETIME | Last update timestamp |

Note: The existing `TaskConfig` model validator enforces `schedule XOR trigger`. A new `trigger_type = "manual"` option will be added, where neither schedule nor webhook trigger is set — the task only runs when explicitly launched from the dashboard or API.

#### `aggregated_events`
Normalized feed of events from all sources.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| project_id | TEXT FK | Reference to projects |
| source | TEXT | "linear", "github", "slack", "paperweight" |
| event_type | TEXT | "issue_created", "pr_opened", "message", "run_completed", etc. |
| title | TEXT | Short description |
| body | TEXT | Optional details |
| author | TEXT | Who triggered the event |
| url | TEXT | Link to original item |
| priority | TEXT | "urgent", "high", "medium", "low", "none" |
| timestamp | DATETIME | When the event occurred |
| source_item_id | TEXT | Native ID for deduplication |
| raw_data | JSON | Original payload for reference |

Deduplication: UNIQUE constraint on `(source, source_item_id)`. On conflict, update.

#### `notification_rules`
Per-project notification configuration.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| project_id | TEXT FK | Reference to projects |
| rule_type | TEXT | "digest" or "alert" |
| channel | TEXT | "slack", "discord", or both |
| channel_target | TEXT | Channel ID or "dm" |
| config | JSON | Rule-specific config (schedule, event types, quiet hours) |
| enabled | BOOLEAN | Toggle |

#### `notification_log`
History of sent notifications for anti-spam and debugging.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| project_id | TEXT FK | Reference to projects |
| rule_id | TEXT FK | Which rule triggered it |
| event_id | TEXT FK | Which event triggered it (nullable for digests) |
| sent_at | DATETIME | When sent |
| channel | TEXT | Where it was sent |
| content | TEXT | What was sent |

## Component 1: Aggregator Service

Background service running inside FastAPI (asyncio tasks).

### Polling

| Source | What it fetches | Default interval |
|--------|----------------|-----------------|
| Linear | Open issues, status changes, comments | 5 min |
| GitHub | Open PRs, CI status, branches | 5 min |
| Slack | Messages in monitored channels, mentions | 2 min |

Intervals configurable per project. Polling complements webhooks — ensures nothing is missed if a webhook fails.

### Event normalization

All events normalized to the `aggregated_events` schema. Each source adapter maps native events to normalized format.

### Deduplication

Webhooks and polling may capture the same event. Dedup by `source` + native item ID. If exists, update instead of insert.

### Auto-discovery

Extends the existing `discovery.py` module (which already handles Linear team and Discord channel discovery by name). New capabilities:
- **Linear**: fuzzy name search on projects/teams (extend existing `auto_discover_project_ids`)
- **GitHub**: fuzzy name search on org repos (new — uses GitHub API client)
- **Slack**: channel name search + `search.messages` API to find channels where project name is mentioned frequently (new — uses Slack Bot client)

Results presented in setup wizard. Confidence scoring: exact name match = high, contains match = medium, mention-frequency-only = low. High confidence sources are pre-checked in the wizard.

### Failure recovery

Polling tasks use a simple retry strategy: on exception, log the error, wait 30s, and retry. After 3 consecutive failures for a source, mark it as degraded in the UI (yellow indicator) and back off to 15 min intervals. Recovery is automatic when the next poll succeeds.

### Data retention

`aggregated_events` are retained for 90 days by default. A daily cleanup task purges older entries. Configurable per project in settings.

## Component 2: Project Hub UI

### Sidebar changes

```
┌─────────────┐
│  Projects   │  ← new section at top
│   MomEase   │
│   Other     │
├─────────────┤
│  Runs       │  ← existing view (kept)
├─────────────┤
│  Settings   │  ← new
└─────────────┘
```

### Project page layout

**Header**: Project name + action buttons (▶ Run, + Task, ⚙ Config)

**Zone 1 — Feed (top)**
Unified reverse-chronological timeline of events from all sources.
- Icon per source (Linear, GitHub, Slack, Paperweight)
- Timestamp, title, author
- Link to original item
- Inline filters: by source, event type, date range

**Zone 2 — Sections (bottom)**
Collapsible cards, one per source:

| Card | Content |
|------|---------|
| **Linear** | Open issues grouped by status, priority counters |
| **GitHub** | Open PRs, CI status, active branches |
| **Slack** | Recent messages from monitored channels, mention highlights |
| **Runs** | Recent Paperweight runs, status, cost |

Each card has "view more" to expand with full details.

## Component 3: Setup Wizard

Three-step flow when creating a new project in the dashboard:

### Step 1 — Basics
- Project name
- Repository path
- Default branch

### Step 2 — Auto-discovery
Aggregator searches for sources matching project name (fuzzy: "momease", "mom-ease", "mom ease").

Presents results as checklist:
```
Found these sources for "MomEase":

Linear
  ☑ Project "MomEase" (team Mobile)
  ☐ Project "MomEase-Backend" (team Platform)

GitHub
  ☑ repo momease-app
  ☑ repo momease-api

Slack
  ☑ #dev-momease (channel)
  ☑ #momease-deploys (channel)
  ☐ #mobile-general (frequent mentions)
```

User confirms, unchecks, or adds manually.

### Step 3 — Notifications
- Where to receive: Slack DM, specific channel, Discord, or both
- Digest schedule (default: 9:00 AM)
- Urgent alerts: enabled by default

### YAML migration

On first dashboard load with existing YAML projects, offer to import:
> "Found 3 projects configured in YAML. Import to dashboard?"

Import to SQLite, keep YAMLs as backup.

## Component 4: Task Manager

### Task CRUD — Visual form

| Field | Input |
|-------|-------|
| Name | text |
| Intent | textarea — what the agent should do |
| Trigger | dropdown: Manual, Schedule (visual cron picker), Webhook (Linear/GitHub) |
| Model | dropdown: opus, sonnet, haiku |
| Budget | slider or numeric input (max cost per run) |
| Autonomy | dropdown: pr-only, auto-merge, notify |

For webhook triggers, contextual sub-options:
- Linear: which events (issue created, label added, status changed)
- GitHub: which events (push, PR opened, review approved)

### Task list

Table per project: status (active/paused), last run, next scheduled run. Toggle to pause/activate without deleting.

## Component 5: Run Launcher

**▶ Run** button in project header opens modal:

### Option 1 — Run existing task
Dropdown with project tasks. Select and trigger.

### Option 2 — Ad-hoc run
Textarea for free-form intent. Choose model and budget. Runs once without saving as task.

### During run
- Redirect to live stream (reuses existing streaming UI)
- Badge on project indicates "running" with spinner
- On completion, event appears in project feed

### Run history per project
In the Runs section of Project Hub:
- Status (success, failure, in progress)
- Originating task
- Cost, duration
- Link to created PR (if any)
- Button to view full output (reuses existing drawer)

## Component 6: Notification Engine

### Daily digest

Scheduler runs at configured time per project (default: 9 AM).

Generates aggregated summary:
```
📋 MomEase — Daily Summary

Linear: 3 open issues (1 urgent), 2 closed yesterday
GitHub: 2 PRs awaiting review, CI green
Slack: 12 messages in #dev-momease, 3 mentions of you
Runs: 1 run completed (PR #23 created), cost $0.42

⚠ Action needed:
  → Issue "Fix crash on login" marked as urgent
  → PR #21 awaiting your review for 2 days
```

Sent via Slack DM, channel, and/or Discord — configurable per project.

### Real-time alerts

Triggered immediately when:

| Event | Source |
|-------|--------|
| Issue with urgent/critical priority created | Linear |
| Direct mention of you | Slack |
| CI failing on open PR | GitHub |
| Paperweight run failed | Internal |

Each alert includes direct link to item + link to project dashboard.

### Anti-spam

- **Cooldown per type**: same alert type for same item doesn't repeat within 30 min
- **Grouping**: if 5 urgent issues are created in sequence, groups into single notification
- **Quiet hours**: optional, configurable (e.g., no alerts between 10 PM - 8 AM)
- All configurable in project settings page

## Implementation Phases

Recommended build order:

1. **Data model + Project CRUD** — SQLite tables, project create/edit/delete API
2. **Task Manager** — tasks table, CRUD UI, TaskConfig model changes for "manual" trigger
3. **Run Launcher** — manual run trigger from dashboard, ad-hoc runs
4. **Aggregator — Linear** — polling with existing `linear_client.py`, event normalization
5. **GitHub API client + Aggregator** — new client, polling for PRs/CI
6. **Slack Bot client + Aggregator** — new client, polling for messages/mentions
7. **Project Hub UI** — feed + section cards + sidebar
8. **Auto-discovery** — extend `discovery.py` with GitHub + Slack
9. **Notification Engine** — digest first, then real-time alerts, then anti-spam
10. **YAML migration wizard** — import existing configs

Each phase is independently deployable and testable.

## Migration Strategy

1. New SQLite tables are additive — no breaking changes to existing schema
2. During transition, both YAML and SQLite configs are supported — system merges both, SQLite takes precedence on conflicts
3. Import wizard migrates YAML → SQLite on first use, keeps YAMLs as backup
4. After full migration, YAMLs are no longer read (but not deleted)
5. Existing webhook handlers extended to also feed Aggregator
6. Existing dashboard pages (runs, streaming) remain untouched
7. `TaskConfig` model updated to support `trigger_type = "manual"` (relaxes existing `schedule XOR trigger` validator)

## Success Criteria

- User can create a project in the dashboard without touching YAML
- Opening a project shows aggregated feed from Linear, GitHub, Slack, and Paperweight
- Tasks can be created, edited, paused, and deleted visually
- Runs can be triggered from the dashboard (existing task or ad-hoc)
- Daily digest arrives at configured time with accurate summary
- Urgent alerts fire within 2 minutes of triggering event
- Auto-discovery finds relevant sources with reasonable accuracy
