"""Discord Run Notifier — creates and edits messages for live run progress."""

import asyncio
import logging
import time

import httpx

logger = logging.getLogger(__name__)
DISCORD_API_URL = "https://discord.com/api/v10"


class DiscordRunNotifier:
    EDIT_INTERVAL_SECONDS = 2.0
    MAX_EVENTS_IN_EMBED = 40
    MAX_EMBED_LENGTH = 4000

    def __init__(self, bot_token: str) -> None:
        self.bot_token = bot_token
        self._last_edit_time: float = 0.0
        self._headers = {
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
        }

    async def _request(
        self, method: str, path: str, json: dict | None = None
    ) -> dict:
        url = f"{DISCORD_API_URL}{path}"
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method, url, json=json, headers=self._headers, timeout=10.0
            )
            if response.status_code == 429:
                retry_after = response.json().get("retry_after", 2.0)
                logger.warning(
                    "Discord rate limited, backing off %.1fs", retry_after
                )
                await asyncio.sleep(retry_after)
                response = await client.request(
                    method, url, json=json, headers=self._headers, timeout=10.0
                )
            response.raise_for_status()
            return response.json()

    def _build_embed(
        self,
        identifier: str,
        title: str,
        events: list[dict] | None = None,
        status: str = "running",
        pr_url: str | None = None,
        cost: float = 0.0,
        duration_s: float = 0.0,
        error: str | None = None,
    ) -> dict:
        color = {"running": 0x059669, "success": 0x4ADE80, "failure": 0xF87171}
        status_label = {
            "running": "⚡ Executando issue",
            "success": "✅ Issue resolvida",
            "failure": "❌ Falha",
        }

        lines: list[str] = []
        if events:
            display_events = events
            omitted = 0
            if len(events) > self.MAX_EVENTS_IN_EMBED:
                omitted = len(events) - self.MAX_EVENTS_IN_EMBED
                display_events = events[-self.MAX_EVENTS_IN_EMBED :]
            if omitted:
                lines.append(f"*... {omitted} earlier events omitted*")
            for evt in display_events:
                ts = time.strftime(
                    "%H:%M:%S", time.localtime(evt.get("timestamp", 0))
                )
                etype = evt.get("type", "unknown")
                content = evt.get("content", "")[:120]
                icon = {
                    "assistant": "💭",
                    "tool_use": "🔧",
                    "tool_result": "📋",
                    "system": "🚀",
                }.get(etype, "•")
                tool = evt.get("tool_name", "")
                label = f"**{tool}** {content}" if tool else content
                lines.append(f"`{ts}` {icon} {label}")

        desc_body = "\n".join(lines) if lines else "*aguardando eventos...*"
        if len(desc_body) > self.MAX_EMBED_LENGTH:
            desc_body = desc_body[-self.MAX_EMBED_LENGTH :]

        embed: dict = {
            "title": f"{status_label.get(status, status)} — {identifier}",
            "description": f"**{title}**\n\n{desc_body}",
            "color": color.get(status, 0x6B7280),
        }

        footer_parts: list[str] = []
        if duration_s > 0:
            m, s = divmod(int(duration_s), 60)
            if status == "success":
                icon = "✓"
            elif status == "failure":
                icon = "✗"
            else:
                icon = "⏱"
            footer_parts.append(f"{icon} {m}m{s:02d}s")
        if cost > 0:
            footer_parts.append(f"${cost:.2f}")
        if pr_url:
            embed["url"] = pr_url
        if error:
            embed["description"] += f"\n\n```\n{error[:500]}\n```"
        if footer_parts:
            embed["footer"] = {"text": " · ".join(footer_parts)}

        return embed

    async def create_run_message(
        self, channel_id: str, identifier: str, title: str
    ) -> str:
        embed = self._build_embed(identifier, title, status="running")
        data = await self._request(
            "POST", f"/channels/{channel_id}/messages", json={"embeds": [embed]}
        )
        return data["id"]

    async def update_run_message(
        self,
        channel_id: str,
        message_id: str,
        identifier: str,
        title: str,
        events: list[dict],
    ) -> None:
        now = time.time()
        if now - self._last_edit_time < self.EDIT_INTERVAL_SECONDS:
            return
        embed = self._build_embed(identifier, title, events=events, status="running")
        await self._request(
            "PATCH",
            f"/channels/{channel_id}/messages/{message_id}",
            json={"embeds": [embed]},
        )
        self._last_edit_time = now
