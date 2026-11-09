from __future__ import annotations
import hashlib
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np

from tests.support.environment import requires_tesseract

from safe_action_core import SafetyStore
from scripts.daily_shops_bluestacks import (
    DailyShopsPurchaseRoute,
    DailyShopsLivePort,
    PurchaseEffect,
    QuantityDialog,
    TabOffer,
    RUINS_TAB,
    RARE_EARTH_TAB,
    _purchase_daily_offer,
)
from tasks.purchases_disabled import (
    RARE_EARTH_CURRENCY,
    RARE_EARTH_MODULE_ITEM,
    RARE_EARTH_SHOP,
    RUINS_CHIP_ITEM,
    RUINS_CURRENCY,
    RUINS_SHOP,
    ShopOffer,
    daily_shop_quantity,
)
from tasks.scheduler_task_result import SchedulerIdentity


KEYS = {RUINS_TAB: "reset:ruins", RARE_EARTH_TAB: "reset:rare-earth"}


def offer(tab, *, price=None, balance=None, stock=None, owned=4):
    if tab == RUINS_TAB:
        return ShopOffer(
            RUINS_SHOP, RUINS_CHIP_ITEM, RUINS_CURRENCY,
            15 if price is None else price, 16649 if balance is None else balance,
            100 if stock is None else stock, owned, rarity=3,
            available=(100 if stock is None else stock) > 0,
            offer_identity="ruins:three-star-chip",
        )
    return ShopOffer(
        RARE_EARTH_SHOP, RARE_EARTH_MODULE_ITEM, RARE_EARTH_CURRENCY,
        13800 if price is None else price, 211995 if balance is None else balance,
        20 if stock is None else stock, owned, rarity=3,
        available=(20 if stock is None else stock) > 0,
        offer_identity="rare-earth:three-star-module",
    )


class ReplayDailyShopsPort:
    def __init__(self, *, offers=None, incomplete=(), prior=None, effect=None,
                 wrong_quantity=0, wrong_tab=RUINS_TAB, home=True):
        self.offers = dict(offers or {tab: offer(tab) for tab in (RUINS_TAB, RARE_EARTH_TAB)})
        self.incomplete = set(incomplete)
        self.prior = dict(prior or {})
        self.effect = effect
        self.wrong_quantity, self.wrong_tab = wrong_quantity, wrong_tab
        self.home = home
        self.purchases = []
        self.cancelled = 0
        self.entered = 0
        self.switched = 0
        self.home_calls = 0

    def action_status(self, key):
        return self.prior.get(key)

    def enter_ruins_shop(self):
        self.entered += 1
        return True

    def inspect_tab(self, tab):
        if tab in self.incomplete:
            return TabOffer(None, False, "EXACT_TAB_OFFER_NOT_AVAILABLE")
        return TabOffer(self.offers.get(tab), True)

    def open_quantity_dialog(self, tab, row):
        maximum = daily_shop_quantity(row, shop_identity=row.shop_identity)
        selected = min(maximum, 1)
        return QuantityDialog(
            row.shop_identity, row.item_identity, row.currency_identity,
            row.unit_price, selected, selected * row.unit_price,
            (430, 700, 560, 770), True,
        )

    def select_quantity(self, tab, row, quantity, dialog):
        selected = quantity + self.wrong_quantity if tab == self.wrong_tab else quantity
        return QuantityDialog(
            row.shop_identity, row.item_identity, row.currency_identity,
            row.unit_price, selected, selected * row.unit_price,
            dialog.inner_buy_roi, True,
        )

    def cancel_quantity_dialog(self):
        self.cancelled += 1
        return True

    def purchase(self, tab, row, dialog, key):
        self.purchases.append((tab, row, dialog, key))
        if self.effect is not None:
            return self.effect
        quantity = dialog.selected_quantity
        return PurchaseEffect(
            status="confirmed", journal_status="confirmed", inner_buy_dispatched=True,
            purchase_transport_calls=1, currency_after=None,
            stock_after=row.stock - quantity, item_quantity_after=None,
            item_identity_after=row.item_identity, currency_identity_after=row.currency_identity,
            tab_successor_verified=True, action_key=key,
            acknowledgements=((row.item_identity, quantity),),
        )

    def switch_to_rare_earth(self):
        self.switched += 1
        return True

    def return_home(self):
        self.home_calls += 1
        return self.home


class ActualSafetyStoreShopPort(ReplayDailyShopsPort):
    """Replay outer navigation while the inner BUY crosses the real policy/store path."""

    def __init__(self, context, *, mismatch_immediate=False):
        super().__init__(incomplete={RUINS_TAB})
        self.context = context
        self.runtime = SimpleNamespace(
            action_keys=set(), taps=[],
            measure_foreground_package=lambda: "com.global.ztmslg",
        )
        self.tap_frame_hashes = []
        self.runtime.tap = lambda source, *args, **kwargs: self._record_tap(source, **kwargs)
        self.last_offer_capture = None
        self.before_bag_capture = None
        self.last_bag_capture = None
        self.mismatch_immediate = mismatch_immediate
        self.dialog_reads = []
        self.capture_count = 0
        self.rare_offer = offer(
            RARE_EARTH_TAB, price=13800, balance=211995, stock=20, owned=4,
        )

    def _record_tap(self, source, **kwargs):
        action_key = kwargs["action_key"]
        self.runtime.action_keys.add(action_key)
        self.runtime.taps.append(action_key)
        self.tap_frame_hashes.append(source.sha256)

    def action_status(self, key):
        row = self.context.action_store.get_action_by_key(key)
        return row.get("final_status") if row else None

    def inspect_tab(self, tab):
        if tab == RUINS_TAB:
            return TabOffer(None, True, "TAB_OFFER_NOT_AVAILABLE")
        return TabOffer(self.rare_offer, True)

    def open_quantity_dialog(self, tab, row):
        return QuantityDialog(
            row.shop_identity, row.item_identity, row.currency_identity,
            row.unit_price, 1, row.unit_price, (430, 700, 560, 770), True,
        )

    def select_quantity(self, tab, row, quantity, dialog):
        return QuantityDialog(
            row.shop_identity, row.item_identity, row.currency_identity,
            row.unit_price, quantity, quantity * row.unit_price, dialog.inner_buy_roi, True,
        )

    def _capture(self, label):
        self.capture_count += 1
        digest = hashlib.sha256(f"{self.capture_count}:{label}".encode()).hexdigest()
        return SimpleNamespace(
            label=label, frame=np.full((1280, 800, 3), 64, dtype=np.uint8),
            sha256=digest, captured_monotonic=float(self.capture_count),
            path=Path("/synthetic") / f"{digest}.png",
        )

    def _dialog(self, captured, current_offer):
        quantity = 14 if (
            self.mismatch_immediate and captured.label.endswith("inner-buy-immediate-before")
        ) else 15
        self.dialog_reads.append((
            captured.label, quantity, quantity * current_offer.unit_price,
            captured.captured_monotonic, captured.sha256,
        ))
        return QuantityDialog(
            current_offer.shop_identity, current_offer.item_identity, current_offer.currency_identity,
            current_offer.unit_price, quantity, quantity * current_offer.unit_price,
            (430, 700, 560, 770), True,
        )

    def _read_offer(self, _captured, _tab):
        return None

    def _page(self, _captured):
        return "UNKNOWN", "unrecognized shop successor"

    def _ocr(self, _captured):
        return []

    def _hits(self, _lines, _text):
        return []

    def _purchase_acknowledgements(self, captured):
        return ()

    def purchase(self, tab, row, dialog, action_key):
        self.purchases.append((tab, row, dialog, action_key))
        return _purchase_daily_offer(
            self.context, self, tab, row, dialog, action_key, settle_seconds=0,
        )



class ActualSafetyStorePairedShopPort(ActualSafetyStoreShopPort):
    """Synthetic per-tab readings crossing the real native policy and journal."""

    def __init__(self, context, *, unaffordable_second=False, missing_acknowledgement=False, unproved_first=False):
        super().__init__(context)
        self.offers = {
            RUINS_TAB: offer(RUINS_TAB, price=15, balance=16649, stock=100, owned=4),
            RARE_EARTH_TAB: offer(RARE_EARTH_TAB, price=13800,
                                  balance=0 if unaffordable_second else 211995, stock=20, owned=4),
        }
        self.observed_after = {
            RUINS_TAB: offer(RUINS_TAB, price=15, balance=16649, stock=0, owned=None),
            RARE_EARTH_TAB: offer(RARE_EARTH_TAB, price=13800, balance=4995, stock=5, owned=19),
        }
        self.current_tab = ""
        self.dispatched_tabs = set()
        self.runtime.reconcile = lambda *args: None
        self.unproved_first = unproved_first
        self.missing_acknowledgement = missing_acknowledgement

    def enter_ruins_shop(self):
        self.entered += 1
        self.current_tab = RUINS_TAB
        return True

    def switch_to_rare_earth(self):
        if self.current_tab != RUINS_TAB:
            raise AssertionError("native purchase left the shared shop before adjacent-tab switch")
        self.switched += 1
        self.current_tab = RARE_EARTH_TAB
        return True

    def return_home(self):
        self.home_calls += 1
        self.current_tab = "home"
        return True

    def inspect_tab(self, tab):
        self.last_offer_capture = self._capture(f"{tab}-offer-source")
        if tab == RUINS_TAB and self.unproved_first:
            return TabOffer(None, False, "EXACT_TAB_OFFER_NOT_AVAILABLE",
                            str(self.last_offer_capture.path), self.last_offer_capture.sha256)
        return TabOffer(self.offers[tab], True, evidence_ref=str(self.last_offer_capture.path),
                        evidence_frame_sha256=self.last_offer_capture.sha256)

    def _dialog(self, captured, current_offer):
        quantity = daily_shop_quantity(current_offer, shop_identity=current_offer.shop_identity)
        return QuantityDialog(
            current_offer.shop_identity, current_offer.item_identity, current_offer.currency_identity,
            current_offer.unit_price, quantity, quantity * current_offer.unit_price,
            (430, 700, 560, 770), True,
        )

    def _record_tap(self, source, **kwargs):
        super()._record_tap(source, **kwargs)
        self.dispatched_tabs.add(self.current_tab)

    def _read_offer(self, captured, tab):
        return self.observed_after[tab] if tab in self.dispatched_tabs else self.offers[tab]

    def _page(self, captured):
        return self.current_tab, ""
    def _purchase_acknowledgements(self, captured):
        if self.missing_acknowledgement or self.current_tab not in self.dispatched_tabs:
            return ()
        row = self.offers[self.current_tab]
        return ((row.item_identity, daily_shop_quantity(row, shop_identity=row.shop_identity)),)



class RetainedPairedShopPort(ActualSafetyStorePairedShopPort):
    """Retain synthetic PNGs so restart consumes the native proof reader too."""

    def __init__(self, context):
        super().__init__(context)
        self.readings = {}
        self.action_keys = dict(KEYS)

    def _capture(self, label):
        import cv2
        self.capture_count += 1
        frame = np.full((1280, 800, 3), 64, dtype=np.uint8)
        frame[0, 0, 0] = self.capture_count
        path = self.context.session.session_directory / f"{self.capture_count:04d}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(path), frame):
            raise AssertionError("cannot retain synthetic frame")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        row = (self.observed_after[self.current_tab] if self.current_tab in self.dispatched_tabs
               else self.offers.get(self.current_tab))
        self.readings[self.capture_count] = self.current_tab, row
        return SimpleNamespace(label=label, sha256=digest, captured_monotonic=float(self.capture_count),
                               frame=frame, path=path)

    def _read_offer(self, captured, tab):
        page, row = self.readings[int(captured.frame[0, 0, 0])]
        return row if page == tab else None

    def _page(self, captured):
        return self.readings[int(captured.frame[0, 0, 0])][0], ""
    def _purchase_acknowledgements(self, captured):
        tab, row = self.readings[int(captured.frame[0, 0, 0])]
        before = self.offers.get(tab)
        if before is None or row is None or row.stock >= before.stock:
            return ()
        return ((before.item_identity,
                 daily_shop_quantity(before, shop_identity=before.shop_identity)),)


    def action_status(self, key):
        return DailyShopsLivePort.action_status(self, key)


def safety_store_purchase_context(directory, store):
    now = 1_700_000_000.0
    owner = "automation-service:daily-shops-replay"
    identity = SchedulerIdentity(
        "resource-account", "resource-server", "game-day-2023-11-14", "daily_shops_purchase",
    )
    store.acquire_lease(owner, now, 3600.0)
    from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID
    return SimpleNamespace(
        identity=identity, owner=owner, action_store=store,
        runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        utc_clock=lambda: now, monotonic_clock=lambda: 10.0,
        session=SimpleNamespace(session_directory=Path(directory) / "native-session"),
        checkpoint=lambda: None, validate_identity=lambda: None,
        is_clean_home=lambda _frame: True,
    )


class DailyShopsNativeReplayTests(unittest.TestCase):
    def test_native_retained_shop_receipts_survive_restart_without_reentry_or_spend(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                context = safety_store_purchase_context(directory, store)
                port = RetainedPairedShopPort(context)
                context.monotonic_clock = lambda: float(port.capture_count) + 0.1
                first = DailyShopsPurchaseRoute(port, action_keys=KEYS).run()
                self.assertEqual(first.status, "completed", first.to_mapping())
                self.assertEqual(port.action_status(KEYS[RUINS_TAB]), "confirmed")
                self.assertEqual(port.action_status(KEYS[RARE_EARTH_TAB]), "confirmed")
                taps = list(port.runtime.taps)
                second = DailyShopsPurchaseRoute(port, action_keys=KEYS).run()
                self.assertEqual(second.status, "already_complete")
                self.assertEqual(port.runtime.taps, taps)
                self.assertTrue(all(row["status"] == "already_confirmed"
                                    for row in second.tab_results.values()))
            finally:
                store.close()

    def test_blocked_ruins_defers_but_independent_rare_earth_confirms_in_same_visit(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                context = safety_store_purchase_context(directory, store)
                port = ActualSafetyStorePairedShopPort(context, unproved_first=True)
                context.monotonic_clock = lambda: float(port.capture_count) + 0.1
                result = DailyShopsPurchaseRoute(port, action_keys=KEYS).run()
                self.assertEqual(result.status, "deferred", result.to_mapping())
                self.assertEqual(result.tab_results[RUINS_TAB]["status"], "blocked")
                self.assertEqual(result.tab_results[RUINS_TAB]["quantity"], 0)
                self.assertEqual(result.tab_results[RARE_EARTH_TAB]["status"], "confirmed")
                self.assertIsNone(store.get_action_by_key(KEYS[RUINS_TAB]))
                self.assertEqual(port.runtime.taps, [KEYS[RARE_EARTH_TAB]])
                self.assertFalse(result.identical_retry_denied)
                self.assertEqual((port.entered, port.switched, port.home_calls), (1, 1, 1))
            finally:
                store.close()

    def test_native_acknowledgements_finish_both_tabs_without_leaving_shared_shop(self):
        for partial in (False, True):
            with self.subTest(unaffordable_second=partial), tempfile.TemporaryDirectory() as directory:
                store = SafetyStore(Path(directory) / "actions.sqlite3")
                try:
                    context = safety_store_purchase_context(directory, store)
                    port = ActualSafetyStorePairedShopPort(context, unaffordable_second=partial)
                    context.monotonic_clock = lambda: float(port.capture_count) + 0.1
                    result = DailyShopsPurchaseRoute(port, action_keys=KEYS).run()
                    self.assertEqual(result.status, "deferred" if partial else "completed", result.to_mapping())
                    self.assertFalse(result.effect_reconciliation_required)
                    self.assertFalse(result.identical_retry_denied)
                    self.assertEqual(port.entered, 1)
                    self.assertEqual(port.switched, 1)
                    self.assertEqual(port.home_calls, 1)
                    self.assertEqual(result.committed_action_count, 1 if partial else 2)
                    self.assertTrue(result.tab_results[RUINS_TAB]["effect_verified"])
                    self.assertEqual(store.get_action_by_key(KEYS[RUINS_TAB])["final_status"], "confirmed")
                    replay = DailyShopsPurchaseRoute(port, action_keys=KEYS).run()
                    self.assertEqual(replay.purchase_transport_calls, 0)
                    self.assertEqual(len(port.runtime.taps), 1 if partial else 2)
                finally:
                    store.close()

    def test_native_missing_acknowledgement_blocks_second_tab_and_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                context = safety_store_purchase_context(directory, store)
                port = ActualSafetyStorePairedShopPort(context, missing_acknowledgement=True)
                context.monotonic_clock = lambda: float(port.capture_count) + 0.1
                result = DailyShopsPurchaseRoute(port, action_keys=KEYS).run()
                self.assertEqual(result.status, "unresolved")
                self.assertTrue(result.identical_retry_denied)
                self.assertEqual(port.switched, 0)
                self.assertEqual(port.runtime.taps, [KEYS[RUINS_TAB]])
                replay = DailyShopsPurchaseRoute(port, action_keys=KEYS).run()
                self.assertEqual(replay.status, "unresolved")
                self.assertEqual(port.runtime.taps, [KEYS[RUINS_TAB]])
            finally:
                store.close()


    def test_uses_live_stock_and_affordability_maximum_for_each_tab(self):
        ruins = offer(RUINS_TAB, price=15, balance=16649, stock=100)
        rare = offer(RARE_EARTH_TAB, price=13800, balance=211995, stock=20)
        port = ReplayDailyShopsPort(offers={RUINS_TAB: ruins, RARE_EARTH_TAB: rare})
        result = DailyShopsPurchaseRoute(port, action_keys=KEYS).run()
        self.assertEqual(result.status, "completed")
        self.assertEqual([entry[2].selected_quantity for entry in port.purchases], [100, 15])
        self.assertEqual([entry[2].total for entry in port.purchases], [1500, 207000])
        self.assertEqual(result.purchase_transport_calls, 2)
        self.assertTrue(all(row["effect_verified"] for row in result.tab_results.values()))
        self.assertTrue(result.terminal_home_verified)
        self.assertTrue(result.accounting_verified)

    def test_tab_is_independent_when_the_other_exact_offer_is_unavailable(self):
        port = ReplayDailyShopsPort(incomplete={RUINS_TAB})
        result = DailyShopsPurchaseRoute(port, action_keys=KEYS).run()
        self.assertEqual(len(port.purchases), 1)
        self.assertEqual(port.purchases[0][0], RARE_EARTH_TAB)
        self.assertEqual(result.tab_results[RUINS_TAB]["status"], "blocked")
        self.assertEqual(result.tab_results[RARE_EARTH_TAB]["status"], "confirmed")
        self.assertEqual(result.status, "deferred")
        self.assertTrue(result.terminal_home_verified)

    def test_sold_out_or_unaffordable_tab_does_not_block_other_tab(self):
        sold_out = offer(RUINS_TAB, stock=0)
        unaffordable = offer(RARE_EARTH_TAB, balance=1)
        port = ReplayDailyShopsPort(offers={RUINS_TAB: sold_out, RARE_EARTH_TAB: offer(RARE_EARTH_TAB)})
        result = DailyShopsPurchaseRoute(port, action_keys=KEYS).run()
        self.assertEqual(len(port.purchases), 1)
        self.assertEqual(result.tab_results[RUINS_TAB]["status"], "deferred")
        self.assertEqual(result.tab_results[RARE_EARTH_TAB]["status"], "confirmed")
        self.assertEqual(daily_shop_quantity(unaffordable, shop_identity=RARE_EARTH_SHOP), 0)

    def test_numeric_dialog_mismatch_cancels_without_inner_buy_on_that_tab(self):
        port = ReplayDailyShopsPort(wrong_quantity=-1)
        result = DailyShopsPurchaseRoute(port, action_keys=KEYS).run()
        self.assertEqual([entry[0] for entry in port.purchases], [RARE_EARTH_TAB])
        self.assertEqual(port.cancelled, 1)
        self.assertEqual(result.purchase_transport_calls, 1)
        self.assertEqual(result.tab_results[RUINS_TAB]["status"], "blocked")
        self.assertEqual(result.tab_results[RARE_EARTH_TAB]["status"], "confirmed")
        self.assertEqual(result.status, "deferred")

    def test_unknown_sent_purchase_is_not_retried_or_followed_by_another_tab(self):
        effect = PurchaseEffect(
            status="unresolved", journal_status="unresolved", inner_buy_dispatched=True,
            purchase_transport_calls=1, currency_after=None, stock_after=None,
            item_quantity_after=None, item_identity_after="", currency_identity_after="",
            tab_successor_verified=False, effect_reconciliation_required=True,
            identical_retry_denied=True, action_key=KEYS[RUINS_TAB], reason="effect unknown",
        )
        port = ReplayDailyShopsPort(effect=effect)
        result = DailyShopsPurchaseRoute(port, action_keys=KEYS).run()
        self.assertEqual(len(port.purchases), 1)
        self.assertEqual(port.purchases[0][0], RUINS_TAB)
        self.assertEqual(result.purchase_transport_calls, 1)
        self.assertEqual(result.status, "unresolved")
        self.assertTrue(result.effect_reconciliation_required)
        self.assertTrue(result.identical_retry_denied)

    def test_real_safety_store_purchase_checks_immediate_numeric_recapture_and_unknown_retry(self):
        for mismatch in (True, False):
            with self.subTest(mismatch_immediate=mismatch), tempfile.TemporaryDirectory() as directory:
                store = SafetyStore(Path(directory) / "safety.sqlite3")
                try:
                    context = safety_store_purchase_context(directory, store)
                    port = ActualSafetyStoreShopPort(context, mismatch_immediate=mismatch)
                    context.monotonic_clock = lambda: float(port.capture_count) + 0.1
                    result = DailyShopsPurchaseRoute(port, action_keys=KEYS).run()
                    self.assertEqual(len(port.purchases), 1)
                    _tab, selected_offer, selected_dialog, action_key = port.purchases[0]
                    self.assertEqual(_tab, RARE_EARTH_TAB)
                    self.assertEqual(selected_dialog.selected_quantity, 15)
                    self.assertEqual(selected_dialog.total, 207000)
                    self.assertEqual(
                        selected_dialog.total,
                        selected_dialog.selected_quantity * selected_offer.unit_price,
                    )
                    immediate = [
                        event for event in port.dialog_reads
                        if event[0].endswith("inner-buy-immediate-before")
                    ]
                    self.assertEqual(len(immediate), 1)
                    policy_reads = [
                        event for event in port.dialog_reads
                        if event[0].endswith("purchase-policy-source")
                    ]
                    self.assertEqual(len(policy_reads), 1)
                    self.assertGreater(immediate[0][3], policy_reads[0][3])
                    self.assertNotEqual(immediate[0][4], policy_reads[0][4])
                    action = store.get_action_by_key(action_key)
                    if mismatch:
                        self.assertEqual(immediate[0][1:3], (14, 193200))
                        self.assertIsNone(action)
                        self.assertEqual(port.runtime.taps, [])
                        self.assertEqual(result.tab_results[RARE_EARTH_TAB]["status"], "blocked")
                        self.assertEqual(result.purchase_transport_calls, 0)
                    else:
                        self.assertIsNotNone(action)
                        self.assertEqual(immediate[0][1:3], (15, 207000))
                        self.assertEqual(port.runtime.taps, [action_key])
                        self.assertEqual(port.tap_frame_hashes, [immediate[0][4]])
                        self.assertEqual(result.status, "unresolved")
                        self.assertEqual(result.purchase_transport_calls, 1)
                        replay = DailyShopsPurchaseRoute(port, action_keys=KEYS).run()
                        self.assertEqual(replay.status, "unresolved")
                        self.assertEqual(len(port.purchases), 1)
                        self.assertEqual(port.runtime.taps, [action_key])
                finally:
                    store.close()

    def test_restart_after_both_confirmed_records_skips_all_spends(self):
        port = ReplayDailyShopsPort(prior={key: "confirmed" for key in KEYS.values()})
        result = DailyShopsPurchaseRoute(port, action_keys=KEYS).run()
        self.assertEqual(port.purchases, [])
        self.assertEqual(result.purchase_transport_calls, 0)
        self.assertEqual(result.committed_action_count, 0)
        self.assertEqual(result.status, "already_complete")
        self.assertTrue(all(row["status"] == "already_confirmed" for row in result.tab_results.values()))

    def test_home_failure_blocks_route_but_retains_confirmed_purchase_effects(self):
        port = ReplayDailyShopsPort(home=False)
        result = DailyShopsPurchaseRoute(port, action_keys=KEYS).run()
        self.assertEqual(result.status, "blocked")
        self.assertFalse(result.terminal_home_verified)
        self.assertTrue(all(row["effect_verified"] for row in result.tab_results.values()))
        self.assertFalse(result.effect_reconciliation_required)



class RuinsOverviewActualPixelTests(unittest.TestCase):
    @requires_tesseract
    def test_actual_overview_binds_exchange_without_claiming_ready_chests(self):
        source = Path(__file__).resolve().parent / "fixtures/daily_shop_entry/ruins-overview-successor.png"
        with tempfile.TemporaryDirectory() as directory:
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                port, runtime = native_daily_shop_entry_port(directory, store, source)
                synthetic_successor = port._ocr

                def current_source_ocr(captured):
                    if runtime.state == "home":
                        return DailyShopsLivePort._ocr(port, captured)
                    return synthetic_successor(captured)

                port._ocr = current_source_ocr
                self.assertTrue(port._tap_text(
                    "Exchange", "daily-shops:ruins-exchange",
                    lambda after: port._page(after)[0] == RUINS_TAB,
                ))
                self.assertEqual(runtime.taps, ["daily-shops:ruins-exchange"])
                self.assertEqual(runtime.input_count, 1)
            finally:
                store.close()

    @requires_tesseract
    def test_missing_exchange_does_not_authorize_overview_navigation(self):
        import cv2
        source = Path(__file__).resolve().parent / "fixtures/daily_shop_entry/ruins-overview-successor.png"
        with tempfile.TemporaryDirectory() as directory:
            frame = cv2.imread(str(source))
            frame[100:175, 190:375] = 0
            masked = Path(directory) / "exchange-not-visible.png"
            self.assertTrue(cv2.imwrite(str(masked), frame))
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                port, runtime = native_daily_shop_entry_port(directory, store, masked)
                port._ocr = lambda captured: DailyShopsLivePort._ocr(port, captured)
                self.assertFalse(port._tap_text(
                    "Exchange", "daily-shops:ruins-exchange", lambda _after: True,
                ))
                self.assertEqual(runtime.taps, [])
                self.assertEqual(runtime.input_count, 0)
            finally:
                store.close()

    @requires_tesseract
    def test_owned_overview_returns_home_but_unknown_context_sends_no_back(self):
        root = Path(__file__).resolve().parents[1]
        source = root / "tests/fixtures/daily_shop_entry/ruins-overview-successor.png"
        home = root / "tasks/assets/home_atlas/bluestacks/800x1280/tiles/viewport-001.png"
        for recognized in (True, False):
            with self.subTest(recognized=recognized), tempfile.TemporaryDirectory() as directory:
                store = SafetyStore(Path(directory) / "actions.sqlite3")
                try:
                    port, runtime = native_daily_shop_entry_port(
                        directory, store, source, home_source=home,
                    )
                    if not recognized:
                        runtime.state = "unknown"
                    self.assertEqual(port.return_home(), recognized)
                    self.assertEqual(len(runtime.backs), int(recognized))
                    self.assertEqual(runtime.input_count, int(recognized))
                    self.assertEqual(runtime.taps, [])
                finally:
                    store.close()


class DailyShopActualSelectorTests(unittest.TestCase):
    SOURCE = Path(__file__).resolve().parent / "fixtures/daily_shop_entry/ruins-shop-successor.png"

    @requires_tesseract
    def test_actual_selected_shop_is_independent_of_item_description_ocr(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                port, runtime = native_daily_shop_entry_port(directory, store, self.SOURCE)
                captured = runtime.capture("actual-shop")
                self.assertEqual(port._page(captured)[0], RUINS_TAB)
                self.assertEqual(runtime.input_count, 0)
            finally:
                store.close()

    @requires_tesseract
    def test_missing_current_selection_never_authorizes_back(self):
        import cv2
        with tempfile.TemporaryDirectory() as directory:
            frame = cv2.imread(str(self.SOURCE))
            frame[210:230, 190:250] = 0
            source = Path(directory) / "missing-selected-marker.png"
            self.assertTrue(cv2.imwrite(str(source), frame))
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                port, runtime = native_daily_shop_entry_port(directory, store, source)
                self.assertEqual(port._page(runtime.capture("ambiguous-shop"))[0], "unknown")
                self.assertFalse(port.return_home())
                self.assertEqual(runtime.backs, [])
                self.assertEqual(runtime.input_count, 0)
            finally:
                store.close()

    @requires_tesseract
    def test_clipped_neighbor_has_one_bounded_reveal_and_no_guessed_tap(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                port, runtime = native_daily_shop_entry_port(directory, store, self.SOURCE)
                port.current_tab = RUINS_TAB
                self.assertFalse(port.switch_to_rare_earth())
                self.assertFalse(port.switch_to_rare_earth())
                self.assertEqual(len(runtime.swipes), 1)
                self.assertEqual(runtime.taps, [])
                self.assertEqual(runtime.input_count, 1)
            finally:
                store.close()


GOLD_SELECTOR_RUN = Path(__file__).resolve().parent / "fixtures/daily_shop_entry/gold-selector-run"
RUN_RUINS_OFFER = GOLD_SELECTOR_RUN / "0017-daily-shops-ruins-offer-source.png"
RUN_REVEAL_SOURCE = GOLD_SELECTOR_RUN / "0019-daily-shops-selector-reveal-source.png"
RUN_REVEALED = GOLD_SELECTOR_RUN / "0021-daily-shops-Rare-Earth-Shop-source.png"


class SelectorRunTransport:
    """Actual #72 selector pixels; no Rare Earth successor was ever observed, so taps change nothing."""

    def __init__(self, start, revealed):
        self.state, self.revealed, self.inputs = start, revealed, []

    def capture_png(self):
        return self.state.read_bytes()

    def dispatch_swipe(self, start, end, *_duration):
        self.inputs.append(("swipe", start, end))
        self.state = self.revealed

    def dispatch_tap(self, point):
        self.inputs.append(("tap", point))


class DailyShopGoldSelectorRunTests(unittest.TestCase):
    @requires_tesseract
    def test_actual_0017_offer_without_owned_retains_exact_purchase_quantity(self):
        from scripts.bluestacks_native_runtime import captured_native_frame_from_png
        captured = captured_native_frame_from_png(
            RUN_RUINS_OFFER.read_bytes(), captured_monotonic=1, path=RUN_RUINS_OFFER,
        )
        port = object.__new__(DailyShopsLivePort)
        port.currency_icons = {}
        port.context = SimpleNamespace(is_clean_home=lambda _frame: False)
        port._capture = lambda _label: captured
        readiness = port.inspect_tab(RUINS_TAB)
        self.assertTrue(readiness.complete, readiness)
        self.assertIsNotNone(readiness.offer)
        row = readiness.offer
        self.assertEqual((row.item_identity, row.unit_price, row.balance, row.stock),
                         (RUINS_CHIP_ITEM, 15, 16649, 100))
        self.assertIsNone(row.item_quantity)
        self.assertEqual(daily_shop_quantity(row, shop_identity=RUINS_SHOP), 100)

    def switch_twice(self, directory, start, revealed):
        from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
        from scripts.startup_normalization import is_clean_home_frame
        transport = SelectorRunTransport(start, revealed)
        runtime = LocalBlueStacksRuntime(transport, Path(directory) / "native", execute=True)
        context = SimpleNamespace(
            runtime=runtime, checkpoint=lambda: None, is_clean_home=is_clean_home_frame,
            session=SimpleNamespace(observe=lambda capture, *, label: capture(label)),
        )
        port = DailyShopsLivePort(context, action_keys=KEYS, settle_seconds=0)
        port.current_tab = RUINS_TAB
        return (port.switch_to_rare_earth(), port.switch_to_rare_earth()), transport, runtime, port

    @requires_tesseract
    def test_revealed_selector_keeps_shop_header_and_exposes_exact_unselected_label(self):
        from scripts.bluestacks_native_runtime import captured_native_frame_from_png
        port = object.__new__(DailyShopsLivePort)
        port.context = SimpleNamespace(is_clean_home=lambda _frame: False)
        for path, label in ((RUN_REVEAL_SOURCE, []), (RUN_REVEALED, [(270, 180, 407, 215)])):
            with self.subTest(frame=path.name):
                captured = captured_native_frame_from_png(path.read_bytes(), captured_monotonic=1, path=path)
                self.assertTrue(port._hits(port._ocr_region(
                    captured.frame, (285, 0, 515, 65), psm=7, light_text=True,
                ), "Shop"))
                page, lines = port._page(captured)
                self.assertEqual(page, RUINS_TAB)
                self.assertEqual(port._selector_labels(lines, "Rare Earth Shop"), label)
                for roi in label:
                    self.assertFalse(port._shop_selected(captured.frame, roi))

    @requires_tesseract
    def test_actual_reveal_binds_one_exact_label_tap_and_unverified_successor_never_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            results, transport, runtime, port = self.switch_twice(directory, RUN_REVEAL_SOURCE, RUN_REVEALED)
            self.assertEqual(results, (False, False))
            self.assertEqual(transport.inputs, [("swipe", (220, 145), (500, 145)), ("tap", (338, 197))])
            self.assertEqual(runtime.input_count, 2)
            self.assertEqual(port.current_tab, RUINS_TAB)

    @requires_tesseract
    def test_no_progress_reveal_sends_no_tap_and_no_second_reveal(self):
        with tempfile.TemporaryDirectory() as directory:
            results, transport, runtime, _port = self.switch_twice(directory, RUN_REVEAL_SOURCE, RUN_REVEAL_SOURCE)
            self.assertEqual(results, (False, False))
            self.assertEqual(transport.inputs, [("swipe", (220, 145), (500, 145))])
            self.assertEqual(runtime.input_count, 1)


class NativeDailyShopEntryRuntime:
    """Retained Home pixels, fake transport; successor text is synthetic, not acceptance."""

    execute = True
    in_flight_action = None

    def __init__(self, directory, source, *, pan_successor="unchanged", zoom_successor=None, home_source=None):
        self.session = Path(directory)
        self.runner = SimpleNamespace(executable="offline-replay", serial="offline")
        self.source = source
        self.pan_successor = pan_successor
        self.zoom_successor = zoom_successor
        self.home_source = home_source
        self.backs = []
        self.zooms = []
        self.input_count = 0
        self.ordinal = 0
        self.now = 100.0
        self.state = "home"
        self.taps = []
        self.swipes = []

    def capture(self, label):
        import cv2
        import time
        from scripts.bluestacks_native_runtime import CapturedNativeFrame
        self.ordinal += 1
        self.now = time.monotonic()
        if self.state == "home":
            frame = cv2.imread(str(self.source))
        else:
            marker = {"unknown": 0, "overview": 31, "shop": 63}[self.state]
            frame = np.full((1280, 800, 3), marker, dtype=np.uint8)
        # Deliberately encode a different PNG representation than frame_digest.
        ok, encoded = cv2.imencode(".png", frame, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        assert ok
        png = encoded.tobytes()
        path = self.session / f"{self.ordinal:04d}-{label}.png"
        path.write_bytes(png)
        return CapturedNativeFrame(frame, png, hashlib.sha256(png).hexdigest(), self.now, path)

    def tap(self, captured, **target):
        self.input_count += 1
        self.taps.append(target["target_identity"])
        self.state = {
            "home.building.ruins": "overview",
            "daily-shops:ruins-exchange": "shop",
        }[target["target_identity"]]

    def swipe(self, captured, **gesture):
        self.input_count += 1
        self.swipes.append(gesture)
        if self.pan_successor == "unknown":
            self.state = "unknown"

    def dispatch_external_zoom(self, captured, *, action_key, transport):
        self.input_count += 1
        self.zooms.append((captured, action_key))
        if self.zoom_successor == "unknown":
            self.state = "unknown"
        elif self.zoom_successor is not None:
            self.source = self.zoom_successor

    def back(self, captured, *, action_key):
        self.input_count += 1
        self.backs.append(action_key)
        if self.home_source is None:
            self.state = "unknown"
        else:
            self.state = "home"
            self.source = self.home_source

    def clock(self):
        return self.now + 0.01

    def measure_device_state(self):
        return "device"

    def measure_foreground_package(self):
        return "com.global.ztmslg"


class NativeDailyShopEntrySession:
    owner = "daily-shop-replay"
    invocation_id = "daily-shop-entry-replay"

    def observe(self, capture, *, label):
        return capture(label)

    def run_action(self, **action):
        before = action["capture"]("entry-before")
        action["authorize"](before)
        action["dispatch"](before)
        after = action["settled_successor"]()
        state = action["recognize"](after)
        return SimpleNamespace(
            status="completed" if state != "unknown" else "unresolved", state=state,
        )


def native_daily_shop_entry_port(directory, store, source, *, lease_held=True, **runtime_options):
    from scripts.startup_normalization import is_clean_home_frame
    if lease_held:
        store.acquire_lease(NativeDailyShopEntrySession.owner, 1000.0, 3600.0)
    runtime = NativeDailyShopEntryRuntime(directory, source, **runtime_options)
    context = SimpleNamespace(
        runtime=runtime, session=NativeDailyShopEntrySession(), action_store=store,
        occurrence_key="daily-shop-entry-reset", monotonic_clock=runtime.clock,
        utc_clock=lambda: 1000.0, checkpoint=lambda: None, settle_seconds=0.0,
        is_clean_home=is_clean_home_frame,
        max_inputs=48,
    )
    port = DailyShopsLivePort(context, action_keys=KEYS, settle_seconds=0)
    # Only the route-owned successor OCR is synthetic. Home pixels, clean-Home
    # recognition, localization, binding, planning and pan authority remain real.
    def successor_ocr(captured):
        marker = int(captured.frame[0, 0, 0])
        phrases = {
            31: ("Ruins Challenge", "Exchange"),
            63: ("3★ Chip Enhance Material",),
        }.get(marker, ())
        return tuple(
            tuple((word, (160 + i * 110, 300 + row * 100,
                           260 + i * 110, 340 + row * 100))
                  for i, word in enumerate(phrase.split()))
            for row, phrase in enumerate(phrases)
        )
    port._ocr = successor_ocr
    return port, runtime


class DailyShopMappedEntryTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]
    TILES = ROOT / "tasks/assets/home_atlas/bluestacks/800x1280/tiles"

    def setUp(self):
        self.enterContext(patch(
            "scripts.atlas_runtime_startup.ScrcpyMotionEventZoomTransport",
            return_value=SimpleNamespace(
                zoom_out_once=lambda: self.fail("offline runtime attempted physical zoom transport"),
            ),
        ))

    def test_native_visible_binding_uses_semantic_not_transport_digest_and_exchange(self):
        from tasks.home_atlas_vision import frame_digest
        with tempfile.TemporaryDirectory() as directory:
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                port, runtime = native_daily_shop_entry_port(
                    directory, store, self.TILES / "viewport-001.png",
                )
                source = runtime.capture("digest-proof")
                self.assertNotEqual(source.sha256, frame_digest(source.frame))
                self.assertIsNotNone(port._mapped_ruins(source.frame))
                self.assertTrue(port.enter_ruins_shop())
                self.assertEqual(runtime.taps, [
                    "home.building.ruins", "daily-shops:ruins-exchange",
                ])
                self.assertEqual(runtime.swipes, [])
                self.assertEqual(port.current_tab, RUINS_TAB)
            finally:
                store.close()

    def test_unverified_overview_or_exchange_never_advances_to_shop(self):
        for denied_target in ("home.building.ruins", "daily-shops:ruins-exchange"):
            with self.subTest(target=denied_target), tempfile.TemporaryDirectory() as directory:
                store = SafetyStore(Path(directory) / "actions.sqlite3")
                try:
                    port, runtime = native_daily_shop_entry_port(
                        directory, store, self.TILES / "viewport-001.png",
                    )
                    tap = runtime.tap
                    def unknown_successor(captured, **target):
                        tap(captured, **target)
                        if target["target_identity"] == denied_target:
                            runtime.state = "unknown"
                    runtime.tap = unknown_successor
                    self.assertFalse(port.enter_ruins_shop())
                    expected = (["home.building.ruins"] if denied_target == "home.building.ruins"
                                else ["home.building.ruins", "daily-shops:ruins-exchange"])
                    self.assertEqual(runtime.taps, expected)
                    self.assertEqual(port.current_tab, "")
                finally:
                    store.close()

    def test_actual_zoomed_source_unchanged_stops_after_one_sdk_zoom(self):
        source = self.ROOT / "tests/fixtures/daily_shop_entry/canonical-home-source.png"
        with tempfile.TemporaryDirectory() as directory:
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                port, runtime = native_daily_shop_entry_port(directory, store, source)
                self.assertFalse(port.enter_ruins_shop())
                self.assertEqual(len(runtime.zooms), 1)
                self.assertEqual((runtime.taps, runtime.swipes), ([], []))
            finally:
                store.close()

    def test_actual_source_sdk_zoom_then_native_binding_and_exchange(self):
        source = self.ROOT / "tests/fixtures/daily_shop_entry/canonical-home-source.png"
        with tempfile.TemporaryDirectory() as directory:
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                port, runtime = native_daily_shop_entry_port(
                    directory, store, source,
                    zoom_successor=self.TILES / "viewport-001.png",
                )
                self.assertTrue(port.enter_ruins_shop())
                self.assertEqual(len(runtime.zooms), 1)
                self.assertEqual(runtime.input_count, 3)
                self.assertEqual(runtime.taps, [
                    "home.building.ruins", "daily-shops:ruins-exchange",
                ])
                self.assertEqual(runtime.swipes, [])
            finally:
                store.close()

    def test_actual_source_unknown_zoom_successor_or_budget_cannot_open_ruins(self):
        source = self.ROOT / "tests/fixtures/daily_shop_entry/canonical-home-source.png"
        for budget_exhausted in (False, True):
            with self.subTest(budget_exhausted=budget_exhausted), tempfile.TemporaryDirectory() as directory:
                store = SafetyStore(Path(directory) / "actions.sqlite3")
                try:
                    port, runtime = native_daily_shop_entry_port(
                        directory, store, source, zoom_successor="unknown",
                    )
                    if budget_exhausted:
                        runtime.input_count = 48
                    self.assertFalse(port.enter_ruins_shop())
                    self.assertEqual(len(runtime.zooms), 0 if budget_exhausted else 1)
                    self.assertEqual((runtime.taps, runtime.swipes), ([], []))
                finally:
                    store.close()

    def test_supported_zoom_recovery_is_capped_at_two_accounted_inputs(self):
        import cv2
        source = self.ROOT / "tests/fixtures/daily_shop_entry/canonical-home-source.png"
        with tempfile.TemporaryDirectory() as directory:
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                port, runtime = native_daily_shop_entry_port(directory, store, source)
                native_zoom = runtime.dispatch_external_zoom
                def changed_but_still_zoomed(captured, *, action_key, transport):
                    native_zoom(captured, action_key=action_key, transport=transport)
                    # Explicit synthetic HUD-only mutation avoids repeated-image
                    # rejection while retaining the actual source's zoom geometry.
                    frame = captured.frame.copy()
                    frame[0, len(runtime.zooms)] ^= np.uint8(1)
                    mutated = Path(directory) / f"synthetic-still-zoomed-{len(runtime.zooms)}.png"
                    self.assertTrue(cv2.imwrite(str(mutated), frame))
                    runtime.source = mutated
                runtime.dispatch_external_zoom = changed_but_still_zoomed
                self.assertFalse(port.enter_ruins_shop())
                self.assertEqual(len(runtime.zooms), 2)
                self.assertEqual(runtime.input_count, 2)
                self.assertEqual((runtime.taps, runtime.swipes), ([], []))
            finally:
                store.close()

    def test_pan_unchanged_or_unknown_never_opens_ruins_or_retries(self):
        from tests.support.environment import requires_tesseract
        # Native pan capability verification uses the production OCR family probe.
        @requires_tesseract
        def exercise():
            for successor in ("unchanged", "unknown"):
                with self.subTest(successor=successor), tempfile.TemporaryDirectory() as directory:
                    store = SafetyStore(Path(directory) / "actions.sqlite3")
                    try:
                        port, runtime = native_daily_shop_entry_port(
                            directory, store, self.TILES / "viewport-010.png",
                            pan_successor=successor,
                        )
                        self.assertFalse(port.enter_ruins_shop())
                        self.assertEqual(len(runtime.swipes), 1)
                        self.assertEqual(runtime.taps, [])
                        self.assertIn("mapped_home_atlas_pan_not_verified", port.entry_reason)
                        # Same occurrence must not resend its unresolved pan after restart.
                        restarted, _unused = native_daily_shop_entry_port(
                            directory, store, self.TILES / "viewport-010.png",
                            pan_successor=successor,
                        )
                        restarted.runtime = runtime
                        restarted.context.runtime = runtime
                        self.assertFalse(restarted.enter_ruins_shop())
                        self.assertEqual(len(runtime.swipes), 1)
                    finally:
                        store.close()
        exercise()

    def test_pan_without_owned_lease_dispatches_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                port, runtime = native_daily_shop_entry_port(
                    directory, store, self.TILES / "viewport-010.png", lease_held=False,
                )
                self.assertFalse(port.enter_ruins_shop())
                self.assertEqual((runtime.taps, runtime.swipes, runtime.zooms), ([], [], []))
                self.assertIn("mapped_home_atlas_pan_not_verified", port.entry_reason)
            finally:
                store.close()

    def test_real_navigator_rejects_unchanged_and_unknown_native_successors(self):
        import cv2
        from scripts.home_atlas_bluestacks import bluestacks_direct_pan_contract
        from tasks.home_atlas_planner import DirectPanNavigator, PlanDisposition
        with tempfile.TemporaryDirectory() as directory:
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                port, runtime = native_daily_shop_entry_port(
                    directory, store, self.TILES / "viewport-010.png",
                )
                atlas, localizer = port._home_mapping()
                initial = localizer.localize(runtime.capture("planning").frame)
                safe, calibration = bluestacks_direct_pan_contract()
                for successor in (cv2.imread(str(runtime.source)),
                                  np.zeros((1280, 800, 3), dtype=np.uint8)):
                    navigator = DirectPanNavigator(
                        atlas, "home.building.ruins", safe, calibration, maximum_pans=1,
                    )
                    plan = navigator.plan(initial)
                    self.assertIs(plan.disposition, PlanDisposition.PAN)
                    runtime.swipe(
                        runtime.capture("fake-transport-source"),
                        start=plan.drag_start, end=plan.drag_end,
                    )
                    progress = navigator.record_progress(initial, localizer.localize(successor))
                    self.assertFalse(progress.accepted)
                    self.assertIsNone(port._mapped_ruins(successor))
                    self.assertEqual(runtime.taps, [])
            finally:
                store.close()

    def test_checkpoint_budget_denial_dispatches_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                port, runtime = native_daily_shop_entry_port(
                    directory, store, self.TILES / "viewport-010.png",
                )
                checkpoints = []
                def exhausted():
                    checkpoints.append(True)
                    if len(checkpoints) > 1:
                        raise RuntimeError("invocation input budget exhausted")
                port.context.checkpoint = exhausted
                self.assertFalse(port.enter_ruins_shop())
                self.assertEqual((runtime.taps, runtime.swipes), ([], []))
            finally:
                store.close()

if __name__ == "__main__":
    unittest.main()
