"""Focused offline tests for the Phase-3 Noah's Tavern navigation-development adapter.

These prove the flow-agnostic navigation boundary generalizes to a second flow using only
task-specific route declaration + route logic + these tests, without touching the shared lock,
transport firewall, current-frame verifier, evidence finalizer, or any delivery/governance state.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

import numpy as np

from scripts.bluestacks_flow_collector import EXPECTED_PACKAGE
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.navigation_development_boundary import (
    NavigationBoundaryError,
    NavigationGuardedRuntime,
    make_source_safety_facts,
)
from scripts.noahs_tavern_recruit_bluestacks import (
    NOAHS_TAVERN_HOME_ATLAS_BUILDING_ID,
    NOAHS_TAVERN_SAFE_EXIT_TARGET,
    NoahTavernNavigationCanaryRoute,
    noahs_tavern_navigation_route_declaration,
)
from tasks.noahs_tavern_recruit import (
    HOME_BASE_SCREEN,
    NOAHS_TAVERN_FREE_TARGET,
    NOAHS_TAVERN_SCREEN,
    NOAHS_TAVERN_TIER_TARGET_PREFIX,
    NoahTavernObservation,
    NoahTierObservation,
    RecruitTier,
    TIER_ATTEMPT_MAXIMUMS,
)


def _tiers() -> tuple[NoahTierObservation, ...]:
    return tuple(
        NoahTierObservation(
            tier=tier,
            daily_attempt_maximum=TIER_ATTEMPT_MAXIMUMS[tier],
            attempts_remaining=None,
        )
        for tier in RecruitTier
    )


def _observation(screen: str, captured_monotonic: float | None) -> NoahTavernObservation:
    if screen == "HOME_BASE":
        return NoahTavernObservation(
            screen_state=HOME_BASE_SCREEN,
            selected_tier=None,
            tiers=_tiers(),
            frame_sha256="a" * 64,
            captured_monotonic=captured_monotonic,
            recognized=True,
            home_tavern_target_roi=(100, 300, 260, 470),
        )
    if screen == "HOME_NO_ROI":
        return NoahTavernObservation(
            screen_state=HOME_BASE_SCREEN,
            selected_tier=None,
            tiers=_tiers(),
            frame_sha256="a" * 64,
            captured_monotonic=captured_monotonic,
            recognized=True,
            home_tavern_target_roi=None,
        )
    if screen == "NOAHS_TAVERN":
        return NoahTavernObservation(
            screen_state=NOAHS_TAVERN_SCREEN,
            selected_tier=RecruitTier.BASIC,
            tiers=_tiers(),
            frame_sha256="b" * 64,
            captured_monotonic=captured_monotonic,
            recognized=True,
            overlay_state="none",
        )
    return NoahTavernObservation(
        screen_state="UNKNOWN",
        selected_tier=None,
        tiers=_tiers(),
        frame_sha256="c" * 64,
        captured_monotonic=captured_monotonic,
        recognized=False,
    )


class ScriptedTavernRuntime:
    """Minimal NativeRuntimePort fake that advances a scripted screen list on each nav input."""

    execute = True
    in_flight_action = None
    session = Path("synthetic-tavern-session")

    def __init__(self, screens: list[str]) -> None:
        self.screens = list(screens)
        self.pos = 0
        self.calls: list[tuple[str, dict]] = []
        self._device_state = "device"
        self._foreground_package = EXPECTED_PACKAGE
        self._n = 0

    def measure_device_state(self) -> str:
        return self._device_state

    def measure_foreground_package(self) -> str:
        return self._foreground_package

    def _screen(self) -> str:
        return self.screens[min(self.pos, len(self.screens) - 1)]

    def capture(self, label: str) -> CapturedNativeFrame:
        self._n += 1
        frame = np.zeros((1280, 800, 3), np.uint8)
        frame[0, 0, 0] = self._n % 256
        frame[0, 0, 1] = (self._n // 256) % 256
        payload = f"{self._screen()}:{self._n}".encode()
        return CapturedNativeFrame(
            frame,
            payload,
            hashlib.sha256(frame.tobytes()).hexdigest(),
            time.monotonic(),
            Path(f"{label}.png"),
        )

    def recognizer(self, frame, *, captured_monotonic=None, stale=False):
        return _observation(self._screen(), captured_monotonic)

    def _advance(self) -> None:
        self.pos = min(self.pos + 1, len(self.screens) - 1)

    def tap(self, source, **kwargs) -> None:
        self.calls.append(("tap", dict(kwargs)))
        self._advance()

    def back(self, source, **kwargs) -> None:
        self.calls.append(("back", dict(kwargs)))
        self._advance()

    def reconcile(self, *args, **kwargs) -> None:
        return None

    def record_recovery(self, **kwargs) -> None:
        return None


class NoahTavernNavigationDeclarationTests(unittest.TestCase):
    def test_declaration_is_navigation_only_and_excludes_recruit_target(self) -> None:
        declaration = noahs_tavern_navigation_route_declaration()
        declaration.validate()
        self.assertEqual(declaration.consequence_class, "navigation_only")
        self.assertEqual(declaration.allowed_gesture_classes, frozenset({"tap", "back"}))
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
    def test_navigation_round_trip_home_to_tavern_to_home(self) -> None:
        stub = ScriptedTavernRuntime(["HOME_BASE", "NOAHS_TAVERN", "HOME_BASE"])
        route = NoahTavernNavigationCanaryRoute(
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

    def test_missing_home_tavern_target_is_blocked(self) -> None:
        stub = ScriptedTavernRuntime(["HOME_NO_ROI"])
        route = NoahTavernNavigationCanaryRoute(stub, recognizer=stub.recognizer, settle_seconds=0.0)
        result = route.run()
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.reason, "home_tavern_target_not_current_frame_bound")
        self.assertEqual(stub.calls, [])

    def test_unrecognized_source_is_blocked_without_transport(self) -> None:
        stub = ScriptedTavernRuntime(["UNKNOWN"])
        route = NoahTavernNavigationCanaryRoute(stub, recognizer=stub.recognizer, settle_seconds=0.0)
        result = route.run()
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.reason, "source_state_not_recognized")
        self.assertEqual(stub.calls, [])

    def test_safe_exit_rejects_unrecognized_successor_after_one_input(self) -> None:
        stub = ScriptedTavernRuntime(["HOME_BASE", "NOAHS_TAVERN", "UNKNOWN"])
        route = NoahTavernNavigationCanaryRoute(stub, recognizer=stub.recognizer, settle_seconds=0.0)
        result = route.run()
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.reason, "safe_exit_canonical_home_not_proven")
        self.assertEqual(result.navigation_input_count, 2)
        self.assertEqual(len(stub.calls), 2)
        self.assertEqual(result.records[-1]["target_identity"], NOAHS_TAVERN_SAFE_EXIT_TARGET)

    def test_safe_exit_rejects_unrecognized_tavern_source_without_input(self) -> None:
        stub = ScriptedTavernRuntime(["UNKNOWN"])
        route = NoahTavernNavigationCanaryRoute(stub, recognizer=stub.recognizer, settle_seconds=0.0)
        captured = stub.capture("source")
        result = route._return_home(captured, _observation("UNKNOWN", captured.captured_monotonic))
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.reason, "return_source_not_recognized")
        self.assertEqual(stub.calls, [])

    def test_canonical_home_rejects_recognized_tavern_even_if_localizer_is_positive(self) -> None:
        runtime = ScriptedTavernRuntime(["NOAHS_TAVERN"])
        route = NoahTavernNavigationCanaryRoute(
            runtime,
            recognizer=runtime.recognizer,
            home_localizer=SimpleNamespace(localize=lambda _frame: SimpleNamespace(recognized=True, zoom_identity="fully_zoomed_out", frame_sha256="a" * 64)),
            settle_seconds=0.0,
        )
        captured = runtime.capture("tavern")
        self.assertFalse(route._canonical_home_proven(captured, _observation("NOAHS_TAVERN", 1.0)))

    def test_recovery_continuation_route_budget_and_phase_contract(self) -> None:
        import scripts.noahs_tavern_recruit_bluestacks as module
        with TemporaryDirectory() as directory:
            class Runtime(ScriptedTavernRuntime):
                def __init__(self):
                    super().__init__(["NOAHS_TAVERN", "HOME_BASE", "HOME_BASE", "NOAHS_TAVERN", "HOME_BASE"])
                    self.max_inputs = 40
                    self.session = Path(directory)
            runtime = Runtime()
            args = SimpleNamespace(adb="adb", serial="emulator-5554", output_directory=Path(directory), settle_seconds=0.0)
            class FakeRoute:
                def __init__(self, _runtime, **_kwargs):
                    self.records = []
                def _observe(self, _label):
                    return runtime.capture("x"), _observation("NOAHS_TAVERN", 1.0)
                def _return_home(self, _source, _obs):
                    return SimpleNamespace(status="completed", terminal_home_verified=True, navigation_input_count=1, records=({"action": "safe_exit"},))
                def run(self):
                    return SimpleNamespace(status="completed", reason="verified_safe_return_home", terminal_home_verified=True, navigation_input_count=2, records=({"action": "tap_tavern_navigation"}, {"action": "safe_exit_to_canonical_home"}))
            with patch("scripts.noahs_tavern_recruit_bluestacks.LocalBlueStacksRuntime.connect", return_value=runtime), patch(
                "scripts.noahs_tavern_recruit_bluestacks.NoahTavernNavigationCanaryRoute", FakeRoute
            ):
                # Run the checked-in production continuation with a deterministic runtime seam.
                result = json.loads(module.run_noahs_tavern_recovery_continuation(args))
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["terminal_home_verified"])
        self.assertEqual(result["recruit_taps"], 0)
        self.assertEqual(result["navigation_input_count"], 3)
        self.assertEqual(len(result["recovery_records"]), 1)
        self.assertTrue(all(item["phase"] == "recovery_prelude" for item in result["recovery_records"]))
        self.assertEqual(len(result["proof_records"]), 2)
        self.assertTrue(all(item["phase"] == "canonical_round_trip" for item in result["proof_records"]))
        self.assertEqual(runtime.max_inputs, 3)

    def test_recovery_continuation_stops_after_failed_recovery(self) -> None:
        import scripts.noahs_tavern_recruit_bluestacks as module
        with TemporaryDirectory() as directory:
            class Runtime(ScriptedTavernRuntime):
                def __init__(self):
                    super().__init__(["NOAHS_TAVERN", "UNKNOWN"])
                    self.max_inputs = 40
                    self.session = Path(directory)
            runtime = Runtime()
            args = SimpleNamespace(adb="adb", serial="emulator-5554", output_directory=Path(directory), settle_seconds=0.0)
            class FakeRoute:
                def __init__(self, _runtime, **_kwargs): pass
                def _observe(self, _label): return runtime.capture("x"), _observation("UNKNOWN", 1.0)
            with patch("scripts.noahs_tavern_recruit_bluestacks.LocalBlueStacksRuntime.connect", return_value=runtime):
                with patch("scripts.noahs_tavern_recruit_bluestacks.NoahTavernNavigationCanaryRoute", FakeRoute):
                    result = json.loads(module.run_noahs_tavern_recovery_continuation(args))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["navigation_input_count"], 0)
        self.assertEqual(result["proof_records"], [])


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


class NoahTavernNavigationIsolationTests(unittest.TestCase):
    def test_adapter_reads_no_delivery_or_governance_state(self) -> None:
        import scripts.noahs_tavern_recruit_bluestacks as module

        source = Path(module.__file__).read_text(encoding="utf-8").lower()
        for needle in (
            "flow_delivery_queue",
            "flow-delivery-lease",
            "flow_delivery_control",
            "flow_delivery_context",
            "validate_governance",
            "validation-receipt",
            "gameplay_flow_contracts",
            "flow_delivery_coverage",
            "backlog_task_index",
            "backlog.md",
            "current_handoff",
        ):
            self.assertNotIn(needle, source)


class NoahTavernNavigationPnsctlTests(unittest.TestCase):
    def test_preflight_only_is_zero_transport(self) -> None:
        import scripts.pnsctl as pnsctl

        args = SimpleNamespace(
            preflight_only=True,
            live=False,
            yes=False,
            supervised_live_opt_in=False,
        )
        payload = json.loads(pnsctl.noahs_tavern_navigation(args))
        self.assertEqual(payload["status"], "preflight_passed")
        self.assertEqual(payload["transport_calls"], 0)
        self.assertEqual(payload["production_registration"], "NOT_REGISTERED")
        self.assertFalse(payload["scheduler_enabled"])

    def test_live_requires_yes_and_supervised_opt_in(self) -> None:
        import scripts.pnsctl as pnsctl

        with self.assertRaises(pnsctl.OperatorError):
            pnsctl.noahs_tavern_navigation(
                SimpleNamespace(
                    preflight_only=False,
                    live=True,
                    yes=False,
                    supervised_live_opt_in=False,
                )
            )
        with self.assertRaises(pnsctl.OperatorError):
            pnsctl.noahs_tavern_navigation(
                SimpleNamespace(
                    preflight_only=False,
                    live=True,
                    yes=True,
                    supervised_live_opt_in=False,
                )
            )

    def test_preflight_capture_is_zero_transport_and_owns_navigation_session(self) -> None:
        import scripts.pnsctl as pnsctl

        class FakeRuntime:
            execute = False
            max_inputs = 40

            def __init__(self, session: Path):
                self.session = session
                self.session.mkdir(parents=True, exist_ok=True)
                self.calls = 0

            def capture(self, label: str) -> CapturedNativeFrame:
                self.calls += 1
                frame = np.zeros((1280, 800, 3), np.uint8)
                path = self.session / f"{label}.png"
                return CapturedNativeFrame(frame, frame.tobytes(), hashlib.sha256(frame.tobytes()).hexdigest(), time.monotonic(), path)

        with TemporaryDirectory() as directory:
            runtime = FakeRuntime(Path(directory) / "runtime")
            args = SimpleNamespace(
                preflight_capture=True,
                preflight_only=False,
                live=False,
                yes=False,
                supervised_live_opt_in=False,
                adb=Path("adb"),
                serial="emulator-5554",
                output_directory=Path(directory) / "output",
            )
            localization = SimpleNamespace(recognized=False, zoom_identity="unknown", frame_sha256="")
            with patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", return_value=runtime), patch(
                "scripts.noahs_tavern_recruit_bluestacks.BlueStacksHomeLocalizer",
                return_value=SimpleNamespace(localize=lambda _frame: localization),
            ) as localizer, patch("scripts.navigation_development_boundary.NavigationDevelopmentSession") as session:
                session.return_value.__enter__.return_value = session.return_value
                payload = json.loads(pnsctl.noahs_tavern_navigation(args))
            self.assertEqual(payload["transport_calls"], 0)
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(runtime.calls, 1)
            self.assertTrue(session.called)
            self.assertTrue(localizer.called)

    def test_preflight_capture_and_preflight_only_are_mutually_exclusive(self) -> None:
        import scripts.pnsctl as pnsctl

        with self.assertRaisesRegex(pnsctl.OperatorError, "mutually exclusive"):
            pnsctl.noahs_tavern_navigation(
                SimpleNamespace(
                    preflight_capture=True,
                    preflight_only=True,
                    live=False,
                    yes=False,
                    supervised_live_opt_in=False,
                )
            )
if __name__ == "__main__":
    unittest.main()
