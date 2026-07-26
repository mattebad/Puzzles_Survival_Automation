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
    NOVA_SUPERVISED_PULSE_SCENARIO_ID,
    ScenarioAttemptError,
    ScenarioAttemptRecord,
    ScenarioFailureClass,
    ScenarioOutcome,
    ScenarioPhase,
    SupervisedNovaPulseScenarioAttemptRecord,
    apply_scenario_record,
    apply_supervised_pulse_scenario_record,
    empty_supervised_pulse_scenario,
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
    def test_checked_in_queue_retains_completed_no_praise_terminal_state(self) -> None:
        queue = _queue()
        control.validate_queue(queue)
        scenario = _scenario()
        validate_named_scenario_state(scenario)
        self.assertEqual(scenario["scenario_id"], NOVA_CANARY_SCENARIO_ID)
        self.assertEqual(scenario["maximum_execution_attempts"], 2)
        self.assertEqual(scenario["execution_attempt_count"], 2)
        self.assertEqual(scenario["status"], "exhausted")
        self.assertEqual(scenario["forbidden_input_classes"], ["consequential"])
        self.assertEqual(len(scenario["attempts"]), 2)
        self.assertEqual(scenario["attempts"][0]["candidate_commit"], "dc8210c1038c5233c893e2d42ee691a96b23ac48")
        self.assertEqual(scenario["attempts"][0]["outcome"], "blocked")
        self.assertEqual(scenario["attempts"][0]["reason"], "research_lab_radial_not_bound")
        self.assertIsNone(scenario["attempts"][0]["correction_ref"])
        self.assertEqual(
            scenario["attempts"][1]["candidate_commit"],
            "c3a4b3affeb97fa88420602bdd6b24f335e9612d",
        )
        self.assertEqual(scenario["attempts"][1]["outcome"], "completed")
        self.assertEqual(scenario["attempts"][1]["input_count"], 4)
        self.assertEqual(scenario["attempts"][1]["reason"], "verified_safe_return_home")
        self.assertIn(
            "nova-navigation-canary-20260722T020656687010Z",
            scenario["attempts"][1]["evidence_refs"][0],
        )
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
        self.assertEqual(flow["status"], "completed")
        self.assertEqual(flow["maximum_live_attempts"], 2)
        self.assertEqual(flow["live_attempt_count"], 2)
        self.assertEqual(len(flow["live_attempts"]), 2)
        blocked = flow["live_attempts"][0]
        self.assertEqual(blocked["ordinal"], 1)
        self.assertEqual(blocked["active_flow"], FLOW_ID)
        self.assertEqual(blocked["lease_owner"], "gf-mvp-009-parent")
        self.assertEqual(blocked["lease_session"], "gf-mvp-009-attempt-1")
        self.assertEqual(
            blocked["repository_head"],
            "dc8210c1038c5233c893e2d42ee691a96b23ac48",
        )
        self.assertEqual(blocked["terminal_outcome"], "blocked")
        self.assertIn("research_lab_radial_not_bound", blocked["diagnosis"])
        self.assertIn("zero Praise", blocked["diagnosis"])
        completed = flow["live_attempts"][1]
        self.assertEqual(completed["ordinal"], 2)
        self.assertEqual(
            completed["repository_head"],
            "c3a4b3affeb97fa88420602bdd6b24f335e9612d",
        )
        self.assertEqual(completed["terminal_outcome"], "completed")
        self.assertIn("20260722T020656687010Z", completed["session_directory"])
        self.assertIn("four navigation inputs", completed["diagnosis"])
        self.assertEqual(flow["flow_id"], FLOW_ID)
        self.assertEqual(
            queue.get("active_flow_id"),
            "CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY",
        )

    def test_replay_and_pre_input_failure_do_not_consume_budget(self) -> None:
        scenario = _scenario()
        initial_count = len(scenario["pre_input_results"])
        initial_execution_count = scenario["execution_attempt_count"]
        self.assertEqual(scenario["status"], "exhausted")
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
        historical = deepcopy(scenario)
        historical["attempts"] = historical["attempts"][:1]
        historical["execution_attempt_count"] = 1
        historical["status"] = "ready"
        historical["maximum_execution_attempts"] = 2
        validate_named_scenario_state(historical)
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
            apply_scenario_record(historical, without_correction)
        same_candidate = ScenarioAttemptRecord(
            NOVA_CANARY_SCENARIO_ID,
            ScenarioPhase.EXECUTION,
            ScenarioOutcome.BLOCKED,
            historical["attempts"][0]["candidate_commit"],
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
            apply_scenario_record(historical, same_candidate)
        # Policy accepts a corrected changed-candidate record; do not persist a fabricated attempt.
        accepted = apply_scenario_record(historical, retry)
        self.assertEqual(accepted["execution_attempt_count"], 2)
        self.assertEqual(accepted["status"], "exhausted")
        self.assertEqual(len(historical["attempts"]), 1)
        self.assertEqual(len(scenario["attempts"]), 2)

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


class SupervisedNovaPulseScenarioTests(unittest.TestCase):
    def test_accepts_exactly_one_consequential_praise_and_rejects_second_zero_invalid(self) -> None:
        ok = SupervisedNovaPulseScenarioAttemptRecord(
            NOVA_SUPERVISED_PULSE_SCENARIO_ID,
            ScenarioPhase.EXECUTION,
            ScenarioOutcome.COMPLETED,
            "a" * 40,
            4,
            1,
            "mixed_navigation_and_one_consequential",
            True,
            "confirmed_praise_and_verified_safe_return_home",
            evidence_refs=("session/",),
            terminal_ownership_state="released",
        )
        self.assertEqual(ok.input_count, 5)
        with self.assertRaisesRegex(ScenarioAttemptError, "at most one"):
            SupervisedNovaPulseScenarioAttemptRecord(
                NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                ScenarioPhase.EXECUTION,
                ScenarioOutcome.COMPLETED,
                "a" * 40,
                4,
                2,
                "mixed_navigation_and_one_consequential",
                True,
                "too many praises",
            )
        with self.assertRaisesRegex(ScenarioAttemptError, "exactly one Praise"):
            SupervisedNovaPulseScenarioAttemptRecord(
                NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                ScenarioPhase.EXECUTION,
                ScenarioOutcome.COMPLETED,
                "a" * 40,
                4,
                0,
                "navigation_only",
                True,
                "completed without Praise",
            )
        with self.assertRaisesRegex(ScenarioAttemptError, "prohibits consequential"):
            ScenarioAttemptRecord(
                NOVA_CANARY_SCENARIO_ID,
                ScenarioPhase.EXECUTION,
                ScenarioOutcome.FAILED,
                "a" * 40,
                1,
                "consequential",
                True,
                "canary still bans consequential",
                failure_class=ScenarioFailureClass.CONSEQUENTIAL_PLAN_PROHIBITED,
            )

    def test_apply_supervised_pulse_persists_candidate_counts_and_terminal_state(self) -> None:
        scenario = empty_supervised_pulse_scenario()
        record = SupervisedNovaPulseScenarioAttemptRecord(
            NOVA_SUPERVISED_PULSE_SCENARIO_ID,
            ScenarioPhase.EXECUTION,
            ScenarioOutcome.COMPLETED,
            "b" * 40,
            3,
            1,
            "mixed_navigation_and_one_consequential",
            True,
            "confirmed_praise_and_verified_safe_return_home",
            evidence_refs=("session/result.json",),
            terminal_ownership_state="released",
        )
        updated = apply_supervised_pulse_scenario_record(scenario, record)
        self.assertEqual(updated["execution_attempt_count"], 1)
        self.assertEqual(updated["status"], "exhausted")
        self.assertEqual(updated["attempts"][0]["candidate_commit"], "b" * 40)
        self.assertEqual(updated["attempts"][0]["navigation_input_count"], 3)
        self.assertEqual(updated["attempts"][0]["praise_transport_calls"], 1)
        self.assertEqual(updated["attempts"][0]["terminal_ownership_state"], "released")
        self.assertFalse(updated["attempts"][0]["unresolved_action"])
        with self.assertRaisesRegex(ScenarioAttemptError, "budget exhausted"):
            apply_supervised_pulse_scenario_record(updated, record)


if __name__ == "__main__":
    unittest.main()
