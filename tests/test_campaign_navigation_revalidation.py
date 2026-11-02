"""A slow map plan needs a new source, without running the atlas planner again."""
from contextlib import ExitStack
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import bluestacks_campaign_ap as live
from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
from tasks.campaign_atlas_chapter_nav import AtlasChapterNavDecision
from tasks.campaign_atlas_vision import OrbTranslationBackend, RegistrationMeasurement
from tasks.campaign_auto_battle import CampaignAction, CampaignAutoBattleConfig, CampaignRouteObservation, CampaignScreen, CampaignStage
from tasks.campaign_auto_battle_runtime import CampaignRuntimeCommand
from tasks.campaign_auto_battle_vision import CampaignFrameRecognition


STAGE = CampaignStage(1, 15, 9)
PAN = (540, 740, 260, 740, 350)


def registration(**changes):
    return replace(RegistrationMeasurement("translation", np.eye(3), 1.0, 0.0, 80, 80, 1.0, "measured", 0.0),
                   **changes)


def recognized(frame, *, action=CampaignAction.NAVIGATE_CHAPTER, targets=(), **changes):
    values = dict(screen=CampaignScreen.TIER_MAP if action is CampaignAction.NAVIGATE_CHAPTER else CampaignScreen.CHAPTER_MAP,
                  selected_tier=1, chapter_number=15 if action is CampaignAction.NAVIGATE_STAGE else None,
                  chapter_navigation_available=True, stage_navigation_available=True, ap_current=120)
    values.update(changes)
    return CampaignFrameRecognition(CampaignRouteObservation(**values), hashlib.sha256(frame.tobytes()).hexdigest(),
                                     tuple(targets), {})


class NavigationDevice:
    def __init__(self, frames):
        self.frames = frames
        self.captures = 0
        self.inputs = []

    def capture_png(self):
        frame = self.frames[min(self.captures, len(self.frames) - 1)]
        self.captures += 1
        success, png = cv2.imencode(".png", frame)
        assert success
        return png.tobytes()

    def dispatch_swipe(self, start, end, duration=500):
        self.inputs.append(("swipe", start, end, duration))

    def dispatch_tap(self, point):
        self.inputs.append(("tap", point))


class CampaignNavigationRevalidationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.ordinal = 0
        self.stack.enter_context(patch.object(LocalBlueStacksRuntime, "connect",
                                             side_effect=AssertionError("device access forbidden")))
        self.stack.enter_context(patch("tasks.campaign_atlas_chapter_nav.resolve_atlas_chapter_navigation",
                                      side_effect=AssertionError("revalidation must not rerun the atlas planner")))

    def runtime(self, frames=None, *, max_age=30):
        if frames is None:
            before = np.full((1280, 800, 3), 40, np.uint8)
            after = before.copy()
            after[5, 5] = 80
            frames = [before, after]
        device = NavigationDevice(frames)
        runtime = LocalBlueStacksRuntime(device, self.root / f"runtime-{self.ordinal}", execute=True,
                                        frame_max_age_seconds=max_age)
        runtime.max_inputs = 16
        self.ordinal += 1
        return runtime, device

    def refresh(self, runtime, source, command, *, source_targets=(), fresh_targets=(), fresh_changes=None, observe=None):
        action = command.action
        recognition = recognized(source.frame, action=action, targets=source_targets)
        return live._revalidate_campaign_navigation(
            runtime, source, recognition, command, STAGE,
            observe=observe or (lambda capture: recognized(capture.frame, action=action, targets=fresh_targets,
                                                          **(fresh_changes or {}))))

    @staticmethod
    def pan():
        return CampaignRuntimeCommand(CampaignAction.NAVIGATE_CHAPTER, "swipe", "atlas-directed pan", swipe=PAN)

    @staticmethod
    def send(runtime, source, command):
        if command.kind == "swipe":
            x0, y0, x1, y1, duration = command.swipe
            runtime.swipe(source, start=(x0, y0), end=(x1, y1), duration_ms=duration, action_key="navigation")
        else:
            runtime.tap(source, target_identity=command.target_identity, target_roi=command.target_roi,
                        action_key="navigation")

    def test_expensive_planner_runs_once_and_transport_uses_actual_new_capture(self):
        runtime, device = self.runtime(max_age=0.1)
        captures = []
        capture = runtime.capture
        def record(label):
            found = capture(label)
            captures.append(found)
            return found
        def plan(*_args, **_kwargs):
            time.sleep(0.15)
            return AtlasChapterNavDecision("swipe", "measured atlas pan", swipe=PAN, pan_direction="left",
                                           distance_to_screen_center_px=500, localization_support=("anchor",))
        config = CampaignAutoBattleConfig(STAGE, ap_cost=14, ap_budget=14, max_runs=1)
        with patch.object(runtime, "capture", side_effect=record), \
                patch.object(runtime, "swipe", wraps=runtime.swipe) as dispatch, \
                patch.object(live, "recognize_campaign_frame", side_effect=lambda frame, *_args, **_kwargs: recognized(frame)), \
                patch("tasks.campaign_atlas_chapter_nav.resolve_atlas_chapter_navigation", side_effect=plan) as planner, \
                patch.object(OrbTranslationBackend, "measure", return_value=registration()):
            with self.assertRaises(live.CampaignApRunError):
                live.run_campaign_ap_route(runtime, config, checkpoint=lambda: None, maximum_steps=1,
                                           post_input_delay=0, sleep=lambda _seconds: None)
        self.assertEqual(planner.call_count, 1)
        self.assertEqual(len(captures), 2)
        self.assertGreater(captures[1].captured_monotonic - captures[0].captured_monotonic, runtime.frame_max_age_seconds)
        self.assertIs(dispatch.call_args.args[0], captures[1])
        self.assertEqual(device.inputs, [("swipe", PAN[:2], PAN[2:4], PAN[4])])
        rows = [json.loads(line) for line in runtime.events.read_text().splitlines()]
        evidence = next(row for row in rows if row["type"] == "navigation_revalidation")
        self.assertEqual(evidence["proposal_captured_monotonic"], captures[0].captured_monotonic)
        self.assertEqual(evidence["immediate_captured_monotonic"], captures[1].captured_monotonic)
        self.assertEqual(evidence["proposal_sha256"], captures[0].sha256)
        self.assertEqual(evidence["immediate_sha256"], captures[1].sha256)
        transported = next(row for row in rows if row["type"] == "dispatch")
        self.assertEqual(transported["source_sha256"], captures[1].sha256)

    def test_tap_rebinds_intersecting_current_control_without_replanning(self):
        runtime, device = self.runtime()
        source = runtime.capture("proposal")
        identity, old_roi, new_roi = "campaign-stage-1-15-9", (300, 500, 360, 560), (304, 502, 364, 562)
        command = CampaignRuntimeCommand(CampaignAction.NAVIGATE_STAGE, "tap", "selected stage",
                                          target_identity=identity, target_roi=old_roi)
        with patch.object(OrbTranslationBackend, "measure", return_value=registration()):
            current, fresh, rebound = self.refresh(runtime, source, command, source_targets=((identity, old_roi),),
                                                    fresh_targets=((identity, new_roi),))
        self.send(runtime, current, rebound)
        self.assertEqual(rebound.target_identity, command.target_identity)
        self.assertEqual(rebound.target_roi, new_roi)
        self.assertEqual(device.inputs, [("tap", (334, 532))])
        self.assertGreater(current.captured_monotonic, source.captured_monotonic)
        self.assertEqual(fresh.frame_sha256, hashlib.sha256(current.frame.tobytes()).hexdigest())

    def test_changed_map_context_or_ap_blocks_before_input(self):
        for changes in ({"screen": CampaignScreen.HOME_BASE}, {"recognized": False},
                        {"overlay_state": "unknown"}, {"selected_tier": 2},
                        {"chapter_navigation_available": False}, {"ap_current": 119}):
            with self.subTest(changes=changes):
                runtime, device = self.runtime()
                source = runtime.capture("proposal")
                with patch.object(OrbTranslationBackend, "measure", return_value=registration()):
                    with self.assertRaises(RuntimeError):
                        self.refresh(runtime, source, self.pan(), fresh_changes=changes)
                self.assertEqual(device.inputs, [])
                self.assertEqual(runtime.input_count, 0)

    def test_translation_uncertain_geometry_and_unknown_registration_block_input(self):
        for measurement in (registration(translation_px=12), registration(residual_px=7),
                            registration(reason="insufficient_features", matches=0, inliers=0, residual_px=float("inf"))):
            with self.subTest(measurement=measurement):
                runtime, device = self.runtime()
                source = runtime.capture("proposal")
                with patch.object(OrbTranslationBackend, "measure", return_value=measurement):
                    with self.assertRaises(RuntimeError):
                        self.refresh(runtime, source, self.pan())
                self.assertEqual(device.inputs, [])
                self.assertEqual(runtime.input_count, 0)

    def test_wrong_native_geometry_is_rejected_before_input(self):
        runtime, device = self.runtime([np.ones((1280, 800, 3), np.uint8), np.ones((640, 400, 3), np.uint8)])
        source = runtime.capture("proposal")
        with self.assertRaises(RuntimeError):
            self.refresh(runtime, source, self.pan())
        self.assertEqual(device.captures, 2)
        self.assertEqual(device.inputs, [])
        self.assertEqual(runtime.input_count, 0)

    def test_immediate_capture_expiring_during_validation_cannot_dispatch_or_retry(self):
        runtime, device = self.runtime(max_age=0.1)
        source = runtime.capture("proposal")
        def slow_observe(captured):
            time.sleep(0.15)
            return recognized(captured.frame)
        with patch.object(OrbTranslationBackend, "measure", return_value=registration()):
            current, _fresh, command = self.refresh(runtime, source, self.pan(), observe=slow_observe)
        with self.assertRaises(RuntimeError):
            self.send(runtime, current, command)
        self.assertEqual(device.captures, 2)
        self.assertEqual(device.inputs, [])
        self.assertEqual(runtime.input_count, 0)

    def test_same_identity_elsewhere_cannot_replace_the_measured_control(self):
        runtime, device = self.runtime()
        source = runtime.capture("proposal")
        identity, old_roi = "campaign-stage-1-15-9", (300, 500, 360, 560)
        command = CampaignRuntimeCommand(CampaignAction.NAVIGATE_STAGE, "tap", "selected stage",
                                          target_identity=identity, target_roi=old_roi)
        with patch.object(OrbTranslationBackend, "measure", return_value=registration()):
            with self.assertRaises(RuntimeError):
                self.refresh(runtime, source, command, source_targets=((identity, old_roi),),
                             fresh_targets=((identity, (500, 650, 560, 710)),))
        self.assertEqual(device.inputs, [])
        self.assertEqual(runtime.input_count, 0)

    def test_retained_native_map_orb_accepts_unchanged_viewport_despite_footer_animation(self):
        frame = cv2.imread("tests/fixtures/campaign_tier_controls/panned-tier1-map.png")
        self.assertIsNotNone(frame)
        changed = frame.copy()
        changed[1245:1260, 10:40] = 255 - changed[1245:1260, 10:40]
        runtime, device = self.runtime([frame, changed])
        source = runtime.capture("proposal")
        current, _fresh, command = self.refresh(runtime, source, self.pan())
        self.assertNotEqual(current.sha256, source.sha256)
        self.assertEqual(command.swipe, PAN)
        self.send(runtime, current, command)
        self.assertEqual(len(device.inputs), 1)


if __name__ == "__main__":
    unittest.main()
