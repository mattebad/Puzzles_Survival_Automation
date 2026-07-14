from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.donation_disabled import (
    DonationObservation,
    donation_authorizeable,
    donation_disabled_dispatch,
    donation_postcondition_verified,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_disabled_donation_observations.json"
MATRIX = ROOT / "tasks/daily_quest_execution_matrix.json"


def load_fixture(name: str) -> DonationObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return DonationObservation(**payload)


class DisabledDonationContractTests(unittest.TestCase):
    def test_tech_target_and_resource_model_are_required(self):
        observation = load_fixture("valid")
        self.assertTrue(donation_authorizeable(observation))
        for changes in (
            {"tech_identity": ""},
            {"target_identity": "alliance-tech-row"},
            {"resource_identity": ""},
            {"resource_known": False},
            {"donation_amount": 101},
            {"resource_balance_before": 9},
            {"donation_count_before": 1},
        ):
            self.assertFalse(donation_authorizeable(replace(observation, **changes)))

    def test_main_and_ambiguous_source_states_fail_closed(self):
        observation = load_fixture("valid")
        self.assertFalse(donation_authorizeable(load_fixture("main_negative")))
        for changes in (
            {"selected_daily_row": False},
            {"screen_state": "MAIN_QUEST"},
            {"target_provenance": "gnbots-reference"},
            {"overlay_state": "unknown"},
            {"reset_guard_active": True},
            {"recognized": False},
        ):
            self.assertFalse(donation_authorizeable(replace(observation, **changes)))

    def test_donation_successor_is_offline_resource_and_progress_arithmetic_only(self):
        before = load_fixture("valid")
        after = replace(
            before,
            resource_balance_after=90,
            donation_count_after=1,
            daily_progress_after=1,
            donation_confirmed=True,
            successor_state="DONATION_RECONCILED",
        )
        self.assertTrue(donation_postcondition_verified(before, after))
        self.assertFalse(
            donation_postcondition_verified(
                before, replace(after, resource_balance_after=89)
            )
        )
        self.assertFalse(
            donation_postcondition_verified(
                before, replace(after, tech_identity="other-tech")
            )
        )
        self.assertFalse(
            donation_postcondition_verified(
                before, replace(after, daily_progress_after=2)
            )
        )

    def test_disabled_policy_blocks_dispatch_and_keeps_claim_separate(self):
        result = donation_disabled_dispatch(load_fixture("valid"))
        self.assertEqual(result.outcome, TaskOutcome.BLOCKED)
        self.assertEqual(result.reason, "DONATION_DISABLED_POLICY")
        self.assertEqual(result.details["dispatch_count"], 0)
        self.assertIsNone(result.completion_key)

    def test_matrix_keeps_donation_disabled_and_dormant(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        row = next(
            item
            for item in matrix["objectives"]
            if item["objective_key"] == "donate_alliance_tech"
        )
        self.assertEqual(row["implementation_status"], "DISABLED_POLICY")
        self.assertEqual(row["promotion_state"], "DISABLED_POLICY")
        self.assertEqual(row["current_runtime_registration_status"], "NOT_REGISTERED")
        self.assertFalse(row["scheduler_eligibility"])


if __name__ == "__main__":
    unittest.main()
