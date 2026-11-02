"""Legacy Campaign commands cannot start a second AP executor."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts import bluestacks_campaign_ap as native


BASE = ["--adb", "unused", "--serial", "emulator-5554", "--stage", "1-15-9",
        "--ap-cost", "14", "--ap-budget", "14", "--max-runs", "1"]


class CampaignLegacyEntrypointTests(unittest.TestCase):
    def test_ordinary_execute_refuses_before_validation_prompt_device_or_store(self):
        stderr = io.StringIO()
        with (
            redirect_stderr(stderr),
            patch.object(native, "require_campaign_home_atlas_building") as atlas,
            patch.object(native.LocalBlueStacksRuntime, "connect") as connect,
            patch.object(native, "open_canonical_action_store") as store,
            patch("builtins.input") as prompt,
        ):
            with self.assertRaises(SystemExit) as raised:
                native.main([*BASE, "--execute"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("pnsctl automation-service serve", stderr.getvalue())
        for operation in (atlas, prompt, connect, store):
            operation.assert_not_called()

    def test_ordinary_dry_run_remains_non_consuming(self):
        stdout = io.StringIO()
        with (
            redirect_stdout(stdout),
            patch.object(native, "require_campaign_home_atlas_building"),
            patch.object(native.LocalBlueStacksRuntime, "connect") as connect,
            patch.object(native, "open_canonical_action_store") as store,
            patch("builtins.input") as prompt,
        ):
            code = native.main(BASE)
        result = json.loads(stdout.getvalue())
        self.assertEqual((code, result["status"], result["dispatch"]), (0, "dry-run", False))
        for operation in (prompt, connect, store):
            operation.assert_not_called()

    def test_navigation_and_explicit_victory_recovery_keep_the_existing_engine(self):
        for mode, extra, status in (
            ("navigation", ["--navigation-only"], "navigation_only_complete"),
            ("recovery", ["--victory-home-only", "--initial-ap", "120"], "completed"),
        ):
            runtime = SimpleNamespace(session=Path("offline-cli-test"), max_inputs=96)
            store = Mock()
            with (
                self.subTest(mode=mode), redirect_stdout(io.StringIO()),
                patch.object(native, "require_campaign_home_atlas_building"),
                patch.object(native.LocalBlueStacksRuntime, "connect", return_value=runtime) as connect,
                patch.object(native, "open_canonical_action_store", return_value=store),
                patch.object(native, "CampaignStageChallengeBoundary") as stage_boundary,
                patch.object(native, "run_campaign_ap_route", return_value={"status": status}) as engine,
            ):
                code = native.main([*BASE, *extra, "--execute", "--yes"])
            self.assertEqual(code, 0)
            connect.assert_called_once()
            stage_boundary.assert_not_called()
            self.assertIs(engine.call_args.args[0], runtime)
            self.assertEqual(engine.call_args.args[1].navigation_only, mode == "navigation")
            self.assertIsNone(engine.call_args.kwargs["stage_challenge_boundary"])
            self.assertEqual(engine.call_args.kwargs["victory_home_only"], mode == "recovery")
            self.assertEqual(engine.call_args.kwargs["initial_ap"], 120 if mode == "recovery" else None)
            store.acquire_lease.assert_called_once()
            store.release_lease.assert_called_once()
            store.close.assert_called_once()

    def test_invalid_recovery_configuration_still_refuses_before_device(self):
        for extra in (["--victory-home-only"],
                      ["--victory-home-only", "--initial-ap", "120", "--max-runs", "2"],
                      ["--victory-home-only", "--initial-ap", "120", "--navigation-only"]):
            with (
                self.subTest(extra=extra), redirect_stderr(io.StringIO()),
                patch.object(native, "require_campaign_home_atlas_building"),
                patch.object(native.LocalBlueStacksRuntime, "connect") as connect,
                patch.object(native, "open_canonical_action_store") as store,
            ):
                with self.assertRaises(SystemExit) as raised:
                    native.main([*BASE, *extra, "--execute", "--yes"])
                self.assertEqual(raised.exception.code, 2)
                connect.assert_not_called()
                store.assert_not_called()


if __name__ == "__main__":
    unittest.main()
