from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.bioenhancer import (
    BioenhancerObservation,
    bioenhancer_authorizeable,
    bioenhancer_perform_one_pulse,
    bioenhancer_postcondition_verified,
    bioenhancer_transaction_spec,
)
from tasks.contracts import TaskOutcome


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_bioenhancer_observations.json"


def load_fixture(name: str) -> BioenhancerObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return BioenhancerObservation(**payload)


class BioenhancerContractTests(unittest.TestCase):
    def test_free_single_research_is_exact(self):
        observation = load_fixture("free_synthetic")
        self.assertTrue(bioenhancer_authorizeable(observation))
        spec = bioenhancer_transaction_spec(observation)
        self.assertEqual(spec.action_kind, "RESEARCH_BIOENHANCER_FREE")
        self.assertTrue(spec.free_only)
        self.assertEqual(spec.maximum_cost, 0)

    def test_paid_and_static_reference_cases_fail_closed(self):
        self.assertFalse(bioenhancer_authorizeable(load_fixture("paid_negative")))
        self.assertFalse(bioenhancer_authorizeable(load_fixture("static_reference_negative")))

    def test_exact_free_target_and_safety_guards_are_required(self):
        observation = load_fixture("free_synthetic")
        for changes in (
            {"target_identity": "generic-research"},
            {"target_roi": (10, 10, 100, 80)},
            {"free_banner_visible": False},
            {"free_available": False},
            {"research_mode": "TEN_X"},
            {"research_ready": False},
            {"cost_type": "materials"},
            {"cost_amount": 1},
            {"quantity": 10},
            {"overlay_state": "unknown"},
            {"reset_guard_active": True},
        ):
            self.assertFalse(bioenhancer_authorizeable(replace(observation, **changes)))

    def test_postcondition_requires_positive_result_same_day(self):
        before = load_fixture("free_synthetic")
        self.assertFalse(bioenhancer_postcondition_verified(before, before))
        result = replace(before, research_result_visible=True, result_identity="bioenhancer-result")
        self.assertTrue(bioenhancer_postcondition_verified(before, result))
        counted = replace(before, research_count=1)
        self.assertTrue(bioenhancer_postcondition_verified(before, counted))
        cooldown = replace(before, cooldown_active=True)
        self.assertTrue(bioenhancer_postcondition_verified(before, cooldown))
        self.assertFalse(
            bioenhancer_postcondition_verified(before, replace(result, game_day_id="next-day"))
        )

    def test_perform_one_pulse_is_pure_and_fail_safe(self):
        before = load_fixture("free_synthetic")
        prepared = bioenhancer_perform_one_pulse(before)
        self.assertEqual(prepared.outcome, TaskOutcome.PROGRESS)
        result = bioenhancer_perform_one_pulse(before, replace(before, research_count=1))
        self.assertEqual(result.outcome, TaskOutcome.DONE)
        self.assertEqual(result.completion_key, "bioenhancer:free:completed")


if __name__ == "__main__":
    unittest.main()
