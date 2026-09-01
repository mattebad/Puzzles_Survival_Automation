from __future__ import annotations

import contextlib
import json
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from safe_action_core import SafetyStore

from automation_service.registry import load_canonical_registry

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
