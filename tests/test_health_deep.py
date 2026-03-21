from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agents.main import create_app


@pytest.fixture
def app(tmp_path):
    config_path = Path(__file__).parent.parent / "config.yaml"
    return create_app(
        config_path=config_path,
        projects_dir=tmp_path / "projects",
        data_dir=tmp_path / "data",
    )


@pytest.fixture
def client(app):
    return TestClient(app)


def test_health_returns_component_status(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "components" in data
    assert "db" in data["components"]
    assert data["components"]["db"] == "ok"


def test_health_reports_disk_status(client):
    response = client.get("/health")
    data = response.json()
    assert data["components"]["disk"] == "ok"
