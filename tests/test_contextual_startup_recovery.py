"""Known startup recovery on the caller's real native ledger, without a device."""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import startup_recovery as recovery
from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime, NATIVE_RUNTIME_PROFILE_ID
from scripts.startup_surface_recognition import (
    SCARLETT_EXPECTED_SUCCESSOR, SCARLETT_FORBIDDEN_PURCHASE_ROIS,
    SCARLETT_MAX_INPUTS, SCARLETT_SAFE_BACK_ROI, SCARLETT_SAFE_BACK_TARGET_IDENTITY,
    SCARLETT_THREE_DAY_PACK, is_exact_scarlett_recognition,
)


SCARLETT, ARTWORK, RETRY, RETRY_ART = 31, 71, 73, 74
MOVED, LOST, VIP, COMMERCIAL, MODAL, UNKNOWN, HOME = 81, 101, 91, 121, 161, 181, 211
VIP_ROI = (263, 781, 537, 869)


def marker(frame):
    return int(frame[200, 200, 0])


class PngDevice:
    def __init__(self):
        self.frames = []
        self.current = HOME
        self.taps = []
        self.transport_failure = False

    def capture_png(self):
        if self.frames:
            self.current = self.frames.pop(0)
        frame = np.full((1280, 800, 3), 17, np.uint8)
        frame[100:1200, :, :] = self.current
        ok, encoded = cv2.imencode(".png", frame)
        assert ok
        return encoded.tobytes()

    def dispatch_tap(self, point):
        self.taps.append(point)
        if self.transport_failure:
            raise RuntimeError("transport completion uncertain")


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
            recovery, "recognize_startup_surface", side_effect=self.startup_surface,
        ))
        self.stack.enter_context(patch.object(
            recovery, "recognize_reset_popup", side_effect=self.reset_popup,
        ))

    @staticmethod
    def startup_surface(frame, payload=None):
        state = marker(frame)
        if state not in {SCARLETT, ARTWORK, RETRY, RETRY_ART, MOVED, LOST}:
            return {"recognized": False, "commercial_looking": state == COMMERCIAL}
        payload = payload if payload is not None else cv2.imencode(".png", frame)[1].tobytes()
        digest = hashlib.sha256(payload).hexdigest()
        detail = {
            "recognized": True, "surface_identity": SCARLETT_THREE_DAY_PACK,
            "surface_kind": "full_page", "runtime_profile_id": NATIVE_RUNTIME_PROFILE_ID,
            "width": 800, "height": 1280, "frame_sha256": digest,
            "title_text": "scarlett 3-day pack", "title_identity": True,
            "semantic_evidence": (
                "title:Scarlett 3-Day Pack", "full_page_real_money_promotion",
                "visible_in_game_back_upper_left", "purchase_regions_excluded",
                "current_offer_benefits_and_three_day_rows", "current_first_topup_notice",
            ),
            "safe_exit_target_identity": SCARLETT_SAFE_BACK_TARGET_IDENTITY,
            "safe_exit_roi": SCARLETT_SAFE_BACK_ROI,
            "forbidden_purchase_rois": SCARLETT_FORBIDDEN_PURCHASE_ROIS,
            "purchase_exclusion_verified": True, "critical_roi_hashes": (("artwork", digest),),
            "page_context_verified": True, "measured_back_roi": (47, 0, 128, 59),
            "expected_successor": SCARLETT_EXPECTED_SUCCESSOR,
            "max_inputs": SCARLETT_MAX_INPUTS, "target_count": 1,
        }
        if state == MOVED:
            detail.update(safe_exit_roi=(200, 100, 320, 160), measured_back_roi=(207, 100, 280, 150))
        elif state == LOST:
            detail["measured_back_roi"] = None
        return detail

    @staticmethod
    def reset_popup(frame):
        if marker(frame) == VIP:
            return {
                "recognized": True, "popup_identity": "VIP_POINTS_GET_PTS",
                "target_identity": recovery.VIP_RESET_TARGET,
                "target": VIP_ROI, "target_center": (400, 825),
                "title_identity": True, "body_identity": True, "literal_close": True,
                "geometry_valid": True, "panel_present": True,
            }
        return {"recognized": False, "blocking_unknown_modal": marker(frame) == MODAL}

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
        self.assertTrue(is_exact_scarlett_recognition(self.startup_surface(captured.frame, captured.png)))
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
