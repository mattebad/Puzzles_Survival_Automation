"""Actual selection preview needs its causal zero-selection and item witnesses."""
from contextlib import ExitStack
from dataclasses import replace
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import enhancement_bluestacks as native
from scripts.bluestacks_native_runtime import captured_native_frame_from_png
from tasks.enhancement import enhancement_bluestacks_authorizeable, enhancement_bluestacks_postcondition_verified


FIXTURES = Path(__file__).parent / "fixtures/enhancement_item_modal"
PREVIEW_SHA = "b563eb1c2fcff08feda3f6dfffdf2cd47d730a73323095ed4a57434b468f8e90"


class SelectionContextNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        original_ocr, original_label = native._default_ocr, native._material_label
        ocr_cache, label_cache = {}, {}
        def ocr(frame, roi):
            x0, y0, x1, y1 = roi
            key = roi, hashlib.sha256(frame[y0:y1, x0:x1].tobytes()).hexdigest()
            if key not in ocr_cache:
                ocr_cache[key] = original_ocr(frame, roi)
            return list(ocr_cache[key])
        def label(frame, box):
            x0, y0, x1, y1 = box
            key = box, hashlib.sha256(frame[y0:y1, x0:x1].tobytes()).hexdigest()
            if key not in label_cache:
                label_cache[key] = original_label(frame, box)
            return label_cache[key]
        cls.stack.enter_context(patch.object(native, "_default_ocr", side_effect=ocr))
        cls.stack.enter_context(patch.object(native, "_material_label", side_effect=label))
        names = ("native-gear-sof-suit-20261029.png", "native-gear-no-material-selected-20261029.png",
            "native-gear-quantity-one-20261029.png", "native-gear-one-material-preview-20261029.png")
        cls.captures = tuple(captured_native_frame_from_png((FIXTURES / name).read_bytes(),
            path=Path("unit-context/session/frames") / f"{index}.png", captured_monotonic=float(index + 1))
            for index, name in enumerate(names))

    def context(self, captures=None):
        modal, baseline, quantity, current = captures or self.captures
        return native.recognize_selection_context(current, modal=modal, baseline=baseline, quantity=quantity,
            variant="gear", game_day_id="current-reset")

    @staticmethod
    def erased(capture, box):
        changed = capture.frame.copy()
        x0, y0, x1, y1 = box
        changed[y0:y1, x0:x1] = 0
        ok, png = cv2.imencode(".png", changed)
        assert ok
        return captured_native_frame_from_png(png.tobytes(), path=capture.path,
            captured_monotonic=capture.captured_monotonic)

    def route(self):
        modal, baseline, quantity, _ = self.captures
        runtime = SimpleNamespace(session=Path("unit-context/session"))
        route = native.EnhancementIntegratedRoute(runtime, variant="gear", reset_identity="current-reset", session=object())
        route._selection_witnesses = dict(modal=modal, baseline=baseline, quantity=quantity)
        targets = self.context().diagnostics["selection_context_targets"]
        for identity, capture, target in (("open-enhance:gear", modal, targets["modal_enhance"]),
                ("material-select:gear", baseline, targets["baseline_card"]),
                ("quantity-use", quantity, targets["quantity_use"])):
            route.stages.append({"kind": "dispatch", "target_identity": identity,
                "frame_sha256": capture.sha256, "target_roi": target, "resource_affecting": False})
        return route

    def test_actual_selected_page_preserves_committed_baseline_and_separate_green_preview(self):
        result = self.context()
        self.assertEqual(self.captures[3].sha256, PREVIEW_SHA)
        self.assertTrue(result.recognized, result)
        observation = result.observation
        self.assertIsNotNone(observation)
        self.assertTrue(observation.item_equipped)
        self.assertEqual((observation.item_exp_current, observation.item_exp_preview, observation.item_exp_required), (10, 20, 260000))
        self.assertEqual(observation.material_slot_facts, ((0, 4, 0, 2), (1, 1, 1, 9562), (2, 0, 0, 100)))
        self.assertEqual(observation.material_inventory_count, 9562)
        self.assertEqual(observation.evidence_refs, tuple(str(frame.path) for frame in
            (self.captures[3], self.captures[0], self.captures[1], self.captures[2])))
        self.assertEqual(observation.selection_baseline_frame_sha256, self.captures[1].sha256)
        self.assertEqual(observation.selection_baseline_evidence_ref, str(self.captures[1].path))
        self.assertTrue(enhancement_bluestacks_authorizeable(observation))
        self.assertFalse(enhancement_bluestacks_postcondition_verified(observation, observation))

    def test_panel_alone_and_green_preview_are_never_committed_effect_or_equipment_proof(self):
        current = self.captures[3]
        for stage in ("material", "post"):
            result = native.recognize_commander_stage(current.frame, variant="gear", stage=stage,
                source_frame_sha256=current.sha256, evidence_ref=current.path, game_day_id="current-reset")
            self.assertIsNone(result.observation)
            self.assertEqual(result.diagnostics["exp_display_state"], "preview")
            if stage == "post":
                self.assertFalse(result.recognized)
        bad = list(self.captures)
        bad[1] = replace(current, path=bad[1].path, captured_monotonic=2.)
        self.assertFalse(self.context(bad).recognized)

    def test_hash_session_order_and_missing_current_unequip_quantity_witness_deny(self):
        for index, changed in ((0, self.erased(self.captures[0], native.GEAR_DETAIL_FOOTER_ROIS["unequip"])),
                (2, self.erased(self.captures[2], (508, 670, 623, 710))),
                (1, replace(self.captures[1], path=Path("historical/frames/old.png"))),
                (1, replace(self.captures[1], captured_monotonic=4.5)),
                (3, replace(self.captures[3], sha256="a" * 64))):
            with self.subTest(index=index, path=changed.path):
                captures = list(self.captures)
                captures[index] = changed
                result = self.context(captures)
                self.assertFalse(result.recognized, result)
                self.assertIsNone(result.observation)

    def test_changed_stock_quantity_other_material_or_missing_check_and_confirm_deny(self):
        for read in ((1, 562), (1, 9561), (2, 9562), None):
            with self.subTest(read=read), patch.object(native, "_selected_material_fraction", return_value=read):
                self.assertFalse(self.context().recognized)
        for box in ((209, 638, 260, 677), (480, 1180, 660, 1246), (335, 620, 390, 636)):
            captures = list(self.captures)
            captures[3] = self.erased(captures[3], box)
            self.assertFalse(self.context(captures).recognized)

    def test_selected_border_keeps_row_major_slot_identity(self):
        old = native._material_cell_boxes(self.captures[1].frame)
        current = native._material_cell_boxes(self.captures[3].frame)
        self.assertEqual(len(current), 3)
        self.assertEqual(current[1], (187, 611, 284, 707))
        self.assertTrue(all(max(abs(a - b) for a, b in zip(before, after)) <= 3 for before, after in zip(old, current)))
        label = native._material_label(self.captures[1].frame, old[1])[1]
        self.assertEqual(native._selected_material_fraction(self.captures[3].frame, label), (1, 9562))

    def test_native_consumer_requires_exact_current_run_navigation_sources_and_targets(self):
        route = self.route()
        current = self.captures[3]
        self.assertTrue(route._selected_material(current).recognized)
        original = list(map(dict, route.stages))
        for change in ("source", "target", "extra"):
            route.stages = list(map(dict, original))
            if change == "source":
                route.stages[0]["frame_sha256"] = "a" * 64
            elif change == "target":
                route.stages[1]["target_roi"] = (1, 1, 2, 2)
            else:
                route.stages.append(dict(original[-1], target_identity="unrelated-input"))
            result = route._selected_material(current)
            self.assertFalse(result.recognized)
            self.assertIsNone(result.observation)
        route.stages = original
        route.runtime.session = Path("a-different-live-session")
        self.assertFalse(route._selected_material(current).recognized)

    def test_fresh_changed_selection_prevents_resource_dispatch(self):
        route = self.route()
        current = replace(self.captures[3], path=Path("unit-context/session/frames/fresh.png"), captured_monotonic=5.)
        route.runtime.capture = lambda label: current
        def forbidden(*args, **kwargs):
            self.fail("changed selection cannot send any transport")
        route.runtime.tap = forbidden
        class Session:
            def run_action(self, *, capture, authorize, dispatch, **kwargs):
                source = capture("fresh-immediate-before")
                authorize(source)
                forbidden()
        route.session = Session()
        with patch.object(native, "_selected_material_fraction", return_value=(2, 9562)):
            with self.assertRaises(native._FlowBlocked):
                route._action(label="use-one-star-enhancer", identity="enhancement-use",
                    before_recognizer=route._selected_material, post_recognizer=forbidden,
                    target_getter=lambda result: result.observation.target_roi, resource_affecting=True)
        self.assertEqual(route.resource_dispatch_keys, [])


if __name__ == "__main__":
    unittest.main()
