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
from tasks.home_nav_recognition import NAV_STRIP_BOX, _load_template


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
            x0, y0, x1, y1 = NAV_STRIP_BOX
            image[y0:y1, x0:x1] = _load_template()
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
                "text": [],
                "left": [],
                "top": [],
                "width": [],
                "height": [],
                "conf": [],
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
        self.assertEqual(target, (291, 1223, 351, 1271))
        self.assertEqual(
            (target[0] + target[2]) // 2,
            321,
        )
        self.assertEqual(
            (target[1] + target[3]) // 2,
            1247,
        )

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
            if float(np.mean(image[:, 536:1066])) <= float(np.mean(image[:, :534])):
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

    def test_template_home_adapter_uses_fixed_quest_point_without_navigation_ocr(self) -> None:
        captures = Path(__file__).resolve().parents[1] / ".local-captures" / "development-sessions"
        fixtures = (
            ("delegated-3589bf46-33a8-4396-8517-fccce900dc15", True),
            ("delegated-9ba8b6e5-3c79-49df-9d96-8ac24a9421fd", True),
            ("delegated-e0dece90-4270-4cda-8aad-15bda0c689c0", True),
            ("delegated-5dd7d35b-cb70-4261-a26f-f993e33300e7", False),
        )
        checked = 0
        for session_id, expected_home in fixtures:
            matches = sorted(
                (captures / session_id).glob(
                    "runtime/*/frames/0001-home-source.png"
                )
            )
            if not matches:
                continue
            frame = cv2.imread(str(matches[0]))
            self.assertIsNotNone(frame)
            assert frame is not None
            recognition = daily.DailyRowClaimRecognizer(
                ocr=self._ocr_for([])
            ).recognize_home(frame)
            checked += 1
            self.assertEqual(recognition.recognized, expected_home, session_id)
            if expected_home:
                self.assertEqual(recognition.target_roi, (291, 1223, 351, 1271))
                self.assertEqual(
                    recognition.visual_evidence["template_home"]["quest_tap_point"],
                    (321, 1247),
                )
                self.assertEqual(
                    recognition.visual_evidence["template_home"]["recognized"],
                    True,
                )
            else:
                self.assertIsNone(recognition.target_roi)
                self.assertFalse(
                    recognition.visual_evidence["template_home"]["recognized"]
                )
        if checked == 0:
            self.skipTest("retained Home fixtures are unavailable")

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

    @unittest.skip("legacy OCR Home geometry replaced by template adapter")
    def test_retained_home_source_binds_current_quest_icon_component(self) -> None:
        source_path = (
            Path(__file__).resolve().parents[1]
            / ".local-captures/development-sessions/delegated-9ba8b6e5-3c79-49df-9d96-8ac24a9421fd"
            / "runtime/daily-row-reconnaissance-20260817T022942663935Z/frames/0001-home-source.png"
        )
        if not source_path.is_file():
            self.skipTest("retained Home source is unavailable in this checkout")
        payload = source_path.read_bytes()
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            "0efd272a66314b944978f1b7acd82c9482d3ba02b13585b5ac4dd2694be80d8e",
        )
        frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame)
        assert frame is not None
        recognizer = daily.DailyRowClaimRecognizer(
            ocr=self._ocr_for(
                [
                    ("world", 30 * 2, (1242 - 1000) * 2, (137 - 30) * 2, (1268 - 1242) * 2),
                    ("quest", 284 * 2, (1242 - 1000) * 2, (359 - 284) * 2, (1266 - 1242) * 2),
                    ("bag", 406 * 2, (1244 - 1000) * 2, (450 - 406) * 2, (1266 - 1244) * 2),
                ]
            )
        )

        recognition = recognizer.recognize_home(frame)

        self.assertTrue(recognition.recognized)
        self.assertEqual(recognition.target_identity, daily.HOME_QUEST_IDENTITY)
        self.assertEqual(recognition.target_roi, (318, 1202, 321, 1205))
        binding = recognition.visual_evidence["quest_binding"]
        self.assertEqual(binding["component_count"], 1)
        self.assertEqual(binding["component_roi"], (311, 1196, 333, 1215))
        self.assertEqual(binding["selected_point"], (319, 1203))
        self.assertEqual(binding["ownership_lane"], (202, 375))
        self.assertEqual(binding["icon_band"], (202, 1146, 375, 1242))

    @unittest.skip("legacy OCR Home geometry replaced by template adapter")
    def test_fresh_home_source_binds_quest_with_right_side_navigation_chain(self) -> None:
        source_path = (
            Path(__file__).resolve().parents[1]
            / ".local-captures/development-sessions/delegated-e0dece90-4270-4cda-8aad-15bda0c689c0"
            / "runtime/daily-row-reconnaissance-20260817T054254117686Z/frames/0001-home-source.png"
        )
        if not source_path.is_file():
            self.skipTest("fresh Home source is unavailable in this checkout")
        payload = source_path.read_bytes()
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            "a82f1e4f3b9760810acbe139fb7afea7dd25433e896afb7297a1cec6f94fe442",
        )
        frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame)
        assert frame is not None
        recognizer = daily.DailyRowClaimRecognizer(
            ocr=self._ocr_for(
                [
                    ("quest", 284 * 2, (1230 - 1000) * 2, 75 * 2, 38 * 2),
                    ("bag", 390 * 2, (1233 - 1000) * 2, 108 * 2, 33 * 2),
                    ("mail", 512 * 2, (1242 - 1000) * 2, 50 * 2, 20 * 2),
                    ("more", 714 * 2, (1222 - 1000) * 2, 75 * 2, 40 * 2),
                ]
            )
        )

        recognition = recognizer.recognize_home(frame)

        self.assertTrue(recognition.recognized)
        self.assertEqual(recognition.target_identity, daily.HOME_QUEST_IDENTITY)
        binding = recognition.visual_evidence["quest_binding"]
        self.assertEqual(binding["navigation_evidence"], "right_side_label_chain")
        self.assertIsNone(binding["left_label_roi"])
        self.assertEqual(binding["right_label_roi"], (390, 1233, 498, 1266))
        self.assertEqual(binding["component_count"], 1)
        self.assertEqual(binding["raw_support_result"]["supported_pixel"], True)
        self.assertEqual(binding["raw_support_result"]["complete_3x3"], True)
        selected_x, selected_y = binding["selected_point"]
        component_x0, component_y0, component_x1, component_y1 = binding["component_roi"]
        self.assertTrue(component_x0 <= selected_x < component_x1)
        self.assertTrue(component_y0 <= selected_y < component_y1)
        target_x0, target_y0, target_x1, target_y1 = recognition.target_roi
        self.assertEqual((target_x1 - target_x0, target_y1 - target_y0), (3, 3))

    @unittest.skip("legacy OCR Home geometry replaced by template adapter")
    def test_home_quest_right_side_fallback_remains_fail_closed(self) -> None:
        right_chain = [
            ("quest", 284 * 2, (1230 - 1000) * 2, 75 * 2, 38 * 2),
            ("bag", 390 * 2, (1233 - 1000) * 2, 108 * 2, 33 * 2),
            ("mail", 512 * 2, (1242 - 1000) * 2, 50 * 2, 20 * 2),
            ("more", 714 * 2, (1222 - 1000) * 2, 75 * 2, 40 * 2),
        ]
        frame = self._home_frame()

        arbitrary_chain_frame = self._home_frame()
        cv2.rectangle(
            arbitrary_chain_frame,
            (310, 1170),
            (350, 1200),
            (0, 180, 255),
            -1,
        )
        arbitrary_chain = [
            right_chain[0],
            ("world", right_chain[1][1], right_chain[1][2], right_chain[1][3], right_chain[1][4]),
            ("hero", right_chain[2][1], right_chain[2][2], right_chain[2][3], right_chain[2][4]),
            ("alliance", right_chain[3][1], right_chain[3][2], right_chain[3][3], right_chain[3][4]),
        ]
        wrong_quest = daily.DailyRowClaimRecognizer(
            ocr=self._ocr_for(arbitrary_chain)
        ).recognize_home(arbitrary_chain_frame)
        self.assertFalse(wrong_quest.recognized)
        self.assertEqual(
            wrong_quest.visual_evidence["quest_binding"]["reason"],
            "quest_and_adjacent_navigation_labels_not_proven",
        )

        wide_gap_frame = self._home_frame()
        cv2.rectangle(
            wide_gap_frame,
            (310, 1170),
            (350, 1200),
            (0, 180, 255),
            -1,
        )
        wide_gap_chain = [
            *right_chain[:3],
            ("more", 760 * 2, (1222 - 1000) * 2, 40 * 2, 40 * 2),
        ]
        wide_gap = daily.DailyRowClaimRecognizer(
            ocr=self._ocr_for(wide_gap_chain)
        ).recognize_home(wide_gap_frame)
        self.assertFalse(wide_gap.recognized)
        self.assertEqual(
            wide_gap.visual_evidence["quest_binding"]["reason"],
            "quest_and_adjacent_navigation_labels_not_proven",
        )

        lone = daily.DailyRowClaimRecognizer(
            ocr=self._ocr_for([right_chain[0]])
        ).recognize_home(frame)
        self.assertFalse(lone.recognized)
        self.assertEqual(
            lone.visual_evidence["quest_binding"]["reason"],
            "quest_and_adjacent_navigation_labels_not_proven",
        )

        insufficient = daily.DailyRowClaimRecognizer(
            ocr=self._ocr_for(right_chain[:3])
        ).recognize_home(frame)
        self.assertFalse(insufficient.recognized)
        self.assertEqual(
            insufficient.visual_evidence["quest_binding"]["reason"],
            "quest_and_adjacent_navigation_labels_not_proven",
        )

        unsupported = daily.DailyRowClaimRecognizer(
            ocr=self._ocr_for(right_chain)
        ).recognize_home(frame)
        self.assertFalse(unsupported.recognized)
        self.assertEqual(
            unsupported.visual_evidence["quest_binding"]["reason"],
            "no_unique_home_quest_visual_component",
        )

        wrong_dimensions = daily.DailyRowClaimRecognizer(
            ocr=self._ocr_for(right_chain)
        ).recognize_home(np.zeros((640, 400, 3), dtype=np.uint8))
        self.assertFalse(wrong_dimensions.recognized)
        self.assertEqual(wrong_dimensions.reason, "profile_dimensions_mismatch")

    @unittest.skip("legacy OCR Home geometry replaced by template adapter")
    def test_current_home_icon_morphology_excludes_low_value_background(self) -> None:
        frame = self._home_frame()
        # The muted, saturated navigation background is deliberately present
        # across the OCR-derived icon band; only the brighter icon remains
        # eligible for the raw high-saturation component pass.
        cv2.rectangle(frame, (282, 1020), (437, 1099), (61, 100, 100), -1)
        cv2.rectangle(frame, (330, 1038), (389, 1081), (25, 90, 150), -1)

        recognition = self._home_recognizer().recognize_home(frame)

        self.assertTrue(recognition.recognized)
        binding = recognition.visual_evidence["quest_binding"]
        self.assertEqual(binding["component_count"], 1)
        self.assertGreaterEqual(binding["component_roi"][0], 330)
        self.assertLessEqual(binding["component_roi"][2], 390)

    @unittest.skip("legacy OCR Home geometry replaced by template adapter")
    def test_home_quest_preserves_muted_antialiased_icon_support(self) -> None:
        frame = self._home_frame()
        # BGR (109, 180, 180) is approximately HSV saturation 100/value 180.
        cv2.rectangle(frame, (330, 1038), (389, 1081), (109, 180, 180), -1)

        recognition = self._home_recognizer().recognize_home(frame)

        self.assertTrue(recognition.recognized)
        self.assertEqual(
            recognition.visual_evidence["quest_binding"]["component_count"],
            1,
        )

    @unittest.skip("legacy OCR Home geometry replaced by template adapter")
    def test_home_quest_rejects_low_value_muted_background_without_icon(self) -> None:
        frame = self._home_frame()
        # BGR (61, 100, 100) is approximately HSV saturation 100/value 100
        # and is the deliberately excluded low-value navigation background.
        cv2.rectangle(frame, (330, 1038), (389, 1081), (61, 100, 100), -1)

        recognition = self._home_recognizer().recognize_home(frame)

        self.assertFalse(recognition.recognized)
        self.assertEqual(
            recognition.visual_evidence["quest_binding"]["reason"],
            "no_unique_home_quest_visual_component",
        )

    @unittest.skip("legacy OCR Home geometry replaced by template adapter")
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

    @unittest.skip("legacy OCR Home geometry replaced by template adapter")
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

    @unittest.skip("legacy OCR Home geometry replaced by template adapter")
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

    @unittest.skip("legacy OCR Home geometry replaced by template adapter")
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

    @unittest.skip("legacy OCR Home geometry replaced by template adapter")
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

    @unittest.skip("legacy OCR Home geometry replaced by template adapter")
    def test_home_quest_rejects_out_of_lane_and_wrong_label_evidence(self) -> None:
        out_of_lane = self._home_frame()
        cv2.rectangle(out_of_lane, (240, 1040), (270, 1070), (0, 180, 255), -1)
        out_of_lane_recognition = self._home_recognizer().recognize_home(out_of_lane)
        self.assertFalse(out_of_lane_recognition.recognized)
        self.assertEqual(
            out_of_lane_recognition.visual_evidence["quest_binding"]["reason"],
            "no_unique_home_quest_visual_component",
        )

        wrong_label = self._home_frame()
        cv2.rectangle(wrong_label, (330, 1040), (390, 1080), (0, 180, 255), -1)
        wrong_label_recognizer = daily.DailyRowClaimRecognizer(
            ocr=self._ocr_for(
                [
                    ("world", 180 * 2, 100 * 2, 50 * 2, 20 * 2),
                    ("quest", 330 * 2, 100 * 2, 60 * 2, 20 * 2),
                    ("settings", 490 * 2, 100 * 2, 50 * 2, 20 * 2),
                ]
            )
        )
        wrong_label_recognition = wrong_label_recognizer.recognize_home(wrong_label)
        self.assertFalse(wrong_label_recognition.recognized)
        self.assertEqual(
            wrong_label_recognition.visual_evidence["quest_binding"]["reason"],
            "quest_and_adjacent_navigation_labels_not_proven",
        )

    @unittest.skip("legacy OCR Home geometry replaced by template adapter")
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

    @unittest.skip("legacy OCR Home geometry replaced by template adapter")
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

    @unittest.skip("legacy OCR Home geometry replaced by template adapter")
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

    @unittest.skip("legacy OCR Home geometry replaced by template adapter")
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
                    ("alliance", 1240, 70, 140, 20),
                ]
            )
        ).recognize_daily_selected(frame)
        self.assertTrue(recognition.recognized)
        self.assertEqual(recognition.state, daily.DAILY_SELECTED_STATE)
        self.assertGreater(
            recognition.visual_evidence["selected_margin"],
            0.015,
        )

    def test_selected_daily_fallback_rejects_disassociated_alliance_row(self) -> None:
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        cv2.rectangle(frame, (170, 52), (620, 150), (0, 210, 255), -1)
        recognition = daily.DailyRowClaimRecognizer(
            ocr=self._ocr_for(
                [
                    ("main", 100 * 2, (70 - 35) * 2, 70 * 2, 20 * 2),
                    ("alliance", 620 * 2, (180 - 35) * 2, 140 * 2, 20 * 2),
                ]
            )
        ).recognize_daily_selected(frame)

        self.assertFalse(recognition.recognized)
        self.assertEqual(recognition.state, daily.UNKNOWN_STATE)
        self.assertGreater(recognition.visual_evidence["selected_margin"], 0.02)
        self.assertFalse(recognition.visual_evidence["tab_row_compatible"])
        self.assertEqual(
            recognition.visual_evidence["reason"],
            "main-alliance-tab-row-is-vertically-incompatible",
        )

    def test_retained_selected_daily_uses_center_tab_without_daily_ocr(self) -> None:
        captures = Path(__file__).resolve().parents[1] / ".local-captures"
        daily_path = (
            captures
            / "development-sessions/delegated-ff8e1873-88d5-4ad6-8a2d-52a22782e49c"
            / "runtime/daily-row-reconnaissance-20260817T201002000223Z/frames"
            / "0010-quest-daily-tab-poll-04.png"
        )
        main_path = (
            captures
            / "development-sessions/delegated-ff8e1873-88d5-4ad6-8a2d-52a22782e49c"
            / "runtime/daily-row-reconnaissance-20260817T201002000223Z/frames"
            / "0004-home-quest-entry-poll-01.png"
        )
        if not daily_path.is_file() or not main_path.is_file():
            self.skipTest("retained Daily/Main frames are unavailable")

        def retained_tab_context_ocr(image: np.ndarray) -> dict[str, list[object]]:
            if image.shape[0] == daily.NATIVE_HEIGHT * 2:
                tokens: list[tuple[str, int, int, int, int]] = []
            else:
                tokens = [
                    ("Main", 42 * 2, (83 - 35) * 2, (172 - 42) * 2, (103 - 83) * 2),
                    (
                        "Alliance",
                        493 * 2,
                        (74 - 35) * 2,
                        (594 - 493) * 2,
                        (94 - 74) * 2,
                    ),
                    (
                        "Activity",
                        493 * 2,
                        (96 - 35) * 2,
                        (594 - 493) * 2,
                        (114 - 96) * 2,
                    ),
                ]
            return {
                "text": [item[0] for item in tokens],
                "left": [item[1] for item in tokens],
                "top": [item[2] for item in tokens],
                "width": [item[3] for item in tokens],
                "height": [item[4] for item in tokens],
                "conf": ["95"] * len(tokens),
            }

        daily_frame = cv2.imread(str(daily_path))
        main_frame = cv2.imread(str(main_path))
        self.assertIsNotNone(daily_frame)
        self.assertIsNotNone(main_frame)
        assert daily_frame is not None
        assert main_frame is not None

        recognizer = daily.DailyRowClaimRecognizer(ocr=retained_tab_context_ocr)
        selected = recognizer.recognize_daily_selected(daily_frame)
        self.assertTrue(selected.recognized)
        self.assertEqual(selected.state, daily.DAILY_SELECTED_STATE)
        self.assertNotIn("daily", selected.ocr_text.split())
        self.assertGreater(selected.visual_evidence["selected_margin"], 0.02)

        main = recognizer.recognize_daily_selected(main_frame)
        self.assertFalse(main.recognized)
        self.assertEqual(main.state, daily.UNKNOWN_STATE)
        self.assertLessEqual(main.visual_evidence["selected_margin"], 0.02)

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
        for _claim_text, claim_roi in claim_tokens:
            cv2.rectangle(
                frame,
                (claim_roi[0] - 10, claim_roi[1] - 5),
                (claim_roi[2] + 10, claim_roi[3] + 5),
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
        self.assertEqual(recognition.target_identity, "daily-quest-claim")
        self.assertEqual(recognition.target_roi, (640, 475, 721, 516))
        evidence = recognition.visual_evidence
        self.assertNotIn("objective_key", evidence)
        self.assertNotIn("objective_name", evidence)
        self.assertNotIn("current_progress", evidence)
        self.assertNotIn("required_progress", evidence)
        self.assertNotIn("reward_points", evidence)
        self.assertEqual(evidence["points"], 0)
        self.assertEqual(evidence["row_bounds"], (70, 432, 780, 542))
        self.assertEqual(evidence["claim_roi"], (640, 475, 721, 516))
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
        self.assertFalse(observation.catalog_reconciled)
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

    def test_gold_claim_binding_does_not_require_stylized_claim_ocr(self):
        frame, _ocr, tokens = self._claim_fixture()
        ocr_without_claim = self._ocr_for_native_tokens(
            [item for item in tokens if item[0].casefold() != "claim"]
        )
        recognition = daily.DailyRowClaimRecognizer(
            ocr=ocr_without_claim
        ).recognize_daily_claim(
            frame,
            observed_utc="2026-08-16T00:00:00Z",
        )

        self.assertTrue(recognition.recognized)
        self.assertEqual(recognition.visual_evidence["recognized_claim_controls"], 1)
        self.assertEqual(recognition.visual_evidence["claim_ocr_roi"], None)
        self.assertEqual(recognition.visual_evidence["button_evidence"]["button_class"], "ordinary_claim_button")

    def test_red_go_control_is_rejected_by_gold_hsv_binding(self):
        frame, ocr, _tokens = self._claim_fixture(
            claim_tokens=(),
            extra_tokens=(("Go", (650, 480, 710, 510)),),
        )
        cv2.rectangle(frame, (640, 475), (720, 515), (0, 0, 255), -1)
        recognition = daily.DailyRowClaimRecognizer(ocr=ocr).recognize_daily_claim(
            frame,
            observed_utc="2026-08-16T00:00:00Z",
        )

        self.assertTrue(recognition.recognized)
        self.assertFalse(recognition.visual_evidence["claim_ready"])
        self.assertEqual(recognition.visual_evidence["recognized_claim_controls"], 0)
        self.assertIsNone(recognition.target_roi)

    def test_multiple_safe_claim_controls_select_one_deterministically(self):
        frame, ocr, _tokens = self._claim_fixture(
            claim_tokens=(
                ("Claim", (570, 480, 610, 510)),
                ("Claim", (670, 480, 710, 510)),
            )
        )
        recognition = daily.DailyRowClaimRecognizer(ocr=ocr).recognize_daily_claim(
            frame,
            observed_utc="2026-08-16T00:00:00Z",
        )

        self.assertTrue(recognition.recognized)
        self.assertEqual(recognition.target_roi, (560, 475, 621, 516))
        evidence = recognition.visual_evidence
        self.assertEqual(evidence["recognized_claim_controls"], 2)
        self.assertEqual(evidence["available_claim_controls"], 2)
        self.assertEqual(evidence["available_ordinary_claim_controls"], 2)
        self.assertEqual(
            [candidate["status"] for candidate in evidence["claim_candidates"]],
            ["eligible", "eligible"],
        )

    def test_multiple_claim_controls_skip_unsafe_cost_and_select_safe_control(self):
        frame, ocr, _tokens = self._claim_fixture(
            claim_tokens=(
                ("Claim", (570, 480, 610, 510)),
                ("Claim", (670, 480, 710, 510)),
            ),
            extra_tokens=(("Gems", (400, 500, 440, 525)),),
        )
        recognition = daily.DailyRowClaimRecognizer(ocr=ocr).recognize_daily_claim(
            frame,
            observed_utc="2026-08-16T00:00:00Z",
        )

        self.assertTrue(recognition.recognized)
        self.assertEqual(recognition.target_roi, (660, 475, 721, 516))
        evidence = recognition.visual_evidence
        self.assertEqual(evidence["recognized_claim_controls"], 2)
        self.assertEqual(evidence["available_ordinary_claim_controls"], 1)
        self.assertIn(
            "claim_attached_cost",
            evidence["claim_candidates"][0]["rejection_reasons"],
        )

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
        self.assertIn("escaped", recognition.reason or "")

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
                "available_ordinary_claim_controls": 0,
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
        after_evidence.update(
            {"claim_ready": False, "available_ordinary_claim_controls": 0, "points": 5}
        )
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

class ClaimCanaryRuntime:
    execute = True
    frame_max_age_seconds = 30.0

    def __init__(self, root: Path):
        self.session = root / "runtime"
        self.session.mkdir(parents=True)
        self.events = self.session / "events.jsonl"
        self.labels: list[str] = []
        self.taps: list[dict[str, object]] = []
        self.backs: list[dict[str, object]] = []
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
                "consequence_class": (
                    getattr(delegated, "receipt", {}).get(
                        "consequence_class",
                        "ordinary_development",
                    )
                    if (delegated := boundary.current_delegated_runtime_context())
                    is not None
                    else "ordinary_development"
                ),
                "source_sha256": source.sha256,
            }
        )
        if delegated is not None:
            consequence_class = str(
                delegated.receipt.get("consequence_class", "ordinary_development")
            )
            delegated.reserve_input(
                action_identity=target_identity,
                action_class=action_class,
                consequence_class=consequence_class,
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

    def back(
        self,
        source: CapturedNativeFrame,
        *,
        action_key: str,
        target_identity: str = "android-back",
        continuation_of: str | None = None,
    ) -> None:
        self.reservations.append(
            {
                "action_identity": target_identity,
                "action_class": "navigation",
                "consequence_class": (
                    getattr(delegated, "receipt", {}).get(
                        "consequence_class",
                        "ordinary_development",
                    )
                    if (delegated := boundary.current_delegated_runtime_context())
                    is not None
                    else "ordinary_development"
                ),
                "source_sha256": source.sha256,
            }
        )
        if delegated is not None:
            consequence_class = str(
                delegated.receipt.get("consequence_class", "ordinary_development")
            )
            delegated.reserve_input(
                action_identity=target_identity,
                action_class="navigation",
                consequence_class=consequence_class,
                source_evidence_hash=source.sha256,
                action_key=action_key,
            )
            delegated.mark_transported(action_key)
        self.backs.append(
            {
                "action_key": action_key,
                "target_identity": target_identity,
                "source_sha256": source.sha256,
                "continuation_of": continuation_of,
            }
        )
        self.input_count += 1
        with self.events.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "type": "dispatch",
                        "action_key": action_key,
                        "target_identity": "android-back",
                        "action_class": "navigation",
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
    def __init__(
        self,
        outcome: str,
        *,
        available_controls: int = 1,
        selected_daily: bool = True,
        home: bool = True,
        template_home: bool = True,
    ):
        self.outcome = outcome
        self.available_controls = available_controls
        self.selected_daily = selected_daily
        self.home = home
        self.template_home = template_home
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
        recognized = True
        reset_timer: str | None = "04:00:00"
        if not before and self.outcome == "points":
            points = 5
            ready = False
        elif not before and self.outcome == "row_disappeared":
            ready = False
        elif not before and self.outcome == "row_missing_points":
            ready = False
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
            "claim_ready": ready,
            "available_claim_controls": self.available_controls if ready else 0,
            "available_ordinary_claim_controls": self.available_controls if ready else 0,
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
            "daily-quest-claim" if ready else None,
            (605, 455, 755, 535) if ready else None,
            "scripted daily claim",
            visual,
            None if recognized else "full-frame overlay/modal detected",
        )

    def recognize_daily_selected(
        self,
        _frame: np.ndarray,
    ) -> daily.FrameRecognition:
        recognized = self.selected_daily and self.outcome not in {"selected_unknown", "overlay"}
        return daily.FrameRecognition(
            daily.DAILY_SELECTED_STATE if recognized else daily.UNKNOWN_STATE,
            recognized,
            "daily-quest-selected" if recognized else None,
            (280, 80, 370, 110) if recognized else None,
            "selected Daily",
            {
                "selected_daily": recognized,
                "unblurred": True,
                "blurred": False,
                "full_frame_overlay": {"recognized": not recognized},
            },
            None if recognized else "selected Daily is unknown",
        )

    def recognize_home(
        self,
        _frame: np.ndarray,
    ) -> daily.FrameRecognition:
        recognized = self.home and self.outcome not in {"non_home", "home_unknown"}
        return daily.FrameRecognition(
            daily.HOME_STATE if recognized else daily.QUEST_STATE,
            recognized,
            "home-quest-entry" if recognized else None,
            (180, 1028, 231, 1078) if recognized else None,
            "Home" if recognized else "Quest",
            {
                "template_home": {
                    "recognized": self.template_home and recognized
                },
                "full_frame_overlay": {"recognized": False},
            },
            None if recognized else "Home template was not recognized",
        )


class ImmediateBeforeBaselineClaimRecognizer(ScriptedClaimRecognizer):
    """Make the source baseline differ from the tap-authorizing frame."""

    def recognize_daily_claim(
        self,
        frame: np.ndarray,
        *,
        game_day_id: str | None = None,
    ) -> daily.FrameRecognition:
        recognition = super().recognize_daily_claim(
            frame,
            game_day_id=game_day_id,
        )
        if self.calls != 1:
            return recognition
        visual = dict(recognition.visual_evidence or {})
        visual["points"] = 10
        return replace(recognition, visual_evidence=visual)


class DailyClaimCanaryTests(unittest.TestCase):
    def test_standalone_canary_is_disabled_without_runtime_or_input_dispatch(self):
        from scripts import daily_claim_canary

        class RuntimeProbe:
            def __init__(self) -> None:
                self.taps = 0

            def tap(self, *_args, **_kwargs) -> None:
                self.taps += 1

        probe = RuntimeProbe()
        result = daily_claim_canary.run(probe)

        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(result["input_count"], 0)
        self.assertEqual(probe.taps, 0)
        self.assertNotIn("LocalBlueStacksRuntime", vars(daily_claim_canary))
        self.assertIn("pnsctl.py development-session daily-row-claim", result["canonical_command"])

    def _run_canary(
        self,
        root: Path,
        outcome: str,
        *,
        available_controls: int = 1,
        recognizer: ScriptedClaimRecognizer | None = None,
    ):
        runtime = ClaimCanaryRuntime(root)
        recognizer = recognizer or ScriptedClaimRecognizer(
            outcome,
            available_controls=available_controls,
        )
        with patch.object(daily, "DAILY_CLAIM_SUCCESS_POLL_INTERVAL_SECONDS", 0.0), patch.object(
            daily, "DAILY_CLAIM_SUCCESS_POLL_MAX_ATTEMPTS", 2
        ), patch.object(
            daily, "DAILY_RETURN_HOME_SUCCESS_POLL_INTERVAL_SECONDS", 0.0
        ), patch.object(
            daily, "DAILY_RETURN_HOME_SUCCESS_POLL_MAX_ATTEMPTS", 2
        ), patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
            with boundary.DevelopmentSession(
                owner="test-daily-claim-canary",
                invocation_id=f"test-{outcome}",
                session_directory=root / "session",
                max_inputs=2,
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
            self.assertEqual(result["input_count"], 2)
            self.assertEqual(len(runtime.taps), 1)
            self.assertEqual(len(runtime.backs), 1)
            self.assertEqual(runtime.taps[0]["target_identity"], "daily-claim:aggregate")
            self.assertEqual(runtime.taps[0]["target_roi"], (605, 455, 755, 535))
            self.assertEqual(
                [item["action_identity"] for item in runtime.reservations],
                ["daily-claim:aggregate", "daily-return-home"],
            )
            self.assertEqual(
                [item["action_class"] for item in runtime.reservations],
                ["reward_claim", "navigation"],
            )
            self.assertEqual(result["claim"]["points_before"], 0)
            self.assertEqual(result["claim"]["points_after"], 5)
            self.assertTrue(result["home"]["verified"])
            self.assertEqual(result["home"]["state"], daily.HOME_STATE)
            self.assertIn("return_home_final", result["frames"])
            self.assertTrue(session._ownership.lock.held is False)
            self.assertIn("immediate_before", result["frames"])
            self.assertIn("immediate_post", result["frames"])
            annotated = Path(result["claim"]["annotated_immediate_before"])
            self.assertTrue(annotated.is_file())
            self.assertGreater(annotated.stat().st_size, 0)

    def test_canary_uses_immediate_before_points_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            result, runtime, _recognizer, _session = self._run_canary(
                Path(directory),
                "points",
                recognizer=ImmediateBeforeBaselineClaimRecognizer("points"),
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["input_count"], 2)
        self.assertEqual(len(runtime.taps), 1)
        self.assertEqual(len(runtime.backs), 1)
        self.assertEqual(result["claim"]["points_before"], 0)
        self.assertEqual(result["claim"]["points_after"], 5)
        self.assertEqual(
            result["recognitions"]["source"]["visual_evidence"]["points"],
            10,
        )
        self.assertEqual(
            result["recognitions"]["immediate_before"]["visual_evidence"]["points"],
            0,
        )

    def test_canary_requires_final_template_home_and_never_retries_back(self):
        with tempfile.TemporaryDirectory() as directory:
            result, runtime, _recognizer, _session = self._run_canary(
                Path(directory),
                "points",
                recognizer=ScriptedClaimRecognizer("points", home=False),
            )

        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(result["input_count"], 2)
        self.assertEqual(len(runtime.taps), 1)
        self.assertEqual(len(runtime.backs), 1)
        self.assertNotIn("home", result)
        self.assertEqual(
            result["recognitions"]["return_home_immediate_post"]["state"],
            daily.QUEST_STATE,
        )

    def test_canary_selected_daily_source_failure_does_not_dispatch_back(self):
        with tempfile.TemporaryDirectory() as directory:
            result, runtime, _recognizer, _session = self._run_canary(
                Path(directory),
                "points",
                recognizer=ScriptedClaimRecognizer(
                    "points",
                    selected_daily=False,
                ),
            )

        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(result["input_count"], 1)
        self.assertEqual(len(runtime.taps), 1)
        self.assertEqual(runtime.backs, [])
        self.assertEqual(result["claim"]["points_after"], 5)

    def test_canary_with_multiple_eligible_controls_still_dispatches_once(self):
        with tempfile.TemporaryDirectory() as directory:
            result, runtime, _recognizer, _session = self._run_canary(
                Path(directory),
                "points",
                available_controls=2,
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["input_count"], 2)
        self.assertEqual(len(runtime.taps), 1)
        self.assertEqual(len(runtime.backs), 1)
        self.assertEqual(
            result["recognitions"]["source"]["visual_evidence"][
                "available_ordinary_claim_controls"
            ],
            2,
        )
        self.assertEqual(
            result["recognitions"]["immediate_post"]["visual_evidence"][
                "available_ordinary_claim_controls"
            ],
            0,
        )

    def test_canary_rejects_ocr_missing_row_with_unchanged_points(self):
        with tempfile.TemporaryDirectory() as directory:
            result, runtime, _recognizer, _session = self._run_canary(
                Path(directory), "row_disappeared"
            )

            self.assertEqual(result["status"], "evidence_required")
            self.assertEqual(len(runtime.taps), 1)
            post = result["recognitions"]["immediate_post"]["visual_evidence"]
            self.assertEqual(post["points"], 0)

    def test_canary_failure_is_evidence_required_without_retry(self):
        for outcome in (
            "unchanged",
            "row_missing_points",
            "control_changed",
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


class DailyReturnHomeTests(unittest.TestCase):
    def _run(
        self,
        root: Path,
        *,
        recognizer: ScriptedClaimRecognizer | None = None,
        runtime: ClaimCanaryRuntime | None = None,
    ):
        runtime = runtime or ClaimCanaryRuntime(root)
        recognizer = recognizer or ScriptedClaimRecognizer("points")
        with patch.object(
            daily,
            "DAILY_RETURN_HOME_SUCCESS_POLL_INTERVAL_SECONDS",
            0.0,
        ), patch.object(
            daily,
            "DAILY_RETURN_HOME_SUCCESS_POLL_MAX_ATTEMPTS",
            2,
        ), patch.object(
            boundary,
            "RUNTIME_INPUT_LOCK_PATH",
            root / "lock.sqlite3",
        ):
            with boundary.DevelopmentSession(
                owner="test-daily-return-home",
                invocation_id="test-daily-return-home",
                session_directory=root / "session",
                max_inputs=1,
            ) as session:
                result = daily.run_daily_row_claim_return_home(
                    runtime,
                    session,
                    recognizer=recognizer,
                )
        return result, runtime

    def test_selected_daily_return_home_dispatches_one_back_without_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, runtime = self._run(root)

        self.assertEqual(result["status"], "observed")
        self.assertEqual(result["input_count"], 1)
        self.assertEqual(runtime.taps, [])
        self.assertEqual(len(runtime.backs), 1)
        self.assertEqual(
            result["actions"][0]["label"],
            "daily-return-home",
        )
        self.assertEqual(
            result["recognitions"]["source"]["state"],
            daily.DAILY_SELECTED_STATE,
        )
        self.assertEqual(
            result["recognitions"]["return_home_immediate_before"]["state"],
            daily.DAILY_SELECTED_STATE,
        )
        self.assertEqual(result["home"]["state"], daily.HOME_STATE)
        self.assertIn("return_home_final", result["frames"])

    def test_return_home_rejects_non_selected_sources_without_input(self):
        for label, recognizer in (
            ("home", ScriptedClaimRecognizer("points", selected_daily=False)),
            ("quest", ScriptedClaimRecognizer("points", selected_daily=False)),
            ("unknown", ScriptedClaimRecognizer("points", selected_daily=False)),
            ("overlay", ScriptedClaimRecognizer("points", selected_daily=False)),
        ):
            with self.subTest(source=label), tempfile.TemporaryDirectory() as directory:
                result, runtime = self._run(
                    Path(directory),
                    recognizer=recognizer,
                )
                self.assertEqual(result["status"], "evidence_required")
                self.assertEqual(result["input_count"], 0)
                self.assertEqual(runtime.backs, [])

    def test_return_home_rejects_stale_immediate_before_without_input(self):
        class StaleImmediateBeforeRuntime(ClaimCanaryRuntime):
            def capture(self, label: str) -> CapturedNativeFrame:
                frame = super().capture(label)
                if label == "daily-return-home-immediate-before":
                    return _frame(
                        self.session,
                        "stale-immediate-before",
                        age=60.0,
                    )
                return frame

        with tempfile.TemporaryDirectory() as directory:
            result, runtime = self._run(
                Path(directory),
                runtime=StaleImmediateBeforeRuntime(Path(directory)),
            )

        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(result["input_count"], 0)
        self.assertEqual(runtime.backs, [])
        self.assertIn("return_home_immediate_before", result["frames"])

    def test_return_home_rejects_wrong_dimensions_without_input(self):
        class WrongDimensionsRuntime(ClaimCanaryRuntime):
            def capture(self, label: str) -> CapturedNativeFrame:
                super().capture(label)
                return _frame(
                    self.session,
                    "wrong-dimensions",
                    image=np.zeros((720, 400, 3), dtype=np.uint8),
                )

        with tempfile.TemporaryDirectory() as directory:
            result, runtime = self._run(
                Path(directory),
                runtime=WrongDimensionsRuntime(Path(directory)),
            )

        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(result["input_count"], 0)
        self.assertEqual(runtime.backs, [])

    def test_return_home_non_home_successor_is_evidence_required_without_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            result, runtime = self._run(
                Path(directory),
                recognizer=ScriptedClaimRecognizer("points", home=False),
            )

        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(result["input_count"], 1)
        self.assertEqual(len(runtime.backs), 1)
        self.assertNotIn("home", result)
        self.assertEqual(
            result["recognitions"]["return_home_immediate_post"]["state"],
            daily.QUEST_STATE,
        )

    def test_generic_home_without_template_proof_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            result, runtime = self._run(
                Path(directory),
                recognizer=ScriptedClaimRecognizer(
                    "points",
                    template_home=False,
                ),
            )

        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(result["input_count"], 1)
        self.assertEqual(len(runtime.backs), 1)
        self.assertEqual(
            result["recognitions"]["return_home_immediate_post"]["state"],
            daily.HOME_STATE,
        )
        self.assertFalse(
            result["recognitions"]["return_home_immediate_post"][
                "visual_evidence"
            ]["template_home"]["recognized"]
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
        limit = (
            0
            if mode == "prepare"
            else 2
            if mode == "canary"
            else 1
        )
        if max_inputs is not None:
            limit = max_inputs
        variant = (
            "aggregate-claim-dismiss-vip"
            if mode == "dismiss-vip-popup"
            else "aggregate-claim-return-home"
            if mode == "return-home"
            else f"aggregate-claim-{mode}"
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
            "selected-daily-aggregate-claim",
            "--variant",
            variant,
        ]

    def _receipt(self, root: Path, mode: str, *, command: list[str] | None = None):
        state = root / "receipts.sqlite3"
        controller = control.DelegatedRuntimeReceiptController(state)
        controller._candidate = lambda: ("head", "fingerprint")  # type: ignore[method-assign]
        command = command or self._command(root, mode)
        variant = (
            "aggregate-claim-dismiss-vip"
            if mode == "dismiss-vip-popup"
            else "aggregate-claim-return-home"
            if mode == "return-home"
            else f"aggregate-claim-{mode}"
        )
        if mode == "prepare":
            receipt_class = "reconnaissance"
            identities = ["daily-row-prepare-observation"]
            classes = ["observation"]
            consequence = "navigation_only"
            total = 0
            terminals = ["observed", "evidence_required"]
            result_identity = "daily-claim:prepare:aggregate"
            gates = {}
        elif mode == "canary":
            receipt_class = "canary"
            identities = ["daily-claim:aggregate", "daily-return-home"]
            classes = ["reward_claim", "navigation"]
            consequence = "ordinary_development"
            total = 2
            terminals = ["completed", "evidence_required"]
            result_identity = "daily-claim:canary:aggregate"
            gates = {
                "implementation_self_check_evidence": "self-check",
                "independent_read_only_tester_evidence": "tester",
                "parent_integration_acceptance": "accepted",
            }
        elif mode == "return-home":
            receipt_class = "reconnaissance"
            identities = ["daily-return-home"]
            classes = ["navigation"]
            consequence = "navigation_only"
            total = 1
            terminals = ["observed", "evidence_required"]
            result_identity = "daily-claim:return-home:verified"
            gates = {}
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
                "action_identity": identity,
                "action_class": action_class,
                "consequence_class": consequence,
                "resource_affecting": False,
                "combat_confirmation": False,
            }
            for identity, action_class in zip(identities, classes)
        ]
        receipt = controller.issue(
            task_id="daily-row-claim",
            flow_id="DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
            receipt_class=receipt_class,
            agent_identity="luna-agent",
            command_argv=command,
            scenario="selected-daily-aggregate-claim",
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
                max_inputs=(
                    0
                    if mode == "prepare"
                    else 2
                    if mode == "canary"
                    else 1
                ),
                delegated_receipt=state,
                agent_identity="luna-agent",
                task_id="daily-row-claim",
                flow_id="DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                scenario="selected-daily-aggregate-claim",
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
                ("variant", "aggregate-claim-canary"),
                ("max_total_inputs", 2),
                ("permitted_action_identities", ["daily-claim:aggregate"]),
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

    def test_parser_and_return_home_receipt_freeze_navigation_contract(self):
        command = self._command(Path("receipt.sqlite3"), "return-home")
        parsed = pnsctl.parser().parse_args(command)
        self.assertEqual(parsed.mode, "return-home")
        self.assertEqual(parsed.max_inputs, 1)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller, receipt = self._receipt(root, "return-home")
            self.assertEqual(receipt["receipt_class"], "reconnaissance")
            self.assertEqual(receipt["variant"], "aggregate-claim-return-home")
            self.assertEqual(receipt["max_total_inputs"], 1)
            self.assertEqual(
                receipt["permitted_action_identities"],
                ["daily-return-home"],
            )
            self.assertEqual(receipt["permitted_action_classes"], ["navigation"])
            self.assertEqual(receipt["consequence_class"], "navigation_only")
            self.assertEqual(
                receipt["evidence_result_binding"]["result_identity"],
                "daily-claim:return-home:verified",
            )
            pnsctl._validate_daily_row_claim_receipt(
                receipt,
                mode="return-home",
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
                    scenario="selected-daily-aggregate-claim",
                    variant="aggregate-claim-dismiss-vip",
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
            self.assertNotIn("objective_key", result["claim"])
            self.assertNotIn("current_progress", result["claim"])
            self.assertNotIn("required_progress", result["claim"])
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
                    scenario="selected-daily-aggregate-claim",
                    variant="aggregate-claim-prepare",
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
                    result_identity="daily-claim:prepare:aggregate",
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
                        scenario="selected-daily-aggregate-claim",
                        variant="aggregate-claim-prepare",
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
                    scenario="selected-daily-aggregate-claim",
                    variant="aggregate-claim-prepare",
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
                    scenario="selected-daily-aggregate-claim",
                    variant="wrong-variant",
                    command_argv=bad_command,
                )
            self.assertEqual(controller.inspect()["status"], "issued")

    def test_canary_receipt_and_pnsctl_route_bind_reward_claim_and_terminal_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, controller, _receipt = self._run_pnsctl(root, "canary")

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["input_count"], 2)
            self.assertEqual(len(result["actions"]), 2)
            self.assertEqual(result["actions"][0]["requested_action"], "reward_claim")
            self.assertEqual(result["actions"][1]["requested_action"], "navigation")
            self.assertEqual(
                [row["label"] for row in result["actions"]],
                ["daily-claim:aggregate", "daily-return-home"],
            )
            self.assertEqual(result["claim"]["points_after"], 5)
            self.assertIn("immediate_before", result["frames"])
            self.assertIn("immediate_post", result["frames"])
            self.assertTrue(result["home"]["verified"])
            self.assertTrue(result["claim"]["annotated_immediate_before"])
            self.assertEqual(controller.inspect()["status"], "consumed")

    def test_artifacts_reject_generic_home_without_template_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, _controller, _receipt = self._run_pnsctl(root, "canary")
            final = result["recognitions"]["return_home_final"]
            visual = dict(final["visual_evidence"])
            visual["template_home"] = {"recognized": False}
            final["visual_evidence"] = visual
            with self.assertRaisesRegex(
                pnsctl.OperatorError,
                "final Home is not recognized",
            ):
                pnsctl._validate_daily_row_claim_artifacts(
                    Path(result["session_directory"]),
                    result,
                    mode="canary",
                )

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
                    scenario="selected-daily-aggregate-claim",
                    variant="aggregate-claim-prepare",
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


class RetiredDailyReadyRowArtifactFixtures:
    """Retained scan artifacts must prove the exact native swipe dispatches."""

    _REGION = (100, 520, 700, 1120)
    _START = (400, 1000)
    _END = (400, 560)
    _IDENTITIES = (
        "daily-row-scan-swipe-1",
        "daily-row-scan-swipe-2",
        "daily-row-scan-swipe-3",
    )

    def _artifact(self, root: Path, *, count: int = 2, status: str = "observed"):
        session = root / "session"
        session.mkdir(parents=True)
        frames: dict[str, dict[str, object]] = {}
        captured_frames: dict[str, CapturedNativeFrame] = {}

        def add_frame(name: str) -> dict[str, object]:
            captured = _frame(session, name)
            reference = {
                "path": name + ".png",
                "sha256": captured.sha256,
                "captured_monotonic": captured.captured_monotonic,
            }
            frames[name] = reference
            captured_frames[name] = captured
            return reference

        add_frame("source")
        class SwipeTransport:
            def dispatch_swipe(
                self,
                _start: tuple[int, int],
                _end: tuple[int, int],
            ) -> None:
                return None

        native_runtime = LocalBlueStacksRuntime(
            SwipeTransport(),
            session / "runtime",
            execute=True,
        )
        events_path = native_runtime.events
        events_path.write_text(
            json.dumps({"type": "capture", "label": "daily-row-scan-source"}) + "\n",
            encoding="utf-8",
        )
        swipes: list[dict[str, object]] = []
        actions: list[dict[str, object]] = []
        before_refs: list[dict[str, object]] = []
        for ordinal, identity in enumerate(self._IDENTITIES[:count], start=1):
            before_key = f"swipe_{ordinal:02d}_immediate_before"
            before = add_frame(before_key)
            before_refs.append(before)
            native_runtime.swipe(
                captured_frames[before_key],
                start=self._START,
                end=self._END,
                action_key=identity,
                target_identity=identity,
            )

        dispatches: list[dict[str, object]] = []
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("type") == "dispatch":
                dispatches.append(event)
        self.assertEqual(len(dispatches), count)
        for ordinal, (before, event) in enumerate(
            zip(before_refs, dispatches),
            start=1,
        ):
            identity = str(event["target_identity"])
            swipes.append(
                {
                    "ordinal": ordinal,
                    "action_identity": identity,
                    "action_class": event["action_class"],
                    "consequence_class": event["consequence_class"],
                    "source_frame_sha256": event["source_sha256"],
                    "start": event["start"],
                    "end": event["end"],
                    "safe_list_region": self._REGION,
                    "status": "completed",
                    "before": before,
                    "after": None,
                }
            )
            actions.append(
                {
                    "ordinal": ordinal,
                    "action_class": event["action_class"],
                    "requested_action": "navigation",
                    "label": identity,
                    "status": "completed",
                    "before_sha256": before["sha256"],
                    "after_sha256": "b" * 64,
                    "recovery_used": False,
                }
            )

        (session / "final.png").write_bytes(b"annotated")
        payload: dict[str, object] = {
            "status": status,
            "mode": "scan-ready-row",
            "input_count": count,
            "resource_affecting_inputs": 0,
            "combat_confirmations": 0,
            "claim_authority": False,
            "scan_budget": 3,
            "swipe_identities": list(self._IDENTITIES),
            "safe_list_region": self._REGION,
            "swipe_start": self._START,
            "swipe_end": self._END,
            "frames": frames,
            "swipes": swipes,
            "actions": actions,
            "runtime_events_path": "runtime/events.jsonl",
            "final_annotation": "final.png",
            "dispatch": count > 0,
        }
        if status == "observed":
            payload["ready_row"] = {
                "status": "ready",
                "claim_authority": False,
                "objective_key": "upgrade_building",
                "objective_name": "Upgrade building",
                "row_bounds": (70, 432, 780, 542),
                "claim_roi": (605, 455, 755, 535),
            }
        return session, payload, events_path

    def test_positive_multi_swipe_artifact_matches_runtime_events(self):
        with tempfile.TemporaryDirectory() as directory:
            session, payload, _events_path = self._artifact(Path(directory))
            pnsctl._validate_daily_row_claim_artifacts(
                session,
                payload,
                mode="scan-ready-row",
            )

    def test_scan_rejects_out_of_region_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            session, payload, _events_path = self._artifact(Path(directory))
            payload["swipes"][0]["end"] = (700, 1120)
            with self.assertRaisesRegex(pnsctl.OperatorError, "outside"):
                pnsctl._validate_daily_row_claim_artifacts(
                    session,
                    payload,
                    mode="scan-ready-row",
                )

    def test_scan_rejects_source_hash_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            session, payload, _events_path = self._artifact(Path(directory))
            payload["swipes"][0]["source_frame_sha256"] = "0" * 64
            with self.assertRaisesRegex(pnsctl.OperatorError, "source hash"):
                pnsctl._validate_daily_row_claim_artifacts(
                    session,
                    payload,
                    mode="scan-ready-row",
                )

    def test_scan_rejects_non_navigation_consequence(self):
        with tempfile.TemporaryDirectory() as directory:
            session, payload, _events_path = self._artifact(Path(directory))
            payload["swipes"][0]["consequence_class"] = "resource_affecting"
            with self.assertRaisesRegex(pnsctl.OperatorError, "class"):
                pnsctl._validate_daily_row_claim_artifacts(
                    session,
                    payload,
                    mode="scan-ready-row",
                )

    def test_scan_rejects_missing_and_extra_runtime_dispatch(self):
        for mutation, expected in (
            ("missing", "count"),
            ("extra", "count"),
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                session, payload, events_path = self._artifact(Path(directory))
                rows = [
                    json.loads(line)
                    for line in events_path.read_text(encoding="utf-8").splitlines()
                ]
                dispatch_indices = [
                    index for index, row in enumerate(rows) if row["type"] == "dispatch"
                ]
                if mutation == "missing":
                    rows.pop(dispatch_indices[-1])
                else:
                    rows.append(dict(rows[dispatch_indices[0]]))
                events_path.write_text(
                    "".join(json.dumps(row) + "\n" for row in rows),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(pnsctl.OperatorError, expected):
                    pnsctl._validate_daily_row_claim_artifacts(
                        session,
                        payload,
                        mode="scan-ready-row",
                    )

    def test_scan_rejects_reordered_runtime_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            session, payload, events_path = self._artifact(Path(directory))
            rows = [
                json.loads(line)
                for line in events_path.read_text(encoding="utf-8").splitlines()
            ]
            dispatches = [row for row in rows if row["type"] == "dispatch"]
            rows = [row for row in rows if row["type"] != "dispatch"]
            rows.extend(reversed(dispatches))
            events_path.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(pnsctl.OperatorError, "identity"):
                pnsctl._validate_daily_row_claim_artifacts(
                    session,
                    payload,
                    mode="scan-ready-row",
                )

    def test_scan_rejects_non_swipe_runtime_gesture(self):
        with tempfile.TemporaryDirectory() as directory:
            session, payload, events_path = self._artifact(Path(directory))
            rows = [
                json.loads(line)
                for line in events_path.read_text(encoding="utf-8").splitlines()
            ]
            next(row for row in rows if row["type"] == "dispatch")["gesture"] = "tap"
            events_path.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(pnsctl.OperatorError, "identity or class"):
                pnsctl._validate_daily_row_claim_artifacts(
                    session,
                    payload,
                    mode="scan-ready-row",
                )

    def test_scan_rejects_missing_required_runtime_dispatch_fields(self):
        for field in ("gesture", "action_class", "consequence_class"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                session, payload, events_path = self._artifact(Path(directory))
                rows = [
                    json.loads(line)
                    for line in events_path.read_text(encoding="utf-8").splitlines()
                ]
                dispatch = next(row for row in rows if row["type"] == "dispatch")
                dispatch.pop(field)
                events_path.write_text(
                    "".join(json.dumps(row) + "\n" for row in rows),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(pnsctl.OperatorError, "identity or class"):
                    pnsctl._validate_daily_row_claim_artifacts(
                        session,
                        payload,
                        mode="scan-ready-row",
                    )

    def test_evidence_terminal_validates_available_scan_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            session, payload, events_path = self._artifact(
                Path(directory),
                status="evidence_required",
            )
            payload.pop("final_annotation")
            pnsctl._validate_daily_row_claim_artifacts(
                session,
                payload,
                mode="scan-ready-row",
            )
            rows = [
                json.loads(line)
                for line in events_path.read_text(encoding="utf-8").splitlines()
            ]
            events_path.write_text(
                "".join(
                    json.dumps(row) + "\n"
                    for row in rows
                    if row["type"] != "dispatch"
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(pnsctl.OperatorError, "count"):
                pnsctl._validate_daily_row_claim_artifacts(
                    session,
                    payload,
                    mode="scan-ready-row",
                )


class RetiredDailyReadyRowScanFixtures:
    """Independent row-scan fixtures exercise observation without Claim authority."""

    class Runtime:
        execute = True
        frame_max_age_seconds = 30.0

        def __init__(self, root: Path, *, unchanged_after_swipe: bool = False) -> None:
            self.session = root
            self.session.mkdir(parents=True, exist_ok=True)
            self.labels: list[str] = []
            self.swipes: list[dict[str, object]] = []
            self._last_capture: CapturedNativeFrame | None = None
            self.unchanged_after_swipe = unchanged_after_swipe
            self._ordinal = 0

        def capture(self, label: str) -> CapturedNativeFrame:
            self.labels.append(label)
            if (
                self.unchanged_after_swipe
                and label.endswith("-immediate-post")
                and self._last_capture is not None
            ):
                return self._last_capture
            self._ordinal += 1
            image = np.zeros((1280, 800, 3), dtype=np.uint8)
            image[0, 0, 0] = self._ordinal % 255
            captured = _frame(
                self.session,
                label.replace(":", "_"),
                image=image,
            )
            if label.endswith("-immediate-before"):
                self._last_capture = captured
            return captured

        def measure_device_state(self) -> str:
            return "device"

        def measure_foreground_package(self) -> str:
            return daily.EXPECTED_PACKAGE

        def swipe(
            self,
            source: CapturedNativeFrame,
            *,
            start: tuple[int, int],
            end: tuple[int, int],
            action_key: str,
            target_identity: str,
        ) -> None:
            self.swipes.append(
                {
                    "source": source.sha256,
                    "start": start,
                    "end": end,
                    "action_key": action_key,
                    "target_identity": target_identity,
                }
            )

    class Recognizer:
        def __init__(self, ready_on_call: int | None = None) -> None:
            self.calls = 0
            self.ready_on_call = ready_on_call

        def recognize_daily_ready_rows(
            self,
            _frame: np.ndarray,
            *,
            game_day_id: str | None = None,
            observed_utc: str | None = None,
        ) -> daily.FrameRecognition:
            self.calls += 1
            ready = (
                self.ready_on_call is not None
                and self.calls >= self.ready_on_call
            )
            row = {
                "objective_key": "upgrade_building",
                "objective_name": "Upgrade building",
                "observed_name": "upgrade building 1 1",
                "current_progress": 1,
                "required_progress": 1,
                "progress_text": "upgrade building 1 1",
                "reward": {"text": "reward pts 5", "points": 5},
                "row_bounds": (70, 432, 780, 542),
                "claim_roi": (605, 455, 755, 535),
                "status": "ready",
                "claim_authority": False,
            }
            visual = {
                "selected_daily": True,
                "full_frame_overlay": {"recognized": False, "markers": ()},
                "generic_modal_overlay": {"recognized": False},
                "reset_timer": "23:07:46",
                "reset_timer_seconds": 83266,
                "reset_observed_utc": "2026-08-17T00:00:00Z",
                "reset_deadline_utc": "2026-08-17T23:07:46Z",
                "reset_deadline_identity": "reset-deadline:2026-08-17T23:07:46Z",
                "game_day_id": game_day_id or "reset-deadline:2026-08-17T23:07:46Z",
                "inventory_rows": [row],
                "ready_row": row if ready else None,
            }
            return daily.FrameRecognition(
                daily.DAILY_SELECTED_STATE,
                True,
                daily.DAILY_ROW_SCAN_OBSERVATION_IDENTITY if ready else None,
                row["claim_roi"] if ready else None,
                "selected Daily",
                visual,
                None,
            )

    def _run_scan(
        self,
        root: Path,
        *,
        ready_on_call: int | None,
        unchanged_after_swipe: bool = False,
    ):
        with patch.object(daily, "DAILY_ROW_SCAN_SETTLE_INTERVAL_SECONDS", 0.0), patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"
        ):
            with boundary.DevelopmentSession(
                owner="test-daily-ready-row-scan",
                invocation_id="test-daily-ready-row-scan",
                session_directory=root / "session",
                max_inputs=3,
            ) as session:
                runtime = self.Runtime(
                    session.session_directory / "runtime",
                    unchanged_after_swipe=unchanged_after_swipe,
                )
                result = daily.run_daily_row_claim_ready_row_scan(
                    runtime,
                    session,
                    recognizer=self.Recognizer(ready_on_call),
                    game_day_id="reset-deadline:2026-08-17T23:07:46Z",
                    wall_utc=lambda: __import__("datetime").datetime.fromisoformat(
                        "2026-08-17T00:00:00+00:00"
                    ),
                )
        return result, runtime

    def test_visible_ready_row_uses_zero_inputs_and_retains_non_authorizing_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            result, runtime = self._run_scan(
                Path(directory),
                ready_on_call=1,
            )
        self.assertEqual(result["status"], "observed")
        self.assertEqual(result["input_count"], 0)
        self.assertEqual(runtime.swipes, [])
        self.assertEqual(result["ready_row"]["objective_key"], "upgrade_building")
        self.assertFalse(result["claim_authority"])
        self.assertFalse(result["ready_row"]["claim_authority"])
        self.assertTrue(result["final_annotation"])

    def test_one_swipe_finds_ready_row_with_safe_navigation_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            result, runtime = self._run_scan(
                Path(directory),
                ready_on_call=4,
            )
        self.assertEqual(result["status"], "observed")
        self.assertEqual(result["input_count"], 1)
        self.assertEqual(len(runtime.swipes), 1)
        self.assertEqual(runtime.swipes[0]["action_key"], "daily-row-scan-swipe-1")
        self.assertEqual(runtime.swipes[0]["target_identity"], "daily-row-scan-swipe-1")
        region = tuple(result["swipes"][0]["safe_list_region"])
        start = tuple(runtime.swipes[0]["start"])
        end = tuple(runtime.swipes[0]["end"])
        self.assertEqual(region, tuple(daily.DAILY_ROW_SCAN_LIST_REGION))
        header_tabs = (0, 0, 800, 340)
        row_button_lane = (region[2] - 100, region[1], region[2], region[3])
        for point in (start, end):
            self.assertGreater(point[0], region[0])
            self.assertLess(point[0], region[2])
            self.assertGreater(point[1], region[1])
            self.assertLess(point[1], region[3])
            self.assertFalse(
                header_tabs[0] <= point[0] < header_tabs[2]
                and header_tabs[1] <= point[1] < header_tabs[3]
            )
            self.assertFalse(
                row_button_lane[0] <= point[0] < row_button_lane[2]
                and row_button_lane[1] <= point[1] < row_button_lane[3]
            )

    def test_three_swipes_without_ready_row_end_evidence_required(self):
        with tempfile.TemporaryDirectory() as directory:
            result, runtime = self._run_scan(
                Path(directory),
                ready_on_call=None,
            )
        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(result["input_count"], 3)
        self.assertEqual(
            [item["action_key"] for item in runtime.swipes],
            [
                "daily-row-scan-swipe-1",
                "daily-row-scan-swipe-2",
                "daily-row-scan-swipe-3",
            ],
        )

    def test_unchanged_swipe_successor_stops_without_repeated_swipe(self):
        with tempfile.TemporaryDirectory() as directory:
            result, runtime = self._run_scan(
                Path(directory),
                ready_on_call=None,
                unchanged_after_swipe=True,
            )
        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(result["input_count"], 1)
        self.assertEqual(len(runtime.swipes), 1)


if __name__ == "__main__":
    unittest.main()
