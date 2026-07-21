"""SQLite adapter for scheduler-aware invocation state keyed by account/server/reset/task."""

from __future__ import annotations

import json
from typing import Optional

from tasks.scheduler_task_result import (
    SchedulerAwareTaskResult,
    SchedulerIdentity,
    SchedulerInvocationState,
    SchedulerTaskOutcome,
)

from .store import SafetyStore


_OUTCOME_TO_STATUS = {
    SchedulerTaskOutcome.ACTION_PERFORMED: "deferred",
    SchedulerTaskOutcome.DEFERRED: "deferred",
    SchedulerTaskOutcome.COMPLETE_FOR_RESET: "complete_for_reset",
    SchedulerTaskOutcome.ALREADY_COMPLETE: "already_complete",
    SchedulerTaskOutcome.BLOCKED: "blocked",
    SchedulerTaskOutcome.MANUAL_REQUIRED: "manual_required",
}


class SQLiteSchedulerInvocationRepository:
    """Persist SchedulerAwareTaskResult snapshots in the existing SafetyStore database."""

    def __init__(self, store: SafetyStore) -> None:
        self.store = store

    @staticmethod
    def _from_row(row: dict) -> SchedulerInvocationState:
        return SchedulerInvocationState(
            identity=SchedulerIdentity(
                account_id=row["account_id"],
                server_id=row["server_id"],
                reset_id=row["reset_id"],
                task_id=row["task_id"],
            ),
            status=row["status"],
            revision=int(row["revision"]),
            next_eligible_at=row["next_eligible_at"],
            last_reason_code=row["last_reason_code"],
            observed_progress_json=row["observed_progress_json"],
            action_count_total=int(row["action_count_total"]),
            unresolved_action=bool(row["unresolved_action"]),
            evidence_refs_json=row["evidence_refs_json"],
        )

    def get(self, identity: SchedulerIdentity) -> Optional[SchedulerInvocationState]:
        row = self.store.get_scheduler_invocation_state(
            identity.account_id,
            identity.server_id,
            identity.reset_id,
            identity.task_id,
        )
        return self._from_row(row) if row is not None else None

    def list(self) -> tuple[SchedulerInvocationState, ...]:
        return tuple(self._from_row(row) for row in self.store.list_scheduler_invocation_states())

    def save(self, state: SchedulerInvocationState, updated_at: float) -> SchedulerInvocationState:
        self.store.upsert_scheduler_invocation_state(
            {
                "account_id": state.identity.account_id,
                "server_id": state.identity.server_id,
                "reset_id": state.identity.reset_id,
                "task_id": state.identity.task_id,
                "status": state.status,
                "next_eligible_at": state.next_eligible_at,
                "revision": state.revision,
                "last_reason_code": state.last_reason_code,
                "observed_progress_json": state.observed_progress_json,
                "action_count_total": state.action_count_total,
                "unresolved_action": state.unresolved_action,
                "evidence_refs_json": state.evidence_refs_json,
            },
            updated_at,
        )
        return state

    def apply_result(
        self,
        result: SchedulerAwareTaskResult,
        updated_at: float,
        *,
        prior: Optional[SchedulerInvocationState] = None,
    ) -> SchedulerInvocationState:
        current = prior if prior is not None else self.get(result.identity)
        revision = 0 if current is None else current.revision + 1
        prior_actions = 0 if current is None else current.action_count_total
        status = _OUTCOME_TO_STATUS[result.outcome]
        if result.unresolved_action:
            status = "unresolved"
        state = SchedulerInvocationState(
            identity=result.identity,
            status=status,
            revision=revision,
            next_eligible_at=result.next_eligible_at,
            last_reason_code=result.reason_code,
            observed_progress_json=json.dumps(dict(result.observed_progress), sort_keys=True),
            action_count_total=prior_actions + result.action_count,
            unresolved_action=result.unresolved_action,
            evidence_refs_json=json.dumps(list(result.evidence_refs), sort_keys=True),
        )
        return self.save(state, updated_at)

    def is_eligible(self, identity: SchedulerIdentity, now: float) -> bool:
        state = self.get(identity)
        if state is None:
            return True
        if state.status in {"complete_for_reset", "already_complete", "blocked", "manual_required", "unresolved"}:
            return False
        if state.next_eligible_at is None:
            return state.status == "pending"
        return state.next_eligible_at <= now
