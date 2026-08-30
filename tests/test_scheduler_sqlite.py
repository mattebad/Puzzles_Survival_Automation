from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from safe_action_core import SQLiteTaskStateRepository, SafetyStore
from tasks.scheduler import LegacySchedulerRetiredError, SQLiteBackedOnePulseScheduler, TaskState


class RetiredSQLiteSchedulerTests(unittest.TestCase):
    def test_populated_task_state_is_preserved_but_not_interpreted(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SafetyStore(Path(folder) / "state.sqlite3")
            try:
                repository = SQLiteTaskStateRepository(store)
                state = TaskState("legacy", "legacy:done", "day-1")
                repository.save(state, 0.0)
                self.assertEqual(repository.list()[0].task_id, "legacy")
                with self.assertRaises(LegacySchedulerRetiredError):
                    SQLiteBackedOnePulseScheduler(repository)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
