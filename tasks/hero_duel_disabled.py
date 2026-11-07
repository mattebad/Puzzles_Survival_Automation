"""Reset-scoped semantics for the bounded Hero Duel–Survival route.

This module owns facts and transition guards only. Native OCR, transport,
canonical action persistence, and Home/Atlas evidence stay in their owners.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Optional

from .contracts import ROI
from .profile import ACTIVE_RUNTIME_PROFILE_ID, BLUESTACKS_NATIVE_TARGET_PROVENANCE


MAX_HERO_DUEL_CYCLES = 3
HERO_DUEL_SURVIVAL = "hero_duel_survival"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")


@dataclass(frozen=True)
class HeroDuelObservation:
    """One fresh native screen observation; facts are never input authority."""

    screen_state: str
    source_frame_sha256: str
    target_provenance: str = BLUESTACKS_NATIVE_TARGET_PROVENANCE
    evidence_refs: tuple[str, ...] = ()
    runtime_profile_id: str = ACTIVE_RUNTIME_PROFILE_ID
    recognized: bool = True
    overlay_state: str = "none"
    event_identity: str = ""
    event_variant: str = ""
    event_active: Optional[bool] = None
    free_entries_remaining: Optional[int] = None
    entry_cost: Optional[int] = None
    entry_cost_known: bool = False
    pass_balance: Optional[int] = None
    excluded_hero_ids: Optional[tuple[str, ...]] = None
    displayed_hero_ids: tuple[str, ...] = ()
    defense_hero_ids: tuple[str, ...] = ()
    defense_save_acknowledged: bool = False
    saved_defense_expected_hero_ids: tuple[str, ...] = ()
    attack_hero_ids: tuple[str, ...] = ()
    attack_slots_populated: Optional[int] = None
    listed_opponent_free: bool = False
    free_opponent_selected: bool = False
    challenge_now_visible: bool = False
    activate_visible: bool = False
    premium_prompt_visible: bool = False
    battle_board_visible: bool = False
    wave_text: str = ""
    battle_exit_visible: bool = False
    flee_warning_visible: bool = False
    flee_control_visible: bool = False
    fight_control_visible: bool = False
    loss_result_visible: bool = False
    tap_to_continue_visible: bool = False
    cycle_battle_loaded: bool = False
    cycle_exit_confirmed: bool = False
    cycle_flee_confirmed: bool = False
    cycle_loss_result_seen: bool = False
    cycle_continue_confirmed: bool = False
    terminal_home_verified: bool = False
    target_identity: str = ""
    target_roi: Optional[ROI] = None
    game_day_id: Optional[str] = None
    entry_ordinal: Optional[int] = None


def _native_observation_valid(observation: HeroDuelObservation) -> bool:
    refs = observation.evidence_refs
    return bool(
        observation.recognized
        and observation.runtime_profile_id == ACTIVE_RUNTIME_PROFILE_ID
        and observation.target_provenance == BLUESTACKS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and isinstance(refs, tuple)
        and refs
        and all(isinstance(ref, str) and ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "native:", "synthetic:")) for ref in refs)
    )


def hero_duel_source_valid(observation: HeroDuelObservation) -> bool:
    """Require a current, fully bound target on a native screen observation."""

    return bool(
        _native_observation_valid(observation)
        and observation.overlay_state in {"none", "none_observed"}
        and observation.screen_state
        and observation.target_roi is not None
        and len(observation.target_roi) == 4
        and all(type(value) is int for value in observation.target_roi)
        and 0 <= observation.target_roi[0] < observation.target_roi[2] <= 800
        and 0 <= observation.target_roi[1] < observation.target_roi[3] <= 1280
        and bool(observation.target_identity)
    )


def hero_duel_current_survival(observation: HeroDuelObservation) -> bool:
    """Accept only the exact current Survival event; Glory is a separate mode."""

    return bool(
        _native_observation_valid(observation)
        and observation.overlay_state in {"none", "none_observed"}
        and observation.screen_state in {
            "event_select",
            "emergency_details",
            "defense_formation",
            "hero_duel_overview",
            "challenge_upsell",
            "opponent_list",
            "attack_formation",
            "active_battle",
            "flee_warning",
            "loss_result",
        }
        and observation.event_variant == HERO_DUEL_SURVIVAL
        and observation.event_identity.strip()
        and observation.event_active is True
    )


def hero_duel_first_five_eligible(
    observation: HeroDuelObservation,
) -> tuple[str, ...] | None:
    """Return the current first five displayed heroes after current exclusions."""

    exclusions = observation.excluded_hero_ids
    displayed = observation.displayed_hero_ids
    if exclusions is None or not displayed:
        return None
    if (
        any(not isinstance(value, str) or not value.strip() for value in exclusions)
        or any(not isinstance(value, str) or not value.strip() for value in displayed)
        or len(set(displayed)) != len(displayed)
        or len(set(exclusions)) != len(exclusions)
    ):
        return None
    excluded = set(exclusions)
    eligible = tuple(hero for hero in displayed if hero not in excluded)
    return eligible[:5] if len(eligible) >= 5 else None


def hero_duel_defense_ready(observation: HeroDuelObservation) -> bool:
    """Defense must be the first five current eligible heroes, saved explicitly."""

    expected = hero_duel_first_five_eligible(observation)
    return bool(
        hero_duel_current_survival(observation)
        and expected is not None
        and observation.screen_state == "hero_duel_overview"
        and observation.defense_save_acknowledged
        and observation.defense_hero_ids == expected
    )


def hero_duel_attack_fill(
    observation: HeroDuelObservation,
) -> tuple[str, ...] | None:
    """Return only missing attack heroes; preserve a complete valid lineup."""

    eligible = hero_duel_first_five_eligible(observation)
    selected = observation.attack_hero_ids
    if eligible is None or len(set(selected)) != len(selected):
        return None
    if any(hero not in observation.displayed_hero_ids for hero in selected):
        return None
    exclusions = set(observation.excluded_hero_ids or ())
    if any(hero in exclusions for hero in selected):
        return None
    populated = observation.attack_slots_populated
    if type(populated) is not int or populated != len(selected) or not 0 <= populated <= 5:
        return None
    if populated == 5:
        return () if len(selected) == 5 else None
    missing = 5 - populated
    available = tuple(hero for hero in eligible if hero not in set(selected))
    return available[:missing] if len(available) >= missing else None


def hero_duel_cycle_budget(
    observation: HeroDuelObservation,
) -> tuple[int, int] | None:
    """Return (available entries, UI-inferred prior uses), not completion proof.

    A smaller current Free allowance can indicate earlier use, but only
    canonical, reconciled entry/flee effects establish the completed quota.
    """

    remaining = observation.free_entries_remaining
    if type(remaining) is not int or not 0 <= remaining <= MAX_HERO_DUEL_CYCLES:
        return None
    return remaining, MAX_HERO_DUEL_CYCLES - remaining


def hero_duel_entry_authorizeable(
    observation: HeroDuelObservation,
    *,
    ordinal: int,
    game_day_id: str,
) -> bool:
    """Prove the free, listed-opponent entry transaction's full source facts."""

    # The attack roster/order can legitimately differ from the saved defense
    # source. Retain the independently verified first-five defense selection.
    eligible = observation.saved_defense_expected_hero_ids
    return bool(
        hero_duel_source_valid(observation)
        and hero_duel_current_survival(observation)
        and observation.screen_state == "attack_formation"
        and observation.target_identity == "hero-duel-attack-challenge"
        and type(ordinal) is int
        and 1 <= ordinal <= MAX_HERO_DUEL_CYCLES
        and game_day_id
        and observation.game_day_id == game_day_id
        and observation.entry_ordinal == ordinal
        and observation.entry_cost_known
        and observation.entry_cost == 0
        and observation.free_entries_remaining is not None
        and observation.free_entries_remaining > 0
        and type(observation.pass_balance) is int
        and observation.pass_balance >= 0
        and observation.listed_opponent_free
        and observation.free_opponent_selected
        and len(eligible) == 5
        and hero_duel_defense_lineup_valid(observation, eligible)
        and observation.excluded_hero_ids is not None
        and not any(hero in observation.excluded_hero_ids for hero in eligible)
        and hero_duel_attack_lineup_valid(observation)
        and not observation.activate_visible
        and not observation.premium_prompt_visible
    )


def hero_duel_flee_authorizeable(
    observation: HeroDuelObservation,
    *,
    ordinal: int,
    game_day_id: str,
) -> bool:
    """Allow only the observed Flee button on the matching current warning."""

    return bool(
        hero_duel_source_valid(observation)
        and hero_duel_current_survival(observation)
        and observation.screen_state == "flee_warning"
        and observation.target_identity == "hero-duel-warning-flee"
        and type(ordinal) is int
        and 1 <= ordinal <= MAX_HERO_DUEL_CYCLES
        and game_day_id
        and observation.game_day_id == game_day_id
        and observation.entry_ordinal == ordinal
        and observation.cycle_battle_loaded
        and observation.cycle_exit_confirmed
        and observation.flee_warning_visible
        and observation.flee_control_visible
        and not observation.premium_prompt_visible
    )


def hero_duel_defense_lineup_valid(
    observation: HeroDuelObservation,
    expected: tuple[str, ...] | None = None,
) -> bool:
    expected = expected or hero_duel_first_five_eligible(observation)
    return bool(
        expected is not None
        and len(expected) == 5
        and len(observation.defense_hero_ids) == 5
        and observation.defense_hero_ids == expected
        and observation.defense_save_acknowledged
    )


def hero_duel_attack_lineup_valid(observation: HeroDuelObservation) -> bool:
    heroes = observation.attack_hero_ids
    excluded = set(observation.excluded_hero_ids or ())
    return bool(
        observation.attack_slots_populated == 5
        and len(heroes) == 5
        and len(set(heroes)) == 5
        and all(hero in observation.displayed_hero_ids for hero in heroes)
        and not any(hero in excluded for hero in heroes)
    )


def hero_duel_cycle_postcondition_verified(
    before: HeroDuelObservation,
    after: HeroDuelObservation | None,
    *,
    ordinal: int,
    game_day_id: str,
) -> bool:
    """Verify the full battle/flee/result and exact free/pass deltas."""

    if after is None or not hero_duel_current_survival(before):
        return False
    initial_budget = hero_duel_cycle_budget(before)
    return bool(
        initial_budget is not None
        and ordinal == MAX_HERO_DUEL_CYCLES - initial_budget[0] + 1
        and 1 <= ordinal <= MAX_HERO_DUEL_CYCLES
        and before.screen_state == "hero_duel_overview"
        and after.screen_state == "hero_duel_overview"
        and hero_duel_current_survival(after)
        and after.event_identity == before.event_identity
        and after.game_day_id == game_day_id
        and before.game_day_id == game_day_id
        and type(before.free_entries_remaining) is int
        and after.free_entries_remaining == before.free_entries_remaining - 1
        and type(before.pass_balance) is int
        and before.pass_balance >= 0
        and after.pass_balance == before.pass_balance
        and after.cycle_battle_loaded
        and after.cycle_exit_confirmed
        and after.cycle_flee_confirmed
        and after.cycle_loss_result_seen
        and after.cycle_continue_confirmed
    )


def hero_duel_action_key(
    *,
    runtime_scope: str,
    account_id: str,
    server_id: str,
    game_day_id: str,
    ordinal: int,
    action_kind: str,
) -> str:
    """Build a stable canonical key bound to account, reset, ordinal and action."""

    values = (runtime_scope, account_id, server_id, game_day_id, action_kind)
    if (
        not all(isinstance(value, str) and _IDENTITY_RE.fullmatch(value) for value in values)
        or type(ordinal) is not int
        or not 1 <= ordinal <= MAX_HERO_DUEL_CYCLES
    ):
        raise ValueError("Hero Duel action identity or ordinal is invalid")
    identity = json.dumps(
        [*values[:4], ordinal, action_kind], ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return "hero-duel:v2:" + hashlib.sha256(identity).hexdigest()


def hero_duel_policy_preconditions(
    action_kind: str,
    *,
    event_identity: str,
    ordinal: int,
    game_day_id: str,
    free_allowance_before: int | None = None,
    pass_balance_before: int | None = None,
    free_allowance_at_flee: int | None = None,
) -> tuple[str, ...]:
    """Return product/event-instance facts plus exact UI balances for each dispatch."""

    if (
        action_kind not in {
            "hero_duel_free_entry",
            "hero_duel_flee",
            "hero_duel_save_defense",
        }
        or type(ordinal) is not int
        or not 1 <= ordinal <= MAX_HERO_DUEL_CYCLES
        or not isinstance(game_day_id, str)
        or not _IDENTITY_RE.fullmatch(game_day_id)
        or not isinstance(event_identity, str)
        or not _IDENTITY_RE.fullmatch(event_identity)
    ):
        raise ValueError("Hero Duel policy action, event, or ordinal identity is invalid")
    product = (
        "hero_duel_product=hero_duel",
        "hero_duel_product_revision=hero_duel-v2",
        f"hero_duel_event_identity={event_identity}",
    )
    if action_kind == "hero_duel_free_entry":
        if (
            type(free_allowance_before) is not int
            or free_allowance_before != MAX_HERO_DUEL_CYCLES - ordinal + 1
            or type(pass_balance_before) is not int
            or pass_balance_before < 0
        ):
            raise ValueError("Hero Duel entry requires exact current Free and pass balances")
        return (
            *product,
            f"hero_duel_free_allowance_before={free_allowance_before}",
            f"hero_duel_pass_balance_before={pass_balance_before}",
            f"hero_duel_entry_ordinal={ordinal}",
            f"hero_duel_entry_reset={game_day_id}",
            "current_event_is_hero_duel_survival",
            "event_active",
            "emergency_details_exclusions_inspected",
            "defense_first_five_eligible_saved",
            "attack_five_eligible_slots_populated",
            "listed_opponent_free_selected",
            "entry_cost_exactly_zero",
            "premium_prompt_absent",
            "overlay_absent",
        )
    if action_kind == "hero_duel_flee":
        if (
            type(free_allowance_at_flee) is not int
            or free_allowance_at_flee != MAX_HERO_DUEL_CYCLES - ordinal
            or type(pass_balance_before) is not int
            or pass_balance_before < 0
        ):
            raise ValueError("Hero Duel Flee requires exact current Free and unchanged pass balances")
        return (
            *product,
            f"hero_duel_free_allowance_at_flee={free_allowance_at_flee}",
            f"hero_duel_pass_balance_before={pass_balance_before}",
            f"hero_duel_entry_ordinal={ordinal}",
            f"hero_duel_entry_reset={game_day_id}",
            "current_event_is_hero_duel_survival",
            "entry_same_cycle_ordinal_confirmed",
            "current_battle_loaded",
            "battle_exit_control_bound",
            "flee_warning_visible",
            "flee_button_bound",
            "fight_control_excluded",
            "premium_prompt_absent",
            "overlay_absent",
        )
    return (
        *product,
        "current_event_is_hero_duel_survival",
        "event_active",
        "emergency_details_exclusions_inspected",
        "first_five_eligible_heroes_bound",
        "five_defense_slots_exact",
        "prohibited_support_absent",
        "overlay_absent",
    )

