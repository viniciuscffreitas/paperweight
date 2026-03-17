import logging

import httpx

from agents.models import BudgetStatus, RunRecord, RunStatus

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def format_message(self, run: RunRecord | None) -> str:
        if run is None:
            return ""
        duration = ""
        if run.started_at and run.finished_at:
            delta = run.finished_at - run.started_at
            minutes, seconds = divmod(int(delta.total_seconds()), 60)
            duration = f"{minutes}m{seconds:02d}s"
        cost = f"${run.cost_usd:.2f}" if run.cost_usd is not None else "N/A"
        turns = str(run.num_turns) if run.num_turns is not None else "N/A"
        if run.status == RunStatus.SUCCESS:
            pr_line = f"\n   PR: {run.pr_url}" if run.pr_url else ""
            return (
                f"[{run.project}] {run.task} completed{pr_line}"
                f"\n   Cost: {cost} | Turns: {turns} | Duration: {duration}"
            )
        error_line = f"\n   Error: {run.error_message}" if run.error_message else ""
        return (
            f"[{run.project}] {run.task} {run.status}{error_line}"
            f"\n   Cost: {cost} | Turns: {turns} | Duration: {duration}"
        )

    def format_budget_warning(self, status: BudgetStatus) -> str:
        pct = int(status.spent_today_usd / status.daily_limit_usd * 100)
        return (
            f"Budget warning: ${status.spent_today_usd:.2f} / "
            f"${status.daily_limit_usd:.2f} used today ({pct}%)"
        )

    async def send_text(self, text: str) -> None:
        await self._send(text)

    async def send_run_notification(self, run: RunRecord) -> None:
        msg = self.format_message(run)
        await self._send(msg)

    async def send_budget_warning(self, status: BudgetStatus) -> None:
        msg = self.format_budget_warning(status)
        await self._send(msg)

    async def _send(self, text: str) -> None:
        if not self.webhook_url:
            logger.debug("No Slack webhook URL configured, skipping notification")
            return
        try:
            async with httpx.AsyncClient() as client:
                await client.post(self.webhook_url, json={"text": text}, timeout=10)
        except httpx.HTTPError:
            logger.exception("Failed to send Slack notification")
