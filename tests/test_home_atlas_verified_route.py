"""Offline verified-route integration tests for Home Atlas navigate-building."""

from __future__ import annotations

import importlib
import inspect
import json
import struct
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator
from unittest.mock import patch

import numpy as np

from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.home_atlas_bluestacks import (
    BlueStacksLocalizeFirstHomeDriver,
    CONFIRMED_NOT_DISPATCHED_STATUS,
    HomeDriverDisposition,
    NAVIGATE_BUILDING_TARGET_IDENTITY,
    ScrcpyMotionEventZoomTransport,
    attach_navigate_terminal_reports,
    build_navigate_pan_observation,
    build_navigate_pan_policy_request,
    build_navigate_perception_bundle,
    command_navigate_building,
    create_bluestacks_session_calibration,
    dispatch_verified_navigate_pan,
    gesture_geometry_roi,
    identity_from_captured,
    reject_direct_navigate_building_transport,
)
from scripts.noahs_tavern_recruit_bluestacks import record_home_zoom_recovery_input
from safe_action_core import (
    ActionStatus,
    CentralPolicy,
    SafetyStore,
)
from tasks.home_atlas import (
    AmbiguityState,
    AtlasViewport,
    BuildingBinding,
    HomeAtlas,
    LocalizationResult,
    PlatformProfile,
    SemanticBuilding,
    ZoomIdentity,
)
from tasks.home_atlas_vision import BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, frame_digest
from tasks.home_context import HomeReadyObservation
from tasks.navigation_observability import report_navigation_session
from tasks.navigation_session import (
    AuthorizationScope,
    create_session,
    load_session,
    save_session,
)
from tasks.navigation_session import TrustedTransportNonDispatchAuthority
from tasks.perception_bundle import PerceptionBundleError
from tasks.runtime_identity import RuntimeIdentityAssurance, VerifiedRuntimeIdentity


PROFILE = PlatformProfile(BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, (800, 1280), "com.global.ztmslg")
_TEST_WALL = 1000.0
_TEST_LEASE_TTL = 100.0


class _MonoClock:
    """Keep offline executor timing relative to FakeRuntime capture ordinals.

    ``dispatch_verified_navigate_pan`` acquires its own fresh pre_dispatch capture,
    so the injected clock must stay just ahead of the most recent capture monotonic.
    FakeRuntime sets ``captured_monotonic == ordinal``; tracking the live ordinal
    keeps observation/dispatch ages small and positive after the extra capture.
    """

    def __init__(self, runtime: "_FakeRuntime") -> None:
        self._runtime = runtime

    def __call__(self) -> float:
        return float(self._runtime.ordinal) + 0.2


@contextmanager
def _open_safety_store(directory: Path, *, name: str = "safety.sqlite3") -> Iterator[SafetyStore]:
    """Acquire a leased SafetyStore and always close it (Windows tempfile cleanup)."""

    store = SafetyStore(Path(directory) / name)
    store.acquire_lease("owner", _TEST_WALL, _TEST_LEASE_TTL)
    try:
        yield store
    finally:
        store.close()


def _building(
    *,
    semantic_id: str = "home.building.bank",
    polygon=((300, 400), (440, 400), (440, 540), (300, 540)),
) -> SemanticBuilding:
    return SemanticBuilding(
        semantic_id,
        "Bank",
        polygon,
        0.98,
        ("v1",),
        recognition={"bluestacks": {"label": "Bank"}},
        semantic_proof=("visible Bank label",),
        interaction_eligible=True,
        platform_binding_policy={"bluestacks": {"label": "Bank"}},
    )


def _far_building() -> SemanticBuilding:
    return _building(polygon=((900, 900), (1040, 900), (1040, 1040), (900, 1040)))


def _atlas(target: SemanticBuilding | None = None) -> HomeAtlas:
    target = target or _building()
    viewport = AtlasViewport(
        "v1",
        "unused.png",
        "a" * 64,
        "now",
        ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
        ((0, 0), (800, 0), (800, 1280), (0, 1280)),
        1,
        0,
        "translation",
    )
    polygons = (((0, 0), (1500, 0), (1500, 2800), (0, 2800)),)
    return HomeAtlas(
        3,
        "test",
        "1",
        PROFILE,
        "fully_zoomed_out",
        "atlas pixels",
        (0, 0),
        1500,
        2800,
        "atlas.png",
        "test",
        "test",
        polygons,
        (),
        (viewport,),
        (target,),
        polygons,
        (0.0, 0.0, 1500.0, 2800.0),
    )


def _localization(digest: str = "a" * 64, *, x: float = 0.0, y: float = 0.0) -> LocalizationResult:
    return LocalizationResult(
        True,
        BLUESTACKS_PLATFORM,
        BLUESTACKS_PROFILE_ID,
        ZoomIdentity.FULLY_ZOOMED_OUT,
        ((1.0, 0.0, x), (0.0, 1.0, y), (0.0, 0.0, 1.0)),
        ((x, y), (x + 800.0, y), (x + 800.0, y + 1280.0), (x, y + 1280.0)),
        0.95,
        ("v1",),
        0.4,
        AmbiguityState.NONE,
        "interior",
        digest,
        "now",
    )


class _FakeRuntime:
    execute = True
    in_flight_action = None

    def __init__(self, session: Path):
        self.session = session
        self.swipes: list[dict[str, object]] = []
        self.taps: list[dict[str, object]] = []
        self.ordinal = 0
        self._origin = (0.0, 0.0)
        self.progress_after_swipe = False
        self.captured_frames: list[tuple[str, CapturedNativeFrame]] = []

    def capture(self, label: str) -> CapturedNativeFrame:
        self.ordinal += 1
        frame = np.zeros((1280, 800, 3), np.uint8)
        frame[0, 0] = (self.ordinal % 200, 10, 10)
        if self.progress_after_swipe and "settled" in label:
            # Distinct pixels so semantic digest changes with progress origin.
            frame[10, 10] = (40, 40, 40)
        captured = CapturedNativeFrame(
            frame,
            f"png-{self.ordinal}".encode(),
            "f" * 64,
            float(self.ordinal),
            self.session / f"{label}.png",
        )
        self.captured_frames.append((label, captured))
        return captured

    def captures_labeled(self, label: str) -> list[CapturedNativeFrame]:
        return [captured for name, captured in self.captured_frames if name == label]

    def tap(
        self,
        captured: CapturedNativeFrame,
        *,
        target_identity: str,
        target_roi: tuple[int, int, int, int],
        action_key: str,
        consequential: bool,
    ) -> None:
        self.taps.append(
            {
                "target_identity": target_identity,
                "target_roi": target_roi,
                "action_key": action_key,
                "consequential": consequential,
                "sha256": captured.sha256,
            }
        )

    def swipe(self, captured, *, start, end, action_key, target_identity):
        self.swipes.append(
            {
                "start": start,
                "end": end,
                "action_key": action_key,
                "target_identity": target_identity,
                "sha256": captured.sha256,
            }
        )
        if self.progress_after_swipe:
            self._origin = (self._origin[0] + 300.0, self._origin[1] + 90.0)


def _args(directory: Path, *, building_id: str, execute: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        execute=execute,
        yes=execute,
        atlas=Path(directory) / "atlas.json",
        building_id=building_id,
        maximum_pans=4,
        settle_seconds=0,
        adb="unused",
        serial="emulator-5554",
        output_directory=Path(directory),
    )


def _policy_for(task_id: str) -> CentralPolicy:
    return CentralPolicy(supervised_tasks=frozenset({"MVP-QUEST-TO-CLAIM", task_id}))


def _ready() -> HomeReadyObservation:
    return HomeReadyObservation(
        True,
        True,
        VerifiedRuntimeIdentity(
            "test-runtime",
            "acct-1",
            "server-1",
            "reset-1",
            RuntimeIdentityAssurance.SUPERVISED_NAVIGATION_BINDING,
            ("test-identity",),
        ),
        False,
        False,
    )


class HomeAtlasVerifiedRouteTests(unittest.TestCase):
    def test_headless_scrcpy_pinch_serializes_two_native_pointer_streams(self) -> None:
        messages = ScrcpyMotionEventZoomTransport.pinch_messages(steps=8)

        self.assertEqual(len(messages), 20)
        decoded = [struct.unpack(">BBQiiHHHII", payload) for _label, payload in messages]
        self.assertTrue(all(len(payload) == 32 for _label, payload in messages))
        self.assertEqual(decoded[0][:7], (2, 0, 1, 350, 640, 800, 1280))
        self.assertEqual(decoded[1][:7], (2, 0, 2, 450, 640, 800, 1280))
        self.assertEqual(decoded[-2][:7], (2, 1, 2, 690, 640, 800, 1280))
        self.assertEqual(decoded[-1][:7], (2, 1, 1, 110, 640, 800, 1280))
        self.assertEqual({item[2] for item in decoded}, {1, 2})
        self.assertEqual({(item[5], item[6]) for item in decoded}, {(800, 1280)})

    def test_localize_first_driver_binds_visible_noncanonical_home_without_pan(self) -> None:
        target = _building()
        world = _atlas(target)
        frame = np.zeros((1280, 800, 3), np.uint8)
        digest = frame_digest(frame)
        localization = replace(
            _localization(digest, x=120.0, y=80.0),
            frame_sha256=digest,
        )
        binding = BuildingBinding(
            target.semantic_id,
            (320, 420, 420, 520),
            digest,
            0.95,
            ("current-frame OCR: Bank",),
        )
        localizer = SimpleNamespace(
            localize=lambda _frame: localization,
            canonical_reference=frame,
        )
        with patch(
            "scripts.home_atlas_bluestacks.bind_visible_building",
            return_value=binding,
        ):
            driver = BlueStacksLocalizeFirstHomeDriver(
                world,
                Path("atlas.json"),
                _ready(),
                target.semantic_id,
                localizer=localizer,
            )
            step = driver.observe(frame)
        self.assertEqual(step.disposition, HomeDriverDisposition.COMPLETE)
        self.assertIs(step.binding, binding)
        self.assertEqual(driver.navigator.pan_count, 0)

    def test_localize_first_driver_plans_bounded_pan_for_offscreen_building(self) -> None:
        target = _far_building()
        world = _atlas(target)
        frame = np.zeros((1280, 800, 3), np.uint8)
        digest = frame_digest(frame)
        localization = replace(_localization(digest), frame_sha256=digest)
        localizer = SimpleNamespace(
            localize=lambda _frame: localization,
            canonical_reference=frame,
        )
        with patch(
            "scripts.home_atlas_bluestacks.bind_visible_building",
            return_value=None,
        ):
            driver = BlueStacksLocalizeFirstHomeDriver(
                world,
                Path("atlas.json"),
                _ready(),
                target.semantic_id,
                localizer=localizer,
                maximum_pans=4,
            )
            step = driver.observe(frame)
        self.assertEqual(step.disposition, HomeDriverDisposition.PAN)
        self.assertIsNotNone(step.plan)
        self.assertIsNotNone(step.plan.drag_start)
        self.assertIsNotNone(step.plan.drag_end)

    def test_localize_first_driver_routes_intermediate_zoom_to_bounded_recovery(self) -> None:
        target = _building()
        world = _atlas(target)
        first = np.zeros((1280, 800, 3), np.uint8)
        second = first.copy()
        second[0, 0] = (1, 1, 1)
        intermediate = replace(
            _localization(),
            recognized=False,
            zoom_identity=ZoomIdentity.INTERMEDIATE,
            screen_to_atlas=None,
            confidence=0.92,
            frame_sha256=frame_digest(first),
        )
        localizer = SimpleNamespace(
            localize=lambda frame: replace(
                intermediate,
                frame_sha256=frame_digest(frame),
            ),
            canonical_reference=first,
        )
        driver = BlueStacksLocalizeFirstHomeDriver(
            world,
            Path("atlas.json"),
            _ready(),
            target.semantic_id,
            localizer=localizer,
            maximum_zoom_inputs=1,
        )
        planned = driver.observe(first)
        self.assertEqual(planned.disposition, HomeDriverDisposition.RECOVER_ZOOM)
        self.assertEqual(planned.recovery_input_ordinal, 1)
        driver.record_zoom_input_dispatched(planned.source_frame_sha256)
        exhausted = driver.observe(second)
        self.assertEqual(exhausted.disposition, HomeDriverDisposition.BLOCKED)
        self.assertEqual(exhausted.reason, "maximum_zoom_recovery_inputs")

    def test_zoom_plan_uses_semantic_digest_not_png_transport_digest(self) -> None:
        target = _building()
        world = _atlas(target)
        frame = np.zeros((1280, 800, 3), np.uint8)
        localization = replace(
            _localization(),
            recognized=False,
            zoom_identity=ZoomIdentity.ZOOMED_IN,
            screen_to_atlas=None,
            confidence=0.92,
            frame_sha256=frame_digest(frame),
        )
        localizer = SimpleNamespace(localize=lambda _frame: localization, canonical_reference=frame)
        driver = BlueStacksLocalizeFirstHomeDriver(
            world, Path("atlas.json"), _ready(), target.semantic_id, localizer=localizer, maximum_zoom_inputs=1
        )
        planned = driver.observe(frame)
        self.assertEqual(planned.disposition, HomeDriverDisposition.RECOVER_ZOOM)
        # Runtime PNG-byte hashes differ from semantic pixel digests; planner identity remains
        # the semantic frame digest produced by the Home localizer.
        with self.assertRaises(ValueError):
            driver.record_zoom_input_dispatched("png-byte-hash")
        record_home_zoom_recovery_input(driver, planned)

    def test_localize_first_driver_accepts_independently_corroborated_zoomed_in_home(self) -> None:
        target = _building()
        world = _atlas(target)
        frame = np.zeros((1280, 800, 3), np.uint8)
        localization = replace(
            _localization(),
            recognized=False,
            zoom_identity=ZoomIdentity.ZOOMED_IN,
            screen_to_atlas=None,
            confidence=0.73,
            frame_sha256=frame_digest(frame),
        )
        localizer = SimpleNamespace(
            localize=lambda _frame: localization,
            canonical_reference=frame,
        )
        with patch(
            "scripts.home_atlas_bluestacks.classify_zoom",
            return_value=SimpleNamespace(
                identity=ZoomIdentity.ZOOMED_IN,
                confidence=0.71,
            ),
        ):
            step = BlueStacksLocalizeFirstHomeDriver(
                world,
                Path("atlas.json"),
                _ready(),
                target.semantic_id,
                localizer=localizer,
            ).observe(frame)
        self.assertEqual(step.disposition, HomeDriverDisposition.RECOVER_ZOOM)

    def test_localize_first_driver_rejects_uncorroborated_low_confidence_zoom(self) -> None:
        target = _building()
        world = _atlas(target)
        frame = np.zeros((1280, 800, 3), np.uint8)
        localization = replace(
            _localization(),
            recognized=False,
            zoom_identity=ZoomIdentity.ZOOMED_IN,
            screen_to_atlas=None,
            confidence=0.73,
            frame_sha256=frame_digest(frame),
        )
        localizer = SimpleNamespace(
            localize=lambda _frame: localization,
            canonical_reference=frame,
        )
        with patch(
            "scripts.home_atlas_bluestacks.classify_zoom",
            return_value=SimpleNamespace(
                identity=ZoomIdentity.INTERMEDIATE,
                confidence=0.90,
            ),
        ):
            step = BlueStacksLocalizeFirstHomeDriver(
                world,
                Path("atlas.json"),
                _ready(),
                target.semantic_id,
                localizer=localizer,
            ).observe(frame)
        self.assertEqual(step.disposition, HomeDriverDisposition.BLOCKED)
        self.assertEqual(step.reason, "home_localization_ambiguous:zoomed_in")

    def test_localize_first_driver_accepts_low_overlap_zoom_with_strong_geometry(self) -> None:
        target = _building()
        world = _atlas(target)
        frame = np.zeros((1280, 800, 3), np.uint8)
        localization = replace(
            _localization(),
            recognized=False,
            zoom_identity=ZoomIdentity.UNKNOWN,
            screen_to_atlas=None,
            confidence=0.0,
            frame_sha256=frame_digest(frame),
        )
        localizer = SimpleNamespace(
            localize=lambda _frame: localization,
            canonical_reference=frame,
        )
        with patch(
            "scripts.home_atlas_bluestacks.classify_zoom",
            return_value=SimpleNamespace(
                identity=ZoomIdentity.ZOOMED_IN,
                confidence=0.01,
                scale=0.44,
                residual_px=0.31,
                supporting_landmarks=tuple(f"landmark-{index}" for index in range(12)),
            ),
        ):
            step = BlueStacksLocalizeFirstHomeDriver(
                world,
                Path("atlas.json"),
                _ready(),
                target.semantic_id,
                localizer=localizer,
            ).observe(frame)
        self.assertEqual(step.disposition, HomeDriverDisposition.RECOVER_ZOOM)

    def test_localize_first_driver_blocks_repeated_or_unknown_recovery_frames(self) -> None:
        target = _building()
        world = _atlas(target)
        frame = np.zeros((1280, 800, 3), np.uint8)
        intermediate = replace(
            _localization(),
            recognized=False,
            zoom_identity=ZoomIdentity.INTERMEDIATE,
            screen_to_atlas=None,
            confidence=0.92,
            frame_sha256=frame_digest(frame),
        )
        localizer = SimpleNamespace(
            localize=lambda _frame: intermediate,
            canonical_reference=frame,
        )
        driver = BlueStacksLocalizeFirstHomeDriver(
            world,
            Path("atlas.json"),
            _ready(),
            target.semantic_id,
            localizer=localizer,
        )
        self.assertEqual(driver.observe(frame).disposition, HomeDriverDisposition.RECOVER_ZOOM)
        repeated = driver.observe(frame)
        self.assertEqual(repeated.disposition, HomeDriverDisposition.BLOCKED)
        self.assertEqual(repeated.reason, "repeated_zoom_recovery_frame")
        unknown_localizer = SimpleNamespace(
            localize=lambda _frame: replace(
                intermediate,
                zoom_identity=ZoomIdentity.UNKNOWN,
                confidence=0.0,
            ),
            canonical_reference=frame,
        )
        unknown = BlueStacksLocalizeFirstHomeDriver(
            world,
            Path("atlas.json"),
            _ready(),
            target.semantic_id,
            localizer=unknown_localizer,
        ).observe(frame)
        self.assertEqual(unknown.disposition, HomeDriverDisposition.BLOCKED)
        self.assertIn("home_localization_ambiguous", unknown.reason)

    def test_complete_offline_home_atlas_navigation(self) -> None:
        target = _building()
        world = _atlas(target)
        with tempfile.TemporaryDirectory() as directory:
            runtime = _FakeRuntime(Path(directory))
            sample = runtime.capture("seed")
            digest = frame_digest(sample.frame)
            loc = replace(_localization(digest), frame_sha256=digest)
            binding = BuildingBinding(
                target.semantic_id,
                (320, 420, 420, 520),
                digest,
                0.95,
                ("current-frame OCR: Bank",),
            )
            args = _args(directory, building_id=target.semantic_id)
            fake_localizer = SimpleNamespace(
                localize=lambda frame: replace(loc, frame_sha256=frame_digest(frame))
            )
            with patch("scripts.home_atlas_bluestacks.load_home_atlas", return_value=world), patch(
                "scripts.home_atlas_bluestacks.BlueStacksHomeLocalizer", return_value=fake_localizer
            ), patch("scripts.home_atlas_bluestacks.connect_runtime", return_value=runtime), patch(
                "scripts.home_atlas_bluestacks.bind_visible_building",
                side_effect=lambda frame, localization_arg, building_arg: replace(
                    binding, frame_sha256=localization_arg.frame_sha256
                ),
            ):
                code = command_navigate_building(args)
            self.assertEqual(code, 0)
            self.assertEqual(runtime.swipes, [])
            payload = json.loads((runtime.session / "navigate-building-result.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "completed")
            self.assertIn("navigation_observability", payload)
            self.assertEqual(payload["production_registration"], "NOT_REGISTERED")
            self.assertIs(payload["scheduler_eligibility"], False)
            # Finding 2: terminal completed emit carries full action-ledger parity.
            for field in (
                "requested",
                "authorized",
                "dispatched",
                "transport_observed",
                "verified",
                "completed",
                "failed",
                "unresolved",
            ):
                self.assertIn(field, payload, msg=f"missing ledger field {field}")
                self.assertIn(field, payload["action_ledger"])
            self.assertIs(payload["completed"], True)
            self.assertIs(payload["verified"], True)
            self.assertIs(payload["failed"], False)
            # Zero-pan completion dispatched no transport.
            self.assertIs(payload["transport_observed"], False)

    def test_immutable_perception_consumption(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = _FakeRuntime(Path(directory))
            captured = runtime.capture("frame")
            identity = identity_from_captured(
                captured, session_id=str(runtime.session), ordinal=1, label="frame"
            )
            loc = replace(_localization(frame_digest(captured.frame)), frame_sha256=frame_digest(captured.frame))
            binding = BuildingBinding(
                "home.building.bank",
                (320, 420, 420, 520),
                loc.frame_sha256,
                0.95,
                ("evidence",),
            )
            bundle = build_navigate_perception_bundle(identity, loc, binding)
            first = bundle.checked_navigation_inputs()
            second = bundle.checked_navigation_inputs()
            self.assertEqual(first[0].frame_sha256, second[0].frame_sha256)
            self.assertIs(bundle.frame, identity)

    def test_one_authoritative_session_and_resumed_session(self) -> None:
        auth = AuthorizationScope(
            task_id="RUNTIME-RESUMABLE-NAVIGATION-SESSIONS",
            owner_operator="home-atlas-navigate-building",
            action_class="navigation_only",
            platform=BLUESTACKS_PLATFORM,
            profile=BLUESTACKS_PROFILE_ID,
            environment="local_bluestacks",
            target_building_id="home.building.bank",
        )
        session = create_session(auth, runtime_capture_session_id="resume-runtime", maximum_pans=4)
        first_id = session.navigation_session_id
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "navigate-session.json"
            save_session(session, path)
            loaded = load_session(path)
        self.assertEqual(loaded.navigation_session_id, first_id)
        self.assertEqual(loaded.authorization.target_building_id, "home.building.bank")

    def test_bounded_correction_no_progress_wrong_direction_repeated_viewport(self) -> None:
        from tasks.home_atlas_planner import DirectPanNavigator, measure_pan_progress, plan_direct_pan
        from scripts.home_atlas_bluestacks import bluestacks_direct_pan_contract

        safe, calibration = bluestacks_direct_pan_contract()
        world = _atlas(_far_building())
        first = plan_direct_pan(world, _localization(), "home.building.bank", safe, calibration)
        self.assertEqual(first.disposition.value, "pan")
        self.assertEqual(
            measure_pan_progress(_localization(), _localization(digest="c" * 64), first, calibration).reason,
            "no_measured_progress",
        )
        self.assertEqual(
            measure_pan_progress(
                _localization(),
                _localization(digest="d" * 64, x=-100.0, y=-40.0),
                first,
                calibration,
            ).reason,
            "movement_wrong_direction",
        )
        controller = DirectPanNavigator(world, "home.building.bank", safe, calibration, maximum_pans=4)
        self.assertEqual(controller.plan(_localization()).disposition.value, "pan")
        self.assertEqual(controller.plan(_localization(digest="e" * 64)).reason, "repeated_viewport")

    def test_camera_or_map_clamp(self) -> None:
        from tasks.home_atlas_planner import plan_building_viewport
        from scripts.home_atlas_bluestacks import bluestacks_direct_pan_contract

        # BlueStacks route uses recovery-aware planning_policy; edge-unreachable
        # targets fail closed as no_recoverable_actionable_viewport (not legacy clamp).
        safe, _ = bluestacks_direct_pan_contract()
        target = _building(polygon=((10, 500), (110, 500), (110, 620), (10, 620)))
        plan = plan_building_viewport(
            _atlas(target),
            _localization(x=400.0, y=0.0),
            target.semantic_id,
            safe,
        )
        self.assertEqual(plan.disposition.value, "rejected")
        self.assertEqual(plan.reason, "no_recoverable_actionable_viewport")
        rejection_reasons = tuple(item.reason for item in (plan.best_rejected_by_reason or ()))
        count_reasons = tuple(reason for reason, _count in (plan.rejection_counts or ()))
        self.assertTrue(
            any("clamp" in reason or "edge" in reason or "map" in reason for reason in rejection_reasons + count_reasons)
            or bool(plan.rejection_counts),
            msg="edge/clamp rejection evidence must be retained",
        )

    def test_stale_frame_and_cross_capture_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = _FakeRuntime(Path(directory))
            captured = runtime.capture("frame")
            identity = identity_from_captured(
                captured, session_id=str(runtime.session), ordinal=1, label="frame"
            )
            foreign = replace(_localization("b" * 64), frame_sha256="b" * 64)
            with self.assertRaises(PerceptionBundleError) as raised:
                build_navigate_perception_bundle(identity, foreign, None).checked_navigation_inputs()
            # Cross-capture localization digests fail closed at semantic join.
            self.assertEqual(raised.exception.reason_code, "SEMANTIC_DIGEST_MISMATCH")

    def test_cross_session_state(self) -> None:
        a = create_bluestacks_session_calibration("session-a")
        b = create_bluestacks_session_calibration("session-b")
        self.assertNotEqual(a.navigation_session_id, b.navigation_session_id)
        self.assertEqual(a.original.camera_px_per_drag_x, b.original.camera_px_per_drag_x)

    def test_malformed_recapture_ambiguous_localization_missing_actionable_target(self) -> None:
        world = _atlas(_far_building())
        with tempfile.TemporaryDirectory() as directory:
            runtime = _FakeRuntime(Path(directory))
            sample = runtime.capture("seed")
            loc = replace(_localization(frame_digest(sample.frame)), frame_sha256=frame_digest(sample.frame))
            args = _args(directory, building_id="home.building.bank")
            fake_localizer = SimpleNamespace(
                localize=lambda frame: replace(loc, frame_sha256=frame_digest(frame), recognized=False)
            )
            with patch("scripts.home_atlas_bluestacks.load_home_atlas", return_value=world), patch(
                "scripts.home_atlas_bluestacks.BlueStacksHomeLocalizer", return_value=fake_localizer
            ), patch("scripts.home_atlas_bluestacks.connect_runtime", return_value=runtime):
                code = command_navigate_building(args)
            self.assertEqual(code, 3)
            payload = json.loads((runtime.session / "navigate-building-result.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["reason"], "source_localization_failed")

        with tempfile.TemporaryDirectory() as directory:
            runtime = _FakeRuntime(Path(directory))
            sample = runtime.capture("seed")
            loc = replace(_localization(frame_digest(sample.frame)), frame_sha256=frame_digest(sample.frame))
            args = _args(directory, building_id="home.building.bank", execute=False)
            fake_localizer = SimpleNamespace(
                localize=lambda frame: replace(loc, frame_sha256=frame_digest(frame))
            )
            with patch("scripts.home_atlas_bluestacks.load_home_atlas", return_value=world), patch(
                "scripts.home_atlas_bluestacks.BlueStacksHomeLocalizer", return_value=fake_localizer
            ), patch("scripts.home_atlas_bluestacks.connect_runtime", return_value=runtime), patch(
                "scripts.home_atlas_bluestacks.bind_visible_building", return_value=None
            ):
                code = command_navigate_building(args)
            self.assertEqual(code, 0)
            payload = json.loads((runtime.session / "navigate-building-result.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "dry_run")
            self.assertEqual(runtime.swipes, [])

    def test_capability_issuance_and_consumption_denials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = _FakeRuntime(Path(directory))
            captured = runtime.capture("before")
            identity = identity_from_captured(
                captured, session_id=str(runtime.session), ordinal=1, label="before"
            )
            with _open_safety_store(Path(directory)) as store:
                policy = CentralPolicy(supervised_tasks=frozenset({"OTHER-TASK"}))
                issued, execution, _obs, _telemetry = dispatch_verified_navigate_pan(
                    runtime=runtime,
                    immediate_before=captured,
                    identity=identity,
                    drag_start=(450, 500),
                    drag_end=(300, 450),
                    action_id="deny-issue-1",
                    action_key="deny-issue-key-1",
                    task_id="RUNTIME-RESUMABLE-NAVIGATION-SESSIONS",
                    navigation_session_id="nav-session-deny-1",
                    lease_owner="owner",
                    policy=policy,
                    store=store,
                    monotonic_clock=_MonoClock(runtime),
                    wall_clock=lambda: _TEST_WALL,
                )
                self.assertFalse(issued.authorized)
                self.assertIsNone(execution)
                self.assertEqual(runtime.swipes, [])

            with _open_safety_store(Path(directory), name="safety2.sqlite3") as store2:
                policy2 = _policy_for("RUNTIME-RESUMABLE-NAVIGATION-SESSIONS")
                issued2, execution2, obs, _telemetry2 = dispatch_verified_navigate_pan(
                    runtime=runtime,
                    immediate_before=captured,
                    identity=identity,
                    drag_start=(450, 500),
                    drag_end=(300, 450),
                    action_id="deny-consume-1",
                    action_key="deny-consume-key-1",
                    task_id="RUNTIME-RESUMABLE-NAVIGATION-SESSIONS",
                    navigation_session_id="nav-session-deny-2",
                    lease_owner="owner",
                    policy=policy2,
                    store=store2,
                    monotonic_clock=_MonoClock(runtime),
                    wall_clock=lambda: _TEST_WALL,
                )
                self.assertTrue(issued2.authorized)
                assert issued2.capability is not None
                # Force consumption denial by executing with drifted ROI after issuance.
                drifted = replace(obs, target_roi=(250, 250, 260, 260))
                from safe_action_core import SafeActionExecutor, TransportResult

                def transport(_intent):
                    runtime.swipes.append({"bypass": True})
                    return TransportResult(True, "SHOULD_NOT_RUN")

                executor = SafeActionExecutor(
                    store2,
                    policy2,
                    "owner",
                    lambda: obs.capture_completed_monotonic + 0.2,
                    transport,
                    lambda: drifted,
                    lambda: (),
                    lambda *_: True,
                    wall_clock=lambda: _TEST_WALL,
                    max_pre_dispatch_attempts=1,
                )
                prior = replace(
                    obs,
                    frame_sha256=("a" if obs.frame_sha256[:1] != "a" else "b") * 64,
                    capture_completed_monotonic=obs.capture_completed_monotonic - 0.05,
                )
                request = build_navigate_pan_policy_request(
                    observation=prior,
                    action_id="deny-consume-1",
                    action_key="deny-consume-key-1",
                    task_id="RUNTIME-RESUMABLE-NAVIGATION-SESSIONS",
                    navigation_session_id="nav-session-deny-2",
                    lease_owner="owner",
                    monotonic_now=obs.capture_completed_monotonic + 0.2,
                )
                # New capability for drifted path: issue on original, consume against drifted ROI.
                issued3 = policy2.issue_capability(
                    build_navigate_pan_policy_request(
                        observation=obs,
                        action_id="deny-consume-2",
                        action_key="deny-consume-key-2",
                        task_id="RUNTIME-RESUMABLE-NAVIGATION-SESSIONS",
                        navigation_session_id="nav-session-deny-2",
                        lease_owner="owner",
                        monotonic_now=obs.capture_completed_monotonic + 0.2,
                    )
                )
                self.assertTrue(issued3.authorized)
                assert issued3.capability is not None
                result = executor.execute(
                    replace(request, action_id="deny-consume-2", action_key="deny-consume-key-2"),
                    issued3.capability,
                )
                self.assertNotEqual(result.status, ActionStatus.CONFIRMED)
                self.assertFalse(any(item.get("bypass") for item in runtime.swipes))

    def test_policy_drift_before_final_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = _FakeRuntime(Path(directory))
            captured = runtime.capture("before")
            identity = identity_from_captured(
                captured, session_id=str(runtime.session), ordinal=1, label="before"
            )
            with _open_safety_store(Path(directory)) as store:
                policy = _policy_for("RUNTIME-RESUMABLE-NAVIGATION-SESSIONS")
                obs = build_navigate_pan_observation(
                    identity=identity, drag_start=(450, 500), drag_end=(300, 450)
                )
                issued = policy.issue_capability(
                    build_navigate_pan_policy_request(
                        observation=obs,
                        action_id="drift-1",
                        action_key="drift-key-1",
                        task_id="RUNTIME-RESUMABLE-NAVIGATION-SESSIONS",
                        navigation_session_id="nav-drift",
                        lease_owner="owner",
                        monotonic_now=obs.capture_completed_monotonic + 0.2,
                    )
                )
                self.assertTrue(issued.authorized)
                assert issued.capability is not None
                from safe_action_core import SafeActionExecutor, TransportResult

                calls = []

                def transport(_intent):
                    calls.append(1)
                    return TransportResult(True, "NO")

                moved = replace(obs, target_roi=(400, 400, 410, 410))
                executor = SafeActionExecutor(
                    store,
                    policy,
                    "owner",
                    lambda: obs.capture_completed_monotonic + 0.2,
                    transport,
                    lambda: moved,
                    lambda: (),
                    lambda *_: True,
                    wall_clock=lambda: _TEST_WALL,
                    max_pre_dispatch_attempts=1,
                )
                prior = replace(
                    obs,
                    frame_sha256=("a" if obs.frame_sha256[:1] != "a" else "b") * 64,
                    capture_completed_monotonic=obs.capture_completed_monotonic - 0.05,
                )
                result = executor.execute(
                    build_navigate_pan_policy_request(
                        observation=prior,
                        action_id="drift-1",
                        action_key="drift-key-1",
                        task_id="RUNTIME-RESUMABLE-NAVIGATION-SESSIONS",
                        navigation_session_id="nav-drift",
                        lease_owner="owner",
                        monotonic_now=obs.capture_completed_monotonic + 0.2,
                    ),
                    issued.capability,
                )
                self.assertEqual(calls, [])
                self.assertNotEqual(result.status, ActionStatus.CONFIRMED)

    def test_dry_run_zero_transport(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = _FakeRuntime(Path(directory))
            captured = runtime.capture("before")
            identity = identity_from_captured(
                captured, session_id=str(runtime.session), ordinal=1, label="before"
            )
            with _open_safety_store(Path(directory)) as store:
                issued, execution, _obs, _telemetry = dispatch_verified_navigate_pan(
                    runtime=runtime,
                    immediate_before=captured,
                    identity=identity,
                    drag_start=(450, 500),
                    drag_end=(300, 450),
                    action_id="dry-1",
                    action_key="dry-key-1",
                    task_id="RUNTIME-RESUMABLE-NAVIGATION-SESSIONS",
                    navigation_session_id="nav-dry",
                    lease_owner="owner",
                    policy=_policy_for("RUNTIME-RESUMABLE-NAVIGATION-SESSIONS"),
                    store=store,
                    monotonic_clock=_MonoClock(runtime),
                    dry_run=True,
                    wall_clock=lambda: _TEST_WALL,
                )
                self.assertTrue(issued.authorized)
                assert execution is not None
                self.assertEqual(execution.transport_calls, 0)
                self.assertEqual(runtime.swipes, [])

    def test_duplicate_action_suppression(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = _FakeRuntime(Path(directory))
            captured = runtime.capture("before")
            identity = identity_from_captured(
                captured, session_id=str(runtime.session), ordinal=1, label="before"
            )
            with _open_safety_store(Path(directory)) as store:
                policy = _policy_for("RUNTIME-RESUMABLE-NAVIGATION-SESSIONS")
                kwargs = dict(
                    runtime=runtime,
                    immediate_before=captured,
                    identity=identity,
                    drag_start=(450, 500),
                    drag_end=(300, 450),
                    action_id="dup-1",
                    action_key="dup-key-shared",
                    task_id="RUNTIME-RESUMABLE-NAVIGATION-SESSIONS",
                    navigation_session_id="nav-dup",
                    lease_owner="owner",
                    policy=policy,
                    store=store,
                    monotonic_clock=_MonoClock(runtime),
                    wall_clock=lambda: _TEST_WALL,
                )
                first = dispatch_verified_navigate_pan(**kwargs)
                self.assertTrue(first[0].authorized)
                assert first[1] is not None
                self.assertEqual(first[1].status, ActionStatus.CONFIRMED)
                second = dispatch_verified_navigate_pan(
                    **{**kwargs, "action_id": "dup-2"}
                )
                self.assertTrue(second[0].authorized)
                assert second[1] is not None
                self.assertEqual(second[1].status, ActionStatus.CANCELLED)
                self.assertEqual(len(runtime.swipes), 1)

    def test_transport_observed_without_semantic_success(self) -> None:
        world = _atlas(_far_building())
        with tempfile.TemporaryDirectory() as directory:
            runtime = _FakeRuntime(Path(directory))
            sample = runtime.capture("seed")
            loc = replace(_localization(frame_digest(sample.frame)), frame_sha256=frame_digest(sample.frame))
            args = _args(directory, building_id="home.building.bank")
            fake_localizer = SimpleNamespace(
                localize=lambda frame: replace(loc, frame_sha256=frame_digest(frame))
            )
            with patch("scripts.home_atlas_bluestacks.load_home_atlas", return_value=world), patch(
                "scripts.home_atlas_bluestacks.BlueStacksHomeLocalizer", return_value=fake_localizer
            ), patch("scripts.home_atlas_bluestacks.connect_runtime", return_value=runtime), patch(
                "scripts.home_atlas_bluestacks.bind_visible_building", return_value=None
            ), patch(
                "scripts.home_atlas_bluestacks.time.monotonic",
                side_effect=lambda: float(runtime.ordinal) + 0.2,
            ):
                code = command_navigate_building(args)
            self.assertEqual(code, 3)
            self.assertEqual(len(runtime.swipes), 1)
            payload = json.loads((runtime.session / "navigate-building-result.json").read_text(encoding="utf-8"))
            self.assertTrue(payload.get("transport_observed"))
            self.assertFalse(payload.get("semantic_verified"))
            self.assertEqual(payload["reason"], "no_measured_progress")
            # Finding 2: distinct requested/authorized/dispatched/transport/verified/
            # completed states are all present; transport observed but not verified.
            ledger = payload["action_ledger"]
            self.assertIs(ledger["requested"], True)
            self.assertIs(ledger["authorized"], True)
            self.assertIs(ledger["dispatched"], True)
            self.assertIs(ledger["transport_observed"], True)
            self.assertIs(ledger["verified"], False)
            self.assertIs(ledger["completed"], False)
            self.assertIs(ledger["failed"], True)
            self.assertIs(ledger["unresolved"], False)
            self.assertEqual(ledger["executor_status"], "confirmed")
            # The single pan record mirrors the same ledger fields.
            pan_record = payload["records"][-1]
            self.assertEqual(pan_record["action_ledger"], ledger)
            self.assertTrue(pan_record["transport_observed"])
            self.assertFalse(pan_record["semantic_verified"])

    def test_semantic_verification_failure_and_observability(self) -> None:
        world = _atlas(_far_building())
        with tempfile.TemporaryDirectory() as directory:
            runtime = _FakeRuntime(Path(directory))
            sample = runtime.capture("seed")
            loc = replace(_localization(frame_digest(sample.frame)), frame_sha256=frame_digest(sample.frame))
            args = _args(directory, building_id="home.building.bank")
            fake_localizer = SimpleNamespace(
                localize=lambda frame: replace(loc, frame_sha256=frame_digest(frame))
            )
            with patch("scripts.home_atlas_bluestacks.load_home_atlas", return_value=world), patch(
                "scripts.home_atlas_bluestacks.BlueStacksHomeLocalizer", return_value=fake_localizer
            ), patch("scripts.home_atlas_bluestacks.connect_runtime", return_value=runtime), patch(
                "scripts.home_atlas_bluestacks.bind_visible_building", return_value=None
            ), patch(
                "scripts.home_atlas_bluestacks.time.monotonic",
                side_effect=lambda: float(runtime.ordinal) + 0.2,
            ):
                command_navigate_building(args)
            payload = json.loads((runtime.session / "navigate-building-result.json").read_text(encoding="utf-8"))
            obs = payload["navigation_observability"]
            self.assertEqual(obs["schema_name"], "navigation_session_observability")
            self.assertEqual(
                obs["non_dispatch_authority"]["reason_code"],
                "NON_DISPATCH_AUTHORITY_UNAVAILABLE",
            )
            self.assertEqual(payload["confirmed_not_dispatched_authority"], CONFIRMED_NOT_DISPATCHED_STATUS)
            self.assertEqual(payload["session_calibration"]["schema_name"], "navigation_session_calibration")
            self.assertIs(payload["session_calibration"]["authorize_dispatch"], False)
            self.assertIs(payload["session_calibration"]["persistence_authorized"], False)

    def test_calibration_observability(self) -> None:
        state = create_bluestacks_session_calibration("calib-obs-session")
        auth = AuthorizationScope(
            task_id="RUNTIME-RESUMABLE-NAVIGATION-SESSIONS",
            owner_operator="home-atlas-navigate-building",
            action_class="navigation_only",
            platform=BLUESTACKS_PLATFORM,
            profile=BLUESTACKS_PROFILE_ID,
            environment="local_bluestacks",
            target_building_id="home.building.bank",
        )
        session = create_session(
            auth,
            runtime_capture_session_id="calib-runtime",
            maximum_pans=4,
            navigation_session_id="calib-obs-session",
        )
        result = attach_navigate_terminal_reports(
            {"status": "blocked", "reason": "probe"},
            session,
            session_calibration=state,
        )
        self.assertIn("navigation_observability_json", result)
        json.loads(result["navigation_observability_json"])
        self.assertEqual(result["session_calibration"]["navigation_session_id"], "calib-obs-session")

    def test_direct_transport_bypass_rejection(self) -> None:
        with self.assertRaises(RuntimeError) as raised:
            reject_direct_navigate_building_transport()
        self.assertEqual(str(raised.exception), "DIRECT_TRANSPORT_BYPASS_REJECTED")
        module = importlib.import_module("scripts.home_atlas_bluestacks")
        route_source = inspect.getsource(command_navigate_building) + inspect.getsource(
            module._command_navigate_building_body
        )
        self.assertNotIn("runtime.swipe(", route_source)
        self.assertIn("dispatch_verified_navigate_pan(", route_source)

    def test_registration_scheduler_and_confirmed_not_dispatched_unchanged(self) -> None:
        self.assertEqual(CONFIRMED_NOT_DISPATCHED_STATUS, "NON_DISPATCH_AUTHORITY_UNAVAILABLE")
        with self.assertRaises(Exception) as raised:
            TrustedTransportNonDispatchAuthority(authority_id="verified-route-probe")
        self.assertEqual(raised.exception.reason_code, "NON_DISPATCH_AUTHORITY_UNAVAILABLE")
        module = importlib.import_module("scripts.home_atlas_bluestacks")
        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn('production_registration"] = "NOT_REGISTERED"', source)
        self.assertIn('scheduler_eligibility"] = False', source)

    def test_gesture_roi_and_authorized_dispatch_smoke(self) -> None:
        roi = gesture_geometry_roi((450, 500), (300, 450))
        self.assertEqual(roi, (300, 450, 450, 500))
        with tempfile.TemporaryDirectory() as directory:
            runtime = _FakeRuntime(Path(directory))
            captured = runtime.capture("before")
            identity = identity_from_captured(
                captured, session_id=str(runtime.session), ordinal=1, label="before"
            )
            with _open_safety_store(Path(directory)) as store:
                issued, execution, obs, telemetry = dispatch_verified_navigate_pan(
                    runtime=runtime,
                    immediate_before=captured,
                    identity=identity,
                    drag_start=(450, 500),
                    drag_end=(300, 450),
                    action_id="ok-1",
                    action_key="ok-key-1",
                    task_id="RUNTIME-RESUMABLE-NAVIGATION-SESSIONS",
                    navigation_session_id="nav-ok",
                    lease_owner="owner",
                    policy=_policy_for("RUNTIME-RESUMABLE-NAVIGATION-SESSIONS"),
                    store=store,
                    monotonic_clock=_MonoClock(runtime),
                    wall_clock=lambda: _TEST_WALL,
                )
                self.assertTrue(issued.authorized)
                assert execution is not None
                self.assertEqual(execution.status, ActionStatus.CONFIRMED)
                self.assertEqual(execution.transport_calls, 1)
                self.assertEqual(len(runtime.swipes), 1)
                self.assertEqual(runtime.swipes[0]["target_identity"], NAVIGATE_BUILDING_TARGET_IDENTITY)
                self.assertEqual(obs.target_roi, roi)
                self.assertEqual(obs.consequence, "navigate_zero_cost")
                # The capability is bound to the fresh pre_dispatch capture, not
                # the caller's planning frame; transport swiped that fresh frame.
                fresh_frames = runtime.captures_labeled("navigate-pan-pre-dispatch")
                self.assertEqual(len(fresh_frames), 1)
                self.assertEqual(obs.frame_sha256, frame_digest(fresh_frames[0].frame))
                self.assertNotEqual(obs.frame_sha256, identity.semantic_sha256)
                self.assertTrue(telemetry["transport_observed"])
                self.assertEqual(
                    telemetry["pre_dispatch_frame_sha256"], obs.frame_sha256
                )

    def test_recapture_rebuilds_distinct_semantic_observation(self) -> None:
        # Finding 1 negative control: the executor recapture must rebuild a NEW
        # Observation from the fresh pre_dispatch capture, never return the
        # issuance object by identity, while matching digest+monotonic exactly.
        module = importlib.import_module("scripts.home_atlas_bluestacks")
        real_executor = module.SafeActionExecutor
        recorded: dict[str, object] = {}

        def _spy(*args, **kwargs):
            instance = real_executor(*args, **kwargs)
            recorded["recapture"] = instance.recapture
            return instance

        with tempfile.TemporaryDirectory() as directory:
            runtime = _FakeRuntime(Path(directory))
            captured = runtime.capture("before")
            identity = identity_from_captured(
                captured, session_id=str(runtime.session), ordinal=1, label="before"
            )
            with _open_safety_store(Path(directory)) as store:
                with patch("scripts.home_atlas_bluestacks.SafeActionExecutor", _spy):
                    issued, execution, obs, _telemetry = dispatch_verified_navigate_pan(
                        runtime=runtime,
                        immediate_before=captured,
                        identity=identity,
                        drag_start=(450, 500),
                        drag_end=(300, 450),
                        action_id="rebind-1",
                        action_key="rebind-key-1",
                        task_id="RUNTIME-RESUMABLE-NAVIGATION-SESSIONS",
                        navigation_session_id="nav-rebind",
                        lease_owner="owner",
                        policy=_policy_for("RUNTIME-RESUMABLE-NAVIGATION-SESSIONS"),
                        store=store,
                        monotonic_clock=_MonoClock(runtime),
                        wall_clock=lambda: _TEST_WALL,
                    )
                self.assertTrue(issued.authorized)
                assert execution is not None
                self.assertEqual(execution.status, ActionStatus.CONFIRMED)
                recapture = recorded["recapture"]
                first = recapture()
                second = recapture()
                # Distinct object each call and never the issuance observation.
                self.assertIsNot(first, second)
                self.assertIsNot(first, obs)
                self.assertIsNot(second, obs)
                # ...yet digest + monotonic match so consume can succeed unchanged.
                self.assertEqual(first.frame_sha256, obs.frame_sha256)
                self.assertEqual(
                    first.capture_completed_monotonic, obs.capture_completed_monotonic
                )
                self.assertEqual(second.frame_sha256, obs.frame_sha256)

    def test_fresh_pre_dispatch_capture_distinct_from_planning_frame(self) -> None:
        # Finding 1: a genuine fresh pre_dispatch capture is acquired; the
        # planning immediate_before is never treated as the issuance frame.
        with tempfile.TemporaryDirectory() as directory:
            runtime = _FakeRuntime(Path(directory))
            captured = runtime.capture("before")
            identity = identity_from_captured(
                captured, session_id=str(runtime.session), ordinal=1, label="before"
            )
            with _open_safety_store(Path(directory)) as store:
                issued, execution, obs, telemetry = dispatch_verified_navigate_pan(
                    runtime=runtime,
                    immediate_before=captured,
                    identity=identity,
                    drag_start=(450, 500),
                    drag_end=(300, 450),
                    action_id="fresh-1",
                    action_key="fresh-key-1",
                    task_id="RUNTIME-RESUMABLE-NAVIGATION-SESSIONS",
                    navigation_session_id="nav-fresh",
                    lease_owner="owner",
                    policy=_policy_for("RUNTIME-RESUMABLE-NAVIGATION-SESSIONS"),
                    store=store,
                    monotonic_clock=_MonoClock(runtime),
                    wall_clock=lambda: _TEST_WALL,
                )
                self.assertTrue(issued.authorized)
                assert execution is not None
                fresh_frames = runtime.captures_labeled("navigate-pan-pre-dispatch")
                self.assertEqual(len(fresh_frames), 1)
                fresh = fresh_frames[0]
                # Capability is bound to the fresh capture, not the planning frame.
                self.assertEqual(obs.frame_sha256, frame_digest(fresh.frame))
                self.assertNotEqual(obs.frame_sha256, identity.semantic_sha256)
                self.assertEqual(
                    telemetry["pre_dispatch_frame_sha256"], frame_digest(fresh.frame)
                )
                # Transport swiped the fresh capture the capability is bound to.
                self.assertEqual(len(runtime.swipes), 1)
                self.assertEqual(runtime.swipes[0]["sha256"], fresh.sha256)

    def test_recapture_scene_drift_fails_closed(self) -> None:
        # Finding 1: if the rebuilt pre_dispatch observation drifts to a different
        # capture (cross-capture / scene change), consume fails closed with zero
        # transport. Transport success is never inferred from issuance.
        from safe_action_core import SafeActionExecutor, TransportResult

        with tempfile.TemporaryDirectory() as directory:
            runtime = _FakeRuntime(Path(directory))
            first = runtime.capture("pre-dispatch")
            first_identity = identity_from_captured(
                first, session_id=str(runtime.session), ordinal=1, label="pre-dispatch"
            )
            drifted = runtime.capture("drifted")
            drifted_identity = identity_from_captured(
                drifted, session_id=str(runtime.session), ordinal=2, label="drifted"
            )
            obs = build_navigate_pan_observation(
                identity=first_identity, drag_start=(450, 500), drag_end=(300, 450)
            )
            drifted_obs = build_navigate_pan_observation(
                identity=drifted_identity, drag_start=(450, 500), drag_end=(300, 450)
            )
            self.assertNotEqual(obs.frame_sha256, drifted_obs.frame_sha256)
            with _open_safety_store(Path(directory)) as store:
                policy = _policy_for("RUNTIME-RESUMABLE-NAVIGATION-SESSIONS")
                issued = policy.issue_capability(
                    build_navigate_pan_policy_request(
                        observation=obs,
                        action_id="drift-scene-1",
                        action_key="drift-scene-key-1",
                        task_id="RUNTIME-RESUMABLE-NAVIGATION-SESSIONS",
                        navigation_session_id="nav-drift-scene",
                        lease_owner="owner",
                        monotonic_now=obs.capture_completed_monotonic + 0.2,
                    )
                )
                self.assertTrue(issued.authorized)
                assert issued.capability is not None
                calls: list[int] = []

                def transport(_intent):
                    calls.append(1)
                    return TransportResult(True, "SHOULD_NOT_RUN")

                proposal = replace(
                    obs,
                    capture_completed_monotonic=obs.capture_completed_monotonic - 0.05,
                )
                executor = SafeActionExecutor(
                    store,
                    policy,
                    "owner",
                    lambda: obs.capture_completed_monotonic + 0.2,
                    transport,
                    lambda: drifted_obs,
                    lambda: (),
                    lambda *_: True,
                    wall_clock=lambda: _TEST_WALL,
                    max_pre_dispatch_attempts=1,
                )
                result = executor.execute(
                    build_navigate_pan_policy_request(
                        observation=proposal,
                        action_id="drift-scene-1",
                        action_key="drift-scene-key-1",
                        task_id="RUNTIME-RESUMABLE-NAVIGATION-SESSIONS",
                        navigation_session_id="nav-drift-scene",
                        lease_owner="owner",
                        monotonic_now=obs.capture_completed_monotonic + 0.2,
                    ),
                    issued.capability,
                )
                self.assertEqual(calls, [])
                self.assertNotEqual(result.status, ActionStatus.CONFIRMED)

    def test_regression_module_imports(self) -> None:
        modules = (
            "tasks.navigation_session",
            "tasks.navigation_observability",
            "tasks.navigation_session_calibration",
            "tasks.perception_bundle",
            "safe_action_core",
            "tasks.home_atlas_planner",
        )
        for name in modules:
            importlib.import_module(name)

    def test_campaign_home_atlas_building_seam_exports(self) -> None:
        from scripts.home_atlas_bluestacks import (
            CAMPAIGN_HOME_ATLAS_BUILDING_ID,
            campaign_home_atlas_building_id,
            command_navigate_building,
            dispatch_verified_campaign_home_building_tap,
            dispatch_verified_navigate_pan,
            reject_direct_campaign_home_building_transport,
            require_campaign_home_atlas_building,
            run_verified_campaign_home_atlas_entry,
            run_verified_ultimate_challenge_campaign_door,
        )

        self.assertEqual(campaign_home_atlas_building_id(), "home.building.campaign")
        self.assertEqual(require_campaign_home_atlas_building(), CAMPAIGN_HOME_ATLAS_BUILDING_ID)
        self.assertTrue(callable(command_navigate_building))
        self.assertTrue(callable(dispatch_verified_navigate_pan))
        self.assertTrue(callable(dispatch_verified_campaign_home_building_tap))
        self.assertTrue(callable(run_verified_campaign_home_atlas_entry))
        self.assertTrue(callable(run_verified_ultimate_challenge_campaign_door))
        with self.assertRaises(RuntimeError) as raised:
            reject_direct_campaign_home_building_transport()
        self.assertEqual(str(raised.exception), "DIRECT_TRANSPORT_BYPASS_REJECTED")

    def test_ultimate_challenge_campaign_door_reuses_home_atlas_entry(self) -> None:
        import inspect

        from scripts import home_atlas_bluestacks as home_atlas

        door_src = inspect.getsource(home_atlas.run_verified_ultimate_challenge_campaign_door)
        self.assertIn("run_verified_campaign_home_atlas_entry", door_src)
        self.assertIn("home.building.campaign", door_src)
        self.assertNotIn("parse_supported_campaign_story_destination", door_src)

    def test_campaign_home_entry_rejects_false_opened_without_semantic_bind(self) -> None:
        """Transport success without semantic Campaign open must not report status opened."""

        from scripts.home_atlas_bluestacks import (
            CAMPAIGN_HOME_ATLAS_BUILDING_ID,
            run_verified_campaign_home_atlas_entry,
        )

        campaign = _building(
            semantic_id=CAMPAIGN_HOME_ATLAS_BUILDING_ID,
            polygon=((300, 400), (440, 400), (440, 540), (300, 540)),
        )
        world = _atlas(campaign)
        with tempfile.TemporaryDirectory() as directory:
            runtime = _FakeRuntime(Path(directory))
            sample = runtime.capture("seed")
            digest = frame_digest(sample.frame)
            loc = replace(_localization(digest), frame_sha256=digest)
            binding = BuildingBinding(
                CAMPAIGN_HOME_ATLAS_BUILDING_ID,
                (320, 420, 420, 520),
                digest,
                0.95,
                ("current-frame OCR: Campaign",),
            )
            fake_localizer = SimpleNamespace(
                localize=lambda frame: replace(loc, frame_sha256=frame_digest(frame))
            )

            def _bind(frame, localization_arg, building_arg):
                return replace(binding, frame_sha256=localization_arg.frame_sha256)

            with patch(
                "scripts.home_atlas_bluestacks.require_campaign_home_atlas_building",
                return_value=CAMPAIGN_HOME_ATLAS_BUILDING_ID,
            ), patch(
                "scripts.home_atlas_bluestacks.load_home_atlas",
                return_value=world,
            ), patch(
                "scripts.home_atlas_bluestacks.BlueStacksHomeLocalizer",
                return_value=fake_localizer,
            ), patch(
                "scripts.home_atlas_bluestacks.bind_visible_building",
                side_effect=_bind,
            ), patch(
                "scripts.home_atlas_bluestacks.time.monotonic",
                side_effect=lambda: float(runtime.ordinal) + 0.2,
            ):
                result = run_verified_campaign_home_atlas_entry(
                    runtime,
                    atlas_path=Path(directory) / "atlas.json",
                    maximum_pans=1,
                    execute=True,
                    settle_seconds=0,
                    semantic_opened_check=lambda _frame: False,
                )

            self.assertNotEqual(result["status"], "opened")
            self.assertEqual(result["status"], "blocked_fail_closed")
            self.assertIn("semantic Campaign/TIER_MAP", result["reason"])
            self.assertEqual(len(runtime.taps), 1)
            self.assertEqual(runtime.taps[0]["target_identity"], CAMPAIGN_HOME_ATLAS_BUILDING_ID)
            telemetry = result["tap_telemetry"]
            self.assertTrue(telemetry.get("transport_observed") or telemetry.get("dispatched"))
            self.assertIs(telemetry.get("verified"), False)
            self.assertIs(telemetry.get("completed"), False)

    def test_campaign_home_entry_plans_before_pan_prepare(self) -> None:
        """Campaign entry must advance created -> source_home -> plan_created before prepare."""

        from scripts.home_atlas_bluestacks import (
            CAMPAIGN_HOME_ATLAS_BUILDING_ID,
            run_verified_campaign_home_atlas_entry,
        )
        from tasks.navigation_session import (
            NavigationCheckpoint,
            NavigationSessionError,
            record_pan_prepared,
            record_plan,
            record_source_home_verified,
        )

        campaign = _building(
            semantic_id=CAMPAIGN_HOME_ATLAS_BUILDING_ID,
            polygon=((900, 900), (1040, 900), (1040, 1040), (900, 1040)),
        )
        world = _atlas(campaign)
        lifecycle: list[tuple[str, str]] = []

        def _wrap_source(session, **kwargs):
            lifecycle.append(("before_source_home", session.checkpoint.value))
            record_source_home_verified(session, **kwargs)
            lifecycle.append(("after_source_home", session.checkpoint.value))

        def _wrap_plan(session, **kwargs):
            lifecycle.append(("before_plan", session.checkpoint.value))
            record_plan(session, **kwargs)
            lifecycle.append(("after_plan", session.checkpoint.value))

        def _wrap_prepare(session, **kwargs):
            lifecycle.append(("before_prepare", session.checkpoint.value))
            if session.checkpoint is not NavigationCheckpoint.PLAN_CREATED:
                raise NavigationSessionError("PREPARE_REQUIRES_PLAN", session.checkpoint.value)
            return record_pan_prepared(session, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            runtime = _FakeRuntime(Path(directory))
            sample = runtime.capture("seed")
            digest = frame_digest(sample.frame)
            loc = replace(_localization(digest, x=0.0, y=0.0), frame_sha256=digest)
            fake_localizer = SimpleNamespace(
                localize=lambda frame: replace(loc, frame_sha256=frame_digest(frame))
            )
            with patch(
                "scripts.home_atlas_bluestacks.require_campaign_home_atlas_building",
                return_value=CAMPAIGN_HOME_ATLAS_BUILDING_ID,
            ), patch(
                "scripts.home_atlas_bluestacks.load_home_atlas",
                return_value=world,
            ), patch(
                "scripts.home_atlas_bluestacks.BlueStacksHomeLocalizer",
                return_value=fake_localizer,
            ), patch(
                "scripts.home_atlas_bluestacks.bind_visible_building",
                return_value=None,
            ), patch(
                "scripts.home_atlas_bluestacks.record_source_home_verified",
                side_effect=_wrap_source,
            ), patch(
                "scripts.home_atlas_bluestacks.record_plan",
                side_effect=_wrap_plan,
            ), patch(
                "scripts.home_atlas_bluestacks.record_pan_prepared",
                side_effect=_wrap_prepare,
            ), patch(
                "scripts.home_atlas_bluestacks.time.monotonic",
                side_effect=lambda: float(runtime.ordinal) + 0.2,
            ):
                result = run_verified_campaign_home_atlas_entry(
                    runtime,
                    atlas_path=Path(directory) / "atlas.json",
                    maximum_pans=1,
                    execute=True,
                    settle_seconds=0,
                    semantic_opened_check=lambda _frame: False,
                )

            self.assertEqual(result["status"], "blocked_fail_closed")
            self.assertEqual(len(runtime.swipes), 1)
            self.assertEqual(
                [item[0] for item in lifecycle[:6]],
                [
                    "before_source_home",
                    "after_source_home",
                    "before_plan",
                    "after_plan",
                    "before_prepare",
                ],
            )
            self.assertEqual(lifecycle[0][1], NavigationCheckpoint.CREATED.value)
            self.assertEqual(
                lifecycle[1][1], NavigationCheckpoint.SOURCE_HOME_VERIFIED.value
            )
            self.assertEqual(lifecycle[2][1], NavigationCheckpoint.SOURCE_HOME_VERIFIED.value)
            self.assertEqual(lifecycle[3][1], NavigationCheckpoint.PLAN_CREATED.value)
            self.assertEqual(lifecycle[4][1], NavigationCheckpoint.PLAN_CREATED.value)
            self.assertEqual(result["records"][0]["navigation_checkpoint"], "plan_created")

    def test_campaign_home_entry_fail_closed_without_plan(self) -> None:
        """Skipping record_plan must still fail closed at prepare; no pan dispatch."""

        from scripts.home_atlas_bluestacks import (
            CAMPAIGN_HOME_ATLAS_BUILDING_ID,
            run_verified_campaign_home_atlas_entry,
        )
        from tasks.navigation_session import NavigationSessionError

        campaign = _building(
            semantic_id=CAMPAIGN_HOME_ATLAS_BUILDING_ID,
            polygon=((900, 900), (1040, 900), (1040, 1040), (900, 1040)),
        )
        world = _atlas(campaign)
        with tempfile.TemporaryDirectory() as directory:
            runtime = _FakeRuntime(Path(directory))
            sample = runtime.capture("seed")
            digest = frame_digest(sample.frame)
            loc = replace(_localization(digest), frame_sha256=digest)
            fake_localizer = SimpleNamespace(
                localize=lambda frame: replace(loc, frame_sha256=frame_digest(frame))
            )
            with patch(
                "scripts.home_atlas_bluestacks.require_campaign_home_atlas_building",
                return_value=CAMPAIGN_HOME_ATLAS_BUILDING_ID,
            ), patch(
                "scripts.home_atlas_bluestacks.load_home_atlas",
                return_value=world,
            ), patch(
                "scripts.home_atlas_bluestacks.BlueStacksHomeLocalizer",
                return_value=fake_localizer,
            ), patch(
                "scripts.home_atlas_bluestacks.bind_visible_building",
                return_value=None,
            ), patch(
                "scripts.home_atlas_bluestacks.record_plan",
                lambda *_args, **_kwargs: None,
            ), patch(
                "scripts.home_atlas_bluestacks.time.monotonic",
                side_effect=lambda: float(runtime.ordinal) + 0.2,
            ):
                with self.assertRaises(NavigationSessionError) as raised:
                    run_verified_campaign_home_atlas_entry(
                        runtime,
                        atlas_path=Path(directory) / "atlas.json",
                        maximum_pans=1,
                        execute=True,
                        settle_seconds=0,
                        semantic_opened_check=lambda _frame: False,
                    )
            self.assertEqual(raised.exception.reason_code, "PREPARE_REQUIRES_PLAN")
            self.assertEqual(str(raised.exception), "source_home_verified")
            self.assertEqual(runtime.swipes, [])


if __name__ == "__main__":
    unittest.main()
