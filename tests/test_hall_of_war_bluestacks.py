"""Hall route regressions; retained frames test recognition, not live dispatch acceptance."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
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
    run_hall_of_war_native,
)
from tasks.hall_of_war import (
    AttemptState,
    RewardState,
    ChallengeObservation,
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
    def test_retained_lose_result_requires_attempt_damage_and_bottom_continuation(self):
        frames = (
            Path(__file__).resolve().parents[2] / "Puzzle_Survival_Runtime_POC"
            / ".local-captures" / "canonical-owner-replay-20261109T080850495633Z"
            / "zombie-zero-owned-radial-quote-reader-and-verified-formation"
            / "HALL-OF-WAR-ZOMBIE-ZERO-BLUESTACKS-INTEGRATION-20261109T132229643646Z-17d8dae5"
            / "hall-of-war-zombie-zero-20261109T132229721168Z" / "frames"
        )
        names = (
            "0068-hall-of-war-dispatch-immediate-post.png",
            "0069-hall-of-war-dispatch-settled.png",
            "0070-hall-of-war-dispatch-postcondition.png",
        )
        if not all((frames / name).is_file() for name in names):
            self.skipTest("immutable owner Hall dispatch result frames are not installed")
        vision = HallOfWarVision()
        for index, name in enumerate(names):
            with self.subTest(frame=name):
                frame = cv2.imread(str(frames / name), cv2.IMREAD_COLOR)
                self.assertIsNotNone(frame)
                if index == 0:
                    self.assertEqual(vision.result_modal(frame), (False, None))
                    continue
                self.assertEqual(vision.result_modal(frame), (True, 2_166_282_036))
                self.assertEqual(
                    vision.bind_result_confirm(frame).target_roi, (306, 1236, 494, 1259),
                )
        missing_damage = frame.copy()
        missing_damage[820:900] = 0
        self.assertEqual(vision.result_modal(missing_damage), (False, None))
        missing_continuation = frame.copy()
        missing_continuation[1200:] = 0
        self.assertEqual(vision.result_modal(missing_continuation), (False, None))

    def test_retained_radial_captions_ignore_only_outer_ocr_quotes(self):
        from scripts.home_atlas_bluestacks import (
            BlueStacksHomeLocalizer, bind_visible_building, load_home_atlas,
        )
        from scripts.hall_of_war_bluestacks import HALL_OF_WAR_ATLAS_BUILDING_ID, HALL_OF_WAR_RADIAL_TARGET

        root = Path(__file__).resolve().parents[1]
        frames = (
            root.parent / "Puzzle_Survival_Runtime_POC" / ".local-captures"
            / "canonical-owner-replay-20261109T080850495633Z"
            / "zombie-zero-visible-Hall-after-fenced-marker-review"
            / "HALL-OF-WAR-ZOMBIE-ZERO-BLUESTACKS-INTEGRATION-20261109T124804785389Z-f6fb79a4"
            / "hall-of-war-zombie-zero-20261109T124804880070Z" / "frames"
        )
        names = (
            "0030-hall-of-war-open-building-immediate-before.png",
            "0032-hall-of-war-open-building-settled.png",
            "0033-hall-of-war-radial-current.png",
        )
        if not all((frames / name).is_file() for name in names):
            self.skipTest("immutable owner Hall radial replay frames are not installed")
        atlas_path = root / "tasks/assets/home_atlas/bluestacks/800x1280/atlas.json"
        atlas = load_home_atlas(atlas_path)
        localizer = BlueStacksHomeLocalizer(atlas, atlas_path)
        vision = HallOfWarVision()
        entry = None
        for name in names:
            with self.subTest(frame=name):
                frame = cv2.imread(str(frames / name), cv2.IMREAD_COLOR)
                self.assertIsNotNone(frame)
                localization = localizer.localize(frame)
                binding = bind_visible_building(
                    frame, localization, atlas.lookup_building(HALL_OF_WAR_ATLAS_BUILDING_ID),
                    home_is_clean=vision.is_clean_home,
                )
                self.assertIsNotNone(binding)
                if entry is None:
                    entry = binding
                    self.assertIsNone(vision.radial_captions(frame, binding.screen_anchor))
                    continue
                self.assertTrue(vision.same_hall_anchor(entry, binding))
                captions = vision.radial_captions(frame, binding.screen_anchor)
                self.assertIsNotNone(captions)
                self.assertEqual(set(captions), {"Details", "Upgrade", "Military Operation", "Zombie Zero"})
                self.assertEqual(captions["Zombie Zero"], (423, 807, 497, 845))
                target = vision.radial_target(frame, captions)
                self.assertIsNotNone(target)
                self.assertEqual(target.target_identity, HALL_OF_WAR_RADIAL_TARGET)

    def test_retained_selection_toast_expiry_preserves_verified_formation(self):
        frames = (
            Path(__file__).resolve().parents[2] / "Puzzle_Survival_Runtime_POC"
            / ".local-captures" / "canonical-owner-replay-20261109T080850495633Z"
            / "zombie-zero-stored-daily-bound-supervised-replay"
            / "HALL-OF-WAR-ZOMBIE-ZERO-BLUESTACKS-INTEGRATION-20261109T110736197462Z-4717e3e8"
            / "hall-of-war-zombie-zero-20261109T110736273415Z" / "frames"
        )
        names = (
            "0063-hall-of-war-select-troop-set-one-settled.png",
            "0064-hall-of-war-troop-set-one-applied.png",
        )
        if not all((frames / name).is_file() for name in names):
            self.skipTest("immutable owner Hall replay frames are not installed")
        captures = []
        for index, name in enumerate(names):
            path = frames / name
            encoded = path.read_bytes()
            frame = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
            self.assertIsNotNone(frame)
            captures.append(CapturedNativeFrame(
                frame, encoded, hashlib.sha256(encoded).hexdigest(), 100.0 + index, path,
            ))
        selected, current = captures
        route = object.__new__(HallOfWarBoundary)
        route.vision = HallOfWarVision()
        self.assertTrue(route.vision.troop_set_one_applied(selected.frame))
        self.assertEqual(route.vision.hero_count(selected.frame), 5)
        self.assertFalse(route.vision.troop_set_one_applied(current.frame))
        self.assertEqual(route.vision.troop_counts(current.frame), (160200, 160200))
        route._last_successor_capture = selected
        route.result = {"verified_navigation": ["select-troop-set-one"]}
        route._record_troop_set_one_formation(current)
        self.assertTrue(route.formation_proof["applied"])
        self.assertEqual(route.formation_proof["source_frame_sha256"], current.sha256)
        self.assertEqual(route.formation_proof["applied_toast_frame_sha256"], selected.sha256)
        self.assertEqual(route.result["troop_set_one"]["hero_count"], 5)
        self.assertEqual(route.formation_proof["current_troops"], 160200)

        route.result["verified_navigation"] = []
        with self.assertRaisesRegex(HallOfWarRouteError, "formation_or_current_troops"):
            route._record_troop_set_one_formation(current)
        route.result["verified_navigation"] = ["select-troop-set-one"]
        changed = current.frame.copy()
        x0, y0, _x1, _y1 = route.vision._HERO_RECTS[0]
        changed[y0, x0] ^= 255
        changed_capture = CapturedNativeFrame(
            changed, b"changed", "c" * 64, 102.0, current.path,
        )
        with self.assertRaisesRegex(HallOfWarRouteError, "formation_or_current_troops"):
            route._record_troop_set_one_formation(changed_capture)

    def test_immediate_dispatch_binding_preserves_positive_damage_and_manual_scope(self):
        route = object.__new__(HallOfWarBoundary)
        route.result = {"saved_military_verified": True}
        signature = ("a" * 64,) * 5
        route.formation_proof = {"formation_signature": signature}
        target = BoundTarget(DISPATCH_TARGET, (100, 100, 220, 160))
        route.vision = SimpleNamespace(
            dispatch_page=lambda _frame: True, troop_counts=lambda _frame: (160200, 160200),
            hero_count=lambda _frame: 5, formation_signature=lambda _frame: signature,
            bind_dispatch=lambda _frame: target,
        )
        observation = ChallengeObservation(
            page_identity="ZOMBIE_ZERO", page_exact=True, attempt=AttemptState.READY,
            saved_military_verified=True, troop_set_one_selected=True, troop_set_one_applied=True,
            five_heroes_populated=True, current_troops=160200, troop_capacity=160200,
            today_highest_damage=2_166_282_036, attempt_source_frame_sha256="a" * 64,
            dispatch_page_identity="ZOMBIE_ZERO_DISPATCH", dispatch_page_exact=True,
            attempt_ordinal=1, source_frame_sha256="b" * 64,
        )
        route.operator_request_id = None
        self.assertIsNone(route._bind_dispatch_target(None, observation))
        route.operator_request_id = "owner-supervised-hall-canary"
        self.assertEqual(route._bind_dispatch_target(None, observation), target)
        self.assertEqual(observation.today_highest_damage, 2_166_282_036)

    def test_manual_replay_keeps_confirmed_reset_dispatch_key_nonrepeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            route, runtime, store = _route(Path(directory), effects_confirmed=True)
            try:
                route.operator_request_id = "owner-supervised-hall-canary"
                self.assertEqual(_perform(route, "dispatch")[:2], ("confirmed", 1))
                repeated = _perform(route, "dispatch")
                self.assertEqual(repeated[:2], ("blocked", 0))
                self.assertEqual(runtime.tap_count, 1)
                self.assertEqual(route.result["dispatch_transport_calls"], 1)
            finally:
                store.release_lease(OWNER, NOW)
                store.close()

    def test_positive_manual_damage_and_claimed_reward_require_explicit_replay(self):
        for request_id in (None, "owner-supervised-hall-canary"):
            with self.subTest(request_id=request_id), tempfile.TemporaryDirectory() as directory:
                route, runtime, store = _route(Path(directory), effects_confirmed=True)
                try:
                    runtime.session = Path(directory)
                    runtime.input_count = 0
                    route.operator_request_id = request_id
                    route.dispatch_key = "fixed-reset-dispatch-key"
                    route.reward_key = "fixed-reset-reward-key"
                    route.vision = SimpleNamespace(
                        is_clean_home=lambda _frame: True,
                        zombie_zero_page=lambda _frame: True,
                        challenge_reward=lambda _frame: SimpleNamespace(reward=RewardState.CLAIMED),
                        bind_attack=lambda _frame: None,
                    )
                    route._home_binding = lambda: (None, None)
                    route._page_observation = lambda _page: (AttemptState.READY, 2_166_282_036)
                    route._hall_radial = lambda _page: SimpleNamespace(
                        recognized=True, radial_identity="hall-radial",
                        owning_facility=SimpleNamespace(facility_semantic_id="hall"),
                        source_frame=SimpleNamespace(semantic_sha256="a" * 64),
                        metadata={"entry_frame_sha256": "b" * 64},
                        controls=(SimpleNamespace(control_id="hall_of_war_zombie_zero", label="Zombie Zero"),),
                    )
                    navigation = []

                    def navigate(**kwargs):
                        navigation.append(kwargs["label"])
                        if kwargs["label"] == "open-dispatch":
                            raise HallOfWarRouteError("regression_stop_before_dispatch_navigation")

                    def return_home(**_kwargs):
                        route.result["terminal_home_verified"] = True
                        return True

                    route._navigation_tap = navigate
                    route._return_home = return_home
                    result = route.execute()
                    self.assertEqual("open-dispatch" in navigation, request_id is not None)
                    if request_id is None:
                        self.assertEqual(result["challenge_status"], "deferred_unexplained_prior_same_reset_use")
                        self.assertEqual(result["reward_status"], "already_claimed")
                    else:
                        self.assertIn("regression_stop_before_dispatch_navigation", result["reason"])
                    self.assertEqual(runtime.tap_count, 0)
                    self.assertEqual(result["dispatch_transport_calls"], 0)
                    self.assertEqual(result["reward_claim_transport_calls"], 0)
                finally:
                    store.release_lease(OWNER, NOW)
                    store.close()

    def test_manual_replay_rejects_mismatched_occurrence_before_checkpoint(self):
        def unexpected_checkpoint():
            self.fail("mismatched manual replay reached the live checkpoint")

        context = SimpleNamespace(
            occurrence_key="current-manual-occurrence", checkpoint=unexpected_checkpoint,
        )
        for arguments in (
            {"operator_request_id": "owner-canary"},
            {"operator_request_id": "owner-canary", "manual_occurrence_key": "other-occurrence"},
            {"operator_request_id": "", "manual_occurrence_key": context.occurrence_key},
            {"operator_request_id": "owner-canary", "manual_occurrence_key": context.occurrence_key,
             "allow_extra_dispatches": 10},
        ):
            with self.subTest(arguments=arguments), self.assertRaisesRegex(ValueError, "exact claimed manual occurrence"):
                run_hall_of_war_native(context, arguments)

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
            route.operator_request_id = "owner-supervised-hall-canary"
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
