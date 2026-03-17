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


def test_root_redirects_to_dashboard(app_with_dashboard):
    resp = app_with_dashboard.get("/", follow_redirects=False)
    assert resp.status_code in (301, 302, 307, 308)
    assert resp.headers["location"] == "/dashboard"


def test_dashboard_has_mobile_hamburger(app_with_dashboard):
    resp = app_with_dashboard.get("/dashboard")
    assert b"toggleSidebar" in resp.content


def test_dashboard_table_has_overflow_scroll(app_with_dashboard):
    resp = app_with_dashboard.get("/dashboard")
    assert b"overflow-x" in resp.content


def test_dashboard_has_skip_link(app_with_dashboard):
    resp = app_with_dashboard.get("/dashboard")
    assert b"main-content" in resp.content


def test_dashboard_has_bottom_nav(app_with_dashboard):
    resp = app_with_dashboard.get("/dashboard")
    assert b"bottom-nav" in resp.content


def test_dashboard_hamburger_has_aria_label(app_with_dashboard):
    resp = app_with_dashboard.get("/dashboard")
    assert b"Abrir menu" in resp.content


def test_dashboard_has_drag_handle(app_with_dashboard):
    # sheet-handle lives in base.html (panel shell), not in the hub fragment
    resp = app_with_dashboard.get("/dashboard")
    assert b"sheet-handle" in resp.content


def test_dashboard_has_projects_sheet(app_with_dashboard):
    resp = app_with_dashboard.get("/dashboard")
    assert b"projects-sheet" in resp.content


def test_dashboard_projects_nav_calls_open_projects_sheet(app_with_dashboard):
    resp = app_with_dashboard.get("/dashboard")
    assert b"openProjectsSheet" in resp.content


def test_dashboard_has_content_card(app_with_dashboard):
    resp = app_with_dashboard.get("/dashboard")
    assert b"content-card" in resp.content


def test_dashboard_topbar_slot_present(app_with_dashboard):
    """Topbar block rendered inside main, separate from content card."""
    resp = app_with_dashboard.get("/dashboard")
    assert b"app-topbar" in resp.content


def test_dashboard_main_element_has_id_for_skip_link(app_with_dashboard):
    """The skip-link target id='main-content' must be on the <main> element."""
    resp = app_with_dashboard.get("/dashboard")
    assert b'id="main-content"' in resp.content


def test_main_imports_dashboard_html_not_nicegui():
    """main.py must import from dashboard_html, not from dashboard (NiceGUI)."""
    import inspect
    from agents import main
    source = inspect.getsource(main)
    assert "from agents.dashboard_html import setup_dashboard" in source
    assert "from agents.dashboard import setup_dashboard" not in source


def test_dashboard_chrome_no_redundant_border(app_with_dashboard):
    """content-card must NOT have border-top/border-left/margin-top that duplicate
    the sidebar border-right and topbar border-bottom."""
    resp = app_with_dashboard.get("/dashboard")
    html = resp.text
    # These styles on #content-card cause double-border artifacts in the L-chrome
    assert "margin-top:-1px" not in html
    # content-card must not carry its own border (sidebar/topbar already define the L frame)
    import re
    content_card_match = re.search(r'id="content-card"[^>]*style="([^"]*)"', html)
    assert content_card_match, "content-card element not found"
    card_style = content_card_match.group(1)
    assert "border-top" not in card_style, "content-card must not have border-top"
    assert "border-left" not in card_style, "content-card must not have border-left"


def test_dashboard_chrome_label_contrast(app_with_dashboard):
    """Chrome labels ('paperweight', 'Projects') must use #9ca3af (WCAG AA) not #6b7280."""
    resp = app_with_dashboard.get("/dashboard")
    html = resp.content
    # #6b7280 on #0d0f18 fails WCAG AA for small text; #9ca3af passes
    assert b"color:#6b7280;text-transform:uppercase" not in html


# ---------------------------------------------------------------------------
# Chrome L — borderless floating card
# ---------------------------------------------------------------------------


def test_dashboard_chrome_sidebar_no_right_border(app_with_dashboard):
    """Sidebar must not have border-right — separation via color contrast only."""
    import re
    resp = app_with_dashboard.get("/dashboard")
    html = resp.text
    match = re.search(r'id="sidebar"[^>]*style="([^"]*)"', html)
    assert match, "#sidebar not found"
    assert "border-right" not in match.group(1)


def test_dashboard_chrome_topbar_no_bottom_border(app_with_dashboard):
    """#app-topbar must not have border-bottom — floating card effect."""
    import re
    resp = app_with_dashboard.get("/dashboard")
    html = resp.text
    match = re.search(r'id="app-topbar"[^>]*style="([^"]*)"', html)
    assert match, "#app-topbar not found"
    assert "border-bottom" not in match.group(1)


# ---------------------------------------------------------------------------
# Chrome L — height alignment
# ---------------------------------------------------------------------------


def test_dashboard_chrome_l_sidebar_header_no_internal_border(app_with_dashboard):
    """Sidebar header must not have its own border-bottom (causes misaligned L)."""
    import re
    resp = app_with_dashboard.get("/dashboard")
    html = resp.text
    match = re.search(r'<div[^>]*style="([^"]*)"[^>]*>\s*<span[^>]*>paperweight', html)
    assert match, "Sidebar header div not found"
    assert "border-bottom" not in match.group(1), (
        "Sidebar header border-bottom creates a second horizontal line that breaks the L"
    )


def test_dashboard_chrome_l_sidebar_header_height(app_with_dashboard):
    """Sidebar header must declare height:44px to align with topbar."""
    import re
    resp = app_with_dashboard.get("/dashboard")
    html = resp.text
    match = re.search(r'<div[^>]*style="([^"]*)"[^>]*>\s*<span[^>]*>paperweight', html)
    assert match, "Sidebar header div not found"
    assert "height:44px" in match.group(1)


def test_dashboard_chrome_l_topbar_height(app_with_dashboard):
    """Topbar content must be 44px tall to match sidebar header."""
    import re
    resp = app_with_dashboard.get("/dashboard")
    html = resp.text
    topbar_region = re.search(
        r'id="app-topbar"[^>]*>(.*?)</div>\s*<!--', html, re.DOTALL
    )
    assert topbar_region, "#app-topbar region not found"
    assert "height:44px" in topbar_region.group(1)


# ---------------------------------------------------------------------------
# Setup wizard
# ---------------------------------------------------------------------------


def test_dashboard_empty_state_has_add_project_cta(app_with_dashboard):
    """When no projects exist, sidebar shows an 'add project' call-to-action."""
    resp = app_with_dashboard.get("/dashboard")
    assert b"add project" in resp.content


def test_setup_discover_returns_200(app_with_dashboard):
    """POST /setup/discover returns HTTP 200."""
    resp = app_with_dashboard.post(
        "/setup/discover", data={"name": "myproject", "repo_path": "/tmp/repo"}
    )
    assert resp.status_code == 200


def test_setup_discover_returns_html(app_with_dashboard):
    """POST /setup/discover returns text/html content-type."""
    resp = app_with_dashboard.post(
        "/setup/discover", data={"name": "myproject", "repo_path": "/tmp/repo"}
    )
    assert "text/html" in resp.headers["content-type"]


def test_setup_create_returns_hx_redirect(app_with_dashboard):
    """POST /setup/create returns HX-Redirect header pointing to /dashboard."""
    resp = app_with_dashboard.post(
        "/setup/create", data={"name": "My New Project", "repo_path": "/tmp/my-project"}
    )
    assert resp.headers.get("hx-redirect") == "/dashboard"
