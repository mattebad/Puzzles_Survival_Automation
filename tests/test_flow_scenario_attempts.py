"""Focused tests for the one-attempt Nova MVP scenario budget."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from scripts import flow_delivery_control as control
from tasks.flow_scenario_attempts import (
    NOVA_CANARY_SCENARIO_ID,
    ScenarioAttemptError,
    ScenarioAttemptRecord,
    ScenarioFailureClass,
    ScenarioOutcome,
    ScenarioPhase,
    apply_scenario_record,
    replay_validated_record,
    scenario_record_from_mapping,
    validate_named_scenario_state,
)


ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "tasks" / "flow_delivery_queue.json"
FLOW_ID = "NOVA-PRAISE-HOME-ATLAS-MIGRATION"


def _queue() -> dict:
    return json.loads(QUEUE_PATH.read_text(encoding="utf-8"))


def _scenario() -> dict:
    queue = _queue()
    flow = next(item for item in queue["flows"] if item["flow_id"] == FLOW_ID)
    return deepcopy(flow["named_scenarios"][0])


class ScenarioAttemptPolicyTests(unittest.TestCase):
    def test_checked_in_queue_has_one_ready_no_praise_scenario(self) -> None:
        queue = _queue()
        control.validate_queue(queue)
        scenario = _scenario()
        validate_named_scenario_state(scenario)
        self.assertEqual(scenario["scenario_id"], NOVA_CANARY_SCENARIO_ID)
        self.assertEqual(scenario["maximum_execution_attempts"], 1)
        self.assertEqual(scenario["execution_attempt_count"], 0)
        self.assertEqual(scenario["forbidden_input_classes"], ["consequential"])
        self.assertEqual(len(scenario["pre_input_results"]), 1)
        self.assertFalse(
            scenario["pre_input_results"][0]["consumes_execution_budget"]
        )

    def test_replay_and_pre_input_failure_do_not_consume_budget(self) -> None:
        scenario = _scenario()
        initial_count = len(scenario["pre_input_results"])
        replay = replay_validated_record(
            candidate_commit="a" * 40,
            evidence_refs=("before.png", "after.png"),
        )
        after_replay = apply_scenario_record(scenario, replay)
        self.assertEqual(after_replay["execution_attempt_count"], 0)
        self.assertEqual(len(after_replay["pre_input_results"]), initial_count + 1)
        self.assertEqual(len(scenario["pre_input_results"]), initial_count)
        failure = ScenarioAttemptRecord(
            NOVA_CANARY_SCENARIO_ID,
            ScenarioPhase.PRE_INPUT,
            ScenarioOutcome.BLOCKED,
            "a" * 40,
            0,
            "none",
            False,
            "package mismatch",
            failure_class=ScenarioFailureClass.ENVIRONMENT_PREFLIGHT,
        )
        after_failure = apply_scenario_record(after_replay, failure)
        self.assertEqual(after_failure["execution_attempt_count"], 0)
        self.assertEqual(len(after_failure["pre_input_results"]), initial_count + 2)
        self.assertEqual(after_failure["status"], "ready")

    def test_first_navigation_input_consumes_and_exhausts_named_budget(self) -> None:
        execution = ScenarioAttemptRecord(
            NOVA_CANARY_SCENARIO_ID,
            ScenarioPhase.EXECUTION,
            ScenarioOutcome.FAILED,
            "b" * 40,
            1,
            "navigation_only",
            True,
            "Nova successor not recognized",
            failure_class=ScenarioFailureClass.SCREEN_RECOGNITION,
            evidence_refs=("source.png", "post.png"),
            terminal_ownership_state="released",
        )
        updated = apply_scenario_record(_scenario(), execution)
        self.assertEqual(updated["execution_attempt_count"], 1)
        self.assertEqual(updated["status"], "exhausted")
        with self.assertRaisesRegex(ScenarioAttemptError, "budget exhausted"):
            apply_scenario_record(updated, execution)

    def test_consequential_and_pre_input_transport_are_rejected(self) -> None:
        with self.assertRaisesRegex(ScenarioAttemptError, "prohibits consequential"):
            ScenarioAttemptRecord(
                NOVA_CANARY_SCENARIO_ID,
                ScenarioPhase.EXECUTION,
                ScenarioOutcome.FAILED,
                "c" * 40,
                1,
                "consequential",
                True,
                "forbidden Praise plan",
                failure_class=ScenarioFailureClass.CONSEQUENTIAL_PLAN_PROHIBITED,
            )
        with self.assertRaisesRegex(ScenarioAttemptError, "pre-input"):
            ScenarioAttemptRecord(
                NOVA_CANARY_SCENARIO_ID,
                ScenarioPhase.PRE_INPUT,
                ScenarioOutcome.BLOCKED,
                "c" * 40,
                1,
                "navigation_only",
                False,
                "invalid pre-input transport",
                failure_class=ScenarioFailureClass.EXECUTABLE_REGISTRATION,
            )

    def test_queue_application_is_pure_and_flow_specific(self) -> None:
        queue = _queue()
        before = deepcopy(queue)
        updated = control.apply_named_scenario_result(
            queue,
            flow_id=FLOW_ID,
            record=replay_validated_record(
                candidate_commit="d" * 40,
                evidence_refs=("replay.json",),
            ),
        )
        self.assertEqual(queue, before)
        nova = next(item for item in updated["flows"] if item["flow_id"] == FLOW_ID)
        original_nova = next(item for item in queue["flows"] if item["flow_id"] == FLOW_ID)
        self.assertEqual(
            len(nova["named_scenarios"][0]["pre_input_results"]),
            len(original_nova["named_scenarios"][0]["pre_input_results"]) + 1,
        )
        with self.assertRaisesRegex(control.FlowDeliveryError, "only for Nova"):
            control.apply_named_scenario_result(
                queue,
                flow_id="NOAHS-TAVERN-HOME-ATLAS-MIGRATION",
                record=replay_validated_record(
                    candidate_commit="d" * 40,
                    evidence_refs=("replay.json",),
                ),
            )

    def test_mapping_rejects_non_boolean_budget_flag(self) -> None:
        mapping = replay_validated_record(
            candidate_commit="e" * 40,
            evidence_refs=("replay.json",),
        ).to_mapping()
        mapping["consumes_execution_budget"] = "false"
        with self.assertRaises(ScenarioAttemptError):
            scenario_record_from_mapping(mapping)


if __name__ == "__main__":
    unittest.main()
