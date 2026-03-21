from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.github_client import GitHubClient


@pytest.fixture
def client() -> GitHubClient:
    return GitHubClient(token="test-token")


@pytest.mark.asyncio
async def test_list_open_prs(client: GitHubClient) -> None:
    mock_response = MagicMock()
    mock_response.json.return_value = [
        {
            "number": 1,
            "title": "Fix bug",
            "state": "open",
            "html_url": "https://github.com/org/repo/pull/1",
            "user": {"login": "dev1"},
            "head": {"ref": "fix-bug"},
        },
    ]
    mock_response.raise_for_status = MagicMock()
    with patch.object(client._client, "get", new=AsyncMock(return_value=mock_response)):
        prs = await client.list_open_prs("org/repo")
    assert len(prs) == 1
    assert prs[0]["number"] == 1


@pytest.mark.asyncio
async def test_get_check_status(client: GitHubClient) -> None:
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "state": "success",
        "statuses": [{"state": "success", "context": "ci/test"}],
    }
    mock_response.raise_for_status = MagicMock()
    with patch.object(client._client, "get", new=AsyncMock(return_value=mock_response)):
        status = await client.get_combined_status("org/repo", "abc123")
    assert status["state"] == "success"


@pytest.mark.asyncio
async def test_list_branches(client: GitHubClient) -> None:
    mock_response = MagicMock()
    mock_response.json.return_value = [
        {"name": "main", "commit": {"sha": "abc123"}},
        {"name": "feature", "commit": {"sha": "def456"}},
    ]
    mock_response.raise_for_status = MagicMock()
    with patch.object(client._client, "get", new=AsyncMock(return_value=mock_response)):
        branches = await client.list_branches("org/repo")
    assert len(branches) == 2


@pytest.mark.asyncio
async def test_search_repos(client: GitHubClient) -> None:
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "items": [
            {"full_name": "org/momease-app", "name": "momease-app"},
            {"full_name": "org/momease-api", "name": "momease-api"},
        ]
    }
    mock_response.raise_for_status = MagicMock()
    with patch.object(client._client, "get", new=AsyncMock(return_value=mock_response)):
        repos = await client.search_repos("org", "momease")
    assert len(repos) == 2
