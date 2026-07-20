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
            "A missing optional hook event does not authorize another execution surface.",
            "It only disables the additional hook cross-check.",
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
            "A missing optional hook event does not authorize another execution surface.",
            command,
        )


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
                    result = HOOK._handle_start(payload)
                event = json.loads(paths["ROUTING_EVENTS"].read_text(encoding="utf-8"))
                lease = json.loads(paths["LEASE"].read_text(encoding="utf-8"))
                with HOOK.state_lock():
                    with self.assertRaisesRegex(HOOK.GuardError, "another parent"):
                        HOOK._handle_start({**payload, "conversation_id": "other"})
        self.assertEqual(result["permission"], "allow")
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
                    result = HOOK._handle_start(payload)
                event = json.loads(paths["ROUTING_EVENTS"].read_text(encoding="utf-8"))
                lease = json.loads(paths["LEASE"].read_text(encoding="utf-8"))
        self.assertEqual(result["permission"], "allow")
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
            with patch.multiple(HOOK, **paths):
                with HOOK.state_lock():
                    HOOK._handle_start(payload)
                marker = json.loads(paths["WRITABLE_MARKER"].read_text(encoding="utf-8"))
                marker["created_at"] = "2000-01-01T00:00:00Z"
                paths["WRITABLE_MARKER"].write_text(json.dumps(marker) + "\n", encoding="utf-8")
                with HOOK.state_lock():
                    with self.assertRaisesRegex(HOOK.GuardError, "marker remains"):
                        HOOK._handle_start({**payload, "subagent_id": "writer-2"})
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
        flow = queue["flows"][0]
        flow["status"] = "active"
        flow["last_completed_stage"] = stage
        queue["active_flow_id"] = flow["flow_id"]
        controller.queue_path.write_text(json.dumps(queue) + "\n", encoding="utf-8")
        lease = json.loads(controller.lease_path.read_text(encoding="utf-8"))
        lease["active_flow"] = flow["flow_id"]
        lease["active_stage"] = stage
        lease["runtime_ownership_state"] = runtime
        controller.lease_path.write_text(json.dumps(lease) + "\n", encoding="utf-8")
        return flow["flow_id"]

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
        self.assertEqual(registry["flows"], {})


if __name__ == "__main__":
    unittest.main()
