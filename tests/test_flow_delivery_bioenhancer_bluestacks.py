"""Focused tests for the BlueStacks Bioenhancer flow-delivery adapter."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import unittest
from unittest.mock import patch

import scripts.pnsctl as pnsctl
from scripts.bioenhancer_free_research_canary import (
    _free_research_cooldown_visible,
    evaluate_free_research_postcondition,
)
from scripts.flow_delivery_bioenhancer_bluestacks import (
    FLOW_ID,
    MAX_INPUTS,
    RUNNER_ID,
    _write_delivery_result,
    _max_inputs,
    run_bioenhancer_free_research,
)


class BioenhancerFlowDeliveryTests(unittest.TestCase):
    def _lease(self, *, maximum: int = 8):
        return {
            "owner": "outer-development-session",
            "max_inputs": maximum,
            "development_session": SimpleNamespace(
                session_directory=Path("tests") / "bioenhancer-dry-run-session",
                run_action=lambda **_kwargs: None,
            ),
        }

    def test_registry_binds_consequential_runner_without_promotion(self):
        contract = pnsctl._load_bluestacks_flow_registry()[FLOW_ID]
        self.assertEqual(contract["runner"], RUNNER_ID)
        self.assertEqual(contract["consequence_class"], "consequential")
        self.assertIn(RUNNER_ID, pnsctl._BLUESTACKS_FLOW_RUNNERS)
        self.assertEqual(
            contract["recovery_handler"],
            "bioenhancer_free_research_bluestacks_recovery",
        )

    def test_dry_run_is_zero_transport_and_preserves_disabled_state(self):
        result = run_bioenhancer_free_research(
            {"active_flow_id": FLOW_ID},
            self._lease(),
            live=False,
        )
        self.assertIn('"status": "dry_run"', result)
        self.assertIn('"input_count": 0', result)
        self.assertIn('"free_research_transport_calls": 0', result)
        self.assertIn('"production_registration": "NOT_REGISTERED"', result)
        self.assertIn('"scheduler_enabled": false', result)

    def test_max_inputs_is_bounded(self):
        self.assertEqual(_max_inputs(self._lease(maximum=MAX_INPUTS)), MAX_INPUTS)
        with self.assertRaises(pnsctl.OperatorError):
            _max_inputs(self._lease(maximum=MAX_INPUTS + 1))
        with self.assertRaises(pnsctl.OperatorError):
            _max_inputs(self._lease(maximum=0))

    def test_free_research_postcondition_requires_cooldown_timer(self):
        self.assertEqual(
            evaluate_free_research_postcondition("Free in 18:12:44"),
            {
                "count_observed": False,
                "timer_proven": True,
                "proven": True,
            },
        )
        for token_text in ("2/100", "1/100"):
            with self.subTest(token_text=token_text):
                self.assertEqual(
                    evaluate_free_research_postcondition(token_text),
                    {
                        "count_observed": True,
                        "timer_proven": False,
                        "proven": False,
                    },
                )

    def test_free_research_cooldown_rejects_binding_evidence(self):
        self.assertTrue(_free_research_cooldown_visible("Free in 18:11:52 2/100"))
        self.assertFalse(_free_research_cooldown_visible("Free Research 1x"))

    def test_completed_artifact_passes_operational_generic_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / ".local-captures" / "bioenhancer-completed"
            (session / "frames").mkdir(parents=True)
            (session / "frames" / "terminal.png").write_bytes(b"native-frame")
            (session / "events.jsonl").write_text("{}\n", encoding="utf-8")
            _write_delivery_result(
                session,
                {
                    "status": "completed",
                    "free_research_transport_calls": 1,
                    "input_count": 4,
                    "terminal_home_verified": True,
                    "reason": "free_research_postcondition_verified",
                },
                lease={"owner": "test-owner"},
                maximum=8,
            )
            with (
                patch.object(pnsctl, "REPO_ROOT", root),
                patch.object(
                    pnsctl,
                    "_load_flow_delivery_state",
                    side_effect=pnsctl.OperatorError("no active delivery"),
                ),
            ):
                verdict = json.loads(pnsctl.bluestacks_verify_flow(session))
            self.assertEqual(verdict["status"], "verified")
            self.assertEqual(verdict["flow_id"], FLOW_ID)


if __name__ == "__main__":
    unittest.main()
