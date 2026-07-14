from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.challenge_disabled import (
    ChallengeObservation,
    challenge_authorizeable,
    challenge_disabled_dispatch,
    challenge_postcondition_verified,
)
from tasks.contracts import TaskOutcome


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_disabled_challenge_observations.json"
MATRIX = ROOT / "tasks/daily_quest_execution_matrix.json"


def load_fixture(name: str) -> ChallengeObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return ChallengeObservation(**payload)


class DisabledChallengeContractTests(unittest.TestCase):
    def test_ruins_identity_and_entry_cost_are_required(self):
        observation = load_fixture("valid")
        self.assertTrue(challenge_authorizeable(observation))
        for changes in (
            {"challenge_identity": "ULTIMATE_CHALLENGE"},
            {"objective_key": "ultimate_challenge"},
            {"challenge_available": False},
            {"target_identity": "generic-entry"},
            {"entry_cost_known": False},
            {"entry_cost_ap": 101},
            {"ap_balance_before": 4},
            {"premium_entry": True},
        ):
            self.assertFalse(challenge_authorizeable(replace(observation, **changes)))

    def test_main_ultimate_and_ambiguous_states_fail_closed(self):
        observation = load_fixture("valid")
        self.assertFalse(challenge_authorizeable(load_fixture("main_negative")))
        for changes in (
            {"selected_daily_row": False},
            {"screen_state": "MAIN_QUEST"},
            {"target_provenance": "gnbots-reference"},
            {"overlay_state": "unknown"},
            {"reset_guard_active": True},
            {"recognized": False},
        ):
            self.assertFalse(challenge_authorizeable(replace(observation, **changes)))

    def test_result_successor_is_offline_identity_and_progress_replay_only(self):
        before = load_fixture("valid")
        after = replace(
            before,
            challenge_result_after="RESULT_RECONCILED",
            daily_progress_after=1,
            entry_confirmed=True,
            successor_state="CHALLENGE_RECONCILED",
        )
        self.assertTrue(challenge_postcondition_verified(before, after))
        self.assertFalse(
            challenge_postcondition_verified(
                before, replace(after, challenge_result_after="UNKNOWN")
            )
        )
        self.assertFalse(
            challenge_postcondition_verified(
                before, replace(after, challenge_identity="OTHER_CHALLENGE")
            )
        )
        self.assertFalse(
            challenge_postcondition_verified(
                before, replace(after, daily_progress_after=2)
            )
        )

    def test_disabled_policy_blocks_dispatch_and_keeps_claim_separate(self):
        result = challenge_disabled_dispatch(load_fixture("valid"))
        self.assertEqual(result.outcome, TaskOutcome.BLOCKED)
        self.assertEqual(result.reason, "CHALLENGE_DISABLED_POLICY")
        self.assertEqual(result.details["dispatch_count"], 0)
        self.assertIsNone(result.completion_key)

    def test_matrix_keeps_ruins_challenge_disabled_and_dormant(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        row = next(
            item
            for item in matrix["objectives"]
            if item["objective_key"] == "ruins_challenge"
        )
        self.assertEqual(row["implementation_status"], "DISABLED_POLICY")
        self.assertEqual(row["promotion_state"], "DISABLED_POLICY")
        self.assertEqual(row["current_runtime_registration_status"], "NOT_REGISTERED")
        self.assertFalse(row["scheduler_eligibility"])


if __name__ == "__main__":
    unittest.main()
