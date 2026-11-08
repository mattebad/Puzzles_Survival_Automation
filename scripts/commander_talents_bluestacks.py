"""Bounded native helper for verifying saved Commander Talent Memory presets.

This module is called only from an already-owned DevelopmentSession. It is not
an operator flow and does not edit Commander talent trees or saved memories.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from tasks.commander_talents import (
    PRESET_NAMES,
    PresetRowState,
    TalentMemoryObservation,
    TalentPresetNativeResult as NativePresetResult,
    TalentSwitchPermit as NativeSwitchPermit,
    context_fingerprint,
    observe_preset,
    recognize_talent_memory,
)
from scripts.bluestacks_native_runtime import CapturedNativeFrame, NativeBox
from scripts.enhancement_bluestacks import (
    NATIVE_HEIGHT,
    NATIVE_WIDTH,
    _default_ocr,
    _hits,
    _normalize,
    recognize_home_frame,
)


MAX_NAVIGATION_INPUTS = 3
HOME = "home"
PROFILE = "commander_info"
COMMANDER_TALENT = "commander_talent"
TALENT_MEMORY = "talent_memory"
UNKNOWN = "unknown"
FULL_FRAME: NativeBox = (0, 0, NATIVE_WIDTH, NATIVE_HEIGHT)


@dataclass(frozen=True)
class TalentPageObservation:
    page: str
    recognized: bool
    target: NativeBox | None
    preset: TalentMemoryObservation | None
    evidence_ref: str
    frame_sha256: str
    reason: str




def _evidence(frame: CapturedNativeFrame) -> str:
    return str(getattr(frame, "path", "") or f"sha256:{frame.sha256}")


def _all_hits(frame: CapturedNativeFrame, ocr_engine: Callable | None) -> tuple[Any, ...]:
    engine = ocr_engine or _default_ocr
    return tuple(_hits(frame.frame, FULL_FRAME, engine))


def _hit_box(hit: Any) -> NativeBox | None:
    value = getattr(hit, "bounds", None)
    if type(value) not in (tuple, list) or len(value) != 4:
        return None
    try:
        x0, y0, x1, y1 = (int(part) for part in value)
    except (TypeError, ValueError):
        return None
    if not (0 <= x0 < x1 <= NATIVE_WIDTH and 0 <= y0 < y1 <= NATIVE_HEIGHT):
        return None
    return (x0, y0, x1, y1)


def _label_hits(hits: Sequence[Any], label: str) -> list[Any]:
    expected = _normalize(label)
    return [hit for hit in hits if _normalize(getattr(hit, "text", "")) == expected and _hit_box(hit) is not None]


def _recognized_page(
    frame: CapturedNativeFrame,
    *,
    required_preset: str,
    ocr_engine: Callable | None,
) -> TalentPageObservation:
    evidence_ref = _evidence(frame)
    digest = str(frame.sha256)
    hits = _all_hits(frame, ocr_engine)
    normalized = {_normalize(getattr(hit, "text", "")) for hit in hits}

    home = recognize_home_frame(
        frame.frame,
        source_frame_sha256=digest,
        ocr_engine=ocr_engine,
    )
    if home.recognized and home.portrait_target is not None:
        return TalentPageObservation(HOME, True, home.portrait_target, None, evidence_ref, digest,
                                     "CANONICAL_HOME_AND_PROFILE_PORTRAIT_RECOGNIZED")

    if ("commander info" in normalized or "commanderinfo" in normalized) and (
        len(normalized & {"gear", "chip", "module", "cube", "bioenhancer"}) >= 4
        and len(normalized & {"talent", "commander", "boosts", "alliance", "achievement"}) >= 4
    ):
        talent_hits = [hit for hit in _label_hits(hits, "Talent") if _hit_box(hit)[1] >= 1000]
        if len(talent_hits) == 1:
            return TalentPageObservation(PROFILE, True, _hit_box(talent_hits[0]), None, evidence_ref, digest,
                                         "COMMANDER_INFO_AND_PROFILE_TALENT_ENTRY_RECOGNIZED")
        return TalentPageObservation(UNKNOWN, False, None, None, evidence_ref, digest,
                                     "PROFILE_TALENT_ENTRY_NOT_UNIQUE")

    if "cmdr talent" in normalized and "talent memory" in normalized:
        if {"economy", "military", "balance"}.issubset(normalized) and "reset" in normalized:
            memory_hits = _label_hits(hits, "Talent Memory")
            if len(memory_hits) == 1:
                return TalentPageObservation(COMMANDER_TALENT, True, _hit_box(memory_hits[0]), None,
                                             evidence_ref, digest, "COMMANDER_TALENT_MEMORY_ENTRY_RECOGNIZED")
        return TalentPageObservation(UNKNOWN, False, None, None, evidence_ref, digest,
                                     "COMMANDER_TALENT_PAGE_INCOMPLETE")

    if "talent memory" in normalized:
        recognition = recognize_talent_memory(hits)
        if recognition.recognized:
            preset = observe_preset(
                recognition,
                required_preset,
                source_frame_sha256=digest,
                evidence_ref=evidence_ref,
            )
            return TalentPageObservation(TALENT_MEMORY, True, preset.apply_target, preset,
                                         evidence_ref, digest, preset.reason)
        return TalentPageObservation(UNKNOWN, False, None, None, evidence_ref, digest,
                                     recognition.reason)

    return TalentPageObservation(UNKNOWN, False, None, None, evidence_ref, digest,
                                 "COMMANDER_TALENT_CONTEXT_NOT_RECOGNIZED")


def recognize_commander_talent_page(
    frame: CapturedNativeFrame,
    *,
    required_preset: str,
    ocr_engine: Callable | None = None,
) -> TalentPageObservation:
    """Read-only recognition of the current Home/Profile/Talent Memory page."""

    return _recognized_page(frame, required_preset=required_preset, ocr_engine=ocr_engine)


def _dispatch_marker(callback: Callable[[CapturedNativeFrame], None]):
    class SessionDispatch:
        def _authorize_dispatch(self) -> None:
            return None

        def dispatch(self, frame: CapturedNativeFrame) -> None:
            callback(frame)

    return SessionDispatch()


def _validate_boundary(
    session: Any,
    runtime: Any,
    *,
    checkpoint: Callable[[], None],
    runtime_input_lock: Any,
) -> tuple[str, str]:
    if not callable(checkpoint) or not callable(getattr(session, "observe", None)) or not callable(getattr(session, "run_action", None)):
        raise RuntimeError("commander talent helper requires an active DevelopmentSession and checkpoint")
    if getattr(session, "is_active", False) is not True:
        raise RuntimeError("commander talent helper requires the active owned DevelopmentSession")
    if getattr(session, "runtime_input_lock", None) is not runtime_input_lock:
        raise RuntimeError("commander talent helper requires the session's exact held runtime input lock")
    if not callable(getattr(runtime, "capture", None)) or not callable(getattr(runtime, "tap", None)):
        raise RuntimeError("commander talent helper requires the route's native runtime")
    owner = getattr(runtime_input_lock, "owner", None)
    invocation_id = getattr(runtime_input_lock, "invocation_id", None)
    if type(owner) is not str or not owner or type(invocation_id) is not str or not invocation_id:
        raise RuntimeError("commander talent helper runtime owner identity is missing")
    runtime_input_lock.assert_held(owner, invocation_id)
    checkpoint()
    runtime_input_lock.assert_held(owner, invocation_id)
    return owner, invocation_id


def _run_navigation_action(
    session: Any,
    runtime: Any,
    *,
    source_generation: str | int,
    label: str,
    source_page: str,
    destination_page: str,
    target_identity: str,
    target_getter: Callable[[TalentPageObservation], NativeBox | None],
    required_preset: str,
    ocr_engine: Callable | None,
    checkpoint: Callable[[], None],
    runtime_input_lock: Any,
) -> tuple[bool, TalentPageObservation | None, str]:
    target_state: dict[str, NativeBox] = {}
    transport_returned = False

    def capture(capture_label: str) -> CapturedNativeFrame:
        checkpoint()
        runtime_input_lock.assert_held(runtime_input_lock.owner, runtime_input_lock.invocation_id)
        return runtime.capture(capture_label)

    def authorize(frame: CapturedNativeFrame) -> None:
        current = _recognized_page(frame, required_preset=required_preset, ocr_engine=ocr_engine)
        if not current.recognized or current.page != source_page:
            raise RuntimeError("TALENT_NAVIGATION_SOURCE_CHANGED:" + current.reason)
        target = target_getter(current)
        if target is None:
            raise RuntimeError("TALENT_NAVIGATION_TARGET_UNBOUND")
        target_state["target"] = target

    def dispatch(frame: CapturedNativeFrame) -> None:
        nonlocal transport_returned
        current = _recognized_page(frame, required_preset=required_preset, ocr_engine=ocr_engine)
        if not current.recognized or current.page != source_page or current.frame_sha256 != frame.sha256:
            raise RuntimeError("TALENT_NAVIGATION_DISPATCH_FRAME_MISMATCH")
        target = target_state.get("target")
        if target is None:
            raise RuntimeError("TALENT_NAVIGATION_TARGET_NOT_AUTHORIZED")
        action_key = f"commander-talent:{source_generation}:{label}:{frame.sha256}"
        runtime.tap(
            frame,
            target_identity=target_identity,
            target_roi=target,
            action_key=action_key,
            action_class="navigation",
            consequential=False,
        )
        transport_returned = True

    def recognize(frame: CapturedNativeFrame) -> str:
        current = _recognized_page(frame, required_preset=required_preset, ocr_engine=ocr_engine)
        return current.page if current.recognized else UNKNOWN

    session_result = session.run_action(
        action_class="navigation",
        label=label,
        capture=capture,
        dispatch=_dispatch_marker(dispatch).dispatch,
        recognize=recognize,
        authorize=authorize,
        target_roi=None,
    )
    current = _recognized_page(session_result_frame(session, runtime, label),
                               required_preset=required_preset, ocr_engine=ocr_engine)
    success = bool(
        transport_returned
        and getattr(session_result, "status", "") == "completed"
        and getattr(session_result, "state", "") == destination_page
        and current.recognized
        and current.page == destination_page
    )
    return success, current, "NAVIGATION_VERIFIED" if success else "NAVIGATION_SUCCESSOR_UNKNOWN"


def session_result_frame(session: Any, runtime: Any, label: str) -> CapturedNativeFrame:
    return session.observe(runtime.capture, label=f"commander-talent-{label}-settled")


def run_commander_talent_preset(
    session: Any,
    runtime: Any,
    required_preset: str,
    *,
    checkpoint: Callable[[], None],
    runtime_input_lock: Any,
    action_store: Any,
    source_generation: str | int,
    context: Any,
    ocr_engine: Callable | None = None,
    switch_approval: Callable[[TalentMemoryObservation, CapturedNativeFrame], NativeSwitchPermit | None] | None = None,
    switch_outcome: Callable[[str, str, bool, TalentMemoryObservation | None], None] | None = None,
) -> NativePresetResult:
    """Verify a saved memory, or dispatch one explicitly approved switch.

    Missing cost/cooldown/confirmation facts or missing canonical approval are
    a zero-input defer. The source evidence has no approved switch branch today.
    """

    if required_preset not in PRESET_NAMES:
        raise ValueError("required preset must be Military, Economy, or Training")
    if (
        type(source_generation) not in (str, int)
        or type(source_generation) is str and not source_generation.strip()
        or type(source_generation) is int and source_generation < 0
    ):
        raise ValueError("source generation must be a non-empty string or non-negative integer")
    context_fingerprint(context)
    owner, invocation_id = _validate_boundary(
        session, runtime, checkpoint=checkpoint, runtime_input_lock=runtime_input_lock,
    )
    # A borrowed service lock identifies the outer operator, not this native
    # session. Keep its ownership fence above; bind preset proof to the session.
    session_invocation_id = getattr(session, "invocation_id", None)
    if type(session_invocation_id) is not str or not session_invocation_id:
        raise RuntimeError("commander talent helper native session identity is missing")
    if source_generation != session_invocation_id:
        raise ValueError("source_generation must match the held native session invocation")
    start_count = int(getattr(session, "input_count", 0))

    if action_store is None or not callable(getattr(action_store, "has_action_block", None)):
        raise RuntimeError("commander talent helper requires the canonical action store")
    if action_store.has_action_block():
        return NativePresetResult("unknown", False, required_preset, "CANONICAL_ACTION_REQUIRES_INSPECTION", (),
                                  int(getattr(session, "input_count", 0)) - start_count)

    try:
        current = session.observe(runtime.capture, label="commander-talent-source")
        page = _recognized_page(current, required_preset=required_preset, ocr_engine=ocr_engine)
        refs = [page.evidence_ref]
        if not page.recognized:
            return NativePresetResult("unknown", False, required_preset, page.reason, tuple(refs),
                                      int(getattr(session, "input_count", 0)) - start_count)

        transitions = {
            HOME: (PROFILE, "commander-profile-portrait"),
            PROFILE: (COMMANDER_TALENT, "commander-profile-talent-entry"),
            COMMANDER_TALENT: (TALENT_MEMORY, "commander-talent-memory-entry"),
        }
        for _ in range(MAX_NAVIGATION_INPUTS):
            if page.page == TALENT_MEMORY:
                break
            transition = transitions.get(page.page)
            if transition is None:
                return NativePresetResult("unknown", False, required_preset, "UNSUPPORTED_TALENT_START_CONTEXT",
                                          tuple(refs), int(getattr(session, "input_count", 0)) - start_count)
            destination, label = transition
            success, settled, reason = _run_navigation_action(
                session, runtime,
                source_generation=source_generation,
                label=label,
                source_page=page.page,
                destination_page=destination,
                target_identity=f"commander-talent-navigation:{page.page}:{destination}",
                target_getter=lambda observed: observed.target,
                required_preset=required_preset,
                ocr_engine=ocr_engine,
                checkpoint=checkpoint,
                runtime_input_lock=runtime_input_lock,
            )
            if settled is not None:
                page = settled
                refs.append(settled.evidence_ref)
            if not success or settled is None:
                return NativePresetResult("unknown", False, required_preset, reason, tuple(refs),
                                          int(getattr(session, "input_count", 0)) - start_count)

        if page.page != TALENT_MEMORY or page.preset is None or not page.preset.recognized:
            return NativePresetResult("unknown", False, required_preset, "TALENT_MEMORY_NOT_VERIFIED",
                                      tuple(refs), int(getattr(session, "input_count", 0)) - start_count)
        observation = page.preset
        if observation.row_state is PresetRowState.APPLIED:
            return NativePresetResult("already_applied", True, required_preset, "EXACT_PRESET_ALREADY_APPLIED",
                                      tuple(dict.fromkeys((*refs, observation.evidence_ref))),
                                      int(getattr(session, "input_count", 0)) - start_count)

        if not observation.switch_facts_complete:
            return NativePresetResult("deferred", False, required_preset,
                                      "SWITCH_COST_CONFIRMATION_OR_COOLDOWN_UNKNOWN",
                                      tuple(dict.fromkeys((*refs, observation.evidence_ref))),
                                      int(getattr(session, "input_count", 0)) - start_count)
        if switch_approval is None:
            return NativePresetResult("deferred", False, required_preset, "SWITCH_NOT_APPROVED",
                                      tuple(dict.fromkeys((*refs, observation.evidence_ref))),
                                      int(getattr(session, "input_count", 0)) - start_count)

        pending: dict[str, Any] = {}
        dispatch_returned = False

        def switch_capture(label: str) -> CapturedNativeFrame:
            checkpoint()
            runtime_input_lock.assert_held(owner, invocation_id)
            return runtime.capture(label)

        def switch_authorize(frame: CapturedNativeFrame) -> None:
            found = _recognized_page(frame, required_preset=required_preset, ocr_engine=ocr_engine)
            if not found.recognized or found.page != TALENT_MEMORY or found.preset is None:
                raise RuntimeError("TALENT_SWITCH_SOURCE_UNKNOWN")
            fresh = found.preset
            if (fresh.row_state is not PresetRowState.APPLY or fresh.preset_name != required_preset
                    or not fresh.switch_facts_complete):
                raise RuntimeError("TALENT_SWITCH_FACTS_CHANGED")
            if (fresh.cost_text, fresh.cooldown_text, fresh.confirmation_text) != (
                observation.cost_text, observation.cooldown_text, observation.confirmation_text
            ):
                raise RuntimeError("TALENT_SWITCH_COST_OR_CONFIRMATION_CHANGED")
            if not callable(switch_outcome):
                raise RuntimeError("TALENT_SWITCH_SETTLEMENT_UNAVAILABLE")
            permit = switch_approval(fresh, frame)
            if not isinstance(permit, NativeSwitchPermit):
                raise RuntimeError("TALENT_SWITCH_NOT_APPROVED")
            pending["permit"] = permit
            pending["observation"] = fresh

        def switch_dispatch(frame: CapturedNativeFrame) -> None:
            nonlocal dispatch_returned
            found = _recognized_page(frame, required_preset=required_preset, ocr_engine=ocr_engine)
            fresh = found.preset
            permit = pending.get("permit")
            if (not found.recognized or found.page != TALENT_MEMORY or fresh is None
                    or fresh.row_state is not PresetRowState.APPLY
                    or fresh.source_frame_sha256 != frame.sha256
                    or not isinstance(permit, NativeSwitchPermit)):
                raise RuntimeError("TALENT_SWITCH_DISPATCH_BINDING_INVALID")
            runtime_input_lock.assert_held(owner, invocation_id)
            checkpoint()
            runtime.tap(
                frame,
                target_identity=f"talent-memory-row:{required_preset}:apply",
                target_roi=fresh.apply_target,
                action_key=permit.action_key,
                action_class="commander_talent_preset",
                consequential=True,
            )
            dispatch_returned = True

        def switch_recognize(frame: CapturedNativeFrame) -> str:
            found = _recognized_page(frame, required_preset=required_preset, ocr_engine=ocr_engine)
            if found.recognized and found.page == TALENT_MEMORY and found.preset is not None:
                if found.preset.row_state is PresetRowState.APPLIED:
                    return "applied"
                return "apply"
            return UNKNOWN

        try:
            switch_result = session.run_action(
                action_class="commander_talent_preset",
                label=f"commander-talent-switch-{required_preset.casefold()}",
                capture=switch_capture,
                dispatch=_dispatch_marker(switch_dispatch).dispatch,
                recognize=switch_recognize,
                authorize=switch_authorize,
                target_roi=None,
                consequence_class="commander_talent_preset_switch",
            )
        except Exception as exc:
            permit = pending.get("permit")
            reason = str(exc) or type(exc).__name__
            if isinstance(permit, NativeSwitchPermit):
                if switch_outcome is not None:
                    switch_outcome(permit.action_key, "unknown", dispatch_returned, pending.get("observation"))
                return NativePresetResult(
                    "unknown", False, required_preset, reason,
                    tuple(dict.fromkeys((*refs, observation.evidence_ref))),
                    int(getattr(session, "input_count", 0)) - start_count,
                    permit.action_key, True,
                )
            status = "deferred" if reason in {
                "TALENT_SWITCH_NOT_APPROVED",
                "TALENT_SWITCH_FACTS_CHANGED",
                "TALENT_SWITCH_COST_OR_CONFIRMATION_CHANGED",
                "TALENT_SWITCH_SETTLEMENT_UNAVAILABLE",
            } else "unknown"
            return NativePresetResult(
                status, False, required_preset, reason,
                tuple(dict.fromkeys((*refs, observation.evidence_ref))),
                int(getattr(session, "input_count", 0)) - start_count,
            )

        permit = pending.get("permit")
        if not isinstance(permit, NativeSwitchPermit):
            return NativePresetResult("deferred", False, required_preset, "SWITCH_NOT_APPROVED",
                                      tuple(dict.fromkeys((*refs, observation.evidence_ref))),
                                      int(getattr(session, "input_count", 0)) - start_count)
        switch_frame = session.observe(runtime.capture, label="commander-talent-switch-settled")
        refs.append(_evidence(switch_frame))
        successor = _recognized_page(switch_frame, required_preset=required_preset, ocr_engine=ocr_engine)
        switched = bool(
            dispatch_returned
            and getattr(switch_result, "status", "") == "completed"
            and getattr(switch_result, "state", "") == "applied"
            and successor.recognized
            and successor.page == TALENT_MEMORY
            and successor.preset is not None
            and successor.preset.row_state is PresetRowState.APPLIED
            and successor.preset.applied_preset == required_preset
        )
        status = "switched" if switched else "unknown"
        if switch_outcome is not None:
            switch_outcome(permit.action_key, status, dispatch_returned, successor.preset)
        return NativePresetResult(
            status,
            switched,
            required_preset,
            "EXACT_PRESET_APPLIED_SUCCESSOR_VERIFIED" if switched else "SWITCH_SUCCESSOR_UNKNOWN_NO_RETRY",
            tuple(dict.fromkeys((*refs, successor.evidence_ref))),
            int(getattr(session, "input_count", 0)) - start_count,
            permit.action_key,
            dispatch_returned,
        )
    except BaseException:
        raise
