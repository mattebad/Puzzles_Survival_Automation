"""Focused tests for the BlueStacks Daily Row flow-delivery adapter."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

import scripts.pnsctl as pnsctl
from scripts.flow_delivery_daily_row_claim_bluestacks import (
    FLOW_ID,
    MAX_INPUTS,
    RUNNER_ID,
    _max_inputs,
    run_daily_row_claim,
)


class DailyRowClaimFlowDeliveryTests(unittest.TestCase):
    def _lease(self, *, maximum: int = MAX_INPUTS):
        return {
            "owner": "outer-development-session",
            "max_inputs": maximum,
            "development_session": SimpleNamespace(
                session_directory=Path("tests") / "daily-row-claim-dry-run-session",
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
            "daily_row_claim_bluestacks_recovery",
        )

    def test_dry_run_is_zero_transport_and_preserves_disabled_state(self):
        result = run_daily_row_claim(
            {"active_flow_id": FLOW_ID},
            self._lease(),
            live=False,
        )
        self.assertIn('"status": "dry_run"', result)
        self.assertIn('"input_count": 0', result)
        self.assertIn('"dispatch": false', result)
        self.assertIn('"production_registration": "NOT_REGISTERED"', result)
        self.assertIn('"scheduler_enabled": false', result)

    def test_max_inputs_is_bounded_at_reconnaissance_plus_canary_ceiling(self):
        self.assertEqual(_max_inputs(self._lease(maximum=MAX_INPUTS)), MAX_INPUTS)
        with self.assertRaises(pnsctl.OperatorError):
            _max_inputs(self._lease(maximum=MAX_INPUTS + 1))
        with self.assertRaises(pnsctl.OperatorError):
            _max_inputs(self._lease(maximum=0))


if __name__ == "__main__":
    unittest.main()
