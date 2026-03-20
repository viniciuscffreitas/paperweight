"""Tests for composite Jinja2 macros."""
from __future__ import annotations

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

_TEMPLATES_DIR = Path(__file__).parent.parent / "src" / "agents" / "templates"

@pytest.fixture
def jinja_env():
    return Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=False)

def test_task_card_renders_title(jinja_env):
    tmpl = jinja_env.from_string('''
    {% from "components/macros.html" import task_card %}
    {{ task_card(item, project_id="proj1") }}
    ''')
    item = type('Item', (), {'id': '1', 'title': 'Fix auth bug', 'status': 'running', 'source': 'linear', 'source_id': 'LIN-1', 'source_url': '', 'pr_url': '', 'session_id': '', 'created_at': '', 'updated_at': ''})()
    html = tmpl.render(item=item)
    assert "Fix auth bug" in html
    assert "17px" in html or "task-title" in html

def test_task_card_running_has_glow(jinja_env):
    tmpl = jinja_env.from_string('{% from "components/macros.html" import task_card %}{{ task_card(item, project_id="p") }}')
    item = type('Item', (), {'id': '1', 'title': 'T', 'status': 'running', 'source': '', 'source_id': '', 'source_url': '', 'pr_url': '', 'session_id': '', 'created_at': '', 'updated_at': ''})()
    html = tmpl.render(item=item)
    assert "running" in html
    assert "pulse" in html or "glow" in html.lower() or "status-dot" in html

def test_task_card_done_has_opacity(jinja_env):
    tmpl = jinja_env.from_string('{% from "components/macros.html" import task_card_done %}{{ task_card_done(item, project_id="p") }}')
    item = type('Item', (), {'id': '1', 'title': 'Done task', 'status': 'done', 'source': '', 'source_id': '', 'source_url': '', 'pr_url': '', 'session_id': '', 'created_at': '', 'updated_at': ''})()
    html = tmpl.render(item=item)
    assert "0.35" in html

def test_stats_line_renders_counters(jinja_env):
    tmpl = jinja_env.from_string('{% from "components/macros.html" import stats_line %}{{ stats_line(counts, 2.30, 10) }}')
    html = tmpl.render(counts={'running': 3, 'review': 1, 'queued': 2, 'done': 8})
    assert "3" in html
    assert "running" in html
    assert "2.30" in html or "$2.30" in html

def test_tab_bar_renders_tabs(jinja_env):
    tmpl = jinja_env.from_string('{% from "components/macros.html" import tab_bar %}{{ tab_bar(tabs, "activity") }}')
    tabs = [{'name': 'activity', 'label': 'Activity', 'hx_url': '/a'}, {'name': 'output', 'label': 'Output', 'hx_url': '/o'}, {'name': 'chat', 'label': 'Chat', 'hx_url': '/c'}]
    html = tmpl.render(tabs=tabs)
    assert "Activity" in html
    assert "Output" in html
    assert "Chat" in html

def test_sidebar_item_active(jinja_env):
    tmpl = jinja_env.from_string('{% from "components/macros.html" import sidebar_item %}{{ sidebar_item("myproj", "proj1", active=true) }}')
    html = tmpl.render()
    assert "myproj" in html
    assert "#161616" in html or "active" in html.lower()
