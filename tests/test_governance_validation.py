from __future__ import annotations

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
        self.assertEqual(state["current_task_id"], "GOV-DURABLE-STATE")
        self.assertIn(
            state["current_task_state"],
            {"in_progress", "completed"},
        )
        self.assertEqual(state["next_task_id"], "MVP-QUEST-TO-CLAIM")
        self.assertEqual(
            state["next_task_activation_status"],
            "contract_migration_required",
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

    def test_next_task_is_not_required_to_have_active_contract(self):
        state = validate_governance.parse_handoff()
        backlog = (ROOT / "BACKLOG.md").read_text(encoding="utf-8")
        next_block = validate_governance.task_block(backlog, state["next_task_id"])
        with self.assertRaises(validate_governance.GovernanceValidationError):
            validate_governance.validate_task_contract(
                next_block,
                state["next_task_id"],
            )
        validate_governance.validate_repository(ROOT)


if __name__ == "__main__":
    unittest.main()
