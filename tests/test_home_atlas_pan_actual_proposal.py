"""Real Home localization and dispatch fences verify a retained native camera pan."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Iterator
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from safe_action_core import ActionStatus, SafetyStore
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts import home_atlas_bluestacks as home
from tasks.home_atlas_planner import DirectPanNavigator, PanProgress, PlanDisposition
from tasks.home_atlas_vision import frame_digest
from tasks.perception_bundle import PerceptionBundleError
from tests.support.home_atlas import _RecordingPolicy
from tests.ocr_memo import install_module_memo
from tests.support.environment import requires_tesseract


def setUpModule():
    # Identical frames are replayed across tests; run real Tesseract once per unique input.
    install_module_memo()


ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "tasks/assets/home_atlas/bluestacks/800x1280/atlas.json"
FIXTURES = ROOT / "tests/fixtures/research_lab_home_entry"
INITIAL = "initial-safe-subregion.png"
SETTLED = "fully-visible-after-pan.png"


class _NativeFixtureRuntime:
    """Each capture is a new event; fixture pixels and PNG bytes are unchanged."""

    execute = True
    in_flight_action = None

    def __init__(self, session: Path) -> None:
        self.session = session
        self.ordinal = 0
        self.now = 100.0
        self.issuance_step = 0.25
        self.post_fixture: str | None = SETTLED
        self.captures: list[tuple[str, CapturedNativeFrame]] = []
        self.swipes: list[tuple[CapturedNativeFrame, dict[str, object]]] = []

    def capture(self, label: str) -> CapturedNativeFrame:
        self.ordinal += 1
        self.now += self.issuance_step if label == "navigate-pan-pre-dispatch" else 0.25
        fixture = self.post_fixture if label == "native-pan-settled" else INITIAL
        if fixture is None:
            frame = np.zeros((1280, 800, 3), dtype=np.uint8)
            ok, encoded = cv2.imencode(".png", frame)
            assert ok
            png = encoded.tobytes()
        else:
            png = (FIXTURES / fixture).read_bytes()
            frame = cv2.imread(str(FIXTURES / fixture))
        path = self.session / f"{self.ordinal:04d}-{label}.png"
        path.write_bytes(png)
        captured = CapturedNativeFrame(frame, png, hashlib.sha256(png).hexdigest(), self.now, path)
        self.captures.append((label, captured))
        return captured

    def swipe(self, captured: CapturedNativeFrame, **gesture: object) -> None:
        self.swipes.append((captured, gesture))

    def clock(self) -> float:
        return self.now + 0.01


class _PanCase:
    def __init__(self, directory: Path, atlas, localizer) -> None:
        self.runtime = _NativeFixtureRuntime(directory)
        self.planning = self.runtime.capture("native-pan-planning")
        self.identity = home.identity_from_captured(
            self.planning, session_id=str(directory), ordinal=self.runtime.ordinal,
            label="native-pan-planning",
        )
        self.before_localization = localizer.localize(self.planning.frame)
        self.localizer = localizer
        safe, calibration = home.bluestacks_direct_pan_contract()
        self.navigator = DirectPanNavigator(atlas, "home.building.research_lab", safe, calibration)
        self.plan = self.navigator.plan(self.before_localization)
        self.policy = _RecordingPolicy()
        self.store = SafetyStore(directory / "pan-safety.sqlite3")
        self.store.acquire_lease("owner", 1000.0, 100.0)
        self.progress = None
        self.post_calls = 0

    def post_pan_observer(self):
        self.post_calls += 1
        captured = self.runtime.capture("native-pan-settled")
        identity = home.identity_from_captured(
            captured, session_id=str(self.runtime.session), ordinal=self.runtime.ordinal,
            label="native-pan-settled",
        )
        after = self.localizer.localize(captured.frame)
        self.progress = self.navigator.record_progress(self.before_localization, after)
        return captured, identity, self.progress

    def dispatch(self, *, observer=True, post_observer=None):
        return home.dispatch_verified_navigate_pan(
            runtime=self.runtime, immediate_before=self.planning, identity=self.identity,
            drag_start=self.plan.drag_start, drag_end=self.plan.drag_end,
            action_id="native-home-pan", action_key="native-home-pan-key",
            task_id=home.SUPPLY_DEPOT_ROUTE_TASK_ID, navigation_session_id="native-home-pan-session",
            lease_owner="owner", policy=self.policy, store=self.store,
            monotonic_clock=self.runtime.clock, wall_clock=lambda: 1000.0,
            post_pan_observer=(post_observer or self.post_pan_observer) if observer else None,
        )


class HomeAtlasActualPanProposalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.atlas = home.load_home_atlas(ATLAS)
        cls.localizer = home.BlueStacksHomeLocalizer(cls.atlas, ATLAS)

    @contextmanager
    def case(self, *, native_ocr=False) -> Iterator[_PanCase]:
        with tempfile.TemporaryDirectory() as directory:
            case = _PanCase(Path(directory), self.atlas, self.localizer)
            try:
                self.assertTrue(case.before_localization.recognized)
                self.assertEqual(case.plan.disposition, PlanDisposition.PAN)
                self.assertEqual(case.plan.drag_start, (450, 500))
                self.assertEqual(case.plan.drag_end, (511, 573))
                if native_ocr:
                    yield case
                else:
                    with patch.object(home, "is_clean_home_frame", return_value=True):
                        yield case
            finally:
                case.store.close()

    @requires_tesseract
    def test_native_pan_preserves_actual_proposal_issuance_and_measured_post_capture(self) -> None:
        with self.case(native_ocr=True) as case:
            issued, execution, immediate, telemetry = case.dispatch()
            self.assertTrue(issued.authorized)
            self.assertEqual(execution.status, ActionStatus.CONFIRMED)
            self.assertEqual(execution.transport_calls, 1)
            self.assertEqual(len(case.runtime.swipes), 1)
            fresh = case.runtime.captures[1][1]
            self.assertIs(case.runtime.swipes[0][0], fresh)
            self.assertEqual(case.runtime.swipes[0][1]["start"], (450, 500))
            self.assertEqual(case.runtime.swipes[0][1]["end"], (511, 573))
            self.assertEqual(immediate.frame_sha256, frame_digest(fresh.frame))
            self.assertEqual(immediate.capture_completed_monotonic, fresh.captured_monotonic)
            self.assertTrue(any(request.policy_phase == "pre_dispatch" and request.observation is immediate
                                for request in case.policy.requests))
            action = case.store.get_action("native-home-pan")
            self.assertEqual(action["source_frame_sha256"], case.identity.semantic_sha256)
            self.assertEqual(action["source_frame_captured_at"], case.planning.captured_monotonic)
            self.assertLess(action["source_frame_captured_at"], immediate.capture_completed_monotonic)
            self.assertTrue(case.progress.accepted)
            self.assertAlmostEqual(case.progress.progress_px, 171.26, delta=1.0)
            self.assertEqual(case.post_calls, 1)
            self.assertEqual(len(case.runtime.captures), 3)
            settled = case.runtime.captures[-1][1]
            self.assertIs(telemetry["settled"], settled)
            self.assertEqual(telemetry["settled_identity"].semantic_sha256, frame_digest(settled.frame))
            self.assertEqual(telemetry["settled_identity"].capture_completed_monotonic, settled.captured_monotonic)
            self.assertNotEqual(telemetry["settled_identity"].semantic_sha256, case.identity.semantic_sha256)
            self.assertTrue(telemetry["verified"])
            self.assertEqual(json.loads(action["reconciliation_result_json"])["frame_sha256"], frame_digest(settled.frame))

    def test_stale_actual_proposal_is_not_replaced_by_fresh_issuance(self) -> None:
        with self.case() as case:
            case.runtime.now += 40.0
            issued, execution, immediate, _ = case.dispatch()
            self.assertTrue(issued.authorized)
            self.assertEqual(execution.status, ActionStatus.CANCELLED)
            self.assertEqual(execution.transport_calls, 0)
            self.assertFalse(case.runtime.swipes)
            self.assertEqual(case.post_calls, 0)
            self.assertGreater(immediate.capture_completed_monotonic, case.planning.captured_monotonic + 30.0)
            self.assertTrue(any(request.observation.capture_completed_monotonic == case.planning.captured_monotonic
                                for request in case.policy.requests))

    def test_equal_planning_and_issuance_times_cannot_dispatch(self) -> None:
        with self.case() as case:
            case.runtime.issuance_step = 0.0
            with patch.object(case.policy, "issue_capability", wraps=case.policy.issue_capability) as issue:
                with self.assertRaises(PerceptionBundleError):
                    case.dispatch()
            issue.assert_not_called()
            self.assertFalse(case.runtime.swipes)
            self.assertEqual(case.post_calls, 0)

    def test_invalid_capture_boundaries_stop_before_capability_issuance(self) -> None:
        for boundary in ("backward_time", "equal_ordinal", "backward_ordinal", "missing_ordinal",
                         "different_session", "planning_transport_mismatch"):
            with self.subTest(boundary=boundary), self.case() as case, ExitStack() as patches:
                if boundary == "backward_time":
                    case.runtime.issuance_step = -0.25
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
                self.assertFalse(case.runtime.swipes)
                self.assertEqual(case.post_calls, 0)

    def test_executor_preserves_canonical_request_fields_from_issuance(self) -> None:
        with self.case() as case:
            builder = home.build_navigate_pan_policy_request
            built = []

            def build(**kwargs):
                request = replace(builder(**kwargs), game_day_id=f"canonical-day-{len(built) + 1}")
                built.append(request)
                return request

            with patch.object(home, "build_navigate_pan_policy_request", side_effect=build):
                issued, execution, _, _ = case.dispatch()
            self.assertTrue(issued.authorized)
            self.assertEqual(execution.status, ActionStatus.CONFIRMED)
            self.assertEqual(execution.transport_calls, 1)
            action = case.store.get_action("native-home-pan")
            self.assertEqual(action["game_day_id"], built[0].game_day_id)
            self.assertEqual(action["source_frame_sha256"], case.identity.semantic_sha256)
            self.assertEqual(action["source_frame_captured_at"], case.planning.captured_monotonic)

    def test_missing_post_observer_stops_before_issuance_or_input(self) -> None:
        with self.case() as case:
            with self.assertRaises(ValueError):
                case.dispatch(observer=False)
            self.assertEqual(len(case.runtime.captures), 1)
            self.assertFalse(case.policy.requests)
            self.assertFalse(case.runtime.swipes)

    def test_repeated_native_post_viewport_is_unresolved_after_one_swipe(self) -> None:
        with self.case() as case:
            case.runtime.post_fixture = INITIAL
            _, execution, _, telemetry = case.dispatch()
            self.assertFalse(case.progress.accepted)
            self.assertEqual(case.progress.reason, "repeated_viewport")
            self.assertEqual(execution.status, ActionStatus.UNRESOLVED)
            self.assertEqual(execution.transport_calls, 1)
            self.assertEqual(len(case.runtime.swipes), 1)
            self.assertEqual(case.post_calls, 1)
            self.assertFalse(telemetry["verified"])
            self.assertEqual(case.store.get_action("native-home-pan")["final_status"], ActionStatus.UNRESOLVED.value)

    @requires_tesseract
    def test_unknown_actual_post_image_rejects_claimed_progress_after_one_swipe(self) -> None:
        with self.case(native_ocr=True) as case:
            case.runtime.post_fixture = None

            def unknown_post_with_claimed_progress():
                case.post_calls += 1
                captured = case.runtime.capture("native-pan-settled")
                identity = home.identity_from_captured(
                    captured, session_id=str(case.runtime.session), ordinal=case.runtime.ordinal,
                    label="native-pan-settled",
                )
                return captured, identity, PanProgress(
                    True, "measured_progress", (1.0, 0.0), (1.0, 0.0), (0.0, 0.0), 1.0,
                )

            _, execution, _, telemetry = case.dispatch(post_observer=unknown_post_with_claimed_progress)
            self.assertEqual(execution.status, ActionStatus.UNRESOLVED)
            self.assertEqual(execution.transport_calls, 1)
            self.assertEqual(len(case.runtime.swipes), 1)
            self.assertEqual(case.post_calls, 1)
            self.assertEqual(len(case.runtime.captures), 3)
            self.assertIs(telemetry["settled"], case.runtime.captures[-1][1])
            self.assertFalse(telemetry["verified"])
            self.assertEqual(case.store.get_action("native-home-pan")["final_status"], ActionStatus.UNRESOLVED.value)

    def test_actual_planning_capture_cannot_be_reused_as_post_evidence(self) -> None:
        with self.case() as case:
            def stale_post():
                case.post_calls += 1
                return case.planning, case.identity, None

            _, execution, _, telemetry = case.dispatch(post_observer=stale_post)
            self.assertEqual(execution.status, ActionStatus.UNRESOLVED)
            self.assertEqual(execution.reason, "postcondition_observation_failure")
            self.assertEqual(execution.transport_calls, 1)
            self.assertEqual(len(case.runtime.swipes), 1)
            self.assertEqual(case.post_calls, 1)
            self.assertEqual(len(case.runtime.captures), 2)
            self.assertNotIn("settled", telemetry)
            self.assertEqual(case.store.get_action("native-home-pan")["final_status"], ActionStatus.UNRESOLVED.value)

    def test_clean_home_requires_typed_finite_positive_pan_measurement(self) -> None:
        measured = PanProgress(True, "measured_progress", (1.0, 0.0), (1.0, 0.0), (0.0, 0.0), 1.0)
        for name, invalid in (
            ("bare_boolean", True),
            ("zero_vector", replace(measured, measured_camera_displacement=(0.0, 0.0))),
            ("nonfinite_vector", replace(measured, measured_camera_displacement=(float("nan"), 0.0))),
            ("mismatched_norm", replace(measured, progress_px=2.0)),
            ("zero_progress", replace(measured, progress_px=0.0)),
            ("nonfinite_progress", replace(measured, progress_px=float("inf"))),
        ):
            with self.subTest(measurement=name), self.case() as case:
                def actual_home_with_invalid_measurement():
                    case.post_calls += 1
                    captured = case.runtime.capture("native-pan-settled")
                    identity = home.identity_from_captured(
                        captured, session_id=str(case.runtime.session), ordinal=case.runtime.ordinal,
                        label="native-pan-settled",
                    )
                    return captured, identity, invalid

                _, execution, _, telemetry = case.dispatch(post_observer=actual_home_with_invalid_measurement)
                self.assertEqual(execution.status, ActionStatus.UNRESOLVED)
                self.assertEqual(execution.transport_calls, 1)
                self.assertEqual(len(case.runtime.swipes), 1)
                self.assertEqual(case.post_calls, 1)
                self.assertFalse(telemetry.get("verified", False))
                self.assertEqual(case.store.get_action("native-home-pan")["final_status"], ActionStatus.UNRESOLVED.value)


if __name__ == "__main__":
    unittest.main()
