"""Canonical generation/context handling for saved Commander talent presets.

This is a reusable helper, not a schedulable flow. Native UI behavior is
provided by an explicitly injected callable and runs inside the caller's
already-held DevelopmentSession.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import time
from typing import Any, Callable, Protocol

from safe_action_core.models import ActionClass, ActionIntent, PolicyResult, TransportResult
from tasks.commander_talents import (
    PRESET_NAMES,
    PresetRowState,
    TalentMemoryObservation,
    TalentPresetNativeResult,
    TalentSwitchPermit,
    context_fingerprint,
)


_SWITCH_CONSEQUENCE = "commander_talent_preset_switch"


class CommanderTalentNativePort(Protocol):
    """A route-owned callable bound to the fixed native runtime implementation."""

    def __call__(
        self,
        session: Any,
        runtime: Any,
        required_preset: str,
        *,
        checkpoint: Callable[[], None],
        runtime_input_lock: Any,
        action_store: Any,
        source_generation: str | int,
        context: Any,
        switch_approval: Callable[[TalentMemoryObservation, Any], TalentSwitchPermit | None] | None,
        switch_outcome: Callable[[str, str, bool, TalentMemoryObservation | None], None] | None,
    ) -> TalentPresetNativeResult: ...


@dataclass(frozen=True)
class CommanderTalentSwitchApproval:
    """A route-policy decision bound to exact observed switch facts and source."""

    intent: ActionIntent
    policy_result: PolicyResult
    cost_text: str
    cooldown_text: str
    confirmation_text: str
    source_frame_sha256: str
    source_generation: str | int
    context_sha256: str


@dataclass(frozen=True)
class CommanderTalentPresetResult:
    status: str
    verified: bool
    preset_name: str
    reason: str
    evidence_refs: tuple[str, ...]
    input_count: int
    source_generation: str | int
    context_sha256: str
    switch_action_key: str | None = None
    effect_reconciliation_required: bool = False
    identical_retry_denied: bool = False


def _generation(value: object) -> str | int:
    if type(value) is str and value.strip() == value and value and not any(ch.isspace() for ch in value):
        return value
    if type(value) is int and value >= 0:
        return value
    raise ValueError("source_generation must be a non-empty exact string or non-negative integer")


def _source_hash(value: object) -> bool:
    return bool(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value))


def _cost(value: str) -> tuple[str, float] | None:
    match = re.fullmatch(
        r"\s*(?:switch\s+)?cost\s*[:=]\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s+([A-Za-z][A-Za-z0-9_-]*)\s*",
        value,
        re.IGNORECASE,
    )
    if match is None:
        return None
    try:
        amount = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    if amount < 0:
        return None
    return match.group(2).casefold(), amount


def _policy_snapshot_matches(
    approval: CommanderTalentSwitchApproval,
    observation: TalentMemoryObservation,
    *,
    source_generation: str | int,
    context_sha256: str,
) -> bool:
    intent, policy = approval.intent, approval.policy_result
    parsed_cost = _cost(observation.cost_text or "")
    if parsed_cost is None:
        return False
    currency, amount = parsed_cost
    expected_action = f"switch_commander_talent_preset:{observation.preset_name.casefold()}"
    expected_kind = "commander_talent_preset_switch"
    expected_target = f"talent-memory-row:{observation.preset_name}:apply"
    expected_post = f"talent-memory-applied:{observation.preset_name}"
    expected_key = f"commander-talent-switch:{observation.preset_name.casefold()}:{source_generation}"
    required_preconditions = {
        f"saved-preset-name:{observation.preset_name}",
        f"currently-Apply:{observation.preset_name}",
        f"previous-applied-preset:{observation.applied_preset}",
        f"exact-cost-observed:{observation.cost_text}",
        f"cooldown-observed:{observation.cooldown_text}",
        f"confirmation-observed:{observation.confirmation_text}",
        f"source-generation:{source_generation}",
        f"context-sha256:{context_sha256}",
    }
    expected_class = ActionClass.ZERO_COST_CONSEQUENTIAL if amount == 0 else ActionClass.SPEND_OR_STRATEGIC
    if (
        approval.cost_text != observation.cost_text
        or approval.cooldown_text != observation.cooldown_text
        or approval.confirmation_text != observation.confirmation_text
        or approval.source_frame_sha256 != observation.source_frame_sha256
        or approval.source_generation != source_generation
        or approval.context_sha256 != context_sha256
        or observation.applied_preset not in PRESET_NAMES
        or observation.applied_preset == observation.preset_name
        or not _source_hash(approval.source_frame_sha256)
        or not policy.authorized
        or intent.action_key != expected_key
        or intent.semantic_action != expected_action
        or intent.action_kind != expected_kind
        or intent.subject != observation.preset_name
        or intent.source_state != "TALENT_MEMORY"
        or intent.target_identity != expected_target
        or intent.target_roi != observation.apply_target
        or intent.source_frame_sha256 != observation.source_frame_sha256
        or intent.expected_postcondition != expected_post
        or intent.consequence != _SWITCH_CONSEQUENCE
        or intent.cost_type.casefold() != currency
        or intent.resource_or_currency != currency
        or float(intent.cost_amount) != amount
        or intent.maximum_cost is None
        or float(intent.maximum_cost) != amount
        or intent.free_only is not (amount == 0)
        or intent.quantity != 1
        or intent.action_class is not expected_class
        or not required_preconditions.issubset(set(intent.semantic_preconditions))
        or expected_post not in intent.semantic_postconditions
    ):
        return False
    request = policy.request_snapshot
    if not isinstance(request, dict):
        return False
    try:
        request_cost = request.get("maximum_cost")
        request_class = ActionClass(request.get("action_class"))
    except (TypeError, ValueError):
        return False
    observed = request.get("observation")
    if not isinstance(observed, dict):
        return False
    target_roi = observed.get("target_roi")
    return bool(
        request.get("action_id") == intent.action_id
        and request.get("action_key") == intent.action_key
        and request.get("task_id") == intent.task_id
        and request.get("semantic_action") == intent.semantic_action
        and request.get("action_kind") == expected_kind
        and request.get("subject") == observation.preset_name
        and request.get("resource_or_currency") == currency
        and request.get("free_only") is (amount == 0)
        and type(request_cost) in (int, float)
        and float(request_cost) == amount
        and request_class is expected_class
        and request.get("semantic_postconditions") == list(intent.semantic_postconditions)
        and request.get("semantic_preconditions") == list(intent.semantic_preconditions)
        and request.get("expected_runtime_profile_id") == intent.runtime_profile_id
        and observed.get("frame_sha256") == observation.source_frame_sha256
        and observed.get("source_state") == "TALENT_MEMORY"
        and observed.get("target_identity") == expected_target
        and target_roi == list(observation.apply_target or ())
        and observed.get("control_class") == expected_kind
        and observed.get("consequence") == _SWITCH_CONSEQUENCE
        and observed.get("cost_type") == currency
        and type(observed.get("cost_amount")) in (int, float)
        and float(observed.get("cost_amount")) == amount
        and observed.get("quantity") == 1
        and observed.get("expected_postcondition") == expected_post
    )


def _store_lease_valid(action_store: Any, runtime_input_lock: Any) -> bool:
    lease_valid = getattr(action_store, "lease_valid_for", None)
    if not callable(lease_valid):
        return False
    try:
        return bool(lease_valid(runtime_input_lock.owner, time.time()))
    except Exception:
        return False



def _confirmed_switch(action_store: Any, action_key: str) -> bool:
    get_action = getattr(action_store, "get_action_by_key", None)
    if not callable(get_action):
        return False
    try:
        action = get_action(action_key)
    except Exception:
        return False
    if not isinstance(action, dict):
        return False
    return action.get("final_status", action.get("status")) == "confirmed"


def ensure_commander_talent_preset(
    session: Any,
    runtime: Any,
    required_preset: str,
    *,
    checkpoint: Callable[[], None],
    runtime_input_lock: Any,
    action_store: Any,
    source_generation: str | int,
    context: Any,
    native_port: CommanderTalentNativePort,
    switch_approval: Callable[[TalentMemoryObservation, Any], CommanderTalentSwitchApproval | None] | None = None,
) -> CommanderTalentPresetResult:
    """Verify the required exact saved preset using the caller's owned native runtime."""

    if required_preset not in PRESET_NAMES:
        raise ValueError("required preset must be Military, Economy, or Training")
    generation = _generation(source_generation)
    context_sha256 = context_fingerprint(context)
    if not callable(checkpoint) or not callable(native_port):
        raise ValueError("checkpoint and an explicitly injected talent native port are required")
    if getattr(session, "is_active", False) is not True:
        raise RuntimeError("commander talent verification requires the active DevelopmentSession")
    if getattr(session, "runtime_input_lock", None) is not runtime_input_lock:
        raise RuntimeError("commander talent verification requires the session's exact held runtime lock")
    owner = getattr(runtime_input_lock, "owner", None)
    invocation_id = getattr(runtime_input_lock, "invocation_id", None)
    if type(owner) is not str or not owner or type(invocation_id) is not str or not invocation_id:
        raise RuntimeError("commander talent verification requires a held owner identity")
    session_owner = getattr(session, "owner", None)
    session_invocation_id = getattr(session, "invocation_id", None)
    if (type(session_owner) is not str or not session_owner
            or type(session_invocation_id) is not str or not session_invocation_id):
        raise RuntimeError("commander talent native session identity is missing")
    if generation != session_invocation_id:
        raise ValueError("source_generation must match the held native session invocation")
    if (session_owner, session_invocation_id) != (owner, invocation_id):
        # A canonical borrowed session retains its own generation while its
        # outer operator holds the input lock. The SDK validates both scopes.
        assert_session_held = getattr(session, "assert_held", None)
        if not callable(assert_session_held):
            raise RuntimeError("commander talent borrowed session ownership cannot be verified")
        assert_session_held(session_owner, session_invocation_id)
    runtime_input_lock.assert_held(owner, invocation_id)
    checkpoint()
    runtime_input_lock.assert_held(owner, invocation_id)
    if action_store is None or not callable(getattr(action_store, "has_action_block", None)):
        raise RuntimeError("commander talent verification requires the canonical action store")
    action_blocked = action_store.has_action_block()
    if action_blocked:
        return CommanderTalentPresetResult(
            "unknown", False, required_preset, "CANONICAL_ACTION_REQUIRES_INSPECTION", (), 0,
            generation, context_sha256, identical_retry_denied=True,
        )
    prepared: dict[str, ActionIntent] = {}

    def prepare_switch(observation: TalentMemoryObservation, frame: Any) -> TalentSwitchPermit | None:
        if switch_approval is None or not observation.switch_facts_complete:
            return None
        approval = switch_approval(observation, frame)
        if not isinstance(approval, CommanderTalentSwitchApproval):
            return None
        if not _policy_snapshot_matches(
            approval,
            observation,
            source_generation=generation,
            context_sha256=context_sha256,
        ):
            return None
        if action_store.has_action_block() or not _store_lease_valid(action_store, runtime_input_lock):
            return None
        if callable(getattr(action_store, "get_action_by_key", None)):
            if action_store.get_action_by_key(approval.intent.action_key) is not None:
                return None
        try:
            action_store.prepare_action(approval.intent, approval.policy_result, time.time())
        except Exception:
            return None
        prepared[approval.intent.action_key] = approval.intent
        return TalentSwitchPermit(approval.intent.action_key)

    def settle_switch(
        action_key: str,
        status: str,
        dispatched: bool,
        observation: TalentMemoryObservation | None,
    ) -> None:
        intent = prepared.get(action_key)
        if intent is None:
            return
        if dispatched:
            action_store.mark_input_sent(
                intent.action_id,
                time.time(),
                TransportResult(True, "COMMANDER_TALENT_PRESET_SWITCH_DISPATCHED"),
            )
        if (
            status == "switched"
            and dispatched is True
            and observation is not None
            and observation.recognized is True
            and observation.preset_name == required_preset
            and observation.row_state is PresetRowState.APPLIED
            and observation.applied_preset == required_preset
            and _source_hash(observation.source_frame_sha256)
            and type(observation.evidence_ref) is str
            and observation.evidence_ref.strip()
        ):
            action_store.mark_confirmed(
                intent.action_id,
                time.time(),
                {
                    "preset_name": required_preset,
                    "source_frame_sha256": observation.source_frame_sha256,
                    "evidence_ref": observation.evidence_ref,
                    "postcondition": f"talent-memory-applied:{required_preset}",
                },
            )
        else:
            action_store.mark_unresolved(
                intent.action_id,
                time.time(),
                "commander_talent_switch_successor_unknown_no_retry",
                {
                    "preset_name": required_preset,
                    "dispatch_returned": dispatched,
                    "observation": observation.evidence_ref if observation is not None else None,
                },
            )

    runtime_input_lock.assert_held(owner, invocation_id)
    checkpoint()
    native_result = native_port(
        session,
        runtime,
        required_preset,
        checkpoint=checkpoint,
        runtime_input_lock=runtime_input_lock,
        action_store=action_store,
        source_generation=generation,
        context=context,
        switch_approval=prepare_switch if switch_approval is not None else None,
        switch_outcome=settle_switch,
    )
    runtime_input_lock.assert_held(owner, invocation_id)
    checkpoint()
    runtime_input_lock.assert_held(owner, invocation_id)
    if not isinstance(native_result, TalentPresetNativeResult):
        raise TypeError("talent native port must return TalentPresetNativeResult")
    if native_result.preset_name != required_preset:
        raise ValueError("talent native port returned another preset identity")
    has_current_applied_proof = bool(
        native_result.verified is True
        and native_result.status == "already_applied"
        and native_result.switch_action_key is None
        and native_result.switch_transport_attempted is False
        and native_result.evidence_refs
    )
    has_confirmed_switch_proof = bool(
        native_result.verified is True
        and native_result.status == "switched"
        and native_result.switch_action_key
        and native_result.switch_transport_attempted is True
        and native_result.evidence_refs
        and _confirmed_switch(action_store, native_result.switch_action_key)
    )
    successful = has_current_applied_proof or has_confirmed_switch_proof
    return CommanderTalentPresetResult(
        native_result.status,
        successful,
        required_preset,
        native_result.reason,
        tuple(native_result.evidence_refs),
        native_result.input_count,
        generation,
        context_sha256,
        switch_action_key=native_result.switch_action_key,
        effect_reconciliation_required=native_result.switch_transport_attempted and not successful,
        identical_retry_denied=native_result.switch_transport_attempted and not successful,
    )
