# Task-Centric Architecture Design

## Problem

Paperweight has fragmented data models: `RunRecord` tracks executions, `AgentSession` tracks interactive chats, Linear issues live externally, and `TaskConfig` in YAML defines execution templates. Nothing connects them. If Linear triggers a run, there's no way to continue that work in the Agent Tab. If you brainstorm in the Agent Tab, there's no way to turn that into an autonomous task. Each path is isolated.

The onboarding also assumes external integrations (Linear, Slack, Discord) from the start, when the core value — "agent works on your code" — only needs a git repo and Claude.

## Goal

Make **Task** the universal unit of work. Everything is a Task. The Agent Tab is the universal interface. External integrations are optional sources that feed Tasks. Every interaction becomes data and context that makes the agent smarter on each attempt.

## Design

### The Task Entity

A Task represents a unit of work from creation to completion. It is the single concept that ties together conversations, agent runs, PRs, and external issue tracker items.

```
Task
  id: str (12-char hex)
  project: str
  title: str
  description: str (the full problem statement / spec)
  source: "agent-tab" | "linear" | "github" | "manual" | "schedule"
  source_id: str (Linear issue ID, GitHub issue #, empty for manual)
  source_url: str (link back to Linear/GitHub issue, empty for manual)
  status: "draft" | "pending" | "running" | "review" | "done" | "failed"
  session_id: str | null (→ AgentSession, for Agent Tab continuity)
  pr_url: str | null
  context: str (accumulated context: conversation summary, prior attempts, errors)
  created_at: datetime
  updated_at: datetime
```

**Relationships:**
- A Task has zero or many `RunRecord`s (agent execution attempts).
- A Task has zero or one `AgentSession` (for interactive work / refinement).
- A Task may reference an external item via `source` + `source_id`.

### Task Lifecycle

```
DRAFT → PENDING → RUNNING → REVIEW → DONE
                     ↓                  ↑
                  FAILED ──→ (retry) ──→┘
                     ↓
              (user refines via Agent Tab)
                     ↓
                  PENDING (re-queued)
```

**DRAFT**: Created from an Agent Tab conversation that hasn't been formalized yet. The user is still brainstorming. A draft has a session but no autonomous runs.

**PENDING**: Ready for the agent to pick up. Can be created by: user clicking "Create Task" in the dashboard, Linear/GitHub issue arriving, cron schedule firing, or user promoting a draft.

**RUNNING**: Agent is actively working. A `RunRecord` is in progress.

**REVIEW**: Agent finished, PR created. Waiting for CI, review, or user inspection.

**DONE**: PR merged or user marked as complete. If source is Linear, the issue moves to "Done". If source is GitHub, the issue is closed.

**FAILED**: Agent couldn't complete the work. The error and context are preserved. User can: (a) open in Agent Tab to refine and retry, (b) re-queue as pending, or (c) close.

### Context Accumulation

Every interaction adds to the Task's context. This is what makes the agent intelligent across attempts:

1. **Conversation context**: When a task originates from Agent Tab brainstorming, the conversation summary becomes the task description. Key decisions, constraints, and requirements discovered during chat are preserved.

2. **Run context**: Each `RunRecord` contributes: what files were changed, what tools were used, what errors occurred, what the cost was. On retry, the agent receives this context via the prompt (similar to the existing `progress_file_path` mechanism, but richer).

3. **Review context**: If CI fails, the failure output is appended to context. If a human leaves PR review comments, those are captured. If the user opens the Agent Tab and gives feedback ("this approach is wrong, try X instead"), that becomes context.

4. **External context**: If the task came from Linear, the issue description, comments, and status changes are context. If from GitHub, the issue body and comments.

The agent prompt for any task always includes: task description + accumulated context from all prior runs + user feedback. The agent never starts from zero on a retry.

### How Tasks Are Created

#### From Agent Tab (brainstorm → task)

1. User opens Agent Tab, starts a conversation ("I need to understand why the tests are slow").
2. Claude investigates, discusses, proposes solutions.
3. User says "ok, create a task to fix the slow tests" (or clicks a "Create Task" button).
4. System creates a Task with:
   - `source: "agent-tab"`
   - `title`: auto-generated from conversation (like current `_generate_title`)
   - `description`: the crystallized problem + solution from the conversation
   - `context`: full conversation history summary
   - `session_id`: the current session (so the worktree is preserved)
   - `status: "pending"` (ready for autonomous execution)
5. Agent picks up the task and works autonomously.

#### From Dashboard (manual creation)

1. User clicks "Create Task" in the project's task list.
2. Fills in title + description.
3. Task created with `source: "manual"`, `status: "pending"`.
4. Agent picks it up.

#### From Linear (webhook or polling)

1. Issue with label "agent" arrives via webhook or 15-min polling.
2. System creates a Task with:
   - `source: "linear"`
   - `source_id`: Linear issue ID
   - `source_url`: Linear issue URL
   - `title`: issue title
   - `description`: issue description
   - `context`: any existing comments on the issue
   - `status: "pending"`
3. Agent picks it up. Status updates flow back to Linear.

#### From GitHub Issues (polling via `gh`)

1. System polls `gh issue list --label agent` for configured repos.
2. For each new issue, creates a Task with:
   - `source: "github"`
   - `source_id`: issue number
   - `source_url`: issue URL
   - Same pattern as Linear.

#### From Schedule (cron)

1. APScheduler fires a cron job.
2. System creates a Task with:
   - `source: "schedule"`
   - `title`: task name from YAML
   - `description`: the prompt from TaskConfig
   - `status: "pending"`

### Task Processing (Autonomous)

When a task reaches `status: "pending"`, the processing loop picks it up:

1. Find next pending task (FIFO, respecting `max_concurrent`).
2. Create or reuse an `AgentSession` + worktree for the task.
3. Build the prompt: task description + accumulated context + project conventions (CLAUDE.md).
4. Execute via `run_adhoc()` (reuses existing executor infrastructure).
5. On success: create PR, set `status: "review"`, update `pr_url`.
6. On failure: set `status: "failed"`, append error to `context`.
7. If source is Linear/GitHub: update the external tracker.

### Task Refinement (Interactive)

When a user opens a task in the Agent Tab:

1. The Agent Tab loads with full task context: description, prior runs, PR, errors.
2. The existing worktree is still there (session persists).
3. User can chat with Claude in that worktree context.
4. Any changes Claude makes build on prior work.
5. User can: re-submit for autonomous processing, or manually close.

This is the key insight: **the autonomous run and the interactive session share the same worktree and context**. There's no "start over" — you always continue.

### Dashboard UX Changes

#### Project Tasks Tab (replaces current static task list)

Current: shows `TaskConfig` entries from YAML (static templates).
New: shows `Task` entries from SQLite (live work items).

Each task row shows:
- Status badge (draft/pending/running/review/done/failed)
- Source badge (agent-tab/linear/github/manual/schedule)
- Title
- PR link (if exists)
- Cost (sum of all runs)
- Last updated

Clicking a task opens the Agent Tab pre-loaded with that task's context.

#### Creating Tasks

Two entry points:
1. **"+ New Task" button** in the tasks tab → form with title + description → creates pending task.
2. **Agent Tab → "Create Task"** → promotes the current conversation to a task.

#### Task Detail (inside Agent Tab)

When viewing a task in the Agent Tab, the top bar shows:
- Task title + status
- Source badge
- PR link
- Run history (collapsible: attempt 1, attempt 2, ...)
- "Re-run" button (re-queues as pending)

Below: the normal Agent Tab interface for interactive work.

### Work Finder Architecture

Instead of webhooks directly triggering `run_task()`, they create Tasks. A unified work finder loop processes them:

```python
async def process_pending_tasks():
    """Main loop: find pending tasks, process them."""
    while True:
        tasks = task_store.list_pending(limit=max_concurrent)
        for task in tasks:
            if can_afford(task) and has_capacity():
                asyncio.create_task(process_task(task))
        await asyncio.sleep(10)  # check every 10 seconds

async def check_external_sources():
    """Periodic: check Linear, GitHub Issues for new work."""
    # Linear (if configured)
    if linear_client:
        issues = find_agent_issues_from_linear()
        for issue in issues:
            if not task_store.exists_by_source("linear", issue.id):
                task_store.create(source="linear", ...)

    # GitHub Issues (if gh authenticated)
    if gh_available:
        issues = find_agent_issues_from_github()
        for issue in issues:
            if not task_store.exists_by_source("github", issue.number):
                task_store.create(source="github", ...)
```

This cleanly separates "finding work" from "doing work". Each source is just a function that creates Tasks.

### What Changes vs What Stays

**New:**
- `Task` entity in SQLite (new table, new store class)
- Task processing loop (replaces direct webhook→run_task dispatch)
- Dashboard tasks tab shows live Tasks instead of YAML TaskConfigs
- Agent Tab gains task context (knows which task it's working on)
- "Create Task" action from Agent Tab conversations
- GitHub Issues polling via `gh issue list` (new work finder)

**Modified:**
- Webhook handlers create Tasks instead of directly calling `run_task()`
- Scheduler creates Tasks instead of directly calling `run_task()`
- `run_adhoc()` receives task context in the prompt
- Agent Tab links sessions to tasks

**Unchanged:**
- Executor (`run_task`, `run_adhoc`) — same execution engine
- Streaming (WebSocket, events) — same pipeline
- PR creation — same `_create_pr()` with rich body
- CI + auto-review — same GitHub Actions
- Session management — same `AgentSession` model
- Budget — same `BudgetManager`
- Coordination protocol — same (works at run level, not task level)

### Onboarding (Zero Friction)

With this architecture, the minimal onboarding is:

```bash
git clone <paperweight>
cd paperweight
uv sync
claude /login
gh auth login  # optional: enables PR creation + GitHub Issues
uv run agents
# → open http://localhost:8080
# → add your repo (just name + path, no integrations needed)
# → open Agent Tab, start talking
# → or create a task, let agent work autonomously
```

Integrations are added later, one by one:
- Add `LINEAR_API_KEY` to `.env` → Linear issues become task sources
- Add `DISCORD_BOT_TOKEN` → get run notifications in Discord
- Configure webhook secrets → get real-time triggers instead of polling
- Each integration is a 1-line env var change, not a structural requirement

### Data as Context — The Intelligence Loop

Every piece of data in the system feeds back into agent intelligence:

```
Task created (description + source context)
  → Agent reads full context before starting
  → Agent works, produces run events + code changes
  → Events stored in SQLite (tool calls, errors, results)
  → On failure: error + events become retry context
  → On success: PR created, review feedback captured
  → If CI fails: failure output → context → retry
  → If user refines: conversation → context → next attempt
  → Each attempt builds on ALL prior context
```

The agent never starts from zero. Every interaction, every failure, every piece of feedback accumulates in the task's context. This is what makes paperweight progressively smarter at solving each task.

## Non-Goals

- **Not replacing Linear/GitHub as issue trackers.** Tasks in paperweight are work items for the agent, not a full project management tool. External trackers remain the source of truth for project planning.
- **Not building a chat UI.** The Agent Tab already exists. We're adding task awareness to it, not rebuilding it.
- **Not changing the executor.** The execution engine is solid. We're changing what feeds into it (Tasks) and what captures its output (Task context).

## Success Criteria

1. A user with only git + claude can create a task in the dashboard and have the agent resolve it autonomously.
2. A task from Linear and a task created manually in the dashboard go through the exact same processing pipeline.
3. When an agent fails, the user can open the task in the Agent Tab, see everything that happened, give feedback, and re-run — with the agent having full context of prior attempts.
4. Adding an integration (Linear, GitHub Issues) is a single env var change that makes new task sources available without changing any workflow.
5. Every interaction (conversation, run, error, review comment) becomes persistent context that improves the agent's next attempt.
