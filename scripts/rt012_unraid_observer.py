#!/usr/bin/env python3
"""RT-012 read-only observer for a temporary Unraid-local container.

The observer owns only the evidence directory supplied on the command line. It uses the
existing NAS-local ADB server for read-only Android observation, optionally starting the already
provisioned package without sending game input. Host/QEMU/NAS metrics are collected by the
companion host-side collector.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import platform
import pwd
import signal
import struct
import subprocess
import sys
import time
import zlib
from datetime import datetime, timedelta, timezone


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
STOP_REQUESTED = False


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def write_json(path: pathlib.Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_log(path: pathlib.Path, message: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{iso(utc_now())} {message}\n")


def stop_handler(signum: int, _frame: object) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True


def run_command(
    adb_path: str,
    arguments: list[str],
    *,
    binary: bool = False,
    timeout: int = 45,
) -> tuple[int, bytes | str, float]:
    started = time.perf_counter()
    completed = subprocess.run(
        [adb_path, *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    output: bytes | str = completed.stdout if binary else completed.stdout.decode("utf-8", "replace")
    return completed.returncode, output, elapsed_ms


def adb_text(adb_path: str, serial: str, arguments: list[str], timeout: int = 45) -> tuple[str, float]:
    code, output, elapsed_ms = run_command(
        adb_path,
        ["-s", serial, *arguments],
        timeout=timeout,
    )
    if code != 0:
        raise RuntimeError(f"adb exit {code}: {str(output).strip()[:1000]}")
    return str(output).strip(), elapsed_ms


def capture_png(adb_path: str, serial: str, path: pathlib.Path) -> float:
    code, output, elapsed_ms = run_command(
        adb_path,
        ["-s", serial, "exec-out", "screencap", "-p"],
        binary=True,
        timeout=60,
    )
    if code != 0:
        raise RuntimeError(f"screenshot adb exit {code}: {output[:1000]!r}")
    if not isinstance(output, bytes) or len(output) < 32:
        raise RuntimeError("screenshot output is empty or too small")
    path.write_bytes(output)
    return elapsed_ms


def decode_png_health(path: pathlib.Path) -> dict[str, object]:
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("invalid PNG signature")
    offset = len(PNG_SIGNATURE)
    width = height = bit_depth = color_type = interlace = None
    idat = bytearray()
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if chunk_end > len(data):
            raise ValueError("truncated PNG chunk")
        chunk = data[offset + 8 : offset + 8 + length]
        if chunk_type == b"IHDR":
            if length != 13:
                raise ValueError("invalid IHDR")
            width, height, bit_depth, color_type, _compression, _filter, interlace = struct.unpack(
                ">IIBBBBB", chunk
            )
        elif chunk_type == b"IDAT":
            idat.extend(chunk)
        elif chunk_type == b"IEND":
            break
        offset = chunk_end

    if width is None or height is None or bit_depth is None or color_type is None:
        raise ValueError("PNG has no IHDR")
    result: dict[str, object] = {
        "width": width,
        "height": height,
        "bytes": len(data),
        "decode_supported": False,
        "mostly_black": None,
        "dark_ratio": None,
        "mean_luma": None,
    }
    if bit_depth != 8 or color_type not in (0, 2, 4, 6) or interlace != 0:
        return result

    channels = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
    row_bytes = width * channels
    raw = zlib.decompress(bytes(idat))
    expected = (row_bytes + 1) * height
    if len(raw) != expected:
        raise ValueError(f"PNG decoded byte count {len(raw)} != {expected}")

    previous = bytearray(row_bytes)
    dark = 0
    total = 0
    luma_total = 0.0
    for y in range(height):
        row_start = y * (row_bytes + 1)
        filter_type = raw[row_start]
        encoded = raw[row_start + 1 : row_start + 1 + row_bytes]
        row = bytearray(row_bytes)
        for index, value in enumerate(encoded):
            left = row[index - channels] if index >= channels else 0
            up = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = up
            elif filter_type == 3:
                predictor = (left + up) // 2
            elif filter_type == 4:
                estimate = left + up - upper_left
                pa = abs(estimate - left)
                pb = abs(estimate - up)
                pc = abs(estimate - upper_left)
                predictor = left if pa <= pb and pa <= pc else up if pb <= pc else upper_left
            else:
                raise ValueError(f"unsupported PNG filter {filter_type}")
            row[index] = (value + predictor) & 0xFF

        for x in range(0, width, max(1, width // 40)):
            pixel = x * channels
            if color_type == 0:
                luma = float(row[pixel])
            elif color_type == 2:
                luma = 0.2126 * row[pixel] + 0.7152 * row[pixel + 1] + 0.0722 * row[pixel + 2]
            elif color_type == 4:
                luma = float(row[pixel])
            else:
                luma = 0.2126 * row[pixel] + 0.7152 * row[pixel + 1] + 0.0722 * row[pixel + 2]
            total += 1
            luma_total += luma
            if luma < 8:
                dark += 1
        previous = row

    dark_ratio = dark / total if total else 1.0
    result.update(
        {
            "decode_supported": True,
            "mostly_black": dark_ratio >= 0.98,
            "dark_ratio": round(dark_ratio, 6),
            "mean_luma": round(luma_total / total, 3) if total else 0.0,
        }
    )
    return result


def digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()


def evidence_bytes(root: pathlib.Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--adb", default="/opt/adb")
    parser.add_argument("--serial", default="192.168.122.79:5555")
    parser.add_argument("--duration-hours", type=int, default=4)
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--max-evidence-mib", type=int, default=512)
    parser.add_argument("--expected-width", type=int, default=800)
    parser.add_argument("--expected-height", type=int, default=1280)
    parser.add_argument("--package", default="com.global.ztmslg")
    parser.add_argument("--activity", default="com.games37.sdk.AtlasPluginDemoActivity")
    parser.add_argument("--vm-name", default="PnS-BlissOS-PoC")
    parser.add_argument("--launch-game", action="store_true")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    root = pathlib.Path(args.output).resolve()
    frames = root / "frames"
    android = root / "android"
    root.mkdir(parents=True, exist_ok=True)
    frames.mkdir(exist_ok=True)
    android.mkdir(exist_ok=True)
    log_path = root / "observer.log"
    start = utc_now()
    deadline = start + timedelta(hours=args.duration_hours)
    user = pwd.getpwuid(os.getuid()).pw_name if hasattr(os, "getuid") else "unknown"
    identity = {
        "observer": "rt012_unraid_observer.py",
        "pid": os.getpid(),
        "uid": os.getuid() if hasattr(os, "getuid") else None,
        "user": user,
        "hostname": platform.node(),
        "started_at": iso(start),
        "expected_end_at": iso(deadline),
        "output_directory": str(root),
        "interval_seconds": args.interval_seconds,
        "duration_hours": args.duration_hours,
        "max_evidence_bytes": args.max_evidence_mib * 1024 * 1024,
        "adb_path": args.adb,
        "serial": args.serial,
        "vm_name": args.vm_name,
        "package": args.package,
        "activity": args.activity,
        "launch_game": args.launch_game,
        "gameplay_input_sent": False,
        "credential_or_tutorial_automation": False,
        "argv": sys.argv,
    }
    write_json(root / "observer-identity.json", identity)
    append_log(log_path, "observer started; read-only game observation")
    append_log(log_path, f"started_at={identity['started_at']} expected_end_at={identity['expected_end_at']}")

    sample_records: list[dict[str, object]] = []
    stop_reason = "duration"
    run_error: str | None = None
    adb_failures = 0
    invalid_frames = 0
    black_frames = 0
    non_foreground = 0
    hard_stop = False
    startup_system_control_used = False
    previous_hash: str | None = None
    duplicate_run = 0
    max_duplicate_run = 0

    try:
        code, output, _ = run_command(args.adb, ["connect", args.serial], timeout=30)
        append_log(log_path, f"adb_connect_exit={code} result={str(output).strip()[:500]}")
        state, _ = adb_text(args.adb, args.serial, ["get-state"])
        boot, _ = adb_text(args.adb, args.serial, ["shell", "getprop", "sys.boot_completed"])
        if state != "device" or boot != "1":
            raise RuntimeError(f"ADB not ready: state={state} boot={boot}")

        display, _ = adb_text(args.adb, args.serial, ["shell", "wm", "size"])
        density, _ = adb_text(args.adb, args.serial, ["shell", "wm", "density"])
        rotation, _ = adb_text(args.adb, args.serial, ["shell", "wm", "user-rotation"])
        renderer, _ = adb_text(args.adb, args.serial, ["shell", "getprop", "ro.hardware.egl"])
        profile = {
            "display": display,
            "density": density,
            "rotation": rotation,
            "renderer": renderer,
            "expected_width": args.expected_width,
            "expected_height": args.expected_height,
            "profile_match": (
                f"Override size: {args.expected_width}x{args.expected_height}" in display
                and "160" in density
                and "mesa" in renderer.lower()
            ),
        }
        write_json(root / "android-profile.json", profile)
        if not profile["profile_match"]:
            raise RuntimeError(f"unexpected runtime profile: {profile}")

        policy, _ = adb_text(args.adb, args.serial, ["shell", "dumpsys", "window", "policy"])
        if "mInputRestricted=true" in policy:
            # This is the plan-approved non-game startup keyguard sequence only. It is never sent
            # during a sample and is recorded explicitly as system control, not gameplay input.
            for keyevent in ("KEYCODE_WAKEUP", "82"):
                adb_text(args.adb, args.serial, ["shell", "input", "keyevent", keyevent])
            adb_text(args.adb, args.serial, ["shell", "cmd", "window", "dismiss-keyguard"])
            startup_system_control_used = True
            append_log(log_path, "approved non-game keyguard dismissal used")

        if args.launch_game:
            launch, _ = adb_text(
                args.adb,
                args.serial,
                ["shell", "am", "start", "-W", "-n", f"{args.package}/{args.activity}"],
                timeout=90,
            )
            (root / "game-launch.txt").write_text(launch + "\n", encoding="utf-8")
            time.sleep(30)

        while utc_now() < deadline and not STOP_REQUESTED:
            sample_started = utc_now()
            sample_number = len(sample_records) + 1
            frame_name = f"frame-{sample_number:05d}.png"
            frame_path = frames / frame_name
            sample: dict[str, object] = {
                "sample": sample_number,
                "captured_at": iso(sample_started),
                "elapsed_seconds": round((sample_started - start).total_seconds(), 3),
                "adb_healthy": False,
                "capture_ms": None,
                "frame": None,
                "game_foreground": None,
                "window_focus": None,
                "surface_list_digest": None,
                "activity_digest": None,
                "error": None,
                "hard_stop_signals": [],
            }
            try:
                state, _ = adb_text(args.adb, args.serial, ["get-state"])
                boot, _ = adb_text(args.adb, args.serial, ["shell", "getprop", "sys.boot_completed"])
                if state != "device" or boot != "1":
                    raise RuntimeError(f"ADB state not ready: state={state} boot={boot}")
                sample["adb_healthy"] = True
                capture_ms = capture_png(args.adb, args.serial, frame_path)
                health = decode_png_health(frame_path)
                frame_hash = hashlib.sha256(frame_path.read_bytes()).hexdigest()
                if frame_hash == previous_hash:
                    duplicate_run += 1
                else:
                    duplicate_run = 0
                previous_hash = frame_hash
                max_duplicate_run = max(max_duplicate_run, duplicate_run)
                health.update(
                    {
                        "sha256": frame_hash,
                        "valid_dimensions": health["width"] == args.expected_width
                        and health["height"] == args.expected_height,
                        "duplicate_run": duplicate_run,
                    }
                )
                sample["capture_ms"] = round(capture_ms, 3)
                sample["frame"] = {"path": f"frames/{frame_name}", **health}
                if not health["valid_dimensions"]:
                    invalid_frames += 1
                if health["mostly_black"] is True:
                    black_frames += 1

                activity, _ = adb_text(args.adb, args.serial, ["shell", "dumpsys", "activity", "top"])
                windows, _ = adb_text(args.adb, args.serial, ["shell", "dumpsys", "window", "windows"])
                surfaces, _ = adb_text(args.adb, args.serial, ["shell", "dumpsys", "SurfaceFlinger", "--list"])
                focus_lines = [
                    line.strip()
                    for line in windows.splitlines()
                    if "mCurrentFocus" in line or "mFocusedApp" in line
                ]
                sample["window_focus"] = focus_lines[:10]
                sample["surface_list_digest"] = digest_text(surfaces)
                sample["activity_digest"] = digest_text(activity)
                foreground = args.package in activity
                sample["game_foreground"] = foreground
                if not foreground:
                    non_foreground += 1
                combined = f"{activity}\n{windows}".lower()
                signals = [
                    word
                    for word in (
                        "login required",
                        "log in",
                        "tutorial",
                        "captcha",
                        "verification code",
                        "session expired",
                        "wrong account",
                        "account restoration",
                    )
                    if word in combined
                ]
                sample["hard_stop_signals"] = signals
                if signals:
                    hard_stop = True
                    stop_reason = "account_or_session_hard_stop"
                    append_log(log_path, f"hard-stop signal at sample={sample_number}: {signals}")
            except Exception as exc:  # retain the failed sample and continue to collect evidence
                adb_failures += 1
                sample["error"] = str(exc)
                append_log(log_path, f"sample={sample_number} error={exc}")

            sample_records.append(sample)
            with (root / "samples.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(sample, sort_keys=True) + "\n")
            write_json(
                root / "observer-state.json",
                {
                    "last_sample": sample_number,
                    "last_sample_at": sample["captured_at"],
                    "samples": len(sample_records),
                    "expected_end_at": iso(deadline),
                    "stop_requested": STOP_REQUESTED,
                    "stop_reason": stop_reason,
                    "evidence_bytes": evidence_bytes(root),
                },
            )
            if hard_stop:
                break
            if evidence_bytes(root) > args.max_evidence_mib * 1024 * 1024:
                stop_reason = "evidence_quota"
                break

            next_sample = start + timedelta(seconds=len(sample_records) * args.interval_seconds)
            remaining = (next_sample - utc_now()).total_seconds()
            while remaining > 0 and not STOP_REQUESTED:
                time.sleep(min(remaining, 1.0))
                remaining = (next_sample - utc_now()).total_seconds()
        if STOP_REQUESTED:
            stop_reason = "signal"
    except Exception as exc:
        run_error = str(exc)
        stop_reason = "error"
        append_log(log_path, f"run_error={run_error}")
    finally:
        run_end = utc_now()
        try:
            run_command(args.adb, ["disconnect", args.serial], timeout=30)
        except Exception as exc:
            append_log(log_path, f"adb_disconnect_error={exc}")

        capture_values = [
            float(sample["capture_ms"])
            for sample in sample_records
            if isinstance(sample.get("capture_ms"), (int, float))
        ]
        valid_frames = sum(
            1
            for sample in sample_records
            if isinstance(sample.get("frame"), dict) and sample["frame"].get("valid_dimensions")
        )
        summary = {
            "generated_at": iso(run_end),
            "started_at": iso(start),
            "ended_at": iso(run_end),
            "expected_end_at": iso(deadline),
            "duration_hours_requested": args.duration_hours,
            "duration_completed": stop_reason == "duration" and run_end >= deadline,
            "interval_seconds": args.interval_seconds,
            "samples": len(sample_records),
            "expected_width": args.expected_width,
            "expected_height": args.expected_height,
            "startup_system_control_used": startup_system_control_used,
            "gameplay_input_sent": False,
            "credential_or_tutorial_automation": False,
            "adb_failures": adb_failures,
            "invalid_frames": invalid_frames,
            "black_frames": black_frames,
            "non_foreground_samples": non_foreground,
            "valid_frames": valid_frames,
            "capture_ms_p50": sorted(capture_values)[len(capture_values) // 2] if capture_values else None,
            "capture_ms_p95": (
                sorted(capture_values)[min(len(capture_values) - 1, int(len(capture_values) * 0.95))]
                if capture_values
                else None
            ),
            "unique_hashes": len(
                {
                    sample["frame"]["sha256"]
                    for sample in sample_records
                    if isinstance(sample.get("frame"), dict) and sample["frame"].get("sha256")
                }
            ),
            "max_duplicate_run": max_duplicate_run,
            "hard_stop_observed": hard_stop,
            "evidence_bytes": evidence_bytes(root),
            "evidence_quota_bytes": args.max_evidence_mib * 1024 * 1024,
            "stop_reason": stop_reason,
            "run_error": run_error,
            "manual_visual_review_required": True,
            "host_metrics_review_required": True,
            "all_observer_criteria_met": (
                stop_reason == "duration"
                and run_end >= deadline
                and len(sample_records) > 0
                and adb_failures == 0
                and invalid_frames == 0
                and black_frames == 0
                and non_foreground == 0
                and not hard_stop
                and max_duplicate_run < 12
            ),
        }
        write_json(root / "summary.json", summary)
        append_log(log_path, f"observer ended stop_reason={stop_reason} samples={len(sample_records)}")

    return 0 if summary["all_observer_criteria_met"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
