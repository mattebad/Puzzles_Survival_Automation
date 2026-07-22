#!/usr/bin/env python3
"""Offline batch diagnostics for Nova radial recognition on retained frames.

Runs the production recognizer (tasks.nova_praise_vision.recognize_nova_frame) against
retained native PNG frames in two modes (provenanced and initial-unprovenanced) and
reports which gate rejected a Nova bind. No live runtime, ADB, lease, or network.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tasks.gameplay_flow_replay import load_retained_native_frame
from tasks.nova_praise import NOVA_INTERACTION_TARGET
from tasks.nova_praise_vision import (
    RESEARCH_LAB_ROI,
    ResearchLabTapProvenance,
    recognize_nova_frame,
)

SYNTHETIC_CAPTURED_MONOTONIC = 1000.0
SYNTHETIC_DISPATCHED_MONOTONIC = 999.0  # within 30s freshness window, strictly prior
MODES = ("provenanced", "initial-unprovenanced")


def _research_lab_center_roi() -> tuple[int, int, int, int]:
    """Center-ish box derived from RESEARCH_LAB_ROI for synthetic tap provenance."""

    x0, y0, x1, y1 = RESEARCH_LAB_ROI
    cx = (x0 + x1) // 2
    cy = (y0 + y1) // 2
    half = 24
    return (cx - half, cy - half, cx + half, cy + half)


def _classify_reject_gate(
    *,
    bound: bool,
    bind_method: str,
    template: dict[str, Any],
    radial: dict[str, Any],
) -> str:
    if bound:
        return "bound"
    reject = template.get("reject_reason")
    missing = list(radial.get("rejected_or_missing_observations") or ())
    if reject == "weak_template_match":
        return (
            f"template_weak_score "
            f"(score={template.get('score')}, min={template.get('min_score')}, "
            f"margin={template.get('margin')})"
        )
    if reject == "ambiguous_or_duplicated_template_match":
        return (
            f"template_ambiguous "
            f"(score={template.get('score')}, margin={template.get('margin')}, "
            f"min_margin={template.get('min_margin')}, "
            f"distinct_strong={template.get('spatially_distinct_strong_count')})"
        )
    if reject == "clipped_or_partial_template_match":
        return f"template_clipped (match_roi={template.get('match_roi')})"
    if reject in (
        "no_template_response_in_nova_sector",
        "no_template_response_in_radial_region",
    ):
        return f"template_no_response ({reject}; search_roi={template.get('search_roi')})"
    if reject == "missing_template":
        return "missing_template_asset"
    if reject:
        return f"template_rejected ({reject})"
    if "localized_home_context" in missing:
        return "missing_home_context"
    if "incompatible_full_screen_or_modal_state" in missing:
        return "incompatible_state"
    if "compatible_research_lab_ocr" in missing:
        return f"ocr_missing_terms (ocr_terms={list(radial.get('ocr_terms') or ())})"
    if "research_lab_tap_provenance" in missing or "fresh_post_tap_frame" in missing:
        return "provenance_or_freshness"
    if "ambiguous_radial_geometry" in missing:
        return f"ambiguous_geometry (bind_method={bind_method})"
    if "current_frame_nova_target" in missing or "compatible_radial_control_arrangement" in missing:
        return (
            f"geometry_not_bound (bind_method={bind_method}; "
            f"template_accepted={template.get('accepted')}; "
            f"score={template.get('score')}; margin={template.get('margin')})"
        )
    if missing:
        return f"radial_gate ({', '.join(missing)})"
    return f"unrecognized_non_bind (bind_method={bind_method})"


def diagnose_frame(
    frame: np.ndarray,
    *,
    frame_name: str,
    frame_sha256: str | None = None,
    captured_monotonic: float = SYNTHETIC_CAPTURED_MONOTONIC,
    modes: Sequence[str] = MODES,
) -> list[dict[str, Any]]:
    """Run recognize_nova_frame in the requested modes; return compact report dicts."""

    if frame is None or not isinstance(frame, np.ndarray):
        raise ValueError("frame must be a numpy ndarray")
    reports: list[dict[str, Any]] = []
    digest = frame_sha256
    for mode in modes:
        if mode == "provenanced":
            provenance = ResearchLabTapProvenance(
                action_key="diagnostic:synthetic-research-lab-tap",
                target_identity="home.building.research_lab",
                source_frame_sha256=digest
                or hashlib.sha256(frame.tobytes()).hexdigest(),
                target_roi=_research_lab_center_roi(),
                dispatched_monotonic=SYNTHETIC_DISPATCHED_MONOTONIC,
            )
            recognition = recognize_nova_frame(
                frame,
                captured_monotonic=captured_monotonic,
                stale=False,
                research_lab_tap_provenance=provenance,
                home_context_visible=True,
                incompatible_state=False,
            )
        elif mode == "initial-unprovenanced":
            recognition = recognize_nova_frame(
                frame,
                captured_monotonic=captured_monotonic,
                stale=False,
                research_lab_tap_provenance=None,
                home_context_visible=True,
                incompatible_state=False,
            )
        else:
            raise ValueError(f"unknown diagnostic mode: {mode}")

        observation = recognition.observation
        template = dict(recognition.diagnostics.get("nova_radial_template") or {})
        radial = dict(recognition.diagnostics.get("research_lab_radial") or {})
        bind_method = str(radial.get("bind_method") or "none")
        nova_bound = bool(
            observation.recognized
            and observation.screen_state == "RESEARCH_LAB_MENU"
            and (
                recognition.target(NOVA_INTERACTION_TARGET) is not None
                or observation.nova_control_visible
            )
        )
        reject_gate = _classify_reject_gate(
            bound=nova_bound,
            bind_method=bind_method,
            template=template,
            radial=radial,
        )
        reports.append(
            {
                "frame": frame_name,
                "mode": mode,
                "frame_sha256": recognition.frame_sha256,
                "screen_state": observation.screen_state,
                "recognized": bool(observation.recognized),
                "nova_control_visible": bool(observation.nova_control_visible),
                "nova_bound": nova_bound,
                "bind_method": bind_method,
                "reject_gate": reject_gate,
                "template": {
                    "accepted": template.get("accepted"),
                    "score": template.get("score"),
                    "margin": template.get("margin"),
                    "scale": template.get("scale"),
                    "search_roi": template.get("search_roi"),
                    "match_roi": template.get("match_roi"),
                    "reject_reason": template.get("reject_reason"),
                    "min_score": template.get("min_score"),
                    "min_margin": template.get("min_margin"),
                    "spatially_distinct_strong_count": template.get(
                        "spatially_distinct_strong_count"
                    ),
                },
                "radial": {
                    "supporting": list(radial.get("supporting_observations") or ()),
                    "rejected_or_missing": list(
                        radial.get("rejected_or_missing_observations") or ()
                    ),
                    "ocr_terms": list(radial.get("ocr_terms") or ()),
                    "nova_target_roi": radial.get("nova_target_roi"),
                    "confidence": radial.get("confidence"),
                },
                "targets": [
                    {"identity": identity, "roi": list(roi)}
                    for identity, roi in recognition.targets
                ],
            }
        )
    return reports


def _resolve_frame_paths(path: Path) -> list[Path]:
    if not path.exists():
        return []
    if path.is_file():
        return [path] if path.suffix.lower() == ".png" else []
    return sorted(path.glob("*.png"))


def diagnose_path(
    path: Path,
    *,
    captured_monotonic: float = SYNTHETIC_CAPTURED_MONOTONIC,
    modes: Sequence[str] = MODES,
) -> list[dict[str, Any]]:
    """Diagnose every PNG under a session/frames directory (or a single PNG)."""

    frames = _resolve_frame_paths(path)
    if not frames:
        return [
            {
                "frame": str(path),
                "mode": None,
                "error": "path_missing_or_no_png_frames",
                "nova_bound": False,
                "reject_gate": "path_missing_or_no_png_frames",
            }
        ]
    reports: list[dict[str, Any]] = []
    for frame_path in frames:
        captured = load_retained_native_frame(
            frame_path,
            captured_monotonic=captured_monotonic,
        )
        reports.extend(
            diagnose_frame(
                captured.frame,
                frame_name=frame_path.name,
                frame_sha256=captured.sha256,
                captured_monotonic=captured_monotonic,
                modes=modes,
            )
        )
    return reports


def format_human_report(reports: Iterable[dict[str, Any]]) -> str:
    lines: list[str] = []
    for report in reports:
        if report.get("error"):
            lines.append(f"[ERROR] {report.get('frame')}: {report['error']}")
            continue
        template = report.get("template") or {}
        radial = report.get("radial") or {}
        lines.append(
            f"{report['frame']} | mode={report['mode']} | "
            f"state={report['screen_state']} recognized={report['recognized']} | "
            f"bound={report['nova_bound']} | bind_method={report['bind_method']} | "
            f"gate={report['reject_gate']}"
        )
        lines.append(
            f"  template: accepted={template.get('accepted')} "
            f"score={template.get('score')} margin={template.get('margin')} "
            f"scale={template.get('scale')} "
            f"search_roi={template.get('search_roi')} "
            f"match_roi={template.get('match_roi')} "
            f"reject_reason={template.get('reject_reason')}"
        )
        lines.append(
            f"  radial supporting={radial.get('supporting')} "
            f"rejected_or_missing={radial.get('rejected_or_missing')} "
            f"ocr_terms={radial.get('ocr_terms')}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Session directory, frames directory, or PNG file(s)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON list instead of human text",
    )
    parser.add_argument(
        "--mode",
        action="append",
        choices=list(MODES),
        help="Restrict to one mode (repeatable). Default: both.",
    )
    args = parser.parse_args(argv)
    modes: Sequence[str] = tuple(args.mode) if args.mode else MODES
    all_reports: list[dict[str, Any]] = []
    for path in args.paths:
        candidate = path
        if candidate.is_dir() and (candidate / "frames").is_dir() and not list(
            candidate.glob("*.png")
        ):
            candidate = candidate / "frames"
        all_reports.extend(diagnose_path(candidate, modes=modes))
    if args.json:
        print(json.dumps(all_reports, indent=2, sort_keys=True, default=str))
    else:
        print(format_human_report(all_reports))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
