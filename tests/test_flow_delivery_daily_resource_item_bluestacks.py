from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from scripts import daily_resource_item_bluestacks as route
from scripts import flow_delivery_daily_resource_item_bluestacks as delivery
from scripts import pnsctl
from scripts.evidence_hygiene import sha256_stream


REPO = Path(__file__).resolve().parents[1]
LIVE_FRAMES = (
    REPO
    / ".local-captures"
    / "development-sessions"
    / "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION-20260819T042658331966Z"
    / "runtime"
    / "daily-resource-item-20260819T042658970087Z-20260819T042659055847Z"
    / "frames"
)


def _digest(path: Path) -> str:
    digest, _size = sha256_stream(path)
    return digest


def _frame_ref(path: Path) -> dict[str, object]:
    return {"path": path.as_posix(), "sha256": _digest(path)}


def _copy_into(session: Path, source: Path, name: str) -> Path:
    target = session / "frames" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def _write_blank_native(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = np.zeros((1280, 800, 3), dtype=np.uint8)
    cv2.imwrite(str(path), image)
    return path


class DailyResourceItemDeliveryTests(unittest.TestCase):
    def test_authoritative_budgets_agree_across_active_sources(self):
        contract = json.loads(
            (
                REPO
                / "tasks"
                / "gameplay_flow_contracts"
                / "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION.json"
            ).read_text(encoding="utf-8")
        )
        profile = json.loads(
            (REPO / "tasks" / "flow_delivery_validation_profiles.json").read_text(
                encoding="utf-8"
            )
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
        self.assertEqual(delivery.MAX_INPUTS, 10)
        self.assertEqual(delivery.MAX_RESOURCE_LIST_SWIPES, 6)

    def test_frame_binding_rejects_wrong_hash_escape_and_outside_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            frame = _write_blank_native(session / "frames" / "home.png")
            good = {"path": "frames/home.png", "sha256": _digest(frame)}
            self.assertIsNotNone(delivery._bound_retained_frame(session, good))

            wrong = {"path": "frames/home.png", "sha256": "a" * 64}
            self.assertIsNone(delivery._bound_retained_frame(session, wrong))

            missing = {"path": "frames/missing.png", "sha256": good["sha256"]}
            self.assertIsNone(delivery._bound_retained_frame(session, missing))

            escape = {"path": "../frames/home.png", "sha256": good["sha256"]}
            self.assertIsNone(delivery._bound_retained_frame(session, escape))

            outside = Path(tmp).parent / "outside-home.png"
            _write_blank_native(outside)
            absolute = {"path": str(outside), "sha256": _digest(outside)}
            self.assertIsNone(delivery._bound_retained_frame(session, absolute))

    def test_verifier_accepts_retained_live_frames_with_real_digests(self):
        before_src = LIVE_FRAMES / "0007-daily-resource-item:use-1k-food-immediate-before.png"
        after_src = LIVE_FRAMES / "0009-daily-resource-item-use-settled.png"
        home_src = LIVE_FRAMES / "0013-daily-resource-item-return-home-settled-final.png"
        if not (before_src.is_file() and after_src.is_file() and home_src.is_file()):
            self.skipTest("retained live Daily Resource Item frames are unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            before = _copy_into(session, before_src, "item-before.png")
            after = _copy_into(session, after_src, "item-after.png")
            home = _copy_into(session, home_src, "home.png")
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
                            "item_before_frame": {
                                "path": "frames/item-before.png",
                                "sha256": _digest(before),
                            },
                            "item_after_frame": {
                                "path": "frames/item-after.png",
                                "sha256": _digest(after),
                            },
                            "terminal_home_frame": {
                                "path": "frames/home.png",
                                "sha256": _digest(home),
                            },
                        },
                    },
                    "session_directory": str(session),
                },
                {},
                {},
            )
        self.assertEqual(verified["status"], "verified")
        self.assertEqual(verified["owned_before_rederived"], 129680)
        self.assertEqual(verified["owned_after_rederived"], 129679)
        self.assertTrue(verified["terminal_home_rerecognized"])
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
        before_src = LIVE_FRAMES / "0007-daily-resource-item:use-1k-food-immediate-before.png"
        after_src = LIVE_FRAMES / "0009-daily-resource-item-use-settled.png"
        home_src = LIVE_FRAMES / "0013-daily-resource-item-return-home-settled-final.png"
        if not (before_src.is_file() and after_src.is_file() and home_src.is_file()):
            self.skipTest("retained live Daily Resource Item frames are unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            before = _copy_into(session, before_src, "item-before.png")
            after = _copy_into(session, after_src, "item-after.png")
            home = _copy_into(session, home_src, "home.png")
            semantic = {
                "before_owned_quantity": 129680,
                "after_owned_quantity": 129679,
                "item_before_frame": {
                    "path": "frames/item-before.png",
                    "sha256": _digest(before),
                },
                "item_after_frame": {
                    "path": "frames/item-after.png",
                    "sha256": _digest(after),
                },
                "terminal_home_frame": {
                    "path": "frames/home.png",
                    "sha256": _digest(home),
                },
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

            def verify(result: dict) -> str:
                return delivery.verify_daily_resource_item(
                    {"result": result, "session_directory": str(session)},
                    {},
                    {},
                )["status"]

            (session / "events.jsonl").write_text("", encoding="utf-8")
            self.assertEqual(verify(dict(base)), "evidence_required")

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
            self.assertEqual(verify(dict(base)), "evidence_required")

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
            self.assertEqual(verify(bad_delta), "evidence_required")

            wrong_before = dict(base)
            wrong_before["semantic_evidence"] = {
                **semantic,
                "item_before_frame": {
                    "path": "frames/item-before.png",
                    "sha256": "a" * 64,
                },
            }
            self.assertEqual(verify(wrong_before), "evidence_required")

            wrong_after = dict(base)
            wrong_after["semantic_evidence"] = {
                **semantic,
                "item_after_frame": {
                    "path": "frames/item-after.png",
                    "sha256": "b" * 64,
                },
            }
            self.assertEqual(verify(wrong_after), "evidence_required")

            wrong_home = dict(base)
            wrong_home["semantic_evidence"] = {
                **semantic,
                "terminal_home_frame": {
                    "path": "frames/home.png",
                    "sha256": "c" * 64,
                },
            }
            self.assertEqual(verify(wrong_home), "evidence_required")

            missing_home = dict(base)
            missing_home["semantic_evidence"] = {
                **semantic,
                "terminal_home_frame": None,
            }
            self.assertEqual(verify(missing_home), "evidence_required")

            escaped = dict(base)
            escaped["semantic_evidence"] = {
                **semantic,
                "terminal_home_frame": {
                    "path": "../frames/home.png",
                    "sha256": _digest(home),
                },
            }
            self.assertEqual(verify(escaped), "evidence_required")

            # Non-Home pixels with claimed recognized_home flags.
            blank_home = _write_blank_native(session / "frames" / "blank-home.png")
            non_home = dict(base)
            non_home["semantic_evidence"] = {
                **semantic,
                "terminal_home_frame": {
                    "path": "frames/blank-home.png",
                    "sha256": _digest(blank_home),
                },
            }
            self.assertEqual(verify(non_home), "evidence_required")


if __name__ == "__main__":
    unittest.main()
