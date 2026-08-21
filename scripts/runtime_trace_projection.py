"""Read-only projection of an action's causal evidence chain.

The projection is observability only.  It does not write journals, alter
SafetyStore state, infer a transport from dispatch, or infer semantic success
from a transport result.  Inputs may be mappings or typed event objects from
existing replay consumers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from collections.abc import Iterable, Mapping
from typing import Any


class TraceStage(str, Enum):
    OBSERVATION = "observation"
    INTENT = "intent"
    TRANSPORT = "transport"
    SETTLED_SUCCESSOR = "settled_successor"
    SEMANTIC_RESULT = "semantic_result"
    TERMINAL_RESULT = "terminal_result"
    UNKNOWN = "unknown"


class TraceStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"
    CONTRADICTORY = "contradictory"


_STAGE_ALIASES = {
    "observation": TraceStage.OBSERVATION,
    "observe": TraceStage.OBSERVATION,
    "source": TraceStage.OBSERVATION,
    "intent": TraceStage.INTENT,
    "planned_intent": TraceStage.INTENT,
    "transport": TraceStage.TRANSPORT,
    "dispatch": TraceStage.TRANSPORT,
    "input": TraceStage.TRANSPORT,
    "settled_successor": TraceStage.SETTLED_SUCCESSOR,
    "settled": TraceStage.SETTLED_SUCCESSOR,
    "successor": TraceStage.SETTLED_SUCCESSOR,
    "semantic_result": TraceStage.SEMANTIC_RESULT,
    "semantic": TraceStage.SEMANTIC_RESULT,
    "terminal_result": TraceStage.TERMINAL_RESULT,
    "terminal": TraceStage.TERMINAL_RESULT,
    "result": TraceStage.TERMINAL_RESULT,
}


@dataclass(frozen=True)
class TraceEvent:
    stage: TraceStage | str
    payload: Any = None
    action_key: str = ""
    evidence_ref: str = ""
    event_id: str = ""
    explicit_success: bool | None = None
    contradictory: bool = False

    def normalized_stage(self) -> TraceStage:
        if isinstance(self.stage, TraceStage):
            return self.stage
        return _STAGE_ALIASES.get(str(self.stage).strip().lower(), TraceStage.UNKNOWN)


@dataclass(frozen=True)
class CausalTraceProjection:
    status: TraceStatus
    events: tuple[TraceEvent, ...]
    stages: tuple[TraceStage, ...]
    missing_stages: tuple[TraceStage, ...]
    unknown_reasons: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    action_key: str = ""
    transport_observed: bool = False
    semantic_success_observed: bool = False
    terminal_success_observed: bool = False
    authority_mutated: bool = False

    @property
    def input_count(self) -> int:
        # The projection reports accounting already present in event payloads;
        # dispatch itself is not a success signal.
        return sum(1 for event in self.events if event.normalized_stage() is TraceStage.TRANSPORT)

    @property
    def transport_succeeded(self) -> bool:
        return self.transport_observed

    @property
    def semantic_succeeded(self) -> bool:
        return self.semantic_success_observed

    @property
    def is_authorizing(self) -> bool:
        return False


_REQUIRED = (
    TraceStage.OBSERVATION,
    TraceStage.INTENT,
    TraceStage.TRANSPORT,
    TraceStage.SETTLED_SUCCESSOR,
    TraceStage.SEMANTIC_RESULT,
    TraceStage.TERMINAL_RESULT,
)


def _event_value(event: Any, key: str, default: Any = None) -> Any:
    if isinstance(event, Mapping):
        return event.get(key, default)
    return getattr(event, key, default)


def _coerce_event(item: Any, ordinal: int) -> TraceEvent:
    if isinstance(item, TraceEvent):
        return item
    stage = _event_value(item, "stage", _event_value(item, "kind", _event_value(item, "event_type", _event_value(item, "type", "unknown"))))
    payload = _event_value(item, "payload", item)
    action_key = str(_event_value(item, "action_key", _event_value(item, "action", _event_value(item, "correlation_id", ""))) or "")
    evidence_ref = str(_event_value(item, "evidence_ref", _event_value(item, "evidence", _event_value(item, "path", ""))) or "")
    event_id = str(_event_value(item, "event_id", _event_value(item, "id", f"event:{ordinal}")) or f"event:{ordinal}")
    explicit = _event_value(item, "explicit_success", None)
    if explicit is None:
        candidate = _event_value(item, "transport_observed", _event_value(item, "semantic_success", _event_value(item, "success", None)))
        if isinstance(candidate, bool):
            explicit = candidate
    contradictory = bool(_event_value(item, "contradictory", False))
    return TraceEvent(stage, payload, action_key, evidence_ref, event_id, explicit, contradictory)


def _stage_success(event: TraceEvent) -> bool | None:
    if event.explicit_success is not None:
        return bool(event.explicit_success)
    payload = event.payload
    if isinstance(payload, Mapping):
        for key in ("transport_observed", "semantic_success", "terminal_success", "success"):
            value = payload.get(key)
            if isinstance(value, bool):
                return value
        status = str(payload.get("status", "")).strip().lower()
        if status in {"success", "succeeded", "completed", "complete", "ok"}:
            return True
        if status in {"failed", "blocked", "unknown", "unresolved", "contradictory"}:
            return False
    return None


def project_trace(events: Iterable[TraceEvent | Mapping[str, Any] | Any], *, action_key: str | None = None) -> CausalTraceProjection:
    """Project a causal chain without changing any source event or authority."""

    normalized = tuple(_coerce_event(item, index) for index, item in enumerate(events, 1))
    foreign_action_requested = bool(
        action_key is not None
        and any(event.action_key and event.action_key != action_key for event in normalized)
    )
    if action_key is not None:
        normalized = tuple(item for item in normalized if not item.action_key or item.action_key == action_key)
    stages = tuple(item.normalized_stage() for item in normalized)
    stage_set = set(stages)
    missing = tuple(stage for stage in _REQUIRED if stage not in stage_set)
    unknown_reasons: list[str] = []
    contradictions: list[str] = []
    bound_keys = {event.action_key for event in normalized if event.action_key}
    unbound_count = sum(1 for event in normalized if not event.action_key)
    binding_contradiction = False
    if action_key is None:
        if len(bound_keys) > 1 or (bound_keys and unbound_count):
            binding_contradiction = True
            contradictions.append("mixed_action_keys")
        elif not bound_keys and normalized:
            unknown_reasons.append("action_key_unbound")
    elif foreign_action_requested:
        # Filtering cannot silently relabel a foreign action.
        binding_contradiction = True
        contradictions.append("requested_action_key_mismatch")
    elif unbound_count:
        unknown_reasons.append("action_key_unbound")
    if any(stage is TraceStage.UNKNOWN for stage in stages):
        unknown_reasons.append("unknown_event_stage")
    for event in normalized:
        if event.contradictory:
            contradictions.append(f"event:{event.event_id}")

    # Dispatch/intent presence is not transport proof. Only an explicitly
    # observed transport result contributes transport_observed.
    transport_observed = False
    semantic_success = False
    terminal_success = False
    for event in normalized:
        stage = event.normalized_stage()
        success = _stage_success(event)
        if stage is TraceStage.TRANSPORT and success is True:
            transport_observed = True
        elif stage is TraceStage.SEMANTIC_RESULT and success is True:
            semantic_success = True
        elif stage is TraceStage.TERMINAL_RESULT and success is True:
            terminal_success = True
        if success is False and stage in {TraceStage.TRANSPORT, TraceStage.SEMANTIC_RESULT, TraceStage.TERMINAL_RESULT}:
            contradictions.append(f"negative_{stage.value}:{event.event_id}") if success is False and any(
                prior.normalized_stage() is stage and _stage_success(prior) is True for prior in normalized
            ) else None

    if contradictions or binding_contradiction:
        status = TraceStatus.CONTRADICTORY
    elif not normalized or missing:
        status = TraceStatus.UNKNOWN if not normalized or any(stage is TraceStage.UNKNOWN for stage in stages) else TraceStatus.INCOMPLETE
        if missing:
            unknown_reasons.append("missing:" + ",".join(stage.value for stage in missing))
    elif unbound_count or not bound_keys:
        status = TraceStatus.UNKNOWN
        if unbound_count and "action_key_unbound" not in unknown_reasons:
            unknown_reasons.append("action_key_unbound")
    elif not transport_observed and any(stage is TraceStage.TRANSPORT for stage in stages):
        # A dispatch event with no explicit transport result remains unknown.
        status = TraceStatus.UNKNOWN
        unknown_reasons.append("transport_not_observed")
    elif not semantic_success:
        status = TraceStatus.UNKNOWN
        unknown_reasons.append("semantic_success_not_observed")
    elif not terminal_success:
        status = TraceStatus.UNKNOWN
        unknown_reasons.append("terminal_success_not_observed")
    else:
        status = TraceStatus.COMPLETE

    return CausalTraceProjection(
        status=status,
        events=normalized,
        stages=stages,
        missing_stages=missing,
        unknown_reasons=tuple(dict.fromkeys(unknown_reasons)),
        contradictions=tuple(dict.fromkeys(contradictions)),
        action_key=action_key or (next(iter(bound_keys)) if len(bound_keys) == 1 else ""),
        transport_observed=transport_observed,
        semantic_success_observed=semantic_success,
        terminal_success_observed=terminal_success,
        authority_mutated=False,
    )


project_causal_trace = project_trace
build_trace_projection = project_trace
RuntimeTraceEvent = TraceEvent
RuntimeTraceProjection = CausalTraceProjection
TraceProjection = CausalTraceProjection
project_runtime_trace = project_trace


__all__ = [
    "TraceStage",
    "TraceStatus",
    "TraceEvent",
    "CausalTraceProjection",
    "RuntimeTraceEvent",
    "RuntimeTraceProjection",
    "TraceProjection",
    "project_trace",
    "project_causal_trace",
    "build_trace_projection",
    "project_runtime_trace",
]
