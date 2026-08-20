#!/usr/bin/env python3
"""Reproducible operator interface for local BlueStacks development.

Only this checked-in interface owns the routine worker, private ADB, validation, evidence, and
cleanup commands for the local BlueStacks development runtime.
"""

from __future__ import annotations

import argparse
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
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
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from scripts.bluestacks_adb_readiness import (  # noqa: E402
    ADBReadinessError,
    ensure_adb_ready,
)
from scripts.evidence_hygiene import sha256_stream  # noqa: E402

PACKAGE = "com.global.ztmslg"
NAVIGATION_ASSET_ROOT = "tasks/assets/navigation/800x1280"
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
BLUESTACKS_ADB = Path(r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe")
BLUESTACKS_SERIAL = "emulator-5554"
BLUESTACKS_NATIVE_WIDTH = 800
BLUESTACKS_NATIVE_HEIGHT = 1280
BLUESTACKS_ARTIFACT_ROOT = REPO_ROOT / ".local-captures" / "flow-delivery"
DEVELOPMENT_SESSION_ROOT = REPO_ROOT / ".local-captures" / "development-sessions"
RESOURCE_PRIMARY_LOGIN_SLOT_VERSION = "primary-login-slot-v1"
RESOURCE_IDENTITY_RECEIPT_FILENAME = "resource-identity-receipt.json"
RESOURCE_IDENTITY_RECEIPT_KIND = "resource_identity_observation"
RESOURCE_IDENTITY_RECEIPT_VERSION = 2
RESOURCE_IDENTITY_PRODUCER_KIND = "pnsctl-resource-identity-observation"
RESOURCE_IDENTITY_PRODUCER_VERSION = "pnsctl-resource-identity-observation-v2"
RESOURCE_IDENTITY_PRODUCER_OWNER = "pnsctl-resource-identity-observation"
RESOURCE_IDENTITY_VALIDITY_SECONDS = 600
RESOURCE_IDENTITY_RECURRENCE_SECONDS = 24 * 60 * 60
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
NOVA_SUPERVISED_PULSE_MAX_INPUTS = 8
NOVA_SUPERVISED_PRAISE_MAX_INPUTS = 1
NOVA_SUPERVISED_PULSE_OUTPUT_DEFAULT = (
    BLUESTACKS_ARTIFACT_ROOT / NOVA_SUPERVISED_PULSE_FLOW_ID
)
NOVA_SUPERVISED_ACTION_DATABASE = (
    REPO_ROOT / ".local-orchestrator" / "bluestacks-actions.sqlite3"
)
NOVA_SUPERVISED_GUARD_ARCHIVE_DIR = REPO_ROOT / ".local-orchestrator" / "nova-supervised-guard-archive"
NOVA_SUPERVISED_GUARD_RECEIPT_DIR = REPO_ROOT / ".local-orchestrator" / "nova-supervised-guard-receipts"
FLOW_DELIVERY_QUEUE = REPO_ROOT / "tasks" / "flow_delivery_queue.json"
FLOW_DELIVERY_LEASE = REPO_ROOT / ".local-orchestrator" / "flow-delivery-lease.json"
FLOW_DELIVERY_BLUESTACKS_REGISTRY = (
    REPO_ROOT / "tasks" / "flow_delivery_bluestacks_registry.json"
)
BLUESTACKS_FLOW_IDS = (
    "AUTONOMY-SERVICE-CAMPAIGN-NAVIGATION-PROVING-SLICE",
    "BIOENHANCER-FREE-RESEARCH-BLUESTACKS-INTEGRATION",
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
    "SUPPLY-DEPOT-BLUESTACKS-INTEGRATION",
    "SUPPLY-DEPOT-LEGACY-ADAPTER-RETIREMENT",
    "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
    "DAILY-MILESTONE-CLAIM-BLUESTACKS-INTEGRATION",
    "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION",
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
    try:
        from scripts.flow_delivery_nova_praise_bluestacks import (
            register as register_nova_praise,
        )
    except ImportError:
        from flow_delivery_nova_praise_bluestacks import (
            register as register_nova_praise,
        )
    try:
        from scripts.flow_delivery_bioenhancer_bluestacks import (
            register as register_bioenhancer,
        )
    except ImportError:
        from flow_delivery_bioenhancer_bluestacks import (
            register as register_bioenhancer,
        )
    try:
        from scripts.flow_delivery_daily_row_claim_bluestacks import (
            register as register_daily_row_claim,
        )
    except ImportError:
        from flow_delivery_daily_row_claim_bluestacks import (
            register as register_daily_row_claim,
        )
    try:
        from scripts.flow_delivery_supply_depot_bluestacks import (
            register as register_supply_depot,
        )
    except ImportError:
        from flow_delivery_supply_depot_bluestacks import (
            register as register_supply_depot,
        )
    try:
        from scripts.flow_delivery_daily_resource_item_bluestacks import (
            register as register_daily_resource_item,
        )
    except ImportError:
        from flow_delivery_daily_resource_item_bluestacks import (
            register as register_daily_resource_item,
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
    register_nova_praise(
        _BLUESTACKS_FLOW_RUNNERS,
        _BLUESTACKS_EVIDENCE_VALIDATORS,
        _BLUESTACKS_RECOVERY_HANDLERS,
    )
    register_bioenhancer(
        _BLUESTACKS_FLOW_RUNNERS,
        _BLUESTACKS_EVIDENCE_VALIDATORS,
        _BLUESTACKS_RECOVERY_HANDLERS,
    )
    register_daily_row_claim(
        _BLUESTACKS_FLOW_RUNNERS,
        _BLUESTACKS_EVIDENCE_VALIDATORS,
        _BLUESTACKS_RECOVERY_HANDLERS,
    )
    register_supply_depot(
        _BLUESTACKS_FLOW_RUNNERS,
        _BLUESTACKS_EVIDENCE_VALIDATORS,
        _BLUESTACKS_RECOVERY_HANDLERS,
    )
    register_daily_resource_item(
        _BLUESTACKS_FLOW_RUNNERS,
        _BLUESTACKS_EVIDENCE_VALIDATORS,
        _BLUESTACKS_RECOVERY_HANDLERS,
    )


_register_checked_in_bluestacks_handlers()


class OperatorError(RuntimeError):
    pass


def _resource_fixed_runtime_binding():
    """Derive Resource's fixed slot identity from checked-in runtime constants."""

    from scripts.daily_row_claim_bluestacks import BLUESTACKS_RUNTIME_PROFILE_ID
    from tasks.runtime_identity import derive_fixed_runtime_binding

    return derive_fixed_runtime_binding(
        serial=BLUESTACKS_SERIAL,
        runtime_profile_id=BLUESTACKS_RUNTIME_PROFILE_ID,
        package_id=PACKAGE,
        login_slot_version=RESOURCE_PRIMARY_LOGIN_SLOT_VERSION,
    )


_NOVA_RESET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _validate_nova_reset_id(reset_id: object) -> str:
    """Validate a reset identity before using it as a filesystem component."""

    if not isinstance(reset_id, str):
        raise OperatorError("Nova reset_id must be a string")
    value = reset_id.strip()
    if (
        value != reset_id
        or value in {".", ".."}
        or not _NOVA_RESET_ID_RE.fullmatch(value)
    ):
        raise OperatorError("Nova reset_id contains unsafe path characters")
    return value


def _nova_supervised_guard_path(reset_id: object) -> Path:
    """Return the immutable-reset-scoped active guard path."""

    selected_reset = _validate_nova_reset_id(reset_id)
    configured_root = REPO_ROOT / ".local-orchestrator"
    if os.path.islink(configured_root):
        raise OperatorError("Nova supervised guard root must not be a symlink")
    orchestrator = configured_root.resolve()
    path = orchestrator / (
        f"nova-praise-one-free-pulse-{selected_reset}.guard.json"
    )
    if path.parent != orchestrator or os.path.islink(path):
        raise OperatorError("Nova supervised guard path is unsafe")
    return path


def _nova_supervised_guard_archive_dir() -> Path:
    configured = Path(NOVA_SUPERVISED_GUARD_ARCHIVE_DIR)
    if os.path.islink(configured):
        raise OperatorError("Nova supervised guard archive must not be a symlink")
    configured_root = configured.parent.resolve()
    repo_root = (REPO_ROOT / ".local-orchestrator").resolve()
    archive = (
        configured
        if configured_root == repo_root
        else REPO_ROOT / ".local-orchestrator" / "nova-supervised-guard-archive"
    ).resolve()
    if archive.exists() and os.path.islink(archive):
        raise OperatorError("Nova supervised guard archive must not be a symlink")
    return archive


def _nova_supervised_guard_receipt_dir() -> Path:
    configured = Path(NOVA_SUPERVISED_GUARD_RECEIPT_DIR)
    if os.path.islink(configured):
        raise OperatorError("Nova supervised guard receipt directory is unsafe")
    configured_root = configured.parent.resolve()
    repo_root = (REPO_ROOT / ".local-orchestrator").resolve()
    receipt = (
        configured
        if configured_root == repo_root
        else REPO_ROOT / ".local-orchestrator" / "nova-supervised-guard-receipts"
    ).resolve()
    if receipt.exists() and os.path.islink(receipt):
        raise OperatorError("Nova supervised guard receipt directory is unsafe")
    return receipt


def _infer_single_nova_reset_id() -> str:
    """Compatibility for retained offline guard fixtures; live callers pass it explicitly."""

    root = (REPO_ROOT / ".local-orchestrator").resolve()
    candidates = sorted(root.glob("nova-praise-one-free-pulse-*.guard.json"))
    if len(candidates) != 1:
        raise OperatorError("Nova guard reset_id is required when multiple guards exist")
    payload_path = candidates[0]
    match = re.fullmatch(
        r"nova-praise-one-free-pulse-(?P<reset>[A-Za-z0-9][A-Za-z0-9_.-]{0,127})\.guard\.json",
        payload_path.name,
    )
    if match is None:
        raise OperatorError("Nova guard path does not contain a valid reset_id")
    selected = _validate_nova_reset_id(match.group("reset"))
    if _nova_supervised_guard_path(selected) != payload_path:
        raise OperatorError("Nova guard path/reset binding is invalid")
    return selected


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
            "PNS-FLOW-DELIVERY",
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


def _read_delegated_observation_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise OperatorError(f"delegated observation {label} is unavailable or unsafe")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperatorError(f"delegated observation {label} is unreadable") from exc
    if not isinstance(payload, dict):
        raise OperatorError(f"delegated observation {label} must be an object")
    return payload


def _delegated_observation_ownership_released(session: Any | None) -> bool:
    lock = getattr(getattr(session, "_ownership", None), "lock", None)
    return lock is not None and not bool(getattr(lock, "held", True))


def _delegated_observation_failure_payload(
    result: Mapping[str, Any],
    *,
    receipt: Mapping[str, Any],
    result_identity: str,
    error: str,
    ownership_released: bool,
) -> dict[str, Any]:
    return {
        **dict(result),
        "status": "evidence_required",
        "receipt_id": receipt["receipt_id"],
        "receipt_digest": receipt["receipt_digest"],
        "evidence_result_identity": result_identity,
        "input_count": 0,
        "dispatch": False,
        "ownership_released": ownership_released,
        "error": error,
    }


def _write_delegated_observation_failure(
    session_directory: Path,
    *,
    result: Mapping[str, Any],
    receipt: Mapping[str, Any],
    result_identity: str,
    error: str,
    ownership_released: bool,
) -> dict[str, Any]:
    failure = _delegated_observation_failure_payload(
        result,
        receipt=receipt,
        result_identity=result_identity,
        error=error,
        ownership_released=ownership_released,
    )
    session_directory.mkdir(parents=True, exist_ok=True)
    (session_directory / "result.json").write_text(
        json.dumps(failure, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {
        "status": "evidence_required",
        "receipt_id": receipt["receipt_id"],
        "receipt_digest": receipt["receipt_digest"],
        "evidence_result_identity": result_identity,
        "input_count": 0,
        "action_count": 0,
        "dispatch": False,
        "ownership_released": ownership_released,
        "lifecycle_state_created": False,
        "blocker": error,
        "next_action": "repair the reported delegated observation failure",
    }
    summary_path = session_directory / "summary.json"
    if summary_path.is_file() and not summary_path.is_symlink():
        try:
            prior = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            prior = {}
        if isinstance(prior, dict):
            summary = {**prior, **summary}
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return failure


def _validate_delegated_observation_artifacts(
    session_directory: Path,
    *,
    receipt: Mapping[str, Any],
    result_identity: str,
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    frame_path = session_directory / "observe.png"
    if frame_path.is_symlink() or not frame_path.is_file():
        raise OperatorError("delegated observation frame is unavailable or unsafe")
    try:
        frame_hash = hashlib.sha256(frame_path.read_bytes()).hexdigest()
    except (OSError, UnicodeError) as exc:
        raise OperatorError("delegated observation frame is unreadable") from exc
    declared_hash = observation.get("frame_sha256")
    if not isinstance(declared_hash, str) or frame_hash != declared_hash:
        raise OperatorError("delegated observation frame hash mismatch")

    result = _read_delegated_observation_json(
        session_directory / "result.json",
        "result.json",
    )
    summary = _read_delegated_observation_json(
        session_directory / "summary.json",
        "summary.json",
    )
    expected_bindings = {
        "receipt_id": receipt["receipt_id"],
        "receipt_digest": receipt["receipt_digest"],
        "evidence_result_identity": result_identity,
    }
    for label, payload in (("result.json", result), ("summary.json", summary)):
        for field, expected in expected_bindings.items():
            if payload.get(field) != expected:
                raise OperatorError(
                    f"delegated observation {label} {field} binding mismatch"
                )
        if payload.get("status") != "observed":
            raise OperatorError(f"delegated observation {label} status is not observed")
        if payload.get("input_count") != 0:
            raise OperatorError(f"delegated observation {label} input count is not zero")
        if payload.get("dispatch") is not False:
            raise OperatorError(f"delegated observation {label} dispatch is not false")
        if payload.get("ownership_released") is not True:
            raise OperatorError(
                f"delegated observation {label} ownership release is unproven"
            )
    if result.get("runtime_access") is not True:
        raise OperatorError("delegated observation result runtime access is unproven")
    if result.get("observation") != dict(observation):
        raise OperatorError("delegated observation result observation binding mismatch")
    if result.get("observation", {}).get("frame_sha256") != frame_hash:
        raise OperatorError("delegated observation result frame hash mismatch")
    if summary.get("action_count") != 0:
        raise OperatorError("delegated observation summary contains actions")
    return result


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


DAILY_ROW_RECON_TASK_ID = "daily-row-claim"
DAILY_ROW_RECON_FLOW_ID = "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION"
DAILY_ROW_RECON_SCENARIO = "selected-daily-row-evidence"
DAILY_ROW_RECON_VARIANT = "home-quest-daily"
DAILY_ROW_RECON_CONTINUATION_VARIANT = "quest-daily-continuation"
DAILY_ROW_RECON_RESULT_IDENTITY = (
    "daily-row-claim:reconnaissance:selected-daily-row-evidence"
)
DAILY_ROW_RECON_ACTION_IDENTITIES = ("home-quest-entry", "quest-daily-tab")
DAILY_ROW_RECON_ACTION_CLASSES = ("navigation", "navigation")
DAILY_ROW_RECON_CONTINUATION_ACTION_IDENTITIES = ("quest-daily-tab",)
DAILY_ROW_RECON_CONTINUATION_ACTION_CLASSES = ("navigation",)


def _daily_row_recon_variant_spec(variant: str) -> Mapping[str, Any]:
    if variant == DAILY_ROW_RECON_VARIANT:
        return {
            "max_inputs": 2,
            "action_identities": DAILY_ROW_RECON_ACTION_IDENTITIES,
            "action_classes": DAILY_ROW_RECON_ACTION_CLASSES,
        }
    if variant == DAILY_ROW_RECON_CONTINUATION_VARIANT:
        return {
            "max_inputs": 1,
            "action_identities": DAILY_ROW_RECON_CONTINUATION_ACTION_IDENTITIES,
            "action_classes": DAILY_ROW_RECON_CONTINUATION_ACTION_CLASSES,
        }
    raise OperatorError("daily row reconnaissance variant is not frozen")


def _validate_daily_row_recon_receipt(receipt: Mapping[str, Any]) -> None:
    variant = receipt.get("variant")
    spec = _daily_row_recon_variant_spec(str(variant))
    expected = {
        "receipt_class": "reconnaissance",
        "task_id": DAILY_ROW_RECON_TASK_ID,
        "flow_id": DAILY_ROW_RECON_FLOW_ID,
        "scenario": DAILY_ROW_RECON_SCENARIO,
        "variant": variant,
        "consequence_class": "navigation_only",
        "max_total_inputs": spec["max_inputs"],
        "max_resource_affecting_inputs": 0,
        "max_combat_confirmations": 0,
        "permitted_action_identities": list(spec["action_identities"]),
        "permitted_action_classes": list(spec["action_classes"]),
        "permitted_terminal_states": ["observed", "evidence_required"],
    }
    for field, value in expected.items():
        if field == "permitted_terminal_states":
            if set(receipt.get(field, ())) != set(value):
                raise OperatorError(
                    f"daily row reconnaissance receipt {field} is not frozen"
                )
            continue
        if receipt.get(field) != value:
            raise OperatorError(f"daily row reconnaissance receipt {field} is not frozen")
    expected_bindings = [
        {
            "action_identity": identity,
            "action_class": action_class,
            "consequence_class": "navigation_only",
            "resource_affecting": False,
            "combat_confirmation": False,
        }
        for identity, action_class in zip(
            spec["action_identities"], spec["action_classes"]
        )
    ]
    if receipt.get("action_bindings") != expected_bindings:
        raise OperatorError("daily row reconnaissance receipt action bindings are not frozen")
    binding = receipt.get("evidence_result_binding")
    if not isinstance(binding, Mapping) or binding.get("result_identity") != DAILY_ROW_RECON_RESULT_IDENTITY:
        raise OperatorError("daily row reconnaissance result identity is not frozen")
    command = receipt.get("command_argv")
    if (
        not isinstance(command, list)
        or len(command) != 16
        or command[:3] != [
            "development-session",
            "daily-row-reconnaissance",
            "--max-inputs",
        ]
        or command[3] != str(spec["max_inputs"])
        or command[4] != "--delegated-receipt"
        or not isinstance(command[5], str)
        or not command[5]
        or command[6] != "--agent-identity"
        or not isinstance(command[7], str)
        or not command[7]
        or command[8:10] != ["--task-id", DAILY_ROW_RECON_TASK_ID]
        or command[10:12] != ["--flow-id", DAILY_ROW_RECON_FLOW_ID]
        or command[12:14] != ["--scenario", DAILY_ROW_RECON_SCENARIO]
        or command[14:16] != ["--variant", str(variant)]
    ):
        raise OperatorError("daily row reconnaissance command shape is not frozen")


def _daily_recon_artifact_path(session_directory: Path, value: object) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise OperatorError("daily row reconnaissance artifact path is missing")
    candidate = Path(value)
    resolved = (candidate if candidate.is_absolute() else session_directory / candidate).resolve()
    try:
        resolved.relative_to(session_directory.resolve())
    except ValueError as exc:
        raise OperatorError("daily row reconnaissance artifact escaped its session") from exc
    if resolved.is_symlink() or not resolved.is_file():
        raise OperatorError("daily row reconnaissance artifact is missing or unsafe")
    return resolved


def _validate_daily_recon_artifacts(
    session_directory: Path,
    payload: Mapping[str, Any],
) -> None:
    from scripts.bluestacks_native_runtime import captured_native_frame_from_png

    variant = str(payload.get("variant"))
    spec = _daily_row_recon_variant_spec(variant)
    required_frames = (
        {
            "source",
            "home_immediate_before",
            "quest_successor",
            "daily_immediate_before",
            "daily_terminal",
        }
        if variant == DAILY_ROW_RECON_VARIANT
        else {"source", "daily_immediate_before", "daily_terminal"}
    )
    frames = payload.get("frames")
    if not isinstance(frames, Mapping) or not required_frames <= set(frames):
        raise OperatorError("daily row reconnaissance required native frames are missing")

    def validate_frame(name: str, reference: object) -> None:
        if not isinstance(reference, Mapping):
            raise OperatorError(f"daily row reconnaissance frame reference is malformed: {name}")
        path = _daily_recon_artifact_path(session_directory, reference.get("path"))
        declared_hash = reference.get("sha256")
        if not isinstance(declared_hash, str):
            raise OperatorError(f"daily row reconnaissance frame hash is missing: {name}")
        raw = path.read_bytes()
        actual_hash = hashlib.sha256(raw).hexdigest()
        if actual_hash != declared_hash:
            raise OperatorError(f"daily row reconnaissance frame hash mismatch: {name}")
        captured_native_frame_from_png(
            raw,
            captured_monotonic=float(reference.get("captured_monotonic", 0.0)),
            path=path,
        )

    for name, reference in frames.items():
        validate_frame(str(name), reference)
    polls = payload.get("polls")
    if not isinstance(polls, list):
        raise OperatorError("daily row reconnaissance polling evidence is missing")
    for index, poll in enumerate(polls):
        if not isinstance(poll, Mapping):
            raise OperatorError(f"daily row reconnaissance poll is malformed: {index}")
        if poll.get("action_identity") not in spec["action_identities"]:
            raise OperatorError("daily row reconnaissance poll action identity is invalid")
        if not isinstance(poll.get("recognition"), Mapping):
            raise OperatorError("daily row reconnaissance poll semantics are missing")
        validate_frame(
            f"poll-{index}",
            poll.get("frame"),
        )

    actions = payload.get("actions")
    if not isinstance(actions, list) or len(actions) != spec["max_inputs"]:
        raise OperatorError("daily row reconnaissance action count is not frozen")
    if [
        (row.get("action_key") or row.get("label"))
        for row in actions
        if isinstance(row, Mapping)
    ] != list(spec["action_identities"]):
        raise OperatorError("daily row reconnaissance action identity order is invalid")
    if any(
        not isinstance(row, Mapping)
        or row.get("status") != "completed"
        or row.get("requested_action") != "navigation"
        for row in actions
    ):
        raise OperatorError("daily row reconnaissance action records are not completed navigation")
    if payload.get("input_count") != spec["max_inputs"]:
        raise OperatorError("daily row reconnaissance input count is not frozen")
    if payload.get("resource_affecting_inputs") != 0 or payload.get("combat_confirmations") != 0:
        raise OperatorError("daily row reconnaissance contains a forbidden budget")
    terminal = payload.get("recognitions", {}).get("daily_terminal")
    if not isinstance(terminal, Mapping) or terminal.get("state") != "DAILY_SELECTED":
        raise OperatorError("daily row reconnaissance terminal semantics are not selected Daily")
    source = payload.get("recognitions", {}).get("source")
    expected_source = "HOME" if variant == DAILY_ROW_RECON_VARIANT else "QUEST"
    if not isinstance(source, Mapping) or source.get("state") != expected_source:
        raise OperatorError("daily row reconnaissance source semantics are not variant-bound")
    events_path = _daily_recon_artifact_path(
        session_directory,
        payload.get("runtime_events_path"),
    )
    event_rows = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    dispatches = [row for row in event_rows if row.get("type") == "dispatch"]
    if len(dispatches) != spec["max_inputs"]:
        raise OperatorError("daily row reconnaissance event log dispatch count is not frozen")
    if [
        row.get("action_key") or row.get("target_identity")
        for row in dispatches
    ] != list(spec["action_identities"]):
        raise OperatorError("daily row reconnaissance event action identity order is invalid")


def _write_daily_recon_artifacts(
    session_directory: Path,
    payload: Mapping[str, Any],
    *,
    ownership_released: bool,
) -> None:
    session_directory.mkdir(parents=True, exist_ok=True)
    result = dict(payload)
    result["ownership_released"] = ownership_released
    (session_directory / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    summary = {
        "status": result.get("status"),
        "receipt_id": result.get("receipt_id"),
        "receipt_digest": result.get("receipt_digest"),
        "evidence_result_identity": result.get("evidence_result_identity"),
        "input_count": result.get("input_count", 0),
        "action_count": len(result.get("actions", []))
        if isinstance(result.get("actions"), list)
        else 0,
        "dispatch": result.get("input_count", 0) > 0,
        "resource_affecting_inputs": result.get("resource_affecting_inputs", 0),
        "combat_confirmations": result.get("combat_confirmations", 0),
        "ownership_released": ownership_released,
        "lifecycle_state_created": False,
    }
    frame_records = result.get("frames")
    if isinstance(frame_records, Mapping):
        summary["frame_sha256"] = {
            name: reference.get("sha256")
            for name, reference in frame_records.items()
            if isinstance(reference, Mapping)
        }
    if result.get("popup_identity"):
        summary["popup_identity"] = result.get("popup_identity")
    if result.get("action_identity"):
        summary["action_identity"] = result.get("action_identity")
    if result.get("successor"):
        summary["successor"] = result.get("successor")
    if result.get("reason"):
        summary["blocker"] = result["reason"]
    (session_directory / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def development_session_daily_row_reconnaissance(
    *,
    max_inputs: int,
    delegated_receipt: Path,
    agent_identity: str,
    task_id: str,
    flow_id: str,
    scenario: str,
    variant: str,
    command_argv: Sequence[str] | None = None,
) -> str:
    """Run one frozen bounded Daily reconnaissance route variant."""

    expected_bindings = (
        max_inputs,
        task_id,
        flow_id,
        scenario,
        variant,
        agent_identity,
        command_argv,
    )
    spec = _daily_row_recon_variant_spec(variant)
    if max_inputs != spec["max_inputs"]:
        raise OperatorError(
            f"daily row reconnaissance requires --max-inputs {spec['max_inputs']}"
        )
    if any(value is None for value in expected_bindings[1:]):
        raise OperatorError("daily row reconnaissance requires complete receipt bindings")
    if task_id != DAILY_ROW_RECON_TASK_ID or flow_id != DAILY_ROW_RECON_FLOW_ID:
        raise OperatorError("daily row reconnaissance task or flow binding is not frozen")
    if scenario != DAILY_ROW_RECON_SCENARIO:
        raise OperatorError("daily row reconnaissance scenario is not frozen")
    if command_argv is None:
        raise OperatorError("daily row reconnaissance command binding is required")

    from scripts.daily_row_claim_bluestacks import (
        run_daily_row_reconnaissance,
        run_quest_daily_continuation,
    )
    from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
    from scripts.navigation_development_boundary import (
        DevelopmentSession,
        delegated_runtime_context,
    )
    from scripts.flow_delivery_control import DelegatedRuntimeReceiptController

    # Inspect before consumption so an incorrectly scoped receipt remains issued.
    inspected = DelegatedRuntimeReceiptController(delegated_receipt).inspect()
    _validate_daily_row_recon_receipt(inspected["receipt"])
    _controller, receipt, context = _consume_delegated_receipt(
        delegated_receipt,
        command_argv=command_argv,
        agent_identity=agent_identity,
        task_id=task_id,
        flow_id=flow_id,
        receipt_class="reconnaissance",
        scenario=scenario,
        variant=variant,
        max_inputs=spec["max_inputs"],
    )
    _validate_daily_row_recon_receipt(receipt)

    invocation_id = f"delegated-{receipt['receipt_id']}"
    session_directory = _development_session_directory(invocation_id)
    checkpoint_before = _checkpoint_hashes()
    session: Any | None = None
    runtime: Any | None = None
    route_result: dict[str, Any] | None = None
    terminal_recorded = False

    def base_payload(status: str, reason: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": status,
            "task_id": task_id,
            "flow_id": flow_id,
            "scenario": scenario,
            "variant": variant,
            "receipt_id": receipt["receipt_id"],
            "receipt_digest": receipt["receipt_digest"],
            "evidence_result_identity": context.result_identity,
            "session_directory": str(session_directory),
            "input_count": int(getattr(session, "input_count", 0)),
            "resource_affecting_inputs": 0,
            "combat_confirmations": 0,
            "dispatch": int(getattr(session, "input_count", 0)) > 0,
            "ownership_released": False,
        }
        if reason:
            payload["reason"] = reason
        if route_result:
            payload.update(route_result)
            payload.update(
                {
                    "status": status,
                    "task_id": task_id,
                    "flow_id": flow_id,
                    "scenario": scenario,
                    "variant": variant,
                    "receipt_id": receipt["receipt_id"],
                    "receipt_digest": receipt["receipt_digest"],
                    "evidence_result_identity": context.result_identity,
                    "session_directory": str(session_directory),
                }
            )
        if runtime is not None:
            runtime_session = Path(runtime.session)
            try:
                runtime_relative = runtime_session.resolve().relative_to(
                    session_directory.resolve()
                )
                payload["runtime_session_directory"] = str(runtime_relative).replace("\\", "/")
            except (OSError, ValueError):
                payload["runtime_session_directory"] = str(runtime_session)
            payload["runtime_events_path"] = str(
                Path(payload["runtime_session_directory"]) / "events.jsonl"
            )
            payload["runtime_input_count"] = int(getattr(runtime, "input_count", 0))
        return payload

    try:
        with delegated_runtime_context(context):
            with DevelopmentSession(
                owner=f"pnsctl-delegated-daily-row-recon:{flow_id}",
                invocation_id=invocation_id,
                session_directory=session_directory,
                max_inputs=spec["max_inputs"],
            ) as active_session:
                session = active_session
                runtime = LocalBlueStacksRuntime.connect(
                    adb=str(BLUESTACKS_ADB),
                    serial=BLUESTACKS_SERIAL,
                    output_directory=session_directory / "runtime",
                    workflow="daily-row-reconnaissance",
                    execute=True,
                )
                route = (
                    run_daily_row_reconnaissance
                    if variant == DAILY_ROW_RECON_VARIANT
                    else run_quest_daily_continuation
                )
                route_result = route(runtime, active_session)
                active_session.terminal_status = route_result.get(
                    "status", "evidence_required"
                )

        ownership_released = _delegated_observation_ownership_released(session)
        if not ownership_released:
            raise OperatorError("daily row reconnaissance ownership release is unproven")
        checkpoint_after = _checkpoint_hashes()
        if checkpoint_after != checkpoint_before:
            route_result = {
                **(route_result or {}),
                "status": "evidence_required",
                "reason": "daily row reconnaissance mutated a checkpoint artifact",
            }
        status = str((route_result or {}).get("status") or "evidence_required")
        payload = base_payload(status)
        payload["ownership_released"] = True
        _write_daily_recon_artifacts(
            session_directory,
            payload,
            ownership_released=True,
        )
        if status == "observed":
            _validate_daily_recon_artifacts(session_directory, payload)
        context.record_terminal(status=status, payload=payload)
        terminal_recorded = True
        return json.dumps(payload, sort_keys=True, default=str)
    except BaseException as exc:
        ownership_released = _delegated_observation_ownership_released(session)
        failure = base_payload(
            "evidence_required",
            f"{type(exc).__name__}: {exc}",
        )
        failure["ownership_released"] = ownership_released
        if not terminal_recorded:
            context.record_terminal(status="evidence_required", payload=failure)
            terminal_recorded = True
        try:
            _write_daily_recon_artifacts(
                session_directory,
                failure,
                ownership_released=ownership_released,
            )
        except BaseException as artifact_error:
            raise exc.with_traceback(exc.__traceback__) from artifact_error
        raise exc.with_traceback(exc.__traceback__)


DAILY_ROW_CLAIM_TASK_ID = "daily-row-claim"
DAILY_ROW_CLAIM_FLOW_ID = "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION"
DAILY_ROW_CLAIM_SCENARIO = "selected-daily-aggregate-claim"
DAILY_ROW_CLAIM_PREPARE_VARIANT = "aggregate-claim-prepare"
DAILY_ROW_CLAIM_CANARY_VARIANT = "aggregate-claim-canary"
DAILY_ROW_CLAIM_RETURN_HOME_VARIANT = "aggregate-claim-return-home"
DAILY_ROW_CLAIM_DISMISS_VIP_VARIANT = "aggregate-claim-dismiss-vip"
DAILY_ROW_CLAIM_PREPARE_RESULT_IDENTITY = "daily-claim:prepare:aggregate"
DAILY_ROW_CLAIM_CANARY_RESULT_IDENTITY = "daily-claim:canary:aggregate"
DAILY_ROW_CLAIM_RETURN_HOME_RESULT_IDENTITY = "daily-claim:return-home:verified"
DAILY_ROW_CLAIM_DISMISS_VIP_RESULT_IDENTITY = (
    "daily-row-claim:popup-dismiss:vip-points"
)
DAILY_ROW_CLAIM_PREPARE_ACTION_IDENTITY = "daily-row-prepare-observation"
DAILY_ROW_CLAIM_ACTION_IDENTITY = "daily-claim:aggregate"
DAILY_ROW_CLAIM_RETURN_HOME_ACTION_IDENTITY = "daily-return-home"
DAILY_ROW_CLAIM_DISMISS_VIP_ACTION_IDENTITY = "reset-popup-close"


def _daily_row_claim_spec(mode: str) -> Mapping[str, Any]:
    if mode == "prepare":
        return {
            "mode": mode,
            "receipt_class": "reconnaissance",
            "max_inputs": 0,
            "variant": DAILY_ROW_CLAIM_PREPARE_VARIANT,
            "scenario": DAILY_ROW_CLAIM_SCENARIO,
            "action_identities": (DAILY_ROW_CLAIM_PREPARE_ACTION_IDENTITY,),
            "action_classes": ("observation",),
            "consequence_class": "navigation_only",
            "result_identity": DAILY_ROW_CLAIM_PREPARE_RESULT_IDENTITY,
            "terminal_states": ("observed", "evidence_required"),
        }
    if mode == "canary":
        return {
            "mode": mode,
            "receipt_class": "canary",
            "max_inputs": 2,
            "variant": DAILY_ROW_CLAIM_CANARY_VARIANT,
            "scenario": DAILY_ROW_CLAIM_SCENARIO,
            "action_identities": (
                DAILY_ROW_CLAIM_ACTION_IDENTITY,
                DAILY_ROW_CLAIM_RETURN_HOME_ACTION_IDENTITY,
            ),
            "action_classes": ("reward_claim", "navigation"),
            "consequence_class": "ordinary_development",
            "result_identity": DAILY_ROW_CLAIM_CANARY_RESULT_IDENTITY,
            "terminal_states": ("completed", "evidence_required"),
        }
    if mode == "return-home":
        return {
            "mode": mode,
            "receipt_class": "reconnaissance",
            "max_inputs": 1,
            "variant": DAILY_ROW_CLAIM_RETURN_HOME_VARIANT,
            "scenario": DAILY_ROW_CLAIM_SCENARIO,
            "action_identities": (DAILY_ROW_CLAIM_RETURN_HOME_ACTION_IDENTITY,),
            "action_classes": ("navigation",),
            "consequence_class": "navigation_only",
            "result_identity": DAILY_ROW_CLAIM_RETURN_HOME_RESULT_IDENTITY,
            "terminal_states": ("observed", "evidence_required"),
        }
    if mode == "dismiss-vip-popup":
        return {
            "mode": mode,
            "receipt_class": "reconnaissance",
            "max_inputs": 1,
            "variant": DAILY_ROW_CLAIM_DISMISS_VIP_VARIANT,
            "scenario": DAILY_ROW_CLAIM_SCENARIO,
            "action_identities": (DAILY_ROW_CLAIM_DISMISS_VIP_ACTION_IDENTITY,),
            "action_classes": ("navigation",),
            "consequence_class": "navigation_only",
            "result_identity": DAILY_ROW_CLAIM_DISMISS_VIP_RESULT_IDENTITY,
            "terminal_states": ("observed", "evidence_required"),
        }
    raise OperatorError("daily row Claim mode is unsupported")


def _validate_daily_row_claim_receipt(
    receipt: Mapping[str, Any],
    *,
    mode: str,
) -> None:
    spec = _daily_row_claim_spec(mode)
    expected = {
        "receipt_class": spec["receipt_class"],
        "task_id": DAILY_ROW_CLAIM_TASK_ID,
        "flow_id": DAILY_ROW_CLAIM_FLOW_ID,
        "scenario": spec["scenario"],
        "variant": spec["variant"],
        "consequence_class": spec["consequence_class"],
        "max_total_inputs": spec["max_inputs"],
        "max_resource_affecting_inputs": 0,
        "max_combat_confirmations": 0,
        "permitted_action_identities": list(spec["action_identities"]),
        "permitted_action_classes": list(spec["action_classes"]),
        "permitted_terminal_states": list(spec["terminal_states"]),
    }
    for field, value in expected.items():
        actual = receipt.get(field)
        if field == "permitted_terminal_states":
            if set(actual or ()) != set(value):
                raise OperatorError(f"daily row Claim receipt {field} is not frozen")
        elif actual != value:
            raise OperatorError(f"daily row Claim receipt {field} is not frozen")
    expected_bindings = [
        {
            "action_identity": identity,
            "action_class": action_class,
            "consequence_class": spec["consequence_class"],
            "resource_affecting": False,
            "combat_confirmation": False,
        }
        for identity, action_class in zip(
            spec["action_identities"], spec["action_classes"]
        )
    ]
    if receipt.get("action_bindings") != expected_bindings:
        raise OperatorError("daily row Claim receipt action bindings are not frozen")
    binding = receipt.get("evidence_result_binding")
    if not isinstance(binding, Mapping) or binding.get("result_identity") != spec["result_identity"]:
        raise OperatorError("daily row Claim result identity is not frozen")
    command = receipt.get("command_argv")
    expected_prefix = [
        "development-session",
        "daily-row-claim",
        "--mode",
        mode,
        "--max-inputs",
        str(spec["max_inputs"]),
    ]
    if (
        not isinstance(command, list)
        or len(command) != 18
        or command[:6] != expected_prefix
        or command[6] != "--delegated-receipt"
        or not isinstance(command[7], str)
        or not command[7]
        or command[8] != "--agent-identity"
        or not isinstance(command[9], str)
        or not command[9]
        or command[10:12] != ["--task-id", DAILY_ROW_CLAIM_TASK_ID]
        or command[12:14] != ["--flow-id", DAILY_ROW_CLAIM_FLOW_ID]
        or command[14:16] != ["--scenario", spec["scenario"]]
        or command[16:18] != ["--variant", spec["variant"]]
    ):
        raise OperatorError("daily row Claim command shape is not frozen")


def _write_daily_row_claim_artifacts(
    session_directory: Path,
    payload: Mapping[str, Any],
    *,
    ownership_released: bool,
) -> None:
    session_directory.mkdir(parents=True, exist_ok=True)
    result = {**dict(payload), "ownership_released": ownership_released}
    (session_directory / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    actions = result.get("actions")
    summary = {
        "status": result.get("status"),
        "receipt_id": result.get("receipt_id"),
        "receipt_digest": result.get("receipt_digest"),
        "evidence_result_identity": result.get("evidence_result_identity"),
        "input_count": result.get("input_count", 0),
        "action_count": len(actions) if isinstance(actions, list) else 0,
        "dispatch": bool(result.get("input_count", 0)),
        "ownership_released": ownership_released,
        "lifecycle_state_created": False,
    }
    claim = result.get("claim")
    if isinstance(claim, Mapping):
        for reset_field in (
            "reset_timer",
            "reset_timer_seconds",
            "reset_observed_utc",
            "reset_deadline_utc",
            "reset_deadline_identity",
            "reset_deadline_tolerance_seconds",
        ):
            if reset_field in claim:
                summary[reset_field] = claim[reset_field]
    ready_row = result.get("ready_row")
    if isinstance(ready_row, Mapping):
        summary["ready_row"] = {
            field: ready_row.get(field)
            for field in (
                "objective_key",
                "objective_name",
                "current_progress",
                "required_progress",
                "reward",
                "row_bounds",
                "claim_roi",
                "claim_authority",
            )
        }
    if result.get("final_annotation"):
        summary["final_annotation"] = result.get("final_annotation")
    if result.get("swipe_identities"):
        summary["swipe_identities"] = result.get("swipe_identities")
    if result.get("reason"):
        summary["blocker"] = result["reason"]
    (session_directory / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _daily_row_claim_artifact_path(
    session_directory: Path,
    value: object,
    *,
    label: str,
) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise OperatorError(f"Daily row Claim {label} path is missing")
    candidate = Path(value)
    resolved = (
        candidate if candidate.is_absolute() else session_directory / candidate
    ).resolve()
    try:
        resolved.relative_to(session_directory.resolve())
    except ValueError as exc:
        raise OperatorError(f"Daily row Claim {label} escaped the session") from exc
    if resolved.is_symlink() or not resolved.is_file():
        raise OperatorError(f"Daily row Claim {label} is missing or unsafe")
    return resolved


def _validate_daily_row_claim_artifacts(
    session_directory: Path,
    payload: Mapping[str, Any],
    *,
    mode: str,
) -> None:
    from scripts.bluestacks_native_runtime import captured_native_frame_from_png

    def template_home_proven(recognition: object) -> bool:
        if not isinstance(recognition, Mapping):
            return False
        visual = recognition.get("visual_evidence")
        if not isinstance(visual, Mapping):
            return False
        template = visual.get("template_home")
        return (
            isinstance(template, Mapping)
            and template.get("recognized") is True
        )

    frames = payload.get("frames")
    if not isinstance(frames, Mapping) or "source" not in frames:
        raise OperatorError("Daily row Claim source frame is missing")
    for name, reference in frames.items():
        if not isinstance(reference, Mapping):
            raise OperatorError(f"Daily row Claim frame reference is malformed: {name}")
        path_value = reference.get("path")
        if not isinstance(path_value, str):
            raise OperatorError(f"Daily row Claim frame path is missing: {name}")
        path = (session_directory / path_value).resolve()
        try:
            path.relative_to(session_directory.resolve())
        except ValueError as exc:
            raise OperatorError("Daily row Claim frame escaped the session") from exc
        if path.is_symlink() or not path.is_file():
            raise OperatorError(f"Daily row Claim frame is missing or unsafe: {name}")
        raw = path.read_bytes()
        declared = reference.get("sha256")
        if hashlib.sha256(raw).hexdigest() != declared:
            raise OperatorError(f"Daily row Claim frame hash mismatch: {name}")
        captured_native_frame_from_png(
            raw,
            captured_monotonic=float(reference.get("captured_monotonic", 0.0)),
            path=path,
        )
    if mode == "prepare":
        claim = payload.get("claim")
        if not isinstance(claim, Mapping) or not claim.get("annotated_source"):
            raise OperatorError("Daily row Claim annotated prepare overlay is missing")
        required_reset_fields = (
            "reset_timer",
            "reset_timer_seconds",
            "reset_observed_utc",
            "reset_deadline_utc",
            "reset_deadline_identity",
            "reset_deadline_tolerance_seconds",
        )
        if any(claim.get(field) is None for field in required_reset_fields):
            raise OperatorError("Daily row Claim reset deadline evidence is missing")
        annotated = (session_directory / str(claim["annotated_source"])).resolve()
        if annotated.is_symlink() or not annotated.is_file() or annotated.stat().st_size == 0:
            raise OperatorError("Daily row Claim annotated prepare overlay is unsafe")
    elif mode == "canary":
        actions = payload.get("actions")
        if not isinstance(actions, list) or len(actions) != 2:
            raise OperatorError("Daily row Claim canary action count is not two")
        if payload.get("input_count") != 2:
            raise OperatorError("Daily row Claim canary input count is not two")
        required_frames = {
            "immediate_before",
            "immediate_post",
            "return_home_source",
            "return_home_immediate_before",
            "return_home_immediate_post",
            "return_home_final",
        }
        if not required_frames <= set(frames):
            raise OperatorError("Daily row Claim canary immediate evidence is missing")
        expected_actions = [
            ("daily-claim:aggregate", "reward_claim"),
            ("daily-return-home", "navigation"),
        ]
        if [
            (
                row.get("action_key") or row.get("label"),
                row.get("requested_action"),
            )
            for row in actions
            if isinstance(row, Mapping)
        ] != expected_actions:
            raise OperatorError("Daily row Claim canary action identity order is invalid")
        if any(
            not isinstance(row, Mapping) or row.get("status") != "completed"
            for row in actions
        ):
            raise OperatorError("Daily row Claim canary action records are not completed")
        claim = payload.get("claim")
        if not isinstance(claim, Mapping) or not claim.get("annotated_immediate_before"):
            raise OperatorError("Daily row Claim annotated immediate-before overlay is missing")
        required_reset_fields = (
            "reset_timer",
            "reset_timer_seconds",
            "reset_observed_utc",
            "reset_deadline_utc",
            "reset_deadline_identity",
            "reset_deadline_tolerance_seconds",
        )
        if any(claim.get(field) is None for field in required_reset_fields):
            raise OperatorError("Daily row Claim reset deadline evidence is missing")
        annotated = (session_directory / str(claim["annotated_immediate_before"])).resolve()
        try:
            annotated.relative_to(session_directory.resolve())
        except ValueError as exc:
            raise OperatorError("Daily row Claim annotated overlay escaped the session") from exc
        if annotated.is_symlink() or not annotated.is_file() or annotated.stat().st_size == 0:
            raise OperatorError("Daily row Claim annotated immediate-before overlay is unsafe")
        recognitions = payload.get("recognitions")
        if not isinstance(recognitions, Mapping):
            raise OperatorError("Daily row Claim recognitions are missing")
        for name in ("return_home_source", "return_home_immediate_before"):
            recognition = recognitions.get(name)
            if (
                not isinstance(recognition, Mapping)
                or recognition.get("state") != "DAILY_SELECTED"
                or recognition.get("successor_proven") is not True
            ):
                raise OperatorError(
                    f"Daily row Claim {name} is not selected Daily"
                )
        final_home = recognitions.get("return_home_final")
        if (
            not isinstance(final_home, Mapping)
            or final_home.get("state") != "HOME"
            or final_home.get("recognized") is not True
            or not template_home_proven(final_home)
        ):
            raise OperatorError("Daily row Claim final Home is not recognized")
        home = payload.get("home")
        if not isinstance(home, Mapping) or home.get("verified") is not True:
            raise OperatorError("Daily row Claim final Home evidence is missing")
    elif mode == "return-home":
        actions = payload.get("actions")
        if not isinstance(actions, list) or len(actions) != 1:
            raise OperatorError("Daily return-home action count is not one")
        if payload.get("input_count") != 1:
            raise OperatorError("Daily return-home input count is not one")
        if (
            payload.get("resource_affecting_inputs") != 0
            or payload.get("combat_confirmations") != 0
        ):
            raise OperatorError("Daily return-home contains a forbidden budget")
        if (
            payload.get("action_identity") != "daily-return-home"
            or payload.get("action_class") != "navigation"
            or payload.get("consequence_class") != "navigation_only"
        ):
            raise OperatorError("Daily return-home action binding is not frozen")
        action = actions[0]
        if (
            not isinstance(action, Mapping)
            or action.get("requested_action") != "navigation"
            or action.get("label") != "daily-return-home"
            or action.get("status") != "completed"
        ):
            raise OperatorError("Daily return-home action record is not frozen")
        required_frames = {
            "source",
            "return_home_immediate_before",
            "return_home_immediate_post",
            "return_home_final",
        }
        if not required_frames <= set(frames):
            raise OperatorError("Daily return-home evidence is missing")
        recognitions = payload.get("recognitions")
        if not isinstance(recognitions, Mapping):
            raise OperatorError("Daily return-home recognitions are missing")
        for name in ("source", "return_home_immediate_before"):
            recognition = recognitions.get(name)
            if (
                not isinstance(recognition, Mapping)
                or recognition.get("state") != "DAILY_SELECTED"
                or recognition.get("successor_proven") is not True
            ):
                raise OperatorError(
                    f"Daily return-home {name} is not selected Daily"
                )
        final_home = recognitions.get("return_home_final")
        if (
            not isinstance(final_home, Mapping)
            or final_home.get("state") != "HOME"
            or final_home.get("recognized") is not True
            or not template_home_proven(final_home)
        ):
            raise OperatorError("Daily return-home final Home is not recognized")
        home = payload.get("home")
        if not isinstance(home, Mapping) or home.get("verified") is not True:
            raise OperatorError("Daily return-home final Home evidence is missing")
    elif mode == "dismiss-vip-popup":
        actions = payload.get("actions")
        if not isinstance(actions, list) or len(actions) != 1:
            raise OperatorError("Daily VIP popup action count is not one")
        if payload.get("input_count") != 1:
            raise OperatorError("Daily VIP popup input count is not one")
        if (
            payload.get("resource_affecting_inputs") != 0
            or payload.get("combat_confirmations") != 0
        ):
            raise OperatorError("Daily VIP popup contains a forbidden budget")
        if payload.get("action_identity") != "reset-popup-close":
            raise OperatorError("Daily VIP popup action identity is not frozen")
        if payload.get("action_class") != "navigation":
            raise OperatorError("Daily VIP popup action class is not frozen")
        if payload.get("consequence_class") != "navigation_only":
            raise OperatorError("Daily VIP popup consequence is not frozen")
        action = actions[0]
        if (
            not isinstance(action, Mapping)
            or action.get("requested_action") != "navigation"
            or action.get("label") != "reset-popup-close"
            or action.get("status") != "completed"
        ):
            raise OperatorError("Daily VIP popup action record is not frozen")
        for name in ("source", "immediate_before", "immediate_post"):
            if name not in frames:
                raise OperatorError(f"Daily VIP popup {name} evidence is missing")
        popup_records = payload.get("popup_recognitions")
        if not isinstance(popup_records, Mapping):
            raise OperatorError("Daily VIP popup recognitions are missing")
        required_semantics = {
            "get pts",
            "log in every day to get vip pts",
            "close",
            "spatially associated close control",
        }
        for name in ("source", "immediate_before"):
            popup = popup_records.get(name)
            frame = frames.get(name)
            if not isinstance(popup, Mapping) or not isinstance(frame, Mapping):
                raise OperatorError(f"Daily VIP popup {name} recognition is missing")
            if (
                popup.get("status") != "allowed"
                or popup.get("popup_identity") != "VIP_POINTS_GET_PTS"
                or popup.get("target_identity") != "reset-popup-close"
                or popup.get("source_frame_sha256") != frame.get("sha256")
                or not required_semantics.issubset(
                    {
                        str(value).casefold().replace("_", " ")
                        for value in popup.get("semantic_evidence", ())
                    }
                )
            ):
                raise OperatorError(
                    f"Daily VIP popup {name} exact identity or hash is not frozen"
                )
            target_roi = popup.get("target_roi")
            if (
                not isinstance(target_roi, (list, tuple))
                or len(target_roi) != 4
                or not (
                    0 <= int(target_roi[0]) < int(target_roi[2]) <= 800
                    and 0 <= int(target_roi[1]) < int(target_roi[3]) <= 1280
                )
            ):
                raise OperatorError(f"Daily VIP popup {name} target ROI is unsafe")
        polls = payload.get("polls")
        if not isinstance(polls, list) or not polls:
            raise OperatorError("Daily VIP popup polls are missing")
        successor = payload.get("successor")
        if (
            not isinstance(successor, Mapping)
            or successor.get("state") != "DAILY_SELECTED"
            or successor.get("popup_absent") is not True
            or successor.get("unblurred") is not True
        ):
            raise OperatorError("Daily VIP popup successor is not selected Daily")
def development_session_daily_row_claim(
    *,
    mode: str,
    max_inputs: int,
    delegated_receipt: Path,
    agent_identity: str,
    task_id: str,
    flow_id: str,
    scenario: str,
    variant: str,
    command_argv: Sequence[str] | None = None,
) -> str:
    """Run the receipt-bound Daily prepare, Claim, or VIP popup continuation."""

    spec = _daily_row_claim_spec(mode)
    if max_inputs != spec["max_inputs"]:
        raise OperatorError(
            f"daily row Claim {mode} requires --max-inputs {spec['max_inputs']}"
        )
    if (
        task_id != DAILY_ROW_CLAIM_TASK_ID
        or flow_id != DAILY_ROW_CLAIM_FLOW_ID
        or scenario != spec["scenario"]
        or variant != spec["variant"]
        or command_argv is None
    ):
        raise OperatorError("daily row Claim bindings are not frozen")

    from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
    from scripts.daily_row_claim_bluestacks import (
        run_daily_row_claim_vip_popup_dismissal,
        run_daily_row_claim_canary,
        run_daily_row_claim_prepare,
        run_daily_row_claim_return_home,
    )
    from scripts.flow_delivery_control import DelegatedRuntimeReceiptController
    from scripts.navigation_development_boundary import (
        DevelopmentSession,
        delegated_runtime_context,
    )

    inspected = DelegatedRuntimeReceiptController(delegated_receipt).inspect()
    _validate_daily_row_claim_receipt(inspected["receipt"], mode=mode)
    _controller, receipt, context = _consume_delegated_receipt(
        delegated_receipt,
        command_argv=command_argv,
        agent_identity=agent_identity,
        task_id=task_id,
        flow_id=flow_id,
        receipt_class=spec["receipt_class"],
        scenario=scenario,
        variant=variant,
        max_inputs=spec["max_inputs"],
    )
    _validate_daily_row_claim_receipt(receipt, mode=mode)

    invocation_id = f"delegated-{receipt['receipt_id']}"
    session_directory = _development_session_directory(invocation_id)
    session: Any | None = None
    runtime: Any | None = None
    route_result: dict[str, Any] | None = None
    terminal_recorded = False
    checkpoint_before = _checkpoint_hashes()
    # Daily reset authority is bound from the displayed in-game countdown
    # after the source frame is captured.  A host date is not a game-day
    # identity and must never authorize this flow.
    game_day_id: str | None = None
    reset_identity: str | None = None
    previous_limit = os.environ.get("PNS_DEVELOPMENT_MAX_INPUTS")

    def base_payload(status: str, reason: str | None = None) -> dict[str, Any]:
        nonlocal game_day_id, reset_identity
        payload: dict[str, Any] = {
            "status": status,
            "mode": mode,
            "task_id": task_id,
            "flow_id": flow_id,
            "scenario": scenario,
            "variant": variant,
            "receipt_id": receipt["receipt_id"],
            "receipt_digest": receipt["receipt_digest"],
            "evidence_result_identity": context.result_identity,
            "session_directory": str(session_directory),
            "input_count": int(getattr(session, "input_count", 0)),
            "resource_affecting_inputs": 0,
            "combat_confirmations": 0,
            "dispatch": int(getattr(session, "input_count", 0)) > 0,
            "ownership_released": False,
            "game_day_id": game_day_id,
            "reset_identity": reset_identity,
        }
        if reason:
            payload["reason"] = reason
        if route_result:
            bound_identity = route_result.get("game_day_id")
            if isinstance(bound_identity, str) and bound_identity:
                game_day_id = bound_identity
                reset_identity = bound_identity
            payload.update(route_result)
            payload.update(
                {
                    "status": status,
                    "mode": mode,
                    "task_id": task_id,
                    "flow_id": flow_id,
                    "scenario": scenario,
                    "variant": variant,
                    "receipt_id": receipt["receipt_id"],
                    "receipt_digest": receipt["receipt_digest"],
                    "evidence_result_identity": context.result_identity,
                    "session_directory": str(session_directory),
                    "game_day_id": game_day_id,
                    "reset_identity": reset_identity,
                }
            )
        if runtime is not None:
            runtime_session = Path(runtime.session)
            try:
                relative = runtime_session.resolve().relative_to(session_directory.resolve())
                runtime_relative = str(relative).replace("\\", "/")
            except (OSError, ValueError):
                runtime_relative = str(runtime_session)
            payload["runtime_session_directory"] = runtime_relative
            payload["runtime_events_path"] = f"{runtime_relative}/events.jsonl"
        return payload

    try:
        # LocalBlueStacksRuntime uses a positive internal input ceiling even
        # during the zero-input prepare session; DevelopmentSession remains the
        # authoritative zero-input boundary.
        os.environ["PNS_DEVELOPMENT_MAX_INPUTS"] = str(max(1, spec["max_inputs"]))
        with delegated_runtime_context(context):
            with DevelopmentSession(
                owner=f"pnsctl-delegated-daily-row-claim:{mode}",
                invocation_id=invocation_id,
                session_directory=session_directory,
                max_inputs=spec["max_inputs"],
                allow_zero_inputs=mode == "prepare",
            ) as active_session:
                session = active_session
                runtime = LocalBlueStacksRuntime.connect(
                    adb=str(BLUESTACKS_ADB),
                    serial=BLUESTACKS_SERIAL,
                    output_directory=session_directory / "runtime",
                    workflow="daily-row-claim",
                    execute=True,
                )
                route_result = (
                    run_daily_row_claim_prepare(
                        runtime,
                        active_session,
                        game_day_id=game_day_id,
                    )
                    if mode == "prepare"
                    else run_daily_row_claim_canary(
                        runtime,
                        active_session,
                        game_day_id=game_day_id,
                    )
                    if mode == "canary"
                    else run_daily_row_claim_return_home(
                        runtime,
                        active_session,
                    )
                    if mode == "return-home"
                    else run_daily_row_claim_vip_popup_dismissal(
                        runtime,
                        active_session,
                    )
                )
                active_session.terminal_status = route_result.get(
                    "status", "evidence_required"
                )
        if previous_limit is None:
            os.environ.pop("PNS_DEVELOPMENT_MAX_INPUTS", None)
        else:
            os.environ["PNS_DEVELOPMENT_MAX_INPUTS"] = previous_limit
        if session is None or session._ownership.lock.held:
            raise OperatorError("Daily row Claim ownership release is unproven")
        if _checkpoint_hashes() != checkpoint_before:
            route_result = {
                **(route_result or {}),
                "status": "evidence_required",
                "reason": "Daily Claim mutated a checkpoint artifact",
            }
        status = str((route_result or {}).get("status") or "evidence_required")
        payload = base_payload(status)
        payload["ownership_released"] = True
        _write_daily_row_claim_artifacts(
            session_directory,
            payload,
            ownership_released=True,
        )
        if status in {"observed", "completed"}:
            _validate_daily_row_claim_artifacts(
                session_directory,
                payload,
                mode=mode,
            )
        context.record_terminal(status=status, payload=payload)
        terminal_recorded = True
        return json.dumps(payload, sort_keys=True, default=str)
    except BaseException as exc:
        if previous_limit is None:
            os.environ.pop("PNS_DEVELOPMENT_MAX_INPUTS", None)
        else:
            os.environ["PNS_DEVELOPMENT_MAX_INPUTS"] = previous_limit
        ownership_released = not bool(
            getattr(getattr(getattr(session, "_ownership", None), "lock", None), "held", True)
        )
        failure = base_payload(
            "evidence_required",
            f"{type(exc).__name__}: {exc}",
        )
        failure["ownership_released"] = ownership_released
        if not terminal_recorded:
            # Durable controller terminal evidence must be recorded before
            # fallible JSON/artifact persistence.
            context.record_terminal(status="evidence_required", payload=failure)
            terminal_recorded = True
        _write_daily_row_claim_artifacts(
            session_directory,
            failure,
            ownership_released=ownership_released,
        )
        raise


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
            "ownership_released": False,
        }
        session: Any | None = None
        observation: Mapping[str, Any] | None = None
        terminal_recorded = False
        try:
            with delegated_runtime_context(context):
                with DevelopmentSession(
                    owner=f"pnsctl-delegated-observe:{flow_id}",
                    invocation_id=invocation_id,
                    session_directory=session_directory,
                    max_inputs=0,
                    allow_zero_inputs=True,
                ) as active_session:
                    session = active_session
                    observation, frame = _development_runtime_observation()
                    (session_directory / "observe.png").write_bytes(frame)
                    result.update({"status": "observed", "observation": observation})
                    session.terminal_status = "observed"
                    (session_directory / "result.json").write_text(
                        json.dumps(result, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
            ownership_released = _delegated_observation_ownership_released(session)
            if not ownership_released:
                raise OperatorError("delegated observation ownership release is unproven")
            if _checkpoint_hashes() != before:
                raise OperatorError("delegated observation mutated a checkpoint artifact")
            result["ownership_released"] = True
            (session_directory / "result.json").write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            summary = _read_delegated_observation_json(
                session_directory / "summary.json",
                "summary.json",
            )
            summary.update(
                {
                    "status": "observed",
                    "receipt_id": receipt["receipt_id"],
                    "receipt_digest": receipt["receipt_digest"],
                    "evidence_result_identity": context.result_identity,
                    "input_count": 0,
                    "dispatch": False,
                    "ownership_released": True,
                }
            )
            (session_directory / "summary.json").write_text(
                json.dumps(summary, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            persisted_result = _validate_delegated_observation_artifacts(
                session_directory,
                receipt=receipt,
                result_identity=context.result_identity,
                observation=observation or {},
            )
            context.record_terminal(status="observed", payload=persisted_result)
            terminal_recorded = True
        except BaseException as exc:
            failure = _delegated_observation_failure_payload(
                result,
                receipt=receipt,
                result_identity=context.result_identity,
                error=f"{type(exc).__name__}: {exc}",
                ownership_released=_delegated_observation_ownership_released(session),
            )
            if not terminal_recorded:
                context.record_terminal(status="evidence_required", payload=failure)
            try:
                _write_delegated_observation_failure(
                    session_directory,
                    result=result,
                    receipt=receipt,
                    result_identity=context.result_identity,
                    error=f"{type(exc).__name__}: {exc}",
                    ownership_released=_delegated_observation_ownership_released(session),
                )
            except BaseException as artifact_error:
                raise exc from artifact_error
            raise
        return json.dumps(persisted_result, sort_keys=True)
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


def _resource_identity_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise OperatorError(f"{label} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise OperatorError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise OperatorError(f"{label} must be UTC")
    parsed = parsed.astimezone(timezone.utc)
    canonical = parsed.isoformat().replace("+00:00", "Z")
    if value != canonical:
        raise OperatorError(f"{label} is not an exact UTC timestamp")
    return parsed


def _resource_identity_receipt_digest(payload: Mapping[str, Any]) -> str:
    unsigned = dict(payload)
    unsigned.pop("receipt_digest", None)
    encoded = json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _remove_resource_identity_receipt(path: Path) -> None:
    try:
        if path.is_symlink() or not path.exists():
            return
        path.unlink()
    except OSError:
        # A failed cleanup is still fail-closed because the consumer requires
        # the observed summary and receipt to agree.
        pass


def development_session_resource_identity_observe() -> str:
    """Capture the fixed runtime binding and selected-Daily reset with zero input."""

    import cv2
    import numpy as np

    from scripts import daily_row_claim_bluestacks as daily
    from scripts.navigation_development_boundary import DevelopmentSession
    from tasks.runtime_identity import (
        ResourceIdentityEvidence,
        RESOURCE_IDENTITY_MIN_RESET_REMAINING_SECONDS,
        RuntimeIdentityConfiguration,
        produce_resource_runtime_identity,
    )

    binding = _resource_fixed_runtime_binding()

    invocation_id = (
        f"resource-identity-observe-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    )
    session_directory = _development_session_directory(invocation_id)
    receipt_path = session_directory / RESOURCE_IDENTITY_RECEIPT_FILENAME
    checkpoint_before = _checkpoint_hashes()
    result: dict[str, Any] = {
        "status": "failed",
        "operation": "resource-identity-observe",
        "session_directory": str(session_directory),
        "receipt_path": str(receipt_path),
        "input_count": 0,
        "action_count": 0,
        "max_inputs": 0,
        "dispatch": False,
        "lifecycle_state_created": False,
    }

    try:
        with DevelopmentSession(
            owner=RESOURCE_IDENTITY_PRODUCER_OWNER,
            invocation_id=invocation_id,
            session_directory=session_directory,
            max_inputs=0,
            allow_zero_inputs=True,
        ) as session:
            observation, frame = _development_runtime_observation()
            if not isinstance(observation, Mapping):
                raise OperatorError("Resource identity runtime observation is malformed")
            if observation.get("device_state") != "device":
                raise OperatorError("Resource identity runtime device state is not device")
            if observation.get("foreground_package") != PACKAGE:
                raise OperatorError(
                    "Resource identity runtime package is not Puzzles & Survival"
                )
            if (
                observation.get("native_width") != BLUESTACKS_NATIVE_WIDTH
                or observation.get("native_height") != BLUESTACKS_NATIVE_HEIGHT
            ):
                raise OperatorError("Resource identity runtime is not native 800x1280")
            if (
                not isinstance(frame, bytes)
                or frame[:8] != b"\x89PNG\r\n\x1a\n"
                or len(frame) < 24
            ):
                raise OperatorError("Resource identity source frame is not a valid PNG")
            width = int.from_bytes(frame[16:20], "big")
            height = int.from_bytes(frame[20:24], "big")
            if (width, height) != (
                BLUESTACKS_NATIVE_WIDTH,
                BLUESTACKS_NATIVE_HEIGHT,
            ):
                raise OperatorError("Resource identity source frame is not native 800x1280")
            frame_digest = hashlib.sha256(frame).hexdigest()
            if observation.get("frame_sha256") != frame_digest:
                raise OperatorError("Resource identity source frame hash is not runtime-bound")

            source_path = session_directory / "source.png"
            source_path.write_bytes(frame)
            encoded = np.frombuffer(frame, dtype=np.uint8)
            image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
            if image is None or tuple(image.shape[:2]) != (
                BLUESTACKS_NATIVE_HEIGHT,
                BLUESTACKS_NATIVE_WIDTH,
            ):
                raise OperatorError("Resource identity source frame cannot be decoded natively")

            observed = datetime.now(timezone.utc).replace(microsecond=0)
            observed_utc = observed.isoformat().replace("+00:00", "Z")
            recognition = daily.DailyRowClaimRecognizer().recognize_daily_claim(
                image,
                game_day_id=None,
                observed_utc=observed,
            )
            visual = recognition.visual_evidence
            if not isinstance(visual, Mapping):
                raise OperatorError("Resource Daily recognizer evidence is missing")
            overlay = visual.get("full_frame_overlay")
            if isinstance(overlay, Mapping) and overlay.get("recognized") is True:
                raise OperatorError("Resource identity is blocked by an unknown modal")
            if (
                not recognition.recognized
                or recognition.state != daily.DAILY_SELECTED_STATE
                or visual.get("selected_daily") is not True
                or visual.get("runtime_profile_id") != daily.BLUESTACKS_RUNTIME_PROFILE_ID
            ):
                raise OperatorError(
                    "Resource identity requires positively recognized selected Daily"
                )

            derived_identity = visual.get("reset_deadline_identity")
            derived_deadline = visual.get("reset_deadline_utc")
            derived_observed = visual.get("reset_observed_utc")
            timer_seconds = visual.get("reset_timer_seconds")
            if (
                not isinstance(derived_identity, str)
                or not isinstance(derived_deadline, str)
                or not isinstance(derived_observed, str)
                or not isinstance(timer_seconds, int)
                or isinstance(timer_seconds, bool)
                or timer_seconds <= 0
            ):
                raise OperatorError(
                    "Resource identity reset deadline is not a valid selected-Daily observation"
                )
            derived_observed_dt = _resource_identity_timestamp(
                derived_observed,
                "Resource recognizer reset observation",
            )
            derived_deadline_dt = _resource_identity_timestamp(
                derived_deadline,
                "Resource recognizer reset deadline",
            )
            if derived_observed_dt != observed or derived_observed != observed_utc:
                raise OperatorError(
                    "Resource recognizer reset observation is not bound to capture time"
                )
            if derived_deadline_dt != derived_observed_dt + timedelta(seconds=timer_seconds):
                raise OperatorError(
                    "Resource recognizer reset deadline is not timer-derived"
                )
            if derived_identity != f"reset-deadline:{derived_deadline}":
                raise OperatorError(
                    "Resource recognizer reset identity is not bound to its deadline"
                )
            if (
                derived_deadline_dt - observed
            ).total_seconds() <= RESOURCE_IDENTITY_MIN_RESET_REMAINING_SECONDS:
                raise OperatorError(
                    "Resource identity reset deadline is expired or too close to observation"
                )
            configuration = RuntimeIdentityConfiguration(
                binding.runtime_scope,
                binding.account_id,
                binding.server_id,
                derived_identity,
            )

            expires = min(
                observed + timedelta(seconds=RESOURCE_IDENTITY_VALIDITY_SECONDS),
                derived_deadline_dt,
            )
            expires_utc = expires.isoformat().replace("+00:00", "Z")
            frame_ref = {
                "path": "source.png",
                "session_relative_path": "source.png",
                "sha256": frame_digest,
                "captured_utc": observed_utc,
                "observed_utc": observed_utc,
            }
            evidence_refs = (
                f"producer-kind:{RESOURCE_IDENTITY_PRODUCER_KIND}",
                f"producer-version:{RESOURCE_IDENTITY_PRODUCER_VERSION}",
                f"producer-owner:{RESOURCE_IDENTITY_PRODUCER_OWNER}",
                f"producer-invocation:{invocation_id}",
                f"producer-session:{invocation_id}",
                "identity-semantics:fixed-runtime-binding-plus-observed-reset",
                f"runtime-binding-kind:{binding.as_dict()['kind']}",
                f"runtime-binding-digest:{binding.binding_digest}",
                f"runtime-scope:{binding.runtime_scope}",
                f"fixed-runtime-serial:{binding.serial}",
                f"fixed-runtime-profile:{binding.runtime_profile_id}",
                f"fixed-runtime-package:{binding.package_id}",
                f"fixed-login-slot-version:{binding.login_slot_version}",
                "reset-observed:selected-daily-native-frame",
                "recognizer:DailyRowClaimRecognizer",
                "frame-path:source.png",
                f"frame-sha256:{frame_digest}",
            )
            deadline_payload: dict[str, Any] = {
                "displayed_timer": visual.get("reset_timer"),
                "reset_timer_seconds": timer_seconds,
                "observed_utc": observed_utc,
                "reset_observed_utc": derived_observed,
                "normalized_deadline_utc": derived_deadline,
                "reset_deadline_utc": derived_deadline,
                "deadline_identity": derived_identity,
                "reset_deadline_identity": derived_identity,
                "tolerance_seconds": visual.get(
                    "reset_deadline_tolerance_seconds"
                ),
                "recurrence_class": "daily_reset",
                "recurrence_interval_seconds": RESOURCE_IDENTITY_RECURRENCE_SECONDS,
                "daily_recurrence_seconds": RESOURCE_IDENTITY_RECURRENCE_SECONDS,
                "recurrence_interval_hours": 24,
                "machine_observed": True,
                "daily_frame": frame_ref,
            }
            if deadline_payload["tolerance_seconds"] is None:
                deadline_payload["tolerance_seconds"] = 0
            if (
                type(deadline_payload["tolerance_seconds"]) is not int
                or deadline_payload["tolerance_seconds"] < 0
            ):
                raise OperatorError("Resource reset deadline tolerance is invalid")

            provisional_evidence = ResourceIdentityEvidence(
                account_id=binding.account_id,
                server_id=binding.server_id,
                reset_id=configuration.reset_id,
                evidence_refs=evidence_refs,
                observed_utc=observed_utc,
                expires_utc=expires_utc,
                content_digest="0" * 64,
                runtime_scope=binding.runtime_scope,
                runtime_binding_digest=binding.binding_digest,
            )
            evidence = ResourceIdentityEvidence(
                account_id=provisional_evidence.account_id,
                server_id=provisional_evidence.server_id,
                reset_id=provisional_evidence.reset_id,
                evidence_refs=provisional_evidence.evidence_refs,
                observed_utc=provisional_evidence.observed_utc,
                expires_utc=provisional_evidence.expires_utc,
                content_digest=provisional_evidence.computed_digest(),
                runtime_scope=provisional_evidence.runtime_scope,
                runtime_binding_digest=provisional_evidence.runtime_binding_digest,
            )
            verified = produce_resource_runtime_identity(
                configuration,
                evidence,
                deadline_payload,
                observed,
                binding,
            )
            if _checkpoint_hashes() != checkpoint_before:
                raise OperatorError(
                    "Resource identity observation mutated a persistent checkpoint artifact"
                )

            producer = {
                "kind": RESOURCE_IDENTITY_PRODUCER_KIND,
                "version": RESOURCE_IDENTITY_PRODUCER_VERSION,
                "owner": RESOURCE_IDENTITY_PRODUCER_OWNER,
                "invocation_id": invocation_id,
                "session_id": invocation_id,
                "session_directory": invocation_id,
            }
            receipt: dict[str, Any] = {
                "schema_version": RESOURCE_IDENTITY_RECEIPT_VERSION,
                "receipt_kind": RESOURCE_IDENTITY_RECEIPT_KIND,
                "receipt_version": RESOURCE_IDENTITY_RECEIPT_VERSION,
                "producer_kind": RESOURCE_IDENTITY_PRODUCER_KIND,
                "producer_version": RESOURCE_IDENTITY_PRODUCER_VERSION,
                "producer_owner": RESOURCE_IDENTITY_PRODUCER_OWNER,
                "producer_invocation_id": invocation_id,
                "producer_session_id": invocation_id,
                "producer_session_directory": invocation_id,
                "producer": producer,
                "identity_semantics": "fixed_runtime_binding_plus_observed_daily_reset",
                "assurance": verified.assurance.value,
                "runtime_binding": binding.as_dict(),
                "runtime_binding_digest": binding.binding_digest,
                "runtime_scope": binding.runtime_scope,
                "account_id": binding.account_id,
                "server_id": binding.server_id,
                "reset_id": configuration.reset_id,
                "observed_utc": evidence.observed_utc,
                "expires_utc": evidence.expires_utc,
                "frame": frame_ref,
                "reset_deadline": {
                    "identity": derived_identity,
                    "deadline_utc": derived_deadline,
                    "observed_utc": derived_observed,
                    "timer_seconds": timer_seconds,
                },
                "recurrence": {
                    "class": "daily_reset",
                    "interval_seconds": RESOURCE_IDENTITY_RECURRENCE_SECONDS,
                    "interval_hours": 24,
                },
                "evidence_refs": list(evidence.evidence_refs),
                "resource_identity_evidence": {
                    **evidence.as_dict(),
                    "content_digest": evidence.content_digest,
                },
                "current_reset_deadline_evidence": deadline_payload,
                "self_digest": evidence.content_digest,
            }
            receipt["receipt_digest"] = _resource_identity_receipt_digest(receipt)
            if receipt_path.exists() or receipt_path.is_symlink():
                raise OperatorError("Resource identity receipt already exists")
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            session.terminal_status = "observed"
            result.update(
                {
                    "status": "observed",
                    "producer_kind": RESOURCE_IDENTITY_PRODUCER_KIND,
                    "producer_version": RESOURCE_IDENTITY_PRODUCER_VERSION,
                    "owner": RESOURCE_IDENTITY_PRODUCER_OWNER,
                    "invocation_id": invocation_id,
                    "identity_semantics": "fixed_runtime_binding_plus_observed_daily_reset",
                    "assurance": verified.assurance.value,
                    "runtime_binding": binding.as_dict(),
                    "runtime_binding_digest": binding.binding_digest,
                    "runtime_scope": verified.runtime_scope,
                    "account_id": verified.account_id,
                    "server_id": verified.server_id,
                    "reset_id": verified.reset_id,
                    "observed_utc": verified.observed_utc,
                    "expires_utc": verified.expires_utc,
                    "reset_deadline_identity": derived_identity,
                    "reset_deadline_utc": derived_deadline,
                    "frame": frame_ref,
                    "evidence_refs": list(evidence.evidence_refs),
                    "ownership_released": False,
                }
            )
            (session_directory / "result.json").write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        summary_path = session_directory / "summary.json"
        if summary_path.is_symlink() or not summary_path.is_file():
            raise OperatorError("Resource identity producer summary.json was not written")
        summary_digest, summary_size = sha256_stream(summary_path)
        if summary_size <= 0:
            raise OperatorError("Resource identity producer summary.json is empty")
        try:
            persisted_receipt = json.loads(
                receipt_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OperatorError("Resource identity receipt could not be finalized") from exc
        if not isinstance(persisted_receipt, dict):
            raise OperatorError("Resource identity receipt could not be finalized")
        persisted_receipt["summary_sha256"] = summary_digest
        persisted_receipt["receipt_digest"] = _resource_identity_receipt_digest(
            persisted_receipt
        )
        receipt_path.write_text(
            json.dumps(persisted_receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if _checkpoint_hashes() != checkpoint_before:
            raise OperatorError(
                "Resource identity observation mutated a persistent checkpoint artifact"
            )
        result["ownership_released"] = True
        return json.dumps(result, sort_keys=True)
    except BaseException:
        _remove_resource_identity_receipt(receipt_path)
        raise


def _load_resource_identity_payload(
    identity_evidence: Path | None,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """Load and authenticate a receipt from a prior Resource identity session."""

    root = Path(DEVELOPMENT_SESSION_ROOT)
    if root.is_symlink() or not root.is_dir():
        raise OperatorError("Resource identity evidence root is unavailable or unsafe")
    if identity_evidence is None:
        raise OperatorError("Resource production identity evidence is unavailable")
    supplied_path = Path(identity_evidence)
    if any(part == ".." for part in supplied_path.parts):
        raise OperatorError("Resource production identity evidence path contains traversal")
    evidence_path = (
        supplied_path
        if supplied_path.is_absolute()
        else root / supplied_path
    )
    evidence_absolute = Path(os.path.abspath(str(evidence_path)))
    root_absolute = Path(os.path.abspath(str(root)))
    try:
        evidence_absolute.relative_to(root_absolute)
    except ValueError as exc:
        raise OperatorError(
            "Resource production identity evidence must remain beneath the fixed capture root"
        ) from exc
    probe = evidence_absolute.parent
    while probe != root_absolute:
        if probe.is_symlink():
            raise OperatorError(
                "Resource production identity evidence path must not use symlink directories"
            )
        probe = probe.parent
    if evidence_path.is_symlink() or not evidence_path.is_file():
        raise OperatorError(
            "Resource production identity evidence must be a regular non-symlink file"
        )
    if evidence_path.name != RESOURCE_IDENTITY_RECEIPT_FILENAME:
        raise OperatorError(
            "Resource production identity evidence must use the exact receipt filename"
        )
    try:
        root_resolved = root.resolve()
        evidence_resolved = evidence_path.resolve()
        relative = evidence_resolved.relative_to(root_resolved)
    except (OSError, ValueError) as exc:
        raise OperatorError(
            "Resource production identity evidence must remain beneath the fixed capture root"
        ) from exc
    if len(relative.parts) != 2 or relative.parts[-1] != RESOURCE_IDENTITY_RECEIPT_FILENAME:
        raise OperatorError(
            "Resource production identity evidence must be directly inside one session directory"
        )
    probe = root_resolved
    for part in relative.parts[:-1]:
        probe = probe / part
        if probe.is_symlink() or not probe.is_dir():
            raise OperatorError(
                "Resource production identity session must use regular directories"
            )
    identity_session = root_resolved / relative.parts[0]
    if identity_session.is_symlink() or not identity_session.is_dir():
        raise OperatorError("Resource identity session directory is unavailable or unsafe")
    try:
        payload = json.loads(evidence_resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperatorError("Resource production identity evidence is unreadable") from exc
    if not isinstance(payload, Mapping):
        raise OperatorError("Resource production identity evidence must be an object")

    expected_binding = _resource_fixed_runtime_binding()
    receipt_binding = payload.get("runtime_binding")
    if not isinstance(receipt_binding, Mapping) or dict(receipt_binding) != expected_binding.as_dict():
        raise OperatorError(
            "Resource identity receipt fixed serial/profile/package/login-slot binding "
            "does not match current runtime constants"
        )
    if (
        payload.get("identity_semantics")
        != "fixed_runtime_binding_plus_observed_daily_reset"
        or payload.get("assurance") != "fixed_runtime_binding_reset_observed"
        or payload.get("runtime_binding_digest") != expected_binding.binding_digest
        or payload.get("runtime_scope") != expected_binding.runtime_scope
        or payload.get("account_id") != expected_binding.account_id
        or payload.get("server_id") != expected_binding.server_id
    ):
        raise OperatorError("Resource identity receipt fixed runtime binding semantics are invalid")

    if (
        type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != RESOURCE_IDENTITY_RECEIPT_VERSION
    ):
        raise OperatorError("Resource identity receipt schema is unsupported")
    if payload.get("receipt_kind") != RESOURCE_IDENTITY_RECEIPT_KIND:
        raise OperatorError("Resource identity receipt kind is not exact")
    if (
        type(payload.get("receipt_version")) is not int
        or payload.get("receipt_version") != RESOURCE_IDENTITY_RECEIPT_VERSION
    ):
        raise OperatorError("Resource identity receipt version is not exact")

    producer = payload.get("producer")
    if not isinstance(producer, Mapping):
        raise OperatorError("Resource identity receipt producer is missing")
    producer_fields = {
        "kind": RESOURCE_IDENTITY_PRODUCER_KIND,
        "version": RESOURCE_IDENTITY_PRODUCER_VERSION,
        "owner": RESOURCE_IDENTITY_PRODUCER_OWNER,
    }
    for field, expected in producer_fields.items():
        if producer.get(field) != expected:
            raise OperatorError(f"Resource identity producer {field} is not exact")
    if (
        payload.get("producer_kind") != RESOURCE_IDENTITY_PRODUCER_KIND
        or payload.get("producer_version") != RESOURCE_IDENTITY_PRODUCER_VERSION
        or payload.get("producer_owner") != RESOURCE_IDENTITY_PRODUCER_OWNER
    ):
        raise OperatorError("Resource identity receipt producer binding is not exact")

    producer_invocation = producer.get("invocation_id")
    producer_session_id = producer.get("session_id")
    producer_session_directory = producer.get("session_directory")
    if (
        not isinstance(producer_invocation, str)
        or not producer_invocation.startswith("resource-identity-observe-")
        or producer_invocation != payload.get("producer_invocation_id")
        or producer_session_id != producer_invocation
        or producer_session_directory != identity_session.name
        or producer_invocation != identity_session.name
        or payload.get("producer_session_id") != identity_session.name
        or payload.get("producer_session_directory") != identity_session.name
    ):
        raise OperatorError("Resource identity receipt producer session binding is invalid")

    summary_path = identity_session / "summary.json"
    if summary_path.is_symlink() or not summary_path.is_file():
        raise OperatorError("Resource identity producer summary.json is required")
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperatorError("Resource identity producer summary.json is unreadable") from exc
    if not isinstance(summary, Mapping):
        raise OperatorError("Resource identity producer summary.json must be an object")
    if (
        type(summary.get("schema_version")) is not int
        or summary.get("schema_version") != 1
        or summary.get("session_kind") != "ordinary_development"
        or summary.get("owner") != RESOURCE_IDENTITY_PRODUCER_OWNER
        or summary.get("invocation_id") != producer_invocation
        or summary.get("status") != "observed"
        or type(summary.get("input_count")) is not int
        or summary.get("input_count") != 0
        or type(summary.get("action_count")) is not int
        or summary.get("action_count") != 0
        or type(summary.get("max_inputs")) is not int
        or summary.get("max_inputs") != 0
        or summary.get("ownership_released") is not True
        or summary.get("lifecycle_state_created") is not False
    ):
        raise OperatorError("Resource identity producer summary is not an authenticated zero-input observation")
    summary_digest = payload.get("summary_sha256")
    if (
        not isinstance(summary_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", summary_digest.casefold()) is None
    ):
        raise OperatorError("Resource identity producer summary digest is missing")
    try:
        actual_summary_digest, summary_size = sha256_stream(summary_path)
    except OSError as exc:
        raise OperatorError("Resource identity producer summary cannot be hashed") from exc
    if summary_size <= 0 or actual_summary_digest.casefold() != summary_digest.casefold():
        raise OperatorError("Resource identity producer summary digest does not match")

    evidence_payload = payload.get(
        "resource_identity_evidence",
        None,
    )
    deadline_payload = payload.get(
        "current_reset_deadline_evidence",
        None,
    )
    if not isinstance(evidence_payload, Mapping) or not isinstance(deadline_payload, Mapping):
        raise OperatorError(
            "Resource production identity requires current machine-observed reset deadline evidence"
        )
    evidence_payload = dict(evidence_payload)
    deadline_payload = dict(deadline_payload)

    try:
        from tasks.runtime_identity import ResourceIdentityEvidence

        evidence_refs_value = evidence_payload.get("evidence_refs")
        if not isinstance(evidence_refs_value, (list, tuple)) or not evidence_refs_value:
            raise OperatorError("Resource identity receipt evidence references are malformed")
        if any(
            not isinstance(value, str) or not value.strip()
            for value in evidence_refs_value
        ):
            raise OperatorError("Resource identity receipt evidence references are malformed")
        evidence_payload["evidence_refs"] = tuple(evidence_refs_value)
        evidence = ResourceIdentityEvidence(**evidence_payload)
        if evidence.content_digest != evidence.computed_digest():
            raise OperatorError("Resource identity evidence self-digest does not match")
    except (TypeError, ValueError) as exc:
        raise OperatorError("Resource identity evidence semantics are invalid") from exc

    runtime_scope = payload.get("runtime_scope")
    if (
        not isinstance(runtime_scope, str)
        or not runtime_scope.strip()
        or runtime_scope != runtime_scope.strip()
    ):
        raise OperatorError("Resource identity receipt runtime scope is not normalized")
    for field in (
        "account_id",
        "server_id",
        "reset_id",
        "runtime_scope",
        "runtime_binding_digest",
    ):
        expected_value = (
            expected_binding.runtime_scope
            if field == "runtime_scope"
            else expected_binding.binding_digest
            if field == "runtime_binding_digest"
            else payload.get(field)
        )
        if payload.get(field) != evidence_payload.get(field) or (
            field in {"runtime_scope", "runtime_binding_digest"}
            and evidence_payload.get(field) != expected_value
        ):
            raise OperatorError(f"Resource identity receipt {field} binding is invalid")
    if (
        payload.get("observed_utc") != evidence_payload.get("observed_utc")
        or payload.get("expires_utc") != evidence_payload.get("expires_utc")
        or payload.get("self_digest") != evidence_payload.get("content_digest")
    ):
        raise OperatorError("Resource identity receipt freshness or self-digest binding is invalid")
    _resource_identity_timestamp(
        evidence_payload.get("observed_utc"),
        "Resource identity evidence observed_utc",
    )
    _resource_identity_timestamp(
        evidence_payload.get("expires_utc"),
        "Resource identity evidence expires_utc",
    )

    receipt_frame = payload.get("frame")
    deadline_frame = deadline_payload.get("daily_frame")
    if not isinstance(receipt_frame, Mapping) or not isinstance(deadline_frame, Mapping):
        raise OperatorError("Resource identity receipt frame binding is missing")
    for field in ("path", "sha256", "captured_utc", "observed_utc"):
        if receipt_frame.get(field) != deadline_frame.get(field):
            raise OperatorError("Resource identity receipt frame binding is inconsistent")
    session_relative_path = receipt_frame.get("session_relative_path")
    if session_relative_path is not None and session_relative_path != receipt_frame.get(
        "path"
    ):
        raise OperatorError("Resource identity receipt frame path aliases disagree")
    frame_value = receipt_frame.get("path")
    frame_digest = receipt_frame.get("sha256")
    frame_candidate = Path(frame_value) if isinstance(frame_value, str) else None
    if (
        frame_candidate is None
        or not frame_value.strip()
        or frame_candidate.is_absolute()
        or any(part == ".." for part in frame_candidate.parts)
        or not isinstance(frame_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", frame_digest.casefold()) is None
    ):
        raise OperatorError("Resource identity receipt frame is not session-bound")
    lexical_frame = identity_session / frame_candidate
    if lexical_frame.is_symlink():
        raise OperatorError("Resource identity receipt frame must not be a symlink")
    try:
        bound_frame = _session_relative_path(
            identity_session,
            frame_value,
            "Resource identity receipt frame",
        )
        actual_frame_digest, frame_size = sha256_stream(bound_frame)
    except OSError as exc:
        raise OperatorError("Resource identity receipt frame cannot be hashed") from exc
    if frame_size <= 0 or actual_frame_digest.casefold() != frame_digest.casefold():
        raise OperatorError("Resource identity receipt frame hash is not session-bound")
    if (
        deadline_payload.get("recurrence_class") != "daily_reset"
        or deadline_payload.get("machine_observed") is not True
        or type(deadline_payload.get("recurrence_interval_seconds")) is not int
        or deadline_payload.get("recurrence_interval_seconds")
        != RESOURCE_IDENTITY_RECURRENCE_SECONDS
        or type(deadline_payload.get("daily_recurrence_seconds")) is not int
        or deadline_payload.get("daily_recurrence_seconds")
        != RESOURCE_IDENTITY_RECURRENCE_SECONDS
        or type(deadline_payload.get("recurrence_interval_hours")) is not int
        or deadline_payload.get("recurrence_interval_hours") != 24
    ):
        raise OperatorError("Resource identity receipt recurrence is not exactly 24 hours")
    recurrence = payload.get("recurrence")
    if not isinstance(recurrence, Mapping) or (
        recurrence.get("class") != "daily_reset"
        or type(recurrence.get("interval_seconds")) is not int
        or recurrence.get("interval_seconds") != RESOURCE_IDENTITY_RECURRENCE_SECONDS
        or type(recurrence.get("interval_hours")) is not int
        or recurrence.get("interval_hours") != 24
    ):
        raise OperatorError("Resource identity receipt recurrence binding is invalid")
    reset_deadline = payload.get("reset_deadline")
    if not isinstance(reset_deadline, Mapping) or (
        reset_deadline.get("identity")
        != deadline_payload.get("deadline_identity")
        or reset_deadline.get("deadline_utc")
        != deadline_payload.get("normalized_deadline_utc")
        or reset_deadline.get("observed_utc")
        != deadline_payload.get("observed_utc")
        or reset_deadline.get("timer_seconds")
        != deadline_payload.get("reset_timer_seconds")
    ):
        raise OperatorError("Resource identity receipt reset deadline binding is invalid")

    receipt_refs = payload.get("evidence_refs")
    if not isinstance(receipt_refs, list) or receipt_refs != list(
        evidence_payload["evidence_refs"]
    ):
        raise OperatorError("Resource identity receipt evidence references are not bound")
    required_refs = {
        f"producer-kind:{RESOURCE_IDENTITY_PRODUCER_KIND}",
        f"producer-version:{RESOURCE_IDENTITY_PRODUCER_VERSION}",
        f"producer-owner:{RESOURCE_IDENTITY_PRODUCER_OWNER}",
        f"producer-invocation:{producer_invocation}",
        f"producer-session:{identity_session.name}",
        "identity-semantics:fixed-runtime-binding-plus-observed-reset",
        f"runtime-binding-kind:{expected_binding.as_dict()['kind']}",
        f"runtime-binding-digest:{expected_binding.binding_digest}",
        f"runtime-scope:{expected_binding.runtime_scope}",
        f"fixed-runtime-serial:{expected_binding.serial}",
        f"fixed-runtime-profile:{expected_binding.runtime_profile_id}",
        f"fixed-runtime-package:{expected_binding.package_id}",
        f"fixed-login-slot-version:{expected_binding.login_slot_version}",
        "reset-observed:selected-daily-native-frame",
        f"frame-path:{frame_value}",
        f"frame-sha256:{frame_digest.casefold()}",
    }
    if not required_refs.issubset(set(evidence_payload["evidence_refs"])):
        raise OperatorError("Resource identity evidence references are incomplete")
    _resource_identity_timestamp(
        receipt_frame.get("captured_utc"),
        "Resource identity frame captured_utc",
    )
    _resource_identity_timestamp(
        receipt_frame.get("observed_utc"),
        "Resource identity frame observed_utc",
    )
    if _resource_identity_receipt_digest(payload) != payload.get("receipt_digest"):
        raise OperatorError("Resource identity receipt digest does not match its contents")

    # Keep receipt-only bindings private to the loader's returned payload.  The
    # ResourceIdentityEvidence dataclass is constructed from the public fields
    # only, while the consumer can still compare the configured scope before
    # opening any canonical store.
    deadline_payload["_receipt_runtime_scope"] = runtime_scope
    deadline_payload["_receipt_producer_invocation_id"] = producer_invocation
    return evidence_payload, deadline_payload, identity_session


def _resource_deadline_evidence(
    payload: Mapping[str, Any],
) -> tuple[str, datetime]:
    """Validate the exact machine-observed deadline and accepted daily recurrence."""

    deadline_identity = payload.get(
        "deadline_identity",
        payload.get("reset_deadline_identity"),
    )
    normalized = payload.get("normalized_deadline_utc")
    if not isinstance(deadline_identity, str) or not deadline_identity.strip():
        raise OperatorError("Resource reset deadline identity is missing")
    if not isinstance(normalized, str) or not normalized.strip():
        raise OperatorError("Resource normalized reset deadline is missing")
    try:
        deadline = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise OperatorError("Resource normalized reset deadline is invalid") from exc
    if deadline.tzinfo is None:
        raise OperatorError("Resource normalized reset deadline must be UTC")
    deadline = deadline.astimezone(timezone.utc)
    canonical_deadline = deadline.isoformat().replace("+00:00", "Z")
    if normalized != canonical_deadline:
        raise OperatorError("Resource normalized reset deadline is not exact")
    if deadline_identity != f"reset-deadline:{canonical_deadline}":
        raise OperatorError("Resource reset deadline identity is not bound to the normalized deadline")
    recurrence_class = payload.get("recurrence_class", "daily_reset")
    if recurrence_class != "daily_reset":
        raise OperatorError("Resource reset evidence is not the accepted daily recurrence")
    for field, expected in (
        ("recurrence_interval_seconds", 24 * 60 * 60),
        ("daily_recurrence_seconds", 24 * 60 * 60),
    ):
        if field in payload and payload[field] != expected:
            raise OperatorError("Resource recurrence interval is not exactly 24 hours")
    if "recurrence_interval_hours" in payload and payload["recurrence_interval_hours"] != 24:
        raise OperatorError("Resource recurrence interval is not exactly 24 hours")
    observed = payload.get("observed_utc", payload.get("reset_observed_utc"))
    if observed is not None:
        try:
            observed_utc = datetime.fromisoformat(str(observed).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise OperatorError("Resource reset observation timestamp is invalid") from exc
        if observed_utc.tzinfo is None or observed_utc.astimezone(timezone.utc) > deadline:
            raise OperatorError("Resource reset deadline precedes its machine observation")
    return deadline_identity, deadline


def _resource_identity_frame_proof(
    *,
    session: Path,
    evidence_payload: Mapping[str, Any],
    deadline_payload: Mapping[str, Any],
) -> tuple[Path, str, datetime, datetime, Mapping[str, Any]]:
    """Resolve and verify the retained native Daily frame proof.

    JSON is only a transport envelope here.  Production authority comes from
    rerunning the checked-in Daily recognizer against this exact retained
    frame, never from ``machine_observed`` or a caller-computed identity.
    """

    frame_payload: Mapping[str, Any] | None = None
    for candidate in (
        deadline_payload.get("daily_frame"),
        deadline_payload.get("observation_frame"),
        deadline_payload.get("frame"),
        evidence_payload.get("daily_frame"),
        evidence_payload.get("observation_frame"),
        evidence_payload.get("frame"),
    ):
        if isinstance(candidate, Mapping):
            frame_payload = candidate
            break
    if frame_payload is None:
        raise OperatorError("Resource identity requires a hash-bound Daily observation frame")
    path_value = frame_payload.get("path") or frame_payload.get("session_relative_path")
    digest = frame_payload.get("sha256") or frame_payload.get("frame_sha256")
    captured_value = frame_payload.get("captured_utc") or evidence_payload.get("captured_utc")
    observed_value = (
        frame_payload.get("observed_utc")
        or deadline_payload.get("observed_utc")
        or deadline_payload.get("reset_observed_utc")
    )
    receipt_observed_value = evidence_payload.get("observed_utc")
    if (
        not isinstance(path_value, str)
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest.casefold())
        or not isinstance(captured_value, str)
        or not isinstance(observed_value, str)
        or not isinstance(receipt_observed_value, str)
    ):
        raise OperatorError("Resource Daily frame provenance is malformed")
    try:
        captured = datetime.fromisoformat(captured_value.replace("Z", "+00:00"))
        observed = datetime.fromisoformat(observed_value.replace("Z", "+00:00"))
        receipt_observed = datetime.fromisoformat(
            receipt_observed_value.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise OperatorError("Resource Daily frame provenance timestamp is invalid") from exc
    if (
        captured.tzinfo is None
        or observed.tzinfo is None
        or receipt_observed.tzinfo is None
    ):
        raise OperatorError("Resource Daily frame provenance must be UTC")
    captured = captured.astimezone(timezone.utc)
    observed = observed.astimezone(timezone.utc)
    receipt_observed = receipt_observed.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    if (
        captured > now
        or observed > now
        or receipt_observed > now
        or (now - captured).total_seconds() > 600
        or (now - observed).total_seconds() > 600
        or (now - receipt_observed).total_seconds() > 600
    ):
        raise OperatorError("Resource Daily identity frame is stale")
    if abs((observed - captured).total_seconds()) > 600:
        raise OperatorError("Resource Daily observation timestamp is not frame-bound")
    if abs((receipt_observed - observed).total_seconds()) > 600:
        raise OperatorError("Resource identity receipt timestamp is not frame-bound")
    frame_candidate = Path(path_value)
    if frame_candidate.is_absolute():
        raise OperatorError("resource Daily frame must be a session-relative path")
    if any(part == ".." for part in frame_candidate.parts):
        raise OperatorError("resource Daily frame path contains traversal")
    session_path = Path(session)
    if session_path.is_symlink() or not session_path.is_dir():
        raise OperatorError("Resource Daily identity session directory is unavailable or unsafe")
    session_path = session_path.resolve()
    lexical_frame = session_path / frame_candidate
    probe = session_path
    for part in frame_candidate.parts[:-1]:
        probe = probe / part
        if probe.is_symlink() or not probe.is_dir():
            raise OperatorError("resource Daily frame path uses an unsafe directory")
    if lexical_frame.is_symlink():
        raise OperatorError("resource Daily frame must be a regular non-symlink file")
    frame_path = _session_relative_path(session_path, path_value, "resource Daily frame")
    try:
        actual_digest, size = sha256_stream(frame_path)
    except OSError as exc:
        raise OperatorError("Resource Daily frame cannot be hashed") from exc
    if size <= 0 or actual_digest.casefold() != digest.casefold():
        raise OperatorError("Resource Daily frame hash does not match its provenance")
    import cv2

    image = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
    if image is None or tuple(image.shape[:2]) != (
        BLUESTACKS_NATIVE_HEIGHT,
        BLUESTACKS_NATIVE_WIDTH,
    ):
        raise OperatorError("Resource Daily identity frame is not native 800x1280")
    from scripts.daily_row_claim_bluestacks import (
        BLUESTACKS_RUNTIME_PROFILE_ID,
        DAILY_SELECTED_STATE,
        DailyRowClaimRecognizer,
    )

    recognition = DailyRowClaimRecognizer().recognize_daily_claim(
        image,
        game_day_id=None,
        observed_utc=observed,
    )
    visual = recognition.visual_evidence or {}
    if (
        not recognition.recognized
        or recognition.state != DAILY_SELECTED_STATE
        or visual.get("selected_daily") is not True
        or visual.get("runtime_profile_id") != BLUESTACKS_RUNTIME_PROFILE_ID
    ):
        raise OperatorError("Resource Daily identity frame is not positively recognized")
    return frame_path, actual_digest.casefold(), captured, observed, visual


def _produce_resource_runtime_identity(
    *,
    runtime_scope: str | None = None,
    account_id: str | None = None,
    server_id: str | None = None,
    reset_id: str | None = None,
    identity_evidence: Path | None = None,
    session: Path | None = None,
    return_deadline_evidence: bool = False,
):
    """Produce Resource identity from one authenticated receipt and fixed constants.

    The legacy identity arguments remain accepted for generic CLI compatibility, but are ignored
    for Resource.  The receipt and the current checked-in runtime binding are authoritative.
    """

    from tasks.runtime_identity import (
        ResourceIdentityEvidence,
        RuntimeIdentityConfiguration,
        produce_resource_runtime_identity,
    )

    if session is None:
        raise OperatorError("Resource production identity requires the current session")
    expected_binding = _resource_fixed_runtime_binding()
    current_session = Path(session)
    if current_session.is_symlink() or not current_session.is_dir():
        raise OperatorError("Resource production identity requires the current session")
    current_session = current_session.resolve()
    evidence_payload, deadline_payload, identity_session = _load_resource_identity_payload(
        identity_evidence
    )
    if identity_session == current_session:
        raise OperatorError(
            "Resource production identity must come from a prior identity-observation session"
        )
    receipt_invocation_id = deadline_payload.get("_receipt_producer_invocation_id")
    if receipt_invocation_id != identity_session.name:
        raise OperatorError("Resource production receipt invocation is not session-bound")
    frame_path, frame_digest, captured_utc, observed_utc, visual = _resource_identity_frame_proof(
        session=identity_session,
        evidence_payload=evidence_payload,
        deadline_payload=deadline_payload,
    )
    claimed_deadline_identity, claimed_deadline = _resource_deadline_evidence(deadline_payload)
    derived_identity = visual.get("reset_deadline_identity")
    derived_deadline = visual.get("reset_deadline_utc")
    derived_observed = visual.get("reset_observed_utc")
    if (
        derived_identity != claimed_deadline_identity
        or derived_deadline != deadline_payload.get("normalized_deadline_utc")
        or derived_observed != deadline_payload.get("observed_utc", deadline_payload.get("reset_observed_utc"))
    ):
        raise OperatorError("Resource Daily recognizer disagrees with claimed deadline evidence")
    verified_deadline_payload = dict(deadline_payload)
    verified_deadline_payload.update(
        {
            "deadline_identity": derived_identity,
            "normalized_deadline_utc": derived_deadline,
            "observed_utc": derived_observed,
            "reset_observed_utc": derived_observed,
            "reset_timer_seconds": visual.get("reset_timer_seconds"),
            "daily_frame": {
                "path": frame_path.relative_to(identity_session).as_posix(),
                "sha256": frame_digest,
                "captured_utc": captured_utc.isoformat().replace("+00:00", "Z"),
                "observed_utc": observed_utc.isoformat().replace("+00:00", "Z"),
            },
            "machine_observed": True,
        }
    )
    evaluated_utc = datetime.now(timezone.utc)
    verified_deadline_payload["_evaluated_utc"] = (
        evaluated_utc.isoformat().replace("+00:00", "Z")
    )
    evidence_refs_value = evidence_payload.get("evidence_refs")
    if evidence_refs_value is None:
        evidence_refs = ()
    elif isinstance(evidence_refs_value, (list, tuple)):
        evidence_refs = tuple(evidence_refs_value)
    else:
        raise OperatorError("Resource identity receipt evidence references are malformed")
    required_refs = (
        f"frame-path:{frame_path.relative_to(identity_session).as_posix()}",
        f"frame-sha256:{frame_digest}",
        f"producer-session:{identity_session.name}",
    )
    producer_refs = {
        ref for ref in evidence_refs if isinstance(ref, str) and ref.startswith("producer-session:")
    }
    frame_path_refs = {
        ref for ref in evidence_refs if isinstance(ref, str) and ref.startswith("frame-path:")
    }
    frame_sha_refs = {
        ref for ref in evidence_refs if isinstance(ref, str) and ref.startswith("frame-sha256:")
    }
    if (
        (producer_refs and producer_refs != {required_refs[2]})
        or (frame_path_refs and frame_path_refs != {required_refs[0]})
        or (frame_sha_refs and frame_sha_refs != {required_refs[1]})
    ):
        raise OperatorError(
            "Resource identity receipt evidence references must bind the prior identity session"
        )
    evidence_payload = dict(evidence_payload)
    if any(ref not in evidence_refs for ref in required_refs):
        evidence_refs = tuple(dict.fromkeys((*evidence_refs, *required_refs)))
        evidence_payload["evidence_refs"] = evidence_refs
        evidence_payload["content_digest"] = "0" * 64
        provisional = ResourceIdentityEvidence(**dict(evidence_payload))
        evidence_payload["content_digest"] = provisional.computed_digest()
    else:
        evidence_payload["evidence_refs"] = evidence_refs
    try:
        evidence = ResourceIdentityEvidence(**dict(evidence_payload))
        configuration = RuntimeIdentityConfiguration(
            expected_binding.runtime_scope,
            expected_binding.account_id,
            expected_binding.server_id,
            evidence.reset_id,
        )
        identity = produce_resource_runtime_identity(
            configuration,
            evidence,
            verified_deadline_payload,
            evaluated_utc,
            expected_binding,
        )
        if return_deadline_evidence:
            return identity, verified_deadline_payload
        return identity
    except (TypeError, ValueError) as exc:
        raise OperatorError(f"Resource production identity denied: {exc}") from exc


def _inspect_admitted_resource_store(path: Path, *, fixed_canonical: bool) -> None:
    """Read the store schema without allowing SQLite to create or migrate it."""

    if fixed_canonical:
        from scripts.navigation_development_boundary import (
            CANONICAL_ACTION_STORE_PATH,
            require_fixed_orchestrator_path,
        )

        path = require_fixed_orchestrator_path(
            path,
            CANONICAL_ACTION_STORE_PATH,
            "canonical Resource SafetyStore",
        )
    if path.is_symlink() or not path.is_file():
        raise OperatorError("canonical Resource SafetyStore v4 is not already admitted")
    try:
        connection = sqlite3.connect(
            path.resolve().as_uri() + "?mode=ro",
            uri=True,
            timeout=0,
        )
    except sqlite3.Error as exc:
        raise OperatorError("canonical Resource SafetyStore cannot be inspected read-only") from exc
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        version_row = connection.execute(
            "SELECT version FROM schema_version WHERE singleton=1"
        ).fetchone()
        if version_row is None or int(version_row["version"]) != 4:
            raise OperatorError(
                "canonical Resource SafetyStore must already be schema v4; migration is disabled"
            )
        tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        required = {
            "actions",
            "controller_lease",
            "resource_reset_identities",
            "resource_occurrences",
            "resource_attempts",
            "resource_attempt_claims",
            "resource_reservations",
            "resource_transport_facts",
            "resource_transport_outcomes",
            "resource_live_effects",
        }
        if not required.issubset(tables):
            raise OperatorError(
                "canonical Resource SafetyStore v4 is incomplete; migration is disabled"
            )
    except sqlite3.Error as exc:
        raise OperatorError("canonical Resource SafetyStore schema is unreadable") from exc
    finally:
        connection.close()


def _open_admitted_resource_store(
    *,
    store_path: Path | None = None,
    store_factory: Callable[[Path], Any] | None = None,
) -> Any:
    """Open v4 only after a read-only schema admission check.

    ``store_factory`` and a non-canonical path are private offline-test seams.
    The production call uses the fixed canonical path and the real SafetyStore.
    """

    from safe_action_core import SafetyStore
    from safe_action_core.store import SchemaVersionError
    from scripts.navigation_development_boundary import CANONICAL_ACTION_STORE_PATH

    injected = store_factory is not None
    path = Path(store_path) if store_path is not None else Path(CANONICAL_ACTION_STORE_PATH)
    _inspect_admitted_resource_store(path, fixed_canonical=not injected)
    factory = store_factory or SafetyStore
    try:
        store = factory(path)
    except (OSError, SchemaVersionError) as exc:
        raise OperatorError("canonical Resource SafetyStore v4 could not be opened") from exc
    if getattr(store, "schema_version", None) != 4:
        try:
            store.close()
        except BaseException:
            pass
        raise OperatorError("canonical Resource SafetyStore must already be schema v4")
    return store


def _resource_reset_identity(
    verified_identity: Any,
    deadline_payload: Mapping[str, Any],
) -> Any:
    """Bind one Resource reset to the exact observed deadline and 24-hour interval."""

    from safe_action_core.resource_effect_authority import ResourceResetIdentity
    from tasks.runtime_identity import (
        RuntimeIdentityAssurance,
        VerifiedRuntimeIdentity,
    )

    if type(verified_identity) is not VerifiedRuntimeIdentity:
        raise OperatorError("Resource runtime identity is missing or not verified")
    if (
        verified_identity.assurance
        is not RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_RESET_OBSERVED
    ):
        raise OperatorError(
            "Resource runtime identity is not FIXED_RUNTIME_BINDING_RESET_OBSERVED"
        )
    deadline_identity, deadline = _resource_deadline_evidence(deadline_payload)
    if verified_identity.reset_id != deadline_identity:
        raise OperatorError("Resource runtime identity does not match the observed reset deadline")
    if not verified_identity.observed_utc or not verified_identity.expires_utc:
        raise OperatorError("Resource runtime identity freshness evidence is incomplete")
    observed = _resource_identity_timestamp(
        verified_identity.observed_utc,
        "Resource runtime identity observed_utc",
    )
    expires = _resource_identity_timestamp(
        verified_identity.expires_utc,
        "Resource runtime identity expires_utc",
    )
    evaluated_value = deadline_payload.get("_evaluated_utc")
    if evaluated_value is None:
        evaluated = datetime.now(timezone.utc)
    else:
        evaluated = _resource_identity_timestamp(
            evaluated_value,
            "Resource identity evaluation timestamp",
        )
    if observed > evaluated or expires <= evaluated or expires <= observed:
        raise OperatorError("Resource runtime identity is stale")
    if evaluated >= deadline:
        raise OperatorError("Resource reset deadline has been reached")
    if deadline <= observed:
        raise OperatorError("Resource reset deadline is not after observed identity evidence")
    evidence_refs = tuple(
        dict.fromkeys(
            (
                *tuple(verified_identity.evidence_refs),
                deadline_identity,
            )
        )
    )
    return ResourceResetIdentity(
        reset_identity_id=deadline_identity,
        account_id=verified_identity.account_id,
        server_id=verified_identity.server_id,
        runtime_scope=verified_identity.runtime_scope,
        reset_start_utc=(deadline - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        reset_deadline_utc=deadline.isoformat().replace("+00:00", "Z"),
        assurance="FIXED_RUNTIME_BINDING_RESET_OBSERVED",
        observed_at=max(0.0, observed.timestamp()),
        expires_at=expires.timestamp(),
        evidence_refs=evidence_refs,
    )


def _build_resource_runtime_components(
    *,
    session: Any,
    verified_identity: Any,
    deadline_payload: Mapping[str, Any],
    store_path: Path | None = None,
    store_factory: Callable[[Path], Any] | None = None,
    wall_clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Construct the production Resource authority inside the held session."""

    from safe_action_core.models import (
        ActionClass,
        ActionIntent,
        Observation,
        PolicyRequest,
    )
    from safe_action_core.policy import ACTIVE_RUNTIME_PROFILE_ID, CentralPolicy
    from safe_action_core.resource_effect_authority import (
        PreparedResourceAuthorization,
        ResourceEffectAuthority,
        ResourceOccurrenceIdentity,
        ResourceReservationSpec,
        RESOURCE_FLOW_ID,
        RESOURCE_OBJECTIVE_ACTION_ID,
        RESOURCE_PRODUCT_POLICY_REVISION,
        RESOURCE_RECURRENCE_CLASS,
        RESOURCE_RECURRENCE_POLICY_REVISION,
        RESOURCE_TARGET_VARIANT,
    )
    from scripts.flow_delivery_daily_resource_item_bluestacks import (
        ResourceDispatchWindow,
        ResourceDispatchWindowError,
    )
    from scripts.navigation_development_boundary import DevelopmentSessionError

    if not hasattr(session, "runtime_input_lock"):
        raise OperatorError("pnsctl DevelopmentSession cannot expose its held runtime lock")
    try:
        runtime_lock = session.runtime_input_lock
    except DevelopmentSessionError as exc:
        raise OperatorError("Resource authority requires the entered pnsctl DevelopmentSession") from exc
    owner = str(getattr(session, "owner", "") or "")
    invocation_id = str(getattr(session, "invocation_id", "") or "")
    if not owner or not invocation_id:
        raise OperatorError("Resource authority requires the exact pnsctl owner and invocation")
    runtime_lock.assert_held(owner, invocation_id)
    reset_identity = _resource_reset_identity(verified_identity, deadline_payload)
    dispatch_window = ResourceDispatchWindow(
        reset_deadline_utc=_resource_identity_timestamp(
            reset_identity.reset_deadline_utc,
            "Resource reset deadline",
        ),
        receipt_expires_utc=_resource_identity_timestamp(
            verified_identity.expires_utc,
            "Resource receipt expiry",
        ),
    )
    try:
        dispatch_window.require_current(
            ResourceDispatchWindow.sample_current_utc(wall_clock)
        )
    except ResourceDispatchWindowError as exc:
        raise OperatorError(
            "Resource dispatch window denied before Resource SafetyStore open"
        ) from exc
    store = _open_admitted_resource_store(
        store_path=store_path,
        store_factory=store_factory,
    )
    authority = None
    controller_lease: Mapping[str, Any] | None = None
    try:
        authority = ResourceEffectAuthority(store)
        now = time.monotonic()
        controller_lease = authority.acquire_resource_controller_lease(
            owner_id=owner,
            now=now,
            ttl_seconds=600.0,
            mode="execute",
            runtime_invocation_id=invocation_id,
            block_keys={
                "account_id": reset_identity.account_id,
                "server_id": reset_identity.server_id,
                "reset_identity_id": reset_identity.reset_identity_id,
            },
        )
        policy = CentralPolicy(supervised_tasks={RESOURCE_FLOW_ID})
        preparation_used = False

        def prepare_resource_effect(
            source: Any,
            target_roi: tuple[int, int, int, int],
            requested_action_key: str,
        ) -> PreparedResourceAuthorization:
            nonlocal preparation_used
            if preparation_used:
                raise OperatorError("Resource preparation callback is one-shot")
            preparation_used = True
            from scripts.bluestacks_native_runtime import CapturedNativeFrame

            if type(source) is not CapturedNativeFrame:
                raise OperatorError("Resource preparation requires the captured immediate-before frame")
            if requested_action_key != "daily-resource-item:use-1k-food":
                raise OperatorError("Resource preparation action key is not the exact Use seam")
            runtime_lock.assert_held(owner, invocation_id)
            now = time.monotonic()
            authority.create_reset_identity(reset_identity)
            occurrence = authority.create_resource_occurrence(
                ResourceOccurrenceIdentity(
                    reset_identity.account_id,
                    reset_identity.server_id,
                    RESOURCE_FLOW_ID,
                    reset_identity.reset_identity_id,
                    product_policy_revision=RESOURCE_PRODUCT_POLICY_REVISION,
                    recurrence_policy_revision=RESOURCE_RECURRENCE_POLICY_REVISION,
                    recurrence_class=RESOURCE_RECURRENCE_CLASS,
                    objective_action_id=RESOURCE_OBJECTIVE_ACTION_ID,
                    target_variant=RESOURCE_TARGET_VARIANT,
                ),
                now=now,
            )
            occurrence_id = str(occurrence["occurrence_id"])
            hypothesis_digest = hashlib.sha256(
                json.dumps(
                    {
                        "source_sha256": source.sha256,
                        "target_roi": tuple(target_roi),
                        "target_identity": "daily-resource-item:use-1k-food",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            claim = authority.claim_resource_attempt(
                occurrence_id,
                owner,
                expected_revision=int(occurrence["state_revision"]),
                now=now,
                hypothesis_digest=hypothesis_digest,
            )
            if claim.state != "ACTIVE" or not claim.can_dispatch:
                raise OperatorError("Resource occurrence did not grant one dispatch claim")
            context = authority.occurrence_context(occurrence_id)
            controller_token = str(
                controller_lease.get("controller_token")
                or controller_lease.get("lease_token")
                or ""
            )
            controller_generation = int(
                controller_lease.get(
                    "controller_generation",
                    controller_lease.get("generation", 0),
                )
            )
            authorization_generation = authority.next_resource_authorization_generation(context)
            reservation_spec = ResourceReservationSpec(
                authorization_generation=authorization_generation,
                immediate_before_sha256=source.sha256,
                runtime_invocation_id=invocation_id,
                controller_token=controller_token,
                controller_generation=controller_generation,
            )
            fence = authority.resource_dispatch_fence(
                context,
                claim,
                controller_lease,
                reservation_spec,
            )
            height, width = source.frame.shape[:2]
            observation = Observation(
                frame_sha256=source.sha256,
                capture_completed_monotonic=float(source.captured_monotonic),
                runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
                width=int(width),
                height=int(height),
                valid_png=source.png[:8] == b"\x89PNG\r\n\x1a\n",
                corrupt=False,
                black=not bool(source.frame.any()),
                source_state="RESOURCES_1K_FOOD_READY",
                overlay_state="none",
                target_identity="daily-resource-item:use-1k-food",
                target_roi=tuple(target_roi),
                recognized=True,
                control_class="USE",
                consequence="ordinary_non_idempotent_resource_item_use",
                cost_type="owned_inventory_item",
                cost_amount=1,
                quantity=1,
                expected_postcondition="RESOURCES_1K_FOOD_USED",
                evidence_refs=(
                    *tuple(verified_identity.evidence_refs),
                    f"frame:{source.sha256}",
                ),
                package_foreground=True,
            )
            action_key = authority.resource_action_key(context, authorization_generation)
            action_id = (
                "resource-action:v1:"
                + hashlib.sha256(
                    json.dumps(
                        {
                            "action_key": action_key,
                            "context": context.as_dict(),
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
            )
            intent = ActionIntent(
                action_id=action_id,
                action_key=action_key,
                task_id=RESOURCE_FLOW_ID,
                semantic_action="USE_RESOURCE_ITEM",
                source_state="RESOURCES_1K_FOOD_READY",
                target_identity="daily-resource-item:use-1k-food",
                target_roi=tuple(target_roi),
                source_frame_sha256=source.sha256,
                source_frame_captured_at=float(source.captured_monotonic),
                runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
                game_day_id=reset_identity.reset_identity_id,
                expected_postcondition="RESOURCES_1K_FOOD_USED",
                consequence="ordinary_non_idempotent_resource_item_use",
                cost_type="owned_inventory_item",
                cost_amount=1,
                quantity=1,
                evidence_refs=observation.evidence_refs,
                consequential=False,
                action_class=ActionClass.OWNED_ITEM_NON_IDEMPOTENT,
                action_kind="USE_RESOURCE_ITEM",
                subject="1k_food",
                resource_or_currency="1k_food",
                maximum_cost=1,
                free_only=False,
                semantic_preconditions=("exact_owned_1k_food", "single_use"),
                semantic_postconditions=("RESOURCES_1K_FOOD_USED",),
                resource_authorization_context=context,
            )
            duplicate = store.connection.execute(
                "SELECT 1 FROM actions WHERE action_key=?",
                (action_key,),
            ).fetchone() is not None
            request = PolicyRequest(
                action_id=action_id,
                action_key=action_key,
                task_id=RESOURCE_FLOW_ID,
                task_mode="supervised_validation",
                semantic_action="USE_RESOURCE_ITEM",
                expected_runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
                observation=observation,
                monotonic_now=now,
                observation_max_age_seconds=30.0,
                dispatch_max_age_seconds=30.0,
                lease_owner=owner,
                lease_valid=True,
                unresolved_action=False,
                duplicate_action_key=duplicate,
                game_day_id=reset_identity.reset_identity_id,
                policy_phase="pre_dispatch",
                action_class=ActionClass.OWNED_ITEM_NON_IDEMPOTENT,
                action_kind="USE_RESOURCE_ITEM",
                subject="1k_food",
                resource_or_currency="1k_food",
                maximum_cost=1,
                free_only=False,
                semantic_preconditions=("exact_owned_1k_food", "single_use"),
                semantic_postconditions=("RESOURCES_1K_FOOD_USED",),
                runtime_session_id=invocation_id,
                resource_authorization_context=context,
                effect_dispatch_fence=fence,
            )
            issued = policy.issue_capability(request)
            if not issued.authorized or issued.capability is None:
                raise OperatorError(
                    f"Resource capability denied: {issued.reason_code}"
                )
            prepared = authority.prepare_resource_effect_action(
                context,
                claim,
                claim,
                controller_lease,
                intent,
                issued.policy_result,
                reservation_spec,
                now=now,
            )
            if prepared.fence != fence:
                raise OperatorError("Resource preparation fence changed during atomic preparation")
            return PreparedResourceAuthorization(
                prepared=prepared,
                request=request,
                capability=issued.capability,
            )

        def runtime_factory(inner: Any) -> Any:
            from scripts.flow_delivery_daily_resource_item_bluestacks import (
                AuthorizedResourceItemRuntime,
            )

            return AuthorizedResourceItemRuntime(
                inner,
                authority=authority,
                controller_lease=controller_lease,
                runtime_lock=runtime_lock,
                policy=policy,
                prepare=prepare_resource_effect,
                now=time.monotonic,
                dispatch_window=dispatch_window,
                wall_clock=wall_clock,
            )

        return {
            "runtime_factory": runtime_factory,
            "authority": authority,
            "store": store,
            "controller_lease": controller_lease,
            "dispatch_window": dispatch_window,
        }
    except BaseException:
        if authority is not None and controller_lease is not None:
            try:
                authority.release_resource_controller_lease(
                    owner,
                    str(
                        controller_lease.get("controller_token")
                        or controller_lease.get("lease_token")
                        or ""
                    ),
                    time.monotonic(),
                )
            except BaseException:
                pass
        store.close()
        raise


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
    runtime_scope: str | None = None,
    account_id: str | None = None,
    server_id: str | None = None,
    reset_id: str | None = None,
    identity_evidence: Path | None = None,
    command_argv: Sequence[str] | None = None,
    _resource_store_path: Path | None = None,
    _resource_store_factory: Callable[[Path], Any] | None = None,
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
    resource_runtime_identity = None
    resource_deadline_evidence: dict[str, Any] | None = None
    resource_runtime_components: dict[str, Any] | None = None

    if chest_continuation is not None:
        chest_continuation = Path(chest_continuation)

    if flow_id not in BLUESTACKS_FLOW_IDS:
        raise OperatorError("flow ID is not in the checked-in runtime allowlist")
    contract = _load_bluestacks_flow_registry().get(flow_id)
    if contract is None or contract["runner"] not in _BLUESTACKS_FLOW_RUNNERS:
        raise OperatorError("DEVELOPMENT_FLOW_RUNNER_UNAVAILABLE")
    nova_identity = None
    if flow_id == NOVA_SUPERVISED_PULSE_FLOW_ID:
        if not 1 <= int(max_inputs) <= NOVA_SUPERVISED_PULSE_MAX_INPUTS:
            raise OperatorError(
                f"Nova supervised development-session max_inputs must be between 1 and "
                f"{NOVA_SUPERVISED_PULSE_MAX_INPUTS}"
            )
        nova_identity, missing = _nova_supervised_identity(
            argparse.Namespace(
                runtime_scope=runtime_scope,
                account_id=account_id,
                server_id=server_id,
                reset_id=reset_id,
                identity_evidence=identity_evidence,
            )
        )
        if missing:
            raise OperatorError(
                "Nova development-session identity is incomplete: "
                + ", ".join(missing)
            )
        _validate_nova_reset_id(nova_identity.reset_id)
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
            if flow_id == "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION" and live:
                produced = _produce_resource_runtime_identity(
                    runtime_scope=runtime_scope,
                    account_id=account_id,
                    server_id=server_id,
                    reset_id=reset_id,
                    identity_evidence=identity_evidence,
                    session=session_directory,
                    return_deadline_evidence=True,
                )
                resource_runtime_identity, resource_deadline_evidence = produced
                resource_runtime_components = _build_resource_runtime_components(
                    session=session,
                    verified_identity=resource_runtime_identity,
                    deadline_payload=resource_deadline_evidence,
                    store_path=_resource_store_path,
                    store_factory=_resource_store_factory,
                )
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
                "nova_identity": nova_identity,
                "nova_reset_id": (
                    nova_identity.reset_id if nova_identity is not None else None
                ),
                "development_session": session,
                "resource_runtime_identity": resource_runtime_identity,
                "resource_deadline_evidence": resource_deadline_evidence,
            }
            if resource_runtime_components is not None:
                runtime_context["resource_runtime_factory"] = resource_runtime_components[
                    "runtime_factory"
                ]
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
        try:
            if resource_runtime_components is not None:
                authority = resource_runtime_components["authority"]
                controller = resource_runtime_components["controller_lease"]
                try:
                    authority.release_resource_controller_lease(
                        owner,
                        str(
                            controller.get("controller_token")
                            or controller.get("lease_token")
                            or ""
                        ),
                        time.monotonic(),
                    )
                finally:
                    resource_runtime_components["store"].close()
        finally:
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
    selected_reset = _validate_nova_reset_id(reset_id)
    if not re.fullmatch(r"[0-9a-f]{40}", candidate_commit):
        raise OperatorError("Nova supervised guard candidate_commit is invalid")
    guard_path = _nova_supervised_guard_path(selected_reset)
    guard_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "flow_id": NOVA_SUPERVISED_PULSE_FLOW_ID,
        "scenario_id": NOVA_SUPERVISED_PULSE_SCENARIO_ID,
        "reset_id": selected_reset,
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
    reset_id: str,
) -> None:
    selected_reset = _validate_nova_reset_id(reset_id)
    path = _nova_supervised_guard_path(selected_reset)
    if not path.is_file():
        raise OperatorError("supervised invocation guard is missing at finalization")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperatorError("supervised invocation guard is unreadable") from exc
    if not isinstance(payload, dict):
        raise OperatorError("supervised invocation guard must be an object")
    if payload.get("reset_id") != selected_reset:
        raise OperatorError("guard reset_id mismatch at finalization")
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
    if os.path.islink(path):
        raise OperatorError("supervised invocation guard is unsafe at finalization")
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        os.replace(str(tmp), str(path))
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise


def _bind_nova_supervised_invocation_guard_session(
    session_directory: str,
    *,
    reset_id: str | None = None,
) -> None:
    """Atomically bind the active guard to a session as soon as it exists.

    Preserves guard identity/status fields. Never deletes the guard or weakens O_EXCL.
    """

    selected_reset = _validate_nova_reset_id(
        reset_id if reset_id is not None else _infer_single_nova_reset_id()
    )
    path = _nova_supervised_guard_path(selected_reset)
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
    if payload.get("reset_id") != selected_reset:
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
    if os.path.islink(tmp):
        raise OperatorError("supervised invocation guard temporary path is unsafe")
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
    _validate_nova_reset_id(guard.get("reset_id"))

    events = _read_jsonl_objects(session / "events.jsonl", "events.jsonl")
    if not events:
        raise OperatorError("events.jsonl must be nonempty")
    praise_transport_field_present = "praise_transport_calls" in result
    praise = (
        result.get("praise_transport_calls") if praise_transport_field_present else None
    )
    if praise_transport_field_present:
        if type(praise) is not int or praise != 0:
            raise OperatorError("proven_no_effect requires praise_transport_calls == 0")
    capability_audit = _read_jsonl_objects(
        session / "capability-audit.jsonl",
        "capability-audit.jsonl",
    )
    zero_input_block = (
        result.get("status") == "blocked"
        and nav == 0
        and praise_transport_field_present
        and praise == 0
    )
    if not capability_audit and not zero_input_block:
        raise OperatorError("capability-audit.jsonl must be nonempty")

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
            nova_count = connection.execute(
                f"SELECT COUNT(*) AS n FROM actions "
                f"WHERE task_id=? AND game_day_id=? AND NOT ({no_effect_clause})",
                (NOVA_TASK_ID, guard["reset_id"]),
            ).fetchone()["n"]
        finally:
            connection.close()
        if int(nova_count) != 0:
            raise OperatorError(
                "SafetyStore has current-reset Nova action rows; not proven_no_effect"
            )
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
                if row.get("game_day_id") == guard["reset_id"]
                and not is_no_effect_cancelled(row)
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
    reset_id: str | None = None,
    legacy_null_session_recovery: bool = False,
    expected_candidate_commit: str | None = None,
) -> str:
    """Archive the active Nova supervised guard only after audited proven-no-effect proof."""

    selected_reset = _validate_nova_reset_id(
        reset_id if reset_id is not None else _infer_single_nova_reset_id()
    )
    guard_path = _nova_supervised_guard_path(selected_reset)
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
    if guard.get("reset_id") != selected_reset:
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

    receipt_dir = _nova_supervised_guard_receipt_dir()
    archive_dir = _nova_supervised_guard_archive_dir()
    receipt_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = (
        receipt_dir
        / f"proven-no-effect-{stamp}-{receipt_digest[:16]}.json"
    )
    archive_path = (
        archive_dir
        / f"nova-praise-one-free-pulse-{selected_reset}.guard.{stamp}.{guard_sha256[:16]}.json"
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
    selected = _validate_nova_reset_id(getattr(args, "reset_id", None))
    verified = _validate_nova_reset_id(getattr(identity, "reset_id", None))
    if selected != verified:
        raise OperatorError("supervised pulse reset_id does not match verified identity")


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


def _retained_flow_result(
    session_directory: Path,
) -> tuple[Path, dict[str, Any]]:
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
    legacy_nova = False
    if not result_path.is_file() and not result_path.is_symlink():
        legacy_nova_result = session / "result.json"
        if legacy_nova_result.is_file() and not legacy_nova_result.is_symlink():
            result_path = legacy_nova_result
            legacy_nova = True
    if result_path.is_symlink() or not result_path.is_file():
        raise OperatorError("flow-delivery-result.json is required")
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperatorError("flow-delivery-result.json is required") from exc
    if (
        not isinstance(result, dict)
        or result.get("schema_version") != 1
        or result.get("flow_id") not in BLUESTACKS_FLOW_IDS
        or (legacy_nova and result.get("flow_id") != NOVA_SUPERVISED_PULSE_FLOW_ID)
    ):
        raise OperatorError("unsupported flow-delivery result identity")
    return session, result


def bluestacks_verify_flow(session_directory: Path) -> str:
    session, retained_result = _retained_flow_result(session_directory)
    retained_flow_id = str(retained_result["flow_id"])
    if retained_flow_id == NOVA_SUPERVISED_PULSE_FLOW_ID:
        structure = _verify_nova_supervised_one_free_pulse_session(session)
        return json.dumps(
            {
                "status": "verified",
                "flow_id": retained_flow_id,
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

    structure = _verify_flow_structure(session)
    try:
        queue, lease = _load_flow_delivery_state(require_runtime_held=False)
        if queue.get("active_flow_id") != retained_flow_id:
            raise OperatorError("active flow does not match retained evidence")
    except OperatorError:
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
        elif retained_flow_id in {
            "BIOENHANCER-FREE-RESEARCH-BLUESTACKS-INTEGRATION",
            "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
            "SUPPLY-DEPOT-BLUESTACKS-INTEGRATION",
            "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION",
        }:
            queue = {"active_flow_id": retained_flow_id}
            lease = {
                "active_stage": "evidence_review",
                "runtime_ownership_state": "released",
                "unresolved_action_state": "clear",
            }
        else:
            queue, lease = _retained_troop_training_state(session)
    if lease.get("active_stage") != "evidence_review":
        raise OperatorError("verify-flow requires the active evidence_review stage")
    flow_id = queue["active_flow_id"]
    contract = _load_bluestacks_flow_registry().get(flow_id)
    if (
        contract is None
        or contract["evidence_validator"] not in _BLUESTACKS_EVIDENCE_VALIDATORS
    ):
        raise OperatorError("FLOW_EVIDENCE_VALIDATOR_UNAVAILABLE")
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
    if os.path.islink(args.identity_evidence) or not args.identity_evidence.is_file():
        raise OperatorError("Nova supervised identity evidence is missing or unsafe")
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
        selected_reset_id = _validate_nova_reset_id(identity.reset_id)
        _confine_nova_supervised_paths(args)
        if args.preflight_only:
            return json.dumps(
                {
                    "status": "preflight_passed",
                    "scenario_id": NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                    "flow_id": NOVA_SUPERVISED_PULSE_FLOW_ID,
                    "reset_id": selected_reset_id,
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
            reset_id=selected_reset_id,
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
                route_result["reset_id"] = selected_reset_id
                if session:
                    _bind_nova_supervised_invocation_guard_session(
                        session,
                        reset_id=selected_reset_id,
                    )
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
                reset_id=selected_reset_id,
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


_CONDUCT_DEFAULT_MAX_INPUTS = {
    "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION": 16,
    "NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE": 8,
    "BIOENHANCER-FREE-RESEARCH-BLUESTACKS-INTEGRATION": 8,
    "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION": 4,
    "SUPPLY-DEPOT-BLUESTACKS-INTEGRATION": 10,
    "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION": 10,
    "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION": 24,
}
_CONDUCT_KNOWLEDGE_PATHS = (
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / "docs" / "android-back-state-matrix.md",
    REPO_ROOT / "docs" / "runtime-input-safety-policy.md",
)


def _conduct_max_inputs(flow_id: str, requested: int | None) -> int:
    maximum = (
        _CONDUCT_DEFAULT_MAX_INPUTS.get(flow_id, 12)
        if requested is None
        else int(requested)
    )
    if not 1 <= maximum <= 100:
        raise OperatorError("conduct max_inputs must be between 1 and 100")
    return maximum


def _derive_conductor_framing(flow_id: str) -> dict[str, bool]:
    """Derive the routine framing claims from checked-in policy and route bindings."""

    from tasks.gameplay_flow_contracts import load_flow_contract

    registry = _load_bluestacks_flow_registry()
    route = registry.get(flow_id)
    if route is None:
        return {}
    try:
        active_contract = load_flow_contract(flow_id)
    except (OSError, UnicodeError, ValueError):
        active_contract = {}
    contract_consulted = (
        isinstance(active_contract, Mapping)
        and active_contract.get("flow_id") == flow_id
    )
    try:
        knowledge = [
            path.read_text(encoding="utf-8") for path in _CONDUCT_KNOWLEDGE_PATHS
        ]
    except (OSError, UnicodeError):
        knowledge = []
    handlers_bound = (
        route["runner"] in _BLUESTACKS_FLOW_RUNNERS
        and route["evidence_validator"] in _BLUESTACKS_EVIDENCE_VALIDATORS
        and route["recovery_handler"] in _BLUESTACKS_RECOVERY_HANDLERS
    )
    policy_consulted = len(knowledge) == len(_CONDUCT_KNOWLEDGE_PATHS) and all(
        value.strip() for value in knowledge
    )
    return {
        "intent_match": handlers_bound and contract_consulted,
        "no_documented_unsafe_input": (
            handlers_bound and policy_consulted and contract_consulted
        ),
        # Project policy forbids manual-only states as route preconditions; a
        # current unexpected manual state remains a fail-closed runner concern.
        "no_manual_only_precondition": handlers_bound
        and policy_consulted
        and contract_consulted
        and "manual-only" in knowledge[0].casefold(),
        "consequential_actions_enumerated": route["consequence_class"]
        in {"navigation_only", "consequential"}
        and contract_consulted
        and bool(active_contract.get("consequential_action_class")),
        "durable_knowledge_consulted": policy_consulted and contract_consulted,
    }


def _conductor_live_summary(
    flow_id: str,
    run_payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Load retained route detail and verify completed execution before DONE."""

    summary = dict(run_payload)
    verification: dict[str, Any] | None = None
    runtime_session = str(run_payload.get("runtime_session_directory") or "").strip()
    if runtime_session:
        try:
            _session, retained = _retained_flow_result(Path(runtime_session))
            if retained.get("flow_id") != flow_id:
                raise OperatorError("retained flow identity does not match conduct flow")
            summary = {
                "status": retained.get("status", run_payload.get("status", "unknown")),
                "result": retained,
            }
        except OperatorError as exc:
            summary = {
                "status": "evidence_required",
                "reason": f"retained execution evidence is unavailable: {exc}",
                "result": dict(run_payload),
            }
    if str(summary.get("status") or "").casefold() in {
        "completed",
        "complete_for_reset",
        "success",
        "done",
    }:
        try:
            verification = json.loads(
                bluestacks_verify_flow(Path(runtime_session))
            )
        except (OperatorError, OSError, ValueError, json.JSONDecodeError) as exc:
            verification = {
                "status": "evidence_required",
                "flow_id": flow_id,
                "reason": f"{type(exc).__name__}: {exc}",
            }
        if verification.get("status") == "verified":
            summary["evidence_verified"] = True
            summary["verification"] = verification
        else:
            summary["status"] = "evidence_required"
            summary["reason"] = str(
                verification.get("reason")
                or "route-specific evidence verification is required"
            )
            summary["verification"] = verification
    return summary, verification


def conduct_flow(
    flow_id: str,
    *,
    live: bool = False,
    yes: bool = False,
    max_inputs: int | None = None,
    framing: Mapping[str, bool] | None = None,
    summary_path: Path | None = None,
    state_root: Path | None = None,
    runtime_scope: str | None = None,
    account_id: str | None = None,
    server_id: str | None = None,
    reset_id: str | None = None,
    identity_evidence: Path | None = None,
) -> str:
    """Run one conductor iteration for a registered flow.

    Dry-run by default: validates framing, prints the plan, and writes/updates the
    conductor-owned per-flow state file. Live execution requires ``--live --yes`` and
    goes through development-session observe + run-flow (never bypasses pnsctl).
    """

    from tasks.flow_conductor import (
        FramingChecklist,
        apply_framing,
        framing_plan,
        load_state,
        record_iteration,
        save_state,
        summary_milestone,
    )

    if flow_id not in BLUESTACKS_FLOW_IDS:
        raise OperatorError(f"unknown BlueStacks flow id: {flow_id}")

    state = load_state(flow_id, root=state_root)
    maximum = _conduct_max_inputs(flow_id, max_inputs)
    checklist_values = {
        "intent_match": False,
        "no_documented_unsafe_input": False,
        "no_manual_only_precondition": False,
        "consequential_actions_enumerated": False,
        "durable_knowledge_consulted": False,
    }
    checklist_values.update(_derive_conductor_framing(flow_id))
    if framing:
        checklist_values.update(
            {
                key: checklist_values[key] and bool(value)
                for key, value in framing.items()
            }
        )
    checklist = FramingChecklist(**checklist_values)
    state = apply_framing(state, checklist)
    plan = framing_plan(flow_id)

    if not checklist.complete():
        path = save_state(state, root=state_root)
        return json.dumps(
            {
                "status": "framing_incomplete",
                "decision": state.last_decision,
                "flow_id": flow_id,
                "state_path": str(path),
                "plan": plan,
            },
            sort_keys=True,
        )

    if summary_path is not None:
        summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
        state = record_iteration(
            state,
            summary=summary,
            milestone=summary_milestone(summary),
            evidence_ref=str(summary_path),
        )
        path = save_state(state, root=state_root)
        return json.dumps(
            {
                "status": state.status,
                "decision": state.last_decision,
                "blocker": state.last_blocker,
                "flow_id": flow_id,
                "state_path": str(path),
                "plan": plan,
            },
            sort_keys=True,
        )

    if not live:
        path = save_state(state, root=state_root)
        return json.dumps(
            {
                "status": "dry_run",
                "decision": "CONTINUE",
                "flow_id": flow_id,
                "state_path": str(path),
                "plan": plan,
                "note": "Pass --live --yes to observe then run-flow through pnsctl.",
            },
            sort_keys=True,
        )

    if not yes:
        raise OperatorError("live conduct requires --yes")
    resource_flow = flow_id == "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION"
    if resource_flow and identity_evidence is None:
        raise OperatorError(
            "Resource conduct requires the authenticated identity_evidence receipt"
        )

    observe_output = development_session_observe(
        max_inputs=1,
        flow_id=flow_id,
        command_argv=[
            "development-session",
            "observe",
            "--flow-id",
            flow_id,
            "--max-inputs",
            "1",
        ],
    )
    run_kwargs: dict[str, Any] = {
        "live": True,
        "yes": True,
        "max_inputs": maximum,
        "identity_evidence": identity_evidence,
        "command_argv": [
            "development-session",
            "run-flow",
            flow_id,
            "--live",
            "--yes",
            "--max-inputs",
            str(maximum),
        ],
    }
    if not resource_flow:
        run_kwargs.update(
            {
                "runtime_scope": runtime_scope,
                "account_id": account_id,
                "server_id": server_id,
                "reset_id": reset_id,
            }
        )
    run_output = development_session_run_flow(flow_id, **run_kwargs)
    run_payload = json.loads(run_output) if run_output.strip().startswith("{") else {
        "status": "unknown",
        "raw": run_output,
    }
    classification_summary, verification = _conductor_live_summary(
        flow_id,
        run_payload if isinstance(run_payload, dict) else {"status": "unknown"},
    )
    state = record_iteration(
        state,
        summary=classification_summary,
        milestone=summary_milestone(classification_summary),
        evidence_ref=str(run_payload.get("runtime_session_directory") or "").strip()
        or None,
    )
    path = save_state(state, root=state_root)
    return json.dumps(
        {
            "status": state.status,
            "decision": state.last_decision,
            "blocker": state.last_blocker,
            "flow_id": flow_id,
            "state_path": str(path),
            "observe": json.loads(observe_output)
            if observe_output.strip().startswith("{")
            else observe_output,
            "run": run_payload,
            "verification": verification,
            "plan": plan,
        },
        sort_keys=True,
    )


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
    resource_identity_observe = development_sub.add_parser(
        "resource-identity-observe",
        help="zero-input selected-Daily Resource identity observation",
    )
    daily_row_recon = development_sub.add_parser("daily-row-reconnaissance")
    daily_row_recon.add_argument("--max-inputs", type=int, required=True)
    daily_row_recon.add_argument("--delegated-receipt", type=Path, required=True)
    daily_row_recon.add_argument("--agent-identity", required=True)
    daily_row_recon.add_argument("--task-id", required=True)
    daily_row_recon.add_argument("--flow-id", required=True)
    daily_row_recon.add_argument("--scenario", required=True)
    daily_row_recon.add_argument("--variant", required=True)
    daily_row_claim = development_sub.add_parser("daily-row-claim")
    daily_row_claim.add_argument(
        "--mode",
        choices=("prepare", "canary", "return-home", "dismiss-vip-popup"),
        required=True,
    )
    daily_row_claim.add_argument("--max-inputs", type=int, required=True)
    daily_row_claim.add_argument("--delegated-receipt", type=Path, required=True)
    daily_row_claim.add_argument("--agent-identity", required=True)
    daily_row_claim.add_argument("--task-id", required=True)
    daily_row_claim.add_argument("--flow-id", required=True)
    daily_row_claim.add_argument("--scenario", required=True)
    daily_row_claim.add_argument("--variant", required=True)
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
    development_run.add_argument("--runtime-scope")
    development_run.add_argument("--account-id")
    development_run.add_argument("--server-id")
    development_run.add_argument("--reset-id")
    development_run.add_argument("--identity-evidence", type=Path)
    conduct = sub.add_parser(
        "conduct",
        help=(
            "Autonomous flow-delivery conductor iteration "
            "(dry-run by default; live requires --live --yes)"
        ),
    )
    conduct.add_argument("flow_id", choices=BLUESTACKS_FLOW_IDS)
    conduct.add_argument("--live", action="store_true")
    conduct.add_argument("--yes", action="store_true")
    conduct.add_argument(
        "--max-inputs",
        type=int,
        default=None,
        help="Override the registered flow's safe conductor input ceiling",
    )
    conduct.add_argument(
        "--summary",
        type=Path,
        help="Classify an existing summary.json without live input",
    )
    conduct.add_argument(
        "--state-root",
        type=Path,
        default=None,
        help="Override conductor state directory (tests)",
    )
    conduct.add_argument("--runtime-scope")
    conduct.add_argument("--account-id")
    conduct.add_argument("--server-id")
    conduct.add_argument("--reset-id")
    conduct.add_argument("--identity-evidence", type=Path)
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
    nova_guard_reconcile.add_argument("--reset-id", required=True)
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
                    reset_id=args.reset_id,
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
            elif args.development_command == "resource-identity-observe":
                output = development_session_resource_identity_observe()
            elif args.development_command == "daily-row-reconnaissance":
                output = development_session_daily_row_reconnaissance(
                    max_inputs=args.max_inputs,
                    delegated_receipt=args.delegated_receipt,
                    agent_identity=args.agent_identity,
                    task_id=args.task_id,
                    flow_id=args.flow_id,
                    scenario=args.scenario,
                    variant=args.variant,
                    command_argv=command_argv,
                )
            elif args.development_command == "daily-row-claim":
                output = development_session_daily_row_claim(
                    mode=args.mode,
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
                    runtime_scope=args.runtime_scope,
                    account_id=args.account_id,
                    server_id=args.server_id,
                    reset_id=args.reset_id,
                    identity_evidence=args.identity_evidence,
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
    if args.command == "conduct":
        try:
            output = conduct_flow(
                args.flow_id,
                live=bool(args.live),
                yes=bool(args.yes),
                max_inputs=(
                    int(args.max_inputs) if args.max_inputs is not None else None
                ),
                summary_path=args.summary,
                state_root=args.state_root,
                runtime_scope=args.runtime_scope,
                account_id=args.account_id,
                server_id=args.server_id,
                reset_id=args.reset_id,
                identity_evidence=args.identity_evidence,
            )
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
                        "command": "conduct",
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
    raise OperatorError("unsupported pnsctl command")


if __name__ == "__main__":
    raise SystemExit(main())
