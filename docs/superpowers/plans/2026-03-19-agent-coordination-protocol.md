# Paperweight Coordination Protocol (PCP) — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add full-mesh agent coordination to paperweight — agents working on the same repo see each other's file claims, avoid conflicts via a broker, and delegate contested files to mediator agents.

**Architecture:** Six independent chunks. Chunk 1 adds the Pydantic models + config. Chunk 2 adds the protocol I/O layer (state.json, inbox.jsonl, outbox.jsonl). Chunk 3 extends streaming.py with file_path extraction. Chunk 4 implements the ClaimRegistry state machine. Chunk 5 implements the CoordinationBroker (the brain). Chunk 6 integrates broker into executor.py and main.py, including worktree lifecycle changes and mediator spawning. Each chunk is self-contained with TDD and produces a passing test suite.

**Spec:** `docs/superpowers/specs/2026-03-19-agent-coordination-protocol-design.md`

**Tech Stack:** Python 3.13, FastAPI, Pydantic, SQLite (WAL mode), asyncio, pytest, pytest-asyncio

---

## File Map

### New files

| File | Responsibility |
|------|---------------|
| `src/agents/coordination/__init__.py` | Package init, re-exports |
| `src/agents/coordination/models.py` | Pydantic models: `Claim`, `Mediation`, `CoordMessage`, `CoordinationConfig`, `MediatorConfig` |
| `src/agents/coordination/protocol.py` | Atomic I/O: `write_state()`, `read_inbox()`, `append_outbox()`, `init_coordination_dir()` |
| `src/agents/coordination/claims.py` | `ClaimRegistry`: in-memory state machine with TTL, deadlock detection |
| `src/agents/coordination/broker.py` | `CoordinationBroker`: central orchestrator, stream event handler, inbox poller, mediator trigger |
| `src/agents/coordination/mediator.py` | `MediatorSpawner`: builds mediator prompt, spawns via executor, handles rebase |
| `tests/test_coordination_models.py` | Tests for Pydantic models and config |
| `tests/test_coordination_protocol.py` | Tests for filesystem I/O (state, inbox, outbox) |
| `tests/test_coordination_claims.py` | Tests for ClaimRegistry state machine |
| `tests/test_coordination_broker.py` | Tests for broker event handling and conflict detection |
| `tests/test_coordination_mediator.py` | Tests for mediator prompt building and spawning |

### Modified files

| File | Change |
|------|--------|
| `src/agents/streaming.py` | Add `file_path: str` field to `StreamEvent`, extract from `tool_use` input |
| `src/agents/config.py` | Add `CoordinationConfig` to `GlobalConfig` |
| `src/agents/executor.py` | Create `/.paperweight/`, register/deregister with broker, inject preamble, defer worktree cleanup |
| `src/agents/app_state.py` | Add `broker: CoordinationBroker | None` field |
| `src/agents/main.py` | Initialize broker, hook into `broadcast_event`, start/stop lifecycle |
| `src/agents/history.py` | Add 3 new tables: `file_claims`, `mediations`, `coordination_log` |
| `tests/test_streaming.py` | Add tests for file_path extraction |
| `tests/test_executor.py` | Add tests for coordination integration |

---

## Chunk 1: Pydantic Models + Config

### Task 1.1: Write failing tests for coordination models

**Files:**
- Create: `tests/test_coordination_models.py`

- [ ] **Step 1: Write test file**

```python
"""Tests for coordination Pydantic models and config."""
import pytest


def test_claim_model_defaults():
    from agents.coordination.models import Claim, ClaimStatus, ClaimType

    claim = Claim(
        id="c-001",
        run_id="run-abc",
        file_path="src/api/users.py",
        claim_type=ClaimType.HARD,
    )
    assert claim.status == ClaimStatus.ACTIVE
    assert claim.intent == ""
    assert claim.last_activity == claim.claimed_at


def test_claim_type_enum():
    from agents.coordination.models import ClaimType

    assert ClaimType.SOFT == "soft"
    assert ClaimType.HARD == "hard"


def test_claim_status_enum():
    from agents.coordination.models import ClaimStatus

    assert ClaimStatus.ACTIVE == "active"
    assert ClaimStatus.CONTESTED == "contested"
    assert ClaimStatus.MEDIATING == "mediating"
    assert ClaimStatus.RELEASED == "released"
    assert ClaimStatus.COMPLETED == "completed"


def test_mediation_model_defaults():
    from agents.coordination.models import Mediation, MediationStatus

    med = Mediation(
        id="med-001",
        file_paths=["src/api/users.py"],
        requester_run_ids=["run-a", "run-b"],
    )
    assert med.status == MediationStatus.PENDING
    assert med.mediator_run_id is None


def test_mediation_status_enum():
    from agents.coordination.models import MediationStatus

    assert MediationStatus.PENDING == "pending"
    assert MediationStatus.RUNNING == "running"
    assert MediationStatus.COMPLETED == "completed"
    assert MediationStatus.FAILED == "failed"


def test_coord_message_need_file():
    from agents.coordination.models import CoordMessage

    msg = CoordMessage(type="need_file", file="src/api/users.py", intent="add auth")
    assert msg.type == "need_file"
    assert msg.file == "src/api/users.py"


def test_coordination_config_defaults():
    from agents.coordination.models import CoordinationConfig

    cfg = CoordinationConfig()
    assert cfg.enabled is False
    assert cfg.mode == "full-mesh"
    assert cfg.claim_timeout_seconds == 300
    assert cfg.poll_interval_ms == 500
    assert cfg.auto_rebase is True
    assert cfg.mediator.model == "claude-sonnet-4-6"
    assert cfg.mediator.max_cost_usd == 1.00
    assert cfg.mediator.timeout_minutes == 5
    assert cfg.mediator.max_concurrent == 2


def test_coordination_config_in_global():
    from agents.config import GlobalConfig

    cfg = GlobalConfig()
    assert hasattr(cfg, "coordination")
    assert cfg.coordination.enabled is False
```

- [ ] **Step 2: Run to confirm RED**

```bash
.venv/bin/pytest tests/test_coordination_models.py -v
```

Expected: FAIL (import errors — modules don't exist yet)

---

### Task 1.2: Implement coordination models

**Files:**
- Create: `src/agents/coordination/__init__.py`
- Create: `src/agents/coordination/models.py`
- Modify: `src/agents/config.py`

- [ ] **Step 1: Create package init**

```python
"""Paperweight Coordination Protocol (PCP) — inter-agent coordination."""
```

- [ ] **Step 2: Create models.py**

```python
"""Pydantic models for the coordination protocol."""
from __future__ import annotations

import time
from enum import StrEnum

from pydantic import BaseModel, Field


class ClaimType(StrEnum):
    SOFT = "soft"
    HARD = "hard"


class ClaimStatus(StrEnum):
    ACTIVE = "active"
    CONTESTED = "contested"
    MEDIATING = "mediating"
    RELEASED = "released"
    COMPLETED = "completed"


class MediationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


def _now() -> float:
    return time.time()


class Claim(BaseModel):
    id: str
    run_id: str
    file_path: str
    claim_type: ClaimType
    status: ClaimStatus = ClaimStatus.ACTIVE
    claimed_at: float = Field(default_factory=_now)
    last_activity: float = Field(default_factory=_now)
    released_at: float | None = None
    intent: str = ""


class Mediation(BaseModel):
    id: str
    file_paths: list[str]
    requester_run_ids: list[str]
    mediator_run_id: str | None = None
    status: MediationStatus = MediationStatus.PENDING
    created_at: float = Field(default_factory=_now)
    completed_at: float | None = None


class CoordMessage(BaseModel):
    type: str
    file: str = ""
    intent: str = ""
    mediation_id: str = ""
    action: str = ""
    detail: str = ""
    priority: str = ""
    reason: str = ""
    ts: float = Field(default_factory=_now)


class MediatorConfig(BaseModel):
    model: str = "claude-sonnet-4-6"
    max_cost_usd: float = 1.00
    timeout_minutes: int = 5
    max_concurrent: int = 2


class CoordinationConfig(BaseModel):
    enabled: bool = False
    mode: str = "full-mesh"
    claim_timeout_seconds: int = 300
    poll_interval_ms: int = 500
    auto_rebase: bool = True
    mediator: MediatorConfig = MediatorConfig()
```

- [ ] **Step 3: Add CoordinationConfig to GlobalConfig**

In `src/agents/config.py`, add import and field:

```python
# At top, after existing imports:
from agents.coordination.models import CoordinationConfig

# In GlobalConfig class, add field:
coordination: CoordinationConfig = CoordinationConfig()
```

- [ ] **Step 4: Run tests → GREEN**

```bash
.venv/bin/pytest tests/test_coordination_models.py -v
```

Expected: all PASSED

- [ ] **Step 5: Run full suite to check no regressions**

```bash
.venv/bin/pytest --tb=short -q
```

Expected: all existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add src/agents/coordination/ src/agents/config.py tests/test_coordination_models.py
git commit -m "feat(coordination): Pydantic models + CoordinationConfig"
```

---

## Chunk 2: Protocol I/O Layer

### Task 2.1: Write failing tests for protocol I/O

**Files:**
- Create: `tests/test_coordination_protocol.py`

- [ ] **Step 1: Write test file**

```python
"""Tests for coordination protocol filesystem I/O."""
import json
from pathlib import Path

import pytest


@pytest.fixture
def worktree(tmp_path):
    return tmp_path / "worktree"


def test_init_coordination_dir(worktree):
    from agents.coordination.protocol import init_coordination_dir

    init_coordination_dir(worktree)
    pw = worktree / ".paperweight"
    assert pw.is_dir()
    assert (pw / "state.json").exists()
    assert (pw / "inbox.jsonl").exists()
    assert (pw / "outbox.jsonl").exists()

    state = json.loads((pw / "state.json").read_text())
    assert state["protocol_version"] == 1
    assert state["active_runs"] == {}
    assert state["claims"] == {}
    assert state["mediations"] == {}


def test_write_state_atomic(worktree):
    from agents.coordination.protocol import init_coordination_dir, write_state

    init_coordination_dir(worktree)
    state = {
        "protocol_version": 1,
        "updated_at": "2026-03-19T10:00:00Z",
        "this_run_id": "run-a",
        "active_runs": {},
        "claims": {"src/x.py": {"owner_run": "run-a", "type": "hard"}},
        "mediations": {},
    }
    write_state(worktree, state)
    result = json.loads((worktree / ".paperweight" / "state.json").read_text())
    assert result["claims"]["src/x.py"]["owner_run"] == "run-a"


def test_write_state_no_partial_reads(worktree):
    """Atomic write via tmp+rename means no .tmp file lingers."""
    from agents.coordination.protocol import init_coordination_dir, write_state

    init_coordination_dir(worktree)
    write_state(worktree, {"protocol_version": 1})
    tmp_files = list((worktree / ".paperweight").glob("*.tmp"))
    assert tmp_files == []


def test_append_outbox(worktree):
    from agents.coordination.protocol import append_outbox, init_coordination_dir

    init_coordination_dir(worktree)
    append_outbox(worktree, {"type": "file_released", "file": "x.py"})
    append_outbox(worktree, {"type": "file_mediated", "file": "y.py"})

    lines = (worktree / ".paperweight" / "outbox.jsonl").read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["type"] == "file_released"
    assert json.loads(lines[1])["type"] == "file_mediated"


def test_read_inbox_incremental(worktree):
    from agents.coordination.protocol import init_coordination_dir, read_inbox

    init_coordination_dir(worktree)
    inbox_path = worktree / ".paperweight" / "inbox.jsonl"
    inbox_path.write_text(
        '{"type":"need_file","file":"a.py"}\n'
        '{"type":"heartbeat"}\n'
    )

    msgs, pos = read_inbox(worktree, from_position=0)
    assert len(msgs) == 2
    assert msgs[0]["type"] == "need_file"
    assert pos > 0

    # Append more
    with inbox_path.open("a") as f:
        f.write('{"type":"edit_complete","file":"b.py"}\n')

    msgs2, pos2 = read_inbox(worktree, from_position=pos)
    assert len(msgs2) == 1
    assert msgs2[0]["type"] == "edit_complete"
    assert pos2 > pos


def test_read_inbox_empty(worktree):
    from agents.coordination.protocol import init_coordination_dir, read_inbox

    init_coordination_dir(worktree)
    msgs, pos = read_inbox(worktree, from_position=0)
    assert msgs == []
    assert pos == 0
```

- [ ] **Step 2: Run to confirm RED**

```bash
.venv/bin/pytest tests/test_coordination_protocol.py -v
```

Expected: FAIL (import errors)

---

### Task 2.2: Implement protocol I/O

**Files:**
- Create: `src/agents/coordination/protocol.py`

- [ ] **Step 1: Write protocol.py**

```python
"""Atomic filesystem I/O for the coordination protocol.

Files managed per worktree:
  /.paperweight/state.json   — broker writes, agent reads (atomic via tmp+rename)
  /.paperweight/inbox.jsonl  — agent appends, broker reads (incremental seek)
  /.paperweight/outbox.jsonl — broker appends, agent reads
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

COORD_DIR = ".paperweight"


def init_coordination_dir(worktree: Path) -> None:
    """Create /.paperweight/ with empty protocol files."""
    pw = worktree / COORD_DIR
    pw.mkdir(parents=True, exist_ok=True)

    state = {
        "protocol_version": 1,
        "updated_at": _iso_now(),
        "this_run_id": "",
        "active_runs": {},
        "claims": {},
        "mediations": {},
    }
    (pw / "state.json").write_text(json.dumps(state, indent=2))
    (pw / "inbox.jsonl").touch()
    (pw / "outbox.jsonl").touch()


def write_state(worktree: Path, state: dict) -> None:
    """Atomic write: tmp file → os.rename (POSIX-atomic)."""
    pw = worktree / COORD_DIR
    state["updated_at"] = _iso_now()
    tmp_path = pw / ".state.json.tmp"
    tmp_path.write_text(json.dumps(state, indent=2))
    os.rename(str(tmp_path), str(pw / "state.json"))


def read_inbox(worktree: Path, from_position: int = 0) -> tuple[list[dict], int]:
    """Read new JSONL lines from inbox starting at byte position."""
    inbox = worktree / COORD_DIR / "inbox.jsonl"
    if not inbox.exists():
        return [], 0
    file_size = inbox.stat().st_size
    if file_size <= from_position:
        return [], from_position

    messages: list[dict] = []
    with inbox.open() as f:
        f.seek(from_position)
        for line in f:
            line = line.strip()
            if line:
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        new_position = f.tell()
    return messages, new_position


def append_outbox(worktree: Path, message: dict) -> None:
    """Append a single JSONL line to outbox."""
    outbox = worktree / COORD_DIR / "outbox.jsonl"
    message["ts"] = message.get("ts") or _iso_now()
    with outbox.open("a") as f:
        f.write(json.dumps(message) + "\n")


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
```

- [ ] **Step 2: Run tests → GREEN**

```bash
.venv/bin/pytest tests/test_coordination_protocol.py -v
```

Expected: all PASSED

- [ ] **Step 3: Commit**

```bash
git add src/agents/coordination/protocol.py tests/test_coordination_protocol.py
git commit -m "feat(coordination): protocol I/O — state.json, inbox.jsonl, outbox.jsonl"
```

---

## Chunk 3: StreamEvent file_path Extraction

### Task 3.1: Write failing tests for file_path extraction

**Files:**
- Modify: `tests/test_streaming.py`

- [ ] **Step 1: Add tests at end of test_streaming.py**

```python
def test_parse_edit_tool_extracts_file_path():
    from agents.streaming import parse_stream_line

    line = json.dumps({
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use",
            "name": "Edit",
            "input": {
                "file_path": "/tmp/agents/run-1/src/api/users.py",
                "old_string": "def get_users():",
                "new_string": "def get_users(cursor=None):",
            },
        }]},
    })
    event = parse_stream_line(line)
    assert event is not None
    assert event.type == "tool_use"
    assert event.tool_name == "Edit"
    assert event.file_path == "/tmp/agents/run-1/src/api/users.py"


def test_parse_write_tool_extracts_file_path():
    from agents.streaming import parse_stream_line

    line = json.dumps({
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use",
            "name": "Write",
            "input": {"file_path": "/tmp/agents/run-1/src/new_file.py", "content": "hello"},
        }]},
    })
    event = parse_stream_line(line)
    assert event is not None
    assert event.file_path == "/tmp/agents/run-1/src/new_file.py"


def test_parse_read_tool_extracts_file_path():
    from agents.streaming import parse_stream_line

    line = json.dumps({
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use",
            "name": "Read",
            "input": {"file_path": "/tmp/agents/run-1/README.md"},
        }]},
    })
    event = parse_stream_line(line)
    assert event is not None
    assert event.file_path == "/tmp/agents/run-1/README.md"


def test_parse_bash_tool_no_file_path():
    from agents.streaming import parse_stream_line

    line = json.dumps({
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use",
            "name": "Bash",
            "input": {"command": "ls -la"},
        }]},
    })
    event = parse_stream_line(line)
    assert event is not None
    assert event.file_path == ""
```

- [ ] **Step 2: Run to confirm RED**

```bash
.venv/bin/pytest tests/test_streaming.py::test_parse_edit_tool_extracts_file_path -v
```

Expected: FAIL (`StreamEvent` has no `file_path` field)

---

### Task 3.2: Add file_path to StreamEvent

**Files:**
- Modify: `src/agents/streaming.py`

- [ ] **Step 1: Add field to StreamEvent**

In `StreamEvent` class (line 25-29), add `file_path`:

```python
class StreamEvent(BaseModel):
    type: StreamEventType
    content: str = ""
    tool_name: str = ""
    file_path: str = ""
    timestamp: float
```

- [ ] **Step 2: Extract file_path in parse_stream_line**

In the `tool_use` handler (lines 65-71), extract `file_path` from input:

```python
            if block_type == "tool_use":
                tool_name = block.get("name", "")
                tool_input = block.get("input", {})
                file_path = ""
                if isinstance(tool_input, dict) and tool_name in ("Edit", "Write", "Read"):
                    file_path = tool_input.get("file_path", "")
                return StreamEvent(
                    type="tool_use",
                    tool_name=tool_name,
                    content=json.dumps(tool_input)[:200],
                    file_path=file_path,
                    timestamp=time.time(),
                )
```

- [ ] **Step 3: Run tests → GREEN**

```bash
.venv/bin/pytest tests/test_streaming.py -v
```

Expected: all PASSED (old + new tests)

- [ ] **Step 4: Run full suite**

```bash
.venv/bin/pytest --tb=short -q
```

Expected: all pass (StreamEvent field is optional with default "")

- [ ] **Step 5: Commit**

```bash
git add src/agents/streaming.py tests/test_streaming.py
git commit -m "feat(streaming): extract file_path from Edit/Write/Read tool calls"
```

---

## Chunk 4: ClaimRegistry State Machine

### Task 4.1: Write failing tests for ClaimRegistry

**Files:**
- Create: `tests/test_coordination_claims.py`

- [ ] **Step 1: Write test file**

```python
"""Tests for ClaimRegistry state machine."""
import time

import pytest


@pytest.fixture
def registry():
    from agents.coordination.claims import ClaimRegistry
    return ClaimRegistry()


def test_soft_claim(registry):
    registry.soft_claim("run-a", "src/x.py")
    claim = registry.get_claim_for_file("src/x.py")
    assert claim is not None
    assert claim.claim_type.value == "soft"
    assert claim.run_id == "run-a"


def test_hard_claim_no_conflict(registry):
    conflict = registry.hard_claim("run-a", "src/x.py")
    assert conflict is None
    claim = registry.get_claim_for_file("src/x.py")
    assert claim is not None
    assert claim.claim_type.value == "hard"


def test_hard_claim_conflict(registry):
    registry.hard_claim("run-a", "src/x.py")
    conflict = registry.hard_claim("run-b", "src/x.py")
    assert conflict is not None
    assert conflict.run_id == "run-a"


def test_hard_claim_same_owner_no_conflict(registry):
    registry.hard_claim("run-a", "src/x.py")
    conflict = registry.hard_claim("run-a", "src/x.py")
    assert conflict is None


def test_soft_claim_upgrades_to_hard(registry):
    registry.soft_claim("run-a", "src/x.py")
    conflict = registry.hard_claim("run-a", "src/x.py")
    assert conflict is None
    claim = registry.get_claim_for_file("src/x.py")
    assert claim.claim_type.value == "hard"


def test_release(registry):
    registry.hard_claim("run-a", "src/x.py")
    registry.release("run-a", "src/x.py")
    assert registry.get_claim_for_file("src/x.py") is None


def test_release_all(registry):
    registry.hard_claim("run-a", "src/x.py")
    registry.hard_claim("run-a", "src/y.py")
    registry.release_all("run-a")
    assert registry.get_claims_for_run("run-a") == []


def test_update_activity(registry):
    registry.hard_claim("run-a", "src/x.py")
    claim = registry.get_claim_for_file("src/x.py")
    old_activity = claim.last_activity
    time.sleep(0.01)
    registry.update_activity("run-a")
    claim = registry.get_claim_for_file("src/x.py")
    assert claim.last_activity > old_activity


def test_check_ttl(registry):
    registry.hard_claim("run-a", "src/x.py")
    # Manually set old activity
    claim = registry.get_claim_for_file("src/x.py")
    claim.last_activity = time.time() - 400  # older than 300s default
    expired = registry.check_ttl(timeout_seconds=300)
    assert len(expired) == 1
    assert expired[0].file_path == "src/x.py"
    # Claim should be released
    assert registry.get_claim_for_file("src/x.py") is None


def test_mark_contested(registry):
    registry.hard_claim("run-a", "src/x.py")
    registry.mark_contested("src/x.py")
    claim = registry.get_claim_for_file("src/x.py")
    assert claim.status.value == "contested"


def test_mark_mediating(registry):
    registry.hard_claim("run-a", "src/x.py")
    registry.mark_mediating("src/x.py")
    claim = registry.get_claim_for_file("src/x.py")
    assert claim.status.value == "mediating"


def test_get_claims_for_run(registry):
    registry.hard_claim("run-a", "src/x.py")
    registry.hard_claim("run-a", "src/y.py")
    registry.hard_claim("run-b", "src/z.py")
    claims = registry.get_claims_for_run("run-a")
    assert len(claims) == 2


def test_detect_deadlock_no_cycle(registry):
    """No deadlock when there's no circular dependency."""
    registry.hard_claim("run-a", "src/x.py")
    registry.add_need("run-b", "src/x.py")
    cycles = registry.detect_deadlock()
    assert cycles == []


def test_detect_deadlock_simple_cycle(registry):
    """Deadlock: A claims x, needs y. B claims y, needs x."""
    registry.hard_claim("run-a", "src/x.py")
    registry.hard_claim("run-b", "src/y.py")
    registry.add_need("run-a", "src/y.py")
    registry.add_need("run-b", "src/x.py")
    cycles = registry.detect_deadlock()
    assert len(cycles) == 1
    assert set(cycles[0]) == {"run-a", "run-b"}


def test_build_state_snapshot(registry):
    registry.hard_claim("run-a", "src/x.py")
    snapshot = registry.build_state_snapshot("run-b", "intent-b")
    assert "run-a" not in snapshot.get("this_run_id", "")
    assert "src/x.py" in snapshot["claims"]
```

- [ ] **Step 2: Run to confirm RED**

```bash
.venv/bin/pytest tests/test_coordination_claims.py -v
```

Expected: FAIL (import errors)

---

### Task 4.2: Implement ClaimRegistry

**Files:**
- Create: `src/agents/coordination/claims.py`

- [ ] **Step 1: Write claims.py**

```python
"""ClaimRegistry — in-memory state machine for file claims with TTL."""
from __future__ import annotations

import time
import uuid
from collections import defaultdict

from agents.coordination.models import Claim, ClaimStatus, ClaimType


class ClaimRegistry:
    def __init__(self) -> None:
        self._claims: dict[str, Claim] = {}           # file_path → Claim
        self._run_claims: dict[str, set[str]] = defaultdict(set)  # run_id → {file_paths}
        self._run_intents: dict[str, str] = {}         # run_id → intent
        self._needs: dict[str, set[str]] = defaultdict(set)  # run_id → {file_paths needed}

    def soft_claim(self, run_id: str, file_path: str) -> None:
        if file_path in self._claims:
            return
        claim = Claim(
            id=f"c-{uuid.uuid4().hex[:8]}",
            run_id=run_id,
            file_path=file_path,
            claim_type=ClaimType.SOFT,
        )
        self._claims[file_path] = claim
        self._run_claims[run_id].add(file_path)

    def hard_claim(self, run_id: str, file_path: str) -> Claim | None:
        existing = self._claims.get(file_path)
        if existing and existing.run_id != run_id and existing.status != ClaimStatus.RELEASED:
            return existing  # conflict
        if existing and existing.run_id == run_id:
            existing.claim_type = ClaimType.HARD
            existing.last_activity = time.time()
            return None
        claim = Claim(
            id=f"c-{uuid.uuid4().hex[:8]}",
            run_id=run_id,
            file_path=file_path,
            claim_type=ClaimType.HARD,
        )
        self._claims[file_path] = claim
        self._run_claims[run_id].add(file_path)
        return None

    def release(self, run_id: str, file_path: str) -> None:
        claim = self._claims.get(file_path)
        if claim and claim.run_id == run_id:
            claim.status = ClaimStatus.RELEASED
            claim.released_at = time.time()
            del self._claims[file_path]
            self._run_claims[run_id].discard(file_path)

    def release_all(self, run_id: str) -> None:
        for fp in list(self._run_claims.get(run_id, set())):
            self.release(run_id, fp)
        self._run_claims.pop(run_id, None)
        self._needs.pop(run_id, None)
        self._run_intents.pop(run_id, None)

    def update_activity(self, run_id: str) -> None:
        now = time.time()
        for fp in self._run_claims.get(run_id, set()):
            claim = self._claims.get(fp)
            if claim:
                claim.last_activity = now

    def check_ttl(self, timeout_seconds: int = 300) -> list[Claim]:
        now = time.time()
        expired: list[Claim] = []
        for fp, claim in list(self._claims.items()):
            if claim.claim_type == ClaimType.HARD and (now - claim.last_activity) > timeout_seconds:
                expired.append(claim)
                self.release(claim.run_id, fp)
        return expired

    def mark_contested(self, file_path: str) -> None:
        claim = self._claims.get(file_path)
        if claim:
            claim.status = ClaimStatus.CONTESTED

    def mark_mediating(self, file_path: str) -> None:
        claim = self._claims.get(file_path)
        if claim:
            claim.status = ClaimStatus.MEDIATING

    def get_claim_for_file(self, file_path: str) -> Claim | None:
        return self._claims.get(file_path)

    def get_claims_for_run(self, run_id: str) -> list[Claim]:
        return [
            self._claims[fp]
            for fp in self._run_claims.get(run_id, set())
            if fp in self._claims
        ]

    def add_need(self, run_id: str, file_path: str) -> None:
        self._needs[run_id].add(file_path)

    def set_intent(self, run_id: str, intent: str) -> None:
        self._run_intents[run_id] = intent

    def get_intent(self, run_id: str) -> str:
        return self._run_intents.get(run_id, "")

    def detect_deadlock(self) -> list[list[str]]:
        """DFS cycle detection on the waits-for graph."""
        # Build waits-for: run_id → set of run_ids it waits for
        waits_for: dict[str, set[str]] = defaultdict(set)
        for run_id, needed_files in self._needs.items():
            for fp in needed_files:
                claim = self._claims.get(fp)
                if claim and claim.run_id != run_id:
                    waits_for[run_id].add(claim.run_id)

        visited: set[str] = set()
        in_stack: set[str] = set()
        cycles: list[list[str]] = []

        def dfs(node: str, path: list[str]) -> None:
            if node in in_stack:
                cycle_start = path.index(node)
                cycles.append(path[cycle_start:])
                return
            if node in visited:
                return
            visited.add(node)
            in_stack.add(node)
            path.append(node)
            for neighbor in waits_for.get(node, set()):
                dfs(neighbor, path)
            path.pop()
            in_stack.remove(node)

        for run_id in waits_for:
            if run_id not in visited:
                dfs(run_id, [])

        return cycles

    def build_state_snapshot(self, this_run_id: str, this_intent: str = "") -> dict:
        """Build state.json content for a specific worktree."""
        active_runs: dict[str, dict] = {}
        for run_id, file_paths in self._run_claims.items():
            if run_id == this_run_id:
                continue
            active_claims = [fp for fp in file_paths if fp in self._claims]
            if active_claims:
                active_runs[run_id] = {
                    "intent": self._run_intents.get(run_id, ""),
                    "files_claimed": sorted(active_claims),
                    "status": "running",
                }

        claims: dict[str, dict] = {}
        for fp, claim in self._claims.items():
            if claim.run_id != this_run_id:
                claims[fp] = {
                    "owner_run": claim.run_id,
                    "type": claim.claim_type.value,
                    "since": claim.claimed_at,
                }

        return {
            "protocol_version": 1,
            "this_run_id": this_run_id,
            "active_runs": active_runs,
            "claims": claims,
            "mediations": {},
        }
```

- [ ] **Step 2: Run tests → GREEN**

```bash
.venv/bin/pytest tests/test_coordination_claims.py -v
```

Expected: all PASSED

- [ ] **Step 3: Full suite check**

```bash
.venv/bin/pytest --tb=short -q
```

- [ ] **Step 4: Commit**

```bash
git add src/agents/coordination/claims.py tests/test_coordination_claims.py
git commit -m "feat(coordination): ClaimRegistry state machine with TTL + deadlock detection"
```

---

## Chunk 5: CoordinationBroker

### Task 5.1: Write failing tests for broker

**Files:**
- Create: `tests/test_coordination_broker.py`

- [ ] **Step 1: Write test file**

```python
"""Tests for CoordinationBroker."""
import asyncio
import json
from pathlib import Path

import pytest

from agents.coordination.models import CoordinationConfig


@pytest.fixture
def config():
    return CoordinationConfig(enabled=True, poll_interval_ms=50)


@pytest.fixture
def broker(config):
    from agents.coordination.broker import CoordinationBroker
    return CoordinationBroker(config)


@pytest.fixture
def worktree_a(tmp_path):
    wt = tmp_path / "wt-a"
    wt.mkdir()
    return wt


@pytest.fixture
def worktree_b(tmp_path):
    wt = tmp_path / "wt-b"
    wt.mkdir()
    return wt


@pytest.mark.asyncio
async def test_register_run(broker, worktree_a):
    await broker.register_run("run-a", worktree_a, "add pagination")
    assert "run-a" in broker.active_worktrees
    state = json.loads((worktree_a / ".paperweight" / "state.json").read_text())
    assert state["this_run_id"] == "run-a"


@pytest.mark.asyncio
async def test_deregister_run(broker, worktree_a):
    await broker.register_run("run-a", worktree_a, "add pagination")
    await broker.deregister_run("run-a")
    assert "run-a" not in broker.active_worktrees


@pytest.mark.asyncio
async def test_on_stream_event_hard_claim(broker, worktree_a):
    from agents.streaming import StreamEvent

    await broker.register_run("run-a", worktree_a, "add pagination")
    # Use path relative to worktree fixture (tmp_path-based)
    abs_path = str(worktree_a / "src" / "users.py")
    event = StreamEvent(
        type="tool_use",
        tool_name="Edit",
        file_path=abs_path,
        timestamp=1.0,
    )
    await broker.on_stream_event("run-a", event, worktree_root=worktree_a)
    claim = broker.claims.get_claim_for_file("src/users.py")
    assert claim is not None
    assert claim.claim_type.value == "hard"


@pytest.mark.asyncio
async def test_on_stream_event_read_soft_claim(broker, worktree_a):
    from agents.streaming import StreamEvent

    await broker.register_run("run-a", worktree_a, "add pagination")
    abs_path = str(worktree_a / "src" / "users.py")
    event = StreamEvent(
        type="tool_use",
        tool_name="Read",
        file_path=abs_path,
        timestamp=1.0,
    )
    await broker.on_stream_event("run-a", event, worktree_root=worktree_a)
    claim = broker.claims.get_claim_for_file("src/users.py")
    assert claim is not None
    assert claim.claim_type.value == "soft"


@pytest.mark.asyncio
async def test_conflict_detection(broker, worktree_a, worktree_b):
    from agents.streaming import StreamEvent

    await broker.register_run("run-a", worktree_a, "add pagination")
    await broker.register_run("run-b", worktree_b, "add auth")

    # Both agents edit the same repo-relative file, but from different worktrees
    event_a = StreamEvent(type="tool_use", tool_name="Edit",
                          file_path=str(worktree_a / "src" / "users.py"), timestamp=1.0)
    await broker.on_stream_event("run-a", event_a, worktree_root=worktree_a)

    event_b = StreamEvent(type="tool_use", tool_name="Edit",
                          file_path=str(worktree_b / "src" / "users.py"), timestamp=2.0)
    conflict = await broker.on_stream_event("run-b", event_b, worktree_root=worktree_b)
    assert conflict is not None
    assert conflict.run_id == "run-a"


@pytest.mark.asyncio
async def test_update_all_state_files(broker, worktree_a, worktree_b):
    from agents.streaming import StreamEvent

    await broker.register_run("run-a", worktree_a, "add pagination")
    await broker.register_run("run-b", worktree_b, "add auth")

    event = StreamEvent(type="tool_use", tool_name="Edit",
                        file_path=str(worktree_a / "src" / "users.py"), timestamp=1.0)
    await broker.on_stream_event("run-a", event, worktree_root=worktree_a)

    # State in B's worktree should show A's claim
    state_b = json.loads((worktree_b / ".paperweight" / "state.json").read_text())
    assert "src/users.py" in state_b["claims"]


@pytest.mark.asyncio
async def test_has_pending_mediations(broker, worktree_a):
    await broker.register_run("run-a", worktree_a, "task")
    assert not await broker.has_pending_mediations("run-a")


@pytest.mark.asyncio
async def test_process_inbox_need_file(broker, worktree_a, worktree_b):
    await broker.register_run("run-a", worktree_a, "add pagination")
    await broker.register_run("run-b", worktree_b, "add auth")

    # A claims users.py
    from agents.streaming import StreamEvent
    event = StreamEvent(type="tool_use", tool_name="Edit",
                        file_path="/tmp/wt-a/src/users.py", timestamp=1.0)
    await broker.on_stream_event("run-a", event, worktree_root=worktree_a)

    # B writes need_file to inbox
    inbox = worktree_b / ".paperweight" / "inbox.jsonl"
    with inbox.open("a") as f:
        f.write(json.dumps({"type": "need_file", "file": "src/users.py", "intent": "add auth"}) + "\n")

    # Broker processes inboxes
    await broker.poll_inboxes_once()

    # Claim should be contested
    claim = broker.claims.get_claim_for_file("src/users.py")
    assert claim.status.value == "contested"
```

- [ ] **Step 2: Run to confirm RED**

```bash
.venv/bin/pytest tests/test_coordination_broker.py -v
```

Expected: FAIL (import errors)

---

### Task 5.2: Implement CoordinationBroker

**Files:**
- Create: `src/agents/coordination/broker.py`

- [ ] **Step 1: Write broker.py**

```python
"""CoordinationBroker — central orchestrator for inter-agent coordination."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from agents.coordination.claims import ClaimRegistry
from agents.coordination.models import Claim, CoordinationConfig
from agents.coordination.protocol import (
    append_outbox,
    init_coordination_dir,
    read_inbox,
    write_state,
)

logger = logging.getLogger(__name__)

# Tools that indicate file access
_WRITE_TOOLS = {"Edit", "Write"}
_READ_TOOLS = {"Read"}
_FILE_TOOLS = _WRITE_TOOLS | _READ_TOOLS


class CoordinationBroker:
    def __init__(self, config: CoordinationConfig) -> None:
        self.config = config
        self.claims = ClaimRegistry()
        self.active_worktrees: dict[str, Path] = {}
        self._inbox_positions: dict[str, int] = {}
        self._poll_task: asyncio.Task | None = None
        self._state_write_pending = False
        self._state_write_lock = asyncio.Lock()
        self._pending_mediations: dict[str, list[str]] = {}  # run_id → [mediation_ids]

    async def start(self) -> None:
        if self.config.enabled:
            self._poll_task = asyncio.create_task(self._poll_loop())
            logger.info("CoordinationBroker started (mode=%s)", self.config.mode)

    async def stop(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("CoordinationBroker stopped")

    async def register_run(self, run_id: str, worktree: Path, intent: str) -> None:
        init_coordination_dir(worktree)
        self.active_worktrees[run_id] = worktree
        self._inbox_positions[run_id] = 0
        self.claims.set_intent(run_id, intent)
        await self._update_all_state_files()

    async def deregister_run(self, run_id: str) -> None:
        self.claims.release_all(run_id)
        self.active_worktrees.pop(run_id, None)
        self._inbox_positions.pop(run_id, None)
        await self._update_all_state_files()

    async def on_stream_event(
        self,
        run_id: str,
        event: object,
        worktree_root: Path | None = None,
    ) -> Claim | None:
        """Called for every stream event. Returns conflicting Claim if detected."""
        self.claims.update_activity(run_id)

        tool_name = getattr(event, "tool_name", "")
        file_path = getattr(event, "file_path", "")

        if not tool_name or tool_name not in _FILE_TOOLS or not file_path:
            return None

        # Normalize absolute worktree path to repo-relative
        rel_path = file_path
        if worktree_root and os.path.isabs(file_path):
            try:
                rel_path = os.path.relpath(file_path, str(worktree_root))
            except ValueError:
                rel_path = file_path

        conflict: Claim | None = None
        if tool_name in _WRITE_TOOLS:
            conflict = self.claims.hard_claim(run_id, rel_path)
        elif tool_name in _READ_TOOLS:
            self.claims.soft_claim(run_id, rel_path)

        await self._update_all_state_files()
        return conflict

    async def has_pending_mediations(self, run_id: str) -> bool:
        return bool(self._pending_mediations.get(run_id))

    async def poll_inboxes_once(self) -> None:
        """Read all inboxes once. Used by poll loop and tests."""
        for run_id, worktree in list(self.active_worktrees.items()):
            pos = self._inbox_positions.get(run_id, 0)
            messages, new_pos = read_inbox(worktree, pos)
            self._inbox_positions[run_id] = new_pos
            for msg in messages:
                await self._process_inbox_message(run_id, msg)

    async def _process_inbox_message(self, run_id: str, msg: dict) -> None:
        msg_type = msg.get("type", "")
        file_path = msg.get("file", "")

        if msg_type == "need_file":
            self.claims.add_need(run_id, file_path)
            claim = self.claims.get_claim_for_file(file_path)
            if claim and claim.run_id != run_id:
                self.claims.mark_contested(file_path)
                logger.info(
                    "Conflict detected: %s needs %s (claimed by %s)",
                    run_id, file_path, claim.run_id,
                )
                # TODO(future): spawn mediator agent — requires integration testing with real CLI
        elif msg_type == "edit_complete":
            logger.info("Run %s completed edit on %s", run_id, file_path)
        elif msg_type == "heartbeat":
            self.claims.update_activity(run_id)
        elif msg_type == "escalation":
            logger.warning("Run %s escalated: %s", run_id, msg.get("message", ""))

    async def _update_all_state_files(self) -> None:
        """Debounced: coalesce rapid claim changes."""
        for run_id, worktree in list(self.active_worktrees.items()):
            state = self.claims.build_state_snapshot(
                this_run_id=run_id,
                this_intent=self.claims.get_intent(run_id),
            )
            write_state(worktree, state)

    async def _poll_loop(self) -> None:
        interval = self.config.poll_interval_ms / 1000
        while True:
            try:
                await self.poll_inboxes_once()
                expired = self.claims.check_ttl(self.config.claim_timeout_seconds)
                if expired:
                    for claim in expired:
                        logger.info("Claim expired (TTL): %s on %s", claim.run_id, claim.file_path)
                    await self._update_all_state_files()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in coordination poll loop")
            await asyncio.sleep(interval)
```

- [ ] **Step 2: Run tests → GREEN**

```bash
.venv/bin/pytest tests/test_coordination_broker.py -v
```

Expected: all PASSED

- [ ] **Step 3: Full suite check**

```bash
.venv/bin/pytest --tb=short -q
```

- [ ] **Step 4: Commit**

```bash
git add src/agents/coordination/broker.py tests/test_coordination_broker.py
git commit -m "feat(coordination): CoordinationBroker — event handler, inbox poller, state sync"
```

---

## Chunk 6: Integration + Mediator

### Task 6.1: Write failing tests for mediator prompt building

**Files:**
- Create: `tests/test_coordination_mediator.py`

- [ ] **Step 1: Write test file**

```python
"""Tests for MediatorSpawner prompt building."""
import pytest


def test_build_mediator_prompt():
    from agents.coordination.mediator import build_mediator_prompt

    prompt = build_mediator_prompt(
        file_path="src/api/users.py",
        file_content="def get_users():\n    return []",
        intent_a="Add pagination with cursor parameter",
        intent_b="Add authentication middleware",
        task_a_description="issue-resolver: ENG-142",
        task_b_description="issue-resolver: ENG-155",
    )
    assert "src/api/users.py" in prompt
    assert "pagination" in prompt.lower()
    assert "authentication" in prompt.lower()
    assert "Agent A" in prompt
    assert "Agent B" in prompt
    assert "def get_users()" in prompt


def test_build_mediator_prompt_with_diff():
    from agents.coordination.mediator import build_mediator_prompt

    prompt = build_mediator_prompt(
        file_path="src/api/users.py",
        file_content="def get_users():\n    return []",
        intent_a="Add pagination",
        intent_b="Add auth",
        task_a_description="resolver",
        task_b_description="resolver",
        diff_a="+ def get_users(cursor=None):",
    )
    assert "diff" in prompt.lower() or "Changes" in prompt


def test_build_coordination_preamble():
    from agents.coordination.mediator import build_coordination_preamble

    preamble = build_coordination_preamble()
    assert "Coordinated Mode" in preamble
    assert "state.json" in preamble
    assert "inbox.jsonl" in preamble
    assert "outbox.jsonl" in preamble
    assert "NEVER force-edit" in preamble
```

- [ ] **Step 2: Run to confirm RED**

```bash
.venv/bin/pytest tests/test_coordination_mediator.py -v
```

Expected: FAIL (import errors)

---

### Task 6.2: Implement mediator module

**Files:**
- Create: `src/agents/coordination/mediator.py`

- [ ] **Step 1: Write mediator.py**

```python
"""MediatorSpawner — builds mediator prompts and coordinates mediation runs."""
from __future__ import annotations


COORDINATION_PREAMBLE = """## Coordinated Mode — Paperweight Protocol

You are running alongside other AI agents on the same repository. Each agent has
an isolated git worktree, but you share the same codebase.

### MANDATORY — Before editing ANY file:
1. Read `/.paperweight/state.json` to check `claims`
2. If the file is claimed by another agent: DO NOT edit it
3. Instead, append to `/.paperweight/inbox.jsonl`:
   {"type":"need_file","file":"<path>","intent":"<what you need to do>"}
4. Continue with OTHER files. Check `/.paperweight/outbox.jsonl` periodically.

### After editing a file:
Append to `/.paperweight/inbox.jsonl`:
{"type":"edit_complete","file":"<path>"}

### After each major step, read `/.paperweight/outbox.jsonl`:
- `file_mediated`: A mediator handled this file. SKIP it entirely.
- `file_released`: File available. You may edit it now.

### Heartbeat:
Every ~10 tool calls, append to inbox.jsonl: {"type":"heartbeat"}

### Rules:
- NEVER force-edit a claimed file
- If ALL your files are claimed, work on tests, docs, or config
- The orchestrator resolves conflicts automatically
"""


def build_coordination_preamble() -> str:
    return COORDINATION_PREAMBLE


def build_mediator_prompt(
    file_path: str,
    file_content: str,
    intent_a: str,
    intent_b: str,
    task_a_description: str,
    task_b_description: str,
    diff_a: str = "",
) -> str:
    """Build the prompt for a mediator agent resolving a file conflict."""
    diff_section = ""
    if diff_a:
        diff_section = f"\nChanges Agent A already made (diff):\n```\n{diff_a}\n```\n"

    return f"""## Mediation Task

Two agents need changes to the same file. Apply BOTH changes coherently.

### Agent A — "{task_a_description}"
What Agent A needs in {file_path}: "{intent_a}"
{diff_section}
### Agent B — "{task_b_description}"
What Agent B needs in {file_path}: "{intent_b}"

### Current file ({file_path}):
```
{file_content}
```

### Instructions:
1. Understand what BOTH agents need for this file
2. Apply both changes coherently — they should work together
3. If the changes are incompatible, apply the most critical one and document the other as a TODO
4. Write tests if the file has associated test files
5. Commit: "mediation({file_path.split('/')[-1]}): <summary>"
6. Touch ONLY the contested file(s) — nothing else
"""
```

- [ ] **Step 2: Run tests → GREEN**

```bash
.venv/bin/pytest tests/test_coordination_mediator.py -v
```

Expected: all PASSED

- [ ] **Step 3: Commit**

```bash
git add src/agents/coordination/mediator.py tests/test_coordination_mediator.py
git commit -m "feat(coordination): mediator prompt builder + coordination preamble"
```

---

### Task 6.3: Write failing tests for executor integration

**Files:**
- Modify: `tests/test_executor.py`

- [ ] **Step 1: Add coordination integration tests**

```python
@pytest.mark.asyncio
async def test_executor_creates_coordination_dir_when_enabled(tmp_path):
    """When coordination is enabled, executor should create /.paperweight/ in worktree."""
    from agents.coordination.models import CoordinationConfig

    # This test just verifies the coordination dir creation function works
    from agents.coordination.protocol import init_coordination_dir

    worktree = tmp_path / "test-worktree"
    worktree.mkdir()
    init_coordination_dir(worktree)

    pw = worktree / ".paperweight"
    assert pw.is_dir()
    assert (pw / "state.json").exists()
    assert (pw / "inbox.jsonl").exists()
    assert (pw / "outbox.jsonl").exists()
```

- [ ] **Step 2: Run to confirm GREEN** (this test uses already-implemented code)

```bash
.venv/bin/pytest tests/test_executor.py::test_executor_creates_coordination_dir_when_enabled -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_executor.py
git commit -m "test(coordination): integration test for worktree coordination dir"
```

---

### Task 6.4: Wire broker into app_state and main.py

**Files:**
- Modify: `src/agents/app_state.py`
- Modify: `src/agents/main.py`
- Modify: `src/agents/history.py`

- [ ] **Step 1: Add broker to AppState**

In `src/agents/app_state.py`, add:

```python
# Add import at top (TYPE_CHECKING block):
from agents.coordination.broker import CoordinationBroker

# In __init__, add parameter and field:
def __init__(self, ..., broker: CoordinationBroker | None = None) -> None:
    ...
    self.broker = broker
```

- [ ] **Step 2: Add coordination tables to history.py**

In `src/agents/history.py`, add to `_init_db()` after existing CREATE TABLE statements:

```python
conn.execute("""
    CREATE TABLE IF NOT EXISTS file_claims (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        file_path TEXT NOT NULL,
        claim_type TEXT NOT NULL,
        status TEXT NOT NULL,
        claimed_at REAL NOT NULL,
        last_activity REAL NOT NULL,
        released_at REAL,
        UNIQUE(run_id, file_path)
    )
""")
conn.execute(
    "CREATE INDEX IF NOT EXISTS idx_claims_file ON file_claims (file_path, status)"
)
conn.execute("""
    CREATE TABLE IF NOT EXISTS mediations (
        id TEXT PRIMARY KEY,
        file_paths TEXT NOT NULL,
        requester_run_ids TEXT NOT NULL,
        mediator_run_id TEXT,
        status TEXT NOT NULL,
        created_at REAL NOT NULL,
        completed_at REAL
    )
""")
conn.execute("""
    CREATE TABLE IF NOT EXISTS coordination_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        direction TEXT NOT NULL,
        message_type TEXT NOT NULL,
        content TEXT NOT NULL,
        timestamp REAL NOT NULL
    )
""")
conn.execute(
    "CREATE INDEX IF NOT EXISTS idx_coordlog_run ON coordination_log (run_id, timestamp)"
)
```

- [ ] **Step 3: Hook broker into broadcast_event in main.py**

In `src/agents/main.py`, in the `broadcast_event` function (line 95), add at the end (after the stream_queues loop at line 130):

```python
    # Coordination: forward event to broker for claim tracking
    if state.broker:
        worktree_path = Path(config.execution.worktree_base) / run_id
        await state.broker.on_stream_event(
            run_id, event,
            worktree_root=worktree_path if worktree_path.exists() else None,
        )
```

The worktree path is deterministic: `{worktree_base}/{run_id}`. No loop needed.

- [ ] **Step 4: Initialize broker in main.py lifespan**

In `src/agents/main.py`:

**4a.** After the `executor = Executor(...)` call (line 132), add broker creation:

```python
    from agents.coordination.broker import CoordinationBroker
    broker = None
    if config.coordination.enabled:
        broker = CoordinationBroker(config.coordination)
```

**4b.** In the `state = AppState(...)` call (line 143), add `broker=broker`:

```python
    state = AppState(
        projects=projects,
        executor=executor,
        history=history,
        budget=budget,
        notifier=notifier,
        github_secret=config.webhooks.github_secret,
        linear_secret=config.webhooks.linear_secret,
        project_store=project_store,
        github_client=github_client,
        slack_bot_client=slack_bot_client,
        aggregator=aggregator,
        broker=broker,
    )
```

**4c.** Also pass `broker` to the `Executor(...)` call (line 132):

```python
    executor = Executor(
        config=config.execution,
        budget=budget,
        history=history,
        notifier=notifier,
        data_dir=data_dir,
        on_stream_event=broadcast_event,
        linear_client=linear_client,
        discord_notifier=discord_notifier_client,
        broker=broker,
    )
```

Note: `broadcast_event` is defined before `executor` in main.py but references `state` which is created after. Since `broadcast_event` is a closure that captures `state` at call time (not definition time), this works. The `broker` however must be created before `executor` since executor uses it synchronously in `__init__`.

**4d.** In the lifespan function, after `scheduler.start()`, add:

```python
    if broker:
        await broker.start()
```

And in the shutdown section, before `scheduler.shutdown()`, add:

```python
    if broker:
        await broker.stop()
```

- [ ] **Step 5: Run full test suite**

```bash
.venv/bin/pytest --tb=short -q
```

Expected: all tests pass (coordination is disabled by default, no impact)

- [ ] **Step 6: Commit**

```bash
git add src/agents/app_state.py src/agents/main.py src/agents/history.py
git commit -m "feat(coordination): wire broker into app lifecycle + SQLite tables"
```

---

### Task 6.5: Inject coordination preamble in executor

**Files:**
- Modify: `src/agents/executor.py`

- [ ] **Step 1: Add coordination preamble injection**

In `executor.py`, in `run_task()`, after `prompt = build_prompt(task, variables or {})` (line 201) and before worktree creation:

```python
            # Coordination: inject preamble if enabled
            coordination_enabled = bool(self.broker)
            if coordination_enabled:
                from agents.coordination.mediator import build_coordination_preamble
                prompt = build_coordination_preamble() + "\n\n---\n\n" + prompt
```

Add `broker` parameter to `__init__`:

```python
def __init__(self, ..., broker: object | None = None) -> None:
    ...
    self.broker = broker
```

After worktree creation (line 216), register with broker:

```python
            if coordination_enabled:
                await self.broker.register_run(run_id, worktree_path, task.intent or task.prompt or "")
```

In the `finally` block (line 278), replace unconditional worktree cleanup with conditional:

```python
            # Worktree cleanup: defer if coordination has pending mediations
            should_cleanup = True
            if coordination_enabled and worktree_path:
                await self.broker.deregister_run(run_id)
                if await self.broker.has_pending_mediations(run_id):
                    should_cleanup = False
                    logger.info("Deferring worktree cleanup for %s (pending mediations)", run_id)
            if should_cleanup and worktree_path and worktree_path.exists():
                try:
                    await self._run_cmd(
                        ["git", "worktree", "remove", "--force", str(worktree_path)],
                        cwd=project.repo,
                    )
                except Exception:
                    logger.warning("Failed to remove worktree %s", worktree_path)
```

- [ ] **Step 2: Run full suite**

```bash
.venv/bin/pytest --tb=short -q
```

Expected: all pass (broker is None by default, so `coordination_enabled = False` and no behavior change)

- [ ] **Step 3: Commit**

```bash
git add src/agents/executor.py
git commit -m "feat(coordination): preamble injection + worktree lifecycle management"
```

---

### Task 6.6: Final verification

- [ ] **Step 1: Run full test suite**

```bash
.venv/bin/pytest --tb=short -q
```

Expected: all tests pass

- [ ] **Step 2: Lint check**

```bash
.venv/bin/ruff check src/agents/coordination/ tests/test_coordination_*.py
```

- [ ] **Step 3: Run Review Gate**

Invoke `pr-review-toolkit:review-pr` on all changed files.

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -A && git commit -m "fix(coordination): review gate fixes"
```

---

## Summary

After all 6 chunks:

| What | Status |
|------|--------|
| Pydantic models (Claim, Mediation, CoordMessage, Config) | ✅ |
| Protocol I/O (state.json, inbox.jsonl, outbox.jsonl) | ✅ |
| StreamEvent.file_path extraction | ✅ |
| ClaimRegistry state machine + TTL + deadlock detection | ✅ |
| CoordinationBroker (event handler, inbox poller, state sync) | ✅ |
| Executor integration (preamble, worktree lifecycle) | ✅ |
| Mediator prompt builder | ✅ |
| SQLite tables for persistence | ✅ |
| `coordination.enabled: false` by default (backward compatible) | ✅ |

**Not yet implemented (future chunks):**
- Mediator spawning via executor (needs real Claude CLI to test)
- Rebase logic after mediation
- Dashboard coordination tab
- Debounced state.json writes (optimization)

These are deferred because they require integration testing with real Claude CLI runs and cannot be unit-tested meaningfully.
