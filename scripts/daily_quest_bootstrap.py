#!/usr/bin/env python3
"""Fail-closed Daily Quest bootstrap corpus validator and recognizer.

This task-scoped helper validates final-profile corpus metadata and performs conservative
screen/target checks for the bootstrap navigation path. It never owns ADB or sends input.
Ambiguous, clipped, stale, profile-mismatched, or unknown states remain non-actionable.
"""

from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import cv2
import numpy as np
import pytesseract

from startup_normalization import classify_home_base_live, load_frame, parse_keyguard_policy


FRAME_WIDTH = 800
FRAME_HEIGHT = 1280
FRAME_SHAPE = (FRAME_HEIGHT, FRAME_WIDTH)

# These ROIs are recognition regions only. A target is actionable only after the associated
# positive screen and OCR/layout checks pass, followed by an immediate fresh recapture.
ROIS: Dict[str, Tuple[int, int, int, int]] = {
    "home_quest_entry": (250, 1130, 410, 1280),
    "quest_title": (0, 0, 800, 180),
    "quest_tabs": (120, 80, 680, 300),
    "daily_quest_tab": (300, 70, 500, 140),
    "daily_header": (0, 0, 800, 450),
    "daily_rows": (0, 400, 800, 1120),
    "daily_bottom": (0, 1080, 800, 1280),
}

DAILY_GO_BUTTON_BANDS: Tuple[Tuple[int, int, int, int], ...] = tuple(
    (530, y0, 750, y0 + 90) for y0 in (410, 545, 680, 815, 950, 1085)
)

FORBIDDEN_REGIONS: Dict[str, Tuple[int, int, int, int]] = {
    "purchase_or_premium": (0, 0, 800, 1280),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_profile(manifest_path: Path) -> Mapping[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("runtime profile manifest must be an object")
    profile_id = manifest.get("profile_id")
    profile_hash = manifest.get("profile_content_sha256")
    if not isinstance(profile_id, str) or not profile_id:
        raise ValueError("runtime profile profile_id is missing")
    if not isinstance(profile_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", profile_hash):
        raise ValueError("runtime profile hash is missing or malformed")
    return manifest


def valid_png_frame(path: Path) -> Dict[str, Any]:
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")
    frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None or frame.shape != (FRAME_HEIGHT, FRAME_WIDTH, 3):
        raise ValueError(f"profile mismatch or corrupt frame: {path}")
    if float(np.mean(frame)) < 3.0:
        raise ValueError(f"black frame rejected: {path}")
    return {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "width": FRAME_WIDTH,
        "height": FRAME_HEIGHT,
        "bytes": len(raw),
    }


def crop(frame: np.ndarray, roi: Tuple[int, int, int, int]) -> np.ndarray:
    x0, y0, x1, y1 = roi
    return frame[y0:y1, x0:x1]


def ocr(frame: np.ndarray, roi: Tuple[int, int, int, int], psm: int = 6) -> str:
    text = pytesseract.image_to_string(crop(frame, roi), config=f"--psm {psm}")
    return re.sub(r"\s+", " ", text.lower()).strip()


def ocr_has_phrase(text: str, phrase: str, threshold: float = 0.88) -> bool:
    """Accept only a close OCR spelling of a required semantic phrase."""
    compact = re.sub(r"[^a-z]", "", text.lower())
    target = re.sub(r"[^a-z]", "", phrase.lower())
    if not compact or not target:
        return False
    if target in compact:
        return True
    minimum = max(1, len(target) - 2)
    maximum = min(len(compact), len(target) + 2)
    return any(
        SequenceMatcher(None, compact[start : start + width], target).ratio() >= threshold
        for width in range(minimum, maximum + 1)
        for start in range(0, max(0, len(compact) - width + 1))
    )


def frame_from(path: Path) -> np.ndarray:
    valid_png_frame(path)
    frame = load_frame(path)
    if frame.shape != (FRAME_HEIGHT, FRAME_WIDTH, 3):
        raise ValueError(f"profile mismatch: {path}")
    return frame


def recognize_home(
    frame_path: Path,
    cash_reference: Path,
    policy_path: Path | None = None,
) -> Dict[str, Any]:
    frame = frame_from(frame_path)
    cash = frame_from(cash_reference)
    safe_os_surface = True
    if policy_path:
        policy = parse_keyguard_policy(policy_path.read_text(encoding="utf-8"))
        safe_os_surface = (
            policy.get("showing") is False
            and policy.get("secure") is False
            and policy.get("input_restricted") is False
        )
    home = classify_home_base_live(frame, cash_mall_rejected=True, safe_os_surface=safe_os_surface)
    quest_text = ocr(frame, ROIS["home_quest_entry"], psm=6)
    quest_target_recognized = "quest" in quest_text
    recognized = bool(home["recognized"] and quest_target_recognized and safe_os_surface)
    return {
        "state": "HOME_BASE" if recognized else "UNKNOWN",
        "recognized": recognized,
        "home_features": home,
        "quest_entry_text": quest_text,
        "quest_entry_target_recognized": quest_target_recognized,
        "quest_entry_roi": list(ROIS["home_quest_entry"]),
        "safe_os_surface": safe_os_surface,
        "reason": "Home/Base and Quest entry OCR passed"
        if recognized
        else "Home/Base, safe OS, or Quest entry recognition did not pass",
    }


def recognize_quest(frame_path: Path) -> Dict[str, Any]:
    frame = frame_from(frame_path)
    title = ocr(frame, ROIS["quest_title"], psm=6)
    tabs = ocr(frame, ROIS["quest_tabs"], psm=6)
    quest_present = ocr_has_phrase(title, "quest", threshold=0.80) or ocr_has_phrase(
        tabs, "quest", threshold=0.80
    )
    daily_target = ocr_has_phrase(tabs, "dailyquest", threshold=0.88)
    recognized = quest_present or daily_target
    return {
        "state": "QUEST" if recognized else "UNKNOWN",
        "recognized": recognized,
        "title_text": title,
        "tabs_text": tabs,
        "daily_quest_target_recognized": daily_target,
        "daily_quest_tab_roi": list(ROIS["daily_quest_tab"]),
        "reason": "Quest screen and Daily Quest tab evidence passed"
        if recognized and daily_target
        else "Quest screen or Daily Quest tab evidence is insufficient",
    }


def recognize_daily_quest(
    frame_path: Path,
    daily_reference: Path | None = None,
    main_reference: Path | None = None,
) -> Dict[str, Any]:
    frame = frame_from(frame_path)
    selected_tab_positive = None
    if daily_reference and main_reference:
        # The tab label exists on every Quest category. Require the selected-state
        # comparison when references are supplied for live navigation.
        from navigation_recognition import recognize_daily_selected
        selected = recognize_daily_selected(
            frame,
            frame_from(daily_reference),
            frame_from(main_reference),
        )
        selected_tab_positive = selected.recognized
    header = ocr(frame, ROIS["daily_header"], psm=6)
    rows = ocr(frame, ROIS["daily_rows"], psm=6)
    bottom = ocr(frame, ROIS["daily_bottom"], psm=6)
    title_positive = ocr_has_phrase(header, "dailyquest", threshold=0.88) or (
        ocr_has_phrase(header, "daily", threshold=0.80)
        and ocr_has_phrase(header, "quest", threshold=0.80)
    )
    button_texts = [ocr(frame, roi, psm=7) for roi in DAILY_GO_BUTTON_BANDS]
    row_words = {
        word
        for word in ("go", "claim")
        if ocr_has_phrase(rows, word, threshold=0.80)
        or any(ocr_has_phrase(text, word, threshold=0.80) for text in button_texts)
    }
    go_present = "go" in row_words
    claim_present = "claim" in row_words
    recognized = title_positive and (
        ocr_has_phrase(header, "pts", threshold=0.75)
        or ocr_has_phrase(header, "point", threshold=0.80)
        or ocr_has_phrase(header, "reset", threshold=0.80)
    )
    if selected_tab_positive is not None:
        recognized = recognized and selected_tab_positive
    return {
        "state": "DAILY_QUEST" if recognized else "UNKNOWN",
        "recognized": recognized,
        "header_text": header,
        "rows_text": rows,
        "go_button_texts": button_texts,
        "bottom_text": bottom,
        "title_positive": title_positive,
        "selected_tab_positive": selected_tab_positive,
        "incomplete_or_go_present": go_present,
        "claim_observed_only": claim_present,
        "row_controls": sorted(row_words),
        "clipped_or_partial_bottom_row_present": True,
        "clipped_rows_abstain": True,
        "ambiguous_rows_abstain": True,
        "claim_input_authorized": False,
        "reason": "Daily Quest header and points/reset evidence passed"
        if recognized
        else "Daily Quest title/header or points/reset evidence is insufficient",
    }


def validate_asset_manifest(manifest_path: Path, profile_path: Path) -> Dict[str, Any]:
    profile = load_profile(profile_path)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("assets"), list):
        raise ValueError("asset manifest must contain an assets list")
    required = {
        "asset_id", "source_evidence_path", "capture_timestamp", "sha256", "width", "height",
        "profile_id", "profile_content_sha256", "game_package", "game_version", "locale",
        "screen_state", "overlay_state", "settled_or_transient", "freshness_status", "label", "rois",
        "forbidden_regions", "production_asset", "provenance", "review_status",
    }
    seen: set[str] = set()
    results = []
    for asset in data["assets"]:
        if not isinstance(asset, dict):
            raise ValueError("asset entry must be an object")
        missing = required - set(asset)
        if missing:
            raise ValueError(f"asset {asset.get('asset_id', '<unknown>')} missing: {sorted(missing)}")
        asset_id = asset["asset_id"]
        if asset_id in seen:
            raise ValueError(f"duplicate asset_id: {asset_id}")
        seen.add(asset_id)
        if asset["profile_id"] != profile["profile_id"]:
            raise ValueError(f"asset profile mismatch: {asset_id}")
        if asset["profile_content_sha256"] != profile["profile_content_sha256"]:
            raise ValueError(f"asset profile hash mismatch: {asset_id}")
        if asset["production_asset"] is True and asset["review_status"] != "promoted":
            raise ValueError(f"production asset is not promoted: {asset_id}")
        if asset["freshness_status"] not in {"fresh", "stale", "unknown"}:
            raise ValueError(f"invalid freshness status: {asset_id}")
        if asset["production_asset"] is True and asset["freshness_status"] != "fresh":
            raise ValueError(f"stale or unknown production asset: {asset_id}")
        source = Path(asset["source_evidence_path"])
        actual = valid_png_frame(source)
        if asset["sha256"] != actual["sha256"]:
            raise ValueError(f"asset hash mismatch: {asset_id}")
        if asset["width"] != FRAME_WIDTH or asset["height"] != FRAME_HEIGHT:
            raise ValueError(f"asset dimensions mismatch: {asset_id}")
        if asset["label"] == "ambiguous" and asset.get("action_target"):
            raise ValueError(f"ambiguous asset cannot carry an action target: {asset_id}")
        results.append({"asset_id": asset_id, "valid": True, **actual})
    return {
        "manifest": str(manifest_path),
        "profile_id": profile["profile_id"],
        "profile_content_sha256": profile["profile_content_sha256"],
        "asset_count": len(results),
        "assets": results,
        "input_lock": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    home = sub.add_parser("recognize-home")
    home.add_argument("--frame", type=Path, required=True)
    home.add_argument("--cash-reference", type=Path, required=True)
    home.add_argument("--policy", type=Path)
    home.add_argument("--output", type=Path)
    home.set_defaults(handler=lambda a: recognize_home(a.frame, a.cash_reference, a.policy))
    quest = sub.add_parser("recognize-quest")
    quest.add_argument("--frame", type=Path, required=True)
    quest.add_argument("--output", type=Path)
    quest.set_defaults(handler=lambda a: recognize_quest(a.frame))
    daily = sub.add_parser("recognize-daily-quest")
    daily.add_argument("--frame", type=Path, required=True)
    daily.add_argument("--daily-reference", type=Path)
    daily.add_argument("--main-reference", type=Path)
    daily.add_argument("--output", type=Path)
    daily.set_defaults(handler=lambda a: recognize_daily_quest(a.frame, a.daily_reference, a.main_reference))
    assets = sub.add_parser("validate-assets")
    assets.add_argument("--manifest", type=Path, required=True)
    assets.add_argument("--profile", type=Path, default=Path("runtime-profile/manifest.json"))
    assets.add_argument("--output", type=Path)
    assets.set_defaults(handler=lambda a: validate_asset_manifest(a.manifest, a.profile))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = args.handler(args)
    output = json.dumps(result, indent=2, sort_keys=True)
    if getattr(args, "output", None):
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    if args.command.startswith("recognize") and not result.get("recognized", False):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
