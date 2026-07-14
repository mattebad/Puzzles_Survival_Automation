from __future__ import annotations

import unittest
from pathlib import Path

import cv2

from safe_action_core import ActionClass
from scripts.personal_might_praise_live import (
    GAME_BACK,
    RetryableNavigationFailure,
    recognize_route,
    run_bounded_navigation_attempts,
)


ROOT = Path(__file__).resolve().parents[1]
SPEEDUP_FRAME = (
    ROOT
    / "evidence/sessions/20260713-personal-might-praise/live-corrected-popup-006"
    / "reset-popup-close-post-004.png"
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
