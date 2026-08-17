from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import time
from typing import Callable
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
            cv2.rectangle(image, (0, 60), (267, 145), (0, 180, 255), -1)
            cv2.rectangle(image, (268, 60), (533, 145), (70, 70, 70), -1)
            cv2.rectangle(image, (534, 60), (799, 145), (70, 70, 70), -1)
        captured = _frame(self.session, label, image=image)
        with self.events.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "capture", "label": label}) + "\n")
        return captured


class MainAbsentContinuationRuntime(FakeRuntime):
    def capture(self, label: str) -> CapturedNativeFrame:
        self.labels.append(label)
        image = np.zeros((1280, 800, 3), dtype=np.uint8)
        daily_selected = label.startswith("quest-daily-tab-immediate-post") or label.startswith(
            "quest-daily-tab-poll-"
        )
        main_color = (70, 70, 70) if daily_selected else (0, 180, 255)
        daily_color = (0, 180, 255) if daily_selected else (70, 70, 70)
        cv2.rectangle(image, (0, 60), (267, 145), main_color, -1)
        cv2.rectangle(image, (268, 60), (533, 145), daily_color, -1)
        cv2.rectangle(image, (534, 60), (799, 145), (70, 70, 70), -1)
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
                ("daily", 640, 136, 140, 56),
                ("quest", 804, 138, 160, 48),
                ("alliance", 1236, 114, 190, 36),
                ("activity", 1248, 168, 172, 44),
                ("Recom'd", 672, 288, 256, 52),
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

    def recognize_main_quest(self, frame: np.ndarray) -> daily.FrameRecognition:
        return self.recognize_quest(frame)

    def recognize_daily_selected(self, frame: np.ndarray) -> daily.FrameRecognition:
        self.calls.append(("daily", self._label(frame)))
        return self._recognition(
            daily.DAILY_SELECTED_STATE if self.selected_daily else daily.UNKNOWN_STATE,
            "daily-quest-selected" if self.selected_daily else None,
            (326, 78, 486, 152) if self.selected_daily else None,
        )


class LabelSettlingRecognizer(ScriptedRecognizer):
    def __init__(
        self,
        *,
        quest_ready_label: str | None = None,
        daily_ready_label: str | None = None,
        main_source_state: str = daily.QUEST_STATE,
    ) -> None:
        super().__init__(selected_daily=True)
        self.quest_ready_after = (
            2 if quest_ready_label == "home-quest-entry-poll-01" else 999
            if quest_ready_label is not None
            else 1
        )
        self.daily_ready_after = (
            2 if daily_ready_label == "quest-daily-tab-poll-01" else 999
            if daily_ready_label is not None
            else 1
        )
        self.main_source_state = main_source_state

    def recognize_quest(self, frame: np.ndarray) -> daily.FrameRecognition:
        self.quest_calls = getattr(self, "quest_calls", 0) + 1
        if self.quest_calls <= self.quest_ready_after:
            if self.quest_calls < self.quest_ready_after:
                return self._recognition(daily.UNKNOWN_STATE, None, None)
        return self._recognition(
            daily.QUEST_STATE,
            daily.QUEST_DAILY_IDENTITY,
            (304, 74, 492, 146),
        )

    def recognize_main_quest(self, frame: np.ndarray) -> daily.FrameRecognition:
        if self.main_source_state != daily.QUEST_STATE:
            return self._recognition(self.main_source_state, None, None)
        return self._recognition(
            daily.QUEST_STATE,
            daily.QUEST_DAILY_IDENTITY,
            (304, 74, 492, 146),
        )

    def recognize_daily_selected(self, frame: np.ndarray) -> daily.FrameRecognition:
        self.daily_calls = getattr(self, "daily_calls", 0) + 1
        if self.daily_calls <= self.daily_ready_after:
            if self.daily_calls < self.daily_ready_after:
                return self._recognition(daily.UNKNOWN_STATE, None, None)
        return self._recognition(
            daily.DAILY_SELECTED_STATE,
            "daily-quest-selected",
            (326, 78, 486, 152),
        )


class DailyRowReconnaissanceTests(unittest.TestCase):
    def _session(self, root: Path) -> boundary.DevelopmentSession:
        return boundary.DevelopmentSession(
            owner="test-daily-row-recon",
            invocation_id="test-daily-row-recon",
            session_directory=root / "session",
            max_inputs=2,
        )

    def _continuation_session(self, root: Path) -> boundary.DevelopmentSession:
        return boundary.DevelopmentSession(
            owner="test-daily-row-continuation",
            invocation_id="test-daily-row-continuation",
            session_directory=root / "session",
            max_inputs=1,
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

    def test_delayed_quest_successor_polls_without_repeating_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", Path(directory) / "lock.sqlite3"
        ), patch.object(daily, "SUCCESSOR_POLL_INTERVAL_SECONDS", 0.0), patch.object(
            daily, "SUCCESSOR_POLL_TIMEOUT_SECONDS", 1.0
        ):
            root = Path(directory)
            runtime = FakeRuntime(root)
            recognizer = LabelSettlingRecognizer(
                quest_ready_label="home-quest-entry-poll-01"
            )
            with self._session(root) as session:
                result = daily.run_daily_row_reconnaissance(
                    runtime, session, recognizer=recognizer
                )

        self.assertEqual(result["status"], "observed")
        self.assertEqual(
            [tap["target_identity"] for tap in runtime.taps],
            [daily.HOME_QUEST_IDENTITY, daily.QUEST_DAILY_IDENTITY],
        )
        self.assertEqual(
            [poll["label"] for poll in result["polls"] if poll["action_identity"] == daily.HOME_QUEST_IDENTITY],
            ["home-quest-entry-immediate-post", "home-quest-entry-poll-01"],
        )

    def test_delayed_daily_successor_polls_without_repeating_daily(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", Path(directory) / "lock.sqlite3"
        ), patch.object(daily, "SUCCESSOR_POLL_INTERVAL_SECONDS", 0.0), patch.object(
            daily, "SUCCESSOR_POLL_TIMEOUT_SECONDS", 1.0
        ):
            root = Path(directory)
            runtime = FakeRuntime(root)
            recognizer = LabelSettlingRecognizer(
                daily_ready_label="quest-daily-tab-poll-01"
            )
            with self._session(root) as session:
                result = daily.run_daily_row_reconnaissance(
                    runtime, session, recognizer=recognizer
                )

        self.assertEqual(result["status"], "observed")
        self.assertEqual(len(runtime.taps), 2)
        self.assertEqual(
            [poll["label"] for poll in result["polls"] if poll["action_identity"] == daily.QUEST_DAILY_IDENTITY],
            ["quest-daily-tab-immediate-post", "quest-daily-tab-poll-01"],
        )

    def test_poll_timeout_does_not_dispatch_an_extra_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", Path(directory) / "lock.sqlite3"
        ), patch.object(daily, "SUCCESSOR_POLL_INTERVAL_SECONDS", 0.0), patch.object(
            daily, "SUCCESSOR_POLL_TIMEOUT_SECONDS", 1.0
        ), patch.object(daily, "SUCCESSOR_POLL_MAX_ATTEMPTS", 2):
            root = Path(directory)
            runtime = FakeRuntime(root)
            recognizer = LabelSettlingRecognizer(
                daily_ready_label="never-observed"
            )
            with self._session(root) as session:
                result = daily.run_daily_row_reconnaissance(
                    runtime, session, recognizer=recognizer
                )

        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(len(runtime.taps), 2)
        self.assertEqual(
            len(
                [
                    poll
                    for poll in result["polls"]
                    if poll["action_identity"] == daily.QUEST_DAILY_IDENTITY
                ]
            ),
            3,
        )

    def test_continuation_starts_on_main_quest_and_dispatches_only_daily(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", Path(directory) / "lock.sqlite3"
        ):
            root = Path(directory)
            runtime = FakeRuntime(root)
            recognizer = LabelSettlingRecognizer()
            with self._continuation_session(root) as session:
                result = daily.run_quest_daily_continuation(
                    runtime, session, recognizer=recognizer
                )

        self.assertEqual(result["status"], "observed")
        self.assertEqual(len(runtime.taps), 1)
        self.assertEqual(runtime.taps[0]["target_identity"], daily.QUEST_DAILY_IDENTITY)
        self.assertEqual(set(result["frames"]), {"source", "daily_immediate_before", "daily_terminal"})
        self.assertEqual(result["recognitions"]["source"]["state"], daily.QUEST_STATE)

    def test_continuation_rejects_home_source_without_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", Path(directory) / "lock.sqlite3"
        ):
            root = Path(directory)
            runtime = FakeRuntime(root)
            recognizer = LabelSettlingRecognizer(main_source_state=daily.HOME_STATE)
            with self._continuation_session(root) as session:
                result = daily.run_quest_daily_continuation(
                    runtime, session, recognizer=recognizer
                )

        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(runtime.taps, [])

    def test_continuation_rejects_unknown_source_without_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", Path(directory) / "lock.sqlite3"
        ):
            root = Path(directory)
            runtime = FakeRuntime(root)
            recognizer = LabelSettlingRecognizer(main_source_state=daily.UNKNOWN_STATE)
            with self._continuation_session(root) as session:
                result = daily.run_quest_daily_continuation(
                    runtime, session, recognizer=recognizer
                )

        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(runtime.taps, [])

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
    def _quest_ocr(
        *,
        shift_x: int = 0,
        shift_y: int = 0,
        context_text: str = "Recom’d",
        tokens: list[tuple[str, tuple[int, int, int, int]]] | None = None,
        extra_tokens: list[tuple[str, tuple[int, int, int, int]]] | None = None,
    ):
        # Hand-authored native geometry converted through an independent OCR
        # crop model; these fixtures do not import production ROIs.
        native_tokens: list[tuple[str, tuple[int, int, int, int]]] = tokens or [
            ("Daily", (320 + shift_x, 103 + shift_y, 390 + shift_x, 131 + shift_y)),
            ("Quest", (402 + shift_x, 104 + shift_y, 482 + shift_x, 128 + shift_y)),
            ("Alliance", (618 + shift_x, 92 + shift_y, 713 + shift_x, 110 + shift_y)),
            ("Activity", (624 + shift_x, 119 + shift_y, 710 + shift_x, 141 + shift_y)),
            (context_text, (336 + shift_x, 179 + shift_y, 464 + shift_x, 205 + shift_y)),
        ]
        if extra_tokens:
            native_tokens.extend(extra_tokens)

        def scaled(item: tuple[str, tuple[int, int, int, int]]) -> tuple[str, int, int, int, int]:
            text, (x0, y0, x1, y1) = item
            return text, x0 * 2, (y0 - 35) * 2, (x1 - x0) * 2, (y1 - y0) * 2

        return DailyRowRecognizerTests._ocr_for([scaled(item) for item in native_tokens])

    @staticmethod
    def _main_absent_continuation_ocr():
        base = DailyRowRecognizerTests._quest_ocr()

        def ocr(image: np.ndarray) -> dict[str, list[object]]:
            if image.shape[0] != 390:
                return DailyRowRecognizerTests._ocr_for([])(image)
            data = base(image)
            if float(np.mean(image[:, :534])) >= float(np.mean(image[:, 536:1066])):
                return data
            extra = DailyRowRecognizerTests._ocr_for(
                [("Main", 100 * 2, (70 - 35) * 2, 80 * 2, 20 * 2)]
            )(image)
            for key in ("text", "left", "top", "width", "height", "conf"):
                data[key] = extra[key] + data[key]
            return data

        return ocr

    @staticmethod
    def _quest_frame(*, shift_x: int = 0, shift_y: int = 0, daily_selected: bool = False) -> np.ndarray:
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        y0, y1 = 60 + shift_y, 145 + shift_y
        main_color = (70, 70, 70) if daily_selected else (0, 180, 255)
        daily_color = (0, 180, 255) if daily_selected else (70, 70, 70)
        cv2.rectangle(frame, (shift_x, y0), (267 + shift_x, y1), main_color, -1)
        cv2.rectangle(frame, (268 + shift_x, y0), (533 + shift_x, y1), daily_color, -1)
        cv2.rectangle(frame, (534 + shift_x, y0), (799 + shift_x, y1), (70, 70, 70), -1)
        return frame

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

        frame = self._quest_frame()
        quest = daily.DailyRowClaimRecognizer(
            ocr=self._quest_ocr()
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

    def test_quest_recognizes_split_context_without_stylized_title(self) -> None:
        recognition = daily.DailyRowClaimRecognizer(
            ocr=self._quest_ocr()
        ).recognize_quest(self._quest_frame())

        self.assertTrue(recognition.recognized)
        self.assertIsNone(recognition.visual_evidence["quest_header"])
        self.assertTrue(recognition.visual_evidence["selection_proven"])

    def test_continuation_accepts_spatial_main_proof_without_main_title_ocr(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", Path(directory) / "lock.sqlite3"
        ):
            root = Path(directory)
            runtime = MainAbsentContinuationRuntime(root)
            recognizer = daily.DailyRowClaimRecognizer(
                ocr=self._main_absent_continuation_ocr()
            )
            session = boundary.DevelopmentSession(
                owner="test-daily-row-continuation",
                invocation_id="test-daily-row-continuation",
                session_directory=root / "session",
                max_inputs=1,
            )
            with session:
                result = daily.run_quest_daily_continuation(
                    runtime, session, recognizer=recognizer
                )

        self.assertEqual(result["status"], "observed")
        self.assertEqual(result["input_count"], 1)
        self.assertEqual(len(runtime.taps), 1)
        self.assertEqual(runtime.taps[0]["target_identity"], daily.QUEST_DAILY_IDENTITY)
        source = result["recognitions"]["source"]
        self.assertTrue(source["recognized"])
        self.assertTrue(source["visual_evidence"]["selection_proven"])
        self.assertFalse(source["visual_evidence"]["main_tab_present"])
        self.assertNotIn("main", source["ocr_text"].split())

    def test_quest_accepts_normalized_recommend_spelling(self) -> None:
        recognition = daily.DailyRowClaimRecognizer(
            ocr=self._quest_ocr(context_text="Recommend")
        ).recognize_quest(self._quest_frame())

        self.assertTrue(recognition.recognized)

    def test_quest_spatial_semantics_translate_with_current_layout(self) -> None:
        recognition = daily.DailyRowClaimRecognizer(
            ocr=self._quest_ocr(shift_x=100, shift_y=15)
        ).recognize_quest(self._quest_frame(shift_x=100, shift_y=15))

        self.assertTrue(recognition.recognized)
        self.assertGreater(recognition.target_roi[0], 300)

    def test_quest_rejects_missing_or_disassociated_context(self) -> None:
        cases = [
            (
                "missing_activity",
                [
                    ("Daily", (320, 103, 390, 131)),
                    ("Quest", (402, 104, 482, 128)),
                    ("Alliance", (618, 92, 713, 110)),
                    ("Recom’d", (336, 179, 464, 205)),
                ],
            ),
            (
                "quest_far_from_daily",
                [
                    ("Daily", (320, 103, 390, 131)),
                    ("Quest", (560, 104, 640, 128)),
                    ("Alliance", (618, 92, 713, 110)),
                    ("Activity", (624, 119, 710, 141)),
                    ("Recom’d", (336, 179, 464, 205)),
                ],
            ),
            (
                "context_elsewhere",
                [
                    ("Daily", (320, 103, 390, 131)),
                    ("Quest", (402, 104, 482, 128)),
                    ("Alliance", (618, 92, 713, 110)),
                    ("Activity", (624, 119, 710, 141)),
                    ("Recommend", (620, 179, 748, 205)),
                ],
            ),
            (
                "fragmented_context",
                [
                    ("Daily", (320, 103, 390, 131)),
                    ("Quest", (402, 104, 482, 128)),
                    ("Alliance", (618, 92, 713, 110)),
                    ("Activity", (624, 119, 710, 141)),
                    ("Recom", (336, 179, 425, 205)),
                    ("d", (430, 179, 464, 205)),
                ],
            ),
        ]
        for name, tokens in cases:
            with self.subTest(case=name):
                recognition = daily.DailyRowClaimRecognizer(
                    ocr=self._quest_ocr(tokens=tokens)
                ).recognize_quest(self._quest_frame())
                self.assertFalse(recognition.recognized)

    def test_quest_rejects_selected_daily_visual_state(self) -> None:
        recognition = daily.DailyRowClaimRecognizer(
            ocr=self._quest_ocr()
        ).recognize_quest(self._quest_frame(daily_selected=True))

        self.assertFalse(recognition.recognized)
        self.assertEqual(recognition.reason, "main-quest-selection-not-proven")
        self.assertLess(
            recognition.visual_evidence["main_selected_margin"],
            0.015,
        )

    def test_quest_rejects_duplicate_daily_target_and_unrelated_text(self) -> None:
        duplicate = daily.DailyRowClaimRecognizer(
            ocr=self._quest_ocr(
                extra_tokens=[("Daily", (120, 103, 190, 131))]
            )
        ).recognize_quest(self._quest_frame())
        self.assertFalse(duplicate.recognized)

        unrelated = daily.DailyRowClaimRecognizer(
            ocr=self._quest_ocr(
                extra_tokens=[("Recommend", (700, 179, 790, 205))]
            )
        ).recognize_quest(self._quest_frame())
        self.assertFalse(unrelated.recognized)

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
    def test_continuation_receipt_freezes_variant_budget_and_actions_before_consume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "receipts.sqlite3"
            command = [
                "development-session",
                "daily-row-reconnaissance",
                "--max-inputs",
                "1",
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
                "quest-daily-continuation",
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
                variant="quest-daily-continuation",
                permitted_action_identities=["quest-daily-tab"],
                permitted_action_classes=["navigation"],
                consequence_class="navigation_only",
                max_total_inputs=1,
                max_resource_affecting_inputs=0,
                max_combat_confirmations=0,
                permitted_terminal_states=["observed", "evidence_required"],
                result_identity=pnsctl.DAILY_ROW_RECON_RESULT_IDENTITY,
            )

            with self.assertRaisesRegex(pnsctl.OperatorError, "requires --max-inputs 1"):
                pnsctl.development_session_daily_row_reconnaissance(
                    max_inputs=2,
                    delegated_receipt=state,
                    agent_identity="luna-agent",
                    task_id="daily-row-claim",
                    flow_id="DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                    scenario="selected-daily-row-evidence",
                    variant="quest-daily-continuation",
                    command_argv=command,
                )
            self.assertEqual(controller.inspect()["status"], "issued")

            with patch.object(
                control,
                "DelegatedRuntimeReceiptController",
                return_value=controller,
            ), self.assertRaises(control.FlowDeliveryError):
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
            self.assertEqual(controller.inspect()["status"], "issued")
            self.assertEqual(receipt["max_total_inputs"], 1)

            bad_state = root / "bad-receipts.sqlite3"
            bad_controller = control.DelegatedRuntimeReceiptController(bad_state)
            bad_controller._candidate = lambda: ("head", "fingerprint")  # type: ignore[method-assign]
            bad_controller.issue(
                task_id="daily-row-claim",
                flow_id="DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                receipt_class="reconnaissance",
                agent_identity="luna-agent",
                command_argv=command,
                scenario="selected-daily-row-evidence",
                variant="quest-daily-continuation",
                permitted_action_identities=["home-quest-entry"],
                permitted_action_classes=["navigation"],
                consequence_class="navigation_only",
                max_total_inputs=1,
                max_resource_affecting_inputs=0,
                max_combat_confirmations=0,
                permitted_terminal_states=["observed", "evidence_required"],
                result_identity=pnsctl.DAILY_ROW_RECON_RESULT_IDENTITY,
            )
            with patch.object(
                control,
                "DelegatedRuntimeReceiptController",
                return_value=bad_controller,
            ), self.assertRaises(pnsctl.OperatorError):
                pnsctl.development_session_daily_row_reconnaissance(
                    max_inputs=1,
                    delegated_receipt=bad_state,
                    agent_identity="luna-agent",
                    task_id="daily-row-claim",
                    flow_id="DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                    scenario="selected-daily-row-evidence",
                    variant="quest-daily-continuation",
                    command_argv=command,
                )
            self.assertEqual(bad_controller.inspect()["status"], "issued")

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

    def test_continuation_command_accepts_three_frame_terminal_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "receipts.sqlite3"
            command = [
                "development-session",
                "daily-row-reconnaissance",
                "--max-inputs",
                "1",
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
                "quest-daily-continuation",
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
                variant="quest-daily-continuation",
                permitted_action_identities=["quest-daily-tab"],
                permitted_action_classes=["navigation"],
                consequence_class="navigation_only",
                max_total_inputs=1,
                max_resource_affecting_inputs=0,
                max_combat_confirmations=0,
                permitted_terminal_states=["observed", "evidence_required"],
                result_identity=pnsctl.DAILY_ROW_RECON_RESULT_IDENTITY,
            )

            def connect(**kwargs):
                return FakeRuntime(Path(kwargs["output_directory"]))

            with patch.object(pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"), patch.object(
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
                    max_inputs=1,
                    delegated_receipt=state,
                    agent_identity="luna-agent",
                    task_id="daily-row-claim",
                    flow_id="DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                    scenario="selected-daily-row-evidence",
                    variant="quest-daily-continuation",
                    command_argv=command,
                )

            result = json.loads(output)
            self.assertEqual(result["status"], "observed")
            self.assertEqual(result["input_count"], 1)
            self.assertTrue(result["ownership_released"])
            self.assertEqual(set(result["frames"]), {"source", "daily_immediate_before", "daily_terminal"})
            self.assertEqual(controller.inspect()["status"], "consumed")

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


class DailyClaimRecognitionTests(unittest.TestCase):
    @staticmethod
    def _ocr_for_native_tokens(
        tokens: list[tuple[str, tuple[int, int, int, int]]],
    ):
        def ocr(_image: np.ndarray) -> dict[str, list[object]]:
            return {
                "text": [text for text, _roi in tokens],
                "left": [roi[0] * 2 for _text, roi in tokens],
                "top": [roi[1] * 2 for _text, roi in tokens],
                "width": [(roi[2] - roi[0]) * 2 for _text, roi in tokens],
                "height": [(roi[3] - roi[1]) * 2 for _text, roi in tokens],
                "conf": ["95"] * len(tokens),
            }

        return ocr

    @classmethod
    def _claim_fixture(
        cls,
        *,
        row_y: int = 450,
        selected_tab: str = "daily",
        include_daily_title: bool = True,
        objective: str = "Consume",
        quantity: str = "20",
        progress: str = "36 20",
        reward: str = "Reward Pts +5",
        claim_tokens: tuple[tuple[str, tuple[int, int, int, int]], ...] | None = None,
        extra_tokens: tuple[tuple[str, tuple[int, int, int, int]], ...] = (),
        include_reset: bool = True,
        reset_timer: str = "04:00:00",
        cost_icon: bool = False,
    ) -> tuple[np.ndarray, Callable[[np.ndarray], dict[str, list[object]]], list[tuple[str, tuple[int, int, int, int]]]]:
        tokens: list[tuple[str, tuple[int, int, int, int]]] = [
            ("Main", (80, 80, 170, 110)),
            ("Alliance", (500, 80, 610, 110)),
            ("Activity", (505, 115, 610, 140)),
            ("Daily Quest Pts 0", (80, 220, 240, 250)),
        ]
        if include_daily_title:
            tokens.insert(1, ("Daily", (280, 80, 370, 110)))
        if include_reset:
            tokens.append((f"Reset {reset_timer}", (500, 220, 730, 250)))
        objective_y = row_y
        tokens.extend(
            [
                (objective, (100, objective_y, 190, objective_y + 25)),
                (quantity, (200, objective_y, 220, objective_y + 25)),
                ("Stamina" if objective == "Consume" else "Food", (230, objective_y, 320, objective_y + 25)),
                (progress, (330, objective_y, 410, objective_y + 25)),
                (reward, (350, objective_y + 40, 510, objective_y + 65)),
            ]
        )
        if claim_tokens is None:
            claim_tokens = (("Claim", (650, objective_y + 30, 710, objective_y + 60)),)
        tokens.extend(claim_tokens)
        tokens.extend(extra_tokens)

        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        panel_top = max(350, objective_y - 20)
        panel_bottom = min(1270, objective_y + 95)
        cv2.rectangle(
            frame,
            (70, panel_top),
            (780, panel_bottom),
            (45, 45, 45),
            -1,
        )
        cv2.rectangle(
            frame,
            (70, panel_top),
            (780, panel_bottom),
            (120, 120, 120),
            2,
        )
        if selected_tab == "daily":
            cv2.rectangle(frame, (250, 55), (430, 145), (0, 210, 255), -1)
            cv2.rectangle(frame, (50, 55), (220, 145), (70, 70, 70), -1)
        elif selected_tab == "main":
            cv2.rectangle(frame, (50, 55), (220, 145), (0, 210, 255), -1)
            cv2.rectangle(frame, (250, 55), (430, 145), (70, 70, 70), -1)
        else:
            cv2.rectangle(frame, (50, 55), (220, 145), (70, 70, 70), -1)
            cv2.rectangle(frame, (250, 55), (430, 145), (70, 70, 70), -1)
        if claim_tokens:
            cv2.rectangle(
                frame,
                (640, objective_y + 25),
                (720, objective_y + 65),
                (0, 180, 255),
                -1,
            )
        if cost_icon:
            cv2.circle(frame, (580, objective_y + 45), 12, (0, 220, 180), -1)
        return frame, cls._ocr_for_native_tokens(tokens), tokens

    def test_selected_daily_binds_independent_row_progress_reward_points_and_roi(self):
        frame, ocr, _tokens = self._claim_fixture()
        recognition = daily.DailyRowClaimRecognizer(ocr=ocr).recognize_daily_claim(
            frame,
            observed_utc="2026-08-16T00:00:00Z",
        )

        self.assertTrue(recognition.recognized)
        self.assertEqual(recognition.state, "DAILY_SELECTED")
        self.assertEqual(recognition.target_identity, "daily-row-claim:consume_stamina")
        self.assertEqual(recognition.target_roi, (605, 455, 755, 535))
        evidence = recognition.visual_evidence
        self.assertEqual(evidence["objective_key"], "consume_stamina")
        self.assertEqual(evidence["objective_name"], "consume 20 stamina")
        self.assertEqual(evidence["current_progress"], 36)
        self.assertEqual(evidence["required_progress"], 20)
        self.assertEqual(evidence["reward_points"], 5)
        self.assertEqual(evidence["points"], 0)
        self.assertEqual(evidence["row_bounds"], (70, 432, 780, 542))
        self.assertEqual(evidence["claim_roi"], (605, 455, 755, 535))
        self.assertEqual(
            evidence["game_day_id"],
            "reset-deadline:2026-08-16T04:00:00Z",
        )

        observation = daily.daily_claim_observation_from_recognition(
            recognition,
            source_frame_sha256="b" * 64,
            evidence_ref="runtime/frames/0001-daily.png",
            game_day_id=evidence["game_day_id"],
        )
        self.assertIsNotNone(observation)
        self.assertTrue(observation.catalog_reconciled)
        self.assertTrue(
            __import__("tasks.available_daily_claim", fromlist=["available_daily_claim_authorizeable"])
            .available_daily_claim_authorizeable(observation)
        )

    def test_selected_daily_title_may_be_missed_when_current_pixels_and_context_bind_center_tab(self):
        frame, ocr, _tokens = self._claim_fixture(include_daily_title=False)
        recognition = daily.DailyRowClaimRecognizer(ocr=ocr).recognize_daily_claim(
            frame,
            observed_utc="2026-08-16T00:00:00Z",
        )

        self.assertTrue(recognition.recognized)
        self.assertTrue(recognition.visual_evidence["selected_daily"])
        self.assertFalse(recognition.visual_evidence["selected_daily_semantics"]["title_ocr_present"])

    def test_daily_claim_rejects_main_missing_context_and_overlay_states(self):
        cases = (
            ("main_selected", self._claim_fixture(selected_tab="main")),
            ("missing_daily_semantics", self._claim_fixture(selected_tab="unknown", include_daily_title=False)),
            (
                "overlay",
                self._claim_fixture(extra_tokens=(("Confirm", (300, 300, 400, 330)),)),
            ),
            ("reset_missing", self._claim_fixture(include_reset=False)),
        )
        for name, (frame, ocr, _tokens) in cases:
            with self.subTest(case=name):
                recognition = daily.DailyRowClaimRecognizer(ocr=ocr).recognize_daily_claim(
                    frame,
                    game_day_id="game-day-a",
                )
                self.assertFalse(recognition.recognized)

    def test_daily_claim_rejects_go_milestone_clipped_and_row_geometry_negatives(self):
        cases = (
            ("go", self._claim_fixture(claim_tokens=())),
            (
                "milestone",
                self._claim_fixture(
                    extra_tokens=(("Milestone Chest", (100, 390, 280, 415)),)
                ),
            ),
            ("clipped", self._claim_fixture(row_y=1190)),
            (
                "claim_adjacent",
                self._claim_fixture(
                    claim_tokens=(
                        ("Claim", (550, 460, 610, 490)),
                        ("Claim", (650, 460, 710, 490)),
                    )
                ),
            ),
        )
        for name, (frame, ocr, _tokens) in cases:
            with self.subTest(case=name):
                recognition = daily.DailyRowClaimRecognizer(ocr=ocr).recognize_daily_claim(
                    frame,
                    game_day_id="game-day-a",
                )
                self.assertFalse(
                    bool((recognition.visual_evidence or {}).get("claim_ready"))
                )

    def test_daily_claim_rejects_exactly_one_adjacent_row_claim(self):
        frame, ocr, _tokens = self._claim_fixture(
            claim_tokens=(("Claim", (650, 555, 710, 585)),)
        )
        recognition = daily.DailyRowClaimRecognizer(ocr=ocr).recognize_daily_claim(
            frame,
            observed_utc="2026-08-16T00:00:00Z",
        )
        self.assertFalse(recognition.recognized)
        self.assertIn("outside", recognition.reason or "")

    def test_daily_claim_rejects_numeric_only_and_icon_only_attached_costs(self):
        numeric_frame, numeric_ocr, _tokens = self._claim_fixture(
            extra_tokens=(("2", (520, 500, 560, 525)),)
        )
        icon_frame, icon_ocr, _tokens = self._claim_fixture(cost_icon=True)
        for name, frame, ocr in (
            ("numeric-only", numeric_frame, numeric_ocr),
            ("icon-only", icon_frame, icon_ocr),
        ):
            with self.subTest(case=name):
                recognition = daily.DailyRowClaimRecognizer(
                    ocr=ocr
                ).recognize_daily_claim(
                    frame,
                    observed_utc="2026-08-16T00:00:00Z",
                )
                self.assertFalse(recognition.recognized)
                self.assertIn("attached", recognition.reason or "")

    def test_reset_deadline_is_bound_from_injected_wall_utc_and_rollover_rejects(self):
        before_frame, before_ocr, _tokens = self._claim_fixture(
            reset_timer="00:00:02"
        )
        before = daily.DailyRowClaimRecognizer(ocr=before_ocr).recognize_daily_claim(
            before_frame,
            observed_utc="2026-08-16T23:59:58Z",
        )
        self.assertTrue(before.recognized)
        before_evidence = before.visual_evidence
        self.assertEqual(
            before_evidence["reset_deadline_identity"],
            "reset-deadline:2026-08-17T00:00:00Z",
        )
        self.assertEqual(
            before_evidence["game_day_id"],
            before_evidence["reset_deadline_identity"],
        )

        after_frame, after_ocr, _tokens = self._claim_fixture(
            reset_timer="23:59:58"
        )
        after = daily.DailyRowClaimRecognizer(ocr=after_ocr).recognize_daily_claim(
            after_frame,
            observed_utc="2026-08-17T00:00:00Z",
            game_day_id=before_evidence["game_day_id"],
        )
        after_evidence = dict(after.visual_evidence)
        after_evidence.update(
            {
                "claim_ready": False,
                "same_objective_present": False,
                "objective_key": None,
                "points": 5,
            }
        )
        after = replace(
            after,
            target_identity=None,
            target_roi=None,
            visual_evidence=after_evidence,
        )
        self.assertFalse(
            daily.daily_claim_postcondition_verified(
                before,
                after,
                game_day_id=before_evidence["game_day_id"],
            )
        )

    def test_reset_deadline_accepts_monotonic_injected_countdown(self):
        before_frame, before_ocr, _tokens = self._claim_fixture()
        before = daily.DailyRowClaimRecognizer(ocr=before_ocr).recognize_daily_claim(
            before_frame,
            observed_utc="2026-08-16T00:00:00Z",
        )
        after_frame, after_ocr, _tokens = self._claim_fixture(
            reset_timer="03:59:58"
        )
        after = daily.DailyRowClaimRecognizer(ocr=after_ocr).recognize_daily_claim(
            after_frame,
            observed_utc="2026-08-16T00:00:02Z",
            game_day_id=before.visual_evidence["game_day_id"],
        )
        after_evidence = dict(after.visual_evidence)
        after_evidence.update({"claim_ready": False, "points": 5})
        after = replace(
            after,
            target_identity=None,
            target_roi=None,
            visual_evidence=after_evidence,
        )
        self.assertTrue(
            daily.daily_claim_postcondition_verified(
                before,
                after,
                game_day_id=before.visual_evidence["game_day_id"],
            )
        )

    def test_daily_claim_rejects_duplicate_objective_and_wrong_objective(self):
        duplicate = self._claim_fixture(
            extra_tokens=(
                ("Consume", (100, 620, 190, 645)),
                ("20", (200, 620, 220, 645)),
                ("Stamina", (230, 620, 320, 645)),
                ("36 20", (330, 620, 410, 645)),
            )
        )
        wrong = self._claim_fixture(objective="Gather", quantity="10", progress="3 10")
        for name, fixture in (("duplicate", duplicate), ("wrong", wrong)):
            with self.subTest(case=name):
                frame, ocr, _tokens = fixture
                recognition = daily.DailyRowClaimRecognizer(ocr=ocr).recognize_daily_claim(
                    frame,
                    game_day_id="game-day-a",
                )
                self.assertFalse(
                    bool((recognition.visual_evidence or {}).get("claim_ready"))
                )
                self.assertIsNone(recognition.target_identity)

    def test_daily_claim_rejects_wrong_reward_progress_and_unknown_cost(self):
        cases = (
            ("wrong_reward", self._claim_fixture(reward="Reward Pts +10")),
            ("incomplete_progress", self._claim_fixture(progress="15 20")),
            (
                "unknown_cost",
                self._claim_fixture(
                    extra_tokens=(("2 Gems", (520, 500, 610, 525)),)
                ),
            ),
        )
        for name, (frame, ocr, _tokens) in cases:
            with self.subTest(case=name):
                recognition = daily.DailyRowClaimRecognizer(ocr=ocr).recognize_daily_claim(
                    frame,
                    game_day_id="game-day-a",
                )
                self.assertFalse(
                    bool((recognition.visual_evidence or {}).get("claim_ready"))
                )


class ClaimCanaryRuntime:
    execute = True
    frame_max_age_seconds = 30.0

    def __init__(self, root: Path):
        self.session = root / "runtime"
        self.session.mkdir(parents=True)
        self.events = self.session / "events.jsonl"
        self.labels: list[str] = []
        self.taps: list[dict[str, object]] = []
        self.reservations: list[dict[str, object]] = []
        self.input_count = 0
        self._ordinal = 0

    def capture(self, label: str) -> CapturedNativeFrame:
        self._ordinal += 1
        self.labels.append(label)
        safe_label = label.replace(":", "_").replace("/", "_")
        return _frame(self.session, f"{self._ordinal:04d}-{safe_label}")

    def measure_device_state(self) -> str:
        return "device"

    def measure_foreground_package(self) -> str:
        return daily.EXPECTED_PACKAGE

    def tap(
        self,
        source: CapturedNativeFrame,
        *,
        target_identity: str,
        target_roi: tuple[int, int, int, int],
        action_key: str,
        action_class: str = "navigation",
        consequential: bool = False,
        continuation_of: str | None = None,
    ) -> None:
        self.reservations.append(
            {
                "action_identity": target_identity,
                "action_class": action_class,
                "consequence_class": "ordinary_development",
                "source_sha256": source.sha256,
            }
        )
        delegated = boundary.current_delegated_runtime_context()
        if delegated is not None:
            delegated.reserve_input(
                action_identity=target_identity,
                action_class=action_class,
                consequence_class="ordinary_development",
                source_evidence_hash=source.sha256,
                action_key=action_key,
            )
            delegated.mark_transported(action_key)
        self.taps.append(
            {
                "target_identity": target_identity,
                "target_roi": target_roi,
                "action_key": action_key,
                "action_class": action_class,
                "consequential": consequential,
                "continuation_of": continuation_of,
            }
        )
        self.input_count += 1
        with self.events.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "type": "dispatch",
                        "target_identity": target_identity,
                        "target_roi": target_roi,
                        "action_class": action_class,
                    }
                )
                + "\n"
            )


class VipPopupRuntime(FakeRuntime):
    def __init__(self, root: Path, *, modal_post: bool = False) -> None:
        super().__init__(root)
        self.action_classes: list[str] = []
        self.modal_post = modal_post

    def capture(self, label: str) -> CapturedNativeFrame:
        self.labels.append(label)
        image = np.zeros((1280, 800, 3), dtype=np.uint8)
        cv2.rectangle(image, (0, 60), (267, 145), (70, 70, 70), -1)
        cv2.rectangle(image, (268, 60), (533, 145), (0, 180, 255), -1)
        cv2.rectangle(image, (534, 60), (799, 145), (70, 70, 70), -1)
        if self.modal_post and (
            label == "reset-popup-close-immediate-post"
            or label.startswith("reset-popup-close-poll-")
        ):
            image = cv2.addWeighted(image, 0.25, np.zeros_like(image), 0.75, 0)
            cv2.rectangle(image, (96, 260), (704, 948), (255, 255, 255), 8)
        captured = _frame(self.session, label, image=image)
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
        action_class: str = "navigation",
        consequential: bool = False,
        continuation_of: str | None = None,
    ) -> None:
        self.action_classes.append(action_class)
        super().tap(
            source,
            target_identity=target_identity,
            target_roi=target_roi,
            action_key=action_key,
            consequential=consequential,
            continuation_of=continuation_of,
        )


class IndependentVipPopupFake:
    """Independent popup contract fake; production OCR is not reused."""

    def __init__(
        self,
        states: list[str],
        *,
        mismatch_hash: bool = False,
        invalid_roi: bool = False,
    ) -> None:
        self.states = states
        self.mismatch_hash = mismatch_hash
        self.invalid_roi = invalid_roi
        self.calls = 0

    def __call__(
        self,
        _frame: np.ndarray,
        *,
        source_frame_sha256: str,
    ) -> dict[str, object]:
        index = min(self.calls, len(self.states) - 1)
        state = self.states[index]
        self.calls += 1
        if state != "allowed":
            return {
                "status": state,
                "popup_identity": None,
                "target_identity": None,
                "target_roi": None,
                "source_frame_sha256": source_frame_sha256,
                "semantic_evidence": (),
                "reason": f"scripted-{state}",
            }
        return {
            "status": "allowed",
            "popup_identity": "VIP_POINTS_GET_PTS",
            "target_identity": "reset-popup-close",
            "target_roi": (100, 700, 300, 780) if not self.invalid_roi else (900, 700, 950, 780),
            "source_frame_sha256": (
                "0" * 64 if self.mismatch_hash else source_frame_sha256
            ),
            "semantic_evidence": (
                "Get Pts",
                "Log in every day to get VIP pts",
                "Close",
                "spatially_associated_close_control",
            ),
            "reason": "",
        }


class SelectedDailySuccessorFake:
    def __init__(self, *, recognized: bool = True, blurred: bool = False) -> None:
        self.recognized = recognized
        self.blurred = blurred
        self.calls = 0

    def recognize_daily_selected(
        self,
        _frame: np.ndarray,
    ) -> daily.FrameRecognition:
        self.calls += 1
        return daily.FrameRecognition(
            daily.DAILY_SELECTED_STATE if self.recognized else daily.UNKNOWN_STATE,
            self.recognized,
            "daily-quest-selected" if self.recognized else None,
            (280, 80, 370, 110) if self.recognized else None,
            "selected Daily",
            {
                "selected_daily": self.recognized,
                "unblurred": not self.blurred,
                "blurred": self.blurred,
                "full_frame_overlay": {"recognized": self.blurred},
            },
            None if self.recognized else "selected Daily is unknown",
        )


class ScriptedClaimRecognizer:
    def __init__(self, outcome: str):
        self.outcome = outcome
        self.calls = 0

    def recognize_daily_claim(
        self,
        _frame: np.ndarray,
        *,
        game_day_id: str | None = None,
    ) -> daily.FrameRecognition:
        self.calls += 1
        before = self.calls <= 2
        ready = before or self.outcome == "unchanged"
        points = 0
        objective_key: str | None = "consume_stamina"
        same_objective_present = True
        recognized = True
        reset_timer: str | None = "04:00:00"
        if not before and self.outcome == "points":
            points = 5
            ready = False
        elif not before and self.outcome == "row_disappeared":
            ready = False
            objective_key = None
            same_objective_present = False
        elif not before and self.outcome == "row_missing_points":
            ready = False
            objective_key = None
            same_objective_present = False
            points = None
        elif not before and self.outcome == "wrong_delta":
            points = 4
            ready = False
        elif not before and self.outcome == "plus_ten":
            points = 10
            ready = False
        elif not before and self.outcome == "control_changed":
            ready = False
        elif not before and self.outcome == "wrong_objective":
            points = 5
            objective_key = "other_objective"
            ready = False
        elif not before and self.outcome == "overlay":
            recognized = False
        elif not before and self.outcome == "reset":
            points = 5
            ready = False
            reset_timer = None

        visual = {
            "selected_daily": True,
            "game_day_id": game_day_id,
            "points": points,
            "reset_timer": reset_timer,
            "reset_timer_seconds": 14400 if reset_timer is not None else None,
            "reset_observed_utc": (
                "2026-08-16T00:00:00Z" if reset_timer is not None else None
            ),
            "reset_deadline_utc": (
                "2026-08-16T04:00:00Z" if reset_timer is not None else None
            ),
            "reset_deadline_identity": game_day_id if reset_timer is not None else None,
            "reset_deadline_tolerance_seconds": (
                2 if reset_timer is not None else None
            ),
            "objective_key": objective_key,
            "objective_name": "consume 20 stamina",
            "current_progress": 36,
            "required_progress": 20,
            "reward_points": 5,
            "same_objective_present": same_objective_present,
            "claim_ready": ready,
            "row_bounds": (82, 432, 773, 545),
            "claim_roi": (605, 455, 755, 535),
            "row_fully_visible": True,
            "claim_fully_visible": ready,
            "cost_type": "none",
            "cost_amount": 0,
            "quantity": 1,
            "ordinary_reward_claim": ready,
            "free_control_proven": ready,
            "quantity_one_proven": ready,
            "cost_region_scan": {
                "attached_cost": False,
                "numeric_only_cost": False,
                "icon_only_cost": False,
                "currency_icon": False,
                "currency_amount": False,
            },
            "row_panel_geometry": {
                "proven": True,
                "source": "independent-test-panel",
                "bounds": (82, 432, 773, 545),
            },
            "milestone_reward": False,
            "full_frame_overlay": {
                "recognized": not recognized,
                "markers": ("confirm",) if not recognized else (),
            },
        }
        return daily.FrameRecognition(
            daily.DAILY_SELECTED_STATE if recognized else daily.UNKNOWN_STATE,
            recognized,
            "daily-row-claim:consume_stamina" if ready else None,
            (605, 455, 755, 535) if ready else None,
            "scripted daily claim",
            visual,
            None if recognized else "full-frame overlay/modal detected",
        )


class DailyClaimCanaryTests(unittest.TestCase):
    def _run_canary(self, root: Path, outcome: str):
        runtime = ClaimCanaryRuntime(root)
        recognizer = ScriptedClaimRecognizer(outcome)
        with patch.object(daily, "DAILY_CLAIM_SUCCESS_POLL_INTERVAL_SECONDS", 0.0), patch.object(
            daily, "DAILY_CLAIM_SUCCESS_POLL_MAX_ATTEMPTS", 2
        ), patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
            with boundary.DevelopmentSession(
                owner="test-daily-claim-canary",
                invocation_id=f"test-{outcome}",
                session_directory=root / "session",
                max_inputs=1,
            ) as session:
                result = daily.run_daily_row_claim_canary(
                    runtime,
                    session,
                    game_day_id="game-day-a",
                    recognizer=recognizer,
                )
        return result, runtime, recognizer, session

    def test_canary_dispatches_one_reward_claim_and_proves_points_success(self):
        with tempfile.TemporaryDirectory() as directory:
            result, runtime, _recognizer, session = self._run_canary(
                Path(directory), "points"
            )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["input_count"], 1)
            self.assertEqual(len(runtime.taps), 1)
            self.assertEqual(runtime.taps[0]["target_identity"], "daily-row-claim:consume_stamina")
            self.assertEqual(runtime.taps[0]["target_roi"], (605, 455, 755, 535))
            self.assertEqual(runtime.reservations[0]["action_class"], "reward_claim")
            self.assertEqual(result["claim"]["points_before"], 0)
            self.assertEqual(result["claim"]["points_after"], 5)
            self.assertTrue(session._ownership.lock.held is False)
            self.assertIn("immediate_before", result["frames"])
            self.assertIn("immediate_post", result["frames"])
            annotated = Path(result["claim"]["annotated_immediate_before"])
            self.assertTrue(annotated.is_file())
            self.assertGreater(annotated.stat().st_size, 0)

    def test_canary_rejects_ocr_missing_row_with_unchanged_points(self):
        with tempfile.TemporaryDirectory() as directory:
            result, runtime, _recognizer, _session = self._run_canary(
                Path(directory), "row_disappeared"
            )

            self.assertEqual(result["status"], "evidence_required")
            self.assertEqual(len(runtime.taps), 1)
            post = result["recognitions"]["immediate_post"]["visual_evidence"]
            self.assertIsNone(post["objective_key"])
            self.assertEqual(post["points"], 0)

    def test_canary_failure_is_evidence_required_without_retry(self):
        for outcome in (
            "unchanged",
            "row_missing_points",
            "wrong_delta",
            "plus_ten",
            "control_changed",
            "wrong_objective",
            "overlay",
            "reset",
        ):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                result, runtime, _recognizer, _session = self._run_canary(
                    Path(directory), outcome
                )

                self.assertEqual(result["status"], "evidence_required")
                self.assertEqual(len(runtime.taps), 1)
                self.assertEqual(result["input_count"], 1)
                self.assertGreaterEqual(len(result["polls"]), 1)
                self.assertTrue(result["frames"]["immediate_post"]["sha256"])
                self.assertTrue(
                    all(
                        poll["frame"]["sha256"]
                        for poll in result["polls"]
                    )
                )


class VipPopupDismissalTests(unittest.TestCase):
    def _run(
        self,
        root: Path,
        popup: IndependentVipPopupFake,
        *,
        daily_successor: SelectedDailySuccessorFake | None = None,
        max_attempts: int = 2,
        modal_post: bool = False,
    ):
        runtime = VipPopupRuntime(root, modal_post=modal_post)
        daily_successor = daily_successor or SelectedDailySuccessorFake()
        with patch.object(
            daily,
            "VIP_POPUP_SUCCESS_POLL_INTERVAL_SECONDS",
            0.0,
        ), patch.object(
            daily,
            "VIP_POPUP_SUCCESS_POLL_MAX_ATTEMPTS",
            max_attempts,
        ), patch.object(
            boundary,
            "RUNTIME_INPUT_LOCK_PATH",
            root / "lock.sqlite3",
        ):
            with boundary.DevelopmentSession(
                owner="test-vip-popup-dismissal",
                invocation_id="test-vip-popup",
                session_directory=root / "session",
                max_inputs=1,
            ) as session:
                result = daily.run_daily_row_claim_vip_popup_dismissal(
                    runtime,
                    session,
                    popup_recognizer=popup,
                    daily_recognizer=daily_successor,
                )
        return result, runtime, daily_successor

    def test_exact_vip_popup_dispatches_once_and_observes_selected_daily(self):
        with tempfile.TemporaryDirectory() as directory:
            result, runtime, successor = self._run(
                Path(directory),
                IndependentVipPopupFake(["allowed", "allowed", "absent"]),
            )

        self.assertEqual(result["status"], "observed")
        self.assertEqual(result["input_count"], 1)
        self.assertEqual(len(runtime.taps), 1)
        self.assertEqual(runtime.action_classes, ["navigation"])
        self.assertEqual(runtime.taps[0]["target_identity"], "reset-popup-close")
        self.assertEqual(
            set(result["frames"]),
            {"source", "immediate_before", "immediate_post"},
        )
        self.assertEqual(
            result["popup_recognitions"]["source"]["popup_identity"],
            "VIP_POINTS_GET_PTS",
        )
        for name in ("source", "immediate_before"):
            self.assertEqual(
                result["popup_recognitions"][name]["source_frame_sha256"],
                result["frames"][name]["sha256"],
            )
        self.assertTrue(result["successor"]["popup_absent"])
        self.assertTrue(result["successor"]["unblurred"])
        self.assertEqual(successor.calls, 1)

    def test_non_vip_central_modal_blocks_selected_daily_successor(self):
        with tempfile.TemporaryDirectory() as directory:
            result, runtime, _successor = self._run(
                Path(directory),
                IndependentVipPopupFake(["allowed", "allowed", "absent"]),
                modal_post=True,
            )

        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(result["input_count"], 1)
        self.assertEqual(len(runtime.taps), 1)
        self.assertIsNotNone(result["polls"][0]["recognition"])
        self.assertTrue(
            result["polls"][0]["recognition"]["visual_evidence"][
                "generic_modal_overlay"
            ]["recognized"]
        )
        self.assertEqual(
            result["polls"][0]["recognition"]["visual_evidence"][
                "generic_modal_overlay"
            ]["state"],
            "modal",
        )

    def test_clean_selected_daily_has_no_visual_panel_false_positive(self):
        with tempfile.TemporaryDirectory() as directory:
            result, runtime, _successor = self._run(
                Path(directory),
                IndependentVipPopupFake(["allowed", "allowed", "absent"]),
            )

        self.assertEqual(result["status"], "observed")
        self.assertEqual(len(runtime.taps), 1)
        generic_overlay = result["successor"]["recognition"]["visual_evidence"][
            "generic_modal_overlay"
        ]
        self.assertFalse(generic_overlay["recognized"])
        self.assertEqual(generic_overlay["state"], "none_observed")

    def test_wrong_or_unknown_popup_does_not_dispatch(self):
        for state in ("unknown", "wrong-popup"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                result, runtime, _successor = self._run(
                    Path(directory),
                    IndependentVipPopupFake([state]),
                )
                self.assertEqual(result["status"], "evidence_required")
                self.assertEqual(result["input_count"], 0)
                self.assertEqual(runtime.taps, [])

    def test_mismatched_close_geometry_or_hash_does_not_dispatch(self):
        for kwargs in (
            {"invalid_roi": True},
            {"mismatch_hash": True},
        ):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as directory:
                result, runtime, _successor = self._run(
                    Path(directory),
                    IndependentVipPopupFake(["allowed"], **kwargs),
                )
                self.assertEqual(result["status"], "evidence_required")
                self.assertEqual(runtime.taps, [])

    def test_popup_still_present_or_unknown_successor_never_retries_input(self):
        cases = (
            (["allowed", "allowed", "allowed"], SelectedDailySuccessorFake()),
            (["allowed", "allowed", "unknown"], SelectedDailySuccessorFake()),
            (["allowed", "allowed", "absent"], SelectedDailySuccessorFake(recognized=False)),
        )
        for popup_states, successor in cases:
            with self.subTest(popup_states=popup_states), tempfile.TemporaryDirectory() as directory:
                result, runtime, _successor = self._run(
                    Path(directory),
                    IndependentVipPopupFake(popup_states),
                    daily_successor=successor,
                    max_attempts=2,
                )
                self.assertEqual(result["status"], "evidence_required")
                self.assertEqual(result["input_count"], 1)
                self.assertEqual(len(runtime.taps), 1)
                self.assertGreaterEqual(len(result["polls"]), 1)


class PnsctlDailyClaimTests(unittest.TestCase):
    def _command(self, root: Path, mode: str, *, max_inputs: int | None = None) -> list[str]:
        limit = 0 if mode == "prepare" else 1
        if max_inputs is not None:
            limit = max_inputs
        variant = (
            "consume-stamina-dismiss-vip"
            if mode == "dismiss-vip-popup"
            else f"consume-stamina-{mode}"
        )
        return [
            "development-session",
            "daily-row-claim",
            "--mode",
            mode,
            "--max-inputs",
            str(limit),
            "--delegated-receipt",
            str(root / "receipts.sqlite3"),
            "--agent-identity",
            "luna-agent",
            "--task-id",
            "daily-row-claim",
            "--flow-id",
            "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
            "--scenario",
            "consume-stamina-row-claim",
            "--variant",
            variant,
        ]

    def _receipt(self, root: Path, mode: str, *, command: list[str] | None = None):
        state = root / "receipts.sqlite3"
        controller = control.DelegatedRuntimeReceiptController(state)
        controller._candidate = lambda: ("head", "fingerprint")  # type: ignore[method-assign]
        command = command or self._command(root, mode)
        variant = (
            "consume-stamina-dismiss-vip"
            if mode == "dismiss-vip-popup"
            else f"consume-stamina-{mode}"
        )
        if mode == "prepare":
            receipt_class = "reconnaissance"
            identities = ["daily-row-prepare-observation"]
            classes = ["observation"]
            consequence = "navigation_only"
            total = 0
            terminals = ["observed", "evidence_required"]
            result_identity = "daily-row-claim:prepare:consume_stamina"
            gates = {}
        elif mode == "canary":
            receipt_class = "canary"
            identities = ["daily-row-claim:consume_stamina"]
            classes = ["reward_claim"]
            consequence = "ordinary_development"
            total = 1
            terminals = ["completed", "evidence_required"]
            result_identity = "daily-row-claim:canary:consume_stamina"
            gates = {
                "implementation_self_check_evidence": "self-check",
                "independent_read_only_tester_evidence": "tester",
                "parent_integration_acceptance": "accepted",
            }
        else:
            receipt_class = "reconnaissance"
            identities = ["reset-popup-close"]
            classes = ["navigation"]
            consequence = "navigation_only"
            total = 1
            terminals = ["observed", "evidence_required"]
            result_identity = "daily-row-claim:popup-dismiss:vip-points"
            gates = {}
        action_bindings = [
            {
                "action_identity": identities[0],
                "action_class": classes[0],
                "consequence_class": consequence,
                "resource_affecting": False,
                "combat_confirmation": False,
            }
        ]
        receipt = controller.issue(
            task_id="daily-row-claim",
            flow_id="DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
            receipt_class=receipt_class,
            agent_identity="luna-agent",
            command_argv=command,
            scenario="consume-stamina-row-claim",
            variant=variant,
            permitted_action_identities=identities,
            permitted_action_classes=classes,
            action_bindings=action_bindings,
            consequence_class=consequence,
            max_total_inputs=total,
            max_resource_affecting_inputs=0,
            max_combat_confirmations=0,
            permitted_terminal_states=terminals,
            result_identity=result_identity,
            **gates,
        )
        return controller, receipt

    def _run_pnsctl(self, root: Path, mode: str):
        state = root / "receipts.sqlite3"
        controller, receipt = self._receipt(root, mode)
        variant = str(receipt["variant"])

        def connect(**kwargs):
            return ClaimCanaryRuntime(Path(kwargs["output_directory"]))

        with patch.object(pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"), patch.object(
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
            return_value=ScriptedClaimRecognizer(
                "points" if mode == "canary" else "points"
            ),
        ), patch.object(
            boundary,
            "RUNTIME_INPUT_LOCK_PATH",
            root / "lock.sqlite3",
        ), patch.object(
            daily,
            "DAILY_CLAIM_SUCCESS_POLL_INTERVAL_SECONDS",
            0.0,
        ):
            output = pnsctl.development_session_daily_row_claim(
                mode=mode,
                max_inputs=0 if mode == "prepare" else 1,
                delegated_receipt=state,
                agent_identity="luna-agent",
                task_id="daily-row-claim",
                flow_id="DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                scenario="consume-stamina-row-claim",
                variant=variant,
                command_argv=self._command(root, mode),
            )
        return json.loads(output), controller, receipt

    def test_parser_and_prepare_receipt_freeze_zero_input_observation_binding(self):
        parsed = pnsctl.parser().parse_args(
            self._command(Path("receipt.sqlite3"), "prepare")
        )
        self.assertEqual(parsed.development_command, "daily-row-claim")
        self.assertEqual(parsed.mode, "prepare")
        self.assertEqual(parsed.max_inputs, 0)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller, receipt = self._receipt(root, "prepare")
            self.assertEqual(receipt["receipt_class"], "reconnaissance")
            self.assertEqual(receipt["max_total_inputs"], 0)
            self.assertEqual(
                receipt["permitted_action_identities"],
                ["daily-row-prepare-observation"],
            )
            self.assertEqual(receipt["permitted_action_classes"], ["observation"])
            self.assertEqual(
                receipt["action_bindings"],
                [
                    {
                        "action_identity": "daily-row-prepare-observation",
                        "action_class": "observation",
                        "consequence_class": "navigation_only",
                        "resource_affecting": False,
                        "combat_confirmation": False,
                    }
                ],
            )
            pnsctl._validate_daily_row_claim_receipt(receipt, mode="prepare")
            self.assertEqual(controller.inspect()["status"], "issued")

    def test_parser_and_dismiss_receipt_freeze_popup_navigation_before_consume(self):
        command = self._command(Path("receipt.sqlite3"), "dismiss-vip-popup")
        parsed = pnsctl.parser().parse_args(command)
        self.assertEqual(parsed.development_command, "daily-row-claim")
        self.assertEqual(parsed.mode, "dismiss-vip-popup")
        self.assertEqual(parsed.max_inputs, 1)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller, receipt = self._receipt(root, "dismiss-vip-popup")
            self.assertEqual(receipt["receipt_class"], "reconnaissance")
            self.assertEqual(receipt["max_total_inputs"], 1)
            self.assertEqual(receipt["permitted_action_identities"], ["reset-popup-close"])
            self.assertEqual(receipt["permitted_action_classes"], ["navigation"])
            self.assertEqual(receipt["consequence_class"], "navigation_only")
            self.assertEqual(
                receipt["evidence_result_binding"]["result_identity"],
                "daily-row-claim:popup-dismiss:vip-points",
            )
            pnsctl._validate_daily_row_claim_receipt(
                receipt,
                mode="dismiss-vip-popup",
            )
            for field, value in (
                ("variant", "consume-stamina-canary"),
                ("max_total_inputs", 2),
                ("permitted_action_identities", ["daily-row-claim:consume_stamina"]),
            ):
                with self.subTest(field=field):
                    wrong = dict(receipt)
                    wrong[field] = value
                    with self.assertRaises(pnsctl.OperatorError):
                        pnsctl._validate_daily_row_claim_receipt(
                            wrong,
                            mode="dismiss-vip-popup",
                        )
            self.assertEqual(controller.inspect()["status"], "issued")

    def test_dismiss_artifact_failure_records_durable_evidence_required_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "receipts.sqlite3"
            controller, receipt = self._receipt(root, "dismiss-vip-popup")
            route_result = {
                "status": "observed",
                "mode": "dismiss-vip-popup",
                "input_count": 1,
                "resource_affecting_inputs": 0,
                "combat_confirmations": 0,
                "actions": [
                    {
                        "label": "reset-popup-close",
                        "requested_action": "navigation",
                        "status": "completed",
                    }
                ],
            }

            def connect(**kwargs):
                return VipPopupRuntime(Path(kwargs["output_directory"]))

            with patch.object(
                pnsctl,
                "DEVELOPMENT_SESSION_ROOT",
                root / "sessions",
            ), patch.object(
                pnsctl,
                "DEVELOPMENT_CHECKPOINT_PATHS",
                (),
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
                "run_daily_row_claim_vip_popup_dismissal",
                return_value=route_result,
            ), patch.object(
                pnsctl,
                "_write_daily_row_claim_artifacts",
                side_effect=OSError("fallback artifact write failed"),
            ), patch.object(
                boundary,
                "RUNTIME_INPUT_LOCK_PATH",
                root / "lock.sqlite3",
            ):
                with self.assertRaisesRegex(
                    OSError,
                    "fallback artifact write failed",
                ):
                    pnsctl.development_session_daily_row_claim(
                        mode="dismiss-vip-popup",
                        max_inputs=1,
                        delegated_receipt=state,
                        agent_identity="luna-agent",
                        task_id="daily-row-claim",
                        flow_id="DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                        scenario="consume-stamina-row-claim",
                        variant="consume-stamina-dismiss-vip",
                        command_argv=self._command(root, "dismiss-vip-popup"),
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
            self.assertEqual(
                json.loads(terminal[1])["status"],
                "evidence_required",
            )

    def test_prepare_fake_runtime_retains_native_hashes_overlay_semantics_and_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, controller, receipt = self._run_pnsctl(root, "prepare")

            self.assertEqual(result["status"], "observed")
            self.assertEqual(result["input_count"], 0)
            self.assertEqual(result["resource_affecting_inputs"], 0)
            self.assertEqual(result["combat_confirmations"], 0)
            self.assertTrue(result["ownership_released"])
            self.assertEqual(result["claim"]["objective_key"], "consume_stamina")
            self.assertEqual(result["claim"]["current_progress"], 36)
            self.assertEqual(result["claim"]["required_progress"], 20)
            self.assertEqual(result["claim"]["points"], 0)
            self.assertEqual(result["claim"]["reset_timer"], "04:00:00")
            self.assertEqual(result["claim"]["game_day_id"], result["game_day_id"])
            self.assertEqual(tuple(result["claim"]["row_bounds"]), (82, 432, 773, 545))
            self.assertEqual(tuple(result["claim"]["claim_roi"]), (605, 455, 755, 535))
            source = result["frames"]["source"]
            self.assertEqual(len(source["sha256"]), 64)
            session = Path(result["session_directory"])
            raw = session / source["path"]
            self.assertTrue(raw.is_file())
            self.assertEqual(cv2.imread(str(raw)).shape[:2], (1280, 800))
            annotated = session / result["claim"]["annotated_source"]
            self.assertTrue(annotated.is_file())
            self.assertGreater(annotated.stat().st_size, 0)
            self.assertEqual(controller.inspect()["status"], "consumed")
            connection = controller._connection()
            try:
                terminal = connection.execute(
                    "SELECT status FROM delegated_results WHERE receipt_id=?",
                    (receipt["receipt_id"],),
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(terminal[0], "observed")

    def test_prepare_rejects_wrong_identity_or_class_before_receipt_consumption(self):
        cases = (
            (
                "permitted_action_identities",
                ["daily-row-prepare-capability"],
                ["observation"],
                "daily-row-prepare-capability",
                "observation",
            ),
            (
                "permitted_action_classes",
                ["daily-row-prepare-observation"],
                ["navigation"],
                "daily-row-prepare-observation",
                "navigation",
            ),
        )
        for field, identities, classes, identity, action_class in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state = root / "receipts.sqlite3"
                command = self._command(root, "prepare")
                controller = control.DelegatedRuntimeReceiptController(state)
                controller._candidate = lambda: ("head", "fingerprint")  # type: ignore[method-assign]
                controller.issue(
                    task_id="daily-row-claim",
                    flow_id="DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                    receipt_class="reconnaissance",
                    agent_identity="luna-agent",
                    command_argv=command,
                    scenario="consume-stamina-row-claim",
                    variant="consume-stamina-prepare",
                    permitted_action_identities=identities,
                    permitted_action_classes=classes,
                    action_bindings=[
                        {
                            "action_identity": identity,
                            "action_class": action_class,
                            "consequence_class": "navigation_only",
                            "resource_affecting": False,
                            "combat_confirmation": False,
                        }
                    ],
                    consequence_class="navigation_only",
                    max_total_inputs=0,
                    max_resource_affecting_inputs=0,
                    max_combat_confirmations=0,
                    permitted_terminal_states=["observed", "evidence_required"],
                    result_identity="daily-row-claim:prepare:consume_stamina",
                )
                with self.assertRaisesRegex(
                    pnsctl.OperatorError,
                    f"daily row Claim receipt {field}",
                ):
                    pnsctl.development_session_daily_row_claim(
                        mode="prepare",
                        max_inputs=0,
                        delegated_receipt=state,
                        agent_identity="luna-agent",
                        task_id="daily-row-claim",
                        flow_id="DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                        scenario="consume-stamina-row-claim",
                        variant="consume-stamina-prepare",
                        command_argv=command,
                    )
                self.assertEqual(controller.inspect()["status"], "issued")

    def test_prepare_rejects_mismatched_variant_or_budget_before_receipt_consumption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller, _receipt = self._receipt(root, "prepare")
            command = self._command(root, "prepare")
            with self.assertRaisesRegex(pnsctl.OperatorError, "max-inputs 0"):
                pnsctl.development_session_daily_row_claim(
                    mode="prepare",
                    max_inputs=1,
                    delegated_receipt=root / "receipts.sqlite3",
                    agent_identity="luna-agent",
                    task_id="daily-row-claim",
                    flow_id="DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                    scenario="consume-stamina-row-claim",
                    variant="consume-stamina-prepare",
                    command_argv=command,
                )
            self.assertEqual(controller.inspect()["status"], "issued")

            bad_command = self._command(root, "prepare")
            bad_command[-1] = "wrong-variant"
            with self.assertRaises(pnsctl.OperatorError):
                pnsctl.development_session_daily_row_claim(
                    mode="prepare",
                    max_inputs=0,
                    delegated_receipt=root / "receipts.sqlite3",
                    agent_identity="luna-agent",
                    task_id="daily-row-claim",
                    flow_id="DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                    scenario="consume-stamina-row-claim",
                    variant="wrong-variant",
                    command_argv=bad_command,
                )
            self.assertEqual(controller.inspect()["status"], "issued")

    def test_canary_receipt_and_pnsctl_route_bind_reward_claim_and_terminal_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, controller, _receipt = self._run_pnsctl(root, "canary")

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["input_count"], 1)
            self.assertEqual(len(result["actions"]), 1)
            self.assertEqual(result["actions"][0]["requested_action"], "reward_claim")
            self.assertEqual(result["claim"]["points_after"], 5)
            self.assertIn("immediate_before", result["frames"])
            self.assertIn("immediate_post", result["frames"])
            self.assertTrue(result["claim"]["annotated_immediate_before"])
            self.assertEqual(controller.inspect()["status"], "consumed")

    def test_prepare_failure_records_durable_evidence_required_before_fallback_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller, receipt = self._receipt(root, "prepare")
            with patch.object(
                pnsctl,
                "DEVELOPMENT_SESSION_ROOT",
                root / "sessions",
            ), patch.object(
                pnsctl,
                "DEVELOPMENT_CHECKPOINT_PATHS",
                (),
            ), patch.object(
                control,
                "DelegatedRuntimeReceiptController",
                return_value=controller,
            ), patch.object(
                LocalBlueStacksRuntime,
                "connect",
                side_effect=pnsctl.OperatorError("recognition failed"),
            ), patch.object(
                pnsctl,
                "_write_daily_row_claim_artifacts",
                side_effect=OSError("fallback artifact write failed"),
            ), patch.object(
                boundary,
                "RUNTIME_INPUT_LOCK_PATH",
                root / "lock.sqlite3",
            ):
                with self.assertRaisesRegex(OSError, "fallback artifact write failed"):
                    pnsctl.development_session_daily_row_claim(
                        mode="prepare",
                        max_inputs=0,
                        delegated_receipt=root / "receipts.sqlite3",
                        agent_identity="luna-agent",
                        task_id="daily-row-claim",
                        flow_id="DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                        scenario="consume-stamina-row-claim",
                        variant="consume-stamina-prepare",
                        command_argv=self._command(root, "prepare"),
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


if __name__ == "__main__":
    unittest.main()
