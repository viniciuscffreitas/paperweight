"""Tests for the NiceGUI dashboard setup."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state_and_config(tmp_path: Path):
    """Return a minimal (AppState-like, GlobalConfig-like) pair."""
    from agents.budget import BudgetManager
    from agents.config import GlobalConfig, load_global_config, load_project_configs
    from agents.history import HistoryDB
    from agents.main import AppState
    from agents.notifier import Notifier

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
budget:
  daily_limit_usd: 10.00
  warning_threshold_usd: 7.00
  pause_on_limit: true
notifications:
  slack_webhook_url: ""
webhooks:
  github_secret: ""
  linear_secret: ""
execution:
  worktree_base: /tmp/test-agents
  default_model: sonnet
  default_max_cost_usd: 5.00
  default_autonomy: pr-only
  max_concurrent: 3
  timeout_minutes: 15
  dry_run: true
server:
  host: 127.0.0.1
  port: 9090
"""
    )
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    (projects_dir / "proj.yaml").write_text(
        """
name: proj
repo: /tmp/repo
tasks:
  daily:
    description: "Daily task"
    schedule: "0 9 * * *"
    prompt: "Do something"
"""
    )

    config: GlobalConfig = load_global_config(config_file)
    projects = load_project_configs(projects_dir)
    history = HistoryDB(tmp_path / "agents.db")
    budget = BudgetManager(config=config.budget, history=history)
    notifier = Notifier(webhook_url="")

    from agents.executor import Executor

    executor = Executor(
        config=config.execution,
        budget=budget,
        history=history,
        notifier=notifier,
        data_dir=tmp_path / "data",
        on_stream_event=AsyncMock(),
    )

    state = AppState(
        projects=projects,
        executor=executor,
        history=history,
        budget=budget,
        notifier=notifier,
        github_secret="",
        linear_secret="",
    )
    return state, config


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_setup_dashboard_is_importable():
    """setup_dashboard can be imported from agents.dashboard."""
    from agents.dashboard import setup_dashboard

    assert callable(setup_dashboard)


def test_setup_dashboard_calls_run_with(tmp_path: Path):
    """setup_dashboard calls ui.run_with(app) to mount NiceGUI onto FastAPI."""
    state, config = _make_state_and_config(tmp_path)
    fake_app = MagicMock()

    with patch("agents.dashboard.ui") as mock_ui:
        # ui.page returns a decorator that we must honour so the inner function
        # is actually registered; simulate that by returning a passthrough decorator.
        mock_ui.page.return_value = lambda fn: fn

        from agents.dashboard import setup_dashboard

        setup_dashboard(fake_app, state, config)

        mock_ui.run_with.assert_called_once_with(fake_app)


def test_setup_dashboard_registers_dashboard_page(tmp_path: Path):
    """setup_dashboard registers a page at /dashboard."""
    state, config = _make_state_and_config(tmp_path)
    fake_app = MagicMock()

    with patch("agents.dashboard.ui") as mock_ui:
        mock_ui.page.return_value = lambda fn: fn

        from agents.dashboard import setup_dashboard

        setup_dashboard(fake_app, state, config)

        # ui.page must have been called with "/dashboard"
        mock_ui.page.assert_called_once_with("/dashboard")


def test_setup_dashboard_mounted_in_create_app(tmp_path: Path):
    """create_app() mounts the dashboard (ui.run_with is called once)."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
budget:
  daily_limit_usd: 10.00
  warning_threshold_usd: 7.00
  pause_on_limit: true
notifications:
  slack_webhook_url: ""
webhooks:
  github_secret: ""
  linear_secret: ""
execution:
  worktree_base: /tmp/test-agents
  default_model: sonnet
  default_max_cost_usd: 5.00
  default_autonomy: pr-only
  max_concurrent: 3
  timeout_minutes: 15
  dry_run: true
server:
  host: 127.0.0.1
  port: 9090
"""
    )
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    with patch("agents.dashboard.ui") as mock_ui:
        mock_ui.page.return_value = lambda fn: fn

        from agents.main import create_app

        create_app(
            config_path=config_file,
            projects_dir=projects_dir,
            data_dir=tmp_path / "data",
        )

        mock_ui.run_with.assert_called_once()


def test_dashboard_page_renders_budget_header(tmp_path: Path):
    """The dashboard page function calls ui.header and displays budget info."""
    state, config = _make_state_and_config(tmp_path)
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
        # Make context managers work
        mock_ui.header.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_ui.header.return_value.__exit__ = MagicMock(return_value=False)
        mock_ui.row.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_ui.row.return_value.__exit__ = MagicMock(return_value=False)
        mock_ui.card.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_ui.card.return_value.__exit__ = MagicMock(return_value=False)

        from agents.dashboard import setup_dashboard

        setup_dashboard(fake_app, state, config)

    assert captured_page_fn is not None, "Page function was not registered"

    # Now call the page function (it's async)
    import asyncio

    with patch("agents.dashboard.ui") as mock_ui:
        mock_ui.header.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_ui.header.return_value.__exit__ = MagicMock(return_value=False)
        mock_ui.row.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_ui.row.return_value.__exit__ = MagicMock(return_value=False)
        mock_ui.card.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_ui.card.return_value.__exit__ = MagicMock(return_value=False)
        mock_label = MagicMock()
        mock_ui.label.return_value = mock_label
        mock_ui.linear_progress.return_value = MagicMock()
        mock_ui.log.return_value = MagicMock()
        mock_ui.table.return_value = MagicMock()
        mock_ui.select.return_value = MagicMock()
        mock_ui.button.return_value = MagicMock()
        mock_ui.timer.return_value = MagicMock()

        asyncio.get_event_loop().run_until_complete(captured_page_fn())

        # ui.header() should have been called to build the page header
        mock_ui.header.assert_called_once()
        # ui.label should have been called multiple times (header, stats, sections…)
        assert mock_ui.label.call_count >= 1


def test_dashboard_page_uses_dark_mode(tmp_path: Path):
    """The dashboard page enables dark mode."""
    state, config = _make_state_and_config(tmp_path)
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

    import asyncio

    with patch("agents.dashboard.ui") as mock_ui:
        mock_ui.header.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_ui.header.return_value.__exit__ = MagicMock(return_value=False)
        mock_ui.row.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_ui.row.return_value.__exit__ = MagicMock(return_value=False)
        mock_ui.card.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_ui.card.return_value.__exit__ = MagicMock(return_value=False)
        mock_ui.label.return_value = MagicMock()
        mock_ui.linear_progress.return_value = MagicMock()
        mock_ui.log.return_value = MagicMock()
        mock_ui.table.return_value = MagicMock()
        mock_ui.select.return_value = MagicMock()
        mock_ui.button.return_value = MagicMock()
        mock_ui.timer.return_value = MagicMock()

        asyncio.get_event_loop().run_until_complete(captured_page_fn())

        mock_ui.dark_mode.assert_called_once_with(True)


def test_dashboard_page_registers_auto_refresh_timer(tmp_path: Path):
    """The dashboard page sets up a 5-second auto-refresh timer."""
    state, config = _make_state_and_config(tmp_path)
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

    import asyncio

    with patch("agents.dashboard.ui") as mock_ui:
        mock_ui.header.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_ui.header.return_value.__exit__ = MagicMock(return_value=False)
        mock_ui.row.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_ui.row.return_value.__exit__ = MagicMock(return_value=False)
        mock_ui.card.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_ui.card.return_value.__exit__ = MagicMock(return_value=False)
        mock_ui.label.return_value = MagicMock()
        mock_ui.linear_progress.return_value = MagicMock()
        mock_ui.log.return_value = MagicMock()
        mock_ui.table.return_value = MagicMock()
        mock_ui.select.return_value = MagicMock()
        mock_ui.button.return_value = MagicMock()
        mock_ui.timer.return_value = MagicMock()

        asyncio.get_event_loop().run_until_complete(captured_page_fn())

        # timer(5.0, ...) must be called
        timer_calls = mock_ui.timer.call_args_list
        assert any(call.args[0] == 5.0 for call in timer_calls), (
            f"Expected ui.timer(5.0, ...) but got: {timer_calls}"
        )
