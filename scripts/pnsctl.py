#!/usr/bin/env python3
"""Reproducible operator interface for local BlueStacks development.

Only this checked-in interface owns the routine worker, private ADB, validation, evidence, and
cleanup commands for the local BlueStacks development runtime.
"""

from __future__ import annotations

import argparse
from contextlib import nullcontext
from dataclasses import asdict
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
from tasks.runtime_identity import (  # noqa: E402
    BLUESTACKS_ADB,
    BLUESTACKS_PACKAGE,
    BLUESTACKS_SERIAL,
    resource_fixed_runtime_binding,
)

# This is deliberately a narrow admission check for the bootstrap command.  A
# launcher-looking window is not enough: only these verified BlueStacks Home
# packages may be used as the safe source for starting the installed game.
BLUESTACKS_LAUNCHER_PACKAGES = frozenset(
    {
        "com.bluestacks.launcher",
        "com.bluestacks.gamecenter",
        "com.uncube.launcher3",
    }
)
NAVIGATION_ASSET_ROOT = "tasks/assets/navigation/800x1280"
BLUESTACKS_NATIVE_WIDTH = 800
BLUESTACKS_NATIVE_HEIGHT = 1280
BLUESTACKS_ARTIFACT_ROOT = REPO_ROOT / ".local-captures" / "flow-delivery"
DEVELOPMENT_SESSION_ROOT = REPO_ROOT / ".local-captures" / "development-sessions"
RESOURCE_AUTHORIZATION_FRESHNESS_SECONDS = 600.0
DEVELOPMENT_CHECKPOINT_PATHS = (
    REPO_ROOT / "BACKLOG.md",
    REPO_ROOT / "tasks" / "flow_delivery_queue.json",
    REPO_ROOT / "CURRENT_HANDOFF.md",
)
RECRUITMENT_MAINTENANCE_FLOW_ID = "RECRUITMENT-FREE-ATTEMPT-MAINTENANCE"
CAMPAIGN_AP_FLOW_ID = "CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY"
# Default development-session input ceiling per registered flow (12 when unlisted).
_DEFAULT_MAX_INPUTS = {
    "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION": 16,
    "BIOENHANCER-FREE-RESEARCH-BLUESTACKS-INTEGRATION": 8,
    "PERSONAL-MIGHT-PRAISE-BLUESTACKS-INTEGRATION": 8,
    "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION": 4,
    "SUPPLY-DEPOT-BLUESTACKS-INTEGRATION": 10,
    "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION": 10,
    "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION": 24,
    RECRUITMENT_MAINTENANCE_FLOW_ID: 12,
    "CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY": 16,
    "TROOP-TRAINING-END-TO-END-CONSOLIDATION": 32,
}
FLOW_DELIVERY_QUEUE = REPO_ROOT / "tasks" / "flow_delivery_queue.json"
FLOW_DELIVERY_LEASE = REPO_ROOT / ".local-orchestrator" / "flow-delivery-lease.json"
FLOW_DELIVERY_BLUESTACKS_REGISTRY = (
    REPO_ROOT / "tasks" / "flow_delivery_bluestacks_registry.json"
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
        from scripts.flow_delivery_bioenhancer_bluestacks import (
            register as register_bioenhancer,
        )
    except ImportError:
        from flow_delivery_bioenhancer_bluestacks import (
            register as register_bioenhancer,
        )
    try:
        from scripts.flow_delivery_personal_might_bluestacks import (
            register as register_personal_might,
        )
    except ImportError:
        from flow_delivery_personal_might_bluestacks import (
            register as register_personal_might,
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
        from scripts.flow_delivery_recruitment_bluestacks import (
            register as register_recruitment,
        )
    except ImportError:
        from flow_delivery_recruitment_bluestacks import (
            register as register_recruitment,
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
    register_personal_might(
        _BLUESTACKS_FLOW_RUNNERS,
        _BLUESTACKS_EVIDENCE_VALIDATORS,
        _BLUESTACKS_RECOVERY_HANDLERS,
    )
    register_daily_resource_item(
        _BLUESTACKS_FLOW_RUNNERS,
        _BLUESTACKS_EVIDENCE_VALIDATORS,
        _BLUESTACKS_RECOVERY_HANDLERS,
    )
    register_recruitment(
        _BLUESTACKS_FLOW_RUNNERS,
        _BLUESTACKS_EVIDENCE_VALIDATORS,
        _BLUESTACKS_RECOVERY_HANDLERS,
    )


_register_checked_in_bluestacks_handlers()


class OperatorError(RuntimeError):
    pass


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
        if not isinstance(contract, dict):
            raise OperatorError("BlueStacks flow registry contract is incomplete")
        if set(contract) != required or any(
            not isinstance(contract[field], str) or not contract[field].strip()
            for field in required
        ):
            raise OperatorError("BlueStacks flow registry contract is incomplete")
        if contract["consequence_class"] not in {"navigation_only", "consequential"}:
            raise OperatorError("BlueStacks flow registry consequence class is invalid")
    return registry["flows"]


def _implemented_bluestacks_flow_ids() -> tuple[str, ...]:
    """Flow IDs whose registry route has all three handlers bound in code.

    This is the single source for the flow IDs ``pnsctl`` offers and accepts, so
    a planned or contract-only flow can never be selectable before it has a
    runner, evidence validator, and recovery handler.
    """

    return tuple(
        flow_id
        for flow_id, route in _load_bluestacks_flow_registry().items()
        if route["runner"] in _BLUESTACKS_FLOW_RUNNERS
        and route["evidence_validator"] in _BLUESTACKS_EVIDENCE_VALIDATORS
        and route["recovery_handler"] in _BLUESTACKS_RECOVERY_HANDLERS
    )


BLUESTACKS_FLOW_IDS = _implemented_bluestacks_flow_ids()


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


def _resolve_installed_game_activity() -> str:
    """Resolve the installed P&S launcher activity with an exact package bind."""

    raw = str(
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
            BLUESTACKS_PACKAGE,
        )
    ).strip()
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    resolved_activity = lines[-1] if lines else ""
    if not resolved_activity.startswith(f"{BLUESTACKS_PACKAGE}/"):
        raise OperatorError(
            "installed Puzzles & Survival launcher activity was not resolved"
        )
    return resolved_activity


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
    if focused_package != BLUESTACKS_PACKAGE:
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
    if focused_package != BLUESTACKS_PACKAGE:
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


def _development_launcher_observation() -> tuple[dict[str, Any], bytes]:
    """Capture a native frame while admitting the launcher as a source state.

    This is intentionally separate from the ordinary development observation:
    ordinary route work must already be in P&S, while crash recovery may only
    start from the positively identified BlueStacks launcher.
    """

    state = str(_run_fixed_bluestacks_adb("get-state")).strip()
    frame = _run_fixed_bluestacks_adb("exec-out", "screencap", "-p", binary=True)
    if (
        not isinstance(frame, bytes)
        or frame[:8] != b"\x89PNG\r\n\x1a\n"
        or len(frame) < 24
    ):
        raise OperatorError("launch-game observation did not receive a valid PNG frame")
    width = int.from_bytes(frame[16:20], "big")
    height = int.from_bytes(frame[20:24], "big")
    focus = str(_run_fixed_bluestacks_adb("shell", "dumpsys", "window"))
    focused_package = _focused_package(focus)
    if state != "device":
        raise OperatorError("approved runtime serial is not in device state")
    if (width, height) != (BLUESTACKS_NATIVE_WIDTH, BLUESTACKS_NATIVE_HEIGHT):
        raise OperatorError("launch-game frame is not native 800x1280")
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
    from scripts.bluestacks_native_runtime import portable_filename_component

    try:
        safe = portable_filename_component(invocation_id, field="development session invocation ID")
    except RuntimeError as exc:
        raise OperatorError(str(exc)) from exc
    return DEVELOPMENT_SESSION_ROOT / safe


class ApplicationStartupError(OperatorError):
    def __init__(self, reason: str, result: Mapping[str, Any]):
        super().__init__(reason)
        self.startup_result = dict(result)


def owner_bound_application_startup(*, runtime_input_lock, checkpoint, session_directory: Path,
                                    flow_id: str | None = None, require_ready: bool = False) -> dict[str, Any]:
    """Observe or launch once using the caller's already-held runtime owner."""
    from scripts.navigation_development_boundary import NavigationBoundaryError, require_canonical_unresolved_clear

    def gate():
        try:
            require_canonical_unresolved_clear()
        except NavigationBoundaryError as exc:
            raise OperatorError(str(exc)) from exc

    def fence():
        runtime_input_lock.assert_held(runtime_input_lock.owner, runtime_input_lock.invocation_id)
        checkpoint()

    fence()
    gate()
    session_directory = Path(session_directory)
    session_directory.mkdir(parents=True, exist_ok=False)
    result = {"status": "unresolved", "session_directory": str(session_directory),
              "serial": BLUESTACKS_SERIAL, "system_launch_count": 0, "game_input_count": 0,
              "input_count": 0, "dispatch": False, "route_ready": False}

    def persist():
        (session_directory / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def capture(label):
        fence()
        observation, frame = _development_launcher_observation()
        fence()
        (session_directory / f"{label}.png").write_bytes(frame)
        return observation, frame

    transport_started = False
    try:
        before, _ = capture("before")
        result.update(before_observation=before, before_frame="before.png")
        persist()
        focused = str(before["foreground_package"])
        if focused == BLUESTACKS_PACKAGE:
            # Existing route owns validation of its current Profile/Chapter context.
            result.update(status="already_foreground", foreground_package=focused,
                          action="observe_existing_game")
            after, _ = capture("after")
            if after["foreground_package"] != BLUESTACKS_PACKAGE:
                raise OperatorError("Puzzles & Survival foreground changed during startup observation")
            result.update(after_observation=after, after_frame="after.png")
            persist()
            return result
        if focused not in BLUESTACKS_LAUNCHER_PACKAGES:
            raise OperatorError(f"launch-game requires the positively identified BlueStacks launcher; focused package was {focused!r}")
        activity = _resolve_installed_game_activity()
        if require_ready:
            immediate, _ = capture("immediate-before")
            if immediate["foreground_package"] != focused:
                raise OperatorError("launcher source changed before application start")
            result.update(immediate_before_observation=immediate, immediate_before_frame="immediate-before.png")
            persist()
        fence()
        gate()
        fence()
        result.update(system_launch_count=1, action="start_checked_in_activity_from_bluestacks_launcher",
                      resolved_activity=activity, transport_status="attempted",
                      launch_intent={"action": "android.intent.action.MAIN",
                                     "category": "android.intent.category.LAUNCHER",
                                     "flags": "0x10000000", "component": activity})
        # Persist the attempt before transport: an exception cannot authorize retry.
        persist()
        fence()
        transport_started = True
        # Match the measured BlueStacks icon intent: MAIN/LAUNCHER + NEW_TASK.
        # Do not add RESET_TASK_IF_NEEDED; this launcher's icon does not use it.
        transport = _run_fixed_bluestacks_adb(
            "shell", "am", "start", "-W", "-a", "android.intent.action.MAIN",
            "-c", "android.intent.category.LAUNCHER", "-f", "0x10000000", "-n", activity,
        )
        result.update(transport_status="returned", transport_result=str(transport))
        persist()
        # Allow cold loading to settle before requiring Home or an owned popup.
        # The same owner/checkpoints remain active and no launch is retried.
        deadline = time.monotonic() + 90.0
        ordinal = 0
        while True:
            fence()
            focus = str(_run_fixed_bluestacks_adb("shell", "dumpsys", "window"))
            fence()
            package = _focused_package(focus)
            if package not in BLUESTACKS_LAUNCHER_PACKAGES and package != BLUESTACKS_PACKAGE:
                unexpected, _ = capture("unexpected-foreground")
                result.update(after_observation=unexpected, after_frame="unexpected-foreground.png")
                persist()
                raise OperatorError(f"launch-game encountered manual or unknown foreground package {package!r}")
            if package == BLUESTACKS_PACKAGE:
                label = "after" if not require_ready else f"readiness-{ordinal:03d}"
                after, frame = capture(label)
                if after["foreground_package"] != BLUESTACKS_PACKAGE:
                    raise OperatorError("Puzzles & Survival foreground was not stable after launch")
                result.update(after_observation=after, after_frame=f"{label}.png", foreground_package=BLUESTACKS_PACKAGE)
                if not require_ready:
                    result.update(status="launched")
                    persist()
                    return result
                from scripts.startup_recovery import classify_startup_frame
                from scripts.startup_normalization import is_clean_home_frame
                import cv2
                import numpy as np
                decoded = cv2.imdecode(np.frombuffer(frame, dtype=np.uint8), cv2.IMREAD_COLOR)
                plan = classify_startup_frame(str(flow_id or ""), frame)
                fence()
                ready = decoded is not None and is_clean_home_frame(decoded)
                fence()
                if (ready or (plan.status in {"recovery_required", "route_owned"}
                             and bool(plan.recovery_owner))):
                    result.update(status="launched", route_ready=True,
                                  readiness="clean_home" if ready else "known_startup_overlay")
                    persist()
                    return result
                ordinal += 1
            if time.monotonic() >= deadline:
                terminal, _ = capture("timeout")
                result.update(after_observation=terminal, after_frame="timeout.png",
                              foreground_package=terminal["foreground_package"])
                raise OperatorError("Puzzles & Survival did not reach a recognized startup surface")
            time.sleep(1.0)
    except Exception as exc:
        if result.get("transport_status") == "attempted" and not transport_started:
            result.update(system_launch_count=0, transport_status="not_attempted")
        result.update(status="unresolved", reason=str(exc))
        try:
            persist()
        except OSError:
            pass
        raise ApplicationStartupError(str(exc), result) from exc


def _cold_restart_game(*, runtime_input_lock, session_directory: Path) -> dict[str, Any]:
    """Explicit operator test: stop only a clean idle game, then reuse startup."""
    from automation_service.state import BotStateManager
    from scripts.navigation_development_boundary import NavigationBoundaryError, require_canonical_unresolved_clear
    from scripts.startup_normalization import is_clean_home_frame
    import cv2
    import numpy as np

    with BotStateManager(read_only=True) as state:
        if Path(state.db_path).resolve() != BotStateManager.DEFAULT_DB_PATH.resolve() or not Path(state.db_path).is_file():
            raise OperatorError("cold restart requires the existing canonical state database")

        def checkpoint():
            runtime_input_lock.assert_held(runtime_input_lock.owner, runtime_input_lock.invocation_id)
            try:
                require_canonical_unresolved_clear()
            except NavigationBoundaryError as exc:
                raise OperatorError(str(exc)) from exc
            if state.get_service_enabled() or state._db.execute(
                "SELECT 1 FROM flow_state WHERE enabled=1"
            ).fetchone():
                raise OperatorError("cold restart requires disabled service and flow controls")
            if state.get_service_lease().owner_instance_id is not None or state._db.execute(
                "SELECT 1 FROM runs WHERE state IN ('CLAIMED','RUNNING','STOP_REQUESTED','RECOVERING')"
            ).fetchone():
                raise OperatorError("cold restart requires no active service operator or run")

        checkpoint()
        session_directory.mkdir(parents=True, exist_ok=False)
        result: dict[str, Any] = {
            "status": "unresolved", "session_directory": str(session_directory),
            "authorization": "Explicit launch-game --cold-restart --live --yes; current user requested cold process restart validation.",
            "system_stop_count": 0, "system_launch_count": 0, "game_input_count": 0,
            "input_count": 0, "cold_stop_verified": False,
        }
        try:
            before, frame = _development_launcher_observation()
            (session_directory / "before.png").write_bytes(frame)
            result.update(before_observation=before, before_frame="before.png")
            decoded = cv2.imdecode(np.frombuffer(frame, dtype=np.uint8), cv2.IMREAD_COLOR)
            if before["foreground_package"] != BLUESTACKS_PACKAGE or decoded is None or not is_clean_home_frame(decoded):
                raise OperatorError("cold restart requires positively recognized clean Home")
            checkpoint()
            activity = _resolve_installed_game_activity()
            immediate, immediate_frame = _development_launcher_observation()
            (session_directory / "immediate-before.png").write_bytes(immediate_frame)
            result.update(immediate_before_observation=immediate, immediate_before_frame="immediate-before.png")
            decoded = cv2.imdecode(np.frombuffer(immediate_frame, dtype=np.uint8), cv2.IMREAD_COLOR)
            if immediate["foreground_package"] != BLUESTACKS_PACKAGE or decoded is None or not is_clean_home_frame(decoded):
                raise OperatorError("clean Home changed before the cold stop")
            checkpoint()
            # Persist the single attempt before transport. An uncertain stop is
            # retained and never retried by this invocation.
            result["system_stop_count"] = 1
            with (session_directory / "stop-attempt.json").open("x", encoding="utf-8") as stream:
                json.dump(result, stream, indent=2, sort_keys=True)
            stop_result = _run_fixed_bluestacks_adb("shell", "am", "force-stop", BLUESTACKS_PACKAGE)
            checkpoint()
            processes = str(_run_fixed_bluestacks_adb("shell", "ps", "-A")).splitlines()
            rows = [line.split() for line in processes[1:] if line.split()]
            if not processes or not rows or processes[0].split()[-1:] != ["NAME"]:
                raise OperatorError("cold stop process observation is unreadable")
            remaining = [row[-1] for row in rows if (
                row[-1] == BLUESTACKS_PACKAGE or row[-1].startswith(BLUESTACKS_PACKAGE + ":")
            )]
            if remaining:
                raise OperatorError("game process remains after the single cold stop")
            stopped, stopped_frame = _development_launcher_observation()
            if stopped["foreground_package"] not in BLUESTACKS_LAUNCHER_PACKAGES:
                raise OperatorError("cold stop did not expose the known BlueStacks launcher")
            (session_directory / "stopped.png").write_bytes(stopped_frame)
            result.update(cold_stop_verified=True, stopped_observation=stopped,
                          stopped_frame="stopped.png", stop_transport_result=str(stop_result),
                          resolved_activity=activity)
            startup = owner_bound_application_startup(
                runtime_input_lock=runtime_input_lock, checkpoint=checkpoint,
                session_directory=session_directory / "startup", flow_id=CAMPAIGN_AP_FLOW_ID,
                require_ready=True,
            )
            result.update(status="cold_restarted", startup=startup,
                          system_launch_count=startup["system_launch_count"],
                          route_ready=startup["route_ready"], readiness=startup.get("readiness"))
        except Exception as exc:
            result.update(reason=f"{type(exc).__name__}: {exc}")
            if isinstance(exc, ApplicationStartupError):
                result.update(startup=exc.startup_result,
                              system_launch_count=exc.startup_result.get("system_launch_count", 0))
            raise ApplicationStartupError(str(exc), result) from exc
        finally:
            with (session_directory / "result.json").open("x", encoding="utf-8") as stream:
                json.dump(result, stream, indent=2, sort_keys=True)
                stream.write("\n")
        return result


def development_session_launch_game(*, live: bool, yes: bool, cold_restart: bool = False) -> str:
    if not live or not yes:
        raise OperatorError("launch-game requires explicit --live --yes")
    from scripts.navigation_development_boundary import RuntimeInputLock
    invocation_id = f"launch-game-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    owner = "pnsctl-development-session:launch-game"
    with RuntimeInputLock(owner=owner, invocation_id=invocation_id) as lock:
        if cold_restart:
            result = _cold_restart_game(runtime_input_lock=lock,
                session_directory=_development_session_directory(invocation_id))
        else:
            result = owner_bound_application_startup(runtime_input_lock=lock, checkpoint=lambda: None,
                session_directory=_development_session_directory(invocation_id))
    return json.dumps(result, sort_keys=True)


def _run_shared_startup_recovery(
    *,
    flow_id: str,
    task_id: str,
    session_directory: Path,
    max_inputs: int,
    recovery_scope: str | None,
    expected_source_sha256: str | None = None,
    runtime_holder: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recover the exact shared startup surface within the active flow boundary."""
    from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
    from scripts.startup_recovery import classify_startup_frame, recover_known_startup_overlay

    runtime = LocalBlueStacksRuntime.connect(
        adb=str(BLUESTACKS_ADB),
        serial=BLUESTACKS_SERIAL,
        output_directory=session_directory / "startup-recovery",
        workflow=f"{flow_id.lower()}-startup-recovery",
        execute=True,
    )
    if runtime_holder is not None:
        runtime_holder["runtime"] = runtime
    runtime.max_inputs = min(runtime.max_inputs, max_inputs, 2)
    actions: list[dict[str, Any]] = []
    seen: set[str] = set()
    while len(actions) < 2:
        result = recover_known_startup_overlay(
            runtime,
            task_id=task_id,
            # This proves only a retained, nonblack native successor. The
            # active route must recognize its own context before acting.
            recognize_successor=lambda frame: bool(
                frame.shape == (1280, 800, 3) and frame.any()
            ),
            successor_state="RETAINED_STARTUP_SUCCESSOR",
            recovery_scope=recovery_scope,
            expected_source_sha256=expected_source_sha256,
        )
        item = result.to_mapping()
        actions.append(item)
        identity = str(result.popup_identity or "")
        seen.add(identity)
        if result.status not in {"surface_dismissed_successor_captured", "recovered"}:
            break
        post = runtime.capture("startup-recovery-chain-observation")
        plan = classify_startup_frame(flow_id, post.png)
        if plan.status == "clear" or plan.status == "route_owned":
            break
        if (plan.status != "recovery_required" or plan.popup_identity in seen
                or runtime.input_count >= runtime.max_inputs):
            item = dict(item, status="evidence_required", reason=(
                "startup_successor_blocked_or_repeated_or_budget_exhausted"
            ))
            break
        expected_source_sha256 = post.sha256
    payload = dict(item)
    payload["actions"] = actions
    payload["flow_id"] = flow_id
    payload["recovery_input_count"] = sum(int(action["input_count"]) for action in actions)
    payload["input_count"] = payload["recovery_input_count"]
    payload["route_input_count"] = 0
    payload["total_input_count"] = payload["recovery_input_count"]
    return payload

def _canonical_action_identity(row: Mapping[str, Any]) -> str | None:
    """Return the identity recorded by the action/input ledger, if present."""

    for field in ("action_key", "label"):
        value = row.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None

def _action_transport_attempts(row: Mapping[str, Any]) -> int:
    attempted = row.get("transport_attempted_count", 1)
    if type(attempted) is not int or attempted < 1:
        raise OperatorError("action ledger transport attempt count is invalid")
    return attempted


def _startup_recovery_action_rows(
    result: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Project one startup recovery action without collapsing its input budget."""

    if not isinstance(result, Mapping):
        return []
    actions = result.get("actions")
    if isinstance(actions, list):
        rows = [row for action in actions for row in _startup_recovery_action_rows(action)]
        for ordinal, row in enumerate(rows):
            row["ordinal"] = ordinal
        return rows
    try:
        input_count = int(
            result.get("input_count")
            or result.get("recovery_input_count")
            or 0
        )
    except (TypeError, ValueError):
        return []
    if input_count <= 0:
        return []
    identity = _canonical_action_identity(result)
    if identity is None:
        raise OperatorError("startup recovery transport is missing an action identity")
    status = str(result.get("status") or "unknown")
    semantic_status = (
        "confirmed"
        if status in {"surface_dismissed_successor_captured", "recovered"}
        else "unknown"
    )
    after_sha256 = result.get("after_sha256")
    return [
        {
            "ordinal": 0,
            "action_class": "navigation",
            "action_key": identity,
            "target_identity": (
                result.get("safe_exit_target_identity")
                or result.get("popup_identity")
            ),
            "before_sha256": result.get("before_sha256"),
            "after_sha256": after_sha256,
            "after_path": None,
            "transport_attempted": True,
            "transport_attempted_count": input_count,
            "semantic_status": semantic_status,
            "semantic_completed": semantic_status == "confirmed",
            "semantic_reason": result.get("reason"),
            "reason": result.get("reason") or "startup recovery semantic outcome is unknown",
            "effect_reconciliation_required": semantic_status != "confirmed",
            "capture_status": (
                "post_captured" if after_sha256 else "post_capture_missing"
            ),
            "status": (
                "completed" if semantic_status == "confirmed" else "effect_reconciliation_required"
            ),
            "recovery": True,
        }
    ]


def _unique_action_rows(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Keep one latest canonical row per action identity."""

    unique: list[dict[str, Any]] = []
    positions: dict[str, int] = {}
    for row in rows:
        identity = _canonical_action_identity(row)
        if identity is None:
            raise OperatorError("action ledger row is missing an action identity")
        replacement = dict(row)
        previous_position = positions.get(identity)
        if previous_position is None:
            positions[identity] = len(unique)
            unique.append(replacement)
            continue
        previous = unique[previous_position]
        previous_status = previous.get("semantic_status", previous.get("status"))
        replacement_status = replacement.get("semantic_status", replacement.get("status"))
        if previous_status == "completed":
            previous_status = "confirmed"
        if replacement_status == "completed":
            replacement_status = "confirmed"
        if (
            previous_status in {"confirmed", "failed_confirmed"}
            and previous_status != replacement_status
        ):
            raise OperatorError("action ledger contains conflicting terminal outcomes")
        replacement["transport_attempted_count"] = max(
            _action_transport_attempts(previous), _action_transport_attempts(replacement)
        )
        unique[previous_position] = replacement
    return unique


def _compact_development_action_results(
    event_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Project canonical dispatch rows without treating captures as success.

    ``events.jsonl`` is an evidence projection, not a second action ledger.
    Only executable dispatch rows create actions.  A later capture records
    post-capture provenance; only an explicit reconciliation row can establish
    semantic completion.
    """

    dispatches: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    pending: str | None = None
    reconciliations: dict[str, Mapping[str, Any]] = {}
    for event in event_rows:
        kind = event.get("type")
        if kind == "dispatch":
            if event.get("execute") is False or event.get("transport_attempted") is False:
                pending = None
                continue
            identity = _canonical_action_identity(event)
            if identity is None:
                raise OperatorError("executable dispatch is missing an action identity")
            if identity not in dispatches:
                dispatches[identity] = {
                    "ordinal": len(order) + 1,
                    "action_class": "ordinary_development",
                    "action_key": identity,
                    "target_identity": event.get("target_identity"),
                    "before_sha256": event.get("source_sha256"),
                    "after_sha256": None,
                    "after_path": None,
                    "transport_attempted": True,
                    "transport_attempted_count": _action_transport_attempts(event),
                }
                order.append(identity)
            else:
                dispatches[identity]["transport_attempted_count"] = max(
                    dispatches[identity]["transport_attempted_count"],
                    _action_transport_attempts(event),
                )
            pending = identity
        elif kind == "capture" and pending is not None:
            action = dispatches[pending]
            if action["after_sha256"] is None:
                action["after_sha256"] = event.get("sha256")
                action["after_path"] = event.get("path")
            pending = None
        elif kind == "reconcile":
            identity = _canonical_action_identity(event)
            if identity is None:
                raise OperatorError("reconciliation is missing an action identity")
            previous = reconciliations.get(identity)
            if (
                previous is not None
                and previous.get("status") in {"confirmed", "failed_confirmed"}
                and event.get("status") != previous.get("status")
            ):
                raise OperatorError("action ledger contains conflicting terminal reconciliations")
            reconciliations[identity] = event

    actions: list[dict[str, Any]] = []
    for identity in order:
        action = dispatches[identity]
        reconciliation = reconciliations.get(identity)
        semantic_status = (
            str(reconciliation.get("status") or "unknown")
            if reconciliation is not None
            else "unknown"
        )
        if semantic_status not in {"confirmed", "failed_confirmed", "unresolved"}:
            semantic_status = "unknown"
        action["semantic_status"] = semantic_status
        action["semantic_completed"] = semantic_status == "confirmed"
        action["semantic_reason"] = (
            reconciliation.get("reason") if reconciliation is not None else None
        )
        action["reason"] = action["semantic_reason"] or "semantic postcondition is not confirmed"
        action["effect_reconciliation_required"] = semantic_status in {"unknown", "unresolved"}
        action["capture_status"] = (
            "post_captured"
            if action["after_sha256"] is not None
            else "post_capture_missing"
        )
        action["status"] = (
            "completed" if semantic_status == "confirmed"
            else "effect_reconciliation_required" if action["effect_reconciliation_required"]
            else "unknown"
        )
        actions.append(action)
    return actions

def _retained_transport_count(event_rows: Sequence[Mapping[str, Any]]) -> int:
    """Count canonical transport attempts once per action identity."""

    attempts_by_identity: dict[str, int] = {}
    for row in event_rows:
        kind = row.get("type")
        if kind is not None:
            if kind != "dispatch" or row.get("execute") is False:
                continue
            if row.get("transport_attempted") is False:
                continue
        else:
            # DevelopmentSession action rows are the canonical input ledger.
            if row.get("transport_attempted") is False:
                continue
            status = str(row.get("status") or "").strip().lower()
            if status in {"failed_before_dispatch", "not_dispatched", "cancelled"}:
                continue
        identity = _canonical_action_identity(row)
        if identity is None:
            raise OperatorError("retained transport is missing an action identity")
        attempts_by_identity[identity] = max(
            attempts_by_identity.get(identity, 0), _action_transport_attempts(row)
        )
    return sum(attempts_by_identity.values())


def _retained_semantic_completed_count(
    action_rows: Sequence[Mapping[str, Any]],
) -> int:
    """Count explicit positive semantic outcomes once per canonical action."""

    semantic_by_identity: dict[str, str] = {}
    for row in action_rows:
        if row.get("type") not in {None, "dispatch", "reconcile"}:
            continue
        identity = _canonical_action_identity(row)
        if identity is None:
            raise OperatorError("semantic action ledger row is missing an action identity")
        semantic_status = row.get("semantic_status")
        if semantic_status is None:
            if row.get("type") is not None:
                # A capture after transport is not a semantic result.
                continue
            semantic_status = row.get("status")
        semantic_by_identity[identity] = str(semantic_status or "").strip().lower()
    return sum(
        status in {"confirmed", "completed"}
        for status in semantic_by_identity.values()
    )


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
    from scripts.delegated_runtime_receipts import (
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
            raise OperatorError(
                f"delegated observation {label} input count is not zero"
            )
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
            raise OperatorError(
                f"daily row reconnaissance receipt {field} is not frozen"
            )
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
        raise OperatorError(
            "daily row reconnaissance receipt action bindings are not frozen"
        )
    binding = receipt.get("evidence_result_binding")
    if (
        not isinstance(binding, Mapping)
        or binding.get("result_identity") != DAILY_ROW_RECON_RESULT_IDENTITY
    ):
        raise OperatorError("daily row reconnaissance result identity is not frozen")
    command = receipt.get("command_argv")
    if (
        not isinstance(command, list)
        or len(command) != 16
        or command[:3]
        != [
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
    resolved = (
        candidate if candidate.is_absolute() else session_directory / candidate
    ).resolve()
    try:
        resolved.relative_to(session_directory.resolve())
    except ValueError as exc:
        raise OperatorError(
            "daily row reconnaissance artifact escaped its session"
        ) from exc
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
        raise OperatorError(
            "daily row reconnaissance required native frames are missing"
        )

    def validate_frame(name: str, reference: object) -> None:
        if not isinstance(reference, Mapping):
            raise OperatorError(
                f"daily row reconnaissance frame reference is malformed: {name}"
            )
        path = _daily_recon_artifact_path(session_directory, reference.get("path"))
        declared_hash = reference.get("sha256")
        if not isinstance(declared_hash, str):
            raise OperatorError(
                f"daily row reconnaissance frame hash is missing: {name}"
            )
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
            raise OperatorError(
                "daily row reconnaissance poll action identity is invalid"
            )
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
        raise OperatorError(
            "daily row reconnaissance action records are not completed navigation"
        )
    if payload.get("input_count") != spec["max_inputs"]:
        raise OperatorError("daily row reconnaissance input count is not frozen")
    if (
        payload.get("resource_affecting_inputs") != 0
        or payload.get("combat_confirmations") != 0
    ):
        raise OperatorError("daily row reconnaissance contains a forbidden budget")
    terminal = payload.get("recognitions", {}).get("daily_terminal")
    if not isinstance(terminal, Mapping) or terminal.get("state") != "DAILY_SELECTED":
        raise OperatorError(
            "daily row reconnaissance terminal semantics are not selected Daily"
        )
    source = payload.get("recognitions", {}).get("source")
    expected_source = "HOME" if variant == DAILY_ROW_RECON_VARIANT else "QUEST"
    if not isinstance(source, Mapping) or source.get("state") != expected_source:
        raise OperatorError(
            "daily row reconnaissance source semantics are not variant-bound"
        )
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
        raise OperatorError(
            "daily row reconnaissance event log dispatch count is not frozen"
        )
    if [
        row.get("action_key") or row.get("target_identity") for row in dispatches
    ] != list(spec["action_identities"]):
        raise OperatorError(
            "daily row reconnaissance event action identity order is invalid"
        )


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
        raise OperatorError(
            "daily row reconnaissance requires complete receipt bindings"
        )
    if task_id != DAILY_ROW_RECON_TASK_ID or flow_id != DAILY_ROW_RECON_FLOW_ID:
        raise OperatorError(
            "daily row reconnaissance task or flow binding is not frozen"
        )
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
    from scripts.delegated_runtime_receipts import DelegatedRuntimeReceiptController

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
                payload["runtime_session_directory"] = str(runtime_relative).replace(
                    "\\", "/"
                )
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
            raise OperatorError(
                "daily row reconnaissance ownership release is unproven"
            )
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
DAILY_ROW_CLAIM_DISMISS_VIP_RESULT_IDENTITY = "daily-row-claim:popup-dismiss:vip-points"
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
    if (
        not isinstance(binding, Mapping)
        or binding.get("result_identity") != spec["result_identity"]
    ):
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
        return isinstance(template, Mapping) and template.get("recognized") is True

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
        if (
            annotated.is_symlink()
            or not annotated.is_file()
            or annotated.stat().st_size == 0
        ):
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
            raise OperatorError(
                "Daily row Claim canary action identity order is invalid"
            )
        if any(
            not isinstance(row, Mapping) or row.get("status") != "completed"
            for row in actions
        ):
            raise OperatorError(
                "Daily row Claim canary action records are not completed"
            )
        claim = payload.get("claim")
        if not isinstance(claim, Mapping) or not claim.get(
            "annotated_immediate_before"
        ):
            raise OperatorError(
                "Daily row Claim annotated immediate-before overlay is missing"
            )
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
        annotated = (
            session_directory / str(claim["annotated_immediate_before"])
        ).resolve()
        try:
            annotated.relative_to(session_directory.resolve())
        except ValueError as exc:
            raise OperatorError(
                "Daily row Claim annotated overlay escaped the session"
            ) from exc
        if (
            annotated.is_symlink()
            or not annotated.is_file()
            or annotated.stat().st_size == 0
        ):
            raise OperatorError(
                "Daily row Claim annotated immediate-before overlay is unsafe"
            )
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
                raise OperatorError(f"Daily row Claim {name} is not selected Daily")
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
                raise OperatorError(f"Daily return-home {name} is not selected Daily")
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
    from scripts.delegated_runtime_receipts import DelegatedRuntimeReceiptController
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
                relative = runtime_session.resolve().relative_to(
                    session_directory.resolve()
                )
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
            getattr(
                getattr(getattr(session, "_ownership", None), "lock", None),
                "held",
                True,
            )
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
            raise OperatorError(
                "delegated reconnaissance observation requires max_inputs=0"
            )
        values = (agent_identity, task_id, flow_id, scenario, variant, command_argv)
        if any(value is None for value in values):
            raise OperatorError(
                "delegated observation requires complete receipt bindings"
            )
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
                raise OperatorError(
                    "delegated observation ownership release is unproven"
                )
            if _checkpoint_hashes() != before:
                raise OperatorError(
                    "delegated observation mutated a checkpoint artifact"
                )
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
                    ownership_released=_delegated_observation_ownership_released(
                        session
                    ),
                )
            except BaseException as artifact_error:
                raise exc from artifact_error
            raise
        return json.dumps(persisted_result, sort_keys=True)
    if max_inputs < 0:
        raise OperatorError("ordinary observation requires max_inputs >= 0")
    invocation_id = f"observe-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    session_directory = _development_session_directory(invocation_id)
    before = _checkpoint_hashes()
    session: Any | None = None
    observation: Mapping[str, Any] | None = None
    result: dict[str, Any] = {
        "status": "evidence_required",
        "session_directory": str(session_directory),
        "observation": None,
        "input_count": 0,
        "dispatch": False,
        "lifecycle_state_created": False,
        "ownership_released": False,
    }

    def persist_terminal_artifacts(
        status: str,
        *,
        ownership_released: bool,
        blocker: str | None = None,
    ) -> dict[str, Any]:
        artifact = {
            **result,
            "status": status,
            "observation": observation,
            "input_count": 0,
            "lifecycle_state_created": False,
            "ownership_released": ownership_released,
        }
        if blocker:
            artifact["error"] = blocker
        summary: dict[str, Any] = {}
        summary_path = session_directory / "summary.json"
        if summary_path.is_file() and not summary_path.is_symlink():
            try:
                prior = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                prior = {}
            if isinstance(prior, dict):
                summary.update(prior)
        summary.update(
            {
                "status": status,
                "input_count": 0,
                "action_count": 0,
                "dispatch": False,
                "ownership_released": ownership_released,
                "lifecycle_state_created": False,
            }
        )
        if blocker:
            summary["blocker"] = blocker
            summary["next_action"] = "repair the reported observation evidence failure"
        (session_directory / "result.json").write_text(
            json.dumps(artifact, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        summary_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return artifact

    with DevelopmentSession(
        owner="pnsctl-development-observe",
        invocation_id=invocation_id,
        session_directory=session_directory,
        max_inputs=max_inputs,
        allow_zero_inputs=(max_inputs == 0),
    ) as active_session:
        session = active_session
        active_session.terminal_status = "evidence_required"
        observation, frame = _development_runtime_observation()
        (session_directory / "observe.png").write_bytes(frame)
        result["observation"] = observation
    ownership_released = _delegated_observation_ownership_released(session)
    checkpoint_unchanged = _checkpoint_hashes() == before
    blocker: str | None = None
    if not ownership_released:
        blocker = "ordinary observation ownership release is unproven"
    elif not checkpoint_unchanged:
        blocker = "ordinary observation mutated a persistent checkpoint artifact"
    if blocker is not None:
        persist_terminal_artifacts(
            "evidence_required",
            ownership_released=ownership_released,
            blocker=blocker,
        )
        raise OperatorError(blocker)
    if session is not None:
        session.terminal_status = "observed"
    result = persist_terminal_artifacts(
        "observed",
        ownership_released=True,
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


def _resource_wall_clock(
    wall_clock: Callable[[], datetime] | None = None,
) -> datetime:
    value = datetime.now(timezone.utc) if wall_clock is None else wall_clock()
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise OperatorError(
            "Resource authorization wall clock must be timezone-aware UTC"
        )
    try:
        return value.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError) as exc:
        raise OperatorError(
            "Resource authorization wall clock must be timezone-aware UTC"
        ) from exc


def _load_resource_daily_reset_authority() -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the checked-in product authority before deriving Resource reset bounds."""

    from tasks.product_authority import (
        ProductAuthorityError,
        get_daily_reset_policy,
        load_product_authority,
    )

    try:
        authority = load_product_authority()
        policy = get_daily_reset_policy(authority)
    except ProductAuthorityError as exc:
        raise OperatorError(
            "Resource product authority or static UTC reset policy is invalid"
        ) from exc
    return authority, policy


def _resource_deadline_evidence(
    payload: Mapping[str, Any],
) -> tuple[str, datetime]:
    """Validate the static UTC reset payload without consulting runtime visuals."""

    from tasks.runtime_identity import derive_static_utc_reset

    authority, reset_policy = _load_resource_daily_reset_authority()
    if not isinstance(payload, Mapping):
        raise OperatorError("Resource static reset payload is malformed")
    deadline_identity = payload.get(
        "reset_identity_id",
        payload.get("deadline_identity", payload.get("reset_deadline_identity")),
    )
    normalized = payload.get(
        "reset_deadline_utc",
        payload.get("normalized_deadline_utc"),
    )
    start_value = payload.get("reset_start_utc")
    if not isinstance(deadline_identity, str) or not deadline_identity.strip():
        raise OperatorError("Resource reset deadline identity is missing")
    if not isinstance(normalized, str) or not normalized.strip():
        raise OperatorError("Resource reset deadline is missing")
    if not isinstance(start_value, str) or not start_value.strip():
        raise OperatorError("Resource reset start is missing")
    deadline = _resource_identity_timestamp(normalized, "Resource reset deadline")
    start = _resource_identity_timestamp(start_value, "Resource reset start")
    if (
        deadline_identity != f"reset-deadline:{normalized}"
        or deadline != start + timedelta(days=1)
        or start.hour != 0
        or start.minute != 0
        or start.second != 0
        or start.microsecond != 0
        or payload.get("recurrence_class") != "daily_reset"
        or payload.get("recurrence_interval_seconds")
        != reset_policy["interval_seconds"]
        or payload.get("recurrence_interval_hours") != 24
        or payload.get("reset_timezone") != reset_policy["timezone"]
        or payload.get("reset_time") != reset_policy["reset_time"]
        or payload.get("product_authority_revision") != authority["authority_revision"]
        or payload.get("product_authority_digest") != authority["authority_digest"]
        or payload.get("product_policy_id") != reset_policy["policy_id"]
        or payload.get("reset_policy_id") != reset_policy["policy_id"]
        or payload.get("assurance") != "fixed_runtime_binding_static_utc_reset"
        or payload.get("identity_semantics")
        != "fixed_runtime_binding_plus_static_utc_reset"
    ):
        raise OperatorError("Resource reset payload is not the static UTC daily rule")
    evaluated_value = payload.get("_evaluated_utc", payload.get("evaluated_utc"))
    if evaluated_value is not None:
        evaluated = _resource_identity_timestamp(
            evaluated_value,
            "Resource reset evaluation timestamp",
        )
        try:
            expected = derive_static_utc_reset(evaluated)
        except ValueError as exc:
            raise OperatorError(
                "Resource reset evaluation timestamp is invalid"
            ) from exc
        if (
            expected.reset_identity_id != deadline_identity
            or expected.reset_start_utc != start
            or expected.reset_deadline_utc != deadline
        ):
            raise OperatorError(
                "Resource reset payload does not match its UTC wall-clock sample"
            )
    return deadline_identity, deadline


def _produce_resource_runtime_identity(
    *,
    session: Any,
    wall_clock: Callable[[], datetime] | None = None,
    return_deadline_evidence: bool = False,
):
    """Produce Resource identity inside the already-entered DevelopmentSession."""

    from tasks.runtime_identity import (
        RuntimeIdentityAssurance,
        derive_resource_runtime_identity,
        derive_static_utc_reset,
    )

    if session is None:
        raise OperatorError("Resource production identity requires the current session")
    owner = str(getattr(session, "owner", "") or "")
    invocation_id = str(getattr(session, "invocation_id", "") or "")
    if not owner or not invocation_id:
        raise OperatorError(
            "Resource production identity requires the current session binding"
        )
    binding = resource_fixed_runtime_binding()
    evaluated = _resource_wall_clock(wall_clock)
    authority, reset_policy = _load_resource_daily_reset_authority()
    try:
        window = derive_static_utc_reset(evaluated)
        identity = derive_resource_runtime_identity(
            binding,
            evaluated,
            authorization_freshness_seconds=RESOURCE_AUTHORIZATION_FRESHNESS_SECONDS,
            evidence_refs=(
                "identity-source:fixed-runtime-binding",
                "identity-source:static-utc-midnight-reset",
                f"product-authority-revision:{authority['authority_revision']}",
                f"product-authority-digest:{authority['authority_digest']}",
                f"product-policy-id:{reset_policy['policy_id']}",
                f"session-owner:{owner}",
                f"session-invocation:{invocation_id}",
            ),
        )
    except (TypeError, ValueError) as exc:
        raise OperatorError(f"Resource production identity denied: {exc}") from exc
    deadline_payload: dict[str, Any] = {
        "reset_identity_id": window.reset_identity_id,
        "deadline_identity": window.reset_identity_id,
        "reset_deadline_identity": window.reset_identity_id,
        "reset_start_utc": window.reset_start_text,
        "reset_deadline_utc": window.reset_deadline_text,
        "normalized_deadline_utc": window.reset_deadline_text,
        "evaluated_utc": window.evaluated_utc.isoformat().replace("+00:00", "Z"),
        "_evaluated_utc": window.evaluated_utc.isoformat().replace("+00:00", "Z"),
        "authorization_expires_utc": identity.expires_utc,
        "recurrence_class": "daily_reset",
        "recurrence_interval_seconds": reset_policy["interval_seconds"],
        "recurrence_interval_hours": 24,
        "reset_timezone": reset_policy["timezone"],
        "reset_time": reset_policy["reset_time"],
        "product_authority_revision": authority["authority_revision"],
        "product_authority_digest": authority["authority_digest"],
        "product_policy_id": reset_policy["policy_id"],
        "reset_policy_id": reset_policy["policy_id"],
        "assurance": identity.assurance.value,
        "identity_semantics": "fixed_runtime_binding_plus_static_utc_reset",
        "runtime_scope": binding.runtime_scope,
        "account_id": binding.account_id,
        "server_id": binding.server_id,
    }
    if (
        identity.assurance
        is not RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_STATIC_UTC_RESET
    ):
        raise OperatorError("Resource identity assurance is not static UTC")
    _resource_deadline_evidence(deadline_payload)
    if return_deadline_evidence:
        return identity, deadline_payload
    return identity


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
        raise OperatorError(
            "canonical Resource SafetyStore cannot be inspected read-only"
        ) from exc
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
        raise OperatorError(
            "canonical Resource SafetyStore schema is unreadable"
        ) from exc
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
    path = (
        Path(store_path)
        if store_path is not None
        else Path(CANONICAL_ACTION_STORE_PATH)
    )
    _inspect_admitted_resource_store(path, fixed_canonical=not injected)
    factory = store_factory or SafetyStore
    try:
        store = factory(path)
    except (OSError, SchemaVersionError) as exc:
        raise OperatorError(
            "canonical Resource SafetyStore v4 could not be opened"
        ) from exc
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
    """Bind one Resource reset to the exact static UTC midnight interval."""

    from safe_action_core.resource_effect_authority import ResourceResetIdentity
    from tasks.runtime_identity import (
        RuntimeIdentityAssurance,
        VerifiedRuntimeIdentity,
    )

    if type(verified_identity) is not VerifiedRuntimeIdentity:
        raise OperatorError("Resource runtime identity is missing or not verified")
    if (
        verified_identity.assurance
        is not RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_STATIC_UTC_RESET
    ):
        raise OperatorError(
            "Resource runtime identity is not FIXED_RUNTIME_BINDING_STATIC_UTC_RESET"
        )
    deadline_identity, deadline = _resource_deadline_evidence(deadline_payload)
    reset_start = _resource_identity_timestamp(
        str(getattr(verified_identity, "reset_start_utc", "") or ""),
        "Resource runtime identity reset_start_utc",
    )
    identity_deadline = _resource_identity_timestamp(
        str(getattr(verified_identity, "reset_deadline_utc", "") or ""),
        "Resource runtime identity reset_deadline_utc",
    )
    if (
        verified_identity.reset_id != deadline_identity
        or identity_deadline != deadline
        or deadline_payload.get("reset_start_utc")
        != reset_start.isoformat().replace("+00:00", "Z")
    ):
        raise OperatorError(
            "Resource runtime identity does not match the static UTC reset"
        )
    if not verified_identity.observed_utc or not verified_identity.expires_utc:
        raise OperatorError(
            "Resource runtime identity freshness evidence is incomplete"
        )
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
    if reset_start + timedelta(days=1) != deadline or evaluated < reset_start:
        raise OperatorError("Resource reset is not the active static UTC window")
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
        reset_start_utc=(deadline - timedelta(days=1))
        .isoformat()
        .replace("+00:00", "Z"),
        reset_deadline_utc=deadline.isoformat().replace("+00:00", "Z"),
        assurance=RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_STATIC_UTC_RESET.value,
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
        ResourceAuthorizationWindow,
        ResourceAuthorizationWindowError,
    )
    from scripts.navigation_development_boundary import DevelopmentSessionError

    if not hasattr(session, "runtime_input_lock"):
        raise OperatorError(
            "pnsctl DevelopmentSession cannot expose its held runtime lock"
        )
    try:
        runtime_lock = session.runtime_input_lock
    except DevelopmentSessionError as exc:
        raise OperatorError(
            "Resource authority requires the entered pnsctl DevelopmentSession"
        ) from exc
    owner = str(getattr(session, "owner", "") or "")
    invocation_id = str(getattr(session, "invocation_id", "") or "")
    if not owner or not invocation_id:
        raise OperatorError(
            "Resource authority requires the exact pnsctl owner and invocation"
        )
    runtime_lock.assert_held(owner, invocation_id)
    reset_identity = _resource_reset_identity(verified_identity, deadline_payload)
    authorization_window = ResourceAuthorizationWindow(
        reset_deadline_utc=_resource_identity_timestamp(
            reset_identity.reset_deadline_utc,
            "Resource reset deadline",
        ),
        authorization_expires_utc=_resource_identity_timestamp(
            verified_identity.expires_utc,
            "Resource authorization expiry",
        ),
    )
    try:
        authorization_window.require_current(
            ResourceAuthorizationWindow.sample_current_utc(wall_clock)
        )
    except ResourceAuthorizationWindowError as exc:
        raise OperatorError(
            "Resource authorization window denied before Resource SafetyStore open"
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
                raise OperatorError(
                    "Resource preparation requires the captured immediate-before frame"
                )
            if requested_action_key != "daily-resource-item:use-1k-food":
                raise OperatorError(
                    "Resource preparation action key is not the exact Use seam"
                )
            runtime_lock.assert_held(owner, invocation_id)
            now = time.monotonic()
            authority.ensure_static_utc_reset_identity(reset_identity)
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
                raise OperatorError(
                    "Resource occurrence did not grant one dispatch claim"
                )
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
            authorization_generation = authority.next_resource_authorization_generation(
                context
            )
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
            action_key = authority.resource_action_key(
                context, authorization_generation
            )
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
            duplicate = (
                store.connection.execute(
                    "SELECT 1 FROM actions WHERE action_key=?",
                    (action_key,),
                ).fetchone()
                is not None
            )
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
                raise OperatorError(f"Resource capability denied: {issued.reason_code}")
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
                raise OperatorError(
                    "Resource preparation fence changed during atomic preparation"
                )
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
                authorization_window=authorization_window,
                wall_clock=wall_clock,
            )

        return {
            "runtime_factory": runtime_factory,
            "authority": authority,
            "store": store,
            "controller_lease": controller_lease,
            "authorization_window": authorization_window,
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
    max_inputs: int | None = None,
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
    command_argv: Sequence[str] | None = None,
    _resource_store_path: Path | None = None,
    _resource_store_factory: Callable[[Path], Any] | None = None,
    _resource_wall_clock: Callable[[], datetime] | None = None,
) -> str:
    """Run a complete registered flow without queue, lease, replay, or preflight ceremony."""

    if live and flow_id == CAMPAIGN_AP_FLOW_ID and recovery_only is not True:
        raise OperatorError(
            "Ordinary Campaign execution uses pnsctl automation-service "
            "--mode supervised --adapter bluestacks serve --live --flow campaign; "
            "the legacy one-battle runner is retired."
        )
    if max_inputs is None:
        max_inputs = _DEFAULT_MAX_INPUTS.get(flow_id, 12)

    from scripts.navigation_development_boundary import (
        DevelopmentInitialObservation,
        DevelopmentSession,
    )
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
        _controller, delegated_receipt_payload, delegated_context = (
            _consume_delegated_receipt(
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
    if live and not yes:
        raise OperatorError("live development session requires --yes")
    if recovery_only:
        if flow_id == CAMPAIGN_AP_FLOW_ID:
            if recovery_session is None:
                raise OperatorError("Campaign victory recovery requires --recovery-session")
            from tasks.campaign_victory_recovery import load_victory_recovery_proof

            try:
                load_victory_recovery_proof(Path(recovery_session))
            except (ValueError, OSError) as exc:
                raise OperatorError(f"Campaign victory recovery proof rejected: {exc}") from exc
        if (
            flow_id == "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION"
            and recovery_session is None
        ):
            raise OperatorError("Ultimate recovery requires --recovery-session")
        if (
            flow_id == "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION"
            and recovery_session is None
        ):
            raise OperatorError("Ruins recovery requires --recovery-session")
        if (
            flow_id == "PERSONAL-MIGHT-PRAISE-BLUESTACKS-INTEGRATION"
            and recovery_session is None
        ):
            raise OperatorError("Personal Might recovery requires --recovery-session")
        if flow_id not in {
            CAMPAIGN_AP_FLOW_ID,
            "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION",
            "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION",
            "TROOP-TRAINING-END-TO-END-CONSOLIDATION",
            "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION",
            "WORLD-MAP-NAVIGATION-FOUNDATION",
            "PERSONAL-MIGHT-PRAISE-BLUESTACKS-INTEGRATION",
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
            f"local-{identity_now.date().isoformat()}-enhancement-family"
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
    registration_snapshot = None
    if (
        flow_id in {
            "WORLD-MAP-NAVIGATION-FOUNDATION",
            RECRUITMENT_MAINTENANCE_FLOW_ID,
            CAMPAIGN_AP_FLOW_ID,
        }
        and live
        and not recovery_only
        and not search_entry_only
    ):
        from automation_service.registry import consume_registered_entry

        try:
            registration_snapshot = consume_registered_entry(flow_id)
        except ValueError as exc:
            raise OperatorError(
                f"{flow_id} phase registration is invalid"
            ) from exc
        if registration_snapshot is None:
            raise OperatorError(
                f"{flow_id} full route is not registered for a phase canary"
            )
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
            observation = dict(observation)
            observation.setdefault("frame_sha256", hashlib.sha256(frame).hexdigest())
            from scripts.startup_recovery import classify_startup_frame

            startup_recovery_plan = classify_startup_frame(flow_id, frame)
            session.remember_control(
                "startup_recovery_plan",
                startup_recovery_plan.to_mapping(),
            )
            startup_runtime_holder: dict[str, Any] = {}
            startup_recovery_result: dict[str, Any] | None = None
            startup_recovery_input_count = 0
            startup_recovery_terminal_status: str | None = None
            startup_recovery_terminal_home_verified: bool | None = None
            if startup_recovery_plan.status != "clear":
                # Preserve the source before any recovery attempt. The route's
                # source.png is written later from a post-recovery frame.
                (session_directory / "startup-source.png").write_bytes(frame)
                session.remember_control(
                    "startup_source_sha256", hashlib.sha256(frame).hexdigest()
                )
            if (
                live
                and startup_recovery_plan.status == "recovery_required"
                and startup_recovery_plan.recovery_owner
                in {
                    "shared_home_startup_recovery",
                    "shared_startup_surface_recovery",
                }
            ):
                startup_recovery_result = _run_shared_startup_recovery(
                    flow_id=flow_id,
                    task_id=str(task_id or flow_id),
                    session_directory=session_directory,
                    max_inputs=max_inputs,
                    recovery_scope=runtime_scope,
                    expected_source_sha256=str(observation["frame_sha256"]),
                    runtime_holder=startup_runtime_holder,
                )
                startup_recovery_input_count = int(
                    startup_recovery_result.get("recovery_input_count")
                    or startup_recovery_result.get("input_count")
                    or 0
                )
                recovery_status = str(startup_recovery_result.get("status") or "")
                if recovery_status == "evidence_required" and startup_recovery_input_count > 0:
                    startup_recovery_terminal_status = "evidence_required"
                elif recovery_status not in {
                    "surface_dismissed_successor_captured",
                    "recovered",
                } or not 1 <= startup_recovery_input_count <= min(max_inputs, 2):
                    session.blocker = str(
                        startup_recovery_result.get("reason")
                        or "shared startup recovery did not reconcile"
                    )
                    session.next_action = (
                        "retain startup recovery evidence; identical retry is denied"
                    )
                    raise OperatorError(session.blocker)
                session.remember_control(
                    "startup_recovery_result", startup_recovery_result
                )
                session.remember_control(
                    "recovery_input_count", startup_recovery_input_count
                )
                if (
                    startup_recovery_input_count >= max_inputs
                    and recovery_status
                    in {
                        "surface_dismissed_successor_captured",
                        "recovered",
                    }
                ):
                    session.blocker = None
                    session.next_action = (
                        "startup recovery completed; route execution was intentionally not run"
                    )
                    startup_recovery_terminal_status = "completed"
                # The route initial observation is always captured after the final
                # shared recovery input settles, never from the promotional source.
                startup_runtime = startup_runtime_holder.get("runtime")
                if startup_runtime is not None:
                    post = startup_runtime.capture(
                        "startup-recovery-route-initial-observation"
                    )
                    frame = post.png
                    observation = {
                        "device_state": "device",
                        "foreground_package": BLUESTACKS_PACKAGE,
                        "native_width": BLUESTACKS_NATIVE_WIDTH,
                        "native_height": BLUESTACKS_NATIVE_HEIGHT,
                        "frame_sha256": post.sha256,
                    }
                else:
                    observation, frame = _development_runtime_observation()
                    observation = dict(observation)
                    observation.setdefault("frame_sha256", hashlib.sha256(frame).hexdigest())
                if startup_runtime is not None:
                    route_plan = classify_startup_frame(flow_id, frame)
                    if route_plan.status not in {"clear", "route_owned"}:
                        startup_recovery_terminal_status = "evidence_required"
                        startup_recovery_result = dict(
                            startup_recovery_result,
                            reason="startup_route_observation_requires_reassessment",
                        )
            if live and startup_recovery_plan.status == "blocked":
                (session_directory / "source.png").write_bytes(frame)
                session.blocker = startup_recovery_plan.reason
                session.next_action = (
                    "retain the frame and repair exact startup recognition"
                )
                raise OperatorError(startup_recovery_plan.reason)
            if startup_recovery_input_count:
                os.environ["PNS_DEVELOPMENT_MAX_INPUTS"] = str(
                    max_inputs - startup_recovery_input_count
                )
            (session_directory / "source.png").write_bytes(frame)
            initial_observation = DevelopmentInitialObservation(
                observation=observation,
                frame_sha256=str(observation.get("frame_sha256") or ""),
                frame_path="source.png",
                invocation_id=invocation_id,
            )
            session.set_initial_observation(initial_observation)
            session.remember_control("initial_observation_bound", True)
            for key, value in (
                ("viewport_signature", None),
                ("list_signature", None),
                ("direction", None),
                ("target_history", []),
                ("settle_history", []),
                ("recovery_result", None),
                ("pending_semantic_intent", None),
            ):
                session.remember_control(key, value)
            if startup_recovery_terminal_status is not None:
                session.terminal_status = startup_recovery_terminal_status
                startup_recovery_terminal_home_verified = False
                session.remember_control(
                    "terminal_home_verified", startup_recovery_terminal_home_verified
                )
                if startup_recovery_terminal_status == "evidence_required":
                    session.blocker = str(
                        startup_recovery_result.get("reason")
                        if startup_recovery_result is not None
                        else "evidence_required_unknown_startup_successor"
                    )
                    session.next_action = (
                        "retain startup recovery successor evidence; route dispatch is denied"
                    )
            if flow_id == "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION" and live:
                produced = _produce_resource_runtime_identity(
                    session=session,
                    wall_clock=_resource_wall_clock,
                    return_deadline_evidence=True,
                )
                resource_runtime_identity, resource_deadline_evidence = produced
                resource_runtime_components = _build_resource_runtime_components(
                    session=session,
                    verified_identity=resource_runtime_identity,
                    deadline_payload=resource_deadline_evidence,
                    store_path=_resource_store_path,
                    store_factory=_resource_store_factory,
                    wall_clock=_resource_wall_clock,
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
                "route_max_inputs": max_inputs - startup_recovery_input_count,
                "startup_recovery_result": startup_recovery_result,
                "startup_recovery_input_count": startup_recovery_input_count,
                "development_session": session,
                "initial_observation": initial_observation,
                "initial_observation_payload": initial_observation.to_mapping(),
                "initial_frame_sha256": initial_observation.frame_sha256,
                "startup_recovery_plan": startup_recovery_plan.to_mapping(),
                "registration_snapshot": registration_snapshot,
                "session_control_memory": session.control_memory,
                "resource_runtime_identity": resource_runtime_identity,
                "resource_deadline_evidence": resource_deadline_evidence,
            }
            if resource_runtime_components is not None:
                runtime_context["resource_runtime_factory"] = (
                    resource_runtime_components["runtime_factory"]
                )
            runner = _BLUESTACKS_FLOW_RUNNERS[contract["runner"]]
            if startup_recovery_terminal_status is not None:
                recovery_session = startup_runtime_holder.get("runtime")
                raw = json.dumps(
                    {
                        "status": startup_recovery_terminal_status,
                        "flow_id": flow_id,
                        "reason": str(
                            session.blocker
                            or "startup_recovery_completed_route_not_run"
                        ),
                        "dispatch": startup_recovery_input_count > 0,
                        "completion_scope": "startup_recovery_only",
                        "route_dispatch": False,
                        "session_directory": "",
                        "startup_recovery_session_directory": str(
                            getattr(recovery_session, "session", "")
                        ),
                        "input_count": startup_recovery_input_count,
                        "recovery_input_count": startup_recovery_input_count,
                        "route_input_count": 0,
                        "total_input_count": startup_recovery_input_count,
                        "terminal_home_verified": startup_recovery_terminal_home_verified,
                    },
                    sort_keys=True,
                )
            else:
                try:
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
                except BaseException:
                    # The route did not return a result to project below, but
                    # startup transport already happened in its own runtime.
                    # Preserve it alongside any actions recorded by the route.
                    startup_rows = _startup_recovery_action_rows(startup_recovery_result)
                    if startup_recovery_input_count:
                        session.input_count += startup_recovery_input_count
                        session.remember_control(
                            "failed_route_startup_transport_count", startup_recovery_input_count
                        )
                        session.actions = _unique_action_rows([*startup_rows, *session.actions])
                        with (session_directory / "actions.jsonl").open(
                            "a", encoding="utf-8", newline="\n"
                        ) as handle:
                            for row in startup_rows:
                                handle.write(json.dumps(row, sort_keys=True) + "\n")
                    raise
            result = json.loads(raw)
            child_text = str(result.get("session_directory") or "")
            child = Path(child_text) if child_text else None
            event_rows: list[dict[str, Any]] = []
            transport_evidence_available = False
            if child is not None and child.is_dir():
                events = child / "events.jsonl"
                if events.is_file():
                    transport_evidence_available = True
                    for line in events.read_text(encoding="utf-8").splitlines():
                        row = json.loads(line) if line.strip() else {}
                        if row:
                            event_rows.append(row)
            retained_action_rows = _compact_development_action_results(event_rows)
            canonical_action_rows = list(session.actions)
            route_action_rows = canonical_action_rows or retained_action_rows
            startup_action_rows = _startup_recovery_action_rows(
                startup_recovery_result
            )
            action_rows = _unique_action_rows(
                [*startup_action_rows, *route_action_rows]
            )
            if route_action_rows:
                route_retained_count = _retained_transport_count(route_action_rows)
            elif transport_evidence_available:
                route_retained_count = _retained_transport_count(event_rows)
            else:
                route_retained_count = int(session.input_count)
            if flow_id == "CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY":
                campaign_retained = result.get("campaign_transport_count")
                if type(campaign_retained) is not int or campaign_retained < 0:
                    raise OperatorError(
                        "Campaign AP route did not report retained transport accounting"
                    )
                route_retained_count = campaign_retained
            if flow_id == "TROOP-TRAINING-END-TO-END-CONSOLIDATION" and live:
                troop_retained = result.get("troop_training_transport_count")
                if type(troop_retained) is not int or troop_retained < 0:
                    raise OperatorError(
                        "Troop Training route did not report retained transport accounting"
                    )
                route_retained_count = troop_retained
            if flow_id == "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION":
                ultimate_retained = result.get("retained_transport_count")
                if type(ultimate_retained) is not int or ultimate_retained < 0:
                    raise OperatorError(
                        "Ultimate terminal route did not report retained transport accounting"
                    )
                route_retained_count = ultimate_retained
            retained_count = startup_recovery_input_count + route_retained_count
            if retained_count > max_inputs:
                raise OperatorError("development session exceeded its input limit")
            if session.input_count == 0 and retained_count:
                session.adopt_retained_transport_count(
                    retained_count,
                    source="runtime_session/events.jsonl",
                )
            elif session.input_count != retained_count:
                raise OperatorError(
                    "development session input count does not match retained transports"
                )
            semantic_completed_count = _retained_semantic_completed_count(action_rows)
            dispatch_count = session.input_count
            session.actions = action_rows
            if action_rows:
                with (session_directory / "actions.jsonl").open(
                    "w", encoding="utf-8", newline="\n"
                ) as handle:
                    for row in action_rows:
                        handle.write(json.dumps(row, sort_keys=True) + "\n")
            result_status = str(result.get("status") or "unknown")
            if result_status == "evidence_required":
                session.terminal_status = "evidence_required"
                session.blocker = str(
                    result.get("reason") or "evidence_required"
                )
                session.next_action = (
                    "retain startup recovery successor evidence; route dispatch is denied"
                )
            elif result.get("effect_reconciliation_required") is True:
                session.terminal_status = "effect_reconciliation_required"
                session.blocker = "effect_reconciliation_required"
                session.next_action = (
                    "observe-only effect reconciliation; identical retry is denied"
                )
            elif result_status not in {"completed", "dry_run", "observed"}:
                session.terminal_status = "blocked"
                session.blocker = str(
                    result.get("reason") or "development result is not terminal"
                )
                session.next_action = (
                    f"inspect {child_text or session_directory} and repair recognition or recovery "
                    f"for {session.blocker} before rerunning materially changed behavior"
                )
            if action_rows and semantic_completed_count < len(action_rows) and session.terminal_status is None:
                session.terminal_status = "blocked"
                session.blocker = "action semantic outcome is not confirmed"
                session.next_action = "observe-only effect reconciliation; identical retry is denied"
            if _checkpoint_hashes() != checkpoint_before:
                raise OperatorError(
                    "ordinary development session mutated a checkpoint artifact"
                )
            wrapper = {
                "status": session.terminal_status or result.get("status", "unknown"),
                "flow_id": flow_id,
                "session_directory": str(session_directory),
                "runtime_session_directory": child_text,
                "input_count": dispatch_count,
                "transport_attempted_count": dispatch_count,
                "action_count": len(action_rows),
                "semantic_completed_count": semantic_completed_count,
                "recovery_input_count": startup_recovery_input_count,
                "route_input_count": route_retained_count,
                "total_input_count": dispatch_count,
                "startup_recovery_result": startup_recovery_result,
                "max_inputs": max_inputs,
                "chest_continuation": str(chest_continuation)
                if chest_continuation is not None
                else None,
                "runtime_observation": observation,
                "initial_observation": initial_observation.to_mapping(),
                "initial_frame_sha256": initial_observation.frame_sha256,
                "proof_topology": str(
                    result.get(
                        "proof_topology",
                        "continuous"
                        if flow_id
                        in {
                            "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION",
                            "WORLD-MAP-NAVIGATION-FOUNDATION",
                            "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                            "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION",
                            "BIOENHANCER-FREE-RESEARCH-BLUESTACKS-INTEGRATION",
                            "SUPPLY-DEPOT-BLUESTACKS-INTEGRATION",
                            "TROOP-TRAINING-END-TO-END-CONSOLIDATION",
                        }
                        else "composite",
                    )
                ),
                "causal_trace_count": int(result.get("causal_trace_count") or 0),
                "lifecycle_state_created": False,
                "persistent_checkpoint_artifacts_unchanged": True,
                "result": result,
            }
            if delegated_receipt_payload is not None:
                wrapper["receipt_id"] = delegated_receipt_payload["receipt_id"]
                wrapper["receipt_digest"] = delegated_receipt_payload["receipt_digest"]
                wrapper["evidence_result_identity"] = delegated_context.result_identity
            if startup_recovery_terminal_home_verified is not None:
                wrapper["terminal_home_verified"] = (
                    startup_recovery_terminal_home_verified
                )
            (session_directory / "result.json").write_text(
                json.dumps(wrapper, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        if startup_recovery_terminal_home_verified is not None:
            summary_path = session_directory / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["terminal_home_verified"] = (
                startup_recovery_terminal_home_verified
            )
            summary_path.write_text(
                json.dumps(summary, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        if delegated_context is not None:
            if (
                not (session_directory / "source.png").is_file()
                or not (session_directory / "result.json").is_file()
                or not (session_directory / "summary.json").is_file()
                or session._ownership.lock.held
            ):
                raise OperatorError(
                    "delegated flow evidence or ownership release is unproven"
                )
            terminal_status = str(result.get("status") or "evidence_required")
            if (
                terminal_status
                not in delegated_receipt_payload["permitted_terminal_states"]
            ):
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
    allowed_statuses = {"completed", "blocked", "unresolved", "manual_required"}
    if result.get("effect_reconciliation_required") is True:
        allowed_statuses.add("effect_reconciliation_required")
    if result_status not in allowed_statuses:
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
        "causal_trace_path",
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
    ):
        raise OperatorError("unsupported flow-delivery result identity")
    return session, result


def bluestacks_verify_flow(session_directory: Path) -> str:
    session, retained_result = _retained_flow_result(session_directory)
    retained_flow_id = str(retained_result["flow_id"])
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
            CAMPAIGN_AP_FLOW_ID,
            RECRUITMENT_MAINTENANCE_FLOW_ID,
            "BIOENHANCER-FREE-RESEARCH-BLUESTACKS-INTEGRATION",
            "PERSONAL-MIGHT-PRAISE-BLUESTACKS-INTEGRATION",
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
            max_inputs=32,
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


def _canonical_service_serve_argv(command_argv: Sequence[str]) -> list[str] | None:
    """Forward only canonical serve syntax; leave its parser authoritative."""

    if not command_argv or command_argv[0] != "automation-service":
        return None
    index = 1
    while index < len(command_argv):
        value = command_argv[index]
        if value == "serve":
            return list(command_argv[1:])
        option, separator, _value = value.partition("=")
        if option not in {"--mode", "--adapter", "--state-path"}:
            return None
        # A separate option value can itself be named "serve". Skip it rather
        # than mistaking a path or invalid mode value for the command.
        index += 1 if separator else 2
    return None


def automation_service_offline(args: argparse.Namespace) -> int:
    """Delegate automation-service commands through its canonical CLI facade."""

    from automation_service.cli import main as automation_main

    command = args.automation_service_command
    argv = [
        "--mode",
        getattr(args, "mode", "disabled"),
    ]
    state_path = getattr(args, "state_path", None)
    if state_path is not None:
        argv.extend(["--state-path", str(state_path)])
    argv.append(command)
    if command in {"enable", "disable"}:
        argv.append(args.flow_id)
    if command == "run":
        argv.append(args.flow_id)
        if args.live:
            argv.append("--live")
        argv.extend(
            [
                "--account-id",
                args.account_id,
                "--server-id",
                args.server_id,
                "--reset-id",
                args.reset_id,
            ]
        )
        if args.operator_request_id is not None:
            argv.extend(["--operator-request-id", args.operator_request_id])
    if command in {"service-disable", "emergency-stop"}:
        argv.extend(["--reason", args.reason])
    if getattr(args, "now_utc_epoch", None) is not None:
        argv.extend(["--now-utc-epoch", str(args.now_utc_epoch)])
    return automation_main(argv)


def automation_service_scheduler_pulse_offline(args: argparse.Namespace) -> int:
    """Run one canonical, fail-closed, zero-transport scheduler pulse."""

    from automation_service.contracts import (
        RecurrenceClass,
        RecurrenceProjection,
        SchedulerFacts,
    )
    from automation_service.registry import canonical_flow_specs
    from automation_service.service import AutomationService
    from automation_service.state import BotStateManager, resolve_state_path

    state_path = Path(resolve_state_path(args.state_path))
    with BotStateManager(state_path) as state:
        state.initialize_flows(canonical_flow_specs())
        service = AutomationService(mode="dry_run", state=state)
        flow_id = getattr(args, "flow_id", None)
        if flow_id is None:
            if getattr(args, "projection_observed_balance", None) is not None:
                flow_id = CAMPAIGN_AP_FLOW_ID
            elif getattr(args, "projection_observed_at_utc", None) is not None:
                flow_id = RECRUITMENT_MAINTENANCE_FLOW_ID
            else:
                from automation_service.registry import load_canonical_registry

                flow_id = load_canonical_registry()[0].flow_id
        descriptor = service.flow_descriptor(flow_id)
        flow_state = state.get_flow(flow_id)
        scheduler_eligible = bool(
            descriptor is not None
            and descriptor.scheduler_eligible
            and state.get_service_enabled()
            and flow_state is not None
            and flow_state.enabled
            and not flow_state.blocked
        )
        now = (
            float(args.now_utc_epoch)
            if args.now_utc_epoch is not None
            else datetime.now(timezone.utc).timestamp()
        )
        healthy = bool(getattr(args, "health_ok", False))
        projections = {}
        observed_at = getattr(args, "projection_observed_at_utc", None)
        if flow_id == RECRUITMENT_MAINTENANCE_FLOW_ID and observed_at is not None:
            projections[flow_id] = RecurrenceProjection(
                RecurrenceClass.COOLDOWN,
                next_eligible_at=getattr(args, "projection_next_eligible_at", None),
                observed_at_utc=float(observed_at),
            )
        elif (
            flow_id == CAMPAIGN_AP_FLOW_ID
            and observed_at is not None
            and getattr(args, "projection_observed_balance", None) is not None
        ):
            projections[flow_id] = RecurrenceProjection(
                RecurrenceClass.AP_REGENERATION,
                next_eligible_at=getattr(args, "projection_next_eligible_at", None),
                observed_at_utc=float(observed_at),
                observed_balance=float(args.projection_observed_balance),
            )
        facts = SchedulerFacts(
            args.account_id,
            args.server_id,
            args.reset_id,
            now,
            health_ok=healthy,
            accepted_product=(
                descriptor.accepted_product if descriptor is not None else False
            ),
            product_revision=(
                descriptor.product_revision if descriptor is not None else None
            ),
            registration_status=(
                descriptor.registration_status
                if descriptor is not None
                else "NOT_REGISTERED"
            ),
            scheduler_eligible=(
                descriptor.scheduler_eligible if descriptor is not None else False
            ),
            owner_available=healthy,
            clock_ok=healthy,
            reset_agreement=healthy,
            projections=projections,
        )
        report = service.pulse(facts)
        candidate = None
        if report.candidate is not None:
            candidate = {
                "flow_id": report.candidate.descriptor.flow_id,
                "identity": asdict(report.candidate.identity),
                "occurrence_key": report.candidate.occurrence_key,
            }
        result = report.result.to_mapping() if report.result is not None else None
        print(
            json.dumps(
                {
                    "status": "selected" if candidate is not None else "disabled",
                    "command": "scheduler-pulse",
                    "reason": report.reason_code,
                    "candidate": candidate,
                    "result": result,
                    "transport_count": 0,
                    "production_registration": (
                        descriptor.registration_status
                        if descriptor is not None
                        else "NOT_REGISTERED"
                    ),
                    "scheduler_eligible": scheduler_eligible,
                    "accepted_product": (
                        descriptor.accepted_product
                        if descriptor is not None
                        else False
                    ),
                    "product_revision": (
                        descriptor.product_revision
                        if descriptor is not None
                        else None
                    ),
                },
                sort_keys=True,
            )
        )
        return 0


scheduler_pulse_offline = automation_service_scheduler_pulse_offline


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
    development_launch = development_sub.add_parser(
        "launch-game",
        help=(
            "Bootstrap the installed game from the BlueStacks launcher only; "
            "live requires --live --yes"
        ),
    )
    development_launch.add_argument("--live", action="store_true")
    development_launch.add_argument("--yes", action="store_true")
    development_launch.add_argument("--cold-restart", action="store_true",
        help="explicitly cold-stop a clean idle game, verify process exit, then reuse guarded startup")
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
    development_run.add_argument("--max-inputs", type=int, default=None)
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
    bluestacks = sub.add_parser("bluestacks")
    bluestacks_sub = bluestacks.add_subparsers(dest="bluestacks_command", required=True)
    bluestacks_sub.add_parser("preflight")
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
    # main forwards serve before this parser runs, so the canonical CLI owns
    # its options, validation, help and existing runtime controls.
    automation_sub.add_parser(
        "serve",
        help="canonical native service; put --mode, --adapter and --state-path before serve",
    )
    automation_status = automation_sub.add_parser("status")
    automation_status.add_argument(
        "--mode", choices=("disabled", "observe_only", "dry_run"), default="disabled"
    )
    automation_status.add_argument("--state-path", type=Path, default=None)
    automation_health = automation_sub.add_parser("health")
    automation_health.add_argument(
        "--mode", choices=("disabled", "observe_only", "dry_run"), default="disabled"
    )
    automation_health.add_argument("--state-path", type=Path, default=None)
    automation_enable = automation_sub.add_parser("enable")
    automation_enable.add_argument("flow_id")
    automation_enable.add_argument("--state-path", type=Path, default=None)
    automation_enable.add_argument("--now-utc-epoch", type=float, default=None)
    automation_disable = automation_sub.add_parser("disable")
    automation_disable.add_argument("flow_id")
    automation_disable.add_argument("--state-path", type=Path, default=None)
    automation_disable.add_argument("--now-utc-epoch", type=float, default=None)
    automation_run = automation_sub.add_parser("run")
    automation_run.add_argument("flow_id")
    automation_run.add_argument(
        "--mode", choices=("disabled", "observe_only", "dry_run"), default="disabled"
    )
    automation_run.add_argument("--live", action="store_true")
    automation_run.add_argument("--state-path", type=Path, default=None)
    automation_run.add_argument("--account-id", default="offline-account")
    automation_run.add_argument("--server-id", default="offline-server")
    automation_run.add_argument("--reset-id", default="offline-reset")
    automation_run.add_argument("--operator-request-id", default=None)
    automation_run.add_argument("--now-utc-epoch", type=float, default=None)
    service_enable = automation_sub.add_parser("service-enable")
    service_enable.add_argument("--state-path", type=Path, default=None)
    service_enable.add_argument("--now-utc-epoch", type=float, default=None)
    service_disable = automation_sub.add_parser("service-disable")
    service_disable.add_argument("--state-path", type=Path, default=None)
    service_disable.add_argument("--now-utc-epoch", type=float, default=None)
    service_disable.add_argument("--reason", default="service disabled")
    emergency_stop = automation_sub.add_parser("emergency-stop")
    emergency_stop.add_argument("--state-path", type=Path, default=None)
    emergency_stop.add_argument("--now-utc-epoch", type=float, default=None)
    emergency_stop.add_argument("--reason", default="emergency stop")
    scheduler_pulse = automation_sub.add_parser(
        "pulse",
        help="one offline UTC scheduler pulse; never starts runtime or transport",
    )
    scheduler_pulse.add_argument("--flow-id", default=None)
    scheduler_pulse.add_argument("--state-path", type=Path, default=None)
    scheduler_pulse.add_argument("--account-id", default="offline-account")
    scheduler_pulse.add_argument("--server-id", default="offline-server")
    scheduler_pulse.add_argument("--reset-id", default="offline-reset")
    scheduler_pulse.add_argument("--now-utc-epoch", type=float, default=None)
    scheduler_pulse.add_argument(
        "--projection-observed-at-utc", type=float, default=None
    )
    scheduler_pulse.add_argument(
        "--projection-next-eligible-at", type=float, default=None
    )
    scheduler_pulse.add_argument(
        "--projection-observed-balance", type=float, default=None
    )
    scheduler_pulse.add_argument(
        "--health-ok",
        action="store_true",
        help="admit the healthy offline selection gates; never starts runtime",
    )
    return root


def main(argv: Sequence[str] | None = None) -> int:
    command_argv = list(sys.argv[1:] if argv is None else argv)
    canonical_argv = _canonical_service_serve_argv(command_argv)
    if canonical_argv is not None:
        from automation_service.cli import main as automation_main

        return automation_main(
            canonical_argv, application_startup=owner_bound_application_startup
        )
    args = parser().parse_args(argv)
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
            elif args.development_command == "launch-game":
                output = development_session_launch_game(
                    live=bool(args.live),
                    yes=bool(args.yes),
                    cold_restart=bool(args.cold_restart),
                )
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
            if args.automation_service_command == "pulse":
                return automation_service_scheduler_pulse_offline(args)
            return automation_service_offline(args)
        except (OperatorError, OSError, RuntimeError, ValueError) as exc:
            from automation_service.state import StateBusyError

            if isinstance(exc, StateBusyError) or (
                isinstance(exc, sqlite3.OperationalError)
                and any(
                    marker in str(exc).casefold() for marker in ("busy", "locked")
                )
            ):
                print(
                    json.dumps(
                        {
                            "status": "error",
                            "reason": "SQLITE_BUSY",
                            "retryable": True,
                        },
                        sort_keys=True,
                    ),
                    file=sys.stderr,
                )
            else:
                print("pnsctl: " + str(exc), file=sys.stderr)
            return 2
    raise OperatorError("unsupported pnsctl command")


if __name__ == "__main__":
    raise SystemExit(main())
