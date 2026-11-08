from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

import cv2
import numpy as np

from automation_service.registry import NANO_MATERIAL_PRODUCTION_MAX_INPUTS
from safe_action_core import SafetyStore
from scripts import atlas_runtime_startup
from scripts import nano_material_production_bluestacks as route
from scripts import navigation_development_boundary as boundary
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID
from tests.support.environment import requires_tesseract


_STATE_CODE = {"home": 1, "gear_factory": 2, "nanoweapon": 3, "active": 4, "idle": 5, "complete": 6, "unknown": 7}


def _ocr_rows(state: str):
    rows = [
        "Nanoweapon",
        "Material Production",
        "Production Slot 1 of 1",
        "Duration 6 hours",
        "Cost 0",
        "No other costs",
    ]
    if state == "active":
        rows.extend(("Production Active", "Timer 05:59:00"))
    elif state == "idle":
        rows.extend(("Production Idle", "Timer 00:00:00", "Start"))
    elif state == "complete":
        rows.extend(("Production Complete", "Timer 00:00:00", "Claim"))
    elif state == "unknown":
        rows.append("Production State Unknown")
    if state == "home":
        return ["Home", "Build", "Research", "Pit", "Idle"]
    if state == "gear_factory":
        return ["Gear Factory", "Weapons", "Armor", "Factory Level", "Nanoweapon"]
    if state == "nanoweapon":
        return ["Nanoweapon", "Craft Weapon", "Weapon Details", "Available Recipes", "Material Production"]
    return rows


def _fake_tesseract(frame, *, timeout, config):
    state_code = int(frame[0, 0, 0])
    state = next(name for name, code in _STATE_CODE.items() if code == state_code)
    rows = _ocr_rows(state)
    result = {key: [] for key in ("text", "left", "top", "width", "height", "conf", "block_num", "par_num", "line_num")}
    for index, text in enumerate(rows):
        result["text"].append(text)
        result["left"].append(250)
        result["top"].append(100 + index * 32)
        result["width"].append(max(24, len(text) * 8))
        result["height"].append(20)
        result["conf"].append(95)
        result["block_num"].append(1)
        result["par_num"].append(1)
        result["line_num"].append(index + 1)
    return result


@dataclass(frozen=True)
class _Capture:
    frame: np.ndarray
    sha256: str
    path: Path
    captured_monotonic: float
    ordinal: int
    png: bytes = b""


class _Runtime:
    def __init__(self, session_directory: Path, *, state: str, unknown_after_claim: bool = False):
        self.session = session_directory
        self.session_directory = session_directory
        self.state = state
        self.unknown_after_claim = unknown_after_claim
        self.input_count = 0
        self.max_inputs = NANO_MATERIAL_PRODUCTION_MAX_INPUTS
        self.captures: dict[str, _Capture] = {}
        self.actions: list[tuple[str, str]] = []
        self.ordinal = 0

    def capture(self, label: str):
        self.ordinal += 1
        state_code = _STATE_CODE[self.state]
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        frame[0, 0, 0] = state_code
        digest = hashlib.sha256(self.state.encode("ascii")).hexdigest()
        path = self.session / "frames" / f"{self.ordinal:04d}-{label}.png"
        captured = _Capture(frame, digest, path, 100.0 + self.ordinal / 1000.0, self.ordinal)
        self.captures[str(path)] = captured
        return captured

    def measure_foreground_package(self):
        return "com.global.ztmslg"

    def tap(self, _captured, *, target_identity, target_roi, action_key, action_class, consequential):
        self.actions.append((action_class, action_key))
        self.input_count += 1
        if action_class == "CLAIM_NANO_MATERIAL_PRODUCTION":
            self.state = "unknown" if self.unknown_after_claim else "idle"
        elif action_class == "START_NANO_MATERIAL_PRODUCTION":
            self.state = "active"
        elif action_class == "navigation":
            if target_identity == route.GEAR_FACTORY_ID:
                self.state = "gear_factory"
            elif target_identity == "gear-factory:nanoweapon":
                self.state = "nanoweapon"
            elif target_identity == "nanoweapon:material-production-tab":
                self.state = "idle"

    def press_key(self, _captured, *, key, action_key):
        self.actions.append((f"KEY:{key}", action_key))
        self.input_count += 1
        self.state = "home"


class _Session:
    def __init__(self, runtime: _Runtime, owner: str):
        self.runtime = runtime
        self.owner = owner
        self.invocation_id = "nano-smoke-invocation"
        self.session_directory = runtime.session_directory
        self.input_count = 0
        self.max_inputs = NANO_MATERIAL_PRODUCTION_MAX_INPUTS
        self.initial_observation = None

    def observe(self, capture, *, label):
        return capture(label)

    def set_initial_observation(self, value):
        if self.initial_observation is not None:
            raise AssertionError("initial observation may bind only once")
        self.initial_observation = value

    def run_action(self, *, action_class, label, capture, authorize, dispatch, recognize,
                   settled_successor, consequence_class):
        before = capture(f"{label}-before")
        admitted = authorize(before)
        if admitted is False:
            return SimpleNamespace(status="failed", state="unknown", before_sha256=before.sha256, after_sha256="")
        dispatch(before)
        self.input_count += 1
        after = capture(f"{label}-after")
        state = recognize(after)
        settled = settled_successor()
        state = recognize(settled)
        return SimpleNamespace(
            status="completed" if state != "unknown" else "failed",
            state=state,
            before_sha256=before.sha256,
            after_sha256=settled.sha256,
        )


class _NativeContext:
    def __init__(self, root: Path, *, state: str, occurrence_key: str, unknown_after_claim: bool = False):
        self.runtime_profile_id = ACTIVE_RUNTIME_PROFILE_ID
        self.flow_id = route.FLOW_ID
        self.product_id = route.PRODUCT_ID
        self.product_revision = route.PRODUCT_REVISION
        self.occurrence_key = occurrence_key
        self.identity = SimpleNamespace(reset_id="game-day-1", account_id="acct", server_id="server")
        self.owner = "automation-service:nano-material-production"
        self.runtime = _Runtime(root, state=state, unknown_after_claim=unknown_after_claim)
        self.session = _Session(self.runtime, self.owner)
        self.action_store = SafetyStore(root / "action-store.sqlite")
        self.action_store.acquire_lease(self.owner, 1_700_000_000.0, 3600.0)
        self.max_inputs = NANO_MATERIAL_PRODUCTION_MAX_INPUTS
        self.settle_seconds = 0.0
        self._utc = 1_700_000_000.0
        self.runtime_input_lock = None

    def close(self):
        self.action_store.close()

    def checkpoint(self):
        return None

    def validate_identity(self):
        return None

    def utc_clock(self):
        return self._utc

    def monotonic_clock(self):
        return 100.0 + self.runtime.ordinal / 1000.0

    def is_clean_home(self, frame):
        return int(frame[0, 0, 0]) == _STATE_CODE["home"]

    def bind_initial_observation(self, captured):
        self.session.set_initial_observation(SimpleNamespace(frame_sha256=captured.sha256))

    def prepare_startup(self, **_kwargs):
        raise RuntimeError("fake startup recovery is not enabled in these panel-origin smoke cases")

    def accounting(self):
        count = self.session.input_count
        return SimpleNamespace(input_count=count, session_input_count=count, runtime_input_count=self.runtime.input_count,
                               verified=count == self.runtime.input_count)

    def capture_reference(self, path, expected_sha256):
        captured = self.runtime.captures[str(path)]
        if captured.sha256 != expected_sha256:
            raise ValueError("capture hash mismatch")
        reference = SimpleNamespace(
            frame_path=f"frames/{Path(path).name}",
            frame_sha256=expected_sha256,
            observed_utc="2026-11-06T00:00:00Z",
            capture_ordinal=captured.ordinal,
        )
        return captured, reference


class NanoMaterialProductionNativeSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self._ocr_patch = mock.patch.object(route, "tesseract_data", _fake_tesseract)
        self._ocr_patch.start()
        # These are logical slot-state replays, not rendered-tab OCR fixtures.
        self.enterContext(mock.patch.object(
            route, "_nanoweapon_selected_tab",
            side_effect=lambda frame: (
                "Material Production" if int(frame[0, 0, 0]) in {
                    _STATE_CODE["active"], _STATE_CODE["idle"], _STATE_CODE["complete"],
                } else None
            ),
        ))

    def tearDown(self):
        self._ocr_patch.stop()
        self.temp.cleanup()

    def _context(self, *, state, occurrence="NANO-MATERIAL-PRODUCTION-MAINTENANCE:timer:2026-11-06", unknown_after_claim=False):
        return _NativeContext(self.root, state=state, occurrence_key=occurrence, unknown_after_claim=unknown_after_claim)

    def test_active_production_refreshes_due_without_transport(self):
        context = self._context(state="active")
        try:
            result = route.run_material_production_in_context(
                context, occurrence_key=context.occurrence_key, return_home=False,
            )
            self.assertEqual(result["status"], "deferred")
            self.assertEqual(result["production_transport_calls"], 0)
            self.assertEqual(result["committed_action_count"], 0)
            self.assertEqual(result["production_state"], "active")
            self.assertEqual(result["production_duration_seconds"], 21600)
            self.assertEqual(result["active_production_count"], 1)
            self.assertGreater(result["timer_seconds_remaining"], 0)
            self.assertEqual(result["native_occurrence_key"], context.occurrence_key)
            self.assertFalse(result["zero_resource_cost_confirmed"])
            self.assertTrue(result["accounting_verified"])
            self.assertFalse(result["terminal_home_verified"])
            self.assertEqual(context.runtime.input_count, 0)
        finally:
            context.close()

    def test_idle_production_starts_one_zero_cost_batch(self):
        context = self._context(state="idle")
        try:
            result = route.run_material_production_in_context(
                context, occurrence_key=context.occurrence_key, return_home=False,
            )
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["production_transport_calls"], 1)
            self.assertEqual(result["committed_action_count"], 1)
            self.assertEqual(context.runtime.actions[0][0], "START_NANO_MATERIAL_PRODUCTION")
            self.assertTrue(result["zero_resource_cost_confirmed"])
            self.assertTrue(result["accounting_verified"])
        finally:
            context.close()

    def test_completed_production_claims_then_starts_as_two_effects(self):
        context = self._context(state="complete")
        try:
            result = route.run_material_production_in_context(
                context, occurrence_key=context.occurrence_key, return_home=False,
            )
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["production_transport_calls"], 2)
            self.assertEqual(result["committed_action_count"], 2)
            self.assertEqual(
                [kind for kind, _key in context.runtime.actions],
                ["CLAIM_NANO_MATERIAL_PRODUCTION", "START_NANO_MATERIAL_PRODUCTION"],
            )
            self.assertEqual(
                context.runtime.actions[0][1],
                f"{route.PRODUCT_ID}|{context.occurrence_key}|claim",
            )
            self.assertEqual(
                context.runtime.actions[1][1],
                f"{route.PRODUCT_ID}|{context.occurrence_key}|start",
            )
            self.assertEqual(result["production_state"], "active")
            self.assertTrue(result["zero_resource_cost_confirmed"])
        finally:
            context.close()

    def _owned_observation(self, captured, occurrence, *, state):
        return route.MaterialProductionObservation(
            screen_state="NANOWEAPON", selected_nanoweapon=True,
            selected_tab=route.MATERIAL_PRODUCTION_TAB, production_state=state,
            active_production_count=0, completed_batch_count=1 if state == "complete" else 0,
            production_duration_seconds=None, timer_seconds_remaining=None,
            cost_known=state == "complete", cost_type="none" if state == "complete" else "unknown",
            cost_amount=0 if state == "complete" else None, other_costs_known=state == "complete",
            nonzero_other_costs=False, target_identity=route.NANO_MATERIAL_PRODUCTION_TARGET,
            target_roi=route._MATERIAL_COMPLETE_CLAIM_CONTROL, panel_bounds=route._MATERIAL_COMPLETE_PANEL,
            claim_visible=state == "complete", start_enabled=state == "idle",
            target_provenance=route.BLUESTACKS_NATIVE_TARGET_PROVENANCE,
            source_frame_sha256=captured.sha256, evidence_refs=("evidence/owned-frame.png",),
            occurrence_key=occurrence,
        )

    def test_completed_claim_does_not_require_start_quote_or_timer(self):
        context = self._context(state="complete")
        try:
            before = self._owned_observation(context.runtime.capture("complete"), context.occurrence_key, state="complete")
            idle = replace(before, production_state="idle", completed_batch_count=0,
                           claim_visible=False, start_enabled=True, cost_known=False,
                           cost_type="unknown", cost_amount=None, other_costs_known=False,
                           source_frame_sha256="b" * 64)
            route.material_production_claim_spec(before)
            self.assertTrue(route.material_production_claim_postcondition_verified(before, idle))
            with self.assertRaises(ValueError):
                route.material_production_start_spec(idle)
            active = replace(idle, production_state="active", active_production_count=1,
                             start_enabled=False, timer_seconds_remaining=21599,
                             source_frame_sha256="c" * 64)
            self.assertTrue(route.material_production_authorizeable(active))
            self.assertFalse(route.material_production_start_postcondition_verified(idle, active))
            quoted = replace(idle, production_duration_seconds=21600, cost_known=True,
                             cost_type="none", cost_amount=0, other_costs_known=True)
            self.assertTrue(route.material_production_start_postcondition_verified(quoted, active))
            self.assertFalse(route.material_production_authorizeable(replace(active, timer_seconds_remaining=21601)))
        finally:
            context.close()

    def test_confirmed_claim_preserved_when_idle_start_quote_missing(self):
        context = self._context(state="complete")
        def panel(captured, **_kwargs):
            observation = self._owned_observation(captured, context.occurrence_key, state=context.runtime.state)
            return route._PanelRead(observation, observation.target_roi, "recognized")
        try:
            with (
                mock.patch.object(route, "_panel_observation", side_effect=panel),
                mock.patch.object(route, "_prepare_route_source", side_effect=lambda _ctx, current, _key: current),
            ):
                result = route.run_material_production_in_context(
                    context, occurrence_key=context.occurrence_key, return_home=False,
                )
            self.assertEqual(result["reason"], "MATERIAL_PRODUCTION_START_QUOTE_UNKNOWN")
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["committed_action_count"], 1)
            self.assertEqual(result["production_transport_calls"], 1)
            self.assertFalse(result["effect_reconciliation_required"])
            self.assertFalse(result["identical_retry_denied"])
            self.assertEqual([kind for kind, _ in context.runtime.actions], ["CLAIM_NANO_MATERIAL_PRODUCTION"])
            self.assertIsNotNone(result["last_action_evidence"]["after"])
            self.assertTrue(result["zero_resource_cost_confirmed"])
            self.assertEqual(result["production_state_frame"]["frame_sha256"], result["last_action_evidence"]["after"]["frame_sha256"])
        finally:
            context.close()

    def test_actual_completed_profile_requires_material_not_craft_ownership(self):
        context = self._context(state="complete")
        captured = context.runtime.capture("complete")
        body = (
            route._Word("Produces 24-38 material(s) at random. Upgrade Gear", 96, (78, 978, 721, 1003), (1, 1, 1)),
            route._Word("Factory to increase output.", 96, (237, 1003, 560, 1027), (2, 1, 1)),
        )
        claim = (route._Word("Claim", 96, (363, 1200, 438, 1222), (1, 1, 1)),)
        def words(_frame, roi=None, **_kwargs):
            return claim if roi == route._MATERIAL_COMPLETE_CLAIM_CROP else body
        try:
            with mock.patch.object(route, "_ocr_words", side_effect=words):
                with mock.patch.object(route, "_nanoweapon_selected_tab", return_value="Material Production"):
                    observed = route._panel_observation(captured, context=context, occurrence_key=context.occurrence_key)
                self.assertIsNotNone(observed.observation)
                self.assertIsNone(observed.observation.production_duration_seconds)
                self.assertIsNone(observed.observation.timer_seconds_remaining)
                self.assertEqual(observed.observation.completed_batch_count, 1)
                self.assertEqual(observed.observation.target_roi, route._MATERIAL_COMPLETE_CLAIM_CONTROL)
                with mock.patch.object(route, "_nanoweapon_selected_tab", return_value="Craft Weapon"):
                    refused = route._panel_observation(captured, context=context, occurrence_key=context.occurrence_key)
                self.assertIsNone(refused.observation)
        finally:
            context.close()

    def test_opaque_occurrence_with_pipe_is_preserved_exactly(self):
        occurrence = "NANO-MATERIAL-PRODUCTION-MAINTENANCE:timer:2026-11-06|basis"
        context = self._context(state="idle", occurrence=occurrence)
        try:
            result = route.run_material_production_in_context(
                context, occurrence_key=occurrence, return_home=False,
            )
            self.assertEqual(result["status"], "completed")
            self.assertEqual(
                context.runtime.actions[0][1],
                f"{route.PRODUCT_ID}|{occurrence}|start",
            )
            self.assertEqual(result["native_occurrence_key"], occurrence)
        finally:
            context.close()


    def test_unknown_claim_successor_stops_before_start(self):
        context = self._context(state="complete", unknown_after_claim=True)
        try:
            result = route.run_material_production_in_context(
                context, occurrence_key=context.occurrence_key, return_home=True,
            )
            self.assertEqual(result["status"], "unresolved")
            self.assertEqual(result["production_transport_calls"], 1)
            self.assertEqual(result["attempted_action_count"], 1)
            self.assertTrue(result["attempted_action_count_known"])
            self.assertFalse(result["action_evidence_required"])
            self.assertFalse(result["terminal_home_verified"])
            evidence = result["last_action_evidence"]
            for phase in ("before", "after"):
                frame = evidence[phase]
                self.assertTrue(frame["frame_path"])
                self.assertEqual(len(frame["frame_sha256"]), 64)
                self.assertTrue(frame["observed_utc"])
                self.assertGreater(frame["capture_ordinal"], 0)
            self.assertGreater(
                evidence["after"]["capture_ordinal"],
                evidence["before"]["capture_ordinal"],
            )
            self.assertEqual(result["committed_action_count"], 0)
            self.assertEqual(result["input_count"], 1)
            self.assertEqual(result["session_input_count"], 1)
            self.assertEqual(result["runtime_input_count"], 1)
            self.assertTrue(result["accounting_verified"])
            action_row = context.action_store.get_action_by_key(
                f"{route.PRODUCT_ID}|{context.occurrence_key}|claim"
            )
            self.assertIsNotNone(action_row)
            self.assertEqual(action_row["final_status"], "unresolved")
            self.assertTrue(result["effect_reconciliation_required"])
            self.assertTrue(result["identical_retry_denied"])
            self.assertEqual(
                [kind for kind, _key in context.runtime.actions],
                ["CLAIM_NANO_MATERIAL_PRODUCTION"],
            )
            self.assertFalse(result["zero_resource_cost_confirmed"])
            context.runtime.state = "complete"
            retried = route.run_material_production_in_context(
                context, occurrence_key=context.occurrence_key, return_home=False,
            )
            self.assertEqual(retried["status"], "blocked")
            self.assertEqual(retried["production_transport_calls"], 0)
            self.assertEqual(retried["committed_action_count"], 0)
            self.assertEqual(len(context.runtime.actions), 1)
        finally:
            context.close()

    def test_duplicate_start_key_and_active_restart_do_not_replay_effect(self):
        context = self._context(state="idle")
        try:
            first = route.run_material_production_in_context(
                context, occurrence_key=context.occurrence_key, return_home=False,
            )
            self.assertEqual(first["production_transport_calls"], 1)
            context.runtime.state = "idle"
            duplicate = route.run_material_production_in_context(
                context, occurrence_key=context.occurrence_key, return_home=False,
            )
            self.assertEqual(duplicate["status"], "blocked")
            self.assertEqual(duplicate["production_transport_calls"], 0)
            self.assertEqual(len(context.runtime.actions), 1)
            context.runtime.state = "active"
            restarted = route.run_material_production_in_context(
                context, occurrence_key=context.occurrence_key, return_home=False,
            )
            self.assertEqual(restarted["status"], "deferred")
            self.assertEqual(restarted["production_transport_calls"], 0)
            self.assertEqual(len(context.runtime.actions), 1)
        finally:
            context.close()




@dataclass(frozen=True)
class _PixelCapture(CapturedNativeFrame):
    ordinal: int = 0


class _PixelHomeRuntime(_Runtime):
    """Native Home pixels and synthetic route panels over a device-free transport."""

    execute = True
    in_flight_action = None
    runner = SimpleNamespace(executable="fake-adb-not-executed", serial="emulator-5554")

    def __init__(self, directory, *, zoom_source, zoom_result="canonical", panel_state="idle"):
        super().__init__(directory, state="zoomed_home")
        self.zoom_source = zoom_source
        self.canonical_source = Path(__file__).resolve().parents[1] / "tasks/assets/home_atlas/bluestacks/800x1280/tiles/viewport-010.png"
        self.zoom_result = zoom_result
        self.panel_state = panel_state
        self.events = directory / "fake-native-events.jsonl"
        self.zoom_calls = 0
        self.targets = []

    def capture(self, label):
        # Native capture is blocking. Model a genuine later capture even on
        # Windows' coarse monotonic clock; never rewrite a policy timestamp.
        time.sleep(0.02)
        self.ordinal += 1
        path = self.session / "frames" / f"{self.ordinal:04d}-{label}.png"
        if self.state in {"home", "zoomed_home"}:
            source = self.zoom_source if self.state == "zoomed_home" else self.canonical_source
            payload = source.read_bytes()
            frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
            digest = hashlib.sha256(payload).hexdigest()
        else:
            payload = b""
            frame = np.zeros((1280, 800, 3), dtype=np.uint8)
            frame[0, 0, 0] = _STATE_CODE[self.state]
            digest = hashlib.sha256(self.state.encode("ascii")).hexdigest()
        captured = _PixelCapture(frame, payload, digest, time.monotonic(), path, self.ordinal)
        self.captures[str(path)] = captured
        return captured

    def measure_device_state(self):
        return "device"

    def dispatch_external_zoom(self, source, *, action_key, transport):
        if self.input_count >= self.max_inputs:
            raise RuntimeError("native input budget exhausted")
        transport()
        self.zoom_calls += 1
        self.input_count += 1
        self.actions.append(("ZOOM", action_key))
        if self.zoom_result == "canonical":
            self.state = "home"
        elif self.zoom_result == "unknown":
            self.state = "unknown"

    def zoom_out(self, *args, **kwargs):
        raise AssertionError("sequential zoom transport must never be used")

    def tap(self, captured, **kwargs):
        self.targets.append(kwargs["target_identity"])
        super().tap(captured, **kwargs)
        if kwargs["target_identity"] == "nanoweapon:material-production-tab":
            self.state = self.panel_state


class _PixelZoomTransport:
    def __init__(self, **kwargs):
        self.calls = 0

    def zoom_out_once(self):
        self.calls += 1


class NanoMaterialProductionPixelEntryTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]
    ZOOM_SOURCE = ROOT / "tests/fixtures/home_base/native-home-bio-zoomed-20261029.png"
    ACTUAL_SOURCE = ROOT / "tests/fixtures/home_base/nano-material-production-home-20261108.png"

    def pixel_context(self, directory, *, source=None, zoom_result="canonical", panel_state="idle"):
        """Real DevelopmentSession; only device pixels/transport and panel OCR are replayed."""
        root = Path(directory)
        context = _NativeContext(root, state="idle", occurrence_key="nano-production-native-pixel-replay")
        stack = ExitStack()
        stack.enter_context(mock.patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"))
        session = stack.enter_context(boundary.DevelopmentSession(
            owner=context.owner,
            invocation_id="nano-production-native-pixel-replay",
            session_directory=root / "native",
            max_inputs=NANO_MATERIAL_PRODUCTION_MAX_INPUTS,
        ))
        context.runtime = _PixelHomeRuntime(
            root / "native", zoom_source=source or self.ZOOM_SOURCE,
            zoom_result=zoom_result, panel_state=panel_state,
        )
        context.session = session
        context.is_clean_home = route.is_clean_home_frame
        context.monotonic_clock = time.monotonic
        context.bind_initial_observation = lambda captured: session.set_initial_observation(
            {"frame_sha256": captured.sha256},
        )
        close_store = context.close

        def close():
            try:
                stack.close()
            finally:
                close_store()

        context.close = close
        return context

    def return_to_zoomed_home(self, context, zoom_source):
        press_key = context.runtime.press_key

        def press(captured, **kwargs):
            press_key(captured, **kwargs)
            context.runtime.state = "zoomed_home"
            context.runtime.zoom_source = zoom_source

        context.runtime.press_key = press

    def pixel_patches(self):
        stack = ExitStack()
        stack.enter_context(mock.patch.object(
            atlas_runtime_startup, "ScrcpyMotionEventZoomTransport", _PixelZoomTransport,
        ))
        real_words = route._ocr_words
        def panel_words(frame):
            # Synthetic panel OCR only; Home recognition, zoom classification,
            # localization, mapped binding and safety policy remain production.
            if np.count_nonzero(frame) != 1:
                return ()
            return real_words(frame)
        stack.enter_context(mock.patch.object(route, "tesseract_data", _fake_tesseract))
        stack.enter_context(mock.patch.object(route, "_ocr_words", side_effect=panel_words))
        return stack

    @requires_tesseract
    def test_native_home_zoom_entry_mapped_factory_and_terminal_home(self):
        for panel_state, effects in (("active", 0), ("idle", 1), ("complete", 2)):
            with self.subTest(panel_state=panel_state), tempfile.TemporaryDirectory() as directory:
                context = self.pixel_context(directory, panel_state=panel_state)
                try:
                    with self.pixel_patches():
                        result = route.run_material_production_in_context(
                            context, occurrence_key=context.occurrence_key, return_home=True,
                        )
                    self.assertEqual(result["status"], "deferred" if not effects else "completed")
                    self.assertEqual(context.runtime.zoom_calls, 1)
                    self.assertEqual(context.runtime.targets[:3], [
                        route.GEAR_FACTORY_ID, "gear-factory:nanoweapon",
                        "nanoweapon:material-production-tab",
                    ])
                    self.assertEqual(result["production_transport_calls"], effects)
                    self.assertTrue(result["terminal_home_verified"])
                    self.assertTrue(result["accounting_verified"])
                    self.assertLessEqual(result["input_count"], route.MAX_INPUTS)
                    self.assertEqual(context.session.input_count, context.runtime.input_count)
                finally:
                    context.close()

    @requires_tesseract
    def test_retained_actual_failure_source_normalizes_before_atlas_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            context = self.pixel_context(directory, source=self.ACTUAL_SOURCE, panel_state="active")
            try:
                with self.pixel_patches():
                    result = route.run_material_production_in_context(
                        context, occurrence_key=context.occurrence_key, return_home=True,
                    )
                self.assertEqual(result["status"], "deferred")
                self.assertEqual(context.runtime.zoom_calls, 1)
                self.assertTrue(result["terminal_home_verified"])
                self.assertTrue(result["accounting_verified"])
            finally:
                context.close()

    @requires_tesseract
    def test_unchanged_unknown_or_exhausted_zoom_never_taps_factory(self):
        for successor in ("unchanged", "unknown", "budget"):
            with self.subTest(successor=successor), tempfile.TemporaryDirectory() as directory:
                context = self.pixel_context(directory, zoom_result=successor)
                try:
                    if successor == "budget":
                        context.runtime.input_count = context.runtime.max_inputs
                        context.session.input_count = context.runtime.max_inputs
                    with self.pixel_patches():
                        result = route.run_material_production_in_context(
                            context, occurrence_key=context.occurrence_key, return_home=True,
                        )
                    self.assertEqual(result["status"], "blocked")
                    self.assertFalse(result["terminal_home_verified"])
                    self.assertEqual(result["production_transport_calls"], 0)
                    self.assertEqual(context.runtime.targets, [])
                    self.assertEqual(context.runtime.zoom_calls, 0 if successor == "budget" else 1)
                    self.assertTrue(result["accounting_verified"])
                finally:
                    context.close()

    @requires_tesseract
    def test_panel_return_to_zoomed_home_is_normalized_before_terminal_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            context = self.pixel_context(directory, panel_state="active")
            context.runtime.state = "active"
            self.return_to_zoomed_home(context, self.ZOOM_SOURCE)
            try:
                with self.pixel_patches():
                    result = route.run_material_production_in_context(
                        context, occurrence_key=context.occurrence_key, return_home=True,
                    )
                self.assertEqual(result["status"], "deferred")
                self.assertEqual(context.runtime.zoom_calls, 1)
                self.assertEqual(result["production_transport_calls"], 0)
                self.assertTrue(result["terminal_home_verified"])
                self.assertTrue(result["accounting_verified"])
                self.assertEqual((context.runtime.input_count, context.session.input_count), (2, 2))
            finally:
                context.close()

    @requires_tesseract
    def test_entry_and_terminal_zooms_interleave_with_route_inputs_in_one_session(self):
        with tempfile.TemporaryDirectory() as directory:
            context = self.pixel_context(directory, panel_state="active")
            self.return_to_zoomed_home(context, self.ACTUAL_SOURCE)
            try:
                with self.pixel_patches():
                    result = route.run_material_production_in_context(
                        context, occurrence_key=context.occurrence_key, return_home=True,
                    )
                self.assertEqual(result["status"], "deferred")
                self.assertTrue(result["terminal_home_verified"])
                self.assertTrue(result["accounting_verified"])
                self.assertEqual(context.runtime.zoom_calls, 2)
                self.assertEqual([kind for kind, _key in context.runtime.actions], [
                    "ZOOM", "navigation", "navigation", "navigation", "KEY:Escape", "ZOOM",
                ])
                self.assertEqual((context.runtime.input_count, context.session.input_count), (6, 6))
                labels = [row["label"] for row in context.session.actions]
                self.assertEqual(len(labels), 6)
                self.assertTrue(labels[0].startswith("home-atlas-startup-zoom-01-"))
                self.assertTrue(labels[-1].startswith("home-atlas-startup-zoom-01-"))
                self.assertNotEqual(labels[0], labels[-1])
                self.assertEqual({row["status"] for row in context.session.actions}, {"completed"})
            finally:
                context.close()

    @requires_tesseract
    def test_return_to_already_zoomed_source_gets_no_identical_zoom(self):
        with tempfile.TemporaryDirectory() as directory:
            context = self.pixel_context(directory, panel_state="active")
            self.return_to_zoomed_home(context, self.ZOOM_SOURCE)
            try:
                with self.pixel_patches():
                    result = route.run_material_production_in_context(
                        context, occurrence_key=context.occurrence_key, return_home=True,
                    )
                self.assertFalse(result["terminal_home_verified"])
                self.assertEqual(result["production_transport_calls"], 0)
                self.assertEqual(context.runtime.zoom_calls, 1)
                self.assertTrue(result["accounting_verified"])
                self.assertEqual((context.runtime.input_count, context.session.input_count), (5, 5))
            finally:
                context.close()

if __name__ == "__main__":
    unittest.main()
