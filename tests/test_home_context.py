"""Focused tests for shared Home context levels and navigation primitives."""

from __future__ import annotations

import unittest

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
)
from tasks.home_context import (
    HOME_NAVIGATION_PRIMITIVES_DIGEST,
    HomeContextLevel,
    HomePrimitiveAction,
    HomeReadyObservation,
    classify_home_context,
    ensure_canonical_home,
    ensure_home_ready,
    home_levels_are_distinct,
    localize_home,
    navigate_home_building,
)
from tasks.runtime_identity import RuntimeIdentityAssurance, VerifiedRuntimeIdentity


def _identity() -> VerifiedRuntimeIdentity:
    return VerifiedRuntimeIdentity(
        "test-runtime",
        "acct-1",
        "server-1",
        "reset-1",
        RuntimeIdentityAssurance.SUPERVISED_NAVIGATION_BINDING,
        ("test-identity",),
    )


def _ready(**changes) -> HomeReadyObservation:
    base = dict(
        game_foregrounded=True,
        expected_native_profile=True,
        identity=_identity(),
        manual_only_state=False,
        blocking_unknown_modal=False,
    )
    base.update(changes)
    return HomeReadyObservation(**base)


def _atlas() -> HomeAtlas:
    profile = PlatformProfile("BlueStacks 5 / Android", "pns-bluestacks-5-p64-800x1280-v1", (800, 1280), "com.global.ztmslg")
    viewport = AtlasViewport(
        "v1",
        "tile.png",
        "a" * 64,
        "now",
        ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
        ((0, 0), (800, 0), (800, 1280), (0, 1280)),
        1.0,
        0.0,
        "origin",
    )
    visible = SemanticBuilding(
        "home.building.research_lab",
        "Research Lab",
        ((350, 500), (450, 500), (450, 620), (350, 620)),
        0.95,
        ("v1",),
        semantic_proof=("test",),
    )
    return HomeAtlas(
        2,
        "test",
        "1",
        profile,
        "fully_zoomed_out",
        "atlas pixels",
        (0, 0),
        1600,
        1800,
        "atlas.png",
        "test",
        "test",
        (((0, 0), (1600, 0), (1600, 1800), (0, 1800)),),
        (),
        (viewport,),
        (visible,),
    )


def _loc(
    *,
    recognized: bool = True,
    zoom: ZoomIdentity = ZoomIdentity.FULLY_ZOOMED_OUT,
    tx: float = 0.0,
    ty: float = 0.0,
    residual: float = 0.4,
    digest: str = "a" * 64,
) -> LocalizationResult:
    return LocalizationResult(
        recognized,
        "BlueStacks 5 / Android",
        "pns-bluestacks-5-p64-800x1280-v1",
        zoom,
        ((1, 0, tx), (0, 1, ty), (0, 0, 1)) if recognized else None,
        ((tx, ty), (tx + 800, ty), (tx + 800, ty + 1280), (tx, ty + 1280)),
        0.95 if recognized else 0.0,
        ("v1",) if recognized else (),
        residual if recognized else None,
        AmbiguityState.NONE if recognized else AmbiguityState.INSUFFICIENT_LANDMARKS,
        "interior",
        digest,
        "now",
    )


class HomeContextTests(unittest.TestCase):
    def test_three_home_levels_are_distinct(self):
        self.assertTrue(home_levels_are_distinct())
        ready = ensure_home_ready(_ready())
        localized = localize_home(_ready(), _loc(tx=100, ty=50, residual=1.5))
        canonical = ensure_canonical_home(_ready(), _loc(residual=0.4))
        self.assertEqual(ready.level, HomeContextLevel.HOME_READY)
        self.assertEqual(localized.level, HomeContextLevel.HOME_LOCALIZED)
        self.assertEqual(canonical.level, HomeContextLevel.HOME_CANONICAL)
        self.assertNotEqual(ready.level, localized.level)
        self.assertNotEqual(localized.level, canonical.level)

    def test_localized_home_does_not_force_canonical(self):
        decision = navigate_home_building(_atlas(), "home.building.research_lab", _ready(), _loc(tx=120, ty=80, residual=1.2))
        self.assertFalse(decision.requires_canonical_recovery)
        self.assertNotEqual(decision.action, HomePrimitiveAction.RECOVER_CANONICAL)
        self.assertIn(decision.action, {HomePrimitiveAction.BIND_BUILDING, HomePrimitiveAction.PAN, HomePrimitiveAction.TAP_BUILDING})

    def test_visible_building_binds_without_pan(self):
        binding = BuildingBinding(
            "home.building.research_lab",
            (350, 500, 450, 620),
            "a" * 64,
            0.95,
            ("ocr",),
        )
        decision = navigate_home_building(_atlas(), "home.building.research_lab", _ready(), _loc(), binding)
        self.assertEqual(decision.action, HomePrimitiveAction.TAP_BUILDING)
        self.assertIsNotNone(decision.navigation)
        self.assertEqual(decision.navigation.action, NavigationAction.TAP_TARGET)

    def test_offscreen_building_uses_bounded_atlas_navigation(self):
        nav = ClosedLoopBuildingNavigator(_atlas(), "home.building.research_lab")
        decision = navigate_home_building(
            _atlas(),
            "home.building.research_lab",
            _ready(),
            _loc(tx=-900, ty=0, digest="b" * 64),
            navigator=nav,
        )
        self.assertEqual(decision.action, HomePrimitiveAction.PAN)
        self.assertIsNotNone(decision.navigation)
        self.assertEqual(decision.navigation.action, NavigationAction.PAN)

    def test_failed_localization_routes_through_canonical_recovery(self):
        decision = navigate_home_building(
            _atlas(),
            "home.building.research_lab",
            _ready(),
            _loc(recognized=False, zoom=ZoomIdentity.ZOOMED_IN),
        )
        self.assertTrue(decision.requires_canonical_recovery)
        self.assertEqual(decision.action, HomePrimitiveAction.RECOVER_CANONICAL)
        classified = classify_home_context(_ready(), _loc(recognized=False, zoom=ZoomIdentity.ZOOMED_IN))
        self.assertTrue(classified.requires_canonical_recovery)

    def test_synthetic_intermediate_transform_never_authorizes_direct_navigation(self):
        intermediate = _loc(zoom=ZoomIdentity.INTERMEDIATE)
        localized = localize_home(_ready(), intermediate)
        self.assertEqual(localized.action, HomePrimitiveAction.RECOVER_CANONICAL)
        self.assertTrue(localized.requires_canonical_recovery)
        decision = navigate_home_building(
            _atlas(),
            "home.building.research_lab",
            _ready(),
            intermediate,
        )
        self.assertEqual(decision.action, HomePrimitiveAction.RECOVER_CANONICAL)
        self.assertTrue(decision.requires_canonical_recovery)

    def test_configuration_without_verified_identity_cannot_be_home_ready(self):
        decision = ensure_home_ready(_ready(identity=None))
        self.assertIsNone(decision.level)
        self.assertEqual(decision.reason, "account_server_identity_unavailable")

    def test_primitives_digest_is_stable_hex(self):
        self.assertEqual(len(HOME_NAVIGATION_PRIMITIVES_DIGEST), 64)


if __name__ == "__main__":
    unittest.main()
