"""The actual Module item popup supplies equipment and measured navigation only."""
from contextlib import ExitStack
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import enhancement_bluestacks as native
from scripts.bluestacks_native_runtime import captured_native_frame_from_png
from tests.ocr_memo import install_module_memo


def setUpModule():
    # Identical frames are replayed across tests; run real Tesseract once per unique input.
    install_module_memo()


FRAME = Path(__file__).parent / "fixtures/enhancement_item_modal/native-module-fighter-20261029.png"
# Exact native bytes from the zero-resource navigation probe:
# .local-captures/development-sessions/module-item-inspection-20261029T152218391066Z/
# runtime/module-item-inspection-20261029T152218582058Z/frames/0010-module-item-inspection-terminal.png
SHA = "567cccfd09bb14b9d2336e42e26fea0642d9a2c64e4b090c7583a45ebd478f42"


class ModuleModalNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = FRAME.read_bytes()
        cls.frame = cv2.imdecode(np.frombuffer(cls.raw, np.uint8), cv2.IMREAD_COLOR)
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        original, cache = native._default_ocr, {}
        def ocr(frame, roi):
            x0, y0, x1, y1 = roi
            key = roi, hashlib.sha256(frame[y0:y1, x0:x1].tobytes()).hexdigest()
            if key not in cache:
                cache[key] = original(frame, roi)
            return list(cache[key])
        cls.ocr = staticmethod(ocr)
        cls.stack.enter_context(patch.object(native, "_default_ocr", side_effect=ocr))

    def recognize(self, frame=None, engine=None):
        return native.recognize_commander_stage(self.frame if frame is None else frame, variant="module", stage="item",
            source_frame_sha256=SHA, evidence_ref=FRAME, ocr_engine=engine, game_day_id="current-reset")

    def test_actual_module_binds_full_identity_dynamic_level_equipped_footer_and_visible_controls(self):
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), SHA)
        result = self.recognize()
        self.assertTrue(result.recognized, result)
        self.assertEqual((result.item_identity, result.item_level, result.detail_state), ("fighter module", 18, "item_modal"))
        self.assertEqual((result.open_target, result.close_target), ((152, 892, 259, 930), (662, 357, 714, 409)))
        self.assertEqual([row["label"] for row in result.diagnostics["stat_rows"]], ["fighter hp", "fighter def", "fighter atk"])
        self.assertEqual([row["value"] for row in result.diagnostics["stat_rows"]], ["59.7%"] * 3)
        self.assertEqual(set(result.diagnostics["footer_controls"]), {"enhance", "promote", "replace", "unequip"})
        capture = captured_native_frame_from_png(self.raw, path=FRAME, captured_monotonic=1.)
        route = native.EnhancementIntegratedRoute(SimpleNamespace(), variant="module", reset_identity="current-reset", session=object())
        self.assertTrue(route._selection_source(capture, "modal").recognized)
        self.assertIsNone(result.observation)
        self.assertIsNone(result.quantity)
        self.assertFalse(result.material_selected)
        self.assertFalse(route.resource_dispatch_keys)

    def test_missing_equipment_stats_icon_level_or_close_never_falls_back_to_legacy_static_facts(self):
        for box in (native.MODULE_DETAIL_FOOTER_ROIS["unequip"], native.MODULE_DETAIL_FOOTER_ROIS["enhance"],
                (600, 630, 705, 672), (125, 712, 300, 752), native.MODULE_DETAIL_LEVEL_ROI,
                (377, 516, 425, 558), (640, 345, 735, 420)):
            changed = self.frame.copy()
            x0, y0, x1, y1 = box
            changed[y0:y1, x0:x1] = 0
            with self.subTest(box=box):
                result = self.recognize(changed)
                self.assertFalse(result.recognized, result)
                self.assertIsNone(result.open_target)
        changed = self.frame.copy()
        icon = changed[447:561, 343:457]
        hsv = cv2.cvtColor(icon, cv2.COLOR_BGR2HSV)
        icon[(hsv[:, :, 0] >= 5) & (hsv[:, :, 0] <= 60) & (hsv[:, :, 1] > 70)] = 0
        self.assertFalse(self.recognize(changed).recognized)

    def test_level_item_and_enhance_control_must_be_unambiguous_current_evidence(self):
        for level in ("18", "-18", "+18x", "+1800", "+1O", ""):
            def ocr(frame, roi):
                return [native.OcrHit(level, native.MODULE_DETAIL_LEVEL_ROI)] if roi == native.MODULE_DETAIL_LEVEL_ROI else self.ocr(frame, roi)
            with self.subTest(level=level):
                self.assertFalse(self.recognize(engine=ocr).recognized)
        def changed_level(frame, roi):
            return [native.OcrHit("+19", native.MODULE_DETAIL_LEVEL_ROI)] if roi == native.MODULE_DETAIL_LEVEL_ROI else self.ocr(frame, roi)
        self.assertEqual(self.recognize(engine=changed_level).item_level, 19)
        for changed_roi, text in ((native.MODULE_DETAIL_TITLE_ROI, "6* Fighter Chip"),
                (native.MODULE_DETAIL_FOOTER_ROIS["enhance"], "Enhance")):
            def ocr(frame, roi):
                if roi == changed_roi:
                    return [native.OcrHit(text, roi)] * (2 if text == "Enhance" else 1)
                return self.ocr(frame, roi)
            self.assertFalse(self.recognize(engine=ocr).recognized)

    def test_measured_module_x_rebinds_and_unknown_successor_never_repeats_navigation(self):
        from tests.test_enhancement_item_modal_native import NativeEnhancementExitTests
        commander = FRAME.with_name("native-commander-gear-20261029.png").read_bytes()
        runtime, session = NativeEnhancementExitTests().runtime([self.raw, self.raw, commander])
        route = native.EnhancementIntegratedRoute(runtime, variant="module", reset_identity="current-reset", session=session)
        with patch.object(native.time, "sleep"):
            _, result = route._navigate_to("commander_overview")
        self.assertEqual(result.detail_state, "commander_overview")
        self.assertEqual([item["target_roi"] for item in runtime.inputs], [(662, 357, 714, 409)])
        changed = self.frame.copy()
        changed[345:420, 640:735] = 0
        missing = cv2.imencode(".png", changed)[1].tobytes()
        runtime, session = NativeEnhancementExitTests().runtime([self.raw, missing])
        route = native.EnhancementIntegratedRoute(runtime, variant="module", reset_identity="current-reset", session=session)
        with self.assertRaises(native._FlowBlocked):
            route._navigate_to("commander_overview")
        self.assertFalse(runtime.inputs)
        unknown = cv2.imencode(".png", np.zeros((1280, 800, 3), np.uint8))[1].tobytes()
        runtime, session = NativeEnhancementExitTests().runtime([self.raw, self.raw] + [unknown] * 4)
        route = native.EnhancementIntegratedRoute(runtime, variant="module", reset_identity="current-reset", session=session)
        with patch.object(native.time, "sleep"), self.assertRaises(native._FlowBlocked):
            route._navigate_to("commander_overview")
        self.assertEqual(len(runtime.inputs), 1)
        self.assertFalse(route.resource_dispatch_keys)


if __name__ == "__main__":
    unittest.main()
