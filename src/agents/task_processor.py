"""Background task processor — claims pending tasks and executes them."""
import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from agents.models import RunStatus, TaskStatus

if TYPE_CHECKING:
    from agents.app_state import AppState
    from agents.config import GlobalConfig
    from agents.models import WorkItem
    from agents.task_store import TaskStore

logger = logging.getLogger(__name__)

_MAX_CONTEXT_BYTES = 8192


class TaskProcessor:
    def __init__(
        self,
        task_store: "TaskStore",
        state: "AppState",
        config: "GlobalConfig",
    ) -> None:
        self.task_store = task_store
        self.state = state
        self.config = config
        self._running = False

    @staticmethod
    def build_prompt(item: "WorkItem", context_entries: list[dict]) -> str:
        """Assemble the agent prompt from task description + context."""
        parts: list[str] = []
        parts.append(f"# Task: {item.title}\n")
        parts.append(item.description)

        if context_entries:
            parts.append("\n\n## Prior Context (newest first)")
            total = 0
            for entry in reversed(context_entries):
                content = entry.get("content", "")
                entry_type = entry.get("type", "")
                line = f"\n### [{entry_type}]\n{content}"
                if total + len(line) > _MAX_CONTEXT_BYTES:
                    parts.append("\n\n(... earlier context truncated ...)")
                    break
                parts.append(line)
                total += len(line)

        return "\n".join(parts)

    async def process_one(self, item: "WorkItem") -> None:
        """Process a single task: create/reuse session, run agent, update status."""
        project = self.state.projects.get(item.project)
        if project is None:
            logger.warning("Task %s references unknown project %s", item.id, item.project)
            self.task_store.update_status(item.id, TaskStatus.FAILED)
            return

        template_name = item.template
        template = project.tasks.get(template_name) if template_name else None
        model = template.model if template else self.config.execution.default_model
        max_cost = template.max_cost_usd if template else self.config.execution.default_max_cost_usd

        # Normalize model name
        model_map = {
            "sonnet": "claude-sonnet-4-6",
            "haiku": "claude-haiku-4-5-20251001",
            "opus": "claude-opus-4-6",
        }
        model = model_map.get(model, model)

        session_manager = self.state.session_manager
        if item.session_id:
            session = session_manager.get_session(item.session_id)
            if session is None or session.status != "active":
                session = session_manager.create_session(item.project, model, max_cost)
                self.task_store.update_session(item.id, session.id)
            if not session_manager.try_acquire_run(session.id):
                logger.warning("Task %s: session %s locked, will retry", item.id, item.session_id)
                # Release claim — set back to pending
                self.task_store.update_status(item.id, TaskStatus.PENDING)
                return
        else:
            session = session_manager.create_session(item.project, model, max_cost)
            session_manager.try_acquire_run(session.id)
            self.task_store.update_session(item.id, session.id)

        is_resume = session.claude_session_id is not None
        context_entries = self.task_store.get_context(item.id)
        prompt = self.build_prompt(item, context_entries=context_entries)

        try:
            async with (
                self.state.get_semaphore(self.config.execution.max_concurrent),
                self.state.get_repo_semaphore(project.repo),
            ):
                from agents.executor_utils import generate_run_id
                run_id = generate_run_id(item.project, "task")

                result = await self.state.executor.run_adhoc(
                    project, prompt, session, is_resume=is_resume, run_id=run_id,
                )

                if result.claude_session_id:
                    session_manager.update_session(
                        session.id, claude_session_id=result.claude_session_id,
                    )

                if result.status == RunStatus.SUCCESS:
                    pr_url = None
                    try:
                        from pathlib import Path
                        worktree = Path(session.worktree_path)
                        if worktree.exists():
                            branch = f"agents/session-{session.id}"
                            pr_url = await self.state.executor._create_pr(
                                cwd=str(worktree), project=project,
                                task_name=item.title[:40], branch=branch,
                                autonomy=template.autonomy if template else "pr-only",
                            )
                    except Exception:
                        logger.warning("Failed to create PR for task %s", item.id)

                # Write run context entry
                try:
                    run_events = self.state.history.list_events(run_id)
                    files_changed = [
                        e.get("file_path", "") for e in run_events
                        if e.get("type") == "tool_use" and e.get("tool_name") in ("Edit", "Write")
                        and e.get("file_path")
                    ]
                    summary = f"Status: {result.status}\nCost: ${result.cost_usd or 0:.2f}"
                    if files_changed:
                        summary += f"\nFiles changed: {', '.join(set(files_changed))}"
                    if result.error_message:
                        summary += f"\nError: {result.error_message}"
                    self.task_store.add_context(
                        item.id,
                        "run_result" if result.status == RunStatus.SUCCESS else "run_error",
                        summary,
                        source_run_id=run_id,
                    )
                except Exception:
                    logger.warning("Failed to write context for task %s", item.id)

                if result.status == RunStatus.SUCCESS:
                    self.task_store.update_status(
                        item.id,
                        TaskStatus.REVIEW if pr_url else TaskStatus.DONE,
                        pr_url=pr_url,
                    )
                else:
                    from agents.retry import RetryPolicy, should_retry_error
                    retry_policy = RetryPolicy()
                    retry_count = item.retry_count + 1
                    if (
                        should_retry_error(result.error_message or "")
                        and retry_policy.can_retry(retry_count)
                    ):
                        delay = retry_policy.delay_for_attempt(retry_count)
                        next_retry = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()
                        self.task_store.mark_for_retry(item.id, retry_count, next_retry)
                        logger.info(
                            "Task %s will retry (attempt %d) at %s",
                            item.id, retry_count, next_retry,
                        )
                    else:
                        self.task_store.update_status(item.id, TaskStatus.FAILED)
        except Exception:
            logger.exception("Task %s failed", item.id)
            self.task_store.update_status(item.id, TaskStatus.FAILED)
        finally:
            session_manager.release_run(session.id)

    async def run_loop(self) -> None:
        """Main processing loop — polls for pending tasks every 10s."""
        self._running = True
        logger.info("TaskProcessor started")
        while self._running:
            try:
                pending = self.task_store.list_pending(
                    limit=self.config.execution.max_concurrent,
                )
                for item in pending:
                    if not self.state.budget.can_afford(
                        self.config.execution.default_max_cost_usd,
                    ):
                        logger.info("Budget exhausted, skipping task %s", item.id)
                        continue
                    if self.task_store.try_claim(item.id):
                        asyncio.create_task(self.process_one(item))

                now_iso = datetime.now(UTC).isoformat()
                retryable = self.task_store.list_retryable(
                    now_iso, limit=self.config.execution.max_concurrent,
                )
                for item in retryable:
                    if not self.state.budget.can_afford(
                        self.config.execution.default_max_cost_usd,
                    ):
                        break
                    if self.task_store.try_claim_any(item.id):
                        asyncio.create_task(self.process_one(item))
            except Exception:
                logger.exception("TaskProcessor loop error")
            await asyncio.sleep(10)

    def stop(self) -> None:
        self._running = False
