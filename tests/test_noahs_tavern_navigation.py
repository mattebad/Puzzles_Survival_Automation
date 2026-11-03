"""Focused offline tests for the Phase-3 Noah's Tavern navigation-development adapter.

These prove the flow-agnostic navigation boundary generalizes to a second flow using only
task-specific route declaration + route logic + these tests, without touching the shared lock,
transport firewall, current-frame verifier, evidence finalizer, or any delivery/governance state.
"""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.navigation_development_boundary import (
    NavigationBoundaryError,
    NavigationGuardedRuntime,
    make_source_safety_facts,
)
from scripts.noahs_tavern_recruit_bluestacks import (
    NOAHS_TAVERN_HOME_ATLAS_BUILDING_ID,
    NOAHS_TAVERN_SAFE_EXIT_TARGET,
    NoahTavernNavigationRoute,
    noahs_tavern_navigation_route_declaration,
)
from tasks.noahs_tavern_recruit import (
    HOME_BASE_SCREEN,
    NOAHS_TAVERN_FREE_TARGET,
    NOAHS_TAVERN_SCREEN,
    NOAHS_TAVERN_TIER_TARGET_PREFIX,
    RecruitTier,
)
from tests.support.tavern import ScriptedTavernRuntime, _observation


class NoahTavernNavigationDeclarationTests(unittest.TestCase):
    def test_declaration_is_navigation_only_and_excludes_recruit_target(self) -> None:
        declaration = noahs_tavern_navigation_route_declaration()
        declaration.validate()
        self.assertEqual(declaration.consequence_class, "navigation_only")
        self.assertEqual(
            declaration.allowed_gesture_classes,
            frozenset({"tap", "back", "zoom_out"}),
        )
        self.assertIn("home-zoom-out", declaration.allowed_target_identities)
        self.assertIn(NOAHS_TAVERN_HOME_ATLAS_BUILDING_ID, declaration.allowed_target_identities)
        self.assertIn(NOAHS_TAVERN_SAFE_EXIT_TARGET, declaration.allowed_target_identities)
        self.assertNotIn("system-back", declaration.allowed_target_identities)
        for tier in RecruitTier:
            self.assertIn(
                NOAHS_TAVERN_TIER_TARGET_PREFIX + tier.name,
                declaration.allowed_target_identities,
            )
        # The consequential recruit endpoint must not be dispatchable through this route.
        self.assertNotIn(NOAHS_TAVERN_FREE_TARGET, declaration.allowed_target_identities)
        self.assertNotIn("noahs-tavern-daily-free", declaration.allowed_target_identities)
        self.assertEqual(
            declaration.allowed_source_states,
            frozenset({HOME_BASE_SCREEN, NOAHS_TAVERN_SCREEN}),
        )


class NoahTavernNavigationRouteTests(unittest.TestCase):
    def setUp(self):
        # These tests script semantic screens, not native image localization.
        localizer = SimpleNamespace(localize=lambda _frame: SimpleNamespace(recognized=False))
        patcher = patch("scripts.noahs_tavern_recruit_bluestacks.BlueStacksHomeLocalizer", return_value=localizer)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_localization_allocation_failure_blocks_without_further_input(self):
        import cv2

        runtime = ScriptedTavernRuntime(["UNKNOWN"])
        localizer = SimpleNamespace(localize=lambda _frame: None)
        route = NoahTavernNavigationRoute(
            runtime, recognizer=runtime.recognizer, home_localizer=localizer,
            settle_seconds=0.0,
        )
        source = runtime.capture("unknown")
        with patch.object(localizer, "localize", side_effect=cv2.error("allocation failed")):
            result = route._return_home(source, _observation("UNKNOWN", source.captured_monotonic))
        self.assertEqual(result.status, "blocked")
        self.assertEqual(runtime.calls, [])
        self.assertIn("allocation failed", result.records[0]["error"])

    def test_navigation_round_trip_home_to_tavern_to_home(self) -> None:
        stub = ScriptedTavernRuntime(["HOME_BASE", "NOAHS_TAVERN", "HOME_BASE"])
        route = NoahTavernNavigationRoute(
            stub,
            recognizer=stub.recognizer,
            settle_seconds=0.0,
        )
        result = route.run()
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.reason, "verified_safe_return_home")
        self.assertTrue(result.terminal_home_verified)
        self.assertEqual(result.recruit_taps, 0)
        self.assertEqual(result.navigation_input_count, 2)
        self.assertEqual([kind for kind, _ in stub.calls], ["tap", "back"])
        self.assertEqual(stub.calls[0][1]["target_identity"], NOAHS_TAVERN_HOME_ATLAS_BUILDING_ID)
        self.assertFalse(stub.calls[0][1]["consequential"])
        guarded = route.runtime
        self.assertIsInstance(guarded, NavigationGuardedRuntime)
        self.assertTrue(guarded.authorized_gestures)
        for gesture in guarded.authorized_gestures:
            self.assertFalse(gesture["consequential"])
            self.assertTrue(gesture["transport_observed"])
        self.assertEqual(
            [(item[0], item[1]) for item in stub.reconciles],
            [
                (stub.calls[0][1]["action_key"], "confirmed"),
                (stub.calls[1][1]["action_key"], "confirmed"),
            ],
        )

    def test_missing_home_tavern_target_is_blocked(self) -> None:
        stub = ScriptedTavernRuntime(["HOME_NO_ROI"])
        route = NoahTavernNavigationRoute(stub, recognizer=stub.recognizer, settle_seconds=0.0)
        result = route.run()
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.reason, "home_tavern_target_not_current_frame_bound")
        self.assertEqual(stub.calls, [])

    def test_unrecognized_source_is_blocked_without_transport(self) -> None:
        stub = ScriptedTavernRuntime(["UNKNOWN"])
        route = NoahTavernNavigationRoute(stub, recognizer=stub.recognizer, settle_seconds=0.0)
        result = route.run()
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.reason, "source_state_not_recognized")
        self.assertEqual(stub.calls, [])

    def test_safe_exit_rejects_unrecognized_successor_after_one_input(self) -> None:
        stub = ScriptedTavernRuntime(["HOME_BASE", "NOAHS_TAVERN", "UNKNOWN"])
        route = NoahTavernNavigationRoute(stub, recognizer=stub.recognizer, settle_seconds=0.0)
        result = route.run()
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.reason, "safe_exit_canonical_home_not_proven")
        self.assertEqual(result.navigation_input_count, 2)
        self.assertEqual(len(stub.calls), 2)
        self.assertEqual(result.records[-1]["target_identity"], NOAHS_TAVERN_SAFE_EXIT_TARGET)
        self.assertEqual(stub.reconciles[-1][1], "unresolved")

    def test_safe_exit_rejects_unrecognized_tavern_source_without_input(self) -> None:
        stub = ScriptedTavernRuntime(["UNKNOWN"])
        route = NoahTavernNavigationRoute(stub, recognizer=stub.recognizer, settle_seconds=0.0)
        captured = stub.capture("source")
        result = route._return_home(captured, _observation("UNKNOWN", captured.captured_monotonic))
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.reason, "return_source_not_recognized")
        self.assertEqual(stub.calls, [])

    def test_canonical_home_rejects_recognized_tavern_even_if_localizer_is_positive(self) -> None:
        runtime = ScriptedTavernRuntime(["NOAHS_TAVERN"])
        route = NoahTavernNavigationRoute(
            runtime,
            recognizer=runtime.recognizer,
            home_localizer=SimpleNamespace(localize=lambda _frame: SimpleNamespace(recognized=True, zoom_identity="fully_zoomed_out", frame_sha256="a" * 64)),
            settle_seconds=0.0,
        )
        captured = runtime.capture("tavern")
        self.assertFalse(route._canonical_home_proven(captured, _observation("NOAHS_TAVERN", 1.0)))


class NoahTavernFirewallExclusionTests(unittest.TestCase):
    def _guarded(self) -> tuple[NavigationGuardedRuntime, CapturedNativeFrame]:
        stub = ScriptedTavernRuntime(["NOAHS_TAVERN"])
        guarded = NavigationGuardedRuntime(stub, noahs_tavern_navigation_route_declaration())
        return guarded, stub.capture("x")

    def test_consequential_recruit_target_is_denied(self) -> None:
        guarded, source = self._guarded()
        guarded.prepare_source_safety(
            make_source_safety_facts(
                recognized=True,
                source_state=NOAHS_TAVERN_SCREEN,
                frame_sha256=source.sha256,
                captured_monotonic=source.captured_monotonic,
            )
        )
        with self.assertRaises(NavigationBoundaryError):
            guarded.tap(
                source,
                target_identity="noahs-tavern-daily-free",
                target_roi=(90, 925, 385, 1055),
                action_key="recruit-denied",
                consequential=True,
            )

    def test_consequential_flag_on_declared_target_is_denied(self) -> None:
        guarded, source = self._guarded()
        guarded.prepare_source_safety(
            make_source_safety_facts(
                recognized=True,
                source_state=HOME_BASE_SCREEN,
                frame_sha256=source.sha256,
                captured_monotonic=source.captured_monotonic,
                target_roi=(100, 300, 260, 470),
            )
        )
        with self.assertRaisesRegex(NavigationBoundaryError, "consequential"):
            guarded.tap(
                source,
                target_identity=NOAHS_TAVERN_HOME_ATLAS_BUILDING_ID,
                target_roi=(100, 300, 260, 470),
                action_key="building-consequential",
                consequential=True,
            )


if __name__ == "__main__":
    unittest.main()
