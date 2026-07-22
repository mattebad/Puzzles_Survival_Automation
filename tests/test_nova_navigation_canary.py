"""Offline controller and retained-evidence tests for the no-Praise Nova canary."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.home_atlas_bluestacks import HomeDriverDisposition, HomeDriverStep
from scripts.nova_praise_bluestacks import (
    BlueStacksNovaPraiseAdapter,
    NovaAdapterConfig,
    NovaNavigationCanaryRoute,
)
from tasks.gameplay_flow_replay import ReplayNativeRuntime, load_retained_native_frame
from tasks.home_atlas import (
    AmbiguityState,
    BuildingBinding,
    LocalizationResult,
    ZoomIdentity,
)
from tasks.home_context import HomeReadyObservation
from tasks.home_atlas_vision import frame_digest
from tasks.nova_praise import (
    NOVA_INTERACTION_TARGET,
    NOVA_PRAISE_TARGET,
    NOVA_SCREEN,
    NovaPraiseObservation,
)
from tasks.nova_praise_vision import (
    NOVA_PRAISE_ROI,
    NOVA_RADIAL_TEMPLATE_PATH,
    NOVA_TEMPLATE_MIN_MARGIN,
    NOVA_TEMPLATE_MIN_SCORE,
    NOVA_TEMPLATE_SCALES,
    NovaFrameRecognition,
    ResearchLabTapProvenance,
    evaluate_research_lab_radial_evidence,
    recognize_nova_frame,
)
import tasks.nova_praise_vision as nova_praise_vision
from tasks.runtime_identity import RuntimeIdentityAssurance, VerifiedRuntimeIdentity


ROOT = Path(__file__).resolve().parents[1]
ATLAS_PATH = ROOT / "tasks/assets/home_atlas/bluestacks/800x1280/atlas.json"
FIXTURE_ROOT = ROOT / "tests/fixtures/nova_praise_preflight"
ASSET_MANIFEST = ROOT / "tasks/assets/nova_praise/800x1280/manifest.json"


def _identity() -> VerifiedRuntimeIdentity:
    return VerifiedRuntimeIdentity(
        "bluestacks-dev-primary",
        "acct-1",
        "server-1",
        "reset-1",
        RuntimeIdentityAssurance.SUPERVISED_NAVIGATION_BINDING,
        ("operator-bound-current-frame",),
    )


def _localization(digest: str) -> LocalizationResult:
    return LocalizationResult(
        True,
        "BlueStacks 5 / Android",
        "pns-bluestacks-5-p64-800x1280-v1",
        ZoomIdentity.FULLY_ZOOMED_OUT,
        ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
        ((0, 0), (800, 0), (800, 1280), (0, 1280)),
        0.95,
        ("fixture",),
        0.2,
        AmbiguityState.NONE,
        "interior",
        digest,
        "now",
    )


def _radial_recognition(digest: str) -> NovaFrameRecognition:
    observation = NovaPraiseObservation(
        screen_state="RESEARCH_LAB_MENU",
        research_lab_identity=True,
        nova_control_visible=True,
        selected_nova=False,
        praise_enabled=False,
        praise_target_identity="",
        praise_target_roi=NOVA_PRAISE_ROI,
        attempts_remaining=None,
        frame_sha256=digest,
        captured_monotonic=1.0,
        recognized=True,
    )
    return NovaFrameRecognition(
        observation,
        digest,
        ((NOVA_INTERACTION_TARGET, (226, 640, 270, 684)),),
        {
            "research_lab_radial": {
                "recognized": True,
                "geometry_anchors": ("details", "nova", "research", "upgrade"),
                "hough_only_anchors": ("details", "nova", "research", "upgrade"),
                "bind_method": "hough_radial",
            }
        },
    )


def _home_recognition(digest: str) -> NovaFrameRecognition:
    observation = NovaPraiseObservation(
        screen_state="HOME_BASE",
        research_lab_identity=True,
        nova_control_visible=False,
        selected_nova=False,
        praise_enabled=False,
        praise_target_identity="",
        praise_target_roi=NOVA_PRAISE_ROI,
        attempts_remaining=None,
        frame_sha256=digest,
        captured_monotonic=1.0,
        recognized=True,
    )
    return NovaFrameRecognition(observation, digest, (), {})


def _nova_recognition(digest: str) -> NovaFrameRecognition:
    observation = NovaPraiseObservation(
        screen_state=NOVA_SCREEN,
        research_lab_identity=True,
        nova_control_visible=False,
        selected_nova=True,
        praise_enabled=True,
        praise_target_identity=NOVA_PRAISE_TARGET,
        praise_target_roi=NOVA_PRAISE_ROI,
        attempts_remaining=6,
        frame_sha256=digest,
        captured_monotonic=1.0,
        recognized=True,
    )
    return NovaFrameRecognition(
        observation,
        digest,
        ((NOVA_PRAISE_TARGET, NOVA_PRAISE_ROI),),
        {},
    )


def _fixture(name: str) -> dict:
    manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    return next(item for item in manifest["fixtures"] if item["id"] == name)


def _load_fixture_frame(fixture: dict) -> np.ndarray:
    path = FIXTURE_ROOT / fixture["path"]
    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    assert frame is not None
    assert hashlib.sha256(path.read_bytes()).hexdigest() == fixture["file_sha256"]
    return frame


def _lab_provenance(fixture: dict, dispatched: float = 10.0) -> ResearchLabTapProvenance:
    action = fixture["preceding_action"]
    return ResearchLabTapProvenance(
        action["action_key"],
        action["target_identity"],
        action["source_sha256"],
        tuple(action["target_roi"]),
        dispatched,
    )


def _enable_offline_runtime_probes(runtime) -> None:
    """Attach live-probe methods for offline Fake/Replay runtimes used in tests."""

    if not hasattr(runtime, "measure_device_state"):
        runtime.measure_device_state = lambda: "device"  # type: ignore[attr-defined]
    if not hasattr(runtime, "measure_foreground_package"):
        runtime.measure_foreground_package = lambda: "com.global.ztmslg"  # type: ignore[attr-defined]


class FakeRuntime:
    execute = True
    in_flight_action = None
    session = Path("nova-navigation-canary-test")

    def __init__(self) -> None:
        self.ordinal = 0
        self.inputs: list[tuple[str, dict[str, object]]] = []
        self.labels: list[str] = []
        self._device_state = "device"
        self._foreground_package = "com.global.ztmslg"

    def measure_device_state(self) -> str:
        return self._device_state

    def measure_foreground_package(self) -> str:
        return self._foreground_package

    def capture(self, label: str) -> CapturedNativeFrame:
        self.ordinal += 1
        self.labels.append(label)
        frame = np.zeros((1280, 800, 3), np.uint8)
        frame[0, 0] = (self.ordinal % 256, 1, 1)
        payload = f"capture-{self.ordinal}".encode()
        return CapturedNativeFrame(
            frame,
            payload,
            hashlib.sha256(payload).hexdigest(),
            time.monotonic(),
            Path(f"{label}.png"),
        )

    def tap(self, source, **kwargs) -> None:
        self.inputs.append(("tap", kwargs))

    def swipe(self, source, **kwargs) -> None:
        self.inputs.append(("swipe", kwargs))

    def back(self, source, **kwargs) -> None:
        self.inputs.append(("back", kwargs))


class FakeHomeDriver:
    def __init__(self) -> None:
        frame = np.zeros((1280, 800, 3), np.uint8)
        digest = frame_digest(frame)
        localization = _localization(digest)
        binding = BuildingBinding(
            "home.building.research_lab",
            (198, 407, 363, 632),
            digest,
            0.95,
            ("current-frame OCR: Research Lab",),
        )
        self.step = HomeDriverStep(
            HomeDriverDisposition.COMPLETE,
            "current_frame_semantic_building_bound",
            digest,
            localization,
            binding,
        )
        self.localizer = type("Localizer", (), {"localize": lambda _self, _frame: localization})()
        self.ready = HomeReadyObservation(True, True, _identity(), False, False)

    def observe(self, _frame):
        return self.step


class RecognitionQueue:
    def __init__(self, *items: NovaFrameRecognition) -> None:
        self.items = list(items)

    def __call__(self, *_args, **_kwargs):
        if not self.items:
            raise AssertionError("unexpected recognition")
        return self.items.pop(0)


class NovaNavigationCanaryTests(unittest.TestCase):
    def test_controller_orders_navigation_and_never_plans_praise(self) -> None:
        runtime = FakeRuntime()
        recognizer = RecognitionQueue(
            _home_recognition("0" * 64),
            _radial_recognition("a" * 64),
            _radial_recognition("b" * 64),
            _nova_recognition("c" * 64),
            _nova_recognition("d" * 64),
            _home_recognition("e" * 64),
        )
        route = NovaNavigationCanaryRoute(
            runtime,
            _identity(),
            atlas_path=ATLAS_PATH,
            home_driver=FakeHomeDriver(),
            recognizer=recognizer,
            settle_seconds=0,
        )
        with patch.object(route, "_home_localized", return_value=True):
            result = route.run()
        self.assertEqual(result.status, "completed")
        self.assertTrue(result.terminal_home_verified)
        self.assertEqual(result.praise_taps, 0)
        self.assertEqual([kind for kind, _ in runtime.inputs], ["tap", "tap", "back"])
        self.assertTrue(all(not data.get("consequential", False) for _, data in runtime.inputs))
        self.assertNotIn(NOVA_PRAISE_TARGET, [data.get("target_identity") for _, data in runtime.inputs])
        for suffix in ("immediate-post", "settled"):
            self.assertTrue(any(suffix in label for label in runtime.labels))

    def test_unbound_radial_blocks_before_nova_tap(self) -> None:
        runtime = FakeRuntime()
        unbound = replace(_radial_recognition("a" * 64), targets=())
        route = NovaNavigationCanaryRoute(
            runtime,
            _identity(),
            atlas_path=ATLAS_PATH,
            home_driver=FakeHomeDriver(),
            recognizer=RecognitionQueue(_home_recognition("0" * 64), unbound),
            settle_seconds=0,
        )
        with patch.object(route, "_home_localized", return_value=True):
            result = route.run()
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.reason, "research_lab_radial_not_bound")
        self.assertEqual([kind for kind, _ in runtime.inputs], ["tap"])
        self.assertEqual(result.praise_taps, 0)

    def test_known_nova_start_returns_home_before_full_canary_route(self) -> None:
        runtime = FakeRuntime()
        recognizer = RecognitionQueue(
            _nova_recognition("0" * 64),
            _nova_recognition("1" * 64),
            _home_recognition("2" * 64),
            _radial_recognition("3" * 64),
            _radial_recognition("4" * 64),
            _nova_recognition("5" * 64),
            _nova_recognition("6" * 64),
            _home_recognition("7" * 64),
        )
        route = NovaNavigationCanaryRoute(
            runtime,
            _identity(),
            atlas_path=ATLAS_PATH,
            home_driver=FakeHomeDriver(),
            recognizer=recognizer,
            settle_seconds=0,
        )
        with patch.object(route, "_home_localized", return_value=True):
            result = route.run()
        self.assertEqual(result.status, "completed")
        self.assertEqual(
            [kind for kind, _ in runtime.inputs],
            ["back", "tap", "tap", "back"],
        )
        self.assertEqual(result.praise_taps, 0)

    def test_bound_radial_start_continues_with_initial_provenance(self) -> None:
        runtime = FakeRuntime()
        provenance = ResearchLabTapProvenance(
            "nova-canary:open-research-lab:fixture",
            "home.building.research_lab",
            "2" * 64,
            (198, 407, 363, 632),
            10.0,
        )
        recognizer = RecognitionQueue(
            _radial_recognition("0" * 64),
            _radial_recognition("1" * 64),
            _nova_recognition("2" * 64),
            _nova_recognition("3" * 64),
            _home_recognition("4" * 64),
        )
        route = NovaNavigationCanaryRoute(
            runtime,
            _identity(),
            atlas_path=ATLAS_PATH,
            home_driver=FakeHomeDriver(),
            recognizer=recognizer,
            settle_seconds=0,
            initial_research_lab_tap_provenance=provenance,
        )
        with patch.object(route, "_home_localized", return_value=True):
            result = route.run()
        self.assertEqual(result.status, "completed")
        self.assertEqual([kind for kind, _ in runtime.inputs], ["tap", "back"])
        self.assertEqual(runtime.inputs[0][1]["target_identity"], NOVA_INTERACTION_TARGET)
        self.assertNotIn(
            "home.building.research_lab",
            [data.get("target_identity") for _, data in runtime.inputs],
        )
        self.assertEqual(result.praise_taps, 0)

    def test_bound_radial_start_without_provenance_continues_when_recognized(self) -> None:
        runtime = FakeRuntime()
        recognizer = RecognitionQueue(
            _radial_recognition("0" * 64),
            _radial_recognition("1" * 64),
            _nova_recognition("2" * 64),
            _nova_recognition("3" * 64),
            _home_recognition("4" * 64),
        )
        route = NovaNavigationCanaryRoute(
            runtime,
            _identity(),
            atlas_path=ATLAS_PATH,
            home_driver=FakeHomeDriver(),
            recognizer=recognizer,
            settle_seconds=0,
        )
        with patch.object(route, "_home_localized", return_value=True):
            result = route.run()
        self.assertEqual(result.status, "completed")
        self.assertEqual([kind for kind, _ in runtime.inputs], ["tap", "back"])
        self.assertEqual(runtime.inputs[0][1]["target_identity"], NOVA_INTERACTION_TARGET)
        self.assertEqual(result.praise_taps, 0)
        self.assertNotIn(
            NOVA_PRAISE_TARGET,
            [data.get("target_identity") for _, data in runtime.inputs],
        )

    def test_false_measured_home_context_blocks_before_nova_input(self) -> None:
        runtime = FakeRuntime()
        provenance = ResearchLabTapProvenance(
            "nova-canary:open-research-lab:fixture",
            "home.building.research_lab",
            "2" * 64,
            (198, 407, 363, 632),
            10.0,
        )
        route = NovaNavigationCanaryRoute(
            runtime,
            _identity(),
            atlas_path=ATLAS_PATH,
            home_driver=FakeHomeDriver(),
            recognizer=RecognitionQueue(_radial_recognition("0" * 64)),
            settle_seconds=0,
            initial_research_lab_tap_provenance=provenance,
        )
        with patch.object(route, "_home_localized", return_value=False):
            with patch.object(route, "_home_context_measured", return_value=False):
                result = route.run()
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.reason, "initial_radial_home_context_not_established")
        self.assertEqual(runtime.inputs, [])

    def test_retained_radial_measured_home_context_succeeds(self) -> None:
        fixture = _fixture("blocked-canary-radial-48a116d3")
        path = FIXTURE_ROOT / fixture["path"]
        captured = load_retained_native_frame(
            path,
            captured_monotonic=11.0,
            expected_sha256=fixture["file_sha256"],
        )
        route = NovaNavigationCanaryRoute(
            FakeRuntime(),
            _identity(),
            atlas_path=ATLAS_PATH,
            settle_seconds=0,
            initial_research_lab_tap_provenance=_lab_provenance(fixture),
        )
        measured = route._home_localized(captured)
        self.assertTrue(measured)
        recognized = recognize_nova_frame(
            captured.frame,
            captured_monotonic=captured.captured_monotonic,
            research_lab_tap_provenance=_lab_provenance(fixture),
            home_context_visible=measured,
        )
        self.assertTrue(recognized.observation.recognized)
        self.assertEqual(recognized.target(NOVA_INTERACTION_TARGET), (226, 640, 270, 684))

    def test_unbound_radial_start_blocks_without_generic_back(self) -> None:
        runtime = FakeRuntime()
        unbound = replace(_radial_recognition("0" * 64), targets=())
        provenance = ResearchLabTapProvenance(
            "nova-canary:open-research-lab:fixture",
            "home.building.research_lab",
            "2" * 64,
            (198, 407, 363, 632),
            10.0,
        )
        route = NovaNavigationCanaryRoute(
            runtime,
            _identity(),
            atlas_path=ATLAS_PATH,
            home_driver=FakeHomeDriver(),
            recognizer=RecognitionQueue(unbound),
            settle_seconds=0,
            initial_research_lab_tap_provenance=provenance,
        )
        result = route.run()
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.reason, "initial_research_lab_radial_not_bound")
        self.assertEqual(runtime.inputs, [])

    def test_compatibility_adapter_cannot_dispatch_praise(self) -> None:
        calls = []
        adapter = BlueStacksNovaPraiseAdapter(
            NovaAdapterConfig(dry_run=False),
            transport=lambda point: calls.append(point),
        )
        adapter.controller.now = 1.0
        with self.assertRaisesRegex(RuntimeError, "centralized action boundary"):
            adapter.command(_nova_recognition("a" * 64))
        self.assertEqual(calls, [])

    def test_retained_radial_strong_initial_composite_without_provenance(self) -> None:
        fixture = _fixture("blocked-canary-radial-48a116d3")
        frame = _load_fixture_frame(fixture)
        recognized = recognize_nova_frame(
            frame,
            captured_monotonic=11.0,
            home_context_visible=True,
        )
        self.assertTrue(recognized.observation.recognized)
        self.assertEqual(recognized.observation.screen_state, "RESEARCH_LAB_MENU")
        self.assertEqual(recognized.target(NOVA_INTERACTION_TARGET), (226, 640, 270, 684))
        radial = recognized.diagnostics["research_lab_radial"]
        self.assertEqual(radial["bind_method"], "template_nova_plus_research_hough")
        self.assertTrue(radial["initial_unprovenanced_composite"])
        self.assertGreaterEqual(radial["template_score"], NOVA_TEMPLATE_MIN_SCORE)
        self.assertGreaterEqual(radial["template_margin"], NOVA_TEMPLATE_MIN_MARGIN)

    def test_retained_radial_provenance_path_still_binds(self) -> None:
        fixture = _fixture("research-lab-radial-07f3d826")
        frame = _load_fixture_frame(fixture)
        fresh = recognize_nova_frame(
            frame,
            captured_monotonic=11.0,
            research_lab_tap_provenance=_lab_provenance(fixture),
            home_context_visible=True,
        )
        self.assertEqual(fresh.observation.screen_state, "RESEARCH_LAB_MENU")
        self.assertTrue(fresh.observation.recognized)
        self.assertEqual(fresh.target(NOVA_INTERACTION_TARGET), (232, 652, 276, 696))

    def test_blocked_canary_frame_hough_rejects_and_template_binds(self) -> None:
        fixture = _fixture("blocked-canary-radial-48a116d3")
        frame = _load_fixture_frame(fixture)
        provenance = _lab_provenance(fixture)
        recognized = recognize_nova_frame(
            frame,
            captured_monotonic=11.0,
            research_lab_tap_provenance=provenance,
            home_context_visible=True,
        )
        radial = recognized.diagnostics["research_lab_radial"]
        self.assertEqual(tuple(radial["hough_only_anchors"]), ("nova", "research"))
        self.assertEqual(radial["hough_only_nova_roi"], (232, 652, 276, 696))
        self.assertTrue(recognized.observation.recognized)
        self.assertEqual(recognized.observation.screen_state, "RESEARCH_LAB_MENU")
        target = recognized.target(NOVA_INTERACTION_TARGET)
        self.assertEqual(target, (226, 640, 270, 684))
        self.assertEqual(radial["bind_method"], "template_nova_plus_research_hough")
        self.assertGreaterEqual(radial["template_score"], NOVA_TEMPLATE_MIN_SCORE)
        self.assertGreaterEqual(radial["template_margin"], NOVA_TEMPLATE_MIN_MARGIN)
        self.assertEqual(radial["template_match_roi"], target)
        self.assertIn(radial["template_scale"], NOVA_TEMPLATE_SCALES)

    def test_template_match_roi_is_actual_winning_overlap(self) -> None:
        fixture = _fixture("blocked-canary-radial-48a116d3")
        frame = _load_fixture_frame(fixture)
        recognized = recognize_nova_frame(
            frame,
            captured_monotonic=11.0,
            research_lab_tap_provenance=_lab_provenance(fixture),
            home_context_visible=True,
        )
        target = recognized.target(NOVA_INTERACTION_TARGET)
        assert target is not None
        template = cv2.imread(str(NOVA_RADIAL_TEMPLATE_PATH), cv2.IMREAD_COLOR)
        crop = frame[target[1] : target[3], target[0] : target[2]]
        self.assertEqual(crop.shape, template.shape)
        score = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)[0, 0]
        self.assertGreaterEqual(float(score), NOVA_TEMPLATE_MIN_SCORE)

    def test_route_replay_records_nova_tap_with_zero_transport(self) -> None:
        fixture = _fixture("blocked-canary-radial-48a116d3")
        path = FIXTURE_ROOT / fixture["path"]
        base = time.monotonic()
        provenance = _lab_provenance(fixture, dispatched=base - 4.0)
        captures = [
            load_retained_native_frame(path, captured_monotonic=base - 3.0, expected_sha256=fixture["file_sha256"]),
            load_retained_native_frame(path, captured_monotonic=base - 2.0, expected_sha256=fixture["file_sha256"]),
            load_retained_native_frame(path, captured_monotonic=base - 1.0, expected_sha256=fixture["file_sha256"]),
            load_retained_native_frame(path, captured_monotonic=base - 0.1, expected_sha256=fixture["file_sha256"]),
        ]
        runtime = ReplayNativeRuntime(
            ROOT / "nova-canary-replay-zero-transport",
            captures=captures,
        )
        _enable_offline_runtime_probes(runtime)
        route = NovaNavigationCanaryRoute(
            runtime,
            _identity(),
            atlas_path=ATLAS_PATH,
            home_driver=FakeHomeDriver(),
            settle_seconds=0,
            initial_research_lab_tap_provenance=provenance,
        )
        result = route.run()
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.reason, "nova_lab_successor_not_recognized")
        self.assertFalse(runtime.execute)
        self.assertFalse(runtime.dispatches_transport)
        self.assertEqual(runtime.transport_calls, 0)
        self.assertEqual(len(runtime.intended_inputs), 1)
        intended = runtime.intended_inputs[0]
        self.assertEqual(intended.target_identity, NOVA_INTERACTION_TARGET)
        self.assertEqual(intended.target_roi, (226, 640, 270, 684))
        self.assertFalse(intended.consequential)
        self.assertNotEqual(intended.target_identity, "home.building.research_lab")
        self.assertNotEqual(intended.target_identity, NOVA_PRAISE_TARGET)
        self.assertEqual(result.praise_taps, 0)

    def test_route_replay_strong_initial_radial_without_tap_provenance(self) -> None:
        fixture = _fixture("blocked-canary-radial-48a116d3")
        path = FIXTURE_ROOT / fixture["path"]
        base = time.monotonic()
        captures = [
            load_retained_native_frame(path, captured_monotonic=base - 3.0, expected_sha256=fixture["file_sha256"]),
            load_retained_native_frame(path, captured_monotonic=base - 2.0, expected_sha256=fixture["file_sha256"]),
            load_retained_native_frame(path, captured_monotonic=base - 1.0, expected_sha256=fixture["file_sha256"]),
            load_retained_native_frame(path, captured_monotonic=base - 0.1, expected_sha256=fixture["file_sha256"]),
        ]
        runtime = ReplayNativeRuntime(
            ROOT / "nova-canary-replay-initial-no-provenance",
            captures=captures,
        )
        _enable_offline_runtime_probes(runtime)
        route = NovaNavigationCanaryRoute(
            runtime,
            _identity(),
            atlas_path=ATLAS_PATH,
            home_driver=FakeHomeDriver(),
            settle_seconds=0,
        )
        result = route.run()
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.reason, "nova_lab_successor_not_recognized")
        self.assertEqual(result.navigation_input_count, 1)
        self.assertEqual(result.praise_taps, 0)
        self.assertEqual(runtime.transport_calls, 0)
        self.assertEqual(len(runtime.intended_inputs), 1)
        intended = runtime.intended_inputs[0]
        self.assertEqual(intended.target_identity, NOVA_INTERACTION_TARGET)
        self.assertEqual(intended.target_roi, (226, 640, 270, 684))
        self.assertFalse(intended.consequential)
        self.assertNotEqual(intended.target_identity, NOVA_PRAISE_TARGET)
        self.assertEqual(
            [record["action"] for record in result.records],
            ["tap_nova_navigation"],
        )

    def test_initial_radial_template_only_ambiguous_stale_incompatible_block(self) -> None:
        fixture = _fixture("blocked-canary-radial-48a116d3")
        frame = _load_fixture_frame(fixture)
        template = cv2.imread(str(NOVA_RADIAL_TEMPLATE_PATH), cv2.IMREAD_COLOR)
        assert template is not None

        template_only = np.zeros((1280, 800, 3), np.uint8)
        template_only[640:684, 226:270] = template
        template_only_recognition = recognize_nova_frame(
            template_only,
            captured_monotonic=11.0,
            home_context_visible=True,
        )
        self.assertFalse(template_only_recognition.observation.recognized)
        template_diag = template_only_recognition.diagnostics["nova_radial_template"]
        self.assertFalse(template_diag["accepted"])
        self.assertIn(
            template_diag["reject_reason"],
            {
                "missing_research_circle_candidates",
                "no_unambiguous_research_template_pairing",
            },
        )

        ambiguous = frame.copy()
        second_match = (320, 720, 364, 764)
        ambiguous[
            second_match[1] : second_match[3],
            second_match[0] : second_match[2],
        ] = template
        first_research = (269, 571, 45)
        rel = nova_praise_vision._RESEARCH_TO_NOVA_OFFSET
        second_research = (
            (second_match[0] + second_match[2]) // 2 - rel[0],
            (second_match[1] + second_match[3]) // 2 - rel[1],
            30,
        )
        ambiguous_template = nova_praise_vision._match_nova_radial_template(
            ambiguous,
            None,
            research_circle_candidates=(first_research, second_research),
        )
        self.assertFalse(ambiguous_template["accepted"])
        self.assertEqual(
            ambiguous_template["reject_reason"],
            "ambiguous_research_template_pairings",
        )
        with patch.object(
            nova_praise_vision,
            "_hough_radial_circle_candidates",
            return_value=[first_research, second_research],
        ):
            ambiguous_recognition = recognize_nova_frame(
                ambiguous,
                captured_monotonic=11.0,
                home_context_visible=True,
            )
        self.assertFalse(ambiguous_recognition.observation.recognized)
        self.assertEqual(
            ambiguous_recognition.diagnostics["nova_radial_template"]["reject_reason"],
            "ambiguous_research_template_pairings",
        )

        stale_recognition = recognize_nova_frame(
            frame,
            captured_monotonic=11.0,
            home_context_visible=True,
            stale=True,
        )
        self.assertFalse(stale_recognition.observation.recognized)

        incompatible_recognition = recognize_nova_frame(
            frame,
            captured_monotonic=11.0,
            home_context_visible=True,
            incompatible_state=True,
        )
        self.assertFalse(incompatible_recognition.observation.recognized)

        wrong_context = recognize_nova_frame(
            frame,
            captured_monotonic=11.0,
            home_context_visible=False,
        )
        self.assertFalse(wrong_context.observation.recognized)

    def test_route_never_plans_or_dispatches_praise(self) -> None:
        runtime = FakeRuntime()
        recognizer = RecognitionQueue(
            _radial_recognition("0" * 64),
            _radial_recognition("1" * 64),
            _nova_recognition("2" * 64),
            _nova_recognition("3" * 64),
            _home_recognition("4" * 64),
        )
        route = NovaNavigationCanaryRoute(
            runtime,
            _identity(),
            atlas_path=ATLAS_PATH,
            home_driver=FakeHomeDriver(),
            recognizer=recognizer,
            settle_seconds=0,
        )
        with patch.object(route, "_home_localized", return_value=True):
            result = route.run()
        self.assertEqual(result.praise_taps, 0)
        self.assertNotIn(NOVA_PRAISE_TARGET, [data.get("target_identity") for _, data in runtime.inputs])
        self.assertTrue(all(not data.get("consequential", False) for _, data in runtime.inputs))
        self.assertNotIn("praise", " ".join(record["action"] for record in result.records).lower())

    def test_template_manifest_hash_mismatch_rejects(self) -> None:
        import tempfile

        fixture = _fixture("blocked-canary-radial-48a116d3")
        frame = _load_fixture_frame(fixture)
        bad_manifest = {
            "schema_version": 1,
            "templates": [
                {
                    "id": "nova-radial-portrait",
                    "path": "nova-radial-portrait.png",
                    "file_sha256": "0" * 64,
                    "intended_visual_variant": "Research Lab radial Nova portrait/control",
                    "source": {
                        "path": "tests/fixtures/nova_praise_preflight/research-lab-radial-07f3d826.png",
                        "file_sha256": "07f3d8267d7a19384e4064e6439f0f655536d5a86fe41dff9897fca766ee88bd",
                        "crop_xyxy": [137, 631, 181, 675],
                    },
                    "runtime_profile": "native-800x1280",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            manifest_path.write_text(json.dumps(bad_manifest), encoding="utf-8")
            with patch.object(
                nova_praise_vision,
                "NOVA_RADIAL_TEMPLATE_MANIFEST_PATH",
                manifest_path,
            ):
                nova_praise_vision._NOVA_TEMPLATE_CACHE = None
                recognized = recognize_nova_frame(
                    frame,
                    captured_monotonic=11.0,
                    research_lab_tap_provenance=_lab_provenance(fixture),
                    home_context_visible=True,
                )
        nova_praise_vision._NOVA_TEMPLATE_CACHE = None
        template = recognized.diagnostics["nova_radial_template"]
        self.assertFalse(recognized.observation.recognized)
        self.assertEqual(template["reject_reason"], "stale_or_invalid_template_provenance")
        self.assertFalse(template["accepted"])

    def test_translated_valid_radial_still_binds(self) -> None:
        fixture = _fixture("research-lab-radial-07f3d826")
        frame = _load_fixture_frame(fixture)
        shift = 12
        translated = np.zeros_like(frame)
        translated[shift:, shift:] = frame[:-shift, :-shift]
        provenance = _lab_provenance(fixture)
        x0, y0, x1, y1 = provenance.target_roi
        shifted = ResearchLabTapProvenance(
            provenance.action_key,
            provenance.target_identity,
            provenance.source_frame_sha256,
            (x0 + shift, y0 + shift, x1 + shift, y1 + shift),
            provenance.dispatched_monotonic,
        )
        recognized = recognize_nova_frame(
            translated,
            captured_monotonic=11.0,
            research_lab_tap_provenance=shifted,
            home_context_visible=True,
        )
        self.assertTrue(recognized.observation.recognized)
        target = recognized.target(NOVA_INTERACTION_TARGET)
        self.assertIsNotNone(target)
        self.assertEqual(target, (232 + shift, 652 + shift, 276 + shift, 696 + shift))

    def test_supported_visual_scale_variation_binds_scaled_match_roi(self) -> None:
        fixture = _fixture("blocked-canary-radial-48a116d3")
        frame = _load_fixture_frame(fixture)
        template = cv2.imread(str(NOVA_RADIAL_TEMPLATE_PATH), cv2.IMREAD_COLOR)
        scale = 1.08
        self.assertIn(scale, NOVA_TEMPLATE_SCALES)
        height = int(round(template.shape[0] * scale))
        width = int(round(template.shape[1] * scale))
        scaled = cv2.resize(template, (width, height), interpolation=cv2.INTER_CUBIC)
        varied = frame.copy()
        varied[640:684, 226:270] = 0
        center_x, center_y = 248, 662
        x0 = center_x - width // 2
        y0 = center_y - height // 2
        varied[y0 : y0 + height, x0 : x0 + width] = scaled
        recognized = recognize_nova_frame(
            varied,
            captured_monotonic=11.0,
            research_lab_tap_provenance=_lab_provenance(fixture),
            home_context_visible=True,
        )
        self.assertTrue(recognized.observation.recognized)
        radial = recognized.diagnostics["research_lab_radial"]
        target = recognized.target(NOVA_INTERACTION_TARGET)
        self.assertEqual(radial["template_scale"], scale)
        self.assertEqual(target, (x0, y0, x0 + width, y0 + height))
        self.assertEqual(radial["template_match_roi"], target)
        crop = varied[target[1] : target[3], target[0] : target[2]]
        self.assertEqual(crop.shape[:2], (height, width))

    def test_production_matcher_weak_and_ambiguous_rejects(self) -> None:
        fixture = _fixture("blocked-canary-radial-48a116d3")
        frame = _load_fixture_frame(fixture)
        template = cv2.imread(str(NOVA_RADIAL_TEMPLATE_PATH), cv2.IMREAD_COLOR)
        provenance = _lab_provenance(fixture)

        weak = frame.copy()
        weak[620:705, 205:290] = np.random.RandomState(0).randint(
            0, 255, weak[620:705, 205:290].shape, dtype=np.uint8
        )
        weak_recognition = recognize_nova_frame(
            weak,
            captured_monotonic=11.0,
            research_lab_tap_provenance=provenance,
            home_context_visible=True,
        )
        weak_template = weak_recognition.diagnostics["nova_radial_template"]
        self.assertFalse(weak_recognition.observation.recognized)
        self.assertEqual(weak_template["reject_reason"], "weak_template_match")
        self.assertLess(weak_template["score"], NOVA_TEMPLATE_MIN_SCORE)

        ambiguous = frame.copy()
        ambiguous[600:720, 160:300] = 40
        ambiguous[640:684, 226:270] = template
        ambiguous[606:650, 192:236] = template
        ambiguous_recognition = recognize_nova_frame(
            ambiguous,
            captured_monotonic=11.0,
            research_lab_tap_provenance=provenance,
            home_context_visible=True,
        )
        ambiguous_template = ambiguous_recognition.diagnostics["nova_radial_template"]
        self.assertFalse(ambiguous_recognition.observation.recognized)
        self.assertEqual(
            ambiguous_template["reject_reason"],
            "ambiguous_or_duplicated_template_match",
        )
        self.assertLess(ambiguous_template["margin"], NOVA_TEMPLATE_MIN_MARGIN)

        clean = recognize_nova_frame(
            frame,
            captured_monotonic=11.0,
            research_lab_tap_provenance=provenance,
            home_context_visible=True,
        )
        clean_template = clean.diagnostics["nova_radial_template"]
        self.assertTrue(clean.observation.recognized)
        self.assertGreaterEqual(clean_template["overlapping_peer_count"], 1)
        self.assertEqual(clean_template["spatially_distinct_strong_count"], 0)

    def test_recognize_negatives_home_building_ocr_stale_clipped(self) -> None:
        blocked = _fixture("blocked-canary-radial-48a116d3")
        frame = _load_fixture_frame(blocked)
        provenance = _lab_provenance(blocked)
        template = cv2.imread(str(NOVA_RADIAL_TEMPLATE_PATH), cv2.IMREAD_COLOR)

        home_path = FIXTURE_ROOT / "zoomed-home-a.png"
        home_frame = cv2.imread(str(home_path), cv2.IMREAD_COLOR)
        self.assertIsNotNone(home_frame)
        home_recognition = recognize_nova_frame(
            home_frame,
            captured_monotonic=11.0,
            research_lab_tap_provenance=provenance,
            home_context_visible=True,
        )
        self.assertFalse(home_recognition.observation.recognized)
        self.assertNotEqual(home_recognition.observation.screen_state, "RESEARCH_LAB_MENU")

        different = recognize_nova_frame(
            frame,
            captured_monotonic=11.0,
            research_lab_tap_provenance=ResearchLabTapProvenance(
                provenance.action_key,
                provenance.target_identity,
                provenance.source_frame_sha256,
                (500, 900, 600, 1000),
                provenance.dispatched_monotonic,
            ),
            home_context_visible=True,
        )
        self.assertFalse(different.observation.recognized)
        self.assertNotIn(
            "research",
            set(different.diagnostics["research_lab_radial_hough"].get("hough_anchors") or ()),
        )

        ocr_only = frame.copy()
        ocr_only[450:800, 0:450] = 20
        ocr_recognition = recognize_nova_frame(
            ocr_only,
            captured_monotonic=11.0,
            research_lab_tap_provenance=provenance,
            home_context_visible=True,
        )
        self.assertFalse(ocr_recognition.observation.recognized)
        self.assertEqual(
            ocr_recognition.diagnostics["nova_radial_template"]["reject_reason"],
            "weak_template_match",
        )

        stale = recognize_nova_frame(
            frame,
            captured_monotonic=9.0,
            research_lab_tap_provenance=provenance,
            home_context_visible=True,
        )
        self.assertFalse(stale.observation.recognized)
        self.assertIn(
            "fresh_post_tap_frame",
            stale.diagnostics["research_lab_radial"]["rejected_or_missing_observations"],
        )

        clipped = frame.copy()
        clipped[640:684, 226:270] = 0
        edge_provenance = ResearchLabTapProvenance(
            provenance.action_key,
            provenance.target_identity,
            provenance.source_frame_sha256,
            (2, 407, 146, 632),
            provenance.dispatched_monotonic,
        )
        clipped[631:675, 2:46] = template
        clipped_recognition = recognize_nova_frame(
            clipped,
            captured_monotonic=11.0,
            research_lab_tap_provenance=edge_provenance,
            home_context_visible=True,
        )
        self.assertFalse(clipped_recognition.observation.recognized)
        self.assertEqual(
            clipped_recognition.diagnostics["nova_radial_template"]["reject_reason"],
            "clipped_or_partial_template_match",
        )

    def test_radial_composite_negative_controls_fail_closed(self) -> None:
        valid = {
            "source_frame_sha256": "a" * 64,
            "provenance_valid": True,
            "fresh_successor": True,
            "home_context_visible": True,
            "geometry_anchors": ("details", "upgrade", "research", "nova"),
            "ocr_terms": ("research", "bioenhancer"),
            "nova_target_roi": (226, 640, 270, 684),
        }
        for changes in (
            {"provenance_valid": False},
            {"fresh_successor": False},
            {"home_context_visible": False},
            {"geometry_anchors": ()},
            {"ocr_terms": ()},
            {"nova_target_roi": None},
            {"ambiguous_geometry": True},
            {"incompatible_state": True},
        ):
            with self.subTest(changes=changes):
                evidence = evaluate_research_lab_radial_evidence(**{**valid, **changes})
                self.assertFalse(evidence.recognized)
                self.assertEqual(evidence.semantic_state, "UNKNOWN")

    def test_hough_full_path_remains_valid_without_template_requirement(self) -> None:
        evidence = evaluate_research_lab_radial_evidence(
            source_frame_sha256="a" * 64,
            provenance_valid=True,
            fresh_successor=True,
            home_context_visible=True,
            geometry_anchors=("details", "upgrade", "research", "nova"),
            ocr_terms=("research", "bioenhancer"),
            nova_target_roi=(226, 640, 270, 684),
            nova_template_accepted=False,
        )
        self.assertTrue(evidence.recognized)

    def test_project_owned_template_manifest_provenance(self) -> None:
        manifest = json.loads(ASSET_MANIFEST.read_text(encoding="utf-8"))
        entry = manifest["templates"][0]
        raw = NOVA_RADIAL_TEMPLATE_PATH.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), entry["file_sha256"])
        self.assertEqual(
            entry["source"]["file_sha256"],
            "ea6fd89e9dae862adf965a44fffe15e83653ed84234754f18419d4ac712487cb",
        )
        self.assertEqual(entry["source"]["crop_xyxy"], [226, 640, 270, 684])
        self.assertEqual(entry["runtime_profile"], "native-800x1280")
        self.assertEqual(
            entry["file_sha256"],
            "b020dd21c09831cf732dde04d7177527353179a1f8182dfb0677d1d84ef5eeee",
        )


if __name__ == "__main__":
    unittest.main()
