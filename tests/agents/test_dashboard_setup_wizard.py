"""Tests for the project setup wizard page."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    for attr in ("row", "column", "card", "stepper", "step", "stepper_navigation", "dialog"):
        ctx = _make_ui_ctx_mock()
        getattr(mock_ui, attr).return_value = ctx
    mock_ui.label.return_value = MagicMock()
    mock_ui.input.return_value = MagicMock()
    mock_ui.select.return_value = MagicMock()
    mock_ui.checkbox.return_value = MagicMock()
    mock_ui.notify.return_value = MagicMock()
    btn = _make_ui_ctx_mock()
    mock_ui.button.return_value = btn
    mock_ui.page.return_value = lambda fn: fn
    return mock_ui


def _make_mock_state():
    state = MagicMock()
    state.project_store.create_project.return_value = None
    state.project_store.create_source.return_value = None
    state.project_store.create_notification_rule.return_value = None
    # No integration clients by default
    state.linear_client = None
    state.github_client = None
    state.slack_bot_client = None
    return state


def _capture_page_fn(mock_ui_patch_target: str, setup_fn, *args):
    """Register the page via setup_fn, return the captured async page function."""
    captured = {}

    def capture_page(path):
        def decorator(fn):
            captured["fn"] = fn
            captured["path"] = path
            return fn
        return decorator

    with patch(mock_ui_patch_target) as mock_ui:
        mock_ui.page.side_effect = capture_page
        setup_fn(*args)

    return captured.get("fn"), captured.get("path")


# ---------------------------------------------------------------------------
# Import / registration
# ---------------------------------------------------------------------------


def test_module_is_importable():
    from agents.dashboard_setup_wizard import setup_wizard_page
    assert callable(setup_wizard_page)


def test_setup_wizard_page_registers_route():
    """setup_wizard_page registers a NiceGUI page at /dashboard/project/new."""
    from agents.dashboard_setup_wizard import setup_wizard_page

    state = _make_mock_state()
    fake_app = MagicMock()

    fn, path = _capture_page_fn(
        "agents.dashboard_setup_wizard.ui", setup_wizard_page, fake_app, state
    )

    assert path == "/dashboard/project/new"
    assert callable(fn)


def test_dashboard_registers_wizard_page():
    """setup_dashboard calls setup_wizard_page so the wizard route is wired up."""
    from agents.dashboard_setup_wizard import setup_wizard_page  # noqa: F401

    with patch("agents.dashboard.setup_wizard_page") as mock_wizard, \
         patch("agents.dashboard.setup_project_hub"), \
         patch("agents.dashboard.ui") as mock_ui:
        mock_ui.page.return_value = lambda fn: fn

        from agents.dashboard import setup_dashboard
        fake_app = MagicMock()
        fake_state = MagicMock()
        fake_config = MagicMock()
        fake_config.execution.dry_run = False

        setup_dashboard(fake_app, fake_state, fake_config)

        mock_wizard.assert_called_once_with(fake_app, fake_state)


# ---------------------------------------------------------------------------
# Page render
# ---------------------------------------------------------------------------


def test_wizard_page_renders_heading():
    """The wizard page renders a 'New Project' heading."""
    from agents.dashboard_setup_wizard import setup_wizard_page

    state = _make_mock_state()
    fake_app = MagicMock()
    fn, _ = _capture_page_fn(
        "agents.dashboard_setup_wizard.ui", setup_wizard_page, fake_app, state
    )

    mock_ui = _make_ui_mock()
    with (
        patch("agents.dashboard_setup_wizard.ui", mock_ui),
        patch("agents.dashboard_theme.ui", mock_ui),
    ):
        asyncio.run(fn())

    label_calls = [str(c) for c in mock_ui.label.call_args_list]
    assert any("New Project" in c for c in label_calls)


def test_wizard_page_creates_stepper():
    """The wizard page creates a ui.stepper with three steps."""
    from agents.dashboard_setup_wizard import setup_wizard_page

    state = _make_mock_state()
    fake_app = MagicMock()
    fn, _ = _capture_page_fn(
        "agents.dashboard_setup_wizard.ui", setup_wizard_page, fake_app, state
    )

    mock_ui = _make_ui_mock()
    with (
        patch("agents.dashboard_setup_wizard.ui", mock_ui),
        patch("agents.dashboard_theme.ui", mock_ui),
    ):
        asyncio.run(fn())

    mock_ui.stepper.assert_called_once()
    # Three steps: Basics, Discover Sources, Notifications
    step_calls = [c.args[0] for c in mock_ui.step.call_args_list]
    assert "Basics" in step_calls
    assert "Discover Sources" in step_calls
    assert "Notifications" in step_calls


def test_wizard_page_renders_input_fields():
    """Step 1 renders Project Name, Repository Path, and Default Branch inputs."""
    from agents.dashboard_setup_wizard import setup_wizard_page

    state = _make_mock_state()
    fake_app = MagicMock()
    fn, _ = _capture_page_fn(
        "agents.dashboard_setup_wizard.ui", setup_wizard_page, fake_app, state
    )

    mock_ui = _make_ui_mock()
    with (
        patch("agents.dashboard_setup_wizard.ui", mock_ui),
        patch("agents.dashboard_theme.ui", mock_ui),
    ):
        asyncio.run(fn())

    input_labels = [c.args[0] for c in mock_ui.input.call_args_list]
    assert "Project Name" in input_labels
    assert "Repository Path" in input_labels
    assert "Default Branch" in input_labels


def test_wizard_page_renders_notification_select():
    """Step 3 renders a notification channel select."""
    from agents.dashboard_setup_wizard import setup_wizard_page

    state = _make_mock_state()
    fake_app = MagicMock()
    fn, _ = _capture_page_fn(
        "agents.dashboard_setup_wizard.ui", setup_wizard_page, fake_app, state
    )

    mock_ui = _make_ui_mock()
    with (
        patch("agents.dashboard_setup_wizard.ui", mock_ui),
        patch("agents.dashboard_theme.ui", mock_ui),
    ):
        asyncio.run(fn())

    select_calls = [str(c) for c in mock_ui.select.call_args_list]
    assert any("slack" in c for c in select_calls)


# ---------------------------------------------------------------------------
# _discover_sources
# ---------------------------------------------------------------------------


def test_discover_sources_returns_empty_without_clients():
    """_discover_sources returns [] when no integration clients are configured."""
    from agents.dashboard_setup_wizard import _discover_sources

    state = _make_mock_state()
    result = asyncio.run(_discover_sources("myproject", state))
    assert result == []


def test_discover_sources_linear_match():
    """_discover_sources returns linear teams that match the project name."""
    from agents.dashboard_setup_wizard import _discover_sources

    state = _make_mock_state()
    state.linear_client = MagicMock()
    state.linear_client.fetch_teams = AsyncMock(
        return_value={"myproject": "team-id-1", "other": "team-id-2"}
    )

    result = asyncio.run(_discover_sources("myproject", state))

    assert len(result) == 1
    assert result[0]["source_type"] == "linear"
    assert result[0]["source_id"] == "team-id-1"
    assert result[0]["confidence"] == "high"


def test_discover_sources_linear_partial_match():
    """_discover_sources marks partial linear team matches as medium confidence."""
    from agents.dashboard_setup_wizard import _discover_sources

    state = _make_mock_state()
    state.linear_client = MagicMock()
    state.linear_client.fetch_teams = AsyncMock(return_value={"myproject-backend": "team-id-2"})

    result = asyncio.run(_discover_sources("myproject", state))

    assert len(result) == 1
    assert result[0]["confidence"] == "medium"


def test_discover_sources_github_match():
    """_discover_sources returns github repos that match the project name."""
    from agents.dashboard_setup_wizard import _discover_sources

    state = _make_mock_state()
    state.github_client = MagicMock()
    state.github_client.search_repos = AsyncMock(return_value=[
        {"full_name": "org/myproject", "name": "myproject"},
        {"full_name": "org/other", "name": "other"},
    ])

    result = asyncio.run(_discover_sources("myproject", state))

    assert len(result) == 2
    assert all(r["source_type"] == "github" for r in result)
    matching = [r for r in result if r["source_id"] == "org/myproject"]
    assert matching[0]["confidence"] == "high"


def test_discover_sources_slack_match():
    """_discover_sources returns slack channels that match the project name."""
    from agents.dashboard_setup_wizard import _discover_sources

    state = _make_mock_state()
    state.slack_bot_client = MagicMock()
    state.slack_bot_client.search_channels_by_name = AsyncMock(return_value=[
        {"id": "C123", "name": "myproject"},
        {"id": "C456", "name": "myproject-alerts"},
    ])

    result = asyncio.run(_discover_sources("myproject", state))

    assert len(result) == 2
    assert all(r["source_type"] == "slack" for r in result)
    exact = [r for r in result if r["source_id"] == "C123"]
    assert exact[0]["confidence"] == "high"


def test_discover_sources_suppresses_client_exceptions():
    """_discover_sources swallows exceptions from individual integration clients."""
    from agents.dashboard_setup_wizard import _discover_sources

    state = _make_mock_state()
    state.linear_client = MagicMock()
    state.linear_client.fetch_teams = AsyncMock(side_effect=RuntimeError("network error"))

    # Should not raise; just returns empty
    result = asyncio.run(_discover_sources("myproject", state))
    assert result == []


def test_discover_sources_limits_github_to_five():
    """_discover_sources caps GitHub results at 5 repos."""
    from agents.dashboard_setup_wizard import _discover_sources

    state = _make_mock_state()
    state.github_client = MagicMock()
    state.github_client.search_repos = AsyncMock(return_value=[
        {"full_name": f"org/repo{i}", "name": f"repo{i}"} for i in range(10)
    ])

    result = asyncio.run(_discover_sources("myproject", state))
    assert len(result) == 5


def test_discover_sources_limits_slack_to_five():
    """_discover_sources caps Slack results at 5 channels."""
    from agents.dashboard_setup_wizard import _discover_sources

    state = _make_mock_state()
    state.slack_bot_client = MagicMock()
    state.slack_bot_client.search_channels_by_name = AsyncMock(return_value=[
        {"id": f"C{i}", "name": f"channel{i}"} for i in range(10)
    ])

    result = asyncio.run(_discover_sources("myproject", state))
    assert len(result) == 5


# ---------------------------------------------------------------------------
# render_wizard_content — embeddable function for bottom sheet
# ---------------------------------------------------------------------------


def test_render_wizard_content_is_exported():
    """render_wizard_content is importable from dashboard_setup_wizard."""
    from agents.dashboard_setup_wizard import render_wizard_content
    assert callable(render_wizard_content)


def test_render_wizard_content_renders_stepper():
    """render_wizard_content creates a stepper with three steps."""
    from agents.dashboard_setup_wizard import render_wizard_content

    state = _make_mock_state()
    on_close = MagicMock()

    mock_ui = _make_ui_mock()
    mock_ui.html.return_value = MagicMock()
    with (
        patch("agents.dashboard_setup_wizard.ui", mock_ui),
        patch("agents.dashboard_theme.ui", mock_ui),
    ):
        render_wizard_content(state, on_close)

    mock_ui.stepper.assert_called_once()
    step_calls = [c.args[0] for c in mock_ui.step.call_args_list]
    assert "Basics" in step_calls
    assert "Discover Sources" in step_calls
    assert "Notifications" in step_calls


def test_render_wizard_content_renders_inputs():
    """render_wizard_content renders Project Name, Repo Path, Default Branch inputs."""
    from agents.dashboard_setup_wizard import render_wizard_content

    state = _make_mock_state()
    on_close = MagicMock()

    mock_ui = _make_ui_mock()
    mock_ui.html.return_value = MagicMock()
    with (
        patch("agents.dashboard_setup_wizard.ui", mock_ui),
        patch("agents.dashboard_theme.ui", mock_ui),
    ):
        render_wizard_content(state, on_close)

    input_labels = [c.args[0] for c in mock_ui.input.call_args_list]
    assert "Project Name" in input_labels
    assert "Repository Path" in input_labels
    assert "Default Branch" in input_labels


def test_render_wizard_content_renders_step_track():
    """render_wizard_content renders the step track HTML."""
    from agents.dashboard_setup_wizard import render_wizard_content

    state = _make_mock_state()
    on_close = MagicMock()

    mock_ui = _make_ui_mock()
    mock_ui.html.return_value = MagicMock()
    with (
        patch("agents.dashboard_setup_wizard.ui", mock_ui),
        patch("agents.dashboard_theme.ui", mock_ui),
    ):
        render_wizard_content(state, on_close)

    html_calls = [str(c) for c in mock_ui.html.call_args_list]
    assert any("step-track" in c for c in html_calls)
