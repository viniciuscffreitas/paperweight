import os

import pytest


def pytest_collection_modifyitems(config, items):
    """Skip tests marked with @pytest.mark.e2e when running in CI."""
    if os.environ.get("CI"):
        skip_ci = pytest.mark.skip(reason="E2E test requires local git + claude CLI")
        for item in items:
            if "e2e" in item.keywords:
                item.add_marker(skip_ci)
