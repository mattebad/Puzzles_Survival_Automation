"""Device-forbidden Bioenhancer execution and truthful UTC cadence/partial accounting."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from automation_service.bioenhancer import (
    BioenhancerExecutionHandler, BioenhancerNativePartialResultError,
    BioenhancerRunner, PRODUCT_ID, bioenhancer_next_due,
)
from automation_service.registry import NOVA_FLOW_ID, CANONICAL_FLOW_REGISTRY
from scripts import navigation_development_boundary as boundary
from scripts import startup_recovery as startup
from scripts.bioenhancer_free_research_canary import parse_free_research_cooldown
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.startup_recovery import ContextualPopupRecoveryResult
from tasks.scheduler_task_result import SchedulerIdentity


START = 1_800_000_000.0
IDENTITY = SchedulerIdentity("account", "server", "game-day-2027-01-15", PRODUCT_ID)


class ServiceBioenhancerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.patch = patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", self.root / "lock.sqlite3")
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.owner = boundary.RuntimeInputLock(owner="serve", invocation_id="serve-invocation")
        self.addCleanup(self.owner.release)
        self.now, self.stopped = START, False
        self.home = patch("scripts.startup_normalization.is_clean_home_frame", return_value=True)
        self.home_recognizer = self.home.start()
        self.addCleanup(self.home.stop)
        from scripts.bioenhancer_free_research_canary import bind_bioenhancer_back
        self.real_bio_binder = bind_bioenhancer_back
        self.bio = patch("scripts.bioenhancer_free_research_canary.bind_bioenhancer_back", return_value=None)
        self.bio_recognizer = self.bio.start()
        self.addCleanup(self.bio.stop)
        self.real_startup_recovery = startup.recover_contextual_startup_overlay
        self.startup = patch("scripts.startup_recovery.recover_contextual_startup_overlay",
                             side_effect=self._clear_startup)
        self.startup_recovery = self.startup.start()
        self.addCleanup(self.startup.stop)

    @staticmethod
    def _clear_startup(runtime, captured, *, recognize_successor, **kwargs):
        return ContextualPopupRecoveryResult(captured, False, True,
            bool(recognize_successor(captured)), 0, "clear_current_context")

    def checkpoint(self):
        self.owner.assert_held("serve", "serve-invocation")
        if self.stopped:
            raise RuntimeError("generation changed or stop requested")

    def _runtime(self):
        test = self
        class Runtime:
            def __init__(self):
                self.session = self.events = None
                self.ordinal = self.input_count = 0
                self.action_keys = set()
                self.frame_actions = set()
                self.checkpoint = None
                self.on_input = None
                self.initial_png = None
            def connect(self, **kwargs):
                self.session = kwargs["output_directory"] / "native"
                (self.session / "frames").mkdir(parents=True)
                self.events = self.session / "events.jsonl"
                self.events.write_text("")
                return self
            def capture(self, label):
                if self.checkpoint:
                    self.checkpoint()
                self.ordinal += 1
                if self.ordinal == 1 and self.initial_png is not None:
                    raw = self.initial_png
                    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                else:
                    image = np.full((1280, 800, 3), self.ordinal, np.uint8)
                    raw = cv2.imencode(".png", image)[1].tobytes()
                path = self.session / "frames" / f"{self.ordinal:04}-{label}.png"
                path.write_bytes(raw)
                sha = hashlib.sha256(raw).hexdigest()
                with self.events.open("a") as handle:
                    handle.write(json.dumps({"type": "capture", "label": label, "path": str(path), "sha256": sha, "timestamp": datetime.fromtimestamp(test.now, timezone.utc).isoformat()}) + "\n")
                return CapturedNativeFrame(image, raw, sha, float(self.ordinal), path)
            def tap(self, _frame, *, action_key, **kwargs):
                self.checkpoint()
                self.input_count += 1
                self.action_keys.add(action_key)
                self.frame_actions.add((_frame.sha256, kwargs.get("target_identity"), kwargs.get("target_roi")))
                with self.events.open("a") as handle:
                    handle.write(json.dumps({"type": "dispatch", "action_key": action_key,
                                             "execute": True, **kwargs}) + "\n")
                if self.on_input:
                    self.on_input()
            def reconcile(self, action_key, status, captured, reason):
                with self.events.open("a") as handle:
                    handle.write(json.dumps({"type": "reconcile", "action_key": action_key,
                                             "status": status, "post_sha256": captured.sha256,
                                             "reason": reason}) + "\n")
        return Runtime()

    def _native_route(self, *, consume):
        def route(*, session, runtime, **kwargs):
            cooldown_source = runtime.capture("cooldown-source")
            if consume:
                session.run_action(action_class="free_action", label="research", capture=runtime.capture,
                                   dispatch=lambda frame: runtime.tap(frame, action_key="free-research-1x:1"),
                                   recognize=lambda frame: "cooldown")
                cooldown_source = runtime.capture("free-research-post-settled")
            session.run_action(action_class="navigation", label="exit", capture=runtime.capture,
                               dispatch=lambda frame: runtime.tap(frame, action_key="bioenhancer-return-home:1"),
                               recognize=lambda frame: "home")
            home = runtime.capture("home-proof")
            cooldown = parse_free_research_cooldown("Free in 01:00:00", now=datetime.fromtimestamp(self.now, timezone.utc))
            self.now += 5
            return {
                "status": "completed", "no_work": not consume,
                "cooldown": {**cooldown, "frame_path": cooldown_source.path.relative_to(runtime.session).as_posix(), "frame_sha256": cooldown_source.sha256},
                "post_sha256": cooldown_source.sha256,
                "return_home": {"status": "home_returned", "terminal_home_frame": {"frame_path": home.path.relative_to(runtime.session).as_posix(), "frame_sha256": home.sha256}},
                "semantic_postcondition": {"proven": True, "timer_proven": True} if consume else None,
            }
        return route

    def _popup_startup(self, *, resume=True, kind="vip", throw_after_input=False):
        def recover(runtime, captured, *, action_key, recognize_successor, **kwargs):
            self.assertEqual(runtime.input_count, 0)
            before = runtime.capture("startup-dispatch-before")
            runtime.tap(before, action_key=action_key,
                        target_identity="reset-popup-close" if kind == "vip" else "scarlett-three-day-pack-in-game-back",
                        target_roi=(263, 781, 537, 869) if kind == "vip" else (39, 0, 168, 61))
            if throw_after_input:
                self.stopped = True
            settled = runtime.capture("startup-settled")
            return ContextualPopupRecoveryResult(settled, True, True,
                bool(resume and recognize_successor(settled)), 1,
                "known_popup_dismissed" if resume else "unknown_successor")
        return recover

    def _runner(self):
        return BioenhancerRunner(adb="unused", serial="emulator-5554",
                                 output_directory=self.root / "output", utc_clock=lambda: self.now)

    def test_unknown_initial_context_has_zero_inputs_and_never_enters_route(self):
        self.owner.acquire()
        self.home_recognizer.return_value = False
        runtime = self._runtime()
        with (
            patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=runtime.connect),
            patch("scripts.bioenhancer_free_research_canary.run") as route,
            self.assertRaises(BioenhancerNativePartialResultError) as caught,
        ):
            self._runner()(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner)
        route.assert_not_called()
        self.assertEqual(caught.exception.partial_result["total_input_count"], 0)
        self.assertFalse(caught.exception.partial_result["startup_recovery"]["resume_ready"])

    def test_unknown_or_stopped_popup_successor_retains_one_input_before_failure(self):
        self.owner.acquire()
        for stopped in (False, True):
            with self.subTest(stopped=stopped):
                self.stopped = False
                runtime = self._runtime()
                self.startup_recovery.side_effect = self._popup_startup(resume=False, throw_after_input=stopped)
                with (
                    patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=runtime.connect),
                    patch("scripts.bioenhancer_free_research_canary.run") as route,
                    self.assertRaises(BioenhancerNativePartialResultError) as caught,
                ):
                    self._runner()(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner)
                route.assert_not_called()
                partial = caught.exception.partial_result
                self.assertEqual((partial["total_input_count"], partial["free_research_transport_calls"]), (1, 0))
                self.assertEqual(partial["startup_recovery"]["input_count"], 1)
                self.assertEqual(partial["route_input_count"], 0)
                self.assertTrue(partial["accounting_verified"])
                self.assertTrue(partial["identical_retry_denied"])
                summary = json.loads((runtime.session.parent / "summary.json").read_text())
                self.assertEqual(summary["input_count"], 1)
                self.assertTrue(self.owner.held)

    def test_already_open_bio_context_does_not_require_home_or_popup_input(self):
        self.owner.acquire()
        self.home_recognizer.return_value = False
        self.bio_recognizer.return_value = object()
        runtime = self._runtime()
        with (
            patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=runtime.connect),
            patch("scripts.bioenhancer_free_research_canary.run", side_effect=self._native_route(consume=False)),
            patch("scripts.flow_delivery_bioenhancer_bluestacks._verify_no_work_frames", return_value=True),
        ):
            result = self._runner()(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner)
        self.assertEqual(result["startup_recovery"]["input_count"], 0)
        self.assertEqual(result["route_input_count"], 1)
        self.assertNotIn("home_frame", result["startup_recovery"])
        self.assertEqual((result["total_input_count"], result["free_research_transport_calls"]), (1, 0))

    def test_after_popup_bio_context_does_not_replace_fresh_clean_home(self):
        self.owner.acquire()
        self.home_recognizer.return_value = False
        self.bio_recognizer.return_value = object()
        self.startup_recovery.side_effect = self._popup_startup()
        runtime = self._runtime()
        with (
            patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=runtime.connect),
            patch("scripts.bioenhancer_free_research_canary.run") as route,
            self.assertRaises(BioenhancerNativePartialResultError) as caught,
        ):
            self._runner()(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner)
        route.assert_not_called()
        self.assertEqual(caught.exception.partial_result["total_input_count"], 1)
        self.assertIn("fresh clean Home", caught.exception.partial_result["reason"])

    def test_startup_and_route_share_the_eight_input_limit(self):
        self.owner.acquire()
        self.startup_recovery.side_effect = self._popup_startup()
        runtime = self._runtime()
        def too_many_inputs(*, session, runtime, **kwargs):
            for number in range(8):
                session.run_action(action_class="navigation", label=f"route-{number}", capture=runtime.capture,
                    dispatch=lambda frame, number=number: runtime.tap(frame, action_key=f"route:{number}"),
                    recognize=lambda _frame: "recognized")
        with (
            patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=runtime.connect),
            patch("scripts.bioenhancer_free_research_canary.run", side_effect=too_many_inputs),
            self.assertRaises(BioenhancerNativePartialResultError) as caught,
        ):
            self._runner()(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner)
        self.assertEqual(caught.exception.partial_result["total_input_count"], 8)
        self.assertEqual(caught.exception.partial_result["route_input_count"], 7)
        self.assertEqual(runtime.input_count, 8)
        self.assertTrue(caught.exception.partial_result["accounting_verified"])

    def test_shared_helper_vip_and_scarlett_use_no_second_store_or_runtime(self):
        from tests.test_startup_recovery import StartupRecoveryTests, popup

        self.owner.acquire()
        for kind in ("vip", "scarlett"):
            with self.subTest(kind=kind):
                self.now = START
                runtime = self._runtime()
                self.startup_recovery.side_effect = lambda *args, **kwargs: self.real_startup_recovery(
                    *args, **kwargs, sleep=lambda _seconds: None)
                def surface(_frame, raw):
                    if kind != "scarlett" or runtime.input_count:
                        return {"recognized": False, "commercial_looking": False}
                    return {**StartupRecoveryTests._scarlett_detail(),
                            "frame_sha256": hashlib.sha256(raw).hexdigest()}
                with (
                    patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=runtime.connect) as connect,
                    patch("scripts.bioenhancer_free_research_canary.run", side_effect=self._native_route(consume=False)),
                    patch("scripts.flow_delivery_bioenhancer_bluestacks._verify_no_work_frames", return_value=True),
                    patch.object(startup, "recognize_startup_surface", side_effect=surface),
                    patch.object(startup, "recognize_reset_popup", side_effect=lambda _frame:
                                 popup() if kind == "vip" and runtime.input_count == 0 else {"recognized": False}),
                    patch.object(startup, "SafetyStore", side_effect=AssertionError("no startup store")),
                    patch.object(startup, "recover_known_startup_overlay", side_effect=AssertionError("no leased recovery")),
                    patch.object(boundary.RuntimeInputLock, "acquire", side_effect=AssertionError("no second owner")),
                    patch.object(boundary.RuntimeInputLock, "release", side_effect=AssertionError("borrowed owner retained")),
                ):
                    result = self._runner()(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner)
                connect.assert_called_once()
                self.assertEqual((result["total_input_count"], result["route_input_count"]), (2, 1))
                recovery = result["startup_recovery"]
                self.assertEqual((recovery["input_count"], result["free_research_transport_calls"]), (1, 0))
                self.assertTrue(recovery["resume_ready"])
                self.assertTrue(recovery["accounting_verified"])
                for field in ("initial_frame", "settled_frame", "home_frame"):
                    self.assertTrue((runtime.session / recovery[field]["frame_path"]).is_file())
                rows = [json.loads(line) for line in runtime.events.read_text().splitlines()]
                self.assertEqual(sum(row["type"] == "dispatch" for row in rows), 2)
                self.assertTrue(any(row["type"] == "reconcile" and row["status"] == "confirmed" for row in rows))
                summary = json.loads((runtime.session.parent / "summary.json").read_text())
                self.assertEqual(summary["input_count"], 2)
                self.assertEqual(summary["control_memory"]["transport_count_source"], "events.jsonl:contextual-startup")
                self.assertFalse(summary["ownership_released"])
                self.assertEqual(summary["initial_frame_sha256"], recovery["home_frame"]["frame_sha256"])
                self.assertTrue(self.owner.held)

    def test_real_native_already_open_bio_passes_shared_startup_without_popup_input(self):
        self.owner.acquire()
        runtime = self._runtime()
        runtime.initial_png = (Path(__file__).parent / "fixtures/bioenhancer_exit/native-bio-research-cooldown.png").read_bytes()
        self.home_recognizer.return_value = False
        self.bio_recognizer.side_effect = self.real_bio_binder
        self.startup_recovery.side_effect = self.real_startup_recovery
        with (
            patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=runtime.connect),
            patch("scripts.bioenhancer_free_research_canary.run", side_effect=self._native_route(consume=False)),
            patch("scripts.flow_delivery_bioenhancer_bluestacks._verify_no_work_frames", return_value=True),
            patch.object(startup, "SafetyStore", side_effect=AssertionError("no startup store")),
        ):
            result = self._runner()(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner)
        self.assertTrue(result["startup_recovery"]["resume_ready"])
        self.assertEqual((result["startup_recovery"]["input_count"], result["route_input_count"]), (0, 1))
        self.assertNotIn("home_frame", result["startup_recovery"])

    def test_construction_is_device_free_and_wrong_registration_cannot_install_handler(self):
        with patch("scripts.bluestacks_native_runtime.ADBRunner", side_effect=AssertionError("device forbidden")):
            runner = BioenhancerRunner(adb="unused", serial="emulator-5554", output_directory=self.root / "output")
        self.assertFalse((self.root / "output").exists())
        nova = next(entry.registration for entry in CANONICAL_FLOW_REGISTRY if entry.flow_id == NOVA_FLOW_ID)
        with self.assertRaises(ValueError):
            BioenhancerExecutionHandler(nova, lambda *_args: None)
        with self.assertRaises(TypeError):
            BioenhancerExecutionHandler(nova.to_mapping(), lambda *_args: None)

    def test_native_effect_and_no_work_keep_actual_counts_and_utc_deadline(self):
        for consume in (False, True):
            with self.subTest(consume=consume):
                # Each iteration has its own immutable native evidence directory.
                self.root = self.root / str(consume)
                self.root.mkdir()
                self.owner.acquire()
                self.now = START
                runtime = self._runtime()
                runner = BioenhancerRunner(adb="unused", serial="emulator-5554", output_directory=self.root / "output", utc_clock=lambda: self.now)
                def recognize(_frame, *, now):
                    return parse_free_research_cooldown("Free in 01:00:00", now=now)
                with (
                    patch("scripts.bluestacks_native_runtime.ADBRunner", side_effect=AssertionError("device forbidden")),
                    patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=runtime.connect),
                    patch("scripts.bioenhancer_free_research_canary.run", side_effect=self._native_route(consume=consume)),
                    patch("scripts.bioenhancer_free_research_canary.recognize_free_research_cooldown", side_effect=recognize),
                    patch("scripts.flow_delivery_bioenhancer_bluestacks._verify_no_work_frames", return_value=True),
                ):
                    result = runner(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner)
                self.assertEqual(result["total_input_count"], 2 if consume else 1)
                self.assertEqual(result["free_research_transport_calls"], int(consume))
                self.assertEqual(result["no_work"], not consume)
                self.assertTrue(result["terminal_home_verified"])
                self.assertEqual(bioenhancer_next_due(result, IDENTITY, START), START + 3600)
                self.assertTrue(self.owner.held)
                self.owner.release()

    def test_stop_after_one_research_preserves_partial_count_without_another_input(self):
        self.owner.acquire()
        runtime = self._runtime()
        runtime.on_input = lambda: setattr(self, "stopped", True)
        runner = BioenhancerRunner(adb="unused", serial="emulator-5554", output_directory=self.root / "output", utc_clock=lambda: self.now)
        with (
            patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=runtime.connect),
            patch("scripts.bioenhancer_free_research_canary.run", side_effect=self._native_route(consume=True)),
        ):
            with self.assertRaises(BioenhancerNativePartialResultError) as caught:
                runner(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner)
        partial = caught.exception.partial_result
        self.assertEqual((partial["total_input_count"], partial["free_research_transport_calls"]), (1, 1))
        self.assertTrue(partial["accounting_verified"])
        self.assertTrue(partial["effect_reconciliation_required"])
        self.assertEqual(runtime.input_count, 1)
        self.assertTrue(self.owner.held)

    def test_incomplete_navigation_preserves_native_reason_without_cooldown_lookup(self):
        self.owner.acquire()
        runtime = self._runtime()

        def route(*, session, runtime, **kwargs):
            for ordinal in range(2):
                session.run_action(
                    action_class="navigation", label=f"open-research-{ordinal}", capture=runtime.capture,
                    dispatch=lambda frame, ordinal=ordinal: runtime.tap(frame, action_key=f"open-research:{ordinal}"),
                    recognize=lambda _frame: "research_lab_radial",
                )
            return {"status": "evidence_required", "reason": "free_research_not_bound"}

        with (
            patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=runtime.connect),
            patch("scripts.bioenhancer_free_research_canary.run", side_effect=route),
            patch("automation_service.bioenhancer._current_cooldown") as cooldown,
            self.assertRaises(BioenhancerNativePartialResultError) as caught,
        ):
            self._runner()(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner)
        cooldown.assert_not_called()
        partial = caught.exception.partial_result
        self.assertEqual(partial["reason"], "free_research_not_bound")
        self.assertEqual((partial["total_input_count"], partial["free_research_transport_calls"]), (2, 0))
        self.assertTrue(partial["accounting_verified"])
        self.assertFalse(partial["effect_reconciliation_required"])
        self.assertTrue(partial["identical_retry_denied"])
        self.assertNotIn("next_due_utc", partial)

    def test_missing_owner_or_stopped_run_never_connects_device(self):
        runner = BioenhancerRunner(adb="unused", serial="emulator-5554", output_directory=self.root / "output", utc_clock=lambda: self.now)
        with patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect") as connect:
            with self.assertRaises(BioenhancerNativePartialResultError) as caught:
                runner(IDENTITY, None, lambda: None, runtime_input_lock=self.owner)
        self.assertEqual(caught.exception.partial_result["total_input_count"], 0)
        connect.assert_not_called()

    def test_unverified_terminal_frames_preserve_consumed_inputs_and_block_retry(self):
        self.owner.acquire()
        runtime = self._runtime()
        runner = BioenhancerRunner(adb="unused", serial="emulator-5554", output_directory=self.root / "output", utc_clock=lambda: self.now)
        with (
            patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=runtime.connect),
            patch("scripts.bioenhancer_free_research_canary.run", side_effect=self._native_route(consume=True)),
            patch("scripts.bioenhancer_free_research_canary.recognize_free_research_cooldown", side_effect=lambda _frame, *, now: parse_free_research_cooldown("Free in 01:00:00", now=now)),
            patch("scripts.flow_delivery_bioenhancer_bluestacks._verify_no_work_frames", return_value=False),
        ):
            with self.assertRaises(BioenhancerNativePartialResultError) as caught:
                runner(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner)
        partial = caught.exception.partial_result
        self.assertEqual((partial["total_input_count"], partial["free_research_transport_calls"]), (2, 1))
        self.assertTrue(partial["accounting_verified"])
        self.assertFalse(partial["terminal_home_verified"])
        self.assertTrue(partial["identical_retry_denied"])
        self.assertTrue(self.owner.held)

    def test_due_requires_verified_current_identity_home_effect_and_clock(self):
        cooldown = parse_free_research_cooldown("Free in 01:00:00", now=datetime.fromtimestamp(START, timezone.utc))
        base = {
            "status": "completed", "terminal_home_verified": True, "cooldown_proof_verified": True,
            "accounting_verified": True, "time_basis": "utc", "completed_at_utc": START + 5,
            "account_id": IDENTITY.account_id, "server_id": IDENTITY.server_id, "reset_id": IDENTITY.reset_id,
            "total_input_count": 1, "free_research_transport_calls": 0, "no_work": True,
            "cooldown": cooldown, "next_due_utc": cooldown["next_due_utc"],
        }
        self.assertEqual(bioenhancer_next_due(base, IDENTITY, START), START + 3600)
        for changes in ({"terminal_home_verified": False}, {"account_id": "other"}, {"completed_at_utc": START - 1}, {"no_work": False}, {"free_research_transport_calls": 1}, {"total_input_count": True}, {"effect_reconciliation_required": True}, {"cooldown_proof_verified": False}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                bioenhancer_next_due(dict(base, **changes), IDENTITY, START)
        with self.assertRaises(ValueError):
            bioenhancer_next_due(base, IDENTITY, START + 10)


if __name__ == "__main__":
    unittest.main()
