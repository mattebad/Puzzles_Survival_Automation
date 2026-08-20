"""Focused tests for account/server/reset/task scheduler invocation persistence."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from safe_action_core import CURRENT_SCHEMA_VERSION, SafetyStore, SQLiteSchedulerInvocationRepository
from tasks.nova_praise_pulse import NOVA_TASK_ID
from tasks.scheduler_task_result import SchedulerAwareTaskResult, SchedulerIdentity


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
