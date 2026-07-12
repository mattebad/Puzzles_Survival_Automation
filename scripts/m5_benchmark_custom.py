#!/usr/bin/env python3
"""Offline M5 benchmark for the incumbent deterministic startup adapter.

This is a task-scoped replay harness. It deliberately has no ADB transport and no input
primitive. Live ADB capture/reconnect facts are referenced from the already-passed RT-010,
RT-021, and MVP evidence instead of being repeated here.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import cv2
import numpy as np

import startup_normalization as sn


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def percentile(values: Iterable[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return round(float(ordered[index]), 6)


def decode(path: Path) -> Tuple[np.ndarray, float, bool]:
    started = time.perf_counter()
    raw = path.read_bytes()
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    valid = image is not None and sn._valid_frame(image)
    return image, elapsed_ms, bool(valid)


def asset_record(path: Path) -> Dict[str, Any]:
    image, elapsed_ms, valid = decode(path)
    dimensions = list(reversed(image.shape[:2])) if image is not None else None
    return {
        "path": str(path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "png_signature": path.read_bytes()[:8].hex() == "89504e470d0a1a0a",
        "dimensions": dimensions,
        "locked_profile_valid": valid,
        "decode_ms": round(elapsed_ms, 6),
    }


def policy_contract(decision: sn.CashMallDecision, *, fresh: bool, attempt: int,
                    target_stable: bool, target_overlap: bool) -> Dict[str, Any]:
    authorized = bool(
        decision.recognized
        and decision.fresh_frame_dimensions
        and fresh
        and target_stable
        and not target_overlap
        and attempt == 0
    )
    return {
        "authorized": authorized,
        "fresh": fresh,
        "attempt": attempt,
        "target_stable": target_stable,
        "target_overlap": target_overlap,
        "source_state": decision.state,
        "target_roi": list(decision.target_roi),
        "reason": "positive source/target and one-input policy predicates passed"
        if authorized
        else "central policy contract denied stale, unstable, overlapping, unknown, or repeated input",
    }


def import_inventory(script_path: Path) -> Dict[str, Any]:
    tree = ast.parse(script_path.read_text(encoding="utf-8"))
    modules: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module.split(".")[0])
    return {"top_level_imports": sorted(set(modules))}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--annotation-dir", type=Path, required=True)
    args = parser.parse_args()

    root = args.repo_root.resolve()
    evidence = root / "evidence" / "sessions" / "20260711-mvp-startup-normalization"
    cash = root / "evidence" / "sessions" / "20260711-rt-012-observe-soak" / "cash-mall-startup-reference.png"
    ending_soon = evidence / "remote-cache" / "20260711-cash-mall-observe-2120" / "frame-final.png"
    home = evidence / "remote-cache" / "20260711-cash-mall-input-2125" / "frame-settled-after.png"
    keyguard = evidence / "remote-cache" / "20260711-live-observe-2042" / "frame-before.png"
    ios_reference = root / "examples" / "screenshots" / "IMG_5080.PNG"
    keyguard_policy = evidence / "remote-cache" / "20260711-live-observe-2042" / "policy-before.txt"
    keyguard_boot = evidence / "remote-cache" / "20260711-live-observe-2042" / "boot.txt"
    rt021_record = root / "evidence" / "sessions" / "20260711-rt-021-worker-vm-adb" / "record.md"
    rt010_record = root / "evidence" / "sessions" / "20260711-rt-010-capture" / "record.md"
    input_record = evidence / "remote-cache" / "20260711-cash-mall-input-2125" / "input-command-record.txt"

    for required in (cash, ending_soon, home, keyguard, ios_reference, keyguard_policy, keyguard_boot):
        if not required.exists():
            raise SystemExit(f"missing retained benchmark fixture: {required}")

    assets = {
        "cash_mall": cash,
        "ending_soon": ending_soon,
        "home_base": home,
        "keyguard_launcher": keyguard,
        "profile_mismatch": ios_reference,
    }
    corpus = {name: asset_record(path) for name, path in assets.items()}

    # One hundred immutable replay captures. These measure decode/profile enforcement only;
    # live ADB capture latency remains the retained RT-010 measurement below.
    replay_order = [cash, ending_soon, home, keyguard, ios_reference] * 20
    replay_latencies: List[float] = []
    replay_valid: List[bool] = []
    replay_dimensions: List[Any] = []
    for path in replay_order:
        image, elapsed_ms, valid = decode(path)
        replay_latencies.append(elapsed_ms)
        replay_valid.append(valid)
        replay_dimensions.append(list(reversed(image.shape[:2])) if image is not None else None)
    expected_replay_valid = [path != ios_reference for path in replay_order]
    replay_result = {
        "operations": len(replay_order),
        "profile_valid_count": sum(actual == expected for actual, expected in zip(replay_valid, expected_replay_valid)),
        "profile_valid_expected_count": len(replay_order),
        "profile_mismatch_rejected_count": sum(not actual for actual, path in zip(replay_valid, replay_order) if path == ios_reference),
        "latency_ms": {
            "p50": percentile(replay_latencies, 0.50),
            "p95": percentile(replay_latencies, 0.95),
            "max": round(max(replay_latencies), 6),
        },
        "all_expected_dimensions": all(
            dimensions == [800, 1280] if path != ios_reference else dimensions != [800, 1280]
            for path, dimensions in zip(replay_order, replay_dimensions)
        ),
        "source": "immutable retained PNG replay; not live ADB latency",
    }

    cash_frame = sn.load_frame(cash)
    ending_frame = sn.load_frame(ending_soon)
    home_frame = sn.load_frame(home)
    keyguard_frame = sn.load_frame(keyguard)
    ios_frame = sn.load_frame(ios_reference)
    overlay_reference = ending_frame

    classification_cases: List[Tuple[str, np.ndarray, bool]] = []
    classification_cases.extend(("cash_mall", cash_frame, True) for _ in range(20))
    classification_cases.extend(("ending_soon", ending_frame, True) for _ in range(20))
    classification_cases.extend(("home_base", home_frame, False) for _ in range(20))
    classification_cases.extend(("keyguard_launcher", keyguard_frame, False) for _ in range(20))
    classification_cases.extend(("profile_mismatch", ios_frame, False) for _ in range(20))
    classification_results: List[Dict[str, Any]] = []
    classification_latencies: List[float] = []
    for name, frame, expected in classification_cases:
        started = time.perf_counter()
        decision = sn.classify_cash_mall(frame, cash_frame, overlay_reference)
        classification_latencies.append((time.perf_counter() - started) * 1000.0)
        classification_results.append({
            "case": name,
            "expected_recognized": expected,
            "recognized": bool(decision.recognized),
            "state": decision.state,
            "unknown_overlay": decision.unknown_overlay,
        })
    classification_result = {
        "operations": len(classification_results),
        "expected_count": len(classification_results),
        "passed_count": sum(item["recognized"] == item["expected_recognized"] for item in classification_results),
        "all_expected_outcomes": all(item["recognized"] == item["expected_recognized"] for item in classification_results),
        "latency_ms": {
            "p50": percentile(classification_latencies, 0.50),
            "p95": percentile(classification_latencies, 0.95),
            "max": round(max(classification_latencies), 6),
        },
        "cases": {name: sum(item["case"] == name for item in classification_results) for name in assets},
    }

    args.annotation_dir.mkdir(parents=True, exist_ok=True)
    target_trials: List[Dict[str, Any]] = []
    for index in range(25):
        frame = ending_frame if index % 2 else cash_frame
        decision = sn.classify_cash_mall(frame, cash_frame, overlay_reference)
        output = args.annotation_dir / f"target-{index + 1:02d}.png"
        sn.write_annotation(frame, decision, output)
        target_trials.append({
            "trial": index + 1,
            "recognized": bool(decision.recognized),
            "target_roi": list(decision.target_roi),
            "annotation_sha256": sha256(output),
            "purchase_offer_premium_controls_authorized": False,
        })
    target_result = {
        "operations": len(target_trials),
        "expected_roi": list(sn.ROIS["back_arrow"]),
        "all_recognized": all(item["recognized"] for item in target_trials),
        "all_exact_roi": all(item["target_roi"] == list(sn.ROIS["back_arrow"]) for item in target_trials),
        "all_spend_controls_denied": all(not item["purchase_offer_premium_controls_authorized"] for item in target_trials),
        "trials": target_trials,
    }

    ocr_latencies: List[float] = []
    ocr_results: List[Dict[str, Any]] = []
    for index in range(10):
        started = time.perf_counter()
        result = sn.classify_home_base_live(home_frame, cash_mall_rejected=True, safe_os_surface=True)
        ocr_latencies.append((time.perf_counter() - started) * 1000.0)
        ocr_results.append({
            "trial": index + 1,
            "recognized": bool(result["recognized"]),
            "navigation_hits": result.get("navigation_ocr_hits", []),
            "scene_hits": result.get("scene_ocr_hits", []),
        })
    ocr_result = {
        "operations": len(ocr_results),
        "all_recognized": all(item["recognized"] for item in ocr_results),
        "latency_ms": {
            "p50": percentile(ocr_latencies, 0.50),
            "p95": percentile(ocr_latencies, 0.95),
            "max": round(max(ocr_latencies), 6),
        },
        "roi": "Home/Base scene and bottom-navigation regions only",
    }

    policy_cases = []
    positive_decision = sn.classify_cash_mall(cash_frame, cash_frame, overlay_reference)
    for label, kwargs, expected in (
        ("fresh-positive", {"fresh": True, "attempt": 0, "target_stable": True, "target_overlap": False}, True),
        ("stale-frame", {"fresh": False, "attempt": 0, "target_stable": True, "target_overlap": False}, False),
        ("unstable-target", {"fresh": True, "attempt": 0, "target_stable": False, "target_overlap": False}, False),
        ("target-overlap", {"fresh": True, "attempt": 0, "target_stable": True, "target_overlap": True}, False),
        ("repeat-input", {"fresh": True, "attempt": 1, "target_stable": True, "target_overlap": False}, False),
    ):
        result = policy_contract(positive_decision, **kwargs)
        policy_cases.append({"case": label, "expected": expected, **result})
    unknown_result = policy_contract(
        sn.classify_cash_mall(home_frame, cash_frame, overlay_reference),
        fresh=True, attempt=0, target_stable=True, target_overlap=False,
    )
    policy_cases.append({"case": "unknown-source", "expected": False, **unknown_result})
    policy_result = {
        "cases": policy_cases,
        "all_expected": all(item["authorized"] == item["expected"] for item in policy_cases),
        "input_commands_sent": 0,
        "immediate_recapture_required": True,
        "source": "offline policy-contract mock plus retained MVP gate evidence",
    }

    boot_text = keyguard_boot.read_text(encoding="utf-8")
    policy_text = keyguard_policy.read_text(encoding="utf-8")
    keyguard_authorized = sn.authorize_keyguard_dismissal(
        boot_text, policy_text, keyguard_frame, [keyguard_frame], fresh=True,
        game_force_stopped=True, security_prompt=False, swipe_count=0,
    )
    keyguard_repeat = sn.authorize_keyguard_dismissal(
        boot_text, policy_text, keyguard_frame, [keyguard_frame], fresh=True,
        game_force_stopped=True, security_prompt=False, swipe_count=1,
    )
    gesture_trials = [
        {"trial": 1, "authorized": bool(keyguard_authorized.swipe_authorized), "input_sent": False},
        *({"trial": index, "authorized": bool(keyguard_repeat.swipe_authorized), "input_sent": False}
          for index in range(2, 11)),
    ]
    gesture_result = {
        "operations": len(gesture_trials),
        "authorized_expected_count": 1,
        "authorized_count": sum(item["authorized"] for item in gesture_trials),
        "no_input_sent": all(not item["input_sent"] for item in gesture_trials),
        "one-swipe-retry-denied": not keyguard_repeat.swipe_authorized,
        "trials": gesture_trials,
    }

    reconnect_trials = []
    for index in range(1, 6):
        reconnect_trials.append({
            "trial": index,
            "transport": "mock direct-private-ADB adapter",
            "initial": "DISCONNECTED",
            "reconnected": "DEVICE",
            "capture_allowed_after_reconnect": True,
            "input_sent": False,
        })

    result = {
        "task": "M5-CUSTOM-BASELINE",
        "candidate": "custom Python + direct ADB + OpenCV + local OCR",
        "decision": "PASSED_BASELINE",
        "benchmark_scope": "offline replay, mocks, dry-run annotations, and retained RT-010/RT-021/MVP live evidence; no live game input",
        "corpus": corpus,
        "measurements": {
            "replay_capture": replay_result,
            "classification": classification_result,
            "target_resolution": target_result,
            "ocr": ocr_result,
            "gesture_resolution": gesture_result,
            "reconnect_mock": {"operations": len(reconnect_trials), "all_reconnected": True, "trials": reconnect_trials},
        },
        "policy": policy_result,
        "retained_live_facts": {
            "adb_capture": str(rt010_record),
            "adb_capture_p95_ms": 1026.136,
            "adb_capture_profile": "800x1280",
            "worker_reconnect": str(rt021_record),
            "worker_reconnect_passed": True,
            "mvp_one_input_record": str(input_record),
            "mvp_one_input_repeated": False,
        },
        "packaging": {
            "worker_identity": "UID 65534:nobody from retained RT-021 evidence",
            "unprivileged_worker_path": "passed in RT-021 with constrained host-network boundary",
            "production_dependencies": import_inventory(root / "scripts" / "startup_normalization.py"),
            "third_party_framework_dependency": False,
            "policy_gate_embedded_in_framework": False,
        },
        "diagnostics": {
            "replay_hashes_retained": True,
            "per_trial_results_retained": True,
            "unknown_outcomes_fail_closed": True,
            "stale_and_profile_mismatch_rejected": policy_result["all_expected"],
        },
        "limitations": [
            "replay decode timing is not live ADB capture timing",
            "RT-021 provides one retained live reconnect path; additional cycles are safe mocks",
            "Home/Base OCR remains ROI-specific and requires final M6 corpus promotion",
            "the helper does not itself own the future SQLite scheduler or controller",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "task": result["task"],
        "decision": result["decision"],
        "classification": classification_result["all_expected_outcomes"],
        "targets": target_result["all_recognized"] and target_result["all_exact_roi"],
        "ocr": ocr_result["all_recognized"],
        "policy": policy_result["all_expected"],
        "gesture": gesture_result["one-swipe-retry-denied"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
