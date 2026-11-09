"""The public AP runner keeps one native input boundary and one pending battle."""
from contextlib import ExitStack
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import bluestacks_campaign_ap as live
from safe_action_core import ActionStatus, SafetyStore
from tasks.campaign_auto_battle import (CampaignAutoBattleConfig, CampaignRouteObservation,
    CampaignRouteProgress, CampaignScreen)
from tasks.campaign_auto_battle_vision import CampaignFrameRecognition
from tests.support.campaign_ap_runner import (
    DrainFakeADB, PHASES, STAGE, STAGE_ROI, recognize, recognize_drain,
)


class StableBattleDrainFakeADB(DrainFakeADB):
    """Repeat exact battle PNGs; AP facts remain visible on their actual screens."""
    def capture_png(self):
        self.capture_count += 1
        if self.on_capture:
            self.on_capture(self.capture_count)
        frame = np.full((1280, 800, 3), PHASES.index(self.phase), np.uint8)
        if self.phase not in {"lineup", "battle", "winner"}:
            frame[2, 2] = (self.ap, self.cost, 0)
        success, png = cv2.imencode(".png", frame)
        assert success
        return png.tobytes()

    def dispatch_tap(self, point):
        if self.phase == "battle":
            self.inputs.append(("tap", point))
            self.phase = "winner"
            if self.on_input:
                self.on_input(len(self.inputs))
            return
        super().dispatch_tap(point)


class CampaignApNativeRunnerTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        temporary = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.root = Path(temporary)
        self.runner = DrainFakeADB(ap=14, regen_per_battle=1, phase="stage")
        self.runtime = live.LocalBlueStacksRuntime(self.runner, self.root / "route", execute=True)
        self.runtime.max_inputs = 16
        self.stopped = False
        self.checkpoints = 0
        self.stage_sources = []
        self.stack.enter_context(patch.object(live.LocalBlueStacksRuntime, "connect",
                                             side_effect=AssertionError("device access forbidden")))
        self.stack.enter_context(patch.object(live, "recognize_campaign_frame", side_effect=lambda frame, stage, **kwargs:
            recognize_drain(frame, stage, world=self.runner, **kwargs)))
        self.config = CampaignAutoBattleConfig(target_stage=STAGE, ap_cost=14, ap_budget=14, max_runs=1,
                                               battle_poll_seconds=0.01, battle_timeout_seconds=1)

    def checkpoint(self):
        self.checkpoints += 1
        if self.stopped:
            raise RuntimeError("STOP_REQUESTED")

    def boundary(self, source, recognition, command, *, progress):
        self.stage_sources.append(source)
        self.assertEqual(recognition.observation.stage_dialog, STAGE)
        self.assertEqual(recognition.observation.ap_cost, 14)
        self.assertEqual(command.target_roi, STAGE_ROI)
        action_key = f"accepted-stage-entry:{source.sha256}"
        self.runtime.tap(source, target_identity=command.target_identity, target_roi=command.target_roi,
                         action_key=action_key, action_class="campaign_ap_challenge", consequential=True)
        post = self.runtime.capture("policy-stage-entry-successor")
        self.runtime.reconcile(action_key, "confirmed", post, "test Stage successor verified Hero Lineup")
        return live.CampaignStageEntryResult("confirmed", "Hero Lineup verified", action_key, 1,
                                             post, recognize(post.frame, STAGE))

    def run_route(self, **kwargs):
        return live.run_campaign_ap_route(
            self.runtime, self.config, checkpoint=self.checkpoint,
            stage_challenge_boundary=kwargs.pop("stage_challenge_boundary", self.boundary),
            post_input_delay=0, maximum_steps=20, sleep=kwargs.pop("sleep", lambda _seconds: None), **kwargs)

    def events(self, name="events.jsonl"):
        return [json.loads(line) for line in (self.runtime.session / name).read_text().splitlines() if line]

    def native_boundary(self):
        store = SafetyStore(self.root / "actions.sqlite3")
        self.stack.callback(store.close)
        store.acquire_lease("test-owner", time.time(), 3600)
        return store, live.CampaignStageChallengeBoundary(
            self.runtime, store, self.config, owner="test-owner", game_day_id="game-day-2026-10-29",
            sleep=lambda _seconds: None, settle_seconds=0)

    def test_one_battle_commits_only_after_winner_chapter_ap_and_home(self):
        result = self.run_route()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["new_battle_count"], 1)
        self.assertEqual(result["committed_ap_effect_count"], 1)
        self.assertEqual(result["total_input_count"], len(self.runner.inputs))
        self.assertEqual(result["progress"]["completed_runs"], 1)
        self.assertEqual(result["progress"]["ap_spent"], 14)
        self.assertEqual(result["progress"]["ap_regenerated"], 1)
        self.assertFalse(result["effect_reconciliation_required"])
        self.assertEqual(len(self.stage_sources), 1)
        self.assertGreaterEqual(self.runner.capture_count, 2)
        commands = [row for row in self.events() if row.get("type") == "command"]
        lineup = next(row for row in commands if row["action"] == "CONFIRM_LINEUP")
        self.assertEqual(lineup["progress"]["ap_spent"], 0)
        self.assertEqual(lineup["progress"]["completed_runs"], 0)
        self.assertGreater(self.checkpoints, len(self.runner.inputs))

    def test_drain_repeats_at_chapter_with_fresh_unique_policy_entries(self):
        self.runner.ap, self.runner.regen_per_battle = 28, 0
        self.config = replace(self.config, max_runs=12, ap_budget=168)
        self.runtime.max_inputs = 96
        store, boundary = self.native_boundary()
        with patch.object(self.runtime, "measure_foreground_package", return_value="com.global.ztmslg"):
            result = self.run_route(stage_challenge_boundary=boundary)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["progress"]["current_ap"], 0)
        self.assertEqual(result["progress"]["ap_spent"], 28)
        self.assertEqual((result["stage_entry_transport_count"], result["new_battle_count"],
                          result["committed_ap_effect_count"]), (2, 2, 2))
        self.assertEqual(len(set(result["entry_action_keys"])), 2)
        self.assertEqual([key.rsplit(":", 1)[-1] for key in result["entry_action_keys"]], ["1", "2"])
        actions = store.list_actions_for_task(live.CAMPAIGN_AP_FLOW_ID)
        self.assertEqual(len(actions), 2)
        self.assertTrue(all(row["final_status"] == "confirmed" and row["cost_amount"] == 14 for row in actions))
        commands = [row["action"] for row in self.events() if row.get("type") == "command"]
        self.assertEqual(commands.count("RETURN_HOME"), 1)
        self.assertEqual(commands.count("LEAVE_CHAPTER_MAP"), 1)
        self.assertEqual(self.runner.battles_started, 2)

    def test_real_runtime_repeats_identical_lineup_auto_and_victory_under_new_confirmed_entries(self):
        self.runner = StableBattleDrainFakeADB(ap=28, phase="stage")
        self.runtime = live.LocalBlueStacksRuntime(self.runner, self.root / "stable-route", execute=True)
        self.runtime.max_inputs = 96
        self.config = replace(self.config, max_runs=12, ap_budget=168)
        store, boundary = self.native_boundary()

        def observed(frame, stage, **kwargs):
            found = recognize_drain(frame, stage, world=self.runner, **kwargs)
            if found.observation.screen is CampaignScreen.BATTLE:
                return replace(found, observation=replace(found.observation, auto_enabled=False),
                               targets=(("campaign-auto", (700, 1000, 780, 1080)),))
            return found

        with patch.object(live, "recognize_campaign_frame", side_effect=observed), \
                patch.object(self.runtime, "measure_foreground_package", return_value="com.global.ztmslg"):
            result = self.run_route(stage_challenge_boundary=boundary)
        self.assertEqual(result["status"], "completed")
        self.assertEqual((result["stage_entry_transport_count"], result["new_battle_count"],
                          result["committed_ap_effect_count"]), (2, 2, 2))
        self.assertEqual(result["progress"]["current_ap"], 0)
        entries = store.list_actions_for_task(live.CAMPAIGN_AP_FLOW_ID)
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(row["final_status"] == "confirmed" for row in entries))
        dispatches = [row for row in self.events("native-events.jsonl") if row["type"] == "dispatch"]
        for target in ("campaign-lineup-challenge", "campaign-auto", "campaign-victory-continue"):
            rows = [row for row in dispatches if row["target_identity"] == target]
            with self.subTest(target=target):
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[0]["source_sha256"], rows[1]["source_sha256"])
                self.assertEqual([row["continuation_of"] for row in rows], result["entry_action_keys"])
        self.assertEqual(result["total_input_count"], len(self.runner.inputs))

    def test_direct_stage_boundary_rejects_cumulative_budget_before_capture_or_input(self):
        self.config = replace(self.config, max_runs=2)
        _store, boundary = self.native_boundary()
        boundary.attempted_entries = 1
        source = self.runtime.capture("direct-budget-stage")
        recognition = recognize_drain(source.frame, STAGE, world=self.runner)
        command = live.CampaignRuntimeCommand(live.CampaignAction.CHALLENGE_STAGE, "tap", "test",
            target_identity="campaign-challenge-1-15-9", target_roi=STAGE_ROI)
        progress = CampaignRouteProgress(initial_ap=28, current_ap=14, completed_runs=1, ap_spent=14)
        captures = self.runner.capture_count
        with self.assertRaises(RuntimeError):
            boundary(source, recognition, command, progress=progress)
        self.assertEqual(boundary.attempted_entries, 1)
        self.assertEqual(self.runner.capture_count, captures)
        self.assertEqual(self.runtime.input_count, 0)
        self.assertEqual(self.runner.inputs, [])

    def test_direct_stage_boundary_requires_exact_typed_bounded_prior_ledger(self):
        self.config = replace(self.config, max_runs=12, ap_budget=168)
        _store, boundary = self.native_boundary()
        boundary.attempted_entries = 1
        source = self.runtime.capture("direct-typed-stage")
        recognition = recognize_drain(source.frame, STAGE, world=self.runner)
        command = live.CampaignRuntimeCommand(live.CampaignAction.CHALLENGE_STAGE, "tap", "test",
            target_identity="campaign-challenge-1-15-9", target_roi=STAGE_ROI)
        progress = CampaignRouteProgress(initial_ap=28, current_ap=14, completed_runs=1, ap_spent=14)
        invalid = [replace(progress, **{field: float(getattr(progress, field))})
                   for field in ("initial_ap", "current_ap", "completed_runs", "ap_spent", "ap_regenerated")]
        invalid += [replace(progress, loss_seen=0), replace(progress, ap_regenerated=False),
                    CampaignRouteProgress(initial_ap=121, current_ap=107, completed_runs=1, ap_spent=14),
                    CampaignRouteProgress(initial_ap=120, current_ap=121, completed_runs=1,
                                          ap_spent=14, ap_regenerated=15)]
        captures = self.runner.capture_count
        for malformed in invalid:
            with self.subTest(progress=malformed), self.assertRaises(RuntimeError):
                boundary(source, recognition, command, progress=malformed)
        self.assertEqual(boundary.attempted_entries, 1)
        self.assertEqual(self.runner.capture_count, captures)
        self.assertEqual(self.runtime.input_count, 0)
        self.assertEqual(self.runner.inputs, [])

    def test_affordable_ap_at_backstop_preserves_the_win_and_stops_without_another_input(self):
        self.runner.ap, self.runner.regen_per_battle = 28, 0
        result = self.run_route()
        self.assertNotEqual(result["status"], "completed")
        self.assertEqual(result["committed_ap_effect_count"], 1)
        self.assertEqual(result["progress"]["current_ap"], 14)
        self.assertEqual(result["new_battle_count"], 1)
        self.assertEqual(len(self.runner.inputs), 3)
        self.assertFalse(result["terminal_home_verified"])

    def test_terminal_normalizer_binds_returned_capture(self):
        self.runner.ap, self.runner.regen_per_battle = 14, 0
        returned = []
        def normalize(_original):
            frame = self.runtime.capture("test-normalized-terminal")
            returned.append(frame)
            return frame
        result = self.run_route(terminal_home_normalizer=normalize,
            terminal_home_ap_reader=lambda frame: int(frame.frame[2, 2, 0]))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["terminal_home_frame"], str(returned[0].path))
        self.assertEqual(result["terminal_home_sha256"], returned[0].sha256)
        self.assertEqual(result["total_input_count"], self.runtime.input_count)

    def test_terminal_home_regeneration_at_backstop_exits_promptly_with_known_effect(self):
        self.runner.ap, self.runner.regen_per_battle = 27, 0
        original_capture, candidates = self.runtime.capture, []
        def capture(label):
            if label == "campaign-route-terminal-home":
                self.runner.ap += 1
            captured = original_capture(label)
            if label == "campaign-route-terminal-home":
                candidates.append(captured)
            return captured
        with patch.object(self.runtime, "capture", side_effect=capture):
            result = self.run_route(terminal_home_ap_reader=lambda frame: int(frame.frame[2, 2, 0]))
        self.assertNotEqual(result["status"], "completed")
        self.assertEqual(result["committed_ap_effect_count"], 1)
        self.assertEqual(result["progress"]["current_ap"], 14)
        self.assertEqual(result["progress"]["ap_regenerated"], 1)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(self.runner.inputs), 5)

    def test_changed_late_stage_cost_cannot_reach_policy_or_lineup(self):
        self.runner.on_capture = lambda count: setattr(self.runner, "phase", "wrong-stage") if count == 2 else None
        result = self.run_route()
        self.assertNotEqual(result["status"], "completed")
        self.assertEqual(self.stage_sources, [])
        self.assertEqual(self.runner.inputs, [])
        self.assertEqual(result["committed_ap_effect_count"], 0)

    def test_native_stage_boundary_reuses_policy_executor_and_temporary_action_journal(self):
        store, boundary = self.native_boundary()
        captures, proposals, immediate, issued, successors = {}, [], [], [], []
        original_capture = self.runtime.capture
        original_execute = live.SafeActionExecutor.execute
        original_issue = live.CentralPolicy.issue_capability

        def capture(label):
            captured = original_capture(label)
            captures[str(captured.path)] = captured
            return captured

        def issue(policy, request, *args, **kwargs):
            issued.append(request.observation)
            return original_issue(policy, request, *args, **kwargs)

        def execute(executor, request, *args, **kwargs):
            proposals.append(request.observation)
            recapture, post_observe = executor.recapture, executor.post_observe
            def before():
                observation = recapture()
                immediate.append(observation)
                return observation
            def after():
                for observation in post_observe():
                    successors.append(observation)
                    yield observation
            executor.recapture, executor.post_observe = before, after
            return original_execute(executor, request, *args, **kwargs)

        with patch.object(self.runtime, "measure_foreground_package", return_value="com.global.ztmslg"), \
                patch.object(self.runtime, "capture", side_effect=capture), \
                patch.object(live.CentralPolicy, "issue_capability", new=issue), \
                patch.object(live.SafeActionExecutor, "execute", new=execute):
            result = self.run_route(stage_challenge_boundary=boundary)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["committed_ap_effect_count"], 1)
        self.assertEqual((len(proposals), len(immediate), len(issued)), (1, 1, 1))
        for observation in (*proposals, *immediate, *issued, *successors):
            captured = captures[observation.evidence_refs[0]]
            self.assertEqual(observation.frame_sha256, captured.sha256)
            self.assertEqual(observation.capture_completed_monotonic, captured.captured_monotonic)
        self.assertNotEqual(proposals[0].evidence_refs, immediate[0].evidence_refs)
        self.assertLess(proposals[0].capture_completed_monotonic, immediate[0].capture_completed_monotonic)
        self.assertEqual(issued[0].frame_sha256, immediate[0].frame_sha256)
        self.assertEqual(issued[0].capture_completed_monotonic, immediate[0].capture_completed_monotonic)
        self.assertTrue(successors)
        for observation in successors:
            self.assertIsNone(observation.cost_type)
            self.assertIsNone(observation.cost_amount)
        actions = store.list_actions_for_task(live.CAMPAIGN_AP_FLOW_ID)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["final_status"], ActionStatus.CONFIRMED.value)
        commands = [row for row in self.events() if row.get("type") == "command"]
        lineup = next(row for row in commands if row["action"] == "CONFIRM_LINEUP")
        self.assertEqual(lineup["progress"]["ap_spent"], 0)

    def assert_immediate_stage_change_blocks(self, kind):
        _store, boundary = self.native_boundary()
        moved = False
        def changed(frame, stage, **kwargs):
            found = recognize(frame, stage, **kwargs)
            if moved and found.observation.screen is CampaignScreen.STAGE_DIALOG:
                if kind == "balance":
                    found = replace(found, observation=replace(found.observation, ap_current=119))
                else:
                    found = replace(found, targets=(("campaign-challenge-1-15-9", (139, 842, 385, 921)),))
            return found
        def enter(source, recognition, command, *, progress):
            nonlocal moved
            if kind == "cost":
                self.runner.phase = "wrong-stage"
            else:
                moved = True
            return boundary(source, recognition, command, progress=progress)
        with patch.object(self.runtime, "measure_foreground_package", return_value="com.global.ztmslg"), \
                patch.object(live, "recognize_campaign_frame", side_effect=changed):
            result = self.run_route(stage_challenge_boundary=enter)
        self.assertNotEqual(result["status"], "completed")
        self.assertEqual(result["total_input_count"], 0)
        self.assertEqual(result["stage_entry_transport_count"], 0)
        self.assertEqual(result["new_battle_count"], 0)
        self.assertEqual(result["committed_ap_effect_count"], 0)
        self.assertEqual(self.runner.inputs, [])

    def test_actual_immediate_stage_cost_change_prevents_transport(self):
        self.assert_immediate_stage_change_blocks("cost")

    def test_actual_immediate_stage_target_move_prevents_transport(self):
        self.assert_immediate_stage_change_blocks("target")

    def test_actual_immediate_ap_balance_change_prevents_transport(self):
        self.assert_immediate_stage_change_blocks("balance")

    def test_unrelated_initial_lineup_dispatches_nothing(self):
        self.runner.phase = "lineup"
        result = self.run_route()
        self.assertNotEqual(result["status"], "completed")
        self.assertEqual(self.runner.inputs, [])
        self.assertEqual(result["new_battle_count"], 0)

    def test_missing_accepted_policy_boundary_dispatches_nothing(self):
        result = self.run_route(stage_challenge_boundary=None)
        self.assertNotEqual(result["status"], "completed")
        self.assertEqual(self.runner.inputs, [])
        self.assertEqual(result["new_battle_count"], 0)
        self.assertEqual(result["committed_ap_effect_count"], 0)

    def test_once_only_lineup_continuation_ignores_new_screen_hash(self):
        self.runner.repeat_lineup = True
        result = self.run_route()
        self.assertNotEqual(result["status"], "completed")
        self.assertEqual(len(self.runner.inputs), 2)
        self.assertEqual(result["new_battle_count"], 1)
        self.assertEqual(result["committed_ap_effect_count"], 0)
        self.assertTrue(result["effect_reconciliation_required"])

    def test_stop_after_lineup_retains_pending_battle_and_actual_partial_count(self):
        self.runner.on_input = lambda count: setattr(self, "stopped", True) if count == 2 else None
        with self.assertRaises(live.CampaignApRunError) as raised:
            self.run_route()
        result = raised.exception.partial_result
        self.assertEqual(result["total_input_count"], 2)
        self.assertEqual(result["new_battle_count"], 1)
        self.assertEqual(result["committed_ap_effect_count"], 0)
        self.assertTrue(result["effect_reconciliation_required"])
        self.assertEqual(len(self.runner.inputs), 2)

    def test_transport_error_retains_attempted_input_and_unknown_battle(self):
        def fail(count):
            if count == 2:
                raise OSError("transport result unknown")
        self.runner.on_input = fail
        with self.assertRaises(live.CampaignApRunError) as raised:
            self.run_route()
        result = raised.exception.partial_result
        self.assertEqual(result["total_input_count"], self.runtime.input_count)
        self.assertEqual(result["total_input_count"], 2)
        self.assertTrue(result["effect_reconciliation_required"])
        self.assertEqual(result["committed_ap_effect_count"], 0)

    def test_policy_pretransport_exception_cannot_invent_a_stage_transport(self):
        def rejected_before_transport(_source, _recognition, _command, **_kwargs):
            raise RuntimeError("current dispatch fence rejected")
        with self.assertRaises(live.CampaignApRunError) as raised:
            self.run_route(stage_challenge_boundary=rejected_before_transport)
        result = raised.exception.partial_result
        self.assertEqual(result["total_input_count"], 0)
        self.assertEqual(result["stage_entry_transport_count"], 0)
        self.assertEqual(result["new_battle_count"], 0)
        self.assertEqual(self.runner.inputs, [])

    def test_malformed_stage_boundary_result_retains_one_input_without_lineup(self):
        def malformed(source, _recognition, command, **_kwargs):
            self.runtime.tap(source, target_identity=command.target_identity, target_roi=command.target_roi,
                             action_key="malformed-boundary-stage-entry", consequential=True)
            return {"status": "confirmed", "action_key": "malformed-boundary-stage-entry", "transport_calls": 1}
        result = self.run_route(stage_challenge_boundary=malformed)
        self.assertNotEqual(result["status"], "completed")
        self.assertEqual(result["total_input_count"], 1)
        self.assertEqual(result["stage_entry_transport_count"], 1)
        self.assertIsNone(result["entry_action_key"])
        self.assertEqual(result["committed_ap_effect_count"], 0)
        self.assertEqual(result["new_battle_count"], 0)
        self.assertEqual(len(self.runner.inputs), 1)
        self.assertEqual(json.loads((self.runtime.session / "result.json").read_text()), result)

    def test_home_atlas_uses_same_runtime_and_cumulative_input_cap(self):
        self.runner.phase = "home"
        self.runtime.max_inputs = 4
        seen = []
        def atlas(runtime, **_kwargs):
            seen.append(runtime)
            for index in range(2):
                source = runtime.capture(f"atlas-pan-{index}")
                runtime.swipe(source, start=(600, 700), end=(200, 700), action_key=f"atlas-pan-{index}")
            source = runtime.capture("atlas-entry")
            runtime.tap(source, target_identity="home.building.campaign", target_roi=(400, 500, 500, 600),
                        action_key="atlas-entry")
            return {"status": "opened", "navigation_input_count": 3}
        with patch.object(live, "run_verified_campaign_home_atlas_entry", side_effect=atlas):
            with self.assertRaises(live.CampaignApRunError) as raised:
                self.run_route()
        self.assertEqual(seen, [self.runtime])
        self.assertEqual(len(self.runner.inputs), 4)
        self.assertEqual(raised.exception.partial_result["total_input_count"], 4)
        self.assertEqual(raised.exception.partial_result["committed_ap_effect_count"], 0)

    def test_terminal_recovery_unwinds_one_existing_winner_without_new_battle(self):
        self.runner.ap = 106
        self.runner.phase = "winner"
        result = self.run_route(initial_ap=120, victory_home_only=True)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["new_battle_count"], 0)
        self.assertEqual(result["progress"]["completed_runs"], 1)
        self.assertEqual(result["progress"]["ap_spent"], 14)
        self.assertEqual(len(self.runner.inputs), 3)
        self.assertEqual(self.stage_sources, [])
        native = self.events("native-events.jsonl")
        targets = [row["target_identity"] for row in native if row.get("type") == "dispatch"]
        self.assertEqual(targets, ["campaign-victory-continue", "campaign-chapter-back", "campaign-exit-base"])

    def test_unexpected_battle_during_navigation_cannot_adopt_an_unrelated_run(self):
        self.runner.phase = "home"
        def atlas(_runtime, **_kwargs):
            self.runner.phase = "battle"
            return {"status": "opened", "navigation_input_count": 0}
        with patch.object(live, "run_verified_campaign_home_atlas_entry", side_effect=atlas):
            result = self.run_route()
        self.assertNotEqual(result["status"], "completed")
        self.assertEqual(result["new_battle_count"], 0)
        self.assertEqual(result["committed_ap_effect_count"], 0)
        self.assertEqual(self.stage_sources, [])
        self.assertEqual(self.runner.inputs, [])

    def test_unknown_frames_cannot_extend_the_original_battle_deadline(self):
        class Clock:
            now = 1000.0
            def monotonic(self):
                return self.now
            def sleep(self, duration):
                self.now += duration
        clock = Clock()
        self.config = CampaignAutoBattleConfig(target_stage=STAGE, ap_cost=14, ap_budget=14, max_runs=1,
                                               battle_poll_seconds=0.1, battle_timeout_seconds=1)
        battle_start = []
        def observed(frame, stage, **kwargs):
            phase = PHASES[int(frame[0, 0, 0])]
            if phase == "battle":
                battle_start.append(clock.now)
            if phase == "winner":
                return CampaignFrameRecognition(
                    CampaignRouteObservation(screen=CampaignScreen.UNKNOWN, recognized=False),
                    hashlib.sha256(frame.tobytes()).hexdigest(), (), {})
            return recognize(frame, stage, **kwargs)
        with patch.object(live, "recognize_campaign_frame", side_effect=observed):
            with self.assertRaises(live.CampaignApRunError) as raised:
                self.run_route(monotonic_clock=clock.monotonic, sleep=clock.sleep, recognition_timeout=0.3)
        self.assertEqual(len(battle_start), 1)
        self.assertGreaterEqual(clock.now, battle_start[0] + self.config.battle_timeout_seconds)
        self.assertLessEqual(clock.now, battle_start[0] + self.config.battle_timeout_seconds
                             + self.config.battle_poll_seconds + 0.0001)
        result = raised.exception.partial_result
        self.assertEqual(result["total_input_count"], 2)
        self.assertEqual(len(self.runner.inputs), 2)
        self.assertEqual(result["new_battle_count"], 1)
        self.assertEqual(result["committed_ap_effect_count"], 0)
        self.assertTrue(result["effect_reconciliation_required"])



if __name__ == "__main__":
    unittest.main()
