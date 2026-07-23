"""Offline Ultimate Challenge daily contracts.

Separate from Campaign AP destination parsing and from Ruins Challenge Daily.
Owns ``already_completed`` detection and one-success-per-reset / reset-window
fail-closed persistence. Does not authorize challenge-action dispatch,
production registration, or gameplay scheduling.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Mapping, Optional

from .contracts import ROI
from .profile import PROFILE_ID


FLOW_ID = "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION"
ULTIMATE_CHALLENGE_ENTRY_IDENTITY = "ultimate-challenge-entry"
ULTIMATE_CHALLENGE_OBJECTIVE = "ultimate_challenge_daily"

TERMINAL_ALREADY_COMPLETED = "already_completed"
TERMINAL_NAVIGATION_ONLY_COMPLETE = "navigation_only_complete"
TERMINAL_BLOCKED = "blocked_fail_closed"
TERMINAL_COMPLETE_FOR_RESET = "complete_for_reset"

# The consequential route is intentionally explicit and finite.  These values
# are state identities, not visual evidence claims; a production recognizer
# must positively bind each state before its corresponding action is allowed.
ULTIMATE_CHALLENGE_STATE = "ultimate_challenge"
HERO_LINEUP_STATE = "hero_lineup"
ACTIVE_CHALLENGE_STATE = "active_challenge"
FLEE_WARNING_STATE = "flee_warning"
FLEE_CONFIRMED_STATE = "flee_confirmed"
HOME_RETURNED_STATE = "home_returned"
ULTIMATE_CHALLENGE_STATES = (
    ULTIMATE_CHALLENGE_STATE,
    HERO_LINEUP_STATE,
    ACTIVE_CHALLENGE_STATE,
    FLEE_WARNING_STATE,
    FLEE_CONFIRMED_STATE,
    HOME_RETURNED_STATE,
)

ACTION_TAP_CHALLENGE = "tap_challenge"
ACTION_TAP_LINEUP_CHALLENGE = "tap_lineup_challenge"
ACTION_TAP_UPPER_RIGHT_EXIT = "tap_upper_right_exit"
ACTION_TAP_FLEE = "tap_flee"
ACTION_RETURN_CANONICAL_HOME = "return_canonical_home"
ULTIMATE_CHALLENGE_ACTIONS = (
    ACTION_TAP_CHALLENGE,
    ACTION_TAP_LINEUP_CHALLENGE,
    ACTION_TAP_UPPER_RIGHT_EXIT,
    ACTION_TAP_FLEE,
    ACTION_RETURN_CANONICAL_HOME,
)

_EXPECTED_PREDECESSOR = {
    HERO_LINEUP_STATE: ULTIMATE_CHALLENGE_STATE,
    ACTIVE_CHALLENGE_STATE: HERO_LINEUP_STATE,
    FLEE_WARNING_STATE: ACTIVE_CHALLENGE_STATE,
    FLEE_CONFIRMED_STATE: FLEE_WARNING_STATE,
    HOME_RETURNED_STATE: FLEE_CONFIRMED_STATE,
}

REPLAY_EVIDENCE_REQUIRED = "evidence_required"

COMPLETION_UNKNOWN = "unknown"
COMPLETION_COMPLETED = "completed"
COMPLETION_NOT_COMPLETED = "not_completed"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RESET_IDENTITY_RE = re.compile(r"^[A-Za-z0-9._:-]{4,128}$")


def _has_ocr_token(folded_text: str, token: str) -> bool:
    """True when ``token`` appears as a whole word (avoids unclaimed/ultimately substrings)."""

    return re.search(rf"\b{re.escape(token)}\b", folded_text) is not None


# Broad Campaign-screen search window for Ultimate Challenge entry OCR (native 800x1280).
ULTIMATE_CHALLENGE_ENTRY_SEARCH_ROI: ROI = (40, 160, 760, 1100)


@dataclass(frozen=True)
class UltimateChallengeResetWindowState:
    """Persistent last-success / reset-window state for one-success-per-reset."""

    reset_identity: Optional[str]
    last_success_reset_identity: Optional[str]
    last_success_at: Optional[str]
    completion_state: str = COMPLETION_UNKNOWN
    schema_version: int = 1
    flow_id: str = FLOW_ID
    objective: str = ULTIMATE_CHALLENGE_OBJECTIVE

    def __post_init__(self) -> None:
        if self.flow_id != FLOW_ID:
            raise ValueError("Ultimate Challenge reset state must use the UC flow id")
        if self.objective != ULTIMATE_CHALLENGE_OBJECTIVE:
            raise ValueError("Ultimate Challenge reset state must use the UC objective")
        if self.completion_state not in {
            COMPLETION_UNKNOWN,
            COMPLETION_COMPLETED,
            COMPLETION_NOT_COMPLETED,
        }:
            raise ValueError(f"invalid UC completion_state: {self.completion_state}")


@dataclass(frozen=True)
class UltimateChallengeEntryObservation:
    """Bound Ultimate Challenge entry control on a verified Campaign screen."""

    campaign_screen_recognized: bool
    entry_control_visible: bool
    entry_control_identity: str
    entry_roi: Optional[ROI]
    already_completed_marker: bool
    reset_identity: Optional[str]
    source_frame_sha256: str
    overlay_state: str = "none_observed"
    runtime_profile_id: str = PROFILE_ID
    recognized: bool = True

    def __post_init__(self) -> None:
        if self.entry_roi is not None:
            x0, y0, x1, y1 = self.entry_roi
            if not (0 <= x0 < x1 <= 800 and 0 <= y0 < y1 <= 1280):
                raise ValueError("Ultimate Challenge entry ROI must be native 800x1280 bounds")


@dataclass(frozen=True)
class UltimateChallengeNavigationDecision:
    terminal: str
    reason: str
    dispatch_authorized: bool
    reset_identity: Optional[str] = None
    entry_roi: Optional[ROI] = None
    details: Mapping[str, object] | None = None


@dataclass(frozen=True)
class UltimateChallengeExecutionObservation:
    """One positively recognized frame for the bounded consequential route.

    ``native_selector_evidence`` is deliberately separate from a boolean
    target bind.  A semantic state or coordinate alone cannot authorize an
    input; both must be backed by current native, hash-bound selector proof.
    """

    state: str
    target_bound: bool
    native_selector_evidence: bool
    reset_identity: Optional[str]
    source_frame_sha256: str
    target_roi: Optional[ROI]
    recognized: bool = True
    overlay_state: str = "none_observed"
    resource_prompt_visible: bool = False
    resource_cost: object | None = None
    auto_battle_visible: bool = False
    refill_visible: bool = False
    already_complete: bool = False
    runtime_profile_id: str = PROFILE_ID

    def __post_init__(self) -> None:
        if self.target_roi is not None:
            x0, y0, x1, y1 = self.target_roi
            if not (0 <= x0 < x1 <= 800 and 0 <= y0 < y1 <= 1280):
                raise ValueError("Ultimate Challenge target ROI must be native 800x1280 bounds")


@dataclass(frozen=True)
class UltimateChallengeExecutionDecision:
    """Bounded next-step decision; ``dispatch_authorized`` gates transport."""

    state: str
    action: str | None
    successor_state: str | None
    dispatch_authorized: bool
    terminal: str
    reason: str
    reset_identity: Optional[str] = None
    completion_recordable: bool = False


@dataclass(frozen=True)
class UltimateChallengeReplayGate:
    """Truthful zero-transport replay status for the current evidence set."""

    status: str
    transport_count: int
    dispatch_authorized: bool
    evidence_required: bool
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "transport_count": self.transport_count,
            "dispatch_authorized": self.dispatch_authorized,
            "evidence_required": self.evidence_required,
            "reason": self.reason,
        }


def reset_identity_is_positive(reset_identity: Optional[str]) -> bool:
    """True only for a positively established non-empty reset / game-day identity."""

    if not isinstance(reset_identity, str):
        return False
    value = reset_identity.strip()
    return bool(value) and bool(_RESET_IDENTITY_RE.fullmatch(value))


def _execution_blocked(
    observation: UltimateChallengeExecutionObservation,
    reason: str,
    *,
    reset_identity: Optional[str],
) -> UltimateChallengeExecutionDecision:
    return UltimateChallengeExecutionDecision(
        state=observation.state,
        action=None,
        successor_state=None,
        dispatch_authorized=False,
        terminal=TERMINAL_BLOCKED,
        reason=reason,
        reset_identity=reset_identity,
    )


def evaluate_execution_step(
    observation: UltimateChallengeExecutionObservation,
    *,
    current_reset_identity: Optional[str] = None,
    prior_state: str | None = None,
) -> UltimateChallengeExecutionDecision:
    """Plan one exact Ultimate Challenge step, failing closed before transport.

    This is an offline policy seam only.  It does not dispatch input, register a
    runner, or infer missing visual evidence.  Completion is recordable only
    after a recognized ``flee_confirmed`` successor reaches canonical Home.
    """

    identity = current_reset_identity
    if not reset_identity_is_positive(identity):
        return _execution_blocked(
            observation,
            "Ultimate Challenge requires an explicit positive current reset identity",
            reset_identity=identity,
        )
    if observation.state not in ULTIMATE_CHALLENGE_STATES:
        return _execution_blocked(
            observation,
            "unrecognized Ultimate Challenge state",
            reset_identity=identity,
        )
    if not reset_identity_is_positive(observation.reset_identity):
        return _execution_blocked(
            observation,
            "observation requires an explicit positive reset identity",
            reset_identity=identity,
        )
    if observation.reset_identity != current_reset_identity:
        return _execution_blocked(
            observation,
            "observation reset identity does not match current reset window",
            reset_identity=identity,
        )

    if not observation.already_complete:
        expected_predecessor = _EXPECTED_PREDECESSOR.get(observation.state)
        if observation.state != ULTIMATE_CHALLENGE_STATE and prior_state is None:
            return _execution_blocked(
                observation,
                "Ultimate Challenge route must start at ultimate_challenge",
                reset_identity=identity,
            )
        if prior_state is not None and expected_predecessor != prior_state:
            return _execution_blocked(
                observation,
                "state does not follow the required Ultimate Challenge transition",
                reset_identity=identity,
            )

    if not observation.recognized:
        return _execution_blocked(observation, "state is not recognized", reset_identity=identity)
    if observation.runtime_profile_id != PROFILE_ID or not _SHA256_RE.fullmatch(
        observation.source_frame_sha256 or ""
    ):
        return _execution_blocked(
            observation,
            "current native frame/profile provenance is required",
            reset_identity=identity,
        )
    if observation.overlay_state not in {"none", "none_observed"}:
        return _execution_blocked(
            observation,
            "unexpected overlay blocks Ultimate Challenge dispatch",
            reset_identity=identity,
        )
    if (
        observation.resource_prompt_visible
        or observation.resource_cost is not None
        or observation.auto_battle_visible
        or observation.refill_visible
    ):
        return _execution_blocked(
            observation,
            "resource prompt/cost, refill, or Auto Battle is prohibited",
            reset_identity=identity,
        )
    if observation.state == HOME_RETURNED_STATE:
        if not observation.native_selector_evidence:
            return _execution_blocked(
                observation,
                "native hash-bound Home evidence is required",
                reset_identity=identity,
            )
        if observation.already_complete:
            return UltimateChallengeExecutionDecision(
                state=observation.state,
                action=None,
                successor_state=HOME_RETURNED_STATE,
                dispatch_authorized=False,
                terminal=TERMINAL_BLOCKED,
                reason="already-complete Home policy is valid but native replay evidence is required",
                reset_identity=identity,
            )
        completed = prior_state == FLEE_CONFIRMED_STATE
        return UltimateChallengeExecutionDecision(
            state=HOME_RETURNED_STATE,
            action=None,
            successor_state=HOME_RETURNED_STATE,
            dispatch_authorized=False,
            terminal=TERMINAL_BLOCKED,
            reason=(
                "complete_for_reset is planned after Home but native replay evidence is required"
                if completed
                else "canonical Home reached without a recognized Flee successor"
            ),
            reset_identity=identity,
            completion_recordable=False,
        )
    if observation.already_complete and observation.state == ULTIMATE_CHALLENGE_STATE:
        if not observation.native_selector_evidence:
            return _execution_blocked(
                observation,
                "native hash-bound already-complete evidence is required",
                reset_identity=identity,
            )
        return UltimateChallengeExecutionDecision(
            state=ULTIMATE_CHALLENGE_STATE,
            action=ACTION_RETURN_CANONICAL_HOME,
            successor_state=HOME_RETURNED_STATE,
            dispatch_authorized=False,
            terminal=TERMINAL_BLOCKED,
            reason="already-complete Home return is planned but native replay evidence is required",
            reset_identity=identity,
        )
    if observation.already_complete:
        return _execution_blocked(
            observation,
            "already-complete requires canonical Home terminal",
            reset_identity=identity,
        )
    if not observation.target_bound or observation.target_roi is None:
        return _execution_blocked(
            observation,
            "consequential target is not positively bound",
            reset_identity=identity,
        )
    if not observation.native_selector_evidence:
        return _execution_blocked(
            observation,
            "native hash-bound selector evidence is required",
            reset_identity=identity,
        )

    transitions = {
        ULTIMATE_CHALLENGE_STATE: (ACTION_TAP_CHALLENGE, HERO_LINEUP_STATE),
        HERO_LINEUP_STATE: (ACTION_TAP_LINEUP_CHALLENGE, ACTIVE_CHALLENGE_STATE),
        ACTIVE_CHALLENGE_STATE: (ACTION_TAP_UPPER_RIGHT_EXIT, FLEE_WARNING_STATE),
        FLEE_WARNING_STATE: (ACTION_TAP_FLEE, FLEE_CONFIRMED_STATE),
        FLEE_CONFIRMED_STATE: (ACTION_RETURN_CANONICAL_HOME, HOME_RETURNED_STATE),
    }
    action, successor = transitions[observation.state]
    return UltimateChallengeExecutionDecision(
        state=observation.state,
        action=action,
        successor_state=successor,
        dispatch_authorized=False,
        terminal=TERMINAL_BLOCKED,
        reason=(
            f"policy plans only {action} from {observation.state}; "
            "native production replay evidence is required before dispatch"
        ),
        reset_identity=identity,
    )


# Explicit alias for callers that describe this seam as a route planner.
plan_ultimate_challenge_execution = evaluate_execution_step


def ultimate_challenge_zero_transport_replay_gate(
    native_selector_fixture: Mapping[str, object] | None = None,
) -> UltimateChallengeReplayGate:
    """Report the evidence gate without fabricating a positive replay.

    No native hash-bound Ultimate Challenge selector fixture is retained in the
    repository today, so the default result is always ``evidence_required``
    with zero transport.  A future task may pass a real fixture after the
    independent evidence-retention requirements are satisfied.
    """

    if not isinstance(native_selector_fixture, Mapping):
        return UltimateChallengeReplayGate(
            status=REPLAY_EVIDENCE_REQUIRED,
            transport_count=0,
            dispatch_authorized=False,
            evidence_required=True,
            reason="native hash-bound Ultimate Challenge selector fixture is absent",
        )
    # Self-declared metadata or a plausible digest is not evidence. The gate
    # remains closed until a later task wires a retained native sequence through
    # the production recognizer/controller and consequential journal path.
    return UltimateChallengeReplayGate(
        status=REPLAY_EVIDENCE_REQUIRED,
        transport_count=0,
        dispatch_authorized=False,
        evidence_required=True,
        reason="production-recognizer native sequence and journal-backed replay are absent",
    )


def entry_observation_is_bound(observation: UltimateChallengeEntryObservation) -> bool:
    """Positive bind of UC entry control on a recognized Campaign screen (no action)."""

    return bool(
        observation.recognized
        and observation.campaign_screen_recognized
        and observation.entry_control_visible
        and observation.entry_control_identity == ULTIMATE_CHALLENGE_ENTRY_IDENTITY
        and observation.entry_roi is not None
        and observation.overlay_state in {"none", "none_observed"}
        and observation.runtime_profile_id == PROFILE_ID
        and bool(_SHA256_RE.fullmatch(observation.source_frame_sha256 or ""))
    )


def evaluate_already_completed(
    state: UltimateChallengeResetWindowState,
    *,
    current_reset_identity: Optional[str],
    observation: UltimateChallengeEntryObservation | None = None,
) -> UltimateChallengeNavigationDecision:
    """Return already_completed or fail closed; never authorizes challenge dispatch."""

    if observation is not None and observation.already_completed_marker:
        # Generic OCR "claimed" / "already"+"complet" must not terminal without a bound UC entry.
        if not (
            observation.campaign_screen_recognized
            and observation.entry_control_visible
            and observation.entry_control_identity == ULTIMATE_CHALLENGE_ENTRY_IDENTITY
        ):
            return UltimateChallengeNavigationDecision(
                terminal=TERMINAL_BLOCKED,
                reason="already_completed marker without bound Ultimate Challenge entry identity",
                dispatch_authorized=False,
                reset_identity=current_reset_identity,
            )
        if not reset_identity_is_positive(current_reset_identity) and not reset_identity_is_positive(
            observation.reset_identity
        ):
            return UltimateChallengeNavigationDecision(
                terminal=TERMINAL_BLOCKED,
                reason="already_completed marker without positive reset identity",
                dispatch_authorized=False,
                reset_identity=current_reset_identity,
            )
        identity = current_reset_identity or observation.reset_identity
        return UltimateChallengeNavigationDecision(
            terminal=TERMINAL_ALREADY_COMPLETED,
            reason="verified already_completed marker on Campaign Ultimate Challenge entry",
            dispatch_authorized=False,
            reset_identity=identity,
            entry_roi=observation.entry_roi if entry_observation_is_bound(observation) else None,
        )

    if state.completion_state == COMPLETION_COMPLETED:
        if not reset_identity_is_positive(current_reset_identity):
            return UltimateChallengeNavigationDecision(
                terminal=TERMINAL_BLOCKED,
                reason="ambiguous reset identity while completion_state=completed",
                dispatch_authorized=False,
                reset_identity=current_reset_identity,
            )
        if not reset_identity_is_positive(state.last_success_reset_identity):
            return UltimateChallengeNavigationDecision(
                terminal=TERMINAL_BLOCKED,
                reason="completion_state=completed without positive last_success_reset_identity",
                dispatch_authorized=False,
                reset_identity=current_reset_identity,
            )
        if state.last_success_reset_identity != current_reset_identity:
            return UltimateChallengeNavigationDecision(
                terminal=TERMINAL_BLOCKED,
                reason="completion_state=completed but last success is outside current reset window",
                dispatch_authorized=False,
                reset_identity=current_reset_identity,
                details={
                    "last_success_reset_identity": state.last_success_reset_identity,
                    "current_reset_identity": current_reset_identity,
                },
            )
        return UltimateChallengeNavigationDecision(
            terminal=TERMINAL_ALREADY_COMPLETED,
            reason="verified one-success-per-reset already_completed for current reset window",
            dispatch_authorized=False,
            reset_identity=current_reset_identity,
        )

    if state.completion_state == COMPLETION_UNKNOWN and state.last_success_reset_identity:
        return UltimateChallengeNavigationDecision(
            terminal=TERMINAL_BLOCKED,
            reason="ambiguous completion_state with last_success_reset_identity present",
            dispatch_authorized=False,
            reset_identity=current_reset_identity,
        )

    return UltimateChallengeNavigationDecision(
        terminal=TERMINAL_BLOCKED,
        reason="not already_completed",
        dispatch_authorized=False,
        reset_identity=current_reset_identity,
    )


def evaluate_navigation_only(
    state: UltimateChallengeResetWindowState,
    observation: UltimateChallengeEntryObservation,
    *,
    current_reset_identity: Optional[str] = None,
) -> UltimateChallengeNavigationDecision:
    """Navigation-only decision: already_completed, entry verified, or fail closed."""

    identity = current_reset_identity if current_reset_identity is not None else observation.reset_identity
    completed = evaluate_already_completed(
        state,
        current_reset_identity=identity,
        observation=observation,
    )
    if completed.terminal == TERMINAL_ALREADY_COMPLETED:
        return completed
    if completed.terminal == TERMINAL_BLOCKED and completed.reason != "not already_completed":
        return completed

    if not entry_observation_is_bound(observation):
        return UltimateChallengeNavigationDecision(
            terminal=TERMINAL_BLOCKED,
            reason="Ultimate Challenge entry control not positively bound on Campaign screen",
            dispatch_authorized=False,
            reset_identity=identity,
        )

    # Navigation-only validates entry bind; challenge action remains unauthorized.
    return UltimateChallengeNavigationDecision(
        terminal=TERMINAL_NAVIGATION_ONLY_COMPLETE,
        reason="Ultimate Challenge entry control verified; navigation-only stops before challenge action",
        dispatch_authorized=False,
        reset_identity=identity,
        entry_roi=observation.entry_roi,
    )


def record_verified_success(
    state: UltimateChallengeResetWindowState,
    *,
    reset_identity: str,
    success_at: str | None = None,
    terminal_state: str | None = None,
) -> UltimateChallengeResetWindowState:
    """Persist one success only after the canonical Home terminal.

    Callers must explicitly supply the canonical Home terminal; recording from
    Flee or any intermediate/omitted state is rejected.
    """

    if not reset_identity_is_positive(reset_identity):
        raise ValueError("cannot record Ultimate Challenge success without positive reset identity")
    if terminal_state != HOME_RETURNED_STATE:
        raise ValueError("Ultimate Challenge success requires canonical Home terminal")
    if (
        state.completion_state == COMPLETION_COMPLETED
        and state.last_success_reset_identity == reset_identity
    ):
        raise ValueError("repeated Ultimate Challenge success in the same reset window is prohibited")
    stamp = success_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return UltimateChallengeResetWindowState(
        reset_identity=reset_identity,
        last_success_reset_identity=reset_identity,
        last_success_at=stamp,
        completion_state=COMPLETION_COMPLETED,
    )


def record_verified_home_success(
    state: UltimateChallengeResetWindowState,
    *,
    reset_identity: str,
    success_at: str | None = None,
) -> UltimateChallengeResetWindowState:
    """Named Home-terminal wrapper for new execution integrations."""

    return record_verified_success(
        state,
        reset_identity=reset_identity,
        success_at=success_at,
        terminal_state=HOME_RETURNED_STATE,
    )


def empty_reset_window_state() -> UltimateChallengeResetWindowState:
    return UltimateChallengeResetWindowState(
        reset_identity=None,
        last_success_reset_identity=None,
        last_success_at=None,
        completion_state=COMPLETION_NOT_COMPLETED,
    )


def load_reset_window_state(path: Path) -> UltimateChallengeResetWindowState:
    if not path.is_file():
        return empty_reset_window_state()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Ultimate Challenge reset-window state must be a JSON object")
    if "flow_id" not in raw:
        raise ValueError("Ultimate Challenge reset state requires explicit flow_id")
    if "objective" not in raw:
        raise ValueError("Ultimate Challenge reset state requires explicit objective")
    return UltimateChallengeResetWindowState(
        reset_identity=raw.get("reset_identity"),
        last_success_reset_identity=raw.get("last_success_reset_identity"),
        last_success_at=raw.get("last_success_at"),
        completion_state=str(raw.get("completion_state") or COMPLETION_UNKNOWN),
        schema_version=int(raw.get("schema_version") or 1),
        flow_id=str(raw["flow_id"]),
        objective=str(raw["objective"]),
    )


def save_reset_window_state(path: Path, state: UltimateChallengeResetWindowState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _ocr_hit_texts(
    ocr_hits: Mapping[str, ROI] | list[tuple[str, ROI]] | list[str],
) -> list[str]:
    if isinstance(ocr_hits, Mapping):
        return [str(text) for text in ocr_hits.keys()]
    texts: list[str] = []
    for item in ocr_hits:
        if isinstance(item, tuple) and item:
            texts.append(str(item[0]))
        else:
            texts.append(str(item))
    return texts


def ultimate_challenge_entry_roi_from_ocr_hits(
    ocr_hits: Mapping[str, ROI] | list[tuple[str, ROI]],
) -> ROI | None:
    """Return UC entry ROI only for ultimate+challenge (or equivalent strong identity).

    Lone ``ultimate`` / ``ultim`` hits are insufficient. Word-boundary matching rejects
    substrings such as ``ultimately``.
    """

    hits = dict(ocr_hits) if isinstance(ocr_hits, Mapping) else dict(ocr_hits)

    def _is_ultimate_token(folded: str) -> bool:
        stripped = folded.strip()
        return _has_ocr_token(stripped, "ultimate") or stripped == "ultim"

    def _is_challenge_token(folded: str) -> bool:
        return _has_ocr_token(folded.strip(), "challenge")

    for text, roi in hits.items():
        folded = str(text).casefold()
        if _is_ultimate_token(folded) and _is_challenge_token(folded):
            return roi

    ultimate_roi: ROI | None = None
    challenge_seen = False
    for text, roi in hits.items():
        folded = str(text).casefold()
        if _is_challenge_token(folded):
            challenge_seen = True
        # Accept truncated OCR "ultim" only when "challenge" is also present (strong pair).
        if _is_ultimate_token(folded):
            if ultimate_roi is None:
                ultimate_roi = roi
    if ultimate_roi is not None and challenge_seen:
        return ultimate_roi
    return None


def _ocr_signals_already_completed(folded_texts: list[str], joined: str) -> bool:
    """True for already+completed/complete tokens; never for incomplete substrings."""

    def _has_incomplete(text: str) -> bool:
        return _has_ocr_token(text, "incomplete")

    def _has_already(text: str) -> bool:
        return _has_ocr_token(text, "already")

    def _has_complete_phrase(text: str) -> bool:
        return _has_ocr_token(text, "completed") or _has_ocr_token(text, "complete")

    if any(_has_incomplete(text) for text in folded_texts) or _has_incomplete(joined):
        return False
    already = any(_has_already(text) for text in folded_texts) or _has_already(joined)
    completed = any(_has_complete_phrase(text) for text in folded_texts) or _has_complete_phrase(
        joined
    )
    return bool(already and completed)


def ultimate_challenge_already_completed_from_ocr_hits(
    ocr_hits: Mapping[str, ROI] | list[tuple[str, ROI]] | list[str],
    *,
    entry_control_visible: bool,
) -> bool:
    """Detect UC already_completed from OCR without treating generic Campaign text as terminal.

    Generic ``claimed`` / ``already``+``completed`` in a wide ROI require a bound UC entry.
    Stronger UC-scoped phrases (ultimate+challenge with claimed/already-completed) may qualify
    on their own because they carry the UC identity in-text. ``Unclaimed`` must not match
    ``claimed``. Any ``incomplete`` token rejects the marker on every path (claimed,
    already+complete, and UC-scoped); ``incomplete`` must not match ``complete``/``completed``
    (word-boundary / token match only).
    """

    folded_texts = [text.casefold() for text in _ocr_hit_texts(ocr_hits)]
    joined = " ".join(folded_texts)
    # Incomplete rejects already_completed for claimed, already+complete, and UC-scoped paths.
    if any(_has_ocr_token(text, "incomplete") for text in folded_texts) or _has_ocr_token(
        joined, "incomplete"
    ):
        return False
    uc_scoped = _has_ocr_token(joined, "ultimate") and _has_ocr_token(joined, "challenge")
    claimed = any(_has_ocr_token(text, "claimed") for text in folded_texts) or _has_ocr_token(
        joined, "claimed"
    )
    already_complet = _ocr_signals_already_completed(folded_texts, joined)
    if uc_scoped and (claimed or already_complet):
        return True
    if not entry_control_visible:
        return False
    return bool(claimed or already_complet)


def recognize_ultimate_challenge_entry_from_texts(
    *,
    campaign_screen_recognized: bool,
    ocr_hits: Mapping[str, ROI] | list[tuple[str, ROI]],
    source_frame_sha256: str,
    reset_identity: Optional[str] = None,
    already_completed_marker: bool | None = None,
    overlay_state: str = "none_observed",
) -> UltimateChallengeEntryObservation:
    """Build an entry observation from OCR word hits (offline / operator shared)."""

    entry_roi = ultimate_challenge_entry_roi_from_ocr_hits(ocr_hits)
    visible = entry_roi is not None and campaign_screen_recognized
    if already_completed_marker is None:
        marker = ultimate_challenge_already_completed_from_ocr_hits(
            ocr_hits, entry_control_visible=visible
        )
    else:
        # Explicit marker still cannot stick without UC entry identity on this frame.
        marker = bool(already_completed_marker) and visible
    return UltimateChallengeEntryObservation(
        campaign_screen_recognized=campaign_screen_recognized,
        entry_control_visible=visible,
        entry_control_identity=ULTIMATE_CHALLENGE_ENTRY_IDENTITY if visible else "",
        entry_roi=entry_roi if visible else None,
        already_completed_marker=marker,
        reset_identity=reset_identity,
        source_frame_sha256=source_frame_sha256,
        overlay_state=overlay_state,
        recognized=True,
    )
