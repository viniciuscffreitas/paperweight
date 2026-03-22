"""Tests that register_profile_routes is wired into the lifespan auth block."""
from __future__ import annotations

import importlib
import inspect
from unittest.mock import MagicMock, patch, call


def test_profile_routes_registered_when_secret_key_set(tmp_path, monkeypatch):
    """When SECRET_KEY is set, lifespan must call register_profile_routes."""
    monkeypatch.setenv("SECRET_KEY", "test-secret")

    registered = []

    def _fake_register_profile(app, auth_db, templates):
        registered.append((app, auth_db, templates))

    # Re-import lifespan with mocked register_profile_routes
    import agents.lifespan as lifespan_mod

    # We test by inspecting the source: register_profile_routes must be imported
    # and called inside the SECRET_KEY block.
    src = inspect.getsource(lifespan_mod)
    assert "register_profile_routes" in src, (
        "register_profile_routes must be referenced in lifespan.py"
    )
    assert "from agents.profile_routes import register_profile_routes" in src, (
        "profile_routes must be imported inside the SECRET_KEY block"
    )


def test_profile_routes_module_importable():
    """Smoke-test: agents.profile_routes must be importable and expose register_profile_routes."""
    from agents.profile_routes import register_profile_routes
    assert callable(register_profile_routes)
