"""Exactly-one-input orchestration over injected capture, transport, and reconciliation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Iterable, Optional

from .freshness import ocr_reuse_denial
from .models import (
    CAPABILITY_DRY_RUN_ZERO_TRANSPORT,
    CAPABILITY_EXECUTOR_DRY_RUN,
    CAPABILITY_RETIRED_NO_DISPATCH,
    CAPABILITY_SCHEMA_INVALID,
    CapabilityAuditRecord,
    ActionClass,
    ActionIntent,
    ActionStatus,
    InputCapability,
    Observation,
    PolicyDecision,
    PolicyRequest,
    TransportResult,
)
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

    @staticmethod
    def _rebuild_request(
        request: PolicyRequest,
        *,
        monotonic_now: float,
        lease_owner: Optional[str],
        lease_valid: bool,
        unresolved_action: bool,
        duplicate_action_key: bool,
        policy_phase: Optional[str] = None,
        observation: Optional[Observation] = None,
    ) -> PolicyRequest:
        return PolicyRequest(
            action_id=request.action_id,
            action_key=request.action_key,
            task_id=request.task_id,
            task_mode=request.task_mode,
            semantic_action=request.semantic_action,
            expected_runtime_profile_id=request.expected_runtime_profile_id,
            observation=observation if observation is not None else request.observation,
            monotonic_now=monotonic_now,
            observation_max_age_seconds=request.observation_max_age_seconds,
            dispatch_max_age_seconds=request.dispatch_max_age_seconds,
            lease_owner=lease_owner,
            lease_valid=lease_valid,
            unresolved_action=unresolved_action,
            duplicate_action_key=duplicate_action_key,
            game_day_id=request.game_day_id,
            policy_phase=policy_phase if policy_phase is not None else request.policy_phase,
            promotional_back_count=request.promotional_back_count,
            action_class=request.action_class,
            action_kind=request.action_kind or request.semantic_action,
            subject=request.subject,
            resource_or_currency=request.resource_or_currency,
            maximum_cost=request.maximum_cost,
            free_only=request.free_only,
            allowed_confirmation_dialogs=request.allowed_confirmation_dialogs,
            semantic_preconditions=request.semantic_preconditions,
            semantic_postconditions=request.semantic_postconditions,
            runtime_session_id=request.runtime_session_id,
        )

    def _terminal_with_capability(
        self,
        request: PolicyRequest,
        capability: Optional[InputCapability],
        *,
        reason: str,
        dry_run: bool,
        calls: int,
        cancel_prepared: bool,
        allow_transport: bool = False,
    ) -> Optional[ExecutionResult]:
        """Consume capability on every terminal attempt; return a result when dispatch must stop."""
        if capability is None:
            if dry_run:
                if cancel_prepared:
                    self.store.mark_cancelled(request.action_id, self.wall_clock(), "dry_run:" + reason)
                return ExecutionResult(
                    request.action_id, ActionStatus.CANCELLED, CAPABILITY_DRY_RUN_ZERO_TRANSPORT, calls
                )
            return None
        consume = (
            self.policy.consume_capability(capability, request)
            if allow_transport and not dry_run
            else self.policy.retire_capability(capability, request)
        )
        self.store.audit(
            request.task_id,
            "capability_consume",
            self.wall_clock(),
            consume.audit,
            request.action_id,
        )
        if dry_run:
            dry_run_audit = CapabilityAuditRecord(
                event=CAPABILITY_EXECUTOR_DRY_RUN,
                reason_code=CAPABILITY_DRY_RUN_ZERO_TRANSPORT,
                decision="dry_run",
                binding_fingerprint=consume.audit.binding_fingerprint,
                capability_ref=consume.audit.capability_ref,
                transport_calls=calls,
                dry_run=True,
                policy_authorized=False,
                transport_occurred=False,
                details=(
                    ("binding_matched", consume.binding_matched),
                    ("consumed", consume.consumed),
                    ("executor_transport_calls", calls),
                ),
            )
            self.store.audit(
                request.task_id,
                "capability_executor_dry_run",
                self.wall_clock(),
                dry_run_audit,
                request.action_id,
            )
            if cancel_prepared:
                self.store.mark_cancelled(
                    request.action_id,
                    self.wall_clock(),
                    "dry_run:" + consume.reason_code,
                )
            return ExecutionResult(
                request.action_id, ActionStatus.CANCELLED, CAPABILITY_DRY_RUN_ZERO_TRANSPORT, calls
            )
        if not allow_transport or not consume.allow_dispatch:
            if cancel_prepared:
                self.store.mark_cancelled(
                    request.action_id,
                    self.wall_clock(),
                    "capability:" + consume.reason_code,
                )
            terminal_reason = (
                reason
                if not allow_transport and consume.reason_code == CAPABILITY_RETIRED_NO_DISPATCH
                else consume.reason_code
            )
            return ExecutionResult(request.action_id, ActionStatus.CANCELLED, terminal_reason, calls)
        return None

    def _cancel_malformed_pre_dispatch(
        self,
        request: PolicyRequest,
        capability: Optional[InputCapability],
        *,
        dry_run: bool,
        calls: int,
    ) -> ExecutionResult:
        terminal_request = request
        if self.policy.evaluate(terminal_request).reason_code != CAPABILITY_SCHEMA_INVALID:
            terminal_request = replace(
                request,
                observation=object(),
                policy_phase="pre_dispatch",
            )
        terminal = self._terminal_with_capability(
            terminal_request,
            capability,
            reason=CAPABILITY_SCHEMA_INVALID,
            dry_run=dry_run,
            calls=calls,
            cancel_prepared=True,
        )
        if terminal is not None:
            return terminal
        self.store.mark_cancelled(
            terminal_request.action_id,
            self.wall_clock(),
            "pre_input_revalidation:" + CAPABILITY_SCHEMA_INVALID,
        )
        return ExecutionResult(
            terminal_request.action_id,
            ActionStatus.CANCELLED,
            CAPABILITY_SCHEMA_INVALID,
            calls,
        )

    def execute(
        self,
        request: PolicyRequest,
        capability: Optional[InputCapability] = None,
        *,
        dry_run: bool = False,
    ) -> ExecutionResult:
        calls = 0
        monotonic_now = self.monotonic_clock()
        recorded_at = self.wall_clock()
        pending_capability = capability
        if self._process_global_block:
            if pending_capability is not None:
                terminal = self._terminal_with_capability(
                    request,
                    pending_capability,
                    reason=self._process_global_block,
                    dry_run=dry_run,
                    calls=calls,
                    cancel_prepared=False,
                )
                if terminal is not None:
                    return terminal
            raise GlobalActionBlock(self._process_global_block)
        lease_valid = self.store.lease_valid_for(self.owner_id, recorded_at)
        unresolved = self.store.has_action_block()
        duplicate = self.store.action_key_exists(request.action_key)
        request = self._rebuild_request(
            request,
            monotonic_now=monotonic_now,
            lease_owner=self.owner_id if lease_valid else None,
            lease_valid=lease_valid,
            unresolved_action=unresolved,
            duplicate_action_key=duplicate,
        )
        first_policy = self.policy.evaluate(request)
        self.store.audit(request.task_id, "policy_evaluated", recorded_at, first_policy, request.action_id)
        if not first_policy.authorized:
            terminal = self._terminal_with_capability(
                request,
                pending_capability,
                reason=first_policy.reason_code,
                dry_run=dry_run,
                calls=calls,
                cancel_prepared=False,
            )
            pending_capability = None
            if terminal is not None:
                return terminal
            return ExecutionResult(request.action_id, ActionStatus.CANCELLED, first_policy.reason_code, calls)

        intent = self._intent(request)
        try:
            self.store.prepare_action(intent, first_policy, recorded_at)
        except DuplicateActionError:
            terminal = self._terminal_with_capability(
                request,
                pending_capability,
                reason="DUPLICATE_ACTION_KEY",
                dry_run=dry_run,
                calls=calls,
                cancel_prepared=False,
            )
            pending_capability = None
            if terminal is not None:
                return terminal
            return ExecutionResult(request.action_id, ActionStatus.CANCELLED, "DUPLICATE_ACTION_KEY", calls)

        immediate = None
        pre_request = request
        for attempt in range(1, self.max_pre_dispatch_attempts + 1):
            try:
                immediate = self.recapture()
            except (AttributeError, TypeError, ValueError):
                return self._cancel_malformed_pre_dispatch(
                    request,
                    pending_capability,
                    dry_run=dry_run,
                    calls=calls,
                )
            if type(immediate) is not Observation:
                return self._cancel_malformed_pre_dispatch(
                    request,
                    pending_capability,
                    dry_run=dry_run,
                    calls=calls,
                )
            pre_now = self.monotonic_clock()
            pre_recorded_at = self.wall_clock()
            lease_valid = self.store.lease_valid_for(self.owner_id, pre_recorded_at)
            pre_request = self._rebuild_request(
                request,
                monotonic_now=pre_now,
                lease_owner=self.owner_id if lease_valid else None,
                lease_valid=lease_valid,
                unresolved_action=self.store.has_action_block(exclude_action_id=request.action_id),
                duplicate_action_key=False,
                policy_phase="pre_dispatch",
                observation=immediate,
            )
            pre_policy = self.policy.evaluate(pre_request)
            if pre_policy.reason_code == CAPABILITY_SCHEMA_INVALID:
                return self._cancel_malformed_pre_dispatch(
                    pre_request,
                    pending_capability,
                    dry_run=dry_run,
                    calls=calls,
                )
            try:
                changed = self._changed(
                    request.observation,
                    immediate,
                    allow_target_roi_change=(
                        request.semantic_action in {
                            "DISMISS_ALLIANCE_FORT_WAVE",
                            "RESEARCH_BIOENHANCER_FREE",
                        }
                    ),
                )
                reuse_denial = ocr_reuse_denial(request.observation, immediate)
            except (AttributeError, TypeError, ValueError):
                return self._cancel_malformed_pre_dispatch(
                    pre_request,
                    pending_capability,
                    dry_run=dry_run,
                    calls=calls,
                )
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
                terminal = self._terminal_with_capability(
                    pre_request,
                    pending_capability,
                    reason=reason,
                    dry_run=dry_run,
                    calls=calls,
                    cancel_prepared=True,
                )
                pending_capability = None
                if terminal is not None:
                    return terminal
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
                terminal = self._terminal_with_capability(
                    pre_request,
                    pending_capability,
                    reason="STALE_FRAME",
                    dry_run=dry_run,
                    calls=calls,
                    cancel_prepared=True,
                )
                pending_capability = None
                if terminal is not None:
                    return terminal
                self.store.mark_cancelled(
                    request.action_id,
                    self.wall_clock(),
                    "pre_input_revalidation:STALE_FRAME",
                )
                return ExecutionResult(request.action_id, ActionStatus.CANCELLED, "STALE_FRAME", calls)
            break

        assert immediate is not None

        # Final capability boundary: revalidate identity/coordinates/capture and consume one-shot.
        if pending_capability is not None or dry_run:
            terminal = self._terminal_with_capability(
                pre_request,
                pending_capability,
                reason="AUTHORIZED",
                dry_run=dry_run,
                calls=calls,
                cancel_prepared=True,
                allow_transport=not dry_run,
            )
            pending_capability = None
            if terminal is not None:
                return terminal

        dispatch_intent = intent
        if (
            request.semantic_action in {
                "DISMISS_ALLIANCE_FORT_WAVE",
                "RESEARCH_BIOENHANCER_FREE",
                "CLAIM_DAILY_QUEST",
            }
            and immediate.target_roi is not None
        ):
            dispatch_intent = replace(
                intent,
                target_roi=immediate.target_roi,
                source_frame_sha256=immediate.frame_sha256,
                source_frame_captured_at=immediate.capture_completed_monotonic,
                evidence_refs=immediate.evidence_refs,
            )

        try:
            calls += 1
            transport_result = self.transport(dispatch_intent)
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
    def _changed(
        first: Observation,
        second: Observation,
        *,
        allow_target_roi_change: bool = False,
    ) -> Optional[str]:
        fields = (
            ("runtime_profile_id", first.runtime_profile_id, second.runtime_profile_id),
            ("source_state", first.source_state, second.source_state),
            ("overlay_state", first.overlay_state, second.overlay_state),
            ("target_identity", first.target_identity, second.target_identity),
            ("consequence", first.consequence, second.consequence),
            ("cost_type", first.cost_type, second.cost_type),
            ("cost_amount", first.cost_amount, second.cost_amount),
            ("quantity", first.quantity, second.quantity),
            ("expected_postcondition", first.expected_postcondition, second.expected_postcondition),
            ("source_family", first.source_family, second.source_family),
            ("target_isolated", first.target_isolated, second.target_isolated),
            ("forbidden_region_intersects_target", first.forbidden_region_intersects_target, second.forbidden_region_intersects_target),
            ("arrow_geometry", first.arrow_geometry, second.arrow_geometry),
            ("forbidden_regions", first.forbidden_regions, second.forbidden_regions),
            ("package_foreground", first.package_foreground, second.package_foreground),
            ("os_surface", first.os_surface, second.os_surface),
            ("hard_stop_detected", first.hard_stop_detected, second.hard_stop_detected),
        )
        for name, before, after in fields:
            if before != after:
                return name.upper() + "_CHANGED"
        if not allow_target_roi_change and first.target_roi != second.target_roi:
            return "TARGET_ROI_CHANGED"
        if second.capture_completed_monotonic <= first.capture_completed_monotonic:
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
            consequential=request.action_class != ActionClass.NAVIGATION_ONLY,
            source_family=obs.source_family,
            target_isolated=obs.target_isolated,
            forbidden_region_intersects_target=obs.forbidden_region_intersects_target,
            arrow_geometry=obs.arrow_geometry,
            promotional_back_count=request.promotional_back_count,
            action_class=request.action_class,
            action_kind=request.semantic_action,
            subject=obs.target_identity,
            resource_or_currency=obs.cost_type,
            maximum_cost=obs.cost_amount,
            free_only=obs.cost_type == "none" and obs.cost_amount == 0,
            allowed_confirmation_dialogs=request.allowed_confirmation_dialogs,
            semantic_preconditions=request.semantic_preconditions or (obs.source_state, obs.overlay_state),
            semantic_postconditions=request.semantic_postconditions or (obs.expected_postcondition,),
        )


# The existing fail-closed executor is the MVP ActionTransaction implementation.
ActionTransaction = SafeActionExecutor
