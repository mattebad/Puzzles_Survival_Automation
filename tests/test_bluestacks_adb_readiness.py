from __future__ import annotations

from subprocess import CompletedProcess, TimeoutExpired
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.bluestacks_adb_readiness import (
    ADBReadinessError,
    ensure_adb_ready,
    reset_adb_readiness_cache,
)
from scripts import bluestacks_flow_collector as collector
from scripts import pnsctl


class BlueStacksADBReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_adb_readiness_cache()

    def tearDown(self) -> None:
        reset_adb_readiness_cache()

    def test_default_start_timeout_probes_fixed_serial_unqualified(self) -> None:
        calls: list[list[str]] = []

        def run(command, **kwargs):
            calls.append(command)
            if len(calls) == 1:
                self.assertEqual(kwargs["timeout"], 5.0)
                raise TimeoutExpired(command, kwargs["timeout"])
            return CompletedProcess([], 0, "device\n", "")

        ensure_adb_ready("HD-Adb.exe", "emulator-5554", run=run)
        self.assertEqual(calls, [
            ["HD-Adb.exe", "start-server"],
            ["HD-Adb.exe", "-s", "emulator-5554", "get-state"],
        ])

    def test_server_starts_before_probe_and_success_is_cached(self) -> None:
        calls: list[list[str]] = []
        responses = iter(
            (
                CompletedProcess([], 0, "server started", ""),
                CompletedProcess([], 0, "device\n", ""),
            )
        )

        def run(command, **kwargs):
            calls.append(command)
            return next(responses)

        cache: set[tuple[str, str]] = set()
        ensure_adb_ready("HD-Adb.exe", "emulator-5554", run=run, cache=cache)
        ensure_adb_ready("HD-Adb.exe", "emulator-5554", run=run, cache=cache)
        self.assertEqual(calls, [
            ["HD-Adb.exe", "start-server"],
            ["HD-Adb.exe", "-s", "emulator-5554", "get-state"],
        ])
        self.assertNotIn("connect", calls[0])

    def test_transient_offline_then_device_retries_with_bounded_sleep(self) -> None:
        calls: list[list[str]] = []
        responses = iter(
            (
                CompletedProcess([], 0, "", "server started"),
                CompletedProcess([], 1, "offline\n", "device offline"),
                CompletedProcess([], 0, "device\n", ""),
            )
        )
        run = lambda command, **kwargs: (calls.append(command) or next(responses))
        sleeps: list[float] = []
        ensure_adb_ready(
            "adb",
            "emulator-5554",
            run=run,
            sleep=sleeps.append,
            monotonic=iter((0.0, 0.0, 0.0, 0.01, 0.02)).__next__,
        )
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [0.05])

    def test_timeout_has_compact_diagnostics_and_never_connects(self) -> None:
        calls: list[list[str]] = []
        responses = iter(
            (
                TimeoutExpired(["adb", "start-server"], 5.0),
                CompletedProcess([], 1, "offline\n", "offline"),
            )
        )
        def run(command, **kwargs):
            calls.append(command)
            response = next(responses)
            if isinstance(response, Exception):
                raise response
            return response

        clock = iter((0.0, 0.0, 0.0, 1.0, 2.0, 3.0)).__next__
        with self.assertRaisesRegex(
            ADBReadinessError, r"ADB readiness timed out.*start-server timed out; offline"
        ):
            ensure_adb_ready(
                "adb",
                "emulator-5554",
                run=run,
                sleep=lambda _seconds: None,
                monotonic=clock,
                deadline_seconds=1.0,
            )
        self.assertTrue(calls)
        self.assertTrue(all("connect" not in command for command in calls))

    def test_parent_fixed_command_invokes_readiness_before_serial_command(self) -> None:
        with TemporaryDirectory() as directory:
            executable = Path(directory) / "HD-Adb.exe"
            executable.write_bytes(b"stub")
            with patch.object(pnsctl, "BLUESTACKS_ADB", executable), patch.object(
                pnsctl, "ensure_adb_ready"
            ) as ready, patch.object(
                pnsctl.subprocess,
                "run",
                return_value=CompletedProcess([], 0, "device\n", ""),
            ) as run:
                pnsctl._run_fixed_bluestacks_adb("get-state")
            ready.assert_called_once_with(str(executable), pnsctl.BLUESTACKS_SERIAL)
            self.assertEqual(run.call_args.args[0][1:3], ["-s", pnsctl.BLUESTACKS_SERIAL])

    def test_child_runner_invokes_readiness_before_list_devices(self) -> None:
        runner = collector.ADBRunner("HD-Adb.exe", "emulator-5554")
        with patch.object(collector, "ensure_adb_ready") as ready, patch.object(
            collector.subprocess,
            "run",
            return_value=CompletedProcess(
                [], 0, b"List of devices attached\nemulator-5554\tdevice\n", b""
            ),
        ):
            devices = runner.list_devices()
        ready.assert_called_once_with("HD-Adb.exe", "emulator-5554")
        self.assertEqual([(device.serial, device.state) for device in devices], [("emulator-5554", "device")])

    def test_child_serial_selection_lists_devices_without_fake_serial_probe(self) -> None:
        runner = collector.ADBRunner("HD-Adb.exe", "__selection__")
        with patch.object(collector, "ensure_adb_ready") as ready, patch.object(
            collector.subprocess,
            "run",
            return_value=CompletedProcess(
                [], 0, b"List of devices attached\nemulator-5554\tdevice\n", b""
            ),
        ) as run:
            devices = runner.list_devices()
        ready.assert_called_once_with("HD-Adb.exe", None)
        self.assertEqual(run.call_args.args[0], ["HD-Adb.exe", "devices", "-l"])
        self.assertEqual(devices[0].serial, "emulator-5554")

    def test_development_cli_parses_optional_ruins_continuation(self) -> None:
        parsed = pnsctl.parser().parse_args(
            [
                "development-session",
                "run-flow",
                "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION",
                "--chests-only",
                "--chest-continuation",
                "checkpoint.json",
            ]
        )
        self.assertEqual(parsed.chest_continuation, Path("checkpoint.json"))
        self.assertTrue(parsed.chests_only)


if __name__ == "__main__":
    unittest.main()
