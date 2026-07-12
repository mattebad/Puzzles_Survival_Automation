"""Exactly-one-input orchestration over injected capture, transport, and reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from .freshness import ocr_reuse_denial
from .models import ActionIntent, ActionStatus, Observation, PolicyDecision, PolicyRequest, TransportResult
from .policy import CentralPolicy
from .store import DuplicateActionError, SafetyStore


@dataclass(frozen=True)
class ExecutionResult:
    action_id: str
    status: ActionStatus
    reason: str
    transport_calls: int


class GlobalActionBlock(RuntimeError):
    pass


class SafeActionExecutor:
    def __init__(
        self,
        store: SafetyStore,
        policy: CentralPolicy,
        owner_id: str,
        monotonic_clock: Callable[[], float],
        transport: Callable[[ActionIntent], TransportResult],
        recapture: Callable[[], Observation],
        post_observe: Callable[[], Iterable[Observation]],
        reconcile: Callable[[ActionIntent, Observation], bool],
        wall_clock: Optional[Callable[[], float]] = None,
        max_pre_dispatch_attempts: int = 2,
    ) -> None:
        self.store = store
        self.policy = policy
        self.owner_id = owner_id
        self.monotonic_clock = monotonic_clock
        self.wall_clock = wall_clock or monotonic_clock
        self.transport = transport
        self.recapture = recapture
        self.post_observe = post_observe
        self.reconcile = reconcile
        if max_pre_dispatch_attempts < 1 or max_pre_dispatch_attempts > 3:
            raise ValueError("max_pre_dispatch_attempts must be between 1 and 3")
        self.max_pre_dispatch_attempts = max_pre_dispatch_attempts
        self._process_global_block: Optional[str] = None

    @property
    def global_block_reason(self) -> Optional[str]:
        if self._process_global_block:
            return self._process_global_block
        if self.store.has_action_block():
            return "unresolved or nonterminal consequential action"
        return None

    def execute(self, request: PolicyRequest) -> ExecutionResult:
        calls = 0
        monotonic_now = self.monotonic_clock()
        recorded_at = self.wall_clock()
        if self._process_global_block:
            raise GlobalActionBlock(self._process_global_block)
        lease_valid = self.store.lease_valid_for(self.owner_id, recorded_at)
        unresolved = self.store.has_action_block()
        duplicate = self.store.action_key_exists(request.action_key)
        request = PolicyRequest(
            action_id=request.action_id,
            action_key=request.action_key,
            task_id=request.task_id,
            task_mode=request.task_mode,
            semantic_action=request.semantic_action,
            expected_runtime_profile_id=request.expected_runtime_profile_id,
            observation=request.observation,
            monotonic_now=monotonic_now,
            observation_max_age_seconds=request.observation_max_age_seconds,
            dispatch_max_age_seconds=request.dispatch_max_age_seconds,
            lease_owner=self.owner_id if lease_valid else None,
            lease_valid=lease_valid,
            unresolved_action=unresolved,
            duplicate_action_key=duplicate,
            game_day_id=request.game_day_id,
        )
        first_policy = self.policy.evaluate(request)
        self.store.audit(request.task_id, "policy_evaluated", recorded_at, first_policy, request.action_id)
        if not first_policy.authorized:
            return ExecutionResult(request.action_id, ActionStatus.CANCELLED, first_policy.reason_code, calls)

        intent = self._intent(request)
        try:
            self.store.prepare_action(intent, first_policy, recorded_at)
        except DuplicateActionError:
            return ExecutionResult(request.action_id, ActionStatus.CANCELLED, "DUPLICATE_ACTION_KEY", calls)

        immediate = None
        for attempt in range(1, self.max_pre_dispatch_attempts + 1):
            immediate = self.recapture()
            pre_now = self.monotonic_clock()
            pre_recorded_at = self.wall_clock()
            lease_valid = self.store.lease_valid_for(self.owner_id, pre_recorded_at)
            pre_request = request.with_observation(immediate, pre_now)
            pre_request = PolicyRequest(
                action_id=pre_request.action_id,
                action_key=pre_request.action_key,
                task_id=pre_request.task_id,
                task_mode=pre_request.task_mode,
                semantic_action=pre_request.semantic_action,
                expected_runtime_profile_id=pre_request.expected_runtime_profile_id,
                observation=pre_request.observation,
                monotonic_now=pre_request.monotonic_now,
                observation_max_age_seconds=pre_request.observation_max_age_seconds,
                dispatch_max_age_seconds=pre_request.dispatch_max_age_seconds,
                lease_owner=self.owner_id if lease_valid else None,
                lease_valid=lease_valid,
                unresolved_action=self.store.has_action_block(exclude_action_id=request.action_id),
                duplicate_action_key=False,
                game_day_id=pre_request.game_day_id,
                policy_phase="pre_dispatch",
            )
            pre_policy = self.policy.evaluate(pre_request)
            changed = self._changed(request.observation, immediate)
            reuse_denial = ocr_reuse_denial(request.observation, immediate)
            self.store.audit(
                request.task_id,
                "pre_input_attempt",
                pre_recorded_at,
                {
                    "attempt": attempt,
                    "max_attempts": self.max_pre_dispatch_attempts,
                    "policy": pre_policy,
                    "changed": changed,
                    "ocr_reuse_denial": reuse_denial,
                    "frame_age_seconds": pre_now - immediate.capture_completed_monotonic,
                    "transport_calls": calls,
                },
                request.action_id,
            )
            if pre_policy.decision == PolicyDecision.GLOBAL_INPUT_LOCK:
                reason = pre_policy.reason_code
            else:
                reason = changed or reuse_denial or (None if pre_policy.authorized else pre_policy.reason_code)
            if reason == "STALE_FRAME" and attempt < self.max_pre_dispatch_attempts:
                continue
            if reason:
                self.store.mark_cancelled(
                    request.action_id,
                    pre_recorded_at,
                    "pre_input_revalidation:" + reason,
                )
                return ExecutionResult(request.action_id, ActionStatus.CANCELLED, reason, calls)

            dispatch_now = self.monotonic_clock()
            dispatch_age = dispatch_now - immediate.capture_completed_monotonic
            if dispatch_age > request.dispatch_max_age_seconds:
                self.store.audit(
                    request.task_id,
                    "dispatch_freshness_failed",
                    self.wall_clock(),
                    {"attempt": attempt, "frame_age_seconds": dispatch_age, "transport_calls": calls},
                    request.action_id,
                )
                if attempt < self.max_pre_dispatch_attempts:
                    continue
                self.store.mark_cancelled(
                    request.action_id,
                    self.wall_clock(),
                    "pre_input_revalidation:STALE_FRAME",
                )
                return ExecutionResult(request.action_id, ActionStatus.CANCELLED, "STALE_FRAME", calls)
            break

        assert immediate is not None

        try:
            calls += 1
            transport_result = self.transport(intent)
        except BaseException as exc:
            # A transport exception cannot prove the device did not receive the input.
            self._best_effort_unresolved(request.action_id, "ambiguous_transport_exception", exc)
            return ExecutionResult(request.action_id, ActionStatus.UNRESOLVED, "ambiguous_transport_exception", calls)

        if not transport_result.dispatched:
            self.store.mark_cancelled(request.action_id, self.wall_clock(), "transport_conclusively_not_dispatched")
            return ExecutionResult(request.action_id, ActionStatus.CANCELLED, "transport_conclusively_not_dispatched", calls)

        try:
            self.store.mark_input_sent(request.action_id, self.wall_clock(), transport_result)
        except BaseException as exc:
            self._best_effort_unresolved(request.action_id, "persistence_failure_after_possible_dispatch", exc)
            return ExecutionResult(request.action_id, ActionStatus.UNRESOLVED, "persistence_failure_after_possible_dispatch", calls)

        try:
            observations = list(self.post_observe())
        except BaseException as exc:
            self._best_effort_unresolved(request.action_id, "postcondition_observation_failure", exc)
            return ExecutionResult(request.action_id, ActionStatus.UNRESOLVED, "postcondition_observation_failure", calls)
        for observation in observations:
            try:
                confirmed = self.reconcile(intent, observation)
            except BaseException as exc:
                self._best_effort_unresolved(request.action_id, "postcondition_reconciler_failure", exc)
                return ExecutionResult(request.action_id, ActionStatus.UNRESOLVED, "postcondition_reconciler_failure", calls)
            if confirmed:
                try:
                    self.store.mark_confirmed(
                        request.action_id,
                        self.wall_clock(),
                        {"confirmed": True, "frame_sha256": observation.frame_sha256, "evidence_refs": observation.evidence_refs},
                    )
                except BaseException as exc:
                    self._best_effort_unresolved(request.action_id, "evidence_persistence_failure_after_dispatch", exc)
                    return ExecutionResult(request.action_id, ActionStatus.UNRESOLVED, "evidence_persistence_failure_after_dispatch", calls)
                return ExecutionResult(request.action_id, ActionStatus.CONFIRMED, "positive_postcondition", calls)

        reason = "verification_timeout" if not observations else "unexpected_successor"
        try:
            self.store.mark_unresolved(
                request.action_id,
                self.wall_clock(),
                reason,
                {"confirmed": False, "observations": [item.frame_sha256 for item in observations]},
            )
        except BaseException as exc:
            self._best_effort_unresolved(request.action_id, "unresolved_persistence_failure_after_dispatch", exc)
        return ExecutionResult(request.action_id, ActionStatus.UNRESOLVED, reason, calls)

    def _best_effort_unresolved(self, action_id: str, reason: str, exc: BaseException) -> None:
        self._process_global_block = reason
        try:
            self.store.mark_unresolved(action_id, self.wall_clock(), reason, {"exception_type": type(exc).__name__})
        except BaseException:
            # The durable prepared record remains ambiguous and startup reconciliation will block it.
            pass

    @staticmethod
    def _changed(first: Observation, second: Observation) -> Optional[str]:
        fields = (
            ("runtime_profile_id", first.runtime_profile_id, second.runtime_profile_id),
            ("source_state", first.source_state, second.source_state),
            ("overlay_state", first.overlay_state, second.overlay_state),
            ("target_identity", first.target_identity, second.target_identity),
            ("target_roi", first.target_roi, second.target_roi),
            ("consequence", first.consequence, second.consequence),
            ("cost_type", first.cost_type, second.cost_type),
            ("cost_amount", first.cost_amount, second.cost_amount),
            ("quantity", first.quantity, second.quantity),
            ("expected_postcondition", first.expected_postcondition, second.expected_postcondition),
        )
        for name, before, after in fields:
            if before != after:
                return name.upper() + "_CHANGED"
        if (
            first.frame_sha256 == second.frame_sha256
            or second.capture_completed_monotonic <= first.capture_completed_monotonic
        ):
            return "IMMEDIATE_RECAPTURE_NOT_FRESH"
        return None

    @staticmethod
    def _intent(request: PolicyRequest) -> ActionIntent:
        obs = request.observation
        assert obs.target_identity is not None and obs.target_roi is not None
        assert obs.expected_postcondition is not None and obs.consequence is not None
        assert obs.cost_type is not None and obs.cost_amount is not None and obs.quantity is not None
        return ActionIntent(
            action_id=request.action_id,
            action_key=request.action_key,
            task_id=request.task_id,
            semantic_action=request.semantic_action,
            source_state=obs.source_state,
            target_identity=obs.target_identity,
            target_roi=obs.target_roi,
            source_frame_sha256=obs.frame_sha256,
            source_frame_captured_at=obs.capture_completed_monotonic,
            runtime_profile_id=obs.runtime_profile_id,
            game_day_id=request.game_day_id,
            expected_postcondition=obs.expected_postcondition,
            consequence=obs.consequence,
            cost_type=obs.cost_type,
            cost_amount=obs.cost_amount,
            quantity=obs.quantity,
            evidence_refs=obs.evidence_refs,
        )
