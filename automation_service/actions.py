"""Single action/transport boundary for the canonical automation service.

The executor owns no device protocol.  It composes a :class:`RuntimeSession`, a
registry-driven :class:`ScreenRouter`, and the existing adapter/transport seam.  Every
possible input receives a fresh capture, a current stable target binding, an atomic
SQLite reservation, and a committed DISPATCHING state before exactly one transport call.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import inspect
import math
import time
from typing import Any, Callable, Iterable

from .contracts import SemanticActionIntent
from .screens import CaptureCycle, ScreenId, ScreenObservation, ScreenRouter, TargetBinding
from .session import RuntimeSession
from .state import ActionRecord, ActionState, DispatchValidation, RunState


class ActionExecutionError(RuntimeError):
    """Malformed action boundary input (runtime outcomes are returned, not raised)."""


class ActionOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    NO_EFFECT = "NO_EFFECT"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class ActionResult:
    """Immutable action outcome and evidence references."""

    outcome: ActionOutcome
    reason: str
    action: ActionRecord | None = None
    source: ScreenObservation | None = None
    pre_dispatch: ScreenObservation | None = None
    successor: ScreenObservation | None = None
    transport_attempted: bool = False
    transport_succeeded: bool | None = None

    @property
    def action_id(self) -> str | None:
        return self.action.action_id if self.action is not None else None

    @property
    def succeeded(self) -> bool:
        return self.outcome is ActionOutcome.SUCCEEDED

    @property
    def unknown(self) -> bool:
        return self.outcome is ActionOutcome.UNKNOWN


class SuccessorConstraint:
    """Bounded post-input successor contract.

    A screen set is only a coarse allowlist; a supplied predicate may require exact
    semantic progress (for example, a dismissed overlay or a changed row state).
    """

    def __init__(
        self,
        screens: ScreenId | str | Iterable[ScreenId | str] | None = None,
        *,
        overlays_absent: Iterable[str] = (),
        predicate: Callable[[ScreenObservation], bool] | None = None,
    ) -> None:
        if screens is None:
            normalized: tuple[ScreenId, ...] = ()
        elif isinstance(screens, (ScreenId, str)):
            normalized = (self._screen(screens),)
        else:
            normalized = tuple(self._screen(item) for item in screens)
        self.screens = normalized
        self.overlays_absent = tuple(str(item) for item in overlays_absent)
        self.predicate = predicate

    @staticmethod
    def _screen(value: ScreenId | str) -> ScreenId:
        try:
            return value if isinstance(value, ScreenId) else ScreenId(str(value))
        except ValueError:
            return ScreenId.UNKNOWN

    def accepts(self, observation: ScreenObservation) -> bool:
        if observation.is_unknown:
            return False
        if self.screens and observation.screen not in self.screens:
            return False
        if any(observation.has_overlay(overlay) for overlay in self.overlays_absent):
            return False
        return self.predicate is None or bool(self.predicate(observation))


class ActionExecutor:
    """Reserve, fence, dispatch once, and classify one semantic intent."""

    def __init__(
        self,
        session: RuntimeSession,
        router: ScreenRouter,
        *,
        transport: Callable[..., Any] | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
        successor_timeout_seconds: float = 2.0,
        successor_constraint: SuccessorConstraint | None = None,
    ) -> None:
        has_fence = callable(getattr(session, "ensure_fence", None)) or callable(
            getattr(session, "validate_fence", None)
        )
        if not callable(getattr(session, "capture", None)) or not has_fence:
            raise TypeError("ActionExecutor requires a RuntimeSession-compatible session")
        if not callable(getattr(router, "observe", None)) or not callable(getattr(router, "invalidate", None)):
            raise TypeError("ActionExecutor requires a ScreenRouter-compatible router")
        if transport is not None and not callable(transport):
            raise TypeError("transport must be callable")
        if not math.isfinite(float(successor_timeout_seconds)) or successor_timeout_seconds <= 0:
            raise ValueError("successor timeout must be finite and positive")
        self.session = session
        self.router = router
        self.transport = transport
        self._monotonic = monotonic_clock
        self.successor_timeout_seconds = float(successor_timeout_seconds)
        self.successor_constraint = successor_constraint

    def execute(
        self,
        intent: SemanticActionIntent,
        *,
        source: ScreenObservation | None = None,
        source_observation: ScreenObservation | None = None,
        idempotency_key: str | None = None,
        action_class: str = "semantic_input",
        quantity: int = 1,
        input_cost: int = 1,
        expected_successor: SuccessorConstraint | ScreenId | str | Iterable[ScreenId | str] | Callable[[ScreenObservation], bool] | None = None,
        successor_timeout_seconds: float | None = None,
        retry_of_action_id: str | None = None,
        hypothesis_digest: str | None = None,
    ) -> ActionResult:
        """Execute one intent; UNKNOWN is terminal and is never retried here."""

        if not isinstance(intent, SemanticActionIntent):
            raise TypeError("intent must be a SemanticActionIntent")
        source = source_observation or source
        if intent.flow_id is not None and intent.flow_id != self.session.flow_id:
            if self.session.run is not None:
                return self._blocked_before_transport("FLOW_MISMATCH", source=source)
            return self._blocked("FLOW_MISMATCH", source=source)
        if not isinstance(action_class, str) or not action_class.strip():
            raise ActionExecutionError("action_class is required")
        if type(quantity) is not int or quantity < 1 or type(input_cost) is not int or input_cost < 0:
            raise ActionExecutionError("quantity/input_cost are invalid")
        key = str(idempotency_key or intent.action_key)
        if not key.strip():
            raise ActionExecutionError("idempotency key is required")
        if retry_of_action_id is not None:
            retry_of_action_id = str(retry_of_action_id)
            if not retry_of_action_id.strip():
                raise ActionExecutionError("retry action id cannot be blank")
        hypothesis = intent.expected_postcondition if hypothesis_digest is None else str(hypothesis_digest)
        if not hypothesis.strip():
            raise ActionExecutionError("hypothesis digest is required")
        run = self.session.run
        if run is None:
            return self._blocked("RUN_NOT_CLAIMED", source=source)
        heartbeat = getattr(self.session, "heartbeat", None)
        if callable(heartbeat):
            try:
                renewed = heartbeat()
            except Exception as exc:
                reason = f"HEARTBEAT_FAILED:{type(exc).__name__}"
                return self._blocked_before_transport(reason, source=source)
            if renewed is None or isinstance(renewed, bool) or not hasattr(renewed, "state"):
                return self._blocked_before_transport("HEARTBEAT_FENCE_FAILED", source=source)
            run = renewed
        # A claimed occurrence is only admission state.  Promote it through
        # the fenced state authority before capturing any input-capable frame;
        # reserve_action and validate_dispatch intentionally reject CLAIMED.
        if run.state is RunState.CLAIMED:
            try:
                started = self._state_call(
                    "transition_run",
                    run.run_id,
                    RunState.RUNNING,
                    expected_state=RunState.CLAIMED,
                    now_utc_epoch=self._utc(),
                )
            except Exception as exc:
                reason = f"RUN_START_FAILED:{type(exc).__name__}"
                return self._blocked_before_transport(reason, source=source)
            if started is None or getattr(started, "state", None) is not RunState.RUNNING:
                return self._blocked_before_transport("RUN_START_DENIED", source=source)
            run = started
            if hasattr(self.session, "_run"):
                self.session._run = started
        if run.state is not RunState.RUNNING:
            return self._blocked_before_transport("RUN_NOT_RUNNING", source=source)
        # Planning/source recognition is never reused for dispatch.  This is a new
        # capture cycle even when the frame hash is unchanged.
        try:
            pre_cycle = self.session.capture("pre-dispatch")
            pre = self.router.observe(pre_cycle, deadline_monotonic=self._monotonic() + self.successor_timeout_seconds)
        except Exception as exc:
            reason = f"PRE_DISPATCH_CAPTURE_FAILED:{type(exc).__name__}"
            return self._blocked_before_transport(reason, source=source)
        if pre.is_unknown:
            reason = pre.reason_code or "UNKNOWN_PRE_DISPATCH"
            return self._blocked_before_transport(reason, source=source, pre_dispatch=pre)

        try:
            target_identity = intent.target_identity
            if not target_identity:
                return self._blocked_before_transport("TARGET_IDENTITY_REQUIRED", source=source, pre_dispatch=pre)
            target = pre.target(target_identity)
            if target is None:
                return self._blocked_before_transport("TARGET_NOT_RECOGNIZED", source=source, pre_dispatch=pre)
            if source is not None:
                valid, reason = source.revalidate_target(pre, target_identity)
                if not valid:
                    return self._blocked_before_transport(reason, source=source, pre_dispatch=pre)
        except Exception as exc:
            # Target lookup and stable-ROI compatibility are untrusted recognition
            # callbacks.  They are pre-dispatch authority and therefore block.
            reason = f"TARGET_RECOGNITION_FAILED:{type(exc).__name__}"
            return self._blocked_before_transport(
                reason,
                source=source,
                pre_dispatch=pre,
            )
        authoritative_source = source or pre
        stable_source_digest = authoritative_source.stable_roi_digest
        if not isinstance(stable_source_digest, str) or not stable_source_digest.strip():
            return self._blocked_before_transport("SOURCE_STABLE_ROI_REQUIRED", source=source, pre_dispatch=pre)

        # Reservation is itself a generation/budget/idempotency fence.
        try:
            current_fence = self._ensure_fence()
        except Exception as exc:
            reason = f"FENCE_VALIDATION_FAILED:{type(exc).__name__}"
            return self._blocked_before_transport(reason, source=source, pre_dispatch=pre)
        if not isinstance(current_fence, DispatchValidation):
            return self._blocked_before_transport(
                "FENCE_VALIDATION_INVALID_RESULT",
                source=source,
                pre_dispatch=pre,
            )
        if not current_fence.valid:
            return self._blocked_before_transport(
                current_fence.reason or "FENCE_VALIDATION_FAILED",
                source=source,
                pre_dispatch=pre,
            )
        try:
            action = self._state_call(
                "reserve_action",
                run.run_id,
                key,
                intent.action_key,
                source_capture_id=pre.capture_id,
                source_frame_hash=pre.frame_hash,
                source_stable_roi_digest=stable_source_digest,
                source_binding_digest=target.binding_digest,
                target_identity=target.target_identity,
                target_binding_digest=target.binding_digest,
                action_class=action_class,
                quantity=quantity,
                input_cost=input_cost,
                retry_of_action_id=retry_of_action_id,
                hypothesis_digest=hypothesis,
                now_utc_epoch=self._utc(),
            )
        except Exception as exc:
            reason = f"RESERVATION_FAILED:{type(exc).__name__}"
            return self._blocked_before_transport(reason, source=source, pre_dispatch=pre)
        if action is None:
            return self._blocked_before_transport("RESERVATION_DENIED", source=source, pre_dispatch=pre)

        # The state manager's transition is the durable commit point immediately before
        # transport.  No transport is attempted unless this succeeds and the final
        # service/flow/run generation validation still passes.
        try:
            dispatching = self._state_call(
                "transition_action",
                action.action_id,
                ActionState.DISPATCHING,
                expected_state=ActionState.RESERVED,
                now_utc_epoch=self._utc(),
            )
        except Exception as exc:
            dispatching = None
            transition_error = f"DISPATCH_COMMIT_FAILED:{type(exc).__name__}"
        else:
            transition_error = "DISPATCH_COMMIT_DENIED"
        if dispatching is None:
            return self._blocked_before_transport(
                transition_error,
                action=action,
                source=source,
                pre_dispatch=pre,
            )
        action = dispatching

        # This is the last service/run fence before the fresh source/target
        # revalidation.  The capture and revalidation below must be the final
        # perception work before the one transport call.
        try:
            final_fence = self._ensure_fence(action_id=action.action_id)
        except Exception as exc:
            final_fence = None
            final_fence_error = f"FENCE_VALIDATION_FAILED:{type(exc).__name__}"
        else:
            final_fence_error = None
        if final_fence is None or not final_fence.valid:
            reason = final_fence_error or final_fence.reason or "FENCE_VALIDATION_FAILED"
            return self._pretransport_abort(
                action,
                reason,
                source=source,
                pre_dispatch=pre,
            )

        final_observation: ScreenObservation | None = None
        final_reason: str | None = None
        try:
            # Recognition is cache-backed, so invalidate before taking the final
            # cycle even when an adapter happens to reuse a frame identity.
            self.router.invalidate()
            final_cycle = self.session.capture("final-pre-transport")
            final_observation = self.router.observe(
                final_cycle,
                deadline_monotonic=self._monotonic() + self.successor_timeout_seconds,
            )
            if final_observation.is_unknown:
                final_reason = final_observation.reason_code or "UNKNOWN_FINAL_SCREEN"
            else:
                valid, final_reason = authoritative_source.revalidate_target(
                    final_observation,
                    target_identity,
                )
                if valid:
                    final_reason = None
        except Exception as exc:
            final_reason = f"FINAL_PRE_DISPATCH_REVALIDATION_FAILED:{type(exc).__name__}"
        if final_reason is not None:
            return self._pretransport_abort(
                action,
                final_reason,
                source=source,
                pre_dispatch=pre,
            )
        # Recheck the fence after the final perception cycle as well.  An
        # emergency can be requested by that cycle's owner before the
        # transport boundary; this read is the last admission check.
        try:
            transport_fence = self._ensure_fence(action_id=action.action_id)
        except Exception as exc:
            transport_fence = None
            transport_fence_error = f"FENCE_VALIDATION_FAILED:{type(exc).__name__}"
        else:
            transport_fence_error = None
        if transport_fence is None or not transport_fence.valid:
            reason = transport_fence_error or transport_fence.reason or "FENCE_VALIDATION_FAILED"
            return self._pretransport_abort(
                action,
                reason,
                source=source,
                pre_dispatch=pre,
            )
        try:
            emergency_requested = bool(getattr(self.session, "emergency_requested", False))
        except Exception:
            emergency_requested = True
        if emergency_requested:
            return self._pretransport_abort(
                action,
                "EMERGENCY_STOP_REQUESTED",
                source=source,
                pre_dispatch=pre,
            )

        # No capture, recognition, or state mutation occurs between this final
        # revalidation and transport.  A changed source or target therefore
        # cannot reach the external boundary.
        transport_attempted = True

        try:
            raw_result = self._transport(intent, final_cycle)
            transport_succeeded = self._transport_success(raw_result)

        except Exception as exc:
            # Even an exception after the transport boundary invalidates the
            # pre-dispatch recognition cache; the action is durable UNKNOWN.
            try:
                self.router.invalidate()
            except Exception:
                pass
            reason = f"TRANSPORT_EXCEPTION:{type(exc).__name__}"
            terminal = self._mark_unknown_after_transport(
                action,
                reason,
                transport_summary="transport raised after DISPATCHING commit",
            )
            self._release_after_emergency(force=True, reason=f"post-transport unknown: {reason}")
            result = ActionResult(
                ActionOutcome.UNKNOWN,
                reason,
                terminal or action,
                source,
                pre,
                None,
                True,
                None,
            )
            return result
        successor: ScreenObservation | None = None
        successor_reason = "SUCCESSOR_DEADLINE"
        successor_exception = False
        constraint: SuccessorConstraint | None = None
        constraint_matched = False
        try:
            self.router.invalidate()
        except Exception as exc:
            successor_exception = True
            successor_reason = f"CACHE_INVALIDATION_FAILED:{type(exc).__name__}"
        if not successor_exception:
            try:
                deadline = self._monotonic() + (
                    self.successor_timeout_seconds
                    if successor_timeout_seconds is None
                    else float(successor_timeout_seconds)
                )
                configured_constraint = self.successor_constraint if expected_successor is None else expected_successor
                constraint = self._constraint(configured_constraint)
                if self._monotonic() < deadline:
                    post_cycle = self.session.capture("successor")
                    successor = self.router.observe(post_cycle, deadline_monotonic=deadline)
                    if successor.is_unknown:
                        successor_reason = successor.reason_code or "UNKNOWN_SUCCESSOR"
                    elif constraint is None:
                        successor_reason = "SUCCESSOR_CONSTRAINT_REQUIRED"
                    else:
                        # Evaluate exactly once.  A predicate may have side effects
                        # or raise; a second evaluation could authorize input.
                        try:
                            constraint_matched = bool(constraint.accepts(successor))
                        except Exception as exc:
                            successor_exception = True
                            successor_reason = f"SUCCESSOR_CONSTRAINT_EXCEPTION:{type(exc).__name__}"
                        else:
                            successor_reason = "SUCCESSOR_VERIFIED" if constraint_matched else "SUCCESSOR_CONSTRAINT_FAILED"
                else:
                    successor_reason = "SUCCESSOR_DEADLINE"
            except Exception as exc:
                successor_exception = True
                successor_reason = f"SUCCESSOR_CAPTURE_FAILED:{type(exc).__name__}"
        matched = constraint_matched
        if matched:
            outcome = ActionOutcome.SUCCEEDED
            terminal_state = ActionState.SUCCEEDED
        elif successor_exception or transport_succeeded:
            outcome = ActionOutcome.UNKNOWN
            terminal_state = ActionState.UNKNOWN
        else:
            outcome = ActionOutcome.NO_EFFECT
            terminal_state = ActionState.NO_EFFECT
        terminal: ActionRecord | None = None
        commit_error: str | None = None
        try:
            terminal = self._state_call(
                "transition_action",
                action.action_id,
                terminal_state,
                expected_state=ActionState.DISPATCHING,
                outcome_reason=successor_reason,
                successor_screen=successor.screen.value if successor and not successor.is_unknown else None,
                successor_binding_digest=self._successor_digest(successor),
                transport_summary="one transport call",
                consequence_summary="verified successor" if matched else "successor not verified",
                now_utc_epoch=self._utc(),
            )
        except Exception as exc:
            commit_error = f"TERMINAL_COMMIT_FAILED:{type(exc).__name__}"
        if terminal is not None:
            try:
                valid_terminal = ActionState(getattr(terminal, "state", None)) is terminal_state
            except (TypeError, ValueError):
                valid_terminal = False
            if not valid_terminal:
                terminal = None
                commit_error = commit_error or "TERMINAL_COMMIT_INVALID_RESULT"
        if terminal is None:
            commit_error = commit_error or "TERMINAL_COMMIT_DENIED"
            terminal = self._mark_unknown_after_transport(
                action,
                commit_error,
                transport_summary="terminal action commit was not confirmed",
                consequence_summary="post-transport reconciliation required",
            )
            outcome = ActionOutcome.UNKNOWN
            successor_reason = commit_error
            self._release_after_emergency(force=True, reason=f"post-transport unknown: {commit_error}")
        else:
            action = terminal
            if outcome is ActionOutcome.UNKNOWN:
                self._release_after_emergency(force=True, reason=f"post-transport unknown: {successor_reason}")
            else:
                self._release_after_emergency()
        action = terminal or action
        return ActionResult(outcome, successor_reason, action, source, pre, successor, transport_attempted, transport_succeeded)

    def _ensure_fence(self, *, action_id: str | None = None) -> DispatchValidation:
        """Use the strengthened fence hook, with legacy validation fallback."""

        method = getattr(self.session, "ensure_fence", None)
        if not callable(method):
            method = getattr(self.session, "validate_fence", None)
        if not callable(method):
            raise TypeError("session has no fence validation contract")
        if action_id is None:
            return method()
        try:
            parameters = inspect.signature(method).parameters.values()
            accepts_kwargs = any(item.kind is item.VAR_KEYWORD for item in parameters)
            accepts_action_id = any(
                item.name == "action_id"
                and item.kind in (item.POSITIONAL_OR_KEYWORD, item.KEYWORD_ONLY)
                for item in parameters
            )
        except (TypeError, ValueError):
            accepts_kwargs = True
            accepts_action_id = False
        if accepts_kwargs or accepts_action_id:
            return method(action_id=action_id)
        return method()

    def _state_call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Invoke a state mutation with every available owner/run/lease token."""

        method = getattr(self.session.state_manager, method_name)
        token_getter = getattr(self.session, "_token_kwargs", None)
        if callable(token_getter):
            kwargs = {**token_getter(include_run=True), **kwargs}
        authority_call = getattr(self.session, "_authority_call", None)
        if callable(authority_call):
            return authority_call(method, *args, **kwargs)
        return method(*args, **kwargs)
    def _mark_unknown_after_transport(
        self,
        action: ActionRecord,
        reason: str,
        *,
        transport_summary: str,
        consequence_summary: str | None = None,
    ) -> ActionRecord | None:
        """Persist UNKNOWN through the post-transport reconciliation path.

        This path is intentionally separate from pre-transport aborts.  It may
        cross a disabled or generation-changed service boundary, but still
        requires the exact run/lease identity supplied by the session.
        """

        authority = self.session.state_manager
        post_transport = getattr(authority, "mark_post_transport_unknown", None)
        if callable(post_transport):
            try:
                marked = self._state_call(
                    "mark_post_transport_unknown",
                    action.action_id,
                    outcome_reason=reason,
                    transport_summary=transport_summary,
                    consequence_summary=consequence_summary,
                    now_utc_epoch=self._utc(),
                )
            except Exception:
                marked = None
            try:
                marked_unknown = marked is not None and ActionState(getattr(marked, "state", None)) is ActionState.UNKNOWN
            except (TypeError, ValueError):
                marked_unknown = False
            if marked_unknown:
                return marked
        try:
            marked = self._state_call(
                "transition_action",
                action.action_id,
                ActionState.UNKNOWN,
                expected_state=ActionState.DISPATCHING,
                outcome_reason=reason,
                transport_summary=transport_summary,
                consequence_summary=consequence_summary,
                now_utc_epoch=self._utc(),
            )
        except Exception:
            marked = None
        try:
            marked_unknown = marked is not None and ActionState(getattr(marked, "state", None)) is ActionState.UNKNOWN
        except (TypeError, ValueError):
            marked_unknown = False
        if marked_unknown:
            return marked
        getter = getattr(authority, "get_action", None)
        if callable(getter):
            try:
                current = getter(action.action_id)
            except Exception:
                current = None
            if current is not None and getattr(current, "state", None) is ActionState.UNKNOWN:
                return current
        return None

    def _blocked_before_transport(
        self,
        reason: str,
        *,
        action: ActionRecord | None = None,
        source: ScreenObservation | None,
        pre_dispatch: ScreenObservation | None = None,
    ) -> ActionResult:
        """Block one pre-transport path and always clean up its ownership.

        A reservation is a budget mutation even though it cannot cross the
        external boundary.  When one exists, route it through the guarded
        pre-transport abort path before terminalizing the run.  Earlier
        admission failures have no action to abort, so force the run through
        ``STOP_REQUESTED`` and release the session's exact lease identity.
        """

        if action is not None:
            try:
                action_state = ActionState(getattr(action, "state", None))
            except (TypeError, ValueError):
                action_state = None
            if action_state in {ActionState.RESERVED, ActionState.DISPATCHING}:
                return self._pretransport_abort(
                    action,
                    reason,
                    source=source,
                    pre_dispatch=pre_dispatch,
                )
        self._release_after_emergency(force=True, reason=reason)
        return self._blocked(
            reason,
            action=action,
            source=source,
            pre_dispatch=pre_dispatch,
        )


    def _pretransport_abort(
        self,
        action: ActionRecord,
        reason: str,
        *,
        source: ScreenObservation | None,
        pre_dispatch: ScreenObservation | None,
    ) -> ActionResult:
        """Durably abort a RESERVED/DISPATCHING action before transport."""

        try:
            action_state = ActionState(getattr(action, "state", None))
        except (TypeError, ValueError):
            action_state = None
        try:
            if action_state is ActionState.RESERVED:
                # RESERVED has not crossed the transport boundary; the normal
                # transition refunds the reserved budget under the exact fence.
                aborted = self._state_call(
                    "transition_action",
                    action.action_id,
                    ActionState.BLOCKED,
                    expected_state=ActionState.RESERVED,
                    outcome_reason=reason,
                    transport_summary="transport not called",
                    consequence_summary="pre-transport abort",
                    now_utc_epoch=self._utc(),
                )
            elif action_state is ActionState.DISPATCHING:
                # DISPATCHING needs the proof-carrying abort API so it cannot
                # be relabeled through a generic terminal transition.
                aborted = self._state_call(
                    "abort_pretransport_action",
                    action.action_id,
                    ActionState.BLOCKED,
                    expected_state=ActionState.DISPATCHING,
                    transport_attempted=False,
                    outcome_reason=reason,
                    transport_summary="transport not called",
                    consequence_summary="pre-transport abort",
                    now_utc_epoch=self._utc(),
                )
            else:
                aborted = None
        except Exception:
            aborted = None
        # A pre-transport abort is the emergency cleanup path: terminalize a
        # STOP_REQUESTED run and release its exact singleton lease even when the
        # session did not observe the stop through its convenience property.
        self._release_after_emergency(force=True, reason=reason)
        return self._blocked(
            reason,
            action=aborted or action,
            source=source,
            pre_dispatch=pre_dispatch,
        )

    def _release_after_emergency(
        self,
        *,
        force: bool = False,
        reason: str = "emergency stop after in-flight transport",
    ) -> None:
        try:
            requested = bool(getattr(self.session, "emergency_requested", False))
        except Exception:
            requested = True
        if not requested and not force:
            return
        if force:
            # A flow-generation race need not have emitted STOP_REQUESTED.  Move
            # the run into the safe fenced state before project_terminal so a
            # post-transport UNKNOWN can never leave an active run behind.
            try:
                current = self.session.refresh_run()
                if current is not None and current.state in {
                    RunState.CLAIMED,
                    RunState.RUNNING,
                    RunState.RECOVERING,
                }:
                    self._state_call(
                        "transition_run",
                        current.run_id,
                        RunState.STOP_REQUESTED,
                        expected_state=current.state,
                        reason=reason,
                        now_utc_epoch=self._utc(),
                    )
            except Exception:
                pass
        release = getattr(self.session, "release", None)
        if not callable(release):
            return
        try:
            release(outcome="BLOCKED", reason=reason)
        except Exception:
            # The action may already have crossed the external boundary.  Release
            # is best-effort cleanup and must not turn a typed result into an exception.
            pass

    @staticmethod
    def _successor_digest(observation: ScreenObservation | None) -> str | None:
        if observation is None or observation.is_unknown:
            return None
        if observation.stable_roi_digest:
            return observation.stable_roi_digest
        for target in observation.targets:
            if target.stable_roi_digest:
                return target.stable_roi_digest
        return None


    def _utc(self) -> float:
        clock = getattr(self.session, "_utc", None)
        return float(clock()) if callable(clock) else time.time()


    def _transport(self, intent: SemanticActionIntent, cycle: CaptureCycle) -> Any:
        transport = self.transport
        if transport is None:
            transport = getattr(self.session.adapter, "execute", None)
        if not callable(transport):
            raise ActionExecutionError("no transport adapter is configured")
        try:
            params = inspect.signature(transport).parameters.values()
            positional = [item for item in params if item.kind in (item.POSITIONAL_ONLY, item.POSITIONAL_OR_KEYWORD)]
            variadic = any(item.kind is item.VAR_POSITIONAL for item in params)
        except (TypeError, ValueError):
            positional, variadic = (), True
        if variadic or len(positional) >= 2:
            return transport(intent, cycle)
        return transport(intent)

    @staticmethod
    def _transport_success(result: Any) -> bool:
        if hasattr(result, "transport_calls"):
            try:
                return int(result.transport_calls) > 0
            except (TypeError, ValueError):
                return False
        if hasattr(result, "transported"):
            return bool(result.transported)
        return bool(result)

    @staticmethod
    def _constraint(value: Any) -> SuccessorConstraint | None:
        if value is None:
            return None
        if isinstance(value, SuccessorConstraint):
            return value
        accepts = getattr(value, "accepts_successor", None)
        if callable(accepts):
            return SuccessorConstraint(predicate=accepts)
        if callable(value):
            return SuccessorConstraint(predicate=value)
        return SuccessorConstraint(value)

    @staticmethod
    def _blocked(
        reason: str,
        *,
        action: ActionRecord | None = None,
        source: ScreenObservation | None = None,
        pre_dispatch: ScreenObservation | None = None,
    ) -> ActionResult:
        return ActionResult(ActionOutcome.BLOCKED, str(reason), action, source, pre_dispatch, None, False, None)


__all__ = ["ActionExecutionError", "ActionExecutor", "ActionOutcome", "ActionResult", "SuccessorConstraint"]
