"""Focused action-boundary and production-path replay tests for Nova Praise."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from safe_action_core import SafetyStore
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.nova_praise_centralized import (
    NovaActionIdentity,
    NovaPraiseActionBoundary,
)
from tasks.gameplay_flow_replay import ReplayNativeRuntime, load_retained_native_frame
from tasks.home_atlas import load_home_atlas
from tasks.nova_praise import NOVA_PRAISE_TARGET, NOVA_SCREEN, NovaPraiseObservation
from tasks.nova_praise_pulse import NOVA_TASK_ID, NovaPulseController
from tasks.nova_praise_vision import (
    NOVA_PRAISE_ROI,
    NovaFrameRecognition,
    recognize_nova_frame,
)
from tasks.scheduler_task_result import SchedulerIdentity


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "fixtures" / "nova_praise_replay" / "manifest.json"
IDENTITY = SchedulerIdentity("account-1", "server-1", "reset-1", NOVA_TASK_ID)


def _synthetic_nova_frame(
    base_value: int = 7,
    *,
    praise_button_present: bool = True,
) -> np.ndarray:
    """Native 800x1280 frame; optional red Praise ROI for fast revalidation."""

    frame = np.full((1280, 800, 3), base_value, dtype=np.uint8)
    if praise_button_present:
        x0, y0, x1, y1 = NOVA_PRAISE_ROI
        frame[y0:y1, x0:x1] = (0, 0, 255)
    return frame


def praise_observation(
    attempts: int,
    captured: float,
    *,
    enabled: bool = True,
    cooldown: int | None = None,
    digest: str = "a" * 64,
) -> NovaPraiseObservation:
    return NovaPraiseObservation(
        screen_state=NOVA_SCREEN,
        research_lab_identity=True,
        nova_control_visible=False,
        selected_nova=True,
        praise_enabled=enabled,
        praise_target_identity=NOVA_PRAISE_TARGET if enabled else "",
        praise_target_roi=NOVA_PRAISE_ROI,
        attempts_remaining=attempts,
        cooldown_active=cooldown is not None,
        cooldown_seconds=cooldown,
        next_eligible_at=captured + cooldown if cooldown is not None else None,
        frame_sha256=digest,
        captured_monotonic=captured,
        overlay_state="none_observed",
        recognized=True,
    )


def recognition(observation: NovaPraiseObservation) -> NovaFrameRecognition:
    targets = (
        ((NOVA_PRAISE_TARGET, NOVA_PRAISE_ROI),)
        if observation.praise_enabled
        else ()
    )
    return NovaFrameRecognition(observation, observation.frame_sha256, targets, {})


class FakeRuntime:
    execute = True
    dispatches_transport = True

    def __init__(
        self,
        count: int = 20,
        *,
        varying_pixels: bool = False,
        foreground_package: str | None = None,
        praise_button_present: bool = True,
    ) -> None:
        from scripts.bluestacks_flow_collector import EXPECTED_PACKAGE

        self.session = Path("centralized-nova-test-session")
        self.in_flight_action = None
        self.index = 0
        self.labels: list[str] = []
        self.taps: list[tuple[str, dict[str, object]]] = []
        self.reconciliations: list[tuple[str, str]] = []
        self.foreground_package = (
            EXPECTED_PACKAGE if foreground_package is None else foreground_package
        )
        # varying_pixels simulates decorative button animation across successive captures.
        # Immediate-before issuance must not require a second live capture for that drift.
        # praise_button_present paints NOVA_PRAISE_ROI red so fast immediate revalidation
        # can corroborate the fixed Praise control without OCR.
        self.frames = [
            CapturedNativeFrame(
                _synthetic_nova_frame(
                    ordinal if varying_pixels else 7,
                    praise_button_present=praise_button_present,
                ),
                b"png",
                f"{ordinal + 1:064x}",
                float(ordinal + 1),
                Path(f"central-{ordinal + 1}.png"),
            )
            for ordinal in range(count)
        ]

    def measure_foreground_package(self) -> str:
        return self.foreground_package

    def capture(self, label: str) -> CapturedNativeFrame:
        self.labels.append(label)
        result = self.frames[self.index]
        self.index += 1
        return result

    def tap(self, source: CapturedNativeFrame, **kwargs) -> None:
        self.taps.append((source.sha256, kwargs))
        if kwargs.get("consequential"):
            self.in_flight_action = kwargs["action_key"]

    def reconcile(self, action_key: str, status: str, _post, _reason: str) -> None:
        if self.in_flight_action != action_key:
            raise RuntimeError("local evidence correlation does not match central action")
        self.reconciliations.append((action_key, status))
        if status != "unresolved":
            self.in_flight_action = None


class RecognitionQueue:
    def __init__(self, *items: NovaFrameRecognition) -> None:
        self.items = list(items)

    def __call__(self, *_args, **_kwargs) -> NovaFrameRecognition:
        if not self.items:
            raise AssertionError("unexpected recognition call")
        return self.items.pop(0)


def pulse(*, replay: bool) -> NovaPulseController:
    return NovaPulseController(
        IDENTITY,
        load_home_atlas(
            ROOT
            / "tasks"
            / "assets"
            / "home_atlas"
            / "bluestacks"
            / "800x1280"
            / "atlas.json"
        ),
        now=1.0,
        replay_mode=replay,
    )


class CentralizedNovaBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = SafetyStore(Path(self.temp.name) / "actions.sqlite3")
        self.store.acquire_lease("owner", 100.0, 600.0)
        self.runtime = FakeRuntime()

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def boundary(
        self,
        *items: NovaFrameRecognition,
        execute: bool = True,
        runtime=None,
        pulse_controller: NovaPulseController | None = None,
    ) -> NovaPraiseActionBoundary:
        selected_runtime = runtime or self.runtime
        return NovaPraiseActionBoundary(
            selected_runtime,
            self.store,
            pulse_controller or pulse(replay=not execute),
            runtime_scope="bluestacks-dev-primary",
            owner_id="owner",
            invocation_id="invocation-1",
            execute=execute,
            recognizer=RecognitionQueue(*items) if items else recognize_nova_frame,
            monotonic_clock=(
                (lambda: 101.25)
                if getattr(selected_runtime, "dispatches_transport", True) is False
                else (lambda: 3.25)
            ),
            wall_clock=lambda: 100.5,
            post_delays=(0.0,),
        )

    def armed_proposal(self, attempts: int = 6) -> tuple[CapturedNativeFrame, NovaFrameRecognition]:
        captured = self.runtime.capture("proposal")
        return captured, recognition(
            praise_observation(attempts, captured.captured_monotonic)
        )

    def test_runtime_scope_is_part_of_durable_action_identity(self) -> None:
        primary = NovaActionIdentity(IDENTITY, "bluestacks-dev-primary", "invocation-1", 6)
        secondary = NovaActionIdentity(IDENTITY, "bluestacks-dev-secondary", "invocation-1", 6)
        self.assertNotEqual(primary.action_key, secondary.action_key)

    def _success_recognitions(
        self,
        *,
        attempts_before: int = 6,
    ) -> tuple[NovaFrameRecognition, ...]:
        # Post frame only. Immediate-before uses fast revalidation against the proposal.
        return (
            recognition(
                praise_observation(
                    attempts_before - 1,
                    4.0,
                    enabled=False,
                    cooldown=278,
                    digest="d" * 64,
                )
            ),
        )

    def test_live_boundary_prepares_dispatches_and_confirms_exact_decrement(self) -> None:
        proposal_capture, proposal = self.armed_proposal()
        result = self.boundary(*self._success_recognitions()).execute_praise(
            proposal_capture, proposal
        )
        self.assertEqual(result.status, "confirmed")
        self.assertEqual((result.attempts_before, result.attempts_after), (6, 5))
        self.assertEqual(result.transport_calls, 1)
        self.assertEqual(len(self.runtime.taps), 1)
        self.assertTrue(result.operational_state_mutated)
        self.assertIn("praise-central-immediate-before", self.runtime.labels)
        self.assertNotIn("praise-central-pre-dispatch", self.runtime.labels)
        self.assertEqual(
            self.runtime.labels.count("praise-central-immediate-before"),
            1,
        )
        transitions = [
            event["lifecycle_to"]
            for event in self.store.audit_events(result.action_id)
            if event["event_type"] == "action_transition"
        ]
        self.assertEqual(transitions, ["prepared", "input_sent", "confirmed"])
        scheduler = self.store.get_scheduler_invocation_state(
            IDENTITY.account_id,
            IDENTITY.server_id,
            IDENTITY.reset_id,
            IDENTITY.task_id,
        )
        self.assertEqual(scheduler["status"], "deferred")

    def test_planning_frame_never_mints_capability(self) -> None:
        proposal_capture, proposal = self.armed_proposal()
        boundary = self.boundary(*self._success_recognitions())
        issued_digests: list[str] = []
        original_issue = None
        from safe_action_core import CentralPolicy
        from unittest.mock import patch

        real_issue = CentralPolicy.issue_capability

        def tracking_issue(self_policy, request):
            issued_digests.append(request.observation.frame_sha256)
            return real_issue(self_policy, request)

        with patch.object(CentralPolicy, "issue_capability", tracking_issue):
            result = boundary.execute_praise(proposal_capture, proposal)
        self.assertEqual(result.status, "confirmed")
        self.assertEqual(issued_digests, [self.runtime.frames[1].sha256])
        self.assertNotEqual(proposal_capture.sha256, issued_digests[0])

    def test_issue_proposal_and_consume_share_immediate_capture_identity(self) -> None:
        proposal_capture, proposal = self.armed_proposal()
        boundary = self.boundary(*self._success_recognitions())
        frames: list[str] = []
        monos: list[float] = []
        original_request = boundary._request

        def tracking_request(action, observation, *, phase: str = "proposal"):
            frames.append(observation.frame_sha256)
            monos.append(observation.capture_completed_monotonic)
            return original_request(action, observation, phase=phase)

        from unittest.mock import patch

        with patch.object(boundary, "_request", side_effect=tracking_request):
            result = boundary.execute_praise(proposal_capture, proposal)
        self.assertEqual(result.status, "confirmed")
        # issue uses immediate mono; executor proposal is predecessor offset of same digest.
        self.assertGreaterEqual(len(frames), 2)
        self.assertEqual(frames[0], frames[1])
        self.assertEqual(frames[0], self.runtime.frames[1].sha256)
        self.assertAlmostEqual(monos[1], monos[0] - 0.05)
        self.assertEqual(result.transport_calls, 1)
        self.assertEqual(len(self.runtime.taps), 1)
        self.assertEqual(self.runtime.taps[0][0], frames[0])

    def test_animated_decorative_pixels_do_not_force_second_capture(self) -> None:
        self.runtime = FakeRuntime(varying_pixels=True)
        proposal_capture, proposal = self.armed_proposal()
        result = self.boundary(*self._success_recognitions()).execute_praise(
            proposal_capture, proposal
        )
        self.assertEqual(result.status, "confirmed")
        self.assertEqual(result.transport_calls, 1)
        self.assertEqual(len(self.runtime.taps), 1)
        self.assertEqual(
            [label for label in self.runtime.labels if label.startswith("praise-central-")],
            ["praise-central-immediate-before", "praise-central-post-1"],
        )

    def test_at_most_one_praise_transport(self) -> None:
        proposal_capture, proposal = self.armed_proposal()
        result = self.boundary(*self._success_recognitions()).execute_praise(
            proposal_capture, proposal
        )
        self.assertEqual(result.status, "confirmed")
        self.assertEqual(result.transport_calls, 1)
        self.assertEqual(len(self.runtime.taps), 1)
        self.assertEqual(self.runtime.labels.count("praise-central-immediate-before"), 1)

    def test_confirmed_seven_to_six_decrement_path(self) -> None:
        proposal_capture, proposal = self.armed_proposal(attempts=7)
        result = self.boundary(
            *self._success_recognitions(attempts_before=7)
        ).execute_praise(proposal_capture, proposal)
        self.assertEqual(result.status, "confirmed")
        self.assertEqual((result.attempts_before, result.attempts_after), (7, 6))
        self.assertEqual(result.transport_calls, 1)

    def test_stale_immediate_frame_zero_transport(self) -> None:
        proposal_capture, proposal = self.armed_proposal()
        clock = {"now": 3.25}

        def advancing_clock() -> float:
            return clock["now"]

        boundary = NovaPraiseActionBoundary(
            self.runtime,
            self.store,
            pulse(replay=False),
            runtime_scope="bluestacks-dev-primary",
            owner_id="owner",
            invocation_id="invocation-1",
            execute=True,
            recognizer=RecognitionQueue(*self._success_recognitions()),
            monotonic_clock=advancing_clock,
            wall_clock=lambda: 100.5,
            post_delays=(0.0,),
        )
        original_capture = self.runtime.capture

        def capture_and_age(label: str):
            frame = original_capture(label)
            if label == "praise-central-immediate-before":
                clock["now"] = frame.captured_monotonic + 5.0
            return frame

        self.runtime.capture = capture_and_age
        result = boundary.execute_praise(proposal_capture, proposal)
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.transport_calls, 0)
        self.assertEqual(self.runtime.taps, [])
        self.assertNotIn("CAPABILITY_CAPTURE_MISMATCH", result.reason)
        self.assertIn(
            result.reason,
            {"STALE_FRAME", "CAPABILITY_STALE_OBSERVATION"},
        )

    def test_package_mismatch_blocks_with_zero_transport(self) -> None:
        self.runtime = FakeRuntime(foreground_package="com.other.package")
        proposal_capture, proposal = self.armed_proposal()
        result = self.boundary().execute_praise(proposal_capture, proposal)
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.reason, "PACKAGE_FOREGROUND_MISMATCH")
        self.assertEqual(result.transport_calls, 0)
        self.assertIsNone(result.journal_status)
        self.assertEqual(self.runtime.taps, [])
        self.assertEqual(self.store.list_actions_for_task(NOVA_TASK_ID), [])

    def test_consume_remeasure_package_mismatch_blocks_with_zero_transport(self) -> None:
        proposal_capture, proposal = self.armed_proposal()
        boundary = self.boundary(*self._success_recognitions())
        packages = {"n": 0}
        from scripts.bluestacks_flow_collector import EXPECTED_PACKAGE

        def measure() -> str:
            packages["n"] += 1
            # First measure builds the issued immediate Observation; rebuild remeasures.
            if packages["n"] >= 2:
                return "com.other.package"
            return EXPECTED_PACKAGE

        self.runtime.measure_foreground_package = measure
        result = boundary.execute_praise(proposal_capture, proposal)
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.transport_calls, 0)
        self.assertEqual(self.runtime.taps, [])
        self.assertNotEqual(result.reason, "CAPABILITY_CAPTURE_MISMATCH")
        self.assertGreaterEqual(packages["n"], 2)

    def test_immediate_absent_praise_button_blocks_with_zero_transport(self) -> None:
        self.runtime = FakeRuntime(praise_button_present=False)
        proposal_capture, proposal = self.armed_proposal()
        result = self.boundary().execute_praise(proposal_capture, proposal)
        self.assertEqual(result.status, "blocked")
        self.assertTrue(result.reason.startswith("immediate_before_rejected:"))
        self.assertEqual(result.transport_calls, 0)
        self.assertIsNone(result.journal_status)
        self.assertEqual(self.runtime.taps, [])
        self.assertEqual(self.store.list_actions_for_task(NOVA_TASK_ID), [])

    def test_immediate_before_uses_fast_revalidation_not_full_ocr(self) -> None:
        proposal_capture, proposal = self.armed_proposal()
        calls = {"recognize": 0}
        boundary = NovaPraiseActionBoundary(
            self.runtime,
            self.store,
            pulse(replay=False),
            runtime_scope="bluestacks-dev-primary",
            owner_id="owner",
            invocation_id="invocation-1",
            execute=True,
            recognizer=RecognitionQueue(*self._success_recognitions()),
            monotonic_clock=lambda: 3.25,
            wall_clock=lambda: 100.5,
            post_delays=(0.0,),
        )
        original = boundary._recognize

        def tracked_recognize(captured):
            calls["recognize"] += 1
            return original(captured)

        boundary._recognize = tracked_recognize  # type: ignore[method-assign]
        from unittest.mock import patch

        def boom(*_args, **_kwargs):
            raise AssertionError("OCR must not run on immediate-before fast path")

        with patch("tasks.nova_praise_vision.pytesseract.image_to_string", boom), patch(
            "tasks.nova_praise_vision.pytesseract.image_to_data", boom
        ):
            result = boundary.execute_praise(proposal_capture, proposal)
        self.assertEqual(result.status, "confirmed")
        self.assertEqual(result.transport_calls, 1)
        # Full recognizer runs only for post-observe, never for immediate-before.
        self.assertEqual(calls["recognize"], 1)
        self.assertEqual((result.attempts_before, result.attempts_after), (6, 5))

    def test_immediate_profile_change_blocks_with_zero_transport(self) -> None:
        proposal_capture, proposal = self.armed_proposal()
        bad = CapturedNativeFrame(
            np.full((640, 400, 3), 7, dtype=np.uint8),
            b"png",
            "c" * 64,
            2.0,
            Path("central-non-native.png"),
        )
        original = self.runtime.capture

        def capture_non_native(label: str):
            if label == "praise-central-immediate-before":
                self.runtime.labels.append(label)
                return bad
            return original(label)

        self.runtime.capture = capture_non_native
        with self.assertRaisesRegex(ValueError, "native 800x1280"):
            self.boundary().execute_praise(proposal_capture, proposal)
        self.assertEqual(self.runtime.taps, [])
        self.assertEqual(self.store.list_actions_for_task(NOVA_TASK_ID), [])

    def test_proposal_paid_surface_blocks_with_zero_transport(self) -> None:
        proposal_capture, proposal = self.armed_proposal()
        paid = NovaFrameRecognition(
            proposal.observation,
            proposal.frame_sha256,
            proposal.targets,
            {"body_text": "confirm purchase premium"},
        )
        with self.assertRaisesRegex(ValueError, "paid"):
            self.boundary(*self._success_recognitions()).execute_praise(
                proposal_capture, paid
            )
        self.assertEqual(self.runtime.taps, [])
        self.assertEqual(self.store.list_actions_for_task(NOVA_TASK_ID), [])

    def test_capability_denial_before_prepare_returns_blocked_without_store_error(self) -> None:
        proposal_capture, proposal = self.armed_proposal()
        # Immediate frame mono ~2.0; clock far ahead forces STALE_FRAME at issue time.
        boundary = NovaPraiseActionBoundary(
            self.runtime,
            self.store,
            pulse(replay=False),
            runtime_scope="bluestacks-dev-primary",
            owner_id="owner",
            invocation_id="invocation-1",
            execute=True,
            recognizer=RecognitionQueue(),
            monotonic_clock=lambda: 20.0,
            wall_clock=lambda: 100.5,
            post_delays=(0.0,),
        )
        result = boundary.execute_praise(proposal_capture, proposal)
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.reason, "STALE_FRAME")
        self.assertEqual(result.transport_calls, 0)
        self.assertIsNone(result.journal_status)
        self.assertEqual(self.store.list_actions_for_task(NOVA_TASK_ID), [])
        self.assertFalse(self.store.has_action_block())
        self.assertEqual(self.runtime.taps, [])
        self.assertEqual(
            self.runtime.labels,
            ["proposal", "praise-central-immediate-before"],
        )

    def test_duplicate_and_mismatched_attempts_never_redispatch(self) -> None:
        proposal_capture, proposal = self.armed_proposal()
        boundary = self.boundary(*self._success_recognitions())
        first = boundary.execute_praise(proposal_capture, proposal)
        second = boundary.execute_praise(proposal_capture, proposal)
        self.assertEqual(first.status, "confirmed")
        self.assertEqual(second.reason, "existing_action_confirmed")
        self.assertEqual(len(self.runtime.taps), 1)
        self.assertEqual(first.transport_calls, 1)

        other_runtime = FakeRuntime(praise_button_present=False)
        other_capture = other_runtime.capture("proposal")
        with tempfile.TemporaryDirectory() as directory:
            other_store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                other_store.acquire_lease("owner", 100.0, 600.0)
                other = NovaPraiseActionBoundary(
                    other_runtime,
                    other_store,
                    pulse(replay=False),
                    runtime_scope="bluestacks-dev-primary",
                    owner_id="owner",
                    invocation_id="other",
                    execute=True,
                    recognizer=RecognitionQueue(),
                    monotonic_clock=lambda: 3.25,
                    wall_clock=lambda: 100.5,
                    post_delays=(0.0,),
                )
                blocked = other.execute_praise(
                    other_capture,
                    recognition(praise_observation(6, 1.0)),
                )
                self.assertEqual(blocked.status, "blocked")
                self.assertTrue(blocked.reason.startswith("immediate_before_rejected:"))
                self.assertEqual(blocked.transport_calls, 0)
                self.assertEqual(other_runtime.taps, [])
                self.assertEqual(other_store.list_actions_for_task(NOVA_TASK_ID), [])
            finally:
                other_store.close()

    def test_no_effect_cancelled_retry_supersedes_and_dispatches_once(self) -> None:
        proposal_capture, proposal = self.armed_proposal()
        seeded = self.boundary(
            *self._success_recognitions(),
            execute=False,
        ).execute_praise(proposal_capture, proposal)
        self.assertEqual(seeded.status, "dry-run")
        self.assertEqual(seeded.transport_calls, 0)
        self.assertEqual(self.store.get_action(seeded.action_id)["final_status"], "cancelled")

        self.runtime = FakeRuntime()
        retry_capture, retry_proposal = self.armed_proposal()
        retried = self.boundary(*self._success_recognitions()).execute_praise(
            retry_capture,
            retry_proposal,
        )

        self.assertEqual(retried.status, "confirmed")
        self.assertEqual(retried.transport_calls, 1)
        self.assertEqual(len(self.runtime.taps), 1)
        self.assertEqual(self.store.get_action(retried.action_id)["final_status"], "confirmed")
        self.assertTrue(
            any(
                event["event_type"] == "action_superseded"
                and event["action_id"] == retried.action_id
                for event in self.store.audit_events(retried.action_id)
            )
        )

    def test_input_sent_existing_action_still_blocks(self) -> None:
        proposal_capture, proposal = self.armed_proposal()
        original_mark_confirmed = self.store.mark_confirmed
        self.store.mark_confirmed = lambda *_args, **_kwargs: None
        try:
            seeded = self.boundary(*self._success_recognitions()).execute_praise(
                proposal_capture,
                proposal,
            )
        finally:
            self.store.mark_confirmed = original_mark_confirmed
        self.assertEqual(seeded.status, "confirmed")
        self.assertEqual(self.store.get_action(seeded.action_id)["final_status"], "input_sent")

        self.runtime = FakeRuntime()
        retry_capture, retry_proposal = self.armed_proposal()
        blocked = self.boundary(*self._success_recognitions()).execute_praise(
            retry_capture,
            retry_proposal,
        )
        self.assertEqual(blocked.status, "blocked")
        self.assertEqual(blocked.reason, "existing_action_input_sent")
        self.assertEqual(blocked.transport_calls, 0)
        self.assertEqual(self.runtime.taps, [])

    def test_ambiguous_postcondition_is_unresolved_without_scheduler_update(self) -> None:
        proposal_capture, proposal = self.armed_proposal()
        result = self.boundary(
            recognition(praise_observation(6, 4.0, digest="d" * 64)),
        ).execute_praise(proposal_capture, proposal)
        self.assertEqual(result.status, "unresolved")
        self.assertTrue(self.store.has_action_block())
        self.assertIsNone(
            self.store.get_scheduler_invocation_state(
                IDENTITY.account_id,
                IDENTITY.server_id,
                IDENTITY.reset_id,
                IDENTITY.task_id,
            )
        )

    def test_crash_after_transport_blocks_restart_redispatch(self) -> None:
        proposal_capture, proposal = self.armed_proposal()
        boundary = self.boundary()
        original_mark_input_sent = self.store.mark_input_sent
        original_mark_unresolved = self.store.mark_unresolved

        def simulate_process_death(*_args, **_kwargs):
            raise SystemExit("process terminated after transport")

        self.store.mark_input_sent = simulate_process_death
        self.store.mark_unresolved = simulate_process_death
        crashed = boundary.execute_praise(proposal_capture, proposal)
        self.assertEqual(crashed.status, "unresolved")
        self.assertEqual(crashed.reason, "persistence_failure_after_possible_dispatch")
        self.assertEqual(len(self.runtime.taps), 1)
        self.store.mark_input_sent = original_mark_input_sent
        self.store.mark_unresolved = original_mark_unresolved
        self.assertEqual(self.store.startup_reconcile(101.0), [crashed.action_id])
        restarted = self.boundary().execute_praise(proposal_capture, proposal)
        self.assertEqual(restarted.reason, "existing_action_unresolved")
        self.assertEqual(len(self.runtime.taps), 1)

    def test_cooldown_and_zero_no_dispatch_results_persist_only_live(self) -> None:
        cooldown = praise_observation(5, 1.0, enabled=False, cooldown=120)
        boundary = self.boundary()
        deferred = boundary.record_no_dispatch(cooldown, evidence_ref="cooldown.png")
        self.assertEqual(deferred.status, "deferred")
        self.assertEqual(deferred.transport_calls, 0)
        self.assertTrue(deferred.operational_state_mutated)
        self.store.close()
        self.store = SafetyStore(Path(self.temp.name) / "zero.sqlite3")
        self.store.acquire_lease("owner", 100.0, 600.0)
        complete = self.boundary().record_no_dispatch(
            praise_observation(0, 2.0, enabled=False),
            evidence_ref="zero.png",
        )
        self.assertEqual(complete.status, "complete_for_reset")
        self.assertEqual(self.runtime.taps, [])

    def test_retained_six_to_five_uses_production_path_with_zero_transport(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cases = {item["fixture_id"]: item for item in manifest["cases"]}
        before_case = cases["praise_attempts_available"]
        after_case = cases["praise_on_cooldown"]
        before = load_retained_native_frame(
            ROOT / before_case["path"],
            captured_monotonic=100.0,
            expected_sha256=before_case["sha256"],
        )
        after = load_retained_native_frame(
            ROOT / after_case["path"],
            captured_monotonic=101.0,
            expected_sha256=after_case["sha256"],
        )
        replay_runtime = ReplayNativeRuntime(Path(self.temp.name) / "replay")
        boundary = self.boundary(
            execute=False,
            runtime=replay_runtime,
            pulse_controller=pulse(replay=True),
        )
        result = boundary.replay_praise(before, after)
        self.assertEqual(result.status, "replay_confirmed")
        self.assertEqual((result.attempts_before, result.attempts_after), (6, 5))
        self.assertEqual(result.transport_calls, 0)
        self.assertEqual(replay_runtime.transport_calls, 0)
        self.assertEqual(len(replay_runtime.intended_inputs), 1)
        self.assertEqual(
            replay_runtime.intended_inputs[0].target_identity,
            NOVA_PRAISE_TARGET,
        )
        self.assertFalse(result.operational_state_mutated)
        self.assertEqual(self.store.list_actions_for_task(NOVA_TASK_ID), [])
        self.assertIsNone(
            self.store.get_scheduler_invocation_state(
                IDENTITY.account_id,
                IDENTITY.server_id,
                IDENTITY.reset_id,
                IDENTITY.task_id,
            )
        )

    def test_retained_cooldown_replay_does_not_persist_scheduler_state(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        case = next(
            item
            for item in manifest["cases"]
            if item["fixture_id"] == "praise_on_cooldown"
        )
        captured = load_retained_native_frame(
            ROOT / case["path"],
            captured_monotonic=101.0,
            expected_sha256=case["sha256"],
        )
        replay_runtime = ReplayNativeRuntime(Path(self.temp.name) / "cooldown-replay")
        boundary = self.boundary(
            execute=False,
            runtime=replay_runtime,
            pulse_controller=pulse(replay=True),
        )
        recognized = boundary._recognize(captured)
        result = boundary.replay_no_dispatch(
            recognized.observation,
            evidence_ref=str(captured.path),
        )
        self.assertEqual(result.status, "deferred")
        self.assertEqual(result.transport_calls, 0)
        self.assertEqual(replay_runtime.intended_inputs, [])
        self.assertFalse(result.operational_state_mutated)
        self.assertIsNone(
            self.store.get_scheduler_invocation_state(
                IDENTITY.account_id,
                IDENTITY.server_id,
                IDENTITY.reset_id,
                IDENTITY.task_id,
            )
        )


if __name__ == "__main__":
    unittest.main()
