from __future__ import annotations

import unittest

from tasks.contracts import TaskOutcome, TaskResult
from tasks.scheduler import (
    OnePulseScheduler,
    SchedulerError,
    TaskState,
    TaskStateStatus,
)


def state(task_id: str, due: float = 0.0) -> TaskState:
    return TaskState(task_id, f"{task_id}:done", "day-1", next_due_monotonic=due)


class SchedulerTests(unittest.TestCase):
    def test_selects_at_most_one_deterministic_due_task(self):
        scheduler = OnePulseScheduler((state("b", 1.0), state("a", 1.0), state("later", 9.0)))
        candidate = scheduler.next_pulse(2.0, "day-1", lease_valid=True, unresolved_action=False)
        self.assertEqual(candidate.task_id, "a")
        self.assertIsNone(scheduler.next_pulse(2.0, "day-2", lease_valid=True, unresolved_action=False))

    def test_lease_and_unresolved_gates_block_without_mutating_state(self):
        scheduler = OnePulseScheduler((state("a"),))
        before = scheduler.snapshot()
        self.assertIsNone(scheduler.next_pulse(0.0, "day-1", lease_valid=False, unresolved_action=False))
        self.assertIsNone(scheduler.next_pulse(0.0, "day-1", lease_valid=True, unresolved_action=True))
        self.assertEqual(scheduler.snapshot(), before)

    def test_progress_and_blocked_results_use_bounded_backoff(self):
        scheduler = OnePulseScheduler((state("a"),))
        updated = scheduler.record_result("a", TaskResult.progress("wait for observation"), 10.0, backoff_seconds=5.0)
        self.assertEqual(updated.status, TaskStateStatus.PENDING)
        self.assertEqual(updated.next_due_monotonic, 15.0)
        self.assertIsNone(scheduler.next_pulse(14.9, "day-1", lease_valid=True, unresolved_action=False))
        updated = scheduler.record_result("a", TaskResult(TaskOutcome.BLOCKED, "no target", verified=True), 20.0, backoff_seconds=7.0)
        self.assertEqual(updated.next_due_monotonic, 27.0)

    def test_only_verified_matching_completion_marks_done(self):
        scheduler = OnePulseScheduler((state("a"),))
        mismatch = scheduler.record_result("a", TaskResult.done("wrong", "other", "STATE"), 1.0)
        self.assertEqual(mismatch.status, TaskStateStatus.BLOCKED)
        scheduler = OnePulseScheduler((state("a"),))
        done = scheduler.record_result("a", TaskResult.done("confirmed", "a:done", "STATE"), 1.0)
        self.assertEqual(done.status, TaskStateStatus.DONE)
        self.assertIsNone(scheduler.next_pulse(2.0, "day-1", lease_valid=True, unresolved_action=False))

    def test_failed_safe_and_unresolved_never_auto_retry(self):
        scheduler = OnePulseScheduler((state("a"), state("b")))
        failed = scheduler.record_result("a", TaskResult(TaskOutcome.FAILED_SAFE, "unknown", verified=False), 1.0)
        self.assertEqual(failed.status, TaskStateStatus.BLOCKED)
        unresolved = scheduler.mark_unresolved("b", "transport outcome unknown")
        self.assertEqual(unresolved.status, TaskStateStatus.UNRESOLVED)
        self.assertIsNone(scheduler.next_pulse(2.0, "day-1", lease_valid=True, unresolved_action=False))

    def test_unresolved_requires_positive_reconciliation(self):
        scheduler = OnePulseScheduler((state("a"),))
        scheduler.mark_unresolved("a", "unknown")
        blocked = scheduler.reconcile_unresolved("a", TaskResult.progress("not positive"))
        self.assertEqual(blocked.status, TaskStateStatus.BLOCKED)
        scheduler = OnePulseScheduler((state("a"),))
        scheduler.mark_unresolved("a", "unknown")
        done = scheduler.reconcile_unresolved("a", TaskResult.done("positive", "a:done", "STATE"))
        self.assertEqual(done.status, TaskStateStatus.DONE)

    def test_snapshot_round_trip_is_deterministic(self):
        scheduler = OnePulseScheduler((state("b", 2.0), state("a", 1.0)))
        scheduler.record_result("a", TaskResult.progress("wait", "STATE"), 3.0, backoff_seconds=4.0)
        raw = scheduler.to_json()
        restored = OnePulseScheduler.from_json(raw)
        self.assertEqual(restored.to_json(), raw)
        self.assertEqual([item.task_id for item in restored.snapshot()], ["a", "b"])

    def test_invalid_state_and_schema_fail_closed(self):
        with self.assertRaises(SchedulerError):
            TaskState("", "key", "day")
        with self.assertRaises(SchedulerError):
            OnePulseScheduler.from_json('{"schema":"wrong","states":[]}')
        with self.assertRaises(SchedulerError):
            OnePulseScheduler((state("a"),)).register(TaskState("a", "other", "day-1"))


if __name__ == "__main__":
    unittest.main()
