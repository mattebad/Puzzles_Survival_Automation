from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.hero_upgrade_disabled import (
    HeroUpgradeObservation,
    hero_upgrade_authorizeable,
    hero_upgrade_disabled_dispatch,
    hero_upgrade_postcondition_verified,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_disabled_hero_upgrade_observations.json"
MATRIX = ROOT / "tasks/daily_quest_execution_matrix.json"


def load_fixture(name: str) -> HeroUpgradeObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return HeroUpgradeObservation(**payload)


class DisabledHeroUpgradeContractTests(unittest.TestCase):
    def test_selected_hero_and_material_identity_are_required(self):
        observation = load_fixture("valid")
        self.assertTrue(hero_upgrade_authorizeable(observation))
        for changes in (
            {"hero_identity": ""},
            {"hero_selected": False},
            {"target_identity": "hero-recruit"},
            {"material_known": False},
            {"material_balance": 99},
        ):
            self.assertFalse(hero_upgrade_authorizeable(replace(observation, **changes)))

    def test_main_and_ambiguous_source_states_fail_closed(self):
        observation = load_fixture("valid")
        self.assertFalse(hero_upgrade_authorizeable(load_fixture("main_negative")))
        for changes in (
            {"selected_daily_row": False},
            {"screen_state": "MAIN_QUEST"},
            {"target_provenance": "gnbots-reference"},
            {"overlay_state": "unknown"},
            {"reset_guard_active": True},
            {"recognized": False},
        ):
            self.assertFalse(hero_upgrade_authorizeable(replace(observation, **changes)))

    def test_level_successor_is_offline_arithmetic_only(self):
        before = load_fixture("valid")
        after = replace(
            before,
            current_level=11,
            target_level=12,
            hero_level_after=11,
            daily_progress_after=1,
            successor_state="HERO_LEVEL_RECONCILED",
        )
        self.assertTrue(hero_upgrade_postcondition_verified(before, after))
        self.assertFalse(
            hero_upgrade_postcondition_verified(
                before, replace(after, current_level=12)
            )
        )
        self.assertFalse(
            hero_upgrade_postcondition_verified(
                before, replace(after, hero_identity="hero-beta")
            )
        )
        self.assertFalse(
            hero_upgrade_postcondition_verified(
                before, replace(after, game_day_id="synthetic-day-2")
            )
        )

    def test_disabled_policy_blocks_dispatch_and_keeps_claim_separate(self):
        result = hero_upgrade_disabled_dispatch(load_fixture("valid"))
        self.assertEqual(result.outcome, TaskOutcome.BLOCKED)
        self.assertEqual(result.reason, "HERO_UPGRADE_DISABLED_POLICY")
        self.assertEqual(result.details["dispatch_count"], 0)
        self.assertIsNone(result.completion_key)

    def test_matrix_keeps_hero_upgrade_disabled_and_dormant(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        row = next(
            item
            for item in matrix["objectives"]
            if item["objective_key"] == "upgrade_hero"
        )
        self.assertEqual(row["implementation_status"], "DISABLED_POLICY")
        self.assertEqual(row["promotion_state"], "DISABLED_POLICY")
        self.assertEqual(row["current_runtime_registration_status"], "NOT_REGISTERED")
        self.assertFalse(row["scheduler_eligibility"])


if __name__ == "__main__":
    unittest.main()
