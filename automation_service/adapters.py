"""Transport adapters with an explicit zero-transport default."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import threading
import time
import math
from typing import Callable, Iterable, Protocol

from safe_action_core import ExecutionResult, InputCapability, PolicyRequest, SafeActionExecutor
from .contracts import PerceptionEnvelope, SemanticActionIntent, ServiceMode


class AdapterError(RuntimeError):
    """Raised when an adapter admission or transport contract is violated."""


class AdapterKind(str, Enum):
    FAKE = "fake"
    REPLAY = "replay"
    BLUESTACKS_SUPERVISED = "bluestacks_supervised"


@dataclass(frozen=True)
class FrameSample:
    frame_id: str
    envelope: PerceptionEnvelope
    payload: bytes = b""


@dataclass(frozen=True)
class AdapterStatus:
    kind: AdapterKind
    mode: ServiceMode
    connected: bool
    transport_count: int
    last_frame_id: str | None = None


class DeviceAdapter(Protocol):
    """The service sees semantic intents only; coordinate binding stays below it."""

    kind: AdapterKind

    def capture(self) -> FrameSample:
        ...

    def execute(self, intent: SemanticActionIntent) -> bool:
        ...

    def status(self) -> AdapterStatus:
        ...


class FakeDeviceAdapter:
    """Deterministic adapter with no device and no transport."""

    kind = AdapterKind.FAKE

    def __init__(self, frames: Iterable[FrameSample] = ()) -> None:
        self._frames = tuple(frames)
        self._index = 0
        self._last: FrameSample | None = None
        self._attempted_intents: list[SemanticActionIntent] = []

    @property
    def attempted_intents(self) -> tuple[SemanticActionIntent, ...]:
        return tuple(self._attempted_intents)

    def capture(self) -> FrameSample:
        if not self._frames:
            raise AdapterError("fake adapter has no frame samples")
        sample = self._frames[min(self._index, len(self._frames) - 1)]
        self._index += 1
        self._last = sample
        return sample

    def execute(self, intent: SemanticActionIntent) -> bool:
        self._attempted_intents.append(intent)
        return False

    def status(self) -> AdapterStatus:
        return AdapterStatus(
            self.kind,
            ServiceMode.DRY_RUN,
            connected=False,
            transport_count=0,
            last_frame_id=self._last.frame_id if self._last else None,
        )


class ReplayDeviceAdapter(FakeDeviceAdapter):
    """Retained replay adapter; replay never calls a transport."""

    kind = AdapterKind.REPLAY

    def status(self) -> AdapterStatus:
        status = super().status()
        return AdapterStatus(
            self.kind,
            ServiceMode.OBSERVE_ONLY,
            status.connected,
            0,
            status.last_frame_id,
        )


@dataclass
class AdmissionToken:
    """Single-use, flow-bound supervised admission proof."""

    flow_id: str
    task_id: str
    semantic_action: str
    action_class: str
    issued_at_utc: float
    expires_at_utc: float
    max_inputs: int = 1
    _consumed: bool = field(default=False, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @property
    def consumed(self) -> bool:
        with self._lock:
            return self._consumed

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                self.flow_id,
                self.task_id,
                self.semantic_action,
                self.action_class,
            )
        ):
            raise ValueError("admission token requires flow, task, and action identity")
        if type(self.max_inputs) is not int or self.max_inputs != 1:
            raise ValueError("supervised admission tokens must allow exactly one input")
        if not all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in (self.issued_at_utc, self.expires_at_utc)
        ) or not all(
            math.isfinite(float(value))
            for value in (self.issued_at_utc, self.expires_at_utc)
        ) or self.expires_at_utc <= self.issued_at_utc:
            raise ValueError("admission token UTC bounds are invalid")

    def validate_intent(self, intent: SemanticActionIntent) -> None:
        if (intent.flow_id or intent.task_id) != self.flow_id:
            raise AdapterError("supervised admission token flow mismatch")
        if intent.task_id != self.task_id or intent.semantic_action != self.semantic_action:
            raise AdapterError("supervised admission token intent mismatch")

    def claim(
        self,
        *,
        flow_id: str,
        task_id: str,
        semantic_action: str,
        action_class: str,
        now_utc: float,
    ) -> None:
        with self._lock:
            if self._consumed:
                raise AdapterError("supervised admission token has already been consumed")
            if now_utc < self.issued_at_utc or now_utc >= self.expires_at_utc:
                raise AdapterError("supervised admission token is expired or not yet valid")
            if (flow_id, task_id, semantic_action, action_class) != (
                self.flow_id,
                self.task_id,
                self.semantic_action,
                self.action_class,
            ):
                raise AdapterError("supervised admission token binding mismatch")
            self._consumed = True


class RequestCapabilityBinding(Protocol):
    """Bound seam producing the exact core request and capability for one intent."""

    def bind(
        self,
        intent: SemanticActionIntent,
        admission: AdmissionToken,
    ) -> tuple[PolicyRequest, InputCapability]:
        ...


class SupervisedBlueStacksAdapter:
    """Explicitly supervised semantic adapter.

    The adapter delegates exclusively to SafeActionExecutor. It deliberately exposes no tap,
    coordinate, shell, ADB, remote endpoint, or transport callable.
    """

    kind = AdapterKind.BLUESTACKS_SUPERVISED

    def __init__(
        self,
        *,
        admission_token: AdmissionToken,
        capture: Callable[[], FrameSample],
        executor: SafeActionExecutor,
        request_capability_binding: RequestCapabilityBinding,
        connection_status: Callable[[], bool],
        mode: ServiceMode = ServiceMode.SUPERVISED,
        utc_clock: Callable[[], float] = time.time,
    ) -> None:
        if mode is not ServiceMode.SUPERVISED:
            raise AdapterError("BlueStacks adapter requires explicit supervised mode")
        if not isinstance(admission_token, AdmissionToken):
            raise AdapterError("BlueStacks adapter requires an explicit admission token")
        if type(executor) is not SafeActionExecutor:
            raise AdapterError("BlueStacks adapter requires a SafeActionExecutor")
        if not callable(getattr(request_capability_binding, "bind", None)):
            raise AdapterError("supervised adapter requires a request/capability binding seam")
        if not callable(connection_status):
            raise AdapterError("supervised adapter requires a connection-status probe")
        self._capture = capture
        self._executor = executor
        self._binding = request_capability_binding
        self._connection_status = connection_status
        self._token = admission_token
        self._utc_clock = utc_clock
        self._last: FrameSample | None = None
        self._transport_count = 0

    def capture(self) -> FrameSample:
        sample = self._capture()
        self._last = sample
        return sample

    def execute(self, intent: SemanticActionIntent) -> ExecutionResult:
        try:
            self._token.validate_intent(intent)
            request, capability = self._binding.bind(intent, self._token)
            if type(request) is not PolicyRequest or type(capability) is not InputCapability:
                raise AdapterError("request/capability binding did not produce core authority types")
            if (
                request.task_id != self._token.task_id
                or request.semantic_action != self._token.semantic_action
                or request.action_class.value != self._token.action_class
            ):
                raise AdapterError("core policy request does not match supervised admission")
            capability_binding = capability.binding_audit_dict()
            expected_binding = {
                "task_id": request.task_id,
                "action_id": request.action_id,
                "action_key": request.action_key,
                "semantic_action": request.semantic_action,
                "action_class": request.action_class.value,
            }
            if any(
                capability_binding.get(field) != expected
                for field, expected in expected_binding.items()
            ):
                raise AdapterError("input capability does not match the core policy request")
            self._token.claim(
                flow_id=intent.flow_id or intent.task_id,
                task_id=request.task_id,
                semantic_action=request.semantic_action,
                action_class=request.action_class.value,
                now_utc=self._utc_clock(),
            )
            result = self._executor.execute(request, capability)
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError("supervised executor binding failed closed") from exc
        if type(result) is not ExecutionResult:
            raise AdapterError("SafeActionExecutor returned an invalid execution result")
        self._transport_count += result.transport_calls
        return result

    def status(self) -> AdapterStatus:
        return AdapterStatus(
            self.kind,
            ServiceMode.SUPERVISED,
            connected=bool(self._connection_status()),
            transport_count=self._transport_count,
            last_frame_id=self._last.frame_id if self._last else None,
        )

