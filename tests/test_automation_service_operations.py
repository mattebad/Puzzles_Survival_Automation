from __future__ import annotations

import tempfile
import unittest
from types import SimpleNamespace

from automation_service.adapters import (
    AdapterKind,
    AdapterStatus,
    FakeDeviceAdapter,
    FrameSample,
    SupervisedBlueStacksAdapter,
)
from automation_service.contracts import PerceptionEnvelope, ServiceMode
from automation_service.operations import FakeAlertSink, OperationsService, structured_summary
from automation_service.service import AutomationService, ServiceError


class AutomationServiceOperationsTests(unittest.TestCase):
    def test_health_snapshot_and_summary_are_structured(self) -> None:
        adapter = FakeDeviceAdapter(
            (FrameSample("frame", PerceptionEnvelope("frame", "home", "profile", "fresh")),)
        )
        alerts = FakeAlertSink()
        with tempfile.TemporaryDirectory() as folder:
            service = OperationsService(
                adapter_status=adapter.status,
                database_probe=lambda: True,
                lease_held=lambda: True,
                disk_path=folder,
                alert_sink=alerts,
            )
            health = service.health(current_state="home", current_task="campaign")
            self.assertTrue(health.healthy)
            summary = structured_summary(health=health, task_summaries={"campaign": {"mode": "disabled"}})
            self.assertEqual(summary["schema"], "automation-service-summary-v1")
            self.assertEqual(summary["tasks"]["campaign"]["mode"], "disabled")
            self.assertEqual(alerts.events, [])

    def test_unhealthy_state_alerts_and_retention_never_deletes(self) -> None:
        adapter = FakeDeviceAdapter()
        alerts = FakeAlertSink()
        with tempfile.TemporaryDirectory() as folder:
            service = OperationsService(
                adapter_status=adapter.status,
                database_probe=lambda: False,
                lease_held=lambda: False,
                disk_path=folder,
                alert_sink=alerts,
            )
            health = service.health(unresolved_action=True)
            self.assertFalse(health.healthy)
            self.assertTrue(alerts.events)
            classification = service.classify_retention("state.sqlite3", category="retain")
            self.assertFalse(classification.deletion_allowed)

    def test_supervised_health_requires_lease_adapter_and_fresh_frame(self) -> None:
        alerts = FakeAlertSink()
        service = OperationsService(
            adapter_status=lambda: AdapterStatus(
                AdapterKind.BLUESTACKS_SUPERVISED,
                ServiceMode.SUPERVISED,
                connected=False,
                transport_count=0,
            ),
            database_probe=lambda: True,
            lease_held=lambda: True,
            alert_sink=alerts,
        )
        health = service.health(
            mode=ServiceMode.SUPERVISED,
            last_frame_age_seconds=None,
        )
        self.assertFalse(health.healthy)
        self.assertTrue(health.adapter_required)
        self.assertTrue(alerts.events)

    def test_service_owns_health_mode(self) -> None:
        operations = OperationsService(
            adapter_status=lambda: AdapterStatus(
                AdapterKind.BLUESTACKS_SUPERVISED,
                ServiceMode.SUPERVISED,
                connected=False,
                transport_count=0,
            ),
            database_probe=lambda: True,
            lease_held=lambda: False,
        )
        service = object.__new__(AutomationService)
        service.mode = ServiceMode.SUPERVISED
        service.operations = operations
        health = service.health(last_frame_age_seconds=None)
        self.assertEqual(health.mode, "supervised")
        self.assertFalse(health.healthy)
        self.assertTrue(health.lease_required)
        with self.assertRaises(ServiceError):
            service.health(mode=ServiceMode.DISABLED)

    def test_supervised_service_rejects_custom_activation_authority(self) -> None:
        adapter = object.__new__(SupervisedBlueStacksAdapter)
        coordinator = SimpleNamespace(activation_authority=object())
        with self.assertRaises(ServiceError):
            AutomationService(
                mode=ServiceMode.SUPERVISED,
                adapter=adapter,
                coordinator=coordinator,
            )


if __name__ == "__main__":
    unittest.main()

