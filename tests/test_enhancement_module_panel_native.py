"""Actual Module panel material evidence and navigation; no resource input."""
from contextlib import ExitStack
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import enhancement_bluestacks as native
from tests.support.enhancement import exit_runtime
from tests.ocr_memo import install_module_memo


def setUpModule():
    # Identical frames are replayed across tests; run real Tesseract once per unique input.
    install_module_memo()


FRAME = Path(__file__).parent / "fixtures/enhancement_item_modal/native-module-zero-selected-20261029.png"
# Byte-identical to the native Module baseline frame 0036 from
# soak-20261029T170721304033Z-8b7ce8de, before any Module material selection.
SHA = "c588d4f1ec9b98060fb3a6d1851c72ed384a275a86cd1767ff10d4e6603c6085"
CARD = (79, 612, 172, 705)


class ModulePanelNativeTests(unittest.TestCase):
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

        cls.stack.enter_context(patch.object(native, "_default_ocr", side_effect=ocr))
        cls.stack.enter_context(patch.object(native.time, "sleep"))
        cls.panel = native.recognize_commander_stage(cls.frame, variant="module", stage="material",
            source_frame_sha256=SHA, evidence_ref=FRAME, game_day_id="current-reset")

    def recognize(self, image):
        raw = cv2.imencode(".png", image)[1].tobytes()
        return native.recognize_commander_stage(image, variant="module", stage="material",
            source_frame_sha256=hashlib.sha256(raw).hexdigest(), evidence_ref=Path("offline-changed-module-panel.png"),
            game_day_id="current-reset")

    def assert_no_material_authority(self, result):
        self.assertIsNone(result.observation)
        self.assertIsNone(result.material_target)
        self.assertIsNone(result.open_target)
        self.assertIsNot(result.diagnostics.get("resource_authority"), True)

    def test_actual_module_panel_binds_one_real_star_and_inventory_without_equipment_authority(self):
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), SHA)
        result = self.panel
        self.assertTrue(result.recognized, result)
        self.assertEqual((result.item_identity, result.item_level, result.detail_state),
            ("fighter module", 18, "enhancement_panel"))
        self.assertEqual(result.frame_sha256, SHA)
        self.assertEqual((result.diagnostics["item_exp_current"], result.diagnostics["item_exp_required"]),
            (10, 104500))
        self.assertEqual(result.diagnostics["exp_display_state"], "committed")
        self.assertEqual(result.observation.material_slot_facts, ((0, 1, 0, 8299),))
        self.assertEqual(result.observation.material_inventory_count, 8299)
        self.assertEqual(result.observation.source_frame_sha256, SHA)
        self.assertIn(str(FRAME), result.observation.evidence_refs)
        self.assertEqual(result.quantity, 0)
        self.assertFalse(result.material_selected)
        self.assertFalse(result.observation.item_equipped)
        self.assertEqual(result.material_target, CARD)
        self.assertEqual(result.back_target, (47, 2, 128, 61))
        self.assertIsNone(result.open_target)
        self.assertFalse(native.enhancement_bluestacks_authorizeable(result.observation))
        self.assertFalse(native.enhancement_bluestacks_postcondition_verified(result.observation, result.observation))

    def test_tiny_actual_icon_glints_cannot_replace_an_erased_real_star(self):
        changed = self.frame.copy()
        # The actual gold star is x113..136/y678..699; detached icon glints at
        # x150/y672 and x144/y676 are retained, never promoted into a star.
        changed[678:700, 113:137] = 0
        self.assertTrue(np.array_equal(changed[672:674, 150:152], self.frame[672:674, 150:152]))
        self.assertTrue(np.array_equal(changed[676:677, 144:147], self.frame[676:677, 144:147]))
        self.assert_no_material_authority(self.recognize(changed))

    def test_missing_fraction_slash_or_populated_card_never_disappears_into_a_valid_observation(self):
        for name, box in (("fraction", (99, 619, 169, 636)), ("slash", (114, 621, 122, 634)),
                ("card", (77, 610, 174, 707))):
            with self.subTest(missing=name):
                changed = self.frame.copy()
                x0, y0, x1, y1 = box
                changed[y0:y1, x0:x1] = 0
                self.assert_no_material_authority(self.recognize(changed))

    def test_second_actual_populated_one_star_card_denies_a_unique_material_target(self):
        changed = self.frame.copy()
        changed[612:705, 189:282] = self.frame[612:705, 79:172]
        read = native._material_cells(changed)
        self.assertIsNotNone(read)
        self.assertEqual(read[0], ((0, 1, 0, 8299), (1, 1, 0, 8299)))
        self.assert_no_material_authority(self.recognize(changed))

    def test_measured_back_reaches_home_without_resource_and_missing_fresh_back_blocks(self):
        commander = FRAME.with_name("native-commander-gear-20261029.png").read_bytes()
        home = (Path(__file__).parent / "fixtures/home_base/native-home-bio-zoomed-20261029.png").read_bytes()
        runtime, session = exit_runtime([self.raw, self.raw, commander, commander, home])
        route = native.EnhancementIntegratedRoute(runtime, variant="module", reset_identity="current-reset", session=session)
        _, terminal = route._navigate_to("home")
        self.assertEqual(terminal.detail_state, "home")
        self.assertEqual([row["target_identity"] for row in runtime.inputs],
            ["enhancement-visible-back", "commander-visible-back"])
        self.assertEqual([row["target_roi"] for row in runtime.inputs], [(47, 2, 128, 61), (48, 2, 129, 61)])
        self.assertEqual([row[1] for row in runtime.journal], ["confirmed", "confirmed"])
        self.assertFalse(route.resource_dispatch_keys)
        changed = self.frame.copy()
        changed[:90, :180] = 0
        missing = cv2.imencode(".png", changed)[1].tobytes()
        runtime, session = exit_runtime([self.raw, missing])
        route = native.EnhancementIntegratedRoute(runtime, variant="module", reset_identity="current-reset", session=session)
        with self.assertRaises(native._FlowBlocked):
            route._navigate_to("home")
        self.assertFalse(runtime.inputs)
        self.assertFalse(route.resource_dispatch_keys)


if __name__ == "__main__":
    unittest.main()
