"""Focused fake-based tests for the canonical runtime/perception boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
import tempfile
import unittest

from automation_service.actions import ActionExecutor, ActionOutcome, SuccessorConstraint
from automation_service.contracts import FlowSpec, PerceptionEnvelope, SemanticActionIntent
from automation_service.overlays import OverlayRecoveryManager
from automation_service.screens import (
    CaptureCycle,
    OverlayId,
    ScreenDefinition,
    ScreenId,
    ScreenObservation,
    ScreenRouter,
    TargetBinding,
)
from automation_service.state import ActionState, BotStateManager, DispatchValidation, RunState
from automation_service.session import RuntimeSession
from automation_service.adapters import FrameSample


FLOW_ID = "BOUNDARY-FLOW"
RESET_ID = "boundary-reset"
TARGET = "button:free"


@dataclass
class SequenceAdapter:
    frames: list[FrameSample]
    transport_result: object = True
    transport_error: Exception | None = None

    def __post_init__(self) -> None:
        self.index = 0
        self.transports: list[SemanticActionIntent] = []
        self.state_manager: BotStateManager | None = None

    def capture(self) -> FrameSample:
        sample = self.frames[min(self.index, len(self.frames) - 1)]
        self.index += 1
        return sample

    def execute(self, intent: SemanticActionIntent) -> object:
        self.transports.append(intent)
        if self.transport_error is not None:
            raise self.transport_error
        return self.transport_result


def frame(name: str, screen: str = "HOME", *, roi: tuple[int, int, int, int] = (10, 10, 30, 30), overlay: str | None = None, digest: str = "stable") -> FrameSample:
    return FrameSample(
        name,
        PerceptionEnvelope(name, screen.lower(), "native-800x1280", "fresh"),
        payload={"screen": screen, "roi": roi, "overlay": overlay, "digest": digest},
    )


def router() -> ScreenRouter:
    def recognize(cycle: CaptureCycle) -> ScreenObservation:
        payload = cycle.payload
        screen = ScreenId(payload["screen"])
        overlays = () if payload.get("overlay") is None else (OverlayId(payload["overlay"]),)
        targets = (
            TargetBinding(TARGET, payload["roi"], semantic_identity="free-button", stable_roi_digest=payload["digest"]),
        )
        if OverlayId.VIP_RESET in overlays:
            targets += (TargetBinding("overlay:vip-reset:close", (100, 100, 140, 140), semantic_identity="close", stable_roi_digest="close"),)
        return ScreenObservation(screen, overlays, cycle.frame_hash, 0.99, targets, cycle.capture_id, payload["digest"], ("fake",), "recognized", True)

    return ScreenRouter({ScreenId.HOME: recognize, ScreenId.DAILY: recognize})


def manager(path: Path) -> BotStateManager:
    value = BotStateManager(path, owner_instance_id="boundary-owner")
    value.initialize_flows([FlowSpec(FLOW_ID, cadence="manual")])
    value.set_service_enabled(True, now_utc_epoch=1.0)
    value.set_flow_enabled(FLOW_ID, True, now_utc_epoch=1.0)
    return value


def intent() -> SemanticActionIntent:
    return SemanticActionIntent(
        "tap_free",
        FLOW_ID,
        "HOME",
        "HOME successor",
        target_identity=TARGET,
        flow_id=FLOW_ID,
    )


class ScreenBoundaryTests(unittest.TestCase):
    def test_animation_hash_variance_preserves_stable_target_binding(self) -> None:
        target = TargetBinding(TARGET, (10, 10, 30, 30), "free-button", "stable")
        source = ScreenObservation(ScreenId.HOME, (), "a" * 64, 0.99, (target,), "capture-a", "stable", recognized=True)
        fresh = ScreenObservation(ScreenId.HOME, (), "b" * 64, 0.99, (target,), "capture-b", "stable", recognized=True)
        self.assertEqual(source.revalidate_target(fresh, TARGET), (True, "OK"))

    def test_changed_target_roi_is_stale_and_fails_closed(self) -> None:
        source_target = TargetBinding(TARGET, (10, 10, 30, 30), "free-button", "stable")
        fresh_target = TargetBinding(TARGET, (11, 10, 31, 30), "free-button", "stable")
        source = ScreenObservation(ScreenId.HOME, (), "a" * 64, 0.99, (source_target,), "a", recognized=True)
        fresh = ScreenObservation(ScreenId.HOME, (), "b" * 64, 0.99, (fresh_target,), "b", recognized=True)
        self.assertEqual(source.revalidate_target(fresh, TARGET), (False, "STALE_OR_CHANGED_TARGET_ROI"))

    def test_changed_source_roi_digest_is_stale_with_same_target_binding(self) -> None:
        target = TargetBinding(TARGET, (10, 10, 30, 30), "free-button", "stable-target")
        source = ScreenObservation(
            ScreenId.HOME,
            (),
            "a" * 64,
            0.99,
            (target,),
            "capture-a",
            "stable-source-a",
            recognized=True,
        )
        fresh = ScreenObservation(
            ScreenId.HOME,
            (),
            "b" * 64,
            0.99,
            (target,),
            "capture-b",
            "stable-source-b",
            recognized=True,
        )
        self.assertEqual(
            source.revalidate_target(fresh, TARGET),
            (False, "STALE_OR_CHANGED_SOURCE_ROI"),
        )

    def test_ocr_is_not_called_after_deadline(self) -> None:
        calls: list[str] = []
        router = ScreenRouter(
            [
                ScreenDefinition(
                    ScreenId.HOME,
                    template=lambda _cycle: True,
                    geometry=lambda _cycle: True,
                    ocr=lambda _cycle: calls.append("ocr") or {"screen": "HOME", "confidence": 1.0},
                )
            ],
            clock=lambda: 10.0,
        )
        observation = router.observe(CaptureCycle("capture", "a" * 64), deadline_monotonic=9.0)
        self.assertEqual(observation.reason_code, "RECOGNITION_DEADLINE")
        self.assertEqual(calls, [])

    def test_unknown_screen_is_typed_and_cached_by_capture_identity(self) -> None:
        router = ScreenRouter()
        cycle = CaptureCycle("capture", "a" * 64)
        first = router.observe(cycle)
        second = router.observe(cycle)
        self.assertIs(first, second)
        self.assertTrue(first.is_unknown)
        self.assertEqual(first.reason_code, "UNKNOWN_SCREEN")


class RuntimeBoundaryTests(unittest.TestCase):
    def _session(self, manager: BotStateManager, adapter: SequenceAdapter) -> RuntimeSession:
        session = RuntimeSession(manager, adapter, flow_id=FLOW_ID, reset_id=RESET_ID, max_inputs=2, max_actions=2)
        self.assertIsNotNone(session.claim())
        return session

    def test_stale_roi_blocks_without_transport(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                adapter = SequenceAdapter([frame("source", roi=(10, 10, 30, 30)), frame("pre", roi=(11, 10, 31, 30))])
                session = self._session(state, adapter)
                source = router().observe(session.capture("source"))
                executor = ActionExecutor(session, router())
                result = executor.execute(intent(), source=source)
                self.assertEqual(result.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(result.reason, "STALE_OR_CHANGED_TARGET_ROI")
                self.assertEqual(adapter.transports, [])
            finally:
                state.close()

    def test_changed_source_roi_same_target_blocks_without_transport(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                adapter = SequenceAdapter(
                    [
                        frame("source", digest="stable-source"),
                        frame("pre", digest="changed-source"),
                    ]
                )
                session = self._session(state, adapter)
                source = router().observe(session.capture("source"))
                result = ActionExecutor(session, router()).execute(intent(), source=source)
                self.assertEqual(result.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(result.reason, "STALE_OR_CHANGED_SOURCE_ROI")
                self.assertEqual(adapter.transports, [])
            finally:
                state.close()

    def test_pretransport_denials_terminalize_run_release_lease_and_allow_next_claim(self) -> None:
        """Every post-claim admission denial must leave no active ownership."""

        scenarios = (
            ("service disabled after claim", "service", "SERVICE_DISABLED"),
            ("stale target ROI", "stale-target", "STALE_OR_CHANGED_TARGET_ROI"),
            ("stale source ROI", "stale-source", "STALE_OR_CHANGED_SOURCE_ROI"),
            ("heartbeat exception", "heartbeat-exception", "HEARTBEAT_FAILED:RuntimeError"),
            ("heartbeat false", "heartbeat-false", "HEARTBEAT_FENCE_FAILED"),
            ("fence denial", "fence", "FENCE_DENIED"),
            ("reservation denial", "reservation", "RESERVATION_DENIED"),
            ("dispatch commit denial", "dispatch-commit", "DISPATCH_COMMIT_DENIED"),
        )
        active_states = {RunState.CLAIMED, RunState.RUNNING, RunState.STOP_REQUESTED, RunState.RECOVERING}
        future = 10_000_000_000.0

        for label, scenario, expected_reason in scenarios:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as folder:
                state = manager(Path(folder) / "state.sqlite3")
                try:
                    source: ScreenObservation | None = None
                    if scenario == "service":
                        class DisableOnPreDispatch(SequenceAdapter):
                            def capture(self) -> FrameSample:
                                sample = super().capture()
                                if self.index == 1:
                                    state.set_service_enabled(False, emergency_reason="test denial", now_utc_epoch=2.0)
                                return sample

                        adapter = DisableOnPreDispatch([frame("pre")])
                    elif scenario == "stale-target":
                        adapter = SequenceAdapter(
                            [
                                frame("source", roi=(10, 10, 30, 30)),
                                frame("pre", roi=(11, 10, 31, 30)),
                            ]
                        )
                    elif scenario == "stale-source":
                        adapter = SequenceAdapter(
                            [
                                frame("source", digest="stable-source"),
                                frame("pre", digest="changed-source"),
                            ]
                        )
                    else:
                        adapter = SequenceAdapter([frame("pre")])

                    session = self._session(state, adapter)
                    run_id = session.run_id
                    if scenario in {"stale-target", "stale-source"}:
                        source = router().observe(session.capture("source"))
                    if scenario == "heartbeat-exception":
                        def heartbeat_exception() -> None:
                            raise RuntimeError("heartbeat")

                        session.heartbeat = heartbeat_exception  # type: ignore[method-assign]
                    elif scenario == "heartbeat-false":
                        session.heartbeat = lambda: None  # type: ignore[method-assign]
                    elif scenario == "fence":
                        session.ensure_fence = lambda **_kwargs: DispatchValidation(False, "FENCE_DENIED")  # type: ignore[method-assign]
                    elif scenario == "reservation":
                        state.reserve_action = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
                    elif scenario == "dispatch-commit":
                        original_transition = state.transition_action

                        def deny_dispatch(
                            action_id: str,
                            state_value: object,
                            *args: object,
                            **kwargs: object,
                        ) -> object:
                            if ActionState(state_value) is ActionState.DISPATCHING:
                                return None
                            return original_transition(action_id, state_value, *args, **kwargs)

                        state.transition_action = deny_dispatch  # type: ignore[method-assign]

                    result = ActionExecutor(session, router()).execute(intent(), source=source)
                    self.assertEqual(result.outcome, ActionOutcome.BLOCKED)
                    self.assertEqual(result.reason, expected_reason)
                    self.assertFalse(result.transport_attempted)
                    self.assertEqual(adapter.transports, [])
                    if scenario == "dispatch-commit":
                        self.assertIsNotNone(result.action)
                        assert result.action is not None
                        self.assertEqual(result.action.state, ActionState.BLOCKED)
                    self.assertIsNotNone(run_id)
                    assert run_id is not None
                    persisted_run = state.get_run(run_id)
                    self.assertIsNotNone(persisted_run)
                    assert persisted_run is not None
                    self.assertNotIn(persisted_run.state, active_states)
                    self.assertIn(
                        persisted_run.state,
                        {
                            RunState.SUCCEEDED,
                            RunState.DEFERRED,
                            RunState.BLOCKED,
                            RunState.FAILED,
                            RunState.ABANDONED,
                        },
                    )
                    lease = state.get_service_lease()
                    self.assertIsNone(lease.owner_instance_id)
                    self.assertIsNone(lease.process_start_token)

                    state.set_service_enabled(True, now_utc_epoch=future)
                    next_session = RuntimeSession(
                        state,
                        SequenceAdapter([frame("next")]),
                        flow_id=FLOW_ID,
                        reset_id=RESET_ID,
                        utc_clock=lambda: future,
                        max_inputs=2,
                        max_actions=2,
                    )
                    try:
                        self.assertIsNotNone(next_session.claim())
                    finally:
                        next_session.close()
                finally:
                    state.close()

    def test_disable_generation_race_blocks_before_transport(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                class DisableOnPreDispatch(SequenceAdapter):
                    def capture(self) -> FrameSample:
                        sample = super().capture()
                        if self.index == 2:
                            state.set_service_enabled(False, emergency_reason="test race", now_utc_epoch=2.0)
                        return sample

                adapter = DisableOnPreDispatch([frame("source"), frame("pre")])
                session = self._session(state, adapter)
                source = router().observe(session.capture("source"))
                result = ActionExecutor(session, router()).execute(intent(), source=source)
                self.assertEqual(result.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(adapter.transports, [])
            finally:
                state.close()
    def test_emergency_after_dispatching_before_transport_aborts_and_releases(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                class EmergencyOnFinalCapture(SequenceAdapter):
                    session: RuntimeSession | None = None

                    def capture(self) -> FrameSample:
                        sample = super().capture()
                        if self.index == 2:
                            assert self.session is not None
                            self.session.request_emergency_stop("test pre-transport race")
                        return sample

                adapter = EmergencyOnFinalCapture([frame("pre"), frame("final")])
                session = self._session(state, adapter)
                adapter.session = session
                result = ActionExecutor(session, router()).execute(intent())

                self.assertEqual(result.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(result.reason, "SERVICE_DISABLED")
                self.assertFalse(result.transport_attempted)
                self.assertEqual(adapter.transports, [])
                self.assertIsNotNone(result.action)
                assert result.action is not None
                self.assertEqual(result.action.state.value, "BLOCKED")
                assert session.run_id is not None
                run = state.get_run(session.run_id)
                assert run is not None
                self.assertEqual(run.consumed_inputs, 0)
                self.assertIsNone(state.get_service_lease().owner_instance_id)

                state.set_service_enabled(True, now_utc_epoch=10_000_000_000.0)
                next_session = RuntimeSession(
                    state,
                    SequenceAdapter([frame("next")]),
                    flow_id=FLOW_ID,
                    reset_id=RESET_ID,
                    utc_clock=lambda: 10_000_000_000.0,
                    max_inputs=2,
                    max_actions=2,
                )
                try:
                    self.assertIsNotNone(next_session.claim())
                finally:
                    next_session.close()
            finally:
                state.close()


    def test_unknown_screen_blocks_without_reservation_or_transport(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                adapter = SequenceAdapter([frame("source", screen="UNKNOWN"), frame("pre", screen="UNKNOWN")])
                session = self._session(state, adapter)
                result = ActionExecutor(session, router()).execute(intent())
                self.assertEqual(result.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(adapter.transports, [])
            finally:
                state.close()

    def test_transport_exception_is_unknown_and_is_not_automatically_retried(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                adapter = SequenceAdapter([frame("source"), frame("pre"), frame("post")], transport_error=RuntimeError("adb"))
                session = self._session(state, adapter)
                source = router().observe(session.capture("source"))
                executor = ActionExecutor(session, router())
                first = executor.execute(intent(), source=source, idempotency_key="one-shot")
                second = executor.execute(intent(), source=source, idempotency_key="one-shot")
                self.assertEqual(first.outcome, ActionOutcome.UNKNOWN)
                self.assertEqual(second.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(len(adapter.transports), 1)
            finally:
                state.close()

    def test_source_changes_between_reservation_and_transport_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                adapter = SequenceAdapter(
                    [
                        frame("pre", digest="stable-source"),
                        frame("final", digest="changed-source"),
                    ]
                )
                session = self._session(state, adapter)
                result = ActionExecutor(session, router()).execute(intent())
                self.assertEqual(result.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(result.reason, "STALE_OR_CHANGED_SOURCE_ROI")
                self.assertIsNotNone(result.action)
                self.assertEqual(result.action.state.value, "BLOCKED")
                self.assertEqual(adapter.index, 2)
                self.assertEqual(adapter.transports, [])
            finally:
                state.close()

    def test_new_idempotency_key_cannot_redispatch_same_binding(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                adapter = SequenceAdapter([frame("same")], transport_result=False)
                session = self._session(state, adapter)
                executor = ActionExecutor(session, router())
                first = executor.execute(
                    intent(),
                    idempotency_key="binding-first",
                    expected_successor=SuccessorConstraint(ScreenId.HOME),
                )
                self.assertEqual(first.outcome, ActionOutcome.SUCCEEDED)
                self.assertIsNotNone(first.action)
                assert first.action is not None
                self.assertEqual(first.action.source_stable_roi_digest, "stable")
                self.assertTrue(first.action.binding_fingerprint)
                second = executor.execute(
                    intent(),
                    idempotency_key="binding-second",
                    expected_successor=SuccessorConstraint(ScreenId.HOME),
                )
                self.assertEqual(second.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(second.reason, "RESERVATION_DENIED")
                self.assertEqual(len(adapter.transports), 1)
            finally:
                state.close()

    def test_no_effect_rejects_retry_with_unchanged_hypothesis(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                adapter = SequenceAdapter([frame("unchanged")], transport_result=False)
                session = self._session(state, adapter)
                executor = ActionExecutor(session, router())
                first = executor.execute(
                    intent(),
                    idempotency_key="no-effect-first",
                    expected_successor=SuccessorConstraint(predicate=lambda _observation: False),
                )
                self.assertEqual(first.outcome, ActionOutcome.NO_EFFECT)
                self.assertIsNotNone(first.action)
                assert first.action is not None
                second = executor.execute(
                    intent(),
                    idempotency_key="no-effect-retry",
                    retry_of_action_id=first.action.action_id,
                    expected_successor=SuccessorConstraint(predicate=lambda _observation: False),
                )
                self.assertEqual(second.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(second.reason, "RESERVATION_DENIED")
                self.assertEqual(len(adapter.transports), 1)
            finally:
                state.close()

    def test_close_terminalizes_run_and_releases_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                session = self._session(state, SequenceAdapter([frame("source")]))
                run_id = session.run_id
                session.close()
                assert run_id is not None
                self.assertIn(state.get_run(run_id).state, {RunState.ABANDONED, RunState.BLOCKED})
                next_session = RuntimeSession(state, SequenceAdapter([frame("next")]), flow_id=FLOW_ID, reset_id=RESET_ID)
                self.assertIsNotNone(next_session.claim())
                next_session.close()
            finally:
                state.close()

    def test_manual_claim_persists_operator_identity_and_enters_running(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                session = RuntimeSession(
                    state,
                    SequenceAdapter([frame("manual")]),
                    flow_id=FLOW_ID,
                    reset_id=RESET_ID,
                    operator_request_id="operator-boundary-42",
                )
                run = session.claim()
                self.assertIsNotNone(run)
                assert run is not None
                self.assertEqual(run.state, RunState.RUNNING)
                self.assertEqual(run.occurrence_kind, "manual")
                self.assertEqual(run.occurrence_basis, "operator-boundary-42")
                self.assertEqual(state.get_flow(FLOW_ID).next_occurrence_key, 0)
                session.close()
            finally:
                state.close()

    def test_inflight_emergency_commit_failure_marks_unknown_and_releases(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                class EmergencyTransport(SequenceAdapter):
                    def execute(self, intent_value: SemanticActionIntent) -> object:
                        state.set_service_enabled(False, emergency_reason="in-flight race", now_utc_epoch=2.0)
                        return super().execute(intent_value)

                original_transition = state.transition_action

                def deny_terminal_commit(action_id: str, state_value: object, *args: object, **kwargs: object) -> object:
                    if ActionState(state_value) in {ActionState.SUCCEEDED, ActionState.NO_EFFECT}:
                        return None
                    return original_transition(action_id, state_value, *args, **kwargs)

                state.transition_action = deny_terminal_commit  # type: ignore[method-assign]
                adapter = EmergencyTransport([frame("pre"), frame("final"), frame("post")], transport_result=False)
                session = self._session(state, adapter)
                executor = ActionExecutor(session, router())
                result = executor.execute(
                    intent(),
                    expected_successor=SuccessorConstraint(ScreenId.HOME),
                )

                self.assertEqual(result.outcome, ActionOutcome.UNKNOWN)
                self.assertEqual(len(adapter.transports), 1)
                self.assertIsNotNone(result.action)
                assert result.action is not None
                persisted_action = state.get_action(result.action.action_id)
                self.assertIsNotNone(persisted_action)
                assert persisted_action is not None
                self.assertEqual(persisted_action.state, ActionState.UNKNOWN)
                assert session.run_id is not None
                persisted_run = state.get_run(session.run_id)
                self.assertIsNotNone(persisted_run)
                assert persisted_run is not None
                self.assertEqual(persisted_run.state, RunState.BLOCKED)
                self.assertIsNone(state.get_service_lease().owner_instance_id)

                second = executor.execute(intent(), expected_successor=SuccessorConstraint(ScreenId.HOME))
                self.assertEqual(second.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(len(adapter.transports), 1)
            finally:
                state.close()

    def test_heartbeat_renews_ttl_before_takeover_then_stale_generation_is_fenced(self) -> None:
        class MutableClock:
            value = 0.0

            def __call__(self) -> float:
                return self.value

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            owner_a = manager(path)
            owner_b = BotStateManager(path, owner_instance_id="boundary-owner-b")
            try:
                clock = MutableClock()
                session = RuntimeSession(
                    owner_a,
                    SequenceAdapter([frame("heartbeat")]),
                    flow_id=FLOW_ID,
                    reset_id=RESET_ID,
                    lease_ttl_seconds=60.0,
                    utc_clock=clock,
                )
                run = session.claim()
                self.assertIsNotNone(run)
                assert run is not None
                clock.value = 30.0
                renewed = session.heartbeat()
                self.assertIsNotNone(renewed)
                assert renewed is not None
                self.assertEqual(renewed.heartbeat_at_utc, 30.0)
                lease = owner_a.get_service_lease()
                self.assertEqual(lease.expires_at_utc, 90.0)

                self.assertIsNone(
                    owner_b.takeover_orphan(
                        run.run_id,
                        owner_instance_id=owner_b.owner_instance_id,
                        process_start_token=owner_b.process_start_token,
                        process_id=owner_b.process_id,
                        now_utc_epoch=61.0,
                        heartbeat_timeout_seconds=60.0,
                    )
                )
                recovered = owner_b.takeover_orphan(
                    run.run_id,
                    owner_instance_id=owner_b.owner_instance_id,
                    process_start_token=owner_b.process_start_token,
                    process_id=owner_b.process_id,
                    now_utc_epoch=91.0,
                    heartbeat_timeout_seconds=60.0,
                )
                self.assertIsNotNone(recovered)
                assert recovered is not None
                self.assertEqual(recovered.state, RunState.RECOVERING)
                clock.value = 91.0
                validation = session.validate_fence()
                self.assertFalse(validation.valid)
                self.assertIn(validation.reason, {"RUN_OWNERSHIP_MISMATCH", "SERVICE_LEASE_MISMATCH"})
                session.close()
            finally:
                owner_b.close()
                owner_a.close()

    def test_blocking_ocr_times_out_unknown_and_releases_ownership(self) -> None:
        finished = threading.Event()

        def blocking_ocr(_cycle: CaptureCycle) -> object:
            finished.wait()
            return {"screen": "HOME"}

        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                session = self._session(state, SequenceAdapter([frame("ocr")]))
                perception = ScreenRouter(
                    [ScreenDefinition(ScreenId.HOME, ocr=blocking_ocr)],
                    callback_timeout_seconds=0.05,
                )
                result = ActionExecutor(session, perception).execute(intent())
                self.assertEqual(result.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(result.reason, "OCR_DEADLINE")
                self.assertEqual(result.transport_attempted, False)
                self.assertEqual(len(session.adapter.transports), 0)
                self.assertIsNone(state.get_service_lease().owner_instance_id)
                assert session.run_id is not None
                persisted_run = state.get_run(session.run_id)
                self.assertIsNotNone(persisted_run)
                assert persisted_run is not None
                self.assertEqual(persisted_run.state, RunState.BLOCKED)
            finally:
                finished.set()
                state.close()


class OverlayBoundaryTests(unittest.TestCase):
    def test_overlay_plan_returns_semantic_intent_and_enforces_successor(self) -> None:
        source = ScreenObservation(
            ScreenId.HOME,
            (OverlayId.VIP_RESET,),
            "a" * 64,
            0.99,
            (TargetBinding("overlay:vip-reset:close", (10, 10, 20, 20), "close", "close"),),
            "overlay-source",
            recognized=True,
        )
        plan = OverlayRecoveryManager().plan(source)
        assert plan is not None
        self.assertEqual(plan.intent.semantic_action, "dismiss_vip_reset")
        still_present = ScreenObservation(ScreenId.HOME, (OverlayId.VIP_RESET,), "b" * 64, 0.99, (), "post", recognized=True)
        gone = ScreenObservation(ScreenId.HOME, (), "c" * 64, 0.99, (), "post-2", recognized=True)
        self.assertFalse(plan.accepts_successor(still_present))
        self.assertTrue(plan.accepts_successor(gone))


    def _session(self, state: BotStateManager, adapter: SequenceAdapter) -> RuntimeSession:
        session = RuntimeSession(state, adapter, flow_id=FLOW_ID, reset_id=RESET_ID, max_inputs=2, max_actions=2)
        self.assertIsNotNone(session.claim())
        return session

    def test_recognizer_callback_exceptions_are_unknown_and_cached(self) -> None:
        cycle = CaptureCycle("callback", "a" * 64)

        def exploding(_cycle: CaptureCycle) -> object:
            raise RuntimeError("recognizer")

        for callback_name in ("template", "geometry", "recognizer", "ocr"):
            definition = ScreenDefinition(ScreenId.HOME, **{callback_name: exploding})
            observation = ScreenRouter([definition]).observe(cycle)
            self.assertTrue(observation.is_unknown)
            self.assertEqual(observation.reason_code, "RECOGNITION_EXCEPTION:RuntimeError")
        direct = ScreenRouter([exploding]).observe(cycle)
        self.assertTrue(direct.is_unknown)
        self.assertEqual(direct.reason_code, "RECOGNITION_EXCEPTION:RuntimeError")

        class ExplodingRecognizer:
            def recognize(self, _cycle: CaptureCycle, _deadline: float | None = None) -> object:
                raise LookupError("recognizer object")

        object_result = ScreenRouter([ExplodingRecognizer()]).observe(cycle)
        self.assertTrue(object_result.is_unknown)
        self.assertEqual(object_result.reason_code, "RECOGNITION_EXCEPTION:LookupError")

    def test_target_predicate_exception_blocks_without_transport(self) -> None:
        class ExplodingSource(ScreenObservation):
            def revalidate_target(self, _fresh: ScreenObservation, _identity: str) -> tuple[bool, str]:
                raise LookupError("target predicate")

        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                adapter = SequenceAdapter([frame("pre")])
                session = self._session(state, adapter)
                source = ExplodingSource(
                    ScreenId.HOME,
                    (),
                    "source" * 11,
                    0.99,
                    (TargetBinding(TARGET, (10, 10, 30, 30), "free-button", "stable"),),
                    "source",
                    recognized=True,
                )
                result = ActionExecutor(session, router()).execute(intent(), source=source)
                self.assertEqual(result.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(adapter.transports, [])
            finally:
                state.close()

    def test_successor_predicate_exception_is_unknown_and_not_retried(self) -> None:
        def exploding(_observation: ScreenObservation) -> bool:
            raise LookupError("successor predicate")

        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                adapter = SequenceAdapter([frame("pre"), frame("post")])
                session = self._session(state, adapter)
                result = ActionExecutor(session, router()).execute(
                    intent(),
                    expected_successor=SuccessorConstraint(predicate=exploding),
                )
                self.assertEqual(result.outcome, ActionOutcome.UNKNOWN)
                self.assertEqual(len(adapter.transports), 1)
            finally:
                state.close()

    def test_overlay_policy_exception_returns_no_plan(self) -> None:
        class ExplodingPolicy:
            overlay = OverlayId.VIP_RESET
            target_identity = "overlay:vip-reset:close"

            @property
            def allowed_base_screens(self) -> tuple[ScreenId, ...]:
                raise LookupError("overlay policy")

        source = ScreenObservation(
            ScreenId.HOME,
            (OverlayId.VIP_RESET,),
            "a" * 64,
            0.99,
            (TargetBinding("overlay:vip-reset:close", (10, 10, 20, 20), "close", "close"),),
            "overlay-source",
            recognized=True,
        )
        self.assertIsNone(OverlayRecoveryManager([ExplodingPolicy()]).plan(source))

    def test_capture_exception_blocks_before_transport(self) -> None:
        class ExplodingCapture(SequenceAdapter):
            def capture(self) -> FrameSample:
                if self.index >= 0:
                    raise OSError("capture")
                return super().capture()

        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                adapter = ExplodingCapture([frame("pre")])
                session = self._session(state, adapter)
                result = ActionExecutor(session, router()).execute(intent())
                self.assertEqual(result.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(adapter.transports, [])
            finally:
                state.close()

    def test_process_owner_token_drift_blocks_before_transport(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                lease = state.acquire_service_lease(
                    owner_instance_id="boundary-owner",
                    process_start_token="process-a",
                    process_id=state.process_id,
                    now_utc_epoch=1.0,
                )
                assert lease is not None
                adapter = SequenceAdapter([frame("pre")])
                session = RuntimeSession(
                    state,
                    adapter,
                    flow_id=FLOW_ID,
                    reset_id=RESET_ID,
                    process_start_token="process-a",
                    lease_generation=lease.lease_generation,
                    max_inputs=2,
                    max_actions=2,
                )
                self.assertIsNotNone(session.claim())
                session.process_start_token = "process-b"
                self.assertEqual(session._token_kwargs(include_run=True)["process_start_token"], "process-b")
                validation = session.validate_fence()
                self.assertFalse(validation.valid)
                self.assertEqual(validation.reason, "RUN_OWNERSHIP_MISMATCH")
                result = ActionExecutor(session, router()).execute(intent())
                self.assertEqual(result.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(adapter.transports, [])
            finally:
                state.close()

if __name__ == "__main__":
    unittest.main()
