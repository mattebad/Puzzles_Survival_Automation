"""Recovery-only startup must release gameplay eligibility, not gameplay credit."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import time
import sqlite3
import unittest
from unittest import mock

import cv2

from automation_service.registry import (
    CANONICAL_FLOW_REGISTRY, ENHANCEMENT_FLOW_ID, PERSONAL_MIGHT_FLOW_ID,
    RECRUITMENT_FLOW_ID, RESOURCE_ITEM_FLOW_ID, ULTIMATE_FLOW_ID,
)
from automation_service.state import BotStateManager, StateError, TerminalProjectionError
from automation_service.contracts import OccurrenceDisposition, RecurrenceProjection, SchedulerFacts
from automation_service.scheduler import UtcPulseCoordinator
from automation_service.ultimate import UltimateExecutionHandler
from automation_service.enhancement import EnhancementExecutionHandler
from automation_service.personal_might import PersonalMightExecutionHandler
from automation_service.resource_item import ResourceItemExecutionHandler
from automation_service.recruitment import RecruitmentExecutionHandler, recruitment_reset
from tasks.runtime_identity import FIXED_RUNTIME_SCOPE
from tests.test_network_disconnect_boundaries import (
    CanonicalServiceNetworkPreludeTests, CONFIRM_CENTER, screen_frame, sha,
)


def install_legacy_run_uniqueness(path, *, future_syntax=False):
    """Reconstruct the pre-cutover UNIQUE constraint without changing any row."""
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys = OFF")
        definition = db.execute("SELECT sql FROM sqlite_master WHERE name = 'runs'").fetchone()[0]
        dependent_sql = [row[0] for row in db.execute(
            "SELECT sql FROM sqlite_master WHERE tbl_name = 'runs' "
            "AND type IN ('index', 'trigger') AND sql IS NOT NULL AND name <> 'runs_gameplay_occurrence_idx'"
        )]
        body = definition[definition.index("("):].rstrip()
        unique = 'UNIQUE ("flow_id", "occurrence_key")' if future_syntax else "UNIQUE (flow_id, occurrence_key)"
        db.execute("CREATE TABLE runs_legacy " + body[:-1] + ", " + unique + ")")
        columns = ", ".join('\"' + row[1] + '\"' for row in db.execute("PRAGMA table_info(runs)"))
        db.execute(f"INSERT INTO runs_legacy ({columns}) SELECT {columns} FROM runs")
        db.execute("DROP TABLE runs")
        db.execute("ALTER TABLE runs_legacy RENAME TO runs")
        for statement in dependent_sql:
            db.execute(statement)


class RecoveryOccurrenceTests(unittest.TestCase):
    def case(self, flow_id=RECRUITMENT_FLOW_ID, *, screen="disconnect", after_tap="home"):
        helper = CanonicalServiceNetworkPreludeTests("runTest")
        self.addCleanup(helper.doCleanups)
        case, device, core, attempts = helper.service_case(screen=screen, after_tap=after_tap)
        if flow_id != RECRUITMENT_FLOW_ID:
            entry = next(entry for entry in CANONICAL_FLOW_REGISTRY if entry.flow_id == flow_id)

            def forbidden_route(*args, **kwargs):
                self.fail("recovery-only invocation entered gameplay")

            setattr(case.service, entry.cli_name.replace("-", "_") + "_runner", forbidden_route)
            case.service.set_flow_enabled(flow_id, True)
        return case, device, core, attempts

    def serve_once(self, case, flow_id):
        reports = []
        case.service.serve(account_id="account", server_id="server", stop=case.stop,
                           emit=lambda report: (reports.append(report), case.stop.set()),
                           clock=lambda: case.stop.now, flow_ids=(flow_id,))
        self.assertEqual(len(reports), 1)
        rows = case.state._db.execute("SELECT run_id FROM runs").fetchall()
        self.assertEqual(len(rows), 1)
        return reports[0], case.state.get_run(rows[0]["run_id"])

    def assert_fresh_claim(self, case, flow_id, prelude):
        flow = case.state.get_flow(flow_id)
        self.assertEqual(flow.next_occurrence_key, 0)
        self.assertIsNone(flow.last_completed_at_utc)
        self.assertIsNone(flow.last_accepted_projection_key)
        self.assertFalse(flow.blocked)
        self.assertEqual(prelude.state, "DEFERRED")
        self.assertEqual(prelude.consumed_actions, 0)
        self.assertIs(prelude.occurrence_disposition, OccurrenceDisposition.PRESERVE_FOR_FRESH_CONTEXT)
        now = flow.next_due_at_utc
        self.assertGreater(now, case.stop.now)
        # A different connection/process identity sees the persisted released slot.
        with BotStateManager(case.state_path) as restarted:
            entry = next(entry for entry in CANONICAL_FLOW_REGISTRY if entry.flow_id == flow_id)
            handler_type = {
                ULTIMATE_FLOW_ID: UltimateExecutionHandler,
                ENHANCEMENT_FLOW_ID: EnhancementExecutionHandler,
                PERSONAL_MIGHT_FLOW_ID: PersonalMightExecutionHandler,
                RESOURCE_ITEM_FLOW_ID: ResourceItemExecutionHandler,
                RECRUITMENT_FLOW_ID: RecruitmentExecutionHandler,
            }[flow_id]
            options = {"flow_spec": entry.spec} if flow_id in {ULTIMATE_FLOW_ID, PERSONAL_MIGHT_FLOW_ID} else {}
            handler = handler_type(entry.registration, lambda *_args: self.fail("selection executed gameplay"), **options)
            handler.flow_spec = entry.spec
            coordinator = UtcPulseCoordinator(restarted, (entry.descriptor,), {flow_id: handler}, clock=lambda: now)
            facts = SchedulerFacts(
                "account", "server", prelude.reset_id, now, health_ok=True,
                accepted_product=entry.product_id, product_revision=entry.product_revision,
                registration_status=entry.registration_status, scheduler_eligible=entry.scheduler_eligible,
                owner_available=True, clock_ok=True, reset_agreement=True,
                projections={flow_id: RecurrenceProjection(entry.descriptor.recurrence_class,
                                                           observed_at_utc=now, next_eligible_at=now)},
            )
            candidate = coordinator.select(facts, flow_id=flow_id)
            self.assertIsNotNone(candidate)
            self.assertEqual(candidate.occurrence_key, prelude.occurrence_key)
            self.assertIsNone(restarted.claim_occurrence(flow_id, prelude.reset_id,
                                                        now_utc_epoch=now - 0.25))
            fresh = restarted.claim_occurrence(flow_id, prelude.reset_id, now_utc_epoch=now,
                                               max_inputs=prelude.max_inputs,
                                               max_actions=prelude.max_actions)
            self.assertIsNotNone(fresh)
            self.assertNotEqual(fresh.run_id, prelude.run_id)
            self.assertNotEqual(fresh.run_token, prelude.run_token)
            self.assertEqual(fresh.occurrence_key, prelude.occurrence_key)
            self.assertEqual(fresh.occurrence_ordinal, prelude.occurrence_ordinal)
            self.assertEqual((fresh.consumed_inputs, fresh.consumed_actions), (0, 0))
            self.assertIsNone(restarted.claim_occurrence(flow_id, prelude.reset_id, now_utc_epoch=now))
            self.assertIsNone(case.state.claim_occurrence(flow_id, prelude.reset_id, now_utc_epoch=now))
            retained = restarted.get_run(prelude.run_id)
            self.assertEqual((retained.consumed_inputs, retained.consumed_actions),
                             (prelude.consumed_inputs, 0))
            with self.assertRaises(TerminalProjectionError):
                restarted.project_terminal(
                    fresh.run_id, "DEFERRED", owner_instance_id=prelude.owner_instance_id,
                    process_start_token=prelude.process_start_token, run_token=prelude.run_token,
                    lease_generation=prelude.lease_generation, next_due_at_utc=now + 1,
                    now_utc_epoch=now,
                )
            authority = dict(owner_instance_id=fresh.owner_instance_id,
                             process_start_token=fresh.process_start_token,
                             run_token=fresh.run_token, lease_generation=fresh.lease_generation)
            self.assertIsNotNone(restarted.transition_run(fresh.run_id, "RUNNING",
                                                         now_utc_epoch=now, **authority))
            # Ordinary gameplay DEFERRED still consumes the occurrence.
            restarted.project_terminal(fresh.run_id, "DEFERRED", next_due_at_utc=now + 10,
                                       now_utc_epoch=now, **authority)
            self.assertEqual(restarted.get_flow(flow_id).next_occurrence_key, 1)
            self.assertEqual(restarted.get_run(prelude.run_id).consumed_inputs, prelude.consumed_inputs)
            self.assertEqual(restarted.get_run(prelude.run_id).occurrence_key, prelude.occurrence_key)

    def test_relaunch_is_system_accounting_not_gameplay_credit(self):
        case, device, _core, _attempts = self.case(ULTIMATE_FLOW_ID, after_tap="launcher")
        report, prelude = self.serve_once(case, ULTIMATE_FLOW_ID)
        self.assertEqual(report["status"], "deferred", report)
        self.assertEqual(len(device.launches), 1)
        self.assertEqual(report["result"]["system_launch_count"], 1)
        self.assertEqual((prelude.consumed_inputs, prelude.consumed_actions), (1, 0))
        self.assert_fresh_claim(case, ULTIMATE_FLOW_ID, prelude)

    def test_update_restart_preserves_daily_and_cooldown_occurrences_without_game_input(self):
        for flow_id in (ULTIMATE_FLOW_ID, ENHANCEMENT_FLOW_ID, PERSONAL_MIGHT_FLOW_ID,
                        RESOURCE_ITEM_FLOW_ID, RECRUITMENT_FLOW_ID):
            with self.subTest(flow_id=flow_id):
                case, device, _core, _attempts = self.case(flow_id, screen="update")
                report, prelude = self.serve_once(case, flow_id)
                self.assertEqual(report["status"], "deferred", report)
                self.assertEqual(device.taps, [])
                self.assertEqual((len(device.stops), len(device.launches)), (1, 1))
                self.assertEqual(device.unexpected, [])
                self.assertEqual(case.runtimes, [])
                self.assertEqual((prelude.consumed_inputs, prelude.consumed_actions), (0, 0))
                result = report["result"]
                self.assertEqual((result["system_stop_count"], result["system_launch_count"]), (1, 1))
                recovery = result["network_recovery"]
                self.assertEqual(recovery["interruption_identity"], "UPDATE_RESTART_REQUIRED")
                episode = case.state.get_network_recovery(FIXED_RUNTIME_SCOPE)
                self.assertEqual(episode.episode_id, recovery["episode_id"])
                self.assertEqual(episode.status, "RECOVERED")
                self.assertEqual((episode.confirm_attempts, episode.relaunch_attempts,
                                  episode.restart_attempts), (0, 0, 1))
                self.assertEqual(episode.restart_transport_status, "returned")
                self.assert_fresh_claim(case, flow_id, prelude)

    def test_update_returned_restart_episode_allows_zero_transport_resume_without_gameplay(self):
        case, device, _core, _attempts = self.case(ULTIMATE_FLOW_ID, screen="update")
        real_startup = case.service.application_startup

        def resumed(*args):
            result = real_startup(*args)
            result["system_stop_count"] = result["system_launch_count"] = 0
            result["network_recovery"]["system_stop_count"] = 0
            result["network_recovery"]["system_launch_count"] = 0
            return result

        case.service.application_startup = resumed
        report, prelude = self.serve_once(case, ULTIMATE_FLOW_ID)
        self.assertEqual(report["status"], "deferred", report)
        self.assertEqual((prelude.consumed_inputs, prelude.consumed_actions), (0, 0))
        self.assertEqual(device.taps, [])
        self.assert_fresh_claim(case, ULTIMATE_FLOW_ID, prelude)

    def test_update_recovery_requires_actual_returned_restart_episode_even_without_new_input(self):
        variants = {
            "missing_episode": None,
            "open_episode": {"status": "OPEN"},
            "unused_restart_budget": {"restart_attempts": 0},
            "attempted_restart": {"restart_transport_status": "attempted"},
            "unknown_restart": {"restart_transport_status": "unknown"},
            "wrong_identity": {"interruption_identity": "NETWORK_DISCONNECT_10054"},
            "confirm_budget_used": {"confirm_attempts": 1},
            "relaunch_budget_used": {"relaunch_attempts": 1},
        }
        for name, changes in variants.items():
            with self.subTest(variant=name):
                case, device, _core, _attempts = self.case(ULTIMATE_FLOW_ID, screen="update")
                real_startup = case.service.application_startup

                def tampered(*args):
                    result = real_startup(*args)
                    episode = case.state.get_network_recovery(FIXED_RUNTIME_SCOPE)
                    observed = None if changes is None else replace(episode, **changes)
                    patcher = mock.patch.object(case.state, "get_network_recovery", return_value=observed)
                    patcher.start()
                    self.addCleanup(patcher.stop)
                    # A fresh invocation can report no new transport. Durable
                    # restart proof remains mandatory; zero input is no bypass.
                    result["system_stop_count"] = result["system_launch_count"] = 0
                    result["network_recovery"]["system_stop_count"] = 0
                    result["network_recovery"]["system_launch_count"] = 0
                    return result

                case.service.application_startup = tampered
                report, prelude = self.serve_once(case, ULTIMATE_FLOW_ID)
                self.assertEqual(report["status"], "blocked", report)
                self.assertEqual((prelude.consumed_inputs, prelude.consumed_actions), (0, 0))
                self.assertTrue(case.state.get_flow(ULTIMATE_FLOW_ID).blocked)
                self.assertEqual(case.runtimes, [])
                self.assertEqual(device.taps, [])

    def test_update_recovery_rejects_confirm_and_inconsistent_stop_accounting(self):
        for name in ("confirm_input", "missing_stop", "two_stops", "boolean_stop", "missing_identity"):
            with self.subTest(variant=name):
                case, device, _core, _attempts = self.case(ULTIMATE_FLOW_ID, screen="update")
                real_startup = case.service.application_startup

                def tampered(*args):
                    result = real_startup(*args)
                    recovery = result["network_recovery"]
                    if name == "confirm_input":
                        result["game_input_count"] = result["input_count"] = 1
                        recovery["game_input_count"] = recovery["input_count"] = 1
                    elif name == "missing_identity":
                        recovery.pop("interruption_identity")
                    else:
                        stops = {"missing_stop": 0, "two_stops": 2, "boolean_stop": True}[name]
                        result["system_stop_count"] = recovery["system_stop_count"] = stops
                    return result

                case.service.application_startup = tampered
                report, prelude = self.serve_once(case, ULTIMATE_FLOW_ID)
                self.assertEqual(report["status"], "blocked", report)
                self.assertEqual(prelude.consumed_actions, 0)
                self.assertEqual(case.runtimes, [])
                self.assertEqual(device.taps, [])

    def test_daily_once_routes_keep_their_only_occurrence_and_recovery_charge(self):
        for flow_id in (ULTIMATE_FLOW_ID, ENHANCEMENT_FLOW_ID,
                        PERSONAL_MIGHT_FLOW_ID, RESOURCE_ITEM_FLOW_ID):
            with self.subTest(flow_id=flow_id):
                case, device, _core, _attempts = self.case(flow_id)
                report, prelude = self.serve_once(case, flow_id)
                self.assertEqual(report["status"], "deferred", report)
                self.assertEqual(device.taps, [("disconnect", CONFIRM_CENTER)])
                self.assertEqual(prelude.consumed_inputs, 1)
                self.assertEqual(report["result"]["system_launch_count"], 0)
                self.assert_fresh_claim(case, flow_id, prelude)

    def test_cooldown_recurrence_preserves_original_occurrence(self):
        case, device, _core, _attempts = self.case()
        report, prelude = self.serve_once(case, RECRUITMENT_FLOW_ID)
        self.assertEqual(report["status"], "deferred", report)
        self.assertEqual(prelude.consumed_inputs, len(device.taps))
        self.assert_fresh_claim(case, RECRUITMENT_FLOW_ID, prelude)

    def test_zero_input_connected_resume_does_not_consume_daily_occurrence(self):
        case, device, _core, _attempts = self.case(ULTIMATE_FLOW_ID, screen="home")
        case.state.begin_network_recovery(scope_key=FIXED_RUNTIME_SCOPE,
                                          source_frame_hash=sha("disconnect"), now_utc_epoch=time.time())
        report, prelude = self.serve_once(case, ULTIMATE_FLOW_ID)
        self.assertEqual(report["status"], "deferred", report)
        self.assertEqual(device.taps, [])
        self.assertEqual(prelude.consumed_inputs, 0)
        self.assert_fresh_claim(case, ULTIMATE_FLOW_ID, prelude)

    def seed_original_episode(self, case):
        original = screen_frame("disconnect")
        original[100, 100] = (19, 19, 19)  # Different valid original capture, outside modal/Home.
        ok, encoded = cv2.imencode(".png", original)
        self.assertTrue(ok)
        original_sha = hashlib.sha256(encoded.tobytes()).hexdigest()
        self.assertNotEqual(original_sha, sha("disconnect"))
        return case.state.begin_network_recovery(scope_key=FIXED_RUNTIME_SCOPE,
                                                source_frame_hash=original_sha,
                                                now_utc_epoch=time.time())

    def test_positive_resumed_confirm_keeps_original_and_current_source_evidence(self):
        case, device, _core, _attempts = self.case(ULTIMATE_FLOW_ID)
        episode = self.seed_original_episode(case)
        report, prelude = self.serve_once(case, ULTIMATE_FLOW_ID)
        self.assertEqual(report["status"], "deferred", report)
        recovery = report["result"]["network_recovery"]
        self.assertEqual(recovery["source_sha256"], sha("disconnect"))
        self.assertEqual(recovery["episode_source_sha256"], episode.source_frame_hash)
        self.assertEqual(recovery["episode_id"], episode.episode_id)
        self.assertEqual(device.taps, [("disconnect", CONFIRM_CENTER)])
        self.assertEqual(prelude.consumed_inputs, 1)
        self.assert_fresh_claim(case, ULTIMATE_FLOW_ID, prelude)

    def test_mutated_original_source_is_not_admitted_even_after_real_recovery(self):
        case, device, _core, _attempts = self.case(ULTIMATE_FLOW_ID)
        episode = self.seed_original_episode(case)
        real_startup = case.service.application_startup

        def tampered(*args):
            result = real_startup(*args)
            self.assertEqual(result["network_recovery"]["episode_source_sha256"], episode.source_frame_hash)
            result["network_recovery"]["episode_source_sha256"] = sha("disconnect")
            return result

        case.service.application_startup = tampered
        report, run = self.serve_once(case, ULTIMATE_FLOW_ID)
        self.assertEqual(report["status"], "blocked", report)
        self.assertNotIn(run.state, {"DEFERRED", "SUCCEEDED"})
        self.assertEqual(run.consumed_actions, 0)
        self.assertEqual(run.consumed_inputs, 1)
        self.assertEqual(device.taps, [("disconnect", CONFIRM_CENTER)])
        self.assertTrue(case.state.get_flow(ULTIMATE_FLOW_ID).blocked)

    def test_legacy_migration_preserves_run_action_history_and_enables_fresh_lifecycle_claim(self):
        case, _device, _core, _attempts = self.case(ULTIMATE_FLOW_ID)
        reset = recruitment_reset(case.stop.now)
        historical = case.state.claim_occurrence(RECRUITMENT_FLOW_ID, reset,
                                                  now_utc_epoch=case.stop.now, max_inputs=2, max_actions=1)
        self.assertIsNotNone(historical)
        authority = dict(owner_instance_id=historical.owner_instance_id,
                         process_start_token=historical.process_start_token,
                         run_token=historical.run_token, lease_generation=historical.lease_generation)
        case.state.transition_run(historical.run_id, "RUNNING", now_utc_epoch=case.stop.now, **authority)
        action = case.state.reserve_action(historical.run_id, "historical-key", "historical-action",
                                           now_utc_epoch=case.stop.now, **authority)
        self.assertIsNotNone(action)
        case.state.transition_action(action.action_id, "CANCELLED", now_utc_epoch=case.stop.now, **authority)
        case.state.project_terminal(historical.run_id, "DEFERRED",
                                    next_due_at_utc=case.stop.now + 10, now_utc_epoch=case.stop.now, **authority)
        case.state.release_service_lease(owner_instance_id=historical.owner_instance_id,
                                        process_start_token=historical.process_start_token,
                                        lease_generation=historical.lease_generation)
        before_run = dict(case.state._db.execute("SELECT * FROM runs WHERE run_id = ?", (historical.run_id,)).fetchone())
        before_action = dict(case.state._db.execute("SELECT * FROM actions WHERE action_id = ?", (action.action_id,)).fetchone())
        case.state.close()
        install_legacy_run_uniqueness(case.state_path)
        case.state = case.stack.enter_context(BotStateManager(case.state_path))
        case.service.state = case.state
        self.assertEqual(dict(case.state._db.execute("SELECT * FROM runs WHERE run_id = ?", (historical.run_id,)).fetchone()), before_run)
        self.assertEqual(dict(case.state._db.execute("SELECT * FROM actions WHERE action_id = ?", (action.action_id,)).fetchone()), before_action)
        self.assertEqual(case.state._db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(case.state._db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        # Ordinary historical DEFERRED remains consumed, even after migration.
        self.assertIsNone(case.state.claim_occurrence(RECRUITMENT_FLOW_ID, reset,
                                                      occurrence_key=historical.occurrence_key,
                                                      now_utc_epoch=case.stop.now + 10))
        reports = []
        case.service.serve(account_id="account", server_id="server", stop=case.stop,
                           emit=lambda report: (reports.append(report), case.stop.set()),
                           clock=lambda: case.stop.now, flow_ids=(ULTIMATE_FLOW_ID,))
        self.assertEqual(reports[0]["status"], "deferred", reports)
        prelude_id = case.state._db.execute("SELECT run_id FROM runs WHERE flow_id = ?", (ULTIMATE_FLOW_ID,)).fetchone()[0]
        prelude = case.state.get_run(prelude_id)
        self.assert_fresh_claim(case, ULTIMATE_FLOW_ID, prelude)
        # A second reopen neither rewrites history nor reconsumes the slot.
        with BotStateManager(case.state_path) as again:
            self.assertEqual(dict(again._db.execute("SELECT * FROM runs WHERE run_id = ?", (historical.run_id,)).fetchone()), before_run)
            self.assertEqual(dict(again._db.execute("SELECT * FROM actions WHERE action_id = ?", (action.action_id,)).fetchone()), before_action)
            self.assertEqual(again.get_run(prelude_id).occurrence_key, prelude.occurrence_key)

    def test_nested_launch_credit_requires_canonical_relaunch_not_just_confirm(self):
        case, device, _core, _attempts = self.case(ULTIMATE_FLOW_ID)
        real_startup = case.service.application_startup

        def tampered(*args):
            result = real_startup(*args)
            result["system_launch_count"] = 1
            result["network_recovery"]["system_launch_count"] = 1
            return result

        case.service.application_startup = tampered
        report, run = self.serve_once(case, ULTIMATE_FLOW_ID)
        self.assertEqual(report["status"], "blocked", report)
        self.assertNotIn(run.state, {"DEFERRED", "SUCCEEDED"})
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (1, 0))
        episode = case.state.get_network_recovery(FIXED_RUNTIME_SCOPE)
        self.assertEqual(episode.relaunch_attempts, 0)
        self.assertEqual(device.launches, [])

    def test_initial_ordinary_launch_is_separate_from_zero_input_transient_recovery(self):
        case, device, _core, _attempts = self.case(ULTIMATE_FLOW_ID, screen="launcher")
        device.after_launch = "disconnect"
        real_capture = device.capture

        def capture():
            transient = device.screen == "disconnect"
            payload = real_capture()
            if transient:
                device.screen = "home"
            return payload

        device.capture = capture
        report, run = self.serve_once(case, ULTIMATE_FLOW_ID)
        self.assertEqual(report["status"], "deferred", report)
        self.assertEqual(report["result"]["system_launch_count"], 1)
        recovery = report["result"]["network_recovery"]
        self.assertEqual((recovery["game_input_count"], recovery["system_launch_count"]), (0, 0))
        self.assertIsNone(recovery["episode_id"])
        self.assertIsNone(case.state.get_network_recovery(FIXED_RUNTIME_SCOPE))
        self.assertEqual(len(device.launches), 1)
        self.assertEqual(device.taps, [])
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (0, 0))
        self.assert_fresh_claim(case, ULTIMATE_FLOW_ID, run)

    def test_read_only_legacy_open_does_not_run_schema_cutover(self):
        case, _device, _core, _attempts = self.case(ULTIMATE_FLOW_ID)
        case.state.close()
        install_legacy_run_uniqueness(case.state_path)
        with sqlite3.connect(case.state_path) as db:
            before = db.execute("SELECT type, name, sql FROM sqlite_master ORDER BY type, name").fetchall()
        with BotStateManager(case.state_path, read_only=True) as observer:
            self.assertTrue(observer.get_service_enabled())
        with sqlite3.connect(case.state_path) as db:
            self.assertEqual(db.execute("SELECT type, name, sql FROM sqlite_master ORDER BY type, name").fetchall(), before)

    def test_unrecognized_future_unique_syntax_rolls_back_cutover_without_schema_side_effects(self):
        case, _device, _core, _attempts = self.case(ULTIMATE_FLOW_ID)
        case.state.close()
        install_legacy_run_uniqueness(case.state_path, future_syntax=True)
        with sqlite3.connect(case.state_path) as db:
            db.execute("ALTER TABLE runs DROP COLUMN occurrence_disposition")
            before = db.execute("SELECT type, name, sql FROM sqlite_master ORDER BY type, name").fetchall()
        with self.assertRaisesRegex(StateError, "unsupported runs occurrence constraint migration"):
            BotStateManager(case.state_path)
        with sqlite3.connect(case.state_path) as db:
            self.assertEqual(db.execute("SELECT type, name, sql FROM sqlite_master ORDER BY type, name").fetchall(), before)
