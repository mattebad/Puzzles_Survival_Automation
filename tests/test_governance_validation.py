from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_governance


class GovernanceValidationTests(unittest.TestCase):
    def test_repository_governance_contract_passes(self):
        errors, warnings = validate_governance.validate_repository(ROOT)
        self.assertEqual(errors, [])
        self.assertTrue(any("untouched legacy" in warning for warning in warnings))

    def test_handoff_has_distinct_current_and_next_task_fields(self):
        state = validate_governance.parse_handoff()
        self.assertEqual(state["current_task_id"], "HOME-NAVIGATION-BOUNDED-SESSION-CALIBRATION")
        self.assertEqual(state["current_task_state"], "in_progress")
        self.assertEqual(
            state["next_task_id"],
            "RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION",
        )
        self.assertEqual(
            state["next_task_activation_status"],
            "dependency_blocked",
        )
        self.assertNotEqual(state["current_task_id"], state["next_task_id"])

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

    def test_declared_successor_exists_without_becoming_active(self):
        state = validate_governance.parse_handoff()
        backlog = (ROOT / "BACKLOG.md").read_text(encoding="utf-8")
        next_block = validate_governance.task_block(backlog, state["next_task_id"])
        self.assertIn("RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION", next_block)
        self.assertIn("Pending", next_block)
        self.assertIn("not activated", next_block)
        validate_governance.validate_successor(backlog, state)
        validate_governance.validate_repository(ROOT)

    def test_active_offline_collector_contract_is_complete(self):
        state = validate_governance.parse_handoff()
        backlog = (ROOT / "BACKLOG.md").read_text(encoding="utf-8")
        active_block = validate_governance.task_block(backlog, state["current_task_id"])
        fields = validate_governance.validate_task_contract(
            active_block,
            state["current_task_id"],
        )
        self.assertTrue(fields["Evidence requirement"].startswith("NOT_APPLICABLE"))
        self.assertIsNone(state["evidence"]["active_evidence_manifest"])
        self.assertIsNone(
            validate_governance.validate_task_evidence(
                state,
                fields,
                state["current_task_id"],
                ROOT,
            )
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

    def test_offline_evidence_requires_explicit_reason(self):
        state = copy.deepcopy(validate_governance.parse_handoff())
        backlog = (ROOT / "BACKLOG.md").read_text(encoding="utf-8")
        fields = validate_governance.validate_task_contract(
            validate_governance.task_block(backlog, state["current_task_id"]),
            state["current_task_id"],
        )
        state["evidence"]["evidence_requirement_reason"] = ""
        with self.assertRaises(validate_governance.GovernanceValidationError):
            validate_governance.validate_task_evidence(
                state,
                fields,
                state["current_task_id"],
                ROOT,
            )

    def test_live_task_cannot_bypass_required_evidence(self):
        state = copy.deepcopy(validate_governance.parse_handoff())
        backlog = (ROOT / "BACKLOG.md").read_text(encoding="utf-8")
        mvp_fields = validate_governance.validate_task_contract(
            validate_governance.task_block(backlog, "MVP-QUEST-TO-CLAIM"),
            "MVP-QUEST-TO-CLAIM",
        )
        state["evidence"]["evidence_requirement"] = "NOT_APPLICABLE"
        state["evidence"]["evidence_requirement_reason"] = "incorrect bypass"
        state["evidence"]["active_evidence_manifest"] = None
        with self.assertRaises(validate_governance.GovernanceValidationError):
            validate_governance.validate_task_evidence(
                state,
                mvp_fields,
                "MVP-QUEST-TO-CLAIM",
                ROOT,
            )


if __name__ == "__main__":
    unittest.main()
