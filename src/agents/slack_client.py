import httpx


class SlackBotClient:
    """Slack Bot API client for reading channels, messages, and searching."""

    BASE_URL = "https://slack.com/api"

    def __init__(self, bot_token: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={"Authorization": f"Bearer {bot_token}"},
            timeout=15.0,
        )

    async def list_channels(self, *, types: str = "public_channel,private_channel") -> list[dict]:
        resp = await self._client.get("/conversations.list", params={"types": types, "limit": 200})
        resp.raise_for_status()
        data = resp.json()
        return data.get("channels", [])

    async def search_channels_by_name(self, query: str) -> list[dict]:
        channels = await self.list_channels()
        query_lower = query.lower()
        return [ch for ch in channels if query_lower in ch.get("name", "").lower()]

    async def get_channel_history(self, channel_id: str, *, limit: int = 50, oldest: str | None = None) -> list[dict]:
        params: dict[str, object] = {"channel": channel_id, "limit": limit}
        if oldest:
            params["oldest"] = oldest
        resp = await self._client.get("/conversations.history", params=params)
        resp.raise_for_status()
        data = resp.json()
        return data.get("messages", [])

    async def search_messages(self, query: str, *, count: int = 20) -> list[dict]:
        resp = await self._client.get("/search.messages", params={"query": query, "count": count})
        resp.raise_for_status()
        data = resp.json()
        return data.get("messages", {}).get("matches", [])

    async def get_user_info(self, user_id: str) -> dict:
        resp = await self._client.get("/users.info", params={"user": user_id})
        resp.raise_for_status()
        return resp.json().get("user", {})

    async def close(self) -> None:
        await self._client.aclose()
