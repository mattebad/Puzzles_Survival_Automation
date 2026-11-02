"""Nova adopts shared startup recovery on its existing native input ledger."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
from scripts.nova_praise_bluestacks import NovaNavigationCanaryRoute
from tests.test_nova_navigation_canary import ATLAS_PATH, _identity


FIXTURES = Path(__file__).parent / "fixtures/startup"


class RetainedDevice:
    def __init__(self, frames):
        self.frames = list(frames)
        self.current = self.frames[0]
        self.taps = []
        self.fail_transport = False

    def capture_png(self):
        if self.frames:
            self.current = self.frames.pop(0)
        return self.current

    def dispatch_tap(self, point):
        self.taps.append(point)
        if self.fail_transport:
            raise RuntimeError("transport completion uncertain")


class NovaStartupRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.vip = (FIXTURES / "nova-vip-reset-20261031.png").read_bytes()
        self.home = (FIXTURES / "nova-home-parent-20261030.png").read_bytes()
        self.unknown = cv2.imencode(".png", np.zeros((1280, 800, 3), np.uint8))[1].tobytes()

    def route(self, frames):
        device = RetainedDevice(frames)
        runtime = LocalBlueStacksRuntime(device, Path(self.directory.name) / "native", execute=True)
        runtime.max_inputs = 8
        route = NovaNavigationCanaryRoute(runtime, _identity(), atlas_path=ATLAS_PATH,
                                          maximum_steps=0, settle_seconds=0)
        return device, runtime, route

    def events(self, runtime, kind):
        return [row for row in map(json.loads, runtime.events.read_text(encoding="utf-8").splitlines())
                if row["type"] == kind]

    def test_exact_vip_close_resumes_at_home_and_is_counted_once(self):
        device, runtime, route = self.route([self.vip, self.vip, self.home])
        with patch("scripts.startup_recovery.SafetyStore", side_effect=AssertionError("reuse caller ledger")):
            result = route.run()
        self.assertEqual(result.reason, "maximum_navigation_steps")
        self.assertEqual((runtime.input_count, result.navigation_input_count), (1, 1))
        self.assertEqual(result.praise_taps, 0)
        self.assertEqual(device.taps, [(400, 807)])
        dispatch, = self.events(runtime, "dispatch")
        self.assertEqual(dispatch["target_identity"], "reset-popup-close")
        self.assertFalse(dispatch["consequential"])
        captures = self.events(runtime, "capture")
        self.assertEqual(dispatch["source_sha256"], captures[1]["sha256"])
        self.assertEqual(self.events(runtime, "reconcile")[0]["status"], "confirmed")

    def test_vip_then_scarlett_retains_two_navigation_steps_and_zero_praise(self):
        scarlett = (FIXTURES / "scarlett-current-20261030.png").read_bytes()
        device, runtime, route = self.route([self.vip, self.vip, scarlett, scarlett, self.home])
        result = route.run()
        self.assertEqual(result.reason, "maximum_navigation_steps")
        self.assertEqual((runtime.input_count, result.navigation_input_count, result.praise_taps), (2, 2, 0))
        self.assertEqual(len(device.taps), 2)
        startup = next(row for row in result.records if row.get("action") == "startup_overlay_recovery")
        self.assertEqual(startup["input_count"], 2)
        self.assertTrue(startup["resume_ready"])
        self.assertEqual([step["popup_identity"] for step in startup["steps"]],
                         ["VIP_POINTS_GET_PTS", "SCARLETT_THREE_DAY_PACK"])
        self.assertEqual([row["status"] for row in self.events(runtime, "reconcile")], ["confirmed", "confirmed"])

    def test_unknown_source_sends_no_close_or_back(self):
        device, runtime, route = self.route([self.unknown])
        result = route.run()
        self.assertEqual(result.status, "blocked")
        self.assertEqual((runtime.input_count, result.navigation_input_count), (0, 0))
        self.assertEqual(device.taps, [])

    def test_changed_popup_before_dispatch_sends_nothing(self):
        device, runtime, route = self.route([self.vip, self.unknown])
        result = route.run()
        self.assertTrue(result.reason.startswith("startup_overlay:"))
        self.assertEqual((runtime.input_count, result.navigation_input_count), (0, 0))
        self.assertEqual(device.taps, [])

    def test_unknown_successor_counts_close_and_stops_without_retry(self):
        device, runtime, route = self.route([self.vip, self.vip, self.unknown])
        result = route.run()
        self.assertTrue(result.reason.startswith("startup_overlay:"))
        self.assertEqual((runtime.input_count, result.navigation_input_count), (1, 1))
        self.assertEqual(len(device.taps), 1)
        self.assertFalse(result.terminal_home_verified)

    def test_uncertain_transport_counts_close_without_retry_or_praise(self):
        device, runtime, route = self.route([self.vip, self.vip, self.home])
        device.fail_transport = True
        result = route.run()
        self.assertTrue(result.reason.startswith("startup_overlay:"))
        self.assertEqual((runtime.input_count, result.navigation_input_count), (1, 1))
        self.assertEqual((len(device.taps), result.praise_taps), (1, 0))

    def test_checkpoint_stop_after_close_keeps_actual_input_accounting(self):
        device, runtime, route = self.route([self.vip, self.vip, self.home])

        def checkpoint():
            if device.taps:
                raise RuntimeError("checkpoint stop after dispatch")

        runtime.checkpoint = checkpoint
        with self.assertRaisesRegex(RuntimeError, "checkpoint stop"):
            route.run()
        self.assertEqual((runtime.input_count, route.input_count, len(device.taps)), (1, 1, 1))
        self.assertEqual(route.records[-1]["input_count"], 1)
        self.assertFalse(route.records[-1]["resume_ready"])


if __name__ == "__main__":
    unittest.main()
