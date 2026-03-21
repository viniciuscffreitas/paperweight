import pytest

from agents.config import load_project_configs
from agents.migration import migrate_yaml_projects
from agents.project_store import ProjectStore


@pytest.fixture
def store(tmp_path):
    return ProjectStore(tmp_path / "test.db")


@pytest.fixture
def yaml_dir(tmp_path):
    d = tmp_path / "projects"
    d.mkdir()
    (d / "momease.yaml").write_text("""
name: momease
repo: /repos/momease
base_branch: main
branch_prefix: agents/
notify: slack
linear_team_id: team-123
tasks:
  fix-bugs:
    description: Fix all bugs
    intent: Find and fix bugs
    schedule: "0 9 * * *"
    model: sonnet
    max_cost_usd: 5.0
    autonomy: pr-only
  review-prs:
    description: Review open PRs
    intent: Review and comment on PRs
    trigger:
      type: github
      events: ["pull_request.opened"]
    model: sonnet
    max_cost_usd: 3.0
    autonomy: read-only
""")
    return d


def test_migrate_yaml_projects(store, yaml_dir):
    projects = load_project_configs(yaml_dir)
    count = migrate_yaml_projects(projects, store)
    assert count == 1
    p = store.get_project("momease")
    assert p is not None
    assert p["name"] == "momease"
    tasks = store.list_tasks("momease")
    assert len(tasks) == 2
    sources = store.list_sources("momease")
    assert len([s for s in sources if s["source_type"] == "linear"]) == 1


def test_migrate_skips_existing(store, yaml_dir):
    projects = load_project_configs(yaml_dir)
    migrate_yaml_projects(projects, store)
    count = migrate_yaml_projects(projects, store)
    assert count == 0


def test_migrate_task_schedule_trigger_type(store, yaml_dir):
    projects = load_project_configs(yaml_dir)
    migrate_yaml_projects(projects, store)
    tasks = store.list_tasks("momease")
    task_map = {t["name"]: t for t in tasks}
    assert task_map["fix-bugs"]["trigger_type"] == "schedule"
    assert task_map["review-prs"]["trigger_type"] == "webhook"


def test_migrate_task_without_linear(store, tmp_path):
    d = tmp_path / "projects2"
    d.mkdir()
    (d / "simple.yaml").write_text("""
name: simple
repo: /repos/simple
base_branch: main
tasks:
  do-stuff:
    description: Do stuff
    intent: Do some stuff
    model: sonnet
    max_cost_usd: 2.0
    autonomy: pr-only
""")
    projects = load_project_configs(d)
    count = migrate_yaml_projects(projects, store)
    assert count == 1
    sources = store.list_sources("simple")
    assert len([s for s in sources if s["source_type"] == "linear"]) == 0


def test_migrate_sets_correct_repo_path(store, yaml_dir):
    projects = load_project_configs(yaml_dir)
    migrate_yaml_projects(projects, store)
    p = store.get_project("momease")
    assert p["repo_path"] == "/repos/momease"


def test_migrate_empty_projects_dir(store, tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    projects = load_project_configs(d)
    count = migrate_yaml_projects(projects, store)
    assert count == 0
