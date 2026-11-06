"""Focused canonical Supply Depot service-boundary checks."""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import automation_service.registry as registry
from automation_service.supply import (
    FLOW_ID,
    PRODUCT_ID,
    PRODUCT_REVISION,
    PROFILE_ID,
    SupplyExecutionHandler,
    SupplyNativePartialResultError,
    SupplyRunner,
    supply_next_due,
)
from scripts import navigation_development_boundary as boundary
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.navigation_development_boundary import DevelopmentSession
from scripts.startup_recovery import ContextualPopupRecoveryResult
from tasks.scheduler_task_result import SchedulerIdentity
from tasks.home_atlas_vision import frame_digest
from tasks.perception_bundle import NativeFrameIdentity
from tasks.supply_depot_vision import SupplyDepotControl, SupplyDepotScreenRecognition
from tests.ocr_memo import install_module_memo
from tests.support.environment import requires_ocr_worker, requires_tesseract



def setUpModule():
    # Identical frames are replayed across tests; run real Tesseract once per unique input.
    install_module_memo()


START = 1_800_000_000.0
IDENTITY = SchedulerIdentity("account", "server", "game-day-2027-01-15", PRODUCT_ID)
HOME_FIXTURE = Path(__file__).parent / "fixtures" / "home_base" / "native-home-20261029.png"
NON_HOME_FIXTURE = Path(__file__).parent / "fixtures" / "home_nav" / "campaign-20261028-a.png"


class ServiceSupplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.lock_patch = patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", self.root / "lock.sqlite3")
        self.lock_patch.start()
        self.addCleanup(self.lock_patch.stop)
        self.owner = boundary.RuntimeInputLock(owner="serve", invocation_id="serve-invocation")
        self.addCleanup(self.owner.release)
        self.now = START

    def checkpoint(self):
        self.owner.assert_held("serve", "serve-invocation")

    def _runtime(self, terminal_payload):
        test = self

        class Runtime:
            def __init__(self):
                self.session = None
                self.events = None
                self.ordinal = 0
                self.input_count = 0
                self.action_keys = set()
                self.checkpoint = None
                self.max_inputs = None
                self.terminal_payload = terminal_payload
                self.initial_payload = HOME_FIXTURE.read_bytes()
                self.after_startup_payload = HOME_FIXTURE.read_bytes()
                self.last_terminal_path = None

            def connect(self, **kwargs):
                self.session = Path(kwargs["output_directory"]) / "native"
                (self.session / "frames").mkdir(parents=True)
                self.events = self.session / "events.jsonl"
                self.events.write_text("", encoding="utf-8")
                return self

            def capture(self, label):
                if self.checkpoint:
                    self.checkpoint()
                self.ordinal += 1
                if label == "supply-depot-canonical-initial":
                    payload = self.initial_payload
                    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
                elif label in {"supply-depot-canonical-after-startup", "startup-helper-settled"}:
                    payload = self.after_startup_payload
                    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
                elif label == "supply-depot-home-settled":
                    payload = self.terminal_payload
                    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
                else:
                    image = np.full((1280, 800, 3), self.ordinal, np.uint8)
                    payload = cv2.imencode(".png", image)[1].tobytes()
                path = self.session / "frames" / f"{self.ordinal:04d}-{label}.png"
                path.write_bytes(payload)
                if label == "supply-depot-home-settled":
                    self.last_terminal_path = path
                digest = hashlib.sha256(payload).hexdigest()
                with self.events.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({
                        "type": "capture",
                        "label": label,
                        "path": str(path),
                        "sha256": digest,
                        "captured_monotonic": float(self.ordinal),
                        "timestamp": datetime.fromtimestamp(test.now, timezone.utc).isoformat(),
                    }) + "\n")
                return CapturedNativeFrame(image, payload, digest, float(self.ordinal), path)

            def _dispatch(self, source, *, action_key, target_identity, target_roi, **kwargs):
                if self.checkpoint:
                    self.checkpoint()
                self.action_keys.add(action_key)
                self.input_count += 1
                with self.events.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({
                        "type": "dispatch",
                        "action_key": action_key,
                        "target_identity": target_identity,
                        "target_roi": target_roi,
                        "source_sha256": source.sha256,
                    }) + "\n")

            def tap(self, source, *, target_identity, target_roi, action_key, **kwargs):
                self._dispatch(source, action_key=action_key, target_identity=target_identity, target_roi=target_roi, **kwargs)

            def long_press(self, source, *, target_identity, target_roi, action_key, **kwargs):
                self._dispatch(source, action_key=action_key, target_identity=target_identity, target_roi=target_roi, **kwargs)

        return Runtime()

    def _native_route(self, *, consume=False, fail_after_hold=False, tamper_terminal=False):
        def route(*, session, runtime, **kwargs):
            before = runtime.capture("supply-depot-free-source")
            if consume:
                session.run_action(
                    action_class="resource_collection",
                    label="supply-depot-free-hold",
                    capture=runtime.capture,
                    target_roi=(100, 100, 200, 200),
                    dispatch=lambda frame: runtime.long_press(
                        frame,
                        target_identity="supply-depot-free-food-hold",
                        target_roi=(100, 100, 200, 200),
                        action_key="supply-depot-free-hold:3:test",
                    ),
                    recognize=lambda frame: "exhausted",
                )
                if fail_after_hold:
                    raise RuntimeError("route stopped after reserved free hold")
            session.run_action(
                action_class="navigation",
                label="supply-depot-visible-exit",
                capture=runtime.capture,
                target_roi=(10, 10, 20, 20),
                dispatch=lambda frame: runtime.tap(
                    frame,
                    target_identity="supply-depot-back-arrow",
                    target_roi=(10, 10, 20, 20),
                    action_key="supply-depot-visible-exit:test",
                ),
                recognize=lambda frame: "home_verified",
            )
            runtime.capture("supply-depot-home-settled")
            if tamper_terminal:
                runtime.last_terminal_path.write_bytes(b"changed-after-capture")
            return {
                "status": "completed",
                "terminal_home_verified": True,
                "free_attempts_before": 3 if consume else 0,
                "free_attempts_after": 0,
                "hold_transport_calls": 1 if consume else 0,
            }

        return route

    def _runner(self, runtime):
        return SupplyRunner(
            adb="unused",
            serial="emulator-5554",
            output_directory=self.root / "output",
            utc_clock=lambda: self.now,
        )

    def _startup(self, *, ready=True, consume=False, interrupt=False):
        def recover(runtime, captured, *, action_key, recognize_successor, **kwargs):
            for ordinal in range(int(consume)):
                runtime.tap(captured, action_key=f"{action_key}:{ordinal}",
                    target_identity="reset-popup-close" if ordinal == 0 else "scarlett-three-day-pack-in-game-back",
                    target_roi=(10, 10, 20, 20))
            if interrupt:
                raise RuntimeError("startup interrupted after reserved input")
            settled = runtime.capture("startup-helper-settled") if consume else captured
            return ContextualPopupRecoveryResult(settled, consume, True, ready,
                int(consume), "known_popup_dismissed" if consume else "unknown_startup_surface")
        return recover

    def test_construction_is_device_free_and_descriptor_is_reset_scoped(self):
        with patch("scripts.bluestacks_native_runtime.ADBRunner", side_effect=AssertionError("device forbidden")):
            runner = self._runner(None)
        self.assertFalse((self.root / "output").exists())
        fixed = {
            FLOW_ID: {
                "flow_id": FLOW_ID,
                "product_id": PRODUCT_ID,
                "product_revision": PRODUCT_REVISION,
                "production_handler": "supply_depot_execution_handler",
                "profile": PROFILE_ID,
                "mode": "phase_canary",
                "registration_status": "REGISTERED",
                "scheduler_eligible": True,
            }
        }
        with patch.dict(registry._FIXED_BINDINGS, fixed, clear=False):
            snapshot = registry.RegisteredDispatchSnapshot(**fixed[FLOW_ID])
            handler = SupplyExecutionHandler(snapshot, lambda run, facts: run)
        descriptor = handler.describe()
        self.assertEqual((descriptor.flow_id, descriptor.accepted_product, descriptor.product_revision), (FLOW_ID, PRODUCT_ID, PRODUCT_REVISION))
        self.assertEqual((descriptor.cadence, descriptor.reset_scoped), ("daily_once_per_reset", True))

    @requires_tesseract
    def test_free_effect_and_zero_work_have_exact_counts_and_actual_reset(self):
        for consume in (False, True):
            with self.subTest(consume=consume):
                self.owner.acquire()
                runtime = self._runtime(HOME_FIXTURE.read_bytes())
                with (
                    patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=runtime.connect),
                    patch("scripts.supply_depot_free_route.run", side_effect=self._native_route(consume=consume)),
                ):
                    result = self._runner(runtime)(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner)
                self.assertEqual(result["total_input_count"], 1 + int(consume))
                self.assertEqual(result["route_input_count"], result["total_input_count"])
                self.assertEqual(result["hold_transport_calls"], int(consume))
                self.assertEqual(result["free_attempts_before"], 3 if consume else 0)
                self.assertTrue(result["terminal_home_verified"])
                self.assertEqual(result["next_reset_at_utc"], START - (START % 86400) + 86400)
                self.assertEqual(supply_next_due(result, IDENTITY, START), result["next_reset_at_utc"])
                self.assertFalse(self.owner.held is False)
                self.owner.release()

    @requires_tesseract
    def test_failure_after_hold_keeps_reserved_count_and_denies_retry(self):
        self.owner.acquire()
        runtime = self._runtime(HOME_FIXTURE.read_bytes())
        with (
            patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=runtime.connect),
            patch("scripts.supply_depot_free_route.run", side_effect=self._native_route(consume=True, fail_after_hold=True)),
        ):
            with self.assertRaises(SupplyNativePartialResultError) as caught:
                self._runner(runtime)(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner)
        partial = caught.exception.partial_result
        self.assertEqual((partial["total_input_count"], partial["hold_transport_calls"]), (1, 1))
        self.assertTrue(partial["accounting_verified"])
        self.assertTrue(partial["effect_reconciliation_required"])
        self.assertTrue(partial["identical_retry_denied"])
        self.assertTrue(self.owner.held)

    @requires_tesseract
    def test_navigation_failure_preserves_native_reason_and_exact_zero_effect_accounting(self):
        self.owner.acquire()
        runtime = self._runtime(HOME_FIXTURE.read_bytes())

        def route(*, session, runtime, **kwargs):
            for index in range(2):
                session.run_action(
                    action_class="navigation", label=f"supply-navigation-{index}",
                    capture=runtime.capture, target_roi=(10, 10, 20, 20),
                    dispatch=lambda frame, index=index: runtime.tap(
                        frame, target_identity="home-camera-click-drag" if index == 0 else "home.building.supply_depot",
                        target_roi=(10, 10, 20, 20), action_key=f"supply-navigation-{index}"),
                    recognize=lambda frame: "radial_observed",
                )
            return {"status": "blocked", "reason": "supply_depot_radial_not_recognized",
                    "free_attempts_before": None, "free_attempts_after": None,
                    "hold_transport_calls": 0, "terminal_home_verified": False}

        with (
            patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=runtime.connect),
            patch("scripts.supply_depot_free_route.run", side_effect=route),
        ):
            with self.assertRaises(SupplyNativePartialResultError) as caught:
                self._runner(runtime)(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner)
        partial = caught.exception.partial_result
        self.assertEqual(partial["reason"], "supply_depot_radial_not_recognized")
        self.assertEqual((partial["input_count"], partial["hold_transport_calls"]), (2, 0))
        self.assertTrue(partial["accounting_verified"])
        self.assertFalse(partial["effect_reconciliation_required"])
        self.assertTrue(partial["identical_retry_denied"])
        self.assertFalse(partial["terminal_home_verified"])
        self.assertIsNone(partial["free_attempts_before"])
        self.assertIsNone(partial["free_attempts_after"])

    @requires_tesseract
    def test_popup_input_is_adopted_once_and_stays_separate_from_free_hold(self):
        self.owner.acquire()
        runtime = self._runtime(HOME_FIXTURE.read_bytes())
        runtime.initial_payload = Path("tasks/assets/navigation/800x1280/reset_popup_source.png").read_bytes()
        original_adopt = DevelopmentSession.adopt_retained_transport_count
        route = self._native_route()
        def run(**kwargs):
            self.assertEqual((kwargs["session"].input_count, kwargs["runtime"].input_count), (1, 1))
            self.assertIn("supply-depot-canonical-after-startup", kwargs["session"].initial_observation.frame_path)
            return route(**kwargs)
        with (
            patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=runtime.connect),
            patch("scripts.startup_recovery.recover_contextual_startup_overlay", side_effect=self._startup(ready=True, consume=True)),
            patch("scripts.supply_depot_free_route.run", side_effect=run),
            patch.object(DevelopmentSession, "adopt_retained_transport_count", autospec=True, side_effect=original_adopt) as adopt,
            patch.object(boundary.RuntimeInputLock, "acquire", side_effect=AssertionError("no nested owner")),
            patch.object(boundary.RuntimeInputLock, "release", side_effect=AssertionError("borrowed owner retained")),
        ):
            result = self._runner(runtime)(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner)
        self.assertEqual(adopt.call_count, 1)
        self.assertEqual(adopt.call_args.args[1], 1)
        self.assertEqual((result["total_input_count"], result["hold_transport_calls"]), (2, 0))
        self.assertEqual(result["route_input_count"], 1)
        self.assertEqual(result["startup_recovery"]["input_count"], 1)
        self.assertTrue(result["startup_recovery"]["clean_home_verified"])
        self.assertNotEqual(result["startup_recovery"]["source_frame"]["frame_sha256"], result["startup_recovery"]["route_source_frame"]["frame_sha256"])
        self.assertTrue(result["no_work"])
        self.assertTrue(result["accounting_verified"])
        self.assertTrue(self.owner.held)

    @requires_tesseract
    def test_two_startup_inputs_are_adopted_once_before_zero_hold_route(self):
        self.owner.acquire()
        runtime = self._runtime(HOME_FIXTURE.read_bytes())
        def run(**kwargs):
            self.assertEqual((kwargs["session"].input_count, kwargs["runtime"].input_count), (2, 2))
            return self._native_route()(**kwargs)
        original = DevelopmentSession.adopt_retained_transport_count
        with patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=runtime.connect), \
                patch("scripts.startup_recovery.recover_contextual_startup_overlay", side_effect=self._startup(consume=2)), \
                patch("scripts.supply_depot_free_route.run", side_effect=run), \
                patch.object(DevelopmentSession, "adopt_retained_transport_count", autospec=True, side_effect=original) as adopt:
            result = self._runner(runtime)(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner)
        self.assertEqual(adopt.call_count, 1)
        self.assertEqual(adopt.call_args.args[1], 2)
        self.assertEqual((result["startup_recovery"]["input_count"], result["route_input_count"],
                          result["total_input_count"], result["hold_transport_calls"]), (2, 1, 3, 0))
        self.assertTrue(result["accounting_verified"])

    def test_unknown_startup_or_unknown_successor_blocks_route_with_true_partial_count(self):
        for consume, interrupt in ((False, False), (True, False), (True, True)):
            with self.subTest(consume=consume, interrupt=interrupt):
                self.owner.acquire()
                runtime = self._runtime(HOME_FIXTURE.read_bytes())
                original_adopt = DevelopmentSession.adopt_retained_transport_count
                with (
                    patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=runtime.connect),
                    patch("scripts.startup_recovery.recover_contextual_startup_overlay", side_effect=self._startup(ready=False, consume=consume, interrupt=interrupt)),
                    patch("scripts.supply_depot_free_route.run", side_effect=AssertionError("route must not start")) as run,
                    patch.object(DevelopmentSession, "adopt_retained_transport_count", autospec=True, side_effect=original_adopt) as adopt,
                ):
                    with self.assertRaises(SupplyNativePartialResultError) as caught:
                        self._runner(runtime)(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner)
                partial = caught.exception.partial_result
                self.assertEqual((partial["total_input_count"], partial["hold_transport_calls"]), (int(consume), 0))
                self.assertEqual(partial["startup_recovery"]["input_count"], int(consume))
                self.assertEqual(partial["route_input_count"], 0)
                self.assertTrue(partial["accounting_verified"])
                self.assertEqual(adopt.call_count, 1)
                self.assertEqual(adopt.call_args.args[1], int(consume))
                self.assertFalse(partial["effect_reconciliation_required"])
                self.assertEqual(partial["identical_retry_denied"], consume)
                run.assert_not_called()
                self.owner.release()

    @requires_tesseract
    def test_popup_success_must_recapture_clean_home_before_route_binding(self):
        self.owner.acquire()
        runtime = self._runtime(HOME_FIXTURE.read_bytes())
        runtime.after_startup_payload = NON_HOME_FIXTURE.read_bytes()
        with (
            patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=runtime.connect),
            patch("scripts.startup_recovery.recover_contextual_startup_overlay", side_effect=self._startup(ready=True, consume=True)),
            patch("scripts.supply_depot_free_route.run", side_effect=AssertionError("dirty Home cannot start route")) as run,
        ):
            with self.assertRaises(SupplyNativePartialResultError) as caught:
                self._runner(runtime)(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner)
        self.assertEqual(caught.exception.partial_result["total_input_count"], 1)
        self.assertFalse(caught.exception.partial_result["startup_recovery"]["clean_home_verified"])
        run.assert_not_called()

    def test_lost_owner_blocks_raw_helper_capture_even_with_noop_checkpoint(self):
        self.owner.acquire()
        runtime = self._runtime(HOME_FIXTURE.read_bytes())
        def recover(runtime, captured, **kwargs):
            self.owner.release()
            runtime.capture("raw-startup-capture-after-owner-loss")
            raise AssertionError("raw capture must fail before transport")
        with (
            patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=runtime.connect),
            patch("scripts.startup_recovery.recover_contextual_startup_overlay", side_effect=recover),
            patch("scripts.supply_depot_free_route.run", side_effect=AssertionError("route cannot start")) as run,
        ):
            with self.assertRaises(SupplyNativePartialResultError) as caught:
                self._runner(runtime)(IDENTITY, None, lambda: None, runtime_input_lock=self.owner)
        self.assertEqual(caught.exception.partial_result["total_input_count"], 0)
        self.assertEqual(runtime.ordinal, 1)
        run.assert_not_called()

    def test_startup_native_ledger_mismatch_blocks_before_route(self):
        self.owner.acquire()
        runtime = self._runtime(HOME_FIXTURE.read_bytes())
        startup = self._startup(ready=True, consume=True)
        def missing_dispatch(*args, **kwargs):
            recovered = startup(*args, **kwargs)
            rows = [json.loads(line) for line in runtime.events.read_text().splitlines()]
            runtime.events.write_text("".join(json.dumps(row) + "\n" for row in rows if row["type"] != "dispatch"))
            return recovered
        with (
            patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=runtime.connect),
            patch("scripts.startup_recovery.recover_contextual_startup_overlay", side_effect=missing_dispatch),
            patch("scripts.supply_depot_free_route.run", side_effect=AssertionError("unmatched ledger cannot start route")) as run,
        ):
            with self.assertRaises(SupplyNativePartialResultError) as caught:
                self._runner(runtime)(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner)
        self.assertEqual((caught.exception.partial_result["total_input_count"], caught.exception.partial_result["hold_transport_calls"]), (1, 0))
        self.assertFalse(caught.exception.partial_result["startup_recovery"]["accounting_verified"])
        self.assertFalse(caught.exception.partial_result["accounting_verified"])
        run.assert_not_called()

    @requires_tesseract
    @requires_ocr_worker
    def test_known_route_surfaces_preserve_no_popup_entry_without_new_input(self):
        fixtures = Path(__file__).parent / "fixtures/supply_depot"
        for branch, name in (("facility", "native-facility-20261029.png"),
                ("exhausted", "native-exhausted-20261029.png"),
                ("arena", "native-arena-20261029.png"),
                ("radial", "native-raised-radial-20261029.png")):
            with self.subTest(source=name):
                self.owner.acquire()
                runtime = self._runtime(HOME_FIXTURE.read_bytes())
                runtime.initial_payload = (fixtures / name).read_bytes()
                expected_frame = cv2.imdecode(np.frombuffer(runtime.initial_payload, np.uint8), cv2.IMREAD_COLOR)

                def assert_source(frame, *, source_frame=None, source_png=None):
                    self.assertTrue(np.array_equal(frame, expected_frame))
                    if source_frame is not None:
                        self.assertIsInstance(source_frame, NativeFrameIdentity)
                        self.assertEqual(source_png, runtime.initial_payload)
                        self.assertEqual(source_frame.transport_sha256, hashlib.sha256(source_png).hexdigest())
                        self.assertEqual(source_frame.semantic_sha256, frame_digest(frame))
                        self.assertEqual(source_frame.runtime_session_id, str(runtime.session))
                        captures = [row for row in map(json.loads, runtime.events.read_text().splitlines())
                            if row["type"] == "capture"]
                        self.assertEqual(source_frame.capture_ordinal, len(captures))
                        self.assertEqual(source_frame.capture_completed_monotonic, captures[-1]["captured_monotonic"])
                        self.assertEqual(source_frame.evidence_path, captures[-1]["path"])

                def screen(frame, *, source_frame, source_png) -> SupplyDepotScreenRecognition:
                    assert_source(frame, source_frame=source_frame, source_png=source_png)
                    return SupplyDepotScreenRecognition(
                        recognized=branch == "exhausted", state="exhausted_or_cooldown" if branch == "exhausted" else "unknown",
                        title_text="Supply Depot" if branch == "exhausted" else "", controls=tuple(
                            SupplyDepotControl(index, (index * 200, 1140, (index + 1) * 200, 1280),
                                reward, "collected_or_cooldown", False, 0.90)
                            for index, reward in enumerate(("food", "wood", "steel", "gas"))
                        ) if branch == "exhausted" else (), premium_or_purchase_visible=False,
                        overlay=False, ambiguity="none" if branch == "exhausted" else "title_not_recognized",
                        frame_sha256=frame_digest(frame), daily_free_attempts=0 if branch == "exhausted" else None,
                    )

                def arena(frame) -> tuple[int, int, int, int] | None:
                    assert_source(frame)
                    return (47, 2, 128, 61) if branch == "arena" else None

                def radial(frame, *, source_frame, source_png) -> bool:
                    assert_source(frame, source_frame=source_frame, source_png=source_png)
                    return branch == "radial"

                with (
                    ExitStack() as seams,
                    patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=runtime.connect),
                    patch("scripts.supply_depot_free_route.run", side_effect=RuntimeError("offline stop at proven route entry")) as run,
                ):
                    # Keep one native pixel-to-service composition. The other rows
                    # exercise distinct source-bound service admission branches;
                    # their native recognizers are covered in the vision/route tests.
                    if branch != "facility":
                        seams.enter_context(patch("scripts.startup_normalization.is_clean_home_frame", return_value=False))
                        seams.enter_context(patch("scripts.supply_depot_free_route.recognize_supply_depot_screen", side_effect=screen))
                        seams.enter_context(patch("scripts.supply_depot_free_route._arena_exit_target", side_effect=arena))
                        seams.enter_context(patch("scripts.supply_depot_free_route.recognize_supply_depot_radial", side_effect=radial))
                    with self.assertRaises(SupplyNativePartialResultError) as caught:
                        self._runner(runtime)(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner)
                partial = caught.exception.partial_result
                self.assertEqual((partial["total_input_count"], partial["route_input_count"], partial["hold_transport_calls"]), (0, 0, 0))
                self.assertTrue(partial["accounting_verified"])
                startup = partial["startup_recovery"]
                self.assertTrue(startup["resume_ready"])
                self.assertTrue(startup["popup_absent"])
                self.assertFalse(startup["dismissed"])
                self.assertTrue(startup["accounting_verified"])
                self.assertEqual(startup["input_count"], 0)
                self.assertEqual(startup["source_frame"], startup["settled_frame"])
                self.assertEqual(startup["source_frame"], startup["route_source_frame"])
                rows = [json.loads(line) for line in runtime.events.read_text().splitlines()]
                self.assertFalse([row for row in rows if row["type"] == "dispatch"])
                self.assertEqual(runtime.input_count, 0)
                run.assert_called_once()
                self.owner.release()

    @requires_tesseract
    def test_terminal_home_replay_rejects_non_home_and_changed_bytes(self):
        cases = (
            (NON_HOME_FIXTURE.read_bytes(), False),
            (HOME_FIXTURE.read_bytes(), True),
        )
        for payload, tamper in cases:
            with self.subTest(non_home=payload == NON_HOME_FIXTURE.read_bytes(), tamper=tamper):
                self.owner.acquire()
                runtime = self._runtime(payload)
                with (
                    patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=runtime.connect),
                    patch("scripts.supply_depot_free_route.run", side_effect=self._native_route(tamper_terminal=tamper)),
                ):
                    with self.assertRaises(SupplyNativePartialResultError) as caught:
                        self._runner(runtime)(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner)
                self.assertEqual(caught.exception.partial_result["total_input_count"], 1)
                self.assertTrue(caught.exception.partial_result["identical_retry_denied"])
                self.owner.release()

    def test_due_rejects_missing_current_home_or_inferred_reset(self):
        base = {
            "status": "completed",
            "terminal_home_verified": True,
            "accounting_verified": True,
            "effect_reconciliation_required": False,
            "identical_retry_denied": False,
            "time_basis": "utc",
            "flow_id": FLOW_ID,
            "product_id": PRODUCT_ID,
            "product_revision": PRODUCT_REVISION,
            "task_id": PRODUCT_ID,
            "account_id": IDENTITY.account_id,
            "server_id": IDENTITY.server_id,
            "reset_id": IDENTITY.reset_id,
            "completed_at_utc": START + 5,
            "next_reset_at_utc": START - (START % 86400) + 86400,
            "total_input_count": 1,
            "hold_transport_calls": 0,
            "free_attempts_before": 0,
            "free_attempts_after": 0,
            "no_work": True,
            "terminal_home_frame": {"frame_path": "frames/home.png", "frame_sha256": "a" * 64},
        }
        self.assertEqual(supply_next_due(base, IDENTITY, START), base["next_reset_at_utc"])
        for changes in (
            {"terminal_home_frame": None},
            {"next_reset_at_utc": START + 10},
            {"accounting_verified": False},
            {"free_attempts_before": 2},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                supply_next_due({**base, **changes}, IDENTITY, START)


if __name__ == "__main__":
    unittest.main()
