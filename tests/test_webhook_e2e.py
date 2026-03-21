"""
E2E tests for the WEBHOOK → EXECUTOR flow.

These tests complement test_main.py by covering scenarios not yet tested there:
- Unknown *task* (not project) returns 404
- /status response includes the 'projects' key
- GitHub webhook with valid signature + matching task → executor triggered
- Linear webhook regular trigger (not agent-issue path) → executor triggered
- Linear webhook with invalid signature → 401
- GitHub webhook with no matching task → still returns 200 "processed"
"""

import hashlib
import hmac
import json

import pytest
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

MINIMAL_CONFIG = """
budget:
  daily_limit_usd: 10.00
  warning_threshold_usd: 7.00
  pause_on_limit: true
notifications:
  slack_webhook_url: ""
webhooks:
  github_secret: "gh-secret"
  linear_secret: "lin-secret"
execution:
  worktree_base: /tmp/test-agents-e2e
  default_model: haiku
  default_max_cost_usd: 1.00
  default_autonomy: pr-only
  max_concurrent: 2
  timeout_minutes: 10
  dry_run: true
server:
  host: 127.0.0.1
  port: 9999
"""

GITHUB_PROJECT_YAML = """
name: ghproj
repo: /tmp/gh-repo
tasks:
  ci-fix:
    description: "Fix CI failures"
    prompt: "Fix CI on {{branch}}"
    trigger:
      type: github
      events: [check_suite.completed]
      filter:
        conclusion: failure
"""

LINEAR_PROJECT_YAML = """
name: linproj
repo: /tmp/lin-repo
tasks:
  triage:
    description: "Triage Linear issue"
    prompt: "Triage {{issue_title}}"
    trigger:
      type: linear
      events: [Issue.create]
      filter: {}
"""


@pytest.fixture
def app_with_github(tmp_path):
    """App with a GitHub-triggered task."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(MINIMAL_CONFIG)
    proj_dir = tmp_path / "projects"
    proj_dir.mkdir()
    (proj_dir / "ghproj.yaml").write_text(GITHUB_PROJECT_YAML)

    from agents.main import create_app
    return create_app(config_path=cfg, projects_dir=proj_dir, data_dir=tmp_path / "data")


@pytest.fixture
def app_with_linear(tmp_path):
    """App with a Linear-triggered task."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(MINIMAL_CONFIG)
    proj_dir = tmp_path / "projects"
    proj_dir.mkdir()
    (proj_dir / "linproj.yaml").write_text(LINEAR_PROJECT_YAML)

    from agents.main import create_app
    return create_app(config_path=cfg, projects_dir=proj_dir, data_dir=tmp_path / "data")


@pytest.fixture
def app_basic(tmp_path):
    """Minimal app with a single project/task (no webhook trigger)."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(MINIMAL_CONFIG)
    proj_dir = tmp_path / "projects"
    proj_dir.mkdir()
    (proj_dir / "myproj.yaml").write_text("""
name: myproj
repo: /tmp/my-repo
tasks:
  do-work:
    description: "Do some work"
    prompt: "Work"
""")
    from agents.main import create_app
    return create_app(config_path=cfg, projects_dir=proj_dir, data_dir=tmp_path / "data")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _github_sig(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _linear_sig(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Scenario: unknown task returns 404
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_task_returns_404(app_basic):
    """POST /tasks/{valid_project}/nonexistent/run must return 404."""
    transport = ASGITransport(app=app_basic)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/tasks/myproj/nonexistent-task/run")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Scenario: /status includes 'projects' key
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_includes_projects_list(app_basic):
    """/status must include a 'projects' key listing configured project names."""
    transport = ASGITransport(app=app_basic)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "projects" in data
    assert "myproj" in data["projects"]


# ---------------------------------------------------------------------------
# Scenario: GitHub webhook → executor triggered (E2E)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_github_webhook_triggers_executor(app_with_github):
    """
    Full E2E: GitHub webhook with valid signature and matching event
    must invoke executor.run_task with trigger_type='github'.
    """
    state = app_with_github.state.app_state

    calls: list[dict] = []
    original_run_task = state.executor.run_task

    async def tracking_run_task(project, task_name, **kwargs):
        calls.append({"project": project.name, "task": task_name, "kwargs": kwargs})
        return await original_run_task(project, task_name, **kwargs)

    state.executor.run_task = tracking_run_task

    payload = {
        "action": "completed",
        "check_suite": {"head_branch": "main", "head_sha": "abc123", "conclusion": "failure"},
        "repository": {"full_name": "org/repo"},
        "conclusion": "failure",
    }
    body = json.dumps(payload).encode()
    sig = _github_sig(body, "gh-secret")

    transport = ASGITransport(app=app_with_github)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "check_suite",
                "X-Hub-Signature-256": sig,
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "processed"}
    assert len(calls) == 1
    assert calls[0]["project"] == "ghproj"
    assert calls[0]["task"] == "ci-fix"
    assert calls[0]["kwargs"]["trigger_type"] == "github"
    assert calls[0]["kwargs"]["variables"]["branch"] == "main"


# ---------------------------------------------------------------------------
# Scenario: GitHub webhook — no matching task still returns 200
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_github_webhook_no_match_returns_processed(app_with_github):
    """
    GitHub webhook with valid signature but event that doesn't match any task
    must return 200 'processed' without triggering the executor.
    """
    state = app_with_github.state.app_state

    calls: list[dict] = []
    original_run_task = state.executor.run_task

    async def tracking_run_task(project, task_name, **kwargs):
        calls.append(task_name)
        return await original_run_task(project, task_name, **kwargs)

    state.executor.run_task = tracking_run_task

    # 'push' event — task only listens to check_suite.completed
    payload = {"ref": "refs/heads/main", "repository": {"full_name": "org/repo"}}
    body = json.dumps(payload).encode()
    sig = _github_sig(body, "gh-secret")

    transport = ASGITransport(app=app_with_github)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": sig,
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "processed"}
    assert calls == [], "Executor must not be called when no task matches"


# ---------------------------------------------------------------------------
# Scenario: Linear webhook — regular trigger → executor triggered (E2E)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_linear_webhook_regular_trigger_fires_executor(app_with_linear):
    """
    Full E2E: Linear webhook with a matching regular trigger (not agent-issue path)
    must invoke executor.run_task with trigger_type='linear'.
    """
    state = app_with_linear.state.app_state

    calls: list[dict] = []
    original_run_task = state.executor.run_task

    async def tracking_run_task(project, task_name, **kwargs):
        calls.append({"project": project.name, "task": task_name, "kwargs": kwargs})
        return await original_run_task(project, task_name, **kwargs)

    state.executor.run_task = tracking_run_task

    payload = {
        "action": "create",
        "type": "Issue",
        "data": {
            "id": "issue-lin-1",
            "identifier": "LIN-1",
            "title": "Login broken",
            "description": "Users can't log in",
            "teamId": "team-lin",
            "labels": [],
        },
    }
    body = json.dumps(payload).encode()
    sig = _linear_sig(body, "lin-secret")

    transport = ASGITransport(app=app_with_linear)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhooks/linear",
            content=body,
            headers={
                "Linear-Signature": sig,
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "processed"}
    # At least the regular-trigger call must be present
    triggered = [c for c in calls if c["task"] == "triage"]
    assert len(triggered) >= 1
    assert triggered[0]["kwargs"]["trigger_type"] == "linear"
    assert triggered[0]["kwargs"]["variables"]["issue_title"] == "Login broken"


# ---------------------------------------------------------------------------
# Scenario: Linear webhook invalid signature → 401
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_linear_webhook_invalid_signature_returns_401(app_with_linear):
    """Linear webhook with a bad signature must be rejected with 401."""
    payload = {"action": "create", "type": "Issue", "data": {}}
    body = json.dumps(payload).encode()

    transport = ASGITransport(app=app_with_linear)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhooks/linear",
            content=body,
            headers={
                "Linear-Signature": "bad-signature",
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Scenario: Manual trigger dry_run completes and returns run_id
# (complementary to test_main: verifies run_id format contains project+task)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_manual_trigger_run_id_format(app_basic):
    """
    POST /tasks/{project}/{task}/run must return 202 with a run_id
    that contains the project and task names.
    """
    transport = ASGITransport(app=app_basic)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/tasks/myproj/do-work/run")
    assert resp.status_code == 202
    data = resp.json()
    assert "run_id" in data
    assert "myproj" in data["run_id"]
    assert "do-work" in data["run_id"]
