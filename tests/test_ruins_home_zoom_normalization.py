from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from safe_action_core.store import SafetyStore

from automation_service.native_execution import NativeRouteRequest
from scripts import base_route_native_runtime as native_runtime
from scripts import ruins_challenge_bluestacks as native_route
from scripts.bluestacks_flow_collector import ADBRunner
from scripts.bluestacks_native_runtime import CapturedNativeFrame, IntegratedRouteResult, LocalBlueStacksRuntime, captured_native_frame_from_png
from scripts.home_atlas_bluestacks import HomeDriverDisposition, HomeDriverStep
from scripts.navigation_development_boundary import RuntimeInputLock
from scripts import navigation_development_boundary as development
from scripts.ruins_challenge_bluestacks import RuinsIntegratedRoute
from scripts.startup_recovery import ContextualPopupRecoveryResult
from tasks.home_atlas_vision import frame_digest
from tasks.home_atlas_planner import BuildingViewportPlan, DirectPanPlan, PlanDisposition
from tasks.home_atlas import AmbiguityState, LocalizationResult, ZoomIdentity
from tasks.runtime_identity import (
    BLUESTACKS_ADB,
    BLUESTACKS_SERIAL,
    derive_resource_runtime_identity,
    resource_fixed_runtime_binding,
)
from tasks.scheduler_task_result import SchedulerIdentity


FIXTURES = Path(__file__).parent / "fixtures"
HOME_PNG = (FIXTURES / "home_base" / "native-home-20261029.png").read_bytes()
NON_HOME_PNG = (FIXTURES / "home_nav" / "campaign-20261028-a.png").read_bytes()


def _zoomed_home_png() -> bytes:
    """A distinct clean-Home successor, as the live pinch changed the settled frame."""

    frame = cv2.imdecode(np.frombuffer(HOME_PNG, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise AssertionError("test Home PNG decoding failed")
    frame[640, 400] = 255 - frame[640, 400]
    encoded, payload = cv2.imencode(".png", frame)
    if not encoded:
        raise AssertionError("test PNG encoding failed")
    return payload.tobytes()


class _BlueStacksDevice(ADBRunner):
    """ADB surface below the real LocalBlueStacksRuntime; frames replay in order."""

    def run(
        self, *arguments: str, timeout: float = 30.0, input_payload: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        raise AssertionError("replay must never execute an ADB command")

    def __init__(self, payloads: list[bytes]) -> None:
        super().__init__("replay-adb", BLUESTACKS_SERIAL)
        self.payloads = list(payloads)
        self.taps: list[tuple[int, int]] = []

    def capture_png(self) -> bytes:
        return self.payloads.pop(0) if len(self.payloads) > 1 else self.payloads[0]

    def get_state(self) -> str:
        return "device"

    def shell_text(self, *_arguments: str, timeout: float = 30.0) -> str:
        return "mCurrentFocus=Window{1 u0 com.global.ztmslg/com.unity3d.player.UnityPlayerActivity}"

    def dispatch_tap(self, point: tuple[int, int]) -> None:
        self.taps.append(point)


class _CanonicalExecutor:
    transport_calls_by_category = {"challenge": 0, "chest": 0}

    def status(self, *_args, **_kwargs):
        raise AssertionError("Home preparation must not query consequential effects")

    def execute(self, *_args, **_kwargs):
        raise AssertionError("Home preparation must not dispatch consequential effects")


class RuinsHomeZoomNormalizationTests(unittest.TestCase):
    def _session(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(development, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"))
        return self.enterContext(development.DevelopmentSession(
            owner="ruins-route-fixture", invocation_id="offline",
            session_directory=root / "session", max_inputs=48,
        ))
    @staticmethod
    def _frame(digest: str):
        return CapturedNativeFrame(
            frame=np.zeros((1280, 800, 3), dtype=np.uint8),
            png=b"", sha256=digest, captured_monotonic=1.0, path=Path("replay.png"),
        )

    @staticmethod
    def _step(disposition: HomeDriverDisposition, digest: str, reason: str = "test"):
        return SimpleNamespace(
            disposition=disposition,
            source_frame_sha256=digest,
            reason=reason,
        )

    def _route(self, frames, steps):
        runtime = SimpleNamespace(captures=list(frames), zoom_calls=[])
        runtime.capture = lambda _label: runtime.captures.pop(0)
        runtime.dispatch_zoom_out = lambda source, facts, transport=None: (
            runtime.zoom_calls.append((source, facts, transport))
        )
        driver = SimpleNamespace(steps=list(steps), recorded=[])
        driver.observe = lambda _frame: driver.steps.pop(0)
        driver.record_zoom_input_dispatched = lambda digest: driver.recorded.append(
            digest
        )
        route = RuinsIntegratedRoute.__new__(RuinsIntegratedRoute)
        route.runtime = runtime
        route.session = self._session()
        route.reset_identity = "game-day-2026-11-08"
        route._navigation_identity = None
        route.home_driver = driver
        route.zoom_transport = None
        route.post_input_delay = 0.0
        return route, runtime, driver

    def test_canonical_home_requires_no_zoom(self):
        before = self._frame("a" * 64)
        route, runtime, _driver = self._route(
            [before], [self._step(HomeDriverDisposition.BIND, before.sha256)]
        )

        captured, _step, reason = route._recover_home_zoom_before_ruins_binding()

        self.assertIs(captured, before)
        self.assertIsNone(reason)
        self.assertEqual(runtime.zoom_calls, [])

    def test_unknown_localization_blocks_without_campaign_bypass(self):
        before = self._frame("a" * 64)
        route, runtime, _driver = self._route(
            [before],
            [
                self._step(
                    HomeDriverDisposition.BLOCKED,
                    before.sha256,
                    "home_localization_ambiguous:unknown",
                )
            ],
        )

        captured, _step, reason = route._recover_home_zoom_before_ruins_binding()

        self.assertIsNone(captured)
        self.assertEqual(
            reason, "home_zoom_recovery_blocked:home_localization_ambiguous:unknown"
        )
        self.assertEqual(runtime.zoom_calls, [])

    def test_supported_noncanonical_home_recovers_to_settled_frame(self):
        before = self._frame("a" * 64)
        immediate = self._frame("b" * 64)
        settled = self._frame("c" * 64)
        route, runtime, driver = self._route(
            [before, immediate, immediate, settled],
            [
                self._step(HomeDriverDisposition.RECOVER_ZOOM, "semantic-before"),
                self._step(HomeDriverDisposition.PAN, "semantic-settled"),
            ],
        )

        captured, step, reason = route._recover_home_zoom_before_ruins_binding()

        self.assertIs(captured, settled)
        self.assertIsNone(reason)
        self.assertEqual(driver.recorded, ["semantic-before"])
        self.assertEqual(len(runtime.zoom_calls), 1)
        assert step is not None
        self.assertIs(step.disposition, HomeDriverDisposition.PAN)

    def test_unchanged_settled_frame_blocks_after_one_zoom(self):
        before = self._frame("a" * 64)
        route, runtime, driver = self._route(
            [before, self._frame("b" * 64), self._frame("b" * 64), self._frame("a" * 64)],
            [self._step(HomeDriverDisposition.RECOVER_ZOOM, "semantic-before")],
        )

        captured, _step, reason = route._recover_home_zoom_before_ruins_binding()

        self.assertIsNone(captured)
        self.assertEqual(reason, "home_zoom_recovery_no_progress")
        self.assertEqual(driver.recorded, ["semantic-before"])
        self.assertEqual(len(runtime.zoom_calls), 1)

    def test_home_pan_inputs_stop_at_route_budget_even_if_driver_keeps_planning(self):
        route = RuinsIntegratedRoute.__new__(RuinsIntegratedRoute)
        route.session = self._session()
        route.reset_identity = "game-day-2026-11-08"
        route._navigation_identity = None
        frames = iter(self._frame(f"{index:064x}") for index in range(1, 14))
        before = next(frames)
        localized = LocalizationResult(
            True, "bluestacks", "test", ZoomIdentity.FULLY_ZOOMED_OUT, None, (),
            1.0, (), 0.0, AmbiguityState.NONE, "interior", before.sha256, "test",
        )
        step = HomeDriverStep(
            disposition=HomeDriverDisposition.PAN, reason="calculated_direct_pan",
            source_frame_sha256=before.sha256,
            localization=localized,
            plan=DirectPanPlan(
                PlanDisposition.PAN, "calculated_direct_pan",
                BuildingViewportPlan(
                    PlanDisposition.PAN, "calculated_direct_pan", native_route.RUINS_HOME_ATLAS_BUILDING_ID,
                    (0.0, 0.0), (50.0, 20.0), (50.0, 20.0), None, (50.0, 20.0),
                ),
                drag_start=(450, 500), drag_end=(500, 520),
            ),
        )
        swipes = []
        reconciliations = []
        route.runtime = SimpleNamespace(
            capture=lambda _label: next(frames),
            swipe=lambda _source, **kwargs: swipes.append(kwargs),
            reconcile=lambda *args: reconciliations.append(args),
        )
        route.home_driver = SimpleNamespace(
            localizer=SimpleNamespace(localize=lambda _frame: localized),
            record_pan_progress=lambda *_args: SimpleNamespace(accepted=True, reason="measured_progress"),
            observe=lambda _frame, **_kwargs: step,
        )
        route._prepare_navigation = lambda *_args, **_kwargs: None
        route.post_input_delay = 0
        with patch.object(native_route, "is_clean_home_frame", return_value=True):
            captured, reason = route._pan_home_before_ruins_binding(before, step)
        self.assertIsNone(captured)
        self.assertEqual(reason, "home_atlas_pan_input_limit")
        self.assertEqual(len(swipes), native_route.MAXIMUM_HOME_PAN_INPUTS)
        self.assertEqual(len(reconciliations), native_route.MAXIMUM_HOME_PAN_INPUTS)



class RuinsNativeHomeZoomAccountingTests(unittest.TestCase):
    """Retain journal/session accounting coverage when pan geometry is unavailable.

    Full calculated-pan entry is covered separately with the production Home driver.
    """

    def _run(self, payloads, dispositions, *, startup=False, tamper_journal=False):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        output = root / "sessions"
        output.mkdir()
        device = _BlueStacksDevice(payloads)
        runtimes: list[LocalBlueStacksRuntime] = []
        pinches: list[str] = []
        recorded: list[str] = []
        steps = list(dispositions)

        def connect(**kwargs):
            runtime = LocalBlueStacksRuntime(
                device, Path(kwargs["output_directory"]) / f"{kwargs['workflow']}-replay", execute=True,
            )
            runtimes.append(runtime)
            return runtime

        class Pinch:
            def __init__(self, *, adb, serial, evidence_directory):
                self.evidence_directory = evidence_directory

            def zoom_out_once(self):
                pinches.append(str(self.evidence_directory))
                if tamper_journal:
                    events = runtimes[0].events
                    kept = [
                        line for line in events.read_text(encoding="utf-8").splitlines()
                        if json.loads(line).get("type") != "dispatch"
                    ]
                    events.write_text("\n".join(kept) + "\n", encoding="utf-8")

        class HomeDriver:
            def __init__(self, *_args, **_kwargs):
                pass

            def observe(self, frame):
                return SimpleNamespace(
                    disposition=steps.pop(0), reason="retained_live_classification",
                    source_frame_sha256=frame_digest(frame),
                    plan=None,
                )

            def record_zoom_input_dispatched(self, digest):
                recorded.append(digest)

        def recover_startup(runtime, source, *, source_context, recognize_successor, action_key, settle_seconds):
            runtime.tap(source, target_identity="startup-popup-close", target_roi=(700, 80, 760, 140),
                        action_key=action_key)
            settled = runtime.capture("ruins-startup-settled")
            self.assertTrue(recognize_successor(settled))
            return ContextualPopupRecoveryResult(settled, True, True, True, 1, "replayed_startup_dismissed")

        backend = derive_resource_runtime_identity(
            resource_fixed_runtime_binding(), datetime(2026, 11, 8, 3, tzinfo=timezone.utc),
        )
        identity = SchedulerIdentity("account", "server", "game-day-2026-11-08", native_route.RUINS_PRODUCT_ID)
        with (
            patch("scripts.navigation_development_boundary.RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"),
            patch.object(native_runtime.LocalBlueStacksRuntime, "connect", new=connect),
            patch.object(native_runtime, "open_canonical_action_store",
                         new=lambda: SafetyStore(root / "actions.sqlite3")),
            patch.object(native_runtime, "recover_contextual_startup_overlay", new=(
                recover_startup if startup
                else lambda *_args, **_kwargs: self.fail("clean Home must not run startup recovery")
            )),
            patch.object(native_route, "ScrcpyMotionEventZoomTransport", new=Pinch),
            patch.object(native_route, "BlueStacksLocalizeFirstHomeDriver", new=HomeDriver),
            patch.object(native_route.RuinsIntegratedRoute, "_current_frame_ruins_binding",
                         new=lambda _route, _captured: None),
        ):
            lock = RuntimeInputLock(owner="automation-service", invocation_id="ruins-replay").acquire()
            try:
                binding = native_route.create_service_binding(native_runtime.make_native_route_binding)
                outcome = binding.run(NativeRouteRequest(
                    flow_id=binding.flow_id, product_id=binding.product_id,
                    product_revision=binding.product_revision,
                    runtime_profile_id=binding.runtime_profile_id, identity=identity,
                    previous_reset_id=None, occurrence_key="ruins-replay-occurrence",
                    checkpoint=lambda: None, validate_identity=lambda: None, runtime_input_lock=lock,
                    adb=str(BLUESTACKS_ADB), serial=BLUESTACKS_SERIAL, output_directory=output,
                    max_inputs=binding.max_inputs, max_actions=binding.max_actions, settle_seconds=0.0,
                    arguments={
                        "account_id": identity.account_id, "server_id": identity.server_id,
                        "current_day": "Sun", "runtime_identity": backend,
                        "runtime_scope": backend.runtime_scope,
                        "action_executor_factory": lambda _context: _CanonicalExecutor(),
                    },
                ))
            finally:
                lock.release()
        self.assertEqual(steps, [])
        runtime = runtimes[0]
        dispatches = [
            row for row in map(json.loads, runtime.events.read_text(encoding="utf-8").splitlines())
            if row.get("type") == "dispatch"
        ]
        return outcome, runtime, dispatches, pinches, recorded

    def test_live_home_zoom_input_is_owned_by_the_session(self):
        outcome, runtime, dispatches, pinches, recorded = self._run(
            [HOME_PNG, HOME_PNG, _zoomed_home_png()],
            [HomeDriverDisposition.RECOVER_ZOOM, HomeDriverDisposition.RECOVER_ZOOM, HomeDriverDisposition.PAN],
        )

        self.assertIsNone(outcome.failure)
        self.assertTrue(outcome.accounting_verified)
        self.assertEqual(
            (outcome.input_count, outcome.session_input_count, outcome.runtime_input_count), (1, 1, 1),
        )
        self.assertEqual([(row["target_identity"], row["transport"]) for row in dispatches],
                         [("home-zoom-out", "adapter-owned-native-zoom")])
        self.assertEqual(pinches, [str(runtime.session)])
        self.assertEqual(len(recorded), 1)
        result = outcome.native_result
        self.assertEqual((result["status"], result["reason"]), ("blocked", "home_atlas_pan_geometry_unavailable"))
        self.assertEqual(
            (result["actions_completed"], result["challenge_transport_calls"],
             result["chest_claim_transport_calls"], result["terminal_home_verified"]),
            (0, 0, 0, False),
        )
        self.assertEqual((result["session_input_count"], result["runtime_input_count"]), (1, 1))
        self.assertTrue(result["accounting_verified"])

    def test_startup_recovery_and_route_zoom_use_one_session_total(self):
        outcome, _runtime, dispatches, pinches, _recorded = self._run(
            [NON_HOME_PNG, HOME_PNG, HOME_PNG, _zoomed_home_png()],
            [HomeDriverDisposition.RECOVER_ZOOM, HomeDriverDisposition.RECOVER_ZOOM, HomeDriverDisposition.PAN],
            startup=True,
        )

        self.assertIsNone(outcome.failure)
        startup = outcome.startup_recovery
        assert startup is not None
        self.assertEqual(startup.input_count, 1)
        self.assertTrue(startup.accounting_verified)
        self.assertTrue(outcome.accounting_verified)
        self.assertEqual(
            (outcome.input_count, outcome.session_input_count, outcome.runtime_input_count), (2, 2, 2),
        )
        self.assertEqual([row["target_identity"] for row in dispatches], ["startup-popup-close", "home-zoom-out"])
        self.assertEqual(len(pinches), 1)
        self.assertEqual(outcome.native_result["reason"], "home_atlas_pan_geometry_unavailable")

    def test_restart_from_retained_zoomed_home_blocks_without_input(self):
        outcome, _runtime, dispatches, pinches, recorded = self._run(
            [_zoomed_home_png()], [HomeDriverDisposition.PAN],
        )

        self.assertIsNone(outcome.failure)
        self.assertTrue(outcome.accounting_verified)
        self.assertEqual(
            (outcome.input_count, outcome.session_input_count, outcome.runtime_input_count), (0, 0, 0),
        )
        self.assertEqual((dispatches, pinches, recorded), ([], [], []))
        self.assertEqual(outcome.native_result["reason"], "home_atlas_pan_geometry_unavailable")

    def test_runtime_journal_mismatch_retains_session_owned_input(self):
        outcome, _runtime, dispatches, pinches, _recorded = self._run(
            [HOME_PNG, HOME_PNG, _zoomed_home_png()],
            [HomeDriverDisposition.RECOVER_ZOOM, HomeDriverDisposition.RECOVER_ZOOM, HomeDriverDisposition.PAN],
            tamper_journal=True,
        )

        self.assertEqual((dispatches, len(pinches)), ([], 1))
        self.assertIn("differs from its retained dispatch journal", outcome.failure)
        self.assertFalse(outcome.accounting_verified)
        self.assertEqual((outcome.session_input_count, outcome.runtime_input_count), (1, 1))
        self.assertEqual(outcome.native_result, {})
        partial = outcome.partial_result
        assert partial is not None
        self.assertFalse(partial["accounting_verified"])
        self.assertFalse(partial["journal_verified"])
        self.assertEqual(
            (partial["status"], partial["ruins_dispatch_count"]), ("blocked", 0),
        )


class _AtlasEntryDevice(_BlueStacksDevice):
    """Replay native pixels after each requested transport, without touching a device."""

    def __init__(self, source, far, bound, successor, *, pan_effect="bound"):
        super().__init__([source])
        self.far = far
        self.bound = bound
        self.successor = successor
        self.pan_effect = pan_effect
        self.swipes = []
        self.pinches = 0

    def zoom_out_once(self):
        self.pinches += 1
        self.payloads = [self.far]

    def dispatch_swipe(self, start, end, duration_ms: int = 400) -> None:
        self.swipes.append((start, end))
        if self.pan_effect == "bound":
            self.payloads = [self.bound]
        elif self.pan_effect == "unknown":
            self.payloads = [NON_HOME_PNG]

    def dispatch_tap(self, point):
        super().dispatch_tap(point)
        self.payloads = [self.successor]


class RuinsCalculatedHomeEntryTests(unittest.TestCase):
    """Exercise the real Home driver, Atlas binder, guarded runtime and native journal.

    Retained native Home viewports are replayed, not a physical pan simulation.
    Ruins list semantics are injected separately: no native Ruins successor or
    challenge/chest acceptance is claimed by these Home-entry checks.
    """

    @classmethod
    def setUpClass(cls):
        cls.far = (FIXTURES / "campaign_home_entry/canonical-home-20261029.png").read_bytes()
        cls.bound = (native_route.ROOT / "tasks/assets/home_atlas/bluestacks/800x1280/tiles/viewport-014.png").read_bytes()
        cls.zoomed = (FIXTURES / "home_base/native-home-bio-zoomed-20261029.png").read_bytes()
        cls.atlas_path = native_route.ROOT / "tasks/assets/home_atlas/bluestacks/800x1280/atlas.json"
        cls.atlas = native_route.load_home_atlas(cls.atlas_path)
        cls.localizer = native_route.BlueStacksHomeLocalizer(cls.atlas, cls.atlas_path)

    @classmethod
    def tearDownClass(cls):
        del cls.localizer

    def _entry(self, *, zoom=False, pan_effect="bound", successor="ruins", bind=True, max_inputs=48):
        previous = getattr(self, "_entry_scope", None)
        if previous is not None:
            previous.close()
        self._entry_scope = ExitStack()
        self.addCleanup(self._entry_scope.close)
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        device = _AtlasEntryDevice(
            self.zoomed if zoom else self.far, self.far, self.bound,
            self.bound if successor == "unchanged" else NON_HOME_PNG, pan_effect=pan_effect,
        )
        runtime = LocalBlueStacksRuntime(device, root / "native", execute=True)
        runtime.max_inputs = max_inputs
        self.enterContext(patch.object(development, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"))
        session = self._entry_scope.enter_context(development.DevelopmentSession(
            owner="ruins-atlas-entry", invocation_id="offline",
            session_directory=root / "session", max_inputs=max_inputs,
        ))
        backend = derive_resource_runtime_identity(
            resource_fixed_runtime_binding(), datetime(2026, 11, 8, 3, tzinfo=timezone.utc),
        )
        home_driver = native_route.BlueStacksLocalizeFirstHomeDriver(
            self.atlas, self.atlas_path,
            native_route.HomeReadyObservation(True, True, backend, False, False),
            native_route.RUINS_HOME_ATLAS_BUILDING_ID, localizer=self.localizer,
            maximum_pans=native_route.MAXIMUM_HOME_PAN_INPUTS,
            maximum_zoom_inputs=native_route.MAXIMUM_HOME_ZOOM_INPUTS,
        )
        route = RuinsIntegratedRoute(
            runtime, reset_identity="game-day-2026-11-08", current_day="Sun",
            account_id="account", server_id="server", runtime_scope=backend.runtime_scope,
            product_id=native_route.RUINS_PRODUCT_ID, product_revision=native_route.RUINS_PRODUCT_REVISION,
            runtime_identity=backend, action_executor=_CanonicalExecutor(), session=session,
            initial_capture=runtime.capture("replay-home"), home_driver=home_driver,
            zoom_transport=device, post_input_delay=0,
        )
        recognition = SimpleNamespace(observation=SimpleNamespace(
            recognized=successor in {"ruins", "wrong-reset"},
            screen_identity="RUINS_CHALLENGE" if successor in {"ruins", "wrong-reset"} else "UNKNOWN",
            reset_identity="other-reset" if successor == "wrong-reset" else route.reset_identity,
        ))
        self.enterContext(patch.object(native_route, "recognize_ruins_frame", return_value=recognition))
        if not bind:
            self.enterContext(patch.object(route, "_current_frame_ruins_binding", return_value=None))
        return route, runtime, device

    @staticmethod
    def _dispatches(runtime):
        return [
            row for row in map(json.loads, runtime.events.read_text(encoding="utf-8").splitlines())
            if row.get("type") == "dispatch"
        ]

    def test_zoom_then_calculated_pan_uses_fresh_mapped_binding(self):
        route, runtime, device = self._entry(zoom=True)
        entry = route._enter_ruins()
        self.assertIsInstance(entry, tuple)
        assert isinstance(entry, tuple)
        self.assertEqual(entry[1].observation.screen_identity, "RUINS_CHALLENGE")
        self.assertEqual(entry[1].observation.reset_identity, route.reset_identity)
        self.assertEqual((device.pinches, len(device.swipes), len(device.taps)), (1, 1, 1))
        dispatches = self._dispatches(runtime)
        self.assertEqual([row["target_identity"] for row in dispatches], [
            "home-zoom-out", native_route.RUINS_HOME_PAN_TARGET, native_route.RUINS_HOME_ATLAS_BUILDING_ID,
        ])
        self.assertNotEqual(dispatches[1]["source_sha256"], dispatches[2]["source_sha256"])
        source = captured_native_frame_from_png(
            self.bound, captured_monotonic=1.0, path=Path("replay-bound.png"),
        )
        target = route._current_frame_ruins_binding(source)
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(device.taps, [((target[0] + target[2]) // 2, (target[1] + target[3]) // 2)])
        self.assertEqual(runtime.input_count, 3)
        self.assertEqual(route.session.input_count, 3)
        self.assertEqual((route.challenge_transport_calls, route.chest_claim_transport_calls), (0, 0))

    def test_pan_only_restart_does_not_repeat_zoom(self):
        route, runtime, device = self._entry()
        self.assertIsInstance(route._enter_ruins(), tuple)
        self.assertEqual((device.pinches, len(device.swipes), len(device.taps), runtime.input_count), (0, 1, 1, 2))
        self.assertEqual(route.session.input_count, 2)

    def test_unavailable_current_binding_never_uses_projected_target(self):
        route, runtime, device = self._entry(bind=False)
        result = route._enter_ruins()
        self.assertIsInstance(result, IntegratedRouteResult)
        assert isinstance(result, IntegratedRouteResult)
        self.assertEqual(result.reason, "home_atlas_ruins_not_bound")
        self.assertEqual((len(device.swipes), device.taps, runtime.input_count), (1, [], 1))

    def test_unchanged_or_unknown_pan_successor_stops_without_retry(self):
        for effect in ("unchanged", "unknown"):
            with self.subTest(effect=effect):
                route, runtime, device = self._entry(pan_effect=effect)
                result = route._enter_ruins()
                self.assertIsInstance(result, IntegratedRouteResult)
                assert isinstance(result, IntegratedRouteResult)
                self.assertTrue(result.reason.startswith("home_atlas_pan_successor_not_verified:"))
                self.assertEqual((len(device.swipes), device.taps, runtime.input_count), (1, [], 1))
                self.assertEqual(len(self._dispatches(runtime)), 1)

    def test_unrecognized_unchanged_or_wrong_reset_ruins_successor_stops_after_one_tap(self):
        for successor in ("unknown", "unchanged", "wrong-reset"):
            with self.subTest(successor=successor):
                route, runtime, device = self._entry(successor=successor)
                result = route._enter_ruins()
                self.assertIsInstance(result, IntegratedRouteResult)
                assert isinstance(result, IntegratedRouteResult)
                self.assertEqual(result.reason, "Ruins list not positively recognized")
                self.assertEqual((len(device.swipes), len(device.taps), runtime.input_count), (1, 1, 2))
                self.assertEqual((route.challenge_transport_calls, route.chest_claim_transport_calls), (0, 0))

    def test_non_pan_plan_objects_fail_closed_before_transport(self):
        for malformed_plan in (object(), SimpleNamespace(drag_start=(450, 500), drag_end=(500, 520))):
            with self.subTest(plan_type=type(malformed_plan).__name__):
                route, runtime, device = self._entry()
                observe = route.home_driver.observe

                def malformed_step(frame, *, localization=None):
                    return replace(observe(frame, localization=localization), plan=malformed_plan)

                with patch.object(route.home_driver, "observe", side_effect=malformed_step):
                    result = route._enter_ruins()
                assert isinstance(result, IntegratedRouteResult)
                self.assertEqual(result.reason, "home_atlas_pan_geometry_unavailable")
                self.assertEqual((device.swipes, device.taps, runtime.input_count), ([], [], 0))
                self.assertEqual(self._dispatches(runtime), [])

    def test_runtime_input_budget_blocks_entry_tap_after_pan(self):
        route, runtime, device = self._entry(max_inputs=1)
        with self.assertRaisesRegex(RuntimeError, "input limit reached"):
            route._enter_ruins()
        self.assertEqual((len(device.swipes), device.taps, runtime.input_count), (1, [], 1))
        self.assertEqual(len(self._dispatches(runtime)), 1)


if __name__ == "__main__":
    unittest.main()
