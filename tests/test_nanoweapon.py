from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest

from tasks.nanoweapon import (
    NanoweaponObservation,
    nanoweapon_authorizeable,
    nanoweapon_postcondition_verified,
    nanoweapon_transaction_spec,
)
from tests.support.observations import load_observation


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_nanoweapon_observations.json"


def load_fixture(name: str) -> NanoweaponObservation:
    return load_observation(
        FIXTURE, name, NanoweaponObservation,
        ("target_roi", "panel_bounds", "evidence_refs"),
    )


class NanoweaponContractTests(unittest.TestCase):
    def test_normal_craft_recipe_is_exact(self):
        observation = load_fixture("normal_craft_synthetic")
        self.assertTrue(nanoweapon_authorizeable(observation))
        spec = nanoweapon_transaction_spec(observation)
        self.assertFalse(spec.free_only)
        self.assertEqual(spec.quantity, 1)
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

    def test_active_successor_requires_exact_debit_timer_and_same_reset(self):
        before = replace(load_fixture("normal_craft_synthetic"), source_frame_sha256="a" * 64)
        active = replace(
            before, nano_parts=before.nano_parts - 100, active_craft_count=1,
            starts_this_reset=1, craft_timer_active=True, craft_timer_seconds_remaining=43199,
            craft_result_visible=False, claim_visible=False, source_frame_sha256="b" * 64,
        )
        self.assertTrue(nanoweapon_postcondition_verified(before, active))
        for changes in (
            {"nano_parts": before.nano_parts - 99},
            {"nano_parts": before.nano_parts - 101},
            {"active_craft_count": 0},
            {"active_craft_count": 2},
            {"starts_this_reset": 0},
            {"craft_timer_active": False},
            {"craft_timer_seconds_remaining": 0},
            {"craft_timer_seconds_remaining": 43201},
            {"craft_result_visible": True},
            {"claim_visible": True},
            {"source_frame_sha256": before.source_frame_sha256},
            {"game_day_id": "next-day"},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(nanoweapon_postcondition_verified(before, replace(active, **changes)))


if __name__ == "__main__":
    unittest.main()
