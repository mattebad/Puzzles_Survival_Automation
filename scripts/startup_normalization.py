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
    features: Dict[str, float]
    target_roi: Tuple[int, int, int, int]
    denial_rules: Tuple[str, ...]
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


def classify_cash_mall(frame: np.ndarray, reference: np.ndarray) -> CashMallDecision:
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
            features={},
            target_roi=ROIS["back_arrow"],
            denial_rules=denial_rules,
            reason="frame is not the locked 800x1280 profile",
        )

    features = {
        name: _feature_similarity(_crop(frame, roi), _crop(reference, roi))
        for name, roi in ROIS.items()
    }
    no_overlay = _overlay_guard(frame, reference, features)
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
        reason = "all positive Cash Mall structural/context features passed"
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


def _decision_json(path: Path, reference: Path, frame: Path) -> Dict[str, object]:
    reference_frame = load_frame(reference)
    candidate_frame = load_frame(frame)
    decision = classify_cash_mall(candidate_frame, reference_frame)
    return {
        "frame": str(frame),
        "frame_sha256": sha256_file(frame),
        "reference": str(reference),
        "reference_sha256": sha256_file(reference),
        "decision": asdict(decision),
    }


def run_offline(args: argparse.Namespace) -> int:
    reference = Path(args.reference)
    positives = [reference]
    negatives = [Path(item) for item in args.negative]
    results = {
        "profile": {"width": FRAME_WIDTH, "height": FRAME_HEIGHT},
        "reference_type": "development/reference; not a production asset",
        "positive": [_decision_json(reference, reference, item) for item in positives],
        "negative": [_decision_json(item, reference, item) for item in negatives],
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
        decision = classify_cash_mall(candidate, candidate)
        write_annotation(candidate, decision, Path(args.annotation))
        results["annotation"] = str(args.annotation)
    output = json.dumps(results, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    print(output)
    positive_pass = all(item["decision"]["recognized"] for item in results["positive"])
    negatives_pass = all(not item["decision"]["recognized"] for item in results["negative"])
    return 0 if positive_pass and negatives_pass else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    offline = subparsers.add_parser("offline", help="run fail-closed reference classification")
    offline.add_argument("--reference", required=True, help="800x1280 Cash Mall reference")
    offline.add_argument("--negative", action="append", default=[], help="negative frame; repeat")
    offline.add_argument("--home-reference", help="optional same-profile Home/Base reference")
    offline.add_argument("--annotation", help="write non-actionable dry-run annotation PNG")
    offline.add_argument("--output", help="write JSON result file")
    offline.set_defaults(handler=run_offline)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    sys.exit(main())
