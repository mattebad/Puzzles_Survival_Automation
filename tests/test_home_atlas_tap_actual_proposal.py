"""The Home Atlas tap adapters preserve planning evidence through real dispatch fences."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from typing import Iterator
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from safe_action_core import ActionStatus, SafetyStore
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts import home_atlas_bluestacks as home
from tasks.home_atlas import AmbiguityState, BuildingBinding, LocalizationResult, ZoomIdentity
from tasks.home_atlas_vision import BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, frame_digest
from tasks.perception_bundle import PerceptionBundleError
from tests.support.home_atlas import _RecordingPolicy


_KINDS = ("supply_building", "supply_radial", "supply_exit", "campaign_building")
_BUILDERS = {
    "supply_building": "build_supply_depot_building_observation",
    "supply_radial": "build_supply_depot_radial_observation",
    "supply_exit": "build_supply_depot_exit_observation",
    "campaign_building": "build_campaign_home_building_observation",
}


class _Runtime:
    """Native capture events with real PNG bytes, hashes, and independent clock times."""

    execute = True
    in_flight_action = None

    def __init__(self, directory: Path) -> None:
        self.session = directory
        self.ordinal = 0
        self.now = 100.0
        self.capture_time_step = 0.25
        self.captures: list[tuple[str, CapturedNativeFrame]] = []
        self.taps: list[tuple[CapturedNativeFrame, dict[str, object]]] = []

    def capture(self, label: str) -> CapturedNativeFrame:
        self.ordinal += 1
        self.now += self.capture_time_step
        frame = np.full((1280, 800, 3), 60, dtype=np.uint8)
        frame[0, 0] = (self.ordinal, 100, 180)
        ok, encoded = cv2.imencode(".png", frame)
        assert ok
        png = encoded.tobytes()
        path = self.session / f"{self.ordinal:04d}-{label}.png"
        path.write_bytes(png)
        captured = CapturedNativeFrame(frame, png, hashlib.sha256(png).hexdigest(), self.now, path)
        self.captures.append((label, captured))
        return captured

    def tap(self, captured: CapturedNativeFrame, **target: object) -> None:
        self.taps.append((captured, target))

    def clock(self) -> float:
        return self.now + 0.01


def _binding(frame: np.ndarray, kind: str) -> BuildingBinding:
    return BuildingBinding(
        building_id=(home.CAMPAIGN_HOME_ATLAS_BUILDING_ID if kind == "campaign_building"
                     else home.SUPPLY_DEPOT_BUILDING_TARGET_IDENTITY),
        target_roi=(300, 400, 400, 500),
        frame_sha256=frame_digest(frame),
        confidence=0.99,
        semantic_evidence=("current-frame mapped interaction anchor", "Claim Supply"),
    )


def _screen(frame: np.ndarray, *, recognized: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        recognized=recognized,
        state="available" if recognized else "unknown",
        title_text="Supply Depot" if recognized else "",
        controls=(), premium_or_purchase_visible=False, overlay=False,
        ambiguity="none" if recognized else "title_not_recognized",
        frame_sha256=frame_digest(frame), daily_free_attempts=None,
    )


def _home(frame: np.ndarray, *, recognized: bool = True) -> LocalizationResult:
    return LocalizationResult(
        recognized=recognized, platform=BLUESTACKS_PLATFORM, profile_id=BLUESTACKS_PROFILE_ID,
        zoom_identity=ZoomIdentity.FULLY_ZOOMED_OUT,
        screen_to_atlas=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        viewport_polygon=((0, 0), (800, 0), (800, 1280), (0, 1280)),
        confidence=0.99, supporting_landmarks=("current-frame-landmark",), residual_px=0.0,
        ambiguity_state=AmbiguityState.NONE, map_edge_state="none",
        frame_sha256=frame_digest(frame), timestamp="test-native-capture",
    )


class _Case:
    def __init__(self, directory: Path, kind: str) -> None:
        self.kind = kind
        self.runtime = _Runtime(directory)
        self.planning = self.runtime.capture("planning")
        self.identity = home.identity_from_captured(
            self.planning, session_id=str(directory), ordinal=self.runtime.ordinal, label="planning",
        )
        self.binding = _binding(self.planning.frame, kind)
        self.policy = _RecordingPolicy()
        self.store = SafetyStore(directory / "safety.sqlite3")
        self.store.acquire_lease("owner", 1000.0, 100.0)
        self.action_id = f"actual-proposal-{kind}"
        self.successor_recognized = True

    def dispatch(self):
        common = dict(
            runtime=self.runtime, immediate_before=self.planning, identity=self.identity,
            action_id=self.action_id, action_key=f"{self.action_id}-key",
            task_id=home.SUPPLY_DEPOT_ROUTE_TASK_ID, navigation_session_id="native-test-session",
            lease_owner="owner", policy=self.policy, store=self.store,
            monotonic_clock=self.runtime.clock, wall_clock=lambda: 1000.0,
        )
        if self.kind == "supply_exit":
            return home.dispatch_verified_supply_depot_exit_tap(
                **common, home_successor_recognizer=lambda frame, **_: _home(
                    frame, recognized=self.successor_recognized,
                ),
            )
        common["binding"] = self.binding
        if self.kind == "supply_building":
            return home.dispatch_verified_supply_depot_building_tap(
                **common, rebind_building=lambda frame, _: _binding(frame, self.kind),
            )
        if self.kind == "supply_radial":
            return home.dispatch_verified_supply_depot_radial_tap(
                **common, rebind_radial=lambda frame, _: _binding(frame, self.kind),
            )
        return home.dispatch_verified_campaign_home_building_tap(
            **common, semantic_opened_check=lambda _: self.successor_recognized,
        )


@contextmanager
def _case(kind: str) -> Iterator[_Case]:
    with tempfile.TemporaryDirectory() as directory, ExitStack() as patches:
        case = _Case(Path(directory), kind)
        atlas = SimpleNamespace(lookup_building=lambda semantic_id: SimpleNamespace(semantic_id=semantic_id))
        patches.enter_context(patch.object(home, "load_home_atlas", return_value=atlas))
        patches.enter_context(patch.object(home, "BlueStacksHomeLocalizer", return_value=SimpleNamespace(
            localize=lambda frame: _home(frame),
        )))
        patches.enter_context(patch.object(home, "bind_visible_building", side_effect=lambda frame, *_args, **_kwargs:
            _binding(frame, "campaign_building")))
        patches.enter_context(patch.object(home, "bind_supply_depot_claim_supply", side_effect=lambda frame, **_kwargs:
            _binding(frame, "supply_radial") if case.successor_recognized else None))
        patches.enter_context(patch.object(home, "recognize_supply_depot_screen", side_effect=lambda frame, **_kwargs:
            _screen(frame, recognized=case.successor_recognized)))
        try:
            yield case
        finally:
            case.store.close()


class HomeAtlasActualTapProposalTests(unittest.TestCase):
    def test_actual_planning_and_issuance_evidence_survive_one_real_core_dispatch(self) -> None:
        for kind in _KINDS:
            with self.subTest(kind=kind), _case(kind) as case:
                issued, execution, immediate, telemetry = case.dispatch()
                self.assertTrue(issued.authorized)
                self.assertEqual(execution.status, ActionStatus.CONFIRMED)
                self.assertEqual(execution.transport_calls, 1)
                self.assertEqual(len(case.runtime.taps), 1)
                fresh = case.runtime.captures[1][1]
                self.assertIs(case.runtime.taps[0][0], fresh)
                self.assertEqual(immediate.frame_sha256, frame_digest(fresh.frame))
                self.assertEqual(immediate.capture_completed_monotonic, fresh.captured_monotonic)
                self.assertTrue(any(request.policy_phase == "pre_dispatch" and request.observation is immediate
                                    for request in case.policy.requests))
                action = case.store.get_action(case.action_id)
                self.assertEqual(action["source_frame_sha256"], case.identity.semantic_sha256)
                self.assertEqual(action["source_frame_captured_at"], case.planning.captured_monotonic)
                self.assertNotEqual(action["source_frame_sha256"], immediate.frame_sha256)
                settled = case.runtime.captures[-1][1]
                self.assertEqual(telemetry["settled_identity"].semantic_sha256, frame_digest(settled.frame))
                self.assertEqual(telemetry["settled_identity"].capture_completed_monotonic, settled.captured_monotonic)
                reconciled = json.loads(action["reconciliation_result_json"])
                self.assertEqual(reconciled["frame_sha256"], frame_digest(settled.frame))
                self.assertTrue(telemetry["completed"])

    def test_stale_planning_is_not_replaced_by_fresh_issuance(self) -> None:
        for kind in _KINDS:
            with self.subTest(kind=kind), _case(kind) as case:
                case.runtime.now += 40.0
                issued, execution, immediate, _ = case.dispatch()
                self.assertTrue(issued.authorized)
                self.assertEqual(execution.status, ActionStatus.CANCELLED)
                self.assertEqual(execution.transport_calls, 0)
                self.assertFalse(case.runtime.taps)
                planning_requests = [request for request in case.policy.requests
                                     if request.observation.frame_sha256 == case.identity.semantic_sha256]
                self.assertTrue(planning_requests)
                self.assertEqual(planning_requests[-1].observation.capture_completed_monotonic,
                                 case.planning.captured_monotonic)
                self.assertGreater(immediate.capture_completed_monotonic, case.planning.captured_monotonic + 30)

    def test_invalid_planning_source_or_cost_cannot_be_erased_by_valid_issuance(self) -> None:
        for kind in _KINDS:
            for invalid in ({"recognized": False}, {"cost_type": "premium", "cost_amount": 1}):
                with self.subTest(kind=kind, invalid=invalid), _case(kind) as case:
                    builder_name = _BUILDERS[kind]
                    builder = getattr(home, builder_name)

                    def build(*, identity, **kwargs):
                        observation = builder(identity=identity, **kwargs)
                        return replace(observation, **invalid) if identity is case.identity else observation

                    with patch.object(home, builder_name, side_effect=build):
                        issued, execution, _, _ = case.dispatch()
                    self.assertTrue(issued.authorized)
                    self.assertEqual(execution.status, ActionStatus.CANCELLED)
                    self.assertEqual(execution.transport_calls, 0)
                    self.assertFalse(case.runtime.taps)

    def test_only_campaign_roi_drift_dispatches_the_independently_bound_current_target(self) -> None:
        for kind in _KINDS:
            with self.subTest(kind=kind), _case(kind) as case:
                builder_name = _BUILDERS[kind]
                builder = getattr(home, builder_name)

                def build(*, identity, **kwargs):
                    observation = builder(identity=identity, **kwargs)
                    if identity is case.identity:
                        x1, y1, x2, y2 = observation.target_roi
                        return replace(observation, target_roi=(x1 + 2, y1 + 2, x2 + 2, y2 + 2))
                    return observation

                with patch.object(home, builder_name, side_effect=build):
                    issued, execution, immediate, _ = case.dispatch()
                self.assertTrue(issued.authorized)
                if kind == "campaign_building":
                    self.assertEqual(execution.status, ActionStatus.CONFIRMED)
                    self.assertEqual(execution.transport_calls, 1)
                    self.assertTrue(issued.capability.consumed)
                    self.assertEqual(len(case.runtime.taps), 1)
                    fresh = case.runtime.captures[1][1]
                    self.assertIs(case.runtime.taps[0][0], fresh)
                    self.assertEqual(case.runtime.taps[0][1]["target_roi"], immediate.target_roi)
                    self.assertEqual(immediate.frame_sha256, frame_digest(fresh.frame))
                    self.assertEqual(immediate.capture_completed_monotonic, fresh.captured_monotonic)
                    continue
                self.assertEqual(execution.status, ActionStatus.CANCELLED)
                self.assertEqual(execution.reason, "TARGET_ROI_CHANGED")
                self.assertEqual(execution.transport_calls, 0)
                self.assertFalse(case.runtime.taps)

    def test_mismatched_planning_capture_identity_stops_before_fresh_capture(self) -> None:
        for kind in _KINDS:
            with self.subTest(kind=kind), _case(kind) as case:
                case.identity = replace(case.identity, semantic_sha256="0" * 64)
                with self.assertRaises(PerceptionBundleError):
                    case.dispatch()
                self.assertEqual(len(case.runtime.captures), 1)
                self.assertFalse(case.runtime.taps)

    def test_exit_requires_recognized_actual_planning_facility(self) -> None:
        with _case("supply_exit") as case:
            def recognize(frame, **_kwargs):
                return _screen(frame, recognized=frame_digest(frame) != case.identity.semantic_sha256)

            with patch.object(home, "recognize_supply_depot_screen", side_effect=recognize):
                with self.assertRaises(PerceptionBundleError):
                    case.dispatch()
            self.assertEqual(len(case.runtime.captures), 1)
            self.assertFalse(case.runtime.taps)

    def test_invalid_capture_boundaries_stop_before_capability_issuance(self) -> None:
        for kind in _KINDS:
            for boundary in ("equal_time", "backward_time", "equal_ordinal", "backward_ordinal",
                             "missing_ordinal", "different_session", "planning_transport_mismatch"):
                with self.subTest(kind=kind, boundary=boundary), _case(kind) as case, ExitStack() as patches:
                    if boundary in ("equal_time", "backward_time"):
                        case.runtime.capture_time_step = 0.0 if boundary == "equal_time" else -0.25
                    elif boundary in ("equal_ordinal", "backward_ordinal"):
                        case.runtime.ordinal -= 1 if boundary == "equal_ordinal" else 2
                    elif boundary == "missing_ordinal":
                        capture = case.runtime.capture

                        def capture_without_ordinal(label):
                            captured = capture(label)
                            del case.runtime.ordinal
                            return captured

                        patches.enter_context(patch.object(case.runtime, "capture", side_effect=capture_without_ordinal))
                    elif boundary == "different_session":
                        case.runtime.session = case.runtime.session / "different-session"
                        case.runtime.session.mkdir()
                    else:
                        case.identity = replace(case.identity, transport_sha256="f" * 64)
                    issue = patches.enter_context(patch.object(
                        case.policy, "issue_capability", wraps=case.policy.issue_capability,
                    ))
                    with self.assertRaises(PerceptionBundleError):
                        case.dispatch()
                    issue.assert_not_called()
                    self.assertFalse(case.runtime.taps)

    def test_executor_preserves_canonical_request_fields_from_issuance(self) -> None:
        for kind in _KINDS:
            with self.subTest(kind=kind), _case(kind) as case:
                builder_name = _BUILDERS[kind].replace("_observation", "_policy_request")
                builder = getattr(home, builder_name)
                built = []

                def build(**kwargs):
                    request = replace(builder(**kwargs), game_day_id=f"canonical-day-{len(built) + 1}")
                    built.append(request)
                    return request

                with patch.object(home, builder_name, side_effect=build):
                    issued, execution, _, _ = case.dispatch()
                self.assertTrue(issued.authorized)
                self.assertEqual(execution.status, ActionStatus.CONFIRMED)
                self.assertEqual(execution.transport_calls, 1)
                action = case.store.get_action(case.action_id)
                self.assertEqual(action["game_day_id"], built[0].game_day_id)
                self.assertEqual(action["source_frame_sha256"], case.identity.semantic_sha256)
                self.assertEqual(action["source_frame_captured_at"], case.planning.captured_monotonic)

    def test_unknown_actual_postcondition_never_confirms_or_repeats_transport(self) -> None:
        for kind in _KINDS:
            with self.subTest(kind=kind), _case(kind) as case:
                # Supply Exit needs recognized P/I and an independently unknown Home.
                case.successor_recognized = False
                with patch.object(home, "recognize_supply_depot_screen", side_effect=lambda frame, **_kwargs:
                                  _screen(frame, recognized=kind == "supply_exit")):
                    _, execution, _, telemetry = case.dispatch()
                self.assertEqual(execution.status, ActionStatus.UNRESOLVED)
                self.assertEqual(execution.transport_calls, 1)
                self.assertEqual(len(case.runtime.taps), 1)
                self.assertFalse(telemetry["completed"])
                self.assertEqual(case.store.get_action(case.action_id)["final_status"], ActionStatus.UNRESOLVED.value)


if __name__ == "__main__":
    unittest.main()
