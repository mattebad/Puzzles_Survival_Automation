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
    revalidate_nova_praise_frame_fast,
)
import tasks.nova_praise_vision as nova_praise_vision
from tasks.runtime_identity import RuntimeIdentityAssurance, VerifiedRuntimeIdentity


ROOT = Path(__file__).resolve().parents[1]
ATLAS_PATH = ROOT / "tasks/assets/home_atlas/bluestacks/800x1280/atlas.json"
FIXTURE_ROOT = ROOT / "tests/fixtures/nova_praise_preflight"
ASSET_MANIFEST = ROOT / "tasks/assets/nova_praise/800x1280/manifest.json"
NOVA_FLOW_CAPTURES = (
    ROOT / ".local-captures" / "flow-delivery" / "NOVA-PRAISE-HOME-ATLAS-MIGRATION"
)
SELECTED_HOME_CANARY_FRAME = (
    NOVA_FLOW_CAPTURES
    / "nova-navigation-canary-20260722T152646968017Z"
    / "frames"
    / "0001-canary-source.png"
)
POSITIVE_HOME_CANARY_FRAME = (
    NOVA_FLOW_CAPTURES
    / "nova-navigation-canary-20260722T160241223935Z"
    / "frames"
    / "0001-canary-source.png"
)
EXPANDED_RADIAL_CANARY_FRAME = (
    NOVA_FLOW_CAPTURES
    / "nova-navigation-canary-20260722T020656687010Z"
    / "frames"
    / "0008-canary-open-nova-immediate-before.png"
)
SUPERVISED_OCR_MISS_NOVA_FRAME = (
    ROOT
    / ".local-captures"
    / "flow-delivery"
    / "NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE"
    / "nova-praise-one-free-pulse-20260722T175237968971Z"
    / "frames"
    / "0008-canary-open-nova-immediate-before.png"
)
SUPERVISED_OCR_MISS_LAB_PROVENANCE = ResearchLabTapProvenance(
    "nova-canary:open-research-lab:5a7a54555b91225a3ab6d6dd88dcb620907d65d6bcb029ac3bd0b2710d771154",
    "home.building.research_lab",
    "5a7a54555b91225a3ab6d6dd88dcb620907d65d6bcb029ac3bd0b2710d771154",
    (355, 317, 523, 545),
    10.0,
)
SUPERVISED_OCR_MISS_NOVA_ROI = (385, 552, 429, 596)


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
                "geometry_anchors": ("nova",),
                "hough_only_anchors": ("details", "nova", "research", "upgrade"),
                "bind_method": "template_nova_initial",
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


class RecordingRecognitionQueue(RecognitionQueue):
    def __init__(self, *items: NovaFrameRecognition) -> None:
        super().__init__(*items)
        self.calls: list[dict[str, object]] = []

    def __call__(self, *_args, **kwargs):
        self.calls.append(kwargs)
        return super().__call__(*_args, **kwargs)


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

    def test_research_lab_provenance_stamps_after_dispatch_not_pre_tap_capture(
        self,
    ) -> None:
        """Long pre-tap prep must not age the 30s successor window; post-dispatch age still applies."""
        clock = {"t": 1_000_000.0}

        def mono() -> float:
            return clock["t"]

        home_before_sha = hashlib.sha256(b"capture-2").hexdigest()
        runtime = FakeRuntime()
        recognizer = RecordingRecognitionQueue(
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
        real_prepare = route._prepare_home_navigation
        real_settle = route._settle

        def prepare_with_long_prep(captured, **kwargs):
            # 18.6s of validated pre-dispatch preparation (session T194935572262Z shape).
            clock["t"] += 18.6
            return real_prepare(captured, **kwargs)

        def settle_with_post_dispatch_latency(immediate_label: str, settled_label: str):
            immediate_post = route._capture(immediate_label)
            if settled_label == "canary-open-lab-settled":
                clock["t"] += 21.2
            settled = route._capture(settled_label)
            return immediate_post, settled

        route._prepare_home_navigation = prepare_with_long_prep  # type: ignore[method-assign]
        route._settle = settle_with_post_dispatch_latency  # type: ignore[method-assign]
        with patch("time.monotonic", mono):
            with patch.object(route, "_home_localized", return_value=True):
                pre_tap_capture = clock["t"]
                result = route.run()
        self.assertEqual(result.status, "completed")
        self.assertEqual(
            [kind for kind, _ in runtime.inputs],
            ["tap", "tap", "back"],
        )
        provenanced = [
            call
            for call in recognizer.calls
            if call.get("research_lab_tap_provenance") is not None
        ]
        self.assertTrue(provenanced)
        provenance = provenanced[0]["research_lab_tap_provenance"]
        assert isinstance(provenance, ResearchLabTapProvenance)
        self.assertEqual(provenance.source_frame_sha256, home_before_sha)
        self.assertEqual(provenance.target_identity, "home.building.research_lab")
        self.assertEqual(provenance.target_roi, (198, 407, 363, 632))
        self.assertEqual(
            provenance.action_key,
            f"nova-canary:open-research-lab:{home_before_sha}",
        )
        # Dispatch stamp is post-transport monotonic, not the pre-tap capture time.
        self.assertNotEqual(provenance.dispatched_monotonic, pre_tap_capture)
        self.assertAlmostEqual(
            provenance.dispatched_monotonic,
            pre_tap_capture + 18.6,
            places=5,
        )
        settle_monotonic = float(provenanced[0]["captured_monotonic"])
        settle_age_from_dispatch = settle_monotonic - provenance.dispatched_monotonic
        settle_age_from_pre_tap = settle_monotonic - pre_tap_capture
        self.assertGreater(settle_age_from_pre_tap, 30.0)
        self.assertLessEqual(settle_age_from_dispatch, 30.0)
        self.assertAlmostEqual(settle_age_from_dispatch, 21.2, places=5)

        fixture = _fixture("blocked-canary-radial-48a116d3")
        frame = _load_fixture_frame(fixture)
        still_fresh = recognize_nova_frame(
            frame,
            captured_monotonic=provenance.dispatched_monotonic + 21.2,
            research_lab_tap_provenance=provenance,
            home_context_visible=True,
        )
        self.assertTrue(still_fresh.observation.recognized)
        stale_after_dispatch = recognize_nova_frame(
            frame,
            captured_monotonic=provenance.dispatched_monotonic + 30.1,
            research_lab_tap_provenance=provenance,
            home_context_visible=True,
        )
        self.assertFalse(stale_after_dispatch.observation.recognized)
        radial = stale_after_dispatch.diagnostics["research_lab_radial"]
        self.assertIn("fresh_post_tap_frame", radial["rejected_or_missing_observations"])
        self.assertFalse(radial["recognized"])

    def test_failed_research_lab_tap_never_creates_provenance(self) -> None:
        runtime = FakeRuntime()

        def _failing_tap(_source, **_kwargs) -> None:
            raise RuntimeError("research_lab_transport_failed")

        runtime.tap = _failing_tap  # type: ignore[method-assign]
        recognizer = RecordingRecognitionQueue(_home_recognition("0" * 64))
        route = NovaNavigationCanaryRoute(
            runtime,
            _identity(),
            atlas_path=ATLAS_PATH,
            home_driver=FakeHomeDriver(),
            recognizer=recognizer,
            settle_seconds=0,
        )
        with patch.object(route, "_home_localized", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "research_lab_transport_failed"):
                route.run()
        self.assertEqual(runtime.inputs, [])
        self.assertTrue(
            all(
                call.get("research_lab_tap_provenance") is None
                for call in recognizer.calls
            )
        )

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
        self.assertEqual(radial["bind_method"], "template_nova_initial")
        self.assertTrue(radial["initial_unprovenanced_composite"])
        self.assertGreaterEqual(radial["template_score"], NOVA_TEMPLATE_MIN_SCORE)
        self.assertGreaterEqual(radial["template_margin"], NOVA_TEMPLATE_MIN_MARGIN)
        # Strong initial template composite remains authoritative with empty OCR.
        with patch.object(nova_praise_vision, "_radial_ocr_terms", return_value=()):
            empty_ocr = recognize_nova_frame(
                frame,
                captured_monotonic=11.0,
                home_context_visible=True,
            )
        self.assertTrue(empty_ocr.observation.recognized)
        self.assertEqual(empty_ocr.target(NOVA_INTERACTION_TARGET), (226, 640, 270, 684))
        empty_radial = empty_ocr.diagnostics["research_lab_radial"]
        self.assertEqual(empty_radial["bind_method"], "template_nova_initial")
        self.assertEqual(tuple(empty_radial.get("ocr_terms") or ()), ())

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
        self.assertEqual(fresh.target(NOVA_INTERACTION_TARGET), (226, 640, 270, 684))
        self.assertEqual(
            fresh.diagnostics["research_lab_radial"]["bind_method"],
            "template_nova_from_research_tap",
        )

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
        self.assertEqual(radial["bind_method"], "template_nova_from_research_tap")
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
        # Strong accepted template + forced home context + empty OCR is now
        # authoritative for initial-unprovenanced (OCR no longer required).
        template_only_recognition = recognize_nova_frame(
            template_only,
            captured_monotonic=11.0,
            home_context_visible=True,
        )
        self.assertTrue(template_only_recognition.observation.recognized)
        self.assertEqual(
            template_only_recognition.target(NOVA_INTERACTION_TARGET),
            (226, 640, 270, 684),
        )
        self.assertEqual(
            template_only_recognition.diagnostics["research_lab_radial"]["bind_method"],
            "template_nova_initial",
        )

        ambiguous = frame.copy()
        second_match = (320, 720, 364, 764)
        ambiguous[
            second_match[1] : second_match[3],
            second_match[0] : second_match[2],
        ] = template
        ambiguous_template = nova_praise_vision._match_nova_radial_template(
            ambiguous,
            None,
        )
        self.assertFalse(ambiguous_template["accepted"])
        self.assertEqual(
            ambiguous_template["reject_reason"],
            "ambiguous_or_duplicated_template_match",
        )
        ambiguous_recognition = recognize_nova_frame(
            ambiguous,
            captured_monotonic=11.0,
            home_context_visible=True,
        )
        self.assertFalse(ambiguous_recognition.observation.recognized)
        self.assertEqual(
            ambiguous_recognition.diagnostics["nova_radial_template"]["reject_reason"],
            "ambiguous_or_duplicated_template_match",
        )
        self.assertEqual(
            ambiguous_recognition.diagnostics["research_lab_radial"]["bind_method"],
            "ambiguous_or_duplicated_template_match",
        )
        self.assertTrue(
            NovaNavigationCanaryRoute._research_radial_geometry_present(
                ambiguous_recognition
            )
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

    def test_initial_radial_widened_search_binds_right_shifted_template(self) -> None:
        template = cv2.imread(str(NOVA_RADIAL_TEMPLATE_PATH), cv2.IMREAD_COLOR)
        assert template is not None
        template_height, template_width = template.shape[:2]
        y = 640
        right_shifted_x = 449
        old_sector_x = 226
        self.assertLess(right_shifted_x, 450)
        self.assertGreater(right_shifted_x + template_width, 450)

        def synthetic_frame(*x_positions: int) -> np.ndarray:
            frame = np.zeros((1280, 800, 3), dtype=np.uint8)
            for x in x_positions:
                frame[y : y + template_height, x : x + template_width] = template
            return frame

        with patch.object(
            nova_praise_vision,
            "_radial_ocr_terms",
            return_value=("research", "nova"),
        ):
            right_shifted = recognize_nova_frame(
                synthetic_frame(right_shifted_x),
                captured_monotonic=11.0,
                research_lab_tap_provenance=None,
                home_context_visible=True,
                stale=False,
            )
            control = recognize_nova_frame(
                synthetic_frame(old_sector_x),
                captured_monotonic=11.0,
                research_lab_tap_provenance=None,
                home_context_visible=True,
                stale=False,
            )
            black = recognize_nova_frame(
                np.zeros((1280, 800, 3), dtype=np.uint8),
                captured_monotonic=11.0,
                research_lab_tap_provenance=None,
                home_context_visible=True,
                stale=False,
            )
            duplicate = recognize_nova_frame(
                synthetic_frame(old_sector_x, right_shifted_x),
                captured_monotonic=11.0,
                research_lab_tap_provenance=None,
                home_context_visible=True,
                stale=False,
            )

        right_template = right_shifted.diagnostics["nova_radial_template"]
        self.assertTrue(right_shifted.observation.recognized)
        self.assertEqual(
            right_shifted.diagnostics["research_lab_radial"]["bind_method"],
            "template_nova_initial",
        )
        self.assertEqual(right_template["search_roi"], (0, 450, 560, 800))
        self.assertTrue(right_template["accepted"])
        self.assertGreaterEqual(right_template["score"], NOVA_TEMPLATE_MIN_SCORE)
        right_target = right_shifted.target(NOVA_INTERACTION_TARGET)
        self.assertIsNotNone(right_target)
        assert right_target is not None
        self.assertLessEqual(abs(right_target[0] - right_shifted_x), 1)
        self.assertLessEqual(abs(right_target[1] - y), 1)
        self.assertLessEqual(abs((right_target[2] - right_target[0]) - template_width), 1)
        self.assertLessEqual(abs((right_target[3] - right_target[1]) - template_height), 1)

        self.assertTrue(control.observation.recognized)
        control_target = control.target(NOVA_INTERACTION_TARGET)
        self.assertIsNotNone(control_target)
        assert control_target is not None
        self.assertLessEqual(abs(control_target[0] - old_sector_x), 1)
        self.assertLessEqual(abs(control_target[1] - y), 1)

        self.assertFalse(black.observation.recognized)
        self.assertIsNone(black.target(NOVA_INTERACTION_TARGET))

        duplicate_template = duplicate.diagnostics["nova_radial_template"]
        self.assertFalse(duplicate.observation.recognized)
        self.assertIsNone(duplicate.target(NOVA_INTERACTION_TARGET))
        self.assertEqual(
            duplicate_template["reject_reason"],
            "ambiguous_or_duplicated_template_match",
        )
        self.assertGreaterEqual(
            duplicate_template["spatially_distinct_strong_count"],
            1,
        )

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
        self.assertEqual(target, (226 + shift, 640 + shift, 270 + shift, 684 + shift))
        self.assertEqual(
            recognized.diagnostics["research_lab_radial"]["bind_method"],
            "template_nova_from_research_tap",
        )

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
            "geometry_anchors": ("nova",),
            "ocr_terms": ("research", "bioenhancer"),
            "nova_target_roi": (226, 640, 270, 684),
            "nova_template_accepted": True,
        }
        self.assertTrue(evaluate_research_lab_radial_evidence(**valid).recognized)
        empty_ocr = evaluate_research_lab_radial_evidence(**{**valid, "ocr_terms": ()})
        self.assertTrue(empty_ocr.recognized)
        self.assertEqual(empty_ocr.nova_target_roi, (226, 640, 270, 684))
        self.assertNotIn(
            "compatible_research_lab_ocr",
            empty_ocr.rejected_or_missing_observations,
        )
        # Strong unambiguous initial template composite is authoritative; OCR is
        # corroborating/diagnostic only and must not veto recognition.
        initial_empty_ocr = evaluate_research_lab_radial_evidence(
            **{
                **valid,
                "provenance_valid": False,
                "fresh_successor": False,
                "ocr_terms": (),
                "initial_unprovenanced_composite": True,
            }
        )
        self.assertTrue(initial_empty_ocr.recognized)
        self.assertEqual(initial_empty_ocr.nova_target_roi, (226, 640, 270, 684))
        self.assertIn(
            "compatible_research_lab_ocr",
            initial_empty_ocr.rejected_or_missing_observations,
        )
        for changes in (
            {"provenance_valid": False},
            {"fresh_successor": False},
            {"home_context_visible": False},
            {"geometry_anchors": ()},
            {"nova_target_roi": None},
            {"ambiguous_geometry": True},
            {"incompatible_state": True},
            {"nova_template_accepted": False},
        ):
            with self.subTest(changes=changes):
                evidence = evaluate_research_lab_radial_evidence(**{**valid, **changes})
                self.assertFalse(evidence.recognized)
                self.assertEqual(evidence.semantic_state, "UNKNOWN")
        # Fail-closed negatives for the strong-initial / empty-OCR path.
        initial_base = {
            **valid,
            "provenance_valid": False,
            "fresh_successor": False,
            "ocr_terms": (),
            "initial_unprovenanced_composite": True,
        }
        for changes in (
            {"home_context_visible": False},
            {"geometry_anchors": ()},
            {"nova_target_roi": None},
            {"ambiguous_geometry": True},
            {"incompatible_state": True},
            {"nova_template_accepted": False},
            {"initial_unprovenanced_composite": False},
        ):
            with self.subTest(initial_fail_closed=changes):
                evidence = evaluate_research_lab_radial_evidence(
                    **{**initial_base, **changes}
                )
                self.assertFalse(evidence.recognized)
                self.assertEqual(evidence.semantic_state, "UNKNOWN")

    def test_supervised_ocr_miss_accepted_template_binds_nova(self) -> None:
        if not SUPERVISED_OCR_MISS_NOVA_FRAME.is_file():
            self.skipTest(f"retained frame absent: {SUPERVISED_OCR_MISS_NOVA_FRAME}")
        frame = cv2.imread(str(SUPERVISED_OCR_MISS_NOVA_FRAME), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame)
        with patch.object(nova_praise_vision, "_radial_ocr_terms", return_value=()):
            recognized = recognize_nova_frame(
                frame,
                captured_monotonic=23.7,
                research_lab_tap_provenance=SUPERVISED_OCR_MISS_LAB_PROVENANCE,
                home_context_visible=True,
            )
        self.assertTrue(recognized.observation.recognized)
        self.assertEqual(recognized.observation.screen_state, "RESEARCH_LAB_MENU")
        self.assertEqual(
            recognized.target(NOVA_INTERACTION_TARGET),
            SUPERVISED_OCR_MISS_NOVA_ROI,
        )
        radial = recognized.diagnostics["research_lab_radial"]
        self.assertEqual(radial["bind_method"], "template_nova_from_research_tap")
        self.assertEqual(tuple(radial.get("ocr_terms") or ()), ())
        self.assertNotIn(
            "compatible_research_lab_ocr",
            radial["rejected_or_missing_observations"],
        )
        template = recognized.diagnostics["nova_radial_template"]
        self.assertTrue(template["accepted"])
        self.assertGreaterEqual(template["score"], NOVA_TEMPLATE_MIN_SCORE)
        self.assertGreaterEqual(template["margin"], NOVA_TEMPLATE_MIN_MARGIN)
        self.assertEqual(template["match_roi"], SUPERVISED_OCR_MISS_NOVA_ROI)

    def test_hough_full_without_template_never_recognizes_radial(self) -> None:
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
        self.assertFalse(evidence.recognized)
        self.assertIsNone(evidence.nova_target_roi)

    def test_fresh_research_tap_template_binds_without_hough_research_anchor(self) -> None:
        fixture = _fixture("blocked-canary-radial-48a116d3")
        frame = _load_fixture_frame(fixture)
        provenance = _lab_provenance(fixture)
        with patch.object(
            nova_praise_vision,
            "_research_lab_radial_geometry",
            return_value=(
                ("details", "nova", "upgrade"),
                None,
                False,
                {
                    "method": "hough_circles",
                    "hough_anchors": ("details", "nova", "upgrade"),
                    "hough_nova_roi": None,
                    "hough_ambiguous": False,
                    "hough_candidate_count": 0,
                    "hough_candidates": (),
                    "search_roi": (0, 450, 450, 800),
                },
            ),
        ):
            recognized = recognize_nova_frame(
                frame,
                captured_monotonic=11.0,
                research_lab_tap_provenance=provenance,
                home_context_visible=True,
            )
        self.assertTrue(recognized.observation.recognized)
        self.assertEqual(recognized.observation.screen_state, "RESEARCH_LAB_MENU")
        self.assertEqual(recognized.target(NOVA_INTERACTION_TARGET), (226, 640, 270, 684))
        radial = recognized.diagnostics["research_lab_radial"]
        self.assertEqual(radial["bind_method"], "template_nova_from_research_tap")
        self.assertNotIn("research", set(radial.get("hough_only_anchors") or ()))

    def test_selected_home_hough_only_does_not_promote_radial(self) -> None:
        if not SELECTED_HOME_CANARY_FRAME.is_file():
            self.skipTest(f"retained frame absent: {SELECTED_HOME_CANARY_FRAME}")
        raw = SELECTED_HOME_CANARY_FRAME.read_bytes()
        frame = cv2.imread(str(SELECTED_HOME_CANARY_FRAME), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame)
        captured = CapturedNativeFrame(
            frame,
            raw,
            hashlib.sha256(raw).hexdigest(),
            11.0,
            SELECTED_HOME_CANARY_FRAME,
        )
        route = NovaNavigationCanaryRoute(
            FakeRuntime(),
            _identity(),
            atlas_path=ATLAS_PATH,
            settle_seconds=0,
        )
        recognition, measured_home = route._recognize_with_measured_home(captured)
        self.assertTrue(measured_home)
        radial = recognition.diagnostics.get("research_lab_radial") or {}
        self.assertFalse(radial.get("recognized"))
        self.assertEqual(radial.get("bind_method"), "none")
        self.assertEqual(tuple(radial.get("ocr_terms") or ()), ("research",))
        self.assertIsNone(recognition.target(NOVA_INTERACTION_TARGET))
        self.assertFalse(route._research_radial_geometry_present(recognition))
        self.assertNotEqual(route._navigation_surface(recognition), "RESEARCH_LAB_MENU")
        home_capture, blocked, initial_radial = route._normalize_known_start_to_home(
            captured
        )
        self.assertIsNone(blocked)
        self.assertIsNone(initial_radial)
        self.assertIs(home_capture, captured)

    def test_positive_home_base_wins_over_hough_ambiguity(self) -> None:
        if not POSITIVE_HOME_CANARY_FRAME.is_file():
            self.skipTest(f"retained frame absent: {POSITIVE_HOME_CANARY_FRAME}")
        raw = POSITIVE_HOME_CANARY_FRAME.read_bytes()
        frame = cv2.imread(str(POSITIVE_HOME_CANARY_FRAME), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame)
        captured = CapturedNativeFrame(
            frame,
            raw,
            hashlib.sha256(raw).hexdigest(),
            11.0,
            POSITIVE_HOME_CANARY_FRAME,
        )
        route = NovaNavigationCanaryRoute(
            FakeRuntime(),
            _identity(),
            atlas_path=ATLAS_PATH,
            settle_seconds=0,
        )
        recognition, measured_home = route._recognize_with_measured_home(captured)
        self.assertTrue(measured_home)
        self.assertTrue(recognition.observation.recognized)
        self.assertEqual(recognition.observation.screen_state, "HOME_BASE")
        radial = recognition.diagnostics.get("research_lab_radial") or {}
        self.assertTrue(radial.get("hough_ambiguous") or radial.get("ambiguous_geometry"))
        self.assertEqual(radial.get("bind_method"), "none")
        self.assertEqual(tuple(radial.get("ocr_terms") or ()), ("research",))
        self.assertIsNone(recognition.target(NOVA_INTERACTION_TARGET))
        self.assertEqual(route._navigation_surface(recognition), "HOME_BASE")
        self.assertFalse(route._research_radial_geometry_present(recognition))
        home_capture, blocked, initial_radial = route._normalize_known_start_to_home(
            captured
        )
        self.assertIsNone(blocked)
        self.assertIsNone(initial_radial)
        self.assertIs(home_capture, captured)

    def test_prior_expanded_radial_retained_frame_remains_bound(self) -> None:
        if not EXPANDED_RADIAL_CANARY_FRAME.is_file():
            self.skipTest(f"retained frame absent: {EXPANDED_RADIAL_CANARY_FRAME}")
        frame = cv2.imread(str(EXPANDED_RADIAL_CANARY_FRAME), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame)
        recognized = recognize_nova_frame(
            frame,
            captured_monotonic=11.0,
            home_context_visible=True,
        )
        self.assertTrue(recognized.observation.recognized)
        self.assertEqual(recognized.observation.screen_state, "RESEARCH_LAB_MENU")
        self.assertEqual(recognized.target(NOVA_INTERACTION_TARGET), (381, 634, 425, 678))
        radial = recognized.diagnostics["research_lab_radial"]
        self.assertEqual(radial["bind_method"], "template_nova_initial")
        self.assertAlmostEqual(radial["template_score"], 0.976879, places=5)
        self.assertGreaterEqual(radial["template_margin"], NOVA_TEMPLATE_MIN_MARGIN)
        self.assertEqual(radial["template_match_roi"], (381, 634, 425, 678))
        self.assertTrue(
            NovaNavigationCanaryRoute._research_radial_geometry_present(recognized)
        )
        self.assertEqual(
            NovaNavigationCanaryRoute._navigation_surface(recognized),
            "RESEARCH_LAB_MENU",
        )

    def test_synthetic_template_ambiguity_remains_fail_closed(self) -> None:
        base_obs = replace(
            _radial_recognition("a" * 64).observation,
            recognized=False,
            screen_state="UNKNOWN",
        )
        ambiguous = NovaFrameRecognition(
            base_obs,
            "a" * 64,
            (),
            {
                "research_lab_radial": {
                    "recognized": False,
                    "geometry_anchors": (),
                    "hough_only_anchors": ("details", "nova", "research", "upgrade"),
                    "bind_method": "ambiguous_or_duplicated_template_match",
                    "ambiguous_geometry": True,
                    "ocr_terms": ("research",),
                }
            },
        )
        self.assertTrue(
            NovaNavigationCanaryRoute._research_radial_geometry_present(ambiguous)
        )
        self.assertEqual(
            NovaNavigationCanaryRoute._navigation_surface(ambiguous),
            "RESEARCH_LAB_MENU",
        )

        hough_only = NovaFrameRecognition(
            replace(base_obs, frame_sha256="b" * 64),
            "b" * 64,
            (),
            {
                "research_lab_radial": {
                    "recognized": False,
                    "geometry_anchors": ("details", "nova", "research", "upgrade"),
                    "hough_only_anchors": ("details", "nova", "research", "upgrade"),
                    "bind_method": "none",
                    "ambiguous_geometry": True,
                    "hough_ambiguous": True,
                    "ocr_terms": ("research", "nova", "details"),
                }
            },
        )
        self.assertFalse(
            NovaNavigationCanaryRoute._research_radial_geometry_present(hough_only)
        )
        self.assertNotEqual(
            NovaNavigationCanaryRoute._navigation_surface(hough_only),
            "RESEARCH_LAB_MENU",
        )

        runtime = FakeRuntime()
        route = NovaNavigationCanaryRoute(
            runtime,
            _identity(),
            atlas_path=ATLAS_PATH,
            home_driver=FakeHomeDriver(),
            recognizer=RecognitionQueue(ambiguous),
            settle_seconds=0,
        )
        result = route.run()
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.reason, "initial_radial_ambiguous")
        self.assertEqual(runtime.inputs, [])

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


class NovaPraiseFastRevalidationTests(unittest.TestCase):
    def _enabled_prior(self, attempts: int = 6) -> NovaFrameRecognition:
        observation = NovaPraiseObservation(
            screen_state=NOVA_SCREEN,
            research_lab_identity=True,
            nova_control_visible=False,
            selected_nova=True,
            praise_enabled=True,
            praise_target_identity=NOVA_PRAISE_TARGET,
            praise_target_roi=NOVA_PRAISE_ROI,
            attempts_remaining=attempts,
            cooldown_active=False,
            cooldown_seconds=None,
            frame_sha256="a" * 64,
            captured_monotonic=1.0,
            overlay_state="none_observed",
            recognized=True,
        )
        return NovaFrameRecognition(
            observation,
            observation.frame_sha256,
            ((NOVA_PRAISE_TARGET, NOVA_PRAISE_ROI),),
            {"header_text": "nova", "body_text": "praise"},
        )

    def _frame(self, *, praise_red: bool) -> np.ndarray:
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        if praise_red:
            x0, y0, x1, y1 = NOVA_PRAISE_ROI
            frame[y0:y1, x0:x1] = (0, 0, 255)
        return frame

    def test_fast_revalidation_enables_when_prior_valid_and_red_present(self) -> None:
        prior = self._enabled_prior(attempts=6)

        def boom(*_args, **_kwargs):
            raise AssertionError("fast revalidation must not invoke OCR")

        with patch.object(nova_praise_vision.pytesseract, "image_to_string", boom), patch.object(
            nova_praise_vision.pytesseract, "image_to_data", boom
        ), patch.object(nova_praise_vision, "_text", boom), patch.object(
            nova_praise_vision, "_ocr_boxes", boom
        ):
            result = revalidate_nova_praise_frame_fast(
                self._frame(praise_red=True),
                prior=prior,
                captured_monotonic=2.5,
            )
        self.assertTrue(result.observation.praise_enabled)
        self.assertEqual(result.observation.attempts_remaining, 6)
        self.assertEqual(result.observation.praise_target_identity, NOVA_PRAISE_TARGET)
        self.assertEqual(result.observation.praise_target_roi, NOVA_PRAISE_ROI)
        self.assertEqual(result.target(NOVA_PRAISE_TARGET), NOVA_PRAISE_ROI)
        self.assertEqual(result.observation.captured_monotonic, 2.5)
        self.assertTrue(result.diagnostics.get("fast_revalidation"))
        self.assertGreaterEqual(float(result.diagnostics["praise_red_ratio"]), 0.08)
        self.assertFalse(any(key.endswith("_text") for key in result.diagnostics))

    def test_fast_revalidation_fail_closed_without_red_or_invalid_prior(self) -> None:
        prior = self._enabled_prior()
        missing = revalidate_nova_praise_frame_fast(
            self._frame(praise_red=False),
            prior=prior,
            captured_monotonic=2.5,
        )
        self.assertFalse(missing.observation.praise_enabled)
        self.assertEqual(missing.targets, ())
        self.assertEqual(missing.observation.screen_state, "UNKNOWN")

        disabled_prior = NovaFrameRecognition(
            replace(prior.observation, praise_enabled=False, praise_target_identity=""),
            prior.frame_sha256,
            (),
            {},
        )
        rejected = revalidate_nova_praise_frame_fast(
            self._frame(praise_red=True),
            prior=disabled_prior,
            captured_monotonic=2.5,
        )
        self.assertFalse(rejected.observation.praise_enabled)
        self.assertEqual(rejected.targets, ())


if __name__ == "__main__":
    unittest.main()
