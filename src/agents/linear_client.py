import logging

import httpx

logger = logging.getLogger(__name__)
LINEAR_API_URL = "https://api.linear.app/graphql"


class LinearClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._team_states_cache: dict[str, dict[str, str]] = {}

    async def _graphql(self, query: str, variables: dict | None = None) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                LINEAR_API_URL,
                json={"query": query, "variables": variables or {}},
                headers={"Authorization": self.api_key, "Content-Type": "application/json"},
                timeout=15.0,
            )
            response.raise_for_status()
            return response.json()

    async def fetch_issue(self, issue_id: str) -> dict:
        query = """
        query($id: String!) {
            issue(id: $id) {
                id identifier title description
                state { name }
                labels { nodes { name id } }
            }
        }
        """
        data = await self._graphql(query, {"id": issue_id})
        issue = data.get("data", {}).get("issue", {})
        return {
            "id": issue.get("id", ""),
            "identifier": issue.get("identifier", ""),
            "title": issue.get("title", ""),
            "description": issue.get("description", ""),
            "state": issue.get("state", {}).get("name", ""),
            "labels": [n.get("name", "") for n in issue.get("labels", {}).get("nodes", [])],
        }
