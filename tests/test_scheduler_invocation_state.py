"""Focused tests for account/server/reset/task scheduler invocation persistence."""

from pathlib import Path
import tempfile
import threading
import unittest

from safe_action_core import CURRENT_SCHEMA_VERSION, SafetyStore, SQLiteSchedulerInvocationRepository
from safe_action_core.scheduler_invocation_state import ProjectionInvalidatedError
from automation_service.contracts import RecurrenceClass, RecurrenceProjection
from tasks.nova_praise_pulse import NOVA_TASK_ID
from tasks.scheduler_task_result import (
    SchedulerAwareTaskResult,
    SchedulerIdentity,
    SchedulerTaskOutcome,
)


class SchedulerInvocationStateTests(unittest.TestCase):
    def test_schema_migrates_to_v3_and_keys_by_account_server_reset_task(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            store = SafetyStore(path)
            self.assertEqual(store.schema_version, CURRENT_SCHEMA_VERSION)
            self.assertGreaterEqual(CURRENT_SCHEMA_VERSION, 3)
            repo = SQLiteSchedulerInvocationRepository(store)
            identity = SchedulerIdentity("acct-a", "srv-1", "reset-1", NOVA_TASK_ID)
            other_reset = SchedulerIdentity("acct-a", "srv-1", "reset-2", NOVA_TASK_ID)
            result = SchedulerAwareTaskResult.action_performed(
                identity,
                "FREE_PRAISE_VERIFIED",
                action_count=1,
                observed_progress={"attempts_remaining": 6},
                next_eligible_at=200.0,
            )
            saved = repo.apply_result(result, 100.0)
            self.assertEqual(saved.identity.composite_key, identity.composite_key)
            self.assertEqual(repo.get(identity).status, "deferred")
            self.assertIsNone(repo.get(other_reset))
            self.assertFalse(repo.is_eligible(identity, 150.0))
            self.assertTrue(repo.is_eligible(identity, 200.0))
            store.close()

            reopened = SafetyStore(path)
            try:
                restored = SQLiteSchedulerInvocationRepository(reopened)
                loaded = restored.get(identity)
                self.assertIsNotNone(loaded)
                self.assertEqual(loaded.next_eligible_at, 200.0)
                self.assertEqual(loaded.action_count_total, 1)
            finally:
                reopened.close()

    def test_reset_rollover_makes_task_eligible_again(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            store = SafetyStore(path)
            repo = SQLiteSchedulerInvocationRepository(store)
            day1 = SchedulerIdentity("acct", "srv", "day-1", NOVA_TASK_ID)
            day2 = SchedulerIdentity("acct", "srv", "day-2", NOVA_TASK_ID)
            repo.apply_result(
                SchedulerAwareTaskResult.complete_for_reset(day1, "NOVA_PRAISE_ATTEMPTS_CONSUMED"),
                10.0,
            )
            self.assertFalse(repo.is_eligible(day1, 999.0))
            self.assertTrue(repo.is_eligible(day2, 11.0))
            store.close()
    def test_populated_legacy_v4_invocation_check_upgrades_in_place(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            store = SafetyStore(path)
            store.connection.execute("ALTER TABLE scheduler_invocation_state RENAME TO scheduler_invocation_state_legacy")
            store.connection.execute(
                """CREATE TABLE scheduler_invocation_state (
                account_id TEXT NOT NULL,
                server_id TEXT NOT NULL,
                reset_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','deferred','complete_for_reset','already_complete','blocked','manual_required','unresolved')),
                next_eligible_at REAL,
                revision INTEGER NOT NULL,
                last_reason_code TEXT NOT NULL,
                observed_progress_json TEXT NOT NULL,
                action_count_total INTEGER NOT NULL,
                unresolved_action INTEGER NOT NULL,
                evidence_refs_json TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (account_id,server_id,reset_id,task_id)
                )"""
            )
            store.connection.execute(
                """INSERT INTO scheduler_invocation_state VALUES
                ('acct','srv','reset','task','deferred',200.0,1,'WAIT','{}',0,0,'[]',100.0)"""
            )
            store.connection.execute("DROP TABLE scheduler_invocation_state_legacy")
            store.close()
            reopened = SafetyStore(path)
            try:
                self.assertEqual(reopened.schema_version, 4)
                restored = SQLiteSchedulerInvocationRepository(reopened).get(
                    SchedulerIdentity("acct", "srv", "reset", "task")
                )
                self.assertIsNotNone(restored)
                self.assertEqual(restored.status, "deferred")
                self.assertEqual(restored.next_eligible_at, 200.0)
            finally:
                reopened.close()


    def test_same_pulse_deferred_occurrence_is_durable_fence(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SafetyStore(Path(folder) / "state.sqlite3")
            try:
                repo = SQLiteSchedulerInvocationRepository(store)
                identity = SchedulerIdentity("acct", "srv", "reset", "task")
                claim = repo.claim_occurrence(identity, 100.0, pulse_token="pulse-100")
                self.assertIsNotNone(claim)
                repo.finalize_claim(
                    claim,
                    SchedulerAwareTaskResult.deferred(identity, "WAIT", 100.0),
                    100.0,
                )
                self.assertIsNone(repo.claim_occurrence(identity, 100.0, pulse_token="pulse-100"))
                self.assertIsNotNone(repo.claim_occurrence(identity, 101.0, pulse_token="pulse-101"))
            finally:
                store.close()

    def test_two_sqlite_connections_claim_one_occurrence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            initial_store = SafetyStore(path)
            initial_store.close()
            barrier = threading.Barrier(2)
            claims = []
            errors = []

            def attempt():
                store = SafetyStore(path)
                try:
                    barrier.wait()
                    claim = SQLiteSchedulerInvocationRepository(store).claim_occurrence(
                        SchedulerIdentity("acct", "srv", "reset", "task"),
                        100.0,
                        pulse_token="pulse-100",
                    )
                    claims.append(claim)
                except Exception as exc:
                    errors.append(exc)
                finally:
                    store.close()

            threads = [
                threading.Thread(target=attempt),
                threading.Thread(target=attempt),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            self.assertEqual(sum(claim is not None for claim in claims), 1)

    def test_stale_projection_cannot_restore_invalidated_observation(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SafetyStore(Path(folder) / "state.sqlite3")
            try:
                repo = SQLiteSchedulerInvocationRepository(store)
                identity = SchedulerIdentity("acct", "srv", "reset", "task")
                projection = RecurrenceProjection(
                    RecurrenceClass.QUEUE_GENERATION,
                    observed_at_utc=100.0,
                    generation="g1",
                )
                repo.save_projection(identity, "projection", projection, 100.0)
                repo.invalidate_projections(identity, 101.0)
                store.close()
                reopened = SafetyStore(Path(folder) / "state.sqlite3")
                try:
                    restored = SQLiteSchedulerInvocationRepository(reopened)
                    self.assertFalse(restored.projection_is_valid("projection", 101.0, 300.0))
                    with self.assertRaises(ProjectionInvalidatedError):
                        restored.save_projection(identity, "projection", projection, 100.0)
                    with self.assertRaises(ProjectionInvalidatedError):
                        restored.save_projection(identity, "projection", {"generation": "stale"}, 101.0)
                    with self.assertRaises(ValueError):
                        restored.save_projection(identity, "projection", {"generation": "undated"}, 102.0)
                    with self.assertRaises(ValueError):
                        restored.save_projection(identity, "projection", projection, None)
                    restored.save_projection(
                        identity,
                        "projection",
                        RecurrenceProjection(
                            RecurrenceClass.QUEUE_GENERATION,
                            observed_at_utc=102.0,
                            generation="g2",
                        ),
                        102.0,
                    )
                    self.assertTrue(restored.projection_is_valid("projection", 102.0, 300.0))
                finally:
                    reopened.close()
            finally:
                pass

    def test_reset_disagreement_invalidates_declared_and_observed_projections(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SafetyStore(Path(folder) / "state.sqlite3")
            try:
                repo = SQLiteSchedulerInvocationRepository(store)
                declared = SchedulerIdentity("acct", "srv", "declared", "task")
                observed = SchedulerIdentity("acct", "srv", "observed", "task")
                projection = RecurrenceProjection(
                    RecurrenceClass.QUEUE_GENERATION,
                    observed_at_utc=100.0,
                    generation="g1",
                )
                repo.save_projection(declared, "declared-projection", projection, 100.0)
                repo.save_projection(observed, "observed-projection", projection, 100.0)
                repo.record_reset_disagreement("acct", "srv", "declared", "observed", 101.0)
                self.assertIsNone(repo.get_projection("declared-projection"))
                self.assertIsNone(repo.get_projection("observed-projection"))
            finally:
                store.close()

    def test_orphan_reconciliation_accepts_only_verified_positive_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SafetyStore(Path(folder) / "state.sqlite3")
            try:
                repo = SQLiteSchedulerInvocationRepository(store)
                identity = SchedulerIdentity("acct", "srv", "reset", "task")
                claim = repo.claim_occurrence(identity, 100.0, pulse_token="pulse-100")
                self.assertIsNotNone(claim)
                deferred = SchedulerAwareTaskResult.deferred(identity, "WAIT", 200.0)
                state = repo.reconcile_orphan_claim(claim.claim_id, deferred, 101.0)
                self.assertEqual(state.status, "reconciliation_required")
                self.assertTrue(state.unresolved_action)
                self.assertEqual(repo.get_occurrence(claim.occurrence_key).status, "RECONCILIATION_REQUIRED")
            finally:
                store.close()


    def test_v2_database_migrates_forward(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.sqlite3"
            import sqlite3

            conn = sqlite3.connect(str(path))
            conn.executescript(
                """
                CREATE TABLE schema_version (singleton INTEGER PRIMARY KEY CHECK (singleton = 1), version INTEGER NOT NULL);
                INSERT INTO schema_version(singleton, version) VALUES (1, 2);
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
                    status TEXT NOT NULL,
                    next_due_monotonic REAL,
                    revision INTEGER NOT NULL,
                    last_reason TEXT NOT NULL,
                    updated_at REAL NOT NULL
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
                    consequential INTEGER NOT NULL,
                    policy_request_json TEXT NOT NULL,
                    policy_decision TEXT NOT NULL,
                    policy_reason TEXT NOT NULL,
                    prepared_at REAL NOT NULL,
                    input_attempt_at REAL,
                    transport_result_json TEXT,
                    reconciliation_result_json TEXT,
                    evidence_refs_json TEXT NOT NULL,
                    final_status TEXT NOT NULL,
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
                """
            )
            conn.close()
            store = SafetyStore(path)
            try:
                self.assertEqual(store.schema_version, CURRENT_SCHEMA_VERSION)
                repo = SQLiteSchedulerInvocationRepository(store)
                identity = SchedulerIdentity("a", "b", "c", NOVA_TASK_ID)
                repo.apply_result(SchedulerAwareTaskResult.deferred(identity, "WAIT", 50.0), 1.0)
                self.assertEqual(repo.get(identity).status, "deferred")
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
