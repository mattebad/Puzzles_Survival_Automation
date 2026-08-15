from __future__ import annotations

import json
from pathlib import Path
import unittest

from automation_service import (
    CostEffectVector,
    FamilyFacts,
    FlowDescriptor,
    NormalizedOutcome,
    NormalizedResult,
    PerceptionEnvelope,
    SchedulerFacts,
    SemanticActionIntent,
)
from automation_service.registry import ENTRY_FIELDS, load_disabled_registry
from scripts.pnsctl import BLUESTACKS_FLOW_IDS


ROOT = Path(__file__).resolve().parents[1]


class AutomationServiceContractTests(unittest.TestCase):
    def test_typed_contracts_preserve_separate_facts_and_cost_dimensions(self) -> None:
        descriptor = FlowDescriptor("flow", "owner", "family", "variant", "daily_once")
        facts = PerceptionEnvelope(
            "capture-1",
            "home_canonical",
            "profile",
            "fresh",
            family_facts=(FamilyFacts("campaign", True, {"destination": "1-20-9"}),),
        )
        cost = CostEffectVector(
            resource={"food": -10},
            currency={"premium": 0},
            ap=0,
            reserve={"food": 100},
            cap={"ap": 120},
        )
        intent = SemanticActionIntent(
            "navigate_campaign",
            "flow",
            "home_canonical",
            "campaign_destination_recognized",
            cost,
        )
        self.assertEqual(descriptor.family, "family")
        self.assertFalse(descriptor.scheduler_eligible)
        self.assertEqual(facts.facts_for("campaign").values["destination"], "1-20-9")
        self.assertEqual(intent.cost_effect.to_mapping()["resource"]["food"], -10)
        self.assertEqual(intent.action_key, "flow:navigate_campaign")

    def test_normalized_outcomes_have_scheduler_vocabulary(self) -> None:
        result = NormalizedResult(
            NormalizedOutcome.DEFERRED,
            "COOLDOWN",
            next_eligible_at=123.0,
        )
        self.assertEqual(result.outcome.value, "deferred")
        self.assertFalse(SchedulerFacts("a", "s", "r", 123.0).health_ok)
        self.assertEqual(
            SchedulerFacts("a", "s", "r", 123.0, health_ok=True).now_utc_epoch,
            123.0,
        )

    def test_unresolved_normalizes_to_global_block(self) -> None:
        result = NormalizedResult(NormalizedOutcome.UNRESOLVED, "UNKNOWN_RESULT")
        self.assertTrue(result.unresolved_action)

    def test_disabled_registry_owns_only_disabled_production_fields(self) -> None:
        entries = load_disabled_registry()
        self.assertTrue(entries)
        payload = json.loads(
            (ROOT / "tasks" / "flow_delivery_disabled_production_registry.json").read_text(
                encoding="utf-8"
            )
        )
        for value in payload["flows"].values():
            self.assertEqual(set(value), ENTRY_FIELDS)
        self.assertTrue(all(item.mode == "disabled" for item in entries))
        self.assertTrue(all(item.registration_status == "NOT_REGISTERED" for item in entries))
        self.assertTrue(all(item.scheduler_eligible is False for item in entries))
        self.assertEqual({item.flow_id for item in entries}, set(BLUESTACKS_FLOW_IDS))


if __name__ == "__main__":
    unittest.main()

