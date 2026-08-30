from __future__ import annotations

import contextlib
from io import StringIO
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from automation_service import registry as registration

from scripts.pnsctl import main


def nova_registered_registry_payload() -> dict:
    source = (
        Path(__file__).resolve().parents[1]
        / "tasks"
        / "flow_delivery_disabled_production_registry.json"
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    for flow_id in payload["flows"]:
        if flow_id != registration.NOVA_FLOW_ID:
            payload["flows"][flow_id] = {
                "mode": "disabled",
                "product_id": None,
                "product_revision": None,
                "production_handler": None,
                "profile": None,
                "registration_status": "NOT_REGISTERED",
                "scheduler_eligible": False,
                "supported_profiles": [],
            }
    payload["flows"][registration.NOVA_FLOW_ID] = {
        "mode": registration.NOVA_PHASE_MODE,
        "product_id": registration.NOVA_PRODUCT_ID,
        "product_revision": registration.NOVA_PRODUCT_REVISION,
        "production_handler": registration.NOVA_HANDLER_ID,
        "profile": registration.NOVA_PROFILE_ID,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
        "supported_profiles": [registration.NOVA_PROFILE_ID],
    }
    return payload


def recruitment_registered_registry_payload() -> dict:
    payload = nova_registered_registry_payload()
    payload["flows"][registration.NOVA_FLOW_ID] = {
        "mode": "disabled",
        "product_id": None,
        "product_revision": None,
        "production_handler": None,
        "profile": None,
        "registration_status": "NOT_REGISTERED",
        "scheduler_eligible": False,
        "supported_profiles": [],
    }
    payload["flows"][registration.RECRUITMENT_FLOW_ID] = {
        "mode": registration.RECRUITMENT_PHASE_MODE,
        "product_id": registration.RECRUITMENT_PRODUCT_ID,
        "product_revision": registration.RECRUITMENT_PRODUCT_REVISION,
        "production_handler": registration.RECRUITMENT_HANDLER_ID,
        "profile": registration.RECRUITMENT_PROFILE_ID,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
        "supported_profiles": [registration.RECRUITMENT_PROFILE_ID],
    }
    return payload


def campaign_registered_registry_payload() -> dict:
    payload = nova_registered_registry_payload()
    payload["flows"][registration.NOVA_FLOW_ID] = {
        "mode": "disabled",
        "product_id": None,
        "product_revision": None,
        "production_handler": None,
        "profile": None,
        "registration_status": "NOT_REGISTERED",
        "scheduler_eligible": False,
        "supported_profiles": [],
    }
    payload["flows"][registration.CAMPAIGN_FLOW_ID] = {
        "mode": registration.CAMPAIGN_PHASE_MODE,
        "product_id": registration.CAMPAIGN_PRODUCT_ID,
        "product_revision": registration.CAMPAIGN_PRODUCT_REVISION,
        "production_handler": registration.CAMPAIGN_HANDLER_ID,
        "profile": registration.CAMPAIGN_PROFILE_ID,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
        "supported_profiles": [registration.CAMPAIGN_PROFILE_ID],
    }
    return payload


class PnsctlSchedulerPulseTests(unittest.TestCase):
    def test_pulse_without_state_path_is_disabled_and_zero_transport(self) -> None:
        output = StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["automation-service", "pulse"]), 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "disabled")
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

    def test_healthy_pulse_selects_only_registered_nova_zero_transport_handler(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scheduler.sqlite3"
            registry_path = Path(folder) / "registry.json"
            registry_path.write_text(
                json.dumps(nova_registered_registry_payload()), encoding="utf-8"
            )
            output = StringIO()
            with (
                patch.object(registration, "REGISTRY_PATH", registry_path),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(
                    main(
                        [
                            "automation-service",
                            "pulse",
                            "--state-path",
                            str(path),
                            "--now-utc-epoch",
                            "100",
                            "--health-ok",
                        ]
                    ),
                    0,
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["status"], "selected")
            self.assertEqual(
                payload["candidate"]["flow_id"],
                "NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE",
            )
            self.assertEqual(
                payload["result"]["reason_code"], "NOVA_PRAISE_PARENT_CANARY_REQUIRED"
            )
            self.assertEqual(payload["transport_count"], 0)
            self.assertEqual(payload["accepted_product"], "nova_praise")

    def test_recruitment_pulse_requires_fresh_due_projection_and_is_restart_safe(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scheduler.sqlite3"
            registry_path = Path(folder) / "registry.json"
            registry_path.write_text(
                json.dumps(recruitment_registered_registry_payload()),
                encoding="utf-8",
            )
            base = [
                "automation-service",
                "pulse",
                "--state-path",
                str(path),
                "--now-utc-epoch",
                "100",
                "--health-ok",
            ]
            with patch.object(registration, "REGISTRY_PATH", registry_path):
                missing = StringIO()
                with contextlib.redirect_stdout(missing):
                    self.assertEqual(main(base), 0)
                self.assertEqual(json.loads(missing.getvalue())["status"], "disabled")

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
                self.assertEqual(
                    payload["candidate"]["flow_id"],
                    registration.RECRUITMENT_FLOW_ID,
                )
                self.assertEqual(
                    payload["result"]["reason_code"],
                    "RECRUITMENT_MAINTENANCE_PARENT_CANARY_REQUIRED",
                )
                self.assertEqual(payload["transport_count"], 0)

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
                self.assertEqual(json.loads(duplicate.getvalue())["status"], "disabled")

    def test_campaign_pulse_requires_fresh_funded_projection_and_is_restart_safe(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scheduler.sqlite3"
            registry_path = Path(folder) / "registry.json"
            registry_path.write_text(
                json.dumps(campaign_registered_registry_payload()),
                encoding="utf-8",
            )
            base = [
                "automation-service",
                "pulse",
                "--state-path",
                str(path),
                "--now-utc-epoch",
                "100",
                "--health-ok",
                "--projection-observed-at-utc",
                "95",
                "--projection-next-eligible-at",
                "90",
            ]
            with patch.object(registration, "REGISTRY_PATH", registry_path):
                underfunded = StringIO()
                with contextlib.redirect_stdout(underfunded):
                    self.assertEqual(
                        main(base + ["--projection-observed-balance", "13"]),
                        0,
                    )
                self.assertEqual(
                    json.loads(underfunded.getvalue())["status"],
                    "disabled",
                )

                selected = StringIO()
                with contextlib.redirect_stdout(selected):
                    self.assertEqual(
                        main(base + ["--projection-observed-balance", "14"]),
                        0,
                    )
                payload = json.loads(selected.getvalue())
                self.assertEqual(payload["status"], "selected")
                self.assertEqual(
                    payload["candidate"]["flow_id"],
                    registration.CAMPAIGN_FLOW_ID,
                )
                self.assertEqual(
                    payload["result"]["reason_code"],
                    "CAMPAIGN_AP_PARENT_CANARY_REQUIRED",
                )
                self.assertEqual(payload["transport_count"], 0)

                duplicate = StringIO()
                with contextlib.redirect_stdout(duplicate):
                    self.assertEqual(
                        main(base + ["--projection-observed-balance", "14"]),
                        0,
                    )
                self.assertEqual(
                    json.loads(duplicate.getvalue())["status"],
                    "disabled",
                )


if __name__ == "__main__":
    unittest.main()
