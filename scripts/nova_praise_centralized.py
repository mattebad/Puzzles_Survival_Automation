"""Centralized one-shot action and zero-transport replay boundary for Nova Praise.

Selectively admitted from ``fix/nova-pulse-integration`` commits d9c4e336 and 8271de62.
Home/Research Lab/radial/Nova navigation remains outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import re
import time
from typing import Callable, Iterable

from safe_action_core import (
    ActionClass,
    ActionStatus,
    CentralPolicy,
    Observation,
    PolicyRequest,
    SafeActionExecutor,
    SafetyStore,
    SQLiteSchedulerInvocationRepository,
    TransportResult,
)
from scripts.bluestacks_native_runtime import CapturedNativeFrame, NativeRuntimePort
from tasks.nova_praise import (
    NOVA_PRAISE_TARGET,
    NOVA_SCREEN,
    NovaPraiseObservation,
    nova_authorizeable,
    nova_postcondition_verified,
)
from tasks.nova_praise_pulse import NOVA_TASK_ID, NovaPulseController
from tasks.nova_praise_runtime import NovaAction, NovaPraiseRuntimeController
from tasks.nova_praise_vision import NovaFrameRecognition, recognize_nova_frame
from tasks.scheduler_task_result import (
    SchedulerAwareTaskResult,
    SchedulerIdentity,
    SchedulerTaskOutcome,
)


PROFILE_ID = "pns-bluestacks-5-p64-800x1280-v1"
SEMANTIC_ACTION = "PRAISE_NOVA"
EXPECTED_POSTCONDITION = "NOVA_PRAISE_ATTEMPT_DECREMENT_AND_COOLDOWN"
_ATTEMPTS_STATE_RE = re.compile(r"^NOVA_PRAISE_ATTEMPTS_(\d+)$")
_PAID_MARKERS = ("confirm", "purchase", "premium", "diamond", "cash", "cost", "buy")


@dataclass(frozen=True)
class NovaActionIdentity:
    scheduler: SchedulerIdentity
    runtime_scope: str
    invocation_id: str
    attempts_before: int

    def __post_init__(self) -> None:
        if self.scheduler.task_id != NOVA_TASK_ID:
            raise ValueError("Nova action identity requires the nova_praise task")
        if not self.runtime_scope.strip() or self.runtime_scope != self.runtime_scope.strip():
            raise ValueError("Nova runtime scope is required")
        if not self.invocation_id.strip() or self.invocation_id != self.invocation_id.strip():
            raise ValueError("Nova invocation identity is required")
        if self.attempts_before <= 0:
            raise ValueError("Nova action identity requires positive attempts")

    @property
    def durable_basis(self) -> str:
        identity = self.scheduler
        return json.dumps(
            {
                "account_id": identity.account_id,
                "attempts_before": self.attempts_before,
                "reset_id": identity.reset_id,
                "runtime_scope": self.runtime_scope,
                "server_id": identity.server_id,
                "task_id": identity.task_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def action_key(self) -> str:
        return "nova-praise:" + hashlib.sha256(self.durable_basis.encode("utf-8")).hexdigest()

    @property
    def action_id(self) -> str:
        value = json.dumps(
            {
                "action_identity": json.loads(self.durable_basis),
                "invocation_id": self.invocation_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return "nova-praise-" + hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NovaBoundaryResult:
    status: str
    reason: str
    action_id: str | None
    action_key: str | None
    transport_calls: int
    attempts_before: int | None
    attempts_after: int | None
    cooldown_seconds: int | None
    next_eligible_at: float | None
    journal_status: str | None
    scheduler_outcome: str | None
    evidence_refs: tuple[str, ...]
    after_capture: CapturedNativeFrame | None = None
    after_recognition: NovaFrameRecognition | None = None
    intended_inputs: tuple[dict[str, object], ...] = ()
    operational_state_mutated: bool = False

    def to_mapping(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason": self.reason,
            "action_id": self.action_id,
            "action_key": self.action_key,
            "transport_calls": self.transport_calls,
            "attempts_before": self.attempts_before,
            "attempts_after": self.attempts_after,
            "cooldown_seconds": self.cooldown_seconds,
            "next_eligible_at": self.next_eligible_at,
            "journal_status": self.journal_status,
            "scheduler_outcome": self.scheduler_outcome,
            "evidence_refs": list(self.evidence_refs),
            "intended_inputs": list(self.intended_inputs),
            "operational_state_mutated": self.operational_state_mutated,
        }


class NovaPraiseActionBoundary:
    """Own authoritative Praise planning, journal, dispatch, replay, and reconciliation."""

    def __init__(
        self,
        runtime: NativeRuntimePort,
        store: SafetyStore,
        pulse: NovaPulseController,
        *,
        runtime_scope: str,
        owner_id: str,
        invocation_id: str,
        execute: bool,
        recognizer: Callable[..., NovaFrameRecognition] = recognize_nova_frame,
        monotonic_clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        post_delays: tuple[float, ...] = (0.8, 1.8, 3.0),
    ) -> None:
        self.runtime = runtime
        self.store = store
        self.pulse = pulse
        self.runtime_scope = runtime_scope
        self.owner_id = owner_id
        self.invocation_id = invocation_id
        self.execute = execute
        self.recognizer = recognizer
        self.monotonic_clock = monotonic_clock
        self.wall_clock = wall_clock
        self.post_delays = post_delays
        self.scheduler_repository = SQLiteSchedulerInvocationRepository(store)
        self.transport_calls = 0

    @property
    def identity(self) -> SchedulerIdentity:
        return self.pulse.identity

    def _recognize(self, captured: CapturedNativeFrame) -> NovaFrameRecognition:
        return self.recognizer(
            captured.frame,
            captured_monotonic=captured.captured_monotonic,
            stale=False,
        )

    @staticmethod
    def _paid_surface_detected(recognition: NovaFrameRecognition) -> bool:
        text = " ".join(
            str(value).casefold()
            for key, value in recognition.diagnostics.items()
            if key.endswith("_text")
        )
        return any(marker in text for marker in _PAID_MARKERS)

    def _authorize_recognition(
        self,
        captured: CapturedNativeFrame,
        recognition: NovaFrameRecognition,
        *,
        expected_attempts: int,
    ) -> tuple[NovaPraiseObservation, tuple[int, int, int, int]]:
        observation = recognition.observation
        verifier = NovaPraiseRuntimeController(now=captured.captured_monotonic)
        command = verifier.next_command(recognition)
        target = recognition.target(NOVA_PRAISE_TARGET) or command.target_roi
        if command.action is not NovaAction.PRAISE or not nova_authorizeable(
            observation,
            now=captured.captured_monotonic,
        ):
            raise ValueError("current frame does not authorize one free Nova Praise")
        if observation.attempts_remaining != expected_attempts:
            raise ValueError("current Nova attempts differ from the proposed action")
        if target is None or target != observation.praise_target_roi:
            raise ValueError("current Nova Praise semantic target is missing or moved")
        if self._paid_surface_detected(recognition):
            raise ValueError("paid or confirmation surface detected on Nova frame")
        return observation, target

    @staticmethod
    def _roi_digest(
        captured: CapturedNativeFrame,
        roi: tuple[int, int, int, int],
    ) -> str:
        x0, y0, x1, y1 = roi
        return hashlib.sha256(captured.frame[y0:y1, x0:x1].tobytes()).hexdigest()

    def _action_observation(
        self,
        captured: CapturedNativeFrame,
        recognition: NovaFrameRecognition,
        *,
        expected_attempts: int,
    ) -> Observation:
        semantic, target = self._authorize_recognition(
            captured,
            recognition,
            expected_attempts=expected_attempts,
        )
        return Observation(
            frame_sha256=captured.sha256,
            capture_completed_monotonic=captured.captured_monotonic,
            runtime_profile_id=PROFILE_ID,
            width=800,
            height=1280,
            valid_png=True,
            corrupt=False,
            black=False,
            source_state=f"NOVA_PRAISE_ATTEMPTS_{semantic.attempts_remaining}",
            overlay_state=semantic.overlay_state,
            target_identity=NOVA_PRAISE_TARGET,
            target_roi=target,
            recognized=True,
            control_class="PRAISE",
            consequence="praise_zero_cost",
            cost_type="none",
            cost_amount=0,
            quantity=1,
            expected_postcondition=EXPECTED_POSTCONDITION,
            evidence_refs=(str(captured.path),),
            critical_roi_hashes=(("nova-praise", self._roi_digest(captured, target)),),
            ocr_result_frame_sha256=captured.sha256,
            ocr_result_capture_completed_monotonic=captured.captured_monotonic,
            source_family="nova_praise",
            target_isolated=True,
            package_foreground=True,
        )

    @staticmethod
    def _post_observation(
        captured: CapturedNativeFrame,
        recognition: NovaFrameRecognition,
    ) -> Observation:
        semantic = recognition.observation
        return Observation(
            frame_sha256=captured.sha256,
            capture_completed_monotonic=captured.captured_monotonic,
            runtime_profile_id=PROFILE_ID,
            width=800,
            height=1280,
            valid_png=True,
            corrupt=False,
            black=False,
            source_state=semantic.screen_state,
            overlay_state=semantic.overlay_state,
            target_identity=None,
            target_roi=None,
            recognized=semantic.recognized,
            evidence_refs=(str(captured.path),),
            ocr_result_frame_sha256=captured.sha256,
            ocr_result_capture_completed_monotonic=captured.captured_monotonic,
            source_family="nova_praise",
            package_foreground=True,
        )

    def _request(
        self,
        action: NovaActionIdentity,
        observation: Observation,
        *,
        phase: str = "proposal",
    ) -> PolicyRequest:
        return PolicyRequest(
            action_id=action.action_id,
            action_key=action.action_key,
            task_id=NOVA_TASK_ID,
            task_mode="supervised_validation",
            semantic_action=SEMANTIC_ACTION,
            expected_runtime_profile_id=PROFILE_ID,
            observation=observation,
            monotonic_now=self.monotonic_clock(),
            observation_max_age_seconds=3.0,
            dispatch_max_age_seconds=2.0,
            lease_owner=self.owner_id,
            lease_valid=self.store.lease_valid_for(self.owner_id, self.wall_clock()),
            unresolved_action=self.store.has_action_block(),
            duplicate_action_key=self.store.action_key_exists(action.action_key),
            game_day_id=self.identity.reset_id,
            policy_phase=phase,
            action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
            action_kind=SEMANTIC_ACTION,
            subject=NOVA_PRAISE_TARGET,
            resource_or_currency=None,
            maximum_cost=0,
            free_only=True,
            semantic_preconditions=(
                "research_lab_nova_screen",
                "enabled_nova_praise",
                "positive_attempt_count",
                "no_cooldown",
                "fresh_native_frame",
                f"account:{self.identity.account_id}",
                f"server:{self.identity.server_id}",
                f"reset:{self.identity.reset_id}",
            ),
            semantic_postconditions=(
                "attempt_count_decreases_by_one",
                "cooldown_visible_or_zero_terminal",
            ),
            runtime_session_id=str(self.runtime.session),
        )

    def _persist_scheduler(
        self,
        result: SchedulerAwareTaskResult,
        *,
        before: int,
        after: int | None,
        evidence_refs: tuple[str, ...],
    ) -> None:
        progress = dict(result.observed_progress)
        progress.update(
            {
                "attempts_before": before,
                "attempts_after": after,
                "reset_id": self.identity.reset_id,
            }
        )
        terminal = replace(result, observed_progress=progress, evidence_refs=evidence_refs)
        self.scheduler_repository.apply_result(terminal, self.wall_clock())

    def record_no_dispatch(
        self,
        observation: NovaPraiseObservation,
        *,
        evidence_ref: str,
    ) -> NovaBoundaryResult:
        result = self.pulse.praise_result(observation)
        if result.outcome not in {
            SchedulerTaskOutcome.DEFERRED,
            SchedulerTaskOutcome.COMPLETE_FOR_RESET,
        }:
            return NovaBoundaryResult(
                "blocked",
                result.reason_code,
                None,
                None,
                0,
                observation.attempts_remaining,
                observation.attempts_remaining,
                observation.cooldown_seconds,
                result.next_eligible_at,
                None,
                result.outcome.value,
                (evidence_ref,),
            )
        self._persist_scheduler(
            result,
            before=observation.attempts_remaining or 0,
            after=observation.attempts_remaining,
            evidence_refs=(evidence_ref,),
        )
        return NovaBoundaryResult(
            result.outcome.value,
            result.reason_code,
            None,
            None,
            0,
            observation.attempts_remaining,
            observation.attempts_remaining,
            observation.cooldown_seconds,
            result.next_eligible_at,
            None,
            result.outcome.value,
            (evidence_ref,),
            operational_state_mutated=True,
        )

    def replay_no_dispatch(
        self,
        observation: NovaPraiseObservation,
        *,
        evidence_ref: str,
    ) -> NovaBoundaryResult:
        """Evaluate cooldown/zero state without operational persistence."""

        result = self.pulse.praise_result(observation)
        if result.outcome not in {
            SchedulerTaskOutcome.DEFERRED,
            SchedulerTaskOutcome.COMPLETE_FOR_RESET,
        }:
            status = "blocked"
        else:
            status = result.outcome.value
        return NovaBoundaryResult(
            status,
            result.reason_code,
            None,
            None,
            0,
            observation.attempts_remaining,
            observation.attempts_remaining,
            observation.cooldown_seconds,
            result.next_eligible_at,
            None,
            result.outcome.value,
            (evidence_ref,),
        )

    def replay_praise(
        self,
        before_capture: CapturedNativeFrame,
        after_capture: CapturedNativeFrame,
    ) -> NovaBoundaryResult:
        """Run production recognition/policy/planner/postcondition logic with zero transport."""

        if getattr(self.runtime, "dispatches_transport", True) is not False:
            raise ValueError("replay requires a zero-transport runtime")
        if self.store.list_actions_for_task(NOVA_TASK_ID):
            raise ValueError("replay store must start without Nova actions")
        before_recognition = self._recognize(before_capture)
        attempts = before_recognition.observation.attempts_remaining
        if attempts is None or attempts <= 0:
            raise ValueError("positive Nova attempts are required for replay")
        action = NovaActionIdentity(
            self.identity,
            self.runtime_scope,
            self.invocation_id,
            attempts,
        )
        observation = self._action_observation(
            before_capture,
            before_recognition,
            expected_attempts=attempts,
        )
        self.pulse.now = before_capture.captured_monotonic
        planned = self.pulse.praise_result(before_recognition.observation)
        if planned.outcome is not SchedulerTaskOutcome.ACTION_PERFORMED:
            raise ValueError("production task-result logic did not plan one free Praise")
        policy = CentralPolicy({NOVA_TASK_ID})
        issued = policy.issue_capability(self._request(action, observation))
        if not issued.authorized or issued.capability is None:
            raise ValueError(f"production policy rejected replay: {issued.reason_code}")

        self.runtime.tap(
            before_capture,
            target_identity=NOVA_PRAISE_TARGET,
            target_roi=observation.target_roi or (0, 0, 0, 0),
            action_key=action.action_key,
            consequential=True,
        )
        intended = (
            {
                "kind": "tap",
                "source_frame_sha256": before_capture.sha256,
                "target_identity": NOVA_PRAISE_TARGET,
                "target_roi": list(observation.target_roi or ()),
                "action_key": action.action_key,
                "consequential": True,
            },
        )
        after_recognition = self._recognize(after_capture)
        if not nova_postcondition_verified(
            before_recognition.observation,
            after_recognition.observation,
            now=after_recognition.observation.captured_monotonic,
        ):
            return NovaBoundaryResult(
                "replay_blocked",
                "NOVA_PRAISE_POSTCONDITION_NOT_PROVEN",
                action.action_id,
                action.action_key,
                0,
                attempts,
                after_recognition.observation.attempts_remaining,
                after_recognition.observation.cooldown_seconds,
                after_recognition.observation.next_eligible_at,
                None,
                None,
                (str(before_capture.path), str(after_capture.path)),
                after_capture,
                after_recognition,
                intended,
            )
        self.pulse.now = after_capture.captured_monotonic
        scheduler = self.pulse.accept_praise_postcondition(
            before_recognition.observation,
            after_recognition.observation,
        )
        if scheduler.outcome not in {
            SchedulerTaskOutcome.ACTION_PERFORMED,
            SchedulerTaskOutcome.COMPLETE_FOR_RESET,
        }:
            raise RuntimeError("verified replay did not produce a production task result")
        if self.store.list_actions_for_task(NOVA_TASK_ID):
            raise RuntimeError("replay mutated the action journal")
        if self.scheduler_repository.get(self.identity) is not None:
            raise RuntimeError("replay mutated scheduler state")
        return NovaBoundaryResult(
            "replay_confirmed",
            "production_path_postcondition_verified_zero_transport",
            action.action_id,
            action.action_key,
            0,
            attempts,
            after_recognition.observation.attempts_remaining,
            after_recognition.observation.cooldown_seconds,
            scheduler.next_eligible_at,
            None,
            scheduler.outcome.value,
            (str(before_capture.path), str(after_capture.path)),
            after_capture,
            after_recognition,
            intended,
        )

    def execute_praise(
        self,
        proposal_capture: CapturedNativeFrame,
        proposal_recognition: NovaFrameRecognition,
    ) -> NovaBoundaryResult:
        attempts = proposal_recognition.observation.attempts_remaining
        if attempts is None or attempts <= 0:
            raise ValueError("positive Nova attempts are required before centralized dispatch")
        action = NovaActionIdentity(
            self.identity,
            self.runtime_scope,
            self.invocation_id,
            attempts,
        )
        existing = self.store.get_action_by_key(action.action_key)
        if existing is not None:
            return NovaBoundaryResult(
                "blocked",
                f"existing_action_{existing['final_status']}",
                existing["action_id"],
                action.action_key,
                0,
                attempts,
                None,
                None,
                None,
                existing["final_status"],
                None,
                (),
            )

        prepare_capture = self.runtime.capture("praise-central-prepare")
        prepare_recognition = self._recognize(prepare_capture)
        prepare_observation = self._action_observation(
            prepare_capture,
            prepare_recognition,
            expected_attempts=attempts,
        )
        immediate_capture = self.runtime.capture("praise-central-immediate-before")
        immediate_recognition = self._recognize(immediate_capture)
        immediate_observation = self._action_observation(
            immediate_capture,
            immediate_recognition,
            expected_attempts=attempts,
        )

        policy = CentralPolicy({NOVA_TASK_ID})
        issued = policy.issue_capability(self._request(action, immediate_observation))
        self.store.audit(
            NOVA_TASK_ID,
            "capability_issued",
            self.wall_clock(),
            issued.audit,
            action.action_id,
        )
        if not issued.authorized or issued.capability is None:
            return NovaBoundaryResult(
                "blocked",
                issued.reason_code,
                action.action_id,
                action.action_key,
                0,
                attempts,
                None,
                None,
                None,
                None,
                None,
                (str(prepare_capture.path), str(immediate_capture.path)),
            )

        after_by_hash: dict[str, tuple[CapturedNativeFrame, NovaFrameRecognition]] = {}

        def dispatch(_intent) -> TransportResult:
            self.transport_calls += 1
            self.runtime.tap(
                immediate_capture,
                target_identity=NOVA_PRAISE_TARGET,
                target_roi=immediate_observation.target_roi or (0, 0, 0, 0),
                action_key=action.action_key,
                consequential=True,
            )
            return TransportResult(True, "BLUESTACKS_TAP_DISPATCHED")

        def post_observe() -> Iterable[Observation]:
            results: list[Observation] = []
            for ordinal, delay in enumerate(self.post_delays, 1):
                if delay > 0:
                    time.sleep(delay)
                captured = self.runtime.capture(f"praise-central-post-{ordinal}")
                recognition = self._recognize(captured)
                observed = self._post_observation(captured, recognition)
                after_by_hash[observed.frame_sha256] = (captured, recognition)
                results.append(observed)
            return results

        def reconcile(_intent, observed: Observation) -> bool:
            _captured, recognition = after_by_hash[observed.frame_sha256]
            return nova_postcondition_verified(
                immediate_recognition.observation,
                recognition.observation,
                now=recognition.observation.captured_monotonic,
            )

        executor = SafeActionExecutor(
            self.store,
            policy,
            self.owner_id,
            self.monotonic_clock,
            dispatch,
            lambda: immediate_observation,
            post_observe,
            reconcile,
            wall_clock=self.wall_clock,
            max_pre_dispatch_attempts=1,
        )
        execution = executor.execute(
            self._request(action, prepare_observation),
            issued.capability,
            dry_run=not self.execute,
        )
        journal = self.store.get_action(action.action_id)
        evidence = [str(prepare_capture.path), str(immediate_capture.path)]
        evidence.extend(str(captured.path) for captured, _ in after_by_hash.values())

        if execution.status is ActionStatus.CONFIRMED:
            positive = next(
                (
                    pair
                    for pair in after_by_hash.values()
                    if nova_postcondition_verified(
                        immediate_recognition.observation,
                        pair[1].observation,
                        now=pair[1].observation.captured_monotonic,
                    )
                ),
                None,
            )
            if positive is None:
                raise RuntimeError("confirmed Nova action lacks retained positive postcondition")
            after_capture, after_recognition = positive
            self.pulse.now = after_capture.captured_monotonic
            scheduler = self.pulse.accept_praise_postcondition(
                immediate_recognition.observation,
                after_recognition.observation,
            )
            if scheduler.outcome not in {
                SchedulerTaskOutcome.ACTION_PERFORMED,
                SchedulerTaskOutcome.COMPLETE_FOR_RESET,
            }:
                raise RuntimeError("confirmed Nova action lacks terminal scheduler result")
            self._persist_scheduler(
                scheduler,
                before=attempts,
                after=after_recognition.observation.attempts_remaining,
                evidence_refs=tuple(evidence),
            )
            if getattr(self.runtime, "in_flight_action", None) == action.action_key:
                self.runtime.reconcile(
                    action.action_key,
                    "confirmed",
                    after_capture,
                    "central journal confirmed exact decrement and cooldown",
                )
            return NovaBoundaryResult(
                "confirmed",
                execution.reason,
                action.action_id,
                action.action_key,
                execution.transport_calls,
                attempts,
                after_recognition.observation.attempts_remaining,
                after_recognition.observation.cooldown_seconds,
                scheduler.next_eligible_at,
                journal["final_status"],
                scheduler.outcome.value,
                tuple(evidence),
                after_capture,
                after_recognition,
                operational_state_mutated=True,
            )

        if execution.status is ActionStatus.UNRESOLVED:
            unresolved_capture = next(
                reversed([pair[0] for pair in after_by_hash.values()]),
                immediate_capture,
            )
            if getattr(self.runtime, "in_flight_action", None) == action.action_key:
                self.runtime.reconcile(
                    action.action_key,
                    "unresolved",
                    unresolved_capture,
                    "central journal could not prove Nova postcondition",
                )
            return NovaBoundaryResult(
                "unresolved",
                execution.reason,
                action.action_id,
                action.action_key,
                execution.transport_calls,
                attempts,
                None,
                None,
                None,
                journal["final_status"],
                None,
                tuple(evidence),
                operational_state_mutated=True,
            )

        return NovaBoundaryResult(
            "dry-run" if not self.execute else "blocked",
            execution.reason,
            action.action_id,
            action.action_key,
            execution.transport_calls,
            attempts,
            None,
            None,
            None,
            journal["final_status"],
            None,
            tuple(evidence),
            operational_state_mutated=True,
        )

    def reconcile_restart(
        self,
        captured: CapturedNativeFrame,
        recognition: NovaFrameRecognition,
    ) -> NovaBoundaryResult:
        candidates = [
            item
            for item in self.store.list_unresolved_actions()
            if item["task_id"] == NOVA_TASK_ID
        ]
        if len(candidates) != 1:
            return NovaBoundaryResult(
                "unresolved",
                "restart_requires_exactly_one_nova_action",
                None,
                None,
                0,
                None,
                None,
                None,
                None,
                "unresolved",
                None,
                (str(captured.path),),
            )
        action = candidates[0]
        match = _ATTEMPTS_STATE_RE.fullmatch(action["source_state"])
        if match is None or action["input_attempt_at"] is None:
            return NovaBoundaryResult(
                "unresolved",
                "restart_action_has_no_authoritative_input_sent_record",
                action["action_id"],
                action["action_key"],
                0,
                None,
                None,
                None,
                None,
                action["final_status"],
                None,
                (str(captured.path),),
            )
        attempts = int(match.group(1))
        before = NovaPraiseObservation(
            screen_state=NOVA_SCREEN,
            research_lab_identity=True,
            nova_control_visible=False,
            selected_nova=True,
            praise_enabled=True,
            praise_target_identity=NOVA_PRAISE_TARGET,
            praise_target_roi=tuple(json.loads(action["target_roi_json"])),
            attempts_remaining=attempts,
            frame_sha256=action["source_frame_sha256"],
            captured_monotonic=action["source_frame_captured_at"],
            recognized=True,
        )
        after = recognition.observation
        if not nova_postcondition_verified(before, after, now=after.captured_monotonic):
            return NovaBoundaryResult(
                "unresolved",
                "restart_postcondition_not_proven",
                action["action_id"],
                action["action_key"],
                0,
                attempts,
                after.attempts_remaining,
                after.cooldown_seconds,
                after.next_eligible_at,
                action["final_status"],
                None,
                (str(captured.path),),
            )
        self.store.reconcile_confirmed(
            action["action_id"],
            self.wall_clock(),
            {
                "confirmed": True,
                "restart_reconciliation": True,
                "frame_sha256": captured.sha256,
                "evidence_refs": [str(captured.path)],
            },
        )
        self.pulse.now = captured.captured_monotonic
        scheduler = self.pulse.accept_praise_postcondition(before, after)
        self._persist_scheduler(
            scheduler,
            before=attempts,
            after=after.attempts_remaining,
            evidence_refs=(str(captured.path),),
        )
        return NovaBoundaryResult(
            "confirmed",
            "restart_postcondition_reconciled",
            action["action_id"],
            action["action_key"],
            0,
            attempts,
            after.attempts_remaining,
            after.cooldown_seconds,
            scheduler.next_eligible_at,
            "confirmed",
            scheduler.outcome.value,
            (str(captured.path),),
            captured,
            recognition,
            operational_state_mutated=True,
        )
