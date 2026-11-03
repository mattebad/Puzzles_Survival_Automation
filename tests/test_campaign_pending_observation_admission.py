"""Offline admission tests: pending metadata never asserts game AP facts."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation_service.contracts import NormalizedOutcome, NormalizedResult, RecurrenceClass, RecurrenceProjection
from automation_service.handlers import CampaignApSelectionHandler
from automation_service.campaign import CampaignExecutionHandler
from automation_service.registry import CAMPAIGN_FLOW_ID, CANONICAL_FLOW_REGISTRY
from automation_service.scheduler import UtcPulseCoordinator
from tests.support.scheduler import initialize, make_descriptor, make_facts


def pending(**changes):
    values = dict(recurrence_class=RecurrenceClass.AP_REGENERATION,
                  observation_pending=True, generation="0")
    values.update(changes)
    return RecurrenceProjection(**values)


class PendingObservationTests(unittest.TestCase):
    def descriptor(self):
        return replace(make_descriptor(recurrence=pending()), reset_scoped=False,
                       allows_pending_resource_observation=True)

    def test_pending_carries_no_game_observation_and_rejects_invalid_shapes(self):
        projection = pending()
        self.assertIsNone(projection.observed_at_utc)
        self.assertIsNone(projection.observed_balance)
        for changes in ({"observation_pending": 1}, {"generation": " "},
                        {"generation": None}, {"observed_at_utc": 100},
                        {"observed_balance": 0},
                        {"recurrence_class": RecurrenceClass.STAMINA_REGENERATION},
                        {"next_eligible_at": float("nan")}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                pending(**changes)
        with self.assertRaises(ValueError):
            RecurrenceProjection(RecurrenceClass.AP_REGENERATION)
        for changes in ({"reset_scoped": True}, {"allows_pending_resource_observation": 1},
                        {"recurrence": RecurrenceProjection(RecurrenceClass.COOLDOWN, observed_at_utc=1)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(self.descriptor(), **changes)

    def test_registered_selector_stays_strict_execution_explicitly_admits_pending(self):
        entry = next(x for x in CANONICAL_FLOW_REGISTRY if x.flow_id == CAMPAIGN_FLOW_ID)
        facts = make_facts(accepted_product=entry.product_id, product_revision=entry.product_revision,
                           projections={CAMPAIGN_FLOW_ID: pending()})
        selector = CampaignApSelectionHandler(entry.registration)
        self.assertEqual(selector.minimum_observed_ap, 14)
        self.assertFalse(selector.eligibility(facts))
        executor = CampaignExecutionHandler(entry.registration, lambda *args: None)
        self.assertTrue(executor.eligibility(facts))
        self.assertFalse(executor.eligibility(replace(facts, health_ok=False)))
        self.assertFalse(executor.eligibility(replace(facts, owner_available=False)))

    def test_legacy_scheduler_rejects_pending_even_with_descriptor_optin(self):
        descriptor = self.descriptor()
        facts = make_facts(projections={descriptor.flow_id: pending()})
        self.assertFalse(UtcPulseCoordinator._recurrence_allows(descriptor, facts, 100))

    def test_canonical_matches_due_and_generation_then_claims_once(self):
        with tempfile.TemporaryDirectory() as root:
            descriptor = self.descriptor()
            state, coordinator, handler = initialize(Path(root) / "state.sqlite3", descriptor)
            with state:
                handler.result = NormalizedResult(NormalizedOutcome.DEFERRED, "OBSERVED",
                                                  verified=True, next_eligible_at=200)
                for projection in (pending(generation="1"), pending(next_eligible_at=99)):
                    self.assertIsNone(coordinator.pulse(make_facts(projections={descriptor.flow_id: projection})).candidate)
                report = coordinator.pulse(make_facts(projections={descriptor.flow_id: pending()}))
                self.assertIsNotNone(report.result)
                self.assertEqual(handler.plan_calls, 1)
                self.assertEqual(state.get_flow(descriptor.flow_id).next_occurrence_key, 1)
                self.assertIsNone(coordinator.pulse(make_facts(now=200, projections={descriptor.flow_id: pending()})).candidate)
                report = coordinator.pulse(make_facts(now=200, projections={descriptor.flow_id: pending(generation="1", next_eligible_at=200)}))
                self.assertIsNotNone(report.result)
                self.assertEqual(handler.plan_calls, 2)

    def test_schedule_change_after_selection_cannot_dispatch_stale_pending(self):
        with tempfile.TemporaryDirectory() as root:
            descriptor = self.descriptor()
            state, coordinator, handler = initialize(Path(root) / "state.sqlite3", descriptor)
            with state:
                canonical = coordinator._canonical
                original = canonical._prepare_claim
                def changed(*args, **kwargs):
                    state.update_schedule(descriptor.flow_id, next_occurrence_key=1)
                    return original(*args, **kwargs)
                with patch.object(canonical, "_prepare_claim", side_effect=changed):
                    report = coordinator.pulse(make_facts(projections={descriptor.flow_id: pending()}))
                self.assertIsNone(report.result)
                self.assertEqual(handler.plan_calls, 0)
                self.assertEqual(state.get_flow(descriptor.flow_id).next_occurrence_key, 1)


if __name__ == "__main__":
    unittest.main()
