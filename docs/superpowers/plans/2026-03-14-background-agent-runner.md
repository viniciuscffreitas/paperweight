# Background Agent Runner — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python service that orchestrates Claude Code CLI sessions in background — on schedules and event triggers — across multiple projects, with cost control and Slack notifications.

**Architecture:** FastAPI service with APScheduler for cron jobs, webhook endpoints for GitHub/Linear events, an executor that spawns `claude -p` in isolated git worktrees, SQLite for history/job storage, and a budget manager that reads `total_cost_usd` from CLI output.

**Tech Stack:** Python 3.13, uv, FastAPI, APScheduler, SQLite, Claude Code CLI (`claude -p`), httpx (Slack webhooks)

**Spec:** `docs/superpowers/specs/2026-03-14-background-agent-runner-design.md`

---

## Chunk 1: Foundation (Scaffold + Models + Config + History)

### Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/agents/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `.gitignore`
- Create: `.python-version`
- Create: `config.yaml`
- Create: `projects/example.yaml`

- [ ] **Step 1: Initialize git repo**

```bash
cd /Users/vini/Developer/agents
git init
```

- [ ] **Step 2: Create pyproject.toml**

```toml
[project]
name = "agents"
version = "0.1.0"
description = "Background Agent Runner — orchestrates Claude Code CLI sessions"
requires-python = ">=3.13"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
    "pydantic>=2.10",
    "pydantic-settings>=2.7",
    "pyyaml>=6.0",
    "apscheduler>=3.11,<4",
    "sqlalchemy>=2.0",
    "httpx>=0.28",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.25",
    "httpx>=0.28",
    "ruff>=0.9",
    "pyright>=1.1",
]

[tool.ruff]
target-version = "py313"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "PT", "RUF", "ANN"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["ANN"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.pyright]
pythonVersion = "3.13"
typeCheckingMode = "basic"
```

- [ ] **Step 3: Create .python-version**

```
3.13
```

- [ ] **Step 4: Create .gitignore**

```gitignore
__pycache__/
*.pyc
.venv/
data/
.ruff_cache/
*.egg-info/
dist/
.env
firebase-debug.log
```

- [ ] **Step 5: Create source package**

```python
# src/agents/__init__.py
```

Empty file — just marks the package.

- [ ] **Step 6: Create tests/conftest.py**

```python
# tests/conftest.py
```

Empty for now — fixtures will be added as needed.

- [ ] **Step 7: Create config.yaml with defaults**

```yaml
# config.yaml
budget:
  daily_limit_usd: 10.00
  warning_threshold_usd: 7.00
  pause_on_limit: true

notifications:
  slack_webhook_url: ${SLACK_WEBHOOK_URL}

webhooks:
  github_secret: ${GITHUB_WEBHOOK_SECRET}
  linear_secret: ${LINEAR_WEBHOOK_SECRET}

execution:
  worktree_base: /tmp/agents
  default_model: sonnet
  default_max_cost_usd: 5.00
  default_autonomy: pr-only
  max_concurrent: 3
  timeout_minutes: 15
  dry_run: false

server:
  host: 0.0.0.0
  port: 8080
```

- [ ] **Step 8: Create projects/example.yaml**

```yaml
# projects/example.yaml — example project config (not loaded in prod)
name: example
repo: /tmp/example-repo
base_branch: main
branch_prefix: agents/
notify: none

tasks:
  hello:
    description: "Test task — just says hello"
    schedule: "0 9 * * *"
    model: haiku
    max_cost_usd: 0.10
    autonomy: pr-only
    prompt: |
      Say hello and list the files in this repository.
```

- [ ] **Step 9: Install dependencies and verify**

```bash
cd /Users/vini/Developer/agents
uv sync --all-extras
uv run python -c "import fastapi; import apscheduler; print('OK')"
```

- [ ] **Step 10: Commit scaffold**

```bash
git add pyproject.toml src/ tests/ .gitignore .python-version config.yaml projects/
git commit -m "chore: scaffold project with deps and config"
```

---

### Task 2: Pydantic Models

**Files:**
- Create: `src/agents/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing tests for models**

```python
# tests/test_models.py
import pytest
from datetime import datetime


def test_trigger_config_creation():
    from agents.models import TriggerConfig

    trigger = TriggerConfig(type="github", events=["check_suite.completed"], filter={"conclusion": "failure"})
    assert trigger.type == "github"
    assert trigger.events == ["check_suite.completed"]
    assert trigger.filter == {"conclusion": "failure"}


def test_task_config_defaults():
    from agents.models import TaskConfig

    task = TaskConfig(
        description="test",
        prompt="do something",
        schedule="0 3 * * MON",
    )
    assert task.model == "sonnet"
    assert task.max_cost_usd == 5.00
    assert task.autonomy == "pr-only"
    assert task.trigger is None


def test_task_config_schedule_and_trigger_mutually_exclusive():
    from agents.models import TaskConfig, TriggerConfig

    # Both set — should raise
    with pytest.raises(ValueError, match="mutually exclusive"):
        TaskConfig(
            description="test",
            prompt="do something",
            schedule="0 3 * * MON",
            trigger=TriggerConfig(type="github", events=["push"]),
        )


def test_task_config_requires_schedule_or_trigger():
    from agents.models import TaskConfig

    # Neither set — should raise
    with pytest.raises(ValueError, match="schedule.*trigger"):
        TaskConfig(
            description="test",
            prompt="do something",
        )


def test_project_config_creation():
    from agents.models import ProjectConfig, TaskConfig

    project = ProjectConfig(
        name="sekit",
        repo="/Users/vini/Developer/sekit",
        tasks={
            "dep-update": TaskConfig(
                description="Update deps",
                prompt="update deps",
                schedule="0 3 * * MON",
            )
        },
    )
    assert project.name == "sekit"
    assert project.base_branch == "main"
    assert project.branch_prefix == "agents/"
    assert project.notify == "slack"


def test_run_record_creation():
    from agents.models import RunRecord, RunStatus, TriggerType

    run = RunRecord(
        id="run-123",
        project="sekit",
        task="dep-update",
        trigger_type=TriggerType.SCHEDULE,
        started_at=datetime(2026, 3, 14, 3, 0, 0),
        status=RunStatus.RUNNING,
        model="sonnet",
    )
    assert run.id == "run-123"
    assert run.status == RunStatus.RUNNING
    assert run.cost_usd is None
    assert run.pr_url is None


def test_budget_status():
    from agents.models import BudgetStatus

    status = BudgetStatus(
        daily_limit_usd=10.0,
        spent_today_usd=7.5,
    )
    assert status.remaining_usd == 2.5
    assert status.is_warning is True
    assert status.is_exceeded is False


def test_budget_status_exceeded():
    from agents.models import BudgetStatus

    status = BudgetStatus(
        daily_limit_usd=10.0,
        spent_today_usd=10.5,
    )
    assert status.remaining_usd == 0.0
    assert status.is_exceeded is True
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /Users/vini/Developer/agents
uv run python -m pytest tests/test_models.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'agents.models'`

- [ ] **Step 3: Implement models**

```python
# src/agents/models.py
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, model_validator


class TriggerType(StrEnum):
    SCHEDULE = "schedule"
    GITHUB = "github"
    LINEAR = "linear"
    MANUAL = "manual"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class TriggerConfig(BaseModel):
    type: str
    events: list[str]
    filter: dict[str, str] = {}


class TaskConfig(BaseModel):
    description: str
    prompt: str
    schedule: str | None = None
    trigger: TriggerConfig | None = None
    model: str = "sonnet"
    max_cost_usd: float = 5.00
    autonomy: str = "pr-only"

    @model_validator(mode="after")
    def validate_schedule_or_trigger(self) -> "TaskConfig":
        if self.schedule and self.trigger:
            msg = "schedule and trigger are mutually exclusive"
            raise ValueError(msg)
        if not self.schedule and not self.trigger:
            msg = "Either schedule or trigger must be set"
            raise ValueError(msg)
        return self


class ProjectConfig(BaseModel):
    name: str
    repo: str
    base_branch: str = "main"
    branch_prefix: str = "agents/"
    notify: str = "slack"
    tasks: dict[str, TaskConfig]


class RunRecord(BaseModel):
    id: str
    project: str
    task: str
    trigger_type: TriggerType
    started_at: datetime
    finished_at: datetime | None = None
    status: RunStatus
    model: str
    num_turns: int | None = None
    cost_usd: float | None = None
    pr_url: str | None = None
    error_message: str | None = None
    output_file: str | None = None


class BudgetStatus(BaseModel):
    daily_limit_usd: float
    spent_today_usd: float
    warning_threshold_usd: float = 7.00

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.daily_limit_usd - self.spent_today_usd)

    @property
    def is_warning(self) -> bool:
        return self.spent_today_usd >= self.warning_threshold_usd

    @property
    def is_exceeded(self) -> bool:
        return self.spent_today_usd >= self.daily_limit_usd
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run python -m pytest tests/test_models.py -v
```

Expected: all PASS

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run pyright src/
```

- [ ] **Step 6: Commit**

```bash
git add src/agents/models.py tests/test_models.py
git commit -m "feat: add Pydantic models for config, runs, and budget"
```

---

### Task 3: Config Loader

**Files:**
- Create: `src/agents/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_config.py
import os
import pytest
from pathlib import Path


def test_resolve_env_vars():
    from agents.config import resolve_env_vars

    os.environ["TEST_SECRET"] = "my-secret"
    assert resolve_env_vars("${TEST_SECRET}") == "my-secret"
    assert resolve_env_vars("no-vars-here") == "no-vars-here"
    assert resolve_env_vars("prefix-${TEST_SECRET}-suffix") == "prefix-my-secret-suffix"
    del os.environ["TEST_SECRET"]


def test_resolve_env_vars_missing_returns_empty():
    from agents.config import resolve_env_vars

    assert resolve_env_vars("${NONEXISTENT_VAR}") == ""


def test_load_global_config(tmp_path):
    from agents.config import load_global_config

    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
budget:
  daily_limit_usd: 15.00
  warning_threshold_usd: 10.00
  pause_on_limit: false

notifications:
  slack_webhook_url: https://hooks.slack.com/test

webhooks:
  github_secret: gh-secret
  linear_secret: ln-secret

execution:
  worktree_base: /tmp/test-agents
  default_model: haiku
  default_max_cost_usd: 2.00
  default_autonomy: pr-only
  max_concurrent: 2
  timeout_minutes: 10
  dry_run: true

server:
  host: 127.0.0.1
  port: 9090
""")

    config = load_global_config(config_file)
    assert config.budget.daily_limit_usd == 15.00
    assert config.execution.default_model == "haiku"
    assert config.execution.dry_run is True
    assert config.server.port == 9090


def test_load_project_configs(tmp_path):
    from agents.config import load_project_configs

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    (projects_dir / "myproject.yaml").write_text("""
name: myproject
repo: /tmp/myrepo
base_branch: develop
tasks:
  lint:
    description: "Run linter"
    schedule: "0 2 * * *"
    model: haiku
    max_cost_usd: 0.50
    prompt: "Run the linter and fix issues"
""")

    projects = load_project_configs(projects_dir)
    assert len(projects) == 1
    assert projects["myproject"].name == "myproject"
    assert projects["myproject"].base_branch == "develop"
    assert "lint" in projects["myproject"].tasks


def test_load_project_configs_skips_example(tmp_path):
    from agents.config import load_project_configs

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    (projects_dir / "example.yaml").write_text("""
name: example
repo: /tmp/example-repo
tasks:
  hello:
    description: "Test"
    schedule: "0 9 * * *"
    prompt: "hello"
""")

    projects = load_project_configs(projects_dir)
    assert len(projects) == 0


def test_render_prompt_template():
    from agents.config import render_prompt

    template = "CI failed on branch {{branch}}. SHA: {{sha}}"
    result = render_prompt(template, {"branch": "main", "sha": "abc123", "extra": "ignored"})
    assert result == "CI failed on branch main. SHA: abc123"


def test_render_prompt_missing_var_left_as_is():
    from agents.config import render_prompt

    template = "Branch: {{branch}}, PR: {{pr_number}}"
    result = render_prompt(template, {"branch": "feat/x"})
    assert result == "Branch: feat/x, PR: {{pr_number}}"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
uv run python -m pytest tests/test_config.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement config loader**

```python
# src/agents/config.py
import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel

from agents.models import ProjectConfig


class BudgetConfig(BaseModel):
    daily_limit_usd: float = 10.00
    warning_threshold_usd: float = 7.00
    pause_on_limit: bool = True


class NotificationsConfig(BaseModel):
    slack_webhook_url: str = ""


class WebhooksConfig(BaseModel):
    github_secret: str = ""
    linear_secret: str = ""


class ExecutionConfig(BaseModel):
    worktree_base: str = "/tmp/agents"
    default_model: str = "sonnet"
    default_max_cost_usd: float = 5.00
    default_autonomy: str = "pr-only"
    max_concurrent: int = 3
    timeout_minutes: int = 15
    dry_run: bool = False


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080


class GlobalConfig(BaseModel):
    budget: BudgetConfig = BudgetConfig()
    notifications: NotificationsConfig = NotificationsConfig()
    webhooks: WebhooksConfig = WebhooksConfig()
    execution: ExecutionConfig = ExecutionConfig()
    server: ServerConfig = ServerConfig()


def resolve_env_vars(value: str) -> str:
    """Replace ${VAR} references with environment variable values."""
    def replacer(match: re.Match[str]) -> str:
        return os.environ.get(match.group(1), "")

    return re.sub(r"\$\{(\w+)\}", replacer, value)


def _resolve_dict(data: dict) -> dict:
    """Recursively resolve env vars in all string values."""
    resolved = {}
    for key, value in data.items():
        if isinstance(value, str):
            resolved[key] = resolve_env_vars(value)
        elif isinstance(value, dict):
            resolved[key] = _resolve_dict(value)
        else:
            resolved[key] = value
    return resolved


def load_global_config(path: Path) -> GlobalConfig:
    """Load and validate global config from YAML file."""
    raw = yaml.safe_load(path.read_text())
    resolved = _resolve_dict(raw)
    return GlobalConfig(**resolved)


def load_project_configs(projects_dir: Path) -> dict[str, ProjectConfig]:
    """Load all project configs from YAML files in a directory. Skips 'example'."""
    projects: dict[str, ProjectConfig] = {}
    if not projects_dir.exists():
        return projects

    for yaml_file in sorted(projects_dir.glob("*.yaml")):
        raw = yaml.safe_load(yaml_file.read_text())
        if raw.get("name") == "example":
            continue
        project = ProjectConfig(**raw)
        projects[project.name] = project

    return projects


def render_prompt(template: str, variables: dict[str, str]) -> str:
    """Replace {{var}} placeholders with values. Unknown vars left as-is."""
    result = template
    for key, value in variables.items():
        result = result.replace("{{" + key + "}}", value)
    return result
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run python -m pytest tests/test_config.py -v
```

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff check src/ tests/ && uv run pyright src/
```

- [ ] **Step 6: Commit**

```bash
git add src/agents/config.py tests/test_config.py
git commit -m "feat: add config loader with env var resolution and prompt templates"
```

---

### Task 4: History (SQLite)

**Files:**
- Create: `src/agents/history.py`
- Create: `tests/test_history.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_history.py
import pytest
from datetime import datetime, timezone
from pathlib import Path


@pytest.fixture
def history_db(tmp_path):
    from agents.history import HistoryDB

    db_path = tmp_path / "test.db"
    return HistoryDB(db_path)


def test_create_tables(history_db):
    """Tables should be created on init."""
    import sqlite3

    conn = sqlite3.connect(history_db.db_path)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()
    assert "runs" in tables


def test_insert_and_get_run(history_db):
    from agents.models import RunRecord, RunStatus, TriggerType

    run = RunRecord(
        id="run-001",
        project="sekit",
        task="dep-update",
        trigger_type=TriggerType.SCHEDULE,
        started_at=datetime(2026, 3, 14, 3, 0, 0, tzinfo=timezone.utc),
        status=RunStatus.RUNNING,
        model="sonnet",
    )

    history_db.insert_run(run)
    fetched = history_db.get_run("run-001")

    assert fetched is not None
    assert fetched.id == "run-001"
    assert fetched.project == "sekit"
    assert fetched.status == RunStatus.RUNNING


def test_update_run_completion(history_db):
    from agents.models import RunRecord, RunStatus, TriggerType

    run = RunRecord(
        id="run-002",
        project="sekit",
        task="ci-fix",
        trigger_type=TriggerType.GITHUB,
        started_at=datetime(2026, 3, 14, 3, 0, 0, tzinfo=timezone.utc),
        status=RunStatus.RUNNING,
        model="sonnet",
    )
    history_db.insert_run(run)

    history_db.update_run(
        run_id="run-002",
        status=RunStatus.SUCCESS,
        finished_at=datetime(2026, 3, 14, 3, 5, 0, tzinfo=timezone.utc),
        cost_usd=0.45,
        num_turns=8,
        pr_url="https://github.com/org/repo/pull/1",
    )

    fetched = history_db.get_run("run-002")
    assert fetched is not None
    assert fetched.status == RunStatus.SUCCESS
    assert fetched.cost_usd == 0.45
    assert fetched.pr_url == "https://github.com/org/repo/pull/1"


def test_list_runs_today(history_db):
    from agents.models import RunRecord, RunStatus, TriggerType

    now = datetime.now(timezone.utc)

    for i in range(3):
        history_db.insert_run(RunRecord(
            id=f"run-{i}",
            project="sekit",
            task="test",
            trigger_type=TriggerType.MANUAL,
            started_at=now,
            status=RunStatus.SUCCESS,
            model="sonnet",
            cost_usd=1.0 + i,
        ))

    runs = history_db.list_runs_today()
    assert len(runs) == 3


def test_total_cost_today(history_db):
    from agents.models import RunRecord, RunStatus, TriggerType

    now = datetime.now(timezone.utc)

    history_db.insert_run(RunRecord(
        id="run-a", project="p", task="t", trigger_type=TriggerType.MANUAL,
        started_at=now, status=RunStatus.SUCCESS, model="s", cost_usd=2.50,
    ))
    history_db.insert_run(RunRecord(
        id="run-b", project="p", task="t", trigger_type=TriggerType.MANUAL,
        started_at=now, status=RunStatus.SUCCESS, model="s", cost_usd=1.25,
    ))
    # Running task with no cost yet
    history_db.insert_run(RunRecord(
        id="run-c", project="p", task="t", trigger_type=TriggerType.MANUAL,
        started_at=now, status=RunStatus.RUNNING, model="s",
    ))

    assert history_db.total_cost_today() == pytest.approx(3.75)


def test_get_nonexistent_run(history_db):
    assert history_db.get_run("nonexistent") is None


def test_mark_running_as_cancelled(history_db):
    from agents.models import RunRecord, RunStatus, TriggerType

    now = datetime.now(timezone.utc)

    history_db.insert_run(RunRecord(
        id="run-x", project="p", task="t", trigger_type=TriggerType.MANUAL,
        started_at=now, status=RunStatus.RUNNING, model="s",
    ))
    history_db.insert_run(RunRecord(
        id="run-y", project="p", task="t", trigger_type=TriggerType.MANUAL,
        started_at=now, status=RunStatus.SUCCESS, model="s",
    ))

    history_db.mark_running_as_cancelled()

    assert history_db.get_run("run-x").status == RunStatus.CANCELLED
    assert history_db.get_run("run-y").status == RunStatus.SUCCESS
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
uv run python -m pytest tests/test_history.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement history**

```python
# src/agents/history.py
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from agents.models import RunRecord, RunStatus


class HistoryDB:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    project TEXT NOT NULL,
                    task TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    started_at TIMESTAMP NOT NULL,
                    finished_at TIMESTAMP,
                    status TEXT NOT NULL,
                    model TEXT NOT NULL,
                    num_turns INTEGER,
                    cost_usd REAL,
                    pr_url TEXT,
                    error_message TEXT,
                    output_file TEXT
                )
            """)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def insert_run(self, run: RunRecord) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO runs (id, project, task, trigger_type, started_at, finished_at,
                   status, model, num_turns, cost_usd, pr_url, error_message, output_file)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run.id, run.project, run.task, run.trigger_type, run.started_at.isoformat(),
                 run.finished_at.isoformat() if run.finished_at else None,
                 run.status, run.model, run.num_turns, run.cost_usd,
                 run.pr_url, run.error_message, run.output_file),
            )

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def update_run(
        self,
        run_id: str,
        status: RunStatus | None = None,
        finished_at: datetime | None = None,
        cost_usd: float | None = None,
        num_turns: int | None = None,
        pr_url: str | None = None,
        error_message: str | None = None,
        output_file: str | None = None,
    ) -> None:
        updates: list[str] = []
        values: list[object] = []

        for field, value in [
            ("status", status),
            ("finished_at", finished_at.isoformat() if finished_at else None),
            ("cost_usd", cost_usd),
            ("num_turns", num_turns),
            ("pr_url", pr_url),
            ("error_message", error_message),
            ("output_file", output_file),
        ]:
            if value is not None:
                updates.append(f"{field} = ?")
                values.append(value)

        if not updates:
            return

        values.append(run_id)
        with self._conn() as conn:
            conn.execute(f"UPDATE runs SET {', '.join(updates)} WHERE id = ?", values)

    def list_runs_today(self) -> list[RunRecord]:
        today = datetime.now(timezone.utc).date().isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE started_at >= ? ORDER BY started_at DESC",
                (today,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def total_cost_today(self) -> float:
        today = datetime.now(timezone.utc).date().isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) as total FROM runs WHERE started_at >= ?",
                (today,),
            ).fetchone()
        return float(row["total"])

    def mark_running_as_cancelled(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE runs SET status = ?, finished_at = ? WHERE status = ?",
                (RunStatus.CANCELLED, now, RunStatus.RUNNING),
            )

    def _row_to_record(self, row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            id=row["id"],
            project=row["project"],
            task=row["task"],
            trigger_type=row["trigger_type"],
            started_at=datetime.fromisoformat(row["started_at"]),
            finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
            status=row["status"],
            model=row["model"],
            num_turns=row["num_turns"],
            cost_usd=row["cost_usd"],
            pr_url=row["pr_url"],
            error_message=row["error_message"],
            output_file=row["output_file"],
        )
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run python -m pytest tests/test_history.py -v
```

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff check src/ tests/ && uv run pyright src/
```

- [ ] **Step 6: Commit**

```bash
git add src/agents/history.py tests/test_history.py
git commit -m "feat: add SQLite history store for run records"
```

---

## Chunk 2: Core Logic (Budget + Notifier + Executor)

### Task 5: Budget Manager

**Files:**
- Create: `src/agents/budget.py`
- Create: `tests/test_budget.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_budget.py
import pytest
from datetime import datetime, timezone
from pathlib import Path


@pytest.fixture
def budget_deps(tmp_path):
    from agents.history import HistoryDB
    from agents.config import BudgetConfig
    from agents.budget import BudgetManager

    db = HistoryDB(tmp_path / "test.db")
    config = BudgetConfig(daily_limit_usd=10.0, warning_threshold_usd=7.0, pause_on_limit=True)
    return BudgetManager(config=config, history=db), db


def test_budget_status_empty(budget_deps):
    manager, _ = budget_deps
    status = manager.get_status()
    assert status.spent_today_usd == 0.0
    assert status.remaining_usd == 10.0
    assert status.is_exceeded is False


def test_budget_status_after_spending(budget_deps):
    from agents.models import RunRecord, RunStatus, TriggerType

    manager, db = budget_deps
    now = datetime.now(timezone.utc)
    db.insert_run(RunRecord(
        id="r1", project="p", task="t", trigger_type=TriggerType.MANUAL,
        started_at=now, status=RunStatus.SUCCESS, model="s", cost_usd=4.50,
    ))

    status = manager.get_status()
    assert status.spent_today_usd == pytest.approx(4.50)
    assert status.remaining_usd == pytest.approx(5.50)


def test_can_afford_yes(budget_deps):
    manager, _ = budget_deps
    assert manager.can_afford(max_cost_usd=5.0) is True


def test_can_afford_no(budget_deps):
    from agents.models import RunRecord, RunStatus, TriggerType

    manager, db = budget_deps
    now = datetime.now(timezone.utc)
    db.insert_run(RunRecord(
        id="r1", project="p", task="t", trigger_type=TriggerType.MANUAL,
        started_at=now, status=RunStatus.SUCCESS, model="s", cost_usd=8.00,
    ))

    assert manager.can_afford(max_cost_usd=5.0) is False


def test_can_afford_when_paused(budget_deps):
    from agents.models import RunRecord, RunStatus, TriggerType

    manager, db = budget_deps
    now = datetime.now(timezone.utc)
    db.insert_run(RunRecord(
        id="r1", project="p", task="t", trigger_type=TriggerType.MANUAL,
        started_at=now, status=RunStatus.SUCCESS, model="s", cost_usd=10.50,
    ))

    assert manager.can_afford(max_cost_usd=0.01) is False


def test_record_cost(budget_deps):
    manager, _ = budget_deps
    manager.record_cost(3.50)
    # record_cost is a no-op — cost is tracked via history
    # Just verify it doesn't raise
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
uv run python -m pytest tests/test_budget.py -v
```

- [ ] **Step 3: Implement budget manager**

```python
# src/agents/budget.py
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

    def record_cost(self, cost_usd: float) -> None:
        # Cost is tracked via history records.
        # This method exists for interface consistency.
        pass
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run python -m pytest tests/test_budget.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/agents/budget.py tests/test_budget.py
git commit -m "feat: add budget manager with daily limit enforcement"
```

---

### Task 6: Notifier

**Files:**
- Create: `src/agents/notifier.py`
- Create: `tests/test_notifier.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_notifier.py
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch


def test_format_success_message():
    from agents.notifier import Notifier
    from agents.models import RunRecord, RunStatus, TriggerType

    notifier = Notifier(webhook_url="https://hooks.slack.com/test")
    run = RunRecord(
        id="run-001", project="sekit", task="dep-update",
        trigger_type=TriggerType.SCHEDULE,
        started_at=datetime(2026, 3, 14, 3, 0, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 3, 14, 3, 2, 34, tzinfo=timezone.utc),
        status=RunStatus.SUCCESS, model="haiku",
        cost_usd=0.18, num_turns=12,
        pr_url="https://github.com/org/repo/pull/42",
    )

    msg = notifier.format_message(run)
    assert "[sekit] dep-update" in msg
    assert "$0.18" in msg
    assert "pull/42" in msg


def test_format_failure_message():
    from agents.notifier import Notifier
    from agents.models import RunRecord, RunStatus, TriggerType

    notifier = Notifier(webhook_url="https://hooks.slack.com/test")
    run = RunRecord(
        id="run-002", project="fintech", task="ci-fix",
        trigger_type=TriggerType.GITHUB,
        started_at=datetime(2026, 3, 14, 3, 0, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 3, 14, 3, 8, 12, tzinfo=timezone.utc),
        status=RunStatus.FAILURE, model="sonnet",
        cost_usd=1.23, num_turns=28,
        error_message="Tests failed after fix attempt",
    )

    msg = notifier.format_message(run)
    assert "[fintech] ci-fix" in msg
    assert "failed" in msg.lower() or "FAILURE" in msg or "Tests failed" in msg


def test_format_budget_warning():
    from agents.notifier import Notifier
    from agents.models import BudgetStatus

    notifier = Notifier(webhook_url="https://hooks.slack.com/test")
    status = BudgetStatus(daily_limit_usd=10.0, spent_today_usd=7.23)
    msg = notifier.format_budget_warning(status)
    assert "$7.23" in msg
    assert "$10.00" in msg


def test_noop_notifier():
    from agents.notifier import Notifier

    notifier = Notifier(webhook_url="")
    # None input should return empty string
    msg = notifier.format_message(None)  # type: ignore
    assert msg == ""
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
uv run python -m pytest tests/test_notifier.py -v
```

- [ ] **Step 3: Implement notifier**

```python
# src/agents/notifier.py
import logging
from datetime import timezone

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
                f"[{run.project}] {run.task} completed"
                f"{pr_line}"
                f"\n   Cost: {cost} | Turns: {turns} | Duration: {duration}"
            )

        error_line = f"\n   Error: {run.error_message}" if run.error_message else ""
        return (
            f"[{run.project}] {run.task} {run.status}"
            f"{error_line}"
            f"\n   Cost: {cost} | Turns: {turns} | Duration: {duration}"
        )

    def format_budget_warning(self, status: BudgetStatus) -> str:
        pct = int(status.spent_today_usd / status.daily_limit_usd * 100)
        return (
            f"Budget warning: ${status.spent_today_usd:.2f} / "
            f"${status.daily_limit_usd:.2f} used today ({pct}%)"
        )

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
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run python -m pytest tests/test_notifier.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/agents/notifier.py tests/test_notifier.py
git commit -m "feat: add Slack notifier with message formatting"
```

---

### Task 7: Executor

**Files:**
- Create: `src/agents/executor.py`
- Create: `tests/test_executor.py`

This is the core component. Tests mock the `claude` CLI and `git` commands.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_executor.py
import json
import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def executor_deps(tmp_path):
    from agents.config import ExecutionConfig
    from agents.history import HistoryDB
    from agents.config import BudgetConfig
    from agents.budget import BudgetManager
    from agents.notifier import Notifier
    from agents.executor import Executor

    db = HistoryDB(tmp_path / "test.db")
    budget_config = BudgetConfig(daily_limit_usd=10.0)
    budget = BudgetManager(config=budget_config, history=db)
    notifier = Notifier(webhook_url="")
    exec_config = ExecutionConfig(
        worktree_base=str(tmp_path / "worktrees"),
        dry_run=False,
        timeout_minutes=1,
    )
    data_dir = tmp_path / "data" / "runs"
    data_dir.mkdir(parents=True)

    executor = Executor(
        config=exec_config,
        budget=budget,
        history=db,
        notifier=notifier,
        data_dir=tmp_path / "data",
    )
    return executor, db


def test_generate_run_id():
    from agents.executor import generate_run_id

    run_id = generate_run_id("sekit", "dep-update")
    assert run_id.startswith("sekit-dep-update-")
    assert len(run_id) > len("sekit-dep-update-")


def test_generate_branch_name():
    from agents.executor import generate_branch_name

    branch = generate_branch_name("agents/", "dep-update")
    assert branch.startswith("agents/dep-update-")


@pytest.mark.asyncio
async def test_executor_dry_run(tmp_path):
    from agents.config import ExecutionConfig
    from agents.history import HistoryDB
    from agents.config import BudgetConfig
    from agents.budget import BudgetManager
    from agents.notifier import Notifier
    from agents.executor import Executor
    from agents.models import ProjectConfig, TaskConfig, RunStatus

    db = HistoryDB(tmp_path / "test.db")
    budget = BudgetManager(config=BudgetConfig(), history=db)
    notifier = Notifier(webhook_url="")
    exec_config = ExecutionConfig(worktree_base=str(tmp_path / "wt"), dry_run=True)

    executor = Executor(
        config=exec_config, budget=budget, history=db,
        notifier=notifier, data_dir=tmp_path / "data",
    )

    project = ProjectConfig(
        name="test", repo="/tmp/test",
        tasks={"hello": TaskConfig(description="t", prompt="hi", schedule="0 * * * *")},
    )

    result = await executor.run_task(project, "hello", trigger_type="manual")
    assert result.status == RunStatus.SUCCESS
    assert "dry_run" in result.id or result.cost_usd == 0.0


@pytest.mark.asyncio
async def test_executor_budget_exceeded(executor_deps):
    from agents.models import ProjectConfig, TaskConfig, RunRecord, RunStatus, TriggerType

    executor, db = executor_deps

    # Exhaust budget
    db.insert_run(RunRecord(
        id="r-old", project="p", task="t", trigger_type=TriggerType.MANUAL,
        started_at=datetime.now(timezone.utc), status=RunStatus.SUCCESS,
        model="s", cost_usd=10.0,
    ))

    project = ProjectConfig(
        name="test", repo="/tmp/test",
        tasks={"hello": TaskConfig(description="t", prompt="hi", schedule="0 * * * *")},
    )

    result = await executor.run_task(project, "hello", trigger_type="manual")
    assert result.status == RunStatus.FAILURE
    assert "budget" in result.error_message.lower()


def test_parse_claude_output():
    from agents.executor import parse_claude_output

    raw = json.dumps({
        "result": "Done! Created PR.",
        "is_error": False,
        "total_cost_usd": 0.45,
        "num_turns": 8,
        "usage": {"input_tokens": 5000, "output_tokens": 1200},
    })

    parsed = parse_claude_output(raw)
    assert parsed.cost_usd == pytest.approx(0.45)
    assert parsed.num_turns == 8
    assert parsed.is_error is False
    assert parsed.result == "Done! Created PR."


def test_parse_claude_output_error():
    from agents.executor import parse_claude_output

    raw = json.dumps({
        "result": "Error occurred",
        "is_error": True,
        "total_cost_usd": 0.10,
        "num_turns": 3,
    })

    parsed = parse_claude_output(raw)
    assert parsed.is_error is True
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
uv run python -m pytest tests/test_executor.py -v
```

- [ ] **Step 3: Implement executor**

```python
# src/agents/executor.py
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from agents.budget import BudgetManager
from agents.config import ExecutionConfig, render_prompt
from agents.history import HistoryDB
from agents.models import ProjectConfig, RunRecord, RunStatus, TriggerType
from agents.notifier import Notifier

logger = logging.getLogger(__name__)


class ClaudeOutput(BaseModel):
    result: str = ""
    is_error: bool = False
    cost_usd: float = 0.0
    num_turns: int = 0


def generate_run_id(project: str, task: str) -> str:
    short_uuid = uuid.uuid4().hex[:8]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{project}-{task}-{timestamp}-{short_uuid}"


def generate_branch_name(prefix: str, task: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{prefix}{task}-{timestamp}"


def parse_claude_output(raw: str) -> ClaudeOutput:
    try:
        data = json.loads(raw)
        return ClaudeOutput(
            result=data.get("result", ""),
            is_error=data.get("is_error", False),
            cost_usd=data.get("total_cost_usd", 0.0),
            num_turns=data.get("num_turns", 0),
        )
    except (json.JSONDecodeError, KeyError):
        return ClaudeOutput(result=raw, is_error=True)


class Executor:
    def __init__(
        self,
        config: ExecutionConfig,
        budget: BudgetManager,
        history: HistoryDB,
        notifier: Notifier,
        data_dir: Path,
    ) -> None:
        self.config = config
        self.budget = budget
        self.history = history
        self.notifier = notifier
        self.data_dir = data_dir
        self._running_processes: dict[str, asyncio.subprocess.Process] = {}

    async def run_task(
        self,
        project: ProjectConfig,
        task_name: str,
        trigger_type: str = "manual",
        variables: dict[str, str] | None = None,
    ) -> RunRecord:
        task = project.tasks[task_name]
        run_id = generate_run_id(project.name, task_name)

        run = RunRecord(
            id=run_id,
            project=project.name,
            task=task_name,
            trigger_type=TriggerType(trigger_type),
            started_at=datetime.now(timezone.utc),
            status=RunStatus.RUNNING,
            model=task.model,
        )
        self.history.insert_run(run)

        # Budget check
        if not self.budget.can_afford(task.max_cost_usd):
            run.status = RunStatus.FAILURE
            run.error_message = f"Budget exceeded. Need ${task.max_cost_usd}, remaining: ${self.budget.get_status().remaining_usd:.2f}"
            run.finished_at = datetime.now(timezone.utc)
            self.history.update_run(
                run_id=run.id, status=run.status,
                finished_at=run.finished_at, error_message=run.error_message,
            )
            await self.notifier.send_run_notification(run)
            return run

        # Dry run
        if self.config.dry_run:
            logger.info("DRY RUN: would execute %s/%s", project.name, task_name)
            run.status = RunStatus.SUCCESS
            run.cost_usd = 0.0
            run.finished_at = datetime.now(timezone.utc)
            self.history.update_run(
                run_id=run.id, status=run.status,
                finished_at=run.finished_at, cost_usd=0.0,
            )
            return run

        # Real execution
        worktree_path: Path | None = None
        try:
            prompt = render_prompt(task.prompt, variables or {})
            branch_name = generate_branch_name(project.branch_prefix, task_name)
            worktree_path = Path(self.config.worktree_base) / run_id

            # Create worktree
            await self._run_cmd(
                ["git", "worktree", "add", str(worktree_path), "-b", branch_name, project.base_branch],
                cwd=project.repo,
            )

            # Run claude
            claude_cmd = [
                "claude", "-p", prompt,
                "--model", task.model,
                "--max-budget-usd", str(task.max_cost_usd),
                "--output-format", "json",
                "--permission-mode", "auto",
                "--no-session-persistence",
            ]

            stdout = await self._run_claude(
                claude_cmd, cwd=str(worktree_path), run_id=run_id,
                timeout=self.config.timeout_minutes * 60,
            )

            output = parse_claude_output(stdout)

            # Save output to file
            output_dir = self.data_dir / "runs"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / f"{run_id}.json"
            output_file.write_text(stdout)

            run.cost_usd = output.cost_usd
            run.num_turns = output.num_turns
            run.output_file = str(output_file)

            if output.is_error:
                run.status = RunStatus.FAILURE
                run.error_message = output.result[:500]
            else:
                # Create PR
                pr_url = await self._create_pr(
                    cwd=str(worktree_path),
                    project=project,
                    task_name=task_name,
                    branch=branch_name,
                    autonomy=task.autonomy,
                )
                run.status = RunStatus.SUCCESS
                run.pr_url = pr_url

        except asyncio.TimeoutError:
            run.status = RunStatus.TIMEOUT
            run.error_message = f"Timed out after {self.config.timeout_minutes} minutes"
        except Exception as e:
            run.status = RunStatus.FAILURE
            run.error_message = str(e)[:500]
            logger.exception("Task execution failed: %s/%s", project.name, task_name)
        finally:
            run.finished_at = datetime.now(timezone.utc)
            self.history.update_run(
                run_id=run.id, status=run.status, finished_at=run.finished_at,
                cost_usd=run.cost_usd, num_turns=run.num_turns,
                pr_url=run.pr_url, error_message=run.error_message,
                output_file=run.output_file,
            )

            # Cleanup worktree
            if worktree_path and worktree_path.exists():
                try:
                    await self._run_cmd(
                        ["git", "worktree", "remove", "--force", str(worktree_path)],
                        cwd=project.repo,
                    )
                except Exception:
                    logger.warning("Failed to remove worktree %s", worktree_path)

            self._running_processes.pop(run_id, None)

        await self.notifier.send_run_notification(run)

        # Check budget warning
        status = self.budget.get_status()
        if status.is_warning:
            await self.notifier.send_budget_warning(status)

        return run

    async def cancel_run(self, run_id: str) -> bool:
        proc = self._running_processes.get(run_id)
        if proc is None:
            return False
        proc.terminate()
        return True

    async def shutdown(self) -> None:
        for run_id, proc in self._running_processes.items():
            logger.info("Terminating process for run %s", run_id)
            proc.terminate()

        for run_id, proc in self._running_processes.items():
            try:
                await asyncio.wait_for(proc.wait(), timeout=30)
            except asyncio.TimeoutError:
                proc.kill()

        self.history.mark_running_as_cancelled()
        self._running_processes.clear()

    async def _run_claude(
        self, cmd: list[str], cwd: str, run_id: str, timeout: int,
    ) -> str:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._running_processes[run_id] = proc

        try:
            stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return stdout_bytes.decode()
        except asyncio.TimeoutError:
            proc.terminate()
            raise

    async def _run_cmd(self, cmd: list[str], cwd: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            msg = f"Command failed: {' '.join(cmd)}\n{stderr.decode()}"
            raise RuntimeError(msg)
        return stdout.decode()

    async def _create_pr(
        self, cwd: str, project: ProjectConfig, task_name: str,
        branch: str, autonomy: str,
    ) -> str | None:
        # Check if branch has commits ahead of base (Claude already commits during execution)
        log_output = await self._run_cmd(
            ["git", "log", f"{project.base_branch}..HEAD", "--oneline"], cwd=cwd,
        )
        if not log_output.strip():
            return None

        # Push branch
        await self._run_cmd(["git", "push", "-u", "origin", branch], cwd=cwd)

        # Create PR
        pr_cmd = [
            "gh", "pr", "create",
            "--title", f"[agents] {project.name}/{task_name}",
            "--body", f"Automated by Background Agent Runner\n\nTask: {task_name}\nProject: {project.name}",
            "--base", project.base_branch,
        ]
        pr_output = await self._run_cmd(pr_cmd, cwd=cwd)
        pr_url = pr_output.strip()

        if autonomy == "auto-merge":
            try:
                await self._run_cmd(["gh", "pr", "merge", "--auto", "--squash", pr_url], cwd=cwd)
            except RuntimeError:
                logger.warning("Failed to enable auto-merge for %s", pr_url)

        return pr_url
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run python -m pytest tests/test_executor.py -v
```

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff check src/ tests/ && uv run pyright src/
```

- [ ] **Step 6: Commit**

```bash
git add src/agents/executor.py tests/test_executor.py
git commit -m "feat: add executor with worktree isolation and claude CLI invocation"
```

---

## Chunk 3: Wiring (Webhooks + Scheduler + Main)

### Task 8: GitHub Webhook Handler

**Files:**
- Create: `src/agents/webhooks/__init__.py`
- Create: `src/agents/webhooks/github.py`
- Create: `tests/test_webhooks/__init__.py`
- Create: `tests/test_webhooks/test_github.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_webhooks/test_github.py
import hashlib
import hmac
import json
import pytest


def test_verify_signature_valid():
    from agents.webhooks.github import verify_github_signature

    secret = "test-secret"
    body = b'{"action": "completed"}'
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    assert verify_github_signature(body, sig, secret) is True


def test_verify_signature_invalid():
    from agents.webhooks.github import verify_github_signature

    assert verify_github_signature(b"body", "sha256=bad", "secret") is False


def test_match_trigger_basic():
    from agents.webhooks.github import match_github_event
    from agents.models import TaskConfig, TriggerConfig

    task = TaskConfig(
        description="fix ci",
        prompt="fix it",
        trigger=TriggerConfig(
            type="github",
            events=["check_suite.completed"],
            filter={"conclusion": "failure"},
        ),
    )

    # Matching event
    assert match_github_event(
        event_type="check_suite",
        action="completed",
        payload={"conclusion": "failure"},
        task=task,
    ) is True


def test_match_trigger_wrong_event():
    from agents.webhooks.github import match_github_event
    from agents.models import TaskConfig, TriggerConfig

    task = TaskConfig(
        description="fix ci",
        prompt="fix it",
        trigger=TriggerConfig(type="github", events=["check_suite.completed"]),
    )

    assert match_github_event(
        event_type="push", action=None, payload={}, task=task,
    ) is False


def test_match_trigger_filter_mismatch():
    from agents.webhooks.github import match_github_event
    from agents.models import TaskConfig, TriggerConfig

    task = TaskConfig(
        description="fix ci",
        prompt="fix it",
        trigger=TriggerConfig(
            type="github",
            events=["check_suite.completed"],
            filter={"conclusion": "failure"},
        ),
    )

    assert match_github_event(
        event_type="check_suite", action="completed",
        payload={"conclusion": "success"},
        task=task,
    ) is False


def test_extract_github_variables():
    from agents.webhooks.github import extract_github_variables

    payload = {
        "check_suite": {"head_branch": "feat/login", "head_sha": "abc123"},
        "repository": {"full_name": "org/repo"},
        "action": "completed",
    }

    variables = extract_github_variables("check_suite", payload)
    assert variables["branch"] == "feat/login"
    assert variables["sha"] == "abc123"
    assert variables["repo_full_name"] == "org/repo"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
uv run python -m pytest tests/test_webhooks/test_github.py -v
```

- [ ] **Step 3: Create __init__.py files**

```python
# src/agents/webhooks/__init__.py
```

```python
# tests/test_webhooks/__init__.py
```

- [ ] **Step 4: Implement GitHub webhook handler**

```python
# src/agents/webhooks/github.py
import hashlib
import hmac

from agents.models import TaskConfig


def verify_github_signature(body: bytes, signature: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def match_github_event(
    event_type: str,
    action: str | None,
    payload: dict,
    task: TaskConfig,
) -> bool:
    if task.trigger is None or task.trigger.type != "github":
        return False

    event_key = f"{event_type}.{action}" if action else event_type

    if event_key not in task.trigger.events and event_type not in task.trigger.events:
        return False

    for filter_key, filter_value in task.trigger.filter.items():
        if str(payload.get(filter_key, "")) != filter_value:
            return False

    return True


def extract_github_variables(event_type: str, payload: dict) -> dict[str, str]:
    variables: dict[str, str] = {}

    repo = payload.get("repository", {})
    variables["repo_full_name"] = repo.get("full_name", "")

    if event_type == "check_suite":
        suite = payload.get("check_suite", {})
        variables["branch"] = suite.get("head_branch", "")
        variables["sha"] = suite.get("head_sha", "")
        variables["conclusion"] = suite.get("conclusion", "")

    elif event_type == "pull_request":
        pr = payload.get("pull_request", {})
        variables["branch"] = pr.get("head", {}).get("ref", "")
        variables["pr_number"] = str(pr.get("number", ""))
        variables["pr_title"] = pr.get("title", "")
        variables["pr_url"] = pr.get("html_url", "")

    elif event_type == "issues":
        issue = payload.get("issue", {})
        variables["issue_number"] = str(issue.get("number", ""))
        variables["issue_title"] = issue.get("title", "")
        variables["issue_body"] = issue.get("body", "")

    return variables
```

- [ ] **Step 5: Run tests — verify they pass**

```bash
uv run python -m pytest tests/test_webhooks/test_github.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/agents/webhooks/ tests/test_webhooks/
git commit -m "feat: add GitHub webhook handler with HMAC verification"
```

---

### Task 9: Linear Webhook Handler

**Files:**
- Create: `src/agents/webhooks/linear.py`
- Create: `tests/test_webhooks/test_linear.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_webhooks/test_linear.py
import pytest


def test_match_linear_event():
    from agents.webhooks.linear import match_linear_event
    from agents.models import TaskConfig, TriggerConfig

    task = TaskConfig(
        description="handle issue",
        prompt="work on {{issue_title}}",
        trigger=TriggerConfig(
            type="linear",
            events=["Issue.update"],
            filter={"status": "In Progress"},
        ),
    )

    assert match_linear_event(
        event_type="Issue",
        action="update",
        payload={"status": "In Progress"},
        task=task,
    ) is True


def test_match_linear_event_wrong_action():
    from agents.webhooks.linear import match_linear_event
    from agents.models import TaskConfig, TriggerConfig

    task = TaskConfig(
        description="t", prompt="p",
        trigger=TriggerConfig(type="linear", events=["Issue.create"]),
    )

    assert match_linear_event(
        event_type="Issue", action="update", payload={}, task=task,
    ) is False


def test_extract_linear_variables():
    from agents.webhooks.linear import extract_linear_variables

    payload = {
        "data": {
            "id": "ISS-123",
            "title": "Fix login bug",
            "description": "Users can't log in",
            "assignee": {"name": "Vini"},
            "state": {"name": "In Progress"},
        },
    }

    variables = extract_linear_variables(payload)
    assert variables["issue_id"] == "ISS-123"
    assert variables["issue_title"] == "Fix login bug"
    assert variables["assignee"] == "Vini"
    assert variables["status"] == "In Progress"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
uv run python -m pytest tests/test_webhooks/test_linear.py -v
```

- [ ] **Step 3: Implement Linear webhook handler**

```python
# src/agents/webhooks/linear.py
import hashlib
import hmac

from agents.models import TaskConfig


def verify_linear_signature(body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def match_linear_event(
    event_type: str,
    action: str,
    payload: dict,
    task: TaskConfig,
) -> bool:
    if task.trigger is None or task.trigger.type != "linear":
        return False

    event_key = f"{event_type}.{action}"
    if event_key not in task.trigger.events:
        return False

    for filter_key, filter_value in task.trigger.filter.items():
        if str(payload.get(filter_key, "")) != filter_value:
            return False

    return True


def extract_linear_variables(payload: dict) -> dict[str, str]:
    data = payload.get("data", {})
    assignee = data.get("assignee", {})
    state = data.get("state", {})

    return {
        "issue_id": data.get("id", ""),
        "issue_title": data.get("title", ""),
        "issue_description": data.get("description", ""),
        "assignee": assignee.get("name", "") if isinstance(assignee, dict) else "",
        "status": state.get("name", "") if isinstance(state, dict) else "",
    }
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run python -m pytest tests/test_webhooks/test_linear.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/agents/webhooks/linear.py tests/test_webhooks/test_linear.py
git commit -m "feat: add Linear webhook handler"
```

---

### Task 10: Scheduler

**Files:**
- Create: `src/agents/scheduler.py`
- Create: `tests/test_scheduler.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_scheduler.py
import pytest


def test_parse_cron_fields():
    from agents.scheduler import parse_cron_to_apscheduler

    fields = parse_cron_to_apscheduler("0 3 * * MON")
    assert fields["minute"] == "0"
    assert fields["hour"] == "3"
    assert fields["day"] == "*"
    assert fields["month"] == "*"
    assert fields["day_of_week"] == "MON"


def test_parse_cron_every_hour():
    from agents.scheduler import parse_cron_to_apscheduler

    fields = parse_cron_to_apscheduler("30 * * * *")
    assert fields["minute"] == "30"
    assert fields["hour"] == "*"


def test_build_job_id():
    from agents.scheduler import build_job_id

    assert build_job_id("sekit", "dep-update") == "sekit:dep-update"


def test_collect_scheduled_tasks():
    from agents.scheduler import collect_scheduled_tasks
    from agents.models import ProjectConfig, TaskConfig, TriggerConfig

    projects = {
        "sekit": ProjectConfig(
            name="sekit", repo="/tmp/sekit",
            tasks={
                "dep-update": TaskConfig(
                    description="t", prompt="p", schedule="0 3 * * MON",
                ),
                "ci-fix": TaskConfig(
                    description="t", prompt="p",
                    trigger=TriggerConfig(type="github", events=["push"]),
                ),
            },
        ),
    }

    scheduled = collect_scheduled_tasks(projects)
    assert len(scheduled) == 1
    assert scheduled[0] == ("sekit", "dep-update", "0 3 * * MON")
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
uv run python -m pytest tests/test_scheduler.py -v
```

- [ ] **Step 3: Implement scheduler**

```python
# src/agents/scheduler.py
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from agents.models import ProjectConfig

logger = logging.getLogger(__name__)


def parse_cron_to_apscheduler(cron_expr: str) -> dict[str, str]:
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        msg = f"Invalid cron expression: {cron_expr}"
        raise ValueError(msg)

    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }


def build_job_id(project_name: str, task_name: str) -> str:
    return f"{project_name}:{task_name}"


def collect_scheduled_tasks(
    projects: dict[str, ProjectConfig],
) -> list[tuple[str, str, str]]:
    """Returns list of (project_name, task_name, cron_expression) for scheduled tasks."""
    result: list[tuple[str, str, str]] = []
    for project_name, project in projects.items():
        for task_name, task in project.tasks.items():
            if task.schedule:
                result.append((project_name, task_name, task.schedule))
    return result


def create_scheduler(db_path: str) -> AsyncIOScheduler:
    jobstores = {
        "default": SQLAlchemyJobStore(url=f"sqlite:///{db_path}"),
    }
    return AsyncIOScheduler(jobstores=jobstores)


def register_jobs(
    scheduler: AsyncIOScheduler,
    projects: dict[str, ProjectConfig],
    run_task_callback: object,
) -> None:
    scheduled = collect_scheduled_tasks(projects)

    # Remove old jobs
    existing_jobs = {job.id for job in scheduler.get_jobs()}

    for project_name, task_name, cron_expr in scheduled:
        job_id = build_job_id(project_name, task_name)
        cron_fields = parse_cron_to_apscheduler(cron_expr)

        if job_id in existing_jobs:
            scheduler.reschedule_job(job_id, trigger="cron", **cron_fields)
            existing_jobs.discard(job_id)
        else:
            scheduler.add_job(
                run_task_callback,
                trigger="cron",
                id=job_id,
                kwargs={"project_name": project_name, "task_name": task_name},
                **cron_fields,
                replace_existing=True,
            )

    # Remove jobs for tasks that no longer exist
    for old_id in existing_jobs:
        scheduler.remove_job(old_id)
        logger.info("Removed stale job: %s", old_id)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run python -m pytest tests/test_scheduler.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/agents/scheduler.py tests/test_scheduler.py
git commit -m "feat: add scheduler with cron parsing and job registration"
```

---

### Task 11: FastAPI Main App

**Files:**
- Create: `src/agents/main.py`
- Create: `tests/test_main.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_main.py
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from pathlib import Path


@pytest.fixture
def test_app(tmp_path):
    """Create a test FastAPI app with mocked dependencies."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
budget:
  daily_limit_usd: 10.00
  warning_threshold_usd: 7.00
  pause_on_limit: true
notifications:
  slack_webhook_url: ""
webhooks:
  github_secret: test-secret
  linear_secret: test-linear-secret
execution:
  worktree_base: /tmp/test-agents
  default_model: sonnet
  default_max_cost_usd: 5.00
  default_autonomy: pr-only
  max_concurrent: 3
  timeout_minutes: 15
  dry_run: true
server:
  host: 127.0.0.1
  port: 9090
""")

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    (projects_dir / "testproj.yaml").write_text("""
name: testproj
repo: /tmp/test-repo
tasks:
  hello:
    description: "Test task"
    schedule: "0 9 * * *"
    model: haiku
    max_cost_usd: 0.10
    prompt: "Say hello"
""")

    from agents.main import create_app

    app = create_app(
        config_path=config_file,
        projects_dir=projects_dir,
        data_dir=tmp_path / "data",
    )
    return app


@pytest.fixture
def client(test_app):
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=test_app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_status(client):
    response = await client.get("/status")
    assert response.status_code == 200
    data = response.json()
    assert "budget" in data
    assert "runs_today" in data


@pytest.mark.asyncio
async def test_status_budget(client):
    response = await client.get("/status/budget")
    assert response.status_code == 200
    data = response.json()
    assert "daily_limit_usd" in data
    assert "spent_today_usd" in data
    assert "remaining_usd" in data


@pytest.mark.asyncio
async def test_manual_trigger(client):
    response = await client.post("/tasks/testproj/hello/run")
    assert response.status_code == 202
    data = response.json()
    assert "run_id" in data


@pytest.mark.asyncio
async def test_manual_trigger_unknown_project(client):
    response = await client.post("/tasks/unknown/hello/run")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_github_webhook_no_signature(client):
    response = await client.post(
        "/webhooks/github",
        content=b'{}',
        headers={"X-GitHub-Event": "push"},
    )
    assert response.status_code == 401
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
uv run python -m pytest tests/test_main.py -v
```

- [ ] **Step 3: Implement main app**

```python
# src/agents/main.py
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request, Response, BackgroundTasks

from agents.budget import BudgetManager
from agents.config import load_global_config, load_project_configs
from agents.executor import Executor
from agents.history import HistoryDB
from agents.notifier import Notifier
from agents.models import ProjectConfig
from agents.scheduler import create_scheduler, register_jobs
from agents.webhooks.github import (
    extract_github_variables,
    match_github_event,
    verify_github_signature,
)
from agents.webhooks.linear import (
    extract_linear_variables,
    match_linear_event,
    verify_linear_signature,
)

logger = logging.getLogger(__name__)


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
    ) -> None:
        self.projects = projects
        self.executor = executor
        self.history = history
        self.budget = budget
        self.notifier = notifier
        self.github_secret = github_secret
        self.linear_secret = linear_secret
        self._semaphore: asyncio.Semaphore | None = None
        self._repo_semaphores: dict[str, asyncio.Semaphore] = {}

    def get_semaphore(self, max_concurrent: int) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(max_concurrent)
        return self._semaphore

    def get_repo_semaphore(self, repo: str) -> asyncio.Semaphore:
        if repo not in self._repo_semaphores:
            self._repo_semaphores[repo] = asyncio.Semaphore(2)  # max 2 concurrent per repo
        return self._repo_semaphores[repo]


def create_app(
    config_path: Path | None = None,
    projects_dir: Path | None = None,
    data_dir: Path | None = None,
) -> FastAPI:
    base = Path(__file__).resolve().parent.parent.parent
    config_path = config_path or base / "config.yaml"
    projects_dir = projects_dir or base / "projects"
    data_dir = data_dir or base / "data"

    config = load_global_config(config_path)
    projects = load_project_configs(projects_dir)

    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "agents.db"

    history = HistoryDB(db_path)
    budget = BudgetManager(config=config.budget, history=history)
    notifier = Notifier(webhook_url=config.notifications.slack_webhook_url)
    executor = Executor(
        config=config.execution,
        budget=budget,
        history=history,
        notifier=notifier,
        data_dir=data_dir,
    )

    state = AppState(
        projects=projects,
        executor=executor,
        history=history,
        budget=budget,
        notifier=notifier,
        github_secret=config.webhooks.github_secret,
        linear_secret=config.webhooks.linear_secret,
    )

    # --- Lifespan: start scheduler, handle shutdown ---

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Mark stale running tasks as cancelled on startup
        history.mark_running_as_cancelled()

        # Set up and start scheduler
        scheduler = create_scheduler(str(db_path))

        async def scheduled_run(project_name: str, task_name: str) -> None:
            project = state.projects.get(project_name)
            if project and task_name in project.tasks:
                async with state.get_semaphore(config.execution.max_concurrent):
                    async with state.get_repo_semaphore(project.repo):
                        await state.executor.run_task(
                            project, task_name, trigger_type="schedule",
                            variables={"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "project_name": project_name},
                        )

        register_jobs(scheduler, state.projects, scheduled_run)
        scheduler.start()
        logger.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))

        yield

        # Shutdown
        scheduler.shutdown(wait=False)
        await state.executor.shutdown()
        logger.info("Shutdown complete")

    app = FastAPI(title="Background Agent Runner", lifespan=lifespan)
    app.state.app_state = state  # type: ignore[attr-defined]

    # --- Routes ---

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/status")
    async def status() -> dict:
        budget_status = state.budget.get_status()
        runs = state.history.list_runs_today()
        return {
            "budget": budget_status.model_dump(),
            "runs_today": [r.model_dump(mode="json") for r in runs],
            "projects": list(state.projects.keys()),
        }

    @app.get("/status/budget")
    async def budget_status() -> dict:
        return state.budget.get_status().model_dump()

    @app.post("/tasks/{project_name}/{task_name}/run", status_code=202)
    async def manual_trigger(
        project_name: str, task_name: str, background_tasks: BackgroundTasks,
    ) -> dict:
        project = state.projects.get(project_name)
        if project is None:
            return Response(status_code=404, content=f"Project {project_name} not found")  # type: ignore[return-value]
        if task_name not in project.tasks:
            return Response(status_code=404, content=f"Task {task_name} not found")  # type: ignore[return-value]

        async def _run() -> None:
            async with state.get_semaphore(config.execution.max_concurrent):
                async with state.get_repo_semaphore(project.repo):
                    await state.executor.run_task(project, task_name, trigger_type="manual")

        background_tasks.add_task(_run)
        return {"run_id": f"{project_name}-{task_name}", "status": "enqueued"}

    @app.post("/webhooks/github")
    async def github_webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
        body = await request.body()
        signature = request.headers.get("X-Hub-Signature-256", "")

        if not verify_github_signature(body, signature, state.github_secret):
            return Response(status_code=401, content="Invalid signature")  # type: ignore[return-value]

        event_type = request.headers.get("X-GitHub-Event", "")
        payload = await request.json()
        action = payload.get("action")

        for project in state.projects.values():
            for task_name, task in project.tasks.items():
                if match_github_event(event_type, action, payload, task):
                    variables = extract_github_variables(event_type, payload)

                    async def _run(p: ProjectConfig = project, tn: str = task_name, v: dict = variables) -> None:
                        async with state.get_semaphore(config.execution.max_concurrent):
                            async with state.get_repo_semaphore(p.repo):
                                await state.executor.run_task(p, tn, trigger_type="github", variables=v)

                    background_tasks.add_task(_run)

        return {"status": "processed"}

    @app.post("/webhooks/linear")
    async def linear_webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
        body = await request.body()
        signature = request.headers.get("Linear-Signature", "")

        if state.linear_secret and not verify_linear_signature(body, signature, state.linear_secret):
            return Response(status_code=401, content="Invalid signature")  # type: ignore[return-value]

        payload = await request.json()
        event_type = payload.get("type", "")
        action = payload.get("action", "")

        for project in state.projects.values():
            for task_name, task in project.tasks.items():
                if match_linear_event(event_type, action, payload, task):
                    variables = extract_linear_variables(payload)

                    async def _run(p: ProjectConfig = project, tn: str = task_name, v: dict = variables) -> None:
                        async with state.get_semaphore(config.execution.max_concurrent):
                            async with state.get_repo_semaphore(p.repo):
                                await state.executor.run_task(p, tn, trigger_type="linear", variables=v)

                    background_tasks.add_task(_run)

        return {"status": "processed"}

    @app.post("/runs/{run_id}/cancel")
    async def cancel_run(run_id: str) -> dict:
        cancelled = await state.executor.cancel_run(run_id)
        if not cancelled:
            return Response(status_code=404, content="Run not found or not running")  # type: ignore[return-value]
        return {"status": "cancelled"}

    return app
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run python -m pytest tests/test_main.py -v
```

- [ ] **Step 5: Run ALL tests**

```bash
uv run python -m pytest tests/ -v
```

- [ ] **Step 6: Lint and type-check everything**

```bash
uv run ruff check src/ tests/ && uv run ruff format src/ tests/ && uv run pyright src/
```

- [ ] **Step 7: Commit**

```bash
git add src/agents/main.py tests/test_main.py
git commit -m "feat: add FastAPI app with webhook routes and status endpoints"
```

---

### Task 12: Entry Point and Run Script

**Files:**
- Modify: `pyproject.toml` (add script entry)

- [ ] **Step 1: Add entry point to pyproject.toml**

Add to `pyproject.toml`:
```toml
[project.scripts]
agents = "agents.main:run"
```

- [ ] **Step 2: Add run function to main.py**

Append to `src/agents/main.py`:

```python
def run() -> None:
    import uvicorn

    base = Path.cwd()
    config = load_global_config(base / "config.yaml")
    app = create_app(
        config_path=base / "config.yaml",
        projects_dir=base / "projects",
        data_dir=base / "data",
    )
    uvicorn.run(app, host=config.server.host, port=config.server.port)
```

- [ ] **Step 3: Verify it starts**

```bash
cd /Users/vini/Developer/agents
uv run agents &
sleep 2
curl http://localhost:8080/health
kill %1
```

Expected: `{"status":"ok"}`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml src/agents/main.py
git commit -m "feat: add CLI entry point"
```

---

### Task 13: Smoke Test with Real Config

**Files:**
- Create: `projects/sekit.yaml` (real project config)
- Modify: `config.yaml` (set dry_run: true)

- [ ] **Step 1: Create real project config for Sekit**

```yaml
# projects/sekit.yaml
name: sekit
repo: /Users/vini/Developer/sekit
base_branch: main
branch_prefix: agents/
notify: slack

tasks:
  dep-update:
    description: "Update dependencies and run tests"
    schedule: "0 3 * * MON"
    model: haiku
    max_cost_usd: 1.00
    autonomy: auto-merge
    prompt: |
      Update all dependencies in this monorepo.
      For each app, run the appropriate update command.
      Then run `just check-all`.
      If all tests pass, commit the changes.

  lint-fix:
    description: "Fix lint issues across all apps"
    schedule: "0 4 * * FRI"
    model: haiku
    max_cost_usd: 0.50
    autonomy: auto-merge
    prompt: |
      Run linters across all apps in this monorepo:
      - `just lint-web`, `just lint-api`, `just lint-agents`
      Fix any auto-fixable issues and commit.
```

- [ ] **Step 2: Enable dry_run in config.yaml**

Verify `dry_run: true` is set in `config.yaml` under `execution`.

- [ ] **Step 3: Start the server and trigger manually**

```bash
cd /Users/vini/Developer/agents
uv run agents &
sleep 2
curl -X POST http://localhost:8080/tasks/sekit/dep-update/run
curl http://localhost:8080/status
kill %1
```

- [ ] **Step 4: Verify status output shows the dry run**

Check that the status response includes a run record with status "success" and cost 0.0.

- [ ] **Step 5: Commit**

```bash
git add projects/sekit.yaml
git commit -m "feat: add Sekit project config for background agents"
```

---

### Task 14: Final Verification

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/vini/Developer/agents
uv run python -m pytest tests/ -v --tb=short
```

All tests must pass.

- [ ] **Step 2: Run linter and type checker**

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run pyright src/
```

No errors.

- [ ] **Step 3: Verify project structure matches spec**

```bash
find src/ tests/ projects/ -type f | sort
```

Verify it matches the spec's project structure.

- [ ] **Step 4: Final commit if any fixes were needed**

```bash
git add -A && git commit -m "chore: final cleanup and verification"
```
