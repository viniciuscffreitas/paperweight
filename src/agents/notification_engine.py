"""Notification Engine — daily digests and real-time urgent alerts."""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)


class NotificationEngine:
    def __init__(
        self,
        *,
        store: Any,  # noqa: ANN401
        slack_notifier: Any = None,  # noqa: ANN401
        discord_notifier: Any = None,  # noqa: ANN401
    ) -> None:
        self.store = store
        self.slack_notifier = slack_notifier
        self.discord_notifier = discord_notifier

    def build_digest(self, project_id: str) -> str:
        project = self.store.get_project(project_id)
        if not project:
            return "Project not found"
        events = self.store.list_events(project_id, limit=200)
        if not events:
            return f"📋 {project['name']} — No activity in recent period."
        by_source = {}
        for e in events:
            by_source.setdefault(e["source"], []).append(e)
        lines = [f"📋 {project['name']} — Daily Summary\n"]
        for source, source_events in sorted(by_source.items()):
            type_counts = Counter(e["event_type"] for e in source_events)
            urgent_count = sum(1 for e in source_events if e["priority"] in ("urgent", "high"))
            summary_parts = [f"{count} {etype}" for etype, count in type_counts.items()]
            line = f"{source.capitalize()}: {', '.join(summary_parts)}"
            if urgent_count:
                line += f" ({urgent_count} urgent)"
            lines.append(line)
        urgent_events = [e for e in events if e["priority"] in ("urgent", "high")]
        if urgent_events:
            lines.append("\n⚠ Action needed:")
            for e in urgent_events[:5]:
                lines.append(f"  → {e['title']}")
        return "\n".join(lines)

    def check_urgent_events(self, project_id: str) -> list[dict]:
        events = self.store.list_events(project_id, limit=50)
        return [e for e in events if e["priority"] in ("urgent", "high")]

    async def send_digest(self, project_id: str) -> None:
        rules = self.store.list_notification_rules(project_id)
        digest_rules = [r for r in rules if r["rule_type"] == "digest" and r.get("enabled", True)]
        if not digest_rules:
            return
        digest_text = self.build_digest(project_id)
        for rule in digest_rules:
            try:
                if rule["channel"] == "slack" and self.slack_notifier:
                    await self.slack_notifier.send_text(digest_text)
                elif rule["channel"] == "discord" and self.discord_notifier:
                    await self.discord_notifier.create_run_message(
                        rule["channel_target"], project_id, digest_text[:200]
                    )
                self.store.log_notification(
                    project_id=project_id,
                    rule_id=rule["id"],
                    event_id="digest",
                    channel=rule["channel"],
                    content=digest_text[:500],
                )
            except Exception:
                logger.exception("Failed to send digest for %s", project_id)

    async def send_urgent_alert(self, project_id: str, event: dict) -> None:
        rules = self.store.list_notification_rules(project_id)
        alert_rules = [r for r in rules if r["rule_type"] == "alert" and r.get("enabled", True)]
        if not alert_rules:
            return
        event_id = event.get("id", event.get("source_item_id", ""))
        # Check cooldown per alert rule using the first alert rule as representative
        first_rule = alert_rules[0]
        if self.store.was_recently_notified(
            project_id=project_id,
            rule_id=first_rule["id"],
            event_id=event_id,
            cooldown_minutes=30,
        ):
            return
        alert_text = f"🚨 {event.get('title', 'Unknown event')}"
        if event.get("url"):
            alert_text += f"\n{event['url']}"
        for rule in alert_rules:
            try:
                if rule["channel"] == "slack" and self.slack_notifier:
                    await self.slack_notifier.send_text(alert_text)
                self.store.log_notification(
                    project_id=project_id,
                    rule_id=rule["id"],
                    event_id=event_id,
                    channel=rule["channel"],
                    content=alert_text[:500],
                )
            except Exception:
                logger.exception("Failed to send alert for %s", project_id)

    def build_overnight_digest(self, history: object, hours: int = 12) -> str:
        """Build a summary of what happened in the last N hours."""
        from datetime import UTC, datetime, timedelta

        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        overnight_runs = history.list_runs_since(cutoff)

        if not overnight_runs:
            return ""

        successes = [r for r in overnight_runs if r.status == "success"]
        failures = [r for r in overnight_runs if r.status in ("failure", "timeout")]
        prs = [r for r in overnight_runs if r.pr_url]
        total_cost = sum(r.cost_usd or 0 for r in overnight_runs)

        lines = ["📋 Overnight Summary\n"]
        n, s, f = len(overnight_runs), len(successes), len(failures)
        lines.append(f"  {n} runs | {s} succeeded | {f} failed")
        lines.append(f"  Cost: ${total_cost:.2f}")

        if prs:
            lines.append(f"\n  PRs created ({len(prs)}):")
            for r in prs:
                lines.append(f"    → {r.pr_url}")

        if failures:
            lines.append(f"\n  Failures ({len(failures)}):")
            for r in failures[:5]:
                error = (r.error_message or "unknown")[:80]
                lines.append(f"    ✗ {r.project}/{r.task}: {error}")

        return "\n".join(lines)

    async def process_new_events(self, project_id: str) -> None:
        urgent = self.check_urgent_events(project_id)
        for event in urgent:
            await self.send_urgent_alert(project_id, event)
