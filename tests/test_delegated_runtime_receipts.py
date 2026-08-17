from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from scripts import flow_delivery_control as control
from scripts import navigation_development_boundary as boundary
from scripts import pnsctl
from scripts.bluestacks_native_runtime import CapturedNativeFrame, LocalBlueStacksRuntime


def _frame(name: str) -> CapturedNativeFrame:
    payload = name.encode("utf-8")
    return CapturedNativeFrame(
        np.zeros((1280, 800, 3), dtype=np.uint8),
        payload,
        hashlib.sha256(payload).hexdigest(),
        time.monotonic(),
        Path(f"{name}.png"),
    )


class ReceiptTests(unittest.TestCase):
    def _controller(self, root: Path) -> control.DelegatedRuntimeReceiptController:
        controller = control.DelegatedRuntimeReceiptController(root / "receipts.sqlite3")
        controller._candidate = lambda: ("head", "fingerprint")  # type: ignore[method-assign]
        return controller

    def _issue(
        self,
        controller: control.DelegatedRuntimeReceiptController,
        *,
        receipt_class: str = "canary",
        command: list[str] | None = None,
        total: int = 2,
        identities: list[str] | None = None,
        classes: list[str] | None = None,
        terminals: list[str] | None = None,
        gates: bool = True,
        resource_budget: int = 0,
        combat_budget: int = 0,
        action_bindings: list[dict] | None = None,
        consequence_class: str = "navigation_only",
    ) -> dict:
        return controller.issue(
            task_id="TASK-1",
            flow_id="FLOW-1",
            receipt_class=receipt_class,
            agent_identity="luna-1",
            command_argv=command or ["development-session", "delegated-dry-run"],
            scenario="scenario-a",
            variant="variant-a",
            permitted_action_identities=identities or ["target-a"],
            permitted_action_classes=classes or ["navigation"],
            consequence_class=consequence_class,
            max_total_inputs=total,
            max_resource_affecting_inputs=resource_budget,
            max_combat_confirmations=combat_budget,
            permitted_terminal_states=terminals or ["dry_run", "evidence_required"],
            result_identity="result-a",
            action_bindings=action_bindings,
            implementation_self_check_evidence="self-check" if gates else "",
            independent_read_only_tester_evidence="tester" if gates else "",
            parent_integration_acceptance="accepted" if gates else "",
        )

    def _consume(self, controller, receipt, **overrides):
        values = {
            "receipt_id": receipt["receipt_id"],
            "agent_identity": receipt["agent_identity"],
            "task_id": receipt["task_id"],
            "flow_id": receipt["flow_id"],
            "receipt_class": receipt["receipt_class"],
            "command_argv": receipt["command_argv"],
            "scenario": receipt["scenario"],
            "variant": receipt["variant"],
        }
        values.update(overrides)
        return controller.consume(**values)

    def _git_controller(self, root: Path):
        (root / "tracked.txt").write_text("one\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
        env = {
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        }
        subprocess.run(
            ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-qm", "candidate"],
            cwd=root,
            check=True,
            env={**__import__("os").environ, **env},
        )
        return control.DelegatedRuntimeReceiptController(
            root / "receipts.sqlite3", repo_root=root
        )

    def test_issue_inspect_consume_and_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self._controller(Path(directory))
            receipt = self._issue(controller)
            self.assertEqual(controller.inspect()["status"], "issued")
            controller.consume(
                receipt_id=receipt["receipt_id"],
                agent_identity="luna-1",
                task_id="TASK-1",
                flow_id="FLOW-1",
                receipt_class="canary",
                command_argv=receipt["command_argv"],
                scenario="scenario-a",
                variant="variant-a",
            )
            self.assertEqual(controller.inspect()["status"], "consumed")
            with self.assertRaises(TypeError):
                controller.consume(receipt_id=receipt["receipt_id"])
            with self.assertRaisesRegex(control.FlowDeliveryError, "already consumed"):
                self._consume(controller, receipt)

    def test_wrong_identity_task_flow_and_command_fail_closed(self) -> None:
        for field, value in (
            ("agent_identity", "other"),
            ("task_id", "OTHER"),
            ("flow_id", "OTHER"),
            ("command_argv", ["development-session", "changed"]),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                controller = self._controller(Path(directory))
                receipt = self._issue(controller)
                kwargs = {
                    "agent_identity": "luna-1",
                    "task_id": "TASK-1",
                    "flow_id": "FLOW-1",
                    "receipt_class": "canary",
                    "command_argv": receipt["command_argv"],
                    "scenario": "scenario-a",
                    "variant": "variant-a",
                }
                kwargs[field] = value
                with self.assertRaises(control.FlowDeliveryError):
                    controller.consume(receipt_id=receipt["receipt_id"], **kwargs)
                self.assertEqual(controller.inspect()["status"], "issued")

    def test_changed_head_fingerprint_and_dirty_candidate_are_denied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self._controller(Path(directory))
            receipt = self._issue(controller)
            controller._candidate = lambda: ("changed-head", "fingerprint")  # type: ignore[method-assign]
            with self.assertRaisesRegex(control.FlowDeliveryError, "HEAD changed"):
                self._consume(controller, receipt)
        with tempfile.TemporaryDirectory() as directory:
            controller = self._controller(Path(directory))
            controller._candidate = lambda: (_ for _ in ()).throw(
                control.FlowDeliveryError("delegated receipt denied: dirty or untracked")
            )  # type: ignore[method-assign]
            with self.assertRaises(control.FlowDeliveryError):
                self._issue(controller)

    def test_argument_scenario_variant_and_expiration_are_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self._controller(Path(directory))
            receipt = self._issue(controller)
            with self.assertRaises(control.FlowDeliveryError):
                self._consume(controller, receipt, scenario="other")
            controller.now = lambda: time_now(receipt["expires_at"])
            with self.assertRaisesRegex(control.FlowDeliveryError, "expired"):
                self._consume(controller, receipt)

    def test_reconnaissance_capability_separation_and_canary_gates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self._controller(Path(directory))
            recon = self._issue(
                controller,
                receipt_class="reconnaissance",
                command=["development-session", "observe", "--max-inputs", "0"],
                total=0,
                identities=["safe-navigation"],
                classes=["navigation"],
                terminals=["observed", "evidence_required"],
                gates=False,
            )
            self.assertEqual(recon["max_combat_confirmations"], 0)
            with self.assertRaises(control.FlowDeliveryError):
                controller.issue(
                    task_id="T",
                    flow_id="F",
                    receipt_class="reconnaissance",
                    agent_identity="a",
                    command_argv=["development-session", "observe"],
                    scenario="s",
                    variant="v",
                    permitted_action_identities=["purchase-confirm"],
                    permitted_action_classes=["navigation"],
                    consequence_class="navigation_only",
                    max_total_inputs=1,
                    max_resource_affecting_inputs=1,
                    max_combat_confirmations=0,
                    permitted_terminal_states=["observed"],
                    result_identity="r",
                )
        with tempfile.TemporaryDirectory() as directory:
            controller = self._controller(Path(directory))
            with self.assertRaisesRegex(control.FlowDeliveryError, "self-check"):
                self._issue(controller, gates=False)

    def test_zero_input_observation_capability_issues_and_cannot_reserve(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self._controller(Path(directory))
            receipt = self._issue(
                controller,
                receipt_class="reconnaissance",
                command=["development-session", "observe", "--max-inputs", "0"],
                total=0,
                identities=["daily-row-prepare-observation"],
                classes=["observation"],
                terminals=["observed", "evidence_required"],
                gates=False,
                action_bindings=[
                    {
                        "action_identity": "daily-row-prepare-observation",
                        "action_class": "observation",
                        "consequence_class": "navigation_only",
                        "resource_affecting": False,
                        "combat_confirmation": False,
                    }
                ],
            )
            self.assertEqual(receipt["max_total_inputs"], 0)
            self.assertEqual(receipt["permitted_action_classes"], ["observation"])
            consumed = self._consume(controller, receipt)
            with self.assertRaisesRegex(control.FlowDeliveryError, "budget exhausted"):
                controller.reserve_input(
                    consumed,
                    action_identity="daily-row-prepare-observation",
                    action_class="observation",
                    consequence_class="navigation_only",
                    action_key="prepare-observation",
                )

    def test_reconnaissance_rejects_old_claim_prepare_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self._controller(Path(directory))
            with self.assertRaisesRegex(control.FlowDeliveryError, "forbidden capability"):
                self._issue(
                    controller,
                    receipt_class="reconnaissance",
                    command=["development-session", "observe", "--max-inputs", "0"],
                    total=0,
                    identities=["daily-row-claim-prepare-observation"],
                    classes=["observation"],
                    terminals=["observed", "evidence_required"],
                    gates=False,
                    action_bindings=[
                        {
                            "action_identity": "daily-row-claim-prepare-observation",
                            "action_class": "observation",
                            "consequence_class": "navigation_only",
                            "resource_affecting": False,
                            "combat_confirmation": False,
                        }
                    ],
                )

    def test_budget_reservation_precedes_transport_and_unresolved_never_reopens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self._controller(Path(directory))
            receipt = self._issue(
                controller,
                total=1,
                identities=["target-a"],
                terminals=["completed", "evidence_required"],
            )
            consumed = self._consume(controller, receipt)
            context = control.DelegatedRuntimeContext(
                controller, consumed, result_identity="result-a"
            )
            reservation = context.reserve_input(
                action_identity="target-a",
                action_class="navigation",
                consequence_class="navigation_only",
                source_evidence_hash="a" * 64,
                action_key="action-a",
            )
            self.assertEqual(reservation["ordinal"], 1)
            context.mark_reconciled("action-a", unresolved=True)
            with self.assertRaisesRegex(control.FlowDeliveryError, "unresolved"):
                context.reserve_input(
                    action_identity="target-a",
                    action_class="navigation",
                    consequence_class="navigation_only",
                    action_key="retry",
                )
            with self.assertRaisesRegex(control.FlowDeliveryError, "pending"):
                context.record_terminal(status="completed", payload={})
            context.record_terminal(
                status="evidence_required",
                payload={"receipt_id": receipt["receipt_id"]},
            )

    def test_result_binding_and_terminal_state_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self._controller(Path(directory))
            receipt = self._issue(controller)
            consumed = self._consume(controller, receipt)
            context = control.DelegatedRuntimeContext(
                controller, consumed, result_identity="result-a"
            )
            with self.assertRaises(control.FlowDeliveryError):
                context.record_terminal(status="completed", payload={})
            with self.assertRaisesRegex(control.FlowDeliveryError, "result identity"):
                control.DelegatedRuntimeContext(
                    controller, consumed, result_identity="other"
                ).record_terminal(status="dry_run", payload={})

    def test_cached_keys_and_reconciled_actions_still_hit_durable_replay_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self._controller(Path(directory))
            receipt = self._issue(
                controller,
                identities=["target-a", "target-b"],
                classes=["navigation", "navigation"],
                total=2,
                terminals=["completed", "evidence_required"],
            )
            consumed = self._consume(controller, receipt)
            context = control.DelegatedRuntimeContext(
                controller, consumed, result_identity="result-a"
            )
            context.reserve_input(
                action_identity="target-a",
                action_class="navigation",
                consequence_class="navigation_only",
                action_key="same-key",
            )
            context.mark_reconciled("same-key")
            with self.assertRaisesRegex(control.FlowDeliveryError, "identical"):
                context.reserve_input(
                    action_identity="target-a",
                    action_class="navigation",
                    consequence_class="navigation_only",
                    action_key="same-key",
                )

    def test_delegated_recovery_requires_explicit_binding_before_callback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self._controller(root)
            receipt = self._issue(
                controller,
                identities=["action"],
                classes=["navigation"],
                total=2,
                terminals=["completed", "evidence_required"],
            )
            consumed = self._consume(controller, receipt)
            context = control.DelegatedRuntimeContext(
                controller, consumed, result_identity="result-a"
            )
            called = []
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with boundary.delegated_runtime_context(context):
                    with boundary.DevelopmentSession(
                        owner="luna",
                        invocation_id="recovery",
                        session_directory=root / "session",
                        max_inputs=2,
                    ) as session:
                        with self.assertRaisesRegex(
                            boundary.DevelopmentSessionError, "explicit action binding"
                        ):
                            session.run_action(
                                action_class="navigation",
                                label="action",
                                capture=lambda label: _frame(label),
                                dispatch=lambda _source: None,
                                recognize=lambda _source: "unknown",
                                recover=lambda _source: called.append(True) or True,
                            )
            self.assertEqual(called, [])

    def test_resource_and_combat_flags_are_durable_and_budgeted(self) -> None:
        bindings = [
            {
                "action_identity": "claim-one",
                "action_class": "claim",
                "consequence_class": "resource_affecting",
                "resource_affecting": True,
                "combat_confirmation": False,
            },
            {
                "action_identity": "combat-one",
                "action_class": "combat_confirmation",
                "consequence_class": "combat_confirmation",
                "resource_affecting": False,
                "combat_confirmation": True,
            },
            {
                "action_identity": "claim-two",
                "action_class": "claim",
                "consequence_class": "resource_affecting",
                "resource_affecting": True,
                "combat_confirmation": False,
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            controller = self._controller(Path(directory))
            receipt = self._issue(
                controller,
                identities=["claim-one", "combat-one", "claim-two"],
                classes=["claim", "combat_confirmation", "claim"],
                action_bindings=bindings,
                total=3,
                resource_budget=1,
                combat_budget=1,
                terminals=["completed", "evidence_required"],
            )
            consumed = self._consume(controller, receipt)
            context = control.DelegatedRuntimeContext(
                controller, consumed, result_identity="result-a"
            )
            for identity, action_class, consequence, key in (
                ("claim-one", "claim", "resource_affecting", "r1"),
                ("combat-one", "combat_confirmation", "combat_confirmation", "c1"),
            ):
                context.reserve_input(
                    action_identity=identity,
                    action_class=action_class,
                    consequence_class=consequence,
                    action_key=key,
                )
                context.mark_reconciled(key)
            with self.assertRaisesRegex(control.FlowDeliveryError, "resource-affecting"):
                context.reserve_input(
                    action_identity="claim-two",
                    action_class="claim",
                    consequence_class="resource_affecting",
                    action_key="r2",
                )

    def test_action_bindings_cannot_cross_pair_identity_and_class(self) -> None:
        bindings = [
            {
                "action_identity": "navigation-one",
                "action_class": "combat_confirmation",
                "consequence_class": "combat_confirmation",
                "resource_affecting": False,
                "combat_confirmation": True,
            },
            {
                "action_identity": "combat-one",
                "action_class": "navigation",
                "consequence_class": "navigation_only",
                "resource_affecting": False,
                "combat_confirmation": False,
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            controller = self._controller(Path(directory))
            with self.assertRaisesRegex(control.FlowDeliveryError, "exact bindings"):
                self._issue(
                    controller,
                    identities=["navigation-one", "combat-one"],
                    classes=["navigation", "combat_confirmation"],
                    action_bindings=bindings,
                    total=2,
                    combat_budget=1,
                )

    def test_all_pending_reservation_states_block_success(self) -> None:
        for pending_status in ("reserved", "input_sent", "unresolved"):
            with self.subTest(pending_status=pending_status), tempfile.TemporaryDirectory() as directory:
                controller = self._controller(Path(directory))
                receipt = self._issue(
                    controller,
                    identities=["target-a"],
                    classes=["navigation"],
                    total=1,
                    terminals=["completed", "evidence_required"],
                )
                consumed = self._consume(controller, receipt)
                context = control.DelegatedRuntimeContext(
                    controller, consumed, result_identity="result-a"
                )
                context.reserve_input(
                    action_identity="target-a",
                    action_class="navigation",
                    consequence_class="navigation_only",
                    action_key="a",
                )
                if pending_status == "input_sent":
                    context.mark_transported("a")
                elif pending_status == "unresolved":
                    context.mark_reconciled("a", unresolved=True)
                with self.assertRaisesRegex(control.FlowDeliveryError, "pending"):
                    context.record_terminal(status="completed", payload={})

    def test_canary_rejects_unsupported_terminal_vocabulary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self._controller(Path(directory))
            with self.assertRaisesRegex(control.FlowDeliveryError, "terminal vocabulary"):
                self._issue(controller, terminals=["not-a-terminal"])

    def test_real_git_content_fingerprint_rejects_tracked_and_untracked_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self._git_controller(root)
            receipt = self._issue(controller)
            self.assertEqual(receipt["working_tree_fingerprint"], controller._candidate()[1])
            self._consume(controller, receipt)
            receipt2 = self._issue(controller)
            (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(control.FlowDeliveryError, "dirty|changed"):
                self._consume(controller, receipt2)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self._git_controller(root)
            receipt = self._issue(controller)
            (root / "untracked.txt").write_text("untracked\n", encoding="utf-8")
            with self.assertRaisesRegex(control.FlowDeliveryError, "dirty|untracked"):
                self._consume(controller, receipt)

    def test_direct_development_session_reserves_before_callback_and_releases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self._controller(root)
            receipt = self._issue(
                controller,
                identities=["action"],
                classes=["navigation"],
                terminals=["completed", "evidence_required"],
                total=1,
            )
            consumed = self._consume(controller, receipt)
            context = control.DelegatedRuntimeContext(
                controller, consumed, result_identity="result-a"
            )
            order: list[str] = []
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with boundary.delegated_runtime_context(context):
                    with boundary.DevelopmentSession(
                        owner="luna",
                        invocation_id="one",
                        session_directory=root / "session",
                        max_inputs=1,
                    ) as session:
                        result = session.run_action(
                            action_class="navigation",
                            label="action",
                            capture=lambda label: _frame(label),
                            dispatch=lambda _source: order.append("transport"),
                            recognize=lambda _source: "known",
                        )
            self.assertEqual(result.status, "completed")
            self.assertEqual(order, ["transport"])
            self.assertFalse(session._ownership.lock.held)
            context.record_terminal(status="completed", payload={"ok": True})

    def test_runtime_transport_exception_marks_reservation_unresolved(self) -> None:
        class Runner:
            def dispatch_tap(self, point):
                raise TimeoutError("transport timeout")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self._controller(root)
            receipt = self._issue(
                controller,
                identities=["target"],
                classes=["navigation"],
                total=1,
            )
            consumed = self._consume(controller, receipt)
            context = control.DelegatedRuntimeContext(
                controller, consumed, result_identity="result-a"
            )
            runtime = LocalBlueStacksRuntime(
                Runner(), root / "runtime", execute=True
            )
            with patch.object(boundary, "_DELEGATED_RUNTIME_CONTEXT") as context_var:
                context_var.get.return_value = context
                with self.assertRaises(TimeoutError):
                    runtime.tap(
                        _frame("source"),
                        target_identity="target",
                        target_roi=(1, 1, 10, 10),
                        action_key="tap-a",
                    )
            with self.assertRaisesRegex(control.FlowDeliveryError, "unresolved"):
                context.reserve_input(
                    action_identity="target",
                    action_class="navigation",
                    consequence_class="navigation_only",
                    action_key="retry",
                )

    def test_overlapping_singleton_and_compatibility_boundaries_remain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "lock.sqlite3"
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", lock):
                first = boundary.RuntimeInputLock(owner="a", invocation_id="1").acquire()
                with self.assertRaises(boundary.NavigationBoundaryError):
                    boundary.RuntimeInputLock(owner="b", invocation_id="2").acquire()
                first.release()
            self.assertTrue(pnsctl.BLUESTACKS_FLOW_IDS)
            self.assertIsNotNone(pnsctl._BLUESTACKS_FLOW_RUNNERS)

    def test_pnsctl_dry_run_and_zero_input_observe_bind_results_without_live_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "receipts.sqlite3"
            dry_argv = [
                "development-session",
                "delegated-dry-run",
                "--delegated-receipt",
                str(state),
                "--agent-identity",
                "luna-1",
                "--task-id",
                "TASK-1",
                "--flow-id",
                "FLOW-1",
                "--scenario",
                "scenario-a",
                "--variant",
                "variant-a",
                "--max-inputs",
                "0",
            ]
            controller = self._controller(root)
            self._issue(
                controller,
                receipt_class="canary",
                command=dry_argv,
                total=0,
                terminals=["dry_run", "evidence_required"],
            )
            with patch.object(pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"), patch.object(
                pnsctl, "_development_runtime_observation", side_effect=AssertionError
            ), patch.object(
                control.DelegatedRuntimeReceiptController,
                "_candidate",
                return_value=("head", "fingerprint"),
            ):
                output = json.loads(
                    pnsctl.development_session_delegated_dry_run(
                        receipt_state=state,
                        command_argv=dry_argv,
                        agent_identity="luna-1",
                        task_id="TASK-1",
                        flow_id="FLOW-1",
                        scenario="scenario-a",
                        variant="variant-a",
                        max_inputs=0,
                    )
                )
            self.assertFalse(output["runtime_access"])

    def test_pnsctl_zero_input_delegated_observe_owns_and_releases_mocked_singleton(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "receipts.sqlite3"
            observe_argv = [
                "development-session", "observe", "--max-inputs", "0",
                "--delegated-receipt", str(state), "--agent-identity", "luna-1",
                "--task-id", "TASK-1", "--flow-id", "FLOW-1",
                "--scenario", "scenario-a", "--variant", "variant-a",
            ]
            controller = self._controller(root)
            self._issue(
                controller,
                receipt_class="reconnaissance",
                command=observe_argv,
                total=0,
                terminals=["observed", "evidence_required"],
                gates=False,
            )
            observation = {
                "device_state": "device",
                "foreground_package": pnsctl.PACKAGE,
                "native_width": 800,
                "native_height": 1280,
                "frame_sha256": hashlib.sha256(b"png").hexdigest(),
            }
            with patch.object(pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"), patch.object(
                pnsctl, "DEVELOPMENT_CHECKPOINT_PATHS", ()
            ), patch.object(
                pnsctl, "_development_runtime_observation", return_value=(observation, b"png")
            ), patch.object(
                control.DelegatedRuntimeReceiptController,
                "_candidate",
                return_value=("head", "fingerprint"),
            ), patch.object(
                boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"
            ):
                output = json.loads(
                    pnsctl.development_session_observe(
                        max_inputs=0,
                        delegated_receipt=state,
                        agent_identity="luna-1",
                        task_id="TASK-1",
                        flow_id="FLOW-1",
                        scenario="scenario-a",
                        variant="variant-a",
                        command_argv=observe_argv,
                    )
                )
            self.assertEqual(output["status"], "observed")
            self.assertEqual(output["input_count"], 0)
            self.assertTrue((Path(output["session_directory"]) / "observe.png").is_file())
            summary = json.loads(
                (Path(output["session_directory"]) / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["receipt_id"], output["receipt_id"])
            self.assertEqual(summary["status"], "observed")
            self.assertFalse(summary["dispatch"])
            self.assertTrue(summary["ownership_released"])
            self.assertEqual(controller.inspect()["status"], "consumed")

    def test_observe_frame_hash_mismatch_records_fail_closed_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "receipts.sqlite3"
            argv = ["development-session", "observe", "--max-inputs", "0"]
            controller = self._controller(root)
            receipt = self._issue(
                controller,
                receipt_class="reconnaissance",
                command=argv,
                total=0,
                terminals=["observed", "evidence_required"],
                gates=False,
            )
            observation = {
                "device_state": "device",
                "foreground_package": pnsctl.PACKAGE,
                "native_width": 800,
                "native_height": 1280,
                "frame_sha256": "a" * 64,
            }
            with patch.object(pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"), patch.object(
                pnsctl, "DEVELOPMENT_CHECKPOINT_PATHS", ()
            ), patch.object(
                pnsctl, "_development_runtime_observation", return_value=(observation, b"png")
            ), patch.object(
                control.DelegatedRuntimeReceiptController,
                "_candidate",
                return_value=("head", "fingerprint"),
            ), patch.object(
                boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"
            ):
                with self.assertRaisesRegex(pnsctl.OperatorError, "frame hash mismatch"):
                    pnsctl.development_session_observe(
                        max_inputs=0,
                        delegated_receipt=state,
                        agent_identity="luna-1",
                        task_id="TASK-1",
                        flow_id="FLOW-1",
                        scenario="scenario-a",
                        variant="variant-a",
                        command_argv=argv,
                    )
            session_directory = root / "sessions" / f"delegated-{receipt['receipt_id']}"
            result = json.loads((session_directory / "result.json").read_text(encoding="utf-8"))
            summary = json.loads((session_directory / "summary.json").read_text(encoding="utf-8"))
            for artifact in (result, summary):
                self.assertEqual(artifact["status"], "evidence_required")
                self.assertEqual(artifact["receipt_id"], receipt["receipt_id"])
                self.assertEqual(artifact["receipt_digest"], receipt["receipt_digest"])
                self.assertEqual(artifact["input_count"], 0)
                self.assertFalse(artifact["dispatch"])
            self.assertTrue(result["ownership_released"])
            self.assertTrue(summary["ownership_released"])

    def test_observe_release_failure_records_evidence_required_not_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "receipts.sqlite3"
            argv = ["development-session", "observe", "--max-inputs", "0"]
            controller = self._controller(root)
            receipt = self._issue(
                controller,
                receipt_class="reconnaissance",
                command=argv,
                total=0,
                terminals=["observed", "evidence_required"],
                gates=False,
            )

            class BrokenSession:
                def __init__(self, **_kwargs):
                    self._ownership = type("Ownership", (), {})()
                    self._ownership.lock = type("Lock", (), {"held": True})()

                def __enter__(self):
                    Path(pnsctl.DEVELOPMENT_SESSION_ROOT, f"delegated-{receipt['receipt_id']}").mkdir(
                        parents=True, exist_ok=True
                    )
                    return self

                def __exit__(self, *_args):
                    raise RuntimeError("ownership release failed")

            observation = {
                "device_state": "device",
                "foreground_package": pnsctl.PACKAGE,
                "native_width": 800,
                "native_height": 1280,
                "frame_sha256": "a" * 64,
            }
            with patch.object(pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"), patch.object(
                pnsctl, "DEVELOPMENT_CHECKPOINT_PATHS", ()
            ), patch.object(
                pnsctl, "_development_runtime_observation", return_value=(observation, b"png")
            ), patch.object(
                control.DelegatedRuntimeReceiptController,
                "_candidate",
                return_value=("head", "fingerprint"),
            ), patch.object(boundary, "DevelopmentSession", BrokenSession):
                with self.assertRaisesRegex(RuntimeError, "release failed"):
                    pnsctl.development_session_observe(
                        max_inputs=0,
                        delegated_receipt=state,
                        agent_identity="luna-1",
                        task_id="TASK-1",
                        flow_id="FLOW-1",
                        scenario="scenario-a",
                        variant="variant-a",
                        command_argv=argv,
                    )
            consumed = receipt
            session_directory = root / "sessions" / f"delegated-{receipt['receipt_id']}"
            result = json.loads((session_directory / "result.json").read_text(encoding="utf-8"))
            summary = json.loads((session_directory / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "evidence_required")
            self.assertEqual(summary["status"], "evidence_required")
            self.assertFalse(result["ownership_released"])
            self.assertFalse(summary["ownership_released"])
            with self.assertRaisesRegex(control.FlowDeliveryError, "terminal result"):
                controller.record_result(
                    consumed,
                    status="observed",
                    result_identity="result-a",
                    payload={},
                )

    def test_observe_failure_artifact_write_still_records_evidence_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "receipts.sqlite3"
            argv = ["development-session", "observe", "--max-inputs", "0"]
            controller = self._controller(root)
            receipt = self._issue(
                controller,
                receipt_class="reconnaissance",
                command=argv,
                total=0,
                terminals=["observed", "evidence_required"],
                gates=False,
            )
            with patch.object(pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"), patch.object(
                pnsctl, "DEVELOPMENT_CHECKPOINT_PATHS", ()
            ), patch.object(
                pnsctl,
                "_development_runtime_observation",
                side_effect=pnsctl.OperatorError("observation failed"),
            ), patch.object(
                control.DelegatedRuntimeReceiptController,
                "_candidate",
                return_value=("head", "fingerprint"),
            ), patch.object(
                boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"
            ), patch.object(
                pnsctl,
                "_write_delegated_observation_failure",
                side_effect=OSError("failure artifact write failed"),
            ):
                with self.assertRaisesRegex(pnsctl.OperatorError, "observation failed"):
                    pnsctl.development_session_observe(
                        max_inputs=0,
                        delegated_receipt=state,
                        agent_identity="luna-1",
                        task_id="TASK-1",
                        flow_id="FLOW-1",
                        scenario="scenario-a",
                        variant="variant-a",
                        command_argv=argv,
                    )

            connection = controller._connection()
            try:
                terminal = connection.execute(
                    "SELECT status, payload_json FROM delegated_results WHERE receipt_id=?",
                    (receipt["receipt_id"],),
                ).fetchone()
            finally:
                connection.close()
            self.assertIsNotNone(terminal)
            self.assertEqual(terminal[0], "evidence_required")
            self.assertEqual(json.loads(terminal[1])["status"], "evidence_required")
            with self.assertRaisesRegex(control.FlowDeliveryError, "terminal result"):
                controller.record_result(
                    receipt,
                    status="observed",
                    result_identity="result-a",
                    payload={},
                )

    def test_daily_claim_canary_reserves_exact_reward_claim_class_once(self) -> None:
        bindings = [
            {
                "action_identity": "daily-row-claim:consume_stamina",
                "action_class": "reward_claim",
                "consequence_class": "ordinary_development",
                "resource_affecting": False,
                "combat_confirmation": False,
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self._controller(root)
            receipt = self._issue(
                controller,
                identities=["daily-row-claim:consume_stamina"],
                classes=["reward_claim"],
                action_bindings=bindings,
                consequence_class="ordinary_development",
                total=1,
                terminals=["completed", "evidence_required"],
            )
            consumed = self._consume(controller, receipt)
            context = control.DelegatedRuntimeContext(
                controller, consumed, result_identity="result-a"
            )
            reservation = context.reserve_input(
                action_identity="daily-row-claim:consume_stamina",
                action_class="reward_claim",
                consequence_class="ordinary_development",
                source_evidence_hash="a" * 64,
                action_key="daily-row-claim:consume_stamina",
            )
            self.assertEqual(reservation["ordinal"], 1)
            connection = controller._connection()
            try:
                stored = connection.execute(
                    "SELECT action_class, consequence_class, status "
                    "FROM delegated_reservations WHERE receipt_id=?",
                    (receipt["receipt_id"],),
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(tuple(stored), ("reward_claim", "ordinary_development", "reserved"))
            context.mark_reconciled("daily-row-claim:consume_stamina")
            with self.assertRaisesRegex(control.FlowDeliveryError, "identical action retry"):
                context.reserve_input(
                    action_identity="daily-row-claim:consume_stamina",
                    action_class="reward_claim",
                    consequence_class="ordinary_development",
                    action_key="retry",
                )


def time_now(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


if __name__ == "__main__":
    unittest.main()
