from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import daily_row_claim_bluestacks as daily
from scripts import flow_delivery_control as control
from scripts import navigation_development_boundary as boundary
from scripts import pnsctl
from scripts.bluestacks_native_runtime import CapturedNativeFrame, LocalBlueStacksRuntime


def _frame(
    root: Path,
    label: str,
    *,
    age: float = 0.0,
    image: np.ndarray | None = None,
) -> CapturedNativeFrame:
    image = image if image is not None else np.zeros((1280, 800, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    payload = encoded.tobytes()
    path = root / f"{label}.png"
    path.write_bytes(payload)
    return CapturedNativeFrame(
        image,
        payload,
        hashlib.sha256(payload).hexdigest(),
        time.monotonic() - age,
        path,
    )


class FakeRuntime:
    execute = True
    frame_max_age_seconds = 30.0

    def __init__(self, root: Path, *, stale: bool = False) -> None:
        self.session = root / "runtime"
        self.session.mkdir(parents=True)
        self.events = self.session / "events.jsonl"
        self._root = root
        self._stale = stale
        self.labels: list[str] = []
        self.taps: list[dict[str, object]] = []
        self.input_count = 0

    def capture(self, label: str) -> CapturedNativeFrame:
        self.labels.append(label)
        captured = _frame(self.session, label, age=60.0 if self._stale else 0.0)
        with self.events.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "capture", "label": label}) + "\n")
        return captured

    def tap(
        self,
        source: CapturedNativeFrame,
        *,
        target_identity: str,
        target_roi: tuple[int, int, int, int],
        action_key: str,
        consequential: bool = False,
        continuation_of: str | None = None,
    ) -> None:
        self.taps.append(
            {
                "target_identity": target_identity,
                "target_roi": target_roi,
                "action_key": action_key,
                "consequential": consequential,
                "continuation_of": continuation_of,
                "source_sha256": source.sha256,
            }
        )
        delegated = boundary.current_delegated_runtime_context()
        if delegated is not None:
            delegated.reserve_input(
                action_identity=target_identity,
                action_class="navigation",
                consequence_class="navigation_only",
                source_evidence_hash=source.sha256,
                action_key=action_key,
            )
            delegated.mark_transported(action_key)
        self.input_count += 1
        with self.events.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "type": "dispatch",
                        "action_key": action_key,
                        "target_identity": target_identity,
                    }
                )
                + "\n"
            )


class VisualFakeRuntime(FakeRuntime):
    HOME_COMPONENT = (180, 1028, 231, 1078)

    def capture(self, label: str) -> CapturedNativeFrame:
        self.labels.append(label)
        image = np.zeros((1280, 800, 3), dtype=np.uint8)
        if label in {"home-source", "home-quest-entry-immediate-before"}:
            x0, y0, x1, y1 = self.HOME_COMPONENT
            cv2.rectangle(image, (x0, y0), (x1 - 1, y1 - 1), (0, 180, 255), -1)
            self.home_foreground = np.zeros((1280, 800), dtype=bool)
            self.home_foreground[y0:y1, x0:x1] = True
        else:
            cv2.rectangle(image, (280, 20), (500, 190), (0, 180, 255), -1)
        captured = _frame(self.session, label, image=image)
        with self.events.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "capture", "label": label}) + "\n")
        return captured


class ModalOCR:
    """Keep narrow target OCR valid while adding a modal to selected full frames."""

    def __init__(self, modal_full_calls: set[int]) -> None:
        self.modal_full_calls = modal_full_calls
        self.full_calls = 0

    @staticmethod
    def _data(tokens: list[tuple[str, int, int, int, int]]) -> dict[str, list[object]]:
        return {
            "text": [item[0] for item in tokens],
            "left": [item[1] for item in tokens],
            "top": [item[2] for item in tokens],
            "width": [item[3] for item in tokens],
            "height": [item[4] for item in tokens],
            "conf": ["95"] * len(tokens),
        }

    def __call__(self, image: np.ndarray) -> dict[str, list[object]]:
        if image.shape[0] == 2560:
            tokens: list[tuple[str, int, int, int, int]] = []
            if self.full_calls in self.modal_full_calls:
                tokens.append(("confirm", 280, 500, 240, 80))
            self.full_calls += 1
            return self._data(tokens)
        if image.shape[0] == 560:
            return self._data(
                [
                    ("world", 80, 160, 80, 40),
                    ("quest", 360, 160, 100, 40),
                    ("hero", 640, 160, 80, 40),
                ]
            )
        return self._data(
            [
                ("quest", 100, 5, 100, 40),
                ("daily", 700, 70, 100, 40),
            ]
        )


class ScriptedRecognizer:
    def __init__(self, *, selected_daily: bool = True) -> None:
        self.selected_daily = selected_daily
        self.calls: list[tuple[str, str]] = []

    @staticmethod
    def _recognition(
        state: str,
        identity: str | None,
        roi: tuple[int, int, int, int] | None,
    ) -> daily.FrameRecognition:
        return daily.FrameRecognition(
            state,
            state != daily.UNKNOWN_STATE,
            identity if state != daily.UNKNOWN_STATE else None,
            roi if state != daily.UNKNOWN_STATE else None,
            state,
            {"independent_test_semantics": True},
        )

    def _label(self, frame: np.ndarray) -> str:
        # The fake runtime uses zero-valued frames; the recognizer call order
        # is intentionally separate from production geometry constants.
        return str(len(self.calls))

    def recognize_home(self, frame: np.ndarray) -> daily.FrameRecognition:
        self.calls.append(("home", self._label(frame)))
        return self._recognition(
            daily.HOME_STATE,
            daily.HOME_QUEST_IDENTITY,
            (101, 1101, 207, 1187) if len(self.calls) == 1 else (127, 1118, 241, 1204),
        )

    def recognize_quest(self, frame: np.ndarray) -> daily.FrameRecognition:
        self.calls.append(("quest", self._label(frame)))
        if not self.selected_daily:
            return self._recognition(daily.UNKNOWN_STATE, None, None)
        return self._recognition(
            daily.QUEST_STATE,
            daily.QUEST_DAILY_IDENTITY,
            (304, 74, 492, 146),
        )

    def recognize_daily_selected(self, frame: np.ndarray) -> daily.FrameRecognition:
        self.calls.append(("daily", self._label(frame)))
        return self._recognition(
            daily.DAILY_SELECTED_STATE if self.selected_daily else daily.UNKNOWN_STATE,
            "daily-quest-selected" if self.selected_daily else None,
            (326, 78, 486, 152) if self.selected_daily else None,
        )


class DailyRowReconnaissanceTests(unittest.TestCase):
    def _session(self, root: Path) -> boundary.DevelopmentSession:
        return boundary.DevelopmentSession(
            owner="test-daily-row-recon",
            invocation_id="test-daily-row-recon",
            session_directory=root / "session",
            max_inputs=2,
        )

    def test_two_step_route_rebinds_current_geometry_and_retains_five_frames(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", Path(directory) / "lock.sqlite3"
        ):
            root = Path(directory)
            runtime = FakeRuntime(root)
            recognizer = ScriptedRecognizer()
            with self._session(root) as session:
                result = daily.run_daily_row_reconnaissance(
                    runtime,
                    session,
                    recognizer=recognizer,
                )

        self.assertEqual(result["status"], "observed")
        self.assertEqual(result["input_count"], 2)
        self.assertEqual(result["resource_affecting_inputs"], 0)
        self.assertEqual(result["combat_confirmations"], 0)
        self.assertEqual(
            runtime.labels,
            [
                "home-source",
                "home-quest-entry-immediate-before",
                "home-quest-entry-immediate-post",
                "quest-daily-tab-immediate-before",
                "quest-daily-tab-immediate-post",
            ],
        )
        self.assertEqual(
            [tap["target_identity"] for tap in runtime.taps],
            [daily.HOME_QUEST_IDENTITY, daily.QUEST_DAILY_IDENTITY],
        )
        self.assertEqual(runtime.taps[0]["target_roi"], (127, 1118, 241, 1204))
        self.assertEqual(runtime.taps[1]["target_roi"], (304, 74, 492, 146))
        self.assertEqual(
            set(result["frames"]),
            {
                "source",
                "home_immediate_before",
                "quest_successor",
                "daily_immediate_before",
                "daily_terminal",
            },
        )
        self.assertEqual(
            [row["label"] for row in result["actions"]],
            [daily.HOME_QUEST_IDENTITY, daily.QUEST_DAILY_IDENTITY],
        )

    def test_dispatched_home_quest_center_is_inside_rendered_component(self) -> None:
        label = (180, 1080, 230, 1100)
        rendered_component = VisualFakeRuntime.HOME_COMPONENT

        def ocr(image: np.ndarray) -> dict[str, list[object]]:
            if image.shape[0] != 560:
                return {
                    "text": [],
                    "left": [],
                    "top": [],
                    "width": [],
                    "height": [],
                    "conf": [],
                }
            return {
                "text": ["world", "quest", "hero"],
                "left": [80, label[0] * 2, 640],
                "top": [(label[1] - 1000) * 2] * 3,
                "width": [80, (label[2] - label[0]) * 2, 80],
                "height": [40, (label[3] - label[1]) * 2, 40],
                "conf": ["95", "95", "95"],
            }

        home_recognizer = daily.DailyRowClaimRecognizer(ocr=ocr)

        class HomeGeometryRecognizer(ScriptedRecognizer):
            def recognize_home(self, frame: np.ndarray) -> daily.FrameRecognition:
                return home_recognizer.recognize_home(frame)

        with tempfile.TemporaryDirectory() as directory, patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", Path(directory) / "lock.sqlite3"
        ):
            root = Path(directory)
            runtime = VisualFakeRuntime(root)
            with self._session(root) as session:
                result = daily.run_daily_row_reconnaissance(
                    runtime,
                    session,
                    recognizer=HomeGeometryRecognizer(),
                )

        self.assertEqual(result["status"], "observed")
        target = runtime.taps[0]["target_roi"]
        target_x0, target_y0, target_x1, target_y1 = target
        center_x = (target_x0 + target_x1) // 2
        center_y = (target_y0 + target_y1) // 2
        self.assertEqual((target_x1 - target_x0, target_y1 - target_y0), (3, 3))
        self.assertTrue(np.all(runtime.home_foreground[target_y0:target_y1, target_x0:target_x1]))
        self.assertTrue(runtime.home_foreground[center_y, center_x])
        self.assertLess(center_y, label[1])

    def test_unknown_quest_successor_stops_without_second_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", Path(directory) / "lock.sqlite3"
        ):
            root = Path(directory)
            runtime = FakeRuntime(root)
            recognizer = ScriptedRecognizer(selected_daily=False)
            with self._session(root) as session:
                result = daily.run_daily_row_reconnaissance(
                    runtime,
                    session,
                    recognizer=recognizer,
                )

        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(result["input_count"], 1)
        self.assertEqual(len(runtime.taps), 1)
        self.assertNotIn(daily.QUEST_DAILY_IDENTITY, [tap["target_identity"] for tap in runtime.taps])
        self.assertNotIn("daily_terminal", result["frames"])
        self.assertEqual(result["resource_affecting_inputs"], 0)
        self.assertEqual(result["combat_confirmations"], 0)

    def test_stale_immediate_before_stops_before_transport(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", Path(directory) / "lock.sqlite3"
        ):
            root = Path(directory)
            runtime = FakeRuntime(root, stale=True)
            with self._session(root) as session:
                result = daily.run_daily_row_reconnaissance(
                    runtime,
                    session,
                    recognizer=ScriptedRecognizer(),
                )

        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(len(runtime.taps), 0)
        self.assertIn("stale", result["reason"])

    def _run_with_full_frame_modal(self, modal_full_calls: set[int]):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", Path(directory) / "lock.sqlite3"
        ):
            root = Path(directory)
            runtime = VisualFakeRuntime(root)
            recognizer = daily.DailyRowClaimRecognizer(
                ocr=ModalOCR(modal_full_calls)
            )
            with self._session(root) as session:
                result = daily.run_daily_row_reconnaissance(
                    runtime,
                    session,
                    recognizer=recognizer,
                )
            return result, runtime

    def test_full_frame_modal_blocks_first_tap_with_valid_home_ocr(self) -> None:
        result, runtime = self._run_with_full_frame_modal({1})

        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(runtime.taps, [])
        self.assertIn("full-frame overlay/modal detected", result["reason"])

    def test_full_frame_modal_blocks_second_tap_with_valid_daily_ocr(self) -> None:
        result, runtime = self._run_with_full_frame_modal({3})

        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(
            [tap["target_identity"] for tap in runtime.taps],
            [daily.HOME_QUEST_IDENTITY],
        )
        self.assertIn("full-frame overlay/modal detected", result["reason"])


class DailyRowRecognizerTests(unittest.TestCase):
    @staticmethod
    def _ocr_for(tokens: list[tuple[str, int, int, int, int]]):
        def ocr(_image: np.ndarray):
            return {
                "text": [item[0] for item in tokens],
                "left": [item[1] for item in tokens],
                "top": [item[2] for item in tokens],
                "width": [item[3] for item in tokens],
                "height": [item[4] for item in tokens],
                "conf": ["95"] * len(tokens),
            }

        return ocr

    @staticmethod
    def _home_recognizer(
        *,
        quest: tuple[int, int, int, int] = (330, 1100, 390, 1120),
        left: tuple[int, int, int, int] = (180, 1100, 230, 1120),
        right: tuple[int, int, int, int] = (490, 1100, 540, 1120),
    ) -> daily.DailyRowClaimRecognizer:
        def scaled(token: tuple[str, tuple[int, int, int, int]]) -> tuple[str, int, int, int, int]:
            text, (x0, y0, x1, y1) = token
            return text, x0 * 2, (y0 - 1000) * 2, (x1 - x0) * 2, (y1 - y0) * 2

        return daily.DailyRowClaimRecognizer(
            ocr=DailyRowRecognizerTests._ocr_for(
                [
                    scaled(("world", left)),
                    scaled(("quest", quest)),
                    scaled(("hero", right)),
                ]
            )
        )

    @staticmethod
    def _home_frame() -> np.ndarray:
        return np.zeros((1280, 800, 3), dtype=np.uint8)

    def _assert_supported_point(
        self,
        recognition: daily.FrameRecognition,
        foreground: np.ndarray,
        *,
        quest_roi: tuple[int, int, int, int] = (330, 1100, 390, 1120),
    ) -> None:
        self.assertTrue(recognition.recognized)
        target = recognition.target_roi
        self.assertIsNotNone(target)
        self.assertEqual((target[2] - target[0], target[3] - target[1]), (3, 3))
        self.assertTrue(np.all(foreground[target[1] : target[3], target[0] : target[2]]))
        binding = recognition.visual_evidence["quest_binding"]
        self.assertEqual(len(binding["component_roi"]), 4)
        self.assertEqual(binding["quest_ocr_roi"], quest_roi)
        self.assertIn("ownership_lane", binding)
        self.assertIn("icon_band", binding)
        self.assertIn("selected_point", binding)
        self.assertGreater(binding["clearance"], 0.0)
        self.assertEqual(binding["raw_support_result"]["complete_3x3"], True)

    def test_home_and_quest_targets_are_derived_from_current_ocr_geometry(self) -> None:
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        rendered_component = (175, 1038, 226, 1089)
        label = (175, 1100, 225, 1120)
        cv2.rectangle(
            frame,
            rendered_component[:2],
            (rendered_component[2] - 1, rendered_component[3] - 1),
            (0, 180, 255),
            -1,
        )
        home = daily.DailyRowClaimRecognizer(
            ocr=self._ocr_for(
                [
                    ("world", 40 * 2, (label[1] - 1000) * 2, 80, 40),
                    ("quest", label[0] * 2, (label[1] - 1000) * 2, (label[2] - label[0]) * 2, 40),
                    ("hero", 320 * 2, (label[1] - 1000) * 2, 80, 40),
                ]
            )
        ).recognize_home(frame)
        self.assertTrue(home.recognized)
        self.assertEqual(home.target_identity, daily.HOME_QUEST_IDENTITY)
        target = home.target_roi
        self.assertEqual((target[2] - target[0], target[3] - target[1]), (3, 3))
        center_x = (target[0] + target[2]) // 2
        center_y = (target[1] + target[3]) // 2
        self.assertGreaterEqual(center_x, rendered_component[0])
        self.assertLess(center_x, rendered_component[2])
        self.assertGreaterEqual(center_y, rendered_component[1])
        self.assertLess(center_y, rendered_component[3])

        cv2.rectangle(frame, (240, 40), (560, 185), (0, 180, 255), -1)
        quest = daily.DailyRowClaimRecognizer(
            ocr=self._ocr_for(
                [
                    ("quest", 340, 10, 70, 20),
                    ("daily", 820, 70, 140, 20),
                ]
            )
        ).recognize_quest(frame)
        self.assertTrue(quest.recognized)
        self.assertEqual(quest.target_identity, daily.QUEST_DAILY_IDENTITY)
        self.assertTrue(quest.target_roi[0] < 410 < quest.target_roi[2])

    def test_home_quest_target_tracks_moved_ocr_x_geometry(self) -> None:
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        fixtures = (
            ((224, 1048, 275, 1092), (224, 1100, 274, 1120)),
            ((424, 1048, 475, 1092), (424, 1100, 474, 1120)),
        )
        targets = []
        for rendered_component, label in fixtures:
            frame = np.zeros((1280, 800, 3), dtype=np.uint8)
            cv2.rectangle(
                frame,
                rendered_component[:2],
                (rendered_component[2] - 1, rendered_component[3] - 1),
                (0, 180, 255),
                -1,
            )
            recognition = daily.DailyRowClaimRecognizer(
                ocr=self._ocr_for(
                    [
                        ("world", (label[0] - 140) * 2, (label[1] - 1000) * 2, 80, 40),
                        (
                            "quest",
                            label[0] * 2,
                            (label[1] - 1000) * 2,
                            (label[2] - label[0]) * 2,
                            (label[3] - label[1]) * 2,
                        ),
                        ("hero", (label[2] + 100) * 2, (label[1] - 1000) * 2, 80, 40),
                    ]
                )
            ).recognize_home(frame)
            self.assertTrue(recognition.recognized)
            target = recognition.target_roi
            targets.append(target)
            center_x = (target[0] + target[2]) // 2
            center_y = (target[1] + target[3]) // 2
            self.assertEqual((target[2] - target[0], target[3] - target[1]), (3, 3))
            self.assertGreaterEqual(center_x, rendered_component[0])
            self.assertLess(center_x, rendered_component[2])
            self.assertGreaterEqual(center_y, rendered_component[1])
            self.assertLess(center_y, rendered_component[3])
            self.assertLess(center_y, label[1])

        first, second = targets
        self.assertEqual(
            (second[0] + second[2]) // 2 - (first[0] + first[2]) // 2,
            ((fixtures[1][0][0] + fixtures[1][0][2]) // 2)
            - ((fixtures[0][0][0] + fixtures[0][0][2]) // 2),
        )

    def test_ring_u_and_concave_controls_choose_raw_supported_points(self) -> None:
        shapes = ("ring", "u", "concave")
        for shape in shapes:
            with self.subTest(shape=shape):
                frame = self._home_frame()
                foreground = np.zeros((1280, 800), dtype=np.uint8)
                if shape == "ring":
                    cv2.circle(frame, (360, 1060), 30, (0, 180, 255), 8)
                    cv2.circle(foreground, (360, 1060), 30, 255, 8)
                elif shape == "u":
                    points = ((330, 1030), (330, 1078), (390, 1078), (390, 1030))
                    cv2.polylines(frame, [np.array(points)], False, (0, 180, 255), 10)
                    cv2.polylines(foreground, [np.array(points)], False, 255, 10)
                else:
                    points = np.array(
                        [[330, 1030], [390, 1030], [390, 1042], [342, 1042], [342, 1078], [330, 1078]]
                    )
                    cv2.fillPoly(frame, [points], (0, 180, 255))
                    cv2.fillPoly(foreground, [points], 255)

                recognition = self._home_recognizer().recognize_home(frame)
                self._assert_supported_point(recognition, foreground)
                binding = recognition.visual_evidence["quest_binding"]
                component = binding["component_roi"]
                bbox_center = ((component[0] + component[2]) // 2, (component[1] + component[3]) // 2)
                self.assertFalse(bool(foreground[bbox_center[1], bbox_center[0]]))

    def test_translated_adjacent_labels_and_control_translate_selected_point(self) -> None:
        points: list[tuple[int, int]] = []
        for shift in (0, 137):
            frame = self._home_frame()
            foreground = np.zeros((1280, 800), dtype=np.uint8)
            x0, y0, x1, y1 = (330 + shift, 1038, 390 + shift, 1082)
            cv2.rectangle(frame, (x0, y0), (x1 - 1, y1 - 1), (0, 180, 255), -1)
            cv2.rectangle(foreground, (x0, y0), (x1 - 1, y1 - 1), 255, -1)
            recognition = self._home_recognizer(
                quest=(330 + shift, 1100, 390 + shift, 1120),
                left=(180 + shift, 1100, 230 + shift, 1120),
                right=(490 + shift, 1100, 540 + shift, 1120),
            ).recognize_home(frame)
            self._assert_supported_point(
                recognition,
                foreground,
                quest_roi=(330 + shift, 1100, 390 + shift, 1120),
            )
            points.append(recognition.visual_evidence["quest_binding"]["selected_point"])

        self.assertEqual(points[1][0] - points[0][0], 137)
        self.assertEqual(points[1][1], points[0][1])

    def test_neighbor_lane_distractor_is_ignored(self) -> None:
        frame = self._home_frame()
        foreground = np.zeros((1280, 800), dtype=np.uint8)
        cv2.rectangle(frame, (330, 1038), (389, 1081), (0, 180, 255), -1)
        cv2.rectangle(foreground, (330, 1038), (389, 1081), 255, -1)
        cv2.rectangle(frame, (220, 1038), (270, 1081), (0, 180, 255), -1)
        recognition = self._home_recognizer().recognize_home(frame)

        self._assert_supported_point(recognition, foreground)
        binding = recognition.visual_evidence["quest_binding"]
        self.assertGreaterEqual(binding["component_roi"][0], 282)
        self.assertGreaterEqual(binding["selected_point"][0], 330)

    def test_raw_gap_rejects_morphology_only_bridge(self) -> None:
        frame = self._home_frame()
        cv2.rectangle(frame, (330, 1040), (349, 1070), (0, 180, 255), -1)
        cv2.rectangle(frame, (355, 1040), (374, 1070), (0, 180, 255), -1)
        recognition = self._home_recognizer().recognize_home(frame)

        self.assertFalse(recognition.recognized)
        self.assertEqual(
            recognition.visual_evidence["quest_binding"]["reason"],
            "ambiguous_home_quest_visual_components",
        )

    def test_home_quest_rejects_missing_labels_no_support_boundary_broad_thin_and_ambiguous(self) -> None:
        missing_labels = self._home_frame()
        missing_recognition = daily.DailyRowClaimRecognizer(
            ocr=self._ocr_for(
                [
                    ("world", 180 * 2, 100 * 2, 100, 40),
                    ("quest", 330 * 2, 100 * 2, 120, 40),
                ]
            )
        ).recognize_home(missing_labels)
        self.assertFalse(missing_recognition.recognized)
        self.assertEqual(
            missing_recognition.visual_evidence["quest_binding"]["reason"],
            "quest_and_adjacent_navigation_labels_not_proven",
        )

        cases: list[tuple[str, np.ndarray]] = []
        cases.append(("no_support", self._home_frame()))

        boundary = self._home_frame()
        cv2.rectangle(boundary, (282, 1040), (320, 1070), (0, 180, 255), -1)
        cases.append(("boundary", boundary))

        broad = self._home_frame()
        cv2.rectangle(broad, (290, 1040), (429, 1070), (0, 180, 255), -1)
        cases.append(("broad", broad))

        thin = self._home_frame()
        cv2.rectangle(thin, (355, 1040), (358, 1090), (0, 180, 255), -1)
        cases.append(("thin", thin))

        ambiguous = self._home_frame()
        cv2.rectangle(ambiguous, (330, 1040), (349, 1070), (0, 180, 255), -1)
        cv2.rectangle(ambiguous, (371, 1040), (390, 1070), (0, 180, 255), -1)
        cases.append(("ambiguous", ambiguous))

        for name, frame in cases:
            with self.subTest(case=name):
                recognition = self._home_recognizer().recognize_home(frame)
                self.assertFalse(recognition.recognized)
                if name == "ambiguous":
                    self.assertEqual(
                        recognition.visual_evidence["quest_binding"]["reason"],
                        "ambiguous_home_quest_visual_components",
                    )
                else:
                    self.assertEqual(
                        recognition.visual_evidence["quest_binding"]["reason"],
                        "no_unique_home_quest_visual_component",
                    )

    def test_home_quest_requires_a_visible_component(self) -> None:
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        label = (250, 1098, 310, 1118)
        recognition = daily.DailyRowClaimRecognizer(
            ocr=self._ocr_for(
                [
                    ("world", 100 * 2, (label[1] - 1000) * 2, 80, 40),
                    ("quest", label[0] * 2, (label[1] - 1000) * 2, 120, 40),
                    ("hero", 450 * 2, (label[1] - 1000) * 2, 80, 40),
                ]
            )
        ).recognize_home(frame)

        self.assertFalse(recognition.recognized)
        self.assertEqual(
            recognition.visual_evidence["quest_binding"]["reason"],
            "no_unique_home_quest_visual_component",
        )

    def test_home_quest_rejects_ambiguous_visible_components(self) -> None:
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        rendered_components = ((255, 1048, 280, 1080), (300, 1048, 325, 1080))
        for component in rendered_components:
            cv2.rectangle(
                frame,
                component[:2],
                (component[2] - 1, component[3] - 1),
                (0, 180, 255),
                -1,
            )
        label = (250, 1098, 320, 1118)
        recognition = daily.DailyRowClaimRecognizer(
            ocr=self._ocr_for(
                [
                    ("world", 120 * 2, (label[1] - 1000) * 2, 80, 40),
                    ("quest", label[0] * 2, (label[1] - 1000) * 2, 140, 40),
                    ("hero", 420 * 2, (label[1] - 1000) * 2, 80, 40),
                ]
            )
        ).recognize_home(frame)

        self.assertFalse(recognition.recognized)
        self.assertEqual(
            recognition.visual_evidence["quest_binding"]["reason"],
            "ambiguous_home_quest_visual_components",
        )

    def test_selected_daily_requires_spatial_main_comparison(self) -> None:
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        cv2.rectangle(frame, (360, 55), (520, 145), (0, 210, 255), -1)
        recognition = daily.DailyRowClaimRecognizer(
            ocr=self._ocr_for(
                [
                    ("main", 100, 70, 70, 20),
                    ("daily", 820, 70, 140, 20),
                ]
            )
        ).recognize_daily_selected(frame)
        self.assertTrue(recognition.recognized)
        self.assertEqual(recognition.state, daily.DAILY_SELECTED_STATE)
        self.assertGreater(
            recognition.visual_evidence["selected_margin"],
            0.015,
        )

    def test_catalog_parser_exposes_frozen_command_bindings(self) -> None:
        parsed = pnsctl.parser().parse_args(
            [
                "development-session",
                "daily-row-reconnaissance",
                "--max-inputs",
                "2",
                "--delegated-receipt",
                "receipt.sqlite3",
                "--agent-identity",
                "luna-agent",
                "--task-id",
                "daily-row-claim",
                "--flow-id",
                "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                "--scenario",
                "selected-daily-row-evidence",
                "--variant",
                "home-quest-daily",
            ]
        )
        self.assertEqual(parsed.development_command, "daily-row-reconnaissance")
        self.assertEqual(parsed.max_inputs, 2)
        self.assertEqual(parsed.task_id, "daily-row-claim")


class PnsctlDailyRowCommandTests(unittest.TestCase):
    def test_receipt_bound_command_records_observed_terminal_after_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "receipts.sqlite3"
            command = [
                "development-session",
                "daily-row-reconnaissance",
                "--max-inputs",
                "2",
                "--delegated-receipt",
                str(state),
                "--agent-identity",
                "luna-agent",
                "--task-id",
                "daily-row-claim",
                "--flow-id",
                "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                "--scenario",
                "selected-daily-row-evidence",
                "--variant",
                "home-quest-daily",
            ]
            controller = control.DelegatedRuntimeReceiptController(state)
            controller._candidate = lambda: ("head", "fingerprint")  # type: ignore[method-assign]
            controller.issue(
                task_id="daily-row-claim",
                flow_id="DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                receipt_class="reconnaissance",
                agent_identity="luna-agent",
                command_argv=command,
                scenario="selected-daily-row-evidence",
                variant="home-quest-daily",
                permitted_action_identities=["home-quest-entry", "quest-daily-tab"],
                permitted_action_classes=["navigation", "navigation"],
                consequence_class="navigation_only",
                max_total_inputs=2,
                max_resource_affecting_inputs=0,
                max_combat_confirmations=0,
                permitted_terminal_states=["observed", "evidence_required"],
                result_identity=pnsctl.DAILY_ROW_RECON_RESULT_IDENTITY,
            )

            def connect(**kwargs):
                return FakeRuntime(Path(kwargs["output_directory"]))

            with patch.object(
                pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"
            ), patch.object(
                pnsctl, "DEVELOPMENT_CHECKPOINT_PATHS", ()
            ), patch.object(
                control,
                "DelegatedRuntimeReceiptController",
                return_value=controller,
            ), patch.object(
                LocalBlueStacksRuntime,
                "connect",
                side_effect=connect,
            ), patch.object(
                daily,
                "DailyRowClaimRecognizer",
                return_value=ScriptedRecognizer(),
            ), patch.object(
                boundary,
                "RUNTIME_INPUT_LOCK_PATH",
                root / "lock.sqlite3",
            ):
                output = pnsctl.development_session_daily_row_reconnaissance(
                    max_inputs=2,
                    delegated_receipt=state,
                    agent_identity="luna-agent",
                    task_id="daily-row-claim",
                    flow_id="DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                    scenario="selected-daily-row-evidence",
                    variant="home-quest-daily",
                    command_argv=command,
                )

            result = json.loads(output)
            self.assertEqual(result["status"], "observed")
            self.assertEqual(result["input_count"], 2)
            self.assertTrue(result["ownership_released"])
            self.assertEqual(controller.inspect()["status"], "consumed")
            connection = controller._connection()
            try:
                terminal = connection.execute(
                    "SELECT status FROM delegated_results WHERE receipt_id=?",
                    (result["receipt_id"],),
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(terminal[0], "observed")

    def test_daily_recon_failure_records_terminal_before_fallback_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "receipts.sqlite3"
            command = [
                "development-session",
                "daily-row-reconnaissance",
                "--max-inputs",
                "2",
                "--delegated-receipt",
                str(state),
                "--agent-identity",
                "luna-agent",
                "--task-id",
                "daily-row-claim",
                "--flow-id",
                "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                "--scenario",
                "selected-daily-row-evidence",
                "--variant",
                "home-quest-daily",
            ]
            controller = control.DelegatedRuntimeReceiptController(state)
            controller._candidate = lambda: ("head", "fingerprint")  # type: ignore[method-assign]
            receipt = controller.issue(
                task_id="daily-row-claim",
                flow_id="DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                receipt_class="reconnaissance",
                agent_identity="luna-agent",
                command_argv=command,
                scenario="selected-daily-row-evidence",
                variant="home-quest-daily",
                permitted_action_identities=["home-quest-entry", "quest-daily-tab"],
                permitted_action_classes=["navigation", "navigation"],
                consequence_class="navigation_only",
                max_total_inputs=2,
                max_resource_affecting_inputs=0,
                max_combat_confirmations=0,
                permitted_terminal_states=["observed", "evidence_required"],
                result_identity=pnsctl.DAILY_ROW_RECON_RESULT_IDENTITY,
            )

            with patch.object(
                pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"
            ), patch.object(
                pnsctl, "DEVELOPMENT_CHECKPOINT_PATHS", ()
            ), patch.object(
                control,
                "DelegatedRuntimeReceiptController",
                return_value=controller,
            ), patch.object(
                LocalBlueStacksRuntime,
                "connect",
                side_effect=pnsctl.OperatorError("observation failed"),
            ), patch.object(
                pnsctl,
                "_write_daily_recon_artifacts",
                side_effect=OSError("fallback artifact write failed"),
            ), patch.object(
                boundary,
                "RUNTIME_INPUT_LOCK_PATH",
                root / "lock.sqlite3",
            ):
                with self.assertRaisesRegex(
                    pnsctl.OperatorError, "observation failed"
                ):
                    pnsctl.development_session_daily_row_reconnaissance(
                        max_inputs=2,
                        delegated_receipt=state,
                        agent_identity="luna-agent",
                        task_id="daily-row-claim",
                        flow_id="DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                        scenario="selected-daily-row-evidence",
                        variant="home-quest-daily",
                        command_argv=command,
                    )

            connection = controller._connection()
            try:
                terminal = connection.execute(
                    "SELECT status, payload_json FROM delegated_results WHERE receipt_id=?",
                    (receipt["receipt_id"],),
                ).fetchone()
            finally:
                connection.close()
            self.assertIsNotNone(terminal)
            self.assertEqual(terminal[0], "evidence_required")
            self.assertEqual(json.loads(terminal[1])["status"], "evidence_required")
            with self.assertRaisesRegex(control.FlowDeliveryError, "terminal result"):
                controller.record_result(
                    receipt,
                    status="observed",
                    result_identity=pnsctl.DAILY_ROW_RECON_RESULT_IDENTITY,
                    payload={},
                )


if __name__ == "__main__":
    unittest.main()
