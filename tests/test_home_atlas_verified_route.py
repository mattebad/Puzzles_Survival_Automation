"""Offline verified-route integration tests for Home Atlas navigate-building."""

from __future__ import annotations

import importlib
import inspect
import json
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
    CONFIRMED_NOT_DISPATCHED_STATUS,
    NAVIGATE_BUILDING_TARGET_IDENTITY,
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
from tasks.navigation_observability import report_navigation_session
from tasks.navigation_session import (
    AuthorizationScope,
    create_session,
    load_session,
    save_session,
)
from tasks.navigation_session import TrustedTransportNonDispatchAuthority
from tasks.perception_bundle import PerceptionBundleError


PROFILE = PlatformProfile(BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, (800, 1280), "com.global.ztmslg")
_TEST_WALL = 1000.0
_TEST_LEASE_TTL = 100.0


class _MonoClock:
    """Keep offline executor timing relative to FakeRuntime capture ordinals."""

    def __init__(self, captured: CapturedNativeFrame) -> None:
        self.value = float(captured.captured_monotonic) + 0.2

    def __call__(self) -> float:
        return self.value


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
        self.ordinal = 0
        self._origin = (0.0, 0.0)
        self.progress_after_swipe = False

    def capture(self, label: str) -> CapturedNativeFrame:
        self.ordinal += 1
        frame = np.zeros((1280, 800, 3), np.uint8)
        frame[0, 0] = (self.ordinal % 200, 10, 10)
        if self.progress_after_swipe and "settled" in label:
            # Distinct pixels so semantic digest changes with progress origin.
            frame[10, 10] = (40, 40, 40)
        return CapturedNativeFrame(
            frame,
            f"png-{self.ordinal}".encode(),
            "f" * 64,
            float(self.ordinal),
            self.session / f"{label}.png",
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


class HomeAtlasVerifiedRouteTests(unittest.TestCase):
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
                issued, execution, _obs = dispatch_verified_navigate_pan(
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
                    monotonic_clock=_MonoClock(captured),
                    wall_clock=lambda: _TEST_WALL,
                )
                self.assertFalse(issued.authorized)
                self.assertIsNone(execution)
                self.assertEqual(runtime.swipes, [])

            with _open_safety_store(Path(directory), name="safety2.sqlite3") as store2:
                policy2 = _policy_for("RUNTIME-RESUMABLE-NAVIGATION-SESSIONS")
                issued2, execution2, obs = dispatch_verified_navigate_pan(
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
                    monotonic_clock=_MonoClock(captured),
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
                issued, execution, _obs = dispatch_verified_navigate_pan(
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
                    monotonic_clock=_MonoClock(captured),
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
                    monotonic_clock=_MonoClock(captured),
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
                issued, execution, obs = dispatch_verified_navigate_pan(
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
                    monotonic_clock=_MonoClock(captured),
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


if __name__ == "__main__":
    unittest.main()
