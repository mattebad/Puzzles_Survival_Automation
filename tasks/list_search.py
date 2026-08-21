"""Pure list/card search state for offline replay.

The search primitive consumes observations that have already been captured by an
adapter.  It records what was visible before any requested motion, tracks list
and frame signatures, and returns a decision.  It never owns a transport
callback and therefore cannot dispatch input during replay.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from collections.abc import Hashable, Iterable, Mapping
from typing import Any, Callable

from tasks.transition_stability import observation_signature


class SearchStatus(str, Enum):
    TRANSIENT = "transient"
    TARGET_VISIBLE = "target_visible"
    NO_MOTION = "no_motion"
    REPEATED_STATE = "repeated_state"
    REVERSED_ONCE = "reversed_once"
    TIMEOUT = "timeout"
    CONTRADICTORY = "contradictory"


class SearchDirection(str, Enum):
    FORWARD = "forward"
    REVERSE = "reverse"
    UNKNOWN = "unknown"


ListSearchStateStatus = SearchStatus
ListSearchResultStatus = SearchStatus


@dataclass(frozen=True)
class ListObservation:
    """One current-frame list inspection.

    ``displacement`` is measured from the preceding inspection.  Direction is
    adapter-supplied because list axes and coordinate orientation are not
    shared product policy.
    """

    frame_signature: Hashable
    list_signature: Hashable
    target_visible: bool = False
    displacement: float = 0.0
    direction: SearchDirection | str = SearchDirection.UNKNOWN
    typed_observation: Any = None
    evidence_ref: str = ""

    @property
    def signature(self) -> Hashable:
        return self.list_signature

    def normalized_direction(self) -> SearchDirection:
        if isinstance(self.direction, SearchDirection):
            return self.direction
        raw = str(self.direction or "").strip().lower()
        if raw in {"forward", "next", "down", "right", "+1", "1"}:
            return SearchDirection.FORWARD
        if raw in {"reverse", "backward", "previous", "up", "left", "-1"}:
            return SearchDirection.REVERSE
        return SearchDirection.UNKNOWN


@dataclass(frozen=True)
class ListSearchDecision:
    status: SearchStatus
    observations: tuple[ListObservation, ...]
    frame_signatures: tuple[Hashable, ...]
    list_signatures: tuple[Hashable, ...]
    displacements: tuple[float, ...]
    directions: tuple[SearchDirection, ...]
    cumulative_displacement: float = 0.0
    reversal_count: int = 0
    no_motion: bool = False
    repeated: bool = False
    target_visible: bool = False
    dispatch_allowed: bool = False
    input_count: int = 0
    reason: str = ""

    @property
    def state(self) -> SearchStatus:
        return self.status

    @property
    def inspected_before_motion(self) -> bool:
        return bool(self.observations)

    @property
    def issued_inputs(self) -> int:
        return self.input_count


def _coerce(item: ListObservation | Mapping[str, Any] | Any, ordinal: int) -> ListObservation:
    if isinstance(item, ListObservation):
        return item
    if isinstance(item, Mapping):
        frame = item.get("frame_signature", item.get("frame", item.get("capture_signature")))
        listing = item.get("list_signature", item.get("list", item.get("signature", frame)))
        if frame is None:
            frame = listing
        return ListObservation(
            frame_signature=frame,
            list_signature=listing,
            target_visible=bool(item.get("target_visible", item.get("visible", False))),
            displacement=float(item.get("displacement", item.get("delta", 0.0)) or 0.0),
            direction=item.get("direction", SearchDirection.UNKNOWN),
            typed_observation=item.get("typed_observation", item.get("observation")),
            evidence_ref=str(item.get("evidence_ref", item.get("evidence", "")) or ""),
        )
    # A bare typed observation is retained and used as both signatures. This
    # path is useful for tiny replay tests; production adapters should provide
    # explicit frame/list signatures.
    sig = observation_signature(item)
    return ListObservation(sig, sig, typed_observation=item, evidence_ref=f"ordinal:{ordinal}")


def _result(
    observations: tuple[ListObservation, ...],
    *,
    status: SearchStatus,
    reversal_count: int,
    reason: str,
    no_motion: bool = False,
    repeated: bool = False,
    target_visible: bool = False,
) -> ListSearchDecision:
    return ListSearchDecision(
        status=status,
        observations=observations,
        frame_signatures=tuple(item.frame_signature for item in observations),
        list_signatures=tuple(item.list_signature for item in observations),
        displacements=tuple(float(item.displacement) for item in observations),
        directions=tuple(item.normalized_direction() for item in observations),
        cumulative_displacement=sum(float(item.displacement) for item in observations),
        reversal_count=reversal_count,
        no_motion=no_motion,
        repeated=repeated,
        target_visible=target_visible,
        dispatch_allowed=False,
        input_count=0,
        reason=reason,
    )


def inspect_list(
    observations: Iterable[ListObservation | Mapping[str, Any] | Any],
    *,
    target_visible: Callable[[ListObservation], bool] | None = None,
    max_inspections: int | None = None,
    allow_one_reversal: bool = True,
) -> ListSearchDecision:
    """Inspect a replay sequence and return a non-authorizing search decision."""

    if max_inspections is not None and (isinstance(max_inspections, bool) or int(max_inspections) < 1):
        raise ValueError("max_inspections must be a positive integer or None")
    if not isinstance(allow_one_reversal, bool):
        raise ValueError("allow_one_reversal must be bool")
    items = tuple(_coerce(item, index) for index, item in enumerate(observations, 1))
    if max_inspections is not None:
        items = items[: int(max_inspections)]
    if not items:
        return _result(items, status=SearchStatus.TRANSIENT, reversal_count=0, reason="no_inspections")

    reversal_count = 0
    seen: set[Hashable] = set()
    previous_direction = SearchDirection.UNKNOWN
    first = items[0]
    if (target_visible(first) if target_visible is not None else first.target_visible):
        return _result(items[:1], status=SearchStatus.TARGET_VISIBLE, reversal_count=0, reason="target_visible_before_motion", target_visible=True)
    seen.add(first.list_signature)

    for index, item in enumerate(items[1:], 1):
        visible = target_visible(item) if target_visible is not None else item.target_visible
        direction = item.normalized_direction()
        if visible:
            return _result(items[: index + 1], status=SearchStatus.TARGET_VISIBLE, reversal_count=reversal_count, reason="target_visible", target_visible=True)

        # A repeated frame/list signature with no displacement is stronger than
        # a merely repeated OCR/card signature and is classified as no-motion.
        same_frame = item.frame_signature == items[index - 1].frame_signature
        same_list = item.list_signature == items[index - 1].list_signature
        displacement = float(item.displacement)
        if displacement == 0.0 or (same_frame and same_list):
            return _result(items[: index + 1], status=SearchStatus.NO_MOTION, reversal_count=reversal_count, reason="no_motion", no_motion=True)

        # Direction changes are evidence-driven regardless of whether the new
        # card signature has appeared before.  At most one is admitted.
        direction_changed = (
            direction is not SearchDirection.UNKNOWN
            and previous_direction is not SearchDirection.UNKNOWN
            and direction is not previous_direction
        )
        if direction_changed:
            if allow_one_reversal and reversal_count == 0:
                reversal_count = 1
            else:
                return _result(items[: index + 1], status=SearchStatus.CONTRADICTORY, reversal_count=reversal_count, reason="multiple_direction_reversals")

        if item.list_signature in seen:
            # One evidence-driven reversal is permitted. The repeated state is
            # accepted only when the direction changed and no earlier reversal
            # was consumed; a second reversal is contradictory.
            if not direction_changed:
                return _result(items[: index + 1], status=SearchStatus.REPEATED_STATE, reversal_count=reversal_count, reason="repeated_list_state", repeated=True)

        if direction is not SearchDirection.UNKNOWN:
            previous_direction = direction
        seen.add(item.list_signature)

    if max_inspections is not None and len(items) >= int(max_inspections):
        return _result(items, status=SearchStatus.TIMEOUT, reversal_count=reversal_count, reason="inspection_ceiling_reached")
    if reversal_count:
        return _result(items, status=SearchStatus.REVERSED_ONCE, reversal_count=reversal_count, reason="one_evidence_driven_reversal")
    return _result(items, status=SearchStatus.TRANSIENT, reversal_count=0, reason="search_incomplete")


def search_list(*args: Any, **kwargs: Any) -> ListSearchDecision:
    """Alias for :func:`inspect_list` used by replay consumers."""

    return inspect_list(*args, **kwargs)


class ListSearchTracker:
    """Small immutable-style wrapper; it only stores observations locally."""

    def __init__(self, *, allow_one_reversal: bool = True, max_inspections: int | None = None) -> None:
        self.allow_one_reversal = allow_one_reversal
        self.max_inspections = max_inspections
        self._observations: tuple[ListObservation, ...] = ()

    @property
    def observations(self) -> tuple[ListObservation, ...]:
        return self._observations

    def inspect(self, observation: ListObservation | Mapping[str, Any] | Any) -> ListSearchDecision:
        self._observations = self._observations + (_coerce(observation, len(self._observations) + 1),)
        return inspect_list(
            self._observations,
            allow_one_reversal=self.allow_one_reversal,
            max_inspections=self.max_inspections,
        )

    step = inspect

    def result(self) -> ListSearchDecision:
        return inspect_list(
            self._observations,
            allow_one_reversal=self.allow_one_reversal,
            max_inspections=self.max_inspections,
        )


ListSearchObservation = ListObservation
ListSearchResult = ListSearchDecision
ListSearchState = ListSearchDecision
evaluate_list_search = inspect_list
classify_list_search = inspect_list


__all__ = [
    "SearchStatus",
    "SearchDirection",
    "ListSearchStateStatus",
    "ListSearchResultStatus",
    "ListObservation",
    "ListSearchObservation",
    "ListSearchDecision",
    "ListSearchResult",
    "ListSearchState",
    "ListSearchTracker",
    "inspect_list",
    "search_list",
    "evaluate_list_search",
    "classify_list_search",
]
