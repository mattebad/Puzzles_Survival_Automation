"""Only one transient read-timeout retry; input transports never retry."""

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import cv2
import numpy as np

from scripts.bluestacks_flow_collector import ADBError
from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime


def png(width=800, height=1280):
    ok, encoded = cv2.imencode(".png", np.full((height, width, 3), 73, np.uint8))
    assert ok
    return encoded.tobytes()


class CaptureRunner:
    def __init__(self, outcomes, order=None):
        self.outcomes = iter(outcomes)
        self.order = order if order is not None else []
        self.capture_calls = 0
        self.taps = []

    def capture_png(self):
        self.capture_calls += 1
        self.order.append("capture")
        outcome = next(self.outcomes)
        if isinstance(outcome, subprocess.TimeoutExpired):
            # Match ADBRunner.run's explicit cause chain.
            raise ADBError("ADB command timed out") from outcome
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def dispatch_tap(self, point):
        self.taps.append(point)
        raise ADBError("input timeout") from subprocess.TimeoutExpired("input tap", 30)


class NativeCaptureRetryTests(unittest.TestCase):
    def runtime(self, outcomes, order=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        runner = CaptureRunner(outcomes, order)
        runtime = LocalBlueStacksRuntime(runner, Path(directory.name), execute=True)
        return runtime, runner

    @staticmethod
    def events(runtime):
        return [json.loads(line) for line in runtime.events.read_text().splitlines()]

    def test_one_timeout_then_valid_frame_rechecks_and_retains_only_real_png(self):
        payload = png()
        order = []
        runtime, runner = self.runtime([subprocess.TimeoutExpired("screencap", 45), payload], order)
        runtime.checkpoint = lambda: order.append("checkpoint")
        captured = runtime.capture("fresh-home")
        self.assertEqual(order, ["checkpoint", "capture", "checkpoint", "capture"])
        self.assertEqual(runner.capture_calls, 2)
        self.assertEqual(runtime.input_count, 0)
        self.assertEqual(runner.taps, [])
        self.assertEqual(runtime.ordinal, 1)
        self.assertEqual(captured.sha256, hashlib.sha256(payload).hexdigest())
        self.assertEqual(captured.path.read_bytes(), payload)
        self.assertEqual(len(list(runtime.frames.glob("*.png"))), 1)
        failed, successful = self.events(runtime)
        self.assertEqual(failed["type"], "capture_failure")
        self.assertEqual(failed["label"], "fresh-home")
        self.assertEqual(failed["attempt"], 1)
        self.assertEqual(failed["cause_class"], "TimeoutExpired")
        self.assertNotIn("sha256", failed)
        self.assertEqual(successful["type"], "capture")

    def test_two_timeouts_stop_without_a_third_attempt_or_invented_frame(self):
        runtime, runner = self.runtime([subprocess.TimeoutExpired("screencap", 45)] * 2)
        with self.assertRaises(ADBError):
            runtime.capture("home")
        self.assertEqual(runner.capture_calls, 2)
        self.assertEqual(runtime.input_count, 0)
        self.assertEqual(runtime.ordinal, 0)
        self.assertEqual(list(runtime.frames.iterdir()), [])
        events = self.events(runtime)
        self.assertEqual([event["attempt"] for event in events], [1, 2])
        self.assertFalse(events[-1]["retrying"])
        self.assertTrue(all(event["type"] == "capture_failure" for event in events))

    def test_checkpoint_stop_after_timeout_prevents_second_read(self):
        runtime, runner = self.runtime([subprocess.TimeoutExpired("screencap", 45), png()])
        calls = []

        def checkpoint():
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("operator stopped")

        runtime.checkpoint = checkpoint
        with self.assertRaisesRegex(RuntimeError, "operator stopped"):
            runtime.capture("home")
        self.assertEqual(len(calls), 2)
        self.assertEqual(runner.capture_calls, 1)
        self.assertEqual(list(runtime.frames.iterdir()), [])
        self.assertEqual(runtime.input_count, 0)

    def test_other_adb_errors_propagate_without_retry(self):
        for message in ("ADB executable was not found", "device unauthorized", "device offline"):
            with self.subTest(error=message):
                error = ADBError(message)
                runtime, runner = self.runtime([error, png()])
                with self.assertRaises(ADBError) as caught:
                    runtime.capture("home")
                self.assertIs(caught.exception, error)
                self.assertEqual(runner.capture_calls, 1)
                self.assertFalse(runtime.events.exists())

    def test_corrupt_or_wrong_profile_payload_is_not_retried(self):
        for payload in (b"not-png", png(width=400, height=640)):
            with self.subTest(payload_length=len(payload)):
                runtime, runner = self.runtime([payload, png()])
                with self.assertRaises(RuntimeError):
                    runtime.capture("home")
                self.assertEqual(runner.capture_calls, 1)
                self.assertEqual(list(runtime.frames.iterdir()), [])
                self.assertFalse(runtime.events.exists())

    def test_input_timeout_is_still_one_transport_and_propagates(self):
        runtime, runner = self.runtime([png()])
        source = runtime.capture("home")
        with self.assertRaises(ADBError):
            runtime.tap(source, target_identity="test-navigation", target_roi=(200, 300, 300, 400), action_key="one-tap")
        self.assertEqual(len(runner.taps), 1)
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(runner.capture_calls, 1)
        self.assertIn("one-tap", runtime.action_keys)
