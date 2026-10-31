"""Ultimate daily service retains current Flee proof and the existing reset guard."""
from contextlib import ExitStack
from dataclasses import replace
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from automation_service import ultimate as service
from automation_service.recruitment import recruitment_reset
from automation_service.registry import CANONICAL_FLOW_REGISTRY
from safe_action_core import SafetyStore
from scripts import bluestacks_ultimate_challenge as native
from scripts import startup_recovery as startup
from scripts import startup_surface_recognition as surfaces
from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
from tasks import ultimate_challenge_daily as task
from tasks.scheduler_task_result import SchedulerIdentity


PHASES = ("home", "campaign", "ultimate", "lineup", "battle", "warning", "vip", "scarlett", "unknown")
ENTRY = (450, 300, 550, 400)
CHALLENGE = (300, 1100, 500, 1200)
FLEE = (470, 600, 700, 700)
VIP_CLOSE = (275, 780, 525, 830)


class UltimateDevice:
    def __init__(self):
        self.phase = "home"
        self.inputs = []
        self.captures = 0
        self.startup_successor = "home"
        self.startup_transport_error = False
        self.after_startup_input = None

    def capture_png(self):
        self.captures += 1
        frame = np.full((1280, 800, 3), PHASES.index(self.phase), np.uint8)
        frame[1, 1] = self.captures % 255
        success, png = cv2.imencode(".png", frame)
        assert success
        return png.tobytes()

    def dispatch_tap(self, point):
        self.inputs.append(("tap", point))
        if self.phase in {"vip", "scarlett"}:
            self.phase = self.startup_successor
            if self.after_startup_input:
                self.after_startup_input()
            if self.startup_transport_error:
                raise OSError("ambiguous native startup transport")
            return
        self.phase = {"home": "campaign", "campaign": "home" if point[1] > 900 else "ultimate",
                      "ultimate": "lineup", "lineup": "battle", "battle": "warning",
                      "warning": "ultimate"}[self.phase]

    def dispatch_back(self):
        self.inputs.append(("back",))
        self.phase = "campaign"


class UltimateServiceTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(dir=".local-orchestrator")))
        self.state_path = self.root / "reset.json"
        self.now = 1_800_000_000.0
        self.reset = recruitment_reset(self.now)
        self.identity = SchedulerIdentity("account", "server", self.reset, "ultimate_challenge_daily")
        self.device = UltimateDevice()
        self.runtimes = []
        self.stopped = False
        self.stop_after_flee = False
        self.stack.enter_context(patch.object(service, "RESET_STATE_PATH", self.state_path))
        self.action_store = self.stack.enter_context(patch("scripts.navigation_development_boundary.open_canonical_action_store",
                                                         side_effect=lambda: SafetyStore(self.root / "actions.sqlite3")))
        self.connect = self.stack.enter_context(patch.object(LocalBlueStacksRuntime, "connect", side_effect=self.runtime))
        self.stack.enter_context(patch.object(LocalBlueStacksRuntime, "measure_foreground_package",
                                             return_value="com.global.ztmslg"))
        self.stack.enter_context(patch.object(native, "_home_nav_terminal", side_effect=lambda frame: self.phase(frame) == "home"))
        self.normalize = self.stack.enter_context(patch.object(native, "_normalize_ultimate_home_before_campaign",
                                                              return_value=(True, {"zoom_input_count": 0})))
        self.door = self.stack.enter_context(patch.object(native, "run_verified_ultimate_challenge_campaign_door",
                                                         side_effect=self.campaign_door))
        self.stack.enter_context(patch.object(native, "_bind_ultimate_challenge_entry", side_effect=self.bind_entry))
        self.stack.enter_context(patch.object(native, "_bind_flee_warning_button",
                                             side_effect=lambda frame: FLEE if self.phase(frame) == "warning" else None))
        self.stack.enter_context(patch.object(native, "_recognize_ultimate_main",
                                             side_effect=lambda frame: CHALLENGE if self.phase(frame) == "ultimate" else None))
        self.daily = self.stack.enter_context(patch.object(native, "_run_daily_route", side_effect=self.daily_route))
        self.stack.enter_context(patch.object(startup, "recognize_reset_popup", side_effect=self.popup))
        self.stack.enter_context(patch.object(startup, "recognize_startup_surface", side_effect=self.startup_surface))
        self.runner = service.UltimateRunner(adb="FORBIDDEN", serial="emulator-5554", output_directory=self.root,
                                             utc_clock=lambda: self.now, post_input_delay=0)

    @staticmethod
    def phase(frame):
        return PHASES[int(frame[0, 0, 0])]

    def popup(self, frame):
        return {"recognized": self.phase(frame) == "vip", "popup_identity": "VIP_POINTS_GET_PTS",
                "target_identity": startup.VIP_RESET_TARGET, "target": VIP_CLOSE,
                "title_identity": True, "body_identity": True, "literal_close": True,
                "geometry_valid": True, "panel_present": True,
                "blocking_unknown_modal": self.phase(frame) == "unknown"}

    def startup_surface(self, frame, png=None):
        if self.phase(frame) != "scarlett":
            return {"recognized": False, "commercial_looking": self.phase(frame) == "unknown"}
        if png is None:
            png = cv2.imencode(".png", frame)[1].tobytes()
        return {
            "recognized": True, "surface_identity": surfaces.SCARLETT_THREE_DAY_PACK,
            "surface_kind": surfaces.SCARLETT_SURFACE_KIND, "runtime_profile_id": service.PROFILE_ID,
            "width": 800, "height": 1280, "title_text": "Scarlett 3-Day Pack", "title_identity": True,
            "safe_exit_target_identity": surfaces.SCARLETT_SAFE_BACK_TARGET_IDENTITY,
            "safe_exit_roi": surfaces.SCARLETT_SAFE_BACK_ROI,
            "forbidden_purchase_rois": surfaces.SCARLETT_FORBIDDEN_PURCHASE_ROIS,
            "purchase_exclusion_verified": True, "expected_successor": surfaces.SCARLETT_EXPECTED_SUCCESSOR,
            "max_inputs": 1, "target_count": 1, "page_context_verified": True,
            "measured_back_roi": (50, 10, 140, 50), "frame_sha256": hashlib.sha256(png).hexdigest(),
            "semantic_evidence": ("title:Scarlett 3-Day Pack", "full_page_real_money_promotion",
                                  "visible_in_game_back_upper_left", "purchase_regions_excluded",
                                  "current_offer_benefits_and_three_day_rows", "current_first_topup_notice"),
        }

    def runtime(self, **_kwargs):
        runtime = LocalBlueStacksRuntime(self.device, self.root / f"native-{len(self.runtimes)}", execute=True)
        self.runtimes.append(runtime)
        return runtime

    def checkpoint(self):
        if self.stopped:
            raise RuntimeError("STOP_REQUESTED")

    def campaign_door(self, runtime, **_kwargs):
        source = runtime.capture("home-door-before")
        runtime.tap(source, target_identity="home.building.campaign", target_roi=(400, 500, 500, 600),
                    action_key="home-door")
        return {"status": "opened"}

    def bind_entry(self, frame, *, reset_identity):
        return task.UltimateChallengeEntryObservation(
            True, True, task.ULTIMATE_CHALLENGE_ENTRY_IDENTITY, ENTRY, False,
            reset_identity, native.frame_sha256(frame))

    def daily_route(self, *, runtime, starting_state, **_kwargs):
        self.assertEqual(starting_state, "campaign_entry")
        source = runtime.capture("entry-before")
        runtime.tap(source, target_identity="ultimate-challenge-entry", target_roi=ENTRY, action_key="entry")
        actions = []
        source = runtime.capture("challenge-before")
        for action, roi in (("tap_challenge", CHALLENGE), ("tap_lineup_challenge", CHALLENGE),
                            ("tap_upper_right_exit", (700, 20, 750, 75)), ("tap_flee", FLEE)):
            key = f"current-{action}"
            runtime.tap(source, target_identity=action, target_roi=roi, action_key=key, consequential=True)
            post = runtime.capture(f"{action}-post")
            runtime.reconcile(key, "confirmed", post, "current typed successor")
            actions.append({"action": action, "target_roi": roi, "before_sha256": source.sha256,
                            "post_sha256": post.sha256})
            source = post
        if self.stop_after_flee:
            self.stopped = True
            runtime.capture("blocked-home-capture")
        runtime.back(source, action_key="return-campaign")
        source = runtime.capture("campaign-return")
        runtime.tap(source, target_identity="campaign-exit-base", target_roi=(700, 950, 790, 1050),
                    action_key="return-home")
        return task.TERMINAL_COMPLETE_FOR_RESET, {"completed_actions": actions, "reason": "Flee and Home verified"}

    def write_state(self, state):
        task.save_reset_window_state(self.state_path, state)
        return self.state_path.read_bytes()

    def completed(self, reset):
        return task.record_verified_home_success(task.empty_reset_window_state(), reset_identity=reset,
                                                  success_at=f"{reset.removeprefix('game-day-')}T00:00:00+00:00")

    def test_construction_is_device_free_and_handler_has_one_bounded_action(self):
        self.connect.assert_not_called()
        entry = next(item for item in CANONICAL_FLOW_REGISTRY if item.product_id == "ultimate_challenge_daily")
        handler = service.UltimateExecutionHandler(entry.registration, lambda *_args: None)
        self.assertEqual((handler.max_inputs, handler.max_actions), (16, 1))
        self.assertFalse(handler.selection_only)

    def test_same_reset_completion_only_observes_current_home_and_preserves_state(self):
        before = self.write_state(self.completed(self.reset))
        with patch.object(startup, "recover_contextual_startup_overlay",
                          wraps=startup.recover_contextual_startup_overlay) as recover:
            result = self.runner(self.identity, None, self.checkpoint)
        recover.assert_not_called()
        self.assertEqual(result["status"], "already_completed")
        self.assertEqual(result["startup_navigation_count"], 0)
        self.assertEqual(result["total_input_count"], 0)
        self.assertEqual(result["ultimate_dispatch_count"], 0)
        self.assertEqual(result["flee_transport_calls"], 0)
        self.assertEqual(result["committed_action_count"], 0)
        self.assertEqual(self.device.captures, 1)
        self.assertEqual(self.state_path.read_bytes(), before)
        self.normalize.assert_not_called()
        self.action_store.assert_not_called()
        self.door.assert_not_called()
        self.daily.assert_not_called()

    def test_prior_completed_day_allows_one_current_flee_home_then_idempotent_repeat(self):
        self.write_state(self.completed(recruitment_reset(self.now - 86400)))
        result = self.runner(self.identity, None, self.checkpoint)
        self.assertEqual(result["status"], "complete_for_reset")
        self.assertEqual(result["ultimate_dispatch_count"], 1)
        self.assertEqual(result["flee_transport_calls"], 1)
        self.assertEqual(result["committed_action_count"], 1)
        self.assertEqual(result["total_input_count"], len(self.device.inputs))
        self.assertTrue(result["terminal_home_verified"])
        state = task.load_reset_window_state(self.state_path)
        self.assertEqual(state.last_success_reset_identity, self.reset)
        self.assertEqual(state.completion_state, task.COMPLETION_COMPLETED)
        before, inputs = self.state_path.read_bytes(), len(self.device.inputs)
        repeated = self.runner(self.identity, None, self.checkpoint)
        self.assertEqual(repeated["status"], "already_completed")
        self.assertEqual(repeated["total_input_count"], 0)
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertEqual(len(self.device.inputs), inputs)
        self.assertEqual(self.daily.call_count, 1)

    def test_unknown_and_pending_current_or_previous_reset_never_start_another_route(self):
        unknown = replace(task.empty_reset_window_state(), reset_identity=self.reset,
                          completion_state=task.COMPLETION_UNKNOWN)
        states = [unknown, replace(task.empty_reset_window_state(),
                                   reset_identity=recruitment_reset(self.now + 86400))] + [task.record_pending_home(
            task.empty_reset_window_state(), reset_identity=reset,
            session_directory=str(self.root / "retained-pending"), result_sha256="a" * 64)
            for reset in (self.reset, recruitment_reset(self.now - 86400))]
        for state in states:
            with self.subTest(state=state):
                before = self.write_state(state)
                with self.assertRaises(service.UltimateRunnerError) as raised:
                    self.runner(self.identity, None, self.checkpoint)
                self.assertEqual(raised.exception.partial_result["total_input_count"], 0)
                self.assertEqual(self.state_path.read_bytes(), before)
        self.assertEqual(self.device.inputs, [])
        self.normalize.assert_not_called()
        self.door.assert_not_called()
        self.daily.assert_not_called()

    def test_initial_lineup_or_battle_is_not_adopted(self):
        for phase in ("lineup", "battle"):
            with self.subTest(phase=phase):
                self.device.phase = phase
                with self.assertRaises(service.UltimateRunnerError) as raised:
                    self.runner(self.identity, None, self.checkpoint)
                self.assertEqual(raised.exception.partial_result["total_input_count"], 0)
        self.assertEqual(self.device.inputs, [])
        self.daily.assert_not_called()

    def test_proven_flee_stop_before_home_persists_current_proof_and_prevents_repeat(self):
        self.stop_after_flee = True
        with self.assertRaises(service.UltimateRunnerError) as raised:
            self.runner(self.identity, None, self.checkpoint)
        result = raised.exception.partial_result
        self.assertIn("STOP_REQUESTED", result["reason"])
        self.assertEqual(result["total_input_count"], 6)
        self.assertEqual(result["ultimate_dispatch_count"], 1)
        self.assertEqual(result["flee_transport_calls"], 1)
        self.assertEqual(result["committed_action_count"], 0)
        pending = task.load_reset_window_state(self.state_path)
        self.assertEqual(pending.completion_state, task.COMPLETION_UNKNOWN)
        proof = Path(pending.pending_home_session) / "result.json"
        self.assertEqual(hashlib.sha256(proof.read_bytes()).hexdigest(), pending.pending_home_result_sha256)
        from scripts import flow_delivery_ultimate_challenge_bluestacks as delivery
        with patch.object(delivery, "is_clean_home_frame", side_effect=lambda frame: self.phase(frame) == "home"):
            self.assertEqual(delivery._verified_home_evidence(proof.parent, result), (False, None))
        before, inputs = self.state_path.read_bytes(), len(self.device.inputs)
        self.stopped = False
        with self.assertRaises(service.UltimateRunnerError):
            self.runner(self.identity, None, self.checkpoint)
        self.assertEqual(self.daily.call_count, 1)
        self.assertEqual(len(self.device.inputs), inputs)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_result_write_failure_preserves_completed_guard_and_prevents_another_flee(self):
        with patch.object(self.runner, "_write_result", side_effect=OSError("result write failed")):
            with self.assertRaises(service.UltimateRunnerError) as raised:
                self.runner(self.identity, None, self.checkpoint)
        result = raised.exception.partial_result
        self.assertEqual(result["total_input_count"], 8)
        self.assertEqual(result["ultimate_dispatch_count"], 1)
        self.assertEqual(result["flee_transport_calls"], 1)
        state = task.load_reset_window_state(self.state_path)
        self.assertEqual(state.completion_state, task.COMPLETION_COMPLETED)
        self.assertEqual(state.last_success_reset_identity, self.reset)
        self.assertIsNone(state.pending_home_session)
        before, inputs = self.state_path.read_bytes(), len(self.device.inputs)
        repeated = self.runner(self.identity, None, self.checkpoint)
        self.assertEqual(repeated["status"], "already_completed")
        self.assertEqual(repeated["total_input_count"], 0)
        self.assertEqual(self.daily.call_count, 1)
        self.assertEqual(len(self.device.inputs), inputs)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_result_normalization_requires_current_identity_flee_home_and_next_utc_reset(self):
        result = self.runner(self.identity, None, self.checkpoint)
        midnight = (self.now // 86400 + 1) * 86400
        self.assertEqual(service.ultimate_next_due(result, self.identity, self.now - 1), midnight)
        for changes in ({"time_basis": "monotonic"}, {"terminal_home_verified": False},
                        {"flee_transport_calls": 2}, {"committed_action_count": 0},
                        {"next_eligible_at": self.now + 900}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                service.ultimate_next_due(dict(result, **changes), self.identity, self.now - 1)
        with self.assertRaises(ValueError):
            service.ultimate_next_due(result, replace(self.identity, task_id="another-task"), self.now - 1)

    def test_known_startup_vip_or_scarlett_only_adds_one_navigation_to_already_completed(self):
        for phase, target, roi in (("vip", startup.VIP_RESET_TARGET, VIP_CLOSE),
                                   ("scarlett", surfaces.SCARLETT_SAFE_BACK_TARGET_IDENTITY,
                                    surfaces.SCARLETT_SAFE_BACK_ROI)):
            with self.subTest(phase=phase):
                before = self.write_state(self.completed(self.reset))
                self.device.phase = phase
                previous_inputs = len(self.device.inputs)
                previous_runtimes = len(self.runtimes)
                with patch.object(startup, "recover_contextual_startup_overlay",
                                  wraps=startup.recover_contextual_startup_overlay) as recover:
                    result = self.runner(self.identity, None, self.checkpoint)
                recover.assert_called_once()
                self.assertEqual(result["status"], "already_completed")
                self.assertEqual(result["startup_navigation_count"], 1)
                self.assertEqual((result["total_input_count"], result["ultimate_dispatch_count"],
                                  result["flee_transport_calls"], result["committed_action_count"]), (1, 0, 0, 0))
                self.assertEqual(len(self.device.inputs) - previous_inputs, 1)
                self.assertEqual(len(self.runtimes) - previous_runtimes, 1)
                runtime = self.runtimes[-1]
                rows = [json.loads(line) for line in runtime.events.read_text().splitlines()]
                dispatch = [row for row in rows if row["type"] == "dispatch"]
                self.assertEqual(len(dispatch), 1)
                self.assertEqual(dispatch[0]["target_identity"], target)
                self.assertEqual(tuple(dispatch[0]["target_roi"]), roi)
                confirmed = [row for row in rows if row["type"] == "reconcile" and row["status"] == "confirmed"]
                self.assertEqual([row["action_key"] for row in confirmed], [dispatch[0]["action_key"]])
                proof = result["startup_navigation_proof"]
                self.assertEqual(proof["runtime_session"], str(runtime.session.resolve()))
                self.assertEqual(proof["target_identity"], target)
                self.assertEqual(tuple(proof["target_roi"]), roi)
                self.assertEqual(proof["action_key"], dispatch[0]["action_key"])
                self.assertTrue(proof["helper"]["resume_ready"])
                self.assertEqual(proof["helper"]["input_count"], 1)
                captures = [proof[role] for role in ("source", "immediate_before", "settled", "home")]
                times = [capture["captured_monotonic"] for capture in captures]
                self.assertTrue(all(before < after for before, after in zip(times, times[1:])))
                for capture in captures:
                    path = runtime.session / capture["frame_path"]
                    path.resolve().relative_to(runtime.session.resolve())
                    png = path.read_bytes()
                    self.assertEqual(hashlib.sha256(png).hexdigest(), capture["frame_sha256"])
                    self.assertEqual(cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR).shape, (1280, 800, 3))
                self.assertEqual(len({capture["frame_path"] for capture in captures}), 4)
                self.assertEqual(result["initial_source_frame_sha256"], proof["source"]["frame_sha256"])
                self.assertEqual(result["initial_home_frame_sha256"], proof["home"]["frame_sha256"])
                self.assertEqual(result["home_frame_sha256"], proof["home"]["frame_sha256"])
                self.assertTrue(result["terminal_home_verified"])
                self.assertEqual(service.ultimate_next_due(result, self.identity, self.now - 1),
                                 (self.now // 86400 + 1) * 86400)
                self.assertEqual(self.state_path.read_bytes(), before)
        self.action_store.assert_not_called()
        self.normalize.assert_not_called()
        self.door.assert_not_called()
        self.daily.assert_not_called()

    def test_fresh_reset_startup_recovery_keeps_one_daily_flee_and_nine_actual_inputs(self):
        self.write_state(self.completed(recruitment_reset(self.now - 86400)))
        self.device.phase = "vip"
        with patch.object(startup, "recover_contextual_startup_overlay",
                          wraps=startup.recover_contextual_startup_overlay) as recover:
            result = self.runner(self.identity, None, self.checkpoint)
        recover.assert_called_once()
        self.assertEqual(result["status"], "complete_for_reset")
        self.assertEqual(result["startup_navigation_count"], 1)
        self.assertEqual(result["total_input_count"], 9)
        self.assertEqual(len(self.device.inputs), 9)
        self.assertEqual((result["ultimate_dispatch_count"], result["flee_transport_calls"],
                          result["committed_action_count"]), (1, 1, 1))
        self.assertEqual(service.ultimate_next_due(result, self.identity, self.now - 1),
                         (self.now // 86400 + 1) * 86400)
        with self.assertRaises(ValueError):
            service.ultimate_next_due(dict(result, total_input_count=1, input_count=1),
                                      self.identity, self.now - 1)
        self.assertEqual(self.action_store.call_count, 1)
        self.assertEqual(self.daily.call_count, 1)

    def test_unknown_startup_is_zero_input_and_does_not_change_completed_reset(self):
        before = self.write_state(self.completed(self.reset))
        self.device.phase = "unknown"
        with self.assertRaises(service.UltimateRunnerError) as caught:
            self.runner(self.identity, None, self.checkpoint)
        self.assertEqual(caught.exception.partial_result["total_input_count"], 0)
        self.assertEqual(caught.exception.partial_result["startup_navigation_count"], 0)
        self.assertFalse(self.device.inputs)
        self.assertEqual(self.state_path.read_bytes(), before)
        self.action_store.assert_not_called()
        self.daily.assert_not_called()

    def test_startup_next_due_rebuilds_current_proof_and_rejects_forged_or_missing_evidence(self):
        before = self.write_state(self.completed(self.reset))
        self.device.phase = "vip"
        result = self.runner(self.identity, None, self.checkpoint)
        for mutation in ("missing_proof", "missing_count", "extra_count", "wrong_target", "wrong_roi",
                         "cross_frame", "replayed_source", "forged_time", "wrong_session", "helper_not_ready",
                         "wrong_home_alias_hash", "wrong_home_alias_path", "home_alias_not_recognized"):
            candidate = copy.deepcopy(result)
            proof = candidate["startup_navigation_proof"]
            if mutation == "missing_proof":
                candidate.pop("startup_navigation_proof")
            elif mutation == "missing_count":
                candidate.pop("startup_navigation_count")
            elif mutation == "extra_count":
                candidate["startup_navigation_count"] = 2
            elif mutation == "wrong_target":
                proof["target_identity"] = "another-game-control"
            elif mutation == "wrong_roi":
                proof["target_roi"] = [100, 100, 200, 200]
            elif mutation == "cross_frame":
                proof["immediate_before"]["frame_sha256"] = proof["source"]["frame_sha256"]
            elif mutation == "replayed_source":
                proof["immediate_before"]["frame_path"] = proof["source"]["frame_path"]
            elif mutation == "forged_time":
                proof["home"]["captured_monotonic"] = proof["settled"]["captured_monotonic"]
            elif mutation == "wrong_session":
                proof["runtime_session"] = str(self.root / "another-session")
            elif mutation == "helper_not_ready":
                proof["helper"]["resume_ready"] = False
            elif mutation == "wrong_home_alias_hash":
                candidate["home_frame_sha256"] = "f" * 64
            elif mutation == "wrong_home_alias_path":
                candidate["home_frame"] = proof["source"]["frame_path"]
            else:
                candidate["home_nav_recognized"] = False
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                service.ultimate_next_due(candidate, self.identity, self.now - 1)
        runtime = self.runtimes[-1]
        source_path = runtime.session / result["startup_navigation_proof"]["source"]["frame_path"]
        source_path.unlink()  # Fault only in this test's just-created current proof.
        with self.assertRaises((ValueError, OSError)):
            service.ultimate_next_due(result, self.identity, self.now - 1)
        self.assertEqual(self.state_path.read_bytes(), before)
        self.action_store.assert_not_called()
        self.daily.assert_not_called()

    def test_startup_unknown_post_stop_or_transport_error_preserves_one_input_without_daily_retry(self):
        for failure in ("unknown_post", "stop", "ambiguous_transport"):
            with self.subTest(failure=failure):
                before = self.write_state(self.completed(self.reset))
                self.device.phase = "vip"
                self.device.startup_successor = "unknown" if failure == "unknown_post" else "home"
                self.device.startup_transport_error = failure == "ambiguous_transport"
                self.device.after_startup_input = (lambda: setattr(self, "stopped", True)) if failure == "stop" else None
                previous_inputs = len(self.device.inputs)
                with self.assertRaises(service.UltimateRunnerError) as caught:
                    self.runner(self.identity, None, self.checkpoint)
                partial = caught.exception.partial_result
                self.assertEqual(partial["total_input_count"], 1)
                self.assertEqual(partial["startup_navigation_count"], 1)
                self.assertEqual((partial["ultimate_dispatch_count"], partial["flee_transport_calls"],
                                  partial["committed_action_count"]), (0, 0, 0))
                self.assertEqual(len(self.device.inputs) - previous_inputs, 1)
                self.assertTrue(partial["identical_retry_denied"])
                self.assertEqual(self.state_path.read_bytes(), before)
                self.stopped = False
        self.action_store.assert_not_called()
        self.daily.assert_not_called()
        self.door.assert_not_called()

    def test_current_startup_ledger_or_source_png_fault_cannot_become_already_completed(self):
        real_recover = startup.recover_contextual_startup_overlay
        for fault in ("missing_ledger", "malformed_ledger", "missing_dispatch_png", "replayed_target",
                      "extra_unrelated_dispatch", "extra_flee_dispatch"):
            with self.subTest(fault=fault):
                before = self.write_state(self.completed(self.reset))
                self.device.phase = "vip"

                def recover_with_fault(runtime, captured, **kwargs):
                    recovered = real_recover(runtime, captured, **kwargs)
                    rows = [json.loads(line) for line in runtime.events.read_text().splitlines()]
                    if fault == "missing_ledger":
                        runtime.events.unlink()
                    elif fault == "malformed_ledger":
                        runtime.events.write_text("malformed current test event\n")
                    elif fault == "missing_dispatch_png":
                        dispatch = next(row for row in rows if row["type"] == "dispatch")
                        source = next(row for row in rows if row["type"] == "capture"
                                      and row["sha256"] == dispatch["source_sha256"])
                        Path(source["path"]).unlink()
                    elif fault == "replayed_target":
                        next(row for row in rows if row["type"] == "dispatch")["target_identity"] = "another-game-control"
                        runtime.events.write_text("".join(json.dumps(row) + "\n" for row in rows))
                    else:
                        dispatch = next(row for row in rows if row["type"] == "dispatch")
                        extra = {key: value for key, value in dispatch.items() if key not in {"type", "timestamp"}}
                        extra.update(action_key="unexpected-before-current-home",
                                     target_identity="tap_flee" if fault == "extra_flee_dispatch" else "another-game-control")
                        runtime._event("dispatch", extra)
                    return recovered

                with patch.object(startup, "recover_contextual_startup_overlay", side_effect=recover_with_fault):
                    with self.assertRaises(service.UltimateRunnerError) as caught:
                        self.runner(self.identity, None, self.checkpoint)
                self.assertEqual(caught.exception.partial_result["total_input_count"], 1)
                self.assertEqual(caught.exception.partial_result["startup_navigation_count"], 1)
                self.assertEqual(caught.exception.partial_result["ultimate_dispatch_count"], 0)
                self.assertEqual(self.state_path.read_bytes(), before)
        self.action_store.assert_not_called()
        self.daily.assert_not_called()

    def test_already_completed_next_due_rejects_any_later_unaccounted_native_dispatch(self):
        for initial in ("home", "vip"):
            for target in ("another-game-control", "tap_flee"):
                with self.subTest(initial=initial, target=target):
                    before = self.write_state(self.completed(self.reset))
                    self.device.phase = initial
                    result = self.runner(self.identity, None, self.checkpoint)
                    self.assertEqual(result["status"], "already_completed")
                    runtime = self.runtimes[-1]
                    actual_inputs = runtime.input_count
                    # Current test-ledger fault only: no device call, frame
                    # mutation, input counter update or reset-state write.
                    runtime._event("dispatch", {
                        "action_key": "unexpected-after-current-home", "target_identity": target,
                        "target_roi": list(FLEE), "source_sha256": result["home_frame_sha256"],
                        "action_class": "navigation", "consequential": False, "execute": True,
                    })
                    with self.assertRaises(ValueError):
                        service.ultimate_next_due(result, self.identity, self.now - 1)
                    self.assertEqual(runtime.input_count, actual_inputs)
                    self.assertEqual(self.state_path.read_bytes(), before)
        self.action_store.assert_not_called()
        self.daily.assert_not_called()


if __name__ == "__main__":
    unittest.main()
