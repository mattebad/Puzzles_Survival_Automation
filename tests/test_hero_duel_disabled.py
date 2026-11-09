from __future__ import annotations

from dataclasses import replace
import unittest

from tasks.hero_duel_disabled import (
    HERO_DUEL_SURVIVAL, HeroDuelObservation, hero_duel_action_key,
    hero_duel_attack_fill, hero_duel_attack_lineup_valid, hero_duel_current_survival,
    hero_duel_cycle_budget, hero_duel_cycle_postcondition_verified,
    hero_duel_defense_lineup_valid, hero_duel_defense_ready,
    hero_duel_entry_authorizeable, hero_duel_first_five_eligible,
    hero_duel_flee_authorizeable, hero_duel_policy_preconditions, hero_duel_source_valid,
)


def observation(**changes):
    values = dict(screen_state="hero_duel_overview", source_frame_sha256="a" * 64,
        evidence_refs=("synthetic:hero-duel-route",), event_identity="survival-event",
        event_variant=HERO_DUEL_SURVIVAL, event_active=True,
        free_entries_remaining=3, entry_cost=0, entry_cost_known=True,
        displayed_hero_ids=("a", "unavailable", "b", "c", "d", "e", "f"),
        eligible_hero_ids=("a", "b", "c", "d", "e", "f"),
        defense_hero_ids=("a", "b", "c", "d", "e"), defense_save_acknowledged=True,
        formation_slot_states=("active",) * 5, listed_opponent_free=True,
        free_opponent_selected=True, target_identity="hero-duel-overview-challenge",
        target_roi=(100, 1080, 700, 1180), game_day_id="game-day-2027-01-02", entry_ordinal=1)
    values.update(changes)
    return HeroDuelObservation(**values)


class HeroDuelSemanticsTests(unittest.TestCase):
    def test_exact_current_survival_needs_no_daily_row(self):
        current = observation()
        self.assertTrue(hero_duel_current_survival(current))
        for changes in ({"event_variant": "hero_duel_glory"}, {"event_identity": ""},
                {"event_active": False}, {"runtime_profile_id": "retired-bliss"},
                {"target_provenance": "bliss-native"}):
            self.assertFalse(hero_duel_current_survival(replace(current, **changes)))

    def test_first_five_require_positive_availability_not_portrait_presence(self):
        current = observation()
        self.assertEqual(hero_duel_first_five_eligible(current), ("a", "b", "c", "d", "e"))
        self.assertIsNone(hero_duel_first_five_eligible(replace(current, eligible_hero_ids=None)))
        self.assertIsNone(hero_duel_first_five_eligible(replace(current, eligible_hero_ids=())))
        self.assertIsNone(hero_duel_first_five_eligible(replace(current, displayed_hero_ids=("a", "a"))))

    def test_defense_membership_not_slot_order_and_saved_ack(self):
        current = observation(defense_hero_ids=("e", "d", "c", "b", "a"))
        self.assertTrue(hero_duel_defense_lineup_valid(current))
        self.assertTrue(hero_duel_defense_ready(current))
        self.assertFalse(hero_duel_defense_lineup_valid(replace(current, defense_hero_ids=("f", "d", "c", "b", "a"))))
        self.assertFalse(hero_duel_defense_ready(replace(current, defense_save_acknowledged=False)))
        self.assertFalse(hero_duel_defense_lineup_valid(replace(current, formation_slot_states=("active",) * 4)))

    def test_attack_preserves_complete_lineup_and_only_fills_known_empty_slots(self):
        complete = observation(screen_state="attack_formation", eligible_hero_ids=None)
        self.assertTrue(hero_duel_attack_lineup_valid(complete))
        self.assertEqual(hero_duel_attack_fill(complete), ())
        partial = replace(complete, formation_slot_states=("active", "empty", "active", "empty", "empty"),
            displayed_hero_ids=("a", "b", "c", "d"), eligible_hero_ids=("a", "c", "d"))
        self.assertEqual(hero_duel_attack_fill(partial), ("a", "c", "d"))
        self.assertFalse(hero_duel_attack_lineup_valid(partial))
        self.assertIsNone(hero_duel_attack_fill(replace(partial, eligible_hero_ids=None)))
        self.assertIsNone(hero_duel_attack_fill(replace(partial,
            formation_slot_states=("active", "unknown", "active", "empty", "empty"))))

    def test_current_quota_preserves_manual_usage_without_claiming_cycles(self):
        for remaining in (0, 1, 2, 3):
            current = observation(free_entries_remaining=remaining)
            self.assertEqual(hero_duel_cycle_budget(current), (remaining, 3 - remaining))
            self.assertFalse(hero_duel_cycle_postcondition_verified(current, current,
                ordinal=1, game_day_id=current.game_day_id))
        for invalid in (None, 4, -1, True):
            self.assertIsNone(hero_duel_cycle_budget(observation(free_entries_remaining=invalid)))

    def test_entry_requires_current_free_opponent_and_active_lineups_not_paid_inventory(self):
        attack = observation(screen_state="attack_formation", target_identity="hero-duel-attack-challenge",
            free_entries_remaining=1)
        self.assertTrue(hero_duel_entry_authorizeable(attack, ordinal=1, game_day_id=attack.game_day_id))
        for changes in ({"entry_cost_known": False}, {"entry_cost": 1}, {"free_entries_remaining": 0},
                {"listed_opponent_free": False}, {"free_opponent_selected": False},
                {"formation_slot_states": ("active",) * 4 + ("unknown",)},
                {"defense_save_acknowledged": False}, {"activate_visible": True},
                {"premium_prompt_visible": True}, {"overlay_state": "unknown"}, {"target_roi": None}):
            self.assertFalse(hero_duel_entry_authorizeable(replace(attack, **changes),
                ordinal=1, game_day_id=attack.game_day_id))
        self.assertFalse(hero_duel_entry_authorizeable(replace(attack, entry_ordinal=4),
            ordinal=4, game_day_id=attack.game_day_id))

    def test_flee_requires_loaded_battle_exit_warning_and_only_flee_control(self):
        warning = observation(screen_state="flee_warning", target_identity="hero-duel-warning-flee",
            cycle_battle_loaded=True, cycle_exit_confirmed=True,
            flee_warning_visible=True, flee_control_visible=True, fight_control_visible=True)
        self.assertTrue(hero_duel_flee_authorizeable(warning, ordinal=1, game_day_id=warning.game_day_id))
        for changes in ({"cycle_battle_loaded": False}, {"cycle_exit_confirmed": False},
                {"flee_warning_visible": False}, {"flee_control_visible": False},
                {"target_identity": "hero-duel-warning-fight"}, {"premium_prompt_visible": True}):
            self.assertFalse(hero_duel_flee_authorizeable(replace(warning, **changes),
                ordinal=1, game_day_id=warning.game_day_id))

    def test_cycle_requires_counter_decrement_and_full_battle_result_path(self):
        before = observation(free_entries_remaining=1)
        after = replace(before, free_entries_remaining=0, cycle_battle_loaded=True,
            cycle_exit_confirmed=True, cycle_flee_confirmed=True, cycle_loss_result_seen=True,
            cycle_continue_confirmed=True)
        self.assertTrue(hero_duel_cycle_postcondition_verified(before, after,
            ordinal=2, game_day_id=before.game_day_id))
        for changes in ({"free_entries_remaining": 1}, {"event_identity": "different"},
                {"cycle_flee_confirmed": False}, {"cycle_loss_result_seen": False}):
            self.assertFalse(hero_duel_cycle_postcondition_verified(before, replace(after, **changes),
                ordinal=2, game_day_id=before.game_day_id))

    def test_policy_uses_current_free_quota_without_universal_ordinal_equation(self):
        common = dict(event_identity="survival-event", ordinal=1, game_day_id="game-day-2027-01-02")
        hero_duel_policy_preconditions("hero_duel_free_entry", **common, free_allowance_before=1)
        hero_duel_policy_preconditions("hero_duel_flee", **common, free_allowance_at_flee=0)
        for amount in (0, -1, 4, None):
            with self.assertRaises(ValueError):
                hero_duel_policy_preconditions("hero_duel_free_entry", **common, free_allowance_before=amount)

    def test_action_keys_preserve_reset_ordinal_and_child_identity(self):
        fields = dict(runtime_scope="runtime:fixed", account_id="primary-account", server_id="primary-server",
            game_day_id="game-day-2027-01-02", ordinal=1, action_kind="hero_duel_free_entry")
        entry = hero_duel_action_key(**fields)
        self.assertEqual(entry, hero_duel_action_key(**fields))
        for changes in ({"ordinal": 2}, {"action_kind": "hero_duel_flee"}, {"game_day_id": "game-day-2027-01-03"}):
            self.assertNotEqual(entry, hero_duel_action_key(**{**fields, **changes}))
        with self.assertRaises(ValueError):
            hero_duel_action_key(**{**fields, "ordinal": 0})

    def test_source_requires_native_binding_and_valid_bounds(self):
        current = observation()
        self.assertTrue(hero_duel_source_valid(current))
        for changes in ({"target_roi": (100, 100, 900, 1200)}, {"source_frame_sha256": "invalid"}, {"evidence_refs": ()}):
            self.assertFalse(hero_duel_source_valid(replace(current, **changes)))


if __name__ == "__main__":
    unittest.main()
