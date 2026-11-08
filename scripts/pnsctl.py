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
from automation_service.registry import (  # noqa: E402
    ALLIANCE_HELP_FLOW_ID,
    ALLIANCE_DONATION_FLOW_ID,
    ALLIANCE_SHOP_FLOW_ID,
    DAILY_SHOPS_FLOW_ID,
    BIOENHANCER_FLOW_ID,
    CAMPAIGN_FLOW_ID,
    DAILY_REWARDS_FLOW_ID,
    ENHANCEMENT_FLOW_ID,
    ENHANCEMENT_MAX_INPUTS,
    PERSONAL_MIGHT_FLOW_ID,
    RECRUITMENT_FLOW_ID,
    RESOURCE_ITEM_FLOW_ID,
    RUINS_FLOW_ID,
    NANO_MATERIAL_PRODUCTION_FLOW_ID,
    NANOWEAPON_FLOW_ID,
    HERO_DUEL_FLOW_ID,
    RECOMMENDED_RESEARCH_FLOW_ID,
    FOOD_FARM_BOOST_FLOW_ID,
    SUPPLY_FLOW_ID,
    HALL_OF_WAR_FLOW_ID,
    TROOP_TRAINING_FLOW_ID,
    TROOP_TRAINING_MAX_INPUTS,
    WALI_UPGRADE_FLOW_ID,
    ULTIMATE_FLOW_ID,
    WORLD_FLOW_ID,
)
from automation_service.native_execution import NativeRouteBoundary  # noqa: E402
from scripts import (  # noqa: E402
    flow_delivery_bioenhancer_bluestacks,
    flow_delivery_campaign_bluestacks,
    flow_delivery_personal_might_bluestacks,
    flow_delivery_recruitment_bluestacks,
    flow_delivery_supply_depot_bluestacks,
    flow_delivery_ultimate_challenge_bluestacks,
)
from scripts.bluestacks_adb_readiness import (  # noqa: E402
    ADBReadinessError,
    ensure_adb_ready,
)
from tasks.runtime_identity import (  # noqa: E402
    BLUESTACKS_ADB,
    BLUESTACKS_PACKAGE,
    BLUESTACKS_SERIAL,
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
DEVELOPMENT_CHECKPOINT_PATHS = (
    REPO_ROOT / "BACKLOG.md",
    REPO_ROOT / "tasks" / "flow_delivery_queue.json",
    REPO_ROOT / "docs" / "agent" / "CURRENT_HANDOFF.md",
)
# Flow identities and native route budgets are owned by the canonical registry;
# pnsctl only aliases facts needed by its legacy development routes.
RECRUITMENT_MAINTENANCE_FLOW_ID = RECRUITMENT_FLOW_ID
CAMPAIGN_AP_FLOW_ID = CAMPAIGN_FLOW_ID
CAMPAIGN_PROVING_FLOW_ID = flow_delivery_campaign_bluestacks.PROVING_FLOW_ID
# The Campaign development session budget is its own fact: it is not the service route cap.
CAMPAIGN_DEVELOPMENT_SESSION_MAX_INPUTS = 16
# Default development-session input ceiling per registered flow (12 when unlisted).
_DEFAULT_MAX_INPUTS = {
    ULTIMATE_FLOW_ID: flow_delivery_ultimate_challenge_bluestacks.MAX_TOTAL_INPUTS,
    BIOENHANCER_FLOW_ID: flow_delivery_bioenhancer_bluestacks.MAX_INPUTS,
    PERSONAL_MIGHT_FLOW_ID: flow_delivery_personal_might_bluestacks.MAX_INPUTS,
    SUPPLY_FLOW_ID: flow_delivery_supply_depot_bluestacks.MAX_INPUTS,
    ENHANCEMENT_FLOW_ID: ENHANCEMENT_MAX_INPUTS,
    RECRUITMENT_MAINTENANCE_FLOW_ID: flow_delivery_recruitment_bluestacks.MAX_INPUTS,
    CAMPAIGN_AP_FLOW_ID: CAMPAIGN_DEVELOPMENT_SESSION_MAX_INPUTS,
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
    register_recruitment(
        _BLUESTACKS_FLOW_RUNNERS,
        _BLUESTACKS_EVIDENCE_VALIDATORS,
        _BLUESTACKS_RECOVERY_HANDLERS,
    )


_register_checked_in_bluestacks_handlers()


def _native_service_route_bindings() -> Mapping[str, NativeRouteBoundary]:
    """Build device-free native bindings for fixed canonical service routes."""
    from scripts.base_route_native_runtime import make_native_route_binding
    from scripts.daily_resource_item_bluestacks import (
        create_service_binding as create_resource_item_binding,
    )
    from scripts.daily_row_claim_bluestacks import (
        create_service_binding as create_daily_rewards_binding,
    )
    from scripts.ruins_challenge_bluestacks import (
        create_service_binding as create_ruins_binding,
    )
    from scripts.alliance_help_bluestacks import (
        create_service_binding as create_alliance_help_binding,
    )
    from scripts.alliance_donation_bluestacks import (
        create_service_binding as create_alliance_donation_binding,
    )
    from scripts.alliance_shop_bluestacks import (
        create_service_binding as create_alliance_shop_binding,
    )
    from scripts.daily_shops_bluestacks import (
        create_service_binding as create_daily_shops_binding,
    )
    from scripts.nano_material_production_bluestacks import (
        create_service_binding as create_nano_material_production_binding,
    )
    from scripts.nanoweapon_bluestacks import (
        create_service_binding as create_nanoweapon_binding,
    )
    from scripts.hero_duel_bluestacks import (
        create_service_binding as create_hero_duel_binding,
    )
    from scripts.recommended_research_bluestacks import (
        create_service_binding as create_recommended_research_binding,
    )
    from scripts.food_farm_boost_bluestacks import (
        create_service_binding as create_food_farm_boost_binding,
    )
    from scripts.hall_of_war_bluestacks import (
        create_service_binding as create_hall_of_war_binding,
    )
    from scripts.troop_training_bluestacks import (
        create_service_binding as create_troop_training_binding,
    )
    from scripts.wali_upgrade_bluestacks import (
        create_service_binding as create_wali_upgrade_binding,
    )

    return {
        DAILY_REWARDS_FLOW_ID: create_daily_rewards_binding(
            make_native_route_binding
        ),
        RESOURCE_ITEM_FLOW_ID: create_resource_item_binding(
            make_native_route_binding
        ),
        RUINS_FLOW_ID: create_ruins_binding(make_native_route_binding),
        ALLIANCE_HELP_FLOW_ID: create_alliance_help_binding(make_native_route_binding),
        ALLIANCE_DONATION_FLOW_ID: create_alliance_donation_binding(
            make_native_route_binding
        ),
        ALLIANCE_SHOP_FLOW_ID: create_alliance_shop_binding(
            make_native_route_binding
        ),
        DAILY_SHOPS_FLOW_ID: create_daily_shops_binding(make_native_route_binding),
        NANO_MATERIAL_PRODUCTION_FLOW_ID: create_nano_material_production_binding(
            make_native_route_binding
        ),
        NANOWEAPON_FLOW_ID: create_nanoweapon_binding(make_native_route_binding),
        HERO_DUEL_FLOW_ID: create_hero_duel_binding(make_native_route_binding),
        RECOMMENDED_RESEARCH_FLOW_ID: create_recommended_research_binding(make_native_route_binding),
        FOOD_FARM_BOOST_FLOW_ID: create_food_farm_boost_binding(make_native_route_binding),
        HALL_OF_WAR_FLOW_ID: create_hall_of_war_binding(make_native_route_binding),
        TROOP_TRAINING_FLOW_ID: create_troop_training_binding(make_native_route_binding),
        WALI_UPGRADE_FLOW_ID: create_wali_upgrade_binding(make_native_route_binding),
    }


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
    allow_troop_training_recovery: bool = False,
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
    active_flow = queue.get("active_flow_id")
    if not active_flow or lease.get("active_flow") != active_flow:
        raise OperatorError("queue and lease must identify one active development flow")
    if active_flow not in BLUESTACKS_FLOW_IDS and not (
        allow_troop_training_recovery and active_flow == TROOP_TRAINING_FLOW_ID
    ):
        raise OperatorError("active flow is not in the BlueStacks allowlist")
    if lease.get("unresolved_action_state") != "clear" and not (
        allow_troop_training_recovery and active_flow == TROOP_TRAINING_FLOW_ID
    ):
        raise OperatorError("the global unresolved-action gate is not clear")
    return queue, lease



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
        or result.get("flow_id") != ENHANCEMENT_FLOW_ID
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

def _troop_training_recovery_history() -> dict[str, Any] | None:
    """Read canonical Training and Resource effect history without mutating it."""

    from automation_service.recruitment import recruitment_reset
    from automation_service.troop_training import derive_training_action_state
    from safe_action_core.store import CURRENT_SCHEMA_VERSION
    from scripts.navigation_development_boundary import CANONICAL_ACTION_STORE_PATH
    from tasks.runtime_identity import resource_fixed_runtime_binding

    path = CANONICAL_ACTION_STORE_PATH
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise OperatorError("canonical action history path is unsafe")
    now = time.time()
    reset_id = recruitment_reset(now)
    binding = resource_fixed_runtime_binding()
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            schema = connection.execute(
                "SELECT version FROM schema_version WHERE singleton=1"
            ).fetchone()
            if schema is None or schema["version"] != CURRENT_SCHEMA_VERSION:
                raise OperatorError("canonical action history schema is not current")
            action_rows = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM actions WHERE task_id=? ORDER BY prepared_at, action_id",
                    (TROOP_TRAINING_FLOW_ID,),
                ).fetchall()
            ]
            state = derive_training_action_state(
                action_rows,
                runtime_scope=binding.runtime_scope,
                account_id=binding.account_id,
                server_id=binding.server_id,
                game_day_id=reset_id,
            )
            prefix = f"troop-training:{state.runtime_identity_sha256}:"
            unresolved = [
                row
                for row in action_rows
                if str(row.get("action_key") or "").startswith(prefix)
                and row.get("final_status") in {"prepared", "input_sent", "unresolved"}
            ]
            if any(row.get("consequential") != 1 for row in unresolved):
                raise OperatorError(
                    "canonical Training pending action is not consequentially bound"
                )
            confirmed_queue_keys = set(state.pending_start_action_keys.values())
            confirmed_queue_rows = [
                row
                for row in action_rows
                if row.get("action_key") in confirmed_queue_keys
                and row.get("final_status") == "confirmed"
            ]
            candidate_rows = {row["action_id"]: row for row in unresolved}
            candidate_rows.update(
                {row["action_id"]: row for row in confirmed_queue_rows}
            )
            if not candidate_rows:
                return None
            candidate_ids = set(candidate_rows)
            global_blockers = {
                str(row["action_id"])
                for row in connection.execute(
                    """SELECT action_id FROM actions
                       WHERE consequential=1
                         AND final_status IN ('prepared','input_sent','unresolved')"""
                ).fetchall()
            }
            if not global_blockers.issubset(candidate_ids):
                raise OperatorError(
                    "canonical action history contains an unrelated unresolved effect"
                )
            block_rows = connection.execute(
                """SELECT p.projection_state,p.current_reset_id,b.scope_key,
                          b.account_id,b.server_id,b.reset_identity_id,b.occurrence_key
                   FROM resource_effect_block_projection p
                   JOIN resource_effect_block_facts b ON b.block_id=p.block_id
                   WHERE p.projection_state IN ('ACTIVE','CONFLICT','CLEARED')"""
            ).fetchall()
            scope_values = {binding.account_id, binding.server_id}
            for row in block_rows:
                matches = any(
                    value in scope_values
                    for value in (
                        row["scope_key"],
                        row["account_id"],
                        row["server_id"],
                        row["reset_identity_id"],
                        row["occurrence_key"],
                    )
                    if value is not None
                )
                broad_unknown = (
                    str(row["scope_key"]).startswith("runtime-objective:")
                    and row["account_id"] is None
                    and row["server_id"] is None
                    and row["reset_identity_id"] is None
                    and row["occurrence_key"] is None
                )
                if not matches and not broad_unknown:
                    continue
                if row["projection_state"] in {"ACTIVE", "CONFLICT"} or (
                    row["projection_state"] == "CLEARED"
                    and row["current_reset_id"] != reset_id
                ):
                    raise OperatorError(
                        "canonical Resource effect history blocks Training recovery"
                    )
            return {
                "task_id": TROOP_TRAINING_FLOW_ID,
                "runtime_identity_sha256": state.runtime_identity_sha256,
                "reset_id": reset_id,
                "action_ids": sorted(candidate_ids),
                "action_keys": sorted(
                    str(row["action_key"]) for row in candidate_rows.values()
                ),
                "pending_statuses": sorted(
                    {
                        str(row["final_status"])
                        for row in unresolved
                    }
                ),
                "confirmed_queue_action_ids": sorted(
                    row["action_id"] for row in confirmed_queue_rows
                ),
                "source": "canonical_sqlite_action_and_resource_history",
            }
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise OperatorError("canonical Training action history is unavailable") from exc
    except (TypeError, ValueError) as exc:
        raise OperatorError("canonical Training action history is malformed") from exc




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


def _network_dialog(frame_bytes: bytes) -> dict[str, Any]:
    import cv2
    import numpy as np
    from scripts.bluestacks_popup_recognition import recognize_network_disconnect
    return recognize_network_disconnect(cv2.imdecode(np.frombuffer(frame_bytes, dtype=np.uint8), cv2.IMREAD_COLOR))


def _owner_bound_network_recovery(*, runtime_input_lock, checkpoint, session_directory,
                                  state_manager, allow_relaunch: bool, inspect_only: bool = False) -> dict[str, Any]:
    from automation_service.state import BotStateManager
    from scripts.navigation_development_boundary import RuntimeInputLock, open_canonical_action_store
    from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
    from scripts.startup_normalization import is_clean_home_frame
    from scripts.startup_recovery import (
        classify_startup_frame, recover_network_disconnect, inspect_network_disconnect_context,
    )
    from tasks.runtime_identity import FIXED_RUNTIME_SCOPE

    if (not isinstance(runtime_input_lock, RuntimeInputLock) or not runtime_input_lock.held
            or not isinstance(state_manager, BotStateManager) or state_manager.read_only
            or Path(state_manager.db_path).resolve() != BotStateManager.DEFAULT_DB_PATH.resolve()
            or not Path(state_manager.db_path).is_file()):
        raise OperatorError("network recovery requires the actual owner and existing canonical writable state")
    store = open_canonical_action_store()
    owner = f"{runtime_input_lock.owner}:network-recovery:{runtime_input_lock.invocation_id}"
    leased = False
    runtime = None
    launches = 0
    try:
        if store.has_action_block():
            raise OperatorError("network recovery cannot bypass an unresolved action")
        store.acquire_lease(owner, time.time(), 300.0)
        leased = True

        def fenced():
            runtime_input_lock.assert_held(runtime_input_lock.owner, runtime_input_lock.invocation_id)
            checkpoint()
            if not store.lease_valid_for(owner, time.time()):
                raise OperatorError("network recovery Core lease lost")

        fenced()
        runtime = LocalBlueStacksRuntime.connect(
            adb=str(BLUESTACKS_ADB), serial=BLUESTACKS_SERIAL,
            output_directory=Path(session_directory), workflow="network-recovery", execute=not inspect_only,
        )
        runtime.max_inputs = 0 if inspect_only else min(runtime.max_inputs, 1)
        runtime.checkpoint = fenced

        def context(captured):
            fenced()
            if runtime.measure_device_state() != "device":
                return "MANUAL_REQUIRED"
            package = runtime.measure_foreground_package()
            if package in BLUESTACKS_LAUNCHER_PACKAGES:
                return "BLUESTACKS_LAUNCHER"
            if package != BLUESTACKS_PACKAGE:
                return "MANUAL_REQUIRED"
            detail = _network_dialog(captured.png)
            if detail.get("recognized") or detail.get("blocking_unknown_modal"):
                return "UNKNOWN"
            if is_clean_home_frame(captured.frame):
                return "HOME_BASE"
            plan = classify_startup_frame("", captured.png)
            if plan.status == "recovery_required" and plan.recovery_owner in {
                "shared_home_startup_recovery", "shared_startup_surface_recovery",
            }:
                return "KNOWN_STARTUP_OVERLAY"
            return "MANUAL_REQUIRED" if plan.status == "blocked" else "UNKNOWN"

        def relaunch():
            nonlocal launches
            fenced()
            if not allow_relaunch:
                raise OperatorError("the current startup already consumed its single launch budget")
            episode = state_manager.get_network_recovery(FIXED_RUNTIME_SCOPE)
            if episode is None or episode.relaunch_attempts != 1:
                raise OperatorError("network relaunch requires its persisted reserved episode")
            try:
                started = owner_bound_application_startup(
                    runtime_input_lock=runtime_input_lock, checkpoint=fenced,
                    session_directory=runtime.session / "application-relaunch", require_ready=True,
                    state_manager=state_manager, recovery_launch_episode_id=episode.episode_id,
                )
            except Exception as exc:
                failed = getattr(exc, "startup_result", {})
                launches = failed.get("system_launch_count", 0) if isinstance(failed, dict) else 0
                raise
            launches = started.get("system_launch_count")
            return started

        if inspect_only:
            return inspect_network_disconnect_context(
                runtime, state_manager=state_manager, action_store=store, owner=owner,
                checkpoint=fenced, observe_context=context, scope_key=FIXED_RUNTIME_SCOPE,
                authorization="Current operator explicitly selected capture-only inspection of its prior zero-cost network Confirm: zero inputs, zero launches, no original-run acceptance.",
            )

        return recover_network_disconnect(
            runtime, state_manager=state_manager, action_store=store, owner=owner,
            checkpoint=fenced, observe_context=context, relaunch=relaunch,
            scope_key=FIXED_RUNTIME_SCOPE,
            authorization="Current operator explicitly selected bounded network recovery: one Confirm, at most one permitted launcher-only game launch, zero resource spend.",
        )
    except Exception as exc:
        if runtime is None:
            raise
        # Even a lost owner/post-capture failure must retain the actual attempted
        # inputs. Never turn the exception into readiness or renew its budget.
        failed = {
            "status": "unresolved" if runtime.input_count else "blocked",
            "reason": f"network_recovery_stopped:{type(exc).__name__}:{exc}",
            "scope_key": FIXED_RUNTIME_SCOPE, "game_input_count": runtime.input_count,
            "input_count": runtime.input_count, "system_launch_count": launches,
            "accounting_verified": (type(launches) is int and launches in (0, 1)
                                    and runtime.input_count in (0, 1)),
            "unresolved_action": store.has_action_block() or bool(runtime.input_count), "route_ready": False,
            "frame_directory": str(runtime.frames), "transport_events": str(runtime.events),
        }
        failed_path = runtime.session / "network-recovery-stopped.json"
        failed["result_path"] = str(failed_path)
        with failed_path.open("x", encoding="utf-8") as stream:
            json.dump(failed, stream, indent=2, sort_keys=True)
            stream.write("\n")
        return failed
    finally:
        try:
            if leased:
                store.release_lease(owner, time.time())
        finally:
            store.close()


def development_session_recover_network(*, live: bool, yes: bool, inspect_only: bool = False) -> str:
    """Run finite recovery or explicit zero-input inspection, with gameplay off."""
    if not live or not yes:
        raise OperatorError("recover-network requires explicit --live --yes")
    from automation_service.state import BotStateManager
    from scripts.navigation_development_boundary import RuntimeInputLock
    from automation_service.state import resolve_state_path
    existing_state = Path(resolve_state_path())
    if existing_state.resolve() != BotStateManager.DEFAULT_DB_PATH.resolve() or not existing_state.is_file():
        raise OperatorError("network recovery requires the existing canonical state database")

    operation = "inspect-network" if inspect_only else "recover-network"
    invocation_id = f"{operation}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    with RuntimeInputLock(owner="pnsctl-development-session:recover-network", invocation_id=invocation_id) as lock:
        with BotStateManager() as state:
            def checkpoint():
                lock.assert_held(lock.owner, lock.invocation_id)
                if (state.get_service_enabled()
                        or state._db.execute("SELECT 1 FROM flow_state WHERE enabled=1").fetchone()
                        or state.get_service_lease().owner_instance_id is not None
                        or state._db.execute(
                            "SELECT 1 FROM runs WHERE state IN ('CLAIMED','RUNNING','STOP_REQUESTED','RECOVERING')"
                        ).fetchone()):
                    raise OperatorError("standalone network recovery requires disabled controls and no service operator")
            checkpoint()
            if inspect_only:
                result = _owner_bound_network_recovery(
                    runtime_input_lock=lock, checkpoint=checkpoint,
                    session_directory=_development_session_directory(invocation_id),
                    state_manager=state, allow_relaunch=False, inspect_only=True,
                )
                if result.get("status") != "inspected_connected_context":
                    raise ApplicationStartupError(str(result.get("reason")), result)
            else:
                result = owner_bound_application_startup(
                    runtime_input_lock=lock, checkpoint=checkpoint,
                    session_directory=_development_session_directory(invocation_id),
                    require_ready=True, network_recovery=True, state_manager=state,
                )
    return json.dumps(result, sort_keys=True)


def owner_bound_application_startup(*, runtime_input_lock, checkpoint, session_directory: Path,
                                    flow_id: str | None = None, require_ready: bool = False,
                                    network_recovery: bool = False, state_manager=None,
                                    recovery_launch_episode_id: str | None = None) -> dict[str, Any]:
    """Observe or launch under the caller; reconnect only with explicit authority."""
    from scripts.navigation_development_boundary import NavigationBoundaryError, require_canonical_unresolved_clear
    from automation_service.state import BotStateManager
    from scripts.navigation_development_boundary import RuntimeInputLock
    from tasks.runtime_identity import FIXED_RUNTIME_SCOPE

    def recovery_episode():
        if state_manager is not None:
            return state_manager.get_network_recovery(FIXED_RUNTIME_SCOPE)
        # Ordinary startup must not bypass an unfinished recovery just because
        # its caller did not opt into issuing recovery inputs.
        if BotStateManager.DEFAULT_DB_PATH.is_file():
            with BotStateManager(read_only=True) as observed_state:
                return observed_state.get_network_recovery(FIXED_RUNTIME_SCOPE)
        return None

    if recovery_launch_episode_id is not None and (
        network_recovery or not isinstance(runtime_input_lock, RuntimeInputLock)
        or not isinstance(state_manager, BotStateManager) or state_manager.read_only
        or Path(state_manager.db_path).resolve() != BotStateManager.DEFAULT_DB_PATH.resolve()
    ):
        raise OperatorError("network launch requires the canonical reserved recovery owner/state")

    def gate():
        try:
            require_canonical_unresolved_clear()
        except NavigationBoundaryError as exc:
            raise OperatorError(str(exc)) from exc

    def fence():
        runtime_input_lock.assert_held(runtime_input_lock.owner, runtime_input_lock.invocation_id)
        checkpoint()
        if recovery_launch_episode_id is not None:
            episode = recovery_episode()
            if (episode is None or episode.episode_id != recovery_launch_episode_id
                    or episode.status not in {"OPEN", "DEFERRED"}
                    or episode.confirm_attempts != 1 or episode.confirm_transport_status != "returned"
                    or episode.relaunch_attempts != 1 or episode.relaunch_transport_status != "attempted"
                    or not episode.updated_at_utc <= time.time() < episode.deadline_at_utc):
                raise OperatorError("network recovery original launch budget or deadline exhausted")

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

    def guard_network(frame):
        detail = _network_dialog(frame)
        active = recovery_episode()
        encountered = detail.get("recognized") or detail.get("blocking_unknown_modal")
        if (not encountered and recovery_launch_episode_id is not None and active is not None
                and active.episode_id == recovery_launch_episode_id):
            # The one reserved launcher-only lifecycle call cannot recurse into
            # recovery. Its fence still checks the original budget/deadline.
            return False
        if not encountered and not (active is not None and active.status != "RECOVERED"):
            return False
        if detail.get("blocking_unknown_modal") or not network_recovery:
            raise OperatorError("network interruption requires exact authorized recovery:" + str(detail.get("reason")))
        recovery = _owner_bound_network_recovery(
            runtime_input_lock=runtime_input_lock, checkpoint=fence,
            session_directory=session_directory, state_manager=state_manager,
            allow_relaunch=result["system_launch_count"] == 0,
        )
        result.update(
            network_recovery=recovery, game_input_count=recovery["game_input_count"],
            input_count=recovery["input_count"],
            system_launch_count=result["system_launch_count"] + recovery["system_launch_count"],
            dispatch=recovery["game_input_count"] > 0, route_ready=recovery["route_ready"],
            action="bounded_network_recovery",
        )
        if not recovery["route_ready"] or recovery["status"] != "recovered":
            raise OperatorError("network recovery paused:" + str(recovery["reason"]))
        result.update(status="network_recovered", readiness="fresh_network_recovery_context")
        persist()
        return True

    transport_started = False
    try:
        before, before_png = capture("before")
        result.update(before_observation=before, before_frame="before.png")
        persist()
        focused = str(before["foreground_package"])
        if focused in {BLUESTACKS_PACKAGE, *BLUESTACKS_LAUNCHER_PACKAGES} and guard_network(before_png):
            return result
        if focused == BLUESTACKS_PACKAGE:
            # Existing route owns validation of its current Profile/Chapter context.
            result.update(status="already_foreground", foreground_package=focused,
                          action="observe_existing_game")
            after, after_png = capture("after")
            if after["foreground_package"] != BLUESTACKS_PACKAGE:
                raise OperatorError("Puzzles & Survival foreground changed during startup observation")
            result.update(after_observation=after, after_frame="after.png")
            if guard_network(after_png):
                return result
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
        episode = recovery_episode() if recovery_launch_episode_id is not None else None
        remaining = max(0.0, episode.deadline_at_utc - time.time()) if episode else 90.0
        deadline = time.monotonic() + min(90.0, remaining)
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
                if guard_network(frame):
                    return result
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


def development_session_recover_resource_home(*, live: bool, yes: bool) -> str:
    """Reacquire the existing navigation owner without replaying Resource Use."""
    if not live or not yes:
        raise OperatorError("recover-resource-home requires explicit --live --yes")
    from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
    from scripts.daily_resource_item_bluestacks import recover_resource_item_home
    from scripts.navigation_development_boundary import (
        DevelopmentSession, require_canonical_unresolved_clear,
    )

    invocation_id = f"resource-recover-home-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    session_directory = _development_session_directory(invocation_id)
    with DevelopmentSession(
        owner="pnsctl-resource-recover-home", invocation_id=invocation_id,
        session_directory=session_directory, max_inputs=1,
    ) as session:
        require_canonical_unresolved_clear()
        lock = session.runtime_input_lock
        runtime = LocalBlueStacksRuntime.connect(
            adb=str(BLUESTACKS_ADB), serial=BLUESTACKS_SERIAL,
            output_directory=session_directory / "native",
            workflow="resource-recover-home", execute=True,
        )
        runtime.max_inputs = 1
        runtime.checkpoint = lambda: lock.assert_held(session.owner, invocation_id)
        result = dict(recover_resource_item_home(runtime, session))
        result.update(
            session_directory=str(session_directory), runtime_session_directory=str(runtime.session),
            controls_changed=False, resource_effect_status="unchanged",
            route_execution_attempted=False,
        )
        session.remember_control("navigation_only_recovery", result)
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



def development_session_run_flow(
    flow_id: str,
    *,
    live: bool,
    yes: bool,
    max_inputs: int | None = None,
    recovery_only: bool = False,
    search_entry_only: bool = False,
    recovery_session: Path | None = None,
    enhancement_variant: str = "gear",
    delegated_receipt: Path | None = None,
    agent_identity: str | None = None,
    task_id: str | None = None,
    scenario: str | None = None,
    variant: str | None = None,
    runtime_scope: str | None = None,
    command_argv: Sequence[str] | None = None,
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
        if flow_id != WORLD_FLOW_ID:
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

    enhancement_reset_identity: str | None = None


    if flow_id == TROOP_TRAINING_FLOW_ID:
        raise OperatorError(
            "ordinary Training execution uses the canonical automation service; "
            "recover-home is navigation-only"
        )
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
            flow_id == ULTIMATE_FLOW_ID
            and recovery_session is None
        ):
            raise OperatorError("Ultimate recovery requires --recovery-session")
        if (
            flow_id == PERSONAL_MIGHT_FLOW_ID
            and recovery_session is None
        ):
            raise OperatorError("Personal Might recovery requires --recovery-session")
        if flow_id not in {
            CAMPAIGN_AP_FLOW_ID,
            ULTIMATE_FLOW_ID,
            ENHANCEMENT_FLOW_ID,
            WORLD_FLOW_ID,
            PERSONAL_MIGHT_FLOW_ID,
        }:
            raise OperatorError(
                "recovery-only is unsupported for this development flow"
            )
    if flow_id == ENHANCEMENT_FLOW_ID:
        enhancement_variant = str(enhancement_variant).strip().lower()
        if enhancement_variant not in {"gear", "chip", "module"}:
            raise OperatorError(
                "Enhancement development-session variant is unsupported"
            )
        identity_now = datetime.now(timezone.utc)
        enhancement_reset_identity = (
            f"local-{identity_now.date().isoformat()}-enhancement-family"
        )
    registration_snapshot = None
    if (
        flow_id in {
            WORLD_FLOW_ID,
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
                "enhancement_variant": enhancement_variant,
                "enhancement_reset_identity": enhancement_reset_identity,
                "enhancement_recovery_only": (
                    recovery_only
                    and flow_id == ENHANCEMENT_FLOW_ID
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
            }
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
            if flow_id == CAMPAIGN_AP_FLOW_ID:
                campaign_retained = result.get("campaign_transport_count")
                if type(campaign_retained) is not int or campaign_retained < 0:
                    raise OperatorError(
                        "Campaign AP route did not report retained transport accounting"
                    )
                route_retained_count = campaign_retained
            if flow_id == ULTIMATE_FLOW_ID:
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
                "runtime_observation": observation,
                "initial_observation": initial_observation.to_mapping(),
                "initial_frame_sha256": initial_observation.frame_sha256,
                "proof_topology": str(
                    result.get(
                        "proof_topology",
                        "continuous"
                        if flow_id
                        in {
                            WORLD_FLOW_ID,
                            ENHANCEMENT_FLOW_ID,
                            BIOENHANCER_FLOW_ID,
                            SUPPLY_FLOW_ID,
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
    if result.get("flow_id") == ENHANCEMENT_FLOW_ID:
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
        if retained_flow_id == CAMPAIGN_PROVING_FLOW_ID:
            queue = {"active_flow_id": retained_flow_id}
            lease = {
                "active_stage": "evidence_review",
                "runtime_ownership_state": "released",
                "unresolved_action_state": "clear",
            }
        elif retained_flow_id == ENHANCEMENT_FLOW_ID:
            queue, lease = _retained_enhancement_state(session_directory)
        elif retained_flow_id == WORLD_FLOW_ID:
            queue = {"active_flow_id": retained_flow_id}
            lease = {
                "active_stage": "evidence_review",
                "runtime_ownership_state": "released",
                "unresolved_action_state": "clear",
            }
        elif retained_flow_id in {
            CAMPAIGN_AP_FLOW_ID,
            RECRUITMENT_MAINTENANCE_FLOW_ID,
            BIOENHANCER_FLOW_ID,
            PERSONAL_MIGHT_FLOW_ID,
            SUPPLY_FLOW_ID,
        }:
            queue = {"active_flow_id": retained_flow_id}
            lease = {
                "active_stage": "evidence_review",
                "runtime_ownership_state": "released",
                "unresolved_action_state": "clear",
            }
        else:
            raise OperatorError(
                "released flow has no retained evidence adapter"
            )
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



def _run_troop_training_return_home(
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
    *,
    history_required: bool,
    runtime_input_lock=None,
    checkpoint=None,
) -> str:
    from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
    from scripts.navigation_development_boundary import (
        DevelopmentInitialObservation,
        DevelopmentSession,
    )
    from scripts.startup_recovery import classify_startup_frame
    from scripts.troop_training_bluestacks import (
        run_troop_training_home_recovery,
    )

    if queue.get("active_flow_id") != TROOP_TRAINING_FLOW_ID:
        raise OperatorError("manual Training recovery requires the active Training route")
    if (runtime_input_lock is None) != (checkpoint is None):
        raise OperatorError("borrowed Training recovery requires a lock and checkpoint")
    if lease.get("runtime_ownership_state") == "held" and runtime_input_lock is None:
        raise OperatorError(
            "the active controller must call recover-home with its held runtime lock"
        )
    invocation_id = (
        f"troop-training-recover-home-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    )
    session_directory = _development_session_directory(invocation_id)
    max_inputs = TROOP_TRAINING_MAX_INPUTS
    before = _checkpoint_hashes()
    session_options: dict[str, Any] = {}
    if runtime_input_lock is not None:
        session_options = {
            "runtime_input_lock": runtime_input_lock,
            "checkpoint": checkpoint,
        }
    result: dict[str, Any] = {
        "status": "blocked",
        "flow_id": TROOP_TRAINING_FLOW_ID,
        "recovery_mode": "manual_navigation_only",
        "training_action_resolved": False,
        "training_dispatch_count": 0,
        "controls_changed": False,
        "input_count": 0,
        "max_inputs": max_inputs,
        "session_directory": str(session_directory),
    }
    with DevelopmentSession(
        owner=f"pnsctl-troop-training-recover-home:{TROOP_TRAINING_FLOW_ID}",
        invocation_id=invocation_id,
        session_directory=session_directory,
        max_inputs=max_inputs,
        **session_options,
    ) as session:
        lock = session.runtime_input_lock
        lock_owner, lock_invocation = lock.owner, lock.invocation_id

        def fence() -> None:
            lock.assert_held(lock_owner, lock_invocation)
            if checkpoint is not None:
                checkpoint()

        current_queue, current_lease = _load_flow_delivery_state(
            require_runtime_held=False,
            allow_troop_training_recovery=True,
        )
        if (
            current_queue.get("active_flow_id") != TROOP_TRAINING_FLOW_ID
            or current_lease.get("active_stage") != lease.get("active_stage")
        ):
            raise OperatorError("Training flow-delivery authorization changed before recovery")
        history = _troop_training_recovery_history()
        if history_required and history is None:
            raise OperatorError(
                "released Training recovery requires canonical pending queue/action history"
            )
        if (
            current_lease.get("unresolved_action_state") != "clear"
            and history is None
        ):
            raise OperatorError(
                "Training recovery lacks its canonical unresolved action history"
            )
        runtime = LocalBlueStacksRuntime.connect(
            adb=str(BLUESTACKS_ADB),
            serial=BLUESTACKS_SERIAL,
            output_directory=session_directory / "native-runtime",
            workflow="troop-training-manual-recovery",
            execute=True,
        )
        runtime.max_inputs = max_inputs
        runtime.checkpoint = fence
        initial = runtime.capture("training-recovery-startup-source")
        source_path = session_directory / "source.png"
        source_path.write_bytes(initial.png)
        (session_directory / "startup-source.png").write_bytes(initial.png)
        startup_plan = classify_startup_frame(
            TROOP_TRAINING_FLOW_ID,
            initial.png,
        )
        observation = {
            "device_state": "device",
            "foreground_package": BLUESTACKS_PACKAGE,
            "native_width": BLUESTACKS_NATIVE_WIDTH,
            "native_height": BLUESTACKS_NATIVE_HEIGHT,
            "frame_sha256": initial.sha256,
        }
        typed_observation = DevelopmentInitialObservation(
            observation=observation,
            frame_sha256=initial.sha256,
            frame_path="source.png",
            invocation_id=invocation_id,
        )
        session.set_initial_observation(typed_observation)
        session.remember_control(
            "startup_recovery_plan",
            startup_plan.to_mapping(),
        )
        session.remember_control("canonical_training_history", history)
        session.remember_control("training_effect_mutated", False)
        if startup_plan.status != "clear":
            session.blocker = startup_plan.reason
            session.next_action = (
                "retain the startup source and require its exact startup recovery owner"
            )
            session.terminal_status = "blocked"
            recovery_result: dict[str, Any] = {
                "status": "blocked",
                "reason": startup_plan.reason,
                "input_count": 0,
                "training_execution_attempted": False,
                "training_action_resolved": False,
                "training_dispatch_count": 0,
                "controls_changed": False,
            }
        else:
            recovery_result = dict(
                run_troop_training_home_recovery(
                    runtime,
                    session=session,
                    checkpoint=fence,
                    max_inputs=max_inputs,
                )
            )
            session.terminal_status = (
                "navigation_complete"
                if recovery_result.get("status") == "completed"
                and recovery_result.get("final_home_recognized") is True
                else "blocked"
            )
            if session.terminal_status == "blocked":
                session.blocker = str(
                    recovery_result.get("reason") or "native Home recovery was not proven"
                )
                session.next_action = (
                    "retain Training action state and repair only the reported navigation proof"
                )
        result.update(
            {
                "status": session.terminal_status,
                "runtime_session_directory": str(runtime.session),
                "input_count": session.input_count,
                "action_count": len(session.actions),
                "startup_recovery_plan": startup_plan.to_mapping(),
                "canonical_training_history": history,
                "training_effect_status": (
                    "unchanged_unresolved"
                    if history and history.get("pending_statuses")
                    else "unchanged"
                ),
                "route_result": recovery_result,
            }
        )
    if _checkpoint_hashes() != before:
        raise OperatorError("manual Training recovery mutated a persistent checkpoint artifact")
    return json.dumps(result, sort_keys=True)


def bluestacks_recover_home(*, runtime_input_lock=None, checkpoint=None) -> str:
    queue, lease = _load_flow_delivery_state(
        require_runtime_held=False,
        allow_troop_training_recovery=True,
    )
    if lease.get("active_stage") not in {
        "live_preflight",
        "live_execution",
        "evidence_review",
    }:
        raise OperatorError(
            "recover-home is available only during an admitted live delivery stage"
        )
    if queue.get("active_flow_id") == TROOP_TRAINING_FLOW_ID:
        history = _troop_training_recovery_history()
        unresolved = lease.get("unresolved_action_state") != "clear"
        released = lease.get("runtime_ownership_state") != "held"
        if (unresolved or released) and history is None:
            raise OperatorError(
                "Training recovery requires canonical SQLite action/resource history"
            )
        return _run_troop_training_return_home(
            queue,
            lease,
            history_required=unresolved or released,
            runtime_input_lock=runtime_input_lock,
            checkpoint=checkpoint,
        )
    if lease.get("runtime_ownership_state") != "held":
        raise OperatorError("legacy flow recovery requires its held controller runtime")
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
    resource_recovery = development_sub.add_parser(
        "recover-resource-home",
        help="one exact Resources-list Back to verified Home; no item use; requires --live --yes",
    )
    resource_recovery.add_argument("--live", action="store_true")
    resource_recovery.add_argument("--yes", action="store_true")
    development_reconnect = development_sub.add_parser(
        "recover-network", help="bounded exact10054 recovery; requires --live --yes",
    )
    development_reconnect.add_argument("--live", action="store_true")
    development_reconnect.add_argument("--yes", action="store_true")
    development_reconnect.add_argument(
        "--inspect-only", action="store_true",
        help="zero-input fresh-Home inspection of its own returned Confirm; not original-run acceptance",
    )
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
            canonical_argv,
            application_startup=owner_bound_application_startup,
            native_route_bindings=_native_service_route_bindings(),
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
            elif args.development_command == "recover-resource-home":
                output = development_session_recover_resource_home(
                    live=bool(args.live), yes=bool(args.yes),
                )
            elif args.development_command == "recover-network":
                output = development_session_recover_network(
                    live=bool(args.live), yes=bool(args.yes), inspect_only=bool(args.inspect_only),
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
