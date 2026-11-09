"""Reset-scoped facts and transition guards for free Hero Duel–Survival cycles."""
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
    """Fresh native facts, including positive availability rather than portrait presence."""

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
    displayed_hero_ids: tuple[str, ...] = ()
    eligible_hero_ids: Optional[tuple[str, ...]] = None
    defense_hero_ids: tuple[str, ...] = ()
    defense_save_acknowledged: bool = False
    formation_slot_states: tuple[str, ...] = ()
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
    return bool(observation.recognized
        and observation.runtime_profile_id == ACTIVE_RUNTIME_PROFILE_ID
        and observation.target_provenance == BLUESTACKS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and isinstance(refs, tuple) and refs
        and all(isinstance(ref, str) and ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "native:", "synthetic:")) for ref in refs))


def hero_duel_source_valid(observation: HeroDuelObservation) -> bool:
    return bool(_native_observation_valid(observation)
        and observation.overlay_state in {"none", "none_observed"}
        and observation.screen_state and observation.target_roi is not None
        and len(observation.target_roi) == 4
        and all(type(value) is int for value in observation.target_roi)
        and 0 <= observation.target_roi[0] < observation.target_roi[2] <= 800
        and 0 <= observation.target_roi[1] < observation.target_roi[3] <= 1280
        and observation.target_identity)


def hero_duel_current_survival(observation: HeroDuelObservation) -> bool:
    return bool(_native_observation_valid(observation)
        and observation.overlay_state in {"none", "none_observed"}
        and observation.screen_state in {"event_select", "emergency_details", "defense_formation",
            "hero_duel_overview", "challenge_upsell", "opponent_list", "attack_formation",
            "active_battle", "flee_warning", "loss_result"}
        and observation.event_variant == HERO_DUEL_SURVIVAL
        and observation.event_identity.strip() and observation.event_active is True)


def hero_duel_first_five_eligible(observation: HeroDuelObservation) -> tuple[str, ...] | None:
    displayed, eligible = observation.displayed_hero_ids, observation.eligible_hero_ids
    if (eligible is None or len(set(displayed)) != len(displayed)
            or len(set(eligible)) != len(eligible)
            or any(not isinstance(hero, str) or not hero for hero in displayed)
            or any(hero not in displayed for hero in eligible)):
        return None
    first = tuple(hero for hero in displayed if hero in eligible)
    return first[:5] if len(first) >= 5 else None


def hero_duel_defense_lineup_valid(observation: HeroDuelObservation,
        expected: tuple[str, ...] | None = None) -> bool:
    expected = expected or hero_duel_first_five_eligible(observation)
    return bool(expected is not None and len(expected) == 5
        and len(observation.defense_hero_ids) == 5
        and set(observation.defense_hero_ids) == set(expected)
        and observation.formation_slot_states == ("active",) * 5)


def hero_duel_defense_ready(observation: HeroDuelObservation) -> bool:
    return bool(hero_duel_current_survival(observation)
        and observation.defense_save_acknowledged)


def hero_duel_attack_fill(observation: HeroDuelObservation) -> tuple[str, ...] | None:
    slots = observation.formation_slot_states
    if len(slots) != 5 or any(state not in {"active", "empty"} for state in slots):
        return None
    missing = slots.count("empty")
    if not missing:
        return ()
    eligible = observation.eligible_hero_ids
    if eligible is None:
        return None
    # The native producer excludes checked cards from this ordered add list.
    available = tuple(hero for hero in observation.displayed_hero_ids if hero in eligible)
    return available[:missing] if len(available) >= missing else None


def hero_duel_attack_lineup_valid(observation: HeroDuelObservation) -> bool:
    return observation.formation_slot_states == ("active",) * 5


def hero_duel_cycle_budget(observation: HeroDuelObservation) -> tuple[int, int] | None:
    """The current quota preserves manual/development use without inventing receipts."""
    remaining = observation.free_entries_remaining
    if type(remaining) is not int or not 0 <= remaining <= MAX_HERO_DUEL_CYCLES:
        return None
    return remaining, MAX_HERO_DUEL_CYCLES - remaining


def hero_duel_entry_authorizeable(observation: HeroDuelObservation, *, ordinal: int,
        game_day_id: str) -> bool:
    return bool(hero_duel_source_valid(observation) and hero_duel_current_survival(observation)
        and observation.screen_state == "attack_formation"
        and observation.target_identity == "hero-duel-attack-challenge"
        and type(ordinal) is int and 1 <= ordinal <= MAX_HERO_DUEL_CYCLES
        and game_day_id and observation.game_day_id == game_day_id
        and observation.entry_ordinal == ordinal
        and observation.entry_cost_known and observation.entry_cost == 0
        and type(observation.free_entries_remaining) is int
        and 0 < observation.free_entries_remaining <= MAX_HERO_DUEL_CYCLES
        and observation.listed_opponent_free and observation.free_opponent_selected
        and observation.defense_save_acknowledged and hero_duel_attack_lineup_valid(observation)
        and not observation.activate_visible and not observation.premium_prompt_visible)


def hero_duel_flee_authorizeable(observation: HeroDuelObservation, *, ordinal: int,
        game_day_id: str) -> bool:
    return bool(hero_duel_source_valid(observation) and hero_duel_current_survival(observation)
        and observation.screen_state == "flee_warning"
        and observation.target_identity == "hero-duel-warning-flee"
        and type(ordinal) is int and 1 <= ordinal <= MAX_HERO_DUEL_CYCLES
        and game_day_id and observation.game_day_id == game_day_id
        and observation.entry_ordinal == ordinal and observation.cycle_battle_loaded
        and observation.cycle_exit_confirmed and observation.flee_warning_visible
        and observation.flee_control_visible and not observation.premium_prompt_visible)


def hero_duel_cycle_postcondition_verified(before: HeroDuelObservation,
        after: HeroDuelObservation | None, *, ordinal: int, game_day_id: str) -> bool:
    """Require the observed free-counter decrement and full battle/result path."""
    return bool(after is not None and hero_duel_current_survival(before)
        and 1 <= ordinal <= MAX_HERO_DUEL_CYCLES
        and before.screen_state == after.screen_state == "hero_duel_overview"
        and hero_duel_current_survival(after) and after.event_identity == before.event_identity
        and after.game_day_id == before.game_day_id == game_day_id
        and type(before.free_entries_remaining) is int and before.free_entries_remaining > 0
        and after.free_entries_remaining == before.free_entries_remaining - 1
        and after.cycle_battle_loaded and after.cycle_exit_confirmed
        and after.cycle_flee_confirmed and after.cycle_loss_result_seen
        and after.cycle_continue_confirmed)


def hero_duel_action_key(*, runtime_scope: str, account_id: str, server_id: str,
        game_day_id: str, ordinal: int, action_kind: str) -> str:
    values = (runtime_scope, account_id, server_id, game_day_id, action_kind)
    if (not all(isinstance(value, str) and _IDENTITY_RE.fullmatch(value) for value in values)
            or type(ordinal) is not int or not 1 <= ordinal <= MAX_HERO_DUEL_CYCLES):
        raise ValueError("Hero Duel action identity or ordinal is invalid")
    identity = json.dumps([*values[:4], ordinal, action_kind], ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")
    return "hero-duel:v2:" + hashlib.sha256(identity).hexdigest()


def hero_duel_policy_preconditions(action_kind: str, *, event_identity: str, ordinal: int,
        game_day_id: str, free_allowance_before: int | None = None,
        free_allowance_at_flee: int | None = None) -> tuple[str, ...]:
    """Current free state and event-bound authority; no paid-pass inventory proof."""
    if (action_kind not in {"hero_duel_free_entry", "hero_duel_flee", "hero_duel_save_defense"}
            or type(ordinal) is not int or not 1 <= ordinal <= MAX_HERO_DUEL_CYCLES
            or not isinstance(game_day_id, str) or not _IDENTITY_RE.fullmatch(game_day_id)
            or not isinstance(event_identity, str) or not _IDENTITY_RE.fullmatch(event_identity)):
        raise ValueError("Hero Duel policy action, event, or ordinal identity is invalid")
    product = ("hero_duel_product=hero_duel", "hero_duel_product_revision=hero_duel-v2",
        f"hero_duel_event_identity={event_identity}")
    if action_kind == "hero_duel_free_entry":
        if type(free_allowance_before) is not int or not 1 <= free_allowance_before <= 3:
            raise ValueError("Hero Duel entry requires a current positive Free allowance")
        return (*product, f"hero_duel_free_allowance_before={free_allowance_before}",
            f"hero_duel_entry_ordinal={ordinal}", f"hero_duel_entry_reset={game_day_id}",
            "current_event_is_hero_duel_survival", "event_active", "defense_first_five_eligible_saved",
            "attack_five_eligible_slots_populated", "listed_opponent_free_selected",
            "entry_cost_exactly_zero", "premium_prompt_absent", "overlay_absent")
    if action_kind == "hero_duel_flee":
        if type(free_allowance_at_flee) is not int or not 0 <= free_allowance_at_flee <= 3:
            raise ValueError("Hero Duel Flee requires its confirmed entry Free state")
        return (*product, f"hero_duel_free_allowance_at_flee={free_allowance_at_flee}",
            f"hero_duel_entry_ordinal={ordinal}", f"hero_duel_entry_reset={game_day_id}",
            "current_event_is_hero_duel_survival", "entry_same_cycle_ordinal_confirmed",
            "current_battle_loaded", "battle_exit_control_bound", "flee_warning_visible",
            "flee_button_bound", "fight_control_excluded", "premium_prompt_absent", "overlay_absent")
    return (*product, "current_event_is_hero_duel_survival", "event_active",
        "first_five_eligible_heroes_bound", "five_defense_slots_exact",
        "prohibited_support_absent", "overlay_absent")
