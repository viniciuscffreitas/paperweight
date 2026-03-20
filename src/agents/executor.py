import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from agents.budget import BudgetManager
from agents.config import ExecutionConfig, build_prompt
from agents.executor_notifications import fail_agent_run, finalize_agent_success
from agents.executor_utils import (
    ClaudeOutput,
    generate_branch_name,
    generate_run_id,
)
from agents.history import HistoryDB
from agents.models import ProjectConfig, RunRecord, RunStatus, TriggerType
from agents.notifier import Notifier

if TYPE_CHECKING:
    from agents.session_manager import AgentSession

# Re-export utilities that external callers import from this module
from agents.executor_utils import (  # noqa: E402  # re-exports
    append_progress_log,
    delete_progress_log,
    parse_claude_output,
    write_progress_log,
)

__all__ = [
    "ClaudeOutput",
    "Executor",
    "append_progress_log",
    "delete_progress_log",
    "generate_branch_name",
    "generate_run_id",
    "parse_claude_output",
    "write_progress_log",
]

logger = logging.getLogger(__name__)


class Executor:
    def __init__(
        self,
        config: ExecutionConfig,
        budget: BudgetManager,
        history: HistoryDB,
        notifier: Notifier,
        data_dir: Path,
        on_stream_event: Callable | None = None,
        linear_client: object | None = None,
        discord_notifier: object | None = None,
        broker: object | None = None,
    ) -> None:
        self.config = config
        self.budget = budget
        self.history = history
        self.notifier = notifier
        self.data_dir = data_dir
        self._running_processes: dict[str, asyncio.subprocess.Process] = {}
        self.on_stream_event = on_stream_event or self._noop_event
        self.linear_client = linear_client
        self.discord_notifier = discord_notifier
        self.broker = broker

    async def _noop_event(self, run_id: str, event: object) -> None:
        pass

    async def _check_budget(self, run: RunRecord, max_cost_usd: float) -> RunRecord | None:
        """Return the failed RunRecord if budget exceeded, None if OK."""
        if self.budget.can_afford(max_cost_usd):
            return None
        run.status = RunStatus.FAILURE
        run.error_message = (
            f"Budget exceeded. Need ${max_cost_usd}, "
            f"remaining: ${self.budget.get_status().remaining_usd:.2f}"
        )
        run.finished_at = datetime.now(UTC)
        self.history.update_run(
            run_id=run.id, status=run.status, finished_at=run.finished_at,
            error_message=run.error_message,
        )
        await self._emit(run.id, "task_failed", run.error_message)
        return run

    async def _handle_dry_run(self, run: RunRecord, label: str) -> RunRecord:
        """Handle dry_run mode — mark success and return immediately."""
        logger.info("DRY RUN: would execute %s", label)
        await self._emit(run.id, "dry_run", "dry_run=true — skipping Claude execution")
        run.status = RunStatus.SUCCESS
        run.cost_usd = 0.0
        run.finished_at = datetime.now(UTC)
        self.history.update_run(
            run_id=run.id, status=run.status, finished_at=run.finished_at, cost_usd=0.0,
        )
        await self._emit(run.id, "task_completed", "done (dry run)")
        return run

    async def _emit(self, run_id: str, event_type: str, content: str = "") -> None:
        from agents.streaming import StreamEvent

        await self.on_stream_event(
            run_id,
            StreamEvent(type=event_type, content=content, timestamp=time.time()),  # type: ignore[arg-type]
        )

    async def run_task(
        self,
        project: ProjectConfig,
        task_name: str,
        trigger_type: str = "manual",
        variables: dict[str, str] | None = None,
    ) -> RunRecord:
        task = project.tasks[task_name]
        variables = variables or {}
        issue_id = variables.get("issue_id", "")
        is_agent_issue = bool(issue_id and self.linear_client)

        run_id = generate_run_id(project.name, task_name, issue_id=issue_id)
        run = RunRecord(
            id=run_id,
            project=project.name,
            task=task_name,
            trigger_type=TriggerType(trigger_type),
            started_at=datetime.now(UTC),
            status=RunStatus.RUNNING,
            model=task.model,
        )
        self.history.insert_run(run)
        await self._emit(run_id, "task_started", f"{project.name}/{task_name} [{trigger_type}]")

        # Agent issue — notify Linear + Discord at start
        discord_msg_id = ""
        if is_agent_issue:
            team_id = variables.get("team_id", "")
            identifier = variables.get("issue_identifier", "")
            title = variables.get("issue_title", "")
            try:
                await self.linear_client.update_status(issue_id, team_id, "In Progress")  # type: ignore[union-attr]
                await self.linear_client.post_comment(issue_id, "\U0001f916 Agente iniciou execução")  # type: ignore[union-attr]
            except Exception:
                logger.warning("Failed to update Linear for %s", issue_id)
            if self.discord_notifier and project.discord_channel_id:
                try:
                    discord_msg_id = await self.discord_notifier.create_run_message(  # type: ignore[union-attr]
                        project.discord_channel_id, identifier, title,
                    )
                except Exception:
                    logger.warning("Failed to create Discord message for %s", issue_id)

        failed = await self._check_budget(run, task.max_cost_usd)
        if failed:
            await self.notifier.send_run_notification(run)
            return failed
        if self.config.dry_run:
            run = await self._handle_dry_run(run, f"{project.name}/{task_name}")
            if is_agent_issue:
                await finalize_agent_success(
                    project, variables, discord_msg_id, run,
                    self.linear_client, self.discord_notifier,
                )
            return run

        worktree_path: Path | None = None
        coordination_enabled = bool(self.broker)
        try:
            prompt = build_prompt(task, variables or {})
            if coordination_enabled:
                from agents.coordination.mediator import build_coordination_preamble
                prompt = build_coordination_preamble() + "\n\n---\n\n" + prompt

            branch_name = generate_branch_name(project.branch_prefix, task_name)
            worktree_path = Path(self.config.worktree_base) / run_id
            await self._run_cmd(
                ["git", "worktree", "add", str(worktree_path), "-b", branch_name, project.base_branch],
                cwd=project.repo,
            )

            if coordination_enabled:
                await self.broker.register_run(run_id, worktree_path, task.intent or task.prompt or "")  # type: ignore[union-attr]

            claude_cmd = [
                "claude", "-p", prompt, "--model", task.model,
                "--max-budget-usd", str(task.max_cost_usd),
                "--output-format", "stream-json", "--verbose",
                "--permission-mode", "auto", "--no-session-persistence",
            ]
            output, raw_output = await self._run_claude(
                claude_cmd, cwd=str(worktree_path), run_id=run_id,
                timeout=self.config.timeout_minutes * 60,
            )

            output_dir = self.data_dir / "runs"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / f"{run_id}.json"
            output_file.write_text(raw_output)

            run.cost_usd = output.cost_usd
            run.num_turns = output.num_turns
            run.output_file = str(output_file)

            if output.is_error:
                run.status = RunStatus.FAILURE
                run.error_message = output.result[:500]
                await self._emit(run_id, "task_failed", run.error_message)
            else:
                pr_url = await self._create_pr(
                    cwd=str(worktree_path), project=project, task_name=task_name,
                    branch=branch_name, autonomy=task.autonomy,
                )
                run.status = RunStatus.SUCCESS
                run.pr_url = pr_url
                msg = f"done — PR: {pr_url}" if pr_url else "done (no changes)"
                await self._emit(run_id, "task_completed", msg)
                if is_agent_issue:
                    await finalize_agent_success(
                        project, variables, discord_msg_id, run,
                        self.linear_client, self.discord_notifier,
                    )

        except TimeoutError:
            run.status = RunStatus.TIMEOUT
            run.error_message = f"Timed out after {self.config.timeout_minutes} minutes"
            await self._emit(run_id, "task_failed", run.error_message)
        except Exception as e:
            run.status = RunStatus.FAILURE
            run.error_message = str(e)[:500]
            logger.exception("Task execution failed: %s/%s", project.name, task_name)
            await self._emit(run_id, "task_failed", run.error_message)
        finally:
            run.finished_at = datetime.now(UTC)
            self.history.update_run(
                run_id=run.id, status=run.status, finished_at=run.finished_at,
                cost_usd=run.cost_usd, num_turns=run.num_turns, pr_url=run.pr_url,
                error_message=run.error_message, output_file=run.output_file,
            )
            should_cleanup = True
            if coordination_enabled and worktree_path:
                await self.broker.deregister_run(run_id)  # type: ignore[union-attr]
                if await self.broker.has_pending_mediations(run_id):  # type: ignore[union-attr]
                    should_cleanup = False
                    logger.info("Deferring worktree cleanup for %s (pending mediations)", run_id)
            if should_cleanup and worktree_path and worktree_path.exists():
                try:
                    await self._run_cmd(
                        ["git", "worktree", "remove", "--force", str(worktree_path)],
                        cwd=project.repo,
                    )
                except Exception:
                    logger.warning("Failed to remove worktree %s", worktree_path)
            self._running_processes.pop(run_id, None)

        await self.notifier.send_run_notification(run)
        if is_agent_issue and run.status in (RunStatus.FAILURE, RunStatus.TIMEOUT):
            await fail_agent_run(
                project, variables, discord_msg_id, run, 1, 1,
                self.linear_client, self.discord_notifier,
            )
        status = self.budget.get_status()
        if status.is_warning:
            await self.notifier.send_budget_warning(status)
        return run

    async def run_adhoc(
        self,
        project: ProjectConfig,
        prompt: str,
        session: "AgentSession",
        is_resume: bool = False,
        run_id: str = "",
    ) -> RunRecord:
        if not run_id:
            run_id = generate_run_id(project.name, "agent")

        run = RunRecord(
            id=run_id,
            project=project.name,
            task="agent",
            trigger_type=TriggerType.AGENT,
            started_at=datetime.now(UTC),
            status=RunStatus.RUNNING,
            model=session.model,
            session_id=session.id,
        )
        self.history.insert_run(run)
        await self._emit(run_id, "task_started", f"{project.name}/agent [agent]")

        failed = await self._check_budget(run, session.max_cost_usd)
        if failed:
            return failed
        if self.config.dry_run:
            return await self._handle_dry_run(run, f"{project.name}/agent (session={session.id})")

        worktree_path = Path(session.worktree_path)
        try:
            if is_resume:
                if not worktree_path.exists():
                    msg = f"Worktree not found for resume: {worktree_path}"
                    raise RuntimeError(msg)
            else:
                await self._run_cmd(
                    [
                        "git", "worktree", "add", str(worktree_path),
                        "-b", f"agents/session-{session.id}", project.base_branch,
                    ],
                    cwd=project.repo,
                )

            claude_cmd = [
                "claude", "-p", prompt, "--model", session.model,
                "--max-budget-usd", str(session.max_cost_usd),
                "--output-format", "stream-json", "--verbose",
                "--permission-mode", "auto",
            ]
            if is_resume and session.claude_session_id:
                claude_cmd.extend(["--resume", session.claude_session_id])

            output, raw_output = await self._run_claude(
                claude_cmd, cwd=str(worktree_path), run_id=run_id,
                timeout=self.config.timeout_minutes * 60,
            )

            output_dir = self.data_dir / "runs"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / f"{run_id}.json"
            output_file.write_text(raw_output)

            run.cost_usd = output.cost_usd
            run.num_turns = output.num_turns
            run.output_file = str(output_file)

            run.claude_session_id = output.session_id or None

            if output.is_error:
                run.status = RunStatus.FAILURE
                run.error_message = output.result[:500]
                await self._emit(run_id, "task_failed", run.error_message)
            else:
                run.status = RunStatus.SUCCESS
                await self._emit(run_id, "task_completed", "done")

        except TimeoutError:
            run.status = RunStatus.TIMEOUT
            run.error_message = f"Timed out after {self.config.timeout_minutes} minutes"
            await self._emit(run_id, "task_failed", run.error_message)
        except Exception as e:
            run.status = RunStatus.FAILURE
            run.error_message = str(e)[:500]
            logger.exception("Ad-hoc execution failed: %s/agent (session=%s)", project.name, session.id)
            await self._emit(run_id, "task_failed", run.error_message)
        finally:
            run.finished_at = datetime.now(UTC)
            self.history.update_run(
                run_id=run.id, status=run.status, finished_at=run.finished_at,
                cost_usd=run.cost_usd, num_turns=run.num_turns,
                error_message=run.error_message, output_file=run.output_file,
            )
            self._running_processes.pop(run_id, None)
            # Worktree cleanup intentionally omitted — session manager owns the lifecycle

        return run

    # ------------------------------------------------------------------
    # Compatibility shims — delegate to standalone notification helpers
    # ------------------------------------------------------------------

    async def _finalize_agent_success(
        self,
        project: ProjectConfig,
        variables: dict[str, str],
        discord_msg_id: str,
        run: RunRecord,
    ) -> None:
        await finalize_agent_success(
            project, variables, discord_msg_id, run,
            self.linear_client, self.discord_notifier,
        )

    async def _fail_agent_run(
        self,
        project: ProjectConfig,
        variables: dict[str, str],
        discord_msg_id: str,
        run: RunRecord,
        attempt: int,
        max_attempts: int,
    ) -> None:
        await fail_agent_run(
            project, variables, discord_msg_id, run, attempt, max_attempts,
            self.linear_client, self.discord_notifier,
        )

    async def cancel_run(self, run_id: str) -> bool:
        proc = self._running_processes.get(run_id)
        if proc is None:
            return False
        proc.terminate()
        return True

    async def shutdown(self) -> None:
        for run_id, proc in self._running_processes.items():
            logger.info("Terminating process for run %s", run_id)
            proc.terminate()
        for _run_id, proc in self._running_processes.items():
            try:
                await asyncio.wait_for(proc.wait(), timeout=30)
            except TimeoutError:
                proc.kill()
        self.history.mark_running_as_cancelled()
        self._running_processes.clear()

    async def _run_claude(
        self,
        cmd: list[str],
        cwd: str,
        run_id: str,
        timeout: int,
    ) -> tuple[ClaudeOutput, str]:
        from agents.streaming import RunStream

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._running_processes[run_id] = proc
        stream = RunStream(run_id=run_id, on_event=self.on_stream_event)
        try:
            result = await asyncio.wait_for(stream.process_stream(proc), timeout=timeout)
            return result, stream.get_raw_output()
        except TimeoutError:
            proc.terminate()
            raise

    async def _run_cmd(self, cmd: list[str], cwd: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            msg = f"Command failed: {' '.join(cmd)}\n{stderr.decode()}"
            raise RuntimeError(msg)
        return stdout.decode()

    async def _create_pr(
        self,
        cwd: str,
        project: ProjectConfig,
        task_name: str,
        branch: str,
        autonomy: str,
    ) -> str | None:
        log_output = await self._run_cmd(
            ["git", "log", f"{project.base_branch}..HEAD", "--oneline"],
            cwd=cwd,
        )
        if not log_output.strip():
            return None
        await self._run_cmd(["git", "push", "-u", "origin", branch], cwd=cwd)
        pr_cmd = [
            "gh", "pr", "create",
            "--title", f"[agents] {project.name}/{task_name}",
            "--body", f"Automated by Background Agent Runner\n\nTask: {task_name}\nProject: {project.name}",
            "--base", project.base_branch,
        ]
        pr_output = await self._run_cmd(pr_cmd, cwd=cwd)
        pr_url = pr_output.strip()
        if autonomy == "auto-merge":
            try:
                await self._run_cmd(
                    ["gh", "pr", "merge", "--auto", "--squash", pr_url],
                    cwd=cwd,
                )
            except RuntimeError:
                logger.warning("Failed to enable auto-merge for %s", pr_url)
        return pr_url
