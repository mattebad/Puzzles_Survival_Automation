"""Real core admission over distinct, immutable Survey planning/input captures."""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts import flow_delivery_campaign_atlas_bluestacks as survey
from tasks.campaign_atlas import InputBudgetCategory, SurveyPhase
from tasks.campaign_auto_battle import CampaignScreen


class _Runtime:
    def __init__(self, root, *, changed_control=False, immediate_time=101.0):
        self.session = root
        self.ordinal = 0
        self.frames = []
        self.taps = []
        self.changed_control = changed_control
        self.immediate_time = immediate_time

    def capture(self, label):
        self.ordinal += 1
        frame = np.zeros((1280, 800, 3), np.uint8)
        frame[10:30, 650:700] = self.ordinal * 30  # harmless HUD animation
        x = 130 if self.ordinal == 2 and self.changed_control else 120
        frame[220:280, x:x + 60] = 255
        ok, encoded = cv2.imencode(".png", frame)
        assert ok
        png = encoded.tobytes()
        path = self.session / f"{self.ordinal}-{label}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
        timestamp = 100.0 if self.ordinal == 1 else self.immediate_time if self.ordinal == 2 else 102.0
        captured = CapturedNativeFrame(frame, png, hashlib.sha256(png).hexdigest(), timestamp, path)
        self.frames.append(captured)
        return captured

    def tap(self, source, **kwargs):
        self.taps.append((source, kwargs))


class CampaignSurveyFreshnessTests(unittest.TestCase):
    def _run(self, *, changed_control=False, immediate_time=101.0, changed_source=False):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            runtime = _Runtime(root / "runtime", changed_control=changed_control,
                               immediate_time=immediate_time)
            planning = runtime.capture("planning")
            before_metadata = (planning.sha256, planning.captured_monotonic, planning.png)
            stack.enter_context(patch.object(survey.time, "monotonic", return_value=103.0))
            stack.enter_context(patch.object(survey.time, "sleep", return_value=None))
            operator = survey._SurveyOperator(root, runtime, "test-survey", lease_owner="test-owner")
            stack.callback(operator.close)

            def recognize(frame):
                is_immediate = frame[10, 650, 0] == 60
                state = CampaignScreen.UNKNOWN if changed_source and is_immediate else CampaignScreen.TIER_MAP
                return SimpleNamespace(observation=SimpleNamespace(screen=state, selected_tier=1))

            def bind(_recognition, _identity, *, frame):
                mask = cv2.inRange(frame[200:300, 100:220], (250, 250, 250), (255, 255, 255))
                x, y, width, height = cv2.boundingRect(mask)
                if not width or not height:
                    raise RuntimeError("unknown current control")
                return x + 100, y + 200, x + 100 + width, y + 200 + height

            stack.enter_context(patch.object(operator, "recognize", side_effect=recognize))
            stack.enter_context(patch.object(survey, "require_bound_survey_target", side_effect=bind))
            stack.enter_context(patch.object(survey, "_annotate_roi", return_value="annotation.png"))
            execute = stack.enter_context(patch.object(operator, "_execute_via_safe_action",
                                                       wraps=operator._execute_via_safe_action))
            issue = stack.enter_context(patch.object(operator.policy, "issue_capability",
                                                     wraps=operator.policy.issue_capability))
            failed = None
            try:
                operator.dispatch_bound_tap(
                    phase=SurveyPhase.DIFFICULTY_GEOMETRY_PAIR,
                    category=InputBudgetCategory.AUXILIARY, source_rel="runtime/planning.png",
                    before=planning, before_rel="runtime/planning.png", identity="campaign-tier-1",
                    action_key="test-tier", expected_successor=lambda result: result.observation.screen == CampaignScreen.TIER_MAP,
                )
            except RuntimeError as exc:
                failed = exc
            self.assertEqual((planning.sha256, planning.captured_monotonic, planning.png), before_metadata)
            if execute.called:
                proposal = execute.call_args.kwargs["proposal_observation"]
                immediate = execute.call_args.kwargs["observation"]
                self.assertEqual((proposal.frame_sha256, proposal.capture_completed_monotonic),
                                 (planning.sha256, 100.0))
                self.assertEqual((immediate.frame_sha256, immediate.capture_completed_monotonic),
                                 (runtime.frames[1].sha256, immediate_time))
            if issue.called:
                issued_source = issue.call_args.args[0].observation
                self.assertEqual((issued_source.frame_sha256, issued_source.capture_completed_monotonic),
                                 (runtime.frames[1].sha256, immediate_time))
            return failed, runtime.taps, runtime.frames

    def test_real_planning_and_input_metadata_are_preserved_through_core(self):
        failed, taps, frames = self._run()
        self.assertIsNone(failed)
        self.assertEqual(len(taps), 1)
        self.assertIs(taps[0][0], frames[1])
        self.assertNotEqual(frames[0].sha256, frames[1].sha256)
        self.assertEqual([item.captured_monotonic for item in frames], [100.0, 101.0, 102.0])

    def test_same_capture_time_does_not_become_fresh_by_arithmetic(self):
        failed, taps, frames = self._run(immediate_time=100.0)
        self.assertIsNotNone(failed)
        self.assertEqual(taps, [])
        self.assertEqual([item.captured_monotonic for item in frames], [100.0, 100.0])

    def test_changed_current_control_or_source_blocks_without_input(self):
        for changes in ({"changed_control": True}, {"changed_source": True}):
            with self.subTest(changes=changes):
                failed, taps, _frames = self._run(**changes)
                self.assertIsNotNone(failed)
                self.assertEqual(taps, [])
