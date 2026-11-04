"""Retained current Chip modal; no device or resource transport."""
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
from tests.support.enhancement import exit_runtime
from tests.support.environment import requires_tesseract


FRAME = Path(__file__).parent / "fixtures/enhancement_item_modal/native-chip-fighter-20261029.png"
# Byte-identical to the real, zero-Chip-Use family attempt frame 0032:
# .local-captures/automation-service-authorized/enhancement-20261029T144131190370Z/
# enhancement-20261029T144131223602Z-e20a1cb2/runtime/
# enhancement-family-20261029T144201295689Z/frames/0032-open-enhance-panel-immediate-before.png
SHA = "6c001c4b4e274d6875a59951d58c326201ff1e36a15cbfe767f63081cd6f853a"


class ChipModalNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.raw = FRAME.read_bytes()
        cls.frame = cv2.imdecode(np.frombuffer(cls.raw, np.uint8), cv2.IMREAD_COLOR)
        original = native._default_ocr
        cache = {}
        def ocr(frame, roi):
            x0, y0, x1, y1 = roi
            key = roi, hashlib.sha256(frame[y0:y1, x0:x1].tobytes()).hexdigest()
            if key not in cache:
                cache[key] = original(frame, roi)
            return list(cache[key])
        cls.ocr = staticmethod(ocr)
        cls.stack.enter_context(patch.object(native, "_default_ocr", side_effect=ocr))

    def recognize(self, frame=None, engine=None, variant="chip"):
        return native.recognize_commander_stage(self.frame if frame is None else frame, variant=variant,
            stage="item", source_frame_sha256=SHA, evidence_ref=FRAME, ocr_engine=engine, game_day_id="current-reset")

    @requires_tesseract
    def test_real_chip_modal_has_actual_level_stats_equipped_footer_and_measured_controls(self):
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), SHA)
        result = self.recognize()
        self.assertTrue(result.recognized, result)
        self.assertEqual((result.item_identity, result.item_level, result.detail_state), ("fighter chip", 20, "item_modal"))
        self.assertEqual(result.open_target, (87, 892, 194, 930))
        self.assertEqual(result.close_target, (662, 357, 714, 409))
        self.assertEqual([row["label"] for row in result.diagnostics["stat_rows"]], ["fighter hp", "fighter def", "fighter atk"])
        self.assertEqual([row["value"] for row in result.diagnostics["stat_rows"]], ["78.1%"] * 3)
        self.assertEqual(set(result.diagnostics["footer_controls"]), {"enhance", "promote", "modify", "replace", "unequip"})
        self.assertIsNone(result.observation)
        self.assertIsNone(result.quantity)
        self.assertFalse(result.material_selected)

    @requires_tesseract
    def test_current_title_without_ocr_star_still_requires_the_actual_equipped_icon(self):
        path = FRAME.with_name("native-chip-title-omitted-star-20261031.png")
        raw = path.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), "3784bf54a6d1a9151f0212070535af2ff8af5b461ab8010ff51d94996d03fa6a")
        frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        result = self.recognize(frame)
        self.assertTrue(result.recognized, result)
        self.assertEqual((result.item_identity, result.item_level), ("fighter chip", 20))
        self.assertEqual(result.diagnostics["item_star"], 7)
        self.assertIsNone(result.observation)
        self.assertFalse(result.material_selected)
        frame[516:558, 377:425] = 0
        denied = self.recognize(frame)
        self.assertFalse(denied.recognized)
        self.assertIsNone(denied.open_target)

    @requires_tesseract
    def test_level_is_parsed_and_missing_malformed_or_duplicate_level_cannot_default_to_twenty(self):
        def level_engine(text, duplicate=False):
            def ocr(frame, roi):
                if roi == native.CHIP_DETAIL_LEVEL_ROI:
                    return [native.OcrHit(text, (350, 456, 391, 477))] * (2 if duplicate else 1)
                return self.ocr(frame, roi)
            return ocr
        self.assertEqual(self.recognize(engine=level_engine("+21")).item_level, 21)
        for text, duplicate in (("", False), ("-20", False), ("20", False), ("+2000", False), ("+2O", False), ("+20", True)):
            with self.subTest(text=text, duplicate=duplicate):
                result = self.recognize(engine=level_engine(text, duplicate))
                self.assertFalse(result.recognized)
                self.assertIsNone(result.open_target)

    @requires_tesseract
    def test_missing_equipped_control_stat_icon_or_close_cannot_authorize_modal(self):
        for box in (native.CHIP_DETAIL_FOOTER_ROIS["unequip"], native.CHIP_DETAIL_FOOTER_ROIS["enhance"],
                (600, 672, 705, 712), (125, 712, 300, 752), (343, 449, 391, 477),
                (377, 516, 425, 558), (640, 345, 735, 420)):
            with self.subTest(box=box):
                changed = self.frame.copy()
                x0, y0, x1, y1 = box
                changed[y0:y1, x0:x1] = 0
                result = self.recognize(changed)
                self.assertFalse(result.recognized, result)
                self.assertIsNone(result.open_target)
        # Remove the blue icon, preserving its overlaid level and red stars.
        changed = self.frame.copy()
        icon = changed[447:561, 343:457]
        hsv = cv2.cvtColor(icon, cv2.COLOR_BGR2HSV)
        icon[(hsv[:, :, 0] >= 60) & (hsv[:, :, 0] <= 140) & (hsv[:, :, 1] > 80)] = 0
        self.assertFalse(self.recognize(changed).recognized)

    @requires_tesseract
    def test_wrong_item_variant_and_nonunique_enhance_do_not_bind(self):
        def wrong(frame, roi):
            if roi == native.CHIP_DETAIL_TITLE_ROI:
                return [native.OcrHit("7* Fighter Module", (287, 370, 508, 403))]
            return self.ocr(frame, roi)
        self.assertFalse(self.recognize(engine=wrong).recognized)
        def duplicate(frame, roi):
            hits = self.ocr(frame, roi)
            return hits + [native.OcrHit("Enhance", (95, 925, 186, 933))] if roi == native.CHIP_DETAIL_FOOTER_ROIS["enhance"] else hits
        ambiguous = self.recognize(engine=duplicate)
        self.assertFalse(ambiguous.recognized)
        self.assertIsNone(ambiguous.open_target)
        self.assertFalse(self.recognize(variant="gear").recognized)
        self.assertFalse(self.recognize(variant="module").recognized)

    @requires_tesseract
    def test_known_chip_close_is_rebound_before_navigation_and_uses_no_resource(self):
        commander = FRAME.with_name("native-commander-gear-20261029.png").read_bytes()
        runtime, session = exit_runtime([self.raw, self.raw, commander, commander])
        route = native.EnhancementIntegratedRoute(runtime, variant="chip", reset_identity="current-reset", session=session)
        _, terminal = route._navigate_to("commander_overview")
        self.assertEqual(terminal.detail_state, "commander_overview")
        self.assertEqual([item["target_identity"] for item in runtime.inputs], ["item-detail-close"])
        self.assertEqual(runtime.inputs[0]["target_roi"], (662, 357, 714, 409))
        self.assertFalse(route.resource_dispatch_keys)
        missing = self.frame.copy()
        missing[345:420, 640:735] = 0
        raw = cv2.imencode(".png", missing)[1].tobytes()
        runtime, session = exit_runtime([self.raw, raw])
        route = native.EnhancementIntegratedRoute(runtime, variant="chip", reset_identity="current-reset", session=session)
        with self.assertRaises(native._FlowBlocked):
            route._navigate_to("commander_overview")
        self.assertFalse(runtime.inputs)

    @requires_tesseract
    def test_chip_modal_satisfies_current_run_equipped_gate_but_has_no_material_authority(self):
        capture = captured_native_frame_from_png(self.raw, path=FRAME, captured_monotonic=1.)
        route = native.EnhancementIntegratedRoute(SimpleNamespace(), variant="chip", reset_identity="current-reset", session=object())
        result = route._selection_source(capture, "modal")
        self.assertTrue(result.recognized)
        self.assertIsNone(result.observation)
        self.assertEqual(route._selection_witnesses, {"modal": capture})
        self.assertFalse(route.resource_dispatch_keys)


if __name__ == "__main__":
    unittest.main()
