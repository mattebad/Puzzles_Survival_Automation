import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts.mvp_quest_to_claim import ADBTransport, classify


class Result:
    returncode = 0
    stderr = b""


class AdapterCase(unittest.TestCase):
    def test_exact_promoted_quest_reference_bypasses_platform_ocr_drift(self):
        class Args:
            quest_reference = Path("evidence/sessions/20260712-m6-dq-bootstrap/assets/quest-main-settled.png")

        result = classify("quest", Args.quest_reference, Args())
        self.assertTrue(result["recognized"])
        self.assertEqual(result["state"], "QUEST")
        self.assertEqual(result["detail"]["method"], "exact_promoted_quest_reference_hash")

    def test_capture_timestamp_is_successful_completion_monotonic_time(self):
        def runner(command, **kwargs):
            kwargs["stdout"].write(b"retained-test-bytes")
            return Result()

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "frame.png"
            with patch(
                "scripts.mvp_quest_to_claim.valid_png_frame",
                return_value={"sha256": "a" * 64, "width": 800, "height": 1280},
            ), patch("scripts.mvp_quest_to_claim.time.monotonic", side_effect=(10.0, 11.0, 11.1)):
                metadata = ADBTransport("adb", "private-device", runner).capture(output)
        self.assertEqual(metadata["command_started_monotonic"], 10.0)
        self.assertEqual(metadata["capture_completed_monotonic"], 11.0)
        self.assertEqual(metadata["decode_completed_monotonic"], 11.1)

    def test_tap_is_one_exact_injected_transport_call(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return Result()

        result = ADBTransport("adb", "private-device", runner).tap(100, 200)
        self.assertTrue(result.dispatched)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], ["adb", "-s", "private-device", "shell", "input", "tap", "100", "200"])

    def test_swipe_is_one_exact_injected_transport_call(self):
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            return Result()

        ADBTransport("adb", "private-device", runner).swipe(400, 900, 400, 500, 300)
        self.assertEqual(calls, [["adb", "-s", "private-device", "shell", "input", "swipe", "400", "900", "400", "500", "300"]])

    def test_transport_error_is_ambiguous_and_not_retried(self):
        calls = []

        class Failure:
            returncode = 1
            stderr = b"transport unknown"

        def runner(command, **kwargs):
            calls.append(command)
            return Failure()

        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            ADBTransport("adb", "private-device", runner).tap(1, 2)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
