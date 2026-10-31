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
from automation_service.registry import canonical_flow_specs
from automation_service.state import BotStateManager
from scripts import navigation_development_boundary as boundary
from scripts import pnsctl
from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime


class CanonicalServeFacadeTests(unittest.TestCase):
    def test_native_options_and_exit_status_are_forwarded_unchanged(self):
        for common in (
            ["--mode", "supervised", "--adapter", "bluestacks", "--state-path", "state with spaces.sqlite3"],
            ["--mode=supervised", "--adapter=bluestacks", "--state-path=serve"],
        ):
            with self.subTest(common=common):
                argv = ["automation-service", *common, "serve", "--live"]
                for flow in ("nova", "campaign", "ultimate", "supply", "recruitment", "enhancement", "bioenhancer", "personal-might"):
                    argv.extend(["--flow", flow])
                argv.extend(["--campaign-stage", "1-15-9", "--campaign-cadence-seconds", "300",
                             "--adb", "C:/Program Files/BlueStacks_nxt/HD-Adb.exe", "--serial", "emulator-5554",
                             "--account-id", "account", "--server-id", "server", "--output-directory", "captures with spaces"])
                parsed = cli.build_parser().parse_args(argv[1:])
                self.assertEqual(parsed.mode, "supervised")
                self.assertEqual(len(parsed.flow), 8)
                with patch.object(cli, "main", return_value=17) as canonical:
                    self.assertEqual(pnsctl.main(argv), 17)
                canonical.assert_called_once_with(argv[1:])

    def test_a_global_option_value_named_serve_is_not_the_command(self):
        for common in (["--state-path", "serve"], ["--state-path=serve"], ["--mode", "serve"]):
            with self.subTest(common=common), patch.object(cli, "main") as canonical:
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    pnsctl.main(["automation-service", *common, "status"])
                self.assertEqual(error.exception.code, 2)
                canonical.assert_not_called()

    def test_help_exposes_the_canonical_serve_options(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(pnsctl.main(["automation-service", "serve", "--help"]), 0)
        for option in ("--live", "--flow", "--campaign-stage", "--campaign-cadence-seconds"):
            self.assertIn(option, output.getvalue())
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as error:
            pnsctl.main(["automation-service", "--help"])
        self.assertEqual(error.exception.code, 0)

    def test_missing_native_authorization_is_rejected_before_state_or_device(self):
        base = ["automation-service", "--mode", "supervised", "--adapter", "bluestacks", "serve",
                "--serial", "emulator-5554", "--account-id", "account", "--server-id", "server"]
        for argv in (base, [*base, "--live", "--flow", "unknown"]):
            with self.subTest(argv=argv), patch.object(cli, "BotStateManager") as state, patch.object(
                LocalBlueStacksRuntime, "connect"
            ) as connect, redirect_stderr(io.StringIO()):
                self.assertEqual(pnsctl.main(argv), 2)
                state.assert_not_called()
                connect.assert_not_called()

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
                    "--serial", "emulator-5554", "--account-id", "account", "--server-id", "server",
                ])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["reason"], "SERVICE_DISABLED")
            connect.assert_not_called()
            with BotStateManager(database, read_only=True) as state:
                self.assertFalse(state.get_service_enabled())
                self.assertFalse(any(row[0] for row in state._db.execute("SELECT enabled FROM flow_state")))
                self.assertEqual(state._db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)

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

    def test_ordinary_campaign_conductor_stops_before_state_or_runtime(self):
        with patch("tasks.flow_conductor.load_state") as load, patch.object(
            pnsctl, "development_session_run_flow"
        ) as run, patch.object(pnsctl, "development_session_observe") as observe:
            with self.assertRaises(pnsctl.OperatorError):
                pnsctl.conduct_flow(pnsctl.CAMPAIGN_AP_FLOW_ID, live=True, yes=True)
            for operation in (load, run, observe):
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

    def test_campaign_offline_conductor_modes_remain_available(self):
        framing = {key: True for key in ("intent_match", "no_documented_unsafe_input", "no_manual_only_precondition",
                                        "consequential_actions_enumerated", "durable_knowledge_consulted")}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = root / "summary.json"
            summary.write_text(json.dumps({"status": "blocked", "reason": "retained offline result"}), encoding="utf-8")
            with patch.object(pnsctl, "_derive_conductor_framing", return_value=framing), patch.object(
                pnsctl, "development_session_run_flow"
            ) as run, patch.object(pnsctl, "development_session_observe") as observe:
                dry = json.loads(pnsctl.conduct_flow(pnsctl.CAMPAIGN_AP_FLOW_ID, state_root=root))
                self.assertEqual(dry["status"], "dry_run")
                classified = json.loads(pnsctl.conduct_flow(pnsctl.CAMPAIGN_AP_FLOW_ID, live=True, yes=True,
                                                          state_root=root, summary_path=summary))
                self.assertIn("state_path", classified)
                run.assert_not_called()
                observe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
