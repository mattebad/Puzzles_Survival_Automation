from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.hero_duel_disabled import (
    HeroDuelObservation,
    hero_duel_authorizeable,
    hero_duel_disabled_dispatch,
    hero_duel_postcondition_verified,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_disabled_hero_duel_observations.json"
MATRIX = ROOT / "tasks/daily_quest_execution_matrix.json"


def load_fixture(name: str) -> HeroDuelObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return HeroDuelObservation(**payload)


class DisabledHeroDuelContractTests(unittest.TestCase):
    def test_event_identity_and_join_target_are_exact(self):
        observation = load_fixture("valid")
        self.assertTrue(hero_duel_authorizeable(observation))
        for changes in (
            {"event_identity": ""},
            {"event_active": False},
            {"target_identity": "hero-duel-attack"},
            {"control_class": "ATTACK"},
            {"join_control_visible": False},
            {"attempts_remaining": 0},
        ):
            self.assertFalse(hero_duel_authorizeable(replace(observation, **changes)))

    def test_main_static_and_ambiguous_states_fail_closed(self):
        observation = load_fixture("valid")
        self.assertFalse(hero_duel_authorizeable(load_fixture("main_negative")))
        for changes in (
            {"selected_daily_row": False},
            {"screen_state": "MAIN_QUEST"},
            {"overlay_state": "unknown"},
            {"reset_guard_active": True},
            {"target_provenance": "gnbots-reference"},
            {"recognized": False},
        ):
            self.assertFalse(hero_duel_authorizeable(replace(observation, **changes)))

    def test_participation_successor_is_offline_only(self):
        before = load_fixture("valid")
        after = replace(
            before,
            daily_progress_after=1,
            participation_confirmed=True,
            successor_state="PARTICIPATION_RECONCILED",
        )
        self.assertTrue(hero_duel_postcondition_verified(before, after))
        self.assertFalse(
            hero_duel_postcondition_verified(
                before, replace(after, daily_progress_after=2)
            )
        )
        self.assertFalse(
            hero_duel_postcondition_verified(
                before, replace(after, event_identity="hero-duel-event-2")
            )
        )
        self.assertFalse(
            hero_duel_postcondition_verified(
                before, replace(after, participation_confirmed=False)
            )
        )

    def test_disabled_policy_blocks_dispatch_and_keeps_claim_separate(self):
        result = hero_duel_disabled_dispatch(load_fixture("valid"))
        self.assertEqual(result.outcome, TaskOutcome.BLOCKED)
        self.assertEqual(result.reason, "HERO_DUEL_DISABLED_POLICY")
        self.assertEqual(result.details["dispatch_count"], 0)
        self.assertIsNone(result.completion_key)

    def test_matrix_keeps_duel_disabled_and_dormant(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        row = next(
            item
            for item in matrix["objectives"]
            if item["objective_key"] == "join_hero_duel"
        )
        self.assertEqual(row["implementation_status"], "DISABLED_POLICY")
        self.assertEqual(row["promotion_state"], "DISABLED_POLICY")
        self.assertEqual(row["current_runtime_registration_status"], "NOT_REGISTERED")
        self.assertFalse(row["scheduler_eligibility"])


if __name__ == "__main__":
    unittest.main()
