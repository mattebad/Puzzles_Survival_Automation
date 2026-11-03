from pathlib import Path
import hashlib
import unittest

import cv2
import numpy as np

from tasks.campaign_auto_battle import CampaignScreen, CampaignStage
from tasks.campaign_auto_battle_vision import _bind_tier_controls, _selected_tier, recognize_campaign_frame
from tests.ocr_memo import install_module_memo


def setUpModule():
    # Identical frames are replayed across tests; run real Tesseract once per unique input.
    install_module_memo()


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/campaign_tier_controls"


class CampaignTierControlTests(unittest.TestCase):
    def frame(self, name):
        frame = cv2.imread(str(FIXTURES / name))
        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape, (1280, 800, 3))
        return frame

    def test_current_and_older_native_maps_bind_both_current_controls(self):
        for name, selected, expected_centers in (
            ("current-tier-map.png", 2, ((460, 90), (560, 90))),
            ("older-tier-map.png", 1, ((465, 98), (575, 98))),
            ("panned-tier1-map.png", 1, ((460, 90), (560, 90))),
            ("retained-tier2-map.png", 2, ((465, 98), (575, 98))),
        ):
            with self.subTest(name=name):
                recognition = recognize_campaign_frame(self.frame(name), CampaignStage(1, 20, 9))
                self.assertEqual(recognition.observation.screen, CampaignScreen.TIER_MAP)
                self.assertEqual(recognition.observation.selected_tier, selected)
                self.assertEqual(_selected_tier(self.frame(name))[0], selected)
                for tier, (cx, cy) in enumerate(expected_centers, 1):
                    x0, y0, x1, y1 = recognition.target(f"campaign-tier-{tier}")
                    self.assertLessEqual(x0, cx)
                    self.assertLessEqual(y0, cy)
                    self.assertGreater(x1, cx)
                    self.assertGreater(y1, cy)
                    self.assertLess(abs((x0 + x1) / 2 - cx), 5)

    def test_large_map_animation_outside_tier_controls_keeps_same_binding(self):
        source = self.frame("current-tier-map.png")
        _, faces = _bind_tier_controls(source)
        animated = source.copy()
        animated[200:1000] = 255 - animated[200:1000]
        # The former pair selector read these changing gap/background pixels.
        animated[45:145, 375:650] = 255 - animated[45:145, 375:650]
        for x0, y0, x1, y1 in faces:
            animated[y0:y1, x0:x1] = source[y0:y1, x0:x1]
        self.assertNotEqual(hashlib.sha256(source.tobytes()).digest(), hashlib.sha256(animated.tobytes()).digest())
        self.assertGreater(np.count_nonzero(source != animated), 1_000_000)
        original = recognize_campaign_frame(source, CampaignStage(1, 20, 9))
        changed = recognize_campaign_frame(animated, CampaignStage(1, 20, 9))
        self.assertEqual(changed.observation.screen, CampaignScreen.TIER_MAP)
        self.assertEqual(changed.observation.selected_tier, original.observation.selected_tier)
        for tier in (1, 2):
            self.assertEqual(changed.target(f"campaign-tier-{tier}"), original.target(f"campaign-tier-{tier}"))

    def test_changed_control_or_digit_fails_closed(self):
        frame = self.frame("current-tier-map.png")
        for roi in ((413, 59, 503, 119), (513, 59, 603, 119), (540, 70, 580, 109)):
            with self.subTest(roi=roi):
                changed = frame.copy()
                x0, y0, x1, y1 = roi
                changed[y0:y1, x0:x1] = 0
                self.assertIsNone(_bind_tier_controls(changed)[1])
                result = recognize_campaign_frame(changed, CampaignStage(1, 20, 9))
                self.assertNotEqual(result.observation.screen, CampaignScreen.TIER_MAP)
                self.assertIsNone(result.target("campaign-tier-1"))
                self.assertIsNone(result.target("campaign-tier-2"))

    def test_face_identity_requires_one_gold_and_one_brown_selection(self):
        first = self.frame("panned-tier1-map.png")
        second = self.frame("current-tier-map.png")
        _, (one, two) = _bind_tier_controls(first)
        for variant in ("both_gold", "both_brown", "gray"):
            with self.subTest(variant=variant):
                changed = first.copy()
                box = two if variant == "both_gold" else one
                x0, y0, x1, y1 = box
                if variant == "gray":
                    gray = cv2.cvtColor(changed[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
                    changed[y0:y1, x0:x1] = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
                else:
                    changed[y0:y1, x0:x1] = second[y0:y1, x0:x1]
                score, controls = _bind_tier_controls(changed)
                self.assertGreaterEqual(score, 0.90)  # Digits/faces still match.
                self.assertIsNone(controls)
                self.assertIsNone(_selected_tier(changed)[0])

    def test_misaligned_or_duplicate_pairs_reject_even_matching_faces(self):
        source = self.frame("panned-tier1-map.png")
        _, (one, two) = _bind_tier_controls(source)
        for variant in ("misaligned", "duplicate"):
            with self.subTest(variant=variant):
                changed = source.copy()
                if variant == "misaligned":
                    x0, y0, x1, y1 = two
                    face = changed[y0:y1, x0:x1].copy()
                    changed[y0:y1, x0:x1] = 0
                    changed[y0 + 15:y1 + 15, x0:x1] = face
                else:
                    changed[45:145, 375:650] = 0
                    for top in (50, 100):
                        for x0, y0, x1, y1 in (one, two):
                            face = source[y0:y1, x0:x1]
                            changed[top:top + face.shape[0], x0:x1] = face
                self.assertIsNone(_bind_tier_controls(changed)[1])

    def test_wrong_digit_cannot_replace_the_other_tier(self):
        source = self.frame("current-tier-map.png")
        _, (one, two) = _bind_tier_controls(source)
        x0, y0, x1, y1 = two
        a, b, c, d = one
        source[y0:y1, x0:x1] = cv2.resize(source[b:d, a:c], (x1 - x0, y1 - y0))
        self.assertIsNone(_bind_tier_controls(source)[1])

    def test_native_home_and_nova_are_not_tier_maps(self):
        home = cv2.imread(str(ROOT / "tests/fixtures/nova_praise_preflight/zoomed-home-a.png"))
        for frame in (home, self.frame("nova-screen.png")):
            with self.subTest(frame_hash=hashlib.sha256(frame.tobytes()).hexdigest()):
                result = recognize_campaign_frame(frame, CampaignStage(1, 20, 9))
                self.assertNotEqual(result.observation.screen, CampaignScreen.TIER_MAP)
                self.assertIsNone(result.target("campaign-tier-1"))
                self.assertIsNone(result.target("campaign-tier-2"))


if __name__ == "__main__":
    unittest.main()
