#!/usr/bin/env python3
"""Bounded supervised Personal Might Praise-to-Claim adapter.

All live input goes through SafeActionExecutor.  Recognition is local, semantic, and fail-closed;
there is no generic tap endpoint, transport retry, or unattended loop.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPTS_ROOT = Path(__file__).resolve().parent
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from safe_action_core import (  # noqa: E402
    ActionClass,
    CentralPolicy,
    Observation,
    PolicyRequest,
    SafeActionExecutor,
    SafetyStore,
    TransportResult,
)
from tasks.daily_quest import (  # noqa: E402
    DailyQuestClaimObservation,
    PersonalMightPraiseHandler,
    PraiseObservation,
    claim_authorizeable,
    claim_postcondition_verified,
)
from tasks.profile import (  # noqa: E402
    HOME_MORE,
    MIGHT_PRAISE_ACTION,
    PERSONAL_MIGHT_BACK,
    PERSONAL_MIGHT_CHECK,
    PERSONAL_MIGHT_LEADERBOARD,
    PERSONAL_MIGHT_ROW,
    RANKINGS_BACK,
    RANKINGS_ENTRY,
    RESET_POPUP_CLOSE,
)
from mvp_quest_to_claim import ADBTransport, load_frame  # noqa: E402
from navigation_recognition import recognize_daily_selected, recognize_home_quest, recognize_local_state, similarity  # noqa: E402
from daily_quest_bootstrap import valid_png_frame  # noqa: E402


PROFILE_ID = "pns-blissos-poc-virgl-800x1280-v1"
TASK_ID = "MVP-QUEST-TO-CLAIM"
FRAME_SIZE = (1280, 800)
COORDINATE_SPACE = "FULL_FRAME_800X1280"
OBJECTIVE = "Praise 1x in Personal Might rank"
OBJECTIVE_ALIASES = ("Praise 1x in Personal Might rank", "Personal Might praise")
MIGHT_REGION = (300, 0, 800, 500)
HOME_MORE_REGION = HOME_MORE.roi
RANKINGS_REGION = RANKINGS_ENTRY.roi
PERSONAL_ROW_REGION = PERSONAL_MIGHT_ROW.roi
CHECK_REGION = PERSONAL_MIGHT_CHECK.roi
LEADERBOARD_REGION = PERSONAL_MIGHT_LEADERBOARD.roi
PRAISE_REGION = MIGHT_PRAISE_ACTION.roi
BACK_REGION = PERSONAL_MIGHT_BACK.roi
RESET_POPUP_CLOSE_REGION = RESET_POPUP_CLOSE.roi
VIP_POPUP_TITLE_REGION = (260, 390, 540, 440)
VIP_POPUP_BODY_REGION = (120, 480, 680, 720)
VIP_POPUP_PANEL_REGION = (40, 370, 600, 890)
OLD_INVALID_CLOSE_POINT = (320, 650)
VIP_CLOSE_CENTER_Y_RANGE = (780, 830)
VIP_CLOSE_INTERIOR_MARGIN = 12
MAX_VIP_POPUP_INPUTS = 1
CLAIM_CONTROL_RE = re.compile(r"\bclaim\b", re.IGNORECASE)
PROGRESS_RE = re.compile(r"\b(\d+)\s*/\s*(\d+)\b")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def crop(frame: np.ndarray, roi: tuple[int, int, int, int]) -> np.ndarray:
    x0, y0, x1, y1 = roi
    return frame[y0:y1, x0:x1]


def normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def translate_crop_bounds(
    local_bounds: tuple[int, int, int, int],
    crop_roi: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    """Translate crop-local OCR geometry into full-frame coordinates."""
    lx0, ly0, lx1, ly1 = local_bounds
    cx0, cy0, _cx1, _cy1 = crop_roi
    return cx0 + lx0, cy0 + ly0, cx0 + lx1, cy0 + ly1


def point_inside(
    bounds: tuple[int, int, int, int],
    point: tuple[int, int],
    *,
    margin: int = 0,
) -> bool:
    x0, y0, x1, y1 = bounds
    x, y = point
    return x0 + margin <= x <= x1 - margin and y0 + margin <= y <= y1 - margin


def ocr_lines(frame: np.ndarray, roi: tuple[int, int, int, int] = (0, 0, 800, 1280)) -> list[dict[str, Any]]:
    """Return OCR lines with absolute bounds, retaining local geometry."""
    x0, y0, x1, y1 = roi
    image = crop(frame, roi)
    enlarged = cv2.resize(image, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
    data = pytesseract.image_to_data(enlarged, config="--psm 6", output_type=Output.DICT)
    grouped: dict[tuple[int, int, int], dict[str, Any]] = {}
    for i, raw in enumerate(data["text"]):
        text = normalized(raw)
        if not text:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        left = x0 + int(data["left"][i] / 2.5)
        top = y0 + int(data["top"][i] / 2.5)
        right = left + int(data["width"][i] / 2.5)
        bottom = top + int(data["height"][i] / 2.5)
        item = grouped.setdefault(key, {"text": [], "bounds": [left, top, right, bottom]})
        item["text"].append(text)
        item["bounds"] = [
            min(item["bounds"][0], left),
            min(item["bounds"][1], top),
            max(item["bounds"][2], right),
            max(item["bounds"][3], bottom),
        ]
    return [
        {"text": normalized(" ".join(item["text"])), "bounds": tuple(item["bounds"])}
        for item in grouped.values()
    ]


def find_phrase(lines: list[dict[str, Any]], phrases: Iterable[str]) -> Optional[dict[str, Any]]:
    phrases = tuple(normalized(item) for item in phrases)
    for line in lines:
        text = line["text"]
        if any(phrase in text for phrase in phrases):
            return line
    return None


def parse_progress(text: str) -> Optional[tuple[int, int]]:
    match = PROGRESS_RE.search(text)
    if not match:
        return None
    current, required = (int(value) for value in match.groups())
    return (current, required) if required > 0 and 0 <= current <= required else None


def frame_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _observation(
    *,
    path: Path,
    state: str,
    target_identity: Optional[str],
    target_roi: Optional[tuple[int, int, int, int]],
    expected_postcondition: str,
    consequence: str,
    action_class: ActionClass,
    control_class: Optional[str] = None,
    recognized: bool = True,
    overlay_state: str = "none_observed",
    critical_rois: Iterable[tuple[str, tuple[int, int, int, int]]] = (),
) -> Observation:
    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None or frame.shape != (1280, 800, 3):
        raise ValueError("live frame is not locked 800x1280")
    captured = time.monotonic()
    hashes = tuple(
        (name, hashlib.sha256(crop(frame, roi).tobytes()).hexdigest())
        for name, roi in critical_rois
    )
    digest = frame_hash(path)
    return Observation(
        frame_sha256=digest,
        capture_completed_monotonic=captured,
        runtime_profile_id=PROFILE_ID,
        width=800,
        height=1280,
        valid_png=True,
        corrupt=False,
        black=False,
        source_state=state,
        overlay_state=overlay_state if recognized else "unknown",
        target_identity=target_identity,
        target_roi=target_roi,
        recognized=recognized,
        control_class=control_class,
        consequence=consequence,
        cost_type="none",
        cost_amount=0,
        quantity=1,
        expected_postcondition=expected_postcondition,
        evidence_refs=(str(path),),
        critical_roi_hashes=hashes,
        ocr_result_frame_sha256=digest,
        ocr_result_capture_completed_monotonic=captured,
    )


def recognize_route(frame: np.ndarray, state: str) -> dict[str, Any]:
    """Recognize one route source and its locally associated next control."""
    lines = ocr_lines(frame)
    all_text = " ".join(item["text"] for item in lines)
    if state == "HOME_BASE":
        item = find_phrase(lines, ("more",))
        return {"state": "HOME_BASE", "recognized": item is not None, "target": item, "target_id": "home-more-navigation"}
    if state == "MORE":
        item = find_phrase(lines, ("rankings", "ranking"))
        return {"state": "MORE", "recognized": item is not None, "target": item, "target_id": "rankings-entry"}
    if state == "RANKINGS":
        item = find_phrase(lines, ("personal might rank", "personal might"))
        return {"state": "RANKINGS", "recognized": item is not None, "target": item, "target_id": "personal-might-rank-row"}
    if state == "PERSONAL_MIGHT_RANK":
        item = find_phrase(lines, ("check",))
        personal = find_phrase(lines, ("personal might", "might rank"))
        associated = bool(item and personal and abs(item["bounds"][1] - personal["bounds"][1]) < 90)
        return {"state": state, "recognized": associated, "target": item if associated else None, "target_id": "personal-might-rank-check"}
    if state == "PERSONAL_MIGHT_LEADERBOARD":
        leaderboard = find_phrase(lines, ("personal might", "might"))
        praise = find_phrase(lines, ("praise", "thumb"))
        top_lines = [item for item in lines if item["bounds"][1] < 500]
        text = " ".join(item["text"] for item in top_lines)
        identity = bool(leaderboard and ("might" in text or "power" in text))
        praise_ok = bool(praise and praise["bounds"][0] >= 500)
        cooldown = any(token in all_text for token in ("already praised", "praised today", "cooldown"))
        return {
            "state": state,
            "recognized": identity,
            "leaderboard_identity": identity,
            "might_region_identity": identity and bool(top_lines),
            "target": praise if praise_ok else None,
            "target_id": "personal-might-praise" if praise_ok else "",
            "already_praised": cooldown,
            "cooldown_active": cooldown,
            "praise_disabled": identity and not praise_ok and cooldown,
        }
    if state in {"RANKINGS_BACK", "PERSONAL_MIGHT_BACK", "ALLIANCE_BACK"}:
        item = find_phrase(lines, ("back",))
        identity = (
            state != "ALLIANCE_BACK"
            or "speedup help" in all_text
            or ("help" in all_text and "request" in all_text)
        )
        return {
            "state": state,
            "recognized": bool(item and identity),
            "target": item,
            "target_id": "standard-game-back-arrow",
        }
    raise ValueError("unsupported route source: " + state)


def recognize_home_more(frame: np.ndarray, reference: np.ndarray) -> dict[str, Any]:
    """Bind More to Home/Base plus its fixed local template ROI."""
    home = recognize_home_quest(frame, reference)
    score = similarity(crop(frame, HOME_MORE_REGION), crop(reference, HOME_MORE_REGION))
    return {
        "recognized": bool(home.recognized and score >= HOME_MORE.threshold),
        "target": {"bounds": HOME_MORE_REGION},
        "target_id": "home-more-navigation",
        "home_recognized": home.recognized,
        "home_detail": home.as_dict(),
        "more_template_score": score,
    }


def recognize_reset_popup(frame: np.ndarray) -> dict[str, Any]:
    """Recognize only the retained VIP Points modal and literal Close button."""
    if frame.shape != (1280, 800, 3):
        return {"recognized": False, "reason": "profile_dimensions_mismatch"}

    title_crop = cv2.resize(crop(frame, VIP_POPUP_TITLE_REGION), None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    title_gray = cv2.cvtColor(title_crop, cv2.COLOR_BGR2GRAY)
    title_binary = cv2.threshold(title_gray, 120, 255, cv2.THRESH_BINARY)[1]
    title_text = normalized(pytesseract.image_to_string(title_binary, config="--psm 7"))
    title_identity = re.sub(r"[^a-z]", "", title_text) in {"getpts", "getpoints"}

    body_crop = cv2.resize(crop(frame, VIP_POPUP_BODY_REGION), None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
    body_text = normalized(pytesseract.image_to_string(body_crop, config="--psm 6"))
    body_identity = bool(
        "log in every day to get vip pt" in body_text
        and ("obtained vip pt" in body_text or "obtaind vip pt" in body_text)
    )

    close_crop = crop(frame, RESET_POPUP_CLOSE_REGION)
    close_enlarged = cv2.resize(close_crop, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    close_text = normalized(pytesseract.image_to_string(close_enlarged, config="--psm 7"))
    literal_close = close_text == "close"

    hsv = cv2.cvtColor(close_crop, cv2.COLOR_BGR2HSV)
    orange = cv2.inRange(hsv, np.array([0, 35, 70], np.uint8), np.array([35, 255, 220], np.uint8))
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(orange)
    candidates = [tuple(int(value) for value in stats[index]) for index in range(1, count) if stats[index, 4] >= 5000]
    component = max(candidates, key=lambda item: item[4], default=None)
    button_bounds = None
    if component:
        left, top, width, height, _area = component
        button_bounds = translate_crop_bounds(
            (left, top, left + width, top + height),
            RESET_POPUP_CLOSE_REGION,
        )

    target_center = (
        ((button_bounds[0] + button_bounds[2]) // 2, (button_bounds[1] + button_bounds[3]) // 2)
        if button_bounds else None
    )
    geometry_valid = bool(
        button_bounds
        and 250 <= button_bounds[0] <= 300
        and 750 <= button_bounds[1] <= 790
        and 500 <= button_bounds[2] <= 550
        and 830 <= button_bounds[3] <= 870
        and button_bounds[1] > 740
        and button_bounds[3] < 880
        and target_center
        and VIP_CLOSE_CENTER_Y_RANGE[0] <= target_center[1] <= VIP_CLOSE_CENTER_Y_RANGE[1]
        and point_inside(button_bounds, target_center, margin=VIP_CLOSE_INTERIOR_MARGIN)
        and not point_inside(button_bounds, OLD_INVALID_CLOSE_POINT)
    )
    panel = crop(frame, VIP_POPUP_PANEL_REGION)
    panel_present = float(panel.mean()) > 20.0
    recognized = bool(title_identity and body_identity and literal_close and geometry_valid and panel_present)
    return {
        "recognized": recognized,
        "popup_identity": "VIP_POINTS_GET_PTS" if recognized else None,
        "title_text": title_text,
        "title_identity": title_identity,
        "body_text": body_text,
        "body_identity": body_identity,
        "matched_close_text": close_text,
        "literal_close": literal_close,
        "target": button_bounds if recognized else None,
        "target_center": target_center if recognized else None,
        "target_identity": "reset-popup-close" if recognized else None,
        "geometry_valid": geometry_valid,
        "panel_present": panel_present,
        "close_region": RESET_POPUP_CLOSE_REGION,
    }


def build_vip_popup_artifact(
    source_path: Path,
    frame: np.ndarray,
    detail: dict[str, Any],
) -> dict[str, Any]:
    bounds = tuple(detail["target"]) if detail.get("target") else ()
    tap = tuple(detail["target_center"]) if detail.get("target_center") else ()
    center_y = tap[1] if tap else None
    artifact = {
        "target_action": "DISMISS_VIP_POINTS_POPUP",
        "target_control": "Close",
        "coordinate_space": COORDINATE_SPACE,
        "source_screenshot": str(source_path),
        "full_frame_dimensions": {"width": int(frame.shape[1]), "height": int(frame.shape[0])},
        "popup_identity": detail.get("popup_identity"),
        "matched_close_text": detail.get("matched_close_text"),
        "detected_button_bounds": list(bounds),
        "proposed_tap": list(tap),
        "target_center_y": center_y,
        "tap_inside_button_with_margin": bool(bounds and tap and point_inside(bounds, tap, margin=VIP_CLOSE_INTERIOR_MARGIN)),
        "center_y_between_780_and_830": bool(center_y is not None and 780 <= center_y <= 830),
        "old_coordinate_320_650_outside_button": bool(bounds and not point_inside(bounds, OLD_INVALID_CLOSE_POINT)),
        "no_overlap_with_streak_or_points_text": bool(bounds and bounds[1] > 740),
        "recognized_popup": detail,
    }
    artifact["passed"] = bool(
        detail.get("recognized")
        and artifact["full_frame_dimensions"] == {"width": 800, "height": 1280}
        and artifact["popup_identity"] == "VIP_POINTS_GET_PTS"
        and artifact["matched_close_text"] == "close"
        and artifact["tap_inside_button_with_margin"]
        and artifact["center_y_between_780_and_830"]
        and artifact["old_coordinate_320_650_outside_button"]
        and artifact["no_overlap_with_streak_or_points_text"]
    )
    return artifact


def vip_popup_handled(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    recognized_successor: bool,
) -> bool:
    return bool(before.get("recognized") and not after.get("recognized") and recognized_successor)


def roi_from_item(item: Optional[dict[str, Any]], fallback: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    if not item:
        return fallback
    x0, y0, x1, y1 = item["bounds"]
    return (max(0, x0 - 18), max(0, y0 - 18), min(800, x1 + 18), min(1280, y1 + 18))


class LiveAdapter:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.transport = ADBTransport(args.adb, args.serial)
        self.store = SafetyStore(args.database)
        self.evidence = args.evidence
        self.evidence.mkdir(parents=True, exist_ok=True)
        self.counter = 0
        self.owner = args.owner
        self.game_day = args.game_day
        self.input_count = 0
        self.vip_popup_input_count = 0

    def capture(self, label: str) -> tuple[Path, dict[str, Any]]:
        self.counter += 1
        path = self.evidence / f"{label}-{self.counter:03d}.png"
        metadata = self.transport.capture(path)
        valid_png_frame(path)
        return path, metadata

    def _request(
        self,
        action_id: str,
        action_key: str,
        obs: Observation,
        semantic: str,
        action_class: ActionClass,
        consequence: str,
        expected_postcondition: str,
    ) -> PolicyRequest:
        return PolicyRequest(
            action_id=action_id,
            action_key=action_key,
            task_id=TASK_ID,
            task_mode="supervised_validation",
            semantic_action=semantic,
            expected_runtime_profile_id=PROFILE_ID,
            observation=obs,
            monotonic_now=time.monotonic(),
            observation_max_age_seconds=3.0,
            dispatch_max_age_seconds=2.0,
            lease_owner=self.owner,
            lease_valid=True,
            unresolved_action=False,
            duplicate_action_key=False,
            game_day_id=self.game_day,
            action_class=action_class,
            action_kind=semantic,
            subject=semantic,
            maximum_cost=0,
            free_only=True,
            semantic_preconditions=(obs.source_state, obs.target_identity or ""),
            semantic_postconditions=(expected_postcondition,),
        )

    def execute_input(
        self,
        *,
        name: str,
        source_state: str,
        target_identity: str,
        target_roi: tuple[int, int, int, int],
        expected_state: str,
        semantic: str,
        consequence: str,
        action_class: ActionClass,
        initial_path: Path,
        initial: Observation,
        post_reader: Callable[[Path], Observation],
        postcondition: Callable[[Observation], bool],
        transport: Callable[[], TransportResult],
    ) -> Any:
        action_id = f"{name}-{int(time.time())}-{self.counter}"
        action_key = action_id
        pre_counter = {"n": 0}

        def recapture() -> Observation:
            pre_counter["n"] += 1
            path, _ = self.capture(f"{name}-immediate-before-{pre_counter['n']}")
            return post_reader(path)

        def post_observe() -> Iterable[Observation]:
            results = []
            for delay in (0.8, 1.8, 3.0):
                time.sleep(delay)
                path, _ = self.capture(f"{name}-post")
                results.append(post_reader(path))
            return results

        def dispatch(_intent) -> TransportResult:
            self.input_count += 1
            return transport()

        request = self._request(action_id, action_key, initial, semantic, action_class, consequence, expected_state)
        executor = SafeActionExecutor(
            self.store,
            CentralPolicy(),
            self.owner,
            time.monotonic,
            dispatch,
            recapture,
            post_observe,
            lambda _intent, item: postcondition(item),
            wall_clock=time.time,
            max_pre_dispatch_attempts=1,
        )
        result = executor.execute(request)
        write_json(self.evidence / f"{name}-result.json", {
            "result": result.__dict__,
            "action": self.store.get_action(action_id),
            "pre_dispatch_attempts": pre_counter["n"],
        })
        if result.status.value != "confirmed":
            raise RuntimeError(f"{name}: {result.status.value} ({result.reason}); stopping without retry")
        return result

    def dismiss_reset_popup(self, detail: dict[str, Any]) -> Any:
        if self.vip_popup_input_count >= MAX_VIP_POPUP_INPUTS:
            raise RuntimeError("VIP popup input limit reached; refusing second Close tap")
        source_path, _ = self.capture("reset-popup-source")
        image = cv2.imread(str(source_path))
        detail = recognize_reset_popup(image)
        artifact = build_vip_popup_artifact(source_path, image, detail)
        if not artifact["passed"]:
            write_json(self.evidence / "vip-points-popup-pre-dispatch-failed.json", artifact)
            raise RuntimeError("VIP Points popup pre-dispatch artifact failed")
        target_roi = tuple(detail["target"])
        proposed_tap = tuple(detail["target_center"])
        cv2.rectangle(image, (target_roi[0], target_roi[1]), (target_roi[2], target_roi[3]), (0, 255, 0), 3)
        cv2.circle(image, proposed_tap, 8, (0, 0, 255), -1)
        annotated = self.evidence / "vip-points-popup-pre-dispatch-annotated.png"
        cv2.imwrite(str(annotated), image)
        artifact["annotated_screenshot"] = str(annotated)
        artifact["game_day_id"] = self.game_day
        artifact["action_class"] = "navigation_only"
        write_json(self.evidence / "vip-points-popup-pre-dispatch.json", artifact)
        initial = _observation(
            path=source_path,
            state="RESET_POPUP",
            target_identity="reset-popup-close",
            target_roi=target_roi,
            expected_postcondition="HOME_BASE",
            consequence="navigate_zero_cost",
            action_class=ActionClass.NAVIGATION_ONLY,
            overlay_state="known_reset_popup",
            critical_rois=(("popup_close", RESET_POPUP_CLOSE_REGION),),
        )

        def read_post(path: Path) -> Observation:
            frame = load_frame(path)
            home = recognize_home_quest(frame, load_frame(self.args.home_reference))
            popup_after = recognize_reset_popup(frame)
            still_popup = bool(popup_after["recognized"])
            return _observation(
                path=path,
                state="HOME_BASE" if home.recognized else "RESET_POPUP",
                target_identity=None if home.recognized else "reset-popup-close",
                target_roi=None if home.recognized else target_roi,
                expected_postcondition="HOME_BASE",
                consequence="navigate_zero_cost",
                action_class=ActionClass.NAVIGATION_ONLY,
                recognized=home.recognized or still_popup,
                overlay_state="none_observed" if home.recognized else ("known_reset_popup" if still_popup else "unknown"),
                critical_rois=(("popup_close", RESET_POPUP_CLOSE_REGION),),
            )

        def dispatch_close() -> TransportResult:
            if self.vip_popup_input_count >= MAX_VIP_POPUP_INPUTS:
                raise RuntimeError("VIP popup input limit reached during dispatch")
            self.vip_popup_input_count += 1
            return self.transport.tap(*proposed_tap)

        return self.execute_input(
            name="reset-popup-close",
            source_state="RESET_POPUP",
            target_identity="reset-popup-close",
            target_roi=target_roi,
            expected_state="HOME_BASE",
            semantic="DISMISS_RESET_POPUP",
            consequence="navigate_zero_cost",
            action_class=ActionClass.NAVIGATION_ONLY,
            initial_path=source_path,
            initial=initial,
            post_reader=read_post,
            postcondition=lambda item: vip_popup_handled(
                detail,
                recognize_reset_popup(load_frame(Path(item.evidence_refs[0]))),
                recognized_successor=item.recognized and item.source_state == "HOME_BASE",
            ),
            transport=dispatch_close,
        )

    def run_route_step(
        self,
        name: str,
        source_state: str,
        expected_state: str,
        semantic: str,
        fallback_roi: tuple[int, int, int, int],
        *,
        detection_state: Optional[str] = None,
        target_id: Optional[str] = None,
    ) -> Any:
        source_path, _ = self.capture(f"{name}-source")
        source_frame = load_frame(source_path)
        detail = recognize_route(source_frame, detection_state or source_state)
        if source_state == "HOME_BASE" and target_id != "home-quest-entry":
            detail = recognize_home_more(source_frame, load_frame(self.args.home_reference))
        elif target_id == "home-quest-entry":
            home = recognize_home_quest(source_frame, load_frame(self.args.home_reference))
            detail = {
                "recognized": home.recognized,
                "target": {"bounds": home.target_roi} if home.recognized else None,
                "target_id": "home-quest-entry",
            }
        if not detail["recognized"]:
            write_json(self.evidence / f"{name}-blocked.json", {
                "source_state": source_state,
                "expected_state": expected_state,
                "target_id": target_id,
                "detail": detail,
            })
            raise RuntimeError(f"{name}: source or local target not recognized: {detail}")
        target_roi = roi_from_item(detail["target"], fallback_roi)
        target_id = target_id or detail["target_id"]
        initial = _observation(
            path=source_path,
            state=source_state,
            target_identity=target_id,
            target_roi=target_roi,
            expected_postcondition=expected_state,
            consequence="navigate_zero_cost",
            action_class=ActionClass.NAVIGATION_ONLY,
            critical_rois=(("source", fallback_roi), ("target", target_roi)),
        )

        def read_post(path: Path) -> Observation:
            frame = load_frame(path)
            post = recognize_route(frame, expected_state) if expected_state in {
                "MORE", "RANKINGS", "PERSONAL_MIGHT_RANK", "PERSONAL_MIGHT_LEADERBOARD",
                "RANKINGS_BACK", "PERSONAL_MIGHT_BACK",
            } else {"recognized": False}
            if expected_state == "QUEST":
                quest = recognize_local_state(
                    frame,
                    load_frame(self.args.quest_reference),
                    "QUEST",
                    (300, 70, 500, 140),
                    "daily-quest-target",
                )
                post = {"recognized": quest.recognized}
            elif expected_state == "DAILY_QUEST":
                daily = recognize_daily_selected(
                    frame,
                    load_frame(self.args.daily_reference),
                    load_frame(self.args.main_quest_reference),
                )
                post = {"recognized": daily.recognized}
            elif expected_state == "HOME_BASE":
                home = recognize_home_quest(frame, load_frame(self.args.home_reference))
                post = {"recognized": home.recognized}
            successor = bool(post.get("recognized"))
            return _observation(
                path=path,
                state=expected_state if successor else source_state,
                target_identity=None if successor else target_id,
                target_roi=None if successor else target_roi,
                expected_postcondition=expected_state,
                consequence="navigate_zero_cost",
                action_class=ActionClass.NAVIGATION_ONLY,
                recognized=successor,
                critical_rois=(("source", fallback_roi), ("target", target_roi)),
            )

        return self.execute_input(
            name=name,
            source_state=source_state,
            target_identity=target_id,
            target_roi=target_roi,
            expected_state=expected_state,
            semantic=semantic,
            consequence="navigate_zero_cost",
            action_class=ActionClass.NAVIGATION_ONLY,
            initial_path=source_path,
            initial=initial,
            post_reader=read_post,
            postcondition=lambda item: item.recognized and item.source_state == expected_state,
            transport=lambda: self.transport.tap((target_roi[0] + target_roi[2]) // 2, (target_roi[1] + target_roi[3]) // 2),
        )

    def praise(self) -> tuple[Path, PraiseObservation]:
        source_path, _ = self.capture("praise-source")
        frame = load_frame(source_path)
        detail = recognize_route(frame, "PERSONAL_MIGHT_LEADERBOARD")
        progress = (0, 1)
        observation = PraiseObservation(
            screen_state="PERSONAL_MIGHT_LEADERBOARD",
            objective_name=OBJECTIVE,
            current_progress=progress[0],
            required_progress=progress[1],
            target_identity=detail.get("target_id", ""),
            target_roi=PRAISE_REGION,
            leaderboard_identity=bool(detail.get("leaderboard_identity")),
            might_region_identity=bool(detail.get("might_region_identity")),
            target_visible=bool(detail.get("target")),
            zero_cost_evidence=True,
            game_day_id=self.game_day,
            already_praised=bool(detail.get("already_praised")),
            cooldown_active=bool(detail.get("cooldown_active")),
            praise_disabled=bool(detail.get("praise_disabled")),
        )
        if not PersonalMightPraiseHandler.authorizeable(observation):
            if observation.already_praised or observation.cooldown_active:
                return source_path, observation
            raise RuntimeError("Personal Might Praise target/preconditions not recognized")
        artifact = {
            "target_action": "PRAISE_PERSONAL_MIGHT",
            "source_screenshot": str(source_path),
            "personal_might_leaderboard_proof": detail,
            "might_region_bounds": list(MIGHT_REGION),
            "thumbs_up_target_bounds": list(PRAISE_REGION),
            "proposed_tap": [(PRAISE_REGION[0] + PRAISE_REGION[2]) // 2, (PRAISE_REGION[1] + PRAISE_REGION[3]) // 2],
            "tap_inside_praise_control": True,
            "game_day_id": self.game_day,
            "zero_cost_classification": "praise_zero_cost",
            "cooldown_or_already_praised": False,
        }
        annotated = self.evidence / "praise-pre-dispatch-annotated.png"
        image = cv2.imread(str(source_path))
        cv2.rectangle(image, (PRAISE_REGION[0], PRAISE_REGION[1]), (PRAISE_REGION[2], PRAISE_REGION[3]), (0, 255, 0), 3)
        cv2.circle(image, ((PRAISE_REGION[0] + PRAISE_REGION[2]) // 2, (PRAISE_REGION[1] + PRAISE_REGION[3]) // 2), 8, (0, 0, 255), -1)
        cv2.putText(image, "PRAISE_PERSONAL_MIGHT", (PRAISE_REGION[0], max(20, PRAISE_REGION[1] - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.imwrite(str(annotated), image)
        artifact["annotated_screenshot"] = str(annotated)
        write_json(self.evidence / "praise-pre-dispatch.json", artifact)

        def read_post(path: Path) -> Observation:
            post_detail = recognize_route(load_frame(path), "PERSONAL_MIGHT_LEADERBOARD")
            after = PraiseObservation(
                screen_state="PERSONAL_MIGHT_LEADERBOARD",
                objective_name=OBJECTIVE,
                current_progress=0,
                required_progress=1,
                target_identity=post_detail.get("target_id", ""),
                target_roi=PRAISE_REGION,
                leaderboard_identity=bool(post_detail.get("leaderboard_identity")),
                might_region_identity=bool(post_detail.get("might_region_identity")),
                target_visible=bool(post_detail.get("target")),
                zero_cost_evidence=True,
                game_day_id=self.game_day,
                already_praised=bool(post_detail.get("already_praised")),
                cooldown_active=bool(post_detail.get("cooldown_active")),
                praise_disabled=bool(post_detail.get("praise_disabled")),
            )
            return _observation(
                path=path,
                state="PERSONAL_MIGHT_LEADERBOARD",
                target_identity=after.target_identity or None,
                target_roi=PRAISE_REGION if after.target_identity else None,
                expected_postcondition="praise_control_changes_or_disables",
                consequence="praise_zero_cost",
                action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
                recognized=after.leaderboard_identity,
                critical_rois=(("leaderboard", LEADERBOARD_REGION), ("might", MIGHT_REGION), ("praise", PRAISE_REGION)),
            )

        def postcondition(item: Observation) -> bool:
            detail = recognize_route(load_frame(Path(item.evidence_refs[0])), "PERSONAL_MIGHT_LEADERBOARD")
            after = PraiseObservation(
                screen_state="PERSONAL_MIGHT_LEADERBOARD",
                objective_name=OBJECTIVE,
                current_progress=0,
                required_progress=1,
                target_identity=detail.get("target_id", ""),
                target_roi=PRAISE_REGION,
                leaderboard_identity=bool(detail.get("leaderboard_identity")),
                might_region_identity=bool(detail.get("might_region_identity")),
                target_visible=bool(detail.get("target")),
                zero_cost_evidence=True,
                game_day_id=self.game_day,
                already_praised=bool(detail.get("already_praised")),
                cooldown_active=bool(detail.get("cooldown_active")),
                praise_disabled=bool(detail.get("praise_disabled")),
            )
            return PersonalMightPraiseHandler.postcondition_verified(observation, after)

        result = self.execute_input(
            name="praise",
            source_state="PERSONAL_MIGHT_LEADERBOARD",
            target_identity=MIGHT_PRAISE_ACTION.name,
            target_roi=PRAISE_REGION,
            expected_state="PERSONAL_MIGHT_LEADERBOARD",
            semantic="PRAISE_PERSONAL_MIGHT",
            consequence="praise_zero_cost",
            action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
            initial_path=source_path,
            initial=_observation(
                path=source_path,
                state="PERSONAL_MIGHT_LEADERBOARD",
                target_identity=MIGHT_PRAISE_ACTION.name,
                target_roi=PRAISE_REGION,
                expected_postcondition="praise_control_changes_or_disables",
                consequence="praise_zero_cost",
                action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
                critical_rois=(("leaderboard", LEADERBOARD_REGION), ("might", MIGHT_REGION), ("praise", PRAISE_REGION)),
            ),
            post_reader=read_post,
            postcondition=postcondition,
            transport=lambda: self.transport.tap((PRAISE_REGION[0] + PRAISE_REGION[2]) // 2, (PRAISE_REGION[1] + PRAISE_REGION[3]) // 2),
        )
        return source_path, observation

    def _daily_claim_observation(self, path: Path) -> tuple[DailyQuestClaimObservation, dict[str, Any]]:
        frame = load_frame(path)
        lines = ocr_lines(frame)
        objective_line = find_phrase(lines, OBJECTIVE_ALIASES)
        selected = recognize_daily_selected(
            frame,
            load_frame(self.args.daily_reference),
            load_frame(self.args.main_quest_reference),
        ).recognized
        row_text = objective_line["text"] if objective_line else ""
        progress = parse_progress(row_text) or (0, 1)
        claim_line = find_phrase(lines, ("claim",))
        row_bounds = roi_from_item(objective_line, (0, 400, 800, 1120))
        claim_roi = roi_from_item(claim_line, (530, row_bounds[1], 750, min(1280, row_bounds[3])))
        claim_visible = bool(claim_line and row_bounds[1] <= claim_roi[1] < row_bounds[3])
        result = DailyQuestClaimObservation(
            screen_state="DAILY_QUEST",
            selected_daily_quest=selected,
            objective_name=OBJECTIVE if objective_line else "",
            current_progress=progress[0],
            required_progress=progress[1],
            row_bounds=row_bounds,
            target_identity="daily-quest-claim" if claim_visible else "",
            target_roi=claim_roi,
            control_class="CLAIM" if claim_visible else "",
            row_fully_visible=row_bounds[1] >= 400 and row_bounds[3] <= 1120,
            claim_fully_visible=claim_visible,
            game_day_id=self.game_day,
            recognized=selected and objective_line is not None,
        )
        return result, {"lines": lines, "objective_line": objective_line, "claim_line": claim_line, "selected": selected}

    def claim(self) -> Any:
        source_path, _ = self.capture("claim-source")
        before, detail = self._daily_claim_observation(source_path)
        write_json(self.evidence / "claim-pre-dispatch.json", {
            "source_screenshot": str(source_path),
            "selected_daily_quest": before.selected_daily_quest,
            "objective_name": before.objective_name,
            "progress": [before.current_progress, before.required_progress],
            "row_bounds": list(before.row_bounds),
            "claim_bounds": list(before.target_roi),
            "control_class": before.control_class,
            "game_day_id": before.game_day_id,
        })
        if not claim_authorizeable(before):
            raise RuntimeError("exact completed Personal Might Praise Claim row not recognized")

        def read_post(path: Path) -> Observation:
            after, _ = self._daily_claim_observation(path)
            return _observation(
                path=path,
                state="DAILY_QUEST",
                target_identity=after.target_identity or None,
                target_roi=after.target_roi if after.target_identity else None,
                expected_postcondition="exact_praise_row_claimed",
                consequence="claim_zero_cost_reward",
                action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
                control_class=after.control_class or None,
                recognized=after.selected_daily_quest,
                critical_rois=(("daily_header", (0, 0, 800, 450)), ("claim_row", before.row_bounds)),
            )

        def postcondition(item: Observation) -> bool:
            after, _ = self._daily_claim_observation(Path(item.evidence_refs[0]))
            disappeared = after.target_identity != "daily-quest-claim"
            return claim_postcondition_verified(before, after, row_disappeared=disappeared)

        return self.execute_input(
            name="claim",
            source_state="DAILY_QUEST",
            target_identity=before.target_identity,
            target_roi=before.target_roi,
            expected_state="DAILY_QUEST",
            semantic="CLAIM_DAILY_QUEST",
            consequence="claim_zero_cost_reward",
            action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
            initial_path=source_path,
            initial=_observation(
                path=source_path,
                state="DAILY_QUEST",
                target_identity=before.target_identity,
                target_roi=before.target_roi,
                expected_postcondition="exact_praise_row_claimed",
                consequence="claim_zero_cost_reward",
                action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
                control_class="CLAIM",
                critical_rois=(("daily_header", (0, 0, 800, 450)), ("claim_row", before.row_bounds)),
            ),
            post_reader=read_post,
            postcondition=postcondition,
            transport=lambda: self.transport.tap((before.target_roi[0] + before.target_roi[2]) // 2, (before.target_roi[1] + before.target_roi[3]) // 2),
        )

    def run(self) -> int:
        if self.store.list_nonterminal_actions() or self.store.list_unresolved_actions():
            raise RuntimeError("existing action state blocks Praise validation")
        self.store.acquire_lease(self.owner, time.time(), self.args.lease_ttl)
        try:
            startup_path, _ = self.capture("startup-source")
            startup_frame = load_frame(startup_path)
            popup = recognize_reset_popup(startup_frame)
            write_json(self.evidence / "startup-diagnosis.json", {
                "popup": popup,
                "ocr_lines": ocr_lines(startup_frame),
                "foreground_assumed_game": True,
            })
            if popup["recognized"]:
                self.dismiss_reset_popup(popup)
                if self.args.popup_only:
                    write_json(self.evidence / "vip-points-popup-task-result.json", {
                        "status": "confirmed",
                        "popup_was_present": True,
                        "popup_inputs": self.vip_popup_input_count,
                    })
                    return 0
            elif self.args.popup_only:
                home = recognize_home_quest(startup_frame, load_frame(self.args.home_reference))
                if not home.recognized:
                    raise RuntimeError("VIP Points popup absent but known Home/Base successor not recognized")
                write_json(self.evidence / "vip-points-popup-task-result.json", {
                    "status": "confirmed_absent",
                    "popup_was_present": False,
                    "popup_inputs": self.vip_popup_input_count,
                })
                return 0
            startup_text = " ".join(item["text"] for item in ocr_lines(startup_frame))
            if "speedup help" in startup_text or ("help" in startup_text and "request" in startup_text):
                self.run_route_step(
                    "normalize-alliance-to-home", "SPEEDUP_HELP", "HOME_BASE",
                    "ALLIANCE_BACK", BACK_REGION, detection_state="ALLIANCE_BACK",
                    target_id="standard-game-back-arrow",
                )
            for name, source, target, semantic, roi in (
                ("home-to-more", "HOME_BASE", "MORE", "HOME_TO_MORE", HOME_MORE_REGION),
                ("more-to-rankings", "MORE", "RANKINGS", "MORE_TO_RANKINGS", RANKINGS_REGION),
                ("rankings-to-personal-might", "RANKINGS", "PERSONAL_MIGHT_RANK", "RANKINGS_TO_PERSONAL_MIGHT", PERSONAL_ROW_REGION),
                ("personal-might-check", "PERSONAL_MIGHT_RANK", "PERSONAL_MIGHT_LEADERBOARD", "PERSONAL_MIGHT_CHECK", CHECK_REGION),
            ):
                self.run_route_step(name, source, target, semantic, roi)
            _path, praise_obs = self.praise()
            if praise_obs.already_praised or praise_obs.cooldown_active:
                raise RuntimeError("ALREADY_PRAISED_OR_COOLDOWN")
            self.run_route_step(
                "personal-might-back-to-rankings", "PERSONAL_MIGHT_LEADERBOARD", "RANKINGS",
                "PERSONAL_MIGHT_BACK", BACK_REGION, detection_state="PERSONAL_MIGHT_BACK",
            )
            self.run_route_step(
                "rankings-back-to-home", "RANKINGS", "HOME_BASE", "RANKINGS_BACK",
                BACK_REGION, detection_state="RANKINGS_BACK",
            )
            # Existing bounded Quest navigation remains the only route to selected Daily Quest.
            self.run_route_step(
                "home-to-quest", "HOME_BASE", "QUEST", "HOME_TO_QUEST",
                (250, 1130, 410, 1280), target_id="home-quest-entry",
            )
            self.run_route_step("quest-to-daily", "QUEST", "DAILY_QUEST", "QUEST_TO_DAILY", (300, 70, 500, 140))
            claim_result = self.claim()
            write_json(self.evidence / "praise-task-result.json", {
                "status": "confirmed",
                "input_count": self.input_count,
                "claim_result": claim_result.__dict__,
            })
            return 0 if claim_result.status.value == "confirmed" else 3
        finally:
            lease = self.store.get_lease(time.time())
            if lease and lease.get("valid") and lease.get("owner_id") == self.owner:
                self.store.release_lease(self.owner, time.time())
            self.store.close()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--adb", default="/opt/adb")
    root.add_argument("--serial", default="192.168.122.79:5555")
    root.add_argument("--database", type=Path, required=True)
    root.add_argument("--evidence", type=Path, required=True)
    root.add_argument("--owner", required=True)
    root.add_argument("--game-day", default="daily-2026-07-13")
    root.add_argument("--lease-ttl", type=float, default=600.0)
    root.add_argument("--daily-reference", type=Path, required=True)
    root.add_argument("--main-quest-reference", type=Path, required=True)
    root.add_argument("--home-reference", type=Path, required=True)
    root.add_argument("--quest-reference", type=Path, required=True)
    root.add_argument("--popup-only", action="store_true")
    return root


if __name__ == "__main__":
    raise SystemExit(LiveAdapter(parser().parse_args()).run())
