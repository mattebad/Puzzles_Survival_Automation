from __future__ import annotations

import contextlib
from io import StringIO
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from automation_service.registry import (
    CAMPAIGN_FLOW_ID,
    NOVA_FLOW_ID,
    RECRUITMENT_FLOW_ID,
)
from automation_service.state import BotStateManager

from scripts.pnsctl import main




class PnsctlSchedulerPulseTests(unittest.TestCase):
    def _enable_sqlite_gates(self, path: Path, flow_id: str) -> None:
        with contextlib.redirect_stdout(StringIO()):
            self.assertEqual(
                main(
                    [
                        "automation-service",
                        "service-enable",
                        "--state-path",
                        str(path),
                        "--now-utc-epoch",
                        "1",
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(
                    [
                        "automation-service",
                        "enable",
                        flow_id,
                        "--state-path",
                        str(path),
                        "--now-utc-epoch",
                        "1",
                    ]
                ),
                0,
            )

    def test_pulse_without_state_path_is_disabled_and_zero_transport(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            default_path = Path(folder) / "default.sqlite3"
            output = StringIO()
            with (
                patch.object(BotStateManager, "DEFAULT_DB_PATH", str(default_path)),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["automation-service", "pulse"]), 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "disabled")
        self.assertEqual(payload["reason"], "GLOBAL_HEALTH_BREAKER")
        self.assertEqual(payload["production_registration"], "REGISTERED")
        self.assertEqual(payload["accepted_product"], "world_map_navigation")
        self.assertEqual(payload["transport_count"], 0)
        self.assertFalse(payload["scheduler_eligible"])

    def test_pulse_with_state_path_persists_nothing_when_health_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scheduler.sqlite3"
            output = StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(
                    main(
                        [
                            "automation-service",
                            "pulse",
                            "--state-path",
                            str(path),
                            "--now-utc-epoch",
                            "100",
                        ]
                    ),
                    0,
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["status"], "disabled")
            self.assertEqual(payload["transport_count"], 0)
            self.assertEqual(payload["reason"], "GLOBAL_HEALTH_BREAKER")
            self.assertFalse(payload["scheduler_eligible"])

    def test_healthy_pulse_requires_sqlite_service_and_flow_enablement(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scheduler.sqlite3"
            base = [
                "automation-service",
                "pulse",
                "--state-path",
                str(path),
                "--flow-id",
                NOVA_FLOW_ID,
                "--now-utc-epoch",
                "100",
                "--health-ok",
            ]

            disabled = StringIO()
            with contextlib.redirect_stdout(disabled):
                self.assertEqual(main(base), 0)
            disabled_payload = json.loads(disabled.getvalue())
            self.assertEqual(disabled_payload["reason"], "SERVICE_DISABLED")
            self.assertFalse(disabled_payload["scheduler_eligible"])

            with contextlib.redirect_stdout(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "automation-service",
                            "service-enable",
                            "--state-path",
                            str(path),
                            "--now-utc-epoch",
                            "101",
                        ]
                    ),
                    0,
                )

            flow_disabled = StringIO()
            with contextlib.redirect_stdout(flow_disabled):
                self.assertEqual(main(base), 0)
            flow_disabled_payload = json.loads(flow_disabled.getvalue())
            self.assertEqual(flow_disabled_payload["status"], "disabled")
            self.assertEqual(flow_disabled_payload["reason"], "NO_ELIGIBLE_TASK")
            self.assertFalse(flow_disabled_payload["scheduler_eligible"])
            self.assertEqual(flow_disabled_payload["transport_count"], 0)

            with contextlib.redirect_stdout(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "automation-service",
                            "enable",
                            NOVA_FLOW_ID,
                            "--state-path",
                            str(path),
                            "--now-utc-epoch",
                            "102",
                        ]
                    ),
                    0,
                )

            selected = StringIO()
            with contextlib.redirect_stdout(selected):
                self.assertEqual(main(base), 0)
            payload = json.loads(selected.getvalue())
            self.assertEqual(payload["status"], "selected")
            self.assertEqual(payload["candidate"]["flow_id"], NOVA_FLOW_ID)
            self.assertEqual(
                payload["result"]["reason_code"],
                "NOVA_PRAISE_PARENT_CANARY_REQUIRED",
            )
            self.assertEqual(payload["transport_count"], 0)
            self.assertEqual(payload["accepted_product"], "nova_praise")
            self.assertTrue(payload["scheduler_eligible"])

    def test_recruitment_pulse_requires_fresh_due_projection_and_is_restart_safe(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scheduler.sqlite3"
            self._enable_sqlite_gates(path, RECRUITMENT_FLOW_ID)
            base = [
                "automation-service",
                "pulse",
                "--state-path",
                str(path),
                "--flow-id",
                RECRUITMENT_FLOW_ID,
                "--now-utc-epoch",
                "100",
                "--health-ok",
            ]
            missing = StringIO()
            with contextlib.redirect_stdout(missing):
                self.assertEqual(main(base), 0)
            missing_payload = json.loads(missing.getvalue())
            self.assertEqual(missing_payload["status"], "disabled")
            self.assertEqual(missing_payload["reason"], "NO_ELIGIBLE_TASK")
            self.assertTrue(missing_payload["scheduler_eligible"])

            selected = StringIO()
            with contextlib.redirect_stdout(selected):
                self.assertEqual(
                    main(
                        base
                        + [
                            "--projection-observed-at-utc",
                            "95",
                            "--projection-next-eligible-at",
                            "90",
                        ]
                    ),
                    0,
                )
            payload = json.loads(selected.getvalue())
            self.assertEqual(payload["status"], "selected")
            self.assertEqual(payload["candidate"]["flow_id"], RECRUITMENT_FLOW_ID)
            self.assertEqual(
                payload["result"]["reason_code"],
                "RECRUITMENT_MAINTENANCE_PARENT_CANARY_REQUIRED",
            )
            self.assertEqual(payload["transport_count"], 0)
            self.assertTrue(payload["scheduler_eligible"])

            duplicate = StringIO()
            with contextlib.redirect_stdout(duplicate):
                self.assertEqual(
                    main(
                        base
                        + [
                            "--projection-observed-at-utc",
                            "95",
                            "--projection-next-eligible-at",
                            "90",
                        ]
                    ),
                    0,
                )
            duplicate_payload = json.loads(duplicate.getvalue())
            self.assertEqual(duplicate_payload["status"], "disabled")
            self.assertEqual(
                duplicate_payload["reason"],
                "NO_ELIGIBLE_TASK",
            )
            changed_projection = StringIO()
            with contextlib.redirect_stdout(changed_projection):
                self.assertEqual(
                    main(
                        base
                        + [
                            "--projection-observed-at-utc",
                            "96",
                            "--projection-next-eligible-at",
                            "90",
                        ]
                    ),
                    0,
                )
            changed_payload = json.loads(changed_projection.getvalue())
            self.assertEqual(changed_payload["status"], "selected")
            self.assertEqual(
                changed_payload["candidate"]["occurrence_key"],
                f"{RECRUITMENT_FLOW_ID}:offline-reset:1",
            )

            next_reset = StringIO()
            with contextlib.redirect_stdout(next_reset):
                self.assertEqual(
                    main(
                        base
                        + [
                            "--reset-id",
                            "offline-reset-2",
                            "--projection-observed-at-utc",
                            "95",
                            "--projection-next-eligible-at",
                            "90",
                        ]
                    ),
                    0,
                )
            next_reset_payload = json.loads(next_reset.getvalue())
            self.assertEqual(next_reset_payload["status"], "selected")
            self.assertEqual(
                next_reset_payload["candidate"]["occurrence_key"],
                f"{RECRUITMENT_FLOW_ID}:offline-reset-2:0",
            )

    def test_campaign_pulse_requires_fresh_funded_projection_and_is_restart_safe(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scheduler.sqlite3"
            self._enable_sqlite_gates(path, CAMPAIGN_FLOW_ID)
            base = [
                "automation-service",
                "pulse",
                "--state-path",
                str(path),
                "--flow-id",
                CAMPAIGN_FLOW_ID,
                "--now-utc-epoch",
                "100",
                "--health-ok",
                "--projection-observed-at-utc",
                "95",
                "--projection-next-eligible-at",
                "90",
            ]
            underfunded = StringIO()
            with contextlib.redirect_stdout(underfunded):
                self.assertEqual(
                    main(base + ["--projection-observed-balance", "13"]),
                    0,
                )
            underfunded_payload = json.loads(underfunded.getvalue())
            self.assertEqual(underfunded_payload["status"], "disabled")
            self.assertEqual(underfunded_payload["reason"], "NO_ELIGIBLE_TASK")
            self.assertTrue(underfunded_payload["scheduler_eligible"])

            selected = StringIO()
            with contextlib.redirect_stdout(selected):
                self.assertEqual(
                    main(base + ["--projection-observed-balance", "14"]),
                    0,
                )
            payload = json.loads(selected.getvalue())
            self.assertEqual(payload["status"], "selected")
            self.assertEqual(payload["candidate"]["flow_id"], CAMPAIGN_FLOW_ID)
            self.assertEqual(
                payload["result"]["reason_code"],
                "CAMPAIGN_AP_PARENT_CANARY_REQUIRED",
            )
            self.assertEqual(payload["transport_count"], 0)
            self.assertTrue(payload["scheduler_eligible"])

            duplicate = StringIO()
            with contextlib.redirect_stdout(duplicate):
                self.assertEqual(
                    main(base + ["--projection-observed-balance", "14"]),
                    0,
                )
            duplicate_payload = json.loads(duplicate.getvalue())
            self.assertEqual(duplicate_payload["status"], "disabled")
            self.assertEqual(
                duplicate_payload["reason"],
                "NO_ELIGIBLE_TASK",
            )
            changed_projection = StringIO()
            with contextlib.redirect_stdout(changed_projection):
                self.assertEqual(
                    main(base + ["--projection-observed-balance", "15"]),
                    0,
                )
            changed_payload = json.loads(changed_projection.getvalue())
            self.assertEqual(changed_payload["status"], "selected")
            self.assertEqual(
                changed_payload["candidate"]["occurrence_key"],
                f"{CAMPAIGN_FLOW_ID}:offline-reset:1",
            )

            next_reset = StringIO()
            with contextlib.redirect_stdout(next_reset):
                self.assertEqual(
                    main(
                        base
                        + [
                            "--reset-id",
                            "offline-reset-2",
                            "--projection-observed-balance",
                            "14",
                        ]
                    ),
                    0,
                )
            next_reset_payload = json.loads(next_reset.getvalue())
            self.assertEqual(next_reset_payload["status"], "selected")
            self.assertEqual(
                next_reset_payload["candidate"]["occurrence_key"],
                f"{CAMPAIGN_FLOW_ID}:offline-reset-2:0",
            )


if __name__ == "__main__":
    unittest.main()
