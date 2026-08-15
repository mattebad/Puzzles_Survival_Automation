from __future__ import annotations

import json
from pathlib import Path
import unittest

from automation_service.campaign import (
    FORBIDDEN_CAMPAIGN_INPUTS,
    CampaignNavigationHandler,
)
from automation_service.contracts import (
    FamilyFacts,
    NormalizedOutcome,
    PerceptionEnvelope,
    SchedulerFacts,
)


ROOT = Path(__file__).resolve().parents[1]


class AutomationServiceCampaignTests(unittest.TestCase):
    def test_handler_delegates_exact_destination_and_stays_navigation_only(self) -> None:
        handler = CampaignNavigationHandler("1-20-9")
        descriptor = handler.describe()
        self.assertEqual(descriptor.flow_id, "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION")
        self.assertEqual(descriptor.variant, "navigation_only")
        self.assertFalse(descriptor.scheduler_eligible)
        self.assertTrue(handler.eligibility(SchedulerFacts("a", "s", "r", 1.0, health_ok=True), PerceptionEnvelope(
            "c", "home_canonical", "profile", "fresh"
        )))
        plan = handler.plan(
            SchedulerFacts("a", "s", "r", 1.0, health_ok=True),
            PerceptionEnvelope(
                "c",
                "home_canonical",
                "profile",
                "fresh",
                family_facts=(FamilyFacts("campaign", True, {}),),
            ),
        )
        result = handler.reconcile(plan)
        self.assertEqual(result.outcome, NormalizedOutcome.BLOCKED)
        self.assertIn("EVIDENCE", result.reason_code)
        summary = handler.summarize()
        self.assertEqual(summary["transport_count"], 0)
        self.assertEqual(set(summary["forbidden_inputs"]), FORBIDDEN_CAMPAIGN_INPUTS)

    def test_campaign_parser_and_contract_forbid_sweep_blitz_auto_complete_and_refill(self) -> None:
        with self.assertRaises(ValueError):
            CampaignNavigationHandler("1-2-9")
        contract = json.loads(
            (
                ROOT
                / "tasks"
                / "gameplay_flow_contracts"
                / "CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY.json"
            ).read_text(encoding="utf-8")
        )
        scenario = next(
            item for item in contract["scenarios"] if item["scenario_id"] == "campaign_auto_battle_live"
        )
        self.assertTrue(FORBIDDEN_CAMPAIGN_INPUTS.isdisjoint(scenario["permitted_inputs"]))
        self.assertTrue(FORBIDDEN_CAMPAIGN_INPUTS <= set(scenario["forbidden_inputs"]))
        self.assertNotIn("repeat_until_ap_below_cost", contract["permitted_inputs"])
        self.assertTrue(
            FORBIDDEN_CAMPAIGN_INPUTS.isdisjoint(set(scenario["permitted_inputs"]))
        )

    def test_manual_or_forbidden_context_is_not_eligible(self) -> None:
        handler = CampaignNavigationHandler()
        facts = SchedulerFacts("a", "s", "r", 1.0, health_ok=True)
        forbidden = PerceptionEnvelope(
            "c",
            "home_canonical",
            "profile",
            "fresh",
            negative_evidence=("sweep",),
        )
        self.assertFalse(handler.eligibility(facts, forbidden))


if __name__ == "__main__":
    unittest.main()

