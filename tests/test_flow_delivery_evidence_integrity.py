"""Executable command and operator-evidence integrity tests."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import pnsctl
from scripts.flow_delivery_evidence import (
    FlowEvidenceIntegrityError,
    REQUIRED_OPERATOR_ARTIFACTS,
    require_operator_evidence,
)


ROOT = Path(__file__).resolve().parents[1]


def _write_complete_operator_session(root: Path) -> None:
    (root / "result.json").write_text(
        json.dumps({"status": "completed", "terminal": "navigation_only_complete"}) + "\n",
        encoding="utf-8",
    )
    for name in REQUIRED_OPERATOR_ARTIFACTS:
        (root / name).write_text(json.dumps({"event": name}) + "\n", encoding="utf-8")
    frames = root / "frames"
    frames.mkdir()
    (frames / "frame-0001.png").write_bytes(b"nonempty-operator-frame")


class FlowDeliveryEvidenceIntegrityTests(unittest.TestCase):
    def test_complete_operator_evidence_is_returned_without_synthesis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_complete_operator_session(root)
            result, frames = require_operator_evidence(root)
        self.assertEqual(result["terminal"], "navigation_only_complete")
        self.assertEqual(frames, ["frames/frame-0001.png"])

    def test_missing_and_zero_byte_evidence_fail_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_complete_operator_session(root)
            (root / "journal.jsonl").unlink()
            with self.assertRaisesRegex(FlowEvidenceIntegrityError, "missing"):
                require_operator_evidence(root)
            (root / "journal.jsonl").write_bytes(b"")
            with self.assertRaisesRegex(FlowEvidenceIntegrityError, "zero-byte"):
                require_operator_evidence(root)

    def test_missing_frames_and_result_fail_without_fallback_capture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_complete_operator_session(root)
            for frame in (root / "frames").glob("*.png"):
                frame.unlink()
            with self.assertRaisesRegex(FlowEvidenceIntegrityError, "frames"):
                require_operator_evidence(root)
            (root / "result.json").unlink()
            with self.assertRaisesRegex(FlowEvidenceIntegrityError, "result"):
                require_operator_evidence(root)

    def test_campaign_and_ultimate_wrappers_do_not_create_placeholder_evidence(self) -> None:
        for path in (
            ROOT / "scripts" / "flow_delivery_campaign_bluestacks.py",
            ROOT / "scripts" / "flow_delivery_ultimate_challenge_bluestacks.py",
        ):
            source = path.read_text(encoding="utf-8")
            self.assertIn("require_operator_evidence", source)
            self.assertNotIn('write_text("", encoding="utf-8")', source)
            self.assertNotIn("operator-terminal.png", source)
            self.assertNotIn('_run_fixed_bluestacks_adb("exec-out", "screencap"', source)


class NovaPnsctlBoundaryTests(unittest.TestCase):
    def test_nova_command_is_narrow_and_parseable(self) -> None:
        args = pnsctl.parser().parse_args(["nova-praise-pulse"])
        self.assertEqual(args.command, "nova-praise-pulse")
        self.assertFalse(args.live)
        self.assertEqual(args.scenario, "nova_navigation_round_trip_no_praise")
        self.assertFalse(hasattr(args, "tap"))
        self.assertFalse(hasattr(args, "swipe"))

    def test_offline_command_runs_retained_production_replay(self) -> None:
        args = pnsctl.parser().parse_args(["nova-praise-pulse"])
        result = json.loads(pnsctl.nova_praise_pulse_replay(args))
        self.assertEqual(result["status"], "replay_confirmed")
        self.assertEqual(result["transport_calls"], 0)
        self.assertEqual(len(result["intended_inputs"]), 1)
        self.assertFalse(result["operational_state_mutated"])
        self.assertEqual(result["scenario_record"]["phase"], "pre_input")
        self.assertFalse(result["scenario_record"]["consumes_execution_budget"])
        self.assertEqual(result["production_registration"], "NOT_REGISTERED")
        self.assertFalse(result["scheduler_enabled"])

    def test_live_command_missing_identity_stops_before_runtime_connection(self) -> None:
        args = pnsctl.parser().parse_args(
            [
                "nova-praise-pulse",
                "--live",
                "--yes",
                "--supervised-live-opt-in",
            ]
        )
        result = json.loads(pnsctl.nova_praise_pulse_live(args))
        self.assertEqual(result["status"], "manual_required")
        self.assertFalse(result["runtime_connected"])
        self.assertEqual(result["transport_calls"], 0)
        self.assertIn("identity_evidence", result["missing_configuration_fields"])
        self.assertEqual(
            result["scenario_record"]["failure_class"],
            "supervised_identity",
        )
        self.assertFalse(result["scenario_record"]["consumes_execution_budget"])

    def test_verified_identity_is_passed_only_to_checked_in_navigation_runner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "identity.json"
            evidence.write_text(
                json.dumps(
                    {
                        "account_id": "acct-1",
                        "server_id": "server-1",
                        "reset_id": "reset-1",
                        "assurance": "supervised_navigation_binding",
                        "evidence_refs": ["operator-bound-current-frame"],
                    }
                ),
                encoding="utf-8",
            )
            args = pnsctl.parser().parse_args(
                [
                    "nova-praise-pulse",
                    "--live",
                    "--yes",
                    "--supervised-live-opt-in",
                    "--runtime-scope",
                    "bluestacks-dev-primary",
                    "--account-id",
                    "acct-1",
                    "--server-id",
                    "server-1",
                    "--reset-id",
                    "reset-1",
                    "--identity-evidence",
                    str(evidence),
                ]
            )
            with patch(
                "scripts.nova_praise_bluestacks.run_nova_navigation_canary",
                return_value=json.dumps(
                    {
                        "status": "completed",
                        "scenario_id": "nova_navigation_round_trip_no_praise",
                        "transport_calls": 3,
                        "navigation_input_count": 3,
                        "praise_taps": 0,
                    }
                ),
            ) as runner:
                result = json.loads(pnsctl.nova_praise_pulse_live(args))
            runner.assert_called_once()
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["praise_taps"], 0)
            self.assertEqual(result["scenario_record"]["phase"], "execution")
            self.assertTrue(result["scenario_record"]["consumes_execution_budget"])


if __name__ == "__main__":
    unittest.main()
