"""Replay native Gear selection and its stock/EXP successor without transport."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2

from scripts import enhancement_bluestacks as native
from scripts.bluestacks_native_runtime import captured_native_frame_from_png
from tasks.enhancement import enhancement_bluestacks_postcondition_verified
from tests.support.environment import requires_tesseract


FIXTURES = Path(__file__).parent / "fixtures/enhancement_material_label_crop"


class MaterialLabelCropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        provenance = json.loads((FIXTURES / "provenance.json").read_text())
        cls.captures = []
        for name, record in provenance["frames"].items():
            capture = captured_native_frame_from_png((FIXTURES / name).read_bytes(),
                path=FIXTURES / name, captured_monotonic=record["captured_monotonic"])
            if capture.sha256 != record["sha256"]:
                raise AssertionError("native fixture hash changed")
            cls.captures.append(capture)

    @classmethod
    def _native_selection_results(cls):
        if not hasattr(cls, "_before"):
            modal, baseline, quantity, selected, successor = cls.captures
            cls._before = native.recognize_selection_context(selected, modal=modal,
                baseline=baseline, quantity=quantity, variant="gear", game_day_id="native-regression")
            cls._after = native.recognize_commander_stage(successor.frame, variant="gear", stage="post",
                source_frame_sha256=successor.sha256, evidence_ref=successor.path,
                game_day_id="native-regression")
        return cls._before, cls._after

    @requires_tesseract
    def test_native_label_reads_exact_stock_and_complete_selection_witnesses_prove_effect(self):
        before_result, after_result = self._native_selection_results()
        self.assertTrue(before_result.recognized, before_result)
        self.assertTrue(after_result.recognized, after_result)
        before, after = before_result.observation, after_result.observation
        self.assertEqual((before.material_inventory_count, after.material_inventory_count), (9561, 9560))
        self.assertEqual((before.item_exp_current, before.item_exp_preview, after.item_exp_current), (20, 30, 30))
        self.assertEqual((before.quantity, after.quantity), (1, 0))
        self.assertTrue(enhancement_bluestacks_postcondition_verified(before, after))

    def test_disagreement_and_malformed_fraction_never_supply_inventory(self):
        frame = self.captures[-1].frame
        box = native._material_cell_boxes(frame)[1]
        for readings in (("0/9560", "0/3560"), ("0//9560", "0//9560"), ("1/0", "1/0")):
            with self.subTest(readings=readings), patch("pytesseract.image_to_string", side_effect=readings):
                self.assertIsNone(native._material_label(frame, box))

    @requires_tesseract
    def test_current_zero_selection_keeps_complete_native_counts_without_equipped_authority(self):
        path = FIXTURES / "native-gear-baseline-antialias-20261031.png"
        record = json.loads(path.with_suffix(".json").read_text())
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), record["sha256"])
        frame = cv2.imread(str(path))
        result = native.recognize_commander_stage(frame, variant="gear", stage="material",
            source_frame_sha256=record["sha256"], evidence_ref=path, game_day_id="current-reset")
        self.assertTrue(result.recognized, result)
        self.assertEqual(result.reason, "ENHANCEMENT_MATERIAL_FACTS_OBSERVED")
        self.assertEqual(result.observation.material_slot_facts,
            ((0, 4, 0, 2), (1, 1, 0, 9560), (2, 0, 0, 100)))
        self.assertEqual(result.quantity, 0)
        self.assertFalse(result.material_selected)
        self.assertFalse(result.observation.item_equipped)
        self.assertIsNotNone(result.material_target)

    @requires_tesseract
    def test_wrong_stock_identity_preview_and_source_still_fail_closed(self):
        before_result, after_result = self._native_selection_results()
        before, after = before_result.observation, after_result.observation
        wrong_slots = tuple((slot, stars, selected, owned + (1 if stars == 1 else 0))
            for slot, stars, selected, owned in after.material_slot_facts)
        for changed in (
            replace(after, material_slot_facts=wrong_slots, material_inventory_count=9561),
            replace(after, selected_item_identity="another suit"),
            replace(after, item_exp_current=31),
            replace(after, item_exp_preview=30),
            replace(after, source_frame_sha256=before.source_frame_sha256),
        ):
            with self.subTest(changed=changed):
                self.assertFalse(enhancement_bluestacks_postcondition_verified(before, changed))


if __name__ == "__main__":
    unittest.main()
