from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import cv2
import numpy as np

from scripts import flow_delivery_control as control
from scripts import navigation_development_boundary as boundary
from scripts.bluestacks_native_runtime import CapturedNativeFrame, LocalBlueStacksRuntime


class FakeRunner:
    def __init__(self) -> None:
        self.taps: list[tuple[int, int]] = []
        self.swipes: list[tuple[tuple[int, int], tuple[int, int]]] = []
        self.capture_calls = 0
        self.capture_payload: bytes | None = None

    def capture_png(self) -> bytes:
        self.capture_calls += 1
        if self.capture_payload is not None:
            return self.capture_payload
        image = np.zeros((1280, 800, 3), dtype=np.uint8)
        ok, encoded = cv2.imencode(".png", image)
        assert ok
        return encoded.tobytes()

    def dispatch_tap(self, point: tuple[int, int]) -> None:
        self.taps.append(point)

    def dispatch_swipe(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> None:
        self.swipes.append((start, end))


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

    def test_stop_between_authorization_and_transport_sends_no_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime, runner = self._runtime(root)
            calls = 0

            def checkpoint():
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise RuntimeError("stop requested")

            runtime.checkpoint = checkpoint
            with self.assertRaisesRegex(RuntimeError, "stop requested"):
                runtime.tap(
                    source_frame(root), target_identity="target-a",
                    target_roi=(100, 200, 140, 240), action_key="target-a",
                )
            self.assertEqual(runner.taps, [])

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

    def test_real_swipe_emits_exact_scan_event_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime, runner = self._runtime(root)
            _controller, context = self._navigation_context(root)
            source = source_frame(root)
            with boundary.delegated_runtime_context(context):
                runtime.swipe(
                    source,
                    start=(400, 1000),
                    end=(400, 560),
                    action_key="target-a",
                    target_identity="target-a",
                )

            self.assertEqual(runner.swipes, [((400, 1000), (400, 560))])
            event = json.loads(runtime.events.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(
                {field: event[field] for field in (
                    "gesture",
                    "action_class",
                    "consequence_class",
                )},
                {
                    "gesture": "swipe",
                    "action_class": "navigation",
                    "consequence_class": "navigation_only",
                },
            )
            self.assertEqual(event["action_key"], "target-a")
            self.assertEqual(event["target_identity"], "target-a")
            self.assertEqual(event["start"], [400, 1000])
            self.assertEqual(event["end"], [400, 560])
            self.assertEqual(event["source_sha256"], source.sha256)
            connection = _controller._connection()
            try:
                reservation = connection.execute(
                    "SELECT action_class, consequence_class, status "
                    "FROM delegated_reservations WHERE receipt_id=?",
                    (context.receipt["receipt_id"],),
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(
                tuple(reservation),
                ("navigation", "navigation_only", "input_sent"),
            )

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
    def test_capture_sanitizes_path_and_ads_syntax_before_runner_capture(self):
        labels = {
            "../outside": "outside",
            r"..\outside": "outside",
            "capture:stream": "capture-stream",
        }
        for label, expected in labels.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                runtime, runner = self._runtime(root)
                captured = runtime.capture(label)
                self.assertEqual(runner.capture_calls, 1)
                self.assertEqual(captured.path.name, f"0001-{expected}.png")
                self.assertEqual(captured.path.parent, runtime.frames)
                self.assertEqual(captured.path.read_bytes(), captured.png)
                event = json.loads(runtime.events.read_text(encoding="utf-8"))
                self.assertEqual(event["label"], label)
                self.assertEqual(event["filename_component"], expected)
                self.assertFalse((root / "outside.png").exists())

    def test_capture_rejects_empty_or_ambiguous_label_before_runner_capture(self):
        for label in ("", "   ", "..", "://"):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                runtime, runner = self._runtime(root)
                with self.assertRaises(RuntimeError):
                    runtime.capture(label)
                self.assertEqual(runner.capture_calls, 0)
                self.assertFalse((root / "outside.png").exists())

    def test_capture_sanitizes_punctuation_and_retains_original_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime, runner = self._runtime(root)
            captured = runtime.capture("capture label")
            self.assertEqual(runner.capture_calls, 1)
            self.assertEqual(captured.path.name, "0001-capture-label.png")
            self.assertEqual(captured.path.read_bytes(), captured.png)
            event = json.loads(runtime.events.read_text(encoding="utf-8"))
            self.assertEqual(event["label"], "capture label")
            self.assertEqual(event["filename_component"], "capture-label")
            self.assertEqual(event["path"], str(captured.path))
    def test_connect_rejects_ambiguous_workflow_before_device_operations(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("scripts.bluestacks_native_runtime.ADBRunner") as runner:
                with self.assertRaisesRegex(RuntimeError, "ambiguous"):
                    LocalBlueStacksRuntime.connect(
                        adb="adb",
                        serial="not-a-device",
                        output_directory=Path(directory),
                        workflow="..",
                        execute=True,
                    )
                runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
