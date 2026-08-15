from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

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
from scripts.flow_delivery_campaign_bluestacks import (
    MAX_PROVING_CYCLES,
    PROVING_FLOW_ID,
    run_campaign_navigation_proving_slice,
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

    def test_dedicated_proving_flow_is_navigation_only_and_disabled(self) -> None:
        contract = json.loads(
            (
                ROOT
                / "tasks"
                / "gameplay_flow_contracts"
                / f"{PROVING_FLOW_ID}.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(contract["consequential_action_class"], "none_declared")
        self.assertEqual(contract["proof_state"], "evidence_required")
        self.assertFalse(contract["production_eligible"])
        self.assertFalse(contract["scheduler_eligibility"])
        self.assertNotIn("challenge", " ".join(contract["permitted_inputs"]).casefold())

    def test_proving_runner_rotates_destinations_and_enforces_ten_cycle_budget(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pnsctl = SimpleNamespace(
                BLUESTACKS_ARTIFACT_ROOT=root,
                OperatorError=RuntimeError,
            )
            with patch(
                "scripts.flow_delivery_campaign_bluestacks._pnsctl",
                return_value=pnsctl,
            ), patch(
                "scripts.flow_delivery_campaign_bluestacks._run_campaign_navigation_execution",
                return_value=json.dumps({"status": "completed"}),
            ) as run:
                run_campaign_navigation_proving_slice({}, {"owner": "test"})
                self.assertEqual(run.call_args.kwargs["destination"], "1-20-9")
                for ordinal in range(MAX_PROVING_CYCLES):
                    result = (
                        root
                        / PROVING_FLOW_ID
                        / f"run-{ordinal}"
                        / "flow-delivery-result.json"
                    )
                    result.parent.mkdir(parents=True, exist_ok=True)
                    result.write_text(
                        json.dumps({"flow_id": PROVING_FLOW_ID}),
                        encoding="utf-8",
                    )
                with self.assertRaisesRegex(RuntimeError, "budget is exhausted"):
                    run_campaign_navigation_proving_slice({}, {"owner": "test"})


if __name__ == "__main__":
    unittest.main()

