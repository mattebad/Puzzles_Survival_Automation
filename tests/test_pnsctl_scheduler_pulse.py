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

    def test_healthy_pulse_selects_only_registered_nova_zero_transport_handler(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scheduler.sqlite3"
            registry_path = Path(folder) / "registry.json"
            registry_path.write_text(
                json.dumps(nova_registered_registry_payload()), encoding="utf-8"
            )
            output = StringIO()
            with patch.object(
                registration, "REGISTRY_PATH", registry_path
            ), contextlib.redirect_stdout(output):
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
            self.assertEqual(payload["result"]["reason_code"], "NOVA_PRAISE_PARENT_CANARY_REQUIRED")
            self.assertEqual(payload["transport_count"], 0)
            self.assertEqual(payload["accepted_product"], "nova_praise")

if __name__ == "__main__":
    unittest.main()
