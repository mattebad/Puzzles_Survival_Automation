"""The operator facade delegates native execution to the canonical service."""
from __future__ import annotations

from contextlib import nullcontext, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from automation_service import cli
from automation_service.registry import (
    NANO_MATERIAL_PRODUCTION_FLOW_ID,
    NANOWEAPON_FLOW_ID,
    HERO_DUEL_FLOW_ID,
    RECOMMENDED_RESEARCH_FLOW_ID,
    FOOD_FARM_BOOST_FLOW_ID,
    HALL_OF_WAR_FLOW_ID,
    canonical_flow_specs,
    TROOP_TRAINING_FLOW_ID,
)
from automation_service.state import BotStateManager
from scripts import navigation_development_boundary as boundary
from scripts import pnsctl
from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
from tasks.runtime_identity import BLUESTACKS_ADB


class CanonicalServeFacadeTests(unittest.TestCase):

    def test_a_global_option_value_named_serve_is_not_the_command(self):
        for common in (["--state-path", "serve"], ["--state-path=serve"], ["--mode", "serve"]):
            with self.subTest(common=common), patch.object(cli, "main") as canonical:
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    pnsctl.main(["automation-service", *common, "status"])
                self.assertEqual(error.exception.code, 2)
                canonical.assert_not_called()

    def test_help_exposes_the_canonical_serve_options(self):
        output = io.StringIO()
        with patch.object(LocalBlueStacksRuntime, "connect") as connect, patch(
            "scripts.resource_item_authorization.open_admitted_resource_store"
        ) as resource_store, patch(
            "scripts.base_route_native_runtime.open_canonical_action_store"
        ) as action_store, redirect_stdout(output):
            self.assertEqual(pnsctl.main(["automation-service", "serve", "--help"]), 0)
        connect.assert_not_called()
        resource_store.assert_not_called()
        action_store.assert_not_called()
        for option in (
            "--live",
            "--flow",
            "--campaign-stage",
            "--campaign-cadence-seconds",
            "ruins",
            "alliance-help",
            "nano-material-production",
            "nanoweapon",
            "hero-duel",
            "recommended-research",
            "food-farm-boost",
            "hall-of-war",
            "troop-training",
        ):
            self.assertIn(option, output.getvalue())
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as error:
            pnsctl.main(["automation-service", "--help"])
        self.assertEqual(error.exception.code, 0)

    def test_missing_native_authorization_is_rejected_before_state_or_device(self):
        base = ["automation-service", "--mode", "supervised", "--adapter", "bluestacks", "serve",
                "--serial", "emulator-5554", "--account-id", "account", "--server-id", "server"]
        for argv in ([*base, "--flow", "recruitment"], [*base, "--live", "--flow", "unknown"]):
            with self.subTest(argv=argv), patch.object(cli, "BotStateManager") as state, patch.object(
                LocalBlueStacksRuntime, "connect"
            ) as connect, redirect_stderr(io.StringIO()):
                self.assertEqual(pnsctl.main(argv), 2)
                state.assert_not_called()
                connect.assert_not_called()

    def test_missing_selection_is_an_argument_error_before_state_or_device(self):
        with patch.object(
            cli, "BotStateManager", side_effect=AssertionError("state initialization forbidden without selection")
        ) as state, patch(
            "scripts.bluestacks_native_runtime.ADBRunner", side_effect=AssertionError("device access forbidden")
        ) as adb, patch.object(
            LocalBlueStacksRuntime, "connect", side_effect=AssertionError("device access forbidden")
        ) as connect, redirect_stderr(io.StringIO()):
            self.assertEqual(pnsctl.main([
                "automation-service", "--mode", "supervised", "--adapter", "bluestacks",
                "serve", "--live", "--serial", "emulator-5554",
                "--account-id", "account", "--server-id", "server",
            ]), 2)
        state.assert_not_called()
        adb.assert_not_called()
        connect.assert_not_called()

    def test_batch_d_e_f_flows_keep_disabled_sqlite_controls_and_do_not_start_runtime(self):
        for flow, flow_id in (
            ("nano-material-production", NANO_MATERIAL_PRODUCTION_FLOW_ID),
            ("nanoweapon", NANOWEAPON_FLOW_ID),
            ("hero-duel", HERO_DUEL_FLOW_ID),
            ("recommended-research", RECOMMENDED_RESEARCH_FLOW_ID),
            ("food-farm-boost", FOOD_FARM_BOOST_FLOW_ID),
            ("hall-of-war", HALL_OF_WAR_FLOW_ID),
            ("troop-training", TROOP_TRAINING_FLOW_ID),
        ):
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as directory:
                database = Path(directory) / "isolated-state.sqlite3"
                with BotStateManager(database) as state:
                    state.initialize_flows(canonical_flow_specs())
                    self.assertFalse(state.get_service_enabled())
                    self.assertFalse(state.get_flow(flow_id).enabled)
                output = io.StringIO()
                with patch.object(boundary, "RuntimeInputLock", return_value=nullcontext()), patch.object(
                    LocalBlueStacksRuntime, "connect"
                ) as connect, redirect_stdout(output):
                    code = pnsctl.main([
                        "automation-service", "--mode", "supervised", "--adapter", "bluestacks",
                        "--state-path", str(database), "serve", "--live", "--flow", flow,
                        "--adb", str(BLUESTACKS_ADB),
                        "--serial", "emulator-5554", "--account-id", "account", "--server-id", "server",
                    ])
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(output.getvalue())["reason"], "SERVICE_DISABLED")
                connect.assert_not_called()
                with BotStateManager(database, read_only=True) as state:
                    self.assertFalse(state.get_service_enabled())
                    self.assertFalse(state.get_flow(flow_id).enabled)
                    self.assertEqual(state._db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)

    def test_a_valid_native_command_respects_disabled_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "isolated-state.sqlite3"
            with BotStateManager(database) as state:
                state.initialize_flows(canonical_flow_specs())
                self.assertFalse(state.get_service_enabled())
            output = io.StringIO()
            with patch.object(boundary, "RuntimeInputLock", return_value=nullcontext()), patch.object(
                LocalBlueStacksRuntime, "connect"
            ) as connect, redirect_stdout(output):
                code = pnsctl.main([
                    "automation-service", "--mode", "supervised", "--adapter", "bluestacks",
                    "--state-path", str(database), "serve", "--live", "--flow", "campaign",
                    "--adb", str(BLUESTACKS_ADB),
                    "--serial", "emulator-5554", "--account-id", "account", "--server-id", "server",
                ])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["reason"], "SERVICE_DISABLED")
            connect.assert_not_called()
            with BotStateManager(database, read_only=True) as state:
                self.assertFalse(state.get_service_enabled())
                self.assertFalse(any(row[0] for row in state._db.execute("SELECT enabled FROM flow_state")))
                self.assertEqual(state._db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)

    def test_a_native_command_off_the_fixed_bluestacks_adb_is_rejected_before_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "isolated-state.sqlite3"
            with BotStateManager(database) as state:
                state.initialize_flows(canonical_flow_specs())
            for adb in ((), ("--adb", "adb")):
                with self.subTest(adb=adb):
                    output = io.StringIO()
                    with patch.object(boundary, "RuntimeInputLock", return_value=nullcontext()), patch.object(
                        LocalBlueStacksRuntime, "connect"
                    ) as connect, redirect_stdout(output):
                        code = pnsctl.main([
                            "automation-service", "--mode", "supervised", "--adapter", "bluestacks",
                            "--state-path", str(database), "serve", "--live", "--flow", "campaign", *adb,
                            "--serial", "emulator-5554", "--account-id", "account", "--server-id", "server",
                        ])
                    self.assertEqual(code, 2)
                    self.assertEqual(json.loads(output.getvalue())["error"],
                                     "native application startup requires the fixed BlueStacks runtime")
                    connect.assert_not_called()
            with BotStateManager(database, read_only=True) as state:
                self.assertEqual(state._db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)

    def test_direct_service_cli_cannot_serve_native_without_the_pnsctl_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with patch.object(LocalBlueStacksRuntime, "connect") as connect, redirect_stdout(output):
                code = cli.main([
                    "--mode", "supervised", "--adapter", "bluestacks",
                    "--state-path", str(Path(directory) / "state.sqlite3"), "serve", "--live",
                    "--flow", "campaign", "--serial", "emulator-5554",
                    "--account-id", "account", "--server-id", "server",
                ])
            self.assertEqual(code, 2)
            self.assertIn("native application startup is supplied by", json.loads(output.getvalue())["error"])
            connect.assert_not_called()

    def test_ordinary_legacy_campaign_stops_before_receipt_or_runtime(self):
        with patch.object(pnsctl, "_consume_delegated_receipt") as receipt, patch.object(
            pnsctl, "_load_bluestacks_flow_registry"
        ) as registry, patch.object(boundary, "DevelopmentSession") as session, patch.object(
            pnsctl, "_development_runtime_observation"
        ) as observe:
            with self.assertRaises(pnsctl.OperatorError):
                pnsctl.development_session_run_flow(
                    pnsctl.CAMPAIGN_AP_FLOW_ID, live=True, yes=True,
                    delegated_receipt=Path("unused-receipt.json"),
                )
            for operation in (receipt, registry, session, observe):
                operation.assert_not_called()


    def test_explicit_campaign_recovery_keeps_its_existing_proof_gate(self):
        flow = pnsctl.CAMPAIGN_AP_FLOW_ID
        with patch.object(pnsctl, "_load_bluestacks_flow_registry", return_value={flow: {"runner": "recovery-test"}}), patch.dict(
            pnsctl._BLUESTACKS_FLOW_RUNNERS, {"recovery-test": Mock()}
        ), patch("tasks.campaign_victory_recovery.load_victory_recovery_proof", side_effect=ValueError("invalid proof")) as proof, patch.object(
            boundary, "DevelopmentSession"
        ) as session:
            with self.assertRaises(pnsctl.OperatorError):
                pnsctl.development_session_run_flow(flow, live=True, yes=True, recovery_only=True,
                                                    recovery_session=Path("retained-proof"))
            proof.assert_called_once_with(Path("retained-proof"))
            session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
