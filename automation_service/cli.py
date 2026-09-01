"""Local, non-arbitrary automation-service CLI.

The CLI exposes status/health and fake/replay execution only.  It has no ADB, coordinate,
shell, remote, or automatic mode endpoint.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from typing import Sequence

from .adapters import AdapterError, FakeDeviceAdapter, ReplayDeviceAdapter
from .contracts import SchedulerFacts, ServiceMode
from .operations import OperationsService, structured_summary
from .registry import canonical_flow_specs
from .service import AutomationService, ServiceError
from .state import BotStateManager


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
        choices=("fake", "replay"),
        default=os.environ.get("AUTOMATION_SERVICE_ADAPTER", "fake"),
    )
    parser.add_argument(
        "--state-path",
        type=Path,
        default=Path(
            os.environ.get(
                "AUTOMATION_SERVICE_STATE_PATH",
                BotStateManager.DEFAULT_DB_PATH,
            )
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("health")
    subparsers.add_parser("observe")
    subparsers.add_parser("summary")
    subparsers.add_parser("serve")
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    if args.mode == "supervised" and args.adapter != "bluestacks":
        print(
            "supervised mode requires the executor-bound BlueStacks adapter",
            file=sys.stderr,
        )
        return 2
    adapter = _adapter(args.adapter)
    state_path = args.state_path

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
            with BotStateManager(state_path) as state:
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
        except (ServiceError, ValueError) as exc:
            print(json.dumps({"error": str(exc)}, sort_keys=True))
            return 2

    if args.command == "serve":
        try:
            with BotStateManager(state_path) as state:
                service = AutomationService(
                    mode=args.mode,
                    adapter=adapter,
                    state=state,
                )
                while True:
                    health = service.health(
                        current_state=service.mode.value,
                        current_task=None,
                    )
                    if not health.healthy:
                        return 1
                    time.sleep(30)
        except (ServiceError, ValueError) as exc:
            print(json.dumps({"error": str(exc)}, sort_keys=True))
            return 2

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
