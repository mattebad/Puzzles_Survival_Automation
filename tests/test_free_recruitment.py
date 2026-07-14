from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.free_recruitment import (
    FreeRecruitmentObservation,
    free_recruitment_authorizeable,
    free_recruitment_perform_one_pulse,
    free_recruitment_postcondition_verified,
    free_recruitment_transaction_spec,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_free_recruitment_observations.json"


def load_fixture(name: str) -> FreeRecruitmentObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return FreeRecruitmentObservation(**payload)


class FreeRecruitmentContractTests(unittest.TestCase):
    def test_free_single_mode_is_exact(self):
        observation = load_fixture("free_synthetic")
        self.assertTrue(free_recruitment_authorizeable(observation))
        spec = free_recruitment_transaction_spec(observation)
        self.assertEqual(spec.action_kind, "RECRUIT_FREE")
        self.assertTrue(spec.free_only)
        self.assertEqual(spec.maximum_cost, 0)

    def test_ten_x_and_static_reference_cases_fail_closed(self):
        self.assertFalse(free_recruitment_authorizeable(load_fixture("ten_x_negative")))
        self.assertFalse(free_recruitment_authorizeable(load_fixture("static_reference_negative")))

    def test_exact_free_banner_target_and_safety_guards_are_required(self):
        observation = load_fixture("free_synthetic")
        for changes in (
            {"target_identity": "generic-recruit"},
            {"target_roi": (10, 10, 100, 80)},
            {"free_banner_visible": False},
            {"free_available": False},
            {"recruitment_mode": "TEN_X"},
            {"cost_type": "tokens"},
            {"cost_amount": 1},
            {"quantity": 10},
            {"unknown_confirmation": True},
            {"overlay_state": "unknown"},
            {"reset_guard_active": True},
        ):
            self.assertFalse(free_recruitment_authorizeable(replace(observation, **changes)))

    def test_postcondition_requires_confirmed_result_or_count_increase(self):
        before = load_fixture("free_synthetic")
        self.assertFalse(free_recruitment_postcondition_verified(before, before))
        result = replace(before, recruitment_result_visible=True, result_identity="hero-result")
        self.assertTrue(free_recruitment_postcondition_verified(before, result))
        counted = replace(before, recruitment_count=1)
        self.assertTrue(free_recruitment_postcondition_verified(before, counted))
        self.assertFalse(free_recruitment_postcondition_verified(before, replace(result, game_day_id="next-day")))

    def test_perform_one_pulse_is_pure_and_fail_safe(self):
        before = load_fixture("free_synthetic")
        prepared = free_recruitment_perform_one_pulse(before)
        self.assertEqual(prepared.outcome, TaskOutcome.PROGRESS)
        result = free_recruitment_perform_one_pulse(before, replace(before, recruitment_count=1))
        self.assertEqual(result.outcome, TaskOutcome.DONE)
        self.assertEqual(result.completion_key, "recruitment:free:completed")


if __name__ == "__main__":
    unittest.main()
