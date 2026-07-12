#!/usr/bin/env python3
"""Benchmark retained-frame proposal and immediate-before freshness stages.

This is offline replay only. Live screenshot-command latency is read from retained RT-010
measurements; no ADB, game, VM, container, or network endpoint is accessed.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List

import cv2
import numpy as np
import pytesseract

import daily_quest_bootstrap as dq
from mvp_quest_to_claim import PROFILE_ID, classify, critical_roi_hashes
from safe_action_core import CentralPolicy, Observation, PolicyRequest


def percentile(values: List[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(len(ordered) * fraction + 0.999999) - 1))]


def summary(values: List[float]) -> Dict[str, float | int]:
    full_p95 = percentile(stage_values["capture_completion_to_first_policy"], 0.95)
    full_max = max(stage_values["capture_completion_to_first_policy"])
    fast_p95 = percentile(stage_values["capture_completion_to_second_policy"], 0.95)
    return {
        "samples": len(values),
        "p50_ms": round(statistics.median(values) * 1000, 4),
        "p95_ms": round(percentile(values, 0.95) * 1000, 4),
        "max_ms": round(max(values) * 1000, 4),
    }


def timed(bucket: List[float], callback):
    started = time.perf_counter()
    value = callback()
    bucket.append(time.perf_counter() - started)
    return value


def policy_request(observation: Observation, now: float, phase: str) -> PolicyRequest:
    return PolicyRequest(
        action_id="benchmark-only",
        action_key="benchmark-only",
        task_id="MVP-QUEST-TO-CLAIM",
        task_mode="supervised_validation",
        semantic_action="NAVIGATE_ZERO_COST",
        expected_runtime_profile_id=PROFILE_ID,
        observation=observation,
        monotonic_now=now,
        observation_max_age_seconds=3.0,
        dispatch_max_age_seconds=2.0,
        lease_owner="benchmark",
        lease_valid=True,
        unresolved_action=False,
        duplicate_action_key=False,
        policy_phase=phase,
    )


def retained_capture_latency(csv_path: Path) -> Dict[str, Any]:
    values = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            values.append(float(row["capture_ms"]) / 1000.0)
    return {"source": str(csv_path), **summary(values)}


def run(args: argparse.Namespace) -> Dict[str, Any]:
    if args.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = args.tesseract_cmd
    elif os.name == "nt" and Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe").exists():
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    modes = {
        "home": args.home,
        "quest": args.quest,
        "daily": args.daily,
    }
    stage_values: Dict[str, List[float]] = {
        name: []
        for name in (
            "offline_capture_read",
            "image_decode",
            "profile_validation",
            "screen_classification_total",
            "roi_ocr_total",
            "target_detection",
            "first_policy_evaluation",
            "immediate_before_recapture_read",
            "second_validation_total",
            "second_policy_evaluation",
            "transport_invocation_mock",
            "capture_completion_to_first_policy",
            "capture_completion_to_second_policy",
        )
    }
    per_mode: Dict[str, Dict[str, Any]] = {}
    policy = CentralPolicy()
    original_ocr = dq.ocr
    ocr_durations: List[float] = []

    def measured_ocr(*ocr_args, **ocr_kwargs):
        started = time.perf_counter()
        try:
            return original_ocr(*ocr_args, **ocr_kwargs)
        finally:
            ocr_durations.append(time.perf_counter() - started)

    dq.ocr = measured_ocr
    try:
        for mode, frame_path in modes.items():
            mode_start = len(stage_values["screen_classification_total"])
            for _ in range(args.samples):
                raw = timed(stage_values["offline_capture_read"], frame_path.read_bytes)
                capture_completed = time.perf_counter()
                decoded = timed(
                    stage_values["image_decode"],
                    lambda: cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR),
                )
                timed(
                    stage_values["profile_validation"],
                    lambda: (
                        decoded is not None
                        and decoded.shape == (1280, 800, 3)
                        and float(np.mean(decoded)) >= 3.0
                    ),
                )
                ocr_before = sum(ocr_durations)
                result = timed(
                    stage_values["screen_classification_total"],
                    lambda: classify(mode, frame_path, args),
                )
                stage_values["roi_ocr_total"].append(sum(ocr_durations) - ocr_before)
                bindings = timed(
                    stage_values["target_detection"],
                    lambda: critical_roi_hashes(mode, frame_path, args),
                )
                frame_hash = dq.sha256_file(frame_path)
                observation = Observation(
                    frame_sha256=frame_hash,
                    capture_completed_monotonic=capture_completed,
                    runtime_profile_id=PROFILE_ID,
                    width=800,
                    height=1280,
                    valid_png=True,
                    corrupt=False,
                    black=False,
                    source_state=result["state"],
                    overlay_state="none_observed" if result["recognized"] else "unknown",
                    target_identity=args.target,
                    target_roi=tuple(args.roi),
                    consequence="navigate_zero_cost",
                    cost_type="none",
                    cost_amount=0,
                    quantity=1,
                    expected_postcondition="BENCHMARK_SUCCESSOR",
                    critical_roi_hashes=bindings,
                    ocr_result_frame_sha256=frame_hash,
                )
                first_now = time.perf_counter()
                timed(
                    stage_values["first_policy_evaluation"],
                    lambda: policy.evaluate(policy_request(observation, first_now, "proposal")),
                )
                stage_values["capture_completion_to_first_policy"].append(first_now - capture_completed)

                raw2 = timed(stage_values["immediate_before_recapture_read"], frame_path.read_bytes)
                immediate_completed = time.perf_counter()
                immediate_started = time.perf_counter()
                decoded2 = cv2.imdecode(np.frombuffer(raw2, dtype=np.uint8), cv2.IMREAD_COLOR)
                valid = decoded2 is not None and decoded2.shape == (1280, 800, 3) and float(np.mean(decoded2)) >= 3.0
                immediate_bindings = critical_roi_hashes(mode, frame_path, args)
                if not valid or immediate_bindings != bindings:
                    raise RuntimeError("retained benchmark frame changed during replay")
                immediate = replace(
                    observation,
                    capture_completed_monotonic=immediate_completed,
                    critical_roi_hashes=immediate_bindings,
                    ocr_result_frame_sha256=observation.frame_sha256,
                    ocr_reused=False,
                )
                stage_values["second_validation_total"].append(time.perf_counter() - immediate_started)
                second_now = time.perf_counter()
                timed(
                    stage_values["second_policy_evaluation"],
                    lambda: policy.evaluate(policy_request(immediate, second_now, "pre_dispatch")),
                )
                stage_values["capture_completion_to_second_policy"].append(
                    second_now - immediate_completed
                )
                timed(stage_values["transport_invocation_mock"], lambda: None)
            mode_end = len(stage_values["screen_classification_total"])
            per_mode[mode] = {"samples": mode_end - mode_start, "recognized": bool(result["recognized"])}
    finally:
        dq.ocr = original_ocr

    return {
        "scope": "offline retained final-runtime replay plus retained RT-010 live capture timing; zero live input",
        "samples_per_mode": args.samples,
        "total_pipeline_samples": args.samples * len(modes),
        "modes": per_mode,
        "retained_live_screenshot_command": retained_capture_latency(args.capture_csv),
        "stages": {name: summary(values) for name, values in stage_values.items()},
        "calibration": {
            "observation_freshness_seconds": 3.0,
            "dispatch_freshness_seconds": 2.0,
            "dispatch_calibration_target_seconds": 1.9,
            "bounded_pre_dispatch_attempts": 2,
            "post_input_observation_timeout_seconds": 10.0,
            "rationale": (
                "the 2.0-second dispatch hard maximum exceeds the measured "
                f"{full_p95:.3f}-second full-validation p95 and {full_max:.3f}-second maximum "
                f"by a bounded margin; exact critical-ROI reuse measured {fast_p95 * 1000:.1f} ms p95"
            ),
        },
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--samples", type=int, default=30)
    root.add_argument("--home", type=Path, required=True)
    root.add_argument("--quest", type=Path, required=True)
    root.add_argument("--daily", type=Path, required=True)
    root.add_argument("--cash-reference", type=Path, required=True)
    root.add_argument("--cash-overlay-reference", type=Path)
    root.add_argument("--policy-file", type=Path)
    root.add_argument("--capture-csv", type=Path, required=True)
    root.add_argument("--tesseract-cmd")
    root.add_argument("--target", default="benchmark-target")
    root.add_argument("--roi", type=int, nargs=4, default=(250, 1130, 410, 1280))
    root.add_argument("--output", type=Path, required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    result = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
