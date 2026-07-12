#!/usr/bin/env python3
"""Fail-closed Cash Mall startup classifier and dry-run annotator.

This module deliberately does not own ADB or input transport.  It only classifies fresh
profile-sized frames and produces an annotated, non-actionable target proposal.  A supervised
controller may use the returned target only after a fresh source recapture and the policy gates
described in BACKLOG.md pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence, Tuple

import cv2
import numpy as np


FRAME_WIDTH = 800
FRAME_HEIGHT = 1280
FRAME_SHAPE = (FRAME_HEIGHT, FRAME_WIDTH)

# These are feature ROIs in the locked 800x1280 logical frame.  They are not an authorization
# by themselves; authorization requires positive recognition immediately before an input.
ROIS: Dict[str, Tuple[int, int, int, int]] = {
    "title_region": (220, 0, 580, 70),
    "back_arrow": (35, 0, 180, 65),
    "premium_header": (570, 0, 780, 65),
    "mall_header": (0, 70, 800, 230),
    "mall_context": (0, 230, 800, 475),
    "purchase_context": (40, 1000, 760, 1250),
}


@dataclass(frozen=True)
class CashMallDecision:
    state: str
    recognized: bool
    fresh_frame_dimensions: bool
    no_unknown_overlay: bool
    unknown_overlay: bool
    known_informational_overlay: bool
    features: Dict[str, float]
    target_roi: Tuple[int, int, int, int]
    denial_rules: Tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class KeyguardDecision:
    state: str
    visual_match: bool
    boot_completed: bool
    showing: Optional[bool]
    secure: Optional[bool]
    input_restricted: Optional[bool]
    swipe_authorized: bool
    swipe_count: int
    swipe_command: Tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class LauncherDecision:
    state: str
    visual_match: bool
    keyguard_nonblocking: bool
    focused_launcher: bool
    home_allowed: bool
    reason: str


def load_frame(path: Path) -> np.ndarray:
    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f"cannot decode image: {path}")
    return frame


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _crop(frame: np.ndarray, roi: Tuple[int, int, int, int]) -> np.ndarray:
    x0, y0, x1, y1 = roi
    return frame[y0:y1, x0:x1]


def _feature_similarity(candidate: np.ndarray, reference: np.ndarray) -> float:
    """Return a bounded pixel/edge similarity score for same-sized ROIs."""
    if candidate.shape != reference.shape:
        return 0.0
    candidate_gray = cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY)
    reference_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    pixel = 1.0 - float(np.mean(cv2.absdiff(candidate_gray, reference_gray))) / 255.0
    candidate_edge = cv2.Canny(candidate_gray, 80, 180)
    reference_edge = cv2.Canny(reference_gray, 80, 180)
    edge = 1.0 - float(np.mean(cv2.absdiff(candidate_edge, reference_edge))) / 255.0
    return round(max(0.0, min(1.0, 0.70 * pixel + 0.30 * edge)), 6)


def _valid_frame(frame: np.ndarray) -> bool:
    return frame.ndim == 3 and frame.shape[:2] == FRAME_SHAPE and frame.shape[2] == 3


def _parse_policy_bool(policy_text: str, label: str) -> Optional[bool]:
    keyguard_start = policy_text.find("KeyguardServiceDelegate")
    keyguard_end = policy_text.find("Looper state", keyguard_start)
    block = policy_text[keyguard_start:keyguard_end if keyguard_end >= 0 else None]
    match = re.search(rf"^\s*{re.escape(label)}=(true|false)\s*$", block, re.MULTILINE)
    return None if match is None else match.group(1) == "true"


def parse_keyguard_policy(policy_text: str) -> Dict[str, Optional[bool]]:
    """Extract only the startup safety fields from Android window-policy output."""
    input_match = re.search(r"^\s*mInputRestricted=(true|false)\s*$", policy_text, re.MULTILINE)
    return {
        "showing": _parse_policy_bool(policy_text, "showing"),
        "secure": _parse_policy_bool(policy_text, "secure"),
        "input_restricted": None if input_match is None else input_match.group(1) == "true",
    }


def _keyguard_visual_score(candidate: np.ndarray, reference: np.ndarray) -> float:
    if not _valid_frame(candidate) or not _valid_frame(reference):
        return 0.0
    # Exclude the changing clock/notification pixels while retaining the wallpaper, unlock
    # message, status surface, and taskbar geometry that identify the known Bliss fixture.
    stable_rois = ((0, 300, 800, 1140), (0, 1140, 800, 1280))
    scores = [
        _feature_similarity(_crop(candidate, roi), _crop(reference, roi))
        for roi in stable_rois
    ]
    return round(0.65 * scores[0] + 0.35 * scores[1], 6)


def _keyguard_unlock_text_score(candidate: np.ndarray, reference: np.ndarray) -> float:
    # The central unlock message is the positive visual anchor that separates the known keyguard
    # from the same-wallpaper launcher, Cash Mall, and other dark/black frames.
    roi = (250, 1190, 550, 1260)
    return _feature_similarity(_crop(candidate, roi), _crop(reference, roi))


def classify_known_keyguard(
    frame: np.ndarray, references: Sequence[np.ndarray], threshold: float = 0.62
) -> Dict[str, object]:
    """Recognize only the retained non-secure Bliss unlock/keyguard visual family."""
    if not _valid_frame(frame):
        return {
            "state": "UNKNOWN",
            "recognized": False,
            "visual_match": False,
            "score": 0.0,
            "reason": "candidate is not the locked 800x1280 profile",
        }
    scores = [_keyguard_visual_score(frame, reference) for reference in references]
    text_scores = [_keyguard_unlock_text_score(frame, reference) for reference in references]
    score = max(scores, default=0.0)
    text_score = max(text_scores, default=0.0)
    recognized = score >= threshold and text_score >= 0.985
    return {
        "state": "KNOWN_NONSECURE_KEYGUARD" if recognized else "UNKNOWN",
        "recognized": recognized,
        "visual_match": recognized,
        "score": score,
        "reference_scores": scores,
        "unlock_text_score": text_score,
        "unlock_text_reference_scores": text_scores,
        "reason": "known Bliss unlock/keyguard surface matched"
        if recognized
        else "candidate does not match the retained known unlock/keyguard surface",
    }


def authorize_keyguard_dismissal(
    boot_completed_text: str,
    policy_text: str,
    frame: np.ndarray,
    references: Sequence[np.ndarray],
    *,
    fresh: bool = True,
    game_force_stopped: bool = True,
    security_prompt: bool = False,
    swipe_count: int = 0,
) -> KeyguardDecision:
    """Fail-closed authorization for the one scoped central unlock swipe."""
    policy = parse_keyguard_policy(policy_text)
    visual = classify_known_keyguard(frame, references)
    boot_completed = boot_completed_text.strip() == "1"
    predicates = (
        boot_completed,
        policy["showing"] is True,
        policy["secure"] is False,
        policy["input_restricted"] is True,
        bool(visual["recognized"]),
        fresh,
        game_force_stopped,
        not security_prompt,
        swipe_count == 0,
    )
    authorized = all(predicates)
    if authorized:
        reason = "all known non-secure keyguard predicates passed; one swipe authorized"
    elif swipe_count != 0:
        reason = "swipe already used; no retry is authorized"
    elif security_prompt:
        reason = "credential or security prompt detected"
    else:
        reason = "one or more non-secure keyguard predicates failed"
    return KeyguardDecision(
        state="AUTHORIZED" if authorized else "BLOCKED",
        visual_match=bool(visual["recognized"]),
        boot_completed=boot_completed,
        showing=policy["showing"],
        secure=policy["secure"],
        input_restricted=policy["input_restricted"],
        swipe_authorized=authorized,
        swipe_count=swipe_count,
        swipe_command=("input", "swipe", "400", "1120", "400", "520", "350")
        if authorized
        else (),
        reason=reason,
    )


def classify_launcher_surface(
    frame: np.ndarray, references: Sequence[np.ndarray], policy_text: str, activity_text: str
) -> LauncherDecision:
    """Verify a safe launcher after the one swipe; focus alone is insufficient."""
    scores = [_keyguard_visual_score(frame, reference) for reference in references]
    # The retained launcher fixture has the same wallpaper geometry but no unlock-surface message.
    visual_match = max(scores, default=0.0) >= 0.52
    policy = parse_keyguard_policy(policy_text)
    nonblocking = (
        policy["secure"] is False
        and policy["input_restricted"] is False
        and policy["showing"] is False
    )
    focused_launcher = bool(
        re.search(r"com\.farmerbb\.taskbar|HomeActivityDelegate|Launcher", activity_text)
    )
    allowed = visual_match and nonblocking and focused_launcher
    return LauncherDecision(
        state="SAFE_LAUNCHER" if allowed else "UNKNOWN",
        visual_match=visual_match,
        keyguard_nonblocking=nonblocking,
        focused_launcher=focused_launcher,
        home_allowed=allowed,
        reason="launcher visual, policy, and focus checks passed"
        if allowed
        else "launcher visual/policy/focus checks did not all pass",
    )


def _overlay_guard(frame: np.ndarray, reference: np.ndarray, features: Dict[str, float]) -> bool:
    """Conservative guard for unknown center overlays.

    The source must retain both the Cash Mall structural regions and the expected center/banner
    context. A strong title/header match paired with a severely divergent mall context is treated
    as an unknown overlay, never as a tappable Cash Mall state.
    """
    del frame, reference
    return not (
        features["title_region"] >= 0.82
        and features["back_arrow"] >= 0.70
        and features["mall_header"] >= 0.55
        and features["mall_context"] < 0.25
    )


def _header_overlay_bbox(frame: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    """Return a light rectangular banner over the Cash Mall offer header, if present."""
    roi = frame[90:230, 100:760]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    bright = np.where(gray > 210, 255, 0).astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(bright)
    for x, y, width, height, area in stats[1:]:
        if width >= 100 and height >= 20 and area >= 1000:
            return (int(x + 100), int(y + 90), int(width), int(height))
    return None


def _rectangles_intersect(
    first: Tuple[int, int, int, int], second: Tuple[int, int, int, int]
) -> bool:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _allowlisted_ending_soon_overlay(
    frame: np.ndarray,
    overlay_reference: Optional[np.ndarray],
    target_roi: Tuple[int, int, int, int],
) -> bool:
    """Allow only the observed informational Ending Soon banner, never a generic overlay."""
    bbox = _header_overlay_bbox(frame)
    if bbox is None or overlay_reference is None or not _valid_frame(overlay_reference):
        return False
    allowed_bbox = (200, 130, 210, 85)
    overlay_roi = (200, 130, 410, 215)
    return (
        _rectangles_intersect(bbox, allowed_bbox)
        and not _rectangles_intersect(bbox, target_roi)
        and _feature_similarity(_crop(frame, overlay_roi), _crop(overlay_reference, overlay_roi))
        >= 0.90
    )


def classify_cash_mall(
    frame: np.ndarray,
    reference: np.ndarray,
    informational_overlay_reference: Optional[np.ndarray] = None,
) -> CashMallDecision:
    denial_rules = (
        "never select purchase, offer, premium-currency, or confirmation controls",
        "never authorize from coordinates without positive Cash Mall recognition immediately before input",
        "stale, unknown-overlay, timeout, and unexpected-successor frames are UNKNOWN",
    )
    if not _valid_frame(frame) or not _valid_frame(reference):
        return CashMallDecision(
            state="UNKNOWN",
            recognized=False,
            fresh_frame_dimensions=False,
            no_unknown_overlay=False,
            unknown_overlay=False,
            known_informational_overlay=False,
            features={},
            target_roi=ROIS["back_arrow"],
            denial_rules=denial_rules,
            reason="frame is not the locked 800x1280 profile",
        )

    features = {
        name: _feature_similarity(_crop(frame, roi), _crop(reference, roi))
        for name, roi in ROIS.items()
    }
    detected_overlay = _header_overlay_bbox(frame) is not None
    known_informational_overlay = _allowlisted_ending_soon_overlay(
        frame, informational_overlay_reference, ROIS["back_arrow"]
    )
    unknown_overlay = detected_overlay and not known_informational_overlay
    no_overlay = _overlay_guard(frame, reference, features) and not unknown_overlay
    thresholds = {
        "title_region": 0.82,
        "back_arrow": 0.70,
        "premium_header": 0.60,
        "mall_header": 0.55,
        "mall_context": 0.50,
        "purchase_context": 0.40,
    }
    passed = all(features[name] >= threshold for name, threshold in thresholds.items())
    recognized = passed and no_overlay
    if recognized:
        state = "CASH_MALL"
        reason = (
            "all positive Cash Mall features passed with the allowlisted Ending Soon informational banner"
            if known_informational_overlay
            else "all positive Cash Mall structural/context features passed"
        )
    elif not no_overlay:
        state = "UNKNOWN"
        reason = "possible unknown overlay: source structure and center context disagree"
    else:
        state = "UNKNOWN"
        reason = "one or more positive Cash Mall features did not pass"
    return CashMallDecision(
        state=state,
        recognized=recognized,
        fresh_frame_dimensions=True,
        no_unknown_overlay=no_overlay,
        unknown_overlay=unknown_overlay,
        known_informational_overlay=known_informational_overlay,
        features=features,
        target_roi=ROIS["back_arrow"],
        denial_rules=denial_rules,
        reason=reason,
    )


def classify_home_base(frame: np.ndarray, reference: Optional[np.ndarray]) -> Dict[str, object]:
    """Classify Home/Base only with a same-profile positive reference.

    Cross-device/iOS screenshots are intentionally rejected.  This prevents a visually similar
    development screenshot from authorizing a live postcondition on the locked Android runtime.
    """
    if reference is None:
        return {
            "state": "UNKNOWN",
            "recognized": False,
            "reason": "no final locked-runtime Home/Base reference is available",
        }
    if not _valid_frame(frame) or not _valid_frame(reference):
        return {
            "state": "UNKNOWN",
            "recognized": False,
            "reason": "Home/Base reference is not the locked 800x1280 runtime profile",
        }
    # A future final-profile asset must add positive bottom navigation, resource header, and base
    # scene features. This conservative same-profile comparison is still bounded and fail-closed.
    scene_roi = (0, 90, 800, 1120)
    nav_roi = (0, 1120, 800, 1280)
    scene_score = _feature_similarity(_crop(frame, scene_roi), _crop(reference, scene_roi))
    nav_score = _feature_similarity(_crop(frame, nav_roi), _crop(reference, nav_roi))
    recognized = scene_score >= 0.55 and nav_score >= 0.55
    return {
        "state": "HOME_BASE" if recognized else "UNKNOWN",
        "recognized": recognized,
        "scene_score": scene_score,
        "navigation_score": nav_score,
        "reason": "same-profile Home/Base scene and bottom navigation passed"
        if recognized
        else "Home/Base positive features did not pass",
    }


def classify_home_base_live(
    frame: np.ndarray, *, cash_mall_rejected: bool, safe_os_surface: bool = True
) -> Dict[str, object]:
    """Recognize final-profile Home/Base from independent stable regions and local OCR."""
    if not _valid_frame(frame):
        return {
            "state": "UNKNOWN",
            "recognized": False,
            "reason": "Home/Base candidate is not the locked 800x1280 profile",
        }
    resource_roi = frame[0:180, :]
    scene_roi = frame[180:1160, :]
    navigation_roi = frame[1160:1280, :]

    def activity_score(roi: np.ndarray) -> float:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 80, 180)
        return round(float(np.count_nonzero(edges)) / float(edges.size), 6)

    resource_score = activity_score(resource_roi)
    scene_score = activity_score(scene_roi)
    navigation_score = activity_score(navigation_roi)
    try:
        import pytesseract

        navigation_text = pytesseract.image_to_string(navigation_roi, config="--psm 6").lower()
        scene_text = pytesseract.image_to_string(scene_roi, config="--psm 6").lower()
    except Exception as exc:  # pragma: no cover - environment capability is deliberately fail-closed
        return {
            "state": "UNKNOWN",
            "recognized": False,
            "reason": f"local OCR capability unavailable: {exc}",
        }

    navigation_terms = ("quest", "bag", "mail", "more", "alliance", "hero", "world")
    scene_terms = ("headquarters", "watch tower", "warehouse", "camp", "research", "depot")
    navigation_hits = sorted(term for term in navigation_terms if term in navigation_text)
    scene_hits = sorted(term for term in scene_terms if term in scene_text)
    recognized = (
        safe_os_surface
        and cash_mall_rejected
        and resource_score >= 0.04
        and scene_score >= 0.04
        and navigation_score >= 0.05
        and len(navigation_hits) >= 3
        and len(scene_hits) >= 2
    )
    return {
        "state": "HOME_BASE" if recognized else "UNKNOWN",
        "recognized": recognized,
        "resource_header_score": resource_score,
        "base_scene_score": scene_score,
        "bottom_navigation_score": navigation_score,
        "navigation_ocr_hits": navigation_hits,
        "scene_ocr_hits": scene_hits,
        "navigation_ocr_text": navigation_text,
        "scene_ocr_text": scene_text,
        "reason": "resource header, base scene, bottom navigation, and OCR anchors passed"
        if recognized
        else "Home/Base stable-region, OCR, OS, or source-negative checks did not all pass",
    }


def write_annotation(frame: np.ndarray, decision: CashMallDecision, output: Path) -> None:
    annotated = frame.copy()
    x0, y0, x1, y1 = decision.target_roi
    cv2.rectangle(annotated, (x0, y0), (x1, y1), (0, 220, 0), 3)
    cv2.putText(
        annotated,
        "DRY-RUN ONLY: recognized back-arrow ROI",
        (20, 1245),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (0, 220, 0),
        2,
        cv2.LINE_AA,
    )
    for name in ("premium_header", "mall_header", "mall_context", "purchase_context"):
        rx0, ry0, rx1, ry1 = ROIS[name]
        cv2.rectangle(annotated, (rx0, ry0), (rx1, ry1), (0, 0, 220), 2)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), annotated):
        raise OSError(f"could not write annotation: {output}")


def _decision_json(
    path: Path,
    reference: Path,
    frame: Path,
    informational_overlay_reference: Optional[np.ndarray] = None,
) -> Dict[str, object]:
    reference_frame = load_frame(reference)
    candidate_frame = load_frame(frame)
    decision = classify_cash_mall(candidate_frame, reference_frame, informational_overlay_reference)
    return {
        "frame": str(frame),
        "frame_sha256": sha256_file(frame),
        "reference": str(reference),
        "reference_sha256": sha256_file(reference),
        "decision": asdict(decision),
    }


def run_offline(args: argparse.Namespace) -> int:
    reference = Path(args.reference)
    informational_overlay_reference = (
        load_frame(Path(args.informational_overlay_reference))
        if args.informational_overlay_reference
        else None
    )
    positives = [reference]
    negatives = [Path(item) for item in args.negative]
    results = {
        "profile": {"width": FRAME_WIDTH, "height": FRAME_HEIGHT},
        "reference_type": "development/reference; not a production asset",
        "positive": [
            _decision_json(reference, reference, item, informational_overlay_reference)
            for item in positives
        ],
        "negative": [
            _decision_json(item, reference, item, informational_overlay_reference)
            for item in negatives
        ],
        "home_base_offline": {
            "state": "UNKNOWN",
            "reason": "no final locked-runtime Home/Base reference supplied",
        },
    }
    if args.home_reference:
        home_reference = load_frame(Path(args.home_reference))
        home_candidate = classify_home_base(home_reference, home_reference)
        results["home_base_reference_check"] = {
            "reference": args.home_reference,
            "reference_sha256": sha256_file(Path(args.home_reference)),
            "decision": home_candidate,
        }
    if args.annotation:
        candidate = load_frame(reference)
        decision = classify_cash_mall(candidate, candidate, informational_overlay_reference)
        write_annotation(candidate, decision, Path(args.annotation))
        results["annotation"] = str(args.annotation)
    output = json.dumps(results, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    print(output)
    positive_pass = all(item["decision"]["recognized"] for item in results["positive"])
    negatives_pass = all(not item["decision"]["recognized"] for item in results["negative"])
    return 0 if positive_pass and negatives_pass else 2


def run_keyguard_offline(args: argparse.Namespace) -> int:
    candidate = load_frame(Path(args.candidate))
    references = [load_frame(Path(item)) for item in args.reference]
    policy_text = Path(args.policy).read_text(encoding="utf-8") if args.policy else ""
    boot_text = Path(args.boot).read_text(encoding="utf-8") if args.boot else "1"
    decision = authorize_keyguard_dismissal(
        boot_text,
        policy_text,
        candidate,
        references,
        fresh=True,
        game_force_stopped=True,
        security_prompt=False,
        swipe_count=0,
    )
    result = {"candidate": args.candidate, "decision": asdict(decision)}
    output = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if decision.swipe_authorized else 2


def run_classify_frame(args: argparse.Namespace) -> int:
    candidate_path = Path(args.candidate)
    reference_path = Path(args.reference)
    candidate = load_frame(candidate_path)
    reference = load_frame(reference_path)
    overlay_reference = (
        load_frame(Path(args.informational_overlay_reference))
        if args.informational_overlay_reference
        else None
    )
    decision = classify_cash_mall(candidate, reference, overlay_reference)
    if args.annotation:
        write_annotation(candidate, decision, Path(args.annotation))
    result = {
        "candidate": str(candidate_path),
        "candidate_sha256": sha256_file(candidate_path),
        "reference": str(reference_path),
        "decision": asdict(decision),
    }
    output = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if decision.recognized else 2


def run_home_base_live(args: argparse.Namespace) -> int:
    candidate_path = Path(args.candidate)
    candidate = load_frame(candidate_path)
    cash_reference = load_frame(Path(args.cash_reference))
    overlay_reference = (
        load_frame(Path(args.informational_overlay_reference))
        if args.informational_overlay_reference
        else None
    )
    cash = classify_cash_mall(candidate, cash_reference, overlay_reference)
    policy = parse_keyguard_policy(Path(args.policy).read_text(encoding="utf-8"))
    safe_os_surface = (
        policy["showing"] is False
        and policy["secure"] is False
        and policy["input_restricted"] is False
    )
    home = classify_home_base_live(
        candidate, cash_mall_rejected=not cash.recognized, safe_os_surface=safe_os_surface
    )
    result = {
        "candidate": str(candidate_path),
        "candidate_sha256": sha256_file(candidate_path),
        "cash_mall_postcheck": asdict(cash),
        "safe_os_surface": safe_os_surface,
        "home_base": home,
    }
    output = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if home["recognized"] else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    offline = subparsers.add_parser("offline", help="run fail-closed reference classification")
    offline.add_argument("--reference", required=True, help="800x1280 Cash Mall reference")
    offline.add_argument("--negative", action="append", default=[], help="negative frame; repeat")
    offline.add_argument("--home-reference", help="optional same-profile Home/Base reference")
    offline.add_argument(
        "--informational-overlay-reference",
        help="final-profile reference for the explicitly allowlisted Ending Soon banner",
    )
    offline.add_argument("--annotation", help="write non-actionable dry-run annotation PNG")
    offline.add_argument("--output", help="write JSON result file")
    offline.set_defaults(handler=run_offline)
    keyguard = subparsers.add_parser(
        "keyguard-offline", help="authorize the one scoped non-secure keyguard swipe"
    )
    keyguard.add_argument("--candidate", required=True, help="fresh 800x1280 candidate frame")
    keyguard.add_argument(
        "--reference", action="append", required=True, help="retained known keyguard frame; repeat"
    )
    keyguard.add_argument("--policy", help="window-policy output")
    keyguard.add_argument("--boot", help="sys.boot_completed output")
    keyguard.add_argument("--output", help="write JSON result file")
    keyguard.set_defaults(handler=run_keyguard_offline)
    classify = subparsers.add_parser("classify-frame", help="classify one fresh Cash Mall frame")
    classify.add_argument("--candidate", required=True, help="fresh 800x1280 candidate frame")
    classify.add_argument("--reference", required=True, help="clean Cash Mall reference frame")
    classify.add_argument(
        "--informational-overlay-reference",
        help="optional final-profile Ending Soon banner fixture",
    )
    classify.add_argument("--annotation", help="write a non-actionable target annotation")
    classify.add_argument("--output", help="write JSON result file")
    classify.set_defaults(handler=run_classify_frame)
    home = subparsers.add_parser("home-base-live", help="verify final-profile Home/Base postcondition")
    home.add_argument("--candidate", required=True, help="fresh 800x1280 Home/Base candidate")
    home.add_argument("--cash-reference", required=True, help="clean Cash Mall reference")
    home.add_argument("--informational-overlay-reference", help="allowlisted banner fixture")
    home.add_argument("--policy", required=True, help="postcondition window-policy output")
    home.add_argument("--output", help="write JSON result file")
    home.set_defaults(handler=run_home_base_live)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    sys.exit(main())
