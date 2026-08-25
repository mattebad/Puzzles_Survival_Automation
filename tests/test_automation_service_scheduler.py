from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from automation_service.contracts import (
    FlowDescriptor,
    NormalizedOutcome,
    NormalizedResult,
    RecurrenceClass,
    RecurrenceProjection,
    SchedulerFacts,
)
from automation_service.scheduler import UtcPulseCoordinator
from safe_action_core import SafetyStore, SQLiteSchedulerInvocationRepository


class Authority:
    def permits(self, descriptor, facts):
        return True


class Handler:
    def __init__(self, descriptor, result=None, revalidate=True, raises=False):
        self.descriptor = descriptor
        self.result = result or NormalizedResult(NormalizedOutcome.COMPLETE_FOR_RESET, "DONE")
        self.revalidate_value = revalidate
        self.raises = raises
        self.plan_calls = 0

    def describe(self):
        return self.descriptor

    def eligibility(self, facts, perception=None):
        return True

    def revalidate(self, facts, perception=None):
        if self.raises:
            raise RuntimeError("revalidation unknown")
        return self.revalidate_value

    def plan(self, facts, perception=None):
        self.plan_calls += 1
        if self.raises:
            raise RuntimeError("handler unknown")
        return self.result

    def reconcile(self, plan, perception=None):
        return plan

    def recover(self, reason_code):
        return NormalizedResult(NormalizedOutcome.BLOCKED, reason_code)

    def summarize(self):
        return {"plan_calls": self.plan_calls}


def descriptor(flow_id="flow", **kwargs):
    return FlowDescriptor(
        flow_id, "owner", "family", "variant", "daily_once_per_reset",
        scheduler_eligible=True, accepted_product="product-v1", product_revision="r1",
        registration_status="REGISTERED", **kwargs,
    )


def facts(reset="reset-1", now=100.0, **kwargs):
    values = dict(
        health_ok=True,
        accepted_product="product-v1",
        product_revision="r1",
        registration_status="REGISTERED",
        scheduler_eligible=True,
        owner_available=True,
        clock_ok=True,
        reset_agreement=True,
    )
    values.update(kwargs)
    return SchedulerFacts("account", "server", reset, now, **values)

class AutomationServiceSchedulerTests(unittest.TestCase):
    def test_mandatory_gates_fail_closed_without_handler_start(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SafetyStore(Path(folder) / "state.sqlite3")
            try:
                d = descriptor(); handler = Handler(d)
                coordinator = UtcPulseCoordinator(SQLiteSchedulerInvocationRepository(store), [d], {d.flow_id: handler}, activation_authority=Authority())
                report = coordinator.pulse(facts(clock_ok=False))
                self.assertEqual(report.reason_code, "UTC_CLOCK_INVALID")
                self.assertEqual(handler.plan_calls, 0)
            finally:
                store.close()

    def test_one_candidate_per_pulse_and_restart_safe_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SafetyStore(Path(folder) / "state.sqlite3")
            d1, d2 = descriptor("first", priority=1), descriptor("second", priority=2)
            h1, h2 = Handler(d1), Handler(d2)
            try:
                repo = SQLiteSchedulerInvocationRepository(store)
                coordinator = UtcPulseCoordinator(repo, [d1, d2], {"first": h1, "second": h2}, activation_authority=Authority())
                first = coordinator.pulse(facts())
                self.assertEqual(first.candidate.descriptor.flow_id, "first")
                self.assertEqual(h1.plan_calls, 1); self.assertEqual(h2.plan_calls, 0)
                second = UtcPulseCoordinator(repo, [d1, d2], {"first": h1, "second": h2}, activation_authority=Authority()).pulse(facts(now=101))
                self.assertEqual(second.candidate.descriptor.flow_id, "second")
            finally:
                store.close()

    def test_post_selection_revalidation_and_unknown_are_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SafetyStore(Path(folder) / "state.sqlite3")
            try:
                d = descriptor(); h = Handler(d, revalidate=False); repo = SQLiteSchedulerInvocationRepository(store)
                report = UtcPulseCoordinator(repo, [d], {d.flow_id: h}, activation_authority=Authority()).pulse(facts())
                self.assertEqual(report.reason_code, "POST_SELECTION_REVALIDATION_FAILED"); self.assertEqual(h.plan_calls, 0)
            finally:
                store.close()
        with tempfile.TemporaryDirectory() as folder:
            store = SafetyStore(Path(folder) / "state.sqlite3")
            try:
                d = descriptor(); h = Handler(d, raises=True); repo = SQLiteSchedulerInvocationRepository(store)
                report = UtcPulseCoordinator(repo, [d], {d.flow_id: h}, activation_authority=Authority()).pulse(facts())
                self.assertEqual(report.result.outcome.value, "reconciliation_required")
                self.assertTrue(repo.get(report.candidate.identity).unresolved_action)
            finally:
                store.close()

    def test_abandoned_bounded_repeat_claim_reuses_ordinal_across_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            projection = RecurrenceProjection(
                RecurrenceClass.BOUNDED_REPEAT,
                observed_at_utc=100.0,
                repeat_ordinal=0,
                repeat_limit=2,
            )
            d = descriptor(recurrence=projection)
            handler = Handler(d, revalidate=False)
            store = SafetyStore(path)
            try:
                repo = SQLiteSchedulerInvocationRepository(store)
                coordinator = UtcPulseCoordinator(
                    repo, [d], {d.flow_id: handler}, activation_authority=Authority()
                )
                first = coordinator.pulse(facts(now=100.0, projections={"flow": projection}))
                second = coordinator.pulse(facts(now=101.0, projections={"flow": projection}))
                self.assertEqual(first.reason_code, "POST_SELECTION_REVALIDATION_FAILED")
                self.assertEqual(second.reason_code, "POST_SELECTION_REVALIDATION_FAILED")
                self.assertEqual(first.candidate.claim.occurrence.repeat_ordinal, 0)
                self.assertEqual(second.candidate.claim.occurrence.repeat_ordinal, 0)
                self.assertEqual(handler.plan_calls, 0)
                self.assertEqual(repo.next_repeat_ordinal(first.candidate.identity, 2), 0)
                self.assertEqual(
                    [item.repeat_ordinal for item in repo.list_occurrences()],
                    [0],
                )
            finally:
                store.close()

            reopened = SafetyStore(path)
            try:
                handler.revalidate_value = True
                handler.result = NormalizedResult(
                    NormalizedOutcome.ACTION_PERFORMED,
                    "CONSUMED",
                    action_count=1,
                )
                repo = SQLiteSchedulerInvocationRepository(reopened)
                resumed = UtcPulseCoordinator(
                    repo, [d], {d.flow_id: handler}, activation_authority=Authority()
                ).pulse(facts(now=102.0, projections={"flow": projection}))
                self.assertEqual(resumed.candidate.claim.occurrence.repeat_ordinal, 0)
                self.assertEqual(resumed.reason_code, "CONSUMED")
                self.assertEqual(handler.plan_calls, 1)
                self.assertEqual(repo.next_repeat_ordinal(resumed.candidate.identity, 2), 1)
            finally:
                reopened.close()

            final_store = SafetyStore(path)
            try:
                final_handler = Handler(
                    d,
                    result=NormalizedResult(
                        NormalizedOutcome.ACTION_PERFORMED,
                        "CONSUMED",
                        action_count=1,
                    ),
                )
                repo = SQLiteSchedulerInvocationRepository(final_store)
                final = UtcPulseCoordinator(
                    repo,
                    [d],
                    {d.flow_id: final_handler},
                    activation_authority=Authority(),
                ).pulse(facts(now=103.0, projections={"flow": projection}))
                self.assertEqual(final.candidate.claim.occurrence.repeat_ordinal, 1)
                self.assertEqual(final_handler.plan_calls, 1)
            finally:
                final_store.close()

    def test_blocked_result_is_terminal_without_unresolved_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SafetyStore(Path(folder) / "state.sqlite3")
            try:
                d = descriptor()
                h = Handler(d, result=NormalizedResult(NormalizedOutcome.BLOCKED, "POLICY_BLOCKED"))
                repo = SQLiteSchedulerInvocationRepository(store)
                report = UtcPulseCoordinator(
                    repo, [d], {d.flow_id: h}, activation_authority=Authority()
                ).pulse(facts())
                self.assertEqual(report.result.outcome, NormalizedOutcome.BLOCKED)
                state = repo.get(report.candidate.identity)
                self.assertEqual(state.status, "blocked")
                self.assertFalse(state.unresolved_action)
            finally:
                store.close()

    def test_manual_required_is_terminal_and_does_not_lock_other_flow(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SafetyStore(Path(folder) / "state.sqlite3")
            try:
                d1, d2 = descriptor("manual"), descriptor("next")
                h1 = Handler(d1, result=NormalizedResult(NormalizedOutcome.MANUAL_REQUIRED, "NEEDS_OPERATOR"))
                h2 = Handler(d2)
                repo = SQLiteSchedulerInvocationRepository(store)
                coordinator = UtcPulseCoordinator(
                    repo,
                    [d1, d2],
                    {"manual": h1, "next": h2},
                    activation_authority=Authority(),
                )
                first = coordinator.pulse(facts())
                self.assertEqual(first.result.outcome, NormalizedOutcome.MANUAL_REQUIRED)
                self.assertFalse(repo.get(first.candidate.identity).unresolved_action)
                self.assertEqual(repo.get(first.candidate.identity).status, "manual_required")
                second = coordinator.pulse(facts(now=101.0))
                self.assertEqual(second.candidate.descriptor.flow_id, "next")
            finally:
                store.close()

    def test_undated_projection_is_rejected_for_cooldown_timer_and_selection(self):
        with self.assertRaises(ValueError):
            RecurrenceProjection(RecurrenceClass.COOLDOWN, next_eligible_at=100.0)
        with self.assertRaises(ValueError):
            RecurrenceProjection(RecurrenceClass.TIMER, next_eligible_at=100.0)
        with tempfile.TemporaryDirectory() as folder:
            store = SafetyStore(Path(folder) / "state.sqlite3")
            try:
                d = descriptor(
                    recurrence=RecurrenceProjection(
                        RecurrenceClass.QUEUE_GENERATION,
                        generation="g1",
                    )
                )
                handler = Handler(d)
                report = UtcPulseCoordinator(
                    SQLiteSchedulerInvocationRepository(store),
                    [d],
                    {d.flow_id: handler},
                    activation_authority=Authority(),
                ).pulse(facts())
                self.assertIsNone(report.candidate)
                self.assertEqual(handler.plan_calls, 0)
            finally:
                store.close()


    def test_reset_identity_allows_independent_next_occurrence(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SafetyStore(Path(folder) / "state.sqlite3")
            try:
                d = descriptor(); h = Handler(d); repo = SQLiteSchedulerInvocationRepository(store)
                coordinator = UtcPulseCoordinator(repo, [d], {d.flow_id: h}, activation_authority=Authority())
                self.assertIsNotNone(coordinator.pulse(facts("r1")).candidate)
                self.assertIsNone(coordinator.pulse(facts("r1", now=101)).candidate)
                self.assertIsNotNone(coordinator.pulse(facts("r2", now=102)).candidate)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
