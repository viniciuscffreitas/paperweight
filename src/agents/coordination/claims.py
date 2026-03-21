"""ClaimRegistry — in-memory state machine for file claims with TTL."""

from __future__ import annotations

import time
import uuid
from collections import defaultdict

from agents.coordination.models import Claim, ClaimStatus, ClaimType


class ClaimRegistry:
    def __init__(self) -> None:
        self._claims: dict[str, Claim] = {}
        self._run_claims: dict[str, set[str]] = defaultdict(set)
        self._run_intents: dict[str, str] = {}
        self._needs: dict[str, set[str]] = defaultdict(set)

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
            return existing
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
            self._claims[fp] for fp in self._run_claims.get(run_id, set()) if fp in self._claims
        ]

    def add_need(self, run_id: str, file_path: str) -> None:
        self._needs[run_id].add(file_path)

    def set_intent(self, run_id: str, intent: str) -> None:
        self._run_intents[run_id] = intent

    def get_intent(self, run_id: str) -> str:
        return self._run_intents.get(run_id, "")

    def detect_deadlock(self) -> list[list[str]]:
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
