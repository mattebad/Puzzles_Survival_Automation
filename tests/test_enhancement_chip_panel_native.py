"""Actual Chip material facts grant selection/navigation, never resource authority."""
from contextlib import ExitStack
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import enhancement_bluestacks as native
from tests.support.enhancement import exit_runtime
from tests.support.environment import requires_tesseract


FRAME = Path(__file__).parent / "fixtures/enhancement_item_modal/native-chip-zero-selected-20261029.png"
# Byte-identical to pass 6's settled native Chip panel, before any Chip selection.
SHA = "7b93b8ab729ef0492c4408e054cfaefe850b8b466388fe0a232b8a4dfa976ac3"
EXP_ROI = (300, 330, 505, 366)


class ChipPanelNativeTests(unittest.TestCase):
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

    def recognize(self, frame=None, *, engine=None):
        if frame is None:
            image, digest, path = self.frame, SHA, FRAME
        else:
            image = frame
            raw = cv2.imencode(".png", image)[1].tobytes()
            digest, path = hashlib.sha256(raw).hexdigest(), Path("offline-changed-chip-panel.png")
        return native.recognize_commander_stage(image, variant="chip", stage="material",
            source_frame_sha256=digest, evidence_ref=path, game_day_id="current-reset", ocr_engine=engine)

    def overridden(self, roi, texts):
        def ocr(frame, requested):
            if requested == roi:
                return [native.OcrHit(text, roi) for text in texts]
            return self.ocr(frame, requested)
        return ocr

    def assert_no_material_authority(self, result):
        self.assertIsNone(result.observation)
        self.assertIsNone(result.material_target)
        self.assertIsNone(result.open_target)
        self.assertIsNot(result.diagnostics.get("resource_authority"), True)

    @requires_tesseract
    def test_actual_chip_panel_retains_measured_facts_without_equipment_or_resource_authority(self):
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), SHA)
        result = self.recognize()
        self.assertTrue(result.recognized, result)
        self.assertEqual((result.item_identity, result.item_level, result.detail_state),
            ("fighter chip", 20, "enhancement_panel"))
        self.assertEqual(result.frame_sha256, SHA)
        self.assertEqual((result.diagnostics["item_exp_current"], result.diagnostics["item_exp_required"]),
            (10, 140000))
        self.assertEqual(result.diagnostics["exp_display_state"], "committed")
        self.assertEqual(result.observation.material_slot_facts, ((0, 3, 0, 200), (1, 1, 0, 11535)))
        self.assertEqual(result.observation.material_inventory_count, 11535)
        self.assertEqual(result.observation.source_frame_sha256, SHA)
        self.assertIn(str(FRAME), result.observation.evidence_refs)
        self.assertEqual(result.quantity, 0)
        self.assertFalse(result.material_selected)
        self.assertFalse(result.observation.item_equipped)
        self.assertEqual(result.material_target, (189, 612, 282, 705))
        self.assertEqual(result.back_target, (47, 2, 128, 61))
        self.assertIsNone(result.open_target)
        self.assertFalse(native.enhancement_bluestacks_authorizeable(result.observation))
        self.assertFalse(native.enhancement_bluestacks_postcondition_verified(result.observation, result.observation))

    @requires_tesseract
    def test_missing_clipped_wrong_or_conflicting_item_name_cannot_supply_material_observation(self):
        for texts in ([], ["7* Fighter Chi+20"], ["7* Fighter Module+20"],
                ["7* Fighter Chip+20", "Fighter Module+20"]):
            with self.subTest(texts=texts):
                result = self.recognize(engine=self.overridden(native.ENHANCEMENT_PANEL_TITLE_ROI, texts))
                self.assertFalse(result.recognized)
                self.assert_no_material_authority(result)

    @requires_tesseract
    def test_missing_or_mismatched_icon_level_and_missing_exp_never_default_to_known_values(self):
        for roi, texts in ((native.ENHANCEMENT_PANEL_LEVEL_ROI, []),
                (native.ENHANCEMENT_PANEL_LEVEL_ROI, ["+204"]), (EXP_ROI, [])):
            with self.subTest(roi=roi, texts=texts):
                result = self.recognize(engine=self.overridden(roi, texts))
                self.assertFalse(result.recognized)
                self.assert_no_material_authority(result)

    @requires_tesseract
    def test_missing_fraction_or_actual_slash_cannot_be_repaired_from_digits_or_speckles(self):
        missing_fraction = self.frame.copy()
        missing_fraction[619:636, 113:168] = 0
        missing_slash = self.frame.copy()
        missing_slash[621:634, 127:133] = 0
        speckles = missing_slash.copy()
        for y in (621, 627, 633):
            speckles[y, 130] = 255
        for name, frame in (("fraction", missing_fraction), ("slash", missing_slash), ("speckles", speckles)):
            with self.subTest(missing=name):
                self.assertIsNone(native._material_fraction(frame, (79, 612, 172, 705)))
                self.assert_no_material_authority(self.recognize(frame))

    @requires_tesseract
    def test_current_panel_back_reaches_commander_with_one_navigation_and_zero_resource(self):
        commander = FRAME.with_name("native-commander-gear-20261029.png").read_bytes()
        runtime, session = exit_runtime([self.raw, self.raw, commander, commander])
        route = native.EnhancementIntegratedRoute(runtime, variant="chip", reset_identity="current-reset", session=session)
        _, terminal = route._navigate_to("commander_overview")
        self.assertEqual(terminal.detail_state, "commander_overview")
        self.assertEqual([row["target_identity"] for row in runtime.inputs], ["enhancement-visible-back"])
        self.assertEqual(runtime.inputs[0]["target_roi"], (47, 2, 128, 61))
        self.assertFalse(route.resource_dispatch_keys)
        self.assertEqual([row[1] for row in runtime.journal], ["confirmed"])

    @requires_tesseract
    def test_fresh_frame_missing_back_cannot_reuse_the_planning_frame_target(self):
        changed = self.frame.copy()
        changed[:90, :180] = 0
        raw = cv2.imencode(".png", changed)[1].tobytes()
        runtime, session = exit_runtime([self.raw, raw])
        route = native.EnhancementIntegratedRoute(runtime, variant="chip", reset_identity="current-reset", session=session)
        with self.assertRaises(native._FlowBlocked):
            route._navigate_to("commander_overview")
        self.assertFalse(runtime.inputs)
        self.assertFalse(route.resource_dispatch_keys)


if __name__ == "__main__":
    unittest.main()
