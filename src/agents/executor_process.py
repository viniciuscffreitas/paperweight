"""Subprocess helpers for the Executor — process management and Claude CLI launcher."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.executor_utils import ClaudeOutput
    from agents.history import HistoryDB

logger = logging.getLogger(__name__)


async def run_cmd(cmd: list[str], cwd: str) -> str:
    """Run a generic subprocess and return stdout.  Raises RuntimeError on non-zero exit."""
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


async def run_claude(
    cmd: list[str],
    cwd: str,
    run_id: str,
    timeout: int,
    env: dict[str, str] | None,
    running_processes: dict[str, asyncio.subprocess.Process],
    on_stream_event: Callable,
) -> tuple[ClaudeOutput, str]:
    """Launch the Claude CLI and stream its output.

    Registers the process in *running_processes* so it can be cancelled.
    """
    import os as _os

    from agents.streaming import RunStream

    # Ensure ~/.local/bin is in PATH for claude/gh CLIs
    run_env = env or {**_os.environ}
    path = run_env.get("PATH", "")
    home = _os.path.expanduser("~")
    local_bin = f"{home}/.local/bin"
    if local_bin not in path:
        run_env["PATH"] = f"{local_bin}:{path}"

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=run_env,
    )
    running_processes[run_id] = proc
    stream = RunStream(run_id=run_id, on_event=on_stream_event)
    try:
        result = await asyncio.wait_for(stream.process_stream(proc), timeout=timeout)
        return result, stream.get_raw_output()
    except TimeoutError:
        proc.terminate()
        raise


async def cancel_run(
    running_processes: dict[str, asyncio.subprocess.Process],
    run_id: str,
) -> bool:
    """Terminate the process for *run_id*.  Returns True if found, False if not running."""
    proc = running_processes.get(run_id)
    if proc is None:
        return False
    proc.terminate()
    return True


async def shutdown(
    running_processes: dict[str, asyncio.subprocess.Process],
    history: HistoryDB,
) -> None:
    """Terminate all running processes and mark them cancelled in the history DB."""
    for run_id, proc in running_processes.items():
        logger.info("Terminating process for run %s", run_id)
        proc.terminate()
    for _run_id, proc in running_processes.items():
        try:
            await asyncio.wait_for(proc.wait(), timeout=30)
        except TimeoutError:
            proc.kill()
    history.mark_running_as_cancelled()
    running_processes.clear()
