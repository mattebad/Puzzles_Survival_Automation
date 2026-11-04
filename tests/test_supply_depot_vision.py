from __future__ import annotations

from collections import deque
from contextlib import ExitStack
from pathlib import Path
import math
from unittest.mock import patch
import cv2
import time
from dataclasses import replace
import unittest

import numpy as np

from tasks.home_atlas_vision import BLUESTACKS_PROFILE_ID, frame_digest
from tasks.perception_bundle import NativeFrameIdentity
from tasks import supply_depot_vision as supply_depot_module
from tasks.supply_depot_vision import (
    _claim_label_row_from_data,
    bind_supply_depot_claim_supply,
    recognize_supply_depot_screen,
    recognize_supply_depot_radial,
)
from tests.support.environment import requires_ocr_worker, requires_tesseract


def queued_ocr(*values: str):
    queue = deque(values)

    def ocr(_image, _psm):
        if not queue:
            raise AssertionError("unexpected OCR call")
        return queue.popleft()

    return ocr


def screen_ocr(*, attempts: str = "Daily free attempts: 9", panel: str = "", controls: tuple[str, ...] = ("Free",) * 4):
    values = ["Supply Depot", "Supply Depot", attempts, attempts, panel]
    for control in controls:
        values.extend((control, control))
    return queued_ocr(*values)


class FixtureScreenOcr:
    def __init__(self, fail_region: str | None = None) -> None:
        self.fail_region = fail_region

    def __call__(self, image: np.ndarray, _psm: int) -> str:
        pixel = image[image.shape[0] // 2, image.shape[1] // 2]
        marker = int(pixel if np.ndim(pixel) == 0 else pixel[0])
        region, text = {
            10: ("title", "Supply Depot"),
            20: ("attempts", "Daily free attempts: 9"),
            30: ("panel", ""),
            40: ("control_0", "Free"),
            50: ("control_1", "Free"),
            60: ("control_2", "Free"),
            70: ("control_3", "Free"),
        }[marker]
        if region == self.fail_region:
            raise RuntimeError("adversarial OCR engine failure")
        return text


def frame_identity(
    frame: np.ndarray,
    *,
    session: str = "capture-session",
    ordinal: int = 1,
    monotonic: float = 1000.0,
) -> NativeFrameIdentity:
    digest = frame_digest(frame)
    return NativeFrameIdentity(
        capture_kind="fixture",
        runtime_session_id=session,
        capture_ordinal=ordinal,
        capture_completed_monotonic=monotonic,
        transport_sha256=digest,
        semantic_sha256="b" * 64,
        runtime_profile_id=BLUESTACKS_PROFILE_ID,
        width=800,
        height=1280,
    )


class SupplyDepotVisionTests(unittest.TestCase):
    def test_details_icon_candidate_alone_cannot_establish_menu_identity_or_target(self):
        path = supply_depot_module._DETAILS_ICON_PATH
        glyph = cv2.imread(str(path))
        frame = np.zeros((1280, 800, 3), np.uint8)
        frame[780:823, 480:518] = glyph
        self.assertFalse(recognize_supply_depot_radial(frame, ocr=lambda *_: "Details"))
        with patch("scripts.bluestacks_popup_recognition.recognize_reset_popup", return_value={}):
            self.assertIsNone(bind_supply_depot_claim_supply(frame, ocr=lambda *_: "Details"))

    @requires_tesseract
    @requires_ocr_worker
    def test_native_collapsed_drawer_keeps_safe_button_despite_covered_lower_caption(self):
        from scripts.bluestacks_native_runtime import captured_native_frame_from_png
        from scripts.home_atlas_bluestacks import identity_from_captured

        path = Path(__file__).parent / "fixtures/supply_depot/native-drawer-collapsed-radial-20261101.png"
        captured = captured_native_frame_from_png(path.read_bytes(), path=path, captured_monotonic=time.monotonic())
        identity = identity_from_captured(captured, session_id="offline-supply-collapsed-drawer", ordinal=1)
        self.assertEqual(supply_depot_module.bind_home_event_drawer_toggle(captured.frame, expanded=False),
                         (728, 1058, 765, 1076))
        self.assertIsNone(supply_depot_module.bind_home_event_drawer_toggle(captured.frame, expanded=True))
        binding = bind_supply_depot_claim_supply(captured.frame, source_frame=identity, source_png=captured.png)
        self.assertIsNotNone(binding, self.native_ocr_diagnostics)
        self.assertEqual((binding.target_roi[2] - binding.target_roi[0],
                          binding.target_roi[3] - binding.target_roi[1]), (16, 12))
        for point in (binding.target_roi[:2], binding.target_roi[2:],
                      (binding.target_roi[0], binding.target_roi[3]),
                      (binding.target_roi[2], binding.target_roi[1])):
            self.assertLess(math.dist(point, (686, 853)), 36)
        self.assertEqual(binding.frame_sha256, frame_digest(captured.frame))
        self.assertFalse(any(binding.target_roi[0] < x1 and binding.target_roi[2] > x0
            and binding.target_roi[1] < y1 and binding.target_roi[3] > y0
            for x0, y0, x1, y1 in supply_depot_module.HUD_MASK_RECTS))

    def test_native_expanded_drawer_binds_only_its_unique_down_chevron(self):
        path = Path(__file__).parent / "fixtures/supply_depot/native-drawer-occluded-radial-20261101.png"
        frame = cv2.imread(str(path))
        bind = supply_depot_module.bind_home_event_drawer_toggle
        self.assertEqual(bind(frame, expanded=True), (729, 1057, 764, 1075))
        self.assertIsNone(bind(frame, expanded=False))
        erased = frame.copy()
        erased[1057:1075, 729:764] = 0
        self.assertIsNone(bind(erased, expanded=True))
        # A synthetic reversed glyph checks direction discrimination only;
        # it is not retained live proof of a collapsed drawer.
        reversed_arrow = frame.copy()
        reversed_arrow[1061:1071, 733:760] = np.flipud(frame[1061:1071, 733:760])
        self.assertIsNone(bind(reversed_arrow, expanded=True))
        self.assertEqual(bind(reversed_arrow, expanded=False), (729, 1057, 764, 1075))
        duplicate = frame.copy()
        duplicate[1061:1071, 690:717] = frame[1061:1071, 733:760]
        self.assertIsNone(bind(duplicate, expanded=True))
        no_rail = frame.copy()
        no_rail[1048:1084, 600:790] = 150
        no_rail[1061:1071, 733:760] = frame[1061:1071, 733:760]
        self.assertIsNone(bind(no_rail, expanded=True))
        for name in ("native-raised-radial-20261029.png", "native-facility-20261029.png"):
            self.assertIsNone(bind(cv2.imread(str(path.parent / name)), expanded=True), name)

    @requires_tesseract
    @requires_ocr_worker
    def test_native_exhausted_capture_keeps_identity_across_scene_animation(self):
        from scripts.bluestacks_native_runtime import captured_native_frame_from_png
        from scripts.home_atlas_bluestacks import identity_from_captured
        from scripts.supply_depot_free_route import exhausted_free_state

        root = Path(__file__).parent / "fixtures/supply_depot"
        path = root / "native-exhausted-20261029.png"
        captured = captured_native_frame_from_png(path.read_bytes(), path=path, captured_monotonic=time.monotonic())
        earlier = cv2.imread(str(root / "native-facility-20261029.png"))
        self.assertFalse(np.array_equal(earlier[70:], captured.frame[70:]))
        identity = identity_from_captured(captured, session_id="offline-supply-exhausted", ordinal=1)
        result = recognize_supply_depot_screen(captured.frame, source_frame=identity, source_png=captured.png)
        self.assertTrue(result.recognized, result)
        self.assertEqual(result.daily_free_attempts, 0)
        self.assertTrue(exhausted_free_state(result))
        self.assertTrue(all(not control.zero_cost for control in result.controls))

    @requires_tesseract
    @requires_ocr_worker
    def test_native_scene_cannot_replace_missing_or_wrong_header(self):
        from scripts.bluestacks_native_runtime import captured_native_frame_from_png
        from scripts.home_atlas_bluestacks import identity_from_captured

        path = Path(__file__).parent / "fixtures/supply_depot/native-exhausted-20261029.png"
        frame = cv2.imread(str(path))
        x0, y0, x1, y1 = supply_depot_module.SUPPLY_DEPOT_TITLE_ROI
        for wrong_title in ("", "Research Lab"):
            with self.subTest(title=wrong_title):
                changed = frame.copy()
                changed[y0:y1, x0:x1] = 0
                if wrong_title:
                    cv2.putText(changed, wrong_title, (x0 + 20, y0 + 42), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                payload = cv2.imencode(".png", changed)[1].tobytes()
                captured = captured_native_frame_from_png(payload, path=path, captured_monotonic=time.monotonic())
                identity = identity_from_captured(captured, session_id="offline-supply-header-negative", ordinal=1)
                result = recognize_supply_depot_screen(captured.frame, source_frame=identity, source_png=captured.png)
                self.assertFalse(result.recognized)
                self.assertEqual(result.controls, ())

    @requires_tesseract
    @requires_ocr_worker
    def test_original_native_capture_recognizes_free_controls_with_explicit_identity(self):
        from scripts.bluestacks_native_runtime import captured_native_frame_from_png
        from scripts.home_atlas_bluestacks import identity_from_captured

        path = Path(__file__).parent / "fixtures/supply_depot/native-facility-20261029.png"
        captured = captured_native_frame_from_png(path.read_bytes(), path=path, captured_monotonic=time.monotonic())
        identity = identity_from_captured(captured, session_id="offline-supply", ordinal=1)
        self.assertNotEqual(identity.transport_sha256, identity.semantic_sha256)
        result = recognize_supply_depot_screen(captured.frame, source_frame=identity, source_png=captured.png)
        self.assertTrue(result.recognized, result)
        self.assertEqual(result.state, "available")
        self.assertEqual(result.daily_free_attempts, 9)
        self.assertTrue(all(control.zero_cost for control in result.controls))
        rejected = recognize_supply_depot_screen(captured.frame, source_frame=identity, source_png=captured.png + b"changed")
        self.assertFalse(rejected.recognized)
        self.assertEqual(rejected.controls, ())

    def setUp(self):
        self.native_ocr_diagnostics = []
        original_ocr = supply_depot_module.run_semantic_ocr
        def observe_ocr(*args, **kwargs):
            result = original_ocr(*args, **kwargs)
            self.native_ocr_diagnostics.append({
                "roi": args[1].roi, "status": str(result.status),
                "reason": result.reason_code, "text": result.text,
            })
            return result
        observer = patch.object(supply_depot_module, "run_semantic_ocr", side_effect=observe_ocr)
        observer.start()
        self.addCleanup(observer.stop)
        self.frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        regions = (
            (supply_depot_module.SUPPLY_DEPOT_TITLE_ROI, 10),
            (supply_depot_module.SUPPLY_DEPOT_ATTEMPTS_ROI, 20),
            (supply_depot_module.SUPPLY_DEPOT_PANEL_ROI, 30),
            *((roi, 40 + 10 * index) for index, roi in enumerate(
                supply_depot_module.SUPPLY_DEPOT_CONTROL_BANDS
            )),
        )
        for (x0, y0, x1, y1), marker in regions:
            self.frame[y0:y1, x0:x1] = marker

    def test_exact_screen_reads_every_free_control_and_attempt_count(self):
        result = recognize_supply_depot_screen(self.frame, ocr=screen_ocr())
        self.assertTrue(result.recognized)
        self.assertEqual(result.state, "available")
        self.assertEqual(result.daily_free_attempts, 9)
        self.assertEqual([item.reward_kind for item in result.controls], ["food", "wood", "steel", "gas"])
        self.assertTrue(all(item.state == "available_free" and item.zero_cost for item in result.controls))
        self.assertFalse(result.premium_or_purchase_visible)
        self.assertEqual(result.ambiguity, "none")

    def test_stylized_zero_attempt_count_is_read_as_zero(self):
        result = recognize_supply_depot_screen(
            self.frame,
            ocr=screen_ocr(attempts="Daily free attempts: O", controls=("diamond 2",) * 4),
        )
        self.assertTrue(result.recognized)
        self.assertEqual(result.daily_free_attempts, 0)
        self.assertEqual(result.state, "paid_or_purchase")
        self.assertEqual(result.ambiguity, "none")

    def test_cooldown_exhausted_and_purchase_states_are_separate(self):
        cooldown = recognize_supply_depot_screen(
            self.frame,
            ocr=screen_ocr(controls=("Collected 00:30",) * 4),
        )
        self.assertEqual(cooldown.state, "exhausted_or_cooldown")
        self.assertTrue(all(item.state == "collected_or_cooldown" for item in cooldown.controls))

        purchase = recognize_supply_depot_screen(
            self.frame,
            ocr=screen_ocr(panel="Mall Purchase", controls=("Buy 20 diamonds",) * 4),
        )
        self.assertEqual(purchase.state, "paid_or_purchase")
        self.assertTrue(purchase.premium_or_purchase_visible)
        self.assertFalse(any(item.zero_cost for item in purchase.controls))

    def test_ambiguous_control_or_attempt_count_fails_closed(self):
        ambiguous = recognize_supply_depot_screen(
            self.frame,
            ocr=screen_ocr(attempts="attempt count unreadable", controls=("mystery", "Free", "Free", "Free")),
        )
        self.assertIn("ambiguous_control", ambiguous.ambiguity)
        self.assertIn("daily_free_attempts_not_recognized", ambiguous.ambiguity)


    def test_radial_identity_alone_does_not_supply_a_button_target(self):
        with (
            patch.object(supply_depot_module, "tesseract_data", return_value={"text": []}),
            patch("scripts.bluestacks_popup_recognition.recognize_reset_popup", return_value={}),
        ):
            for text in ("Details Upgrade Claim Supply", "Details grade Claim Supply",
                         "etail Clai rage Supp", "etail Clai Upgrade Sup",
                         "Det Clai: rade Upgrade Supply"):
                with self.subTest(text=text):
                    ocr = lambda _image, _psm: text
                    self.assertTrue(recognize_supply_depot_radial(self.frame, ocr=ocr))
                    self.assertIsNone(bind_supply_depot_claim_supply(self.frame, ocr=ocr))
        self.assertFalse(recognize_supply_depot_radial(self.frame, ocr=lambda *_: "Upgrade Details"))
        for text in ("Claim Supply Upgrade", "Det Claim Supply", "Det Upgrade Claim"):
            with self.subTest(incomplete=text):
                self.assertFalse(recognize_supply_depot_radial(self.frame, ocr=lambda *_: text))

    def test_radial_target_rejects_current_modal(self):
        with patch("scripts.bluestacks_popup_recognition.recognize_reset_popup", return_value={"blocking_unknown_modal": True}):
            self.assertIsNone(bind_supply_depot_claim_supply(self.frame, ocr=lambda *_: "Details Upgrade Claim Supply"))

    def test_target_label_ocr_timeout_is_non_actionable(self):
        with (
            patch.object(supply_depot_module, "_recognized_supply_radial_roi", return_value=(145, 840, 800, 1120)),
            patch("scripts.bluestacks_popup_recognition.recognize_reset_popup", return_value={}),
            patch.object(supply_depot_module, "tesseract_data", side_effect=RuntimeError("OCR timeout")) as engine,
        ):
            self.assertIsNone(bind_supply_depot_claim_supply(self.frame))
        self.assertEqual(engine.call_args.kwargs["timeout"], 5)

    @requires_tesseract
    @requires_ocr_worker
    def test_native_edge_radial_identity_does_not_authorize_footer_covered_label(self):
        frame = cv2.imread(str(Path(__file__).parent / "fixtures/supply_depot/native-edge-radial-20261029.png"))
        self.assertIsNotNone(frame)
        if not recognize_supply_depot_radial(frame):
            readings = {
                str(roi): supply_depot_module._ocr_roi_text(
                    frame, roi, supply_depot_module._default_ocr, scale=2
                )
                for roi in supply_depot_module.SUPPLY_DEPOT_RADIAL_ROIS
            }
            self.fail(f"Native radial identity lost; OCR readings: {readings!r}")
        from scripts.bluestacks_native_runtime import captured_native_frame_from_png
        from scripts.home_atlas_bluestacks import identity_from_captured
        path = Path(__file__).parent / "fixtures/supply_depot/native-edge-radial-20261029.png"
        captured = captured_native_frame_from_png(path.read_bytes(), path=path, captured_monotonic=time.monotonic())
        identity = identity_from_captured(captured, session_id="offline-supply-radial", ordinal=1)
        binding = bind_supply_depot_claim_supply(frame, source_frame=identity, source_png=captured.png)
        self.assertIsNone(binding)

    def test_claim_row_rejects_missing_duplicate_and_oversize_claims(self):
        for text, width in (([], []), (["Claim", "Claim"], [150, 150]), (["Claim"], [500]),
                            (["Clai"], [100]), (["Claimed"], [100]), (["Claim", "Clai"], [100, 100])):
            data = {"text": text, "left": [20] * len(text), "top": [20] * len(text), "width": width, "height": [40] * len(text)}
            self.assertIsNone(_claim_label_row_from_data(data, search_roi=(145, 620, 800, 1020)))
        clipped = {"text": ["Claim"], "left": [0], "top": [20], "width": [100], "height": [40]}
        self.assertIsNone(_claim_label_row_from_data(clipped, search_roi=(145, 620, 800, 1020)))

    @requires_tesseract
    @requires_ocr_worker
    def test_native_raised_radial_uses_tight_label_and_book_occlusion_stays_blocked(self):
        from scripts.bluestacks_native_runtime import captured_native_frame_from_png
        from scripts.home_atlas_bluestacks import identity_from_captured

        root = Path(__file__).parent / "fixtures/supply_depot"
        for name, actionable in (("native-raised-radial-20261029.png", True), ("native-book-occluded-radial-20261029.png", False)):
            with self.subTest(name=name):
                path = root / name
                captured = captured_native_frame_from_png(path.read_bytes(), path=path, captured_monotonic=time.monotonic())
                identity = identity_from_captured(captured, session_id="offline-supply-label", ordinal=1)
                diagnostics = {}
                def trace(name):
                    original = getattr(supply_depot_module, name)
                    def observed(*args, **kwargs):
                        try:
                            value = original(*args, **kwargs)
                        except ValueError as exc:
                            diagnostics.setdefault(name, []).append(str(exc))
                            raise
                        diagnostics.setdefault(name, []).append(value)
                        return value
                    return observed
                with ExitStack() as stack:
                    for name in ("_ocr_roi_text", "_recognized_supply_radial_roi", "_claim_text_roi_from_data",
                                 "_claim_label_row_from_data", "_claim_button_interior"):
                        stack.enter_context(patch.object(supply_depot_module, name, side_effect=trace(name)))
                    binding = bind_supply_depot_claim_supply(captured.frame, source_frame=identity, source_png=captured.png)
                self.assertEqual(binding is not None, actionable,
                                 {"binding": diagnostics, "ocr": self.native_ocr_diagnostics})
                if binding is not None:
                    self.assertLess(binding.target_roi[3], 864)
                    self.assertEqual((binding.target_roi[2] - binding.target_roi[0],
                                      binding.target_roi[3] - binding.target_roi[1]), (16, 12))
                    self.assertFalse(any(
                        binding.target_roi[0] < hx1 and binding.target_roi[2] > hx0
                        and binding.target_roi[1] < hy1 and binding.target_roi[3] > hy0
                        for hx0, hy0, hx1, hy1 in supply_depot_module.HUD_MASK_RECTS))
                    for box in ((652, 864, 720, 886), (665, 817, 708, 856)):
                        changed = captured.frame.copy()
                        x0, y0, x1, y1 = box
                        changed[y0:y1, x0:x1] = 0
                        self.assertIsNone(bind_supply_depot_claim_supply(changed))

    @requires_tesseract
    @requires_ocr_worker
    def test_actual_hud_occluded_radial_stays_recognized_but_not_actionable(self):
        from scripts.bluestacks_native_runtime import captured_native_frame_from_png
        from scripts.home_atlas_bluestacks import identity_from_captured

        path = Path(__file__).parent / "fixtures/supply_depot/native-hud-occluded-radial-20261029.png"
        captured = captured_native_frame_from_png(path.read_bytes(), path=path, captured_monotonic=time.monotonic())
        identity = identity_from_captured(captured, session_id="offline-supply-hud", ordinal=1)
        self.assertTrue(recognize_supply_depot_radial(captured.frame, source_frame=identity, source_png=captured.png),
                        self.native_ocr_diagnostics)
        self.assertIsNone(bind_supply_depot_claim_supply(captured.frame, source_frame=identity, source_png=captured.png))

    def test_safe_label_subregion_rejects_full_occlusion_and_slivers(self):
        choose = supply_depot_module._safe_claim_label_region
        self.assertEqual(choose((652, 887, 720, 907)), (654, 889, 675, 905))
        for roi in ((680, 901, 748, 926), (661, 1078, 731, 1098), (660, 887, 720, 907),
                    (652, 887, 720, 899), (700, 200, 750, 230)):
            with self.subTest(roi=roi):
                self.assertIsNone(choose(roi))

    @requires_ocr_worker
    def test_capture_bound_screen_recognizes_free_controls(self):
        result = recognize_supply_depot_screen(
            self.frame,
            ocr=FixtureScreenOcr(),
            source_frame=frame_identity(self.frame),
        )
        self.assertTrue(result.recognized)
        self.assertEqual(result.daily_free_attempts, 9)
        self.assertEqual(
            [control.state for control in result.controls],
            ["available_free"] * 4,
        )


    def test_forged_explicit_identity_fails_closed(self):
        forged = NativeFrameIdentity(
            capture_kind="fixture",
            runtime_session_id="forged",
            capture_ordinal=9,
            capture_completed_monotonic=1.0,
            transport_sha256="a" * 64,
            semantic_sha256="b" * 64,
            runtime_profile_id=BLUESTACKS_PROFILE_ID,
            width=800,
            height=1280,
        )
        rejected = recognize_supply_depot_screen(self.frame, ocr=screen_ocr(), source_frame=forged)
        self.assertFalse(rejected.recognized)
        self.assertEqual(rejected.controls, ())

    def test_matching_semantic_digest_cannot_repair_wrong_transport_identity(self):
        identity = replace(
            frame_identity(self.frame),
            transport_sha256="a" * 64,
            semantic_sha256=frame_digest(self.frame),
        )
        result = recognize_supply_depot_screen(
            self.frame, ocr=FixtureScreenOcr(), source_frame=identity
        )
        self.assertFalse(result.recognized)
        self.assertEqual(result.controls, ())

    def assert_fail_closed_ocr_result(self, result, reason):
        self.assertFalse(result.recognized)
        self.assertEqual(result.state, "unknown")
        self.assertEqual(result.ambiguity, reason)
        self.assertEqual(result.controls, ())
        self.assertFalse(result.premium_or_purchase_visible)

    @requires_ocr_worker
    def test_explicit_attempts_ocr_engine_failure_fails_closed(self):
        result = recognize_supply_depot_screen(
            self.frame,
            ocr=FixtureScreenOcr("attempts"),
            source_frame=frame_identity(self.frame),
        )
        self.assert_fail_closed_ocr_result(result, "ocr_invalid_attempts")
        self.assertIsNone(result.daily_free_attempts)

    @requires_ocr_worker
    def test_explicit_panel_ocr_engine_failure_fails_closed(self):
        result = recognize_supply_depot_screen(
            self.frame,
            ocr=FixtureScreenOcr("panel"),
            source_frame=replace(
                frame_identity(self.frame),
                semantic_sha256=frame_digest(self.frame),
            ),
        )
        self.assert_fail_closed_ocr_result(result, "ocr_invalid_panel")
        self.assertEqual(result.daily_free_attempts, 9)

    @requires_ocr_worker
    def test_explicit_control_ocr_engine_failure_discards_partial_controls(self):
        result = recognize_supply_depot_screen(
            self.frame,
            ocr=FixtureScreenOcr("control_1"),
            source_frame=frame_identity(self.frame),
        )
        self.assert_fail_closed_ocr_result(result, "ocr_invalid_control_1")
        self.assertEqual(result.daily_free_attempts, 9)



if __name__ == "__main__":
    unittest.main()
