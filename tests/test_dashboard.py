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


def _make_dashboard_ui_mock():
    """Return a MagicMock for ui that handles all new dashboard components."""
    mock_ui = MagicMock()
    for attr in ("row", "column", "card", "element", "scroll_area"):
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.classes.return_value = ctx
        ctx.style.return_value = ctx
        ctx.props.return_value = ctx
        getattr(mock_ui, attr).return_value = ctx
    mock_ui.label.return_value = MagicMock()
    mock_ui.html.return_value = MagicMock()
    mock_ui.linear_progress.return_value = MagicMock()
    mock_ui.badge.return_value = MagicMock()
    mock_table = MagicMock()
    mock_table.classes.return_value = mock_table
    mock_table.style.return_value = mock_table
    mock_ui.table.return_value = mock_table
    mock_ui.select.return_value = MagicMock()
    btn_mock = MagicMock()
    btn_mock.props.return_value = btn_mock
    btn_mock.classes.return_value = btn_mock
    btn_mock.__enter__ = MagicMock(return_value=btn_mock)
    btn_mock.__exit__ = MagicMock(return_value=False)
    mock_ui.button.return_value = btn_mock
    mock_ui.timer.return_value = MagicMock()
    mock_ui.dialog.return_value = MagicMock()
    return mock_ui


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


def test_dashboard_page_renders_header_with_stats(tmp_path: Path):
    """The dashboard page renders a compact header with active/failed stats."""
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

    assert captured_page_fn is not None, "Page function was not registered"

    import asyncio

    mock_ui = _make_dashboard_ui_mock()
    with patch("agents.dashboard.ui", mock_ui):
        mock_client = MagicMock()
        mock_client.on_disconnect = MagicMock()
        asyncio.run(captured_page_fn(mock_client))

        # ui.row() should have been called to build the page layout
        assert mock_ui.row.call_count >= 1
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

    mock_ui = _make_dashboard_ui_mock()
    with patch("agents.dashboard.ui", mock_ui):
        mock_client = MagicMock()
        mock_client.on_disconnect = MagicMock()
        asyncio.run(captured_page_fn(mock_client))

        mock_ui.dark_mode.assert_called_once_with(True)


def test_on_row_click_falls_back_to_sqlite_when_not_in_memory(tmp_path: Path):
    """When run_events has no entry for a run, on_row_click falls back to history.list_events."""
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

    # Seed SQLite with events for a run that is NOT in the in-memory cache
    run_id = "run-historical-001"
    state.history.insert_event(run_id, {
        "run_id": run_id, "type": "task_started", "content": "proj/daily [manual]",
        "tool_name": "", "timestamp": 1000.0,
    })
    assert run_id not in state.run_events  # confirm: not in memory

    import asyncio

    captured_build_args: dict = {}

    def fake_build_run_drawer(**kwargs):
        captured_build_args.update(kwargs)

    mock_ui = _make_dashboard_ui_mock()
    on_callbacks: dict = {}

    def fake_on(event_name, callback):
        on_callbacks[event_name] = callback
    mock_ui.table.return_value.on = fake_on

    with (
        patch("agents.dashboard.ui", mock_ui),
        patch("agents.dashboard._build_run_drawer", side_effect=fake_build_run_drawer),
    ):
        mock_client = MagicMock()
        mock_client.on_disconnect = MagicMock()
        asyncio.run(captured_page_fn(mock_client))

        # Simulate a row click on the historical run
        mock_event = MagicMock()
        mock_event.args = [
            None,
            {"id": run_id, "project": "proj", "task": "daily", "raw_status": "success"},
        ]
        on_callbacks["rowClick"](mock_event)

    # The drawer must have been called with events from SQLite
    assert "existing_events" in captured_build_args
    events = captured_build_args["existing_events"]
    assert len(events) == 1
    assert events[0]["type"] == "task_started"


def test_on_row_click_prefers_memory_events_over_sqlite(tmp_path: Path):
    """When run_events has an entry in memory, it is used instead of hitting SQLite."""
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

    run_id = "run-live-001"
    memory_events = [
        {
            "run_id": run_id, "type": "assistant", "content": "live",
            "tool_name": "", "timestamp": 2000.0,
        },
    ]
    state.run_events[run_id] = memory_events

    import asyncio

    captured_build_args: dict = {}

    def fake_build_run_drawer(**kwargs):
        captured_build_args.update(kwargs)

    mock_ui = _make_dashboard_ui_mock()
    on_callbacks: dict = {}

    def fake_on(event_name, callback):
        on_callbacks[event_name] = callback
    mock_ui.table.return_value.on = fake_on

    with (
        patch("agents.dashboard.ui", mock_ui),
        patch("agents.dashboard._build_run_drawer", side_effect=fake_build_run_drawer),
    ):
        mock_client = MagicMock()
        mock_client.on_disconnect = MagicMock()
        asyncio.run(captured_page_fn(mock_client))

        mock_event = MagicMock()
        mock_event.args = [
            None,
            {"id": run_id, "project": "proj", "task": "daily", "raw_status": "running"},
        ]
        on_callbacks["rowClick"](mock_event)

    assert captured_build_args["existing_events"] == memory_events


def test_dashboard_page_registers_auto_refresh_timer(tmp_path: Path):
    """The dashboard page sets up timers for drain_queue (0.15s) and refresh (3.0s)."""
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

    mock_ui = _make_dashboard_ui_mock()
    with patch("agents.dashboard.ui", mock_ui):
        mock_client = MagicMock()
        mock_client.on_disconnect = MagicMock()
        asyncio.run(captured_page_fn(mock_client))

        # timer must be called (0.15s for drain_queue + 3.0s for refresh)
        timer_calls = mock_ui.timer.call_args_list
        assert any(call.args[0] == 3.0 for call in timer_calls), (
            f"Expected ui.timer(3.0, ...) but got: {timer_calls}"
        )
