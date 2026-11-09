"""Local controls, offline adapters, and explicitly supervised BlueStacks routes.

Native serve uses the existing service/flow controls, owner, claims, and dispatch fences.
Automatic mode remains unsupported.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import signal
import threading
import time
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from .adapters import AdapterError, FakeDeviceAdapter, ReplayDeviceAdapter
from .contracts import SchedulerFacts, ServiceMode
from .native_execution import NativeRouteBoundary
from .operations import OperationsService, structured_summary
from .registry import (
    ALLIANCE_HELP_FLOW_ID,
    ALLIANCE_DONATION_FLOW_ID,
    ALLIANCE_SHOP_FLOW_ID,
    DAILY_SHOPS_FLOW_ID,
    DAILY_REWARDS_FLOW_ID,
    RESOURCE_ITEM_FLOW_ID,
    NANO_MATERIAL_PRODUCTION_FLOW_ID,
    NANOWEAPON_FLOW_ID,
    HERO_DUEL_FLOW_ID,
    RECOMMENDED_RESEARCH_FLOW_ID,
    FOOD_FARM_BOOST_FLOW_ID,
    RUINS_FLOW_ID,
    HALL_OF_WAR_FLOW_ID,
    TROOP_TRAINING_FLOW_ID,
    WALI_UPGRADE_FLOW_ID,
    canonical_flow_specs,
    servable_flow_names,
)
from .service import AutomationService, ServiceError
from .state import BotStateManager, FlowInspectionDenied, FlowState, StateBusyError, resolve_state_path
from tasks.runtime_identity import BLUESTACKS_ADB, BLUESTACKS_SERIAL


def _application_startup_directory(root: Path, run_id: str) -> Path:
    """Reserve a fresh evidence name for each invocation of a reused claim."""
    return Path(root) / f"application-startup-{run_id}-{uuid4().hex}"


_MAX_SERVE_DURATION_SECONDS = 600.0
_ONCE_TERMINAL_STATUSES = frozenset({"completed", "deferred", "blocked"})


def _serve_duration_seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a number of seconds") from None
    if not math.isfinite(seconds) or not 0 < seconds <= _MAX_SERVE_DURATION_SECONDS:
        raise argparse.ArgumentTypeError(f"must be > 0 and <= {_MAX_SERVE_DURATION_SECONDS:g} seconds")
    return seconds



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="automation-service")
    parser.add_argument(
        "--mode",
        choices=("disabled", "observe_only", "dry_run", "supervised"),
        default=os.environ.get("AUTOMATION_SERVICE_MODE", "disabled"),
        help="service mode; automatic mode is intentionally unsupported",
    )
    parser.add_argument(
        "--adapter",
        choices=("fake", "replay", "bluestacks"),
        default=os.environ.get("AUTOMATION_SERVICE_ADAPTER", "fake"),
    )
    parser.add_argument(
        "--state-path",
        type=Path,
        default=None,
        help=(
            "SQLite state path; relative paths and AUTOMATION_SERVICE_STATE_PATH "
            "are resolved against the repository root"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("health")
    subparsers.add_parser("observe")
    subparsers.add_parser("summary")
    serve = subparsers.add_parser("serve")
    serve.add_argument("--live", action="store_true", help="explicitly permit the selected native routes")
    serve.add_argument("--recover-network-disconnect", action="store_true",
                       help="authorize one exact10054 Confirm and at most one permitted game launch per persistent episode")
    serve.add_argument("--flow", action="append", choices=tuple(servable_flow_names()), required=True,
                       help="required route to serve; repeat to select routes")
    serve.add_argument("--campaign-stage", default="1-15-9")
    serve.add_argument("--operator-request-id", default=None,
                       help="one explicit extra Enhancement/Ultimate run; preserves daily completion")
    serve.add_argument("--campaign-cadence-seconds", type=float, default=300.0,
                       help="wait after a completed AP drain before checking Campaign again (default: 300 seconds)")
    serve.add_argument("--adb", default="adb")
    serve.add_argument("--serial")
    serve.add_argument("--account-id")
    serve.add_argument("--server-id")
    serve.add_argument("--output-directory", type=Path)
    serve.add_argument("--once", action="store_true",
                       help="stop cooperatively after the first completed, deferred or blocked route report")
    serve.add_argument("--max-duration-seconds", type=_serve_duration_seconds, default=None,
                       help="cooperatively stop serve after this many seconds (0 < seconds <= 600)")
    enable = subparsers.add_parser("enable")
    enable.add_argument("flow_id")
    enable.add_argument("--now-utc-epoch", type=float, default=None)
    disable = subparsers.add_parser("disable")
    disable.add_argument("flow_id")
    disable.add_argument("--now-utc-epoch", type=float, default=None)
    emergency = subparsers.add_parser("emergency-stop")
    emergency.add_argument("--now-utc-epoch", type=float, default=None)
    emergency.add_argument("--reason", default="emergency stop")
    service_enable = subparsers.add_parser("service-enable")
    service_enable.add_argument("--now-utc-epoch", type=float, default=None)
    service_disable = subparsers.add_parser("service-disable")
    service_disable.add_argument("--reason", default="service disabled")
    service_disable.add_argument("--now-utc-epoch", type=float, default=None)
    run = subparsers.add_parser("run")
    run.add_argument("flow_id")
    run.add_argument("--live", action="store_true")
    run.add_argument("--account-id", default="cli-account")
    run.add_argument("--server-id", default="cli-server")
    run.add_argument("--reset-id", default="cli-reset")
    run.add_argument(
        "--operator-request-id",
        default=None,
        help="manual-run idempotency identity; generated when omitted",
    )
    run.add_argument("--now-utc-epoch", type=float, default=None)
    shadow = subparsers.add_parser("shadow")
    shadow.add_argument("flow_id", nargs="?")
    shadow.add_argument("--account-id", default="cli-account")
    shadow.add_argument("--server-id", default="cli-server")
    shadow.add_argument("--reset-id", default="cli-reset")
    shadow.add_argument("--now-utc-epoch", type=float, default=None)
    inspect = subparsers.add_parser(
        "inspect-rearm",
        help=(
            "audited zero-effect inspection rearm of an exhausted, disabled, blocked flow "
            "(state-only; --preview is read-only)"
        ),
    )
    inspect.add_argument("flow_id")
    inspect.add_argument("--preview", action="store_true",
                         help="report eligibility and the current CAS facts without mutating state")
    inspect.add_argument("--expected-generation", type=int, default=None)
    inspect.add_argument("--expected-row-version", type=int, default=None)
    inspect.add_argument("--expected-consecutive-failures", type=int, default=None)
    inspect.add_argument("--attest-untracked-failures", type=int, default=0,
                         help="exact count of failures that predate the attempt ledger, attested by --evidence")
    inspect.add_argument("--attest-zero-gameplay-attempt", type=int, action="append", default=[],
                         metavar="ATTEMPT_SEQ",
                         help="ledger attempt with missing/unverified accounting whose zero gameplay effect "
                              "--evidence proves; repeat for exactly every such attempt in the window")
    inspect.add_argument("--attest-zero-gameplay-run", action="append", default=[],
                         metavar="RUN_ID",
                         help="legacy run with unverified accounting and no attempt-ledger rows whose zero "
                              "gameplay effect --evidence proves; repeat for exactly every such window run")
    inspect.add_argument("--evidence", type=Path, default=None,
                         help="retained inspection evidence file inside the repository")
    inspect.add_argument("--reason", default=None)
    inspect.add_argument("--now-utc-epoch", type=float, default=None)
    return parser


def _adapter(name: str) -> FakeDeviceAdapter | ReplayDeviceAdapter:
    """Build one of the CLI's non-transport adapters.

    The CLI intentionally exposes only fake and replay adapters.  Neither adapter
    can dispatch device input, which keeps disabled/observe-only commands
    independent from any registry or evidence authority.
    """
    if name == "fake":
        return FakeDeviceAdapter()
    if name == "replay":
        return ReplayDeviceAdapter()
    raise ValueError(f"unsupported adapter: {name}")


def _initialize_state_database(path: Path) -> None:
    """Create the canonical database and seed static flows disabled."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with BotStateManager(path) as state:
        state.initialize_flows(canonical_flow_specs())


_CANONICAL_TABLE_COLUMNS = {
    "service_control": {
        "singleton_id",
        "enabled",
        "generation",
        "emergency_reason",
        "emergency_at_utc",
        "updated_at_utc",
        "row_version",
    },
    "flow_state": {
        "flow_id",
        "enabled",
        "generation",
        "blocked",
        "priority",
        "cadence",
        "max_attempts",
        "next_occurrence_key",
        "row_version",
    },
    "runs": {
        "run_id",
        "flow_id",
        "occurrence_key",
        "reset_id",
        "claimed_flow_generation",
        "service_generation",
        "owner_instance_id",
        "mode",
        "state",
        "max_inputs",
        "max_actions",
        "row_version",
    },
    "actions": {
        "action_id",
        "run_id",
        "sequence_no",
        "idempotency_key",
        "semantic_action_key",
        "state",
        "row_version",
    },
}


def _database_probe(path: Path) -> bool:
    """Return true only for an intact canonical BotStateManager database."""

    if not path.is_file():
        return False
    try:
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        try:
            if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                return False
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if set(_CANONICAL_TABLE_COLUMNS) - tables:
                return False
            for table, expected_columns in _CANONICAL_TABLE_COLUMNS.items():
                actual_columns = {
                    row[1]
                    for row in connection.execute(f"PRAGMA table_info({table})")
                }
                if not expected_columns <= actual_columns:
                    return False
            service_row = connection.execute(
                "SELECT COUNT(*) FROM service_control WHERE singleton_id = 1"
            ).fetchone()
            return service_row == (1,)
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        return False


def _structured_error(exc: BaseException) -> dict[str, object]:
    """Return the stable operator-facing failure shape for expected contention."""

    if isinstance(exc, StateBusyError) or (
        isinstance(exc, sqlite3.OperationalError)
        and any(marker in str(exc).casefold() for marker in ("busy", "locked"))
    ):
        return {
            "status": "error",
            "reason": "SQLITE_BUSY",
            "retryable": True,
        }
    reason = getattr(exc, "reason", None)
    retryable = getattr(exc, "retryable", None)
    if reason is not None:
        payload: dict[str, object] = {
            "status": "error",
            "reason": reason,
            "retryable": bool(retryable),
        }
        return payload
    return {"status": "error", "error": str(exc)}


def _flow_failure_facts(flow: FlowState | None) -> dict[str, object] | None:
    """Operator-facing CAS and retry-window facts for one flow."""

    if flow is None:
        return None
    return {
        "flow_id": flow.flow_id,
        "enabled": flow.enabled,
        "blocked": flow.blocked,
        "blocked_reason": flow.blocked_reason,
        "generation": flow.generation,
        "row_version": flow.row_version,
        "consecutive_failures": flow.consecutive_failures,
        "inspected_failure_baseline": flow.inspected_failure_baseline,
        "retry_window_failures": flow.retry_window_failures,
        "max_attempts": flow.max_attempts,
    }


def _inspect_rearm(args: argparse.Namespace, state_path: Path) -> int:
    """Preview or apply one audited zero-effect inspected retry rearm."""

    if not _database_probe(state_path):
        print(json.dumps({"status": "error", "reason": "STATE_UNAVAILABLE", "retryable": False}, sort_keys=True))
        return 2
    now = float(args.now_utc_epoch) if args.now_utc_epoch is not None else time.time()
    try:
        if args.preview:
            with BotStateManager(state_path, read_only=True) as state:
                review = state.review_flow_inspection(
                    args.flow_id,
                    attested_untracked_failures=args.attest_untracked_failures,
                    attested_zero_gameplay_attempts=tuple(args.attest_zero_gameplay_attempt),
                    attested_zero_gameplay_runs=tuple(args.attest_zero_gameplay_run),
                    now_utc_epoch=now,
                )
            print(json.dumps({
                "command": "inspect-rearm",
                "preview": True,
                "status": "eligible" if review.eligible else "denied",
                "reason": review.reason,
                "flow": _flow_failure_facts(review.flow),
                "required_attested_untracked_failures": review.untracked_failures,
                "last_attempt_seq": review.last_attempt_seq,
                "window": review.window_summary,
            }, sort_keys=True))
            return 0 if review.eligible else 2
        if (
            args.expected_generation is None
            or args.expected_row_version is None
            or args.expected_consecutive_failures is None
            or args.evidence is None
            or args.reason is None
        ):
            raise FlowInspectionDenied("INSPECTION_ARGUMENTS_REQUIRED")
        with BotStateManager(state_path) as state:
            inspection = state.inspect_rearm_flow(
                args.flow_id,
                expected_generation=args.expected_generation,
                expected_row_version=args.expected_row_version,
                expected_consecutive_failures=args.expected_consecutive_failures,
                reason=args.reason,
                evidence_path=args.evidence,
                attested_untracked_failures=args.attest_untracked_failures,
                attested_zero_gameplay_attempts=tuple(args.attest_zero_gameplay_attempt),
                attested_zero_gameplay_runs=tuple(args.attest_zero_gameplay_run),
                now_utc_epoch=now,
            )
            flow = state.get_flow(args.flow_id)
        print(json.dumps({
            "command": "inspect-rearm",
            "preview": False,
            "status": "rearmed",
            "inspection_id": inspection.inspection_id,
            "attested_untracked_failures": inspection.attested_untracked_failures,
            "evidence_reference": inspection.evidence_reference,
            "evidence_sha256": inspection.evidence_sha256,
            "flow": _flow_failure_facts(flow),
            "window": inspection.window_summary,
        }, sort_keys=True))
        return 0
    except (FlowInspectionDenied, StateBusyError, sqlite3.OperationalError, ValueError) as exc:
        print(json.dumps(_structured_error(exc), sort_keys=True))
        return 2



def main(
    argv: Sequence[str] | None = None,
    *,
    application_startup: Callable[..., Mapping[str, Any]] | None = None,
    native_route_bindings: Mapping[str, NativeRouteBoundary] | None = None,
) -> int:
    """Run the service CLI.

    Native serve needs an owner-bound application startup. The operator composition root
    (``scripts/pnsctl.py``) supplies it so this package never imports the operator layer.
    """
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    if args.command == "inspect-rearm":
        # State-only operator decision: no adapter, device, or serve mode is opened.
        return _inspect_rearm(args, Path(resolve_state_path(args.state_path)))
    native_serve = args.command == "serve" and args.adapter == "bluestacks"
    if args.adapter == "bluestacks" and (
        not native_serve or args.mode != "supervised" or not args.live
        or not args.serial or not args.account_id or not args.server_id
    ):
        print("BlueStacks requires supervised serve --live, --serial, --account-id and --server-id", file=sys.stderr)
        return 2
    if args.mode == "supervised" and not native_serve:
        print(
            "supervised mode requires the executor-bound BlueStacks adapter",
            file=sys.stderr,
        )
        return 2
    if args.command == "serve" and args.recover_network_disconnect and not native_serve:
        print("network recovery requires the supervised native --live boundary", file=sys.stderr)
        return 2
    if args.command == "serve" and args.once and not native_serve:
        print("--once requires the supervised native --live boundary", file=sys.stderr)
        return 2
    adapter = None if native_serve else _adapter(args.adapter)
    state_path = Path(resolve_state_path(args.state_path))
    observation_only = args.command == "shadow" or (
        args.command == "run" and not args.live
    )
    if args.command in {
        "enable",
        "disable",
        "emergency-stop",
        "service-enable",
        "service-disable",
        "status",
        "run",
        "shadow",
    }:
        try:
            with BotStateManager(
                state_path, read_only=observation_only
            ) as state:
                service = AutomationService(
                    mode=args.mode,
                    adapter=adapter,
                    state=state,
                )
                if args.command == "status":
                    snapshot = service.status()
                    flow_generations = {
                        flow_id: state.get_flow(flow_id).generation
                        for flow_id in (snapshot.flow_enabled or {})
                        if state.get_flow(flow_id) is not None
                    }
                    payload = {
                        "schema": "automation-service-status-v2",
                        "mode": snapshot.mode.value,
                        "adapter": snapshot.adapter_kind,
                        "registration_status": (
                            "REGISTERED"
                            if snapshot.registered_flows
                            else "NOT_REGISTERED"
                        ),
                        "scheduler_eligible": snapshot.scheduler_eligible,
                        "registered_flows": list(snapshot.registered_flows),
                        "disabled_flows": list(snapshot.disabled_flows),
                        "service_enabled": snapshot.service_enabled,
                        "service_generation": state.get_service().generation,
                        "flow_enabled": snapshot.flow_enabled or {},
                        "flow_generations": flow_generations,
                    }
                    print(json.dumps(payload, sort_keys=True))
                    return 0
                now = (
                    float(args.now_utc_epoch)
                    if getattr(args, "now_utc_epoch", None) is not None
                    else time.time()
                )
                if args.command == "enable":
                    state_value = service.enable_flow(
                        args.flow_id, now_utc_epoch=now
                    )
                    payload = {
                        "command": "enable",
                        "flow_id": args.flow_id,
                        "enabled": state_value.enabled,
                        "generation": state_value.generation,
                    }
                elif args.command == "disable":
                    state_value = service.disable_flow(
                        args.flow_id, now_utc_epoch=now
                    )
                    payload = {
                        "command": "disable",
                        "flow_id": args.flow_id,
                        "enabled": state_value.enabled,
                        "generation": state_value.generation,
                    }
                elif args.command == "service-enable":
                    service_control = service.set_service_enabled(
                        True, now_utc_epoch=now
                    )
                    payload = {
                        "command": "service-enable",
                        "enabled": service_control.enabled,
                        "generation": service_control.generation,
                    }
                elif args.command == "service-disable":
                    service_control = service.set_service_enabled(
                        False,
                        emergency_reason=args.reason,
                        now_utc_epoch=now,
                    )
                    payload = {
                        "command": "service-disable",
                        "enabled": service_control.enabled,
                        "generation": service_control.generation,
                        "emergency_reason": service_control.emergency_reason,
                    }
                elif args.command == "emergency-stop":
                    service_control = service.emergency_stop(
                        args.reason, now_utc_epoch=now
                    )
                    payload = {
                        "command": "emergency-stop",
                        "enabled": service_control.enabled,
                        "generation": service_control.generation,
                        "emergency_reason": service_control.emergency_reason,
                    }
                else:
                    flow_id = getattr(args, "flow_id", None)
                    descriptor = (
                        service.flow_descriptor(flow_id)
                        if flow_id is not None
                        else None
                    )
                    facts = SchedulerFacts(
                        args.account_id,
                        args.server_id,
                        args.reset_id,
                        now,
                        health_ok=True,
                        accepted_product=(
                            descriptor.accepted_product
                            if descriptor is not None
                            else False
                        ),
                        product_revision=(
                            descriptor.product_revision
                            if descriptor is not None
                            else None
                        ),
                        registration_status=(
                            descriptor.registration_status
                            if descriptor is not None
                            else "NOT_REGISTERED"
                        ),
                        scheduler_eligible=(
                            descriptor.scheduler_eligible
                            if descriptor is not None
                            else False
                        ),
                        owner_available=True,
                        clock_ok=True,
                        reset_agreement=True,
                    )
                    report = service.run(
                        flow_id,
                        facts,
                        live=args.command == "run" and args.live,
                        operator_request_id=getattr(
                            args, "operator_request_id", None
                        ),
                    )
                    candidate = (
                        {
                            "flow_id": report.candidate.descriptor.flow_id,
                            "occurrence_key": report.candidate.occurrence_key,
                            "run_id": (
                                report.candidate.claim.run_id
                                if report.candidate.claim is not None
                                else None
                            ),
                        }
                        if report.candidate is not None
                        else None
                    )
                    payload = {
                        "command": args.command,
                        "reason": report.reason_code,
                        "candidate": candidate,
                        "result": (
                            report.result.to_mapping()
                            if report.result is not None
                            else None
                        ),
                        "transport_count": 0,
                    }
                    if args.command == "run" and args.live and report.candidate is None:
                        print(json.dumps(payload, sort_keys=True))
                        return 2
                print(json.dumps(payload, sort_keys=True))
                return 0
        except (ServiceError, StateBusyError, sqlite3.OperationalError, ValueError) as exc:
            print(json.dumps(_structured_error(exc), sort_keys=True))
            return 2

    if args.command == "serve":
        stop = threading.Event()
        previous_handlers = {}
        terminal_reported = threading.Event()
        duration_elapsed = threading.Event()
        duration_timer = None

        def stop_after_duration() -> None:
            duration_elapsed.set()
            stop.set()

        def emit(result: Mapping[str, Any]) -> None:
            print(json.dumps(result, sort_keys=True), flush=True)
            if args.once and result.get("status") in _ONCE_TERMINAL_STATUSES:
                terminal_reported.set()
                stop.set()

        try:
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous_handlers[signum] = signal.signal(signum, lambda *_: stop.set())
            if args.max_duration_seconds is not None:
                duration_timer = threading.Timer(args.max_duration_seconds, stop_after_duration)
                duration_timer.daemon = True
                duration_timer.start()
            with BotStateManager(state_path) as state:
                runner = None
                nova_runner = None
                campaign_runner = None
                bioenhancer_runner = None
                supply_runner = None
                ultimate_runner = None
                enhancement_runner = None
                personal_might_runner = None
                daily_rewards_runner = None
                resource_item_runner = None
                ruins_runner = None
                alliance_help_runner = None
                alliance_donation_runner = None
                alliance_shop_runner = None
                nano_material_production_runner = None
                nanoweapon_runner = None
                hero_duel_runner = None
                recommended_research_runner = None
                food_farm_boost_runner = None
                daily_shops_runner = None
                hall_of_war_runner = None
                troop_training_runner = None
                wali_upgrade_runner = None
                selected = args.flow
                if native_serve:
                    from .recruitment import RecruitmentRunner
                    from .nova import NovaRunner
                    from .campaign import CampaignRunner
                    from .bioenhancer import BioenhancerRunner
                    from .supply import SupplyRunner
                    from .ultimate import UltimateRunner
                    from .enhancement import EnhancementRunner
                    from .personal_might import PersonalMightRunner
                    from .daily_rewards import DailyRewardsRunner
                    from .resource_item import ResourceItemRunner
                    from .ruins import RuinsRunner
                    from .alliance_help import AllianceHelpRunner
                    from .alliance_donation import AllianceDonationRunner
                    from .alliance_shop import AllianceShopRunner
                    from .daily_shops import DailyShopsRunner
                    from .nano_material_production import NanoMaterialProductionRunner
                    from .nanoweapon import NanoweaponRunner
                    from .hero_duel import HeroDuelRunner
                    from .recommended_research import RecommendedResearchRunner
                    from .food_farm_boost import FoodFarmBoostRunner
                    from .hall_of_war import HallOfWarRunner
                    from .troop_training import TroopTrainingRunner
                    from .wali_upgrade import WaliUpgradeRunner

                    if "recruitment" in selected:
                        runner = RecruitmentRunner(
                            adb=args.adb, serial=args.serial,
                            output_directory=args.output_directory or state_path.parent / "recruitment-sessions",
                            maintenance_path=state_path.with_suffix(".recruitment.sqlite3"),
                        )
                    if "nova" in selected:
                        nova_runner = NovaRunner(
                            adb=args.adb, serial=args.serial,
                            output_directory=args.output_directory or state_path.parent / "nova-sessions",
                        )
                    if "campaign" in selected:
                        campaign_runner = CampaignRunner(
                            adb=args.adb, serial=args.serial,
                            output_directory=args.output_directory or state_path.parent / "campaign-sessions",
                            stage=args.campaign_stage, cadence_seconds=args.campaign_cadence_seconds,
                        )
                    if "bioenhancer" in selected:
                        bioenhancer_runner = BioenhancerRunner(
                            adb=args.adb, serial=args.serial,
                            output_directory=args.output_directory or state_path.parent / "bioenhancer-sessions",
                        )
                    if "supply" in selected:
                        supply_runner = SupplyRunner(
                            adb=args.adb, serial=args.serial,
                            output_directory=args.output_directory or state_path.parent / "supply-sessions",
                        )
                    if "ultimate" in selected:
                        ultimate_runner = UltimateRunner(
                            adb=args.adb, serial=args.serial,
                            output_directory=args.output_directory or state_path.parent / "ultimate-sessions",
                        )
                    if "enhancement" in selected:
                        enhancement_runner = EnhancementRunner(
                            adb=args.adb, serial=args.serial,
                            output_directory=args.output_directory or state_path.parent / "enhancement-sessions",
                        )
                    if "personal-might" in selected:
                        personal_might_runner = PersonalMightRunner(
                            adb=args.adb, serial=args.serial,
                            output_directory=args.output_directory or state_path.parent / "personal-might-sessions",
                        )
                    if "daily-rewards" in selected:
                        if native_route_bindings is None or DAILY_REWARDS_FLOW_ID not in native_route_bindings:
                            raise ServiceError("daily-rewards native binding is supplied by scripts/pnsctl.py automation-service")
                        daily_rewards_runner = DailyRewardsRunner(
                            adb=args.adb, serial=args.serial,
                            output_directory=args.output_directory or state_path.parent / "daily-rewards-sessions",
                            native=native_route_bindings[DAILY_REWARDS_FLOW_ID],
                        )
                    if "resource-item" in selected:
                        if native_route_bindings is None or RESOURCE_ITEM_FLOW_ID not in native_route_bindings:
                            raise ServiceError("resource-item native binding is supplied by scripts/pnsctl.py automation-service")
                        resource_item_runner = ResourceItemRunner(
                            adb=args.adb, serial=args.serial,
                            output_directory=args.output_directory or state_path.parent / "resource-item-sessions",
                            native=native_route_bindings[RESOURCE_ITEM_FLOW_ID],
                        )
                    if "ruins" in selected:
                        if native_route_bindings is None or RUINS_FLOW_ID not in native_route_bindings:
                            raise ServiceError("ruins native binding is supplied by scripts/pnsctl.py automation-service")
                        ruins_runner = RuinsRunner(
                            native=native_route_bindings[RUINS_FLOW_ID],
                            output_directory=args.output_directory or state_path.parent / "ruins-sessions",
                        )
                    if "alliance-help" in selected:
                        if native_route_bindings is None or ALLIANCE_HELP_FLOW_ID not in native_route_bindings:
                            raise ServiceError("alliance-help native binding is supplied by scripts/pnsctl.py automation-service")
                        alliance_help_runner = AllianceHelpRunner(
                            adb=args.adb,
                            serial=args.serial,
                            output_directory=args.output_directory or state_path.parent / "alliance-help-sessions",
                            native=native_route_bindings[ALLIANCE_HELP_FLOW_ID],
                        )
                    if "alliance-donation" in selected:
                        if native_route_bindings is None or ALLIANCE_DONATION_FLOW_ID not in native_route_bindings:
                            raise ServiceError("alliance-donation native binding is supplied by scripts/pnsctl.py automation-service")
                        alliance_donation_runner = AllianceDonationRunner(
                            adb=args.adb,
                            serial=args.serial,
                            output_directory=args.output_directory or state_path.parent / "alliance-donation-sessions",
                            native=native_route_bindings[ALLIANCE_DONATION_FLOW_ID],
                        )
                    if "alliance-shop" in selected:
                        if native_route_bindings is None or ALLIANCE_SHOP_FLOW_ID not in native_route_bindings:
                            raise ServiceError("alliance-shop native binding is supplied by scripts/pnsctl.py automation-service")
                        alliance_shop_runner = AllianceShopRunner(
                            adb=args.adb,
                            serial=args.serial,
                            output_directory=args.output_directory or state_path.parent / "alliance-shop-sessions",
                            native=native_route_bindings[ALLIANCE_SHOP_FLOW_ID],
                        )
                    if "daily-shops" in selected:
                        if native_route_bindings is None or DAILY_SHOPS_FLOW_ID not in native_route_bindings:
                            raise ServiceError("daily-shops native binding is supplied by scripts/pnsctl.py automation-service")
                        daily_shops_runner = DailyShopsRunner(
                            adb=args.adb,
                            serial=args.serial,
                            output_directory=args.output_directory or state_path.parent / "daily-shops-sessions",
                            native=native_route_bindings[DAILY_SHOPS_FLOW_ID],
                        )
                    if "nano-material-production" in selected:
                        if native_route_bindings is None or NANO_MATERIAL_PRODUCTION_FLOW_ID not in native_route_bindings:
                            raise ServiceError("nano-material-production native binding is supplied by scripts/pnsctl.py automation-service")
                        nano_material_production_runner = NanoMaterialProductionRunner(
                            adb=args.adb,
                            serial=args.serial,
                            output_directory=args.output_directory or state_path.parent / "nano-material-production-sessions",
                            native=native_route_bindings[NANO_MATERIAL_PRODUCTION_FLOW_ID],
                        )
                    if "nanoweapon" in selected:
                        if native_route_bindings is None or NANOWEAPON_FLOW_ID not in native_route_bindings:
                            raise ServiceError("nanoweapon native binding is supplied by scripts/pnsctl.py automation-service")
                        nanoweapon_runner = NanoweaponRunner(
                            adb=args.adb,
                            serial=args.serial,
                            output_directory=args.output_directory or state_path.parent / "nanoweapon-sessions",
                            native=native_route_bindings[NANOWEAPON_FLOW_ID],
                        )
                    if "hero-duel" in selected:
                        if native_route_bindings is None or HERO_DUEL_FLOW_ID not in native_route_bindings:
                            raise ServiceError("hero-duel native binding is supplied by scripts/pnsctl.py automation-service")
                        hero_duel_runner = HeroDuelRunner(
                            adb=args.adb,
                            serial=args.serial,
                            output_directory=args.output_directory or state_path.parent / "hero-duel-sessions",
                            native=native_route_bindings[HERO_DUEL_FLOW_ID],
                        )
                    if "recommended-research" in selected:
                        if native_route_bindings is None or RECOMMENDED_RESEARCH_FLOW_ID not in native_route_bindings:
                            raise ServiceError("recommended-research native binding is supplied by scripts/pnsctl.py automation-service")
                        recommended_research_runner = RecommendedResearchRunner(
                            adb=args.adb,
                            serial=args.serial,
                            output_directory=args.output_directory or state_path.parent / "recommended-research-sessions",
                            native=native_route_bindings[RECOMMENDED_RESEARCH_FLOW_ID],
                        )
                    if "food-farm-boost" in selected:
                        if native_route_bindings is None or FOOD_FARM_BOOST_FLOW_ID not in native_route_bindings:
                            raise ServiceError("food-farm-boost native binding is supplied by scripts/pnsctl.py automation-service")
                        food_farm_boost_runner = FoodFarmBoostRunner(
                            adb=args.adb,
                            serial=args.serial,
                            output_directory=args.output_directory or state_path.parent / "food-farm-boost-sessions",
                            native=native_route_bindings[FOOD_FARM_BOOST_FLOW_ID],
                        )
                    if "hall-of-war" in selected:
                        if native_route_bindings is None or HALL_OF_WAR_FLOW_ID not in native_route_bindings:
                            raise ServiceError("hall-of-war native binding is supplied by scripts/pnsctl.py automation-service")
                        hall_of_war_runner = HallOfWarRunner(
                            adb=args.adb,
                            serial=args.serial,
                            output_directory=args.output_directory or state_path.parent / "hall-of-war-sessions",
                            native=native_route_bindings[HALL_OF_WAR_FLOW_ID],
                        )
                    if "troop-training" in selected:
                        if native_route_bindings is None or TROOP_TRAINING_FLOW_ID not in native_route_bindings:
                            raise ServiceError("troop-training native binding is supplied by scripts/pnsctl.py automation-service")
                        troop_training_runner = TroopTrainingRunner(
                            adb=args.adb,
                            serial=args.serial,
                            output_directory=args.output_directory or state_path.parent / "troop-training-sessions",
                            native=native_route_bindings[TROOP_TRAINING_FLOW_ID],
                        )
                    if "wali-upgrade" in selected:
                        if native_route_bindings is None or WALI_UPGRADE_FLOW_ID not in native_route_bindings:
                            raise ServiceError("wali-upgrade native binding is supplied by scripts/pnsctl.py automation-service")
                        wali_upgrade_runner = WaliUpgradeRunner(
                            adb=args.adb,
                            serial=args.serial,
                            output_directory=args.output_directory or state_path.parent / "wali-upgrade-sessions",
                            native=native_route_bindings[WALI_UPGRADE_FLOW_ID],
                        )
                service_startup = None
                if native_serve:
                    if application_startup is None:
                        raise ServiceError("native application startup is supplied by scripts/pnsctl.py automation-service")
                    if (str(Path(args.adb).resolve()), args.serial) != (str(BLUESTACKS_ADB.resolve()), BLUESTACKS_SERIAL):
                        raise ServiceError("native application startup requires the fixed BlueStacks runtime")
                    startup_root = (args.output_directory or state_path.parent / "application-startup")
                    def service_startup(flow_id, run_id, runtime_input_lock, checkpoint):
                        recovery_options = (
                            {"network_recovery": True, "state_manager": state}
                            if args.recover_network_disconnect else {}
                        )
                        return application_startup(
                            runtime_input_lock=runtime_input_lock, checkpoint=checkpoint,
                            session_directory=_application_startup_directory(Path(startup_root), run_id),
                            flow_id=flow_id, require_ready=True, **recovery_options)
                service = AutomationService(
                    mode=args.mode, adapter=adapter, state=state, recruitment_runner=runner,
                    nova_runner=nova_runner,
                    campaign_runner=campaign_runner,
                    bioenhancer_runner=bioenhancer_runner,
                    supply_runner=supply_runner,
                    ultimate_runner=ultimate_runner,
                    enhancement_runner=enhancement_runner,
                    personal_might_runner=personal_might_runner,
                    daily_rewards_runner=daily_rewards_runner,
                    resource_item_runner=resource_item_runner,
                    application_startup=service_startup,
                    ruins_runner=ruins_runner,
                    alliance_help_runner=alliance_help_runner,
                    alliance_donation_runner=alliance_donation_runner,
                    alliance_shop_runner=alliance_shop_runner,
                    daily_shops_runner=daily_shops_runner,
                    nano_material_production_runner=nano_material_production_runner,
                    nanoweapon_runner=nanoweapon_runner,
                    hero_duel_runner=hero_duel_runner,
                    recommended_research_runner=recommended_research_runner,
                    food_farm_boost_runner=food_farm_boost_runner,
                    hall_of_war_runner=hall_of_war_runner,
                    troop_training_runner=troop_training_runner,
                    wali_upgrade_runner=wali_upgrade_runner,
                )
                if native_serve:
                    flow_names = servable_flow_names()

                    service.serve(
                        account_id=args.account_id, server_id=args.server_id, stop=stop,
                        operator_request_id=args.operator_request_id,
                        emit=emit,
                        flow_ids=tuple(flow_names[flow] for flow in selected),
                    )
                    if duration_elapsed.is_set() and not terminal_reported.is_set():
                        print(json.dumps({"status": "stopped", "reason": "MAX_DURATION_ELAPSED"},
                                         sort_keys=True), flush=True)
                        return 1 if args.once else 0
                else:
                    while not stop.is_set():
                        health = service.health(current_state=service.mode.value, current_task=None)
                        if not health.healthy:
                            return 1
                        stop.wait(30)
                return 0
        except (ServiceError, StateBusyError, sqlite3.OperationalError, ValueError) as exc:
            print(json.dumps(_structured_error(exc), sort_keys=True))
            return 2
        finally:
            if duration_timer is not None:
                duration_timer.cancel()
            for signum, previous in previous_handlers.items():
                signal.signal(signum, previous)

    observed_frame_id = None
    service = AutomationService(
        mode=ServiceMode.OBSERVE_ONLY
        if args.command == "observe"
        else args.mode,
        adapter=adapter,
        operations=OperationsService(
            adapter_status=adapter.status,
            database_probe=lambda: _database_probe(state_path),
            lease_held=lambda: False,
            disk_path=str(state_path.parent),
        ),
    )
    if args.command == "observe":
        try:
            observed_frame_id = service.observe().frame_id
        except AdapterError as exc:
            print(
                json.dumps(
                    {
                        "schema": "automation-service-observation-v1",
                        "observed": False,
                        "reason": str(exc),
                    },
                    sort_keys=True,
                )
            )
            return 1
    health = service.health(
        current_state="observe_only" if args.command == "observe" else "disabled",
        current_task=None,
    )
    payload = (
        structured_summary(health=health)
        if args.command == "summary"
        else health.to_mapping()
        | (
            {"observed": True, "frame_id": observed_frame_id}
            if args.command == "observe"
            else {}
        )
    )
    print(json.dumps(payload, sort_keys=True))
    return 0 if health.healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
