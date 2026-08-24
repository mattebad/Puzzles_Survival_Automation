"""Versioned SQLite journal, append-only audit log, and controller lease."""

from __future__ import annotations

import json
import hashlib
import math
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional

from .models import ActionIntent, ActionStatus, PolicyResult, snapshot

CURRENT_SCHEMA_VERSION = 4
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
        "reconciliation_required",
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


RESOURCE_ATTEMPT_STATUSES = frozenset(
    {"CLAIMED", "DENIED", "ABANDONED", "COMPLETED", "NO_EFFECT", "UNRESOLVED", "RECONCILING"}
)
RESOURCE_RESERVATION_STATUSES = frozenset(
    {
        "RESERVED",
        "DISPATCHING",
        "RELEASED_NOT_SENT",
        "SENT_ACKNOWLEDGED",
        "TRANSPORT_UNKNOWN",
        "EFFECT_CONFIRMED",
        "NO_EFFECT_CONFIRMED",
        "UNRESOLVED",
        "CLOSED",
    }
)
RESOURCE_TRANSPORT_STATUSES = frozenset(
    {"INTENT_RECORDED", "NOT_SENT", "SENT_ACKNOWLEDGED", "TRANSPORT_UNKNOWN"}
)

_RESOURCE_V4_DDL = (
    """
    CREATE TABLE IF NOT EXISTS resource_reset_identities (
        reset_identity_id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL,
        server_id TEXT NOT NULL,
        runtime_scope TEXT NOT NULL,
        reset_start_utc TEXT NOT NULL,
        reset_deadline_utc TEXT NOT NULL,
        assurance TEXT NOT NULL,
        observed_at REAL NOT NULL,
        expires_at REAL,
        evidence_refs_json TEXT NOT NULL,
        content_digest TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS resource_reset_identity_scope_idx
    ON resource_reset_identities(account_id, server_id, reset_identity_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_occurrences (
        occurrence_id TEXT PRIMARY KEY,
        occurrence_key TEXT NOT NULL UNIQUE,
        account_id TEXT NOT NULL,
        server_id TEXT NOT NULL,
        flow_id TEXT NOT NULL,
        recurrence_class TEXT NOT NULL CHECK (recurrence_class = 'daily_reset'),
        recurrence_epoch TEXT NOT NULL,
        objective_action_id TEXT NOT NULL CHECK (objective_action_id = 'use_resource_item'),
        target_variant TEXT NOT NULL CHECK (target_variant = '1k_food'),
        effect_ordinal INTEGER NOT NULL CHECK (effect_ordinal = 1),
        quantity INTEGER NOT NULL CHECK (quantity = 1),
        product_policy_revision TEXT NOT NULL,
        recurrence_policy_revision TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('ELIGIBLE','RESERVED','COMPLETED','NO_EFFECT','UNRESOLVED','BLOCKED')),
        state_revision INTEGER NOT NULL CHECK (state_revision >= 0),
        reset_identity_id TEXT NOT NULL,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        content_digest TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL,
        UNIQUE (account_id, server_id, recurrence_epoch, objective_action_id, target_variant, effect_ordinal),
        FOREIGN KEY (account_id, server_id, recurrence_epoch)
            REFERENCES resource_reset_identities(account_id, server_id, reset_identity_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_attempts (
        attempt_id TEXT PRIMARY KEY,
        occurrence_id TEXT NOT NULL,
        attempt_generation INTEGER NOT NULL CHECK (attempt_generation >= 1),
        state TEXT NOT NULL CHECK (state IN ('CLAIMED','DENIED','ABANDONED','COMPLETED','NO_EFFECT','UNRESOLVED','RECONCILING')),
        hypothesis_digest TEXT NOT NULL,
        owner_id TEXT,
        state_revision INTEGER NOT NULL CHECK (state_revision >= 0),
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        content_digest TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL,
        UNIQUE (occurrence_id, attempt_generation),
        FOREIGN KEY (occurrence_id) REFERENCES resource_occurrences(occurrence_id)
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS resource_attempt_identity_idx
    ON resource_attempts(attempt_id, occurrence_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_attempt_claims (
        claim_id TEXT PRIMARY KEY,
        attempt_id TEXT NOT NULL,
        occurrence_id TEXT NOT NULL,
        owner_id TEXT NOT NULL,
        claim_token_digest TEXT NOT NULL,
        claim_epoch INTEGER NOT NULL CHECK (claim_epoch >= 1),
        acquired_at REAL NOT NULL,
        expires_at REAL NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('ACTIVE','EXPIRED','RELEASED','RECONCILIATION_ONLY')),
        reservation_id TEXT,
        content_digest TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL,
        UNIQUE (attempt_id, claim_epoch),
        FOREIGN KEY (attempt_id, occurrence_id)
            REFERENCES resource_attempts(attempt_id, occurrence_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_historical_transport_facts (
        transport_fact_id TEXT PRIMARY KEY,
        historical_session_id TEXT NOT NULL,
        action_key TEXT NOT NULL,
        transport_at_utc TEXT,
        source_frame_sha256 TEXT,
        transport_result_json TEXT NOT NULL,
        unknown_fields_json TEXT NOT NULL,
        evidence_refs_json TEXT NOT NULL,
        content_digest TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_historical_effects (
        historical_effect_id TEXT PRIMARY KEY,
        transport_fact_id TEXT NOT NULL,
        historical_session_id TEXT NOT NULL,
        occurrence_id TEXT NOT NULL,
        effect_kind TEXT NOT NULL CHECK (effect_kind = 'historical'),
        effect_ordinal INTEGER NOT NULL CHECK (effect_ordinal = 1),
        before_owned_quantity INTEGER,
        after_owned_quantity INTEGER,
        before_resource_quantity INTEGER,
        after_resource_quantity INTEGER,
        effect_state TEXT NOT NULL CHECK (effect_state IN ('CONFIRMED','UNRESOLVED')),
        account_id TEXT,
        server_id TEXT,
        reset_identity_id TEXT,
        unknown_fields_json TEXT NOT NULL,
        content_digest TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL,
        UNIQUE (transport_fact_id, effect_ordinal),
        FOREIGN KEY (transport_fact_id) REFERENCES resource_historical_transport_facts(transport_fact_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_historical_classifications (
        classification_id TEXT PRIMARY KEY,
        historical_effect_id TEXT NOT NULL,
        classification_code TEXT NOT NULL CHECK (classification_code = 'SUSPECTED_SAME_CYCLE_DUPLICATE'),
        scope_key TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        content_digest TEXT NOT NULL UNIQUE,
        UNIQUE (historical_effect_id, classification_code),
        FOREIGN KEY (historical_effect_id) REFERENCES resource_historical_effects(historical_effect_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_reset_binding_assertions (
        assertion_id TEXT PRIMARY KEY,
        effect_kind TEXT NOT NULL CHECK (effect_kind IN ('historical','live')),
        effect_id TEXT NOT NULL,
        account_id TEXT,
        server_id TEXT,
        reset_identity_id TEXT,
        assertion_state TEXT NOT NULL CHECK (assertion_state IN ('UNRESOLVED','BOUND','CONFLICT')),
        evidence_refs_json TEXT NOT NULL,
        unknown_fields_json TEXT NOT NULL,
        content_digest TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL,
        UNIQUE (assertion_id, effect_kind, effect_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_reset_binding_projection (
        effect_kind TEXT NOT NULL CHECK (effect_kind IN ('historical','live')),
        effect_id TEXT NOT NULL,
        assertion_id TEXT NOT NULL,
        account_id TEXT,
        server_id TEXT,
        reset_identity_id TEXT,
        projection_state TEXT NOT NULL CHECK (projection_state IN ('UNRESOLVED','BOUND','CONFLICT')),
        state_revision INTEGER NOT NULL CHECK (state_revision >= 0),
        updated_at REAL NOT NULL,
        PRIMARY KEY (effect_kind, effect_id),
        FOREIGN KEY (assertion_id, effect_kind, effect_id)
            REFERENCES resource_reset_binding_assertions(assertion_id, effect_kind, effect_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_reservations (
        reservation_id TEXT PRIMARY KEY,
        occurrence_id TEXT NOT NULL,
        attempt_id TEXT NOT NULL,
        action_id TEXT NOT NULL UNIQUE,
        effect_ordinal INTEGER NOT NULL CHECK (effect_ordinal = 1),
        authorization_generation INTEGER NOT NULL CHECK (authorization_generation >= 1),
        state TEXT NOT NULL CHECK (state IN ('RESERVED','DISPATCHING','RELEASED_NOT_SENT','SENT_ACKNOWLEDGED','TRANSPORT_UNKNOWN','RECONCILING','EFFECT_CONFIRMED','NO_EFFECT_CONFIRMED','UNRESOLVED','CLOSED')),
        state_revision INTEGER NOT NULL CHECK (state_revision >= 0),
        account_id TEXT NOT NULL,
        server_id TEXT NOT NULL,
        reset_identity_id TEXT NOT NULL,
        product_policy_revision TEXT NOT NULL,
        recurrence_policy_revision TEXT NOT NULL,
        authorization_context_digest TEXT NOT NULL,
        claim_token_digest TEXT NOT NULL,
        claim_epoch INTEGER NOT NULL CHECK (claim_epoch >= 1),
        controller_token_digest TEXT NOT NULL,
        controller_generation INTEGER NOT NULL CHECK (controller_generation >= 1),
        runtime_invocation_id TEXT NOT NULL,
        immediate_before_sha256 TEXT NOT NULL,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        content_digest TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL,
        UNIQUE (occurrence_id, effect_ordinal, authorization_generation),
        FOREIGN KEY (occurrence_id) REFERENCES resource_occurrences(occurrence_id),
        FOREIGN KEY (attempt_id, occurrence_id)
            REFERENCES resource_attempts(attempt_id, occurrence_id),
        FOREIGN KEY (action_id) REFERENCES actions(action_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_transport_facts (
        transport_fact_id TEXT PRIMARY KEY,
        reservation_id TEXT NOT NULL UNIQUE,
        occurrence_id TEXT NOT NULL,
        attempt_id TEXT NOT NULL,
        account_id TEXT NOT NULL,
        server_id TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('INTENT_RECORDED','NOT_SENT','SENT_ACKNOWLEDGED','TRANSPORT_UNKNOWN')),
        runtime_invocation_id TEXT NOT NULL,
        adapter_invoked INTEGER NOT NULL CHECK (adapter_invoked IN (0,1)),
        transport_result_json TEXT,
        recorded_at REAL NOT NULL,
        content_digest TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL,
        UNIQUE (transport_fact_id, reservation_id, occurrence_id, attempt_id),
        FOREIGN KEY (reservation_id) REFERENCES resource_reservations(reservation_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_transport_outcomes (
        outcome_id TEXT PRIMARY KEY,
        transport_fact_id TEXT NOT NULL UNIQUE,
        reservation_id TEXT NOT NULL UNIQUE,
        occurrence_id TEXT NOT NULL,
        attempt_id TEXT NOT NULL,
        account_id TEXT NOT NULL,
        server_id TEXT NOT NULL,
        runtime_invocation_id TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('NOT_SENT','SENT_ACKNOWLEDGED','TRANSPORT_UNKNOWN')),
        adapter_invoked INTEGER NOT NULL CHECK (adapter_invoked IN (0,1)),
        result_json TEXT NOT NULL,
        result_digest TEXT NOT NULL,
        recorded_at REAL NOT NULL,
        content_digest TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL,
        UNIQUE (outcome_id, transport_fact_id, reservation_id, occurrence_id, attempt_id),
        FOREIGN KEY (transport_fact_id, reservation_id, occurrence_id, attempt_id)
            REFERENCES resource_transport_facts(transport_fact_id, reservation_id, occurrence_id, attempt_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_live_effects (
        live_effect_id TEXT PRIMARY KEY,
        reservation_id TEXT NOT NULL,
        transport_fact_id TEXT NOT NULL,
        occurrence_id TEXT NOT NULL,
        attempt_id TEXT NOT NULL,
        account_id TEXT NOT NULL,
        server_id TEXT NOT NULL,
        effect_ordinal INTEGER NOT NULL CHECK (effect_ordinal = 1),
        effect_state TEXT NOT NULL CHECK (effect_state IN ('CONFIRMED','NO_EFFECT','UNRESOLVED')),
        before_owned_quantity INTEGER,
        after_owned_quantity INTEGER,
        evidence_refs_json TEXT NOT NULL,
        created_at REAL NOT NULL,
        content_digest TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL,
        FOREIGN KEY (reservation_id) REFERENCES resource_reservations(reservation_id),
        FOREIGN KEY (transport_fact_id, reservation_id, occurrence_id, attempt_id)
            REFERENCES resource_transport_facts(transport_fact_id, reservation_id, occurrence_id, attempt_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_effect_block_facts (
        block_id TEXT PRIMARY KEY,
        scope_key TEXT NOT NULL UNIQUE,
        account_id TEXT,
        server_id TEXT,
        reset_identity_id TEXT,
        occurrence_key TEXT,
        block_reason TEXT NOT NULL,
        active INTEGER NOT NULL CHECK (active IN (0,1)),
        content_digest TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_effect_block_resolutions (
        resolution_id TEXT PRIMARY KEY,
        block_id TEXT NOT NULL,
        decision TEXT NOT NULL CHECK (decision IN ('KEEP_ACTIVE','CLEAR_FOR_PROVEN_LATER_RESET','SUPERSEDE_SCOPE','CONFLICT')),
        authoritative_evidence_json TEXT NOT NULL,
        current_reset_id TEXT,
        supersedes_resolution_id TEXT,
        content_digest TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL,
        FOREIGN KEY (block_id) REFERENCES resource_effect_block_facts(block_id),
        FOREIGN KEY (supersedes_resolution_id) REFERENCES resource_effect_block_resolutions(resolution_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_effect_block_projection (
        block_id TEXT PRIMARY KEY,
        scope_key TEXT NOT NULL UNIQUE,
        projection_state TEXT NOT NULL CHECK (projection_state IN ('ACTIVE','CLEARED','CONFLICT')),
        current_reset_id TEXT,
        source_resolution_id TEXT,
        state_revision INTEGER NOT NULL CHECK (state_revision >= 0),
        updated_at REAL NOT NULL,
        FOREIGN KEY (block_id) REFERENCES resource_effect_block_facts(block_id),
        FOREIGN KEY (source_resolution_id) REFERENCES resource_effect_block_resolutions(resolution_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_terminal_observations (
        observation_id TEXT PRIMARY KEY,
        occurrence_id TEXT NOT NULL,
        terminal_state TEXT NOT NULL CHECK (terminal_state IN ('HOME_CANONICAL','HOME_READY','UNKNOWN','MANUAL_REQUIRED')),
        frame_sha256 TEXT,
        evidence_refs_json TEXT NOT NULL,
        content_digest TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL,
        UNIQUE (observation_id, occurrence_id),
        FOREIGN KEY (occurrence_id) REFERENCES resource_occurrences(occurrence_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_terminal_projection (
        occurrence_id TEXT PRIMARY KEY,
        observation_id TEXT NOT NULL,
        terminal_state TEXT NOT NULL CHECK (terminal_state IN ('HOME_CANONICAL','HOME_READY','UNKNOWN','MANUAL_REQUIRED')),
        state_revision INTEGER NOT NULL CHECK (state_revision >= 0),
        updated_at REAL NOT NULL,
        FOREIGN KEY (observation_id, occurrence_id)
            REFERENCES resource_terminal_observations(observation_id, occurrence_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_transition_history (
        transition_id TEXT PRIMARY KEY,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        state_from TEXT,
        state_to TEXT NOT NULL,
        state_revision INTEGER NOT NULL CHECK (state_revision >= 0),
        recorded_at REAL NOT NULL,
        payload_json TEXT NOT NULL,
        content_digest TEXT NOT NULL UNIQUE,
        UNIQUE (entity_type, entity_id, state_revision)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_closures (
        closure_id TEXT PRIMARY KEY,
        reservation_id TEXT NOT NULL,
        occurrence_id TEXT NOT NULL,
        attempt_id TEXT NOT NULL,
        closure_kind TEXT NOT NULL CHECK (closure_kind IN ('RELEASED_NOT_SENT','NO_EFFECT_CONFIRMED','EFFECT_CONFIRMED','UNRESOLVED')),
        reason TEXT NOT NULL,
        content_digest TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL,
        FOREIGN KEY (reservation_id) REFERENCES resource_reservations(reservation_id)
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS resource_reservation_active_effect_idx
    ON resource_reservations(occurrence_id, effect_ordinal)
    WHERE state IN ('RESERVED','DISPATCHING','SENT_ACKNOWLEDGED','TRANSPORT_UNKNOWN','RECONCILING','EFFECT_CONFIRMED','UNRESOLVED')
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS resource_confirmed_effect_idx
    ON resource_live_effects(occurrence_id, effect_ordinal)
    WHERE effect_state = 'CONFIRMED'
    """,
    """
    CREATE TRIGGER IF NOT EXISTS resource_reset_projection_insert_guard
    BEFORE INSERT ON resource_reset_binding_projection
    BEGIN
        SELECT CASE WHEN NOT EXISTS (
            SELECT 1
            FROM resource_reset_binding_assertions a
            WHERE a.assertion_id = NEW.assertion_id
              AND a.effect_kind = NEW.effect_kind
              AND a.effect_id = NEW.effect_id
              AND a.assertion_state = NEW.projection_state
              AND COALESCE(a.account_id, '') = COALESCE(NEW.account_id, '')
              AND COALESCE(a.server_id, '') = COALESCE(NEW.server_id, '')
              AND COALESCE(a.reset_identity_id, '') = COALESCE(NEW.reset_identity_id, '')
        ) THEN RAISE(ABORT, 'reset projection does not match assertion') END;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS resource_reset_projection_update_guard
    BEFORE UPDATE ON resource_reset_binding_projection
    BEGIN
        SELECT CASE WHEN NOT EXISTS (
            SELECT 1
            FROM resource_reset_binding_assertions a
            WHERE a.assertion_id = NEW.assertion_id
              AND a.effect_kind = NEW.effect_kind
              AND a.effect_id = NEW.effect_id
              AND a.assertion_state = NEW.projection_state
              AND COALESCE(a.account_id, '') = COALESCE(NEW.account_id, '')
              AND COALESCE(a.server_id, '') = COALESCE(NEW.server_id, '')
              AND COALESCE(a.reset_identity_id, '') = COALESCE(NEW.reset_identity_id, '')
        ) THEN RAISE(ABORT, 'reset projection does not match assertion') END;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS resource_terminal_projection_insert_guard
    BEFORE INSERT ON resource_terminal_projection
    BEGIN
        SELECT CASE WHEN NOT EXISTS (
            SELECT 1
            FROM resource_terminal_observations o
            WHERE o.observation_id = NEW.observation_id
              AND o.occurrence_id = NEW.occurrence_id
              AND o.terminal_state = NEW.terminal_state
        ) THEN RAISE(ABORT, 'terminal projection does not match observation') END;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS resource_terminal_projection_update_guard
    BEFORE UPDATE ON resource_terminal_projection
    BEGIN
        SELECT CASE WHEN NOT EXISTS (
            SELECT 1
            FROM resource_terminal_observations o
            WHERE o.observation_id = NEW.observation_id
              AND o.occurrence_id = NEW.occurrence_id
              AND o.terminal_state = NEW.terminal_state
        ) THEN RAISE(ABORT, 'terminal projection does not match observation') END;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS resource_reservation_binding_guard
    BEFORE INSERT ON resource_reservations
    BEGIN
        SELECT CASE WHEN NOT EXISTS (
            SELECT 1
            FROM resource_occurrences o
            JOIN resource_attempts a ON a.attempt_id = NEW.attempt_id
                                     AND a.occurrence_id = NEW.occurrence_id
            WHERE o.occurrence_id = NEW.occurrence_id
              AND o.account_id = NEW.account_id
              AND o.server_id = NEW.server_id
              AND o.reset_identity_id = NEW.reset_identity_id
              AND o.product_policy_revision = NEW.product_policy_revision
              AND o.recurrence_policy_revision = NEW.recurrence_policy_revision
              AND o.effect_ordinal = NEW.effect_ordinal
        ) THEN RAISE(ABORT, 'Resource reservation identity or revision mismatch') END;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS resource_reservation_binding_update_guard
    BEFORE UPDATE ON resource_reservations
    BEGIN
        SELECT CASE WHEN NOT EXISTS (
            SELECT 1
            FROM resource_occurrences o
            JOIN resource_attempts a ON a.attempt_id = NEW.attempt_id
                                     AND a.occurrence_id = NEW.occurrence_id
            WHERE o.occurrence_id = NEW.occurrence_id
              AND o.account_id = NEW.account_id
              AND o.server_id = NEW.server_id
              AND o.reset_identity_id = NEW.reset_identity_id
              AND o.product_policy_revision = NEW.product_policy_revision
              AND o.recurrence_policy_revision = NEW.recurrence_policy_revision
              AND o.effect_ordinal = NEW.effect_ordinal
        ) THEN RAISE(ABORT, 'Resource reservation identity or revision mismatch') END;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS resource_transport_binding_guard
    BEFORE INSERT ON resource_transport_facts
    BEGIN
        SELECT CASE WHEN NOT EXISTS (
            SELECT 1
            FROM resource_reservations r
            WHERE r.reservation_id = NEW.reservation_id
              AND r.occurrence_id = NEW.occurrence_id
              AND r.attempt_id = NEW.attempt_id
              AND r.account_id = NEW.account_id
              AND r.server_id = NEW.server_id
        ) THEN RAISE(ABORT, 'Resource transport identity mismatch') END;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS resource_live_effect_binding_guard
    BEFORE INSERT ON resource_live_effects
    BEGIN
        SELECT CASE WHEN NOT EXISTS (
            SELECT 1
            FROM resource_reservations r
            JOIN resource_transport_facts t ON t.transport_fact_id = NEW.transport_fact_id
                                             AND t.reservation_id = NEW.reservation_id
                                             AND t.occurrence_id = NEW.occurrence_id
                                             AND t.attempt_id = NEW.attempt_id
            WHERE r.reservation_id = NEW.reservation_id
              AND r.account_id = NEW.account_id
              AND r.server_id = NEW.server_id
              AND r.effect_ordinal = NEW.effect_ordinal
        ) THEN RAISE(ABORT, 'Resource live effect identity mismatch') END;
    END
    """,
)
_RESOURCE_APPEND_ONLY_TABLES = (
    "resource_reset_identities",
    "resource_occurrences",
    "resource_attempts",
    "resource_attempt_claims",
    "resource_historical_transport_facts",
    "resource_historical_effects",
    "resource_historical_classifications",
    "resource_reset_binding_assertions",
    "resource_reset_binding_projection",
    "resource_reservations",
    "resource_transport_facts",
    "resource_transport_outcomes",
    "resource_live_effects",
    "resource_effect_block_facts",
    "resource_effect_block_resolutions",
    "resource_effect_block_projection",
    "resource_terminal_observations",
    "resource_terminal_projection",
    "resource_transition_history",
    "resource_closures",
)
_RESOURCE_IMMUTABLE_FACT_TABLES = (
    "resource_reset_identities",
    "resource_historical_transport_facts",
    "resource_historical_effects",
    "resource_historical_classifications",
    "resource_reset_binding_assertions",
    "resource_transport_facts",
    "resource_transport_outcomes",
    "resource_live_effects",
    "resource_effect_block_facts",
    "resource_effect_block_resolutions",
    "resource_terminal_observations",
    "resource_transition_history",
    "resource_closures",
)


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
        try:
            self._migrate()
            self._ensure_scheduler_tables()
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
            if version == 5:
                self.connection.execute("UPDATE schema_version SET version=4 WHERE singleton=1")
                version = 4
            else:
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
                        released_at REAL,
                        generation INTEGER NOT NULL DEFAULT 0 CHECK (generation >= 0),
                        lease_token_digest TEXT,
                        runtime_invocation_id TEXT,
                        lease_mode TEXT NOT NULL DEFAULT 'legacy'
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
                        status TEXT NOT NULL CHECK(status IN ('pending','deferred','complete_for_reset','already_complete','blocked','manual_required','unresolved','reconciliation_required')),
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
                    status TEXT NOT NULL CHECK(status IN ('pending','deferred','complete_for_reset','already_complete','blocked','manual_required','unresolved','reconciliation_required')),
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
        if self.schema_version == 3:
            self._migrate_resource_v4()
        if self.schema_version == 4:
            self._ensure_scheduler_invocation_reconciliation()
        if self.schema_version != CURRENT_SCHEMA_VERSION:
            raise SchemaVersionError("database migration did not reach the current schema")
    def _ensure_scheduler_invocation_reconciliation(self) -> None:
        """Rebuild legacy invocation CHECK while preserving every v4 row."""

        with self.transaction() as db:
            sql_row = db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='scheduler_invocation_state'"
            ).fetchone()
            sql = str(sql_row["sql"]) if sql_row is not None else ""
            if "reconciliation_required" not in sql:
                db.execute("ALTER TABLE scheduler_invocation_state RENAME TO scheduler_invocation_state_v4")
                db.execute(
                    """CREATE TABLE scheduler_invocation_state (
                        account_id TEXT NOT NULL,
                        server_id TEXT NOT NULL,
                        reset_id TEXT NOT NULL,
                        task_id TEXT NOT NULL,
                        status TEXT NOT NULL CHECK(status IN ('pending','deferred','complete_for_reset','already_complete','blocked','manual_required','unresolved','reconciliation_required')),
                        next_eligible_at REAL,
                        revision INTEGER NOT NULL CHECK(revision >= 0),
                        last_reason_code TEXT NOT NULL,
                        observed_progress_json TEXT NOT NULL,
                        action_count_total INTEGER NOT NULL CHECK(action_count_total >= 0),
                        unresolved_action INTEGER NOT NULL CHECK (unresolved_action IN (0,1)),
                        evidence_refs_json TEXT NOT NULL,
                        updated_at REAL NOT NULL,
                        PRIMARY KEY (account_id,server_id,reset_id,task_id)
                    )"""
                )
                db.execute(
                    """INSERT INTO scheduler_invocation_state
                    SELECT account_id,server_id,reset_id,task_id,status,next_eligible_at,revision,
                           last_reason_code,observed_progress_json,action_count_total,
                           unresolved_action,evidence_refs_json,updated_at
                    FROM scheduler_invocation_state_v4"""
                )
                db.execute("DROP TABLE scheduler_invocation_state_v4")


    def _ensure_scheduler_tables(self) -> None:
        """Create scheduler-owned occurrence/projection tables in the same SQLite store."""

        self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS scheduler_occurrences (
                    occurrence_id TEXT PRIMARY KEY,
                    occurrence_key TEXT NOT NULL UNIQUE,
                    account_id TEXT NOT NULL,
                    server_id TEXT NOT NULL,
                    reset_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    recurrence_class TEXT NOT NULL,
                    repeat_ordinal INTEGER NOT NULL CHECK (repeat_ordinal >= 0),
                    status TEXT NOT NULL CHECK (
                        status IN (
                            'ELIGIBLE','CLAIMED','DEFERRED','COMPLETED',
                            'BLOCKED','MANUAL_REQUIRED','RECONCILIATION_REQUIRED'
                        )
                    ),
                    state_revision INTEGER NOT NULL CHECK (state_revision >= 0),
                    next_eligible_at REAL,
                    projection_json TEXT NOT NULL,
                    claim_id TEXT,
                    claim_token TEXT,
                    pulse_token TEXT,
                    last_reason_code TEXT NOT NULL DEFAULT '',
                    action_count_total INTEGER NOT NULL CHECK (action_count_total >= 0),
                    unresolved_action INTEGER NOT NULL DEFAULT 0 CHECK (unresolved_action IN (0,1)),
                    evidence_refs_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE (account_id, server_id, reset_id, task_id, repeat_ordinal)
                );
                CREATE INDEX IF NOT EXISTS scheduler_occurrence_due_idx
                    ON scheduler_occurrences(account_id, server_id, reset_id, status, next_eligible_at);
                CREATE TABLE IF NOT EXISTS scheduler_occurrence_claims (
                    claim_id TEXT PRIMARY KEY,
                    occurrence_id TEXT NOT NULL,
                    claim_token TEXT NOT NULL UNIQUE,
                    claimed_at REAL NOT NULL,
                    state TEXT NOT NULL CHECK (
                        state IN ('ACTIVE','COMPLETED','DEFERRED','RECONCILIATION_REQUIRED','ABANDONED')
                    ),
                    completed_at REAL,
                    FOREIGN KEY (occurrence_id) REFERENCES scheduler_occurrences(occurrence_id)
                );
                CREATE TABLE IF NOT EXISTS scheduler_projection_state (
                    projection_key TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    server_id TEXT NOT NULL,
                    reset_id TEXT NOT NULL,
                    projection_json TEXT NOT NULL,
                    observed_at_utc REAL NOT NULL,
                    valid INTEGER NOT NULL CHECK (valid IN (0,1)),
                    revision INTEGER NOT NULL CHECK (revision >= 0),
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scheduler_clock_state (
                    account_id TEXT NOT NULL,
                    server_id TEXT NOT NULL,
                    reset_id TEXT NOT NULL,
                    last_utc_epoch REAL NOT NULL,
                    valid INTEGER NOT NULL CHECK (valid IN (0,1)),
                    revision INTEGER NOT NULL CHECK (revision >= 0),
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (account_id, server_id, reset_id)
                );
                """
            )
        columns = {
            str(row["name"])
            for row in self.connection.execute("PRAGMA table_info(scheduler_occurrences)").fetchall()
        }
        for name, definition in (
            ("pulse_token", "TEXT"),
            ("last_reason_code", "TEXT NOT NULL DEFAULT ''"),
            ("unresolved_action", "INTEGER NOT NULL DEFAULT 0 CHECK (unresolved_action IN (0,1))"),
        ):
            if name not in columns:
                self.connection.execute(
                    f"ALTER TABLE scheduler_occurrences ADD COLUMN {name} {definition}"
                )

    def _migrate_resource_v4(self) -> None:
        """Apply the additive Resource schema while preserving every v3 row/API."""

        with self.transaction() as db:
            columns = {
                str(row["name"])
                for row in db.execute("PRAGMA table_info(controller_lease)").fetchall()
            }
            for name, definition in (
                ("generation", "INTEGER NOT NULL DEFAULT 0 CHECK (generation >= 0)"),
                ("lease_token_digest", "TEXT"),
                ("runtime_invocation_id", "TEXT"),
                ("lease_mode", "TEXT NOT NULL DEFAULT 'legacy'"),
            ):
                if name not in columns:
                    db.execute(f"ALTER TABLE controller_lease ADD COLUMN {name} {definition}")
            historical_effect_columns = {
                str(row["name"])
                for row in db.execute(
                    "PRAGMA table_info(resource_historical_effects)"
                ).fetchall()
            }
            if historical_effect_columns and "occurrence_id" not in historical_effect_columns:
                db.execute(
                    "ALTER TABLE resource_historical_effects "
                    "ADD COLUMN occurrence_id TEXT NOT NULL DEFAULT ''"
                )
            for statement in _RESOURCE_V4_DDL:
                db.execute(statement)
            for table_name in _RESOURCE_APPEND_ONLY_TABLES:
                trigger_name = f"{table_name}_no_delete"
                db.execute(
                    f"""
                    CREATE TRIGGER IF NOT EXISTS {trigger_name}
                    BEFORE DELETE ON {table_name}
                    BEGIN
                        SELECT RAISE(ABORT, 'Resource facts and projections are append-only');
                    END
                    """
                )
            for table_name in _RESOURCE_IMMUTABLE_FACT_TABLES:
                trigger_name = f"{table_name}_no_update"
                db.execute(
                    f"""
                    CREATE TRIGGER IF NOT EXISTS {trigger_name}
                    BEFORE UPDATE ON {table_name}
                    BEGIN
                        SELECT RAISE(ABORT, 'Resource immutable facts cannot be updated');
                    END
                    """
                )
            db.execute("UPDATE schema_version SET version=4 WHERE singleton=1")

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

    def _insert_action(
        self,
        db: sqlite3.Connection,
        intent: ActionIntent,
        policy: PolicyResult,
        prepared_at: float,
    ) -> None:
        """Insert one legacy action inside a caller-owned transaction."""

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

    def prepare_action(self, intent: ActionIntent, policy: PolicyResult, prepared_at: float) -> None:
        try:
            with self.transaction() as db:
                self._insert_action(db, intent, policy, prepared_at)
        except sqlite3.IntegrityError as exc:
            if "action_key" in str(exc) or "UNIQUE" in str(exc):
                raise DuplicateActionError(intent.action_key) from exc
            raise

    def prepare_resource_effect_action(self, *args: Any, **kwargs: Any) -> Any:
        """Resource-specific atomic action/reservation wrapper on the sole store."""

        from .resource_effect_authority import ResourceEffectAuthority

        return ResourceEffectAuthority(self).prepare_resource_effect_action(*args, **kwargs)

    def reconcile_resource_effect_observe_only(self, *args: Any, **kwargs: Any) -> Any:
        from .resource_effect_authority import ResourceEffectAuthority

        return ResourceEffectAuthority(self).reconcile_resource_effect_observe_only(*args, **kwargs)

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
            generation = (
                int(row["generation"])
                if row is not None and active and row["owner_id"] == owner_id
                else int(row["generation"]) + 1
                if row is not None
                else 1
            )
            db.execute(
                """INSERT INTO controller_lease(
                    singleton,owner_id,acquired_at,heartbeat_at,expires_at,released_at,
                    generation,lease_token_digest,runtime_invocation_id,lease_mode
                )
                VALUES(1,?,?,?,?,NULL,?,?,?,?) ON CONFLICT(singleton) DO UPDATE SET
                owner_id=excluded.owner_id,acquired_at=excluded.acquired_at,
                heartbeat_at=excluded.heartbeat_at,expires_at=excluded.expires_at,
                released_at=NULL,generation=excluded.generation,
                lease_token_digest=excluded.lease_token_digest,
                runtime_invocation_id=excluded.runtime_invocation_id,
                lease_mode=excluded.lease_mode""",
                (
                    owner_id,
                    acquired,
                    now,
                    now + ttl_seconds,
                    generation,
                    None,
                    None,
                    "legacy",
                ),
            )
            self._insert_audit(db, "controller", "lease_acquired", now, {"owner_id": owner_id, "expires_at": now + ttl_seconds}, None, None, None)
        return self.get_lease(now)

    @staticmethod
    def _lease_token_digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def acquire_resource_controller_lease(
        self,
        owner_id: str,
        now: float,
        ttl_seconds: float,
        *,
        mode: str = "execute",
        runtime_invocation_id: str,
        block_keys: Optional[Mapping[str, Any] | List[str]] = None,
    ) -> Dict[str, Any]:
        """Acquire a fenced Resource controller lease without changing legacy lease semantics."""

        if mode not in {"execute", "reconcile"}:
            raise LeaseError("Resource controller lease mode must be execute or reconcile")
        if not owner_id or not runtime_invocation_id or ttl_seconds <= 0:
            raise LeaseError("Resource controller lease identity and positive TTL are required")
        if mode == "execute" and self.has_scoped_effect_block(block_keys or ()):
            raise LeaseError("active Resource effect block prevents execute lease acquisition")
        with self.transaction() as db:
            row = db.execute("SELECT * FROM controller_lease WHERE singleton=1").fetchone()
            active = row is not None and row["released_at"] is None and row["expires_at"] > now
            if active and row["owner_id"] != owner_id:
                raise LeaseError("controller lease is held by another owner")
            if mode == "execute" and self.has_action_block():
                raise LeaseError("legacy unresolved or nonterminal action blocks Resource lease acquisition")
            if mode == "reconcile" and not active and self.has_action_block():
                raise LeaseError("legacy unresolved or nonterminal action blocks Resource lease acquisition")
            same_owner = active and row["owner_id"] == owner_id
            generation = int(row["generation"]) if same_owner else (int(row["generation"]) + 1 if row else 1)
            acquired = row["acquired_at"] if same_owner else now
            token = uuid.uuid4().hex
            token_digest = self._lease_token_digest(token)
            db.execute(
                """INSERT INTO controller_lease(
                    singleton,owner_id,acquired_at,heartbeat_at,expires_at,released_at,
                    generation,lease_token_digest,runtime_invocation_id,lease_mode
                ) VALUES(1,?,?,?,?,NULL,?,?,?,?)
                ON CONFLICT(singleton) DO UPDATE SET
                    owner_id=excluded.owner_id,acquired_at=excluded.acquired_at,
                    heartbeat_at=excluded.heartbeat_at,expires_at=excluded.expires_at,
                    released_at=NULL,generation=excluded.generation,
                    lease_token_digest=excluded.lease_token_digest,
                    runtime_invocation_id=excluded.runtime_invocation_id,
                    lease_mode=excluded.lease_mode""",
                (
                    owner_id,
                    acquired,
                    now,
                    now + ttl_seconds,
                    generation,
                    token_digest,
                    runtime_invocation_id,
                    mode,
                ),
            )
            self._insert_audit(
                db,
                "controller",
                "resource_lease_acquired",
                now,
                {
                    "owner_id": owner_id,
                    "generation": generation,
                    "runtime_invocation_id": runtime_invocation_id,
                    "mode": mode,
                    "expires_at": now + ttl_seconds,
                },
                None,
                None,
                None,
            )
        result = self.get_lease(now) or {}
        result.update(
            {
                "controller_token": token,
                "controller_generation": generation,
                "runtime_invocation_id": runtime_invocation_id,
                "mode": mode,
            }
        )
        return result

    def release_resource_controller_lease(
        self,
        owner_id: str,
        controller_token: str,
        now: float,
    ) -> None:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM controller_lease WHERE singleton=1").fetchone()
            if (
                row is None
                or row["owner_id"] != owner_id
                or row["released_at"] is not None
                or row["lease_token_digest"] != self._lease_token_digest(controller_token)
            ):
                raise LeaseError("Resource controller lease token is not held by owner")
            db.execute(
                "UPDATE controller_lease SET released_at=? WHERE singleton=1",
                (now,),
            )
            self._insert_audit(
                db,
                "controller",
                "resource_lease_released",
                now,
                {"owner_id": owner_id, "generation": row["generation"]},
                None,
                None,
                None,
            )

    def heartbeat_resource_controller_lease(
        self,
        owner_id: str,
        controller_token: str,
        now: float,
        ttl_seconds: float,
    ) -> Dict[str, Any]:
        if ttl_seconds <= 0:
            raise LeaseError("lease TTL must be positive")
        with self.transaction() as db:
            row = db.execute("SELECT * FROM controller_lease WHERE singleton=1").fetchone()
            if (
                row is None
                or row["owner_id"] != owner_id
                or row["released_at"] is not None
                or row["expires_at"] <= now
                or row["lease_token_digest"] != self._lease_token_digest(controller_token)
            ):
                raise LeaseError("Resource controller lease token is not active")
            db.execute(
                "UPDATE controller_lease SET heartbeat_at=?,expires_at=? WHERE singleton=1",
                (now, now + ttl_seconds),
            )
        return self.get_lease(now) or {}

    def resource_controller_lease_valid(
        self,
        owner_id: str,
        controller_token: str,
        controller_generation: int,
        runtime_invocation_id: str,
        now: float,
        *,
        mode: Optional[str] = None,
    ) -> bool:
        lease = self.get_lease(now)
        if not lease or not lease.get("valid"):
            return False
        if lease.get("owner_id") != owner_id:
            return False
        if lease.get("generation") != controller_generation:
            return False
        if lease.get("runtime_invocation_id") != runtime_invocation_id:
            return False
        if mode is not None and lease.get("lease_mode") != mode:
            return False
        return (
            isinstance(controller_token, str)
            and self._lease_token_digest(controller_token) == lease.get("lease_token_digest")
        )

    def has_scoped_effect_block(
        self,
        block_keys: Mapping[str, Any] | List[str] | tuple[str, ...] | set[str] = (),
    ) -> bool:
        """Resolve Resource scope blocks lazily to keep v3 imports/cycles unchanged."""

        from .resource_effect_authority import ResourceEffectAuthority

        return ResourceEffectAuthority(self).has_scoped_resource_block(block_keys)


    def has_scoped_resource_block(
        self,
        block_keys: Mapping[str, Any] | List[str] | tuple[str, ...] | set[str] = (),
    ) -> bool:
        return self.has_scoped_effect_block(block_keys)

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
