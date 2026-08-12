from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from tasks.home_atlas import (
    AmbiguityState,
    AtlasViewport,
    BuildingBinding,
    ClosedLoopBuildingNavigator,
    HomeAtlas,
    LocalizationResult,
    NavigationAction,
    PlatformProfile,
    SemanticBuilding,
    ZoomIdentity,
    load_home_atlas,
)
from tasks.home_atlas_vision import (
    BLUESTACKS_PLATFORM,
    BLUESTACKS_PROFILE_ID,
    BlueStacksHomeLocalizer,
    classify_zoom,
    hud_mask,
    mask_home_hud,
    register_home_frame,
    validate_loop_closure,
)
from scripts.home_atlas_bluestacks import _GRID_GESTURES, _canonical_pan_gesture, _registration_geometry


def synthetic_home(seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    frame = np.full((1280, 800, 3), (72, 93, 68), np.uint8)
    for index in range(260):
        x = int(rng.integers(145, 665))
        y = int(rng.integers(90, 1010))
        color = tuple(int(item) for item in rng.integers(35, 235, size=3))
        if index % 2:
            cv2.circle(frame, (x, y), int(rng.integers(3, 18)), color, -1)
        else:
            cv2.rectangle(frame, (x, y), (x + int(rng.integers(5, 30)), y + int(rng.integers(5, 30))), color, -1)
    cv2.line(frame, (150, 900), (660, 160), (220, 220, 220), 7)
    cv2.putText(frame, "HEADQUARTERS", (230, 600), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 3)
    return frame


def atlas_contract() -> HomeAtlas:
    profile = PlatformProfile(BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, (800, 1280), "com.global.ztmslg")
    viewport = AtlasViewport(
        "v1", "tile.png", "a" * 64, "2026-07-18T00:00:00+00:00",
        ((1, 0, 100), (0, 1, 100), (0, 0, 1)),
        ((100, 100), (900, 100), (900, 1380), (100, 1380)), 1.0, 0.0, "origin",
    )
    building = SemanticBuilding(
        "home.building.supply_depot", "Supply Depot",
        ((650, 650), (730, 650), (730, 740), (650, 740)), 0.95, ("v1",),
        semantic_proof=("opened exact Supply Depot successor",),
    )
    return HomeAtlas(
        2, "test", "1", profile, "fully_zoomed_out", "atlas pixels", (0, 0), 1600, 1800,
        "atlas.png", "test", "test", (((0, 0), (1600, 0), (1600, 1800), (0, 1800)),), (),
        (viewport,), (building,),
    )


def localization(*, tx: float = 100, ty: float = 100, digest: str = "a" * 64) -> LocalizationResult:
    return LocalizationResult(
        True, BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, ZoomIdentity.FULLY_ZOOMED_OUT,
        ((1, 0, tx), (0, 1, ty), (0, 0, 1)),
        ((tx, ty), (tx + 800, ty), (tx + 800, ty + 1280), (tx, ty + 1280)),
        0.95, ("v1",), 1.2, AmbiguityState.NONE, "interior", digest, "2026-07-18T00:00:00+00:00",
    )


class HomeAtlasVisionTests(unittest.TestCase):
    def test_retained_bluestacks_atlas_contract_is_deterministic_and_profile_separated(self):
        manifest = Path(__file__).resolve().parents[1] / "tasks/assets/home_atlas/bluestacks/800x1280/atlas.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        atlas = load_home_atlas(manifest)
        self.assertEqual((atlas.width, atlas.height), (1447, 2769))
        self.assertEqual(atlas.origin, (0.0, 0.0))
        self.assertEqual(atlas.canonical_zoom_identity, "fully_zoomed_out")
        self.assertEqual(atlas.profile.profile_id, BLUESTACKS_PROFILE_ID)
        self.assertNotEqual(atlas.profile.profile_id, "pns-800x1280-v1")
        self.assertEqual(len(atlas.viewports), 30)
        self.assertEqual(len({item.source_sha256 for item in atlas.viewports}), 30)
        self.assertTrue(all(item.accepted and item.residual_px < 1.0 for item in atlas.viewports))
        self.assertLessEqual(max(item.loop_closure_residual_px for item in atlas.viewports), 1.2)
        self.assertTrue(atlas.coverage_polygons)
        self.assertEqual(atlas.coverage_gaps, ())
        self.assertEqual(len(payload["rejected_viewports"]), 2)
        self.assertTrue(all(item["reason"] == "duplicate_viewport" for item in payload["rejected_viewports"]))
        self.assertEqual(payload["coverage_assessment"]["status"], "full_reachable_base_coverage")
        self.assertEqual(payload["coverage_assessment"]["verified_interior_coverage_gaps"], 0)
        self.assertEqual(payload["coverage_assessment"]["verified_registration_coverage_gaps"], 0)
        self.assertEqual(payload["boundary_evidence"]["rows"], 5)
        self.assertEqual(payload["boundary_evidence"]["navigation_inputs"], 30)
        self.assertEqual(len(payload["boundary_evidence"]["clamp_keys"]), 8)
        self.assertEqual(len(atlas.buildings), 65)
        self.assertTrue(all(item.navigation_anchor for item in atlas.buildings))
        self.assertTrue(all(item.safe_interaction_region_id for item in atlas.buildings))
        self.assertTrue(all(item.semantic_proof for item in atlas.buildings))
        self.assertTrue(all(item.platform_binding_policy for item in atlas.buildings))
        self.assertEqual(sum(item.semantic_id.startswith("home.building.farm.") for item in atlas.buildings), 7)
        self.assertEqual(sum(item.semantic_id.startswith("home.building.lumber_mill.") for item in atlas.buildings), 6)
        self.assertEqual(sum(item.semantic_id.startswith("home.building.bootcamp.") for item in atlas.buildings), 4)
        self.assertEqual(sum(item.semantic_id.startswith("home.building.steel_plant.") for item in atlas.buildings), 6)
        self.assertEqual(sum(item.semantic_id.startswith("home.building.infirmary.") for item in atlas.buildings), 3)
        self.assertEqual(sum(item.semantic_id.startswith("home.building.gas_field.") for item in atlas.buildings), 8)
        repeated_prefixes = ("home.building.farm.", "home.building.lumber_mill.", "home.building.bootcamp.", "home.building.steel_plant.", "home.building.infirmary.", "home.building.gas_field.")
        named_ids = {item.semantic_id for item in atlas.buildings if not item.semantic_id.startswith(repeated_prefixes)}
        self.assertEqual(named_ids, {
            "home.building.alliance_hall", "home.building.arena", "home.building.bank",
            "home.building.campaign", "home.building.containment_center",
            "home.building.cultivation_center", "home.building.fighter_camp",
            "home.building.forum", "home.building.gear_factory", "home.building.hall_of_war",
            "home.building.headquarters", "home.building.mystery_shop",
            "home.building.noahs_tavern", "home.building.parade_grounds", "home.building.pit",
            "home.building.radio", "home.building.research_center", "home.building.research_lab",
            "home.building.rider_camp", "home.building.ruins", "home.building.shooter_camp",
            "home.building.supply_depot", "home.building.swp_lab", "home.building.trading_post",
            "home.building.trap_factory", "home.building.vehicle_depot",
            "home.building.virology_lab", "home.building.warehouse",
            "home.building.wasteland_conquest", "home.building.watch_tower", "home.landmark.wall",
        })
        self.assertFalse(atlas.lookup_building("home.building.forum").supporting_source_frames)
        self.assertFalse(atlas.lookup_building("home.building.forum").interaction_eligible)
        parade = atlas.lookup_building("home.building.parade_grounds")
        self.assertFalse(parade.interaction_eligible)
        self.assertEqual(parade.supporting_source_frames, ("viewport-018", "viewport-019"))
        self.assertIn("Parade Grounds", " ".join(parade.semantic_proof))
        self.assertEqual(parade.safe_interaction_region_id, "unavailable-fixed-right-hud")
        self.assertFalse(atlas.lookup_building("home.landmark.wall").interaction_eligible)
        self.assertEqual(payload["production_registration"], "NOT_REGISTERED")
        self.assertFalse(payload["scheduler_eligibility"])
        supply = atlas.lookup_building("home.building.supply_depot")
        self.assertEqual(supply.center, (1246.7, 976.1))
        self.assertIn("supply depot label", " ".join(supply.semantic_proof).lower())
        image = cv2.imread(str(manifest.parent / atlas.image_path), cv2.IMREAD_COLOR)
        self.assertEqual(image.shape[:2], (atlas.height, atlas.width))

    def test_grid_gestures_preserve_overlap_and_registration_geometry_is_bounded(self):
        self.assertEqual(abs(_GRID_GESTURES["left"][1][0] - _GRID_GESTURES["left"][0][0]), 150)
        self.assertEqual(abs(_GRID_GESTURES["right"][1][0] - _GRID_GESTURES["right"][0][0]), 150)
        self.assertEqual(abs(_GRID_GESTURES["up"][1][1] - _GRID_GESTURES["up"][0][1]), 180)

        frame = synthetic_home()
        shifted = cv2.warpAffine(frame, np.float32([[1, 0, 120], [0, 1, -80]]), (800, 1280))
        registration = register_home_frame(shifted, frame)
        scale, movement = _registration_geometry(registration)
        self.assertAlmostEqual(scale, 1.0, places=3)
        self.assertGreater(movement, 100.0)
        self.assertEqual(_canonical_pan_gesture(np.asarray([-400.0, -200.0])), ("horizontal", (320, 500), (470, 500)))
        self.assertEqual(_canonical_pan_gesture(np.asarray([50.0, -300.0])), ("vertical", (450, 260), (450, 403)))
        self.assertEqual(_canonical_pan_gesture(np.asarray([163.0, 20.0])), ("horizontal", (480, 500), (402, 500)))
        self.assertEqual(_canonical_pan_gesture(np.asarray([5.0, 90.0])), ("vertical", (450, 440), (450, 397)))

    def test_native_frame_guard_and_hud_mask(self):
        frame = synthetic_home()
        masked = mask_home_hud(frame)
        self.assertEqual(masked.shape, frame.shape)
        self.assertTrue(np.all(masked[0:82] == 0))
        self.assertTrue(np.all(masked[1100:1280] == 0))
        self.assertGreater(int(hud_mask().sum()), 0)
        with self.assertRaises(ValueError):
            mask_home_hud(frame[:1000])

    def test_translation_registration_and_low_confidence_rejection(self):
        reference = synthetic_home()
        transform = np.float32([[1, 0, 70], [0, 1, -45]])
        candidate = cv2.warpAffine(reference, transform, (800, 1280))
        result = register_home_frame(candidate, reference)
        self.assertTrue(result.accepted)
        self.assertIn(result.model, {"translation", "similarity", "affine", "homography"})
        self.assertLess(result.residual_px, 4.5)
        rejected = register_home_frame(np.zeros_like(reference), reference)
        self.assertFalse(rejected.accepted)
        self.assertEqual(rejected.reason, "insufficient_landmarks")

    def test_affine_model_is_selected_only_when_measured(self):
        reference = synthetic_home()
        affine = cv2.getRotationMatrix2D((400, 640), 2.5, 0.97)
        affine[:, 2] += (16, -22)
        candidate = cv2.warpAffine(reference, affine, (800, 1280))
        result = register_home_frame(candidate, reference)
        self.assertTrue(result.accepted)
        self.assertIn(result.model, {"similarity", "affine", "homography"})
        self.assertLess(result.residual_px, 4.5)

    def test_zoom_classification_distinguishes_canonical_zoomed_and_unknown(self):
        canonical = synthetic_home()
        self.assertEqual(classify_zoom(canonical, canonical).identity, ZoomIdentity.FULLY_ZOOMED_OUT)
        live_clamp_matrix = cv2.getRotationMatrix2D((400, 640), 0, 1.0 / 0.95)
        live_clamp = cv2.warpAffine(canonical, live_clamp_matrix, (800, 1280))
        self.assertEqual(classify_zoom(live_clamp, canonical).identity, ZoomIdentity.FULLY_ZOOMED_OUT)
        intermediate_matrix = cv2.getRotationMatrix2D((400, 640), 0, 1.0 / 0.925)
        intermediate = cv2.warpAffine(canonical, intermediate_matrix, (800, 1280))
        self.assertEqual(classify_zoom(intermediate, canonical).identity, ZoomIdentity.INTERMEDIATE)
        zoom_matrix = cv2.getRotationMatrix2D((400, 640), 0, 1.25)
        zoomed_in = cv2.warpAffine(canonical, zoom_matrix, (800, 1280))
        self.assertEqual(classify_zoom(zoomed_in, canonical).identity, ZoomIdentity.ZOOMED_IN)
        unknown = np.zeros_like(canonical)
        self.assertEqual(classify_zoom(unknown, canonical).identity, ZoomIdentity.UNKNOWN)
        self.assertEqual(classify_zoom(canonical, canonical, overlay=True).identity, ZoomIdentity.OVERLAY)

    def test_loop_closure(self):
        first = np.eye(3)
        close = np.array([[1, 0, 4], [0, 1, -3], [0, 0, 1]], dtype=float)
        far = np.array([[1, 0, 40], [0, 1, 0], [0, 0, 1]], dtype=float)
        self.assertTrue(validate_loop_closure((first, close))[0])
        self.assertFalse(validate_loop_closure((first, far))[0])

    def test_localizer_known_unknown_stale_overlay_and_profile_separation(self):
        frame = synthetic_home()
        atlas = atlas_contract()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cv2.imwrite(str(root / "tile.png"), frame)
            manifest = root / "atlas.json"
            manifest.write_text("{}", encoding="utf-8")
            localizer = BlueStacksHomeLocalizer(atlas, manifest)
            known = localizer.localize(frame)
            self.assertTrue(known.recognized)
            self.assertEqual(known.zoom_identity, ZoomIdentity.FULLY_ZOOMED_OUT)
            self.assertFalse(localizer.localize(np.zeros_like(frame)).recognized)
            self.assertEqual(localizer.localize(frame, stale=True).ambiguity_state, AmbiguityState.STALE_FRAME)
            self.assertTrue(localizer.localize(frame, overlay=True).overlay)
            wrong = replace(atlas, profile=replace(atlas.profile, platform="Bliss OS"))
            with self.assertRaises(ValueError):
                BlueStacksHomeLocalizer(wrong, manifest)


class ClosedLoopNavigatorTests(unittest.TestCase):
    def test_visible_target_requires_current_frame_semantic_binding(self):
        navigator = ClosedLoopBuildingNavigator(atlas_contract(), "home.building.supply_depot")
        loc = localization()
        self.assertEqual(navigator.next_command(loc).action, NavigationAction.BIND_TARGET)

        navigator = ClosedLoopBuildingNavigator(atlas_contract(), "home.building.supply_depot")
        binding = BuildingBinding(
            "home.building.supply_depot", (520, 520, 620, 640), loc.frame_sha256, 0.94,
            ("Supply Depot label", "exact successor policy"),
        )
        command = navigator.next_command(loc, binding)
        self.assertEqual(command.action, NavigationAction.TAP_TARGET)

    def test_partially_visible_target_continues_panning_before_binding(self):
        navigator = ClosedLoopBuildingNavigator(atlas_contract(), "home.building.supply_depot")
        # The target intersects the safe viewport but extends beyond its right
        # edge, matching the live event-HUD occlusion case.
        partial = localization(tx=50, ty=100)
        command = navigator.next_command(partial)
        self.assertEqual(command.action, NavigationAction.PAN)
        self.assertEqual(command.reason, "bounded_pan_toward_target")

    def test_exact_safe_binding_can_override_conservative_polygon_at_edge(self):
        navigator = ClosedLoopBuildingNavigator(atlas_contract(), "home.building.supply_depot")
        partial = localization(tx=50, ty=100)
        binding = BuildingBinding(
            "home.building.supply_depot", (610, 560, 650, 620), partial.frame_sha256, 0.94,
            ("current-frame OCR: Supply Depot",),
        )
        command = navigator.next_command(partial, binding)
        self.assertEqual(command.action, NavigationAction.TAP_TARGET)

    def test_coordinate_only_binding_is_rejected(self):
        navigator = ClosedLoopBuildingNavigator(atlas_contract(), "home.building.supply_depot")
        loc = localization()
        binding = BuildingBinding("home.building.supply_depot", (520, 520, 620, 640), loc.frame_sha256, 0.94, ())
        self.assertEqual(navigator.next_command(loc, binding).action, NavigationAction.STOP)

    def test_outside_viewport_plans_bounded_pan_then_requires_progress(self):
        navigator = ClosedLoopBuildingNavigator(atlas_contract(), "home.building.supply_depot")
        far = localization(tx=-700, ty=-500)
        command = navigator.next_command(far)
        self.assertEqual(command.action, NavigationAction.PAN)
        self.assertNotEqual(command.pan_start, command.pan_end)
        no_progress = localization(tx=-700, ty=-500, digest="b" * 64)
        self.assertEqual(navigator.next_command(no_progress).reason, "no_measured_progress")

    def test_repeated_viewport_wrong_zoom_and_maximum_pan_fail_closed(self):
        navigator = ClosedLoopBuildingNavigator(atlas_contract(), "home.building.supply_depot", maximum_pans=1)
        first = localization(tx=-700, ty=-500)
        self.assertEqual(navigator.next_command(first).action, NavigationAction.PAN)
        progressed = localization(tx=-400, ty=-300, digest="b" * 64)
        self.assertEqual(navigator.next_command(progressed).reason, "maximum_pan_count")

        navigator = ClosedLoopBuildingNavigator(atlas_contract(), "home.building.supply_depot")
        repeated = localization()
        navigator.next_command(repeated)
        self.assertEqual(navigator.next_command(repeated).reason, "repeated_viewport")

        navigator = ClosedLoopBuildingNavigator(atlas_contract(), "home.building.supply_depot")
        wrong_zoom = replace(localization(), zoom_identity=ZoomIdentity.ZOOMED_IN)
        self.assertEqual(navigator.next_command(wrong_zoom).reason, "canonical_zoom_required")


if __name__ == "__main__":
    unittest.main()
