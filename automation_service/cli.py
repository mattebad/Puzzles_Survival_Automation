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

from safe_action_core import SafetyStore

from .adapters import AdapterError, FakeDeviceAdapter, ReplayDeviceAdapter
from .contracts import ServiceMode
from .operations import OperationsService, structured_summary
from .registry import load_disabled_registry
from .service import ServiceError


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
                os.path.join(
                    os.environ.get("AUTOMATION_SERVICE_STATE_DIR", "."),
                    "automation-service.sqlite3",
                ),
            )
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("health")
    subparsers.add_parser("observe")
    subparsers.add_parser("summary")
    subparsers.add_parser("serve")
    return parser


def _adapter(kind: str):
    return FakeDeviceAdapter() if kind == "fake" else ReplayDeviceAdapter()


def _initialize_state_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    store = SafetyStore(path)
    store.close()


def _database_probe(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        connection = sqlite3.connect(f"file:{path}?mode=rw", uri=True)
        try:
            quick_check = connection.execute("PRAGMA quick_check").fetchone()
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            return quick_check == ("ok",) and {
                "controller_lease",
                "scheduler_invocation_state",
            } <= tables
        finally:
            connection.close()
    except sqlite3.Error:
        return False


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    if args.mode == "supervised" and args.adapter != "bluestacks":
        print("supervised mode requires the executor-bound BlueStacks adapter", file=sys.stderr)
        return 2
    adapter = _adapter(args.adapter)
    state_path = args.state_path
    operations = OperationsService(
        adapter_status=adapter.status,
        database_probe=lambda: _database_probe(state_path),
        lease_held=lambda: False,
        disk_path=str(state_path.parent),
    )
    registry = load_disabled_registry()
    if args.command == "status":
        payload = {
            "schema": "automation-service-status-v1",
            "mode": args.mode,
            "adapter": args.adapter,
            "registration_status": "NOT_REGISTERED",
            "scheduler_eligible": False,
            "registered_flows": [],
            "disabled_flows": [entry.flow_id for entry in registry],
        }
        print(json.dumps(payload, sort_keys=True))
        return 0
    else:
        if args.command == "serve":
            _initialize_state_database(state_path)
            while True:
                health = operations.health(
                    current_state="disabled",
                    mode=ServiceMode.DISABLED,
                    current_task=None,
                )
                if not health.healthy:
                    return 1
                time.sleep(30)
        observed_frame_id = None
        if args.command == "observe":
            try:
                observed_frame_id = adapter.capture().frame_id
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
        health = operations.health(
            current_state="observe_only" if args.command == "observe" else "disabled",
            mode=args.mode,
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

