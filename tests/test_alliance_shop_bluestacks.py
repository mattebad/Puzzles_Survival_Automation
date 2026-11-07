from __future__ import annotations

import unittest

from scripts.alliance_shop_bluestacks import (
    AllianceShopPurchaseRoute,
    OfferScan,
    PurchaseEffect,
    QuantityDialog,
)
from tasks.purchases_disabled import (
    ALLIANCE_CURRENCY,
    ALLIANCE_FALLBACK_ITEM,
    ALLIANCE_OTHER_SHOP,
    ALLIANCE_WEEKLY_SHOP,
    ShopOffer,
)


def offer(shop, item, currency=ALLIANCE_CURRENCY, *, price=37, balance=100,
          stock=4, owned=8, rarity=None, available=True, recognized=True):
    return ShopOffer(
        shop_identity=shop,
        item_identity=item,
        currency_identity=currency,
        unit_price=price,
        balance=balance,
        stock=stock,
        item_quantity=owned,
        rarity=rarity,
        available=available,
        recognized=recognized,
        offer_identity=f"{shop}:{item}",
    )


class ReplayAllianceShopPort:
    def __init__(self, *, weekly=(), weekly_complete=True, fallback=None,
                 fallback_complete=True, effect=None, dialog=None, prior=None,
                 home=True):
        self.weekly = OfferScan(
            tuple(weekly), weekly_complete, evidence_refs=("weekly-frame.png",),
            evidence_frame_sha256s=("a" * 64,),
        )
        self.fallback, self.fallback_complete = fallback, fallback_complete
        self.last_other_scan_evidence = {}
        self.effect = effect
        self.dialog_override = dialog
        self.prior = prior
        self.home = home
        self.other_entered = False
        self.purchases = []
        self.cancelled = 0
        self.home_calls = 0

    def action_status(self, _key):
        return self.prior

    def enter_weekly_offers(self):
        return True

    def scan_weekly_offers(self):
        return self.weekly

    def enter_other_offers(self):
        self.other_entered = True
        return True

    def scan_other_fallback(self):
        self.last_other_scan_evidence = {
            "frame_refs": ("other-frame.png",), "frame_sha256s": ("b" * 64,),
        }
        reason = "" if self.fallback is not None else "EXACT_FALLBACK_NOT_PRESENT"
        return self.fallback, self.fallback_complete, reason

    def open_quantity_dialog(self, selected):
        if self.dialog_override is not None:
            return self.dialog_override
        return QuantityDialog(
            selected.shop_identity, selected.item_identity, selected.currency_identity,
            selected.unit_price, 1, selected.unit_price, (500, 600, 600, 660),
        )

    def cancel_quantity_dialog(self):
        self.cancelled += 1
        return True

    def purchase_one(self, selected, _dialog, key):
        self.purchases.append((selected, key))
        if self.effect is not None:
            return self.effect
        return PurchaseEffect(
            status="confirmed", journal_status="confirmed", inner_buy_dispatched=True,
            purchase_transport_calls=1, currency_after=selected.balance - selected.unit_price,
            stock_after=selected.stock - 1, item_quantity_after=selected.item_quantity + 1,
            item_identity_after=selected.item_identity,
            currency_identity_after=selected.currency_identity,
            tab_successor_verified=True, action_key=key,
        )

    def return_home(self):
        self.home_calls += 1
        return self.home


class AllianceShopNativeReplayTests(unittest.TestCase):
    def test_affordable_preferred_offer_is_the_only_purchase(self):
        preferred = offer(ALLIANCE_WEEKLY_SHOP, "Bioenhance Scheme")
        fallback = offer(ALLIANCE_OTHER_SHOP, ALLIANCE_FALLBACK_ITEM,
                         price=9, rarity=1)
        port = ReplayAllianceShopPort(weekly=(preferred,), fallback=fallback)
        result = AllianceShopPurchaseRoute(port, action_key="reset-bound-key").run()
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.purchase_transport_calls, 1)
        self.assertEqual(result.committed_action_count, 1)
        self.assertEqual(port.purchases, [(preferred, "reset-bound-key")])
        self.assertFalse(port.other_entered)
        self.assertTrue(result.offer_effect_verified)
        self.assertTrue(result.terminal_home_verified)

    def test_unaffordable_preferred_offer_falls_back_to_exact_other_item(self):
        weekly = offer(ALLIANCE_WEEKLY_SHOP, "Timed Recruit Coin", price=101, balance=100)
        fallback = offer(ALLIANCE_OTHER_SHOP, ALLIANCE_FALLBACK_ITEM,
                         price=9, rarity=1)
        port = ReplayAllianceShopPort(weekly=(weekly,), fallback=fallback)
        result = AllianceShopPurchaseRoute(port, action_key="reset-bound-key").run()
        self.assertEqual(result.status, "completed")
        self.assertTrue(port.other_entered)
        self.assertEqual(port.purchases[0][0], fallback)
        self.assertEqual(result.selected_offer["quantity"], 1)
        evidence = result.to_mapping()["selection_evidence"]
        self.assertTrue(evidence["weekly_inventory"]["complete"])
        self.assertEqual(
            [(row["unit_price"], row["balance"]) for row in evidence["weekly_offers"]],
            [(101, 100)],
        )
        self.assertTrue(evidence["fallback_inventory"]["complete"])
        self.assertEqual(evidence["fallback_offer"]["offer_identity"], fallback.offer_identity)

    def test_diamond_int_recruit_coin_never_substitutes_for_timed_recruit_coin(self):
        excluded = offer(ALLIANCE_WEEKLY_SHOP, "Int. Recruit Coin", "Diamonds", price=1)
        fallback = offer(ALLIANCE_OTHER_SHOP, ALLIANCE_FALLBACK_ITEM,
                         price=9, rarity=1)
        port = ReplayAllianceShopPort(weekly=(excluded,), fallback=fallback)
        result = AllianceShopPurchaseRoute(port, action_key="reset-bound-key").run()
        self.assertEqual(result.status, "completed")
        self.assertEqual(port.purchases[0][0], fallback)

    def test_incomplete_weekly_inventory_blocks_fallback_authority(self):
        fallback = offer(ALLIANCE_OTHER_SHOP, ALLIANCE_FALLBACK_ITEM, rarity=1)
        port = ReplayAllianceShopPort(weekly=(), weekly_complete=False, fallback=fallback)
        result = AllianceShopPurchaseRoute(port, action_key="reset-bound-key").run()
        self.assertEqual(result.status, "blocked")
        self.assertFalse(port.other_entered)
        self.assertEqual(port.purchases, [])
        self.assertTrue(result.terminal_home_verified)

    def test_changed_quantity_dialog_is_cancelled_without_inner_buy(self):
        preferred = offer(ALLIANCE_WEEKLY_SHOP, "Joy Coin")
        dialog = QuantityDialog(
            ALLIANCE_WEEKLY_SHOP, "Joy Coin", ALLIANCE_CURRENCY,
            preferred.unit_price, 2, preferred.unit_price * 2,
            (500, 600, 600, 660),
        )
        port = ReplayAllianceShopPort(weekly=(preferred,), dialog=dialog)
        result = AllianceShopPurchaseRoute(port, action_key="reset-bound-key").run()
        self.assertEqual(result.status, "blocked")
        self.assertEqual(port.cancelled, 1)
        self.assertEqual(port.purchases, [])
        self.assertEqual(result.purchase_transport_calls, 0)

    def test_unknown_sent_purchase_is_not_retried_and_retains_reconciliation(self):
        preferred = offer(ALLIANCE_WEEKLY_SHOP, "Bioenhance Scheme")
        effect = PurchaseEffect(
            status="unresolved", journal_status="unresolved", inner_buy_dispatched=True,
            purchase_transport_calls=1, currency_after=None, stock_after=None,
            item_quantity_after=None, item_identity_after="", currency_identity_after="",
            tab_successor_verified=False, effect_reconciliation_required=True,
            identical_retry_denied=True, action_key="reset-bound-key", reason="unknown",
        )
        port = ReplayAllianceShopPort(weekly=(preferred,), effect=effect)
        result = AllianceShopPurchaseRoute(port, action_key="reset-bound-key").run()
        self.assertEqual(result.status, "unresolved")
        self.assertEqual(result.purchase_transport_calls, 1)
        self.assertTrue(result.effect_reconciliation_required)
        self.assertTrue(result.identical_retry_denied)
        self.assertEqual(len(port.purchases), 1)

    def test_restart_after_confirmation_recovers_home_without_dispatch(self):
        port = ReplayAllianceShopPort(prior="confirmed")
        result = AllianceShopPurchaseRoute(port, action_key="reset-bound-key").run()
        self.assertEqual(result.status, "already_complete")
        self.assertEqual(result.purchase_transport_calls, 0)
        self.assertEqual(result.committed_action_count, 0)
        self.assertEqual(result.prior_confirmed_action_count, 1)
        self.assertTrue(result.terminal_home_verified)

    def test_no_affordable_offer_is_deferred_not_fabricated_as_complete(self):
        weekly = offer(ALLIANCE_WEEKLY_SHOP, "Bioenhance Scheme", price=101, balance=100)
        port = ReplayAllianceShopPort(weekly=(weekly,), fallback=None)
        result = AllianceShopPurchaseRoute(port, action_key="reset-bound-key").run()
        self.assertEqual(result.status, "deferred")
        self.assertEqual(result.purchase_transport_calls, 0)
        self.assertTrue(result.accounting_verified)
        self.assertTrue(result.terminal_home_verified)

    def test_home_failure_does_not_report_success_after_purchase(self):
        preferred = offer(ALLIANCE_WEEKLY_SHOP, "Joy Coin")
        port = ReplayAllianceShopPort(weekly=(preferred,), home=False)
        result = AllianceShopPurchaseRoute(port, action_key="reset-bound-key").run()
        self.assertEqual(result.status, "unresolved")
        self.assertFalse(result.terminal_home_verified)
        self.assertTrue(result.effect_reconciliation_required)


if __name__ == "__main__":
    unittest.main()
