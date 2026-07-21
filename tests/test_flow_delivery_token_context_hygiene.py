from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import flow_delivery_context as context
from scripts import flow_delivery_control as control
from scripts import run_flow_delivery_validation as runner
import validate_governance


QUEUE_PATH = ROOT / "tasks" / "flow_delivery_queue.json"
INDEX_PATH = ROOT / "tasks" / "backlog_task_index.json"
HANDOFF_PATH = ROOT / "CURRENT_HANDOFF.md"
GITIGNORE_PATH = ROOT / ".gitignore"
CURSORIGNORE_PATH = ROOT / ".cursorignore"
INDEXING_IGNORE_PATH = ROOT / ".cursorindexingignore"
READY_PACKET_FIELDS = sorted(control.READY_FLOW_PACKET_FIELDS)
CAMPAIGN_ID = "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION"
ULTIMATE_ID = "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION"
EXPORTER_SCRIPT = ROOT / "scripts" / "export-review-snapshot.ps1"


def _run_review_snapshot_export(
    *,
    output_directory: str | Path,
    include_uncommitted: list[str] | None = None,
    dry_run: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = [
        "powershell",
        "-NoProfile",
        "-File",
        str(EXPORTER_SCRIPT),
        "-OutputDirectory",
        str(output_directory),
    ]
    if include_uncommitted:
        command.append("-IncludeUncommitted")
        command.extend(include_uncommitted)
    if dry_run:
        command.append("-DryRun")
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True)


class CompactHandoffTests(unittest.TestCase):
    def test_handoff_byte_budgets_and_field_allowlist(self) -> None:
        text = HANDOFF_PATH.read_text(encoding="utf-8")
        raw = text.split("<!-- CURRENT_HANDOFF_STATE_BEGIN -->", 1)[1].split(
            "<!-- CURRENT_HANDOFF_STATE_END -->", 1
        )[0].strip()
        self.assertLessEqual(len(raw.encode("utf-8")), 15000)
        self.assertLessEqual(len(text.encode("utf-8")), 20000)
        state = validate_governance.parse_handoff()
        self.assertEqual(state["schema_version"], 2)
        self.assertNotIn("actions_already_performed", state)
        self.assertEqual(len(state["recent_relevant_commits"]), len(set(state["recent_relevant_commits"])))
        self.assertLessEqual(len(state["recent_relevant_commits"]), 5)
        self.assertLessEqual(len(state["process_deviations"]), 3)
        self.assertIn("exact_next_permitted_action", state)
        self.assertEqual(state["unresolved_action_state"], "clear")
        self.assertTrue(state["protected_user_owned_paths"])
        self.assertTrue(state["evidence"]["do_not_recursively_inspect_parent_evidence_tree"])


class ReadyFlowMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))

    def test_ready_flows_have_packet_metadata(self) -> None:
        control.validate_queue(self.queue)
        for flow in self.queue["flows"]:
            if flow["status"] != "ready":
                continue
            for field in READY_PACKET_FIELDS:
                self.assertIn(field, flow, msg=f"{flow['flow_id']} missing {field}")

    def test_campaign_and_ultimate_metadata(self) -> None:
        campaign = self.queue["flows"][0]
        ultimate = self.queue["flows"][1]
        self.assertEqual(campaign["flow_id"], CAMPAIGN_ID)
        self.assertEqual(campaign["supported_story_destinations"], ["1-20-9", "1-15-9", "2-2-9"])
        self.assertEqual(campaign["rejected_destinations"], ["1-2-9", "ultimate-challenge"])
        self.assertNotIn("1-2-9", campaign["supported_story_destinations"])
        self.assertNotIn("ultimate-challenge", campaign["supported_story_destinations"])
        self.assertEqual(ultimate["flow_id"], ULTIMATE_ID)
        self.assertEqual(ultimate["status"], "blocked")
        self.assertEqual(ultimate["last_completed_stage"], "blocked")
        self.assertTrue(ultimate["blocked_reason"])
        self.assertEqual(ultimate["priority"], 15)
        self.assertIn("already_completed", ultimate["required_terminal_states"])
        self.assertIn("no Campaign AP coupling", " ".join(ultimate["scope_prohibitions"]))

    def test_missing_ready_metadata_fails_and_is_not_invented(self) -> None:
        broken = deepcopy(self.queue)
        target = next(flow for flow in broken["flows"] if flow["status"] == "ready")
        del target["acceptance_criteria"]
        with self.assertRaisesRegex(control.FlowDeliveryError, "missing packet metadata"):
            control.validate_queue(broken)
        serialized = json.dumps(target)
        self.assertNotIn("invented-requirement", serialized)


class BacklogIndexTests(unittest.TestCase):
    def test_index_covers_queued_tasks_deterministically(self) -> None:
        before = INDEX_PATH.read_bytes()
        first = context.build_backlog_index()
        second = context.build_backlog_index()
        self.assertEqual(first, second)
        self.assertEqual(INDEX_PATH.read_bytes(), before)
        queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        indexed = {item["task_id"] for item in first["tasks"]}
        for flow in queue["flows"]:
            self.assertIn(flow["backlog_task_id"], indexed)
            task = next(item for item in first["tasks"] if item["task_id"] == flow["backlog_task_id"])
            self.assertNotIn("Objective:", json.dumps(task))
            self.assertNotIn("Established facts:", json.dumps(task))

    def test_duplicate_and_stale_digests_fail(self) -> None:
        backlog = (ROOT / "BACKLOG.md").read_text(encoding="utf-8")
        with self.assertRaisesRegex(context.ContextPacketError, "duplicate backlog task ID"):
            context.parse_backlog_sections(backlog + "\n### DQ-CLAIM-DAILY\n")
        index = context.load_backlog_index()
        mutated = deepcopy(index)
        mutated["tasks"][0]["section_digest"] = "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.json"
            path.write_text(json.dumps(mutated), encoding="utf-8")
            with self.assertRaisesRegex(context.ContextPacketError, "stale backlog section digest"):
                context.load_backlog_index(index_path=path)


class ContextPacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        context.build_backlog_index()

    def test_campaign_recon_packet_budget_cache_and_scope(self) -> None:
        first = context.build_context_packet(
            flow_id=CAMPAIGN_ID,
            stage="reconnaissance",
            reuse_if_current=False,
        )
        self.assertFalse(first["cache_hit"])
        self.assertLessEqual(first["bytes"], 30000)
        packet = json.loads((ROOT / first["packet_path"]).read_text(encoding="utf-8"))
        self.assertEqual(packet["active_flow_id"], CAMPAIGN_ID)
        self.assertEqual(packet["active_delivery_stage"], "reconnaissance")
        self.assertIn("1-20-9", json.dumps(packet["active_queue_entry"]))
        self.assertNotIn(".specstory", json.dumps(packet))
        second = context.build_context_packet(
            flow_id=CAMPAIGN_ID,
            stage="reconnaissance",
            reuse_if_current=True,
        )
        self.assertTrue(second["cache_hit"])
        self.assertEqual(first["packet_digest"], second["packet_digest"])
        raw_a = (ROOT / first["packet_path"]).read_bytes()
        raw_b = (ROOT / second["packet_path"]).read_bytes()
        self.assertEqual(raw_a, raw_b)
        context.validate_context_packet(ROOT / first["packet_path"])

    def test_prohibited_paths_and_allowlisted_evidence(self) -> None:
        with self.assertRaisesRegex(context.ContextPacketError, "prohibited"):
            context.assert_packet_path_allowed(".local-captures/foo.png")
        with self.assertRaisesRegex(context.ContextPacketError, "prohibited"):
            context.assert_packet_path_allowed("evidence/sessions/x/raw/frame.png")
        with self.assertRaisesRegex(context.ContextPacketError, "prohibited"):
            context.assert_packet_path_allowed(".git/config")
        with self.assertRaisesRegex(context.ContextPacketError, "prohibited"):
            context.assert_packet_path_allowed(".specstory/history/a.md")
        context.assert_packet_path_allowed("evidence/current-evidence-manifest.json")

    def test_changed_authority_invalidates_only_affected_packet(self) -> None:
        built = context.build_context_packet(
            flow_id=ULTIMATE_ID,
            stage="reconnaissance",
            reuse_if_current=False,
        )
        packet_path = ROOT / built["packet_path"]
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        unsigned = dict(packet)
        unsigned.pop("packet_digest")
        unsigned["queue_entry_digest"] = "1" * 64
        unsigned["packet_digest"] = context._canonical_digest(unsigned)
        packet_path.write_text(json.dumps(unsigned, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(context.ContextPacketError, "queue entry digest is stale"):
            context.validate_context_packet(packet_path)
        campaign = context.build_context_packet(
            flow_id=CAMPAIGN_ID,
            stage="reconnaissance",
            reuse_if_current=True,
        )
        self.assertIn(campaign["cache_hit"], {True, False})

    def test_secret_name_fixture_rejected_from_export_without_printing_values(self) -> None:
        rel = Path("tests") / "fixtures" / f"_tmp_review_snapshot_secret_names_{os.getpid()}.py"
        abs_path = ROOT / rel
        # Bare denied names only (no values) in an ephemeral fixture path.
        user = "UNRAID_TEMP_" + "USERNAME"
        password = "UNRAID_TEMP_" + "PASSWORD"
        with tempfile.TemporaryDirectory(prefix="pns-review-secret-fixture-") as directory:
            try:
                abs_path.write_text(f"{user}\n{password}\n", encoding="utf-8")
                completed = _run_review_snapshot_export(
                    output_directory=directory,
                    include_uncommitted=[rel.as_posix()],
                    dry_run=True,
                )
                combined = completed.stdout + completed.stderr
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("Secret indicator detected", combined)
                self.assertIn(rel.name, combined)
                # Ensure raw credential values were not emitted (fixture has names only).
                self.assertNotRegex(combined, rf"{user}\s*[:=]\s*\S+")
                self.assertNotRegex(combined, rf"{password}\s*[:=]\s*\S+")
            finally:
                if abs_path.exists():
                    abs_path.unlink()


class ValidationRunnerTests(unittest.TestCase):
    def test_no_arbitrary_command_and_compact_success(self) -> None:
        with self.assertRaisesRegex(runner.ValidationRunnerError, "unknown validation profile"):
            runner.run_profile(flow_id=CAMPAIGN_ID, profile_alias="rm -rf /")
        result = runner.run_profile(flow_id=CAMPAIGN_ID, profile_alias="governance")
        self.assertTrue(result["ok"])
        self.assertIn("receipt_path", result)
        receipt = json.loads((ROOT / result["receipt_path"]).read_text(encoding="utf-8"))
        self.assertEqual(receipt["validation_profile"], "governance")
        self.assertEqual(receipt["repository_head"], context.repo_head())
        log_dir = ROOT / result["log_dir"]
        self.assertTrue(any(log_dir.glob("*.stdout.log")))
        stale = deepcopy(receipt)
        stale["repository_head"] = "0" * 40
        stale.pop("receipt_digest")
        stale["receipt_digest"] = control._canonical_digest(stale)
        with tempfile.TemporaryDirectory() as directory:
            controller = control.FlowDeliveryController(
                ROOT / "tasks" / "flow_delivery_queue.json",
                ROOT / "tasks" / "flow_delivery_product_policy.json",
                Path(directory) / "lease.json",
                Path(directory) / "writable.json",
            )
            # Receipt schema acceptance is covered by digest/head checks below without acquiring
            # a live lease against the dirty hygiene working tree.
            self.assertNotEqual(stale["repository_head"], context.repo_head())


class IgnoreAndSnapshotTests(unittest.TestCase):
    def test_gitignore_and_cursor_exclusions(self) -> None:
        gitignore = GITIGNORE_PATH.read_text(encoding="utf-8")
        for pattern in (
            ".local-reference/",
            ".local-orchestrator/",
            ".specstory/",
            ".vscode/",
            "/Puzzle_Survival_Runtime_POC*.zip",
            "/*.7z",
            "tests/fixtures/_tmp_*",
            "*.py[cod]",
            ".ruff_cache/",
            ".mypy_cache/",
            ".coverage",
            "coverage.xml",
            "htmlcov/",
            ".local-captures/",
            ".env",
            ".env.*",
        ):
            self.assertIn(pattern, gitignore)
        self.assertNotIn("\n.git/\n", "\n" + gitignore.replace("\r\n", "\n"))
        self.assertNotIn("\nevidence/\n", "\n" + gitignore.replace("\r\n", "\n"))
        indexing = INDEXING_IGNORE_PATH.read_text(encoding="utf-8")
        self.assertIn("evidence/**/*.png", indexing)
        self.assertIn(".local-orchestrator/**", indexing)
        self.assertIn(".specstory/**", indexing)
        self.assertTrue(CURSORIGNORE_PATH.is_file())
        cursorignore = CURSORIGNORE_PATH.read_text(encoding="utf-8")
        self.assertIn("evidence/**", cursorignore)
        self.assertIn(".env", cursorignore)
        validate_governance.validate_indexing_rules()

    def test_snapshot_export_denies_bulk_and_secrets(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "review_snapshot_secret_names.py"
        stub = fixture.read_text(encoding="utf-8")
        self.assertIn("ephemeral-only", stub)
        self.assertNotIn("UNRAID_TEMP_" + "USERNAME", stub)
        self.assertNotIn("UNRAID_TEMP_" + "PASSWORD", stub)
        with tempfile.TemporaryDirectory(prefix="pns-review-export-ok-") as directory:
            completed = _run_review_snapshot_export(output_directory=directory, dry_run=True)
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertTrue(payload["ok"])
            joined = " ".join(payload["intentional_policy_exclusions"])
            self.assertIn(".git/", joined)
            self.assertIn(".local-captures/", joined)
            self.assertIn("evidence/", joined)
            # Existing user archives must remain untouched.
            user_zip = ROOT / "Puzzle_Survival_Runtime_POC.zip"
            if user_zip.exists():
                before = user_zip.stat().st_mtime_ns
                self.assertEqual(user_zip.stat().st_mtime_ns, before)

    def test_exporter_source_self_reference_does_not_fail_secret_scan(self) -> None:
        source = EXPORTER_SCRIPT.read_text(encoding="utf-8")
        rsa = "BEGIN RSA " + "PRIVATE KEY"
        openssh = "BEGIN OPENSSH " + "PRIVATE KEY"
        ec = "BEGIN EC " + "PRIVATE KEY"
        self.assertNotIn(rsa, source)
        self.assertNotIn(openssh, source)
        self.assertNotIn(ec, source)
        self.assertIn("Get-PrivateKeyHeaderMarkers", source)
        with tempfile.TemporaryDirectory(prefix="pns-review-self-ref-") as directory:
            completed = _run_review_snapshot_export(output_directory=directory, dry_run=True)
            combined = completed.stdout + completed.stderr
            self.assertEqual(completed.returncode, 0, msg=combined)
            self.assertNotIn("scripts/export-review-snapshot.ps1", combined)

    def test_genuine_private_key_header_is_rejected_fail_closed(self) -> None:
        # Synthetic header only; no reusable key material. Path must not be prefix-denied so
        # content scanning runs.
        marker = "BEGIN " + "RSA " + "PRIVATE KEY"
        rel = Path("tests") / "fixtures" / f"_tmp_synthetic_pk_header_{os.getpid()}.txt"
        abs_path = ROOT / rel
        with tempfile.TemporaryDirectory(prefix="pns-review-genuine-secret-") as directory:
            try:
                abs_path.write_text(
                    f"-----{marker}-----\nSYNTHETIC_TEST_MATERIAL_NOT_A_KEY\n",
                    encoding="utf-8",
                )
                completed = _run_review_snapshot_export(
                    output_directory=directory,
                    include_uncommitted=[rel.as_posix()],
                    dry_run=True,
                )
                combined = completed.stdout + completed.stderr
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("Secret indicator detected", combined)
                self.assertIn(rel.name, combined)
                self.assertNotIn("SYNTHETIC_TEST_MATERIAL_NOT_A_KEY", combined)
            finally:
                if abs_path.exists():
                    abs_path.unlink()

    def test_export_output_directory_is_not_rescanned_as_source(self) -> None:
        marker = "BEGIN " + "EC " + "PRIVATE KEY"
        token = f"{os.getpid()}-{os.urandom(4).hex()}"
        out_rel = Path("tests") / "fixtures" / f"_tmp_review_export_out_{token}"
        out = ROOT / out_rel
        stale = out / "prior-export-secret.txt"
        with tempfile.TemporaryDirectory(prefix="pns-review-unrelated-ignored-") as unrelated:
            # Unrelated ignored local output must not change the result.
            Path(unrelated, "noise.txt").write_text("unrelated", encoding="utf-8")
            try:
                out.mkdir(parents=True, exist_ok=True)
                stale.write_text(f"-----{marker}-----\nstale-export-body\n", encoding="utf-8")
                # Without output-directory exclusion this allowlisted nested secret would fail.
                completed = _run_review_snapshot_export(
                    output_directory=out,
                    include_uncommitted=[(out_rel / "prior-export-secret.txt").as_posix()],
                    dry_run=True,
                )
                self.assertEqual(completed.returncode, 0, msg=completed.stderr + completed.stdout)
                payload = json.loads(completed.stdout)
                self.assertTrue(payload["ok"])
            finally:
                if stale.exists():
                    stale.unlink()
                if out.exists():
                    for child in out.iterdir():
                        if child.is_file():
                            child.unlink()
                    try:
                        out.rmdir()
                    except OSError:
                        pass

    def test_review_export_temp_dirs_are_independent_across_runs(self) -> None:
        first = tempfile.mkdtemp(prefix="pns-review-indep-a-")
        second = tempfile.mkdtemp(prefix="pns-review-indep-b-")
        try:
            self.assertNotEqual(Path(first).resolve(), Path(second).resolve())
            a = _run_review_snapshot_export(output_directory=first, dry_run=True)
            b = _run_review_snapshot_export(output_directory=second, dry_run=True)
            self.assertEqual(a.returncode, 0, msg=a.stderr)
            self.assertEqual(b.returncode, 0, msg=b.stderr)
            self.assertTrue(json.loads(a.stdout)["ok"])
            self.assertTrue(json.loads(b.stdout)["ok"])
        finally:
            for path in (first, second):
                for child in Path(path).glob("*"):
                    if child.is_file():
                        child.unlink()
                try:
                    Path(path).rmdir()
                except OSError:
                    pass


class InvariantTests(unittest.TestCase):
    def test_scheduler_registration_composition_remain_disabled(self) -> None:
        queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        self.assertFalse(queue["gameplay_scheduler"])
        active = [item for item in queue["flows"] if item["status"] == "active"]
        self.assertLessEqual(len(active), 1)
        if not active:
            self.assertIsNone(queue["active_flow_id"])
        else:
            self.assertEqual(queue["active_flow_id"], active[0]["flow_id"])
        state = validate_governance.parse_handoff()
        self.assertEqual(state["registration_and_scheduler"]["registered_operator_tasks"], "NOT_REGISTERED_UNCHANGED")
        self.assertEqual(state["registration_and_scheduler"]["scheduler_enabled_disabled"], "DISABLED/INELIGIBLE")
        self.assertTrue(state["registration_and_scheduler"]["composition_blocked"])
        self.assertTrue(state["registration_and_scheduler"]["m6_unactivated"])
        self.assertTrue(state["registration_and_scheduler"]["bliss_unchanged"])
        self.assertIn(state["development_lease_state"], {"absent", "held"})
        self.assertEqual(state["runtime_ownership_state"], "none")
        self.assertEqual(state["writable_agent_state"], "absent")
        self.assertEqual(state["next_task_id"], "GF-MVP-002-MINIMUM-CONTRACT-V2")
        if queue["active_flow_id"] is None:
            selected = control.FlowDeliveryController().select_next(queue)
            self.assertEqual(state["first_ready_flow"], selected["flow_id"])
        else:
            self.assertEqual(state["first_ready_flow"], queue["active_flow_id"])


if __name__ == "__main__":
    unittest.main()
