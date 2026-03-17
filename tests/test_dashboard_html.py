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
