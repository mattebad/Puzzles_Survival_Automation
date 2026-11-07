from __future__ import annotations

from types import SimpleNamespace
import unittest

import numpy as np

import scripts.hero_duel_bluestacks as route


class HeroDuelVisionReplayTests(unittest.TestCase):
    def setUp(self):
        self.now = [1_800_000_000.0]
        self.vision = route.HeroDuelVision(
            checkpoint=lambda: None,
            reset_id="game-day-2027-01-02",
            utc_clock=lambda: self.now[0],
        )
        self.frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        self.lines = ()
        self.vision._lines = lambda _frame: self.lines

    @staticmethod
    def _line(text, y, x=100):
        return {
            "text": text,
            "norm": route._norm(text),
            "box": (x, y, x + max(40, len(text) * 8), y + 18),
            "center": (x + max(40, len(text) * 8) // 2, y + 9),
        }

    def _capture(self):
        return SimpleNamespace(frame=self.frame)

    def test_current_survival_screen_binds_countdown_instance_and_balances(self):
        self.lines = tuple(self._line(text, 80 + index * 40) for index, text in enumerate((
            "Hero Duel Survival", "Challenge", "Free 3/3", "Pass 123", "23:59:59",
        )))
        page = self.vision.recognize(self._capture(), target_hint=("challenge-now", "challenge"))
        self.assertEqual(page["screen_state"], "hero_duel_overview")
        self.assertTrue(page["event_timer_visible"])
        self.assertTrue(page["event_active"])
        self.assertRegex(page["event_identity"], r"^survival_game-day-2027-01-02_ends_[0-9]+$")
        self.assertEqual(page["free_entries_remaining"], 3)
        self.assertEqual(page["pass_balance"], 123)
        self.assertEqual(page["target_identity"], "challenge-now")
        self.assertIsNotNone(page["target_roi"])


    def test_dueling_legend_upsell_requires_challenge_now_and_never_binds_activate(self):
        self.lines = tuple(self._line(text, 80 + index * 40) for index, text in enumerate((
            "Dueling Legend", "Challenge Now", "Activate", "23:59:59",
        )))
        page = self.vision.recognize(self._capture(), target_hint=("hero-duel-challenge-now", "challenge now"))
        self.assertEqual(page["screen_state"], "challenge_upsell")
        self.assertEqual(page["target_identity"], "hero-duel-challenge-now")
        self.assertIsNotNone(page["target_roi"])
        self.assertNotEqual(page["target_roi"], self.vision.bind_phrase(self.lines, "activate"))

    def test_countdown_deadline_is_stable_but_changed_instance_is_rejected(self):
        self.lines = tuple(self._line(text, 80 + index * 40) for index, text in enumerate((
            "Hero Duel Survival", "Challenge", "02:00:00",
        )))
        first = self.vision.recognize(self._capture())
        self.now[0] += 60
        self.lines = tuple(self._line(text, 80 + index * 40) for index, text in enumerate((
            "Hero Duel Survival", "Challenge", "01:59:00",
        )))
        same = self.vision.recognize(self._capture())
        self.assertEqual(first["event_identity"], same["event_identity"])
        self.now[0] += 60
        self.lines = tuple(self._line(text, 80 + index * 40) for index, text in enumerate((
            "Hero Duel Survival", "Challenge", "02:58:00",
        )))
        changed = self.vision.recognize(self._capture())
        self.assertEqual(changed["overlay_state"], "event_identity_changed")
        self.assertFalse(self.vision.current_event_valid)

    def test_glory_and_unknown_page_never_bind_a_survival_control(self):
        self.lines = (self._line("Hero Duel Glory", 80), self._line("Challenge Now", 120))
        page = self.vision.recognize(self._capture(), target_hint=("challenge-now", "challenge now"))
        self.assertEqual(page["screen_state"], "unknown")
        self.assertIsNone(page["event_identity"])
        self.assertIsNone(page["target_roi"])
        self.assertFalse(page["event_active"])

    def test_emergency_exclusions_and_first_eligible_defense_row_are_read(self):
        self.lines = (
            self._line("Emergency Details", 50),
            self._line("Excluded Heroes", 130),
            self._line("Avery", 170, 80),
            self._line("Bailey", 170, 200),
            self._line("Cora", 170, 320),
            self._line("Diana", 170, 440),
            self._line("Elias", 170, 560),
            self._line("Freya", 170, 680),
            self._line("23:59:59", 1200),
        )
        details = self.vision.recognize(self._capture())
        self.assertEqual(details["screen_state"], "emergency_details")
        self.assertEqual(details["excluded_hero_ids"], ("Avery", "Bailey", "Cora", "Diana", "Elias", "Freya"))
        self.vision.excluded = ("Avery",)
        self.lines = (
            self._line("Defense Formation", 80),
            self._line("Avery", 150, 80),
            self._line("Bailey", 150, 200),
            self._line("Cora", 150, 320),
            self._line("Diana", 150, 440),
            self._line("Elias", 150, 560),
            self._line("Save Form", 1100),
            self._line("23:59:59", 1200),
        )
        formation = self.vision.recognize(self._capture())
        self.assertEqual(formation["screen_state"], "defense_formation")
        self.assertEqual(formation["defense_hero_ids"], ("Avery", "Bailey", "Cora", "Diana", "Elias"))

    def test_emergency_details_x_requires_one_recognized_close_control(self):
        header = self._line("Emergency Details", 100, 280)
        header["word_boxes"] = (
            ("Emergency", (280, 100, 360, 118)),
            ("Details", (370, 100, 430, 118)),
        )
        close = self._line("X", 100, 730)
        close["word_boxes"] = (("X", (730, 100, 750, 120)),)
        self.lines = (header, close)
        page = self.vision.recognize(
            self._capture(),
            target_hint=("hero-duel-emergency-close-x", "emergency close x"),
        )
        self.assertEqual(page["screen_state"], "emergency_details")
        self.assertEqual(page["target_identity"], "hero-duel-emergency-close-x")
        self.assertEqual(page["target_roi"], (727, 97, 753, 123))
        self.assertIsNone(self.vision.emergency_close_x_roi((header,)))

    def test_first_free_opponent_row_binds_its_button_when_multiple_are_listed(self):
        def opponent_line(name, y, free_x):
            line = self._line(f"{name} Free", y)
            line["word_boxes"] = (
                (name, (100, y, 260, y + 18)),
                ("Free", (free_x, y, free_x + 50, y + 18)),
            )
            return line

        lines = (
            opponent_line("Player One", 200, 700),
            opponent_line("Player Two", 400, 700),
            opponent_line("Player Three", 600, 700),
        )
        row = self.vision.first_free_opponent_row(lines)
        self.assertEqual(row["text"], "Player One Free")
        self.assertEqual(row["free_button_roi"], (700, 200, 750, 218))
        self.assertIsNone(self.vision.first_free_opponent_row((
            opponent_line("Player One", 200, 700),
            opponent_line("Player Two", 200, 500),
        )))
        self.assertIsNone(self.vision.first_free_opponent_row((self._line("Player One Free", 200),)))



    def test_combined_ocr_line_yields_distinct_hero_cards_and_exact_duplicate_target(self):
        def token_line(names, y, *, gap):
            words = []
            x = 80
            for name in names:
                width = max(32, len(name) * 8)
                words.append((name, (x, y, x + width, y + 18)))
                x += width + gap
            line = self._line(" ".join(names), y, 80)
            line["box"] = (80, y, x, y + 18)
            line["center"] = ((80 + x) // 2, y + 9)
            line["word_boxes"] = tuple(words)
            return line

        lines = (
            self._line("Defense Formation", 80),
            token_line(("Avery", "Bailey", "Cora", "Diana", "Elias"), 150, gap=40),
            token_line(("Avery", "Freya", "Gabrielle", "Hazel", "Iris"), 600, gap=40),
        )
        self.assertEqual(self.vision.hero_rows(lines), (
            ("Avery", "Bailey", "Cora", "Diana", "Elias"),
            ("Avery", "Freya", "Gabrielle", "Hazel", "Iris"),
        ))
        self.assertEqual(
            self.vision.heading_row(lines, ("defense formation",)),
            ("Avery", "Bailey", "Cora", "Diana", "Elias"),
        )
        removal_roi = self.vision.hero_selection_roi(lines, "Avery", "defense_formation", add=False)
        addition_roi = self.vision.hero_selection_roi(lines, "Avery", "defense_formation", add=True)
        self.assertIsNotNone(removal_roi)
        self.assertIsNotNone(addition_roi)
        self.assertNotEqual(removal_roi, addition_roi)

    def test_hero_card_word_grouping_preserves_multiword_names_and_rejects_ambiguous_targets(self):
        line = self._line("Avery Beth Cora", 150)
        line["word_boxes"] = (
            ("Avery", (80, 150, 120, 168)),
            ("Beth", (128, 150, 160, 168)),
            ("Cora", (210, 150, 250, 168)),
        )
        self.assertEqual(self.vision.hero_rows((line,)), (("Avery Beth", "Cora"),))
        heading = self._line("Defense Formation", 80)
        formation = self._line("Avery Bailey Cora Diana Elias", 150)
        formation["word_boxes"] = tuple(
            (name, (80 + index * 100, 150, 120 + index * 100, 168))
            for index, name in enumerate(("Avery", "Bailey", "Cora", "Diana", "Elias"))
        )
        duplicate = self._line("Avery Avery", 600)
        duplicate["word_boxes"] = (
            ("Avery", (80, 600, 120, 618)),
            ("Avery", (220, 600, 260, 618)),
        )
        lines = (heading, formation, duplicate)
        self.assertIsNone(self.vision.hero_selection_roi(lines, "Avery", "defense_formation", add=True))
class HeroDuelNativeBindingTests(unittest.TestCase):
    def test_native_request_requires_exact_occurrence_identity_lock_and_budget(self):
        request = SimpleNamespace(
            flow_id=route.FLOW_ID,
            product_id=route.PRODUCT_ID,
            product_revision=route.PRODUCT_REVISION,
            runtime_profile_id=route.PROFILE_ID,
            identity=SimpleNamespace(task_id=route.PRODUCT_ID, reset_id="game-day-2027-01-02"),
            occurrence_key="occ:hero-duel:current-reset:1",
            max_inputs=route.MAX_INPUTS,
            max_actions=route.MAX_ACTIONS,
            runtime_input_lock=SimpleNamespace(held=True, owner="automation-service"),
        )
        route._validate_native_request(request)
        request.occurrence_key = " "
        with self.assertRaises(ValueError):
            route._validate_native_request(request)


if __name__ == "__main__":
    unittest.main()
