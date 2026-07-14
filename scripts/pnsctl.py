#!/usr/bin/env python3
"""Reproducible operator interface for the Unraid-hosted Bliss trial.

Only this checked-in interface owns the routine worker, private ADB, validation, evidence, and
cleanup commands.  Credentials are read from the project .env for the lifetime of one subprocess
call and are never printed, serialized, or written to evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from shlex import quote
from typing import Any, Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
HOST = "nas.local"
HOST_KEY = "ssh-ed25519 255 f0:b5:ee:95:fb:d2:6c:e5:f5:bf:d2:86:67:9b:21:55"
PACKAGE = "com.global.ztmslg"
ACTIVITY = "com.global.ztmslg/.MainActivity"
SERIAL = "192.168.122.79:5555"
ADB_SOCKET = "tcp:127.0.0.1:5042"
ADB_HOST_PATH = "/mnt/cache/domains/PnS-BlissOS-PoC/tools/platform-tools/adb"
IMAGE = "pns-mvp-quest-to-claim:20260712-navigation-v2"
REMOTE_BASE = "/mnt/cache/puzzle-survival-runtime/mvp-quest-to-claim/20260713-help-all"
CONTAINER = "pns-mvp-help-all-20260713"
REMOTE_WORKSPACE = REMOTE_BASE + "/workspace"
REMOTE_EVIDENCE = REMOTE_BASE + "/evidence"
REMOTE_DB = REMOTE_EVIDENCE + "/actions.sqlite3"
M6_ASSET_ROOT = "evidence/sessions/20260712-m6-dq-bootstrap/assets"
CASH_REFERENCE = "evidence/sessions/20260711-rt-012-observe-soak/cash-mall-startup-reference.png"
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class OperatorError(RuntimeError):
    pass


@dataclass(frozen=True)
class OperatorConfig:
    repo_root: Path = REPO_ROOT
    host: str = HOST
    host_key: str = HOST_KEY
    image: str = IMAGE
    container: str = CONTAINER
    remote_base: str = REMOTE_BASE
    remote_workspace: str = REMOTE_WORKSPACE
    remote_evidence: str = REMOTE_EVIDENCE
    remote_database: str = REMOTE_DB
    adb_host_path: str = ADB_HOST_PATH
    adb_socket: str = ADB_SOCKET
    serial: str = SERIAL
    package: str = PACKAGE
    activity: str = ACTIVITY


def load_credentials(env_path: Path | None = None) -> tuple[str, str]:
    """Load the approved process-only credentials without logging their values."""
    path = env_path or REPO_ROOT / ".env"
    values: dict[str, str] = {}
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name in {"UNRAID_TEMP_USERNAME", "UNRAID_TEMP_PASSWORD"}:
                values[name] = value.strip().strip('"').strip("'")
    values.setdefault("UNRAID_TEMP_USERNAME", os.environ.get("UNRAID_TEMP_USERNAME", ""))
    values.setdefault("UNRAID_TEMP_PASSWORD", os.environ.get("UNRAID_TEMP_PASSWORD", ""))
    if not values["UNRAID_TEMP_USERNAME"] or not values["UNRAID_TEMP_PASSWORD"]:
        raise OperatorError("approved Unraid credentials are not available in the process environment")
    return values["UNRAID_TEMP_USERNAME"], values["UNRAID_TEMP_PASSWORD"]


def redact_argv(argv: Sequence[str]) -> list[str]:
    result = list(argv)
    for index, item in enumerate(result[:-1]):
        if item == "-pw":
            result[index + 1] = "<process-only-password>"
    return result


def _plink_argv(cfg: OperatorConfig, command: str) -> list[str]:
    username, password = load_credentials()
    return [
        str(Path("/mnt/c/Program Files/PuTTY/plink.exe")), "-batch", "-hostkey", cfg.host_key,
        "-pw", password, f"{username}@{cfg.host}", command,
    ]


def run_remote(cfg: OperatorConfig, command: str) -> str:
    result = subprocess.run(_plink_argv(cfg, command), check=False, capture_output=True, text=True)
    if result.returncode:
        detail = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
        raise OperatorError("remote command failed:\n" + detail)
    return result.stdout


def _windows_path(value: str) -> str:
    if value.startswith("/mnt/") and len(value) > 6:
        drive = value[5].upper()
        return drive + ":/" + value[7:]
    return value


def _pscp_argv(cfg: OperatorConfig, sources: Iterable[str], destination: str, recursive: bool = False, *, local_sources: bool = True, local_destination: bool = False) -> list[str]:
    username, password = load_credentials()
    args = [str(Path("/mnt/c/Program Files/PuTTY/pscp.exe")), "-batch", "-hostkey", cfg.host_key, "-pw", password]
    if recursive:
        args.append("-r")
    args.extend(_windows_path(source) if local_sources else f"{username}@{cfg.host}:{source}" for source in sources)
    if local_destination:
        args.append(_windows_path(destination))
    else:
        args.append(f"{username}@{cfg.host}:{destination}")
    return args


def run_pscp(cfg: OperatorConfig, sources: Iterable[str], destination: str, recursive: bool = False, *, local_sources: bool = True, local_destination: bool = False) -> None:
    result = subprocess.run(_pscp_argv(cfg, sources, destination, recursive, local_sources=local_sources, local_destination=local_destination), check=False, capture_output=True, text=True)
    if result.returncode:
        raise OperatorError("evidence/workspace synchronization failed: " + result.stderr.strip())


def _adb_shell(cfg: OperatorConfig, command: str) -> str:
    script = (
        "if test -x /opt/adb; then adb_bin=/opt/adb; else adb_bin=$(command -v adb); fi; "
        "export HOME=/tmp; export ADB_SERVER_PORT=5042; unset ADB_SERVER_SOCKET; "
        f"exec \"$adb_bin\" -s {quote(cfg.serial)} {command}"
    )
    return (
        f"docker exec -e ADB_SERVER_SOCKET={quote(cfg.adb_socket)} {quote(cfg.container)} "
        f"sh -lc {quote(script)}"
    )


def _safe_name(value: str) -> str:
    if not NAME_RE.fullmatch(value):
        raise OperatorError("operation name must contain only letters, numbers, dot, dash, or underscore")
    return value


def sync_workspace(cfg: OperatorConfig) -> None:
    run_remote(cfg, f"mkdir -p {quote(cfg.remote_workspace)}/evidence/sessions/20260712-m6-dq-bootstrap/assets {quote(cfg.remote_workspace)}/evidence/sessions/20260711-rt-012-observe-soak {quote(cfg.remote_workspace)}/evidence/sessions/20260712-mvp-quest-to-claim/promotional-escape {quote(cfg.remote_workspace)}/evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/remote-complete {quote(cfg.remote_workspace)}/evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/help-all-validation-20260713/remote {quote(cfg.remote_workspace)}/evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/help-all-semantic-fix-20260713/remote")
    sources = ["scripts", "tasks", "safe_action_core", "runtime-profile", "tests"]
    for source in sources:
        run_pscp(cfg, [str(cfg.repo_root / source)], cfg.remote_workspace, recursive=True)
    run_pscp(cfg, [str(cfg.repo_root / CASH_REFERENCE)], cfg.remote_workspace + "/evidence/sessions/20260711-rt-012-observe-soak/")
    run_pscp(cfg, [str(cfg.repo_root / "evidence/sessions/20260712-m6-dq-bootstrap/assets")], cfg.remote_workspace + "/evidence/sessions/20260712-m6-dq-bootstrap/", recursive=True)
    run_pscp(cfg, [str(cfg.repo_root / "evidence/sessions/20260712-mvp-quest-to-claim/promotional-escape")], cfg.remote_workspace + "/evidence/sessions/20260712-mvp-quest-to-claim/", recursive=True)
    run_pscp(cfg, [str(cfg.repo_root / "evidence/sessions/20260712-mvp-quest-to-claim/daily-postreset-observation-20260713.png")], cfg.remote_workspace + "/evidence/sessions/20260712-mvp-quest-to-claim/")
    run_pscp(cfg, [str(cfg.repo_root / "evidence/sessions/20260712-mvp-quest-to-claim/reset-reconcile-current.png")], cfg.remote_workspace + "/evidence/sessions/20260712-mvp-quest-to-claim/")
    run_pscp(cfg, [str(cfg.repo_root / "evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/remote-complete/help-go-post-002.png")], cfg.remote_workspace + "/evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/remote-complete/")
    run_pscp(cfg, [str(cfg.repo_root / "evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/actions-after-release.sqlite3")], cfg.remote_workspace + "/evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/")
    run_pscp(cfg, [str(cfg.repo_root / "evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/help-all-validation-20260713/remote/alliance-help-1783981635-source.png"), str(cfg.repo_root / "evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/help-all-validation-20260713/remote/alliance-help-1783981635-post-1.png")], cfg.remote_workspace + "/evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/help-all-validation-20260713/remote/")
    run_pscp(cfg, [str(cfg.repo_root / "evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/help-all-semantic-fix-20260713/remote/alliance-help-1783986842-post-1.png")], cfg.remote_workspace + "/evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/help-all-semantic-fix-20260713/remote/")


def worker_start(cfg: OperatorConfig) -> str:
    sync_workspace(cfg)
    command = f"""
set -eu
mkdir -p {quote(cfg.remote_evidence)}
chown -R 65534:65534 {quote(cfg.remote_evidence)}
if docker inspect {quote(cfg.container)} >/dev/null 2>&1; then
  docker ps --filter name=^{re.escape(cfg.container)}$ --format '{{{{.Names}}}} {{{{.Status}}}}'
  exit 0
fi
adb_mount=''
if test -x {quote(cfg.adb_host_path)}; then adb_mount='-v {quote(cfg.adb_host_path)}:/opt/adb:ro'; fi
docker run -d --name {quote(cfg.container)} --network host --user 65534:65534 --read-only \\
  --tmpfs /tmp:rw,noexec,nosuid,size=256m --pids-limit 256 --memory 2g --cpus 2 \\
  --cap-drop ALL --security-opt no-new-privileges \\
  -v {quote(cfg.remote_workspace)}:/workspace:ro -v {quote(cfg.remote_evidence)}:/evidence:rw \\
  $adb_mount -w /workspace {quote(cfg.image)} sh -lc 'exec tail -f /dev/null'
"""
    return run_remote(cfg, command)


def worker_status(cfg: OperatorConfig) -> str:
    return run_remote(cfg, f"docker ps -a --filter name=^{re.escape(cfg.container)}$ --format '{{{{.Names}}}} {{{{.Status}}}}'")


def worker_stop(cfg: OperatorConfig) -> str:
    return run_remote(cfg, f"docker rm -f {quote(cfg.container)} 2>/dev/null || true")


def adb_start(cfg: OperatorConfig) -> str:
    command = (
        f"docker exec -e ADB_SERVER_SOCKET={quote(cfg.adb_socket)} {quote(cfg.container)} "
        "sh -lc 'if test -x /opt/adb; then adb_bin=/opt/adb; else adb_bin=$(command -v adb); fi; "
        "export HOME=/tmp; export ADB_SERVER_PORT=5042; unset ADB_SERVER_SOCKET; \"$adb_bin\" start-server; "
        f"\"$adb_bin\" -s {quote(cfg.serial)} connect {quote(cfg.serial)}; \"$adb_bin\" devices'"
    )
    return run_remote(cfg, command)


def launch(cfg: OperatorConfig) -> str:
    return run_remote(cfg, _adb_shell(cfg, f"shell am start -W -n {quote(cfg.activity)}"))


def capture(cfg: OperatorConfig, name: str) -> str:
    name = _safe_name(name)
    remote_path = f"{cfg.remote_evidence}/{name}.png"
    return run_remote(cfg, f"{_adb_shell(cfg, 'exec-out screencap -p')} > {quote(remote_path)}")


def observe(cfg: OperatorConfig, name: str) -> str:
    capture(cfg, name)
    status = run_remote(cfg, _adb_shell(cfg, "shell dumpsys window | grep -E 'mCurrentFocus|mFocusedApp' | head -2"))
    return json.dumps({"capture": name, "foreground": status.strip()}, sort_keys=True)


NAVIGATION_STEPS = {
    "cash-home": ("cash", "home", "HOME_BASE", "CASH_MALL_BACK", "standard-game-back-arrow", (45, 5, 130, 60)),
    "home-quest": ("home", "quest", "QUEST", "HOME_TO_QUEST", "home-quest-entry", (250, 1130, 410, 1280)),
    "quest-daily": ("quest", "daily", "DAILY_QUEST", "QUEST_TO_DAILY", "quest-daily-tab", (300, 70, 500, 140)),
}


def navigate(cfg: OperatorConfig, step: str) -> str:
    if step not in NAVIGATION_STEPS:
        raise OperatorError("navigate accepts only the checked-in route names: " + ", ".join(sorted(NAVIGATION_STEPS)))
    source_mode, expected_mode, expected_state, semantic, target, roi = NAVIGATION_STEPS[step]
    stamp = str(int(time.time()))
    args = [
        "python3", "scripts/mvp_quest_to_claim.py", "--cash-reference", "/workspace/evidence/sessions/20260711-rt-012-observe-soak/cash-mall-startup-reference.png",
        "--home-reference", "/workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/home-base-settled.png",
        "--quest-reference", "/workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/quest-main-settled.png",
        "--daily-reference", "/workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/daily-quest-settled.png",
        "--main-quest-reference", "/workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/quest-main-settled.png",
        "execute", "--database", "/evidence/actions.sqlite3", "--evidence", "/evidence",
        "--owner", "pnsctl-" + stamp, "--action-id", "nav-" + step + "-" + stamp,
        "--action-key", "nav-" + step + "-" + stamp, "--source-mode", source_mode,
        "--expected-mode", expected_mode, "--expected-state", expected_state, "--target", target,
        "--roi", *map(str, roi), "--semantic-action", semantic,
    ]
    command = _adb_shell(cfg, "")
    # Reuse the worker's interpreter and ADB environment without creating a second transport.
    command = f"docker exec -e HOME=/tmp -e ADB_SERVER_PORT=5042 {quote(cfg.container)} " + " ".join(quote(item) for item in args)
    return run_remote(cfg, command)


def run_task(cfg: OperatorConfig, task: str) -> str:
    stamp = str(int(time.time()))
    if task == "alliance-help":
        command = (
            f"docker exec -e HOME=/tmp -e ADB_SERVER_PORT=5042 {quote(cfg.container)} python3 scripts/alliance_help_live.py "
            f"--adb /opt/adb --serial {quote(cfg.serial)} --database /evidence/actions-help-all-semantic-fix.sqlite3 "
            f"--evidence /evidence --result /evidence/alliance-help-semantic-fix-result.json --owner pnsctl-{stamp} "
            f"--action-id alliance-help-{stamp} --action-key alliance-help-{stamp}"
        )
    elif task in {"vip-popup", "praise", "praise-route-evidence", "praise-leaderboard-evidence"}:
        popup_only = " --popup-only" if task == "vip-popup" else ""
        navigation_only = " --navigation-evidence-only" if task == "praise-route-evidence" else ""
        leaderboard_only = " --leaderboard-evidence-only" if task == "praise-leaderboard-evidence" else ""
        command = (
            f"docker exec -e HOME=/tmp -e ADB_SERVER_PORT=5042 {quote(cfg.container)} python3 scripts/personal_might_praise_live.py "
            f"--adb /opt/adb --serial {quote(cfg.serial)} --database /evidence/actions-praise-{stamp}.sqlite3 "
            f"--evidence /evidence --owner pnsctl-{stamp} --game-day daily-2026-07-13 "
            "--daily-reference /workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/daily-quest-settled.png "
            "--main-quest-reference /workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/quest-main-settled.png "
            "--home-reference /workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/home-base-settled.png "
            "--quest-reference /workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/quest-main-settled.png"
            + popup_only
            + navigation_only
            + leaderboard_only
        )
    else:
        raise OperatorError("requested task is not in the checked-in supervised task allowlist")
    return run_remote(cfg, command)


def test_command(cfg: OperatorConfig, focused: bool, pattern: str = "test_*.py") -> str:
    name = "pnsctl-focused-20260713" if focused else "pnsctl-full-20260713"
    selector = f"-p {quote(pattern)}" if focused else "-p 'test_*.py'"
    inner = f"python3 -m unittest discover -s tests {selector} 2>&1"
    command = (
        f"docker run --rm --name {name} --user 65534:65534 --read-only "
        f"--tmpfs /tmp:rw,noexec,nosuid,size=256m -v {quote(cfg.remote_workspace)}:/workspace:ro "
        f"-w /workspace {quote(cfg.image)} sh -lc {quote(inner)}"
    )
    return run_remote(cfg, command)


def validate(cfg: OperatorConfig) -> str:
    command = (
        f"docker run --rm --name pnsctl-validate-20260713 --user 65534:65534 --read-only "
        f"--tmpfs /tmp:rw,noexec,nosuid,size=256m -v {quote(cfg.remote_workspace)}:/workspace:ro "
        f"-w /workspace {quote(cfg.image)} sh -lc "
        "'python3 scripts/validate-runtime-profile.py && "
        "python3 scripts/daily_quest_bootstrap.py validate-assets "
        "--manifest evidence/sessions/20260712-m6-dq-bootstrap/assets/asset-manifest.json'"
    )
    return run_remote(cfg, command)


def preserve_evidence(cfg: OperatorConfig, destination: Path) -> str:
    destination.mkdir(parents=True, exist_ok=True)
    run_pscp(cfg, [cfg.remote_evidence + "/*"], str(destination), recursive=True, local_sources=False, local_destination=True)
    return str(destination)


def reconcile(args: argparse.Namespace) -> str:
    source = args.source
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, output)
    from safe_action_core import SafetyStore
    store = SafetyStore(output)
    try:
        row = store.get_action(args.action_id)
        if row["final_status"] != "unresolved":
            raise OperatorError("the retained action is not unresolved; refusing reinterpretation")
        if args.outcome == "positive_postcondition":
            reconciliation = {
                "confirmed": True, "reason": "help_all_control_disappeared_with_stable_speedup_header",
                "evidence": args.evidence, "source_database": str(source),
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
            store.mark_confirmed(args.action_id, time.time(), reconciliation)
            status, reason = "confirmed", "positive_postcondition"
        else:
            store.mark_cancelled(args.action_id, time.time(), "proven_no_effect_mistarget")
            status, reason = "cancelled", "proven_no_effect_mistarget"
        store.audit(
            "MVP-QUEST-TO-CLAIM", "manual_reconciliation", time.time(),
            {"action_id": args.action_id, "result": status, "evidence": args.evidence,
             "source_database": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
            args.action_id,
        )
        result = {"source": str(source), "output": str(output), "action_id": args.action_id, "status": status, "reason": reason}
    finally:
        store.close()
    return json.dumps(result, sort_keys=True)


def cleanup(cfg: OperatorConfig) -> str:
    worker_stop(cfg)
    return run_remote(cfg, "ss -ltn | grep -E ':(5042|5555)\\b' || true")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--run-id", default="help-all-20260713")
    sub = root.add_subparsers(dest="command", required=True)
    for name in ("preflight", "worker-start", "worker-status", "worker-stop", "adb-start", "launch", "capture", "observe", "navigate", "run-task", "test-focused", "test-full", "validate", "preserve-evidence", "cleanup"):
        sub.add_parser(name)
    sub.choices["capture"].add_argument("--name", default="current")
    sub.choices["observe"].add_argument("--name", default="observe")
    sub.choices["navigate"].add_argument("--step", required=True, choices=tuple(NAVIGATION_STEPS))
    sub.choices["run-task"].add_argument("--task", required=True, choices=("alliance-help", "vip-popup", "praise-route-evidence", "praise-leaderboard-evidence", "praise"))
    sub.choices["test-focused"].add_argument("--pattern", default="test_task_module.py")
    sub.choices["preserve-evidence"].add_argument("--destination", type=Path, required=True)
    rec = sub.add_parser("reconcile")
    rec.add_argument("--source", type=Path, required=True)
    rec.add_argument("--output", type=Path, required=True)
    rec.add_argument("--action-id", required=True)
    rec.add_argument("--evidence", nargs="+", required=True)
    rec.add_argument("--outcome", choices=("proven_no_effect", "positive_postcondition"), default="proven_no_effect")
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "reconcile":
        print(reconcile(args))
        return 0
    cfg = OperatorConfig()
    handlers = {
        "preflight": lambda: run_remote(cfg, "set -eu; printf 'vm='; virsh domstate PnS-BlissOS-PoC; printf 'worker='; docker ps --filter name=^%s$ --format '{{.Names}}' || true; printf 'listeners='; ss -ltn | grep -E ':(5037|5042|5555)\\b' || true; test -f /mnt/cache/domains/PnS-BlissOS-PoC/rollback/20260711-rt017-runtime-backup/system.qcow2 && echo backup=intact" % re.escape(cfg.container)),
        "worker-start": lambda: worker_start(cfg),
        "worker-status": lambda: worker_status(cfg),
        "worker-stop": lambda: worker_stop(cfg),
        "adb-start": lambda: adb_start(cfg),
        "launch": lambda: launch(cfg),
        "capture": lambda: capture(cfg, args.name),
        "observe": lambda: observe(cfg, args.name),
        "navigate": lambda: navigate(cfg, args.step),
        "run-task": lambda: run_task(cfg, args.task),
        "test-focused": lambda: test_command(cfg, True, args.pattern),
        "test-full": lambda: test_command(cfg, False),
        "validate": lambda: validate(cfg),
        "preserve-evidence": lambda: preserve_evidence(cfg, args.destination),
        "cleanup": lambda: cleanup(cfg),
    }
    try:
        output = handlers[args.command]()
        if output:
            print(output, end="" if output.endswith("\n") else "\n")
        return 0
    except (OperatorError, OSError, subprocess.SubprocessError) as exc:
        print("pnsctl: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
