from __future__ import annotations

import unittest

from automation_service.contracts import FlowDescriptor, NormalizedOutcome, SchedulerFacts
from automation_service.handlers import DisabledHandler


class AutomationServiceHandlerTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

