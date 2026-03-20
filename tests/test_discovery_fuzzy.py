import pytest
from agents.discovery import auto_discover_project_ids
from agents.models import ProjectConfig, TaskConfig

@pytest.fixture
def dummy_project():
    return ProjectConfig(
        name="paperweight",
        repo="/tmp/test",
        tasks={"test": TaskConfig(description="t", intent="t")},
    )

class FakeLinearClient:
    async def fetch_teams(self):
        return {"pw team": "team-123"}

@pytest.mark.asyncio
async def test_fuzzy_discovery_no_exact_match(dummy_project):
    projects = {"paperweight": dummy_project}
    await auto_discover_project_ids(projects, FakeLinearClient(), None, "")
    assert dummy_project.linear_team_id == ""

class FakeLinearClientSubstring:
    async def fetch_teams(self):
        return {"paperweight-dev": "team-456"}

@pytest.mark.asyncio
async def test_fuzzy_discovery_substring_match(dummy_project):
    projects = {"paperweight": dummy_project}
    await auto_discover_project_ids(projects, FakeLinearClientSubstring(), None, "")
    assert dummy_project.linear_team_id == "team-456"
