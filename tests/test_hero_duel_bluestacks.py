from __future__ import annotations

from types import SimpleNamespace
import json
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch

import cv2
import unittest

import numpy as np

import scripts.hero_duel_bluestacks as route
from safe_action_core.store import SafetyStore
from safe_action_core.models import ActionIntent, PolicyDecision, PolicyResult


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
        self.vision._lines = lambda _frame, **_kwargs: self.lines

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

    def test_exhausted_free_quota_requires_the_current_paid_quote_not_absent_free_text(self):
        challenge = self._line("Challenge", 1140, 300)
        paid = self._line("1/125", 1080, 330)
        self.assertEqual(self.vision._entry_allowance((paid, challenge), "hero_duel_overview"), 0)
        self.assertIsNone(self.vision._entry_allowance((challenge,), "hero_duel_overview"))
        self.assertIsNone(self.vision._entry_allowance((paid, challenge), "attack_formation"))
        distant = self._line("1/125", 200, 330)
        self.assertIsNone(self.vision._entry_allowance((distant, challenge), "hero_duel_overview"))
        free = self._line("Free 1/1", 1080, 330)
        self.assertEqual(self.vision._entry_allowance((free, challenge), "hero_duel_overview"), 1)




class HeroDuelNativeObserverRegressionTests(unittest.TestCase):
    """Exercise OCR grouping and native semantics, not producer result echoes."""

    def setUp(self):
        self.identity = SimpleNamespace(reset_id="game-day-2027-01-02", account_id="account", server_id="server")
        self.records = {}
        context = SimpleNamespace(
            session=SimpleNamespace(owner="test-owner"), runtime=SimpleNamespace(),
            action_store=SimpleNamespace(get_action_by_key=self.records.get, has_action_block=lambda: False),
            identity=self.identity, flow_id=route.FLOW_ID, product_id=route.PRODUCT_ID,
            product_revision=route.PRODUCT_REVISION, runtime_profile_id=route.PROFILE_ID,
            settle_seconds=0, checkpoint=lambda: None, utc_clock=lambda: 1_800_000_000,
            is_clean_home=lambda _frame: False,
            accounting=lambda: SimpleNamespace(input_count=0, verified=True),
        )
        self.flow = route.HeroDuelNativeFlow(context, {})
        self.flow.event_identity = "survival-current-event"
        self.flow.vision.event_identity = self.flow.event_identity
        self.flow.vision.current_event_valid = True
        self.capture = SimpleNamespace(
            frame=np.zeros((1280, 800, 3), dtype=np.uint8),
            sha256="a" * 64, path="replay/current.png",
        )

    def page(self, texts, hint=None):
        # Only OCR transport is fake; grouping, state recognition, target binding
        # and conversion to task observations all run their production code.
        data = {key: [] for key in ("text", "conf", "left", "top", "width", "height")}
        for index, text in enumerate(texts):
            for key, value in zip(data, (text, "95", 100, 60 + index * 60, min(len(text) * 8, 600), 20)):
                data[key].append(value)
        with patch.object(route, "tesseract_data", return_value=data):
            return self.flow.observe(self.capture, hint)

    def entry_record(self, ordinal=1, status="CONFIRMED"):
        facts = route.hero_duel_policy_preconditions(
            "hero_duel_free_entry", event_identity=self.flow.event_identity,
            ordinal=ordinal, game_day_id=self.identity.reset_id,
            free_allowance_before=4 - ordinal,
        )
        self.records[self.flow.action_key(ordinal, "hero_duel_free_entry")] = {
            "final_status": status, "policy_request_json": json.dumps({"semantic_preconditions": facts}),
        }

    def test_warning_retains_confirmed_entry_allowance_without_counter_ocr_or_fight_target(self):
        self.entry_record(status=route.ActionStatus.CONFIRMED.value)
        self.flow.vision.battle_loaded = True
        self.flow.vision.exit_confirmed = True
        page = self.page(("Warning", "Flee will lose points", "Fight", "Flee"),
                         ("hero-duel-warning-flee", "flee"))
        self.assertIsNone(page["free_entries_remaining"])
        observation = self.flow._observation(self.capture, page, 1)
        self.assertEqual(observation.free_entries_remaining, 2)
        self.assertTrue(observation.fight_control_visible)
        self.assertTrue(route.hero_duel_flee_authorizeable(
            observation, ordinal=1, game_day_id=self.identity.reset_id))
        fight = self.page(("Warning", "Fight", "Flee"), ("hero-duel-warning-fight", "fight"))
        self.assertIsNone(fight["target_roi"])
        self.assertEqual(page["target_roi"], (97, 237, 135, 263))
        self.assertFalse(observation.battle_exit_visible)

    def test_unknown_or_absent_entry_never_supplies_missing_warning_counters(self):
        for status in (None, route.ActionStatus.UNRESOLVED.value):
            self.records.clear()
            if status is not None:
                self.entry_record(status=status)
            page = self.page(("Warning", "Fight", "Flee"), ("hero-duel-warning-flee", "flee"))
            observed = self.flow._observation(self.capture, page, 1)
            self.assertIsNone(observed.free_entries_remaining)

    def test_visible_counter_contradiction_is_not_overwritten(self):
        self.entry_record(status=route.ActionStatus.CONFIRMED.value)
        page = self.page(("Warning", "Fight", "Flee", "Free 1/3", "Pass 122"),
                         ("hero-duel-warning-flee", "flee"))
        observed = self.flow._observation(self.capture, page, 1)
        self.assertEqual(observed.free_entries_remaining, 1)

    def test_actual_result_vocabulary_binds_continue_but_not_embedded_buy_now(self):
        texts = ("Rank: 10000 Unchanged", "984(-16)", "Reward List", "Buy Now", "Tap to Continue")
        page = self.page(texts, ("hero-duel-loss-continue", "tap to continue"))
        self.assertEqual(page["screen_state"], "loss_result")
        self.assertEqual(page["overlay_state"], "none")
        self.assertIsNotNone(page["target_roi"])
        ad = self.page(texts, ("ad", "buy now"))
        self.assertIsNone(ad["target_roi"])

    def test_actual_formation_headings_and_unreadable_portraits(self):
        defense = self.page(("Hero Lineup", "McCarty", "Save Form."))
        self.assertEqual(defense["screen_state"], "defense_formation")
        attack = self.page(("Hero Lineup", "Opponent Formation", "Your Formation", "Ulrik", "Challenge"))
        self.assertEqual(attack["screen_state"], "attack_formation")
        self.assertEqual(attack["eligible_hero_ids"], None)
        self.assertFalse(route.hero_duel_attack_lineup_valid(self.flow._observation(self.capture, attack, 1)))
        details = self.page(("Emergency Details", "Heroes cannot use", "Confirm"))
        self.flow._navigation_tap = lambda *_args: {"page": {"screen_state": "defense_formation"}}
        self.assertEqual(self.flow._dismiss_emergency(details)["screen_state"], "defense_formation")


    def test_native_finalize_supplies_adapter_identity_without_claiming_completion(self):
        result = self.flow._finalize()
        self.assertEqual(result["preset_id"], route.PRODUCT_ID)
        self.assertEqual(result["runtime_profile_id"], route.PROFILE_ID)
        self.assertEqual(result["reset_id"], self.identity.reset_id)
        self.assertEqual(result["status"], "blocked")

    def test_continue_closes_route_owned_opponent_successor_before_overview(self):
        calls = []
        pages = iter(({"page": {"screen_state": "opponent_list"}}, {"page": {"screen_state": "hero_duel_overview"}}))
        def navigation(label, phrase, expected, target):
            calls.append((phrase, target))
            return next(pages)
        self.flow._navigation_tap = navigation
        self.assertEqual(self.flow._continue_to_overview("continue")["page"]["screen_state"], "hero_duel_overview")
        self.assertEqual(calls, [("tap to continue", "hero-duel-loss-continue"), ("close", "hero-duel-opponents-close")])

    def test_reopened_unknown_is_denied_without_a_new_capture_or_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "actions.sqlite3"
            store = SafetyStore(path)
            key = self.flow.action_key(1, "hero_duel_free_entry")
            intent = ActionIntent(
                action_id="replay-entry-1", action_key=key, task_id=route.FLOW_ID,
                semantic_action="hero_duel_free_entry", source_state="hero_duel_attack_formation",
                target_identity="hero-duel-attack-challenge", target_roi=(100, 100, 200, 140),
                source_frame_sha256="a" * 64, source_frame_captured_at=1,
                runtime_profile_id=route.PROFILE_ID, game_day_id=self.identity.reset_id,
                expected_postcondition="hero_duel_battle_loaded", consequence="bounded_hero_duel_participation",
                cost_type="none", cost_amount=0, quantity=1, evidence_refs=("synthetic:replay",),
            )
            policy = PolicyResult(PolicyDecision.AUTHORIZE, "synthetic", "replay only", 1, {})
            store.prepare_action(intent, policy, 1)
            store.mark_unresolved(intent.action_id, 2, "synthetic_missing_successor")
            store.close()
            reopened = SafetyStore(path)
            try:
                self.flow.store = reopened
                self.flow.capture = lambda _label: self.fail("UNKNOWN must deny before any new capture")
                outcome = self.flow._effect(
                    kind="hero_duel_free_entry", ordinal=1, source_state="attack_formation",
                    target_id="hero-duel-attack-challenge", phrase="challenge",
                    consequence="bounded_hero_duel_participation", postcondition="hero_duel_battle_loaded",
                    expected_state="active_battle")
                self.assertEqual(outcome["status"], "blocked")
                self.assertEqual(outcome["transport_calls"], 0)
                self.assertTrue(outcome["effect_reconciliation_required"])
                self.assertTrue(reopened.has_action_block())
            finally:
                reopened.close()

    def test_confirmed_receipts_reopen_without_paid_inventory_but_not_changed_event(self):
        for ordinal in range(1, 4):
            self.entry_record(ordinal, status=route.ActionStatus.CONFIRMED.value)
            facts = route.hero_duel_policy_preconditions(
                "hero_duel_flee", event_identity=self.flow.event_identity,
                ordinal=ordinal, game_day_id=self.identity.reset_id,
                free_allowance_at_flee=3 - ordinal)
            self.records[self.flow.action_key(ordinal, "hero_duel_flee")] = {
                "final_status": route.ActionStatus.CONFIRMED.value,
                "policy_request_json": json.dumps({"semantic_preconditions": facts})}
        self.flow._retain_canonical_cycle_proofs([1, 2, 3])
        self.assertEqual([proof["ordinal"] for proof in self.flow.result["cycle_proofs"]], [1, 2, 3])
        self.flow._retain_canonical_cycle_proofs([1, 2, 3])
        self.assertEqual(len(self.flow.result["cycle_proofs"]), 3)
        self.flow.event_identity = "different-event"
        self.assertFalse(self.flow._canonical_proofs_match([1, 2, 3]))

    def test_actual_native_checked_portraits_and_empty_slot_controls(self):
        root = Path(__file__).resolve().parents[2] / "Puzzle_Survival_Runtime_POC" / ".local-captures" / "development-sessions"
        current = root / "restart-resume-20261108T035832132346Z" / "hero-duel75-native-existing-title-fix" / "native" / "HERO-DUEL-EVIDENCE-GATE-20261108T223548207697Z-10db12ed" / "hero-duel-survival-20261108T223548284999Z" / "frames" / "0028-hero-duel-defense-source.png"
        if not current.is_file():
            self.skipTest("retained native formation required")
        image = cv2.imread(str(current))
        slots, displayed, eligible, selected, cards = self.flow.vision._formation_facts(image, "defense_formation")
        self.assertEqual(slots, ("active",) * 5)
        self.assertEqual(set(selected), set(displayed[:5]))
        self.assertTrue(all(hero in eligible for hero in selected))
        self.assertEqual([card["state"] for card in cards[:5]], ["selected"] * 5)
        self.assertIsNotNone(self.flow.vision.defense_remove_roi(image, 0))
        blank = self.flow.vision._formation_facts(np.zeros_like(image), "defense_formation")
        self.assertIsNone(blank[2])
        self.assertNotEqual(blank[0], ("active",) * 5)

    def test_walkthrough_current_candidates_preserve_four_members_and_verify_saved_five(self):
        root = Path(__file__).resolve().parents[2] / "Puzzle_Survival_Runtime_POC" / ".local-captures" / "manual-walkthrough-2026-11-09T04-42-35-490Z"
        if not root.is_dir():
            self.skipTest("retained walkthrough formation required")
        for filename, expected_count in (
                ("0140-duel75-defense-remove-sixth-candidate.jpg", 4),
                ("0145-duel75-defense-readback.jpg", 5)):
            with self.subTest(source=filename):
                window = cv2.imread(str(root / filename))
                self.assertIsNotNone(window)
                # Retained App Player window: remove its title/sidebar, then
                # restore the actual 800x1280 game viewport for native readers.
                image = cv2.resize(window[32:1212, :738], (800, 1280))
                slots, displayed, eligible, selected, cards = self.flow.vision._formation_facts(
                    image, "defense_formation")
                expected = tuple(hero for hero in displayed if hero in eligible)[:5]
                self.assertEqual(len(expected), 5)
                self.assertEqual(len(selected), expected_count)
                keep = self.flow.vision._defense_keep_slots(image, cards, expected)
                self.assertIsNotNone(keep)
                self.assertEqual(set(keep), set(range(expected_count)))
                self.assertEqual(slots.count("active"), expected_count)
                if expected_count == 5:
                    self.assertEqual(set(selected), set(expected))

    def test_saved_defense_is_reopened_and_read_before_any_continuation(self):
        heroes = tuple(f"portrait:0:{index}" for index in range(5))
        game = route.HeroDuelObservation(screen_state="defense_formation",
            source_frame_sha256="a" * 64, displayed_hero_ids=heroes,
            eligible_hero_ids=heroes, defense_hero_ids=heroes,
            formation_slot_states=("active",) * 5)
        for readback in (game, route.HeroDuelObservation(screen_state="hero_duel_overview",
                source_frame_sha256="b" * 64)):
            with self.subTest(readback=readback.screen_state):
                calls = []
                self.flow.vision.defense_saved = False
                self.flow.capture = lambda _label: self.capture
                self.flow.observe = lambda _captured: {"screen_state": "defense_formation"}
                self.flow._navigation_tap = lambda *_args: (
                    calls.append("reopen") or {"page": {"screen_state": "defense_formation"}})
                self.flow._defense_back = lambda _label: (
                    calls.append("back") or {"page": {"screen_state": "hero_duel_overview"}})
                self.flow._effect = lambda **_kwargs: (
                    calls.append("save") or {"status": "confirmed", "transport_calls": 1,
                        "successor": self.capture})
                with patch.object(self.flow, "_observation", side_effect=(game, readback)):
                    result = self.flow._prepare_defense({"screen_state": "defense_formation"})
                if readback is game:
                    self.assertEqual(calls, ["save", "reopen", "back"])
                    self.assertEqual(result["screen_state"], "hero_duel_overview")
                else:
                    self.assertEqual(calls, ["save", "reopen"])
                    self.assertIsNone(result)
                    self.assertFalse(self.flow.vision.defense_saved)

    def test_walkthrough_exhausted_overview_uses_paid_cost_without_inventory_census(self):
        source = Path(__file__).resolve().parents[2] / "Puzzle_Survival_Runtime_POC" / ".local-captures" / "manual-walkthrough-2026-11-09T04-42-35-490Z" / "0170-duel75-cycle3-overview-count.jpg"
        if not source.is_file() or shutil.which("tesseract") is None:
            self.skipTest("retained walkthrough frame and local OCR required")
        window = cv2.imread(str(source))
        self.assertIsNotNone(window)
        image = cv2.resize(window[32:1212, :738], (800, 1280))
        page = self.flow.vision.recognize(SimpleNamespace(frame=image))
        self.assertEqual(page["screen_state"], "hero_duel_overview")
        self.assertEqual(page["free_entries_remaining"], 0)


    def test_retained_actual_images_use_real_observer_when_evidence_and_ocr_exist(self):
        source = Path(__file__).resolve().parents[2] / "Puzzle_Survival_Runtime_POC" / ".local-captures" / "development-sessions" / "investigation2-cua-owner-20261106T232501213650Z"
        if not source.is_dir() or shutil.which("tesseract") is None:
            self.skipTest("evidence_required: retained source images and local Tesseract required")
        for filename, expected in (
            ("0197-duel-defense-save-form-before.png", "defense_formation"),
            ("0208-duel-first-listed-free-opponent-settled.png", "attack_formation"),
            ("0170-hero-duel-emergency-close-before.png", "emergency_details"),
            ("0217-duel-confirm-flee-settled.png", "loss_result"),
            ("0220-duel-result-tap-continue-settled.png", "opponent_list"),
        ):
            with self.subTest(source=filename):
                image = cv2.imread(str(source / filename))
                self.assertIsNotNone(image)
                page = self.flow.vision.recognize(SimpleNamespace(frame=image))
                self.assertEqual(page["screen_state"], expected)

    def test_retained_exit_arrow_uses_current_image_geometry(self):
        source = Path(__file__).resolve().parents[2] / "Puzzle_Survival_Runtime_POC" / ".local-captures" / "development-sessions" / "investigation2-cua-owner-20261106T232501213650Z" / "0212-duel-loaded-battle-exit-before.png"
        if not source.is_file():
            self.skipTest("evidence_required: retained battle toolbar source required")
        image = cv2.imread(str(source))
        self.assertIsNotNone(image)
        self.assertIsNotNone(route.HeroDuelVision.battle_exit_arrow_roi(image))
        self.assertIsNone(route.HeroDuelVision.battle_exit_arrow_roi(np.zeros_like(image)))

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
