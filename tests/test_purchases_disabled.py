from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.purchases_disabled import (
    PurchaseObservation,
    purchase_authorizeable,
    purchase_disabled_dispatch,
    purchase_postcondition_verified,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_disabled_purchase_observations.json"
MATRIX = ROOT / "tasks/daily_quest_execution_matrix.json"


def load_fixture(name: str) -> PurchaseObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return PurchaseObservation(**payload)


class DisabledPurchaseContractTests(unittest.TestCase):
    def test_four_shop_variants_keep_objective_and_shop_identity_separate(self):
        variants = (
            ("valid_box", "buy_box", "BOX"),
            ("valid_ruins", "ruins_shop_purchase", "RUINS_SHOP"),
            ("valid_rare_earth", "rare_earth_shop_purchase", "RARE_EARTH_SHOP"),
            ("valid_alliance", "alliance_shop_purchase", "ALLIANCE_SHOP"),
        )
        for fixture_name, objective_key, shop_identity in variants:
            observation = load_fixture(fixture_name)
            self.assertTrue(purchase_authorizeable(observation))
            self.assertEqual(observation.objective_key, objective_key)
            self.assertEqual(observation.shop_identity, shop_identity)
            self.assertFalse(
                purchase_authorizeable(
                    replace(observation, objective_key="buy_box")
                )
                if objective_key != "buy_box"
                else purchase_authorizeable(
                    replace(observation, shop_identity="RUINS_SHOP")
                )
            )

    def test_cost_offer_and_source_guards_fail_closed(self):
        observation = load_fixture("valid_box")
        for changes in (
            {"offer_identity": ""},
            {"item_identity": ""},
            {"cost_known": False},
            {"cost_amount": 501},
            {"currency_balance_before": 99},
            {"reward_known": False},
            {"premium_offer": True},
            {"target_identity": "generic-buy"},
        ):
            self.assertFalse(purchase_authorizeable(replace(observation, **changes)))

    def test_main_and_ambiguous_states_fail_closed(self):
        observation = load_fixture("valid_box")
        self.assertFalse(purchase_authorizeable(load_fixture("main_negative")))
        for changes in (
            {"selected_daily_row": False},
            {"screen_state": "MAIN_QUEST"},
            {"target_provenance": "gnbots-reference"},
            {"overlay_state": "unknown"},
            {"reset_guard_active": True},
            {"recognized": False},
        ):
            self.assertFalse(purchase_authorizeable(replace(observation, **changes)))

    def test_purchase_successor_is_offline_cost_and_inventory_arithmetic_only(self):
        before = load_fixture("valid_box")
        after = replace(
            before,
            currency_balance_after=400,
            item_quantity_after=1,
            daily_progress_after=1,
            purchase_confirmed=True,
            successor_state="PURCHASE_RECONCILED",
        )
        self.assertTrue(purchase_postcondition_verified(before, after))
        self.assertFalse(
            purchase_postcondition_verified(
                before, replace(after, currency_balance_after=399)
            )
        )
        self.assertFalse(
            purchase_postcondition_verified(
                before, replace(after, item_identity="other-item")
            )
        )
        self.assertFalse(
            purchase_postcondition_verified(
                before, replace(after, shop_identity="RUINS_SHOP")
            )
        )

    def test_disabled_policy_blocks_dispatch_and_keeps_claim_separate(self):
        result = purchase_disabled_dispatch(load_fixture("valid_box"))
        self.assertEqual(result.outcome, TaskOutcome.BLOCKED)
        self.assertEqual(result.reason, "PURCHASE_DISABLED_POLICY")
        self.assertEqual(result.details["dispatch_count"], 0)
        self.assertIsNone(result.completion_key)

    def test_matrix_keeps_all_purchase_variants_disabled_and_dormant(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        keys = {
            "buy_box",
            "ruins_shop_purchase",
            "rare_earth_shop_purchase",
            "alliance_shop_purchase",
        }
        rows = [item for item in matrix["objectives"] if item["objective_key"] in keys]
        self.assertEqual({row["objective_key"] for row in rows}, keys)
        for row in rows:
            self.assertEqual(row["implementation_status"], "DISABLED_POLICY")
            self.assertEqual(row["promotion_state"], "DISABLED_POLICY")
            self.assertEqual(
                row["current_runtime_registration_status"], "NOT_REGISTERED"
            )
            self.assertFalse(row["scheduler_eligibility"])


if __name__ == "__main__":
    unittest.main()
