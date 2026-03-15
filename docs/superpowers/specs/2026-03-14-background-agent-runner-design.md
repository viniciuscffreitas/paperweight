# Background Agent Runner — Design Spec

## Problem

Vini works across ~8 projects (Sekit, Fintech, MomEase, PrimeLeague, etc.) with different stacks. He already has:
- **Claude Code** as a capable coding agent
- **devflow** as a governance layer (TDD enforcement, lint, review gates, spec-driven dev)

What's missing is the **orchestration layer** — the ability to run Claude Code sessions autonomously on schedules and event triggers, across multiple projects, without manual prompting.

## Vision

A Python service ("Runner") that orchestrates Claude Code CLI sessions in background, inspired by the "background agents" paradigm:
- **Human on the loop** (not in the loop) — agents work, humans review PRs
- **Graduated autonomy** — from PR-only to auto-merge, configured per task
- **Cost-controlled** — model routing, per-task limits, daily budget caps

## Architecture

```
                    ┌─────────────────────────────────────────┐
                    │              agents (FastAPI)            │
                    │                                         │
  ┌──────────┐     │  ┌───────────┐     ┌──────────────┐     │     ┌─────────────┐
  │ GitHub   │────▶│  │ Webhooks  │────▶│              │     │────▶│ Slack       │
  │ Linear   │     │  └───────────┘     │   Executor   │     │     │ (notifica)  │
  └──────────┘     │                    │              │     │     └─────────────┘
                    │  ┌───────────┐     │ - worktree   │     │
                    │  │ Scheduler │────▶│ - claude -p  │     │     ┌─────────────┐
                    │  │ (cron)    │     │ - cleanup    │     │────▶│ PR / merge  │
                    │  └───────────┘     └──────────────┘     │     └─────────────┘
                    │                                         │
                    │  ┌───────────┐                          │
                    │  │ Projects  │ YAML configs por projeto │
                    │  └───────────┘                          │
                    └─────────────────────────────────────────┘
```

**Core principle:** The Runner is NOT an agent. It's an agent manager — it schedules, triggers, isolates, collects results, and notifies. The real agent is Claude Code with devflow.

## Stack

- **Python 3.13** + **uv** (consistent with Sekit agents)
- **FastAPI** — webhook receiver + status API
- **APScheduler** — persistent scheduler (SQLite job store)
- **Claude Code CLI** (`claude -p`) — the execution engine
- **Git worktrees** — manual management (not Claude's built-in `--worktree` flag) for explicit control over paths, cleanup, and concurrent isolation
- **SQLite** — history and job store (zero infra dependency)

## Claude Code CLI Interface

The Runner invokes Claude Code in non-interactive print mode. Key flags:

```bash
claude -p "<prompt>" \
  --model sonnet \                    # Model alias (haiku, sonnet, opus)
  --output-format json \              # Structured output with usage stats
  --max-budget-usd 3.00 \            # Hard cost cap per execution
  --permission-mode auto \            # Autonomous tool use without human prompts
  --no-session-persistence            # Ephemeral — no session saved to disk
```

**Permission mode:** `auto` is used by default. Claude decides tool permissions autonomously within safety bounds. This is required because background execution has no stdin for human approval. The `--dangerously-skip-permissions` flag exists but is NOT used in Phase 1 — `auto` is sufficient and safer.

**JSON output schema** (fields consumed by the Runner):

```json
{
  "result": "text output from the agent",
  "is_error": false,
  "total_cost_usd": 0.1834,
  "num_turns": 12,
  "usage": {
    "input_tokens": 45000,
    "output_tokens": 3200,
    "cache_creation_input_tokens": 12000,
    "cache_read_input_tokens": 8000
  },
  "model": "claude-sonnet-4-6"
}
```

The Runner reads `total_cost_usd` directly from the output for budget tracking — no manual price calculation needed.

**Why manual worktrees instead of Claude's `--worktree` flag:** The Runner needs explicit control over worktree paths (for cleanup, concurrent isolation, and history tracking). Claude's built-in flag creates worktrees in its own location, which doesn't give the Runner visibility into the execution environment.

## Components

### 1. Task Config (YAML per project)

Each project gets a YAML file in `projects/`:

```yaml
# projects/sekit.yaml
name: sekit
repo: /Users/vini/Developer/sekit
base_branch: main                    # Branch to create worktrees from (default: main)
branch_prefix: agents/
notify: slack

tasks:
  dep-update:
    description: "Update dependencies and run tests"
    schedule: "0 3 * * MON"
    model: haiku
    max_cost_usd: 1.00
    autonomy: auto-merge
    prompt: |
      Update all dependencies in this monorepo.
      Run `just check-all`. If tests pass, commit and create a PR.

  ci-fix:
    description: "Investigate and fix CI failure"
    trigger:
      type: github
      events: [check_suite.completed]
      filter:
        conclusion: failure
    model: sonnet
    max_cost_usd: 3.00
    autonomy: pr-only
    prompt: |
      CI failed on branch {{branch}}. Investigate the failure logs,
      fix the issue, and push to the same branch.
```

**Config fields:**
- `name` — Project identifier
- `repo` — Absolute path to the repository
- `base_branch` — Branch to create worktrees from. Default: `main`
- `branch_prefix` — Prefix for branches created by agents (default: `agents/`)
- `notify` — Notification channel (`slack`, `none`)
- `tasks` — Map of task definitions

**Task fields:**
- `description` — Human-readable description
- `schedule` — Cron expression (mutually exclusive with `trigger`)
- `trigger` — Event trigger config (mutually exclusive with `schedule`)
- `trigger.type` — Event source (`github`, `linear`)
- `trigger.events` — List of event types to listen for
- `trigger.filter` — Flat key-value exact match on top-level event payload fields (e.g., `conclusion: failure`). No nested paths, no wildcards. Phase 1 keeps it simple.
- `model` — Claude model alias: `haiku`, `sonnet`, or `opus`. Passed verbatim to `claude --model`. Default: `sonnet`
- `max_cost_usd` — Hard cost cap per execution, passed to `--max-budget-usd`. Default: 5.00
- `autonomy` — `pr-only` (default) or `auto-merge`
- `prompt` — The prompt sent to Claude Code. Supports `{{variable}}` interpolation from event payload

**Available template variables per trigger type:**

| Trigger | Variables |
|---|---|
| `github` / `check_suite` | `{{branch}}`, `{{repo_full_name}}`, `{{conclusion}}`, `{{sha}}` |
| `github` / `pull_request` | `{{branch}}`, `{{pr_number}}`, `{{pr_title}}`, `{{pr_url}}` |
| `github` / `issues` | `{{issue_number}}`, `{{issue_title}}`, `{{issue_body}}` |
| `linear` | `{{issue_id}}`, `{{issue_title}}`, `{{issue_description}}`, `{{assignee}}`, `{{status}}` |
| `schedule` | `{{date}}`, `{{project_name}}` |

### 2. Executor

The core execution engine. For each task run:

```
1. Check budget — abort if daily limit exceeded
2. git worktree add <worktree_base>/<run-id> -b <branch_prefix><task>-<timestamp> <base_branch>
3. cd <worktree_base>/<run-id>
4. claude -p "<prompt>" \
     --model <model> \
     --max-budget-usd <max_cost_usd> \
     --output-format json \
     --permission-mode auto \
     --no-session-persistence
5. Parse JSON output: total_cost_usd, num_turns, is_error, result
6. If success + autonomy=pr-only  → gh pr create
   If success + autonomy=auto-merge → gh pr create && gh pr merge --auto
   If failure → notify with error log
7. git worktree remove <worktree_base>/<run-id> (try/finally — always runs)
8. Record in history (SQLite)
```

**Isolation:** Each task runs in a clean worktree. Tasks never interfere with each other. Concurrent tasks on the same repo use separate worktrees with a per-repo semaphore (max 2 concurrent per repo) to avoid git lock contention on push/PR operations.

**Error handling:**
- Timeout: kill process after `timeout_minutes` (default: 15)
- Budget exceeded mid-task: `--max-budget-usd` hard-stops the CLI; Runner records the partial result
- Worktree cleanup: always runs (try/finally), even on failure or timeout
- Claude CLI crash: record failure, notify, do not retry automatically

**Graceful shutdown (SIGTERM):**
- Send SIGTERM to all running Claude CLI subprocesses
- Wait up to 30 seconds for graceful exit
- Clean up all worktrees
- Mark in-progress runs as `cancelled` in history
- Exit cleanly

### 3. Scheduler

APScheduler with SQLite job store (survives restarts):

- On startup: reads all `projects/*.yaml`, registers scheduled tasks
- Cron expressions for scheduling
- Hot reload: watches `projects/` directory for changes, updates jobs
- Concurrent execution limit: configurable (default: 3 simultaneous tasks)

### 4. Webhooks

FastAPI endpoints for event-driven triggers:

```
GET  /health                       → 200 OK (for process monitors)
POST /webhooks/github              → GitHub webhook receiver
POST /webhooks/linear              → Linear webhook receiver
GET  /status                       → Running tasks, recent history, budget
GET  /status/budget                → Budget remaining today
POST /tasks/<project>/<task>/run   → Manual trigger
POST /runs/<run-id>/cancel         → Cancel running task
```

**GitHub webhook flow:**
1. Receive event → verify HMAC signature using `GITHUB_WEBHOOK_SECRET`
2. Match event type against all project task triggers
3. For each match: check filters (flat key-value exact match on payload)
4. If match + budget available → enqueue execution

**Linear webhook flow:**
1. Receive event → verify signature using `LINEAR_WEBHOOK_SECRET`
2. Match against task triggers (issue assigned, status changed, etc.)
3. Inject issue context into prompt template variables
4. Enqueue execution

### 5. Budget Manager

- Reads `total_cost_usd` directly from Claude CLI JSON output (source of truth)
- Tracks cumulative cost per day (resets at midnight local time)
- Before each task: checks remaining budget vs task's `max_cost_usd`
- Warning notification when threshold reached
- Blocks new tasks when limit reached (if `pause_on_limit: true`)
- Per-task hard cap enforced at CLI level via `--max-budget-usd`

### 6. Notifier

Slack webhook notifications:

```
✅ [sekit] dep-update completed
   PR: https://github.com/moonshot-partners/sekit-monorepo/pull/42
   Cost: $0.18 | Turns: 12 | Duration: 2m34s

❌ [fintech] ci-fix failed
   Error: Tests failed after fix attempt
   Branch: agents/ci-fix-20260314-031245
   Cost: $1.23 | Turns: 28 | Duration: 8m12s

⚠️ Budget warning: $7.23 / $10.00 used today (73%)
```

### 7. History (SQLite)

```sql
CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    task TEXT NOT NULL,
    trigger_type TEXT NOT NULL,    -- 'schedule', 'github', 'linear', 'manual'
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    status TEXT NOT NULL,          -- 'running', 'success', 'failure', 'cancelled', 'timeout'
    model TEXT NOT NULL,
    num_turns INTEGER,
    cost_usd REAL,                -- From total_cost_usd in CLI output
    pr_url TEXT,
    error_message TEXT,
    output_file TEXT              -- Path to JSON output file on disk (not inline)
);
```

Output files stored at `data/runs/<run-id>.json` to avoid bloating SQLite with large JSON blobs.

## Autonomy Levels

Configured per task via `autonomy` field:

| Level | Value | Behavior |
|---|---|---|
| Review required | `pr-only` | Creates PR, notifies human. Human merges. |
| Auto-merge | `auto-merge` | Creates PR, enables auto-merge (merges after CI passes). Notifies human. |

Default: `pr-only`. Auto-merge recommended only for low-risk, reversible tasks (dep updates, formatting, lint fixes).

## Model Routing

Per-task model selection via the `model` field. Values are aliases passed verbatim to `claude --model`:

| Alias | Resolves to | Recommended for | Estimated cost/run |
|---|---|---|---|
| `haiku` | `claude-haiku-4-5-20251001` | Dep updates, formatting | ~$0.02-0.05 |
| `sonnet` | `claude-sonnet-4-6` | CI fixes, features | ~$0.15-2.00 |
| `opus` | `claude-opus-4-6` | Complex architectural work | ~$2.00-5.00 |

Full model IDs (e.g., `claude-sonnet-4-6`) are also accepted — the Runner passes the value verbatim.

## Global Config

```yaml
# config.yaml
budget:
  daily_limit_usd: 10.00
  warning_threshold_usd: 7.00
  pause_on_limit: true

notifications:
  slack_webhook_url: ${SLACK_WEBHOOK_URL}

webhooks:
  github_secret: ${GITHUB_WEBHOOK_SECRET}
  linear_secret: ${LINEAR_WEBHOOK_SECRET}

execution:
  worktree_base: /tmp/agents
  default_model: sonnet
  default_max_cost_usd: 5.00
  default_autonomy: pr-only
  max_concurrent: 3
  timeout_minutes: 15
  dry_run: false

server:
  host: 0.0.0.0
  port: 8080
```

Environment variables referenced with `${VAR}` are resolved at load time from the process environment.

## Project Structure

```
agents/
├── pyproject.toml
├── config.yaml                 # Global config (budget, slack, webhooks, execution)
├── projects/                   # One YAML per project
│   ├── sekit.yaml
│   └── fintech.yaml
├── data/                       # Runtime data (gitignored)
│   ├── agents.db               # SQLite (history + scheduler job store)
│   └── runs/                   # JSON output files per run
├── src/
│   └── agents/
│       ├── __init__.py
│       ├── main.py             # FastAPI app + startup (scheduler init, webhook routes)
│       ├── config.py           # Load & validate global config + project configs
│       ├── models.py           # Pydantic models (TaskConfig, RunResult, BudgetStatus)
│       ├── executor.py         # Worktree lifecycle + claude CLI invocation + cleanup
│       ├── scheduler.py        # APScheduler setup with SQLite job store
│       ├── budget.py           # Daily cost tracking + limit enforcement
│       ├── notifier.py         # Slack webhook notifications
│       ├── history.py          # SQLite run history (CRUD)
│       └── webhooks/
│           ├── __init__.py
│           ├── github.py       # GitHub webhook handler + HMAC signature verification
│           └── linear.py       # Linear webhook handler + signature verification
└── tests/
    ├── conftest.py
    ├── test_config.py          # Config loading, validation, defaults, env var resolution
    ├── test_executor.py        # Worktree lifecycle, CLI invocation (mocked)
    ├── test_scheduler.py       # Job registration, cron parsing
    ├── test_budget.py          # Cost tracking, limits, daily reset
    ├── test_notifier.py        # Slack message formatting
    ├── test_history.py         # SQLite CRUD, output file storage
    └── test_webhooks/
        ├── test_github.py      # Event matching, filtering, HMAC verification
        └── test_linear.py      # Event matching, filtering, signature verification
```

## Evolution Path (Phase 2)

When the Runner hits its limits, the natural evolution is:

1. **CLI → Claude Agent SDK** — Replace `claude -p` with direct SDK calls for more control
2. **Worktrees → Containers** — Replace git worktrees with Docker containers for full isolation
3. **Local → Cloud** — Deploy on a VPS with proper process management (systemd)
4. **SQLite → PostgreSQL** — When history/analytics needs grow
5. **Slack → Dashboard** — Web UI for monitoring, config, and manual triggers

Each evolution is independent and incremental. The YAML config format and project structure remain stable across phases.

## Non-Goals (Phase 1)

- Web dashboard (status API is sufficient)
- Multi-user / auth (single-user system)
- Container isolation (worktrees are sufficient)
- Automatic retry on failure (notify and let human decide)
- Agent-to-agent communication (each task is independent)
- Manual price calculation (use `total_cost_usd` from CLI output)
