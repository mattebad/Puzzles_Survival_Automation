"""The actual quantity-one modal is navigation, never material consumption."""
from contextlib import ExitStack
from pathlib import Path
import hashlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import enhancement_bluestacks as native
from scripts.bluestacks_native_runtime import captured_native_frame_from_png
from tests.support.environment import requires_tesseract


FRAME = Path(__file__).parent / "fixtures/enhancement_item_modal/native-gear-quantity-one-20261029.png"
SHA = "fc9a296270d7d8d8b124a1e35a0a10b229b5dd55d5565bbf7862322456c834b5"


class QuantityModalNativeTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.raw = FRAME.read_bytes()
        self.frame = cv2.imdecode(np.frombuffer(self.raw, np.uint8), cv2.IMREAD_COLOR)
        self.original_ocr = native._default_ocr
        cache = {}
        def ocr(frame, roi):
            x0, y0, x1, y1 = roi
            key = roi, hashlib.sha256(frame[y0:y1, x0:x1].tobytes()).hexdigest()
            if key not in cache:
                cache[key] = self.original_ocr(frame, roi)
            return list(cache[key])
        self.stack.enter_context(patch.object(native, "_default_ocr", side_effect=ocr))

    def recognize(self, frame=None, variant="gear"):
        return native.recognize_commander_stage(self.frame if frame is None else frame,
            variant=variant, stage="material", source_frame_sha256=SHA, evidence_ref=FRAME)

    @requires_tesseract
    def test_actual_modal_binds_quantity_use_and_x_without_resource_authority(self):
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), SHA)
        result = self.recognize()
        self.assertTrue(result.recognized, result)
        self.assertEqual(result.detail_state, "quantity_modal")
        self.assertEqual(result.quantity, 1)
        self.assertEqual(result.material_identity, "gear-material-one-star")
        self.assertEqual(result.quantity_target, (277, 768, 523, 847))
        self.assertEqual(result.close_target, (662, 371, 714, 423))
        self.assertEqual(result.diagnostics["material_owned"], 9562)
        self.assertIsNone(result.observation)
        self.assertIsNone(result.open_target)
        self.assertEqual(result.item_identity, "")
        self.assertFalse(result.diagnostics["resource_authority"])

    @requires_tesseract
    def test_current_native_gold_quantity_is_read_and_blank_cannot_default_to_one(self):
        path = FRAME.with_name("native-gear-quantity-gold-20261031.png")
        raw = path.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
            "2cf4bb6190193c7c0f79c9997b7a31e0701d2a328c110784a035ce58438c9b91")
        frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        result = native.recognize_commander_stage(frame, variant="gear", stage="material")
        self.assertTrue(result.recognized, result)
        self.assertEqual(result.quantity, 1)
        self.assertEqual(result.diagnostics["material_owned"], 9560)
        self.assertIsNotNone(result.quantity_target)
        self.assertIsNone(result.observation)
        frame[670:710, 508:623] = 0
        self.assertIsNone(native._quantity_count(frame))
        denied = native.recognize_commander_stage(frame, variant="gear", stage="material")
        self.assertFalse(denied.recognized)
        self.assertIsNone(denied.quantity_target)

    @requires_tesseract
    def test_wrong_quantity_type_material_or_total_denominator_cannot_authorize_use(self):
        for value in (0, 2, 10, None, True):
            with self.subTest(quantity=value), patch.object(native, "_quantity_count", return_value=value):
                result = self.recognize()
                self.assertFalse(result.recognized, result)
                self.assertIsNone(result.quantity_target)
                self.assertIsNone(result.observation)
        for variant in ("chip", "module"):
            result = self.recognize(variant=variant)
            self.assertFalse(result.recognized)
        def mismatched(frame, roi):
            if roi == native.QUANTITY_DENOMINATOR_ROI:
                return [native.OcrHit("/9561", (630, 677, 702, 698))]
            return self.original_ocr(frame, roi)
        with patch.object(native, "_default_ocr", side_effect=mismatched):
            self.assertFalse(self.recognize().recognized)

    @requires_tesseract
    def test_retained_live_denominator_slash_reads_stock_and_missing_field_stays_denied(self):
        path = FRAME.with_name("native-gear-quantity-denominator-20261102.png")
        provenance = json.loads(path.with_suffix(".json").read_text())
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), provenance["transport_sha256"])
        frame = cv2.imread(str(path))
        result = native.recognize_commander_stage(frame, variant="gear", stage="material")
        self.assertTrue(result.recognized, result)
        self.assertEqual(result.diagnostics["denominator_text"], "/9557")
        self.assertEqual(result.diagnostics["material_owned"], 9557)
        self.assertEqual(result.quantity, 1)
        self.assertEqual(result.detail_state, "quantity_modal")
        self.assertIsNotNone(result.quantity_target)
        self.assertFalse(result.diagnostics["resource_authority"])
        self.assertIsNone(result.observation)
        x0, y0, x1, y1 = native.QUANTITY_DENOMINATOR_ROI
        frame[y0:y1, x0:x1] = 0
        denied = native.recognize_commander_stage(frame, variant="gear", stage="material")
        self.assertFalse(denied.recognized)
        self.assertIsNone(denied.quantity_target)

    @requires_tesseract
    def test_missing_quantity_or_use_star_and_ambiguous_use_fail_closed(self):
        for box in ((508, 670, 623, 710), (330, 785, 470, 835), (130, 520, 175, 554)):
            with self.subTest(box=box):
                changed = self.frame.copy()
                x0, y0, x1, y1 = box
                changed[y0:y1, x0:x1] = 0
                result = self.recognize(changed)
                self.assertFalse(result.recognized, result)
                self.assertIsNone(result.quantity_target)
        def duplicated(frame, roi):
            result = self.original_ocr(frame, roi)
            if roi == (330, 785, 470, 835):
                result.append(native.OcrHit("Use", (430, 810, 460, 830)))
            return result
        with patch.object(native, "_default_ocr", side_effect=duplicated):
            self.assertFalse(self.recognize().recognized)

    @requires_tesseract
    def test_item_modal_close_keeps_original_measurement_and_missing_quantity_x_is_none(self):
        gear = cv2.imread(str(FRAME.with_name("native-gear-sof-suit-20261029.png")))
        self.assertEqual(native._visible_item_modal_close(gear), (662, 339, 714, 391))
        changed = self.frame.copy()
        changed[365:435, 640:735] = 0
        result = self.recognize(changed)
        self.assertTrue(result.recognized, result)
        self.assertIsNone(result.close_target)
        self.assertIsNotNone(result.quantity_target)

    @requires_tesseract
    def test_current_quantity_must_rebind_before_navigation_dispatch(self):
        test = self
        class Runtime:
            def __init__(self):
                self.inputs = []
            def capture(self, label):
                return captured_native_frame_from_png(test.raw, path=FRAME, captured_monotonic=1.)
            def tap(self, before, **kwargs):
                self.inputs.append(kwargs)
        runtime = Runtime()
        class Session:
            def run_action(self, *, capture, authorize, dispatch, **kwargs):
                before = capture("quantity-before")
                authorize(before)
                dispatch(before)
        route = native.EnhancementIntegratedRoute(runtime, variant="gear", reset_identity="current-reset", session=Session())
        with patch.object(native, "_quantity_count", return_value=2), self.assertRaises(native._FlowBlocked):
            route._action(label="quantity-one-probe", identity="quantity-use",
                before_recognizer=lambda before: self.recognize(before.frame),
                post_recognizer=lambda after: SimpleNamespace(recognized=True),
                target_getter=lambda recognition: recognition.quantity_target,
                before_guard=lambda recognition: recognition.quantity == 1 and recognition.observation is None,
                resource_affecting=False)
        self.assertFalse(runtime.inputs)


if __name__ == "__main__":
    unittest.main()
