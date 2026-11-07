"""Real canonical service/SQLite and adapter guards over synthetic native DTO faults."""
from __future__ import annotations

import copy
import unittest

from automation_service.recruitment import recruitment_reset
from automation_service.registry import WALI_UPGRADE_FLOW_ID
from automation_service.state import BotStateManager, RunState
from tasks.scheduler_task_result import SchedulerTaskOutcome
from tests.support.service_route_contract import ROUTES, RouteRig


class WaliServiceTests(unittest.TestCase):
    def _corrupt_result(self, rig, corrupt):
        native = rig.runner.adapter.native
        builder = native.result_builder

        def result_builder(*args, **kwargs):
            result = builder(*args, **kwargs)
            corrupt(result)
            return result

        native.result_builder = result_builder

    def _assert_unknown_and_no_restart(self, rig):
        report, = rig.once()
        run, = rig.runs()
        self.assertEqual(report["status"], "blocked", report)
        self.assertEqual(run.state, RunState.FAILED)
        self.assertEqual(run.terminal_outcome, SchedulerTaskOutcome.RECONCILIATION_REQUIRED.value)
        self.assertTrue(report["result"]["effect_reconciliation_required"])
        self.assertTrue(report["result"]["identical_retry_denied"])
        self.assertFalse(report["result"]["native_execution_verified"])
        self.assertTrue(rig.state.get_flow(WALI_UPGRADE_FLOW_ID).blocked)
        inputs = list(rig.runner.inputs)
        with BotStateManager(rig.path) as restarted:
            self.assertEqual(rig.once(state=restarted)[0]["status"], "paused")
        self.assertEqual(rig.runner.inputs, inputs)
        return report["result"], run

    def test_deferred_prefix_can_resume_in_a_new_occurrence_of_the_same_reset(self):
        with RouteRig(self, ROUTES[WALI_UPGRADE_FLOW_ID]) as rig:
            rig.runner.wali_mode = "deferred_prefix"
            first_report, = rig.once()
            first_run, = rig.runs()
            self.assertEqual(first_report["status"], "deferred")
            self.assertEqual(first_report["result"]["confirmed_upgrades"], 1)
            self.assertEqual(first_run.consumed_actions, 1)
            self.assertFalse(rig.state.get_flow(WALI_UPGRADE_FLOW_ID).blocked)
            due = rig.state.get_flow(WALI_UPGRADE_FLOW_ID).next_due_at_utc
            self.assertGreater(due, rig.stop.now)
            self.assertEqual(recruitment_reset(due), first_run.reset_id)
            with BotStateManager(rig.path) as restarted:
                self.assertEqual(rig.once(state=restarted), [])
                rig.stop.now = due
                rig.runner.wali_mode = "single_upgrades"
                resumed, = rig.once(state=restarted)
            first_run, second_run = rig.runs()
            self.assertEqual(resumed["status"], "completed")
            self.assertEqual(
                (resumed["result"]["prior_confirmed_upgrades"],
                 resumed["result"]["confirmed_upgrades"],
                 resumed["result"]["level_upgrade_committed_count"]),
                (1, 3, 2),
            )
            self.assertEqual(second_run.consumed_actions, 2)
            self.assertEqual(first_run.reset_id, second_run.reset_id)
            self.assertNotEqual(first_run.occurrence_key, second_run.occurrence_key)

    def test_standard_evolution_preserves_the_three_normal_upgrade_quota_after_restart(self):
        with RouteRig(self, ROUTES[WALI_UPGRADE_FLOW_ID]) as rig:
            rig.runner.wali_mode = "standard_evolution"
            # One normal before the cap, zero quota for evolution, two after.
            report, = rig.once()
            run, = rig.runs()
            result = report["result"]
            self.assertEqual(report["status"], "completed")
            self.assertEqual(
                (result["confirmed_upgrades"], result["level_upgrade_committed_count"],
                 result["evolution_committed_count"], result["committed_action_count"]),
                (3, 3, 1, 4),
            )
            self.assertEqual([row["normal_inputs"] for row in result["normal_batches"]], [1, 2])
            self.assertTrue(result["native_execution_verified"])
            self.assertEqual(run.consumed_actions, 4)
            self.assertEqual(run.terminal_outcome, SchedulerTaskOutcome.COMPLETE_FOR_RESET.value)
            inputs = list(rig.runner.inputs)
            with BotStateManager(rig.path) as restarted:
                self.assertEqual(rig.once(state=restarted), [])
            self.assertEqual(rig.runner.inputs, inputs)

    def test_relabeling_the_same_level_transition_cannot_create_another_daily_upgrade(self):
        with RouteRig(self, ROUTES[WALI_UPGRADE_FLOW_ID]) as rig:
            rig.runner.wali_mode = "standard_evolution"
            def duplicate_transition_with_fresh_counter(result):
                first, second = result["normal_batches"]
                second.update(
                    before=copy.deepcopy(first["before"]), after=copy.deepcopy(first["after"]),
                    first_ordinal=2, input_limit=1, normal_inputs=1,
                    quoted_antiserum_costs=list(first["quoted_antiserum_costs"]),
                )
                second["before"]["confirmed_upgrades"] = 1
                second["after"]["confirmed_upgrades"] = 2
                result["evolutions"] = []

            self._corrupt_result(rig, duplicate_transition_with_fresh_counter)
            result, run = self._assert_unknown_and_no_restart(rig)
            self.assertEqual(result["confirmed_upgrades"], 1)
            self.assertEqual(result["committed_action_count"], 1)
            self.assertEqual(result["native_reported_counts"]["confirmed_upgrades"], 3)
            self.assertEqual(run.consumed_actions, 4)

    def test_evolution_cannot_fill_a_missing_normal_upgrade_in_native_summary(self):
        with RouteRig(self, ROUTES[WALI_UPGRADE_FLOW_ID]) as rig:
            rig.runner.wali_mode = "standard_evolution"

            def wrongly_credit_evolution(result):
                batch = result["normal_batches"][-1]
                removed_cost = batch["quoted_antiserum_costs"].pop()
                batch["normal_inputs"] = 1
                batch["after"]["current_level"] -= 1
                batch["after"]["confirmed_upgrades"] -= 1
                batch["after"]["material_balances"]["ANTISERUM"] += removed_cost
                if batch["after"].get("spent_materials"):
                    batch["after"]["spent_materials"]["ANTISERUM"] -= removed_cost
                result.update(
                    level_upgrade_committed_count=2, upgrade_transport_calls=2,
                    committed_action_count=3, total_action_count=3,
                    # Two normals plus the evolution's automatic level is NOT quota3.
                    confirmed_upgrades=3,
                )

            self._corrupt_result(rig, wrongly_credit_evolution)
            result, run = self._assert_unknown_and_no_restart(rig)
            self.assertEqual(result["confirmed_upgrades"], 2)
            self.assertEqual(result["native_reported_counts"]["confirmed_upgrades"], 3)
            self.assertEqual(run.consumed_actions, 3)

    def test_unproved_manual_use_is_not_a_committed_evolution(self):
        with RouteRig(self, ROUTES[WALI_UPGRADE_FLOW_ID]) as rig:
            rig.runner.wali_mode = "standard_evolution"

            def remove_actual_manual_receipt(result):
                after = result["evolutions"][0]["after"]
                after["material_usage_receipts"] = ()
                # No numeric receipt or owned-manual after-balance exists either.

            self._corrupt_result(rig, remove_actual_manual_receipt)
            result, run = self._assert_unknown_and_no_restart(rig)
            self.assertEqual(result["evolution_committed_count"], 0)
            self.assertEqual(result["level_upgrade_committed_count"], 3)
            self.assertEqual(result["committed_action_count"], 3)
            self.assertEqual(result["native_reported_counts"]["committed_action_count"], 4)
            self.assertEqual(run.consumed_actions, 4)

    def test_malformed_action_evidence_retains_attempts_but_confirms_no_prefix(self):
        with RouteRig(self, ROUTES[WALI_UPGRADE_FLOW_ID]) as rig:
            self._corrupt_result(
                rig, lambda result: result["normal_batches"][0]["before"].update(evidence_refs=None),
            )
            result, run = self._assert_unknown_and_no_restart(rig)
            self.assertEqual(result["committed_action_count"], 0)
            self.assertEqual(result["confirmed_upgrades"], 0)
            self.assertEqual(run.consumed_actions, 3)

    def test_planned_batch_quantity_cannot_replace_actual_input_count(self):
        with RouteRig(self, ROUTES[WALI_UPGRADE_FLOW_ID]) as rig:
            def invent_missing_inputs(result):
                batch = result["normal_batches"][0]
                batch["normal_inputs"] = 1
                batch["quoted_antiserum_costs"] = batch["quoted_antiserum_costs"][:1]
                # Leave a three-level after-state/summary: planned N is not proof.
            self._corrupt_result(rig, invent_missing_inputs)
            result, run = self._assert_unknown_and_no_restart(rig)
            self.assertEqual(result["confirmed_upgrades"], 0)
            self.assertEqual(result["normal_batches"], [])
            self.assertEqual(run.consumed_actions, 3)

    def test_final_debit_must_equal_the_actual_sequence_of_changing_quotes(self):
        with RouteRig(self, ROUTES[WALI_UPGRADE_FLOW_ID]) as rig:
            def falsify_last_quote(result):
                result["normal_batches"][0]["quoted_antiserum_costs"][-1] += 1
            self._corrupt_result(rig, falsify_last_quote)
            result, run = self._assert_unknown_and_no_restart(rig)
            self.assertEqual(result["confirmed_upgrades"], 0)
            self.assertEqual(run.consumed_actions, 3)


if __name__ == "__main__":
    unittest.main()
