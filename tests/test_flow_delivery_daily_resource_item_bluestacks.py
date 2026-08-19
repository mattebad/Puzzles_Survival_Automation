from __future__ import annotations

import json
import unittest

from scripts import flow_delivery_daily_resource_item_bluestacks as delivery
from scripts import pnsctl


class DailyResourceItemDeliveryTests(unittest.TestCase):
    def test_pnsctl_has_fixed_runner_validator_and_recovery_bindings(self):
        self.assertIs(
            pnsctl._BLUESTACKS_FLOW_RUNNERS[delivery.RUNNER_ID],
            delivery.run_daily_resource_item,
        )
        self.assertIs(
            pnsctl._BLUESTACKS_EVIDENCE_VALIDATORS[delivery.VALIDATOR_ID],
            delivery.verify_daily_resource_item,
        )
        self.assertIs(
            pnsctl._BLUESTACKS_RECOVERY_HANDLERS[delivery.RECOVERY_ID],
            delivery.recover_daily_resource_item,
        )
        self.assertEqual(
            pnsctl._CONDUCT_DEFAULT_MAX_INPUTS[delivery.FLOW_ID],
            delivery.MAX_INPUTS,
        )
        self.assertEqual(delivery.MAX_INPUTS, 10)
        self.assertEqual(delivery.MAX_RESOURCE_LIST_SWIPES, 6)

    def test_registration_is_fixed_and_scheduler_stays_disabled(self):
        runners: dict[str, object] = {}
        validators: dict[str, object] = {}
        recoveries: dict[str, object] = {}
        delivery.register(runners, validators, recoveries)
        self.assertIs(runners[delivery.RUNNER_ID], delivery.run_daily_resource_item)
        self.assertIs(
            validators[delivery.VALIDATOR_ID],
            delivery.verify_daily_resource_item,
        )
        self.assertIs(
            recoveries[delivery.RECOVERY_ID],
            delivery.recover_daily_resource_item,
        )

        verified = delivery.verify_daily_resource_item(
            {
                "result": {
                    "status": "completed",
                    "item_use_transport_calls": 1,
                    "resource_delta_verified": True,
                    "terminal_home_verified": True,
                },
                "session_directory": "session",
            },
            {},
            {},
        )
        self.assertEqual(verified["status"], "verified")
        self.assertEqual(verified["production_registration"], "NOT_REGISTERED")
        self.assertFalse(verified["scheduler_enabled"])

    def test_dry_run_has_zero_transport_and_eleven_input_ceiling(self):
        payload = json.loads(
            delivery.run_daily_resource_item(
                {},
                {"max_inputs": 10},
                live=False,
            )
        )
        self.assertEqual(payload["status"], "dry_run")
        self.assertFalse(payload["dispatch"])
        self.assertEqual(payload["input_count"], 0)
        self.assertEqual(payload["max_inputs"], 10)
        self.assertEqual(payload["max_resource_list_swipes"], 6)
        self.assertEqual(payload["item_use_transport_calls"], 0)
        self.assertFalse(payload["scheduler_enabled"])

    def test_invalid_input_ceiling_fails_closed(self):
        with self.assertRaises(Exception):
            delivery.run_daily_resource_item({}, {"max_inputs": 13}, live=False)
        with self.assertRaises(Exception):
            delivery.run_daily_resource_item({}, {"max_inputs": 12}, live=False)

    def test_incomplete_result_requires_evidence(self):
        result = delivery.verify_daily_resource_item(
            {
                "result": {
                    "status": "completed",
                    "item_use_transport_calls": 1,
                    "resource_delta_verified": False,
                    "terminal_home_verified": True,
                }
            },
            {},
            {},
        )
        self.assertEqual(result["status"], "evidence_required")


if __name__ == "__main__":
    unittest.main()
