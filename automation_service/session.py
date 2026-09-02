"""Fenced runtime-session boundary for the canonical SQLite authority.

This module adapts existing device adapters; it does not own a second state store or
transport implementation.  A session owns one occurrence claim, captures immutable
cycles, and releases its run on every terminal/close path.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import inspect
import math
import time
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

from .state import BotStateManager, DispatchValidation, RunRecord, RunState
from .screens import CaptureCycle


class SessionError(RuntimeError):
    """Session admission, ownership, or generation-fence failure."""


class CaptureAdapter(Protocol):
    def capture(self) -> Any:
        ...


_UNSET = object()


@dataclass(frozen=True)
class SessionFence:
    """Immutable ownership and generation tokens captured when a run is claimed.

    The optional token fields keep this boundary compatible with older state
    authorities while allowing newer authorities to require process/run/lease
    identity at every mutation.
    """

    run_id: str
    flow_id: str
    service_generation: int
    flow_generation: int
    owner_instance_id: str
    process_start_token: str | None = None
    run_token: str | None = None
    lease_generation: int | None = None


class RuntimeSession:
    """One fenced run backed solely by :class:`BotStateManager`."""

    def __init__(
        self,
        state_manager: BotStateManager,
        adapter: CaptureAdapter,
        *,
        flow_id: str,
        reset_id: str,
        owner_instance_id: str | None = None,
        process_start_token: str | None = None,
        run_token: str | None = None,
        lease_generation: int | None = None,
        mode: str = "manual",
        operator_request_id: str | None = None,
        manual_request_id: str | None = None,
        operator_request: str | None = None,
        lease_ttl_seconds: float = 60.0,
        max_inputs: int = 1,
        max_actions: int = 1,
        monotonic_clock: Callable[[], float] = time.monotonic,
        utc_clock: Callable[[], float] = time.time,
        session_id: str | None = None,
    ) -> None:
        if not callable(getattr(state_manager, "claim_occurrence", None)):
            raise TypeError("state_manager must be a BotStateManager-compatible authority")
        if not callable(getattr(adapter, "capture", None)):
            raise TypeError("adapter must provide capture()")
        if mode not in {"manual", "scheduled"}:
            raise SessionError("mode must be manual or scheduled")
        if type(max_inputs) is not int or max_inputs < 0:
            raise SessionError("max_inputs must be non-negative")
        if type(max_actions) is not int or max_actions < 0:
            raise SessionError("max_actions must be non-negative")
        if isinstance(lease_ttl_seconds, bool) or not math.isfinite(float(lease_ttl_seconds)) or float(lease_ttl_seconds) <= 0:
            raise SessionError("lease TTL must be finite and positive")
        request_values = [value for value in (operator_request_id, manual_request_id, operator_request) if value is not None]
        if request_values and any(str(value) != str(request_values[0]) for value in request_values[1:]):
            raise SessionError("operator and manual request IDs disagree")
        supplied_request_id = None if not request_values else request_values[0]
        if mode == "scheduled" and supplied_request_id is not None:
            raise SessionError("scheduled sessions cannot carry an operator request ID")
        self.state_manager = state_manager
        self.adapter = adapter
        self.flow_id = str(flow_id)
        self.reset_id = str(reset_id)
        self._owner_explicit = owner_instance_id is not None
        self.owner_instance_id = str(owner_instance_id or getattr(state_manager, "owner_instance_id", ""))
        if not self.flow_id.strip() or not self.reset_id.strip() or not self.owner_instance_id.strip():
            raise SessionError("session requires flow, reset, and owner identity")
        self.process_start_token = None if process_start_token is None else str(process_start_token)
        self.run_token = None if run_token is None else str(run_token)
        self.lease_generation = lease_generation
        if self.process_start_token is not None and not self.process_start_token.strip():
            raise SessionError("process start token cannot be blank")
        if self.run_token is not None and not self.run_token.strip():
            raise SessionError("run token cannot be blank")
        if self.lease_generation is not None and (
            type(self.lease_generation) is not int or self.lease_generation < 0
        ):
            raise SessionError("lease generation must be non-negative")
        self.mode = mode
        self.operator_request_id = (
            None
            if mode == "scheduled"
            else str(supplied_request_id or f"manual:{self.flow_id}:{self.reset_id}")
        )
        if self.operator_request_id is not None and not self.operator_request_id.strip():
            raise SessionError("operator request ID cannot be blank")
        self.lease_ttl_seconds = float(lease_ttl_seconds)
        self.max_inputs = max_inputs
        self.max_actions = max_actions
        self._monotonic = monotonic_clock
        self._utc = utc_clock
        self.session_id = str(session_id or uuid4().hex)
        if not self.session_id.strip():
            raise SessionError("session identity is required")
        self._run: RunRecord | None = None
        self._closed = False
        self._fenced = False
        self._emergency_requested = False
        self._capture_ordinal = 0
        self._last_capture: CaptureCycle | None = None

    @property
    def run(self) -> RunRecord | None:
        return self._run

    @property
    def run_id(self) -> str | None:
        return self._run.run_id if self._run is not None else None

    @property
    def emergency_requested(self) -> bool:
        return self._emergency_requested
    @property
    def fenced(self) -> bool:
        return self._fenced

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def last_capture(self) -> CaptureCycle | None:
        return self._last_capture

    @property
    def fence(self) -> SessionFence | None:
        if self._run is None:
            return None
        return SessionFence(
            self._run.run_id,
            self._run.flow_id,
            self._run.service_generation,
            self._run.claimed_flow_generation,
            self._run.owner_instance_id,
            getattr(self._run, "process_start_token", self.process_start_token),
            getattr(self._run, "run_token", self.run_token),
            getattr(self._run, "lease_generation", self.lease_generation),
        )

    def _token_kwargs(self, *, include_run: bool = False) -> dict[str, Any]:
        """Return the strongest available ownership fence for authority calls."""

        run = self._run
        process_token = self.process_start_token
        if process_token is None and run is not None:
            process_token = getattr(run, "process_start_token", None)
        run_token = self.run_token if include_run else None
        if run_token is None and include_run and run is not None:
            run_token = getattr(run, "run_token", None)
        lease_generation = self.lease_generation
        if lease_generation is None and run is not None:
            lease_generation = getattr(run, "lease_generation", None)
        return {
            "owner_instance_id": self.owner_instance_id,
            "process_start_token": process_token,
            "run_token": run_token,
            "lease_generation": lease_generation,
        }

    @staticmethod
    def _authority_call(method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Call old and strengthened authorities without dropping supported tokens."""

        try:
            parameters = inspect.signature(method).parameters.values()
            accepts_kwargs = any(item.kind is item.VAR_KEYWORD for item in parameters)
            accepted = {
                item.name
                for item in parameters
                if item.kind in (item.POSITIONAL_OR_KEYWORD, item.KEYWORD_ONLY)
            }
        except (TypeError, ValueError):
            accepts_kwargs = True
            accepted = set()
        if not accepts_kwargs:
            kwargs = {name: value for name, value in kwargs.items() if name in accepted}
        return method(*args, **kwargs)
    def _sync_tokens_from_run(self, run: RunRecord) -> None:
        """Fill tokens learned during an implicit claim without erasing drift.

        Once a caller supplies (or mutates) a token, it is the caller's
        authority fence.  Refreshing a run must not silently replace a drifted
        process/lease token with the value persisted in SQLite.
        """

        process_token = getattr(run, "process_start_token", None)
        run_token = getattr(run, "run_token", None)
        lease_generation = getattr(run, "lease_generation", None)
        if self.process_start_token is None and process_token is not None:
            self.process_start_token = str(process_token)
        if self.run_token is None and run_token is not None:
            self.run_token = str(run_token)
        if self.lease_generation is None and lease_generation is not None:
            self.lease_generation = int(lease_generation)

    def _adopt_matching_lease(self) -> None:
        """Adopt a lease acquired before this session was constructed.

        A pre-acquired lease is a valid admission path when all supplied
        identity fields match it.  Missing fields are learned from the
        authority; mismatches are deliberately left untouched so claim fails
        closed rather than borrowing another owner's lease.
        """

        get_lease = getattr(self.state_manager, "get_service_lease", None)
        if not callable(get_lease):
            return
        try:
            lease = get_lease()
        except Exception:
            return
        owner = getattr(lease, "owner_instance_id", None)
        process_token = getattr(lease, "process_start_token", None)
        generation = getattr(lease, "lease_generation", None)
        if owner != self.owner_instance_id or process_token is None or type(generation) is not int or generation < 1:
            return
        if self.process_start_token is not None and self.process_start_token != str(process_token):
            return
        if self.lease_generation is not None and self.lease_generation != generation:
            return
        self.process_start_token = str(process_token)
        self.lease_generation = generation


    def claim(self) -> RunRecord | None:
        """Atomically claim this occurrence, failing closed when disabled or busy."""

        if self._closed:
            raise SessionError("session is closed")
        if self._run is not None:
            return self._run
        try:
            service = self.state_manager.get_service()
        except Exception:
            self._emergency_requested = True
            return None
        if not service.enabled:
            self._emergency_requested = True
            return None
        run: RunRecord | None = None
        try:
            claim_kwargs: dict[str, Any] = {
                "mode": self.mode,
                "max_inputs": self.max_inputs,
                "max_actions": self.max_actions,
                "now_utc_epoch": self._utc(),
            }
            if self.operator_request_id is not None:
                claim_kwargs["operator_request_id"] = self.operator_request_id
            # With no supplied tokens, let the authority atomically acquire its
            # own lease.  Partial token sets are passed through and fail closed.
            explicit_fence = (
                self._owner_explicit
                or self.process_start_token is not None
                or self.lease_generation is not None
            )
            if explicit_fence:
                self._adopt_matching_lease()
                if self.lease_generation is None:
                    acquire_lease = getattr(self.state_manager, "acquire_service_lease", None)
                    if callable(acquire_lease):
                        process_token = self.process_start_token
                        if process_token is None:
                            process_token = getattr(self.state_manager, "process_start_token", None)
                        try:
                            lease = self._authority_call(
                                acquire_lease,
                                owner_instance_id=self.owner_instance_id,
                                process_start_token=process_token,
                                process_id=getattr(self.state_manager, "process_id", None),
                                lease_ttl_seconds=self.lease_ttl_seconds,
                                now_utc_epoch=self._utc(),
                            )
                        except Exception:
                            lease = None
                        if (
                            lease is not None
                            and getattr(lease, "owner_instance_id", None) == self.owner_instance_id
                            and getattr(lease, "process_start_token", None) is not None
                            and type(getattr(lease, "lease_generation", None)) is int
                            and getattr(lease, "lease_generation", 0) >= 1
                        ):
                            self.process_start_token = str(lease.process_start_token)
                            self.lease_generation = int(lease.lease_generation)
                claim_kwargs.update(self._token_kwargs())
            if self.run_token is not None:
                claim_kwargs["run_token"] = self.run_token
            run = self._authority_call(
                self.state_manager.claim_occurrence,
                self.flow_id,
                self.reset_id,
                **claim_kwargs,
            )
            # A caller may have acquired a lease before constructing this
            # session.  If that lease expired before claim, reacquire it with
            # the same owner/process identity and retry once with the new
            # generation.  A different owner or process token can never be
            # reacquired and therefore still fails closed.
            if run is None and self.lease_generation is not None:
                acquire_lease = getattr(self.state_manager, "acquire_service_lease", None)
                if callable(acquire_lease):
                    process_token = self.process_start_token
                    if process_token is None:
                        process_token = getattr(self.state_manager, "process_start_token", None)
                    try:
                        lease = self._authority_call(
                            acquire_lease,
                            owner_instance_id=self.owner_instance_id,
                            process_start_token=process_token,
                            lease_ttl_seconds=self.lease_ttl_seconds,
                            process_id=getattr(self.state_manager, "process_id", None),
                            now_utc_epoch=self._utc(),
                        )
                    except Exception:
                        lease = None
                    if lease is not None:
                        lease_owner = getattr(lease, "owner_instance_id", None)
                        lease_process = getattr(lease, "process_start_token", None)
                        lease_generation = getattr(lease, "lease_generation", None)
                        if (
                            lease_owner == self.owner_instance_id
                            and lease_process is not None
                            and type(lease_generation) is int
                            and lease_generation >= 1
                        ):
                            self.process_start_token = str(lease_process)
                            self.lease_generation = lease_generation
                            claim_kwargs.update(self._token_kwargs())
                            run = self._authority_call(
                                self.state_manager.claim_occurrence,
                                self.flow_id,
                                self.reset_id,
                                **claim_kwargs,
                            )
        except Exception:
            self._emergency_requested = True
            return None
        if run is not None:
            self._run = run
            self._sync_tokens_from_run(run)
            if run.state is RunState.CLAIMED:
                try:
                    started = self._authority_call(
                        self.state_manager.transition_run,
                        run.run_id,
                        RunState.RUNNING,
                        expected_state=RunState.CLAIMED,
                        now_utc_epoch=self._utc(),
                        **self._token_kwargs(include_run=True),
                    )
                except Exception:
                    started = None
                if started is None or getattr(started, "state", None) is not RunState.RUNNING:
                    self._fenced = True
                    self._emergency_requested = True
                    self.release(outcome="BLOCKED", reason="CLAIMED_TO_RUNNING_FAILED")
                    return None
                self._run = started
                self._sync_tokens_from_run(started)
        return self._run

    acquire = claim
    start = claim

    def __enter__(self) -> "RuntimeSession":
        if self.claim() is None:
            raise SessionError("runtime session claim denied")
        return self

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        self.close()

    def refresh_run(self) -> RunRecord | None:
        if self._run is None:
            return None
        try:
            current = self.state_manager.get_run(self._run.run_id)
        except Exception:
            return None
        if current is not None:
            self._run = current
            self._sync_tokens_from_run(current)
        return current

    def validate_fence(self, *, action_id: str | None = None) -> DispatchValidation:
        """Read the atomic service/flow/run/lease fence immediately before dispatch."""

        if self._run is None:
            return DispatchValidation(False, "RUN_NOT_CLAIMED")
        if self._fenced:
            return DispatchValidation(False, "SESSION_FENCED")
        try:
            validation = self._authority_call(
                self.state_manager.validate_dispatch,
                self._run.run_id,
                action_id=action_id,
                **self._token_kwargs(include_run=True),
            )
            if not isinstance(validation, DispatchValidation):
                return DispatchValidation(False, "FENCE_VALIDATION_INVALID_RESULT")
        except Exception as exc:
            return DispatchValidation(False, f"FENCE_VALIDATION_FAILED:{type(exc).__name__}")
        try:
            self.refresh_run()
        except Exception:
            return DispatchValidation(False, "FENCE_REFRESH_FAILED")
        return validation
    def ensure_fence(self, *, action_id: str | None = None) -> DispatchValidation:
        """Return a typed current fence result for transport admission."""

        try:
            validation = self.validate_fence(action_id=action_id)
        except Exception:
            return DispatchValidation(False, "FENCE_VALIDATION_FAILED")
        if not isinstance(validation, DispatchValidation):
            return DispatchValidation(False, "FENCE_VALIDATION_INVALID_RESULT")
        return validation


    def heartbeat(self) -> RunRecord | None:
        """Renew the exact service lease and run heartbeat as one admission check."""

        if self._run is None or self._closed or self._fenced:
            return None
        tokens = self._token_kwargs(include_run=True)
        lease_result: Any = None
        run_result: RunRecord | None = None
        try:
            renew = getattr(self.state_manager, "renew_service_lease", None)
            if callable(renew):
                lease_result = self._authority_call(
                    renew,
                    lease_ttl_seconds=self.lease_ttl_seconds,
                    now_utc_epoch=self._utc(),
                    **{key: tokens[key] for key in ("owner_instance_id", "process_start_token", "lease_generation")},
                )
        except Exception:
            lease_result = None
        try:
            run_result = self._authority_call(
                self.state_manager.heartbeat_run,
                self._run.run_id,
                now_utc_epoch=self._utc(),
                **tokens,
            )
        except Exception:
            run_result = None
        lease_matches = (
            lease_result is not None
            and getattr(lease_result, "owner_instance_id", None) == self.owner_instance_id
            and getattr(lease_result, "process_start_token", None) == tokens["process_start_token"]
            and getattr(lease_result, "lease_generation", None) == tokens["lease_generation"]
        )
        if not lease_matches or run_result is None:
            self._fence_session("HEARTBEAT_FENCE_FAILED")
            return None
        self._run = run_result
        self._sync_tokens_from_run(run_result)
        return run_result

    def _fence_session(self, reason: str) -> None:
        """Fence and clean up after losing either half of the heartbeat."""

        self._fenced = True
        self._emergency_requested = True
        if not self._closed:
            try:
                current = self.refresh_run()
                if current is not None and current.state in {
                    RunState.CLAIMED,
                    RunState.RUNNING,
                    RunState.RECOVERING,
                }:
                    stopped = self._authority_call(
                        self.state_manager.transition_run,
                        current.run_id,
                        RunState.STOP_REQUESTED,
                        expected_state=current.state,
                        reason=reason,
                        now_utc_epoch=self._utc(),
                        **self._token_kwargs(include_run=True),
                    )
                    if stopped is not None:
                        self._run = stopped
                self.release(outcome="BLOCKED", reason=reason)
                return
            except Exception:
                pass
        self._release_service_lease()

    def capture(self, label: str | None = None) -> CaptureCycle:
        """Capture once and expose one immutable event to all recognition stages."""

        if self._closed:
            raise SessionError("session is closed")
        if self._run is None:
            raise SessionError("capture requires an acquired run")
        if self._run.state is not RunState.RUNNING:
            raise SessionError("capture requires a running run")
        self._capture_ordinal += 1
        sample = self._capture_adapter(label)
        if isinstance(sample, CaptureCycle):
            cycle = sample
            if cycle.capture_ordinal == 0:
                cycle = CaptureCycle(
                    capture_id=cycle.capture_id,
                    frame_hash=cycle.frame_hash,
                    payload=cycle.payload,
                    captured_monotonic=cycle.captured_monotonic or self._monotonic(),
                    capture_ordinal=self._capture_ordinal,
                    width=cycle.width,
                    height=cycle.height,
                    metadata=cycle.metadata,
                )
        else:
            cycle = self._cycle_from_sample(sample)
        self._last_capture = cycle
        return cycle

    def request_emergency_stop(self, reason: str = "emergency stop") -> Any:
        """Fence future claims/dispatches; in-flight transport is not interrupted."""

        self._emergency_requested = True
        result = self.state_manager.set_service_enabled(False, emergency_reason=reason, now_utc_epoch=self._utc())
        self.refresh_run()
        return result

    emergency_stop = request_emergency_stop
    stop = request_emergency_stop

    def release(
        self,
        *,
        outcome: str = "ABANDONED",
        reason: str = "session released",
        retry_not_before_utc: float | None | object = _UNSET,
    ) -> RunRecord | None:
        """Terminalize this run and release singleton ownership exactly once."""

        if self._closed:
            self._release_service_lease()
            return self._run
        self._closed = True
        if self._run is None:
            self._release_service_lease()
            return None
        current = self.refresh_run()
        if current is None:
            self._release_service_lease()
            return None
        if current.state in {
            RunState.SUCCEEDED,
            RunState.DEFERRED,
            RunState.BLOCKED,
            RunState.FAILED,
            RunState.ABANDONED,
        }:
            self._release_service_lease()
            return current
        target = self._terminal_state(outcome)
        kwargs = {
            **self._token_kwargs(include_run=True),
            "expected_state": current.state,
            "reason": reason,
            "outcome": outcome,
            "owner_instance_id": self.owner_instance_id,
            "now_utc_epoch": self._utc(),
        }
        if retry_not_before_utc is not _UNSET:
            kwargs["retry_not_before_utc"] = retry_not_before_utc
        try:
            project = getattr(self.state_manager, "project_terminal", None)
            if callable(project):
                updated = self._authority_call(project, current.run_id, target, **kwargs)
            else:
                updated = self._authority_call(
                    self.state_manager.transition_run,
                    current.run_id,
                    target,
                    **kwargs,
                )
        except Exception:
            updated = None
        if updated is not None:
            self._run = updated
            self._sync_tokens_from_run(updated)
        else:
            try:
                self._run = self.state_manager.get_run(current.run_id)
            except Exception:
                self._run = current
        self._release_service_lease()
        return self._run

    def close(self) -> RunRecord | None:
        """Terminalize a closed occurrence without imposing a retry delay."""

        return self.release(
            outcome="BLOCKED",
            reason="session closed",
            retry_not_before_utc=self._utc(),
        )

    finish = release

    def _release_service_lease(self) -> None:
        """Best-effort release guarded by the session's exact lease tokens."""

        if self.lease_generation is None:
            return
        release = getattr(self.state_manager, "release_service_lease", None)
        if not callable(release):
            return
        try:
            self._authority_call(release, **self._token_kwargs())
        except Exception:
            pass

    @staticmethod
    def _terminal_state(outcome: str) -> RunState:
        value = str(outcome).upper()
        if value in {"SUCCEEDED", "SUCCESS"}:
            return RunState.SUCCEEDED
        if value in {"DEFERRED", "DEFER"}:
            return RunState.DEFERRED
        if value in {"FAILED", "FAILURE"}:
            return RunState.FAILED
        if value in {"BLOCKED", "UNKNOWN", "EMERGENCY_STOPPED"}:
            return RunState.BLOCKED
        return RunState.ABANDONED

    def _capture_adapter(self, label: str | None) -> Any:
        capture = self.adapter.capture
        try:
            params = inspect.signature(capture).parameters.values()
            positional = [item for item in params if item.kind in (item.POSITIONAL_ONLY, item.POSITIONAL_OR_KEYWORD)]
        except (TypeError, ValueError):
            positional = []
        if positional:
            return capture(label or f"{self.session_id}:capture:{self._capture_ordinal}")
        return capture()

    def _cycle_from_sample(self, sample: Any) -> CaptureCycle:
        frame_id = self._attribute(sample, "frame_id", None)
        envelope = self._attribute(sample, "envelope", None)
        if frame_id is None and envelope is not None:
            frame_id = self._attribute(envelope, "capture_id", None)
        capture_id = str(frame_id or f"{self.session_id}:{self._capture_ordinal}")
        payload = self._attribute(sample, "payload", None)
        if payload is None:
            payload = self._attribute(sample, "png", None)
        if payload is None:
            payload = self._attribute(sample, "frame", sample)
        supplied_hash = self._attribute(sample, "frame_sha256", None) or self._attribute(sample, "sha256", None)
        frame_hash = str(supplied_hash) if supplied_hash else self._hash_payload(payload)
        width, height = self._dimensions(sample, payload)
        metadata: dict[str, Any] = {"sample": sample}
        if envelope is not None:
            metadata["envelope"] = envelope
        return CaptureCycle(
            capture_id=capture_id,
            frame_hash=frame_hash,
            payload=payload,
            captured_monotonic=self._monotonic(),
            capture_ordinal=self._capture_ordinal,
            width=width,
            height=height,
            metadata=metadata,
        )

    @staticmethod
    def _attribute(value: Any, name: str, default: Any) -> Any:
        if isinstance(value, Mapping):
            return value.get(name, default)
        return getattr(value, name, default)

    @classmethod
    def _dimensions(cls, sample: Any, payload: Any) -> tuple[int | None, int | None]:
        width = cls._attribute(sample, "width", None)
        height = cls._attribute(sample, "height", None)
        frame = cls._attribute(sample, "frame", None)
        shape = cls._attribute(frame if frame is not None else payload, "shape", None)
        if shape is not None and len(shape) >= 2:
            height = height or int(shape[0])
            width = width or int(shape[1])
        return width, height

    @staticmethod
    def _hash_payload(payload: Any) -> str:
        if isinstance(payload, bytes):
            raw = payload
        elif isinstance(payload, bytearray):
            raw = bytes(payload)
        elif hasattr(payload, "tobytes") and callable(payload.tobytes):
            raw = payload.tobytes()
        else:
            raw = repr(payload).encode("utf-8", "replace")
        return hashlib.sha256(raw).hexdigest()


__all__ = ["CaptureAdapter", "RuntimeSession", "SessionError", "SessionFence"]
