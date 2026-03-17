import pytest
from pathlib import Path
from agents.project_store import ProjectStore


@pytest.fixture
def store(tmp_path: Path) -> ProjectStore:
    return ProjectStore(tmp_path / "test.db")


def test_create_project(store: ProjectStore) -> None:
    store.create_project(id="momease", name="MomEase", repo_path="/repos/momease")
    project = store.get_project("momease")
    assert project is not None
    assert project["name"] == "MomEase"
    assert project["default_branch"] == "main"


def test_list_projects(store: ProjectStore) -> None:
    store.create_project(id="p1", name="Project 1", repo_path="/repos/p1")
    store.create_project(id="p2", name="Project 2", repo_path="/repos/p2")
    projects = store.list_projects()
    assert len(projects) == 2


def test_update_project(store: ProjectStore) -> None:
    store.create_project(id="p1", name="Old Name", repo_path="/repos/p1")
    store.update_project("p1", name="New Name")
    project = store.get_project("p1")
    assert project["name"] == "New Name"


def test_delete_project(store: ProjectStore) -> None:
    store.create_project(id="p1", name="Project 1", repo_path="/repos/p1")
    store.delete_project("p1")
    assert store.get_project("p1") is None


def test_create_source(store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/repos/p1")
    source_id = store.create_source(
        project_id="p1", source_type="linear", source_id="LIN-123", source_name="MomEase Linear",
    )
    sources = store.list_sources("p1")
    assert len(sources) == 1
    assert sources[0]["source_type"] == "linear"


def test_delete_source(store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/repos/p1")
    source_id = store.create_source(
        project_id="p1", source_type="slack", source_id="C123", source_name="#dev"
    )
    store.delete_source(source_id)
    assert store.list_sources("p1") == []


def test_create_task(store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/repos/p1")
    task_id = store.create_task(
        project_id="p1", name="Fix bugs", intent="Fix all open bugs",
        trigger_type="manual", model="sonnet", max_budget=5.0, autonomy="pr-only",
    )
    tasks = store.list_tasks("p1")
    assert len(tasks) == 1
    assert tasks[0]["name"] == "Fix bugs"


def test_update_task(store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/repos/p1")
    task_id = store.create_task(
        project_id="p1", name="Old", intent="Do stuff", trigger_type="manual",
        model="sonnet", max_budget=5.0, autonomy="pr-only",
    )
    store.update_task(task_id, name="New", enabled=False)
    task = store.get_task(task_id)
    assert task["name"] == "New"
    assert task["enabled"] == 0


def test_toggle_task(store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/repos/p1")
    task_id = store.create_task(
        project_id="p1", name="Task", intent="Do stuff", trigger_type="manual",
        model="sonnet", max_budget=5.0, autonomy="pr-only",
    )
    store.update_task(task_id, enabled=False)
    task = store.get_task(task_id)
    assert task["enabled"] == 0
    store.update_task(task_id, enabled=True)
    task = store.get_task(task_id)
    assert task["enabled"] == 1


def test_delete_task(store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/repos/p1")
    task_id = store.create_task(
        project_id="p1", name="Task", intent="Do stuff", trigger_type="manual",
        model="sonnet", max_budget=5.0, autonomy="pr-only",
    )
    store.delete_task(task_id)
    assert store.list_tasks("p1") == []


def test_insert_event(store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/repos/p1")
    store.upsert_event(
        project_id="p1", source="linear", event_type="issue_created",
        title="Fix login", source_item_id="LIN-42", timestamp="2026-03-16T10:00:00Z",
    )
    events = store.list_events("p1")
    assert len(events) == 1
    assert events[0]["title"] == "Fix login"


def test_event_deduplication(store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/repos/p1")
    store.upsert_event(
        project_id="p1", source="linear", event_type="issue_created",
        title="Fix login v1", source_item_id="LIN-42", timestamp="2026-03-16T10:00:00Z",
    )
    store.upsert_event(
        project_id="p1", source="linear", event_type="issue_updated",
        title="Fix login v2", source_item_id="LIN-42", timestamp="2026-03-16T10:05:00Z",
    )
    events = store.list_events("p1")
    assert len(events) == 1
    assert events[0]["title"] == "Fix login v2"


def test_list_events_filtered_by_source(store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/repos/p1")
    store.upsert_event(
        project_id="p1", source="linear", event_type="issue_created",
        title="Issue", source_item_id="L1", timestamp="2026-03-16T10:00:00Z",
    )
    store.upsert_event(
        project_id="p1", source="github", event_type="pr_opened",
        title="PR", source_item_id="G1", timestamp="2026-03-16T10:01:00Z",
    )
    linear_events = store.list_events("p1", source="linear")
    assert len(linear_events) == 1
    assert linear_events[0]["source"] == "linear"


def test_notification_rules_crud(store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/repos/p1")
    rule_id = store.create_notification_rule(
        project_id="p1", rule_type="digest", channel="slack",
        channel_target="dm", config={"schedule": "0 9 * * *"},
    )
    rules = store.list_notification_rules("p1")
    assert len(rules) == 1
    assert rules[0]["rule_type"] == "digest"
    store.delete_notification_rule(rule_id)
    assert store.list_notification_rules("p1") == []


def test_cascade_delete_project(store: ProjectStore) -> None:
    store.create_project(id="p1", name="P1", repo_path="/repos/p1")
    store.create_source(project_id="p1", source_type="linear", source_id="L1", source_name="Lin")
    store.create_task(
        project_id="p1", name="T", intent="I", trigger_type="manual",
        model="sonnet", max_budget=5.0, autonomy="pr-only",
    )
    store.upsert_event(
        project_id="p1", source="linear", event_type="x", title="E",
        source_item_id="E1", timestamp="2026-03-16T10:00:00Z",
    )
    store.create_notification_rule(
        project_id="p1", rule_type="digest", channel="slack", channel_target="dm",
    )
    store.delete_project("p1")
    assert store.list_sources("p1") == []
    assert store.list_tasks("p1") == []
    assert store.list_events("p1") == []
    assert store.list_notification_rules("p1") == []
