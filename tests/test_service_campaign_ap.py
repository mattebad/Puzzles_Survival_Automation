"""Canonical AP admission and native execution with all device access forbidden."""
from contextlib import ExitStack, closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest

import cv2
import numpy as np
from unittest.mock import patch

from automation_service import campaign as ap
from automation_service.contracts import SchedulerFacts
from automation_service.registry import (
    CAMPAIGN_FLOW_ID, CAMPAIGN_PRODUCT_ID, CAMPAIGN_PRODUCT_REVISION, CANONICAL_FLOW_REGISTRY,
)
from automation_service.recruitment import recruitment_reset
from automation_service.service import AutomationService
from automation_service.state import BotStateManager
from safe_action_core import SafetyStore
from scripts import bluestacks_campaign_ap as native
from scripts import navigation_development_boundary as development_boundary
from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
from tasks.campaign_auto_battle import (
    CAMPAIGN_DRAIN_MAX_RUNS, CAMPAIGN_MAX_INPUTS, CampaignRouteObservation, CampaignScreen,
)
from tasks.campaign_auto_battle_vision import CampaignFrameRecognition, recognize_campaign_frame
from tasks.scheduler_task_result import SchedulerIdentity
from tests.test_campaign_ap_native_runner import DrainFakeADB, FakeADB, PHASES, recognize, recognize_drain
from tests.test_service_recruitment import VirtualStop


def _zero_input_native_stop(**changes):
    return dict({
        "status": "blocked_fail_closed", "reason": "TARGET_ROI_CHANGED",
        "destination": "1-15-9", "ap_cost": 14, "ap_before": 120, "ap_after": 120,
        "total_input_count": 0, "input_count": 0, "navigation_input_count": 0,
        "stage_entry_transport_count": 0, "new_battle_count": 0, "committed_ap_effect_count": 0,
        "effect_reconciliation_required": False, "terminal_home_verified": True,
        "progress": {"initial_ap": 120, "current_ap": 120, "ap_spent": 0,
                     "completed_runs": 0, "ap_regenerated": 0, "loss_seen": False},
    }, **changes)


class CampaignServiceRunnerTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.now = 1_800_000_000.0
        self.identity = SchedulerIdentity("account", "server", recruitment_reset(self.now), CAMPAIGN_FLOW_ID)
        self.world = FakeADB("home")
        self.home_ap = 120
        self.post_ap = None
        self.unknown_home = False
        self.stopped = False
        self.checkpoints = 0
        self.runtimes = []
        self.store_path = self.root / "actions.sqlite3"
        self.store_opens = 0
        self.connect = self.stack.enter_context(patch.object(LocalBlueStacksRuntime, "connect", side_effect=self.runtime))
        self.stack.enter_context(patch.object(LocalBlueStacksRuntime, "measure_foreground_package",
                                             return_value="com.global.ztmslg"))
        self.stack.enter_context(patch("scripts.navigation_development_boundary.open_canonical_action_store",
                                      side_effect=self.action_store))
        self.stack.enter_context(patch.object(ap, "recognize_campaign_frame", side_effect=self.recognize))
        self.stack.enter_context(patch.object(ap, "is_clean_home_frame", side_effect=self.clean_home))
        self.stack.enter_context(patch.object(native, "recognize_campaign_frame", side_effect=self.recognize))
        self.stack.enter_context(patch.object(native, "run_verified_campaign_home_atlas_entry", side_effect=self.atlas))
        self.runner = ap.CampaignRunner(adb="FORBIDDEN", serial="emulator-5554", output_directory=self.root,
                                        cadence_seconds=900, utc_clock=lambda: self.now,
                                        monotonic_clock=time.monotonic, settle_seconds=0)

    def runtime(self, **_kwargs):
        runtime = LocalBlueStacksRuntime(self.world, self.root / f"native-{len(self.runtimes)}", execute=True)
        self.runtimes.append(runtime)
        return runtime

    def action_store(self):
        self.store_opens += 1
        return SafetyStore(self.store_path)

    def checkpoint(self):
        self.checkpoints += 1
        if self.stopped:
            raise RuntimeError("STOP_REQUESTED")

    def clean_home(self, frame):
        return PHASES[int(frame[0, 0, 0])] in {"home", "returned-home"}

    def recognize(self, frame, stage, **kwargs):
        found = (recognize_drain(frame, stage, world=self.world, **kwargs)
                 if isinstance(self.world, DrainFakeADB) else recognize(frame, stage, **kwargs))
        if self.unknown_home:
            return CampaignFrameRecognition(
                CampaignRouteObservation(screen=CampaignScreen.UNKNOWN, recognized=False),
                found.frame_sha256, (), {})
        if isinstance(self.world, DrainFakeADB):
            return found
        phase = PHASES[int(frame[0, 0, 0])]
        if found.observation.ap_current is not None and self.post_ap is not None:
            observed_ap = self.home_ap if phase in {"home", "stage", "wrong-stage"} else self.post_ap
            found = replace(found, observation=replace(found.observation, ap_current=observed_ap))
        elif found.observation.screen is CampaignScreen.HOME_BASE and phase == "home":
            found = replace(found, observation=replace(found.observation, ap_current=self.home_ap))
        return found

    def one_battle_drain(self):
        self.home_ap, self.post_ap = 14, 0
        return self.runner(self.identity, None, self.checkpoint)

    def atlas(self, runtime, **_kwargs):
        source = runtime.capture("test-atlas-entry")
        runtime.tap(source, target_identity="home.building.campaign", target_roi=(400, 500, 500, 600),
                    action_key=f"test-atlas-entry:{runtime.input_count}")
        return {"status": "opened", "navigation_input_count": 1}

    def camera_stop(self, runtime, *_args, **_kwargs):
        source = runtime.capture("navigate-pan-pre-dispatch")
        runtime.swipe(source, start=(450, 500), end=(300, 514), target_identity="home-camera-click-drag",
                      action_key="nav-pan:test-camera:1")
        runtime.capture("campaign-entry-00-settled")
        result = _zero_input_native_stop(total_input_count=1, input_count=1, navigation_input_count=1)
        (runtime.session / "result.json").write_text(json.dumps(result, sort_keys=True) + "\n")
        return result

    def facts(self, projection, *, now=None):
        return SchedulerFacts(
            self.identity.account_id, self.identity.server_id, self.identity.reset_id, self.now if now is None else now,
            health_ok=True, accepted_product=CAMPAIGN_PRODUCT_ID, product_revision=CAMPAIGN_PRODUCT_REVISION,
            registration_status="REGISTERED", scheduler_eligible=True, owner_available=True,
            clock_ok=True, reset_agreement=True, projections={CAMPAIGN_FLOW_ID: projection})

    def test_construction_has_no_device_or_action_store_access(self):
        self.connect.assert_not_called()
        self.assertEqual(self.store_opens, 0)
        self.assertEqual(self.world.inputs, [])

    def test_native_home_ap_admission_binds_real_resource_row_and_capture(self):
        fixture = Path("tests/fixtures/campaign_ap_hud/home-ap100-stamina120.png")
        self.world.capture_png = fixture.read_bytes
        with patch.object(ap, "recognize_campaign_frame", new=recognize_campaign_frame), \
                patch.object(ap, "is_clean_home_frame", return_value=True):
            admission = self.runner._read_home(self.runner._connect(self.checkpoint, "test-claimed-home"), self.identity, self.checkpoint, "test-home")
        self.assertEqual(admission.identity, self.identity)
        self.assertEqual(admission.stage_identity, "1-15-9")
        self.assertEqual(admission.ap_current, 100)
        self.assertEqual(admission.observed_at_utc, self.now)
        self.assertEqual(admission.profile_id, "pns-bluestacks-5-p64-800x1280-v1")
        self.assertEqual(admission.frame_sha256, hashlib.sha256(Path(admission.frame_path).read_bytes()).hexdigest())
        self.assertEqual(self.world.inputs, [])
        self.assertEqual(self.store_opens, 0)
        self.assertGreater(self.checkpoints, 0)

    def test_real_execution_admission_allows_no_work_but_retains_freshness_and_selector_funding_guards(self):
        admission = self.runner._read_home(self.runner._connect(self.checkpoint, "test-claimed-home"), self.identity, self.checkpoint, "test-home")
        projection = admission.projection(generation="accepted-ap-generation")
        snapshot = next(item.registration for item in CANONICAL_FLOW_REGISTRY if item.flow_id == CAMPAIGN_FLOW_ID)
        handler = ap.CampaignExecutionHandler(snapshot, lambda *_args: self.fail("selection dispatched input"))
        self.assertTrue(handler.eligibility(self.facts(projection)))
        self.assertFalse(handler.eligibility(self.facts(projection, now=self.now + 301)))
        self.assertTrue(handler.eligibility(self.facts(replace(projection, observed_balance=0))))
        expensive = ap.CampaignExecutionHandler(snapshot, lambda *_args: None, stage="2-2-9")
        self.assertTrue(expensive.eligibility(self.facts(replace(projection, observed_balance=19))))
        selector = ap.CampaignApSelectionHandler(snapshot)
        self.assertFalse(selector.eligibility(self.facts(replace(projection, observed_balance=13))))
        self.assertTrue(selector.eligibility(self.facts(replace(projection, observed_balance=14))))
        with self.assertRaises(ValueError):
            ap.CampaignExecutionHandler(snapshot, lambda *_args: None, stage="1-99-9")
        self.assertEqual(self.world.inputs, [])

    def test_complete_drain_reuses_real_policy_native_controller_with_last_affordable_battle(self):
        result = self.one_battle_drain()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["campaign_dispatch_count"], 1)
        self.assertEqual(result["stage_entry_transport_count"], 1)
        self.assertEqual(result["new_battle_count"], 1)
        self.assertEqual(result["committed_ap_effect_count"], 1)
        self.assertEqual(result["progress"]["ap_spent"], 14)
        self.assertEqual(result["progress"]["completed_runs"], 1)
        self.assertEqual(result["total_input_count"], len(self.world.inputs))
        self.assertTrue(result["terminal_home_verified"])
        self.assertFalse(result["effect_reconciliation_required"])
        self.assertEqual(result["completed_at_utc"], self.now)
        self.assertEqual(result["next_eligible_at"], self.now + 900)
        self.assertEqual(ap.campaign_next_due(result, self.identity, self.now - 1), self.now + 900)
        with closing(sqlite3.connect(self.store_path)) as store:
            row = store.execute("SELECT final_status,cost_type,cost_amount FROM actions").fetchone()
        self.assertEqual(tuple(row), ("confirmed", "AP", 14))

    def test_full_drain_uses_real_native_loop_and_individual_policy_entries_with_regeneration(self):
        self.world = DrainFakeADB(ap=120, regen_per_battle=(6,))
        result = self.runner(self.identity, None, self.checkpoint)
        self.assertEqual(result["status"], "completed")
        self.assertEqual((result["ap_before"], result["ap_after"]), (120, 0))
        self.assertEqual(result["progress"]["ap_spent"], 126)
        self.assertEqual(result["progress"]["ap_regenerated"], 6)
        self.assertEqual(result["progress"]["completed_runs"], 9)
        self.assertEqual(result["stage_entry_transport_count"], 9)
        self.assertEqual(result["new_battle_count"], 9)
        self.assertEqual(result["campaign_dispatch_count"], 9)
        self.assertEqual(result["committed_ap_effect_count"], 9)
        self.assertEqual((self.world.battles_started, self.world.victories), (9, 9))
        self.assertEqual(result["total_input_count"], len(self.world.inputs))
        self.assertGreater(result["total_input_count"], 16)
        self.assertTrue(result["terminal_home_verified"])
        self.assertEqual(ap.campaign_next_due(result, self.identity, self.now - 1), self.now + 900)
        with closing(sqlite3.connect(self.store_path)) as store:
            rows = store.execute("SELECT final_status,cost_type,cost_amount FROM actions").fetchall()
        self.assertEqual(len(rows), 9)
        self.assertTrue(all(tuple(row) == ("confirmed", "AP", 14) for row in rows))
        self.assertEqual(len(result["entry_action_keys"]), len(set(result["entry_action_keys"])))

    def test_unknown_third_battle_keeps_two_native_reconciled_effects_and_no_next_due(self):
        self.world = DrainFakeADB(ap=88)
        self.world.on_input = lambda _count: setattr(self, "stopped", True) if self.world.battles_started == 3 else None
        with self.assertRaises(ap.CampaignApRunnerError) as raised:
            self.runner(self.identity, None, self.checkpoint)
        result = raised.exception.partial_result
        self.assertEqual(result["progress"]["completed_runs"], 2)
        self.assertEqual(result["progress"]["ap_spent"], 28)
        self.assertEqual(result["committed_ap_effect_count"], 2)
        self.assertEqual(result["stage_entry_transport_count"], 3)
        self.assertEqual(result["new_battle_count"], 3)
        self.assertEqual(result["campaign_dispatch_count"], 3)
        self.assertEqual(result["total_input_count"], len(self.world.inputs))
        self.assertTrue(result["effect_reconciliation_required"])
        self.assertTrue(result["identical_retry_denied"])
        self.assertIsNone(result["next_eligible_at"])
        with self.assertRaises(ValueError):
            ap.campaign_next_due(result, self.identity, self.now - 1)

    def test_fresh_terminal_home_regeneration_continues_same_native_invocation(self):
        self.world = DrainFakeADB(ap=27)
        connect = self.runtime
        restored = False
        def runtime(**kwargs):
            current = connect(**kwargs)
            capture = current.capture
            def capture_with_regeneration(label):
                nonlocal restored
                if label == "campaign-route-terminal-home" and not restored:
                    self.assertEqual(self.world.ap, 13)
                    self.world.ap, restored = 14, True
                return capture(label)
            current.capture = capture_with_regeneration
            return current
        with patch.object(LocalBlueStacksRuntime, "connect", side_effect=runtime), \
                patch.object(native, "run_campaign_ap_route", wraps=native.run_campaign_ap_route) as run_route:
            result = self.runner(self.identity, None, self.checkpoint)
        self.assertEqual(run_route.call_count, 1)
        self.assertEqual(len(self.runtimes), 1)
        self.assertEqual(result["status"], "completed")
        self.assertEqual((self.world.battles_started, self.world.victories), (2, 2))
        self.assertEqual(result["committed_ap_effect_count"], 2)
        self.assertEqual(result["progress"]["ap_spent"], 28)
        self.assertEqual(result["progress"]["ap_regenerated"], 1)
        self.assertEqual(result["ap_after"], 0)
        self.assertEqual(result["home_ap_observation"]["ap_current"], 0)
        self.assertEqual(result["terminal_home_frame"], result["home_ap_observation"]["frame_path"])
        self.assertEqual(result["terminal_home_sha256"], result["home_ap_observation"]["frame_sha256"])
        self.assertEqual(result["next_eligible_at"], self.now + 900)

    def test_serve_claim_crosses_midnight_during_battle_or_late_home_and_next_due_uses_new_day(self):
        midnight = (int(self.now) // 86400 + 1) * 86400
        self.runner.cadence_seconds = 300
        for crossing in ("battle", "terminal_home"):
            with self.subTest(crossing=crossing):
                stop = VirtualStop(midnight - 10)
                stop.on_wait = stop.set
                self.runner.utc_clock = lambda: stop.now
                self.world = DrainFakeADB(ap=28 if crossing == "battle" else 27)
                self.store_path = self.root / f"actions-midnight-{crossing}.sqlite3"
                crossed = False
                def advance_midbattle(_count):
                    nonlocal crossed
                    if crossing == "battle" and not crossed and self.world.battles_started == 1:
                        stop.now, crossed = midnight + 1, True
                self.world.on_input = advance_midbattle
                connect = self.runtime
                def runtime(**kwargs):
                    current = connect(**kwargs)
                    capture = current.capture
                    def capture_terminal(label):
                        nonlocal crossed
                        if crossing == "terminal_home" and not crossed and label == "campaign-route-terminal-home":
                            self.assertEqual(self.world.ap, 13)
                            self.world.ap = 14
                            stop.now, crossed = midnight + 1, True
                        return capture(label)
                    current.capture = capture_terminal
                    return current
                observed_identities = []
                read_home = self.runner._read_home
                def observe(runtime, identity, checkpoint, label, **kwargs):
                    if label == "campaign-service-initial-home":
                        observed_identities.append(identity)
                    return read_home(runtime, identity, checkpoint, label, **kwargs)
                def serve(state):
                    reports = []
                    service = AutomationService(mode="supervised", state=state, campaign_runner=self.runner)
                    service.serve(account_id="account", server_id="server", stop=stop,
                                  emit=lambda report: (reports.append(report), stop.set()),
                                  clock=lambda: stop.now, flow_ids=(CAMPAIGN_FLOW_ID,))
                    return reports
                path = self.root / f"service-midnight-{crossing}.sqlite3"
                with patch.object(development_boundary, "RUNTIME_INPUT_LOCK_PATH",
                                  self.root / f"runtime-midnight-{crossing}.sqlite3"), \
                        patch.object(LocalBlueStacksRuntime, "connect", side_effect=runtime), \
                        patch.object(self.runner, "_read_home", side_effect=observe), \
                        patch.object(native, "run_campaign_ap_route", wraps=native.run_campaign_ap_route) as run_native:
                    with BotStateManager(path) as state:
                        controls = AutomationService(mode="supervised", state=state, campaign_runner=self.runner)
                        controls.set_service_enabled(True)
                        controls.set_flow_enabled(CAMPAIGN_FLOW_ID, True)
                        report, = serve(state)
                        self.assertEqual(report["status"], "completed", report)
                        result = report["result"]
                        old_reset = recruitment_reset(midnight - 10)
                        self.assertEqual(result["reset_id"], old_reset)
                        self.assertEqual(result["home_ap_observation"]["reset_id"], old_reset)
                        self.assertEqual(result["completed_at_utc"], midnight + 1)
                        self.assertEqual(result["progress"]["completed_runs"], 2)
                        self.assertEqual(result["progress"]["ap_spent"], 28)
                        self.assertEqual(result["progress"]["ap_regenerated"], int(crossing == "terminal_home"))
                        self.assertEqual(result["ap_after"], 0)
                        self.assertTrue(result["terminal_home_verified"])
                        due = midnight + 301
                        self.assertEqual(state.get_flow(CAMPAIGN_FLOW_ID).next_due_at_utc, due)
                        first_run, = state._db.execute("SELECT reset_id,consumed_inputs,consumed_actions FROM runs").fetchall()
                        self.assertEqual(tuple(first_run), (old_reset, len(self.world.inputs), 2))
                    inputs, connections = len(self.world.inputs), len(self.runtimes)
                    stop = VirtualStop(midnight + 2)
                    stop.on_wait = stop.set
                    with BotStateManager(path) as state:
                        self.assertEqual(serve(state), [])
                    self.assertEqual(len(self.runtimes), connections)
                    self.assertEqual(len(self.world.inputs), inputs)
                    self.assertEqual(len(observed_identities), 1)
                    stop = VirtualStop(due)
                    stop.on_wait = stop.set
                    with BotStateManager(path) as state:
                        deferred, = serve(state)
                        self.assertEqual(deferred["status"], "completed", deferred)
                        self.assertEqual(deferred["result"]["status"], "deferred")
                        self.assertEqual(deferred["result"]["reset_id"], recruitment_reset(due))
                        self.assertEqual(deferred["result"]["total_input_count"], 0)
                        self.assertEqual(state.get_flow(CAMPAIGN_FLOW_ID).next_due_at_utc, due + 300)
                    self.assertEqual([item.reset_id for item in observed_identities], [old_reset, recruitment_reset(due)])
                    self.assertEqual(run_native.call_count, 1)
                    self.assertEqual(len(self.world.inputs), inputs)
                with closing(sqlite3.connect(self.store_path)) as store:
                    rows = store.execute("SELECT final_status,game_day_id,cost_amount FROM actions").fetchall()
                self.assertEqual([tuple(row) for row in rows], [("confirmed", old_reset, 14)] * 2)

    def test_stop_after_stage_preserves_entry_count_and_cannot_launch_lineup(self):
        self.world.on_input = lambda count: setattr(self, "stopped", True) if count == 2 else None
        with self.assertRaises(ap.CampaignApRunnerError) as raised:
            self.runner(self.identity, None, self.checkpoint)
        result = raised.exception.partial_result
        self.assertEqual(result["total_input_count"], 2)
        self.assertEqual(result["stage_entry_transport_count"], 1)
        self.assertEqual(result["campaign_dispatch_count"], 1)
        self.assertEqual(result["new_battle_count"], 0)
        self.assertEqual(result["committed_ap_effect_count"], 0)
        self.assertTrue(result["effect_reconciliation_required"])
        self.assertTrue(result["identical_retry_denied"])
        self.assertEqual(len(self.world.inputs), 2)

    def test_stop_after_lineup_preserves_one_pending_effect_without_double_count(self):
        self.world.on_input = lambda count: setattr(self, "stopped", True) if count == 3 else None
        with self.assertRaises(ap.CampaignApRunnerError) as raised:
            self.runner(self.identity, None, self.checkpoint)
        result = raised.exception.partial_result
        self.assertEqual(result["total_input_count"], 3)
        self.assertEqual(result["stage_entry_transport_count"], 1)
        self.assertEqual(result["new_battle_count"], 1)
        self.assertEqual(result["campaign_dispatch_count"], 1)
        self.assertEqual(result["committed_ap_effect_count"], 0)
        self.assertTrue(result["effect_reconciliation_required"])
        self.assertTrue(result["identical_retry_denied"])
        self.assertEqual(len(self.world.inputs), 3)

    def test_unknown_or_non_home_initial_context_cannot_dispatch(self):
        for unknown, phase in ((True, "home"), (False, "stage")):
            with self.subTest(unknown=unknown, phase=phase):
                self.unknown_home, self.world.phase = unknown, phase
                with self.assertRaises(ap.CampaignApRunnerError) as raised:
                    self.runner(self.identity, None, self.checkpoint)
                self.assertEqual(raised.exception.partial_result["total_input_count"], 0)
                self.assertTrue(raised.exception.partial_result["effect_reconciliation_required"])
        self.assertEqual(self.world.inputs, [])

    def test_proven_zero_input_stop_preserves_no_effect_but_cannot_schedule_or_retry(self):
        with patch.object(native, "run_campaign_ap_route", return_value=_zero_input_native_stop()):
            with self.assertRaises(ap.CampaignApRunnerError) as raised:
                self.runner(self.identity, None, self.checkpoint)
        result = raised.exception.partial_result
        self.assertEqual(result["status"], "unresolved")
        self.assertEqual(result["reason"], "TARGET_ROI_CHANGED")
        self.assertTrue(result["accounting_verified"])
        self.assertEqual(result["total_input_count"], 0)
        self.assertEqual(result["campaign_dispatch_count"], 0)
        self.assertFalse(result["effect_reconciliation_required"])
        self.assertTrue(result["identical_retry_denied"])
        self.assertEqual(self.world.inputs, [])
        with self.assertRaises(ValueError):
            ap.campaign_next_due(result, self.identity, self.now - 1)

    def test_inconsistent_zero_input_counts_or_ap_ledger_still_require_reconciliation(self):
        baseline = _zero_input_native_stop()
        variants = (
            {"input_count": 1}, {"total_input_count": True}, {"navigation_input_count": 1},
            {"campaign_dispatch_count": 1},
            {"stage_entry_transport_count": False}, {"new_battle_count": None},
            {"committed_ap_effect_count": True}, {"accounting_verified": False},
            {"effect_reconciliation_required": True}, {"ap_after": 119}, {"ap_cost": 20},
            {"destination": "2-2-9"}, {"progress": None},
            {"progress": dict(baseline["progress"], completed_runs=True)},
            {"progress": dict(baseline["progress"], current_ap=119, ap_spent=1), "ap_after": 119},
            {"progress": dict(baseline["progress"], current_ap=119, ap_regenerated=1, ap_spent=2),
             "ap_after": 119},
        )
        for changed in variants:
            with self.subTest(changed=changed):
                with patch.object(native, "run_campaign_ap_route", return_value=dict(baseline, **changed)):
                    with self.assertRaises(ap.CampaignApRunnerError) as raised:
                        self.runner(self.identity, None, self.checkpoint)
                result = raised.exception.partial_result
                self.assertEqual(result["total_input_count"], 0)
                self.assertTrue(result["effect_reconciliation_required"])
                self.assertTrue(result["identical_retry_denied"])
                self.assertEqual(self.world.inputs, [])

    def test_nonzero_navigation_or_unknown_native_failure_stays_closed(self):
        def navigation_then_stop(runtime, *_args, **_kwargs):
            source = runtime.capture("test-one-known-navigation")
            runtime.tap(source, target_identity="home.building.campaign", target_roi=(400, 500, 500, 600),
                        action_key="test-one-known-navigation")
            return _zero_input_native_stop(input_count=1, total_input_count=1, navigation_input_count=1)

        with patch.object(native, "run_campaign_ap_route", side_effect=navigation_then_stop):
            with self.assertRaises(ap.CampaignApRunnerError) as raised:
                self.runner(self.identity, None, self.checkpoint)
        self.assertEqual(raised.exception.partial_result["total_input_count"], 1)
        self.assertTrue(raised.exception.partial_result["effect_reconciliation_required"])
        self.assertEqual(len(self.world.inputs), 1)
        self.world = FakeADB("home")
        with patch.object(native, "run_campaign_ap_route", side_effect=RuntimeError("unknown native failure")):
            with self.assertRaises(ap.CampaignApRunnerError) as raised:
                self.runner(self.identity, None, self.checkpoint)
        self.assertEqual(raised.exception.partial_result["total_input_count"], 0)
        self.assertTrue(raised.exception.partial_result["effect_reconciliation_required"])
        self.assertEqual(self.world.inputs, [])

    def test_cleanup_error_preserves_proven_zero_input_no_effect_and_blocked_status(self):
        def action_store():
            store = self.action_store()
            original_close = store.close
            def close():
                original_close()
                raise RuntimeError("close failed")
            store.close = close
            return store

        with patch.object(native, "run_campaign_ap_route", return_value=_zero_input_native_stop()), \
                patch("scripts.navigation_development_boundary.open_canonical_action_store", side_effect=action_store):
            with self.assertRaises(ap.CampaignApRunnerError) as raised:
                self.runner(self.identity, None, self.checkpoint)
        result = raised.exception.partial_result
        self.assertEqual(result["status"], "unresolved")
        self.assertIn("TARGET_ROI_CHANGED", result["reason"])
        self.assertIn("close failed", result["reason"])
        self.assertEqual(result["total_input_count"], 0)
        self.assertTrue(result["accounting_verified"])
        self.assertFalse(result["effect_reconciliation_required"])
        self.assertTrue(result["identical_retry_denied"])
        self.assertEqual(self.world.inputs, [])

    def test_exact_camera_only_journal_requires_new_home_ap_capture_before_no_effect(self):
        with patch.object(native, "run_campaign_ap_route", side_effect=self.camera_stop):
            with self.assertRaises(ap.CampaignApRunnerError) as raised:
                self.runner(self.identity, None, self.checkpoint)
        result = raised.exception.partial_result
        runtime = self.runtimes[-1]
        proof = result["camera_only_no_effect_proof"]
        self.assertEqual(result["status"], "unresolved")
        self.assertTrue(result["identical_retry_denied"])
        self.assertTrue(result["accounting_verified"])
        self.assertFalse(result["effect_reconciliation_required"])
        self.assertEqual(result["total_input_count"], 1)
        self.assertEqual(len(self.world.inputs), 1)
        self.assertEqual(self.world.inputs[0][0], "swipe")
        self.assertIs(proof["input_authority"], False)
        self.assertEqual(proof["camera_inputs"], 1)
        fresh = proof["home_ap_observation"]
        self.assertEqual(fresh["ap_current"], 120)
        self.assertIn("campaign-service-failed-camera-home", fresh["frame_path"])
        self.assertEqual(hashlib.sha256(Path(fresh["frame_path"]).read_bytes()).hexdigest(), fresh["frame_sha256"])
        original = json.loads((runtime.session / "result.json").read_text())
        self.assertEqual(original, _zero_input_native_stop(total_input_count=1, input_count=1, navigation_input_count=1))
        self.assertNotIn("camera_only_no_effect_proof", original)
        with self.assertRaises(ValueError):
            ap.campaign_next_due(result, self.identity, self.now - 1)

    def test_missing_foreign_or_changed_camera_journal_cannot_establish_no_effect(self):
        for corruption in ("missing_dispatch", "unknown_input", "changed_source", "extra_key", "uncalibrated"):
            with self.subTest(corruption=corruption):
                self.world = FakeADB("home")
                def tampered_stop(runtime, *_args, **_kwargs):
                    result = self.camera_stop(runtime)
                    rows = [json.loads(line) for line in runtime.events.read_text().splitlines()]
                    if corruption == "missing_dispatch":
                        rows = [row for row in rows if row["type"] != "dispatch"]
                    elif corruption == "unknown_input":
                        next(row for row in rows if row["type"] == "dispatch")["target_identity"] = "unknown-control"
                    elif corruption == "changed_source":
                        source = next(row for row in rows if row.get("label") == "navigate-pan-pre-dispatch")
                        Path(source["path"]).write_bytes(b"changed test-only source")
                    elif corruption == "uncalibrated":
                        next(row for row in rows if row["type"] == "dispatch")["end"] = [449, 500]
                    else:
                        runtime.action_keys.add("unknown-extra-input")
                    runtime.events.write_text("".join(json.dumps(row) + "\n" for row in rows))
                    return result
                with patch.object(native, "run_campaign_ap_route", side_effect=tampered_stop):
                    with self.assertRaises(ap.CampaignApRunnerError) as raised:
                        self.runner(self.identity, None, self.checkpoint)
                result = raised.exception.partial_result
                self.assertTrue(result["effect_reconciliation_required"])
                self.assertNotIn("camera_only_no_effect_proof", result)
                self.assertEqual(result["total_input_count"], 1)
                self.assertEqual(len(self.world.inputs), 1)

    def test_old_home_aliases_cannot_replace_fresh_home_and_unchanged_ap(self):
        for unknown_home, ap_after in ((True, 120), (False, 119)):
            with self.subTest(unknown_home=unknown_home, ap_after=ap_after):
                self.world, self.unknown_home, self.home_ap = FakeADB("home"), False, 120
                def changed_successor(runtime, *_args, **_kwargs):
                    result = self.camera_stop(runtime)
                    self.unknown_home, self.home_ap = unknown_home, ap_after
                    return result
                with patch.object(native, "run_campaign_ap_route", side_effect=changed_successor):
                    with self.assertRaises(ap.CampaignApRunnerError) as raised:
                        self.runner(self.identity, None, self.checkpoint)
                result = raised.exception.partial_result
                self.assertTrue(result["effect_reconciliation_required"])
                self.assertNotIn("camera_only_no_effect_proof", result)
                self.assertTrue(result["identical_retry_denied"])
                self.assertEqual(result["total_input_count"], 1)
                self.assertEqual(len(self.world.inputs), 1)

    def test_input_during_camera_inspection_is_counted_and_cannot_publish_no_effect(self):
        read_home = self.runner._read_home
        def changed_during_inspection(runtime, identity, checkpoint, label, **kwargs):
            home = read_home(runtime, identity, checkpoint, label, **kwargs)
            if label == "campaign-service-failed-camera-home":
                source = runtime.capture("test-unexpected-input-source")
                runtime.tap(source, target_identity="unknown-control", target_roi=(400, 500, 500, 600),
                            action_key="test-unexpected-input")
            return home
        with patch.object(native, "run_campaign_ap_route", side_effect=self.camera_stop), \
                patch.object(self.runner, "_read_home", side_effect=changed_during_inspection):
            with self.assertRaises(ap.CampaignApRunnerError) as raised:
                self.runner(self.identity, None, self.checkpoint)
        result = raised.exception.partial_result
        self.assertEqual(result["total_input_count"], 2)
        self.assertEqual(len(self.world.inputs), 2)
        self.assertFalse(result["accounting_verified"])
        self.assertTrue(result["effect_reconciliation_required"])
        self.assertTrue(result["identical_retry_denied"])
        self.assertNotIn("camera_only_no_effect_proof", result)

    def test_insufficient_home_ap_defers_without_resource_authority_or_input(self):
        self.home_ap = 13
        result = self.runner(self.identity, None, self.checkpoint)
        self.assertEqual(result["status"], "deferred")
        self.assertEqual((result["ap_before"], result["ap_after"]), (13, 13))
        self.assertTrue(result["terminal_home_verified"])
        self.assertEqual(result["total_input_count"], 0)
        self.assertEqual(result["campaign_dispatch_count"], 0)
        self.assertEqual(result["committed_ap_effect_count"], 0)
        self.assertFalse(result["effect_reconciliation_required"])
        self.assertEqual(ap.campaign_next_due(result, self.identity, self.now - 1), self.now + 900)
        self.assertEqual(self.world.inputs, [])

    def test_composed_vip_chapter_tier_home_ap12_defers_under_one_claim(self):
        # Retained popup and Home images are combined with synthetic navigation
        # successors. This scenario is an offline test, not a live receipt.
        fixture = Path("tests/fixtures/campaign_startup_recovery")
        popup = (fixture / "vip-chapter-source.png").read_bytes()
        home = (fixture / "home-ap12-source.png").read_bytes()
        self.assertEqual(hashlib.sha256(home).hexdigest(),
                         "bb74ff8f02809a2ba77435ba481e4638e0befe4a359d66e754d2a2574ad6caf3")
        home_pixels = cv2.imdecode(np.frombuffer(home, np.uint8), cv2.IMREAD_COLOR)

        class ComposedFake(FakeADB):
            def __init__(self):
                super().__init__("popup")
            def capture_png(self):
                if self.phase == "popup":
                    return popup
                if self.phase == "returned-home":
                    return home
                return super().capture_png()
            def dispatch_tap(self, point):
                if self.phase == "popup":
                    self.inputs.append(("tap", point))
                    self.phase = "chapter"
                    if self.on_input:
                        self.on_input(len(self.inputs))
                else:
                    super().dispatch_tap(point)

        self.world = ComposedFake()
        self.runner.cadence_seconds = 300
        def recognize_composed(frame, stage, **kwargs):
            if np.array_equal(frame, home_pixels):
                return recognize_campaign_frame(frame, stage, **kwargs)
            return recognize(frame, stage, **kwargs)
        from scripts.startup_normalization import is_clean_home_frame
        with patch.object(ap, "recognize_campaign_frame", side_effect=recognize_composed), \
                patch("tasks.campaign_auto_battle_vision.recognize_campaign_frame", side_effect=recognize_composed), \
                patch.object(ap, "is_clean_home_frame", side_effect=is_clean_home_frame), \
                patch("time.sleep"), \
                patch.object(native, "run_campaign_ap_route", side_effect=AssertionError("AP route forbidden")):
            result = self.runner(self.identity, None, self.checkpoint)
        self.assertEqual(result["status"], "deferred")
        self.assertEqual((result["ap_before"], result["ap_after"]), (12, 12))
        self.assertEqual(result["home_ap_observation"]["frame_sha256"], hashlib.sha256(home).hexdigest())
        self.assertEqual(result["total_input_count"], 3)
        self.assertEqual(len(self.world.inputs), 3)
        self.assertEqual(result["route_input_count"], 0)
        self.assertTrue(all(result[key] == 0 for key in ("campaign_dispatch_count", "stage_entry_transport_count",
                          "new_battle_count", "committed_ap_effect_count")))
        self.assertEqual(ap.campaign_next_due(result, self.identity, self.now - 1), self.now + 300)
        ledger = result["initial_normalization"]
        self.assertEqual([entry["target"] for entry in ledger["dispatches"]],
                         ["reset-popup-close", "campaign-chapter-back", "campaign-exit-base"])
        for entry in ledger["dispatches"]:
            source, successor = entry["source"], entry["successor"]
            self.assertNotEqual(source["path"], successor["path"])
            self.assertLess(source["captured_monotonic"], successor["captured_monotonic"])
            self.assertEqual(hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest(), source["sha256"])
            self.assertEqual(hashlib.sha256(Path(successor["path"]).read_bytes()).hexdigest(), successor["sha256"])

    def test_popup_stop_lease_loss_and_ambiguous_successor_never_reach_resource_route(self):
        popup = Path("tests/fixtures/campaign_startup_recovery/vip-chapter-source.png").read_bytes()
        class PopupFake(FakeADB):
            def __init__(self, scenario):
                super().__init__("popup")
                self.scenario = scenario
            def capture_png(self):
                return popup if self.phase == "popup" else super().capture_png()
            def dispatch_tap(self, point):
                self.inputs.append(("tap", point))
                if self.scenario != "ambiguous":
                    self.phase = "chapter"
                if self.on_input:
                    self.on_input(len(self.inputs))
        for scenario in ("stop", "lease", "ambiguous"):
            with self.subTest(scenario=scenario):
                self.stopped = False
                self.world = PopupFake(scenario)
                self.world.on_input = lambda count: setattr(self, "stopped", scenario == "stop")
                self.store_path = self.root / ("safety-" + scenario + ".sqlite3")
                valid = lambda _store, _owner, _now: not (scenario == "lease" and bool(self.world.inputs))
                with patch.object(SafetyStore, "lease_valid_for", valid), \
                        patch("time.sleep"), \
                        patch.object(native, "run_campaign_ap_route",
                                     side_effect=AssertionError("resource route forbidden")) as route:
                    with self.assertRaises(ap.CampaignApRunnerError) as raised:
                        self.runner(self.identity, None, self.checkpoint)
                self.assertEqual(len(self.world.inputs), 1)
                self.assertTrue(raised.exception.partial_result["effect_reconciliation_required"])
                self.assertEqual(raised.exception.partial_result["stage_entry_transport_count"], 0)
                route.assert_not_called()

    def test_deferred_normalization_requires_only_initial_ledger_inputs(self):
        self.home_ap = 13
        result = self.runner(self.identity, None, self.checkpoint)
        home = result["home_ap_observation"]
        entry = {"phase": "initial", "native_before": 0, "native_after": 1,
                 "target": "reset-popup-close", "action_key": "campaign-initial-startup-overlay",
                 "source": {"path": "source.png", "sha256": "source"},
                 "successor": {"path": "after.png", "sha256": "after"}}
        ledger = {"phase": "initial", "native_before": 0, "native_after": 1, "input_count": 1,
                  "dispatches": [entry], "settled_path": home["frame_path"],
                  "settled_sha256": home["frame_sha256"]}
        result.update(total_input_count=1, input_count=1, initial_normalization=ledger, route_input_count=0)
        self.assertEqual(ap.campaign_next_due(result, self.identity, self.now - 1), self.now + 900)
        for changes in ({"route_input_count": 1}, {"terminal_normalization": {}},
                        {"stage_entry_transport_count": 1}, {"total_input_count": 2}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ap.campaign_next_due(dict(result, **changes), self.identity, self.now - 1)
        wrong = dict(ledger, dispatches=[dict(entry, target="home-camera-click-drag")])
        with self.assertRaises(ValueError):
            ap.campaign_next_due(dict(result, initial_normalization=wrong), self.identity, self.now - 1)

    def test_serve_below_cost_records_zero_input_defer_every_300_seconds_and_restart_skips_capture(self):
        self.runner.cadence_seconds = 300
        for balance in (0, 1):
            with self.subTest(balance=balance):
                self.world, self.home_ap = FakeADB("home"), balance
                stop = VirtualStop(self.now)
                started = stop.now
                stop.on_wait = lambda: stop.set() if stop.now >= started + 650 else None
                self.runner.utc_clock = lambda: stop.now
                observed_at, reports = [], []
                read_home = self.runner._read_home
                def observe(runtime, identity, checkpoint, label, **kwargs):
                    if label == "campaign-service-initial-home":
                        observed_at.append(stop.now)
                    return read_home(runtime, identity, checkpoint, label, **kwargs)
                def emit(report):
                    reports.append(report)
                    if len(reports) == 2:
                        stop.set()
                path = self.root / f"service-no-work-{balance}.sqlite3"
                with patch.object(development_boundary, "RUNTIME_INPUT_LOCK_PATH",
                                  self.root / f"runtime-no-work-{balance}.sqlite3"), \
                        patch.object(self.runner, "_read_home", side_effect=observe), \
                        patch.object(native, "run_campaign_ap_route",
                                     side_effect=AssertionError("below-cost Home cannot start Campaign")):
                    with BotStateManager(path) as state:
                        service = AutomationService(mode="supervised", state=state, campaign_runner=self.runner)
                        service.set_service_enabled(True)
                        service.set_flow_enabled(CAMPAIGN_FLOW_ID, True)
                        service.serve(account_id="account", server_id="server", stop=stop, emit=emit,
                                      clock=lambda: stop.now, flow_ids=(CAMPAIGN_FLOW_ID,))
                        self.assertEqual(len(reports), 2, reports)
                        self.assertEqual(observed_at, [started, started + 300])
                        self.assertEqual(state.get_flow(CAMPAIGN_FLOW_ID).next_due_at_utc, started + 600)
                        rows = state._db.execute("SELECT consumed_inputs,consumed_actions FROM runs").fetchall()
                        self.assertEqual([tuple(row) for row in rows], [(0, 0), (0, 0)])
                    for report in reports:
                        result = report["result"]
                        self.assertEqual(report["status"], "completed")
                        self.assertEqual(result["status"], "deferred")
                        self.assertEqual((result["ap_before"], result["ap_after"]), (balance, balance))
                        self.assertTrue(result["terminal_home_verified"])
                        self.assertEqual(result["next_eligible_at"], result["completed_at_utc"] + 300)
                        self.assertTrue(all(result[key] == 0 for key in (
                            "total_input_count", "campaign_dispatch_count", "stage_entry_transport_count",
                            "new_battle_count", "committed_ap_effect_count")))
                    connections = self.connect.call_count
                    stop = VirtualStop(started + 301)
                    stop.on_wait = stop.set
                    restarted_reports = []
                    with BotStateManager(path) as state:
                        restarted = AutomationService(mode="supervised", state=state, campaign_runner=self.runner)
                        restarted.serve(account_id="account", server_id="server", stop=stop,
                                        emit=restarted_reports.append, clock=lambda: stop.now,
                                        flow_ids=(CAMPAIGN_FLOW_ID,))
                    self.assertEqual(restarted_reports, [])
                    self.assertEqual(self.connect.call_count, connections)
                    self.assertEqual(observed_at, [started, started + 300])
                self.assertEqual(self.world.inputs, [])

    def test_utc_identity_and_effect_normalization_rejects_unverified_results(self):
        result = self.one_battle_drain()
        for changes in ({"reset_id": "wrong"}, {"time_basis": "monotonic"},
                        {"completed_at_utc": self.now - 100}, {"terminal_home_verified": False},
                        {"committed_ap_effect_count": 0}, {"battle_outcome": "defeat"},
                        {"effect_reconciliation_required": True}, {"next_eligible_at": float("nan")},
                        {"ap_after": 115}, {"campaign_dispatch_count": 2}, {"ap_cost": 14.0},
                        {"ap_before": 14.0}, {"ap_after": 0.0},
                        {"ap_before": 120, "ap_after": 106,
                         "progress": dict(result["progress"], initial_ap=120, current_ap=106)},
                        {"progress": dict(result["progress"], completed_runs=True)},
                        {"progress": dict(result["progress"], ap_spent=14.0)},
                        {"total_input_count": 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ap.campaign_next_due(dict(result, **changes), self.identity, self.now - 1)

    def test_contradictory_native_cost_is_rejected_without_rewriting_reported_value(self):
        bad_native = {
            "status": "completed", "destination": "1-15-9", "ap_cost": 20,
            "ap_before": 120, "ap_after": 106, "battle_outcome": "victory",
            "stage_entry_transport_count": 1, "new_battle_count": 1,
            "committed_ap_effect_count": 1, "total_input_count": 2,
            "result_successor_verified": True, "terminal_home_verified": True,
            "effect_reconciliation_required": False,
            "progress": {"initial_ap": 120, "current_ap": 106, "ap_spent": 14,
                         "completed_runs": 1, "ap_regenerated": 0, "loss_seen": False},
        }
        with patch.object(native, "run_campaign_ap_route", return_value=bad_native):
            with self.assertRaises(ap.CampaignApRunnerError) as raised:
                self.runner(self.identity, None, self.checkpoint)
        result = raised.exception.partial_result
        self.assertEqual(result["status"], "unresolved")
        self.assertEqual(result["ap_cost"], 20)
        self.assertEqual(result["committed_ap_effect_count"], 0)
        self.assertEqual(self.world.inputs, [])

    def test_normalization_rejects_wrong_task_identity_with_valid_ap_result(self):
        result = self.one_battle_drain()
        with self.assertRaises(ValueError):
            ap.campaign_next_due(result, replace(self.identity, task_id="another-task"), self.now - 1)

    def test_store_close_failure_preserves_stop_reason_and_partial_battle_accounting(self):
        closes = []
        def action_store():
            store = self.action_store()
            original_close = store.close
            def close():
                original_close()
                closes.append(True)
                raise RuntimeError("close failed")
            store.close = close
            return store
        self.world.on_input = lambda count: setattr(self, "stopped", True) if count == 3 else None
        with patch("scripts.navigation_development_boundary.open_canonical_action_store", side_effect=action_store):
            with self.assertRaises(ap.CampaignApRunnerError) as raised:
                self.runner(self.identity, None, self.checkpoint)
        result = raised.exception.partial_result
        self.assertEqual(closes, [True])
        self.assertIn("STOP_REQUESTED", result["reason"])
        self.assertIn("STOP_REQUESTED", str(raised.exception))
        self.assertEqual(result["total_input_count"], 3)
        self.assertEqual(result["campaign_dispatch_count"], 1)
        self.assertEqual(result["new_battle_count"], 1)
        self.assertEqual(result["committed_ap_effect_count"], 0)
        self.assertTrue(result["effect_reconciliation_required"])
        self.assertEqual(len(self.world.inputs), 3)

    def test_canonical_stop_after_entry_or_lineup_blocks_restart_before_observation(self):
        for stop_after in (2, 3):
            with self.subTest(stop_after=stop_after):
                self.world = FakeADB("home")
                self.store_path = self.root / f"actions-stop-{stop_after}.sqlite3"
                path = self.root / f"service-stop-{stop_after}.sqlite3"
                stop = threading.Event()
                self.world.on_input = lambda count: stop.set() if count == stop_after else None
                reports = []
                def emit(report):
                    reports.append(report)
                    stop.set()
                with patch.object(development_boundary, "RUNTIME_INPUT_LOCK_PATH",
                                  self.root / f"runtime-lock-{stop_after}.sqlite3"):
                    with BotStateManager(path) as state:
                        service = AutomationService(mode="supervised", state=state, campaign_runner=self.runner)
                        service.set_service_enabled(True)
                        service.set_flow_enabled(CAMPAIGN_FLOW_ID, True)
                        service.serve(account_id="account", server_id="server", stop=stop, emit=emit,
                                      clock=lambda: self.now, flow_ids=(CAMPAIGN_FLOW_ID,))
                        self.assertEqual(reports[0]["status"], "blocked", reports)
                        self.assertTrue(state.get_flow(CAMPAIGN_FLOW_ID).blocked)
                        row = state._db.execute("SELECT max_inputs,max_actions,consumed_inputs,consumed_actions FROM runs").fetchone()
                        self.assertEqual(tuple(row), (CAMPAIGN_MAX_INPUTS, CAMPAIGN_DRAIN_MAX_RUNS, stop_after, 1))
                    connections = self.connect.call_count
                    inputs = len(self.world.inputs)
                    stop.clear()
                    reports.clear()
                    with BotStateManager(path) as state:
                        restarted = AutomationService(mode="supervised", state=state, campaign_runner=self.runner)
                        restarted.serve(account_id="account", server_id="server", stop=stop, emit=emit,
                                        clock=lambda: self.now, flow_ids=(CAMPAIGN_FLOW_ID,))
                        self.assertEqual(reports[0]["status"], "paused", reports)
                    self.assertEqual(self.connect.call_count, connections)
                    self.assertEqual(len(self.world.inputs), inputs)
                    self.assertEqual(inputs, stop_after)


if __name__ == "__main__":
    unittest.main()
