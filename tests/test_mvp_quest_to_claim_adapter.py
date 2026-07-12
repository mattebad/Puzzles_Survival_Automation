import unittest

from scripts.mvp_quest_to_claim import ADBTransport


class Result:
    returncode = 0
    stderr = b""


class AdapterCase(unittest.TestCase):
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
