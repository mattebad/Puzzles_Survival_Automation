from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

from tasks.noahs_tavern_recruit import (
    HERO_RECRUIT_RESULT_SCREEN,
    NOAHS_TAVERN_SCREEN,
    NOAHS_TAVERN_FREE_TARGET,
    DailyQuestProgress,
    NoahTavernObservation,
    NoahTierObservation,
    RecruitTier,
    TIER_ATTEMPT_MAXIMUMS,
    TierState,
    noah_recruit_authorizeable,
    noah_recruit_transaction_spec,
    noah_result_postcondition_verified,
    parse_cooldown_seconds,
)
from tasks.noahs_tavern_recruit_runtime import NoahAction, NoahTavernRecruitRuntimeController
from tasks.noahs_tavern_recruit_vision import recognize_noahs_tavern_frame
from scripts.noahs_tavern_recruit_bluestacks import (
    BlueStacksNoahsTavernRecruitAdapter,
    _atlas_canonical_home,
    _write_unified_result,
    recognize_home_zoom_source,
)
from tasks.home_atlas import ZoomIdentity


class NoahFixtures:
    def tier(self, tier, *, remaining=None, cooldown_text="", cooldown=False, enabled=False, **changes):
        if remaining is None:
            remaining = TIER_ATTEMPT_MAXIMUMS[tier]
        base = NoahTierObservation(
            tier=tier,
            daily_attempt_maximum=TIER_ATTEMPT_MAXIMUMS[tier],
            attempts_remaining=remaining,
            cooldown_text=cooldown_text,
            cooldown_duration_seconds=parse_cooldown_seconds(cooldown_text),
            cooldown_active=cooldown,
            next_eligible_timestamp=130.0 if cooldown else None,
            free_control_visible=enabled,
            free_control_enabled=enabled,
            target_roi=(100, 950, 370, 1040),
            panel_roi=(40, 840, 760, 1070),
            target_identity=NOAHS_TAVERN_FREE_TARGET,
            control_class=NOAHS_TAVERN_FREE_TARGET,
            cost_type="none",
            cost_amount=0,
            quantity=1,
            premium_control_visible=True,
            recognized=True,
            **changes,
        )
        return base

    def tavern(self, selected=RecruitTier.BASIC, *, basic_remaining=5, daily=0, digest="a" * 64, **changes):
        tiers = {
            RecruitTier.BASIC: self.tier(RecruitTier.BASIC, remaining=basic_remaining, enabled=selected == RecruitTier.BASIC),
            RecruitTier.INT: self.tier(RecruitTier.INT, remaining=1, enabled=selected == RecruitTier.INT),
            RecruitTier.ADV: self.tier(RecruitTier.ADV, remaining=1, enabled=selected == RecruitTier.ADV),
        }
        if selected is not None:
            tiers[selected] = replace(tiers[selected], free_control_visible=True, free_control_enabled=True)
        return NoahTavernObservation(
            screen_state=NOAHS_TAVERN_SCREEN,
            selected_tier=selected,
            tiers=tuple(tiers.values()),
            frame_sha256=digest,
            captured_monotonic=100.0,
            daily_quest_completed=daily,
            recognized=True,
            **changes,
        )

    def result(self, tier=RecruitTier.BASIC, digest="b" * 64):
        return NoahTavernObservation(
            screen_state=HERO_RECRUIT_RESULT_SCREEN,
            selected_tier=None,
            tiers=tuple(self.tier(item, remaining=None, enabled=False) for item in RecruitTier),
            frame_sha256=digest,
            captured_monotonic=101.0,
            recognized=True,
            result_tier=tier,
            result_identity="hero frag",
            safe_close_visible=True,
            safe_close_roi=(100, 1000, 340, 1070),
            premium_result_control_visible=True,
        )

    def after(self, before, tier=RecruitTier.BASIC, daily=1, digest="c" * 64, cooldown_text="00:09:52"):
        tiers = list(before.tiers)
        index = next(i for i, item in enumerate(tiers) if item.tier == tier)
        tiers[index] = replace(
            tiers[index],
            attempts_remaining=(before.tier(tier).attempts_remaining - 1),
            cooldown_text=f"Free in {cooldown_text}",
            cooldown_duration_seconds=parse_cooldown_seconds(cooldown_text),
            cooldown_active=True,
            next_eligible_timestamp=130.0,
            free_control_enabled=False,
        )
        return NoahTavernObservation(
            screen_state=NOAHS_TAVERN_SCREEN,
            selected_tier=tier,
            tiers=tuple(tiers),
            frame_sha256=digest,
            captured_monotonic=102.0,
            recognized=True,
            daily_quest_completed=daily,
        )


class NoahContractTests(unittest.TestCase):
    def setUp(self):
        self.f = NoahFixtures()

    def test_basic_int_adv_tier_recognition_and_maxima(self):
        obs = self.f.tavern()
        self.assertEqual(tuple(item.tier for item in obs.tiers), tuple(RecruitTier))
        self.assertEqual([item.daily_attempt_maximum for item in obs.tiers], [5, 1, 1])

    def test_enabled_free_authorization_and_transaction_spec(self):
        obs = self.f.tavern(selected=RecruitTier.INT)
        self.assertTrue(noah_recruit_authorizeable(obs, RecruitTier.INT))
        spec = noah_recruit_transaction_spec(obs, RecruitTier.INT)
        self.assertEqual(spec.quantity, 1)
        self.assertEqual(spec.maximum_cost, 0)
        self.assertTrue(spec.free_only)

    def test_exact_one_attempt_decrement_and_result(self):
        before = self.f.tavern(selected=RecruitTier.BASIC, basic_remaining=5)
        after = self.f.after(before, daily=1)
        self.assertEqual(before.tier(RecruitTier.BASIC).attempts_remaining - after.tier(RecruitTier.BASIC).attempts_remaining, 1)
        self.assertTrue(noah_result_postcondition_verified(before, self.f.result(), after, RecruitTier.BASIC))

    def test_independent_cooldown_parsing(self):
        self.assertEqual(parse_cooldown_seconds("Free in 00:09:52"), 592)
        self.assertEqual(parse_cooldown_seconds("Free in 23:59:51"), 86391)
        self.assertEqual(parse_cooldown_seconds("Free in 1d23:59:52"), 172792)

    def test_invalid_decrement_and_ambiguous_postcondition_rejected(self):
        before = self.f.tavern(basic_remaining=5)
        bad = self.f.after(before, daily=1)
        tier = bad.tier(RecruitTier.BASIC)
        bad = replace(bad, tiers=(replace(tier, attempts_remaining=5),) + bad.tiers[1:])
        self.assertFalse(noah_result_postcondition_verified(before, self.f.result(), bad, RecruitTier.BASIC))
        self.assertFalse(noah_result_postcondition_verified(before, None, self.f.after(before), RecruitTier.BASIC))

    def test_disabled_cooldown_unknown_stale_overlay_and_premium_guards(self):
        base = self.f.tavern()
        self.assertFalse(noah_recruit_authorizeable(replace(base, tiers=(replace(base.tier(RecruitTier.BASIC), free_control_enabled=False),) + base.tiers[1:]), RecruitTier.BASIC))
        cooled = self.f.after(base)
        self.assertFalse(noah_recruit_authorizeable(cooled, RecruitTier.BASIC))
        self.assertFalse(noah_recruit_authorizeable(replace(base, recognized=False), RecruitTier.BASIC))
        self.assertFalse(noah_recruit_authorizeable(replace(base, stale=True), RecruitTier.BASIC))
        self.assertFalse(noah_recruit_authorizeable(replace(base, overlay_state="unknown"), RecruitTier.BASIC))
        paid = replace(base.tier(RecruitTier.BASIC), cost_type="currency", cost_amount=1)
        self.assertFalse(noah_recruit_authorizeable(replace(base, tiers=(paid,) + base.tiers[1:]), RecruitTier.BASIC))

    def test_native_shape_guard(self):
        with self.assertRaises(ValueError):
            recognize_noahs_tavern_frame(np.zeros((720, 1280, 3), dtype=np.uint8))

    def test_adv_title_ocr_confusion_is_scoped_to_noah_tavern_header(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        calls = []
        def ocr(_image, psm):
            calls.append(psm)
            if psm == 6 and len(calls) == 1:
                return "Noahs Tavern"
            if psm == 6 and len(calls) == 2:
                return "AQV. RECruit"
            return ""
        observed = recognize_noahs_tavern_frame(frame, ocr=ocr)
        self.assertEqual(observed.screen_state, NOAHS_TAVERN_SCREEN)
        self.assertTrue(observed.recognized)
        self.assertEqual(observed.selected_tier, RecruitTier.ADV)

        def negative_ocr(_image, psm):
            if psm == 6:
                return "Unknown Surface" if not calls else "AQV. RECruit"
            return ""
        self.assertNotEqual(
            recognize_noahs_tavern_frame(frame, ocr=negative_ocr).screen_state,
            NOAHS_TAVERN_SCREEN,
        )

    def test_one_attempt_tier_accepts_free_control_when_counter_one_is_vertical_bar(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        calls = 0

        def ocr(_image, _psm):
            nonlocal calls
            calls += 1
            return {
                1: "Noahs Tavern",
                2: "Adv. Recruit",
                5: "Daily free attempts: |",
                8: "Free Recruit 1x",
            }.get(calls, "")

        advanced = recognize_noahs_tavern_frame(frame, ocr=ocr).tier(RecruitTier.ADV)
        self.assertEqual(advanced.attempts_remaining, 1)
        self.assertTrue(advanced.recognized)

    def test_bluestacks_adapter_is_dry_run_by_default(self):
        adapter = BlueStacksNoahsTavernRecruitAdapter()
        self.assertTrue(adapter.config.dry_run)
        self.assertEqual(adapter.command(SimpleNamespace(observation=self.f.tavern(), frame_sha256="a" * 64)).action.value, "RECRUIT_FREE")


class NoahRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.f = NoahFixtures()

    def rec(self, obs):
        return SimpleNamespace(observation=obs, frame_sha256=obs.frame_sha256)

    def test_next_eligible_scheduling(self):
        controller = NoahTavernRecruitRuntimeController(now=100.0)
        before = self.f.tavern(basic_remaining=5)
        self.assertEqual(controller.next_command(self.rec(before)).action, NoahAction.RECRUIT_FREE)
        self.assertFalse(controller.next_command(self.rec(before)).scheduler_ready)
        self.assertEqual(controller.next_command(self.rec(before)).action, NoahAction.STOP)

    def test_result_screen_and_safe_close_then_mixed_tier_repeat(self):
        controller = NoahTavernRecruitRuntimeController(now=100.0)
        before = self.f.tavern(basic_remaining=5)
        self.assertEqual(controller.next_command(self.rec(before)).action, NoahAction.RECRUIT_FREE)
        result = self.f.result()
        self.assertEqual(controller.next_command(self.rec(result)).action, NoahAction.CLOSE_RESULT)
        after = self.f.after(before)
        self.assertTrue(controller.accept_postcondition(self.rec(result), after))
        int_obs = self.f.after(before, daily=1, digest="d" * 64)
        controller.progress.tiers[RecruitTier.INT] = TierState(RecruitTier.INT, 1, 1)
        controller.progress.inspected_tiers.add(RecruitTier.INT)
        controller.progress.tiers[RecruitTier.ADV] = TierState(RecruitTier.ADV, 1, 0, 100, True, 200.0)
        controller.progress.inspected_tiers.add(RecruitTier.ADV)
        self.assertEqual(controller.next_command(self.rec(int_obs)).action, NoahAction.SELECT_TIER)

    def test_basic_cooldown_still_selects_independently_eligible_int(self):
        controller = NoahTavernRecruitRuntimeController(now=100.0)
        basic = self.f.tavern(selected=RecruitTier.BASIC)
        basic_tiers = tuple(
            replace(item, cooldown_active=True, next_eligible_timestamp=130.0, free_control_enabled=False)
            if item.tier is RecruitTier.BASIC else item
            for item in basic.tiers
        )
        basic = replace(basic, tiers=basic_tiers)
        self.assertEqual(controller.next_command(self.rec(basic)).action, NoahAction.SELECT_TIER)
        self.assertEqual(controller.next_command(self.rec(self.f.tavern(selected=RecruitTier.INT, digest="d" * 64))).action, NoahAction.RECRUIT_FREE)

    def test_basic_daily_cap_still_selects_independently_eligible_int(self):
        controller = NoahTavernRecruitRuntimeController(now=100.0)
        controller.maintenance_controller.state.basic_daily_count = 5
        basic = self.f.tavern(selected=RecruitTier.BASIC)
        self.assertEqual(controller.next_command(self.rec(basic)).action, NoahAction.SELECT_TIER)
        self.assertEqual(controller.next_command(self.rec(self.f.tavern(selected=RecruitTier.INT, digest="e" * 64))).action, NoahAction.RECRUIT_FREE)

    def test_daily_claim_readiness_does_not_suppress_independent_advanced_free(self):
        controller = NoahTavernRecruitRuntimeController()
        controller.progress.daily_quest.recruits_completed = 5
        done = self.f.tavern(selected=RecruitTier.ADV, daily=5)
        self.assertEqual(controller.next_command(self.rec(done)).action, NoahAction.RECRUIT_FREE)
        self.assertTrue(controller.progress.daily_quest.ready_to_claim)
        self.assertTrue(controller.progress.daily_quest.claim_dormant)
        self.assertNotIn("CLAIM", [action.value for action in NoahAction])

    def test_wait_when_all_tiers_cooldown(self):
        controller = NoahTavernRecruitRuntimeController(now=100.0)
        for tier, next_at in ((RecruitTier.BASIC, 700.0), (RecruitTier.INT, 200.0), (RecruitTier.ADV, 900.0)):
            controller.progress.tiers[tier] = TierState(tier, {RecruitTier.BASIC: 5, RecruitTier.INT: 1, RecruitTier.ADV: 1}[tier], 0, 600, True, next_at)
            controller.progress.inspected_tiers.add(tier)
        obs = self.f.tavern(basic_remaining=0, daily=3)
        command = controller.next_command(self.rec(obs))
        self.assertEqual(command.action, NoahAction.WAIT_COOLDOWN)
        self.assertTrue(command.scheduler_ready)
        self.assertEqual(command.next_eligible_timestamp, 200.0)

    def test_bad_result_close_is_fail_closed(self):
        controller = NoahTavernRecruitRuntimeController()
        before = self.f.tavern()
        self.assertEqual(controller.next_command(self.rec(before)).action, NoahAction.RECRUIT_FREE)
        bad = replace(self.f.result(), safe_close_visible=False)
        self.assertEqual(controller.next_command(self.rec(bad)).action, NoahAction.STOP)

    def test_unexpected_result_without_dispatch_is_rejected(self):
        controller = NoahTavernRecruitRuntimeController()
        self.assertEqual(controller.next_command(self.rec(self.f.result())).action, NoahAction.STOP)

    def test_unified_zoom_transport_failure_flushes_terminal_result(self):
        """A native zoom exception must retain a blocked result before session unwind."""
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            runtime = SimpleNamespace(session=session, events=session / "events.jsonl", input_count=1)
            payload = {
                "status": "blocked",
                "reason": "home_zoom_normalization_exception",
                "failure_stage": "home_zoom_normalization",
                "error": "ADBError: Android multi-touch device was not found",
                "actions_completed": 0,
                "session_directory": str(session),
                "input_count": 1,
                "terminal_home_verified": False,
                "recruitment_dispatch_count": 0,
                "claim_dispatched": False,
                "zoom_normalization": [{
                    "ordinal": 1,
                    "exception": "ADBError: Android multi-touch device was not found",
                    "immediate_post_error": "capture unavailable",
                }],
            }
            encoded = _write_unified_result(runtime, payload)
            persisted = json.loads((session / "unified-recruitment-result.json").read_text(encoding="utf-8"))
            self.assertEqual(json.loads(encoded), persisted)
            self.assertEqual(persisted["status"], "blocked")
            self.assertEqual(persisted["input_count"], 1)
            self.assertFalse(persisted["terminal_home_verified"])
            self.assertEqual(persisted["recruitment_dispatch_count"], 0)

    def test_home_zoom_source_uses_independent_home_ready_semantics(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        facts = {"state": "HOME_BASE", "recognized": True, "hq_anchor": True, "hud_anchor": True}
        recognized, details = recognize_home_zoom_source(frame, home_classifier=lambda _frame: facts)
        self.assertTrue(recognized)
        self.assertFalse(details["overlay_rejected"])

    def test_home_zoom_source_rejects_wrong_screen_and_overlay(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        for facts in (
            {"state": "NOAHS_TAVERN", "recognized": True},
            {"state": "HOME_BASE", "recognized": True, "overlay": True},
            {"state": "HOME_BASE", "recognized": False},
        ):
            with self.subTest(facts=facts):
                recognized, _ = recognize_home_zoom_source(frame, home_classifier=lambda _frame, f=facts: f)
                self.assertFalse(recognized)

    def test_canonical_atlas_home_accepts_unknown_tavern_ocr_but_rejects_conflict(self):
        localization = SimpleNamespace(
            recognized=True,
            zoom_identity=ZoomIdentity.FULLY_ZOOMED_OUT,
            overlay=False,
        )
        unknown = SimpleNamespace(recognized=False, screen_state="UNKNOWN")
        tavern = SimpleNamespace(recognized=True, screen_state=NOAHS_TAVERN_SCREEN)
        self.assertTrue(_atlas_canonical_home(localization, unknown))
        self.assertFalse(_atlas_canonical_home(localization, tavern))


if __name__ == "__main__":
    unittest.main()
