"""Offline parameterized model for disabled Daily shop purchases.

Box, Ruins Shop, Rare Earth Shop, and Alliance Shop retain distinct Daily identities. Offer,
currency, and successor arithmetic are replayable, but purchase dispatch remains blocked by policy.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .contracts import ROI, TaskOutcome, TaskResult
from .profile import PROFILE_ID


PURCHASE_SCREEN = "SHOP"
PURCHASE_TARGET = "purchase-control"
DISABLED_POLICY_REASON = "PURCHASE_DISABLED_POLICY"
BLISS_NATIVE_TARGET_PROVENANCE = "bliss-native"
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
    runtime_profile_id: str = PROFILE_ID
    recognized: bool = True


def _target_inside_panel(observation: PurchaseObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1)


def _has_bliss_native_source(observation: PurchaseObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLISS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == PROFILE_ID
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
        and _has_bliss_native_source(observation)
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
