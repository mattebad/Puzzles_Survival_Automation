from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import daily_resource_item_bluestacks as route
from scripts import flow_delivery_daily_resource_item_bluestacks as delivery
from scripts import pnsctl


def _write_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Minimal non-empty PNG-like payload for existence checks.
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)


def _frame_ref(path: Path, sha: str) -> dict[str, object]:
    return {"path": path.as_posix(), "sha256": sha}


class DailyResourceItemDeliveryTests(unittest.TestCase):
    def test_authoritative_budgets_agree_across_active_sources(self):
        contract = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "tasks"
                / "gameplay_flow_contracts"
                / "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION.json"
            ).read_text(encoding="utf-8")
        )
        profile = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "tasks"
                / "flow_delivery_validation_profiles.json"
            ).read_text(encoding="utf-8")
        )["flow_profiles"][delivery.FLOW_ID]
        self.assertEqual(route.MAX_ROUTE_INPUTS, 10)
        self.assertEqual(route.MAX_RESOURCE_LIST_SWIPES, 6)
        self.assertEqual(delivery.MAX_INPUTS, route.MAX_ROUTE_INPUTS)
        self.assertEqual(
            delivery.MAX_RESOURCE_LIST_SWIPES, route.MAX_RESOURCE_LIST_SWIPES
        )
        self.assertEqual(
            pnsctl._CONDUCT_DEFAULT_MAX_INPUTS[delivery.FLOW_ID],
            route.MAX_ROUTE_INPUTS,
        )
        self.assertEqual(
            contract["navigation_input_authorization"]["maximum_inputs"],
            route.MAX_ROUTE_INPUTS,
        )
        self.assertEqual(
            contract["navigation_input_authorization"]["maximum_resource_list_swipes"],
            route.MAX_RESOURCE_LIST_SWIPES,
        )
        self.assertEqual(profile["maximum_inputs"], route.MAX_ROUTE_INPUTS)
        self.assertEqual(
            profile["maximum_resource_list_swipes"], route.MAX_RESOURCE_LIST_SWIPES
        )

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

        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            before = session / "frames" / "item-before.png"
            after = session / "frames" / "item-after.png"
            home = session / "frames" / "home.png"
            _write_png(before)
            _write_png(after)
            _write_png(home)
            events = session / "events.jsonl"
            events.write_text(
                json.dumps(
                    {
                        "type": "dispatch",
                        "execute": True,
                        "action_key": delivery.ITEM_USE_ACTION_KEY,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            verified = delivery.verify_daily_resource_item(
                {
                    "result": {
                        "status": "completed",
                        "item_use_transport_calls": 1,
                        "resource_delta_verified": True,
                        "terminal_home_verified": True,
                        "terminal_runtime_state": "recognized_home",
                        "events_path": "events.jsonl",
                        "production_registration": "NOT_REGISTERED",
                        "scheduler_enabled": False,
                        "semantic_evidence": {
                            "before_owned_quantity": 129680,
                            "after_owned_quantity": 129679,
                            "before_food_resource": None,
                            "after_food_resource": None,
                            "item_before_frame": _frame_ref(before, "a" * 64),
                            "item_after_frame": _frame_ref(after, "b" * 64),
                            "terminal_home_frame": _frame_ref(home, "c" * 64),
                        },
                    },
                    "session_directory": str(session),
                },
                {},
                {},
            )
        self.assertEqual(verified["status"], "verified")
        self.assertEqual(verified["production_registration"], "NOT_REGISTERED")
        self.assertFalse(verified["scheduler_enabled"])

    def test_dry_run_has_zero_transport_and_ten_input_ceiling(self):
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
                },
                "session_directory": "session",
            },
            {},
            {},
        )
        self.assertEqual(result["status"], "evidence_required")

    def test_verifier_rejects_boolean_only_and_bad_event_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            before = session / "frames" / "item-before.png"
            after = session / "frames" / "item-after.png"
            home = session / "frames" / "home.png"
            _write_png(before)
            _write_png(after)
            _write_png(home)
            semantic = {
                "before_owned_quantity": 10,
                "after_owned_quantity": 9,
                "item_before_frame": _frame_ref(before, "a" * 64),
                "item_after_frame": _frame_ref(after, "b" * 64),
                "terminal_home_frame": _frame_ref(home, "c" * 64),
            }
            base = {
                "status": "completed",
                "item_use_transport_calls": 1,
                "resource_delta_verified": True,
                "terminal_home_verified": True,
                "terminal_runtime_state": "recognized_home",
                "events_path": "events.jsonl",
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
                "semantic_evidence": semantic,
            }

            # No matching Use event.
            (session / "events.jsonl").write_text("", encoding="utf-8")
            self.assertEqual(
                delivery.verify_daily_resource_item(
                    {"result": dict(base), "session_directory": str(session)},
                    {},
                    {},
                )["status"],
                "evidence_required",
            )

            # Two matching Use events.
            (session / "events.jsonl").write_text(
                "\n".join(
                    json.dumps(
                        {
                            "type": "dispatch",
                            "execute": True,
                            "action_key": delivery.ITEM_USE_ACTION_KEY,
                        }
                    )
                    for _ in range(2)
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                delivery.verify_daily_resource_item(
                    {"result": dict(base), "session_directory": str(session)},
                    {},
                    {},
                )["status"],
                "evidence_required",
            )

            # One event, but retained quantities do not support exact -1.
            (session / "events.jsonl").write_text(
                json.dumps(
                    {
                        "type": "dispatch",
                        "execute": True,
                        "action_key": delivery.ITEM_USE_ACTION_KEY,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            bad_delta = dict(base)
            bad_delta["semantic_evidence"] = {
                **semantic,
                "before_owned_quantity": 10,
                "after_owned_quantity": 8,
            }
            self.assertEqual(
                delivery.verify_daily_resource_item(
                    {"result": bad_delta, "session_directory": str(session)},
                    {},
                    {},
                )["status"],
                "evidence_required",
            )

            # Missing terminal Home frame.
            missing_home = dict(base)
            missing_home["semantic_evidence"] = {
                **semantic,
                "terminal_home_frame": None,
            }
            self.assertEqual(
                delivery.verify_daily_resource_item(
                    {"result": missing_home, "session_directory": str(session)},
                    {},
                    {},
                )["status"],
                "evidence_required",
            )


if __name__ == "__main__":
    unittest.main()
