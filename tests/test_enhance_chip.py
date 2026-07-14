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


def load_chip() -> EnhancementObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"]["chip_variant_negative"]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return EnhancementObservation(**payload)


class ChipEnhancementContractTests(unittest.TestCase):
    def test_chip_variant_binds_chip_tab_and_action(self):
        observation = load_chip()
        self.assertTrue(enhancement_authorizeable(observation, variant="chip"))
        spec = enhancement_transaction_spec(observation, variant="chip")
        self.assertEqual(spec.action_kind, "ENHANCE_CHIP")
        self.assertEqual(spec.subject, "commander-chip-1")
        self.assertEqual(spec.resource_or_currency, "chip-material-one-star")

    def test_chip_cannot_claim_gear_ownership(self):
        observation = load_chip()
        self.assertFalse(enhancement_authorizeable(observation, variant="gear"))
        self.assertFalse(enhancement_authorizeable(observation, variant="module"))

    def test_chip_reuses_material_and_safety_guards(self):
        observation = load_chip()
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
                enhancement_authorizeable(replace(observation, **changes), variant="chip")
            )

    def test_chip_postcondition_requires_same_item_and_positive_change(self):
        before = load_chip()
        leveled = replace(before, item_level=5)
        self.assertTrue(
            enhancement_postcondition_verified(before, leveled, variant="chip")
        )
        self.assertFalse(
            enhancement_postcondition_verified(
                before, replace(leveled, selected_item_kind="GEAR"), variant="chip"
            )
        )
        self.assertFalse(
            enhancement_postcondition_verified(
                before, replace(leveled, game_day_id="next-day"), variant="chip"
            )
        )

    def test_chip_pulse_remains_pure_and_unregistered(self):
        before = load_chip()
        prepared = enhancement_perform_one_pulse(before, variant="chip")
        self.assertEqual(prepared.outcome, TaskOutcome.PROGRESS)
        done = enhancement_perform_one_pulse(
            before, replace(before, item_level=5), variant="chip"
        )
        self.assertEqual(done.outcome, TaskOutcome.DONE)
        self.assertEqual(
            done.completion_key,
            "enhancement:chip:commander-chip-1:completed",
        )


if __name__ == "__main__":
    unittest.main()
