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


def reset_identity_is_positive(reset_identity: Optional[str]) -> bool:
    """True only for a positively established non-empty reset / game-day identity."""

    if not isinstance(reset_identity, str):
        return False
    value = reset_identity.strip()
    return bool(value) and bool(_RESET_IDENTITY_RE.fullmatch(value))


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
) -> UltimateChallengeResetWindowState:
    """Persist one success for the given reset window; fail closed on ambiguous identity."""

    if not reset_identity_is_positive(reset_identity):
        raise ValueError("cannot record Ultimate Challenge success without positive reset identity")
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
