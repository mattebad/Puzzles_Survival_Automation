"""Offline purchase policy and paired-effect arithmetic for exact Daily shop offers.

This module selects only the approved shop products; service policy and canonical
action storage remain the dispatch authorities.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Optional

from .contracts import ROI, TaskOutcome, TaskResult
from .profile import ACTIVE_RUNTIME_PROFILE_ID, BLUESTACKS_NATIVE_TARGET_PROVENANCE


PURCHASE_SCREEN = "SHOP"
PURCHASE_TARGET = "purchase-control"
DISABLED_POLICY_REASON = "PURCHASE_DISABLED_POLICY"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

OBJECTIVE_TO_SHOP = {
    "buy_box": "BOX",
    "ruins_shop_purchase": "RUINS_SHOP",
    "rare_earth_shop_purchase": "RARE_EARTH_SHOP",
    "alliance_shop_purchase": "ALLIANCE_SHOP",
}


@dataclass(frozen=True)
class PurchaseObservation:
    """Semantic shop offer evidence with no executable purchase target."""

    screen_state: str
    selected_daily_row: bool
    objective_key: str
    shop_identity: str
    offer_identity: str
    item_identity: str
    target_identity: str
    target_roi: ROI
    panel_bounds: ROI
    control_class: str
    purchase_control_visible: bool
    currency_identity: str
    cost_known: bool
    cost_amount: Optional[int]
    currency_balance_before: Optional[int]
    item_quantity_before: Optional[int]
    reward_known: bool
    premium_offer: bool
    daily_progress_before: int
    currency_balance_after: Optional[int] = None
    item_quantity_after: Optional[int] = None
    daily_progress_after: Optional[int] = None
    purchase_confirmed: bool = False
    successor_state: str = ""
    game_day_id: Optional[str] = None
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    overlay_state: str = "none_observed"
    reset_guard_active: bool = False
    runtime_profile_id: str = ACTIVE_RUNTIME_PROFILE_ID
    recognized: bool = True


def _target_inside_panel(observation: PurchaseObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1)


def _has_bluestacks_native_source(observation: PurchaseObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLUESTACKS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == ACTIVE_RUNTIME_PROFILE_ID
    )


def purchase_authorizeable(observation: PurchaseObservation) -> bool:
    """Recognize exact shop/offer/cost evidence; this does not authorize a purchase."""

    expected_shop = OBJECTIVE_TO_SHOP.get(observation.objective_key)
    return bool(
        expected_shop
        and observation.screen_state == PURCHASE_SCREEN
        and observation.selected_daily_row
        and observation.shop_identity == expected_shop
        and bool(observation.offer_identity.strip())
        and bool(observation.item_identity.strip())
        and observation.target_identity == PURCHASE_TARGET
        and observation.control_class == "BUY"
        and observation.purchase_control_visible
        and _target_inside_panel(observation)
        and bool(observation.currency_identity.strip())
        and observation.cost_known
        and observation.cost_amount is not None
        and observation.cost_amount > 0
        and observation.currency_balance_before is not None
        and observation.currency_balance_before >= observation.cost_amount
        and observation.item_quantity_before is not None
        and observation.item_quantity_before >= 0
        and observation.reward_known
        and not observation.premium_offer
        and observation.daily_progress_before == 0
        and observation.overlay_state in {"none", "none_observed"}
        and bool(observation.game_day_id)
        and not observation.reset_guard_active
        and observation.recognized
        and _has_bluestacks_native_source(observation)
    )


def purchase_postcondition_verified(
    before: PurchaseObservation,
    after: PurchaseObservation | None,
) -> bool:
    """Verify offline currency/item arithmetic without implying permission to spend."""

    if not purchase_authorizeable(before) or after is None:
        return False
    return bool(
        purchase_authorizeable(after)
        and after.objective_key == before.objective_key
        and after.shop_identity == before.shop_identity
        and after.offer_identity == before.offer_identity
        and after.item_identity == before.item_identity
        and after.currency_identity == before.currency_identity
        and after.game_day_id == before.game_day_id
        and after.purchase_confirmed
        and after.currency_balance_after
        == before.currency_balance_before - before.cost_amount
        and after.item_quantity_after == before.item_quantity_before + 1
        and after.daily_progress_after == 1
        and after.successor_state == "PURCHASE_RECONCILED"
    )


def purchase_disabled_dispatch(observation: PurchaseObservation) -> TaskResult:
    """Always block shop purchase dispatch under current policy."""

    if not purchase_authorizeable(observation):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_VALID_PURCHASE_OBSERVATION",
            verified=True,
            state=PURCHASE_SCREEN,
        )
    return TaskResult(
        TaskOutcome.BLOCKED,
        DISABLED_POLICY_REASON,
        verified=True,
        state=PURCHASE_SCREEN,
        details={"dispatch_count": 0},
    )


# These rules decide whether a currently observed offer is inside the approved
# product envelope. They do not grant dispatch authority.
ALLIANCE_WEEKLY_SHOP = "Weekly Offers"
ALLIANCE_OTHER_SHOP = "Other"
ALLIANCE_CURRENCY = "Alliance Coins"
ALLIANCE_WEEKLY_ITEMS = (
    "Joy Coin",
    "Timed Recruit Coin",
    "Bioenhance Scheme",
)
ALLIANCE_FALLBACK_ITEM = "1★ Gear Enhance Material"
RUINS_SHOP = "Ruins Shop"
RARE_EARTH_SHOP = "Rare Earth Shop"
RUINS_CHIP_ITEM = "3★ Chip Enhance Material"
RARE_EARTH_MODULE_ITEM = "3★ Module Enhance Material"
RUINS_CURRENCY = "Ruins Coins"
RARE_EARTH_CURRENCY = "Rare Earth"


@dataclass(frozen=True)
class ShopOffer:
    """One exact current row; absent/unknown OCR must not be represented as a row."""

    shop_identity: str
    item_identity: str
    currency_identity: str
    unit_price: Optional[int]
    balance: Optional[int]
    stock: Optional[int]
    item_quantity: Optional[int]
    rarity: Optional[int] = None
    available: Optional[bool] = None
    premium: bool = False
    recognized: bool = True
    offer_identity: str = ""


@dataclass(frozen=True)
class AlliancePurchaseChoice:
    status: str
    reason: str
    offer: Optional[ShopOffer] = None
    quantity: int = 0


def _known_nonnegative(value: object) -> bool:
    return type(value) is int and value >= 0


def _known_positive(value: object) -> bool:
    return type(value) is int and value > 0


def alliance_shop_choice(
    weekly_offers: tuple[ShopOffer, ...],
    fallback_offer: Optional[ShopOffer],
    *,
    weekly_inventory_complete: bool,
    fallback_inventory_complete: bool,
) -> AlliancePurchaseChoice:
    """Select one exact affordable Weekly offer, else only the exact Other fallback."""

    if not weekly_inventory_complete:
        return AlliancePurchaseChoice("blocked", "WEEKLY_INVENTORY_INCOMPLETE")
    if type(weekly_offers) is not tuple or any(type(row) is not ShopOffer for row in weekly_offers):
        return AlliancePurchaseChoice("blocked", "WEEKLY_OFFER_EVIDENCE_INVALID")
    matched: dict[str, ShopOffer] = {}
    for row in weekly_offers:
        if row.item_identity not in ALLIANCE_WEEKLY_ITEMS:
            continue
        if row.item_identity in matched:
            return AlliancePurchaseChoice("blocked", "PREFERRED_OFFER_AMBIGUOUS")
        if (
            not row.recognized
            or row.shop_identity != ALLIANCE_WEEKLY_SHOP
            or row.currency_identity != ALLIANCE_CURRENCY
            or row.premium
            or type(row.available) is not bool
            or not _known_positive(row.unit_price)
            or not _known_nonnegative(row.balance)
            or not _known_nonnegative(row.stock)
            or not _known_nonnegative(row.item_quantity)
            or row.available != (row.stock > 0)
        ):
            return AlliancePurchaseChoice("blocked", "PREFERRED_OFFER_EVIDENCE_CHANGED")
        matched[row.item_identity] = row
    for item in ALLIANCE_WEEKLY_ITEMS:
        row = matched.get(item)
        if row is not None and row.available and row.balance >= row.unit_price:
            return AlliancePurchaseChoice("selected", "AFFORDABLE_PREFERRED_OFFER", row, 1)
    if not fallback_inventory_complete:
        return AlliancePurchaseChoice("blocked", "FALLBACK_INVENTORY_INCOMPLETE")
    if fallback_offer is None:
        return AlliancePurchaseChoice("deferred", "NO_AFFORDABLE_ALLOWLISTED_OFFER")
    row = fallback_offer
    if (
        type(row) is not ShopOffer
        or not row.recognized
        or row.shop_identity != ALLIANCE_OTHER_SHOP
        or row.item_identity != ALLIANCE_FALLBACK_ITEM
        or row.currency_identity != ALLIANCE_CURRENCY
        or row.rarity != 1
        or row.premium
        or type(row.available) is not bool
        or not _known_positive(row.unit_price)
        or not _known_nonnegative(row.balance)
        or not _known_nonnegative(row.stock)
        or not _known_nonnegative(row.item_quantity)
        or row.available != (row.stock > 0)
    ):
        return AlliancePurchaseChoice("blocked", "FALLBACK_OFFER_EVIDENCE_CHANGED")
    if not row.available or row.balance < row.unit_price:
        return AlliancePurchaseChoice("deferred", "NO_AFFORDABLE_ALLOWLISTED_OFFER")
    return AlliancePurchaseChoice("selected", "AFFORDABLE_EXACT_FALLBACK", row, 1)


def daily_shop_quantity(offer: ShopOffer, *, shop_identity: str) -> Optional[int]:
    """Return the live affordability/stock cap, or None for unrecognized evidence."""

    expected = {
        RUINS_SHOP: (RUINS_CHIP_ITEM, RUINS_CURRENCY),
        RARE_EARTH_SHOP: (RARE_EARTH_MODULE_ITEM, RARE_EARTH_CURRENCY),
    }.get(shop_identity)
    if (
        expected is None
        or type(offer) is not ShopOffer
        or not offer.recognized
        or offer.shop_identity != shop_identity
        or offer.item_identity != expected[0]
        or offer.currency_identity != expected[1]
        or offer.rarity != 3
        or offer.premium
        or type(offer.available) is not bool
        or not _known_positive(offer.unit_price)
        or not _known_nonnegative(offer.balance)
        or not _known_nonnegative(offer.stock)
        or not _known_nonnegative(offer.item_quantity)
        or offer.available != (offer.stock > 0)
    ):
        return None
    return min(offer.stock, offer.balance // offer.unit_price)


def purchase_dialog_matches(
    offer: ShopOffer,
    *,
    quantity: int,
    selected_quantity: Optional[int],
    displayed_total: Optional[int],
    shop_identity: Optional[str] = None,
) -> bool:
    """Require the numeric dialog quantity and total, never slider position."""

    if (
        type(offer) is not ShopOffer
        or type(quantity) is not int
        or quantity <= 0
        or type(selected_quantity) is not int
        or not _known_positive(offer.unit_price)
        or shop_identity is not None and offer.shop_identity != shop_identity
    ):
        return False
    if offer.shop_identity in {RUINS_SHOP, RARE_EARTH_SHOP}:
        maximum = daily_shop_quantity(offer, shop_identity=offer.shop_identity)
    elif (
        offer.shop_identity == ALLIANCE_WEEKLY_SHOP
        and offer.item_identity in ALLIANCE_WEEKLY_ITEMS
        and offer.currency_identity == ALLIANCE_CURRENCY
        and offer.recognized
        and not offer.premium
        and offer.available is True
        and _known_nonnegative(offer.balance)
        and _known_nonnegative(offer.stock)
        and _known_nonnegative(offer.item_quantity)
        and offer.stock > 0
        and offer.balance >= offer.unit_price
    ):
        maximum = 1
    elif (
        offer.shop_identity == ALLIANCE_OTHER_SHOP
        and offer.item_identity == ALLIANCE_FALLBACK_ITEM
        and offer.currency_identity == ALLIANCE_CURRENCY
        and offer.rarity == 1
        and offer.recognized
        and not offer.premium
        and offer.available is True
        and _known_nonnegative(offer.balance)
        and _known_nonnegative(offer.stock)
        and _known_nonnegative(offer.item_quantity)
        and offer.stock > 0
        and offer.balance >= offer.unit_price
    ):
        maximum = 1
    else:
        return False
    if maximum is None:
        return False
    return bool(
        quantity <= maximum
        and selected_quantity == quantity
        and type(displayed_total) is int
        and displayed_total == quantity * offer.unit_price
    )


def purchase_effect_verified(
    offer: ShopOffer,
    *,
    quantity: int,
    selected_quantity: Optional[int],
    displayed_total: Optional[int],
    currency_after: Optional[int],
    stock_after: Optional[int],
    item_quantity_after: Optional[int],
    item_identity_after: str,
    currency_identity_after: str,
    tab_successor_verified: bool,
    terminal_home_verified: bool,
    inner_buy_dispatched: bool,
) -> bool:
    """Reconcile the exact item and currency effects with both semantic successors."""

    if (
        type(offer) is not ShopOffer
        or not _known_nonnegative(offer.balance)
        or not _known_nonnegative(offer.stock)
        or not _known_nonnegative(offer.item_quantity)
        or not _known_positive(offer.unit_price)
        or type(quantity) is not int
        or quantity <= 0
        or not purchase_dialog_matches(
            offer, quantity=quantity, selected_quantity=selected_quantity,
            displayed_total=displayed_total,
        )
        or not _known_nonnegative(currency_after)
        or not _known_nonnegative(stock_after)
        or not _known_nonnegative(item_quantity_after)
        or type(item_identity_after) is not str
        or type(currency_identity_after) is not str
    ):
        return False
    return bool(
        inner_buy_dispatched is True
        and tab_successor_verified is True
        and terminal_home_verified is True
        and item_identity_after == offer.item_identity
        and currency_identity_after == offer.currency_identity
        and currency_after == offer.balance - quantity * offer.unit_price
        and stock_after == offer.stock - quantity
        and item_quantity_after == offer.item_quantity + quantity
    )


def canonical_purchase_action_key(
    flow_id: str,
    product_id: str,
    identity: object,
    component: str,
) -> str:
    """Build a durable per-reset purchase key, independent of service pulse and screen."""

    account_id = getattr(identity, "account_id", None)
    server_id = getattr(identity, "server_id", None)
    reset_id = getattr(identity, "reset_id", None)
    task_id = getattr(identity, "task_id", None)
    if (
        not isinstance(flow_id, str)
        or not flow_id.strip()
        or not isinstance(product_id, str)
        or not product_id.strip()
        or not isinstance(component, str)
        or not re.fullmatch(r"[a-z][a-z0-9_]*", component)
        or task_id != product_id
        or not all(
            isinstance(value, str) and value.strip()
            for value in (account_id, server_id, reset_id)
        )
    ):
        raise ValueError("canonical purchase key requires its exact route and reset identity")
    binding = json.dumps(
        [flow_id, product_id, account_id, server_id, reset_id, component],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(binding).hexdigest()
    return f"shop-purchase:v1:{component}:{digest}"
