"""Tests for HTMX dashboard HTML routes."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.app_state import AppState
from agents.budget import BudgetManager
from agents.config import BudgetConfig, ExecutionConfig, GlobalConfig
from agents.dashboard_html import setup_dashboard
from agents.executor import Executor
from agents.history import HistoryDB
from agents.notifier import Notifier
from agents.project_store import ProjectStore


@pytest.fixture
def app_with_dashboard(tmp_path):
    """Create a minimal FastAPI app with dashboard routes mounted."""
    app = FastAPI()

    history = HistoryDB(tmp_path / "history.db")
    project_store = ProjectStore(tmp_path / "projects.db")
    budget_config = BudgetConfig()
    budget = BudgetManager(config=budget_config, history=history)
    notifier = Notifier(webhook_url="")
    exec_config = ExecutionConfig()
    executor = Executor(
        config=exec_config,
        budget=budget,
        history=history,
        notifier=notifier,
        data_dir=tmp_path,
    )

    state = AppState(
        projects={},
        executor=executor,
        history=history,
        budget=budget,
        notifier=notifier,
        github_secret="",
        linear_secret="",
        project_store=project_store,
    )
    config = GlobalConfig()
    setup_dashboard(app, state, config)
    return TestClient(app)


@pytest.fixture
def app_with_dashboard_with_project(tmp_path):
    """Create a minimal FastAPI app with dashboard routes and a project."""
    app = FastAPI()

    history = HistoryDB(tmp_path / "history.db")
    project_store = ProjectStore(tmp_path / "projects.db")
    budget_config = BudgetConfig()
    budget = BudgetManager(config=budget_config, history=history)
    notifier = Notifier(webhook_url="")
    exec_config = ExecutionConfig()
    executor = Executor(
        config=exec_config,
        budget=budget,
        history=history,
        notifier=notifier,
        data_dir=tmp_path,
    )

    project_store.create_project(
        id="my-project",
        name="My Project",
        repo_path=str(tmp_path),
    )

    state = AppState(
        projects={},
        executor=executor,
        history=history,
        budget=budget,
        notifier=notifier,
        github_secret="",
        linear_secret="",
        project_store=project_store,
    )
    config = GlobalConfig()
    setup_dashboard(app, state, config)
    return TestClient(app)


def test_dashboard_returns_200(app_with_dashboard):
    resp = app_with_dashboard.get("/dashboard")
    assert resp.status_code == 200


def test_dashboard_contains_sidebar(app_with_dashboard):
    resp = app_with_dashboard.get("/dashboard")
    assert b"paperweight" in resp.content


def test_dashboard_contains_run_table(app_with_dashboard):
    """Dashboard page renders the run history table structure."""
    resp = app_with_dashboard.get("/dashboard")
    assert resp.status_code == 200
    assert b"run-history" in resp.content


def test_dashboard_contains_live_stream_section(app_with_dashboard):
    """Dashboard page contains the live stream pre element."""
    resp = app_with_dashboard.get("/dashboard")
    assert b"live-stream-output" in resp.content


def test_dashboard_with_project_names_in_sidebar(app_with_dashboard_with_project):
    """Dashboard sidebar lists projects when they exist."""
    resp = app_with_dashboard_with_project.get("/dashboard")
    assert b"My Project" in resp.content


@pytest.fixture
def app_with_project(tmp_path):
    """Create a minimal FastAPI app with dashboard routes and a project (id=p1)."""
    app = FastAPI()

    history = HistoryDB(tmp_path / "history.db")
    project_store = ProjectStore(tmp_path / "projects.db")
    budget_config = BudgetConfig()
    budget = BudgetManager(config=budget_config, history=history)
    notifier = Notifier(webhook_url="")
    exec_config = ExecutionConfig()
    executor = Executor(
        config=exec_config,
        budget=budget,
        history=history,
        notifier=notifier,
        data_dir=tmp_path,
    )

    project_store.create_project(id="p1", name="Test Project", repo_path=str(tmp_path))

    state = AppState(
        projects={},
        executor=executor,
        history=history,
        budget=budget,
        notifier=notifier,
        github_secret="",
        linear_secret="",
        project_store=project_store,
    )
    config = GlobalConfig()
    setup_dashboard(app, state, config)
    return TestClient(app)


def test_hub_panel_404_for_missing_project(app_with_dashboard):
    resp = app_with_dashboard.get("/hub/nonexistent-id-xyz")
    assert resp.status_code == 404


def test_hub_panel_contains_project_name(app_with_project):
    resp = app_with_project.get("/hub/p1")
    assert resp.status_code == 200
    assert b"Test Project" in resp.content


def test_hub_panel_contains_tabs(app_with_project):
    resp = app_with_project.get("/hub/p1")
    assert resp.status_code == 200
    assert b"ACTIVITY" in resp.content
    assert b"TASKS" in resp.content
    assert b"RUNS" in resp.content


def test_hub_activity_returns_200(app_with_project):
    resp = app_with_project.get("/hub/p1/activity")
    assert resp.status_code == 200


def test_hub_tasks_returns_200(app_with_project):
    resp = app_with_project.get("/hub/p1/tasks")
    assert resp.status_code == 200


def test_hub_runs_returns_200(app_with_project):
    resp = app_with_project.get("/hub/p1/runs")
    assert resp.status_code == 200


def test_main_imports_dashboard_html_not_nicegui():
    """main.py must import from dashboard_html, not from dashboard (NiceGUI)."""
    import inspect
    from agents import main
    source = inspect.getsource(main)
    assert "from agents.dashboard_html import setup_dashboard" in source
    assert "from agents.dashboard import setup_dashboard" not in source
