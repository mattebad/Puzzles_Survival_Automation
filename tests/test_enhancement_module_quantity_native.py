"""Wrapped native Module material names retain strict quantity/navigation guards."""
from contextlib import ExitStack
import hashlib
from pathlib import Path
import re
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import enhancement_bluestacks as native
from tests.ocr_memo import install_module_memo


def setUpModule():
    # Identical frames are replayed across tests; run real Tesseract once per unique input.
    install_module_memo()


FRAME = Path(__file__).parent / "fixtures/enhancement_item_modal/native-module-quantity-one-20261029.png"
# Byte-identical to native frame 0015 from soak-20261029T172853367201Z-f442649f.
SHA = "53b27cccf3820ab596dcc3cffef162d45efb0931e76572fb82c291f7c07230e1"
MATERIAL_ROI = (220, 435, 700, 497)
TOTAL_ROI = (220, 498, 460, 535)
USE_ROI = (330, 785, 470, 835)


class ModuleQuantityNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.raw = FRAME.read_bytes()
        cls.frame = cv2.imdecode(np.frombuffer(cls.raw, np.uint8), cv2.IMREAD_COLOR)

        def cached(original):
            cache = {}
            def ocr(frame, roi):
                x0, y0, x1, y1 = roi
                key = roi, hashlib.sha256(frame[y0:y1, x0:x1].tobytes()).hexdigest()
                if key not in cache:
                    cache[key] = original(frame, roi)
                return list(cache[key])
            return ocr

        cls.ocr = staticmethod(cached(native._default_ocr))
        cls.material_ocr = staticmethod(cached(native._quantity_material_ocr))
        cls.stack.enter_context(patch.object(native, "_default_ocr", side_effect=cls.ocr))
        cls.stack.enter_context(patch.object(native, "_quantity_material_ocr", side_effect=cls.material_ocr))
        cls.stack.enter_context(patch.object(native.time, "sleep"))
        cls.quantity = native.recognize_commander_stage(cls.frame, variant="module", stage="material",
            source_frame_sha256=SHA, evidence_ref=FRAME, game_day_id="current-reset")

    def recognize(self, frame=None, *, engine=None, variant="module"):
        if frame is None:
            image, digest, path = self.frame, SHA, FRAME
        else:
            image = frame
            raw = cv2.imencode(".png", image)[1].tobytes()
            digest, path = hashlib.sha256(raw).hexdigest(), Path("offline-changed-module-quantity.png")
        return native.recognize_commander_stage(image, variant=variant, stage="material",
            source_frame_sha256=digest, evidence_ref=path, game_day_id="current-reset", ocr_engine=engine)

    def override(self, changed_roi, replacement):
        def ocr(frame, roi):
            if roi == changed_roi:
                return replacement
            return self.material_ocr(frame, roi) if roi == MATERIAL_ROI else self.ocr(frame, roi)
        return ocr

    def assert_denied(self, result):
        self.assertFalse(result.recognized, result)
        self.assertIsNone(result.quantity_target)
        self.assertIsNone(result.observation)
        self.assertIsNone(result.open_target)

    def test_actual_wrapped_module_name_and_quantity_are_complete_without_resource_authority(self):
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), SHA)
        result = self.quantity
        self.assertTrue(result.recognized, result)
        self.assertEqual(result.diagnostics["material_text"], "1* module enhance material")
        self.assertEqual(re.sub(r"\D", "", result.diagnostics["total_text"]), "8299")
        self.assertEqual(result.diagnostics["denominator_text"], "/8299")
        self.assertEqual(result.diagnostics["material_owned"], 8299)
        self.assertEqual((result.detail_state, result.quantity, result.material_identity),
            ("quantity_modal", 1, "module-material-one-star"))
        self.assertEqual(result.frame_sha256, SHA)
        self.assertEqual(result.quantity_target, (277, 768, 523, 847))
        self.assertEqual(result.close_target, (662, 371, 714, 423))
        self.assertIsNone(result.observation)
        self.assertIsNone(result.open_target)
        self.assertEqual(result.item_identity, "")
        self.assertFalse(result.diagnostics["resource_authority"])

    def test_unordered_real_word_boxes_are_sorted_by_source_row_then_x(self):
        actual = self.material_ocr(self.frame, MATERIAL_ROI)
        self.assertEqual([hit.text.lower() for hit in actual], ["1*", "module", "enhance", "material"])
        # Material is on the next source row, although it is left of Module.
        self.assertGreater(actual[-1].bounds[1], max(hit.bounds[3] for hit in actual[:-1]))
        with patch.object(native, "_quantity_material_ocr", return_value=list(reversed(actual))):
            result = self.recognize()
        self.assertTrue(result.recognized, result)
        self.assertEqual(result.diagnostics["material_text"], "1* module enhance material")
        self.assertIsNone(result.observation)

    def test_missing_or_clipped_second_line_cannot_be_supplied_from_context(self):
        for name, box in (("missing", (220, 467, 700, 497)), ("clipped", (295, 467, 350, 497))):
            with self.subTest(material=name):
                changed = self.frame.copy()
                x0, y0, x1, y1 = box
                changed[y0:y1, x0:x1] = 0
                self.assert_denied(self.recognize(changed))

    def test_wrong_variant_unexpected_word_or_total_mismatch_cannot_grant_use(self):
        self.assert_denied(self.recognize(variant="gear"))
        extra_word = self.material_ocr(self.frame, MATERIAL_ROI) + [native.OcrHit("Premium", (550, 439, 670, 465))]
        self.assert_denied(self.recognize(engine=self.override(MATERIAL_ROI, extra_word)))
        self.assert_denied(self.recognize(engine=self.override(TOTAL_ROI, [native.OcrHit("Total: 8,298", TOTAL_ROI)])))

    def test_quantity_star_and_unique_use_guards_remain_required(self):
        for quantity in (2, None, True):
            with self.subTest(quantity=quantity), patch.object(native, "_quantity_count", return_value=quantity):
                self.assert_denied(self.recognize())
        missing_star = self.frame.copy()
        missing_star[520:557, 95:209] = 0
        self.assert_denied(self.recognize(missing_star))
        duplicate_use = self.ocr(self.frame, USE_ROI) + [native.OcrHit("Use", (430, 810, 460, 830))]
        self.assert_denied(self.recognize(engine=self.override(USE_ROI, duplicate_use)))

    def test_quantity_close_panel_back_and_commander_back_reach_home_with_zero_resource(self):
        from tests.test_enhancement_item_modal_native import NativeEnhancementExitTests
        panel = FRAME.with_name("native-module-zero-selected-20261029.png").read_bytes()
        commander = FRAME.with_name("native-commander-gear-20261029.png").read_bytes()
        home = (Path(__file__).parent / "fixtures/home_base/native-home-bio-zoomed-20261029.png").read_bytes()
        runtime, session = NativeEnhancementExitTests().runtime([self.raw, self.raw, panel, panel, commander, commander, home])
        route = native.EnhancementIntegratedRoute(runtime, variant="module", reset_identity="current-reset", session=session)
        _, terminal = route._navigate_to("home")
        self.assertEqual(terminal.detail_state, "home")
        self.assertEqual([row["target_identity"] for row in runtime.inputs],
            ["quantity-modal-close", "enhancement-visible-back", "commander-visible-back"])
        self.assertEqual([row["target_roi"] for row in runtime.inputs],
            [(662, 371, 714, 423), (47, 2, 128, 61), (48, 2, 129, 61)])
        self.assertEqual([row[1] for row in runtime.journal], ["confirmed"] * 3)
        self.assertFalse(route.resource_dispatch_keys)
        changed = self.frame.copy()
        changed[365:435, 640:735] = 0
        missing = cv2.imencode(".png", changed)[1].tobytes()
        runtime, session = NativeEnhancementExitTests().runtime([self.raw, missing])
        route = native.EnhancementIntegratedRoute(runtime, variant="module", reset_identity="current-reset", session=session)
        with self.assertRaises(native._FlowBlocked):
            route._navigate_to("home")
        self.assertFalse(runtime.inputs)
        self.assertFalse(route.resource_dispatch_keys)


if __name__ == "__main__":
    unittest.main()
