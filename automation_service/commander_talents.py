"""Canonical, visit-scoped Commander preset proof and fixed-free switch authority."""
from __future__ import annotations

from dataclasses import dataclass, replace
import re
import time
from typing import Any, Callable, Mapping, Protocol

from safe_action_core import CentralPolicy
from safe_action_core.models import ActionClass, ActionIntent, Observation, PolicyRequest, PolicyResult, TransportResult
from tasks.commander_talents import (
    PRESET_NAMES, PresetRowState, TalentMemoryObservation, TalentPresetNativeResult,
    TalentSwitchPermit, context_fingerprint,
)
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID

_SWITCH_CONSEQUENCE = "commander_talent_preset_switch"
_PROOF_KEY = "commander_talent_applied_proof"


class CommanderTalentNativePort(Protocol):
    def __call__(self, session: Any, runtime: Any, required_preset: str, *,
                 checkpoint: Callable[[], None], runtime_input_lock: Any, action_store: Any,
                 source_generation: str | int, context: Any,
                 switch_approval: Callable[[TalentMemoryObservation, Any], TalentSwitchPermit | None] | None,
                 switch_outcome: Callable[[str, str, bool, TalentMemoryObservation | None], None] | None,
                 ) -> TalentPresetNativeResult: ...


@dataclass(frozen=True)
class CommanderTalentSwitchApproval:
    """A fixed-free route-policy decision bound to this exact Apply source."""
    intent: ActionIntent
    policy_result: PolicyResult
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


def _preconditions(observation: TalentMemoryObservation, generation, context_sha256) -> tuple[str, ...]:
    return (
        f"saved-preset-name:{observation.preset_name}",
        f"currently-Apply:{observation.preset_name}",
        f"previous-applied-preset:{observation.applied_preset}",
        "owner-fixed-free-no-cooldown-switch",
        f"source-generation:{generation}",
        f"context-sha256:{context_sha256}",
    )


def _policy_snapshot_matches(approval, observation, *, source_generation, context_sha256) -> bool:
    intent, policy = approval.intent, approval.policy_result
    name = observation.preset_name
    expected_post = f"talent-memory-applied:{name}"
    if (not observation.recognized or observation.row_state is not PresetRowState.APPLY
            or observation.apply_target is None or observation.applied_preset not in PRESET_NAMES
            or observation.applied_preset == name or not _source_hash(observation.source_frame_sha256)
            or approval.source_frame_sha256 != observation.source_frame_sha256
            or approval.source_generation != source_generation or approval.context_sha256 != context_sha256
            or not policy.authorized):
        return False
    expected = {
        "action_key": f"commander-talent-switch:{name.casefold()}:{source_generation}",
        "semantic_action": f"switch_commander_talent_preset:{name.casefold()}",
        "action_kind": "commander_talent_preset_switch", "subject": name,
        "resource_or_currency": "none", "maximum_cost": 0, "free_only": True,
        "semantic_preconditions": _preconditions(observation, source_generation, context_sha256),
        "semantic_postconditions": (expected_post,),
    }
    if (any(getattr(intent, key) != value for key, value in expected.items())
            or intent.action_class is not ActionClass.ZERO_COST_CONSEQUENTIAL
            or intent.source_state != "TALENT_MEMORY"
            or intent.target_identity != f"talent-memory-row:{name}:apply"
            or intent.target_roi != observation.apply_target
            or intent.source_frame_sha256 != observation.source_frame_sha256
            or intent.expected_postcondition != expected_post
            or intent.consequence != _SWITCH_CONSEQUENCE
            or intent.cost_type != "none" or intent.cost_amount != 0 or intent.quantity != 1):
        return False
    request = policy.request_snapshot
    if not isinstance(request, dict) or not isinstance(request.get("observation"), dict):
        return False
    expected.update(action_id=intent.action_id, task_id=intent.task_id,
                    action_class=ActionClass.ZERO_COST_CONSEQUENTIAL.value,
                    expected_runtime_profile_id=intent.runtime_profile_id)
    for key, value in expected.items():
        if request.get(key) != (list(value) if isinstance(value, tuple) else value):
            return False
    observed = request["observation"]
    return all(observed.get(key) == value for key, value in {
        "frame_sha256": observation.source_frame_sha256, "source_state": "TALENT_MEMORY",
        "target_identity": intent.target_identity, "target_roi": list(observation.apply_target),
        "control_class": "commander_talent_preset_switch", "consequence": _SWITCH_CONSEQUENCE,
        "cost_type": "none", "cost_amount": 0, "quantity": 1, "expected_postcondition": expected_post,
    }.items())


def _store_lease_valid(action_store, session) -> bool:
    try:
        return bool(action_store.lease_valid_for(session.owner, time.time()))
    except (AttributeError, TypeError, ValueError):
        return False


def _default_switch_approval(session, runtime, action_store, observation, frame, *, generation, context, context_sha256):
    """Use the consuming route's policy and a consumed one-shot capability, never a fabricated grant."""
    if not isinstance(context, Mapping):
        return None
    flow_id, reset_id = context.get("flow_id"), context.get("scheduler_reset_id")
    if not isinstance(flow_id, str) or not isinstance(reset_id, str) or not reset_id:
        return None
    name = observation.preset_name
    key = f"commander-talent-switch:{name.casefold()}:{generation}"
    post = f"talent-memory-applied:{name}"
    now = time.monotonic()
    foreground = getattr(runtime, "measure_foreground_package", None)
    obs = Observation(
        frame_sha256=frame.sha256, capture_completed_monotonic=frame.captured_monotonic,
        runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID, width=800, height=1280,
        valid_png=True, corrupt=False, black=False, source_state="TALENT_MEMORY", overlay_state="none_observed",
        target_identity=f"talent-memory-row:{name}:apply", target_roi=observation.apply_target,
        recognized=observation.recognized, control_class="commander_talent_preset_switch",
        consequence=_SWITCH_CONSEQUENCE, cost_type="none", cost_amount=0, quantity=1,
        expected_postcondition=post, evidence_refs=(observation.evidence_ref,), target_isolated=True,
        package_foreground=bool(callable(foreground) and foreground() == "com.global.ztmslg"),
    )
    request = PolicyRequest(
        action_id=key, action_key=key, task_id=flow_id, task_mode="supervised_validation",
        semantic_action=f"switch_commander_talent_preset:{name.casefold()}",
        expected_runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID, observation=obs, monotonic_now=now,
        observation_max_age_seconds=15.0, dispatch_max_age_seconds=10.0,
        lease_owner=session.owner, lease_valid=_store_lease_valid(action_store, session),
        unresolved_action=action_store.has_action_block(), duplicate_action_key=action_store.get_action_by_key(key) is not None,
        game_day_id=reset_id, action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
        action_kind="commander_talent_preset_switch", subject=name, resource_or_currency="none",
        maximum_cost=0, free_only=True, semantic_preconditions=_preconditions(observation, generation, context_sha256),
        semantic_postconditions=(post,), runtime_session_id=str(runtime.session),
        allowed_confirmation_dialogs=("commander_talent_free_apply_confirmation",),
    )
    policy = CentralPolicy({flow_id})
    issued = policy.issue_capability(request)
    action_store.audit(flow_id, "capability_issued", time.time(), issued.audit, key)
    if not issued.authorized or issued.capability is None:
        return None
    consumed = policy.consume_capability(issued.capability, replace(
        request, policy_phase="pre_dispatch", monotonic_now=time.monotonic()))
    action_store.audit(flow_id, "capability_consume", time.time(), consumed.audit, key)
    if not consumed.allow_dispatch:
        return None
    intent = ActionIntent(
        action_id=key, action_key=key, task_id=flow_id, semantic_action=request.semantic_action,
        source_state=obs.source_state, target_identity=obs.target_identity, target_roi=obs.target_roi,
        source_frame_sha256=frame.sha256, source_frame_captured_at=frame.captured_monotonic,
        runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID, game_day_id=reset_id, expected_postcondition=post,
        consequence=_SWITCH_CONSEQUENCE, cost_type="none", cost_amount=0, quantity=1,
        evidence_refs=(observation.evidence_ref,), target_isolated=True, action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
        action_kind=request.action_kind, subject=name, resource_or_currency="none", maximum_cost=0,
        free_only=True, semantic_preconditions=request.semantic_preconditions, semantic_postconditions=(post,),
        allowed_confirmation_dialogs=request.allowed_confirmation_dialogs,
    )
    return CommanderTalentSwitchApproval(intent, issued.policy_result, frame.sha256, generation, context_sha256)


def invalidate_commander_talent_preset(session: Any, reason: str) -> None:
    """Invalidate Applied proof after an external/manual change, restart or relevant context loss."""
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("preset invalidation requires its context-loss reason")
    memory = getattr(session, "control_memory", None)
    if isinstance(memory, dict):
        memory.pop(_PROOF_KEY, None)
    if hasattr(session, "_commander_talent_proof_runtime"):
        delattr(session, "_commander_talent_proof_runtime")


def ensure_commander_talent_preset(
    session: Any, runtime: Any, required_preset: str, *, checkpoint: Callable[[], None],
    runtime_input_lock: Any, action_store: Any, source_generation: str | int, context: Any,
    native_port: CommanderTalentNativePort,
    switch_approval: Callable[[TalentMemoryObservation, Any], CommanderTalentSwitchApproval | None] | None = None,
) -> CommanderTalentPresetResult:
    """Ensure an exact saved preset, reusing only proof from this owned visit and context."""
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
    owner, invocation_id = getattr(runtime_input_lock, "owner", None), getattr(runtime_input_lock, "invocation_id", None)
    if not all(type(value) is str and value for value in (owner, invocation_id)):
        raise RuntimeError("commander talent verification requires a held owner identity")
    session_owner, session_invocation = getattr(session, "owner", None), getattr(session, "invocation_id", None)
    if not all(type(value) is str and value for value in (session_owner, session_invocation)):
        raise RuntimeError("commander talent native session identity is missing")
    if generation != session_invocation:
        raise ValueError("source_generation must match the held native session invocation")
    if (session_owner, session_invocation) != (owner, invocation_id):
        session.assert_held(session_owner, session_invocation)
    runtime_input_lock.assert_held(owner, invocation_id)
    checkpoint()
    runtime_input_lock.assert_held(owner, invocation_id)
    if action_store is None or not callable(getattr(action_store, "has_action_block", None)):
        raise RuntimeError("commander talent verification requires the canonical action store")
    if action_store.has_action_block():
        invalidate_commander_talent_preset(session, "unresolved canonical action")
        return CommanderTalentPresetResult("unknown", False, required_preset, "CANONICAL_ACTION_REQUIRES_INSPECTION",
                                          (), 0, generation, context_sha256, identical_retry_denied=True)
    memory = getattr(session, "control_memory", None)
    if not isinstance(memory, dict):
        memory = {}
        session.control_memory = memory
    binding = {"generation": generation, "context_sha256": context_sha256, "runtime": id(runtime),
               "action_store": id(action_store), "owner": owner, "invocation_id": invocation_id,
               "session_owner": session_owner, "preset": required_preset}
    prior = memory.get(_PROOF_KEY)
    if (isinstance(prior, dict) and prior.get("binding") == binding and prior.get("evidence_refs")
            and getattr(session, "_commander_talent_proof_runtime", None) is runtime):
        return CommanderTalentPresetResult("already_applied", True, required_preset, "CURRENT_VISIT_APPLIED_PROOF_REUSED",
                                          tuple(prior["evidence_refs"]), 0, generation, context_sha256)
    invalidate_commander_talent_preset(session, "fresh preset observation required")
    prepared: dict[str, ActionIntent] = {}

    def prepare_switch(observation, frame):
        if (not observation.recognized or observation.row_state is not PresetRowState.APPLY
                or observation.apply_target is None or frame.sha256 != observation.source_frame_sha256):
            return None
        approval = (switch_approval(observation, frame) if switch_approval is not None else
                    _default_switch_approval(session, runtime, action_store, observation, frame,
                        generation=generation, context=context, context_sha256=context_sha256))
        if not isinstance(approval, CommanderTalentSwitchApproval) or not _policy_snapshot_matches(
                approval, observation, source_generation=generation, context_sha256=context_sha256):
            return None
        if action_store.has_action_block() or not _store_lease_valid(action_store, session):
            return None
        if action_store.get_action_by_key(approval.intent.action_key) is not None:
            return None
        try:
            action_store.prepare_action(approval.intent, approval.policy_result, time.time())
        except Exception:
            return None
        prepared[approval.intent.action_key] = approval.intent
        return TalentSwitchPermit(approval.intent.action_key)

    def settle_switch(action_key, status, dispatched, observation):
        intent = prepared.get(action_key)
        if intent is None:
            return
        if dispatched:
            action_store.mark_input_sent(intent.action_id, time.time(), TransportResult(True, "COMMANDER_TALENT_PRESET_SWITCH_DISPATCHED"))
        if (status == "switched" and dispatched is True and observation is not None
                and observation.recognized and observation.preset_name == required_preset
                and observation.row_state is PresetRowState.APPLIED and observation.applied_preset == required_preset
                and _source_hash(observation.source_frame_sha256) and observation.evidence_ref):
            action_store.mark_confirmed(intent.action_id, time.time(), {
                "preset_name": required_preset, "source_frame_sha256": observation.source_frame_sha256,
                "evidence_ref": observation.evidence_ref, "postcondition": f"talent-memory-applied:{required_preset}"})
        else:
            action_store.mark_unresolved(intent.action_id, time.time(), "commander_talent_switch_successor_unknown_no_retry",
                                        {"preset_name": required_preset, "dispatch_returned": dispatched})

    native_result = native_port(session, runtime, required_preset, checkpoint=checkpoint,
        runtime_input_lock=runtime_input_lock, action_store=action_store, source_generation=generation,
        context=context, switch_approval=prepare_switch, switch_outcome=settle_switch)
    runtime_input_lock.assert_held(owner, invocation_id)
    checkpoint()
    runtime_input_lock.assert_held(owner, invocation_id)
    if not isinstance(native_result, TalentPresetNativeResult) or native_result.preset_name != required_preset:
        raise TypeError("talent native port must return the requested TalentPresetNativeResult")
    current_applied = (native_result.verified and native_result.status == "already_applied"
                       and native_result.switch_action_key is None and not native_result.switch_transport_attempted)
    switched = False
    if native_result.verified and native_result.status == "switched" and native_result.switch_action_key:
        action = action_store.get_action_by_key(native_result.switch_action_key)
        switched = bool(native_result.switch_transport_attempted and isinstance(action, dict)
                        and action.get("final_status", action.get("status")) == "confirmed")
    successful = bool(native_result.evidence_refs and (current_applied or switched))
    if successful:
        memory[_PROOF_KEY] = {"binding": binding, "evidence_refs": list(native_result.evidence_refs)}
        session._commander_talent_proof_runtime = runtime
    return CommanderTalentPresetResult(
        native_result.status, successful, required_preset, native_result.reason, tuple(native_result.evidence_refs),
        native_result.input_count, generation, context_sha256, switch_action_key=native_result.switch_action_key,
        effect_reconciliation_required=native_result.switch_transport_attempted and not successful,
        identical_retry_denied=native_result.switch_transport_attempted and not successful,
    )
