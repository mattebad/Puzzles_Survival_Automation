"""Offline proof that Home nav recognition is deterministic on retained native frames.

Ground-truth labels below come from direct visual inspection of each retained frame,
independent of the template/geometry the recognizer uses (no circular validation).
Frames live under the protected, untracked .local-captures tree; when they are absent
the affected assertions are skipped rather than fabricated.
"""

from __future__ import annotations

import glob
import os
import unittest

import cv2

from tasks.home_nav_recognition import (
    HOME_CORRELATION_THRESHOLD,
    recognize_home_nav,
)

_CAPTURES_ROOT = os.path.join(".local-captures", "development-sessions")

# session id -> (is_home_ground_truth, human-described screen)
_GROUND_TRUTH = {
    "delegated-3589bf46-33a8-4396-8517-fccce900dc15": (True, "home"),
    "delegated-9ba8b6e5-3c79-49df-9d96-8ac24a9421fd": (True, "home"),
    "delegated-b4657bc0-7da6-4278-8876-000d2b8781e4": (True, "home"),
    "delegated-e0dece90-4270-4cda-8aad-15bda0c689c0": (True, "home (template source)"),
    "delegated-e9653d82-a3f9-4a7d-ae5c-c562a76f5525": (True, "home"),
    "delegated-5dd7d35b-cb70-4261-a26f-f993e33300e7": (False, "main quest screen"),
}

_EXPECTED_QUEST_TAP = (321, 1247)


def _find_home_source(session_id: str) -> str | None:
    pattern = os.path.join(_CAPTURES_ROOT, session_id, "runtime", "*", "frames", "0001-home-source.png")
    matches = sorted(glob.glob(pattern))
    return matches[0] if matches else None


class HomeNavRecognitionTest(unittest.TestCase):
    def _load(self, session_id: str):
        path = _find_home_source(session_id)
        if path is None:
            self.skipTest(f"retained frame absent for {session_id}")
        frame = cv2.imread(path)
        self.assertIsNotNone(frame, f"could not read {path}")
        return frame

    def test_recognizes_home_and_rejects_non_home(self):
        checked = 0
        for session_id, (expected_home, _screen) in _GROUND_TRUTH.items():
            path = _find_home_source(session_id)
            if path is None:
                continue
            checked += 1
            frame = cv2.imread(path)
            result = recognize_home_nav(frame)
            self.assertEqual(
                result.is_home,
                expected_home,
                f"{session_id}: expected is_home={expected_home}, "
                f"got {result.is_home} (corr={result.correlation:.4f})",
            )
            if expected_home:
                self.assertGreaterEqual(result.correlation, HOME_CORRELATION_THRESHOLD)
                self.assertEqual(result.quest_tap_point(), _EXPECTED_QUEST_TAP)
            else:
                self.assertLess(result.correlation, HOME_CORRELATION_THRESHOLD)
                self.assertIsNone(result.quest_tap_point())
        if checked == 0:
            self.skipTest("no retained frames present")

    def test_recognition_is_deterministic(self):
        frame = self._load("delegated-3589bf46-33a8-4396-8517-fccce900dc15")
        results = [recognize_home_nav(frame) for _ in range(10)]
        correlations = {round(r.correlation, 6) for r in results}
        home_flags = {r.is_home for r in results}
        self.assertEqual(len(correlations), 1, f"nondeterministic correlation: {correlations}")
        self.assertEqual(home_flags, {True})

    def test_non_native_geometry_fails_closed(self):
        import numpy as np

        wrong = np.zeros((720, 1280, 3), dtype=np.uint8)
        result = recognize_home_nav(wrong)
        self.assertFalse(result.is_home)
        self.assertFalse(result.native_ok)


if __name__ == "__main__":
    unittest.main()
