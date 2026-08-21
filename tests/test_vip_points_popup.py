from __future__ import annotations

import unittest
from pathlib import Path

import cv2

from scripts.bluestacks_popup_recognition import (
    MAX_VIP_POPUP_INPUTS,
    OLD_INVALID_CLOSE_POINT,
    classify_popup_recovery,
    point_inside,
    recognize_reset_popup,
    translate_crop_bounds,
    vip_popup_handled,
)


ROOT = Path(__file__).resolve().parents[1]
POPUP_FRAME = ROOT / "tasks/assets/navigation/800x1280/reset_popup_source.png"


class VipPointsPopupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = cv2.imread(str(POPUP_FRAME))
        if cls.frame is None:
            raise RuntimeError("retained VIP Points popup fixture is missing")

    def test_retained_close_geometry_rejects_old_point_and_accepts_center(self):
        detail = recognize_reset_popup(self.frame)
        self.assertTrue(detail["recognized"])
        bounds = tuple(detail["target"])
        self.assertFalse(point_inside(bounds, OLD_INVALID_CLOSE_POINT))
        self.assertTrue(point_inside(bounds, (400, 810), margin=12))
        self.assertGreater(bounds[1], 740)
        self.assertLess(bounds[3], 880)

    def test_literal_close_identity_is_required(self):
        changed = self.frame.copy()
        changed[790:825, 350:450] = 0
        detail = recognize_reset_popup(changed)
        self.assertFalse(detail["literal_close"])
        self.assertFalse(detail["recognized"])

    def test_generic_orange_button_is_rejected(self):
        changed = self.frame.copy()
        changed[380:720, 100:700] = 0
        detail = recognize_reset_popup(changed)
        self.assertFalse(detail["title_identity"])
        self.assertFalse(detail["body_identity"])
        self.assertFalse(detail["recognized"])

    def test_crop_coordinates_translate_to_full_frame(self):
        self.assertEqual(
            translate_crop_bounds((17, 17, 263, 97), (260, 750, 540, 870)),
            (277, 767, 523, 847),
        )

    def test_one_popup_input_maximum(self):
        self.assertEqual(MAX_VIP_POPUP_INPUTS, 1)

    def test_disappearance_and_successor_confirm_handling(self):
        before = {"recognized": True}
        after = {"recognized": False}
        self.assertTrue(vip_popup_handled(before, after, recognized_successor=True))
        self.assertFalse(vip_popup_handled(before, after, recognized_successor=False))
        self.assertFalse(vip_popup_handled(before, {"recognized": True}, recognized_successor=True))

    def test_popup_recovery_projection_keeps_source_context_and_no_confirm(self):
        result = classify_popup_recovery(
            {
                "recognized": True,
                "popup_identity": "VIP_POINTS_GET_PTS",
                "target_identity": "reset-popup-close",
                "title_text": "Get Pts",
            },
            source_context="daily-list",
            successor_context="daily-list",
        )
        self.assertTrue(result.recognized)
        self.assertEqual(result.source_context, "daily-list")
        self.assertTrue(result.allows_dismissal)
        self.assertFalse(result.confirm_authorized)


if __name__ == "__main__":
    unittest.main()
