from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
import multiprocessing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import flow_delivery_control as control
from scripts import pnsctl


ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "tasks" / "flow_delivery_queue.json"
POLICY_PATH = ROOT / "tasks" / "flow_delivery_product_policy.json"
WORKFLOW_POLICY_PATH = ROOT / "tasks" / "agentic_workflow_policy.json"
WORKFLOW_HOOK_PATH = (
    ROOT / ".cursor" / "hooks" / "pns_agent_workflow_guard.py"
)


def _load_workflow_guard():
    spec = importlib.util.spec_from_file_location(
        "pns_agent_workflow_guard_test_module",
        WORKFLOW_HOOK_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load workflow guard")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


workflow_guard = _load_workflow_guard()
WORKFLOW_PARENT_CONVERSATION_ID = "b5e9970d-00b2-40fb-9cd8-3e7d2d97653e"


def _concurrent_admission_worker(
    root: str,
    counter_dir: str,
    event: dict[str, object],
    barrier,
    result_queue,
) -> None:
    guard = _load_workflow_guard()
    try:
        barrier.wait(timeout=10)
        with (
            patch.object(guard, "_repo_head", return_value="fixture-head"),
            patch.object(
                guard,
                "_latest_handoff_commit",
                return_value="fixture-head",
            ),
        ):
            result = guard.admit(
                event,
                repo_root=Path(root),
                now=datetime(2026, 8, 17, 0, 0, 1, tzinfo=timezone.utc),
                counter_dir=Path(counter_dir),
            )
    except BaseException as exc:
        result_queue.put({"worker_error": repr(exc)})
    else:
        result_queue.put(result)


class FlowDeliveryQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        self.policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    def test_queue_and_policy_schema_are_valid(self) -> None:
        control.validate_queue(self.queue)
        control.validate_policy(self.policy)
        self.assertEqual(
            self.queue["active_development_validation_policy"],
            "focused_component_profiles_only; full_suite_manual_opt_in",
        )
        self.assertFalse(self.queue["gameplay_scheduler"])
        self.assertEqual(
            self.queue["status_vocabulary"],
            ["ready", "active", "blocked", "completed", "needs_product_decision"],
        )
        for flow in self.queue["flows"]:
            for focused_test in flow["focused_tests"]:
                self.assertTrue(
                    (ROOT / focused_test).is_file(),
                    f"{flow['flow_id']} references missing focused test {focused_test}",
                )

    def test_exactly_one_or_zero_active_flow(self) -> None:
        active = [item for item in self.queue["flows"] if item["status"] == "active"]
        self.assertLessEqual(len(active), 1)
        if not active:
            self.assertIsNone(self.queue["active_flow_id"])
        else:
            self.assertEqual(self.queue["active_flow_id"], active[0]["flow_id"])
        broken = deepcopy(self.queue)
        broken["flows"][0]["status"] = "active"
        broken["flows"][0]["live_attempt_count"] = len(
            broken["flows"][0]["live_attempts"]
        )
        broken["flows"][1]["status"] = "active"
        broken["active_flow_id"] = broken["flows"][0]["flow_id"]
        with self.assertRaisesRegex(control.FlowDeliveryError, "exactly one or zero"):
            control.validate_queue(broken)

    def test_completed_history_may_retain_compacted_attempt_count(self) -> None:
        completed = deepcopy(self.queue)
        campaign = next(
            flow
            for flow in completed["flows"]
            if flow["flow_id"] == "AUTONOMY-SERVICE-CAMPAIGN-NAVIGATION-PROVING-SLICE"
        )
        self.assertEqual(campaign["status"], "completed")
        self.assertGreater(
            campaign["live_attempt_count"], len(campaign["live_attempts"])
        )
        control.validate_queue(completed)

        active = deepcopy(completed)
        enhancement = next(
            flow
            for flow in active["flows"]
            if flow["flow_id"] == "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION"
        )
        enhancement["status"] = "active"
        enhancement["last_completed_stage"] = "selected"
        enhancement["live_attempt_count"] = 1
        active["active_flow_id"] = enhancement["flow_id"]
        with self.assertRaisesRegex(
            control.FlowDeliveryError,
            "live_attempt_count does not match attempts",
        ):
            control.validate_queue(active)

    def test_deterministic_selection_and_active_resume(self) -> None:
        controller = control.FlowDeliveryController()
        first = controller.select_next(self.queue)
        if self.queue.get("active_flow_id"):
            self.assertEqual(first["flow_id"], self.queue["active_flow_id"])
        else:
            ready = [flow for flow in self.queue["flows"] if flow["status"] == "ready"]
            if ready:
                expected = min(
                    ready,
                    key=lambda flow: (flow["priority"], flow["flow_id"]),
                )
                self.assertEqual(first["flow_id"], expected["flow_id"])
            else:
                self.assertIsNone(first)
        active = deepcopy(self.queue)
        for flow in active["flows"]:
            if flow["status"] == "active":
                flow["status"] = "ready"
                flow["last_completed_stage"] = "selected"
        active_flow = next(
            flow
            for flow in active["flows"]
            if flow["flow_id"] == "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION"
        )
        active_flow["status"] = "active"
        active_flow["last_completed_stage"] = "implementation"
        active["active_flow_id"] = active_flow["flow_id"]
        self.assertEqual(
            controller.select_next(active)["flow_id"],
            "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION",
        )

    def test_blocked_and_policy_disabled_flows_are_skipped(self) -> None:
        queue = deepcopy(self.queue)
        for flow in queue["flows"]:
            if flow["status"] == "active":
                flow["status"] = "completed"
                flow["last_completed_stage"] = "completed"
        queue["active_flow_id"] = None
        enhancement = next(
            flow
            for flow in queue["flows"]
            if flow["flow_id"] == "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION"
        )
        enhancement["status"] = "blocked"
        enhancement["blocked_reason"] = "test blocker"
        selected = control.FlowDeliveryController(
            lease_path=ROOT / ".local-orchestrator" / "orchestrator-test-no-lease.json"
        ).select_next(queue)
        ready = [flow for flow in queue["flows"] if flow["status"] == "ready"]
        if ready:
            expected = min(
                ready,
                key=lambda flow: (flow["priority"], flow["flow_id"]),
            )
            self.assertEqual(selected["flow_id"], expected["flow_id"])
        else:
            self.assertIsNone(selected)

    def test_composition_bliss_and_gameplay_scheduler_are_excluded(self) -> None:
        identities = {item["flow_id"] for item in self.queue["flows"]}
        joined = json.dumps(self.queue).lower()
        self.assertNotIn("RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION", identities)
        self.assertNotIn("bliss migration", joined)
        self.assertNotIn("production scheduler", joined)
        scheduler = (ROOT / "tasks" / "scheduler.py").read_text(encoding="utf-8")
        self.assertIn("offline Phase F work", scheduler)
        self.assertNotIn("flow_delivery_queue", scheduler)

    def test_initial_order_and_normalized_counts(self) -> None:
        expected = [
            "AUTONOMY-SERVICE-CAMPAIGN-NAVIGATION-PROVING-SLICE",
            "CAMPAIGN-ATLAS-SURVEY-CONTRACT-AND-COLLECTOR-PREP",
            "CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION",
            "CAMPAIGN-ATLAS-NAVIGATION-INTEGRATION-AND-REPLAY",
            "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION",
            "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION",
            "NOVA-PRAISE-HOME-ATLAS-MIGRATION",
            "NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE",
            "CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY",
            "NOAHS-TAVERN-HOME-ATLAS-MIGRATION",
            "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION",
            "TROOP-TRAINING-VERIFIED-NAVIGATION-CONVERGENCE",
            "TROOP-TRAINING-END-TO-END-CONSOLIDATION",
            "SUPPLY-DEPOT-LEGACY-ADAPTER-RETIREMENT",
            "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
            "DAILY-MILESTONE-CLAIM-BLUESTACKS-INTEGRATION",
            "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION",
            "NANOWEAPON-BLUESTACKS-INTEGRATION",
            "NANO-MATERIAL-PRODUCTION-MAINTENANCE",
            "RECRUITMENT-BLUESTACKS-INTEGRATION",
            "RECRUITMENT-FREE-ATTEMPT-MAINTENANCE",
            "WORLD-MAP-NAVIGATION-FOUNDATION",
            "GATHERING-BLUESTACKS-INTEGRATION",
            "ZOMBIE-LAIR-BLUESTACKS-INTEGRATION",
            "ZOMBIE-LAIR-HOME-MAINTENANCE",
            "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION",
            "RUINS-SHOP-PURCHASE-EVIDENCE-GATE",
            "RARE-EARTH-SHOP-PURCHASE-EVIDENCE-GATE",
            "ALLIANCE-SHOP-PURCHASE-EVIDENCE-GATE",
            "HERO-UPGRADE-EVIDENCE-GATE",
            "HERO-DUEL-EVIDENCE-GATE",
            "VIP-GET-PTS-POPUP-DISMISSAL",
        ]
        self.assertEqual([item["flow_id"] for item in self.queue["flows"]], expected)
        counts = {
            status: sum(item["status"] == status for item in self.queue["flows"])
            for status in control.QUEUE_STATUSES
        }
        self.assertIn(counts["active"], (0, 1))
        self.assertEqual(counts["ready"] + counts["active"], 0)
        self.assertEqual(counts["blocked"], 13)
        self.assertEqual(counts["completed"], 19)
        self.assertEqual(counts["needs_product_decision"], 0)

    def test_campaign_destinations_are_exact_and_legacy_pan_is_recorded(self) -> None:
        campaign = next(
            flow
            for flow in self.queue["flows"]
            if flow["flow_id"] == "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION"
        )
        campaign_policy = next(
            item
            for item in self.policy["policies"]
            if item["policy_id"] == "campaign-supported-destinations"
        )
        scope = campaign["live_validation_scope"]
        self.assertEqual(
            campaign["destination_policy_id"], "campaign-supported-destinations"
        )
        self.assertNotIn("supported_story_destinations", campaign)
        self.assertNotIn("rejected_destinations", campaign)
        for destination in campaign_policy["supported_story_destinations"]:
            self.assertIn(destination, scope)
        for rejected in campaign_policy["rejected_destinations"]:
            self.assertNotIn(rejected, campaign_policy["supported_story_destinations"])
            self.assertNotIn(rejected, scope)
        self.assertNotIn("1-2-9", scope)
        self.assertNotIn("ultimate-challenge", scope)
        campaign_source = (ROOT / "scripts" / "bluestacks_campaign_ap.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("--stage", campaign_source)
        self.assertIn("parse_supported_campaign_story_destination", campaign_source)
        runtime_source = (ROOT / "tasks" / "campaign_auto_battle_runtime.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("HOME_PAN_GESTURES", runtime_source)

    def test_ultimate_challenge_completed_metadata_is_retained(self) -> None:
        ultimate = next(
            flow
            for flow in self.queue["flows"]
            if flow["flow_id"] == "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION"
        )
        self.assertEqual(
            ultimate["flow_id"],
            "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION",
        )
        self.assertEqual(ultimate["status"], "completed")
        self.assertEqual(ultimate["last_completed_stage"], "completed")
        self.assertFalse(ultimate["blocked_reason"])
        self.assertEqual(ultimate["priority"], 15)
        self.assertEqual(
            ultimate["product_policy_status"],
            "supervised_consequential_validation",
        )
        self.assertEqual(
            ultimate["execution_product_policy_status"], "explicitly_approved"
        )
        policy_ids = {item["policy_id"] for item in self.policy["policies"]}
        self.assertIn("ultimate-challenge-flow-separation", policy_ids)
        registry = json.loads(
            (ROOT / "tasks" / "flow_delivery_bluestacks_registry.json").read_text(
                encoding="utf-8"
            )
        )
        uc_registry = registry["flows"][
            "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION"
        ]
        self.assertEqual(uc_registry["consequence_class"], "consequential")
        self.assertEqual(uc_registry["runner"], "ultimate_challenge_daily_runner")
        self.assertTrue(
            (ROOT / "scripts" / "bluestacks_ultimate_challenge.py").is_file()
        )
        self.assertTrue(
            (
                ROOT / "scripts" / "flow_delivery_ultimate_challenge_bluestacks.py"
            ).is_file()
        )
        self.assertTrue((ROOT / "tasks" / "ultimate_challenge_daily.py").is_file())
        operator = (ROOT / "scripts" / "bluestacks_ultimate_challenge.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("run_verified_ultimate_challenge_campaign_door", operator)
        self.assertIn("--navigation-only", operator)
        self.assertNotIn(
            'parse_supported_campaign_story_destination("ultimate-challenge")',
            operator,
        )


class FlowDeliveryControllerTests(unittest.TestCase):
    def make_controller(self, directory: str) -> control.FlowDeliveryController:
        root = Path(directory)
        queue = root / "queue.json"
        policy = root / "policy.json"
        queue_data = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        if not any(
            flow["status"] in {"ready", "active"} for flow in queue_data["flows"]
        ):
            candidate = next(
                flow for flow in queue_data["flows"] if flow["status"] == "completed"
            )
            candidate["status"] = "ready"
            candidate["last_completed_stage"] = "selected"
            candidate["blocked_reason"] = ""
            candidate["live_attempt_count"] = len(candidate["live_attempts"])
            queue_data["active_flow_id"] = None
        queue.write_text(json.dumps(queue_data), encoding="utf-8")
        policy.write_bytes(POLICY_PATH.read_bytes())
        return control.FlowDeliveryController(
            queue,
            policy,
            root / "lease.json",
            root / "writable-subagent.json",
        )

    def test_invalid_transition_fails_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(directory)
            with patch.object(controller, "_repo_head", return_value="a" * 40):
                controller.acquire(
                    owner="parent",
                    session_identity="session",
                    runtime_ownership_state="none",
                    unresolved_action_state="clear",
                )
                controller.activate(owner="parent")
                before = controller.queue_path.read_bytes()
                # Advance past whatever stage the copied queue already recorded.
                queue = json.loads(before.decode("utf-8"))
                active = next(
                    item for item in queue["flows"] if item["status"] == "active"
                )
                current = str(active.get("last_completed_stage") or "selected")
                allowed = sorted(control.TRANSITIONS.get(current, set()))
                nxt = next(
                    (
                        stage
                        for stage in allowed
                        if stage
                        not in {
                            "completed",
                            "blocked",
                            "commit",
                            "focused_validation",
                            "full_validation",
                            "live_preflight",
                            "live_execution",
                            "evidence_review",
                        }
                    ),
                    "blocked",
                )
                result = controller.record_stage(owner="parent", stage=nxt)
            self.assertNotEqual(controller.queue_path.read_bytes(), before)
            self.assertEqual(result["last_completed_stage"], nxt)

    def test_full_validation_is_historical_not_an_active_development_transition(
        self,
    ) -> None:
        self.assertNotIn("full_validation", control.TRANSITIONS["focused_validation"])
        self.assertIn("live_preflight", control.TRANSITIONS["focused_validation"])

    def test_local_lease_conflict_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(directory)
            with patch.object(controller, "_repo_head", return_value="b" * 40):
                controller.acquire(
                    owner="one",
                    session_identity="session-one",
                    runtime_ownership_state="none",
                    unresolved_action_state="clear",
                )
                with self.assertRaisesRegex(
                    control.FlowDeliveryError, "lease conflict"
                ):
                    controller.acquire(
                        owner="two",
                        session_identity="session-two",
                        runtime_ownership_state="none",
                        unresolved_action_state="clear",
                    )

    def test_stale_lease_cannot_clear_unresolved_runtime_or_journal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(directory)
            with patch.object(controller, "_repo_head", return_value="c" * 40):
                controller.acquire(
                    owner="parent",
                    session_identity="session",
                    runtime_ownership_state="unknown",
                    unresolved_action_state="unknown",
                )
            for arguments in (
                dict(
                    terminal_evidence=True,
                    runtime_state="unknown",
                    journal_state="resolved",
                    consequential_state="terminal",
                ),
                dict(
                    terminal_evidence=True,
                    runtime_state="released",
                    journal_state="unresolved",
                    consequential_state="terminal",
                ),
                dict(
                    terminal_evidence=True,
                    runtime_state="released",
                    journal_state="resolved",
                    consequential_state="nonterminal",
                ),
            ):
                with self.assertRaises(control.FlowDeliveryError):
                    controller.reconcile(**arguments)
                self.assertTrue(controller.lease_path.exists())

    def test_controller_never_mutates_gameplay_scheduler(self) -> None:
        scheduler = ROOT / "tasks" / "scheduler.py"
        before = scheduler.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(directory)
            controller.status()
            with patch.object(controller, "_repo_head", return_value="d" * 40):
                controller.acquire(
                    owner="parent",
                    session_identity="session",
                    runtime_ownership_state="none",
                    unresolved_action_state="clear",
                )
                controller.activate(owner="parent")
        self.assertEqual(scheduler.read_bytes(), before)

    def test_controller_source_has_no_live_transport(self) -> None:
        source = (ROOT / "scripts" / "flow_delivery_control.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("runtime.tap", source)
        self.assertNotIn("runtime.swipe", source)
        self.assertNotIn("HD-Adb", source)
        self.assertIn('["rev-parse", "HEAD"]', source)


class FlowDeliveryCursorContractTests(unittest.TestCase):
    def test_optional_implementer_is_the_only_development_agent(self) -> None:
        paths = sorted((ROOT / ".cursor" / "agents").glob("*.md"))
        self.assertEqual(
            [path.stem for path in paths],
            ["pns-flow-implementer"],
        )
        text = paths[0].read_text(encoding="utf-8")
        self.assertIn("model: gpt-5.6-luna-xhigh", text)
        self.assertIn("readonly: false", text)

    def test_skill_uses_plan_execute_escalate_with_bounded_delegation(self) -> None:
        skill = (
            ROOT / ".cursor" / "skills" / "pns-flow-delivery" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("The architecture planner freezes the manifest", skill)
        self.assertIn("The Sol parent is the mandatory", skill)
        self.assertIn("`control_plane_owner` for Heavy work", skill)
        self.assertIn("at most one", skill)
        self.assertIn("consolidated repair", skill)
        self.assertIn("compact handoff and", skill)
        self.assertIn("same chat", skill)
        self.assertIn("conversation-level stage and turn budgets", skill)
        self.assertNotIn("fresh chat", skill)
        self.assertIn("optional `pns-flow-implementer`", skill)
        self.assertIn("material, actionable findings", skill)
        self.assertNotIn("pns-flow-recon", skill)
        self.assertNotIn("pns-flow-reviewer", skill)

    def test_host_portable_routing_and_manifest_are_checked_in_contracts(self) -> None:
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        managed, project = agents.split(
            "<!-- codex-workflow-managed-end -->", 1
        )
        self.assertNotIn("execution_coordinator", managed)
        self.assertIn("control_plane_owner", project)
        self.assertIn("procedure_coordinator", project)
        self.assertIn("read-only, defect-first code-and-acceptance", project)
        self.assertIn("Exclude (record as a Note at most, never a finding)", project)
        self.assertIn("exact usage-export model slug", project)
        self.assertIn("Do not put receipt chronology", project)
        routing = (
            ROOT / ".cursor" / "rules" / "pns-model-routing.mdc"
        ).read_text(encoding="utf-8")
        self.assertIn("alwaysApply: true", routing)
        self.assertIn("`control_plane_owner`: Sol parent", routing)
        self.assertIn("`procedure_coordinator`: optional Luna XHigh", routing)
        self.assertIn("`bounded_implementer`: Luna XHigh", routing)
        self.assertIn("routine `independent_tester`: Terra High", routing)
        self.assertIn(
            "high-risk or cross-contract tester: delegated Sol Medium", routing
        )
        self.assertIn("prioritizes concrete defects and acceptance risks", routing)
        self.assertIn("credential exposure", routing)
        self.assertIn("unsafe command execution", routing)
        manifest = (ROOT / "docs" / "execution-manifest-template.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("## Frozen stage control", manifest)
        self.assertIn("Parent conversation ID", manifest)
        self.assertIn("| Role | Exact model slug | Authority |", manifest)
        self.assertIn("gpt-5.6-sol-high", manifest)
        self.assertIn("## Immutable budgets", manifest)
        self.assertNotIn("## Next authorized action", manifest)
        self.assertIn("RFC 3339 UTC milliseconds", manifest)
        self.assertIn("## Frozen architecture decision", manifest)
        self.assertIn("## Escalation conditions", manifest)

    def test_managed_subagent_start_hook_is_checked_in_and_narrow(self) -> None:
        hooks = json.loads((ROOT / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(
            hooks["hooks"]["subagentStart"][0]["command"],
            "python .cursor/hooks/pns_agent_workflow_guard.py",
        )
        self.assertTrue(hooks["hooks"]["subagentStart"][0]["failClosed"])
        policy = json.loads(WORKFLOW_POLICY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            set(policy["managed_agent_types"]),
            {"pns-flow-implementer", "terra-reviewer"},
        )
        self.assertTrue(WORKFLOW_HOOK_PATH.is_file())
        self.assertFalse(
            (ROOT / ".cursor" / "hooks" / "pns_flow_subagent_guard.py").exists()
        )
        self.assertFalse(
            (ROOT / ".cursor" / "rules" / "pns-flow-delivery-subagents.mdc").exists()
        )
        self.assertFalse(
            (ROOT / "tasks" / "flow_delivery_subagent_routing_policy.json").exists()
        )

    def test_obsolete_prompt_is_non_authoritative_and_history_preserved(self) -> None:
        prompt = (ROOT / "autonomous_iteration_prompt.md").read_text(encoding="utf-8")
        self.assertTrue(prompt.startswith("# Obsolete exploratory prompt"))
        self.assertIn("not an execution controller", prompt)
        self.assertNotIn("Use Plan Mode only.", prompt)
        self.assertIn("I want to explore and plan", prompt)

    def test_lf_and_unrelated_historical_prose_are_preserved(self) -> None:
        for path in (
            QUEUE_PATH,
            POLICY_PATH,
            ROOT / ".cursor" / "agents" / "pns-flow-implementer.md",
            ROOT / "autonomous_iteration_prompt.md",
        ):
            self.assertNotIn(b"\r\n", path.read_bytes())
        handoff = (ROOT / "CURRENT_HANDOFF.md").read_text(encoding="utf-8")
        self.assertNotIn(b"\r\n", (ROOT / "CURRENT_HANDOFF.md").read_bytes())
        state = json.loads(
            handoff.split("<!-- CURRENT_HANDOFF_STATE_BEGIN -->", 1)[1]
            .split("<!-- CURRENT_HANDOFF_STATE_END -->", 1)[0]
            .strip()
        )
        self.assertIn(state["current_task_id"], handoff)
        self.assertIn(state["next_task_id"], handoff)
        self.assertEqual(state["next_task_activation_status"], "awaiting_explicit_selection")
        self.assertEqual(state["active_task_or_flow"], "none")
        self.assertNotIn("actions_already_performed", handoff)
        # Historical Ruins/troop handoff ledgers live in Git history, not the compact volatile handoff.


class AgenticWorkflowGuardTests(unittest.TestCase):
    HEAD = "fixture-head"
    NOW = datetime(2026, 8, 17, 0, 0, 1, tzinfo=timezone.utc)

    def write_repo(self, directory: str, **overrides):
        root = Path(directory)
        (root / "tasks").mkdir(parents=True, exist_ok=True)
        policy = json.loads(WORKFLOW_POLICY_PATH.read_text(encoding="utf-8"))
        (root / "tasks" / "agentic_workflow_policy.json").write_text(
            json.dumps(policy),
            encoding="utf-8",
        )
        state = {
            "schema_version": 3,
            "head_binding": "latest_commit_touches_handoff",
            "control_owner": "sol_parent",
            "control_parent_conversation_id": WORKFLOW_PARENT_CONVERSATION_ID,
            "stage_revision": "stage-1",
            "stage_type": "offline_implementation",
            "product_precondition": "proven",
            "failure_class": "none",
            "stage_start_utc": "2026-08-17T00:00:00Z",
            "continuation_checkpoint_utc": "not recorded",
            "user_continuation_utc": "not recorded",
            "budgets": {
                "per_stage": {
                    "implementation": 1,
                    "repair": 1,
                    "review": 1,
                    "recheck": 1,
                },
                "per_parent_conversation": {
                    "managed_turns": 8,
                    "stage_revisions": 3,
                },
            },
        }
        state.update(overrides)
        (root / "CURRENT_HANDOFF.md").write_text(
            "<!-- CURRENT_HANDOFF_STATE_BEGIN -->\n"
            + json.dumps(state)
            + "\n<!-- CURRENT_HANDOFF_STATE_END -->\n",
            encoding="utf-8",
        )
        return root

    @staticmethod
    def event(
        *,
        agent_type="pns-flow-implementer",
        model="cursor-gpt-5.6-luna-xhigh",
        parent=WORKFLOW_PARENT_CONVERSATION_ID,
        fields=None,
    ):
        values = {
            "Control-Owner": "sol_parent",
            "Stage-Revision": "stage-1",
            "Turn-Kind": "implementation",
            "Product-Precondition": "proven",
        }
        if fields:
            values.update(fields)
        prompt = "\n".join(f"{name}: {value}" for name, value in values.items())
        return {
            "hook_event_name": "subagentStart",
            "parent_conversation_id": parent,
            "subagent_type": agent_type,
            "subagent_model": model,
            "prompt": prompt,
        }

    def admit(self, root, event, now=None, counter_dir=None):
        with (
            patch.object(workflow_guard, "_repo_head", return_value=self.HEAD),
            patch.object(
                workflow_guard,
                "_latest_handoff_commit",
                return_value=self.HEAD,
            ),
        ):
            return workflow_guard.admit(
                event,
                repo_root=root,
                now=now or self.NOW,
                counter_dir=counter_dir or root / "counters",
            )

    def test_correctly_bound_implementation_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.write_repo(directory)
            result = self.admit(root, self.event())
        self.assertEqual(result, {"permission": "allow"})

    def test_copied_metadata_from_different_parent_conversation_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.write_repo(directory)
            result = self.admit(
                root,
                self.event(parent="different-parent-conversation"),
            )
        self.assertEqual(result["permission"], "deny")
        self.assertIn("parent conversation ID", result["user_message"])

    def test_parent_conversation_identity_is_required_and_well_formed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.write_repo(directory)
            missing = self.event()
            del missing["parent_conversation_id"]
            missing_result = self.admit(root, missing)
            malformed_root = self.write_repo(
                directory,
                control_parent_conversation_id=" ",
            )
            malformed_result = self.admit(malformed_root, self.event())
        self.assertEqual(missing_result["permission"], "deny")
        self.assertIn("parent conversation ID", missing_result["user_message"])
        self.assertEqual(malformed_result["permission"], "deny")
        self.assertIn("control parent conversation ID", malformed_result["user_message"])

    def test_unmanaged_agent_is_allowed_without_workflow_state(self) -> None:
        result = workflow_guard.admit({"subagent_type": "explore"})
        self.assertEqual(result, {"permission": "allow"})

    def test_handoff_not_updated_in_current_head_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.write_repo(directory)
            with (
                patch.object(
                    workflow_guard,
                    "_repo_head",
                    return_value="current-head",
                ),
                patch.object(
                    workflow_guard,
                    "_latest_handoff_commit",
                    return_value="older-head",
                ),
            ):
                result = workflow_guard.admit(
                    self.event(),
                    repo_root=root,
                    now=self.NOW,
                    counter_dir=root / "counters",
                )
        self.assertEqual(result["permission"], "deny")
        self.assertIn("not updated in the current Git head", result["user_message"])

    def test_missing_or_mismatched_prompt_metadata_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.write_repo(directory)
            missing = self.event(
                fields={
                    "Control-Owner": None,
                }
            )
            missing["prompt"] = "\n".join(
                line
                for line in missing["prompt"].splitlines()
                if not line.startswith("Control-Owner:")
            )
            mismatch = self.event(fields={"Stage-Revision": "stage-2"})
            self.assertEqual(
                self.admit(root, missing)["permission"],
                "deny",
            )
            self.assertEqual(
                self.admit(root, mismatch)["permission"],
                "deny",
            )

    def test_wrong_model_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.write_repo(directory)
            result = self.admit(
                root,
                self.event(model="cursor-gpt-5.6-terra-high"),
            )
        self.assertEqual(result["permission"], "deny")
        self.assertIn("model", result["user_message"])

    def test_duplicate_turn_kind_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.write_repo(directory)
            first = self.admit(root, self.event())
            second = self.admit(root, self.event())
        self.assertEqual(first, {"permission": "allow"})
        self.assertEqual(second["permission"], "deny")
        self.assertIn("already consumed", second["user_message"])

    def test_concurrent_identical_starts_reserve_only_one_turn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.write_repo(directory)
            counter_dir = root / "counters"
            context = multiprocessing.get_context("spawn")
            barrier = context.Barrier(3)
            result_queue = context.Queue()
            workers = [
                context.Process(
                    target=_concurrent_admission_worker,
                    args=(
                        str(root),
                        str(counter_dir),
                        self.event(),
                        barrier,
                        result_queue,
                    ),
                )
                for _ in range(2)
            ]
            for worker in workers:
                worker.start()
            barrier.wait(timeout=10)
            results = [result_queue.get(timeout=15) for _ in workers]
            for worker in workers:
                worker.join(timeout=15)
            self.assertTrue(
                all(not worker.is_alive() for worker in workers),
                "concurrent admission worker did not terminate",
            )
        self.assertCountEqual(
            [result.get("permission") for result in results],
            ["allow", "deny"],
        )
        self.assertFalse(any("worker_error" in result for result in results))

    def test_product_blocked_stage_is_denied_before_worker_iteration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.write_repo(
                directory,
                product_precondition="failed",
                failure_class="product_state",
            )
            result = self.admit(
                root,
                self.event(fields={"Product-Precondition": "failed"}),
            )
        self.assertEqual(result["permission"], "deny")
        self.assertIn("product precondition", result["user_message"])

    def test_conversation_and_stage_limits_are_denied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.write_repo(directory)
            counter_dir = root / "counters"
            counter_path = workflow_guard._counter_path(
                root, WORKFLOW_PARENT_CONVERSATION_ID, counter_dir
            )
            workflow_guard._atomic_write_json(
                counter_path,
                {
                    "schema_version": 1,
                    "parent_conversation_id": WORKFLOW_PARENT_CONVERSATION_ID,
                    "managed_turns": 8,
                    "stage_revisions": [],
                    "stages": {},
                },
            )
            conversation_result = self.admit(root, self.event())
            workflow_guard._atomic_write_json(
                counter_path,
                {
                    "schema_version": 1,
                    "parent_conversation_id": WORKFLOW_PARENT_CONVERSATION_ID,
                    "managed_turns": 1,
                    "stage_revisions": ["stage-a", "stage-b", "stage-c"],
                    "stages": {
                        "stage-a": {"turns": {}},
                        "stage-b": {"turns": {}},
                        "stage-c": {"turns": {}},
                    },
                },
            )
            stage_result = self.admit(root, self.event())
        self.assertIn("managed-turn limit", conversation_result["user_message"])
        self.assertIn("stage-revision limit", stage_result["user_message"])

    def test_early_user_continuation_does_not_satisfy_visible_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.write_repo(
                directory,
                user_continuation_utc="2026-08-17T00:30:00Z",
            )
            result = self.admit(
                root,
                self.event(),
                now=datetime(2026, 8, 17, 1, 0, 1, tzinfo=timezone.utc),
            )
        self.assertEqual(result["permission"], "deny")
        self.assertIn("visible 60-minute checkpoint", result["user_message"])

    def test_visible_checkpoint_allows_between_sixty_and_ninety_minutes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.write_repo(
                directory,
                continuation_checkpoint_utc="2026-08-17T00:45:00Z",
            )
            result = self.admit(
                root,
                self.event(),
                now=datetime(2026, 8, 17, 1, 1, tzinfo=timezone.utc),
            )
        self.assertEqual(result, {"permission": "allow"})

    def test_ninety_minute_checkpoint_requires_both_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.write_repo(
                directory,
                continuation_checkpoint_utc="2026-08-17T01:00:00Z",
            )
            expired = self.admit(
                root,
                self.event(),
                now=datetime(2026, 8, 17, 1, 31, tzinfo=timezone.utc),
            )
            root = self.write_repo(
                directory,
                continuation_checkpoint_utc="2026-08-17T01:00:00Z",
                user_continuation_utc="2026-08-17T01:30:00Z",
            )
            continued = self.admit(
                root,
                self.event(),
                now=datetime(2026, 8, 17, 1, 31, tzinfo=timezone.utc),
            )
        self.assertIn("90-minute continuation", expired["user_message"])
        self.assertEqual(continued, {"permission": "allow"})


class BlueStacksOperatorContractTests(unittest.TestCase):
    def test_bluestacks_commands_are_narrow_and_parseable(self) -> None:
        for argv, command in (
            (["bluestacks", "preflight"], "preflight"),
            (
                [
                    "bluestacks",
                    "run-flow",
                    "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION",
                    "--live",
                ],
                "run-flow",
            ),
            (["bluestacks", "verify-flow", ".local-captures/example"], "verify-flow"),
            (["bluestacks", "recover-home"], "recover-home"),
        ):
            parsed = pnsctl.parser().parse_args(argv)
            self.assertEqual(parsed.command, "bluestacks")
            self.assertEqual(parsed.bluestacks_command, command)
            self.assertFalse(hasattr(parsed, "x"))
            self.assertFalse(hasattr(parsed, "tap"))
            self.assertFalse(hasattr(parsed, "swipe"))

    def test_run_flow_dry_run_never_touches_runtime(self) -> None:
        with (
            patch("scripts.pnsctl._load_flow_delivery_state") as state,
            patch("scripts.pnsctl.subprocess.run") as run,
        ):
            payload = json.loads(
                pnsctl.bluestacks_run_flow(
                    "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION",
                    live=False,
                )
            )
        self.assertEqual(payload["status"], "dry_run")
        self.assertFalse(payload["dispatch"])
        state.assert_not_called()
        run.assert_not_called()

    def test_contract_fixes_private_serial_geometry_and_artifact_root(self) -> None:
        self.assertEqual(pnsctl.BLUESTACKS_SERIAL, "emulator-5554")
        self.assertEqual(
            (pnsctl.BLUESTACKS_NATIVE_WIDTH, pnsctl.BLUESTACKS_NATIVE_HEIGHT),
            (800, 1280),
        )
        self.assertEqual(
            pnsctl.BLUESTACKS_ARTIFACT_ROOT,
            ROOT / ".local-captures" / "flow-delivery",
        )
        source = (ROOT / "scripts" / "pnsctl.py").read_text(encoding="utf-8")
        self.assertNotIn('add_argument("--coordinate', source)
        self.assertNotIn('add_argument("--tap', source)
        self.assertNotIn('add_argument("--swipe', source)


if __name__ == "__main__":
    unittest.main()
