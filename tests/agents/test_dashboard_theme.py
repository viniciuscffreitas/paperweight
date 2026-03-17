"""Tests for dashboard_theme shared CSS and helpers."""
from __future__ import annotations


def test_dashboard_css_contains_bottom_sheet():
    from agents.dashboard_theme import DASHBOARD_CSS
    assert ".bottom-sheet" in DASHBOARD_CSS


def test_dashboard_css_contains_right_panel():
    from agents.dashboard_theme import DASHBOARD_CSS
    assert ".right-panel" in DASHBOARD_CSS


def test_dashboard_css_contains_sheet_up_animation():
    from agents.dashboard_theme import DASHBOARD_CSS
    assert "sheet-up" in DASHBOARD_CSS


def test_dashboard_css_contains_panel_in_animation():
    from agents.dashboard_theme import DASHBOARD_CSS
    assert "panel-in" in DASHBOARD_CSS


def test_dashboard_css_contains_panel_tabs():
    from agents.dashboard_theme import DASHBOARD_CSS
    assert ".panel-tab" in DASHBOARD_CSS


def test_dashboard_css_contains_step_track():
    from agents.dashboard_theme import DASHBOARD_CSS
    assert ".step-track" in DASHBOARD_CSS


def test_dashboard_css_contains_sheet_handle():
    from agents.dashboard_theme import DASHBOARD_CSS
    assert ".sheet-handle" in DASHBOARD_CSS
