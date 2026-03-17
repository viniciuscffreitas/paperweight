"""Aggregator service: normalizers and polling loop."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_LINEAR_PRIORITY = {0: "none", 1: "urgent", 2: "high", 3: "medium", 4: "low"}


# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------


def normalize_linear_issue(raw: dict, *, project_id: str) -> dict:
    """Convert a raw Linear issue dict into a normalized event dict."""
    identifier = raw.get("identifier", "")
    title = raw.get("title", "")
    priority_num = raw.get("priority", 0)
    return {
        "project_id": project_id,
        "source": "linear",
        "event_type": (
            f"issue_{raw.get('state', {}).get('name', 'unknown').lower().replace(' ', '_')}"
        ),
        "title": f"[{identifier}] {title}" if identifier else title,
        "body": raw.get("description", ""),
        "author": raw.get("assignee", {}).get("name", "") if raw.get("assignee") else "",
        "url": raw.get("url", ""),
        "priority": _LINEAR_PRIORITY.get(priority_num, "none"),
        "timestamp": datetime.now(UTC).isoformat(),
        "source_item_id": f"linear:{raw['id']}",
        "raw_data": raw,
    }


def normalize_github_pr(raw: dict, *, project_id: str, ci_status: str = "unknown") -> dict:
    """Convert a raw GitHub PR dict into a normalized event dict."""
    number = raw["number"]
    priority = "high" if ci_status == "failure" else "none"
    return {
        "project_id": project_id,
        "source": "github",
        "event_type": f"pr_{raw.get('state', 'open')}",
        "title": f"PR #{number}: {raw.get('title', '')}",
        "body": raw.get("body", "") or "",
        "author": raw.get("user", {}).get("login", ""),
        "url": raw.get("html_url", ""),
        "priority": priority,
        "timestamp": datetime.now(UTC).isoformat(),
        "source_item_id": f"github:pr:{number}",
        "raw_data": raw,
    }


def normalize_slack_message(
    raw: dict,
    *,
    project_id: str,
    channel_name: str,
    user_name: str = "",
    my_user_id: str | None = None,
) -> dict:
    """Convert a raw Slack message dict into a normalized event dict."""
    text = raw.get("text", "")
    priority = "high" if my_user_id and f"<@{my_user_id}>" in text else "none"
    ts = raw.get("ts", "")
    try:
        dt = datetime.fromtimestamp(float(ts), tz=UTC)
        timestamp = dt.isoformat()
    except (ValueError, TypeError):
        timestamp = datetime.now(UTC).isoformat()
    return {
        "project_id": project_id,
        "source": "slack",
        "event_type": "message",
        "title": f"{channel_name}: {text[:120]}",
        "body": text,
        "author": user_name,
        "url": "",
        "priority": priority,
        "timestamp": timestamp,
        "source_item_id": f"slack:{ts}",
        "raw_data": raw,
    }


# ---------------------------------------------------------------------------
# AggregatorService
# ---------------------------------------------------------------------------


class AggregatorService:
    """Polls configured sources and upserts normalized events into the store."""

    def __init__(
        self,
        *,
        store: Any,  # noqa: ANN401
        linear_client: Any = None,  # noqa: ANN401
        github_client: Any = None,  # noqa: ANN401
        slack_client: Any = None,  # noqa: ANN401
    ) -> None:
        self.store = store
        self.linear_client = linear_client
        self.github_client = github_client
        self.slack_client = slack_client
        self._failure_counts: dict[str, int] = {}
        self._running = False

    def _upsert(self, event: dict) -> None:
        self.store.upsert_event(
            project_id=event["project_id"],
            source=event["source"],
            event_type=event["event_type"],
            title=event["title"],
            source_item_id=event["source_item_id"],
            timestamp=event["timestamp"],
            body=event.get("body", ""),
            author=event.get("author", ""),
            url=event.get("url", ""),
            priority=event.get("priority", "none"),
            raw_data=event.get("raw_data"),
        )

    async def poll_linear(self, project_id: str) -> None:
        """Poll all linear sources for the given project."""
        if self.linear_client is None:
            return
        sources = [
            s for s in self.store.list_sources(project_id) if s["source_type"] == "linear"
        ]
        for source in sources:
            source_key = f"linear:{source['source_id']}"
            raw_cfg = source["config"]
            config = json.loads(raw_cfg) if isinstance(raw_cfg, str) else raw_cfg
            team_id = config.get("team_id", source["source_id"])
            try:
                issues = await self.linear_client.fetch_team_issues(team_id)
                for raw in issues:
                    event = normalize_linear_issue(raw, project_id=project_id)
                    self._upsert(event)
                self._failure_counts[source_key] = 0
            except Exception:
                logger.exception("Failed to poll Linear source %s", source_key)
                self._failure_counts[source_key] = self._failure_counts.get(source_key, 0) + 1

    async def poll_github(self, project_id: str) -> None:
        """Poll all GitHub sources for the given project."""
        if self.github_client is None:
            return
        sources = [
            s for s in self.store.list_sources(project_id) if s["source_type"] == "github"
        ]
        for source in sources:
            raw_cfg = source["config"]
            config = json.loads(raw_cfg) if isinstance(raw_cfg, str) else raw_cfg
            repo = config.get("repo", source["source_id"])
            source_key = f"github:{repo}"
            try:
                prs = await self.github_client.list_open_prs(repo)
                for raw in prs:
                    sha = (raw.get("head") or {}).get("sha", "HEAD")
                    status_data = await self.github_client.get_combined_status(repo, sha)
                    ci_status = status_data.get("state", "unknown")
                    event = normalize_github_pr(raw, project_id=project_id, ci_status=ci_status)
                    self._upsert(event)
                self._failure_counts[source_key] = 0
            except Exception:
                logger.exception("Failed to poll GitHub source %s", source_key)
                self._failure_counts[source_key] = self._failure_counts.get(source_key, 0) + 1

    async def poll_slack(self, project_id: str) -> None:
        """Poll all Slack sources for the given project."""
        if self.slack_client is None:
            return
        sources = [
            s for s in self.store.list_sources(project_id) if s["source_type"] == "slack"
        ]
        for source in sources:
            raw_cfg = source["config"]
            config = json.loads(raw_cfg) if isinstance(raw_cfg, str) else raw_cfg
            channel_id = config.get("channel_id", source["source_id"])
            channel_name = source["source_name"]
            source_key = f"slack:{channel_id}"
            try:
                messages = await self.slack_client.get_channel_history(channel_id)
                for raw in messages:
                    user_id = raw.get("user", "")
                    user_name = ""
                    if user_id:
                        try:
                            user_info = await self.slack_client.get_user_info(user_id)
                            user_name = user_info.get("real_name", "") or user_info.get("name", "")
                        except Exception:
                            logger.warning("Could not fetch Slack user info for %s", user_id)
                    event = normalize_slack_message(
                        raw,
                        project_id=project_id,
                        channel_name=channel_name,
                        user_name=user_name,
                    )
                    self._upsert(event)
                self._failure_counts[source_key] = 0
            except Exception:
                logger.exception("Failed to poll Slack source %s", source_key)
                self._failure_counts[source_key] = self._failure_counts.get(source_key, 0) + 1

    async def poll_all(self, project_id: str) -> None:
        """Poll all sources concurrently for the given project."""
        await asyncio.gather(
            self.poll_linear(project_id),
            self.poll_github(project_id),
            self.poll_slack(project_id),
            return_exceptions=True,
        )

    def get_source_health(self, source_key: str) -> str:
        """Return health status for a source key based on consecutive failure count."""
        count = self._failure_counts.get(source_key, 0)
        if count == 0:
            return "healthy"
        if count < 3:
            return "degraded"
        return "failing"

    async def start(self, poll_interval_seconds: int = 300) -> None:
        """Start the polling loop. Runs indefinitely until stop() is called."""
        self._running = True
        while self._running:
            for project in self.store.list_projects():
                try:
                    await self.poll_all(project["id"])
                except Exception:
                    logger.exception("Aggregator error for project %s", project["id"])
            await asyncio.sleep(poll_interval_seconds)

    def stop(self) -> None:
        """Signal the polling loop to stop after the current iteration."""
        self._running = False
