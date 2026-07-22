"""Focused tests for the Nova MVP scenario budget and authorized second attempt."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from scripts import flow_delivery_control as control
from tasks.flow_scenario_attempts import (
    NOVA_CANARY_SCENARIO_ID,
    NOVA_CANARY_TEMPLATE_CORRECTION_REF,
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


def _unused_scenario() -> dict:
    scenario = _scenario()
    scenario["maximum_execution_attempts"] = 1
    scenario["execution_attempt_count"] = 0
    scenario["attempts"] = []
    scenario["status"] = "ready"
    return scenario


class ScenarioAttemptPolicyTests(unittest.TestCase):
    def test_checked_in_queue_retains_terminal_no_retry_authority(self) -> None:
        queue = _queue()
        control.validate_queue(queue)
        scenario = _scenario()
        validate_named_scenario_state(scenario)
        self.assertEqual(scenario["scenario_id"], NOVA_CANARY_SCENARIO_ID)
        self.assertEqual(scenario["maximum_execution_attempts"], 1)
        self.assertEqual(scenario["execution_attempt_count"], 1)
        self.assertEqual(scenario["status"], "exhausted")
        self.assertEqual(scenario["forbidden_input_classes"], ["consequential"])
        self.assertEqual(len(scenario["attempts"]), 1)
        self.assertEqual(scenario["attempts"][0]["candidate_commit"], "dc8210c1038c5233c893e2d42ee691a96b23ac48")
        self.assertIsNone(scenario["attempts"][0]["correction_ref"])
        self.assertEqual(len(scenario["pre_input_results"]), 2)
        self.assertFalse(
            scenario["pre_input_results"][-1]["consumes_execution_budget"]
        )
        self.assertEqual(
            scenario["pre_input_results"][-1]["candidate_commit"],
            "e345db945cf0b4537bc45d0e905dfb818519f7eb",
        )
        self.assertEqual(
            scenario["pre_input_results"][-1]["reason"],
            "initial_radial_missing_research_lab_provenance",
        )
        self.assertEqual(
            scenario["pre_input_results"][-1]["correction_ref"],
            NOVA_CANARY_TEMPLATE_CORRECTION_REF,
        )
        flow = next(item for item in queue["flows"] if item["flow_id"] == FLOW_ID)
        self.assertEqual(flow["status"], "blocked")
        self.assertEqual(flow["maximum_live_attempts"], 1)
        self.assertEqual(flow["live_attempt_count"], 1)
        self.assertEqual(len(flow["live_attempts"]), 1)
        attempt = flow["live_attempts"][0]
        self.assertEqual(attempt["ordinal"], 1)
        self.assertEqual(attempt["active_flow"], FLOW_ID)
        self.assertEqual(attempt["lease_owner"], "gf-mvp-009-parent")
        self.assertEqual(attempt["lease_session"], "gf-mvp-009-attempt-1")
        self.assertEqual(
            attempt["repository_head"],
            "dc8210c1038c5233c893e2d42ee691a96b23ac48",
        )
        self.assertEqual(attempt["terminal_outcome"], "blocked")
        self.assertIn("research_lab_radial_not_bound", attempt["diagnosis"])
        self.assertIn("zero Praise", attempt["diagnosis"])
        self.assertIn("Do not retry e345db9", flow["next_concrete_action"])
        self.assertEqual(queue.get("active_flow_id"), None)

    def test_replay_and_pre_input_failure_do_not_consume_budget(self) -> None:
        scenario = _scenario()
        initial_count = len(scenario["pre_input_results"])
        initial_execution_count = scenario["execution_attempt_count"]
        replay = replay_validated_record(
            candidate_commit="a" * 40,
            evidence_refs=("before.png", "after.png"),
        )
        after_replay = apply_scenario_record(scenario, replay)
        self.assertEqual(
            after_replay["execution_attempt_count"],
            initial_execution_count,
        )
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
        self.assertEqual(
            after_failure["execution_attempt_count"],
            initial_execution_count,
        )
        self.assertEqual(len(after_failure["pre_input_results"]), initial_count + 2)
        self.assertEqual(after_failure["status"], "exhausted")

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
        updated = apply_scenario_record(_unused_scenario(), execution)
        self.assertEqual(updated["execution_attempt_count"], 1)
        self.assertEqual(updated["status"], "exhausted")
        with self.assertRaisesRegex(ScenarioAttemptError, "budget exhausted"):
            apply_scenario_record(updated, execution)

    def test_authorized_second_attempt_requires_correction_and_changed_candidate(self) -> None:
        scenario = _scenario()
        scenario["maximum_execution_attempts"] = 2
        scenario["status"] = "ready"
        validate_named_scenario_state(scenario)
        retry = ScenarioAttemptRecord(
            NOVA_CANARY_SCENARIO_ID,
            ScenarioPhase.EXECUTION,
            ScenarioOutcome.BLOCKED,
            "f" * 40,
            1,
            "navigation_only",
            True,
            "future live attempt placeholder must not be fabricated here",
            failure_class=ScenarioFailureClass.SCREEN_RECOGNITION,
            evidence_refs=("future.png",),
            correction_ref=NOVA_CANARY_TEMPLATE_CORRECTION_REF,
            terminal_ownership_state="released",
        )
        without_correction = ScenarioAttemptRecord(
            NOVA_CANARY_SCENARIO_ID,
            ScenarioPhase.EXECUTION,
            ScenarioOutcome.BLOCKED,
            "f" * 40,
            1,
            "navigation_only",
            True,
            "missing correction",
            failure_class=ScenarioFailureClass.SCREEN_RECOGNITION,
            evidence_refs=("future.png",),
            terminal_ownership_state="released",
        )
        with self.assertRaisesRegex(ScenarioAttemptError, "correction reference"):
            apply_scenario_record(scenario, without_correction)
        same_candidate = ScenarioAttemptRecord(
            NOVA_CANARY_SCENARIO_ID,
            ScenarioPhase.EXECUTION,
            ScenarioOutcome.BLOCKED,
            scenario["attempts"][0]["candidate_commit"],
            1,
            "navigation_only",
            True,
            "same candidate retry",
            failure_class=ScenarioFailureClass.SCREEN_RECOGNITION,
            evidence_refs=("future.png",),
            correction_ref=NOVA_CANARY_TEMPLATE_CORRECTION_REF,
            terminal_ownership_state="released",
        )
        with self.assertRaisesRegex(ScenarioAttemptError, "correction reference"):
            apply_scenario_record(scenario, same_candidate)
        # Policy accepts a corrected changed-candidate record; do not persist a fabricated attempt.
        accepted = apply_scenario_record(scenario, retry)
        self.assertEqual(accepted["execution_attempt_count"], 2)
        self.assertEqual(accepted["status"], "exhausted")
        self.assertEqual(len(scenario["attempts"]), 1)

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
