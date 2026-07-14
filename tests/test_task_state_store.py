from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from safe_action_core import CURRENT_SCHEMA_VERSION, SQLiteTaskStateRepository, SafetyStore
from safe_action_core.store import StoreError
from tasks.scheduler import TaskState, TaskStateStatus


class SQLiteTaskStateRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "state.sqlite3"
        self.store = SafetyStore(self.path)
        self.repository = SQLiteTaskStateRepository(self.store)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_current_schema_contains_task_state_and_round_trips(self):
        self.assertEqual(self.store.schema_version, CURRENT_SCHEMA_VERSION)
        state = TaskState("daily", "daily:done", "day-1", next_due_monotonic=12.5)
        self.repository.save(state, 10.0)
        self.assertEqual(self.repository.get("daily"), state)
        self.assertEqual(self.repository.list(), (state,))
        self.assertEqual(self.store.audit_events()[-1]["event_type"], "task_state_updated")

    def test_revision_and_completion_key_are_monotonic(self):
        state = TaskState("daily", "daily:done", "day-1", revision=2, last_reason="progress")
        self.repository.save(state, 10.0)
        with self.assertRaises(StoreError):
            self.repository.save(TaskState("daily", "daily:done", "day-1", revision=1), 11.0)
        with self.assertRaises(StoreError):
            self.repository.save(TaskState("daily", "other", "day-1"), 12.0)

    def test_v1_database_migrates_forward_without_losing_task_table(self):
        self.store.connection.execute("UPDATE schema_version SET version=1 WHERE singleton=1")
        self.store.close()
        reopened = SafetyStore(self.path)
        try:
            self.assertEqual(reopened.schema_version, CURRENT_SCHEMA_VERSION)
            adapter = SQLiteTaskStateRepository(reopened)
            state = TaskState("daily", "daily:done", "day-1", status=TaskStateStatus.BLOCKED, next_due_monotonic=None)
            adapter.save(state, 20.0)
            self.assertEqual(adapter.get("daily"), state)
        finally:
            reopened.close()
            self.store = reopened

    def test_action_journal_tables_remain_present(self):
        tables = {row[0] for row in self.store.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"actions", "audit_events", "controller_lease", "task_state"}.issubset(tables))


if __name__ == "__main__":
    unittest.main()
