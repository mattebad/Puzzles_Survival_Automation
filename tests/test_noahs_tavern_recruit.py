from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np
import pytesseract

from tasks.noahs_tavern_recruit import (
    HERO_RECRUIT_RESULT_SCREEN,
    HOME_BASE_SCREEN,
    NOAHS_TAVERN_SCREEN,
    NOAHS_TAVERN_FREE_TARGET,
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
from tasks.noahs_tavern_recruit_vision import (
    TAVERN_ATTEMPTS_ROI,
    TAVERN_FREE_ROI,
    TAVERN_HEADER_ROI,
    TAVERN_TITLE_ROI,
    recognize_noahs_tavern_frame,
)
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.noahs_tavern_recruit_bluestacks import (
    BlueStacksNoahsTavernRecruitAdapter,
    NoahTavernIntegratedRoute,
    _ContextualPopupSession,
    _apply_startup_recovery_input_reserve,
    _atlas_canonical_home,
    _contextual_recovery,
    _write_unified_result,
    recognize_home_zoom_source,
)
from scripts.startup_recovery import ContextualPopupRecoveryResult
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

    def tavern(self, selected=RecruitTier.BASIC, *, basic_remaining=5, digest="a" * 64, **changes):
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
            safe_close_visible=True,
            safe_close_roi=(100, 1000, 340, 1070),
            premium_result_control_visible=True,
        )

    def after(self, before, tier=RecruitTier.BASIC, digest="c" * 64, cooldown_text="00:09:52"):
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
        )


class NoahContractTests(unittest.TestCase):
    def test_popup_absent_preserves_twelve_input_route_cap(self):
        runtime = SimpleNamespace(max_inputs=12)

        allowance = _apply_startup_recovery_input_reserve(
            runtime,
            route_input_cap=12,
            configured_input_cap=40,
            recovery_status="not_present",
            recovery_input_count=0,
        )

        self.assertEqual(allowance, 0)
        self.assertEqual(runtime.max_inputs, 12)


    def test_shared_preflow_fallback_honors_outer_route_reserve(self):
        runtime = SimpleNamespace(max_inputs=11)

        allowance = _apply_startup_recovery_input_reserve(
            runtime,
            route_input_cap=12,
            configured_input_cap=11,
            recovery_status="shared_pre_flow_startup_recovery",
            recovery_input_count=0,
        )

        self.assertEqual(allowance, 0)
        self.assertEqual(runtime.max_inputs, 11)


    def test_pnsctl_recovery_does_not_readd_route_input_allowance(self):
        runtime = SimpleNamespace(max_inputs=11)

        allowance = _apply_startup_recovery_input_reserve(
            runtime,
            route_input_cap=11,
            configured_input_cap=11,
            recovery_status="surface_dismissed_successor_captured",
            recovery_input_count=1,
            recovery_consumed_externally=True,
        )

        self.assertEqual(allowance, 0)
        self.assertEqual(runtime.max_inputs, 11)

    def test_recovery_reserve_respects_configured_ceiling(self):
        runtime = SimpleNamespace(max_inputs=12)

        with self.assertRaisesRegex(
            RuntimeError,
            "cannot accommodate startup recovery",
        ):
            _apply_startup_recovery_input_reserve(
                runtime,
                route_input_cap=12,
                configured_input_cap=12,
                recovery_status="recovered",
                recovery_input_count=1,
            )

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

    def test_independent_cooldown_parsing(self):
        self.assertEqual(parse_cooldown_seconds("Free in 00:09:52"), 592)
        self.assertEqual(parse_cooldown_seconds("Free in 23:59:51"), 86391)
        self.assertEqual(parse_cooldown_seconds("Free in 1d23:59:52"), 172792)

    def test_postcondition_uses_source_count_and_rejects_missing_timer(self):
        before = self.f.tavern(basic_remaining=5)
        conflicting = self.f.after(before)
        tier = conflicting.tier(RecruitTier.BASIC)
        conflicting = replace(conflicting, tiers=(replace(tier, attempts_remaining=5),) + conflicting.tiers[1:])
        self.assertTrue(noah_result_postcondition_verified(before, self.f.result(), conflicting, RecruitTier.BASIC))
        missing_timer = replace(
            self.f.after(before),
            tiers=(replace(self.f.after(before).tier(RecruitTier.BASIC), cooldown_text="", cooldown_duration_seconds=None),)
            + self.f.after(before).tiers[1:],
        )
        self.assertFalse(noah_result_postcondition_verified(before, self.f.result(), missing_timer, RecruitTier.BASIC))
        self.assertFalse(noah_result_postcondition_verified(before, None, self.f.after(before), RecruitTier.BASIC))

    def test_postcondition_rejects_preexisting_cooldown_wrong_tier_stale_and_overlay(self):
        before = self.f.tavern(basic_remaining=5)
        result = self.f.result()
        after = self.f.after(before)
        cooled_before = self.f.after(before)
        self.assertFalse(noah_result_postcondition_verified(cooled_before, result, after, RecruitTier.BASIC))
        self.assertFalse(noah_result_postcondition_verified(before, self.f.result(RecruitTier.INT), after, RecruitTier.BASIC))
        self.assertFalse(noah_result_postcondition_verified(before, result, replace(after, selected_tier=RecruitTier.INT), RecruitTier.BASIC))
        self.assertFalse(noah_result_postcondition_verified(before, result, replace(after, stale=True), RecruitTier.BASIC))
        enabled_after = replace(
            after,
            tiers=(replace(after.tier(RecruitTier.BASIC), free_control_enabled=True),) + after.tiers[1:],
        )
        self.assertFalse(noah_result_postcondition_verified(before, result, enabled_after, RecruitTier.BASIC))
        self.assertFalse(noah_result_postcondition_verified(before, result, replace(after, overlay_state="modal"), RecruitTier.BASIC))

    def test_distinct_frames_allow_clock_tick_ties_but_not_time_reversal(self):
        before = self.f.tavern()
        result = replace(self.f.result(), captured_monotonic=100.0)
        after = replace(self.f.after(before), captured_monotonic=100.0)
        self.assertTrue(noah_result_postcondition_verified(before, result, after, RecruitTier.BASIC))
        self.assertFalse(noah_result_postcondition_verified(
            before, replace(result, captured_monotonic=99.0), after, RecruitTier.BASIC,
        ))
        self.assertFalse(noah_result_postcondition_verified(
            before, result, replace(after, captured_monotonic=99.0), RecruitTier.BASIC,
        ))

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


    def test_result_close_does_not_depend_on_reward_ocr(self):
        try:
            pytesseract.get_tesseract_version()
        except (FileNotFoundError, OSError, RuntimeError, pytesseract.TesseractNotFoundError):
            self.skipTest("Tesseract is unavailable for native OCR fixture")
        frame = cv2.imread(str(Path(__file__).with_name("fixtures") / "noahs_tavern_nova_result.png"))
        self.assertIsNotNone(frame)
        blank_reward = frame.copy()
        blank_reward[450:790, 250:560] = 0
        for label, candidate in (("native", frame), ("reward_removed", blank_reward)):
            with self.subTest(label=label):
                observed = recognize_noahs_tavern_frame(candidate, captured_monotonic=101.0)
                self.assertEqual(observed.screen_state, HERO_RECRUIT_RESULT_SCREEN)
                self.assertTrue(observed.safe_close_visible)
                controller = NoahTavernRecruitRuntimeController(now=100.0)
                before = self.f.tavern(selected=RecruitTier.INT)
                wrap = lambda obs: SimpleNamespace(observation=obs, frame_sha256=obs.frame_sha256)
                self.assertEqual(controller.next_command(wrap(before)).action, NoahAction.RECRUIT_FREE)
                self.assertEqual(controller.next_command(wrap(observed)).action, NoahAction.CLOSE_RESULT)

    def test_result_close_requires_bounded_label_and_color(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        x0, y0, x1, y1 = (90, 975, 350, 1100)
        frame[y0:y1, x0:x1] = (0, 0, 255)

        def close_only_ocr(image, _psm):
            return "Close"

        no_color = frame.copy()
        no_color[y0:y1, x0:x1] = (80, 80, 80)
        self.assertNotEqual(
            recognize_noahs_tavern_frame(no_color, ocr=close_only_ocr).screen_state,
            HERO_RECRUIT_RESULT_SCREEN,
        )

        def no_close_ocr(image, _psm):
            center = image[image.shape[0] // 2, image.shape[1] // 2]
            return "Recruit 1x" if center[2] > 200 else "Close"

        self.assertNotEqual(
            recognize_noahs_tavern_frame(frame, ocr=no_close_ocr).screen_state,
            HERO_RECRUIT_RESULT_SCREEN,
        )

    def test_native_advanced_fixture_preserves_complete_header_and_title_glyphs(self):
        try:
            pytesseract.get_tesseract_version()
        except (FileNotFoundError, OSError, RuntimeError, pytesseract.TesseractNotFoundError):
            self.skipTest("Tesseract is unavailable for native OCR fixture")
        fixture_path = Path(__file__).with_name("fixtures") / "noahs_tavern_advanced_roi.png"
        frame = cv2.imread(str(fixture_path), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame)
        observed = recognize_noahs_tavern_frame(frame)
        self.assertEqual(observed.screen_state, NOAHS_TAVERN_SCREEN)
        self.assertTrue(observed.recognized)
        self.assertEqual(observed.selected_tier, RecruitTier.ADV)
        advanced = observed.tier(RecruitTier.ADV)
        self.assertEqual(advanced.attempts_remaining, 1)
        self.assertTrue(advanced.free_control_enabled)
        self.assertEqual(advanced.cost_amount, 0)
        self.assertEqual(advanced.quantity, 1)

    def test_native_after_close_fixture_keeps_cooldown_and_blocks_duplicate_free(self):
        try:
            pytesseract.get_tesseract_version()
        except (FileNotFoundError, OSError, RuntimeError, pytesseract.TesseractNotFoundError):
            self.skipTest("Tesseract is unavailable for native OCR fixture")
        fixture_path = Path(__file__).with_name("fixtures") / "noahs_tavern_recruit_after_close.png"
        frame = cv2.imread(str(fixture_path), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame)
        observed = recognize_noahs_tavern_frame(frame, captured_monotonic=1000.0)
        self.assertEqual(observed.screen_state, NOAHS_TAVERN_SCREEN)
        self.assertEqual(observed.selected_tier, RecruitTier.ADV)
        advanced = observed.tier(RecruitTier.ADV)
        self.assertIsNone(advanced.attempts_remaining)
        self.assertTrue(advanced.cooldown_active)
        self.assertEqual(advanced.cooldown_duration_seconds, 172794)
        self.assertEqual(advanced.next_eligible_timestamp, 173794.0)
        self.assertFalse(advanced.free_control_enabled)
        self.assertFalse(noah_recruit_authorizeable(observed, RecruitTier.ADV))
        before_frame = cv2.imread(
            str(Path(__file__).with_name("fixtures") / "noahs_tavern_advanced_roi.png"),
            cv2.IMREAD_COLOR,
        )
        self.assertIsNotNone(before_frame)
        before = recognize_noahs_tavern_frame(before_frame)
        self.assertTrue(
            noah_result_postcondition_verified(
                before,
                self.f.result(tier=RecruitTier.ADV),
                observed,
                RecruitTier.ADV,
            )
        )

    def test_free_control_evidence_and_cooldown_precedence(self):
        cases = (
            ("enabled_single", "Adv. Recruit", "Daily free attempts: |",
             "Free Recruit 1x", (180, 0, 180), 1, False, True),
            ("disabled_single", "Adv. Recruit", "Daily free attempts: |",
             "Free Recruit 1x", (80, 80, 80), None, False, False),
            ("timer_words_are_not_a_button", "Adv. Recruit", "Free in ???",
             "Free in ??? Recruit 1x", (180, 0, 180), None, False, False),
            ("basic_cooldown_overrides_free_label", "Basic Recruit",
             "Daily free attempts: 4 Free in 00:09:52",
             "Free Recruit 1x", (180, 0, 180), 4, True, False),
        )
        for name, title, attempts, control, color, remaining, cooldown, enabled in cases:
            with self.subTest(name=name):
                frame = np.zeros((1280, 800, 3), dtype=np.uint8)
                for box, marker in (
                    (TAVERN_HEADER_ROI, 11),
                    (TAVERN_TITLE_ROI, 29),
                    (TAVERN_ATTEMPTS_ROI, 47),
                ):
                    x0, y0, _, _ = box
                    frame[y0 : y0 + 8, x0 : x0 + 8] = marker
                x0, y0, x1, y1 = TAVERN_FREE_ROI
                frame[y0:y1, x0:x1] = color

                def ocr(image, _psm):
                    marker = int(image[5, 5, 0])
                    return {
                        11: "Noahs Tavern",
                        29: title,
                        47: attempts,
                        color[0]: control,
                    }.get(marker, "")

                observed = recognize_noahs_tavern_frame(
                    frame, captured_monotonic=1000.0, ocr=ocr,
                )
                selected = observed.tier(observed.selected_tier)
                self.assertEqual(selected.attempts_remaining, remaining)
                self.assertEqual(selected.cooldown_active, cooldown)
                self.assertEqual(selected.free_control_enabled, enabled)
                self.assertEqual(
                    noah_recruit_authorizeable(observed, observed.selected_tier),
                    enabled,
                )

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
        self.assertEqual(controller.next_command(self.rec(result)).action, NoahAction.STOP)
        after = self.f.after(before)
        self.assertTrue(controller.accept_postcondition(self.rec(result), after))
        int_obs = self.f.after(before, digest="d" * 64)
        controller.progress.tiers[RecruitTier.INT] = TierState(RecruitTier.INT, 1, 1)
        controller.progress.inspected_tiers.add(RecruitTier.INT)
        controller.progress.tiers[RecruitTier.ADV] = TierState(RecruitTier.ADV, 1, 0, 100, True, 200.0)
        controller.progress.inspected_tiers.add(RecruitTier.ADV)
        self.assertEqual(controller.next_command(self.rec(int_obs)).action, NoahAction.SELECT_TIER)

    def test_runtime_derives_consumed_count_from_before(self):
        for post_count in (None, 5):
            with self.subTest(post_count=post_count):
                controller = NoahTavernRecruitRuntimeController(now=100.0)
                before = self.f.tavern(basic_remaining=5)
                self.assertEqual(controller.next_command(self.rec(before)).action, NoahAction.RECRUIT_FREE)
                result = self.f.result()
                self.assertEqual(controller.next_command(self.rec(result)).action, NoahAction.CLOSE_RESULT)
                after = self.f.after(before)
                selected = after.tier(RecruitTier.BASIC)
                altered = replace(selected, attempts_remaining=post_count)
                after = replace(
                    after,
                    tiers=tuple(altered if item.tier is RecruitTier.BASIC else item for item in after.tiers),
                )
                self.assertTrue(controller.accept_postcondition(self.rec(result), after))
                self.assertEqual(
                    controller.maintenance_controller.state.tiers[RecruitTier.BASIC].attempts_remaining,
                    4,
                )

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
        done = self.f.tavern(selected=RecruitTier.ADV)
        self.assertEqual(controller.next_command(self.rec(done)).action, NoahAction.RECRUIT_FREE)
        self.assertTrue(controller.progress.daily_quest.ready_to_claim)
        self.assertTrue(controller.progress.daily_quest.claim_dormant)
        self.assertNotIn("CLAIM", [action.value for action in NoahAction])

    def test_wait_when_all_tiers_cooldown(self):
        controller = NoahTavernRecruitRuntimeController(now=100.0)
        for tier, next_at in ((RecruitTier.BASIC, 700.0), (RecruitTier.INT, 200.0), (RecruitTier.ADV, 900.0)):
            controller.progress.tiers[tier] = TierState(tier, {RecruitTier.BASIC: 5, RecruitTier.INT: 1, RecruitTier.ADV: 1}[tier], 0, 600, True, next_at)
            controller.progress.inspected_tiers.add(tier)
        obs = self.f.tavern(basic_remaining=0)
        command = controller.next_command(self.rec(obs))
        self.assertEqual(command.action, NoahAction.WAIT_COOLDOWN)
        self.assertTrue(command.scheduler_ready)
        self.assertEqual(command.next_eligible_timestamp, 200.0)

    def test_matured_persisted_tier_reopens_before_free_revalidation(self):
        from tasks.noahs_tavern_recruit_maintenance import PersistedTierState

        controller = NoahTavernRecruitRuntimeController(now=100.0)
        state = controller.maintenance_controller.state
        state.tiers[RecruitTier.INT] = PersistedTierState(0, 90.0, 86400, "action_performed")
        state.tiers[RecruitTier.ADV] = PersistedTierState(0, 900.0, 172800, "action_performed")
        basic = self.f.after(self.f.tavern())
        # Actual recognition cannot know the free count behind an unopened tab.
        basic = replace(basic, tiers=tuple(
            replace(item, attempts_remaining=None, free_control_visible=False, free_control_enabled=False)
            if item.tier is RecruitTier.INT else item for item in basic.tiers
        ))
        command = controller.next_command(self.rec(basic))
        self.assertEqual(command.action, NoahAction.SELECT_TIER)
        self.assertEqual(command.tier, RecruitTier.INT)
        fresh_int = self.f.tavern(selected=RecruitTier.INT, digest="e" * 64)
        self.assertEqual(controller.next_command(self.rec(fresh_int)).action, NoahAction.RECRUIT_FREE)

    def test_pending_result_close_rejects_wrong_tier_stale_and_overlay(self):
        for mutation in (
            lambda result: replace(result, result_tier=RecruitTier.INT),
            lambda result: replace(result, stale=True),
            lambda result: replace(result, overlay_state="modal"),
        ):
            with self.subTest(mutation=mutation):
                controller = NoahTavernRecruitRuntimeController()
                before = self.f.tavern()
                self.assertEqual(controller.next_command(self.rec(before)).action, NoahAction.RECRUIT_FREE)
                self.assertEqual(controller.next_command(self.rec(mutation(self.f.result()))).action, NoahAction.STOP)

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


class ContextualPopupRouteTests(unittest.TestCase):
    def setUp(self):
        self.f = NoahFixtures()

    @staticmethod
    def frame(digest: str, marker: int) -> CapturedNativeFrame:
        image = np.full((1280, 800, 3), marker, dtype=np.uint8)
        return CapturedNativeFrame(
            image,
            b"",
            digest,
            time.monotonic(),
            Path(f"{digest[:4]}.png"),
        )

    class Runtime:
        execute = True
        session = "contextual-route"
        max_inputs = 20

        def __init__(self, frames):
            self.frames = list(frames)
            self.taps = []
            self.backs = []
            self.input_count = 0
            self.in_flight_action = None

        def capture(self, _label):
            return self.frames.pop(0)

        def tap(self, captured, **kwargs):
            self.input_count += 1
            self.taps.append((captured, kwargs))

        def back(self, captured, **kwargs):
            self.input_count += 1
            self.backs.append((captured, kwargs))

        def reconcile(self, *_args):
            return None

    def test_home_popup_returns_settled_frame_and_invalidates_old_target(self):
        home = replace(
            self.f.tavern(),
            screen_state=HOME_BASE_SCREEN,
            selected_tier=None,
            home_tavern_target_roi=(10, 20, 30, 40),
            frame_sha256="a" * 64,
        )
        settled_home = replace(home, frame_sha256="b" * 64)
        source = self.frame("a" * 64, 1)
        settled = self.frame("b" * 64, 2)
        runtime = self.Runtime([source])
        route = NoahTavernIntegratedRoute(
            runtime,
            recognizer=lambda frame, **_kwargs: home if int(frame[0, 0, 0]) == 1 else settled_home,
            atlas_binding=lambda captured: (
                (11, 21, 31, 41) if captured is settled else (_ for _ in ()).throw(AssertionError("stale target used"))
            ),
            post_input_delay=0.0,
        )
        recovered = ContextualPopupRecoveryResult(
            settled, True, True, True, 1, "popup_dismissed_resume_ready"
        )
        absent = ContextualPopupRecoveryResult(
            settled, False, True, True, 0, "exact_vip_popup_absent"
        )
        with patch(
            "scripts.noahs_tavern_recruit_bluestacks.recover_contextual_vip_popup",
            side_effect=(recovered, absent),
        ), patch(
            "scripts.noahs_tavern_recruit_bluestacks.recognize_reset_popup",
            return_value={"recognized": False},
        ):
            captured, recognition = route._observe("home-source")
            self.assertIs(captured, settled)
            self.assertEqual(recognition.observation.screen_state, HOME_BASE_SCREEN)
            guarded = route._pre_dispatch(
                captured, recognition, "home-atlas-entry"
            )
        self.assertIsNotNone(guarded)
        self.assertEqual(guarded[0], settled)
        self.assertEqual(runtime.taps, [])
        self.assertEqual(route.contextual_session.records[0]["source_sha256"], "a" * 64)
        self.assertEqual(route.contextual_session.records[0]["settled_sha256"], "b" * 64)

    def test_second_exact_popup_hits_one_dismissal_bound_without_helper_or_input(self):
        source = self.frame("c" * 64, 3)
        runtime = self.Runtime([source])
        session = _ContextualPopupSession(dismissal_used=True)
        with patch(
            "scripts.noahs_tavern_recruit_bluestacks.recognize_reset_popup",
            return_value={"recognized": True, "popup_identity": "VIP_POINTS_GET_PTS"},
        ), patch(
            "scripts.noahs_tavern_recruit_bluestacks.recover_contextual_vip_popup",
            side_effect=AssertionError("second contextual close dispatched"),
        ):
            result = _contextual_recovery(
                runtime,
                source,
                source_context="home-or-tavern",
                recognize_successor=lambda _frame: True,
                session=session,
            )
        self.assertEqual(result.reason, "contextual_popup_dismissal_already_used")
        self.assertEqual(result.input_count, 0)
        self.assertEqual(runtime.input_count, 0)

    def test_popup_after_free_transport_keeps_pending_action_and_never_recruits_again(self):
        result_observation = self.f.result(RecruitTier.ADV)
        source = self.frame("d" * 64, 4)
        runtime = self.Runtime([source])
        controller = NoahTavernRecruitRuntimeController(now=100.0)
        before = self.f.tavern(selected=RecruitTier.ADV)
        controller.progress.awaiting_postcondition = True
        controller.progress.awaiting_tier = RecruitTier.ADV
        controller.progress.awaiting_before = before
        route = NoahTavernIntegratedRoute(
            runtime,
            controller=controller,
            recognizer=lambda _frame, **_kwargs: result_observation,
            post_input_delay=0.0,
        )
        route.pending_action_key = "ADV:free:transported"
        controller.progress.dispatched_action_keys.add(route.pending_action_key)
        absent = ContextualPopupRecoveryResult(
            source, False, True, True, 0, "exact_vip_popup_absent"
        )
        with patch(
            "scripts.noahs_tavern_recruit_bluestacks.recover_contextual_vip_popup",
            return_value=absent,
        ):
            _captured, recognition = route._observe("result-after-free")
        self.assertEqual(route.pending_action_key, "ADV:free:transported")
        self.assertTrue(controller.progress.awaiting_postcondition)
        command = controller.next_command(recognition)
        self.assertEqual(command.action, NoahAction.CLOSE_RESULT)
        self.assertNotEqual(command.action, NoahAction.RECRUIT_FREE)
    def test_resume_unresolved_result_preserves_phase_context_without_duplicate_recruit(self):
        before = self.f.tavern(selected=RecruitTier.ADV, digest="a" * 64)
        result = self.f.result(RecruitTier.ADV, digest="b" * 64)
        after = self.f.after(before, tier=RecruitTier.ADV, digest="c" * 64)
        source = self.frame("b" * 64, 2)
        settled_after = self.frame("c" * 64, 3)
        runtime = self.Runtime([source, settled_after])

        def recognize(frame, **_kwargs):
            return {1: before, 2: result, 3: after}[int(frame[0, 0, 0])]

        route = NoahTavernIntegratedRoute(
            runtime,
            recognizer=recognize,
            post_input_delay=0.0,
        )
        action_key = "ADV:retained-result:transported"
        contexts = []

        def contextual_recovery(
            _runtime,
            captured,
            *,
            source_context,
            recognize_successor,
            action_key,
            settle_seconds,
            sleep,
        ):
            contexts.append((source_context, action_key))
            if len(contexts) == 1:
                return ContextualPopupRecoveryResult(
                    captured, True, True, True, 1, "popup_dismissed_resume_ready"
                )
            if len(contexts) == 2:
                return ContextualPopupRecoveryResult(
                    captured, False, True, True, 0, "exact_vip_popup_absent"
                )
            return ContextualPopupRecoveryResult(
                settled_after, False, True, True, 0, "exact_vip_popup_absent"
            )

        terminal = route._result("completed", "resume_test_terminal", 1)
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            before_path = directory / "before.png"
            result_path = directory / "result.png"
            self.assertTrue(cv2.imwrite(str(before_path), np.full((1280, 800, 3), 1, dtype=np.uint8)))
            self.assertTrue(cv2.imwrite(str(result_path), np.full((1280, 800, 3), 2, dtype=np.uint8)))
            with patch(
                "scripts.noahs_tavern_recruit_bluestacks.recover_contextual_vip_popup",
                side_effect=contextual_recovery,
            ), patch(
                "scripts.noahs_tavern_recruit_bluestacks.recognize_reset_popup",
                return_value={"recognized": False},
            ), patch.object(route, "_return_home", return_value=terminal):
                returned = route.resume_unresolved_result(
                    before_frame=before_path,
                    result_frame=result_path,
                    action_key=action_key,
                    tier=RecruitTier.ADV,
                )

        self.assertEqual(returned.reason, "resume_test_terminal")
        self.assertEqual([context for context, _ in contexts], [
            "recruit-result-adv",
            "recruit-result-close-adv",
            "recruit-postcondition-adv",
        ])
        self.assertEqual(contexts[0][1], "noah:popup-close:recruit-result-adv:" + "b" * 64)
        self.assertEqual(len(runtime.taps), 1)
        self.assertEqual(runtime.taps[0][1]["action_key"], action_key + ":recovery-close")
        self.assertNotEqual(runtime.taps[0][1]["target_identity"], NOAHS_TAVERN_FREE_TARGET)
        self.assertEqual(runtime.input_count, 1)
        self.assertIsNone(route.pending_action_key)
        self.assertIsNone(route.pending_result)
        self.assertFalse(route.controller.progress.awaiting_postcondition)


    def test_result_close_phase_context_changes_only_after_transport(self):
        route = NoahTavernIntegratedRoute(self.Runtime([]), post_input_delay=0.0)
        route.pending_action_key = "ADV:free:transported"
        route.pending_result = route._wrap(self.f.result(RecruitTier.ADV))
        route.controller.progress.awaiting_tier = RecruitTier.ADV
        self.assertEqual(route._contextual_source_context(), "recruit-result-close-adv")
        route.result_close_dispatched = True
        self.assertEqual(route._contextual_source_context(), "recruit-postcondition-adv")

    def test_safe_return_contextual_check_accepts_tavern_without_forcing_home(self):
        tavern = self.f.tavern(selected=RecruitTier.ADV, digest="e" * 64)
        source = self.frame("e" * 64, 5)
        runtime = self.Runtime([source])
        route = NoahTavernIntegratedRoute(
            runtime,
            recognizer=lambda _frame, **_kwargs: tavern,
            post_input_delay=0.0,
        )
        absent = ContextualPopupRecoveryResult(
            source, False, True, True, 0, "exact_vip_popup_absent"
        )
        with patch(
            "scripts.noahs_tavern_recruit_bluestacks.recover_contextual_vip_popup",
            return_value=absent,
        ):
            guarded = route._pre_dispatch(
                source, route._wrap(tavern), "tavern-safe-return"
            )
        self.assertIsNotNone(guarded)
        self.assertEqual(guarded[0], source)
        self.assertEqual(runtime.backs, [])



if __name__ == "__main__":
    unittest.main()
