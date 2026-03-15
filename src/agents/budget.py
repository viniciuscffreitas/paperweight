from agents.config import BudgetConfig
from agents.history import HistoryDB
from agents.models import BudgetStatus


class BudgetManager:
    def __init__(self, config: BudgetConfig, history: HistoryDB) -> None:
        self.config = config
        self.history = history

    def get_status(self) -> BudgetStatus:
        spent = self.history.total_cost_today()
        return BudgetStatus(
            daily_limit_usd=self.config.daily_limit_usd,
            spent_today_usd=spent,
            warning_threshold_usd=self.config.warning_threshold_usd,
        )

    def can_afford(self, max_cost_usd: float) -> bool:
        status = self.get_status()
        if self.config.pause_on_limit and status.is_exceeded:
            return False
        return status.remaining_usd >= max_cost_usd
