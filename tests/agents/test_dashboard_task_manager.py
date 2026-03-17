"""Tests for the Task Manager dashboard page."""
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
    for attr in ("row", "column", "card", "dialog", "separator", "expansion"):
        ctx = _make_ui_ctx_mock()
        getattr(mock_ui, attr).return_value = ctx
    mock_ui.label.return_value = MagicMock()
    mock_ui.input.return_value = MagicMock()
    mock_ui.textarea.return_value = MagicMock()
    mock_ui.select.return_value = MagicMock()
    mock_ui.number.return_value = MagicMock()
    mock_ui.switch.return_value = MagicMock()
    mock_ui.notify.return_value = MagicMock()
    mock_ui.link.return_value = MagicMock()
    btn = _make_ui_ctx_mock()
    mock_ui.button.return_value = btn
    mock_ui.page.return_value = lambda fn: fn
    return mock_ui


def _make_mock_state(tasks=None):
    state = MagicMock()
    state.project_store.get_project.return_value = {"id": "proj-1", "name": "My Project"}
    state.project_store.list_tasks.return_value = tasks or []
    state.project_store.create_task.return_value = "task-new-id"
    state.project_store.update_task.return_value = None
    state.project_store.delete_task.return_value = None
    return state


def _make_sample_task(**overrides):
    base = {
        "id": "task-1",
        "name": "Fix bugs",
        "intent": "Find and fix bugs",
        "trigger_type": "manual",
        "model": "sonnet",
        "max_budget": 5.0,
        "autonomy": "pr-only",
        "enabled": 1,
    }
    base.update(overrides)
    return base


def _capture_page_fn(setup_fn, *args):
    """Register the page via setup_fn, return the captured async page function."""
    captured = {}

    def capture_page(path):
        def decorator(fn):
            captured["fn"] = fn
            captured["path"] = path
            return fn
        return decorator

    with patch("agents.dashboard_task_manager.ui") as mock_ui:
        mock_ui.page.side_effect = capture_page
        setup_fn(*args)

    return captured.get("fn"), captured.get("path")


# ---------------------------------------------------------------------------
# Import / registration
# ---------------------------------------------------------------------------


def test_module_is_importable():
    from agents.dashboard_task_manager import setup_task_manager
    assert callable(setup_task_manager)


def test_setup_task_manager_registers_route():
    """setup_task_manager registers a NiceGUI page at /dashboard/project/{project_id}/tasks."""
    from agents.dashboard_task_manager import setup_task_manager

    state = _make_mock_state()
    fake_app = MagicMock()

    fn, path = _capture_page_fn(setup_task_manager, fake_app, state)

    assert path == "/dashboard/project/{project_id}/tasks"
    assert callable(fn)


def test_dashboard_registers_task_manager():
    """setup_dashboard calls setup_task_manager so the task manager route is wired up."""
    with patch("agents.dashboard.setup_task_manager") as mock_tm, \
         patch("agents.dashboard.setup_wizard_page"), \
         patch("agents.dashboard.setup_project_hub"), \
         patch("agents.dashboard.ui") as mock_ui:
        mock_ui.page.return_value = lambda fn: fn

        from agents.dashboard import setup_dashboard
        fake_app = MagicMock()
        fake_state = MagicMock()
        fake_config = MagicMock()
        fake_config.execution.dry_run = False

        setup_dashboard(fake_app, fake_state, fake_config)

        mock_tm.assert_called_once_with(fake_app, fake_state)


# ---------------------------------------------------------------------------
# Page render — project not found
# ---------------------------------------------------------------------------


def test_tasks_page_shows_error_when_project_not_found():
    """tasks_page shows an error label when the project does not exist."""
    from agents.dashboard_task_manager import setup_task_manager

    state = _make_mock_state()
    state.project_store.get_project.return_value = None
    fake_app = MagicMock()

    fn, _ = _capture_page_fn(setup_task_manager, fake_app, state)

    mock_ui = _make_ui_mock()
    with patch("agents.dashboard_task_manager.ui", mock_ui):
        asyncio.run(fn(project_id="missing"))

    label_calls = [str(c) for c in mock_ui.label.call_args_list]
    assert any("not found" in c.lower() for c in label_calls)


# ---------------------------------------------------------------------------
# Page render — empty task list
# ---------------------------------------------------------------------------


def test_tasks_page_renders_heading():
    """tasks_page renders the project name in the heading."""
    from agents.dashboard_task_manager import setup_task_manager

    state = _make_mock_state()
    fake_app = MagicMock()

    fn, _ = _capture_page_fn(setup_task_manager, fake_app, state)

    mock_ui = _make_ui_mock()
    with patch("agents.dashboard_task_manager.ui", mock_ui):
        asyncio.run(fn(project_id="proj-1"))

    label_calls = [str(c) for c in mock_ui.label.call_args_list]
    assert any("My Project" in c for c in label_calls)


def test_tasks_page_renders_empty_state():
    """tasks_page shows 'No tasks yet' when there are no tasks."""
    from agents.dashboard_task_manager import setup_task_manager

    state = _make_mock_state(tasks=[])
    fake_app = MagicMock()

    fn, _ = _capture_page_fn(setup_task_manager, fake_app, state)

    mock_ui = _make_ui_mock()
    with patch("agents.dashboard_task_manager.ui", mock_ui):
        asyncio.run(fn(project_id="proj-1"))

    label_calls = [str(c) for c in mock_ui.label.call_args_list]
    assert any("no tasks" in c.lower() for c in label_calls)


def test_tasks_page_renders_new_task_button():
    """tasks_page renders a '+ New Task' button."""
    from agents.dashboard_task_manager import setup_task_manager

    state = _make_mock_state()
    fake_app = MagicMock()

    fn, _ = _capture_page_fn(setup_task_manager, fake_app, state)

    mock_ui = _make_ui_mock()
    with patch("agents.dashboard_task_manager.ui", mock_ui):
        asyncio.run(fn(project_id="proj-1"))

    btn_calls = [str(c) for c in mock_ui.button.call_args_list]
    assert any("New Task" in c for c in btn_calls)


def test_tasks_page_renders_back_link():
    """tasks_page renders a back link to the project page."""
    from agents.dashboard_task_manager import setup_task_manager

    state = _make_mock_state()
    fake_app = MagicMock()

    fn, _ = _capture_page_fn(setup_task_manager, fake_app, state)

    mock_ui = _make_ui_mock()
    with patch("agents.dashboard_task_manager.ui", mock_ui):
        asyncio.run(fn(project_id="proj-1"))

    link_calls = [str(c) for c in mock_ui.link.call_args_list]
    assert any("/dashboard/project/proj-1" in c for c in link_calls)


# ---------------------------------------------------------------------------
# Page render — with tasks
# ---------------------------------------------------------------------------


def test_tasks_page_renders_task_names():
    """tasks_page renders the name of each task."""
    from agents.dashboard_task_manager import setup_task_manager

    tasks = [_make_sample_task(), _make_sample_task(id="task-2", name="Deploy")]
    state = _make_mock_state(tasks=tasks)
    fake_app = MagicMock()

    fn, _ = _capture_page_fn(setup_task_manager, fake_app, state)

    mock_ui = _make_ui_mock()
    with patch("agents.dashboard_task_manager.ui", mock_ui):
        asyncio.run(fn(project_id="proj-1"))

    label_calls = [str(c) for c in mock_ui.label.call_args_list]
    assert any("Fix bugs" in c for c in label_calls)
    assert any("Deploy" in c for c in label_calls)


# ---------------------------------------------------------------------------
# _build_task_edit_dialog — create
# ---------------------------------------------------------------------------


def _make_widget_mock(value):
    """A chainable widget mock whose .value is always `value`."""
    m = MagicMock()
    m.value = value
    m.classes.return_value = m
    m.props.return_value = m
    m.style.return_value = m
    return m


def test_build_task_edit_dialog_create_calls_create_task():
    """Saving a new-task dialog calls project_store.create_task with provided values."""
    from agents.dashboard_task_manager import _build_task_edit_dialog

    state = _make_mock_state()
    refresh_fn = MagicMock()

    mock_ui = _make_ui_mock()

    name_mock = _make_widget_mock("New Task")
    intent_mock = _make_widget_mock("Do something")
    trigger_mock = _make_widget_mock("manual")
    model_mock = _make_widget_mock("sonnet")
    budget_mock = _make_widget_mock(5.0)
    autonomy_mock = _make_widget_mock("pr-only")

    mock_ui.input.return_value = name_mock
    mock_ui.textarea.return_value = intent_mock
    mock_ui.select.side_effect = [trigger_mock, model_mock, autonomy_mock]
    mock_ui.number.return_value = budget_mock

    # Keep patch active so the save closure uses mock_ui.notify (not real NiceGUI)
    with patch("agents.dashboard_task_manager.ui", mock_ui):
        _build_task_edit_dialog("proj-1", state, refresh_fn, task=None)

        btn_calls = mock_ui.button.call_args_list
        save_call = [c for c in btn_calls if "Create" in str(c) or "Save" in str(c)]
        assert save_call, "Expected a Save/Create button"

        on_click = save_call[-1].kwargs.get("on_click")
        if on_click:
            asyncio.run(on_click())
            state.project_store.create_task.assert_called_once()
            call_kwargs = state.project_store.create_task.call_args.kwargs
            assert call_kwargs["project_id"] == "proj-1"
            assert call_kwargs["name"] == "New Task"


def test_build_task_edit_dialog_edit_calls_update_task():
    """Saving an edit-task dialog calls project_store.update_task."""
    from agents.dashboard_task_manager import _build_task_edit_dialog

    task = _make_sample_task()
    state = _make_mock_state()
    refresh_fn = MagicMock()

    mock_ui = _make_ui_mock()

    name_mock = _make_widget_mock("Updated Name")
    intent_mock = _make_widget_mock("Updated intent")
    trigger_mock = _make_widget_mock("schedule")
    model_mock = _make_widget_mock("opus")
    budget_mock = _make_widget_mock(10.0)
    autonomy_mock = _make_widget_mock("auto-merge")

    mock_ui.input.return_value = name_mock
    mock_ui.textarea.return_value = intent_mock
    mock_ui.select.side_effect = [trigger_mock, model_mock, autonomy_mock]
    mock_ui.number.return_value = budget_mock

    # Keep patch active so the save closure uses mock_ui.notify (not real NiceGUI)
    with patch("agents.dashboard_task_manager.ui", mock_ui):
        _build_task_edit_dialog("proj-1", state, refresh_fn, task=task)

        btn_calls = mock_ui.button.call_args_list
        save_call = [c for c in btn_calls if "Save" in str(c) or "Create" in str(c)]
        assert save_call

        on_click = save_call[-1].kwargs.get("on_click")
        if on_click:
            asyncio.run(on_click())
            state.project_store.update_task.assert_called_once()
            call_kwargs = state.project_store.update_task.call_args.kwargs
            assert call_kwargs["name"] == "Updated Name"


# ---------------------------------------------------------------------------
# get_source on ProjectStore
# ---------------------------------------------------------------------------


def test_get_source_returns_none_for_missing_id():
    """ProjectStore.get_source returns None when the source_id does not exist."""
    import tempfile
    from pathlib import Path
    from agents.project_store import ProjectStore

    with tempfile.TemporaryDirectory() as tmpdir:
        store = ProjectStore(Path(tmpdir) / "test.db")
        result = store.get_source("nonexistent-id")
        assert result is None


def test_get_source_returns_dict_for_existing_source():
    """ProjectStore.get_source returns a dict with source data when found."""
    import tempfile
    from pathlib import Path
    from agents.project_store import ProjectStore

    with tempfile.TemporaryDirectory() as tmpdir:
        store = ProjectStore(Path(tmpdir) / "test.db")
        store.create_project("proj-1", "My Project", "/tmp/repo")
        sid = store.create_source(
            project_id="proj-1",
            source_type="github",
            source_id="org/repo",
            source_name="org/repo",
        )
        result = store.get_source(sid)
        assert result is not None
        assert result["id"] == sid
        assert result["source_type"] == "github"
        assert result["source_id"] == "org/repo"
