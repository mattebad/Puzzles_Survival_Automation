"""Actual Chip quantity-one facts and measured exits; no device or resource use."""
from contextlib import ExitStack
import hashlib
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import enhancement_bluestacks as native


FRAME = Path(__file__).parent / "fixtures/enhancement_item_modal/native-chip-quantity-one-20261029.png"
# Retained native frame 0015-select-exact-one-star-material-settled-3.png from
# soak-20261029T165424276272Z-f37a0fe5, before the Chip quantity navigation.
SHA = "c1bfa28bc4dcb4f05944aa497e48a9d6d788d61643d863a215e0140bbd4e09b1"
MATERIAL_ROI = native.QUANTITY_MATERIAL_ROI
USE_ROI = (330, 785, 470, 835)


class ChipQuantityNativeTests(unittest.TestCase):
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
        cls.stack.enter_context(patch.object(native.time, "sleep"))
        cls.quantity = native.recognize_commander_stage(cls.frame, variant="chip", stage="material",
            source_frame_sha256=SHA, evidence_ref=FRAME, game_day_id="current-reset")

    def recognize(self, frame=None, *, engine=None):
        if frame is None:
            image, digest, path = self.frame, SHA, FRAME
        else:
            image = frame
            raw = cv2.imencode(".png", image)[1].tobytes()
            digest, path = hashlib.sha256(raw).hexdigest(), Path("offline-changed-chip-quantity.png")
        return native.recognize_commander_stage(image, variant="chip", stage="material",
            source_frame_sha256=digest, evidence_ref=path, game_day_id="current-reset", ocr_engine=engine)

    def overridden(self, roi, texts):
        def ocr(frame, requested):
            if requested == roi:
                return [native.OcrHit(text, roi) for text in texts]
            return self.ocr(frame, requested)
        return ocr

    def assert_denied(self, result):
        self.assertFalse(result.recognized, result)
        self.assertIsNone(result.quantity_target)
        self.assertIsNone(result.observation)
        self.assertIsNone(result.open_target)

    def runtime(self, payloads):
        from tests.test_enhancement_item_modal_native import NativeEnhancementExitTests
        return NativeEnhancementExitTests().runtime(payloads)

    def route(self, runtime, session):
        return native.EnhancementIntegratedRoute(runtime, variant="chip", reset_identity="current-reset", session=session)

    def test_actual_chip_quantity_has_independent_total_denominator_and_navigation_controls(self):
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), SHA)
        result = self.quantity
        self.assertTrue(result.recognized, result)
        self.assertEqual((result.detail_state, result.quantity, result.material_identity),
            ("quantity_modal", 1, "chip-material-one-star"))
        self.assertEqual(result.frame_sha256, SHA)
        self.assertEqual(re.sub(r"\D", "", result.diagnostics["total_text"]), "11535")
        self.assertEqual(result.diagnostics["denominator_text"], "/11535")
        self.assertEqual(result.diagnostics["material_owned"], 11535)
        self.assertEqual(result.quantity_target, (277, 768, 523, 847))
        self.assertEqual(result.close_target, (662, 371, 714, 423))
        self.assertIsNone(result.observation)
        self.assertIsNone(result.open_target)
        self.assertEqual(result.item_identity, "")
        self.assertFalse(result.diagnostics["resource_authority"])

    def test_missing_truncated_or_changed_denominator_cannot_be_filled_from_total(self):
        for texts in ([], ["/1153"], ["/11534"], ["/"]):
            with self.subTest(texts=texts):
                result = self.recognize(engine=self.overridden(native.QUANTITY_DENOMINATOR_ROI, texts))
                self.assert_denied(result)

    def test_wrong_quantity_material_missing_star_or_nonunique_use_cannot_grant_navigation(self):
        for quantity in (2, None, True):
            with self.subTest(quantity=quantity), patch.object(native, "_quantity_count", return_value=quantity):
                self.assert_denied(self.recognize())
        self.assert_denied(self.recognize(engine=self.overridden(MATERIAL_ROI, ["1* Gear Enhance Material"])))
        missing_star = self.frame.copy()
        missing_star[500:557, 95:209] = 0
        self.assert_denied(self.recognize(missing_star))

        def duplicate_use(frame, roi):
            hits = self.ocr(frame, roi)
            return hits + [native.OcrHit("Use", (430, 810, 460, 830))] if roi == USE_ROI else hits

        self.assert_denied(self.recognize(engine=duplicate_use))

    def test_measured_quantity_x_panel_back_and_commander_back_reach_home_without_resource(self):
        panel = FRAME.with_name("native-chip-zero-selected-20261029.png").read_bytes()
        commander = FRAME.with_name("native-commander-gear-20261029.png").read_bytes()
        home = (Path(__file__).parent / "fixtures/home_base/native-home-bio-zoomed-20261029.png").read_bytes()
        runtime, session = self.runtime([self.raw, self.raw, panel, panel, commander, commander, home])
        route = self.route(runtime, session)
        _, terminal = route._navigate_to("home")
        self.assertEqual(terminal.detail_state, "home")
        self.assertEqual([row["target_identity"] for row in runtime.inputs],
            ["quantity-modal-close", "enhancement-visible-back", "commander-visible-back"])
        self.assertEqual([row["target_roi"] for row in runtime.inputs],
            [(662, 371, 714, 423), (47, 2, 128, 61), (48, 2, 129, 61)])
        self.assertFalse(route.resource_dispatch_keys)
        self.assertEqual([row[1] for row in runtime.journal], ["confirmed"] * 3)

    def test_missing_x_on_fresh_frame_blocks_before_any_input(self):
        changed = self.frame.copy()
        changed[365:435, 640:735] = 0
        raw = cv2.imencode(".png", changed)[1].tobytes()
        runtime, session = self.runtime([self.raw, raw])
        route = self.route(runtime, session)
        with self.assertRaises(native._FlowBlocked):
            route._navigate_to("home")
        self.assertFalse(runtime.inputs)
        self.assertFalse(route.resource_dispatch_keys)

    def test_unknown_successor_stops_after_one_measured_x_without_repeating_it(self):
        unknown = cv2.imencode(".png", np.zeros((1280, 800, 3), np.uint8))[1].tobytes()
        runtime, session = self.runtime([self.raw, self.raw] + [unknown] * 4)
        route = self.route(runtime, session)
        with self.assertRaises(native._FlowBlocked):
            route._navigate_to("home")
        self.assertEqual([row["target_identity"] for row in runtime.inputs], ["quantity-modal-close"])
        self.assertEqual(runtime.inputs[0]["target_roi"], (662, 371, 714, 423))
        self.assertFalse(route.resource_dispatch_keys)
        self.assertEqual([row[1] for row in runtime.journal], ["unresolved"])


class QuantityNavigationBoundaryTests(unittest.TestCase):
    def test_detected_quantity_without_safe_exit_cannot_borrow_underlying_panel_back(self):
        from tests.test_enhancement_item_modal_native import NativeEnhancementExitTests
        raw = FRAME.read_bytes()
        quantity_states = (
            native.StageRecognition("navigation", True, "QUANTITY_ONE_USE_NAVIGATION_RECOGNIZED", SHA,
                detail_state="quantity_modal", quantity=1, material_identity="chip-material-one-star",
                quantity_target=(277, 768, 523, 847), close_target=None),
            native.StageRecognition("navigation", False, "QUANTITY_ONE_MATERIAL_FACTS_NOT_PROVEN", SHA,
                diagnostics={"observed_quantity": 2}),
        )
        for quantity in quantity_states:
            with self.subTest(quantity=quantity):
                runtime, session = NativeEnhancementExitTests().runtime([raw])
                route = native.EnhancementIntegratedRoute(runtime, variant="chip",
                    reset_identity="current-reset", session=session)
                tempting = native.StageRecognition("navigation", True, "ENHANCEMENT_PANEL_NAVIGATION_ONLY", SHA,
                    detail_state="enhancement_panel", back_target=(47, 2, 128, 61))
                with patch.object(native, "recognize_home_frame", return_value=SimpleNamespace(recognized=False)), \
                        patch.object(native, "recognize_commander_stage", return_value=native.StageRecognition(
                            "item", False, "NOT_AN_ITEM_MODAL", SHA)), \
                        patch.object(native, "_native_quantity_one", return_value=quantity), \
                        patch.object(native, "_native_enhancement_panel", return_value=tempting) as underlying:
                    with self.assertRaises(native._FlowBlocked):
                        route._navigate_to("home")
                    underlying.assert_not_called()
                self.assertFalse(runtime.inputs)
                self.assertFalse(route.resource_dispatch_keys)


if __name__ == "__main__":
    unittest.main()
