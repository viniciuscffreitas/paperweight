"""Metrics collector — aggregates run history into trend data."""
from agents.history import HistoryDB


def collect_metrics(history: HistoryDB, days: int = 7) -> dict:
    cost_days = history.cost_by_day(days)
    status_counts = history.runs_by_status(days)
    avg_dur = history.avg_duration_seconds(days)
    total_runs = sum(status_counts.values())
    success_count = status_counts.get("success", 0)
    success_rate = (success_count / total_runs * 100) if total_runs > 0 else 0.0
    total_cost = sum(d["cost"] for d in cost_days)
    return {
        "total_runs_7d": total_runs,
        "success_rate_7d": round(success_rate, 2),
        "total_cost_7d": round(total_cost, 2),
        "avg_duration_seconds": round(avg_dur, 1),
        "cost_by_day": cost_days,
        "runs_by_status": status_counts,
    }
