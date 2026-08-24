from __future__ import annotations

import unittest

from tasks.scheduler import LegacySchedulerRetiredError, OnePulseScheduler, TaskState


class RetiredSchedulerTests(unittest.TestCase):
    def test_legacy_constructor_rejects_populated_state(self) -> None:
        state = TaskState("legacy", "legacy:done", "day-1")
        with self.assertRaises(LegacySchedulerRetiredError):
            OnePulseScheduler((state,))

    def test_legacy_state_model_remains_readable_but_not_schedulable(self) -> None:
        state = TaskState("legacy", "legacy:done", "day-1")
        self.assertEqual(state.task_id, "legacy")
        with self.assertRaises(LegacySchedulerRetiredError):
            OnePulseScheduler()


if __name__ == "__main__":
    unittest.main()
