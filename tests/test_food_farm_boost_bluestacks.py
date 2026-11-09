from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import unquote

import cv2
import numpy as np

from scripts import food_farm_boost_bluestacks as route
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID
from tasks.resource_boost_disabled import FoodFarmBoostChoice, food_farm_boost_decision
from automation_service.native_execution import NativeRouteRequest
from safe_action_core import SafetyStore
from scripts import base_route_native_runtime as native_boundary
from scripts import navigation_development_boundary as ownership
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from tasks.runtime_identity import BLUESTACKS_ADB, BLUESTACKS_SERIAL, FIXED_RUNTIME_SCOPE
from tasks.scheduler_task_result import SchedulerIdentity
from tests.support.local_captures import require_capture, requires_local_captures


@dataclass(frozen=True)
class FakeCapture:
    frame: np.ndarray
    sha256: str
    path: Path
    captured_monotonic: float = 10.0



def _recognized_localizer():
    return SimpleNamespace(localize=lambda _frame: SimpleNamespace(
        recognized=True, stale=False, overlay=False,
    ))

class _FarmReplayRuntime:
    """Synthetic transport only; policy, session, lock and journal remain real."""

    def __init__(self, directory, *, apply_collection, change_before_dispatch=False):
        self.session = directory / "replay"
        self.session.mkdir(parents=True)
        self.input_count = 0
        self.max_inputs = route.MAX_INPUTS
        self.apply_collection = apply_collection
        self.state = 0
        self.change_before_dispatch = change_before_dispatch
        self.ordinal = 0
        self.checkpoint = lambda: None

    def capture(self, label):
        self.checkpoint()
        self.ordinal += 1
        if self.change_before_dispatch and label == "food-farm-action-pre-dispatch":
            self.state = 2
        frame = np.full((1280, 800, 3), 40 + self.state, dtype=np.uint8)
        ok, encoded = cv2.imencode(".png", frame)
        if not ok:
            raise AssertionError("replay PNG encoding failed")
        png = encoded.tobytes()
        path = self.session / f"{self.ordinal}-{label}.png"
        path.write_bytes(png)
        return CapturedNativeFrame(frame, png, hashlib.sha256(png).hexdigest(),
                                   10.0 + self.ordinal / 100, path)

    def measure_device_state(self):
        return "device"

    def measure_foreground_package(self):
        return "com.global.ztmslg"

    def tap(self, before, *, consequential, action_class, **_kwargs):
        if consequential is not True or action_class != "collect_food_farm_resources":
            raise AssertionError("only one replay collection input is supported")
        self.input_count += 1
        if self.apply_collection:
            self.state = 1
        else:
            self.state = 3


class NativeFoodFarmBoostTests(unittest.TestCase):
    def test_fixed_factory_retains_optional_collection_and_unknown_fencing_across_restart(self):
        identity = SchedulerIdentity("account", "server", "scheduler-reset", route.PRODUCT_ID)
        farm_id = "home.building.farm.02"
        for scenario in ("confirmed", "unobserved", "unknown", "changed"):
            apply_collection = scenario in {"confirmed", "unobserved"}
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                database = root / "actions.sqlite3"
                runtimes = []

                def connect(**kwargs):
                    runtime = _FarmReplayRuntime(
                        kwargs["output_directory"], apply_collection=apply_collection,
                        change_before_dispatch=scenario == "changed",
                    )
                    runtimes.append(runtime)
                    return runtime

                def bind(frame, *_args, **_kwargs):
                    ok, encoded = cv2.imencode(".png", frame)
                    if not ok:
                        raise AssertionError("replay binding PNG encoding failed")
                    return route.FarmBinding(
                        farm_id, (500, 500, 550, 550),
                        hashlib.sha256(encoded.tobytes()).hexdigest(), ("synthetic:atlas",),
                    )

                def food(frame):
                    return None if scenario == "unobserved" else "110" if int(frame[0, 0, 0]) == 41 else "100"

                with patch.object(ownership, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"), \
                     patch.object(native_boundary, "open_canonical_action_store",
                                  side_effect=lambda: SafetyStore(database)), \
                     patch.object(native_boundary.LocalBlueStacksRuntime, "connect", side_effect=connect), \
                     patch.object(route, "is_clean_home_frame",
                                  side_effect=lambda frame: int(frame[0, 0, 0]) in {40, 41}), \
                     patch.object(route, "load_home_atlas", return_value=object()), \
                     patch.object(route, "BlueStacksHomeLocalizer",
                                  side_effect=lambda *_args: _recognized_localizer()), \
                     patch.object(route, "bind_reachable_farm", side_effect=bind), \
                     patch.object(route, "_home_food_reading", side_effect=food), \
                     patch.object(route, "_open_food_farm_radial",
                                  return_value={"status": "blocked", "reason": "replay ends at radial"}), \
                     ownership.RuntimeInputLock(owner="automation-service", invocation_id="farm-replay") as lock:
                    binding = route.create_service_binding(native_boundary.make_native_route_binding)

                    def request(occurrence):
                        return NativeRouteRequest(
                            flow_id=route.FLOW_ID, product_id=route.PRODUCT_ID,
                            product_revision=route.PRODUCT_REVISION,
                            runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID, identity=identity,
                            previous_reset_id=None, occurrence_key=occurrence,
                            checkpoint=lambda: None, validate_identity=lambda: None,
                            runtime_input_lock=lock, adb=str(BLUESTACKS_ADB), serial=BLUESTACKS_SERIAL,
                            output_directory=root / "sessions", max_inputs=route.MAX_INPUTS,
                            max_actions=route.MAX_ACTIONS, settle_seconds=0.0,
                            utc_clock=lambda: 100.0, monotonic_clock=lambda: 20.0,
                        )

                    first = binding.run(request("first-opaque-occurrence"))
                    self.assertTrue(first.execution_verified, first.failure)
                    if scenario == "changed":
                        self.assertEqual(first.input_count, 0)
                        self.assertEqual(first.native_result["collection_count"], 0)
                        self.assertEqual(first.native_result["boost_transport_calls"], 0)
                        self.assertFalse(first.native_result["effect_reconciliation_required"])
                        self.assertEqual(sum(runtime.input_count for runtime in runtimes), 0)
                        store = SafetyStore(database)
                        try:
                            self.assertFalse(store.has_action_block())
                        finally:
                            store.close()
                        continue
                    self.assertEqual(first.input_count, 1)
                    result = first.native_result
                    self.assertEqual(result["collection_transport_calls"], 1)
                    self.assertEqual(result["collection_count"], int(scenario == "confirmed"))
                    self.assertEqual(result["boost_transport_calls"], 0)
                    self.assertEqual(result["effect_reconciliation_required"], not apply_collection)
                    key = route.food_farm_boost_daily_action_key(
                        runtime_scope=FIXED_RUNTIME_SCOPE, account_id=identity.account_id,
                        server_id=identity.server_id, reset_id=identity.reset_id,
                        phase="collection", collection_occurrence_id="1",
                    )
                    self.assertEqual(result["collection_action_key"], key)
                    second = binding.run(request("second-opaque-occurrence"))
                    self.assertEqual(second.input_count, 0)
                    if apply_collection:
                        self.assertTrue(second.execution_verified, second.failure)
                        self.assertEqual(second.native_result["collection_count"], int(scenario == "confirmed"))
                        self.assertEqual(second.native_result["collection_transport_calls"], 0)
                        self.assertEqual(result["collection_food_after"], None if scenario == "unobserved" else "110")
                    else:
                        self.assertFalse(second.execution_verified)
                    self.assertEqual(sum(runtime.input_count for runtime in runtimes), 1)
                store = SafetyStore(database)
                try:
                    row = store.get_action_by_key(key)
                    self.assertEqual(row["final_status"], "confirmed" if apply_collection else "unresolved")
                    self.assertEqual(store.has_action_block(), not apply_collection)
                finally:
                    store.close()

    def _panel_tokens(self):
        return (
            route.NativeTextToken("Farm", 99, (350, 500, 400, 525)),
            route.NativeTextToken("Boost", 99, (350, 600, 400, 625)),
            route.NativeTextToken("Food", 99, (50, 200, 90, 225)),
            route.NativeTextToken("Output", 99, (92, 200, 150, 225)),
            route.NativeTextToken("Food", 99, (50, 240, 90, 265)),
            route.NativeTextToken("Cap", 99, (92, 240, 130, 265)),
            route.NativeTextToken("Boost", 99, (100, 900, 150, 925)),
            route.NativeTextToken("Output", 99, (155, 900, 210, 925)),
            route.NativeTextToken("1-day", 99, (215, 900, 260, 925)),
            route.NativeTextToken("Boost", 99, (510, 1100, 560, 1125)),
            route.NativeTextToken("Output", 99, (565, 1100, 620, 1125)),
            route.NativeTextToken("1-day", 99, (625, 1100, 665, 1125)),
            route.NativeTextToken("x1", 99, (670, 1120, 690, 1140)),
            route.NativeTextToken("500", 99, (600, 40, 635, 65)),
        )

    def test_current_farm_timer_requires_unambiguous_timer_and_removed_application_controls(self):
        captured = FakeCapture(np.zeros((1280, 800, 3), dtype=np.uint8),
                               "a" * 64, Path("active-farm.png"))
        heading = tuple(token for token in self._panel_tokens() if token.roi[1] < 900)
        timer = route.NativeTextToken("Boosting 23:59:23", 99, (200, 1100, 500, 1130))
        valid_tokens = heading + (timer,)
        with patch.object(route, "_generic_overlay", return_value=False):
            with patch.object(route, "_ocr_tokens", return_value=valid_tokens):
                panel = route.observe_food_farm_boost_panel(
                    captured, farm_identity="home.building.farm.02",
                    evidence_ref="evidence/active-farm.png",
                )
                self.assertIsNotNone(panel)
                self.assertEqual(food_farm_boost_decision(panel.observation).choice,
                                 FoodFarmBoostChoice.ALREADY_ACTIVE)
                self.assertEqual(panel.observation.active_remaining_seconds, 86_363)
            negatives = (
                tuple(token for token in valid_tokens if token.text != "Farm"),
                valid_tokens + (timer,),
                self._panel_tokens() + (timer,),
                heading + (route.NativeTextToken("Boosting 23:99:23", 99, timer.roi),),
            )
            for tokens in negatives:
                with self.subTest(tokens=tokens), patch.object(route, "_ocr_tokens", return_value=tokens):
                    self.assertIsNone(route.observe_food_farm_boost_panel(
                        captured, farm_identity="home.building.farm.02",
                        evidence_ref="evidence/active-farm.png",
                    ))

    def test_visible_button_label_does_not_become_inventory_identity_or_count(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        captured = FakeCapture(frame, "a" * 64, Path("food-farm-panel.png"))
        with patch.object(route, "_ocr_tokens", return_value=self._panel_tokens()), \
             patch.object(route, "_generic_overlay", return_value=False):
            panel = route.observe_food_farm_boost_panel(
                captured, farm_identity="home.building.farm.02",
                evidence_ref="evidence/food-farm-panel.png",
            )
        self.assertIsNotNone(panel)
        observation = panel.observation
        self.assertTrue(observation.option_item_visible)
        self.assertIn("Boost", observation.option_item_name)
        self.assertNotEqual(observation.option_item_name, "Food Output Boost (1-day)")
        self.assertEqual(observation.option_item_cost, 1)
        self.assertFalse(observation.inventory_observed)
        self.assertIsNone(observation.inventory_item_name)
        self.assertIsNone(observation.inventory_item_count)
        self.assertEqual(food_farm_boost_decision(observation).choice, FoodFarmBoostChoice.BLOCKED)

    def test_option_duration_is_bound_to_its_own_control_row(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        captured = FakeCapture(frame, "6" * 64, Path("food-farm-mismatched-options.png"))
        tokens = []
        for token in self._panel_tokens():
            x0, y0, x1, y1 = token.roi
            text = token.text
            if x0 < 400 and y0 >= 800:
                y0, y1 = y0 + 200, y1 + 200
            if x0 >= 600 and text == "1-day":
                text = "1-hour"
            tokens.append(route.NativeTextToken(text, token.confidence, (x0, y0, x1, y1)))
        with patch.object(route, "_ocr_tokens", return_value=tuple(tokens)), \
             patch.object(route, "_generic_overlay", return_value=False):
            panel = route.observe_food_farm_boost_panel(
                captured, farm_identity="home.building.farm.02",
                evidence_ref="evidence/food-farm-mismatched-options.png",
            )
        self.assertIsNotNone(panel)
        self.assertEqual(panel.observation.option_duration_seconds, 3_600)
        self.assertEqual(panel.observation.diamond_duration_seconds, 86_400)

    def test_native_observation_adapter_keeps_missing_inventory_and_direct_purchase_unknown(self):
        observation = route._food_farm_observation(
            farm_identity="home.building.farm.03",
            active_remaining_seconds=None,
            option_duration_seconds=86400,
            option_item_name="Boost Output (1 day)",
            option_item_cost=1,
            option_item_visible=True,
            inventory_item_name=None,
            inventory_item_count=None,
            inventory_observed=False,
            diamond_option_visible=True,
            diamond_item_name="Boost Output (1 day)",
            diamond_duration_seconds=86400,
            diamond_cost=52,
            diamond_balance=500,
            diamond_direct_action_observed=False,
            overlay_state="none",
            source_frame_sha256="b" * 64,
            evidence_refs=("evidence/panel.png",),
            runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        )
        self.assertFalse(observation.diamond_offer_actionable)
        self.assertFalse(observation.inventory_observed)
        self.assertEqual(food_farm_boost_decision(observation).choice, FoodFarmBoostChoice.BLOCKED)

    def test_usable_matching_item_wins_without_a_total_inventory_and_unknown_never_buys(self):
        observation = route._food_farm_observation(
            farm_identity="home.building.farm.02", active_remaining_seconds=None,
            option_duration_seconds=86_400, option_item_name="Boost output (1-day)",
            option_item_cost=1, option_item_visible=True,
            option_item_usable=True, inventory_item_name=None, inventory_item_count=None,
            inventory_observed=False, diamond_option_visible=True,
            diamond_item_name="Boost output (1-day)", diamond_duration_seconds=86_400,
            diamond_cost=48, diamond_balance=500, diamond_direct_action_observed=True,
            overlay_state="none", source_frame_sha256="a" * 64,
            evidence_refs=("evidence/current-farm.png",), runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID)
        self.assertEqual(food_farm_boost_decision(observation).choice, FoodFarmBoostChoice.OWNED_ITEM)
        self.assertIsNone(observation.inventory_item_count)
        with patch.object(route, "_dispatch_canonical_action", return_value={
                "status": "blocked", "reason": "dispatch boundary reached", "transport_calls": 0,
                "effect_reconciliation_required": False}) as dispatch:
            self._run_from_confirmed_collection(observation, occurrence_key="opaque-owned-item")
        facts = dispatch.call_args.kwargs["semantic_preconditions"]
        label = next(fact.split(":", 1)[1] for fact in facts
            if fact.startswith("exact_current_food_farm_item_name:"))
        self.assertFalse(any(character.isspace() for character in label))
        self.assertEqual(unquote(label), observation.option_item_name)
        self.assertEqual(food_farm_boost_decision(replace(observation, option_item_usable=None)).choice,
                         FoodFarmBoostChoice.BLOCKED)
        eligible = replace(observation, option_item_usable=False)
        self.assertEqual(food_farm_boost_decision(eligible).choice, FoodFarmBoostChoice.DIAMONDS)
        for unsafe in (replace(eligible, diamond_cost=49), replace(eligible, diamond_balance=47),
                       replace(eligible, diamond_duration_seconds=3_600)):
            self.assertEqual(food_farm_boost_decision(unsafe).choice, FoodFarmBoostChoice.BLOCKED)

    def test_item_availability_reads_the_cost_glyph_not_the_red_button_or_inventory(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        roi = (500, 1080, 720, 1170)
        token = route.NativeTextToken("1", 99, (670, 1120, 680, 1140))
        frame[1080:1170, 500:720] = (60, 70, 130)  # normal muted-red item button
        self.assertIsNone(route._item_control_usable(frame, (token,), roi))
        frame[1120:1140, 670:680] = (245, 245, 245)
        self.assertIs(route._item_control_usable(frame, (token,), roi), True)
        frame[1120:1140, 670:680] = (0, 0, 255)
        self.assertIs(route._item_control_usable(frame, (token,), roi), False)
        self.assertEqual(route._diamond_balance_lower_bound("54.5K"), 54_400)
        self.assertIsNone(route._exact_balance("54.5K"))
        self.assertEqual(route._diamond_balance_lower_bound("48"), 48)

    def test_reachable_farm_selection_uses_any_mapped_visible_farm(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        localizer = SimpleNamespace(localize=lambda _frame: SimpleNamespace(
            recognized=True, stale=False, overlay=False,
        ))
        atlas = SimpleNamespace(lookup_building=lambda building_id: building_id)

        def bind(_frame, _localization, building_id, *, home_is_clean):
            if building_id != "home.building.farm.02":
                return None
            return SimpleNamespace(
                frame_sha256=route.frame_digest(frame),
                target_roi=(500, 500, 550, 550),
                overlay_intersects=False,
                ambiguous_overlap=False,
                semantic_evidence=("farm:02",),
            )

        with patch.object(route, "is_clean_home_frame", return_value=True), \
             patch.object(route, "_farm_ids", return_value=("home.building.farm.01", "home.building.farm.02")), \
             patch.object(route, "bind_visible_building", side_effect=bind):
            binding = route.bind_reachable_farm(frame, atlas, localizer)
        self.assertIsNotNone(binding)
        self.assertEqual(binding.building_id, "home.building.farm.02")

    def test_radial_boost_control_requires_same_farm_geometry_and_all_exact_labels(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        binding = route.FarmBinding("home.building.farm.02", (480, 500, 540, 560), "a" * 64, ("atlas",))
        tokens = (
            route.NativeTextToken("Details", 99, (390, 620, 450, 640)),
            route.NativeTextToken("Upgrade", 99, (470, 640, 550, 660)),
            route.NativeTextToken("Boost", 99, (570, 620, 620, 640)),
        )
        with patch.object(route, "_ocr_tokens", return_value=tokens):
            self.assertEqual(route._farm_radial_boost_roi(frame, binding), (562, 612, 628, 648))
            self.assertIsNone(route._farm_radial_boost_roi(
                frame, route.FarmBinding("home.building.farm.03", (100, 200, 160, 260),
                                         binding.frame_sha256, binding.evidence)
            ))

    @requires_local_captures
    def test_retained_actual_farm_radial_uses_mapped_owner_not_occluded_farm_caption(self):
        invocation = "FOOD-FARM-OUTPUT-BOOST-DAILY-BLUESTACKS-INTEGRATION-20261109T104945190400Z-d4860ecf"
        frames = (
            Path(__file__).resolve().parents[2] / "Puzzle_Survival_Runtime_POC"
            / ".local-captures" / "canonical-owner-replay-20261109T080850495633Z"
            / "farm-existing-boost-same-building-observation" / invocation
            / "food-farm-output-boost-20261109T104945271055Z" / "frames"
        )

        def retained(name):
            frame = cv2.imread(str(require_capture(frames / name)), cv2.IMREAD_COLOR)
            self.assertIsNotNone(frame)
            return frame

        before = retained("0013-food-farm-action-pre-dispatch.png")
        immediate = retained("0014-food-farm-collect_food_farm_resources-immediate-post.png")
        rebound = retained("0015-food-farm-rebound-before-radial.png")
        radial = retained(f"0018-food-farm-open-radial-{invocation}-3-settled.png")
        atlas = route.load_home_atlas(route.DEFAULT_ATLAS)
        localizer = route.BlueStacksHomeLocalizer(atlas, route.DEFAULT_ATLAS)
        binding = route.bind_reachable_farm(rebound, atlas, localizer)
        self.assertIsNotNone(binding)
        self.assertEqual(binding.building_id, "home.building.farm.01")
        roi = route._farm_radial_boost_roi(radial, binding)
        self.assertIsNotNone(roi)
        x0, y0, x1, y1 = roi
        # Independently annotated actual Boost caption, not central Upgrade.
        self.assertTrue(x0 <= 317 <= x1 and y0 <= 803 <= y1)
        self.assertFalse(x0 <= 223 <= x1 and y0 <= 826 <= y1)
        self.assertIsNone(route._farm_radial_boost_roi(rebound, binding))
        # A nearby other Farm caption cannot transfer radial ownership.
        self.assertIsNone(route._farm_radial_boost_roi(
            radial, replace(binding, building_id="home.building.farm.02",
                            target_roi=(292, 748, 394, 838)),
        ))
        without_boost = radial.copy()
        without_boost[790:816, 280:350] = 0
        self.assertIsNone(route._farm_radial_boost_roi(without_boost, binding))
        # Collection's immediate frame precedes the visible broad-resource tick.
        self.assertEqual(route._home_food_reading(before), "2.43M")
        self.assertEqual(route._home_food_reading(immediate), "2.43M")
        self.assertEqual(route._home_food_reading(rebound), "3.04M")
        self.assertTrue(route._food_reading_increased(
            route._home_food_reading(before), route._home_food_reading(rebound)))



    def _run_from_confirmed_collection(self, observation, *, occurrence_key, active_events=()):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        capture = FakeCapture(frame, "8" * 64, Path("boost-panel.png"))
        binding = route.FarmBinding(
            "home.building.farm.02", (500, 500, 550, 550), capture.sha256, ("atlas",)
        )
        panel = route.BoostPanelRead(
            observation, (600, 1080, 700, 1140), (100, 1080, 300, 1140),
            "Boost Output 1-day", capture,
        )

        class Runtime:
            input_count = 0

            def capture(self, _label):
                return capture

        class Store:
            def get_action_by_key(self, key):
                return {"final_status": "confirmed", "policy_request_json": {
                    "semantic_preconditions": ["current_collection_balance_before:food=100,wood=200,steel=300,gas=400"]
                }} if ":occurrence:collection:" in key else None

            def action_key_exists(self, _key):
                return False

            def audit_events(self, _key):
                return active_events

        context = SimpleNamespace(
            flow_id=route.FLOW_ID, product_id=route.PRODUCT_ID,
            product_revision=route.PRODUCT_REVISION,
            identity=SimpleNamespace(
                runtime_scope="scope", account_id="account", server_id="server",
                reset_id="scheduler-reset", runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
            ),
            occurrence_key=occurrence_key, runtime=Runtime(),
            session=SimpleNamespace(invocation_id=f"occurrence-{occurrence_key}"),
            action_store=Store(), validate_identity=lambda: None, checkpoint=lambda: None,
            settle_seconds=0.0,
        )
        with patch.object(route, "is_clean_home_frame", return_value=True), \
             patch.object(route, "load_home_atlas", return_value=object()), \
             patch.object(route, "BlueStacksHomeLocalizer", side_effect=lambda *_args: _recognized_localizer()), \
             patch.object(route, "bind_reachable_farm", return_value=binding), \
             patch.object(route, "_open_food_farm_radial", return_value={"status": "opened"}), \
             patch.object(
                 route, "_open_food_farm_boost_panel",
                 return_value={"status": "observed", "panel": panel},
             ), \
             patch.object(
                 route, "food_farm_boost_daily_action_key",
                 wraps=route.food_farm_boost_daily_action_key,
             ) as key_factory:
            result = route.run_food_farm_boost_native(context, {})
        return result, key_factory

    def test_first_tap_credits_delayed_hud_tick_before_same_farm_boost_rebound(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        capture = FakeCapture(frame, "7" * 64, Path("collection-successor.png"))
        binding = route.FarmBinding(
            "home.building.farm.02", (500, 500, 550, 550), capture.sha256, ("atlas",)
        )
        observation = route._food_farm_observation(
            farm_identity=binding.building_id, active_remaining_seconds=None,
            option_duration_seconds=86_400, option_item_name="Boost Output 1-day",
            option_item_cost=1, option_item_visible=True,
            inventory_item_name=None, inventory_item_count=None, inventory_observed=False,
            diamond_option_visible=False, diamond_item_name=None, diamond_duration_seconds=None,
            diamond_cost=None, diamond_balance=None, diamond_direct_action_observed=False,
            overlay_state="none", source_frame_sha256=capture.sha256,
            evidence_refs=("evidence/boost-panel.png",),
            runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        )
        panel = route.BoostPanelRead(
            observation, (600, 1080, 700, 1140), None,
            "Boost Output 1-day", capture,
        )
        events = []
        food_readings = iter(("3.00M", "3.00M", "3.93M"))

        class Runtime:
            input_count = 0

            def capture(self, _label):
                return capture

        class Store:
            def get_action_by_key(self, _key):
                return None

            def action_key_exists(self, _key):
                return False

            def has_action_block(self):
                return False

            def audit_events(self, _key):
                return ()

        def dispatch_collection(**kwargs):
            events.append(("collection", kwargs["action_kind"], kwargs["binding"].building_id))
            self.assertTrue(kwargs["after_observer"](capture))
            return {
                "status": "confirmed", "reason": "positive broad resource deltas",
                "transport_calls": 1, "effect_reconciliation_required": False,
                "successor_frame": str(capture.path),
            }

        def open_radial(_context, _atlas, _localizer, rebound):
            events.append(("radial", rebound.building_id))
            return {"status": "opened"}

        def open_panel(_context, *, farm_id, binding):
            events.append(("panel", farm_id))
            return {"status": "observed", "panel": panel}

        context = SimpleNamespace(
            flow_id=route.FLOW_ID, product_id=route.PRODUCT_ID,
            product_revision=route.PRODUCT_REVISION,
            identity=SimpleNamespace(
                runtime_scope="scope", account_id="account", server_id="server",
                reset_id="scheduler-reset", runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
            ),
            occurrence_key="opaque-first-collection", runtime=Runtime(),
            session=SimpleNamespace(invocation_id="first-collection"),
            action_store=Store(), validate_identity=lambda: None, checkpoint=lambda: None,
            settle_seconds=0.0,
        )
        with patch.object(route, "is_clean_home_frame", return_value=True), \
             patch.object(route, "load_home_atlas", return_value=object()), \
             patch.object(route, "BlueStacksHomeLocalizer", side_effect=lambda *_args: _recognized_localizer()), \
             patch.object(route, "bind_reachable_farm", return_value=binding), \
             patch.object(route, "_home_food_reading", side_effect=lambda _frame: next(food_readings)), \
             patch.object(route, "_dispatch_canonical_action", side_effect=dispatch_collection), \
             patch.object(route, "_open_food_farm_radial", side_effect=open_radial), \
             patch.object(route, "_open_food_farm_boost_panel", side_effect=open_panel):
            result = route.run_food_farm_boost_native(context, {})
        self.assertEqual(events, [
            ("collection", "collect_food_farm_resources", binding.building_id),
            ("radial", binding.building_id), ("panel", binding.building_id),
        ])
        self.assertEqual(result["collection_transport_calls"], 1)
        self.assertEqual(result["collection_count"], 1)
        self.assertEqual(result["food_farm_dispatch_count"], 1)
        self.assertTrue(result["collection_effect_accounted"])
        self.assertEqual(result["collection_food_before"], "3.00M")
        self.assertEqual(result["collection_food_after"], "3.93M")
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(result["evidence_required"])
        self.assertTrue(result["partial_failure"])
        self.assertEqual(result["collection_successor"], "hud_tick")
        self.assertEqual(result["collection_successor_frame"], str(capture.path))
        self.assertEqual(result["boost_transport_calls"], 0)

    def test_collection_is_reset_ordinal_and_unknown_inventory_stays_evidence_required(self):
        observation = route._food_farm_observation(
            farm_identity="home.building.farm.02", active_remaining_seconds=None,
            option_duration_seconds=86_400, option_item_name="Boost Output 1-day",
            option_item_cost=1, option_item_visible=True,
            inventory_item_name=None, inventory_item_count=None, inventory_observed=False,
            diamond_option_visible=False, diamond_item_name=None, diamond_duration_seconds=None,
            diamond_cost=None, diamond_balance=None, diamond_direct_action_observed=False,
            overlay_state="none", source_frame_sha256="8" * 64,
            evidence_refs=("evidence/boost-panel.png",),
            runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        )
        first, _first_key_factory = self._run_from_confirmed_collection(
            observation, occurrence_key="opaque-occurrence-one",
        )
        second, second_key_factory = self._run_from_confirmed_collection(
            observation, occurrence_key="opaque-occurrence-two",
        )
        self.assertEqual(first["status"], "blocked")
        self.assertTrue(first["evidence_required"])
        self.assertEqual(first["collection_transport_calls"], 0)
        self.assertEqual(first["collection_count"], 1)
        self.assertTrue(first["collection_effect_accounted"])
        self.assertEqual(first["boost_transport_calls"], 0)
        self.assertNotEqual(first["collection_occurrence_key"], second["collection_occurrence_key"])
        self.assertEqual(first["collection_action_key"], second["collection_action_key"])
        self.assertEqual(
            second_key_factory.call_args_list[0].kwargs["collection_occurrence_id"], "1"
        )

    def test_native_boost_blocks_non_one_day_item_before_dispatch(self):
        observation = route._food_farm_observation(
            farm_identity="home.building.farm.02", active_remaining_seconds=None,
            option_duration_seconds=3_600, option_item_name="Boost Output 1-hour",
            option_item_cost=1, option_item_visible=True,
            inventory_item_name="Boost Output 1-hour", inventory_item_count=1,
            inventory_observed=True, diamond_option_visible=False, diamond_item_name=None,
            diamond_duration_seconds=None, diamond_cost=None, diamond_balance=None,
            diamond_direct_action_observed=False, overlay_state="none",
            source_frame_sha256="8" * 64, evidence_refs=("evidence/boost-panel.png",),
            runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        )
        result, _key_factory = self._run_from_confirmed_collection(
            observation, occurrence_key="opaque-one-hour",
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["boost_transport_calls"], 0)
        self.assertTrue(result["evidence_required"])

    def test_native_premium_dispatch_uses_real_option_without_inventing_confirmation(self):
        observation = route._food_farm_observation(
            farm_identity="home.building.farm.02", active_remaining_seconds=None,
            option_duration_seconds=86_400, option_item_name="Boost Output 1-day",
            option_item_cost=1, option_item_visible=True,
            inventory_item_name="Boost Output 1-day", inventory_item_count=0,
            inventory_observed=True, diamond_option_visible=True,
            diamond_item_name="Boost Output 1-day", diamond_duration_seconds=86_400,
            diamond_cost=48, diamond_balance=500, diamond_direct_action_observed=True,
            overlay_state="none", source_frame_sha256="8" * 64,
            evidence_refs=("evidence/boost-panel.png",),
            runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        )
        with patch.object(route, "_dispatch_canonical_action", return_value={
                "status": "blocked", "reason": "dispatch boundary reached", "transport_calls": 0,
                "effect_reconciliation_required": False}) as dispatch:
            self._run_from_confirmed_collection(observation, occurrence_key="opaque-diamond")
        self.assertEqual(dispatch.call_args.kwargs["action_kind"], "buy_food_farm_output_boost_diamonds")
        self.assertEqual(dispatch.call_args.kwargs["cost_type"], "diamonds")
        self.assertEqual(dispatch.call_args.kwargs["cost_amount"], 48)
        self.assertTrue(callable(dispatch.call_args.kwargs["revalidate_before"]))

    def test_active_timer_above_one_day_is_blocked_instead_of_claimed(self):
        observation = route._food_farm_observation(
            farm_identity="home.building.farm.02", active_remaining_seconds=86_401,
            option_duration_seconds=None, option_item_name=None, option_item_cost=None,
            option_item_visible=False, inventory_item_name=None, inventory_item_count=None,
            inventory_observed=False, diamond_option_visible=False, diamond_item_name=None,
            diamond_duration_seconds=None, diamond_cost=None, diamond_balance=None,
            diamond_direct_action_observed=False, overlay_state="none",
            source_frame_sha256="8" * 64, evidence_refs=("evidence/boost-panel.png",),
            runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        )
        result, _key_factory = self._run_from_confirmed_collection(
            observation, occurrence_key="opaque-long-timer",
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "FOOD_FARM_ACTIVE_TIMER_NOT_EXACT_ONE_DAY_RANGE")
        self.assertTrue(result["evidence_required"])
        self.assertEqual(result["boost_transport_calls"], 0)

    def test_prior_active_timer_prevents_second_reset_boost_even_when_another_farm_is_reachable(self):
        observation = route._food_farm_observation(
            farm_identity="home.building.farm.02", active_remaining_seconds=None,
            option_duration_seconds=86_400, option_item_name="Boost Output 1-day",
            option_item_cost=1, option_item_visible=True,
            inventory_item_name=None, inventory_item_count=None, inventory_observed=False,
            diamond_option_visible=False, diamond_item_name=None, diamond_duration_seconds=None,
            diamond_cost=None, diamond_balance=None, diamond_direct_action_observed=False,
            overlay_state="none", source_frame_sha256="8" * 64,
            evidence_refs=("evidence/boost-panel.png",),
            runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        )
        event = {
            "task_id": route.FLOW_ID,
            "event_type": "food_farm_active_boost_observed",
            "payload_json": {
                "reset_id": "scheduler-reset", "farm_identity": "home.building.farm.03",
                "remaining_seconds": 3_600, "source_frame_sha256": "8" * 64,
            },
        }
        result, _key_factory = self._run_from_confirmed_collection(
            observation, occurrence_key="opaque-wrong-farm", active_events=(event,),
        )
        self.assertEqual(result["status"], "already_complete")
        self.assertEqual(result["active_timer_farm_identity"], "home.building.farm.03")
        self.assertFalse(result["effect_reconciliation_required"])
        self.assertFalse(result["identical_retry_denied"])
        self.assertEqual(result["boost_transport_calls"], 0)

    def test_fake_native_smoke_defers_cleanly_when_no_farm_is_currently_reachable(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        capture = FakeCapture(frame, "c" * 64, Path("home.png"))

        class Runtime:
            input_count = 0

            def capture(self, _label):
                return capture

        identity = SimpleNamespace(
            runtime_scope="scope", account_id="account", server_id="server",
            reset_id="scheduler-reset", runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        )
        context = SimpleNamespace(
            flow_id=route.FLOW_ID, product_id=route.PRODUCT_ID,
            product_revision=route.PRODUCT_REVISION, identity=identity,
            occurrence_key="canonical-occurrence-1", runtime=Runtime(),
            session=SimpleNamespace(invocation_id="invocation-1"),
            action_store=SimpleNamespace(),
            validate_identity=lambda: None, checkpoint=lambda: None,
            settle_seconds=0.0,
        )
        with patch.object(route, "is_clean_home_frame", return_value=True), \
             patch.object(route, "load_home_atlas", return_value=SimpleNamespace(buildings=())), \
             patch.object(route, "BlueStacksHomeLocalizer", side_effect=lambda *_args: _recognized_localizer()), \
             patch.object(route, "bind_reachable_farm", return_value=None):
            result = route.run_food_farm_boost_native(context, {})
        self.assertEqual(result["status"], "deferred")
        self.assertEqual(result["collection_transport_calls"], 0)
        self.assertEqual(result["boost_transport_calls"], 0)
        self.assertEqual(result["food_farm_dispatch_count"], 0)
        self.assertTrue(result["terminal_home_verified"])
        self.assertFalse(result["effect_reconciliation_required"])
        self.assertFalse(result["identical_retry_denied"])

    def test_positive_active_timer_is_persisted_for_exact_current_farm_without_boost(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        capture = FakeCapture(frame, "f" * 64, Path("active-home.png"))
        binding = route.FarmBinding(
            "home.building.farm.03", (500, 500, 550, 550), capture.sha256, ("atlas",)
        )
        observation = route._food_farm_observation(
            farm_identity=binding.building_id, active_remaining_seconds=3_600,
            option_duration_seconds=None, option_item_name=None, option_item_cost=None,
            option_item_visible=False, inventory_item_name=None, inventory_item_count=None,
            inventory_observed=False, diamond_option_visible=False, diamond_item_name=None,
            diamond_duration_seconds=None, diamond_cost=None, diamond_balance=None,
            diamond_direct_action_observed=False, overlay_state="none",
            source_frame_sha256=capture.sha256, evidence_refs=("evidence/active.png",),
            runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        )
        panel = route.BoostPanelRead(
            observation, None, None, "Boosting 01:00:00", capture
        )

        class Runtime:
            input_count = 0

            def capture(self, _label):
                return capture

        class Store:
            def __init__(self):
                self.audit_rows = []

            def get_action_by_key(self, key):
                return {"final_status": "confirmed"} if ":occurrence:collection:" in key else None

            def action_key_exists(self, _key):
                return False

            def audit_events(self, _key):
                return ()

            def audit(self, *args, **kwargs):
                self.audit_rows.append((args, kwargs))

        store = Store()
        identity = SimpleNamespace(
            runtime_scope="scope", account_id="account", server_id="server",
            reset_id="scheduler-reset", runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        )
        context = SimpleNamespace(
            flow_id=route.FLOW_ID, product_id=route.PRODUCT_ID,
            product_revision=route.PRODUCT_REVISION, identity=identity,
            occurrence_key="active-occurrence", runtime=Runtime(),
            session=SimpleNamespace(invocation_id="active-check"),
            action_store=store, validate_identity=lambda: None, checkpoint=lambda: None,
            settle_seconds=0.0, utc_clock=lambda: 100.0,
        )
        with patch.object(route, "is_clean_home_frame", return_value=True), \
             patch.object(route, "load_home_atlas", return_value=object()), \
             patch.object(route, "BlueStacksHomeLocalizer", side_effect=lambda *_args: _recognized_localizer()), \
             patch.object(route, "bind_reachable_farm", return_value=binding), \
             patch.object(route, "_open_food_farm_radial", return_value={"status": "opened"}), \
             patch.object(route, "_open_food_farm_boost_panel", return_value={"status": "observed", "panel": panel}):
            result = route.run_food_farm_boost_native(context, {})
        self.assertEqual(result["status"], "already_active")
        self.assertEqual(result["farm_identity"], binding.building_id)
        self.assertEqual(result["active_timer_farm_identity"], binding.building_id)
        self.assertEqual(result["active_remaining_seconds"], 3_600)
        self.assertEqual(result["boost_transport_calls"], 0)
        self.assertEqual(result["food_farm_dispatch_count"], 0)
        self.assertTrue(store.audit_rows)
        self.assertTrue(route.validate_food_farm_native_result(result))

    def test_durable_unknown_boost_is_not_retried_after_restart(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        capture = FakeCapture(frame, "9" * 64, Path("home.png"))
        binding = route.FarmBinding("home.building.farm.02", (500, 500, 550, 550), capture.sha256, ("atlas",))

        class Runtime:
            input_count = 0

            def capture(self, _label):
                return capture

            def tap(self, *_args, **_kwargs):
                raise AssertionError("unknown reset-scoped boost must not be retransmitted")

        class Store:
            def get_action_by_key(self, key):
                if ":daily:boost:" in key:
                    return {"final_status": "input_sent"}
                return None

        context = SimpleNamespace(
            flow_id=route.FLOW_ID, product_id=route.PRODUCT_ID,
            product_revision=route.PRODUCT_REVISION,
            identity=SimpleNamespace(
                runtime_scope="scope", account_id="account", server_id="server",
                reset_id="scheduler-reset", runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
            ),
            occurrence_key="new-collection-occurrence", runtime=Runtime(),
            session=SimpleNamespace(invocation_id="restart-unknown"),
            action_store=Store(), validate_identity=lambda: None, checkpoint=lambda: None,
        )
        with patch.object(route, "is_clean_home_frame", return_value=True), \
             patch.object(route, "load_home_atlas", return_value=object()), \
             patch.object(route, "BlueStacksHomeLocalizer", side_effect=lambda *_args: _recognized_localizer()), \
             patch.object(route, "bind_reachable_farm", return_value=binding):
            result = route.run_food_farm_boost_native(context, {})
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(result["effect_reconciliation_required"])
        self.assertTrue(result["identical_retry_denied"])
        self.assertEqual(result["boost_transport_calls"], 0)
        self.assertEqual(result["food_farm_dispatch_count"], 0)

    def test_durable_unknown_collection_never_replays_on_same_occurrence(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        capture = FakeCapture(frame, "d" * 64, Path("home.png"))
        binding = route.FarmBinding("home.building.farm.02", (500, 500, 550, 550), capture.sha256, ("atlas",))

        class Runtime:
            input_count = 0

            def capture(self, _label):
                return capture

            def tap(self, *_args, **_kwargs):
                raise AssertionError("durable unknown action must not be retransmitted")

        class Store:
            def get_action_by_key(self, _key):
                return {"final_status": "input_sent"}

        context = SimpleNamespace(
            flow_id=route.FLOW_ID, product_id=route.PRODUCT_ID,
            product_revision=route.PRODUCT_REVISION,
            identity=SimpleNamespace(
                runtime_scope="scope", account_id="account", server_id="server",
                reset_id="scheduler-reset", runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
            ),
            occurrence_key="same-canonical-occurrence", runtime=Runtime(),
            session=SimpleNamespace(invocation_id="restart"),
            action_store=Store(), validate_identity=lambda: None, checkpoint=lambda: None,
        )
        with patch.object(route, "is_clean_home_frame", return_value=True), \
             patch.object(route, "load_home_atlas", return_value=object()), \
             patch.object(route, "BlueStacksHomeLocalizer", side_effect=lambda *_args: _recognized_localizer()), \
             patch.object(route, "bind_reachable_farm", return_value=binding):
            result = route.run_food_farm_boost_native(context, {})
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(result["effect_reconciliation_required"])
        self.assertTrue(result["identical_retry_denied"])
        self.assertEqual(result["collection_transport_calls"], 0)
        self.assertEqual(result["food_farm_dispatch_count"], 0)

    def test_confirmed_boost_row_survives_restart_without_redundant_dispatch(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        capture = FakeCapture(frame, "e" * 64, Path("home.png"))
        binding = route.FarmBinding("home.building.farm.02", (500, 500, 550, 550), capture.sha256, ("atlas",))

        class Runtime:
            input_count = 0

            def capture(self, _label):
                return capture

            def tap(self, *_args, **_kwargs):
                raise AssertionError("confirmed reset-scoped boost must not be repeated")

        class Store:
            def get_action_by_key(self, key):
                if ":daily:boost:" in key:
                    return {
                        "final_status": "confirmed",
                        "target_identity": "home.building.farm.02",
                        "expected_postcondition": "FOOD_FARM_POSITIVE_BOOSTING_TIMER",
                        "consequence": "consume_one_exact_named_owned_food_farm_output_boost_item",
                        "policy_request_json": {
                            "semantic_preconditions": [
                                "exact_current_food_farm_item_name:Farm Output Boost",
                                "exact_current_food_farm_item_duration_seconds:86400",
                            ],
                        },
                        "reconciliation_result_json": {
                            "confirmed": True, "frame_sha256": "e" * 64,
                        },
                    }

        context = SimpleNamespace(
            flow_id=route.FLOW_ID, product_id=route.PRODUCT_ID,
            product_revision=route.PRODUCT_REVISION,
            identity=SimpleNamespace(
                runtime_scope="scope", account_id="account", server_id="server",
                reset_id="scheduler-reset", runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
            ),
            occurrence_key="new-service-occurrence", runtime=Runtime(),
            session=SimpleNamespace(invocation_id="restart"),
            action_store=Store(), validate_identity=lambda: None, checkpoint=lambda: None,
        )
        with patch.object(route, "is_clean_home_frame", return_value=True), \
             patch.object(route, "load_home_atlas", return_value=object()), \
             patch.object(route, "BlueStacksHomeLocalizer", side_effect=lambda *_args: _recognized_localizer()), \
             patch.object(route, "bind_reachable_farm", return_value=binding):
            result = route.run_food_farm_boost_native(context, {})
        self.assertEqual(result["status"], "already_complete")
        self.assertEqual(result["boost_transport_calls"], 0)
        self.assertEqual(result["food_farm_dispatch_count"], 0)
        self.assertTrue(result["terminal_home_verified"])
        self.assertEqual(result["prior_boost_confirmation_farm_identity"], binding.building_id)
        self.assertTrue(route.validate_food_farm_native_result(result))


    def test_result_validator_requires_explicit_collection_and_exact_boost_proof(self):

        farm_id = "home.building.farm.02"
        result = {
            "collection_transport_calls": 1,
            "boost_transport_calls": 1,
            "food_farm_dispatch_count": 2,
            "collection_count": 1,
            "collection_effect_accounted": True,
            "effect_reconciliation_required": False,
            "status": "completed",
            "farm_identity": farm_id,
            "boost_decision": "owned_item",
            "boost_duration_seconds": 86_400,
            "boost_timer_remaining_seconds": 86_390,
            "boost_timer_farm_identity": farm_id,
            "terminal_home_verified": True,
            "terminal_home_frame_sha256": "a" * 64,
        }
        self.assertTrue(route.validate_food_farm_native_result(result))
        invalid_results = (
            {**result, "food_farm_dispatch_count": 1},
            {**result, "collection_count": 0},
            {**result, "boost_duration_seconds": 3_600},
            {**result, "boost_timer_remaining_seconds": 86_401},
            {**result, "boost_timer_farm_identity": "home.building.farm.03"},
            {**result, "boost_decision": "diamonds"},
            {
                **result, "collection_transport_calls": 2,
                "collection_count": 2, "food_farm_dispatch_count": 3,
            },
        )
        for invalid in invalid_results:
            with self.subTest(invalid=invalid):
                self.assertFalse(route.validate_food_farm_native_result(invalid))


    def test_unknown_collection_transport_is_attempted_but_not_committed(self):
        result = {
            "status": "unresolved",
            "collection_transport_calls": 1,
            "boost_transport_calls": 0,
            "food_farm_dispatch_count": 1,
            "collection_count": 0,
            "collection_effect_accounted": False,
            "effect_reconciliation_required": True,
            "identical_retry_denied": True,
        }
        self.assertTrue(route.validate_food_farm_native_result(result))
        self.assertFalse(
            route.validate_food_farm_native_result({**result, "collection_count": 1})
        )

if __name__ == "__main__":
    unittest.main()
