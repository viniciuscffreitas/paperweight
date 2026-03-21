
import pytest


@pytest.fixture
def test_app(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"""
budget:
  daily_limit_usd: 10.0
  warning_threshold_usd: 7.0
  pause_on_limit: true
notifications:
  slack_webhook_url: ""
webhooks:
  github_secret: ""
  linear_secret: ""
execution:
  worktree_base: "{tmp_path / 'worktrees'}"
  dry_run: true
  timeout_minutes: 1
  max_concurrent: 3
  default_model: sonnet
  default_max_cost_usd: 5.0
  default_autonomy: pr-only
server:
  host: 127.0.0.1
  port: 8080
coordination:
  enabled: false
integrations:
  linear_api_key: ""
  discord_bot_token: ""
  discord_guild_id: ""
  github_token: ""
  slack_bot_token: ""
""")
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    proj_yaml = projects_dir / "testproj.yaml"
    proj_yaml.write_text("""
name: testproj
repo: /tmp/fake-repo
base_branch: main
branch_prefix: agents/
tasks:
  hello:
    description: test task
    intent: do a test
    model: sonnet
    max_cost_usd: 1.0
""")
    from agents.main import create_app
    app = create_app(config_path=config_path, projects_dir=projects_dir, data_dir=tmp_path / "data")
    return app


@pytest.mark.asyncio
async def test_agent_endpoint_new_session(test_app):
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post("/api/projects/testproj/agent", json={
            "prompt": "test prompt",
            "model": "sonnet",
            "max_cost_usd": 1.0,
        })
    assert resp.status_code == 202
    data = resp.json()
    assert "run_id" in data
    assert "session_id" in data
    assert data["status"] == "running"


@pytest.mark.asyncio
async def test_agent_endpoint_project_not_found(test_app):
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post("/api/projects/nonexistent/agent", json={"prompt": "test"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_agent_endpoint_empty_prompt(test_app):
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post("/api/projects/testproj/agent", json={"prompt": ""})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_close_session_endpoint(test_app):
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # Create a session first via the agent endpoint
        resp = await client.post("/api/projects/testproj/agent", json={
            "prompt": "test prompt",
        })
        assert resp.status_code == 202
        session_id = resp.json()["session_id"]

        # Close the session
        close_resp = await client.post(f"/api/sessions/{session_id}/close")
    assert close_resp.status_code == 200
    assert close_resp.json()["status"] == "closed"


@pytest.mark.asyncio
async def test_close_session_not_found(test_app):
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post("/api/sessions/nonexistent-session/close")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_agent_endpoint_duplicate_run(test_app):
    """Concurrent run on same session returns 409 when lock is already held."""
    from httpx import ASGITransport, AsyncClient

    # Grab the session_manager from app state and pre-acquire a lock to simulate
    # an in-progress run, then verify the endpoint rejects a second request.
    state = test_app.state.app_state
    session = state.session_manager.create_session("testproj")
    assert state.session_manager.try_acquire_run(session.id)  # lock held

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post("/api/projects/testproj/agent", json={
            "prompt": "second prompt",
            "session_id": session.id,
        })
    assert resp.status_code == 409

    state.session_manager.release_run(session.id)  # cleanup
