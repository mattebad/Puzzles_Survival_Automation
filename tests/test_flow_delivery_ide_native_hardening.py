from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import inspect
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import flow_delivery_control as control
from scripts import pnsctl
from scripts import validate_flow_delivery_model_probe as routing


ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "tasks" / "flow_delivery_queue.json"
POLICY = ROOT / "tasks" / "flow_delivery_product_policy.json"
HOOK_PATH = ROOT / ".cursor" / "hooks" / "pns_flow_subagent_guard.py"
HOOK_SPEC = importlib.util.spec_from_file_location("pns_flow_subagent_guard_test", HOOK_PATH)
assert HOOK_SPEC and HOOK_SPEC.loader
HOOK = importlib.util.module_from_spec(HOOK_SPEC)
HOOK_SPEC.loader.exec_module(HOOK)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class NativeDelegationContractTests(unittest.TestCase):
    def test_no_cursor_cli_launch_behavior_remains(self) -> None:
        python_paths = (
            ROOT / "scripts" / "validate_flow_delivery_model_probe.py",
            ROOT / "scripts" / "flow_delivery_control.py",
            ROOT / ".cursor" / "hooks" / "pns_flow_subagent_guard.py",
        )
        forbidden = (
            "_agent_command",
            "cursor-agent.ps1",
            'shutil.which("agent")',
            '"stream-json"',
            '"--trust"',
            '"--model"',
            "Cursor Agent routing probe",
        )
        for path in python_paths:
            source = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, source, f"{path} retains {token}")
        validator = python_paths[0].read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", validator)
        self.assertNotIn("subprocess.", validator)

    def test_skill_requires_visible_serial_foreground_native_calls(self) -> None:
        skill = (
            ROOT / ".cursor" / "skills" / "pns-flow-delivery" / "SKILL.md"
        ).read_text(encoding="utf-8")
        for required in (
            "Cursor IDE native `Subagent`/`Task` tool",
            "`is_background: false`",
            "serial",
            "visible in this parent conversation",
            "terminal before the parent continues",
            "IDE_NATIVE_SUBAGENT_TOOL_UNAVAILABLE",
            "Do not perform delegated reconnaissance",
            "Do not substitute a built-in subagent",
            "record-subagent-invocation",
            "A missing optional subagentStart audit event does not authorize another execution surface.",
            "It only disables the additional resolved-identity cross-check.",
            "`preToolUse(Task)` is the fail-closed authorization gate",
            "`subagentStart` is audit-only",
        ):
            self.assertIn(required, skill)
        self.assertNotRegex(skill, r"/pns-[a-z-]+")
        self.assertIn("Never use `/multitask`", skill)

    def test_all_custom_agents_are_foreground_and_non_nested(self) -> None:
        for path in (ROOT / ".cursor" / "agents").glob("pns-*.md"):
            text = path.read_text(encoding="utf-8")
            self.assertIn("is_background: false", text)
            self.assertIn("foreground Cursor IDE native custom-subagent invocation", text)
            self.assertIn("invoke another subagent", text)

    def test_checked_in_command_is_ide_native_only(self) -> None:
        command = (
            ROOT / ".cursor" / "commands" / "pns-flow-delivery-loop.md"
        ).read_text(encoding="utf-8")
        self.assertTrue(command.startswith("IDE-NATIVE EXECUTION ONLY."))
        self.assertIn("native Subagent/Task tool in this conversation", command)
        self.assertIn("IDE_NATIVE_SUBAGENT_TOOL_UNAVAILABLE", command)
        self.assertIn("record-subagent-invocation", command)
        self.assertIn(
            "A missing optional subagentStart audit event does not authorize another execution surface.",
            command,
        )
        self.assertIn("`preToolUse(Task)` is the fail-closed authorization gate", command)
        self.assertIn("subagentStart` is", command)
        self.assertIn("audit-only", command)


class PassiveRoutingValidatorTests(unittest.TestCase):
    def make_state(
        self,
        root: Path,
        *,
        event_time: datetime,
        receipt_flow: str = control.CANARY_FLOW_ID,
        receipt_stage: str = "reconnaissance",
        receipt_session: str = "session-current",
        receipt_parent: str = "parent-current",
    ) -> tuple[Path, Path]:
        acquired = event_time - timedelta(seconds=1)
        lease = {
            "workflow": "pns-flow-delivery",
            "owner": "parent-owner",
            "process_or_session_identity": "session-current",
            "bound_parent_conversation_id": "parent-current",
            "acquisition_timestamp": iso(acquired),
            "expected_repository_head": "a" * 40,
            "active_flow": control.CANARY_FLOW_ID,
            "active_stage": "reconnaissance",
        }
        event = {
            "schema_version": 2,
            "timestamp": iso(event_time),
            "lease_acquisition_timestamp": iso(acquired),
            "lease_owner": "parent-owner",
            "lease_session": "session-current",
            "parent_conversation_id": "parent-current",
            "active_flow": control.CANARY_FLOW_ID,
            "active_stage": "reconnaissance",
            "subagent_type": "pns-flow-recon",
            "subagent_id": "native-recon-1",
            "subagent_model": "cursor-grok-4.5-high",
        }
        receipt: dict[str, object] = {
            "schema_version": 1,
            "active_flow": receipt_flow,
            "active_stage": receipt_stage,
            "lease_owner": "parent-owner",
            "lease_session": receipt_session,
            "parent_conversation_id": receipt_parent,
            "custom_agent": "pns-flow-recon",
            "requested_model": "cursor-grok-4.5-high",
            "subagent_id": "native-recon-1",
            "is_background": False,
            "terminal_outcome": "completed",
            "timestamp": iso(event_time),
            "repository_head": "a" * 40,
            "hook_cross_check": {
                "required": False,
                "status": "matched",
                "source": "optional_subagent_start_hook",
                "event_digest": control._canonical_digest(event),
            },
        }
        receipt["receipt_digest"] = control._canonical_digest(receipt)
        lease["subagent_invocation_receipts"] = [receipt]
        lease_path = root / "lease.json"
        events_path = root / "events.jsonl"
        lease_path.write_text(json.dumps(lease) + "\n", encoding="utf-8")
        events_path.write_text(json.dumps(event) + "\n", encoding="utf-8")
        return lease_path, events_path

    def test_valid_receipt_binds_current_lease_session_flow_stage_and_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lease, events = self.make_state(Path(directory), event_time=datetime.now(timezone.utc))
            result = routing.validate_event(
                expected_agent="pns-flow-recon",
                expected_stage="reconnaissance",
                lease_session_id="session-current",
                lease_path=lease,
                events_path=events,
            )
        self.assertEqual(result["subagent_id"], "native-recon-1")
        self.assertEqual(result["resolved_model"], "cursor-grok-4.5-high")
        self.assertEqual(result["source"], "cursor_ide_native_task_receipt")
        self.assertEqual(result["hook_cross_check"]["status"], "matched")

    def test_stale_cross_session_flow_and_stage_events_are_rejected(self) -> None:
        cases = (
            {"receipt_session": "other", "message": "lease_session"},
            {"receipt_parent": "other", "message": "parent_conversation_id"},
            {"receipt_flow": "OTHER-FLOW", "message": "active_flow"},
            {"receipt_stage": "implementation", "message": "active_stage"},
        )
        for case in cases:
            with self.subTest(case=case):
                with tempfile.TemporaryDirectory() as directory:
                    arguments = {key: value for key, value in case.items() if key != "message"}
                    lease, events = self.make_state(
                        Path(directory),
                        event_time=datetime.now(timezone.utc),
                        **arguments,
                    )
                    with self.assertRaisesRegex(
                        routing.RoutingValidationError,
                        case["message"],
                    ):
                        routing.validate_event(
                            expected_agent="pns-flow-recon",
                            expected_stage="reconnaissance",
                            lease_session_id="session-current",
                            lease_path=lease,
                            events_path=events,
                        )

    def test_receipt_predating_current_lease_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lease, events = self.make_state(root, event_time=datetime.now(timezone.utc))
            payload = json.loads(lease.read_text(encoding="utf-8"))
            payload["acquisition_timestamp"] = iso(datetime.now(timezone.utc) + timedelta(seconds=5))
            lease.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(routing.RoutingValidationError, "no native invocation receipt"):
                routing.validate_event(
                    expected_agent="pns-flow-recon",
                    expected_stage="reconnaissance",
                    lease_session_id="session-current",
                    lease_path=lease,
                    events_path=events,
                )

    def test_missing_optional_hook_event_is_supported_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lease, events = self.make_state(root, event_time=datetime.now(timezone.utc))
            payload = json.loads(lease.read_text(encoding="utf-8"))
            receipt = payload["subagent_invocation_receipts"][0]
            receipt["hook_cross_check"] = {
                "required": False,
                "status": "not_emitted",
                "source": "optional_subagent_start_hook",
            }
            unsigned = dict(receipt)
            unsigned.pop("receipt_digest")
            receipt["receipt_digest"] = control._canonical_digest(unsigned)
            lease.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            events.unlink()
            result = routing.validate_event(
                expected_agent="pns-flow-recon",
                expected_stage="reconnaissance",
                lease_session_id="session-current",
                lease_path=lease,
                events_path=events,
            )
        self.assertEqual(result["hook_cross_check"]["status"], "not_emitted")


class HookHardeningTests(unittest.TestCase):
    def local_paths(self, root: Path) -> dict[str, Path]:
        local = root / ".local-orchestrator"
        local.mkdir()
        return {
            "LOCAL_ROOT": local,
            "LEASE": local / "flow-delivery-lease.json",
            "WRITABLE_MARKER": local / "writable-subagent.json",
            "ROUTING_EVENTS": local / "model-routing-events.jsonl",
            "AUTHORIZATION_EVENTS": local / "task-authorization-events.jsonl",
            "STATE_LOCK": local / "subagent-guard.lock",
        }

    def write_lease(self, path: Path, *, stage: str, bound_parent: str | None = None) -> None:
        path.write_text(
            json.dumps(
                {
                    "workflow": "pns-flow-delivery",
                    "owner": "owner",
                    "process_or_session_identity": "session",
                    "bound_parent_conversation_id": bound_parent,
                    "acquisition_timestamp": iso(datetime.now(timezone.utc) - timedelta(seconds=1)),
                    "active_flow": "FLOW",
                    "active_stage": stage,
                    "runtime_ownership_state": "none",
                    "unresolved_action_state": "clear",
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def test_hook_root_is_derived_from_file_not_working_directory(self) -> None:
        source = HOOK_PATH.read_text(encoding="utf-8")
        self.assertIn("ROOT = Path(__file__).resolve().parents[2]", source)
        self.assertNotIn("Path.cwd()", source)

    def test_hook_event_is_current_lease_bound_and_parent_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.local_paths(Path(directory))
            self.write_lease(paths["LEASE"], stage="reconnaissance")
            payload = {
                "hook_event_name": "subagentStart",
                "conversation_id": "parent-current",
                "subagent_id": "native-1",
                "subagent_type": "pns-flow-recon",
                "subagent_model": "cursor-grok-4.5-high",
            }
            with patch.multiple(HOOK, **paths):
                with HOOK.state_lock():
                    result = HOOK._handle_subagent_start_audit(payload)
                event = json.loads(paths["ROUTING_EVENTS"].read_text(encoding="utf-8"))
                lease = json.loads(paths["LEASE"].read_text(encoding="utf-8"))
                with HOOK.state_lock():
                    with self.assertRaisesRegex(HOOK.GuardError, "another parent"):
                        HOOK._bind_parent(lease, "other")
        self.assertEqual(result["permission"], "allow")
        self.assertTrue(event["audit_only"])
        self.assertEqual(lease["bound_parent_conversation_id"], "parent-current")
        self.assertEqual(event["lease_owner"], "owner")
        self.assertEqual(event["lease_session"], "session")
        self.assertEqual(event["active_flow"], "FLOW")
        self.assertEqual(event["active_stage"], "reconnaissance")

    def test_hook_does_not_invent_model_or_parent_fields_when_payload_omits_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.local_paths(Path(directory))
            self.write_lease(paths["LEASE"], stage="reconnaissance")
            payload = {
                "hook_event_name": "subagentStart",
                "subagent_id": "native-optional-fields",
                "subagent_type": "pns-flow-recon",
            }
            with patch.multiple(HOOK, **paths):
                with HOOK.state_lock():
                    result = HOOK._handle_subagent_start_audit(payload)
                event = json.loads(paths["ROUTING_EVENTS"].read_text(encoding="utf-8"))
                lease = json.loads(paths["LEASE"].read_text(encoding="utf-8"))
        self.assertEqual(result["permission"], "allow")
        self.assertTrue(event["audit_only"])
        self.assertIsNone(event["subagent_model"])
        self.assertIsNone(event["parent_conversation_id"])
        self.assertIsNone(lease["bound_parent_conversation_id"])

    def test_stale_writable_marker_fails_closed_and_reconciliation_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.local_paths(Path(directory))
            self.write_lease(paths["LEASE"], stage="implementation", bound_parent="parent")
            payload = {
                "parent_conversation_id": "parent",
                "subagent_id": "writer-1",
                "subagent_type": "pns-flow-implementer",
                "subagent_model": "cursor-grok-4.5-high",
            }
            # Seed a matching preToolUse authorization so the audit path can acquire the marker.
            auth = {
                "authorization_verdict": "allow",
                "requested_agent": "pns-flow-implementer",
                "requested_model": "cursor-grok-4.5-high",
                "lease_session": "session",
                "active_flow": "FLOW",
                "active_stage": "implementation",
                "parent_conversation_id": "parent",
                "event_digest": "seed",
            }
            paths["AUTHORIZATION_EVENTS"] = paths["LOCAL_ROOT"] / "task-authorization-events.jsonl"
            paths["AUTHORIZATION_EVENTS"].write_text(json.dumps(auth) + "\n", encoding="utf-8")
            with patch.multiple(HOOK, **paths):
                with HOOK.state_lock():
                    HOOK._handle_subagent_start_audit(payload)
                marker = json.loads(paths["WRITABLE_MARKER"].read_text(encoding="utf-8"))
                marker["created_at"] = "2000-01-01T00:00:00Z"
                paths["WRITABLE_MARKER"].write_text(json.dumps(marker) + "\n", encoding="utf-8")
                with HOOK.state_lock():
                    with self.assertRaisesRegex(HOOK.GuardError, "marker remains"):
                        HOOK._acquire_writable_marker(
                            json.loads(paths["LEASE"].read_text(encoding="utf-8")),
                            {**payload, "subagent_id": "writer-2"},
                            "parent",
                        )
                with self.assertRaisesRegex(HOOK.GuardError, "not terminal"):
                    HOOK.reconcile_writable_marker(
                        owner="owner",
                        session_id="session",
                        terminal_state="blocked",
                    )
                paths["LEASE"].unlink()
                result = HOOK.reconcile_writable_marker(
                    owner="owner",
                    session_id="session",
                    terminal_state="blocked",
                )
        self.assertTrue(result["reconciled"])
        self.assertEqual(result["reason"], "no_delivery_lease")


class ControllerHardeningTests(unittest.TestCase):
    HEAD = "a" * 40
    FINGERPRINT = "f" * 64

    def make_controller(self, root: Path) -> control.FlowDeliveryController:
        queue = root / "queue.json"
        policy = root / "policy.json"
        queue.write_bytes(QUEUE.read_bytes())
        policy.write_bytes(POLICY.read_bytes())
        controller = control.FlowDeliveryController(
            queue,
            policy,
            root / "lease.json",
            root / "writable-subagent.json",
            root / "events.jsonl",
        )
        controller._repo_head = Mock(return_value=self.HEAD)
        controller._working_tree_state = Mock(return_value=({}, self.FINGERPRINT))
        return controller

    def acquire(self, controller: control.FlowDeliveryController, **overrides: str) -> None:
        arguments = {
            "owner": "parent",
            "session_identity": "session",
            "runtime_ownership_state": "none",
            "unresolved_action_state": "clear",
        }
        arguments.update(overrides)
        controller.acquire(**arguments)

    def set_active(
        self,
        controller: control.FlowDeliveryController,
        *,
        stage: str,
        runtime: str = "held",
    ) -> str:
        self.acquire(controller)
        queue = json.loads(controller.queue_path.read_text(encoding="utf-8"))
        # Real queue may already have an active flow; demote so fixtures stay singular.
        for item in queue["flows"]:
            if item["status"] == "active":
                item["status"] = "ready"
                item["last_completed_stage"] = "selected"
        flow = queue["flows"][0]
        flow["status"] = "active"
        flow["last_completed_stage"] = stage
        flow["live_attempt_count"] = 0
        flow["live_attempts"] = []
        flow["blocked_reason"] = ""
        queue["active_flow_id"] = flow["flow_id"]
        controller.queue_path.write_text(json.dumps(queue) + "\n", encoding="utf-8")
        lease = json.loads(controller.lease_path.read_text(encoding="utf-8"))
        lease["active_flow"] = flow["flow_id"]
        lease["active_stage"] = stage
        lease["runtime_ownership_state"] = runtime
        controller.lease_path.write_text(json.dumps(lease) + "\n", encoding="utf-8")
        return flow["flow_id"]

    def set_fixture_live_attempt_budget(
        self,
        controller: control.FlowDeliveryController,
        maximum: int = 3,
    ) -> None:
        """Give only the isolated controller fixture a budget for budget-behavior tests."""

        queue = json.loads(controller.queue_path.read_text(encoding="utf-8"))
        flow = next(item for item in queue["flows"] if item["status"] == "active")
        flow["maximum_live_attempts"] = maximum
        controller.queue_path.write_text(json.dumps(queue) + "\n", encoding="utf-8")

    def record_invocation(
        self,
        controller: control.FlowDeliveryController,
        *,
        stage: str,
        agent: str | None = None,
        **overrides: object,
    ) -> dict[str, object]:
        lease = json.loads(controller.lease_path.read_text(encoding="utf-8"))
        arguments: dict[str, object] = {
            "owner": "parent",
            "active_flow": lease["active_flow"],
            "active_stage": stage,
            "lease_session": "session",
            "parent_conversation_id": "parent-conversation",
            "custom_agent": agent or control.STAGE_AGENTS[stage],
            "requested_model": control.EXPECTED_SUBAGENT_MODEL,
            "subagent_id": f"native-{stage}",
            "is_background": False,
            "terminal_outcome": "completed",
            "timestamp": control.utc_now(),
            "repository_head": self.HEAD,
        }
        arguments.update(overrides)
        return controller.record_subagent_invocation(**arguments)

    def test_runtime_unknown_or_held_unresolved_action_and_writer_block_activation(self) -> None:
        for runtime, unresolved, marker in (
            ("held", "clear", False),
            ("unknown", "clear", False),
            ("none", "unresolved", False),
            ("none", "unknown", False),
            ("none", "clear", True),
        ):
            with self.subTest(runtime=runtime, unresolved=unresolved, marker=marker):
                with tempfile.TemporaryDirectory() as directory:
                    controller = self.make_controller(Path(directory))
                    self.acquire(
                        controller,
                        runtime_ownership_state=runtime,
                        unresolved_action_state=unresolved,
                    )
                    if marker:
                        controller.writable_marker_path.write_text("{}\n", encoding="utf-8")
                    with self.assertRaises(control.FlowDeliveryError):
                        controller.activate(owner="parent")

    def test_native_task_receipt_accepts_expected_agent_model_and_missing_hook(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory))
            self.set_active(controller, stage="reconnaissance", runtime="none")
            receipt = self.record_invocation(controller, stage="reconnaissance")
            lease = json.loads(controller.lease_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["custom_agent"], "pns-flow-recon")
        self.assertEqual(receipt["requested_model"], "cursor-grok-4.5-high")
        self.assertFalse(receipt["is_background"])
        self.assertEqual(receipt["terminal_outcome"], "completed")
        self.assertEqual(receipt["hook_cross_check"]["status"], "not_emitted")
        self.assertEqual(lease["bound_parent_conversation_id"], "parent-conversation")

    def test_wrong_model_builtin_agent_background_stage_session_parent_and_head_fail(self) -> None:
        cases = (
            (
                {"requested_model": "gpt-5.6-sol-high"},
                "did not request Grok",
            ),
            (
                {"agent": "generalPurpose"},
                "allowed custom agent",
            ),
            (
                {"is_background": True},
                "must be foreground",
            ),
            (
                {"active_stage": "implementation", "agent": "pns-flow-implementer"},
                "another stage",
            ),
            (
                {"active_flow": "OTHER-FLOW"},
                "another flow",
            ),
            (
                {"lease_session": "other-session"},
                "another lease session",
            ),
            (
                {"parent_conversation_id": "other-parent", "bind_parent": True},
                "another parent conversation",
            ),
            (
                {"repository_head": "b" * 40},
                "another HEAD",
            ),
            (
                {"terminal_outcome": "running"},
                "not terminal",
            ),
        )
        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                with tempfile.TemporaryDirectory() as directory:
                    controller = self.make_controller(Path(directory))
                    self.set_active(controller, stage="reconnaissance", runtime="none")
                    arguments = dict(overrides)
                    bind_parent = arguments.pop("bind_parent", False)
                    if bind_parent:
                        lease = json.loads(controller.lease_path.read_text(encoding="utf-8"))
                        lease["bound_parent_conversation_id"] = "parent-conversation"
                        controller.lease_path.write_text(
                            json.dumps(lease) + "\n",
                            encoding="utf-8",
                        )
                    with self.assertRaisesRegex(control.FlowDeliveryError, message):
                        self.record_invocation(
                            controller,
                            stage="reconnaissance",
                            **arguments,
                        )

    def test_stale_and_duplicate_native_receipts_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory))
            self.set_active(controller, stage="reconnaissance", runtime="none")
            with self.assertRaisesRegex(control.FlowDeliveryError, "outside the active stage"):
                self.record_invocation(
                    controller,
                    stage="reconnaissance",
                    timestamp="2000-01-01T00:00:00Z",
                )
            self.record_invocation(controller, stage="reconnaissance")
            with self.assertRaisesRegex(control.FlowDeliveryError, "duplicate"):
                self.record_invocation(controller, stage="reconnaissance")

    def test_stage_advancement_requires_completed_current_stage_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory))
            self.set_active(controller, stage="reconnaissance", runtime="none")
            with self.assertRaisesRegex(control.FlowDeliveryError, "native subagent invocation"):
                controller.record_stage(owner="parent", stage="implementation")
            self.record_invocation(controller, stage="reconnaissance")
            result = controller.record_stage(owner="parent", stage="implementation")
        self.assertEqual(result["last_completed_stage"], "implementation")

    def test_current_hook_event_is_cross_checked_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory))
            self.set_active(controller, stage="reconnaissance", runtime="none")
            lease = json.loads(controller.lease_path.read_text(encoding="utf-8"))
            event = {
                "schema_version": 2,
                "timestamp": control.utc_now(),
                "lease_acquisition_timestamp": lease["acquisition_timestamp"],
                "lease_owner": "parent",
                "lease_session": "session",
                "parent_conversation_id": "parent-conversation",
                "active_flow": lease["active_flow"],
                "active_stage": "reconnaissance",
                "subagent_id": "native-reconnaissance",
                "subagent_type": "pns-flow-recon",
                "subagent_model": "cursor-grok-4.5-high",
            }
            controller.routing_events_path.write_text(
                json.dumps(event) + "\n",
                encoding="utf-8",
            )
            receipt = self.record_invocation(controller, stage="reconnaissance")
        self.assertEqual(receipt["hook_cross_check"]["status"], "matched")
        self.assertEqual(
            receipt["hook_cross_check"]["event_digest"],
            control._canonical_digest(event),
        )

    def test_live_attempts_persist_budget_and_require_retry_diagnosis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory))
            self.set_active(controller, stage="live_execution")
            self.set_fixture_live_attempt_budget(controller)
            first = controller.begin_live_attempt(owner="parent")
            self.assertEqual(first["ordinal"], 1)
            controller.finish_live_attempt(
                owner="parent",
                outcome="failed",
                diagnosis="target moved after recapture",
            )
            with self.assertRaisesRegex(control.FlowDeliveryError, "concrete diagnosis"):
                controller.begin_live_attempt(owner="parent")
            second = controller.begin_live_attempt(
                owner="parent",
                diagnosis="correct route-specific target binding",
            )
            self.assertEqual(second["ordinal"], 2)
            controller.finish_live_attempt(owner="parent", outcome="completed")
            controller.begin_live_attempt(
                owner="parent",
                diagnosis="materially different terminal verification",
            )
            controller.finish_live_attempt(owner="parent", outcome="completed")
            with self.assertRaisesRegex(control.FlowDeliveryError, "exhausted"):
                controller.begin_live_attempt(owner="parent", diagnosis="fourth")
            queue = json.loads(controller.queue_path.read_text(encoding="utf-8"))
        self.assertEqual(queue["flows"][0]["live_attempt_count"], 3)
        self.assertEqual(len(queue["flows"][0]["live_attempts"]), 3)

    def test_entering_live_execution_does_not_consume_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory))
            self.set_active(controller, stage="live_execution")
            queue = json.loads(controller.queue_path.read_text(encoding="utf-8"))
        self.assertEqual(queue["flows"][0]["live_attempt_count"], 0)

    def test_blocked_nonterminal_live_work_prevents_next_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory))
            self.set_active(controller, stage="live_execution")
            self.set_fixture_live_attempt_budget(controller)
            controller.begin_live_attempt(owner="parent")
            controller.block(owner="parent", reason="ambiguous post-transport state")
            self.assertIsNone(controller.select_next())
            with self.assertRaises(control.FlowDeliveryError):
                controller.activate(owner="parent")

    def test_acquisition_head_is_immutable_and_unexpected_drift_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory))
            self.acquire(controller)
            controller._repo_head.return_value = "b" * 40
            with self.assertRaisesRegex(control.FlowDeliveryError, "unexpected repository HEAD"):
                controller.heartbeat(owner="parent")
            lease = json.loads(controller.lease_path.read_text(encoding="utf-8"))
        self.assertEqual(lease["acquired_repository_head"], self.HEAD)
        self.assertEqual(lease["expected_repository_head"], self.HEAD)

    def make_receipt(
        self,
        controller: control.FlowDeliveryController,
        *,
        profile: str,
        stage: str,
        flow_id: str,
        head: str | None = None,
    ) -> dict[str, object]:
        receipt: dict[str, object] = {
            "schema_version": 1,
            "active_flow": flow_id,
            "repository_head": head or self.HEAD,
            "working_tree_fingerprint": self.FINGERPRINT,
            "delivery_stage": stage,
            "validation_profile": profile,
            "command_or_profile": f"checked-in:{profile}",
            "exit_code": 0,
            "timestamp": control.utc_now(),
            "test_count": 5,
            "artifact_paths": ["test-results.json"],
        }
        receipt["receipt_digest"] = control._canonical_digest(receipt)
        return receipt

    def test_validation_receipts_bind_flow_head_stage_and_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self.make_controller(root)
            flow_id = self.set_active(
                controller,
                stage="implementation_review",
                runtime="none",
            )
            bad = self.make_receipt(
                controller,
                profile="focused_tests",
                stage="focused_validation",
                flow_id="OTHER",
            )
            bad_path = root / "bad.json"
            bad_path.write_text(json.dumps(bad) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(control.FlowDeliveryError, "another flow"):
                controller.record_validation_receipt(owner="parent", receipt_path=bad_path)
            for profile in ("focused_tests", "architecture_tests"):
                receipt = self.make_receipt(
                    controller,
                    profile=profile,
                    stage="focused_validation",
                    flow_id=flow_id,
                )
                path = root / f"{profile}.json"
                path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
                controller.record_validation_receipt(owner="parent", receipt_path=path)
            self.record_invocation(controller, stage="implementation_review")
            controller.record_stage(owner="parent", stage="focused_validation")
            queue = json.loads(controller.queue_path.read_text(encoding="utf-8"))
        self.assertEqual(queue["flows"][0]["last_completed_stage"], "focused_validation")

    def _prepare_full_validation(
        self,
        controller: control.FlowDeliveryController,
        *,
        policy_status: str,
    ) -> str:
        flow_id = self.set_active(controller, stage="focused_validation", runtime="none")
        queue = json.loads(controller.queue_path.read_text(encoding="utf-8"))
        queue["flows"][0]["product_policy_status"] = policy_status
        controller.queue_path.write_text(json.dumps(queue) + "\n", encoding="utf-8")
        return flow_id

    def _record_receipt(
        self,
        controller: control.FlowDeliveryController,
        root: Path,
        *,
        profile: str,
        flow_id: str,
    ) -> None:
        receipt = self.make_receipt(
            controller,
            profile=profile,
            stage="full_validation",
            flow_id=flow_id,
        )
        path = root / f"{profile}.json"
        path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
        controller.record_validation_receipt(owner="parent", receipt_path=path)

    def test_navigation_only_flow_validates_through_shared_navigation_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self.make_controller(root)
            flow_id = self._prepare_full_validation(
                controller, policy_status="navigation_only_validation"
            )
            self._record_receipt(
                controller, root, profile="shared_navigation", flow_id=flow_id
            )
            result = controller.record_stage(owner="parent", stage="full_validation")
        self.assertEqual(result["last_completed_stage"], "full_validation")

    def test_consequential_flow_still_requires_full_suite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self.make_controller(root)
            flow_id = self._prepare_full_validation(
                controller, policy_status="supervised_consequential_validation"
            )
            self._record_receipt(
                controller, root, profile="shared_navigation", flow_id=flow_id
            )
            with self.assertRaisesRegex(
                control.FlowDeliveryError, "lacks bound validation receipts"
            ):
                controller.record_stage(owner="parent", stage="full_validation")
            self._record_receipt(
                controller, root, profile="full_suite", flow_id=flow_id
            )
            result = controller.record_stage(owner="parent", stage="full_validation")
        self.assertEqual(result["last_completed_stage"], "full_validation")

    def test_navigation_only_overhead_empty_before_live(self) -> None:
        for stage in control.STAGES:
            self.assertEqual(
                control.required_overhead_for("navigation_only", stage),
                set(),
                msg=stage,
            )

    def test_consequential_overhead_keeps_context_before_subagent_stages(self) -> None:
        expected = {"context_packet", "dependency_section_digests"}
        for stage in (
            "reconnaissance",
            "implementation",
            "implementation_review",
            "correction",
            "evidence_review",
        ):
            self.assertEqual(
                control.required_overhead_for("consequential", stage),
                expected,
                msg=stage,
            )
        self.assertEqual(
            control.required_overhead_for("consequential", "focused_validation"),
            set(),
        )
        self.assertEqual(
            control.required_overhead_for("consequential", "full_validation"),
            set(),
        )
        self.assertEqual(
            control.required_overhead_for("consequential", "live_preflight"),
            set(),
        )
        self.assertEqual(
            control.required_overhead_for("consequential", "live_execution"),
            set(),
        )
        self.assertEqual(
            control.required_overhead_for("consequential", "commit"),
            set(),
        )

    def test_overhead_maps_use_known_kinds(self) -> None:
        for stage, kinds in control.NAVIGATION_ONLY_OVERHEAD_BY_STAGE.items():
            self.assertTrue(
                set(kinds).issubset(control.OVERHEAD_KINDS),
                msg=stage,
            )
        for stage, kinds in control.CONSEQUENTIAL_OVERHEAD_BY_STAGE.items():
            self.assertTrue(
                set(kinds).issubset(control.OVERHEAD_KINDS),
                msg=stage,
            )

    def test_required_overhead_unknown_stage_defaults_empty(self) -> None:
        self.assertEqual(control.required_overhead_for("navigation_only", "not-a-stage"), set())
        self.assertEqual(control.required_overhead_for("consequential", "not-a-stage"), set())

    def test_controller_does_not_import_context_builder(self) -> None:
        source = Path(control.__file__).read_text(encoding="utf-8")
        self.assertNotIn("build_context_packet", source)
        self.assertNotIn("validate_context_packet", source)
        self.assertNotIn("flow_delivery_context", source)

    def test_arbitrary_commit_fails_and_bound_reachable_commit_completes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory))
            self.set_active(controller, stage="commit", runtime="released")
            with self.assertRaisesRegex(control.FlowDeliveryError, "real Git commit"):
                controller.complete(owner="parent", commit="not-a-commit")
            valid = "b" * 40
            lease = json.loads(controller.lease_path.read_text(encoding="utf-8"))
            lease["reviewed_flow_commit"] = valid
            lease["expected_repository_head"] = valid
            lease["observed_repository_head"] = valid
            controller.lease_path.write_text(json.dumps(lease) + "\n", encoding="utf-8")
            controller._repo_head.return_value = valid
            controller._resolve_commit = Mock(return_value=valid)
            controller._commit_reachable = Mock(return_value=True)
            completed = controller.complete(owner="parent", commit=valid)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["last_commit"], valid)


class BlueStacksRegistryHardeningTests(unittest.TestCase):
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
        state = (
            {"active_flow_id": "FLOW"},
            {"owner": "owner"},
        )
        outputs = [
            "device\n",
            bytes(png),
            (
                "mCurrentFocus=Window{1 u0 com.android.launcher/.Launcher}\n"
                "recent com.global.ztmslg/.MainActivity\n"
            ),
        ]
        with patch("scripts.pnsctl._load_flow_delivery_state", return_value=state), patch(
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
        ), patch("scripts.pnsctl._load_bluestacks_flow_registry", return_value={}):
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

    def test_generic_recovery_no_longer_assumes_cultivation_center(self) -> None:
        source = inspect.getsource(pnsctl.bluestacks_recover_home)
        self.assertNotIn("cultivation-center", source)
        self.assertNotIn("expected-title", source)
        self.assertNotIn("subprocess", source)

    def test_registry_is_checked_in_and_has_no_placeholder_flow(self) -> None:
        registry = json.loads(
            (ROOT / "tasks" / "flow_delivery_bluestacks_registry.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(registry["registry_kind"], "flow_delivery_bluestacks")
        flows = registry["flows"]
        self.assertIn("CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION", flows)
        campaign = flows["CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION"]
        self.assertEqual(campaign["consequence_class"], "navigation_only")
        self.assertEqual(campaign["runner"], "campaign_navigation_only_runner")
        self.assertIn("ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION", flows)
        ultimate = flows["ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION"]
        self.assertEqual(ultimate["consequence_class"], "navigation_only")
        self.assertEqual(
            set(flows)
            - {
                "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION",
                "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION",
            },
            set(),
        )


class PreToolUseTaskAuthorizationTests(unittest.TestCase):
    FIXTURE = json.loads(
        (
            ROOT / "tests" / "fixtures" / "pretooluse_task_routing_contract.json"
        ).read_text(encoding="utf-8")
    )

    def local_paths(self, root: Path) -> dict[str, Path]:
        local = root / ".local-orchestrator"
        local.mkdir()
        return {
            "LOCAL_ROOT": local,
            "LEASE": local / "flow-delivery-lease.json",
            "WRITABLE_MARKER": local / "writable-subagent.json",
            "ROUTING_EVENTS": local / "model-routing-events.jsonl",
            "AUTHORIZATION_EVENTS": local / "task-authorization-events.jsonl",
            "STATE_LOCK": local / "subagent-guard.lock",
            "AUDIT_ONLY_FLAG": local / "hook-canary" / "AUDIT_ONLY",
            "CAPTURED_PAYLOAD_PATH": local / "hook-canary" / "latest-pretooluse-task-payload.json",
            "HOOK_CANARY_DIR": local / "hook-canary",
        }

    def write_lease(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "workflow": "pns-flow-delivery",
                    "owner": "owner",
                    "process_or_session_identity": "session",
                    "bound_parent_conversation_id": "parent-fixture-1",
                    "acquisition_timestamp": iso(datetime.now(timezone.utc) - timedelta(seconds=1)),
                    "active_flow": "FLOW",
                    "active_stage": "reconnaissance",
                    "runtime_ownership_state": "none",
                    "unresolved_action_state": "clear",
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def test_non_task_tool_is_unaffected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.local_paths(Path(directory))
            self.write_lease(paths["LEASE"])
            with patch.multiple(HOOK, **paths):
                result = HOOK._handle_pretooluse(self.FIXTURE["non_task_example"])
        self.assertEqual(result["permission"], "allow")

    def test_decision_matrix_from_fixture(self) -> None:
        cases = (
            ("allow_example", "allow"),
            ("sol_model", "deny"),
            ("explore_builtin", "deny"),
            ("general_purpose", "deny"),
            ("missing_model", "deny"),
            ("missing_agent", "deny"),
            ("conflicting_model", "deny"),
        )
        for key, expected in cases:
            with self.subTest(key=key):
                with tempfile.TemporaryDirectory() as directory:
                    paths = self.local_paths(Path(directory))
                    self.write_lease(paths["LEASE"])
                    payload = (
                        self.FIXTURE[key]
                        if key == "allow_example"
                        else self.FIXTURE["deny_examples"][key]
                    )
                    with patch.multiple(HOOK, **paths):
                        lease = json.loads(paths["LEASE"].read_text(encoding="utf-8"))
                        result = HOOK.authorize_task_call(payload, lease=lease)
                self.assertEqual(result["permission"], expected)
                if expected == "deny":
                    self.assertEqual(
                        result["authorization"]["authorization_verdict"],
                        "deny",
                    )

    def test_unknown_agent_and_malformed_json_and_missing_policy_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.local_paths(Path(directory))
            self.write_lease(paths["LEASE"])
            unknown = deepcopy(self.FIXTURE["allow_example"])
            unknown["tool_input"]["subagent_type"] = "pns-unknown-agent"
            with patch.multiple(HOOK, **paths):
                lease = json.loads(paths["LEASE"].read_text(encoding="utf-8"))
                denied = HOOK.authorize_task_call(unknown, lease=lease)
                self.assertEqual(denied["permission"], "deny")
                with patch.object(
                    HOOK.routing_policy,
                    "load_subagent_routing_policy",
                    side_effect=HOOK.routing_policy.RoutingPolicyError("missing"),
                ):
                    with self.assertRaises(HOOK.GuardError):
                        HOOK._load_policy()

    def test_duplicate_authorization_event_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.local_paths(Path(directory))
            self.write_lease(paths["LEASE"])
            payload = self.FIXTURE["allow_example"]
            with patch.multiple(HOOK, **paths):
                lease = json.loads(paths["LEASE"].read_text(encoding="utf-8"))
                first = HOOK.authorize_task_call(payload, lease=lease)
                second = HOOK.authorize_task_call(payload, lease=lease)
            lines = [
                line
                for line in paths["AUTHORIZATION_EVENTS"].read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        self.assertEqual(first["permission"], "allow")
        self.assertEqual(second["permission"], "allow")
        self.assertTrue(second["authorization"].get("duplicate_replay"))
        self.assertEqual(len(lines), 1)

    def test_subagent_start_is_audit_only_and_mismatch_marks_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.local_paths(Path(directory))
            self.write_lease(paths["LEASE"])
            allow = self.FIXTURE["allow_example"]
            with patch.multiple(HOOK, **paths):
                lease = json.loads(paths["LEASE"].read_text(encoding="utf-8"))
                HOOK.authorize_task_call(allow, lease=lease)
                matched = HOOK._handle_subagent_start_audit(
                    self.FIXTURE["subagent_start_audit_example"]
                )
                mismatched = HOOK._handle_subagent_start_audit(
                    {
                        **self.FIXTURE["subagent_start_audit_example"],
                        "subagent_model": "cursor-gpt-5.6-sol-high",
                        "subagent_id": "native-mismatch",
                    }
                )
                events = [
                    json.loads(line)
                    for line in paths["ROUTING_EVENTS"].read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
        self.assertEqual(matched["permission"], "allow")
        self.assertEqual(mismatched["permission"], "allow")
        self.assertTrue(events[0]["audit_only"])
        self.assertTrue(events[0]["requested_versus_resolved_match"])
        self.assertFalse(events[1]["requested_versus_resolved_match"])

    def test_no_cursor_cli_fallback_tokens_remain(self) -> None:
        for path in (
            ROOT / "scripts" / "flow_delivery_control.py",
            ROOT / "scripts" / "flow_delivery_routing_policy.py",
            ROOT / ".cursor" / "hooks" / "pns_flow_subagent_guard.py",
        ):
            text = path.read_text(encoding="utf-8")
            for token in ("stream-json", "--trust", "Cursor Agent routing probe"):
                self.assertNotIn(token, text, path)
            self.assertNotIn("_agent_command", text, path)
            self.assertNotIn("cursor-agent.ps1", text, path)

    def test_orchestrator_docs_require_explicit_agent_and_model(self) -> None:
        command = (
            ROOT / ".cursor" / "commands" / "pns-flow-delivery-loop.md"
        ).read_text(encoding="utf-8")
        skill = (
            ROOT / ".cursor" / "skills" / "pns-flow-delivery" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("cursor-grok-4.5-high", command)
        self.assertIn("cursor-grok-4.5-high", skill)
        self.assertIn("pns-flow-recon", skill)
        self.assertIn("checked-in stage-to-agent mapping", command)
        self.assertIn('or "choose the best agent"', skill)
        self.assertIn("Never use generic language", skill)

if __name__ == "__main__":
    unittest.main()
