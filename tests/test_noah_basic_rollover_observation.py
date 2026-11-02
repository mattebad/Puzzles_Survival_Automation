from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import pytesseract

from safe_action_core import SafetyStore, SQLiteSchedulerInvocationRepository
from tasks.noahs_tavern_recruit import (
    HERO_RECRUIT_RESULT_SCREEN, NOAHS_TAVERN_FREE_TARGET, NOAHS_TAVERN_SCREEN,
    NoahTavernObservation, NoahTierObservation, RecruitTier, TIER_ATTEMPT_MAXIMUMS,
    noah_recruit_authorizeable,
)
from tasks.noahs_tavern_recruit_maintenance import (
    MAINTENANCE_TASK_ID, NoahMaintenanceState, NoahTavernMaintenanceController,
    PersistedTierState, basic_rollover_observation_pending,
    rollover_persisted_maintenance_state,
)
from tasks.noahs_tavern_recruit_runtime import NoahAction, NoahTavernRecruitRuntimeController
from tasks.noahs_tavern_recruit_vision import recognize_noahs_tavern_frame
from tasks.scheduler_task_result import SchedulerIdentity


FIXTURES = Path(__file__).with_name("fixtures") / "noah_basic_rollover_observation"


def source(remaining=5, *, now=100.0, digest="a" * 64):
    return NoahTavernObservation(
        screen_state=NOAHS_TAVERN_SCREEN, selected_tier=RecruitTier.BASIC,
        tiers=tuple(NoahTierObservation(
            tier=tier, daily_attempt_maximum=TIER_ATTEMPT_MAXIMUMS[tier],
            attempts_remaining=remaining if tier is RecruitTier.BASIC else None,
            free_control_visible=tier is RecruitTier.BASIC,
            free_control_enabled=tier is RecruitTier.BASIC,
            target_roi=(90, 925, 385, 1055), panel_roi=(40, 840, 760, 1070),
            target_identity=NOAHS_TAVERN_FREE_TARGET,
            control_class=NOAHS_TAVERN_FREE_TARGET, cost_type="none", cost_amount=0,
            quantity=1, recognized=True,
        ) for tier in RecruitTier),
        frame_sha256=digest, captured_monotonic=now, recognized=True,
    )


def selected_changes(observation, **changes):
    return replace(observation, tiers=tuple(
        replace(item, **changes) if item.tier is RecruitTier.BASIC else item
        for item in observation.tiers
    ))


class BasicRolloverObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SafetyStore(Path(self.temp.name) / "offline.sqlite3")
        self.addCleanup(self.store.close)
        self.repo = SQLiteSchedulerInvocationRepository(self.store)
        self.identity = SchedulerIdentity("offline-account", "offline-server", "new-reset", MAINTENANCE_TASK_ID)
        prior = NoahMaintenanceState("offline-account", "offline-server", "old-reset", basic_daily_count=5)
        prior.tiers[RecruitTier.INT] = PersistedTierState(0, 86500.0, 86400, "action_performed")
        prior.tiers[RecruitTier.ADV] = PersistedTierState(0, 172900.0, 172800, "action_performed")
        rolled = rollover_persisted_maintenance_state(prior, self.identity.reset_id, self.repo, 90.0)
        # A stale native zero must not invent five consumed actions.
        controller = self.runtime(rolled)
        self.assertEqual(controller.next_command(self.recognition(source(0))).action, NoahAction.RECRUIT_FREE)
        self.assertEqual(controller.maintenance_controller.state.basic_daily_count, 0)
        self.assertEqual(self.restored().basic_daily_count, 0)

    def restored(self):
        return NoahMaintenanceState.from_scheduler_invocation(self.repo.get(self.identity))

    def runtime(self, state=None, **kwargs):
        return NoahTavernRecruitRuntimeController(
            now=100.0, maintenance_state=state or self.restored(),
            repository=self.repo, scheduler_identity=self.identity, **kwargs,
        )

    @staticmethod
    def recognition(observation):
        return SimpleNamespace(observation=observation, frame_sha256=observation.frame_sha256)

    def verified_commit(self, runtime, before):
        result = replace(before, screen_state=HERO_RECRUIT_RESULT_SCREEN,
                         selected_tier=None, result_tier=RecruitTier.BASIC,
                         frame_sha256=hashlib.sha256((before.frame_sha256 + "result").encode()).hexdigest(),
                         captured_monotonic=before.captured_monotonic + 1,
                         safe_close_visible=True, safe_close_roi=(100, 1000, 340, 1070))
        after = selected_changes(before, attempts_remaining=max(0, (before.tier(RecruitTier.BASIC).attempts_remaining or 1) - 1),
                                 cooldown_text="Free in 00:10:00", cooldown_duration_seconds=600,
                                 cooldown_active=True, next_eligible_timestamp=before.captured_monotonic + 600,
                                 free_control_enabled=False)
        after = replace(after, frame_sha256=hashlib.sha256((before.frame_sha256 + "after").encode()).hexdigest(),
                        captured_monotonic=before.captured_monotonic + 2)
        self.assertTrue(runtime.accept_postcondition(self.recognition(result), after))

    def test_retained_native_source_independently_recognizes_authorized_full_basic_quota(self):
        path = FIXTURES / "basic-free-five-20261030.png"
        provenance = json.loads(path.with_suffix(".provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), provenance["transport_sha256"])
        original = Path(__file__).parents[1] / provenance["source"]
        if original.exists():
            self.assertEqual(original.read_bytes(), path.read_bytes())
        tesseract = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")
        with patch.object(pytesseract.pytesseract, "tesseract_cmd", str(tesseract) if tesseract.exists() else "tesseract"):
            try:
                pytesseract.get_tesseract_version()
            except (OSError, RuntimeError, pytesseract.TesseractNotFoundError):
                self.skipTest("Tesseract unavailable for retained native OCR")
            observed = recognize_noahs_tavern_frame(cv2.imread(str(path)), captured_monotonic=100.0)
        self.assertEqual(observed.frame_sha256, provenance["decoded_frame_sha256"])
        self.assertEqual(observed.selected_tier, RecruitTier.BASIC)
        self.assertEqual(observed.tier(RecruitTier.BASIC).attempts_remaining, 5)
        self.assertTrue(noah_recruit_authorizeable(observed, RecruitTier.BASIC))
        self.assertEqual(self.runtime().next_command(self.recognition(observed)).action, NoahAction.RECRUIT_FREE)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), provenance["transport_sha256"])

    def test_native_stale_zero_free_button_commits_one_action_and_preserves_other_timers(self):
        path = FIXTURES / "basic-free-zero-20261102.png"
        provenance = json.loads(path.with_suffix(".provenance.json").read_text())
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), provenance["transport_sha256"])
        tesseract = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")
        with patch.object(pytesseract.pytesseract, "tesseract_cmd", str(tesseract) if tesseract.exists() else "tesseract"):
            observed = recognize_noahs_tavern_frame(cv2.imread(str(path)), captured_monotonic=100.0)
        self.assertEqual(observed.frame_sha256, provenance["decoded_frame_sha256"])
        self.assertEqual(observed.tier(RecruitTier.BASIC).attempts_remaining, 0)
        self.assertTrue(noah_recruit_authorizeable(observed, RecruitTier.BASIC))
        runtime = self.runtime()
        previous = self.restored()
        self.assertEqual(runtime.next_command(self.recognition(observed)).action, NoahAction.RECRUIT_FREE)
        self.verified_commit(runtime, observed)
        saved = self.restored()
        self.assertEqual(saved.basic_daily_count, 1)
        self.assertEqual(saved.tiers[RecruitTier.BASIC].next_eligible_at, 700.0)
        for tier in (RecruitTier.INT, RecruitTier.ADV):
            self.assertEqual(saved.tiers[tier], previous.tiers[tier])
        restarted = self.runtime()
        self.assertNotEqual(restarted.next_command(self.recognition(observed), now=699).action, NoahAction.RECRUIT_FREE)
        cooldown = selected_changes(observed, free_control_enabled=False, cooldown_active=True,
                                    cooldown_text="Free in 00:00:01", cooldown_duration_seconds=1,
                                    next_eligible_timestamp=700.0)
        self.assertFalse(restarted.maintenance_controller.current_tier_eligible(cooldown, RecruitTier.BASIC, now=699))
        self.assertEqual(restarted.maintenance_controller.state.basic_daily_count, 1)
        self.assertEqual(restarted.next_command(self.recognition(observed), now=701).action, NoahAction.RECRUIT_FREE)

    def test_restart_uses_durable_zero_and_first_verified_recruit_consumes_sentinel(self):
        before_row = self.repo.get(self.identity)
        runtime = self.runtime()
        before = source()
        self.assertTrue(basic_rollover_observation_pending(runtime.maintenance_controller.state))
        self.assertEqual(runtime.next_command(self.recognition(before)).action, NoahAction.RECRUIT_FREE)
        saved = self.restored()
        self.assertEqual(saved.basic_daily_count, 0)
        self.assertEqual(saved.revision, before_row.revision)
        self.assertEqual(saved.tiers[RecruitTier.INT], NoahMaintenanceState.from_scheduler_invocation(before_row).tiers[RecruitTier.INT])
        self.assertEqual(saved.tiers[RecruitTier.ADV].cooldown_seconds, 172800)
        self.verified_commit(runtime, before)
        consumed = self.restored()
        self.assertEqual(consumed.basic_daily_count, 1)
        self.assertEqual(consumed.tiers[RecruitTier.BASIC].attempts_remaining, 4)
        self.assertEqual(consumed.tiers[RecruitTier.BASIC].last_outcome, "action_performed")
        self.assertEqual(consumed.tiers[RecruitTier.BASIC].next_eligible_at, 700.0)
        self.assertFalse(basic_rollover_observation_pending(consumed))

    def test_confirmed_partial_exhausted_and_legacy_states_never_lower_daily_ownership(self):
        for tier_state in (
            PersistedTierState(4, 700.0, 600, "action_performed"),
            PersistedTierState(3, None, 600, "deferred"),
            PersistedTierState(0, None, 600, "complete_for_reset"),
            PersistedTierState(5, None, 600, "never_observed"),
            PersistedTierState(5, 700.0, 600, "reset_rollover"),
            PersistedTierState(5, None, 599, "reset_rollover"),
        ):
            with self.subTest(state=tier_state):
                state = self.restored()
                state.basic_daily_count = 5
                state.tiers[RecruitTier.BASIC] = tier_state
                self.assertFalse(NoahTavernMaintenanceController(state).current_tier_eligible(source(), RecruitTier.BASIC))
                self.assertEqual(state.basic_daily_count, 5)

    def test_invalid_or_partial_current_sources_cannot_rearm(self):
        valid = source()
        cases = [replace(valid, stale=True), replace(valid, recognized=False),
                 replace(valid, screen_state="UNKNOWN"), replace(valid, overlay_state="popup"),
                 replace(valid, frame_sha256=""), replace(valid, selected_tier=RecruitTier.INT),
                 selected_changes(valid, free_control_enabled=False),
                 selected_changes(valid, cost_type="premium", cost_amount=1),
                 selected_changes(valid, attempts_remaining=None),
                 selected_changes(valid, attempts_remaining=4),
                 selected_changes(valid, recognized=False), selected_changes(valid, overlapping_target=True)]
        for observation in cases:
            with self.subTest(observation=observation):
                runtime = self.runtime()
                runtime.maintenance_controller.state.basic_daily_count = 5
                row = self.repo.get(self.identity)
                self.assertNotEqual(runtime.next_command(self.recognition(observation)).action, NoahAction.RECRUIT_FREE)
                self.assertEqual(runtime.maintenance_controller.state.basic_daily_count, 5)
                self.assertEqual(self.repo.get(self.identity), row)

    def test_unresolved_dispatch_still_stops_without_changing_maintenance_state(self):
        row = self.repo.get(self.identity)
        runtime = self.runtime()
        runtime.progress.awaiting_postcondition = True
        runtime.progress.last_dispatch_state = "postcondition_unresolved"
        self.assertEqual(runtime.next_command(self.recognition(source())).action, NoahAction.STOP)
        self.assertEqual(self.repo.get(self.identity), row)

    def test_pending_helper_is_exact_and_never_lowers_inferred_count(self):
        state = self.restored()
        for count in (0, 2, 5):
            state.basic_daily_count = count
            self.assertTrue(basic_rollover_observation_pending(state))
        self.assertFalse(NoahTavernMaintenanceController(state).current_tier_eligible(source(), RecruitTier.BASIC))
        self.assertEqual(state.basic_daily_count, 5)
        for tier_state in (
            PersistedTierState(4, None, 600, "reset_rollover"),
            PersistedTierState(5, 700.0, 600, "reset_rollover"),
            PersistedTierState(5, None, 86400, "reset_rollover"),
            PersistedTierState(5, None, 600, "action_performed"),
            PersistedTierState(5, None, 600, "deferred"),
            PersistedTierState(5, None, 600, "never_observed"),
        ):
            with self.subTest(tier_state=tier_state):
                state.tiers[RecruitTier.BASIC] = tier_state
                self.assertFalse(basic_rollover_observation_pending(state))

    def test_five_verified_commits_still_cap_even_if_later_source_claims_five(self):
        runtime = self.runtime()
        for index in range(5):
            now = 100.0 + index * 700
            before = source(5 - index, now=now, digest=hashlib.sha256(str(index).encode()).hexdigest())
            self.assertEqual(runtime.next_command(self.recognition(before), now=now).action, NoahAction.RECRUIT_FREE)
            self.verified_commit(runtime, before)
        self.assertEqual(self.restored().basic_daily_count, 5)
        restarted = self.runtime()
        self.assertNotEqual(restarted.next_command(self.recognition(source()), now=10000).action, NoahAction.RECRUIT_FREE)
        self.assertEqual(self.restored().basic_daily_count, 5)


if __name__ == "__main__":
    unittest.main()
