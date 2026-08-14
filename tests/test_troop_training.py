from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import CapturedNativeFrame, LocalBlueStacksRuntime
from scripts.troop_training_bluestacks import TroopTrainingIntegratedRoute, _load_config
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
from tasks.troop_training_vision import (
    QUEUE_BAND,
    QUEUE_TIMER_BAND,
    TAB_ROIS,
    QUANTITY_BAND,
    recognize_auto_use_resource_popup,
    recognize_radial_menu,
    recognize_training,
)


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
        shooter=TrainingConfig(target_tier=tier, quantity=quantity, training_policy=policy, allow_resource_boxes=False),
        rider=TrainingConfig(target_tier=tier, quantity=quantity, training_policy=policy, allow_resource_boxes=False),
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
    def setUp(self):
        super().setUp()
        for troop_type in TROOP_TYPES:
            TrainingController._daily_initiations.discard((RESET, troop_type))

    def test_radial_train_is_bound_inside_tight_facility_relative_sector(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        facility_target = (323, 360, 488, 467)
        template = cv2.imread(str(Path("tasks/assets/troop_training/800x1280/radial-train-icon.png")))
        frame[420:525, 480:600] = template
        with patch("tasks.troop_training_vision._ocr", return_value=""):
            radial = recognize_radial_menu(
                frame,
                troop_type="fighter",
                facility_target=facility_target,
            )
        self.assertTrue(radial.recognized)
        self.assertEqual(radial.facility_identity, FACILITY_BY_TYPE["fighter"])
        self.assertEqual(radial.train_target, (480, 420, 600, 525))

    def test_radial_train_rejects_missing_out_of_sector_or_ambiguous_ocr(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        facility_target = (323, 360, 488, 467)
        template = cv2.imread(str(Path("tasks/assets/troop_training/800x1280/radial-train-icon.png")))
        cases = ("missing", "outside")
        for case in cases:
            candidate = frame.copy()
            if case == "outside":
                candidate[700:805, 480:600] = template
            with self.subTest(case=case), patch("tasks.troop_training_vision._ocr", return_value=""):
                radial = recognize_radial_menu(
                    candidate,
                    troop_type="fighter",
                    facility_target=facility_target,
                )
            self.assertFalse(radial.recognized)
            self.assertIsNone(radial.train_target)

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

    def test_current_max_reconciles_exact_active_queue_without_screen_maximum(self):
        current_max_config = replace(
            config(policy="continuous", allow_resource_boxes=True),
            fighter=TrainingConfig(
                target_tier=8,
                quantity=None,
                quantity_mode="current_max",
                training_policy="continuous",
                allow_resource_boxes=True,
            ),
        )
        controller = TrainingController(current_max_config, reset_identity=RESET)
        active = replace(
            observation("fighter", quantity=1000, queue_active=True, duration=9369),
            quantity_maximum=None,
            queue_label="Train T8 x1000",
            queue_troop_type="fighter",
            queue_tier=8,
            queue_quantity=1000,
        )

        self.assertEqual(controller.reconcile_active_queue(active, "fighter"), "active_queue_reconciled")
        self.assertEqual(controller.states["fighter"].last_dispatch_state, "reconciled_existing")
        self.assertEqual(controller.states["fighter"].resolved_quantity, 1000)

    def test_current_max_reconciliation_rejects_selected_quantity_mismatch(self):
        current_max_config = replace(
            config(policy="continuous", allow_resource_boxes=True),
            fighter=TrainingConfig(
                target_tier=8,
                quantity=None,
                quantity_mode="current_max",
                training_policy="continuous",
                allow_resource_boxes=True,
            ),
        )
        controller = TrainingController(current_max_config, reset_identity=RESET)
        active = replace(
            observation("fighter", quantity=999, queue_active=True, duration=9369),
            quantity_maximum=None,
            queue_label="Train T8 x1000",
            queue_troop_type="fighter",
            queue_tier=8,
            queue_quantity=1000,
        )

        self.assertEqual(controller.reconcile_active_queue(active, "fighter"), "reject_active_queue_quantity")
        self.assertEqual(controller.states["fighter"].last_dispatch_state, "none")

    def test_fixed_reconciliation_still_uses_configured_quantity(self):
        controller = TrainingController(config(), reset_identity=RESET)
        active = replace(
            observation("fighter", quantity=250, queue_active=True, duration=3600),
            queue_label="Train T8 x250",
            queue_troop_type="fighter",
            queue_tier=8,
            queue_quantity=250,
        )

        self.assertEqual(controller.reconcile_active_queue(active, "fighter"), "active_queue_reconciled")
        self.assertEqual(controller.states["fighter"].resolved_quantity, 250)

        mismatch = replace(active, queue_quantity=1000, queue_label="Train T8 x1000")
        self.assertEqual(controller.reconcile_active_queue(mismatch, "fighter"), "reject_active_queue_quantity")

    def test_active_queue_uses_queue_identity_when_carousel_selection_differs(self):
        controller = TrainingController(config(tier=1), reset_identity=RESET)
        active = replace(
            observation("rider", tier=8, quantity=250, queue_active=True, duration=3600),
            queue_label="Train T1 Nomad x250",
            queue_troop_type="rider",
            queue_tier=1,
            queue_quantity=250,
        )

        self.assertEqual(controller.reconcile_active_queue(active, "rider"), "active_queue_reconciled")
        self.assertEqual(controller.states["rider"].resolved_quantity, 250)

        wrong_tier = replace(active, queue_tier=2, queue_label="Train T2 Nomad x250")
        self.assertEqual(controller.reconcile_active_queue(wrong_tier, "rider"), "reject_active_queue_label_mismatch")
        wrong_quantity = replace(active, queue_quantity=249, queue_label="Train T1 Nomad x249")
        self.assertEqual(controller.reconcile_active_queue(wrong_quantity, "rider"), "reject_active_queue_quantity")

        route = TroopTrainingIntegratedRoute.__new__(TroopTrainingIntegratedRoute)
        route.controller = SimpleNamespace(semantic=controller)
        route.training = []
        route._record_reconciled_queue(SimpleNamespace(sha256="c" * 64), active, "rider")
        self.assertEqual(route.training[0]["selected_tier"], 1)
        self.assertEqual(route.training[0]["quantity"], 250)
        self.assertTrue(route.training[0]["maximum_equality_proven"])

    def test_empty_queue_still_requires_configured_selected_tier(self):
        controller = TrainingController(config(tier=1), reset_identity=RESET)
        empty = observation("rider", tier=8, quantity=250, queue_active=False)

        self.assertEqual(controller.plan_training(empty, "rider"), "reject_quantity_or_tier")

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
        before = replace(observation("fighter"), resources=shortage)
        rider_before = replace(observation("rider"), resources=shortage)
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
        self.assertEqual(disabled.plan_resource_box_continuation(before, popup, "fighter"), "reject_resource_boxes_disabled")
        self.assertEqual(enabled.plan_resource_box_continuation(before, popup, "fighter"), "authorize_resource_box_confirmation")
        # Resource boxes are structurally restricted to Fighter/Vehicle even when
        # an unsafe legacy override requests them for Shooter/Rider.
        self.assertEqual(enabled.plan_resource_box_continuation(rider_before, popup, "rider"), "reject_resource_boxes_disabled")
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
        self.assertTrue(enabled.prove_resource_boxes_applied(before, popup, applied, "fighter"))
        self.assertFalse(enabled.prove_resource_boxes_applied(rider_before, popup, applied, "rider"))
        self.assertFalse(disabled.prove_resource_boxes_applied(before, popup, applied, "fighter"))
        mixed = TroopTrainingConfig(
            fighter=TrainingConfig(target_tier=8),
            shooter=TrainingConfig(target_tier=8),
            rider=TrainingConfig(target_tier=8, allow_resource_boxes=True),
            vehicle=TrainingConfig(target_tier=8),
        )
        with self.assertRaisesRegex(TrainingContractError, "structurally forbidden"):
            mixed.validate()

    def test_training_commit_records_timer_expected_completion_and_daily_state(self):
        controller = TrainingController(config(), reset_identity=RESET)
        before = observation()
        after = replace(
            before,
            queue_active=True,
            queue_label="Train T8 x250",
            queue_troop_type="fighter",
            queue_tier=8,
            queue_quantity=250,
            frame_sha256="b" * 64,
        )
        dispatched = datetime(2026, 7, 16, 20, 0, tzinfo=timezone.utc)
        state = controller.commit_training("fighter", before, action_key="training-key", dispatched_at=dispatched, post=after)
        self.assertEqual(state.queue_state, "active")
        self.assertEqual(state.expected_completion_timestamp, expected_completion_timestamp(dispatched, 3600))
        self.assertEqual(state.daily_initiation_state, "initiated")
        self.assertEqual(controller.scheduler_state("fighter").state, "WAIT_UNTIL_COMPLETION")

    def test_daily_persistence_unions_types_and_rejects_malformed_schema(self):
        reset = "persist-union-regression"
        TrainingController._daily_initiations.discard((reset, "shooter"))
        TrainingController._daily_initiations.discard((reset, "rider"))
        with TemporaryDirectory() as directory:
            path = Path(directory) / "troop-training-state.json"
            controller = TrainingController(config(), reset_identity=reset, persistence_path=path)
            for troop_type in ("shooter", "rider"):
                before = observation(troop_type)
                post = replace(
                    before,
                    queue_active=True,
                    queue_label="Train T8 x250",
                    queue_troop_type=troop_type,
                    queue_tier=8,
                    queue_quantity=250,
                )
                controller.commit_training(
                    troop_type,
                    before,
                    action_key=f"persist-{troop_type}",
                    dispatched_at=datetime(2026, 7, 16, 20, 0, tzinfo=timezone.utc),
                    post=post,
                )
            TrainingController._daily_initiations.discard((reset, "shooter"))
            TrainingController._daily_initiations.discard((reset, "rider"))
            restored = TrainingController(config(), reset_identity=reset, persistence_path=path)
            self.assertEqual(restored.states["shooter"].daily_initiation_state, "initiated")
            self.assertEqual(restored.states["rider"].daily_initiation_state, "initiated")

            path.write_text('{"daily_initiations": ["malformed"]}\n', encoding="utf-8")
            malformed = TrainingController(config(), reset_identity="persist-malformed", persistence_path=path)
            self.assertEqual(malformed.plan_training(observation("shooter"), "shooter"), "reject_daily_persistence_unresolved")

    def test_inherited_current_max_rejects_explicit_cli_quantity(self):
        values = {"config": None}
        for troop_type in TROOP_TYPES:
            values.update(
                {
                    f"{troop_type}_enabled": None,
                    f"{troop_type}_tier": None,
                    f"{troop_type}_quantity": 123 if troop_type == "fighter" else None,
                    f"{troop_type}_quantity_mode": "current_max" if troop_type == "fighter" else None,
                    f"{troop_type}_policy": None,
                    f"{troop_type}_allow_resource_boxes": None,
                }
            )
        with self.assertRaisesRegex(ValueError, "current_max cannot include a fixed quantity"):
            _load_config(argparse.Namespace(**values))

    def test_queue_timer_source_is_spatially_bound_to_queue_label(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        tier = TierObservation(8, unlocked=True, selected=True, target_roi=(100, 800, 180, 900))

        def boxes(_frame, _box=None):
            return [("train", (500, 1150, 650, 1200))]

        def queue_ocr(_frame, box=None, *, psm=11):
            if box == QUEUE_BAND:
                return "train t8 veteran x250 02:55:32"
            if box == QUANTITY_BAND:
                return "250 / 1000"
            return "master trainer"

        with (
            patch("tasks.troop_training_vision._ocr", side_effect=queue_ocr),
            patch("tasks.troop_training_vision._ocr_boxes", side_effect=boxes),
            patch("tasks.troop_training_vision._colored_button_target", return_value=None),
            patch("tasks.troop_training_vision._training_title", return_value=("fighter", "Fighter Camp")),
            patch("tasks.troop_training_vision._selected_tier", return_value=8),
            patch("tasks.troop_training_vision._tier_observations", return_value=(tier,)),
        ):
            active = recognize_training(frame)
        self.assertTrue(active.queue_active)
        self.assertEqual(active.training_duration_seconds, 10532)
        self.assertEqual(active.diagnostics["duration_source"], "queue_band")
        self.assertEqual(active.diagnostics["duration_ocr_source"], "queue_band")
        self.assertTrue(active.diagnostics["queue_spatially_associated"])

        def empty_ocr(_frame, box=None, *, psm=11):
            if box == QUEUE_BAND:
                return "queue empty"
            if box == QUANTITY_BAND:
                return "250 / 1000"
            if box == (430, 1135, 700, 1270):
                return "Train 01:02:03"
            return "master trainer"

        with patch("tasks.troop_training_vision._ocr", side_effect=empty_ocr):
            empty = recognize_training(frame)
        self.assertFalse(empty.queue_active)
        self.assertEqual(empty.training_duration_seconds, 3723)
        self.assertEqual(empty.diagnostics["duration_source"], "normal_train_band")
        self.assertEqual(empty.diagnostics["duration_ocr_source"], "normal_train_band")
        self.assertFalse(empty.diagnostics["queue_spatially_associated"])

    def test_active_queue_companion_recognizes_without_master_trainer_signal(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        tier = TierObservation(8, unlocked=True, selected=True, target_roi=(100, 800, 180, 900))

        def boxes(_frame, _box=None):
            return [("train", (500, 1150, 650, 1200))]

        def queue_ocr(_frame, box=None, *, psm=11):
            if box == QUEUE_BAND:
                return "train t1 nomad x250 02:55:32"
            if box == QUANTITY_BAND:
                return "250 / 1000"
            return ""

        with (
            patch("tasks.troop_training_vision._ocr", side_effect=queue_ocr),
            patch("tasks.troop_training_vision._ocr_boxes", side_effect=boxes),
            patch("tasks.troop_training_vision._colored_button_target", return_value=None),
            patch("tasks.troop_training_vision._training_title", return_value=("rider", "Rider Camp")),
            patch("tasks.troop_training_vision._selected_tier", return_value=8),
            patch("tasks.troop_training_vision._tier_observations", return_value=(tier,)),
        ):
            active = recognize_training(frame)

        self.assertTrue(active.recognized)
        self.assertTrue(active.queue_active)
        self.assertEqual(active.queue_tier, 1)
        self.assertEqual(active.queue_quantity, 250)

    def test_packed_queue_timer_fallback_requires_positive_timer(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        tier = TierObservation(8, unlocked=True, selected=True, target_roi=(100, 800, 180, 900))

        def boxes(_frame, _box=None):
            return [("train", (500, 1150, 650, 1200))]

        def recognize_mocked_queue(queue_text, normal_button_text="master trainer", timer_text=None):
            def queue_ocr(_frame, box=None, *, psm=11):
                if box == QUEUE_BAND:
                    return queue_text
                if box == QUANTITY_BAND:
                    return "250 / 1000"
                if box == (430, 1135, 700, 1270):
                    return normal_button_text
                return "master trainer"

            with (
                patch("tasks.troop_training_vision._ocr", side_effect=queue_ocr),
                patch("tasks.troop_training_vision._ocr_boxes", side_effect=boxes),
                patch("tasks.troop_training_vision._colored_button_target", return_value=None),
                patch("tasks.troop_training_vision._training_title", return_value=("fighter", "Fighter Camp")),
                patch("tasks.troop_training_vision._selected_tier", return_value=8),
                patch("tasks.troop_training_vision._tier_observations", return_value=(tier,)),
                patch("tasks.troop_training_vision._queue_timer_text", return_value=timer_text) as timer,
            ):
                return recognize_training(frame), timer

        active, timer = recognize_mocked_queue("train t8 veteran x1000 02236209", timer_text="02:36:09")
        self.assertTrue(active.queue_active)
        self.assertEqual(active.queue_quantity, 1000)
        self.assertEqual(active.queue_tier, 8)
        self.assertEqual(active.training_duration_seconds, 9369)
        self.assertEqual(active.diagnostics["duration_source"], "queue_band")
        self.assertEqual(active.diagnostics["duration_ocr_source"], "queue_timer_band")
        self.assertTrue(active.diagnostics["queue_spatially_associated"])
        timer.assert_called_once_with(frame)

        for invalid_generic in ("99:99:99", "00:00:00"):
            recovered, timer = recognize_mocked_queue(
                f"train t8 veteran x1000 {invalid_generic}",
                timer_text="02:36:09",
            )
            self.assertTrue(recovered.queue_active, invalid_generic)
            self.assertEqual(recovered.training_duration_seconds, 9369, invalid_generic)
            self.assertEqual(recovered.diagnostics["duration_source"], "queue_band", invalid_generic)
            self.assertEqual(recovered.diagnostics["duration_ocr_source"], "queue_timer_band", invalid_generic)
            timer.assert_called_once_with(frame)

        for malformed in ("not-a-timer", "00:00:00"):
            inactive, timer = recognize_mocked_queue(
                "train t8 veteran x1000 02236209",
                timer_text=malformed,
            )
            self.assertFalse(inactive.queue_active, malformed)
            self.assertIsNone(inactive.training_duration_seconds, malformed)
            self.assertEqual(inactive.queue_quantity, 1000, malformed)
            self.assertEqual(inactive.diagnostics["duration_source"], "none", malformed)
            self.assertEqual(inactive.diagnostics["duration_ocr_source"], "none", malformed)
            self.assertFalse(inactive.diagnostics["queue_spatially_associated"], malformed)
            timer.assert_called_once_with(frame)

        empty, timer = recognize_mocked_queue(
            "queue empty",
            normal_button_text="Train 01:02:03",
            timer_text="02:36:09",
        )
        self.assertFalse(empty.queue_active)
        self.assertEqual(empty.training_duration_seconds, 3723)
        self.assertEqual(empty.diagnostics["duration_source"], "normal_train_band")
        self.assertEqual(empty.diagnostics["duration_ocr_source"], "normal_train_band")
        self.assertFalse(empty.diagnostics["queue_spatially_associated"])
        timer.assert_not_called()

        no_exact_label, timer = recognize_mocked_queue(
            "queue active 01:02:03",
            normal_button_text="Train 04:05:06",
            timer_text="02:36:09",
        )
        self.assertFalse(no_exact_label.queue_active)
        self.assertEqual(no_exact_label.training_duration_seconds, 14706)
        self.assertEqual(no_exact_label.diagnostics["duration_source"], "normal_train_band")
        self.assertEqual(no_exact_label.diagnostics["duration_ocr_source"], "normal_train_band")
        self.assertFalse(no_exact_label.diagnostics["queue_spatially_associated"])
        timer.assert_not_called()

    def test_retained_training_queue_timer_fallback_recognizes_active_queue(self):
        frame_path = (
            Path(__file__).resolve().parents[1]
            / ".local-captures"
            / "flow-delivery"
            / "TROOP-TRAINING-END-TO-END-CONSOLIDATION"
            / "run-20260814T033217263154Z"
            / "troop-training-20260814T033217816163Z"
            / "frames"
            / "0003-training-screen-source.png"
        )
        if not frame_path.is_file():
            self.skipTest("retained Fighter training queue frame unavailable")
        frame = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame)
        recognized = recognize_training(frame)
        self.assertTrue(recognized.recognized)
        self.assertTrue(recognized.queue_active)
        self.assertEqual(recognized.queue_quantity, 1000)
        self.assertEqual(recognized.queue_tier, 8)
        self.assertEqual(recognized.selected_tier, 8)
        self.assertIsNotNone(recognized.training_duration_seconds)
        self.assertGreater(recognized.training_duration_seconds, 0)
        self.assertEqual(recognized.diagnostics["duration_source"], "queue_band")
        self.assertEqual(recognized.diagnostics["duration_ocr_source"], "queue_timer_band")
        self.assertEqual(recognized.diagnostics["queue_timer_band"], QUEUE_TIMER_BAND)
        self.assertTrue(recognized.diagnostics["queue_spatially_associated"])

    def test_retained_rider_active_queue_accepts_selected_t8_with_queue_t1(self):
        frame_path = (
            Path(__file__).resolve().parents[1]
            / ".local-captures"
            / "flow-delivery"
            / "TROOP-TRAINING-END-TO-END-CONSOLIDATION"
            / "run-20260814T052918520044Z"
            / "troop-training-20260814T052919039487Z"
            / "frames"
            / "0010-tab-rider-post.png"
        )
        if not frame_path.is_file():
            self.skipTest("retained Rider active-queue frame unavailable")
        recognized = recognize_training(cv2.imread(str(frame_path), cv2.IMREAD_COLOR))
        self.assertTrue(recognized.recognized)
        self.assertTrue(recognized.queue_active)
        self.assertEqual(recognized.troop_type, "rider")
        self.assertEqual(recognized.selected_tier, 8)
        self.assertEqual(recognized.queue_tier, 1)
        self.assertEqual(recognized.queue_quantity, 250)
        self.assertIsNotNone(recognized.training_duration_seconds)
        self.assertGreater(recognized.training_duration_seconds, 0)

    def test_offscreen_tier_uses_only_contiguous_bound_window(self):
        visible = tuple(
            TierObservation(
                number,
                visible=True,
                unlocked=number < 9,
                selected=number == 8,
                question_mark=number >= 9,
                target_roi=(100 + number * 20, 825, 170 + number * 20, 975),
            )
            for number in (6, 7, 8, 9, 10)
        )
        current = replace(observation("rider", tier=8), visible_tiers=visible)
        controller = TrainingController(config(tier=1), reset_identity=RESET)
        self.assertEqual(controller.plan_tier(current, "rider"), "select_tier")
        gapped = replace(current, visible_tiers=(visible[0], visible[2]))
        self.assertEqual(controller.plan_tier(gapped, "rider"), "reject_ambiguous_tier")
        locked = replace(current, visible_tiers=(visible[0], replace(visible[1], question_mark=True)))
        self.assertEqual(controller.plan_tier(locked, "rider"), "reject_ambiguous_tier")

    def test_integrated_tier_selector_swipes_toward_offscreen_tier_and_rebinds(self):
        from scripts.troop_training_bluestacks import TroopTrainingIntegratedRoute

        visible = tuple(
            TierObservation(
                number,
                visible=True,
                unlocked=number < 9,
                selected=number == 8,
                question_mark=number >= 9,
                target_roi=(100 + number * 20, 825, 170 + number * 20, 975),
            )
            for number in (6, 7, 8, 9, 10)
        )
        current = replace(observation("rider", tier=8), visible_tiers=visible)
        selected = replace(observation("rider", tier=1), selected_tier=1)
        runtime = SimpleNamespace(swipes=[], swipe=lambda captured, *, start, end, action_key: runtime.swipes.append((start, end, action_key)))
        route = TroopTrainingIntegratedRoute.__new__(TroopTrainingIntegratedRoute)
        route.config = config(tier=1)
        route.controller = TroopTrainingRuntimeController(route.config, reset_identity=RESET)
        route.runtime = runtime
        route.max_tier_swipes = 2
        route.actions_completed = 0
        route._wait = lambda: None
        route._capture_training = lambda _label: (SimpleNamespace(sha256="b" * 64, frame=object()), selected)
        before = SimpleNamespace(sha256="a" * 64, frame=object())
        captured, result, error = route._select_tier(before, current, "rider")
        self.assertIsNotNone(captured)
        self.assertIsNone(error)
        self.assertEqual(result.selected_tier, 1)
        self.assertEqual(len(runtime.swipes), 1)
        self.assertLess(runtime.swipes[0][0][0], runtime.swipes[0][1][0])

    def test_retained_rider_tier_strip_marks_question_cards_locked(self):
        frame_path = Path(__file__).resolve().parents[1] / ".local-captures" / "flow-delivery" / "TROOP-TRAINING-END-TO-END-CONSOLIDATION" / "run-20260813T185728650296Z" / "troop-training-20260813T185729180830Z" / "frames" / "0020-rider-training-screen-source.png"
        if not frame_path.is_file():
            self.skipTest("retained Rider training frame unavailable")
        frame = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        recognized = recognize_training(frame)
        self.assertTrue(recognized.recognized)
        self.assertEqual(recognized.selected_tier, 8)
        self.assertTrue(recognized.tier(9).locked)
        self.assertTrue(recognized.tier(10).locked)
        rider_controller = TrainingController(config(tier=1), reset_identity=RESET)
        self.assertEqual(rider_controller.plan_tier(recognized, "rider"), "select_tier")

    def test_latest_retained_mixed_unlocked_window_ignores_higher_locked_cards(self):
        """T6-T8 are a safe lower-direction window despite locked T9/T10."""
        frame_path = Path(__file__).resolve().parents[1] / ".local-captures" / "flow-delivery" / "TROOP-TRAINING-END-TO-END-CONSOLIDATION" / "run-20260813T194304476354Z" / "troop-training-20260813T194305096396Z" / "frames" / "0006-rider-training-screen-source.png"
        if not frame_path.is_file():
            self.skipTest("latest retained mixed Rider training frame unavailable")
        frame = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        recognized = recognize_training(frame)
        self.assertTrue(recognized.recognized)
        self.assertEqual(recognized.selected_tier, 8)
        self.assertEqual(tuple(item.tier for item in recognized.visible_tiers), (6, 7, 8, 9, 10))
        self.assertTrue(all(not recognized.tier(tier).locked for tier in (6, 7, 8)))
        self.assertTrue(all(recognized.tier(tier).locked for tier in (9, 10)))
        self.assertIsNotNone(recognized.normal_train_target)
        self.assertEqual(recognized.diagnostics["duration_source"], "normal_train_band")
        self.assertIsNotNone(recognized.training_duration_seconds)
        self.assertGreater(recognized.training_duration_seconds, 0)
        self.assertFalse(recognized.queue_active)
        self.assertFalse(recognized.forbidden_controls)
        rider_controller = TrainingController(config(tier=1), reset_identity=RESET)
        self.assertEqual(rider_controller.plan_tier(recognized, "rider"), "select_tier")

    def test_latest_retained_rider_post_swipe_binds_visible_t1_from_card_text(self):
        """Post-swipe T1 is bound by each card's own label, not slot ordinal."""
        frame_root = Path(__file__).resolve().parents[1] / ".local-captures" / "flow-delivery" / "TROOP-TRAINING-END-TO-END-CONSOLIDATION" / "run-20260813T202455890793Z" / "troop-training-20260813T202456418961Z" / "frames"
        expected = {
            "0002-tier-swipe-rider-0-post.png": (50, 835, 195, 955),
            "0003-tier-swipe-rider-1-post.png": (185, 835, 330, 955),
        }
        for name, expected_roi in expected.items():
            frame_path = frame_root / name
            if not frame_path.is_file():
                self.skipTest(f"retained post-swipe Rider frame unavailable: {name}")
            recognized = recognize_training(cv2.imread(str(frame_path), cv2.IMREAD_COLOR))
            self.assertTrue(recognized.recognized, name)
            self.assertEqual(recognized.troop_type, "rider", name)
            tier_one = recognized.tier(1)
            self.assertIsNotNone(tier_one, name)
            self.assertTrue(tier_one.unlocked, name)
            self.assertFalse(tier_one.selected, name)
            # Independently measured from each retained native frame's T1 card.
            self.assertEqual(tier_one.target_roi, expected_roi, name)

    def test_visible_target_tier_is_tapped_before_any_additional_swipe(self):
        """Once T1 is visible, selection is a bound tap plus fresh selected revalidation."""
        from scripts.troop_training_bluestacks import TroopTrainingIntegratedRoute

        current = observation("rider", tier=3)
        current = replace(
            current,
            visible_tiers=tuple(
                TierObservation(
                    number,
                    visible=True,
                    unlocked=True,
                    selected=number == 3,
                    target_roi=(50 + number * 40, 835, 120 + number * 40, 955),
                )
                for number in (1, 2, 3, 4)
            ),
        )
        post = replace(observation("rider", tier=1), selected_tier=1)

        class Runtime:
            execute = True
            in_flight_action = None
            session = Path("tier-target-first")

            def __init__(self):
                self.inputs = []

            def tap(self, captured, *, target_identity, target_roi, action_key, **kwargs):
                self.inputs.append(("tap", target_identity, target_roi, action_key))

        runtime = Runtime()
        route = TroopTrainingIntegratedRoute.__new__(TroopTrainingIntegratedRoute)
        route.config = config(tier=1)
        route.controller = TroopTrainingRuntimeController(route.config, reset_identity=RESET)
        route.runtime = runtime
        route.max_tier_swipes = 2
        route.actions_completed = 0
        route._wait = lambda: None
        route._capture_training = lambda _label: (SimpleNamespace(sha256="b" * 64, frame=object()), post)
        before = SimpleNamespace(sha256="a" * 64, frame=object())

        captured, selected, error = route._select_tier(before, current, "rider")
        self.assertIsNotNone(captured)
        self.assertIsNone(error)
        self.assertEqual(selected.selected_tier, 1)
        self.assertEqual(len(runtime.inputs), 1)
        self.assertEqual(runtime.inputs[0][0], "tap")
        self.assertEqual(runtime.inputs[0][1], "tier:1")
        self.assertEqual(runtime.inputs[0][2], post.tier(1).target_roi)
        self.assertEqual(len([item for item in runtime.inputs if item[0] == "swipe"]), 0)

    def test_retained_rider_t1_visible_path_taps_bound_card_before_swipe(self):
        """The retained post-swipe frame takes the target-first branch."""
        frame_path = Path(__file__).resolve().parents[1] / ".local-captures" / "flow-delivery" / "TROOP-TRAINING-END-TO-END-CONSOLIDATION" / "run-20260813T202455890793Z" / "troop-training-20260813T202456418961Z" / "frames" / "0002-tier-swipe-rider-0-post.png"
        if not frame_path.is_file():
            self.skipTest("retained post-swipe Rider frame unavailable")
        current = recognize_training(cv2.imread(str(frame_path), cv2.IMREAD_COLOR))
        self.assertIsNotNone(current.tier(1))
        post = replace(observation("rider", tier=1), selected_tier=1)

        class Runtime:
            execute = True
            in_flight_action = None
            session = Path("retained-tier-target-first")

            def __init__(self):
                self.inputs = []

            def tap(self, captured, *, target_identity, target_roi, action_key, **kwargs):
                self.inputs.append(("tap", target_identity, target_roi, action_key))

        runtime = Runtime()
        route = TroopTrainingIntegratedRoute.__new__(TroopTrainingIntegratedRoute)
        route.config = config(tier=1)
        route.controller = TroopTrainingRuntimeController(route.config, reset_identity=RESET)
        route.runtime = runtime
        route.max_tier_swipes = 2
        route.actions_completed = 0
        route._wait = lambda: None
        route._capture_training = lambda _label: (SimpleNamespace(sha256="b" * 64, frame=object()), post)
        before = SimpleNamespace(sha256=current.frame_sha256, frame=cv2.imread(str(frame_path), cv2.IMREAD_COLOR))

        captured, selected, error = route._select_tier(before, current, "rider")
        self.assertIsNotNone(captured)
        self.assertIsNone(error)
        self.assertEqual(selected.selected_tier, 1)
        self.assertEqual(len(runtime.inputs), 1)
        self.assertEqual(runtime.inputs[0][0], "tap")
        self.assertEqual(runtime.inputs[0][2], post.tier(1).target_roi)
        self.assertFalse(any(item[0] == "swipe" for item in runtime.inputs))

    def test_latest_retained_rider_window_swipes_from_current_centers_and_rebinds(self):
        """The retained T6-T8 window drives one bounded lower-direction swipe."""
        from scripts.troop_training_bluestacks import TroopTrainingIntegratedRoute

        frame_path = Path(__file__).resolve().parents[1] / ".local-captures" / "flow-delivery" / "TROOP-TRAINING-END-TO-END-CONSOLIDATION" / "run-20260813T194304476354Z" / "troop-training-20260813T194305096396Z" / "frames" / "0006-rider-training-screen-source.png"
        if not frame_path.is_file():
            self.skipTest("latest retained mixed Rider training frame unavailable")
        current = recognize_training(cv2.imread(str(frame_path), cv2.IMREAD_COLOR))
        post = observation("rider", tier=1)

        class Runtime:
            execute = True
            in_flight_action = None
            session = Path("retained-rider-tier-strip")

            def __init__(self):
                self.inputs: list[tuple[str, object]] = []
                self.frame = CapturedNativeFrame(
                    np.zeros((1280, 800, 3), dtype=np.uint8),
                    b"native",
                    "n" * 64,
                    0.0,
                    Path("frame.png"),
                )

            def swipe(self, _frame, *, start, end, action_key):
                self.inputs.append(("swipe", (start, end, action_key)))

            def capture(self, _label):
                return self.frame

        runtime = Runtime()
        with TemporaryDirectory() as directory, patch(
            "scripts.troop_training_bluestacks.recognize_training", return_value=post
        ):
            route = TroopTrainingIntegratedRoute(
                runtime,
                config=config(tier=1),
                reset_identity=RESET,
                post_input_delay=0,
                max_tier_swipes=1,
                persistence_path=Path(directory) / "state.json",
            )
            selected_capture, selected, error = route._select_tier(runtime.frame, current, "rider")
        self.assertIsNotNone(selected_capture)
        self.assertIsNone(error)
        self.assertEqual(selected.selected_tier, 1)
        self.assertEqual(len(runtime.inputs), 1)
        start, end, _action = runtime.inputs[0][1]
        self.assertEqual(start, (122, 895))
        self.assertEqual(end, (680, 895))
        self.assertGreaterEqual(start[0], 100)
        self.assertLessEqual(end[0], 680)
        self.assertGreaterEqual(end[0] - start[0], 200)
        self.assertGreaterEqual(start[1], 840)
        self.assertLessEqual(start[1], 960)
        self.assertEqual(start[1], end[1])
        self.assertIn("training:navigation:swipe:rider:0", runtime.inputs[0][1][2])

    def test_latest_retained_rider_window_rejects_gapped_or_lower_locked_cards(self):
        """A missing unlocked card or lower locked card blocks before swipe."""
        from scripts.troop_training_bluestacks import TroopTrainingIntegratedRoute

        frame_path = Path(__file__).resolve().parents[1] / ".local-captures" / "flow-delivery" / "TROOP-TRAINING-END-TO-END-CONSOLIDATION" / "run-20260813T194304476354Z" / "troop-training-20260813T194305096396Z" / "frames" / "0006-rider-training-screen-source.png"
        if not frame_path.is_file():
            self.skipTest("latest retained mixed Rider training frame unavailable")
        current = recognize_training(cv2.imread(str(frame_path), cv2.IMREAD_COLOR))
        gapped = replace(current, visible_tiers=tuple(item for item in current.visible_tiers if item.tier != 7))
        lower_locked = replace(
            current,
            visible_tiers=(
                TierObservation(5, visible=True, unlocked=False, target_roi=(0, 835, 130, 955)),
                *current.visible_tiers,
            ),
        )
        controller = TrainingController(config(tier=1), reset_identity=RESET)
        self.assertEqual(controller.plan_tier(gapped, "rider"), "reject_ambiguous_tier")
        self.assertEqual(controller.plan_tier(lower_locked, "rider"), "reject_ambiguous_tier")

        class Runtime:
            execute = True
            in_flight_action = None
            session = Path("retained-rider-tier-strip")

            def __init__(self):
                self.inputs: list[object] = []

            def swipe(self, *_args, **_kwargs):
                self.inputs.append("swipe")

        for candidate in (gapped, lower_locked):
            runtime = Runtime()
            route = TroopTrainingIntegratedRoute.__new__(TroopTrainingIntegratedRoute)
            route.config = config(tier=1)
            route.controller = TroopTrainingRuntimeController(route.config, reset_identity=RESET)
            route.runtime = runtime
            route.max_tier_swipes = 1
            route.actions_completed = 0
            route._wait = lambda: None
            _, selected, error = route._select_tier(SimpleNamespace(sha256="a" * 64, frame=object()), candidate, "rider")
            self.assertIsNone(selected)
            self.assertIn(error, {"reject_ambiguous_tier", "visible tier strip is locked, gapped, or spatially ambiguous"})
            self.assertEqual(runtime.inputs, [])

    def test_stylized_tier_artifacts_are_bound_to_slot_text_not_position(self):
        from tasks.troop_training_vision import TIER_CARD_SLOTS, _tier_observations

        frame = np.full((1280, 800, 3), 255, dtype=np.uint8)
        slot_text = {TIER_CARD_SLOTS[0]: "18", TIER_CARD_SLOTS[1]: "16", TIER_CARD_SLOTS[2]: "17"}

        def fake_ocr(_frame, box=None, *, psm=11):
            return slot_text.get(box, "")

        with patch("tasks.troop_training_vision._ocr_boxes", return_value=[]), patch(
            "tasks.troop_training_vision._ocr", side_effect=fake_ocr
        ):
            tiers = _tier_observations(frame, "", 8)
        by_tier = {item.tier: item for item in tiers}
        self.assertEqual(set(by_tier), {6, 7, 8})
        self.assertEqual(by_tier[8].target_roi, TIER_CARD_SLOTS[0])
        self.assertEqual(by_tier[6].target_roi, TIER_CARD_SLOTS[1])
        self.assertEqual(by_tier[7].target_roi, TIER_CARD_SLOTS[2])
        self.assertTrue(all(item.unlocked for item in by_tier.values()))

    def test_rider_tier_swipe_stops_on_no_progress_without_retry(self):
        from scripts.troop_training_bluestacks import TroopTrainingIntegratedRoute

        visible = tuple(
            TierObservation(
                number,
                visible=True,
                unlocked=True,
                selected=number == 8,
                target_roi=(100 + number * 20, 825, 170 + number * 20, 975),
            )
            for number in (8, 9, 10)
        )
        current = replace(observation("rider", tier=8), visible_tiers=visible)

        class Runtime:
            execute = True
            in_flight_action = None
            session = Path("tier-no-progress")

            def __init__(self):
                self.inputs: list[object] = []
                self.frame = CapturedNativeFrame(
                    np.zeros((1280, 800, 3), dtype=np.uint8), b"native", "n" * 64, 0.0, Path("frame.png")
                )

            def swipe(self, _frame, *, start, end, action_key):
                self.inputs.append((start, end, action_key))

            def capture(self, _label):
                return self.frame

        runtime = Runtime()
        with TemporaryDirectory() as directory, patch(
            "scripts.troop_training_bluestacks.recognize_training", return_value=current
        ):
            route = TroopTrainingIntegratedRoute(
                runtime,
                config=config(tier=1),
                reset_identity=RESET,
                post_input_delay=0,
                max_tier_swipes=2,
                persistence_path=Path(directory) / "state.json",
            )
            _, selected, error = route._select_tier(runtime.frame, current, "rider")
        self.assertIsNone(selected)
        self.assertEqual(error, "tier swipe produced no bounded carousel progress")
        self.assertEqual(len(runtime.inputs), 1)

    def test_offscreen_rider_t1_uses_one_bounded_directional_tier_strip_swipe(self):
        """T1 navigation is directional and revalidated on a fresh selected card."""
        visible = tuple(
            TierObservation(
                number,
                visible=True,
                unlocked=True,
                selected=number == 8,
                target_roi=(100 + number * 20, 825, 170 + number * 20, 975),
            )
            for number in (8, 9, 10)
        )
        current = replace(observation("rider", tier=8), visible_tiers=visible)
        post = observation("rider", tier=1)

        class Runtime:
            execute = True
            in_flight_action = None
            session = Path("tier-strip")

            def __init__(self):
                self.inputs: list[tuple[str, object]] = []
                self.frame = CapturedNativeFrame(
                    np.zeros((1280, 800, 3), dtype=np.uint8),
                    b"native",
                    "n" * 64,
                    0.0,
                    Path("frame.png"),
                )

            def swipe(self, _frame, *, start, end, action_key):
                self.inputs.append(("swipe", (start, end, action_key)))

            def capture(self, _label):
                return self.frame

        runtime = Runtime()
        with TemporaryDirectory() as directory, patch(
            "scripts.troop_training_bluestacks.recognize_training", return_value=post
        ):
            route = TroopTrainingIntegratedRoute(
                runtime,
                config=config(tier=1),
                reset_identity=RESET,
                post_input_delay=0,
                max_tier_swipes=1,
                persistence_path=Path(directory) / "state.json",
            )
            selected_capture, selected, error = route._select_tier(runtime.frame, current, "rider")
        self.assertIsNotNone(selected_capture)
        self.assertIsNone(error)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.selected_tier, 1)
        self.assertTrue(selected.tier(1).unlocked)
        self.assertEqual(len(runtime.inputs), 1)
        self.assertEqual(runtime.inputs[0][0], "swipe")
        # The strip is bound from the current card centers, not a fixed screen
        # coordinate or an assumed swipe count.
        start, end, _action = runtime.inputs[0][1]
        self.assertGreaterEqual(start[0], 100)
        self.assertLessEqual(end[0], 680)
        self.assertGreaterEqual(end[0] - start[0], 160)
        self.assertGreaterEqual(start[1], 840)
        self.assertLessEqual(start[1], 960)
        self.assertEqual(start[1], end[1])

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

        with patch.object(
            TroopTrainingIntegratedRoute,
            "_navigate_selected_facility",
            return_value=(None, None, None, "dry-run-calculated-pan-not-dispatched"),
        ):
            result = TroopTrainingIntegratedRoute(FakeRuntime(), config=config(), reset_identity=RESET).run()
        self.assertEqual(result.status, "dry-run")
        self.assertEqual(result.actions_completed, 0)


if __name__ == "__main__":
    unittest.main()
