"""Integration tests for GitHub Issues → work-item creation in github_webhook."""

import hashlib
import hmac
import json

import pytest
from httpx import ASGITransport, AsyncClient

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
  worktree_base: /tmp/test-agents-gh-issues
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

ISSUE_PROJECT_YAML = """
name: issuerepo
repo: org/repo
tasks:
  issue-resolver:
    description: "Resolve GitHub issues"
    prompt: "Fix issue {{issue_number}}: {{issue_title}}"
"""


def _sig(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def app_with_issue_project(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(MINIMAL_CONFIG)
    proj_dir = tmp_path / "projects"
    proj_dir.mkdir()
    (proj_dir / "issuerepo.yaml").write_text(ISSUE_PROJECT_YAML)

    from agents.main import create_app

    return create_app(config_path=cfg, projects_dir=proj_dir, data_dir=tmp_path / "data")


@pytest.mark.asyncio
async def test_github_issue_opened_with_agent_label_creates_task(app_with_issue_project):
    """issues event with 'agent' label and matching repo creates a work item."""
    state = app_with_issue_project.state.app_state
    assert state.task_store is not None

    payload = {
        "action": "opened",
        "issue": {
            "number": 42,
            "title": "Add pagination",
            "body": "We need cursor-based pagination",
            "html_url": "https://github.com/org/repo/issues/42",
            "labels": [{"name": "agent"}],
        },
        "repository": {"full_name": "org/repo"},
    }
    body = json.dumps(payload).encode()
    sig = _sig(body, "gh-secret")

    transport = ASGITransport(app=app_with_issue_project)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "issues",
                "X-Hub-Signature-256": sig,
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "processed"}
    source_id = "github:org/repo#42"
    assert state.task_store.exists_by_source("github", source_id)


@pytest.mark.asyncio
async def test_github_issue_labeled_agent_creates_task(app_with_issue_project):
    """issues 'labeled' event where the added label is 'agent' creates a work item."""
    state = app_with_issue_project.state.app_state

    payload = {
        "action": "labeled",
        "label": {"name": "agent"},
        "issue": {
            "number": 7,
            "title": "Fix bug",
            "body": "It crashes",
            "html_url": "https://github.com/org/repo/issues/7",
            "labels": [{"name": "agent"}, {"name": "bug"}],
        },
        "repository": {"full_name": "org/repo"},
    }
    body = json.dumps(payload).encode()
    sig = _sig(body, "gh-secret")

    transport = ASGITransport(app=app_with_issue_project)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "issues",
                "X-Hub-Signature-256": sig,
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 200
    assert state.task_store.exists_by_source("github", "github:org/repo#7")


@pytest.mark.asyncio
async def test_github_issue_without_agent_label_no_task_created(app_with_issue_project):
    """issues event without the 'agent' label must NOT create a work item."""
    state = app_with_issue_project.state.app_state

    payload = {
        "action": "opened",
        "issue": {
            "number": 99,
            "title": "Regular issue",
            "body": "Nothing special",
            "html_url": "https://github.com/org/repo/issues/99",
            "labels": [{"name": "bug"}],
        },
        "repository": {"full_name": "org/repo"},
    }
    body = json.dumps(payload).encode()
    sig = _sig(body, "gh-secret")

    transport = ASGITransport(app=app_with_issue_project)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "issues",
                "X-Hub-Signature-256": sig,
                "Content-Type": "application/json",
            },
        )

    assert not state.task_store.exists_by_source("github", "github:org/repo#99")


@pytest.mark.asyncio
async def test_github_issue_dedup_does_not_create_duplicate(app_with_issue_project):
    """Sending the same issue event twice must only create one work item."""
    state = app_with_issue_project.state.app_state

    payload = {
        "action": "opened",
        "issue": {
            "number": 55,
            "title": "Dup issue",
            "body": "",
            "html_url": "https://github.com/org/repo/issues/55",
            "labels": [{"name": "agent"}],
        },
        "repository": {"full_name": "org/repo"},
    }
    body = json.dumps(payload).encode()
    sig = _sig(body, "gh-secret")
    headers = {
        "X-GitHub-Event": "issues",
        "X-Hub-Signature-256": sig,
        "Content-Type": "application/json",
    }

    transport = ASGITransport(app=app_with_issue_project)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/webhooks/github", content=body, headers=headers)
        await client.post("/webhooks/github", content=body, headers=headers)

    # Verify exactly one item with this source_id
    items = state.task_store.list_by_project("issuerepo")
    matching = [i for i in items if i.source_id == "github:org/repo#55"]
    assert len(matching) == 1
