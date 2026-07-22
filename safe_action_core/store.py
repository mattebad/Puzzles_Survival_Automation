"""Versioned SQLite journal, append-only audit log, and controller lease."""

from __future__ import annotations

import json
import math
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional

from .models import ActionIntent, ActionStatus, PolicyResult, snapshot

CURRENT_SCHEMA_VERSION = 3
TASK_STATE_STATUSES = frozenset({"pending", "done", "blocked", "unresolved"})
SCHEDULER_INVOCATION_STATUSES = frozenset(
    {
        "pending",
        "deferred",
        "complete_for_reset",
        "already_complete",
        "blocked",
        "manual_required",
        "unresolved",
    }
)
ALLOWED_TRANSITIONS = {
    ActionStatus.PREPARED.value: {
        ActionStatus.INPUT_SENT.value,
        ActionStatus.UNRESOLVED.value,
        ActionStatus.CANCELLED.value,
    },
    ActionStatus.INPUT_SENT.value: {ActionStatus.CONFIRMED.value, ActionStatus.UNRESOLVED.value},
    ActionStatus.UNRESOLVED.value: {ActionStatus.CONFIRMED.value, ActionStatus.CANCELLED.value},
    ActionStatus.CONFIRMED.value: set(),
    ActionStatus.CANCELLED.value: set(),
}


class StoreError(RuntimeError):
    pass


class DuplicateActionError(StoreError):
    pass


class InvalidTransitionError(StoreError):
    pass


class LeaseError(StoreError):
    pass


class SchemaVersionError(StoreError):
    pass


def _json(value: Any) -> str:
    return json.dumps(snapshot(value), sort_keys=True, separators=(",", ":"))


def is_no_effect_cancelled(row: Mapping[str, Any]) -> bool:
    return (
        row["final_status"] == ActionStatus.CANCELLED.value
        and row.get("input_attempt_at") is None
        and row.get("transport_result_json") is None
    )


class SafetyStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.connection = sqlite3.connect(str(self.path), isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        try:
            self._migrate()
        except BaseException:
            self.connection.close()
            raise

    def close(self) -> None:
        self.connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        else:
            self.connection.execute("COMMIT")

    @property
    def schema_version(self) -> int:
        row = self.connection.execute("SELECT version FROM schema_version WHERE singleton = 1").fetchone()
        return int(row["version"])

    def _migrate(self) -> None:
        table = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchone()
        version = 0
        if table:
            row = self.connection.execute("SELECT version FROM schema_version WHERE singleton = 1").fetchone()
            version = int(row["version"]) if row else 0
        if version > CURRENT_SCHEMA_VERSION:
            raise SchemaVersionError("database schema is newer than this core")
        if version == 0:
            self.connection.executescript(
                    """BEGIN IMMEDIATE;
                    CREATE TABLE IF NOT EXISTS schema_version (
                        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                        version INTEGER NOT NULL
                    );
                    INSERT OR REPLACE INTO schema_version(singleton, version) VALUES (1, 3);
                    CREATE TABLE controller_lease (
                        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                        owner_id TEXT NOT NULL,
                        acquired_at REAL NOT NULL,
                        heartbeat_at REAL NOT NULL,
                        expires_at REAL NOT NULL,
                        released_at REAL
                    );
                    CREATE TABLE task_state (
                        task_id TEXT PRIMARY KEY,
                        completion_key TEXT NOT NULL,
                        game_day_id TEXT NOT NULL,
                        status TEXT NOT NULL CHECK(status IN ('pending','done','blocked','unresolved')),
                        next_due_monotonic REAL,
                        revision INTEGER NOT NULL CHECK(revision >= 0),
                        last_reason TEXT NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    CREATE TABLE scheduler_invocation_state (
                        account_id TEXT NOT NULL,
                        server_id TEXT NOT NULL,
                        reset_id TEXT NOT NULL,
                        task_id TEXT NOT NULL,
                        status TEXT NOT NULL CHECK(status IN ('pending','deferred','complete_for_reset','already_complete','blocked','manual_required','unresolved')),
                        next_eligible_at REAL,
                        revision INTEGER NOT NULL CHECK(revision >= 0),
                        last_reason_code TEXT NOT NULL,
                        observed_progress_json TEXT NOT NULL,
                        action_count_total INTEGER NOT NULL CHECK(action_count_total >= 0),
                        unresolved_action INTEGER NOT NULL CHECK (unresolved_action IN (0, 1)),
                        evidence_refs_json TEXT NOT NULL,
                        updated_at REAL NOT NULL,
                        PRIMARY KEY (account_id, server_id, reset_id, task_id)
                    );
                    CREATE TABLE actions (
                        action_id TEXT PRIMARY KEY,
                        action_key TEXT NOT NULL UNIQUE,
                        task_id TEXT NOT NULL,
                        semantic_action TEXT NOT NULL,
                        source_state TEXT NOT NULL,
                        target_identity TEXT NOT NULL,
                        target_roi_json TEXT NOT NULL,
                        source_frame_sha256 TEXT NOT NULL,
                        source_frame_captured_at REAL NOT NULL,
                        runtime_profile_id TEXT NOT NULL,
                        game_day_id TEXT,
                        expected_postcondition TEXT NOT NULL,
                        consequence TEXT NOT NULL,
                        cost_type TEXT NOT NULL,
                        cost_amount REAL NOT NULL,
                        quantity INTEGER NOT NULL,
                        consequential INTEGER NOT NULL CHECK (consequential IN (0, 1)),
                        policy_request_json TEXT NOT NULL,
                        policy_decision TEXT NOT NULL,
                        policy_reason TEXT NOT NULL,
                        prepared_at REAL NOT NULL,
                        input_attempt_at REAL,
                        transport_result_json TEXT,
                        reconciliation_result_json TEXT,
                        evidence_refs_json TEXT NOT NULL,
                        final_status TEXT NOT NULL CHECK (final_status IN ('prepared','input_sent','confirmed','unresolved','cancelled')),
                        final_reason TEXT,
                        updated_at REAL NOT NULL
                    );
                    CREATE TABLE audit_events (
                        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        action_id TEXT,
                        task_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        lifecycle_from TEXT,
                        lifecycle_to TEXT,
                        recorded_at REAL NOT NULL,
                        payload_json TEXT NOT NULL
                    );
                    CREATE INDEX actions_status_idx ON actions(final_status);
                    CREATE INDEX audit_action_idx ON audit_events(action_id, event_id);
                    COMMIT;
                    """
                )
        version = self.schema_version
        if version == 1:
            self.connection.executescript(
                """BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS task_state (
                    task_id TEXT PRIMARY KEY,
                    completion_key TEXT NOT NULL,
                    game_day_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','done','blocked','unresolved')),
                    next_due_monotonic REAL,
                    revision INTEGER NOT NULL CHECK(revision >= 0),
                    last_reason TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                UPDATE schema_version SET version=2 WHERE singleton=1;
                COMMIT;
                """
            )
        version = self.schema_version
        if version == 2:
            self.connection.executescript(
                """BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS scheduler_invocation_state (
                    account_id TEXT NOT NULL,
                    server_id TEXT NOT NULL,
                    reset_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','deferred','complete_for_reset','already_complete','blocked','manual_required','unresolved')),
                    next_eligible_at REAL,
                    revision INTEGER NOT NULL CHECK(revision >= 0),
                    last_reason_code TEXT NOT NULL,
                    observed_progress_json TEXT NOT NULL,
                    action_count_total INTEGER NOT NULL CHECK(action_count_total >= 0),
                    unresolved_action INTEGER NOT NULL CHECK (unresolved_action IN (0, 1)),
                    evidence_refs_json TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (account_id, server_id, reset_id, task_id)
                );
                UPDATE schema_version SET version=3 WHERE singleton=1;
                COMMIT;
                """
            )
        if self.schema_version != CURRENT_SCHEMA_VERSION:
            raise SchemaVersionError("database migration did not reach the current schema")

    def audit(
        self,
        task_id: str,
        event_type: str,
        recorded_at: float,
        payload: Any,
        action_id: Optional[str] = None,
        lifecycle_from: Optional[str] = None,
        lifecycle_to: Optional[str] = None,
    ) -> None:
        with self.transaction() as db:
            self._insert_audit(db, task_id, event_type, recorded_at, payload, action_id, lifecycle_from, lifecycle_to)

    @staticmethod
    def _insert_audit(
        db: sqlite3.Connection,
        task_id: str,
        event_type: str,
        recorded_at: float,
        payload: Any,
        action_id: Optional[str],
        lifecycle_from: Optional[str],
        lifecycle_to: Optional[str],
    ) -> None:
        db.execute(
            "INSERT INTO audit_events(action_id,task_id,event_type,lifecycle_from,lifecycle_to,recorded_at,payload_json) VALUES (?,?,?,?,?,?,?)",
            (action_id, task_id, event_type, lifecycle_from, lifecycle_to, recorded_at, _json(payload)),
        )

    def action_key_exists(self, action_key: str) -> bool:
        return self.connection.execute("SELECT 1 FROM actions WHERE action_key=?", (action_key,)).fetchone() is not None

    def prepare_action(self, intent: ActionIntent, policy: PolicyResult, prepared_at: float) -> None:
        try:
            with self.transaction() as db:
                db.execute(
                    """INSERT INTO actions(
                    action_id,action_key,task_id,semantic_action,source_state,target_identity,target_roi_json,
                    source_frame_sha256,source_frame_captured_at,runtime_profile_id,game_day_id,
                    expected_postcondition,consequence,cost_type,cost_amount,quantity,consequential,
                    policy_request_json,policy_decision,policy_reason,prepared_at,evidence_refs_json,
                    final_status,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        intent.action_id, intent.action_key, intent.task_id, intent.semantic_action,
                        intent.source_state, intent.target_identity, _json(intent.target_roi),
                        intent.source_frame_sha256, intent.source_frame_captured_at,
                        intent.runtime_profile_id, intent.game_day_id, intent.expected_postcondition,
                        intent.consequence, intent.cost_type, intent.cost_amount, intent.quantity,
                        int(intent.consequential), _json(policy.request_snapshot), policy.decision.value,
                        policy.reason_code, prepared_at, _json(intent.evidence_refs),
                        ActionStatus.PREPARED.value, prepared_at,
                    ),
                )
                self._insert_audit(
                    db, intent.task_id, "action_transition", prepared_at,
                    {"policy": policy, "intent": intent}, intent.action_id, None, ActionStatus.PREPARED.value,
                )
        except sqlite3.IntegrityError as exc:
            if "action_key" in str(exc) or "UNIQUE" in str(exc):
                raise DuplicateActionError(intent.action_key) from exc
            raise

    def _transition(self, action_id: str, status: ActionStatus, now: float, reason: str, **fields: Any) -> None:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM actions WHERE action_id=?", (action_id,)).fetchone()
            if row is None:
                raise StoreError("unknown action")
            old = row["final_status"]
            if status.value not in ALLOWED_TRANSITIONS[old]:
                raise InvalidTransitionError("invalid transition %s -> %s" % (old, status.value))
            assignments = ["final_status=?", "final_reason=?", "updated_at=?"]
            values: List[Any] = [status.value, reason, now]
            for key, value in fields.items():
                assignments.append(key + "=?")
                values.append(_json(value) if key.endswith("_json") else value)
            values.append(action_id)
            db.execute("UPDATE actions SET %s WHERE action_id=?" % ",".join(assignments), values)
            self._insert_audit(
                db, row["task_id"], "action_transition", now,
                {"reason": reason, "fields": fields}, action_id, old, status.value,
            )

    def mark_input_sent(self, action_id: str, now: float, transport_result: Any) -> None:
        self._transition(
            action_id, ActionStatus.INPUT_SENT, now, "transport_reported_dispatch",
            input_attempt_at=now, transport_result_json=transport_result,
        )

    def mark_confirmed(self, action_id: str, now: float, reconciliation: Any) -> None:
        self._transition(
            action_id, ActionStatus.CONFIRMED, now, "positive_postcondition",
            reconciliation_result_json=reconciliation,
        )

    def mark_unresolved(self, action_id: str, now: float, reason: str, reconciliation: Any = None) -> None:
        row = self.get_action(action_id)
        if row["final_status"] == ActionStatus.UNRESOLVED.value:
            self.audit(row["task_id"], "unresolved_observation", now, {"reason": reason, "reconciliation": reconciliation}, action_id)
            return
        self._transition(
            action_id, ActionStatus.UNRESOLVED, now, reason,
            reconciliation_result_json=reconciliation or {"confirmed": False, "reason": reason},
        )

    def mark_cancelled(self, action_id: str, now: float, reason: str) -> None:
        row = self.get_action(action_id)
        if row["final_status"] == ActionStatus.UNRESOLVED.value and not reason.startswith("proven_no_effect"):
            raise InvalidTransitionError("an unresolved action may be cancelled only with proven no-effect evidence")
        self._transition(action_id, ActionStatus.CANCELLED, now, reason)

    def reconcile_confirmed(self, action_id: str, now: float, positive_evidence: Any) -> None:
        if not positive_evidence:
            raise StoreError("positive evidence is required")
        self.mark_confirmed(action_id, now, positive_evidence)

    def get_action(self, action_id: str) -> Dict[str, Any]:
        row = self.connection.execute("SELECT * FROM actions WHERE action_id=?", (action_id,)).fetchone()
        if row is None:
            raise StoreError("unknown action")
        return dict(row)

    def get_action_by_key(self, action_key: str) -> Optional[Dict[str, Any]]:
        row = self.connection.execute(
            "SELECT * FROM actions WHERE action_key=?",
            (action_key,),
        ).fetchone()
        return dict(row) if row is not None else None

    def supersede_no_effect_cancelled_action(self, action_id: str, now: float, reason: str) -> None:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM actions WHERE action_id=?", (action_id,)).fetchone()
            if row is None:
                raise StoreError("unknown action")
            if not is_no_effect_cancelled(dict(row)):
                raise InvalidTransitionError(
                    "only a no-effect cancelled action may be superseded"
                )
            db.execute("DELETE FROM actions WHERE action_id=?", (action_id,))
            self._insert_audit(
                db,
                row["task_id"],
                "action_superseded",
                now,
                {"reason": reason},
                action_id,
                ActionStatus.CANCELLED.value,
                None,
            )

    def list_actions_for_task(self, task_id: str) -> List[Dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM actions WHERE task_id=? ORDER BY prepared_at",
            (task_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_task_state(self, task_id: str) -> Optional[Dict[str, Any]]:
        row = self.connection.execute("SELECT * FROM task_state WHERE task_id=?", (task_id,)).fetchone()
        return dict(row) if row is not None else None

    def list_task_states(self) -> List[Dict[str, Any]]:
        rows = self.connection.execute("SELECT * FROM task_state ORDER BY task_id").fetchall()
        return [dict(row) for row in rows]

    def upsert_task_state(self, state: Mapping[str, Any], updated_at: float) -> None:
        try:
            task_id = str(state["task_id"])
            completion_key = str(state["completion_key"])
            game_day_id = str(state["game_day_id"])
            status = str(state["status"])
            next_due = state.get("next_due_monotonic")
            revision = int(state["revision"])
            last_reason = str(state.get("last_reason", ""))
        except (KeyError, TypeError, ValueError) as exc:
            raise StoreError("invalid task state") from exc
        if not task_id.strip() or not completion_key.strip() or not game_day_id.strip():
            raise StoreError("task state requires task, completion-key, and game-day identity")
        if status not in TASK_STATE_STATUSES or revision < 0 or not math.isfinite(float(updated_at)):
            raise StoreError("invalid task state status, revision, or update time")
        if next_due is not None and not math.isfinite(float(next_due)):
            raise StoreError("task state due time must be finite or None")
        with self.transaction() as db:
            current = db.execute("SELECT completion_key, revision FROM task_state WHERE task_id=?", (task_id,)).fetchone()
            if current is not None and current["completion_key"] != completion_key:
                raise StoreError("task completion key cannot change")
            if current is not None and revision < int(current["revision"]):
                raise StoreError("task state revision cannot move backward")
            db.execute(
                """INSERT INTO task_state(task_id,completion_key,game_day_id,status,next_due_monotonic,revision,last_reason,updated_at)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET
                game_day_id=excluded.game_day_id,status=excluded.status,next_due_monotonic=excluded.next_due_monotonic,
                revision=excluded.revision,last_reason=excluded.last_reason,updated_at=excluded.updated_at""",
                (task_id, completion_key, game_day_id, status, next_due, revision, last_reason, updated_at),
            )
            self._insert_audit(db, task_id, "task_state_updated", updated_at, {
                "task_id": task_id, "completion_key": completion_key, "game_day_id": game_day_id,
                "status": status, "next_due_monotonic": next_due, "revision": revision,
                "last_reason": last_reason,
            }, None, None, None)

    def get_scheduler_invocation_state(
        self,
        account_id: str,
        server_id: str,
        reset_id: str,
        task_id: str,
    ) -> Optional[Dict[str, Any]]:
        row = self.connection.execute(
            """SELECT * FROM scheduler_invocation_state
               WHERE account_id=? AND server_id=? AND reset_id=? AND task_id=?""",
            (account_id, server_id, reset_id, task_id),
        ).fetchone()
        return dict(row) if row is not None else None

    def list_scheduler_invocation_states(self) -> List[Dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT * FROM scheduler_invocation_state
               ORDER BY account_id, server_id, reset_id, task_id"""
        ).fetchall()
        return [dict(row) for row in rows]

    def upsert_scheduler_invocation_state(self, state: Mapping[str, Any], updated_at: float) -> None:
        try:
            account_id = str(state["account_id"])
            server_id = str(state["server_id"])
            reset_id = str(state["reset_id"])
            task_id = str(state["task_id"])
            status = str(state["status"])
            next_eligible = state.get("next_eligible_at")
            revision = int(state["revision"])
            last_reason_code = str(state.get("last_reason_code", ""))
            observed_progress_json = str(state.get("observed_progress_json", "{}"))
            action_count_total = int(state.get("action_count_total", 0))
            unresolved_action = 1 if state.get("unresolved_action") else 0
            evidence_refs_json = str(state.get("evidence_refs_json", "[]"))
        except (KeyError, TypeError, ValueError) as exc:
            raise StoreError("invalid scheduler invocation state") from exc
        if not all(value.strip() for value in (account_id, server_id, reset_id, task_id)):
            raise StoreError("scheduler invocation state requires account/server/reset/task identity")
        if status not in SCHEDULER_INVOCATION_STATUSES or revision < 0 or action_count_total < 0:
            raise StoreError("invalid scheduler invocation status, revision, or action count")
        if not math.isfinite(float(updated_at)):
            raise StoreError("invalid scheduler invocation update time")
        if next_eligible is not None and not math.isfinite(float(next_eligible)):
            raise StoreError("next_eligible_at must be finite or None")
        with self.transaction() as db:
            current = db.execute(
                """SELECT revision FROM scheduler_invocation_state
                   WHERE account_id=? AND server_id=? AND reset_id=? AND task_id=?""",
                (account_id, server_id, reset_id, task_id),
            ).fetchone()
            if current is not None and revision < int(current["revision"]):
                raise StoreError("scheduler invocation revision cannot move backward")
            db.execute(
                """INSERT INTO scheduler_invocation_state(
                    account_id, server_id, reset_id, task_id, status, next_eligible_at, revision,
                    last_reason_code, observed_progress_json, action_count_total, unresolved_action,
                    evidence_refs_json, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(account_id, server_id, reset_id, task_id) DO UPDATE SET
                    status=excluded.status,
                    next_eligible_at=excluded.next_eligible_at,
                    revision=excluded.revision,
                    last_reason_code=excluded.last_reason_code,
                    observed_progress_json=excluded.observed_progress_json,
                    action_count_total=excluded.action_count_total,
                    unresolved_action=excluded.unresolved_action,
                    evidence_refs_json=excluded.evidence_refs_json,
                    updated_at=excluded.updated_at
                """,
                (
                    account_id,
                    server_id,
                    reset_id,
                    task_id,
                    status,
                    next_eligible,
                    revision,
                    last_reason_code,
                    observed_progress_json,
                    action_count_total,
                    unresolved_action,
                    evidence_refs_json,
                    updated_at,
                ),
            )
            self._insert_audit(
                db,
                task_id,
                "scheduler_invocation_state_updated",
                updated_at,
                {
                    "account_id": account_id,
                    "server_id": server_id,
                    "reset_id": reset_id,
                    "task_id": task_id,
                    "status": status,
                    "next_eligible_at": next_eligible,
                    "revision": revision,
                    "last_reason_code": last_reason_code,
                    "action_count_total": action_count_total,
                    "unresolved_action": bool(unresolved_action),
                },
                None,
                None,
                None,
            )

    def list_nonterminal_actions(self) -> List[Dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM actions WHERE final_status IN ('prepared','input_sent') ORDER BY prepared_at"
        ).fetchall()
        return [dict(row) for row in rows]

    def list_unresolved_actions(self, consequential_only: bool = True) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM actions WHERE final_status='unresolved'"
        if consequential_only:
            sql += " AND consequential=1"
        sql += " ORDER BY prepared_at"
        return [dict(row) for row in self.connection.execute(sql).fetchall()]

    def has_unresolved_action(self) -> bool:
        return bool(self.list_unresolved_actions())

    def has_action_block(self, exclude_action_id: Optional[str] = None) -> bool:
        """Block dispatch while an action is unresolved or awaits reconciliation."""
        sql = "SELECT 1 FROM actions WHERE consequential=1 AND final_status IN ('prepared','input_sent','unresolved')"
        params = ()
        if exclude_action_id is not None:
            sql += " AND action_id<>?"
            params = (exclude_action_id,)
        return self.connection.execute(sql + " LIMIT 1", params).fetchone() is not None

    def startup_reconcile(self, now: float) -> List[str]:
        """Conservatively make every persisted ambiguous boundary globally blocking."""
        action_ids = [row["action_id"] for row in self.list_nonterminal_actions()]
        for action_id in action_ids:
            self.mark_unresolved(
                action_id,
                now,
                "restart_nonterminal_requires_reconciliation",
                {"confirmed": False, "automatic_retry": False},
            )
        return action_ids

    def acquire_lease(self, owner_id: str, now: float, ttl_seconds: float) -> Dict[str, Any]:
        if ttl_seconds <= 0:
            raise LeaseError("lease TTL must be positive")
        with self.transaction() as db:
            row = db.execute("SELECT * FROM controller_lease WHERE singleton=1").fetchone()
            active = row is not None and row["released_at"] is None and row["expires_at"] > now
            if active and row["owner_id"] != owner_id:
                raise LeaseError("controller lease is held by another owner")
            needs_new_acquisition = not (active and row["owner_id"] == owner_id)
            if needs_new_acquisition and self.has_action_block():
                raise LeaseError("unresolved or nonterminal action blocks lease acquisition or takeover")
            acquired = row["acquired_at"] if active and row["owner_id"] == owner_id else now
            db.execute(
                """INSERT INTO controller_lease(singleton,owner_id,acquired_at,heartbeat_at,expires_at,released_at)
                VALUES(1,?,?,?,?,NULL) ON CONFLICT(singleton) DO UPDATE SET
                owner_id=excluded.owner_id,acquired_at=excluded.acquired_at,
                heartbeat_at=excluded.heartbeat_at,expires_at=excluded.expires_at,released_at=NULL""",
                (owner_id, acquired, now, now + ttl_seconds),
            )
            self._insert_audit(db, "controller", "lease_acquired", now, {"owner_id": owner_id, "expires_at": now + ttl_seconds}, None, None, None)
        return self.get_lease(now)

    def heartbeat_lease(self, owner_id: str, now: float, ttl_seconds: float) -> Dict[str, Any]:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM controller_lease WHERE singleton=1").fetchone()
            if row is None or row["owner_id"] != owner_id or row["released_at"] is not None or row["expires_at"] <= now:
                raise LeaseError("owner does not hold an active lease")
            db.execute("UPDATE controller_lease SET heartbeat_at=?,expires_at=? WHERE singleton=1", (now, now + ttl_seconds))
        return self.get_lease(now)

    def release_lease(self, owner_id: str, now: float) -> None:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM controller_lease WHERE singleton=1").fetchone()
            if row is None or row["owner_id"] != owner_id or row["released_at"] is not None:
                raise LeaseError("owner does not hold the lease")
            db.execute("UPDATE controller_lease SET released_at=? WHERE singleton=1", (now,))
            self._insert_audit(db, "controller", "lease_released", now, {"owner_id": owner_id}, None, None, None)

    def get_lease(self, now: float) -> Optional[Dict[str, Any]]:
        row = self.connection.execute("SELECT * FROM controller_lease WHERE singleton=1").fetchone()
        if row is None:
            return None
        result = dict(row)
        result["valid"] = result["released_at"] is None and result["expires_at"] > now
        return result

    def lease_valid_for(self, owner_id: str, now: float) -> bool:
        lease = self.get_lease(now)
        return bool(lease and lease["valid"] and lease["owner_id"] == owner_id)

    def audit_events(self, action_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if action_id is None:
            rows = self.connection.execute("SELECT * FROM audit_events ORDER BY event_id").fetchall()
        else:
            rows = self.connection.execute("SELECT * FROM audit_events WHERE action_id=? ORDER BY event_id", (action_id,)).fetchall()
        return [dict(row) for row in rows]
