from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import flow_delivery_control as control
from scripts import flow_delivery_parent_progress as progress


ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "tasks" / "flow_delivery_queue.json"
POLICY_PATH = ROOT / "tasks" / "flow_delivery_product_policy.json"
LOOP_POLICY_PATH = ROOT / "tasks" / "flow_delivery_loop_policy.json"
COMMAND_PATH = ROOT / ".cursor" / "commands" / "pns-flow-delivery-loop.md"
SKILL_PATH = ROOT / ".cursor" / "skills" / "pns-flow-delivery" / "SKILL.md"
CAMPAIGN = "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION"
ULTIMATE = "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION"
NOVA = "NOVA-PRAISE-HOME-ATLAS-MIGRATION"


class LoopPolicyTests(unittest.TestCase):
    def test_policy_schema_default_and_zero_unbounded(self) -> None:
        payload = json.loads(LOOP_POLICY_PATH.read_text(encoding="utf-8"))
        progress.validate_loop_policy(payload)
        self.assertEqual(payload["max_completed_flows_per_parent_conversation"], 2)
        unbounded = {
            "schema_version": 1,
            "registry_kind": "flow_delivery_loop_policy",
            "max_completed_flows_per_parent_conversation": 0,
        }
        progress.validate_loop_policy(unbounded)
        entry = progress.empty_parent_entry(
            parent_conversation_id="p",
            configured_maximum=0,
            policy_digest=progress.loop_policy_digest(unbounded),
        )
        progress.append_counted_completion(entry, flow_id="a", commit="c" * 40)
        progress.append_counted_completion(entry, flow_id="b", commit="d" * 40)
        progress.append_counted_completion(entry, flow_id="c", commit="e" * 40)
        self.assertFalse(entry["rollover_required"])

    def test_negative_and_malformed_policy_fail(self) -> None:
        with self.assertRaises(progress.ParentProgressError):
            progress.validate_loop_policy(
                {
                    "schema_version": 1,
                    "registry_kind": "flow_delivery_loop_policy",
                    "max_completed_flows_per_parent_conversation": -1,
                }
            )
        with self.assertRaises(progress.ParentProgressError):
            progress.validate_loop_policy({"schema_version": 1})
        with self.assertRaises(progress.ParentProgressError):
            progress.validate_loop_policy(
                {
                    "schema_version": 1,
                    "registry_kind": "flow_delivery_loop_policy",
                    "max_completed_flows_per_parent_conversation": 2,
                    "extra": True,
                }
            )

    def test_command_and_skill_are_not_numeric_authorities(self) -> None:
        command = COMMAND_PATH.read_text(encoding="utf-8")
        skill = SKILL_PATH.read_text(encoding="utf-8")
        progress.assert_texts_do_not_hardcode_maximum(
            {"command": command, "skill": skill},
            maximum=2,
        )
        self.assertIn("flow_delivery_loop_policy.json", command)
        self.assertIn("flow_delivery_loop_policy.json", skill)
        self.assertIn(control.PARENT_CONVERSATION_ROLLOVER_REQUIRED, command)
        self.assertIn(control.PARENT_CONVERSATION_ROLLOVER_REQUIRED, skill)
        self.assertIn(control.RESUME_INVOCATION.splitlines()[0], command)


class ParentConversationRolloverControllerTests(unittest.TestCase):
    def make_controller(self, directory: str) -> control.FlowDeliveryController:
        root = Path(directory)
        queue = root / "queue.json"
        policy = root / "policy.json"
        loop_policy = root / "loop_policy.json"
        payload = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        for flow in payload["flows"]:
            if flow["flow_id"] in {CAMPAIGN, ULTIMATE, NOVA}:
                flow["status"] = "ready"
                flow["last_completed_stage"] = None
                flow["blocked_reason"] = ""
                flow["live_attempt_count"] = 0
                flow["live_attempts"] = []
            elif flow["status"] == "active":
                flow["status"] = "ready"
                flow["last_completed_stage"] = None
                flow["blocked_reason"] = ""
        payload["active_flow_id"] = None
        queue.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        policy.write_bytes(POLICY_PATH.read_bytes())
        loop_policy.write_bytes(LOOP_POLICY_PATH.read_bytes())
        return control.FlowDeliveryController(
            queue,
            policy,
            root / "lease.json",
            root / "writable-subagent.json",
            root / "routing.jsonl",
            loop_policy,
            root / "parent-conversation-progress.json",
        )

    def mark_completed(
        self,
        controller: control.FlowDeliveryController,
        flow_id: str,
        commit: str,
    ) -> None:
        queue = json.loads(controller.queue_path.read_text(encoding="utf-8"))
        for flow in queue["flows"]:
            if flow["flow_id"] == flow_id:
                flow["status"] = "completed"
                flow["last_completed_stage"] = "completed"
                flow["last_commit"] = commit
                flow["blocked_reason"] = ""
        queue["active_flow_id"] = None
        controller.queue_path.write_text(
            json.dumps(queue, indent=2) + "\n",
            encoding="utf-8",
        )

    def record(
        self,
        controller: control.FlowDeliveryController,
        *,
        parent: str,
        flow_id: str,
        commit: str,
        receipts=None,
        transition_changed_validated_authority: bool = False,
    ):
        with patch.object(controller, "_repo_head", return_value=commit), patch.object(
            controller, "_resolve_commit", side_effect=lambda value: value
        ), patch.object(controller, "_commit_reachable", return_value=True), patch.object(
            controller, "_working_tree_state", return_value=({}, "fingerprint")
        ):
            return controller.record_counted_gameplay_completion(
                parent_conversation_id=parent,
                flow_id=flow_id,
                counted_commit=commit,
                full_suite_receipts=receipts,
                transition_changed_validated_authority=transition_changed_validated_authority,
            )

    def test_new_parent_starts_at_zero_and_identities_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(directory)
            self.assertEqual(
                controller.parent_progress_entry("parent-a")["completed_gameplay_flow_count"],
                0,
            )
            self.assertEqual(
                controller.parent_progress_entry("parent-b")["completed_gameplay_flow_count"],
                0,
            )
            self.mark_completed(controller, CAMPAIGN, "a" * 40)
            self.record(controller, parent="parent-a", flow_id=CAMPAIGN, commit="a" * 40)
            with patch.object(controller, "_repo_head", return_value="a" * 40), patch.object(
                controller, "_working_tree_state", return_value=({}, "fp")
            ):
                controller.acquire(
                    owner="owner",
                    session_identity="session",
                    runtime_ownership_state="none",
                    unresolved_action_state="clear",
                    parent_conversation_id="parent-a",
                )
                controller.release(owner="owner")
            self.assertEqual(
                controller.parent_progress_entry("parent-a")["completed_gameplay_flow_count"],
                1,
            )
            self.assertEqual(
                controller.parent_progress_entry("parent-b")["completed_gameplay_flow_count"],
                0,
            )
            document = controller.load_parent_progress()
            document["parents"]["stale-parent"] = progress.empty_parent_entry(
                parent_conversation_id="stale-parent",
                configured_maximum=2,
                policy_digest=progress.loop_policy_digest(controller.load_loop_policy()),
            )
            progress.save_progress(controller.progress_path, document)
            selected = controller.select_next(parent_conversation_id="parent-b")
            self.assertEqual(selected["flow_id"], ULTIMATE)
            self.mark_completed(controller, ULTIMATE, "b" * 40)
            with patch.object(controller, "_repo_head", return_value="b" * 40), patch.object(
                controller, "_working_tree_state", return_value=({}, "fp")
            ):
                controller.acquire(
                    owner="owner",
                    session_identity="session",
                    runtime_ownership_state="none",
                    unresolved_action_state="clear",
                    parent_conversation_id="parent-a",
                )
            with self.assertRaisesRegex(control.FlowDeliveryError, "wrong parent identity"):
                self.record(controller, parent="parent-b", flow_id=ULTIMATE, commit="b" * 40)

    def test_counting_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(directory)
            self.mark_completed(controller, CAMPAIGN, "1" * 40)
            first = self.record(controller, parent="parent", flow_id=CAMPAIGN, commit="1" * 40)
            self.assertEqual(first["entry"]["completed_gameplay_flow_count"], 1)
            self.mark_completed(controller, ULTIMATE, "2" * 40)
            second = self.record(controller, parent="parent", flow_id=ULTIMATE, commit="2" * 40)
            self.assertEqual(second["entry"]["completed_gameplay_flow_count"], 2)
            with self.assertRaisesRegex(control.FlowDeliveryError, "duplicate counted"):
                self.record(controller, parent="parent", flow_id=ULTIMATE, commit="2" * 40)
            queue = json.loads(controller.queue_path.read_text(encoding="utf-8"))
            for flow in queue["flows"]:
                if flow["flow_id"] == NOVA:
                    flow["status"] = "blocked"
                    flow["blocked_reason"] = "test"
                    flow["last_completed_stage"] = "blocked"
            controller.queue_path.write_text(json.dumps(queue, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(control.FlowDeliveryError, "blocked flow"):
                self.record(controller, parent="parent", flow_id=NOVA, commit="3" * 40)
            queue = json.loads(controller.queue_path.read_text(encoding="utf-8"))
            for flow in queue["flows"]:
                if flow["flow_id"] == NOVA:
                    flow["status"] = "needs_product_decision"
                    flow["product_policy_status"] = "unresolved_user_decision"
                    flow["blocked_reason"] = "decision"
            controller.queue_path.write_text(json.dumps(queue, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(control.FlowDeliveryError, "needs_product_decision"):
                self.record(controller, parent="parent", flow_id=NOVA, commit="3" * 40)
            with self.assertRaisesRegex(control.FlowDeliveryError, "maintenance-task"):
                self.record(
                    controller,
                    parent="parent",
                    flow_id="FLOW-DELIVERY-PARENT-CONVERSATION-ROLLOVER",
                    commit="3" * 40,
                )
            with self.assertRaisesRegex(control.FlowDeliveryError, "unreachable|current HEAD"):
                with patch.object(controller, "_repo_head", return_value="9" * 40), patch.object(
                    controller, "_resolve_commit", side_effect=lambda value: value
                ), patch.object(controller, "_commit_reachable", return_value=False), patch.object(
                    controller, "_working_tree_state", return_value=({}, "fingerprint")
                ):
                    controller.record_counted_gameplay_completion(
                        parent_conversation_id="parent",
                        flow_id=CAMPAIGN,
                        counted_commit="8" * 40,
                    )

    def test_non_counted_transitions_do_not_increment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(directory)
            self.assertEqual(
                controller.parent_progress_entry("parent")["completed_gameplay_flow_count"],
                0,
            )
            with patch.object(controller, "_repo_head", return_value="c" * 40), patch.object(
                controller, "_working_tree_state", return_value=({}, "fp")
            ):
                controller.acquire(
                    owner="owner",
                    session_identity="session",
                    runtime_ownership_state="none",
                    unresolved_action_state="clear",
                    parent_conversation_id="parent",
                )
                controller.activate(owner="owner", parent_conversation_id="parent")
                controller.record_stage(owner="owner", stage="reconnaissance")
            self.assertEqual(
                controller.parent_progress_entry("parent")["completed_gameplay_flow_count"],
                0,
            )
            queue = json.loads(controller.queue_path.read_text(encoding="utf-8"))
            self.assertEqual(queue["active_flow_id"], CAMPAIGN)
            queue["flows"][0]["next_concrete_action"] = "queue-only note"
            controller.queue_path.write_text(json.dumps(queue, indent=2) + "\n", encoding="utf-8")
            self.assertEqual(
                controller.parent_progress_entry("parent")["completed_gameplay_flow_count"],
                0,
            )

    def test_rollover_enforcement_and_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(directory)
            self.mark_completed(controller, CAMPAIGN, "1" * 40)
            self.record(controller, parent="parent", flow_id=CAMPAIGN, commit="1" * 40)
            selected = controller.select_next(parent_conversation_id="parent")
            self.assertEqual(selected["flow_id"], ULTIMATE)
            self.mark_completed(controller, ULTIMATE, "2" * 40)
            result = self.record(controller, parent="parent", flow_id=ULTIMATE, commit="2" * 40)
            self.assertEqual(result["stop_reason"], control.PARENT_CONVERSATION_ROLLOVER_REQUIRED)
            self.assertEqual(result["resume_invocation"], control.RESUME_INVOCATION)
            with self.assertRaisesRegex(
                control.FlowDeliveryError,
                control.PARENT_CONVERSATION_ROLLOVER_REQUIRED,
            ):
                controller.select_next(parent_conversation_id="parent")
            queue = json.loads(controller.queue_path.read_text(encoding="utf-8"))
            by_id = {flow["flow_id"]: flow for flow in queue["flows"]}
            self.assertEqual(by_id[CAMPAIGN]["status"], "completed")
            self.assertEqual(by_id[ULTIMATE]["status"], "completed")
            self.assertEqual(by_id[NOVA]["status"], "ready")
            with patch.object(controller, "_repo_head", return_value="2" * 40), patch.object(
                controller,
                "_git",
                side_effect=lambda args, check=True: type(
                    "R",
                    (),
                    {
                        "returncode": 0,
                        "stdout": (
                            "main\n"
                            if args[:2] == ["rev-parse", "--abbrev-ref"]
                            else "0\t25\n"
                            if "rev-list" in args
                            else "2" * 40 + "\n"
                        ),
                    },
                )(),
            ), patch.object(controller, "_commit_reachable", return_value=True), patch.object(
                controller, "_working_tree_state", return_value=({}, "fingerprint")
            ):
                report = controller.emit_rollover_required(parent_conversation_id="parent")
            self.assertEqual(report["stop_reason"], control.PARENT_CONVERSATION_ROLLOVER_REQUIRED)
            self.assertEqual(report["resume_invocation"], control.RESUME_INVOCATION)
            self.assertEqual(report["completed_count"], 2)
            fresh = controller.parent_progress_entry("fresh-parent")
            self.assertEqual(fresh["completed_gameplay_flow_count"], 0)
            selected_fresh = controller.select_next(parent_conversation_id="fresh-parent")
            self.assertEqual(selected_fresh["flow_id"], NOVA)

    def test_safe_boundary_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(directory)
            self.mark_completed(controller, CAMPAIGN, "1" * 40)
            self.record(controller, parent="parent", flow_id=CAMPAIGN, commit="1" * 40)
            self.mark_completed(controller, ULTIMATE, "2" * 40)
            self.record(controller, parent="parent", flow_id=ULTIMATE, commit="2" * 40)

            queue = json.loads(controller.queue_path.read_text(encoding="utf-8"))
            queue["flows"][2]["status"] = "active"
            queue["flows"][2]["last_completed_stage"] = "implementation"
            queue["active_flow_id"] = NOVA
            controller.queue_path.write_text(json.dumps(queue, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(control.FlowDeliveryError, "active_flow"):
                with patch.object(controller, "_commit_reachable", return_value=True), patch.object(
                    controller, "_working_tree_state", return_value=({}, "fp")
                ):
                    controller.assert_safe_rollover_boundary(parent_conversation_id="parent")

            queue["active_flow_id"] = None
            queue["flows"][2]["status"] = "ready"
            queue["flows"][2]["last_completed_stage"] = None
            controller.queue_path.write_text(json.dumps(queue, indent=2) + "\n", encoding="utf-8")

            now = control.utc_now()
            lease_payload = {
                "schema_version": 2,
                "workflow": "pns-flow-delivery",
                "lease_mode": "delivery",
                "owner": "owner",
                "host": "host",
                "process_or_session_identity": "session",
                "bound_parent_conversation_id": "parent",
                "acquisition_timestamp": now,
                "heartbeat_timestamp": now,
                "acquired_repository_head": "2" * 40,
                "expected_repository_head": "2" * 40,
                "observed_repository_head": "2" * 40,
                "acquired_working_tree_fingerprint": "fp",
                "expected_working_tree_fingerprint": "fp",
                "acquired_working_tree_snapshot": {},
                "expected_working_tree_snapshot": {},
                "reviewed_attributable_paths": [],
                "active_flow": "",
                "active_stage": "completed",
                "active_stage_entered_at": now,
                "runtime_ownership_state": "held",
                "unresolved_action_state": "clear",
                "live_terminal_evidence": False,
                "safety_blocked_flow": "",
                "validation_receipts": [],
                "subagent_invocation_receipts": [],
                "reviewed_flow_commit": None,
                "gates": {"implementation_parent_reviewed": False},
            }
            control.validate_lease(lease_payload)
            control._atomic_write_json(controller.lease_path, lease_payload)
            with self.assertRaisesRegex(
                control.FlowDeliveryError,
                "runtime_ownership|development_lease",
            ):
                with patch.object(controller, "_commit_reachable", return_value=True), patch.object(
                    controller, "_working_tree_state", return_value=({}, "fp")
                ):
                    controller.assert_safe_rollover_boundary(parent_conversation_id="parent")

            lease = controller.lease()
            assert lease is not None
            lease["runtime_ownership_state"] = "none"
            lease["active_stage"] = "implementation"
            lease["active_flow"] = ""
            control._atomic_write_json(controller.lease_path, lease)
            with self.assertRaisesRegex(
                control.FlowDeliveryError,
                "active_delivery_stage|development_lease",
            ):
                with patch.object(controller, "_commit_reachable", return_value=True), patch.object(
                    controller, "_working_tree_state", return_value=({}, "fp")
                ):
                    controller.assert_safe_rollover_boundary(parent_conversation_id="parent")

            controller.lease_path.unlink()
            controller.writable_marker_path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(control.FlowDeliveryError, "writable_agent_marker"):
                with patch.object(controller, "_commit_reachable", return_value=True), patch.object(
                    controller, "_working_tree_state", return_value=({}, "fp")
                ):
                    controller.assert_safe_rollover_boundary(parent_conversation_id="parent")
            controller.writable_marker_path.unlink()

            with self.assertRaisesRegex(control.FlowDeliveryError, "attributable_uncommitted"):
                with patch.object(controller, "_commit_reachable", return_value=True), patch.object(
                    controller,
                    "_working_tree_state",
                    return_value=(
                        {"scripts/flow_delivery_control.py": {"status": " M"}},
                        "fp",
                    ),
                ):
                    controller.assert_safe_rollover_boundary(parent_conversation_id="parent")

    def test_full_suite_receipt_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(directory)
            head = "f" * 40
            fingerprint = "fingerprint"
            good = {
                "schema_version": 1,
                "active_flow": CAMPAIGN,
                "repository_head": head,
                "working_tree_fingerprint": fingerprint,
                "delivery_stage": "full_validation",
                "validation_profile": "full_suite",
                "command_or_profile": "full",
                "exit_code": 0,
                "timestamp": "2026-07-20T00:00:00Z",
                "test_count": 980,
                "artifact_paths": [],
                "receipt_digest": "digest",
            }
            reuse = controller.evaluate_full_suite_receipt_for_rollover(
                flow_id=CAMPAIGN,
                repository_head=head,
                working_tree_fingerprint=fingerprint,
                receipts=[good],
            )
            self.assertTrue(reuse["reuse"])
            self.assertEqual(reuse["receipt_digest"], "digest")
            stale = deepcopy(good)
            stale["repository_head"] = "0" * 40
            rejected = controller.evaluate_full_suite_receipt_for_rollover(
                flow_id=CAMPAIGN,
                repository_head=head,
                working_tree_fingerprint=fingerprint,
                receipts=[stale],
            )
            self.assertFalse(rejected["reuse"])
            pre_transition = controller.evaluate_full_suite_receipt_for_rollover(
                flow_id=CAMPAIGN,
                repository_head=head,
                working_tree_fingerprint=fingerprint,
                receipts=[good],
                transition_changed_validated_authority=True,
            )
            self.assertFalse(pre_transition["reuse"])
            self.assertEqual(
                pre_transition["reason"],
                "queue_transition_changed_validated_authority",
            )
            self.mark_completed(controller, CAMPAIGN, head)
            recorded = self.record(
                controller,
                parent="parent",
                flow_id=CAMPAIGN,
                commit=head,
                receipts=[good],
            )
            self.assertFalse(recorded["full_suite"]["required"])
            self.assertFalse(recorded["full_suite"]["reuse"])
            self.assertEqual(recorded["full_suite"]["reason"], "full_suite_manual_only")
            self.assertIsNone(
                recorded["entry"]["counted_completions"][0]["full_suite_receipt_digest"]
            )


if __name__ == "__main__":
    unittest.main()
