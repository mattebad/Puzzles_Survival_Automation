from __future__ import annotations

from collections import deque
import unittest
from unittest import mock

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


def failing_screen_ocr(fail_call: int):
    values = [
        "Supply Depot",
        "Supply Depot",
        "Daily free attempts: 9",
        "Daily free attempts: 9",
        "",
        "Free",
        "Free",
        "Free",
        "Free",
        "Free",
        "Free",
        "Free",
        "Free",
    ]
    call_count = 0

    def ocr(_image, _psm):
        nonlocal call_count
        call_count += 1
        if call_count == fail_call:
            raise RuntimeError("adversarial OCR engine failure")
        return values[call_count - 1]

    return ocr


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

    def test_omitted_identity_preserves_legacy_results_without_pipeline(self):
        with (
            mock.patch.object(
                supply_depot_module,
                "run_semantic_ocr",
                side_effect=AssertionError("identity pipeline called"),
            ),
            mock.patch.object(
                supply_depot_module,
                "prepare_ocr_crop",
                side_effect=AssertionError("identity crop called"),
            ),
        ):
            result = recognize_supply_depot_screen(self.frame, ocr=screen_ocr())
        self.assertTrue(result.recognized)
        self.assertEqual(result.daily_free_attempts, 9)
        self.assertFalse(hasattr(supply_depot_module, "_ephemeral_frame_identity"))

    def test_explicit_identity_uses_pipeline_and_preserves_identity(self):
        identity = frame_identity(self.frame)
        observations = []
        real_pipeline = supply_depot_module.run_semantic_ocr

        def recording_pipeline(*args, **kwargs):
            observation = real_pipeline(*args, **kwargs)
            observations.append(observation)
            return observation

        with mock.patch.object(
            supply_depot_module,
            "run_semantic_ocr",
            side_effect=recording_pipeline,
        ) as pipeline:
            result = recognize_supply_depot_screen(
                self.frame,
                ocr=screen_ocr(),
                source_frame=identity,
            )
        self.assertTrue(result.recognized)
        self.assertEqual(result.daily_free_attempts, 9)
        self.assertGreaterEqual(pipeline.call_count, 7)
        for call in pipeline.call_args_list:
            request = call.args[1]
            self.assertIs(request.source_frame, identity)
        self.assertTrue(observations)
        self.assertTrue(
            all(observation.source_frame is identity for observation in observations)
        )

    def test_identical_pixels_keep_distinct_explicit_capture_identities(self):
        first = frame_identity(self.frame, session="session-a", ordinal=1, monotonic=10.0)
        second = frame_identity(self.frame, session="session-a", ordinal=2, monotonic=11.0)
        self.assertEqual(first.transport_sha256, second.transport_sha256)
        self.assertFalse(first.same_capture_event(second))
        observed: list[NativeFrameIdentity] = []
        real_pipeline = supply_depot_module.run_semantic_ocr

        def recording_pipeline(*args, **kwargs):
            observed.append(args[1].source_frame)
            return real_pipeline(*args, **kwargs)

        with mock.patch.object(
            supply_depot_module,
            "run_semantic_ocr",
            side_effect=recording_pipeline,
        ):
            self.assertTrue(
                recognize_supply_depot_screen(
                    self.frame,
                    ocr=screen_ocr(),
                    source_frame=first,
                ).recognized
            )
            self.assertTrue(
                recognize_supply_depot_screen(
                    self.frame,
                    ocr=screen_ocr(),
                    source_frame=second,
                ).recognized
            )
        self.assertIn(first, observed)
        self.assertIn(second, observed)
        self.assertTrue(all(item is first or item is second for item in observed))

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
        self.assertEqual(rejected.ambiguity, "non_native_frame")

    def assert_fail_closed_ocr_result(self, result, reason):
        self.assertFalse(result.recognized)
        self.assertEqual(result.state, "unknown")
        self.assertEqual(result.ambiguity, reason)
        self.assertEqual(result.controls, ())
        self.assertFalse(any(control.zero_cost for control in result.controls))
        self.assertFalse(result.premium_or_purchase_visible)

    def test_explicit_attempts_ocr_engine_failure_fails_closed(self):
        result = recognize_supply_depot_screen(
            self.frame,
            ocr=failing_screen_ocr(3),
            source_frame=frame_identity(self.frame),
        )
        self.assert_fail_closed_ocr_result(result, "ocr_invalid_attempts")
        self.assertIsNone(result.daily_free_attempts)

    def test_explicit_panel_ocr_engine_failure_fails_closed(self):
        result = recognize_supply_depot_screen(
            self.frame,
            ocr=failing_screen_ocr(5),
            source_frame=frame_identity(self.frame),
        )
        self.assert_fail_closed_ocr_result(result, "ocr_invalid_panel")
        self.assertEqual(result.daily_free_attempts, 9)

    def test_explicit_control_ocr_engine_failure_discards_partial_controls(self):
        result = recognize_supply_depot_screen(
            self.frame,
            ocr=failing_screen_ocr(8),
            source_frame=frame_identity(self.frame),
        )
        self.assert_fail_closed_ocr_result(result, "ocr_invalid_control_1")
        self.assertEqual(result.daily_free_attempts, 9)

    def test_default_dynamic_crop_branches_on_identity(self):
        data = {
            "text": ["Details", "Claim", "Upgrade", "Supply"],
            "left": [40, 464, 290, 436],
            "top": [450, 452, 500, 500],
            "width": [120, 108, 170, 136],
            "height": [50, 34, 40, 40],
        }
        with (
            mock.patch.object(
                supply_depot_module.pytesseract,
                "image_to_string",
                return_value="Details Upgrade Claim Supply",
            ),
            mock.patch.object(
                supply_depot_module.pytesseract,
                "image_to_data",
                return_value=data,
            ),
            mock.patch.object(
                supply_depot_module,
                "run_semantic_ocr",
                side_effect=AssertionError("identity pipeline called"),
            ),
            mock.patch.object(
                supply_depot_module,
                "prepare_ocr_crop",
                side_effect=AssertionError("identity crop called"),
            ),
        ):
            legacy = bind_supply_depot_claim_supply(self.frame)
        self.assertIsNotNone(legacy)

        identity = frame_identity(self.frame)
        with (
            mock.patch.object(
                supply_depot_module.pytesseract,
                "image_to_string",
                return_value="Details Upgrade Claim Supply",
            ),
            mock.patch.object(
                supply_depot_module.pytesseract,
                "image_to_data",
                return_value=data,
            ),
            mock.patch.object(
                supply_depot_module,
                "run_semantic_ocr",
                wraps=supply_depot_module.run_semantic_ocr,
            ) as ocr_pipeline,
            mock.patch.object(
                supply_depot_module,
                "prepare_ocr_crop",
                wraps=supply_depot_module.prepare_ocr_crop,
            ) as crop_pipeline,
        ):
            explicit = bind_supply_depot_claim_supply(
                self.frame,
                source_frame=identity,
            )
        self.assertIsNotNone(explicit)
        self.assertGreaterEqual(ocr_pipeline.call_count, 1)
        self.assertGreaterEqual(crop_pipeline.call_count, 1)
        self.assertIs(ocr_pipeline.call_args_list[0].args[1].source_frame, identity)
        self.assertIs(crop_pipeline.call_args_list[-1].args[1].source_frame, identity)


if __name__ == "__main__":
    unittest.main()
