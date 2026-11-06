"""Known startup recovery on the caller's real native ledger, without a device."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from scripts import startup_recovery as recovery
from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
from scripts.startup_surface_recognition import (
    SCARLETT_SAFE_BACK_ROI, SCARLETT_SAFE_BACK_TARGET_IDENTITY,
    SCARLETT_THREE_DAY_PACK, is_exact_scarlett_recognition,
)
from tests.support.contextual_startup import (
    ARTWORK, COMMERCIAL, HOME, LOST, MODAL, MOVED, PngDevice, RETRY, RETRY_ART, SCARLETT,
    UNKNOWN, VIP, VIP_ROI, marker, reset_popup, startup_surface, windows_short_path,
)


class CheckpointStop(RuntimeError):
    pass


class ContextualStartupRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.device = PngDevice()
        self.runtime = LocalBlueStacksRuntime(self.device, self.root / "native", execute=True)
        self.runtime.max_inputs = 8
        forbidden = AssertionError("recovery must reuse its caller's runtime and ownership")
        for target in (
            "scripts.startup_recovery.SafetyStore",
            "safe_action_core.SafetyStore",
            "scripts.bluestacks_native_runtime.ADBRunner",
            "scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect",
            "scripts.navigation_development_boundary.DevelopmentSession",
            "scripts.navigation_development_boundary.RuntimeInputLock.acquire",
        ):
            self.stack.enter_context(patch(target, side_effect=forbidden))
        self.stack.enter_context(patch.object(
            recovery, "recognize_startup_surface", side_effect=startup_surface,
        ))
        self.stack.enter_context(patch.object(
            recovery, "recognize_reset_popup", side_effect=reset_popup,
        ))

    def source(self, *states):
        self.device.frames = list(states)
        return self.runtime.capture("route-source")

    def recover(self, captured, *, action_key="route:startup-back", context="HOME_BASE", successor=None):
        return recovery.recover_contextual_startup_overlay(
            self.runtime, captured, source_context=context,
            recognize_successor=successor or (lambda current: marker(current.frame) == HOME),
            action_key=action_key, settle_seconds=0, sleep=lambda _seconds: None,
        )

    def rows(self, kind):
        return [row for row in (
            json.loads(line) for line in self.runtime.events.read_text(encoding="utf-8").splitlines()
        ) if row["type"] == kind]

    def test_clear_known_successor_returns_same_capture_without_input_or_new_capture(self):
        captured = self.source(HOME)
        result = self.recover(captured)
        self.assertIs(result.settled_frame, captured)
        self.assertTrue(result.resume_ready)
        self.assertEqual(result.input_count, 0)
        self.assertEqual(self.runtime.input_count, 0)
        self.assertEqual(len(self.rows("capture")), 1)
        self.assertEqual(self.rows("dispatch"), [])

    def test_current_scarlett_artwork_variance_uses_fresh_back_and_route_successor(self):
        captured = self.source(SCARLETT, ARTWORK, HOME)
        original = (captured.png, captured.sha256, captured.captured_monotonic, captured.path)
        self.assertTrue(is_exact_scarlett_recognition(startup_surface(captured.frame, captured.png)))
        result = self.recover(captured)
        self.assertTrue(result.resume_ready)
        self.assertTrue(result.dismissed)
        self.assertEqual((result.input_count, self.runtime.input_count), (1, 1))
        before, immediate, post = self.rows("capture")
        self.assertEqual(before["sha256"], captured.sha256)
        self.assertNotEqual(immediate["sha256"], captured.sha256)
        self.assertGreater(immediate["captured_monotonic"], captured.captured_monotonic)
        self.assertNotEqual(immediate["path"], str(captured.path))
        self.assertGreater(post["captured_monotonic"], immediate["captured_monotonic"])
        dispatch, = self.rows("dispatch")
        self.assertEqual(dispatch["source_sha256"], immediate["sha256"])
        self.assertEqual(dispatch["target_identity"], SCARLETT_SAFE_BACK_TARGET_IDENTITY)
        self.assertEqual(tuple(dispatch["target_roi"]), SCARLETT_SAFE_BACK_ROI)
        self.assertEqual(dispatch["action_class"], "navigation")
        self.assertFalse(dispatch["consequential"])
        self.assertEqual(self.rows("reconcile")[0]["status"], "confirmed")
        self.assertEqual((captured.png, captured.sha256, captured.captured_monotonic, captured.path), original)

    def test_unknown_commercial_and_modal_cannot_be_overridden_by_route_callback(self):
        for state in (COMMERCIAL, MODAL):
            with self.subTest(state=state):
                captured = self.source(state)
                result = self.recover(captured, successor=lambda _current: True)
                self.assertFalse(result.resume_ready)
                self.assertEqual(result.input_count, 0)
                self.assertEqual(self.runtime.input_count, 0)
        self.assertEqual(self.rows("dispatch"), [])

    def test_manual_source_context_stops_known_scarlett_without_input(self):
        captured = self.source(SCARLETT, ARTWORK, HOME)
        result = self.recover(captured, context="login", successor=lambda _current: True)
        self.assertFalse(result.resume_ready)
        self.assertEqual(result.input_count, 0)
        self.assertEqual(self.runtime.input_count, 0)
        self.assertEqual(self.rows("dispatch"), [])

    def test_changed_or_lost_back_on_fresh_capture_never_dispatches(self):
        for state in (MOVED, LOST):
            with self.subTest(state=state):
                captured = self.source(SCARLETT, state, HOME)
                result = self.recover(captured)
                self.assertFalse(result.resume_ready)
                self.assertEqual(result.input_count, 0)
                self.assertEqual(self.runtime.input_count, 0)
        self.assertEqual(self.rows("dispatch"), [])

    def test_cap_duplicate_key_and_prior_scarlett_target_deny_additional_input(self):
        for condition in ("cap", "key", "target"):
            with self.subTest(condition=condition):
                device = PngDevice()
                device.frames = [SCARLETT, ARTWORK, RETRY, HOME]
                runtime = LocalBlueStacksRuntime(device, self.root / condition, execute=True)
                seed = runtime.capture("earlier-source")
                runtime.tap(
                    seed, target_identity=SCARLETT_SAFE_BACK_TARGET_IDENTITY if condition == "target" else "prior-navigation",
                    target_roi=SCARLETT_SAFE_BACK_ROI, action_key="used-key",
                    action_class="navigation", consequential=False,
                )
                if condition == "cap":
                    runtime.max_inputs = runtime.input_count
                current = runtime.capture("current-scarlett")
                result = recovery.recover_contextual_startup_overlay(
                    runtime, current, source_context="HOME_BASE",
                    recognize_successor=lambda frame: marker(frame.frame) == HOME,
                    action_key="used-key" if condition == "key" else "new-key",
                    settle_seconds=0, sleep=lambda _seconds: None,
                )
                self.assertFalse(result.resume_ready)
                self.assertEqual(result.input_count, 0)
                self.assertEqual(runtime.input_count, 1)
                self.assertEqual(len(device.taps), 1)

    def test_unknown_post_is_unresolved_and_new_key_cannot_repeat_scarlett_back(self):
        captured = self.source(SCARLETT, ARTWORK, UNKNOWN, RETRY, RETRY_ART, HOME)
        result = self.recover(captured)
        self.assertFalse(result.resume_ready)
        self.assertEqual((result.input_count, self.runtime.input_count), (1, 1))
        self.assertEqual(self.rows("reconcile")[0]["status"], "unresolved")
        current = self.runtime.capture("scarlett-after-unknown")
        retried = self.recover(current, action_key="different-key-after-unknown")
        self.assertFalse(retried.resume_ready)
        self.assertEqual(retried.input_count, 0)
        self.assertEqual(self.runtime.input_count, 1)
        self.assertEqual(len(self.device.taps), 1)

    def test_checkpoint_stop_propagates_before_any_dispatch(self):
        captured = self.source(SCARLETT, ARTWORK, HOME)

        def stop():
            raise CheckpointStop("operator stopped the current route")

        self.runtime.checkpoint = stop
        with self.assertRaises(CheckpointStop):
            self.recover(captured)
        self.assertEqual(self.runtime.input_count, 0)
        self.assertEqual(self.rows("dispatch"), [])

    def test_transport_uncertainty_retains_one_attempt_and_unresolved_ledger(self):
        captured = self.source(SCARLETT, ARTWORK, HOME)
        self.device.transport_failure = True
        result = self.recover(captured)
        self.assertFalse(result.resume_ready)
        self.assertEqual((result.input_count, self.runtime.input_count), (1, 1))
        self.assertEqual(len(self.rows("dispatch")), 1)
        self.assertEqual(len(self.device.taps), 1)
        self.assertEqual(self.rows("reconcile")[0]["status"], "unresolved")

    def test_two_distinct_overlays_use_the_same_ledger_and_only_final_route_successor(self):
        for states, identities in (
            ((VIP, VIP, SCARLETT, ARTWORK, HOME), ("VIP_POINTS_GET_PTS", SCARLETT_THREE_DAY_PACK)),
            ((SCARLETT, ARTWORK, VIP, VIP, HOME), (SCARLETT_THREE_DAY_PACK, "VIP_POINTS_GET_PTS")),
        ):
            with self.subTest(identities=identities):
                self.runtime = LocalBlueStacksRuntime(self.device, self.root / identities[0], execute=True)
                self.runtime.max_inputs = 8
                captured = self.source(*states)
                seen_successors = []
                result = self.recover(captured, successor=lambda frame: (
                    seen_successors.append(marker(frame.frame)) or marker(frame.frame) == HOME))
                self.assertTrue(result.resume_ready)
                self.assertEqual((result.input_count, self.runtime.input_count), (2, 2))
                self.assertEqual([step.popup_identity for step in result.steps], list(identities))
                self.assertEqual(set(seen_successors), {HOME})
                first, second = result.steps
                self.assertIs(first.settled_frame, second.source_frame)
                self.assertEqual(len({step.action_key for step in result.steps}), 2)
                self.assertEqual(len(self.rows("dispatch")), 2)
                self.assertEqual([row["status"] for row in self.rows("reconcile")], ["confirmed", "confirmed"])
                for step in result.steps:
                    self.assertLess(step.source_frame.captured_monotonic, step.immediate_before.captured_monotonic)
                    self.assertLess(step.immediate_before.captured_monotonic, step.settled_frame.captured_monotonic)
                    self.assertNotEqual(step.source_frame.path, step.immediate_before.path)
                    self.assertNotEqual(step.immediate_before.path, step.settled_frame.path)
                    self.assertTrue(step.confirmed)
                    self.assertEqual(step.input_count, 1)

    def test_vip_close_uses_the_rebound_immediate_geometry(self):
        shifted = 94
        roi = (280, 780, 540, 870)
        original = reset_popup
        def popup(frame):
            if marker(frame) == shifted:
                return {**original(np.full_like(frame, VIP)), "target": roi}
            return original(frame)
        captured = self.source(VIP, shifted, HOME)
        with patch.object(recovery, "recognize_reset_popup", side_effect=popup):
            result = self.recover(captured)
        self.assertTrue(result.resume_ready)
        self.assertEqual(self.device.taps, [(410, 825)])
        self.assertEqual(result.steps[0].target_roi, roi)

    def test_second_overlay_requires_a_new_immediate_capture(self):
        captured = self.source(VIP, VIP, SCARLETT)
        capture = self.runtime.capture
        retained = {}
        def current(label):
            if label == "contextual-startup-scarlett-before":
                return retained["post"]
            frame = capture(label)
            if label == "contextual-vip-popup-post":
                retained["post"] = frame
            return frame
        with patch.object(self.runtime, "capture", side_effect=current):
            result = self.recover(captured)
        self.assertFalse(result.resume_ready)
        self.assertEqual((result.input_count, self.runtime.input_count, len(self.device.taps)), (1, 1, 1))

    def test_step_mapping_accepts_windows_aliases_but_keeps_foreign_paths_outside_session(self):
        captured = self.source(VIP, VIP, HOME)
        step, = self.recover(captured).steps
        alias_session = windows_short_path(self.runtime.session)
        self.assertEqual(alias_session.resolve(), self.runtime.session.resolve())
        expected = step.to_mapping(self.runtime.session.resolve())
        self.assertEqual(step.to_mapping(alias_session), expected)
        alias_source = windows_short_path(step.source_frame.path)
        aliased = replace(step, source_frame=replace(step.source_frame, path=alias_source))
        self.assertEqual(aliased.to_mapping(self.runtime.session), expected)
        foreign = self.root / "foreign" / step.source_frame.path.name
        foreign.parent.mkdir()
        foreign.write_bytes(step.source_frame.png)
        with self.assertRaises(ValueError):
            replace(step, source_frame=replace(step.source_frame, path=foreign)).to_mapping(alias_session)

    def test_step_mapping_does_not_erase_a_symlink_reference_when_resolving_paths(self):
        captured = self.source(VIP, VIP, HOME)
        step, = self.recover(captured).steps
        original = os.lstat
        for linked in (step.source_frame.path, step.source_frame.path.parent, self.runtime.session):
            linked_paths = {linked, linked.resolve()}
            with self.subTest(linked=linked), patch("os.lstat",
                    side_effect=lambda path, *args, **kwargs: (
                        os.stat_result((stat.S_IFLNK | 0o777, *original(path, *args, **kwargs)[1:]))
                        if Path(path) in linked_paths else original(path, *args, **kwargs)
                    )):
                with self.assertRaises(ValueError):
                    step.to_mapping(self.runtime.session)

    def test_step_mapping_rejects_a_link_above_the_session_root(self):
        captured = self.source(VIP, VIP, HOME)
        step, = self.recover(captured).steps
        expected = step.to_mapping(self.runtime.session)
        original = os.lstat
        trusted_parent = self.runtime.session.parent
        trusted_parent_paths = {trusted_parent, trusted_parent.resolve()}
        with patch("os.lstat", side_effect=lambda path, *args, **kwargs: (
                os.stat_result((stat.S_IFLNK | 0o777, *original(path, *args, **kwargs)[1:]))
                if Path(path) in trusted_parent_paths else original(path, *args, **kwargs)
        )):
            with self.assertRaises(ValueError):
                step.to_mapping(self.runtime.session)
        self.assertEqual(step.to_mapping(self.runtime.session), expected)

    def test_a_windows_alias_of_the_same_file_is_not_a_fresh_capture(self):
        captured = self.source(HOME)
        alias = windows_short_path(captured.path)
        later_alias = replace(captured, path=alias, captured_monotonic=captured.captured_monotonic + 1)
        self.assertFalse(recovery._contextual_startup_frame_valid(later_alias, after=captured))

    def test_known_intermediate_is_not_ready_when_second_input_is_unavailable(self):
        self.runtime.max_inputs = 1
        captured = self.source(VIP, VIP, SCARLETT, ARTWORK, HOME)
        result = self.recover(captured, successor=lambda _frame: True)
        self.assertFalse(result.resume_ready)
        self.assertEqual((result.input_count, self.runtime.input_count), (1, 1))
        self.assertEqual(marker(result.settled_frame.frame), SCARLETT)
        self.assertEqual(len(result.steps), 1)
        self.assertTrue(result.steps[0].confirmed)
        self.assertEqual(len(self.device.taps), 1)

    def test_repeated_vip_or_unknown_intermediate_never_issues_another_input(self):
        for post in (VIP, COMMERCIAL, MODAL, UNKNOWN):
            with self.subTest(post=post):
                self.runtime = LocalBlueStacksRuntime(self.device, self.root / str(post), execute=True)
                self.runtime.max_inputs = 8
                captured = self.source(VIP, VIP, post, SCARLETT, ARTWORK, HOME)
                result = self.recover(captured)
                self.assertFalse(result.resume_ready)
                self.assertEqual((result.input_count, self.runtime.input_count), (1, 1))
                self.assertEqual(len(result.steps), 1)
                self.assertFalse(result.steps[0].confirmed)
                self.assertEqual(self.rows("reconcile")[0]["status"], "unresolved")

    def test_second_transport_uncertainty_retains_both_attempts_and_never_promotes_home(self):
        original = self.device.dispatch_tap
        def dispatch(point):
            self.device.transport_failure = len(self.device.taps) == 1
            original(point)
        self.device.dispatch_tap = dispatch
        captured = self.source(VIP, VIP, SCARLETT, ARTWORK, HOME)
        result = self.recover(captured)
        self.assertFalse(result.resume_ready)
        self.assertEqual((result.input_count, self.runtime.input_count), (2, 2))
        self.assertEqual([step.confirmed for step in result.steps], [True, False])
        self.assertEqual([row["status"] for row in self.rows("reconcile")], ["confirmed", "unresolved"])
        self.assertEqual(len(self.device.taps), 2)

    def test_exact_vip_still_closes_on_the_same_native_runtime(self):
        captured = self.source(VIP, VIP, HOME)
        result = self.recover(captured)
        self.assertTrue(result.resume_ready)
        self.assertEqual((result.input_count, self.runtime.input_count), (1, 1))
        dispatch, = self.rows("dispatch")
        self.assertEqual(dispatch["target_identity"], recovery.VIP_RESET_TARGET)
        self.assertEqual(tuple(dispatch["target_roi"]), VIP_ROI)
        self.assertEqual(self.device.taps, [(400, 825)])
        self.assertEqual(self.rows("reconcile")[0]["status"], "confirmed")


if __name__ == "__main__":
    unittest.main()
