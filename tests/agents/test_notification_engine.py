from unittest.mock import AsyncMock

import pytest

from agents.notification_engine import NotificationEngine
from agents.project_store import ProjectStore


@pytest.fixture
def store(tmp_path):
    s = ProjectStore(tmp_path / "test.db")
    s.create_project(id="p1", name="P1", repo_path="/r")
    return s


@pytest.fixture
def engine(store):
    return NotificationEngine(
        store=store,
        slack_notifier=AsyncMock(send_text=AsyncMock()),
        discord_notifier=AsyncMock(),
    )


def test_build_digest(engine, store):
    store.upsert_event(
        project_id="p1",
        source="linear",
        event_type="issue_created",
        title="Bug fix",
        source_item_id="L1",
        timestamp="2026-03-16T10:00:00Z",
        priority="urgent",
    )
    store.upsert_event(
        project_id="p1",
        source="github",
        event_type="pr_open",
        title="PR #1",
        source_item_id="G1",
        timestamp="2026-03-16T10:01:00Z",
    )
    digest = engine.build_digest("p1")
    assert "P1" in digest
    assert "Bug fix" in digest or "1" in digest


def test_build_digest_empty(engine):
    digest = engine.build_digest("p1")
    assert "No activity" in digest or "no" in digest.lower()


def test_build_digest_unknown_project(engine):
    digest = engine.build_digest("nonexistent")
    assert "not found" in digest.lower()


def test_build_digest_includes_source_summary(engine, store):
    store.upsert_event(
        project_id="p1",
        source="linear",
        event_type="issue_created",
        title="T1",
        source_item_id="L1",
        timestamp="2026-03-16T10:00:00Z",
        priority="high",
    )
    store.upsert_event(
        project_id="p1",
        source="linear",
        event_type="issue_created",
        title="T2",
        source_item_id="L2",
        timestamp="2026-03-16T10:01:00Z",
        priority="none",
    )
    digest = engine.build_digest("p1")
    assert "Linear" in digest
    assert "urgent" in digest or "1" in digest


def test_check_urgent_alerts(engine, store):
    store.upsert_event(
        project_id="p1",
        source="linear",
        event_type="issue_created",
        title="Critical bug",
        source_item_id="L1",
        timestamp="2026-03-16T10:00:00Z",
        priority="urgent",
    )
    alerts = engine.check_urgent_events("p1")
    assert len(alerts) == 1
    assert alerts[0]["title"] == "Critical bug"


def test_check_urgent_alerts_includes_high(engine, store):
    store.upsert_event(
        project_id="p1",
        source="linear",
        event_type="issue_created",
        title="High prio",
        source_item_id="L1",
        timestamp="2026-03-16T10:00:00Z",
        priority="high",
    )
    alerts = engine.check_urgent_events("p1")
    assert len(alerts) == 1


def test_check_urgent_alerts_none(engine, store):
    store.upsert_event(
        project_id="p1",
        source="linear",
        event_type="issue_created",
        title="Minor fix",
        source_item_id="L1",
        timestamp="2026-03-16T10:00:00Z",
        priority="low",
    )
    assert len(engine.check_urgent_events("p1")) == 0


@pytest.mark.asyncio
async def test_send_digest(engine, store):
    store.create_notification_rule(
        project_id="p1",
        rule_type="digest",
        channel="slack",
        channel_target="dm",
        config={"schedule": "09:00"},
    )
    await engine.send_digest("p1")
    engine.slack_notifier.send_text.assert_called_once()


@pytest.mark.asyncio
async def test_send_digest_no_rules(engine, store):
    # No rules — should not call slack
    await engine.send_digest("p1")
    engine.slack_notifier.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_send_digest_disabled_rule(engine, store):
    store.create_notification_rule(
        project_id="p1",
        rule_type="digest",
        channel="slack",
        channel_target="dm",
        config={},
        enabled=False,
    )
    await engine.send_digest("p1")
    engine.slack_notifier.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_send_urgent_alert(engine, store):
    store.create_notification_rule(
        project_id="p1",
        rule_type="alert",
        channel="slack",
        channel_target="dm",
        config={},
    )
    event = {
        "id": "ev1",
        "title": "Critical!",
        "url": "https://example.com",
        "source_item_id": "L1",
        "priority": "urgent",
    }
    await engine.send_urgent_alert("p1", event)
    engine.slack_notifier.send_text.assert_called_once()
    call_args = engine.slack_notifier.send_text.call_args[0][0]
    assert "Critical!" in call_args
    assert "https://example.com" in call_args


@pytest.mark.asyncio
async def test_send_urgent_alert_no_rules(engine, store):
    event = {"id": "ev1", "title": "Alert", "source_item_id": "L1", "priority": "urgent"}
    await engine.send_urgent_alert("p1", event)
    engine.slack_notifier.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_process_new_events(engine, store):
    store.create_notification_rule(
        project_id="p1",
        rule_type="alert",
        channel="slack",
        channel_target="dm",
        config={},
    )
    store.upsert_event(
        project_id="p1",
        source="linear",
        event_type="issue_created",
        title="Urgent bug",
        source_item_id="L1",
        timestamp="2026-03-16T10:00:00Z",
        priority="urgent",
    )
    await engine.process_new_events("p1")
    engine.slack_notifier.send_text.assert_called_once()


# --- GAP COVERAGE: send_digest discord branch ---


@pytest.mark.asyncio
async def test_send_digest_discord_calls_create_run_message(engine, store):
    """send_digest with a discord rule must delegate to discord_notifier.create_run_message."""
    store.create_notification_rule(
        project_id="p1",
        rule_type="digest",
        channel="discord",
        channel_target="chan-abc",
        config={},
    )
    await engine.send_digest("p1")
    engine.discord_notifier.create_run_message.assert_awaited_once()
    call_args = engine.discord_notifier.create_run_message.call_args
    # First positional arg must be the channel_target
    assert call_args[0][0] == "chan-abc"
    # Second positional arg is the project_id used as identifier
    assert call_args[0][1] == "p1"


@pytest.mark.asyncio
async def test_send_digest_discord_does_not_call_slack(engine, store):
    """A discord digest rule must not trigger the slack notifier."""
    store.create_notification_rule(
        project_id="p1",
        rule_type="digest",
        channel="discord",
        channel_target="chan-abc",
        config={},
    )
    await engine.send_digest("p1")
    engine.slack_notifier.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_send_digest_exception_is_swallowed(engine, store):
    """If the notifier raises, send_digest must not propagate the exception."""
    store.create_notification_rule(
        project_id="p1",
        rule_type="digest",
        channel="slack",
        channel_target="dm",
        config={},
    )
    engine.slack_notifier.send_text.side_effect = RuntimeError("network error")
    # Must not raise
    await engine.send_digest("p1")


# --- GAP COVERAGE: send_urgent_alert cooldown ---


@pytest.mark.asyncio
async def test_send_urgent_alert_skips_when_recently_notified(engine, store):
    """When was_recently_notified returns True the alert must not be sent again."""
    rule_id = store.create_notification_rule(
        project_id="p1",
        rule_type="alert",
        channel="slack",
        channel_target="dm",
        config={},
    )
    event = {"id": "ev1", "title": "Critical!", "source_item_id": "ev1", "priority": "urgent"}
    # Pre-populate the notification log to trigger the cooldown
    store.log_notification(
        project_id="p1",
        rule_id=rule_id,
        event_id="ev1",
        channel="slack",
        content="prev",
    )
    await engine.send_urgent_alert("p1", event)
    engine.slack_notifier.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_send_urgent_alert_without_url(engine, store):
    """Events without a url field must still send correctly."""
    store.create_notification_rule(
        project_id="p1",
        rule_type="alert",
        channel="slack",
        channel_target="dm",
        config={},
    )
    event = {"id": "ev2", "title": "No URL event", "source_item_id": "ev2", "priority": "high"}
    await engine.send_urgent_alert("p1", event)
    engine.slack_notifier.send_text.assert_called_once()
    call_text = engine.slack_notifier.send_text.call_args[0][0]
    assert "No URL event" in call_text
