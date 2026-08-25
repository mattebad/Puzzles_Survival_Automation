"""SQLite scheduler invocation, occurrence-claim, and projection authority."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
import math
import time
import uuid
from typing import Any, Mapping, Optional

from tasks.scheduler_task_result import (
    SchedulerAwareTaskResult,
    SchedulerIdentity,
    SchedulerInvocationState,
    SchedulerOccurrence,
    SchedulerOccurrenceClaim,
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
    SchedulerTaskOutcome.RECONCILIATION_REQUIRED: "reconciliation_required",
    SchedulerTaskOutcome.UNRESOLVED: "reconciliation_required",
    SchedulerTaskOutcome.UNKNOWN: "reconciliation_required",
}
_TERMINAL_STATUSES = frozenset(
    {"complete_for_reset", "already_complete", "blocked", "manual_required", "unresolved", "reconciliation_required"}
)


class SchedulerConcurrencyError(RuntimeError):
    """Raised when a stale claim or revision attempts to mutate scheduler state."""


class ProjectionInvalidatedError(RuntimeError):
    """A stale caller projection cannot replace an invalidated persisted projection."""
class SQLiteSchedulerInvocationRepository:
    """The sole persisted scheduler authority, backed by an existing SafetyStore."""

    def __init__(self, store: SafetyStore) -> None:
        self.store = store

    @staticmethod
    def _from_row(row: Mapping[str, Any]) -> SchedulerInvocationState:
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

    @staticmethod
    def _occurrence_from_row(row: Mapping[str, Any]) -> SchedulerOccurrence:
        return SchedulerOccurrence(
            identity=SchedulerIdentity(
                row["account_id"], row["server_id"], row["reset_id"], row["task_id"]
            ),
            occurrence_key=row["occurrence_key"],
            recurrence_class=row["recurrence_class"],
            repeat_ordinal=int(row["repeat_ordinal"]),
            status=row["status"],
            revision=int(row["state_revision"]),
            next_eligible_at=row["next_eligible_at"],
            projection_json=row["projection_json"],
            claim_id=row["claim_id"],
            claim_token=row["claim_token"],
            last_reason_code=row["last_reason_code"],
            pulse_token=row["pulse_token"],
            action_count_total=int(row["action_count_total"]),
            unresolved_action=bool(row["unresolved_action"]),
            evidence_refs_json=row["evidence_refs_json"],
        )

    def get(self, identity: SchedulerIdentity) -> Optional[SchedulerInvocationState]:
        row = self.store.get_scheduler_invocation_state(
            identity.account_id, identity.server_id, identity.reset_id, identity.task_id
        )
        return self._from_row(row) if row is not None else None

    def list(self) -> tuple[SchedulerInvocationState, ...]:
        return tuple(self._from_row(row) for row in self.store.list_scheduler_invocation_states())

    def get_occurrence(self, occurrence_key: str) -> SchedulerOccurrence | None:
        row = self.store.connection.execute(
            "SELECT * FROM scheduler_occurrences WHERE occurrence_key=?", (occurrence_key,)
        ).fetchone()
        return self._occurrence_from_row(row) if row is not None else None

    def list_occurrences(self) -> tuple[SchedulerOccurrence, ...]:
        rows = self.store.connection.execute(
            "SELECT * FROM scheduler_occurrences ORDER BY account_id,server_id,reset_id,task_id,repeat_ordinal"
        ).fetchall()
        return tuple(self._occurrence_from_row(row) for row in rows)

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

    @staticmethod
    def _status_for_result(result: SchedulerAwareTaskResult) -> str:
        if result.unresolved_action or result.outcome in {
            SchedulerTaskOutcome.RECONCILIATION_REQUIRED,
            SchedulerTaskOutcome.UNRESOLVED,
            SchedulerTaskOutcome.UNKNOWN,
        }:
            return "reconciliation_required"
        if not result.verified and result.outcome in {
            SchedulerTaskOutcome.ACTION_PERFORMED,
            SchedulerTaskOutcome.COMPLETE_FOR_RESET,
            SchedulerTaskOutcome.ALREADY_COMPLETE,
        }:
            return "reconciliation_required"
        return _OUTCOME_TO_STATUS[result.outcome]

    @staticmethod
    def _next_deadline(
        result: SchedulerAwareTaskResult, current: SchedulerInvocationState | None
    ) -> float | None:
        # ACTION_PERFORMED must not erase a previously projected cooldown/timer.
        if result.next_eligible_at is not None:
            return result.next_eligible_at
        if result.outcome is SchedulerTaskOutcome.ACTION_PERFORMED and current is not None:
            return current.next_eligible_at
        return None

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
        status = self._status_for_result(result)
        state = SchedulerInvocationState(
            identity=result.identity,
            status=status,
            revision=revision,
            next_eligible_at=self._next_deadline(result, current),
            last_reason_code=result.reason_code,
            observed_progress_json=json.dumps(dict(result.observed_progress), sort_keys=True),
            action_count_total=prior_actions + result.action_count,
            unresolved_action=(result.unresolved_action or status == "reconciliation_required"),
            evidence_refs_json=json.dumps(list(result.evidence_refs), sort_keys=True),
        )
        self.save(state, updated_at)
        return state

    def _occurrence_key(
        self, identity: SchedulerIdentity, recurrence_class: str, repeat_ordinal: int
    ) -> str:
        return f"{identity.composite_key}|{recurrence_class}|{repeat_ordinal}"

    def claim_occurrence(
        self,
        identity: SchedulerIdentity,
        now_utc_epoch: float,
        *,
        recurrence_class: str = "daily_once_per_reset",
        repeat_ordinal: int = 0,
        occurrence_key: str | None = None,
        next_eligible_at: float | None = None,
        projection: Mapping[str, Any] | None = None,
        eligible: bool = True,
        pulse_token: str | None = None,
    ) -> SchedulerOccurrenceClaim | None:
        if not math.isfinite(float(now_utc_epoch)) or now_utc_epoch < 0:
            raise ValueError("occurrence claim time must be a UTC epoch")
        if repeat_ordinal < 0 or not recurrence_class.strip():
            raise ValueError("occurrence claim recurrence is invalid")
        pulse_token = pulse_token or f"{now_utc_epoch:.9f}"
        occurrence_key = occurrence_key or self._occurrence_key(identity, recurrence_class, repeat_ordinal)
        projection_value = (
            projection.to_mapping()
            if hasattr(projection, "to_mapping")
            else asdict(projection)
            if projection is not None and is_dataclass(projection)
            else dict(projection or {})
        )
        projection_json = json.dumps(projection_value, sort_keys=True, separators=(",", ":"))
        with self.store.transaction() as db:
            invocation = db.execute(
                """SELECT * FROM scheduler_invocation_state
                WHERE account_id=? AND server_id=? AND reset_id=? AND task_id=?""",
                (identity.account_id, identity.server_id, identity.reset_id, identity.task_id),
            ).fetchone()
            if invocation is not None:
                status = str(invocation["status"])
                deadline = invocation["next_eligible_at"]
                if status in _TERMINAL_STATUSES or bool(invocation["unresolved_action"]):
                    return None
                if deadline is not None and float(deadline) > now_utc_epoch:
                    return None
            if not eligible:
                return None
            row = db.execute(
                "SELECT * FROM scheduler_occurrences WHERE occurrence_key=?", (occurrence_key,)
            ).fetchone()
            if row is None:
                occurrence_id = uuid.uuid4().hex
                db.execute(
                    """INSERT INTO scheduler_occurrences(
                    occurrence_id,occurrence_key,account_id,server_id,reset_id,task_id,
                    recurrence_class,repeat_ordinal,status,state_revision,next_eligible_at,
                    projection_json,claim_id,claim_token,pulse_token,last_reason_code,action_count_total,
                    unresolved_action,evidence_refs_json,created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        occurrence_id,
                        occurrence_key,
                        identity.account_id,
                        identity.server_id,
                        identity.reset_id,
                        identity.task_id,
                        recurrence_class,
                        repeat_ordinal,
                        "ELIGIBLE",
                        0,
                        next_eligible_at,
                        projection_json,
                        None,
                        None,
                        pulse_token,
                        "",
                        0,
                        0,
                        "[]",
                        now_utc_epoch,
                        now_utc_epoch,
                    ),
                )
                row = db.execute(
                    "SELECT * FROM scheduler_occurrences WHERE occurrence_id=?", (occurrence_id,)
                ).fetchone()
            else:
                status = str(row["status"])
                deadline = row["next_eligible_at"]
                if status in {"COMPLETED", "BLOCKED", "MANUAL_REQUIRED", "RECONCILIATION_REQUIRED", "CLAIMED"}:
                    return None
                if row["pulse_token"] == pulse_token:
                    return None
                if status == "DEFERRED" and deadline is not None and float(deadline) > now_utc_epoch:
                    return None
            deadline = row["next_eligible_at"]
            if deadline is not None and float(deadline) > now_utc_epoch:
                return None
            claim_id = uuid.uuid4().hex
            claim_token = uuid.uuid4().hex
            updated = db.execute(
                """UPDATE scheduler_occurrences SET status='CLAIMED',state_revision=state_revision+1,
                claim_id=?,claim_token=?,pulse_token=?,updated_at=? WHERE occurrence_id=?
                AND status IN ('ELIGIBLE','DEFERRED')""",
                (claim_id, claim_token, pulse_token, now_utc_epoch, row["occurrence_id"]),
            )
            if updated.rowcount != 1:
                return None
            db.execute(
                """INSERT INTO scheduler_occurrence_claims(
                claim_id,occurrence_id,claim_token,claimed_at,state,completed_at
                ) VALUES (?,?,?,?,?,NULL)""",
                (claim_id, row["occurrence_id"], claim_token, now_utc_epoch, "ACTIVE"),
            )
            claimed = db.execute(
                "SELECT * FROM scheduler_occurrences WHERE occurrence_id=?", (row["occurrence_id"],)
            ).fetchone()
            return SchedulerOccurrenceClaim(
                self._occurrence_from_row(claimed), claim_id, claim_token, now_utc_epoch
            )

    def next_repeat_ordinal(self, identity: SchedulerIdentity, repeat_limit: int) -> int | None:
        """Advance a bounded repeat only from persisted occurrences."""
        if type(repeat_limit) is not int or repeat_limit < 1:
            raise ValueError("repeat limit must be positive")
        row = self.store.connection.execute(
            """SELECT MAX(repeat_ordinal) AS maximum FROM scheduler_occurrences
            WHERE account_id=? AND server_id=? AND reset_id=? AND task_id=?
            AND status IN ('DEFERRED','COMPLETED','BLOCKED','MANUAL_REQUIRED','RECONCILIATION_REQUIRED')""",
            (identity.account_id, identity.server_id, identity.reset_id, identity.task_id),
        ).fetchone()
        ordinal = 0 if row is None or row["maximum"] is None else int(row["maximum"]) + 1
        return ordinal if ordinal < repeat_limit else None

    def list_orphan_claims(self) -> tuple[SchedulerOccurrenceClaim, ...]:
        rows = self.store.connection.execute(
            """SELECT c.*,o.* FROM scheduler_occurrence_claims c
            JOIN scheduler_occurrences o ON o.occurrence_id=c.occurrence_id
            LEFT JOIN scheduler_invocation_state i ON i.account_id=o.account_id
              AND i.server_id=o.server_id AND i.reset_id=o.reset_id AND i.task_id=o.task_id
            WHERE c.state='ACTIVE' AND (i.account_id IS NULL OR i.status NOT IN ('deferred','complete_for_reset','already_complete','blocked','manual_required','unresolved','reconciliation_required'))"""
        ).fetchall()
        return tuple(
            SchedulerOccurrenceClaim(
                self._occurrence_from_row(row), row["claim_id"], row["claim_token"], row["claimed_at"]
            )
            for row in rows
        )

    def reconcile_orphan_claim(
        self,
        claim_id: str,
        result: SchedulerAwareTaskResult,
        updated_at: float,
    ) -> SchedulerInvocationState:
        row = self.store.connection.execute(
            """SELECT c.*,o.* FROM scheduler_occurrence_claims c
            JOIN scheduler_occurrences o ON o.occurrence_id=c.occurrence_id
            WHERE c.claim_id=? AND c.state='ACTIVE'""",
            (claim_id,),
        ).fetchone()
        if row is None:
            raise SchedulerConcurrencyError("active orphan claim not found")
        claim = SchedulerOccurrenceClaim(
            self._occurrence_from_row(row), row["claim_id"], row["claim_token"], row["claimed_at"]
        )
        if not (
            result.verified
            and result.outcome
            in {SchedulerTaskOutcome.COMPLETE_FOR_RESET, SchedulerTaskOutcome.ALREADY_COMPLETE}
        ):
            result = SchedulerAwareTaskResult.reconciliation_required(
                result.identity,
                "ORPHAN_RECONCILIATION_REQUIRED:" + result.reason_code,
                verified=False,
                observed_progress=result.observed_progress,
                action_count=result.action_count,
                consequence=result.consequence,
                evidence_refs=result.evidence_refs,
                unresolved_action=True,
            )
        return self.finalize_claim(claim, result, updated_at)

    reconcile_orphaned_claim = reconcile_orphan_claim

    # Explicit aliases make the authority boundary discoverable without adding a second store.
    claim = claim_occurrence
    atomic_claim = claim_occurrence

    def abandon_claim(self, claim: SchedulerOccurrenceClaim, updated_at: float) -> None:
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT state FROM scheduler_occurrence_claims WHERE claim_id=? AND claim_token=?",
                (claim.claim_id, claim.claim_token),
            ).fetchone()
            if row is None or row["state"] != "ACTIVE":
                raise SchedulerConcurrencyError("claim is not active")
            db.execute(
                "UPDATE scheduler_occurrence_claims SET state='ABANDONED',completed_at=? WHERE claim_id=?",
                (updated_at, claim.claim_id),
            )
            db.execute(
                """UPDATE scheduler_occurrences SET status='ELIGIBLE',state_revision=state_revision+1,
                claim_id=NULL,claim_token=NULL,updated_at=? WHERE occurrence_key=?""",
                (updated_at, claim.occurrence.occurrence_key),
            )

    def finalize_claim(
        self,
        claim: SchedulerOccurrenceClaim,
        result: SchedulerAwareTaskResult,
        updated_at: float,
    ) -> SchedulerInvocationState:
        if result.identity != claim.identity:
            raise SchedulerConcurrencyError("result identity does not match occurrence claim")
        with self.store.transaction() as db:
            row = db.execute(
                """SELECT c.state,o.* FROM scheduler_occurrence_claims c
                JOIN scheduler_occurrences o ON o.occurrence_id=c.occurrence_id
                WHERE c.claim_id=? AND c.claim_token=?""",
                (claim.claim_id, claim.claim_token),
            ).fetchone()
            if row is None or row["state"] != "ACTIVE" or row["status"] != "CLAIMED":
                raise SchedulerConcurrencyError("claim is not active")
            current_row = db.execute(
                """SELECT * FROM scheduler_invocation_state WHERE account_id=? AND server_id=?
                AND reset_id=? AND task_id=?""",
                (result.identity.account_id, result.identity.server_id, result.identity.reset_id, result.identity.task_id),
            ).fetchone()
            current = self._from_row(current_row) if current_row is not None else None
            status = self._status_for_result(result)
            occurrence_status = {
                "deferred": "DEFERRED",
                "complete_for_reset": "COMPLETED",
                "already_complete": "COMPLETED",
                "blocked": "BLOCKED",
                "manual_required": "MANUAL_REQUIRED",
                "reconciliation_required": "RECONCILIATION_REQUIRED",
            }[status]
            deadline = self._next_deadline(result, current)
            actions = (0 if current is None else current.action_count_total) + result.action_count
            revision = 0 if current is None else current.revision + 1
            unresolved = result.unresolved_action or status == "reconciliation_required"
            evidence = json.dumps(list(result.evidence_refs), sort_keys=True)
            db.execute(
                """UPDATE scheduler_occurrences SET status=?,state_revision=state_revision+1,
                next_eligible_at=?,claim_id=NULL,claim_token=NULL,last_reason_code=?,
                action_count_total=?,unresolved_action=?,evidence_refs_json=?,updated_at=?
                WHERE occurrence_id=? AND status='CLAIMED'""",
                (occurrence_status, deadline, result.reason_code, actions, int(unresolved), evidence, updated_at, row["occurrence_id"]),
            )
            claim_state = (
                "RECONCILIATION_REQUIRED"
                if unresolved
                else "COMPLETED"
                if occurrence_status in {"BLOCKED", "MANUAL_REQUIRED"}
                else occurrence_status
            )
            db.execute(
                "UPDATE scheduler_occurrence_claims SET state=?,completed_at=? WHERE claim_id=? AND state='ACTIVE'",
                (claim_state, updated_at, claim.claim_id),
            )
            state = SchedulerInvocationState(
                identity=result.identity,
                status=status,
                revision=revision,
                next_eligible_at=deadline,
                last_reason_code=result.reason_code,
                observed_progress_json=json.dumps(dict(result.observed_progress), sort_keys=True),
                action_count_total=actions,
                unresolved_action=unresolved,
                evidence_refs_json=evidence,
            )
            db.execute(
                """INSERT INTO scheduler_invocation_state(
                account_id,server_id,reset_id,task_id,status,next_eligible_at,revision,
                last_reason_code,observed_progress_json,action_count_total,unresolved_action,
                evidence_refs_json,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(account_id,server_id,reset_id,task_id) DO UPDATE SET
                status=excluded.status,next_eligible_at=excluded.next_eligible_at,revision=excluded.revision,
                last_reason_code=excluded.last_reason_code,observed_progress_json=excluded.observed_progress_json,
                action_count_total=excluded.action_count_total,unresolved_action=excluded.unresolved_action,
                evidence_refs_json=excluded.evidence_refs_json,updated_at=excluded.updated_at""",
                (result.identity.account_id, result.identity.server_id, result.identity.reset_id, result.identity.task_id,
                 status, deadline, revision, result.reason_code, state.observed_progress_json, actions,
                 int(unresolved), evidence, updated_at),
            )
            return state

    complete_claim = finalize_claim

    def reconcile_unresolved(
        self,
        identity: SchedulerIdentity,
        result: SchedulerAwareTaskResult,
        updated_at: float,
    ) -> SchedulerInvocationState:
        current = self.get(identity)
        if current is None or current.status not in {"unresolved", "reconciliation_required"}:
            raise SchedulerConcurrencyError("scheduler occurrence is not reconciliation-required")
        positive = (
            result.verified
            and result.identity == identity
            and result.outcome in {
                SchedulerTaskOutcome.COMPLETE_FOR_RESET,
                SchedulerTaskOutcome.ALREADY_COMPLETE,
            }
        )
        if not positive:
            result = SchedulerAwareTaskResult.reconciliation_required(
                identity, "RECONCILIATION_NOT_POSITIVE", verified=False
            )
            status = "reconciliation_required"
            occurrence_status = "BLOCKED"
        else:
            status = _OUTCOME_TO_STATUS[result.outcome]
            occurrence_status = "COMPLETED"
        deadline = self._next_deadline(result, current)
        actions = current.action_count_total + result.action_count
        state = SchedulerInvocationState(
            identity=identity,
            status=status,
            revision=current.revision + 1,
            next_eligible_at=deadline,
            last_reason_code=result.reason_code,
            observed_progress_json=json.dumps(dict(result.observed_progress), sort_keys=True),
            action_count_total=actions,
            unresolved_action=not positive,
            evidence_refs_json=json.dumps(list(result.evidence_refs), sort_keys=True),
        )
        with self.store.transaction() as db:
            db.execute(
                """INSERT INTO scheduler_invocation_state(
                account_id,server_id,reset_id,task_id,status,next_eligible_at,revision,
                last_reason_code,observed_progress_json,action_count_total,unresolved_action,
                evidence_refs_json,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(account_id,server_id,reset_id,task_id) DO UPDATE SET
                status=excluded.status,next_eligible_at=excluded.next_eligible_at,revision=excluded.revision,
                last_reason_code=excluded.last_reason_code,observed_progress_json=excluded.observed_progress_json,
                action_count_total=excluded.action_count_total,unresolved_action=excluded.unresolved_action,
                evidence_refs_json=excluded.evidence_refs_json,updated_at=excluded.updated_at""",
                (identity.account_id, identity.server_id, identity.reset_id, identity.task_id,
                 status, deadline, state.revision, state.last_reason_code,
                 state.observed_progress_json, actions, int(state.unresolved_action),
                 state.evidence_refs_json, updated_at),
            )
            db.execute(
                """UPDATE scheduler_occurrences SET status=?,state_revision=state_revision+1,
                claim_id=NULL,claim_token=NULL,last_reason_code=?,unresolved_action=?,
                action_count_total=?,evidence_refs_json=?,updated_at=?
                WHERE account_id=? AND server_id=? AND reset_id=? AND task_id=?
                AND status='RECONCILIATION_REQUIRED'""",
                (occurrence_status, state.last_reason_code, int(state.unresolved_action),
                 actions, state.evidence_refs_json, updated_at,
                 identity.account_id, identity.server_id, identity.reset_id, identity.task_id),
            )
            db.execute(
                """UPDATE scheduler_occurrence_claims SET state=?,completed_at=?
                WHERE occurrence_id IN (
                    SELECT occurrence_id FROM scheduler_occurrences
                    WHERE account_id=? AND server_id=? AND reset_id=? AND task_id=?
                ) AND state='RECONCILIATION_REQUIRED'""",
                (occurrence_status, updated_at, identity.account_id, identity.server_id,
                 identity.reset_id, identity.task_id),
            )
        return state

    reconcile_occurrence = reconcile_unresolved

    claim_one = claim_occurrence
    claim_atomic_occurrence = claim_occurrence
    get_occurrence_state = get_occurrence
    list_occurrence_states = list_occurrences
    reconcile = reconcile_unresolved

    def is_eligible(self, identity: SchedulerIdentity, now: float) -> bool:
        state = self.get(identity)
        if state is not None:
            if state.status in _TERMINAL_STATUSES or state.unresolved_action:
                return False
            if state.next_eligible_at is not None and state.next_eligible_at > now:
                return False
        prefix = identity.composite_key + "|"
        row = self.store.connection.execute(
                """SELECT status,next_eligible_at FROM scheduler_occurrences
                WHERE occurrence_key LIKE ? ORDER BY repeat_ordinal DESC LIMIT 1""",
            (prefix + "%",),
        ).fetchone()
        if row is None:
            return True
        if row["status"] in {"COMPLETED", "BLOCKED", "MANUAL_REQUIRED", "RECONCILIATION_REQUIRED", "CLAIMED"}:
            return False
        return row["next_eligible_at"] is None or float(row["next_eligible_at"]) <= now

    def observe_clock(self, identity: SchedulerIdentity, now_utc_epoch: float) -> bool:
        """Record monotonic UTC observation; rollback invalidates projections and defers."""
        if not math.isfinite(float(now_utc_epoch)) or now_utc_epoch < 0:
            raise ValueError("clock observation must be a UTC epoch")
        with self.store.transaction() as db:
            row = db.execute(
                """SELECT * FROM scheduler_clock_state WHERE account_id=? AND server_id=? AND reset_id=?""",
                (identity.account_id, identity.server_id, identity.reset_id),
            ).fetchone()
            watermark = db.execute(
                "SELECT MAX(last_utc_epoch) AS maximum FROM scheduler_clock_state WHERE account_id=? AND server_id=?",
                (identity.account_id, identity.server_id),
            ).fetchone()["maximum"]
            rollback = watermark is not None and float(watermark) > now_utc_epoch
            persisted_utc = float(watermark) if rollback else now_utc_epoch
            revision = 0 if row is None else int(row["revision"]) + 1
            db.execute(
                """INSERT INTO scheduler_clock_state(account_id,server_id,reset_id,last_utc_epoch,valid,revision,updated_at)
                VALUES (?,?,?,?,?,?,?) ON CONFLICT(account_id,server_id,reset_id) DO UPDATE SET
                last_utc_epoch=excluded.last_utc_epoch,valid=excluded.valid,revision=excluded.revision,
                updated_at=excluded.updated_at""",
                (identity.account_id, identity.server_id, identity.reset_id, persisted_utc, int(not rollback), revision, now_utc_epoch),
            )
            if rollback:
                db.execute(
                    """UPDATE scheduler_projection_state SET valid=0,revision=revision+1,updated_at=?
                    WHERE account_id=? AND server_id=? AND reset_id=?""",
                    (now_utc_epoch, identity.account_id, identity.server_id, identity.reset_id),
                )
            return not rollback

    def save_projection(
        self, identity: SchedulerIdentity, projection_key: str, projection: Mapping[str, Any], observed_at_utc: float
    ) -> None:
        if (
            not projection_key.strip()
            or observed_at_utc is None
            or isinstance(observed_at_utc, bool)
            or not math.isfinite(float(observed_at_utc))
            or observed_at_utc < 0
        ):
            raise ValueError("projection key and explicit observation time are required")
        with self.store.transaction() as db:
            current = db.execute(
                "SELECT revision,valid,updated_at FROM scheduler_projection_state WHERE projection_key=?",
                (projection_key,),
            ).fetchone()
            if current is not None and not current["valid"] and observed_at_utc <= float(current["updated_at"]):
                raise ProjectionInvalidatedError("projection observation is stale after invalidation")
            revision = 0 if current is None else int(current["revision"]) + 1
            projection_value = (
                projection.to_mapping()
                if hasattr(projection, "to_mapping")
                else asdict(projection)
                if is_dataclass(projection)
                else dict(projection)
            )
            embedded_observed_at = projection_value.get("observed_at_utc")
            if (
                embedded_observed_at is None
                or isinstance(embedded_observed_at, bool)
                or not math.isfinite(float(embedded_observed_at))
                or float(embedded_observed_at) != float(observed_at_utc)
            ):
                raise ValueError("projection must carry its explicit observation timestamp")
            db.execute(
                """INSERT INTO scheduler_projection_state(
                projection_key,account_id,server_id,reset_id,projection_json,observed_at_utc,valid,revision,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(projection_key) DO UPDATE SET
                projection_json=excluded.projection_json,observed_at_utc=excluded.observed_at_utc,
                valid=1,revision=excluded.revision,updated_at=excluded.updated_at""",
                (projection_key, identity.account_id, identity.server_id, identity.reset_id,
                 json.dumps(projection_value, sort_keys=True), observed_at_utc, 1, revision, observed_at_utc),
            )

    def get_projection(self, projection_key: str) -> Mapping[str, Any] | None:
        row = self.store.connection.execute(
            "SELECT projection_json,valid FROM scheduler_projection_state WHERE projection_key=?",
            (projection_key,),
        ).fetchone()
        if row is None or not row["valid"]:
            return None
        return json.loads(row["projection_json"])

    def invalidate_projections(self, identity: SchedulerIdentity, updated_at: float) -> None:
        with self.store.transaction() as db:
            db.execute(
                """UPDATE scheduler_projection_state SET valid=0,revision=revision+1,updated_at=?
                WHERE account_id=? AND server_id=? AND reset_id=?""",
                (updated_at, identity.account_id, identity.server_id, identity.reset_id),
            )

    def record_reset_disagreement(
        self,
        account_id: str,
        server_id: str,
        declared_reset_id: str,
        observed_reset_id: str | None,
        observed_at_utc: float,
    ) -> None:
        reset_ids = {declared_reset_id}
        if observed_reset_id:
            reset_ids.add(observed_reset_id)
        with self.store.transaction() as db:
            for reset_id in reset_ids:
                db.execute(
                    """UPDATE scheduler_projection_state SET valid=0,revision=revision+1,updated_at=?
                    WHERE account_id=? AND server_id=? AND reset_id=?""",
                    (observed_at_utc, account_id, server_id, reset_id),
                )
                db.execute(
                    """INSERT INTO scheduler_clock_state(
                    account_id,server_id,reset_id,last_utc_epoch,valid,revision,updated_at)
                    VALUES (?,?,?,?,0,0,?) ON CONFLICT(account_id,server_id,reset_id) DO UPDATE SET
                    last_utc_epoch=excluded.last_utc_epoch,valid=0,revision=revision+1,
                    updated_at=excluded.updated_at""",
                    (account_id, server_id, reset_id, observed_at_utc, observed_at_utc),
                )

    def projection_is_valid(
        self, projection_key: str, now_utc_epoch: float, max_age_seconds: float
    ) -> bool:
        row = self.store.connection.execute(
            "SELECT valid,observed_at_utc FROM scheduler_projection_state WHERE projection_key=?",
            (projection_key,),
        ).fetchone()
        if row is None or not row["valid"]:
            return False
        observed = float(row["observed_at_utc"])
        return observed <= now_utc_epoch and now_utc_epoch - observed <= max_age_seconds
