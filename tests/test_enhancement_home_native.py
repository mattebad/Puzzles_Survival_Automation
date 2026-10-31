"""Current native clean Home admits the existing exact Commander portrait target."""

import hashlib
from pathlib import Path
import unittest

import cv2

from scripts.enhancement_bluestacks import HOME_PROFILE_PORTRAIT_ROI, recognize_home_frame


ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "tests/fixtures/home_base/native-home-bio-zoomed-20261029.png"


class EnhancementHomeNativeTests(unittest.TestCase):
    def test_current_home_and_dynamic_artwork_bind_same_portrait_from_new_frames(self):
        frame = cv2.imread(str(HOME))
        first_hash = hashlib.sha256(HOME.read_bytes()).hexdigest()
        first = recognize_home_frame(frame, source_frame_sha256=first_hash)
        self.assertTrue(first.recognized, first)
        self.assertEqual(first.portrait_target, HOME_PROFILE_PORTRAIT_ROI)
        self.assertEqual(first.frame_sha256, first_hash)
        animated = frame.copy()
        animated[80:350, 600:800] = 0
        animated[1180:1235, 200:700] = 0
        animated_hash = hashlib.sha256(cv2.imencode(".png", animated)[1].tobytes()).hexdigest()
        self.assertNotEqual(first_hash, animated_hash)
        second = recognize_home_frame(animated, source_frame_sha256=animated_hash)
        self.assertTrue(second.recognized, second)
        self.assertEqual(second.portrait_target, first.portrait_target)
        self.assertEqual(second.frame_sha256, animated_hash)

    def test_popup_and_radial_home_are_rejected(self):
        for reference in (
            "tasks/assets/navigation/800x1280/reset_popup_source.png",
            "tests/fixtures/nova_praise_preflight/research-lab-radial-07f3d826.png",
        ):
            with self.subTest(reference=reference):
                frame = cv2.imread(str(ROOT / reference))
                result = recognize_home_frame(frame)
                self.assertFalse(result.recognized, result)
                self.assertIsNone(result.portrait_target)

    def test_missing_avatar_or_ambiguous_profile_identity_does_not_bind(self):
        frame = cv2.imread(str(HOME))
        missing = frame.copy()
        missing[35:145, 0:110] = 0
        result = recognize_home_frame(missing)
        self.assertFalse(result.recognized, result)
        self.assertEqual(result.reason, "PROFILE_PORTRAIT_NOT_UNIQUE")
        ambiguous = recognize_home_frame(
            frame,
            ocr_engine=lambda _frame, _roi: [
                {"text": "Commander Portrait", "bounds": (4, 40, 84, 123)},
                {"text": "Profile Portrait", "bounds": (150, 60, 230, 140)},
            ],
        )
        self.assertFalse(ambiguous.recognized)
        self.assertEqual(ambiguous.reason, "PROFILE_PORTRAIT_NOT_UNIQUE")

    def test_non_native_source_does_not_bind_portrait(self):
        frame = cv2.imread(str(HOME))
        result = recognize_home_frame(frame[:640])
        self.assertFalse(result.recognized)
        self.assertEqual(result.reason, "NON_NATIVE_FRAME")
        self.assertIsNone(result.portrait_target)


if __name__ == "__main__":
    unittest.main()
