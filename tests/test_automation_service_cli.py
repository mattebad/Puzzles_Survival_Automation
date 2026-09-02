from __future__ import annotations

import contextlib
import json
import os
from io import StringIO
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from safe_action_core import SafetyStore

from automation_service import cli as cli_module
from automation_service.registry import WORLD_FLOW_ID, load_canonical_registry
from automation_service.state import BotStateManager, resolve_state_path

from automation_service.cli import main


class AutomationServiceCliTests(unittest.TestCase):
    def test_status_reports_static_routes_and_disabled_sqlite_eligibility(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            output = StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(
                    main(
                        [
                            "--state-path",
                            str(Path(folder) / "service.sqlite3"),
                            "status",
                        ]
                    ),
                    0,
                )
            payload = json.loads(output.getvalue())
        canonical_flow_ids = {
            entry.flow_id for entry in load_canonical_registry()
        }
        self.assertEqual(payload["registration_status"], "REGISTERED")
        self.assertEqual(set(payload["registered_flows"]), canonical_flow_ids)
        self.assertEqual(set(payload["disabled_flows"]), canonical_flow_ids)
        self.assertFalse(payload["scheduler_eligible"])
        self.assertFalse(payload["service_enabled"])
        self.assertEqual(
            set(payload["flow_enabled"]),
            canonical_flow_ids,
        )
        self.assertFalse(any(payload["flow_enabled"].values()))

    def test_implicit_state_path_is_repository_rooted_across_cwd(self) -> None:
        flow_id = "NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE"
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            cwd_paths = [base / "one", base / "two", base / "three", base / "four"]
            for cwd in cwd_paths:
                cwd.mkdir()
            expected = base / "implicit.sqlite3"
            previous_cwd = Path.cwd()
            try:
                with patch.object(BotStateManager, "DEFAULT_DB_PATH", str(expected)), patch.dict(
                    os.environ,
                    {"AUTOMATION_SERVICE_STATE_PATH": ""},
                    clear=False,
                ):
                    os.chdir(cwd_paths[0])
                    with contextlib.redirect_stdout(StringIO()):
                        self.assertEqual(main(["service-enable"]), 0)
                    os.chdir(cwd_paths[1])
                    with contextlib.redirect_stdout(StringIO()):
                        self.assertEqual(main(["enable", flow_id]), 0)
                    os.chdir(cwd_paths[2])
                    status_output = StringIO()
                    with contextlib.redirect_stdout(status_output):
                        self.assertEqual(main(["status"]), 0)
                    status = json.loads(status_output.getvalue())
                    self.assertTrue(status["service_enabled"])
                    self.assertTrue(status["flow_enabled"][flow_id])
                    os.chdir(cwd_paths[3])
                    with contextlib.redirect_stdout(StringIO()):
                        self.assertEqual(main(["emergency-stop"]), 0)
                    os.chdir(cwd_paths[0])
                    final_output = StringIO()
                    with contextlib.redirect_stdout(final_output):
                        self.assertEqual(main(["status"]), 0)
                    self.assertFalse(json.loads(final_output.getvalue())["service_enabled"])
                    self.assertEqual(resolve_state_path(), expected.resolve())
            finally:
                os.chdir(previous_cwd)
            self.assertTrue(expected.is_file())
            self.assertFalse(any((cwd / "bot-state.sqlite3").exists() for cwd in cwd_paths))

    def test_state_busy_operator_mutation_is_structured_and_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "busy.sqlite3"
            seed = BotStateManager(path)
            seed.close()
            holder = sqlite3.connect(path, timeout=0.01, isolation_level=None)

            class ShortTimeoutManager(BotStateManager):
                def __init__(self, db_path=None, **kwargs):
                    kwargs["busy_timeout_ms"] = 25
                    super().__init__(db_path, **kwargs)

            try:
                holder.execute("BEGIN IMMEDIATE")
                output = StringIO()
                with patch.object(cli_module, "BotStateManager", ShortTimeoutManager), contextlib.redirect_stdout(output):
                    self.assertEqual(
                        main(["--state-path", str(path), "service-enable"]),
                        2,
                    )
                self.assertEqual(
                    json.loads(output.getvalue()),
                    {"reason": "SQLITE_BUSY", "retryable": True, "status": "error"},
                )
            finally:
                holder.rollback()
                holder.close()

    def test_manual_run_forwards_or_generates_operator_request_id(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state_path = str(Path(folder) / "manual.sqlite3")
            with contextlib.redirect_stdout(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "--mode",
                            "dry_run",
                            "--state-path",
                            state_path,
                            "service-enable",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "--mode",
                            "dry_run",
                            "--state-path",
                            state_path,
                            "enable",
                            WORLD_FLOW_ID,
                        ]
                    ),
                    0,
                )
            output = StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(
                    main(
                        [
                            "--mode",
                            "dry_run",
                            "--state-path",
                            state_path,
                            "run",
                            WORLD_FLOW_ID,
                            "--live",
                            "--operator-request-id",
                            "operator-cli-test",
                        ]
                    ),
                    0,
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["candidate"]["flow_id"], WORLD_FLOW_ID)
            self.assertTrue(
                payload["candidate"]["occurrence_key"].endswith(
                    ":manual:operator-cli-test"
                )
            )
            generated_output = StringIO()
            with contextlib.redirect_stdout(generated_output):
                self.assertEqual(
                    main(
                        [
                            "--mode",
                            "dry_run",
                            "--state-path",
                            state_path,
                            "run",
                            WORLD_FLOW_ID,
                            "--live",
                        ]
                    ),
                    0,
                )
            generated = json.loads(generated_output.getvalue())
            self.assertEqual(generated["candidate"]["flow_id"], WORLD_FLOW_ID)
            self.assertTrue(
                generated["candidate"]["occurrence_key"].startswith(
                    f"{WORLD_FLOW_ID}:manual:manual:"
                )
            )

    def test_status_keeps_non_nova_flows_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state_path = str(Path(folder) / "service.sqlite3")
            with contextlib.redirect_stdout(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "--state-path",
                            state_path,
                            "service-enable",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "--state-path",
                            state_path,
                            "enable",
                            "NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE",
                        ]
                    ),
                    0,
                )
            output = StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(
                    main(["--state-path", state_path, "status"]),
                    0,
                )
            payload = json.loads(output.getvalue())
        self.assertTrue(payload["scheduler_eligible"])
        self.assertTrue(
            payload["flow_enabled"]["NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE"]
        )
        self.assertFalse(
            payload["flow_enabled"]["WORLD-MAP-NAVIGATION-FOUNDATION"]
        )
        self.assertFalse(
            payload["flow_enabled"]["RECRUITMENT-FREE-ATTEMPT-MAINTENANCE"]
        )
        self.assertFalse(
            payload["flow_enabled"]["CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY"]
        )

    def test_automatic_mode_is_rejected(self) -> None:
        with contextlib.redirect_stderr(StringIO()):
            self.assertEqual(main(["--mode", "automatic", "status"]), 2)

    def test_disabled_health_rejects_missing_and_safety_store_only_databases(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / "service.sqlite3"
            missing_output = StringIO()
            with contextlib.redirect_stdout(missing_output):
                self.assertEqual(
                    main(
                        [
                            "--mode",
                            "disabled",
                            "--state-path",
                            str(state_path),
                            "health",
                        ]
                    ),
                    1,
                )
            self.assertIn('"database_ok": false', missing_output.getvalue())
            store = SafetyStore(state_path)
            store.close()
            output = StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(
                    main(
                        [
                            "--mode",
                            "disabled",
                            "--state-path",
                            str(state_path),
                            "health",
                        ]
                    ),
                    1,
                )
            payload = json.loads(output.getvalue())
            self.assertFalse(payload["database_ok"])
            self.assertFalse(payload["healthy"])

            canonical_path = Path(folder) / "canonical.sqlite3"
            from automation_service.state import BotStateManager

            manager = BotStateManager(canonical_path)
            manager.close()
            healthy_output = StringIO()
            with contextlib.redirect_stdout(healthy_output):
                self.assertEqual(
                    main(
                        [
                            "--mode",
                            "disabled",
                            "--state-path",
                            str(canonical_path),
                            "health",
                        ]
                    ),
                    0,
                )
            healthy_payload = json.loads(healthy_output.getvalue())
            self.assertTrue(healthy_payload["database_ok"])
            self.assertTrue(healthy_payload["healthy"])
        with contextlib.redirect_stderr(StringIO()):
            self.assertEqual(
                main(["--mode", "supervised", "--adapter", "fake", "health"]), 2
            )

    def test_observe_fails_when_adapter_has_no_frame(self) -> None:
        output = StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--adapter", "replay", "observe"]), 1)
        self.assertIn('"observed": false', output.getvalue())

    def test_pnsctl_offline_delegation_reports_static_routes_and_disabled_sqlite(
        self,
    ) -> None:
        from scripts.pnsctl import main as pnsctl_main

        with tempfile.TemporaryDirectory() as folder:
            output = StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(
                    pnsctl_main(
                        [
                            "automation-service",
                            "status",
                            "--state-path",
                            str(Path(folder) / "service.sqlite3"),
                        ]
                    ),
                    0,
                )
            payload = json.loads(output.getvalue())
        canonical_flow_ids = {
            entry.flow_id for entry in load_canonical_registry()
        }
        self.assertEqual(payload["registration_status"], "REGISTERED")
        self.assertEqual(set(payload["registered_flows"]), canonical_flow_ids)
        self.assertFalse(payload["scheduler_eligible"])
        self.assertFalse(payload["service_enabled"])
        self.assertFalse(any(payload["flow_enabled"].values()))


if __name__ == "__main__":
    unittest.main()
