from __future__ import annotations

import unittest
from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from safe_action_core import SafetyStore
from scripts import alliance_shop_bluestacks as native
from tests.test_daily_shops_bluestacks import safety_store_purchase_context

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


class ActualSafetyStoreAlliancePort(ReplayAllianceShopPort):
    """Synthetic observed shop frames; policy, capabilities and SQLite are real."""

    def __init__(self, context, *, fallback=False, missing_item_effect=False, changed_immediate=False):
        selected = (offer(ALLIANCE_OTHER_SHOP, ALLIANCE_FALLBACK_ITEM, price=9, rarity=1)
                    if fallback else offer(ALLIANCE_WEEKLY_SHOP, "Bioenhance Scheme"))
        super().__init__(weekly=() if fallback else (selected,), fallback=selected if fallback else None)
        self.context = context
        self.selected = selected
        self.current_tab = "other" if fallback else "weekly"
        self.missing_item_effect = missing_item_effect
        self.capture_count = 0
        self.dialog_reads = []
        self.tap_frame_hashes = []
        self.changed_immediate = changed_immediate
        context.runtime = SimpleNamespace(action_keys=set(), taps=[],
                                         measure_foreground_package=lambda: "com.global.ztmslg")
        self.runtime = context.runtime
        self.runtime.tap = self._tap
        self.runtime.reconcile = lambda *args: None
        context.monotonic_clock = lambda: float(self.capture_count) + 0.1
        context.validate_identity = lambda: None
        self.offer_evidence = {selected.item_identity: self._capture("offer-source")}

    def _capture(self, label):
        self.capture_count += 1
        digest = hashlib.sha256(f"{self.capture_count}:{label}".encode()).hexdigest()
        return SimpleNamespace(label=label, sha256=digest, captured_monotonic=float(self.capture_count),
                               frame=np.full((1280, 800, 3), 64, dtype=np.uint8),
                               path=Path("/synthetic") / f"{digest}.png")

    def _tap(self, source, **kwargs):
        self.runtime.action_keys.add(kwargs["action_key"])
        self.runtime.taps.append(kwargs["action_key"])
        self.tap_frame_hashes.append(source.sha256)

    def action_status(self, key):
        row = self.context.action_store.get_action_by_key(key)
        return row["final_status"] if row else None

    def _quantity_dialog(self, captured, selected):
        dialog = self.open_quantity_dialog(selected)
        if self.changed_immediate and captured.label.endswith("inner-buy-immediate-before"):
            dialog = replace(dialog, selected_quantity=2, total=2 * selected.unit_price)
        self.dialog_reads.append((captured, dialog))
        return dialog

    def _page(self, captured):
        return self.current_tab, ""

    def _read_offer(self, captured, *args):
        return replace(self.selected, balance=self.selected.balance - self.selected.unit_price,
                       stock=self.selected.stock - 1,
                       item_quantity=self.selected.item_quantity + (0 if self.missing_item_effect else 1))

    def _words(self, captured):
        return ()

    def _home(self, captured):
        return True

    def purchase_one(self, selected, dialog, key):
        self.purchases.append((selected, key))
        with patch.object(native, "_hits", return_value=[(100, 300, 400, 350)]):
            return native._purchase_alliance_offer(
                self.context, self, selected, dialog, key, settle_seconds=0,
            )


ENTRY_FIXTURES = Path(__file__).parent / "fixtures" / "alliance_shop_menu"


class MenuPixelTransport:
    """Immutable native pixels; no device, network, or synthetic Shop successor."""

    def __init__(self, *, shop_pixels=False):
        self.state = "immediate-home.png"
        self.inputs = []
        self.shop_pixels = shop_pixels
        self.other_verified = False

    def capture_png(self):
        return (ENTRY_FIXTURES / self.state).read_bytes()

    def dispatch_tap(self, point):
        self.inputs.append(("tap", point))
        if self.state == "immediate-home.png":
            self.state = "alliance-menu.png"
        elif self.shop_pixels:
            self.state = {
                "alliance-menu.png": "weekly-top.png",
                "weekly-top.png": "standard-shop.png",
                "standard-shop.png": "other.png",
            }.get(self.state, self.state)

    def dispatch_back(self):
        self.inputs.append(("back", None))
        self.state = ("alliance-menu.png" if self.state in {
            "weekly-top.png", "standard-shop.png", "other.png",
        } else "immediate-home.png")


def native_menu_entry_smoke(directory, *, shop_pixels=False):
    from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
    transport = MenuPixelTransport(shop_pixels=shop_pixels)
    runtime = LocalBlueStacksRuntime(transport, Path(directory) / "native-entry", execute=True)
    context = SimpleNamespace(
        runtime=runtime,
        session=SimpleNamespace(observe=lambda capture, *, label: capture(label)),
        checkpoint=lambda: None,
        identity=SimpleNamespace(reset_id="pixel-replay-reset"),
    )
    port = native.AllianceShopLivePort(context, settle_seconds=0)
    entered_weekly = port.enter_weekly_offers()
    if entered_weekly and shop_pixels:
        transport.other_verified = port.enter_other_offers()
    returned_home = port.return_home()
    return entered_weekly, returned_home, runtime, transport


class AllianceShopEntryPixelTests(unittest.TestCase):
    def captured(self, name):
        from scripts.bluestacks_native_runtime import captured_native_frame_from_png
        path = ENTRY_FIXTURES / name
        return captured_native_frame_from_png(path.read_bytes(), captured_monotonic=1, path=path)

    def port(self):
        context = SimpleNamespace(
            session=None, runtime=None, checkpoint=lambda: None,
            identity=SimpleNamespace(reset_id="pixel-replay-reset"),
        )
        return native.AllianceShopLivePort(context, settle_seconds=0)

    def test_actual_failure_frame_loses_fullframe_ocr_but_binds_native_footer(self):
        from scripts.alliance_donation_bluestacks import _home_alliance_target
        canonical = self.captured("canonical-home.png")
        immediate = self.captured("immediate-home.png")
        self.assertEqual(len(native._hits(native._ocr_words(canonical), "Alliance")), 1)
        self.assertEqual(native._hits(native._ocr_words(immediate), "Alliance"), [])
        for frame in (canonical, immediate):
            self.assertEqual(_home_alliance_target(frame)[0], "home-nav:alliance")
            self.assertEqual(self.port()._page(frame)[0], "home")

    def test_actual_menu_shop_footer_is_not_current_shop_title(self):
        frame = self.captured("alliance-menu.png")
        self.assertEqual(self.port()._page(frame)[0], "alliance_menu")
        hits = native._hits(native._ocr_words(frame, (40, 1180, 760, 1280)), "Alliance Shop")
        self.assertEqual(len(hits), 1)
        self.assertGreaterEqual(hits[0][1], 1180)

    def test_actual_selected_tabs_not_incidental_navigation_labels(self):
        port = self.port()
        for name, page in (("weekly-top.png", "weekly"), ("weekly-lower.png", "weekly"),
                           ("standard-shop.png", "alliance"), ("other.png", "other")):
            with self.subTest(name=name):
                captured = self.captured(name)
                self.assertEqual(port._page(captured)[0], page)
                if page != "weekly":
                    self.assertTrue(native._hits(
                        native._ocr_words(captured, (40, 85, 281, 155), psm=7), "Weekly Offers",
                    ))
                    self.assertFalse(native._selected_tab(captured, "Weekly Offers", (40, 85, 281, 155)))

    def test_actual_native_runtime_weekly_to_other_entry_and_safe_home(self):
        with tempfile.TemporaryDirectory() as directory:
            weekly, home, runtime, transport = native_menu_entry_smoke(directory, shop_pixels=True)
            self.assertTrue(weekly)
            self.assertTrue(transport.other_verified)
            self.assertTrue(home)
            self.assertEqual(runtime.input_count, 6)
            self.assertEqual(transport.inputs[-1], ("back", None))
            self.assertFalse(any("buy" in key for key in runtime.action_keys))

    def test_real_runtime_entry_binds_fresh_footer_and_menu_then_safe_back(self):
        with tempfile.TemporaryDirectory() as directory:
            weekly, home, runtime, transport = native_menu_entry_smoke(directory)
            self.assertFalse(weekly)  # No invented Shop/Weekly successor.
            self.assertTrue(home)
            self.assertEqual(len(transport.inputs), 3)
            self.assertEqual(transport.inputs[0][0], "tap")
            self.assertTrue(603 <= transport.inputs[0][1][0] <= 683)
            self.assertEqual(transport.inputs[1][0], "tap")
            self.assertLess(transport.inputs[1][1][0], 260)
            self.assertEqual(transport.inputs[2], ("back", None))
            self.assertEqual(runtime.input_count, 3)
            self.assertFalse(any("buy" in key for key in runtime.action_keys))

    def test_unknown_fresh_back_source_dispatches_nothing(self):
        port = self.port()
        captured = self.captured("alliance-menu.png")
        with patch.object(port, "_capture", return_value=captured), \
             patch.object(port, "_page", return_value=("unknown", ())):
            self.assertFalse(port._back())


class AllianceShopInventoryPixelTests(unittest.TestCase):
    def captured(self, name):
        from scripts.bluestacks_native_runtime import captured_native_frame_from_png
        path = ENTRY_FIXTURES / name
        return captured_native_frame_from_png(path.read_bytes(), captured_monotonic=1, path=path)

    def inventory_frame(self, ordinal=1):
        name = ("0011-alliance-shop-weekly-scan-1.png" if ordinal == 1
                else "0013-alliance-shop-weekly-scan-2.png")
        return self.captured(f"inventory-repaired-entry/{name}")

    def changed(self, captured, change):
        frame = captured.frame.copy()
        change(frame)
        valid, encoded = cv2.imencode(".png", frame)
        self.assertTrue(valid)
        png = encoded.tobytes()
        return replace(captured, frame=frame, png=png, sha256=hashlib.sha256(png).hexdigest())

    def port(self, frames):
        remaining = iter(frames)
        last = frames[-1]
        swipes = []
        runtime = SimpleNamespace(
            capture=lambda _label: next(remaining, last),
            swipe=lambda captured, **kwargs: swipes.append((captured, kwargs)),
        )
        context = SimpleNamespace(
            runtime=runtime, checkpoint=lambda: None,
            session=SimpleNamespace(observe=lambda capture, *, label: capture(label)),
            identity=SimpleNamespace(reset_id="inventory-pixel-reset"),
        )
        port = native.AllianceShopLivePort(context, settle_seconds=0)
        port.current_tab = "weekly"
        return port, swipes

    def test_actual_inventory_selects_exact_quote_without_scroll_or_buy(self):
        source = self.inventory_frame()
        port, swipes = self.port([source])
        scan = port.scan_weekly_offers()
        self.assertTrue(scan.complete, scan)
        self.assertEqual(len(scan.offers), 1)
        selected = AllianceShopPurchaseRoute._choice(scan)
        self.assertEqual(selected.status, "selected")
        row = scan.offers[0]
        self.assertEqual(row.item_identity, "Bioenhance Scheme")
        self.assertEqual((row.unit_price, row.balance, row.stock, row.item_quantity),
                         (80000, 1464257, 5, 29))
        self.assertEqual(row.currency_identity, ALLIANCE_CURRENCY)
        self.assertTrue(row.recognized)
        self.assertEqual(swipes, [])
        self.assertEqual(port.offer_evidence[row.item_identity].sha256, source.sha256)
        buy = port._outer_buy_roi(source, row)
        self.assertTrue(548 <= buy[0] < buy[2] <= 720)
        self.assertTrue(663 <= buy[1] < buy[3] <= 692)

    def test_unknown_owned_is_not_complete_or_preferred_absence(self):
        def hide_owned(frame):
            frame[710:746, 60:200] = 0
        before = self.changed(self.inventory_frame(), hide_owned)
        after = self.changed(self.inventory_frame(2), hide_owned)
        port, swipes = self.port([before, after])
        scan = port.scan_weekly_offers()
        self.assertFalse(scan.complete)
        self.assertEqual(scan.reason, "WEEKLY_OFFER_FIELDS_UNRESOLVED")
        self.assertEqual(len(scan.offers), 1)
        self.assertFalse(scan.offers[0].recognized)
        self.assertIsNone(scan.offers[0].item_quantity)
        self.assertEqual(len(scan.evidence_frame_sha256s), 2)
        self.assertEqual(len(swipes), 1)
        _source, gesture = swipes[0]
        buttons = native._offer_buttons(before)
        self.assertLess(gesture["start"][0], min(roi[0] for roi in buttons))
        self.assertEqual(gesture["start"][0], gesture["end"][0])
        self.assertGreater(gesture["start"][1], gesture["end"][1])

    def test_actual_refresh_tick_is_not_offer_list_progress(self):
        before, after = self.inventory_frame(), self.inventory_frame(2)
        self.assertNotEqual(before.sha256, after.sha256)
        self.assertTrue(native._same_offer_view(before, after))
        self.assertFalse(native._same_offer_view(before, self.captured("weekly-lower.png")))

    def test_native_diamond_currency_is_not_an_alliance_coin_quote(self):
        source = self.inventory_frame()
        def replace_coin(frame):
            frame[636:662, 582:608] = cv2.resize(frame[465:489, 598:624], (26, 26))
        altered = self.changed(source, replace_coin)
        port, _swipes = self.port([altered])
        row = port._read_offer(altered, "Bioenhance Scheme", ALLIANCE_WEEKLY_SHOP, None)
        self.assertIsNotNone(row)
        self.assertFalse(row.recognized)
        self.assertEqual(row.currency_identity, "UNKNOWN")
        self.assertIsNone(row.balance)

    def test_exact_native_other_quote_remains_the_only_unaffordable_preferred_fallback(self):
        port, _swipes = self.port([self.inventory_frame()])
        weekly = port._read_offer(self.inventory_frame(), "Bioenhance Scheme", ALLIANCE_WEEKLY_SHOP, None)
        fallback = port._read_offer(self.captured("other.png"), ALLIANCE_FALLBACK_ITEM, ALLIANCE_OTHER_SHOP, 1)
        self.assertIsNotNone(weekly)
        self.assertIsNotNone(fallback)
        self.assertTrue(fallback.recognized)
        self.assertEqual((fallback.unit_price, fallback.stock, fallback.item_quantity), (1000, 10055, 11052))
        replay = ReplayAllianceShopPort(
            weekly=(replace(weekly, balance=weekly.unit_price - 1),), fallback=fallback,
        )
        result = AllianceShopPurchaseRoute(replay, action_key="native-quote-fallback").run()
        self.assertEqual(result.status, "completed", result.to_mapping())
        self.assertTrue(replay.other_entered)
        self.assertEqual(len(replay.purchases), 1)
        self.assertEqual(replay.purchases[0][0].item_identity, ALLIANCE_FALLBACK_ITEM)
        self.assertEqual(result.selected_offer["quantity"], 1)


DIALOG_FIXTURES = ENTRY_FIXTURES / "quantity-dialog"
DIALOG_OFFER = DIALOG_FIXTURES / "0011-alliance-shop-weekly-scan-1.png"
DIALOG_LIST = DIALOG_FIXTURES / "0013-alliance-shop-open-quantity-dialog-immediate-before.png"
DIALOG_MODAL = DIALOG_FIXTURES / "0015-alliance-shop-open-quantity-dialog-settled.png"


def altered_png(path, change):
    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    change(frame)
    valid, encoded = cv2.imencode(".png", frame)
    assert valid
    return encoded.tobytes()


def diamond_total(frame):
    diamond = cv2.imread(str(DIALOG_OFFER), cv2.IMREAD_COLOR)[465:489, 598:624]
    frame[510:552, 238:280] = cv2.resize(diamond, (42, 42))


def erase_title(frame):
    frame[460:500, 240:540] = frame[575:615, 240:540].copy()


class QuantityModalTransport:
    """Actual modal pixels; only the measured close X returns to the actual Weekly list."""

    def __init__(self, start, *, modal=None):
        self.state, self.modal, self.inputs = start, modal, []

    def capture_png(self):
        return self.state if isinstance(self.state, bytes) else self.state.read_bytes()

    def dispatch_tap(self, point):
        self.inputs.append(("tap", point))
        if self.state == DIALOG_LIST and self.modal is not None:
            self.state = self.modal
        elif (self.state == DIALOG_MODAL or isinstance(self.state, bytes)) and (
            671 <= point[0] <= 706 and 389 <= point[1] <= 425
        ):
            self.state = DIALOG_LIST

    def dispatch_back(self):
        self.inputs.append(("back", None))
        self.state = (ENTRY_FIXTURES / "alliance-menu.png" if self.state == DIALOG_LIST
                      else ENTRY_FIXTURES / "immediate-home.png")


class AllianceShopQuantityModalPixelTests(unittest.TestCase):
    def captured(self, path, png=None):
        from scripts.bluestacks_native_runtime import captured_native_frame_from_png
        return captured_native_frame_from_png(png or path.read_bytes(), captured_monotonic=1, path=path)

    def port(self, transport, directory):
        from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
        runtime = LocalBlueStacksRuntime(transport, Path(directory) / "native", execute=True)
        context = SimpleNamespace(
            runtime=runtime, checkpoint=lambda: None,
            session=SimpleNamespace(observe=lambda capture, *, label: capture(label)),
            identity=SimpleNamespace(reset_id="pixel-replay-reset"),
        )
        return native.AllianceShopLivePort(context, settle_seconds=0), runtime

    def selected(self, port):
        row = port._read_offer(self.captured(DIALOG_OFFER), "Bioenhance Scheme", ALLIANCE_WEEKLY_SHOP, None)
        self.assertTrue(row.recognized)
        return row

    def test_actual_modal_binds_exact_quantity_total_coin_and_inner_buy(self):
        from tasks.purchases_disabled import purchase_dialog_matches
        with tempfile.TemporaryDirectory() as directory:
            port, runtime = self.port(QuantityModalTransport(DIALOG_MODAL), directory)
            row = self.selected(port)
            dialog = port._quantity_dialog(self.captured(DIALOG_MODAL), row)
            self.assertEqual(dialog, QuantityDialog(
                ALLIANCE_WEEKLY_SHOP, "Bioenhance Scheme", ALLIANCE_CURRENCY,
                80000, 1, 80000, dialog.inner_buy_roi, True,
            ))
            self.assertTrue(purchase_dialog_matches(
                row, quantity=1, selected_quantity=dialog.selected_quantity,
                displayed_total=dialog.total, shop_identity=row.shop_identity,
            ))
            x0, y0, x1, y1 = dialog.inner_buy_roi
            self.assertTrue(277 <= x0 < x1 <= 523 and 785 <= y0 < y1 <= 864)
            self.assertIsNone(port._quantity_dialog(self.captured(DIALOG_LIST), row))
            self.assertIsNone(port._quantity_dialog(
                self.captured(DIALOG_MODAL), replace(row, item_identity="Joy Coin"),
            ))
            self.assertEqual(runtime.input_count, 0)

    def test_modal_total_currency_needs_current_offer_alliance_coin(self):
        with tempfile.TemporaryDirectory() as directory:
            port, _runtime = self.port(QuantityModalTransport(DIALOG_MODAL), directory)
            row = self.selected(port)
            unbound = native.AllianceShopLivePort(SimpleNamespace(
                session=None, runtime=None, checkpoint=lambda: None,
                identity=SimpleNamespace(reset_id="pixel-replay-reset"),
            ), settle_seconds=0)
            diamond = self.captured(DIALOG_MODAL, altered_png(DIALOG_MODAL, diamond_total))
            for name, reader, frame in (("diamond", port, diamond),
                                        ("no-current-coin", unbound, self.captured(DIALOG_MODAL))):
                with self.subTest(name=name):
                    dialog = reader._quantity_dialog(frame, row)
                    self.assertEqual(dialog.selected_quantity, 1)
                    self.assertFalse(dialog.recognized)
                    self.assertEqual(dialog.currency_identity, "UNKNOWN")
                    self.assertIsNone(dialog.total)

    def test_own_modal_closes_by_measured_x_then_safe_back_home(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = QuantityModalTransport(DIALOG_MODAL)
            port, runtime = self.port(transport, directory)
            self.assertTrue(port.return_home())
            self.assertEqual(transport.inputs[0], ("tap", (688, 407)))
            self.assertEqual(transport.inputs[1:], [("back", None), ("back", None)])
            self.assertEqual(runtime.input_count, 3)
            self.assertFalse(any("buy" in key for key in runtime.action_keys))

    def test_unknown_modal_dispatches_nothing(self):
        def erase_close(frame):
            frame[385:430, 665:712] = frame[440:485, 665:712].copy()
        for change in (erase_title, erase_close):
            with self.subTest(change=change.__name__), tempfile.TemporaryDirectory() as directory:
                transport = QuantityModalTransport(altered_png(DIALOG_MODAL, change))
                port, runtime = self.port(transport, directory)
                self.assertFalse(port.return_home())
                self.assertFalse(port.cancel_quantity_dialog())
                self.assertEqual(transport.inputs, [])
                self.assertEqual(runtime.input_count, 0)

    def test_unproven_modal_currency_is_cancelled_with_zero_purchase(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = QuantityModalTransport(DIALOG_LIST, modal=altered_png(DIALOG_MODAL, diamond_total))
            port, runtime = self.port(transport, directory)
            row = self.selected(port)
            port.action_status = lambda _key: None
            port.enter_weekly_offers = lambda: setattr(port, "current_tab", "weekly") or True
            port.scan_weekly_offers = lambda: OfferScan((row,), True)
            port.purchase_one = lambda *_args: self.fail("inner Buy must not be reached")
            result = AllianceShopPurchaseRoute(port, action_key="modal-currency-cancel").run()
            self.assertEqual((result.status, result.reason), ("blocked", "ALLIANCE_QUANTITY_DIALOG_NOT_EXACT"))
            self.assertEqual((result.purchase_transport_calls, result.committed_action_count), (0, 0))
            self.assertTrue(result.terminal_home_verified)
            self.assertEqual([kind for kind, _point in transport.inputs], ["tap", "tap", "back", "back"])
            self.assertEqual(transport.inputs[1], ("tap", (688, 407)))
            self.assertEqual(runtime.input_count, 4)
            self.assertFalse(any("inner-buy" in key for key in runtime.action_keys))

    def test_startup_closes_only_own_modal_before_binding_canonical_home(self):
        from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
        from scripts.startup_normalization import is_clean_home_frame
        for start, recovered in ((DIALOG_MODAL, True), (altered_png(DIALOG_MODAL, erase_title), False)):
            with self.subTest(recovered=recovered), tempfile.TemporaryDirectory() as directory:
                transport = QuantityModalTransport(start)
                runtime = LocalBlueStacksRuntime(transport, Path(directory) / "native", execute=True)
                bound = []
                context = SimpleNamespace(
                    runtime=runtime, checkpoint=lambda: None, validate_identity=lambda: None,
                    is_clean_home=is_clean_home_frame, occurrence_key="occurrence",
                    identity=SimpleNamespace(reset_id="pixel-replay-reset", account_id="a", server_id="s"),
                    session=SimpleNamespace(
                        observe=lambda capture, *, label: capture(label),
                        adopt_retained_transport_count=lambda _count, source: None,
                        session_directory=Path(directory) / "native",
                    ),
                    accounting=lambda: SimpleNamespace(verified=True, input_count=runtime.input_count),
                    bind_initial_observation=lambda source, extra: bound.append((source, extra)),
                )
                entered = {"status": "route-entered", "purchase_transport_calls": 0, "committed_action_count": 0}
                with patch.object(native, "run_alliance_shop_route", lambda _port, action_key: dict(entered)):
                    result = native._service_driver(context, {"action_key": "key", "settle_seconds": 0})
                if recovered:
                    self.assertEqual(result["status"], "route-entered")
                    self.assertEqual(len(bound), 1)
                    self.assertTrue(is_clean_home_frame(bound[0][0].frame))
                    self.assertEqual(transport.inputs, [("tap", (688, 407)), ("back", None), ("back", None)])
                else:
                    self.assertEqual(result["reason"], "ALLIANCE_CANONICAL_HOME_NOT_RECOGNIZED")
                    self.assertEqual((bound, transport.inputs, result["input_count"]), ([], [], 0))


class AllianceShopNativeReplayTests(unittest.TestCase):
    def test_native_confirmed_weekly_and_fallback_preserve_duplicate_guard_without_unknown_signal(self):
        for fallback in (False, True):
            with self.subTest(fallback=fallback), tempfile.TemporaryDirectory() as directory:
                store = SafetyStore(Path(directory) / "actions.sqlite3")
                try:
                    context = safety_store_purchase_context(directory, store)
                    port = ActualSafetyStoreAlliancePort(context, fallback=fallback)
                    result = AllianceShopPurchaseRoute(port, action_key="native-confirmed").run()
                    self.assertEqual(result.status, "completed", result.to_mapping())
                    self.assertTrue(result.offer_effect_verified)
                    self.assertFalse(result.effect_reconciliation_required)
                    self.assertFalse(result.identical_retry_denied)
                    self.assertEqual(store.get_action_by_key("native-confirmed")["final_status"], "confirmed")
                    self.assertEqual(len(port.dialog_reads), 2)
                    (planned_frame, planned), (immediate_frame, immediate) = port.dialog_reads
                    self.assertGreater(immediate_frame.captured_monotonic, planned_frame.captured_monotonic)
                    self.assertNotEqual(immediate_frame.sha256, planned_frame.sha256)
                    self.assertEqual((planned.selected_quantity, immediate.selected_quantity), (1, 1))
                    self.assertEqual((planned.total, immediate.total), (port.selected.unit_price,) * 2)
                    self.assertEqual(port.tap_frame_hashes, [immediate_frame.sha256])
                    replay = AllianceShopPurchaseRoute(port, action_key="native-confirmed").run()
                    self.assertEqual(replay.status, "already_complete")
                    self.assertEqual(port.runtime.taps, ["native-confirmed"])
                finally:
                    store.close()

    def test_native_spend_without_item_delta_stays_unknown_and_never_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                context = safety_store_purchase_context(directory, store)
                port = ActualSafetyStoreAlliancePort(context, missing_item_effect=True)
                first = AllianceShopPurchaseRoute(port, action_key="native-unknown").run()
                self.assertEqual(first.status, "unresolved")
                self.assertTrue(first.identical_retry_denied)
                self.assertEqual(store.get_action_by_key("native-unknown")["final_status"], "unresolved")
                second = AllianceShopPurchaseRoute(port, action_key="native-unknown").run()
                self.assertEqual(second.status, "unresolved")
                self.assertEqual(port.runtime.taps, ["native-unknown"])
            finally:
                store.close()

    def test_changed_immediate_numeric_quote_is_denied_before_capability_and_transport(self):
        for fallback in (False, True):
            with self.subTest(fallback=fallback), tempfile.TemporaryDirectory() as directory:
                store = SafetyStore(Path(directory) / "actions.sqlite3")
                try:
                    context = safety_store_purchase_context(directory, store)
                    port = ActualSafetyStoreAlliancePort(context, fallback=fallback, changed_immediate=True)
                    dialog = port.open_quantity_dialog(port.selected)
                    effect = port.purchase_one(port.selected, dialog, "native-changed-immediate")
                    self.assertEqual(effect.status, "blocked")
                    self.assertFalse(effect.inner_buy_dispatched)
                    self.assertEqual(effect.purchase_transport_calls, 0)
                    self.assertEqual(port.runtime.taps, [])
                    self.assertIsNone(store.get_action_by_key("native-changed-immediate"))
                    self.assertEqual(port.dialog_reads[-1][1].selected_quantity, 2)
                finally:
                    store.close()

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
