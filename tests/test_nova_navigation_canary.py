"""Offline controller and retained-evidence tests for the no-Praise Nova canary."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
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
from tasks.home_atlas import (
    AmbiguityState,
    BuildingBinding,
    LocalizationResult,
    ZoomIdentity,
)
from tasks.home_atlas_vision import frame_digest
from tasks.nova_praise import (
    NOVA_INTERACTION_TARGET,
    NOVA_PRAISE_TARGET,
    NOVA_SCREEN,
    NovaPraiseObservation,
)
from tasks.nova_praise_vision import (
    NOVA_PRAISE_ROI,
    NovaFrameRecognition,
    ResearchLabTapProvenance,
    evaluate_research_lab_radial_evidence,
    recognize_nova_frame,
)
from tasks.runtime_identity import RuntimeIdentityAssurance, VerifiedRuntimeIdentity


ROOT = Path(__file__).resolve().parents[1]
ATLAS_PATH = ROOT / "tasks/assets/home_atlas/bluestacks/800x1280/atlas.json"
FIXTURE_ROOT = ROOT / "tests/fixtures/nova_praise_preflight"


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
        ((NOVA_INTERACTION_TARGET, (137, 631, 181, 675)),),
        {},
    )


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


class FakeRuntime:
    execute = True
    in_flight_action = None
    session = Path("nova-navigation-canary-test")

    def __init__(self) -> None:
        self.ordinal = 0
        self.inputs: list[tuple[str, dict[str, object]]] = []
        self.labels: list[str] = []

    def capture(self, label: str) -> CapturedNativeFrame:
        self.ordinal += 1
        self.labels.append(label)
        frame = np.zeros((1280, 800, 3), np.uint8)
        frame[0, 0] = (self.ordinal, 1, 1)
        payload = f"capture-{self.ordinal}".encode()
        return CapturedNativeFrame(
            frame,
            payload,
            hashlib.sha256(payload).hexdigest(),
            float(self.ordinal),
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
        self.ready = type("Ready", (), {})()

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
            _radial_recognition("a" * 64),
            _radial_recognition("b" * 64),
            _nova_recognition("c" * 64),
            _nova_recognition("d" * 64),
        )
        route = NovaNavigationCanaryRoute(
            runtime,
            _identity(),
            atlas_path=ATLAS_PATH,
            home_driver=FakeHomeDriver(),
            recognizer=recognizer,
            settle_seconds=0,
        )
        with patch.object(route, "_home_localized", side_effect=[False, True]):
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
            recognizer=RecognitionQueue(unbound),
            settle_seconds=0,
        )
        result = route.run()
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.reason, "research_lab_radial_not_bound")
        self.assertEqual([kind for kind, _ in runtime.inputs], ["tap"])
        self.assertEqual(result.praise_taps, 0)

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

    def test_retained_radial_requires_fresh_research_lab_provenance(self) -> None:
        manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
        fixture = manifest["fixtures"][0]
        path = FIXTURE_ROOT / fixture["path"]
        frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), fixture["file_sha256"])
        stale = recognize_nova_frame(
            frame,
            captured_monotonic=11.0,
            home_context_visible=True,
        )
        self.assertFalse(stale.observation.recognized)
        action = fixture["preceding_action"]
        provenance = ResearchLabTapProvenance(
            action["action_key"],
            action["target_identity"],
            action["source_sha256"],
            tuple(action["target_roi"]),
            10.0,
        )
        fresh = recognize_nova_frame(
            frame,
            captured_monotonic=11.0,
            research_lab_tap_provenance=provenance,
            home_context_visible=True,
        )
        self.assertEqual(fresh.observation.screen_state, "RESEARCH_LAB_MENU")
        self.assertTrue(fresh.observation.recognized)
        self.assertEqual(fresh.target(NOVA_INTERACTION_TARGET), (137, 631, 181, 675))

    def test_radial_composite_negative_controls_fail_closed(self) -> None:
        valid = {
            "source_frame_sha256": "a" * 64,
            "provenance_valid": True,
            "fresh_successor": True,
            "home_context_visible": True,
            "geometry_anchors": ("details", "upgrade", "research", "nova"),
            "ocr_terms": ("research", "bioenhancer"),
            "nova_target_roi": (137, 631, 181, 675),
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


if __name__ == "__main__":
    unittest.main()
