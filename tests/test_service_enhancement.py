"""Device-free canonical Enhancement family ownership and truthful accounting."""
from __future__ import annotations

from dataclasses import replace
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import automation_service.enhancement as enhancement_service
import automation_service.registry as registry
from automation_service.contracts import NormalizedOutcome
from automation_service.enhancement import (
    EnhancementExecutionHandler, EnhancementNativePartialResultError, EnhancementRunner,
    FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID, enhancement_next_due,
)
from automation_service.service import AutomationService
from automation_service.state import BotStateManager, RunState
from scripts import flow_delivery_enhancement_bluestacks as delivery
from scripts import navigation_development_boundary as boundary
from scripts import pnsctl
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from tasks.scheduler_task_result import SchedulerIdentity
from tests.support.service_stop import VirtualStop
from tasks.runtime_identity import BLUESTACKS_SERIAL
from tests.ocr_memo import install_module_memo


def setUpModule():
    # Route/service tests replay identical frames; run real Tesseract once per
    # unique (image, config) and reuse that real result. Real-OCR recognition
    # coverage lives in the named recognition suites (see tests/ocr_memo.py).
    install_module_memo()


START = 1_800_000_000.0
IDENTITY = SchedulerIdentity("account", "server", "game-day-2027-01-15", PRODUCT_ID)
NATIVE_RESET = "local-2027-01-15-enhancement-family"


class _NativeRuntime:
    def __init__(self, test, directory):
        self.test = test
        self.session = directory
        self.frames = directory / "frames"
        self.frames.mkdir(parents=True)
        self.events = directory / "events.jsonl"
        self.events.write_text("", encoding="utf-8")
        self.ordinal = self.input_count = 0
        self.action_keys = set()
        self.frame_actions = set()
        self.checkpoint = None
        self.max_inputs = 24
        self.captures = []

    def _event(self, kind, values):
        with self.events.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": kind, **values}) + "\n")

    def capture(self, label):
        if self.checkpoint:
            self.checkpoint()
        self.ordinal += 1
        image = np.full((1280, 800, 3), self.ordinal + 50, np.uint8)
        png = cv2.imencode(".png", image)[1].tobytes()
        if getattr(self.test, "startup_popup", False):
            sequence = getattr(self.test, "startup_frames", (
                "startup/nova-vip-reset-20261031.png", "home_base/native-home-20261029.png",
            ))
            fixture = sequence[min(self.input_count, len(sequence) - 1)]
            png = (Path(__file__).parent / "fixtures" / fixture).read_bytes()
            image = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        path = self.frames / f"{self.ordinal:04d}-{label}.png"
        path.write_bytes(png)
        sha = hashlib.sha256(png).hexdigest()
        self._event("capture", {"label": label, "path": str(path), "sha256": sha,
                               "captured_monotonic": float(self.ordinal),
                               "timestamp": datetime.fromtimestamp(self.test.now, timezone.utc).isoformat()})
        captured = CapturedNativeFrame(image, png, sha, float(self.ordinal), path)
        self.captures.append(captured)
        return captured

    def tap(self, source, *, target_identity, target_roi, action_key, **kwargs):
        if self.checkpoint:
            self.checkpoint()
        self.input_count += 1
        self.action_keys.add(action_key)
        self.frame_actions.add((source.sha256, target_identity))
        # The real native adapter writes dispatch before transport, so a later
        # checkpoint/transport failure must still retain this attempted input.
        self._event("dispatch", {"action_key": action_key, "target_identity": target_identity,
                                 "target_roi": target_roi, "source_sha256": source.sha256,
                                 "execute": True, "action_class": kwargs.get("action_class", "navigation"),
                                 "consequential": kwargs.get("consequential", False),
                                 "point": [(target_roi[0] + target_roi[2]) // 2, (target_roi[1] + target_roi[3]) // 2],
                                 "timestamp": datetime.fromtimestamp(self.test.now, timezone.utc).isoformat()})
        if self.test.stop_after_inputs == self.input_count:
            self.test.stopped = True

    def reconcile(self, action_key, status, post, reason):
        self._event("reconcile", {"action_key": action_key, "status": status,
                                 "post_sha256": post.sha256, "reason": reason})


class ServiceEnhancementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for target, name, value in (
            (boundary, "RUNTIME_INPUT_LOCK_PATH", self.root / "lock.sqlite3"),
            (pnsctl, "BLUESTACKS_ARTIFACT_ROOT", self.root / "artifacts"),
            (enhancement_service, "BLUESTACKS_ADB", "fake-adb"),
            (delivery, "BLUESTACKS_ADB", "fake-adb"),
        ):
            patched = patch.object(target, name, value)
            patched.start()
            self.addCleanup(patched.stop)
        self.owner = boundary.RuntimeInputLock(owner="automation-service", invocation_id="serve-invocation")
        self.addCleanup(self.owner.release)
        self.now = START
        self.stopped = self.stop_on_connect = False
        self.stop_after_inputs = None
        self.runtimes = []
        self.uses = 3
        self.route_status = "completed"
        self.route_reason = "FAMILY_AND_HOME_VERIFIED"
        self.verification_status = "verified"
        self.topology = "continuous"
        self.retained_count = 0
        self.retained_sources = {}
        self.current_first_sources = False
        self.navigation_inputs = 0
        select = patch.object(delivery, "_select_family_state", side_effect=lambda root, reset, **_kwargs:
                              (root / "occurrences" / reset, reset, {}))
        select.start()
        self.addCleanup(select.stop)
        inventory = patch.object(delivery, "_verify_retained_categories",
                                 side_effect=self.retained_inventory, create=True)
        inventory.start()
        self.addCleanup(inventory.stop)

    def checkpoint(self):
        self.owner.assert_held("automation-service", "serve-invocation")
        if self.stopped:
            raise RuntimeError("stop or canonical generation changed")

    def connect(self, **kwargs):
        runtime = _NativeRuntime(self, Path(kwargs["output_directory"]) / f"native-{len(self.runtimes)}")
        self.runtimes.append(runtime)
        if self.stop_on_connect:
            self.stopped = True
        return runtime

    def runner(self):
        return EnhancementRunner(adb="fake-adb", serial="emulator-5554",
                                 output_directory=self.root / "output", utc_clock=lambda: self.now)

    @contextmanager
    def startup_session(self):
        self.startup_popup = True
        self.owner.acquire()
        try:
            with boundary.DevelopmentSession(owner="automation-service:enhancement", invocation_id="startup-test",
                    session_directory=self.root / "startup-session", max_inputs=24,
                    runtime_input_lock=self.owner, checkpoint=self.checkpoint) as session:
                runtime = self.connect(output_directory=session.session_directory / "runtime")
                runtime.checkpoint = self.checkpoint
                yield runtime, session
        finally:
            self.owner.release()

    def test_native_vip_startup_uses_one_shared_navigation_and_replays_before_family(self):
        with self.startup_session() as (runtime, session):
            proof = delivery._recover_family_startup(runtime, session)
            self.assertEqual((runtime.input_count, session.input_count), (1, 1))
            rows = delivery._read_event_rows(runtime.events)
            dispatches = [row for row in rows if row["type"] == "dispatch"]
            self.assertEqual([row["target_identity"] for row in dispatches], ["reset-popup-close"])
            result = {"startup_recovery": proof, "enhancement_result": {"reset_identity": NATIVE_RESET}}
            delivery._verify_family_startup(result, runtime.session, rows)
            for field in ("source_sha256", "settled_sha256", "action_key"):
                changed = copy.deepcopy(result)
                changed["startup_recovery"]["steps"][0][field] = "changed"
                with self.subTest(field=field), self.assertRaises(pnsctl.OperatorError):
                    delivery._verify_family_startup(changed, runtime.session, rows)

    def test_native_vip_scarlett_stack_reaches_home_with_two_unique_navigation_inputs(self):
        self.startup_frames = ("startup/nova-vip-reset-20261031.png",
                               "startup/scarlett-current-20261030.png", "home_base/native-home-20261029.png")
        with self.startup_session() as (runtime, session):
            proof = delivery._recover_family_startup(runtime, session)
            self.assertEqual((runtime.input_count, session.input_count), (2, 2))
            self.assertEqual([step["popup_identity"] for step in proof["steps"]],
                             ["VIP_POINTS_GET_PTS", "SCARLETT_THREE_DAY_PACK"])
            rows = delivery._read_event_rows(runtime.events)
            result = {"startup_recovery": proof, "enhancement_result": {"reset_identity": NATIVE_RESET}}
            delivery._verify_family_startup(result, runtime.session, rows)
            changed = copy.deepcopy(result)
            changed["startup_recovery"]["steps"] = list(reversed(proof["steps"]))
            with self.assertRaises(pnsctl.OperatorError):
                delivery._verify_family_startup(changed, runtime.session, rows)

    def test_reverse_known_stack_uses_shared_sequence_and_independent_continuous_replay(self):
        self.startup_frames = ("startup/scarlett-current-20261030.png",
                               "startup/nova-vip-reset-20261031.png", "home_base/native-home-20261029.png")
        with self.startup_session() as (runtime, session):
            proof = delivery._recover_family_startup(runtime, session)
            self.assertEqual((runtime.input_count, session.input_count), (2, 2))
            self.assertEqual([step["popup_identity"] for step in proof["steps"]],
                             ["SCARLETT_THREE_DAY_PACK", "VIP_POINTS_GET_PTS"])
            rows = delivery._read_event_rows(runtime.events)
            result = {"startup_recovery": proof, "enhancement_result": {"reset_identity": NATIVE_RESET}}
            delivery._verify_family_startup(result, runtime.session, rows)
            for field in ("immediate_before_sha256", "source_captured_monotonic", "target_identity", "confirmed"):
                changed = copy.deepcopy(result)
                changed["startup_recovery"]["steps"][1][field] = "changed"
                with self.subTest(field=field), self.assertRaises(pnsctl.OperatorError):
                    delivery._verify_family_startup(changed, runtime.session, rows)

    def test_startup_dispatch_prefix_and_each_confirmation_precede_later_input(self):
        self.startup_frames = ("startup/nova-vip-reset-20261031.png",
                               "startup/scarlett-current-20261030.png", "home_base/native-home-20261029.png")
        with self.startup_session() as (runtime, session):
            proof = delivery._recover_family_startup(runtime, session)
            later_source = runtime.capture("later-route-input-source")
            runtime.tap(later_source, target_identity="enhancement-use", target_roi=(100, 100, 200, 200),
                        action_key="enhancement:gear:enhancement-use:later", action_class="enhancement", consequential=True)
            later_post = runtime.capture("later-route-input-post")
            runtime.reconcile("enhancement:gear:enhancement-use:later", "confirmed", later_post, "later-route-step")
            rows = delivery._read_event_rows(runtime.events)
            result = {"startup_recovery": proof, "enhancement_result": {"reset_identity": NATIVE_RESET}}
            delivery._verify_family_startup(result, runtime.session, rows)
            for fault in ("use_before_startup", "use_between_steps", "late_first_confirmation", "late_final_confirmation"):
                changed = copy.deepcopy(rows)
                use = next(row for row in changed if row.get("target_identity") == "enhancement-use")
                if fault.startswith("use_"):
                    changed.remove(use)
                    startups = [row for row in changed if row.get("type") == "dispatch"]
                    pivot = startups[0] if fault == "use_before_startup" else startups[1]
                    changed.insert(changed.index(pivot), use)
                else:
                    key = proof["steps"][0 if fault == "late_first_confirmation" else 1]["action_key"]
                    confirmation = next(row for row in changed if row.get("type") == "reconcile" and row.get("action_key") == key)
                    changed.remove(confirmation)
                    pivot = (next(row for row in changed if row.get("type") == "capture"
                                  and Path(row["path"]).name == Path(proof["steps"][1]["immediate_before_frame"]).name)
                             if fault == "late_first_confirmation" else use)
                    changed.insert(changed.index(pivot) + 1, confirmation)
                with self.subTest(fault=fault), self.assertRaises(pnsctl.OperatorError):
                    delivery._verify_family_startup(result, runtime.session, changed)

    def test_startup_replay_accepts_windows_session_alias_without_accepting_foreign_evidence(self):
        from tests.support.contextual_startup import windows_short_path
        self.startup_frames = ("startup/nova-vip-reset-20261031.png",
                               "startup/scarlett-current-20261030.png", "home_base/native-home-20261029.png")
        with self.startup_session() as (runtime, session):
            proof = delivery._recover_family_startup(runtime, session)
            rows = delivery._read_event_rows(runtime.events)
            alias_session = windows_short_path(runtime.session)
            self.assertEqual(alias_session.resolve(), runtime.session.resolve())
            result = {"startup_recovery": proof, "enhancement_result": {"reset_identity": NATIVE_RESET}}
            delivery._verify_family_startup(result, alias_session, rows)
            foreign = self.root / "foreign" / Path(proof["steps"][0]["immediate_before_frame"]).name
            foreign.parent.mkdir()
            foreign.write_bytes((runtime.session / proof["steps"][0]["immediate_before_frame"]).read_bytes())
            changed = copy.deepcopy(result)
            changed["startup_recovery"]["steps"][0]["immediate_before_frame"] = str(foreign)
            with self.assertRaises(pnsctl.OperatorError):
                delivery._verify_family_startup(changed, alias_session, rows)

    def test_repeated_vip_popup_stops_after_one_navigation_without_retry(self):
        self.startup_frames = ("startup/nova-vip-reset-20261031.png",)
        with self.startup_session() as (runtime, session):
            with self.assertRaises(pnsctl.OperatorError):
                delivery._recover_family_startup(runtime, session)
            self.assertEqual((runtime.input_count, session.input_count), (1, 1))

    def test_startup_failure_keeps_shared_helper_input_without_entering_family(self):
        with self.startup_session() as (runtime, session):
            def interrupted(runtime, captured, **kwargs):
                runtime.tap(captured, target_identity="reset-popup-close", target_roi=(277, 767, 523, 847),
                            action_key=kwargs["action_key"])
                raise RuntimeError("stop after popup input")
            with patch("scripts.startup_recovery.recover_contextual_startup_overlay", side_effect=interrupted):
                with self.assertRaisesRegex(RuntimeError, "stop after popup input"):
                    delivery._recover_family_startup(runtime, session)
            self.assertEqual((runtime.input_count, session.input_count), (1, 1))

    def test_unknown_startup_cannot_dispatch_or_enter_family(self):
        with self.startup_session() as (runtime, session):
            with patch("scripts.startup_recovery.classify_startup_frame",
                       return_value=SimpleNamespace(status="blocked", reason="unknown_startup_surface")), \
                    patch("scripts.startup_recovery.recover_contextual_startup_overlay") as recovery:
                with self.assertRaises(pnsctl.OperatorError):
                    delivery._recover_family_startup(runtime, session)
            recovery.assert_not_called()
            self.assertEqual((runtime.input_count, session.input_count), (0, 0))

    def wrapper(self, queue, lease, *, live=True):
        self.assertTrue(live)
        session = delivery._outer_session(lease)
        initial = delivery._initial_observation(lease, session)
        self.assertEqual(session.owner, "automation-service:enhancement")
        self.assertIs(session.runtime_input_lock, self.owner)
        self.assertIs(lease["runtime_input_lock"], self.owner)
        self.assertEqual(lease["owner"], "automation-service")
        self.assertTrue(callable(lease["checkpoint"]))
        self.assertEqual(lease["max_inputs"], 24)
        self.assertEqual(lease["enhancement_reset_identity"], NATIVE_RESET)
        self.assertEqual((Path(session.session_directory) / "source.png").read_bytes(), self.runtimes[-1].captures[0].png)
        self.assertEqual(initial["frame_sha256"], self.runtimes[-1].captures[0].sha256)
        runtime = delivery.LocalBlueStacksRuntime.connect(
            adb="fake-adb", serial="emulator-5554", output_directory=session.session_directory / "runtime",
            workflow="enhancement-family", execute=True,
        )
        runtime.checkpoint = lease["checkpoint"]
        for index in range(self.navigation_inputs):
            session.run_action(
                action_class="navigation", label=f"setup-navigation-{index}", capture=runtime.capture,
                target_roi=(10, 10, 20, 20), dispatch=lambda frame, index=index: runtime.tap(
                    frame, target_identity="setup-navigation", target_roi=(10, 10, 20, 20),
                    action_key=f"setup-navigation:{index}",
                ), recognize=lambda frame: "navigation_successor",
            )
        proofs = []
        current = [variant for variant in ("gear", "chip", "module") if variant not in self.retained_sources][:self.uses]
        for variant in current:
            action_key = f"enhancement:{variant}:enhancement-use:current"
            session.run_action(
                action_class="navigation", label=f"enhancement-use-{variant}", capture=runtime.capture,
                target_roi=(100, 100, 200, 200),
                dispatch=lambda frame, key=action_key: runtime.tap(
                    frame, target_identity="enhancement-use", target_roi=(100, 100, 200, 200), action_key=key,
                ), recognize=lambda frame: "same_item_successor",
            )
            proofs.append({"variant": variant, "status": "completed", "resource_affecting_dispatch_count": 1,
                           "resource_affecting_action_key": action_key, "runtime_session": str(runtime.session)})
        session.run_action(
            action_class="navigation", label="return-home", capture=runtime.capture,
            target_roi=(10, 10, 20, 20), dispatch=lambda frame: runtime.tap(
                frame, target_identity="navigate-back", target_roi=(10, 10, 20, 20), action_key="home-return:current",
            ), recognize=lambda frame: "home_verified",
        )
        terminal = runtime.capture("family-home-terminal")
        by_variant = {proof["variant"]: proof for proof in proofs}
        by_variant.update({variant: dict(source, status="completed")
                           for variant, source in self.retained_sources.items()})
        proofs = [by_variant[variant] for variant in ("gear", "chip", "module") if variant in by_variant]
        route = {"status": self.route_status, "reason": self.route_reason,
                 "postcondition_verified": True, "terminal_recognized": True,
                 "reset_identity": NATIVE_RESET,
                 "source_frame_sha256": initial["frame_sha256"], "terminal_frame_sha256": terminal.sha256,
                 "resource_affecting_dispatch_count": len(proofs), "category_results": proofs,
                 "state_transition": ["HOME_CANONICAL", "COMMANDER_INFO_RECOGNIZED", "GEAR_SUCCESSOR_RECONCILED",
                                      "CHIP_SUCCESSOR_RECONCILED", "MODULE_SUCCESSOR_RECONCILED", "SAFE_TERMINAL_RECOGNIZED"]}
        result = {"flow_id": FLOW_ID, "status": self.route_status, "variant": "family",
                  "serial": BLUESTACKS_SERIAL, "native_width": 800, "native_height": 1280,
                  "input_count": session.input_count, "dispatch_count": runtime.input_count,
                  "resource_affecting_dispatch_count": len(current), "enhancement_result": route,
                  "terminal_recognized": True, "proof_topology": self.topology,
                  "effect_reconciliation_required": False,
                  "frames": [capture.path.relative_to(runtime.session).as_posix() for capture in runtime.captures],
                  "initial_observation": initial, "initial_frame_sha256": initial["frame_sha256"],
                  "production_registration": "NOT_REGISTERED", "scheduler_enabled": False}
        (runtime.session / "flow-delivery-result.json").write_text(json.dumps(result), encoding="utf-8")
        self.now += 5
        return json.dumps({"status": self.route_status, "flow_id": FLOW_ID, "variant": "family",
                           "session_directory": str(runtime.session), "input_count": runtime.input_count,
                           "dispatch_count": runtime.input_count, "proof_topology": self.topology,
                           "effect_reconciliation_required": False})

    def verifier(self, structure, queue, lease):
        self.assertEqual(structure["result"]["flow_id"], FLOW_ID)
        session = structure["session_directory"]
        proofs = structure["result"]["enhancement_result"]["category_results"]
        by_variant = {proof["variant"]: proof for proof in proofs}
        current = [variant for variant in ("gear", "chip", "module")
                   if variant in by_variant and variant not in self.retained_sources]
        retained = [variant for variant in ("gear", "chip", "module") if variant in self.retained_sources]
        sources = {}
        for variant in ("gear", "chip", "module"):
            if variant in self.retained_sources:
                sources[variant] = dict(self.retained_sources[variant])
            elif variant in by_variant:
                sources[variant] = self.source(variant, session, by_variant[variant]["resource_affecting_action_key"])
        if self.current_first_sources:
            sources = {variant: sources[variant] for variant in (*current, *retained)}
        return {"status": self.verification_status, "flow_id": FLOW_ID, "variant": "family",
                "postcondition_verified": True, "independent_rerecognition": True,
                "initial_observation_verified": True, "causal_trace_verified": True,
                "transport_accounting_verified": True, "proof_topology": self.topology,
                "categories_verified": list(by_variant), "current_categories": current, "retained_categories": retained,
                "retained_category_count": len(retained), "current_resource_affecting_dispatch_count": len(current),
                "category_source_proofs": sources}

    def execute(self):
        return self.runner()(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner)

    def source(self, variant, session, key=None):
        return {"status": "verified", "variant": variant, "reset_identity": NATIVE_RESET,
                "runtime_session": str(session), "delivery_sha256": "b" * 64,
                "resource_affecting_action_key": key or f"enhancement:{variant}:enhancement-use:retained"}

    def retained_inventory(self, completed, reset, *, checkpoint=None):
        self.assertEqual(reset, NATIVE_RESET)
        if checkpoint is not None:
            checkpoint()
        return {variant: self.retained_sources[variant] for variant in ("gear", "chip", "module") if variant in completed}

    def retained_family(self, variants=("gear", "chip", "module"), *, split=False):
        """Mock only native's strict replay boundary; wrapper tests own PNG proof."""
        self.retained_count += 1
        original = self.root / f"original-native-family-{self.retained_count}"
        self.retained_sources = {variant: self.source(variant, original / variant if split else original)
                                 for variant in ("gear", "chip", "module") if variant in variants}
        return {variant: dict(source, status="completed") for variant, source in self.retained_sources.items()}

    def retained_selection(self, progress):
        def select(root, reset, *, checkpoint=None, **_kwargs):
            self.assertTrue(callable(checkpoint))
            checkpoint()
            self.assertEqual(reset, NATIVE_RESET)
            self.assertFalse(self.runtimes)
            return root / "occurrences" / reset, reset, progress
        return select

    def test_construction_is_device_free_and_handler_has_exact_family_budget(self):
        with patch("scripts.bluestacks_native_runtime.ADBRunner", side_effect=AssertionError("device forbidden")):
            self.runner()
        self.assertFalse((self.root / "output").exists())
        binding = dict(flow_id=FLOW_ID, product_id=PRODUCT_ID, product_revision=PRODUCT_REVISION,
                       production_handler="enhancement_family_execution_handler", profile=PROFILE_ID,
                       mode="phase_canary", registration_status="REGISTERED", scheduler_eligible=True)
        with patch.dict(registry._FIXED_BINDINGS, {FLOW_ID: binding}):
            snapshot = registry.RegisteredDispatchSnapshot(**binding)
            handler = EnhancementExecutionHandler(snapshot, lambda run, facts: run)
        self.assertFalse(handler.selection_only)
        self.assertEqual((handler.max_inputs, handler.max_actions), (24, 3))
        descriptor = handler.describe()
        self.assertEqual((descriptor.flow_id, descriptor.family, descriptor.product_revision),
                         (FLOW_ID, PRODUCT_ID, PRODUCT_REVISION))
        self.assertEqual((descriptor.cadence, descriptor.reset_scoped), ("daily_once_per_reset", True))
        self.assertEqual(handler.plan(None).outcome, NormalizedOutcome.BLOCKED)
        with self.assertRaises(TypeError):
            EnhancementExecutionHandler(binding, lambda *_: None)
        other = next(item.registration for item in registry.CANONICAL_FLOW_REGISTRY if item.flow_id == registry.NOVA_FLOW_ID)
        with self.assertRaises(ValueError):
            EnhancementExecutionHandler(other, lambda *_: None)

    def test_wrong_owner_missing_checkpoint_identity_or_stale_reset_never_connects(self):
        with patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect") as connect:
            with self.assertRaises(boundary.NavigationBoundaryError):
                self.execute()  # The correct owner object is currently unheld.
            self.owner.acquire()
            for identity, checkpoint, lock in (
                (IDENTITY, None, self.owner),
                (object(), self.checkpoint, self.owner),
                (replace(IDENTITY, task_id="other-task"), self.checkpoint, self.owner),
                (replace(IDENTITY, reset_id="game-day-2027-01-14"), self.checkpoint, self.owner),
            ):
                with self.subTest(identity=identity, checkpoint=checkpoint):
                    with self.assertRaises((ValueError, TypeError, EnhancementNativePartialResultError)):
                        self.runner()(identity, None, checkpoint, runtime_input_lock=lock)
            with self.assertRaises((ValueError, EnhancementNativePartialResultError)):
                self.runner()(IDENTITY, None, self.checkpoint, runtime_input_lock=None)
            with self.assertRaises(ValueError):
                EnhancementRunner(adb="different-adb", serial="emulator-5554", output_directory=self.root / "output",
                                  utc_clock=lambda: self.now)(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner)
            self.owner.release()
            wrong = boundary.RuntimeInputLock(owner="unrelated-owner", invocation_id="wrong")
            with wrong:
                with self.assertRaises((ValueError, EnhancementNativePartialResultError)):
                    self.runner()(IDENTITY, None, lambda: None, runtime_input_lock=wrong)
        connect.assert_not_called()

    def test_full_family_uses_one_wrapper_and_current_proof_with_exact_counts(self):
        self.owner.acquire()
        with patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=self.connect), \
                patch.object(delivery, "run_enhancement_family", side_effect=self.wrapper) as wrapper, \
                patch.object(delivery, "verify_enhancement_family", side_effect=self.verifier) as verify:
            result = self.execute()
        wrapper.assert_called_once()
        verify.assert_called_once()
        self.assertEqual((result["total_input_count"], result["enhancement_dispatch_count"]), (4, 3))
        self.assertEqual(result["categories_completed"], 3)
        self.assertEqual(result["native_reset_identity"], NATIVE_RESET)
        self.assertEqual(result["reset_id"], IDENTITY.reset_id)
        self.assertTrue(result["accounting_verified"])
        self.assertTrue(result["terminal_home_verified"])
        self.assertEqual(enhancement_next_due(result, IDENTITY, START), START - START % 86400 + 86400)
        self.assertTrue(self.owner.held)

    def test_explicit_extra_family_keeps_real_reset_and_runs_all_three_once(self):
        self.owner.acquire()
        with patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=self.connect), \
                patch.object(delivery, "run_enhancement_family", side_effect=self.wrapper) as wrapper, \
                patch.object(delivery, "verify_enhancement_family", side_effect=self.verifier):
            result = self.runner()(IDENTITY, None, self.checkpoint, runtime_input_lock=self.owner,
                                   operator_request_id="user-extra-family")
        self.assertEqual(result["operator_request_id"], "user-extra-family")
        self.assertEqual(result["native_reset_identity"], NATIVE_RESET)
        self.assertEqual(result["enhancement_dispatch_count"], 3)
        self.assertEqual(result["family_verification"]["current_categories"], ["gear", "chip", "module"])
        self.assertEqual(wrapper.call_count, 1)
        self.assertEqual(wrapper.call_args.args[1]["operator_request_id"], "user-extra-family")

    def test_one_or_two_use_partial_exception_retains_attempted_counts_without_retry(self):
        for used in (1, 2):
            with self.subTest(uses=used):
                self.owner.acquire()
                self.stop_after_inputs = used
                with patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=self.connect), \
                        patch.object(delivery, "run_enhancement_family", side_effect=self.wrapper) as wrapper, \
                        patch.object(delivery, "verify_enhancement_family") as verify:
                    with self.assertRaises(EnhancementNativePartialResultError) as caught:
                        self.execute()
                partial = caught.exception.partial_result
                self.assertEqual((partial["total_input_count"], partial["enhancement_dispatch_count"]), (used, used))
                self.assertTrue(partial["accounting_verified"])
                self.assertTrue(partial["effect_reconciliation_required"])
                self.assertTrue(partial["identical_retry_denied"])
                self.assertFalse(partial["terminal_home_verified"])
                wrapper.assert_called_once()
                verify.assert_not_called()
                self.assertTrue(self.owner.held)
                self.owner.release()
                self.stopped = False

    def test_incomplete_or_unverified_family_never_becomes_success_or_retry(self):
        for uses, status, topology, verified in ((2, "completed", "continuous", "verified"),
                                                  (3, "completed", "composite", "verified"),
                                                  (3, "completed", "continuous", "evidence_required")):
            with self.subTest(uses=uses, topology=topology, verified=verified):
                self.owner.acquire()
                self.uses, self.route_status, self.topology, self.verification_status = uses, status, topology, verified
                with patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=self.connect), \
                        patch.object(delivery, "run_enhancement_family", side_effect=self.wrapper) as wrapper, \
                        patch.object(delivery, "verify_enhancement_family", side_effect=self.verifier):
                    with self.assertRaises(EnhancementNativePartialResultError) as caught:
                        self.execute()
                partial = caught.exception.partial_result
                self.assertEqual((partial["total_input_count"], partial["enhancement_dispatch_count"]), (uses + 1, uses))
                self.assertTrue(partial["effect_reconciliation_required"])
                self.assertTrue(partial["identical_retry_denied"])
                wrapper.assert_called_once()
                self.owner.release()

    def test_checkpoint_stops_before_initial_capture(self):
        self.owner.acquire()
        self.stop_on_connect = True
        with patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=self.connect), \
                patch.object(delivery, "run_enhancement_family") as wrapper:
            with self.assertRaises(EnhancementNativePartialResultError) as caught:
                self.execute()
        self.assertEqual(caught.exception.partial_result["total_input_count"], 0)
        self.assertFalse(self.runtimes[0].captures)
        wrapper.assert_not_called()

    def test_disagreeing_input_accounting_keeps_conservative_partial_count_and_blocks_retry(self):
        self.owner.acquire()

        def wrapper_with_reserved_but_unjournaled_input(queue, lease, *, live):
            result = self.wrapper(queue, lease, live=live)
            lease["development_session"].input_count += 1
            return result

        with patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=self.connect), \
                patch.object(delivery, "run_enhancement_family", side_effect=wrapper_with_reserved_but_unjournaled_input) as wrapper, \
                patch.object(delivery, "verify_enhancement_family") as verify:
            with self.assertRaises(EnhancementNativePartialResultError) as caught:
                self.execute()
        partial = caught.exception.partial_result
        self.assertEqual((partial["total_input_count"], partial["enhancement_dispatch_count"]), (5, 3))
        self.assertFalse(partial["accounting_verified"])
        self.assertTrue(partial["identical_retry_denied"])
        self.assertTrue(partial["effect_reconciliation_required"])
        wrapper.assert_called_once()
        verify.assert_not_called()

    def test_real_wrapper_accepts_borrowed_owner_and_sets_checkpoint_before_native_capture(self):
        self.owner.acquire()
        with boundary.DevelopmentSession(owner="automation-service:enhancement", invocation_id="wrapper-test",
                                         session_directory=self.root / "wrapper-session", max_inputs=24,
                                         runtime_input_lock=self.owner, checkpoint=self.checkpoint) as session:
            initial_runtime = self.connect(output_directory=session.session_directory / "initial")
            initial_runtime.checkpoint = self.checkpoint
            source = session.observe(initial_runtime.capture, label="initial")
            (session.session_directory / "source.png").write_bytes(source.png)
            initial = session.set_initial_observation(boundary.DevelopmentInitialObservation(
                {"frame_sha256": source.sha256}, source.sha256,
                invocation_id=session.invocation_id, frame_path="source.png"))
            lease = dict(development_session=session, owner="automation-service", runtime_input_lock=self.owner,
                         checkpoint=self.checkpoint, initial_observation=initial, initial_frame_sha256=source.sha256,
                         enhancement_reset_identity=NATIVE_RESET, max_inputs=24)
            self.assertIs(delivery._outer_session(lease), session)
            for invalid in ({"runtime_input_lock": None}, {"checkpoint": None}, {"owner": "another-owner"}):
                with self.subTest(invalid=invalid), self.assertRaises(pnsctl.OperatorError):
                    delivery._outer_session(dict(lease, **invalid))

            captures_before_stop = []
            def route(runtime, **_kwargs):
                self.assertTrue(callable(runtime.checkpoint))
                captures_before_stop.append(len(runtime.captures))
                self.stopped = True
                runtime.capture("must-not-capture-after-stop")

            with patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=self.connect), \
                    patch("scripts.enhancement_bluestacks.EnhancementIntegratedRoute") as integrated:
                integrated.side_effect = lambda runtime, **kwargs: type("Route", (), {"run": lambda _: route(runtime, **kwargs)})()
                with self.assertRaises(RuntimeError):
                    delivery.run_enhancement_family({}, lease, live=True)
            self.assertEqual(len(self.runtimes[-1].captures), captures_before_stop[0])
            self.assertEqual(self.runtimes[-1].input_count, 0)
        self.stopped = False
        self.owner.release()
        with boundary.DevelopmentSession(owner=f"pnsctl-development-session:{FLOW_ID}", invocation_id="pns-existing",
                                         session_directory=self.root / "pns-session", max_inputs=24) as session:
            self.assertIs(delivery._outer_session({"development_session": session}), session)

    def test_next_due_rejects_identity_clock_counts_and_proof_mutations(self):
        self.owner.acquire()
        with patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=self.connect), \
                patch.object(delivery, "run_enhancement_family", side_effect=self.wrapper), \
                patch.object(delivery, "verify_enhancement_family", side_effect=self.verifier):
            result = self.execute()
        for changes in ({"terminal_home_verified": False}, {"accounting_verified": False},
                        {"account_id": "another-account"}, {"reset_id": "game-day-2027-01-14"},
                        {"completed_at_utc": START - 1}, {"next_reset_at_utc": START + 60},
                        {"enhancement_dispatch_count": 2}, {"categories_completed": 2},
                        {"total_input_count": 25}, {"total_input_count": True},
                        {"effect_reconciliation_required": True}, {"identical_retry_denied": True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                enhancement_next_due(dict(result, **changes), IDENTITY, START)

    def test_partial_retained_categories_resume_one_wrapper_with_current_counts_only(self):
        for retained_variants in (("gear",), ("gear", "chip"), ("chip",)):
            with self.subTest(retained=retained_variants):
                progress = self.retained_family(retained_variants)
                self.uses = 3 - len(retained_variants)
                self.topology = "composite"
                self.owner.acquire()
                with patch.object(delivery, "_select_family_state", side_effect=self.retained_selection(progress)), \
                        patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=self.connect), \
                        patch.object(delivery, "run_enhancement_family", side_effect=self.wrapper) as wrapper, \
                        patch.object(delivery, "verify_enhancement_family", side_effect=self.verifier):
                    result = self.execute()
                wrapper.assert_called_once()
                self.assertEqual((result["total_input_count"], result["enhancement_dispatch_count"]), (self.uses + 1, self.uses))
                self.assertEqual(result["categories_completed"], 3)
                self.assertEqual(result["proof_topology"], "composite")
                verification = result["family_verification"]
                self.assertEqual(verification["retained_categories"], list(retained_variants))
                remaining = [variant for variant in ("gear", "chip", "module") if variant not in retained_variants]
                self.assertEqual(verification["current_categories"], remaining)
                rows = delivery._read_event_rows(self.runtimes[-1].events)
                keys = [row["action_key"] for row in delivery._resource_dispatch_rows(rows)]
                self.assertEqual([key.split(":")[1] for key in keys], remaining)
                self.assertTrue(result["terminal_home_verified"])
                self.assertEqual(enhancement_next_due(result, IDENTITY, START), START - START % 86400 + 86400)
                self.owner.release()
                self.runtimes.clear()

    def test_current_first_native_source_map_resumes_partial_family(self):
        progress = self.retained_family(("gear",))
        self.uses, self.topology, self.current_first_sources = 2, "composite", True
        self.owner.acquire()

        def verify(*args):
            verification = self.verifier(*args)
            self.assertEqual(list(verification["category_source_proofs"]), ["chip", "module", "gear"])
            return verification

        with patch.object(delivery, "_select_family_state", side_effect=self.retained_selection(progress)), \
                patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=self.connect), \
                patch.object(delivery, "run_enhancement_family", side_effect=self.wrapper) as wrapper, \
                patch.object(delivery, "verify_enhancement_family", side_effect=verify):
            result = self.execute()
        wrapper.assert_called_once()
        self.assertEqual((result["total_input_count"], result["enhancement_dispatch_count"]), (3, 2))
        self.assertEqual(result["categories_completed"], 3)
        self.assertEqual(result["family_verification"]["current_categories"], ["chip", "module"])
        self.assertEqual(result["family_verification"]["retained_categories"], ["gear"])
        self.assertEqual(enhancement_next_due(result, IDENTITY, START), START - START % 86400 + 86400)

    def test_all_retained_categories_from_one_or_many_sources_use_fresh_zero_input_home(self):
        for split in (False, True):
            with self.subTest(split=split):
                progress = self.retained_family(split=split)
                order = []

                def inventory(*args, **kwargs):
                    order.append("retained-verified")
                    return self.retained_inventory(*args, **kwargs)

                def connect(**kwargs):
                    order.append("current-connect")
                    return self.connect(**kwargs)

                self.owner.acquire()
                with patch.object(delivery, "_select_family_state", side_effect=self.retained_selection(progress)), \
                        patch.object(delivery, "_verify_retained_categories", side_effect=inventory), \
                        patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=connect), \
                        patch.object(delivery, "run_enhancement_family") as wrapper, \
                        patch.object(delivery, "_ensure_family_reservations") as reserve, \
                        patch.object(delivery, "_write_family_progress") as write_progress, \
                        patch("scripts.startup_normalization.is_clean_home_frame", return_value=True) as clean_home:
                    result = self.execute()
                self.assertEqual(result["status"], "already_completed")
                self.assertTrue(result["no_work"])
                self.assertEqual((result["total_input_count"], result["enhancement_dispatch_count"]), (0, 0))
                self.assertEqual(result["categories_completed"], 3)
                self.assertEqual(result["proof_topology"], "retained_categories_plus_current_home")
                self.assertEqual(len(self.runtimes), 1)
                self.assertEqual(len(self.runtimes[0].captures), 1)
                self.assertEqual(result["current_home_proof"]["frame_sha256"], self.runtimes[0].captures[0].sha256)
                self.assertEqual(result["retained_category_proofs"], self.retained_sources)
                self.assertEqual(len({proof["runtime_session"] for proof in result["retained_category_proofs"].values()}), 3 if split else 1)
                self.assertEqual(enhancement_next_due(result, IDENTITY, START), START - START % 86400 + 86400)
                self.assertLess(order.index("retained-verified"), order.index("current-connect"))
                clean_home.assert_called_once()
                wrapper.assert_not_called()
                reserve.assert_not_called()
                write_progress.assert_not_called()
                for changes in ({"no_work": False}, {"total_input_count": 1}, {"enhancement_dispatch_count": 1},
                                {"retained_category_proofs": None}, {"current_home_proof": None},
                                {"proof_topology": "continuous"}):
                    with self.subTest(changes=changes), self.assertRaises(ValueError):
                        enhancement_next_due(dict(result, **changes), IDENTITY, START)
                self.owner.release()
                self.runtimes.clear()

    def test_invalid_retained_inventory_or_native_replay_failure_stops_before_connect(self):
        for invalid in ("unknown", "duplicate_key", "wrong_reset", "unverified", "missing_source", "relative_source", "native_failure"):
            with self.subTest(invalid=invalid):
                progress = self.retained_family()
                if invalid == "unknown":
                    progress["unknown"] = dict(progress["gear"])
                elif invalid == "duplicate_key":
                    self.retained_sources["chip"]["resource_affecting_action_key"] = self.retained_sources["gear"]["resource_affecting_action_key"]
                elif invalid == "wrong_reset":
                    self.retained_sources["gear"]["reset_identity"] = "local-2027-01-14-enhancement-family"
                elif invalid == "unverified":
                    self.retained_sources["gear"]["status"] = "evidence_required"
                elif invalid == "missing_source":
                    self.retained_sources["gear"].pop("delivery_sha256")
                elif invalid == "relative_source":
                    self.retained_sources["gear"]["runtime_session"] = "relative-original"
                self.owner.acquire()
                with patch.object(delivery, "_select_family_state", side_effect=self.retained_selection(progress)), \
                        patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect") as connect, \
                        patch.object(delivery, "run_enhancement_family") as wrapper, \
                        patch.object(delivery, "_ensure_family_reservations") as reserve:
                    if invalid == "native_failure":
                        with patch.object(delivery, "_verify_retained_categories", side_effect=ValueError("strict source replay failed")):
                            with self.assertRaises(EnhancementNativePartialResultError):
                                self.execute()
                    else:
                        with self.assertRaises(EnhancementNativePartialResultError):
                            self.execute()
                connect.assert_not_called()
                wrapper.assert_not_called()
                reserve.assert_not_called()
                self.owner.release()

    def test_valid_retained_categories_still_require_fresh_current_home(self):
        progress = self.retained_family()
        self.owner.acquire()
        with patch.object(delivery, "_select_family_state", side_effect=self.retained_selection(progress)), \
                patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=self.connect), \
                patch.object(delivery, "run_enhancement_family") as wrapper, \
                patch("scripts.startup_normalization.is_clean_home_frame", return_value=False):
            with self.assertRaises(EnhancementNativePartialResultError) as caught:
                self.execute()
        self.assertEqual((caught.exception.partial_result["total_input_count"], caught.exception.partial_result["enhancement_dispatch_count"]), (0, 0))
        self.assertEqual(len(self.runtimes[0].captures), 1)
        self.assertEqual(self.runtimes[0].input_count, 0)
        wrapper.assert_not_called()

    def test_native_noncompletion_reason_survives_before_full_verification(self):
        self.route_status, self.route_reason, self.uses = "blocked", "CHIP_EQUIPPED_MODAL_NOT_PROVEN", 1
        self.owner.acquire()
        with patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=self.connect), \
                patch.object(delivery, "run_enhancement_family", side_effect=self.wrapper), \
                patch.object(delivery, "verify_enhancement_family") as verify:
            with self.assertRaises(EnhancementNativePartialResultError) as caught:
                self.execute()
        partial = caught.exception.partial_result
        self.assertEqual(partial["reason"], self.route_reason)
        self.assertEqual(partial["native_reason"], self.route_reason)
        self.assertEqual((partial["total_input_count"], partial["enhancement_dispatch_count"]), (2, 1))
        verify.assert_not_called()

    def test_next_due_rejects_bare_counts_and_unbound_source_inventory(self):
        self.owner.acquire()
        with patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=self.connect), \
                patch.object(delivery, "run_enhancement_family", side_effect=self.wrapper), \
                patch.object(delivery, "verify_enhancement_family", side_effect=self.verifier):
            result = self.execute()
        for field, value in (("categories_verified", ["gear", "chip"]), ("retained_category_count", 1),
                             ("current_resource_affecting_dispatch_count", 2), ("current_categories", ["chip", "module"]),
                             ("retained_categories", ["gear"]), ("category_source_proofs", {})):
            malformed = copy.deepcopy(result)
            malformed["family_verification"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                enhancement_next_due(malformed, IDENTITY, START)
        malformed = copy.deepcopy(result)
        malformed["family_verification"]["category_source_proofs"]["gear"]["runtime_session"] = str(self.root / "unrelated-source")
        with self.assertRaises(ValueError):
            enhancement_next_due(malformed, IDENTITY, START)

    def test_slow_verification_renews_real_service_lease_and_fences_before_projection(self):
        for lose_fence in (False, True):
            with self.subTest(lose_fence=lose_fence):
                self.now, self.uses, self.navigation_inputs, self.topology = START, 1, 7, "composite"
                self.runtimes.clear()
                progress = self.retained_family(("gear", "chip"))
                stop = VirtualStop(self.now)
                stop.on_wait = stop.set
                reports, heartbeats = [], []
                with BotStateManager(self.root / f"canonical-lease-{lose_fence}.sqlite3") as state:
                    service = AutomationService(mode="supervised", state=state, enhancement_runner=self.runner())
                    service.set_service_enabled(True)
                    service.set_flow_enabled(FLOW_ID, True)

                    def selected(root, reset, *, checkpoint=None, **_kwargs):
                        self.assertTrue(callable(checkpoint))
                        checkpoint()
                        return root / "occurrences" / reset, reset, progress

                    def inventory(completed, reset, *, checkpoint=None):
                        self.assertTrue(callable(checkpoint))
                        return self.retained_inventory(completed, reset, checkpoint=checkpoint)

                    def wrapper(queue, lease, *, live):
                        self.owner = lease["runtime_input_lock"]
                        return self.wrapper(queue, lease, live=live)

                    def slow_verifier(structure, queue, lease):
                        for _ in range(4):
                            self.now += 25
                            stop.now = self.now
                            lease["checkpoint"]()
                            renewed = state.get_service_lease()
                            self.assertEqual(renewed.heartbeat_at_utc, stop.now)
                            self.assertGreater(renewed.expires_at_utc, stop.now)
                            heartbeats.append(renewed.lease_generation)
                        if lose_fence:
                            service.set_flow_enabled(FLOW_ID, False)
                            service.set_flow_enabled(FLOW_ID, True)
                        return self.verifier(structure, queue, lease)

                    with patch.object(delivery, "_select_family_state", side_effect=selected), \
                            patch.object(delivery, "_verify_retained_categories", side_effect=inventory), \
                            patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=self.connect), \
                            patch.object(delivery, "run_enhancement_family", side_effect=wrapper) as native_run, \
                            patch.object(delivery, "verify_enhancement_family", side_effect=slow_verifier) as verify, \
                            patch.object(delivery, "_write_family_progress", side_effect=AssertionError("service cannot backfill progress")) as write_progress, \
                            patch("automation_service.enhancement.enhancement_next_due", wraps=enhancement_next_due) as project:
                        service.serve(
                            account_id="account", server_id="server", stop=stop,
                            emit=lambda report: (reports.append(report), stop.set()),
                            clock=lambda: stop.now, flow_ids=(FLOW_ID,),
                        )
                    run_ids = [row[0] for row in state._db.execute("SELECT run_id FROM runs")]
                    self.assertEqual(len(run_ids), 1)
                    run = state.get_run(run_ids[0])
                    self.assertEqual((run.consumed_inputs, run.consumed_actions), (9, 1))
                    self.assertGreater(stop.now - START, 60)
                    self.assertEqual(len(set(heartbeats)), 1)
                    self.assertEqual(run.state, RunState.BLOCKED if lose_fence else RunState.SUCCEEDED)
                    self.assertEqual(reports[0]["status"], "blocked" if lose_fence else "completed")
                    if lose_fence:
                        project.assert_not_called()
                        self.assertIsNone(state.get_flow(FLOW_ID).next_due_at_utc)
                    else:
                        project.assert_called()
                        self.assertEqual(state.get_flow(FLOW_ID).next_due_at_utc, START - START % 86400 + 86400)
                    native_run.assert_called_once()
                    verify.assert_called_once()
                    write_progress.assert_not_called()
                    uses = delivery._resource_dispatch_rows(delivery._read_event_rows(self.runtimes[-1].events))
                    self.assertEqual(len(uses), 1)
                    self.assertIn("enhancement:module:", uses[0]["action_key"])


if __name__ == "__main__":
    unittest.main()
