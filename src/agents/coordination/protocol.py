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
    out = {**state, "updated_at": _iso_now()}
    tmp_path = pw / ".state.json.tmp"
    tmp_path.write_text(json.dumps(out, indent=2))
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
    out = {**message, "ts": message.get("ts") or _iso_now()}
    with outbox.open("a") as f:
        f.write(json.dumps(out) + "\n")


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
