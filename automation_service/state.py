"""Canonical SQLite runtime authority for the automation service.

Only mutable service, flow, run, and action facts live here.  Static
:class:`~automation_service.contracts.FlowSpec` values seed missing flow rows;
this database is the sole authority after initialization.  No queue, Git,
registry, CLI, or evidence state is consulted by this module.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import hashlib
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Iterable, Iterator
from uuid import uuid4

from .contracts import FlowSpec


class RunState(str, Enum):
    """Persisted lifecycle for one claimed occurrence."""

    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    STOP_REQUESTED = "STOP_REQUESTED"
    RECOVERING = "RECOVERING"
    SUCCEEDED = "SUCCEEDED"
    DEFERRED = "DEFERRED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"


class ActionState(str, Enum):
    """Persisted lifecycle for one possible external input."""

    RESERVED = "RESERVED"
    CANCELLED = "CANCELLED"
    DISPATCHING = "DISPATCHING"
    SUCCEEDED = "SUCCEEDED"
    NO_EFFECT = "NO_EFFECT"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class ServiceLease:
    """Exclusive service-loop lease and process identity."""

    owner_instance_id: str | None
    process_id: int | None
    process_start_token: str | None
    lease_generation: int
    heartbeat_at_utc: float | None
    expires_at_utc: float | None
    row_version: int
    @property
    def lease_heartbeat_at_utc(self) -> float | None:
        return self.heartbeat_at_utc

    @property
    def lease_expires_at_utc(self) -> float | None:
        return self.expires_at_utc
    @property
    def lease_expiry_at_utc(self) -> float | None:
        return self.expires_at_utc




@dataclass(frozen=True)
class ServiceControl:
    """Global enable gate and monotonic emergency generation."""

    enabled: bool
    generation: int
    emergency_reason: str | None
    emergency_at_utc: float | None
    updated_at_utc: float
    row_version: int


@dataclass(frozen=True)
class ClockObservation:
    """Persisted UTC high-water observation used to fail closed on rollback."""

    observed_at_utc: float
    high_water_utc: float
    clock_rollback: bool
    accepted: bool
    row_version: int

    @property
    def rollback(self) -> bool:
        """Short compatibility spelling for scheduler clock gates."""

        return self.clock_rollback

    @property
    def high_water(self) -> float:
        return self.high_water_utc




@dataclass(frozen=True)
class FlowState:
    """Mutable flow enable, block, schedule, retry, and accepted projection facts."""

    flow_id: str
    enabled: bool
    generation: int
    blocked: bool
    blocked_reason: str | None
    priority: int
    cadence: str
    max_wait_seconds: float | None
    max_attempts: int
    next_occurrence_key: int
    next_due_at_utc: float | None
    schedule_anchor_utc: float | None
    reset_id: str | None
    retry_not_before_utc: float | None
    eligible_since_utc: float | None
    last_started_at_utc: float | None
    last_completed_at_utc: float | None
    last_outcome: str | None
    consecutive_failures: int
    row_version: int
    last_accepted_projection_key: str | None = None


@dataclass(frozen=True)
class RunRecord:
    """Claim identity, generation fences, lifecycle, and action budgets."""

    run_id: str
    flow_id: str
    occurrence_key: str
    reset_id: str
    claimed_flow_generation: int
    service_generation: int
    owner_instance_id: str
    process_start_token: str
    lease_generation: int
    run_token: str
    mode: str
    state: RunState
    claimed_at_utc: float
    started_at_utc: float | None
    heartbeat_at_utc: float | None
    stop_requested_at_utc: float | None
    terminal_at_utc: float | None
    max_inputs: int
    max_actions: int
    consumed_inputs: int
    consumed_actions: int
    terminal_outcome: str | None
    terminal_reason: str | None
    row_version: int


@dataclass(frozen=True)
class ActionRecord:
    """Reservation identity, provenance bindings, and dispatch lifecycle."""

    action_id: str
    run_id: str
    sequence_no: int
    idempotency_key: str
    semantic_action_key: str
    source_capture_id: str | None
    source_frame_hash: str | None
    source_stable_roi_digest: str | None
    source_binding_digest: str | None
    target_identity: str | None
    target_binding_digest: str | None
    binding_fingerprint: str | None
    action_class: str | None
    quantity: int
    input_cost: int
    state: ActionState
    reserved_at_utc: float
    dispatching_at_utc: float | None
    completed_at_utc: float | None
    retry_of_action_id: str | None
    hypothesis_digest: str | None
    successor_screen: str | None
    successor_binding_digest: str | None
    outcome_reason: str | None
    transport_summary: str | None
    consequence_summary: str | None
    row_version: int


@dataclass(frozen=True)
class DispatchValidation:
    """Atomic result of the final service/flow/run fence check."""

    valid: bool
    reason: str
    service_generation: int | None = None
    flow_generation: int | None = None
    run_state: RunState | None = None


class StateError(RuntimeError):
    """Malformed state-manager operation."""


class StateTransitionError(StateError):
    """Unknown enum value; persisted invalid transitions return ``None``."""


class TerminalProjectionError(StateTransitionError):
    """A terminal run projection failed its ownership or row CAS fence."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)

_ACTIVE_RUN_STATES = ("CLAIMED", "RUNNING", "STOP_REQUESTED", "RECOVERING")
_TERMINAL_RUN_STATES = {
    RunState.SUCCEEDED,
    RunState.DEFERRED,
    RunState.BLOCKED,
    RunState.FAILED,
    RunState.ABANDONED,
}
_TERMINAL_ACTION_STATES = {
    ActionState.CANCELLED,
    ActionState.SUCCEEDED,
    ActionState.NO_EFFECT,
    ActionState.BLOCKED,
}
_UNSET = object()


def _now() -> float:
    return time.time()


def _epoch(value: float | int | None, name: str, *, allow_none: bool = True) -> float | None:
    if value is None and allow_none:
        return None
    if value is None or isinstance(value, bool):
        raise ValueError(f"{name} must be a finite non-negative UTC epoch")
    result = float(value)
    if not result >= 0 or not result < float("inf"):
        raise ValueError(f"{name} must be a finite non-negative UTC epoch")
    return result


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value.strip()


def _nonnegative_int(value: int, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value



def _binding_fingerprint(
    source_stable_roi_digest: str | None,
    source_binding_digest: str | None,
    target_identity: str | None,
    target_binding_digest: str | None,
) -> str | None:
    """Derive a stable action binding key, excluding volatile frame hashes."""

    required = (source_binding_digest, target_identity, target_binding_digest)
    if any(not isinstance(value, str) or not value.strip() for value in required):
        return None
    values = (
        "" if source_stable_roi_digest is None else source_stable_roi_digest.strip(),
        source_binding_digest.strip(),  # type: ignore[union-attr]
        target_identity.strip(),  # type: ignore[union-attr]
        target_binding_digest.strip(),  # type: ignore[union-attr]
    )
    encoded = "\x1f".join(f"{len(value)}:{value}" for value in values).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

class BotStateManager:
    """Own the bounded SQLite authority for service, flows, runs, and actions.

    Every mutation uses a short ``BEGIN IMMEDIATE`` transaction and commits
    before returning.  This manager never runs external work in a transaction;
    callers reserve or transition state, perform external work, then record its
    result in a later transaction.
    """

    DEFAULT_DB_PATH = ".local-orchestrator/bot-state.sqlite3"

    def __init__(
        self,
        db_path: str | os.PathLike[str] = DEFAULT_DB_PATH,
        *,
        owner_instance_id: str | None = None,
        process_start_token: str | None = None,
        process_id: int | None = None,
        busy_timeout_ms: int = 5_000,
    ) -> None:
        if type(busy_timeout_ms) is not int or busy_timeout_ms < 1:
            raise ValueError("busy_timeout_ms must be a positive integer")
        self.db_path = str(db_path)
        self.owner_instance_id = _text(
            f"bot-{uuid4().hex}" if owner_instance_id is None else owner_instance_id,
            "owner_instance_id",
        )
        self.process_start_token = _text(
            uuid4().hex if process_start_token is None else process_start_token,
            "process_start_token",
        )
        self.process_id = os.getpid() if process_id is None else process_id
        if type(self.process_id) is not int or self.process_id < 0:
            raise ValueError("process_id must be a non-negative integer")
        self._lock = threading.RLock()
        if self.db_path not in {":memory:", ""}:
            Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(
            self.db_path,
            timeout=busy_timeout_ms / 1_000,
            isolation_level=None,
            check_same_thread=False,
        )
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute("PRAGMA synchronous = FULL")
        self._db.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
        self._create_schema()

    def close(self) -> None:
        """Close the SQLite connection after external callers have stopped using it."""

        with self._lock:
            self._db.close()

    def __enter__(self) -> "BotStateManager":
        return self

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """Serialize a short local SQLite transaction, never external work."""

        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
            except Exception:
                self._db.rollback()
                raise
            else:
                self._db.commit()

    def _create_schema(self) -> None:
        with self._transaction() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS service_control (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                    generation INTEGER NOT NULL CHECK (generation >= 0),
                    emergency_reason TEXT,
                    emergency_at_utc REAL,
                    updated_at_utc REAL NOT NULL,
                    row_version INTEGER NOT NULL CHECK (row_version >= 0)
                );
                INSERT OR IGNORE INTO service_control
                    (singleton_id, enabled, generation, emergency_reason,
                     emergency_at_utc, updated_at_utc, row_version)
                VALUES (1, 0, 0, NULL, NULL, 0, 0);
                CREATE TABLE IF NOT EXISTS service_lease (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    owner_instance_id TEXT,
                    process_id INTEGER,
                    process_start_token TEXT,
                    lease_generation INTEGER NOT NULL CHECK (lease_generation >= 0),
                    heartbeat_at_utc REAL,
                    expires_at_utc REAL,
                    row_version INTEGER NOT NULL CHECK (row_version >= 0)
                );
                INSERT OR IGNORE INTO service_lease
                    (singleton_id, owner_instance_id, process_id, process_start_token,
                     lease_generation, heartbeat_at_utc, expires_at_utc, row_version)
                VALUES (1, NULL, NULL, NULL, 0, NULL, NULL, 0);
                CREATE TABLE IF NOT EXISTS clock_state (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    high_water_utc REAL NOT NULL CHECK (high_water_utc >= 0),
                    observed_at_utc REAL NOT NULL CHECK (observed_at_utc >= 0),
                    row_version INTEGER NOT NULL CHECK (row_version >= 0)
                );
                INSERT OR IGNORE INTO clock_state
                    (singleton_id, high_water_utc, observed_at_utc, row_version)
                VALUES (1, 0, 0, 0);


                CREATE TABLE IF NOT EXISTS flow_state (
                    flow_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                    generation INTEGER NOT NULL CHECK (generation >= 0),
                    blocked INTEGER NOT NULL CHECK (blocked IN (0, 1)),
                    blocked_reason TEXT,
                    priority INTEGER NOT NULL CHECK (priority >= 0),
                    cadence TEXT NOT NULL,
                    max_wait_seconds REAL,
                    max_attempts INTEGER NOT NULL CHECK (max_attempts >= 1),
                    next_occurrence_key INTEGER NOT NULL CHECK (next_occurrence_key >= 0),
                    next_due_at_utc REAL,
                    schedule_anchor_utc REAL,
                    reset_id TEXT,
                    retry_not_before_utc REAL,
                    eligible_since_utc REAL,
                    last_started_at_utc REAL,
                    last_completed_at_utc REAL,
                    last_outcome TEXT,
                    last_accepted_projection_key TEXT,
                    consecutive_failures INTEGER NOT NULL CHECK (consecutive_failures >= 0),
                    row_version INTEGER NOT NULL CHECK (row_version >= 0)
                );

                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    flow_id TEXT NOT NULL REFERENCES flow_state(flow_id),
                    occurrence_key TEXT NOT NULL,
                    reset_id TEXT NOT NULL,
                    claimed_flow_generation INTEGER NOT NULL CHECK (claimed_flow_generation >= 0),
                    service_generation INTEGER NOT NULL CHECK (service_generation >= 0),
                    owner_instance_id TEXT NOT NULL,
                    process_start_token TEXT NOT NULL,
                    lease_generation INTEGER NOT NULL CHECK (lease_generation >= 0),
                    run_token TEXT NOT NULL,
                    occurrence_ordinal INTEGER NOT NULL CHECK (occurrence_ordinal >= 0),
                    mode TEXT NOT NULL CHECK (mode IN ('scheduled', 'manual')),
                    state TEXT NOT NULL CHECK (state IN (
                        'CLAIMED', 'RUNNING', 'STOP_REQUESTED', 'RECOVERING',
                        'SUCCEEDED', 'DEFERRED', 'BLOCKED', 'FAILED', 'ABANDONED'
                    )),
                    claimed_at_utc REAL NOT NULL,
                    started_at_utc REAL,
                    heartbeat_at_utc REAL,
                    stop_requested_at_utc REAL,
                    terminal_at_utc REAL,
                    max_inputs INTEGER NOT NULL CHECK (max_inputs >= 0),
                    max_actions INTEGER NOT NULL CHECK (max_actions >= 0),
                    consumed_inputs INTEGER NOT NULL CHECK (consumed_inputs >= 0),
                    consumed_actions INTEGER NOT NULL CHECK (consumed_actions >= 0),
                    terminal_outcome TEXT,
                    terminal_reason TEXT,
                    row_version INTEGER NOT NULL CHECK (row_version >= 0),
                    UNIQUE (flow_id, occurrence_key)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS runs_one_active_idx
                    ON runs ((1))
                    WHERE state IN ('CLAIMED', 'RUNNING', 'STOP_REQUESTED', 'RECOVERING');

                CREATE TABLE IF NOT EXISTS actions (
                    action_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    sequence_no INTEGER NOT NULL CHECK (sequence_no >= 1),
                    idempotency_key TEXT NOT NULL UNIQUE,
                    semantic_action_key TEXT NOT NULL,
                    source_capture_id TEXT,
                    source_frame_hash TEXT,
                    source_stable_roi_digest TEXT,
                    source_binding_digest TEXT,
                    target_identity TEXT,
                    target_binding_digest TEXT,
                    binding_fingerprint TEXT,
                    action_class TEXT,
                    quantity INTEGER NOT NULL CHECK (quantity >= 1),
                    input_cost INTEGER NOT NULL CHECK (input_cost >= 0),
                    state TEXT NOT NULL CHECK (state IN (
                        'RESERVED', 'CANCELLED', 'DISPATCHING', 'SUCCEEDED',
                        'NO_EFFECT', 'UNKNOWN', 'BLOCKED'
                    )),
                    reserved_at_utc REAL NOT NULL,
                    dispatching_at_utc REAL,
                    completed_at_utc REAL,
                    retry_of_action_id TEXT REFERENCES actions(action_id),
                    hypothesis_digest TEXT,
                    successor_screen TEXT,
                    successor_binding_digest TEXT,
                    outcome_reason TEXT,
                    transport_summary TEXT,
                    consequence_summary TEXT,
                    row_version INTEGER NOT NULL CHECK (row_version >= 0),
                    UNIQUE (run_id, sequence_no)
                );
                """
            )
            existing = {
                str(item["name"])
                for item in db.execute("PRAGMA table_info(runs)").fetchall()
            }
            migrations = (
                ("process_start_token", "TEXT NOT NULL DEFAULT ''"),
                ("lease_generation", "INTEGER NOT NULL DEFAULT 0"),
                ("run_token", "TEXT NOT NULL DEFAULT ''"),
                ("occurrence_ordinal", "INTEGER NOT NULL DEFAULT 0"),
            )
            for column, declaration in migrations:
                if column not in existing:
                    db.execute(f"ALTER TABLE runs ADD COLUMN {column} {declaration}")
            existing_flows = {
                str(item["name"])
                for item in db.execute("PRAGMA table_info(flow_state)").fetchall()
            }
            if "last_accepted_projection_key" not in existing_flows:
                db.execute(
                    "ALTER TABLE flow_state ADD COLUMN last_accepted_projection_key TEXT"
                )
            existing_actions = {str(item["name"]) for item in db.execute("PRAGMA table_info(actions)").fetchall()}
            action_migrations = (
                ("source_stable_roi_digest", "TEXT"),
                ("binding_fingerprint", "TEXT"),
            )
            for column, declaration in action_migrations:
                if column not in existing_actions:
                    db.execute(f"ALTER TABLE actions ADD COLUMN {column} {declaration}")
            db.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS actions_binding_hypothesis_idx
                   ON actions(run_id, binding_fingerprint, COALESCE(hypothesis_digest, ''))
                   WHERE binding_fingerprint IS NOT NULL"""
            )
    @staticmethod
    def occurrence_key(flow_id: str, reset_id: str, ordinal: int) -> str:
        """Derive a deterministic occurrence identity from flow/reset/ordinal."""

        return f"{_text(flow_id, 'flow_id')}:{_text(reset_id, 'reset_id')}:{_nonnegative_int(ordinal, 'ordinal')}"

    @staticmethod
    def _lease(row: sqlite3.Row) -> ServiceLease:
        return ServiceLease(
            row["owner_instance_id"],
            None if row["process_id"] is None else int(row["process_id"]),
            row["process_start_token"],
            int(row["lease_generation"]),
            row["heartbeat_at_utc"],
            row["expires_at_utc"],
            int(row["row_version"]),
        )


    @staticmethod
    def _service(row: sqlite3.Row) -> ServiceControl:
        return ServiceControl(bool(row["enabled"]), int(row["generation"]), row["emergency_reason"], row["emergency_at_utc"], float(row["updated_at_utc"]), int(row["row_version"]))

    @staticmethod
    def _flow(row: sqlite3.Row) -> FlowState:
        return FlowState(
            row["flow_id"], bool(row["enabled"]), int(row["generation"]), bool(row["blocked"]),
            row["blocked_reason"], int(row["priority"]), row["cadence"], row["max_wait_seconds"],
            int(row["max_attempts"]), int(row["next_occurrence_key"]), row["next_due_at_utc"],
            row["schedule_anchor_utc"], row["reset_id"], row["retry_not_before_utc"],
            row["eligible_since_utc"], row["last_started_at_utc"], row["last_completed_at_utc"],
            row["last_outcome"], int(row["consecutive_failures"]), int(row["row_version"]),
            row["last_accepted_projection_key"],
        )

    @staticmethod
    def _run(row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            row["run_id"], row["flow_id"], row["occurrence_key"], row["reset_id"],
            int(row["claimed_flow_generation"]), int(row["service_generation"]), row["owner_instance_id"],
            row["process_start_token"], int(row["lease_generation"]), row["run_token"],
            row["mode"], RunState(row["state"]), float(row["claimed_at_utc"]), row["started_at_utc"],
            row["heartbeat_at_utc"], row["stop_requested_at_utc"], row["terminal_at_utc"],
            int(row["max_inputs"]), int(row["max_actions"]), int(row["consumed_inputs"]),
            int(row["consumed_actions"]), row["terminal_outcome"], row["terminal_reason"], int(row["row_version"]),
        )

    @staticmethod
    def _action(row: sqlite3.Row) -> ActionRecord:
        return ActionRecord(
            row["action_id"], row["run_id"], int(row["sequence_no"]), row["idempotency_key"],
            row["semantic_action_key"], row["source_capture_id"], row["source_frame_hash"],
            row["source_stable_roi_digest"], row["source_binding_digest"], row["target_identity"],
            row["target_binding_digest"], row["binding_fingerprint"], row["action_class"],
            int(row["quantity"]), int(row["input_cost"]), ActionState(row["state"]),
            float(row["reserved_at_utc"]), row["dispatching_at_utc"], row["completed_at_utc"],
            row["retry_of_action_id"], row["hypothesis_digest"], row["successor_screen"],
            row["successor_binding_digest"], row["outcome_reason"], row["transport_summary"],
            row["consequence_summary"], int(row["row_version"]),
        )

    @staticmethod
    def _clock(row: sqlite3.Row, *, now_utc_epoch: float | None = None) -> ClockObservation:
        observed = float(row["observed_at_utc"])
        high_water = float(row["high_water_utc"])
        rollback = now_utc_epoch is not None and float(now_utc_epoch) < high_water
        return ClockObservation(
            observed,
            high_water,
            rollback,
            not rollback,
            int(row["row_version"]),
        )

    def get_clock(self) -> ClockObservation:
        """Read the persisted UTC high-water without changing it."""

        row = self._db.execute("SELECT * FROM clock_state WHERE singleton_id = 1").fetchone()
        if row is None:
            raise StateError("clock_state row is missing")
        return self._clock(row)

    def observe_clock(self, now_utc_epoch: float | None = None) -> ClockObservation:
        """Persist one UTC observation and fail closed when it rolls backward."""

        now = _epoch(_now() if now_utc_epoch is None else now_utc_epoch, "now", allow_none=False)
        assert now is not None
        with self._transaction() as db:
            row = db.execute("SELECT * FROM clock_state WHERE singleton_id = 1").fetchone()
            if row is None:
                raise StateError("clock_state row is missing")
            high_water = max(float(row["high_water_utc"]), now)
            db.execute(
                """UPDATE clock_state SET high_water_utc = ?, observed_at_utc = ?,
                   row_version = row_version + 1 WHERE singleton_id = 1""",
                (high_water, now),
            )
            return self._clock(
                db.execute("SELECT * FROM clock_state WHERE singleton_id = 1").fetchone(),
                now_utc_epoch=now,
            )

    observe_utc = observe_clock


    def get_service(self) -> ServiceControl:
        """Read the sole global gate and generation fence."""

        row = self._db.execute("SELECT * FROM service_control WHERE singleton_id = 1").fetchone()
        if row is None:
            raise StateError("service_control row is missing")
        return self._service(row)

    def get_service_enabled(self) -> bool:
        """Return the persisted global transport gate."""

        return self.get_service().enabled
    def get_service_lease(self) -> ServiceLease:
        """Read the current exclusive service lease."""

        row = self._db.execute("SELECT * FROM service_lease WHERE singleton_id = 1").fetchone()
        if row is None:
            raise StateError("service_lease row is missing")
        return self._lease(row)

    def acquire_service_lease(
        self,
        *,
        owner_instance_id: str | None = None,
        process_start_token: str | None = None,
        process_id: int | None = None,
        lease_ttl_seconds: float = 60.0,
        now_utc_epoch: float | None = None,
    ) -> ServiceLease | None:
        """Acquire or renew the singleton lease, fencing any expired owner."""

        owner = _text(
            self.owner_instance_id if owner_instance_id is None else owner_instance_id,
            "owner_instance_id",
        )
        token = _text(
            self.process_start_token if process_start_token is None else process_start_token,
            "process_start_token",
        )
        pid = self.process_id if process_id is None else process_id
        if type(pid) is not int or pid < 0:
            raise ValueError("process_id must be a non-negative integer")
        ttl = float(lease_ttl_seconds)
        if isinstance(lease_ttl_seconds, bool) or not ttl > 0 or not ttl < float("inf"):
            raise ValueError("lease_ttl_seconds must be a finite positive number")
        now = _epoch(_now() if now_utc_epoch is None else now_utc_epoch, "now", allow_none=False)
        assert now is not None
        with self._transaction() as db:
            row = db.execute("SELECT * FROM service_lease WHERE singleton_id = 1").fetchone()
            if row is None:
                raise StateError("service_lease row is missing")
            active = row["owner_instance_id"] is not None and row["expires_at_utc"] is not None and float(row["expires_at_utc"]) > now
            if active and (row["owner_instance_id"], row["process_start_token"]) != (owner, token):
                return None
            generation = int(row["lease_generation"]) if active else int(row["lease_generation"]) + 1
            db.execute(
                """UPDATE service_lease SET owner_instance_id = ?, process_id = ?,
                   process_start_token = ?, lease_generation = ?, heartbeat_at_utc = ?,
                   expires_at_utc = ?, row_version = row_version + 1 WHERE singleton_id = 1""",
                (owner, pid, token, generation, now, now + ttl),
            )
            return self._lease(db.execute("SELECT * FROM service_lease WHERE singleton_id = 1").fetchone())

    def renew_service_lease(
        self,
        *,
        owner_instance_id: str | None = None,
        process_start_token: str | None = None,
        lease_generation: int | None = None,
        lease_ttl_seconds: float = 60.0,
        now_utc_epoch: float | None = None,
    ) -> ServiceLease | None:
        """Heartbeat an unexpired lease only with its exact generation."""

        owner = _text(owner_instance_id or self.owner_instance_id, "owner_instance_id")
        token = _text(process_start_token or self.process_start_token, "process_start_token")
        if type(lease_generation) is not int or lease_generation < 1:
            return None
        ttl = float(lease_ttl_seconds)

        if isinstance(lease_ttl_seconds, bool) or not ttl > 0 or not ttl < float("inf"):
            raise ValueError("lease_ttl_seconds must be a finite positive number")
        now = _epoch(_now() if now_utc_epoch is None else now_utc_epoch, "now", allow_none=False)
        assert now is not None
        with self._transaction() as db:
            row = db.execute("SELECT * FROM service_lease WHERE singleton_id = 1").fetchone()
            if row is None or row["owner_instance_id"] != owner or row["process_start_token"] != token:
                return None
            if int(row["lease_generation"]) != lease_generation or row["expires_at_utc"] is None or float(row["expires_at_utc"]) <= now:
                return None
            db.execute(
                "UPDATE service_lease SET heartbeat_at_utc = ?, expires_at_utc = ?, row_version = row_version + 1 WHERE singleton_id = 1 AND lease_generation = ?",
                (now, now + ttl, lease_generation),
            )
            return self._lease(db.execute("SELECT * FROM service_lease WHERE singleton_id = 1").fetchone())

    def has_unresolved_actions(self, run_id: str) -> bool:
        """Return whether a run contains an effect that still needs reconciliation."""

        run_id = _text(run_id, "run_id")
        return (
            self._db.execute(
                "SELECT 1 FROM actions WHERE run_id = ? AND state = 'UNKNOWN' LIMIT 1",
                (run_id,),
            ).fetchone()
            is not None
        )

    def can_retry_run(self, run_id: str) -> bool:
        """Return whether a terminal run may be automatically reclaimed."""

        run_id = _text(run_id, "run_id")
        row = self._db.execute("SELECT state FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return bool(
            row is not None
            and row["state"] in {RunState.FAILED.value, RunState.BLOCKED.value}
            and not self.has_unresolved_actions(run_id)
        )

    def release_service_lease(
        self,
        *,
        owner_instance_id: str | None = None,
        process_start_token: str | None = None,
        lease_generation: int | None = None,
    ) -> bool:
        """Release the lease only for its current owner, token, and generation."""

        owner = _text(owner_instance_id or self.owner_instance_id, "owner_instance_id")
        token = _text(process_start_token or self.process_start_token, "process_start_token")
        if type(lease_generation) is not int or lease_generation < 1:
            return False
        with self._transaction() as db:
            result = db.execute(
                """UPDATE service_lease SET owner_instance_id = NULL, process_id = NULL,
                   process_start_token = NULL, heartbeat_at_utc = NULL, expires_at_utc = NULL,
                   lease_generation = lease_generation + 1, row_version = row_version + 1
                   WHERE singleton_id = 1 AND owner_instance_id = ? AND process_start_token = ?
                     AND lease_generation = ?""",
                (owner, token, lease_generation),
            )
            return result.rowcount == 1
    heartbeat_service_lease = renew_service_lease
    acquire_lease = acquire_service_lease
    renew_lease = renew_service_lease
    release_lease = release_service_lease


    @staticmethod
    def _lease_matches(
        db: sqlite3.Connection,
        *,
        owner_instance_id: str | None,
        process_start_token: str | None,
        lease_generation: int | None,
        now_utc_epoch: float,
    ) -> str | None:
        """Return a lease-fence reason, or ``None`` when the lease is valid."""

        if owner_instance_id is None or process_start_token is None or type(lease_generation) is not int:
            return "SERVICE_LEASE_REQUIRED"
        lease = db.execute("SELECT * FROM service_lease WHERE singleton_id = 1").fetchone()
        if lease is None:
            return "SERVICE_LEASE_MISSING"
        if (
            lease["owner_instance_id"] != owner_instance_id
            or lease["process_start_token"] != process_start_token
            or int(lease["lease_generation"]) != lease_generation
        ):
            return "SERVICE_LEASE_MISMATCH"
        if lease["expires_at_utc"] is None or float(lease["expires_at_utc"]) <= now_utc_epoch:
            return "SERVICE_LEASE_EXPIRED"
        return None

    def get_flow(self, flow_id: str) -> FlowState | None:
        """Read one flow's mutable facts, or ``None`` for an unknown flow."""

        flow_id = _text(flow_id, "flow_id")
        row = self._db.execute("SELECT * FROM flow_state WHERE flow_id = ?", (flow_id,)).fetchone()
        return None if row is None else self._flow(row)

    def get_flow_enabled(self, flow_id: str) -> bool:
        """Return a persisted flow gate; an unknown flow fails closed."""

        state = self.get_flow(flow_id)
        return bool(state is not None and state.enabled)

    def get_run(self, run_id: str) -> RunRecord | None:
        """Read one run's lifecycle and generation fences."""

        row = self._db.execute("SELECT * FROM runs WHERE run_id = ?", (_text(run_id, "run_id"),)).fetchone()
        return None if row is None else self._run(row)

    def get_action(self, action_id: str) -> ActionRecord | None:
        """Read one action's reservation and dispatch state."""

        row = self._db.execute("SELECT * FROM actions WHERE action_id = ?", (_text(action_id, "action_id"),)).fetchone()
        return None if row is None else self._action(row)
    def initialize_flows(self, flow_specs: Iterable[FlowSpec]) -> tuple[FlowState, ...]:
        """Insert missing FlowSpec rows disabled; never overwrite existing rows."""

        specs = tuple(flow_specs)
        seen: set[str] = set()
        for spec in specs:
            if not isinstance(spec, FlowSpec):
                raise TypeError("flow_specs must contain FlowSpec values")
            if spec.flow_id in seen:
                raise ValueError(f"duplicate flow spec: {spec.flow_id}")
            seen.add(spec.flow_id)
        with self._transaction() as db:
            for spec in specs:
                db.execute(
                    """
                    INSERT OR IGNORE INTO flow_state
                        (flow_id, enabled, generation, blocked, blocked_reason, priority,
                         cadence, max_wait_seconds, max_attempts, next_occurrence_key,
                         next_due_at_utc, schedule_anchor_utc, reset_id,
                         retry_not_before_utc, eligible_since_utc, last_started_at_utc,
                         last_completed_at_utc, last_outcome, consecutive_failures, row_version)
                    VALUES (?, 0, 0, 0, NULL, ?, ?, ?, ?, 0, NULL, NULL, NULL,
                            NULL, NULL, NULL, NULL, NULL, 0, 0)
                    """,
                    (spec.flow_id, spec.priority, spec.cadence, spec.max_wait_seconds, spec.max_attempts),
                )
        states: list[FlowState] = []
        for spec in specs:
            state = self.get_flow(spec.flow_id)
            if state is not None:
                states.append(state)
        return tuple(states)

    def set_service_enabled(
        self,
        enabled: bool,
        *,
        emergency_reason: str | None = None,
        now_utc_epoch: float | None = None,
    ) -> ServiceControl:
        """Set the global gate, increment generation, and fence active runs on disable."""

        if type(enabled) is not bool:
            raise ValueError("enabled must be bool")
        now = _epoch(_now() if now_utc_epoch is None else now_utc_epoch, "now", allow_none=False)
        reason = None if enabled else _text(emergency_reason or "emergency stop", "emergency_reason")
        with self._transaction() as db:
            row = db.execute("SELECT generation, row_version FROM service_control WHERE singleton_id = 1").fetchone()
            if row is None:
                raise StateError("service_control row is missing")
            db.execute(
                """
                UPDATE service_control SET enabled = ?, generation = ?, emergency_reason = ?,
                    emergency_at_utc = ?, updated_at_utc = ?, row_version = ?
                WHERE singleton_id = 1
                """,
                (int(enabled), int(row["generation"]) + 1, reason, None if enabled else now, now, int(row["row_version"]) + 1),
            )
            if not enabled:
                db.execute(
                    """UPDATE runs SET state = 'STOP_REQUESTED', stop_requested_at_utc = ?, row_version = row_version + 1
                       WHERE state IN ('CLAIMED', 'RUNNING', 'RECOVERING')""",
                    (now,),
                )
            return self._service(db.execute("SELECT * FROM service_control WHERE singleton_id = 1").fetchone())

    def set_flow_enabled(self, flow_id: str, enabled: bool, *, now_utc_epoch: float | None = None) -> FlowState | None:
        """Set one flow gate, increment its generation, and preserve block facts."""

        flow_id = _text(flow_id, "flow_id")
        if type(enabled) is not bool:
            raise ValueError("enabled must be bool")
        now = _epoch(_now() if now_utc_epoch is None else now_utc_epoch, "now", allow_none=False)
        with self._transaction() as db:
            row = db.execute("SELECT * FROM flow_state WHERE flow_id = ?", (flow_id,)).fetchone()
            if row is None:
                return None
            db.execute(
                """UPDATE flow_state SET enabled = ?, generation = generation + 1, row_version = row_version + 1,
                   eligible_since_utc = CASE WHEN ? = 1 AND eligible_since_utc IS NULL THEN ? ELSE eligible_since_utc END
                   WHERE flow_id = ?""",
                (int(enabled), int(enabled), now, flow_id),
            )
            if not enabled:
                db.execute(
                    """UPDATE runs SET state = 'STOP_REQUESTED', stop_requested_at_utc = ?, row_version = row_version + 1
                       WHERE flow_id = ? AND state IN ('CLAIMED', 'RUNNING', 'RECOVERING')""",
                    (now, flow_id),
                )
            return self._flow(db.execute("SELECT * FROM flow_state WHERE flow_id = ?", (flow_id,)).fetchone())

    def block_flow(self, flow_id: str, reason: str, *, now_utc_epoch: float | None = None) -> FlowState | None:
        """Block a flow without changing enabled or generation state."""

        flow_id = _text(flow_id, "flow_id")
        reason = _text(reason, "reason")
        _epoch(_now() if now_utc_epoch is None else now_utc_epoch, "now", allow_none=False)
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM flow_state WHERE flow_id = ?", (flow_id,)).fetchone() is None:
                return None
            db.execute("UPDATE flow_state SET blocked = 1, blocked_reason = ?, row_version = row_version + 1 WHERE flow_id = ?", (reason, flow_id))
            return self._flow(db.execute("SELECT * FROM flow_state WHERE flow_id = ?", (flow_id,)).fetchone())

    def unblock_flow(self, flow_id: str, *, now_utc_epoch: float | None = None) -> FlowState | None:
        """Unblock a flow without changing enabled or generation state."""

        flow_id = _text(flow_id, "flow_id")
        _epoch(_now() if now_utc_epoch is None else now_utc_epoch, "now", allow_none=False)
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM flow_state WHERE flow_id = ?", (flow_id,)).fetchone() is None:
                return None
            db.execute("UPDATE flow_state SET blocked = 0, blocked_reason = NULL, row_version = row_version + 1 WHERE flow_id = ?", (flow_id,))
            return self._flow(db.execute("SELECT * FROM flow_state WHERE flow_id = ?", (flow_id,)).fetchone())

    def update_schedule(
        self,
        flow_id: str,
        *,
        next_occurrence_key: int | object = _UNSET,
        next_due_at_utc: float | None | object = _UNSET,
        schedule_anchor_utc: float | None | object = _UNSET,
        eligible_since_utc: float | None | object = _UNSET,
        now_utc_epoch: float | None = None,
    ) -> FlowState | None:
        """Update schedule facts without overwriting reset, retry, or gate facts."""

        flow_id = _text(flow_id, "flow_id")
        if next_occurrence_key is not _UNSET:
            _nonnegative_int(next_occurrence_key, "next_occurrence_key")  # type: ignore[arg-type]
        for value, name in ((next_due_at_utc, "next_due_at_utc"), (schedule_anchor_utc, "schedule_anchor_utc"), (eligible_since_utc, "eligible_since_utc")):
            if value is not _UNSET:
                _epoch(value, name)
        _epoch(_now() if now_utc_epoch is None else now_utc_epoch, "now", allow_none=False)
        changes: list[str] = []
        values: list[Any] = []
        for column, value in (("next_occurrence_key", next_occurrence_key), ("next_due_at_utc", next_due_at_utc), ("schedule_anchor_utc", schedule_anchor_utc), ("eligible_since_utc", eligible_since_utc)):
            if value is not _UNSET:
                changes.append(f"{column} = ?")
                values.append(value)
        if not changes:
            return self.get_flow(flow_id)
        values.append(flow_id)
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM flow_state WHERE flow_id = ?", (flow_id,)).fetchone() is None:
                return None
            db.execute(f"UPDATE flow_state SET {', '.join(changes)}, row_version = row_version + 1 WHERE flow_id = ?", values)
            return self._flow(db.execute("SELECT * FROM flow_state WHERE flow_id = ?", (flow_id,)).fetchone())

    def update_reset(
        self,
        flow_id: str,
        reset_id: str,
        *,
        schedule_anchor_utc: float | None | object = _UNSET,
        next_due_at_utc: float | None | object = _UNSET,
        now_utc_epoch: float | None = None,
    ) -> FlowState | None:
        """Persist reset identity and restart its occurrence ordinal when it changes."""

        flow_id, reset_id = _text(flow_id, "flow_id"), _text(reset_id, "reset_id")
        for value, name in ((schedule_anchor_utc, "schedule_anchor_utc"), (next_due_at_utc, "next_due_at_utc")):
            if value is not _UNSET:
                _epoch(value, name)
        now = _epoch(_now() if now_utc_epoch is None else now_utc_epoch, "now", allow_none=False)
        with self._transaction() as db:
            row = db.execute("SELECT * FROM flow_state WHERE flow_id = ?", (flow_id,)).fetchone()
            if row is None:
                return None
            changed = row["reset_id"] != reset_id
            anchor_provided = schedule_anchor_utc is not _UNSET
            due_provided = next_due_at_utc is not _UNSET
            anchor_value = schedule_anchor_utc if anchor_provided else (now if changed else None)
            db.execute(
                """UPDATE flow_state SET reset_id = ?, next_occurrence_key = CASE WHEN ? THEN 0 ELSE next_occurrence_key END,
                   schedule_anchor_utc = CASE WHEN ? THEN ? ELSE schedule_anchor_utc END,
                   next_due_at_utc = CASE WHEN ? THEN ? ELSE next_due_at_utc END,
                   last_accepted_projection_key = CASE WHEN ? THEN NULL ELSE last_accepted_projection_key END,
                   row_version = row_version + 1 WHERE flow_id = ?""",
                (reset_id, int(changed), int(anchor_provided or changed), anchor_value,
                 int(due_provided), next_due_at_utc if due_provided else None,
                 int(changed), flow_id),
            )
            return self._flow(db.execute("SELECT * FROM flow_state WHERE flow_id = ?", (flow_id,)).fetchone())

    def update_retry(
        self,
        flow_id: str,
        *,
        retry_not_before_utc: float | None | object = _UNSET,
        consecutive_failures: int | object = _UNSET,
        last_outcome: str | None | object = _UNSET,
        now_utc_epoch: float | None = None,
    ) -> FlowState | None:
        """Update retry facts independently from schedule due facts."""

        flow_id = _text(flow_id, "flow_id")
        if retry_not_before_utc is not _UNSET:
            _epoch(retry_not_before_utc, "retry_not_before_utc")
        if consecutive_failures is not _UNSET:
            _nonnegative_int(consecutive_failures, "consecutive_failures")  # type: ignore[arg-type]
        if last_outcome is not _UNSET and last_outcome is not None:
            _text(last_outcome, "last_outcome")
        _epoch(_now() if now_utc_epoch is None else now_utc_epoch, "now", allow_none=False)
        changes: list[str] = []
        values: list[Any] = []
        for column, value in (("retry_not_before_utc", retry_not_before_utc), ("consecutive_failures", consecutive_failures), ("last_outcome", last_outcome)):
            if value is not _UNSET:
                changes.append(f"{column} = ?")
                values.append(value)
        if not changes:
            return self.get_flow(flow_id)
        values.append(flow_id)
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM flow_state WHERE flow_id = ?", (flow_id,)).fetchone() is None:
                return None
            db.execute(f"UPDATE flow_state SET {', '.join(changes)}, row_version = row_version + 1 WHERE flow_id = ?", values)
            return self._flow(db.execute("SELECT * FROM flow_state WHERE flow_id = ?", (flow_id,)).fetchone())

    def claim_occurrence(
        self,
        flow_id: str,
        reset_id: str,
        *,
        now_utc_epoch: float | None = None,
        mode: str = "scheduled",
        owner_instance_id: str | None = None,
        process_start_token: str | None = None,
        lease_generation: int | None = None,
        run_token: str | None = None,
        max_inputs: int = 1,
        max_actions: int = 1,
    ) -> RunRecord | None:
        """Atomically claim one due occurrence bound to the current service lease."""

        flow_id, reset_id = _text(flow_id, "flow_id"), _text(reset_id, "reset_id")
        now = _epoch(_now() if now_utc_epoch is None else now_utc_epoch, "now", allow_none=False)
        assert now is not None
        if mode not in {"scheduled", "manual"}:
            raise ValueError("mode must be scheduled or manual")
        implicit_lease = owner_instance_id is None and process_start_token is None and lease_generation is None
        owner = _text(
            self.owner_instance_id if owner_instance_id is None else owner_instance_id,
            "owner_instance_id",
        )
        token = _text(
            self.process_start_token if process_start_token is None else process_start_token,
            "process_start_token",
        )
        _nonnegative_int(max_inputs, "max_inputs")
        _nonnegative_int(max_actions, "max_actions")
        if implicit_lease:
            acquired = self.acquire_service_lease(
                owner_instance_id=owner,
                process_start_token=token,
                process_id=self.process_id,
                now_utc_epoch=now,
            )
            if acquired is None:
                return None
            lease_generation = acquired.lease_generation
        if type(lease_generation) is not int or lease_generation < 1:
            return None
        with self._transaction() as db:
            service = db.execute("SELECT * FROM service_control WHERE singleton_id = 1").fetchone()
            flow = db.execute("SELECT * FROM flow_state WHERE flow_id = ?", (flow_id,)).fetchone()
            if service is None or flow is None or not bool(service["enabled"]):
                return None
            if self._lease_matches(
                db,
                owner_instance_id=owner,
                process_start_token=token,
                lease_generation=lease_generation,
                now_utc_epoch=now,
            ) is not None:
                return None
            if not bool(flow["enabled"]) or bool(flow["blocked"]):
                return None
            if flow["reset_id"] not in (None, reset_id):
                return None
            if flow["next_due_at_utc"] is not None and float(flow["next_due_at_utc"]) > now:
                return None
            if flow["retry_not_before_utc"] is not None and float(flow["retry_not_before_utc"]) > now:
                return None
            if int(flow["consecutive_failures"]) >= int(flow["max_attempts"]):
                return None
            if db.execute("SELECT 1 FROM runs WHERE state IN ('CLAIMED', 'RUNNING', 'STOP_REQUESTED', 'RECOVERING') LIMIT 1").fetchone() is not None:
                return None
            ordinal = int(flow["next_occurrence_key"])
            key = self.occurrence_key(flow_id, reset_id, ordinal)
            existing = db.execute(
                "SELECT * FROM runs WHERE flow_id = ? AND occurrence_key = ?",
                (flow_id, key),
            ).fetchone()
            run_token = _text(
                uuid4().hex if run_token is None else run_token,
                "run_token",
            )
            if existing is not None:
                if existing["state"] not in {RunState.FAILED.value, RunState.BLOCKED.value}:
                    return None
                if db.execute(
                    "SELECT 1 FROM actions WHERE run_id = ? AND state = 'UNKNOWN' LIMIT 1",
                    (existing["run_id"],),
                ).fetchone() is not None:
                    return None
                db.execute(
                    """UPDATE runs SET reset_id = ?, claimed_flow_generation = ?, service_generation = ?,
                       owner_instance_id = ?, process_start_token = ?, lease_generation = ?, run_token = ?,
                       mode = ?, state = 'CLAIMED', claimed_at_utc = ?, started_at_utc = NULL,
                       heartbeat_at_utc = ?, stop_requested_at_utc = NULL, terminal_at_utc = NULL,
                       max_inputs = ?, max_actions = ?, consumed_inputs = 0, consumed_actions = 0,
                       terminal_outcome = NULL, terminal_reason = NULL, row_version = row_version + 1
                       WHERE run_id = ? AND state IN ('FAILED', 'BLOCKED')""",
                    (reset_id, int(flow["generation"]), int(service["generation"]), owner, token,
                     lease_generation, run_token, mode, now, now, max_inputs, max_actions, existing["run_id"]),
                )
                run_id = existing["run_id"]
            else:
                run_id = uuid4().hex
                try:
                    db.execute(
                        """INSERT INTO runs
                           (run_id, flow_id, occurrence_key, reset_id, claimed_flow_generation,
                            service_generation, owner_instance_id, process_start_token, lease_generation,
                            run_token, occurrence_ordinal, mode, state, claimed_at_utc,
                            started_at_utc, heartbeat_at_utc, stop_requested_at_utc, terminal_at_utc,
                            max_inputs, max_actions, consumed_inputs, consumed_actions,
                            terminal_outcome, terminal_reason, row_version)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CLAIMED', ?, NULL, ?, NULL, NULL, ?, ?, 0, 0, NULL, NULL, 0)""",
                        (run_id, flow_id, key, reset_id, int(flow["generation"]), int(service["generation"]),
                         owner, token, lease_generation, run_token, ordinal, mode, now, now, max_inputs, max_actions),
                    )
                except sqlite3.IntegrityError:
                    return None
            db.execute(
                """UPDATE flow_state SET reset_id = ?, last_started_at_utc = ?, eligible_since_utc = NULL,
                   retry_not_before_utc = NULL, row_version = row_version + 1 WHERE flow_id = ?""",
                (reset_id, now, flow_id),
            )
            return self._run(db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone())

    def _project_terminal_db(
        self,
        db: sqlite3.Connection,
        row: sqlite3.Row,
        target: RunState,
        *,
        owner_instance_id: str,
        process_start_token: str,
        run_token: str,
        lease_generation: int,
        expected: RunState | None,
        expected_row_version: int | None,
        outcome: str | None,
        reason: str | None,
        next_due_at_utc: float | None | object,
        retry_not_before_utc: float | None | object,
        accepted_projection_key: str | None | object,
        now: float,
    ) -> RunRecord:
        current = RunState(row["state"])
        if (
            row["owner_instance_id"] != owner_instance_id
            or row["process_start_token"] != process_start_token
            or row["run_token"] != run_token
            or int(row["lease_generation"]) != lease_generation
        ):
            raise TerminalProjectionError("RUN_OWNERSHIP_MISMATCH")
        lease_reason = self._lease_matches(
            db,
            owner_instance_id=owner_instance_id,
            process_start_token=process_start_token,
            lease_generation=lease_generation,
            now_utc_epoch=now,
        )
        if lease_reason is not None:
            raise TerminalProjectionError(lease_reason)
        if (
            current in _TERMINAL_RUN_STATES
            or (expected is not None and current is not expected)
            or expected_row_version is not None and int(row["row_version"]) != expected_row_version
        ):
            raise TerminalProjectionError("TERMINAL_CAS_FAILED")
        allowed = {
            RunState.CLAIMED: {RunState.BLOCKED, RunState.ABANDONED},
            RunState.RUNNING: {RunState.SUCCEEDED, RunState.DEFERRED, RunState.BLOCKED, RunState.FAILED, RunState.ABANDONED},
            RunState.STOP_REQUESTED: {RunState.BLOCKED, RunState.ABANDONED},
            RunState.RECOVERING: {RunState.SUCCEEDED, RunState.DEFERRED, RunState.BLOCKED, RunState.FAILED, RunState.ABANDONED},
        }
        if target not in _TERMINAL_RUN_STATES or target not in allowed.get(current, set()):
            raise TerminalProjectionError("TERMINAL_CAS_FAILED")
        flow = db.execute("SELECT * FROM flow_state WHERE flow_id = ?", (row["flow_id"],)).fetchone()
        service = db.execute("SELECT * FROM service_control WHERE singleton_id = 1").fetchone()
        if flow is None or service is None:
            raise TerminalProjectionError("MISSING_STATE")
        generations_match = (
            int(service["generation"]) == int(row["service_generation"])
            and int(flow["generation"]) == int(row["claimed_flow_generation"])
        )
        safe_fenced_terminal = (
            current is RunState.STOP_REQUESTED
            and target in {RunState.BLOCKED, RunState.ABANDONED}
            and row["stop_requested_at_utc"] is not None
        )
        if not generations_match and not safe_fenced_terminal:
            raise TerminalProjectionError("GENERATION_MISMATCH")
        if next_due_at_utc is not _UNSET:
            _epoch(next_due_at_utc, "next_due_at_utc")
        if retry_not_before_utc is not _UNSET:
            _epoch(retry_not_before_utc, "retry_not_before_utc")
        if accepted_projection_key is not _UNSET and accepted_projection_key is not None:
            _text(accepted_projection_key, "accepted_projection_key")
        flow_outcome = outcome or target.value
        failure = target in {RunState.BLOCKED, RunState.FAILED}
        advance = target in {RunState.SUCCEEDED, RunState.DEFERRED}
        if retry_not_before_utc is _UNSET:
            retry_value: float | None = (
                now + min(3_600.0, float(max(1, 2 ** min(int(flow["consecutive_failures"]) + 1, 10))))
                if failure
                else None
            )
        else:
            retry_value = retry_not_before_utc  # type: ignore[assignment]
        ordinal = int(row["occurrence_ordinal"])
        next_occurrence = (
            int(flow["next_occurrence_key"]) + 1
            if advance
            and row["reset_id"] == flow["reset_id"]
            and int(flow["next_occurrence_key"]) == ordinal
            else int(flow["next_occurrence_key"])
        )
        run_result = db.execute(
            """UPDATE runs SET state = ?, heartbeat_at_utc = ?, terminal_at_utc = ?,
               terminal_outcome = ?, terminal_reason = ?, row_version = row_version + 1
               WHERE run_id = ? AND state = ? AND row_version = ?""",
            (target.value, now, now, outcome, reason, row["run_id"], current.value, int(row["row_version"])),
        )
        if run_result.rowcount != 1:
            raise TerminalProjectionError("TERMINAL_CAS_FAILED")
        flow_result = db.execute(
            """UPDATE flow_state SET next_occurrence_key = ?, next_due_at_utc = CASE WHEN ? THEN ? ELSE next_due_at_utc END,
               retry_not_before_utc = ?, last_completed_at_utc = ?, last_outcome = ?,
               last_accepted_projection_key = CASE WHEN ? THEN ? ELSE last_accepted_projection_key END,
               consecutive_failures = CASE WHEN ? THEN 0 ELSE consecutive_failures + ? END,
               row_version = row_version + 1 WHERE flow_id = ? AND row_version = ?""",
            (
                next_occurrence,
                int(next_due_at_utc is not _UNSET),
                None if next_due_at_utc is _UNSET else next_due_at_utc,
                retry_value,
                now,
                flow_outcome,
                int(accepted_projection_key is not _UNSET and advance),
                None if accepted_projection_key is _UNSET else accepted_projection_key,
                int(advance),
                int(failure),
                row["flow_id"],
                int(flow["row_version"]),
            ),
        )
        if flow_result.rowcount != 1:
            raise TerminalProjectionError("TERMINAL_CAS_FAILED")
        return self._run(db.execute("SELECT * FROM runs WHERE run_id = ?", (row["run_id"],)).fetchone())

    def project_terminal(
        self,
        run_id: str,
        state: RunState | str,
        *,
        owner_instance_id: str,
        process_start_token: str,
        run_token: str,
        lease_generation: int,
        expected_state: RunState | str | None = None,
        expected_row_version: int | None = None,
        reason: str | None = None,
        outcome: str | None = None,
        next_due_at_utc: float | None | object = _UNSET,
        retry_not_before_utc: float | None | object = _UNSET,
        accepted_projection_key: str | None | object = _UNSET,
        now_utc_epoch: float | None = None,
    ) -> RunRecord:
        """Atomically terminalize a run and project schedule/retry facts.

        Ownership, lease, generation, run state, and both row versions are
        compared inside one immediate transaction.  Any failed comparison is
        surfaced as :class:`TerminalProjectionError`, never silently ignored.
        """

        run_id = _text(run_id, "run_id")
        owner = _text(owner_instance_id, "owner_instance_id")
        process_token = _text(process_start_token, "process_start_token")
        token = _text(run_token, "run_token")
        if type(lease_generation) is not int or lease_generation < 1:
            raise TerminalProjectionError("SERVICE_LEASE_REQUIRED")
        try:
            target = RunState(state)
            expected = None if expected_state is None else RunState(expected_state)
        except (TypeError, ValueError) as exc:
            raise StateTransitionError("unknown run state") from exc
        if reason is not None:
            reason = _text(reason, "reason")
        if outcome is not None:
            outcome = _text(outcome, "outcome")
        now = _epoch(_now() if now_utc_epoch is None else now_utc_epoch, "now", allow_none=False)
        assert now is not None
        with self._transaction() as db:
            row = db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                raise TerminalProjectionError("MISSING_STATE")
            return self._project_terminal_db(
                db, row, target, owner_instance_id=owner, process_start_token=process_token,
                run_token=token, lease_generation=lease_generation, expected=expected,
                expected_row_version=expected_row_version, outcome=outcome, reason=reason,
                next_due_at_utc=next_due_at_utc, retry_not_before_utc=retry_not_before_utc,
                accepted_projection_key=accepted_projection_key, now=now,
            )

    def transition_run(
        self,
        run_id: str,
        state: RunState | str,
        *,
        expected_state: RunState | str | None = None,
        reason: str | None = None,
        outcome: str | None = None,
        owner_instance_id: str | None = None,
        process_start_token: str | None = None,
        run_token: str | None = None,
        lease_generation: int | None = None,
        now_utc_epoch: float | None = None,
    ) -> RunRecord | None:
        """Advance a run only with its owner/run/lease token set."""

        run_id = _text(run_id, "run_id")
        try:
            target = RunState(state)
            expected = None if expected_state is None else RunState(expected_state)
        except (TypeError, ValueError) as exc:
            raise StateTransitionError("unknown run state") from exc
        if reason is not None:
            reason = _text(reason, "reason")
        if outcome is not None:
            outcome = _text(outcome, "outcome")
        if owner_instance_id is None or process_start_token is None or run_token is None or type(lease_generation) is not int:
            return None
        owner = _text(owner_instance_id, "owner_instance_id")
        process_token = _text(process_start_token, "process_start_token")
        token = _text(run_token, "run_token")
        now = _epoch(_now() if now_utc_epoch is None else now_utc_epoch, "now", allow_none=False)
        assert now is not None
        if target in _TERMINAL_RUN_STATES:
            try:
                return self.project_terminal(
                    run_id, target, owner_instance_id=owner, process_start_token=process_token,
                    run_token=token, lease_generation=lease_generation, expected_state=expected,
                    reason=reason, outcome=outcome, now_utc_epoch=now,
                )
            except TerminalProjectionError:
                return None
        allowed = {
            RunState.CLAIMED: {RunState.RUNNING, RunState.STOP_REQUESTED, RunState.RECOVERING},
            RunState.RUNNING: {RunState.STOP_REQUESTED, RunState.RECOVERING},
            RunState.STOP_REQUESTED: {RunState.RECOVERING},
            RunState.RECOVERING: {RunState.RUNNING},
        }
        with self._transaction() as db:
            row = db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            current = RunState(row["state"])
            if (
                (expected is not None and current is not expected)
                or current in _TERMINAL_RUN_STATES
                or target not in allowed.get(current, set())
                or row["owner_instance_id"] != owner
                or row["process_start_token"] != process_token
                or row["run_token"] != token
                or int(row["lease_generation"]) != lease_generation
                or self._lease_matches(
                    db,
                    owner_instance_id=owner,
                    process_start_token=process_token,
                    lease_generation=lease_generation,
                    now_utc_epoch=now,
                ) is not None
            ):
                return None
            started = now if target is RunState.RUNNING and row["started_at_utc"] is None else row["started_at_utc"]
            heartbeat = now if target in {RunState.RUNNING, RunState.RECOVERING} else row["heartbeat_at_utc"]
            result = db.execute(
                """UPDATE runs SET state = ?, started_at_utc = ?, heartbeat_at_utc = ?,
                   row_version = row_version + 1 WHERE run_id = ? AND state = ? AND row_version = ?""",
                (target.value, started, heartbeat, run_id, current.value, int(row["row_version"])),
            )
            if result.rowcount != 1:
                return None
            return self._run(db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone())

    def heartbeat_run(
        self,
        run_id: str,
        *,
        owner_instance_id: str | None = None,
        process_start_token: str | None = None,
        run_token: str | None = None,
        lease_generation: int | None = None,
        now_utc_epoch: float | None = None,
    ) -> RunRecord | None:
        """Refresh an active run heartbeat only for its exact owner lease."""

        run_id = _text(run_id, "run_id")
        if owner_instance_id is None or process_start_token is None or run_token is None or type(lease_generation) is not int:
            return None
        owner = _text(owner_instance_id, "owner_instance_id")
        process_token = _text(process_start_token, "process_start_token")
        token = _text(run_token, "run_token")
        now = _epoch(_now() if now_utc_epoch is None else now_utc_epoch, "now", allow_none=False)
        assert now is not None
        with self._transaction() as db:
            row = db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if (
                row is None
                or row["state"] not in _ACTIVE_RUN_STATES
                or row["owner_instance_id"] != owner
                or row["process_start_token"] != process_token
                or row["run_token"] != token
                or int(row["lease_generation"]) != lease_generation
                or self._lease_matches(
                    db,
                    owner_instance_id=owner,
                    process_start_token=process_token,
                    lease_generation=lease_generation,
                    now_utc_epoch=now,
                ) is not None
            ):
                return None
            result = db.execute(
                "UPDATE runs SET heartbeat_at_utc = ?, row_version = row_version + 1 WHERE run_id = ? AND row_version = ?",
                (now, run_id, int(row["row_version"])),
            )
            return None if result.rowcount != 1 else self._run(db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone())
    def reserve_action(
        self,
        run_id: str,
        idempotency_key: str,
        semantic_action_key: str,
        *,
        owner_instance_id: str | None = None,
        process_start_token: str | None = None,
        run_token: str | None = None,
        lease_generation: int | None = None,
        action_id: str | None = None,
        source_capture_id: str | None = None,
        source_frame_hash: str | None = None,
        source_stable_roi_digest: str | None = None,
        source_binding_digest: str | None = None,
        target_identity: str | None = None,
        target_binding_digest: str | None = None,
        action_class: str | None = None,
        quantity: int = 1,
        input_cost: int = 1,
        retry_of_action_id: str | None = None,
        hypothesis_digest: str | None = None,
        now_utc_epoch: float | None = None,
    ) -> ActionRecord | None:
        """Reserve an action only for the owning run and current lease."""

        if owner_instance_id is None or process_start_token is None or run_token is None or type(lease_generation) is not int:
            return None
        run_id = _text(run_id, "run_id")
        idempotency_key = _text(idempotency_key, "idempotency_key")
        semantic_action_key = _text(semantic_action_key, "semantic_action_key")
        owner = _text(owner_instance_id, "owner_instance_id")
        process_token = _text(process_start_token, "process_start_token")
        token = _text(run_token, "run_token")
        if lease_generation < 1:
            return None
        if action_id is not None:
            action_id = _text(action_id, "action_id")
        if action_class is not None:
            action_class = _text(action_class, "action_class")
        for value, name in (
            (source_stable_roi_digest, "source_stable_roi_digest"),
            (source_binding_digest, "source_binding_digest"),
            (target_identity, "target_identity"),
            (target_binding_digest, "target_binding_digest"),
            (retry_of_action_id, "retry_of_action_id"),
            (hypothesis_digest, "hypothesis_digest"),
        ):
            if value is not None:
                _text(value, name)
        binding_fingerprint = _binding_fingerprint(
            source_stable_roi_digest,
            source_binding_digest,
            target_identity,
            target_binding_digest,
        )
        _nonnegative_int(quantity, "quantity")
        _nonnegative_int(input_cost, "input_cost")
        if quantity < 1:
            raise ValueError("quantity must be positive")
        now = _epoch(_now() if now_utc_epoch is None else now_utc_epoch, "now", allow_none=False)
        assert now is not None
        with self._transaction() as db:
            run = db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            service = db.execute("SELECT * FROM service_control WHERE singleton_id = 1").fetchone()
            flow = None if run is None else db.execute("SELECT * FROM flow_state WHERE flow_id = ?", (run["flow_id"],)).fetchone()
            if run is None or service is None or flow is None or run["state"] not in _ACTIVE_RUN_STATES:
                return None
            if (
                run["owner_instance_id"] != owner
                or run["process_start_token"] != process_token
                or run["run_token"] != token
                or int(run["lease_generation"]) != lease_generation
                or self._lease_matches(
                    db,
                    owner_instance_id=owner,
                    process_start_token=process_token,
                    lease_generation=lease_generation,
                    now_utc_epoch=now,
                ) is not None
            ):
                return None
            if not bool(service["enabled"]) or not bool(flow["enabled"]) or bool(flow["blocked"]):
                return None
            if int(service["generation"]) != int(run["service_generation"]) or int(flow["generation"]) != int(run["claimed_flow_generation"]):
                return None
            if retry_of_action_id is not None:
                parent = db.execute(
                    "SELECT action_id, run_id, state, hypothesis_digest FROM actions WHERE action_id = ?",
                    (retry_of_action_id,),
                ).fetchone()
                if (
                    parent is None
                    or parent["run_id"] != run_id
                    or parent["state"] != ActionState.NO_EFFECT.value
                    or hypothesis_digest is None
                    or parent["hypothesis_digest"] == hypothesis_digest
                ):
                    return None
            if binding_fingerprint is not None:
                duplicate = db.execute(
                    """SELECT action_id FROM actions
                       WHERE run_id = ? AND binding_fingerprint = ?
                       ORDER BY sequence_no DESC LIMIT 1""",
                    (run_id, binding_fingerprint),
                ).fetchone()
                if duplicate is not None and duplicate["action_id"] != retry_of_action_id:
                    return None
            if int(run["consumed_inputs"]) + input_cost > int(run["max_inputs"]) or int(run["consumed_actions"]) + 1 > int(run["max_actions"]):
                return None
            if db.execute("SELECT 1 FROM actions WHERE idempotency_key = ?", (idempotency_key,)).fetchone() is not None:
                return None
            sequence = int(db.execute("SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM actions WHERE run_id = ?", (run_id,)).fetchone()[0])
            action_id = action_id or uuid4().hex
            try:
                db.execute(
                    """INSERT INTO actions
                       (action_id, run_id, sequence_no, idempotency_key, semantic_action_key,
                        source_capture_id, source_frame_hash, source_stable_roi_digest,
                        source_binding_digest, target_identity, target_binding_digest,
                        binding_fingerprint, action_class, quantity, input_cost, state,
                        reserved_at_utc, dispatching_at_utc, completed_at_utc, retry_of_action_id,
                        hypothesis_digest, successor_screen, successor_binding_digest, outcome_reason,
                        transport_summary, consequence_summary, row_version)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'RESERVED',
                               ?, NULL, NULL, ?, ?, NULL, NULL, NULL, NULL, NULL, 0)""",
                    (
                        action_id, run_id, sequence, idempotency_key, semantic_action_key,
                        source_capture_id, source_frame_hash, source_stable_roi_digest,
                        source_binding_digest, target_identity, target_binding_digest,
                        binding_fingerprint, action_class, quantity, input_cost, now,
                        retry_of_action_id, hypothesis_digest,
                    ),
                )
            except sqlite3.IntegrityError:
                return None
            db.execute("UPDATE runs SET consumed_inputs = consumed_inputs + ?, consumed_actions = consumed_actions + 1, row_version = row_version + 1 WHERE run_id = ?", (input_cost, run_id))
            return self._action(db.execute("SELECT * FROM actions WHERE action_id = ?", (action_id,)).fetchone())

    def transition_action(
        self,
        action_id: str,
        state: ActionState | str,
        *,
        owner_instance_id: str | None = None,
        process_start_token: str | None = None,
        run_token: str | None = None,
        lease_generation: int | None = None,
        expected_state: ActionState | str | None = None,
        outcome_reason: str | None = None,
        successor_screen: str | None = None,
        successor_binding_digest: str | None = None,
        transport_summary: str | None = None,
        consequence_summary: str | None = None,
        now_utc_epoch: float | None = None,
    ) -> ActionRecord | None:
        """Advance an action only with its owner/run/lease token set."""

        action_id = _text(action_id, "action_id")
        try:
            target = ActionState(state)
            expected = None if expected_state is None else ActionState(expected_state)
        except (TypeError, ValueError) as exc:
            raise StateTransitionError("unknown action state") from exc
        if outcome_reason is not None:
            outcome_reason = _text(outcome_reason, "outcome_reason")
        if owner_instance_id is None or process_start_token is None or run_token is None or type(lease_generation) is not int or lease_generation < 1:
            return None
        owner = _text(owner_instance_id, "owner_instance_id")
        process_token = _text(process_start_token, "process_start_token")
        token = _text(run_token, "run_token")
        now = _epoch(_now() if now_utc_epoch is None else now_utc_epoch, "now", allow_none=False)
        assert now is not None
        allowed = {
            ActionState.RESERVED: {ActionState.CANCELLED, ActionState.DISPATCHING, ActionState.BLOCKED},
            ActionState.DISPATCHING: {ActionState.SUCCEEDED, ActionState.NO_EFFECT, ActionState.UNKNOWN, ActionState.BLOCKED},
            ActionState.UNKNOWN: {ActionState.SUCCEEDED, ActionState.NO_EFFECT, ActionState.BLOCKED},
        }
        with self._transaction() as db:
            row = db.execute("SELECT * FROM actions WHERE action_id = ?", (action_id,)).fetchone()
            if row is None:
                return None
            run = db.execute("SELECT * FROM runs WHERE run_id = ?", (row["run_id"],)).fetchone()
            if run is None:
                return None
            if (
                run["owner_instance_id"] != owner
                or run["process_start_token"] != process_token
                or run["run_token"] != token
                or int(run["lease_generation"]) != lease_generation
                or self._lease_matches(
                    db,
                    owner_instance_id=owner,
                    process_start_token=process_token,
                    lease_generation=lease_generation,
                    now_utc_epoch=now,
                ) is not None
            ):
                return None
            current = ActionState(row["state"])
            if (expected is not None and current is not expected) or current in _TERMINAL_ACTION_STATES or target not in allowed.get(current, set()):
                return None
            # Once an action is DISPATCHING (or already UNKNOWN), a generic
            # terminal transition may be reconciling an external effect.  It
            # must not be used to relabel an action after the service/flow
            # fence has stopped it; only the explicit pre-transport abort
            # below may cross that boundary.
            if current in {ActionState.DISPATCHING, ActionState.UNKNOWN} and target in _TERMINAL_ACTION_STATES:
                service = db.execute("SELECT * FROM service_control WHERE singleton_id = 1").fetchone()
                flow = db.execute("SELECT * FROM flow_state WHERE flow_id = ?", (run["flow_id"],)).fetchone()
                if (
                    service is None
                    or flow is None
                    or not bool(service["enabled"])
                    or int(service["generation"]) != int(run["service_generation"])
                    or not bool(flow["enabled"])
                    or bool(flow["blocked"])
                    or int(flow["generation"]) != int(run["claimed_flow_generation"])
                    or run["state"] == RunState.STOP_REQUESTED.value
                ):
                    return None
            # Keep the fence check and RESERVED -> DISPATCHING mutation in the
            # same transaction: no transport-capable transition may race a
            # service/flow/run generation or lease change.
            if target is ActionState.DISPATCHING and not self._validate_db(
                db,
                row["run_id"],
                owner_instance_id=owner,
                process_start_token=process_token,
                run_token=token,
                lease_generation=lease_generation,
                now_utc_epoch=now,
            ).valid:
                return None
            # RESERVED means no transport occurred.  Refund both budgets when
            # it is cancelled or blocked; DISPATCHING/UNKNOWN are never refunded.
            if current is ActionState.RESERVED and target in {ActionState.CANCELLED, ActionState.BLOCKED}:
                db.execute(
                    "UPDATE runs SET consumed_inputs = MAX(0, consumed_inputs - ?), consumed_actions = MAX(0, consumed_actions - 1), row_version = row_version + 1 WHERE run_id = ?",
                    (int(row["input_cost"]), row["run_id"]),
                )
            result = db.execute(
                """UPDATE actions SET state = ?, dispatching_at_utc = CASE WHEN ? THEN ? ELSE dispatching_at_utc END,
                   completed_at_utc = CASE WHEN ? THEN ? ELSE completed_at_utc END,
                   successor_screen = COALESCE(?, successor_screen), successor_binding_digest = COALESCE(?, successor_binding_digest),
                   outcome_reason = COALESCE(?, outcome_reason), transport_summary = COALESCE(?, transport_summary),
                   consequence_summary = COALESCE(?, consequence_summary), row_version = row_version + 1
                   WHERE action_id = ? AND state = ? AND row_version = ?""",
                (
                    target.value,
                    int(target is ActionState.DISPATCHING),
                    now,
                    int(target in _TERMINAL_ACTION_STATES),
                    now,
                    successor_screen,
                    successor_binding_digest,
                    outcome_reason,
                    transport_summary,
                    consequence_summary,
                    action_id,
                    current.value,
                    int(row["row_version"]),
                ),
            )
            if result.rowcount != 1:
                return None
            return self._action(db.execute("SELECT * FROM actions WHERE action_id = ?", (action_id,)).fetchone())
    def abort_pretransport_action(
        self,
        action_id: str,
        state: ActionState | str = ActionState.BLOCKED,
        *,
        owner_instance_id: str | None = None,
        process_start_token: str | None = None,
        run_token: str | None = None,
        lease_generation: int | None = None,
        expected_state: ActionState | str = ActionState.DISPATCHING,
        transport_attempted: bool | None = None,
        outcome_reason: str | None = None,
        transport_summary: str | None = None,
        consequence_summary: str | None = None,
        now_utc_epoch: float | None = None,
    ) -> ActionRecord | None:
        """Abort a committed action only while transport is proven uncalled.

        This is deliberately separate from :meth:`transition_action`.  A
        DISPATCHING action normally carries external-effect uncertainty and
        cannot be refunded or relabeled after a service stop.  The executor
        calls this operation before entering its transport boundary and passes
        ``transport_attempted=False`` as its control-flow proof.
        """

        action_id = _text(action_id, "action_id")
        try:
            target = ActionState(state)
            expected = ActionState(expected_state)
        except (TypeError, ValueError) as exc:
            raise StateTransitionError("unknown pre-transport action state") from exc
        if target not in {ActionState.BLOCKED, ActionState.CANCELLED} or expected is not ActionState.DISPATCHING:
            return None
        # False must be supplied explicitly by the executor; an omitted proof
        # or a truthy value is never accepted as a no-transport assertion.
        if transport_attempted is not False:
            return None
        if outcome_reason is not None:
            outcome_reason = _text(outcome_reason, "outcome_reason")
        if owner_instance_id is None or process_start_token is None or run_token is None or type(lease_generation) is not int or lease_generation < 1:
            return None
        owner = _text(owner_instance_id, "owner_instance_id")
        process_token = _text(process_start_token, "process_start_token")
        token = _text(run_token, "run_token")
        now = _epoch(_now() if now_utc_epoch is None else now_utc_epoch, "now", allow_none=False)
        assert now is not None
        with self._transaction() as db:
            row = db.execute("SELECT * FROM actions WHERE action_id = ?", (action_id,)).fetchone()
            if row is None:
                return None
            run = db.execute("SELECT * FROM runs WHERE run_id = ?", (row["run_id"],)).fetchone()
            if (
                run is None
                or run["state"] not in _ACTIVE_RUN_STATES
                or run["owner_instance_id"] != owner
                or run["process_start_token"] != process_token
                or run["run_token"] != token
                or int(run["lease_generation"]) != lease_generation
                or self._lease_matches(
                    db,
                    owner_instance_id=owner,
                    process_start_token=process_token,
                    lease_generation=lease_generation,
                    now_utc_epoch=now,
                ) is not None
                or ActionState(row["state"]) is not ActionState.DISPATCHING
            ):
                return None
            result = db.execute(
                """UPDATE actions SET state = ?, completed_at_utc = ?,
                   outcome_reason = COALESCE(?, outcome_reason),
                   transport_summary = COALESCE(?, transport_summary),
                   consequence_summary = COALESCE(?, consequence_summary),
                   row_version = row_version + 1
                   WHERE action_id = ? AND state = ? AND row_version = ?""",
                (
                    target.value,
                    now,
                    outcome_reason,
                    transport_summary,
                    consequence_summary,
                    action_id,
                    ActionState.DISPATCHING.value,
                    int(row["row_version"]),
                ),
            )
            if result.rowcount != 1:
                return None
            db.execute(
                "UPDATE runs SET consumed_inputs = MAX(0, consumed_inputs - ?), consumed_actions = MAX(0, consumed_actions - 1), row_version = row_version + 1 WHERE run_id = ?",
                (int(row["input_cost"]), row["run_id"]),
            )
            return self._action(db.execute("SELECT * FROM actions WHERE action_id = ?", (action_id,)).fetchone())


    def _validate_db(
        self,
        db: sqlite3.Connection,
        run_id: str,
        action_id: str | None = None,
        *,
        owner_instance_id: str | None = None,
        process_start_token: str | None = None,
        run_token: str | None = None,
        lease_generation: int | None = None,
        now_utc_epoch: float | None = None,
    ) -> DispatchValidation:
        service = db.execute("SELECT * FROM service_control WHERE singleton_id = 1").fetchone()
        run = db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if service is None or run is None:
            return DispatchValidation(False, "MISSING_STATE")
        flow = db.execute("SELECT * FROM flow_state WHERE flow_id = ?", (run["flow_id"],)).fetchone()
        if flow is None:
            return DispatchValidation(False, "MISSING_FLOW")
        state = RunState(run["state"])
        base = (int(service["generation"]), int(flow["generation"]), state)
        if owner_instance_id is None and process_start_token is None and run_token is None and lease_generation is None:
            # Validation is read-only; preserving ID-only inspection is safe,
            # while every transport-capable mutation still requires tokens.
            owner_instance_id = run["owner_instance_id"]
            process_start_token = run["process_start_token"]
            run_token = run["run_token"]
            lease_generation = int(run["lease_generation"])
        elif owner_instance_id is None or process_start_token is None or run_token is None or type(lease_generation) is not int:
            return DispatchValidation(False, "SERVICE_LEASE_REQUIRED", *base)
        if (
            run["owner_instance_id"] != owner_instance_id
            or run["process_start_token"] != process_start_token
            or run["run_token"] != run_token
            or int(run["lease_generation"]) != lease_generation
        ):
            return DispatchValidation(False, "RUN_OWNERSHIP_MISMATCH", *base)
        now = _now() if now_utc_epoch is None else now_utc_epoch
        lease_reason = self._lease_matches(
            db,
            owner_instance_id=owner_instance_id,
            process_start_token=process_start_token,
            lease_generation=lease_generation,
            now_utc_epoch=float(now),
        )
        if lease_reason is not None:
            return DispatchValidation(False, lease_reason, *base)
        if not bool(service["enabled"]):
            return DispatchValidation(False, "SERVICE_DISABLED", *base)
        if not bool(flow["enabled"]) or bool(flow["blocked"]):
            return DispatchValidation(False, "FLOW_DISABLED_OR_BLOCKED", *base)
        if state not in {RunState.CLAIMED, RunState.RUNNING, RunState.RECOVERING}:
            return DispatchValidation(False, "RUN_NOT_ACTIVE", *base)
        if int(service["generation"]) != int(run["service_generation"]):
            return DispatchValidation(False, "SERVICE_GENERATION_MISMATCH", *base)
        if int(flow["generation"]) != int(run["claimed_flow_generation"]):
            return DispatchValidation(False, "FLOW_GENERATION_MISMATCH", *base)
        if action_id is not None:
            action = db.execute("SELECT state FROM actions WHERE action_id = ? AND run_id = ?", (action_id, run_id)).fetchone()
            if action is None or action["state"] != ActionState.DISPATCHING.value:
                return DispatchValidation(False, "ACTION_NOT_DISPATCHING", *base)
        return DispatchValidation(True, "OK", *base)

    def validate_dispatch(
        self,
        run_id: str,
        *,
        owner_instance_id: str | None = None,
        process_start_token: str | None = None,
        run_token: str | None = None,
        lease_generation: int | None = None,
        action_id: str | None = None,
        now_utc_epoch: float | None = None,
    ) -> DispatchValidation:
        """Atomically validate service/flow/run/lease generations before dispatch."""

        run_id = _text(run_id, "run_id")
        with self._transaction() as db:
            return self._validate_db(
                db,
                run_id,
                action_id,
                owner_instance_id=owner_instance_id,
                process_start_token=process_start_token,
                run_token=run_token,
                lease_generation=lease_generation,
                now_utc_epoch=now_utc_epoch,
            )

    def list_orphan_runs(self, *, now_utc_epoch: float | None = None, heartbeat_timeout_seconds: float = 60.0) -> tuple[RunRecord, ...]:
        """List active runs whose heartbeat is older than the timeout."""

        now = _epoch(_now() if now_utc_epoch is None else now_utc_epoch, "now", allow_none=False)
        timeout = _epoch(heartbeat_timeout_seconds, "heartbeat_timeout_seconds", allow_none=False)
        if timeout is None:
            raise ValueError("heartbeat_timeout_seconds is required")
        rows = self._db.execute(
            """SELECT * FROM runs WHERE state IN ('CLAIMED', 'RUNNING', 'STOP_REQUESTED', 'RECOVERING')
               AND (heartbeat_at_utc IS NULL OR heartbeat_at_utc < ?) ORDER BY claimed_at_utc, run_id""",
            (now - timeout,),
        ).fetchall()
        return tuple(self._run(row) for row in rows)

    def recover_orphan(
        self,
        run_id: str,
        *,
        now_utc_epoch: float | None = None,
        heartbeat_timeout_seconds: float = 60.0,
    ) -> RunRecord | None:
        """Classify stale reservations and dispatches; orphaned dispatch is never replayed."""

        run_id = _text(run_id, "run_id")
        now = _epoch(_now() if now_utc_epoch is None else now_utc_epoch, "now", allow_none=False)
        timeout = _epoch(heartbeat_timeout_seconds, "heartbeat_timeout_seconds", allow_none=False)
        if timeout is None:
            raise ValueError("heartbeat_timeout_seconds is required")
        assert now is not None
        with self._transaction() as db:
            run = db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if run is None or run["state"] not in _ACTIVE_RUN_STATES or (
                run["heartbeat_at_utc"] is not None and float(run["heartbeat_at_utc"]) >= now - timeout
            ):
                return None
            has_dispatch = db.execute(
                "SELECT 1 FROM actions WHERE run_id = ? AND state = 'DISPATCHING' LIMIT 1", (run_id,)
            ).fetchone() is not None
            reserved_budget = db.execute(
                """SELECT COALESCE(SUM(input_cost), 0) AS input_cost, COUNT(*) AS action_count
                   FROM actions WHERE run_id = ? AND state = 'RESERVED'""",
                (run_id,),
            ).fetchone()
            db.execute(
                "UPDATE runs SET consumed_inputs = MAX(0, consumed_inputs - ?), consumed_actions = MAX(0, consumed_actions - ?), row_version = row_version + 1 WHERE run_id = ?",
                (int(reserved_budget["input_cost"]), int(reserved_budget["action_count"]), run_id),
            )
            db.execute(
                "UPDATE actions SET state = 'UNKNOWN', completed_at_utc = ?, outcome_reason = COALESCE(outcome_reason, 'ORPHANED_DISPATCH'), row_version = row_version + 1 WHERE run_id = ? AND state = 'DISPATCHING'",
                (now, run_id),
            )
            db.execute(
                "UPDATE actions SET state = 'CANCELLED', completed_at_utc = ?, outcome_reason = COALESCE(outcome_reason, 'ORPHANED_RESERVATION'), row_version = row_version + 1 WHERE run_id = ? AND state = 'RESERVED'",
                (now, run_id),
            )
            # A stale reservation has not crossed the transport boundary and
            # may be retried.  A stale dispatch may have reached the adapter;
            # it is terminally blocked for reconciliation and is never replayed.
            target = RunState.BLOCKED if has_dispatch else RunState.FAILED
            db.execute(
                "UPDATE runs SET state = ?, terminal_at_utc = ?, terminal_reason = ?, heartbeat_at_utc = ?, row_version = row_version + 1 WHERE run_id = ?",
                (target.value, now, "ORPHANED_DISPATCH" if has_dispatch else "ORPHANED", now, run_id),
            )
            return self._run(db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone())

    def recover_orphans(
        self,
        *,
        now_utc_epoch: float | None = None,
        heartbeat_timeout_seconds: float = 60.0,
    ) -> tuple[RunRecord, ...]:
        """Recover all stale active runs in deterministic claim order."""

        now = _now() if now_utc_epoch is None else now_utc_epoch
        candidates = self.list_orphan_runs(now_utc_epoch=now, heartbeat_timeout_seconds=heartbeat_timeout_seconds)
        recovered: list[RunRecord] = []
        for candidate in candidates:
            result = self.recover_orphan(candidate.run_id, now_utc_epoch=now, heartbeat_timeout_seconds=heartbeat_timeout_seconds)
            if result is not None:
                recovered.append(result)
        return tuple(recovered)


__all__ = [
    "ActionRecord",
    "ActionState",
    "BotStateManager",
    "ClockObservation",
    "DispatchValidation",
    "FlowState",
    "RunRecord",
    "RunState",
    "ServiceControl",
    "ServiceLease",
    "StateError",
    "StateTransitionError",
    "TerminalProjectionError",
]
