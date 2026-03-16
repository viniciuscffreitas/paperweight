import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from agents.budget import BudgetManager
from agents.config import ExecutionConfig, build_prompt
from agents.history import HistoryDB
from agents.models import ProjectConfig, RunRecord, RunStatus, TriggerType
from agents.notifier import Notifier

logger = logging.getLogger(__name__)


class ClaudeOutput(BaseModel):
    result: str = ""
    is_error: bool = False
    cost_usd: float = 0.0
    num_turns: int = 0


def generate_run_id(project: str, task: str) -> str:
    short_uuid = uuid.uuid4().hex[:8]
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{project}-{task}-{timestamp}-{short_uuid}"


def generate_branch_name(prefix: str, task: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{prefix}{task}-{timestamp}"


def parse_claude_output(raw: str) -> ClaudeOutput:
    try:
        data = json.loads(raw)
        return ClaudeOutput(
            result=data.get("result", ""),
            is_error=data.get("is_error", False),
            cost_usd=data.get("total_cost_usd", 0.0),
            num_turns=data.get("num_turns", 0),
        )
    except (json.JSONDecodeError, KeyError):
        return ClaudeOutput(result=raw, is_error=True)


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

    async def _noop_event(self, run_id: str, event: object) -> None:
        pass

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
        run_id = generate_run_id(project.name, task_name)
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

        if not self.budget.can_afford(task.max_cost_usd):
            run.status = RunStatus.FAILURE
            run.error_message = (
                f"Budget exceeded. Need ${task.max_cost_usd}, "
                f"remaining: ${self.budget.get_status().remaining_usd:.2f}"
            )
            run.finished_at = datetime.now(UTC)
            self.history.update_run(
                run_id=run.id,
                status=run.status,
                finished_at=run.finished_at,
                error_message=run.error_message,
            )
            await self._emit(run_id, "task_failed", run.error_message)
            await self.notifier.send_run_notification(run)
            return run

        if self.config.dry_run:
            logger.info("DRY RUN: would execute %s/%s", project.name, task_name)
            await self._emit(run_id, "dry_run", "dry_run=true — skipping Claude execution")
            run.status = RunStatus.SUCCESS
            run.cost_usd = 0.0
            run.finished_at = datetime.now(UTC)
            self.history.update_run(
                run_id=run.id,
                status=run.status,
                finished_at=run.finished_at,
                cost_usd=0.0,
            )
            await self._emit(run_id, "task_completed", "done (dry run)")
            return run

        worktree_path: Path | None = None
        try:
            prompt = build_prompt(task, variables or {})
            branch_name = generate_branch_name(project.branch_prefix, task_name)
            worktree_path = Path(self.config.worktree_base) / run_id

            await self._run_cmd(
                [
                    "git",
                    "worktree",
                    "add",
                    str(worktree_path),
                    "-b",
                    branch_name,
                    project.base_branch,
                ],
                cwd=project.repo,
            )

            claude_cmd = [
                "claude",
                "-p",
                prompt,
                "--model",
                task.model,
                "--max-budget-usd",
                str(task.max_cost_usd),
                "--output-format",
                "stream-json",
                "--verbose",
                "--permission-mode",
                "auto",
                "--no-session-persistence",
            ]

            output, raw_output = await self._run_claude(
                claude_cmd,
                cwd=str(worktree_path),
                run_id=run_id,
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
                    cwd=str(worktree_path),
                    project=project,
                    task_name=task_name,
                    branch=branch_name,
                    autonomy=task.autonomy,
                )
                run.status = RunStatus.SUCCESS
                run.pr_url = pr_url
                msg = f"done — PR: {pr_url}" if pr_url else "done (no changes)"
                await self._emit(run_id, "task_completed", msg)

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
                run_id=run.id,
                status=run.status,
                finished_at=run.finished_at,
                cost_usd=run.cost_usd,
                num_turns=run.num_turns,
                pr_url=run.pr_url,
                error_message=run.error_message,
                output_file=run.output_file,
            )
            if worktree_path and worktree_path.exists():
                try:
                    await self._run_cmd(
                        ["git", "worktree", "remove", "--force", str(worktree_path)],
                        cwd=project.repo,
                    )
                except Exception:
                    logger.warning("Failed to remove worktree %s", worktree_path)
            self._running_processes.pop(run_id, None)

        await self.notifier.send_run_notification(run)
        status = self.budget.get_status()
        if status.is_warning:
            await self.notifier.send_budget_warning(status)
        return run

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
            "gh",
            "pr",
            "create",
            "--title",
            f"[agents] {project.name}/{task_name}",
            "--body",
            f"Automated by Background Agent Runner\n\nTask: {task_name}\nProject: {project.name}",
            "--base",
            project.base_branch,
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
