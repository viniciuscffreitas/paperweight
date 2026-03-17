# paperweight

> A paperweight for your codebase. Like [Paperclip](https://github.com/paperclipai/paperclip), but leaner.

**paperweight** is a background agent runner that orchestrates [Claude Code](https://claude.ai/code) sessions autonomously — no keyboard, no prompts, no one watching. It runs scheduled and event-triggered tasks across multiple repos, streams everything in real time, and keeps costs in check.

Built without knowing Paperclip existed. Turns out we were solving the same problem from a different angle.

---

## What it does

- Runs `claude -p` headless on a schedule (APScheduler) or on events (GitHub webhooks, Linear webhooks)
- Each project declares an `intent:` + `context_hints:` in YAML — the context the agent needs to work autonomously
- Creates isolated **git worktrees** per execution to prevent conflicts between concurrent runs
- **Budget control**: daily limit + per-task cap, pulling real cost from `stream-json` output
- **Real-time streaming**: WebSocket broadcast of every tool call, token count, and cost as it happens
- **NiceGUI dashboard** at `/dashboard` — live event feed, run history, budget gauge
- Integrates with **Linear** (auto-resolve issues) and **GitHub** (PR-only autonomy by default)

## How it's different from Paperclip

| | paperweight | Paperclip |
|---|---|---|
| Stack | Python / FastAPI / SQLite | Node.js / React / PostgreSQL |
| Focus | Claude Code (deep integration) | Multi-agent (OpenClaw, CC, Codex, Cursor) |
| Governance | Paired with [devflow](https://github.com/viniciuscffreitas/devflow) | Built-in org charts |
| Complexity | Lean — single `config.yaml` | Company OS |
| Autonomy modes | `pr-only`, `auto-merge`, `notify` | Approval gates |

paperweight pairs with **devflow** (in-the-loop governance) to form a complete autonomous coding stack:
- **devflow** = guardrails for when Claude Code is running interactively
- **paperweight** = engine for when Claude Code runs in the background

## Quickstart

```bash
git clone https://github.com/viniciuscffreitas/paperweight
cd paperweight
cp .env.example .env         # add your keys
cp projects/example.yaml projects/myproject.yaml
uv run agents
```

Dashboard at `http://localhost:8080/dashboard`.

## Project config

```yaml
# projects/myproject.yaml
name: myproject
repo: /path/to/your/repo
base_branch: main
branch_prefix: agents/
notify: slack

tasks:
  issue-resolver:
    description: "Resolve Linear issues autonomously end-to-end"
    intent: "Implement the given Linear issue following devflow: TDD, lint, tests, PR"
    trigger:
      type: linear
      events: [Issue.create]
      filter:
        label: agent
    model: claude-sonnet-4-6
    max_cost_usd: 2.00
    autonomy: pr-only
    prompt: |
      Resolve issue {{issue_identifier}} — {{issue_title}}.
      Follow CLAUDE.md. TDD. Create a PR when done.
```

## Global config

```yaml
# config.yaml
budget:
  daily_limit_usd: 10.00
  pause_on_limit: true

execution:
  default_model: sonnet
  default_autonomy: pr-only
  max_concurrent: 3
  timeout_minutes: 15

notifications:
  slack_webhook_url: ${SLACK_WEBHOOK_URL}

integrations:
  linear_api_key: ${LINEAR_API_KEY}
```

All secrets via environment variables — nothing hardcoded.

## Stack

- **Python 3.13** + FastAPI + APScheduler + SQLAlchemy + SQLite
- **NiceGUI** for the dashboard
- **Claude Code CLI** (`claude -p --output-format stream-json --verbose`)
- Webhooks: GitHub + Linear

## Requirements

- Python 3.13+
- [uv](https://github.com/astral-sh/uv)
- [Claude Code](https://claude.ai/code) installed and authenticated

```bash
uv run agents          # start server on :8080
uv run python -m pytest tests/ -v   # 80+ tests
```

## Autonomy modes

| Mode | Behavior |
|---|---|
| `pr-only` | Agent creates a branch + PR, never merges |
| `auto-merge` | Agent merges after passing CI |
| `notify` | Dry run — reports what it would do |

## License

MIT
