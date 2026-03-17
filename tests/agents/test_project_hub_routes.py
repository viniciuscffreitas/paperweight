"""Tests for project_hub_routes — including /api/discover."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.project_hub_routes import register_project_hub_routes

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_state():
    state = MagicMock()
    state.project_store.list_projects.return_value = []
    state.project_store.get_project.return_value = {"id": "p1", "name": "Test"}
    state.project_store.create_project.return_value = None
    state.project_store.list_events.return_value = []
    state.project_store.list_sources.return_value = []
    state.project_store.list_tasks.return_value = []
    state.linear_client = None
    state.github_client = None
    state.slack_bot_client = None
    return state


def _make_test_app(state):
    app = FastAPI()
    register_project_hub_routes(app, state)
    return app


# ---------------------------------------------------------------------------
# /api/discover — basic shape
# ---------------------------------------------------------------------------


def test_discover_endpoint_returns_empty_list_without_clients():
    """POST /api/discover returns [] when no integration clients are configured."""
    state = _make_mock_state()
    app = _make_test_app(state)

    with patch("agents.dashboard_setup_wizard._discover_sources", new=AsyncMock(return_value=[])):
        client = TestClient(app)
        resp = client.post("/api/discover", json={"name": "myproject"})

    assert resp.status_code == 200
    assert resp.json() == []


def test_discover_endpoint_passes_name_to_discover_sources():
    """POST /api/discover forwards the 'name' field to _discover_sources."""
    state = _make_mock_state()
    app = _make_test_app(state)

    mock_discover = AsyncMock(return_value=[])
    with patch("agents.dashboard_setup_wizard._discover_sources", mock_discover):
        client = TestClient(app)
        client.post("/api/discover", json={"name": "coolproject"})

    mock_discover.assert_called_once_with("coolproject", state)


def test_discover_endpoint_uses_empty_string_when_name_missing():
    """POST /api/discover uses '' as the name when the field is absent."""
    state = _make_mock_state()
    app = _make_test_app(state)

    mock_discover = AsyncMock(return_value=[])
    with patch("agents.dashboard_setup_wizard._discover_sources", mock_discover):
        client = TestClient(app)
        client.post("/api/discover", json={})

    mock_discover.assert_called_once_with("", state)


def test_discover_endpoint_returns_sources_from_discover_sources():
    """POST /api/discover returns whatever _discover_sources yields."""
    state = _make_mock_state()
    app = _make_test_app(state)

    expected = [
        {
            "source_type": "linear", "source_id": "team-1",
            "source_name": "myproject", "confidence": "high",
        },
        {
            "source_type": "github", "source_id": "org/myproject",
            "source_name": "myproject", "confidence": "high",
        },
    ]
    mock_discover = AsyncMock(return_value=expected)
    with patch("agents.dashboard_setup_wizard._discover_sources", mock_discover):
        client = TestClient(app)
        resp = client.post("/api/discover", json={"name": "myproject"})

    assert resp.status_code == 200
    assert resp.json() == expected


def test_discover_endpoint_accepts_empty_body():
    """POST /api/discover works with an empty JSON body."""
    state = _make_mock_state()
    app = _make_test_app(state)

    mock_discover = AsyncMock(return_value=[])
    with patch("agents.dashboard_setup_wizard._discover_sources", mock_discover):
        client = TestClient(app)
        resp = client.post("/api/discover", json={})

    assert resp.status_code == 200
