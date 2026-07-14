from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.zombie_lair import (
    ZombieLairObservation,
    zombie_lair_authorizeable,
    zombie_lair_perform_one_pulse,
    zombie_lair_postcondition_verified,
    zombie_lair_transaction_spec,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_zombie_lair_observations.json"


def load_fixture(name: str) -> ZombieLairObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return ZombieLairObservation(**payload)


class ZombieLairContractTests(unittest.TestCase):
    def test_allowlisted_lair_join_binds_exact_target_and_stamina(self):
        observation = load_fixture("lair_synthetic")
        self.assertTrue(zombie_lair_authorizeable(observation))
        spec = zombie_lair_transaction_spec(observation)
        self.assertEqual(spec.action_kind, "JOIN_ZOMBIE_LAIR")
        self.assertEqual(spec.subject, "lair-level-1")
        self.assertEqual(spec.resource_or_currency, "STAMINA")
        self.assertEqual(spec.maximum_cost, 20)

    def test_level_60_main_and_static_states_fail_closed(self):
        self.assertFalse(zombie_lair_authorizeable(load_fixture("level_60_negative")))
        self.assertFalse(zombie_lair_authorizeable(load_fixture("main_negative")))
        self.assertFalse(
            zombie_lair_authorizeable(load_fixture("static_reference_negative"))
        )

    def test_target_march_and_budget_guards_are_required(self):
        observation = load_fixture("lair_synthetic")
        for changes in (
            {"lair_identity": "other-lair"},
            {"action_target_identity": "generic-join"},
            {"stamina_cost": 21},
            {"stamina_cost": 0},
            {"stamina_before": 19},
            {"stamina_budget": 19},
            {"march_slot_available": False},
            {"combat_mode_visible": True},
            {"overlay_state": "unknown"},
            {"target_roi": (10, 10, 100, 80)},
        ):
            self.assertFalse(zombie_lair_authorizeable(replace(observation, **changes)))

    def test_postcondition_requires_exact_lair_stamina_delta_and_result(self):
        before = load_fixture("lair_synthetic")
        after = replace(
            before,
            stamina_before=60,
            defeat_confirmed=True,
        )
        self.assertTrue(zombie_lair_postcondition_verified(before, after))
        self.assertFalse(
            zombie_lair_postcondition_verified(
                before, replace(after, stamina_before=59)
            )
        )
        self.assertFalse(
            zombie_lair_postcondition_verified(
                before, replace(after, lair_identity="other-lair")
            )
        )
        self.assertFalse(
            zombie_lair_postcondition_verified(
                before, replace(after, game_day_id="next-day")
            )
        )

    def test_one_pulse_is_pure_and_dormant(self):
        before = load_fixture("lair_synthetic")
        prepared = zombie_lair_perform_one_pulse(before)
        self.assertEqual(prepared.outcome, TaskOutcome.PROGRESS)
        done = zombie_lair_perform_one_pulse(
            before,
            replace(before, stamina_before=60, result_identity="lair-defeat-result"),
        )
        self.assertEqual(done.outcome, TaskOutcome.DONE)
        self.assertEqual(done.completion_key, "zombie-lair:lair-level-1:completed")


if __name__ == "__main__":
    unittest.main()
