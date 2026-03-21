"""Tests for AppState — session_manager wiring."""

from pathlib import Path
from unittest.mock import MagicMock

from agents.app_state import AppState
from agents.session_manager import SessionManager


def _make_state(tmp_path: Path, with_session_manager: bool = True) -> AppState:
    executor = MagicMock()
    history = MagicMock()
    budget = MagicMock()
    notifier = MagicMock()

    session_manager = SessionManager(tmp_path / "sessions.db") if with_session_manager else None

    return AppState(
        projects={},
        executor=executor,
        history=history,
        budget=budget,
        notifier=notifier,
        github_secret="",
        linear_secret="",
        session_manager=session_manager,
    )


def test_app_state_stores_session_manager(tmp_path):
    state = _make_state(tmp_path, with_session_manager=True)
    assert state.session_manager is not None
    assert isinstance(state.session_manager, SessionManager)


def test_app_state_session_manager_defaults_to_none(tmp_path):
    state = _make_state(tmp_path, with_session_manager=False)
    assert state.session_manager is None


def test_app_state_session_manager_functional(tmp_path):
    state = _make_state(tmp_path, with_session_manager=True)
    session = state.session_manager.create_session("myproject")
    assert session.project == "myproject"
    assert session.status == "active"
    fetched = state.session_manager.get_session(session.id)
    assert fetched is not None
    assert fetched.id == session.id
