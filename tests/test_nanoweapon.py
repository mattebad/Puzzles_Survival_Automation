from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.nanoweapon import (
    NanoweaponObservation,
    nanoweapon_authorizeable,
    nanoweapon_perform_one_pulse,
    nanoweapon_postcondition_verified,
    nanoweapon_transaction_spec,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_nanoweapon_observations.json"


def load_fixture(name: str) -> NanoweaponObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return NanoweaponObservation(**payload)


class NanoweaponContractTests(unittest.TestCase):
    def test_normal_craft_recipe_is_exact(self):
        observation = load_fixture("normal_craft_synthetic")
        self.assertTrue(nanoweapon_authorizeable(observation))
        spec = nanoweapon_transaction_spec(observation)
        self.assertEqual(spec.action_kind, "CRAFT_NANOWEAPON_NORMAL")
        self.assertEqual(spec.subject, "Nano Spear")
        self.assertFalse(spec.free_only)
        self.assertEqual(spec.maximum_cost, 100)
        self.assertEqual(spec.resource_or_currency, "NANO_PARTS")

    def test_material_production_and_static_reference_fail_closed(self):
        self.assertFalse(
            nanoweapon_authorizeable(load_fixture("material_production_negative"))
        )
        self.assertFalse(nanoweapon_authorizeable(load_fixture("static_reference_negative")))

    def test_recipe_material_target_and_policy_guards_are_required(self):
        observation = load_fixture("normal_craft_synthetic")
        for changes in (
            {"selected_tab": "INHERIT"},
            {"recipe_name": ""},
            {"recipe_known": False},
            {"materials_known": False},
            {"materials_available": False},
            {"nano_parts": 99},
            {"target_identity": "generic-craft"},
            {"target_roi": (10, 10, 100, 80)},
            {"duration_policy_approved": False},
            {"craft_duration_seconds": 21600},
            {"cost_type": "none"},
            {"cost_amount": 0},
            {"quantity": 10},
            {"overlay_state": "unknown"},
            {"reset_guard_active": True},
        ):
            self.assertFalse(nanoweapon_authorizeable(replace(observation, **changes)))

    def test_postcondition_requires_positive_result_same_day(self):
        before = load_fixture("normal_craft_synthetic")
        self.assertFalse(nanoweapon_postcondition_verified(before, before))
        result = replace(
            before,
            nano_parts=0,
            craft_result_visible=True,
            result_identity="nano-spear",
        )
        self.assertTrue(nanoweapon_postcondition_verified(before, result))
        counted = replace(before, nano_parts=0, craft_count=1)
        self.assertTrue(nanoweapon_postcondition_verified(before, counted))
        timer = replace(before, nano_parts=0, craft_timer_active=True)
        self.assertTrue(nanoweapon_postcondition_verified(before, timer))
        self.assertFalse(
            nanoweapon_postcondition_verified(
                before,
                replace(result, game_day_id="next-day"),
            )
        )

    def test_perform_one_pulse_is_pure_and_fail_safe(self):
        before = load_fixture("normal_craft_synthetic")
        prepared = nanoweapon_perform_one_pulse(before)
        self.assertEqual(prepared.outcome, TaskOutcome.PROGRESS)
        result = nanoweapon_perform_one_pulse(
            before,
            replace(before, nano_parts=0, craft_count=1),
        )
        self.assertEqual(result.outcome, TaskOutcome.DONE)
        self.assertEqual(result.completion_key, "nanoweapon:normal:completed")


if __name__ == "__main__":
    unittest.main()
