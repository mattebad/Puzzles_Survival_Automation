"""Shared lifecycle for statically bound canonical service native routes.

The pnsctl composition root supplies one fixed driver per installed flow.  This
module owns only borrowed runtime/session/store lifecycle and retained evidence;
route drivers own recognition, action policy, and semantic result acceptance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from automation_service.native_execution import (
    NativeExecutionAccounting,
    NativeExecutionError,
    NativeFrameReference,
    NativeRouteContext,
    NativeRouteOutcome,
    NativeRouteRequest,
    NativeStartupOutcome,
)
from scripts.bluestacks_native_runtime import (
    LocalBlueStacksRuntime,
    captured_native_frame_from_png,
    portable_filename_component,
)
from scripts.home_atlas_bluestacks import identity_from_captured
from scripts.navigation_development_boundary import (
    CANONICAL_ACTION_STORE_PATH,
    DevelopmentInitialObservation,
    DevelopmentSession,
    RuntimeInputLock,
    open_canonical_action_store,
)
from scripts.startup_recovery import recover_contextual_startup_overlay
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID
from tasks.runtime_identity import BLUESTACKS_ADB, BLUESTACKS_SERIAL
from safe_action_core.path_safety import UnsafePathError, require_no_untrusted_symlinks
from scripts.startup_normalization import is_clean_home_frame


NativeRouteDriver = Callable[[NativeRouteContext, Mapping[str, object]], Mapping[str, Any]]
NativeRouteValidator = Callable[[NativeRouteRequest], None]
ActionStoreFactory = Callable[[Path], Any]


@dataclass(frozen=True)
class _BindingConfig:
    flow_id: str
    product_id: str
    product_revision: str
    runtime_profile_id: str
    owner: str
    workflow: str
    max_inputs: int
    max_actions: int | None
    lease_seconds: float
    driver: NativeRouteDriver
    validator: NativeRouteValidator | None
    action_store_factory: ActionStoreFactory | None


class _NativeRouteContext:
    def __init__(
        self,
        request: NativeRouteRequest,
        *,
        owner: str,
        invocation_id: str,
        session: DevelopmentSession,
        runtime: LocalBlueStacksRuntime,
        action_store: Any,
        checkpoint: Callable[[], None],
    ) -> None:
        self.flow_id = request.flow_id
        self.product_id = request.product_id
        self.product_revision = request.product_revision
        self.runtime_profile_id = request.runtime_profile_id
        self.identity = request.identity
        self.previous_reset_id = request.previous_reset_id
        self.occurrence_key = request.occurrence_key
        self.owner = owner
        self.invocation_id = invocation_id
        self.session = session
        self.runtime = runtime
        self.action_store = action_store
        self.runtime_input_lock = request.runtime_input_lock
        self.checkpoint = checkpoint
        self.validate_identity = request.validate_identity
        self.max_inputs = request.max_inputs
        self.max_actions = request.max_actions
        self.settle_seconds = float(request.settle_seconds)
        self.utc_clock = request.utc_clock
        self.monotonic_clock = request.monotonic_clock
        self.initial_frame = session.observe(
            runtime.capture,
            label=f"{portable_filename_component(request.flow_id, field='flow id')}-initial-source",
        )
        self.initial_observation: Mapping[str, Any] = self._base_observation(self.initial_frame)
        self.startup_recovery: NativeStartupOutcome | None = None

    def is_clean_home(self, frame: Any) -> bool:
        self.checkpoint()
        return bool(is_clean_home_frame(frame))

    def _base_observation(self, frame: Any) -> dict[str, Any]:
        self.checkpoint()
        device_state = self.runtime.measure_device_state()
        foreground_package = self.runtime.measure_foreground_package()
        self.checkpoint()
        if device_state != "device" or foreground_package != "com.global.ztmslg":
            raise NativeExecutionError("native startup device or foreground package is not exact")
        return {
            "frame_sha256": frame.sha256,
            "device_state": device_state,
            "foreground_package": foreground_package,
            "native_width": int(frame.frame.shape[1]),
            "native_height": int(frame.frame.shape[0]),
            "runtime_profile_id": self.runtime_profile_id,
            "flow_id": self.flow_id,
            "occurrence_key": self.occurrence_key,
        }

    def bind_initial_observation(
        self,
        frame: Any | None = None,
        *,
        extra: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Bind the route-accepted fresh source to this session exactly once."""

        source = self.initial_frame if frame is None else frame
        if self.session.initial_observation is not None:
            raise NativeExecutionError("native route initial observation is already bound")
        self.checkpoint()
        observation = self._base_observation(source)
        if extra:
            protected = set(observation) & set(extra)
            if protected:
                raise NativeExecutionError(
                    f"route initial observation cannot replace boundary facts: {sorted(protected)}"
                )
            observation.update(dict(extra))
        try:
            frame_path = source.path.relative_to(self.session.session_directory).as_posix()
        except ValueError as exc:
            raise NativeExecutionError("native initial frame is outside its session") from exc
        typed = DevelopmentInitialObservation(
            observation,
            source.sha256,
            frame_path=frame_path,
            invocation_id=self.invocation_id,
        )
        self.session.set_initial_observation(typed)
        self.initial_frame = source
        self.initial_observation = typed.to_mapping()
        return self.initial_observation

    def prepare_startup(
        self,
        *,
        source_context: str,
        recognize_successor: Callable[[Any], bool],
        action_key: str,
        settle_seconds: float | None = None,
    ) -> NativeStartupOutcome:
        """Use the existing allowlisted recovery and adopt its exact input count."""

        self.checkpoint()
        source = self.initial_frame
        before = self.runtime.input_count
        result = None
        recovery_error: Exception | None = None
        try:
            result = recover_contextual_startup_overlay(
                self.runtime,
                source,
                source_context=source_context,
                recognize_successor=recognize_successor,
                action_key=action_key,
                settle_seconds=self.settle_seconds if settle_seconds is None else settle_seconds,
            )
        except Exception as exc:
            recovery_error = exc
        finally:
            after = self.runtime.input_count
            if type(before) is not int or type(after) is not int or after < before:
                raise NativeExecutionError("startup native input accounting is invalid")
            count = after - before
            try:
                self.session.adopt_retained_transport_count(count, source=str(self.runtime.events))
            except Exception as exc:
                raise NativeExecutionError("startup inputs could not be adopted by the session") from exc
        if result is None:
            startup = NativeStartupOutcome(
                source_context=source_context,
                reason=(
                    f"recovery_failed:{type(recovery_error).__name__}:{recovery_error}"
                    if recovery_error is not None
                    else "recovery_returned_no_result"
                ),
                input_count=count,
                reported_input_count=None,
                accounting_verified=False,
                resume_ready=False,
                dismissed=None,
                popup_absent=None,
                steps=(),
            )
            self.startup_recovery = startup
            if recovery_error is not None:
                raise NativeExecutionError(
                    f"known startup recovery failed: {type(recovery_error).__name__}: {recovery_error}"
                ) from recovery_error
            raise NativeExecutionError("known startup recovery returned no result")
        reported_count = result.input_count if type(result.input_count) is int else None
        startup_accounting_verified = reported_count is not None and reported_count == count
        steps = tuple(step.to_mapping(self.runtime.session) for step in result.steps)
        settled = result.settled_frame
        reference = None
        if settled is not None:
            _, reference = self.capture_reference(settled.path, settled.sha256)
        startup = NativeStartupOutcome(
            source_context=source_context,
            reason=result.reason,
            input_count=count,
            reported_input_count=reported_count,
            accounting_verified=startup_accounting_verified,
            resume_ready=bool(result.resume_ready and startup_accounting_verified),
            dismissed=result.dismissed,
            popup_absent=result.popup_absent,
            steps=steps,
            settled_frame=settled,
            settled_reference=reference,
        )
        self.startup_recovery = startup
        if not startup_accounting_verified:
            raise NativeExecutionError("startup recovery and native input counts disagree")
        if not startup.resume_ready or settled is None:
            raise NativeExecutionError(f"known startup did not reach its exact successor: {startup.reason}")
        self.bind_initial_observation(settled)
        return startup

    def capture_reference(
        self,
        path: str | Path,
        expected_sha256: str | None = None,
    ) -> tuple[Any, NativeFrameReference]:
        """Rebuild one unique current-session capture from its retained event."""

        candidate = Path(path)
        runtime_root = Path(self.runtime.session).resolve()
        if not candidate.is_absolute():
            candidate = runtime_root / candidate
        try:
            require_no_untrusted_symlinks(candidate)
            require_no_untrusted_symlinks(self.runtime.events)
        except UnsafePathError as exc:
            raise NativeExecutionError("native capture evidence contains an untrusted link") from exc
        resolved = candidate.resolve()
        try:
            relative = resolved.relative_to(runtime_root)
        except ValueError as exc:
            raise NativeExecutionError("native capture evidence is outside its runtime session") from exc
        if not resolved.is_file():
            raise NativeExecutionError("native capture evidence is missing")
        try:
            rows = [
                json.loads(line)
                for line in self.runtime.events.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, json.JSONDecodeError) as exc:
            raise NativeExecutionError("native capture event journal is unreadable") from exc
        captures = [row for row in rows if isinstance(row, dict) and row.get("type") == "capture"]
        matches = []
        for ordinal, row in enumerate(captures, 1):
            try:
                event_path = Path(row["path"]).resolve()
            except (KeyError, OSError, TypeError):
                continue
            if event_path == resolved:
                matches.append((ordinal, row))
        if len(matches) != 1:
            raise NativeExecutionError("native capture must have exactly one retained event")
        ordinal, row = matches[0]
        payload = resolved.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != row.get("sha256") or (
            expected_sha256 is not None and digest != expected_sha256
        ):
            raise NativeExecutionError("native capture digest differs from retained event")
        captured_monotonic = row.get("captured_monotonic")
        if (not isinstance(captured_monotonic, (int, float))
                or isinstance(captured_monotonic, bool)
                or not math_is_finite(captured_monotonic)):
            raise NativeExecutionError("native capture timestamp is invalid")
        timestamp = row.get("timestamp")
        if not isinstance(timestamp, str) or not timestamp.strip():
            raise NativeExecutionError("native capture UTC timestamp is missing")
        frame = captured_native_frame_from_png(
            payload,
            captured_monotonic=float(captured_monotonic),
            path=resolved,
        )
        reference = NativeFrameReference(
            frame_path=relative.as_posix(),
            frame_sha256=digest,
            observed_utc=timestamp,
            capture_ordinal=ordinal,
        )
        return frame, reference

    def replay_source(
        self,
        captured: Any,
        reference: NativeFrameReference,
        label: str,
    ) -> Mapping[str, Any]:
        self.checkpoint()
        if captured.sha256 != reference.frame_sha256:
            raise NativeExecutionError("native replay frame and reference digest differ")
        return {
            "source_frame": identity_from_captured(
                captured,
                session_id=str(self.runtime.session),
                ordinal=reference.capture_ordinal,
                label=label,
            ),
            "source_png": captured.png,
        }

    def accounting(self) -> NativeExecutionAccounting:
        return _accounting_snapshot(self.session, self.runtime, self.max_inputs)


def _accounting_snapshot(
    session: Any | None,
    runtime: Any | None,
    max_inputs: int,
) -> NativeExecutionAccounting:
    session_count = getattr(session, "input_count", None) if session is not None else None
    runtime_count = getattr(runtime, "input_count", None) if runtime is not None else None
    session_budget = getattr(session, "max_inputs", None) if session is not None else None
    runtime_budget = getattr(runtime, "max_inputs", None) if runtime is not None else None
    valid_types = all(type(value) is int for value in (session_count, runtime_count))
    if valid_types:
        count = max(session_count, runtime_count)
        verified = (
            session_count == runtime_count
            and 0 <= count <= max_inputs
            and type(session_budget) is int
            and session_budget == max_inputs
            and type(runtime_budget) is int
            and 0 <= runtime_budget <= max_inputs
        )
    else:
        count = 0
        verified = False
    return NativeExecutionAccounting(
        input_count=count,
        session_input_count=session_count if type(session_count) is int else 0,
        runtime_input_count=runtime_count if type(runtime_count) is int else 0,
        verified=verified,
    )


def math_is_finite(value: int | float) -> bool:
    return math.isfinite(float(value))


class _BoundNativeRoute:
    def __init__(self, config: _BindingConfig) -> None:
        self.flow_id = config.flow_id
        self.product_id = config.product_id
        self.product_revision = config.product_revision
        self.runtime_profile_id = config.runtime_profile_id
        self.max_inputs = config.max_inputs
        self.max_actions = config.max_actions
        self._config = config

    def _check_request(self, request: NativeRouteRequest) -> None:
        for field_name in (
            "flow_id",
            "product_id",
            "product_revision",
            "runtime_profile_id",
            "max_inputs",
            "max_actions",
        ):
            expected = getattr(self._config, field_name, getattr(self, field_name, None))
            actual = getattr(request, field_name)
            if actual != expected:
                raise NativeExecutionError(f"native request {field_name} does not match its fixed binding")
        lock = request.runtime_input_lock
        if not isinstance(lock, RuntimeInputLock) or not lock.held or lock.owner != "automation-service":
            raise NativeExecutionError("native route requires the actual held automation-service input lock")
        if Path(request.adb).resolve() != Path(BLUESTACKS_ADB).resolve():
            raise NativeExecutionError("native route requires the fixed BlueStacks ADB executable")
        if request.serial != BLUESTACKS_SERIAL:
            raise NativeExecutionError("native route requires the fixed BlueStacks serial")
        if self._config.validator is not None:
            self._config.validator(request)

    def run(self, request: NativeRouteRequest) -> NativeRouteOutcome:
        if not isinstance(request, NativeRouteRequest):
            raise NativeExecutionError("native route request has an unsupported type")
        invocation_id: str | None = None
        session: DevelopmentSession | None = None
        runtime: LocalBlueStacksRuntime | None = None
        store: Any | None = None
        leased = False
        context: _NativeRouteContext | None = None
        native_result: Mapping[str, Any] = {}
        partial_result: Mapping[str, Any] | None = None
        failure: Exception | None = None
        store_failure: Exception | None = None
        try:
            self._check_request(request)
            request.runtime_input_lock.assert_held(
                "automation-service", request.runtime_input_lock.invocation_id
            )
            request.checkpoint()
            request.validate_identity()
            request.runtime_input_lock.assert_held(
                "automation-service", request.runtime_input_lock.invocation_id
            )
            now = request.utc_clock()
            if not isinstance(now, (int, float)) or isinstance(now, bool) or not math_is_finite(now):
                raise NativeExecutionError("native route UTC clock is invalid")
            slug = portable_filename_component(request.flow_id, field="flow id")
            stamp = datetime.fromtimestamp(float(now), timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            invocation_id = f"{slug}-{stamp}-{uuid4().hex[:8]}"
            owner = self._config.owner

            def checkpoint() -> None:
                request.runtime_input_lock.assert_held(
                    "automation-service", request.runtime_input_lock.invocation_id
                )
                request.checkpoint()
                request.runtime_input_lock.assert_held(
                    "automation-service", request.runtime_input_lock.invocation_id
                )
                request.validate_identity()
                current = request.utc_clock()
                if (not isinstance(current, (int, float)) or isinstance(current, bool)
                        or not math_is_finite(current)):
                    raise NativeExecutionError("native route UTC clock is invalid")
                if store is not None and leased and not store.lease_valid_for(owner, current):
                    raise NativeExecutionError("native canonical action-store lease was lost")

            session = DevelopmentSession(
                owner=owner,
                invocation_id=invocation_id,
                session_directory=request.output_directory / invocation_id,
                max_inputs=request.max_inputs,
                runtime_input_lock=request.runtime_input_lock,
                checkpoint=checkpoint,
            )
            with session:
                checkpoint()
                store_factory = self._config.action_store_factory
                store = (
                    store_factory(Path(CANONICAL_ACTION_STORE_PATH))
                    if store_factory is not None
                    else open_canonical_action_store()
                )
                if store.has_action_block():
                    raise NativeExecutionError("native canonical unresolved action requires inspection")
                store.acquire_lease(owner, request.utc_clock(), self._config.lease_seconds)
                leased = True
                checkpoint()
                runtime = LocalBlueStacksRuntime.connect(
                    adb=request.adb,
                    serial=request.serial,
                    output_directory=session.session_directory,
                    workflow=self._config.workflow,
                    execute=True,
                )
                runtime_budget = getattr(runtime, "max_inputs", None)
                if type(runtime_budget) is not int or runtime_budget < 1:
                    raise NativeExecutionError("native runtime input budget is invalid")
                runtime.max_inputs = min(runtime_budget, request.max_inputs)
                runtime.checkpoint = checkpoint
                checkpoint()
                context = _NativeRouteContext(
                    request,
                    owner=owner,
                    invocation_id=invocation_id,
                    session=session,
                    runtime=runtime,
                    action_store=store,
                    checkpoint=checkpoint,
                )
                result = self._config.driver(context, request.arguments)
                if not isinstance(result, Mapping):
                    raise NativeExecutionError("fixed native route driver returned a non-mapping result")
                native_result = result
                checkpoint()
        except Exception as exc:
            failure = exc
            supplied_partial = getattr(exc, "partial_result", None)
            if isinstance(supplied_partial, Mapping):
                partial_result = supplied_partial
        finally:
            if store is not None:
                if leased:
                    try:
                        store.release_lease(self._config.owner, request.utc_clock())
                    except Exception as exc:
                        store_failure = exc
                try:
                    store.close()
                except Exception as exc:
                    store_failure = store_failure or exc
            if store_failure is not None:
                if failure is None:
                    failure = store_failure
                else:
                    failure = NativeExecutionError(
                        f"{failure}; canonical store teardown failed: {store_failure}"
                    )
        accounting = _accounting_snapshot(session, runtime, self.max_inputs)
        if not accounting.verified and failure is None:
            failure = NativeExecutionError("native route input accounting is inconsistent")
        if failure is not None and native_result:
            partial_result = partial_result or native_result
            native_result = {}
        return NativeRouteOutcome(
            flow_id=self.flow_id,
            native_result=native_result,
            partial_result=partial_result,
            failure=(f"{type(failure).__name__}: {failure}" if failure is not None else None),
            invocation_id=invocation_id,
            session_directory=(str(runtime.session) if runtime is not None else (
                str(session.session_directory) if session is not None else None
            )),
            startup_recovery=context.startup_recovery if context is not None else None,
            input_count=accounting.input_count,
            session_input_count=accounting.session_input_count,
            runtime_input_count=accounting.runtime_input_count,
            accounting_verified=accounting.verified,
        )


def make_native_route_binding(
    *,
    flow_id: str,
    product_id: str,
    product_revision: str,
    runtime_profile_id: str,
    owner: str,
    workflow: str,
    max_inputs: int,
    max_actions: int | None,
    driver: NativeRouteDriver,
    validator: NativeRouteValidator | None = None,
    lease_seconds: float = 3600.0,
    action_store_factory: ActionStoreFactory | None = None,
) -> _BoundNativeRoute:
    """Create a device-free fixed binding for one service route's native driver."""

    for name, value in (
        ("flow_id", flow_id),
        ("product_id", product_id),
        ("product_revision", product_revision),
        ("runtime_profile_id", runtime_profile_id),
        ("owner", owner),
        ("workflow", workflow),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"native route binding requires {name}")
    if runtime_profile_id != ACTIVE_RUNTIME_PROFILE_ID:
        raise ValueError("native route binding must use the active runtime profile")
    if not owner.startswith("automation-service:"):
        raise ValueError("native route binding requires its fixed automation-service owner")
    if type(max_inputs) is not int or not 1 <= max_inputs <= 100:
        raise ValueError("native route binding max_inputs must be from 1 through 100")
    if max_actions is not None and (type(max_actions) is not int or max_actions < 0):
        raise ValueError("native route binding max_actions must be non-negative or None")
    if not isinstance(lease_seconds, (int, float)) or isinstance(lease_seconds, bool) or not math_is_finite(lease_seconds) or lease_seconds <= 0:
        raise ValueError("native route binding lease_seconds must be finite and positive")
    if not callable(driver) or (validator is not None and not callable(validator)):
        raise ValueError("native route binding requires a fixed driver and callable validator")
    if action_store_factory is not None and not callable(action_store_factory):
        raise ValueError("native route action_store_factory must be callable")
    config = _BindingConfig(
        flow_id=flow_id,
        product_id=product_id,
        product_revision=product_revision,
        runtime_profile_id=runtime_profile_id,
        owner=owner,
        workflow=workflow,
        max_inputs=max_inputs,
        max_actions=max_actions,
        lease_seconds=float(lease_seconds),
        driver=driver,
        validator=validator,
        action_store_factory=action_store_factory,
    )
    return _BoundNativeRoute(config)
