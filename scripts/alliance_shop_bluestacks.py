"""Bounded Alliance Shop purchase flow over an injected canonical native boundary."""
from __future__ import annotations

from dataclasses import dataclass
import re
import time
from typing import Any, Callable, Mapping, Protocol

import cv2
import numpy as np

from automation_service.registry import (
    ALLIANCE_SHOP_FLOW_ID as FLOW_ID,
    ALLIANCE_SHOP_MAX_INPUTS as MAX_INPUTS,
    ALLIANCE_SHOP_PRODUCT_ID as PRODUCT_ID,
    ALLIANCE_SHOP_PRODUCT_REVISION as PRODUCT_REVISION,
)
from tasks.purchases_disabled import (
    ALLIANCE_FALLBACK_ITEM,
    ALLIANCE_WEEKLY_ITEMS,
    AlliancePurchaseChoice,
    ShopOffer,
    alliance_shop_choice,
    purchase_dialog_matches,
    purchase_effect_verified,
)


@dataclass(frozen=True)
class OfferScan:
    offers: tuple[ShopOffer, ...]
    complete: bool
    reason: str = ""
    evidence_refs: tuple[str, ...] = ()
    evidence_frame_sha256s: tuple[str, ...] = ()

@dataclass(frozen=True)
class QuantityDialog:
    shop_identity: str
    item_identity: str
    currency_identity: str
    unit_price: int | None
    selected_quantity: int | None
    total: int | None
    inner_buy_roi: tuple[int, int, int, int] | None
    recognized: bool = True


@dataclass(frozen=True)
class PurchaseEffect:
    status: str
    journal_status: str | None
    inner_buy_dispatched: bool
    purchase_transport_calls: int
    currency_after: int | None
    stock_after: int | None
    item_quantity_after: int | None
    item_identity_after: str
    currency_identity_after: str
    tab_successor_verified: bool
    effect_reconciliation_required: bool = False
    identical_retry_denied: bool = False
    action_key: str = ""
    reason: str = ""


class AllianceShopPort(Protocol):
    def action_status(self, action_key: str) -> str | None: ...
    def enter_weekly_offers(self) -> bool: ...
    def scan_weekly_offers(self) -> OfferScan: ...
    def enter_other_offers(self) -> bool: ...
    def scan_other_fallback(self) -> tuple[ShopOffer | None, bool, str]: ...
    def open_quantity_dialog(self, offer: ShopOffer) -> QuantityDialog | None: ...
    def cancel_quantity_dialog(self) -> bool: ...
    def purchase_one(self, offer: ShopOffer, dialog: QuantityDialog, action_key: str) -> PurchaseEffect: ...
    def return_home(self) -> bool: ...


@dataclass
class AllianceShopRouteResult:
    status: str = "blocked"
    reason: str = "ALLIANCE_SHOP_ROUTE_NOT_STARTED"
    flow_id: str = FLOW_ID
    task_id: str = PRODUCT_ID
    product_revision: str = PRODUCT_REVISION
    purchase_transport_calls: int = 0
    committed_action_count: int = 0
    prior_confirmed_action_count: int = 0
    accounting_verified: bool = False
    terminal_home_verified: bool = False
    effect_reconciliation_required: bool = False
    identical_retry_denied: bool = False
    selected_offer: Mapping[str, Any] | None = None
    selection_evidence: Mapping[str, Any] | None = None
    no_work_evidence: Mapping[str, Any] | None = None
    action_key: str | None = None
    offer_effect_verified: bool = False
    home_return_attempted: bool = False
    home_returned: bool = False

    def to_mapping(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "flow_id": self.flow_id,
            "task_id": self.task_id,
            "product_revision": self.product_revision,
            "purchase_transport_calls": self.purchase_transport_calls,
            "committed_action_count": self.committed_action_count,
            "prior_confirmed_action_count": self.prior_confirmed_action_count,
            "accounting_verified": self.accounting_verified,
            "terminal_home_verified": self.terminal_home_verified,
            "effect_reconciliation_required": self.effect_reconciliation_required,
            "identical_retry_denied": self.identical_retry_denied,
            "offer_effect_verified": self.offer_effect_verified,
            "selected_offer": dict(self.selected_offer) if self.selected_offer else None,
            "action_key": self.action_key,
            "selection_evidence": dict(self.selection_evidence) if self.selection_evidence else None,
            "no_work_evidence": dict(self.no_work_evidence) if self.no_work_evidence else None,
            "home_return_attempted": self.home_return_attempted,
            "home_returned": self.home_returned,
        }


def _offer_readiness(offer: ShopOffer | None) -> Mapping[str, Any] | None:
    if offer is None:
        return None
    return {
        "shop_identity": offer.shop_identity,
        "item_identity": offer.item_identity,
        "currency_identity": offer.currency_identity,
        "unit_price": offer.unit_price,
        "balance": offer.balance,
        "stock": offer.stock,
        "rarity": offer.rarity,
        "available": offer.available,
        "premium": offer.premium,
        "recognized": offer.recognized,
        "offer_identity": offer.offer_identity,
    }


def _scan_readiness(complete: bool, reason: str, refs, hashes) -> Mapping[str, Any]:
    return {
        "complete": complete,
        "reason": reason,
        "frame_refs": tuple(refs),
        "frame_sha256s": tuple(hashes),
    }


class AllianceShopPurchaseRoute:
    """Purchase at most one exact Weekly offer or exact Other fallback per reset."""

    max_inputs = MAX_INPUTS
    max_actions = 1

    def __init__(self, port: AllianceShopPort, *, action_key: str) -> None:
        if not isinstance(action_key, str) or not action_key.strip():
            raise ValueError("Alliance Shop requires its canonical reset-scoped action key")
        self.port = port
        self.action_key = action_key
        self.result = AllianceShopRouteResult(action_key=action_key)
        self._effect: PurchaseEffect | None = None
        self._offer: ShopOffer | None = None
        self._dialog: QuantityDialog | None = None

    @staticmethod
    def _choice(scan: OfferScan, fallback: ShopOffer | None = None,
                fallback_complete: bool = True) -> AlliancePurchaseChoice:
        return alliance_shop_choice(
            scan.offers, fallback,
            weekly_inventory_complete=scan.complete,
            fallback_inventory_complete=fallback_complete,
        )

    def _open_and_purchase(self, offer: ShopOffer) -> bool:
        dialog = self.port.open_quantity_dialog(offer)
        self._dialog = dialog
        if (
            dialog is None or not dialog.recognized
            or dialog.shop_identity != offer.shop_identity
            or dialog.item_identity != offer.item_identity
            or dialog.currency_identity != offer.currency_identity
            or dialog.unit_price != offer.unit_price
            or not purchase_dialog_matches(
                offer, quantity=1, selected_quantity=dialog.selected_quantity,
                displayed_total=dialog.total, shop_identity=offer.shop_identity,
            )
            or dialog.inner_buy_roi is None
        ):
            if dialog is not None:
                self.port.cancel_quantity_dialog()
            self.result.reason = "ALLIANCE_QUANTITY_DIALOG_NOT_EXACT"
            return False
        effect = self.port.purchase_one(offer, dialog, self.action_key)
        self._effect, self._offer = effect, offer
        self.result.purchase_transport_calls += effect.purchase_transport_calls
        self.result.effect_reconciliation_required = effect.effect_reconciliation_required
        self.result.identical_retry_denied = effect.identical_retry_denied
        self.result.action_key = effect.action_key or self.action_key
        self.result.selected_offer = {
            "shop_identity": offer.shop_identity,
            "offer_identity": offer.offer_identity,
            "item_identity": offer.item_identity,
            "currency_identity": offer.currency_identity,
            "rarity": offer.rarity,
            "unit_price": offer.unit_price,
            "balance_before": offer.balance,
            "stock_before": offer.stock,
            "item_quantity_before": offer.item_quantity,
            "quantity": 1,
            "total": dialog.total,
        }
        if effect.status != "confirmed" or effect.journal_status != "confirmed":
            self.result.reason = effect.reason or "ALLIANCE_PURCHASE_EFFECT_UNRESOLVED"
            self.result.status = "unresolved" if effect.effect_reconciliation_required else "blocked"
            return False
        self.result.committed_action_count = 1
        return True

    def run(self) -> AllianceShopRouteResult:
        prior = self.port.action_status(self.action_key)
        if prior not in {None, "confirmed", "cancelled"}:
            self.result.status = "unresolved"
            self.result.reason = "ALLIANCE_CANONICAL_ACTION_REQUIRES_RECONCILIATION"
            self.result.effect_reconciliation_required = True
            self.result.identical_retry_denied = True
            self.result.home_return_attempted = True
            self.result.home_returned = self.port.return_home()
            self.result.terminal_home_verified = self.result.home_returned
            return self.result
        if prior == "confirmed":
            self.result.reason = "ALLIANCE_RESET_OCCURRENCE_ALREADY_CONFIRMED"
            self.result.prior_confirmed_action_count = 1
            self.result.home_return_attempted = True
            self.result.home_returned = self.port.return_home()
            self.result.terminal_home_verified = self.result.home_returned
            self.result.accounting_verified = self.result.home_returned
            self.result.status = "already_complete" if self.result.home_returned else "blocked"
            return self.result

        purchase_ready = False
        weekly_scan = self.port.scan_weekly_offers() if self.port.enter_weekly_offers() else None
        if weekly_scan is None:
            self.result.reason = "ALLIANCE_WEEKLY_OFFERS_NOT_RECOGNIZED"
        else:
            choice = self._choice(weekly_scan)
            if choice.status == "selected":
                self.result.selection_evidence = {
                    "weekly_inventory": _scan_readiness(
                        weekly_scan.complete, weekly_scan.reason,
                        weekly_scan.evidence_refs, weekly_scan.evidence_frame_sha256s,
                    ),
                    "weekly_offers": tuple(_offer_readiness(row) for row in weekly_scan.offers),
                    "fallback_inventory": None,
                    "fallback_offer": None,
                }
                purchase_ready = self._open_and_purchase(choice.offer)
            elif choice.status == "blocked":
                self.result.reason = choice.reason
            elif self.port.enter_other_offers():
                fallback, complete, fallback_reason = self.port.scan_other_fallback()
                choice = self._choice(weekly_scan, fallback, complete)
                if choice.status == "selected":
                    fallback_evidence = getattr(self.port, "last_other_scan_evidence", {})
                    self.result.selection_evidence = {
                        "weekly_inventory": _scan_readiness(
                            weekly_scan.complete, weekly_scan.reason,
                            weekly_scan.evidence_refs, weekly_scan.evidence_frame_sha256s,
                        ),
                        "weekly_offers": tuple(_offer_readiness(row) for row in weekly_scan.offers),
                        "fallback_inventory": _scan_readiness(
                            complete, fallback_reason,
                            fallback_evidence.get("frame_refs", ()),
                            fallback_evidence.get("frame_sha256s", ()),
                        ),
                        "fallback_offer": _offer_readiness(fallback),
                    }
                    purchase_ready = self._open_and_purchase(choice.offer)
                elif choice.status == "blocked":
                    self.result.reason = choice.reason or fallback_reason
                else:
                    self.result.status = "deferred"
                    self.result.reason = choice.reason or fallback_reason or "NO_AFFORDABLE_ALLIANCE_OFFER"
                    fallback_evidence = getattr(self.port, "last_other_scan_evidence", {})
                    self.result.no_work_evidence = {
                        "reason": self.result.reason,
                        "weekly_inventory": _scan_readiness(
                            weekly_scan.complete, weekly_scan.reason,
                            weekly_scan.evidence_refs, weekly_scan.evidence_frame_sha256s,
                        ),
                        "weekly_offers": tuple(_offer_readiness(row) for row in weekly_scan.offers),
                        "fallback_inventory": _scan_readiness(
                            complete, fallback_reason,
                            fallback_evidence.get("frame_refs", ()),
                            fallback_evidence.get("frame_sha256s", ()),
                        ),
                        "fallback_offer": _offer_readiness(fallback),
                    }
            else:
                self.result.reason = "ALLIANCE_OTHER_FALLBACK_TAB_NOT_RECOGNIZED"

        self.result.home_return_attempted = True
        self.result.home_returned = self.port.return_home()
        self.result.terminal_home_verified = self.result.home_returned
        if self._effect is not None and self._offer is not None and self._dialog is not None:
            effect = self._effect
            self.result.offer_effect_verified = purchase_effect_verified(
                self._offer,
                quantity=1,
                selected_quantity=self._dialog.selected_quantity,
                displayed_total=self._dialog.total,
                currency_after=effect.currency_after,
                stock_after=effect.stock_after,
                item_quantity_after=effect.item_quantity_after,
                item_identity_after=effect.item_identity_after,
                currency_identity_after=effect.currency_identity_after,
                tab_successor_verified=effect.tab_successor_verified,
                terminal_home_verified=self.result.terminal_home_verified,
                inner_buy_dispatched=effect.inner_buy_dispatched,
            )
            if not self.result.offer_effect_verified:
                self.result.status = "unresolved" if (
                    effect.inner_buy_dispatched or effect.journal_status == "confirmed"
                ) else "blocked"
                self.result.reason = "ALLIANCE_ITEM_CURRENCY_HOME_RECONCILIATION_FAILED"
                unresolved = effect.inner_buy_dispatched or effect.journal_status == "confirmed"
                self.result.effect_reconciliation_required = unresolved
                self.result.identical_retry_denied = unresolved
            elif purchase_ready and self.result.terminal_home_verified:
                self.result.status = "completed"
                self.result.reason = "ALLIANCE_ALLOWLISTED_PURCHASE_AND_HOME_VERIFIED"
                self.result.accounting_verified = True
        elif self.result.status == "deferred" and self.result.terminal_home_verified:
            self.result.accounting_verified = self.result.purchase_transport_calls == 0
        elif not self.result.terminal_home_verified:
            self.result.status = "blocked"
            self.result.reason = "ALLIANCE_CANONICAL_HOME_NOT_VERIFIED"
        elif self.result.status != "deferred":
            self.result.status = "blocked"
            if self.result.reason == "ALLIANCE_SHOP_ROUTE_NOT_STARTED":
                self.result.reason = "ALLIANCE_NO_PURCHASE_AUTHORIZED"
        return self.result


def run_alliance_shop_route(port: AllianceShopPort, *, action_key: str) -> dict[str, Any]:
    return AllianceShopPurchaseRoute(port, action_key=action_key).run().to_mapping()


@dataclass(frozen=True)
class _OcrWord:
    text: str
    roi: tuple[int, int, int, int]
    line: tuple[int, int, int]


def _norm(value: str) -> str:
    return re.sub(r"[^0-9a-z★]+", "", value.casefold())


def _ocr_words(captured) -> tuple[_OcrWord, ...]:
    from scripts.bounded_tesseract import call_ocr, tesseract_data
    data = call_ocr(tesseract_data, captured.frame, config="--psm 6")
    words = []
    for index, raw in enumerate(data.get("text", ())):
        text = str(raw).strip()
        try:
            confidence = float(data["conf"][index])
            x, y = int(data["left"][index]), int(data["top"][index])
            width, height = int(data["width"][index]), int(data["height"][index])
            line = (int(data["block_num"][index]), int(data["par_num"][index]), int(data["line_num"][index]))
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if text and confidence >= 35 and 0 <= x < x + width <= 800 and 0 <= y < y + height <= 1280:
            words.append(_OcrWord(text, (x, y, x + width, y + height), line))
    return tuple(words)


def _lines(words):
    groups = {}
    for word in words:
        groups.setdefault(word.line, []).append(word)
    return tuple(tuple(sorted(row, key=lambda item: item.roi[0])) for _key, row in sorted(groups.items()))


def _hits(words, phrase):
    expected = tuple(_norm(part) for part in phrase.split())
    found = []
    for line in _lines(words):
        tokens = tuple(_norm(word.text) for word in line)
        for start in range(len(tokens) - len(expected) + 1):
            if tokens[start:start + len(expected)] == expected:
                selected = line[start:start + len(expected)]
                found.append((min(x.roi[0] for x in selected), min(x.roi[1] for x in selected),
                              max(x.roi[2] for x in selected), max(x.roi[3] for x in selected)))
    return found


def _has(words, phrase):
    return len(_hits(words, phrase)) == 1


def _numbers(line):
    values = []
    for word in line:
        token = word.text.replace(",", "")
        if token.isascii() and token.isdecimal():
            values.append((int(token), word))
    return values


def _icon(captured, word):
    x0, y0, _x1, y1 = word.roi
    cy = (y0 + y1) // 2
    if x0 < 42 or cy < 20 or cy + 20 > 1280:
        return None
    patch = captured.frame[cy - 20:cy + 20, x0 - 42:x0 - 5]
    return cv2.resize(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY), (32, 32))


def _icon_matches(a, b):
    if a is None or b is None or a.shape != b.shape:
        return False
    first, second = a.astype(np.float32), b.astype(np.float32)
    first -= float(first.mean())
    second -= float(second.mean())
    norm = float(np.linalg.norm(first) * np.linalg.norm(second))
    return norm > 1e-6 and float(np.sum(first * second) / norm) >= 0.86


class AllianceShopLivePort:
    """Fresh native OCR and current-frame taps for the observed Alliance Shop path."""

    def __init__(self, context, *, settle_seconds: float):
        if not 0 <= float(settle_seconds) <= 5:
            raise ValueError("Alliance Shop route requires a bounded delay")
        self.context, self.session, self.runtime = context, context.session, context.runtime
        self.settle_seconds = float(settle_seconds)
        self.current_tab = ""
        self.currency_icons: dict[str, np.ndarray] = {}
        self.last_dialog = None
        self.offer_evidence = {}

    def _capture(self, label):
        self.context.checkpoint()
        return self.session.observe(self.runtime.capture, label=label)

    def _words(self, captured):
        self.context.checkpoint()
        return _ocr_words(captured)

    def _home(self, captured):
        from scripts.startup_normalization import is_clean_home_frame
        return bool(is_clean_home_frame(captured.frame))

    def _page(self, captured):
        words = self._words(captured)
        if _has(words, "Weekly Offers"):
            return "weekly", words
        if _has(words, "Other"):
            return "other", words
        if _has(words, "Alliance Shop"):
            return "alliance", words
        if _has(words, "Alliance"):
            return "alliance_menu", words
        if self._home(captured):
            return "home", words
        return "unknown", words

    def action_status(self, action_key):
        import hashlib
        import json
        from pathlib import Path

        action = self.context.action_store.get_action_by_key(action_key)
        if action is None:
            return None
        expected = {
            "action_key": action_key,
            "task_id": FLOW_ID,
            "semantic_action": "PURCHASE_ALLIANCE_SHOP_OFFER",
            "target_identity": "alliance-shop:inner-buy",
            "game_day_id": self.context.identity.reset_id,
            "expected_postcondition": "ALLIANCE_SHOP_PURCHASE_RECONCILED",
            "cost_type": "ALLIANCE_COINS",
            "quantity": 1,
            "runtime_profile_id": self.context.runtime_profile_id,
        }
        if any(action.get(field) != value for field, value in expected.items()):
            return "unresolved"
        state = str(action.get("final_status") or "unresolved")
        if state == "cancelled":
            return state
        if state != "confirmed":
            return "unresolved"
        try:
            request = json.loads(action["policy_request_json"])
            proof = json.loads(action["reconciliation_result_json"])
            preconditions = tuple(request["semantic_preconditions"])
            references = tuple(Path(value) for value in proof["evidence_refs"])
            if len(preconditions) != 12:
                return "unresolved"
            shop = preconditions[0].removeprefix("shop=")
            subject = preconditions[1].removeprefix("item=")
            price = int(preconditions[3].removeprefix("unit_price="))
            stock = int(preconditions[4].removeprefix("stock="))
            balance = int(preconditions[5].removeprefix("balance="))
            quantity = int(preconditions[6].removeprefix("quantity="))
            total = int(preconditions[7].removeprefix("total="))
            source = (
                "ALLIANCE_SHOP_WEEKLY_QUANTITY_DIALOG" if shop == "weekly_offers"
                else "ALLIANCE_SHOP_OTHER_QUANTITY_DIALOG" if shop == "other" else None
            )
            expected_preconditions = (
                f"shop={shop}", f"item={subject}", "currency=ALLIANCE_COINS",
                f"unit_price={price}", f"stock={stock}", f"balance={balance}",
                "quantity=1", f"total={price}",
                f"alliance_shop_reset_id={self.context.identity.reset_id}",
                "alliance_shop_action_ordinal=1", "alliance_shop_action_count_before=0",
                "alliance_shop_action_limit=1",
            )
            allowed_subject = (
                shop == "weekly_offers" and subject in {"joy_coin", "timed_recruit_coin", "bioenhance_scheme"}
            ) or (shop == "other" and subject == "one_star_gear_enhance_material")
            digest = proof["frame_sha256"]
            root = Path(request["runtime_session_id"]).resolve(strict=True)
            if (
                source is None or not allowed_subject or quantity != 1 or total != price
                or stock < 1 or balance < price
                or action.get("cost_amount") != price
                or request.get("task_id") != FLOW_ID
                or request.get("task_mode") != "supervised_validation"
                or request.get("action_kind") != "alliance_shop_purchase-v2"
                or request.get("semantic_action") != "PURCHASE_ALLIANCE_SHOP_OFFER"
                or request.get("subject") != subject
                or request.get("resource_or_currency") != "ALLIANCE_COINS"
                or request.get("maximum_cost") != price
                or request.get("free_only") is not False
                or request.get("semantic_preconditions") != list(expected_preconditions)
                or request.get("semantic_postconditions") != ["ALLIANCE_SHOP_PURCHASE_RECONCILED"]
                or request.get("allowed_confirmation_dialogs") != [source]
                or proof.get("confirmed") is not True
                or not isinstance(digest, str) or len(digest) != 64
                or len(references) < 4
            ):
                return "unresolved"
            retained = []
            for path in references:
                if path.is_absolute() and not path.is_symlink():
                    resolved = path.resolve(strict=True)
                    if resolved.is_relative_to(root) and resolved.is_file():
                        retained.append(resolved)
            if len(set(retained)) != len(set(references)):
                return "unresolved"
            matching = [path for path in retained
                        if hashlib.sha256(path.read_bytes()).hexdigest() == digest]
            if len(matching) != 1:
                return "unresolved"
            frame = cv2.imread(str(matching[0]), cv2.IMREAD_COLOR)
            from scripts.startup_normalization import is_clean_home_frame
            if not is_clean_home_frame(frame):
                return "unresolved"
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, IndexError):
            return "unresolved"
        return "confirmed"

    def _tap(self, target_identity, action_name, bind_target, dispatch, recognize):
        before = self._capture(f"alliance-shop-{action_name}-immediate-before")
        try:
            target = tuple(bind_target(before))
        except (ValueError, TypeError):
            return False
        if len(target) != 4 or not (0 <= target[0] < target[2] <= 800 and 0 <= target[1] < target[3] <= 1280):
            return False
        self.context.checkpoint()
        dispatch(before, target, f"alliance-shop:{action_name}:{before.sha256}")
        after = self._capture(f"alliance-shop-{action_name}-immediate-post")
        if recognize(after):
            return True
        if self.settle_seconds:
            time.sleep(self.settle_seconds)
        settled = self._capture(f"alliance-shop-{action_name}-settled")
        return bool(recognize(settled))

    def _tap_text(self, label, target_identity, action_name, recognize):
        def bind(before):
            matches = _hits(self._words(before), label)
            if len(matches) != 1:
                raise ValueError(f"Alliance {label!r} target is not uniquely recognized")
            return matches[0]
        return self._tap(
            target_identity, action_name, bind,
            lambda before, roi, key: self.runtime.tap(
                before, target_identity=target_identity, target_roi=roi, action_key=key,
            ),
            recognize,
        )

    def _tap_roi(self, bind_target, target_identity, action_name, recognize):
        return self._tap(
            target_identity, action_name, bind_target,
            lambda before, target, key: self.runtime.tap(
                before, target_identity=target_identity, target_roi=target, action_key=key,
            ),
            recognize,
        )

    def _back(self):
        def recognize(after):
            page, _words = self._page(after)
            return page in {"weekly", "other", "alliance", "alliance_menu", "home"}
        return self._tap(
            "system-back", "return-home", lambda _before: (0, 0, 800, 1280),
            lambda before, _roi, key: self.runtime.back(before, action_key=key), recognize,
        )

    def enter_weekly_offers(self):
        if not self._home(self._capture("alliance-shop-home-source")):
            return False
        if not self._tap_text("Alliance", "home.alliance-entry", "open-alliance",
                              lambda frame: self._page(frame)[0] in {"alliance", "alliance_menu"}):
            return False
        if not self._tap_text("Alliance Shop", "alliance:shop-entry", "open-shop",
                              lambda frame: self._page(frame)[0] == "alliance"):
            return False
        if not self._tap_text("Weekly Offers", "alliance-shop:weekly-tab", "open-weekly",
                              lambda frame: self._page(frame)[0] == "weekly"):
            return False
        self.current_tab = "weekly"
        return True

    def enter_other_offers(self):
        if not self._tap_text("Shop", "alliance-shop:standard-shop", "open-standard-shop",
                              lambda frame: _has(self._words(frame), "Other")):
            return False
        if not self._tap_text("Other", "alliance-shop:other-tab", "open-other",
                              lambda frame: self._page(frame)[0] == "other"):
            return False
        self.current_tab = "other"
        return True

    def _read_offer(self, captured, item, shop, rarity):
        words = self._words(captured)
        item_hits = _hits(words, item)
        if len(item_hits) != 1:
            return None
        item_roi = item_hits[0]
        item_y = (item_roi[1] + item_roi[3]) / 2
        price_lines = []
        for line in _lines(words):
            text = " ".join(word.text for word in line).casefold()
            if any(token in text for token in ("owned", "stock", "remaining", "refresh", "total")):
                continue
            values = [entry for entry in _numbers(line) if entry[0] > 0]
            distance = abs(sum((word.roi[1] + word.roi[3]) / 2 for word in line) / len(line) - item_y)
            if len(values) == 1 and distance <= 125:
                price_lines.append((distance, values[0]))
        price_lines.sort(key=lambda row: row[0])
        price = price_lines[0][1] if price_lines and (
            len(price_lines) == 1 or price_lines[0][0] != price_lines[1][0]
        ) else None
        stock_fields = []
        owned_fields = []
        for line in _lines(words):
            text = " ".join(word.text for word in line).casefold()
            distance = abs(sum((word.roi[1] + word.roi[3]) / 2 for word in line) / len(line) - item_y)
            values = _numbers(line)
            if distance <= 160 and len(values) == 1:
                if "remaining" in text or "stock" in text:
                    stock_fields.append(values[0][0])
                if "owned" in text:
                    owned_fields.append(values[0][0])
        stock = stock_fields[0] if len(stock_fields) == 1 else None
        owned = owned_fields[0] if len(owned_fields) == 1 else None
        balance = None
        if price is not None:
            price_icon = _icon(captured, price[1])
            balances = []
            for line in _lines(words):
                for amount, word in _numbers(line):
                    if word.roi[1] <= 220 and _icon_matches(price_icon, _icon(captured, word)):
                        balances.append(amount)
            if len(balances) == 1:
                balance = balances[0]
            if price_icon is not None:
                self.currency_icons[f"{shop}:{item}"] = price_icon
        return ShopOffer(
            shop_identity=shop,
            item_identity=item,
            currency_identity="Alliance Coins",
            unit_price=price[0] if price else None,
            balance=balance,
            stock=stock,
            item_quantity=owned,
            rarity=rarity,
            available=(stock > 0 if stock is not None else None),
            recognized=True,
            offer_identity=f"{shop}:{item}",
        )

    def _scroll(self, captured, words, page):
        buttons = _hits(words, "Buy")
        if len(buttons) < 2:
            return None
        top = min(buttons, key=lambda roi: roi[1])
        bottom = max(buttons, key=lambda roi: roi[1])
        start = ((top[0] + top[2]) // 2, (bottom[1] + bottom[3]) // 2)
        end = ((top[0] + top[2]) // 2, (top[1] + top[3]) // 2)
        if start[1] - end[1] < 80:
            return None
        self.context.checkpoint()
        self.runtime.swipe(
            captured,
            start=start,
            end=end,
            action_key=f"alliance-shop:{page}-scroll:{captured.sha256}",
            target_identity=f"alliance-shop:{page}-offer-list-scroll",
        )
        settled = self._capture(f"alliance-shop-{page}-scroll-successor")
        if self._page(settled)[0] != page:
            return None
        return settled

    def scan_weekly_offers(self):
        if self.current_tab != "weekly":
            return OfferScan((), False, "WEEKLY_TAB_NOT_CURRENT")
        offers = {}
        scanned = []
        def scan_result(complete, reason=""):
            return OfferScan(
                tuple(offers.values()), complete, reason,
                tuple(str(frame.path) for frame in scanned),
                tuple(frame.sha256 for frame in scanned),
            )
        for ordinal in range(5):
            captured = self._capture(f"alliance-shop-weekly-scan-{ordinal + 1}")
            scanned.append(captured)
            if self._page(captured)[0] != "weekly":
                return scan_result(False, "WEEKLY_PAGE_NOT_RECOGNIZED")
            for item in ALLIANCE_WEEKLY_ITEMS:
                offer = self._read_offer(captured, item, "Weekly Offers", None)
                if offer is not None:
                    offers[item] = offer
                    self.offer_evidence[item] = captured
            if any(
                row.available is True and row.stock and row.balance is not None
                and row.unit_price is not None and row.balance >= row.unit_price
                for row in offers.values()
            ):
                return scan_result(True)
            successor = self._scroll(captured, self._words(captured), "weekly")
            if successor is None:
                return scan_result(False, "WEEKLY_LIST_END_NOT_PROVEN")
            if successor.sha256 == captured.sha256:
                return scan_result(True)
        return scan_result(False, "WEEKLY_SCAN_BOUND_REACHED")

    def scan_other_fallback(self):
        self.last_other_scan_evidence = {"frame_refs": (), "frame_sha256s": ()}
        if self.current_tab != "other":
            return None, False, "OTHER_TAB_NOT_CURRENT"
        captured = self._capture("alliance-shop-other-fallback-source")
        scanned = []
        for ordinal in range(8):
            scanned.append(captured)
            self.last_other_scan_evidence = {
                "frame_refs": tuple(str(frame.path) for frame in scanned),
                "frame_sha256s": tuple(frame.sha256 for frame in scanned),
            }
            if self._page(captured)[0] != "other":
                return None, False, "OTHER_PAGE_NOT_RECOGNIZED"
            offer = self._read_offer(captured, ALLIANCE_FALLBACK_ITEM, "Other", 1)
            if offer is not None:
                self.offer_evidence[offer.item_identity] = captured
                return offer, True, ""
            successor = self._scroll(captured, self._words(captured), "other")
            if successor is None:
                return None, False, "OTHER_LIST_END_NOT_PROVEN"
            if successor.sha256 == captured.sha256:
                return None, True, "EXACT_FALLBACK_NOT_PRESENT"
            captured = successor
        return None, False, "OTHER_SCAN_BOUND_REACHED"

    def _outer_buy_roi(self, captured, offer):
        words = self._words(captured)
        items, buys = _hits(words, offer.item_identity), _hits(words, "Buy")
        if len(items) != 1 or not buys:
            raise ValueError("Alliance offer row or Buy target is ambiguous")
        y = (items[0][1] + items[0][3]) / 2
        ranked = sorted((abs((roi[1] + roi[3]) / 2 - y), roi) for roi in buys)
        if ranked[0][0] > 140 or (len(ranked) > 1 and ranked[0][0] == ranked[1][0]):
            raise ValueError("Alliance outer Buy is not bound to the exact offer")
        return ranked[0][1]

    def _quantity_dialog(self, captured, offer):
        words = self._words(captured)
        if len(_hits(words, offer.item_identity)) != 1:
            return None
        totals = [line for line in _lines(words) if "total" in " ".join(word.text for word in line).casefold()]
        quantities = []
        for line in _lines(words):
            text = " ".join(word.text for word in line)
            match = re.search(r"(?<!\d)(\d[\d,]*)\s*/\s*(\d[\d,]*)(?!\d)", text)
            if match:
                quantities.append((int(match.group(1).replace(",", "")), line))
        if len(totals) != 1 or len(quantities) != 1:
            return None
        total_numbers = _numbers(totals[0])
        if len(total_numbers) != 1:
            return None
        total, total_word = total_numbers[0]
        expected_icon = self.currency_icons.get(offer.offer_identity)
        if not _icon_matches(expected_icon, _icon(captured, total_word)):
            return None
        quantity, quantity_line = quantities[0]
        quantity_y = sum((word.roi[1] + word.roi[3]) / 2 for word in quantity_line) / len(quantity_line)
        buys = [roi for roi in _hits(words, "Buy") if (roi[1] + roi[3]) / 2 > quantity_y]
        if not buys:
            return None
        buy_roi = max(buys, key=lambda roi: roi[1])
        return QuantityDialog(
            offer.shop_identity, offer.item_identity, offer.currency_identity,
            offer.unit_price, quantity, total, buy_roi, True,
        )

    def open_quantity_dialog(self, offer):
        captured = self._capture("alliance-shop-outer-buy-source")
        if self._page(captured)[0] != self.current_tab:
            return None
        try:
            roi = self._outer_buy_roi(captured, offer)
        except ValueError:
            return None
        if not self._tap_roi(
            lambda before: self._outer_buy_roi(before, offer),
            f"alliance-shop:outer-buy:{offer.item_identity}", "open-quantity-dialog",
            lambda frame: self._quantity_dialog(frame, offer) is not None,
        ):
            return None
        dialog_frame = self._capture("alliance-shop-quantity-dialog")
        self.last_dialog = (offer, dialog_frame)
        return self._quantity_dialog(dialog_frame, offer)

    def cancel_quantity_dialog(self):
        captured = self._capture("alliance-shop-quantity-cancel-source")
        hits = _hits(self._words(captured), "X")
        if len(hits) != 1:
            return False
        return self._tap_roi(
            lambda before: _hits(self._words(before), "X")[0]
            if len(_hits(self._words(before), "X")) == 1 else None,
            "alliance-shop:quantity-dialog-close", "cancel-quantity-dialog",
            lambda frame: self._page(frame)[0] == self.current_tab,
        )

    def purchase_one(self, offer, dialog, action_key):
        if self.last_dialog is None:
            return PurchaseEffect("blocked", None, False, 0, None, None, None, "", "", False,
                                  action_key=action_key, reason="ALLIANCE_DIALOG_SOURCE_MISSING")
        return _purchase_alliance_offer(
            self.context, self, offer, dialog, action_key, settle_seconds=self.settle_seconds,
        )

    def return_home(self):
        for _ in range(4):
            captured = self._capture("alliance-shop-home-return-source")
            if self._home(captured):
                return True
            if self._page(captured)[0] not in {"weekly", "other", "alliance", "alliance_menu"}:
                return False
            if not self._back():
                return False
        return self._home(self._capture("alliance-shop-home-return-final"))


def _purchase_alliance_offer(context, port, offer, dialog, action_key, *, settle_seconds):
    import hashlib
    from safe_action_core import ActionClass, CentralPolicy, Observation, PolicyRequest, SafeActionExecutor, TransportResult
    from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID

    subject = {
        "Joy Coin": "joy_coin",
        "Timed Recruit Coin": "timed_recruit_coin",
        "Bioenhance Scheme": "bioenhance_scheme",
        ALLIANCE_FALLBACK_ITEM: "one_star_gear_enhance_material",
    }.get(offer.item_identity)
    shop = "weekly_offers" if offer.shop_identity == "Weekly Offers" else "other"
    source_state = (
        "ALLIANCE_SHOP_WEEKLY_QUANTITY_DIALOG"
        if shop == "weekly_offers" else "ALLIANCE_SHOP_OTHER_QUANTITY_DIALOG"
    )
    expected_subjects = {
        "weekly_offers": {"joy_coin", "timed_recruit_coin", "bioenhance_scheme"},
        "other": {"one_star_gear_enhance_material"},
    }
    if subject not in expected_subjects[shop] or offer.currency_identity != "Alliance Coins":
        return PurchaseEffect(
            "blocked", None, False, 0, None, None, None, "", "", False,
            action_key=action_key, reason="ALLIANCE_POLICY_ITEM_OR_CURRENCY_NOT_ALLOWLISTED",
        )
    if not purchase_dialog_matches(
        offer, quantity=1, selected_quantity=dialog.selected_quantity,
        displayed_total=dialog.total, shop_identity=offer.shop_identity,
    ):
        return PurchaseEffect(
            "blocked", None, False, 0, None, None, None, "", "", False,
            action_key=action_key, reason="ALLIANCE_EXACT_DIALOG_QUANTITY_NOT_RECONCILED",
        )
    target_identity = "alliance-shop:inner-buy"
    postcondition = "ALLIANCE_SHOP_PURCHASE_RECONCILED"
    runtime, session, store = context.runtime, context.session, context.action_store
    page_source = port._capture("alliance-shop-purchase-policy-source")
    source_dialog = port._quantity_dialog(page_source, offer)
    if source_dialog is None or (
        source_dialog.selected_quantity != 1 or source_dialog.total != offer.unit_price
        or source_dialog.inner_buy_roi != dialog.inner_buy_roi
    ):
        return PurchaseEffect(
            "blocked", None, False, 0, None, None, None, "", "", False,
            action_key=action_key, reason="ALLIANCE_FRESH_NUMERIC_DIALOG_CHANGED",
        )
    target_roi = source_dialog.inner_buy_roi
    x0, y0, x1, y1 = target_roi
    source_observation = Observation(
        frame_sha256=page_source.sha256,
        capture_completed_monotonic=page_source.captured_monotonic,
        runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        width=800,
        height=1280,
        valid_png=page_source.frame.shape == (1280, 800, 3),
        corrupt=False,
        black=not bool(np.any(page_source.frame)),
        source_state=source_state,
        overlay_state="none",
        target_identity=target_identity,
        target_roi=target_roi,
        recognized=True,
        clipped=False,
        ambiguous=False,
        control_class="BUY",
        consequence="alliance_shop_purchase",
        cost_type="ALLIANCE_COINS",
        cost_amount=offer.unit_price,
        quantity=1,
        expected_postcondition=postcondition,
        evidence_refs=(str(page_source.path),),
        critical_roi_hashes=(("inner-buy", hashlib.sha256(page_source.frame[y0:y1, x0:x1].tobytes()).hexdigest()),),
        ocr_result_frame_sha256=page_source.sha256,
        ocr_result_capture_completed_monotonic=page_source.captured_monotonic,
        ocr_reused=False,
        source_family="ALLIANCE_SHOP",
        target_isolated=True,
        forbidden_region_intersects_target=False,
        package_foreground=runtime.measure_foreground_package() == "com.global.ztmslg",
        os_surface=False,
        hard_stop_detected=False,
    )
    preconditions = (
        f"shop={shop}",
        f"item={subject}",
        "currency=ALLIANCE_COINS",
        f"unit_price={offer.unit_price}",
        f"stock={offer.stock}",
        f"balance={offer.balance}",
        "quantity=1",
        f"total={offer.unit_price}",
        f"alliance_shop_reset_id={context.identity.reset_id}",
        "alliance_shop_action_ordinal=1",
        "alliance_shop_action_count_before=0",
        "alliance_shop_action_limit=1",
    )
    request = PolicyRequest(
        action_id=hashlib.sha256(f"{action_key}:alliance-shop".encode()).hexdigest(),
        action_key=action_key,
        task_id=FLOW_ID,
        task_mode="supervised_validation",
        semantic_action="PURCHASE_ALLIANCE_SHOP_OFFER",
        expected_runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        observation=source_observation,
        monotonic_now=context.monotonic_clock(),
        observation_max_age_seconds=30.0,
        dispatch_max_age_seconds=10.0,
        lease_owner=context.owner,
        lease_valid=store.lease_valid_for(context.owner, context.utc_clock()),
        unresolved_action=store.has_action_block(),
        duplicate_action_key=store.get_action_by_key(action_key) is not None,
        game_day_id=context.identity.reset_id,
        action_class=ActionClass.SPEND_OR_STRATEGIC,
        action_kind="alliance_shop_purchase-v2",
        subject=subject,
        resource_or_currency="ALLIANCE_COINS",
        maximum_cost=offer.unit_price,
        free_only=False,
        allowed_confirmation_dialogs=(source_state,),
        semantic_preconditions=preconditions,
        semantic_postconditions=(postcondition,),
        runtime_session_id=str(session.session_directory),
    )
    policy = CentralPolicy({FLOW_ID})
    issued = policy.issue_capability(request)
    store.audit(FLOW_ID, "capability_issued", context.utc_clock(), issued.audit, request.action_id)
    if not issued.authorized or issued.capability is None:
        return PurchaseEffect(
            "blocked", None, False, 0, None, None, None, "", "", False,
            action_key=action_key, reason=issued.reason_code,
        )
    offer_source = port.offer_evidence.get(offer.item_identity)
    frames = {"current": page_source, "offer_source": offer_source}
    effect_data: dict[str, Any] = {}

    def as_observation(captured, *, source, roi, positive=False):
        if source == postcondition:
            digest = hashlib.sha256(captured.frame.tobytes()).hexdigest()
            bound_target, bound_roi = None, None
        else:
            left, top, right, bottom = roi
            digest = hashlib.sha256(captured.frame[top:bottom, left:right].tobytes()).hexdigest()
            bound_target, bound_roi = (target_identity, roi) if positive else (None, None)
        return Observation(
            frame_sha256=captured.sha256,
            capture_completed_monotonic=captured.captured_monotonic,
            runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
            width=800,
            height=1280,
            valid_png=captured.frame.shape == (1280, 800, 3),
            corrupt=False,
            black=not bool(np.any(captured.frame)),
            source_state=source,
            overlay_state="none",
            target_identity=bound_target,
            target_roi=bound_roi,
            recognized=positive,
            clipped=False,
            ambiguous=not positive,
            control_class="BUY" if bound_target else None,
            consequence="alliance_shop_purchase" if positive else None,
            cost_type="ALLIANCE_COINS" if positive else None,
            cost_amount=offer.unit_price if positive else None,
            quantity=1 if positive else None,
            expected_postcondition=postcondition if positive else None,
            evidence_refs=tuple(dict.fromkeys(
                str(value.path) for value in frames.values() if value is not None
            )) + ((str(captured.path),) if str(captured.path) not in {
                str(value.path) for value in frames.values() if value is not None
            } else ()),
            critical_roi_hashes=(("alliance-shop-effect", digest),),
            ocr_result_frame_sha256=captured.sha256,
            ocr_result_capture_completed_monotonic=captured.captured_monotonic,
            source_family="ALLIANCE_SHOP",
            target_isolated=bound_target is not None,
            package_foreground=runtime.measure_foreground_package() == "com.global.ztmslg",
        )

    def recapture():
        captured = port._capture("alliance-shop-inner-buy-immediate-before")
        current = port._quantity_dialog(captured, offer)
        if current is None or (
            current.selected_quantity != 1 or current.total != offer.unit_price
            or current.inner_buy_roi is None
        ):
            return Observation(
                frame_sha256=captured.sha256, capture_completed_monotonic=captured.captured_monotonic,
                runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID, width=800, height=1280,
                valid_png=captured.frame.shape == (1280, 800, 3), corrupt=False,
                black=not bool(np.any(captured.frame)), source_state=source_state,
                overlay_state="none", recognized=False, ambiguous=True,
                evidence_refs=(str(captured.path),), ocr_result_frame_sha256=captured.sha256,
                ocr_result_capture_completed_monotonic=captured.captured_monotonic,
                package_foreground=runtime.measure_foreground_package() == "com.global.ztmslg",
            )
        frames["current"] = captured
        roi = current.inner_buy_roi
        left, top, right, bottom = roi
        return Observation(
            frame_sha256=captured.sha256, capture_completed_monotonic=captured.captured_monotonic,
            runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID, width=800, height=1280,
            valid_png=captured.frame.shape == (1280, 800, 3), corrupt=False,
            black=not bool(np.any(captured.frame)), source_state=source_state,
            overlay_state="none", target_identity=target_identity, target_roi=roi,
            recognized=True, clipped=False, ambiguous=False, control_class="BUY",
            consequence="alliance_shop_purchase", cost_type="ALLIANCE_COINS",
            cost_amount=offer.unit_price, quantity=1, expected_postcondition=postcondition,
            evidence_refs=(str(captured.path),),
            critical_roi_hashes=(("inner-buy", hashlib.sha256(captured.frame[top:bottom, left:right].tobytes()).hexdigest()),),
            ocr_result_frame_sha256=captured.sha256,
            ocr_result_capture_completed_monotonic=captured.captured_monotonic,
            source_family="ALLIANCE_SHOP", target_isolated=True,
            package_foreground=runtime.measure_foreground_package() == "com.global.ztmslg",
        )

    def transport(intent):
        captured = frames["current"]
        runtime.tap(
            captured, target_identity=target_identity,
            target_roi=intent.target_roi, action_key=action_key,
            action_class=ActionClass.SPEND_OR_STRATEGIC.value, consequential=True,
        )
        return TransportResult(True, "ALLIANCE_INNER_BUY_DISPATCHED")

    def post_observe():
        for ordinal in range(1, 4):
            context.checkpoint()
            if settle_seconds:
                time.sleep(settle_seconds)
            captured = port._capture(f"alliance-shop-purchase-post-{ordinal}")
            page = port._page(captured)[0]
            after = port._read_offer(captured, offer.item_identity, offer.shop_identity, offer.rarity)
            matched = bool(
                page == port.current_tab
                and after is not None
                and after.currency_identity == offer.currency_identity
                and after.balance == offer.balance - offer.unit_price
                and after.stock == offer.stock - 1
                and after.item_quantity == offer.item_quantity + 1
            )
            frames["shop_successor"] = captured
            if after is not None:
                effect_data.update(
                    currency_after=after.balance,
                    stock_after=after.stock,
                    item_quantity_after=after.item_quantity,
                    item_identity_after=after.item_identity,
                    currency_identity_after=after.currency_identity,
                    tab_successor_verified=page == port.current_tab,
                    shop_successor=captured,
                    paired_effect_verified=matched,
                )
            if matched:
                home_ok = port.return_home()
                home_frame = port._capture("alliance-shop-purchase-terminal-home")
                home_ok = bool(home_ok and port._home(home_frame))
                effect_data["terminal_home_verified"] = home_ok
                effect_data["home_frame"] = home_frame
                roi = _hits(port._words(captured), offer.item_identity)[0]
                yield as_observation(
                    home_frame,
                    source=postcondition if home_ok else "ALLIANCE_SHOP_HOME_NOT_VERIFIED",
                    roi=roi,
                    positive=home_ok,
                )
                return
            roi_hits = _hits(port._words(captured), offer.item_identity)
            roi = roi_hits[0] if len(roi_hits) == 1 else (0, 0, 1, 1)
            yield as_observation(
                captured, source="ALLIANCE_SHOP_EFFECT_NOT_RECONCILED",
                roi=roi, positive=False,
            )

    def reconcile(_intent, observed):
        return bool(
            observed.source_state == postcondition
            and effect_data.get("paired_effect_verified") is True
            and effect_data.get("tab_successor_verified") is True
            and effect_data.get("terminal_home_verified") is True
        )

    execution = SafeActionExecutor(
        store, policy, context.owner, context.monotonic_clock, transport,
        recapture, post_observe, reconcile, wall_clock=context.utc_clock,
        max_pre_dispatch_attempts=1,
    ).execute(request, issued.capability)
    action = store.get_action_by_key(action_key)
    dispatched = action_key in runtime.action_keys
    terminal_status = str(action.get("final_status") if action else "unresolved")
    if execution.status.value == "confirmed" and action and action.get("final_status") == "confirmed":
        context.validate_identity()
        try:
            runtime.reconcile(
                action_key, "confirmed", effect_data["home_frame"],
                "exact Alliance item, Alliance Coin, tab and Home deltas verified",
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            pass
    return PurchaseEffect(
        "confirmed" if terminal_status == "confirmed" else "unresolved" if terminal_status in {"input_sent", "unresolved"} else "blocked",
        terminal_status,
        dispatched,
        int(dispatched),
        effect_data.get("currency_after"),
        effect_data.get("stock_after"),
        effect_data.get("item_quantity_after"),
        effect_data.get("item_identity_after", ""),
        effect_data.get("currency_identity_after", ""),
        bool(effect_data.get("tab_successor_verified")),
        effect_reconciliation_required=terminal_status in {"input_sent", "unresolved"},
        identical_retry_denied=dispatched or terminal_status not in {"cancelled"},
        action_key=action_key,
        reason=execution.reason,
    )


def _service_driver(context, arguments: Mapping[str, object]) -> Mapping[str, object]:
    from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID

    context.validate_identity()
    source = context.session.observe(context.runtime.capture, label="alliance-shop-canonical-home-source")
    if not context.is_clean_home(source.frame):
        return {
            "status": "blocked",
            "reason": "ALLIANCE_CANONICAL_HOME_NOT_RECOGNIZED",
            "purchase_transport_calls": 0,
            "committed_action_count": 0,
            "accounting_verified": False,
            "terminal_home_verified": False,
            "effect_reconciliation_required": False,
            "identical_retry_denied": False,
            "input_count": 0,
            "total_input_count": 0,
        }
    context.bind_initial_observation(source, extra={"source_state": "HOME_BASE", "home_verified": True})
    action_key = arguments.get("action_key")
    if not isinstance(action_key, str) or not action_key:
        raise ValueError("Alliance Shop canonical action key is missing")
    port = AllianceShopLivePort(context, settle_seconds=float(arguments.get("settle_seconds", 1.0)))
    try:
        result = run_alliance_shop_route(port, action_key=action_key)
    finally:
        context.session.adopt_retained_transport_count(
            context.runtime.input_count, source=str(context.runtime.events),
        )
    accounting = context.accounting()
    context.validate_identity()
    input_count = accounting.input_count
    result.update(
        account_id=context.identity.account_id,
        server_id=context.identity.server_id,
        reset_id=context.identity.reset_id,
        occurrence_key=context.occurrence_key,
        runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        input_count=input_count,
        total_input_count=input_count,
        accounting_verified=bool(
            accounting.verified and input_count <= MAX_INPUTS
            and result.get("purchase_transport_calls", 0) <= 1
            and result.get("committed_action_count", 0) <= 1
        ),
        source_frame={
            "frame_path": source.path.relative_to(context.session.session_directory).as_posix(),
            "frame_sha256": source.sha256,
        },
        session_directory=str(context.session.session_directory),
    )
    return result


def create_service_binding(make_native_route_binding):
    from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID

    return make_native_route_binding(
        flow_id=FLOW_ID,
        product_id=PRODUCT_ID,
        product_revision=PRODUCT_REVISION,
        runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        owner="automation-service:alliance-shop",
        workflow="alliance-shop-native",
        max_inputs=MAX_INPUTS,
        max_actions=1,
        driver=_service_driver,
        lease_seconds=3600.0,
    )
