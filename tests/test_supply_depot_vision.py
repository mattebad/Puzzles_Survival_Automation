from __future__ import annotations

from collections import deque
from dataclasses import replace
import unittest

import numpy as np

from tasks.home_atlas import AmbiguityState, LocalizationResult, SemanticBuilding, ZoomIdentity
from tasks.home_atlas_vision import BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, frame_digest
from tasks.perception_bundle import NativeFrameIdentity
from tasks import supply_depot_vision as supply_depot_module
from tasks.supply_depot_vision import (
    _claim_supply_roi_from_data,
    SUPPLY_DEPOT_BUILDING_ID,
    bind_supply_depot_building,
    bind_supply_depot_claim_supply,
    recognize_supply_depot_screen,
)


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
    def setUp(self):
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

    def test_building_binding_requires_current_frame_localization_and_semantic_ocr(self):
        localization = LocalizationResult(
            recognized=True,
            platform=BLUESTACKS_PLATFORM,
            profile_id=BLUESTACKS_PROFILE_ID,
            zoom_identity=ZoomIdentity.FULLY_ZOOMED_OUT,
            screen_to_atlas=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            viewport_polygon=((0.0, 0.0), (800.0, 0.0), (800.0, 1280.0), (0.0, 1280.0)),
            confidence=0.99,
            supporting_landmarks=("terrain", "road", "wall"),
            residual_px=0.1,
            ambiguity_state=AmbiguityState.NONE,
            map_edge_state="none",
            frame_sha256=frame_digest(self.frame),
            timestamp="2026-07-18T00:00:00+00:00",
        )
        building = SemanticBuilding(
            semantic_id=SUPPLY_DEPOT_BUILDING_ID,
            display_identity="Supply Depot",
            polygon=((300.0, 400.0), (480.0, 400.0), (480.0, 560.0), (300.0, 560.0)),
            confidence=0.99,
            supporting_source_frames=("viewport-001",),
            semantic_proof=("visible label",),
        )
        binding = bind_supply_depot_building(
            self.frame,
            localization,
            building,
            ocr=lambda _image, _psm: "Supply Depot",
        )
        self.assertIsNotNone(binding)
        self.assertEqual(binding.building_id, SUPPLY_DEPOT_BUILDING_ID)
        self.assertEqual(binding.frame_sha256, frame_digest(self.frame))

        stale = LocalizationResult(**{**localization.__dict__, "frame_sha256": "0" * 64})
        self.assertIsNone(bind_supply_depot_building(self.frame, stale, building, ocr=lambda _image, _psm: "Supply Depot"))
        self.assertIsNone(bind_supply_depot_building(self.frame, localization, building, ocr=lambda _image, _psm: "Headquarters"))

    def test_radial_binding_separates_claim_supply_from_upgrade(self):
        binding = bind_supply_depot_claim_supply(
            self.frame,
            ocr=lambda _image, _psm: "Details Upgrade Claim Supply",
        )
        self.assertIsNotNone(binding)
        self.assertIn("separate Upgrade control observed", binding.semantic_evidence)
        self.assertIsNotNone(bind_supply_depot_claim_supply(self.frame, ocr=lambda _image, _psm: "Details grade Claim Supply"))
        self.assertIsNotNone(bind_supply_depot_claim_supply(self.frame, ocr=lambda _image, _psm: "etail Clai rage Supp"))
        self.assertIsNotNone(bind_supply_depot_claim_supply(self.frame, ocr=lambda _image, _psm: "etail Clai Upgrade Sup"))
        self.assertIsNone(bind_supply_depot_claim_supply(self.frame, ocr=lambda _image, _psm: "Upgrade Details"))

    def test_claim_supply_target_is_derived_from_current_ocr_boxes(self):
        data = {
            "text": ["Details", "Claim", "Upgrade", "Supply"],
            "left": [40, 464, 290, 436],
            "top": [450, 452, 500, 500],
            "width": [120, 108, 170, 136],
            "height": [50, 34, 40, 40],
        }
        self.assertEqual(_claim_supply_roi_from_data(data), (608, 666, 696, 730))

    def test_claim_supply_target_accepts_live_renderer_stems(self):
        data = {
            "text": ["etail", "Clai", "rage", "Supp"],
            "left": [161, 516, 382, 503],
            "top": [646, 646, 697, 694],
            "width": [85, 68, 88, 91],
            "height": [32, 33, 24, 39],
        }
        self.assertEqual(_claim_supply_roi_from_data(data), (641, 763, 707, 827))

    def test_claim_supply_roi_rejects_building_label_sup_contamination(self):
        """Live binder attempt-1 OCR: building title Sup inflated ROI over Upgrade."""

        # Coordinates are already in the radial crop's upscaled image_to_data space
        # (scale=2), matching the live 0007 pre-dispatch frame tokens.
        data = {
            "text": ["Sup", "Depot", "Detail", "Claim", "Upgrade", "Suppl"],
            "left": [331, 413, 138, 522, 306, 509],
            "top": [222, 222, 306, 306, 351, 353],
            "width": [36, 63, 114, 107, 170, 113],
            "height": [16, 19, 33, 33, 39, 40],
        }
        # Legacy union of all clai*/sup* tokens produced the Upgrade-covering ROI.
        self.assertNotEqual(_claim_supply_roi_from_data(data), (555, 551, 725, 657))
        paired = _claim_supply_roi_from_data(data)
        self.assertEqual(paired, (644, 593, 725, 657))
        upgrade = (553.0, 625.5, 638.0, 645.0)
        self.assertTrue(
            upgrade[2] <= paired[0]
            or upgrade[0] >= paired[2]
            or upgrade[3] <= paired[1]
            or upgrade[1] >= paired[3]
        )

    def test_claim_supply_roi_fails_closed_when_only_building_label_supply(self):
        data = {
            "text": ["Sup", "Depot", "Detail", "Claim", "Upgrade"],
            "left": [331, 413, 138, 522, 306],
            "top": [222, 222, 306, 306, 351],
            "width": [36, 63, 114, 107, 170],
            "height": [16, 19, 33, 33, 39],
        }
        self.assertIsNone(_claim_supply_roi_from_data(data))

    def test_upgrade_geometry_cannot_satisfy_claim_supply_pairing(self):
        data = {
            "text": ["Upgrade", "Claim"],
            "left": [306, 522],
            "top": [351, 306],
            "width": [170, 107],
            "height": [39, 33],
        }
        self.assertIsNone(_claim_supply_roi_from_data(data))


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

    def test_explicit_attempts_ocr_engine_failure_fails_closed(self):
        result = recognize_supply_depot_screen(
            self.frame,
            ocr=FixtureScreenOcr("attempts"),
            source_frame=frame_identity(self.frame),
        )
        self.assert_fail_closed_ocr_result(result, "ocr_invalid_attempts")
        self.assertIsNone(result.daily_free_attempts)

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
