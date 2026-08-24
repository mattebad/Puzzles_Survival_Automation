from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_governance


class GovernanceValidationTests(unittest.TestCase):
    def test_repository_governance_contract_passes(self):
        errors, warnings = validate_governance.validate_repository(ROOT)
        self.assertEqual(errors, [])
        self.assertTrue(any("untouched legacy" in warning for warning in warnings))

    def test_flow_delivery_loop_policy_is_validated(self):
        payload = validate_governance.validate_flow_delivery_loop_policy(ROOT)
        self.assertEqual(payload["registry_kind"], "flow_delivery_loop_policy")
        self.assertEqual(payload["max_completed_flows_per_parent_conversation"], 2)
        self.assertIn(".local-orchestrator/", (ROOT / ".gitignore").read_text(encoding="utf-8"))

    def test_handoff_has_distinct_current_and_next_stage_fields(self):
        state = validate_governance.parse_handoff()
        self.assertNotEqual(state["current_task_id"], state["next_task_id"])
        self.assertEqual(
            state["next_task_activation_status"],
            "awaiting_explicit_activation",
        )
        self.assertEqual(
            state["exact_next_permitted_action"],
            state["exact_next_permitted_action"].strip(),
        )
        self.assertEqual(state["control_owner"], "sol_parent")
        self.assertNotIn("actions_already_performed", state)

    def test_manifest_uses_fixed_artifact_state_schema(self):
        manifest = validate_governance.validate_manifest()
        self.assertTrue(manifest["artifacts"])
        for artifact in manifest["artifacts"]:
            self.assertEqual(
                set(artifact),
                {
                    "artifact_id",
                    "status",
                    "path",
                    "expected_sha256",
                    "actual_sha256",
                    "reason",
                },
            )
        self.assertIn("NOT_LOCATED", {item["status"] for item in manifest["artifacts"]})

    def test_manifest_rejects_invented_missing_path(self):
        original = json.loads(
            (ROOT / "evidence" / "current-evidence-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        original["artifacts"][3]["path"] = "evidence/not-located.png"
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "manifest.json"
            candidate.write_text(json.dumps(original), encoding="utf-8")
            with self.assertRaises(validate_governance.GovernanceValidationError):
                validate_governance.validate_manifest(candidate)

    def test_indexing_rules_exclude_raw_material_and_keep_lightweight_files(self):
        validate_governance.validate_indexing_rules()
        patterns = {
            line.strip()
            for line in (ROOT / ".cursorindexingignore").read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertIn("evidence/**/*.png", patterns)
        self.assertNotIn("evidence/current-evidence-manifest.json", patterns)

    def test_declared_successor_remains_inactive(self):
        state = validate_governance.parse_handoff()
        self.assertIsInstance(state["next_task_id"], str)
        self.assertEqual(
            state["next_task_activation_status"],
            "awaiting_explicit_activation",
        )
        self.assertEqual(state["active_task_or_flow"], "none")

    def test_active_stage_evidence_contract_is_complete(self):
        state = validate_governance.parse_handoff()
        evidence = state["evidence"]
        self.assertTrue(evidence["evidence_requirement"].strip())
        self.assertTrue(evidence["monitoring_issue"].strip())
        self.assertTrue(evidence["do_not_recursively_inspect_parent_evidence_tree"])
        self.assertEqual(
            set(state["budgets"]),
            {
                "stage_revisions_used",
                "managed_turns_used",
                "live_attempts_used",
                "runtime_inputs_used",
            },
        )

    def test_existing_gov_and_mvp_contracts_remain_structurally_valid(self):
        backlog = (ROOT / "BACKLOG.md").read_text(encoding="utf-8")
        for task_id in ("GOV-DURABLE-STATE", "MVP-QUEST-TO-CLAIM"):
            fields = validate_governance.validate_task_contract(
                validate_governance.task_block(backlog, task_id),
                task_id,
            )
            self.assertEqual(fields["Evidence requirement"].split()[0].rstrip(":,.;"), "REQUIRED")

    def test_nonexistent_task_id_is_rejected(self):
        backlog = (ROOT / "BACKLOG.md").read_text(encoding="utf-8")
        with self.assertRaises(validate_governance.GovernanceValidationError):
            validate_governance.task_block(backlog, "NOT-A-REAL-TASK")

    def test_completed_state_is_canonical_and_passed_is_rejected(self):
        text = (ROOT / "CURRENT_HANDOFF.md").read_text(encoding="utf-8")
        current_state = validate_governance.parse_handoff()["current_task_state"]
        completed = text.replace(
            f'"current_task_state": "{current_state}"',
            '"current_task_state": "completed"',
            1,
        )
        with tempfile.TemporaryDirectory() as directory:
            completed_path = Path(directory) / "completed.md"
            completed_path.write_text(completed, encoding="utf-8")
            self.assertEqual(
                validate_governance.parse_handoff(completed_path)["current_task_state"],
                "completed",
            )
            passed_path = Path(directory) / "passed.md"
            passed_path.write_text(
                completed.replace(
                    '"current_task_state": "completed"',
                    '"current_task_state": "passed"',
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaises(validate_governance.GovernanceValidationError):
                validate_governance.parse_handoff(passed_path)

    def test_schema_three_rejects_empty_evidence_requirement(self):
        text = (ROOT / "CURRENT_HANDOFF.md").read_text(encoding="utf-8")
        current = validate_governance.parse_handoff()["evidence"]["evidence_requirement"]
        candidate = text.replace(
            json.dumps(current),
            '""',
            1,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "CURRENT_HANDOFF.md"
            path.write_text(candidate, encoding="utf-8")
            with self.assertRaises(validate_governance.GovernanceValidationError):
                validate_governance.parse_handoff(path)

    def test_schema_three_rejects_scheduler_enablement(self):
        text = (ROOT / "CURRENT_HANDOFF.md").read_text(encoding="utf-8").replace(
            '"scheduler_enabled": false',
            '"scheduler_enabled": true',
            1,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "CURRENT_HANDOFF.md"
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(validate_governance.GovernanceValidationError):
                validate_governance.parse_handoff(path)


    def _assert_repository_rejects(self, mutate):
        state = copy.deepcopy(validate_governance.parse_handoff())
        mutate(state)
        with patch.object(validate_governance, "parse_handoff", return_value=state):
            with self.assertRaises(validate_governance.GovernanceValidationError):
                validate_governance.validate_repository(ROOT)

    def test_valid_current_stage_handoff_relations_pass(self):
        state = validate_governance.parse_handoff()
        validate_governance.validate_git_bindings(ROOT, state)
        validate_governance.validate_handoff_relations(state)
        validate_governance.validate_lifecycle_relations(state)

    def test_schema_three_rejects_nonexistent_head_binding(self):
        self._assert_repository_rejects(lambda state: state.update({"head_binding": "0" * 40}))

    def test_schema_three_rejects_malformed_or_backwards_stage_successor(self):
        for successor in ("not-a-stage", "stage-7-autonomous-service-implementation"):
            with self.subTest(successor=successor):
                self._assert_repository_rejects(
                    lambda state, successor=successor: state.update(
                        {"next_task_id": successor}
                    )
                )

    def test_completed_stage_rejects_active_control_state(self):
        mutations = {
            "active_flow": lambda state: state.update({"active_task_or_flow": "flow-x"}),
            "manifest": lambda state: state.update(
                {"active_execution_manifest_path": "evidence/current-evidence-manifest.json"}
            ),
            "lease": lambda state: state.update({"development_lease_state": "held"}),
            "owner": lambda state: state.update({"runtime_ownership_state": "flow-x"}),
            "unresolved_action": lambda state: state.update(
                {"unresolved_action_state": "action-123"}
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                self._assert_repository_rejects(mutate)

    def test_awaiting_activation_rejects_active_flow_or_runtime_authority(self):
        mutations = {
            "active_flow": lambda state: state.update({"active_task_or_flow": "flow-x"}),
            "manifest": lambda state: state.update(
                {"active_execution_manifest_path": "evidence/current-evidence-manifest.json"}
            ),
            "registration": lambda state: state["registration_and_scheduler"].update(
                {"production_registration": "REGISTERED"}
            ),
            "scheduler": lambda state: state["registration_and_scheduler"].update(
                {"scheduler_enabled": True}
            ),
            "owner": lambda state: state.update({"runtime_ownership_state": "flow-x"}),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                self._assert_repository_rejects(mutate)

    def test_legacy_backlog_state_evidence_and_successor_are_still_relational(self):
        cases = {
            "state": lambda state: state.update(
                {
                    "current_task_id": "GOV-DURABLE-STATE",
                    "current_task_state": "in_progress",
                }
            ),
            "evidence": lambda state: (
                state.update({"current_task_id": "GOV-DURABLE-STATE"}),
                state["evidence"].update({"evidence_requirement": "NOT_APPLICABLE"}),
            ),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                self._assert_repository_rejects(mutate)

        state = copy.deepcopy(validate_governance.parse_handoff())
        state["next_task_id"] = "NOT-A-REAL-TASK"
        with self.assertRaises(validate_governance.GovernanceValidationError):
            validate_governance.validate_successor(
                (ROOT / "BACKLOG.md").read_text(encoding="utf-8"),
                state,
            )


if __name__ == "__main__":
    unittest.main()
