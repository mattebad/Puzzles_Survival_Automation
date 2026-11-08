"""One bounded visit to Ruins Shop and Rare Earth Shop with independent tab outcomes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from automation_service.registry import (
    DAILY_SHOPS_FLOW_ID as FLOW_ID,
    DAILY_SHOPS_MAX_INPUTS as MAX_INPUTS,
    DAILY_SHOPS_PRODUCT_ID as PRODUCT_ID,
    DAILY_SHOPS_PRODUCT_REVISION as PRODUCT_REVISION,
)
from tasks.purchases_disabled import (
    RARE_EARTH_SHOP,
    RUINS_SHOP,
    ShopOffer,
    daily_shop_quantity,
    purchase_dialog_matches,
    purchase_effect_verified,
)


RUINS_TAB = "ruins"
RARE_EARTH_TAB = "rare_earth"
TABS = (RUINS_TAB, RARE_EARTH_TAB)
MAX_ACTIONS = 2


@dataclass(frozen=True)
class TabOffer:
    offer: ShopOffer | None
    complete: bool
    reason: str = ""
    evidence_ref: str = ""
    evidence_frame_sha256: str = ""

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


class DailyShopsPort(Protocol):
    """Bounded current-frame operations and canonical per-tab action records."""

    def action_status(self, action_key: str) -> str | None: ...
    def enter_ruins_shop(self) -> bool: ...
    def inspect_tab(self, tab: str) -> TabOffer: ...
    def open_quantity_dialog(self, tab: str, offer: ShopOffer) -> QuantityDialog | None: ...
    def select_quantity(
        self, tab: str, offer: ShopOffer, quantity: int, dialog: QuantityDialog,
    ) -> QuantityDialog | None: ...
    def cancel_quantity_dialog(self) -> bool: ...
    def purchase(
        self, tab: str, offer: ShopOffer, dialog: QuantityDialog, action_key: str,
    ) -> PurchaseEffect: ...
    def switch_to_rare_earth(self) -> bool: ...
    def return_home(self) -> bool: ...


@dataclass
class DailyShopsRouteResult:
    status: str = "blocked"
    reason: str = "DAILY_SHOPS_ROUTE_NOT_STARTED"
    flow_id: str = FLOW_ID
    task_id: str = PRODUCT_ID
    product_revision: str = PRODUCT_REVISION
    purchase_transport_calls: int = 0
    committed_action_count: int = 0
    accounting_verified: bool = False
    terminal_home_verified: bool = False
    effect_reconciliation_required: bool = False
    identical_retry_denied: bool = False
    tab_results: dict[str, dict[str, Any]] | None = None
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
            "accounting_verified": self.accounting_verified,
            "terminal_home_verified": self.terminal_home_verified,
            "effect_reconciliation_required": self.effect_reconciliation_required,
            "identical_retry_denied": self.identical_retry_denied,
            "tab_results": dict(self.tab_results or {}),
            "home_return_attempted": self.home_return_attempted,
            "home_returned": self.home_returned,
        }


class DailyShopsPurchaseRoute:
    """Handle both exact tabs once, preserving independent results across restart."""

    max_inputs = MAX_INPUTS
    max_actions = 2

    def __init__(self, port: DailyShopsPort, *, action_keys: Mapping[str, str]) -> None:
        if set(action_keys) != set(TABS) or any(
            not isinstance(value, str) or not value.strip() for value in action_keys.values()
        ):
            raise ValueError("Daily Shops requires one canonical action key per tab")
        self.port = port
        self.action_keys = dict(action_keys)
        self.result = DailyShopsRouteResult(tab_results={})
        self._effects: dict[str, tuple[ShopOffer, QuantityDialog, PurchaseEffect, int]] = {}

    def _tab_result(self, tab: str, *, status: str, reason: str,
                    offer: ShopOffer | None = None, quantity: int = 0,
                    total: int | None = None, source_ref: str = "",
                    source_hash: str = "", effect_verified: bool = False) -> None:
        self.result.tab_results[tab] = {
            "status": status,
            "reason": reason,
            "quantity": quantity,
            "total": total,
            "offer_identity": offer.offer_identity if offer else None,
            "shop_identity": offer.shop_identity if offer else None,
            "item_identity": offer.item_identity if offer else None,
            "currency_identity": offer.currency_identity if offer else None,
            "rarity": offer.rarity if offer else None,
            "unit_price": offer.unit_price if offer else None,
            "balance_before": offer.balance if offer else None,
            "stock_before": offer.stock if offer else None,
            "item_quantity_before": offer.item_quantity if offer else None,
            "source_frame_ref": source_ref,
            "source_frame_sha256": source_hash,
            "effect_verified": effect_verified,
            "action_key": self.action_keys[tab],
        }

    def _process_tab(self, tab: str) -> bool:
        """Return False only when a consequential effect is unresolved/unknown."""
        action_key = self.action_keys[tab]
        prior = self.port.action_status(action_key)
        if prior == "confirmed":
            self._tab_result(
                tab, status="already_confirmed",
                reason="TAB_OCCURRENCE_ALREADY_CONFIRMED",
                effect_verified=True,
            )
            return True
        if prior not in {None, "cancelled"}:
            self._tab_result(
                tab, status="unresolved",
                reason="TAB_CANONICAL_ACTION_REQUIRES_RECONCILIATION",
            )
            self.result.effect_reconciliation_required = True
            self.result.identical_retry_denied = True
            return False

        observation = self.port.inspect_tab(tab)
        if not observation.complete:
            self._tab_result(
                tab, status="blocked", reason=observation.reason or "TAB_OFFER_INCOMPLETE",
                source_ref=observation.evidence_ref, source_hash=observation.evidence_frame_sha256,
            )
            return True
        offer = observation.offer
        if offer is None:
            self._tab_result(
                tab, status="deferred", reason=observation.reason or "TAB_OFFER_NOT_AVAILABLE",
                source_ref=observation.evidence_ref, source_hash=observation.evidence_frame_sha256,
            )
            return True
        shop = RUINS_SHOP if tab == RUINS_TAB else RARE_EARTH_SHOP
        quantity = daily_shop_quantity(offer, shop_identity=shop)
        if quantity is None:
            self._tab_result(
                tab, status="blocked", reason="TAB_ITEM_OR_COST_NOT_ALLOWLISTED",
                offer=offer, source_ref=observation.evidence_ref,
                source_hash=observation.evidence_frame_sha256,
            )
            return True
        if quantity == 0:
            self._tab_result(
                tab, status="deferred", reason="TAB_NO_AFFORDABLE_STOCK",
                offer=offer, quantity=0, source_ref=observation.evidence_ref,
                source_hash=observation.evidence_frame_sha256,
            )
            return True

        dialog = self.port.open_quantity_dialog(tab, offer)
        if (
            dialog is None
            or not dialog.recognized
            or dialog.shop_identity != offer.shop_identity
            or dialog.item_identity != offer.item_identity
            or dialog.currency_identity != offer.currency_identity
            or dialog.unit_price != offer.unit_price
        ):
            if dialog is not None:
                self.port.cancel_quantity_dialog()
            self._tab_result(
                tab, status="blocked", reason="TAB_QUANTITY_DIALOG_NOT_EXACT",
                offer=offer, quantity=quantity, source_ref=observation.evidence_ref,
                source_hash=observation.evidence_frame_sha256,
            )
            return True
        selected = self.port.select_quantity(tab, offer, quantity, dialog)
        if (
            selected is None
            or not selected.recognized
            or selected.shop_identity != offer.shop_identity
            or selected.item_identity != offer.item_identity
            or selected.currency_identity != offer.currency_identity
            or selected.unit_price != offer.unit_price
            or selected.inner_buy_roi is None
            or not purchase_dialog_matches(
                offer,
                quantity=quantity,
                selected_quantity=selected.selected_quantity,
                displayed_total=selected.total,
                shop_identity=offer.shop_identity,
            )
        ):
            self.port.cancel_quantity_dialog()
            self._tab_result(
                tab, status="blocked", reason="TAB_NUMERIC_QUANTITY_OR_TOTAL_NOT_EXACT",
                offer=offer, quantity=quantity, source_ref=observation.evidence_ref,
                source_hash=observation.evidence_frame_sha256,
            )
            return True

        effect = self.port.purchase(tab, offer, selected, action_key)
        self.result.purchase_transport_calls += effect.purchase_transport_calls
        self.result.effect_reconciliation_required |= effect.effect_reconciliation_required
        self.result.identical_retry_denied |= effect.identical_retry_denied
        if effect.status != "confirmed" or effect.journal_status != "confirmed":
            self._tab_result(
                tab,
                status="unresolved" if effect.effect_reconciliation_required else "blocked",
                reason=effect.reason or "TAB_PURCHASE_NOT_CONFIRMED",
                offer=offer, quantity=quantity, total=selected.total,
                source_ref=observation.evidence_ref, source_hash=observation.evidence_frame_sha256,
            )
            return not effect.effect_reconciliation_required
        self.result.committed_action_count += 1
        self._effects[tab] = (offer, selected, effect, quantity)
        self._tab_result(
            tab, status="confirmed", reason="TAB_ITEM_CURRENCY_AND_SUCCESSOR_CONFIRMED",
            offer=offer, quantity=quantity, total=selected.total,
            source_ref=observation.evidence_ref, source_hash=observation.evidence_frame_sha256,
        )
        return True

    def run(self) -> DailyShopsRouteResult:
        if not self.port.enter_ruins_shop():
            self.result.reason = getattr(
                self.port, "entry_reason", ""
            ) or "RUINS_SHOP_HOME_ATLAS_PATH_NOT_VERIFIED"
            self.result.home_return_attempted = True
            self.result.home_returned = self.port.return_home()
            self.result.terminal_home_verified = self.result.home_returned
            return self.result

        proceed = self._process_tab(RUINS_TAB)
        if proceed:
            if self.port.switch_to_rare_earth():
                proceed = self._process_tab(RARE_EARTH_TAB)
            else:
                self._tab_result(
                    RARE_EARTH_TAB, status="blocked",
                    reason="RARE_EARTH_TAB_SUCCESSOR_NOT_VERIFIED",
                )
        self.result.home_return_attempted = True
        self.result.home_returned = self.port.return_home()
        self.result.terminal_home_verified = self.result.home_returned

        for tab, (offer, dialog, effect, quantity) in self._effects.items():
            proved = purchase_effect_verified(
                offer,
                quantity=quantity,
                selected_quantity=dialog.selected_quantity,
                displayed_total=dialog.total,
                currency_after=effect.currency_after,
                stock_after=effect.stock_after,
                item_quantity_after=effect.item_quantity_after,
                item_identity_after=effect.item_identity_after,
                currency_identity_after=effect.currency_identity_after,
                tab_successor_verified=effect.tab_successor_verified,
                terminal_home_verified=self.result.terminal_home_verified,
                inner_buy_dispatched=effect.inner_buy_dispatched,
            )
            tab_result = self.result.tab_results[tab]
            tab_result["effect_verified"] = proved
            if not proved:
                tab_result.update(status="unresolved", reason="ITEM_CURRENCY_TAB_HOME_RECONCILIATION_FAILED")
                self.result.effect_reconciliation_required = True
                self.result.identical_retry_denied = True

        statuses = [row["status"] for row in self.result.tab_results.values()]
        if not self.result.home_returned:
            self.result.status = "blocked"
            self.result.reason = "DAILY_SHOPS_CANONICAL_HOME_NOT_VERIFIED"
        elif self.result.effect_reconciliation_required or "unresolved" in statuses:
            self.result.status = "unresolved"
            self.result.reason = "DAILY_SHOPS_PURCHASE_EFFECT_REQUIRES_RECONCILIATION"
        elif any(not row.get("effect_verified") for row in self.result.tab_results.values()
                 if row["status"] in {"confirmed", "already_confirmed"}):
            self.result.status = "blocked"
            self.result.reason = "DAILY_SHOPS_CONFIRMED_EFFECT_PROOF_MISSING"
        elif "blocked" in statuses:
            self.result.status = "deferred" if self.result.committed_action_count else "blocked"
            self.result.reason = "DAILY_SHOPS_TAB_BLOCKED_INDEPENDENT_RESULT_RETAINED"
        elif "deferred" in statuses:
            self.result.status = "deferred"
            self.result.reason = "DAILY_SHOPS_AVAILABLE_TAB_RESULTS_RECONCILED"
        else:
            self.result.status = "completed" if self.result.committed_action_count else "already_complete"
            self.result.reason = "DAILY_SHOPS_BOTH_TAB_OCCURRENCES_RECONCILED"
        self.result.accounting_verified = bool(
            self.result.home_returned
            and self.result.purchase_transport_calls <= 2
            and self.result.committed_action_count <= 2
            and self.result.purchase_transport_calls >= self.result.committed_action_count
            and not self.result.effect_reconciliation_required
            and all(row["status"] not in {"unresolved"} for row in self.result.tab_results.values())
        )
        return self.result


def run_daily_shops_route(
    port: DailyShopsPort, *, action_keys: Mapping[str, str],
) -> dict[str, Any]:
    """Entry point for the fixed native bridge and deterministic replay tests."""

    return DailyShopsPurchaseRoute(port, action_keys=action_keys).run().to_mapping()
class DailyShopsLivePort:
    """Mapped Ruins entry, exact current-frame shop binding and paired purchase proof."""

    def __init__(self, context, *, action_keys: Mapping[str, str], settle_seconds: float):
        self.context, self.session, self.runtime = context, context.session, context.runtime
        self.action_keys = dict(action_keys)
        self.settle_seconds = float(settle_seconds)
        self.current_tab = ""
        self.currency_icons = {}
        self.last_offer_capture = None
        self.last_dialog = None
        self.backend_identity = None
        self._home_atlas = None
        self._home_localizer = None
        self.entry_reason = ""

    def _capture(self, label):
        self.context.checkpoint()
        return self.session.observe(self.runtime.capture, label=label)

    def _ocr(self, captured):
        return self._ocr_region(captured.frame)

    @staticmethod
    def _ocr_region(frame, roi=None, *, psm=6):
        from scripts.bounded_tesseract import call_ocr, tesseract_data
        left, top, right, bottom = roi or (0, 0, 800, 1280)
        data = call_ocr(tesseract_data, frame[top:bottom, left:right], config=f"--psm {psm}")
        groups = {}
        for i, text in enumerate(data.get("text", ())):
            value = str(text).strip()
            try:
                if float(data["conf"][i]) < 35:
                    continue
                roi = (
                    left + int(data["left"][i]), top + int(data["top"][i]),
                    left + int(data["left"][i]) + int(data["width"][i]),
                    top + int(data["top"][i]) + int(data["height"][i]),
                )
                line = (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]))
            except (KeyError, ValueError, TypeError, IndexError):
                continue
            if value and 0 <= roi[0] < roi[2] <= 800 and 0 <= roi[1] < roi[3] <= 1280:
                groups.setdefault(line, []).append((value, roi))
        return tuple(tuple(sorted(row, key=lambda value: value[1][0])) for _, row in sorted(groups.items()))

    @staticmethod
    def _norm(value):
        import re
        return re.sub(r"[^0-9a-z★]+", "", value.casefold().replace("*", "★").replace("☆", "★"))

    def _hits(self, lines, phrase):
        expected = tuple(self._norm(value) for value in phrase.split())
        found = []
        for line in lines:
            words = tuple(self._norm(value[0]) for value in line)
            for start in range(len(words) - len(expected) + 1):
                if words[start:start + len(expected)] == expected:
                    selected = line[start:start + len(expected)]
                    boxes = [item[1] for item in selected]
                    found.append((min(v[0] for v in boxes), min(v[1] for v in boxes),
                                  max(v[2] for v in boxes), max(v[3] for v in boxes)))
        return found

    @staticmethod
    def _numbers(line):
        import re
        values = []
        for text, roi in line:
            for match in re.finditer(r"(?<![A-Za-z])\d[\d,]*(?![A-Za-z])", text):
                token = match.group().replace(",", "")
                if token.isascii() and token.isdecimal():
                    values.append((int(token), roi))
        return values

    @staticmethod
    def _icon(captured, roi):
        import cv2
        import numpy as np
        x, y = roi[0], (roi[1] + roi[3]) // 2
        left, top, right, bottom = max(0, x - 130), max(0, y - 28), x, min(1280, y + 29)
        if right - left < 20 or bottom - top < 20:
            return None
        patch = captured.frame[top:bottom, left:right]
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array((0, 75, 55), dtype=np.uint8),
                           np.array((179, 255, 255), dtype=np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), dtype=np.uint8))
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask)
        candidates = []
        for index in range(1, count):
            cx, cy, width, height, area = map(int, stats[index])
            if (14 <= width <= 54 and 14 <= height <= 54 and 100 <= area <= 1800
                    and left + cx + width <= x):
                candidates.append((x - (left + cx + width), cx, cy, width, height))
        if not candidates:
            return None
        nearest = min(value[0] for value in candidates)
        choices = [value for value in candidates if value[0] <= nearest + 12]
        if len(choices) != 1:
            return None
        _distance, cx, cy, width, height = choices[0]
        x0, y0 = max(0, cx - 8), max(0, cy - 8)
        x1, y1 = min(patch.shape[1], cx + width + 8), min(patch.shape[0], cy + height + 8)
        glyph = patch[y0:y1, x0:x1]
        return cv2.resize(cv2.cvtColor(glyph, cv2.COLOR_BGR2GRAY), (32, 32))

    @classmethod
    def _icons_match(cls, first, second):
        import numpy as np
        if first is None or second is None or first.shape != second.shape:
            return False
        a, b = first.astype(np.float32), second.astype(np.float32)
        a -= a.mean()
        b -= b.mean()
        length = float(np.linalg.norm(a) * np.linalg.norm(b))
        return length > 1e-6 and float(np.sum(a * b) / length) >= 0.86

    def _page(self, captured):
        lines = self._ocr(captured)
        if self._hits(lines, "3★ Chip Enhance Material"):
            return "ruins", lines
        if self._hits(lines, "3★ Module Enhance Material"):
            return "rare_earth", lines
        if self._hits(lines, "Ruins Challenge") and self._hits(lines, "Exchange"):
            return "ruins_challenge", lines
        from tasks.ruins_challenge_vision import (
            RUINS_OVERVIEW_CONTROLS_ROI, RUINS_OVERVIEW_HEADER_ROI,
        )
        navigation = (
            self._ocr_region(captured.frame, RUINS_OVERVIEW_HEADER_ROI, psm=7)
            + self._ocr_region(captured.frame, RUINS_OVERVIEW_CONTROLS_ROI)
        )
        if self._hits(navigation, "Ruins Challenge") and self._hits(navigation, "Exchange"):
            body = tuple(line for line in lines if all(word[1][1] >= 210 for word in line))
            return "ruins_challenge", navigation + body
        if self.context.is_clean_home(captured.frame):
            return "home", lines
        return "unknown", lines

    def _tap(self, captured, roi, target_identity, action_key, recognize):
        if roi is None or len(roi) != 4 or not (0 <= roi[0] < roi[2] <= 800 and 0 <= roi[1] < roi[3] <= 1280):
            return False
        self.context.checkpoint()
        self.runtime.tap(captured, target_identity=target_identity, target_roi=roi, action_key=action_key)
        successor = self._capture(f"daily-shops-{target_identity.replace(':', '-')}-successor")
        if recognize(successor):
            return True
        if self.settle_seconds:
            import time
            time.sleep(self.settle_seconds)
        return bool(recognize(self._capture(f"daily-shops-{target_identity.replace(':', '-')}-settled")))

    def _tap_text(self, label, target_identity, recognize):
        before = self._capture(f"daily-shops-{label.replace(' ', '-')}-source")
        _page, lines = self._page(before)
        matches = self._hits(lines, label)
        if len(matches) != 1:
            return False
        return self._tap(
            before, matches[0], target_identity,
            f"daily-shops:{target_identity}:{before.sha256}",
            lambda after: bool(recognize(after)),
        )

    def _home_mapping(self):
        from pathlib import Path
        from tasks.home_atlas import load_home_atlas
        from tasks.home_atlas_vision import BlueStacksHomeLocalizer
        if self._home_atlas is None or self._home_localizer is None:
            atlas_path = Path(__file__).resolve().parents[1] / "tasks/assets/home_atlas/bluestacks/800x1280/atlas.json"
            self._home_atlas = load_home_atlas(atlas_path)
            self._home_localizer = BlueStacksHomeLocalizer(self._home_atlas, atlas_path)
        return self._home_atlas, self._home_localizer

    def _mapped_ruins(self, frame):
        from tasks.home_atlas_vision import bind_visible_building, frame_digest
        atlas, localizer = self._home_mapping()
        localization = localizer.localize(frame)
        binding = bind_visible_building(
            frame, localization, atlas.lookup_building("home.building.ruins"),
            home_is_clean=self.context.is_clean_home,
        )
        # Atlas bindings use the decoded-frame semantic digest, not the native
        # capture's transport PNG digest. The SDK deliberately keeps both.
        if (binding is None or binding.frame_sha256 != frame_digest(frame)
                or binding.overlay_intersects or binding.ambiguous_overlap):
            return None
        return binding


    def _normalize_home_zoom(self):
        from pathlib import Path
        from scripts.atlas_runtime_startup import normalize_runtime_home_atlas_startup
        remaining = min(MAX_INPUTS, self.context.max_inputs) - self.runtime.input_count
        if remaining <= 0:
            self.entry_reason = "DAILY_SHOPS_ENTRY_INPUT_BUDGET_EXHAUSTED"
            return None
        atlas, _localizer = self._home_mapping()
        atlas_path = Path(__file__).resolve().parents[1] / "tasks/assets/home_atlas/bluestacks/800x1280/atlas.json"
        try:
            self._home_localizer, _records = normalize_runtime_home_atlas_startup(
                runtime=self.runtime, atlas=atlas, atlas_path=atlas_path,
                execute=self.runtime.execute, settle_seconds=self.settle_seconds,
                maximum_zoom_inputs=min(2, remaining),
            )
            return self._capture("daily-shops-home-zoom-normalized")
        except RuntimeError as exc:
            self.entry_reason = f"DAILY_SHOPS_ENTRY_DEFERRED:{exc}"
            return None

    def _open_ruins_shop(self):
        from scripts.home_atlas_bluestacks import bind_or_pan_mapped_home_building
        self.entry_reason = ""
        home = self._capture("daily-shops-ruins-home-source")
        if not self.context.is_clean_home(home.frame):
            self.entry_reason = "DAILY_SHOPS_ENTRY_REQUIRES_CLEAN_HOME"
            return False
        home = self._normalize_home_zoom()
        if home is None:
            return False
        atlas, localizer = self._home_mapping()
        home, binding, reason = bind_or_pan_mapped_home_building(
            self.context, current=home, atlas=atlas, localizer=localizer,
            building_id="home.building.ruins", product_id=PRODUCT_ID,
            binding_for_frame=self._mapped_ruins, maximum_pans=8,
        )
        if home is None or binding is None:
            self.entry_reason = f"DAILY_SHOPS_ENTRY_DEFERRED:{reason}"
            return False
        if not self._tap(
            home, tuple(binding.target_roi), "home.building.ruins",
            f"daily-shops:home-ruins:{home.sha256}",
            lambda after: self._page(after)[0] == "ruins_challenge",
        ):
            self.entry_reason = "DAILY_SHOPS_RUINS_OVERVIEW_NOT_VERIFIED"
            return False
        if not self._tap_text(
            "Exchange", "daily-shops:ruins-exchange",
            lambda after: self._page(after)[0] == "ruins",
        ):
            self.entry_reason = "DAILY_SHOPS_EXCHANGE_SUCCESSOR_NOT_VERIFIED"
            return False
        self.current_tab = "ruins"
        return True

    def enter_ruins_shop(self):
        self.backend_identity = getattr(self.context, "backend_identity", None)
        return self._open_ruins_shop()

    def _read_offer(self, captured, tab):
        self._owned_evidence_missing = False
        lines = self._ocr(captured)
        expected = {
            RUINS_TAB: (RUINS_SHOP, "3★ Chip Enhance Material", "Ruins Coins"),
            RARE_EARTH_TAB: (RARE_EARTH_SHOP, "3★ Module Enhance Material", "Rare Earth"),
        }[tab]
        shop, item, currency = expected
        item_hits = self._hits(lines, item)
        if len(item_hits) != 1:
            return None
        item_roi = item_hits[0]
        row_y = (item_roi[1] + item_roi[3]) / 2
        row_prices, stocks, owned_values = [], [], []
        for line in lines:
            text = " ".join(word[0] for word in line).casefold()
            y = sum((word[1][1] + word[1][3]) / 2 for word in line) / len(line)
            all_numbers = self._numbers(line)
            positive_numbers = [value for value in all_numbers if value[0] > 0]
            if "owned" in text and abs(y - row_y) <= 110 and len(all_numbers) == 1:
                owned_values.append(all_numbers[0][0])
            if "left" in text or "remaining" in text or "stock" in text:
                if abs(y - row_y) <= 150 and len(all_numbers) == 1:
                    stocks.append(all_numbers[0][0])
                continue
            if y <= 120 and len(all_numbers) == 1:
                continue
            if abs(y - row_y) <= 130 and len(positive_numbers) == 1 and any(
                phrase in text for phrase in ("buy", "refresh")
            ):
                row_prices.append((abs(y - row_y), positive_numbers[0]))
        row_prices.sort(key=lambda x: x[0])
        if (not row_prices or (len(row_prices) > 1 and row_prices[0][0] == row_prices[1][0])
                or len(set(stocks)) != 1 or len(set(owned_values)) > 1):
            return None
        price, price_roi = row_prices[0][1]
        price_icon = self._icon(captured, price_roi)
        balances = []
        for line in lines:
            for amount, roi in self._numbers(line):
                if roi[1] <= 115 and self._icons_match(price_icon, self._icon(captured, roi)):
                    balances.append(amount)
        if len(balances) != 1 or price_icon is None:
            return None
        self.currency_icons[tab] = price_icon
        # A Bag baseline alone cannot establish a purchase successor while remaining in this
        # shared shop. Without a current explicit Owned value, paired item proof is unavailable.
        if len(owned_values) != 1:
            self._owned_evidence_missing = not owned_values
            return None
        count = owned_values[0]
        stock = stocks[0]
        offer = ShopOffer(
            shop_identity=shop, item_identity=item, currency_identity=currency,
            unit_price=price, balance=balances[0], stock=stock,
            item_quantity=count, rarity=3, available=stock > 0,
            recognized=True, offer_identity=f"{tab}:{item}",
        )
        return offer

    def inspect_tab(self, tab):
        from scripts.daily_shops_bluestacks import TabOffer
        captured = self._capture(f"daily-shops-{tab}-offer-source")
        if self._page(captured)[0] != tab:
            return TabOffer(
                None, False, "EXACT_DAILY_SHOP_TAB_NOT_RECOGNIZED",
                str(captured.path), captured.sha256,
            )
        offer = self._read_offer(captured, tab)
        if offer is None:
            if self._owned_evidence_missing:
                return TabOffer(
                    None, True, "TAB_ITEM_EFFECT_EVIDENCE_REQUIRED",
                    str(captured.path), captured.sha256,
                )
            return TabOffer(
                None, False, "evidence_required:EXACT_DAILY_OFFER_OR_IN_SHOP_OWNED_PROOF_MISSING",
                str(captured.path), captured.sha256,
            )
        self.last_offer_capture = captured
        return TabOffer(offer, True, "", str(captured.path), captured.sha256)

    def action_status(self, action_key):
        import hashlib
        import json
        from pathlib import Path
        action = self.context.action_store.get_action_by_key(action_key)
        if action is None:
            return None
        tab = "ruins" if action_key == self.action_keys.get(RUINS_TAB) else "rare_earth"
        shop = "ruins_shop" if tab == RUINS_TAB else "rare_earth_shop"
        item = "3_star_chip_enhance_material" if tab == RUINS_TAB else "3_star_module_enhance_material"
        currency = "RUINS_COINS" if tab == RUINS_TAB else "RARE_EARTH"
        post = "RUINS_SHOP_PURCHASE_RECONCILED" if tab == RUINS_TAB else "RARE_EARTH_SHOP_PURCHASE_RECONCILED"
        target = "daily-shops:ruins:inner-buy" if tab == RUINS_TAB else "daily-shops:rare-earth:inner-buy"
        exact = {
            "action_key": action_key, "task_id": FLOW_ID,
            "semantic_action": "PURCHASE_DAILY_SHOP_MATERIAL",
            "target_identity": target, "game_day_id": self.context.identity.reset_id,
            "expected_postcondition": post, "cost_type": currency,
            "runtime_profile_id": self.context.runtime_profile_id,
        }
        if any(action.get(key) != value for key, value in exact.items()):
            return "unresolved"
        status = str(action.get("final_status") or "unresolved")
        if status == "cancelled":
            return status
        if status != "confirmed":
            return "unresolved"
        try:
            request = json.loads(action["policy_request_json"])
            observation = request["observation"]
            proof = json.loads(action["reconciliation_result_json"])
            refs = tuple(Path(value) for value in proof["evidence_refs"])
            tokens = tuple(request.get("semantic_preconditions", ()))
            price = int(tokens[4].removeprefix("unit_price="))
            stock = int(tokens[5].removeprefix("stock="))
            balance = int(tokens[6].removeprefix("balance="))
            quantity = int(tokens[7].removeprefix("quantity="))
            total = int(tokens[8].removeprefix("total="))
            source_state = (
                "RUINS_SHOP_QUANTITY_DIALOG" if tab == RUINS_TAB
                else "RARE_EARTH_SHOP_QUANTITY_DIALOG"
            )
            expected_tokens = (
                f"shop={shop}", f"item={item}", "rarity=3", f"currency={currency}",
                f"unit_price={price}", f"stock={stock}", f"balance={balance}",
                f"quantity={quantity}", f"total={total}",
                f"daily_shops_reset_id={self.context.identity.reset_id}",
                f"daily_shops_tab={shop}", "daily_shops_tab_action_ordinal=1",
                "daily_shops_tab_action_count_before=0", "daily_shops_tab_action_limit=1",
            )
            digest = proof["frame_sha256"]
            root = Path(request["runtime_session_id"]).resolve(strict=True)
            if (request.get("task_id") != FLOW_ID
                    or request.get("task_mode") != "supervised_validation"
                    or request.get("game_day_id") != self.context.identity.reset_id
                    or request.get("semantic_action") != "PURCHASE_DAILY_SHOP_MATERIAL"
                    or request.get("action_kind") != PRODUCT_REVISION
                    or request.get("action_class") != "spend_or_strategic"
                    or request.get("subject") != item
                    or request.get("resource_or_currency") != currency
                    or request.get("maximum_cost") != total
                    or request.get("free_only") is not False
                    or request.get("semantic_preconditions") != list(expected_tokens)
                    or request.get("semantic_postconditions") != [post]
                    or request.get("allowed_confirmation_dialogs") != [source_state]
                    or observation.get("source_state") != source_state
                    or observation.get("target_identity") != target
                    or observation.get("cost_type") != currency
                    or observation.get("cost_amount") != total
                    or observation.get("quantity") != quantity
                    or observation.get("expected_postcondition") != post
                    or action.get("quantity") != quantity
                    or action.get("cost_amount") != total
                    or price <= 0 or stock < quantity or balance < total
                    or total != price * quantity
                    or quantity != min(stock, balance // price)
                    or proof.get("confirmed") is not True
                    or not isinstance(digest, str) or len(digest) != 64
                    or len(refs) < 4):
                return "unresolved"
            retained = []
            for path in refs:
                if path.is_absolute() and not path.is_symlink():
                    resolved = path.resolve(strict=True)
                    if resolved.is_relative_to(root) and resolved.is_file():
                        retained.append(resolved)
            if len(set(retained)) != len(set(refs)):
                return "unresolved"
            terminal = [path for path in retained
                        if hashlib.sha256(path.read_bytes()).hexdigest() == digest]
            if len(terminal) != 1:
                return "unresolved"
            from scripts.startup_normalization import is_clean_home_frame
            import cv2
            terminal_frame = cv2.imread(str(terminal[0]), cv2.IMREAD_COLOR)
            if terminal_frame is None:
                return "unresolved"
            if not is_clean_home_frame(terminal_frame):
                # New one-visit receipts settle each action on its own exact shop successor.
                # Historical Home receipts remain read-only and retain duplicate prevention.
                from types import SimpleNamespace
                after_frame = SimpleNamespace(frame=terminal_frame)
                if self._page(after_frame)[0] != tab:
                    return "unresolved"
                after = self._read_offer(after_frame, tab)
                if after is None:
                    return "unresolved"
                paired = False
                for path in retained:
                    if path == terminal[0]:
                        continue
                    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
                    if frame is None:
                        continue
                    before_frame = SimpleNamespace(frame=frame)
                    if self._page(before_frame)[0] != tab:
                        continue
                    before = self._read_offer(before_frame, tab)
                    if (before is not None and before.unit_price == price
                            and before.stock == stock and before.balance == balance
                            and after.shop_identity == before.shop_identity
                            and after.item_identity == before.item_identity
                            and after.currency_identity == before.currency_identity
                            and after.balance == balance - total
                            and after.stock == stock - quantity
                            and after.item_quantity == before.item_quantity + quantity):
                        paired = True
                        break
                if not paired:
                    return "unresolved"
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, IndexError):
            return "unresolved"
        return "confirmed"
    def open_quantity_dialog(self, tab, offer):
        captured = self._capture(f"daily-shops-{tab}-outer-buy-source")
        item_hits, buy_hits = self._hits(self._ocr(captured), offer.item_identity), self._hits(self._ocr(captured), "Buy")
        if len(item_hits) != 1 or not buy_hits:
            return None
        y = (item_hits[0][1] + item_hits[0][3]) / 2
        ranked = sorted((abs((roi[1] + roi[3]) / 2 - y), roi) for roi in buy_hits)
        if ranked[0][0] > 140 or len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
            return None
        if not self._tap(
            captured, ranked[0][1], f"daily-shops:{tab}:outer-buy",
            f"daily-shops:{tab}:outer-buy:{captured.sha256}",
            lambda after: self._dialog(after, offer) is not None,
        ):
            return None
        dialog_frame = self._capture(f"daily-shops-{tab}-quantity-dialog")
        self.last_dialog = (tab, offer, dialog_frame)
        return self._dialog(dialog_frame, offer)

    def _dialog(self, captured, offer):
        import re
        lines = self._ocr(captured)
        if len(self._hits(lines, offer.item_identity)) != 1:
            return None
        totals = [line for line in lines if "total" in " ".join(word[0] for word in line).casefold()]
        quantity_rows = []
        for line in lines:
            if line in totals:
                continue
            text = " ".join(word[0] for word in line)
            match = re.search(r"(?<!\d)(\d[\d,]*)\s*/\s*(\d[\d,]*)(?!\d)", text)
            if match:
                quantity_rows.append((
                    int(match.group(1).replace(",", "")),
                    int(match.group(2).replace(",", "")),
                    line,
                ))
        if len(totals) != 1 or len(quantity_rows) != 1:
            return None
        numbers = self._numbers(totals[0])
        if len(numbers) not in {1, 2}:
            return None
        total = numbers[0][0]
        if len(numbers) == 2 and numbers[1][0] != offer.balance:
            return None
        if not self._icons_match(self.currency_icons.get(RUINS_TAB if offer.shop_identity == RUINS_SHOP else RARE_EARTH_TAB),
                                 self._icon(captured, numbers[0][1])):
            return None
        quantity, cap, qline = quantity_rows[0]
        target = daily_shop_quantity(offer, shop_identity=offer.shop_identity)
        if cap != target or total != quantity * offer.unit_price:
            return None
        qy = sum((word[1][1] + word[1][3]) / 2 for word in qline) / len(qline)
        buys = [roi for roi in self._hits(lines, "Buy") if (roi[1] + roi[3]) / 2 > qy]
        if not buys:
            return None
        buy_roi = max(buys, key=lambda roi: roi[1])
        from scripts.daily_shops_bluestacks import QuantityDialog
        return QuantityDialog(
            offer.shop_identity, offer.item_identity, offer.currency_identity,
            offer.unit_price, quantity, total, buy_roi, True,
        )

    def _slider_track(self, captured, dialog):
        import cv2
        import numpy as np
        import re
        lines = self._ocr(captured)
        quantity_hits = []
        for line in lines:
            text = " ".join(word[0] for word in line)
            if (re.search(r"(?<!\d)\d[\d,]*\s*/\s*\d[\d,]*(?!\d)", text)
                    and self._numbers(line)):
                quantity_hits.append(line)
        if len(quantity_hits) != 1:
            return None
        row = quantity_hits[0]
        cy = int(sum((word[1][1] + word[1][3]) / 2 for word in row) / len(row))
        numeric_values = self._numbers(row)
        numeric_roi = max((item[1] for item in numeric_values), key=lambda roi: roi[0])
        top, bottom = max(0, cy - 20), min(captured.frame.shape[0], cy + 21)
        gray = cv2.cvtColor(captured.frame[top:bottom], cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 40, 120)
        segments = cv2.HoughLinesP(
            edges, rho=1, theta=np.pi / 180, threshold=55,
            minLineLength=120, maxLineGap=14,
        )
        candidates = []
        if segments is not None:
            for entry in segments[:, 0, :]:
                x0, y0, x1, y1 = map(int, entry)
                if (abs(y1 - y0) <= 3 and x0 < numeric_roi[0] - 12
                        and x1 < numeric_roi[0] - 12 and x1 - x0 >= 120):
                    candidates.append((x1 - x0, x0, x1, top + (y0 + y1) // 2))
        if not candidates:
            return None
        longest = max(value[0] for value in candidates)
        best = [value for value in candidates if value[0] >= longest - 10]
        x_ranges = {(value[1], value[2]) for value in best}
        if len(x_ranges) != 1:
            return None
        x0, x1 = next(iter(x_ranges))
        track_y = int(round(sum(value[3] for value in best) / len(best)))
        return (
            x0, track_y, x1, track_y,
            (x0 - 48, track_y - 24, x0 - 8, track_y + 24),
            (x1 + 8, track_y - 24, x1 + 50, track_y + 24),
        )
    def select_quantity(self, tab, offer, quantity, dialog):
        if self.last_dialog is None:
            return None
        source = self._capture(f"daily-shops-{tab}-quantity-adjust-source")
        current = self._dialog(source, offer)
        geometry = self._slider_track(source, current) if current is not None else None
        if geometry is None:
            return None
        left, cy, right, _unused, minus_roi, plus_roi = geometry
        current_quantity = current.selected_quantity
        cap = daily_shop_quantity(offer, shop_identity=offer.shop_identity)
        if type(current_quantity) is not int or type(cap) is not int or cap < quantity:
            return None
        if current_quantity != quantity:
            start_x = round(left + (current_quantity - 1) * (right - left) / max(cap - 1, 1))
            end_x = round(left + (quantity - 1) * (right - left) / max(cap - 1, 1))
            self.context.checkpoint()
            self.runtime.swipe(
                source, start=(start_x, cy), end=(end_x, cy),
                action_key=f"daily-shops:{tab}:quantity-slider:{source.sha256}",
                target_identity=f"daily-shops:{tab}:quantity-slider",
            )
            source = self._capture(f"daily-shops-{tab}-quantity-slider-readback")
            current = self._dialog(source, offer)
            if current is None:
                return None
            difference = quantity - current.selected_quantity
            if abs(difference) > 4:
                return None
            for ordinal in range(abs(difference)):
                button_roi = self._slider_track(source, current)
                if button_roi is None:
                    return None
                roi = button_roi[5] if difference > 0 else button_roi[4]
                if not self._tap(
                    source, roi, f"daily-shops:{tab}:quantity-correction",
                    f"daily-shops:{tab}:quantity-correction:{source.sha256}:{ordinal}",
                    lambda after: self._dialog(after, offer) is not None,
                ):
                    return None
                source = self._capture(f"daily-shops-{tab}-quantity-correction-readback-{ordinal}")
                current = self._dialog(source, offer)
                if current is None:
                    return None
        if (current.selected_quantity != quantity or current.total != quantity * offer.unit_price
                or current.inner_buy_roi is None):
            return None
        return current

    def cancel_quantity_dialog(self):
        if self.last_dialog is None:
            return False
        captured = self._capture("daily-shops-quantity-cancel-source")
        lines = self._ocr(captured)
        closes = self._hits(lines, "X")
        if len(closes) != 1:
            return False
        return self._tap(
            captured, closes[0], "daily-shops:quantity-dialog-close",
            f"daily-shops:quantity-close:{captured.sha256}",
            lambda after: self._page(after)[0] in {RUINS_TAB, RARE_EARTH_TAB},
        )

    def purchase(self, tab, offer, dialog, action_key):
        return _purchase_daily_offer(self.context, self, tab, offer, dialog, action_key,
                                     settle_seconds=self.settle_seconds)


    def _back(self):
        captured = self._capture("daily-shops-back-source")
        page = self._page(captured)[0]
        if page not in {RUINS_TAB, RARE_EARTH_TAB, "ruins_challenge"}:
            return False
        self.context.checkpoint()
        self.runtime.back(captured, action_key=f"daily-shops:back:{captured.sha256}")
        after = self._capture("daily-shops-back-successor")
        return self._page(after)[0] in {RUINS_TAB, RARE_EARTH_TAB, "ruins_challenge", "home"}

    def return_home(self):
        for _ in range(3):
            captured = self._capture("daily-shops-terminal-home-source")
            if self.context.is_clean_home(captured.frame):
                return True
            if self._page(captured)[0] not in {RUINS_TAB, RARE_EARTH_TAB, "ruins_challenge"}:
                return False
            self.context.checkpoint()
            self.runtime.back(captured, action_key=f"daily-shops:return-home:{captured.sha256}")
            successor = self._capture("daily-shops-return-home-successor")
            if self.context.is_clean_home(successor.frame):
                return True
            if self._page(successor)[0] not in {RUINS_TAB, RARE_EARTH_TAB, "ruins_challenge"}:
                return False
        return self.context.is_clean_home(self._capture("daily-shops-terminal-home-final").frame)

    def switch_to_rare_earth(self):
        if self.current_tab == "ruins":
            tab = "Rare Earth Shop"
            if not self._tap_text(
                tab, "daily-shops:rare-earth-tab",
                lambda after: self._page(after)[0] == RARE_EARTH_TAB,
            ):
                return False
            self.current_tab = RARE_EARTH_TAB
            return True
        return self.current_tab == RARE_EARTH_TAB


def _purchase_daily_offer(context, port, tab, offer, dialog, action_key, *, settle_seconds):
    import hashlib
    import numpy as np
    from dataclasses import replace
    from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID
    from safe_action_core import ActionClass, CentralPolicy, Observation, PolicyRequest, SafeActionExecutor, TransportResult
    from scripts.daily_shops_bluestacks import PurchaseEffect

    spec = {
        RUINS_TAB: (
            "ruins_shop", "3_star_chip_enhance_material", "RUINS_COINS",
            "RUINS_SHOP_QUANTITY_DIALOG", "daily-shops:ruins:inner-buy",
            "RUINS_SHOP_PURCHASE_RECONCILED",
        ),
        RARE_EARTH_TAB: (
            "rare_earth_shop", "3_star_module_enhance_material", "RARE_EARTH",
            "RARE_EARTH_SHOP_QUANTITY_DIALOG", "daily-shops:rare-earth:inner-buy",
            "RARE_EARTH_SHOP_PURCHASE_RECONCILED",
        ),
    }[tab]
    shop, subject, currency, source_state, target_identity, postcondition = spec
    quantity = dialog.selected_quantity
    total = dialog.total
    if not purchase_dialog_matches(
        offer, quantity=quantity, selected_quantity=dialog.selected_quantity,
        displayed_total=total, shop_identity=offer.shop_identity,
    ):
        return PurchaseEffect("blocked", None, False, 0, None, None, None, "", "", False,
                              action_key=action_key, reason="DAILY_SHOP_DIALOG_NUMERIC_PROOF_FAILED")
    policy_source = port._capture(f"daily-shops-{tab}-purchase-policy-source")
    initially_read = port._dialog(policy_source, offer)
    if (initially_read is None or initially_read.selected_quantity != quantity
            or initially_read.total != total or initially_read.inner_buy_roi is None):
        return PurchaseEffect("blocked", None, False, 0, None, None, None, "", "", False,
                              action_key=action_key, reason="DAILY_SHOP_FRESH_QUANTITY_CHANGED")
    source = port._capture(f"daily-shops-{tab}-inner-buy-immediate-before")
    current = port._dialog(source, offer)
    if (current is None or current.selected_quantity != quantity or current.total != total
            or current.inner_buy_roi != initially_read.inner_buy_roi):
        return PurchaseEffect("blocked", None, False, 0, None, None, None, "", "", False,
                              action_key=action_key, reason="DAILY_SHOP_IMMEDIATE_QUANTITY_CHANGED")
    roi = current.inner_buy_roi
    x0, y0, x1, y1 = roi

    def observation_for(captured):
        return Observation(
            frame_sha256=captured.sha256, capture_completed_monotonic=captured.captured_monotonic,
            runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID, width=800, height=1280,
            valid_png=captured.frame.shape == (1280, 800, 3), corrupt=False,
            black=not bool(np.any(captured.frame)), source_state=source_state, overlay_state="none",
            target_identity=target_identity, target_roi=roi, recognized=True,
            clipped=False, ambiguous=False, control_class="BUY",
            consequence="daily_shops_purchase", cost_type=currency,
            cost_amount=total, quantity=quantity, expected_postcondition=postcondition,
            evidence_refs=tuple(
                str(value.path) for value in (
                    policy_source, source, port.last_offer_capture,
                ) if value is not None
            ),
            critical_roi_hashes=(("inner-buy", hashlib.sha256(
                captured.frame[y0:y1, x0:x1].tobytes(),
            ).hexdigest()),),
            ocr_result_frame_sha256=captured.sha256,
            ocr_result_capture_completed_monotonic=captured.captured_monotonic,
            source_family="DAILY_SHOPS", target_isolated=True,
            package_foreground=port.runtime.measure_foreground_package() == "com.global.ztmslg",
        )

    observation = observation_for(source)
    policy_observation = observation_for(policy_source)
    preconditions = (
        f"shop={shop}", f"item={subject}", "rarity=3", f"currency={currency}",
        f"unit_price={offer.unit_price}", f"stock={offer.stock}", f"balance={offer.balance}",
        f"quantity={quantity}", f"total={total}",
        f"daily_shops_reset_id={context.identity.reset_id}", f"daily_shops_tab={shop}",
        "daily_shops_tab_action_ordinal=1", "daily_shops_tab_action_count_before=0",
        "daily_shops_tab_action_limit=1",
    )
    request = PolicyRequest(
        action_id=hashlib.sha256(f"{action_key}:daily-shop".encode()).hexdigest(),
        action_key=action_key, task_id=FLOW_ID, task_mode="supervised_validation",
        semantic_action="PURCHASE_DAILY_SHOP_MATERIAL",
        expected_runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID, observation=policy_observation,
        monotonic_now=context.monotonic_clock(), observation_max_age_seconds=30.0,
        dispatch_max_age_seconds=10.0, lease_owner=context.owner,
        lease_valid=context.action_store.lease_valid_for(context.owner, context.utc_clock()),
        unresolved_action=context.action_store.has_action_block(),
        duplicate_action_key=context.action_store.get_action_by_key(action_key) is not None,
        game_day_id=context.identity.reset_id, action_class=ActionClass.SPEND_OR_STRATEGIC,
        action_kind="daily_shops_purchase-v1", subject=subject,
        resource_or_currency=currency, maximum_cost=total, free_only=False,
        allowed_confirmation_dialogs=(source_state,), semantic_preconditions=preconditions,
        semantic_postconditions=(postcondition,), runtime_session_id=str(context.session.session_directory),
    )
    policy = CentralPolicy({FLOW_ID})
    issued = policy.issue_capability(replace(
        request, observation=observation, monotonic_now=context.monotonic_clock(),
    ))
    context.action_store.audit(FLOW_ID, "capability_issued", context.utc_clock(), issued.audit, request.action_id)
    if not issued.authorized or issued.capability is None:
        return PurchaseEffect("blocked", None, False, 0, None, None, None, "", "", False,
                              action_key=action_key, reason=issued.reason_code)
    frames = {"source": policy_source, "current": source}
    effects = {}

    def recapture():
        return observation

    def transport(intent):
        port.runtime.tap(
            frames["current"], target_identity=target_identity,
            target_roi=intent.target_roi, action_key=action_key,
            action_class=ActionClass.SPEND_OR_STRATEGIC.value, consequential=True,
        )
        return TransportResult(True, "DAILY_SHOP_INNER_BUY_DISPATCHED")

    def post_observe():
        for ordinal in range(1, 4):
            context.checkpoint()
            if settle_seconds:
                import time
                time.sleep(settle_seconds)
            captured = port._capture(f"daily-shops-{tab}-purchase-post-{ordinal}")
            after = port._read_offer(captured, tab)
            page = port._page(captured)[0]
            item_after_shop = after.item_quantity if after is not None else None
            item_effect = item_after_shop == offer.item_quantity + quantity
            shop_ok = bool(
                page == tab and after is not None
                and after.balance == offer.balance - total
                and after.stock == offer.stock - quantity
                and item_effect
            )
            if shop_ok:
                effects.update(
                    currency_after=after.balance, stock_after=after.stock,
                    tab_successor_verified=True, shop_frame=captured,
                )
                # Settle the actual paired effects here, before switching tabs. Home is a
                # route-terminal condition, not a reason to leave and re-enter the shop.
                effects.update(
                    item_quantity_after=after.item_quantity, item_identity_after=after.item_identity,
                    currency_identity_after=after.currency_identity, item_effect_verified=True,
                )
                refs = [str(source.path), str(frames["source"].path), str(captured.path)]
                if port.last_offer_capture is not None:
                    refs.append(str(port.last_offer_capture.path))
                yield Observation(
                    frame_sha256=captured.sha256, capture_completed_monotonic=captured.captured_monotonic,
                    runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID, width=800, height=1280,
                    valid_png=captured.frame.shape == (1280, 800, 3), corrupt=False,
                    black=not bool(np.any(captured.frame)), source_state=postcondition,
                    overlay_state="none", target_identity=None, target_roi=None,
                    recognized=True, ambiguous=False, consequence="daily_shops_purchase",
                    cost_type=currency, cost_amount=total, quantity=quantity,
                    expected_postcondition=postcondition, evidence_refs=tuple(dict.fromkeys(refs)),
                    critical_roi_hashes=(("shop-paired-effect", hashlib.sha256(captured.frame.tobytes()).hexdigest()),),
                    ocr_result_frame_sha256=captured.sha256,
                    ocr_result_capture_completed_monotonic=captured.captured_monotonic,
                    source_family="DAILY_SHOPS",
                    package_foreground=port.runtime.measure_foreground_package() == "com.global.ztmslg",
                )
                return
            roi_hits = port._hits(port._ocr(captured), offer.item_identity)
            roi = roi_hits[0] if len(roi_hits) == 1 else (0, 0, 1, 1)
            yield Observation(
                frame_sha256=captured.sha256, capture_completed_monotonic=captured.captured_monotonic,
                runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID, width=800, height=1280,
                valid_png=captured.frame.shape == (1280, 800, 3), corrupt=False,
                source_state=page or "UNKNOWN",
                black=not bool(np.any(captured.frame)),
                overlay_state="none", target_identity=None, target_roi=roi,
                recognized=False, ambiguous=True, evidence_refs=(str(captured.path),),
                ocr_result_frame_sha256=captured.sha256,
                ocr_result_capture_completed_monotonic=captured.captured_monotonic,
                package_foreground=port.runtime.measure_foreground_package() == "com.global.ztmslg",
            )

    def reconcile(_intent, observed):
        return bool(observed.source_state == postcondition
                    and effects.get("item_effect_verified") is True
                    and effects.get("tab_successor_verified") is True)

    execution = SafeActionExecutor(
        context.action_store, policy, context.owner, context.monotonic_clock,
        transport, recapture, post_observe, reconcile,
        wall_clock=context.utc_clock, max_pre_dispatch_attempts=1,
    ).execute(request, issued.capability)
    action = context.action_store.get_action_by_key(action_key)
    dispatched = action_key in port.runtime.action_keys
    journal = str(action.get("final_status") if action else "unresolved")
    if execution.status.value == "confirmed" and journal == "confirmed":
        context.validate_identity()
        try:
            port.runtime.reconcile(action_key, "confirmed", effects["shop_frame"],
                                   "exact observed material, currency, stock and tab effects verified")
        except (AttributeError, KeyError, TypeError, ValueError):
            pass
    return PurchaseEffect(
        "confirmed" if journal == "confirmed" else "unresolved" if journal in {"input_sent", "unresolved"} else "blocked",
        journal, dispatched, int(dispatched), effects.get("currency_after"),
        effects.get("stock_after"), effects.get("item_quantity_after"),
        effects.get("item_identity_after", ""), effects.get("currency_identity_after", ""),
        bool(effects.get("tab_successor_verified")),
        effect_reconciliation_required=journal in {"input_sent", "unresolved"},
        identical_retry_denied=journal in {"prepared", "input_sent", "unresolved"},
        action_key=action_key, reason=execution.reason,
    )


def _service_driver(context, arguments):
    from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID
    action_keys = arguments.get("action_keys")
    if not isinstance(action_keys, Mapping) or set(action_keys) != set(TABS):
        raise ValueError("Daily Shops canonical tab action keys are missing")
    port = DailyShopsLivePort(context, action_keys=action_keys, settle_seconds=context.settle_seconds)
    context.validate_identity()
    source = context.session.observe(context.runtime.capture, label="daily-shops-canonical-home-source")
    if not context.is_clean_home(source.frame):
        try:
            port.return_home()
        finally:
            context.session.adopt_retained_transport_count(
                context.runtime.input_count, source=str(context.runtime.events),
            )
        source = context.session.observe(context.runtime.capture, label="daily-shops-recovered-home-source")
    if not context.is_clean_home(source.frame):
        return {
            "status": "blocked", "reason": "DAILY_SHOPS_HOME_SOURCE_CHANGED",
            "purchase_transport_calls": 0, "committed_action_count": 0,
            "accounting_verified": context.accounting().verified, "terminal_home_verified": False,
            "effect_reconciliation_required": False, "identical_retry_denied": False,
            "input_count": context.runtime.input_count, "total_input_count": context.runtime.input_count,
        }
    context.bind_initial_observation(source, extra={"source_state": "HOME_BASE", "home_verified": True})
    try:
        result = run_daily_shops_route(port, action_keys=action_keys)
    finally:
        context.session.adopt_retained_transport_count(
            context.runtime.input_count, source=str(context.runtime.events),
        )
    accounting = context.accounting()
    context.validate_identity()
    total = accounting.input_count
    result.update(
        account_id=context.identity.account_id, server_id=context.identity.server_id,
        reset_id=context.identity.reset_id, occurrence_key=context.occurrence_key,
        runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID, input_count=total,
        total_input_count=total,
        accounting_verified=bool(
            accounting.verified and total <= MAX_INPUTS
            and result.get("purchase_transport_calls", 0) <= MAX_ACTIONS
            and result.get("committed_action_count", 0) <= MAX_ACTIONS
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
        flow_id=FLOW_ID, product_id=PRODUCT_ID, product_revision=PRODUCT_REVISION,
        runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        owner="automation-service:daily-shops", workflow="daily-shops-native",
        max_inputs=MAX_INPUTS, max_actions=MAX_ACTIONS,
        driver=_service_driver, lease_seconds=3600.0,
    )
