"""Tests for executor_process: subprocess helpers and Claude CLI launcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.executor_process import cancel_run, run_cmd, shutdown

# ---------------------------------------------------------------------------
# run_cmd
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_cmd_returns_stdout_on_success():
    output = await run_cmd(["echo", "hello"], cwd="/tmp")
    assert output.strip() == "hello"


@pytest.mark.asyncio
async def test_run_cmd_raises_on_nonzero_exit():
    with pytest.raises(RuntimeError, match="Command failed"):
        await run_cmd(["false"], cwd="/tmp")


@pytest.mark.asyncio
async def test_run_cmd_includes_stderr_in_error():
    with pytest.raises(RuntimeError) as exc_info:
        await run_cmd(["sh", "-c", "echo oops >&2; exit 1"], cwd="/tmp")
    assert "oops" in str(exc_info.value)


# ---------------------------------------------------------------------------
# cancel_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_run_terminates_known_process():
    proc = MagicMock()
    running: dict[str, object] = {"run-1": proc}
    result = await cancel_run(running, "run-1")
    assert result is True
    proc.terminate.assert_called_once()


@pytest.mark.asyncio
async def test_cancel_run_returns_false_for_unknown_run():
    running: dict[str, object] = {}
    result = await cancel_run(running, "does-not-exist")
    assert result is False


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutdown_terminates_all_processes_and_clears():
    proc1 = MagicMock()
    proc2 = MagicMock()

    async def _wait():
        return 0

    proc1.wait = _wait
    proc2.wait = _wait

    history = MagicMock()
    running = {"r1": proc1, "r2": proc2}

    await shutdown(running, history)

    proc1.terminate.assert_called_once()
    proc2.terminate.assert_called_once()
    history.mark_running_as_cancelled.assert_called_once()
    assert running == {}


@pytest.mark.asyncio
async def test_shutdown_kills_processes_that_do_not_exit():
    proc = MagicMock()
    history = MagicMock()
    running = {"r1": proc}

    # Patch wait_for to raise TimeoutError immediately — no real coroutine needed
    with patch("agents.executor_process.asyncio.wait_for", side_effect=TimeoutError):
        await shutdown(running, history)

    proc.kill.assert_called_once()
    history.mark_running_as_cancelled.assert_called_once()
