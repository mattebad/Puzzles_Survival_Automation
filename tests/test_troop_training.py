from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import CapturedNativeFrame, LocalBlueStacksRuntime
from scripts.troop_training_bluestacks import TroopTrainingIntegratedRoute
from tasks.troop_training import (
    DAILY_TRAINING_QUANTITY,
    FACILITY_BY_TYPE,
    TROOP_TYPES,
    ResourceReading,
    TierObservation,
    TrainingConfig,
    TrainingController,
    TrainingContractError,
    TrainingScreenObservation,
    TroopTrainingConfig,
    all_base_resources_sufficient,
    daily_progress_from_text,
    expected_completion_timestamp,
    parse_duration_seconds,
    parse_quantity,
)
from tasks.troop_training_runtime import TrainingPhase, TroopTrainingRuntimeController
from tasks.troop_training_vision import TAB_ROIS, recognize_auto_use_resource_popup


RESET = "local-reset-2026-07-16"


def config(
    *,
    tier: int | None = 8,
    quantity: int = 250,
    policy: str = "once_daily",
    allow_resource_boxes: bool = False,
) -> TroopTrainingConfig:
    return TroopTrainingConfig(
        fighter=TrainingConfig(target_tier=tier, quantity=quantity, training_policy=policy, allow_resource_boxes=allow_resource_boxes),
        shooter=TrainingConfig(target_tier=tier, quantity=quantity, training_policy=policy, allow_resource_boxes=allow_resource_boxes),
        rider=TrainingConfig(target_tier=tier, quantity=quantity, training_policy=policy, allow_resource_boxes=allow_resource_boxes),
        vehicle=TrainingConfig(target_tier=tier, quantity=quantity, training_policy=policy, allow_resource_boxes=allow_resource_boxes),
    )


def observation(
    troop_type: str = "fighter",
    *,
    tier: int = 8,
    quantity: int = 250,
    queue_active: bool = False,
    duration: int | None = 3600,
    resources: tuple[ResourceReading, ...] | None = None,
    locked: bool = False,
    completion_ready: bool = False,
) -> TrainingScreenObservation:
    resources = resources or tuple(ResourceReading(name, 100_000, 1_000, "base") for name in ("food", "wood", "steel", "gas"))
    tiers = tuple(
        TierObservation(
            number,
            unlocked=not locked or number != tier,
            selected=number == tier,
            question_mark=locked and number == tier,
            lock_reason="requires Lv.26 Shooter Camp" if locked and number == tier else "",
            target_roi=(50 + number * 5, 850, 110 + number * 5, 950),
        )
        for number in range(1, 14)
    )
    return TrainingScreenObservation(
        recognized=True,
        troop_type=troop_type,
        facility_identity=FACILITY_BY_TYPE[troop_type],
        selected_tier=tier,
        visible_tiers=tiers,
        selected_quantity=quantity,
        quantity_maximum=1000,
        resources=resources,
        normal_train_target=(480, 1140, 700, 1240),
        train_now_target=(100, 1140, 360, 1240),
        training_duration_seconds=duration,
        queue_active=queue_active,
        completion_ready=completion_ready,
        completion_batch_id=f"{troop_type}:batch-1" if completion_ready else None,
        frame_sha256="a" * 64,
        captured_at=datetime.now(timezone.utc),
    )


class RecordingRunner:
    def __init__(self):
        ok, encoded = cv2.imencode(".png", np.zeros((1280, 800, 3), dtype=np.uint8))
        if not ok:
            raise AssertionError("PNG encoding failed")
        self.png = encoded.tobytes()
        self.inputs: list[tuple[str, object]] = []

    def capture_png(self):
        return self.png

    def dispatch_tap(self, point):
        self.inputs.append(("tap", point))

    def dispatch_swipe(self, start, end, duration_ms=400):
        self.inputs.append(("swipe", (start, end, duration_ms)))

    def dispatch_text(self, text):
        self.inputs.append(("text", text))

    def dispatch_keyevent(self, key):
        self.inputs.append(("key", key))

    def dispatch_back(self):
        self.inputs.append(("back", None))


class TroopTrainingContractTests(unittest.TestCase):
    def test_explicit_tier_is_required_and_variants_are_independent(self):
        with self.assertRaises(TrainingContractError):
            config(tier=None).validate()
        configured = TroopTrainingConfig(
            fighter=TrainingConfig(target_tier=1),
            shooter=TrainingConfig(target_tier=5),
            rider=TrainingConfig(target_tier=8),
            vehicle=TrainingConfig(target_tier=13),
        )
        configured.validate()
        self.assertEqual(configured.for_type("fighter").target_tier, 1)
        self.assertEqual(configured.for_type("vehicle").target_tier, 13)
        self.assertFalse(configured.for_type("vehicle").allow_resource_boxes)
        with self.assertRaises(TrainingContractError):
            TrainingConfig(target_tier=8, allow_resource_boxes="yes").validate()

    def test_all_supported_tiers_and_locked_tier_rejection(self):
        self.assertEqual(TROOP_TYPES, ("fighter", "shooter", "rider", "vehicle"))
        controller = TrainingController(config(tier=9), reset_identity=RESET)
        locked = observation("shooter", tier=9, locked=True)
        self.assertEqual(controller.plan_tier(locked, "shooter"), "reject_locked_tier")
        self.assertEqual(tuple(range(1, 14)), tuple(item.tier for item in observation().visible_tiers))

    def test_quantity_duration_and_resource_parsing(self):
        self.assertEqual(parse_quantity("250 / 1,000"), 250)
        self.assertIsNone(parse_quantity("MAX"))
        self.assertEqual(parse_duration_seconds("11:42:05"), 42125)
        self.assertEqual(parse_duration_seconds("2d03:04:05"), 183845)
        sufficient = tuple(ResourceReading(name, 100, 50) for name in ("food", "wood", "steel", "gas"))
        insufficient = replace(sufficient[0], held=49)
        self.assertTrue(all_base_resources_sufficient(sufficient))
        self.assertFalse(all_base_resources_sufficient((insufficient, *sufficient[1:])))

    def test_normal_train_authorization_rejects_queue_overlay_and_unknown_resource(self):
        controller = TrainingController(config(), reset_identity=RESET)
        self.assertEqual(controller.plan_training(observation(), "fighter"), "authorize_normal_train")
        self.assertEqual(controller.plan_training(observation(queue_active=True), "fighter"), "reject_active_queue")
        self.assertEqual(controller.plan_training(replace(observation(), overlay_state="popup"), "fighter"), "reject_quantity_or_tier")
        unknown = tuple(ResourceReading(name, None, 50) for name in ("food", "wood", "steel", "gas"))
        self.assertEqual(controller.plan_training(replace(observation(), resources=unknown), "fighter"), "reject_resource_sufficiency")

    def test_known_shortage_requires_exact_warehouse_successor_and_forbidden_popup_is_rejected(self):
        controller = TrainingController(config(), reset_identity=RESET)
        shortage = tuple(ResourceReading(name, 10, 50) for name in ("food", "wood", "steel", "gas"))
        self.assertEqual(controller.plan_training(replace(observation(), resources=shortage), "fighter"), "authorize_normal_train_expected_warehouse")
        forbidden = replace(observation(), premium_popup=True, forbidden_controls=("premium",))
        self.assertEqual(controller.plan_training(forbidden, "fighter"), "reject_forbidden_control")

    def test_auto_use_resource_boxes_are_exactly_recognized_as_non_warehouse(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        with (
            patch(
                "tasks.troop_training_vision._ocr",
                side_effect=(
                    "auto use",
                    "will have sufficient resources after use",
                    "auto use (total) 98.6K/98.0K 1.42M/30.0K 697K/4,323 485K/455 resources held (total) auto-use resource boxes",
                ),
            ),
            patch(
                "tasks.troop_training_vision._ocr_variant_boxes",
                return_value=[("cancel", (180, 990, 290, 1025)), ("confirm", (500, 990, 625, 1025))],
            ),
        ):
            popup = recognize_auto_use_resource_popup(frame)
        self.assertTrue(popup.recognized)
        self.assertTrue(popup.resource_boxes_selected)
        self.assertFalse(popup.warehouse_only)
        self.assertIsNotNone(popup.cancel_target)
        self.assertIsNotNone(popup.confirm_target)
        self.assertEqual(tuple(resource.required for resource in popup.resources_after_use), (98_000, 30_000, 4_323, 455))

    def test_resource_box_toggle_is_independent_and_fail_closed(self):
        shortage = (
            ResourceReading("food", 52_600, 98_000),
            ResourceReading("wood", 1_420_000, 30_000),
            ResourceReading("steel", 697_000, 4_323),
            ResourceReading("gas", 485_000, 455),
        )
        before = replace(observation("rider"), resources=shortage)
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        with (
            patch(
                "tasks.troop_training_vision._ocr",
                side_effect=(
                    "auto use",
                    "will have sufficient resources after use",
                    "auto use (total) 98.6K/98.0K 1.42M/30.0K 697K/4,323 485K/455 resources held (total) auto-use resource boxes",
                ),
            ),
            patch(
                "tasks.troop_training_vision._ocr_variant_boxes",
                return_value=[("cancel", (180, 990, 290, 1025)), ("confirm", (500, 990, 625, 1025))],
            ),
        ):
            popup = recognize_auto_use_resource_popup(frame)
        disabled = TrainingController(config(allow_resource_boxes=False), reset_identity=RESET)
        enabled = TrainingController(config(allow_resource_boxes=True), reset_identity=RESET)
        self.assertEqual(disabled.plan_resource_box_continuation(before, popup, "rider"), "reject_resource_boxes_disabled")
        self.assertEqual(enabled.plan_resource_box_continuation(before, popup, "rider"), "authorize_resource_box_confirmation")
        applied = replace(
            before,
            selected_quantity=251,
            resources=(
                ResourceReading("food", 98_600, 98_400),
                ResourceReading("wood", 1_420_000, 30_100),
                ResourceReading("steel", 697_000, 4_340),
                ResourceReading("gas", 485_000, 457),
            ),
            frame_sha256="b" * 64,
        )
        self.assertTrue(enabled.prove_resource_boxes_applied(before, popup, applied, "rider"))
        self.assertFalse(disabled.prove_resource_boxes_applied(before, popup, applied, "rider"))
        mixed = TroopTrainingConfig(
            fighter=TrainingConfig(target_tier=8),
            shooter=TrainingConfig(target_tier=8),
            rider=TrainingConfig(target_tier=8, allow_resource_boxes=True),
            vehicle=TrainingConfig(target_tier=8),
        )
        self.assertTrue(mixed.rider.allow_resource_boxes)
        self.assertFalse(mixed.vehicle.allow_resource_boxes)

    def test_training_commit_records_timer_expected_completion_and_daily_state(self):
        controller = TrainingController(config(), reset_identity=RESET)
        before = observation()
        after = replace(before, queue_active=True, frame_sha256="b" * 64)
        dispatched = datetime(2026, 7, 16, 20, 0, tzinfo=timezone.utc)
        state = controller.commit_training("fighter", before, action_key="training-key", dispatched_at=dispatched, post=after)
        self.assertEqual(state.queue_state, "active")
        self.assertEqual(state.expected_completion_timestamp, expected_completion_timestamp(dispatched, 3600))
        self.assertEqual(state.daily_initiation_state, "initiated")
        self.assertEqual(controller.scheduler_state("fighter").state, "WAIT_UNTIL_COMPLETION")

    def test_claim_is_exact_once_and_continuous_waits_for_claim_reconciliation(self):
        controller = TrainingController(config(policy="continuous"), reset_identity=RESET)
        before = observation(completion_ready=True)
        self.assertEqual(controller.plan_claim(before, action_key="claim-1"), "authorize_claim")
        self.assertTrue(controller.reconcile_claim(before, replace(before, completion_ready=False, completion_batch_id=None), action_key="claim-1"))
        self.assertEqual(controller.plan_claim(before, action_key="claim-2"), "reject_duplicate_claim")
        state = replace(controller.states["fighter"], queue_state="empty", last_claim_state="none")
        controller.states["fighter"] = state
        self.assertEqual(controller.scheduler_state("fighter").state, "WAIT_CLAIM_RECONCILIATION")

    def test_daily_rows_are_parsed_without_claim_authorization(self):
        progress = daily_progress_from_text("Fighter 250/250 Shooter 0/250 Rider 25/250 Vehicle 250/250")
        self.assertEqual({item.troop_type: item.current for item in progress}, {"fighter": 250, "shooter": 0, "rider": 25, "vehicle": 250})
        self.assertTrue(all(item.maximum == DAILY_TRAINING_QUANTITY for item in progress))

    def test_native_runtime_dry_run_issues_no_swipe_text_or_key_input(self):
        with TemporaryDirectory() as directory:
            runner = RecordingRunner()
            runtime = LocalBlueStacksRuntime(runner, Path(directory) / "session", execute=False)
            source = runtime.capture("dry-run")
            for operation in (
                lambda: runtime.swipe(source, start=(100, 900), end=(650, 900), action_key="swipe"),
                lambda: runtime.type_text(source, text="250", action_key="text"),
                lambda: runtime.press_key(source, key="ENTER", action_key="enter"),
            ):
                with self.assertRaisesRegex(RuntimeError, "dry-run"):
                    operation()
            self.assertEqual(runner.inputs, [])

    def test_scheduler_boundary_remains_disabled(self):
        controller = TrainingController(config(), reset_identity=RESET)
        scheduler = controller.scheduler_state("fighter")
        self.assertFalse(scheduler.scheduler_eligibility)
        self.assertFalse(scheduler.production_registration)
        self.assertEqual(set(TAB_ROIS), set(TROOP_TYPES))

    def test_route_dry_run_cannot_complete_through_mock_transport(self):
        class FakeRuntime:
            execute = False
            in_flight_action = None
            session = Path("fake-session")

            def capture(self, _label):
                return CapturedNativeFrame(np.zeros((1280, 800, 3), dtype=np.uint8), b"png", "a" * 64, 1.0, Path("frame.png"))

        home = type("Home", (), {"recognized": True})()
        with patch("scripts.troop_training_bluestacks.recognize_home", return_value=home):
            result = TroopTrainingIntegratedRoute(FakeRuntime(), config=config(), reset_identity=RESET).run()
        self.assertEqual(result.status, "dry-run")
        self.assertEqual(result.actions_completed, 0)


if __name__ == "__main__":
    unittest.main()
