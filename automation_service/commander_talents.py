"""Canonical, visit-scoped Commander preset proof and explicit switch authority."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import time
from typing import Any, Callable, Protocol

from safe_action_core.models import (
    ActionClass, ActionIntent, Observation, PolicyRequest, PolicyResult, TransportResult,
)
from safe_action_core.policy import CentralPolicy
from tasks.commander_talents import (
    APPLY_CONFIRMATION_DIALOG, PRESET_NAMES, PresetRowState, TalentMemoryObservation,
    TalentPresetNativeResult, TalentSwitchPermit, context_fingerprint,
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
    """A canonical zero-cost policy decision bound to this exact saved-preset Apply source."""
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
        "applicable-scenario-switch-authority",
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
        "action_id": "commander-talent-switch:" + hashlib.sha256(json.dumps(
            [intent.action_key, list(_preconditions(observation, source_generation, context_sha256)),
             list(intent.allowed_confirmation_dialogs)],
            ensure_ascii=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest(),
        "semantic_action": f"switch_commander_talent_preset:{name.casefold()}",
        "action_kind": "commander_talent_preset_switch", "subject": name,
        "resource_or_currency": "none", "maximum_cost": 0, "free_only": True,
        "allowed_confirmation_dialogs": intent.allowed_confirmation_dialogs,
        "semantic_preconditions": _preconditions(observation, source_generation, context_sha256),
        "semantic_postconditions": (expected_post,),
    }
    if (any(getattr(intent, key) != value for key, value in expected.items())
            or intent.action_class is not ActionClass.ZERO_COST_CONSEQUENTIAL
            or intent.cost_type != "none" or intent.cost_amount != 0
            or intent.source_state != "TALENT_MEMORY"
            or intent.target_identity != f"talent-memory-row:{name}:apply"
            or intent.target_roi != observation.apply_target
            or intent.source_frame_sha256 != observation.source_frame_sha256
            or intent.expected_postcondition != expected_post
            or intent.consequence != _SWITCH_CONSEQUENCE
            or intent.quantity != 1):
        return False
    request = policy.request_snapshot
    if not isinstance(request, dict) or not isinstance(request.get("observation"), dict):
        return False
    expected.update(action_id=intent.action_id, task_id=intent.task_id,
                    action_class=intent.action_class.value,
                    expected_runtime_profile_id=intent.runtime_profile_id)
    for key, value in expected.items():
        if request.get(key) != (list(value) if isinstance(value, tuple) else value):
            return False
    observed = request["observation"]
    return all(observed.get(key) == value for key, value in {
        "frame_sha256": observation.source_frame_sha256, "source_state": "TALENT_MEMORY",
        "target_identity": intent.target_identity, "target_roi": list(observation.apply_target),
        "control_class": "commander_talent_preset_switch", "consequence": _SWITCH_CONSEQUENCE,
        "cost_type": "none", "cost_amount": 0,
        "quantity": 1, "expected_postcondition": expected_post,
    }.items())


def _store_lease_valid(action_store, session) -> bool:
    try:
        return bool(action_store.lease_valid_for(session.owner, time.time()))
    except (AttributeError, TypeError, ValueError):
        return False


def commander_talent_switch_approval(
    session: Any, runtime: Any, *, action_store: Any, task_id: str, game_day_id: str,
    source_generation: str | int, context: Any,
) -> Callable[[TalentMemoryObservation, Any], CommanderTalentSwitchApproval | None]:
    """Bind a consumer's saved-preset Apply to a fresh canonical zero-cost policy decision.

    Saved talent presets switch at no cost. The only confirmation authority is the
    saved-preset Apply dialog; talent-tree Reset or edits are never admitted. Each call
    evaluates the exact current source frame, owner lease, unresolved-action block and
    duplicate key, so a stale, changed or previously attempted switch is denied.
    """
    if not all(type(value) is str and value.strip() == value and value for value in (task_id, game_day_id)):
        raise ValueError("commander talent switch approval requires exact consumer task and game day")
    generation = _generation(source_generation)
    context_sha256 = context_fingerprint(context)
    policy = CentralPolicy({task_id})

    def approve(observation: TalentMemoryObservation, frame: Any) -> CommanderTalentSwitchApproval | None:
        name, target = observation.preset_name, observation.apply_target
        pixels, captured = getattr(frame, "frame", None), getattr(frame, "captured_monotonic", None)
        if pixels is None:
            return None
        owner = getattr(session, "owner", None)
        if (not observation.recognized or observation.row_state is not PresetRowState.APPLY
                or name not in PRESET_NAMES or target is None or not observation.evidence_ref
                or not _source_hash(observation.source_frame_sha256)
                or getattr(frame, "sha256", None) != observation.source_frame_sha256
                or getattr(pixels, "ndim", None) != 3 or type(captured) is not float
                or type(owner) is not str or not owner):
            return None
        try:
            foreground = runtime.measure_foreground_package() == "com.global.ztmslg"
            lease_valid = bool(action_store.lease_valid_for(owner, time.time()))
            unresolved = bool(action_store.has_action_block())
            action_key = f"commander-talent-switch:{name.casefold()}:{generation}"
            duplicate = action_store.get_action_by_key(action_key) is not None
        except (AttributeError, TypeError, ValueError):
            return None
        x0, y0, x1, y1 = target
        preconditions = _preconditions(observation, generation, context_sha256)
        dialogs = (APPLY_CONFIRMATION_DIALOG,)
        action_id = "commander-talent-switch:" + hashlib.sha256(json.dumps(
            [action_key, list(preconditions), list(dialogs)], ensure_ascii=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        semantic_action = f"switch_commander_talent_preset:{name.casefold()}"
        target_identity = f"talent-memory-row:{name}:apply"
        post = f"talent-memory-applied:{name}"
        evidence = (observation.evidence_ref,)
        request = PolicyRequest(
            action_id=action_id, action_key=action_key, task_id=task_id, task_mode="supervised_validation",
            semantic_action=semantic_action, expected_runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
            observation=Observation(
                frame_sha256=frame.sha256, capture_completed_monotonic=captured,
                runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID, width=int(pixels.shape[1]),
                height=int(pixels.shape[0]), valid_png=int(pixels.shape[2]) == 3, corrupt=False,
                black=not bool(pixels.any()), source_state="TALENT_MEMORY", overlay_state="none",
                target_identity=target_identity, target_roi=target, recognized=True,
                control_class=_SWITCH_CONSEQUENCE, consequence=_SWITCH_CONSEQUENCE,
                cost_type="none", cost_amount=0, quantity=1, expected_postcondition=post,
                evidence_refs=evidence,
                critical_roi_hashes=(("talent-memory-apply", hashlib.sha256(
                    pixels[y0:y1, x0:x1].tobytes()).hexdigest()),),
                ocr_result_frame_sha256=frame.sha256, ocr_result_capture_completed_monotonic=captured,
                source_family="COMMANDER_TALENT", target_isolated=True, package_foreground=foreground,
            ),
            monotonic_now=time.monotonic(), observation_max_age_seconds=30.0, dispatch_max_age_seconds=10.0,
            lease_owner=owner, lease_valid=lease_valid, unresolved_action=unresolved,
            duplicate_action_key=duplicate, game_day_id=game_day_id,
            action_class=ActionClass.ZERO_COST_CONSEQUENTIAL, action_kind=_SWITCH_CONSEQUENCE,
            subject=name, resource_or_currency="none", maximum_cost=0, free_only=True,
            allowed_confirmation_dialogs=dialogs, semantic_preconditions=preconditions,
            semantic_postconditions=(post,),
        )
        decision = policy.evaluate(request)
        if not decision.authorized:
            return None
        intent = ActionIntent(
            action_id=action_id, action_key=action_key, task_id=task_id, semantic_action=semantic_action,
            source_state="TALENT_MEMORY", target_identity=target_identity, target_roi=target,
            source_frame_sha256=frame.sha256, source_frame_captured_at=captured,
            runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID, game_day_id=game_day_id,
            expected_postcondition=post, consequence=_SWITCH_CONSEQUENCE, cost_type="none",
            cost_amount=0, quantity=1, evidence_refs=evidence, source_family="COMMANDER_TALENT",
            target_isolated=True, action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
            action_kind=_SWITCH_CONSEQUENCE, subject=name, resource_or_currency="none",
            maximum_cost=0, free_only=True, allowed_confirmation_dialogs=dialogs,
            semantic_preconditions=preconditions, semantic_postconditions=(post,),
        )
        return CommanderTalentSwitchApproval(intent, decision, frame.sha256, generation, context_sha256)

    return approve


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
        # Saved-preset Apply is zero-cost; authority is the consumer's fresh canonical
        # policy decision on this exact frame, never a historical approval.
        approval = switch_approval(observation, frame) if switch_approval is not None else None
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
        return TalentSwitchPermit(approval.intent.action_key, approval.intent.allowed_confirmation_dialogs)

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
