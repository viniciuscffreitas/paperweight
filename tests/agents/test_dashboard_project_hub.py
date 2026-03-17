"""Tests for dashboard_project_hub module."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_mock_state(projects=None, events=None, sources=None, tasks=None, runs=None):
    """Build a minimal state mock with project_store and history."""
    state = MagicMock()
    state.project_store.get_project.return_value = (
        projects[0] if projects else {"id": "p1", "name": "Test Project"}
    )
    state.project_store.list_projects.return_value = projects or []
    state.project_store.list_events.return_value = events or []
    state.project_store.list_sources.return_value = sources or []
    state.project_store.list_tasks.return_value = tasks or []
    state.history.list_runs_today.return_value = runs or []
    return state


def _make_ui_ctx_mock():
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=ctx)
    ctx.__exit__ = MagicMock(return_value=False)
    ctx.classes = MagicMock(return_value=ctx)
    ctx.style = MagicMock(return_value=ctx)
    ctx.props = MagicMock(return_value=ctx)
    return ctx


def _make_ui_mock():
    mock_ui = MagicMock()
    for attr in ("row", "column", "card", "expansion", "scroll_area", "dialog"):
        ctx = _make_ui_ctx_mock()
        getattr(mock_ui, attr).return_value = ctx
    mock_ui.label.return_value = MagicMock()
    mock_ui.icon.return_value = MagicMock()
    mock_ui.badge.return_value = MagicMock()
    mock_ui.separator.return_value = MagicMock()
    mock_ui.link.return_value = MagicMock()
    btn = _make_ui_ctx_mock()
    mock_ui.button.return_value = btn
    mock_ui.select.return_value = MagicMock()
    mock_ui.input.return_value = MagicMock()
    mock_ui.textarea.return_value = MagicMock()
    mock_ui.number.return_value = MagicMock()
    mock_ui.page.return_value = lambda fn: fn
    return mock_ui


# ---------------------------------------------------------------------------
# Import / registration tests
# ---------------------------------------------------------------------------


def test_module_is_importable():
    """dashboard_project_hub can be imported."""
    from agents.dashboard_project_hub import setup_project_hub

    assert callable(setup_project_hub)


def test_setup_project_hub_registers_page():
    """setup_project_hub registers a page at /dashboard/project/{project_id}."""
    state = _make_mock_state()
    fake_app = MagicMock()

    with patch("agents.dashboard_project_hub.ui") as mock_ui:
        mock_ui.page.return_value = lambda fn: fn
        from agents.dashboard_project_hub import setup_project_hub

        setup_project_hub(fake_app, state)

        mock_ui.page.assert_called_once_with("/dashboard/project/{project_id}")


# ---------------------------------------------------------------------------
# Render tests
# ---------------------------------------------------------------------------


def test_project_not_found_renders_error():
    """When project_store.get_project returns None, an error label is shown."""
    import asyncio

    state = _make_mock_state()
    state.project_store.get_project.return_value = None
    fake_app = MagicMock()
    captured_fn = None

    def capture_page(path):
        def decorator(fn):
            nonlocal captured_fn
            captured_fn = fn
            return fn

        return decorator

    with patch("agents.dashboard_project_hub.ui") as mock_ui:
        mock_ui.page.side_effect = capture_page
        from agents.dashboard_project_hub import setup_project_hub

        setup_project_hub(fake_app, state)

    assert captured_fn is not None
    mock_ui = _make_ui_mock()
    with (
        patch("agents.dashboard_project_hub.ui", mock_ui),
        patch("agents.dashboard_theme.ui", mock_ui),
    ):
        asyncio.run(captured_fn("missing-id"))
        # Should render an error label
        label_calls = [str(c) for c in mock_ui.label.call_args_list]
        assert any("not found" in c.lower() for c in label_calls)


def test_project_page_renders_project_name():
    """When a project is found, the project name is rendered as a heading."""
    import asyncio

    state = _make_mock_state(projects=[{"id": "p1", "name": "My Project"}])
    fake_app = MagicMock()
    captured_fn = None

    def capture_page(path):
        def decorator(fn):
            nonlocal captured_fn
            captured_fn = fn
            return fn

        return decorator

    with patch("agents.dashboard_project_hub.ui") as mock_ui:
        mock_ui.page.side_effect = capture_page
        from agents.dashboard_project_hub import setup_project_hub

        setup_project_hub(fake_app, state)

    assert captured_fn is not None
    mock_ui = _make_ui_mock()
    with (
        patch("agents.dashboard_project_hub.ui", mock_ui),
        patch("agents.dashboard_theme.ui", mock_ui),
    ):
        asyncio.run(captured_fn("p1"))
        label_calls = [str(c) for c in mock_ui.label.call_args_list]
        assert any("My Project" in c for c in label_calls)


def test_project_page_renders_empty_feed_message():
    """When there are no events, the empty-state message is shown."""
    import asyncio

    state = _make_mock_state(events=[])
    fake_app = MagicMock()
    captured_fn = None

    def capture_page(path):
        def decorator(fn):
            nonlocal captured_fn
            captured_fn = fn
            return fn

        return decorator

    with patch("agents.dashboard_project_hub.ui") as mock_ui:
        mock_ui.page.side_effect = capture_page
        from agents.dashboard_project_hub import setup_project_hub

        setup_project_hub(fake_app, state)

    mock_ui = _make_ui_mock()
    with (
        patch("agents.dashboard_project_hub.ui", mock_ui),
        patch("agents.dashboard_theme.ui", mock_ui),
    ):
        import asyncio

        asyncio.run(captured_fn("p1"))
        label_calls = [str(c) for c in mock_ui.label.call_args_list]
        assert any("Configure sources" in c for c in label_calls)


def test_project_page_renders_events():
    """Event cards are rendered for each event in the feed."""
    import asyncio

    events = [
        {
            "source": "linear", "title": "Fix bug",
            "timestamp": "2024-01-01T10:00:00", "priority": "high", "author": "alice",
        },
        {
            "source": "github", "title": "Open PR",
            "timestamp": "2024-01-01T11:00:00", "priority": "none", "author": "",
        },
    ]
    state = _make_mock_state(events=events)
    fake_app = MagicMock()
    captured_fn = None

    def capture_page(path):
        def decorator(fn):
            nonlocal captured_fn
            captured_fn = fn
            return fn

        return decorator

    with patch("agents.dashboard_project_hub.ui") as mock_ui:
        mock_ui.page.side_effect = capture_page
        from agents.dashboard_project_hub import setup_project_hub

        setup_project_hub(fake_app, state)

    mock_ui = _make_ui_mock()
    with (
        patch("agents.dashboard_project_hub.ui", mock_ui),
        patch("agents.dashboard_theme.ui", mock_ui),
    ):
        asyncio.run(captured_fn("p1"))
        label_calls = [str(c) for c in mock_ui.label.call_args_list]
        assert any("Fix bug" in c for c in label_calls)
        assert any("Open PR" in c for c in label_calls)


# ---------------------------------------------------------------------------
# SOURCE_ICONS / SOURCE_COLORS constants
# ---------------------------------------------------------------------------


def test_source_icons_and_colors_defined():
    """SOURCE_ICONS and SOURCE_COLORS cover the expected sources."""
    from agents.dashboard_project_hub import SOURCE_COLORS, SOURCE_ICONS

    for source in ("linear", "github", "slack"):
        assert source in SOURCE_ICONS
        assert source in SOURCE_COLORS


def test_priority_colors_defined():
    """PRIORITY_COLORS covers expected priority levels."""
    from agents.dashboard_project_hub import PRIORITY_COLORS

    for level in ("urgent", "high", "medium", "low", "none"):
        assert level in PRIORITY_COLORS


# ---------------------------------------------------------------------------
# render_hub_content — embeddable function for right panel
# ---------------------------------------------------------------------------


def test_render_hub_content_is_exported():
    """render_hub_content is importable from dashboard_project_hub."""
    from agents.dashboard_project_hub import render_hub_content
    assert callable(render_hub_content)


def test_render_hub_content_renders_project_name():
    """render_hub_content renders the project name in the panel header."""
    state = _make_mock_state(projects=[{"id": "p1", "name": "My Project"}])
    on_close = MagicMock()

    mock_ui = _make_ui_mock()
    mock_ui.tabs.return_value = _make_ui_ctx_mock()
    mock_ui.tab.return_value = _make_ui_ctx_mock()
    mock_ui.tab_panels.return_value = _make_ui_ctx_mock()
    mock_ui.tab_panel.return_value = _make_ui_ctx_mock()
    mock_ui.html.return_value = MagicMock()

    with (
        patch("agents.dashboard_project_hub.ui", mock_ui),
        patch("agents.dashboard_theme.ui", mock_ui),
    ):
        from agents.dashboard_project_hub import render_hub_content
        render_hub_content("p1", state, on_close)

    label_calls = [str(c) for c in mock_ui.label.call_args_list]
    assert any("My Project" in c for c in label_calls)


def test_render_hub_content_renders_three_tabs():
    """render_hub_content creates Activity, Tasks, and Runs tabs."""
    state = _make_mock_state()
    on_close = MagicMock()

    mock_ui = _make_ui_mock()
    tab_ctx = _make_ui_ctx_mock()
    mock_ui.tabs.return_value = tab_ctx
    mock_ui.tab.return_value = _make_ui_ctx_mock()
    mock_ui.tab_panels.return_value = _make_ui_ctx_mock()
    mock_ui.tab_panel.return_value = _make_ui_ctx_mock()
    mock_ui.html.return_value = MagicMock()

    with (
        patch("agents.dashboard_project_hub.ui", mock_ui),
        patch("agents.dashboard_theme.ui", mock_ui),
    ):
        from agents.dashboard_project_hub import render_hub_content
        render_hub_content("p1", state, on_close)

    tab_names = [str(c) for c in mock_ui.tab.call_args_list]
    assert any("activity" in c.lower() for c in tab_names)
    assert any("tasks" in c.lower() for c in tab_names)
    assert any("runs" in c.lower() for c in tab_names)


def test_render_hub_content_project_not_found_renders_error():
    """render_hub_content renders an error when project is not found."""
    state = _make_mock_state()
    state.project_store.get_project.return_value = None
    on_close = MagicMock()

    mock_ui = _make_ui_mock()
    mock_ui.html.return_value = MagicMock()

    with (
        patch("agents.dashboard_project_hub.ui", mock_ui),
        patch("agents.dashboard_theme.ui", mock_ui),
    ):
        from agents.dashboard_project_hub import render_hub_content
        render_hub_content("missing", state, on_close)

    label_calls = [str(c) for c in mock_ui.label.call_args_list]
    assert any("not found" in c.lower() for c in label_calls)
