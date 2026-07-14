from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from safe_action_core import ActionClass, CentralPolicy, Observation, PolicyRequest, SafetyStore, TransportResult
from safe_action_core.models import ActionStatus
from safe_action_core.executor import SafeActionExecutor
from tasks.contracts import TaskOutcome
from tasks.daily_quest import (
    DailyQuestClaimObservation,
    PersonalMightPraiseHandler,
    PraiseObservation,
    PRAISE_NAVIGATION_BY_NAME,
    claim_authorizeable,
    claim_postcondition_verified,
)
from tasks.profile import MIGHT_PRAISE_ACTION, PERSONAL_MIGHT_ROW


class PraiseContractTests(unittest.TestCase):
    def praise(self, **changes):
        base = PraiseObservation(
            screen_state="PERSONAL_MIGHT_LEADERBOARD",
            objective_name="Praise 1x in Personal Might rank",
            current_progress=0,
            required_progress=1,
            target_identity=MIGHT_PRAISE_ACTION.name,
            target_roi=MIGHT_PRAISE_ACTION.roi,
            leaderboard_identity=True,
            might_region_identity=True,
            target_visible=True,
            zero_cost_evidence=True,
            game_day_id="daily-2026-07-13",
        )
        return replace(base, **changes)

    def claim(self, **changes):
        base = DailyQuestClaimObservation(
            screen_state="DAILY_QUEST",
            selected_daily_quest=True,
            objective_name="Personal Might praise",
            current_progress=1,
            required_progress=1,
            row_bounds=(0, 500, 800, 620),
            target_identity="daily-quest-claim",
            target_roi=(550, 520, 730, 590),
            control_class="CLAIM",
            row_fully_visible=True,
            claim_fully_visible=True,
            game_day_id="daily-2026-07-13",
        )
        return replace(base, **changes)

    def test_catalog_alias_and_progress_match(self):
        self.assertTrue(PersonalMightPraiseHandler.matches_objective("  personal   might praise "))
        self.assertEqual(PersonalMightPraiseHandler.parse_progress("Praise 1x in Personal Might rank 0/1"), (0, 1))

    def test_exact_might_target_and_zero_cost_are_required(self):
        self.assertTrue(PersonalMightPraiseHandler.authorizeable(self.praise()))
        self.assertFalse(PersonalMightPraiseHandler.authorizeable(self.praise(might_region_identity=False)))
        self.assertFalse(PersonalMightPraiseHandler.authorizeable(self.praise(target_identity="generic-thumb")))
        self.assertFalse(PersonalMightPraiseHandler.authorizeable(self.praise(zero_cost_evidence=False)))

    def test_already_praised_cooldown_blocks_without_input(self):
        for changes in ({"already_praised": True}, {"cooldown_active": True}):
            result = PersonalMightPraiseHandler.perform_one_pulse(self.praise(**changes))
            self.assertEqual(result.outcome, TaskOutcome.BLOCKED)
            self.assertIn("ALREADY_PRAISED", result.reason)

    def test_praise_postcondition_and_progress_until_claim(self):
        before = self.praise()
        after = self.praise(target_identity="", target_visible=False, praise_disabled=True)
        self.assertTrue(PersonalMightPraiseHandler.postcondition_verified(before, after))
        result = PersonalMightPraiseHandler.perform_one_pulse(before, after)
        self.assertEqual(result.outcome, TaskOutcome.PROGRESS)
        self.assertFalse(PersonalMightPraiseHandler.completion_check(after))

    def test_ambiguous_postcondition_is_not_done(self):
        result = PersonalMightPraiseHandler.perform_one_pulse(self.praise(), self.praise())
        self.assertEqual(result.outcome, TaskOutcome.FAILED_SAFE)
        self.assertEqual(result.reason, "PRAISE_POSTCONDITION_NOT_PROVEN")

    def test_named_route_has_required_steps_and_no_blind_back_pair(self):
        self.assertEqual(
            tuple(PRAISE_NAVIGATION_BY_NAME),
            (
                "home_to_more",
                "more_to_rankings",
                "personal_might_check_to_leaderboard",
                "personal_might_praise",
                "personal_might_back_to_rankings",
                "rankings_back_to_home",
            ),
        )
        self.assertFalse(PRAISE_NAVIGATION_BY_NAME["personal_might_praise"].allow_one_safe_retry)
        self.assertEqual(
            PRAISE_NAVIGATION_BY_NAME["personal_might_check_to_leaderboard"].source_state,
            "RANKINGS",
        )
        self.assertEqual(PRAISE_NAVIGATION_BY_NAME["personal_might_back_to_rankings"].expected_successors, ("RANKINGS",))
        self.assertEqual(PRAISE_NAVIGATION_BY_NAME["rankings_back_to_home"].expected_successors, ("HOME_BASE", "MORE"))
        self.assertIsNotNone(PRAISE_NAVIGATION_BY_NAME["personal_might_back_to_rankings"].source_anchor)
        self.assertIsNotNone(PRAISE_NAVIGATION_BY_NAME["rankings_back_to_home"].source_anchor)

    def test_claim_requires_selected_exact_completed_row(self):
        self.assertTrue(claim_authorizeable(self.claim()))
        self.assertFalse(claim_authorizeable(self.claim(selected_daily_quest=False)))
        self.assertFalse(claim_authorizeable(self.claim(objective_name="Gather Food")))
        self.assertFalse(claim_authorizeable(self.claim(current_progress=0)))
        self.assertFalse(claim_authorizeable(self.claim(control_class="GO")))
        self.assertFalse(claim_authorizeable(self.claim(milestone_reward=True)))
        self.assertFalse(claim_authorizeable(self.claim(clipped=True)))

    def test_claim_rejects_adjacent_or_unidentified_control(self):
        self.assertFalse(claim_authorizeable(self.claim(target_roi=(20, 20, 100, 80))))
        self.assertFalse(claim_authorizeable(self.claim(target_identity="adjacent-row-claim")))

    def test_claim_postcondition_requires_row_change_or_points(self):
        before = self.claim()
        unchanged = self.claim()
        self.assertFalse(claim_postcondition_verified(before, unchanged))
        disappeared = self.claim(target_identity="", claim_fully_visible=False)
        self.assertTrue(claim_postcondition_verified(before, disappeared, row_disappeared=True))
        self.assertTrue(claim_postcondition_verified(before, unchanged, points_before=10, points_after=11))


class PraiseExecutorTests(unittest.TestCase):
    def test_one_transport_call_and_ambiguous_result_unresolved(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SafetyStore(Path(folder) / "actions.sqlite3")
            store.acquire_lease("praise", 1000.0, 30.0)
            obs = Observation(
                frame_sha256="a" * 64,
                capture_completed_monotonic=999.5,
                runtime_profile_id="pns-blissos-poc-virgl-800x1280-v1",
                width=800,
                height=1280,
                valid_png=True,
                corrupt=False,
                black=False,
                source_state="PERSONAL_MIGHT_LEADERBOARD",
                overlay_state="none_observed",
                target_identity=MIGHT_PRAISE_ACTION.name,
                target_roi=MIGHT_PRAISE_ACTION.roi,
                control_class="PRAISE",
                consequence="praise_zero_cost",
                cost_type="none",
                cost_amount=0,
                quantity=1,
                expected_postcondition="praise_control_changes_or_disables",
                critical_roi_hashes=(("praise", "b" * 64),),
            )
            request = PolicyRequest(
                action_id="praise-1",
                action_key="daily-2026-07-13:praise:personal-might",
                task_id="MVP-QUEST-TO-CLAIM",
                task_mode="supervised_validation",
                semantic_action="PRAISE_PERSONAL_MIGHT",
                expected_runtime_profile_id=obs.runtime_profile_id,
                observation=obs,
                monotonic_now=1000.0,
                observation_max_age_seconds=3.0,
                dispatch_max_age_seconds=2.0,
                lease_owner="praise",
                lease_valid=True,
                unresolved_action=False,
                duplicate_action_key=False,
                game_day_id="daily-2026-07-13",
                action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
            )
            calls = []
            executor = SafeActionExecutor(
                store, CentralPolicy(), "praise", lambda: 1000.0,
                lambda _intent: (calls.append(1) or TransportResult(True, "SENT")),
                lambda: replace(obs, frame_sha256="c" * 64, capture_completed_monotonic=999.8),
                lambda: [],
                lambda _intent, _observation: False,
                wall_clock=lambda: 1000.0,
                max_pre_dispatch_attempts=1,
            )
            result = executor.execute(request)
            self.assertEqual(result.status, ActionStatus.UNRESOLVED)
            self.assertEqual(len(calls), 1)
            self.assertTrue(store.has_action_block())
            store.close()

    def test_known_reset_popup_close_is_bounded_navigation_only(self):
        obs = Observation(
            frame_sha256="a" * 64,
            capture_completed_monotonic=999.5,
            runtime_profile_id="pns-blissos-poc-virgl-800x1280-v1",
            width=800,
            height=1280,
            valid_png=True,
            corrupt=False,
            black=False,
            source_state="RESET_POPUP",
            overlay_state="known_reset_popup",
            target_identity="reset-popup-close",
            target_roi=(280, 770, 520, 845),
            consequence="navigate_zero_cost",
            cost_type="none",
            cost_amount=0,
            quantity=1,
            expected_postcondition="HOME_BASE",
            critical_roi_hashes=(("popup_close", "b" * 64),),
        )
        request = PolicyRequest(
            action_id="popup-1",
            action_key="popup:daily-2026-07-13",
            task_id="MVP-QUEST-TO-CLAIM",
            task_mode="supervised_validation",
            semantic_action="DISMISS_RESET_POPUP",
            expected_runtime_profile_id=obs.runtime_profile_id,
            observation=obs,
            monotonic_now=1000.0,
            observation_max_age_seconds=3.0,
            dispatch_max_age_seconds=2.0,
            lease_owner="popup",
            lease_valid=True,
            unresolved_action=False,
            duplicate_action_key=False,
            game_day_id="daily-2026-07-13",
            action_class=ActionClass.NAVIGATION_ONLY,
        )
        self.assertEqual(CentralPolicy().evaluate(request).reason_code, "AUTHORIZED_NAVIGATION_ONLY")
        self.assertEqual(
            CentralPolicy().evaluate(replace(request, observation=replace(obs, overlay_state="unknown"))).reason_code,
            "UNKNOWN_OVERLAY",
        )


if __name__ == "__main__":
    unittest.main()
