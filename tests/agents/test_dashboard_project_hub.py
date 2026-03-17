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


def test_render_hub_header_has_full_width():
    """Header div in render_hub_content must include width:100% to fill the panel.

    Without width:100%, the header collapses to content width inside the flex
    column, causing the 'narrow centered content' visual bug.
    """
    state = _make_mock_state(projects=[{"id": "p1", "name": "Test"}])
    on_close = MagicMock()

    # Track every style string applied to any ui.element("div")
    style_calls: list[str] = []
    ctx = _make_ui_ctx_mock()

    def capture_style(s: str):
        style_calls.append(s)
        return ctx

    ctx.style = capture_style

    mock_ui = _make_ui_mock()
    mock_ui.element.return_value = ctx
    mock_ui.tabs.return_value = _make_ui_ctx_mock()
    mock_ui.tab.return_value = _make_ui_ctx_mock()
    mock_ui.tab_panels.return_value = _make_ui_ctx_mock()
    mock_ui.tab_panel.return_value = _make_ui_ctx_mock()
    mock_ui.html.return_value = MagicMock()

    with patch("agents.dashboard_project_hub.ui", mock_ui):
        from agents.dashboard_project_hub import render_hub_content
        render_hub_content("p1", state, on_close)

    assert any("width:100%" in s for s in style_calls), (
        f"Expected at least one element to have width:100% but got: {style_calls}"
    )


# ---------------------------------------------------------------------------
# Width-propagation tests (contract: activity/runs scroll_areas fill full width)
# ---------------------------------------------------------------------------


def test_event_card_row_uses_w_full():
    """_render_event_card's row container must use w-full to fill panel width.

    MUST NOT CHANGE: removing w-full would cause cards to collapse to content width.
    """
    from agents.dashboard_project_hub import _render_event_card

    event = {
        "source": "linear",
        "title": "Fix event",
        "timestamp": "2024-01-01T10:00:00",
        "priority": "high",
        "author": "alice",
    }
    row_ctx = _make_ui_ctx_mock()
    mock_ui = _make_ui_mock()
    mock_ui.row.return_value = row_ctx

    with patch("agents.dashboard_project_hub.ui", mock_ui):
        _render_event_card(event)

    assert mock_ui.row.called, "Expected ui.row() to be called for event card"
    classes_calls = [str(c) for c in row_ctx.classes.call_args_list]
    assert any("w-full" in c for c in classes_calls), (
        f"Event card row must have w-full class. Got: {classes_calls}"
    )


def test_all_hub_scroll_areas_propagate_width_to_content():
    """Every scroll_area in render_hub_content must pass width:100% to the inner
    content container via content-style prop.

    QScrollArea's q-scrollarea__content is absolute-positioned; without explicit
    width:100% on that inner element, child rows collapse to their natural width,
    leaving the right side of the panel black.

    CHANGES: Activity and Runs scroll_areas must use
    .props('content-style="...;width:100%..."') instead of .style("padding:...").
    """
    state = _make_mock_state(projects=[{"id": "p1", "name": "Test"}])
    on_close = MagicMock()

    scroll_ctxs: list = []

    def make_scroll_ctx():
        ctx = _make_ui_ctx_mock()
        scroll_ctxs.append(ctx)
        return ctx

    mock_ui = _make_ui_mock()
    mock_ui.scroll_area.side_effect = make_scroll_ctx
    mock_ui.tabs.return_value = _make_ui_ctx_mock()
    mock_ui.tab.return_value = _make_ui_ctx_mock()
    mock_ui.tab_panels.return_value = _make_ui_ctx_mock()
    mock_ui.tab_panel.return_value = _make_ui_ctx_mock()

    with patch("agents.dashboard_project_hub.ui", mock_ui):
        from agents.dashboard_project_hub import render_hub_content

        render_hub_content("p1", state, on_close)

    assert scroll_ctxs, "Expected at least one scroll_area to be created"

    for i, ctx in enumerate(scroll_ctxs):
        props_for_this = [
            str(a) for call in ctx.props.call_args_list for a in call.args
        ]
        assert any("width:100%" in p for p in props_for_this), (
            f"scroll_area #{i} must use content-style with width:100% so inner "
            f"content fills the full panel width. Actual props: {props_for_this}"
        )


def test_open_hub_uses_div_not_card(tmp_path):
    """open_hub wraps render_hub_content in ui.element(div), not ui.card.

    ui.card (QCard) inside a flex column dialog applies its own centering
    behavior — replacing it with a plain div gives full-width control.
    """
    import asyncio
    from pathlib import Path

    # We need _make_state_and_config so import here
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from test_dashboard import _make_state_and_config, _make_dashboard_ui_mock

    state, config = _make_state_and_config(tmp_path)
    state.project_store = MagicMock()
    state.project_store.list_projects.return_value = [{"id": "p1", "name": "Test"}]
    state.project_store.get_project.return_value = {"id": "p1", "name": "Test"}
    state.project_store.list_events.return_value = []
    state.project_store.list_sources.return_value = []
    state.project_store.list_tasks.return_value = []
    fake_app = MagicMock()
    captured_page_fn = None

    def capture_page(path):
        def decorator(fn):
            nonlocal captured_page_fn
            captured_page_fn = fn
            return fn
        return decorator

    with patch("agents.dashboard.ui") as mock_ui:
        mock_ui.page.side_effect = capture_page
        from agents.dashboard import setup_dashboard
        setup_dashboard(fake_app, state, config)

    assert captured_page_fn is not None
    mock_ui = _make_dashboard_ui_mock()

    # Capture dialog mock so we can inspect what's put inside it
    dialog_mock = MagicMock()
    dialog_mock.props.return_value = dialog_mock
    dialog_mock.classes.return_value = dialog_mock
    dialog_mock.__enter__ = MagicMock(return_value=dialog_mock)
    dialog_mock.__exit__ = MagicMock(return_value=False)
    dialog_mock.clear = MagicMock()
    dialog_mock.open = MagicMock()
    mock_ui.dialog.return_value = dialog_mock

    with patch("agents.dashboard.ui", mock_ui), patch("agents.dashboard_theme.ui", mock_ui):
        mock_client = MagicMock()
        mock_client.on_disconnect = MagicMock()
        asyncio.run(captured_page_fn(mock_client))

    # ui.card must NOT be called during page setup — open_hub is lazy
    # When the page is rendered without any click, card count should be 0
    assert mock_ui.card.call_count == 0, (
        "ui.card should not be called at page-render time (open_hub is lazy)"
    )
