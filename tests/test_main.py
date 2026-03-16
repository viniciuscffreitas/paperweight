import pytest


@pytest.fixture
def test_app(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
budget:
  daily_limit_usd: 10.00
  warning_threshold_usd: 7.00
  pause_on_limit: true
notifications:
  slack_webhook_url: ""
webhooks:
  github_secret: test-secret
  linear_secret: test-linear-secret
execution:
  worktree_base: /tmp/test-agents
  default_model: sonnet
  default_max_cost_usd: 5.00
  default_autonomy: pr-only
  max_concurrent: 3
  timeout_minutes: 15
  dry_run: true
server:
  host: 127.0.0.1
  port: 9090
""")
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    (projects_dir / "testproj.yaml").write_text("""
name: testproj
repo: /tmp/test-repo
tasks:
  hello:
    description: "Test task"
    schedule: "0 9 * * *"
    model: haiku
    max_cost_usd: 0.10
    prompt: "Say hello"
""")
    from agents.main import create_app

    app = create_app(config_path=config_file, projects_dir=projects_dir, data_dir=tmp_path / "data")
    return app


@pytest.fixture
def client(test_app):
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=test_app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_status(client):
    response = await client.get("/status")
    assert response.status_code == 200
    data = response.json()
    assert "budget" in data
    assert "runs_today" in data


@pytest.mark.asyncio
async def test_status_budget(client):
    response = await client.get("/status/budget")
    assert response.status_code == 200
    data = response.json()
    assert "daily_limit_usd" in data
    assert "spent_today_usd" in data
    assert "remaining_usd" in data


@pytest.mark.asyncio
async def test_manual_trigger(client):
    response = await client.post("/tasks/testproj/hello/run")
    assert response.status_code == 202
    data = response.json()
    assert "run_id" in data


@pytest.mark.asyncio
async def test_manual_trigger_unknown_project(client):
    response = await client.post("/tasks/unknown/hello/run")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_github_webhook_no_signature(client):
    response = await client.post(
        "/webhooks/github", content=b"{}", headers={"X-GitHub-Event": "push"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_broadcast_event_persists_to_db(test_app):
    """Events emitted via broadcast_event must be persisted to SQLite."""
    state = test_app.state.app_state
    project = list(state.projects.values())[0]
    task_name = list(project.tasks.keys())[0]

    run = await state.executor.run_task(project, task_name, trigger_type="manual")

    events = state.history.list_events(run.id)
    assert len(events) > 0
    event_types = [e["type"] for e in events]
    assert "task_started" in event_types


@pytest.mark.asyncio
async def test_broadcast_event_persists_dry_run_events(test_app):
    """Dry run events (dry_run + task_completed) are persisted to SQLite."""
    state = test_app.state.app_state
    project = list(state.projects.values())[0]
    task_name = list(project.tasks.keys())[0]

    run = await state.executor.run_task(project, task_name, trigger_type="manual")

    events = state.history.list_events(run.id)
    event_types = [e["type"] for e in events]
    assert "dry_run" in event_types
    assert "task_completed" in event_types
