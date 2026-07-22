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

    def __init__(self, count: int = 20) -> None:
        self.session = Path("centralized-nova-test-session")
        self.in_flight_action = None
        self.index = 0
        self.labels: list[str] = []
        self.taps: list[tuple[str, dict[str, object]]] = []
        self.reconciliations: list[tuple[str, str]] = []
        self.frames = [
            CapturedNativeFrame(
                np.full((1280, 800, 3), ordinal, dtype=np.uint8),
                b"png",
                f"{ordinal + 1:064x}",
                float(ordinal + 1),
                Path(f"central-{ordinal + 1}.png"),
            )
            for ordinal in range(count)
        ]

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

    def test_live_boundary_prepares_dispatches_and_confirms_exact_decrement(self) -> None:
        proposal_capture, proposal = self.armed_proposal()
        result = self.boundary(
            recognition(praise_observation(6, 2.0, digest="b" * 64)),
            recognition(praise_observation(6, 3.0, digest="c" * 64)),
            recognition(
                praise_observation(
                    5,
                    4.0,
                    enabled=False,
                    cooldown=278,
                    digest="d" * 64,
                )
            ),
        ).execute_praise(proposal_capture, proposal)
        self.assertEqual(result.status, "confirmed")
        self.assertEqual((result.attempts_before, result.attempts_after), (6, 5))
        self.assertEqual(result.transport_calls, 1)
        self.assertEqual(len(self.runtime.taps), 1)
        self.assertTrue(result.operational_state_mutated)
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

    def test_duplicate_and_mismatched_attempts_never_redispatch(self) -> None:
        proposal_capture, proposal = self.armed_proposal()
        boundary = self.boundary(
            recognition(praise_observation(6, 2.0, digest="b" * 64)),
            recognition(praise_observation(6, 3.0, digest="c" * 64)),
            recognition(praise_observation(5, 4.0, enabled=False, cooldown=278, digest="d" * 64)),
        )
        first = boundary.execute_praise(proposal_capture, proposal)
        second = boundary.execute_praise(proposal_capture, proposal)
        self.assertEqual(first.status, "confirmed")
        self.assertEqual(second.reason, "existing_action_confirmed")
        self.assertEqual(len(self.runtime.taps), 1)

        other_runtime = FakeRuntime()
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
                    recognizer=RecognitionQueue(
                        recognition(praise_observation(5, 2.0, digest="e" * 64))
                    ),
                    monotonic_clock=lambda: 3.25,
                    wall_clock=lambda: 100.5,
                    post_delays=(0.0,),
                )
                with self.assertRaisesRegex(ValueError, "attempts differ"):
                    other.execute_praise(
                        other_capture,
                        recognition(praise_observation(6, 1.0)),
                    )
                self.assertEqual(other_runtime.taps, [])
                self.assertEqual(other_store.list_actions_for_task(NOVA_TASK_ID), [])
            finally:
                other_store.close()

    def test_ambiguous_postcondition_is_unresolved_without_scheduler_update(self) -> None:
        proposal_capture, proposal = self.armed_proposal()
        result = self.boundary(
            recognition(praise_observation(6, 2.0, digest="b" * 64)),
            recognition(praise_observation(6, 3.0, digest="c" * 64)),
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
        boundary = self.boundary(
            recognition(praise_observation(6, 2.0, digest="b" * 64)),
            recognition(praise_observation(6, 3.0, digest="c" * 64)),
        )
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
