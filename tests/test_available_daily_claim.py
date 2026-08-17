from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.available_daily_claim import (
    AvailableDailyClaimObservation,
    available_daily_claim_authorizeable,
    available_daily_claim_perform_one_pulse,
    available_daily_claim_postcondition_verified,
    available_daily_claim_transaction_spec,
)
from tasks.contracts import TaskOutcome


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_daily_claim_observations.json"


def load_fixture(name: str) -> AvailableDailyClaimObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["row_bounds"] = tuple(payload["row_bounds"])
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return AvailableDailyClaimObservation(**payload)


class AvailableDailyClaimContractTests(unittest.TestCase):
    @staticmethod
    def bluestacks_observation(**changes) -> AvailableDailyClaimObservation:
        values = dict(
            screen_state="DAILY_QUEST",
            selected_daily_quest=True,
            objective_key="consume_stamina",
            objective_name="Consume 20 Stamina",
            current_progress=36,
            required_progress=20,
            row_bounds=(90, 400, 710, 570),
            target_identity="daily-quest-claim",
            target_roi=(600, 460, 690, 520),
            control_class="CLAIM",
            row_fully_visible=True,
            claim_fully_visible=True,
            cost_type="none",
            cost_amount=0,
            quantity=1,
            game_day_id="bluestacks-day-2026-08-16",
            target_provenance="bluestacks-native",
            source_frame_sha256="a" * 64,
            evidence_refs=("runtime/frames/0001-daily.png",),
            milestone_reward=False,
            clipped=False,
            overlay_state="none",
            reset_guard_active=False,
            runtime_profile_id="pns-bluestacks-5-p64-800x1280-v1",
            recognized=True,
            points=0,
            reward_points=5,
            reset_timer="04:00:00",
            catalog_reconciled=False,
            ordinary_reward_claim=True,
            free_control_proven=True,
            quantity_one_proven=True,
            cost_region_scan={
                "attached_cost": False,
                "numeric_only_cost": False,
                "icon_only_cost": False,
                "currency_icon": False,
                "currency_amount": False,
            },
            row_panel_proven=True,
            row_panel_source="independent-test-panel",
            reset_timer_seconds=14400,
            reset_observed_utc="2026-08-16T00:00:00Z",
            reset_deadline_utc="2026-08-16T04:00:00Z",
            reset_deadline_identity="bluestacks-day-2026-08-16",
            reset_deadline_tolerance_seconds=2,
        )
        values.update(changes)
        return AvailableDailyClaimObservation(**values)

    def test_bluestacks_native_completed_row_accepts_overcompletion_and_catalog_reconciliation(self):
        observation = self.bluestacks_observation()

        self.assertTrue(available_daily_claim_authorizeable(observation))
        self.assertEqual(observation.current_progress, 36)
        self.assertEqual(observation.required_progress, 20)
        spec = available_daily_claim_transaction_spec(observation)
        self.assertEqual(spec.subject, "Consume 20 Stamina")
        self.assertIn("accepted_native_target_evidence", spec.semantic_preconditions)

    def test_bluestacks_live_evidence_rejects_synthetic_identity_and_uncatalogued_objective(self):
        observation = self.bluestacks_observation()
        for changes in (
            {"evidence_refs": ("synthetic:daily-row",)},
            {"target_provenance": "bliss-native"},
            {"runtime_profile_id": "pns-blissos-poc-virgl-800x1280-v1"},
            {"objective_key": "invented_objective", "objective_name": "Invented Objective"},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(
                    available_daily_claim_authorizeable(replace(observation, **changes))
                )

    def test_bluestacks_claim_rejects_target_row_and_free_action_negatives(self):
        observation = self.bluestacks_observation()
        for changes in (
            {"row_bounds": (90, 400, 500, 570)},
            {"target_roi": (720, 460, 790, 520)},
            {"target_identity": "daily-quest-go", "control_class": "GO"},
            {"milestone_reward": True},
            {"cost_type": "gems"},
            {"cost_type": "unknown"},
            {"cost_amount": 1},
            {"quantity": 2},
            {"ordinary_reward_claim": False},
            {"free_control_proven": False},
            {"quantity_one_proven": False},
            {
                "cost_region_scan": {
                    "attached_cost": True,
                    "currency_icon": True,
                }
            },
            {"row_panel_proven": False},
            {"overlay_state": "unknown"},
            {"reset_guard_active": True},
            {"reset_deadline_identity": "reset-deadline:other"},
            {"reset_timer_seconds": None},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(
                    available_daily_claim_authorizeable(replace(observation, **changes))
                )

    def test_postcondition_requires_same_objective_and_game_day_with_row_or_positive_points_change(self):
        before = self.bluestacks_observation()
        row_changed = replace(
            before,
            target_identity="",
            control_class="",
            claim_fully_visible=False,
        )
        self.assertTrue(
            available_daily_claim_postcondition_verified(
                before, row_changed, row_disappeared=True
            )
        )
        self.assertTrue(
            available_daily_claim_postcondition_verified(
                before,
                before,
                points_before=0,
                points_after=1,
            )
        )
        self.assertFalse(
            available_daily_claim_postcondition_verified(
                before,
                before,
                points_before=0,
                points_after=0,
            )
        )
        self.assertFalse(
            available_daily_claim_postcondition_verified(
                before,
                replace(row_changed, objective_key="other"),
                row_disappeared=True,
            )
        )
        self.assertFalse(
            available_daily_claim_postcondition_verified(
                before,
                replace(row_changed, game_day_id="different-day"),
                row_disappeared=True,
            )
        )

    def test_generalized_contract_does_not_require_personal_might_catalog_alias(self):
        observation = load_fixture("generalized_contract_positive")
        self.assertEqual(observation.objective_key, "gather_food")
        self.assertTrue(available_daily_claim_authorizeable(observation))
        spec = available_daily_claim_transaction_spec(observation)
        self.assertEqual(spec.action_kind, "CLAIM_DAILY_QUEST")
        self.assertEqual(spec.subject, "Gather Food")
        self.assertTrue(spec.free_only)

    def test_go_and_static_reference_cases_fail_closed(self):
        self.assertFalse(available_daily_claim_authorizeable(load_fixture("go_negative")))
        self.assertFalse(available_daily_claim_authorizeable(load_fixture("static_reference_negative")))

    def test_exact_target_cost_and_visibility_guards_are_required(self):
        observation = load_fixture("generalized_contract_positive")
        for changes in (
            {"selected_daily_quest": False},
            {"target_identity": "generic-claim"},
            {"target_roi": (10, 10, 100, 80)},
            {"cost_type": "gems"},
            {"cost_amount": 1},
            {"quantity": 10},
            {"milestone_reward": True},
            {"clipped": True},
            {"overlay_state": "unknown"},
            {"reset_guard_active": True},
            {"game_day_id": None},
        ):
            self.assertFalse(available_daily_claim_authorizeable(replace(observation, **changes)))

    def test_postcondition_requires_same_objective_and_positive_change(self):
        before = load_fixture("generalized_contract_positive")
        self.assertFalse(available_daily_claim_postcondition_verified(before, before))
        disappeared = replace(before, target_identity="", control_class="", claim_fully_visible=False)
        self.assertTrue(available_daily_claim_postcondition_verified(before, disappeared, row_disappeared=True))
        self.assertTrue(available_daily_claim_postcondition_verified(before, before, points_before=5, points_after=6))
        self.assertFalse(available_daily_claim_postcondition_verified(before, replace(disappeared, objective_key="other"), row_disappeared=True))

    def test_perform_one_pulse_is_pure_and_does_not_dispatch(self):
        before = load_fixture("generalized_contract_positive")
        prepared = available_daily_claim_perform_one_pulse(before)
        self.assertEqual(prepared.outcome, TaskOutcome.PROGRESS)
        result = available_daily_claim_perform_one_pulse(
            before,
            replace(before, target_identity="", control_class="", claim_fully_visible=False),
            row_disappeared=True,
        )
        self.assertEqual(result.outcome, TaskOutcome.DONE)
        self.assertEqual(result.completion_key, "daily-quest:gather_food:claimed")


if __name__ == "__main__":
    unittest.main()
