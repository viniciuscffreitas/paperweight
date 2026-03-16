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

    async def fetch_teams(self) -> dict[str, str]:
        """Returns {team_name_lower: team_id} for all teams in the workspace."""
        query = """query { teams { nodes { id name } } }"""
        data = await self._graphql(query)
        nodes = data.get("data", {}).get("teams", {}).get("nodes", [])
        return {node["name"].lower(): node["id"] for node in nodes}

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

    async def post_comment(self, issue_id: str, body: str) -> None:
        query = """mutation($issueId: String!, $body: String!) {
            commentCreate(input: { issueId: $issueId, body: $body }) { success }
        }"""
        await self._graphql(query, {"issueId": issue_id, "body": body})

    async def update_status(self, issue_id: str, team_id: str, target_state_name: str) -> None:
        states = await self._get_team_states(team_id)
        state_id = states.get(target_state_name.lower())
        if not state_id:
            logger.warning("State '%s' not found for team %s", target_state_name, team_id)
            return
        query = """mutation($issueId: String!, $stateId: String!) {
            issueUpdate(id: $issueId, input: { stateId: $stateId }) { success }
        }"""
        await self._graphql(query, {"issueId": issue_id, "stateId": state_id})

    async def _get_team_states(self, team_id: str) -> dict[str, str]:
        if team_id in self._team_states_cache:
            return self._team_states_cache[team_id]
        query = """query($teamId: String!) {
            team(id: $teamId) { states { nodes { id name } } }
        }"""
        data = await self._graphql(query, {"teamId": team_id})
        nodes = data.get("data", {}).get("team", {}).get("states", {}).get("nodes", [])
        states = {node["name"].lower(): node["id"] for node in nodes}
        self._team_states_cache[team_id] = states
        return states

    async def remove_label(self, issue_id: str, label_name: str) -> None:
        data = await self._graphql(
            """query($id: String!) { issue(id: $id) { labels { nodes { id name } } } }""",
            {"id": issue_id},
        )
        nodes = data.get("data", {}).get("issue", {}).get("labels", {}).get("nodes", [])
        label_id = next((n["id"] for n in nodes if n["name"].lower() == label_name.lower()), None)
        if not label_id:
            logger.warning("Label '%s' not found on issue %s", label_name, issue_id)
            return
        await self._graphql(
            """mutation($issueId: String!, $labelId: String!) {
                issueRemoveLabel(id: $issueId, labelId: $labelId) { success }
            }""",
            {"issueId": issue_id, "labelId": label_id},
        )
