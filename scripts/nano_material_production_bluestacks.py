"""Canonical native route for zero-resource Nano Material Production."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping

import numpy as np

from automation_service.registry import (
    NANO_MATERIAL_PRODUCTION_FLOW_ID,
    NANO_MATERIAL_PRODUCTION_MAX_INPUTS,
    NANO_MATERIAL_PRODUCTION_PRODUCT_ID,
    NANO_MATERIAL_PRODUCTION_PRODUCT_REVISION,
    NANO_MATERIAL_PRODUCTION_PROFILE_ID,
)
from safe_action_core import (
    ActionClass,
    ActionStatus,
    CentralPolicy,
    Observation,
    PolicyRequest,
    SafeActionExecutor,
    SafetyStore,
    TransportResult,
)
from scripts.atlas_runtime_startup import normalize_runtime_home_atlas_startup
from scripts.bounded_tesseract import call_ocr, tesseract_data
from scripts.home_atlas_bluestacks import (
    HOME_ATLAS_NAVIGATION_TASK_ID,
    bind_or_pan_mapped_home_building,
    load_home_atlas as _load_atlas,
)
from scripts.startup_normalization import is_clean_home_frame
from tasks.home_atlas_vision import (
    BLUESTACKS_SAFE_INTERACTION_BOX,
    HUD_MASK_RECTS,
    BlueStacksHomeLocalizer,
    bind_visible_building,
    frame_digest,
)
from tasks.nano_material_production import (
    MATERIAL_PRODUCTION_TAB,
    NANO_MATERIAL_PRODUCTION_DURATION_SECONDS,
    NANO_MATERIAL_PRODUCTION_TARGET,
    MaterialProductionObservation,
    material_production_authorizeable,
    material_production_claim_postcondition_verified,
    material_production_claim_spec,
    material_production_due_at,
    material_production_start_postcondition_verified,
    material_production_start_spec,
)
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID, BLUESTACKS_NATIVE_TARGET_PROVENANCE

FLOW_ID = NANO_MATERIAL_PRODUCTION_FLOW_ID
PRODUCT_ID = NANO_MATERIAL_PRODUCTION_PRODUCT_ID
PRODUCT_REVISION = NANO_MATERIAL_PRODUCTION_PRODUCT_REVISION
PROFILE_ID = NANO_MATERIAL_PRODUCTION_PROFILE_ID
MAX_INPUTS = NANO_MATERIAL_PRODUCTION_MAX_INPUTS
MAX_ACTIONS = 2
DEFAULT_ATLAS = Path(__file__).resolve().parents[1] / "tasks" / "assets" / "home_atlas" / "bluestacks" / "800x1280" / "atlas.json"
GEAR_FACTORY_ID = "home.building.gear_factory"
_TIMER_RE = re.compile(r"(?<![0-9])([0-9]{1,2}):([0-5][0-9]):([0-5][0-9])(?![0-9])", re.ASCII)
_DURATION_RE = re.compile(r"\b(?:duration|production time)\s*[:=-]?\s*(21600\s*(?:seconds?|s)|6\s*(?:hours?|hrs?)|06:00:00)\b", re.IGNORECASE | re.ASCII)


@dataclass(frozen=True)
class _Word:
    text: str
    confidence: float
    roi: tuple[int, int, int, int]
    line: tuple[int, int, int]


@dataclass(frozen=True)
class _PanelRead:
    observation: MaterialProductionObservation | None
    control_roi: tuple[int, int, int, int] | None
    reason: str

@dataclass(frozen=True)
class _CaptureView:
    frame: np.ndarray
    sha256: str
    path: Path



def _normal(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold(), re.ASCII))


def _ocr_words(frame: np.ndarray) -> tuple[_Word, ...]:
    if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape != (1280, 800, 3):
        return ()
    try:
        data = call_ocr(tesseract_data, frame, config="--psm 11", call_timeout=5.0)
    except Exception:
        return ()
    if not isinstance(data, Mapping):
        return ()
    fields = ("text", "left", "top", "width", "height", "conf", "block_num", "par_num", "line_num")
    if any(not isinstance(data.get(name), (tuple, list)) for name in fields):
        return ()
    size = min(len(data[name]) for name in fields)
    words: list[_Word] = []
    for index in range(size):
        text = str(data["text"][index]).strip()
        if not text:
            continue
        try:
            confidence = float(data["conf"][index])
            x, y = int(data["left"][index]), int(data["top"][index])
            width, height = int(data["width"][index]), int(data["height"][index])
            line = (int(data["block_num"][index]), int(data["par_num"][index]), int(data["line_num"][index]))
        except (TypeError, ValueError, OverflowError):
            continue
        if confidence < 35 or width <= 0 or height <= 0:
            continue
        x1, y1 = min(800, x + width), min(1280, y + height)
        if 0 <= x < x1 and 0 <= y < y1:
            words.append(_Word(text, confidence, (x, y, x1, y1), line))
    return tuple(words)


def _lines(words: tuple[_Word, ...]) -> tuple[tuple[str, tuple[_Word, ...]], ...]:
    groups: dict[tuple[int, int, int], list[_Word]] = {}
    for word in words:
        groups.setdefault(word.line, []).append(word)
    return tuple(
        (" ".join(item.text for item in ordered), ordered)
        for _key, group in sorted(groups.items())
        for ordered in (tuple(sorted(group, key=lambda item: item.roi[0])),)
    )


def _phrase_lines(lines, phrase: str) -> list[tuple[str, tuple[_Word, ...]]]:
    expected = _normal(phrase)
    return [(text, words) for text, words in lines if _normal(text) == expected]


def _word_roi(words: tuple[_Word, ...]) -> tuple[int, int, int, int] | None:
    if not words:
        return None
    return (
        max(0, min(word.roi[0] for word in words) - 8),
        max(0, min(word.roi[1] for word in words) - 8),
        min(800, max(word.roi[2] for word in words) + 8),
        min(1280, max(word.roi[3] for word in words) + 8),
    )


def _bounds(words: tuple[_Word, ...]) -> tuple[int, int, int, int] | None:
    if not words:
        return None
    return (
        max(0, min(word.roi[0] for word in words) - 20),
        max(0, min(word.roi[1] for word in words) - 20),
        min(800, max(word.roi[2] for word in words) + 20),
        min(1280, max(word.roi[3] for word in words) + 20),
    )


def _zero_cost_proof(lines) -> bool:
    panel_lines = tuple(
        (text, words)
        for text, words in lines
        if _safe_nav_roi(_bounds(words))
    )
    cost_lines = [_normal(text) for text, _words in panel_lines if "cost" in _normal(text)]
    zero_cost = any(
        re.search(r"\bcost\s*(?:none\s*)?(?:[:=-]\s*)?0\b", line, re.ASCII)
        or re.search(r"\bcost\s+free\b", line, re.ASCII)
        for line in cost_lines
    )
    no_other_costs = any(
        _normal(text) in {"no other costs", "other costs 0", "additional costs 0", "no additional costs"}
        for text, _words in panel_lines
    )
    forbidden_cost = any(
        marker in _normal(text)
        for text, _words in panel_lines
        for marker in (
            "diamond", "nano parts", "coins", "gold", "silver", "currency",
            "food", "wood", "steel", "gas", "oil", "iron", "alloy", "ore",
            "crystal", "energy", "token", "ticket", "voucher", "credit", "cash",
            "box", "crate", "chest", "item",
        )
    )
    return bool(zero_cost and no_other_costs and not forbidden_cost)


def _duration_proof(lines) -> bool:
    return any(_DURATION_RE.search(text) for text, _words in lines)


def _panel_observation(captured, *, context, occurrence_key: str) -> _PanelRead:
    words = _ocr_words(captured.frame)
    lines = _lines(words)
    if len(_phrase_lines(lines, "Nanoweapon")) != 1:
        return _PanelRead(None, None, "nanoweapon_title_not_uniquely_recognized")
    if len(_phrase_lines(lines, "Material Production")) != 1:
        return _PanelRead(None, None, "material_production_tab_not_uniquely_recognized")
    if not _duration_proof(lines):
        return _PanelRead(None, None, "exact_21600_second_duration_not_recognized")
    cost_known = _zero_cost_proof(lines)
    if not cost_known:
        return _PanelRead(None, None, "zero_resource_cost_or_other_costs_unknown")

    timers: list[tuple[int, str, tuple[_Word, ...]]] = []
    for line, line_words in lines:
        if "duration" in _normal(line) or "production time" in _normal(line):
            continue
        match = _TIMER_RE.search(line)
        if match:
            hours, minutes, seconds = (int(value) for value in match.groups())
            timers.append((hours * 3600 + minutes * 60 + seconds, line, line_words))
    starts = _phrase_lines(lines, "Start")
    claims = _phrase_lines(lines, "Claim")
    active_markers = [row for row in lines if _normal(row[0]) in {"production active", "active production"}]
    idle_markers = [row for row in lines if _normal(row[0]) in {"production idle", "idle production"}]
    complete_markers = [row for row in lines if _normal(row[0]) in {"production complete", "production completed", "completed production"}]
    one_slot = any(_normal(line) in {"production slot 1 of 1", "slots 1 of 1", "one production slot", "production slots 1 1"} for line, _ in lines)
    if not one_slot:
        return _PanelRead(None, None, "one_slot_state_not_recognized")
    control = None
    if len(claims) == 1 and len(starts) == 0 and len(timers) == 1 and timers[0][0] == 0 and len(complete_markers) == 1:
        production_state, active_count, completed_count, remaining, claim_visible, start_enabled = "complete", 0, 1, 0, True, False
        control = _word_roi(claims[0][1])
    elif len(starts) == 1 and len(claims) == 0 and len(timers) == 1 and timers[0][0] == 0 and len(idle_markers) == 1:
        production_state, active_count, completed_count, remaining, claim_visible, start_enabled = "idle", 0, 0, 0, False, True
        control = _word_roi(starts[0][1])
    elif len(starts) == 0 and len(claims) == 0 and len(timers) == 1 and 0 < timers[0][0] <= NANO_MATERIAL_PRODUCTION_DURATION_SECONDS and len(active_markers) == 1:
        production_state, active_count, completed_count, remaining, claim_visible, start_enabled = "active", 1, 0, timers[0][0], False, False
        control = _word_roi(timers[0][2])
    else:
        return _PanelRead(None, None, "production_state_unknown_or_ambiguous")
    panel_words = tuple(word for _line, line_words in lines for word in line_words)
    panel = _bounds(panel_words)
    if panel is None or control is None or not (panel[0] <= control[0] < control[2] <= panel[2] and panel[1] <= control[1] < control[3] <= panel[3]):
        return _PanelRead(None, None, "production_target_bounds_unknown")
    evidence_ref = _evidence_ref(captured, context.session)
    observation = MaterialProductionObservation(
        screen_state="NANOWEAPON",
        selected_nanoweapon=True,
        selected_tab=MATERIAL_PRODUCTION_TAB,
        production_state=production_state,
        active_production_count=active_count,
        production_duration_seconds=NANO_MATERIAL_PRODUCTION_DURATION_SECONDS,
        timer_seconds_remaining=remaining,
        cost_known=True,
        cost_type="none",
        cost_amount=0,
        other_costs_known=True,
        nonzero_other_costs=False,
        target_identity=NANO_MATERIAL_PRODUCTION_TARGET,
        target_roi=control,
        panel_bounds=panel,
        completed_batch_count=completed_count,
        start_enabled=start_enabled,
        claim_visible=claim_visible,
        overlay_state="none_observed",
        target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
        source_frame_sha256=str(captured.sha256),
        evidence_refs=(evidence_ref,) if evidence_ref else (),
        occurrence_key=occurrence_key,
        runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        recognized=True,
    )
    if not material_production_authorizeable(observation):
        return _PanelRead(None, None, "task_model_rejected_current_production_state")
    return _PanelRead(observation, control, "recognized")


def _evidence_ref(captured, session) -> str:
    try:
        path = Path(captured.path).resolve().relative_to(Path(session.session_directory).resolve())
    except (OSError, ValueError, TypeError):
        return ""
    return "evidence/" + path.as_posix()


def _capture(context, label: str):
    context.checkpoint()
    return context.session.observe(context.runtime.capture, label=label)


def _identity_value(context, name: str) -> str:
    value = getattr(context.identity, name, None)
    if type(value) is not str or not value:
        raise ValueError(f"Nano Material Production requires current {name}")
    return value


def _route_observation(context, captured, *, target_identity: str, target_roi, control_class: str, consequence: str, postcondition: str, source_state: str = "NANOWEAPON") -> Observation:
    runtime = context.runtime
    return Observation(
        frame_sha256=str(captured.sha256),
        capture_completed_monotonic=float(captured.captured_monotonic),
        runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        width=int(captured.frame.shape[1]),
        height=int(captured.frame.shape[0]),
        valid_png=True,
        corrupt=False,
        black=not bool(captured.frame.any()),
        source_state=source_state,
        overlay_state="none_observed",
        target_identity=target_identity,
        target_roi=tuple(target_roi) if target_roi is not None else None,
        recognized=True,
        control_class=control_class,
        consequence=consequence,
        cost_type="none",
        cost_amount=0,
        quantity=1,
        expected_postcondition=postcondition,
        evidence_refs=(str(captured.path),),
        source_family="nano_material_production",
        target_isolated=target_roi is not None,
        package_foreground=str(runtime.measure_foreground_package()) == "com.global.ztmslg",
    )


def _semantic_tokens(observation: MaterialProductionObservation, *, action_kind: str, occurrence_key: str) -> tuple[str, ...]:
    spec = material_production_claim_spec(observation) if action_kind == "CLAIM_NANO_MATERIAL_PRODUCTION" else material_production_start_spec(observation)
    expected = f"native_occurrence_key={occurrence_key}"
    if expected not in spec.semantic_preconditions:
        raise ValueError("Material Production task spec lost its exact occurrence binding")
    return spec.semantic_preconditions


def _dispatch_action(context, *, before_capture, before: MaterialProductionObservation, occurrence_key: str, action_kind: str) -> dict[str, Any]:
    claim = action_kind == "CLAIM_NANO_MATERIAL_PRODUCTION"
    spec = material_production_claim_spec(before) if claim else material_production_start_spec(before)
    phase = "claim" if claim else "start"
    key = f"{PRODUCT_ID}|{occurrence_key}|{phase}"
    subject = spec.subject
    postcondition = spec.semantic_postconditions[0]
    semantic_action = "claim_nano_material_production" if claim else "start_nano_material_production"
    consequence = "nano_material_production_claim" if claim else "nano_material_production_start"
    control_class = "CLAIM" if claim else "PRODUCE"
    action_id = f"nano-material-production:{hashlib.sha256((key + context.session.invocation_id).encode()).hexdigest()}"
    target_roi = tuple(before.target_roi)
    if str(before_capture.sha256) != before.source_frame_sha256:
        return {"status": "blocked", "reason": "production_source_frame_changed", "transport_calls": 0}
    policy_observation = _route_observation(
        context, before_capture, target_identity=subject, target_roi=target_roi,
        control_class=control_class, consequence=consequence, postcondition=postcondition,
    )
    now = float(context.utc_clock())
    monotonic_now = float(context.monotonic_clock())
    store = context.action_store
    request = PolicyRequest(
        action_id=action_id,
        action_key=key,
        task_id=FLOW_ID,
        task_mode="supervised_validation",
        semantic_action=semantic_action,
        expected_runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        observation=policy_observation,
        monotonic_now=monotonic_now,
        observation_max_age_seconds=30.0,
        dispatch_max_age_seconds=30.0,
        lease_owner=context.session.owner,
        lease_valid=store.lease_valid_for(context.session.owner, now),
        unresolved_action=store.has_action_block(),
        duplicate_action_key=store.action_key_exists(key),
        game_day_id=_identity_value(context, "reset_id"),
        action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
        action_kind=action_kind,
        subject=subject,
        resource_or_currency=None,
        maximum_cost=0,
        free_only=True,
        semantic_preconditions=_semantic_tokens(before, action_kind=action_kind, occurrence_key=occurrence_key),
        semantic_postconditions=spec.semantic_postconditions,
        runtime_session_id=str(context.runtime.session),
    )
    policy = CentralPolicy(frozenset({FLOW_ID}))

    successors: list[tuple[Any, MaterialProductionObservation | None, bool]] = []
    runtime = context.runtime

    def observe_successor(captured) -> bool:
        panel = _panel_observation(captured, context=context, occurrence_key=occurrence_key)
        after = panel.observation
        if claim:
            verified = material_production_claim_postcondition_verified(before, after)
        else:
            verified = material_production_start_postcondition_verified(before, after)
        successors.append((captured, after, bool(verified)))
        return bool(verified)
    def action_evidence() -> dict[str, object]:
        post_capture = successors[-1][0] if successors else None
        return {
            "before": _retained_capture_reference(context, before_capture),
            "after": _retained_capture_reference(context, post_capture),
        }

    immediate_observation = None

    def recapture() -> Observation:
        nonlocal before_capture, before, immediate_observation
        if immediate_observation is not None:
            return immediate_observation
        context.validate_identity()
        captured = _capture(context, f"nano-material-production-{phase}-pre-dispatch")
        fresh = _panel_observation(
            captured,
            context=context,
            occurrence_key=occurrence_key,
        ).observation
        if (
            fresh is None
            or not material_production_authorizeable(fresh)
            or fresh.production_state != before.production_state
            or fresh.active_production_count != before.active_production_count
            or fresh.completed_batch_count != before.completed_batch_count
            or fresh.timer_seconds_remaining != before.timer_seconds_remaining
            or fresh.target_roi != before.target_roi
            or fresh.occurrence_key != occurrence_key
        ):
            raise ValueError("Material Production immediate pre-dispatch state changed")
        before_capture = captured
        before = fresh
        immediate_observation = _route_observation(
            context,
            captured,
            target_identity=subject,
            target_roi=tuple(fresh.target_roi),
            control_class=control_class,
            consequence=consequence,
            postcondition=postcondition,
        )
        return immediate_observation

    try:
        immediate_policy_observation = recapture()
    except Exception as exc:
        return {
            "status": "blocked",
            "reason": f"{type(exc).__name__}:{exc}",
            "transport_calls": 0,
            "action_key": key,
        }
    policy_now = float(context.utc_clock())
    capability_request = replace(
        request,
        observation=immediate_policy_observation,
        monotonic_now=float(context.monotonic_clock()),
        lease_owner=context.session.owner,
        lease_valid=store.lease_valid_for(context.session.owner, policy_now),
        unresolved_action=store.has_action_block(),
        duplicate_action_key=store.action_key_exists(key),
        policy_phase="pre_dispatch",
    )
    issued = policy.issue_capability(capability_request)
    store.audit(FLOW_ID, "capability_issued", policy_now, issued.audit, action_id)
    if not issued.authorized or issued.capability is None:
        return {
            "status": "blocked",
            "reason": issued.reason_code,
            "transport_calls": 0,
            "action_key": key,
        }
    def transport(_intent):
        starting = int(getattr(runtime, "input_count", 0))

        def authorize(current):
            rebound = _panel_observation(current, context=context, occurrence_key=occurrence_key).observation
            if (
                current.sha256 != before_capture.sha256
                or rebound is None
                or not material_production_authorizeable(rebound)
                or rebound.production_state != before.production_state
                or rebound.active_production_count != before.active_production_count
                or rebound.completed_batch_count != before.completed_batch_count
                or rebound.timer_seconds_remaining != before.timer_seconds_remaining
                or rebound.target_roi != before.target_roi
                or rebound.occurrence_key != occurrence_key
            ):
                raise RuntimeError("Material Production source or selector changed before dispatch")
            context.checkpoint()
            context.validate_identity()

        def dispatch(current):
            runtime.tap(
                current,
                target_identity=subject,
                target_roi=target_roi,
                action_key=key,
                action_class=action_kind,
                consequential=True,
            )

        def settled():
            time.sleep(float(context.settle_seconds))
            context.checkpoint()
            return runtime.capture(f"nano-material-production-{phase}-successor-settled")

        try:
            context.session.run_action(
                action_class=action_kind,
                label=f"nano-material-production-{phase}",
                capture=runtime.capture,
                authorize=authorize,
                dispatch=dispatch,
                recognize=lambda captured: postcondition if observe_successor(captured) else "unknown",
                settled_successor=settled,
                consequence_class=consequence,
            )
        except Exception as exc:
            sent = int(getattr(runtime, "input_count", 0)) - starting
            return TransportResult(sent == 1, f"NANO_MATERIAL_PRODUCTION_{phase.upper()}_{type(exc).__name__}")
        sent = int(getattr(runtime, "input_count", 0)) - starting
        return TransportResult(sent == 1, "NANO_MATERIAL_PRODUCTION_INPUT_SENT" if sent == 1 else "NANO_MATERIAL_PRODUCTION_INPUT_NOT_SENT")

    def post_observe():
        for captured, after, verified in successors:
            yield Observation(
                frame_sha256=str(captured.sha256),
                capture_completed_monotonic=float(captured.captured_monotonic),
                runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
                width=int(captured.frame.shape[1]),
                height=int(captured.frame.shape[0]),
                valid_png=True,
                corrupt=False,
                black=not bool(captured.frame.any()),
                source_state="NANOWEAPON" if verified else "UNKNOWN",
                overlay_state="none_observed" if verified else "unknown",
                target_identity=subject if verified else None,
                target_roi=tuple(after.target_roi) if verified and after is not None else None,
                recognized=bool(verified),
                evidence_refs=(str(captured.path),),
            )

    starting_inputs = getattr(runtime, "input_count", None)
    try:
        execution = SafeActionExecutor(
            store,
            policy,
            context.session.owner,
            lambda: float(context.monotonic_clock()),
            transport,
            recapture,
            post_observe,
            lambda _intent, observed: bool(
                successors and successors[-1][2] and observed.frame_sha256 == successors[-1][0].sha256
            ),
            wall_clock=lambda: float(context.utc_clock()),
            max_pre_dispatch_attempts=1,
        ).execute(request, issued.capability)
        row = store.get_action_by_key(key)
    except Exception as exc:
        ending_inputs = getattr(runtime, "input_count", None)
        accounting_known = (
            type(starting_inputs) is int
            and type(ending_inputs) is int
            and ending_inputs >= starting_inputs
        )
        sent = ending_inputs - starting_inputs if accounting_known else 0
        try:
            journal_blocked = bool(store.has_action_block())
        except Exception:
            journal_blocked = True
        unresolved = bool(sent or journal_blocked or not accounting_known)
        evidence = action_evidence()
        return {
            "status": "unresolved" if unresolved else "blocked",
            "reason": f"{type(exc).__name__}:{exc}",
            "action_key": key,
            "journal_status": None,
            "transport_calls": sent,
            "effect_reconciliation_required": unresolved,
            "identical_retry_denied": unresolved,
            "successor_capture": None,
            "successor_observation": None,
            "last_action_evidence": evidence,
        }
    sent = int(execution.transport_calls)
    final_successor = next((item for item in reversed(successors) if item[2]), None)
    evidence = action_evidence()
    return {
        "status": "confirmed" if execution.status is ActionStatus.CONFIRMED else "unresolved" if execution.status is ActionStatus.UNRESOLVED else "blocked",
        "reason": execution.reason,
        "action_key": key,
        "journal_status": row.get("final_status") if row else None,
        "transport_calls": sent,
        "effect_reconciliation_required": execution.status is ActionStatus.UNRESOLVED,
        "identical_retry_denied": execution.status is ActionStatus.UNRESOLVED or sent > 0 and execution.status is not ActionStatus.CONFIRMED,
        "successor_capture": final_successor[0] if final_successor else None,
        "successor_observation": final_successor[1] if final_successor else None,
        "last_action_evidence": evidence,
    }


def _safe_nav_roi(roi) -> bool:
    if roi is None:
        return False
    try:
        x0, y0, x1, y1 = roi
    except (TypeError, ValueError):
        return False
    sx0, sy0, sx1, sy1 = BLUESTACKS_SAFE_INTERACTION_BOX
    return bool(
        type(x0) is int and type(y0) is int and type(x1) is int and type(y1) is int
        and sx0 <= x0 < x1 <= sx1 and sy0 <= y0 < y1 <= sy1
        and not any(x0 < hx1 and x1 > hx0 and y0 < hy1 and y1 > hy0 for hx0, hy0, hx1, hy1 in HUD_MASK_RECTS)
    )


def _line_target(frame: np.ndarray, phrase: str) -> tuple[int, int, int, int] | None:
    hits = _phrase_lines(_lines(_ocr_words(frame)), phrase)
    return _word_roi(hits[0][1]) if len(hits) == 1 else None


def _is_nanoweapon_page(frame: np.ndarray) -> bool:
    lines = _lines(_ocr_words(frame))
    return bool(
        len(_phrase_lines(lines, "Nanoweapon")) == 1
        and len(_phrase_lines(lines, "Craft Weapon")) == 1
        and len(_phrase_lines(lines, "Material Production")) == 1
    )


def _is_gear_factory_menu(frame: np.ndarray) -> bool:
    lines = _lines(_ocr_words(frame))
    return bool(
        len(_phrase_lines(lines, "Gear Factory")) == 1
        and len(_phrase_lines(lines, "Nanoweapon")) == 1
    )


def _home_binding(frame: np.ndarray, atlas, localizer):
    if not is_clean_home_frame(frame):
        return None
    localization = localizer.localize(frame)
    if not localization.recognized or localization.stale or localization.overlay:
        return None
    binding = bind_visible_building(
        frame, localization, atlas.lookup_building(GEAR_FACTORY_ID), home_is_clean=is_clean_home_frame,
    )
    if binding is None or binding.building_id != GEAR_FACTORY_ID or binding.frame_sha256 != frame_digest(frame):
        return None
    if binding.overlay_intersects or binding.ambiguous_overlap or not binding.semantic_evidence or not _safe_nav_roi(binding.target_roi):
        return None
    return binding




def _navigation_action(
    context,
    *,
    label: str,
    target_identity: str,
    source_state: str,
    expected_postcondition: str,
    control_class: str,
    bind: Callable[[Any], tuple[int, int, int, int] | None],
    source_recognize: Callable[[Any], bool],
    recognize: Callable[[Any], str | None],
    allowed_successors: tuple[str, ...],
    dispatch: Callable[[Any, str, tuple[int, int, int, int] | None], None],
) -> bool:
    runtime, session, store = context.runtime, context.session, context.action_store
    planning = _capture(context, f"{label}-planning")
    if not source_recognize(planning.frame):
        return False
    planned_roi = bind(planning.frame)
    if control_class == "GO" and not _safe_nav_roi(planned_roi):
        return False
    if control_class != "GO" and planned_roi is not None and not _safe_nav_roi(planned_roi):
        return False
    proposal = _route_observation(
        context,
        planning,
        target_identity=target_identity,
        target_roi=planned_roi,
        control_class=control_class,
        consequence="navigate_zero_cost",
        postcondition=expected_postcondition,
        source_state=source_state,
    )
    action_key = f"{PRODUCT_ID}|{context.occurrence_key}|navigation:{label}"
    action_id = f"nano-material-navigation:{hashlib.sha256((action_key + session.invocation_id).encode()).hexdigest()}"
    now = float(context.utc_clock())
    request = PolicyRequest(
        action_id=action_id,
        action_key=action_key,
        task_id=HOME_ATLAS_NAVIGATION_TASK_ID,
        task_mode="supervised_validation",
        semantic_action="navigate_zero_cost",
        expected_runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        observation=proposal,
        monotonic_now=float(context.monotonic_clock()),
        observation_max_age_seconds=30.0,
        dispatch_max_age_seconds=30.0,
        lease_owner=session.owner,
        lease_valid=store.lease_valid_for(session.owner, now),
        unresolved_action=store.has_action_block(),
        duplicate_action_key=store.action_key_exists(action_key),
        action_class=ActionClass.NAVIGATION_ONLY,
        runtime_session_id=str(runtime.session),
    )
    policy = CentralPolicy(frozenset({HOME_ATLAS_NAVIGATION_TASK_ID}))
    try:
        context.checkpoint()
        context.validate_identity()
        fresh = runtime.capture(f"{label}-pre-dispatch")
        if not source_recognize(fresh.frame):
            raise ValueError("navigation source is not recognized in a fresh frame")
        fresh_roi = bind(fresh.frame)
        if fresh_roi != planned_roi or (
            control_class == "GO" and not _safe_nav_roi(fresh_roi)
        ):
            raise ValueError("navigation target could not be rebound from a fresh frame")
        planning = fresh
        planned_roi = fresh_roi
        proposal = _route_observation(
            context,
            fresh,
            target_identity=target_identity,
            target_roi=fresh_roi,
            control_class=control_class,
            consequence="navigate_zero_cost",
            postcondition=expected_postcondition,
            source_state=source_state,
        )
    except Exception:
        return False
    issue_time = float(context.utc_clock())
    capability_request = replace(
        request,
        observation=proposal,
        monotonic_now=float(context.monotonic_clock()),
        lease_owner=session.owner,
        lease_valid=store.lease_valid_for(session.owner, issue_time),
        unresolved_action=store.has_action_block(),
        duplicate_action_key=store.action_key_exists(action_key),
        policy_phase="pre_dispatch",
    )
    issued = policy.issue_capability(capability_request)
    store.audit(HOME_ATLAS_NAVIGATION_TASK_ID, "capability_issued", issue_time, issued.audit, action_id)
    if not issued.authorized or issued.capability is None:
        return False

    successors: list[tuple[Any, str]] = []

    def recognize_frame(captured):
        state = recognize(captured)
        recognized = state if state in allowed_successors else "UNKNOWN"
        successors.append((captured, recognized))
        return recognized.lower() if recognized != "UNKNOWN" else "unknown"

    def transport(_intent):
        starting = int(getattr(runtime, "input_count", 0))

        def authorize(before):
            if frame_digest(before.frame) != frame_digest(planning.frame) or not source_recognize(before.frame):
                raise RuntimeError("navigation source changed before dispatch")
            roi = bind(before.frame)
            if roi != planned_roi or (
                control_class == "GO" and not _safe_nav_roi(roi)
            ):
                raise RuntimeError("navigation target changed before dispatch")

        def send(before):
            context.checkpoint()
            dispatch(before, action_key, planned_roi)

        def settled():
            time.sleep(float(context.settle_seconds))
            context.checkpoint()
            return runtime.capture(f"{label}-settled")

        try:
            session.run_action(
                action_class="navigation",
                label=label,
                capture=runtime.capture,
                authorize=authorize,
                dispatch=send,
                recognize=recognize_frame,
                consequence_class="navigation_only",
                settled_successor=settled,
            )
        except Exception as exc:
            sent = int(getattr(runtime, "input_count", 0)) - starting
            return TransportResult(sent == 1, f"NANO_NAVIGATION_{type(exc).__name__}")
        sent = int(getattr(runtime, "input_count", 0)) - starting
        return TransportResult(
            sent == 1,
            "NANO_NAVIGATION_INPUT_SENT" if sent == 1 else "NANO_NAVIGATION_INPUT_NOT_SENT",
        )

    def post_observe():
        observed = successors or [(planning, "UNKNOWN")]
        for captured, state in observed:
            yield Observation(
                frame_sha256=str(captured.sha256),
                capture_completed_monotonic=float(captured.captured_monotonic),
                runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
                width=int(captured.frame.shape[1]),
                height=int(captured.frame.shape[0]),
                valid_png=True,
                corrupt=False,
                black=not bool(captured.frame.any()),
                source_state=state,
                overlay_state="none_observed" if state != "UNKNOWN" else "unknown",
                target_identity=None,
                target_roi=None,
                recognized=state != "UNKNOWN",
                evidence_refs=(str(captured.path),),
            )

    def reconcile(_intent, observed):
        return bool(
            successors
            and successors[-1][1] in allowed_successors
            and observed.frame_sha256 == successors[-1][0].sha256
        )

    execution = SafeActionExecutor(
        store,
        policy,
        session.owner,
        lambda: float(context.monotonic_clock()),
        transport,
        lambda: proposal,
        post_observe,
        reconcile,
        wall_clock=lambda: float(context.utc_clock()),
        max_pre_dispatch_attempts=1,
    ).execute(request, issued.capability)
    return bool(
        execution.status is ActionStatus.CONFIRMED
        and execution.transport_calls == 1
        and successors
        and successors[-1][1] in allowed_successors
    )


def _navigation_tap(
    context,
    *,
    label: str,
    target_identity: str,
    source_state: str,
    expected_postcondition: str,
    bind: Callable[[Any], tuple[int, int, int, int] | None],
    source_recognize: Callable[[Any], bool],
    recognize: Callable[[Any], str | None],
    allowed_successors: tuple[str, ...],
) -> bool:
    return _navigation_action(
        context,
        label=label,
        target_identity=target_identity,
        source_state=source_state,
        expected_postcondition=expected_postcondition,
        control_class="GO",
        bind=bind,
        source_recognize=source_recognize,
        recognize=recognize,
        allowed_successors=allowed_successors,
        dispatch=lambda before, action_key, roi: context.runtime.tap(
            before,
            target_identity=target_identity,
            target_roi=roi,
            action_key=action_key,
            action_class="navigation",
            consequential=False,
        ),
    )


def _navigate_to_panel(context, *, occurrence_key: str, current) -> tuple[Any | None, _PanelRead | None, str]:
    initial = current
    panel = _panel_observation(current, context=context, occurrence_key=occurrence_key)
    if panel.observation is not None:
        return current, panel, "panel"
    if _is_nanoweapon_page(current.frame):
        return current, None, "nanoweapon"
    if _is_gear_factory_menu(current.frame):
        kind = "gear_factory"
    elif context.is_clean_home(current.frame):
        try:
            atlas = _load_atlas(DEFAULT_ATLAS)
            localizer = BlueStacksHomeLocalizer(atlas, DEFAULT_ATLAS)
        except Exception:
            return current, None, "home_atlas_unavailable"
        current, binding, binding_error = bind_or_pan_mapped_home_building(
            context, current=current, atlas=atlas, localizer=localizer,
            building_id=GEAR_FACTORY_ID, product_id=PRODUCT_ID,
            binding_for_frame=lambda frame: _home_binding(frame, atlas, localizer),
        )
        if binding is None:
            return current, None, binding_error or "gear_factory_atlas_navigation_blocked"
        if not _navigation_tap(
            context,
            label=f"nano-material-open-gear-factory-{context.session.invocation_id}",
            target_identity=GEAR_FACTORY_ID,
            source_state="HOME_BASE",
            expected_postcondition="GEAR_FACTORY_MENU_OR_NANOWEAPON",
            bind=lambda frame: (lambda value: tuple(value.target_roi) if value is not None and value.building_id == GEAR_FACTORY_ID and value.frame_sha256 == frame_digest(frame) and _safe_nav_roi(value.target_roi) else None)(_home_binding(frame, atlas, localizer)),
            source_recognize=lambda frame: bool(
                context.is_clean_home(frame)
                and (localization := localizer.localize(frame)).recognized
                and not localization.stale
                and not localization.overlay
            ),
            recognize=lambda after: "NANOWEAPON" if _is_nanoweapon_page(after.frame) else "GEAR_FACTORY" if _is_gear_factory_menu(after.frame) else None,
            allowed_successors=("GEAR_FACTORY", "NANOWEAPON"),
        ):
            return None, None, "gear_factory_atlas_navigation_not_verified"
        current = _capture(context, "nano-material-gear-factory-menu")
        if _is_nanoweapon_page(current.frame):
            return current, None, "nanoweapon"
        if not _is_gear_factory_menu(current.frame):
            return None, None, "gear_factory_successor_unknown"
        kind = "gear_factory"
    else:
        return None, None, panel.reason

    if kind == "gear_factory":
        roi = _line_target(current.frame, "Nanoweapon")
        if not _safe_nav_roi(roi):
            return None, None, "nanoweapon_factory_control_unknown"
        if not _navigation_tap(
            context,
            label=f"nano-material-open-nanoweapon-{context.session.invocation_id}",
            target_identity="gear-factory:nanoweapon",
            source_state="GEAR_FACTORY",
            expected_postcondition="NANOWEAPON_PAGE",
            bind=lambda frame: _line_target(frame, "Nanoweapon") if _is_gear_factory_menu(frame) else None,
            source_recognize=_is_gear_factory_menu,
            recognize=lambda after: "NANOWEAPON" if _is_nanoweapon_page(after.frame) else None,
            allowed_successors=("NANOWEAPON",),
        ):
            return None, None, "nanoweapon_successor_not_verified"
        current = _capture(context, "nano-material-nanoweapon-screen")
        if not _is_nanoweapon_page(current.frame):
            return None, None, "nanoweapon_screen_unknown"
        return current, None, "nanoweapon"
    return current if current is not initial else None, None, "nanoweapon"


def _select_material_tab(context, *, occurrence_key: str, captured) -> tuple[Any | None, _PanelRead | None]:
    panel = _panel_observation(captured, context=context, occurrence_key=occurrence_key)
    if panel.observation is not None:
        return captured, panel
    frame = captured.frame
    lines = _lines(_ocr_words(frame))
    if not _is_nanoweapon_page(frame):
        return None, None
    roi = _word_roi(_phrase_lines(lines, "Material Production")[0][1]) if len(_phrase_lines(lines, "Material Production")) == 1 else None
    if not _safe_nav_roi(roi):
        return None, None
    if not _navigation_tap(
        context,
        label=f"nano-material-select-tab-{context.session.invocation_id}",
        target_identity="nanoweapon:material-production-tab",
        source_state="NANOWEAPON",
        expected_postcondition="MATERIAL_PRODUCTION_PANEL",
        bind=lambda frame: _line_target(frame, "Material Production"),
        source_recognize=_is_nanoweapon_page,
        recognize=lambda after: "MATERIAL_PRODUCTION" if _panel_observation(after, context=context, occurrence_key=occurrence_key).observation is not None else None,
        allowed_successors=("MATERIAL_PRODUCTION",),
    ):
        return None, None
    current = _capture(context, "nano-material-production-panel")
    result = _panel_observation(current, context=context, occurrence_key=occurrence_key)
    return (current, result) if result.observation is not None else (None, result)


def _return_home(context, *, occurrence_key: str, current) -> tuple[bool, Any | None]:
    runtime, session = context.runtime, context.session
    try:
        atlas = _load_atlas(DEFAULT_ATLAS)
        localizer = BlueStacksHomeLocalizer(atlas, DEFAULT_ATLAS)
    except Exception:
        return False, None

    def recognized_home(captured) -> bool:
        if not context.is_clean_home(captured.frame):
            return False
        localization = localizer.localize(captured.frame)
        return bool(localization.recognized and not localization.stale and not localization.overlay)

    frame = current
    for ordinal in range(3):
        if recognized_home(frame):
            return True, frame
        if context.is_clean_home(frame.frame):
            normalized = _normalize_home_source(context, frame)
            return (True, normalized) if normalized is not None and recognized_home(normalized) else (False, None)
        panel = _panel_observation(frame, context=context, occurrence_key=occurrence_key)
        if panel.observation is not None:
            def source_recognize(before):
                return _panel_observation(
                    before, context=context, occurrence_key=occurrence_key,
                ).observation is not None
        elif _is_nanoweapon_page(frame.frame):
            def source_recognize(before):
                return _is_nanoweapon_page(before.frame)
        elif _is_gear_factory_menu(frame.frame):
            def source_recognize(before):
                return _is_gear_factory_menu(before.frame)
        else:
            return False, None

        def authorize(before):
            if not source_recognize(before):
                raise RuntimeError("Nano Material Production return source is not positively recognized")

        def dispatch(before):
            context.checkpoint()
            context.validate_identity()
            runtime.press_key(
                before,
                key="Escape",
                action_key=f"{PRODUCT_ID}|{occurrence_key}|return-home:{session.invocation_id}:{ordinal}",
            )

        def recognize(after):
            if recognized_home(after):
                return "HOME_BASE"
            if context.is_clean_home(after.frame):
                return "HOME_BASE_PENDING_ATLAS"
            if _is_nanoweapon_page(after.frame):
                return "NANOWEAPON"
            if _is_gear_factory_menu(after.frame):
                return "GEAR_FACTORY"
            return "unknown"

        def settled():
            time.sleep(float(context.settle_seconds))
            context.checkpoint()
            context.validate_identity()
            return runtime.capture(f"nano-material-return-home-{ordinal}-settled")

        try:
            result = session.run_action(
                action_class="navigation",
                label=f"nano-material-return-home-{session.invocation_id}-{ordinal}",
                capture=runtime.capture,
                authorize=authorize,
                dispatch=dispatch,
                recognize=recognize,
                consequence_class="navigation_only",
                settled_successor=settled,
            )
        except Exception:
            return False, None
        if result.status != "completed" or result.state not in {"HOME_BASE", "HOME_BASE_PENDING_ATLAS", "NANOWEAPON", "GEAR_FACTORY"}:
            return False, None
        frame = _capture(context, f"nano-material-return-home-current-{ordinal}")
    if context.is_clean_home(frame.frame) and not recognized_home(frame):
        frame = _normalize_home_source(context, frame)
        if frame is None:
            return False, None
    return (True, frame) if recognized_home(frame) else (False, None)


def _accounting(context) -> dict[str, object]:
    accounting = context.accounting()
    session_count = getattr(context.session, "input_count", None)
    runtime_count = getattr(context.runtime, "input_count", None)
    valid = bool(
        getattr(accounting, "verified", False)
        and type(session_count) is int and type(runtime_count) is int
        and session_count == runtime_count == getattr(accounting, "input_count", None)
    )
    return {
        "accounting_verified": valid,
        "input_count": int(session_count) if type(session_count) is int else 0,
        "session_input_count": int(session_count) if type(session_count) is int else 0,
        "runtime_input_count": int(runtime_count) if type(runtime_count) is int else 0,
    }


def _home_proof(context, captured) -> dict[str, object]:
    frame, reference = context.capture_reference(captured.path, captured.sha256)
    if not context.is_clean_home(frame):
        raise ValueError("terminal frame is not positively recognized canonical Home")
    return {
        "terminal_home_state": "HOME_BASE",
        "terminal_home_recognized": True,
        "terminal_home_frame": {
            "frame_path": reference.frame_path,
            "frame_sha256": reference.frame_sha256,
            "observed_utc": reference.observed_utc,
            "capture_ordinal": reference.capture_ordinal,
        },
        "terminal_home_frame_path": str(captured.path),
        "terminal_home_frame_sha256": str(captured.sha256),
        "terminal_home_verified": True,
    }

def _retained_capture_reference(context, captured) -> dict[str, object] | None:
    if captured is None:
        return None
    try:
        _frame, reference = context.capture_reference(captured.path, captured.sha256)
    except Exception:
        return None
    frame_path = getattr(reference, "frame_path", None)
    frame_sha256 = getattr(reference, "frame_sha256", None)
    observed_utc = getattr(reference, "observed_utc", None)
    capture_ordinal = getattr(reference, "capture_ordinal", None)
    if (
        type(frame_path) is not str
        or not frame_path
        or frame_sha256 != captured.sha256
        or re.fullmatch(r"[0-9a-f]{64}", str(frame_sha256 or "")) is None
        or type(observed_utc) is not str
        or not observed_utc
        or type(capture_ordinal) is not int
        or capture_ordinal <= 0
    ):
        return None
    return {
        "frame_path": frame_path,
        "frame_sha256": frame_sha256,
        "observed_utc": observed_utc,
        "capture_ordinal": capture_ordinal,
    }

def _retained_panel_proof(context, captured, occurrence_key: str) -> tuple[MaterialProductionObservation, dict[str, object]]:
    frame, reference = context.capture_reference(captured.path, captured.sha256)
    if reference.frame_sha256 != captured.sha256:
        raise ValueError("retained production frame digest differs from the current capture")
    replay = _panel_observation(
        _CaptureView(frame, reference.frame_sha256, Path(captured.path)),
        context=context,
        occurrence_key=occurrence_key,
    ).observation
    if (
        replay is None
        or not material_production_authorizeable(replay)
        or replay.production_state != "active"
        or replay.active_production_count != 1
        or replay.completed_batch_count != 0
    ):
        raise ValueError("retained production frame does not prove one exact active slot")
    return replay, {
        "frame_path": reference.frame_path,
        "frame_sha256": reference.frame_sha256,
        "observed_utc": reference.observed_utc,
        "capture_ordinal": reference.capture_ordinal,
    }



def _base_result(context, occurrence_key: str) -> dict[str, object]:
    return {
        "flow_id": FLOW_ID,
        "product_id": PRODUCT_ID,
        "product_revision": PRODUCT_REVISION,
        "native_occurrence_key": occurrence_key,
        "occurrence_key": occurrence_key,
        "production_transport_calls": 0,
        "attempted_action_count": 0,
        "attempted_action_count_known": True,
        "action_evidence_required": False,
        "committed_action_count": 0,
        "effect_reconciliation_required": False,
        "identical_retry_denied": False,
        "accounting_verified": False,
        "terminal_home_verified": False,
        "zero_resource_cost_confirmed": False,
    }


def _recognized_home(context, frame: np.ndarray, atlas_path: Path = DEFAULT_ATLAS) -> bool:
    if not context.is_clean_home(frame):
        return False
    try:
        atlas = _load_atlas(atlas_path)
        localization = BlueStacksHomeLocalizer(atlas, atlas_path).localize(frame)
    except Exception:
        return False
    return bool(localization.recognized and not localization.stale and not localization.overlay)


def _normalize_home_source(context, current):
    """Use the shared simultaneous-pointer recovery, never sequential zoom input."""
    if _recognized_home(context, current.frame):
        return current
    if not context.is_clean_home(current.frame):
        return None
    context.checkpoint()
    context.validate_identity()
    try:
        atlas = _load_atlas(DEFAULT_ATLAS)
        # Each physical zoom is a session-owned run_action input, so route inputs
        # before or after normalization keep one exact session/runtime count.
        normalize_runtime_home_atlas_startup(
            runtime=context.runtime, atlas=atlas, atlas_path=DEFAULT_ATLAS,
            execute=context.runtime.execute, settle_seconds=float(context.settle_seconds),
            maximum_zoom_inputs=2, session=context.session,
        )
    except Exception:
        return None
    normalized = _capture(context, "nano-material-production-atlas-ready")
    return normalized if _recognized_home(context, normalized.frame) else None


def _prepare_route_source(context, current, occurrence_key: str):
    if context.is_clean_home(current.frame):
        if getattr(context.session, "initial_observation", None) is None:
            context.bind_initial_observation(current)
        return _normalize_home_source(context, current)
    if getattr(context.session, "initial_observation", None) is not None:
        return current
    panel = _panel_observation(current, context=context, occurrence_key=occurrence_key)
    if (
        panel.observation is not None
        or _is_nanoweapon_page(current.frame)
        or _is_gear_factory_menu(current.frame)
        or _recognized_home(context, current.frame)
    ):
        context.bind_initial_observation(current)
        return current
    try:
        atlas = _load_atlas(DEFAULT_ATLAS)
        localizer = BlueStacksHomeLocalizer(atlas, DEFAULT_ATLAS)
        context.prepare_startup(
            source_context="nano_material_production_home",
            recognize_successor=lambda frame: bool(
                context.is_clean_home(frame)
                and (localization := localizer.localize(frame)).recognized
                and not localization.stale
                and not localization.overlay
            ),
            action_key=f"{PRODUCT_ID}|{occurrence_key}|startup",
        )
    except Exception:
        return None
    recovered = _capture(context, "nano-material-production-startup-home")
    return _normalize_home_source(context, recovered) if context.is_clean_home(recovered.frame) else None




def _finalize(context, result: dict[str, object], *, current, return_home: bool, occurrence_key: str, status: str, reason: str) -> dict[str, object]:
    result.update(status=status, reason=reason)
    if return_home:
        home_ok, home_capture = _return_home(context, occurrence_key=occurrence_key, current=current) if current is not None else (False, None)
        if home_ok and home_capture is not None:
            try:
                result.update(_home_proof(context, home_capture))
            except Exception as exc:
                result.update(terminal_home_verified=False, terminal_home_error=f"{type(exc).__name__}:{exc}")
        else:
            result["terminal_home_verified"] = False
            if status in {"completed", "deferred"}:
                result.update(status="unresolved", reason="canonical_home_successor_not_verified")
                if int(result.get("production_transport_calls", 0)):
                    result.update(effect_reconciliation_required=True, identical_retry_denied=True)
    calls = result.get("production_transport_calls")
    attempted_known = type(calls) is int and calls >= 0
    result.update(
        attempted_action_count=calls if attempted_known else None,
        attempted_action_count_known=attempted_known,
    )
    result.update(_accounting(context))
    if not result["accounting_verified"]:
        result.update(status="unresolved" if int(result.get("production_transport_calls", 0)) else "blocked", reason="native_input_accounting_mismatch")
        if int(result.get("production_transport_calls", 0)):
            result.update(effect_reconciliation_required=True, identical_retry_denied=True)
    return result


def run_material_production_in_context(context, *, occurrence_key: str, return_home: bool) -> Mapping[str, object]:
    """Maintain Nano production inside an already-owned native context."""
    if type(occurrence_key) is not str or not occurrence_key:
        raise ValueError("Nano Material Production occurrence key must be a nonempty exact string")
    if occurrence_key != getattr(context, "occurrence_key", None):
        raise ValueError("Nano Material Production occurrence key differs from its borrowed native context")
    if type(return_home) is not bool:
        raise TypeError("return_home must be an exact bool")
    if getattr(context, "runtime_profile_id", None) != ACTIVE_RUNTIME_PROFILE_ID:
        raise ValueError("Nano Material Production requires the active native profile")
    context.checkpoint()
    context.validate_identity()
    result = _base_result(context, occurrence_key)
    current = _capture(context, "nano-material-production-entry")
    current = _prepare_route_source(context, current, occurrence_key)
    if current is None:
        return _finalize(context, result, current=None, return_home=return_home, occurrence_key=occurrence_key, status="blocked", reason="NANO_MATERIAL_PRODUCTION_STARTUP_HOME_UNKNOWN")
    panel_read = _panel_observation(current, context=context, occurrence_key=occurrence_key)
    if panel_read.observation is None:
        current, _screen, page_kind = _navigate_to_panel(context, occurrence_key=occurrence_key, current=current)
        if current is None:
            # Navigation helpers discard their source on refusal; prove the actual terminal screen afresh.
            terminal_source = _capture(context, "nano-material-production-navigation-blocked-source")
            return _finalize(context, result, current=terminal_source, return_home=return_home, occurrence_key=occurrence_key, status="blocked", reason=f"NANO_MATERIAL_PRODUCTION_{page_kind.upper()}")
        before_tab_selection = current
        current, panel_read = _select_material_tab(context, occurrence_key=occurrence_key, captured=current)
        if current is None and context.is_clean_home(before_tab_selection.frame):
            current = before_tab_selection
        if current is None or panel_read is None or panel_read.observation is None:
            return _finalize(context, result, current=current, return_home=return_home, occurrence_key=occurrence_key, status="blocked", reason="NANO_MATERIAL_PRODUCTION_PANEL_NOT_POSITIVELY_RECOGNIZED")
    before = panel_read.observation
    if not material_production_authorizeable(before):
        return _finalize(context, result, current=current, return_home=return_home, occurrence_key=occurrence_key, status="blocked", reason="MATERIAL_PRODUCTION_STATE_NOT_POSITIVELY_RECOGNIZED")

    status = "deferred"
    reason = "MATERIAL_PRODUCTION_ACTIVE_DUE_REFRESH_ONLY"
    if before.production_state == "complete":
        claim = _dispatch_action(
            context,
            before_capture=current,
            before=before,
            occurrence_key=occurrence_key,
            action_kind="CLAIM_NANO_MATERIAL_PRODUCTION",
        )
        calls = int(claim.get("transport_calls", 0))
        claim_confirmed = bool(
            claim.get("status") == "confirmed"
            and claim.get("successor_observation") is not None
            and calls == 1
        )
        result["production_transport_calls"] = calls
        result["committed_action_count"] = int(claim_confirmed)
        if not claim_confirmed:
            evidence = claim.get("last_action_evidence")
            result.update(
                last_action_evidence=evidence,
                action_evidence_required=bool(
                    calls and (
                        not isinstance(evidence, Mapping)
                        or evidence.get("before") is None
                        or evidence.get("after") is None
                    )
                ),
                effect_reconciliation_required=bool(calls),
                identical_retry_denied=bool(calls),
                status="unresolved" if calls else "blocked",
                reason=str(claim.get("reason") or "MATERIAL_PRODUCTION_CLAIM_SUCCESSOR_UNKNOWN"),
            )
            return _finalize(
                context,
                result,
                current=current,
                return_home=return_home,
                occurrence_key=occurrence_key,
                status=str(result["status"]),
                reason=str(result["reason"]),
            )
        current = claim["successor_capture"]
        before = claim["successor_observation"]
        if before.production_state != "idle":
            result.update(
                status="unresolved",
                reason="MATERIAL_PRODUCTION_CLAIM_SUCCESSOR_NOT_IDLE",
                effect_reconciliation_required=True,
                identical_retry_denied=True,
            )
            return _finalize(
                context,
                result,
                current=current,
                return_home=return_home,
                occurrence_key=occurrence_key,
                status="unresolved",
                reason=str(result["reason"]),
            )
        status = "completed"
        reason = "MATERIAL_PRODUCTION_CLAIMED_THEN_RESTARTED"
    if before.production_state == "idle":
        start = _dispatch_action(
            context,
            before_capture=current,
            before=before,
            occurrence_key=occurrence_key,
            action_kind="START_NANO_MATERIAL_PRODUCTION",
        )
        calls = int(start.get("transport_calls", 0))
        start_confirmed = bool(
            start.get("status") == "confirmed"
            and start.get("successor_observation") is not None
            and calls == 1
        )
        result["production_transport_calls"] = int(result["production_transport_calls"]) + calls
        result["committed_action_count"] = int(result["committed_action_count"]) + int(start_confirmed)
        if not start_confirmed:
            sent = int(result["production_transport_calls"])
            evidence = start.get("last_action_evidence")
            result.update(
                last_action_evidence=evidence,
                action_evidence_required=bool(
                    calls and (
                        not isinstance(evidence, Mapping)
                        or evidence.get("before") is None
                        or evidence.get("after") is None
                    )
                ),
                status="unresolved" if sent else "blocked",
                reason=str(start.get("reason") or "MATERIAL_PRODUCTION_START_SUCCESSOR_UNKNOWN"),
                effect_reconciliation_required=bool(sent),
                identical_retry_denied=bool(sent),
            )
            return _finalize(
                context,
                result,
                current=current,
                return_home=return_home,
                occurrence_key=occurrence_key,
                status=str(result["status"]),
                reason=str(result["reason"]),
            )
        current = start["successor_capture"]
        before = start["successor_observation"]
        status = "completed"
        reason = "MATERIAL_PRODUCTION_ACTIVE_21600_CONFIRMED"
    if before.production_state != "active" or not material_production_authorizeable(before):
        result.update(status="blocked", reason="MATERIAL_PRODUCTION_FINAL_ACTIVE_STATE_UNKNOWN")
        return _finalize(context, result, current=current, return_home=return_home, occurrence_key=occurrence_key, status="blocked", reason=str(result["reason"]))
    try:
        before, state_frame = _retained_panel_proof(context, current, occurrence_key)
    except Exception as exc:
        sent = int(result["production_transport_calls"])
        result.update(
            status="unresolved" if sent else "blocked",
            reason=f"retained_production_state_not_proven:{type(exc).__name__}",
            effect_reconciliation_required=bool(sent),
            identical_retry_denied=bool(sent),
        )
        return _finalize(context, result, current=current, return_home=return_home, occurrence_key=occurrence_key, status=str(result["status"]), reason=str(result["reason"]))
    now = float(context.utc_clock())
    next_due = material_production_due_at(now, before.timer_seconds_remaining)
    result.update(
        status=status,
        reason=reason,
        production_state="active",
        active_production_count=1,
        completed_batch_count=0,
        production_duration_seconds=NANO_MATERIAL_PRODUCTION_DURATION_SECONDS,
        timer_seconds_remaining=before.timer_seconds_remaining,
        next_eligible_at=next_due,
        zero_resource_cost_confirmed=True,
        effect_reconciliation_required=False,
        identical_retry_denied=False,
        production_occurrence_key=occurrence_key,
        production_target_identity=NANO_MATERIAL_PRODUCTION_TARGET,
        production_state_frame=state_frame,
        production_state_observation_sha256=before.source_frame_sha256,
        production_evidence_refs=tuple(before.evidence_refs),
    )
    return _finalize(context, result, current=current, return_home=return_home, occurrence_key=occurrence_key, status=status, reason=reason)


def run_nano_material_production_native(context, arguments: Mapping[str, object]) -> Mapping[str, object]:
    if context.flow_id != FLOW_ID or context.product_id != PRODUCT_ID or context.product_revision != PRODUCT_REVISION:
        raise ValueError("Nano Material Production native context binding mismatch")
    if not isinstance(arguments, Mapping):
        raise ValueError("Nano Material Production arguments must be a mapping")
    return run_material_production_in_context(
        context,
        occurrence_key=context.occurrence_key,
        return_home=True,
    )




def create_service_binding(make_native_route_binding):
    """Bind the fixed route to the canonical native owner and store."""
    return make_native_route_binding(
        flow_id=FLOW_ID,
        product_id=PRODUCT_ID,
        product_revision=PRODUCT_REVISION,
        runtime_profile_id=PROFILE_ID,
        owner="automation-service:nano-material-production",
        workflow="nano-material-production-maintenance",
        max_inputs=MAX_INPUTS,
        max_actions=MAX_ACTIONS,
        driver=run_nano_material_production_native,
        action_store_factory=lambda path: SafetyStore(path),
    )
