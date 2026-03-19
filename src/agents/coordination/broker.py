"""CoordinationBroker — central orchestrator for inter-agent coordination."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time as _time
from pathlib import Path

from agents.coordination.claims import ClaimRegistry
from agents.coordination.models import Claim, CoordinationConfig
from agents.coordination.protocol import (
    init_coordination_dir,
    read_inbox,
    write_state,
)
from agents.streaming import StreamEvent

logger = logging.getLogger(__name__)

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
        self._pending_mediations: dict[str, list[str]] = {}
        self._lock = asyncio.Lock()
        self._timeline: list[dict] = []  # recent coordination events (capped at 100)

    def _record_timeline(self, run_id: str, event_type: str, detail: str) -> None:
        entry = {
            "run_id": run_id,
            "type": event_type,
            "detail": detail,
            "timestamp": _time.time(),
        }
        self._timeline.insert(0, entry)
        if len(self._timeline) > 100:
            self._timeline.pop()

    def get_coordination_snapshot(self) -> dict:
        """Return current coordination state for dashboard display."""
        claims = []
        contested = 0
        mediating = 0
        for fp, claim in self.claims._claims.items():
            claims.append({
                "file": fp,
                "owner": claim.run_id,
                "status": claim.status.value,
                "type": claim.claim_type.value,
                "since": claim.claimed_at,
            })
            if claim.status.value == "contested":
                contested += 1
            elif claim.status.value == "mediating":
                mediating += 1

        mediations: list[dict] = []

        return {
            "claims": claims,
            "mediations": mediations,
            "active_runs": len(self.active_worktrees),
            "contested_count": contested,
            "mediating_count": mediating,
            "timeline": self._timeline[:50],
        }

    async def start(self) -> None:
        if self.config.enabled:
            self._poll_task = asyncio.create_task(self._poll_loop())
            logger.info("CoordinationBroker started (mode=%s)", self.config.mode)

    async def stop(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
        logger.info("CoordinationBroker stopped")

    async def register_run(self, run_id: str, worktree: Path, intent: str) -> None:
        init_coordination_dir(worktree)
        self.active_worktrees[run_id] = worktree
        self._inbox_positions[run_id] = 0
        self.claims.set_intent(run_id, intent)
        self._record_timeline(run_id, "registered", intent)
        await self._update_all_state_files()

    async def deregister_run(self, run_id: str) -> None:
        self.claims.release_all(run_id)
        self._record_timeline(run_id, "deregistered", "")
        self.active_worktrees.pop(run_id, None)
        self._inbox_positions.pop(run_id, None)
        await self._update_all_state_files()

    async def on_stream_event(
        self,
        run_id: str,
        event: StreamEvent,
        worktree_root: Path | None = None,
    ) -> Claim | None:
        async with self._lock:
            self.claims.update_activity(run_id)

            tool_name = event.tool_name
            file_path = event.file_path

            if not tool_name or tool_name not in _FILE_TOOLS or not file_path:
                return None

            rel_path = file_path
            if worktree_root and os.path.isabs(file_path):
                try:
                    rel_path = os.path.relpath(file_path, str(worktree_root))
                except ValueError:
                    rel_path = file_path

            conflict: Claim | None = None
            if tool_name in _WRITE_TOOLS:
                conflict = self.claims.hard_claim(run_id, rel_path)
                self._record_timeline(run_id, "claim", f"hard {rel_path}")
            elif tool_name in _READ_TOOLS:
                self.claims.soft_claim(run_id, rel_path)
                self._record_timeline(run_id, "claim", f"soft {rel_path}")

        await self._update_all_state_files()
        return conflict

    async def has_pending_mediations(self, run_id: str) -> bool:
        return bool(self._pending_mediations.get(run_id))

    async def poll_inboxes_once(self) -> None:
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
            self._record_timeline(run_id, "need_file", file_path)
            claim = self.claims.get_claim_for_file(file_path)
            if claim and claim.run_id != run_id:
                self.claims.mark_contested(file_path)
                self._record_timeline(run_id, "contested", f"{file_path} (owner: {claim.run_id})")
                logger.info(
                    "Conflict detected: %s needs %s (claimed by %s)",
                    run_id, file_path, claim.run_id,
                )
        elif msg_type == "edit_complete":
            logger.info("Run %s completed edit on %s", run_id, file_path)
        elif msg_type == "heartbeat":
            self.claims.update_activity(run_id)
            self._record_timeline(run_id, "heartbeat", "")
        elif msg_type == "escalation":
            self._record_timeline(run_id, "escalation", msg.get("message", ""))
            logger.warning("Run %s escalated: %s", run_id, msg.get("message", ""))

    async def _update_all_state_files(self) -> None:
        loop = asyncio.get_running_loop()
        for run_id, worktree in list(self.active_worktrees.items()):
            state = self.claims.build_state_snapshot(
                this_run_id=run_id,
                this_intent=self.claims.get_intent(run_id),
            )
            await loop.run_in_executor(None, write_state, worktree, state)

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
