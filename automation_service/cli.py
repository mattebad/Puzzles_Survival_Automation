"""Local controls, offline adapters, and explicitly supervised BlueStacks routes.

Native serve uses the existing service/flow controls, owner, claims, and dispatch fences.
Automatic mode remains unsupported.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import signal
import threading
import time
from typing import Sequence
from uuid import uuid4

from .adapters import AdapterError, FakeDeviceAdapter, ReplayDeviceAdapter
from .contracts import SchedulerFacts, ServiceMode
from .operations import OperationsService, structured_summary
from .registry import canonical_flow_specs
from .service import AutomationService, ServiceError
from .state import BotStateManager, StateBusyError, resolve_state_path


def _application_startup_directory(root: Path, run_id: str) -> Path:
    """Reserve a fresh evidence name for each invocation of a reused claim."""
    return Path(root) / f"application-startup-{run_id}-{uuid4().hex}"


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
    serve.add_argument("--flow", action="append", choices=("recruitment", "nova", "campaign", "bioenhancer", "supply", "ultimate", "enhancement", "personal-might"),
                       help="route to serve; repeat to select routes (default: recruitment)")
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
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
        try:
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous_handlers[signum] = signal.signal(signum, lambda *_: stop.set())
            with BotStateManager(state_path) as state:
                runner = None
                nova_runner = None
                campaign_runner = None
                bioenhancer_runner = None
                supply_runner = None
                ultimate_runner = None
                enhancement_runner = None
                personal_might_runner = None
                selected = args.flow or ["recruitment"]
                if native_serve:
                    from .recruitment import RecruitmentRunner
                    from .nova import NovaRunner
                    from .campaign import CampaignRunner
                    from .bioenhancer import BioenhancerRunner
                    from .supply import SupplyRunner
                    from .ultimate import UltimateRunner
                    from .enhancement import EnhancementRunner
                    from .personal_might import PersonalMightRunner

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
                application_startup = None
                if native_serve:
                    from scripts import pnsctl
                    if (str(Path(args.adb).resolve()), args.serial) != (str(pnsctl.BLUESTACKS_ADB.resolve()), pnsctl.BLUESTACKS_SERIAL):
                        raise ServiceError("native application startup requires the fixed BlueStacks runtime")
                    startup_root = (args.output_directory or state_path.parent / "application-startup")
                    def application_startup(flow_id, run_id, runtime_input_lock, checkpoint):
                        return pnsctl.owner_bound_application_startup(
                            runtime_input_lock=runtime_input_lock, checkpoint=checkpoint,
                            session_directory=_application_startup_directory(Path(startup_root), run_id),
                            flow_id=flow_id, require_ready=True)
                service = AutomationService(
                    mode=args.mode, adapter=adapter, state=state, recruitment_runner=runner,
                    nova_runner=nova_runner,
                    campaign_runner=campaign_runner,
                    bioenhancer_runner=bioenhancer_runner,
                    supply_runner=supply_runner,
                    ultimate_runner=ultimate_runner,
                    enhancement_runner=enhancement_runner,
                    personal_might_runner=personal_might_runner,
                    application_startup=application_startup,
                )
                if native_serve:
                    from .registry import BIOENHANCER_FLOW_ID, CAMPAIGN_FLOW_ID, ENHANCEMENT_FLOW_ID, NOVA_FLOW_ID, PERSONAL_MIGHT_FLOW_ID, RECRUITMENT_FLOW_ID, SUPPLY_FLOW_ID, ULTIMATE_FLOW_ID

                    service.serve(
                        account_id=args.account_id, server_id=args.server_id, stop=stop,
                        operator_request_id=args.operator_request_id,
                        emit=lambda result: print(json.dumps(result, sort_keys=True), flush=True),
                        flow_ids=tuple({"recruitment": RECRUITMENT_FLOW_ID, "nova": NOVA_FLOW_ID,
                                        "campaign": CAMPAIGN_FLOW_ID, "bioenhancer": BIOENHANCER_FLOW_ID,
                                        "supply": SUPPLY_FLOW_ID, "ultimate": ULTIMATE_FLOW_ID,
                                        "enhancement": ENHANCEMENT_FLOW_ID,
                                        "personal-might": PERSONAL_MIGHT_FLOW_ID}[flow] for flow in selected),
                    )
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
