"""Versioned SQLite journal, append-only audit log, and controller lease."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .models import ActionIntent, ActionStatus, PolicyResult, snapshot

CURRENT_SCHEMA_VERSION = 1
ALLOWED_TRANSITIONS = {
    ActionStatus.PREPARED.value: {
        ActionStatus.INPUT_SENT.value,
        ActionStatus.UNRESOLVED.value,
        ActionStatus.CANCELLED.value,
    },
    ActionStatus.INPUT_SENT.value: {ActionStatus.CONFIRMED.value, ActionStatus.UNRESOLVED.value},
    ActionStatus.UNRESOLVED.value: {ActionStatus.CONFIRMED.value},
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


class SafetyStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.connection = sqlite3.connect(str(self.path), isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self._migrate()

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
                    INSERT OR REPLACE INTO schema_version(singleton, version) VALUES (1, 1);
                    CREATE TABLE controller_lease (
                        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                        owner_id TEXT NOT NULL,
                        acquired_at REAL NOT NULL,
                        heartbeat_at REAL NOT NULL,
                        expires_at REAL NOT NULL,
                        released_at REAL
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
