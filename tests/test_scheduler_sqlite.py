from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from safe_action_core import SQLiteTaskStateRepository, SafetyStore
from tasks.contracts import TaskResult
from tasks.scheduler import SQLiteBackedOnePulseScheduler, TaskState, TaskStateStatus


class SQLiteBackedSchedulerTests(unittest.TestCase):
    def test_backoff_and_completion_survive_repository_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            store = SafetyStore(path)
            repository = SQLiteTaskStateRepository(store)
            repository.save(TaskState("daily", "daily:done", "day-1"), 0.0)
            scheduler = SQLiteBackedOnePulseScheduler(repository)
            self.assertIsNotNone(scheduler.next_pulse(0.0, "day-1", lease_valid=True, unresolved_action=False))
            scheduler.record_result("daily", TaskResult.progress("wait"), 10.0, backoff_seconds=5.0)
            store.close()

            reopened = SafetyStore(path)
            try:
                restored = SQLiteBackedOnePulseScheduler(SQLiteTaskStateRepository(reopened))
                self.assertIsNone(restored.next_pulse(14.9, "day-1", lease_valid=True, unresolved_action=False))
                self.assertIsNotNone(restored.next_pulse(15.0, "day-1", lease_valid=True, unresolved_action=False))
                restored.record_result("daily", TaskResult.done("verified", "daily:done", "DAILY_QUEST"), 15.0)
                self.assertEqual(restored.snapshot()[0].status, TaskStateStatus.DONE)
            finally:
                reopened.close()

    def test_unresolved_state_survives_restart_and_requires_reconciliation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            store = SafetyStore(path)
            repository = SQLiteTaskStateRepository(store)
            repository.save(TaskState("daily", "daily:done", "day-1"), 0.0)
            scheduler = SQLiteBackedOnePulseScheduler(repository)
            scheduler.mark_unresolved("daily", "unknown outcome", 1.0)
            store.close()

            reopened = SafetyStore(path)
            try:
                restored = SQLiteBackedOnePulseScheduler(SQLiteTaskStateRepository(reopened))
                self.assertIsNone(restored.next_pulse(100.0, "day-1", lease_valid=True, unresolved_action=False))
                reconciled = restored.reconcile_unresolved("daily", TaskResult.done("positive", "daily:done", "DAILY_QUEST"), 2.0)
                self.assertEqual(reconciled.status, TaskStateStatus.DONE)
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
