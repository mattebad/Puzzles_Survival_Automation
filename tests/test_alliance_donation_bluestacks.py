from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from automation_service.native_execution import NativeFrameReference
from automation_service.registry import (
    ALLIANCE_DONATION_FLOW_ID,
    ALLIANCE_DONATION_MAX_INPUTS,
    ALLIANCE_DONATION_PRODUCT_ID,
    ALLIANCE_DONATION_PRODUCT_REVISION,
    ALLIANCE_DONATION_PROFILE_ID,
)
from safe_action_core import SafetyStore
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.alliance_donation_bluestacks import DonationSurface
from tasks.donation_disabled import (
    ALLIANCE_TECH_SCREEN,
    DONATION_TARGET,
    MAX_DONATIONS_PER_RESET,
    DonationObservation,
)
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID, BLUESTACKS_NATIVE_TARGET_PROVENANCE

from scripts import alliance_donation_bluestacks as route


@dataclass
class FakeActionResult:
    status: str
    reason: str
    state: str


class FakeSession:
    def __init__(self, runtime, owner: str):
        self.runtime = runtime
        self.owner = owner
        self.input_count = 0
        self.initial_observation: dict[str, object] | None = None
        self.terminal_status = "active"

    def run_action(self, *, action_class, label, capture, dispatch, recognize,
                   authorize=None, settled_successor=None, consequence_class=None, **_kwargs):
        before = capture(f"{label}-before")
        if authorize is not None:
            authorize(before)
        self.input_count += 1
        dispatch(before)
        after = capture(f"{label}-after")
        state = recognize(after)
        if str(state).lower() == "unknown" and settled_successor is not None:
            after = settled_successor()
            state = recognize(after)
        status = "completed" if str(state).lower() != "unknown" else (
            "effect_reconciliation_required" if "effect" in f"{action_class} {consequence_class}" else "unknown"
        )
        return FakeActionResult(status, "fake-native-successor", str(state))


class FakeRuntime:
    def __init__(self, directory: Path, monotonic_clock):
        self.session = directory
        self._monotonic_clock = monotonic_clock
        self.state = "HOME"
        self.hot_visible = False
        self.hot_tree_frames = 0
        self.current_hot_slug: str | None = None
        self.donation_target_slugs: list[str] = []
        self.donation_count = 0
        self.input_count = 0
        self.action_keys: set[str] = set()
        self.frame_actions: set[tuple[str, str, object]] = set()
        self.captures = 0
        self.hot_never = False
        self.recharge_countdown = False
        self.last_capture: CapturedNativeFrame | None = None

    def capture(self, _label: str) -> CapturedNativeFrame:
        self.captures += 1
        if self.state == "TECH_TREE":
            self.hot_tree_frames += 1
            if self.hot_tree_frames >= 2:
                self.hot_visible = True
        token = f"{self.captures}:{self.state}:{self.donation_count}".encode("ascii")
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        frame[0, 0, 0] = {
            "HOME": 1,
            "ALLIANCE_HOME": 2,
            "TECH_TREE": 3,
            "DONATION_PANEL": 4,
            "UNKNOWN": 5,
        }[self.state]
        captured = CapturedNativeFrame(
            frame=frame,
            png=token,
            sha256=hashlib.sha256(token).hexdigest(),
            captured_monotonic=self._monotonic_clock(),
            path=self.session / "frames" / f"{self.captures:04d}.png",
        )
        self.last_capture = captured
        return captured

    def tap(self, source, *, target_identity, target_roi, action_key, action_class="navigation", consequential=False):
        if action_key in self.action_keys:
            raise AssertionError("fake native runtime received a duplicate action key")
        self.action_keys.add(action_key)
        self.frame_actions.add((source.sha256, target_identity, target_roi))
        self.input_count += 1
        if target_identity == "home-nav:alliance":
            self.state = "ALLIANCE_HOME"
        elif target_identity == "alliance:tech-entry":
            self.state = "TECH_TREE"
            self.hot_visible = False
            self.hot_tree_frames = 0
        elif target_identity.startswith("alliance-tech:hot:"):
            self.state = "DONATION_PANEL"
        elif target_identity == DONATION_TARGET:
            if self.current_hot_slug is None:
                raise AssertionError("fake native donation has no freshly bound HOT target")
            self.donation_target_slugs.append(self.current_hot_slug)
            self.donation_count += 1
        else:
            raise AssertionError(f"unexpected fake native target: {target_identity}")

    def back(self, source, *, action_key, target_identity):
        self.action_keys.add(action_key)
        self.frame_actions.add((source.sha256, target_identity, None))
        self.input_count += 1
        self.state = {
            "DONATION_PANEL": "TECH_TREE",
            "TECH_TREE": "ALLIANCE_HOME",
            "ALLIANCE_HOME": "HOME",
        }[self.state]

    def swipe(self, source, *, start, end, action_key, target_identity, duration_ms=400) -> None:
        raise AssertionError("fake runtime swipe must be configured for a reveal scenario")


@dataclass(frozen=True)
class _FakeIdentity:
    account_id: str = "synthetic-account"
    server_id: str = "synthetic-server"
    reset_id: str = "game-day-2023-11-14"


class FakeContext:
    def __init__(self, directory: Path, store: SafetyStore, *, hot_never: bool = False):
        self.utc_now = 1_700_000_000.0
        self.monotonic_now = 0.0
        self.identity = _FakeIdentity()
        self.flow_id = ALLIANCE_DONATION_FLOW_ID
        self.product_id = ALLIANCE_DONATION_PRODUCT_ID
        self.product_revision = ALLIANCE_DONATION_PRODUCT_REVISION
        self.runtime_profile_id = ALLIANCE_DONATION_PROFILE_ID
        self.occurrence_key = "occ:synthetic-alliance-donation"
        self.owner = "automation-service:alliance-donation"
        self.max_inputs = ALLIANCE_DONATION_MAX_INPUTS
        self.max_actions = MAX_DONATIONS_PER_RESET
        self.settle_seconds = 0.0
        self.action_store = store
        self.runtime = FakeRuntime(directory, self.monotonic_clock_now)
        self.runtime.hot_never = hot_never
        self.session = FakeSession(self.runtime, self.owner)
        self.monotonic_clock = self.monotonic_clock_now
        self.checkpoints = 0
        self.identity_checks = 0
        self.initial_frame = self.runtime.capture("initial")
        self.clean_home_bound = False

    def utc_clock(self):
        return self.utc_now

    def monotonic_clock_now(self):
        self.monotonic_now += 0.01
        return self.monotonic_now

    def checkpoint(self):
        self.checkpoints += 1

    def validate_identity(self):
        self.identity_checks += 1

    def capture_reference(self, path, expected_sha256=None):
        captured = next((frame for frame in [self.initial_frame] if frame.path == path), None)
        if captured is None:
            captured = self.runtime.last_capture
        if captured is None:
            raise AssertionError("fake runtime has no retained capture")
        if expected_sha256 is not None and captured.sha256 != expected_sha256:
            raise AssertionError("unexpected fake capture digest")
        reference = NativeFrameReference(
            frame_path=f"frames/{captured.path.name}",
            frame_sha256=captured.sha256,
            observed_utc="2023-11-14T00:00:00Z",
            capture_ordinal=self.runtime.captures,
        )
        return captured, reference

    def bind_initial_observation(self, frame=None, *, extra=None):
        captured = self.initial_frame if frame is None else frame
        self.clean_home_bound = captured is self.initial_frame or captured.sha256 == self.initial_frame.sha256
        self.session.initial_observation = {"frame_sha256": captured.sha256, **dict(extra or {})}
        return self.session.initial_observation


def _surface_for(context: FakeContext, captured: CapturedNativeFrame, *, reset_id: str, evidence_ref: str):
    code = int(captured.frame[0, 0, 0])
    state = {1: "HOME", 2: "ALLIANCE_HOME", 3: "TECH_TREE", 4: "DONATION_PANEL"}.get(code, "UNKNOWN")
    if state == "HOME":
        return DonationSurface(state, captured.sha256, evidence_ref)
    if state == "ALLIANCE_HOME":
        return DonationSurface(state, captured.sha256, evidence_ref, "alliance:tech-entry", (100, 450, 500, 540))
    if state == "TECH_TREE":
        visible = context.runtime.hot_visible and not getattr(context.runtime, "hot_never", False)
        if not visible:
            return DonationSurface(state, captured.sha256, evidence_ref, reason="waiting_for_auto_hot_scroll")
        slug = f"alliance-hot-tech-{context.runtime.donation_count + 1}"
        context.runtime.current_hot_slug = slug
        return DonationSurface(state, captured.sha256, evidence_ref,
                               f"alliance-tech:hot:{slug}", (170, 360, 650, 455),
                               f"Alliance HOT Tech {context.runtime.donation_count + 1}", slug,
                               hot_roi=(160, 350, 230, 390))
    if state == "DONATION_PANEL":
        count = context.runtime.donation_count
        target_roi = (430, 620, 690, 710)
        donation = DonationObservation(
            screen_state=ALLIANCE_TECH_SCREEN,
            auto_hot_marker=True,
            tech_identity=f"Alliance HOT Tech {count + 1}",
            target_identity=DONATION_TARGET,
            target_roi=target_roi,
            panel_bounds=(40, 300, 760, 850),
            control_class="DONATE",
            donate_control_visible=True,
            control_enabled=True,
            quantity=1,
            resource_identity="STEEL",
            resource_known=True,
            donation_amount=1000,
            resource_balance=50_000 - count * 1000,
            available_attempts=20 - count,
            attempt_capacity=20,
            active_recharge_timer=True,
            # A live recharge countdown advances with every capture while attempts remain available.
            next_attempt_available_in_seconds=(3_600 - context.runtime.captures
                                               if getattr(context.runtime, "recharge_countdown", False) else None),
            tech_points=2_000 + count * 550,
            reward_signature=(250, 250, 250, 250),
            game_day_id=reset_id,
            target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
            source_frame_sha256=captured.sha256,
            evidence_refs=(evidence_ref,),
            overlay_state="none",
            runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
            recognized=True,
        )
        slug = f"alliance-hot-tech-{count + 1}"
        context.runtime.current_hot_slug = slug
        return DonationSurface(state, captured.sha256, evidence_ref, DONATION_TARGET, target_roi,
                               donation.tech_identity, slug, donation,
                               premium_roi=(100, 620, 320, 710), reason="current_hot_panel")
    return DonationSurface("UNKNOWN", captured.sha256, evidence_ref, reason="unknown")


class AllianceDonationNativeSmokeTests(unittest.TestCase):
    def _context(self, directory: Path, store: SafetyStore, *, hot_never: bool = False):
        return FakeContext(directory, store, hot_never=hot_never)

    def test_canonical_fake_native_smoke_waits_for_auto_hot_and_caps_ten(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                owner = "automation-service:alliance-donation"
                store.acquire_lease(owner, 1_700_000_000.0, 3600.0)
                context = self._context(Path(directory), store)
                with patch.object(route, "_home_alliance_target", return_value=("home-nav:alliance", (600, 1213, 680, 1280))), \
                     patch.object(route, "recognize_surface", side_effect=lambda captured, **kwargs: _surface_for(context, captured, **kwargs)), \
                     patch.object(route.time, "sleep", return_value=None):
                    result = route.run_alliance_donation(context, {})
                self.assertEqual(result["status"], "complete_for_reset", msg=f"route result: {result}")
                self.assertEqual(result["donation_transport_calls"], 10)
                self.assertEqual(result["committed_action_count"], 10)
                self.assertEqual(result["daily_committed_action_count"], 10)
                self.assertTrue(result["terminal_home_verified"])
                self.assertEqual(context.runtime.donation_count, 10)
                self.assertEqual(len(context.runtime.donation_target_slugs), 10)
                self.assertEqual(len(set(context.runtime.donation_target_slugs)), 10)
                self.assertTrue(context.clean_home_bound)
                self.assertEqual(context.runtime.state, "HOME")
                actions = store.list_actions_for_task(ALLIANCE_DONATION_FLOW_ID)
                self.assertEqual(sum(row["final_status"] == "confirmed" for row in actions), 10)
                self.assertEqual(len({row["action_key"] for row in actions}), 10)
            finally:
                store.close()

    def test_recharge_countdown_tick_between_captures_keeps_consecutive_donations_available(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                owner = "automation-service:alliance-donation"
                store.acquire_lease(owner, 1_700_000_000.0, 3600.0)
                context = self._context(Path(directory), store)
                context.runtime.recharge_countdown = True
                with patch.object(route, "_home_alliance_target", return_value=("home-nav:alliance", (600, 1213, 680, 1280))), \
                     patch.object(route, "recognize_surface", side_effect=lambda captured, **kwargs: _surface_for(context, captured, **kwargs)), \
                     patch.object(route.time, "sleep", return_value=None):
                    result = route.run_alliance_donation(context, {})
                self.assertEqual(result["status"], "complete_for_reset", msg=f"route result: {result}")
                self.assertEqual(result["donation_transport_calls"], 10)
                self.assertEqual(context.runtime.donation_count, 10)
                actions = store.list_actions_for_task(ALLIANCE_DONATION_FLOW_ID)
                self.assertEqual(sum(row["final_status"] == "confirmed" for row in actions), 10)
            finally:
                store.close()

    def test_quote_equality_ignores_countdown_only_while_attempts_are_available(self):
        base = route.DonationObservation(
            screen_state=ALLIANCE_TECH_SCREEN, auto_hot_marker=True, tech_identity="Alliance HOT Tech 1",
            target_identity=DONATION_TARGET, target_roi=(430, 620, 690, 710), panel_bounds=(40, 300, 760, 850),
            control_class="DONATE", donate_control_visible=True, control_enabled=True, quantity=1,
            resource_identity="STEEL", resource_known=True, donation_amount=1000, resource_balance=50_000,
            available_attempts=3, attempt_capacity=20, active_recharge_timer=True,
            next_attempt_available_in_seconds=900, game_day_id="game-day-2023-11-14",
            target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE, source_frame_sha256="a" * 64,
            evidence_refs=("native-frame://frames/0001.png",), overlay_state="none",
            runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID, recognized=True,
        )
        from dataclasses import replace
        self.assertTrue(route._same_donation_facts(base, replace(base, next_attempt_available_in_seconds=899)))
        self.assertFalse(route._same_donation_facts(base, replace(base, next_attempt_available_in_seconds=899,
                                                                  resource_balance=49_000)))
        self.assertFalse(route._same_donation_facts(base, replace(base, available_attempts=4)))
        exhausted = replace(base, available_attempts=0)
        self.assertFalse(route._same_donation_facts(exhausted, replace(exhausted, next_attempt_available_in_seconds=899)))
    def test_unseen_auto_hot_marker_blocks_and_returns_home_without_donating(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            owner = "automation-service:alliance-donation"
            store.acquire_lease(owner, 1_700_000_000.0, 3600.0)
            context = self._context(Path(directory), store, hot_never=True)
            with patch.object(route, "MAX_AUTO_HOT_WAIT_SECONDS", 0.0), \
                 patch.object(route, "_home_alliance_target", return_value=("home-nav:alliance", (600, 1213, 680, 1280))), \
                 patch.object(route, "recognize_surface", side_effect=lambda captured, **kwargs: _surface_for(context, captured, **kwargs)), \
                 patch.object(route.time, "sleep", return_value=None):
                result = route.run_alliance_donation(context, {})
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["donation_transport_calls"], 0)
            self.assertEqual(context.runtime.donation_count, 0)
            self.assertTrue(result["terminal_home_verified"])
            self.assertEqual(context.runtime.state, "HOME")
            store.close()

    def test_failed_tech_entry_returns_from_current_alliance_context_without_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                context = self._context(Path(directory), store)
                original = route._navigation_action

                def navigate(*args, **kwargs):
                    if kwargs["label"] == "open-alliance-tech":
                        return None
                    return original(*args, **kwargs)

                with patch.object(route, "_navigation_action", side_effect=navigate), \
                     patch.object(route, "_home_alliance_target", return_value=("home-nav:alliance", (600, 1213, 680, 1280))), \
                     patch.object(route, "recognize_surface", side_effect=lambda captured, **kwargs: _surface_for(context, captured, **kwargs)):
                    result = route.run_alliance_donation(context, {})
                self.assertEqual(result["reason"], "alliance_donation_tech_entry_successor_unproven")
                self.assertTrue(result["terminal_home_verified"])
                self.assertEqual(context.runtime.input_count, 2)  # One entry and one safe Back.
                self.assertEqual(context.runtime.donation_count, 0)
            finally:
                store.close()

    def test_changed_before_back_refuses_input(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                context = self._context(Path(directory), store)
                context.runtime.state = "ALLIANCE_HOME"
                captured = context.runtime.capture("known-menu")
                surface = _surface_for(context, captured, reset_id=context.identity.reset_id, evidence_ref="known")
                context.runtime.state = "UNKNOWN"
                with patch.object(route, "recognize_surface", side_effect=lambda captured, **kwargs: _surface_for(context, captured, **kwargs)):
                    with self.assertRaisesRegex(RuntimeError, "Back source"):
                        route._back_action(context, surface)
                self.assertEqual(context.runtime.input_count, 0)
                self.assertEqual(context.session.input_count, 0)
                self.assertEqual(context.runtime.donation_count, 0)
            finally:
                store.close()


class AllianceDonationActualFrameTests(unittest.TestCase):
    fixture = Path(__file__).parent / "fixtures" / "alliance_donation_menu" / "donation77-0004.png"

    def _captured(self, frame=None, *, fixture=None):
        png = (fixture or self.fixture).read_bytes()
        if frame is not None:
            encoded, data = cv2.imencode(".png", frame)
            self.assertTrue(encoded)
            png = data.tobytes()
        decoded_frame = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR) if frame is None else frame
        if decoded_frame is None:
            raise AssertionError("donation fixture did not decode")
        return CapturedNativeFrame(
            frame=decoded_frame,
            png=png, sha256=hashlib.sha256(png).hexdigest(), captured_monotonic=1.0, path=self.fixture,
        )

    def test_native_clipped_header_back_art_and_shared_war_line_bind_only_tech_row(self):
        captured = self._captured()
        self.assertEqual(captured.sha256, "cc2efdf9f7962daf973b99756a8c644a56528ee4984c30d1d4142c3bcf9984e9")
        # Old body crop loses the title; full-width title OCR includes the Back/border art.
        body = route._words(captured.frame, (0, 35, 800, 1195))
        self.assertFalse(any(route._normalize(line.text) == "alliance" for line in route._lines(body) if line.roi[1] < 150))
        surface = route.recognize_surface(captured, reset_id="game-day-2026-11-08", evidence_ref="fixture")
        self.assertEqual(surface.state, "ALLIANCE_HOME")
        self.assertEqual(surface.target_identity, "alliance:tech-entry")
        self.assertEqual(surface.target_roi, (436, 611, 629, 659))
        self.assertIsNone(surface.donation)

    def test_body_alliance_tech_cannot_substitute_for_missing_current_header(self):
        frame = self._captured().frame.copy()
        frame[0:70, 200:600] = 0
        captured = self._captured(frame)
        surface = route.recognize_surface(captured, reset_id="d", evidence_ref="mutated")
        self.assertEqual(surface.state, "UNKNOWN")
        self.assertIsNone(surface.target_roi)

    def test_exact_title_not_header_confusable_or_substring(self):
        captured = self._captured()
        for title, expected in (("Alliance Help", "UNKNOWN"), ("Alliance Tech Upgrade", "UNKNOWN"),
                                ("Back Alliance", "UNKNOWN"), ("Alliance Tech", "TECH_TREE")):
            with self.subTest(title=title):
                def words(_frame, roi, **_kwargs):
                    if roi == route.SCREEN_TITLE_ROI:
                        return (route.TextWord(title, (280, 17, 520, 44), (1, 1, 1), 95),)
                    return ()
                with patch.object(route, "_words", side_effect=words):
                    surface = route.recognize_surface(captured, reset_id="d", evidence_ref="fixture")
                self.assertEqual(surface.state, expected)
                self.assertIsNone(surface.target_roi)  # No invented HOT binding.

    def _clipped_hot(self, frame=None):
        fixture = self.fixture.with_name("donation77-0028-clipped-hot.png")
        return self._captured(frame, fixture=fixture)

    def test_actual_bottom_hot_requests_reveal_without_guessing_identity(self):
        captured = self._clipped_hot()
        self.assertEqual(captured.sha256, "82d9cb255eda50c886c8870c0cd611e9345b0b9092b973094dc927a01e2d44c4")
        surface = route.recognize_surface(captured, reset_id="game-day-2026-11-08", evidence_ref="retained")
        self.assertEqual(surface.state, "TECH_TREE")
        self.assertEqual(surface.reason, "clipped_hot_requires_reveal")
        self.assertIsNotNone(surface.hot_roi)
        self.assertIsNone(surface.target_roi)
        self.assertIsNone(surface.tech_slug)
        self.assertIsNone(surface.donation)
        with tempfile.TemporaryDirectory() as directory:
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                context = FakeContext(Path(directory), store)
                calls = []
                context.runtime.capture = lambda _label: captured
                context.runtime.swipe = lambda source, **kwargs: calls.append((source, kwargs))
                context.runtime.last_capture = captured
                after = route._reveal_clipped_hot(context, surface)
                self.assertIsNone(after)  # Static fake transport cannot prove an offscreen identity.
                self.assertEqual(len(calls), 1)
                self.assertEqual(context.session.input_count, 1)
                self.assertEqual(context.runtime.donation_count, 0)
                self.assertEqual(store.list_actions_for_task(ALLIANCE_DONATION_FLOW_ID), [])
                source, gesture = calls[0]
                self.assertEqual(source.sha256, captured.sha256)
                self.assertEqual(gesture["duration_ms"], 500)
                self.assertGreater(gesture["start"][1], gesture["end"][1])
                self.assertLessEqual(gesture["start"][1] - gesture["end"][1], 320)
                self.assertEqual(gesture["target_identity"], "alliance-tech:reveal-current-clipped-hot")
            finally:
                store.close()

    def test_no_hot_wrong_context_and_ambiguous_hot_refuse_reveal_input(self):
        original = self._clipped_hot()
        source = route.recognize_surface(original, reset_id="d", evidence_ref="retained")
        variants = {}
        no_hot = original.frame.copy()
        no_hot[1205:1265, 410:545] = 0
        variants["no_hot"] = no_hot
        wrong = original.frame.copy()
        wrong[0:70, 200:600] = 0
        variants["wrong_context"] = wrong
        ambiguous = original.frame.copy()
        ambiguous[1215:1260, 217:339] = original.frame[1215:1260, 417:539]
        variants["ambiguous"] = ambiguous
        for name, frame in variants.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                captured = self._clipped_hot(frame)
                surface = route.recognize_surface(captured, reset_id="d", evidence_ref="mutated")
                self.assertIsNone(surface.target_roi)
                self.assertIsNone(surface.hot_roi)
                store = SafetyStore(Path(directory) / "actions.sqlite3")
                try:
                    context = FakeContext(Path(directory), store)
                    context.runtime.last_capture = captured
                    context.runtime.capture = lambda _label: captured
                    with self.assertRaisesRegex(RuntimeError, "reveal source changed"):
                        route._reveal_clipped_hot(context, source)
                    self.assertEqual(context.session.input_count, 0)
                    self.assertEqual(context.runtime.input_count, 0)
                    self.assertEqual(context.runtime.donation_count, 0)
                finally:
                    store.close()



if __name__ == "__main__":
    unittest.main()
