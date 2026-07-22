#!/usr/bin/env python3
"""Reproducible operator interface for the Unraid-hosted Bliss trial.

Only this checked-in interface owns the routine worker, private ADB, validation, evidence, and
cleanup commands.  Credentials are read from the project .env for the lifetime of one subprocess
call and are never printed, serialized, or written to evidence.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from shlex import quote
from typing import Any, Iterable, Mapping, Sequence

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
NAVIGATION_ASSET_ROOT = "tasks/assets/navigation/800x1280"
CASH_REFERENCE = NAVIGATION_ASSET_ROOT + "/cash_mall_startup.png"
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
BLUESTACKS_ADB = Path(r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe")
BLUESTACKS_SERIAL = "emulator-5554"
BLUESTACKS_NATIVE_WIDTH = 800
BLUESTACKS_NATIVE_HEIGHT = 1280
BLUESTACKS_ARTIFACT_ROOT = REPO_ROOT / ".local-captures" / "flow-delivery"
NOVA_NAVIGATION_CANARY_OUTPUT_DEFAULT = (
    BLUESTACKS_ARTIFACT_ROOT / "NOVA-PRAISE-HOME-ATLAS-MIGRATION"
)
NOVA_SUPERVISED_PULSE_FLOW_ID = "NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE"
NOVA_SUPERVISED_PULSE_SCENARIO_ID = "nova_praise_one_free_pulse"
NOVA_SUPERVISED_PULSE_RESET_ID = "game-day-2026-07-22"
NOVA_SUPERVISED_PULSE_OUTPUT_DEFAULT = (
    BLUESTACKS_ARTIFACT_ROOT / NOVA_SUPERVISED_PULSE_FLOW_ID
)
NOVA_SUPERVISED_ACTION_DATABASE = (
    REPO_ROOT / ".local-orchestrator" / "bluestacks-actions.sqlite3"
)
NOVA_SUPERVISED_INVOCATION_GUARD = (
    REPO_ROOT
    / ".local-orchestrator"
    / "nova-praise-one-free-pulse-game-day-2026-07-22.guard.json"
)
FLOW_DELIVERY_QUEUE = REPO_ROOT / "tasks" / "flow_delivery_queue.json"
FLOW_DELIVERY_LEASE = REPO_ROOT / ".local-orchestrator" / "flow-delivery-lease.json"
FLOW_DELIVERY_BLUESTACKS_REGISTRY = (
    REPO_ROOT / "tasks" / "flow_delivery_bluestacks_registry.json"
)
BLUESTACKS_FLOW_IDS = (
    "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION",
    "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION",
    "NOVA-PRAISE-HOME-ATLAS-MIGRATION",
    "NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE",
    "NOAHS-TAVERN-HOME-ATLAS-MIGRATION",
    "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION",
    "TROOP-TRAINING-VERIFIED-NAVIGATION-CONVERGENCE",
    "SUPPLY-DEPOT-LEGACY-ADAPTER-RETIREMENT",
    "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
    "DAILY-MILESTONE-CLAIM-BLUESTACKS-INTEGRATION",
    "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION",
    "NANOWEAPON-BLUESTACKS-INTEGRATION",
    "RECRUITMENT-BLUESTACKS-INTEGRATION",
    "WORLD-MAP-NAVIGATION-FOUNDATION",
    "GATHERING-BLUESTACKS-INTEGRATION",
    "ZOMBIE-LAIR-BLUESTACKS-INTEGRATION",
)
# Handler IDs are fixed code bindings, never arbitrary commands. They remain empty until a flow's
# reviewed implementation registers all three route-specific capabilities.
_BLUESTACKS_FLOW_RUNNERS: dict[str, Any] = {}
_BLUESTACKS_EVIDENCE_VALIDATORS: dict[str, Any] = {}
_BLUESTACKS_RECOVERY_HANDLERS: dict[str, Any] = {}


def _register_checked_in_bluestacks_handlers() -> None:
    # Prefer same-directory import so `python scripts/pnsctl.py` and
    # `python -m scripts.pnsctl` register into this module's handler maps.
    try:
        from scripts.flow_delivery_campaign_bluestacks import register as register_campaign
    except ImportError:
        from flow_delivery_campaign_bluestacks import register as register_campaign
    try:
        from scripts.flow_delivery_ultimate_challenge_bluestacks import (
            register as register_ultimate_challenge,
        )
    except ImportError:
        from flow_delivery_ultimate_challenge_bluestacks import (
            register as register_ultimate_challenge,
        )

    register_campaign(
        _BLUESTACKS_FLOW_RUNNERS,
        _BLUESTACKS_EVIDENCE_VALIDATORS,
        _BLUESTACKS_RECOVERY_HANDLERS,
    )
    register_ultimate_challenge(
        _BLUESTACKS_FLOW_RUNNERS,
        _BLUESTACKS_EVIDENCE_VALIDATORS,
        _BLUESTACKS_RECOVERY_HANDLERS,
    )


_register_checked_in_bluestacks_handlers()


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
    run_remote(
        cfg,
        f"mkdir -p {quote(cfg.remote_workspace)}/{M6_ASSET_ROOT}",
    )
    sources = ["scripts", "tasks", "safe_action_core", "runtime-profile", "tests"]
    for source in sources:
        run_pscp(cfg, [str(cfg.repo_root / source)], cfg.remote_workspace, recursive=True)
    run_pscp(
        cfg,
        [str(cfg.repo_root / M6_ASSET_ROOT)],
        cfg.remote_workspace + "/evidence/sessions/20260712-m6-dq-bootstrap/",
        recursive=True,
    )


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
    capture_started = time.time()
    capture(cfg, name)
    capture_completed = time.time()
    status = run_remote(cfg, _adb_shell(cfg, "shell dumpsys window | grep -E 'mCurrentFocus|mFocusedApp' | head -2"))
    return json.dumps(
        {
            "capture": name,
            "capture_started_epoch": capture_started,
            "capture_completed_epoch": capture_completed,
            "capture_completed_utc": datetime.fromtimestamp(
                capture_completed, timezone.utc
            ).isoformat(),
            "foreground": status.strip(),
        },
        sort_keys=True,
    )


NAVIGATION_STEPS = {
    "cash-home": ("cash", "home", "HOME_BASE", "CASH_MALL_BACK", "standard-game-back-arrow", (45, 5, 130, 60), "tap", None),
    "home-quest": ("home", "quest", "QUEST", "HOME_TO_QUEST", "home-quest-entry", (250, 1130, 410, 1280), "tap", None),
    "quest-daily": ("quest", "daily", "DAILY_QUEST", "QUEST_TO_DAILY", "quest-daily-tab", (300, 70, 500, 140), "tap", None),
    "daily-scroll-up": (
        "daily", "daily", "DAILY_QUEST", "SCROLL_DAILY_QUEST", "daily-scroll-viewport",
        (100, 520, 700, 1120), "swipe", (400, 1000, 400, 500, 350),
    ),
    "daily-scroll-up-fine": (
        "daily", "daily", "DAILY_QUEST", "SCROLL_DAILY_QUEST_FINE", "daily-scroll-viewport",
        (100, 520, 700, 1120), "swipe", (400, 800, 400, 700, 250),
    ),
    "daily-scroll-up-micro": (
        "daily", "daily", "DAILY_QUEST", "SCROLL_DAILY_QUEST_MICRO", "daily-scroll-viewport",
        (100, 520, 700, 1120), "swipe", (400, 760, 400, 710, 200),
    ),
    "daily-scroll-down": (
        "daily", "daily", "DAILY_QUEST", "SCROLL_DAILY_QUEST", "daily-scroll-viewport",
        (100, 160, 700, 760), "swipe", (400, 500, 400, 1000, 350),
    ),
    "daily-scroll-down-fine": (
        "daily", "daily", "DAILY_QUEST", "SCROLL_DAILY_QUEST_FINE", "daily-scroll-viewport",
        (100, 160, 700, 760), "swipe", (400, 700, 400, 800, 250),
    ),
    "daily-bioenhancer-go": (
        "daily_bioenhancer", "bioenhancer", "BIOENHANCER", "DAILY_BIOENHANCER_GO", "daily-bioenhancer-go",
        (554, 870, 731, 933), "tap", None,
    ),
    "bioenhancer-daily-back": (
        "bioenhancer", "home", "HOME_BASE", "BIOENHANCER_TO_HOME", "bioenhancer-daily-back",
        (31, 1, 138, 55), "tap", None,
    ),
    "daily-supply-depot-go": (
        "daily", "supply_depot", "SUPPLY_DEPOT", "DAILY_SUPPLY_DEPOT_GO", "daily-supply-depot-go",
        (554, 786, 731, 878), "tap", None,
    ),
    "supply-depot-daily-back": (
        "supply_depot", "home", "HOME_BASE", "SUPPLY_DEPOT_TO_HOME", "supply-depot-daily-back",
        (31, 1, 138, 55), "tap", None,
    ),
    "alliance-fort-dismiss": (
        "alliance_fort", "home", "ALLIANCE_FORT_DISMISSED",
        "DISMISS_ALLIANCE_FORT_WAVE", "alliance-fort-wave-dismiss-x",
        (620, 360, 735, 455), "tap", None,
    ),
}


def navigate(cfg: OperatorConfig, step: str) -> str:
    if step not in NAVIGATION_STEPS:
        raise OperatorError("navigate accepts only the checked-in route names: " + ", ".join(sorted(NAVIGATION_STEPS)))
    source_mode, expected_mode, expected_state, semantic, target, roi, input_kind, swipe = NAVIGATION_STEPS[step]
    stamp = str(int(time.time()))
    args = [
        "python3", "scripts/mvp_quest_to_claim.py", "--cash-reference", f"/workspace/{CASH_REFERENCE}",
        "--home-reference", "/workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/home-base-settled.png",
        "--quest-reference", "/workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/quest-main-settled.png",
        "--daily-reference", "/workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/daily-quest-settled.png",
        "--main-quest-reference", "/workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/quest-main-settled.png",
        "execute", "--database", f"/evidence/actions-nav-{step}-{stamp}.sqlite3", "--evidence", "/evidence",
        "--owner", "pnsctl-" + stamp, "--action-id", "nav-" + step + "-" + stamp,
        "--action-key", "nav-" + step + "-" + stamp, "--source-mode", source_mode,
        "--expected-mode", expected_mode, "--expected-state", expected_state, "--target", target,
        "--roi", *map(str, roi), "--semantic-action", semantic,
    ]
    if input_kind == "swipe":
        if swipe is None:
            raise OperatorError("swipe navigation step is missing its bounded gesture")
        args.extend(["--input-kind", "swipe", "--swipe", *map(str, swipe)])
    if source_mode == "home":
        args.extend(["--observation-max-age", "15", "--dispatch-max-age", "15"])
    command = _adb_shell(cfg, "")
    # Reuse the worker's interpreter and ADB environment without creating a second transport.
    command = (
        f"docker exec -e HOME=/tmp -e ADB_SERVER_PORT=5042 -e PYTHONPATH=/workspace -w /workspace "
        f"{quote(cfg.container)} " + " ".join(quote(item) for item in args)
    )
    return run_remote(cfg, command)


def run_task(cfg: OperatorConfig, task: str, game_day: str = "") -> str:
    stamp = str(int(time.time()))
    if task == "daily-claim":
        if not game_day:
            raise OperatorError("Daily Claim requires an explicit current game-day identity")
        command = (
            f"docker exec -e HOME=/tmp -e ADB_SERVER_PORT=5042 -e PYTHONPATH=/workspace -w /workspace {quote(cfg.container)} "
            f"python3 scripts/mvp_quest_to_claim.py "
            f"--cash-reference /workspace/{CASH_REFERENCE} "
            "--home-reference /workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/home-base-settled.png "
            "--quest-reference /workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/quest-main-settled.png "
            "--daily-reference /workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/daily-quest-settled.png "
            "--main-quest-reference /workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/quest-main-settled.png "
            f"execute --database /evidence/actions-daily-claim-{stamp}.sqlite3 --evidence /evidence "
            f"--owner pnsctl-{stamp} --action-id daily-claim-{stamp} --action-key daily-claim-{stamp} "
            f"--game-day {quote(game_day)} --source-mode daily_claim --expected-mode daily_claimed "
            "--expected-state DAILY_QUEST_CLAIMED --target daily-quest-claim "
            "--roi 500 300 780 550 --semantic-action CLAIM_DAILY_QUEST "
            "--consequence claim_zero_cost_reward --control-class CLAIM --quantity 1"
        )
    elif task == "bioenhancer-free-research":
        if not game_day:
            raise OperatorError("Bioenhancer research requires an explicit current game-day identity")
        command = (
            f"docker exec -e HOME=/tmp -e ADB_SERVER_PORT=5042 -e PYTHONPATH=/workspace -w /workspace {quote(cfg.container)} "
            f"python3 scripts/mvp_quest_to_claim.py "
            f"--cash-reference /workspace/{CASH_REFERENCE} "
            "--home-reference /workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/home-base-settled.png "
            "--quest-reference /workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/quest-main-settled.png "
            "--daily-reference /workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/daily-quest-settled.png "
            "--main-quest-reference /workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/quest-main-settled.png "
            f"execute --database /evidence/actions-bioenhancer-free-{stamp}.sqlite3 --evidence /evidence "
            f"--owner pnsctl-{stamp} --action-id bioenhancer-free-{stamp} --action-key bioenhancer-free-{stamp} "
            f"--game-day {quote(game_day)} --source-mode bioenhancer_free --expected-mode bioenhancer_free "
            "--expected-state BIOENHANCER_RESEARCH_SUCCESS --target bioenhancer-free-research "
            "--roi 94 1133 345 1216 --semantic-action RESEARCH_BIOENHANCER_FREE "
            "--consequence bioenhancer_research_free --control-class RESEARCH_FREE --quantity 1"
        )
    elif task == "alliance-help":
        command = (
            f"docker exec -e HOME=/tmp -e ADB_SERVER_PORT=5042 {quote(cfg.container)} python3 scripts/alliance_help_live.py "
            f"--adb /opt/adb --serial {quote(cfg.serial)} --database /evidence/actions-help-all-semantic-fix.sqlite3 "
            f"--evidence /evidence --result /evidence/alliance-help-semantic-fix-result.json --owner pnsctl-{stamp} "
            f"--action-id alliance-help-{stamp} --action-key alliance-help-{stamp}"
        )
    elif task in {
        "vip-popup", "praise", "praise-route-evidence", "praise-leaderboard-evidence",
        "personal-might-claim",
    }:
        popup_only = " --popup-only" if task == "vip-popup" else ""
        navigation_only = " --navigation-evidence-only" if task == "praise-route-evidence" else ""
        leaderboard_only = " --leaderboard-evidence-only" if task == "praise-leaderboard-evidence" else ""
        claim_only = " --claim-only" if task == "personal-might-claim" else ""
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
            + claim_only
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


def preserve_evidence(cfg: OperatorConfig, destination: Path, names: Sequence[str] = ()) -> str:
    if not names:
        raise OperatorError(
            "preserve-evidence requires at least one exact --name; cumulative remote evidence "
            "downloads are intentionally disabled"
        )
    destination = destination if destination.is_absolute() else (cfg.repo_root / destination)
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    for name in names:
        safe_name = _safe_name(name)
        encoded = run_remote(
            cfg,
            f"base64 -w0 {quote(cfg.remote_evidence + '/' + safe_name)}",
        ).strip()
        (destination / safe_name).write_bytes(base64.b64decode(encoded))
    return str(destination)


def evidence_status(cfg: OperatorConfig) -> str:
    return run_remote(
        cfg,
        f"find {quote(cfg.remote_evidence)} -maxdepth 1 -type f -printf '%f\\n' | sort",
    )


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
                "confirmed": True, "reason": args.reason,
                "evidence": args.evidence, "source_database": str(source),
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
            store.mark_confirmed(args.action_id, time.time(), reconciliation)
            status, reason = "confirmed", args.reason
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


def _load_flow_delivery_state(
    *,
    require_runtime_held: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        queue = json.loads(FLOW_DELIVERY_QUEUE.read_text(encoding="utf-8"))
        lease = json.loads(FLOW_DELIVERY_LEASE.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperatorError("a valid local flow-delivery queue and lease are required") from exc
    if queue.get("queue_kind") != "development_flow_delivery":
        raise OperatorError("invalid flow-delivery queue authority")
    if lease.get("workflow") != "pns-flow-delivery":
        raise OperatorError("invalid flow-delivery lease authority")
    if require_runtime_held and lease.get("runtime_ownership_state") != "held":
        raise OperatorError("the parent must hold BlueStacks runtime ownership")
    if not require_runtime_held and lease.get("runtime_ownership_state") not in {
        "none",
        "released",
        "held",
    }:
        raise OperatorError("BlueStacks runtime ownership is unknown")
    if lease.get("unresolved_action_state") != "clear":
        raise OperatorError("the global unresolved-action gate is not clear")
    active_flow = queue.get("active_flow_id")
    if not active_flow or lease.get("active_flow") != active_flow:
        raise OperatorError("queue and lease must identify one active development flow")
    if active_flow not in BLUESTACKS_FLOW_IDS:
        raise OperatorError("active flow is not in the BlueStacks allowlist")
    return queue, lease


def _load_bluestacks_flow_registry() -> dict[str, dict[str, str]]:
    try:
        registry = json.loads(
            FLOW_DELIVERY_BLUESTACKS_REGISTRY.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperatorError("invalid BlueStacks flow-delivery registry") from exc
    if (
        not isinstance(registry, dict)
        or registry.get("schema_version") != 1
        or registry.get("registry_kind") != "flow_delivery_bluestacks"
        or not isinstance(registry.get("flows"), dict)
    ):
        raise OperatorError("invalid BlueStacks flow-delivery registry")
    required = {
        "runner",
        "evidence_validator",
        "recovery_handler",
        "consequence_class",
    }
    for flow_id, contract in registry["flows"].items():
        if flow_id not in BLUESTACKS_FLOW_IDS or not isinstance(contract, dict):
            raise OperatorError("BlueStacks registry contains an unknown flow")
        if set(contract) != required or any(
            not isinstance(contract[field], str) or not contract[field].strip()
            for field in required
        ):
            raise OperatorError("BlueStacks flow registry contract is incomplete")
        if contract["consequence_class"] not in {"navigation_only", "consequential"}:
            raise OperatorError("BlueStacks flow registry consequence class is invalid")
    return registry["flows"]


def _focused_package(dumpsys_output: str) -> str:
    patterns = (
        r"(?m)^\s*mCurrentFocus=Window\{[^\r\n]*?\s(?:u\d+\s+)?"
        r"(?P<package>[A-Za-z0-9._]+)/[^\s}]+",
        r"(?m)^\s*mFocusedApp=ActivityRecord\{[^\r\n]*?\s(?:u\d+\s+)?"
        r"(?P<package>[A-Za-z0-9._]+)/[^\s}]+",
    )
    for pattern in patterns:
        match = re.search(pattern, dumpsys_output)
        if match:
            return match.group("package")
    raise OperatorError("focused Android application could not be parsed")


def _run_fixed_bluestacks_adb(*arguments: str, binary: bool = False) -> bytes | str:
    if not BLUESTACKS_ADB.is_file():
        raise OperatorError("approved BlueStacks HD-Adb executable is unavailable")
    result = subprocess.run(
        [str(BLUESTACKS_ADB), "-s", BLUESTACKS_SERIAL, *arguments],
        check=False,
        capture_output=True,
        text=not binary,
    )
    if result.returncode:
        stderr = result.stderr if isinstance(result.stderr, str) else result.stderr.decode(errors="replace")
        raise OperatorError("fixed BlueStacks ADB operation failed: " + stderr.strip())
    return result.stdout


def bluestacks_preflight() -> str:
    queue, lease = _load_flow_delivery_state()
    state = str(_run_fixed_bluestacks_adb("get-state")).strip()
    frame = _run_fixed_bluestacks_adb("exec-out", "screencap", "-p", binary=True)
    if not isinstance(frame, bytes) or frame[:8] != b"\x89PNG\r\n\x1a\n" or len(frame) < 24:
        raise OperatorError("BlueStacks preflight did not receive a valid PNG frame")
    width = int.from_bytes(frame[16:20], "big")
    height = int.from_bytes(frame[20:24], "big")
    focus = str(_run_fixed_bluestacks_adb("shell", "dumpsys", "window"))
    if state != "device":
        raise OperatorError("approved BlueStacks serial is not in device state")
    if (width, height) != (BLUESTACKS_NATIVE_WIDTH, BLUESTACKS_NATIVE_HEIGHT):
        raise OperatorError("BlueStacks native frame is not 800x1280")
    focused_package = _focused_package(focus)
    if focused_package != PACKAGE:
        raise OperatorError("Puzzles & Survival is not the foreground package")
    return json.dumps(
        {
            "status": "ready",
            "flow_id": queue["active_flow_id"],
            "lease_owner": lease["owner"],
            "serial": BLUESTACKS_SERIAL,
            "private_serial": True,
            "native_width": width,
            "native_height": height,
            "foreground_package": focused_package,
            "runtime_ownership_state": "held",
            "dispatch": False,
        },
        sort_keys=True,
    )


def bluestacks_run_flow(flow_id: str, *, live: bool) -> str:
    if flow_id not in BLUESTACKS_FLOW_IDS:
        raise OperatorError("flow ID is not in the checked-in BlueStacks allowlist")
    contract = _load_bluestacks_flow_registry().get(flow_id)
    if contract is None or contract["runner"] not in _BLUESTACKS_FLOW_RUNNERS:
        raise OperatorError("FLOW_DELIVERY_RUNNER_UNAVAILABLE")
    if not live:
        return json.dumps(
            {
                "status": "dry_run",
                "flow_id": flow_id,
                "runner": contract["runner"],
                "dispatch": False,
            },
            sort_keys=True,
        )
    from scripts.navigation_development_boundary import NavigationDevelopmentSession

    owner = f"pnsctl-bluestacks-run-flow:{flow_id}"
    invocation_id = f"{flow_id}:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    with NavigationDevelopmentSession(owner=owner, invocation_id=invocation_id):
        queue, lease = _load_flow_delivery_state()
        if queue["active_flow_id"] != flow_id:
            raise OperatorError("only the active development flow may run")
        flow = next(item for item in queue["flows"] if item["flow_id"] == flow_id)
        if flow.get("last_completed_stage") != "live_execution":
            raise OperatorError("controller has not admitted the flow to live_execution")
        return _BLUESTACKS_FLOW_RUNNERS[contract["runner"]](queue, lease)


def _session_relative_path(session: Path, value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise OperatorError(f"{field} must be a non-empty relative path")
    candidate = Path(value)
    if candidate.is_absolute():
        raise OperatorError(f"{field} must be a session-relative path")
    resolved = (session / candidate).resolve()
    try:
        resolved.relative_to(session.resolve())
    except ValueError as exc:
        raise OperatorError(f"{field} escapes the session directory") from exc
    if os.path.islink(resolved) or not resolved.is_file():
        raise OperatorError(f"{field} does not exist as a regular non-symlink file")
    return resolved


def _require_exact_nonsymlink_path(path: Path, expected: Path, label: str) -> Path:
    """Require an exact non-symlink path identity; reject alternates and symlink equivalents."""

    candidate = Path(path)
    expected_path = Path(expected)
    cand_abs = Path(os.path.abspath(os.path.normpath(str(candidate))))
    exp_abs = Path(os.path.abspath(os.path.normpath(str(expected_path))))
    if cand_abs != exp_abs:
        raise OperatorError(f"{label} must be exactly {expected_path}")
    for probe in (cand_abs, exp_abs, *cand_abs.parents, *exp_abs.parents):
        if probe.exists() and os.path.islink(probe):
            raise OperatorError(f"{label} must not be a symlink")
    return expected_path


def _read_nonempty_jsonl(path: Path, field: str) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise OperatorError(f"{field} is unreadable") from exc
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise OperatorError(f"{field} contains invalid JSONL") from exc
        if not isinstance(payload, dict):
            raise OperatorError(f"{field} JSONL rows must be objects")
        rows.append(payload)
    if not rows:
        raise OperatorError(f"{field} must be nonempty")
    return rows


def _session_evidence_file(session: Path, ref: Any, *, field: str = "evidence_refs") -> Path:
    if not isinstance(ref, str) or not ref.strip():
        raise OperatorError(f"{field} entries must be non-empty paths")
    candidate = Path(ref)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (session / candidate).resolve()
    try:
        resolved.relative_to(session.resolve())
    except ValueError as exc:
        raise OperatorError(f"{field} escapes the session directory") from exc
    if os.path.islink(resolved) or not resolved.is_file():
        raise OperatorError(f"{field} must resolve to a regular non-symlink file under the session")
    return resolved


def _persist_nova_session_result(
    session_directory: str | Path,
    updates: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge authoritative accounting into the session result.json on disk."""

    session = Path(session_directory)
    allowed_root = (REPO_ROOT / ".local-captures").resolve()
    try:
        resolved_session = session.resolve()
        resolved_session.relative_to(allowed_root)
    except (OSError, ValueError) as exc:
        raise OperatorError("session directory must resolve under .local-captures") from exc
    if os.path.islink(session) or os.path.islink(resolved_session):
        raise OperatorError("session directory must not be a symlink")
    if not resolved_session.is_dir():
        raise OperatorError("session directory is unavailable or unsafe")
    path = resolved_session / "result.json"
    if os.path.islink(path) or not path.is_file():
        raise OperatorError("result.json must be a regular non-symlink file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperatorError("session result.json is required before accounting persistence") from exc
    if not isinstance(payload, dict):
        raise OperatorError("session result.json must be an object")
    payload.update(dict(updates))
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def _supervised_pulse_completed_facts_ok(route_result: Mapping[str, Any]) -> bool:
    from tasks.nova_praise import (
        NOVA_COOLDOWN_MINIMUM_ACCEPTABLE_SECONDS,
        NOVA_POLICY_COOLDOWN_SECONDS,
    )

    navigation = route_result.get("navigation_input_count")
    praise = route_result.get("praise_transport_calls")
    before = route_result.get("attempts_before")
    after = route_result.get("attempts_after")
    cooldown = route_result.get("cooldown_seconds")
    evidence = route_result.get("evidence_refs")
    session_directory = route_result.get("session_directory")
    return bool(
        route_result.get("status") == "completed"
        and route_result.get("journal_status") == "confirmed"
        and route_result.get("terminal_home_verified") is True
        and type(before) is int
        and before > 0
        and type(after) is int
        and after == before - 1
        and type(cooldown) is int
        and NOVA_COOLDOWN_MINIMUM_ACCEPTABLE_SECONDS <= cooldown <= NOVA_POLICY_COOLDOWN_SECONDS
        and praise == 1
        and type(navigation) is int
        and navigation >= 1
        and isinstance(route_result.get("action_id"), str)
        and str(route_result.get("action_id") or "").strip()
        and isinstance(route_result.get("action_key"), str)
        and str(route_result.get("action_key") or "").strip()
        and isinstance(evidence, list)
        and bool(evidence)
        and isinstance(session_directory, str)
        and bool(str(session_directory).strip())
        and route_result.get("production_registration") == "NOT_REGISTERED"
        and route_result.get("scheduler_enabled") is False
    )


def _create_nova_supervised_invocation_guard(
    *,
    candidate_commit: str,
    reset_id: str,
) -> Path:
    guard_path = NOVA_SUPERVISED_INVOCATION_GUARD
    guard_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "flow_id": NOVA_SUPERVISED_PULSE_FLOW_ID,
        "scenario_id": NOVA_SUPERVISED_PULSE_SCENARIO_ID,
        "reset_id": reset_id,
        "candidate_commit": candidate_commit,
        "status": "started",
        "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "terminal_status": None,
        "session_directory": None,
        "result_status": None,
    }
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(guard_path), flags)
    except FileExistsError as exc:
        raise OperatorError(
            "supervised invocation guard already exists; repeat live input is blocked"
        ) from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    except Exception:
        # Never delete the guard; a partial create still blocks rerun.
        raise
    return guard_path


def _finalize_nova_supervised_invocation_guard(
    *,
    terminal_status: str,
    result_status: str | None,
    session_directory: str | None,
) -> None:
    path = NOVA_SUPERVISED_INVOCATION_GUARD
    if not path.is_file():
        raise OperatorError("supervised invocation guard is missing at finalization")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperatorError("supervised invocation guard is unreadable") from exc
    if not isinstance(payload, dict):
        raise OperatorError("supervised invocation guard must be an object")
    payload["status"] = terminal_status
    payload["terminal_status"] = terminal_status
    payload["result_status"] = result_status
    payload["session_directory"] = session_directory
    payload["finished_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _confine_nova_supervised_paths(args: argparse.Namespace) -> None:
    if Path(args.output_directory) == NOVA_NAVIGATION_CANARY_OUTPUT_DEFAULT:
        args.output_directory = NOVA_SUPERVISED_PULSE_OUTPUT_DEFAULT
    _require_exact_nonsymlink_path(
        Path(args.output_directory),
        NOVA_SUPERVISED_PULSE_OUTPUT_DEFAULT,
        "supervised output directory",
    )
    args.output_directory = NOVA_SUPERVISED_PULSE_OUTPUT_DEFAULT
    _require_exact_nonsymlink_path(
        Path(args.action_database),
        NOVA_SUPERVISED_ACTION_DATABASE,
        "supervised action database",
    )
    args.action_database = NOVA_SUPERVISED_ACTION_DATABASE


def _require_nova_supervised_reset(args: argparse.Namespace, identity) -> None:
    if getattr(args, "reset_id", None) != NOVA_SUPERVISED_PULSE_RESET_ID:
        raise OperatorError("supervised pulse requires reset_id=game-day-2026-07-22")
    if getattr(identity, "reset_id", None) != NOVA_SUPERVISED_PULSE_RESET_ID:
        raise OperatorError("supervised identity reset_id must be game-day-2026-07-22")


def _verify_nova_supervised_one_free_pulse_session(
    session_directory: Path,
) -> dict[str, Any]:
    """Narrow checked-in verifier for supervised one-free-pulse result.json sessions."""

    from tasks.nova_praise import (
        NOVA_COOLDOWN_MINIMUM_ACCEPTABLE_SECONDS,
        NOVA_POLICY_COOLDOWN_SECONDS,
    )
    from tasks.nova_praise_pulse import NOVA_TASK_ID

    session = session_directory.resolve()
    allowed_root = (REPO_ROOT / ".local-captures").resolve()
    try:
        session.relative_to(allowed_root)
    except ValueError as exc:
        raise OperatorError("session directory must remain under .local-captures") from exc
    if os.path.islink(session_directory) or os.path.islink(session) or not session.is_dir():
        raise OperatorError("session directory is unavailable or unsafe")
    result_path = session / "result.json"
    if os.path.islink(result_path) or not result_path.is_file():
        raise OperatorError("result.json must be a regular non-symlink file")
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperatorError("result.json is required") from exc
    if not isinstance(result, dict):
        raise OperatorError("result.json must be an object")
    if result.get("schema_version") != 1:
        raise OperatorError("unsupported result schema_version")
    if result.get("flow_id") != NOVA_SUPERVISED_PULSE_FLOW_ID:
        raise OperatorError("result flow_id is not the supervised Praise flow")
    if result.get("scenario_id") != NOVA_SUPERVISED_PULSE_SCENARIO_ID:
        raise OperatorError("result scenario_id is not nova_praise_one_free_pulse")
    if result.get("status") != "completed":
        raise OperatorError("flow result is not terminally completed")
    navigation = result.get("navigation_input_count")
    praise = result.get("praise_transport_calls")
    if type(navigation) is not int or navigation < 1:
        raise OperatorError("completed supervised pulse requires navigation_input_count >= 1")
    if praise != 1:
        raise OperatorError("completed supervised pulse requires exactly one Praise")
    before = result.get("attempts_before")
    after = result.get("attempts_after")
    if type(before) is not int or type(after) is not int or after != before - 1 or before <= 0:
        raise OperatorError("attempts must prove exact X->X-1")
    cooldown = result.get("cooldown_seconds")
    if (
        type(cooldown) is not int
        or cooldown < NOVA_COOLDOWN_MINIMUM_ACCEPTABLE_SECONDS
        or cooldown > NOVA_POLICY_COOLDOWN_SECONDS
    ):
        raise OperatorError("cooldown is missing or not policy-consistent")
    if result.get("journal_status") != "confirmed":
        raise OperatorError("journal_status must be confirmed")
    if result.get("terminal_home_verified") is not True:
        raise OperatorError("terminal Home was not verified")
    if result.get("production_registration") != "NOT_REGISTERED":
        raise OperatorError("production registration must remain NOT_REGISTERED")
    if result.get("scheduler_enabled") is not False:
        raise OperatorError("scheduler must remain disabled")
    candidate = result.get("candidate_commit")
    scenario_record = result.get("scenario_record")
    if not isinstance(candidate, str) or not candidate.strip():
        raise OperatorError("candidate_commit accounting is missing from result.json")
    if not isinstance(scenario_record, dict):
        raise OperatorError("scenario_record accounting is missing from result.json")
    if scenario_record.get("scenario_id") != NOVA_SUPERVISED_PULSE_SCENARIO_ID:
        raise OperatorError("scenario_record belongs to another scenario")
    if scenario_record.get("candidate_commit") != candidate:
        raise OperatorError("scenario_record candidate_commit mismatch")
    if scenario_record.get("outcome") != "completed":
        raise OperatorError("scenario_record must be COMPLETED")
    if scenario_record.get("input_class") != "mixed_navigation_and_one_consequential":
        raise OperatorError("scenario_record input_class mismatch")
    if scenario_record.get("navigation_input_count") != navigation:
        raise OperatorError("scenario_record navigation count mismatch")
    if scenario_record.get("praise_transport_calls") != praise:
        raise OperatorError("scenario_record praise count mismatch")
    if scenario_record.get("unresolved_action") is not False:
        raise OperatorError("scenario_record must not be unresolved")
    if scenario_record.get("terminal_ownership_state") != "released":
        raise OperatorError("scenario_record terminal ownership must be released")
    action_id = result.get("action_id")
    action_key = result.get("action_key")
    if not isinstance(action_id, str) or not action_id.strip():
        raise OperatorError("action_id is required")
    if not isinstance(action_key, str) or not action_key.strip():
        raise OperatorError("action_key is required")
    action_database = result.get("action_database")
    if not isinstance(action_database, str) or not action_database.strip():
        raise OperatorError("action_database path is required")
    db_path = _require_exact_nonsymlink_path(
        Path(action_database),
        NOVA_SUPERVISED_ACTION_DATABASE,
        "action_database",
    )
    if not db_path.is_file() or os.path.islink(db_path):
        raise OperatorError("action_database must exist as a regular non-symlink SQLite file")
    evidence_refs = result.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not evidence_refs:
        raise OperatorError("evidence_refs are required")
    verified_evidence = [
        str(_session_evidence_file(session, ref).relative_to(session))
        for ref in evidence_refs
    ]
    required_files = {
        "events_path": result.get("events_path") or "events.jsonl",
        "ledger_path": result.get("ledger_path") or "ledger.jsonl",
        "journal_path": result.get("journal_path") or "journal.jsonl",
    }
    verified_paths = {
        field: str(_session_relative_path(session, value, field).relative_to(session))
        for field, value in required_files.items()
    }
    events = _read_nonempty_jsonl(session / verified_paths["events_path"], "events.jsonl")
    ledger = _read_nonempty_jsonl(session / verified_paths["ledger_path"], "ledger.jsonl")
    journal_rows = _read_nonempty_jsonl(
        session / verified_paths["journal_path"],
        "journal.jsonl",
    )
    if not ledger:
        raise OperatorError("ledger.jsonl must be nonempty")
    consequential = [
        event
        for event in events
        if event.get("type") == "dispatch" and event.get("consequential") is True
    ]
    if len(consequential) != 1:
        raise OperatorError("events.jsonl must contain exactly one consequential dispatch")
    if consequential[0].get("action_key") != action_key:
        raise OperatorError("consequential dispatch action_key mismatch")
    journal = journal_rows[-1]
    if journal.get("action_id") != action_id or journal.get("action_key") != action_key:
        raise OperatorError("journal.jsonl action identity mismatch")
    if journal.get("journal_status") != "confirmed":
        raise OperatorError("journal.jsonl status must be confirmed")
    if journal.get("attempts_before") != before or journal.get("attempts_after") != after:
        raise OperatorError("journal.jsonl attempt counts mismatch")
    if journal.get("cooldown_seconds") != cooldown:
        raise OperatorError("journal.jsonl cooldown mismatch")
    if journal.get("terminal_home_verified") is not True:
        raise OperatorError("journal.jsonl terminal Home mismatch")
    try:
        connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise OperatorError("action_database could not be opened read-only") from exc
    try:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT action_id, action_key, task_id, consequential, final_status, input_attempt_at "
            "FROM actions WHERE action_id=?",
            (action_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise OperatorError("action_database is missing the confirmed action_id row")
    if row["action_key"] != action_key:
        raise OperatorError("action_database action_key mismatch")
    if row["task_id"] != NOVA_TASK_ID:
        raise OperatorError("action_database task_id must be nova_praise")
    if int(row["consequential"]) != 1:
        raise OperatorError("action_database row must be consequential")
    if row["final_status"] != "confirmed":
        raise OperatorError("action_database final_status must be confirmed")
    if row["input_attempt_at"] is None:
        raise OperatorError("action_database input_attempt_at must be retained")
    return {
        "result": result,
        "session_directory": str(session),
        "artifacts": verified_paths,
        "evidence_refs": verified_evidence,
        "navigation_input_count": navigation,
        "praise_transport_calls": praise,
        "attempts_before": before,
        "attempts_after": after,
        "cooldown_seconds": cooldown,
    }


def _verify_flow_structure(session_directory: Path) -> dict[str, Any]:
    session = session_directory.resolve()
    allowed_root = (REPO_ROOT / ".local-captures").resolve()
    try:
        session.relative_to(allowed_root)
    except ValueError as exc:
        raise OperatorError("session directory must remain under .local-captures") from exc
    if not session.is_dir() or session.is_symlink():
        raise OperatorError("session directory is unavailable or unsafe")
    result_path = session / "flow-delivery-result.json"
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperatorError("flow-delivery-result.json is required") from exc
    if result.get("schema_version") != 1 or result.get("flow_id") not in BLUESTACKS_FLOW_IDS:
        raise OperatorError("unsupported flow-delivery result identity")
    if result.get("status") != "completed":
        raise OperatorError("flow result is not terminally completed")
    if result.get("serial") != BLUESTACKS_SERIAL:
        raise OperatorError("flow result used an unapproved serial")
    if (result.get("native_width"), result.get("native_height")) != (
        BLUESTACKS_NATIVE_WIDTH,
        BLUESTACKS_NATIVE_HEIGHT,
    ):
        raise OperatorError("flow result is not native 800x1280")
    if not isinstance(result.get("runtime_owner"), str) or not result["runtime_owner"].strip():
        raise OperatorError("flow result does not identify the runtime owner")
    if result.get("terminal_runtime_state") not in {"recognized_home", "safe_blocked_terminal"}:
        raise OperatorError("terminal runtime state is missing or unsafe")
    actions = result.get("actions")
    if not isinstance(actions, list):
        raise OperatorError("flow result actions must be a list")
    required_paths = {
        "events_path": result.get("events_path"),
        "ledger_path": result.get("ledger_path"),
        "capability_audit_path": result.get("capability_audit_path"),
        "journal_path": result.get("journal_path"),
    }
    verified_paths = {
        field: str(_session_relative_path(session, value, field).relative_to(session))
        for field, value in required_paths.items()
    }
    frames = result.get("frames")
    if not isinstance(frames, list) or not frames:
        raise OperatorError("flow result requires frame evidence")
    verified_frames = [
        str(_session_relative_path(session, value, "frames").relative_to(session))
        for value in frames
    ]
    return {
        "result": result,
        "session_directory": str(session),
        "actions": len(actions),
        "frames": verified_frames,
        "artifacts": verified_paths,
        "terminal_runtime_state": result["terminal_runtime_state"],
    }


def bluestacks_verify_flow(session_directory: Path) -> str:
    queue, lease = _load_flow_delivery_state(require_runtime_held=False)
    if lease.get("active_stage") != "evidence_review":
        raise OperatorError("verify-flow requires the active evidence_review stage")
    flow_id = queue["active_flow_id"]
    if flow_id == NOVA_SUPERVISED_PULSE_FLOW_ID:
        structure = _verify_nova_supervised_one_free_pulse_session(session_directory)
        if structure["result"].get("flow_id") != flow_id:
            raise OperatorError("flow evidence belongs to another active flow")
        return json.dumps(
            {
                "status": "verified",
                "flow_id": flow_id,
                "scenario_id": NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                "session_directory": structure["session_directory"],
                "navigation_input_count": structure["navigation_input_count"],
                "praise_transport_calls": structure["praise_transport_calls"],
                "attempts_before": structure["attempts_before"],
                "attempts_after": structure["attempts_after"],
                "cooldown_seconds": structure["cooldown_seconds"],
                "artifacts": structure["artifacts"],
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
            },
            sort_keys=True,
        )
    contract = _load_bluestacks_flow_registry().get(flow_id)
    if (
        contract is None
        or contract["evidence_validator"] not in _BLUESTACKS_EVIDENCE_VALIDATORS
    ):
        raise OperatorError("FLOW_EVIDENCE_VALIDATOR_UNAVAILABLE")
    structure = _verify_flow_structure(session_directory)
    if structure["result"].get("flow_id") != flow_id:
        raise OperatorError("flow evidence belongs to another active flow")
    verdict = _BLUESTACKS_EVIDENCE_VALIDATORS[contract["evidence_validator"]](
        structure,
        queue,
        lease,
    )
    if not isinstance(verdict, dict) or verdict.get("status") != "verified":
        raise OperatorError("route-specific evidence validator did not return a verified verdict")
    return json.dumps(verdict, sort_keys=True)


def bluestacks_recover_home() -> str:
    queue, lease = _load_flow_delivery_state()
    if lease.get("active_stage") not in {"live_preflight", "live_execution", "evidence_review"}:
        raise OperatorError("recover-home is available only during an admitted live delivery stage")
    contract = _load_bluestacks_flow_registry().get(queue["active_flow_id"])
    if contract is None or contract["recovery_handler"] not in _BLUESTACKS_RECOVERY_HANDLERS:
        raise OperatorError("FLOW_RECOVERY_HANDLER_UNAVAILABLE")
    return _BLUESTACKS_RECOVERY_HANDLERS[contract["recovery_handler"]](queue, lease)


def nova_praise_pulse_replay(args: argparse.Namespace) -> str:
    """Run the retained production-path Nova action/cooldown replay with zero transport."""

    from safe_action_core import SafetyStore
    from scripts.nova_praise_centralized import NovaPraiseActionBoundary
    from tasks.gameplay_flow_replay import ReplayNativeRuntime, load_retained_native_frame
    from tasks.home_atlas import load_home_atlas
    from tasks.nova_praise_pulse import NOVA_TASK_ID, NovaPulseController
    from tasks.flow_scenario_attempts import replay_validated_record
    from tasks.scheduler_task_result import SchedulerIdentity

    manifest_path = REPO_ROOT / "tests" / "fixtures" / "nova_praise_replay" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = {item["fixture_id"]: item for item in manifest["cases"]}
    before_case = cases["praise_attempts_available"]
    after_case = cases["praise_on_cooldown"]
    before = load_retained_native_frame(
        REPO_ROOT / before_case["path"],
        captured_monotonic=100.0,
        expected_sha256=before_case["sha256"],
    )
    after = load_retained_native_frame(
        REPO_ROOT / after_case["path"],
        captured_monotonic=101.0,
        expected_sha256=after_case["sha256"],
    )
    identity = SchedulerIdentity(
        args.account_id or "offline-replay-account",
        args.server_id or "offline-replay-server",
        args.reset_id or "offline-replay-reset",
        NOVA_TASK_ID,
    )
    atlas = load_home_atlas(
        REPO_ROOT
        / "tasks"
        / "assets"
        / "home_atlas"
        / "bluestacks"
        / "800x1280"
        / "atlas.json"
    )
    with tempfile.TemporaryDirectory(prefix="pns-nova-replay-") as directory:
        root = Path(directory)
        runtime = ReplayNativeRuntime(root / "runtime")
        store = SafetyStore(root / "replay.sqlite3")
        try:
            store.acquire_lease("replay-owner", 100.0, 600.0)
            pulse = NovaPulseController(identity, atlas, now=100.0, replay_mode=True)
            boundary = NovaPraiseActionBoundary(
                runtime,
                store,
                pulse,
                runtime_scope=args.runtime_scope or "offline-replay",
                owner_id="replay-owner",
                invocation_id=args.invocation_id or "offline-replay",
                execute=False,
                monotonic_clock=lambda: 101.25,
                wall_clock=lambda: 100.5,
                post_delays=(0.0,),
            )
            action = boundary.replay_praise(before, after)
            cooldown = boundary.replay_no_dispatch(
                action.after_recognition.observation,
                evidence_ref=str(after.path),
            )
            actions = store.list_actions_for_task(NOVA_TASK_ID)
            scheduler = store.get_scheduler_invocation_state(
                identity.account_id,
                identity.server_id,
                identity.reset_id,
                identity.task_id,
            )
        finally:
            store.close()
    if actions or scheduler is not None:
        raise OperatorError("Nova replay mutated operational action or scheduler state")
    candidate_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    scenario_record = replay_validated_record(
        candidate_commit=candidate_commit,
        evidence_refs=(str(before.path), str(after.path)),
    )
    return json.dumps(
        {
            "status": "replay_confirmed",
            "command": "nova-praise-pulse",
            "scenario": "retained_nova_six_to_five",
            "transport_calls": 0,
            "intended_inputs": action.to_mapping()["intended_inputs"],
            "action_result": action.to_mapping(),
            "cooldown_result": cooldown.to_mapping(),
            "operational_state_mutated": False,
            "scenario_record": scenario_record.to_mapping(),
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        },
        sort_keys=True,
    )


def _nova_supervised_identity(args: argparse.Namespace):
    from tasks.runtime_identity import (
        RuntimeIdentityAssurance,
        RuntimeIdentityConfiguration,
        RuntimeIdentityObservation,
        verify_runtime_identity,
    )

    values = {
        "runtime_scope": args.runtime_scope,
        "account_id": args.account_id,
        "server_id": args.server_id,
        "reset_id": args.reset_id,
    }
    missing = [
        name
        for name, value in values.items()
        if not isinstance(value, str) or not value.strip() or value != value.strip()
    ]
    if args.identity_evidence is None:
        missing.append("identity_evidence")
    if missing:
        return None, sorted(set(missing))
    for name, value in values.items():
        if not NAME_RE.fullmatch(value):
            raise OperatorError(f"Nova {name} contains unsupported characters")
    try:
        evidence = json.loads(args.identity_evidence.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperatorError("Nova supervised identity evidence is unreadable") from exc
    if not isinstance(evidence, dict):
        raise OperatorError("Nova supervised identity evidence must be an object")
    configuration = RuntimeIdentityConfiguration(
        args.runtime_scope,
        args.account_id,
        args.server_id,
        args.reset_id,
    )
    observation = RuntimeIdentityObservation(
        str(evidence.get("account_id") or ""),
        str(evidence.get("server_id") or ""),
        evidence.get("reset_id"),
        tuple(evidence.get("evidence_refs") or ()),
        operator_bound=evidence.get("assurance") == "supervised_navigation_binding",
        machine_observed=False,
    )
    verified = verify_runtime_identity(
        configuration,
        observation,
        required_assurance=RuntimeIdentityAssurance.SUPERVISED_NAVIGATION_BINDING,
    )
    if verified.identity is None:
        raise OperatorError("Nova supervised identity rejected: " + verified.reason)
    return verified.identity, []


def nova_praise_pulse_live(args: argparse.Namespace) -> str:
    """Admit checked-in no-Praise canary or supervised one-free-pulse scenarios."""

    if not args.yes:
        raise OperatorError("live Nova navigation requires --yes")
    if not args.supervised_live_opt_in:
        raise OperatorError("live Nova navigation requires --supervised-live-opt-in")
    if args.scenario not in {
        "nova_navigation_round_trip_no_praise",
        "nova_praise_one_free_pulse",
    }:
        raise OperatorError("unsupported Nova live scenario")
    from tasks.flow_scenario_attempts import (
        NOVA_CANARY_SCENARIO_ID,
        NOVA_SUPERVISED_PULSE_SCENARIO_ID,
        ScenarioAttemptRecord,
        ScenarioFailureClass,
        ScenarioOutcome,
        ScenarioPhase,
        SupervisedNovaPulseScenarioAttemptRecord,
    )

    candidate_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    identity, missing = _nova_supervised_identity(args)
    if missing:
        if args.scenario == NOVA_SUPERVISED_PULSE_SCENARIO_ID:
            record = SupervisedNovaPulseScenarioAttemptRecord(
                NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                ScenarioPhase.PRE_INPUT,
                ScenarioOutcome.BLOCKED,
                candidate_commit,
                0,
                0,
                "none",
                False,
                "identity_unverified",
                failure_class=ScenarioFailureClass.SUPERVISED_IDENTITY,
            )
        else:
            record = ScenarioAttemptRecord(
                NOVA_CANARY_SCENARIO_ID,
                ScenarioPhase.PRE_INPUT,
                ScenarioOutcome.BLOCKED,
                candidate_commit,
                0,
                "none",
                False,
                "identity_unverified",
                failure_class=ScenarioFailureClass.SUPERVISED_IDENTITY,
            )
        return json.dumps(
            {
                "status": "manual_required",
                "reason": "identity_unverified",
                "missing_configuration_fields": missing,
                "runtime_connected": False,
                "transport_calls": 0,
                "scenario_record": record.to_mapping(),
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
            },
            sort_keys=True,
        )
    if args.scenario == NOVA_SUPERVISED_PULSE_SCENARIO_ID:
        _require_nova_supervised_reset(args, identity)
        _confine_nova_supervised_paths(args)
        if args.preflight_only:
            return json.dumps(
                {
                    "status": "preflight_passed",
                    "scenario_id": NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                    "flow_id": NOVA_SUPERVISED_PULSE_FLOW_ID,
                    "reset_id": NOVA_SUPERVISED_PULSE_RESET_ID,
                    "candidate_commit": candidate_commit,
                    "runtime_connected": False,
                    "transport_calls": 0,
                    "production_registration": "NOT_REGISTERED",
                    "scheduler_enabled": False,
                },
                sort_keys=True,
            )
        from scripts.navigation_development_boundary import NavigationDevelopmentSession

        _create_nova_supervised_invocation_guard(
            candidate_commit=candidate_commit,
            reset_id=NOVA_SUPERVISED_PULSE_RESET_ID,
        )
        session = ""
        result_status: str | None = None
        guard_terminal = "failed"
        runner_returned = False
        praise_calls = 0
        pending_completed_guard = False
        owner = f"pnsctl-nova-supervised:{candidate_commit[:12]}"
        invocation_id = f"nova-supervised-{candidate_commit[:12]}-{int(time.time())}"
        try:
            with NavigationDevelopmentSession(owner=owner, invocation_id=invocation_id):
                try:
                    from scripts import nova_praise_bluestacks as route_module
                except ImportError as exc:
                    raise OperatorError("Nova praise route module is unavailable") from exc
                runner = getattr(route_module, "run_nova_praise_one_free_pulse", None)
                if not callable(runner):
                    record = SupervisedNovaPulseScenarioAttemptRecord(
                        NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                        ScenarioPhase.PRE_INPUT,
                        ScenarioOutcome.BLOCKED,
                        candidate_commit,
                        0,
                        0,
                        "none",
                        False,
                        "NOVA_PRAISE_ONE_FREE_PULSE_ROUTE_NOT_INTEGRATED",
                        failure_class=ScenarioFailureClass.EXECUTABLE_REGISTRATION,
                    )
                    route_result = {
                        "status": "blocked",
                        "reason": "NOVA_PRAISE_ONE_FREE_PULSE_ROUTE_NOT_INTEGRATED",
                        "runtime_connected": False,
                        "transport_calls": 0,
                        "scenario_record": record.to_mapping(),
                        "production_registration": "NOT_REGISTERED",
                        "scheduler_enabled": False,
                        "candidate_commit": candidate_commit,
                    }
                    result_status = "blocked"
                    guard_terminal = "failed"
                    return json.dumps(route_result, sort_keys=True)

                route_result = json.loads(runner(args, identity))
                runner_returned = True
                navigation_count = int(route_result.get("navigation_input_count", 0))
                praise_calls = int(route_result.get("praise_transport_calls", 0))
                status = str(route_result.get("status") or "blocked")
                session = str(route_result.get("session_directory") or "")
                result_status = status
                completed_facts = _supervised_pulse_completed_facts_ok(route_result)
                if status == "completed" and completed_facts:
                    record = SupervisedNovaPulseScenarioAttemptRecord(
                        NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                        ScenarioPhase.EXECUTION,
                        ScenarioOutcome.COMPLETED,
                        candidate_commit,
                        navigation_count,
                        praise_calls,
                        "mixed_navigation_and_one_consequential",
                        True,
                        "confirmed_praise_and_verified_safe_return_home",
                        evidence_refs=(session,),
                        terminal_ownership_state="released",
                    )
                    # Completed guard only after durable session persistence succeeds.
                    pending_completed_guard = True
                    guard_terminal = "failed"
                elif status == "unresolved" or praise_calls >= 1:
                    phase = (
                        ScenarioPhase.EXECUTION
                        if navigation_count >= 1 or praise_calls >= 1
                        else ScenarioPhase.PRE_INPUT
                    )
                    input_class = (
                        "mixed_navigation_and_one_consequential"
                        if praise_calls == 1
                        else "navigation_only"
                        if navigation_count >= 1
                        else "none"
                    )
                    reason = str(
                        route_result.get("reason")
                        or (
                            "supervised_pulse_missing_terminal_facts"
                            if status == "completed" and not completed_facts
                            else "praise_unresolved"
                        )
                    )
                    record = SupervisedNovaPulseScenarioAttemptRecord(
                        NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                        phase,
                        ScenarioOutcome.UNRESOLVED,
                        candidate_commit,
                        navigation_count,
                        praise_calls,
                        input_class,
                        phase is ScenarioPhase.EXECUTION,
                        reason,
                        failure_class=ScenarioFailureClass.POSTCONDITION,
                        evidence_refs=(session,),
                        terminal_ownership_state="released",
                        unresolved_action=True,
                    )
                    if status != "unresolved":
                        route_result["status"] = "unresolved"
                        route_result["reason"] = reason
                        result_status = "unresolved"
                    guard_terminal = "unresolved"
                else:
                    reason = str(route_result.get("reason") or "supervised_pulse_blocked")
                    if status == "completed" and not completed_facts:
                        reason = "supervised_pulse_missing_terminal_facts"
                        route_result["status"] = "blocked"
                        route_result["reason"] = reason
                        result_status = "blocked"
                    if navigation_count == 0 and praise_calls == 0:
                        phase = ScenarioPhase.PRE_INPUT
                        input_class = "none"
                        consumes = False
                        failure_class = ScenarioFailureClass.INITIAL_RECOGNITION
                    else:
                        phase = ScenarioPhase.EXECUTION
                        input_class = "navigation_only"
                        consumes = True
                        failure_class = (
                            ScenarioFailureClass.SCREEN_RECOGNITION
                            if "radial" in reason or "nova" in reason
                            else ScenarioFailureClass.SHARED_NAVIGATION
                            if "home" in reason or "zoom" in reason or "pan" in reason
                            else ScenarioFailureClass.TASK_NAVIGATION
                        )
                    record = SupervisedNovaPulseScenarioAttemptRecord(
                        NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                        phase,
                        ScenarioOutcome.BLOCKED,
                        candidate_commit,
                        navigation_count,
                        praise_calls,
                        input_class,
                        consumes,
                        reason,
                        failure_class=failure_class,
                        evidence_refs=(session,),
                        terminal_ownership_state="released",
                    )
                    guard_terminal = "failed"
                route_result["scenario_record"] = record.to_mapping()
                route_result["candidate_commit"] = candidate_commit
                route_result["production_registration"] = "NOT_REGISTERED"
                route_result["scheduler_enabled"] = False
                if session:
                    persisted = _persist_nova_session_result(
                        session,
                        {
                            "scenario_record": route_result["scenario_record"],
                            "candidate_commit": candidate_commit,
                            "production_registration": "NOT_REGISTERED",
                            "scheduler_enabled": False,
                            "status": route_result.get("status"),
                            "reason": route_result.get("reason"),
                        },
                    )
                    route_result["action_database"] = persisted.get(
                        "action_database",
                        route_result.get("action_database"),
                    )
                    route_result["action_id"] = persisted.get(
                        "action_id",
                        route_result.get("action_id"),
                    )
                    route_result["action_key"] = persisted.get(
                        "action_key",
                        route_result.get("action_key"),
                    )
                    if pending_completed_guard:
                        guard_terminal = "completed"
                elif pending_completed_guard:
                    # Never finalize completed without a durable session result.
                    reason = "supervised_pulse_missing_session_directory"
                    demoted = SupervisedNovaPulseScenarioAttemptRecord(
                        NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                        ScenarioPhase.EXECUTION,
                        ScenarioOutcome.UNRESOLVED,
                        candidate_commit,
                        navigation_count,
                        praise_calls,
                        "mixed_navigation_and_one_consequential",
                        True,
                        reason,
                        failure_class=ScenarioFailureClass.MISSING_EVIDENCE,
                        evidence_refs=(),
                        terminal_ownership_state="released",
                        unresolved_action=True,
                    )
                    route_result["scenario_record"] = demoted.to_mapping()
                    route_result["status"] = "unresolved"
                    route_result["reason"] = reason
                    result_status = "unresolved"
                    guard_terminal = "unresolved"
                return json.dumps(route_result, sort_keys=True)
        except BaseException:
            # Never finalize as completed when the CLI path fails after the runner.
            if runner_returned:
                facts_uncertain = pending_completed_guard or result_status == "completed"
                if praise_calls >= 1 or facts_uncertain:
                    guard_terminal = "unresolved"
                else:
                    guard_terminal = "failed"
            else:
                # Runner crash may have issued transport; block rerun as unresolved.
                guard_terminal = "unresolved"
                if result_status is None:
                    result_status = "unresolved"
            if guard_terminal == "completed":
                guard_terminal = "unresolved"
            raise
        finally:
            _finalize_nova_supervised_invocation_guard(
                terminal_status=guard_terminal,
                result_status=result_status,
                session_directory=session or None,
            )

    from scripts.navigation_development_boundary import NavigationDevelopmentSession

    if args.preflight_only:
        return json.dumps(
            {
                "status": "preflight_passed",
                "scenario_id": NOVA_CANARY_SCENARIO_ID,
                "candidate_commit": candidate_commit,
                "runtime_connected": False,
                "transport_calls": 0,
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
            },
            sort_keys=True,
        )

    try:
        from scripts import nova_praise_bluestacks as route_module
    except ImportError as exc:
        raise OperatorError("Nova navigation route module is unavailable") from exc
    runner = getattr(route_module, "run_nova_navigation_canary", None)
    if not callable(runner):
        record = ScenarioAttemptRecord(
            NOVA_CANARY_SCENARIO_ID,
            ScenarioPhase.PRE_INPUT,
            ScenarioOutcome.BLOCKED,
            candidate_commit,
            0,
            "none",
            False,
            "NOVA_NAVIGATION_ROUTE_NOT_INTEGRATED",
            failure_class=ScenarioFailureClass.EXECUTABLE_REGISTRATION,
        )
        return json.dumps(
            {
                "status": "blocked",
                "reason": "NOVA_NAVIGATION_ROUTE_NOT_INTEGRATED",
                "runtime_connected": False,
                "transport_calls": 0,
                "scenario_record": record.to_mapping(),
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
            },
            sort_keys=True,
        )
    canary_owner = f"pnsctl-nova-canary:{candidate_commit[:12]}"
    canary_invocation = f"nova-canary-{candidate_commit[:12]}-{int(time.time())}"
    with NavigationDevelopmentSession(owner=canary_owner, invocation_id=canary_invocation):
        route_result = json.loads(runner(args, identity))
    input_count = int(route_result.get("navigation_input_count", 0))
    status = str(route_result.get("status") or "blocked")
    if status == "completed":
        record = ScenarioAttemptRecord(
            NOVA_CANARY_SCENARIO_ID,
            ScenarioPhase.EXECUTION,
            ScenarioOutcome.COMPLETED,
            candidate_commit,
            input_count,
            "navigation_only",
            True,
            "verified_safe_return_home",
            evidence_refs=(str(route_result.get("session_directory") or ""),),
            terminal_ownership_state="released",
        )
    else:
        reason = str(route_result.get("reason") or "navigation_route_blocked")
        if input_count == 0:
            phase = ScenarioPhase.PRE_INPUT
            input_class = "none"
            consumes = False
            failure_class = ScenarioFailureClass.INITIAL_RECOGNITION
        else:
            phase = ScenarioPhase.EXECUTION
            input_class = "navigation_only"
            consumes = True
            failure_class = (
                ScenarioFailureClass.SCREEN_RECOGNITION
                if "radial" in reason or "nova" in reason
                else ScenarioFailureClass.SHARED_NAVIGATION
                if "home" in reason or "zoom" in reason or "pan" in reason
                else ScenarioFailureClass.TASK_NAVIGATION
            )
        record = ScenarioAttemptRecord(
            NOVA_CANARY_SCENARIO_ID,
            phase,
            ScenarioOutcome.BLOCKED,
            candidate_commit,
            input_count,
            input_class,
            consumes,
            reason,
            failure_class=failure_class,
            evidence_refs=(str(route_result.get("session_directory") or ""),),
            terminal_ownership_state="released",
        )
    route_result["scenario_record"] = record.to_mapping()
    return json.dumps(route_result, sort_keys=True)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--run-id", default="help-all-20260713")
    sub = root.add_subparsers(dest="command", required=True)
    for name in ("preflight", "worker-start", "worker-status", "worker-stop", "adb-start", "launch", "capture", "observe", "navigate", "run-task", "test-focused", "test-full", "validate", "preserve-evidence", "evidence-status", "cleanup"):
        sub.add_parser(name)
    sub.choices["capture"].add_argument("--name", default="current")
    sub.choices["observe"].add_argument("--name", default="observe")
    sub.choices["navigate"].add_argument("--step", required=True, choices=tuple(NAVIGATION_STEPS))
    sub.choices["run-task"].add_argument(
        "--task",
        required=True,
        choices=(
            "alliance-help", "vip-popup", "praise-route-evidence",
            "praise-leaderboard-evidence", "praise", "personal-might-claim",
            "bioenhancer-free-research", "daily-claim",
        ),
    )
    sub.choices["run-task"].add_argument("--game-day", default="")
    sub.choices["test-focused"].add_argument("--pattern", default="test_task_module.py")
    sub.choices["preserve-evidence"].add_argument("--destination", type=Path, required=True)
    sub.choices["preserve-evidence"].add_argument("--name", action="append", default=[])
    rec = sub.add_parser("reconcile")
    rec.add_argument("--source", type=Path, required=True)
    rec.add_argument("--output", type=Path, required=True)
    rec.add_argument("--action-id", required=True)
    rec.add_argument("--evidence", nargs="+", required=True)
    rec.add_argument("--outcome", choices=("proven_no_effect", "positive_postcondition"), default="proven_no_effect")
    rec.add_argument("--reason", default="positive_postcondition")
    nova_pulse = sub.add_parser("nova-praise-pulse")
    nova_pulse.add_argument("--live", action="store_true")
    nova_pulse.add_argument("--preflight-only", action="store_true")
    nova_pulse.add_argument(
        "--scenario",
        choices=(
            "nova_navigation_round_trip_no_praise",
            "nova_praise_one_free_pulse",
        ),
        default="nova_navigation_round_trip_no_praise",
    )
    nova_pulse.add_argument("--yes", action="store_true")
    nova_pulse.add_argument("--supervised-live-opt-in", action="store_true")
    nova_pulse.add_argument("--runtime-scope")
    nova_pulse.add_argument("--account-id")
    nova_pulse.add_argument("--server-id")
    nova_pulse.add_argument("--reset-id")
    nova_pulse.add_argument("--identity-evidence", type=Path)
    nova_pulse.add_argument("--owner")
    nova_pulse.add_argument("--invocation-id")
    nova_pulse.add_argument("--adb", type=Path, default=BLUESTACKS_ADB)
    nova_pulse.add_argument("--serial", default=BLUESTACKS_SERIAL)
    nova_pulse.add_argument("--settle-seconds", type=float, default=1.0)
    nova_pulse.add_argument(
        "--action-database",
        type=Path,
        default=NOVA_SUPERVISED_ACTION_DATABASE,
        help="durable SafetyStore path for supervised Nova Praise journaling",
    )
    nova_pulse.add_argument("--lease-ttl", type=float, default=3600.0)
    nova_pulse.add_argument(
        "--output-directory",
        type=Path,
        default=NOVA_NAVIGATION_CANARY_OUTPUT_DEFAULT,
    )
    bluestacks = sub.add_parser("bluestacks")
    bluestacks_sub = bluestacks.add_subparsers(dest="bluestacks_command", required=True)
    bluestacks_sub.add_parser("preflight")
    run_flow = bluestacks_sub.add_parser("run-flow")
    run_flow.add_argument("flow_id", choices=BLUESTACKS_FLOW_IDS)
    run_flow.add_argument("--live", action="store_true")
    verify_flow = bluestacks_sub.add_parser("verify-flow")
    verify_flow.add_argument("session_directory", type=Path)
    bluestacks_sub.add_parser("recover-home")
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "nova-praise-pulse":
        try:
            output = (
                nova_praise_pulse_live(args)
                if args.live
                else nova_praise_pulse_replay(args)
            )
            print(output)
            return 0
        except (OperatorError, OSError, RuntimeError, ValueError) as exc:
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "command": "nova-praise-pulse",
                        "error": str(exc),
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 2
    if args.command == "reconcile":
        print(reconcile(args))
        return 0
    if args.command == "bluestacks":
        try:
            if args.bluestacks_command == "preflight":
                output = bluestacks_preflight()
            elif args.bluestacks_command == "run-flow":
                output = bluestacks_run_flow(args.flow_id, live=args.live)
            elif args.bluestacks_command == "verify-flow":
                output = bluestacks_verify_flow(args.session_directory)
            elif args.bluestacks_command == "recover-home":
                output = bluestacks_recover_home()
            else:
                raise OperatorError("unknown BlueStacks command")
            print(output)
            return 0
        except (OperatorError, OSError, subprocess.SubprocessError) as exc:
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "command": f"bluestacks {args.bluestacks_command}",
                        "error": str(exc),
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 2
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
        "run-task": lambda: run_task(cfg, args.task, args.game_day),
        "test-focused": lambda: test_command(cfg, True, args.pattern),
        "test-full": lambda: test_command(cfg, False),
        "validate": lambda: validate(cfg),
        "preserve-evidence": lambda: preserve_evidence(cfg, args.destination, args.name),
        "evidence-status": lambda: evidence_status(cfg),
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
