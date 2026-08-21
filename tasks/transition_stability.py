"""Pure, input-free polling of a settling transition.

The runtime owns capture and transport.  This module only consumes already
captured, typed observations and reports whether a successor is transient,
stable, timed out, or contradictory.  It deliberately has no capture, ADB, or
flow knowledge so it can be used by offline replay and by adapters alike.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from collections.abc import Hashable, Iterable, Mapping
from typing import Any, Callable, Generic, TypeVar


T = TypeVar("T")


class TransitionStatus(str, Enum):
    TRANSIENT = "transient"
    STABLE = "stable"
    TIMEOUT = "timeout"
    CONTRADICTORY = "contradictory"


# Friendly aliases used by callers that describe the result as a state.
TransitionState = TransitionStatus
StabilityStatus = TransitionStatus


def _freeze(value: Any) -> Hashable:
    """Return a deterministic, hashable representation for an observation."""

    if isinstance(value, (str, int, float, bool, bytes, type(None))):
        return value
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((_freeze(item) for item in value), key=repr))
    # Dataclasses and most typed observations have a useful repr.  Keep the
    # type in the key so two unrelated value objects with equal reprs do not
    # accidentally collapse into one state.
    try:
        from dataclasses import asdict, is_dataclass

        if is_dataclass(value):
            return (type(value).__qualname__, _freeze(asdict(value)))
    except (TypeError, ValueError):
        pass
    return (type(value).__qualname__, repr(value))


def observation_signature(value: Any) -> Hashable:
    """Expose the canonical signature used for equality during polling."""

    return _freeze(value)


@dataclass(frozen=True)
class TransitionObservation(Generic[T]):
    """One already-captured successor observation.

    ``state`` is intentionally unconstrained: adapters may carry a typed
    recognition object, a native-frame identity, or a small immutable mapping.
    ``signature`` can be supplied when the typed object has an intentionally
    coarser equality relation.
    """

    state: T
    signature: Hashable | None = None
    evidence_ref: str = ""
    ordinal: int = 0
    contradictory: bool = False

    @property
    def value(self) -> T:
        return self.state

    @property
    def typed_observation(self) -> T:
        return self.state

    def key(self) -> Hashable:
        return self.signature if self.signature is not None else observation_signature(self.state)


@dataclass(frozen=True)
class StableTransitionResult(Generic[T]):
    status: TransitionStatus
    observations: tuple[TransitionObservation[T], ...]
    successor: T | None = None
    successor_signature: Hashable | None = None
    stable_polls: int = 0
    poll_count: int = 0
    timeout_polls: int | None = None
    reason: str = ""
    input_count: int = 0

    @property
    def state(self) -> TransitionStatus:
        return self.status

    @property
    def typed_successor(self) -> T | None:
        return self.successor

    @property
    def dispatched_inputs(self) -> int:
        return self.input_count

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            TransitionStatus.STABLE,
            TransitionStatus.TIMEOUT,
            TransitionStatus.CONTRADICTORY,
        }


def _coerce_observation(item: Any, ordinal: int) -> TransitionObservation[Any]:
    if isinstance(item, TransitionObservation):
        return item if item.ordinal else TransitionObservation(
            item.state, item.signature, item.evidence_ref, ordinal, item.contradictory
        )
    if isinstance(item, Mapping) and ("state" in item or "observation" in item or "value" in item):
        state = item.get("state", item.get("observation", item.get("value")))
        signature = item.get("signature")
        return TransitionObservation(
            state,
            signature,
            str(item.get("evidence_ref", item.get("evidence", "")) or ""),
            int(item.get("ordinal", ordinal) or ordinal),
            bool(item.get("contradictory", False)),
        )
    return TransitionObservation(item, ordinal=ordinal)


def poll_stable_transition(
    observations: Iterable[TransitionObservation[T] | T | Mapping[str, Any]],
    *,
    stable_polls: int = 2,
    timeout_polls: int | None = None,
    expected_signature: Hashable | None = None,
    signature: Callable[[T], Hashable] | None = None,
) -> StableTransitionResult[T]:
    """Classify an existing observation sequence without issuing input.

    A stable result requires ``stable_polls`` consecutive equal signatures. A
    second equally stable but different successor is contradictory. If an
    expected signature is supplied, a stable different successor is also
    contradictory. Exhaustion at the explicit poll ceiling is ``TIMEOUT``;
    otherwise an incomplete sequence is ``TRANSIENT``.
    """

    if isinstance(stable_polls, bool) or int(stable_polls) < 1:
        raise ValueError("stable_polls must be a positive integer")
    if timeout_polls is not None and (isinstance(timeout_polls, bool) or int(timeout_polls) < 1):
        raise ValueError("timeout_polls must be a positive integer or None")
    required = int(stable_polls)
    items = tuple(_coerce_observation(item, index) for index, item in enumerate(observations, 1))
    if timeout_polls is not None:
        items = items[: int(timeout_polls)]

    def key_for(item: TransitionObservation[T]) -> Hashable:
        if item.signature is not None:
            return item.signature
        return signature(item.state) if signature is not None else item.key()

    if not items:
        return StableTransitionResult(
            TransitionStatus.TIMEOUT if timeout_polls is not None else TransitionStatus.TRANSIENT,
            (),
            timeout_polls=int(timeout_polls) if timeout_polls is not None else None,
            reason="no_observations",
        )

    if any(item.contradictory for item in items):
        return StableTransitionResult(
            TransitionStatus.CONTRADICTORY,
            items,
            successor=items[-1].state,
            successor_signature=(items[-1].signature if items[-1].signature is not None else observation_signature(items[-1].state)),
            poll_count=len(items),
            timeout_polls=int(timeout_polls) if timeout_polls is not None else None,
            reason="observation_marked_contradictory",
        )

    runs: list[tuple[Hashable, int, TransitionObservation[T]]] = []
    current_key: Hashable | None = None
    current_count = 0
    current_first: TransitionObservation[T] | None = None
    for item in items:
        key = key_for(item)
        if key == current_key:
            current_count += 1
        else:
            if current_first is not None:
                runs.append((current_key, current_count, current_first))  # type: ignore[arg-type]
            current_key, current_count, current_first = key, 1, item
        if current_count >= required:
            # Keep one run per distinct stable signature. A later run of the
            # same signature is harmless, while a different completed run is
            # explicit contradictory successor evidence.
            if not any(existing_key == key for existing_key, _count, _first in runs):
                runs.append((key, current_count, current_first))

    if current_first is not None:
        if not any(existing_key == current_key for existing_key, _count, _first in runs):
            runs.append((current_key, current_count, current_first))  # type: ignore[arg-type]

    stable_runs = [(key, count, first) for key, count, first in runs if count >= required]
    if len({key for key, _count, _first in stable_runs}) > 1:
        return StableTransitionResult(
            TransitionStatus.CONTRADICTORY,
            items,
            successor=items[-1].state,
            successor_signature=key_for(items[-1]),
            stable_polls=current_count,
            poll_count=len(items),
            timeout_polls=int(timeout_polls) if timeout_polls is not None else None,
            reason="multiple_stable_successors",
        )

    if stable_runs:
        key, count, first = stable_runs[-1]
        if expected_signature is not None and key != expected_signature:
            return StableTransitionResult(
                TransitionStatus.CONTRADICTORY,
                items,
                successor=first.state,
                successor_signature=key,
                stable_polls=count,
                poll_count=len(items),
                timeout_polls=int(timeout_polls) if timeout_polls is not None else None,
                reason="stable_successor_does_not_match_expected",
            )
        return StableTransitionResult(
            TransitionStatus.STABLE,
            items,
            successor=first.state,
            successor_signature=key,
            stable_polls=count,
            poll_count=len(items),
            timeout_polls=int(timeout_polls) if timeout_polls is not None else None,
            reason="successor_stable",
        )

    status = TransitionStatus.TIMEOUT if timeout_polls is not None and len(items) >= int(timeout_polls) else TransitionStatus.TRANSIENT
    return StableTransitionResult(
        status,
        items,
        successor=items[-1].state,
        successor_signature=key_for(items[-1]),
        stable_polls=current_count,
        poll_count=len(items),
        timeout_polls=int(timeout_polls) if timeout_polls is not None else None,
        reason="poll_ceiling_reached" if status is TransitionStatus.TIMEOUT else "successor_still_settling",
    )


class StableTransitionPoller(Generic[T]):
    """Convenience value object for adapters that collect observations first."""

    def __init__(
        self,
        *,
        stable_polls: int = 2,
        timeout_polls: int | None = None,
        expected_signature: Hashable | None = None,
        signature: Callable[[T], Hashable] | None = None,
    ) -> None:
        self.stable_polls = stable_polls
        self.timeout_polls = timeout_polls
        self.expected_signature = expected_signature
        self.signature = signature

    def poll(self, observations: Iterable[TransitionObservation[T] | T | Mapping[str, Any]]) -> StableTransitionResult[T]:
        return poll_stable_transition(
            observations,
            stable_polls=self.stable_polls,
            timeout_polls=self.timeout_polls,
            expected_signature=self.expected_signature,
            signature=self.signature,
        )

    __call__ = poll


# Explicit names make imports self-documenting while retaining a compact core.
stable_transition_poll = poll_stable_transition
classify_transition = poll_stable_transition
poll_transition = poll_stable_transition
settle_transition = poll_stable_transition
TransitionResult = StableTransitionResult
TransitionSample = TransitionObservation


__all__ = [
    "TransitionStatus",
    "TransitionState",
    "StabilityStatus",
    "TransitionObservation",
    "StableTransitionResult",
    "StableTransitionPoller",
    "observation_signature",
    "poll_stable_transition",
    "stable_transition_poll",
    "classify_transition",
    "poll_transition",
    "settle_transition",
    "TransitionResult",
    "TransitionSample",
]
