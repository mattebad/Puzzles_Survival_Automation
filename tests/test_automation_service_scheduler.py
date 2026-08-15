from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from automation_service.contracts import (
    FlowDescriptor,
    NormalizedOutcome,
    NormalizedResult,
    SchedulerFacts,
)
from automation_service.scheduler import DisabledProductionAuthority, UtcPulseCoordinator
from safe_action_core import SafetyStore, SQLiteSchedulerInvocationRepository


class CompleteHandler:
    def __init__(self, descriptor: FlowDescriptor) -> None:
        self.descriptor = descriptor
        self.calls = 0

    def describe(self):
        return self.descriptor

    def eligibility(self, facts, perception=None):
        return facts.health_ok and not facts.unresolved_action

    def plan(self, facts, perception=None):
        self.calls += 1
        return NormalizedResult(
            NormalizedOutcome.COMPLETE_FOR_RESET,
            "FAKE_COMPLETE",
            observed_progress={"pulse": self.calls},
        )

    def reconcile(self, plan, perception=None):
        return plan

    def recover(self, reason_code):
        return NormalizedResult(NormalizedOutcome.BLOCKED, reason_code)

    def summarize(self):
        return {"calls": self.calls}


class DeferredHandler(CompleteHandler):
    def plan(self, facts, perception=None):
        self.calls += 1
        return NormalizedResult(
            NormalizedOutcome.DEFERRED,
            "WAIT_FOR_NEXT_UTC_WINDOW",
            next_eligible_at=facts.now_utc_epoch + 60.0,
        )


class UnresolvedHandler(CompleteHandler):
    def plan(self, facts, perception=None):
        return NormalizedResult(NormalizedOutcome.UNRESOLVED, "UNKNOWN_SUCCESSOR")


class TestActivationAuthority:
    def permits(self, descriptor, facts):
        return True


class AutomationServiceSchedulerTests(unittest.TestCase):
    def test_missing_or_disabled_activation_authority_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SafetyStore(Path(folder) / "state.sqlite3")
            try:
                repository = SQLiteSchedulerInvocationRepository(store)
                descriptor = FlowDescriptor("not-registered", "owner", "family", "v", "pulse")
                report = UtcPulseCoordinator(
                    repository,
                    (descriptor,),
                    {"not-registered": CompleteHandler(descriptor)},
                    activation_authority=DisabledProductionAuthority(),
                ).pulse(SchedulerFacts("a", "s", "r", 100.0, health_ok=True))
                self.assertIsNone(report.candidate)
                self.assertEqual(report.reason_code, "NO_ELIGIBLE_TASK")
            finally:
                store.close()

    def test_one_candidate_per_pulse_and_restart_safe_completion(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            store = SafetyStore(path)
            try:
                repository = SQLiteSchedulerInvocationRepository(store)
                first = FlowDescriptor("first", "owner", "family", "one", "reset_pulse", priority=1, scheduler_eligible=True)
                second = FlowDescriptor("second", "owner", "family", "two", "reset_pulse", priority=2, scheduler_eligible=True)
                first_handler = CompleteHandler(first)
                second_handler = CompleteHandler(second)
                facts = SchedulerFacts("account", "server", "reset", 100.0, health_ok=True)
                coordinator = UtcPulseCoordinator(
                    repository,
                    (first, second),
                    {"first": first_handler, "second": second_handler},
                    activation_authority=TestActivationAuthority(),
                )
                report = coordinator.pulse(facts)
                self.assertEqual(report.candidate.descriptor.flow_id, "first")
                self.assertEqual(first_handler.calls, 1)
                self.assertEqual(second_handler.calls, 0)

                for _ in range(99):
                    coordinator.pulse(facts)
                self.assertEqual(first_handler.calls, 1)

                # Ten fresh coordinators prove that state restoration is repository-backed.
                for _ in range(10):
                    coordinator = UtcPulseCoordinator(
                        repository,
                        (first, second),
                        {"first": first_handler, "second": second_handler},
                        activation_authority=TestActivationAuthority(),
                    )
                    coordinator.pulse(facts)
                self.assertEqual(first_handler.calls, 1)
                self.assertEqual(second_handler.calls, 1)
            finally:
                store.close()

    def test_deadline_is_utc_epoch_and_global_locks_skip_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SafetyStore(Path(folder) / "state.sqlite3")
            try:
                repository = SQLiteSchedulerInvocationRepository(store)
                descriptor = FlowDescriptor("deferred", "owner", "family", "v", "cooldown_pulse", scheduler_eligible=True)
                handler = DeferredHandler(descriptor)
                coordinator = UtcPulseCoordinator(
                    repository,
                    (descriptor,),
                    {"deferred": handler},
                    activation_authority=TestActivationAuthority(),
                )
                first = coordinator.pulse(SchedulerFacts("a", "s", "r", 100.0, health_ok=True))
                self.assertEqual(first.result.next_eligible_at, 160.0)
                locked = coordinator.pulse(
                    SchedulerFacts("a", "s", "r", 200.0, health_ok=True, unresolved_action=True)
                )
                self.assertEqual(locked.reason_code, "GLOBAL_UNRESOLVED_ACTION")
                self.assertEqual(handler.calls, 1)
            finally:
                store.close()

    def test_unresolved_always_persists_blocked_global_lock(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SafetyStore(Path(folder) / "state.sqlite3")
            try:
                repository = SQLiteSchedulerInvocationRepository(store)
                descriptor = FlowDescriptor(
                    "unresolved",
                    "owner",
                    "family",
                    "v",
                    "pulse",
                    scheduler_eligible=True,
                )
                coordinator = UtcPulseCoordinator(
                    repository,
                    (descriptor,),
                    {"unresolved": UnresolvedHandler(descriptor)},
                    activation_authority=TestActivationAuthority(),
                )
                report = coordinator.pulse(
                    SchedulerFacts("a", "s", "r", 100.0, health_ok=True)
                )
                self.assertEqual(report.result.outcome.value, "blocked")
                self.assertTrue(report.result.unresolved_action)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()

