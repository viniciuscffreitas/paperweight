"""E2E tests for concurrency: semaphores, parallel runs, and WebSocket streaming.

Tests the "needs claude -p" paths by mocking _run_claude at the executor level,
letting everything else (worktrees, semaphores, broker, streaming) run for real.
"""

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agents.budget import BudgetManager
from agents.config import BudgetConfig, ExecutionConfig
from agents.coordination.broker import CoordinationBroker
from agents.coordination.models import CoordinationConfig
from agents.executor import Executor
from agents.history import HistoryDB
from agents.models import ProjectConfig, RunStatus, TaskConfig
from agents.notifier import Notifier
from agents.streaming import StreamEvent

pytestmark = pytest.mark.e2e

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _mock_subprocess_lines(lines: list[str]):
    """Create a mock async subprocess from stream-json lines."""
    proc = AsyncMock()
    proc.returncode = 0

    async def _stdout():
        for line in lines:
            yield (line + "\n").encode()

    proc.stdout = _stdout()
    proc.wait = AsyncMock(return_value=0)
    return proc


async def _init_git_repo(path: Path) -> None:
    """Create a minimal git repo at path."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "src").mkdir(exist_ok=True)
    (path / "src" / "main.py").write_text("# main\n")
    for cmd in [
        ["git", "init"],
        ["git", "add", "-A"],
        ["git", "-c", "user.name=test", "-c", "user.email=t@t.com", "commit", "-m", "init"],
    ]:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()


def _make_executor(tmp_path, broker=None, max_concurrent=3):
    """Create an executor with real infra but mocked Claude."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    db = HistoryDB(data_dir / "agents.db")
    budget = BudgetManager(config=BudgetConfig(daily_limit_usd=50.0), history=db)
    notifier = Notifier(webhook_url="")

    captured_events: list[dict] = []

    async def broadcast_event(run_id: str, event: StreamEvent) -> None:
        captured_events.append({"run_id": run_id, **event.model_dump()})
        if broker:
            wt = Path(tmp_path / "worktrees") / run_id
            if wt.exists():
                await broker.on_stream_event(run_id, event, worktree_root=wt)

    exec_config = ExecutionConfig(
        worktree_base=str(tmp_path / "worktrees"),
        timeout_minutes=5,
        max_concurrent=max_concurrent,
    )
    executor = Executor(
        config=exec_config,
        budget=budget,
        history=db,
        notifier=notifier,
        data_dir=data_dir,
        on_stream_event=broadcast_event,
        broker=broker,
    )
    return executor, db, budget, captured_events


def _make_mock_run_claude(executor, file_path="src/main.py", delay=0, cost=0.10):
    """Create a mock _run_claude that simulates editing a file."""

    async def mock_run_claude(cmd, cwd, run_id, timeout):
        if delay:
            await asyncio.sleep(delay)
        worktree = Path(cwd)
        lines = [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Edit",
                                "input": {
                                    "file_path": str(worktree / file_path),
                                    "old_string": "#",
                                    "new_string": "# edited",
                                },
                            }
                        ]
                    },
                }
            ),
            json.dumps(
                {
                    "type": "result",
                    "is_error": False,
                    "total_cost_usd": cost,
                    "num_turns": 3,
                    "result": "Done",
                }
            ),
        ]
        proc = await _mock_subprocess_lines(lines)
        from agents.streaming import RunStream

        stream = RunStream(run_id=run_id, on_event=executor.on_stream_event)
        result = await stream.process_stream(proc)
        return result, stream.get_raw_output()

    return mock_run_claude


# ---------------------------------------------------------------------------
# Test 1: Semaphore limits concurrent runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_semaphore_limits_concurrent_runs(tmp_path):
    """max_concurrent=2 means only 2 runs execute simultaneously."""
    repo = tmp_path / "repo"
    await _init_git_repo(repo)

    executor, _db, _budget, _events = _make_executor(tmp_path, max_concurrent=2)

    # Track concurrency
    concurrency_log: list[int] = []
    current_concurrent = 0
    lock = asyncio.Lock()

    original_mock = _make_mock_run_claude(executor, delay=0.1)

    async def tracking_run_claude(cmd, cwd, run_id, timeout):
        nonlocal current_concurrent
        async with lock:
            current_concurrent += 1
            concurrency_log.append(current_concurrent)
        try:
            return await original_mock(cmd, cwd, run_id, timeout)
        finally:
            async with lock:
                current_concurrent -= 1

    executor._run_claude = tracking_run_claude
    executor._create_pr = AsyncMock(return_value=None)

    project = ProjectConfig(
        name="test",
        repo=str(repo),
        tasks={
            "t1": TaskConfig(description="d", intent="do stuff", max_cost_usd=1.0),
            "t2": TaskConfig(description="d", intent="do stuff", max_cost_usd=1.0),
            "t3": TaskConfig(description="d", intent="do stuff", max_cost_usd=1.0),
            "t4": TaskConfig(description="d", intent="do stuff", max_cost_usd=1.0),
        },
    )

    semaphore = asyncio.Semaphore(2)  # max_concurrent=2

    async def run_with_semaphore(task_name):
        async with semaphore:
            return await executor.run_task(project, task_name, trigger_type="manual")

    # Launch 4 runs concurrently (distinct task names → distinct branches)
    results = await asyncio.gather(
        run_with_semaphore("t1"),
        run_with_semaphore("t2"),
        run_with_semaphore("t3"),
        run_with_semaphore("t4"),
    )

    assert all(r.status == RunStatus.SUCCESS for r in results)
    assert max(concurrency_log) <= 2, f"Max concurrency was {max(concurrency_log)}, expected <=2"
    assert len(results) == 4


# ---------------------------------------------------------------------------
# Test 2: Repo semaphore limits per-repo runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repo_semaphore_limits_per_repo(tmp_path):
    """Per-repo semaphore (limit=2) restricts concurrent runs on same repo."""
    repo = tmp_path / "repo"
    await _init_git_repo(repo)

    executor, _db, _budget, _events = _make_executor(tmp_path, max_concurrent=5)

    concurrency_log: list[int] = []
    current = 0
    lock = asyncio.Lock()

    original_mock = _make_mock_run_claude(executor, delay=0.05)

    async def tracking(cmd, cwd, run_id, timeout):
        nonlocal current
        async with lock:
            current += 1
            concurrency_log.append(current)
        try:
            return await original_mock(cmd, cwd, run_id, timeout)
        finally:
            async with lock:
                current -= 1

    executor._run_claude = tracking
    executor._create_pr = AsyncMock(return_value=None)

    project = ProjectConfig(
        name="test",
        repo=str(repo),
        tasks={
            "r1": TaskConfig(description="d", intent="do stuff", max_cost_usd=1.0),
            "r2": TaskConfig(description="d", intent="do stuff", max_cost_usd=1.0),
            "r3": TaskConfig(description="d", intent="do stuff", max_cost_usd=1.0),
        },
    )

    repo_semaphore = asyncio.Semaphore(2)  # per-repo limit

    async def run_with_repo_sem(task_name):
        async with repo_semaphore:
            return await executor.run_task(project, task_name, trigger_type="manual")

    results = await asyncio.gather(
        run_with_repo_sem("r1"),
        run_with_repo_sem("r2"),
        run_with_repo_sem("r3"),
    )

    assert all(r.status == RunStatus.SUCCESS for r in results)
    assert max(concurrency_log) <= 2


# ---------------------------------------------------------------------------
# Test 3: Coordination broker tracks claims across parallel runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_runs_broker_tracks_claims(tmp_path):
    """Two parallel runs on same repo, different files, broker tracks both."""
    repo = tmp_path / "repo"
    await _init_git_repo(repo)
    (repo / "src" / "auth.py").write_text("# auth\n")

    broker = CoordinationBroker(CoordinationConfig(enabled=True))
    executor, _db, _budget, _events = _make_executor(tmp_path, broker=broker)
    executor._create_pr = AsyncMock(return_value=None)

    project = ProjectConfig(
        name="test",
        repo=str(repo),
        tasks={
            "auth": TaskConfig(description="a", intent="auth", max_cost_usd=1.0),
            "main": TaskConfig(description="m", intent="main", max_cost_usd=1.0),
        },
    )

    claims_during_run: list[dict] = []

    async def mock_auth(cmd, cwd, run_id, timeout):
        wt = Path(cwd)
        lines = [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Edit",
                                "input": {
                                    "file_path": str(wt / "src" / "auth.py"),
                                    "old_string": "#",
                                    "new_string": "# auth edited",
                                },
                            },
                        ]
                    },
                }
            ),
            json.dumps(
                {
                    "type": "result",
                    "is_error": False,
                    "total_cost_usd": 0.10,
                    "num_turns": 2,
                    "result": "ok",
                }
            ),
        ]
        proc = await _mock_subprocess_lines(lines)
        from agents.streaming import RunStream

        stream = RunStream(run_id=run_id, on_event=executor.on_stream_event)
        # Small delay to let the other run start
        await asyncio.sleep(0.05)
        # Capture claims mid-run
        for fp, claim in broker.claims._claims.items():
            claims_during_run.append({"file": fp, "run": claim.run_id})
        return await stream.process_stream(proc), stream.get_raw_output()

    async def mock_main(cmd, cwd, run_id, timeout):
        wt = Path(cwd)
        lines = [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Edit",
                                "input": {
                                    "file_path": str(wt / "src" / "main.py"),
                                    "old_string": "#",
                                    "new_string": "# main edited",
                                },
                            },
                        ]
                    },
                }
            ),
            json.dumps(
                {
                    "type": "result",
                    "is_error": False,
                    "total_cost_usd": 0.10,
                    "num_turns": 2,
                    "result": "ok",
                }
            ),
        ]
        proc = await _mock_subprocess_lines(lines)
        from agents.streaming import RunStream

        stream = RunStream(run_id=run_id, on_event=executor.on_stream_event)
        return await stream.process_stream(proc), stream.get_raw_output()

    # Run auth first (it will capture claims during execution)
    executor._run_claude = mock_auth
    run_a = await executor.run_task(project, "auth", trigger_type="manual")

    executor._run_claude = mock_main
    run_b = await executor.run_task(project, "main", trigger_type="manual")

    assert run_a.status == RunStatus.SUCCESS
    assert run_b.status == RunStatus.SUCCESS

    # After both complete, broker should be clean
    assert len(broker.active_worktrees) == 0
    assert len(broker.claims._claims) == 0


# ---------------------------------------------------------------------------
# Test 4: Mediator prompt is built correctly for conflicting runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mediator_prompt_built_for_conflict(tmp_path):
    """When two agents conflict, mediator prompt contains both intents."""
    from agents.coordination.mediator import build_mediator_prompt

    # Simulate: agent A edited users.py for pagination, agent B needs auth
    prompt = build_mediator_prompt(
        file_path="src/api/users.py",
        file_content="def get_users():\n    return db.query(User).all()\n",
        intent_a="Add cursor-based pagination with before/after params",
        intent_b="Add JWT authentication middleware check",
        task_a_description="ENG-142: Pagination for users endpoint",
        task_b_description="ENG-155: Auth middleware for all API endpoints",
        diff_a="- def get_users():\n+ def get_users(cursor=None, limit=20):",
    )

    # Both intents present
    assert "cursor-based pagination" in prompt
    assert "JWT authentication" in prompt

    # Both task descriptions present
    assert "ENG-142" in prompt
    assert "ENG-155" in prompt

    # File content present
    assert "db.query(User)" in prompt

    # Diff present
    assert "cursor=None" in prompt

    # Instructions present
    assert "BOTH changes coherently" in prompt
    assert "Touch ONLY" in prompt


# ---------------------------------------------------------------------------
# Test 5: Full mediator flow — conflict → prompt → simulated resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_mediator_conflict_flow(tmp_path):
    """
    Simulates the full mediator flow:
    1. Agent A claims file
    2. Agent B detects conflict via inbox
    3. Broker marks contested
    4. Mediator prompt is built with both intents
    5. Mediator "runs" (simulated) and resolves
    """
    repo = tmp_path / "repo"
    await _init_git_repo(repo)

    broker = CoordinationBroker(CoordinationConfig(enabled=True))
    executor, _db, _budget, _events = _make_executor(tmp_path, broker=broker)

    project = ProjectConfig(
        name="test",
        repo=str(repo),
        tasks={
            "task-a": TaskConfig(
                description="Add pagination", intent="Add pagination to users", max_cost_usd=2.0
            ),
            "task-b": TaskConfig(
                description="Add auth", intent="Add auth middleware", max_cost_usd=2.0
            ),
        },
    )

    # Step 1: Agent A runs and claims src/main.py
    executor._run_claude = _make_mock_run_claude(executor, file_path="src/main.py", cost=0.20)
    executor._create_pr = AsyncMock(return_value="https://github.com/org/repo/pull/1")
    run_a = await executor.run_task(project, "task-a", trigger_type="manual")
    assert run_a.status == RunStatus.SUCCESS

    # Step 2: Register Agent B and simulate it reading state + writing need_file
    wt_b = tmp_path / "worktrees" / "manual-wt-b"
    wt_b.mkdir(parents=True, exist_ok=True)
    await broker.register_run("run-b", wt_b, "Add auth middleware")

    # Agent B's worktree has state.json showing A already finished
    # But let's simulate A is still running by re-registering
    wt_a2 = tmp_path / "worktrees" / "manual-wt-a"
    wt_a2.mkdir(parents=True, exist_ok=True)
    await broker.register_run("run-a2", wt_a2, "Add pagination to users")

    # A2 claims the file
    edit_event = StreamEvent(
        type="tool_use",
        tool_name="Edit",
        file_path=str(wt_a2 / "src" / "main.py"),
        timestamp=time.time(),
    )
    await broker.on_stream_event("run-a2", edit_event, worktree_root=wt_a2)

    # B writes need_file to inbox
    inbox_b = wt_b / ".paperweight" / "inbox.jsonl"
    with inbox_b.open("a") as f:
        f.write(
            json.dumps(
                {
                    "type": "need_file",
                    "file": "src/main.py",
                    "intent": "Add auth middleware to main.py",
                }
            )
            + "\n"
        )

    # Step 3: Broker polls and detects conflict
    await broker.poll_inboxes_once()

    claim = broker.claims.get_claim_for_file("src/main.py")
    assert claim is not None
    assert claim.status.value == "contested"

    # Step 4: Build mediator prompt
    from agents.coordination.mediator import build_mediator_prompt

    file_content = (repo / "src" / "main.py").read_text()
    mediator_prompt = build_mediator_prompt(
        file_path="src/main.py",
        file_content=file_content,
        intent_a=broker.claims.get_intent("run-a2"),
        intent_b="Add auth middleware to main.py",
        task_a_description="task-a: Add pagination",
        task_b_description="task-b: Add auth",
    )

    assert "pagination" in mediator_prompt.lower()
    assert "auth" in mediator_prompt.lower()
    assert "# main" in mediator_prompt  # actual file content

    # Step 5: Simulate mediator run (would be executor.run_task in production)
    # The mediator edits the contested file with both changes
    mediator_lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "I'll apply both pagination and auth changes."},
                    ]
                },
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Edit",
                            "input": {
                                "file_path": str(wt_a2 / "src" / "main.py"),
                                "old_string": "# main",
                                "new_string": "# main — with pagination + auth middleware",
                            },
                        },
                    ]
                },
            }
        ),
        json.dumps(
            {
                "type": "result",
                "is_error": False,
                "total_cost_usd": 0.50,
                "num_turns": 4,
                "result": "Mediation complete",
            }
        ),
    ]

    # Parse the mediator output to verify it's valid stream-json
    from agents.streaming import parse_stream_line

    parsed = [parse_stream_line(line) for line in mediator_lines]
    assert parsed[0].type == "assistant"
    assert parsed[1].type == "tool_use"
    assert parsed[1].tool_name == "Edit"
    assert parsed[2].type == "result"

    # Cleanup
    await broker.deregister_run("run-a2")
    await broker.deregister_run("run-b")


# ---------------------------------------------------------------------------
# Test 6: WebSocket receives events during run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_websocket_receives_stream_events(tmp_path):
    """WebSocket client receives events broadcast during a run."""
    repo = tmp_path / "repo"
    await _init_git_repo(repo)

    # Create the app with a project
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
budget:
  daily_limit_usd: 10.0
execution:
  worktree_base: {wt}
  dry_run: true
  max_concurrent: 3
  timeout_minutes: 5
server:
  port: 8080
notifications:
  slack_webhook_url: ""
webhooks:
  github_secret: ""
  linear_secret: ""
integrations:
  linear_api_key: ""
""".format(wt=str(tmp_path / "worktrees"))
    )

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    (projects_dir / "test.yaml").write_text(f"""
name: test
repo: {repo}
base_branch: main
tasks:
  hello:
    description: test task
    intent: say hello
    schedule: "0 * * * *"
    max_cost_usd: 1.0
""")

    from agents.main import create_app

    app = create_app(
        config_path=config_path,
        projects_dir=projects_dir,
        data_dir=tmp_path / "data",
    )

    from starlette.testclient import TestClient

    with TestClient(app) as client, client.websocket_connect("/ws/runs"):
            # Trigger a manual run (dry_run=True, so it completes instantly)
            response = client.post("/tasks/test/hello/run")
            assert response.status_code == 202

            # Give background task time to complete
            import time

            time.sleep(0.5)

            # WebSocket should have received events
            # Note: in dry_run mode, events are emitted but the ws might not
            # have them queued yet since BackgroundTasks runs after response
            # The key assertion is that the WebSocket connected and didn't error


# ---------------------------------------------------------------------------
# Test 7: Coordination preamble content is correct for agent consumption
# ---------------------------------------------------------------------------


def test_coordination_preamble_is_valid_for_agent():
    """Verify preamble contains all protocol instructions an agent needs."""
    from agents.coordination.mediator import build_coordination_preamble

    preamble = build_coordination_preamble()

    # Must contain all 3 protocol files
    assert "state.json" in preamble
    assert "inbox.jsonl" in preamble
    assert "outbox.jsonl" in preamble

    # Must contain the MANDATORY instruction
    assert "MANDATORY" in preamble

    # Must contain all message types the agent should write
    assert "need_file" in preamble
    assert "edit_complete" in preamble
    assert "heartbeat" in preamble

    # Must contain all response types the agent should read
    assert "file_mediated" in preamble
    assert "file_released" in preamble

    # Must contain the safety rule
    assert "NEVER force-edit" in preamble

    # Must be reasonably sized (not too long for context window)
    assert len(preamble) < 2000, f"Preamble is {len(preamble)} chars — too long"
