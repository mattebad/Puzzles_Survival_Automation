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


def load_fixture(name: str) -> EnhancementObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return EnhancementObservation(**payload)


class EnhancementFamilyContractTests(unittest.TestCase):
    def test_gear_variant_uses_exact_one_star_material(self):
        observation = load_fixture("gear_synthetic")
        self.assertTrue(enhancement_authorizeable(observation, variant="gear"))
        spec = enhancement_transaction_spec(observation, variant="gear")
        self.assertEqual(spec.action_kind, "ENHANCE_GEAR")
        self.assertEqual(spec.subject, "commander-gear-1")
        self.assertEqual(spec.resource_or_currency, "gear-material-one-star")
        self.assertFalse(spec.free_only)

    def test_family_ownership_and_main_negative_fail_closed(self):
        self.assertFalse(
            enhancement_authorizeable(load_fixture("chip_variant_negative"), variant="gear")
        )
        self.assertTrue(
            enhancement_authorizeable(load_fixture("chip_variant_negative"), variant="chip")
        )
        self.assertFalse(
            enhancement_authorizeable(load_fixture("main_negative"), variant="gear")
        )

    def test_material_target_and_safety_guards_are_required(self):
        observation = load_fixture("gear_synthetic")
        for changes in (
            {"selected_tab": "CHIP"},
            {"selected_item_kind": "CHIP"},
            {"item_equipped": False},
            {"target_identity": "generic-enhance"},
            {"target_roi": (10, 10, 100, 80)},
            {"enhance_control_visible": False},
            {"action_mode": "PROMOTE"},
            {"material_known": False},
            {"material_available": False},
            {"material_star": 2},
            {"material_quantity": 10},
            {"auto_select_enabled": True},
            {"cost_type": "gems"},
            {"quantity": 10},
            {"overlay_state": "unknown"},
            {"reset_guard_active": True},
        ):
            self.assertFalse(enhancement_authorizeable(replace(observation, **changes)))

    def test_postcondition_requires_same_item_positive_change(self):
        before = load_fixture("gear_synthetic")
        self.assertFalse(
            enhancement_postcondition_verified(before, before, variant="gear")
        )
        leveled = replace(before, item_level=5)
        self.assertTrue(
            enhancement_postcondition_verified(before, leveled, variant="gear")
        )
        consumed = replace(before, material_inventory_count=9)
        self.assertTrue(
            enhancement_postcondition_verified(before, consumed, variant="gear")
        )
        self.assertFalse(
            enhancement_postcondition_verified(
                before, replace(leveled, selected_item_identity="other-gear"), variant="gear"
            )
        )
        self.assertFalse(
            enhancement_postcondition_verified(
                before, replace(leveled, game_day_id="next-day"), variant="gear"
            )
        )

    def test_perform_one_pulse_is_pure_and_fail_safe(self):
        before = load_fixture("gear_synthetic")
        prepared = enhancement_perform_one_pulse(before, variant="gear")
        self.assertEqual(prepared.outcome, TaskOutcome.PROGRESS)
        result = enhancement_perform_one_pulse(
            before, replace(before, item_level=5), variant="gear"
        )
        self.assertEqual(result.outcome, TaskOutcome.DONE)
        self.assertEqual(
            result.completion_key,
            "enhancement:gear:commander-gear-1:completed",
        )


if __name__ == "__main__":
    unittest.main()
