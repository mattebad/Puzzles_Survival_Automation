"""Retained Supply navigation proves only the circular control is clickable."""
import math
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import captured_native_frame_from_png
from scripts.home_atlas_bluestacks import identity_from_captured
from tasks import supply_depot_vision as vision


FIXTURES = Path(__file__).parent / "fixtures/supply_depot"
BEFORE = FIXTURES / "native-button-before-20261029.png"
CLAIM = (657, 878, 718, 897)
SUPPLY = (652, 901, 721, 922)


class SupplyClaimButtonGeometryTests(unittest.TestCase):
    def setUp(self):
        self.frame = cv2.imread(str(BEFORE))

    def target(self, frame=None, claim=CLAIM, supply=SUPPLY):
        return vision._claim_button_interior(self.frame if frame is None else frame, claim, supply)

    def test_actual_target_is_in_true_button_above_the_nonclickable_label(self):
        target = self.target()
        self.assertIsNotNone(target)
        self.assertEqual((target[2] - target[0], target[3] - target[1]), (16, 12))
        self.assertLess(target[3], CLAIM[1])
        for point in (target[:2], target[2:], (target[0], target[3]), (target[2], target[1])):
            self.assertLess(math.dist(point, (686, 853)), 35)
        self.assertFalse(any(target[0] < x1 and target[2] > x0 and target[1] < y1 and target[3] > y0
                             for x0, y0, x1, y1 in vision.HUD_MASK_RECTS))

    def test_missing_or_wrong_suitcase_does_not_bind_a_circle(self):
        for wrong in (False, True):
            frame = self.frame.copy()
            frame[835:873, 665:707] = cv2.resize(self.frame[852:897, 573:610], (42, 38)) if wrong else (25, 25, 45)
            with self.subTest(wrong_icon=wrong):
                self.assertIsNone(self.target(frame))

    def test_button_binding_tolerates_normal_brightness_changes(self):
        for scale, offset in ((.85, 12.), (1.1, -12.)):
            changed = np.clip(self.frame.astype(float) * scale + offset, 0, 255).astype(np.uint8)
            with self.subTest(scale=scale, offset=offset):
                self.assertIsNotNone(self.target(changed))

    def test_missing_or_clipped_circle_is_not_a_button(self):
        for clipped in (False, True):
            frame = self.frame.copy()
            if clipped:
                frame[814:895, 645:665] = (100, 100, 100)
            else:
                icon = frame[835:873, 665:707].copy()
                frame[814:895, 645:728] = (100, 100, 100)
                frame[835:873, 665:707] = icon
            with self.subTest(clipped=clipped):
                self.assertIsNone(self.target(frame))

    def test_duplicate_or_unassociated_icon_is_denied(self):
        frame = self.frame.copy()
        frame[795:833, 720:762] = self.frame[835:873, 665:707]
        self.assertIsNone(self.target(frame))
        self.assertIsNone(self.target(claim=(557, 878, 618, 897), supply=(552, 901, 621, 922)))

    def test_hud_cannot_leave_only_a_sliver_of_real_button(self):
        for shift in (10, 35):
            matrix = np.array(((1., 0., shift), (0., 1., 0.)))
            frame = cv2.warpAffine(self.frame, matrix, (800, 1280))
            claim = (CLAIM[0] + shift, CLAIM[1], CLAIM[2] + shift, CLAIM[3])
            supply = (SUPPLY[0] + shift, SUPPLY[1], SUPPLY[2] + shift, SUPPLY[3])
            with self.subTest(shift=shift):
                self.assertIsNone(self.target(frame, claim, supply))

    def test_missing_or_untrusted_template_is_denied(self):
        with patch.object(vision, "_claim_icon_template", return_value=None):
            self.assertIsNone(self.target())
        with patch.object(vision, "_CLAIM_ICON_PATH") as asset:
            asset.read_bytes.return_value = b"untrusted-template"
            asset.with_suffix.return_value.read_text.return_value = '{}'
            self.assertIsNone(vision._claim_icon_template())
            asset.with_suffix.return_value.read_text.return_value = '[]'
            self.assertIsNone(vision._claim_icon_template())


class SupplyClaimButtonNativeBindingTests(unittest.TestCase):
    def test_actual_before_binds_button_but_label_dismissal_and_changed_png_do_not(self):
        before = captured_native_frame_from_png(BEFORE.read_bytes(), path=BEFORE, captured_monotonic=time.monotonic())
        identity = identity_from_captured(before, session_id="offline-claim-button", ordinal=1)
        binding = vision.bind_supply_depot_claim_supply(before.frame, source_frame=identity, source_png=before.png)
        self.assertIsNotNone(binding)
        self.assertLess(binding.target_roi[3], CLAIM[1])
        self.assertIsNone(vision.bind_supply_depot_claim_supply(before.frame, source_frame=identity, source_png=before.png + b"changed"))
        after = cv2.imread(str(FIXTURES / "native-label-tap-dismissed-20261029.png"))
        self.assertIsNone(vision.bind_supply_depot_claim_supply(after))


if __name__ == "__main__":
    unittest.main()
