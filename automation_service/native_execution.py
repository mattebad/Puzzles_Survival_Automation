"""Typed, import-direction-safe contract for injected native route execution.

Service adapters depend on this protocol rather than importing ``scripts``.  The
pnsctl composition root binds each installed flow to one fixed native driver.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import math
import time
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol


class NativeExecutionError(RuntimeError):
    """A native route binding or its lifecycle boundary failed closed."""


class RuntimeInputLockPort(Protocol):
    owner: str
    invocation_id: str
    @property
    def held(self) -> bool: ...

    def assert_held(self, owner: str, invocation_id: str) -> None: ...


@dataclass(frozen=True)
class NativeFrameReference:
    """Unique capture-event reference retained inside one native runtime session."""

    frame_path: str
    frame_sha256: str
    observed_utc: str
    capture_ordinal: int
    def to_mapping(self) -> dict[str, object]:
        return {
            "frame_path": self.frame_path,
            "frame_sha256": self.frame_sha256,
            "observed_utc": self.observed_utc,
            "capture_ordinal": self.capture_ordinal,
        }


@dataclass(frozen=True)
class NativeStartupOutcome:
    """Evidence from the existing bounded known-overlay startup recovery path."""

    source_context: str
    reason: str
    input_count: int
    reported_input_count: int | None
    accounting_verified: bool
    resume_ready: bool
    dismissed: bool | None
    popup_absent: bool | None
    steps: tuple[Mapping[str, Any], ...]
    settled_frame: Any | None = None
    settled_reference: NativeFrameReference | None = None
    def to_mapping(self) -> dict[str, Any]:
        return {
            "source_context": self.source_context,
            "reason": self.reason,
            "input_count": self.input_count,
            "reported_input_count": self.reported_input_count,
            "accounting_verified": self.accounting_verified,
            "resume_ready": self.resume_ready,
            "dismissed": self.dismissed,
            "popup_absent": self.popup_absent,
            "steps": [dict(step) for step in self.steps],
            "settled_frame": (
                self.settled_reference.to_mapping() if self.settled_reference else None
            ),
        }


@dataclass(frozen=True)
class NativeExecutionAccounting:
    """Cross-check of native transport input count against session accounting."""

    input_count: int
    session_input_count: int
    runtime_input_count: int
    verified: bool


@dataclass(frozen=True)
class NativeRouteRequest:
    """One service claim's exact identity and bounded inputs for its fixed binding."""

    flow_id: str
    product_id: str
    product_revision: str
    runtime_profile_id: str
    identity: object
    previous_reset_id: str | None
    occurrence_key: str
    checkpoint: Callable[[], None]
    validate_identity: Callable[[], None]
    runtime_input_lock: RuntimeInputLockPort
    adb: str
    serial: str
    output_directory: Path
    max_inputs: int
    max_actions: int | None
    settle_seconds: float
    arguments: Mapping[str, object] = field(default_factory=dict)
    utc_clock: Callable[[], float] = time.time
    monotonic_clock: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        for field_name in (
            "flow_id",
            "product_id",
            "product_revision",
            "runtime_profile_id",
            "occurrence_key",
            "adb",
            "serial",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"native route request requires {field_name}")
        if self.previous_reset_id is not None and (
            not isinstance(self.previous_reset_id, str) or not self.previous_reset_id.strip()
        ):
            raise ValueError("native route previous_reset_id must be non-empty or None")
        if not callable(self.checkpoint) or not callable(self.validate_identity):
            raise ValueError("native route request requires checkpoint and identity validator")
        if not callable(self.utc_clock) or not callable(self.monotonic_clock):
            raise ValueError("native route request clocks must be callable")
        if type(self.max_inputs) is not int or not 1 <= self.max_inputs <= 100:
            raise ValueError("native route max_inputs must be an integer from 1 through 100")
        if self.max_actions is not None and (
            type(self.max_actions) is not int or self.max_actions < 0
        ):
            raise ValueError("native route max_actions must be a non-negative integer or None")
        if (not isinstance(self.settle_seconds, (int, float))
                or isinstance(self.settle_seconds, bool)
                or not math.isfinite(float(self.settle_seconds))
                or self.settle_seconds < 0):
            raise ValueError("native route settle_seconds must be finite and non-negative")
        if not isinstance(self.output_directory, Path):
            raise ValueError("native route output_directory must be a Path")
        if not isinstance(self.arguments, Mapping):
            raise ValueError("native route arguments must be a mapping")
        object.__setattr__(self, "arguments", MappingProxyType(dict(self.arguments)))


@dataclass(frozen=True)
class NativeRouteOutcome:
    """Native result plus lifecycle evidence; failure always invalidates success."""

    flow_id: str
    native_result: Mapping[str, Any]
    partial_result: Mapping[str, Any] | None
    failure: str | None
    invocation_id: str | None
    session_directory: str | None
    startup_recovery: NativeStartupOutcome | None
    input_count: int
    session_input_count: int
    runtime_input_count: int
    accounting_verified: bool

    @property
    def execution_verified(self) -> bool:
        """Whether native execution and its shared input accounting completed cleanly."""

        return self.failure is None and self.accounting_verified


class NativeRouteContext(Protocol):
    """The actual borrowed-owner session objects supplied to a fixed native driver."""

    flow_id: str
    product_id: str
    product_revision: str
    runtime_profile_id: str
    identity: object
    previous_reset_id: str | None
    occurrence_key: str
    owner: str
    invocation_id: str
    session: Any
    runtime: Any
    action_store: Any
    runtime_input_lock: RuntimeInputLockPort
    checkpoint: Callable[[], None]
    validate_identity: Callable[[], None]
    utc_clock: Callable[[], float]
    monotonic_clock: Callable[[], float]
    max_inputs: int
    max_actions: int | None
    settle_seconds: float
    initial_frame: Any
    initial_observation: Mapping[str, Any]
    startup_recovery: NativeStartupOutcome | None
    def is_clean_home(self, frame: Any) -> bool: ...

    def bind_initial_observation(
        self,
        frame: Any | None = None,
        *,
        extra: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]: ...

    def prepare_startup(
        self,
        *,
        source_context: str,
        recognize_successor: Callable[[Any], bool],
        action_key: str,
        settle_seconds: float | None = None,
    ) -> NativeStartupOutcome: ...

    def capture_reference(
        self,
        path: str | Path,
        expected_sha256: str | None = None,
    ) -> tuple[Any, NativeFrameReference]: ...

    def replay_source(
        self,
        captured: Any,
        reference: NativeFrameReference,
        label: str,
    ) -> Mapping[str, Any]: ...

    def accounting(self) -> NativeExecutionAccounting: ...


class NativeRouteBoundary(Protocol):
    """One statically bound flow/product native entrypoint and lifecycle owner."""

    flow_id: str
    product_id: str
    product_revision: str
    runtime_profile_id: str
    max_inputs: int
    max_actions: int | None

    def run(self, request: NativeRouteRequest) -> NativeRouteOutcome: ...
