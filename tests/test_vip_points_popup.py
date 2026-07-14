from __future__ import annotations

import unittest
from pathlib import Path

import cv2

from scripts.personal_might_praise_live import (
    LiveAdapter,
    MAX_VIP_POPUP_INPUTS,
    OLD_INVALID_CLOSE_POINT,
    build_vip_popup_artifact,
    point_inside,
    recognize_reset_popup,
    translate_crop_bounds,
    vip_popup_handled,
)


ROOT = Path(__file__).resolve().parents[1]
POPUP_FRAME = (
    ROOT
    / "evidence/sessions/20260713-personal-might-praise/live-diagnostics-003/startup-source-001.png"
)


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

    def test_artifact_enforces_full_frame_center_and_negative_fixture(self):
        detail = recognize_reset_popup(self.frame)
        artifact = build_vip_popup_artifact(POPUP_FRAME, self.frame, detail)
        self.assertTrue(artifact["passed"])
        self.assertEqual(artifact["coordinate_space"], "FULL_FRAME_800X1280")
        self.assertEqual(artifact["target_action"], "DISMISS_VIP_POINTS_POPUP")
        self.assertEqual(artifact["target_control"], "Close")
        self.assertTrue(artifact["center_y_between_780_and_830"])
        self.assertTrue(artifact["old_coordinate_320_650_outside_button"])

    def test_center_y_outside_gate_fails_artifact(self):
        detail = recognize_reset_popup(self.frame)
        detail = {**detail, "target_center": (400, 760)}
        artifact = build_vip_popup_artifact(POPUP_FRAME, self.frame, detail)
        self.assertFalse(artifact["passed"])

    def test_one_popup_input_maximum(self):
        adapter = LiveAdapter.__new__(LiveAdapter)
        adapter.vip_popup_input_count = MAX_VIP_POPUP_INPUTS
        with self.assertRaisesRegex(RuntimeError, "refusing second Close tap"):
            adapter.dismiss_reset_popup({"recognized": True})

    def test_disappearance_and_successor_confirm_handling(self):
        before = {"recognized": True}
        after = {"recognized": False}
        self.assertTrue(vip_popup_handled(before, after, recognized_successor=True))
        self.assertFalse(vip_popup_handled(before, after, recognized_successor=False))
        self.assertFalse(vip_popup_handled(before, {"recognized": True}, recognized_successor=True))


if __name__ == "__main__":
    unittest.main()
