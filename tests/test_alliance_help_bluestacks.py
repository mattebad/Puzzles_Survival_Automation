from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from safe_action_core import SafetyStore
from scripts import alliance_help_bluestacks as route
from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime, box_center
from tasks.alliance_help import (
    CONSEQUENCE, DAILY_REQUEST_LIMIT, HELP_ALL_TARGET_IDENTITY,
    INDIVIDUAL_TARGET_IDENTITY, POSTCONDITION, SEMANTIC_ACTION, SOURCE_STATE,
    HelpAction, HelpObservation, HelpPlan, HelpRequest, alliance_help_action_key,
    choose_help_action, confirmed_request_count, verified_request_delta,
)
from tasks.runtime_identity import derive_resource_runtime_identity, resource_fixed_runtime_binding


class AllianceHelpSemanticsTests(unittest.TestCase):
    def _observation(self, *, ids=("a" * 24,), at=1.0, balance=0, limit=50000,
                     success=False, no_requests=False, complete=False, pending=None,
                     all_count=None, all_free=True, source_fresh=True, overlay=True,
                     cost=False):
        requests = tuple(HelpRequest(item, (550, 260 + index * 80, 680, 310 + index * 80), True, True)
                         for index, item in enumerate(ids))
        return HelpObservation(
            screen_state=SOURCE_STATE, captured_at=at,
            frame_sha256=hashlib.sha256(f"frame:{at}:{balance}:{ids}".encode()).hexdigest(),
            overlay_clear=overlay, source_fresh=source_fresh, requests=requests,
            help_all_roi=(277, 1188, 523, 1268), help_all_free=all_free,
            exact_no_requests_message=no_requests, pending_count=pending,
            request_list_complete=complete, cost_marker_seen=cost,
            daily_alliance_coin_balance=balance, daily_alliance_coin_limit=limit,
            help_success_message=success, help_all_success_count=all_count,
        )

    def test_quota_and_exact_free_individual_selection(self):
        observation = self._observation(ids=("a" * 24, "b" * 24))
        plan = choose_help_action(observation, DAILY_REQUEST_LIMIT)
        self.assertEqual(plan.action, HelpAction.INDIVIDUAL)
        self.assertEqual(plan.target_identity, INDIVIDUAL_TARGET_IDENTITY)
        self.assertEqual(plan.request_ids, ("a" * 24,))
        self.assertEqual(plan.reason, "one_current_free_request_bounded_to_one")
        self.assertEqual(choose_help_action(observation, 0).action, HelpAction.STOP_QUOTA)
        self.assertEqual(choose_help_action(observation, DAILY_REQUEST_LIMIT + 1).action, HelpAction.UNKNOWN)

    def test_help_all_requires_explicit_complete_bounded_set(self):
        requests = ("a" * 24, "b" * 24, "c" * 24)
        incomplete = self._observation(ids=requests, complete=False, pending=3)
        self.assertEqual(choose_help_action(incomplete, 3, allow_help_all=True).action,
                         HelpAction.INDIVIDUAL)
        complete = self._observation(ids=requests, complete=True, pending=3)
        plan = choose_help_action(complete, 3, allow_help_all=True)
        self.assertEqual(plan.action, HelpAction.HELP_ALL)
        self.assertEqual(plan.target_identity, HELP_ALL_TARGET_IDENTITY)
        self.assertEqual(plan.request_ids, requests)
        self.assertEqual(choose_help_action(complete, 2, allow_help_all=True).action,
                         HelpAction.INDIVIDUAL)
        self.assertEqual(choose_help_action(complete, 3).action, HelpAction.INDIVIDUAL)

    def test_no_requests_message_wins_over_visible_help_all_and_costs_block(self):
        no_requests = self._observation(ids=(), no_requests=True, balance=1000)
        plan = choose_help_action(no_requests, 10, allow_help_all=True)
        self.assertEqual(plan.action, HelpAction.NO_REQUESTS)
        self.assertEqual(plan.reason, "exact_no_requests_message")
        missing = choose_help_action(self._observation(ids=(), balance=1000), 10)
        self.assertEqual(missing.action, HelpAction.FREE_HELP_DISAPPEARED)
        paid = choose_help_action(self._observation(cost=True), 10)
        self.assertEqual(paid.action, HelpAction.UNKNOWN)
        stale = choose_help_action(self._observation(source_fresh=False), 10)
        self.assertEqual(stale.action, HelpAction.UNKNOWN)
        capped = choose_help_action(self._observation(balance=50000), 10)
        self.assertEqual(capped.action, HelpAction.UNKNOWN)

    def test_list_disappearance_and_transport_alone_never_confirm(self):
        before = self._observation()
        plan = choose_help_action(before, 10)
        disappeared = self._observation(ids=(), at=2.0, balance=0)
        self.assertEqual(verified_request_delta(before, disappeared, plan=plan,
            remaining=10, transport_calls=1), 0)
        unchanged = self._observation(at=2.0, balance=0)
        self.assertEqual(verified_request_delta(before, unchanged, plan=plan,
            remaining=10, transport_calls=1), 0)
        positive_without_transport = self._observation(ids=(), at=2.0,
            balance=1000, success=True)
        self.assertEqual(verified_request_delta(before, positive_without_transport,
            plan=plan, remaining=10, transport_calls=0), 0)

    def test_one_request_requires_selected_identity_success_toast_and_positive_counter(self):
        before = self._observation(balance=0)
        plan = choose_help_action(before, 10)
        success = self._observation(ids=(), at=2.0, balance=1000, success=True)
        self.assertEqual(verified_request_delta(before, success, plan=plan,
            remaining=10, transport_calls=1), 1)
        selected_still_visible = self._observation(at=2.0, balance=1000, success=True)
        self.assertEqual(verified_request_delta(before, selected_still_visible,
            plan=plan, remaining=10, transport_calls=1), 0)
        wrong_cap = self._observation(ids=(), at=2.0, balance=1000,
            limit=60000, success=True)
        self.assertEqual(verified_request_delta(before, wrong_cap, plan=plan,
            remaining=10, transport_calls=1), 0)
        no_toast = self._observation(ids=(), at=2.0, balance=1000)
        self.assertEqual(verified_request_delta(before, no_toast, plan=plan,
            remaining=10, transport_calls=1), 0)

    def test_bounded_help_all_counts_only_exact_successor_delta(self):
        ids = ("a" * 24, "b" * 24, "c" * 24)
        before = self._observation(ids=ids, complete=True, pending=3)
        plan = choose_help_action(before, 2, allow_help_all=True)
        self.assertEqual(plan.action, HelpAction.INDIVIDUAL)
        plan = choose_help_action(before, 3, allow_help_all=True)
        after = self._observation(ids=("c" * 24,), at=2.0, balance=3000,
            success=True, complete=True, pending=1, all_count=2)
        self.assertEqual(verified_request_delta(before, after, plan=plan,
            remaining=2, transport_calls=1), 2)
        overshoot = self._observation(ids=(), at=2.0, balance=3000,
            success=True, complete=True, pending=0, all_count=3)
        self.assertEqual(verified_request_delta(before, overshoot, plan=plan,
            remaining=2, transport_calls=1), 0)
        uncounted = self._observation(ids=("c" * 24,), at=2.0, balance=3000,
            success=True, complete=True, pending=1, all_count=None)
        self.assertEqual(verified_request_delta(before, uncounted, plan=plan,
            remaining=3, transport_calls=1), 0)

    def test_recognizer_binds_retained_exact_result_text_and_counter(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        text = {
            route.SCREEN_TITLE_ROI: "Speedup Help",
            route.NO_REQUESTS_ROI: "No help request currently...",
            route.HELP_SUCCESS_ROI: "Help successful",
        }
        with (patch.object(route, "_ocr_text", side_effect=lambda _frame, roi, **_kw: text.get(roi, "")),
              patch.object(route, "_individual_controls", return_value=()),
              patch.object(route, "_help_all_control", return_value=(route.HELP_ALL_ROI, True)),
              patch.object(route, "_coin_counter", return_value=(1000, 50000)),
              patch.object(route, "_ocr_tokens", return_value=())):
            result = route.recognize_help_screen(frame, captured_at=10.0,
                frame_sha256="a" * 64, now=10.1,
                overlay_reader=lambda _frame: {"recognized": False, "state": "none"})
        self.assertEqual(result.screen_state, SOURCE_STATE)
        self.assertTrue(result.source_fresh)
        self.assertTrue(result.exact_no_requests_message)
        self.assertTrue(result.help_success_message)
        self.assertEqual(result.daily_alliance_coin_balance, 1000)
        self.assertIsNone(result.help_all_success_count)

    def test_service_native_binding_uses_injected_lifecycle_and_fixed_budgets(self):
        arguments = {}
        binding = object()

        def make_binding(**kwargs):
            arguments.update(kwargs)
            return binding

        self.assertIs(route.create_service_binding(make_binding), binding)
        self.assertEqual(arguments["flow_id"], route.FLOW_ID)
        self.assertEqual(arguments["product_id"], route.PRODUCT_ID)
        self.assertEqual(arguments["product_revision"], route.PRODUCT_REVISION)
        self.assertEqual(arguments["runtime_profile_id"], route.PROFILE_ID)
        self.assertEqual(arguments["owner"], "automation-service:alliance-help")
        self.assertEqual(arguments["workflow"], "alliance-help-native")
        self.assertEqual((arguments["max_inputs"], arguments["max_actions"]),
                         (route.MAX_INPUTS, route.MAX_ACTIONS))
        self.assertIs(arguments["driver"], route._service_driver)
        with self.assertRaises(TypeError):
            route.create_service_binding(None)

    def test_canonical_request_count_requires_contiguous_confirmed_prefix(self):
        confirmed = {i: {"final_status": "confirmed", "quantity": 1, "game_day_id": "reset"}
                     for i in range(1, 4)}
        self.assertEqual(confirmed_request_count(confirmed), 3)
        with self.assertRaisesRegex(ValueError, "not contiguous"):
            confirmed_request_count({1: {"final_status": "confirmed", "quantity": 1, "game_day_id": "reset"},
                                     3: {"final_status": "confirmed", "quantity": 1, "game_day_id": "reset"}})
        identity = SimpleNamespace(runtime_scope="slot", account_id="account",
                                   server_id="server", reset_id="reset")
        self.assertNotEqual(alliance_help_action_key(runtime_scope=identity.runtime_scope,
            account_id=identity.account_id, server_id=identity.server_id,
            reset_id=identity.reset_id, ordinal=1),
            alliance_help_action_key(runtime_scope=identity.runtime_scope,
            account_id=identity.account_id, server_id=identity.server_id,
            reset_id=identity.reset_id, ordinal=2))

    def test_production_route_fake_replay_confirms_ten_then_closes_home(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            now = 1_800_000_000.0
            identity = derive_resource_runtime_identity(resource_fixed_runtime_binding(),
                datetime.fromtimestamp(now, timezone.utc))
            store = SafetyStore(root / "actions.sqlite3")
            session = _ReplaySession(root / "native-session", owner="alliance-help-replay")
            store.acquire_lease(session.owner, now, 3600)
            runtime = _ReplayRuntime(session.session_directory, session)
            session.runtime = runtime
            patches = (
                patch.object(route, "_home", side_effect=lambda frame: runtime.snapshot(frame).state == "home"),
                patch.object(route, "_home_alliance_target", side_effect=lambda frame: (639, 1243, 647, 1251)
                             if runtime.snapshot(frame).state == "home" else None),
                patch.object(route, "_alliance_menu", side_effect=lambda frame: runtime.snapshot(frame).state == "alliance"),
                patch.object(route, "_menu_help_target", return_value=(180, 500, 300, 560)),
                patch.object(route, "_back_target", return_value=(45, 8, 160, 58)),
                patch.object(route, "recognize_help_screen", runtime.observe),
            )
            try:
                for item in patches:
                    item.start()
                result = route.run_alliance_help(
                    session=session, runtime=runtime, store=store, identity=identity,
                    validate_identity=lambda: None, occurrence_key="occ:v1:" + "a" * 64,
                    settle_seconds=0, monotonic_clock=runtime.clock.now,
                    utc_clock=lambda: now, observer=runtime.observe,
                    scheduler_reset_id=f"game-day-{datetime.fromtimestamp(now, timezone.utc).date().isoformat()}",
                )
            finally:
                for item in reversed(patches):
                    item.stop()
                store.release_lease(session.owner, now)
                store.close()
            self.assertEqual(result["status"], "complete_for_reset")
            self.assertEqual(result["confirmed_request_count"], 10)
            self.assertEqual(result["committed_action_count"], 10)
            self.assertEqual(result["help_transport_calls"], 10)
            self.assertEqual(runtime.help_taps, DAILY_REQUEST_LIMIT)
            self.assertEqual(len(result["confirmed_request_records"]), 10)
            self.assertEqual(len(result["help_dispatch_evidence"]), 10)
            self.assertTrue(result["accounting_verified"])
            self.assertTrue(result["terminal_home_verified"])
            self.assertEqual(result["input_count"], session.input_count)
            self.assertEqual(result["input_count"], runtime.input_count)
            self.assertLessEqual(result["input_count"], route.MAX_INPUTS)
            self.assertTrue((session.session_directory / "alliance-help-result.json").is_file())

    def test_no_requests_and_partial_availability_defer_normally_with_exact_remaining_count(self):
        with tempfile.TemporaryDirectory() as directory:
            empty, _blocked, _session, _runtime = _run_replay_route(
                Path(directory) / "empty", requests=0)
            self.assertEqual(empty["status"], "deferred")
            self.assertEqual(empty["reason"], "exact_no_requests_message")
            self.assertEqual(empty["confirmed_request_count"], 0)
            self.assertEqual(empty["help_transport_calls"], 0)
            self.assertTrue(empty["no_work_evidence"]["exact_no_requests_message"])
            self.assertTrue(empty["terminal_home_verified"])

            partial, _blocked, _session, runtime = _run_replay_route(
                Path(directory) / "partial", requests=1)
            self.assertEqual(partial["status"], "deferred")
            self.assertEqual(partial["confirmed_request_count"], 1)
            self.assertEqual(partial["committed_action_count"], 1)
            self.assertEqual(partial["help_transport_calls"], 1)
            self.assertTrue(partial["no_work"])
            self.assertTrue(partial["terminal_home_verified"])
            self.assertLessEqual(partial["input_count"], route.MAX_INPUTS)
            self.assertEqual(runtime.help_taps, 1)

    def test_confirmed_request_prefix_survives_native_process_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_db = root / "canonical-actions.sqlite3"
            first, _blocked, _session, _runtime = _run_replay_route(
                root / "first", requests=1, store_path=state_db)
            after_restart, _blocked, _session, _runtime = _run_replay_route(
                root / "restarted", requests=0, store_path=state_db)
        self.assertEqual(first["confirmed_request_count"], 1)
        self.assertEqual(after_restart["status"], "deferred")
        self.assertEqual(after_restart["confirmed_request_count"], 1)
        self.assertEqual(after_restart["committed_action_count"], 1)
        self.assertEqual(after_restart["help_transport_calls"], 0)
        self.assertTrue(after_restart["terminal_home_verified"])

    def test_transport_only_unknown_is_not_retried_and_route_returns_home(self):
        with tempfile.TemporaryDirectory() as directory:
            result, action_blocked, _session, runtime = _run_replay_route(
                Path(directory) / "unknown", requests=1, suppress_effects=True)
        self.assertEqual(result["status"], "reconciliation_required")
        self.assertEqual(result["help_transport_calls"], 1)
        self.assertEqual(result["confirmed_request_count"], 0)
        self.assertTrue(result["effect_reconciliation_required"])
        self.assertTrue(result["identical_retry_denied"])
        self.assertTrue(result["terminal_home_verified"])
        self.assertTrue(action_blocked)
        self.assertEqual(runtime.help_taps, 1)
        self.assertLessEqual(result["input_count"], route.MAX_INPUTS)


ALLIANCE_MENU_FIXTURE = Path(__file__).parent / "fixtures" / "alliance_help_menu" / "alliance-menu-help56-0005.png"
ALLIANCE_MENU_FIXTURE_SHA256 = "88bb1d05ec658290f3ce1b53a585e4a2b759b270fbb8c2ccc1fc51f4f48a43e2"


def _retained(path: Path, expected_sha256: str | None = None):
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise AssertionError(f"retained fixture bytes changed: {path}")
    frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    return SimpleNamespace(frame=frame, sha256=digest, captured_monotonic=10.0, path=path)


class AllianceHelpRetainedNavigationTests(unittest.TestCase):
    """Production OCR/overlay recognizers on retained native pixels (#56 failure frame)."""

    def test_retained_alliance_menu_is_recognized_and_binds_bottom_bar_help_entry(self):
        menu = _retained(ALLIANCE_MENU_FIXTURE, ALLIANCE_MENU_FIXTURE_SHA256)
        self.assertTrue(route._alliance_menu(menu.frame))
        self.assertFalse(route._home(menu.frame))
        self.assertIsNotNone(route._back_target(menu.frame))
        target = route._menu_help_target(menu.frame)
        self.assertIsNotNone(target)
        x0, y0, x1, y1 = target
        center_x, center_y = (x0 + x1) // 2, (y0 + y1) // 2
        # Alliance Help is the third bottom-bar entry (label/icon about x 416..546), not Mail/Operations.
        self.assertTrue(400 <= x0 < center_x < x1 <= 560, target)
        self.assertTrue(1190 <= center_y < 1280, target)
        self.assertEqual(route._route_context(menu, now=10.5), route.ROUTE_CONTEXT_ALLIANCE_MENU)

    def test_alliance_menu_rejects_other_title_bar_or_any_unclear_overlay(self):
        menu = _retained(ALLIANCE_MENU_FIXTURE, ALLIANCE_MENU_FIXTURE_SHA256)
        help_source = _retained(route.HELP_SOURCE_PATH)
        other_title = menu.frame.copy()
        other_title[0:70] = help_source.frame[0:70]
        self.assertFalse(route._alliance_menu(other_title))
        other_bar = menu.frame.copy()
        other_bar[1180:1280] = help_source.frame[1180:1280]
        self.assertIsNone(route._menu_help_target(other_bar))
        self.assertFalse(route._alliance_menu(other_bar))
        self.assertFalse(route._alliance_menu(menu.frame,
            overlay_reader=lambda _frame: {"recognized": True, "state": "modal"}))
        self.assertFalse(route._alliance_menu(menu.frame,
            overlay_reader=lambda _frame: {"recognized": False}))

        def failing(_frame):
            raise RuntimeError("overlay recognizer unavailable")

        self.assertFalse(route._alliance_menu(menu.frame, overlay_reader=failing))

    def test_retained_speedup_help_title_is_recognized_fresh_only_and_is_not_the_menu(self):
        help_source = _retained(route.HELP_SOURCE_PATH)
        observation = route.recognize_help_screen(help_source.frame, captured_at=10.0,
            frame_sha256=help_source.sha256, now=10.5)
        self.assertEqual(observation.screen_state, SOURCE_STATE)
        self.assertTrue(observation.overlay_clear)
        self.assertFalse(route._alliance_menu(help_source.frame))
        self.assertEqual(route._route_context(help_source, now=10.5), route.ROUTE_CONTEXT_SPEEDUP_HELP)
        self.assertIsNone(route._route_context(help_source, now=100.0))


class AllianceHelpRouteContextRecoveryTests(unittest.TestCase):
    def test_current_alliance_menu_returns_home_then_runs_normal_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _blocked, session, runtime = _run_replay_route(
                Path(directory) / "menu", requests=0, initial_state="alliance")
        recovery = result["route_context_recovery"]
        self.assertEqual(recovery["source_context"], route.ROUTE_CONTEXT_ALLIANCE_MENU)
        self.assertEqual(recovery["verified_navigation"], ["back-alliance-home"])
        self.assertTrue(recovery["home_verified"])
        self.assertEqual(result["status"], "deferred")
        self.assertEqual(result["reason"], "exact_no_requests_message")
        self.assertEqual(result["help_transport_calls"], 0)
        self.assertTrue(result["terminal_home_verified"])
        self.assertTrue(result["accounting_verified"])
        # Back, open Alliance, open Help, then the two terminal Backs.
        self.assertEqual(result["input_count"], 5)
        self.assertEqual(result["input_count"], session.input_count)
        self.assertEqual(result["input_count"], runtime.input_count)

    def test_current_speedup_help_returns_home_before_any_request(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _blocked, session, runtime = _run_replay_route(
                Path(directory) / "help", requests=1, initial_state="help")
        self.assertEqual(result["route_context_recovery"]["verified_navigation"],
                         ["back-speedup-help", "back-alliance-home"])
        self.assertEqual(result["status"], "deferred")
        self.assertEqual(result["confirmed_request_count"], 1)
        self.assertEqual(runtime.help_taps, 1)
        self.assertTrue(result["terminal_home_verified"])
        self.assertTrue(result["accounting_verified"])
        self.assertEqual(result["input_count"], 7)
        self.assertEqual(result["input_count"], session.input_count)

    def test_unknown_start_context_sends_no_input(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _blocked, session, runtime = _run_replay_route(
                Path(directory) / "unknown", requests=1, initial_state="unknown")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "alliance_help_requires_current_clean_home")
        self.assertNotIn("route_context_recovery", result)
        self.assertEqual(runtime.input_count, 0)
        self.assertEqual(session.input_count, 0)
        self.assertEqual(runtime.frame_actions, set())

    def test_unchanged_recovery_back_is_unknown_and_never_repeated(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _blocked, session, runtime = _run_replay_route(
                Path(directory) / "stuck", requests=1, initial_state="alliance", ignore_back=True)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "alliance_help_route_context_recovery_unproven")
        self.assertFalse(result["route_context_recovery"]["home_verified"])
        self.assertFalse(result["terminal_home_verified"])
        self.assertEqual(result["verified_navigation"], [])
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(session.input_count, 1)
        self.assertEqual({item[1] for item in runtime.frame_actions}, {"alliance-help-back"})
        self.assertEqual(runtime.help_taps, 0)
        self.assertTrue(result["accounting_verified"])

    def test_recovery_back_rebinds_the_immediate_route_context(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _blocked, session, runtime = _run_replay_route(
                Path(directory) / "changed", requests=1, initial_state="alliance",
                change_before_back=True,
            )
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["terminal_home_verified"])
        self.assertEqual(runtime.input_count, 0)
        self.assertEqual(session.input_count, 0)
        self.assertEqual(runtime.help_taps, 0)


class _ReplayClock:
    def __init__(self):
        self.value = 1.0

    def now(self):
        return self.value

    def tick(self):
        self.value += 0.01
        return self.value


class _ReplayRuntime:
    def __init__(self, directory: Path, session):
        self.session = str(directory)
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.session_owner = session
        self.clock = _ReplayClock()
        self.state = "home"
        self.requests = [f"{index:024x}" for index in range(10)]
        self.coin = 0
        self.toast_remaining = 0
        self.capture_count = 0
        self.input_count = 0
        self.help_taps = 0
        self.suppress_effects = False
        self.delayed_success = False
        self.pending_effect = False
        self.ignore_back = False
        self.change_before_back = False
        self.frame_actions = set()
        self.frame_keys = {}
        self.snapshots = {}

    def measure_foreground_package(self):
        return "com.global.ztmslg"

    def capture(self, label="capture"):
        if self.change_before_back and label == "alliance-help-back-alliance-home-before":
            self.state = "unknown"
        self.capture_count += 1
        timestamp = self.clock.tick()
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        state_code = {"home": 1, "alliance": 2, "help": 3, "unknown": 4}[self.state]
        toast = int(self.toast_remaining > 0)
        if toast:
            self.toast_remaining -= 1
        frame[0, 0, :] = (state_code, toast, len(self.requests) & 0xFF)
        frame[0, 1, 0] = self.coin & 0xFF
        frame[0, 1, 1] = (self.coin >> 8) & 0xFF
        frame[0, 2, 0] = self.capture_count & 0xFF
        ok, encoded = cv2.imencode(".png", frame)
        if not ok:
            raise AssertionError("replay PNG encoding failed")
        raw = encoded.tobytes()
        digest = hashlib.sha256(raw).hexdigest()
        path = self.directory / f"replay-{self.capture_count:04d}.png"
        path.write_bytes(raw)
        captured = SimpleNamespace(frame=frame, sha256=digest, path=path,
                                   captured_monotonic=timestamp, label=label)
        self.frame_keys[id(frame)] = digest
        self.snapshots[digest] = SimpleNamespace(state=self.state, requests=tuple(self.requests),
            coin=self.coin, toast=bool(toast), capture_count=self.capture_count)
        if self.pending_effect:
            self.pending_effect = False
            self._confirm_help()
        return captured

    def snapshot(self, frame):
        return self.snapshots[self.frame_keys[id(frame)]]

    def tap(self, before, *, target_identity, target_roi, action_key, **_kwargs):
        if target_roi is None or len(target_roi) != 4:
            raise ValueError("replay refuses unbound target")
        self.input_count += 1
        self.frame_actions.add((before.sha256, target_identity, target_roi))
        if target_identity == "home-nav-alliance":
            self.state = "alliance"
        elif target_identity == "alliance-menu-help":
            self.state = "help"
        elif target_identity == INDIVIDUAL_TARGET_IDENTITY:
            self.help_taps += 1
            if self.state != "help" or not self.requests:
                raise ValueError("replay individual Help target is no longer current")
            if not self.suppress_effects:
                if self.delayed_success:
                    self.pending_effect = True
                else:
                    self._confirm_help()
        elif target_identity == "alliance-help-back":
            if self.ignore_back:
                pass
            elif self.state == "help":
                self.state = "alliance"
            elif self.state == "alliance":
                self.state = "home"
            else:
                raise ValueError("replay Back target has no recognized source")
        else:
            raise ValueError(f"replay refuses target {target_identity}")

    def _confirm_help(self):
        self.requests.pop(0)
        self.coin += 1000
        self.toast_remaining = 1

    def observe(self, frame, *, captured_at, frame_sha256, now=None, **_kwargs):
        saved = self.snapshots[frame_sha256]
        requests = tuple(HelpRequest(request_id, (550, 260, 680, 310), True, True)
                         for request_id in saved.requests)
        return HelpObservation(
            screen_state=SOURCE_STATE if saved.state == "help" else "UNKNOWN",
            captured_at=captured_at, frame_sha256=frame_sha256,
            overlay_clear=True, source_fresh=(now is None or 0 <= now - captured_at <= 30),
            requests=requests, help_all_roi=(277, 1188, 523, 1268), help_all_free=True,
            exact_no_requests_message=(saved.state == "help" and not saved.requests),
            pending_count=None, request_list_complete=False, cost_marker_seen=False,
            daily_alliance_coin_balance=saved.coin, daily_alliance_coin_limit=50000,
            help_success_message=saved.toast, help_all_success_count=None,
        )

    def reconcile(self, _action_key, _status, _captured, _reason):
        return None


class _NativeReplayRuntime(LocalBlueStacksRuntime):
    """Real native guards, fingerprints, keys, events and tap transport; offline device."""

    def __init__(self, scene, session):
        self.scene = scene
        targets = {
            box_center((639, 1243, 647, 1251)): ("home-nav-alliance", (639, 1243, 647, 1251)),
            box_center((180, 500, 300, 560)): ("alliance-menu-help", (180, 500, 300, 560)),
            box_center((550, 260, 680, 310)): (INDIVIDUAL_TARGET_IDENTITY, (550, 260, 680, 310)),
            box_center((45, 8, 160, 58)): ("alliance-help-back", (45, 8, 160, 58)),
        }

        def dispatch_tap(point):
            target, roi = targets[point]
            scene.tap(SimpleNamespace(sha256="offline-device"),
                target_identity=target, target_roi=roi,
                action_key=f"device-input-{scene.input_count}")

        super().__init__(SimpleNamespace(dispatch_tap=dispatch_tap),
            session.session_directory, execute=True)
        self.max_inputs = route.MAX_INPUTS
        self.clock = scene.clock

    def capture(self, label="capture"):
        return self.scene.capture(label)

    def measure_foreground_package(self):
        return self.scene.measure_foreground_package()

    @property
    def help_taps(self):
        return self.scene.help_taps


class _ReplaySession:
    def __init__(self, directory: Path, owner: str):
        self.session_directory = directory
        self.session_directory.mkdir(parents=True, exist_ok=True)
        self.owner = owner
        self.input_count = 0
        self.runtime = None

    def observe(self, capture, *, label):
        return capture(label)

    def run_action(self, *, action_class, label, capture, dispatch, recognize,
                   settled_successor, **kwargs):
        before = capture(f"{label}-before")
        authorize = kwargs.get("authorize")
        if callable(authorize):
            authorize(before)
        start = self.runtime.input_count
        dispatch(before)
        self.input_count += self.runtime.input_count - start
        after = capture(f"{label}-after")
        state = recognize(after)
        if state in {"pending", "unknown", None, False}:
            after = settled_successor()
            state = recognize(after)
        status = "completed" if state not in {"pending", "unknown", None, False} else "unknown"
        return SimpleNamespace(status=status, reason="replay", action_class=action_class)


def _run_replay_route(directory: Path, *, requests: int, suppress_effects: bool = False,
                      store_path: Path | None = None, native_dispatch: bool = False,
                      delayed_success: bool = False, initial_state: str = "home",
                      ignore_back: bool = False, change_before_back: bool = False):
    directory.mkdir(parents=True, exist_ok=True)
    now = 1_800_000_000.0
    identity = derive_resource_runtime_identity(resource_fixed_runtime_binding(),
        datetime.fromtimestamp(now, timezone.utc))
    store = SafetyStore(store_path or directory / "actions.sqlite3")
    session = _ReplaySession(directory / "native-session", owner="alliance-help-replay")
    try:
        store.acquire_lease(session.owner, now, 3600)
    except BaseException:
        store.close()
        raise
    scene = _ReplayRuntime(session.session_directory, session)
    runtime = _NativeReplayRuntime(scene, session) if native_dispatch else scene
    session.runtime = runtime
    scene.requests = [f"{index:024x}" for index in range(requests)]
    scene.suppress_effects = suppress_effects
    scene.delayed_success = delayed_success
    scene.state = initial_state
    scene.ignore_back = ignore_back
    scene.change_before_back = change_before_back
    patches = (
        patch.object(route, "_home", side_effect=lambda frame: scene.snapshot(frame).state == "home"),
        patch.object(route, "_home_alliance_target",
            side_effect=lambda frame: (639, 1243, 647, 1251)
                if scene.snapshot(frame).state == "home" else None),
        patch.object(route, "_alliance_menu",
            side_effect=lambda frame: scene.snapshot(frame).state == "alliance"),
        patch.object(route, "_menu_help_target", return_value=(180, 500, 300, 560)),
        patch.object(route, "_back_target", return_value=(45, 8, 160, 58)),
        patch.object(route, "recognize_help_screen", scene.observe),
        patch("scripts.bluestacks_native_runtime.time.monotonic", side_effect=scene.clock.now),
    )
    try:
        for item in patches:
            item.start()
        result = route.run_alliance_help(
            session=session, runtime=runtime, store=store, identity=identity,
            validate_identity=lambda: None, occurrence_key="occ:v1:" + "b" * 64,
            settle_seconds=0, monotonic_clock=runtime.clock.now,
            utc_clock=lambda: now, observer=scene.observe,
            scheduler_reset_id=f"game-day-{datetime.fromtimestamp(now, timezone.utc).date().isoformat()}",
        )
        action_blocked = store.has_action_block()
    finally:
        for item in reversed(patches):
            item.stop()
        store.release_lease(session.owner, now)
        store.close()
    return result, action_blocked, session, runtime


if __name__ == "__main__":
    unittest.main()
