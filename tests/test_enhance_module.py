from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.enhancement import (
    EnhancementObservation,
    enhancement_authorizeable,
    enhancement_perform_one_pulse,
    enhancement_postcondition_verified,
    enhancement_transaction_spec,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_enhancement_observations.json"


def load_module() -> EnhancementObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"]["module_variant"]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return EnhancementObservation(**payload)


class ModuleEnhancementContractTests(unittest.TestCase):
    def test_module_variant_binds_module_tab_and_action(self):
        observation = load_module()
        self.assertTrue(enhancement_authorizeable(observation, variant="module"))
        spec = enhancement_transaction_spec(observation, variant="module")
        self.assertEqual(spec.action_kind, "ENHANCE_MODULE")
        self.assertEqual(spec.subject, "commander-module-1")
        self.assertEqual(spec.resource_or_currency, "module-material-one-star")

    def test_module_cannot_claim_gear_or_chip_ownership(self):
        observation = load_module()
        self.assertFalse(enhancement_authorizeable(observation, variant="gear"))
        self.assertFalse(enhancement_authorizeable(observation, variant="chip"))

    def test_module_reuses_cost_and_target_guards(self):
        observation = load_module()
        for changes in (
            {"material_star": 2},
            {"material_quantity": 2},
            {"auto_select_enabled": True},
            {"material_available": False},
            {"cost_type": "premium"},
            {"target_identity": "generic-enhance"},
            {"overlay_state": "unknown"},
        ):
            self.assertFalse(
                enhancement_authorizeable(replace(observation, **changes), variant="module")
            )

    def test_module_postcondition_requires_same_item_and_positive_change(self):
        before = load_module()
        leveled = replace(before, item_level=5)
        self.assertTrue(
            enhancement_postcondition_verified(before, leveled, variant="module")
        )
        self.assertFalse(
            enhancement_postcondition_verified(
                before, replace(leveled, selected_item_kind="CHIP"), variant="module"
            )
        )
        self.assertFalse(
            enhancement_postcondition_verified(
                before, replace(leveled, game_day_id="next-day"), variant="module"
            )
        )

    def test_module_pulse_is_pure_and_dormant(self):
        before = load_module()
        prepared = enhancement_perform_one_pulse(before, variant="module")
        self.assertEqual(prepared.outcome, TaskOutcome.PROGRESS)
        done = enhancement_perform_one_pulse(
            before, replace(before, item_level=5), variant="module"
        )
        self.assertEqual(done.outcome, TaskOutcome.DONE)
        self.assertEqual(
            done.completion_key,
            "enhancement:module:commander-module-1:completed",
        )


if __name__ == "__main__":
    unittest.main()
