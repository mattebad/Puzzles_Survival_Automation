"""Offline proof that Home nav recognition is deterministic on retained native frames.

Ground-truth labels below come from direct visual inspection of each retained frame,
independent of the template/geometry the recognizer uses (no circular validation).
The portable tests run on committed native frames. The original retained-session frames
live under the protected, untracked .local-captures tree and are covered by an explicit
opt-in test (PNS_LOCAL_CAPTURES=1) that fails, never skips, when a frame is missing.
"""

from __future__ import annotations

import glob
import os
import unittest
from pathlib import Path

import cv2

from tasks.home_nav_recognition import (
    HOME_CORRELATION_THRESHOLD,
    recognize_home_nav,
)
from tests.support.local_captures import LOCAL_CAPTURES, requires_local_captures

_CAPTURES_ROOT = str(LOCAL_CAPTURES / "development-sessions")
_FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Committed native 800x1280 frames: (relative path, is_home ground truth, description).
# Labels come from direct visual inspection, independent of the recognizer's template.
_COMMITTED_TRUTH = (
    ("campaign_ap_hud/home-ap100-stamina120.png", True, "home"),
    ("nova_praise_preflight/zoomed-home-a.png", True, "home (zoomed)"),
    ("resource_effect_authority/portable/session-2-terminal-home.png", True, "home"),
    ("runtime_trace_projection/frames/0007-commander-to-home-terminal-settled.png", True, "home"),
    ("world_map/world-hud-1a2d8f02.png", False, "world map"),
    ("campaign_tier_controls/retained-tier2-map.png", False, "campaign tier map"),
)

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


def _assert_recognition(test: unittest.TestCase, label: str, frame, expected_home: bool) -> None:
    result = recognize_home_nav(frame)
    test.assertEqual(
        result.is_home,
        expected_home,
        f"{label}: expected is_home={expected_home}, "
        f"got {result.is_home} (corr={result.correlation:.4f})",
    )
    if expected_home:
        test.assertGreaterEqual(result.correlation, HOME_CORRELATION_THRESHOLD)
        test.assertEqual(result.quest_tap_point(), _EXPECTED_QUEST_TAP)
    else:
        test.assertLess(result.correlation, HOME_CORRELATION_THRESHOLD)
        test.assertIsNone(result.quest_tap_point())


class HomeNavRecognitionTest(unittest.TestCase):
    def test_recognizes_home_and_rejects_non_home_on_committed_frames(self):
        for relative, expected_home, _screen in _COMMITTED_TRUTH:
            with self.subTest(frame=relative):
                path = _FIXTURES / relative
                frame = cv2.imread(str(path))
                self.assertIsNotNone(frame, f"could not read {path}")
                _assert_recognition(self, relative, frame, expected_home)

    def test_recognition_is_deterministic_on_committed_home_frame(self):
        frame = cv2.imread(str(_FIXTURES / _COMMITTED_TRUTH[0][0]))
        self.assertIsNotNone(frame)
        results = [recognize_home_nav(frame) for _ in range(10)]
        correlations = {round(r.correlation, 6) for r in results}
        home_flags = {r.is_home for r in results}
        self.assertEqual(len(correlations), 1, f"nondeterministic correlation: {correlations}")
        self.assertEqual(home_flags, {True})

    @requires_local_captures
    def test_recognizes_home_and_rejects_non_home_on_retained_sessions(self):
        for session_id, (expected_home, _screen) in _GROUND_TRUTH.items():
            with self.subTest(session=session_id):
                path = _find_home_source(session_id)
                self.assertIsNotNone(
                    path, f"PNS_LOCAL_CAPTURES=1 but retained frame is absent for {session_id}"
                )
                frame = cv2.imread(path)
                self.assertIsNotNone(frame, f"could not read {path}")
                _assert_recognition(self, session_id, frame, expected_home)

    @requires_local_captures
    def test_recognition_is_deterministic_on_retained_session(self):
        session_id = "delegated-3589bf46-33a8-4396-8517-fccce900dc15"
        path = _find_home_source(session_id)
        self.assertIsNotNone(
            path, f"PNS_LOCAL_CAPTURES=1 but retained frame is absent for {session_id}"
        )
        frame = cv2.imread(path)
        self.assertIsNotNone(frame, f"could not read {path}")
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
