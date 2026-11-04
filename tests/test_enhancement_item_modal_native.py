"""Native Gear detail proof and one-selection animation settlement; no device access."""
from dataclasses import replace
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
from tests.ocr_memo import install_module_memo
from tests.support.environment import requires_tesseract


def setUpModule():
    # Identical frames are replayed across tests; run real Tesseract once per unique input.
    install_module_memo()


FIXTURE = Path(__file__).parent / "fixtures/enhancement_item_modal/native-gear-sof-suit-20261029.png"
# Exact bytes copied from the failed, zero-Use canonical attempt's frame 0007:
# .local-captures/automation-service-authorized/enhancement-20261029T104929619983Z/
# enhancement-20261029T104929637700Z-3d4fe933/runtime/
# enhancement-family-20261029T104930494057Z/frames/0007-open-enhance-panel-immediate-before.png
FIXTURE_SHA256 = "d461f5ded242611154b6bcdd11039d1eff01dc36919540bccfeb3c5bf51e9893"
STAT_BULLET_FIXTURE = FIXTURE.with_name("native-gear-sof-suit-stat-bullet-20261029.png")
STAT_BULLET_SHA256 = "0a304b522d49a3259d5fda87a6a310004b9b5ece785fcf513a66abaf07b2d8db"
NO_SELECTION_FIXTURE = FIXTURE.with_name("native-gear-no-material-selected-20261029.png")
NO_SELECTION_SHA256 = "1d4f55bc15b7ea6035d8870b0b7f6a025aa7420403890ecbbe8d76f0103fbe33"
STAR_OCR_FIXTURE = FIXTURE.with_name("native-gear-sof-suit-star-x-20261031.png")
STAR_OCR_SHA256 = "e59f0fc6e2b22045bcbc1f011a802ea39ebe0c57b456e89242f31e66fc1e81b3"


class NativeItemModalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = FIXTURE.read_bytes()
        cls.frame = cv2.imdecode(np.frombuffer(cls.raw, np.uint8), cv2.IMREAD_COLOR)

    @classmethod
    def modal_result(cls):
        if not hasattr(cls, "_cached_modal"):
            cls._cached_modal = native.recognize_commander_stage(cls.frame, variant="gear", stage="item",
                source_frame_sha256=FIXTURE_SHA256, evidence_ref=FIXTURE, game_day_id="current-reset")
        return cls._cached_modal

    @requires_tesseract
    def test_real_native_modal_binds_actual_identity_level_and_unique_enhance(self):
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), FIXTURE_SHA256)
        result = self.modal_result()
        self.assertTrue(result.recognized, result)
        self.assertEqual(result.reason, "GEAR_ITEM_DETAIL_MODAL_RECOGNIZED")
        self.assertEqual(result.frame_sha256, FIXTURE_SHA256)
        self.assertEqual((result.item_identity, result.item_level), ("s.o.f suit", 18))
        self.assertTrue(result.category_selected)
        self.assertEqual(result.open_target, (152, 907, 259, 948))
        self.assertIsNone(result.item_target)
        self.assertIsNone(result.observation)
        self.assertFalse(result.material_selected)
        self.assertIsNone(result.quantity)
        self.assertEqual(result.detail_state, "item_modal")
        self.assertEqual(result.close_target, (662, 339, 714, 391))

    @requires_tesseract
    def test_missing_actual_title_level_star_stats_or_footer_control_never_binds(self):
        for missing in (native.GEAR_DETAIL_TITLE_ROI, native.GEAR_DETAIL_LEVEL_ROI,
                (379, 501, 422, 540), (125, 690, 700, 730),
                native.GEAR_DETAIL_FOOTER_ROIS["enhance"], native.GEAR_DETAIL_FOOTER_ROIS["unequip"]):
            with self.subTest(missing=missing):
                changed = self.frame.copy()
                x0, y0, x1, y1 = missing
                changed[y0:y1, x0:x1] = 0
                result = native.recognize_commander_stage(changed, variant="gear", stage="item")
                self.assertFalse(result.recognized, result)
                self.assertIsNone(result.open_target)

    @requires_tesseract
    def test_current_native_star_ocr_binds_item_navigation_without_resource_authority(self):
        raw = STAR_OCR_FIXTURE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), STAR_OCR_SHA256)
        frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        result = native.recognize_commander_stage(frame, variant="gear", stage="item",
            source_frame_sha256=STAR_OCR_SHA256, evidence_ref=STAR_OCR_FIXTURE)
        self.assertTrue(result.recognized, result)
        self.assertEqual((result.item_identity, result.item_level), ("s.o.f suit", 18))
        self.assertIsNotNone(result.open_target)
        self.assertIsNotNone(result.close_target)
        self.assertIsNone(result.observation)
        self.assertFalse(result.material_selected)
        changed = frame.copy()
        changed[501:540, 379:422] = 0
        denied = native.recognize_commander_stage(changed, variant="gear", stage="item")
        self.assertFalse(denied.recognized)
        self.assertIsNone(denied.open_target)

    @requires_tesseract
    def test_star_alias_preserves_exact_rarity_and_item_identity(self):
        for title in ("6q S.O.F Suit", "7x S.O.F Suit", "6x S.O.F Boots"):
            def ocr(frame, roi):
                if roi == native.GEAR_DETAIL_TITLE_ROI:
                    return [native.OcrHit(title, (305, 353, 490, 376))]
                return native._default_ocr(frame, roi)
            with self.subTest(title=title):
                result = native.recognize_commander_stage(self.frame, variant="gear", stage="item", ocr_engine=ocr)
                self.assertFalse(result.recognized)
                self.assertIsNone(result.open_target)

    @requires_tesseract
    def test_current_stat_bullet_variation_keeps_semantic_rows_and_actual_control(self):
        raw = STAT_BULLET_FIXTURE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), STAT_BULLET_SHA256)
        frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        modal = self.modal_result()
        result = native.recognize_commander_stage(frame, variant="gear", stage="item",
            source_frame_sha256=STAT_BULLET_SHA256, evidence_ref=STAT_BULLET_FIXTURE)
        self.assertTrue(result.recognized, result)
        self.assertEqual((result.item_identity, result.item_level), (modal.item_identity, modal.item_level))
        self.assertEqual((result.open_target, result.close_target), (modal.open_target, modal.close_target))
        self.assertEqual([row["label"] for row in result.diagnostics["stat_rows"]], ["fighter atk", "shooter def", "shooter hp"])
        self.assertEqual([row["value"] for row in result.diagnostics["stat_rows"]], ["149%"] * 3)
        for missing in ((125, 645, 300, 690), (600, 645, 705, 690)):
            with self.subTest(missing=missing):
                changed = frame.copy()
                x0, y0, x1, y1 = missing
                changed[y0:y1, x0:x1] = 0
                denied = native.recognize_commander_stage(changed, variant="gear", stage="item")
                self.assertFalse(denied.recognized, denied)
                self.assertEqual(denied.reason, "GEAR_ITEM_MODAL_STAT_ROW_NOT_RECOGNIZED")
                self.assertIsNone(denied.open_target)

    @requires_tesseract
    def test_duplicate_enhance_and_wrong_variant_or_use_stage_do_not_gain_authority(self):
        def duplicated(frame, roi):
            hits = native._default_ocr(frame, roi)
            if roi == native.GEAR_DETAIL_FOOTER_ROIS["enhance"]:
                hits.append(native.OcrHit("Enhance", (160, 941, 240, 948)))
            return hits
        ambiguous = native.recognize_commander_stage(self.frame, variant="gear", stage="item", ocr_engine=duplicated)
        self.assertFalse(ambiguous.recognized)
        for variant, stage in (("chip", "item"), ("module", "item"), ("gear", "material"), ("gear", "post")):
            with self.subTest(variant=variant, stage=stage):
                result = native.recognize_commander_stage(self.frame, variant=variant, stage=stage)
                self.assertFalse(result.recognized, result)
                self.assertIsNone(result.observation)

    @requires_tesseract
    def test_actual_zero_selection_panel_reports_facts_and_denies_resource(self):
        raw = NO_SELECTION_FIXTURE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), NO_SELECTION_SHA256)
        frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        for stage in ("material", "post"):
            with self.subTest(stage=stage):
                result = native.recognize_commander_stage(frame, variant="gear", stage=stage,
                    source_frame_sha256=NO_SELECTION_SHA256, evidence_ref=NO_SELECTION_FIXTURE)
                self.assertTrue(result.recognized, result)
                self.assertEqual(result.detail_state, "enhancement_panel")
                self.assertEqual((result.item_identity, result.item_level), ("s.o.f suit", 18))
                self.assertEqual((result.diagnostics["item_exp_current"], result.diagnostics["item_exp_required"]), (10, 260000))
                self.assertIsNone(result.open_target)
                self.assertEqual(result.quantity, 0)
                self.assertTrue(result.diagnostics["material_facts_verified"])
                self.assertEqual(result.observation.material_slot_facts, ((0, 4, 0, 2), (1, 1, 0, 9562), (2, 0, 0, 100)))
                self.assertEqual(result.observation.material_inventory_count, 9562)
                self.assertFalse(result.observation.item_equipped)
                self.assertFalse(native.enhancement_bluestacks_authorizeable(result.observation))
                self.assertFalse(native.enhancement_bluestacks_postcondition_verified(result.observation, result.observation))
                self.assertEqual(result.material_target, (189, 612, 282, 705))

    def _route(self, frames, *, family=False):
        test = self
        modal = self.modal_result() if "modal" in frames else None
        overview_image = np.full((1280, 800, 3), 250, np.uint8)
        overview_raw = cv2.imencode(".png", overview_image)[1].tobytes()
        overview = native.StageRecognition("item", True, "COMMANDER_INFO_ICON_OVERVIEW_RECOGNIZED",
            hashlib.sha256(overview_raw).hexdigest(), item_identity="gear-red-star-chest-armor",
            category_selected=True, item_target=native.GEAR_RED_STAR_ARMOR_ROI)
        class Runtime:
            def __init__(self):
                self.ordinal, self.inputs, self.captures = 0, [], []
                self.session = Path("offline-enhancement-item-modal")
            def capture(self, label):
                state = frames[self.ordinal]
                self.ordinal += 1
                self.captures.append((label, state))
                return captured_native_frame_from_png(test.raw if state == "modal" else overview_raw,
                    path=Path(f"offline-{self.ordinal}.png"), captured_monotonic=float(self.ordinal))
            def tap(self, before, **kwargs):
                self.inputs.append(kwargs)
                if kwargs["target_identity"] == "open-enhance:gear":
                    raise native._FlowBlocked("OFFLINE_STOP_AFTER_BOUND_ENHANCE")
        runtime = Runtime()
        class Session:
            def observe(self, capture, *, label):
                return capture(label)
            def run_action(self, *, label, capture, authorize, dispatch, recognize, settled_successor, **kwargs):
                before = capture(f"{label}-immediate-before")
                authorize(before)
                dispatch(before)
                after = capture(f"{label}-immediate-post")
                state = recognize(after)
                if state == "unknown" and settled_successor is not None:
                    after = settled_successor()
                    state = recognize(after)
                return SimpleNamespace(status="completed" if state != "unknown" else "unknown")
        session = Session()
        def recognize(frame, *, variant, stage, source_frame_sha256=None, **kwargs):
            digest = source_frame_sha256 or frame.sha256
            image = frame.frame if hasattr(frame, "frame") else frame
            if stage == "item":
                return replace(overview if int(image[10, 10, 0]) == 250 else modal, frame_sha256=digest)
            return native.StageRecognition(stage, False, "NO_MATERIAL_PROOF", digest)
        route = native.EnhancementIntegratedRoute(runtime, variant="gear", reset_identity="current-reset",
            session=session, variants=native.ORDERED_VARIANTS if family else None)
        with patch.object(native, "recognize_commander_stage", side_effect=recognize), patch.object(native.time, "sleep"):
            if family:
                result = route.run()
            else:
                source = captured_native_frame_from_png(overview_raw, path=Path("offline-source.png"), captured_monotonic=0.)
                result = route._run_single(start_at_commander=True, source_frame=source, initial_recognition=overview)
        return runtime, result

    @requires_tesseract
    def test_selection_waits_for_actual_modal_without_repeating_item_tap(self):
        runtime, result = self._route(["overview", "overview", "overview", "modal", "modal"])
        self.assertEqual([row["target_identity"] for row in runtime.inputs], ["item-select:gear", "open-enhance:gear"])
        self.assertEqual(runtime.inputs[-1]["target_roi"], self.modal_result().open_target)
        self.assertEqual(result["resource_affecting_dispatch_count"], 0)
        self.assertTrue(any(row.get("reason") == "SELECTED_ITEM_DETAIL_NOT_OPEN" for row in result["stages"]))

    def test_unchanged_overview_exhausts_only_bounded_observations_and_blocks(self):
        runtime, result = self._route(["overview"] * 5)
        self.assertEqual([row["target_identity"] for row in runtime.inputs], ["item-select:gear"])
        self.assertEqual(len([label for label, _ in runtime.captures if "settled" in label]), native.MAX_SETTLE_POLLS)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("SELECTED_ITEM_DETAIL_NOT_OPEN", result["reason"])
        self.assertEqual(result["resource_affecting_dispatch_count"], 0)

    @requires_tesseract
    def test_family_startup_current_modal_proceeds_to_enhance_with_zero_new_selection(self):
        runtime, result = self._route(["modal", "modal"], family=True)
        self.assertEqual([row["target_identity"] for row in runtime.inputs], ["open-enhance:gear"])
        self.assertEqual(runtime.inputs[0]["target_roi"], self.modal_result().open_target)
        self.assertEqual(result["resource_affecting_dispatch_count"], 0)


class NativeEnhancementExitTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.modal = FIXTURE.read_bytes()
        self.commander = FIXTURE.with_name("native-commander-gear-20261029.png").read_bytes()
        self.home = (Path(__file__).parent / "fixtures/home_base/native-home-bio-zoomed-20261029.png").read_bytes()
        original_ocr = native._default_ocr
        cache = {}
        def ocr(frame, roi):
            x0, y0, x1, y1 = roi
            key = (roi, hashlib.sha256(frame[y0:y1, x0:x1].tobytes()).hexdigest())
            if key not in cache:
                cache[key] = original_ocr(frame, roi)
            return list(cache[key])
        self.stack.enter_context(patch.object(native, "_default_ocr", side_effect=ocr))
        self.stack.enter_context(patch.object(native.time, "sleep"))

    @requires_tesseract
    def test_native_modal_x_and_commander_arrow_recover_home_with_zero_use(self):
        self.assertEqual(hashlib.sha256(self.commander).hexdigest(), "4e98c17ff9a07c535d663fb4f7fca6eb3dc60d019c9908cb60a1758067eaeaba")
        runtime, session = exit_runtime([self.modal, self.modal, self.commander, self.commander, self.home])
        result = native.run_recovery(runtime, variant="gear", reset_identity="current-reset", session=session, navigation_only=True)
        self.assertEqual(result["status"], "recovered_safe", result)
        self.assertTrue(result["terminal_home_verified"])
        self.assertEqual(result["dispatch_count"], 2)
        self.assertEqual(result["resource_affecting_dispatch_count"], 0)
        self.assertIsNone(result["successor_observation"])
        self.assertEqual([row["target_identity"] for row in runtime.inputs], ["item-detail-close", "commander-visible-back"])
        self.assertEqual([row["target_roi"] for row in runtime.inputs], [(662, 339, 714, 391), (48, 2, 129, 61)])
        self.assertEqual([status for _, status, _ in runtime.journal], ["confirmed", "confirmed"])

    @requires_tesseract
    def test_changed_modal_x_or_missing_commander_arrow_cannot_get_a_blind_tap(self):
        for defect in ("close", "back"):
            with self.subTest(defect=defect):
                frame = cv2.imdecode(np.frombuffer(self.modal if defect == "close" else self.commander, np.uint8), cv2.IMREAD_COLOR)
                if defect == "close":
                    frame[330:400, 640:735] = 0
                else:
                    frame[:90, :180] = 0
                raw = cv2.imencode(".png", frame)[1].tobytes()
                payloads = [self.modal, raw] if defect == "close" else [self.modal, self.modal] + [raw] * 4
                runtime, session = exit_runtime(payloads)
                result = native.run_recovery(runtime, variant="gear", reset_identity="current-reset", session=session, navigation_only=True)
                self.assertEqual(result["status"], "evidence_required", result)
                self.assertEqual(len(runtime.inputs), 0 if defect == "close" else 1)
                self.assertEqual(result["resource_affecting_dispatch_count"], 0)
                self.assertFalse(result["terminal_home_verified"])

    @requires_tesseract
    def test_unknown_or_unchanged_exit_successor_blocks_without_repeating_x(self):
        for successor in (self.modal, cv2.imencode(".png", np.zeros((1280, 800, 3), np.uint8))[1].tobytes()):
            with self.subTest(successor_sha=hashlib.sha256(successor).hexdigest()):
                runtime, session = exit_runtime([self.modal, self.modal] + [successor] * 4)
                result = native.run_recovery(runtime, variant="gear", reset_identity="current-reset", session=session, navigation_only=True)
                self.assertEqual(result["status"], "evidence_required", result)
                self.assertEqual(len(runtime.inputs), 1)
                self.assertEqual(runtime.inputs[0]["target_identity"], "item-detail-close")
                self.assertEqual(runtime.journal[0][1], "unresolved")

    @requires_tesseract
    def test_known_home_needs_zero_input_and_post_recovery_default_stays_observe_only(self):
        runtime, session = exit_runtime([self.home])
        result = native.run_recovery(runtime, variant="gear", reset_identity="current-reset", session=session, navigation_only=True)
        self.assertEqual((result["status"], result["dispatch_count"]), ("recovered_safe", 0))
        self.assertFalse(runtime.inputs)
        runtime, session = exit_runtime([self.modal])
        pending = native.run_recovery(runtime, variant="gear", reset_identity="current-reset", session=session)
        self.assertEqual(pending["status"], "evidence_required")
        self.assertFalse(runtime.inputs)

    def test_confirmed_post_without_a_visible_back_stops_for_inspection(self):
        runtime, session = exit_runtime([self.commander])
        route = native.EnhancementIntegratedRoute(runtime, variant="gear", reset_identity="current-reset", session=session)
        unknown = native.StageRecognition("post", True, "CONFIRMED_EXP_SUCCESSOR", "1" * 64)
        with patch.object(route, "_navigation_state", return_value=replace(unknown, detail_state="enhancement_post")):
            with self.assertRaises(native._FlowBlocked):
                route._navigate_to("home", allow_post=True)
        self.assertFalse(runtime.inputs)

    @requires_tesseract
    def test_known_enhancement_page_exits_without_material_or_effect_authority(self):
        panel = NO_SELECTION_FIXTURE.read_bytes()
        runtime, session = exit_runtime([panel, panel, self.modal, self.modal, self.commander, self.commander, self.home])
        result = native.run_recovery(runtime, variant="gear", reset_identity="current-reset", session=session, navigation_only=True)
        self.assertEqual((result["status"], result["dispatch_count"], result["resource_affecting_dispatch_count"]), ("recovered_safe", 3, 0))
        self.assertTrue(result["terminal_home_verified"])
        self.assertIsNone(result["successor_observation"])
        self.assertEqual([row["target_identity"] for row in runtime.inputs], ["enhancement-visible-back", "item-detail-close", "commander-visible-back"])
        self.assertEqual(runtime.inputs[0]["target_roi"], (47, 2, 128, 61))
        runtime, session = exit_runtime([panel])
        pending = native.run_recovery(runtime, variant="gear", reset_identity="current-reset", session=session)
        self.assertEqual(pending["status"], "evidence_required")
        self.assertEqual(pending["successor_observation"]["material_quantity"], 0)
        self.assertFalse(pending["semantic_successor_proven"])
        self.assertFalse(runtime.inputs)

    @requires_tesseract
    def test_current_panel_consumer_stops_before_any_resource_input(self):
        raw = NO_SELECTION_FIXTURE.read_bytes()
        runtime, session = exit_runtime([raw])
        capture = captured_native_frame_from_png(raw, path=NO_SELECTION_FIXTURE, captured_monotonic=0.)
        observed = native.recognize_commander_stage(capture.frame, variant="gear", stage="material",
            source_frame_sha256=capture.sha256, evidence_ref=capture.path)
        route = native.EnhancementIntegratedRoute(runtime, variant="gear", reset_identity="current-reset", session=session)
        result = route._run_single(start_at_commander=True, source_frame=capture, initial_recognition=observed)
        self.assertEqual(result["status"], "blocked", result)
        self.assertEqual(result["resource_affecting_dispatch_count"], 0)
        # A retained/current panel alone cannot replace this run's equipped
        # modal and zero-selection navigation witnesses.
        self.assertFalse(runtime.inputs)
        self.assertEqual(result["dispatch_count"], 0)


if __name__ == "__main__":
    unittest.main()
