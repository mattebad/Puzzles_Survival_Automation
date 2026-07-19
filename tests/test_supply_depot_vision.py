from __future__ import annotations

from collections import deque
import unittest

import numpy as np

from tasks.home_atlas import AmbiguityState, LocalizationResult, SemanticBuilding, ZoomIdentity
from tasks.home_atlas_vision import BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, frame_digest
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


if __name__ == "__main__":
    unittest.main()
