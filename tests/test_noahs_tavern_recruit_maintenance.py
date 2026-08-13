from __future__ import annotations

from dataclasses import replace
import unittest
from pathlib import Path
import tempfile

from tasks.noahs_tavern_recruit import (
    HERO_RECRUIT_RESULT_SCREEN,
    HOME_BASE_SCREEN,
    NOAHS_TAVERN_SCREEN,
    NOAHS_TAVERN_FREE_TARGET,
    NoahTavernObservation,
    NoahTierObservation,
    RecruitTier,
    TIER_ATTEMPT_MAXIMUMS,
)
from tasks.noahs_tavern_recruit_maintenance import (
    DAILY_RECRUITMENT_TASK_ID,
    MAINTENANCE_TASK_ID,
    NoahMaintenanceState,
    NoahTavernMaintenanceController,
    PersistedTierState,
    TierPassEvidence,
    TierPassOutcome,
    replay_noahs_tavern_maintenance,
    rollover_maintenance_state,
    rollover_persisted_maintenance_state,
)
from tasks.scheduler_task_result import SchedulerIdentity, SchedulerTaskOutcome
from safe_action_core import SafetyStore, SQLiteSchedulerInvocationRepository
from tasks.noahs_tavern_recruit_runtime import NoahTavernRecruitRuntimeController
from scripts.noahs_tavern_recruit_bluestacks import NoahTavernIntegratedRoute


class MaintenanceFixtures:
    def tier(self, tier, *, remaining=None, enabled=True, cooldown=False, next_at=None, cost_type="none", quantity=1):
        return NoahTierObservation(
            tier=tier,
            daily_attempt_maximum=TIER_ATTEMPT_MAXIMUMS[tier],
            attempts_remaining=TIER_ATTEMPT_MAXIMUMS[tier] if remaining is None else remaining,
            cooldown_text=("00:10:00" if tier is RecruitTier.BASIC else "24:00:00" if tier is RecruitTier.INT else "2d00:00:00") if cooldown else "",
            cooldown_duration_seconds=(600 if tier is RecruitTier.BASIC else 86400 if tier is RecruitTier.INT else 172800) if cooldown else None,
            cooldown_active=cooldown,
            next_eligible_timestamp=next_at,
            free_control_visible=enabled,
            free_control_enabled=enabled,
            target_roi=(100, 900, 360, 1030),
            panel_roi=(20, 800, 780, 1080),
            target_identity=NOAHS_TAVERN_FREE_TARGET,
            control_class=NOAHS_TAVERN_FREE_TARGET,
            cost_type=cost_type,
            cost_amount=0 if cost_type == "none" else 1,
            quantity=quantity,
            recognized=True,
        )

    def before(self, tier, **kwargs):
        observation_changes = {}
        if "claim_visible" in kwargs:
            observation_changes["claim_visible"] = kwargs.pop("claim_visible")
        tier_kwargs = dict(kwargs)
        tier_kwargs["enabled"] = tier_kwargs.pop("enabled", True)
        tiers = tuple(self.tier(item, enabled=(tier_kwargs["enabled"] if item is tier else False), **({k: v for k, v in tier_kwargs.items() if k != "enabled"} if item is tier else {})) for item in RecruitTier)
        return NoahTavernObservation(
            screen_state=NOAHS_TAVERN_SCREEN,
            selected_tier=tier,
            tiers=tiers,
            frame_sha256=("a" if tier is RecruitTier.BASIC else "b" if tier is RecruitTier.INT else "c") * 64,
            captured_monotonic=100.0,
            recognized=True,
            **observation_changes,
        )

    def result(self, tier):
        return NoahTavernObservation(
            screen_state=HERO_RECRUIT_RESULT_SCREEN,
            selected_tier=None,
            tiers=tuple(self.tier(item, enabled=False) for item in RecruitTier),
            frame_sha256="d" * 64,
            captured_monotonic=101.0,
            recognized=True,
            result_tier=tier,
            result_identity="hero fragment",
            safe_close_visible=True,
            safe_close_roi=(100, 1000, 360, 1070),
        )

    def after(self, before, tier):
        selected = before.tier(tier)
        cooldown = 600 if tier is RecruitTier.BASIC else 86400 if tier is RecruitTier.INT else 172800
        text = "00:10:00" if tier is RecruitTier.BASIC else "24:00:00" if tier is RecruitTier.INT else "2d00:00:00"
        updated = replace(
            selected,
            attempts_remaining=(selected.attempts_remaining or 0) - 1,
            cooldown_text=f"Free in {text}",
            cooldown_duration_seconds=cooldown,
            cooldown_active=True,
            next_eligible_timestamp=100.0 + cooldown,
            free_control_enabled=False,
        )
        return replace(
            before,
            tiers=tuple(updated if item.tier is tier else item for item in before.tiers),
            frame_sha256="e" * 64,
            captured_monotonic=102.0,
        )

    def evidence(self, tier, **kwargs):
        before = self.before(tier, **kwargs)
        return TierPassEvidence(before, self.result(tier), self.after(before, tier))

    def home(self):
        return NoahTavernObservation(
            screen_state=HOME_BASE_SCREEN,
            selected_tier=None,
            tiers=tuple(self.tier(item, enabled=False) for item in RecruitTier),
            frame_sha256="f" * 64,
            recognized=True,
        )

    def identity(self, task_id=MAINTENANCE_TASK_ID, reset="reset-1"):
        return SchedulerIdentity("acct-1", "server-1", reset, task_id)


class NoahMaintenanceControllerTests(unittest.TestCase):
    def setUp(self):
        self.f = MaintenanceFixtures()
        self.identity = self.f.identity()
        self.state = NoahMaintenanceState.for_identity(self.identity)

    def all_evidence(self):
        return {tier: self.f.evidence(tier) for tier in RecruitTier}

    def test_all_three_eligible_are_used_and_basic_owns_daily(self):
        result = NoahTavernMaintenanceController(self.state, now=100.0).run_pass(self.all_evidence(), self.f.home(), identity=self.identity)
        self.assertEqual(result.scheduler_result.outcome, SchedulerTaskOutcome.DEFERRED)
        self.assertEqual(result.recruitment_dispatch_count, 0)
        self.assertEqual(result.verified_transition_count, 3)
        self.assertEqual(result.state.basic_daily_count, 1)
        self.assertEqual(result.state.tiers[RecruitTier.BASIC].attempts_remaining, 4)
        self.assertEqual(result.state.tiers[RecruitTier.INT].attempts_remaining, 0)
        self.assertEqual(result.state.tiers[RecruitTier.ADV].attempts_remaining, 0)
        self.assertTrue(result.terminal_home_verified)

    def test_int_and_advanced_do_not_increment_daily(self):
        evidence = {tier: self.f.evidence(tier) for tier in (RecruitTier.INT, RecruitTier.ADV)}
        evidence[RecruitTier.BASIC] = self.f.evidence(RecruitTier.BASIC)
        state = NoahMaintenanceState.for_identity(self.identity)
        state.basic_daily_count = 5
        result = NoahTavernMaintenanceController(state, now=100.0).run_pass(evidence, self.f.home(), identity=self.identity)
        self.assertEqual(result.state.basic_daily_count, 5)
        self.assertEqual(result.recruitment_dispatch_count, 0)
        self.assertEqual(result.verified_transition_count, 2)

    def test_cooldown_is_deferred_with_independent_next_eligibility(self):
        evidence = self.all_evidence()
        evidence[RecruitTier.INT] = TierPassEvidence(self.f.before(RecruitTier.INT, remaining=0, enabled=False, cooldown=True, next_at=200.0))
        result = NoahTavernMaintenanceController(self.state, now=100.0).run_pass(evidence, self.f.home(), identity=self.identity)
        self.assertEqual(result.tier_results[1].outcome, TierPassOutcome.DEFERRED)
        self.assertEqual(result.state.tiers[RecruitTier.INT].next_eligible_at, 200.0)
        self.assertEqual(result.state.basic_daily_count, 1)

    def test_basic_maximum_is_idempotent_and_int_adv_still_run(self):
        state = NoahMaintenanceState.for_identity(self.identity)
        state.basic_daily_count = 5
        state.tiers[RecruitTier.BASIC] = PersistedTierState(0, 700.0, 600, "complete_for_reset")
        evidence = self.all_evidence()
        result = NoahTavernMaintenanceController(state, now=100.0).run_pass(evidence, self.f.home(), identity=self.identity)
        self.assertEqual(result.tier_results[0].outcome, TierPassOutcome.ALREADY_COMPLETE)
        self.assertEqual(result.recruitment_dispatch_count, 0)
        self.assertEqual(result.state.basic_daily_count, 5)

    def test_persisted_basic_count_blocks_sixth_even_if_frame_is_stale(self):
        state = NoahMaintenanceState.for_identity(self.identity)
        state.basic_daily_count = 4
        state.tiers[RecruitTier.BASIC] = PersistedTierState(1, None, 600, "action_performed")
        first = NoahTavernMaintenanceController(state, now=100.0).run_pass(
            {tier: self.f.evidence(tier) for tier in RecruitTier}, self.f.home(), identity=self.identity
        )
        self.assertEqual(first.state.basic_daily_count, 5)
        # The frame still (incorrectly) claims one Basic free attempt; persisted Daily ownership wins.
        second = NoahTavernMaintenanceController(first.state, now=101.0).run_pass(
            {tier: self.f.evidence(tier) for tier in RecruitTier}, self.f.home(), identity=self.identity
        )
        self.assertEqual(second.tier_results[0].outcome, TierPassOutcome.ALREADY_COMPLETE)
        self.assertEqual(second.state.basic_daily_count, 5)

    def test_paid_ten_x_and_claim_are_rejected(self):
        for kwargs in ({"cost_type": "currency"}, {"quantity": 10}):
            evidence = self.all_evidence()
            evidence[RecruitTier.BASIC] = TierPassEvidence(self.f.before(RecruitTier.BASIC, **kwargs))
            result = NoahTavernMaintenanceController(self.state, now=100.0).run_pass(evidence, self.f.home(), identity=self.identity)
            self.assertEqual(result.scheduler_result.outcome, SchedulerTaskOutcome.BLOCKED)
            self.assertEqual(result.state.basic_daily_count, 0)
        evidence = self.all_evidence()
        evidence[RecruitTier.BASIC] = TierPassEvidence(self.f.before(RecruitTier.BASIC, claim_visible=True))
        result = NoahTavernMaintenanceController(self.state, now=100.0).run_pass(evidence, self.f.home(), identity=self.identity)
        self.assertEqual(result.scheduler_result.outcome, SchedulerTaskOutcome.BLOCKED)

    def test_missing_or_bad_home_is_fail_closed(self):
        result = NoahTavernMaintenanceController(self.state, now=100.0).run_pass(self.all_evidence(), None, identity=self.identity)
        self.assertEqual(result.scheduler_result.outcome, SchedulerTaskOutcome.BLOCKED)
        self.assertFalse(result.terminal_home_verified)

    def test_zero_transport_replay_and_persistence_round_trip(self):
        evidence = self.all_evidence()
        result, raw = replay_noahs_tavern_maintenance(self.state.to_json(), evidence, self.f.home(), identity=self.identity, now=100.0)
        self.assertEqual(result.scheduler_result.outcome, SchedulerTaskOutcome.DEFERRED)
        self.assertEqual(result.scheduler_result.action_count, 0)
        self.assertEqual(result.scheduler_result.dispatched_actions, ())
        restored = NoahMaintenanceState.from_json(raw)
        self.assertEqual(restored.basic_daily_count, 1)
        self.assertEqual(restored.tiers[RecruitTier.INT].next_eligible_at, 86500.0)

    def test_existing_sqlite_invocation_repository_restores_state_after_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SafetyStore(Path(folder) / "maintenance.sqlite3")
            repo = SQLiteSchedulerInvocationRepository(store)
            result, _ = replay_noahs_tavern_maintenance(
                self.state.to_json(), self.all_evidence(), self.f.home(), identity=self.identity, now=100.0, repository=repo
            )
            self.assertEqual(result.scheduler_result.action_count, 0)
            stored = repo.get(self.identity)
            self.assertIsNotNone(stored)
            restored = NoahMaintenanceState.from_scheduler_invocation(stored)
            self.assertEqual(restored.basic_daily_count, 1)
            self.assertEqual(restored.tiers[RecruitTier.ADV].next_eligible_at, 172900.0)
            store.close()

    def test_reset_rollover_resets_only_basic_daily_ownership(self):
        state = NoahMaintenanceState.for_identity(self.identity)
        state.basic_daily_count = 5
        state.tiers[RecruitTier.INT] = PersistedTierState(0, 86500.0, 86400, "action_performed")
        rolled = rollover_maintenance_state(state, "reset-2")
        self.assertEqual(rolled.basic_daily_count, 0)
        self.assertEqual(rolled.tiers[RecruitTier.BASIC].attempts_remaining, 5)
        self.assertEqual(rolled.tiers[RecruitTier.INT].next_eligible_at, 86500.0)

    def test_reset_rollover_writes_new_repository_identity_and_preserves_long_cooldown(self):
        state = NoahMaintenanceState.for_identity(self.identity)
        state.basic_daily_count = 5
        state.tiers[RecruitTier.INT] = PersistedTierState(0, 86500.0, 86400, "action_performed")
        with tempfile.TemporaryDirectory() as folder:
            store = SafetyStore(Path(folder) / "rollover.sqlite3")
            repo = SQLiteSchedulerInvocationRepository(store)
            rolled = rollover_persisted_maintenance_state(state, "reset-2", repo, 200.0)
            row = repo.get(SchedulerIdentity("acct-1", "server-1", "reset-2", MAINTENANCE_TASK_ID))
            self.assertIsNotNone(row)
            restored = NoahMaintenanceState.from_scheduler_invocation(row)
            self.assertEqual(restored.basic_daily_count, 0)
            self.assertEqual(restored.tiers[RecruitTier.INT].next_eligible_at, 86500.0)
            self.assertIsNone(repo.get(self.identity))
            store.close()

    def test_integrated_runtime_controller_delegates_shared_pass_and_stops_unknown(self):
        controller = NoahTavernRecruitRuntimeController(now=100.0, maintenance_state=self.state)
        result = controller.run_maintenance_pass(self.all_evidence(), self.f.home(), identity=self.identity)
        self.assertEqual(result.verified_transition_count, 3)
        blocked = dict(self.all_evidence())
        blocked[RecruitTier.INT] = TierPassEvidence(replace(blocked[RecruitTier.INT].before, recognized=False))
        stopped = NoahTavernRecruitRuntimeController(now=100.0, maintenance_state=self.state).run_maintenance_pass(blocked, self.f.home(), identity=self.identity)
        self.assertEqual(stopped.scheduler_result.outcome, SchedulerTaskOutcome.BLOCKED)
        self.assertEqual(stopped.verified_transition_count, 0)

    def test_integrated_route_uses_same_shared_controller_seam(self):
        controller = NoahTavernRecruitRuntimeController(now=100.0, maintenance_state=self.state)
        route = NoahTavernIntegratedRoute(object(), controller=controller)
        result = route.run_maintenance_pass(self.all_evidence(), self.f.home(), identity=self.identity)
        self.assertEqual(result.verified_transition_count, 3)
        self.assertEqual(result.recruitment_dispatch_count, 0)

    def test_integrated_route_run_drives_shared_commands_with_sealed_transport(self):
        from types import SimpleNamespace

        before = self.f.before(RecruitTier.BASIC)
        home = replace(self.f.home(), home_tavern_target_roi=(10, 10, 20, 20))
        after = self.f.after(before, RecruitTier.BASIC)
        result = self.f.result(RecruitTier.BASIC)
        int_result = self.f.result(RecruitTier.INT)
        adv_result = self.f.result(RecruitTier.ADV)
        int_before = self.f.before(RecruitTier.INT)
        int_after = self.f.after(int_before, RecruitTier.INT)
        adv_before = self.f.before(RecruitTier.ADV)
        adv_after = self.f.after(adv_before, RecruitTier.ADV)
        sequence = [home, before, result, result, after, int_before, int_result, int_result, int_after, adv_before, adv_result, adv_result, adv_after, adv_after, self.f.home()]

        class SealedRuntime:
            execute = True
            session = "sealed-replay"
            transport_mode = "simulated_in_memory"
            def __init__(self):
                self.index = 0
                self.inputs = []
                self.physical_transport_calls = 0
            def capture(self, _label):
                import numpy as np
                import time
                item = SimpleNamespace(frame=np.zeros((1280, 800, 3), dtype=np.uint8), captured_monotonic=time.monotonic(), sha256=(chr(97 + self.index) * 64))
                self.index += 1
                return item
            def tap(self, _captured, **kwargs):
                self.inputs.append(("tap", kwargs))
                # The route's transport boundary is sealed for this production-shaped replay.
                if kwargs.get("physical_transport", False):
                    self.physical_transport_calls += 1
                    raise AssertionError("sealed replay attempted physical transport")
            def back(self, _captured, **kwargs):
                self.inputs.append(("back", kwargs))
            def measure_device_state(self):
                return "device"
            def measure_foreground_package(self):
                return "com.global.ztmslg"
            def reconcile(self, *_args):
                return None

        sealed = SealedRuntime()
        atlas_calls = []

        def bind_atlas(captured):
            atlas_calls.append(captured.sha256)
            return (10, 20, 30, 40)

        with tempfile.TemporaryDirectory() as folder:
            store = SafetyStore(Path(folder) / "route.sqlite3")
            repo = SQLiteSchedulerInvocationRepository(store)
            controller = NoahTavernRecruitRuntimeController(
                now=0.0,
                maintenance_state=self.state,
                repository=repo,
                scheduler_identity=self.identity,
            )
            route = NoahTavernIntegratedRoute(
                sealed,
                controller=controller,
                recognizer=lambda _frame, **_kwargs: sequence.pop(0),
                post_input_delay=0.0,
                result_timeout=0.1,
                atlas_binding=bind_atlas,
            )
            outcome = route.run(max_steps=10)
            self.assertEqual(outcome.status, "completed", outcome.reason)
            self.assertEqual(len(sealed.inputs), 8)  # open, three free singles, three closes, terminal back
            self.assertEqual(sealed.physical_transport_calls, 0)
            self.assertEqual(sealed.transport_mode, "simulated_in_memory")
            self.assertFalse(hasattr(sealed, "runner"))
            self.assertEqual(sealed.inputs[0][1]["target_identity"], "home.building.noahs_tavern")
            self.assertEqual(sealed.inputs[0][1]["target_roi"], (10, 20, 30, 40))
            self.assertEqual(atlas_calls, ["a" * 64])
            self.assertEqual(sum(1 for kind, _ in sealed.inputs if kind == "back"), 1)
            self.assertEqual(sealed.inputs[1][1]["target_identity"], "noahs-tavern-daily-free")
            stored = repo.get(self.identity)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.action_count_total, 0)
            self.assertEqual(stored.status, "deferred")
            store.close()

    def test_integrated_route_requires_injected_or_production_atlas_binding(self):
        from types import SimpleNamespace

        class Runtime:
            execute = True
            session = "atlas-binding-test"

            def __init__(self):
                self.index = 0
                self.inputs = []

            def capture(self, _label):
                item = SimpleNamespace(frame=object(), captured_monotonic=float(self.index + 1), sha256=(chr(97 + self.index) * 64))
                self.index += 1
                return item

            def tap(self, _captured, **kwargs):
                self.inputs.append(kwargs)

            def back(self, _captured, **kwargs):
                self.inputs.append({"back": True, **kwargs})

        home = replace(self.f.home(), home_tavern_target_roi=(10, 10, 20, 20))
        runtime = Runtime()
        route = NoahTavernIntegratedRoute(
            runtime,
            controller=NoahTavernRecruitRuntimeController(now=0.0, maintenance_state=self.state),
            recognizer=lambda _frame, **_kwargs: home,
            post_input_delay=0.0,
        )
        blocked = route.run(max_steps=1)
        self.assertEqual(blocked.status, "blocked")
        self.assertEqual(blocked.reason, "home_atlas_tavern_binding_not_proven")
        self.assertEqual(runtime.inputs, [])

        runtime = Runtime()
        wrong_source = replace(home, screen_state="UNKNOWN", recognized=False)
        route = NoahTavernIntegratedRoute(
            runtime,
            controller=NoahTavernRecruitRuntimeController(now=0.0, maintenance_state=self.state),
            recognizer=lambda _frame, **_kwargs: wrong_source,
            atlas_binding=lambda captured: (10, 20, 30, 40),
            post_input_delay=0.0,
        )
        blocked = route.run(max_steps=1)
        self.assertEqual(blocked.status, "blocked")
        self.assertEqual(blocked.reason, "maximum controller steps exceeded")
        self.assertEqual(
            runtime.inputs,
            [{
                "target_identity": "home.building.noahs_tavern",
                "target_roi": (10, 20, 30, 40),
                "action_key": "noah:open:" + "a" * 64,
            }],
        )

    def test_capture_delay_cooldown_is_bounded_below_policy_duration(self):
        evidence = self.all_evidence()
        before = evidence[RecruitTier.BASIC].before
        after = self.f.after(before, RecruitTier.BASIC)
        delayed = replace(
            after.tier(RecruitTier.BASIC),
            cooldown_text="Free in 00:09:52",
            cooldown_duration_seconds=592,
        )
        delayed_after = replace(after, tiers=tuple(delayed if item.tier is RecruitTier.BASIC else item for item in after.tiers))
        evidence[RecruitTier.BASIC] = replace(evidence[RecruitTier.BASIC], after_close=delayed_after)
        result = NoahTavernMaintenanceController(self.state, now=100.0).run_pass(evidence, self.f.home(), identity=self.identity)
        self.assertEqual(result.tier_results[0].outcome, TierPassOutcome.ACTION_PERFORMED)

    def test_transport_observed_is_forbidden(self):
        evidence = self.all_evidence()
        evidence[RecruitTier.ADV] = replace(evidence[RecruitTier.ADV], transport_observed=True)
        result = NoahTavernMaintenanceController(self.state, now=100.0).run_pass(evidence, self.f.home(), identity=self.identity)
        self.assertEqual(result.scheduler_result.outcome, SchedulerTaskOutcome.BLOCKED)
        self.assertEqual(result.state.basic_daily_count, 0)

    def test_daily_identity_can_share_pass_without_claim_or_scheduler_activation(self):
        identity = self.f.identity(DAILY_RECRUITMENT_TASK_ID)
        result = NoahTavernMaintenanceController(self.state, now=100.0).run_pass(self.all_evidence(), self.f.home(), identity=identity)
        self.assertEqual(result.scheduler_result.identity.task_id, DAILY_RECRUITMENT_TASK_ID)
        self.assertFalse(result.scheduler_result.consequence.get("claim_dispatched", False))


if __name__ == "__main__":
    unittest.main()
