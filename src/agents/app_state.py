"""Shared application state container."""
import asyncio
from typing import TYPE_CHECKING

from fastapi import WebSocket

from agents.budget import BudgetManager
from agents.executor import Executor
from agents.history import HistoryDB
from agents.models import ProjectConfig
from agents.notifier import Notifier
from agents.project_store import ProjectStore
from agents.session_manager import SessionManager

if TYPE_CHECKING:
    from agents.aggregator import AggregatorService
    from agents.coordination.broker import CoordinationBroker
    from agents.github_client import GitHubClient
    from agents.slack_client import SlackBotClient
    from agents.task_store import TaskStore


class AppState:
    def __init__(
        self,
        projects: dict[str, ProjectConfig],
        executor: Executor,
        history: HistoryDB,
        budget: BudgetManager,
        notifier: Notifier,
        github_secret: str,
        linear_secret: str,
        project_store: ProjectStore | None = None,
        github_client: "GitHubClient | None" = None,
        slack_bot_client: "SlackBotClient | None" = None,
        aggregator: "AggregatorService | None" = None,
        broker: "CoordinationBroker | None" = None,
        session_manager: SessionManager | None = None,
        task_store: "TaskStore | None" = None,
    ) -> None:
        self.projects = projects
        self.executor = executor
        self.history = history
        self.budget = budget
        self.notifier = notifier
        self.github_secret = github_secret
        self.linear_secret = linear_secret
        self.project_store = project_store
        self.github_client = github_client
        self.slack_bot_client = slack_bot_client
        self.aggregator = aggregator
        self.broker = broker
        self.session_manager = session_manager
        self.task_store = task_store
        self._semaphore: asyncio.Semaphore | None = None
        self._repo_semaphores: dict[str, asyncio.Semaphore] = {}
        self.ws_clients: dict[str, set[WebSocket]] = {}
        self.ws_global_clients: set[WebSocket] = set()
        self.stream_queues: list[asyncio.Queue] = []
        self.run_events: dict[str, list[dict]] = {}
        self._agent_issue_seen: dict[str, float] = {}  # issue_id → timestamp (dedup cooldown)

    def get_semaphore(self, max_concurrent: int) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(max_concurrent)
        return self._semaphore

    def get_repo_semaphore(self, repo: str) -> asyncio.Semaphore:
        if repo not in self._repo_semaphores:
            self._repo_semaphores[repo] = asyncio.Semaphore(2)
        return self._repo_semaphores[repo]
