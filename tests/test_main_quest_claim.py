from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.main_quest import (
    MainQuestClaimObservation,
    main_claim_authorizeable,
    main_claim_perform_one_pulse,
    main_claim_postcondition_verified,
    main_claim_transaction_spec,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_main_claim_observations.json"


def load_fixture(name: str) -> MainQuestClaimObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["row_bounds"] = tuple(payload["row_bounds"])
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return MainQuestClaimObservation(**payload)


class MainQuestClaimContractTests(unittest.TestCase):
    def test_fixture_is_explicitly_evidence_gated(self):
        reference_only = load_fixture("reference_only_completed_claim")
        self.assertFalse(main_claim_authorizeable(reference_only))
        self.assertIn("local-reference", reference_only.evidence_refs[0])

    def test_go_negative_is_not_a_claim(self):
        self.assertFalse(main_claim_authorizeable(load_fixture("go_negative")))

    def test_synthetic_positive_contract_requires_bliss_native_metadata(self):
        observation = load_fixture("synthetic_contract_positive")
        self.assertTrue(main_claim_authorizeable(observation))
        spec = main_claim_transaction_spec(observation)
        self.assertEqual(spec.action_kind, "CLAIM_MAIN_QUEST")
        self.assertTrue(spec.free_only)
        self.assertEqual(spec.maximum_cost, 0)
        self.assertIn("bliss_native_target_evidence", spec.semantic_preconditions)

    def test_row_local_target_and_exact_provenance_are_required(self):
        observation = load_fixture("synthetic_contract_positive")
        for changes in (
            {"target_roi": (10, 10, 100, 80)},
            {"target_identity": "generic-claim"},
            {"target_provenance": "gnbots-reference"},
            {"runtime_profile_id": "wrong-profile"},
            {"source_frame_sha256": "bad"},
            {"evidence_refs": ()},
        ):
            self.assertFalse(main_claim_authorizeable(replace(observation, **changes)))

    def test_free_and_safe_guards_are_fail_closed(self):
        observation = load_fixture("synthetic_contract_positive")
        for changes in (
            {"milestone_reward": True},
            {"clipped": True},
            {"overlay_state": "unknown"},
            {"reset_guard_active": True},
            {"game_day_id": None},
            {"claim_fully_visible": False},
            {"current_progress": 0},
            {"cost_type": "gems"},
            {"cost_amount": 1},
            {"quantity": 10},
        ):
            self.assertFalse(main_claim_authorizeable(replace(observation, **changes)))

    def test_postcondition_requires_same_day_same_objective_and_change(self):
        before = load_fixture("synthetic_contract_positive")
        unchanged = before
        self.assertFalse(main_claim_postcondition_verified(before, unchanged))
        disappeared = replace(before, target_identity="", control_class="", claim_fully_visible=False)
        self.assertTrue(main_claim_postcondition_verified(before, disappeared, row_disappeared=True))
        self.assertTrue(main_claim_postcondition_verified(before, unchanged, points_before=5, points_after=6))
        self.assertFalse(main_claim_postcondition_verified(before, replace(disappeared, game_day_id="next-day"), row_disappeared=True))
        self.assertFalse(main_claim_postcondition_verified(before, replace(disappeared, objective_key="other"), row_disappeared=True))

    def test_perform_one_pulse_is_pure_and_fail_safe(self):
        denied = main_claim_perform_one_pulse(load_fixture("reference_only_completed_claim"))
        self.assertEqual(denied.outcome, TaskOutcome.BLOCKED)
        before = load_fixture("synthetic_contract_positive")
        prepared = main_claim_perform_one_pulse(before)
        self.assertEqual(prepared.outcome, TaskOutcome.PROGRESS)
        result = main_claim_perform_one_pulse(
            before,
            replace(before, target_identity="", control_class="", claim_fully_visible=False),
            row_disappeared=True,
        )
        self.assertEqual(result.outcome, TaskOutcome.DONE)
        self.assertEqual(result.completion_key, "main-quest:main-quest-3:claimed")


if __name__ == "__main__":
    unittest.main()
