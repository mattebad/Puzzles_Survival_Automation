from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.activity_milestones import (
    ActivityMilestoneObservation,
    activity_milestone_authorizeable,
    activity_milestone_perform_one_pulse,
    activity_milestone_postcondition_verified,
    activity_milestone_transaction_spec,
)
from tasks.contracts import TaskOutcome


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_activity_milestone_observations.json"


def load_fixture(name: str) -> ActivityMilestoneObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return ActivityMilestoneObservation(**payload)


class ActivityMilestoneContractTests(unittest.TestCase):
    def test_ready_chest_requires_exact_free_contract(self):
        observation = load_fixture("ready_synthetic")
        self.assertTrue(activity_milestone_authorizeable(observation))
        spec = activity_milestone_transaction_spec(observation)
        self.assertEqual(spec.action_kind, "CLAIM_ACTIVITY_MILESTONE")
        self.assertTrue(spec.free_only)
        self.assertEqual(spec.maximum_cost, 0)

    def test_not_ready_and_static_reference_cases_fail_closed(self):
        self.assertFalse(activity_milestone_authorizeable(load_fixture("not_ready_negative")))
        self.assertFalse(activity_milestone_authorizeable(load_fixture("static_reference_negative")))

    def test_exact_target_cost_panel_and_safety_guards_are_required(self):
        observation = load_fixture("ready_synthetic")
        for changes in (
            {"target_identity": "generic-chest"},
            {"target_roi": (10, 10, 100, 80)},
            {"cost_type": "gems"},
            {"cost_amount": 1},
            {"quantity": 10},
            {"selected_activity_milestones": False},
            {"overlay_state": "unknown"},
            {"reset_guard_active": True},
            {"game_day_id": None},
        ):
            self.assertFalse(activity_milestone_authorizeable(replace(observation, **changes)))

    def test_postcondition_requires_same_milestone_and_positive_change(self):
        before = load_fixture("ready_synthetic")
        self.assertFalse(activity_milestone_postcondition_verified(before, before))
        opened = replace(before, milestone_ready=False, control_class="", chest_fully_visible=False)
        self.assertTrue(activity_milestone_postcondition_verified(before, opened))
        self.assertTrue(activity_milestone_postcondition_verified(before, before, points_before=10, points_after=20))
        self.assertFalse(activity_milestone_postcondition_verified(before, replace(opened, milestone_key="other")))

    def test_perform_one_pulse_is_pure_and_fail_safe(self):
        before = load_fixture("ready_synthetic")
        prepared = activity_milestone_perform_one_pulse(before)
        self.assertEqual(prepared.outcome, TaskOutcome.PROGRESS)
        result = activity_milestone_perform_one_pulse(before, replace(before, milestone_ready=False), chest_opened=True)
        self.assertEqual(result.outcome, TaskOutcome.DONE)
        self.assertEqual(result.completion_key, "activity-milestone:activity-10:claimed")


if __name__ == "__main__":
    unittest.main()
