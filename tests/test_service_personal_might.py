"""Device-forbidden Personal Might service execution through the real daily boundary."""
from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from automation_service import personal_might as service
from automation_service.recruitment import recruitment_reset
from automation_service.registry import CANONICAL_FLOW_REGISTRY, RegisteredDispatchSnapshot
from safe_action_core import SafetyStore
from scripts import navigation_development_boundary as boundary
from scripts import personal_might_praise_bluestacks as route
from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
from scripts.startup_recovery import ContextualPopupRecoveryResult
from tasks.runtime_identity import derive_resource_runtime_identity, resource_fixed_runtime_binding
from tasks.scheduler_task_result import SchedulerIdentity


PHASES = ("home", "menu", "rankings", "gold", "gray", "vip", "scarlett", "unknown")
START = datetime(2026, 10, 29, 10, tzinfo=timezone.utc).timestamp()
ROI = (700, 200, 760, 260)


class PersonalDevice:
    def __init__(self):
        self.phase, self.captures, self.inputs = "home", 0, []
        self.after_praise = None
        self.praise_unknown = False
        self.startup_sequence = []

    def capture_png(self):
        self.captures += 1
        image = np.full((1280, 800, 3), PHASES.index(self.phase), np.uint8)
        image[0, 0] = self.captures % 255
        return cv2.imencode(".png", image)[1].tobytes()

    def dispatch_tap(self, point):
        self.inputs.append((self.phase, point))
        if self.phase in {"vip", "scarlett"}:
            self.phase = self.startup_sequence.pop(0) if self.startup_sequence else "home"
            return
        if self.phase == "gold":
            self.phase = "gold" if self.praise_unknown else "gray"
            if self.after_praise:
                self.after_praise()
        else:
            self.phase = {"home": "menu", "menu": "rankings", "rankings": "gold",
                          "gray": "rankings"}[self.phase]
            if self.phase == "gold" and any(item[0] == "gray" for item in self.inputs):
                self.phase = "home"


class ServicePersonalMightTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).absolute()
        self.stack.enter_context(patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", self.root / "owner.sqlite3"))
        self.owner = boundary.RuntimeInputLock(owner="serve", invocation_id="current-run").acquire()
        self.addCleanup(self.owner.release)
        self.now, self.stopped, self.checkpoints = START, False, 0
        self.identity = SchedulerIdentity("logical-account", "logical-server", recruitment_reset(START), service.PRODUCT_ID)
        self.device, self.runtimes = PersonalDevice(), []
        self.db = self.root / "actions.sqlite3"
        self.stack.enter_context(patch.object(boundary, "open_canonical_action_store", side_effect=lambda: SafetyStore(self.db)))
        self.connect = self.stack.enter_context(patch.object(LocalBlueStacksRuntime, "connect", side_effect=self.connect_runtime))
        self.stack.enter_context(patch("scripts.bluestacks_native_runtime.ADBRunner", side_effect=AssertionError("device forbidden")))
        self.stack.enter_context(patch.object(LocalBlueStacksRuntime, "measure_foreground_package", return_value="com.global.ztmslg"))
        self.stack.enter_context(patch("scripts.startup_normalization.is_clean_home_frame", side_effect=lambda frame: self.phase(frame) == "home"))
        self.stack.enter_context(patch.object(route, "is_clean_home_frame", side_effect=lambda frame: self.phase(frame) == "home"))
        self.stack.enter_context(patch.object(route.vision, "more_menu_present", side_effect=lambda frame, **kw: self.phase(frame) == "menu"))
        self.stack.enter_context(patch.object(route.vision, "recognize_more_menu", side_effect=lambda frame, **kw: self.phase(frame) == "menu"))
        self.stack.enter_context(patch.object(route.vision, "is_rankings", side_effect=lambda frame, **kw: self.phase(frame) == "rankings"))
        self.stack.enter_context(patch.object(route.vision, "is_personal_might", side_effect=lambda frame, **kw: self.phase(frame) in {"gold", "gray"}))
        self.stack.enter_context(patch.object(route.vision, "personal_might_praised", side_effect=lambda frame, **kw: self.phase(frame) == "gray"))
        for method, phase, target in (
                ("bind_home_more", "home", route.vision.MORE_TARGET),
                ("bind_more_rankings", "menu", route.vision.RANKINGS_TARGET),
                ("bind_personal_might_check", "rankings", route.vision.CHECK_TARGET),
                ("bind_personal_might_praise", "gold", service.TARGET_IDENTITY)):
            self.stack.enter_context(patch.object(route.vision, method,
                side_effect=lambda frame, _phase=phase, _target=target, **kw: self.target(frame, _phase, _target)))
        self.stack.enter_context(patch.object(route.vision, "bind_back", side_effect=lambda frame, personal_page, **kw:
            self.target(frame, "gray" if personal_page else "rankings", "personal-might-back" if personal_page else "leaderboard-back")))
        self.startup = self.stack.enter_context(patch("scripts.startup_recovery.recover_contextual_startup_overlay",
            side_effect=lambda runtime, captured, **kwargs: ContextualPopupRecoveryResult(captured,
                False, True, bool(kwargs["recognize_successor"](captured)), 0, "exact_startup_overlay_absent")))
        self.runner = service.PersonalMightRunner(adb="unused", serial="emulator-5554",
            output_directory=self.root / "runs", utc_clock=lambda: self.now, settle_seconds=0)

    @staticmethod
    def phase(frame):
        return PHASES[int(frame[10, 10, 0])]

    def target(self, frame, phase, target):
        return SimpleNamespace(target_roi=ROI, target_identity=target) if self.phase(frame) == phase else None

    def checkpoint(self):
        self.checkpoints += 1
        self.owner.assert_held("serve", "current-run")
        if self.stopped:
            raise RuntimeError("stop or generation changed")

    def connect_runtime(self, **kwargs):
        runtime = LocalBlueStacksRuntime(self.device, kwargs["output_directory"] / "native", execute=True)
        self.runtimes.append(runtime)
        return runtime

    def run_route(self):
        return self.runner(self.identity, None, self.checkpoint, runtime_input_lock=self.owner)

    def test_construction_and_invalid_task_day_backend_or_owner_cannot_connect(self):
        self.assertFalse((self.root / "runs").exists())
        cases = (replace(self.identity, task_id="nova_praise"), replace(self.identity, reset_id="game-day-2026-10-28"))
        for identity in cases:
            with self.subTest(identity=identity), self.assertRaises(service.PersonalMightRunnerError) as caught:
                self.runner(identity, None, self.checkpoint, runtime_input_lock=self.owner)
            self.assertEqual(caught.exception.partial_result["total_input_count"], 0)
        self.runner.serial = "emulator-5556"
        with self.assertRaises(service.PersonalMightRunnerError):
            self.run_route()
        self.runner.serial = "emulator-5554"
        self.owner.release()
        with self.assertRaises(service.PersonalMightRunnerError):
            self.runner(self.identity, None, lambda: None, runtime_input_lock=self.owner)
        self.connect.assert_not_called()

    def test_real_boundary_one_praise_then_current_day_gray_repeat_no_praise(self):
        with patch.object(boundary.RuntimeInputLock, "acquire", side_effect=AssertionError("no nested owner")), patch.object(boundary.RuntimeInputLock, "release", side_effect=AssertionError("borrowed owner retained")):
            first = self.run_route()
            self.assertEqual((first["status"], first["total_input_count"], first["praise_transport_calls"]), ("complete_for_reset", 6, 1))
            self.assertTrue(first["terminal_home_verified"])
            backend = derive_resource_runtime_identity(resource_fixed_runtime_binding(), datetime.fromtimestamp(START, timezone.utc))
            self.assertEqual(first["action_key"], service._key(backend))
            self.assertNotEqual(first["backend_identity"]["account_id"], self.identity.account_id)
            self.assertEqual(service.personal_might_next_due(first, self.identity, START), START + 14 * 3600)
            store = SafetyStore(self.db)
            old_id = store.get_action_by_key(first["action_key"])["action_id"]
            self.assertEqual(store.get_action(old_id)["final_status"], "confirmed")
            store.close()
            self.device = PersonalDevice()
            ordinary = self.device.dispatch_tap
            def already_praised(point):
                ordinary(point)
                if self.device.phase == "gold":
                    self.device.phase = "gray"
            self.device.dispatch_tap = already_praised
            second = self.run_route()
            self.assertEqual((second["status"], second["total_input_count"], second["praise_transport_calls"]), ("already_complete", 5, 0))
            self.assertEqual(second["action_id"], old_id)
            self.assertTrue(second["no_work"])
            self.assertEqual(service.personal_might_next_due(second, self.identity, START), START + 14 * 3600)
            self.assertTrue(self.owner.held)
        self.assertGreater(self.checkpoints, sum(item.ordinal + item.input_count for item in self.runtimes))
        for result in (first, second):
            root = Path(result["session_directory"])
            for field in ("source_frame", "praise_result_frame", "terminal_home_frame"):
                self.assertTrue((root / result[field]["frame_path"]).is_file())
            saved = json.loads((root / "personal-might-result.json").read_text())
            self.assertEqual(saved["praise_transport_calls"], result["praise_transport_calls"])

    def test_recognized_open_more_resumes_confirmed_day_without_repeating_praise(self):
        first = self.run_route()
        self.device = PersonalDevice()
        self.device.phase = "menu"
        ordinary = self.device.dispatch_tap
        def already_praised(point):
            ordinary(point)
            if self.device.phase == "gold":
                self.device.phase = "gray"
        self.device.dispatch_tap = already_praised
        home = lambda frame: self.phase(frame) in {"home", "menu"}
        with patch("scripts.startup_normalization.is_clean_home_frame", side_effect=home), patch.object(route, "is_clean_home_frame", side_effect=home):
            second = self.run_route()
        self.assertEqual((second["status"], second["total_input_count"], second["praise_transport_calls"]), ("already_complete", 4, 0))
        self.assertEqual(first["action_id"], second["action_id"])
        self.assertTrue(second["terminal_home_verified"])

    def test_partial_more_menu_stops_before_any_navigation_or_praise(self):
        self.device.phase = "menu"
        with patch("scripts.startup_normalization.is_clean_home_frame", return_value=True), patch.object(route.vision, "recognize_more_menu", return_value=False):
            with self.assertRaises(service.PersonalMightRunnerError) as caught:
                self.run_route()
        self.assertEqual(caught.exception.partial_result["total_input_count"], 0)
        self.assertEqual(caught.exception.partial_result["praise_transport_calls"], 0)
        self.assertEqual(self.device.inputs, [])

    def test_unknown_effect_retains_one_praise_and_blocks_next_attempt_before_device(self):
        self.device.praise_unknown = True
        with self.assertRaises(service.PersonalMightRunnerError) as caught:
            self.run_route()
        partial = caught.exception.partial_result
        self.assertEqual((partial["total_input_count"], partial["praise_transport_calls"]), (4, 1))
        self.assertTrue(partial["effect_reconciliation_required"])
        self.assertTrue(partial["identical_retry_denied"])
        self.assertTrue(partial["accounting_verified"])
        self.assertEqual(len(self.device.inputs), 4)
        count = self.connect.call_count
        with self.assertRaises(service.PersonalMightRunnerError) as blocked:
            self.run_route()
        self.assertEqual(blocked.exception.partial_result["total_input_count"], 0)
        self.assertEqual(self.connect.call_count, count)

    def test_stop_after_praise_retains_partial_attempt_and_borrowed_owner(self):
        self.device.after_praise = lambda: setattr(self, "stopped", True)
        with self.assertRaises(service.PersonalMightRunnerError) as caught:
            self.run_route()
        partial = caught.exception.partial_result
        self.assertEqual((partial["total_input_count"], partial["praise_transport_calls"]), (4, 1))
        self.assertTrue(partial["accounting_verified"])
        self.assertTrue(partial["effect_reconciliation_required"])
        self.assertTrue(self.owner.held)

    def test_gray_replay_after_home_keeps_its_actual_native_capture_identity(self):
        seen = []
        def praised(frame, **source):
            identity = source["source_frame"]
            if identity.label == "personal-might-service-replay":
                seen.append(identity)
            return self.phase(frame) == "gray"
        with patch.object(route.vision, "personal_might_praised", side_effect=praised):
            result = self.run_route()
        self.assertEqual(len(seen), 1)
        native = seen[0]
        runtime = self.runtimes[0]
        captures = [row for row in map(json.loads, runtime.events.read_text().splitlines()) if row["type"] == "capture"]
        matching = [(ordinal, row) for ordinal, row in enumerate(captures, 1) if row["sha256"] == native.transport_sha256]
        self.assertEqual(len(matching), 1)
        ordinal, row = matching[0]
        self.assertEqual(native.capture_ordinal, ordinal)
        self.assertEqual(native.capture_completed_monotonic, row["captured_monotonic"])
        self.assertEqual(native.evidence_path, row["path"])
        self.assertEqual(native.runtime_session_id, str(runtime.session))
        self.assertLess(native.capture_ordinal, runtime.ordinal)
        self.assertEqual(result["praise_result_frame"]["capture_ordinal"], ordinal)
        self.assertEqual(result["terminal_home_frame"]["capture_ordinal"], runtime.ordinal)

    def test_completion_clock_and_cleanup_failure_preserve_consumed_praise(self):
        original_close = SafetyStore.close
        def broken_clock_after_cleanup(store):
            original_close(store)
            self.now = float("nan")
        with patch.object(SafetyStore, "close", new=broken_clock_after_cleanup), self.assertRaises(service.PersonalMightRunnerError) as caught:
            self.run_route()
        partial = caught.exception.partial_result
        self.assertEqual((partial["total_input_count"], partial["praise_transport_calls"]), (6, 1))
        self.assertIsNone(partial["completed_at_utc"])
        self.assertTrue(partial["effect_reconciliation_required"])
        self.assertTrue(partial["identical_retry_denied"])
        self.assertTrue(self.owner.held)

    def test_store_close_failure_is_reported_with_partial_counts(self):
        original_close = SafetyStore.close
        def broken_close(store):
            original_close(store)
            raise RuntimeError("store cleanup failed")
        with patch.object(SafetyStore, "close", new=broken_close), self.assertRaises(service.PersonalMightRunnerError) as caught:
            self.run_route()
        self.assertEqual((caught.exception.partial_result["total_input_count"], caught.exception.partial_result["praise_transport_calls"]), (6, 1))
        self.assertTrue(caught.exception.partial_result["identical_retry_denied"])

    def _popup_recovery(self, *, unknown_post=False, count=1):
        def recover(runtime, captured, **kwargs):
            for ordinal in range(count):
                before = runtime.capture(f"contextual-popup-before-{ordinal}")
                runtime.tap(before, target_identity="reset-popup-close" if ordinal == 0 else "scarlett-three-day-pack-in-game-back",
                    target_roi=(100, 100, 130, 130), action_key=f"{kwargs['action_key']}:{ordinal}", action_class="navigation")
            if unknown_post:
                self.device.phase = "unknown"
            post = runtime.capture("contextual-popup-post")
            ready = bool(kwargs["recognize_successor"](post))
            runtime.reconcile(kwargs["action_key"], "confirmed" if ready else "unresolved", post, "contextual-popup")
            return ContextualPopupRecoveryResult(post, True, True, ready, count, "known_popup_dismissed" if ready else "unknown_popup_successor")
        return recover

    def test_startup_input_is_adopted_once_and_retained_apart_from_one_praise(self):
        original_adopt = boundary.DevelopmentSession.adopt_retained_transport_count
        adopted = []
        def adopt(session, count, **kwargs):
            adopted.append((count, kwargs["source"]))
            return original_adopt(session, count, **kwargs)
        self.device.phase = "vip"
        self.startup.side_effect = self._popup_recovery()
        with patch.object(boundary.DevelopmentSession, "adopt_retained_transport_count", new=adopt):
            result = self.run_route()
        self.assertEqual([count for count, _ in adopted], [1])
        self.assertEqual((result["total_input_count"], result["route_input_count"], result["praise_transport_calls"]), (7, 6, 1))
        self.assertTrue(result["accounting_verified"])
        self.assertEqual(result["startup_recovery"]["input_count"], 1)
        self.assertTrue(result["startup_recovery"]["resume_ready"])
        self.assertNotEqual(result["source_frame"]["frame_sha256"], result["startup_recovery"]["source_frame"]["frame_sha256"])
        labels = [row["label"] for row in map(json.loads, self.runtimes[0].events.read_text().splitlines()) if row["type"] == "capture"]
        self.assertIn("personal-might-canonical-initial-home", labels)
        self.assertTrue(self.owner.held)

    def test_two_startup_inputs_leave_exactly_one_praise_in_the_same_eight_input_budget(self):
        self.device.phase = "vip"
        self.device.startup_sequence = ["scarlett", "home"]
        self.startup.side_effect = self._popup_recovery(count=2)
        result = self.run_route()
        self.assertEqual((result["startup_recovery"]["input_count"], result["route_input_count"],
                          result["total_input_count"], result["praise_transport_calls"]), (2, 6, 8, 1))
        self.assertTrue(result["accounting_verified"])

    def test_unknown_startup_and_unknown_popup_successor_never_enter_route(self):
        for sent in (False, True):
            with self.subTest(input_sent=sent):
                self.device = PersonalDevice()
                self.device.phase = "scarlett" if sent else "unknown"
                self.startup.side_effect = self._popup_recovery(unknown_post=True) if sent else (
                    lambda runtime, captured, **kw: ContextualPopupRecoveryResult(captured, False, None, False, 0, "unknown_startup"))
                with patch.object(route, "run", side_effect=AssertionError("route must not begin")) as run:
                    with self.assertRaises(service.PersonalMightRunnerError) as caught:
                        self.run_route()
                partial = caught.exception.partial_result
                self.assertEqual((partial["total_input_count"], partial["route_input_count"], partial["praise_transport_calls"]), (int(sent), 0, 0))
                self.assertEqual(partial["startup_recovery"]["input_count"], int(sent))
                self.assertFalse(partial["startup_recovery"]["resume_ready"])
                self.assertTrue(partial["accounting_verified"])
                run.assert_not_called()
                self.assertTrue(self.owner.held)

    def test_terminal_png_tampering_blocks_without_losing_consumption(self):
        original = route.run
        def tamper(**kwargs):
            result = original(**kwargs)
            Path(result["successor_frame"]).write_bytes(b"changed PNG")
            return result
        with patch.object(route, "run", side_effect=tamper), self.assertRaises(service.PersonalMightRunnerError) as caught:
            self.run_route()
        self.assertEqual((caught.exception.partial_result["total_input_count"], caught.exception.partial_result["praise_transport_calls"]), (6, 1))
        self.assertTrue(caught.exception.partial_result["identical_retry_denied"])

    def test_due_rejects_unknown_identity_counts_home_and_reset_crossing(self):
        result = self.run_route()
        for changes in ({"terminal_home_verified": False}, {"account_id": "other"},
                {"total_input_count": True}, {"praise_transport_calls": 0}, {"journal_status": "unresolved"},
                {"backend_identity": {}}, {"action_key": "other"}, {"praise_result_frame": {}},
                {"next_eligible_at": START + 30}, {"effect_reconciliation_required": True},
                {"completed_at_utc": START + 86400}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                service.personal_might_next_due(dict(result, **changes), self.identity, START)

    def test_handler_cannot_accept_another_registration_or_a_mapping(self):
        registered = CANONICAL_FLOW_REGISTRY[0].registration
        with self.assertRaises(ValueError):
            service.PersonalMightExecutionHandler(registered, lambda *_: None)
        with self.assertRaises(TypeError):
            service.PersonalMightExecutionHandler(registered.to_mapping(), lambda *_: None)
        binding = dict(flow_id=service.FLOW_ID, product_id=service.PRODUCT_ID,
            product_revision=service.PRODUCT_REVISION, production_handler="personal_might_executor",
            profile=service.PROFILE_ID, mode="supervised", registration_status="REGISTERED", scheduler_eligible=True)
        with patch.dict("automation_service.registry._FIXED_BINDINGS", {service.FLOW_ID: binding}):
            snapshot = RegisteredDispatchSnapshot.from_mapping(binding)
        handler = service.PersonalMightExecutionHandler(snapshot, lambda run, facts: (run, facts))
        self.assertEqual(handler.execute_run("run", "facts"), ("run", "facts"))
        self.assertFalse(handler.selection_only)
        self.assertEqual((handler.max_inputs, handler.max_actions), (8, 1))
        self.assertEqual(handler.describe().cadence, "daily_once_per_reset")


if __name__ == "__main__":
    unittest.main()
