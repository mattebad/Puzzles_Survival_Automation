from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest

import cv2
import numpy as np

from scripts import flow_delivery_control as control
from scripts import navigation_development_boundary as boundary
from scripts.bluestacks_native_runtime import CapturedNativeFrame, LocalBlueStacksRuntime


class FakeRunner:
    def __init__(self) -> None:
        self.taps: list[tuple[int, int]] = []

    def dispatch_tap(self, point: tuple[int, int]) -> None:
        self.taps.append(point)


def source_frame(root: Path, name: str = "source") -> CapturedNativeFrame:
    image = np.zeros((1280, 800, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    payload = encoded.tobytes()
    path = root / f"{name}.png"
    path.write_bytes(payload)
    return CapturedNativeFrame(
        image,
        payload,
        hashlib.sha256(payload).hexdigest(),
        time.monotonic(),
        path,
    )


class LocalBlueStacksRuntimeActionClassTests(unittest.TestCase):
    def _runtime(self, root: Path) -> tuple[LocalBlueStacksRuntime, FakeRunner]:
        runner = FakeRunner()
        runtime = LocalBlueStacksRuntime(
            runner,
            root / "session",
            execute=True,
        )
        return runtime, runner

    def _navigation_context(self, root: Path):
        controller = control.DelegatedRuntimeReceiptController(root / "receipts.sqlite3")
        controller._candidate = lambda: ("head", "fingerprint")  # type: ignore[method-assign]
        receipt = controller.issue(
            task_id="task",
            flow_id="flow",
            receipt_class="reconnaissance",
            agent_identity="agent",
            command_argv=["development-session", "observe"],
            scenario="scenario",
            variant="variant",
            permitted_action_identities=["target-a"],
            permitted_action_classes=["navigation"],
            consequence_class="navigation_only",
            max_total_inputs=1,
            max_resource_affecting_inputs=0,
            max_combat_confirmations=0,
            permitted_terminal_states=["observed", "evidence_required"],
            result_identity="result",
        )
        consumed = controller.consume(
            receipt_id=receipt["receipt_id"],
            agent_identity="agent",
            task_id="task",
            flow_id="flow",
            receipt_class="reconnaissance",
            command_argv=receipt["command_argv"],
            scenario="scenario",
            variant="variant",
        )
        return controller, control.DelegatedRuntimeContext(
            controller, consumed, result_identity="result"
        )

    def test_default_tap_reserves_navigation_and_records_navigation_event(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime, runner = self._runtime(root)
            _controller, context = self._navigation_context(root)
            with boundary.delegated_runtime_context(context):
                runtime.tap(
                    source_frame(root),
                    target_identity="target-a",
                    target_roi=(100, 200, 140, 240),
                    action_key="target-a",
                )

            self.assertEqual(runner.taps, [(120, 220)])
            events = [
                json.loads(line)
                for line in runtime.events.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(events[-1]["type"], "dispatch")
            self.assertEqual(events[-1]["action_class"], "navigation")
            self.assertEqual(events[-1]["target_identity"], "target-a")
            connection = _controller._connection()
            try:
                reservation = connection.execute(
                    "SELECT action_class, status FROM delegated_reservations "
                    "WHERE receipt_id=?",
                    (context.receipt["receipt_id"],),
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(tuple(reservation), ("navigation", "input_sent"))

    def test_optional_reward_claim_tap_records_reward_claim_without_breaking_compatibility(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime, runner = self._runtime(root)
            runtime.tap(
                source_frame(root),
                target_identity="daily-row-claim:consume_stamina",
                target_roi=(600, 450, 700, 530),
                action_key="reward-claim",
                action_class="reward_claim",
            )

            self.assertEqual(runner.taps, [(650, 490)])
            event = json.loads(runtime.events.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(event["action_class"], "reward_claim")

            runtime.tap(
                source_frame(root, "compatibility"),
                target_identity="ordinary-navigation",
                target_roi=(10, 10, 20, 20),
                action_key="compatibility-navigation",
            )
            events = [
                json.loads(line)
                for line in runtime.events.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(events[-1]["action_class"], "navigation")

    def test_empty_or_non_string_action_class_fails_closed_before_transport(self):
        for invalid in ("", "   ", None):
            with self.subTest(action_class=invalid), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                runtime, runner = self._runtime(root)
                with self.assertRaisesRegex(RuntimeError, "action class"):
                    runtime.tap(
                        source_frame(root),
                        target_identity="target",
                        target_roi=(10, 10, 20, 20),
                        action_key="invalid-action",
                        action_class=invalid,  # type: ignore[arg-type]
                    )
                self.assertEqual(runner.taps, [])
                self.assertEqual(runtime.input_count, 0)
                self.assertFalse(runtime.events.exists())


if __name__ == "__main__":
    unittest.main()
