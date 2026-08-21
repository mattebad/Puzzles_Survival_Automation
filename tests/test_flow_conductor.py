"""Focused tests for the autonomous flow-delivery conductor."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import pnsctl
from tasks.flow_conductor import (
    ConductorDecision,
    FramingChecklist,
    apply_framing,
    classify_summary,
    load_state,
    record_iteration,
    save_state,
)
from tasks.gameplay_flow_contracts import FlowContractError, load_flow_contract


class FlowConductorTests(unittest.TestCase):
    def test_nested_external_blockers_precede_done_and_reconciliation(self) -> None:
        cases = (
            {
                "status": "completed",
                "evidence_verified": True,
                "result": {
                    "status": "manual_required",
                    "reason": "nested account state requires operator",
                    "effect_reconciliation_required": True,
                },
            },
            {
                "status": "manual_required",
                "reason": "outer manual state",
                "result": {
                    "status": "completed",
                    "evidence_verified": True,
                },
            },
            {
                "status": "completed",
                "evidence_verified": True,
                "result": {
                    "route_result": {
                        "canary": {
                            "status": "external_block",
                            "next_action": "nested external recovery required",
                        }
                    }
                },
            },
        )
        expected_reasons = (
            "nested account state requires operator",
            "outer manual state",
            "nested external recovery required",
        )
        state = load_state("FLOW-NESTED-EXTERNAL-BLOCK")
        for summary, expected in zip(cases, expected_reasons):
            with self.subTest(expected=expected):
                decision, reason = classify_summary(summary, state=state)
                self.assertEqual(decision, ConductorDecision.EXTERNAL_BLOCK)
                self.assertEqual(reason, expected)

    def test_same_layer_status_and_terminal_external_blockers_both_checked(self) -> None:
        cases = (
            (
                {
                    "status": "completed",
                    "terminal": "manual_required",
                    "reason": "operator must intervene",
                    "evidence_verified": True,
                },
                "operator must intervene",
            ),
            (
                {
                    "status": "manual_required",
                    "terminal": "completed",
                    "reason": "manual account state",
                    "evidence_verified": True,
                },
                "manual account state",
            ),
            (
                {
                    "status": "completed",
                    "terminal": "manual_required",
                    "evidence_verified": True,
                },
                "manual_required",
            ),
            (
                {
                    "status": "completed",
                    "terminal": "manual_required",
                    "reason": "ordinary reconciliation is pending",
                    "evidence_verified": True,
                },
                "manual_required",
            ),
            (
                {
                    "status": "completed",
                    "evidence_verified": True,
                    "route_result": {
                        "status": "completed",
                        "terminal": "manual_required",
                        "next_action": "operator recovery required",
                    },
                },
                "operator recovery required",
            ),
        )
        state = load_state("FLOW-SAME-LAYER-EXTERNAL-BLOCK")
        for summary, expected in cases:
            with self.subTest(expected=expected):
                decision, reason = classify_summary(summary, state=state)
                self.assertEqual(decision, ConductorDecision.EXTERNAL_BLOCK)
                self.assertEqual(reason, expected)

    def test_structured_external_blockers_require_exact_normalized_tokens(self) -> None:
        state = load_state("FLOW-EXACT-STRUCTURED-EXTERNAL-BLOCK")
        for key in ("status", "terminal"):
            with self.subTest(key=key):
                decision, _ = classify_summary(
                    {key: "failed_manual_required_parse"},
                    state=state,
                )
                self.assertNotEqual(decision, ConductorDecision.EXTERNAL_BLOCK)

        for key, value in (
            ("status", " manual_required "),
            ("terminal", "MANUAL_ONLY_STATE"),
        ):
            with self.subTest(key=key, value=value):
                decision, reason = classify_summary({key: value}, state=state)
                self.assertEqual(decision, ConductorDecision.EXTERNAL_BLOCK)
                self.assertEqual(reason, value.strip().casefold())

    def test_effect_reconciliation_never_becomes_done(self) -> None:
        state = load_state("DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION")
        decision, reason = classify_summary(
            {
                "status": "completed",
                "evidence_verified": True,
                "effect_reconciliation_required": True,
            },
            state=state,
        )
        self.assertNotEqual(decision, ConductorDecision.DONE)
        self.assertEqual(reason, "effect_reconciliation_required")

    def test_effect_reconciliation_repeats_converge_without_done(self) -> None:
        state = load_state("FLOW-EFFECT-RECONCILIATION")
        summary = {
            "status": "completed",
            "evidence_verified": True,
            "effect_reconciliation_required": True,
        }
        state = record_iteration(state, summary=summary)
        self.assertEqual(state.last_decision, ConductorDecision.CONTINUE.value)
        self.assertEqual(state.last_blocker, "effect_reconciliation_required")
        self.assertEqual(state.iterations_since_progress, 1)
        state = record_iteration(state, summary=summary)
        self.assertEqual(state.last_decision, ConductorDecision.STEP_BACK.value)
        self.assertEqual(state.step_backs_spent, 1)
        state = record_iteration(state, summary=summary)
        self.assertEqual(state.last_decision, ConductorDecision.ESCALATE.value)
        self.assertNotEqual(state.last_decision, ConductorDecision.DONE.value)

    def test_nested_reconciliation_progress_resets_without_proving_effect(self) -> None:
        state = load_state("FLOW-NESTED-EFFECT-RECONCILIATION")
        state.iterations_since_progress = 2
        state = record_iteration(
            state,
            summary={
                "status": "completed",
                "evidence_verified": True,
                "result": {
                    "reconciliation_status": "effect_reconciliation_required",
                },
            },
            milestone="COMMANDER_RECOGNIZED",
        )
        self.assertEqual(state.last_decision, ConductorDecision.CONTINUE.value)
        self.assertEqual(state.last_blocker, "effect_reconciliation_required")
        self.assertEqual(state.furthest_milestone, "COMMANDER_RECOGNIZED")
        self.assertEqual(state.iterations_since_progress, 0)
        self.assertNotEqual(state.last_decision, ConductorDecision.DONE.value)

    def test_reconciliation_preserves_external_blocker(self) -> None:
        state = load_state("FLOW-EFFECT-EXTERNAL-BLOCK")
        decision, reason = classify_summary(
            {
                "status": "blocked",
                "blocker": "manual_only_state",
                "result": {"effect_reconciliation_required": True},
            },
            state=state,
        )
        self.assertEqual(decision, ConductorDecision.EXTERNAL_BLOCK)
        self.assertEqual(reason, "manual_only_state")

    def test_framing_incomplete_blocks_continue(self) -> None:
        state = load_state("ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION")
        state = apply_framing(
            state,
            FramingChecklist(intent_match=True),
        )
        self.assertEqual(
            state.last_decision, ConductorDecision.FRAMING_INCOMPLETE.value
        )

    def test_classify_done_and_external_block(self) -> None:
        state = load_state("NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE")
        done, _ = classify_summary(
            {
                "status": "completed",
                "terminal_home_verified": True,
                "evidence_verified": True,
            },
            state=state,
        )
        self.assertEqual(done, ConductorDecision.DONE)
        blocked, reason = classify_summary(
            {"status": "blocked", "blocker": "manual_only_state"},
            state=state,
        )
        self.assertEqual(blocked, ConductorDecision.EXTERNAL_BLOCK)
        self.assertIn("manual", reason)
        manual_required, _ = classify_summary(
            {"status": "manual_required"},
            state=state,
        )
        self.assertEqual(manual_required, ConductorDecision.EXTERNAL_BLOCK)

    def test_failed_local_operator_repair_converges_normally(self) -> None:
        summary = {
            "status": "failed",
            "next_action": "repair the local operator error",
        }
        state = load_state("FLOW-LOCAL-OPERATOR-REPAIR")

        state = record_iteration(state, summary=summary)
        self.assertEqual(state.last_decision, ConductorDecision.CONTINUE.value)
        self.assertNotEqual(state.last_decision, ConductorDecision.EXTERNAL_BLOCK.value)

        state = record_iteration(state, summary=summary)
        self.assertEqual(state.last_decision, ConductorDecision.STEP_BACK.value)
        state = record_iteration(state, summary=summary)
        self.assertEqual(state.last_decision, ConductorDecision.ESCALATE.value)

    def test_operator_error_text_does_not_create_external_block(self) -> None:
        state = load_state("FLOW-OPERATOR-ERROR-TEXT")
        decision, reason = classify_summary(
            {
                "status": "failed",
                "reason": "OperatorError: local route repair failed",
            },
            state=state,
        )
        self.assertEqual(decision, ConductorDecision.CONTINUE)
        self.assertEqual(reason, "operatorerror: local route repair failed")

    def test_completed_execution_requires_verified_evidence_for_done(self) -> None:
        state = load_state("FLOW-VERIFY")
        decision, _ = classify_summary({"status": "completed"}, state=state)
        self.assertEqual(decision, ConductorDecision.CONTINUE)
        verified, _ = classify_summary(
            {"status": "completed", "evidence_verified": True},
            state=state,
        )
        self.assertEqual(verified, ConductorDecision.DONE)

    def test_nested_blockers_remain_distinct_and_progress_resets_counter(self) -> None:
        state = load_state("FLOW-NESTED")
        state = record_iteration(
            state,
            summary={"status": "blocked", "result": {"reason": "home_not_localized"}},
            milestone="HOME_SEARCH",
        )
        self.assertEqual(state.defect_signatures, ["home_not_localized"])
        state.iterations_since_progress = 2
        state = record_iteration(
            state,
            summary={"status": "blocked", "result": {"reason": "target_not_bound"}},
            milestone="COMMANDER_RECOGNIZED",
        )
        self.assertEqual(state.last_decision, ConductorDecision.CONTINUE.value)
        self.assertEqual(state.iterations_since_progress, 0)
        self.assertEqual(
            state.defect_signatures,
            ["home_not_localized", "target_not_bound"],
        )

    def test_repeat_defect_triggers_step_back_then_escalate(self) -> None:
        state = load_state("FLOW-A")
        state = record_iteration(
            state,
            summary={
                "status": "blocked",
                "result": {"reason": "initial_surface_not_home"},
            },
        )
        self.assertEqual(state.last_decision, ConductorDecision.CONTINUE.value)
        state = record_iteration(
            state,
            summary={
                "status": "blocked",
                "result": {"reason": "initial_surface_not_home"},
            },
        )
        self.assertEqual(state.last_decision, ConductorDecision.STEP_BACK.value)
        self.assertEqual(state.step_backs_spent, 1)
        state = record_iteration(
            state,
            summary={
                "status": "blocked",
                "result": {"reason": "initial_surface_not_home"},
            },
        )
        self.assertEqual(state.last_decision, ConductorDecision.ESCALATE.value)

    def test_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = load_state("FLOW-B", root=root)
            state = apply_framing(
                state,
                FramingChecklist(
                    intent_match=True,
                    no_documented_unsafe_input=True,
                    no_manual_only_precondition=True,
                    consequential_actions_enumerated=True,
                    durable_knowledge_consulted=True,
                ),
            )
            path = save_state(state, root=root)
            loaded = load_state("FLOW-B", root=root)
            self.assertEqual(loaded.status, "framed")
            self.assertTrue(path.is_file())

    def test_pnsctl_conduct_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code = pnsctl.main(
                [
                    "conduct",
                    "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION",
                    "--state-root",
                    str(root),
                ]
            )
            self.assertEqual(code, 0)
            state = load_state(
                "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION", root=root
            )
            self.assertEqual(state.status, "framed")

    def test_conduct_live_requires_route_specific_verification(self) -> None:
        flow_id = "SUPPLY-DEPOT-BLUESTACKS-INTEGRATION"
        retained = {
            "schema_version": 1,
            "flow_id": flow_id,
            "status": "completed",
            "terminal_home_verified": True,
            "dispatch": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch(
                    "tasks.gameplay_flow_contracts.load_flow_contract",
                    return_value={
                        "flow_id": flow_id,
                        "consequential_action_class": "ordinary_resource_use",
                    },
                ),
                patch.object(
                    pnsctl,
                    "development_session_observe",
                    return_value=json.dumps({"status": "observed"}),
                ),
                patch.object(
                    pnsctl,
                    "development_session_run_flow",
                    return_value=json.dumps(
                        {
                            "status": "completed",
                            "runtime_session_directory": "retained",
                        }
                    ),
                ),
                patch.object(
                    pnsctl,
                    "_retained_flow_result",
                    return_value=(Path("retained"), retained),
                ),
                patch.object(
                    pnsctl,
                    "bluestacks_verify_flow",
                    return_value=json.dumps(
                        {
                            "status": "evidence_required",
                            "flow_id": flow_id,
                            "reason": "independent postcondition failed",
                        }
                    ),
                ),
            ):
                result = json.loads(
                    pnsctl.conduct_flow(
                        flow_id,
                        live=True,
                        yes=True,
                        state_root=root,
                    )
                )
            self.assertNotEqual(result["decision"], ConductorDecision.DONE.value)
            self.assertEqual(result["verification"]["status"], "evidence_required")
            self.assertEqual(load_state(flow_id, root=root).status, "local_defect")

    def test_conduct_live_accepts_verified_completed_evidence(self) -> None:
        flow_id = "SUPPLY-DEPOT-BLUESTACKS-INTEGRATION"
        retained = {
            "schema_version": 1,
            "flow_id": flow_id,
            "status": "completed",
            "terminal_home_verified": True,
            "dispatch": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch(
                    "tasks.gameplay_flow_contracts.load_flow_contract",
                    return_value={
                        "flow_id": flow_id,
                        "consequential_action_class": "ordinary_resource_use",
                    },
                ),
                patch.object(
                    pnsctl,
                    "development_session_observe",
                    return_value=json.dumps({"status": "observed"}),
                ),
                patch.object(
                    pnsctl,
                    "development_session_run_flow",
                    return_value=json.dumps(
                        {
                            "status": "completed",
                            "runtime_session_directory": "retained",
                        }
                    ),
                ),
                patch.object(
                    pnsctl,
                    "_retained_flow_result",
                    return_value=(Path("retained"), retained),
                ),
                patch.object(
                    pnsctl,
                    "bluestacks_verify_flow",
                    return_value=json.dumps(
                        {"status": "verified", "flow_id": flow_id}
                    ),
                ),
            ):
                result = json.loads(
                    pnsctl.conduct_flow(
                        flow_id,
                        live=True,
                        yes=True,
                        state_root=root,
                    )
                )
            self.assertEqual(result["decision"], ConductorDecision.DONE.value)
            completed_state = load_state(flow_id, root=root)
            self.assertEqual(completed_state.status, "done")
            self.assertEqual(completed_state.evidence_refs, ["retained"])

    def test_framing_is_derived_from_bound_handlers_and_policy(self) -> None:
        flow_id = "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION"
        complete = pnsctl._derive_conductor_framing(flow_id)
        self.assertTrue(all(complete.values()))
        with patch.dict(pnsctl._BLUESTACKS_EVIDENCE_VALIDATORS, {}, clear=True):
            incomplete = pnsctl._derive_conductor_framing(flow_id)
        self.assertFalse(incomplete["intent_match"])
        self.assertFalse(incomplete["no_documented_unsafe_input"])

    def test_routine_conduct_cohort_has_valid_contracts_and_complete_framing(
        self,
    ) -> None:
        cohort = tuple(pnsctl._CONDUCT_DEFAULT_MAX_INPUTS)
        registry = pnsctl._load_bluestacks_flow_registry()
        self.assertEqual(len(cohort), len(set(cohort)))
        self.assertTrue(set(cohort) <= set(registry))
        for flow_id in cohort:
            with self.subTest(flow_id=flow_id):
                contract = load_flow_contract(flow_id)
                self.assertEqual(contract["flow_id"], flow_id)
                framing = pnsctl._derive_conductor_framing(flow_id)
                self.assertTrue(all(framing.values()), framing)

    def test_live_conduct_requires_authoritative_active_flow_contract(self) -> None:
        flow_id = "SUPPLY-DEPOT-BLUESTACKS-INTEGRATION"
        cases = (
            ("missing", FlowContractError("missing contract"), None),
            ("unreadable", OSError("unreadable contract"), None),
            ("malformed", FlowContractError("invalid proof_state"), None),
            ("wrong-flow", None, {"flow_id": "OTHER-FLOW"}),
        )
        asserted_framing = {
            field: True for field in FramingChecklist.__dataclass_fields__
        }
        for label, error, contract in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                loader = patch(
                    "tasks.gameplay_flow_contracts.load_flow_contract",
                    side_effect=error,
                    return_value=contract,
                )
                with (
                    loader,
                    patch.object(
                        pnsctl,
                        "development_session_observe",
                        return_value=json.dumps({"status": "observed"}),
                    ) as observe,
                    patch.object(
                        pnsctl,
                        "development_session_run_flow",
                        return_value=json.dumps({"status": "blocked"}),
                    ) as run_flow,
                ):
                    result = json.loads(
                        pnsctl.conduct_flow(
                            flow_id,
                            live=True,
                            yes=True,
                            framing=asserted_framing,
                            state_root=Path(directory),
                        )
                    )
                self.assertEqual(result["status"], "framing_incomplete")
                observe.assert_not_called()
                run_flow.assert_not_called()

    def test_conductor_uses_flow_specific_default_input_ceiling(self) -> None:
        self.assertEqual(
            pnsctl._conduct_max_inputs(
                "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION", None
            ),
            4,
        )
        self.assertEqual(
            pnsctl._conduct_max_inputs(
                "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION", None
            ),
            24,
        )
        self.assertEqual(
            pnsctl._conduct_max_inputs(
                "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION", 3
            ),
            3,
        )

    def test_operational_verification_rejects_missing_retained_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / ".local-captures" / "missing-result"
            session.mkdir(parents=True)
            with patch.object(pnsctl, "REPO_ROOT", root):
                with self.assertRaisesRegex(
                    pnsctl.OperatorError,
                    "flow-delivery-result.json is required",
                ):
                    pnsctl.bluestacks_verify_flow(session)

    def test_pnsctl_conduct_classifies_summary_without_live(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = Path(directory) / "summary.json"
            summary.write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "blocker": "initial_surface_not_home_or_known_nova_context",
                    }
                ),
                encoding="utf-8",
            )
            code = pnsctl.main(
                [
                    "conduct",
                    "NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE",
                    "--summary",
                    str(summary),
                    "--state-root",
                    str(root),
                ]
            )
            self.assertEqual(code, 0)
            state = load_state("NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE", root=root)
            self.assertEqual(state.last_decision, ConductorDecision.CONTINUE.value)
            self.assertEqual(state.status, "local_defect")

    def test_summary_path_recognizes_real_nested_milestone_progress(self) -> None:
        flow_id = "NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for ordinal, milestone in enumerate(
                ("HOME_SEARCH", "COMMANDER_RECOGNIZED"),
                start=1,
            ):
                summary = root / f"summary-{ordinal}.json"
                summary.write_text(
                    json.dumps(
                        {
                            "status": "blocked",
                            "result": {
                                "reason": f"failure-{ordinal}",
                                "milestone": milestone,
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                pnsctl.conduct_flow(
                    flow_id,
                    summary_path=summary,
                    state_root=root,
                )
            state = load_state(flow_id, root=root)
            self.assertEqual(state.furthest_milestone, "COMMANDER_RECOGNIZED")
            self.assertEqual(state.iterations_since_progress, 0)

    def test_summary_path_status_change_is_not_fake_progress(self) -> None:
        flow_id = "NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for ordinal, status in enumerate(("blocked", "failed"), start=1):
                summary = root / f"summary-{ordinal}.json"
                summary.write_text(
                    json.dumps(
                        {
                            "status": status,
                            "result": {
                                "reason": f"failure-{ordinal}",
                                "milestone": "COMMANDER_RECOGNIZED",
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                pnsctl.conduct_flow(
                    flow_id,
                    summary_path=summary,
                    state_root=root,
                )
            state = load_state(flow_id, root=root)
            self.assertEqual(state.furthest_milestone, "COMMANDER_RECOGNIZED")
            self.assertEqual(state.iterations_since_progress, 1)


if __name__ == "__main__":
    unittest.main()
