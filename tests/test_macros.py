"""Tests for Jinja2 macro primitives (Phase 2)."""
from __future__ import annotations

import os
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
    for token in ["--bg-chrome", "--bg-content", "--text-primary", "--text-secondary",
                   "--status-running", "--accent-text", "--card-radius"]:
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


def test_btn_primary_renders_accent_bg(jinja_env):
    """btn(variant='primary') must render with var(--accent-bg) background."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import btn %}"
        "{{ btn('Save') }}"
    )
    html = tmpl.render()
    assert "var(--accent-bg)" in html
    assert "var(--accent)" in html
    assert "Save" in html


def test_btn_ghost_renders_subtle_border(jinja_env):
    """btn(variant='ghost') must render with var(--border-subtle) border."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import btn %}"
        "{{ btn('Cancel', variant='ghost') }}"
    )
    html = tmpl.render()
    assert "var(--border-subtle)" in html
    assert "Cancel" in html


def test_btn_dashed_renders_dashed_border(jinja_env):
    """btn(variant='dashed') must render with border:1px dashed."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import btn %}"
        "{{ btn('+ add project', variant='dashed') }}"
    )
    html = tmpl.render()
    assert "dashed" in html
    assert "var(--border-default)" in html


def test_btn_uses_no_raw_hex(jinja_env):
    """All btn variants must use only var(--token), no raw hex colors."""
    import re
    for variant in ("primary", "ghost", "danger", "dashed"):
        tmpl = jinja_env.from_string(
            "{% from 'components/macros.html' import btn %}"
            f"{{% set v = '{variant}' %}}"
            "{{ btn('Label', variant=v) }}"
        )
        html = tmpl.render()
        raw_hex = re.findall(r'#[0-9a-fA-F]{3,6}\b', html)
        assert not raw_hex, f"btn({variant}) has raw hex: {raw_hex}"


def test_btn_type_attribute_respected(jinja_env):
    """btn(type='submit') must render <button type=\"submit\">."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import btn %}"
        "{{ btn('Go', type='submit') }}"
    )
    html = tmpl.render()
    assert 'type="submit"' in html


def test_btn_onclick_rendered(jinja_env):
    """btn(onclick='doSomething()') must render the onclick attribute."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import btn %}"
        "{{ btn('Click', onclick='doSomething()') }}"
    )
    html = tmpl.render()
    assert "doSomething()" in html


# ---------------------------------------------------------------------------
# input_field macro
# ---------------------------------------------------------------------------


def test_input_field_renders_input_element(jinja_env):
    """input_field must render an <input> element with the given name."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import input_field %}"
        "{{ input_field('repo_path', placeholder='/path/to/repo') }}"
    )
    html = tmpl.render()
    assert '<input' in html
    assert 'name="repo_path"' in html
    assert '/path/to/repo' in html


def test_input_field_renders_label(jinja_env):
    """input_field with label param must render a <label> element."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import input_field %}"
        "{{ input_field('name', label='Project name') }}"
    )
    html = tmpl.render()
    assert '<label' in html
    assert 'Project name' in html


def test_input_field_has_focus_handler(jinja_env):
    """input_field must render onfocus/onblur border-color handlers."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import input_field %}"
        "{{ input_field('x') }}"
    )
    html = tmpl.render()
    assert "onfocus" in html
    assert "onblur" in html
    assert "var(--accent)" in html


def test_input_field_required_attribute(jinja_env):
    """input_field(required=true) must render the required attribute."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import input_field %}"
        "{{ input_field('name', required=true) }}"
    )
    html = tmpl.render()
    assert "required" in html


def test_input_field_uses_no_raw_hex(jinja_env):
    """input_field must use only var(--token), no raw hex colors."""
    import re
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import input_field %}"
        "{{ input_field('test', label='Test', placeholder='ph') }}"
    )
    html = tmpl.render()
    raw_hex = re.findall(r'#[0-9a-fA-F]{3,6}\b', html)
    assert not raw_hex, f"input_field has raw hex: {raw_hex}"


# ---------------------------------------------------------------------------
# status_dot macro
# ---------------------------------------------------------------------------


def test_status_dot_renders_css_class(jinja_env):
    """status_dot must render a span with class 'status-dot <status>'."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import status_dot %}"
        "{{ status_dot('running') }}"
    )
    html = tmpl.render()
    assert 'class="status-dot running"' in html


def test_status_dot_is_aria_hidden(jinja_env):
    """status_dot must be aria-hidden for accessibility."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import status_dot %}"
        "{{ status_dot('success') }}"
    )
    html = tmpl.render()
    assert 'aria-hidden="true"' in html


# ---------------------------------------------------------------------------
# section_label macro
# ---------------------------------------------------------------------------


def test_section_label_renders_uppercase(jinja_env):
    """section_label must render with text-transform:uppercase."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import section_label %}"
        "{{ section_label('Projects') }}"
    )
    html = tmpl.render()
    assert "uppercase" in html
    assert "Projects" in html


def test_section_label_uses_text_secondary(jinja_env):
    """section_label must use var(--text-secondary) color."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import section_label %}"
        "{{ section_label('Live Stream') }}"
    )
    html = tmpl.render()
    assert "var(--text-secondary)" in html


# ---------------------------------------------------------------------------
# divider macro
# ---------------------------------------------------------------------------


def test_divider_renders_border_subtle(jinja_env):
    """divider must render an element using var(--border-subtle)."""
    tmpl = jinja_env.from_string(
        "{% from 'components/macros.html' import divider %}"
        "{{ divider() }}"
    )
    html = tmpl.render()
    assert "var(--border-subtle)" in html
