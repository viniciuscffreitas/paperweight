"""Tests for aggregator normalizers and AggregatorService."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.aggregator import (
    AggregatorService,
    normalize_github_pr,
    normalize_linear_issue,
    normalize_slack_message,
)
from agents.project_store import ProjectStore


# ---------------------------------------------------------------------------
# Normalizer tests
# ---------------------------------------------------------------------------


class TestNormalizeLinearIssue:
    def test_basic_normalization(self):
        raw = {
            "id": "abc123",
            "identifier": "ENG-42",
            "title": "Fix the bug",
            "description": "Some details",
            "state": {"name": "In Progress"},
            "assignee": {"name": "Alice"},
            "url": "https://linear.app/issue/ENG-42",
            "priority": 2,
        }
        result = normalize_linear_issue(raw, project_id="proj-1")

        assert result["project_id"] == "proj-1"
        assert result["source"] == "linear"
        assert result["event_type"] == "issue_in_progress"
        assert result["title"] == "[ENG-42] Fix the bug"
        assert result["body"] == "Some details"
        assert result["author"] == "Alice"
        assert result["url"] == "https://linear.app/issue/ENG-42"
        assert result["priority"] == "high"
        assert result["source_item_id"] == "linear:abc123"
        assert result["raw_data"] == raw

    def test_priority_urgent(self):
        raw = {
            "id": "u1",
            "identifier": "ENG-1",
            "title": "Urgent",
            "state": {"name": "Todo"},
            "priority": 1,
        }
        result = normalize_linear_issue(raw, project_id="p")
        assert result["priority"] == "urgent"

    def test_priority_low(self):
        raw = {
            "id": "l1",
            "identifier": "ENG-2",
            "title": "Low",
            "state": {"name": "Todo"},
            "priority": 4,
        }
        result = normalize_linear_issue(raw, project_id="p")
        assert result["priority"] == "low"

    def test_source_item_id_format(self):
        raw = {"id": "xyz789", "title": "No identifier", "state": {"name": "Done"}, "priority": 0}
        result = normalize_linear_issue(raw, project_id="p")
        assert result["source_item_id"] == "linear:xyz789"

    def test_no_identifier_title_no_brackets(self):
        raw = {"id": "x", "title": "Plain title", "state": {"name": "Done"}, "priority": 0}
        result = normalize_linear_issue(raw, project_id="p")
        assert result["title"] == "Plain title"

    def test_no_assignee(self):
        raw = {"id": "x", "title": "T", "state": {"name": "Done"}, "priority": 0, "assignee": None}
        result = normalize_linear_issue(raw, project_id="p")
        assert result["author"] == ""


class TestNormalizeGithubPr:
    def test_basic(self):
        raw = {
            "number": 99,
            "title": "Add feature",
            "body": "PR body",
            "state": "open",
            "user": {"login": "bob"},
            "html_url": "https://github.com/org/repo/pull/99",
            "head": {"sha": "abc"},
        }
        result = normalize_github_pr(raw, project_id="proj-1")

        assert result["project_id"] == "proj-1"
        assert result["source"] == "github"
        assert result["event_type"] == "pr_open"
        assert result["title"] == "PR #99: Add feature"
        assert result["body"] == "PR body"
        assert result["author"] == "bob"
        assert result["url"] == "https://github.com/org/repo/pull/99"
        assert result["priority"] == "none"
        assert result["source_item_id"] == "github:pr:99"
        assert result["raw_data"] == raw

    def test_author(self):
        raw = {"number": 1, "title": "T", "state": "open", "user": {"login": "charlie"}}
        result = normalize_github_pr(raw, project_id="p")
        assert result["author"] == "charlie"

    def test_source_item_id(self):
        raw = {"number": 42, "title": "T", "state": "open"}
        result = normalize_github_pr(raw, project_id="p")
        assert result["source_item_id"] == "github:pr:42"

    def test_ci_failing_priority_high(self):
        raw = {"number": 5, "title": "Broken", "state": "open"}
        result = normalize_github_pr(raw, project_id="p", ci_status="failure")
        assert result["priority"] == "high"

    def test_ci_success_priority_none(self):
        raw = {"number": 5, "title": "Good", "state": "open"}
        result = normalize_github_pr(raw, project_id="p", ci_status="success")
        assert result["priority"] == "none"


class TestNormalizeSlackMessage:
    def test_basic(self):
        raw = {"text": "Hello world", "ts": "1700000000.123456", "user": "U123"}
        result = normalize_slack_message(raw, project_id="proj-1", channel_name="general")

        assert result["project_id"] == "proj-1"
        assert result["source"] == "slack"
        assert result["event_type"] == "message"
        assert result["title"].startswith("general:")
        assert "Hello world" in result["title"]
        assert result["body"] == "Hello world"
        assert result["priority"] == "none"
        assert result["source_item_id"] == "slack:1700000000.123456"
        assert result["raw_data"] == raw

    def test_channel_name_in_title(self):
        raw = {"text": "hi", "ts": "1700000000.0"}
        result = normalize_slack_message(raw, project_id="p", channel_name="dev-alerts")
        assert result["title"].startswith("dev-alerts:")

    def test_source_item_id(self):
        raw = {"text": "x", "ts": "1699999999.999"}
        result = normalize_slack_message(raw, project_id="p", channel_name="c")
        assert result["source_item_id"] == "slack:1699999999.999"

    def test_mention_priority_high(self):
        raw = {"text": "Hey <@UBOT123> check this", "ts": "1700000000.0"}
        result = normalize_slack_message(
            raw, project_id="p", channel_name="c", my_user_id="UBOT123"
        )
        assert result["priority"] == "high"

    def test_no_mention_priority_none(self):
        raw = {"text": "general chatter", "ts": "1700000000.0"}
        result = normalize_slack_message(
            raw, project_id="p", channel_name="c", my_user_id="UBOT123"
        )
        assert result["priority"] == "none"

    def test_user_name_in_author(self):
        raw = {"text": "hi", "ts": "1700000000.0"}
        result = normalize_slack_message(
            raw, project_id="p", channel_name="c", user_name="dave"
        )
        assert result["author"] == "dave"


# ---------------------------------------------------------------------------
# AggregatorService tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> ProjectStore:
    s = ProjectStore(tmp_path / "test.db")
    s.create_project("proj-1", "Test Project", "/tmp/repo")
    return s


class TestPollLinear:
    @pytest.mark.asyncio
    async def test_poll_linear_issues(self, store: ProjectStore):
        store.create_source(
            "proj-1",
            source_type="linear",
            source_id="team-abc",
            source_name="Engineering",
            config={"team_id": "team-abc"},
        )

        linear_client = MagicMock()
        linear_client.fetch_team_issues = AsyncMock(
            return_value=[
                {
                    "id": "issue-1",
                    "identifier": "ENG-1",
                    "title": "Fix crash",
                    "description": "desc",
                    "state": {"name": "In Progress"},
                    "assignee": {"name": "Alice"},
                    "url": "https://linear.app/issue/ENG-1",
                    "priority": 2,
                }
            ]
        )

        svc = AggregatorService(
            store=store,
            linear_client=linear_client,
        )

        await svc.poll_linear("proj-1")

        events = store.list_events("proj-1", source="linear")
        assert len(events) == 1
        assert events[0]["title"] == "[ENG-1] Fix crash"
        assert events[0]["source_item_id"] == "linear:issue-1"

    @pytest.mark.asyncio
    async def test_poll_linear_no_sources(self, store: ProjectStore):
        linear_client = MagicMock()
        linear_client.fetch_team_issues = AsyncMock(return_value=[])

        svc = AggregatorService(store=store, linear_client=linear_client)
        await svc.poll_linear("proj-1")

        events = store.list_events("proj-1", source="linear")
        assert len(events) == 0
        linear_client.fetch_team_issues.assert_not_called()


class TestPollGithub:
    @pytest.mark.asyncio
    async def test_poll_github_prs(self, store: ProjectStore):
        store.create_source(
            "proj-1",
            source_type="github",
            source_id="org/repo",
            source_name="Main Repo",
            config={"repo": "org/repo"},
        )

        github_client = MagicMock()
        github_client.list_open_prs = AsyncMock(
            return_value=[
                {
                    "number": 7,
                    "title": "Add widget",
                    "body": "body text",
                    "state": "open",
                    "user": {"login": "eve"},
                    "html_url": "https://github.com/org/repo/pull/7",
                    "head": {"sha": "deadbeef"},
                }
            ]
        )
        github_client.get_combined_status = AsyncMock(
            return_value={"state": "success"}
        )

        svc = AggregatorService(store=store, github_client=github_client)
        await svc.poll_github("proj-1")

        events = store.list_events("proj-1", source="github")
        assert len(events) == 1
        assert events[0]["title"] == "PR #7: Add widget"
        assert events[0]["source_item_id"] == "github:pr:7"


class TestPollSlack:
    @pytest.mark.asyncio
    async def test_poll_slack_messages(self, store: ProjectStore):
        store.create_source(
            "proj-1",
            source_type="slack",
            source_id="C12345",
            source_name="dev-chat",
            config={"channel_id": "C12345"},
        )

        slack_client = MagicMock()
        slack_client.get_channel_history = AsyncMock(
            return_value=[
                {"text": "Deploy done", "ts": "1700000001.000", "user": "U999"},
            ]
        )
        slack_client.get_user_info = AsyncMock(
            return_value={"real_name": "Frank", "id": "U999"}
        )

        svc = AggregatorService(store=store, slack_client=slack_client)
        await svc.poll_slack("proj-1")

        events = store.list_events("proj-1", source="slack")
        assert len(events) == 1
        assert "dev-chat" in events[0]["title"]
        assert events[0]["source_item_id"] == "slack:1700000001.000"


class TestSourceHealth:
    def test_healthy_with_no_failures(self, store: ProjectStore):
        svc = AggregatorService(store=store)
        assert svc.get_source_health("linear:team-abc") == "healthy"

    def test_degraded_with_few_failures(self, store: ProjectStore):
        svc = AggregatorService(store=store)
        svc._failure_counts["linear:team-abc"] = 2
        assert svc.get_source_health("linear:team-abc") == "degraded"

    def test_failing_with_many_failures(self, store: ProjectStore):
        svc = AggregatorService(store=store)
        svc._failure_counts["linear:team-abc"] = 5
        assert svc.get_source_health("linear:team-abc") == "failing"
