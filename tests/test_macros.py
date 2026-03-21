"""Tests for Jinja2 macro primitives — bold-minimal design system."""

from __future__ import annotations

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

_TEMPLATES_DIR = Path(__file__).parent.parent / "src" / "agents" / "templates"
_MACROS_PATH = _TEMPLATES_DIR / "components" / "macros.html"
_STATIC_DIR = Path(__file__).parent.parent / "src" / "agents" / "static"


def test_styles_css_exists():
    assert (_STATIC_DIR / "styles.css").exists()


def test_styles_has_design_tokens():
    css = (_STATIC_DIR / "styles.css").read_text()
    for token in [
        "--bg-chrome",
        "--bg-content",
        "--text-primary",
        "--text-secondary",
        "--status-running",
        "--accent-text",
        "--card-radius",
    ]:
        assert token in css, f"Missing token: {token}"


@pytest.fixture
def jinja_env():
    return Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=False)


# ---------------------------------------------------------------------------
# File existence
# ---------------------------------------------------------------------------


def test_macros_file_exists():
    """components/macros.html must exist for Jinja2 import to work."""
    assert _MACROS_PATH.exists(), f"Missing: {_MACROS_PATH}"


# ---------------------------------------------------------------------------
# btn macro
# ---------------------------------------------------------------------------


def test_btn_primary_has_gradient(jinja_env):
    tmpl = jinja_env.from_string('{% from "components/macros.html" import btn %}{{ btn("Save") }}')
    html = tmpl.render()
    assert "gradient" in html.lower() or "accent-gradient" in html


def test_btn_ghost_transparent(jinja_env):
    tmpl = jinja_env.from_string(
        '{% from "components/macros.html" import btn %}{{ btn("Cancel", variant="ghost") }}'
    )
    html = tmpl.render()
    assert "transparent" in html


def test_btn_danger_has_error_color(jinja_env):
    tmpl = jinja_env.from_string(
        '{% from "components/macros.html" import btn %}{{ btn("Delete", variant="danger") }}'
    )
    html = tmpl.render()
    assert "status-error" in html


def test_status_dot_running_class(jinja_env):
    tmpl = jinja_env.from_string(
        '{% from "components/macros.html" import status_dot %}{{ status_dot("running") }}'
    )
    html = tmpl.render()
    assert "running" in html
    assert 'aria-hidden="true"' in html


def test_badge_renders_pill(jinja_env):
    tmpl = jinja_env.from_string(
        '{% from "components/macros.html" import badge %}{{ badge("LIN-342") }}'
    )
    html = tmpl.render()
    assert "LIN-342" in html
    assert "border-radius" in html


def test_input_field_has_focus(jinja_env):
    tmpl = jinja_env.from_string(
        '{% from "components/macros.html" import input_field %}'
        '{{ input_field("email", label="Email") }}'
    )
    html = tmpl.render()
    assert "Email" in html
    assert "accent-focus" in html or "onfocus" in html


def test_section_label_uppercase(jinja_env):
    tmpl = jinja_env.from_string(
        '{% from "components/macros.html" import section_label %}{{ section_label("Projects") }}'
    )
    html = tmpl.render()
    assert "uppercase" in html
    assert "Projects" in html


def test_back_link_renders(jinja_env):
    tmpl = jinja_env.from_string(
        '{% from "components/macros.html" import back_link %}{{ back_link("tasks") }}'
    )
    html = tmpl.render()
    assert "←" in html or "&larr;" in html
    assert "tasks" in html
