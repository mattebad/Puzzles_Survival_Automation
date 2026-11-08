"""Native Alliance Help route: ten positively confirmed, free requests per UTC reset."""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import re
from functools import lru_cache
import time
from typing import Any, Callable, Mapping, Sequence

import cv2
import numpy as np

from safe_action_core import (
    ActionClass, ActionStatus, CentralPolicy, Observation, PolicyRequest,
    SafeActionExecutor, TransportResult,
)
from scripts.bounded_tesseract import call_ocr, tesseract_data, tesseract_string
from scripts.startup_normalization import is_clean_home_frame
from automation_service.registry import (
    ALLIANCE_HELP_FLOW_ID, ALLIANCE_HELP_MAX_INPUTS, ALLIANCE_HELP_PROFILE_ID,
    ALLIANCE_HELP_PRODUCT_ID, ALLIANCE_HELP_PRODUCT_REVISION,
)
from tasks.alliance_help import (
    CONSEQUENCE, CONTROL_CLASS, DAILY_REQUEST_LIMIT, HELP_ALL_TARGET_IDENTITY,
    INDIVIDUAL_TARGET_IDENTITY, POSTCONDITION, SEMANTIC_ACTION, SOURCE_STATE,
    HelpAction, HelpObservation, HelpPlan, HelpRequest, alliance_help_action_key,
    choose_help_action, verified_request_delta,
)
from tasks.home_nav_recognition import recognize_home_nav


FLOW_ID = ALLIANCE_HELP_FLOW_ID
PRODUCT_ID = ALLIANCE_HELP_PRODUCT_ID
PRODUCT_REVISION = ALLIANCE_HELP_PRODUCT_REVISION
PROFILE_ID = ALLIANCE_HELP_PROFILE_ID
MAX_ACTIONS = DAILY_REQUEST_LIMIT
MAX_INPUTS = ALLIANCE_HELP_MAX_INPUTS
HELP_ALL_ROI = (277, 1188, 523, 1268)
HELP_ALL_LABEL_ROI = (260, 1165, 540, 1280)
# Centered header text only. Wider bands include the Back chevron and border art, which made
# production Tesseract return empty/garbled titles on retained native Alliance and Help frames.
SCREEN_TITLE_ROI = (260, 6, 540, 60)
# Label line of the Alliance menu bottom bar (Shop, Mail, Help, Operations); icons sit above it.
ALLIANCE_MENU_BAR_ROI = (60, 1252, 740, 1280)
ALLIANCE_MENU_BAR_LABELS = ("alliance shop", "alliance mail", "alliance help", "operations")
ALLIANCE_MENU_LABEL_GAP = 20
ALLIANCE_MENU_ICON_TOP = 1190
ROUTE_CONTEXT_ALLIANCE_MENU = "alliance_menu"
ROUTE_CONTEXT_SPEEDUP_HELP = "speedup_help"
ALLIANCE_COIN_ROI = (205, 135, 755, 185)
HELP_SUCCESS_ROI = (80, 230, 760, 465)
NO_REQUESTS_ROI = (80, 430, 760, 700)
HELP_ROW_SCAN_ROI = (0, 210, 800, 1150)
HELP_SOURCE_PATH = Path(__file__).resolve().parents[1] / "tasks" / "assets" / "navigation" / "800x1280" / "alliance_help_source.png"


@dataclass(frozen=True)
class HelpToken:
    text: str
    roi: tuple[int, int, int, int]
    confidence: float


def _norm(text: object) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text or "").casefold()).split())


def _ocr_text(frame: np.ndarray, roi: tuple[int, int, int, int], *, psm: int = 7,
              reader: Callable[..., str] | None = None) -> str:
    x0, y0, x1, y1 = roi
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return ""
    enlarged = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    read = reader or tesseract_string
    return str(call_ocr(read, enlarged, config=f"--psm {psm}")).strip()


def _ocr_tokens(frame: np.ndarray, roi: tuple[int, int, int, int], *,
                reader: Callable[..., Mapping[str, Sequence[object]]] | None = None) -> tuple[HelpToken, ...]:
    x0, y0, x1, y1 = roi
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return ()
    scale = 2
    enlarged = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    data = call_ocr(reader or tesseract_data, enlarged, config="--psm 11")
    tokens: list[HelpToken] = []
    fields = (data.get("text", ()), data.get("left", ()), data.get("top", ()),
              data.get("width", ()), data.get("height", ()), data.get("conf", ()))
    for raw, left, top, width, height, confidence in zip(*fields):
        text = _norm(raw)
        try:
            x, y, w, h, conf = int(left), int(top), int(width), int(height), float(confidence)
        except (TypeError, ValueError, OverflowError):
            continue
        if not text or w <= 0 or h <= 0 or conf < 30:
            continue
        target = (x0 + x // scale, y0 + y // scale,
                  min(x1, x0 + (x + w + scale - 1) // scale),
                  min(y1, y0 + (y + h + scale - 1) // scale))
        if target[0] < target[2] and target[1] < target[3]:
            tokens.append(HelpToken(text, target, conf))
    return tuple(tokens)


def _orange_button(frame: np.ndarray, roi: tuple[int, int, int, int]) -> bool:
    x0, y0, x1, y1 = roi
    patch = frame[y0:y1, x0:x1]
    if patch.size == 0:
        return False
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    orange = cv2.inRange(hsv, (5, 55, 65), (38, 255, 255))
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    edge = cv2.Canny(gray, 60, 160)
    return (float(np.count_nonzero(orange)) / float(orange.size) >= 0.10
            and float(np.count_nonzero(edge)) / float(edge.size) >= 0.003)


def _coin_counter(frame: np.ndarray, *, reader: Callable[..., str] | None = None) -> tuple[int, int] | None:
    text = _ocr_text(frame, ALLIANCE_COIN_ROI, psm=7, reader=reader).casefold()
    match = re.search(
        r"daily\s+alliance\s+coin\s+([0-9][0-9, ]*)\s*/\s*([0-9][0-9, ]*)",
        text,
    )
    if match is None:
        return None
    try:
        balance, limit = (int(re.sub(r"[ ,]", "", value)) for value in match.groups())
    except (ValueError, OverflowError):
        return None
    return (balance, limit) if 0 <= balance <= limit and limit > 0 else None


def _request_identifier(tokens: Sequence[HelpToken], center_y: int) -> str | None:
    row = [token for token in tokens
           if 140 <= (token.roi[0] + token.roi[2]) // 2 < 545
           and center_y - 54 <= (token.roi[1] + token.roi[3]) // 2 <= center_y + 38]
    ignored = {"help", "all", "please", "me", "build", "building", "gas", "field", "request"}
    words = [token.text for token in sorted(row, key=lambda item: (
        (item.roi[1] + item.roi[3]) // 2, item.roi[0])) if token.text not in ignored]
    descriptor = _norm(" ".join(words))
    if len(descriptor.split()) < 2:
        return None
    return hashlib.sha256(descriptor.encode("utf-8")).hexdigest()[:24]


def _individual_controls(frame: np.ndarray, *, reader: Callable[..., Mapping[str, Sequence[object]]] | None = None
                         ) -> tuple[HelpRequest, ...]:
    tokens = _ocr_tokens(frame, HELP_ROW_SCAN_ROI, reader=reader)
    found: list[HelpRequest] = []
    for token in tokens:
        if token.text != "help":
            continue
        x0, y0, x1, y1 = token.roi
        center_x, center_y = (x0 + x1) // 2, (y0 + y1) // 2
        if not (550 <= center_x <= 750 and 235 <= center_y <= 1100):
            continue
        button_roi = (max(535, x0 - 48), max(210, y0 - 20),
                      min(760, x1 + 48), min(1120, y1 + 20))
        if not _orange_button(frame, button_roi):
            continue
        request_id = _request_identifier(tokens, center_y)
        if request_id is None:
            continue
        found.append(HelpRequest(request_id, button_roi, True, True))
    return tuple(found)


def _help_all_control(frame: np.ndarray, *, reader: Callable[..., str] | None = None
                     ) -> tuple[tuple[int, int, int, int] | None, bool]:
    label = _norm(_ocr_text(frame, HELP_ALL_LABEL_ROI, psm=7, reader=reader))
    if label != "help all" or not _orange_button(frame, HELP_ALL_ROI):
        return None, False
    return HELP_ALL_ROI, True




def recognize_help_screen(
    frame: np.ndarray,
    *,
    captured_at: float,
    frame_sha256: str,
    now: float | None = None,
    text_reader: Callable[..., str] | None = None,
    token_reader: Callable[..., Mapping[str, Sequence[object]]] | None = None,
    overlay_reader: Callable[[np.ndarray], Mapping[str, object]] | None = None,
) -> HelpObservation:
    """Recognize current source, exact free targets, and source-grounded result signals."""
    current = time.monotonic() if now is None else now
    if (not isinstance(frame, np.ndarray) or frame.shape != (1280, 800, 3)
            or type(captured_at) not in (int, float) or type(captured_at) is bool
            or type(frame_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", frame_sha256)):
        return HelpObservation("UNKNOWN", float(captured_at or 0), str(frame_sha256 or ""),
                               False, False, (), recognizer_reason="invalid_frame_identity")
    title = _norm(_ocr_text(frame, SCREEN_TITLE_ROI, psm=7, reader=text_reader))
    if title.replace(" ", "") != "speeduphelp":
        return HelpObservation("UNKNOWN", float(captured_at), frame_sha256, False,
                               0 <= current - captured_at <= 30.0, (), recognizer_reason="speedup_help_title_unrecognized")
    overlay_clear, overlay_reason = _overlay_evidence(frame, overlay_reader)
    requests = _individual_controls(frame, reader=token_reader)
    help_all_roi, help_all_free = _help_all_control(frame, reader=text_reader)
    body = _norm(_ocr_text(frame, NO_REQUESTS_ROI, psm=6, reader=text_reader))
    exact_no_requests = "no help request currently" in body
    result_text = _norm(_ocr_text(frame, HELP_SUCCESS_ROI, psm=6, reader=text_reader))
    success_message = "help successful" in result_text
    coin = _coin_counter(frame, reader=text_reader)
    # Existing captures prove the individual Help button is zero-cost, but not arbitrary
    # currencies or paid controls. Any cost word adjacent to a current CTA invalidates it.
    cost_words = {"buy", "cost", "diamond", "diamonds", "gem", "gems", "cash", "purchase"}
    control_tokens = _ocr_tokens(frame, (535, 210, 760, 1120), reader=token_reader)
    cost_marker = any(token.text in cost_words for token in control_tokens)
    return HelpObservation(
        screen_state=SOURCE_STATE, captured_at=float(captured_at), frame_sha256=frame_sha256,
        overlay_clear=bool(overlay_clear), source_fresh=0 <= current - captured_at <= 30.0,
        requests=requests, help_all_roi=help_all_roi, help_all_free=help_all_free,
        exact_no_requests_message=exact_no_requests, pending_count=None,
        request_list_complete=False, cost_marker_seen=cost_marker,
        daily_alliance_coin_balance=coin[0] if coin else None,
        daily_alliance_coin_limit=coin[1] if coin else None,
        help_success_message=success_message, help_all_success_count=None,
        recognizer_reason=None if overlay_clear else overlay_reason,
    )


def _default_overlay_reader(frame: np.ndarray) -> Mapping[str, object]:
    from scripts.daily_row_claim_bluestacks import _generic_modal_overlay_evidence
    return _generic_modal_overlay_evidence(frame)


def _overlay_evidence(frame: np.ndarray, overlay_reader: Callable[[np.ndarray], Mapping[str, object]] | None = None
                      ) -> tuple[bool, str]:
    """Return whether the generic modal recognizer positively reports no overlay."""
    try:
        overlay = (overlay_reader or _default_overlay_reader)(frame)
    except Exception as exc:
        return False, f"overlay_recognizer_failed:{type(exc).__name__}"
    clear = overlay.get("recognized") is False and overlay.get("state") in {"none_observed", "none"}
    return clear, str(overlay.get("reason") or "unknown_overlay")


def _alliance_menu_bar(frame: np.ndarray, *, token_reader: Callable[..., Mapping[str, Sequence[object]]] | None = None
                       ) -> dict[str, tuple[int, int, int, int]] | None:
    """Bind the exact four Alliance menu bottom-bar labels left to right, or nothing."""
    groups: list[list[HelpToken]] = []
    for token in sorted(_ocr_tokens(frame, ALLIANCE_MENU_BAR_ROI, reader=token_reader), key=lambda item: item.roi[0]):
        if groups and token.roi[0] - max(item.roi[2] for item in groups[-1]) <= ALLIANCE_MENU_LABEL_GAP:
            groups[-1].append(token)
        else:
            groups.append([token])
    # OCR may split one word ("allian" + "ce"); compare each label without spaces.
    labels = tuple("".join(token.text.replace(" ", "") for token in group) for group in groups)
    if labels != tuple(label.replace(" ", "") for label in ALLIANCE_MENU_BAR_LABELS):
        return None
    return {label: (min(token.roi[0] for token in group), min(token.roi[1] for token in group),
                    max(token.roi[2] for token in group), max(token.roi[3] for token in group))
            for label, group in zip(ALLIANCE_MENU_BAR_LABELS, groups)}


def _alliance_menu(frame: np.ndarray, *, text_reader: Callable[..., str] | None = None,
                   token_reader: Callable[..., Mapping[str, Sequence[object]]] | None = None,
                   overlay_reader: Callable[[np.ndarray], Mapping[str, object]] | None = None) -> bool:
    """Exact Alliance title, positively clear overlay, and the exact Alliance bottom bar."""
    title = _norm(_ocr_text(frame, SCREEN_TITLE_ROI, psm=7, reader=text_reader))
    return (title == "alliance" and _overlay_evidence(frame, overlay_reader)[0]
            and _alliance_menu_bar(frame, token_reader=token_reader) is not None)


def _menu_help_target(frame: np.ndarray, *, token_reader: Callable[..., Mapping[str, Sequence[object]]] | None = None
                     ) -> tuple[int, int, int, int] | None:
    """Bind the bottom-bar Alliance Help entry: its recognized label plus the icon above it."""
    bar = _alliance_menu_bar(frame, token_reader=token_reader)
    if bar is None:
        return None
    x0, _y0, x1, y1 = bar["alliance help"]
    return (x0, ALLIANCE_MENU_ICON_TOP, x1, y1)


def _route_context(captured: Any, *, now: float) -> str | None:
    """Positively recognize an existing route-owned Alliance menu or fresh, clear Help source."""
    if _alliance_menu(captured.frame):
        return ROUTE_CONTEXT_ALLIANCE_MENU
    help_screen = recognize_help_screen(captured.frame, captured_at=captured.captured_monotonic,
                                        frame_sha256=captured.sha256, now=now)
    if help_screen.screen_state == SOURCE_STATE and help_screen.source_fresh and help_screen.overlay_clear:
        return ROUTE_CONTEXT_SPEEDUP_HELP
    return None


@lru_cache(maxsize=1)
def _help_back_template() -> np.ndarray | None:
    source = cv2.imread(str(HELP_SOURCE_PATH), cv2.IMREAD_COLOR)
    if source is None or source.shape != (1280, 800, 3):
        return None
    return source[8:62, 45:170].copy()


def _back_target(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    template = _help_back_template()
    if template is None or frame.shape != (1280, 800, 3):
        return None
    search = frame[0:82, 0:190]
    if template.size == 0 or search.shape[0] < template.shape[0] or search.shape[1] < template.shape[1]:
        return None
    response = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
    _minimum, maximum, _min_location, location = cv2.minMaxLoc(response)
    if not math.isfinite(float(maximum)) or float(maximum) < 0.84:
        return None
    x, y = location
    return (x + 4, y + 4, x + template.shape[1] - 4, y + template.shape[0] - 4)


def _home(frame: np.ndarray) -> bool:
    try:
        return bool(is_clean_home_frame(frame) and recognize_home_nav(frame).is_home)
    except Exception:
        return False


def _home_alliance_target(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    if not _home(frame):
        return None
    point = recognize_home_nav(frame).button_tap_point("alliance")
    if point is None:
        return None
    return (point[0] - 4, point[1] - 4, point[0] + 4, point[1] + 4)


def _current_observation(runtime: Any, captured: Any, *, observer=recognize_help_screen,
                         now: float | None = None) -> HelpObservation:
    return observer(captured.frame, captured_at=captured.captured_monotonic,
                    frame_sha256=captured.sha256,
                    now=time.monotonic() if now is None else now)


def _navigation(*, session: Any, runtime: Any, name: str, binder: Callable[[Any], tuple[str, tuple[int, int, int, int]] | None],
                successor: Callable[[Any], bool], settle_seconds: float) -> tuple[Any | None, str]:
    current: dict[str, Any] = {}

    def authorize(before: Any) -> None:
        bound = binder(before)
        if bound is None:
            raise ValueError(f"{name}_target_not_currently_bound")
        current["identity"], current["roi"] = bound

    def dispatch(before: Any) -> None:
        runtime.tap(before, target_identity=current["identity"], target_roi=current["roi"],
                    action_key=f"alliance-help-navigation:{name}:{before.sha256[:16]}")

    def recognize(after: Any) -> str:
        current["after"] = after
        return name if successor(after) else "unknown"

    def settled() -> Any:
        time.sleep(settle_seconds)
        return runtime.capture(f"alliance-help-{name}-settled")

    outcome = session.run_action(action_class="navigation", label=f"alliance-help-{name}",
        capture=runtime.capture, authorize=authorize, dispatch=dispatch, recognize=recognize,
        settled_successor=settled, consequence_class="navigation_only")
    return (current.get("after"), str(getattr(outcome.status, "value", outcome.status)))



def _durable_request_count(
    store: Any, identity: Any,
) -> tuple[int, bool, str | None, list[dict[str, object]]]:
    actions: dict[int, Mapping[str, object]] = {}
    for ordinal in range(1, DAILY_REQUEST_LIMIT + 1):
        key = alliance_help_action_key(runtime_scope=identity.runtime_scope,
            account_id=identity.account_id, server_id=identity.server_id,
            reset_id=identity.reset_id, ordinal=ordinal)
        row = store.get_action_by_key(key)
        if row is not None:
            actions[ordinal] = row
    if not actions:
        return 0, True, None, []

    records: list[dict[str, object]] = []
    for ordinal in range(1, max(actions) + 1):
        row = actions.get(ordinal)
        if row is None:
            return len(records), False, "canonical_request_ordinals_not_contiguous", records
        key = alliance_help_action_key(runtime_scope=identity.runtime_scope,
            account_id=identity.account_id, server_id=identity.server_id,
            reset_id=identity.reset_id, ordinal=ordinal)
        expected = {
            "task_id": FLOW_ID, "semantic_action": SEMANTIC_ACTION,
            "source_state": SOURCE_STATE, "target_identity": INDIVIDUAL_TARGET_IDENTITY,
            "game_day_id": identity.reset_id, "expected_postcondition": POSTCONDITION,
            "consequence": CONSEQUENCE, "cost_type": "none", "cost_amount": 0,
            "quantity": 1, "consequential": 1, "action_key": key,
        }
        if any(row.get(field) != value for field, value in expected.items()):
            return len(records), False, "canonical_request_record_identity_mismatch", records
        if row.get("final_status") != ActionStatus.CONFIRMED.value:
            return len(records), False, "canonical_request_result_unknown", records
        records.append({field: row.get(field) for field in (
            "action_id", "action_key", "task_id", "semantic_action", "source_state",
            "target_identity", "game_day_id", "expected_postcondition", "consequence",
            "cost_type", "cost_amount", "quantity", "consequential", "final_status",
        )} | {"request_ordinal": ordinal})
    return len(records), True, None, records



class AllianceHelpActionBoundary:
    """One single-use consequential action backed by SafeActionExecutor and SafetyStore."""

    def __init__(self, *, session: Any, runtime: Any, store: Any, identity: Any,
                 validate_identity: Callable[[], None], settle_seconds: float = 1.0,
                 monotonic_clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time,
                 observer=recognize_help_screen):
        self.session, self.runtime, self.store, self.identity = session, runtime, store, identity
        self.validate_identity = validate_identity
        self.settle_seconds, self.monotonic_clock, self.wall_clock = settle_seconds, monotonic_clock, wall_clock
        self.observer, self.used = observer, False

    def execute_one(self, *, ordinal: int, remaining: int, occurrence_key: str) -> dict[str, Any]:
        if self.used:
            raise RuntimeError("Alliance Help action boundary is single-use")
        self.used = True
        self.validate_identity()
        if ordinal != DAILY_REQUEST_LIMIT - remaining + 1 or not 1 <= ordinal <= DAILY_REQUEST_LIMIT:
            raise ValueError("Alliance Help ordinal must match the exact remaining reset quota")
        source = self.session.observe(self.runtime.capture, label=f"alliance-help-proposal-{ordinal:02d}")
        source_observation = _current_observation(self.runtime, source,
            observer=self.observer, now=self.monotonic_clock())
        plan = choose_help_action(source_observation, remaining)
        if plan.action is not HelpAction.INDIVIDUAL or len(plan.request_ids) != 1:
            deferred = plan.action in {HelpAction.NO_REQUESTS, HelpAction.FREE_HELP_DISAPPEARED}
            return {"status": "deferred" if deferred else "blocked",
                    "reason": plan.reason, "help_transport_calls": 0,
                    "committed_action_count": 0, "verified_request_count": 0,
                    "effect_reconciliation_required": False,
                    "identical_retry_denied": False, "plan": plan.action.value,
                    "proposal_frame": str(source.path), "proposal_sha256": source.sha256,
                    "no_work_evidence": {
                        "screen_state": source_observation.screen_state,
                        "source_fresh": source_observation.source_fresh,
                        "overlay_clear": source_observation.overlay_clear,
                        "exact_no_requests_message": source_observation.exact_no_requests_message,
                        "free_request_controls": sum(item.free_control and item.exact_free_label
                            for item in source_observation.requests),
                        "daily_alliance_coin_balance": source_observation.daily_alliance_coin_balance,
                        "daily_alliance_coin_limit": source_observation.daily_alliance_coin_limit,
                        "cost_marker_seen": source_observation.cost_marker_seen,
                        "frame_path": str(source.path), "frame_sha256": source.sha256,
                    } if deferred else None}
        action_key = alliance_help_action_key(runtime_scope=self.identity.runtime_scope,
            account_id=self.identity.account_id, server_id=self.identity.server_id,
            reset_id=self.identity.reset_id, ordinal=ordinal)
        existing = self.store.get_action_by_key(action_key)
        if existing is not None:
            return {"status": "reconciliation_required", "reason": "request_action_key_already_exists",
                    "help_transport_calls": 0, "committed_action_count": 0,
                    "effect_reconciliation_required": existing.get("final_status") != ActionStatus.CONFIRMED.value,
                    "identical_retry_denied": True, "action_key": action_key}
        if self.store.has_action_block():
            return {"status": "reconciliation_required", "reason": "canonical_unresolved_action",
                    "help_transport_calls": 0, "committed_action_count": 0,
                    "effect_reconciliation_required": True, "identical_retry_denied": True,
                    "action_key": action_key}
        immediate_capture = self.runtime.capture(f"alliance-help-immediate-before-{ordinal:02d}")
        immediate = _current_observation(self.runtime, immediate_capture,
            observer=self.observer, now=self.monotonic_clock())
        immediate_plan = choose_help_action(immediate, remaining)
        if (immediate_plan.action is not HelpAction.INDIVIDUAL
                or immediate_plan.request_ids != plan.request_ids
                or immediate_plan.target_roi is None
                or immediate.captured_at <= source_observation.captured_at):
            return {"status": "blocked", "reason": "help_immediate_before_changed",
                    "help_transport_calls": 0, "committed_action_count": 0,
                    "effect_reconciliation_required": False, "identical_retry_denied": False,
                    "proposal_frame": str(source.path), "immediate_frame": str(immediate_capture.path)}
        selected = immediate_plan.request_ids[0]
        target_roi = immediate_plan.target_roi
        target_hash = hashlib.sha256(
            immediate_capture.frame[target_roi[1]:target_roi[3],
                                    target_roi[0]:target_roi[2]].tobytes()).hexdigest()
        observation = Observation(
            frame_sha256=immediate_capture.sha256,
            capture_completed_monotonic=immediate_capture.captured_monotonic,
            runtime_profile_id=PROFILE_ID, width=800, height=1280,
            valid_png=True, corrupt=False, black=False, source_state=SOURCE_STATE,
            overlay_state="none", target_identity=INDIVIDUAL_TARGET_IDENTITY,
            target_roi=target_roi, recognized=True, control_class=CONTROL_CLASS,
            consequence=CONSEQUENCE, cost_type="none", cost_amount=0, quantity=1,
            expected_postcondition=POSTCONDITION,
            evidence_refs=(str(immediate_capture.path),),
            critical_roi_hashes=(('alliance-help-target', target_hash),),
            ocr_result_frame_sha256=immediate_capture.sha256,
            ocr_result_capture_completed_monotonic=immediate_capture.captured_monotonic,
            source_family='alliance_help', target_isolated=True,
            package_foreground=self.runtime.measure_foreground_package() == 'com.global.ztmslg')
        base = {"status": "blocked", "action_key": action_key,
                "request_ordinal": ordinal,
                "selected_request_sha256": hashlib.sha256(selected.encode("utf-8")).hexdigest(),
                "immediate_daily_alliance_coin_balance": immediate.daily_alliance_coin_balance,
                "immediate_daily_alliance_coin_limit": immediate.daily_alliance_coin_limit,
                "help_transport_calls": 0, "committed_action_count": 0,
                "verified_request_count": 0, "effect_reconciliation_required": False,
                "identical_retry_denied": False}
        occurrence_digest = hashlib.sha256(occurrence_key.encode('utf-8')).hexdigest()
        policy_request = PolicyRequest(
            action_id=f'alliance-help-{ordinal:02d}-{occurrence_digest[:8]}-{immediate_capture.sha256[:8]}',
            action_key=action_key, task_id=FLOW_ID, task_mode='supervised_validation',
            semantic_action=SEMANTIC_ACTION, expected_runtime_profile_id=PROFILE_ID,
            observation=observation, monotonic_now=self.monotonic_clock(),
            observation_max_age_seconds=2.0, dispatch_max_age_seconds=2.0,
            lease_owner=self.session.owner, lease_valid=self.store.lease_valid_for(
                self.session.owner, self.wall_clock()), unresolved_action=self.store.has_action_block(),
            duplicate_action_key=self.store.action_key_exists(action_key), game_day_id=self.identity.reset_id,
            action_class=ActionClass.ZERO_COST_CONSEQUENTIAL, action_kind=SEMANTIC_ACTION,
            subject=INDIVIDUAL_TARGET_IDENTITY, maximum_cost=0, free_only=True,
            semantic_preconditions=(
                'alliance_help_product=alliance_help',
                f'alliance_help_product_revision={PRODUCT_REVISION}',
                'alliance_help_quota=10',
                f'alliance_help_request_reset={self.identity.reset_id}',
                f'alliance_help_request_ordinal={ordinal}',
                'alliance_help_target_variant=individual',
                'alliance_help_exact_free_label=Help',
                'alliance_help_complete_request_transition_required'),
            semantic_postconditions=(POSTCONDITION,), runtime_session_id=str(self.runtime.session))
        dispatch_before_capture = self.runtime.capture(
            f'alliance-help-final-immediate-before-{ordinal:02d}')
        dispatch_help_observation = _current_observation(
            self.runtime, dispatch_before_capture, observer=self.observer,
            now=self.monotonic_clock())
        dispatch_plan = choose_help_action(dispatch_help_observation, remaining)
        if (dispatch_plan.action is not HelpAction.INDIVIDUAL
                or dispatch_plan.request_ids != immediate_plan.request_ids
                or dispatch_plan.target_roi != immediate_plan.target_roi
                or dispatch_help_observation.daily_alliance_coin_balance
                    != immediate.daily_alliance_coin_balance
                or dispatch_help_observation.daily_alliance_coin_limit
                    != immediate.daily_alliance_coin_limit):
            return {**base, "reason": "help_final_immediate_before_changed",
                    "proposal_frame": str(source.path),
                    "immediate_before_frame": str(dispatch_before_capture.path),
                    "immediate_before_sha256": dispatch_before_capture.sha256}
        target_x0, target_y0, target_x1, target_y1 = dispatch_plan.target_roi
        dispatch_target_hash = hashlib.sha256(
            dispatch_before_capture.frame[target_y0:target_y1,
                target_x0:target_x1].tobytes()).hexdigest()
        dispatch_observation = Observation(
            frame_sha256=dispatch_before_capture.sha256,
            capture_completed_monotonic=dispatch_before_capture.captured_monotonic,
            runtime_profile_id=PROFILE_ID, width=800, height=1280,
            valid_png=True, corrupt=False, black=False, source_state=SOURCE_STATE,
            overlay_state="none", target_identity=INDIVIDUAL_TARGET_IDENTITY,
            target_roi=dispatch_plan.target_roi, recognized=True, control_class=CONTROL_CLASS,
            consequence=CONSEQUENCE, cost_type="none", cost_amount=0, quantity=1,
            expected_postcondition=POSTCONDITION,
            evidence_refs=(str(dispatch_before_capture.path),),
            critical_roi_hashes=(('alliance-help-target', dispatch_target_hash),),
            ocr_result_frame_sha256=dispatch_before_capture.sha256,
            ocr_result_capture_completed_monotonic=dispatch_before_capture.captured_monotonic,
            source_family='alliance_help', target_isolated=True,
            package_foreground=self.runtime.measure_foreground_package() == 'com.global.ztmslg')
        capability_request = replace(policy_request, observation=dispatch_observation,
                                     monotonic_now=self.monotonic_clock())
        policy = CentralPolicy({FLOW_ID})
        issued = policy.issue_capability(capability_request)
        self.store.audit(FLOW_ID, "capability_issued", self.wall_clock(), issued.audit, policy_request.action_id)
        if not issued.authorized or issued.capability is None:
            return {**base, "reason": issued.reason_code, "policy_reason": issued.reason_code,
                    "proposal_frame": str(source.path), "immediate_before_frame": str(dispatch_before_capture.path),
                    "immediate_before_sha256": dispatch_before_capture.sha256}

        post: list[Any] = []
        post_semantics: dict[str, HelpObservation] = {}
        recapture_returned = False
        session_capture_returned = False
        transport_calls = 0
        dispatch_input_start: int | None = None
        semantic_success = False
        dispatch_evidence: list[dict[str, Any]] = []

        def recapture():
            nonlocal recapture_returned
            if recapture_returned:
                raise ValueError('Alliance Help immediate-before observation is single-use')
            recapture_returned = True
            self.validate_identity()
            return dispatch_observation

        def single_immediate(label: str):
            nonlocal session_capture_returned
            if not session_capture_returned:
                session_capture_returned = True
                return dispatch_before_capture
            return self.runtime.capture(label)


        def _recognized(captured: Any) -> HelpObservation:
            key = str(captured.path)
            if key not in post_semantics:
                post_semantics[key] = _current_observation(
                    self.runtime, captured, observer=self.observer, now=self.monotonic_clock())
            return post_semantics[key]

        def observed_transport_calls() -> int:
            current = getattr(self.runtime, "input_count", None)
            return int(type(current) is int and dispatch_input_start is not None
                       and current > dispatch_input_start)

        def successor(captured: Any) -> str:
            nonlocal semantic_success
            if not any(item.path == captured.path for item in post):
                post.append(captured)
            if len(post) < 2:
                return 'pending'
            latest = post[-1]
            latest_observation = _recognized(latest)
            for success_frame in post[:-1]:
                success_observation = _recognized(success_frame)
                if verified_request_delta(dispatch_help_observation or immediate, success_observation,
                        plan=immediate_plan, remaining=remaining,
                        transport_calls=observed_transport_calls()) != 1:
                    continue
                stable_ids = {item.request_id for item in latest_observation.requests}
                same_balance = (
                    latest_observation.daily_alliance_coin_balance
                    == success_observation.daily_alliance_coin_balance
                    and latest_observation.daily_alliance_coin_limit
                    == success_observation.daily_alliance_coin_limit)
                if (latest_observation.screen_state == SOURCE_STATE
                        and latest_observation.source_fresh and latest_observation.overlay_clear
                        and selected not in stable_ids and same_balance):
                    semantic_success = True
                    return POSTCONDITION
            return 'pending' if len(post) < 3 else 'unknown'

        def settled_successor():
            time.sleep(self.settle_seconds)
            settled = self.runtime.capture(f'alliance-help-result-settled-{ordinal:02d}-1')
            if successor(settled) == POSTCONDITION:
                return settled
            return self.runtime.capture(f'alliance-help-result-settled-{ordinal:02d}-2')

        def dispatch_help(before: Any) -> None:
            start = self.runtime.input_count
            try:
                self.runtime.tap(before,
                    target_identity=INDIVIDUAL_TARGET_IDENTITY,
                    target_roi=dispatch_plan.target_roi, action_key=action_key,
                    action_class='free_action', consequential=False)
            finally:
                if self.runtime.input_count > start:
                    dispatch_evidence.append({
                        "immediate_before_sha256": before.sha256,
                        "target_identity": INDIVIDUAL_TARGET_IDENTITY,
                        "target_roi": dispatch_plan.target_roi,
                        "action_key": action_key,
                    })

        def transport(_intent: Any):
            nonlocal transport_calls, dispatch_input_start
            self.validate_identity()
            before_inputs = self.runtime.input_count
            dispatch_input_start = before_inputs
            try:
                outcome = self.session.run_action(
                    action_class='free_action', label=f'alliance-help-request-{ordinal:02d}',
                    capture=single_immediate,
                    dispatch=dispatch_help,
                    recognize=lambda after: successor(after),
                    settled_successor=settled_successor, consequence_class=CONSEQUENCE)
            finally:
                transport_calls = int(self.runtime.input_count > before_inputs)
            status = getattr(outcome.status, 'value', outcome.status)
            if status != 'completed':
                return TransportResult(transport_calls == 1, f'BLUESTACKS_HELP_{status}')
            return TransportResult(transport_calls == 1, 'BLUESTACKS_ALLIANCE_HELP_DISPATCHED')

        def post_observe():
            for captured in post:
                observed = _recognized(captured)
                yield Observation(frame_sha256=captured.sha256,
                    capture_completed_monotonic=captured.captured_monotonic,
                    runtime_profile_id=PROFILE_ID, width=800, height=1280,
                    target_identity=INDIVIDUAL_TARGET_IDENTITY,
                    target_roi=dispatch_plan.target_roi,
                    valid_png=True, corrupt=False, black=False,
                    source_state=POSTCONDITION if (
                        semantic_success and captured.path == post[-1].path
                        or verified_request_delta(dispatch_help_observation or immediate, observed,
                            plan=immediate_plan, remaining=remaining,
                            transport_calls=transport_calls) == 1
                    ) else 'UNKNOWN',
                    overlay_state='none' if observed.overlay_clear else 'unknown',
                    recognized=observed.source_fresh and observed.overlay_clear,
                    evidence_refs=(str(captured.path),))

        executor = SafeActionExecutor(self.store, policy, self.session.owner,
            self.monotonic_clock, transport, recapture, post_observe,
            lambda _intent, observed: bool(semantic_success and post
                and observed.capture_completed_monotonic == post[-1].captured_monotonic
                and observed.frame_sha256 == post[-1].sha256),
            wall_clock=self.wall_clock, max_pre_dispatch_attempts=1)
        execution = executor.execute(policy_request, issued.capability)
        result_action = self.store.get_action_by_key(action_key)
        if post and callable(getattr(self.runtime, "reconcile", None)):
            self.runtime.reconcile(action_key,
                "confirmed" if execution.status is ActionStatus.CONFIRMED else "unresolved",
                post[-1], execution.reason)
        verified = execution.status is ActionStatus.CONFIRMED and result_action.get("final_status") == ActionStatus.CONFIRMED.value
        dispatch_capture = dispatch_before_capture or immediate_capture
        dispatch_observation = dispatch_help_observation or immediate
        return {**base,
            "status": "confirmed" if verified else "reconciliation_required" if transport_calls or result_action.get("final_status") in {"input_sent", "unresolved"} else "blocked",
            "reason": execution.reason, "help_transport_calls": transport_calls,
            "help_dispatch_evidence": dispatch_evidence,
            "committed_action_count": 1 if verified else 0,
            "verified_request_count": 1 if verified else 0,
            "effect_reconciliation_required": bool(transport_calls and not verified),
            "identical_retry_denied": bool(not verified
                and (transport_calls or result_action.get("final_status") != "cancelled")),
            "journal_status": result_action.get("final_status"),
            "proposal_frame": str(source.path), "proposal_sha256": source.sha256,
            "immediate_before_frame": str(dispatch_capture.path),
            "immediate_before_sha256": dispatch_capture.sha256,
            "immediate_daily_alliance_coin_balance": dispatch_observation.daily_alliance_coin_balance,
            "immediate_daily_alliance_coin_limit": dispatch_observation.daily_alliance_coin_limit,
            "request_result_frames": [str(frame.path) for frame in post],
            "request_result_evidence": [{"frame_path": str(frame.path),
                "frame_sha256": frame.sha256,
                "screen_state": post_semantics[str(frame.path)].screen_state,
                "source_fresh": post_semantics[str(frame.path)].source_fresh,
                "overlay_clear": post_semantics[str(frame.path)].overlay_clear,
                "success_message": post_semantics[str(frame.path)].help_success_message,
                "daily_alliance_coin_balance": post_semantics[str(frame.path)].daily_alliance_coin_balance,
                "daily_alliance_coin_limit": post_semantics[str(frame.path)].daily_alliance_coin_limit,
                "selected_request_absent": selected not in {
                    request.request_id for request in post_semantics[str(frame.path)].requests}}
                for frame in post]}


def _return_home(*, session: Any, runtime: Any, settle_seconds: float,
                 monotonic_clock: Callable[[], float] = time.monotonic) -> tuple[Any | None, list[str]]:
    current = session.observe(runtime.capture, label="alliance-help-return-source")
    route: list[str] = []
    for ordinal in range(2):
        if _home(current.frame):
            return current, route
        if _alliance_menu(current.frame):
            name = "back-alliance-home"
        else:
            help_screen = recognize_help_screen(current.frame,
                captured_at=current.captured_monotonic, frame_sha256=current.sha256,
                now=monotonic_clock())
            if help_screen.screen_state != SOURCE_STATE:
                return None, route
            name = "back-speedup-help"
        # Exact successors only: an unchanged screen is unknown and is never tapped again.
        def successor(after: Any) -> bool:
            return _home(after.frame) or (
                name == "back-speedup-help" and _alliance_menu(after.frame)
            )

        def bind_back(before: Any):
            expected_context = (
                ROUTE_CONTEXT_ALLIANCE_MENU
                if name == "back-alliance-home"
                else ROUTE_CONTEXT_SPEEDUP_HELP
            )
            if _route_context(before, now=monotonic_clock()) != expected_context:
                return None
            target = _back_target(before.frame)
            return ("alliance-help-back", target) if target is not None else None
        after, status = _navigation(session=session, runtime=runtime, name=name,
            binder=bind_back, successor=successor, settle_seconds=settle_seconds)
        if status != "completed" or after is None:
            return None, route
        current = after
        route.append(name)
    return (current, route) if _home(current.frame) else (None, route)


def _write_result(session: Any, result: Mapping[str, Any]) -> None:
    directory = Path(getattr(session, "session_directory", ""))
    if not directory.is_dir():
        raise RuntimeError("Alliance Help requires the canonical native session directory")
    path = directory / "alliance-help-result.json"
    path.write_text(json.dumps(dict(result), sort_keys=True, indent=2) + "\n", encoding="utf-8")


def run_alliance_help(
    *, session: Any, runtime: Any, store: Any, identity: Any,
    validate_identity: Callable[[], None], occurrence_key: str,
    settle_seconds: float = 1.0, monotonic_clock: Callable[[], float] = time.monotonic,
    utc_clock: Callable[[], float] = time.time, observer=recognize_help_screen,
    startup_recovery: Mapping[str, Any] | None = None,
    scheduler_reset_id: str | None = None,
) -> dict[str, Any]:
    """Execute one canonical occurrence and preserve confirmed request progress on every stop."""
    if (type(occurrence_key) is not str or not occurrence_key.strip()
            or occurrence_key != occurrence_key.strip()):
        raise ValueError("Alliance Help requires the canonical service occurrence key")
    validate_identity()
    initial = session.observe(runtime.capture, label="alliance-help-initial-home")
    result: dict[str, Any] = {
        "status": "blocked", "reason": "alliance_help_home_source_unproven",
        "flow_id": FLOW_ID, "task_id": PRODUCT_ID, "product_id": PRODUCT_ID,
        "product_revision": PRODUCT_REVISION, "runtime_profile_id": PROFILE_ID,
        "account_id": identity.account_id, "server_id": identity.server_id,
        "reset_id": identity.reset_id, "scheduler_reset_id": scheduler_reset_id,
        "backend_identity": {
            "runtime_scope": identity.runtime_scope,
            "account_id": identity.account_id, "server_id": identity.server_id,
            "reset_id": identity.reset_id, "assurance": identity.assurance.value,
            "evidence_refs": list(identity.evidence_refs),
            "observed_utc": identity.observed_utc, "expires_utc": identity.expires_utc,
            "runtime_binding_digest": identity.runtime_binding_digest,
            "reset_start_utc": identity.reset_start_utc,
            "reset_deadline_utc": identity.reset_deadline_utc,
        },
        "occurrence_key": occurrence_key,
        "source_frame": {"frame_path": str(initial.path), "frame_sha256": initial.sha256},
        "help_transport_calls": 0, "committed_action_count": 0,
        "verified_request_count": 0, "confirmed_request_count": 0,
        "accounting_verified": False, "terminal_home_verified": False,
        "effect_reconciliation_required": False, "identical_retry_denied": False,
        "no_work": False, "terminal_home_frame": None,
    }
    if startup_recovery is not None:
        result["startup_recovery"] = dict(startup_recovery)
    try:
        count, count_ok, count_reason, confirmed_records = _durable_request_count(store, identity)
    except Exception as exc:
        result.update(status="reconciliation_required" if store.has_action_block() else "blocked",
                      reason=f"{type(exc).__name__}:{exc}",
                      effect_reconciliation_required=store.has_action_block(),
                      identical_retry_denied=store.has_action_block())
        _write_result(session, result)
        return result
    result.update(confirmed_request_count=count, confirmed_request_records=confirmed_records,
                  verified_request_count=count, committed_action_count=count)
    if not count_ok:
        result.update(status="reconciliation_required", reason=count_reason,
                      effect_reconciliation_required=True, identical_retry_denied=True)
    entry_home = initial if _home(initial.frame) else None
    if entry_home is None:
        start_context = _route_context(initial, now=monotonic_clock())
        if start_context is None:
            result["reason"] = "alliance_help_requires_current_clean_home"
            _write_result(session, result)
            return result
        # Existing route-owned Back navigation from a positively recognized Alliance/Help
        # context to a fresh Home; any unknown successor stops without a repeated input.
        recovery: dict[str, Any] = {"source_context": start_context, "verified_navigation": []}
        try:
            home, recovery["verified_navigation"] = _return_home(session=session, runtime=runtime,
                settle_seconds=settle_seconds, monotonic_clock=monotonic_clock)
            entry_home = home if home is not None and _home(home.frame) else None
        except Exception as exc:
            recovery["error"] = f"{type(exc).__name__}:{exc}"
        recovery["home_verified"] = entry_home is not None
        recovery["home_frame"] = ({"frame_path": str(entry_home.path), "frame_sha256": entry_home.sha256}
                                  if entry_home is not None else None)
        result["route_context_recovery"] = recovery
    try:
        if not count_ok:
            result.update(status="reconciliation_required", reason=count_reason,
                          confirmed_request_count=count,
                          effect_reconciliation_required=True, identical_retry_denied=True)
        elif entry_home is None:
            result["reason"] = "alliance_help_route_context_recovery_unproven"
        elif count == DAILY_REQUEST_LIMIT:
            result.update(status="complete_for_reset", reason="ten_requests_already_confirmed",
                          confirmed_request_count=count, no_work=True)
        else:
            current, nav_status = _navigation(session=session, runtime=runtime,
                name="open-alliance", binder=lambda before: (
                    ("home-nav-alliance", roi) if (roi := _home_alliance_target(before.frame)) else None),
                successor=lambda after: _alliance_menu(after.frame), settle_seconds=settle_seconds)
            if nav_status != "completed" or current is None:
                result["reason"] = "alliance_menu_successor_unproven"
            else:
                current, nav_status = _navigation(session=session, runtime=runtime,
                    name="open-speedup-help", binder=lambda before: (
                        ("alliance-menu-help", roi) if _alliance_menu(before.frame)
                        and (roi := _menu_help_target(before.frame)) is not None else None),
                    successor=lambda after: recognize_help_screen(after.frame,
                        captured_at=after.captured_monotonic, frame_sha256=after.sha256,
                        now=monotonic_clock()).screen_state == SOURCE_STATE,
                    settle_seconds=settle_seconds)
                if nav_status != "completed" or current is None:
                    result["reason"] = "speedup_help_successor_unproven"
                else:
                    action = AllianceHelpActionBoundary(session=session, runtime=runtime,
                        store=store, identity=identity, validate_identity=validate_identity,
                        settle_seconds=settle_seconds, monotonic_clock=monotonic_clock,
                        wall_clock=utc_clock, observer=observer)
                    reason = None
                    status = "deferred"
                    while count < DAILY_REQUEST_LIMIT:
                        validate_identity()
                        if store.has_action_block():
                            status, reason = "reconciliation_required", "canonical_unresolved_action"
                            result.update(effect_reconciliation_required=True, identical_retry_denied=True)
                            break
                        ordinal = count + 1
                        one = action.execute_one(ordinal=ordinal,
                            remaining=DAILY_REQUEST_LIMIT - count, occurrence_key=occurrence_key)
                        action = AllianceHelpActionBoundary(session=session, runtime=runtime,
                            store=store, identity=identity, validate_identity=validate_identity,
                            settle_seconds=settle_seconds, monotonic_clock=monotonic_clock,
                            wall_clock=utc_clock, observer=observer)
                        result["help_transport_calls"] += int(one.get("help_transport_calls", 0))
                        result["committed_action_count"] += int(one.get("committed_action_count", 0))
                        result["verified_request_count"] += int(one.get("verified_request_count", 0))
                        result.setdefault("request_actions", []).append(one)
                        if one.get("status") == "confirmed":
                            count += one["verified_request_count"]
                            if count > DAILY_REQUEST_LIMIT:
                                status, reason = "reconciliation_required", "request_quota_overrun"
                                result.update(effect_reconciliation_required=True, identical_retry_denied=True)
                                break
                            status, reason = "complete_for_reset", "ten_free_requests_confirmed"
                            if count == DAILY_REQUEST_LIMIT:
                                break
                            continue
                        if one.get("status") == "deferred":
                            status, reason = "deferred", str(one.get("reason"))
                            result["no_work"] = True
                            no_work = one.get("no_work_evidence")
                            if isinstance(no_work, Mapping):
                                result["no_work_evidence"] = dict(no_work)
                        elif one.get("status") == "reconciliation_required":
                            status, reason = "reconciliation_required", str(one.get("reason"))
                            result.update(effect_reconciliation_required=bool(one.get("effect_reconciliation_required")),
                                          identical_retry_denied=True)
                        else:
                            status, reason = "blocked", str(one.get("reason"))
                        break
                    result.update(status=status, reason=reason,
                                  confirmed_request_count=count)
    except Exception as exc:
        result.update(status="reconciliation_required" if store.has_action_block() else "blocked",
                      reason=f"{type(exc).__name__}:{exc}",
                      effect_reconciliation_required=store.has_action_block(),
                      identical_retry_denied=store.has_action_block())
        count, count_ok, count_reason, confirmed_records = _durable_request_count(store, identity)
        result["confirmed_request_count"] = count if count_ok else result.get("confirmed_request_count", 0)
        if count_reason and not result.get("reason"):
            result["reason"] = count_reason

    result["completed_at_utc"] = utc_clock()
    result["time_basis"] = "utc"
    result["max_inputs"] = MAX_INPUTS
    result["max_actions"] = MAX_ACTIONS
    native_calls = getattr(runtime, "frame_actions", None)
    dispatch_evidence = [
        dispatch for action in result.get("request_actions", ())
        for dispatch in action.get("help_dispatch_evidence", ())
    ]
    dispatch_accounting_valid = isinstance(native_calls, set) and all(
        isinstance(item, tuple) and len(item) == 3
        and isinstance(item[2], tuple) and len(item[2]) == 4
        for item in native_calls)
    if dispatch_accounting_valid:
        help_dispatches = {item for item in native_calls
            if item[1] in {INDIVIDUAL_TARGET_IDENTITY, HELP_ALL_TARGET_IDENTITY}}
        dispatch_accounting_valid = (
            len(dispatch_evidence) == len(help_dispatches)
            and {(item["immediate_before_sha256"], item["target_identity"], item["target_roi"])
                 for item in dispatch_evidence} == help_dispatches)
        measured_help_calls = len(help_dispatches)
        result["help_dispatch_evidence"] = dispatch_evidence
        result["help_transport_calls"] = measured_help_calls
    else:
        result["help_dispatch_evidence"] = []
    if entry_home is None:
        # Recovery Back successor was unknown: never repeat it as a terminal return.
        result["verified_navigation"] = []
    elif not store.has_action_block():
        home, back_steps = _return_home(session=session, runtime=runtime,
            settle_seconds=settle_seconds, monotonic_clock=monotonic_clock)
        result["verified_navigation"] = back_steps
        if home is not None and _home(home.frame):
            result["terminal_home_verified"] = True
            result["terminal_home_frame"] = {"frame_path": str(home.path), "frame_sha256": home.sha256}
    else:
        try:
            home, back_steps = _return_home(session=session, runtime=runtime,
                settle_seconds=settle_seconds, monotonic_clock=monotonic_clock)
            result["verified_navigation"] = back_steps
            if home is not None and _home(home.frame):
                result["terminal_home_verified"] = True
                result["terminal_home_frame"] = {"frame_path": str(home.path), "frame_sha256": home.sha256}
        except Exception as exc:
            result["terminal_home_error"] = f"{type(exc).__name__}:{exc}"
    input_count = getattr(runtime, "input_count", -1)
    session_count = getattr(session, "input_count", -2)
    result["accounting_verified"] = bool(dispatch_accounting_valid
        and type(input_count) is int and type(session_count) is int
        and input_count == session_count and 0 <= input_count <= MAX_INPUTS
        and len(result["help_dispatch_evidence"]) == result["help_transport_calls"]
        and result["help_transport_calls"] <= MAX_ACTIONS)
    result["input_count"] = result["total_input_count"] = input_count
    if result.get("confirmed_request_count") == DAILY_REQUEST_LIMIT and result.get("status") == "complete_for_reset":
        if not result.get("terminal_home_verified"):
            result.update(status="reconciliation_required", reason="ten_requests_confirmed_but_home_not_proven",
                          effect_reconciliation_required=bool(result.get("help_transport_calls")),
                          identical_retry_denied=bool(result.get("help_transport_calls")))
    elif result.get("status") == "deferred" and not result.get("terminal_home_verified"):
        result.update(status="blocked", reason="safe_stop_home_not_proven")
    if not result.get("accounting_verified"):
        result.update(status="reconciliation_required" if result.get("help_transport_calls") else "blocked",
                      reason="alliance_help_input_accounting_mismatch",
                      effect_reconciliation_required=bool(result.get("help_transport_calls")),
                      identical_retry_denied=bool(result.get("help_transport_calls")))
    durable_count, durable_ok, durable_reason, confirmed_records = _durable_request_count(store, identity)
    result["confirmed_request_count"] = durable_count
    result["confirmed_request_records"] = confirmed_records
    result["verified_request_count"] = durable_count
    result["committed_action_count"] = durable_count
    if not durable_ok:
        result.update(status="reconciliation_required", reason=durable_reason,
                      effect_reconciliation_required=True, identical_retry_denied=True)
    confirmed_this_run = sum(
        isinstance(item, Mapping) and item.get("status") == "confirmed"
        for item in result.get("request_actions", ()))
    if result["help_transport_calls"] > confirmed_this_run:
        result.update(status="reconciliation_required",
                      reason="transported_help_request_result_unresolved",
                      effect_reconciliation_required=True, identical_retry_denied=True)
    _write_result(session, result)
    return result


def _service_driver(context: Any, arguments: Mapping[str, object]) -> Mapping[str, Any]:
    """Bind the pure route to the already leased native session and canonical store."""
    from datetime import datetime, timezone
    from tasks.runtime_identity import derive_resource_runtime_identity, resource_fixed_runtime_binding

    if not isinstance(arguments, Mapping) or arguments:
        raise ValueError("Alliance Help has no runtime controls or caller-provided arguments")
    scheduler_identity = context.identity
    if (scheduler_identity.task_id != PRODUCT_ID
            or context.flow_id != FLOW_ID or context.product_id != PRODUCT_ID
            or context.product_revision != PRODUCT_REVISION):
        raise RuntimeError("Alliance Help native binding identity differs from its approved route")
    context.checkpoint()
    context.validate_identity()
    binding = resource_fixed_runtime_binding()
    evidence_refs = (
        "identity-source:fixed-login-slot", "identity-source:static-UTC-reset",
        f"session-owner:{context.owner}", f"session-invocation:{context.invocation_id}",
    )
    evaluated = datetime.fromtimestamp(context.utc_clock(), timezone.utc)
    identity = derive_resource_runtime_identity(binding, evaluated, evidence_refs=evidence_refs)
    if (identity.account_id, identity.server_id) != (
            scheduler_identity.account_id, scheduler_identity.server_id):
        raise RuntimeError("Alliance Help fixed BlueStacks account/server differs from the claimed occurrence")

    def validate_identity() -> None:
        context.checkpoint()
        context.validate_identity()
        current_binding = resource_fixed_runtime_binding()
        evaluated_now = datetime.fromtimestamp(context.utc_clock(), timezone.utc)
        current = derive_resource_runtime_identity(current_binding, evaluated_now,
            evidence_refs=evidence_refs)
        if (current_binding != binding
                or (current.account_id, current.server_id, current.reset_id, current.runtime_scope,
                    current.runtime_binding_digest) != (
                    identity.account_id, identity.server_id, identity.reset_id, identity.runtime_scope,
                    identity.runtime_binding_digest)):
            raise RuntimeError("Alliance Help fixed runtime identity changed during the native occurrence")

    startup_key = hashlib.sha256(
        f"{FLOW_ID}\0{identity.reset_id}\0{context.occurrence_key}".encode("utf-8")
    ).hexdigest()
    initial = context.initial_frame
    start_context = None if _home(initial.frame) else _route_context(initial, now=context.monotonic_clock())
    if start_context is not None:
        # Route-owned Alliance/Help context with a positively clear overlay: bind it without
        # startup input; run_alliance_help returns it to fresh Home via the bound Back target.
        context.bind_initial_observation(initial, extra={"alliance_help_start_context": start_context})
        startup_evidence = {
            "source_context": start_context, "reason": "route_context_bound_without_startup_input",
            "input_count": 0, "accounting_verified": True, "resume_ready": True,
            "dismissed": None, "popup_absent": None, "steps": [], "settled_reference": None,
        }
    else:
        startup = context.prepare_startup(
            source_context="alliance_help",
            recognize_successor=lambda captured: _home(captured.frame),
            action_key=f"{FLOW_ID}:startup:{startup_key}",
            settle_seconds=context.settle_seconds,
        )
        startup_evidence = {
            "source_context": startup.source_context, "reason": startup.reason,
            "input_count": startup.input_count, "accounting_verified": startup.accounting_verified,
            "resume_ready": startup.resume_ready, "dismissed": startup.dismissed,
            "popup_absent": startup.popup_absent, "steps": list(startup.steps),
            "settled_reference": startup.settled_reference.to_mapping()
            if startup.settled_reference is not None else None,
        }
    return run_alliance_help(
        session=context.session, runtime=context.runtime, store=context.action_store,
        identity=identity, validate_identity=validate_identity,
        occurrence_key=context.occurrence_key, scheduler_reset_id=scheduler_identity.reset_id,
        settle_seconds=context.settle_seconds, monotonic_clock=context.monotonic_clock,
        utc_clock=context.utc_clock, startup_recovery=startup_evidence,
    )


def create_service_binding(make_native_route_binding: Callable[..., Any]) -> Any:
    """Create a device-free binding through the controller-owned native lifecycle."""
    if not callable(make_native_route_binding):
        raise TypeError("Alliance Help requires the controller's native route binding builder")
    return make_native_route_binding(
        flow_id=FLOW_ID, product_id=PRODUCT_ID, product_revision=PRODUCT_REVISION,
        runtime_profile_id=PROFILE_ID,
        owner="automation-service:alliance-help", workflow="alliance-help-native",
        max_inputs=MAX_INPUTS, max_actions=MAX_ACTIONS,
        driver=_service_driver, lease_seconds=3600.0,
    )
