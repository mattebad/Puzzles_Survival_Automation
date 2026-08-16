#!/usr/bin/env python3
"""Reproducible operator interface for local BlueStacks development and future Bliss porting.

Only this checked-in interface owns the routine worker, private ADB, validation, evidence, and
cleanup commands.  Credentials are read from the project .env for the lifetime of one subprocess
call and are never printed, serialized, or written to evidence.
"""

from __future__ import annotations

import argparse
import base64
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import inspect
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
from scripts.bluestacks_adb_readiness import (
    ADBReadinessError,
    ensure_adb_ready,
)

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
DEVELOPMENT_SESSION_ROOT = REPO_ROOT / ".local-captures" / "development-sessions"
DEVELOPMENT_CHECKPOINT_PATHS = (
    REPO_ROOT / "BACKLOG.md",
    REPO_ROOT / "tasks" / "flow_delivery_queue.json",
    REPO_ROOT / "CURRENT_HANDOFF.md",
)
NOVA_NAVIGATION_CANARY_OUTPUT_DEFAULT = (
    BLUESTACKS_ARTIFACT_ROOT / "NOVA-PRAISE-HOME-ATLAS-MIGRATION"
)
NOAHS_TAVERN_NAV_OUTPUT_DEFAULT = (
    BLUESTACKS_ARTIFACT_ROOT / "NOAHS-TAVERN-HOME-ATLAS-MIGRATION"
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
NOVA_SUPERVISED_GUARD_ARCHIVE_DIR = (
    REPO_ROOT / ".local-orchestrator" / "nova-supervised-guard-archive"
)
NOVA_SUPERVISED_GUARD_RECEIPT_DIR = (
    REPO_ROOT / ".local-orchestrator" / "nova-supervised-guard-receipts"
)
FLOW_DELIVERY_QUEUE = REPO_ROOT / "tasks" / "flow_delivery_queue.json"
FLOW_DELIVERY_LEASE = REPO_ROOT / ".local-orchestrator" / "flow-delivery-lease.json"
FLOW_DELIVERY_BLUESTACKS_REGISTRY = (
    REPO_ROOT / "tasks" / "flow_delivery_bluestacks_registry.json"
)
BLUESTACKS_FLOW_IDS = (
    "AUTONOMY-SERVICE-CAMPAIGN-NAVIGATION-PROVING-SLICE",
    "CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY",
    "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION",
    "CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION",
    "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION",
    "NOVA-PRAISE-HOME-ATLAS-MIGRATION",
    "NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE",
    "NOAHS-TAVERN-HOME-ATLAS-MIGRATION",
    "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION",
    "TROOP-TRAINING-VERIFIED-NAVIGATION-CONVERGENCE",
    "TROOP-TRAINING-END-TO-END-CONSOLIDATION",
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
        from scripts.flow_delivery_campaign_bluestacks import (
            register as register_campaign,
        )
    except ImportError:
        from flow_delivery_campaign_bluestacks import register as register_campaign
    try:
        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            register as register_campaign_atlas,
        )
    except ImportError:
        from flow_delivery_campaign_atlas_bluestacks import (
            register as register_campaign_atlas,
        )
    try:
        from scripts.flow_delivery_ultimate_challenge_bluestacks import (
            register as register_ultimate_challenge,
        )
    except ImportError:
        from flow_delivery_ultimate_challenge_bluestacks import (
            register as register_ultimate_challenge,
        )
    try:
        from scripts.flow_delivery_ruins_challenge_bluestacks import (
            register as register_ruins,
        )
    except ImportError:
        from flow_delivery_ruins_challenge_bluestacks import register as register_ruins
    try:
        from scripts.flow_delivery_troop_training_bluestacks import (
            register as register_troop_training,
        )
    except ImportError:
        from flow_delivery_troop_training_bluestacks import (
            register as register_troop_training,
        )
    try:
        from scripts.flow_delivery_enhancement_bluestacks import (
            register as register_enhancement,
        )
    except ImportError:
        from flow_delivery_enhancement_bluestacks import (
            register as register_enhancement,
        )
    try:
        from scripts.flow_delivery_world_map_bluestacks import (
            register as register_world_map,
        )
    except ImportError:
        from flow_delivery_world_map_bluestacks import (
            register as register_world_map,
        )

    register_campaign(
        _BLUESTACKS_FLOW_RUNNERS,
        _BLUESTACKS_EVIDENCE_VALIDATORS,
        _BLUESTACKS_RECOVERY_HANDLERS,
    )
    register_campaign_atlas(
        _BLUESTACKS_FLOW_RUNNERS,
        _BLUESTACKS_EVIDENCE_VALIDATORS,
        _BLUESTACKS_RECOVERY_HANDLERS,
    )
    register_ultimate_challenge(
        _BLUESTACKS_FLOW_RUNNERS,
        _BLUESTACKS_EVIDENCE_VALIDATORS,
        _BLUESTACKS_RECOVERY_HANDLERS,
    )
    register_ruins(
        _BLUESTACKS_FLOW_RUNNERS,
        _BLUESTACKS_EVIDENCE_VALIDATORS,
        _BLUESTACKS_RECOVERY_HANDLERS,
    )
    register_troop_training(
        _BLUESTACKS_FLOW_RUNNERS,
        _BLUESTACKS_EVIDENCE_VALIDATORS,
        _BLUESTACKS_RECOVERY_HANDLERS,
    )
    register_enhancement(
        _BLUESTACKS_FLOW_RUNNERS,
        _BLUESTACKS_EVIDENCE_VALIDATORS,
        _BLUESTACKS_RECOVERY_HANDLERS,
    )
    register_world_map(
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
    values.setdefault(
        "UNRAID_TEMP_USERNAME", os.environ.get("UNRAID_TEMP_USERNAME", "")
    )
    values.setdefault(
        "UNRAID_TEMP_PASSWORD", os.environ.get("UNRAID_TEMP_PASSWORD", "")
    )
    if not values["UNRAID_TEMP_USERNAME"] or not values["UNRAID_TEMP_PASSWORD"]:
        raise OperatorError(
            "approved Unraid credentials are not available in the process environment"
        )
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
        str(Path("/mnt/c/Program Files/PuTTY/plink.exe")),
        "-batch",
        "-hostkey",
        cfg.host_key,
        "-pw",
        password,
        f"{username}@{cfg.host}",
        command,
    ]


def run_remote(cfg: OperatorConfig, command: str) -> str:
    result = subprocess.run(
        _plink_argv(cfg, command), check=False, capture_output=True, text=True
    )
    if result.returncode:
        detail = "\n".join(
            part for part in (result.stdout.strip(), result.stderr.strip()) if part
        )
        raise OperatorError("remote command failed:\n" + detail)
    return result.stdout


def _windows_path(value: str) -> str:
    if value.startswith("/mnt/") and len(value) > 6:
        drive = value[5].upper()
        return drive + ":/" + value[7:]
    return value


def _pscp_argv(
    cfg: OperatorConfig,
    sources: Iterable[str],
    destination: str,
    recursive: bool = False,
    *,
    local_sources: bool = True,
    local_destination: bool = False,
) -> list[str]:
    username, password = load_credentials()
    args = [
        str(Path("/mnt/c/Program Files/PuTTY/pscp.exe")),
        "-batch",
        "-hostkey",
        cfg.host_key,
        "-pw",
        password,
    ]
    if recursive:
        args.append("-r")
    args.extend(
        _windows_path(source) if local_sources else f"{username}@{cfg.host}:{source}"
        for source in sources
    )
    if local_destination:
        args.append(_windows_path(destination))
    else:
        args.append(f"{username}@{cfg.host}:{destination}")
    return args


def run_pscp(
    cfg: OperatorConfig,
    sources: Iterable[str],
    destination: str,
    recursive: bool = False,
    *,
    local_sources: bool = True,
    local_destination: bool = False,
) -> None:
    result = subprocess.run(
        _pscp_argv(
            cfg,
            sources,
            destination,
            recursive,
            local_sources=local_sources,
            local_destination=local_destination,
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise OperatorError(
            "evidence/workspace synchronization failed: " + result.stderr.strip()
        )


def _adb_shell(cfg: OperatorConfig, command: str) -> str:
    script = (
        "if test -x /opt/adb; then adb_bin=/opt/adb; else adb_bin=$(command -v adb); fi; "
        "export HOME=/tmp; export ADB_SERVER_PORT=5042; unset ADB_SERVER_SOCKET; "
        f'exec "$adb_bin" -s {quote(cfg.serial)} {command}'
    )
    return (
        f"docker exec -e ADB_SERVER_SOCKET={quote(cfg.adb_socket)} {quote(cfg.container)} "
        f"sh -lc {quote(script)}"
    )


def _safe_name(value: str) -> str:
    if not NAME_RE.fullmatch(value):
        raise OperatorError(
            "operation name must contain only letters, numbers, dot, dash, or underscore"
        )
    return value


def sync_workspace(cfg: OperatorConfig) -> None:
    run_remote(
        cfg,
        f"mkdir -p {quote(cfg.remote_workspace)}/{M6_ASSET_ROOT}",
    )
    sources = ["scripts", "tasks", "safe_action_core", "runtime-profile", "tests"]
    for source in sources:
        run_pscp(
            cfg, [str(cfg.repo_root / source)], cfg.remote_workspace, recursive=True
        )
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
    return run_remote(
        cfg,
        f"docker ps -a --filter name=^{re.escape(cfg.container)}$ --format '{{{{.Names}}}} {{{{.Status}}}}'",
    )


def worker_stop(cfg: OperatorConfig) -> str:
    return run_remote(cfg, f"docker rm -f {quote(cfg.container)} 2>/dev/null || true")


def adb_start(cfg: OperatorConfig) -> str:
    command = (
        f"docker exec -e ADB_SERVER_SOCKET={quote(cfg.adb_socket)} {quote(cfg.container)} "
        "sh -lc 'if test -x /opt/adb; then adb_bin=/opt/adb; else adb_bin=$(command -v adb); fi; "
        'export HOME=/tmp; export ADB_SERVER_PORT=5042; unset ADB_SERVER_SOCKET; "$adb_bin" start-server; '
        f'"$adb_bin" -s {quote(cfg.serial)} connect {quote(cfg.serial)}; "$adb_bin" devices\''
    )
    return run_remote(cfg, command)


def launch(cfg: OperatorConfig) -> str:
    return run_remote(
        cfg, _adb_shell(cfg, f"shell am start -W -n {quote(cfg.activity)}")
    )


def capture(cfg: OperatorConfig, name: str) -> str:
    name = _safe_name(name)
    remote_path = f"{cfg.remote_evidence}/{name}.png"
    return run_remote(
        cfg, f"{_adb_shell(cfg, 'exec-out screencap -p')} > {quote(remote_path)}"
    )


def observe(cfg: OperatorConfig, name: str) -> str:
    capture_started = time.time()
    capture(cfg, name)
    capture_completed = time.time()
    status = run_remote(
        cfg,
        _adb_shell(
            cfg, "shell dumpsys window | grep -E 'mCurrentFocus|mFocusedApp' | head -2"
        ),
    )
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
    "cash-home": (
        "cash",
        "home",
        "HOME_BASE",
        "CASH_MALL_BACK",
        "standard-game-back-arrow",
        (45, 5, 130, 60),
        "tap",
        None,
    ),
    "home-quest": (
        "home",
        "quest",
        "QUEST",
        "HOME_TO_QUEST",
        "home-quest-entry",
        (250, 1130, 410, 1280),
        "tap",
        None,
    ),
    "quest-daily": (
        "quest",
        "daily",
        "DAILY_QUEST",
        "QUEST_TO_DAILY",
        "quest-daily-tab",
        (300, 70, 500, 140),
        "tap",
        None,
    ),
    "daily-scroll-up": (
        "daily",
        "daily",
        "DAILY_QUEST",
        "SCROLL_DAILY_QUEST",
        "daily-scroll-viewport",
        (100, 520, 700, 1120),
        "swipe",
        (400, 1000, 400, 500, 350),
    ),
    "daily-scroll-up-fine": (
        "daily",
        "daily",
        "DAILY_QUEST",
        "SCROLL_DAILY_QUEST_FINE",
        "daily-scroll-viewport",
        (100, 520, 700, 1120),
        "swipe",
        (400, 800, 400, 700, 250),
    ),
    "daily-scroll-up-micro": (
        "daily",
        "daily",
        "DAILY_QUEST",
        "SCROLL_DAILY_QUEST_MICRO",
        "daily-scroll-viewport",
        (100, 520, 700, 1120),
        "swipe",
        (400, 760, 400, 710, 200),
    ),
    "daily-scroll-down": (
        "daily",
        "daily",
        "DAILY_QUEST",
        "SCROLL_DAILY_QUEST",
        "daily-scroll-viewport",
        (100, 160, 700, 760),
        "swipe",
        (400, 500, 400, 1000, 350),
    ),
    "daily-scroll-down-fine": (
        "daily",
        "daily",
        "DAILY_QUEST",
        "SCROLL_DAILY_QUEST_FINE",
        "daily-scroll-viewport",
        (100, 160, 700, 760),
        "swipe",
        (400, 700, 400, 800, 250),
    ),
    "daily-bioenhancer-go": (
        "daily_bioenhancer",
        "bioenhancer",
        "BIOENHANCER",
        "DAILY_BIOENHANCER_GO",
        "daily-bioenhancer-go",
        (554, 870, 731, 933),
        "tap",
        None,
    ),
    "bioenhancer-daily-back": (
        "bioenhancer",
        "home",
        "HOME_BASE",
        "BIOENHANCER_TO_HOME",
        "bioenhancer-daily-back",
        (31, 1, 138, 55),
        "tap",
        None,
    ),
    "daily-supply-depot-go": (
        "daily",
        "supply_depot",
        "SUPPLY_DEPOT",
        "DAILY_SUPPLY_DEPOT_GO",
        "daily-supply-depot-go",
        (554, 786, 731, 878),
        "tap",
        None,
    ),
    "supply-depot-daily-back": (
        "supply_depot",
        "home",
        "HOME_BASE",
        "SUPPLY_DEPOT_TO_HOME",
        "supply-depot-daily-back",
        (31, 1, 138, 55),
        "tap",
        None,
    ),
    "alliance-fort-dismiss": (
        "alliance_fort",
        "home",
        "ALLIANCE_FORT_DISMISSED",
        "DISMISS_ALLIANCE_FORT_WAVE",
        "alliance-fort-wave-dismiss-x",
        (620, 360, 735, 455),
        "tap",
        None,
    ),
}


def navigate(cfg: OperatorConfig, step: str) -> str:
    if step not in NAVIGATION_STEPS:
        raise OperatorError(
            "navigate accepts only the checked-in route names: "
            + ", ".join(sorted(NAVIGATION_STEPS))
        )
    (
        source_mode,
        expected_mode,
        expected_state,
        semantic,
        target,
        roi,
        input_kind,
        swipe,
    ) = NAVIGATION_STEPS[step]
    stamp = str(int(time.time()))
    args = [
        "python3",
        "scripts/mvp_quest_to_claim.py",
        "--cash-reference",
        f"/workspace/{CASH_REFERENCE}",
        "--home-reference",
        "/workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/home-base-settled.png",
        "--quest-reference",
        "/workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/quest-main-settled.png",
        "--daily-reference",
        "/workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/daily-quest-settled.png",
        "--main-quest-reference",
        "/workspace/evidence/sessions/20260712-m6-dq-bootstrap/assets/quest-main-settled.png",
        "execute",
        "--database",
        f"/evidence/actions-nav-{step}-{stamp}.sqlite3",
        "--evidence",
        "/evidence",
        "--owner",
        "pnsctl-" + stamp,
        "--action-id",
        "nav-" + step + "-" + stamp,
        "--action-key",
        "nav-" + step + "-" + stamp,
        "--source-mode",
        source_mode,
        "--expected-mode",
        expected_mode,
        "--expected-state",
        expected_state,
        "--target",
        target,
        "--roi",
        *map(str, roi),
        "--semantic-action",
        semantic,
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
            raise OperatorError(
                "Daily Claim requires an explicit current game-day identity"
            )
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
            raise OperatorError(
                "Bioenhancer research requires an explicit current game-day identity"
            )
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
        "vip-popup",
        "praise",
        "praise-route-evidence",
        "praise-leaderboard-evidence",
        "personal-might-claim",
    }:
        popup_only = " --popup-only" if task == "vip-popup" else ""
        navigation_only = (
            " --navigation-evidence-only" if task == "praise-route-evidence" else ""
        )
        leaderboard_only = (
            " --leaderboard-evidence-only"
            if task == "praise-leaderboard-evidence"
            else ""
        )
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
        raise OperatorError(
            "requested task is not in the checked-in supervised task allowlist"
        )
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


def preserve_evidence(
    cfg: OperatorConfig, destination: Path, names: Sequence[str] = ()
) -> str:
    if not names:
        raise OperatorError(
            "preserve-evidence requires at least one exact --name; cumulative remote evidence "
            "downloads are intentionally disabled"
        )
    destination = (
        destination if destination.is_absolute() else (cfg.repo_root / destination)
    )
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
        f"find {quote(cfg.remote_evidence)} -maxdepth 1 -type f -printf '%f\n' | sort",
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
            raise OperatorError(
                "the retained action is not unresolved; refusing reinterpretation"
            )
        if args.outcome == "positive_postcondition":
            reconciliation = {
                "confirmed": True,
                "reason": args.reason,
                "evidence": args.evidence,
                "source_database": str(source),
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
            store.mark_confirmed(args.action_id, time.time(), reconciliation)
            status, reason = "confirmed", args.reason
        else:
            store.mark_cancelled(
                args.action_id, time.time(), "proven_no_effect_mistarget"
            )
            status, reason = "cancelled", "proven_no_effect_mistarget"
        store.audit(
            "MVP-QUEST-TO-CLAIM",
            "manual_reconciliation",
            time.time(),
            {
                "action_id": args.action_id,
                "result": status,
                "evidence": args.evidence,
                "source_database": str(source),
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            },
            args.action_id,
        )
        result = {
            "source": str(source),
            "output": str(output),
            "action_id": args.action_id,
            "status": status,
            "reason": reason,
        }
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
        raise OperatorError(
            "a valid local flow-delivery queue and lease are required"
        ) from exc
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


def _retained_troop_training_state(
    session_directory: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build evidence-only context for a released Troop Training session.

    This deliberately does not recreate a queue lease or runtime ownership.  It
    only lets the registered validator inspect native artifacts retained by a
    completed development session.
    """

    session = Path(session_directory).resolve()
    allowed_root = (REPO_ROOT / ".local-captures").resolve()
    try:
        session.relative_to(allowed_root)
    except ValueError as exc:
        raise OperatorError(
            "retained Troop Training session is outside .local-captures"
        ) from exc
    result_path = session / "flow-delivery-result.json"
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperatorError("retained Troop Training result is unavailable") from exc
    if (
        not isinstance(result, dict)
        or result.get("flow_id") != "TROOP-TRAINING-END-TO-END-CONSOLIDATION"
    ):
        raise OperatorError("retained session is not Troop Training evidence")
    return (
        {
            "queue_kind": "development_flow_delivery",
            "active_flow_id": result["flow_id"],
            "retained_evidence": True,
        },
        {
            "workflow": "pns-flow-delivery",
            "active_flow": result["flow_id"],
            "active_stage": "evidence_review",
            "runtime_ownership_state": "released",
            "unresolved_action_state": "clear",
            "retained_evidence": True,
        },
    )


def _retained_enhancement_state(
    session_directory: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build evidence-only context for a released Enhancement session."""

    session = Path(session_directory).resolve()
    allowed_root = (REPO_ROOT / ".local-captures").resolve()
    try:
        session.relative_to(allowed_root)
    except ValueError as exc:
        raise OperatorError(
            "retained Enhancement session is outside .local-captures"
        ) from exc
    result_path = session / "flow-delivery-result.json"
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperatorError("retained Enhancement result is unavailable") from exc
    if (
        not isinstance(result, dict)
        or result.get("flow_id") != "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION"
    ):
        raise OperatorError("retained session is not Enhancement evidence")
    return (
        {
            "queue_kind": "development_flow_delivery",
            "active_flow_id": result["flow_id"],
            "retained_evidence": True,
        },
        {
            "workflow": "pns-flow-delivery",
            "active_flow": result["flow_id"],
            "active_stage": "evidence_review",
            "runtime_ownership_state": "released",
            "unresolved_action_state": "clear",
            "retained_evidence": True,
        },
    )


def _latest_troop_training_recovery_candidate() -> Path | None:
    """Find a retained unresolved dispatch that permits safe Home recovery."""

    root = (
        BLUESTACKS_ARTIFACT_ROOT / "TROOP-TRAINING-END-TO-END-CONSOLIDATION"
    ).resolve()
    if not root.is_dir() or root.is_symlink():
        return None
    for result_path in sorted(root.rglob("flow-delivery-result.json"), reverse=True):
        if result_path.is_symlink() or not result_path.is_file():
            raise OperatorError("Troop Training recovery result path is unsafe")
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OperatorError("Troop Training recovery result is unreadable") from exc
        if not isinstance(result, dict) or result.get("flow_id") != root.name:
            continue
        if result.get("status") not in {"blocked", "unresolved", "manual_required"}:
            continue
        session = result_path.parent.resolve()
        try:
            session.relative_to(root)
        except ValueError as exc:
            raise OperatorError(
                "Troop Training recovery session escaped the flow root"
            ) from exc
        events = session / str(result.get("events_path") or "events.jsonl")
        if events.is_symlink() or not events.is_file():
            continue
        try:
            rows = [
                json.loads(line)
                for line in events.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OperatorError(
                "Troop Training recovery events are unreadable"
            ) from exc
        if any(
            isinstance(row, dict)
            and row.get("type") == "reconcile"
            and row.get("status") == "unresolved"
            and isinstance(row.get("action_key"), str)
            and row["action_key"].startswith("training:")
            for row in rows
        ):
            return session
    return None


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
    try:
        ensure_adb_ready(str(BLUESTACKS_ADB), BLUESTACKS_SERIAL)
    except ADBReadinessError as exc:
        raise OperatorError(str(exc)) from exc
    result = subprocess.run(
        [str(BLUESTACKS_ADB), "-s", BLUESTACKS_SERIAL, *arguments],
        check=False,
        capture_output=True,
        text=not binary,
    )
    if result.returncode:
        stderr = (
            result.stderr
            if isinstance(result.stderr, str)
            else result.stderr.decode(errors="replace")
        )
        raise OperatorError("fixed BlueStacks ADB operation failed: " + stderr.strip())
    return result.stdout


def bluestacks_preflight() -> str:
    queue, lease = _load_flow_delivery_state()
    state = str(_run_fixed_bluestacks_adb("get-state")).strip()
    frame = _run_fixed_bluestacks_adb("exec-out", "screencap", "-p", binary=True)
    if (
        not isinstance(frame, bytes)
        or frame[:8] != b"\x89PNG\r\n\x1a\n"
        or len(frame) < 24
    ):
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


def _development_runtime_observation() -> tuple[dict[str, Any], bytes]:
    """Validate the fixed runtime without consulting flow-delivery state."""

    state = str(_run_fixed_bluestacks_adb("get-state")).strip()
    frame = _run_fixed_bluestacks_adb("exec-out", "screencap", "-p", binary=True)
    if (
        not isinstance(frame, bytes)
        or frame[:8] != b"\x89PNG\r\n\x1a\n"
        or len(frame) < 24
    ):
        raise OperatorError("development observation did not receive a valid PNG frame")
    width = int.from_bytes(frame[16:20], "big")
    height = int.from_bytes(frame[20:24], "big")
    focus = str(_run_fixed_bluestacks_adb("shell", "dumpsys", "window"))
    focused_package = _focused_package(focus)
    if state != "device":
        raise OperatorError("approved runtime serial is not in device state")
    if (width, height) != (BLUESTACKS_NATIVE_WIDTH, BLUESTACKS_NATIVE_HEIGHT):
        raise OperatorError("development runtime frame is not native 800x1280")
    if focused_package != PACKAGE:
        raise OperatorError("Puzzles & Survival is not the foreground package")
    return (
        {
            "device_state": state,
            "foreground_package": focused_package,
            "native_width": width,
            "native_height": height,
            "frame_sha256": hashlib.sha256(frame).hexdigest(),
        },
        frame,
    )


def _checkpoint_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in DEVELOPMENT_CHECKPOINT_PATHS:
        try:
            label = str(path.relative_to(REPO_ROOT))
        except ValueError:
            label = str(path)
        hashes[label] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _development_session_directory(invocation_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", invocation_id).strip("-")
    if not safe:
        raise OperatorError("development session invocation ID is invalid")
    return DEVELOPMENT_SESSION_ROOT / safe


def _compact_development_action_results(
    event_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Pair each retained dispatch with its next native capture."""

    actions: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    for event in event_rows:
        kind = event.get("type")
        if kind == "dispatch" and event.get("execute") is not False:
            if pending is not None:
                actions.append(pending)
            pending = {
                "ordinal": len(actions) + 1,
                "action_class": "ordinary_development",
                "action_key": event.get("action_key"),
                "target_identity": event.get("target_identity"),
                "before_sha256": event.get("source_sha256"),
                "after_sha256": None,
                "after_path": None,
                "status": "post_capture_missing",
            }
        elif kind == "capture" and pending is not None:
            pending["after_sha256"] = event.get("sha256")
            pending["after_path"] = event.get("path")
            pending["status"] = "post_captured"
            actions.append(pending)
            pending = None
    if pending is not None:
        actions.append(pending)
    return actions


def _consume_delegated_receipt(
    receipt_state: Path,
    *,
    command_argv: Sequence[str],
    agent_identity: str,
    task_id: str,
    flow_id: str,
    receipt_class: str,
    scenario: str,
    variant: str,
    max_inputs: int | None = None,
):
    from scripts.flow_delivery_control import (
        DelegatedRuntimeContext,
        DelegatedRuntimeReceiptController,
    )

    controller = DelegatedRuntimeReceiptController(receipt_state)
    expected: dict[str, Any] = {}
    if max_inputs is not None:
        expected["max_total_inputs"] = max_inputs
    receipt_id = controller.inspect()["receipt_id"]
    receipt = controller.consume(
        receipt_id=receipt_id,
        agent_identity=agent_identity,
        task_id=task_id,
        flow_id=flow_id,
        receipt_class=receipt_class,
        command_argv=command_argv,
        scenario=scenario,
        variant=variant,
        expected=expected,
    )
    context = DelegatedRuntimeContext(
        controller,
        receipt,
        result_identity=receipt["evidence_result_binding"]["result_identity"],
    )
    return controller, receipt, context


def _delegated_session_path(receipt: Mapping[str, Any]) -> Path:
    return _development_session_directory(f"delegated-{receipt['receipt_id']}")


def development_session_delegated_dry_run(
    *,
    receipt_state: Path,
    command_argv: Sequence[str],
    agent_identity: str,
    task_id: str,
    flow_id: str,
    scenario: str,
    variant: str,
    max_inputs: int,
) -> str:
    """Consume a receipt and write a bound result without runtime access."""

    controller, receipt, context = _consume_delegated_receipt(
        receipt_state,
        command_argv=command_argv,
        agent_identity=agent_identity,
        task_id=task_id,
        flow_id=flow_id,
        receipt_class="canary",
        scenario=scenario,
        variant=variant,
        max_inputs=max_inputs,
    )
    session_directory = _delegated_session_path(receipt)
    session_directory.mkdir(parents=True, exist_ok=False)
    result = {
        "status": "dry_run",
        "task_id": task_id,
        "flow_id": flow_id,
        "scenario": scenario,
        "variant": variant,
        "receipt_id": receipt["receipt_id"],
        "receipt_digest": receipt["receipt_digest"],
        "session_directory": str(session_directory),
        "input_count": 0,
        "runtime_access": False,
        "dispatch": False,
        "evidence_result_identity": context.result_identity,
    }
    try:
        (session_directory / "result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (session_directory / "summary.json").write_text(
            json.dumps(
                {
                    "status": "dry_run",
                    "receipt_id": receipt["receipt_id"],
                    "receipt_digest": receipt["receipt_digest"],
                    "ownership_released": True,
                    "input_count": 0,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        context.record_terminal(status="dry_run", payload=result)
    except BaseException as exc:
        failure = {
            **result,
            "status": "evidence_required",
            "error": f"{type(exc).__name__}: {exc}",
        }
        try:
            context.record_terminal(status="evidence_required", payload=failure)
        finally:
            raise
    return json.dumps(result, sort_keys=True)


def development_session_observe(
    *,
    max_inputs: int = 12,
    delegated_receipt: Path | None = None,
    agent_identity: str | None = None,
    task_id: str | None = None,
    flow_id: str | None = None,
    scenario: str | None = None,
    variant: str | None = None,
    command_argv: Sequence[str] | None = None,
) -> str:
    """Observe the current runtime under automatic singleton ownership."""

    from scripts.navigation_development_boundary import DevelopmentSession
    from scripts.navigation_development_boundary import delegated_runtime_context

    if delegated_receipt is not None:
        if max_inputs != 0:
            raise OperatorError("delegated reconnaissance observation requires max_inputs=0")
        values = (agent_identity, task_id, flow_id, scenario, variant, command_argv)
        if any(value is None for value in values):
            raise OperatorError("delegated observation requires complete receipt bindings")
        _controller, receipt, context = _consume_delegated_receipt(
            delegated_receipt,
            command_argv=command_argv,
            agent_identity=str(agent_identity),
            task_id=str(task_id),
            flow_id=str(flow_id),
            receipt_class="reconnaissance",
            scenario=str(scenario),
            variant=str(variant),
            max_inputs=0,
        )
        invocation_id = f"delegated-{receipt['receipt_id']}"
        session_directory = _development_session_directory(invocation_id)
        before = _checkpoint_hashes()
        result: dict[str, Any] = {
            "status": "evidence_required",
            "flow_id": flow_id,
            "receipt_id": receipt["receipt_id"],
            "receipt_digest": receipt["receipt_digest"],
            "input_count": 0,
            "runtime_access": True,
            "dispatch": False,
            "session_directory": str(session_directory),
            "evidence_result_identity": context.result_identity,
        }
        terminal_recorded = False
        try:
            with delegated_runtime_context(context):
                with DevelopmentSession(
                    owner=f"pnsctl-delegated-observe:{flow_id}",
                    invocation_id=invocation_id,
                    session_directory=session_directory,
                    max_inputs=0,
                    allow_zero_inputs=True,
                ) as session:
                    observation, frame = _development_runtime_observation()
                    (session_directory / "observe.png").write_bytes(frame)
                    result.update({"status": "observed", "observation": observation})
                    (session_directory / "result.json").write_text(
                        json.dumps(result, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
            if (
                not (session_directory / "observe.png").is_file()
                or not (session_directory / "result.json").is_file()
                or not (session_directory / "summary.json").is_file()
                or session._ownership.lock.held
            ):
                raise OperatorError("delegated observation evidence or ownership release is unproven")
            if _checkpoint_hashes() != before:
                raise OperatorError("delegated observation mutated a checkpoint artifact")
            context.record_terminal(status="observed", payload=result)
            terminal_recorded = True
        except BaseException as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
            if not terminal_recorded:
                context.record_terminal(status="evidence_required", payload=result)
            raise
        return json.dumps(result, sort_keys=True)
    if max_inputs < 1:
        raise OperatorError("ordinary observation requires max_inputs >= 1")
    invocation_id = f"observe-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    session_directory = _development_session_directory(invocation_id)
    before = _checkpoint_hashes()
    with DevelopmentSession(
        owner="pnsctl-development-observe",
        invocation_id=invocation_id,
        session_directory=session_directory,
        max_inputs=max_inputs,
    ):
        observation, frame = _development_runtime_observation()
        (session_directory / "observe.png").write_bytes(frame)
        if _checkpoint_hashes() != before:
            raise OperatorError(
                "ordinary observation mutated a persistent checkpoint artifact"
            )
        result = {
            "status": "observed",
            "session_directory": str(session_directory),
            "observation": observation,
            "input_count": 0,
            "lifecycle_state_created": False,
        }
        (session_directory / "result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return json.dumps(result, sort_keys=True)


def development_session_run_flow(
    flow_id: str,
    *,
    live: bool,
    yes: bool,
    max_inputs: int = 12,
    recovery_only: bool = False,
    search_entry_only: bool = False,
    recovery_session: Path | None = None,
    chests_only: bool = False,
    chest_continuation: Path | str | None = None,
    enhancement_variant: str = "gear",
    delegated_receipt: Path | None = None,
    agent_identity: str | None = None,
    task_id: str | None = None,
    scenario: str | None = None,
    variant: str | None = None,
    command_argv: Sequence[str] | None = None,
) -> str:
    """Run a complete registered flow without queue, lease, replay, or preflight ceremony."""

    from scripts.navigation_development_boundary import DevelopmentSession
    from scripts.navigation_development_boundary import delegated_runtime_context

    if search_entry_only:
        if recovery_only:
            raise OperatorError(
                "--search-entry-only and --recovery-only are mutually exclusive"
            )
        if flow_id != "WORLD-MAP-NAVIGATION-FOUNDATION":
            raise OperatorError(
                "--search-entry-only is supported only for World navigation"
            )
        max_inputs = 1

    delegated_context = None
    delegated_receipt_payload = None
    delegated_scope = nullcontext()
    if delegated_receipt is not None:
        values = (agent_identity, task_id, scenario, variant, command_argv)
        if any(value is None for value in values):
            raise OperatorError("delegated canary requires complete receipt bindings")
        _controller, delegated_receipt_payload, delegated_context = _consume_delegated_receipt(
            delegated_receipt,
            command_argv=command_argv,
            agent_identity=str(agent_identity),
            task_id=str(task_id),
            flow_id=flow_id,
            receipt_class="canary",
            scenario=str(scenario),
            variant=str(variant),
            max_inputs=max_inputs,
        )
        delegated_scope = delegated_runtime_context(delegated_context)

    ruins_reset_identity: str | None = None
    ruins_current_day: str | None = None
    ruins_package_id: str | None = None
    ruins_runtime_profile_id: str | None = None
    troop_training_reset_identity: str | None = None
    enhancement_reset_identity: str | None = None

    if chest_continuation is not None:
        chest_continuation = Path(chest_continuation)

    if flow_id not in BLUESTACKS_FLOW_IDS:
        raise OperatorError("flow ID is not in the checked-in runtime allowlist")
    contract = _load_bluestacks_flow_registry().get(flow_id)
    if contract is None or contract["runner"] not in _BLUESTACKS_FLOW_RUNNERS:
        raise OperatorError("DEVELOPMENT_FLOW_RUNNER_UNAVAILABLE")
    if live and not yes:
        raise OperatorError("live development session requires --yes")
    if recovery_only:
        if (
            flow_id == "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION"
            and recovery_session is None
        ):
            raise OperatorError("Ruins recovery requires --recovery-session")
        if flow_id not in {
            "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION",
            "TROOP-TRAINING-END-TO-END-CONSOLIDATION",
            "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION",
            "WORLD-MAP-NAVIGATION-FOUNDATION",
        }:
            raise OperatorError(
                "recovery-only is unsupported for this development flow"
            )
    if chests_only and flow_id != "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION":
        raise OperatorError(
            "chests-only is supported only for the Ruins Challenge flow"
        )
    if chests_only and recovery_only:
        raise OperatorError(
            "Ruins chests-only and recovery-only modes are mutually exclusive"
        )
    if (
        chest_continuation is not None
        and flow_id != "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION"
    ):
        raise OperatorError(
            "--chest-continuation is supported only for the Ruins Challenge flow"
        )
    if chest_continuation is not None and not chests_only:
        raise OperatorError("--chest-continuation requires --chests-only")
    if chest_continuation is not None and not chest_continuation.is_file():
        raise OperatorError("Ruins chest continuation file is unavailable")
    if flow_id == "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION":
        # Bind the child route's reset/day identity once, before singleton
        # ownership or runtime observation, so a midnight boundary cannot make
        # a previously validated continuation mismatch during execution.
        from tasks.ruins_challenge_continuation import (
            PACKAGE_ID as CONTINUATION_PACKAGE_ID,
            RUNTIME_PROFILE_ID as CONTINUATION_RUNTIME_PROFILE_ID,
        )

        identity_now = datetime.now(timezone.utc)
        ruins_reset_identity = (
            f"local-{identity_now.date().isoformat()}-ruins-home-atlas"
        )
        ruins_current_day = identity_now.astimezone().strftime("%a")
        ruins_package_id = CONTINUATION_PACKAGE_ID
        ruins_runtime_profile_id = CONTINUATION_RUNTIME_PROFILE_ID
    elif flow_id == "TROOP-TRAINING-END-TO-END-CONSOLIDATION":
        # Reset-scoped training state is bound once for this development session.
        # The child route receives this exact value; it must not derive a second
        # identity after runtime ownership or observation begins.
        identity_now = datetime.now(timezone.utc)
        troop_training_reset_identity = (
            f"local-{identity_now.date().isoformat()}-troop-training-consolidation"
        )
    elif flow_id == "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION":
        enhancement_variant = str(enhancement_variant).strip().lower()
        if enhancement_variant not in {"gear", "chip", "module"}:
            raise OperatorError(
                "Enhancement development-session variant is unsupported"
            )
        identity_now = datetime.now(timezone.utc)
        enhancement_reset_identity = (
            f"local-{identity_now.date().isoformat()}-enhancement-{enhancement_variant}"
        )
    if chest_continuation is not None:
        from tasks.ruins_challenge_continuation import (
            FLOW_ID as CONTINUATION_FLOW_ID,
            RuinsContinuationError,
            load_continuation,
        )

        try:
            load_continuation(
                chest_continuation,
                expected_flow_id=CONTINUATION_FLOW_ID,
                expected_reset_identity=ruins_reset_identity,
                expected_current_day=ruins_current_day,
                expected_runtime_profile_id=CONTINUATION_RUNTIME_PROFILE_ID,
                expected_package_id=CONTINUATION_PACKAGE_ID,
            )
        except RuinsContinuationError as exc:
            raise OperatorError(
                f"Ruins chest continuation rejected: {exc.reason}"
            ) from exc
    invocation_id = (
        f"{flow_id}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    )
    session_directory = _development_session_directory(invocation_id)
    owner = f"pnsctl-development-session:{flow_id}"
    checkpoint_before = _checkpoint_hashes()
    previous_limit = os.environ.get("PNS_DEVELOPMENT_MAX_INPUTS")
    if delegated_context is not None:
        delegated_scope.__enter__()
    try:
        os.environ["PNS_DEVELOPMENT_MAX_INPUTS"] = str(max_inputs)
        with DevelopmentSession(
            owner=owner,
            invocation_id=invocation_id,
            session_directory=session_directory,
            max_inputs=max_inputs,
        ) as session:
            observation, frame = _development_runtime_observation()
            (session_directory / "source.png").write_bytes(frame)
            queue_context = {
                "active_flow_id": flow_id,
                "development_session": True,
            }
            runtime_context = {
                "owner": owner,
                "runtime_ownership_state": "held",
                "unresolved_action_state": "not_applicable",
                "development_session": True,
                "recovery_only": recovery_only,
                "search_entry_only": search_entry_only,
                "recovery_session": str(recovery_session)
                if recovery_session is not None
                else None,
                "chests_only": chests_only,
                "chest_continuation": str(chest_continuation)
                if chest_continuation is not None
                else None,
                "ruins_reset_identity": ruins_reset_identity,
                "ruins_current_day": ruins_current_day,
                "ruins_package_id": ruins_package_id,
                "ruins_runtime_profile_id": ruins_runtime_profile_id,
                "troop_training_reset_identity": troop_training_reset_identity,
                "troop_training_recovery_only": (
                    recovery_only
                    and flow_id == "TROOP-TRAINING-END-TO-END-CONSOLIDATION"
                ),
                "enhancement_variant": enhancement_variant,
                "enhancement_reset_identity": enhancement_reset_identity,
                "enhancement_recovery_only": (
                    recovery_only
                    and flow_id == "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION"
                ),
                "max_inputs": max_inputs,
            }
            runner = _BLUESTACKS_FLOW_RUNNERS[contract["runner"]]
            if "live" in inspect.signature(runner).parameters:
                raw = runner(queue_context, runtime_context, live=live)
            elif live:
                raw = runner(queue_context, runtime_context)
            else:
                raw = json.dumps(
                    {
                        "status": "dry_run",
                        "flow_id": flow_id,
                        "dispatch": False,
                        "session_directory": "",
                    },
                    sort_keys=True,
                )
            result = json.loads(raw)
            child_text = str(result.get("session_directory") or "")
            child = Path(child_text) if child_text else None
            event_rows: list[dict[str, Any]] = []
            if child is not None and child.is_dir():
                events = child / "events.jsonl"
                if events.is_file():
                    for line in events.read_text(encoding="utf-8").splitlines():
                        row = json.loads(line) if line.strip() else {}
                        if row:
                            event_rows.append(row)
            action_rows = _compact_development_action_results(event_rows)
            dispatch_count = len(action_rows)
            if dispatch_count > max_inputs:
                raise OperatorError("development session exceeded its input limit")
            session.input_count = dispatch_count
            session.actions = action_rows
            if action_rows:
                with (session_directory / "actions.jsonl").open(
                    "w", encoding="utf-8", newline="\n"
                ) as handle:
                    for row in action_rows:
                        handle.write(json.dumps(row, sort_keys=True) + "\n")
            result_status = str(result.get("status") or "unknown")
            if result_status not in {"completed", "dry_run", "observed"}:
                session.terminal_status = "blocked"
                session.blocker = str(
                    result.get("reason") or "development result is not terminal"
                )
                session.next_action = (
                    f"inspect {child_text or session_directory} and repair recognition or recovery "
                    f"for {session.blocker} before rerunning materially changed behavior"
                )
            if _checkpoint_hashes() != checkpoint_before:
                raise OperatorError(
                    "ordinary development session mutated a checkpoint artifact"
                )
            wrapper = {
                "status": result.get("status", "unknown"),
                "flow_id": flow_id,
                "session_directory": str(session_directory),
                "runtime_session_directory": child_text,
                "input_count": dispatch_count,
                "max_inputs": max_inputs,
                "chest_continuation": str(chest_continuation)
                if chest_continuation is not None
                else None,
                "runtime_observation": observation,
                "lifecycle_state_created": False,
                "persistent_checkpoint_artifacts_unchanged": True,
                "result": result,
            }
            if delegated_receipt_payload is not None:
                wrapper["receipt_id"] = delegated_receipt_payload["receipt_id"]
                wrapper["receipt_digest"] = delegated_receipt_payload["receipt_digest"]
                wrapper["evidence_result_identity"] = delegated_context.result_identity
            (session_directory / "result.json").write_text(
                json.dumps(wrapper, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        if delegated_context is not None:
            if (
                not (session_directory / "source.png").is_file()
                or not (session_directory / "result.json").is_file()
                or not (session_directory / "summary.json").is_file()
                or session._ownership.lock.held
            ):
                raise OperatorError("delegated flow evidence or ownership release is unproven")
            terminal_status = str(result.get("status") or "evidence_required")
            if terminal_status not in delegated_receipt_payload["permitted_terminal_states"]:
                terminal_status = "evidence_required"
            delegated_context.record_terminal(status=terminal_status, payload=wrapper)
    except BaseException as exc:
        if delegated_context is not None:
            delegated_context.record_terminal(
                status="evidence_required",
                payload={
                    "status": "evidence_required",
                    "receipt_id": delegated_receipt_payload["receipt_id"],
                    "receipt_digest": delegated_receipt_payload["receipt_digest"],
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
        raise
    finally:
        if previous_limit is None:
            os.environ.pop("PNS_DEVELOPMENT_MAX_INPUTS", None)
        else:
            os.environ["PNS_DEVELOPMENT_MAX_INPUTS"] = previous_limit
        if delegated_context is not None:
            delegated_scope.__exit__(None, None, None)
    return json.dumps(wrapper, sort_keys=True)


def bluestacks_reload_game() -> str:
    queue, lease = _load_flow_delivery_state()
    if lease.get("runtime_ownership_state") != "held":
        raise OperatorError("the parent must hold BlueStacks runtime ownership")
    if lease.get("unresolved_action_state") != "clear":
        raise OperatorError("unresolved action blocks BlueStacks game reload")
    state = str(_run_fixed_bluestacks_adb("get-state")).strip()
    if state != "device":
        raise OperatorError("approved BlueStacks serial is not in device state")
    resolved_activity = (
        str(
            _run_fixed_bluestacks_adb(
                "shell",
                "cmd",
                "package",
                "resolve-activity",
                "--brief",
                "-a",
                "android.intent.action.MAIN",
                "-c",
                "android.intent.category.LAUNCHER",
                PACKAGE,
            )
        )
        .strip()
        .splitlines()[-1]
    )
    if not resolved_activity.startswith(f"{PACKAGE}/"):
        raise OperatorError(
            "installed Puzzles & Survival launcher activity was not resolved"
        )
    _run_fixed_bluestacks_adb("shell", "am", "force-stop", PACKAGE)
    _run_fixed_bluestacks_adb("shell", "am", "start", "-W", "-n", resolved_activity)
    deadline = time.monotonic() + 30.0
    focused_package = None
    while time.monotonic() < deadline:
        focus = str(_run_fixed_bluestacks_adb("shell", "dumpsys", "window"))
        try:
            focused_package = _focused_package(focus)
        except OperatorError:
            focused_package = None
        if focused_package == PACKAGE:
            break
        time.sleep(1.0)
    if focused_package != PACKAGE:
        raise OperatorError(
            "Puzzles & Survival did not return to foreground after reload"
        )
    return json.dumps(
        {
            "status": "reloaded",
            "flow_id": queue["active_flow_id"],
            "serial": BLUESTACKS_SERIAL,
            "foreground_package": focused_package,
            "dispatch": True,
            "action": "force_stop_then_start_checked_in_activity",
            "resolved_activity": resolved_activity,
        },
        sort_keys=True,
    )


def bluestacks_dismiss_reload_overlay(
    expected_frame_sha256: str, expected_frame: Path
) -> str:
    queue, lease = _load_flow_delivery_state()
    if lease.get("runtime_ownership_state") != "held":
        raise OperatorError("the parent must hold BlueStacks runtime ownership")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_frame_sha256):
        raise OperatorError("expected frame SHA-256 is invalid")
    focus = str(_run_fixed_bluestacks_adb("shell", "dumpsys", "window"))
    if _focused_package(focus) != PACKAGE:
        raise OperatorError(
            "Puzzles & Survival is not foreground before overlay dismissal"
        )
    artifact_root = BLUESTACKS_ARTIFACT_ROOT.resolve()
    reference_path = expected_frame.resolve()
    try:
        reference_path.relative_to(artifact_root)
    except ValueError as exc:
        raise OperatorError(
            "expected overlay frame must be retained under the BlueStacks artifact root"
        ) from exc
    reference = reference_path.read_bytes()
    if hashlib.sha256(reference).hexdigest() != expected_frame_sha256:
        raise OperatorError(
            "expected overlay frame hash does not match retained evidence"
        )
    before = _run_fixed_bluestacks_adb("exec-out", "screencap", "-p", binary=True)
    if not isinstance(before, bytes):
        raise OperatorError("reload overlay immediate-before capture failed")
    import cv2
    import numpy as np

    reference_image = cv2.imdecode(
        np.frombuffer(reference, dtype=np.uint8), cv2.IMREAD_GRAYSCALE
    )
    before_image = cv2.imdecode(
        np.frombuffer(before, dtype=np.uint8), cv2.IMREAD_GRAYSCALE
    )
    if (
        reference_image is None
        or before_image is None
        or reference_image.shape != before_image.shape
    ):
        raise OperatorError("reload overlay reference geometry is invalid")
    similarity = float(
        cv2.matchTemplate(before_image, reference_image, cv2.TM_CCOEFF_NORMED)[0, 0]
    )
    if similarity < 0.98:
        raise OperatorError(
            "reload overlay visual identity changed; Back dispatch is not authorized"
        )
    session = (
        BLUESTACKS_ARTIFACT_ROOT
        / queue["active_flow_id"]
        / f"reload-overlay-dismiss-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    )
    session.mkdir(parents=True, exist_ok=False)
    (session / "immediate-before.png").write_bytes(before)
    _run_fixed_bluestacks_adb("shell", "input", "keyevent", "4")
    time.sleep(2.0)
    after = _run_fixed_bluestacks_adb("exec-out", "screencap", "-p", binary=True)
    if not isinstance(after, bytes):
        raise OperatorError("reload overlay dismissal did not produce a post frame")
    (session / "immediate-post.png").write_bytes(after)
    result = {
        "status": "dismissed",
        "flow_id": queue["active_flow_id"],
        "action": "android_back_on_exact_reload_offer_frame",
        "before_sha256": expected_frame_sha256,
        "immediate_before_sha256": hashlib.sha256(before).hexdigest(),
        "visual_similarity": similarity,
        "after_sha256": hashlib.sha256(after).hexdigest(),
        "session_directory": str(session),
        "dispatch": True,
    }
    (session / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return json.dumps(result, sort_keys=True)


def bluestacks_run_flow(flow_id: str, *, live: bool) -> str:
    if flow_id not in BLUESTACKS_FLOW_IDS:
        raise OperatorError("flow ID is not in the checked-in BlueStacks allowlist")
    contract = _load_bluestacks_flow_registry().get(flow_id)
    if contract is None or contract["runner"] not in _BLUESTACKS_FLOW_RUNNERS:
        raise OperatorError("FLOW_DELIVERY_RUNNER_UNAVAILABLE")
    if not live:
        if flow_id == "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION":
            queue, lease = _load_flow_delivery_state(require_runtime_held=False)
            if queue["active_flow_id"] != flow_id:
                raise OperatorError("only the active development flow may run")
            if lease.get("active_stage") not in {
                "focused_validation",
                "live_preflight",
            }:
                raise OperatorError(
                    "Ruins zero-transport replay requires focused validation or live preflight"
                )
            return _BLUESTACKS_FLOW_RUNNERS[contract["runner"]](
                queue, lease, live=False
            )
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
    invocation_id = (
        f"{flow_id}:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    )
    with NavigationDevelopmentSession(owner=owner, invocation_id=invocation_id):
        queue, lease = _load_flow_delivery_state()
        if queue["active_flow_id"] != flow_id:
            raise OperatorError("only the active development flow may run")
        flow = next(item for item in queue["flows"] if item["flow_id"] == flow_id)
        if flow.get("last_completed_stage") != "live_execution":
            raise OperatorError(
                "controller has not admitted the flow to live_execution"
            )
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


def _session_evidence_file(
    session: Path, ref: Any, *, field: str = "evidence_refs"
) -> Path:
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
        raise OperatorError(
            f"{field} must resolve to a regular non-symlink file under the session"
        )
    return resolved


def _persist_nova_session_result(
    session_directory: str | Path,
    updates: Mapping[str, Any],
    *,
    candidate_commit: str | None = None,
) -> dict[str, Any]:
    """Merge authoritative accounting into the session result.json on disk."""

    session = Path(session_directory)
    allowed_root = (REPO_ROOT / ".local-captures").resolve()
    try:
        resolved_session = session.resolve()
        resolved_session.relative_to(allowed_root)
    except (OSError, ValueError) as exc:
        raise OperatorError(
            "session directory must resolve under .local-captures"
        ) from exc
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
        raise OperatorError(
            "session result.json is required before accounting persistence"
        ) from exc
    if not isinstance(payload, dict):
        raise OperatorError("session result.json must be an object")
    payload.update(dict(updates))
    # Future-proof identity: every persisted supervised result binds session + commit.
    payload["session_directory"] = str(resolved_session)
    commit = (
        candidate_commit
        if candidate_commit is not None
        else payload.get("candidate_commit")
    )
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise OperatorError("persisted result requires exact 40-char candidate_commit")
    payload["candidate_commit"] = commit
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
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
        and NOVA_COOLDOWN_MINIMUM_ACCEPTABLE_SECONDS
        <= cooldown
        <= NOVA_POLICY_COOLDOWN_SECONDS
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
    if session_directory:
        existing = payload.get("session_directory")
        if (
            isinstance(existing, str)
            and existing.strip()
            and not _paths_exactly_equal(Path(existing), Path(session_directory))
        ):
            raise OperatorError("guard session_directory changed at finalization")
        payload["session_directory"] = str(Path(session_directory).resolve())
    elif payload.get("session_directory") in (None, ""):
        payload["session_directory"] = session_directory
    payload["finished_at"] = (
        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _bind_nova_supervised_invocation_guard_session(session_directory: str) -> None:
    """Atomically bind the active guard to a session as soon as it exists.

    Preserves guard identity/status fields. Never deletes the guard or weakens O_EXCL.
    """

    path = NOVA_SUPERVISED_INVOCATION_GUARD
    if os.path.islink(path) or not path.is_file():
        raise OperatorError("supervised invocation guard is missing or unsafe")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperatorError("supervised invocation guard is unreadable") from exc
    if not isinstance(payload, dict):
        raise OperatorError("supervised invocation guard must be an object")
    for key in (
        "schema_version",
        "flow_id",
        "scenario_id",
        "reset_id",
        "candidate_commit",
    ):
        if key not in payload:
            raise OperatorError(f"guard missing identity field {key}")
    if payload.get("flow_id") != NOVA_SUPERVISED_PULSE_FLOW_ID:
        raise OperatorError("guard flow_id mismatch during session bind")
    if payload.get("scenario_id") != NOVA_SUPERVISED_PULSE_SCENARIO_ID:
        raise OperatorError("guard scenario_id mismatch during session bind")
    if payload.get("reset_id") != NOVA_SUPERVISED_PULSE_RESET_ID:
        raise OperatorError("guard reset_id mismatch during session bind")
    if not isinstance(payload.get("candidate_commit"), str) or not re.fullmatch(
        r"[0-9a-f]{40}", payload["candidate_commit"]
    ):
        raise OperatorError("guard candidate_commit invalid during session bind")
    bound = Path(session_directory).resolve()
    allowed_root = NOVA_SUPERVISED_PULSE_OUTPUT_DEFAULT.resolve()
    try:
        bound.relative_to(allowed_root)
    except ValueError as exc:
        raise OperatorError(
            "session directory must remain under supervised output root"
        ) from exc
    if not bound.is_dir() or os.path.islink(bound):
        raise OperatorError("session directory is unavailable or unsafe")
    existing = payload.get("session_directory")
    if isinstance(existing, str) and existing.strip():
        if not _paths_exactly_equal(Path(existing), bound):
            raise OperatorError("guard already bound to a different session_directory")
        return
    payload["session_directory"] = str(bound)
    payload["session_bound_at"] = (
        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    tmp = path.with_suffix(path.suffix + ".tmp")
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    flags = os.O_CREAT | os.O_TRUNC | os.O_WRONLY
    fd = os.open(str(tmp), flags)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
        os.replace(str(tmp), str(path))
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise


def _read_jsonl_objects(path: Path, field: str) -> list[dict[str, Any]]:
    """Read JSONL objects; empty files are allowed (unlike the completed-session verifier)."""

    if os.path.islink(path) or not path.is_file():
        raise OperatorError(f"{field} must be a regular non-symlink file")
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
    return rows


_NOVA_SESSION_NAME_RE = re.compile(r"^nova-praise-one-free-pulse-(\d{8}T\d{6})(\d*)Z$")


def _parse_iso_z(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise OperatorError(f"{label} is required")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise OperatorError(f"{label} is not a valid timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_supervised_session_stamp(session_name: str) -> datetime:
    match = _NOVA_SESSION_NAME_RE.fullmatch(session_name)
    if match is None:
        raise OperatorError(
            "session directory name must be nova-praise-one-free-pulse-<UTC-stamp>Z"
        )
    base = datetime.strptime(match.group(1), "%Y%m%dT%H%M%S").replace(
        tzinfo=timezone.utc
    )
    frac = match.group(2) or ""
    if frac:
        micro = int((frac + "000000")[:6])
        base = base.replace(microsecond=micro)
    return base


def _paths_exactly_equal(left: Path, right: Path) -> bool:
    return Path(os.path.abspath(os.path.normpath(str(left)))) == Path(
        os.path.abspath(os.path.normpath(str(right)))
    )


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _list_in_window_supervised_sessions(
    *,
    started: datetime,
    finished: datetime,
) -> list[Path]:
    root = NOVA_SUPERVISED_PULSE_OUTPUT_DEFAULT
    if not root.is_dir():
        return []
    matches: list[Path] = []
    for child in root.iterdir():
        if not child.is_dir() or os.path.islink(child):
            continue
        try:
            stamp = _parse_supervised_session_stamp(child.name)
        except OperatorError:
            continue
        if started <= stamp <= finished:
            matches.append(child.resolve())
    return sorted(matches, key=lambda item: item.name)


def _verify_nova_supervised_proven_no_effect_session(
    session_directory: Path,
    *,
    guard: Mapping[str, Any],
    legacy_null_session_recovery: bool = False,
    expected_candidate_commit: str | None = None,
) -> dict[str, Any]:
    """Fail-closed proof that a supervised session issued zero Praise/consequential transport."""

    from tasks.nova_praise import NOVA_PRAISE_TARGET
    from tasks.nova_praise_pulse import NOVA_TASK_ID

    session = session_directory.resolve()
    allowed_root = NOVA_SUPERVISED_PULSE_OUTPUT_DEFAULT.resolve()
    try:
        session.relative_to(allowed_root)
    except ValueError as exc:
        raise OperatorError(
            "session directory must remain under the supervised pulse output root"
        ) from exc
    if (
        os.path.islink(session_directory)
        or os.path.islink(session)
        or not session.is_dir()
    ):
        raise OperatorError("session directory is unavailable or unsafe")
    session_stamp = _parse_supervised_session_stamp(session.name)

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
    if result.get("flow_id") != guard.get("flow_id"):
        raise OperatorError("result flow_id does not match guard")
    if result.get("scenario_id") != guard.get("scenario_id"):
        raise OperatorError("result scenario_id does not match guard")
    if result.get("status") not in {"failed", "blocked", "unresolved"}:
        raise OperatorError(
            "proven_no_effect requires a non-completed supervised status"
        )

    result_session = result.get("session_directory")
    if not isinstance(result_session, str) or not result_session.strip():
        raise OperatorError("result session_directory is required for guard binding")
    if not _paths_exactly_equal(Path(result_session), session):
        raise OperatorError(
            "result session_directory does not bind the supplied session"
        )

    candidate = guard.get("candidate_commit")
    if not isinstance(candidate, str) or not re.fullmatch(r"[0-9a-f]{40}", candidate):
        raise OperatorError(
            "guard candidate_commit must be a 40-char lowercase git SHA"
        )
    result_candidate = result.get("candidate_commit")
    guard_session = guard.get("session_directory")
    guard_session_missing = guard_session is None or (
        isinstance(guard_session, str) and not guard_session.strip()
    )
    result_commit_missing = result_candidate is None or (
        isinstance(result_candidate, str) and not result_candidate.strip()
    )
    if isinstance(result_candidate, str) and result_candidate.strip():
        if not re.fullmatch(r"[0-9a-f]{40}", result_candidate):
            raise OperatorError(
                "result candidate_commit must be a 40-char lowercase git SHA"
            )
        if result_candidate != candidate:
            raise OperatorError(
                "result candidate_commit does not match the active guard"
            )

    legacy_recovery_used = False
    current_head: str | None = None
    in_window: list[Path] = []
    if legacy_null_session_recovery:
        if not guard_session_missing or not result_commit_missing:
            raise OperatorError(
                "legacy_null_session_recovery is only for null guard session and missing result commit"
            )
        if not isinstance(expected_candidate_commit, str) or not re.fullmatch(
            r"[0-9a-f]{40}", expected_candidate_commit
        ):
            raise OperatorError(
                "legacy recovery requires --expected-candidate-commit as a 40-char git SHA"
            )
        if expected_candidate_commit != candidate:
            raise OperatorError(
                "expected candidate commit does not match guard.candidate_commit"
            )
        current_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if current_head != expected_candidate_commit:
            raise OperatorError(
                "current git HEAD must exactly equal the expected legacy candidate commit"
            )
        started = _parse_iso_z(guard.get("started_at"), "guard started_at")
        finished = _parse_iso_z(guard.get("finished_at"), "guard finished_at")
        if finished < started:
            raise OperatorError("guard finished_at precedes started_at")
        in_window = _list_in_window_supervised_sessions(
            started=started, finished=finished
        )
        if len(in_window) == 0:
            raise OperatorError(
                "no supervised session stamp falls within the guard window"
            )
        if len(in_window) > 1:
            raise OperatorError(
                "multiple supervised sessions fall within the guard window; legacy recovery blocked"
            )
        if in_window[0] != session:
            raise OperatorError(
                "supplied session is not the unique in-window supervised session"
            )
        if session_stamp < started or session_stamp > finished:
            raise OperatorError(
                "session stamp is outside the guard started_at/finished_at window"
            )
        legacy_recovery_used = True
    else:
        if result_commit_missing:
            raise OperatorError(
                "result candidate_commit is required; use --legacy-null-session-recovery only for the audited legacy guard"
            )
        if result_candidate != candidate:
            raise OperatorError(
                "result candidate_commit does not match the active guard"
            )
        if guard_session_missing:
            raise OperatorError(
                "guard session_directory is required for normal reconciliation"
            )
        if not isinstance(guard_session, str):
            raise OperatorError("guard session_directory must be a string")
        if not _paths_exactly_equal(Path(guard_session), session):
            raise OperatorError(
                "guard session_directory does not bind the supplied session"
            )

    action_database = result.get("action_database")
    if not isinstance(action_database, str) or not action_database.strip():
        raise OperatorError("result action_database is required")
    db_path = _require_exact_nonsymlink_path(
        Path(action_database),
        NOVA_SUPERVISED_ACTION_DATABASE,
        "action_database",
    )
    if not db_path.is_file() or os.path.islink(db_path):
        raise OperatorError(
            "action_database must exist as a regular non-symlink SQLite file"
        )

    journal_rows = _read_jsonl_objects(session / "journal.jsonl", "journal.jsonl")
    if not journal_rows:
        raise OperatorError("journal.jsonl must be nonempty")
    journal = journal_rows[-1]
    # Production supervised journals do not emit flow_id; bind strongest fields present.
    if "flow_id" in journal and journal.get("flow_id") not in (
        None,
        NOVA_SUPERVISED_PULSE_FLOW_ID,
    ):
        raise OperatorError("journal flow_id mismatch")
    if journal.get("scenario_id") != NOVA_SUPERVISED_PULSE_SCENARIO_ID:
        raise OperatorError("journal scenario_id mismatch")
    if journal.get("scenario_id") != result.get("scenario_id"):
        raise OperatorError("journal scenario_id does not match result")
    if journal.get("status") not in {"failed", "blocked", "unresolved"}:
        raise OperatorError("journal status is not a proven_no_effect terminal")
    if journal.get("status") != result.get("status"):
        raise OperatorError("journal status does not match result status")
    nav = result.get("navigation_input_count")
    if type(nav) is not int or nav < 0:
        raise OperatorError("navigation_input_count must be a non-negative int")
    if journal.get("navigation_input_count") != nav:
        raise OperatorError("journal navigation_input_count mismatch")
    if "praise_transport_calls" in journal:
        journal_praise = journal.get("praise_transport_calls")
        if type(journal_praise) is not int or journal_praise < 0:
            raise OperatorError(
                "journal praise_transport_calls must be a non-negative int"
            )
        if (
            "praise_transport_calls" in result
            and result.get("praise_transport_calls") != journal_praise
        ):
            raise OperatorError("journal praise_transport_calls does not match result")
    if "reason" in journal and journal.get("reason") not in (
        None,
        "",
        result.get("reason"),
    ):
        raise OperatorError("journal reason does not match result")
    for key in ("action_id", "action_key"):
        if key not in journal:
            continue
        journal_value = journal.get(key)
        result_value = result.get(key)
        if journal_value in (None, ""):
            continue
        if result_value not in (None, "") and journal_value != result_value:
            raise OperatorError(f"journal {key} does not match result")
    if guard.get("reset_id") != NOVA_SUPERVISED_PULSE_RESET_ID:
        raise OperatorError("guard reset_id / game-day mismatch")

    events = _read_jsonl_objects(session / "events.jsonl", "events.jsonl")
    if not events:
        raise OperatorError("events.jsonl must be nonempty")
    capability_audit = _read_jsonl_objects(
        session / "capability-audit.jsonl",
        "capability-audit.jsonl",
    )
    if not capability_audit:
        raise OperatorError("capability-audit.jsonl must be nonempty")

    praise_transport_field_present = "praise_transport_calls" in result
    praise = (
        result.get("praise_transport_calls") if praise_transport_field_present else None
    )
    if praise_transport_field_present:
        if type(praise) is not int or praise != 0:
            raise OperatorError("proven_no_effect requires praise_transport_calls == 0")

    consequential_dispatches = [
        event
        for event in events
        if event.get("type") == "dispatch" and event.get("consequential") is True
    ]
    if consequential_dispatches:
        raise OperatorError(
            "events.jsonl records consequential transport; not proven_no_effect"
        )
    praise_dispatches = [
        event
        for event in events
        if event.get("type") == "dispatch"
        and (
            str(event.get("action_key") or "").startswith("nova-praise:")
            or event.get("target_identity") == NOVA_PRAISE_TARGET
        )
    ]
    if praise_dispatches:
        raise OperatorError(
            "events.jsonl records Praise dispatch; not proven_no_effect"
        )

    praise_captures = [
        event
        for event in events
        if event.get("type") == "capture"
        and isinstance(event.get("label"), str)
        and str(event["label"]).startswith("praise-central-")
    ]
    post_praise_frames = [
        event for event in praise_captures if "post" in str(event.get("label"))
    ]
    if post_praise_frames:
        raise OperatorError(
            "events.jsonl has praise post-dispatch frames; not proven_no_effect"
        )

    scenario = result.get("scenario_record")
    result_action_id = result.get("action_id")
    result_action_key = result.get("action_key")
    praise_reached_with_action = (
        isinstance(result_action_id, str)
        and bool(result_action_id.strip())
        and isinstance(result_action_key, str)
        and bool(result_action_key.strip())
        and bool(praise_captures)
    )
    pre_praise_blocked = result.get("status") == "blocked" and not praise_captures
    praise_cancelled_before_transport = False
    bound_action_final_status: str | None = None
    bound_action_final_reason: str | None = None
    action_rows = 0
    has_action_block = False

    if pre_praise_blocked:
        if not praise_transport_field_present or praise != 0:
            raise OperatorError(
                "pre-Praise blocked proven_no_effect requires praise_transport_calls == 0"
            )
        reason = result.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise OperatorError(
                "pre-Praise blocked proven_no_effect requires result.reason"
            )
        if not isinstance(scenario, Mapping):
            raise OperatorError(
                "pre-Praise blocked proven_no_effect requires scenario_record"
            )
        if scenario.get("outcome") != "blocked":
            raise OperatorError(
                "pre-Praise blocked scenario_record.outcome must be blocked"
            )
        if scenario.get("reason") != reason:
            raise OperatorError("pre-Praise blocked scenario reason mismatch")
        if scenario.get("unresolved_action") is not False:
            raise OperatorError(
                "pre-Praise blocked requires scenario_record.unresolved_action == false"
            )
        if scenario.get("praise_transport_calls") not in (0, None):
            if (
                type(scenario.get("praise_transport_calls")) is not int
                or int(scenario["praise_transport_calls"]) != 0
            ):
                raise OperatorError(
                    "pre-Praise blocked scenario praise_transport_calls must be 0"
                )
        input_class = scenario.get("input_class")
        if input_class not in {"navigation_only", "none"}:
            raise OperatorError(
                "pre-Praise blocked requires navigation_only or none input_class"
            )
        scenario_nav = scenario.get("navigation_input_count")
        if scenario_nav is not None and scenario_nav != nav:
            raise OperatorError(
                "pre-Praise blocked scenario navigation_input_count mismatch"
            )
        if input_class == "none" and nav != 0:
            raise OperatorError(
                "pre-Praise blocked none input_class requires zero navigation"
            )
        if input_class == "navigation_only" and nav < 1:
            raise OperatorError(
                "pre-Praise blocked navigation_only requires navigation_input_count >= 1"
            )
        if "reason" in journal and journal.get("reason") not in (None, "", reason):
            raise OperatorError("pre-Praise blocked journal reason mismatch")
        if journal.get("status") != "blocked":
            raise OperatorError("pre-Praise blocked journal status must be blocked")
        # Navigation may be authorized; forbid only consequential / Praise transport in audit.
        praise_transport_audit = [
            row
            for row in capability_audit
            if row.get("consequential") is True
            and row.get("transport_observed") is True
        ]
        if praise_transport_audit:
            raise OperatorError(
                "capability-audit.jsonl records consequential transport; not proven_no_effect"
            )
        for row in capability_audit:
            if "transport_calls" in row and row.get("transport_calls") not in (0, None):
                if (
                    type(row.get("transport_calls")) is not int
                    or int(row["transport_calls"]) != 0
                ):
                    raise OperatorError("capability-audit transport_calls must be zero")
            action_id = row.get("action_id")
            if isinstance(action_id, str) and action_id.startswith("nova-praise-"):
                raise OperatorError(
                    "pre-Praise blocked capability-audit must not list Nova Praise"
                )
            if row.get("target_identity") == NOVA_PRAISE_TARGET:
                raise OperatorError(
                    "pre-Praise blocked capability-audit must not target Praise"
                )
    elif praise_reached_with_action:
        if not praise_transport_field_present or praise != 0:
            raise OperatorError(
                "Praise-reached cancelled proven_no_effect requires praise_transport_calls == 0"
            )
        reason = result.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise OperatorError(
                "Praise-reached cancelled proven_no_effect requires result.reason"
            )
        if not isinstance(scenario, Mapping):
            raise OperatorError(
                "Praise-reached cancelled proven_no_effect requires scenario_record"
            )
        if scenario.get("reason") != reason:
            raise OperatorError("Praise-reached cancelled scenario reason mismatch")
        if scenario.get("unresolved_action") is not False:
            raise OperatorError(
                "Praise-reached cancelled requires scenario_record.unresolved_action == false"
            )
        if scenario.get("praise_transport_calls") not in (0, None):
            if (
                type(scenario.get("praise_transport_calls")) is not int
                or int(scenario["praise_transport_calls"]) != 0
            ):
                raise OperatorError(
                    "Praise-reached cancelled scenario praise_transport_calls must be 0"
                )
        if journal.get("action_id") not in (None, "", result_action_id):
            raise OperatorError("journal action_id does not match result")
        if journal.get("action_key") not in (None, "", result_action_key):
            raise OperatorError("journal action_key does not match result")
        if "reason" in journal and journal.get("reason") not in (None, "", reason):
            raise OperatorError("Praise-reached cancelled journal reason mismatch")

        last_praise_capture_ts = max(
            str(event.get("timestamp") or "") for event in praise_captures
        )
        if not last_praise_capture_ts:
            raise OperatorError("praise-central captures lack timestamps")
        dispatch_after_praise = [
            event
            for event in events
            if event.get("type") == "dispatch"
            and str(event.get("timestamp") or "") > last_praise_capture_ts
        ]
        if dispatch_after_praise:
            raise OperatorError(
                "dispatch occurred after praise-central captures; not proven_no_effect"
            )

        # Navigation capability-audit.jsonl is not Praise transport proof; only reject
        # explicit consequential Praise signals if present.
        for row in capability_audit:
            if (
                row.get("consequential") is True
                and row.get("transport_observed") is True
            ):
                if (
                    str(row.get("action_id") or "").startswith("nova-praise-")
                    or row.get("target_identity") == NOVA_PRAISE_TARGET
                ):
                    raise OperatorError(
                        "capability-audit.jsonl records Praise consequential transport"
                    )

        from safe_action_core import SafetyStore
        from safe_action_core.store import StoreError

        store = SafetyStore(db_path)
        try:
            try:
                action_row = store.get_action(str(result_action_id))
            except StoreError as exc:
                raise OperatorError(
                    "bound Praise action_id is missing from SafetyStore"
                ) from exc
            if action_row.get("action_key") != result_action_key:
                raise OperatorError("SafetyStore action_key does not match result")
            if action_row.get("action_id") != result_action_id:
                raise OperatorError("SafetyStore action_id does not match result")
            final_status = action_row.get("final_status")
            if final_status in {"confirmed", "input_sent", "unresolved", "prepared"}:
                raise OperatorError(
                    f"Praise action final_status={final_status} is not cancelled-before-transport"
                )
            if final_status != "cancelled":
                raise OperatorError(
                    "Praise-reached proven_no_effect requires cancelled action row"
                )
            final_reason = action_row.get("final_reason")
            if not isinstance(final_reason, str) or not final_reason.strip():
                raise OperatorError("cancelled Praise action lacks final_reason")
            if final_reason != reason and not final_reason.endswith(":" + reason):
                raise OperatorError(
                    "cancelled Praise final_reason does not match result.reason"
                )
            if action_row.get("input_attempt_at") not in (None, ""):
                raise OperatorError("cancelled Praise action recorded input_attempt_at")
            if action_row.get("transport_result_json") not in (None, "", "null"):
                raise OperatorError(
                    "cancelled Praise action recorded transport_result_json"
                )

            audit_rows = store.audit_events(str(result_action_id))
            if not audit_rows:
                raise OperatorError("Praise action lacks SQLite audit_events chain")
            saw_cancel_transition = False
            for audit in audit_rows:
                event_type = str(audit.get("event_type") or "")
                lifecycle_to = audit.get("lifecycle_to")
                if lifecycle_to in {"input_sent", "confirmed", "unresolved"}:
                    raise OperatorError(
                        "Praise audit chain records transport or unresolved lifecycle"
                    )
                if event_type in {
                    "input_sent",
                    "transport_success",
                    "transport_dispatched",
                    "dispatched",
                }:
                    raise OperatorError(
                        "Praise audit chain records dispatch/transport success"
                    )
                payload_raw = audit.get("payload_json")
                payload: Any
                if isinstance(payload_raw, str) and payload_raw.strip():
                    try:
                        payload = json.loads(payload_raw)
                    except json.JSONDecodeError as exc:
                        raise OperatorError(
                            "Praise audit payload_json is invalid JSON"
                        ) from exc
                elif isinstance(payload_raw, Mapping):
                    payload = payload_raw
                else:
                    payload = {}
                if not isinstance(payload, Mapping):
                    raise OperatorError("Praise audit payload must be an object")
                if (
                    payload.get("transport_observed") is True
                    or payload.get("transport_occurred") is True
                ):
                    raise OperatorError("Praise audit records transport observed")
                if "transport_calls" in payload and payload.get(
                    "transport_calls"
                ) not in (0, None):
                    if (
                        type(payload.get("transport_calls")) is not int
                        or int(payload["transport_calls"]) != 0
                    ):
                        raise OperatorError("Praise audit transport_calls must be zero")
                if lifecycle_to == "cancelled" or (
                    event_type == "action_transition" and lifecycle_to == "cancelled"
                ):
                    saw_cancel_transition = True
                    cancel_reason = None
                    if isinstance(payload.get("reason"), str):
                        cancel_reason = payload["reason"]
                    if (
                        cancel_reason
                        and cancel_reason != reason
                        and not cancel_reason.endswith(":" + reason)
                    ):
                        raise OperatorError(
                            "Praise cancel audit reason does not match result"
                        )
            if not saw_cancel_transition:
                raise OperatorError("Praise audit chain lacks cancelled transition")

            if store.list_unresolved_actions():
                raise OperatorError("SafetyStore has unresolved action rows")
            if store.list_nonterminal_actions():
                raise OperatorError("SafetyStore has nonterminal action rows")
            if store.has_action_block():
                raise OperatorError(
                    "SafetyStore has an action block; not proven_no_effect"
                )
            has_action_block = False
            action_rows = len(store.list_actions_for_task(NOVA_TASK_ID))
            if action_rows < 1:
                raise OperatorError("SafetyStore missing bound Nova Praise action row")
            praise_cancelled_before_transport = True
            bound_action_final_status = "cancelled"
            bound_action_final_reason = final_reason
        finally:
            store.close()
    else:
        if not praise_captures:
            raise OperatorError(
                "events.jsonl lacks praise-central captures required for audit proof"
            )
        last_praise_capture_ts = max(
            str(event.get("timestamp") or "") for event in praise_captures
        )
        if not last_praise_capture_ts:
            raise OperatorError("praise-central captures lack timestamps")
        dispatch_after_praise = [
            event
            for event in events
            if event.get("type") == "dispatch"
            and str(event.get("timestamp") or "") > last_praise_capture_ts
        ]
        if dispatch_after_praise:
            raise OperatorError(
                "dispatch occurred after praise-central captures; not proven_no_effect"
            )

        praise_transport_audit = [
            row
            for row in capability_audit
            if row.get("consequential") is True
            and row.get("transport_observed") is True
        ]
        if praise_transport_audit:
            raise OperatorError(
                "capability-audit.jsonl records consequential transport; not proven_no_effect"
            )
        for row in capability_audit:
            if "transport_calls" in row and row.get("transport_calls") not in (0, None):
                if (
                    type(row.get("transport_calls")) is not int
                    or int(row["transport_calls"]) != 0
                ):
                    raise OperatorError("capability-audit transport_calls must be zero")
            action_id = row.get("action_id")
            if isinstance(action_id, str) and action_id.startswith("nova-praise-"):
                if row.get("transport_observed") is True:
                    raise OperatorError("capability-audit shows Nova Praise transport")
                if row.get("transport_calls") not in (0, None):
                    raise OperatorError(
                        "capability-audit Nova Praise transport_calls must be zero"
                    )
        terminal_audit = capability_audit[-1]
        if terminal_audit.get("transport_observed") is not False:
            raise OperatorError(
                "capability-audit terminal row must show transport_observed=false"
            )
        if terminal_audit.get("authorized") is not False:
            raise OperatorError("capability-audit terminal row must be unauthorized")

        if not praise_transport_field_present:
            if not (
                praise_captures
                and not post_praise_frames
                and not consequential_dispatches
                and not praise_dispatches
                and not dispatch_after_praise
                and terminal_audit.get("transport_observed") is False
            ):
                raise OperatorError(
                    "missing praise_transport_calls without a complete zero-transport audit chain"
                )

    if not praise_cancelled_before_transport:
        try:
            connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        except sqlite3.Error as exc:
            raise OperatorError(
                "action_database could not be opened read-only"
            ) from exc
        try:
            connection.row_factory = sqlite3.Row
            no_effect_clause = (
                "final_status='cancelled' "
                "AND input_attempt_at IS NULL "
                "AND transport_result_json IS NULL"
            )
            action_count = connection.execute(
                f"SELECT COUNT(*) AS n FROM actions WHERE NOT ({no_effect_clause})"
            ).fetchone()["n"]
            nova_count = connection.execute(
                f"SELECT COUNT(*) AS n FROM actions WHERE task_id=? AND NOT ({no_effect_clause})",
                (NOVA_TASK_ID,),
            ).fetchone()["n"]
        finally:
            connection.close()
        if int(action_count) != 0 or int(nova_count) != 0:
            raise OperatorError("SafetyStore has action rows; not proven_no_effect")
        from safe_action_core import SafetyStore
        from safe_action_core.store import is_no_effect_cancelled

        store = SafetyStore(db_path)
        try:
            if store.has_action_block():
                raise OperatorError(
                    "SafetyStore has an action block; not proven_no_effect"
                )
            remaining_nova_actions = [
                row
                for row in store.list_actions_for_task(NOVA_TASK_ID)
                if not is_no_effect_cancelled(row)
            ]
            if remaining_nova_actions:
                raise OperatorError(
                    "SafetyStore lists Nova actions; not proven_no_effect"
                )
            has_action_block = False
            action_rows = 0
        finally:
            store.close()

    evidence_hashes = {
        "result.json": _file_sha256(result_path),
        "events.jsonl": _file_sha256(session / "events.jsonl"),
        "capability-audit.jsonl": _file_sha256(session / "capability-audit.jsonl"),
        "journal.jsonl": _file_sha256(session / "journal.jsonl"),
        "action_database": _file_sha256(db_path),
    }

    return {
        "result": result,
        "session_directory": str(session),
        "navigation_input_count": nav,
        "praise_transport_calls": 0 if not praise_transport_field_present else praise,
        "praise_transport_calls_field_present": praise_transport_field_present,
        "events_count": len(events),
        "capability_audit_count": len(capability_audit),
        "action_rows": action_rows,
        "has_action_block": has_action_block,
        "praise_cancelled_before_transport": praise_cancelled_before_transport,
        "bound_action_id": result_action_id
        if praise_cancelled_before_transport
        else None,
        "bound_action_final_status": bound_action_final_status,
        "bound_action_final_reason": bound_action_final_reason,
        "guard_session_directory": guard_session,
        "candidate_commit": candidate,
        "session_stamp": session_stamp.isoformat().replace("+00:00", "Z"),
        "legacy_null_session_recovery": legacy_recovery_used,
        "expected_candidate_commit": expected_candidate_commit
        if legacy_recovery_used
        else None,
        "current_head": current_head if legacy_recovery_used else None,
        "in_window_session_count": len(in_window) if legacy_recovery_used else None,
        "evidence_hashes": evidence_hashes,
    }


def reconcile_nova_supervised_invocation_guard_proven_no_effect(
    session_directory: Path,
    *,
    legacy_null_session_recovery: bool = False,
    expected_candidate_commit: str | None = None,
) -> str:
    """Archive the active Nova supervised guard only after audited proven-no-effect proof."""

    guard_path = NOVA_SUPERVISED_INVOCATION_GUARD
    if os.path.islink(guard_path) or not guard_path.is_file():
        raise OperatorError("supervised invocation guard is missing or unsafe")
    try:
        guard = json.loads(guard_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperatorError("supervised invocation guard is unreadable") from exc
    if not isinstance(guard, dict):
        raise OperatorError("supervised invocation guard must be an object")
    if guard.get("schema_version") != 1:
        raise OperatorError("unsupported supervised invocation guard schema")
    if guard.get("flow_id") != NOVA_SUPERVISED_PULSE_FLOW_ID:
        raise OperatorError("guard flow_id mismatch")
    if guard.get("scenario_id") != NOVA_SUPERVISED_PULSE_SCENARIO_ID:
        raise OperatorError("guard scenario_id mismatch")
    if guard.get("reset_id") != NOVA_SUPERVISED_PULSE_RESET_ID:
        raise OperatorError("guard reset_id mismatch")
    terminal = guard.get("terminal_status") or guard.get("status")
    guard_result_status = guard.get("result_status")
    # Historical blocked finals wrote terminal_status=failed while result_status=blocked.
    historical_blocked_guard = terminal == "failed" and guard_result_status == "blocked"
    blocked_guard = terminal == "blocked" or historical_blocked_guard
    if terminal != "unresolved" and not blocked_guard:
        raise OperatorError(
            "only an unresolved or blocked supervised guard may be reconciled as proven_no_effect"
        )
    if (
        not isinstance(guard.get("candidate_commit"), str)
        or not str(guard["candidate_commit"]).strip()
    ):
        raise OperatorError("guard candidate_commit is required")

    proof = _verify_nova_supervised_proven_no_effect_session(
        session_directory,
        guard=guard,
        legacy_null_session_recovery=legacy_null_session_recovery,
        expected_candidate_commit=expected_candidate_commit,
    )
    result = proof["result"]
    if blocked_guard:
        if result.get("status") != "blocked":
            raise OperatorError(
                "blocked-guard reconcile requires result.status == blocked"
            )
        if guard_result_status != "blocked":
            raise OperatorError(
                "blocked-guard reconcile requires guard.result_status == blocked"
            )
        reason = result.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise OperatorError(
                "blocked-guard reconcile requires a nonempty result.reason"
            )
        scenario = result.get("scenario_record")
        if not isinstance(scenario, Mapping):
            raise OperatorError(
                "blocked-guard reconcile requires result.scenario_record"
            )
        if scenario.get("outcome") != "blocked":
            raise OperatorError(
                "blocked-guard reconcile requires scenario_record.outcome == blocked"
            )
        if scenario.get("unresolved_action") is not False:
            raise OperatorError(
                "blocked-guard reconcile requires scenario_record.unresolved_action == false"
            )
        if scenario.get("reason") != reason:
            raise OperatorError(
                "blocked-guard reconcile requires matching blocked reason"
            )
        if scenario.get("praise_transport_calls") not in (0, None):
            if (
                type(scenario.get("praise_transport_calls")) is not int
                or int(scenario["praise_transport_calls"]) != 0
            ):
                raise OperatorError(
                    "blocked-guard reconcile requires scenario praise_transport_calls == 0"
                )
        if proof["praise_transport_calls"] != 0:
            raise OperatorError(
                "blocked-guard reconcile requires praise_transport_calls == 0"
            )
        if proof.get("praise_cancelled_before_transport"):
            if proof["has_action_block"] is not False:
                raise OperatorError(
                    "blocked-guard reconcile requires no SafetyStore action block"
                )
            if proof.get("bound_action_final_status") != "cancelled":
                raise OperatorError(
                    "blocked-guard cancelled Praise path requires preserved cancelled action row"
                )
        elif proof["action_rows"] != 0 or proof["has_action_block"] is not False:
            raise OperatorError("blocked-guard reconcile requires an empty SafetyStore")
        journal_rows = _read_jsonl_objects(
            Path(proof["session_directory"]) / "journal.jsonl",
            "journal.jsonl",
        )
        journal = journal_rows[-1]
        if journal.get("status") != "blocked":
            raise OperatorError(
                "blocked-guard reconcile requires journal.status == blocked"
            )
        if "reason" in journal and journal.get("reason") not in (None, reason):
            raise OperatorError("blocked-guard reconcile journal reason mismatch")
        if "reason" in guard and guard.get("reason") not in (None, "", reason):
            raise OperatorError("blocked-guard reconcile guard reason mismatch")
    finished_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    stamp = finished_at.replace(":", "").replace("-", "").replace(".", "")
    guard_bytes = guard_path.read_bytes()
    guard_sha256 = hashlib.sha256(guard_bytes).hexdigest()
    receipt = {
        "schema_version": 1,
        "operation": "nova_supervised_invocation_guard_reconcile_proven_no_effect",
        "outcome": "proven_no_effect",
        "finished_at": finished_at,
        "guard_path": str(guard_path),
        "guard_sha256": guard_sha256,
        "guard": guard,
        "session_directory": proof["session_directory"],
        "legacy_null_session_recovery": bool(proof["legacy_null_session_recovery"]),
        "blocked_guard_reconcile": bool(blocked_guard),
        "historical_blocked_guard_terminal_failed": bool(historical_blocked_guard),
        "proof": {
            "navigation_input_count": proof["navigation_input_count"],
            "praise_transport_calls": proof["praise_transport_calls"],
            "praise_transport_calls_field_present": proof[
                "praise_transport_calls_field_present"
            ],
            "events_count": proof["events_count"],
            "capability_audit_count": proof["capability_audit_count"],
            "action_rows": proof["action_rows"],
            "has_action_block": False,
            "praise_cancelled_before_transport": bool(
                proof.get("praise_cancelled_before_transport")
            ),
            "bound_action_id": proof.get("bound_action_id"),
            "bound_action_final_status": proof.get("bound_action_final_status"),
            "bound_action_final_reason": proof.get("bound_action_final_reason"),
            "result_status": proof["result"].get("status"),
            "result_reason": proof["result"].get("reason"),
            "guard_terminal_status": terminal,
            "guard_result_status": guard_result_status,
            "candidate_commit": proof["candidate_commit"],
            "expected_candidate_commit": proof["expected_candidate_commit"],
            "current_head": proof["current_head"],
            "in_window_session_count": proof["in_window_session_count"],
            "session_stamp": proof["session_stamp"],
            "guard_session_directory": proof["guard_session_directory"],
            "evidence_hashes": proof["evidence_hashes"],
        },
        "action_database": str(NOVA_SUPERVISED_ACTION_DATABASE),
        "queue_mutated": False,
        "lease_mutated": False,
        "controller_lifecycle_mutated": False,
    }
    receipt_digest = hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    receipt["receipt_digest"] = receipt_digest

    NOVA_SUPERVISED_GUARD_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    NOVA_SUPERVISED_GUARD_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    receipt_path = (
        NOVA_SUPERVISED_GUARD_RECEIPT_DIR
        / f"proven-no-effect-{stamp}-{receipt_digest[:16]}.json"
    )
    archive_path = (
        NOVA_SUPERVISED_GUARD_ARCHIVE_DIR
        / f"nova-praise-one-free-pulse-game-day-2026-07-22.guard.{stamp}.{guard_sha256[:16]}.json"
    )
    if receipt_path.exists() or archive_path.exists():
        raise OperatorError("reconciliation receipt or archive path already exists")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    fd = os.open(str(receipt_path), flags)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    except Exception:
        raise
    # Move (never delete) the active guard so O_EXCL can create a replacement.
    os.replace(str(guard_path), str(archive_path))
    if guard_path.exists():
        raise OperatorError("active supervised guard remained after archive move")
    if not archive_path.is_file():
        raise OperatorError("archived supervised guard is missing after move")
    return json.dumps(
        {
            "status": "reconciled",
            "outcome": "proven_no_effect",
            "legacy_null_session_recovery": bool(proof["legacy_null_session_recovery"]),
            "guard_archived_to": str(archive_path),
            "receipt_path": str(receipt_path),
            "receipt_digest": receipt_digest,
            "session_directory": proof["session_directory"],
            "praise_transport_calls": 0,
            "action_rows": 0,
            "candidate_commit": proof["candidate_commit"],
        },
        sort_keys=True,
    )


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
        raise OperatorError(
            "session directory must remain under .local-captures"
        ) from exc
    if (
        os.path.islink(session_directory)
        or os.path.islink(session)
        or not session.is_dir()
    ):
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
        raise OperatorError(
            "completed supervised pulse requires navigation_input_count >= 1"
        )
    if praise != 1:
        raise OperatorError("completed supervised pulse requires exactly one Praise")
    before = result.get("attempts_before")
    after = result.get("attempts_after")
    if (
        type(before) is not int
        or type(after) is not int
        or after != before - 1
        or before <= 0
    ):
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
        raise OperatorError(
            "action_database must exist as a regular non-symlink SQLite file"
        )
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
    events = _read_nonempty_jsonl(
        session / verified_paths["events_path"], "events.jsonl"
    )
    ledger = _read_nonempty_jsonl(
        session / verified_paths["ledger_path"], "ledger.jsonl"
    )
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
        raise OperatorError(
            "events.jsonl must contain exactly one consequential dispatch"
        )
    if consequential[0].get("action_key") != action_key:
        raise OperatorError("consequential dispatch action_key mismatch")
    journal = journal_rows[-1]
    if journal.get("action_id") != action_id or journal.get("action_key") != action_key:
        raise OperatorError("journal.jsonl action identity mismatch")
    if journal.get("journal_status") != "confirmed":
        raise OperatorError("journal.jsonl status must be confirmed")
    if (
        journal.get("attempts_before") != before
        or journal.get("attempts_after") != after
    ):
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
        raise OperatorError(
            "session directory must remain under .local-captures"
        ) from exc
    if not session.is_dir() or session.is_symlink():
        raise OperatorError("session directory is unavailable or unsafe")
    result_path = session / "flow-delivery-result.json"
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperatorError("flow-delivery-result.json is required") from exc
    if (
        result.get("schema_version") != 1
        or result.get("flow_id") not in BLUESTACKS_FLOW_IDS
    ):
        raise OperatorError("unsupported flow-delivery result identity")
    result_status = result.get("status")
    if result_status != "completed":
        if result.get("flow_id") not in {
            "TROOP-TRAINING-END-TO-END-CONSOLIDATION",
            "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION",
            "WORLD-MAP-NAVIGATION-FOUNDATION",
        } or result_status not in {
            "blocked",
            "unresolved",
            "manual_required",
        }:
            raise OperatorError("flow result is not terminally completed")
    if result.get("serial") != BLUESTACKS_SERIAL:
        raise OperatorError("flow result used an unapproved serial")
    if (result.get("native_width"), result.get("native_height")) != (
        BLUESTACKS_NATIVE_WIDTH,
        BLUESTACKS_NATIVE_HEIGHT,
    ):
        raise OperatorError("flow result is not native 800x1280")
    if (
        not isinstance(result.get("runtime_owner"), str)
        or not result["runtime_owner"].strip()
    ):
        raise OperatorError("flow result does not identify the runtime owner")
    allowed_terminal_states = {"recognized_home", "safe_blocked_terminal"}
    if result.get("flow_id") == "TROOP-TRAINING-END-TO-END-CONSOLIDATION":
        allowed_terminal_states |= {"blocked", "unresolved", "manual_required"}
    elif result.get("flow_id") == "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION":
        allowed_terminal_states |= {"recognized_safe_terminal"}
    if result.get("terminal_runtime_state") not in allowed_terminal_states:
        raise OperatorError("terminal runtime state is missing or unsafe")
    actions = result.get("actions")
    if not isinstance(actions, list):
        raise OperatorError("flow result actions must be a list")
    declared_required = result.get("required_artifacts")
    required_fields = (
        set(declared_required)
        if isinstance(declared_required, list)
        and all(isinstance(item, str) for item in declared_required)
        else {"events_path", "ledger_path", "capability_audit_path", "journal_path"}
    )
    artifact_fields = (
        "events_path",
        "ledger_path",
        "capability_audit_path",
        "journal_path",
    )
    if not required_fields.issubset(set(artifact_fields)):
        raise OperatorError("flow result required artifact contract is invalid")
    verified_paths: dict[str, str] = {}
    for field in artifact_fields:
        value = result.get(field)
        if value is None:
            if field in required_fields:
                raise OperatorError(
                    f"flow result required artifact is missing: {field}"
                )
            continue
        verified_paths[field] = str(
            _session_relative_path(session, value, field).relative_to(session)
        )
        if not (session / verified_paths[field]).is_file():
            raise OperatorError(f"flow result artifact is missing: {field}")
    frames = result.get("frames")
    if not isinstance(frames, list) or not frames:
        raise OperatorError("flow result requires frame evidence")
    verified_frames = [
        str(_session_relative_path(session, value, "frames").relative_to(session))
        for value in frames
    ]
    if any(
        not (session / value).is_file() or (session / value).stat().st_size == 0
        for value in verified_frames
    ):
        raise OperatorError("flow result frame evidence is missing")
    return {
        "result": result,
        "session_directory": str(session),
        "actions": len(actions),
        "frames": verified_frames,
        "artifacts": verified_paths,
        "terminal_runtime_state": result["terminal_runtime_state"],
    }


def bluestacks_verify_flow(session_directory: Path) -> str:
    structure: dict[str, Any] | None = None
    try:
        queue, lease = _load_flow_delivery_state(require_runtime_held=False)
    except OperatorError:
        structure = _verify_flow_structure(session_directory)
        retained_flow_id = structure["result"].get("flow_id")
        if retained_flow_id == "AUTONOMY-SERVICE-CAMPAIGN-NAVIGATION-PROVING-SLICE":
            queue = {"active_flow_id": retained_flow_id}
            lease = {
                "active_stage": "evidence_review",
                "runtime_ownership_state": "released",
                "unresolved_action_state": "clear",
            }
        elif retained_flow_id == "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION":
            queue, lease = _retained_enhancement_state(session_directory)
        elif retained_flow_id == "WORLD-MAP-NAVIGATION-FOUNDATION":
            queue = {"active_flow_id": retained_flow_id}
            lease = {
                "active_stage": "evidence_review",
                "runtime_ownership_state": "released",
                "unresolved_action_state": "clear",
            }
        else:
            queue, lease = _retained_troop_training_state(session_directory)
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
    if structure is None:
        structure = _verify_flow_structure(session_directory)
    if structure["result"].get("flow_id") != flow_id:
        raise OperatorError("flow evidence belongs to another active flow")
    verdict = _BLUESTACKS_EVIDENCE_VALIDATORS[contract["evidence_validator"]](
        structure,
        queue,
        lease,
    )
    if not isinstance(verdict, dict) or verdict.get("status") not in {
        "verified",
        "evidence_required",
    }:
        raise OperatorError(
            "route-specific evidence validator did not return an accepted verdict"
        )
    return json.dumps(verdict, sort_keys=True)


def bluestacks_recover_home() -> str:
    try:
        queue, lease = _load_flow_delivery_state()
    except OperatorError:
        if _latest_troop_training_recovery_candidate() is None:
            raise
        # A released ordinary session cannot use the old lease-bound recovery
        # handler.  Reacquire singleton ownership through the same development
        # session path, and let the existing route perform only safe Back/Home
        # recovery from a positively recognized active queue.
        return development_session_run_flow(
            "TROOP-TRAINING-END-TO-END-CONSOLIDATION",
            live=True,
            yes=True,
            max_inputs=4,
            recovery_only=True,
        )
    if lease.get("active_stage") not in {
        "live_preflight",
        "live_execution",
        "evidence_review",
    }:
        raise OperatorError(
            "recover-home is available only during an admitted live delivery stage"
        )
    contract = _load_bluestacks_flow_registry().get(queue["active_flow_id"])
    if (
        contract is None
        or contract["recovery_handler"] not in _BLUESTACKS_RECOVERY_HANDLERS
    ):
        raise OperatorError("FLOW_RECOVERY_HANDLER_UNAVAILABLE")
    return _BLUESTACKS_RECOVERY_HANDLERS[contract["recovery_handler"]](queue, lease)


def bluestacks_reconcile_campaign_atlas_survey_action(
    session_directory: Path,
    *,
    action_key: str,
) -> str:
    """Offline zero-input reconciliation for one unresolved Campaign atlas survey action."""

    try:
        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            FLOW_ID,
            reconcile_campaign_atlas_survey_action_offline,
        )
    except ImportError as exc:
        raise OperatorError("Campaign atlas survey reconciler unavailable") from exc
    session = Path(session_directory)
    if not session.is_dir():
        raise OperatorError("survey session directory is missing")
    try:
        session.relative_to(BLUESTACKS_ARTIFACT_ROOT / FLOW_ID)
    except ValueError as exc:
        raise OperatorError(
            "session must live under the Campaign atlas BlueStacks artifact root"
        ) from exc
    try:
        result = reconcile_campaign_atlas_survey_action_offline(
            session,
            action_key=str(action_key),
            expected_flow_id=FLOW_ID,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise OperatorError(
            f"Campaign atlas survey offline reconciliation failed: {exc}"
        ) from exc
    if result.get("zero_input") is not True:
        raise OperatorError("offline reconciliation must remain zero-input")
    return json.dumps(result, sort_keys=True)


def nova_praise_pulse_replay(args: argparse.Namespace) -> str:
    """Run the retained production-path Nova action/cooldown replay with zero transport."""

    from safe_action_core import SafetyStore
    from scripts.nova_praise_centralized import NovaPraiseActionBoundary
    from tasks.gameplay_flow_replay import (
        ReplayNativeRuntime,
        load_retained_native_frame,
    )
    from tasks.home_atlas import load_home_atlas
    from tasks.nova_praise_pulse import NOVA_TASK_ID, NovaPulseController
    from tasks.flow_scenario_attempts import replay_validated_record
    from tasks.scheduler_task_result import SchedulerIdentity

    manifest_path = (
        REPO_ROOT / "tests" / "fixtures" / "nova_praise_replay" / "manifest.json"
    )
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
                    raise OperatorError(
                        "Nova praise route module is unavailable"
                    ) from exc
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
                route_result["candidate_commit"] = candidate_commit
                if session:
                    _bind_nova_supervised_invocation_guard_session(session)
                    route_result["session_directory"] = str(Path(session).resolve())
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
                    reason = str(
                        route_result.get("reason") or "supervised_pulse_blocked"
                    )
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
                    guard_terminal = "blocked"
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
                            "session_directory": str(Path(session).resolve()),
                            "production_registration": "NOT_REGISTERED",
                            "scheduler_enabled": False,
                            "status": route_result.get("status"),
                            "reason": route_result.get("reason"),
                        },
                        candidate_commit=candidate_commit,
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
                facts_uncertain = (
                    pending_completed_guard or result_status == "completed"
                )
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
    with NavigationDevelopmentSession(
        owner=canary_owner, invocation_id=canary_invocation
    ):
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


def noahs_tavern_navigation(args: argparse.Namespace) -> str:
    """Phase-3 navigation-only Noah's Tavern canary over the shared boundary (no recruit).

    ``--preflight-only`` is genuinely zero-transport and needs no supervised opt-in. The live
    path composes only the shared navigation-development session and the task-specific runner;
    it reads no flow-delivery queue, lease, context, receipt, governance, or backlog state.
    """

    candidate_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if getattr(args, "preflight_capture", False) and args.preflight_only:
        raise OperatorError(
            "--preflight-capture and --preflight-only are mutually exclusive"
        )
    if getattr(args, "recovery_continuation", False) and (
        getattr(args, "preflight_capture", False)
        or getattr(args, "preflight_only", False)
    ):
        raise OperatorError(
            "recovery continuation and preflight modes are mutually exclusive"
        )
    if getattr(args, "recovery_continuation", False):
        if not args.live or not args.yes or not args.supervised_live_opt_in:
            raise OperatorError(
                "recovery continuation requires --live --yes --supervised-live-opt-in"
            )
        from scripts import noahs_tavern_recruit_bluestacks as route_module
        from scripts.navigation_development_boundary import NavigationDevelopmentSession

        owner = f"pnsctl-noahs-tavern-recovery:{candidate_commit[:12]}"
        invocation_id = (
            f"noahs-tavern-recovery-{candidate_commit[:12]}-{int(time.time())}"
        )
        with NavigationDevelopmentSession(owner=owner, invocation_id=invocation_id):
            return route_module.run_noahs_tavern_recovery_continuation(args, None)
    if getattr(args, "preflight_capture", False):
        if args.live:
            raise OperatorError("--preflight-capture cannot be combined with --live")
        from scripts.noahs_tavern_recruit_bluestacks import (
            NOAHS_TAVERN_HOME_ATLAS_BUILDING_ID,
            NOAHS_TAVERN_NAV_FLOW_ID,
            NoahTavernNavigationCanaryRoute,
        )
        from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
        import cv2
        import hashlib

        from scripts.navigation_development_boundary import NavigationDevelopmentSession

        def _run_preflight_capture() -> str:
            runtime = LocalBlueStacksRuntime.connect(
                adb=str(args.adb),
                serial=args.serial,
                output_directory=args.output_directory,
                workflow="noahs-tavern-atlas-preflight",
                execute=False,
            )
            route = NoahTavernNavigationCanaryRoute(runtime, settle_seconds=0.0)
            source = runtime.capture("home-atlas-entry-preflight-source")
            localization = route.home_localizer.localize(source.frame)
            binding = route._atlas_binding(source)
            annotated_path = (
                runtime.session / "home-atlas-entry-preflight-annotated.png"
            )
            annotated = source.frame.copy()
            if binding is not None:
                x0, y0, x1, y1 = binding
                cv2.rectangle(annotated, (x0, y0), (x1, y1), (0, 255, 0), 4)
                cv2.putText(
                    annotated,
                    NOAHS_TAVERN_HOME_ATLAS_BUILDING_ID,
                    (x0, max(30, y0 - 12)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 0),
                    2,
                    cv2.LINE_AA,
                )
            cv2.imwrite(str(annotated_path), annotated)
            atlas_bytes = route.atlas_path.read_bytes()
            payload = {
                "schema_version": 1,
                "flow_id": NOAHS_TAVERN_NAV_FLOW_ID,
                "status": "preflight_capture_passed"
                if binding is not None
                else "blocked",
                "reason": "current_frame_atlas_binding"
                if binding is not None
                else "home_atlas_tavern_target_not_current_frame_bound",
                "transport_calls": 0,
                "source_frame": str(source.path),
                "source_frame_sha256": source.sha256,
                "source_frame_semantic_sha256": localization.frame_sha256,
                "annotated_frame": str(annotated_path),
                "atlas_path": str(route.atlas_path),
                "atlas_sha256": hashlib.sha256(atlas_bytes).hexdigest(),
                "building_id": NOAHS_TAVERN_HOME_ATLAS_BUILDING_ID,
                "target_roi": list(binding) if binding is not None else None,
                "localization": localization.__dict__,
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
                "session_directory": str(runtime.session),
            }
            (runtime.session / "home-atlas-entry-preflight-result.json").write_text(
                json.dumps(payload, sort_keys=True, default=str, indent=2) + "\n",
                encoding="utf-8",
            )
            return json.dumps(payload, sort_keys=True, default=str)

        owner = f"pnsctl-noahs-tavern-atlas-preflight:{candidate_commit[:12]}"
        invocation_id = (
            f"noahs-tavern-atlas-preflight-{candidate_commit[:12]}-{int(time.time())}"
        )
        with NavigationDevelopmentSession(owner=owner, invocation_id=invocation_id):
            return _run_preflight_capture()
    if args.preflight_only:
        return json.dumps(
            {
                "status": "preflight_passed",
                "scenario_id": "noahs_tavern_navigation_round_trip_no_recruit",
                "candidate_commit": candidate_commit,
                "runtime_connected": False,
                "transport_calls": 0,
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
            },
            sort_keys=True,
        )
    if not args.live:
        raise OperatorError("noahs-tavern-nav requires --live or --preflight-only")
    if not args.yes:
        raise OperatorError("live Noah's Tavern navigation requires --yes")
    if not args.supervised_live_opt_in:
        raise OperatorError(
            "live Noah's Tavern navigation requires --supervised-live-opt-in"
        )
    from scripts.navigation_development_boundary import NavigationDevelopmentSession

    try:
        from scripts import noahs_tavern_recruit_bluestacks as route_module
    except ImportError as exc:
        raise OperatorError(
            "Noah's Tavern navigation route module is unavailable"
        ) from exc
    runner = getattr(route_module, "run_noahs_tavern_navigation_canary", None)
    if not callable(runner):
        return json.dumps(
            {
                "status": "blocked",
                "reason": "NOAHS_TAVERN_NAVIGATION_ROUTE_NOT_INTEGRATED",
                "runtime_connected": False,
                "transport_calls": 0,
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
            },
            sort_keys=True,
        )
    owner = f"pnsctl-noahs-tavern-nav:{candidate_commit[:12]}"
    invocation_id = f"noahs-tavern-nav-{candidate_commit[:12]}-{int(time.time())}"
    with NavigationDevelopmentSession(owner=owner, invocation_id=invocation_id):
        return runner(args, None)


def noahs_tavern_recruit(args: argparse.Namespace) -> str:
    """Run one bounded ordinary unified Noah's Tavern recruitment pass through pnsctl."""

    candidate_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if args.preflight_only and args.live:
        raise OperatorError("--preflight-only and --live are mutually exclusive")
    if args.reconcile_session is not None:
        if args.live or args.preflight_only:
            raise OperatorError(
                "retained reconciliation is zero-input and cannot use --live or --preflight-only"
            )
        if args.state_session is None or args.terminal_home_session is None:
            raise OperatorError(
                "retained reconciliation requires --state-session and --terminal-home-session"
            )
        from scripts import noahs_tavern_recruit_bluestacks as route_module
        from tasks.scheduler_task_result import SchedulerIdentity
        from tasks.noahs_tavern_recruit_maintenance import MAINTENANCE_TASK_ID

        identity = SchedulerIdentity(
            args.account_id or "local-bluestacks-account",
            args.server_id or "local-bluestacks-server",
            args.reset_id
            or f"game-day-{datetime.now(timezone.utc).date().isoformat()}",
            MAINTENANCE_TASK_ID,
        )
        return route_module.reconcile_noahs_tavern_retained_recruit(args, identity)
    if args.preflight_only:
        from scripts.navigation_development_boundary import NavigationDevelopmentSession
        from scripts import noahs_tavern_recruit_bluestacks as route_module

        owner = f"pnsctl-noahs-tavern-recruit-preflight:{candidate_commit[:12]}"
        invocation_id = (
            f"noahs-tavern-recruit-preflight-{candidate_commit[:12]}-{int(time.time())}"
        )
        with NavigationDevelopmentSession(owner=owner, invocation_id=invocation_id):
            return route_module.run_noahs_tavern_recruitment_preflight(args)
    if not args.live:
        raise OperatorError("noahs-tavern-recruit requires --live or --preflight-only")
    if not args.yes:
        raise OperatorError("live unified recruitment requires --yes")
    if not args.supervised_live_opt_in:
        raise OperatorError(
            "live unified recruitment requires --supervised-live-opt-in"
        )
    continuation = getattr(args, "continuation_session", None) is not None
    required_cap = 4 if continuation else 12
    if args.max_inputs != required_cap:
        raise OperatorError(
            f"unified recruitment live pass requires exact {required_cap}-input cap"
        )
    from scripts.navigation_development_boundary import NavigationDevelopmentSession
    from scripts import noahs_tavern_recruit_bluestacks as route_module
    from tasks.scheduler_task_result import SchedulerIdentity
    from tasks.noahs_tavern_recruit_maintenance import MAINTENANCE_TASK_ID

    identity = SchedulerIdentity(
        args.account_id or "local-bluestacks-account",
        args.server_id or "local-bluestacks-server",
        args.reset_id or f"game-day-{datetime.now(timezone.utc).date().isoformat()}",
        MAINTENANCE_TASK_ID,
    )
    owner = f"pnsctl-noahs-tavern-recruit:{candidate_commit[:12]}"
    invocation_id = f"noahs-tavern-recruit-{candidate_commit[:12]}-{int(time.time())}"
    with NavigationDevelopmentSession(owner=owner, invocation_id=invocation_id):
        if continuation:
            return route_module.run_noahs_tavern_recruitment_continuation(
                args, identity
            )
        return route_module.run_noahs_tavern_unified_recruitment(args, identity)


def automation_service_offline(args: argparse.Namespace) -> int:
    """Backward-compatible, zero-transport delegation to automation_service."""
    from automation_service.cli import main as automation_main

    if args.automation_service_command == "campaign-plan":
        from automation_service.campaign import CampaignNavigationHandler
        from automation_service.contracts import (
            FamilyFacts,
            PerceptionEnvelope,
            SchedulerFacts,
        )

        handler = CampaignNavigationHandler(args.destination)
        plan = handler.plan(
            SchedulerFacts("offline", "offline", "offline", 0.0, health_ok=True),
            PerceptionEnvelope(
                "offline-capture",
                "home_canonical",
                "offline-profile",
                "fresh",
                family_facts=(FamilyFacts("campaign", True, {}),),
            ),
        )
        print(
            json.dumps(
                {
                    "status": "dry_run",
                    "flow_id": handler.describe().flow_id,
                    "destination": handler.destination,
                    "plan_type": type(plan).__name__,
                    "transport_count": 0,
                    "registration_status": "NOT_REGISTERED",
                    "scheduler_eligible": False,
                },
                sort_keys=True,
            )
        )
        return 0
    argv = [
        "--mode",
        args.mode,
        "status" if args.automation_service_command == "status" else "health",
    ]
    return automation_main(argv)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--run-id", default="help-all-20260713")
    sub = root.add_subparsers(dest="command", required=True)
    development = sub.add_parser("development-session")
    development_sub = development.add_subparsers(
        dest="development_command", required=True
    )
    development_observe = development_sub.add_parser("observe")
    development_observe.add_argument("--max-inputs", type=int, default=12)
    development_observe.add_argument("--delegated-receipt", type=Path)
    development_observe.add_argument("--agent-identity")
    development_observe.add_argument("--task-id")
    development_observe.add_argument("--flow-id")
    development_observe.add_argument("--scenario")
    development_observe.add_argument("--variant")
    delegated_dry_run = development_sub.add_parser("delegated-dry-run")
    delegated_dry_run.add_argument("--delegated-receipt", type=Path, required=True)
    delegated_dry_run.add_argument("--agent-identity", required=True)
    delegated_dry_run.add_argument("--task-id", required=True)
    delegated_dry_run.add_argument("--flow-id", required=True)
    delegated_dry_run.add_argument("--scenario", required=True)
    delegated_dry_run.add_argument("--variant", required=True)
    delegated_dry_run.add_argument("--max-inputs", type=int, required=True)
    development_run = development_sub.add_parser("run-flow")
    development_run.add_argument("flow_id", choices=BLUESTACKS_FLOW_IDS)
    development_run.add_argument("--live", action="store_true")
    development_run.add_argument("--yes", action="store_true")
    development_run.add_argument("--max-inputs", type=int, default=12)
    development_mode = development_run.add_mutually_exclusive_group()
    development_mode.add_argument("--recovery-only", action="store_true")
    development_mode.add_argument("--search-entry-only", action="store_true")
    development_run.add_argument("--recovery-session", type=Path, default=None)
    development_run.add_argument("--chests-only", action="store_true")
    development_run.add_argument("--chest-continuation", type=Path, default=None)
    development_run.add_argument(
        "--enhancement-variant",
        choices=("gear", "chip", "module"),
        default="gear",
    )
    development_run.add_argument("--delegated-receipt", type=Path)
    development_run.add_argument("--agent-identity")
    development_run.add_argument("--task-id")
    development_run.add_argument("--scenario")
    development_run.add_argument("--variant")
    for name in (
        "preflight",
        "worker-start",
        "worker-status",
        "worker-stop",
        "adb-start",
        "launch",
        "capture",
        "observe",
        "navigate",
        "run-task",
        "test-focused",
        "test-full",
        "validate",
        "preserve-evidence",
        "evidence-status",
        "cleanup",
    ):
        sub.add_parser(name)
    sub.choices["capture"].add_argument("--name", default="current")
    sub.choices["observe"].add_argument("--name", default="observe")
    sub.choices["navigate"].add_argument(
        "--step", required=True, choices=tuple(NAVIGATION_STEPS)
    )
    sub.choices["run-task"].add_argument(
        "--task",
        required=True,
        choices=(
            "alliance-help",
            "vip-popup",
            "praise-route-evidence",
            "praise-leaderboard-evidence",
            "praise",
            "personal-might-claim",
            "bioenhancer-free-research",
            "daily-claim",
        ),
    )
    sub.choices["run-task"].add_argument("--game-day", default="")
    sub.choices["test-focused"].add_argument("--pattern", default="test_task_module.py")
    sub.choices["preserve-evidence"].add_argument(
        "--destination", type=Path, required=True
    )
    sub.choices["preserve-evidence"].add_argument("--name", action="append", default=[])
    rec = sub.add_parser("reconcile")
    rec.add_argument("--source", type=Path, required=True)
    rec.add_argument("--output", type=Path, required=True)
    rec.add_argument("--action-id", required=True)
    rec.add_argument("--evidence", nargs="+", required=True)
    rec.add_argument(
        "--outcome",
        choices=("proven_no_effect", "positive_postcondition"),
        default="proven_no_effect",
    )
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
    tavern_nav = sub.add_parser("noahs-tavern-nav")
    tavern_nav.add_argument("--live", action="store_true")
    tavern_nav.add_argument("--preflight-only", action="store_true")
    tavern_nav.add_argument("--yes", action="store_true")
    tavern_nav.add_argument("--supervised-live-opt-in", action="store_true")
    tavern_nav.add_argument(
        "--preflight-capture",
        action="store_true",
        help="capture and annotate a zero-input canonical Home Atlas binding",
    )
    tavern_nav.add_argument(
        "--recovery-continuation",
        action="store_true",
        help="one retained Tavern safe-exit prelude, then fresh canonical round trip",
    )
    tavern_nav.add_argument(
        "--safe-exit-only",
        action="store_true",
        help="one positively recognized Tavern exit to canonical Home",
    )
    tavern_nav.add_argument("--adb", type=Path, default=BLUESTACKS_ADB)
    tavern_nav.add_argument("--serial", default=BLUESTACKS_SERIAL)
    tavern_nav.add_argument("--settle-seconds", type=float, default=1.0)
    tavern_nav.add_argument(
        "--output-directory",
        type=Path,
        default=NOAHS_TAVERN_NAV_OUTPUT_DEFAULT,
    )
    tavern_recruit = sub.add_parser("noahs-tavern-recruit")
    tavern_recruit.add_argument("--live", action="store_true")
    tavern_recruit.add_argument("--preflight-only", action="store_true")
    tavern_recruit.add_argument("--yes", action="store_true")
    tavern_recruit.add_argument("--supervised-live-opt-in", action="store_true")
    tavern_recruit.add_argument("--account-id")
    tavern_recruit.add_argument("--server-id")
    tavern_recruit.add_argument("--reset-id")
    tavern_recruit.add_argument("--continuation-session", type=Path)
    tavern_recruit.add_argument("--state-session", type=Path)
    tavern_recruit.add_argument("--reconcile-session", type=Path)
    tavern_recruit.add_argument("--terminal-home-session", type=Path)
    tavern_recruit.add_argument("--max-inputs", type=int, default=12)
    tavern_recruit.add_argument("--adb", type=Path, default=BLUESTACKS_ADB)
    tavern_recruit.add_argument("--serial", default=BLUESTACKS_SERIAL)
    tavern_recruit.add_argument("--settle-seconds", type=float, default=1.0)
    tavern_recruit.add_argument(
        "--output-directory",
        type=Path,
        default=BLUESTACKS_ARTIFACT_ROOT / "RECRUITMENT-FREE-ATTEMPT-MAINTENANCE",
    )
    nova_guard = sub.add_parser("nova-praise-supervised-guard")
    nova_guard_sub = nova_guard.add_subparsers(dest="nova_guard_command", required=True)
    nova_guard_reconcile = nova_guard_sub.add_parser("reconcile-proven-no-effect")
    nova_guard_reconcile.add_argument("--session-directory", type=Path, required=True)
    nova_guard_reconcile.add_argument(
        "--legacy-null-session-recovery",
        action="store_true",
        help="explicit one-off recovery for the audited legacy null-session guard",
    )
    nova_guard_reconcile.add_argument(
        "--expected-candidate-commit",
        default=None,
        help="required with --legacy-null-session-recovery; must match guard and HEAD",
    )
    bluestacks = sub.add_parser("bluestacks")
    bluestacks_sub = bluestacks.add_subparsers(dest="bluestacks_command", required=True)
    bluestacks_sub.add_parser("preflight")
    bluestacks_sub.add_parser("reload-game")
    dismiss_reload_overlay = bluestacks_sub.add_parser("dismiss-reload-overlay")
    dismiss_reload_overlay.add_argument("--expected-frame-sha256", required=True)
    dismiss_reload_overlay.add_argument("--expected-frame", type=Path, required=True)
    run_flow = bluestacks_sub.add_parser("run-flow")
    run_flow.add_argument("flow_id", choices=BLUESTACKS_FLOW_IDS)
    run_flow.add_argument("--live", action="store_true")
    verify_flow = bluestacks_sub.add_parser("verify-flow")
    verify_flow.add_argument("session_directory", type=Path)
    bluestacks_sub.add_parser("recover-home")
    reconcile_survey = bluestacks_sub.add_parser(
        "reconcile-campaign-atlas-survey-action",
        help=(
            "Offline zero-input reconciliation for exactly one unresolved "
            "Campaign atlas survey action (retained frames only; no runtime input)."
        ),
    )
    reconcile_survey.add_argument("--session-directory", type=Path, required=True)
    reconcile_survey.add_argument("--action-key", required=True)
    automation = sub.add_parser("automation-service")
    automation_sub = automation.add_subparsers(
        dest="automation_service_command", required=True
    )
    automation_status = automation_sub.add_parser("status")
    automation_status.add_argument(
        "--mode", choices=("disabled", "observe_only", "dry_run"), default="disabled"
    )
    automation_health = automation_sub.add_parser("health")
    automation_health.add_argument(
        "--mode", choices=("disabled", "observe_only", "dry_run"), default="disabled"
    )
    campaign_plan = automation_sub.add_parser("campaign-plan")
    campaign_plan.add_argument("--destination", default="1-20-9")
    return root


def main(argv: Sequence[str] | None = None) -> int:
    command_argv = list(sys.argv[1:] if argv is None else argv)
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
    if args.command == "noahs-tavern-nav":
        try:
            output = noahs_tavern_navigation(args)
            print(output)
            return 0
        except (OperatorError, OSError, RuntimeError, ValueError) as exc:
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "command": "noahs-tavern-nav",
                        "error": str(exc),
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 2
    if args.command == "noahs-tavern-recruit":
        try:
            output = noahs_tavern_recruit(args)
            print(output)
            return 0
        except (
            OperatorError,
            OSError,
            RuntimeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "command": "noahs-tavern-recruit",
                        "error": str(exc),
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 2
    if args.command == "nova-praise-supervised-guard":
        try:
            if args.nova_guard_command == "reconcile-proven-no-effect":
                output = reconcile_nova_supervised_invocation_guard_proven_no_effect(
                    args.session_directory,
                    legacy_null_session_recovery=bool(
                        getattr(args, "legacy_null_session_recovery", False)
                    ),
                    expected_candidate_commit=getattr(
                        args, "expected_candidate_commit", None
                    ),
                )
            else:
                raise OperatorError("unknown nova supervised guard command")
            print(output)
            return 0
        except (OperatorError, OSError, RuntimeError, ValueError) as exc:
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "command": "nova-praise-supervised-guard",
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
    if args.command == "development-session":
        try:
            if args.development_command == "observe":
                output = development_session_observe(
                    max_inputs=args.max_inputs,
                    delegated_receipt=args.delegated_receipt,
                    agent_identity=args.agent_identity,
                    task_id=args.task_id,
                    flow_id=args.flow_id,
                    scenario=args.scenario,
                    variant=args.variant,
                    command_argv=command_argv,
                )
            elif args.development_command == "delegated-dry-run":
                output = development_session_delegated_dry_run(
                    receipt_state=args.delegated_receipt,
                    command_argv=command_argv,
                    agent_identity=args.agent_identity,
                    task_id=args.task_id,
                    flow_id=args.flow_id,
                    scenario=args.scenario,
                    variant=args.variant,
                    max_inputs=args.max_inputs,
                )
            elif args.development_command == "run-flow":
                output = development_session_run_flow(
                    args.flow_id,
                    live=bool(args.live),
                    yes=bool(args.yes),
                    max_inputs=args.max_inputs,
                    recovery_only=bool(args.recovery_only),
                    search_entry_only=bool(args.search_entry_only),
                    recovery_session=args.recovery_session,
                    chests_only=bool(args.chests_only),
                    chest_continuation=args.chest_continuation,
                    enhancement_variant=args.enhancement_variant,
                    delegated_receipt=args.delegated_receipt,
                    agent_identity=args.agent_identity,
                    task_id=args.task_id,
                    scenario=args.scenario,
                    variant=args.variant,
                    command_argv=command_argv,
                )
            else:
                raise OperatorError("unknown development-session command")
            print(output)
            return 0
        except (
            OperatorError,
            OSError,
            RuntimeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "command": f"development-session {args.development_command}",
                        "error": str(exc),
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 2
    if args.command == "bluestacks":
        try:
            if args.bluestacks_command == "preflight":
                output = bluestacks_preflight()
            elif args.bluestacks_command == "reload-game":
                output = bluestacks_reload_game()
            elif args.bluestacks_command == "dismiss-reload-overlay":
                output = bluestacks_dismiss_reload_overlay(
                    args.expected_frame_sha256, args.expected_frame
                )
            elif args.bluestacks_command == "run-flow":
                output = bluestacks_run_flow(args.flow_id, live=args.live)
            elif args.bluestacks_command == "verify-flow":
                output = bluestacks_verify_flow(args.session_directory)
            elif args.bluestacks_command == "recover-home":
                output = bluestacks_recover_home()
            elif args.bluestacks_command == "reconcile-campaign-atlas-survey-action":
                output = bluestacks_reconcile_campaign_atlas_survey_action(
                    args.session_directory,
                    action_key=str(args.action_key),
                )
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
    if args.command == "automation-service":
        try:
            return automation_service_offline(args)
        except (OperatorError, OSError, RuntimeError, ValueError) as exc:
            print("pnsctl: " + str(exc), file=sys.stderr)
            return 2
    cfg = OperatorConfig()
    handlers = {
        "preflight": lambda: run_remote(
            cfg,
            "set -eu; printf 'vm='; virsh domstate PnS-BlissOS-PoC; printf 'worker='; docker ps --filter name=^%s$ --format '{{.Names}}' || true; printf 'listeners='; ss -ltn | grep -E ':(5037|5042|5555)\\b' || true; test -f /mnt/cache/domains/PnS-BlissOS-PoC/rollback/20260711-rt017-runtime-backup/system.qcow2 && echo backup=intact"
            % re.escape(cfg.container),
        ),
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
        "preserve-evidence": lambda: preserve_evidence(
            cfg, args.destination, args.name
        ),
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
