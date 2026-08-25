from __future__ import annotations

import unittest

from automation_service.contracts import (
    FlowDescriptor,
    NormalizedOutcome,
    PerceptionEnvelope,
    SchedulerFacts,
)
from automation_service.handlers import DisabledHandler, NovaPraiseSelectionHandler
from automation_service.registry import (
    NOVA_FLOW_ID,
    NOVA_HANDLER_ID,
    NOVA_PHASE_MODE,
    NOVA_PRODUCT_ID,
    NOVA_PRODUCT_REVISION,
    NOVA_PROFILE_ID,
    RegisteredDispatchSnapshot,
)


class AutomationServiceHandlerTests(unittest.TestCase):
    def _nova_facts(self, **overrides) -> SchedulerFacts:
        values = {
            "health_ok": True,
            "accepted_product": NOVA_PRODUCT_ID,
            "product_revision": NOVA_PRODUCT_REVISION,
            "registration_status": "REGISTERED",
            "scheduler_eligible": True,
            "owner_available": True,
            "clock_ok": True,
            "reset_agreement": True,
        }
        values.update(overrides)
        return SchedulerFacts("account", "server", "reset", 100.0, **values)

    def test_handler_protocol_surface_is_semantic_and_capability_specific(self) -> None:
        descriptor = FlowDescriptor("flow", "owner", "family", "variant", "daily_once")
        handler = DisabledHandler(descriptor)
        self.assertEqual(handler.describe(), descriptor)
        self.assertFalse(handler.eligibility(SchedulerFacts("a", "s", "r", 1.0)))
        self.assertEqual(handler.plan(SchedulerFacts("a", "s", "r", 1.0)), None)
        self.assertEqual(handler.reconcile(None).outcome, NormalizedOutcome.BLOCKED)
        self.assertEqual(handler.recover("UNKNOWN").outcome, NormalizedOutcome.BLOCKED)
        self.assertEqual(handler.summarize()["mode"], "disabled")

    def test_disabled_handler_cannot_become_scheduler_eligible(self) -> None:
        descriptor = FlowDescriptor(
            "flow",
            "owner",
            "family",
            "variant",
            "daily_once",
            scheduler_eligible=False,
        )
        handler = DisabledHandler(descriptor)
        self.assertFalse(handler.describe().scheduler_eligible)
        self.assertFalse(handler.eligibility(SchedulerFacts("a", "s", "r", 1.0)))

    def test_nova_handler_is_zero_transport_and_requires_parent_canary(self) -> None:
        handler = NovaPraiseSelectionHandler()
        descriptor = handler.describe()
        self.assertEqual(descriptor.flow_id, NOVA_FLOW_ID)
        self.assertEqual(descriptor.cadence, "daily_once_per_reset")
        self.assertEqual(descriptor.accepted_product, NOVA_PRODUCT_ID)
        self.assertEqual(descriptor.product_revision, NOVA_PRODUCT_REVISION)
        self.assertEqual(descriptor.registration_status, "REGISTERED")
        result = handler.plan(self._nova_facts())
        self.assertEqual(result.outcome, NormalizedOutcome.COMPLETE_FOR_RESET)
        self.assertEqual(result.reason_code, "NOVA_PRAISE_PARENT_CANARY_REQUIRED")
        self.assertEqual(result.action_count, 0)
        self.assertEqual(result.observed_progress["transport_count"], 0)
        self.assertEqual(
            result.observed_progress["registration_snapshot"],
            handler.snapshot.to_mapping(),
        )

    def test_nova_handler_fail_closes_product_owner_clock_reset_and_profile_mismatches(
        self,
    ) -> None:
        handler = NovaPraiseSelectionHandler()
        mismatches = (
            {"accepted_product": "world_map_navigation"},
            {"product_revision": "wrong-revision"},
            {"owner_available": False},
            {"clock_ok": False},
            {"clock_rollback": True},
            {"reset_agreement": False},
        )
        for overrides in mismatches:
            with self.subTest(overrides=overrides):
                self.assertFalse(handler.eligibility(self._nova_facts(**overrides)))
                self.assertEqual(
                    handler.plan(self._nova_facts(**overrides)).outcome,
                    NormalizedOutcome.BLOCKED,
                )
        perception = PerceptionEnvelope(
            "capture",
            "home",
            "wrong-profile",
            "fresh",
        )
        self.assertFalse(handler.eligibility(self._nova_facts(), perception))

    def test_nova_handler_rejects_non_nova_snapshot(self) -> None:
        with self.assertRaises(ValueError):
            RegisteredDispatchSnapshot(
                NOVA_FLOW_ID,
                NOVA_PRODUCT_ID,
                NOVA_PRODUCT_REVISION,
                "wrong-handler",
                NOVA_PROFILE_ID,
                NOVA_PHASE_MODE,
                "REGISTERED",
                True,
            )
        with self.assertRaises(TypeError):
            NovaPraiseSelectionHandler(object())


if __name__ == "__main__":
    unittest.main()

