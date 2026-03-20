# Task-Centric Architecture Design

## Problem

Paperweight has fragmented data models: `RunRecord` tracks executions, `AgentSession` tracks interactive chats, Linear issues live externally, and `TaskConfig` in YAML defines execution templates. Nothing connects them. If Linear triggers a run, there's no way to continue that work in the Agent Tab. If you brainstorm in the Agent Tab, there's no way to turn that into an autonomous task. Each path is isolated.

The onboarding also assumes external integrations (Linear, Slack, Discord) from the start, when the core value — "agent works on your code" — only needs a git repo and Claude.

## Goal

Make **Task** the universal unit of work. Everything is a Task. The Agent Tab is the universal interface. External integrations are optional sources that feed Tasks. Every interaction becomes data and context that makes the agent smarter on each attempt.

## Design

### Naming: Task vs TaskTemplate

The codebase already has `TaskConfig` (YAML-defined execution templates like "issue-resolver") and `TaskRecord` (SQLite project hub copy of the same). These represent **templates** — reusable definitions of what work to do, with what model and budget.

The new `Task` entity represents a **work item** — a concrete instance of work being done. To avoid confusion:

- `TaskConfig` → renamed to `TaskTemplate` (in models.py and YAML references)
- `TaskRecord` → renamed to `TaskTemplate` (in project_hub SQLite and routes)
- Existing CRUD routes at `/api/projects/{id}/tasks` → continue working but manage templates
- New `Task` entity → new table `work_items`, new store class, new routes

### The Task Entity

A Task represents a unit of work from creation to completion. It is the single concept that ties together conversations, agent runs, PRs, and external issue tracker items.

```
Task (table: work_items)
  id: str (12-char hex)
  project: str (project name from YAML — matches state.projects keys)
  template: str | null (name of the TaskTemplate that spawned it, e.g. "issue-resolver")
  title: str
  description: str (the full problem statement / spec)
  source: "agent-tab" | "linear" | "github" | "manual" | "schedule"
  source_id: str (Linear issue ID, GitHub issue #, empty for manual)
  source_url: str (link back to Linear/GitHub issue, empty for manual)
  status: "draft" | "pending" | "running" | "review" | "done" | "failed"
  session_id: str | null (→ AgentSession, for Agent Tab continuity)
  pr_url: str | null
  created_at: datetime
  updated_at: datetime
```

**Relationships:**
- A Task has zero or many `RunRecord`s (linked via new `task_id` column on `runs` table).
- A Task has zero or one `AgentSession` (for interactive work / refinement).
- A Task may reference an external item via `source` + `source_id`.
- A Task may reference a `TaskTemplate` via `template` (for budget/model defaults).

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

Every interaction adds to the Task's context. This is what makes the agent intelligent across attempts.

**Storage format:** Context is stored as a JSON array of `TaskContextEntry` objects in a separate `task_context` table (not a text column):

```
TaskContextEntry (table: task_context)
  id: int (autoincrement)
  task_id: str (FK → work_items.id)
  type: "conversation" | "run_result" | "run_error" | "review" | "ci_failure" | "user_feedback" | "external"
  source_run_id: str | null (which run produced this entry)
  content: str (max 4KB per entry — summarized if needed)
  timestamp: float
```

**Cap:** Max 50 entries per task. When exceeded, oldest non-error entries are pruned. This prevents unbounded growth while preserving critical failure context.

**What produces context entries:**

1. **Conversation context** (`type: "conversation"`): When a task is created from Agent Tab, the conversation summary (auto-generated, not raw messages) becomes a context entry. Captures decisions, constraints, and requirements.

2. **Run context** (`type: "run_result"` or `type: "run_error"`): After each run, a mechanical summary is generated: files changed (from `tool_use` events with Edit/Write), final status, cost, error message if any. Not LLM-generated — template-based extraction from `run_events`.

3. **Review context** (`type: "review"` or `type: "ci_failure"`): CI failure output captured from GitHub check runs. PR review comments captured from GitHub webhook events.

4. **User feedback** (`type: "user_feedback"`): When the user gives explicit feedback in the Agent Tab (e.g., "this approach is wrong, try X"), the feedback is captured as a context entry.

5. **External context** (`type: "external"`): Issue description and comments from Linear/GitHub at task creation time.

**Prompt assembly:** When the agent starts working on a task, the prompt is assembled as:
```
[Task description]
[Context entries, newest first, up to 8KB total]
[Project conventions from CLAUDE.md]
```

The agent never starts from zero on a retry.

### How Tasks Are Created

#### From Agent Tab (brainstorm → task)

1. User opens Agent Tab, starts a conversation ("I need to understand why the tests are slow").
2. Claude investigates, discusses, proposes solutions.
3. User clicks a **"Create Task"** button in the Agent Tab toolbar. A modal pre-fills title (from `_generate_title`) and description (from the last substantive Claude response). User can edit before confirming.
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

1. **Claim the task** via atomic `UPDATE work_items SET status = 'running' WHERE id = ? AND status = 'pending'` — check `rowcount == 1` to prevent double-pickup. Same pattern as `session_manager.try_acquire_run()`.
2. **Create or reuse session:** If the task already has a `session_id` (from prior run or Agent Tab), reuse it (the worktree persists). Otherwise, create a new `AgentSession` and set `task.session_id`.
3. **Build the prompt:** task description + context entries (newest first, up to 8KB) + project conventions (CLAUDE.md).
4. **Execute via `run_adhoc()`** (reuses existing executor infrastructure). The `RunRecord` gets `task_id` set to the task's ID.
5. **Respect concurrency:** The processing loop acquires `state.get_semaphore(max_concurrent)` and `state.get_repo_semaphore(repo)` before executing, same as existing paths.
6. On success: create PR via `_create_pr()`, set `status: "review"`, update `pr_url`.
7. On failure: set `status: "failed"`, append `run_error` context entry.
8. If source is Linear/GitHub: update the external tracker.

**Worktree lifecycle:** The Task owns the worktree via its `AgentSession`. Worktrees are NOT cleaned up after autonomous runs (unlike current `run_task()` behavior). They persist until: (a) task status reaches "done" and session cleanup runs, or (b) the stale session cleanup job fires (30min idle). This enables seamless transition from autonomous to interactive.

### Task Refinement (Interactive)

When a user opens a task in the Agent Tab:

1. The Agent Tab loads with full task context: description, prior runs, PR, errors.
2. The worktree is still there (session persists across autonomous and interactive runs).
3. User can chat with Claude in that worktree context — Claude sees all prior changes.
4. Any new work builds on what the agent already did.
5. User can: re-queue for autonomous processing ("Re-run" button sets status back to "pending"), or mark as done.

This is the key insight: **the autonomous run and the interactive session share the same worktree and context**. There's no "start over" — you always continue.

**Session reuse on retry:** When a failed task is re-queued as "pending", the processing loop finds the existing `session_id`, reuses the same worktree, and passes `--resume` to Claude. The agent continues from where it left off, with full context of why the previous attempt failed.

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
- `work_items` table in SQLite + `TaskStore` class
- `task_context` table in SQLite for context accumulation
- `task_id` column on `runs` table (FK to work_items)
- `task_id` column on `agent_sessions` table
- Task processing loop (replaces direct webhook→run_task dispatch)
- Dashboard tasks tab shows live Tasks instead of YAML TaskTemplates
- Agent Tab gains task context bar (title, status, source, run history)
- "Create Task" button in Agent Tab toolbar
- GitHub Issues polling via `gh issue list` (new work finder)

**Modified:**
- `TaskConfig` → renamed to `TaskTemplate` (models.py, config.py, YAML references)
- `TaskRecord` → renamed to `TaskTemplate` (project_store.py, project_hub_routes.py)
- Webhook handlers create Tasks instead of directly calling `run_task()`
- Scheduler creates Tasks instead of directly calling `run_task()`
- `run_adhoc()` receives task context in the prompt
- `AgentSession` gains `task_id` column — sessions can be linked to tasks
- `run_task()` no longer cleans up worktrees for task-linked runs (Task owns lifecycle)
- Agent Tab passes `task_id` when sending prompts

**Unchanged:**
- Executor core (`_run_claude`, `_run_cmd`, `_create_pr`) — same execution engine
- Streaming (WebSocket, events) — same pipeline
- PR creation — same `_create_pr()` with rich body
- CI + auto-review — same GitHub Actions
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

## Implementation Phases

**Phase 1 — Foundation (Task entity + processing loop)**
- New `work_items` and `task_context` tables
- `TaskStore` with CRUD + atomic claim
- Task processing loop (picks up pending tasks, executes via `run_adhoc`)
- Manual task creation from dashboard (title + description form)
- `task_id` FK on `runs` and `agent_sessions` tables
- Rename `TaskConfig` → `TaskTemplate`, `TaskRecord` → `TaskTemplate`

**Phase 2 — Agent Tab integration**
- Link sessions to tasks (`task_id` on agent_sessions)
- Task context bar in Agent Tab (title, status, runs, PR)
- "Create Task" button in Agent Tab toolbar
- "Re-run" button for failed tasks
- Clicking a task in the dashboard opens Agent Tab with full context

**Phase 3 — Source migration**
- Webhook handlers create Tasks instead of calling `run_task()` directly
- Scheduler creates Tasks instead of calling `run_task()` directly
- GitHub Issues polling via `gh issue list --label agent`
- Linear polling creates Tasks instead of calling `run_task()` directly

**Phase 4 — Context accumulation**
- `task_context` entries written after each run (mechanical, template-based)
- Context entries included in agent prompts on retry
- CI failure capture via GitHub webhook
- User feedback capture from Agent Tab interactions

Each phase produces working, testable software. Phases 1-2 can ship together. Phases 3-4 build on the foundation.

## Non-Goals

- **Not replacing Linear/GitHub as issue trackers.** Tasks in paperweight are work items for the agent, not a full project management tool. External trackers remain the source of truth for project planning.
- **Not building a chat UI.** The Agent Tab already exists. We're adding task awareness to it, not rebuilding it.
- **Not rewriting the executor.** The core execution engine (`_run_claude`, `_run_cmd`, `_create_pr`) stays the same. We're changing what feeds into it (Tasks) and what captures its output (Task context). Behavioral changes (worktree lifecycle) are minimal and targeted.

## Success Criteria

1. A user with only git + claude can create a task in the dashboard and have the agent resolve it autonomously.
2. A task from Linear and a task created manually in the dashboard go through the exact same processing pipeline.
3. When an agent fails, the user can open the task in the Agent Tab, see everything that happened, give feedback, and re-run — with the agent having full context of prior attempts.
4. Adding an integration (Linear, GitHub Issues) is a single env var change that makes new task sources available without changing any workflow.
5. Every interaction (conversation, run, error, review comment) becomes persistent context that improves the agent's next attempt.
