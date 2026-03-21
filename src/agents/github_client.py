import httpx


class GitHubClient:
    """GitHub REST API client for polling project data."""

    BASE_URL = "https://api.github.com"

    def __init__(self, token: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15.0,
        )

    async def list_open_prs(self, repo_full_name: str) -> list[dict]:
        resp = await self._client.get(f"/repos/{repo_full_name}/pulls", params={"state": "open"})
        resp.raise_for_status()
        return resp.json()

    async def get_combined_status(self, repo_full_name: str, ref: str) -> dict:
        resp = await self._client.get(f"/repos/{repo_full_name}/commits/{ref}/status")
        resp.raise_for_status()
        return resp.json()

    async def get_check_runs(self, repo_full_name: str, ref: str) -> list[dict]:
        resp = await self._client.get(f"/repos/{repo_full_name}/commits/{ref}/check-runs")
        resp.raise_for_status()
        return resp.json().get("check_runs", [])

    async def list_branches(self, repo_full_name: str) -> list[dict]:
        resp = await self._client.get(f"/repos/{repo_full_name}/branches")
        resp.raise_for_status()
        return resp.json()

    async def search_repos(self, org: str, query: str) -> list[dict]:
        resp = await self._client.get("/search/repositories", params={"q": f"{query} org:{org}"})
        resp.raise_for_status()
        return resp.json().get("items", [])

    async def close(self) -> None:
        await self._client.aclose()
