from __future__ import annotations

import unittest

from tasks.scheduler import (
    LegacySchedulerRetiredError,
    OnePulseScheduler,
    SQLiteBackedOnePulseScheduler,
    TaskState,
)


class SchedulerRetirementTests(unittest.TestCase):
    def test_both_legacy_entrypoints_are_non_instantiable(self) -> None:
        with self.assertRaises(LegacySchedulerRetiredError):
            OnePulseScheduler()
        with self.assertRaises(LegacySchedulerRetiredError):
            SQLiteBackedOnePulseScheduler(object())

    def test_ambiguous_monotonic_state_is_not_guessed(self) -> None:
        historical = TaskState("legacy", "legacy:done", "day-1")
        with self.assertRaises(LegacySchedulerRetiredError):
            OnePulseScheduler((historical,))


if __name__ == "__main__":
    unittest.main()
