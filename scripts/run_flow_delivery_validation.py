#!/usr/bin/env python3
"""Bounded checked-in validation runner for flow-delivery profiles."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
PROFILES_PATH = REPO_ROOT / "tasks" / "flow_delivery_validation_profiles.json"
QUEUE_PATH = REPO_ROOT / "tasks" / "flow_delivery_queue.json"
LOG_ROOT = REPO_ROOT / ".local-orchestrator" / "logs"
RECEIPT_ROOT = REPO_ROOT / ".local-orchestrator" / "validation-receipts"

PROFILE_ALIASES = {
    "focused": "focused_tests",
    "architecture": "architecture_tests",
    "full": "full_suite",
    "governance": "governance",
    # Proportionate profiles reserve the heavy full/architecture/governance load for
    # promotion and keep navigation development on light, targeted checks.
    "shared-navigation": "shared_navigation",
    "task-navigation": "focused_tests",
    "detector": "detector",
    "consequential": "consequential",
    "promotion": "promotion",
}
ALLOWED_PROFILES = set(PROFILE_ALIASES.values())
MAX_CONSOLE_FAILURE_CHARS = 1200


class ValidationRunnerError(RuntimeError):
    """Raised when a checked-in validation profile cannot run safely."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_profiles() -> dict[str, Any]:
    payload = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValidationRunnerError("unsupported validation profile schema")
    if payload.get("registry_kind") != "flow_delivery_validation_profiles":
        raise ValidationRunnerError("wrong validation profile registry kind")
    return payload


def _resolve_unittest_targets(
    profiles: Mapping[str, Any],
    *,
    profile: str,
    flow_id: str,
    queue: Mapping[str, Any],
) -> list[str]:
    global_profiles = profiles.get("global_profiles", {})
    flow_overrides = profiles.get("flow_profiles", {}).get(flow_id, {})
    if profile in flow_overrides:
        targets = flow_overrides[profile]
    elif profile in global_profiles:
        targets = global_profiles[profile]
    elif profile == "focused_tests":
        flow = next(item for item in queue["flows"] if item["flow_id"] == flow_id)
        targets = []
        for path in flow["focused_tests"]:
            if not path.startswith("tests/") or not path.endswith(".py"):
                raise ValidationRunnerError(f"focused test path must be tests/*.py: {path}")
            targets.append("tests." + path[6:-3].replace("/", "."))
    else:
        raise ValidationRunnerError(f"no checked-in targets for profile {profile}")
    if not isinstance(targets, list) or not targets:
        raise ValidationRunnerError(f"profile {profile} targets must be a non-empty list")
    if any(not isinstance(item, str) or not item.strip() for item in targets):
        raise ValidationRunnerError(f"profile {profile} targets must be non-empty strings")
    if any(re.search(r"[;\|&\s]", item) for item in targets if item != "discover"):
        raise ValidationRunnerError("validation targets must not contain shell metacharacters")
    if profile == "full_suite" and targets != ["discover"]:
        raise ValidationRunnerError("full_suite must use the checked-in discover target only")
    return list(targets)


def _repo_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _working_tree_fingerprint() -> str:
    from scripts.flow_delivery_context import working_tree_fingerprint

    return working_tree_fingerprint()


def _parse_test_count(output: str) -> int | None:
    match = re.search(r"Ran (\d+) tests?", output)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d+) passed", output)
    if match:
        return int(match.group(1))
    return None


def _stage_for_profile(profile: str) -> str:
    if profile in {"focused_tests", "architecture_tests", "governance"}:
        return "focused_validation"
    if profile in {"shared_navigation", "detector"}:
        return "navigation_validation"
    if profile == "consequential":
        return "consequential_validation"
    if profile == "promotion":
        return "promotion_validation"
    if profile == "full_suite":
        return "full_validation"
    raise ValidationRunnerError(f"unsupported profile: {profile}")


def run_profile(
    *,
    flow_id: str,
    profile_alias: str,
    stage: str | None = None,
) -> dict[str, Any]:
    if profile_alias not in PROFILE_ALIASES and profile_alias not in ALLOWED_PROFILES:
        raise ValidationRunnerError(f"unknown validation profile: {profile_alias}")
    profile = PROFILE_ALIASES.get(profile_alias, profile_alias)
    if profile not in ALLOWED_PROFILES:
        raise ValidationRunnerError(f"unsupported validation profile: {profile}")

    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    if not any(item["flow_id"] == flow_id for item in queue["flows"]):
        raise ValidationRunnerError(f"unknown flow_id: {flow_id}")
    profiles = _load_profiles()
    targets = _resolve_unittest_targets(profiles, profile=profile, flow_id=flow_id, queue=queue)
    delivery_stage = stage or _stage_for_profile(profile)
    head = _repo_head()
    fingerprint = _working_tree_fingerprint()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    log_dir = LOG_ROOT / flow_id / delivery_stage
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / f"{profile}-{stamp}.stdout.log"
    stderr_path = log_dir / f"{profile}-{stamp}.stderr.log"
    receipt_dir = RECEIPT_ROOT / flow_id / delivery_stage
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"{profile}-{stamp}.json"

    if profile == "full_suite" and targets == ["discover"]:
        command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]
    else:
        command = [sys.executable, "-m", "unittest", *targets]
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    elapsed = time.monotonic() - started
    stdout_path.write_bytes(completed.stdout.replace("\r\n", "\n").encode("utf-8"))
    stderr_path.write_bytes(completed.stderr.replace("\r\n", "\n").encode("utf-8"))
    combined = completed.stdout + "\n" + completed.stderr
    test_count = _parse_test_count(combined)
    artifact_paths = [
        str(stdout_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        str(stderr_path.relative_to(REPO_ROOT)).replace("\\", "/"),
    ]
    unsigned = {
        "schema_version": 1,
        "active_flow": flow_id,
        "repository_head": head,
        "working_tree_fingerprint": fingerprint,
        "delivery_stage": delivery_stage,
        "validation_profile": profile,
        "command_or_profile": f"checked-in:{profile}",
        "exit_code": int(completed.returncode),
        "timestamp": _utc_now(),
        "test_count": test_count,
        "artifact_paths": artifact_paths,
    }
    receipt = {**unsigned, "receipt_digest": _canonical_digest(unsigned)}
    with receipt_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(receipt, indent=2) + "\n")
    if completed.returncode != 0:
        summary = combined.strip().replace("\r\n", "\n")
        if len(summary) > MAX_CONSOLE_FAILURE_CHARS:
            summary = summary[: MAX_CONSOLE_FAILURE_CHARS - 20] + "\n...[truncated]..."
        print(
            json.dumps(
                {
                    "ok": False,
                    "flow_id": flow_id,
                    "profile": profile,
                    "exit_code": completed.returncode,
                    "log_dir": str(log_dir.relative_to(REPO_ROOT)).replace("\\", "/"),
                    "receipt_path": str(receipt_path.relative_to(REPO_ROOT)).replace("\\", "/"),
                    "summary": summary,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise ValidationRunnerError(f"validation profile failed: {profile}")
    result = {
        "ok": True,
        "flow_id": flow_id,
        "profile": profile,
        "delivery_stage": delivery_stage,
        "exit_code": 0,
        "test_count": test_count,
        "elapsed_seconds": round(elapsed, 3),
        "receipt_path": str(receipt_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "log_dir": str(log_dir.relative_to(REPO_ROOT)).replace("\\", "/"),
        "receipt_digest": receipt["receipt_digest"],
    }
    print(json.dumps(result, sort_keys=True))
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in (
        "focused",
        "architecture",
        "full",
        "governance",
        "shared-navigation",
        "task-navigation",
        "detector",
        "consequential",
        "promotion",
    ):
        command = sub.add_parser(name)
        command.add_argument("--flow-id", required=True)
        command.add_argument("--stage", default=None)
    args = parser.parse_args(argv)
    try:
        run_profile(flow_id=args.flow_id, profile_alias=args.command, stage=args.stage)
    except (ValidationRunnerError, OSError, subprocess.CalledProcessError, json.JSONDecodeError, StopIteration) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
