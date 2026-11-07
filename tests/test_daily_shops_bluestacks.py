from __future__ import annotations
import hashlib
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
import numpy as np

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
            purchase_transport_calls=1, currency_after=row.balance - quantity * row.unit_price,
            stock_after=row.stock - quantity, item_quantity_after=row.item_quantity + quantity,
            item_identity_after=row.item_identity, currency_identity_after=row.currency_identity,
            tab_successor_verified=True, action_key=key,
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

    def purchase(self, tab, row, dialog, action_key):
        self.purchases.append((tab, row, dialog, action_key))
        return _purchase_daily_offer(
            self.context, self, tab, row, dialog, action_key, settle_seconds=0,
        )



class ActualSafetyStorePairedShopPort(ActualSafetyStoreShopPort):
    """Synthetic per-tab readings crossing the real native policy and journal."""

    def __init__(self, context, *, unaffordable_second=False, missing_ruins_item=False, unproved_first=False):
        super().__init__(context)
        self.offers = {
            RUINS_TAB: offer(RUINS_TAB, price=15, balance=16649, stock=100, owned=4),
            RARE_EARTH_TAB: offer(RARE_EARTH_TAB, price=13800,
                                  balance=0 if unaffordable_second else 211995, stock=20, owned=4),
        }
        self.observed_after = {
            RUINS_TAB: offer(RUINS_TAB, price=15, balance=15149, stock=0,
                            owned=4 if missing_ruins_item else 104),
            RARE_EARTH_TAB: offer(RARE_EARTH_TAB, price=13800, balance=4995, stock=5, owned=19),
        }
        self.current_tab = ""
        self.dispatched_tabs = set()
        self.runtime.reconcile = lambda *args: None
        self.unproved_first = unproved_first

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
            return TabOffer(None, True, "TAB_ITEM_EFFECT_EVIDENCE_REQUIRED",
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

    def test_unproved_ruins_defers_before_buy_but_independent_rare_earth_confirms_in_same_visit(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                context = safety_store_purchase_context(directory, store)
                port = ActualSafetyStorePairedShopPort(context, unproved_first=True)
                context.monotonic_clock = lambda: float(port.capture_count) + 0.1
                result = DailyShopsPurchaseRoute(port, action_keys=KEYS).run()
                self.assertEqual(result.status, "deferred", result.to_mapping())
                self.assertEqual(result.tab_results[RUINS_TAB]["reason"], "TAB_ITEM_EFFECT_EVIDENCE_REQUIRED")
                self.assertEqual(result.tab_results[RUINS_TAB]["status"], "deferred")
                self.assertEqual(result.tab_results[RARE_EARTH_TAB]["status"], "confirmed")
                self.assertIsNone(store.get_action_by_key(KEYS[RUINS_TAB]))
                self.assertEqual(port.runtime.taps, [KEYS[RARE_EARTH_TAB]])
                self.assertFalse(result.identical_retry_denied)
                self.assertEqual((port.entered, port.switched, port.home_calls), (1, 1, 1))
            finally:
                store.close()

    def test_real_native_paired_effects_finish_both_tabs_without_leaving_shared_shop(self):
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

    def test_real_native_currency_and_stock_without_owned_delta_blocks_second_tab_and_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                context = safety_store_purchase_context(directory, store)
                port = ActualSafetyStorePairedShopPort(context, missing_ruins_item=True)
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
    def test_native_ruins_missing_owned_is_evidence_required_not_inferred_from_bag_or_spend(self):
        frame = np.full((1280, 800, 3), 32, dtype=np.uint8)
        frame[50:80, 250:280] = (0, 180, 220)
        frame[400:430, 250:280] = (0, 180, 220)
        captured = SimpleNamespace(frame=frame, path=Path("/synthetic/ruins.png"), sha256="a" * 64)
        lines = [
            [("16,649", (300, 50, 405, 80))],
            [("3★", (100, 330, 150, 360)), ("Chip", (160, 330, 230, 360)),
             ("Enhance", (240, 330, 330, 360)), ("Material", (340, 330, 430, 360))],
            [("Buy", (450, 400, 520, 430)), ("15", (300, 400, 350, 430))],
            [("Stock", (100, 450, 180, 480)), ("100", (200, 450, 260, 480))],
        ]
        port = object.__new__(DailyShopsLivePort)
        port._ocr = lambda _captured: lines
        port.currency_icons = {}
        self.assertIsNone(port._read_offer(captured, RUINS_TAB))
        port._capture = lambda _label: captured
        readiness = port.inspect_tab(RUINS_TAB)
        self.assertTrue(readiness.complete)
        self.assertIsNone(readiness.offer)
        self.assertEqual(readiness.reason, "TAB_ITEM_EFFECT_EVIDENCE_REQUIRED")
        self.assertEqual(readiness.evidence_frame_sha256, captured.sha256)
        lines.append([("Owned", (100, 380, 180, 410)), ("4", (200, 380, 230, 410))])
        observed = port._read_offer(captured, RUINS_TAB)
        self.assertIsNotNone(observed)
        self.assertEqual(observed.item_quantity, 4)
        self.assertEqual(observed.balance, 16649)


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

    def test_home_failure_never_reports_confirmed_effects(self):
        port = ReplayDailyShopsPort(home=False)
        result = DailyShopsPurchaseRoute(port, action_keys=KEYS).run()
        self.assertEqual(result.status, "blocked")
        self.assertFalse(result.terminal_home_verified)
        self.assertTrue(result.effect_reconciliation_required)

    def test_total_balance_fraction_is_not_quantity_and_balance_must_still_match(self):
        # Synthetic OCR/image input, not retained native acceptance evidence.
        frame = np.full((1280, 800, 3), 32, dtype=np.uint8)
        frame[850:880, 250:280] = (0, 180, 220)
        captured = SimpleNamespace(frame=frame)
        lines = [
            [("3★", (100, 300, 150, 330)), ("Module", (160, 300, 240, 330)),
             ("Enhance", (250, 300, 340, 330)), ("Material", (350, 300, 440, 330))],
            [("15/15", (350, 700, 460, 740))],
            [("Total", (160, 850, 230, 880)), ("207,000", (300, 850, 405, 880)),
             ("/", (410, 850, 420, 880)), ("211,995", (425, 850, 530, 880))],
            [("Buy", (300, 1000, 500, 1050))],
        ]
        port = object.__new__(DailyShopsLivePort)
        port._ocr = lambda _captured: lines
        port.currency_icons = {
            RARE_EARTH_TAB: port._icon(captured, (300, 850, 405, 880))
        }
        current_offer = offer(RARE_EARTH_TAB)
        dialog = port._dialog(captured, current_offer)
        self.assertIsNotNone(dialog)
        self.assertEqual(dialog.selected_quantity, 15)
        self.assertEqual(dialog.total, 207000)
        lines[2][-1] = ("211,996", (425, 850, 530, 880))
        self.assertIsNone(port._dialog(captured, current_offer))


if __name__ == "__main__":
    unittest.main()
