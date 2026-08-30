from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import flow_delivery_control as control
from scripts import pnsctl


ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "tasks" / "flow_delivery_queue.json"
POLICY = ROOT / "tasks" / "flow_delivery_product_policy.json"


class LeanWorkflowTests(unittest.TestCase):
    HEAD = "a" * 40

    def make_controller(self, root: Path) -> control.FlowDeliveryController:
        queue = root / "queue.json"
        policy = root / "policy.json"
        payload = json.loads(QUEUE.read_text(encoding="utf-8"))
        # Isolate from any mid-flight live queue state copied into the fixture.
        payload["active_flow_id"] = None
        for flow in payload["flows"]:
            if flow.get("status") == "active":
                flow["status"] = "ready"
                flow["last_completed_stage"] = None
                flow["blocked_reason"] = ""
        if not any(flow.get("status") == "ready" for flow in payload["flows"]):
            fixture_flow = next(
                flow
                for flow in payload["flows"]
                if flow["flow_id"] == "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION"
            )
            fixture_flow["status"] = "ready"
            fixture_flow["last_completed_stage"] = None
            fixture_flow["last_commit"] = None
            fixture_flow["blocked_reason"] = ""
            fixture_flow["live_attempt_count"] = 0
            fixture_flow["live_attempts"] = []
        queue.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        policy.write_bytes(POLICY.read_bytes())
        controller = control.FlowDeliveryController(
            queue,
            policy,
            root / "lease.json",
            root / "writer.json",
        )
        controller._repo_head = Mock(return_value=self.HEAD)
        return controller

    def activate(self, controller: control.FlowDeliveryController) -> str:
        controller.acquire(
            owner="parent",
            session_identity="session",
            runtime_ownership_state="none",
            unresolved_action_state="clear",
        )
        flow = controller.activate(owner="parent")
        return str(flow["flow_id"])

    def set_live_execution(self, controller: control.FlowDeliveryController) -> str:
        flow_id = self.activate(controller)
        queue = json.loads(controller.queue_path.read_text(encoding="utf-8"))
        flow = next(item for item in queue["flows"] if item["flow_id"] == flow_id)
        flow["last_completed_stage"] = "live_execution"
        flow["requires_bluestacks_live"] = True
        flow["maximum_live_attempts"] = 3
        flow["live_attempt_count"] = 0
        flow["live_attempts"] = []
        flow["product_policy_status"] = "navigation_only_validation"
        flow["evidence_validator"] = "checked-in verifier"
        controller.queue_path.write_text(json.dumps(queue) + "\n", encoding="utf-8")
        lease = json.loads(controller.lease_path.read_text(encoding="utf-8"))
        lease["active_stage"] = "live_execution"
        lease["runtime_ownership_state"] = "held"
        controller.lease_path.write_text(json.dumps(lease) + "\n", encoding="utf-8")
        return flow_id

    def test_parent_can_skip_agent_ceremony(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self.make_controller(root)
            self.activate(controller)
            result = controller.record_stage(
                owner="parent",
                stage="implementation",
            )

            self.assertEqual(result["last_completed_stage"], "implementation")

    def test_optional_delegation_reserves_and_releases_single_writer_lane(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory))
            self.activate(controller)
            marker = controller.begin_delegation(
                owner="parent",
                delegation_id="slice-1",
            )
            self.assertEqual(marker["agent"], "pns-flow-implementer")
            with self.assertRaisesRegex(control.FlowDeliveryError, "already active"):
                controller.begin_delegation(owner="parent", delegation_id="slice-2")
            with self.assertRaisesRegex(control.FlowDeliveryError, "cannot overlap"):
                controller.record_stage(owner="parent", stage="implementation")
            with self.assertRaisesRegex(control.FlowDeliveryError, "delegated writer"):
                controller.review_worktree(owner="parent", paths=["scripts/example.py"])
            with self.assertRaisesRegex(control.FlowDeliveryError, "delegated writer"):
                controller.block(owner="parent", reason="must not race child writes")
            released = controller.end_delegation(
                owner="parent",
                delegation_id="slice-1",
                outcome="completed",
            )
            self.assertTrue(released["released"])
            result = controller.record_stage(owner="parent", stage="implementation")
            self.assertEqual(result["last_completed_stage"], "implementation")

    def test_writer_lane_blocks_activation_live_attempt_release_and_reconcile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self.make_controller(root)
            flow_id = self.set_live_execution(controller)
            lease = json.loads(controller.lease_path.read_text(encoding="utf-8"))
            marker = {
                "schema_version": 1,
                "delegation_id": "slice-live",
                "agent": "pns-flow-implementer",
                "lease_owner": "parent",
                "lease_session": "session",
                "active_flow": flow_id,
                "active_stage": "live_execution",
                "parent_conversation_id": None,
                "started_at": control.utc_now(),
            }
            control._atomic_write_json(controller.writable_marker_path, marker)
            with self.assertRaisesRegex(control.FlowDeliveryError, "cannot overlap"):
                controller.begin_live_attempt(owner="parent")

            lease["runtime_ownership_state"] = "none"
            lease["active_flow"] = ""
            lease["active_stage"] = "completed"
            controller.lease_path.write_text(json.dumps(lease) + "\n", encoding="utf-8")
            queue = json.loads(controller.queue_path.read_text(encoding="utf-8"))
            queue["active_flow_id"] = None
            for flow in queue["flows"]:
                if flow["flow_id"] == flow_id:
                    flow["status"] = "completed"
                    flow["last_completed_stage"] = "completed"
            controller.queue_path.write_text(json.dumps(queue) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(control.FlowDeliveryError, "active optional"):
                controller.release(owner="parent")
            with self.assertRaisesRegex(control.FlowDeliveryError, "active optional"):
                controller.reconcile(
                    terminal_evidence=True,
                    runtime_state="released",
                    journal_state="resolved",
                    consequential_state="terminal",
                )

    def test_corrections_are_short_parent_loop_transitions(self) -> None:
        self.assertEqual(
            control.TRANSITIONS["correction"],
            {"implementation", "implementation_review", "focused_validation", "blocked"},
        )
        self.assertEqual(
            control.required_overhead_for("consequential", "implementation"),
            set(),
        )
        self.assertEqual(
            control.required_overhead_for("consequential", "correction"),
            set(),
        )

    def test_runtime_safety_remains_independent_of_delegation(self) -> None:
        self.assertIn("live_preflight", control.TRANSITIONS["focused_validation"])
        self.assertIn("evidence_review", control.TRANSITIONS["focused_validation"])
        self.assertIn("commit", control.TRANSITIONS["focused_validation"])
        self.assertIn("live_preflight", control.TRANSITIONS["full_validation"])
        self.assertIn("live_execution", control.TRANSITIONS["live_preflight"])
        self.assertEqual(
            control.required_receipts_for("consequential", "full_validation"),
            set(),
        )
        self.assertIn("unresolved_action_state", control.REQUIRED_LEASE_FIELDS)
        self.assertIn("runtime_ownership_state", control.REQUIRED_LEASE_FIELDS)

    def test_live_preflight_can_follow_focused_validation_without_full_suite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self.make_controller(root)
            flow_id = self.set_live_execution(controller)
            queue = json.loads(controller.queue_path.read_text(encoding="utf-8"))
            flow = next(item for item in queue["flows"] if item["flow_id"] == flow_id)
            flow["last_completed_stage"] = "focused_validation"
            controller.queue_path.write_text(json.dumps(queue) + "\n", encoding="utf-8")
            lease = json.loads(controller.lease_path.read_text(encoding="utf-8"))
            lease["active_stage"] = "focused_validation"
            controller.lease_path.write_text(json.dumps(lease) + "\n", encoding="utf-8")

            result = controller.record_stage(owner="parent", stage="live_preflight")

            self.assertEqual(result["last_completed_stage"], "live_preflight")

    def test_live_attempt_budget_and_retry_diagnosis_remain_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory))
            self.set_live_execution(controller)
            first = controller.begin_live_attempt(owner="parent")
            self.assertEqual(first["ordinal"], 1)
            controller.finish_live_attempt(
                owner="parent",
                outcome="failed",
                diagnosis="target moved after recapture",
            )
            with self.assertRaisesRegex(control.FlowDeliveryError, "concrete diagnosis"):
                controller.begin_live_attempt(owner="parent")
            controller.begin_live_attempt(
                owner="parent",
                diagnosis="correct route-specific target binding",
            )
            controller.finish_live_attempt(owner="parent", outcome="completed")
            controller.begin_live_attempt(
                owner="parent",
                diagnosis="materially different terminal verification",
            )
            controller.finish_live_attempt(owner="parent", outcome="completed")
            with self.assertRaisesRegex(control.FlowDeliveryError, "exhausted"):
                controller.begin_live_attempt(owner="parent", diagnosis="fourth attempt")

    def test_activation_rejects_unsafe_runtime_unresolved_action_and_writer(self) -> None:
        cases = (
            ("held", "clear", False),
            ("unknown", "clear", False),
            ("none", "unresolved", False),
            ("none", "unknown", False),
            ("none", "clear", True),
        )
        for runtime, unresolved, writer in cases:
            with self.subTest(runtime=runtime, unresolved=unresolved, writer=writer):
                with tempfile.TemporaryDirectory() as directory:
                    controller = self.make_controller(Path(directory))
                    controller.acquire(
                        owner="parent",
                        session_identity="session",
                        runtime_ownership_state=runtime,
                        unresolved_action_state=unresolved,
                    )
                    if writer:
                        controller.writable_marker_path.write_text("{}\n", encoding="utf-8")
                    with self.assertRaises(control.FlowDeliveryError):
                        controller.activate(owner="parent")

    def test_nonterminal_live_attempt_blocks_next_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory))
            self.set_live_execution(controller)
            controller.begin_live_attempt(owner="parent")
            controller.block(owner="parent", reason="ambiguous post-transport state")
            self.assertIsNone(controller.select_next())
            with self.assertRaises(control.FlowDeliveryError):
                controller.activate(owner="parent")

    def test_acquisition_head_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory))
            controller.acquire(
                owner="parent",
                session_identity="session",
                runtime_ownership_state="none",
                unresolved_action_state="clear",
            )
            controller._repo_head.return_value = "b" * 40
            with self.assertRaisesRegex(control.FlowDeliveryError, "unexpected repository HEAD"):
                controller.heartbeat(owner="parent")

    def test_validation_receipt_stays_bound_to_flow_head_and_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self.make_controller(root)
            flow_id = self.activate(controller)
            controller.record_stage(owner="parent", stage="implementation")
            lease = json.loads(controller.lease_path.read_text(encoding="utf-8"))
            receipt = {
                "schema_version": 1,
                "active_flow": flow_id,
                "repository_head": self.HEAD,
                "working_tree_fingerprint": lease["expected_working_tree_fingerprint"],
                "delivery_stage": "focused_validation",
                "validation_profile": "focused_tests",
                "command_or_profile": "checked-in:focused",
                "exit_code": 0,
                "timestamp": control.utc_now(),
                "test_count": 5,
                "artifact_paths": ["test-results.json"],
            }
            receipt["receipt_digest"] = control._canonical_digest(receipt)
            bad = dict(receipt)
            bad["active_flow"] = "OTHER"
            unsigned = dict(bad)
            unsigned.pop("receipt_digest")
            bad["receipt_digest"] = control._canonical_digest(unsigned)
            bad_path = root / "bad.json"
            bad_path.write_text(json.dumps(bad) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(control.FlowDeliveryError, "another flow"):
                controller.record_validation_receipt(owner="parent", receipt_path=bad_path)
            good_path = root / "good.json"
            good_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
            controller.record_validation_receipt(owner="parent", receipt_path=good_path)
            architecture = dict(receipt)
            architecture["validation_profile"] = "architecture_tests"
            unsigned_architecture = dict(architecture)
            unsigned_architecture.pop("receipt_digest")
            architecture["receipt_digest"] = control._canonical_digest(unsigned_architecture)
            architecture_path = root / "architecture.json"
            architecture_path.write_text(json.dumps(architecture) + "\n", encoding="utf-8")
            controller.record_validation_receipt(owner="parent", receipt_path=architecture_path)
            result = controller.record_stage(owner="parent", stage="focused_validation")
            self.assertEqual(result["last_completed_stage"], "focused_validation")

    def test_commit_completion_requires_bound_reachable_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory))
            flow_id = self.activate(controller)
            queue = json.loads(controller.queue_path.read_text(encoding="utf-8"))
            flow = next(item for item in queue["flows"] if item["flow_id"] == flow_id)
            flow["last_completed_stage"] = "commit"
            controller.queue_path.write_text(json.dumps(queue) + "\n", encoding="utf-8")
            lease = json.loads(controller.lease_path.read_text(encoding="utf-8"))
            lease["active_stage"] = "commit"
            lease["runtime_ownership_state"] = "released"
            valid = "b" * 40
            lease["reviewed_flow_commit"] = valid
            lease["expected_repository_head"] = valid
            lease["observed_repository_head"] = valid
            controller.lease_path.write_text(json.dumps(lease) + "\n", encoding="utf-8")
            controller._repo_head.return_value = valid
            controller._resolve_commit = Mock(side_effect=lambda value: value)
            controller._commit_reachable = Mock(return_value=True)
            with self.assertRaisesRegex(control.FlowDeliveryError, "reviewed flow commit"):
                controller.complete(owner="parent", commit="c" * 40)
            completed = controller.complete(owner="parent", commit=valid)
            self.assertEqual(completed["status"], "completed")

    def test_retired_routing_artifacts_are_absent_and_runtime_is_idle(self) -> None:
        removed = (
            ROOT / ".cursor" / "hooks" / "pns_flow_subagent_guard.py",
            ROOT / ".cursor" / "rules" / "pns-flow-delivery-subagents.mdc",
            ROOT / "tasks" / "flow_delivery_subagent_routing_policy.json",
            ROOT / "scripts" / "flow_delivery_routing_policy.py",
            ROOT / "scripts" / "validate_flow_delivery_model_probe.py",
        )
        for path in removed:
            self.assertFalse(path.exists(), path)

        lease = json.loads(
            (ROOT / "CURRENT_HANDOFF.md")
            .read_text(encoding="utf-8")
            .split("<!-- CURRENT_HANDOFF_STATE_BEGIN -->", 1)[1]
            .split("<!-- CURRENT_HANDOFF_STATE_END -->", 1)[0]
            .strip()
        )
        self.assertEqual(lease["runtime_ownership_state"], "none")


class RuntimeBoundaryTests(unittest.TestCase):
    def test_focused_package_parser_uses_actual_focus_line(self) -> None:
        output = (
            "mCurrentFocus=Window{123 u0 com.global.ztmslg/.MainActivity}\n"
            "other diagnostic com.android.settings/.Settings\n"
        )
        self.assertEqual(pnsctl._focused_package(output), "com.global.ztmslg")
        misleading = (
            "mCurrentFocus=Window{123 u0 com.android.launcher/.Launcher}\n"
            "historical com.global.ztmslg/.MainActivity\n"
        )
        self.assertEqual(pnsctl._focused_package(misleading), "com.android.launcher")

    def test_preflight_rejects_game_package_only_elsewhere_in_dumpsys(self) -> None:
        png = bytearray(24)
        png[:8] = b"\x89PNG\r\n\x1a\n"
        png[16:20] = (800).to_bytes(4, "big")
        png[20:24] = (1280).to_bytes(4, "big")
        outputs = [
            "device\n",
            bytes(png),
            (
                "mCurrentFocus=Window{1 u0 com.android.launcher/.Launcher}\n"
                "recent com.global.ztmslg/.MainActivity\n"
            ),
        ]
        with patch(
            "scripts.pnsctl._load_flow_delivery_state",
            return_value=({"active_flow_id": "FLOW"}, {"owner": "owner"}),
        ), patch(
            "scripts.pnsctl._run_fixed_bluestacks_adb",
            side_effect=outputs,
        ):
            with self.assertRaisesRegex(pnsctl.OperatorError, "not the foreground"):
                pnsctl.bluestacks_preflight()

    def test_missing_runner_verifier_and_recovery_handler_fail_closed(self) -> None:
        with patch("scripts.pnsctl._load_bluestacks_flow_registry", return_value={}):
            with self.assertRaisesRegex(
                pnsctl.OperatorError,
                "FLOW_DELIVERY_RUNNER_UNAVAILABLE",
            ):
                pnsctl.bluestacks_run_flow(
                    "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION",
                    live=False,
                )
        queue = {"active_flow_id": "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION"}
        with patch(
            "scripts.pnsctl._load_flow_delivery_state",
            return_value=(queue, {"active_stage": "evidence_review"}),
        ), patch(
            "scripts.pnsctl._retained_flow_result",
            return_value=(
                Path(".local-captures/fixture-session"),
                {"flow_id": queue["active_flow_id"]},
            ),
        ), patch(
            "scripts.pnsctl._verify_flow_structure",
            return_value={"result": {"flow_id": queue["active_flow_id"]}},
        ), patch(
            "scripts.pnsctl._load_bluestacks_flow_registry",
            return_value={},
        ):
            with self.assertRaisesRegex(
                pnsctl.OperatorError,
                "FLOW_EVIDENCE_VALIDATOR_UNAVAILABLE",
            ):
                pnsctl.bluestacks_verify_flow(Path(".local-captures/missing"))
        with patch(
            "scripts.pnsctl._load_flow_delivery_state",
            return_value=(queue, {"active_stage": "live_execution"}),
        ), patch("scripts.pnsctl._load_bluestacks_flow_registry", return_value={}):
            with self.assertRaisesRegex(
                pnsctl.OperatorError,
                "FLOW_RECOVERY_HANDLER_UNAVAILABLE",
            ):
                pnsctl.bluestacks_recover_home()


if __name__ == "__main__":
    unittest.main()
