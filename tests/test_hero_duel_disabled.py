from __future__ import annotations

from dataclasses import replace
import unittest

from tasks.hero_duel_disabled import (
    HERO_DUEL_SURVIVAL,
    HeroDuelObservation,
    hero_duel_action_key,
    hero_duel_attack_fill,
    hero_duel_attack_lineup_valid,
    hero_duel_current_survival,
    hero_duel_cycle_budget,
    hero_duel_cycle_postcondition_verified,
    hero_duel_defense_ready,
    hero_duel_entry_authorizeable,
    hero_duel_first_five_eligible,
    hero_duel_flee_authorizeable,
    hero_duel_policy_preconditions,
    hero_duel_source_valid,
)
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID, BLUESTACKS_NATIVE_TARGET_PROVENANCE


def observation(**changes) -> HeroDuelObservation:
    values = {
        "screen_state": "hero_duel_overview",
        "source_frame_sha256": "a" * 64,
        "target_provenance": BLUESTACKS_NATIVE_TARGET_PROVENANCE,
        "evidence_refs": ("synthetic:hero-duel-route",),
        "runtime_profile_id": ACTIVE_RUNTIME_PROFILE_ID,
        "event_identity": "synthetic-survival-event",
        "event_variant": HERO_DUEL_SURVIVAL,
        "event_active": True,
        "free_entries_remaining": 3,
        "entry_cost": 0,
        "entry_cost_known": True,
        "pass_balance": 123,
        "excluded_hero_ids": ("support-hero",),
        "displayed_hero_ids": (
            "hero-a",
            "support-hero",
            "hero-b",
            "hero-c",
            "hero-d",
            "hero-e",
            "hero-f",
        ),
        "defense_hero_ids": ("hero-a", "hero-b", "hero-c", "hero-d", "hero-e"),
        "defense_save_acknowledged": True,
        "attack_hero_ids": ("hero-a", "hero-b", "hero-c", "hero-d", "hero-e"),
        "attack_slots_populated": 5,
        "listed_opponent_free": True,
        "free_opponent_selected": True,
        "challenge_now_visible": False,
        "activate_visible": False,
        "premium_prompt_visible": False,
        "battle_board_visible": False,
        "wave_text": "",
        "battle_exit_visible": False,
        "flee_warning_visible": False,
        "flee_control_visible": False,
        "fight_control_visible": False,
        "loss_result_visible": False,
        "tap_to_continue_visible": False,
        "cycle_battle_loaded": False,
        "cycle_exit_confirmed": False,
        "cycle_flee_confirmed": False,
        "cycle_loss_result_seen": False,
        "cycle_continue_confirmed": False,
        "terminal_home_verified": False,
        "target_identity": "hero-duel-overview-challenge",
        "target_roi": (100, 1080, 700, 1180),
        "game_day_id": "reset-deadline:2027-01-02T00:00:00Z",
        "entry_ordinal": 1,
    }
    values.update(changes)
    return HeroDuelObservation(**values)


class HeroDuelSemanticsTests(unittest.TestCase):
    def test_exact_current_survival_needs_no_daily_row(self):
        current = observation()
        self.assertTrue(hero_duel_current_survival(current))
        self.assertFalse(
            hero_duel_current_survival(replace(current, event_variant="hero_duel_glory"))
        )
        self.assertFalse(hero_duel_current_survival(replace(current, event_identity="")))
        self.assertFalse(hero_duel_current_survival(replace(current, event_active=False)))
        self.assertFalse(
            hero_duel_current_survival(replace(current, runtime_profile_id="retired-bliss"))
        )
        self.assertFalse(
            hero_duel_current_survival(replace(current, target_provenance="bliss-native"))
        )

    def test_exclusion_set_selects_first_five_displayed_eligible_heroes(self):
        current = observation()
        self.assertEqual(
            hero_duel_first_five_eligible(current),
            ("hero-a", "hero-b", "hero-c", "hero-d", "hero-e"),
        )
        self.assertIsNone(
            hero_duel_first_five_eligible(replace(current, excluded_hero_ids=None))
        )
        self.assertIsNone(
            hero_duel_first_five_eligible(
                replace(current, displayed_hero_ids=("hero-a", "support-hero", "hero-b"))
            )
        )
        self.assertIsNone(
            hero_duel_first_five_eligible(
                replace(current, displayed_hero_ids=("hero-a", "hero-a", "hero-b"))
            )
        )

    def test_defense_requires_exact_first_five_and_saved_ack(self):
        current = observation()
        self.assertTrue(hero_duel_defense_ready(current))
        self.assertFalse(
            hero_duel_defense_ready(
                replace(current, defense_hero_ids=("hero-b", "hero-a", "hero-c", "hero-d", "hero-e"))
            )
        )
        self.assertFalse(hero_duel_defense_ready(replace(current, defense_save_acknowledged=False)))
        self.assertFalse(
            hero_duel_defense_ready(replace(current, defense_hero_ids=("hero-a", "hero-b")))
        )

    def test_attack_fill_preserves_valid_complete_lineup_and_only_fills_gaps(self):
        complete = observation(
            screen_state="attack_formation",
            target_identity="hero-duel-attack-challenge",
            attack_hero_ids=("hero-b", "hero-c", "hero-d", "hero-e", "hero-f"),
        )
        self.assertTrue(hero_duel_attack_lineup_valid(complete))
        self.assertEqual(hero_duel_attack_fill(complete), ())

        partial = replace(
            complete,
            attack_hero_ids=("hero-b", "hero-c"),
            attack_slots_populated=2,
        )
        self.assertEqual(hero_duel_attack_fill(partial), ("hero-a", "hero-d", "hero-e"))
        self.assertFalse(hero_duel_attack_lineup_valid(partial))
        self.assertIsNone(
            hero_duel_attack_fill(
                replace(partial, attack_hero_ids=("hero-b", "support-hero"), attack_slots_populated=2)
            )
        )
        self.assertIsNone(hero_duel_attack_fill(replace(partial, attack_slots_populated=3)))

    def test_free_allowance_is_not_itself_a_confirmed_cycle_count(self):
        self.assertEqual(hero_duel_cycle_budget(observation(free_entries_remaining=3)), (3, 0))
        self.assertEqual(hero_duel_cycle_budget(observation(free_entries_remaining=2)), (2, 1))
        exhausted = observation(free_entries_remaining=0)
        self.assertEqual(hero_duel_cycle_budget(exhausted), (0, 3))
        self.assertIsNone(hero_duel_cycle_budget(observation(free_entries_remaining=None)))
        self.assertIsNone(hero_duel_cycle_budget(observation(free_entries_remaining=4)))
        self.assertFalse(
            hero_duel_cycle_postcondition_verified(
                exhausted, exhausted, ordinal=3, game_day_id=exhausted.game_day_id
            )
        )

    def test_entry_requires_exact_free_listed_opponent_and_lineups(self):
        attack = observation(
            screen_state="attack_formation",
            target_identity="hero-duel-attack-challenge",
            free_entries_remaining=2,
            entry_ordinal=2,
        )
        self.assertTrue(
            hero_duel_entry_authorizeable(
                attack, ordinal=2, game_day_id=attack.game_day_id
            )
        )
        for changes in (
            {"entry_cost_known": False},
            {"entry_cost": 1},
            {"free_entries_remaining": 0},
            {"pass_balance": None},
            {"listed_opponent_free": False},
            {"free_opponent_selected": False},
            {"attack_slots_populated": 4},
            {"defense_save_acknowledged": False},
            {"activate_visible": True},
            {"premium_prompt_visible": True},
            {"overlay_state": "unknown"},
            {"target_roi": None},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(
                    hero_duel_entry_authorizeable(
                        replace(attack, **changes),
                        ordinal=2,
                        game_day_id=attack.game_day_id,
                    )
                )
        self.assertFalse(hero_duel_entry_authorizeable(attack, ordinal=1, game_day_id=attack.game_day_id))
        self.assertFalse(hero_duel_entry_authorizeable(attack, ordinal=2, game_day_id="other-reset"))

    def test_flee_requires_loaded_battle_warning_and_only_flee_control(self):
        warning = observation(
            screen_state="flee_warning",
            target_identity="hero-duel-warning-flee",
            target_roi=(400, 600, 600, 700),
            entry_ordinal=2,
            cycle_battle_loaded=True,
            battle_exit_visible=True,
            flee_warning_visible=True,
            flee_control_visible=True,
        )
        self.assertTrue(
            hero_duel_flee_authorizeable(warning, ordinal=2, game_day_id=warning.game_day_id)
        )
        for changes in (
            {"cycle_battle_loaded": False},
            {"battle_exit_visible": False},
            {"flee_warning_visible": False},
            {"flee_control_visible": False},
            {"fight_control_visible": True},
            {"premium_prompt_visible": True},
        ):
            self.assertFalse(
                hero_duel_flee_authorizeable(
                    replace(warning, **changes),
                    ordinal=2,
                    game_day_id=warning.game_day_id,
                )
            )

    def test_completed_cycle_requires_loss_path_and_exact_free_pass_deltas(self):
        before = observation(free_entries_remaining=3)
        after = replace(
            before,
            free_entries_remaining=2,
            cycle_battle_loaded=True,
            cycle_exit_confirmed=True,
            cycle_flee_confirmed=True,
            cycle_loss_result_seen=True,
            cycle_continue_confirmed=True,
        )
        self.assertTrue(
            hero_duel_cycle_postcondition_verified(
                before, after, ordinal=1, game_day_id=before.game_day_id
            )
        )
        self.assertFalse(
            hero_duel_cycle_postcondition_verified(
                before, replace(after, free_entries_remaining=3),
                ordinal=1, game_day_id=before.game_day_id,
            )
        )
        self.assertFalse(
            hero_duel_cycle_postcondition_verified(
                before, replace(after, pass_balance=122),
                ordinal=1, game_day_id=before.game_day_id,
            )
        )
        self.assertFalse(
            hero_duel_cycle_postcondition_verified(
                before, replace(after, event_identity="different-event"),
                ordinal=1, game_day_id=before.game_day_id,
            )
        )
        self.assertFalse(
            hero_duel_cycle_postcondition_verified(
                before, replace(after, cycle_flee_confirmed=False),
                ordinal=1, game_day_id=before.game_day_id,
            )
        )

    def test_policy_preconditions_bind_v2_event_instance_ordinal_reset_and_balances(self):
        event_identity = "survival-event-synthetic-001"
        common = {
            "event_identity": event_identity,
            "ordinal": 2,
            "game_day_id": "game-day-2027-01-02",
        }
        entry = hero_duel_policy_preconditions(
            "hero_duel_free_entry",
            **common,
            free_allowance_before=2,
            pass_balance_before=123,
        )
        self.assertEqual(
            entry[:7],
            (
                "hero_duel_product=hero_duel",
                "hero_duel_product_revision=hero_duel-v2",
                f"hero_duel_event_identity={event_identity}",
                "hero_duel_free_allowance_before=2",
                "hero_duel_pass_balance_before=123",
                "hero_duel_entry_ordinal=2",
                "hero_duel_entry_reset=game-day-2027-01-02",
            ),
        )
        self.assertEqual(len(entry), 16)
        self.assertIn("entry_cost_exactly_zero", entry)
        self.assertIn("premium_prompt_absent", entry)
        flee = hero_duel_policy_preconditions(
            "hero_duel_flee",
            **common,
            free_allowance_at_flee=1,
            pass_balance_before=123,
        )
        self.assertEqual(flee[:5], (
            "hero_duel_product=hero_duel",
            "hero_duel_product_revision=hero_duel-v2",
            f"hero_duel_event_identity={event_identity}",
            "hero_duel_free_allowance_at_flee=1",
            "hero_duel_pass_balance_before=123",
        ))
        self.assertEqual(len(flee), 16)
        self.assertIn("fight_control_excluded", flee)
        self.assertIn("entry_same_cycle_ordinal_confirmed", flee)
        other_event = hero_duel_policy_preconditions(
            "hero_duel_flee",
            **{**common, "event_identity": "survival-event-synthetic-002"},
            free_allowance_at_flee=1,
            pass_balance_before=123,
        )
        self.assertNotEqual(flee[:3], other_event[:3])
        save = hero_duel_policy_preconditions(
            "hero_duel_save_defense",
            **common,
        )
        self.assertEqual(save[:3], entry[:3])
        self.assertIn("first_five_eligible_heroes_bound", save)
        with self.assertRaises(ValueError):
            hero_duel_policy_preconditions(
                "hero_duel_free_entry",
                **common,
                free_allowance_before=0,
                pass_balance_before=123,
            )
        with self.assertRaises(ValueError):
            hero_duel_policy_preconditions(
                "hero_duel_flee",
                **common,
                free_allowance_at_flee=4,
                pass_balance_before=123,
            )
        with self.assertRaises(ValueError):
            hero_duel_policy_preconditions(
                "hero_duel_free_entry",
                **common,
                free_allowance_before=2,
                pass_balance_before=-1,
            )
        with self.assertRaises(ValueError):
            hero_duel_policy_preconditions(
                "hero_duel_free_entry",
                **common,
                free_allowance_before=3,
                pass_balance_before=123,
            )
        with self.assertRaises(ValueError):
            hero_duel_policy_preconditions(
                "hero_duel_flee",
                **common,
                free_allowance_at_flee=2,
                pass_balance_before=123,
            )
    def test_action_keys_are_stable_but_separate_by_reset_ordinal_and_child(self):
        fields = {
            "runtime_scope": "runtime:fixed",
            "account_id": "primary-account",
            "server_id": "primary-server",
            "game_day_id": "reset-deadline:2027-01-02T00:00:00Z",
            "ordinal": 1,
        }
        entry = hero_duel_action_key(**fields, action_kind="hero_duel_free_entry")
        self.assertEqual(entry, hero_duel_action_key(**fields, action_kind="hero_duel_free_entry"))
        self.assertNotEqual(entry, hero_duel_action_key(**{**fields, "ordinal": 2}, action_kind="hero_duel_free_entry"))
        self.assertNotEqual(entry, hero_duel_action_key(**fields, action_kind="hero_duel_flee"))
        self.assertNotEqual(
            entry,
            hero_duel_action_key(
                **{**fields, "game_day_id": "reset-deadline:2027-01-03T00:00:00Z"},
                action_kind="hero_duel_free_entry",
            ),
        )
        with self.assertRaises(ValueError):
            hero_duel_action_key(**{**fields, "ordinal": 0}, action_kind="hero_duel_free_entry")

    def test_source_target_requires_current_native_profile_and_bounds(self):
        current = observation()
        self.assertTrue(hero_duel_source_valid(current))
        self.assertFalse(hero_duel_source_valid(replace(current, target_roi=(100, 100, 900, 1200))))
        self.assertFalse(hero_duel_source_valid(replace(current, source_frame_sha256="not-a-hash")))
        self.assertFalse(hero_duel_source_valid(replace(current, evidence_refs=())))


if __name__ == "__main__":
    unittest.main()
