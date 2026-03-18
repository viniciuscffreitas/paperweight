"""Tests for Jinja2 composite macros (Phase 3)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

_TEMPLATES_DIR = Path(__file__).parent.parent / "src" / "agents" / "templates"


@pytest.fixture
def jinja_env():
    return Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=False)


# ---------------------------------------------------------------------------
# sidebar_item macro
# ---------------------------------------------------------------------------


def test_sidebar_item_renders_htmx_get(jinja_env):
    """sidebar_item must render hx-get pointing to /hub/<project_id>."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import sidebar_item %}"
        "{{ sidebar_item('My Project', 'proj-123') }}"
    )
    html = tmpl.render()
    assert 'hx-get="/hub/proj-123"' in html


def test_sidebar_item_renders_htmx_target(jinja_env):
    """sidebar_item must target #panel-content."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import sidebar_item %}"
        "{{ sidebar_item('My Project', 'proj-123') }}"
    )
    html = tmpl.render()
    assert 'hx-target="#panel-content"' in html


def test_sidebar_item_calls_open_panel(jinja_env):
    """sidebar_item must call openPanel() after HTMX request."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import sidebar_item %}"
        "{{ sidebar_item('My Project', 'proj-123') }}"
    )
    html = tmpl.render()
    assert "openPanel()" in html


def test_sidebar_item_renders_project_name(jinja_env):
    """sidebar_item must render the project name."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import sidebar_item %}"
        "{{ sidebar_item('Agent Runner', 'ar-1') }}"
    )
    html = tmpl.render()
    assert "Agent Runner" in html


def test_sidebar_item_uses_no_raw_hex(jinja_env):
    """sidebar_item must use only var(--token), no raw hex."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import sidebar_item %}"
        "{{ sidebar_item('My Project', 'p1') }}"
    )
    html = tmpl.render()
    raw_hex = re.findall(r'#[0-9a-fA-F]{3,6}\b', html)
    assert not raw_hex, f"sidebar_item has raw hex: {raw_hex}"


# ---------------------------------------------------------------------------
# panel_header macro
# ---------------------------------------------------------------------------


def test_panel_header_renders_44px_height(jinja_env):
    """panel_header must render with height:44px."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import panel_header %}"
        "{{ panel_header('My Project') }}"
    )
    html = tmpl.render()
    assert "height:44px" in html


def test_panel_header_renders_project_name(jinja_env):
    """panel_header must render the project name."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import panel_header %}"
        "{{ panel_header('Agent Runner') }}"
    )
    html = tmpl.render()
    assert "Agent Runner" in html


def test_panel_header_has_close_button(jinja_env):
    """panel_header must render a button that calls closePanel()."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import panel_header %}"
        "{{ panel_header('Test') }}"
    )
    html = tmpl.render()
    assert "closePanel()" in html


def test_panel_header_uses_no_raw_hex(jinja_env):
    """panel_header must use only var(--token), no raw hex."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import panel_header %}"
        "{{ panel_header('Test Project') }}"
    )
    html = tmpl.render()
    raw_hex = re.findall(r'#[0-9a-fA-F]{3,6}\b', html)
    assert not raw_hex, f"panel_header has raw hex: {raw_hex}"


# ---------------------------------------------------------------------------
# tab_bar macro
# ---------------------------------------------------------------------------


def test_tab_bar_activity_default_active(jinja_env):
    """tab_bar default active_tab='activity' must have data-active on ACTIVITY button."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import tab_bar %}"
        "{{ tab_bar('p1') }}"
    )
    html = tmpl.render()
    assert 'data-active="true"' in html
    # Active tab has accent border
    assert "var(--accent)" in html


def test_tab_bar_active_tab_has_text_primary(jinja_env):
    """Active tab button must use var(--text-primary) color."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import tab_bar %}"
        "{{ tab_bar('p1', active_tab='tasks') }}"
    )
    html = tmpl.render()
    assert "var(--text-primary)" in html


def test_tab_bar_inactive_tabs_transparent_border(jinja_env):
    """Inactive tabs must have border-bottom:2px solid transparent."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import tab_bar %}"
        "{{ tab_bar('p1') }}"
    )
    html = tmpl.render()
    assert html.count("border-bottom:2px solid transparent") >= 2


def test_tab_bar_all_buttons_have_activate_tab(jinja_env):
    """All 3 tab buttons must call activateTab(this)."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import tab_bar %}"
        "{{ tab_bar('p1') }}"
    )
    html = tmpl.render()
    assert html.count("activateTab(this)") == 3


def test_tab_bar_all_buttons_target_tab_content(jinja_env):
    """All 3 tab buttons must have hx-target='#tab-content'."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import tab_bar %}"
        "{{ tab_bar('p1') }}"
    )
    html = tmpl.render()
    assert html.count('hx-target="#tab-content"') == 3


def test_tab_bar_hx_get_uses_project_id(jinja_env):
    """tab_bar must generate hx-get with the given project_id."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import tab_bar %}"
        "{{ tab_bar('my-project-42') }}"
    )
    html = tmpl.render()
    assert 'hx-get="/hub/my-project-42/activity"' in html
    assert 'hx-get="/hub/my-project-42/tasks"' in html
    assert 'hx-get="/hub/my-project-42/runs"' in html


def test_tab_bar_data_active_aware_hover(jinja_env):
    """All tab buttons must check this.dataset.active in onmouseover/onmouseout."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import tab_bar %}"
        "{{ tab_bar('p1') }}"
    )
    html = tmpl.render()
    assert html.count("this.dataset.active") >= 4  # 2 handlers × 3 buttons


def test_tab_bar_renders_all_tab_labels(jinja_env):
    """tab_bar must render ACTIVITY, TASKS, and RUNS labels."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import tab_bar %}"
        "{{ tab_bar('p1') }}"
    )
    html = tmpl.render()
    assert "ACTIVITY" in html
    assert "TASKS" in html
    assert "RUNS" in html


def test_tab_bar_uses_no_raw_hex(jinja_env):
    """tab_bar must use only var(--token), no raw hex."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import tab_bar %}"
        "{{ tab_bar('p1') }}"
    )
    html = tmpl.render()
    raw_hex = re.findall(r'#[0-9a-fA-F]{3,6}\b', html)
    assert not raw_hex, f"tab_bar has raw hex: {raw_hex}"


# ---------------------------------------------------------------------------
# list_row macro (call block pattern)
# ---------------------------------------------------------------------------


def test_list_row_renders_content(jinja_env):
    """list_row must render its caller content."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import list_row %}"
        "{% call list_row() %}Hello row{% endcall %}"
    )
    html = tmpl.render()
    assert "Hello row" in html


def test_list_row_default_has_border(jinja_env):
    """list_row with default border=true must include border-bottom."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import list_row %}"
        "{% call list_row() %}content{% endcall %}"
    )
    html = tmpl.render()
    assert "border-bottom" in html
    assert "var(--border-subtle)" in html


def test_list_row_no_border_when_false(jinja_env):
    """list_row(border=false) must not include border-bottom."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import list_row %}"
        "{% call list_row(border=false) %}content{% endcall %}"
    )
    html = tmpl.render()
    assert "border-bottom" not in html


def test_list_row_uses_no_raw_hex(jinja_env):
    """list_row must use only var(--token), no raw hex."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import list_row %}"
        "{% call list_row() %}test{% endcall %}"
    )
    html = tmpl.render()
    raw_hex = re.findall(r'#[0-9a-fA-F]{3,6}\b', html)
    assert not raw_hex, f"list_row has raw hex: {raw_hex}"


# ---------------------------------------------------------------------------
# Integration: panel route uses composite macros (zero raw hex in panel)
# ---------------------------------------------------------------------------


def test_panel_template_zero_style_hex(jinja_env):
    """hub/panel.html rendered output must have no raw hex in style= attributes."""
    tmpl = jinja_env.get_template("hub/panel.html")
    html = tmpl.render(id="p1", project=type("P", (), {"name": "Test"})())
    # Extract all style attribute values
    style_values = re.findall(r'style="([^"]*)"', html)
    all_styles = " ".join(style_values)
    raw_hex = re.findall(r'#[0-9a-fA-F]{3,6}\b', all_styles)
    assert not raw_hex, f"panel.html style attrs have raw hex: {raw_hex}"
