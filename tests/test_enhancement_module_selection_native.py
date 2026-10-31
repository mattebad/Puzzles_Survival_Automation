"""Four actual Module witnesses bind a moved card without filling missing facts."""
from contextlib import ExitStack
from dataclasses import replace
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2

from scripts import enhancement_bluestacks as native
from scripts.bluestacks_native_runtime import captured_native_frame_from_png
from tasks.enhancement import enhancement_bluestacks_authorizeable, enhancement_bluestacks_postcondition_verified


FIXTURES = Path(__file__).parent / "fixtures/enhancement_item_modal"
SESSION = Path("unit-module-selection/session")
PREVIEW_SHA = "2b25677dc1b5d903b42eca402014496bdc3e4e46c440c17503f1e88d0c5b5116"
BASELINE_SHA = "c588d4f1ec9b98060fb3a6d1851c72ed384a275a86cd1767ff10d4e6603c6085"
OLD_BOX = (79, 612, 172, 705)
CURRENT_BOX = (77, 615, 173, 712)


class ModuleSelectionNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)

        def cached_ocr(original):
            cache = {}
            def ocr(frame, roi):
                x0, y0, x1, y1 = roi
                key = roi, hashlib.sha256(frame[y0:y1, x0:x1].tobytes()).hexdigest()
                if key not in cache:
                    cache[key] = original(frame, roi)
                return list(cache[key])
            return ocr

        cls.ocr = staticmethod(cached_ocr(native._default_ocr))
        cls.material_ocr = staticmethod(cached_ocr(native._quantity_material_ocr))
        original_label, label_cache = native._material_label, {}
        def label(frame, box):
            x0, y0, x1, y1 = box
            key = box, hashlib.sha256(frame[y0:y1, x0:x1].tobytes()).hexdigest()
            if key not in label_cache:
                label_cache[key] = original_label(frame, box)
            return label_cache[key]
        cls.stack.enter_context(patch.object(native, "_default_ocr", side_effect=cls.ocr))
        cls.stack.enter_context(patch.object(native, "_quantity_material_ocr", side_effect=cls.material_ocr))
        cls.stack.enter_context(patch.object(native, "_material_label", side_effect=label))
        names = ("native-module-fighter-20261029.png", "native-module-zero-selected-20261029.png",
            "native-module-quantity-before-selection-20261029.png", "native-module-one-material-preview-20261029.png")
        cls.captures = tuple(captured_native_frame_from_png((FIXTURES / name).read_bytes(),
            path=SESSION / "frames" / f"{index}.png", captured_monotonic=float(index + 1))
            for index, name in enumerate(names))

    def context(self, captures=None, *, engine=None):
        modal, baseline, quantity, current = captures or self.captures
        return native.recognize_selection_context(current, modal=modal, baseline=baseline, quantity=quantity,
            variant="module", game_day_id="current-reset", ocr_engine=engine)

    @staticmethod
    def erased(capture, box):
        image = capture.frame.copy()
        x0, y0, x1, y1 = box
        image[y0:y1, x0:x1] = 0
        png = cv2.imencode(".png", image)[1].tobytes()
        return captured_native_frame_from_png(png, path=capture.path, captured_monotonic=capture.captured_monotonic)

    def route(self):
        modal, baseline, quantity, _ = self.captures
        runtime = SimpleNamespace(session=SESSION)
        route = native.EnhancementIntegratedRoute(runtime, variant="module", reset_identity="current-reset", session=object())
        route._selection_witnesses = dict(modal=modal, baseline=baseline, quantity=quantity)
        targets = self.context().diagnostics["selection_context_targets"]
        for identity, capture, target in (("open-enhance:module", modal, targets["modal_enhance"]),
                ("material-select:module", baseline, targets["baseline_card"]),
                ("quantity-use", quantity, targets["quantity_use"])):
            route.stages.append({"kind": "dispatch", "target_identity": identity,
                "frame_sha256": capture.sha256, "target_roi": target, "resource_affecting": False})
        return route

    def test_actual_four_frames_keep_committed_exp_and_read_moved_selected_card(self):
        self.assertEqual(self.captures[0].sha256, "567cccfd09bb14b9d2336e42e26fea0642d9a2c64e4b090c7583a45ebd478f42")
        self.assertEqual(self.captures[1].sha256, BASELINE_SHA)
        self.assertEqual(self.captures[2].sha256, "0906b6d90c123d5ccf535fdc53bad337a008e897b42c53e299f985a4c4a5eb25")
        self.assertEqual(self.captures[3].sha256, PREVIEW_SHA)
        self.assertEqual(native._material_cell_boxes(self.captures[1].frame), [OLD_BOX])
        self.assertEqual(native._material_cell_boxes(self.captures[3].frame), [CURRENT_BOX])
        result = self.context()
        self.assertTrue(result.recognized, result)
        observation = result.observation
        self.assertTrue(observation.item_equipped)
        self.assertEqual((observation.selected_item_identity, observation.item_level), ("fighter module", 18))
        self.assertEqual((observation.quantity, observation.material_inventory_count), (1, 8299))
        self.assertEqual(observation.material_slot_facts, ((0, 1, 1, 8299),))
        self.assertEqual((observation.item_exp_current, observation.item_exp_preview, observation.item_exp_required),
            (10, 20, 104500))
        self.assertEqual(observation.source_frame_sha256, PREVIEW_SHA)
        self.assertEqual(observation.evidence_refs, tuple(str(frame.path) for frame in
            (self.captures[3], self.captures[0], self.captures[1], self.captures[2])))
        self.assertEqual(observation.selection_baseline_frame_sha256, BASELINE_SHA)
        self.assertEqual(observation.selection_baseline_evidence_ref, str(self.captures[1].path))
        self.assertTrue(enhancement_bluestacks_authorizeable(observation, variant="module"))
        self.assertFalse(enhancement_bluestacks_postcondition_verified(observation, observation, variant="module"))

    def test_card_association_rejects_adjacent_reordered_extra_ambiguous_or_unbounded_cards(self):
        self.assertIsNotNone(native._material_card_translation(OLD_BOX, CURRENT_BOX))
        adjacent = (189, 612, 282, 705)
        for box in (adjacent, (79, 635, 172, 728), (70, 600, 180, 718)):
            with self.subTest(box=box):
                self.assertIsNone(native._material_card_translation(OLD_BOX, box))
        self.assertIsNone(native._material_card_translation((710, 612, 800, 705), (713, 615, 803, 708)))
        for old, current in (([OLD_BOX], [CURRENT_BOX, adjacent]),
                ([OLD_BOX, adjacent], [adjacent, CURRENT_BOX]),
                ([OLD_BOX, OLD_BOX], [CURRENT_BOX, CURRENT_BOX])):
            with self.subTest(old=old, current=current):
                self.assertIsNone(native._selection_card_translations(old, current))

    def test_literal_wrong_or_missing_selected_fraction_is_never_filled_from_baseline(self):
        for fraction in ((1, 299), (1, 8298), (2, 8299), None):
            with self.subTest(fraction=fraction), patch.object(native, "_selected_material_fraction", return_value=fraction):
                result = self.context()
                self.assertFalse(result.recognized)
                self.assertIsNone(result.observation)

    def test_missing_checkmark_and_unchanged_green_exp_cannot_authorize_selection(self):
        captures = list(self.captures)
        captures[3] = self.erased(captures[3], (85, 638, 165, 682))
        result = self.context(captures)
        self.assertFalse(result.recognized)
        self.assertIsNone(result.observation)

        def unchanged_exp(frame, roi):
            if roi == (300, 330, 505, 366):
                return [native.OcrHit("10/104500", roi)]
            return self.material_ocr(frame, roi) if roi == native.QUANTITY_MATERIAL_ROI else self.ocr(frame, roi)
        result = self.context(engine=unchanged_exp)
        self.assertFalse(result.recognized)
        self.assertIsNone(result.observation)

    def test_current_runtime_requires_exact_three_setup_sources_targets_and_order(self):
        route = self.route()
        current = self.captures[3]
        self.assertTrue(route._selected_material(current).recognized)
        original = list(map(dict, route.stages))
        for change in ("source", "target", "extra", "resource", "order"):
            route.stages = list(map(dict, original))
            if change == "source":
                route.stages[0]["frame_sha256"] = "a" * 64
            elif change == "target":
                route.stages[1]["target_roi"] = (1, 1, 2, 2)
            elif change == "extra":
                route.stages.append(dict(original[-1], target_identity="unrelated-input"))
            elif change == "resource":
                route.stages[0]["resource_affecting"] = True
            else:
                route.stages.reverse()
            with self.subTest(change=change):
                result = route._selected_material(current)
                self.assertFalse(result.recognized)
                self.assertIsNone(result.observation)
                self.assertFalse(route.resource_dispatch_keys)
        route.stages = original
        route.runtime.session = Path("a-different-current-session")
        self.assertFalse(route._selected_material(current).recognized)

    def test_fresh_changed_selection_stops_before_any_resource_transport(self):
        route = self.route()
        fresh = replace(self.captures[3], path=SESSION / "frames" / "fresh.png", captured_monotonic=5.)
        route.runtime.capture = lambda label: fresh
        inputs = []
        route.runtime.tap = lambda *args, **kwargs: inputs.append(kwargs)
        class Session:
            def run_action(self, *, capture, authorize, dispatch, **kwargs):
                source = capture("fresh-immediate-before")
                authorize(source)
                dispatch(source)
        route.session = Session()
        with patch.object(native, "_selected_material_fraction", return_value=(2, 8299)):
            with self.assertRaises(native._FlowBlocked):
                route._action(label="use-one-star-enhancer", identity="enhancement-use",
                    before_recognizer=route._selected_material, post_recognizer=lambda frame: None,
                    target_getter=lambda result: result.observation.target_roi, resource_affecting=True)
        self.assertFalse(inputs)
        self.assertFalse(route.resource_dispatch_keys)


if __name__ == "__main__":
    unittest.main()
