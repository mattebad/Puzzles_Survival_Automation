from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from safe_action_core import SafetyStore
from scripts import alliance_help_bluestacks as route
from scripts import navigation_development_boundary as boundary
from scripts.bluestacks_flow_collector import ADBRunner
from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime, box_center
from tasks.alliance_help import (
    DAILY_REQUEST_LIMIT, HELP_ALL_TARGET_IDENTITY,
    INDIVIDUAL_TARGET_IDENTITY, SOURCE_STATE,
    HelpAction, HelpObservation, HelpRequest, alliance_help_action_key,
    choose_help_action, verified_help_result,
)
from tasks.runtime_identity import derive_resource_runtime_identity, resource_fixed_runtime_binding


class AllianceHelpSemanticsTests(unittest.TestCase):
    def _observation(self, *, ids=("a" * 24,), at=1.0, success=False,
                     no_requests=False, all_count=None, help_all=True, source_fresh=True,
                     overlay=True, cost=False, ready_context=False):
        requests = tuple(HelpRequest(item, (550, 260 + index * 80, 680, 310 + index * 80), True, True)
                         for index, item in enumerate(ids))
        return HelpObservation(
            screen_state=SOURCE_STATE, captured_at=at,
            frame_sha256=hashlib.sha256(f"frame:{at}:{ids}".encode()).hexdigest(),
            overlay_clear=overlay, source_fresh=source_fresh, requests=requests,
            help_all_roi=(277, 1188, 523, 1268) if help_all else None, help_all_free=help_all,
            exact_no_requests_message=no_requests, cost_marker_seen=cost,
            help_success_message=success, help_all_success_count=all_count,
            ready_request_context=ready_context,
        )

    def test_quota_and_individual_fallback_selection(self):
        observation = self._observation(ids=("a" * 24, "b" * 24), help_all=False)
        plan = choose_help_action(observation, DAILY_REQUEST_LIMIT)
        self.assertEqual(plan.action, HelpAction.INDIVIDUAL)
        self.assertEqual(plan.target_identity, INDIVIDUAL_TARGET_IDENTITY)
        self.assertEqual(plan.request_ids, ("a" * 24,))
        self.assertEqual(choose_help_action(observation, 0).action, HelpAction.STOP_QUOTA)
        self.assertEqual(choose_help_action(observation, DAILY_REQUEST_LIMIT + 1).action, HelpAction.UNKNOWN)

    def test_help_all_needs_no_coin_or_census_and_may_exceed_remaining_goal(self):
        observation = self._observation(ids=("a" * 24, "b" * 24, "c" * 24))
        plan = choose_help_action(observation, 1)
        self.assertEqual(plan.action, HelpAction.HELP_ALL)
        self.assertEqual(plan.target_identity, HELP_ALL_TARGET_IDENTITY)
        self.assertEqual(plan.target_roi, route.HELP_ALL_ROI)

    def test_no_requests_never_taps_help_all_and_unsafe_sources_block(self):
        no_requests = self._observation(ids=(), no_requests=True)
        self.assertEqual(choose_help_action(no_requests, 10).action, HelpAction.NO_REQUESTS)
        self.assertEqual(choose_help_action(self._observation(ids=()), 10).action,
                         HelpAction.FREE_HELP_DISAPPEARED)
        for observation in (self._observation(cost=True), self._observation(source_fresh=False),
                            self._observation(overlay=False), self._observation(success=True)):
            self.assertEqual(choose_help_action(observation, 10).action, HelpAction.UNKNOWN)

    def test_rows_disappearing_and_transport_alone_never_prove_our_help(self):
        before = self._observation()
        plan = choose_help_action(before, 10)
        for after, calls in ((self._observation(ids=(), at=2), 1),
                             (self._observation(at=2), 1),
                             (self._observation(ids=(), at=2, success=True), 0)):
            self.assertIsNone(verified_help_result(before, after, plan=plan, transport_calls=calls))

    def test_individual_needs_attributable_success_not_coin_delta(self):
        before = self._observation(help_all=False)
        plan = choose_help_action(before, 10)
        after = self._observation(ids=(), at=2, success=True)
        result = verified_help_result(before, after, plan=plan, transport_calls=1)
        self.assertEqual(result.proven_request_count, 1)
        self.assertIsNone(verified_help_result(before,
            self._observation(at=2, success=True), plan=plan, transport_calls=1))

    def test_known_batch_count_unknown_is_distinct_from_unknown_effect_and_never_clipped(self):
        before = self._observation()
        plan = choose_help_action(before, 2)
        known = verified_help_result(before,
            self._observation(ids=(), at=2, success=True), plan=plan, transport_calls=1)
        self.assertIsNotNone(known)
        self.assertIsNone(known.proven_request_count)
        counted = verified_help_result(before,
            self._observation(ids=(), at=2, success=True, all_count=13), plan=plan, transport_calls=1)
        self.assertEqual(counted.proven_request_count, 13)
        # List motion / other members can remove every visible row. Without the game
        # acknowledgement neither the batch nor any number of helped requests is proven.
        self.assertIsNone(verified_help_result(before,
            self._observation(ids=(), at=2, all_count=13), plan=plan, transport_calls=1))

    def test_help_all_is_independent_of_individual_ocr_but_not_ready_context(self):
        before = self._observation(ids=(), ready_context=True)
        plan = choose_help_action(before, 10)
        self.assertEqual(plan.action, HelpAction.HELP_ALL)
        after = self._observation(ids=(), at=2, success=True, no_requests=True)
        result = verified_help_result(before, after, plan=plan, transport_calls=1)
        self.assertIsNotNone(result)
        self.assertIsNone(result.proven_request_count)
        self.assertIsNone(verified_help_result(
            self._observation(ids=()), after, plan=plan, transport_calls=1))
        self.assertEqual(choose_help_action(after, 10).action, HelpAction.NO_REQUESTS)


    def test_retained_positive_individual_banner_has_no_invented_help_all_count(self):
        post = _retained(route.HELP_SOURCE_PATH.with_name("alliance_help_post.png"))
        result = route.recognize_help_screen(post.frame, captured_at=10.0,
            frame_sha256=post.sha256, now=10.1)
        self.assertEqual(result.screen_state, SOURCE_STATE)
        self.assertTrue(result.help_success_message)
        self.assertTrue(result.exact_no_requests_message)
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

    def test_operation_key_preserves_individual_history_and_is_count_independent(self):
        identity = dict(runtime_scope="slot", account_id="account", server_id="server", reset_id="reset")
        key = alliance_help_action_key(**identity, ordinal=1)
        payload = {**identity, "flow_id": "ALLIANCE-HELP-TEN-FREE-REQUESTS", "ordinal": 1}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(key, f"alliance-help:daily:{digest}:01")
        self.assertNotEqual(key, alliance_help_action_key(**identity, ordinal=2))
        self.assertNotEqual(key, alliance_help_action_key(**identity, ordinal=11))

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
                patch.object(route, "_menu_help_target", return_value=REPLAY_MENU_HELP_ROI),
                patch.object(route, "_help_hub", side_effect=lambda frame: runtime.snapshot(frame).state == "hub"),
                patch.object(route, "_hub_speedup_target", side_effect=lambda frame: REPLAY_HUB_SPEEDUP_ROI
                             if runtime.snapshot(frame).state == "hub" else None),
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

    def test_help_all_retains_known_batch_unknown_quantity_and_prior_credit_across_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "actions.sqlite3"
            prior, _blocked, _session, _runtime = _run_replay_route(
                root / "individual", requests=1, store_path=database)
            batch, blocked, _session, runtime = _run_replay_route(
                root / "batch", requests=12, store_path=database,
                help_all_available=True, native_dispatch=True)
            restarted, _blocked, _session, _runtime = _run_replay_route(
                root / "restart", requests=0, store_path=database, help_all_available=True)
        self.assertEqual(prior["confirmed_request_count"], 1)
        self.assertEqual(runtime.help_taps, 1)
        self.assertFalse(blocked)
        self.assertEqual(batch["status"], "deferred")
        self.assertEqual(batch["reason"], "help_all_batch_confirmed_reobserve")
        self.assertEqual(batch["confirmed_request_count"], 1)
        self.assertEqual(batch["committed_action_count"], 2)
        self.assertEqual(batch["unproven_help_all_batch_count"], 1)
        self.assertFalse(batch["effect_reconciliation_required"])
        self.assertFalse(batch["daily_quantity_proven"])
        record = batch["confirmed_request_records"][-1]
        self.assertEqual(record["operation_ordinal"], 2)
        self.assertIsNone(record["proven_request_count"])
        self.assertEqual(restarted["confirmed_request_records"], batch["confirmed_request_records"])
        self.assertEqual(restarted["help_transport_calls"], 0)

    def test_durable_attributable_batch_count_is_unclipped_and_legacy_individual_keys_survive(self):
        # This tests the durable count contract, not an invented native toast/reader.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "actions.sqlite3"
            prior, _blocked, _session, _runtime = _run_replay_route(
                root / "individual", requests=9, store_path=database)
            batch, _blocked, _session, _runtime = _run_replay_route(
                root / "batch", requests=5, store_path=database, help_all_available=True)
            record = batch["confirmed_request_records"][-1]
            store = SafetyStore(database)
            try:
                store.audit(route.FLOW_ID, route.HELP_ALL_COUNT_EVENT, 1_800_000_000.0,
                    {"action_key": record["action_key"], "proven_request_count": 5},
                    record["action_id"])
            finally:
                store.close()
            restarted, _blocked, _session, runtime = _run_replay_route(
                root / "restart", requests=2, store_path=database, help_all_available=True)
        self.assertEqual(prior["confirmed_request_count"], 9)
        self.assertEqual(restarted["status"], "complete_for_reset")
        self.assertEqual(restarted["confirmed_request_count"], 14)
        self.assertEqual(restarted["committed_action_count"], 10)
        self.assertEqual(restarted["confirmed_request_records"][:9], prior["confirmed_request_records"])
        self.assertEqual(runtime.help_taps, 0)

    def test_help_all_unknown_effect_stops_after_one_tap(self):
        with tempfile.TemporaryDirectory() as directory:
            result, blocked, _session, runtime = _run_replay_route(
                Path(directory), requests=12, suppress_effects=True,
                native_dispatch=True, help_all_available=True)
        self.assertEqual(runtime.help_taps, 1)
        self.assertTrue(blocked)
        self.assertEqual(result["status"], "reconciliation_required")
        self.assertEqual(result["confirmed_request_count"], 0)
        self.assertTrue(result["identical_retry_denied"])


ALLIANCE_MENU_FIXTURE = Path(__file__).parent / "fixtures" / "alliance_help_menu" / "alliance-menu-help56-0005.png"
ALLIANCE_MENU_FIXTURE_SHA256 = "88bb1d05ec658290f3ce1b53a585e4a2b759b270fbb8c2ccc1fc51f4f48a43e2"
HELP_HUB_FIXTURE = Path(__file__).parent / "fixtures" / "alliance_help_menu" / "alliance-help-hub-help56-0012.png"
HELP_HUB_FIXTURE_SHA256 = "8e1241cc50850c446ca04ccb72c86db73869a45b27fcb323dd73cc8dc38e7541"
REPLAY_MENU_HELP_ROI = (416, 1190, 546, 1280)
REPLAY_HUB_SPEEDUP_ROI = (275, 106, 521, 167)


def _retained(path: Path, expected_sha256: str | None = None):
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise AssertionError(f"retained fixture bytes changed: {path}")
    frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    return SimpleNamespace(frame=frame, sha256=digest, captured_monotonic=10.0, path=path)


class AllianceHelpRetainedNavigationTests(unittest.TestCase):
    """Production OCR/overlay recognizers on retained native pixels (#56 failure frame)."""

    def test_real_walkthrough_help_all_needs_no_request_names_and_empty_gold_is_not_ready(self):
        fixture_root = ALLIANCE_MENU_FIXTURE.parent
        names_and_hashes = (
            ("0005-speedup-help-before.jpg",
             "d5c2840123529c943035eaabd350313f5b84b094299aac81a7ae8b49695f9492"),
            ("0006-help-all-immediate.jpg",
             "2e36b46654f188874f0087427c185bd16245982a58d1e0981037466262fdd603"),
            ("0007-help-post-batch-reobserve.jpg",
             "2d61ae16b7a3f01e6ba45e602b99963b974fb93f6339ff33fadfdb5d96068e7d"),
        )
        observations = []
        for at, (name, digest) in enumerate(names_and_hashes, 1):
            retained = _retained(fixture_root / name, digest)
            # Remove only this retained window's OS chrome, then normalize its
            # actual game viewport. These are fixture geometry, never input targets.
            frame = cv2.resize(retained.frame[32:1212, :738], (800, 1280),
                               interpolation=cv2.INTER_AREA)
            with patch.object(route, "_individual_controls", return_value=()):
                observations.append(route.recognize_help_screen(
                    frame, captured_at=float(at), frame_sha256=digest, now=at + 0.1))
        before, success, empty = observations
        self.assertTrue(before.ready_request_context)
        plan = choose_help_action(before, 10)
        self.assertEqual(plan.action, HelpAction.HELP_ALL)
        result = verified_help_result(before, success, plan=plan, transport_calls=1)
        self.assertIsNotNone(result)
        self.assertIsNone(result.proven_request_count)
        self.assertIsNotNone(empty.help_all_roi)
        self.assertFalse(empty.ready_request_context)
        self.assertEqual(choose_help_action(empty, 10).action, HelpAction.NO_REQUESTS)

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
        self.assertFalse(route._help_hub(menu.frame))

    def test_retained_help_hub_is_recognized_and_binds_only_the_speedup_help_row(self):
        hub = _retained(HELP_HUB_FIXTURE, HELP_HUB_FIXTURE_SHA256)
        self.assertTrue(route._help_hub(hub.frame))
        self.assertFalse(route._alliance_menu(hub.frame))
        self.assertFalse(route._home(hub.frame))
        self.assertNotEqual(route.recognize_help_screen(hub.frame, captured_at=10.0,
            frame_sha256=hub.sha256, now=10.5).screen_state, SOURCE_STATE)
        self.assertIsNotNone(route._back_target(hub.frame))
        rows = route._help_hub_rows(hub.frame)
        assert rows is not None
        self.assertEqual(tuple(rows), route.HELP_HUB_ROW_LABELS)
        target = route._hub_speedup_target(hub.frame)
        assert target is not None
        x0, y0, x1, y1 = target
        center_x, center_y = (x0 + x1) // 2, (y0 + y1) // 2
        # Speedup Help is the first row panel (about y 78..198); Transport/Reinforce rows sit below.
        self.assertTrue(80 <= y0 < center_y < y1 <= 200, target)
        self.assertTrue(250 <= x0 < center_x < x1 <= 560, target)
        self.assertLess(y1, rows["transport resources"][1])
        self.assertEqual(route._route_context(hub, now=10.5), route.ROUTE_CONTEXT_HELP_HUB)

    def test_help_hub_rejects_other_title_rows_or_any_unclear_overlay(self):
        hub = _retained(HELP_HUB_FIXTURE, HELP_HUB_FIXTURE_SHA256)
        menu = _retained(ALLIANCE_MENU_FIXTURE, ALLIANCE_MENU_FIXTURE_SHA256)
        other_title = hub.frame.copy()
        other_title[0:70] = menu.frame[0:70]
        self.assertFalse(route._help_hub(other_title))
        duplicated_row = hub.frame.copy()
        duplicated_row[245:300] = hub.frame[110:165]
        self.assertIsNone(route._help_hub_rows(duplicated_row))
        self.assertIsNone(route._hub_speedup_target(duplicated_row))
        self.assertFalse(route._help_hub(duplicated_row))
        reordered = hub.frame.copy()
        reordered[110:165] = hub.frame[245:300]
        reordered[245:300] = hub.frame[110:165]
        self.assertIsNone(route._hub_speedup_target(reordered))
        self.assertFalse(route._help_hub(reordered))
        self.assertFalse(route._help_hub(hub.frame,
            overlay_reader=lambda _frame: {"recognized": True, "state": "modal"}))

        def failing(_frame):
            raise RuntimeError("overlay recognizer unavailable")

        self.assertFalse(route._help_hub(hub.frame, overlay_reader=failing))

    def test_retained_speedup_help_title_is_recognized_fresh_only_and_is_not_the_menu(self):
        help_source = _retained(route.HELP_SOURCE_PATH)
        observation = route.recognize_help_screen(help_source.frame, captured_at=10.0,
            frame_sha256=help_source.sha256, now=10.5)
        self.assertEqual(observation.screen_state, SOURCE_STATE)
        self.assertTrue(observation.overlay_clear)
        self.assertFalse(route._alliance_menu(help_source.frame))
        self.assertFalse(route._help_hub(help_source.frame))
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
        # Back, open Alliance, open hub, open Speedup Help, then the three terminal Backs.
        self.assertEqual(result["input_count"], 7)
        self.assertEqual(result["input_count"], session.input_count)
        self.assertEqual(result["input_count"], runtime.input_count)

    def test_current_speedup_help_returns_home_before_any_request(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _blocked, session, runtime = _run_replay_route(
                Path(directory) / "help", requests=1, initial_state="help")
        self.assertEqual(result["route_context_recovery"]["verified_navigation"],
                         ["back-speedup-help", "back-help-hub", "back-alliance-home"])
        self.assertEqual(result["status"], "deferred")
        self.assertEqual(result["confirmed_request_count"], 1)
        self.assertEqual(runtime.help_taps, 1)
        self.assertTrue(result["terminal_home_verified"])
        self.assertEqual(result["verified_navigation"],
                         ["back-speedup-help", "back-help-hub", "back-alliance-home"])
        self.assertTrue(result["accounting_verified"])
        # Three recovery Backs, three entry taps, one Help, three terminal Backs.
        self.assertEqual(result["input_count"], 10)
        self.assertEqual(result["input_count"], session.input_count)

    def test_current_help_hub_returns_home_before_normal_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _blocked, session, runtime = _run_replay_route(
                Path(directory) / "hub", requests=1, initial_state="hub")
        recovery = result["route_context_recovery"]
        self.assertEqual(recovery["source_context"], route.ROUTE_CONTEXT_HELP_HUB)
        self.assertEqual(recovery["verified_navigation"], ["back-help-hub", "back-alliance-home"])
        self.assertTrue(recovery["home_verified"])
        self.assertEqual(result["status"], "deferred")
        self.assertEqual(result["confirmed_request_count"], 1)
        self.assertEqual(runtime.help_taps, 1)
        self.assertTrue(result["terminal_home_verified"])
        self.assertTrue(result["accounting_verified"])
        self.assertEqual(result["input_count"], 9)
        self.assertEqual(result["input_count"], session.input_count)

    def test_entry_requires_exact_hub_before_speedup_help_row(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _blocked, session, runtime = _run_replay_route(
                Path(directory) / "nohub", requests=1, menu_opens="unknown")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "alliance_help_hub_successor_unproven")
        self.assertEqual(runtime.help_taps, 0)
        self.assertFalse(any(item[1].startswith("help-hub-speedup-help:") for item in runtime.frame_actions))
        self.assertFalse(result["terminal_home_verified"])
        self.assertEqual(result["input_count"], 2)
        self.assertEqual(result["input_count"], session.input_count)
        self.assertTrue(result["accounting_verified"])

    def test_worst_case_recovery_entry_ten_help_and_return_fit_input_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _blocked, session, runtime = _run_replay_route(
                Path(directory) / "worst", requests=10, initial_state="help")
        self.assertEqual(result["status"], "complete_for_reset")
        self.assertEqual(runtime.help_taps, DAILY_REQUEST_LIMIT)
        self.assertTrue(result["terminal_home_verified"])
        self.assertTrue(result["accounting_verified"])
        self.assertEqual(result["input_count"], 19)
        self.assertLessEqual(result["input_count"], route.MAX_INPUTS)
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
        self.assertEqual({item[1] for item in runtime.frame_actions},
                         {"alliance-help-back:recovery:back-alliance-home"})
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

    def test_unchanged_hub_back_is_unknown_and_never_repeated(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _blocked, session, runtime = _run_replay_route(
                Path(directory) / "stuckhub", requests=1, initial_state="hub", ignore_back=True)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "alliance_help_route_context_recovery_unproven")
        self.assertEqual(result["route_context_recovery"]["verified_navigation"], [])
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(session.input_count, 1)
        self.assertEqual({item[1] for item in runtime.frame_actions},
                         {"alliance-help-back:recovery:back-help-hub"})
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
        self.help_all_available = False
        self.toast_remaining = 0
        self.capture_count = 0
        self.input_count = 0
        self.help_taps = 0
        self.suppress_effects = False
        self.delayed_success = False
        self.pending_effect = False
        self.ignore_back = False
        self.change_before_back = False
        self.menu_opens = "hub"
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
        state_code = {"home": 1, "alliance": 2, "help": 3, "unknown": 4, "hub": 5}[self.state]
        toast = int(self.toast_remaining > 0)
        if toast:
            self.toast_remaining -= 1
        frame[0, 0, :] = (state_code, toast, len(self.requests) & 0xFF)
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
            toast=bool(toast), capture_count=self.capture_count)
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
        target_identity = target_identity.split(":")[0]
        if target_identity == "home-nav-alliance":
            self.state = "alliance"
        elif target_identity == "alliance-menu-help":
            if self.state != "alliance":
                raise ValueError("replay Alliance Help entry is no longer current")
            self.state = self.menu_opens
        elif target_identity == "help-hub-speedup-help":
            if self.state != "hub":
                raise ValueError("replay Speedup Help row is no longer current")
            self.state = "help"
        elif target_identity in {INDIVIDUAL_TARGET_IDENTITY, HELP_ALL_TARGET_IDENTITY}:
            self.help_taps += 1
            if self.state != "help" or not self.requests:
                raise ValueError("replay free Help target is no longer current")
            if not self.suppress_effects:
                if self.delayed_success:
                    self.pending_effect = True
                else:
                    self._confirm_help()
        elif target_identity == "alliance-help-back":
            if self.ignore_back:
                pass
            elif self.state == "help":
                self.state = "hub"
            elif self.state == "hub":
                self.state = "alliance"
            elif self.state == "alliance":
                self.state = "home"
            else:
                raise ValueError("replay Back target has no recognized source")
        else:
            raise ValueError(f"replay refuses target {target_identity}")

    def _confirm_help(self):
        if self.help_all_available:
            self.requests.clear()
        else:
            self.requests.pop(0)
        self.toast_remaining = 1

    def observe(self, frame, *, captured_at, frame_sha256, now=None, **_kwargs):
        saved = self.snapshots[frame_sha256]
        requests = tuple(HelpRequest(request_id, (550, 260, 680, 310), True, True)
                         for request_id in saved.requests)
        return HelpObservation(
            screen_state=SOURCE_STATE if saved.state == "help" else "UNKNOWN",
            captured_at=captured_at, frame_sha256=frame_sha256,
            overlay_clear=True, source_fresh=(now is None or 0 <= now - captured_at <= 30),
            requests=requests, help_all_roi=route.HELP_ALL_ROI if self.help_all_available else None,
            help_all_free=self.help_all_available,
            exact_no_requests_message=(saved.state == "help" and not saved.requests),
            cost_marker_seen=False, help_success_message=saved.toast, help_all_success_count=None,
        )

    def reconcile(self, _action_key, _status, _captured, _reason):
        return None


class _NativeReplayRuntime(LocalBlueStacksRuntime):
    """Real native guards, fingerprints, keys, events and tap transport; offline device."""

    def __init__(self, scene, session):
        self.scene = scene
        targets = {
            box_center((639, 1243, 647, 1251)): ("home-nav-alliance", (639, 1243, 647, 1251)),
            box_center(REPLAY_MENU_HELP_ROI): ("alliance-menu-help", REPLAY_MENU_HELP_ROI),
            box_center(REPLAY_HUB_SPEEDUP_ROI): ("help-hub-speedup-help", REPLAY_HUB_SPEEDUP_ROI),
            box_center(route.HELP_ALL_ROI): (HELP_ALL_TARGET_IDENTITY, route.HELP_ALL_ROI),
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
                      ignore_back: bool = False, change_before_back: bool = False,
                      menu_opens: str = "hub", help_all_available: bool = False):
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
    scene.help_all_available = help_all_available
    scene.suppress_effects = suppress_effects
    scene.delayed_success = delayed_success
    scene.state = initial_state
    scene.ignore_back = ignore_back
    scene.change_before_back = change_before_back
    scene.menu_opens = menu_opens
    patches = (
        patch.object(route, "_home", side_effect=lambda frame: scene.snapshot(frame).state == "home"),
        patch.object(route, "_home_alliance_target",
            side_effect=lambda frame: (639, 1243, 647, 1251)
                if scene.snapshot(frame).state == "home" else None),
        patch.object(route, "_alliance_menu",
            side_effect=lambda frame: scene.snapshot(frame).state == "alliance"),
        patch.object(route, "_menu_help_target", return_value=REPLAY_MENU_HELP_ROI),
        patch.object(route, "_help_hub", side_effect=lambda frame: scene.snapshot(frame).state == "hub"),
        patch.object(route, "_hub_speedup_target", side_effect=lambda frame: REPLAY_HUB_SPEEDUP_ROI
            if scene.snapshot(frame).state == "hub" else None),
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


class _PixelNavigationTransport(ADBRunner):
    """Only device transport is fake; revisited pages have identical PNG bytes."""

    def __init__(self, payloads: dict[str, bytes], *, ignore_back: bool = False):
        super().__init__("offline-adb-not-invoked", "offline-pixel-navigation")
        self.payloads, self.state, self.ignore_back = payloads, "alliance", ignore_back
        self.calls: list[tuple[str, tuple[int, int]]] = []

    def capture_png(self) -> bytes:
        return self.payloads[self.state]

    def dispatch_tap(self, point: tuple[int, int]) -> None:
        self.calls.append((self.state, point))
        if point[1] < 80:
            if not self.ignore_back:
                self.state = {"help": "hub", "hub": "alliance", "alliance": "home"}[self.state]
        else:
            self.state = {"home": "alliance", "alliance": "hub", "hub": "help"}[self.state]


def _run_pixel_navigation(
    directory: Path, *, payloads: dict[str, bytes] | None = None, ignore_back: bool = False,
):
    """Device-free smoke entry point: production runtime, session and recognizers."""
    directory.mkdir(parents=True, exist_ok=True)
    if payloads is None:
        leaf = cv2.imread(str(route.HELP_SOURCE_PATH), cv2.IMREAD_COLOR)
        if leaf is None:
            raise RuntimeError(f"Cannot read Help fixture: {route.HELP_SOURCE_PATH}")
        # Derived no-controls leaf retaining native header/Back, without inventing effects.
        leaf[240:390] = leaf[500:650]
        leaf[1165:1280] = leaf[1000:1115]
        encoded, png = cv2.imencode(".png", leaf)
        if not encoded:
            raise RuntimeError("Cannot encode no-controls Help fixture")
        payloads = {
            "home": (Path(__file__).parent / "fixtures/personal_might/native-home-more-20261029.png").read_bytes(),
            "alliance": ALLIANCE_MENU_FIXTURE.read_bytes(),
            "hub": HELP_HUB_FIXTURE.read_bytes(),
            "help": png.tobytes(),
        }
    transport = _PixelNavigationTransport(payloads, ignore_back=ignore_back)
    now = 1_800_000_000.0
    identity = derive_resource_runtime_identity(resource_fixed_runtime_binding(),
        datetime.fromtimestamp(now, timezone.utc))
    result, error = None, None
    store = SafetyStore(directory / "actions.sqlite3")
    try:
        with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", directory / "lock.sqlite3"):
            session = boundary.DevelopmentSession(owner="help-native-replay",
                invocation_id="help-native-replay", session_directory=directory / "session",
                max_inputs=route.MAX_INPUTS)
            try:
                with session:
                    runtime = LocalBlueStacksRuntime(transport, session.session_directory / "native", execute=True)
                    runtime.max_inputs = route.MAX_INPUTS
                    result = route.run_alliance_help(session=session, runtime=runtime,
                        store=store, identity=identity, validate_identity=lambda: None,
                        occurrence_key="occ:pixel-navigation", settle_seconds=0,
                        utc_clock=lambda: now)
            except RuntimeError as exc:
                error = str(exc)
    finally:
        store.close()
    return result, error, session, runtime, transport


class AllianceHelpNativeNavigationIdentityTests(unittest.TestCase):
    def test_identical_revisited_pixels_need_distinct_verified_step_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result, error, session, runtime, transport = _run_pixel_navigation(root / "fixed")
            self.assertIsNone(error)
            assert result is not None
            self.assertEqual(result["status"], "deferred")
            self.assertTrue(result["terminal_home_verified"])
            self.assertTrue(result["accounting_verified"])
            self.assertEqual(result["help_transport_calls"], 0)
            self.assertEqual(result["input_count"], 7)
            self.assertEqual(session.input_count, runtime.input_count)
            self.assertEqual(runtime.input_count, len(transport.calls))
            self.assertEqual([state for state, _point in transport.calls],
                             ["alliance", "home", "alliance", "hub", "help", "hub", "alliance"])
            evidence = runtime.events.read_bytes()
            events = [json.loads(line) for line in evidence.splitlines()]
            dispatches = [item for item in events if item["type"] == "dispatch"]
            self.assertEqual(len(dispatches), 7)
            self.assertEqual(len({item["action_key"] for item in dispatches}), 7)
            self.assertEqual(dispatches[0]["source_sha256"], dispatches[-1]["source_sha256"])
            self.assertEqual(dispatches[0]["target_roi"], dispatches[-1]["target_roi"])
            self.assertNotEqual(dispatches[0]["target_identity"], dispatches[-1]["target_identity"])
            for item in events:
                if item["type"] == "capture":
                    self.assertEqual(hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest(), item["sha256"])
            self.assertEqual(runtime.events.read_bytes(), evidence)

    def test_native_unchanged_back_stops_after_one_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, error, session, runtime, transport = _run_pixel_navigation(Path(temporary), ignore_back=True)
            self.assertIsNone(error)
            assert result is not None
            self.assertFalse(result["terminal_home_verified"])
            self.assertTrue(result["accounting_verified"])
            self.assertEqual(result["input_count"], 1)
            self.assertEqual(result["help_transport_calls"], 0)
            self.assertEqual(session.input_count, 1)
            self.assertEqual(session.input_count, runtime.input_count)
            self.assertEqual(runtime.input_count, len(transport.calls))
            self.assertEqual(len(transport.calls), 1)


if __name__ == "__main__":
    unittest.main()
