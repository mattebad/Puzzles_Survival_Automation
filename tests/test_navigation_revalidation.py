from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2

from safe_action_core import ActionClass
from scripts.personal_might_praise_live import (
    GAME_BACK,
    LiveAdapter,
    MIGHT_PRAISE_ACTION,
    PERSONAL_MIGHT_BACK,
    RANKINGS_ENTRY,
    RetryableNavigationFailure,
    recognize_praise_start_state,
    recognize_route,
    run_bounded_navigation_attempts,
)


ROOT = Path(__file__).resolve().parents[1]
SPEEDUP_FRAME = (
    ROOT
    / "evidence/sessions/20260713-personal-might-praise/live-corrected-popup-006"
    / "reset-popup-close-post-004.png"
)
MORE_FRAME = (
    ROOT
    / "evidence/sessions/20260713-personal-might-praise/live-route-recovery-014"
    / "more-to-rankings-game-attempt-1-attempt-3-source-011.png"
)
RANKINGS_FRAME = (
    ROOT
    / "evidence/sessions/20260713-personal-might-praise/live-rankings-corrected-015"
    / "rankings-evidence-013.png"
)
PERSONAL_MIGHT_FRAME = (
    ROOT
    / "evidence/sessions/20260713-personal-might-praise/live-personal-might-leaderboard-016"
    / "personal-might-leaderboard-evidence-007.png"
)
HOME_FRAME = (
    ROOT
    / "evidence/sessions/20260712-m6-dq-bootstrap/assets"
    / "home-base-settled.png"
)
DAILY_REFERENCE = ROOT / "evidence/sessions/20260712-m6-dq-bootstrap/assets/daily-quest-settled.png"
MAIN_QUEST_REFERENCE = ROOT / "evidence/sessions/20260712-m6-dq-bootstrap/assets/quest-main-settled.png"
PERSONAL_MIGHT_CLAIM_FRAME = (
    ROOT
    / "evidence/sessions/20260713-personal-might-praise/live-daily-claim-evidence-019"
    / "praise-daily-claim-evidence-019.png"
)


class SpeedupHelpBackRecognitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = cv2.imread(str(SPEEDUP_FRAME))
        if cls.frame is None:
            raise RuntimeError("retained Speedup Help fixture is missing")

    def assertBackRecognized(self, frame):
        detail = recognize_route(frame, "ALLIANCE_BACK")
        self.assertTrue(detail["recognized"], detail)
        self.assertEqual(tuple(detail["target"]["bounds"]), GAME_BACK.roi)

    def test_request_row_changes_do_not_invalidate_back(self):
        changed = self.frame.copy()
        changed[230:500, 180:760] = (18, 25, 31)
        self.assertBackRecognized(changed)

    def test_lower_screen_animation_does_not_invalidate_back(self):
        changed = self.frame.copy()
        changed[850:1180, 0:800] = (7, 11, 19)
        self.assertBackRecognized(changed)

    def test_back_change_or_disappearance_blocks(self):
        changed = self.frame.copy()
        x0, y0, x1, y1 = GAME_BACK.roi
        changed[y0:y1, x0:x1] = 0
        self.assertFalse(recognize_route(changed, "ALLIANCE_BACK")["recognized"])

    def test_popup_covering_back_blocks(self):
        covered = self.frame.copy()
        x0, y0, x1, y1 = GAME_BACK.roi
        covered[y0:y1, x0:x1] = (240, 150, 60)
        self.assertFalse(recognize_route(covered, "ALLIANCE_BACK")["recognized"])


class RankingsEntryRecognitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = cv2.imread(str(MORE_FRAME))
        if cls.frame is None:
            raise RuntimeError("retained More fixture is missing")

    def test_rankings_binding_is_tight_and_not_historical_broad_center(self):
        detail = recognize_route(self.frame, "MORE")
        self.assertTrue(detail["recognized"], detail)
        self.assertEqual(tuple(detail["target"]["bounds"]), RANKINGS_ENTRY.roi)
        self.assertEqual(RANKINGS_ENTRY.roi, (602, 1138, 690, 1167))
        self.assertFalse(
            RANKINGS_ENTRY.roi[0] <= 400 <= RANKINGS_ENTRY.roi[2]
            and RANKINGS_ENTRY.roi[1] <= 1152 <= RANKINGS_ENTRY.roi[3]
        )

    def test_rankings_text_outside_local_roi_does_not_bind(self):
        changed = self.frame.copy()
        x0, y0, x1, y1 = RANKINGS_ENTRY.roi
        changed[y0:y1, x0:x1] = 0
        self.assertFalse(recognize_route(changed, "MORE")["recognized"])


class PersonalMightCheckRecognitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = cv2.imread(str(RANKINGS_FRAME))
        if cls.frame is None:
            raise RuntimeError("retained Rankings fixture is missing")

    def test_rankings_and_check_bind_distinct_local_rois(self):
        rankings = recognize_route(self.frame, "RANKINGS")
        check = recognize_route(self.frame, "PERSONAL_MIGHT_RANK")
        self.assertTrue(rankings["recognized"], rankings)
        self.assertTrue(check["recognized"], check)
        self.assertEqual(tuple(rankings["target"]["bounds"]), (170, 220, 560, 325))
        self.assertEqual(tuple(check["target"]["bounds"]), (590, 245, 775, 315))

    def test_missing_check_blocks_check_without_invalidating_row(self):
        changed = self.frame.copy()
        changed[245:315, 590:775] = 0
        self.assertTrue(recognize_route(changed, "RANKINGS")["recognized"])
        self.assertFalse(recognize_route(changed, "PERSONAL_MIGHT_RANK")["recognized"])


class PersonalMightLeaderboardRecognitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = cv2.imread(str(PERSONAL_MIGHT_FRAME))
        if cls.frame is None:
            raise RuntimeError("retained Personal Might fixture is missing")

    def test_identity_praise_and_back_are_local(self):
        leaderboard = recognize_route(self.frame, "PERSONAL_MIGHT_LEADERBOARD")
        back = recognize_route(self.frame, "PERSONAL_MIGHT_BACK")
        self.assertTrue(leaderboard["recognized"], leaderboard)
        self.assertEqual(tuple(leaderboard["target"]["bounds"]), MIGHT_PRAISE_ACTION.roi)
        self.assertGreaterEqual(leaderboard["praise_score"], MIGHT_PRAISE_ACTION.threshold)
        self.assertTrue(back["recognized"], back)
        self.assertEqual(tuple(back["target"]["bounds"]), PERSONAL_MIGHT_BACK.roi)

    def test_changed_praise_target_blocks_action_but_preserves_screen_identity(self):
        changed = self.frame.copy()
        x0, y0, x1, y1 = MIGHT_PRAISE_ACTION.roi
        changed[y0:y1, x0:x1] = 0
        detail = recognize_route(changed, "PERSONAL_MIGHT_LEADERBOARD")
        self.assertTrue(detail["recognized"])
        self.assertIsNone(detail["target"])


class PraiseStartupRecognitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = cv2.imread(str(HOME_FRAME))

    def test_resume_states_are_positive_and_specific(self):
        self.assertEqual(
            recognize_praise_start_state(cv2.imread(str(PERSONAL_MIGHT_FRAME)), self.home),
            "PERSONAL_MIGHT_LEADERBOARD",
        )
        self.assertEqual(
            recognize_praise_start_state(cv2.imread(str(RANKINGS_FRAME)), self.home),
            "RANKINGS",
        )
        self.assertEqual(
            recognize_praise_start_state(cv2.imread(str(MORE_FRAME)), self.home),
            "MORE",
        )
        self.assertEqual(recognize_praise_start_state(self.home, self.home), "HOME_BASE")

    def test_unknown_startup_does_not_default_to_home(self):
        self.assertEqual(
            recognize_praise_start_state(self.home * 0, self.home),
            "UNKNOWN",
        )


class PersonalMightClaimRecognitionTests(unittest.TestCase):
    def test_exact_completed_row_binds_local_claim_control(self):
        adapter = LiveAdapter.__new__(LiveAdapter)
        adapter.args = SimpleNamespace(
            daily_reference=DAILY_REFERENCE,
            main_quest_reference=MAIN_QUEST_REFERENCE,
        )
        adapter.game_day = "daily-2026-07-13"
        observation, detail = adapter._daily_claim_observation(PERSONAL_MIGHT_CLAIM_FRAME)
        self.assertTrue(observation.recognized)
        self.assertTrue(observation.selected_daily_quest)
        self.assertEqual((observation.current_progress, observation.required_progress), (1, 1))
        self.assertEqual(observation.target_identity, "daily-quest-claim")
        self.assertEqual(observation.control_class, "CLAIM")
        self.assertTrue(observation.row_fully_visible)
        self.assertTrue(observation.claim_fully_visible)
        self.assertIsNotNone(detail["claim_line"])
        rx0, ry0, rx1, ry1 = observation.row_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
        self.assertTrue(rx0 <= tx0 < tx1 <= rx1 and ry0 <= ty0 < ty1 <= ry1)


class NavigationRetryTests(unittest.TestCase):
    def test_zero_transport_cancellation_reacquires_and_retries(self):
        calls = []

        def operation(attempt_id):
            calls.append(attempt_id)
            if len(calls) == 1:
                raise RetryableNavigationFailure("OVERLAY_STATE_CHANGED", transport_calls=0)
            return "confirmed"

        result, failures = run_bounded_navigation_attempts("back", operation)
        self.assertEqual(result, "confirmed")
        self.assertEqual(len(failures), 1)
        self.assertEqual(calls, ["back-attempt-1", "back-attempt-2"])

    def test_fresh_retry_gets_new_attempt_identity(self):
        identities = []

        def operation(attempt_id):
            identities.append(attempt_id)
            if len(identities) < 3:
                raise RetryableNavigationFailure("SOURCE_OR_TARGET_NOT_RECOGNIZED")
            return True

        run_bounded_navigation_attempts("more", operation)
        self.assertEqual(len(set(identities)), 3)

    def test_three_failed_fresh_attempts_terminate_boundedly(self):
        identities = []

        def operation(attempt_id):
            identities.append(attempt_id)
            raise RetryableNavigationFailure(
                "SOURCE_OR_TARGET_NOT_RECOGNIZED",
                source_frame=f"{attempt_id}.png",
                target_roi=GAME_BACK.roi,
            )

        with self.assertRaisesRegex(RuntimeError, "three fresh navigation attempts failed"):
            run_bounded_navigation_attempts("rankings", operation)
        self.assertEqual(len(identities), 3)

    def test_retry_logic_does_not_apply_to_praise_or_claim(self):
        for name in ("PRAISE_PERSONAL_MIGHT", "CLAIM_DAILY_QUEST"):
            calls = []

            def operation(attempt_id):
                calls.append(attempt_id)
                raise RetryableNavigationFailure("AMBIGUOUS", transport_calls=1)

            with self.assertRaises(RetryableNavigationFailure):
                run_bounded_navigation_attempts(
                    name,
                    operation,
                    action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
                )
            self.assertEqual(calls, [name])


if __name__ == "__main__":
    unittest.main()
