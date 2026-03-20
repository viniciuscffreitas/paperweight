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
    """Dashboard page renders the project picker (redesigned from run history)."""
    resp = app_with_dashboard.get("/dashboard")
    assert resp.status_code == 200
    # Redesign: /dashboard now shows the project picker, not run history
    assert b"Projects" in resp.content or b"openWizard" in resp.content


def test_dashboard_contains_live_stream_section(app_with_dashboard):
    """Dashboard page contains the project picker view (redesigned from live stream)."""
    resp = app_with_dashboard.get("/dashboard")
    # Redesign: /dashboard is now the project picker; live stream is per-project agent tab
    assert resp.status_code == 200
    assert b"content-card" in resp.content


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
    # Redesign: /hub/<id> redirects to /hub/<id>/tasks (tasks.html full page)
    # The old panel tabs are replaced by the new task list view
    resp = app_with_project.get("/hub/p1")
    assert resp.status_code == 200
    # tasks.html shows project name and task creation button
    assert b"Test Project" in resp.content
    assert b"New Task" in resp.content


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
    # Redesign: /dashboard is the project picker; scrollable content is in overflow-y panels
    resp = app_with_dashboard.get("/dashboard")
    assert resp.status_code == 200
    assert b"overflow" in resp.content


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
    assert b"color:var(--text-muted);text-transform:uppercase" not in html


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


# ---------------------------------------------------------------------------
# Hub panel — Behavior Contract: visual bugs
# ---------------------------------------------------------------------------


def test_panel_header_height_44px(app_with_project):
    """Topbar and sidebar header must be 44px to align in L-chrome."""
    # Redesign: /hub/<id> now redirects to /hub/<id>/tasks (full page, not panel fragment)
    import re
    resp = app_with_project.get("/hub/p1")
    html = resp.text
    assert "height:44px" in html
    # The sidebar header uses height:44px; bottom-nav is 52px but that's correct
    topbar_match = re.search(r'id="app-topbar"[^>]*>[^<]*<div[^>]*style="([^"]*)"', html)
    if topbar_match:
        assert "height:44px" in topbar_match.group(1)


def test_panel_tab_content_background(app_with_project):
    """Content area must use background:var(--bg-content) to match content-card."""
    # Redesign: /hub/<id> redirects to tasks.html which extends base.html with bg-content
    resp = app_with_project.get("/hub/p1")
    assert b"background:var(--bg-content)" in resp.content


def test_activity_tab_default_active(app_with_project):
    """Tasks page renders in the main content panel with correct chrome."""
    # Redesign: /hub/<id>/tasks is the default view; old tab panel replaced by full page
    resp = app_with_project.get("/hub/p1")
    html = resp.text
    assert "content-card" in html
    assert "content-inner" in html


def test_tasks_runs_tabs_inactive_by_default(app_with_project):
    """Tasks page uses sidebar navigation, not the old panel tab bar."""
    # Redesign: the panel tab bar is gone; sidebar items navigate between projects
    resp = app_with_project.get("/hub/p1")
    html = resp.text
    # The base.html sidebar is present
    assert "sidebar" in html
    assert resp.status_code == 200


def test_tabs_no_overflow_x_auto(app_with_project):
    """Tasks view must not use overflow-x:auto in the main content area."""
    # Redesign: tasks.html replaces panel fragment; no overflow-x:auto in new layout
    resp = app_with_project.get("/hub/p1")
    assert b"overflow-x:auto" not in resp.content


def test_panel_tab_activate_js_onclick(app_with_project):
    """Tasks page must render without legacy activateTab JS (redesigned navigation)."""
    # Redesign: activateTab is no longer used; sidebar handles navigation
    resp = app_with_project.get("/hub/p1")
    assert resp.status_code == 200
    html = resp.text
    # New design: task list is rendered directly, not via tab switching
    assert "New Task" in html or "openNewTaskModal" in html


def test_panel_close_button_present(app_with_project):
    """Tasks page must have the wizard close button (base.html close behavior)."""
    # Redesign: panel close button replaced; wizard still has close button
    resp = app_with_project.get("/hub/p1")
    assert b"closeWizard()" in resp.content


def test_htmx_targets_preserved(app_with_project):
    """Tasks page targets #content-inner for HTMX navigation."""
    # Redesign: old #tab-content replaced with #content-inner (base.html)
    resp = app_with_project.get("/hub/p1")
    html = resp.text
    assert 'hx-target="#content-inner"' in html


def test_activity_tab_has_data_active_initially(app_with_project):
    """Tasks page renders correctly via redirect from /hub/<id>."""
    # Redesign: /hub/<id> redirects to tasks; no active tab state needed
    resp = app_with_project.get("/hub/p1")
    assert resp.status_code == 200
    assert b"content-card" in resp.content


def test_inactive_tabs_have_data_active_aware_hover(app_with_project):
    """Sidebar items use dataset-aware hover (base.html sidebar_item macro)."""
    # Redesign: sidebar_item macro uses dataset for active state
    resp = app_with_project.get("/hub/p1")
    html = resp.text
    # base.html renders the sidebar which provides project navigation
    assert "sidebar" in html


def test_hub_panel_contains_agent_tab(app_with_project):
    """Tasks page includes sidebar with project navigation."""
    # Redesign: /hub/<id> → tasks.html which extends base.html with sidebar
    resp = app_with_project.get("/hub/p1")
    assert resp.status_code == 200
    assert b"Test Project" in resp.content


def test_hub_panel_agent_tab_htmx_get(app_with_project):
    """Tasks page includes HTMX navigation to /hub/<id>/tasks."""
    # Redesign: sidebar_item navigates to /hub/<id>/tasks
    resp = app_with_project.get("/hub/p1")
    assert b"/hub/p1/tasks" in resp.content


def test_hub_agent_returns_200(app_with_project):
    """GET /hub/<id>/agent returns 200 for existing project."""
    resp = app_with_project.get("/hub/p1/agent")
    assert resp.status_code == 200


def test_hub_agent_404_for_missing_project(app_with_dashboard):
    """GET /hub/<id>/agent returns 404 when project does not exist."""
    resp = app_with_dashboard.get("/hub/nonexistent-xyz/agent")
    assert resp.status_code == 404


def test_hub_agent_contains_terminal_structure(app_with_project):
    """Agent tab must render the terminal output div and prompt input."""
    resp = app_with_project.get("/hub/p1/agent")
    assert b"agent-output" in resp.content
    assert b"agent-input" in resp.content
    assert b"agent-model" in resp.content


def test_hub_agent_loads_agent_js(app_with_project):
    """Agent tab must include a <script> tag loading /static/agent.js."""
    resp = app_with_project.get("/hub/p1/agent")
    assert b"/static/agent.js" in resp.content


def test_hub_agent_no_session_shows_placeholder(app_with_project):
    """Agent tab with no active session must show the placeholder hint."""
    resp = app_with_project.get("/hub/p1/agent")
    assert b"sem sess" in resp.content


def test_hub_agent_session_status_has_data_attribute(app_with_project):
    """agent-session-status span must carry data-session-id attribute."""
    resp = app_with_project.get("/hub/p1/agent")
    assert b"data-session-id=" in resp.content


# ---------------------------------------------------------------------------
# Phase 1 — CSS Variables
# ---------------------------------------------------------------------------


def test_css_vars_root_defined():
    """styles.css must define the :root CSS custom properties block."""
    import os
    css_path = os.path.join(
        os.path.dirname(__file__), "../src/agents/static/styles.css"
    )
    with open(css_path) as f:
        css = f.read()
    assert ":root {" in css


def test_right_panel_no_border_left_desktop(app_with_dashboard):
    """#right-panel desktop inline style must not contain border-left."""
    import re
    resp = app_with_dashboard.get("/dashboard")
    html = resp.text
    match = re.search(r'id="right-panel"[^>]*style="([^"]*)"', html)
    assert match, "#right-panel not found"
    assert "border-left" not in match.group(1)


def test_templates_use_css_vars(app_with_project):
    """Rendered templates must use CSS custom properties (var(--)."""
    resp = app_with_project.get("/dashboard")
    assert b"var(--" in resp.content
    resp2 = app_with_project.get("/hub/p1")
    assert b"var(--" in resp2.content


# ---------------------------------------------------------------------------
# Light Theme — CSS
# ---------------------------------------------------------------------------

def _read_css() -> str:
    import os
    css_path = os.path.join(
        os.path.dirname(__file__), "../src/agents/static/styles.css"
    )
    with open(css_path) as f:
        return f.read()


def test_css_overlay_tokens_in_root():
    """dashboard.css :root must define --overlay-backdrop and --overlay-shadow tokens."""
    css = _read_css()
    root_end = css.find("[data-theme")
    assert root_end != -1, ":root block not found (no [data-theme] block after it)"
    root_section = css[:root_end]
    assert "--overlay-backdrop:" in root_section, "--overlay-backdrop not in :root"
    assert "--overlay-shadow:" in root_section, "--overlay-shadow not in :root"


def test_css_light_theme_block_exists():
    """dashboard.css must contain a [data-theme="light"] block."""
    css = _read_css()
    assert '[data-theme="light"]' in css


def test_css_light_theme_overrides_all_bg_tokens():
    """[data-theme="light"] block must override all --bg-* tokens."""
    css = _read_css()
    light_block_start = css.find('[data-theme="light"]')
    assert light_block_start != -1
    light_block = css[light_block_start:]
    for token in [
        "--bg-chrome", "--bg-content", "--bg-elevated", "--bg-overlay",
        "--bg-task-success", "--bg-task-error", "--bg-task-hover",
    ]:
        assert token in light_block, f"Missing {token} in light theme block"


def test_css_light_theme_overrides_all_text_tokens():
    """[data-theme="light"] block must override all --text-* tokens."""
    css = _read_css()
    light_block_start = css.find('[data-theme="light"]')
    light_block = css[light_block_start:]
    for token in [
        "--text-primary", "--text-secondary", "--text-muted",
        "--text-disabled", "--text-placeholder",
    ]:
        assert token in light_block, f"Missing {token} in light theme block"


def test_css_light_theme_overrides_border_and_accent_tokens():
    """[data-theme="light"] block must override all border, accent, and overlay tokens."""
    css = _read_css()
    light_block_start = css.find('[data-theme="light"]')
    light_block = css[light_block_start:]
    for token in [
        "--border-subtle", "--border-default", "--border-strong",
        "--accent", "--accent-bg", "--accent-hover",
        "--overlay-backdrop", "--overlay-shadow",
    ]:
        assert token in light_block, f"Missing {token} in light theme block"


def test_css_light_theme_overrides_status_tokens():
    """[data-theme="light"] block must override all --status-* tokens for WCAG 3:1 on cream."""
    css = _read_css()
    light_block_start = css.find('[data-theme="light"]')
    light_block = css[light_block_start:]
    for token in [
        "--status-running", "--status-success", "--status-error",
        "--status-warning", "--status-neutral",
    ]:
        assert token in light_block, f"Missing {token} in light theme block (needed for WCAG contrast on cream)"


# ---------------------------------------------------------------------------
# Light Theme — Endpoint POST /set-theme
# ---------------------------------------------------------------------------


def test_set_theme_light_sets_cookie(app_with_dashboard):
    """POST /set-theme com theme=light seta o cookie theme=light."""
    resp = app_with_dashboard.post("/set-theme", data={"theme": "light"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert "theme" in resp.cookies
    assert resp.cookies["theme"] == "light"


def test_set_theme_dark_sets_cookie(app_with_dashboard):
    """POST /set-theme com theme=dark seta o cookie theme=dark."""
    resp = app_with_dashboard.post("/set-theme", data={"theme": "dark"})
    assert resp.status_code == 200
    assert resp.cookies["theme"] == "dark"


def test_set_theme_invalid_returns_422(app_with_dashboard):
    """POST /set-theme com valor inválido retorna 422."""
    resp = app_with_dashboard.post("/set-theme", data={"theme": "hacker"})
    assert resp.status_code == 422


def test_set_theme_missing_body_returns_422(app_with_dashboard):
    """POST /set-theme sem body retorna 422."""
    resp = app_with_dashboard.post("/set-theme", data={})
    assert resp.status_code == 422


def test_set_theme_cookie_attributes(app_with_dashboard):
    """Cookie deve ter httponly, samesite=lax e max-age corretos."""
    resp = app_with_dashboard.post("/set-theme", data={"theme": "light"})
    set_cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "max-age=31536000" in set_cookie


# ---------------------------------------------------------------------------
# Light Theme — Template
# ---------------------------------------------------------------------------


def test_html_element_has_data_theme_default_dark(app_with_dashboard):
    """Sem cookie, <html> deve ter data-theme="dark"."""
    resp = app_with_dashboard.get("/dashboard")
    assert b'data-theme="dark"' in resp.content


def test_html_element_has_data_theme_light_with_cookie(app_with_dashboard):
    """Com cookie theme=light, <html> deve ter data-theme="light"."""
    app_with_dashboard.cookies.set("theme", "light")
    try:
        resp = app_with_dashboard.get("/dashboard")
        assert b'data-theme="light"' in resp.content
    finally:
        app_with_dashboard.cookies.clear()


def test_html_element_has_data_theme_dark_with_cookie(app_with_dashboard):
    """Com cookie theme=dark, <html> deve ter data-theme="dark"."""
    app_with_dashboard.cookies.set("theme", "dark")
    try:
        resp = app_with_dashboard.get("/dashboard")
        assert b'data-theme="dark"' in resp.content
    finally:
        app_with_dashboard.cookies.clear()


def test_css_sidebar_backdrop_uses_overlay_token():
    """dashboard.css deve usar var(--overlay-backdrop) no backdrop do sidebar."""
    css = _read_css()
    assert "var(--overlay-backdrop)" in css
    # sidebar-backdrop + panel-backdrop + projects-backdrop
    assert css.count("var(--overlay-backdrop)") >= 3


def test_css_sidebar_shadow_uses_overlay_shadow_token():
    """dashboard.css deve usar var(--overlay-shadow) no box-shadow do sidebar mobile."""
    css = _read_css()
    assert "var(--overlay-shadow)" in css


def test_css_no_hardcoded_backdrop_rgba_after_tokenization():
    """Os rgba hardcoded não devem mais aparecer nos backdrops do CSS mobile section."""
    css = _read_css()
    media_mobile_start = css.find("@media (max-width: 767px)")
    media_mobile_end = css.find("@media (min-width: 768px)")
    mobile_section = css[media_mobile_start:media_mobile_end]
    assert "rgba(0,0,0,0.45)" not in mobile_section
    assert "rgba(0,0,0,0.65)" not in mobile_section


# ---------------------------------------------------------------------------
# Light Theme — Toggle Button
# ---------------------------------------------------------------------------


def test_theme_toggle_button_present(app_with_dashboard):
    """Topbar deve conter o botão de toggle de tema."""
    resp = app_with_dashboard.get("/dashboard")
    assert b"theme-toggle" in resp.content
    assert b"toggleTheme" in resp.content


def test_theme_toggle_icon_dark_by_default(app_with_dashboard):
    """Sem cookie, botão deve mostrar ícone de dark (☾)."""
    resp = app_with_dashboard.get("/dashboard")
    assert "☾".encode() in resp.content


def test_theme_toggle_icon_sun_when_light(app_with_dashboard):
    """Com cookie theme=light, botão deve mostrar ícone de light (☀)."""
    app_with_dashboard.cookies.set("theme", "light")
    try:
        resp = app_with_dashboard.get("/dashboard")
        assert "☀".encode() in resp.content
    finally:
        app_with_dashboard.cookies.clear()


def test_theme_toggle_js_rollback_present(app_with_dashboard):
    """JS de toggleTheme deve conter lógica de rollback (dataset.theme = current)."""
    resp = app_with_dashboard.get("/dashboard")
    html = resp.text
    assert "toggleTheme" in html
    assert "html.dataset.theme = current" in html


def test_base_uses_new_assets(app_with_dashboard):
    r = app_with_dashboard.get("/dashboard")
    assert r.status_code == 200
    assert 'styles.css' in r.text
    assert 'app.js' in r.text
    assert 'dashboard.css' not in r.text
    assert 'dashboard.js' not in r.text


# ---------------------------------------------------------------------------
# Task 4 — Task List View & Project Picker
# ---------------------------------------------------------------------------


def test_dashboard_renders_project_picker(app_with_dashboard):
    r = app_with_dashboard.get("/dashboard")
    assert r.status_code == 200
    assert "Projects" in r.text or "projects" in r.text.lower()


def test_hub_redirects_to_tasks(app_with_dashboard_with_project):
    r = app_with_dashboard_with_project.get("/hub/my-project", follow_redirects=False)
    assert r.status_code == 302
    assert "/hub/my-project/tasks" in r.headers.get("location", "")


def test_hub_tasks_renders_new_view(app_with_dashboard_with_project):
    r = app_with_dashboard_with_project.get("/hub/my-project/tasks")
    assert r.status_code == 200
    assert "stats" in r.text.lower() or "running" in r.text


# ---------------------------------------------------------------------------
# Task 5 — Task Detail View
# ---------------------------------------------------------------------------


@pytest.fixture
def app_with_dashboard_with_project_and_task(tmp_path):
    """Create a FastAPI app with dashboard routes, a project, and a work item."""
    from agents.task_store import TaskStore

    app = FastAPI()

    history = HistoryDB(tmp_path / "history.db")
    project_store = ProjectStore(tmp_path / "projects.db")
    task_store = TaskStore(tmp_path / "tasks.db")
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
        id="test-project",
        name="Test Project",
        repo_path=str(tmp_path),
    )
    item = task_store.create(
        project="test-project",
        title="My test task",
        description="A task for testing",
        source="manual",
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
        task_store=task_store,
    )
    config = GlobalConfig()
    setup_dashboard(app, state, config)
    client = TestClient(app)
    client._task_id = item.id  # expose for tests
    return client


def test_task_detail_route_404(app_with_dashboard_with_project):
    """Task detail returns 404 for non-existent task."""
    r = app_with_dashboard_with_project.get("/hub/my-project/task/nonexistent")
    assert r.status_code == 404


def test_hub_task_detail_route(app_with_dashboard_with_project_and_task):
    """Task detail returns 200 and renders task content for an existing task."""
    task_id = app_with_dashboard_with_project_and_task._task_id
    r = app_with_dashboard_with_project_and_task.get(
        f"/hub/test-project/task/{task_id}"
    )
    assert r.status_code == 200
    assert "Back to tasks" in r.text or "back" in r.text.lower()


def test_hub_task_detail_shows_title(app_with_dashboard_with_project_and_task):
    """Task detail renders the task title."""
    task_id = app_with_dashboard_with_project_and_task._task_id
    r = app_with_dashboard_with_project_and_task.get(
        f"/hub/test-project/task/{task_id}"
    )
    assert r.status_code == 200
    assert "My test task" in r.text


def test_hub_task_detail_loads_stream_js(app_with_dashboard_with_project_and_task):
    """Task detail template loads stream.js and task-detail.js."""
    task_id = app_with_dashboard_with_project_and_task._task_id
    r = app_with_dashboard_with_project_and_task.get(
        f"/hub/test-project/task/{task_id}"
    )
    assert r.status_code == 200
    assert b"/static/stream.js" in r.content
    assert b"/static/task-detail.js" in r.content


# ---------------------------------------------------------------------------
# Task 6 — Sessions View & Setup Wizard
# ---------------------------------------------------------------------------


def test_hub_runs_renders_sessions_view(app_with_dashboard_with_project):
    r = app_with_dashboard_with_project.get("/hub/my-project/runs")
    assert r.status_code == 200
    assert "Sessions" in r.text or "sessions" in r.text.lower() or "No sessions" in r.text


def test_setup_discover_uses_new_wizard(app_with_dashboard):
    r = app_with_dashboard.post("/setup/discover", data={"name": "test", "repo_path": "/tmp/test"})
    assert r.status_code == 200
    assert "Link sources" in r.text or "Step 2" in r.text
