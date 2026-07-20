"""Offline adversarial tests for the verified Supply Depot radial route."""

from __future__ import annotations

import importlib
import inspect
import json
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator
from unittest.mock import patch
import tempfile
import unittest

import numpy as np

from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.home_atlas_bluestacks import (
    CONFIRMED_NOT_DISPATCHED_STATUS,
    SUPPLY_DEPOT_BUILDING_SEMANTIC_ACTION,
    SUPPLY_DEPOT_EXIT_SEMANTIC_ACTION,
    SUPPLY_DEPOT_RADIAL_POSTCONDITION,
    build_supply_depot_building_observation,
    build_supply_depot_exit_observation,
    SUPPLY_DEPOT_RADIAL_TARGET_IDENTITY,
    SUPPLY_DEPOT_ROUTE_TASK_ID,
    build_supply_depot_radial_observation,
    build_supply_depot_radial_perception_bundle,
    build_supply_depot_safe_exit_probe,
    command_supply_depot_radial,
    dispatch_verified_supply_depot_building_tap,
    dispatch_verified_supply_depot_exit_tap,
    dispatch_verified_supply_depot_radial_tap,
    identity_from_captured,
    recognize_supply_depot_home_successor,
    reject_direct_supply_depot_radial_transport,
)
from safe_action_core import ActionClass, ActionStatus, CentralPolicy, SafetyStore
from safe_action_core.models import navigation_capability_forbidden_reason
from tasks.home_atlas import AmbiguityState, BuildingBinding, LocalizationResult, ZoomIdentity
from tasks.home_atlas_vision import BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, frame_digest
from tasks.navigation_session import (
    AuthorizationScope,
    NavigationCheckpoint,
    create_session,
)
from tasks.perception_bundle import PerceptionBundleError
from tasks.radial_semantics import radial_semantics_authorize_dispatch


_TEST_WALL = 1000.0
_TEST_LEASE_TTL = 100.0


@contextmanager
def _open_store(directory: Path, *, name: str = "safety.sqlite3") -> Iterator[SafetyStore]:
    store = SafetyStore(directory / name)
    store.acquire_lease("owner", _TEST_WALL, _TEST_LEASE_TTL)
    try:
        yield store
    finally:
        store.close()


class _FakeRuntime:
    execute = True
    in_flight_action = None

    def __init__(self, session: Path) -> None:
        self.session = session
        self.ordinal = 0
        self.taps: list[dict[str, object]] = []

    def capture(self, label: str) -> CapturedNativeFrame:
        self.ordinal += 1
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        frame[0, 0] = (self.ordinal, 10, 20)
        return CapturedNativeFrame(
            frame,
            ("a" * 64).encode("ascii"),
            "a" * 64,
            float(self.ordinal),
            self.session / f"{label}.png",
        )

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


def _binding(frame: np.ndarray) -> BuildingBinding:
    return BuildingBinding(
        building_id="home.building.supply_depot",
        target_roi=(640, 740, 735, 835),
        frame_sha256=frame_digest(frame),
        confidence=0.97,
        semantic_evidence=(
            "current-frame Supply Depot radial",
            "OCR: Claim Supply",
        ),
        overlay_intersects=False,
        ambiguous_overlap=False,
    )


def _identity(
    runtime: _FakeRuntime,
    captured: CapturedNativeFrame,
    *,
    ordinal: int | None = None,
) -> object:
    return identity_from_captured(
        captured,
        session_id=str(runtime.session),
        ordinal=ordinal or int(captured.captured_monotonic),
        label="radial-immediate-before",
    )


def _successor(frame: np.ndarray, *, recognized: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        recognized=recognized,
        state="available" if recognized else "unknown",
        title_text="Supply Depot" if recognized else "",
        controls=(),
        premium_or_purchase_visible=False,
        overlay=False,
        ambiguity="none" if recognized else "title_not_recognized",
        frame_sha256=frame_digest(frame),
        daily_free_attempts=None,
    )


def _home_successor(frame: np.ndarray) -> SimpleNamespace:
    return SimpleNamespace(
        recognized=True,
        frame_sha256=frame_digest(frame),
        confidence=0.99,
        residual_px=0.0,
        profile_id=BLUESTACKS_PROFILE_ID,
    )


def _policy() -> CentralPolicy:
    return CentralPolicy(
        supervised_tasks=frozenset({"MVP-QUEST-TO-CLAIM", SUPPLY_DEPOT_ROUTE_TASK_ID})
    )


class SupplyDepotVerifiedRouteTests(unittest.TestCase):
    def test_command_reuses_all_shared_seams_and_finishes_navigation_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = _FakeRuntime(root)

            def bind(frame, *, source_frame=None):
                return _binding(frame)

            recognizer = lambda frame, *, source_frame=None: _successor(frame)
            args = SimpleNamespace(
                execute=True,
                yes=True,
                settle_seconds=0,
                adb="unused",
                serial="emulator-5554",
                output_directory=root,
            )
            with patch(
                "scripts.home_atlas_bluestacks.connect_runtime",
                return_value=runtime,
            ), patch(
                "scripts.home_atlas_bluestacks.bind_supply_depot_claim_supply",
                side_effect=bind,
            ), patch(
                "scripts.home_atlas_bluestacks.recognize_supply_depot_screen",
                side_effect=recognizer,
            ), patch(
                "scripts.home_atlas_bluestacks.recognize_supply_depot_home_successor",
                side_effect=lambda frame, *, atlas_path=None, source_frame: (
                    _home_successor(frame)
                ),
            ), patch(
                "scripts.home_atlas_bluestacks.time.monotonic",
                side_effect=lambda: float(runtime.ordinal) + 0.2,
            ):
                code = command_supply_depot_radial(args)

            self.assertEqual(code, 0)
            self.assertEqual(len(runtime.taps), 2)
            self.assertEqual(
                runtime.taps[0]["target_identity"],
                SUPPLY_DEPOT_RADIAL_TARGET_IDENTITY,
            )
            self.assertEqual(
                runtime.taps[1]["target_identity"],
                "supply-depot-back-arrow",
            )
            self.assertFalse(runtime.taps[0]["consequential"])
            payload = json.loads(
                (root / "radial-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(payload["status"], "completed")
            self.assertTrue(payload["requested"])
            self.assertTrue(payload["authorized"])
            self.assertTrue(payload["dispatched"])
            self.assertTrue(payload["transport_observed"])
            self.assertTrue(payload["verified"])
            self.assertTrue(payload["completed"])
            self.assertEqual(payload["immediate_post_identity"]["capture_ordinal"], 3)
            self.assertEqual(payload["settled_identity"]["capture_ordinal"], 4)
            self.assertEqual(
                payload["settled_perception_bundle"]["bundle"]["frame"][
                    "capture_ordinal"
                ],
                4,
            )
            self.assertEqual(payload["production_registration"], "NOT_REGISTERED")
            self.assertIs(payload["scheduler_eligibility"], False)
            self.assertEqual(
                payload["confirmed_not_dispatched_authority"],
                CONFIRMED_NOT_DISPATCHED_STATUS,
            )
            self.assertEqual(
                payload["navigation_observability"]["terminal_state"]["value"]["class"],
                "success",
            )
            self.assertEqual(
                payload["radial_semantics"]["radial_semantics"]["radial_identity"],
                "home.radial.supply_depot",
            )
            self.assertIs(
                payload["safe_exit_binding"]["authorize_dispatch"],
                False,
            )
            self.assertEqual(
                payload["safe_exit_binding"]["safe_exit_binding"]["reason_code"],
                "SAFE_EXIT_CANDIDATE_BOUND",
            )

            session_payload = json.loads(
                (root / "radial-navigation-session.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(session_payload["checkpoint"], "home_recovered")
            self.assertEqual(session_payload["outcome"], "completed")
            self.assertEqual(
                [entry["status"] for entry in session_payload["action_ledger"]],
                ["reconciled", "reconciled"],
            )

    def test_direct_radial_transport_bypass_is_rejected_and_command_body_is_sealed(self) -> None:
        with self.assertRaises(RuntimeError) as raised:
            reject_direct_supply_depot_radial_transport()
        self.assertEqual(str(raised.exception), "DIRECT_TRANSPORT_BYPASS_REJECTED")

        module = importlib.import_module("scripts.home_atlas_bluestacks")
        source = inspect.getsource(module.command_supply_depot_radial)
        self.assertNotIn("runtime.tap(", source)
        self.assertIn("dispatch_verified_supply_depot_radial_tap(", source)

    def test_closed_radial_is_opened_through_building_capability_then_exits_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = _FakeRuntime(root)
            radial_calls = 0

            def radial_bind(frame, *, source_frame=None):
                nonlocal radial_calls
                radial_calls += 1
                return None if radial_calls == 1 else _binding(frame)

            args = SimpleNamespace(
                execute=True,
                yes=True,
                settle_seconds=0,
                adb="unused",
                serial="emulator-5554",
                output_directory=root,
            )
            with patch(
                "scripts.home_atlas_bluestacks.connect_runtime",
                return_value=runtime,
            ), patch(
                "scripts.home_atlas_bluestacks.bind_supply_depot_claim_supply",
                side_effect=radial_bind,
            ), patch(
                "scripts.home_atlas_bluestacks.bind_supply_depot_home_building",
                side_effect=lambda frame, *, atlas_path, source_frame: _binding(frame),
            ), patch(
                "scripts.home_atlas_bluestacks.recognize_supply_depot_screen",
                side_effect=lambda frame, *, source_frame=None: _successor(frame),
            ), patch(
                "scripts.home_atlas_bluestacks.recognize_supply_depot_home_successor",
                side_effect=lambda frame, *, atlas_path=None, source_frame: (
                    _home_successor(frame)
                ),
            ), patch(
                "scripts.home_atlas_bluestacks.time.monotonic",
                side_effect=lambda: float(runtime.ordinal) + 0.2,
            ):
                code = command_supply_depot_radial(args)

            self.assertEqual(code, 0)
            self.assertEqual(
                [tap["target_identity"] for tap in runtime.taps],
                [
                    "home.building.supply_depot",
                    SUPPLY_DEPOT_RADIAL_TARGET_IDENTITY,
                    "supply-depot-back-arrow",
                ],
            )
            payload = json.loads(
                (root / "radial-result.json").read_text(encoding="utf-8")
            )
            self.assertTrue(payload["actions"]["building_entry"]["completed"])
            self.assertTrue(payload["actions"]["radial_entry"]["completed"])
            self.assertTrue(payload["actions"]["safe_exit"]["completed"])
            session_payload = json.loads(
                (root / "radial-navigation-session.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(session_payload["checkpoint"], "home_recovered")
            self.assertEqual(
                [entry["status"] for entry in session_payload["action_ledger"]],
                ["reconciled", "reconciled", "reconciled"],
            )

    def test_radial_control_is_navigation_only_but_semantically_claim_labeled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = _FakeRuntime(Path(directory))
            captured = runtime.capture("before")
            identity = _identity(runtime, captured)
            semantics = build_supply_depot_radial_perception_bundle(
                identity, _binding(captured.frame)
            ).radial.semantics
            self.assertEqual(semantics.controls[0].role.value, "claim")
            self.assertEqual(semantics.controls[0].expected_successors, ("facility.screen",))
            self.assertEqual(semantics.controls[0].forbidden_successors, ("facility.claim_supply",))
            self.assertFalse(radial_semantics_authorize_dispatch(semantics))
            observation = build_supply_depot_radial_observation(
                identity=identity,
                binding=_binding(captured.frame),
            )
            self.assertEqual(observation.expected_postcondition, SUPPLY_DEPOT_RADIAL_POSTCONDITION)
            self.assertEqual(observation.control_class, "CLAIM")
            self.assertIsNone(
                navigation_capability_forbidden_reason(
                    SimpleNamespace(
                        action_class=ActionClass.NAVIGATION_ONLY,
                        semantic_action="SUPPLY_DEPOT_RADIAL_NAVIGATION",
                        observation=observation,
                    )
                )
            )

    def test_building_and_exit_capability_exceptions_are_exact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = _FakeRuntime(Path(directory))
            captured = runtime.capture("exact-policy")
            identity = _identity(runtime, captured)
            binding = _binding(captured.frame)
            for semantic_action, observation in (
                (
                    SUPPLY_DEPOT_BUILDING_SEMANTIC_ACTION,
                    build_supply_depot_building_observation(
                        identity=identity,
                        binding=binding,
                    ),
                ),
                (
                    SUPPLY_DEPOT_EXIT_SEMANTIC_ACTION,
                    build_supply_depot_exit_observation(
                        identity=identity,
                        recognized_screen=True,
                    ),
                ),
            ):
                self.assertIsNone(
                    navigation_capability_forbidden_reason(
                        SimpleNamespace(
                            action_class=ActionClass.NAVIGATION_ONLY,
                            semantic_action=semantic_action,
                            observation=observation,
                        )
                    )
                )
            self.assertEqual(
                navigation_capability_forbidden_reason(
                    SimpleNamespace(
                        action_class=ActionClass.NAVIGATION_ONLY,
                        semantic_action=SUPPLY_DEPOT_EXIT_SEMANTIC_ACTION,
                        observation=build_supply_depot_exit_observation(
                            identity=identity,
                            recognized_screen=False,
                        ),
                    )
                ),
                "CAPABILITY_NAVIGATION_CONSEQUENTIAL_DENIED",
            )
            with self.assertRaises(PerceptionBundleError):
                build_supply_depot_building_observation(
                    identity=identity,
                    binding=replace(
                        binding,
                        building_id="home.building.other",
                    ),
                )

    def test_building_and_exit_dry_run_have_zero_transport(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = _FakeRuntime(root)
            captured = runtime.capture("dry-run-entry")
            identity = _identity(runtime, captured)
            with _open_store(root) as store:
                building_issued, building_execution, _, _ = (
                    dispatch_verified_supply_depot_building_tap(
                        runtime=runtime,
                        immediate_before=captured,
                        identity=identity,
                        binding=_binding(captured.frame),
                        action_id="dry-building",
                        action_key="dry-building-key",
                        task_id=SUPPLY_DEPOT_ROUTE_TASK_ID,
                        navigation_session_id="dry-session",
                        lease_owner="owner",
                        policy=_policy(),
                        store=store,
                        monotonic_clock=lambda: 1.2,
                        wall_clock=lambda: _TEST_WALL,
                        dry_run=True,
                    )
                )
                exit_issued, exit_execution, _, _ = (
                    dispatch_verified_supply_depot_exit_tap(
                        runtime=runtime,
                        immediate_before=captured,
                        identity=identity,
                        action_id="dry-exit",
                        action_key="dry-exit-key",
                        task_id=SUPPLY_DEPOT_ROUTE_TASK_ID,
                        navigation_session_id="dry-session",
                        lease_owner="owner",
                        policy=_policy(),
                        store=store,
                        home_successor_recognizer=lambda *args, **kwargs: (
                            _home_successor(captured.frame)
                        ),
                        monotonic_clock=lambda: 1.2,
                        wall_clock=lambda: _TEST_WALL,
                        dry_run=True,
                    )
                )
            self.assertTrue(building_issued.authorized)
            self.assertTrue(exit_issued.authorized)
            self.assertEqual(
                building_execution.status,
                ActionStatus.CANCELLED,
            )
            self.assertEqual(exit_execution.status, ActionStatus.CANCELLED)
            self.assertEqual(building_execution.transport_calls, 0)
            self.assertEqual(exit_execution.transport_calls, 0)
            self.assertEqual(runtime.taps, [])

    def test_normal_claim_remains_denied_by_navigation_capability_firewall(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = _FakeRuntime(Path(directory))
            captured = runtime.capture("before")
            identity = _identity(runtime, captured)
            observation = build_supply_depot_radial_observation(
                identity=identity,
                binding=_binding(captured.frame),
            )
            denied = navigation_capability_forbidden_reason(
                SimpleNamespace(
                    action_class=ActionClass.NAVIGATION_ONLY,
                    semantic_action="SUPPLY_DEPOT_CLAIM",
                    observation=observation,
                )
            )
            self.assertEqual(denied, "CAPABILITY_NAVIGATION_CONSEQUENTIAL_DENIED")

    def test_capability_denial_dispatches_zero_and_does_not_tap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = _FakeRuntime(root)
            captured = runtime.capture("before")
            identity = _identity(runtime, captured)
            with _open_store(root) as store:
                issued, execution, _observation, telemetry = (
                    dispatch_verified_supply_depot_radial_tap(
                        runtime=runtime,
                        immediate_before=captured,
                        identity=identity,
                        binding=_binding(captured.frame),
                        action_id="deny-1",
                        action_key="deny-key-1",
                        task_id=SUPPLY_DEPOT_ROUTE_TASK_ID,
                        navigation_session_id="nav-deny",
                        lease_owner="owner",
                        policy=CentralPolicy(supervised_tasks=frozenset({"OTHER"})),
                        store=store,
                        monotonic_clock=lambda: 1.2,
                        wall_clock=lambda: _TEST_WALL,
                    )
                )
            self.assertFalse(issued.authorized)
            self.assertIsNone(execution)
            self.assertEqual(runtime.taps, [])
            self.assertTrue(telemetry["requested"])
            self.assertFalse(telemetry["authorized"])
            self.assertFalse(telemetry["dispatched"])

    def test_dry_run_consumes_capability_without_transport(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = _FakeRuntime(root)
            captured = runtime.capture("before")
            identity = _identity(runtime, captured)
            with _open_store(root) as store:
                issued, execution, _observation, telemetry = (
                    dispatch_verified_supply_depot_radial_tap(
                        runtime=runtime,
                        immediate_before=captured,
                        identity=identity,
                        binding=_binding(captured.frame),
                        action_id="dry-1",
                        action_key="dry-key-1",
                        task_id=SUPPLY_DEPOT_ROUTE_TASK_ID,
                        navigation_session_id="nav-dry",
                        lease_owner="owner",
                        policy=_policy(),
                        store=store,
                        monotonic_clock=lambda: 1.2,
                        wall_clock=lambda: _TEST_WALL,
                        dry_run=True,
                    )
                )
            self.assertTrue(issued.authorized)
            self.assertIsNotNone(execution)
            self.assertEqual(execution.status, ActionStatus.CANCELLED)
            self.assertEqual(execution.transport_calls, 0)
            self.assertEqual(runtime.taps, [])
            self.assertFalse(telemetry["dispatched"])
            self.assertFalse(telemetry["transport_observed"])

    def test_one_shot_duplicate_action_key_suppresses_second_tap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = _FakeRuntime(root)
            captured = runtime.capture("before")
            identity = _identity(runtime, captured)
            kwargs = dict(
                runtime=runtime,
                immediate_before=captured,
                identity=identity,
                binding=_binding(captured.frame),
                task_id=SUPPLY_DEPOT_ROUTE_TASK_ID,
                navigation_session_id="nav-duplicate",
                lease_owner="owner",
                policy=_policy(),
                settle_seconds=0,
                monotonic_clock=lambda: float(runtime.ordinal) + 0.2,
                wall_clock=lambda: _TEST_WALL,
            )
            with patch(
                "scripts.home_atlas_bluestacks.recognize_supply_depot_screen",
                side_effect=lambda frame, *, source_frame=None: _successor(frame),
            ), _open_store(root) as store:
                first = dispatch_verified_supply_depot_radial_tap(
                    **kwargs,
                    store=store,
                    action_id="duplicate-1",
                    action_key="duplicate-key",
                )
                second = dispatch_verified_supply_depot_radial_tap(
                    **kwargs,
                    store=store,
                    action_id="duplicate-2",
                    action_key="duplicate-key",
                )
            self.assertEqual(first[1].status, ActionStatus.CONFIRMED)
            self.assertEqual(second[1].status, ActionStatus.CANCELLED)
            self.assertEqual(len(runtime.taps), 1)

    def test_stale_or_cross_capture_binding_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = _FakeRuntime(Path(directory))
            first = runtime.capture("first")
            second = runtime.capture("second")
            first_identity = _identity(runtime, first, ordinal=1)
            second_identity = identity_from_captured(
                second,
                session_id=str(runtime.session),
                ordinal=runtime.ordinal,
                label="second",
            )
            foreign = replace(
                _binding(first.frame),
                frame_sha256=second_identity.semantic_sha256,
            )
            with self.assertRaises(PerceptionBundleError) as raised:
                build_supply_depot_radial_observation(
                    identity=first_identity,
                    binding=foreign,
                )
            self.assertEqual(raised.exception.reason_code, "SEMANTIC_DIGEST_MISMATCH")
            with self.assertRaises(PerceptionBundleError):
                build_supply_depot_radial_perception_bundle(
                    first_identity,
                    replace(
                        _binding(first.frame),
                        frame_sha256=second_identity.semantic_sha256,
                    ),
                )

    def test_transport_observed_without_successor_is_not_verified_or_completed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = _FakeRuntime(root)
            args = SimpleNamespace(
                execute=True,
                yes=True,
                settle_seconds=0,
                adb="unused",
                serial="emulator-5554",
                output_directory=root,
            )
            with patch(
                "scripts.home_atlas_bluestacks.connect_runtime",
                return_value=runtime,
            ), patch(
                "scripts.home_atlas_bluestacks.bind_supply_depot_claim_supply",
                side_effect=lambda frame, *, source_frame=None: _binding(frame),
            ), patch(
                "scripts.home_atlas_bluestacks.recognize_supply_depot_screen",
                side_effect=lambda frame, *, source_frame=None: _successor(
                    frame, recognized=False
                ),
            ), patch(
                "scripts.home_atlas_bluestacks.time.monotonic",
                side_effect=lambda: float(runtime.ordinal) + 0.2,
            ):
                code = command_supply_depot_radial(args)
            payload = json.loads(
                (root / "radial-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(code, 3)
            self.assertEqual(len(runtime.taps), 1)
            self.assertTrue(payload["transport_observed"])
            self.assertFalse(payload["verified"])
            self.assertFalse(payload["completed"])
            self.assertEqual(
                payload["actions"]["radial_entry"]["executor_status"],
                ActionStatus.UNRESOLVED.value,
            )
            self.assertEqual(
                payload["navigation_observability"]["terminal_state"]["value"]["class"],
                "uncertain",
            )

    def test_home_successor_accepts_zoomed_in_home_after_exit(self) -> None:
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        digest = frame_digest(frame)
        identity = SimpleNamespace(semantic_sha256=digest)
        zoomed_in = LocalizationResult(
            recognized=False,
            platform=BLUESTACKS_PLATFORM,
            profile_id=BLUESTACKS_PROFILE_ID,
            zoom_identity=ZoomIdentity.ZOOMED_IN,
            screen_to_atlas=None,
            viewport_polygon=((0.0, 0.0), (800.0, 0.0), (800.0, 1280.0), (0.0, 1280.0)),
            confidence=0.90,
            supporting_landmarks=("landmark-a", "landmark-b"),
            residual_px=2.0,
            ambiguity_state=AmbiguityState.NONE,
            map_edge_state="interior",
            frame_sha256=digest,
            timestamp="2026-07-20T00:00:00Z",
        )
        with patch(
            "scripts.home_atlas_bluestacks.recognize_supply_depot_screen",
            return_value=SimpleNamespace(recognized=False),
        ), patch(
            "scripts.home_atlas_bluestacks.load_home_atlas",
            return_value=object(),
        ), patch(
            "scripts.home_atlas_bluestacks.BlueStacksHomeLocalizer",
        ) as localizer_cls:
            localizer_cls.return_value.localize.return_value = zoomed_in
            result = recognize_supply_depot_home_successor(
                frame,
                atlas_path=Path("atlas.json"),
                source_frame=identity,  # type: ignore[arg-type]
            )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.recognized)
        self.assertEqual(result.zoom_identity, ZoomIdentity.ZOOMED_IN)
        self.assertEqual(result.frame_sha256, digest)

    def test_home_successor_rejects_facility_screen(self) -> None:
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        identity = SimpleNamespace(semantic_sha256=frame_digest(frame))
        with patch(
            "scripts.home_atlas_bluestacks.recognize_supply_depot_screen",
            return_value=SimpleNamespace(recognized=True),
        ):
            result = recognize_supply_depot_home_successor(
                frame,
                atlas_path=Path("atlas.json"),
                source_frame=identity,  # type: ignore[arg-type]
            )
        self.assertIsNone(result)

    def test_safe_exit_binder_is_same_capture_and_non_authorizing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = _FakeRuntime(Path(directory))
            captured = runtime.capture("safe-exit-probe")
            identity = _identity(runtime, captured)
            result = build_supply_depot_safe_exit_probe(
                identity,
                radial_binding=_binding(captured.frame),
            )
            self.assertEqual(result.reason_code, "SAFE_EXIT_CANDIDATE_BOUND")
            self.assertFalse(result.authorize_dispatch)
            self.assertTrue(result.source_frame.same_capture_event(identity))
            self.assertIsNotNone(result.candidate)
            self.assertIsNone(result.candidate.capability_grant)
            self.assertIsNone(result.candidate.policy_grant)
            self.assertTrue(
                any(
                    proof.regions
                    for proof in result.exclusion_inventory.coverage
                )
            )

    def test_session_chain_is_single_authoritative_radial_session(self) -> None:
        auth = AuthorizationScope(
            task_id=SUPPLY_DEPOT_ROUTE_TASK_ID,
            owner_operator="supply-depot-radial",
            action_class="navigation_only",
            platform=BLUESTACKS_PLATFORM,
            profile=BLUESTACKS_PROFILE_ID,
            environment="local_bluestacks",
            target_building_id="home.building.supply_depot",
        )
        session = create_session(
            auth,
            route_id="supply-route",
            navigation_session_id="supply-session",
            runtime_capture_session_id="runtime",
            maximum_pans=1,
        )
        self.assertEqual(session.checkpoint, NavigationCheckpoint.CREATED)
        self.assertEqual(session.route_id, "supply-route")
        self.assertEqual(session.navigation_session_id, "supply-session")

    def test_registration_scheduler_and_non_dispatch_posture_unchanged(self) -> None:
        self.assertEqual(
            CONFIRMED_NOT_DISPATCHED_STATUS,
            "NON_DISPATCH_AUTHORITY_UNAVAILABLE",
        )
        module = importlib.import_module("scripts.home_atlas_bluestacks")
        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn('production_registration"] = "NOT_REGISTERED"', source)
        self.assertIn('scheduler_eligibility"] = False', source)


if __name__ == "__main__":
    unittest.main()
