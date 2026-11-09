from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.purchases_disabled import (
    ALLIANCE_CURRENCY,
    ALLIANCE_FALLBACK_ITEM,
    ALLIANCE_OTHER_SHOP,
    ALLIANCE_WEEKLY_SHOP,
    PurchaseObservation,
    RARE_EARTH_CURRENCY,
    RARE_EARTH_MODULE_ITEM,
    RARE_EARTH_SHOP,
    RUINS_CHIP_ITEM,
    RUINS_CURRENCY,
    RUINS_SHOP,
    ShopOffer,
    alliance_shop_choice,
    daily_shop_quantity,
    purchase_authorizeable,
    purchase_dialog_matches,
    purchase_disabled_dispatch,
    purchase_acknowledgements,
    purchase_acknowledged,
    purchase_postcondition_verified,
    canonical_purchase_action_key,
)
from tests.support.observations import load_observation


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_disabled_purchase_observations.json"
MATRIX = ROOT / "tasks/daily_quest_execution_matrix.json"


def load_fixture(name: str) -> PurchaseObservation:
    return load_observation(
        FIXTURE, name, PurchaseObservation,
        ("target_roi", "panel_bounds", "evidence_refs"),
    )


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




def shop_offer(shop, item, currency, price, balance, stock, item_quantity, *,
               rarity=None, available=None, premium=False, recognized=True):
    return ShopOffer(
        shop_identity=shop,
        item_identity=item,
        currency_identity=currency,
        unit_price=price,
        balance=balance,
        stock=stock,
        item_quantity=item_quantity,
        rarity=rarity,
        available=(stock > 0 if available is None else available),
        premium=premium,
        recognized=recognized,
    )


class ApprovedPurchasePolicyTests(unittest.TestCase):
    def test_alliance_selects_one_exact_affordable_weekly_offer(self):
        preferred = shop_offer(
            ALLIANCE_WEEKLY_SHOP, "Bioenhance Scheme", ALLIANCE_CURRENCY,
            37, 100, 4, 8,
        )
        fallback = shop_offer(
            ALLIANCE_OTHER_SHOP, ALLIANCE_FALLBACK_ITEM, ALLIANCE_CURRENCY,
            9, 100, 10, 3, rarity=1,
        )
        choice = alliance_shop_choice(
            (preferred,), fallback,
            weekly_inventory_complete=True,
            fallback_inventory_complete=True,
        )
        self.assertEqual((choice.status, choice.offer, choice.quantity),
                         ("selected", preferred, 1))
        self.assertEqual(choice.reason, "AFFORDABLE_PREFERRED_OFFER")

    def test_unaffordable_or_sold_out_weekly_reaches_only_other_fallback(self):
        fallback = shop_offer(
            ALLIANCE_OTHER_SHOP, ALLIANCE_FALLBACK_ITEM, ALLIANCE_CURRENCY,
            7, 10, 6, 2, rarity=1,
        )
        for preferred in (
            shop_offer(ALLIANCE_WEEKLY_SHOP, "Timed Recruit Coin", ALLIANCE_CURRENCY,
                       11, 10, 2, 0),
            shop_offer(ALLIANCE_WEEKLY_SHOP, "Bioenhance Scheme", ALLIANCE_CURRENCY,
                       11, 10, 0, 0, available=False),
        ):
            choice = alliance_shop_choice(
                (preferred,), fallback,
                weekly_inventory_complete=True,
                fallback_inventory_complete=True,
            )
            self.assertEqual((choice.status, choice.offer, choice.quantity),
                             ("selected", fallback, 1))
            self.assertEqual(choice.reason, "AFFORDABLE_EXACT_FALLBACK")

    def test_alliance_rejects_unknown_alternate_and_premium_preferred_evidence(self):
        fallback = shop_offer(
            ALLIANCE_OTHER_SHOP, ALLIANCE_FALLBACK_ITEM, ALLIANCE_CURRENCY,
            7, 10, 6, 2, rarity=1,
        )
        for changed in (
            shop_offer(ALLIANCE_WEEKLY_SHOP, "Timed Recruit Coin", "Diamonds",
                       1, 50, 2, 0),
            shop_offer(ALLIANCE_WEEKLY_SHOP, "Bioenhance Scheme", ALLIANCE_CURRENCY,
                       7, 10, 2, 0, premium=True),
            shop_offer(ALLIANCE_WEEKLY_SHOP, "Joy Coin", ALLIANCE_CURRENCY,
                       None, 10, 2, 0),
        ):
            choice = alliance_shop_choice(
                (changed,), fallback,
                weekly_inventory_complete=True,
                fallback_inventory_complete=True,
            )
            self.assertEqual(choice.status, "blocked")
        excluded = shop_offer(
            ALLIANCE_WEEKLY_SHOP, "Int. Recruit Coin", "Diamonds",
            1, 50, 2, 0,
        )
        choice = alliance_shop_choice(
            (excluded,), fallback,
            weekly_inventory_complete=True,
            fallback_inventory_complete=True,
        )
        self.assertEqual((choice.status, choice.offer), ("selected", fallback))

    def test_alliance_inventory_ambiguity_and_fallback_limits_fail_closed(self):
        valid = shop_offer(
            ALLIANCE_WEEKLY_SHOP, "Joy Coin", ALLIANCE_CURRENCY,
            7, 10, 1, 0,
        )
        fallback = shop_offer(
            ALLIANCE_OTHER_SHOP, ALLIANCE_FALLBACK_ITEM, ALLIANCE_CURRENCY,
            7, 10, 1, 0, rarity=1,
        )
        for choice in (
            alliance_shop_choice(
                (valid,), fallback,
                weekly_inventory_complete=False,
                fallback_inventory_complete=True,
            ),
            alliance_shop_choice(
                (replace(valid, recognized=False),), fallback,
                weekly_inventory_complete=True,
                fallback_inventory_complete=True,
            ),
            alliance_shop_choice(
                (valid, valid), fallback,
                weekly_inventory_complete=True,
                fallback_inventory_complete=True,
            ),
            alliance_shop_choice(
                (), None,
                weekly_inventory_complete=True,
                fallback_inventory_complete=True,
            ),
            alliance_shop_choice(
                (), replace(fallback, currency_identity="Diamonds"),
                weekly_inventory_complete=True,
                fallback_inventory_complete=True,
            ),
        ):
            self.assertIn(choice.status, {"blocked", "deferred"})
        self.assertEqual(
            alliance_shop_choice(
                (), fallback,
                weekly_inventory_complete=True,
                fallback_inventory_complete=True,
            ).quantity,
            1,
        )

    def test_daily_shop_maximum_is_exact_stock_and_affordability_minimum(self):
        stock_limited = shop_offer(
            RUINS_SHOP, RUINS_CHIP_ITEM, RUINS_CURRENCY, 13, 1000, 4, 2,
            rarity=3,
        )
        balance_limited = shop_offer(
            RARE_EARTH_SHOP, RARE_EARTH_MODULE_ITEM, RARE_EARTH_CURRENCY,
            13, 85, 20, 1, rarity=3,
        )
        self.assertEqual(daily_shop_quantity(stock_limited, shop_identity=RUINS_SHOP), 4)
        self.assertEqual(daily_shop_quantity(balance_limited, shop_identity=RARE_EARTH_SHOP), 6)
        self.assertEqual(
            daily_shop_quantity(
                replace(balance_limited, balance=0),
                shop_identity=RARE_EARTH_SHOP,
            ),
            0,
        )
        self.assertEqual(
            daily_shop_quantity(
                replace(stock_limited, stock=0, available=False),
                shop_identity=RUINS_SHOP,
            ),
            0,
        )

    def test_daily_shop_rejects_wrong_item_rarity_currency_and_uncertain_cost(self):
        valid = shop_offer(
            RARE_EARTH_SHOP, RARE_EARTH_MODULE_ITEM, RARE_EARTH_CURRENCY,
            13, 85, 20, 0, rarity=3,
        )
        for changed in (
            replace(valid, item_identity="Module Promoter"),
            replace(valid, rarity=2),
            replace(valid, currency_identity="Diamonds"),
            replace(valid, unit_price=None),
            replace(valid, available=False),
            replace(valid, premium=True),
            replace(valid, recognized=False),
        ):
            self.assertIsNone(daily_shop_quantity(changed, shop_identity=RARE_EARTH_SHOP))
        self.assertIsNone(daily_shop_quantity(valid, shop_identity=RUINS_SHOP))

    def test_numeric_quantity_and_total_bind_the_purchase_dialog(self):
        offer = shop_offer(
            RUINS_SHOP, RUINS_CHIP_ITEM, RUINS_CURRENCY,
            13, 85, 20, 10, rarity=3,
        )
        self.assertTrue(purchase_dialog_matches(
            offer, quantity=6, selected_quantity=6, displayed_total=78,
        ))
        self.assertFalse(purchase_dialog_matches(
            offer, quantity=6, selected_quantity=5, displayed_total=65,
        ))
        self.assertFalse(purchase_dialog_matches(
            offer, quantity=6, selected_quantity=6, displayed_total=77,
        ))

    def test_exact_acknowledgement_binds_item_and_quantity_without_owned(self):
        offer = shop_offer(
            RUINS_SHOP, RUINS_CHIP_ITEM, RUINS_CURRENCY,
            13, 85, 20, None, rarity=3,
        )
        acknowledgements = purchase_acknowledgements(
            ("Obtained [3★ Chip Enhance Material]x6",),
        )
        self.assertEqual(acknowledgements, ((RUINS_CHIP_ITEM, 6),))
        self.assertTrue(purchase_acknowledged(
            offer, quantity=6, acknowledgements=acknowledgements,
        ))
        for observed in ((), ((RUINS_CHIP_ITEM, 5),),
                         (("3★ Module Enhance Material", 6),),
                         acknowledgements + acknowledgements):
            self.assertFalse(purchase_acknowledged(
                offer, quantity=6, acknowledgements=observed,
            ))

    def test_red_preferred_shortage_allows_fallback_without_numeric_baseline(self):
        preferred = replace(shop_offer(
            ALLIANCE_WEEKLY_SHOP, "Bioenhance Scheme", ALLIANCE_CURRENCY,
            None, None, 4, None,
        ), price_shortage=True)
        fallback = shop_offer(
            ALLIANCE_OTHER_SHOP, ALLIANCE_FALLBACK_ITEM, ALLIANCE_CURRENCY,
            9, 100, 10, None, rarity=1,
        )
        choice = alliance_shop_choice(
            (preferred,), fallback, weekly_inventory_complete=True,
            fallback_inventory_complete=True,
        )
        self.assertEqual((choice.status, choice.offer, choice.quantity),
                         ("selected", fallback, 1))

    def test_canonical_action_keys_are_reset_scoped_not_pulse_scoped(self):
        class Identity:
            account_id = "account-a"
            server_id = "server-a"
            reset_id = "game-day-2030-01-02"
            task_id = "daily_shops_purchase"

        identity = Identity()
        key = canonical_purchase_action_key(
            "DAILY-SHOPS-PURCHASE-EVIDENCE-GATE",
            "daily_shops_purchase",
            identity,
            "ruins_shop",
        )
        self.assertEqual(
            key,
            canonical_purchase_action_key(
                "DAILY-SHOPS-PURCHASE-EVIDENCE-GATE",
                "daily_shops_purchase",
                identity,
                "ruins_shop",
            ),
        )
        identity.reset_id = "game-day-2030-01-03"
        self.assertNotEqual(
            key,
            canonical_purchase_action_key(
                "DAILY-SHOPS-PURCHASE-EVIDENCE-GATE",
                "daily_shops_purchase",
                identity,
                "ruins_shop",
            ),
        )
        with self.assertRaises(ValueError):
            canonical_purchase_action_key(
                "DAILY-SHOPS-PURCHASE-EVIDENCE-GATE",
                "daily_shops_purchase",
                identity,
                "Rare Earth",
            )


if __name__ == "__main__":
    unittest.main()
