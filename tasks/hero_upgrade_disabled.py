"""Offline semantic contracts for Wali's bounded batches of individual single-level upgrades."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Mapping, Optional

from .contracts import ActionTransactionSpec, ROI
from .profile import ACTIVE_RUNTIME_PROFILE_ID, BLUESTACKS_NATIVE_TARGET_PROVENANCE


HERO_SCREEN = "HERO"
EVOLUTION_SCREEN = "HERO_EVOLUTION_PREVIEW"
HERO_TARGET = "hero-upgrade"
EVOLUTION_TARGET = "hero-evolve"
PRODUCT_ID = "hero_upgrade"
PRODUCT_REVISION = "hero_upgrade-v4"
HERO_IDENTITY = "Wali"
NORMAL_UPGRADE_ACTION = "HERO_UPGRADE_SINGLE"
EVOLUTION_ACTION = "HERO_EVOLUTION_STANDARD"
ANTISERUM = "ANTISERUM"
STANDARD_MANUALS = (
    "COMBAT_MANUAL_I",
    "COMBAT_MANUAL_II",
    "COMBAT_MANUAL_III",
    "COMBAT_MANUAL_IV",
    "COMBAT_MANUAL_V",
)
STANDARD_MATERIALS = frozenset((ANTISERUM, *STANDARD_MANUALS))
MAX_CONFIRMED_UPGRADES = 3
NORMAL_BATCH_POSTCONDITIONS = (
    f"hero_identity={HERO_IDENTITY}",
    "same_reset_identity=true",
    "current_level=before+journaled_inputs",
    "evolution_cap=before",
    "confirmed_upgrades=before+journaled_inputs",
    "1<=journaled_inputs<=normal_input_limit",
    "exact_cumulative_ANTISERUM_debit=sum(journaled_input_quotes)",
    "normal_level_delta_only=true",
    "bulk_upgrade=false",
    "reset_action=false",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class HeroUpgradeObservation:
    """Stable selected-Wali evidence and exact visible standard-material vectors."""

    screen_state: str
    hero_identity: str
    hero_selected: bool
    current_level: Optional[int]
    evolution_cap: Optional[int]
    material_costs: Mapping[str, int]
    material_balances: Mapping[str, int]
    target_identity: str
    target_roi: ROI
    panel_bounds: ROI
    control_class: str
    game_day_id: str
    confirmed_upgrades: int
    next_evolution_cap: Optional[int] = None
    material_rows_complete: bool = False
    stable_selected_state: bool = False
    normal_upgrade_visible: bool = False
    normal_single_upgrade: bool = False
    evolution_control_visible: bool = False
    spent_materials: Mapping[str, int] = field(default_factory=dict)
    material_usage_receipts: tuple[str, ...] = ()
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    overlay_state: str = "none_observed"
    # Exact box of the separate "Upgrade to Lv.N" row a normal Upgrade opens.
    # It is never a target; it is tolerated only while it leaves the single
    # control and the complete Antiserum quote recognizable.
    bulk_row_roi: Optional[ROI] = None
    reset_guard_active: bool = False
    runtime_profile_id: str = ACTIVE_RUNTIME_PROFILE_ID
    recognized: bool = True


def _target_inside_panel(observation: HeroUpgradeObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    coords = (px0, py0, px1, py1, tx0, ty0, tx1, ty1)
    return bool(
        all(type(value) is int for value in coords)
        and px0 <= tx0 < tx1 <= px1
        and py0 <= ty0 < ty1 <= py1
    )


def _has_bluestacks_native_source(observation: HeroUpgradeObservation) -> bool:
    refs = observation.evidence_refs
    source_sha = observation.source_frame_sha256
    if (
        not isinstance(refs, tuple)
        or not refs
        or any(not isinstance(ref, str) for ref in refs)
        or not isinstance(source_sha, str)
    ):
        return False
    return bool(
        observation.target_provenance == BLUESTACKS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(source_sha)
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == ACTIVE_RUNTIME_PROFILE_ID
    )


def _known_bulk_row_clear_of_target(observation: HeroUpgradeObservation) -> bool:
    try:
        bx0, by0, bx1, by1 = observation.bulk_row_roi  # type: ignore[misc]
        tx0, ty0, tx1, ty1 = observation.target_roi
        px0, py0, px1, py1 = observation.panel_bounds
    except (TypeError, ValueError):
        return False
    coords = (bx0, by0, bx1, by1, tx0, ty0, tx1, ty1)
    if not all(type(value) is int for value in coords):
        return False
    return bool(
        px0 <= bx0 < bx1 <= px1
        and py0 <= by0 < by1 <= py1
        and not (bx0 < tx1 and bx1 > tx0 and by0 < ty1 and by1 > ty0)
    )


def _stable_wali_observation(
    observation: HeroUpgradeObservation,
    *,
    screen: str,
    target: str,
    allow_known_bulk_row: bool = False,
) -> bool:
    overlay = observation.overlay_state
    overlay_clear = bool(
        isinstance(overlay, str)
        and (
            overlay in {"none", "none_observed"}
            and observation.bulk_row_roi is None
            or allow_known_bulk_row
            and overlay == "wali_bulk_row"
            and _known_bulk_row_clear_of_target(observation)
        )
    )
    return bool(
        observation.screen_state == screen
        and observation.hero_identity == HERO_IDENTITY
        and observation.hero_selected is True
        and observation.stable_selected_state is True
        and type(observation.current_level) is int
        and observation.current_level >= 0
        and type(observation.evolution_cap) is int
        and observation.evolution_cap >= 0
        and type(observation.confirmed_upgrades) is int
        and 0 <= observation.confirmed_upgrades <= MAX_CONFIRMED_UPGRADES
        and observation.target_identity == target
        and _target_inside_panel(observation)
        and overlay_clear
        and isinstance(observation.game_day_id, str)
        and bool(observation.game_day_id.strip())
        and not observation.reset_guard_active
        and observation.recognized is True
        and _has_bluestacks_native_source(observation)
    )


def _valid_material_maps(observation: HeroUpgradeObservation) -> bool:
    if observation.material_rows_complete is not True:
        return False
    if not isinstance(observation.material_costs, Mapping) or not isinstance(
        observation.material_balances, Mapping
    ):
        return False
    if not observation.material_costs or not set(observation.material_costs) <= STANDARD_MATERIALS:
        return False
    if not set(observation.material_balances) <= STANDARD_MATERIALS:
        return False
    for material, cost in observation.material_costs.items():
        balance = observation.material_balances.get(material)
        if (
            type(cost) is not int
            or cost <= 0
            or type(balance) is not int
            or balance < cost
        ):
            return False
    return all(type(balance) is int and balance >= 0 for balance in observation.material_balances.values())


def _exact_cost_vector(
    observation: HeroUpgradeObservation,
    *,
    evolution: bool,
) -> bool:
    costs = observation.material_costs
    if not _valid_material_maps(observation) or ANTISERUM not in costs:
        return False
    if not evolution:
        return set(costs) == {ANTISERUM}
    manuals = set(costs) & set(STANDARD_MANUALS)
    return bool(manuals and set(costs) == {ANTISERUM, *manuals})


def _material_vector_tokens(observation: HeroUpgradeObservation) -> tuple[str, ...]:
    order = (ANTISERUM, *STANDARD_MANUALS)
    materials = tuple(material for material in order if material in observation.material_costs)
    return tuple(
        token
        for material in materials
        for token in (
            f"material_cost.{material}={observation.material_costs[material]}",
            f"material_balance.{material}={observation.material_balances[material]}",
        )
    )


def hero_upgrade_authorizeable(observation: HeroUpgradeObservation) -> bool:
    """Require one affordable normal single-level upgrade for selected Wali."""

    return bool(
        _stable_wali_observation(observation, screen=HERO_SCREEN, target=HERO_TARGET)
        and observation.current_level < observation.evolution_cap
        and observation.control_class == "UPGRADE"
        and observation.normal_upgrade_visible is True
        and observation.normal_single_upgrade is True
        and 0 <= observation.confirmed_upgrades < MAX_CONFIRMED_UPGRADES
        and _exact_cost_vector(observation, evolution=False)
    )


def hero_evolution_authorizeable(observation: HeroUpgradeObservation) -> bool:
    """Require one standard, affordable evolution at the currently displayed cap."""

    return bool(
        _stable_wali_observation(observation, screen=EVOLUTION_SCREEN, target=EVOLUTION_TARGET)
        and observation.current_level == observation.evolution_cap
        and type(observation.next_evolution_cap) is int
        and observation.next_evolution_cap > observation.evolution_cap
        and observation.control_class == "EVOLVE"
        and observation.evolution_control_visible is True
        and observation.confirmed_upgrades < MAX_CONFIRMED_UPGRADES
        and _exact_cost_vector(observation, evolution=True)
    )


def normal_upgrade_input_limit(observation: HeroUpgradeObservation) -> int:
    """Remaining normal quota bounded by the displayed cap; zero when no input is admissible."""

    if not hero_upgrade_authorizeable(observation):
        return 0
    return min(
        MAX_CONFIRMED_UPGRADES - observation.confirmed_upgrades,
        observation.evolution_cap - observation.current_level,
    )


def hero_upgrade_batch_spec(observation: HeroUpgradeObservation, input_limit: int) -> ActionTransactionSpec:
    """One Core intent for up to ``input_limit`` individual single-level Upgrade inputs.

    The first quote and baseline balance are bound; every later input must read
    its own current quote. The baseline balance bounds the cumulative quotes.
    """

    if (
        not hero_upgrade_authorizeable(observation)
        or type(input_limit) is not int
        or not 1 <= input_limit <= normal_upgrade_input_limit(observation)
    ):
        raise ValueError("Wali normal upgrade batch preconditions are not positively recognized")
    return ActionTransactionSpec(
        action_kind=NORMAL_UPGRADE_ACTION,
        expected_source_screen=HERO_SCREEN,
        subject=HERO_IDENTITY,
        quantity=input_limit,
        resource_or_currency=ANTISERUM,
        maximum_cost=observation.material_balances[ANTISERUM],
        free_only=False,
        allowed_confirmation_dialogs=(),
        semantic_preconditions=(
            f"product_id={PRODUCT_ID}",
            f"product_revision={PRODUCT_REVISION}",
            f"reset_identity={observation.game_day_id}",
            f"confirmed_upgrades={observation.confirmed_upgrades}",
            f"next_upgrade_ordinal={observation.confirmed_upgrades + 1}",
            f"hero_identity={HERO_IDENTITY}",
            "hero_selected=true",
            f"current_level={observation.current_level}",
            f"evolution_cap={observation.evolution_cap}",
            f"target_identity={HERO_TARGET}",
            "control_class=UPGRADE",
            "normal_single_upgrade=true",
            "bulk_upgrade=false",
            "standard_materials_only=true",
            f"normal_input_limit={input_limit}",
            "per_input_current_quote_required=true",
            *_material_vector_tokens(observation),
            "stable_selected_state=true",
            "native_target_evidence=true",
            "reset_action=false",
        ),
        semantic_postconditions=NORMAL_BATCH_POSTCONDITIONS,
    )


def _antiserum_quote(observation: HeroUpgradeObservation) -> tuple[int, int, int] | None:
    try:
        return (
            observation.current_level,
            observation.material_balances[ANTISERUM],
            observation.material_costs[ANTISERUM],
        )
    except (KeyError, TypeError):
        return None


def _positive_quotes(quoted_costs: object) -> tuple[int, ...] | None:
    if not isinstance(quoted_costs, (tuple, list)):
        return None
    quotes = tuple(quoted_costs)
    return quotes if all(type(cost) is int and cost > 0 for cost in quotes) else None


def hero_upgrade_batch_input_authorizeable(
    baseline: HeroUpgradeObservation,
    current: HeroUpgradeObservation,
    *,
    input_limit: int,
    quoted_costs: tuple[int, ...],
    previous_source: HeroUpgradeObservation | None,
) -> bool:
    """Admit the next individual input of one authorized batch from current evidence only.

    No intermediate level/debit settlement is asserted. The current source must
    be freshly different from the previous input's source (never its re-read
    quote), keep the single control and an exact affordable Antiserum quote,
    and keep cumulative quotes inside the baseline balance.
    """

    quotes = _positive_quotes(quoted_costs)
    if (
        quotes is None
        or not isinstance(current, HeroUpgradeObservation)
        or type(input_limit) is not int
        or not 1 <= input_limit <= normal_upgrade_input_limit(baseline)
        or len(quotes) >= input_limit
    ):
        return False
    current_quote = _antiserum_quote(current)
    if not quotes:
        return bool(
            previous_source is None
            and hero_upgrade_authorizeable(current)
            and current.game_day_id == baseline.game_day_id
            and current.confirmed_upgrades == baseline.confirmed_upgrades
            and current.evolution_cap == baseline.evolution_cap
            and current_quote == _antiserum_quote(baseline)
        )
    if not isinstance(previous_source, HeroUpgradeObservation) or current_quote is None:
        return False
    previous_quote = _antiserum_quote(previous_source)
    if previous_quote is None or quotes[-1] != previous_quote[2]:
        return False
    level, balance, cost = current_quote
    baseline_balance = baseline.material_balances[ANTISERUM]
    return bool(
        _stable_wali_observation(
            current, screen=HERO_SCREEN, target=HERO_TARGET, allow_known_bulk_row=True,
        )
        and current.game_day_id == baseline.game_day_id
        and current.confirmed_upgrades == baseline.confirmed_upgrades
        and current.evolution_cap == baseline.evolution_cap
        and current.control_class == "UPGRADE"
        and current.normal_upgrade_visible is True
        and current.normal_single_upgrade is True
        and _exact_cost_vector(current, evolution=False)
        and current_quote != previous_quote
        and current.source_frame_sha256 != previous_source.source_frame_sha256
        and previous_quote[0] <= level < current.evolution_cap
        and level <= baseline.current_level + len(quotes)
        and balance <= previous_quote[1]
        and balance <= baseline_balance
        and sum(quotes) + cost <= baseline_balance
    )


def hero_evolution_spec(observation: HeroUpgradeObservation) -> ActionTransactionSpec:
    if not hero_evolution_authorizeable(observation):
        raise ValueError("Wali standard evolution preconditions are not positively recognized")
    return ActionTransactionSpec(
        action_kind=EVOLUTION_ACTION,
        expected_source_screen=EVOLUTION_SCREEN,
        subject=HERO_IDENTITY,
        quantity=1,
        resource_or_currency=None,
        maximum_cost=None,
        free_only=False,
        allowed_confirmation_dialogs=(),
        semantic_preconditions=(
            f"product_id={PRODUCT_ID}",
            f"product_revision={PRODUCT_REVISION}",
            f"reset_identity={observation.game_day_id}",
            f"confirmed_upgrades={observation.confirmed_upgrades}",
            f"next_upgrade_ordinal={observation.confirmed_upgrades + 1}",
            f"hero_identity={HERO_IDENTITY}",
            "hero_selected=true",
            f"current_level={observation.current_level}",
            f"evolution_cap={observation.evolution_cap}",
            f"next_evolution_cap={observation.next_evolution_cap}",
            f"target_identity={EVOLUTION_TARGET}",
            "control_class=EVOLVE",
            "single_standard_evolution=true",
            "bulk_upgrade=false",
            "standard_materials_only=true",
            *_material_vector_tokens(observation),
            "stable_selected_state=true",
            "native_target_evidence=true",
            "reset_action=false",
        ),
        semantic_postconditions=(
            f"hero_identity={HERO_IDENTITY}",
            "same_reset_identity=true",
            "current_level=before+1",
            "evolution_cap=before.next_evolution_cap",
            "confirmed_upgrades=before",
            "exact_ANTISERUM_debit=true",
            "each_standard_manual_used_or_debited=true",
            "usage_receipt_and_settled_frame_refs_preserved=true",
            "reset_action=false",
        ),
    )


def _settled_successor(
    before: HeroUpgradeObservation,
    after: HeroUpgradeObservation | None,
) -> bool:
    return bool(
        isinstance(after, HeroUpgradeObservation)
        and isinstance(after.target_identity, str)
        and after.target_identity in {HERO_TARGET, EVOLUTION_TARGET}
        and _stable_wali_observation(
            after,
            screen=HERO_SCREEN,
            target=after.target_identity,
        )
        and after.game_day_id == before.game_day_id
    )


def _valid_explicit_spend(after: HeroUpgradeObservation, costs: Mapping[str, int]) -> bool:
    if not isinstance(after.spent_materials, Mapping):
        return False
    return all(
        material in costs
        and type(amount) is int
        and amount > 0
        and amount == costs[material]
        for material, amount in after.spent_materials.items()
    )


def _exact_material_debit(
    before: HeroUpgradeObservation,
    after: HeroUpgradeObservation,
    material: str,
) -> bool:
    if not isinstance(after.material_balances, Mapping) or not isinstance(
        after.spent_materials, Mapping
    ):
        return False
    cost = before.material_costs[material]
    explicit = after.spent_materials.get(material)
    if material in after.spent_materials and (type(explicit) is not int or explicit != cost):
        return False
    before_balance = before.material_balances[material]
    after_balance = after.material_balances.get(material)
    if after_balance is not None:
        if type(after_balance) is not int or before_balance - after_balance != cost:
            return False
        return explicit is None or explicit == cost
    return explicit == cost


def hero_upgrade_batch_postcondition_verified(
    before: HeroUpgradeObservation,
    after: HeroUpgradeObservation | None,
    *,
    inputs: int,
    quoted_costs: tuple[int, ...],
) -> bool:
    """Verify one batch's cumulative normal levels against its journaled inputs and quotes.

    ``before`` is the authorized baseline; ``after`` is the one settled final
    proof. Level delta and the exact cumulative Antiserum debit must both
    equal the journaled individual inputs; no per-input settlement is implied.
    """

    quotes = _positive_quotes(quoted_costs)
    if (
        not hero_upgrade_authorizeable(before)
        or not _settled_successor(before, after)
        or type(inputs) is not int
        or not 1 <= inputs <= normal_upgrade_input_limit(before)
        or quotes is None
        or len(quotes) != inputs
        or quotes[0] != before.material_costs[ANTISERUM]
    ):
        return False
    assert after is not None
    total = sum(quotes)
    before_balance = before.material_balances[ANTISERUM]
    balances, spent = after.material_balances, after.spent_materials
    if total > before_balance or not isinstance(balances, Mapping) or not isinstance(spent, Mapping):
        return False
    if set(spent) - {ANTISERUM} or (
        ANTISERUM in spent and (type(spent[ANTISERUM]) is not int or spent[ANTISERUM] != total)
    ):
        return False
    after_balance = balances.get(ANTISERUM)
    if after_balance is None:
        debited = spent.get(ANTISERUM) == total
    else:
        debited = type(after_balance) is int and before_balance - after_balance == total
    return bool(
        debited
        and after.current_level == before.current_level + inputs
        and after.evolution_cap == before.evolution_cap
        and after.confirmed_upgrades == before.confirmed_upgrades + inputs
        and after.confirmed_upgrades <= MAX_CONFIRMED_UPGRADES
    )


def _manual_usage_receipts_valid(after: HeroUpgradeObservation, manuals: set[str]) -> bool:
    receipts = after.material_usage_receipts
    if not isinstance(receipts, tuple) or any(receipt not in STANDARD_MANUALS for receipt in receipts):
        return False
    if len(set(receipts)) != len(receipts) or not set(receipts) <= manuals:
        return False
    if receipts:
        refs = after.evidence_refs
        if not isinstance(refs, tuple) or any(not isinstance(ref, str) for ref in refs):
            return False
        return len(set(refs)) >= len(receipts) + 1
    return True


def hero_evolution_postcondition_verified(
    before: HeroUpgradeObservation,
    after: HeroUpgradeObservation | None,
) -> bool:
    """Verify the cap transition, exact Antiserum debit, and each manual's use."""

    if not hero_evolution_authorizeable(before) or not _settled_successor(before, after):
        return False
    assert after is not None
    manuals = set(before.material_costs) & set(STANDARD_MANUALS)
    if not _valid_explicit_spend(after, before.material_costs):
        return False
    if not _exact_material_debit(before, after, ANTISERUM):
        return False
    if not _manual_usage_receipts_valid(after, manuals):
        return False
    for manual in manuals:
        if manual in after.spent_materials or manual in after.material_balances:
            if not _exact_material_debit(before, after, manual):
                return False
        elif manual not in after.material_usage_receipts:
            return False
    return bool(
        after.current_level == before.current_level + 1
        and after.evolution_cap == before.next_evolution_cap
        and after.confirmed_upgrades == before.confirmed_upgrades
    )
