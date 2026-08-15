from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import pnsctl
from scripts.enhancement_bluestacks import (
    EnhancementIntegratedRoute,
    recognize_commander_stage,
    recognize_daily_frame,
    recognize_enhancement_frame,
)
from scripts.flow_delivery_enhancement_bluestacks import (
    FLOW_ID,
    MAX_DISPATCH_BEARING_CANARY_RUNS_PER_CATEGORY,
    _artifact_usage,
    _decode_native,
    _reserve,
    _verify_observation_binding,
    run_enhancement_family,
)
from tasks.enhancement import (
    BLUESTACKS_NATIVE_TARGET_PROVENANCE,
    BLUESTACKS_RUNTIME_PROFILE_ID,
    EnhancementObservation,
    enhancement_bluestacks_postcondition_verified,
)


# Deliberately independent from production search-bound constants.
TEST_GEOMETRY = {
    "daily": (120, 360, 280, 400),
    "daily_selected": (80, 350, 108, 410),
    "daily_go": (600, 360, 660, 400),
    "header": (220, 40, 410, 78),
    "gear": (120, 170, 180, 210),
    "chip": (220, 170, 280, 210),
    "module": (320, 170, 400, 210),
    "category_selected": (100, 170, 115, 210),
    "item": (180, 300, 390, 340),
    "equipped": (180, 375, 280, 410),
    "level": (180, 435, 280, 470),
    "material": (180, 750, 420, 790),
    "material_selected": (160, 750, 175, 790),
    "quantity": (180, 825, 320, 860),
    "open": (450, 900, 540, 950),
    "confirm": (450, 960, 560, 1010),
    "result": (180, 330, 430, 365),
    "result_far": (600, 700, 780, 740),
}


def _hit(text: str, key: str) -> dict[str, object]:
    return {"text": text, "bounds": TEST_GEOMETRY[key]}


def _engine(
    marker: int,
    *,
    material: str = "Gear Material One Star",
    result_key: str = "result",
):
    def engine(frame, _roi):
        current = int(frame[0, 0, 0])
        if current in (1, 9):
            progress = "1/1" if current == 9 else "0/1"
            return [
                _hit(f"Enhance Gear {progress}", "daily"),
                _hit("Selected", "daily_selected"),
                *([] if current == 9 else [_hit("Go", "daily_go")]),
            ]
        category = [
            _hit("Gear", "gear"),
            _hit("Chip", "chip"),
            _hit("Module", "module"),
            _hit("Selected", "category_selected"),
            _hit("Commander Info", "header"),
            _hit("Item: commander gear 1", "item"),
            _hit("Equipped", "equipped"),
            _hit("Level: 5" if current in (6, 7) else "Level: 4", "level"),
        ]
        if current == 2:
            return category + [_hit("Enhance", "open")]
        if current in (3, 4, 5):
            values = category + [
                _hit(material, "material"),
                _hit("Quantity: 1", "quantity"),
                _hit("Confirm", "confirm"),
            ]
            if current in (4, 5):
                values.append(_hit("Selected", "material_selected"))
            return values
        if current in (6, 7):
            return category + [
                _hit("Gear Material One Star", "material"),
                _hit("Quantity: 1", "quantity"),
                _hit("Result: commander gear 1", result_key),
            ]
        return category

    return engine


class _Runtime:
    execute = True

    def __init__(self, root: Path, markers: list[int]):
        self.session = root
        (root / "frames").mkdir(parents=True)
        self.frames = []
        for index, marker in enumerate(markers):
            frame = np.full((1280, 800, 3), marker, dtype=np.uint8)
            ok, encoded = cv2.imencode(".png", frame)
            assert ok
            path = root / "frames" / f"{index:02d}.png"
            path.write_bytes(encoded.tobytes())
            self.frames.append(
                __import__(
                    "scripts.bluestacks_native_runtime",
                    fromlist=["CapturedNativeFrame"],
                ).CapturedNativeFrame(
                    frame,
                    encoded.tobytes(),
                    __import__("hashlib").sha256(encoded.tobytes()).hexdigest(),
                    float(index),
                    path,
                )
            )
        self.index = 0
        self.events: list[dict[str, object]] = []
        self.taps: list[dict[str, object]] = []

    def capture(self, _label):
        frame = self.frames[self.index]
        self.index += 1
        self.events.append({"type": "capture", "sha256": frame.sha256})
        return frame

    def tap(self, source, **kwargs):
        self.taps.append(kwargs)
        self.events.append(
            {"type": "dispatch", "source_sha256": source.sha256, **kwargs}
        )

    def back(self, source, *, action_key, **_kwargs):
        self.events.append(
            {
                "type": "dispatch",
                "source_sha256": source.sha256,
                "target_identity": "android-back",
                "action_key": action_key,
            }
        )

    def reconcile(self, action_key, status, _post, reason):
        self.events.append(
            {
                "type": "reconcile",
                "action_key": action_key,
                "status": status,
                "reason": reason,
            }
        )

    def _event(self, kind, payload):
        self.events.append({"type": kind, **payload})


class NativeRecognitionTests(unittest.TestCase):
    def test_daily_entry_requires_selected_row_and_exact_progress(self):
        frame = np.ones((1280, 800, 3), dtype=np.uint8)
        self.assertTrue(
            recognize_daily_frame(
                frame,
                variant="gear",
                source_frame_sha256="a" * 64,
                ocr_engine=_engine(1),
            ).recognized
        )
        completed = np.full((1280, 800, 3), 9, dtype=np.uint8)
        self.assertFalse(
            recognize_daily_frame(
                completed,
                variant="gear",
                source_frame_sha256="a" * 64,
                ocr_engine=_engine(9),
            ).recognized
        )

    def test_all_visible_categories_require_requested_selected_marker(self):
        frame = np.full((1280, 800, 3), 2, dtype=np.uint8)
        result = recognize_commander_stage(
            frame,
            variant="gear",
            stage="item",
            source_frame_sha256="b" * 64,
            ocr_engine=_engine(2),
            game_day_id="day",
        )
        self.assertTrue(result.recognized)
        self.assertTrue(result.category_selected)
        self.assertIsNotNone(result.open_target)

    def test_wrong_category_and_absent_material_fail_closed(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        wrong = recognize_commander_stage(
            frame,
            variant="chip",
            stage="item",
            source_frame_sha256="c" * 64,
            ocr_engine=_engine(2),
            game_day_id="day",
        )
        absent = recognize_commander_stage(
            frame,
            variant="gear",
            stage="material",
            source_frame_sha256="d" * 64,
            ocr_engine=_engine(3, material="Module Material One Star"),
            game_day_id="day",
        )
        self.assertFalse(wrong.recognized)
        self.assertFalse(absent.recognized)

    def test_same_item_postcondition_rejects_unrelated_result(self):
        base = EnhancementObservation(
            screen_state="COMMANDER_INFO",
            selected_tab="GEAR",
            selected_item_kind="GEAR",
            selected_item_identity="commander-gear-1",
            item_equipped=True,
            item_level=4,
            target_identity="enhancement-confirm",
            target_roi=(100, 100, 180, 180),
            panel_bounds=(0, 0, 800, 1280),
            control_class="ENHANCE",
            enhance_control_visible=True,
            action_mode="ENHANCE",
            material_identity="gear-material-one-star",
            material_known=True,
            material_available=True,
            material_star=1,
            material_quantity=1,
            quantity=1,
            game_day_id="day",
            target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
            source_frame_sha256="e" * 64,
            runtime_profile_id=BLUESTACKS_RUNTIME_PROFILE_ID,
        )
        after = replace(
            base,
            item_level=5,
            enhancement_result_visible=True,
            result_identity="other-item",
            result_spatially_associated=True,
        )
        self.assertFalse(
            enhancement_bluestacks_postcondition_verified(base, after, variant="gear")
        )

    def test_result_spatial_association_uses_result_hit_geometry(self):
        frame = np.full((1280, 800, 3), 6, dtype=np.uint8)
        associated = recognize_commander_stage(
            frame,
            variant="gear",
            stage="post",
            source_frame_sha256="f" * 64,
            ocr_engine=_engine(6),
            game_day_id="day",
        )
        distant = recognize_commander_stage(
            frame,
            variant="gear",
            stage="post",
            source_frame_sha256="f" * 64,
            ocr_engine=_engine(6, result_key="result_far"),
            game_day_id="day",
        )
        self.assertTrue(associated.observation.result_spatially_associated)
        self.assertFalse(distant.observation.result_spatially_associated)

    def test_frame_recognizer_retains_supplied_native_reference(self):
        frame = np.full((1280, 800, 3), 6, dtype=np.uint8)
        reference = Path("frames/current-native.png")
        result = recognize_enhancement_frame(
            frame,
            variant="gear",
            source_frame_sha256="f" * 64,
            evidence_ref=reference,
            game_day_id="day",
            ocr_engine=_engine(6),
            postcondition=True,
        )
        self.assertEqual(result.observation.evidence_refs, (str(reference),))
        self.assertNotIn("retained-frame.png", result.observation.evidence_refs)


class RouteAndReservationTests(unittest.TestCase):
    def test_route_uses_fresh_multistage_binding_and_settled_poll(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = _Runtime(Path(folder), [1, 1, 2, 2, 3, 4, 5, 6, 7, 9])
            route = EnhancementIntegratedRoute(
                runtime, variant="gear", reset_identity="day", ocr_engine=_engine(1)
            )
            result = route.run()
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["resource_affecting_dispatch_count"], 1)
            self.assertEqual(
                [item["target_identity"] for item in runtime.taps],
                [
                    "daily-enhancement-go:gear",
                    "item-select:gear",
                    "open-enhance:gear",
                    "material-select:gear",
                    "enhancement-confirm",
                ],
            )
            self.assertNotEqual(
                result["source_frame_sha256"], result["terminal_frame_sha256"]
            )
            self.assertTrue(
                any(item["stage"] == "enhancement-settle-0" for item in route.stages)
            )
            self.assertFalse(any(item["consequential"] for item in runtime.taps))
            for field in ("final_before_observation", "immediate_post_observation"):
                references = result[field]["evidence_refs"]
                self.assertEqual(len(references), 1)
                retained = Path(references[0])
                self.assertTrue(retained.is_file())
                self.assertTrue(retained.is_relative_to(runtime.session))
                self.assertNotEqual(retained.name, "retained-frame.png")

    def test_observation_reference_must_match_declared_source_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = _Runtime(Path(folder), [1, 1, 2, 2, 3, 4, 5, 6, 7, 9])
            result = EnhancementIntegratedRoute(
                runtime,
                variant="gear",
                reset_identity="day",
                ocr_engine=_engine(1),
            ).run()
            observation = EnhancementObservation(**result["final_before_observation"])
            mismatched = replace(
                observation,
                evidence_refs=(str(runtime.frames[0].path),),
            )
            with self.assertRaisesRegex(
                pnsctl.OperatorError,
                "does not match its source",
            ):
                _verify_observation_binding(
                    mismatched,
                    runtime.session,
                    {frame.sha256 for frame in runtime.frames},
                    "final-before",
                )

    def test_reservation_survives_crash_and_counts_events_without_result(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / FLOW_ID
            reservation = _reserve(root, "gear")
            self.assertTrue(reservation.is_file())
            with self.assertRaisesRegex(pnsctl.OperatorError, "gear"):
                _reserve(root, "gear")
            (root / "run-chip-crash").mkdir()
            (root / "run-chip-crash" / "events.jsonl").write_text(
                json.dumps(
                    {"type": "dispatch", "target_identity": "enhancement-confirm"}
                )
                + "\n",
                encoding="utf-8",
            )
            usage = _artifact_usage(root)
            self.assertEqual(usage["gear"], 1)
            self.assertEqual(usage["chip"], 1)

    def test_real_png_decoding_rejects_arbitrary_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.png"
            path.write_bytes(b"serialized self agreement")
            with self.assertRaises(pnsctl.OperatorError):
                _decode_native(path)

    def test_dry_run_does_not_start_child(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(pnsctl, "BLUESTACKS_ARTIFACT_ROOT", Path(folder)),
            patch(
                "scripts.flow_delivery_enhancement_bluestacks.subprocess.run"
            ) as child,
        ):
            result = json.loads(
                run_enhancement_family(
                    {}, {"max_inputs": 2, "enhancement_variant": "module"}, live=False
                )
            )
        self.assertEqual(result["status"], "dry_run")
        child.assert_not_called()
        self.assertEqual(MAX_DISPATCH_BEARING_CANARY_RUNS_PER_CATEGORY, 1)


if __name__ == "__main__":
    unittest.main()
