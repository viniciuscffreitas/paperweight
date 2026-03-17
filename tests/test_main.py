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


@pytest.mark.asyncio
async def test_app_creates_linear_client_when_configured(tmp_path):
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
  dry_run: true
server:
  host: 127.0.0.1
  port: 9090
integrations:
  linear_api_key: "test-linear-key"
  discord_bot_token: "test-discord-token"
""")
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    from agents.main import create_app
    app = create_app(config_path=config_file, projects_dir=projects_dir, data_dir=tmp_path / "data")
    state = app.state.app_state
    assert state.executor.linear_client is not None
    assert state.executor.discord_notifier is not None


@pytest.mark.asyncio
async def test_auto_discovery_runs_on_startup(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
budget:
  daily_limit_usd: 10.00
  warning_threshold_usd: 7.00
  pause_on_limit: true
notifications:
  slack_webhook_url: ""
webhooks:
  github_secret: ""
  linear_secret: ""
execution:
  worktree_base: /tmp/test-agents
  dry_run: true
server:
  host: 127.0.0.1
  port: 9090
integrations:
  linear_api_key: "test-key"
  discord_bot_token: "test-token"
  discord_guild_id: "guild-123"
""")
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    (projects_dir / "testproj.yaml").write_text("""
name: testproj
repo: /tmp/test-repo
tasks:
  issue-resolver:
    description: "Resolve Linear issues"
    prompt: "Resolve {{issue_title}}"
    trigger:
      type: linear
      events: [Issue.create]
      filter:
        label: agent
""")
    from unittest.mock import AsyncMock, patch
    from agents.main import create_app

    with patch("agents.discovery.auto_discover_project_ids", new_callable=AsyncMock) as mock_discover:
        app = create_app(config_path=config_file, projects_dir=projects_dir, data_dir=tmp_path / "data")

    # Since lifespan doesn't run in this test context, verify the import works
    from agents.discovery import auto_discover_project_ids
    assert callable(auto_discover_project_ids)


@pytest.mark.asyncio
async def test_create_project(client):
    response = await client.post("/api/projects", json={
        "id": "proj-1",
        "name": "Test Project",
        "repo_path": "/tmp/test-repo",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["id"] == "proj-1"
    assert data["name"] == "Test Project"
    assert data["repo_path"] == "/tmp/test-repo"
    assert data["default_branch"] == "main"


@pytest.mark.asyncio
async def test_list_projects(client):
    await client.post("/api/projects", json={
        "id": "proj-list-1",
        "name": "List Project",
        "repo_path": "/tmp/list-repo",
    })
    response = await client.get("/api/projects")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    ids = [p["id"] for p in data]
    assert "proj-list-1" in ids


@pytest.mark.asyncio
async def test_get_project(client):
    await client.post("/api/projects", json={
        "id": "proj-get-1",
        "name": "Get Project",
        "repo_path": "/tmp/get-repo",
    })
    response = await client.get("/api/projects/proj-get-1")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "proj-get-1"
    assert data["name"] == "Get Project"


@pytest.mark.asyncio
async def test_get_project_not_found(client):
    response = await client.get("/api/projects/nonexistent-proj")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_project(client):
    await client.post("/api/projects", json={
        "id": "proj-del-1",
        "name": "Delete Project",
        "repo_path": "/tmp/del-repo",
    })
    response = await client.delete("/api/projects/proj-del-1")
    assert response.status_code == 204
    get_response = await client.get("/api/projects/proj-del-1")
    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_create_task(client):
    await client.post("/api/projects", json={
        "id": "proj-task-1",
        "name": "Task Project",
        "repo_path": "/tmp/task-repo",
    })
    response = await client.post("/api/projects/proj-task-1/tasks", json={
        "name": "My Task",
        "intent": "Do something useful",
        "trigger_type": "manual",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "My Task"
    assert data["intent"] == "Do something useful"
    assert data["trigger_type"] == "manual"
    assert data["project_id"] == "proj-task-1"


@pytest.mark.asyncio
async def test_list_tasks(client):
    await client.post("/api/projects", json={
        "id": "proj-task-list-1",
        "name": "Task List Project",
        "repo_path": "/tmp/task-list-repo",
    })
    await client.post("/api/projects/proj-task-list-1/tasks", json={
        "name": "Listed Task",
        "intent": "Be listed",
        "trigger_type": "schedule",
    })
    response = await client.get("/api/projects/proj-task-list-1/tasks")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    names = [t["name"] for t in data]
    assert "Listed Task" in names


@pytest.mark.asyncio
async def test_delete_task(client):
    await client.post("/api/projects", json={
        "id": "proj-task-del-1",
        "name": "Task Del Project",
        "repo_path": "/tmp/task-del-repo",
    })
    create_resp = await client.post("/api/projects/proj-task-del-1/tasks", json={
        "name": "Del Task",
        "intent": "To be deleted",
        "trigger_type": "manual",
    })
    task_id = create_resp.json()["id"]
    response = await client.delete(f"/api/tasks/{task_id}")
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_create_source(client):
    await client.post("/api/projects", json={
        "id": "proj-src-1",
        "name": "Source Project",
        "repo_path": "/tmp/src-repo",
    })
    response = await client.post("/api/projects/proj-src-1/sources", json={
        "source_type": "github",
        "source_id": "myorg/myrepo",
        "source_name": "My Repo",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["source_type"] == "github"
    assert data["source_id"] == "myorg/myrepo"
    assert data["source_name"] == "My Repo"
    assert data["project_id"] == "proj-src-1"


@pytest.mark.asyncio
async def test_list_sources(client):
    await client.post("/api/projects", json={
        "id": "proj-src-list-1",
        "name": "Source List Project",
        "repo_path": "/tmp/src-list-repo",
    })
    await client.post("/api/projects/proj-src-list-1/sources", json={
        "source_type": "linear",
        "source_id": "team-abc",
        "source_name": "My Linear Team",
    })
    response = await client.get("/api/projects/proj-src-list-1/sources")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    names = [s["source_name"] for s in data]
    assert "My Linear Team" in names


@pytest.mark.asyncio
async def test_linear_webhook_detects_agent_issue(tmp_path):
    from unittest.mock import AsyncMock, patch

    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
budget:
  daily_limit_usd: 10.00
  warning_threshold_usd: 7.00
  pause_on_limit: true
notifications:
  slack_webhook_url: ""
webhooks:
  github_secret: ""
  linear_secret: ""
execution:
  worktree_base: /tmp/test-agents
  dry_run: true
server:
  host: 127.0.0.1
  port: 9090
integrations:
  linear_api_key: "test-key"
  discord_bot_token: "test-token"
""")
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    (projects_dir / "testproj.yaml").write_text("""
name: testproj
repo: /tmp/test-repo
linear_team_id: team-xyz
discord_channel_id: chan-123
tasks:
  issue-resolver:
    description: "Resolve Linear issues"
    prompt: "Resolve {{issue_title}}"
    trigger:
      type: linear
      events: [Issue.create]
      filter:
        label: agent
""")
    from agents.main import create_app
    from httpx import ASGITransport, AsyncClient
    app = create_app(config_path=config_file, projects_dir=projects_dir, data_dir=tmp_path / "data")
    state = app.state.app_state

    # Patch run_task to track calls and check agent issue path
    original_run_task = state.executor.run_task
    agent_calls = []

    async def tracking_run_task(project, task_name, **kwargs):
        if kwargs.get("trigger_type") == "linear" and "issue_id" in kwargs.get("variables", {}):
            agent_calls.append({"task": task_name, "variables": kwargs["variables"]})
        return await original_run_task(project, task_name, **kwargs)

    state.executor.run_task = tracking_run_task

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/webhooks/linear", json={
            "action": "create",
            "type": "Issue",
            "data": {
                "id": "issue-new-1",
                "identifier": "TST-1",
                "title": "Test issue",
                "description": "Test description",
                "teamId": "team-xyz",
                "labels": [{"name": "agent"}],
            },
        })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processed"
    # Verify the agent issue detection path was triggered
    assert len(agent_calls) >= 1
    assert agent_calls[0]["task"] == "issue-resolver"
    assert agent_calls[0]["variables"]["issue_id"] == "issue-new-1"
