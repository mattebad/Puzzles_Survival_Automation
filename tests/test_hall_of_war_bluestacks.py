"""Replay-only Hall route tests; synthetic pixels are not native evidence or acceptance."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from safe_action_core import SafetyStore
from safe_action_core.store import LeaseError
from scripts.bluestacks_native_runtime import (
    CapturedNativeFrame,
    NATIVE_HEIGHT,
    NATIVE_WIDTH,
)
from scripts.hall_of_war_bluestacks import (
    BoundTarget,
    HallOfWarBoundary,
    HallOfWarRouteError,
    HallOfWarVision,
)
from tasks.hall_of_war import (
    DISPATCH_ACTION,
    DISPATCH_CONSEQUENCE,
    DISPATCH_POSTCONDITION,
    DISPATCH_SOURCE,
    DISPATCH_TARGET,
    REWARD_ACTION,
    REWARD_CONSEQUENCE,
    REWARD_POSTCONDITION,
    REWARD_SOURCE,
    REWARD_TARGET,
    action_key,
)


OWNER = "hall-of-war-native-replay"
RESET_ID = "game-day-2025-01-02"
NOW = 1_700_000_000.0


class _ReplayLock:
    owner = OWNER
    invocation_id = "hall-replay-invocation"

    def assert_held(self, owner, invocation_id):
        if (owner, invocation_id) != (self.owner, self.invocation_id):
            raise AssertionError("replay lock ownership changed")


class _ReplayRuntime:
    session = "hall-of-war-replay-session"

    def __init__(self, root: Path, *, effects_confirmed: bool) -> None:
        self.root = root
        self.effects_confirmed = effects_confirmed
        self.state = 0
        self.capture_count = 0
        self.tap_count = 0
        self.last_capture_monotonic = 100.0

    def capture(self, label: str) -> CapturedNativeFrame:
        self.capture_count += 1
        self.last_capture_monotonic += 0.1
        frame = np.full((NATIVE_HEIGHT, NATIVE_WIDTH, 3), self.state, dtype=np.uint8)
        # Unrelated animation must not make a fresh, still-bound target stale.
        frame[-1, -1] = self.capture_count % 256
        digest = hashlib.sha256(frame.tobytes()).hexdigest()
        path = self.root / f"{self.capture_count:03d}-{label}.png"
        return CapturedNativeFrame(
            frame, b"replay-only", digest, self.last_capture_monotonic, path
        )

    def measure_foreground_package(self) -> str:
        return "com.global.ztmslg"

    def tap(self, _before, *, action_class: str, **_kwargs) -> None:
        self.tap_count += 1
        if self.effects_confirmed:
            self.state = 1 if action_class == "combat" else 2


class _ReplaySession:
    owner = OWNER
    input_limit = 24

    def __init__(self, runtime: _ReplayRuntime) -> None:
        self.runtime_input_lock = _ReplayLock()
        self.runtime = runtime
        self.input_count = 0

    def observe(self, capture, *, label):
        return capture(label)

    def run_action(
        self,
        *,
        action_class,
        label,
        capture,
        dispatch,
        recognize,
        authorize=None,
        settled_successor=None,
        **_kwargs,
    ):
        before = self.observe(capture, label=f"{label}-immediate-before")
        if authorize is not None:
            authorize(before)
        self.input_count += 1
        dispatch(before)
        after = self.observe(capture, label=f"{label}-immediate-post")
        state = recognize(after)
        if str(state).lower() == "unknown" and settled_successor is not None:
            after = settled_successor()
            state = recognize(after)
        return SimpleNamespace(status=state, action_class=action_class)


class _ReplayVision:
    def formation_signature(self, _frame):
        return ("a" * 64,) * 5

    @staticmethod
    def roi_sha256(_frame, roi):
        return hashlib.sha256(repr(roi).encode("ascii")).hexdigest()


def _route(root: Path, *, effects_confirmed: bool):
    runtime = _ReplayRuntime(root, effects_confirmed=effects_confirmed)
    session = _ReplaySession(runtime)
    store = SafetyStore(root / "safety.sqlite3")
    store.acquire_lease(OWNER, NOW, 3600.0)
    route = object.__new__(HallOfWarBoundary)
    route.session = session
    route.runtime = runtime
    route.store = store
    route.game_day_id = RESET_ID
    route.monotonic_clock = lambda: runtime.last_capture_monotonic
    route.wall_clock = lambda: NOW
    route.validate_identity = lambda: None
    route.vision = _ReplayVision()
    route.settle_seconds = 0.0
    route.result = {}
    return route, runtime, store


def _perform(route: HallOfWarBoundary, category: str):
    if category == "dispatch":
        target = DISPATCH_TARGET
        return route._perform_canonical_action(
            category=category,
            action_id=f"hall-of-war-dispatch:{RESET_ID}",
            key=action_key(
                category="dispatch", runtime_scope="replay-slot", account_id="account",
                server_id="server", reset_id=RESET_ID,
            ),
            semantic_action=DISPATCH_ACTION,
            source_state=DISPATCH_SOURCE,
            target_identity=target,
            consequence=DISPATCH_CONSEQUENCE,
            postcondition=DISPATCH_POSTCONDITION,
            binder=lambda _frame: BoundTarget(target, (100, 100, 220, 160)),
            postcondition_checker=lambda frame: int(frame[0, 0, 0]) == 1,
            action_class="combat",
        )
    target = REWARD_TARGET
    return route._perform_canonical_action(
        category=category,
        action_id=f"hall-of-war-reward:{RESET_ID}",
        key=action_key(
            category="reward", runtime_scope="replay-slot", account_id="account",
            server_id="server", reset_id=RESET_ID,
        ),
        semantic_action=REWARD_ACTION,
        source_state=REWARD_SOURCE,
        target_identity=target,
        consequence=REWARD_CONSEQUENCE,
        postcondition=REWARD_POSTCONDITION,
        binder=lambda _frame: BoundTarget(target, (300, 800, 700, 900)),
        postcondition_checker=lambda frame: int(frame[0, 0, 0]) == 2,
        action_class="reward",
    )


class HallOfWarNativeReplayTests(unittest.TestCase):
    def test_observed_lose_damage_and_continue_establish_participation(self):
        vision = HallOfWarVision()
        frame = np.zeros((NATIVE_HEIGHT, NATIVE_WIDTH, 3), dtype=np.uint8)
        continuation = (260, 1210, 530, 1245)
        with patch.object(vision, "text", return_value="LOSE Dmg This Time: 2,166,282,036 Tap to continue"), patch.object(
            vision, "_phrase_boxes", return_value=(continuation,)
        ):
            self.assertEqual(vision.result_modal(frame), (True, 2_166_282_036))
            self.assertEqual(vision.bind_result_confirm(frame).target_roi, continuation)
        with patch.object(vision, "text", return_value="LOSE Tap to continue"), patch.object(
            vision, "_phrase_boxes", return_value=(continuation,)
        ):
            self.assertEqual(vision.result_modal(frame), (False, None))
            self.assertIsNone(vision.bind_result_confirm(frame))

    def test_vision_normalizes_unicode_and_recognizes_zombie_zero_page(self):
        vision = HallOfWarVision()
        frame = np.zeros((NATIVE_HEIGHT, NATIVE_WIDTH, 3), dtype=np.uint8)
        self.assertEqual(vision._normal("  TÓDAY's   Highest   Dmg  "), "today's highest dmg")
        labels = {
            vision._MENU_TITLE_BAND: ("zombie zero",),
            vision._MENU_DAMAGE_BAND: ("today's highest dmg: ?",),
            vision._MENU_REWARD_BAND: ("daily reward",),
            vision._MENU_FOOTER_BAND: (),
        }

        def lines(_frame, band, _colour):
            return tuple(SimpleNamespace(text=text, roi=band) for text in labels[band])

        with patch.object(vision, "_text_lines", side_effect=lines):
            self.assertTrue(vision.zombie_zero_page(frame))
            self.assertIsNone(vision.today_highest_damage(frame))
            labels[vision._MENU_TITLE_BAND] = ()
            self.assertFalse(vision.zombie_zero_page(frame))

    def test_real_executor_and_temporary_safety_store_confirm_both_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            route, runtime, store = _route(Path(directory), effects_confirmed=True)
            try:
                dispatch = _perform(route, "dispatch")
                reward = _perform(route, "reward")
                self.assertEqual(dispatch[:2], ("confirmed", 1))
                self.assertEqual(reward[:2], ("confirmed", 1))
                dispatch_row = store.get_action_by_key(
                    action_key(
                        category="dispatch", runtime_scope="replay-slot", account_id="account",
                        server_id="server", reset_id=RESET_ID,
                    )
                )
                reward_row = store.get_action_by_key(
                    action_key(
                        category="reward", runtime_scope="replay-slot", account_id="account",
                        server_id="server", reset_id=RESET_ID,
                    )
                )
                self.assertEqual(dispatch_row["final_status"], "confirmed")
                self.assertEqual(reward_row["final_status"], "confirmed")
                self.assertEqual(runtime.tap_count, 2)
                self.assertEqual(route.result["dispatch_transport_calls"], 1)
                self.assertEqual(route.result["reward_claim_transport_calls"], 1)
            finally:
                store.release_lease(OWNER, NOW)
                store.close()

    def test_verified_switch_dispatch_reward_prefix_fits_visit_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            route, runtime, store = _route(Path(directory), effects_confirmed=True)
            try:
                self.assertEqual(_perform(route, "dispatch")[:2], ("confirmed", 1))
                self.assertEqual(_perform(route, "reward")[:2], ("confirmed", 1))
                route.result["talent_switch_transport_calls"] = 1
                runtime.input_count = route.session.input_count + 1
                route.session.input_count = runtime.input_count
                result = route._account(1, 1, 3)
                self.assertEqual(result["committed_action_count"], 3)
                self.assertEqual(result["hall_of_war_dispatch_count"], 3)
                self.assertTrue(result["accounting_verified"])
                self.assertFalse(result["effect_reconciliation_required"])
            finally:
                store.release_lease(OWNER, NOW)
                store.close()

    def test_unknown_reward_retains_confirmed_dispatch_across_store_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route, runtime, store = _route(root, effects_confirmed=True)
            lease_held = True
            try:
                self.assertEqual(_perform(route, "dispatch")[:2], ("confirmed", 1))
                runtime.effects_confirmed = False
                self.assertEqual(_perform(route, "reward")[:2], ("unresolved", 1))
                store.release_lease(OWNER, NOW)
                lease_held = False
                store.close()
                store = SafetyStore(root / "safety.sqlite3")
                with self.assertRaises(LeaseError):
                    store.acquire_lease(OWNER, NOW, 3600.0)
                route.store = store
                dispatch_key = action_key(
                    category="dispatch", runtime_scope="replay-slot", account_id="account",
                    server_id="server", reset_id=RESET_ID,
                )
                self.assertEqual(store.get_action_by_key(dispatch_key)["final_status"], "confirmed")
                reward_key = action_key(
                    category="reward", runtime_scope="replay-slot", account_id="account",
                    server_id="server", reset_id=RESET_ID,
                )
                self.assertEqual(store.get_action_by_key(reward_key)["final_status"], "unresolved")
                with self.assertRaises(HallOfWarRouteError):
                    _perform(route, "reward")
                self.assertEqual(runtime.tap_count, 2)
            finally:
                try:
                    if lease_held:
                        store.release_lease(OWNER, NOW)
                finally:
                    store.close()

    def test_unknown_dispatch_is_durable_and_same_action_cannot_be_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            route, runtime, store = _route(Path(directory), effects_confirmed=False)
            try:
                state, calls, _payload = _perform(route, "dispatch")
                self.assertEqual((state, calls), ("unresolved", 1))
                key = action_key(
                    category="dispatch", runtime_scope="replay-slot", account_id="account",
                    server_id="server", reset_id=RESET_ID,
                )
                row = store.get_action_by_key(key)
                self.assertEqual(row["final_status"], "unresolved")
                with self.assertRaises(HallOfWarRouteError):
                    _perform(route, "dispatch")
                self.assertEqual(runtime.tap_count, 1)
                self.assertEqual(route.result["dispatch_transport_calls"], 1)
            finally:
                store.release_lease(OWNER, NOW)
                store.close()


if __name__ == "__main__":
    unittest.main()
