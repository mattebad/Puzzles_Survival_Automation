from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

from automation_service.registry import (
    NANO_MATERIAL_PRODUCTION_FLOW_ID,
    NANO_MATERIAL_PRODUCTION_MAX_INPUTS,
    NANO_MATERIAL_PRODUCTION_PRODUCT_ID,
    NANO_MATERIAL_PRODUCTION_PRODUCT_REVISION,
    NANO_MATERIAL_PRODUCTION_PROFILE_ID,
)
from safe_action_core import SafetyStore
from scripts import nano_material_production_bluestacks as route
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID


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
        return captured.frame, reference


class NanoMaterialProductionNativeSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self._ocr_patch = mock.patch.object(route, "tesseract_data", _fake_tesseract)
        self._ocr_patch.start()

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
            self.assertTrue(result["zero_resource_cost_confirmed"])
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

    def test_home_atlas_navigation_binds_gear_factory_and_canonical_tab(self):
        context = self._context(state="home")
        context.session.initial_observation = SimpleNamespace(frame_sha256="already-bound")

        atlas = route._load_atlas(route.DEFAULT_ATLAS)

        class _Localizer:
            def __init__(self, _atlas, _path):
                pass

            @staticmethod
            def localize(_frame):
                return SimpleNamespace(recognized=True, stale=False, overlay=False)

        def bind_home(frame, _localization, _building, *, home_is_clean):
            return SimpleNamespace(
                building_id=route.GEAR_FACTORY_ID,
                frame_sha256=route.frame_digest(frame),
                target_roi=(300, 500, 400, 560),
                overlay_intersects=False,
                ambiguous_overlap=False,
                semantic_evidence=("atlas-localized-gear-factory",),
            )

        with (
            mock.patch.object(route, "_load_atlas", return_value=atlas),
            mock.patch.object(route, "BlueStacksHomeLocalizer", _Localizer),
            mock.patch.object(route, "bind_visible_building", side_effect=bind_home),
            mock.patch.object(
                route,
                "is_clean_home_frame",
                side_effect=lambda frame: int(frame[0, 0, 0]) == _STATE_CODE["home"],
            ),
        ):
            try:
                result = route.run_material_production_in_context(
                    context, occurrence_key=context.occurrence_key, return_home=False,
                )
                self.assertEqual(result["status"], "completed")
                navigation = [
                    (kind, key) for kind, key in context.runtime.actions
                    if kind == "navigation"
                ]
                self.assertEqual(len(navigation), 3)
                self.assertTrue(all(context.action_store.action_key_exists(key) for _, key in navigation))
                self.assertEqual(context.runtime.state, "active")
                self.assertTrue(result["accounting_verified"])
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
            self.assertTrue(route.validate_nano_material_production_native_result(result))
            invalid_effect_evidence = (
                {"attempted_action_count": None, "attempted_action_count_known": False},
                {"action_evidence_required": True},
                {"last_action_evidence": {"before": evidence["before"]}},
            )
            for changes in invalid_effect_evidence:
                with self.subTest(changes=changes):
                    self.assertFalse(
                        route.validate_nano_material_production_native_result(
                            dict(result, **changes)
                        )
                    )
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

    def test_fixed_native_binding_runs_real_driver_and_returns_home_evidence(self):
        binding = {}
        native = route.create_service_binding(lambda **values: binding.update(values) or values)
        self.assertEqual(native["flow_id"], NANO_MATERIAL_PRODUCTION_FLOW_ID)
        self.assertEqual(native["product_id"], NANO_MATERIAL_PRODUCTION_PRODUCT_ID)
        self.assertEqual(native["product_revision"], NANO_MATERIAL_PRODUCTION_PRODUCT_REVISION)
        self.assertEqual(native["runtime_profile_id"], NANO_MATERIAL_PRODUCTION_PROFILE_ID)
        self.assertEqual(native["max_inputs"], NANO_MATERIAL_PRODUCTION_MAX_INPUTS)
        self.assertEqual(native["max_actions"], 2)
        factory_store = native["action_store_factory"](self.root / "factory-store.sqlite")
        try:
            self.assertIsInstance(factory_store, SafetyStore)
        finally:
            factory_store.close()
        context = self._context(state="active", occurrence="service-driver")
        class _HomeLocalizer:
            def __init__(self, _atlas, _path):
                pass

            @staticmethod
            def localize(_frame):
                return SimpleNamespace(recognized=True, stale=False, overlay=False)

        try:
            with (
                mock.patch.object(route, "_load_atlas", return_value=SimpleNamespace()),
                mock.patch.object(route, "BlueStacksHomeLocalizer", _HomeLocalizer),
            ):
                result = binding["driver"](context, {})
            self.assertEqual(result["status"], "deferred")
            self.assertTrue(result["terminal_home_verified"])
            self.assertEqual(result["terminal_home_state"], "HOME_BASE")
            self.assertTrue(result["accounting_verified"])
            self.assertEqual(result["native_occurrence_key"], context.occurrence_key)
            self.assertTrue(binding["validator"](result))
        finally:
            context.close()

    def test_native_validator_requires_retained_production_frame_and_exact_identity(self):
        context = self._context(state="active")

        class _HomeLocalizer:
            def __init__(self, _atlas, _path):
                pass

            @staticmethod
            def localize(_frame):
                return SimpleNamespace(recognized=True, stale=False, overlay=False)

        try:
            with (
                mock.patch.object(route, "_load_atlas", return_value=SimpleNamespace()),
                mock.patch.object(route, "BlueStacksHomeLocalizer", _HomeLocalizer),
            ):
                result = route.run_material_production_in_context(
                    context,
                    occurrence_key=context.occurrence_key,
                    return_home=True,
                )
            self.assertTrue(route.validate_nano_material_production_native_result(result))
            invalid = (
                {"production_occurrence_key": "different"},
                {"production_target_identity": "different"},
                {"production_state_frame": {**result["production_state_frame"], "frame_path": ""}},
                {"production_state_frame": {**result["production_state_frame"], "observed_utc": ""}},
                {"production_state_frame": {**result["production_state_frame"], "capture_ordinal": True}},
                {"next_eligible_at": float("nan")},
            )
            for changes in invalid:
                with self.subTest(changes=changes):
                    self.assertFalse(
                        route.validate_nano_material_production_native_result(
                            dict(result, **changes)
                        )
                    )
        finally:
            context.close()


if __name__ == "__main__":
    unittest.main()
