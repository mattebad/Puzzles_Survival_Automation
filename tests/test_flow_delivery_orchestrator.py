from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from scripts import flow_delivery_control as control
from scripts import pnsctl


ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "tasks" / "flow_delivery_queue.json"
POLICY_PATH = ROOT / "tasks" / "flow_delivery_product_policy.json"


class FlowDeliveryQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        self.policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    def test_queue_and_policy_schema_are_valid(self) -> None:
        control.validate_queue(self.queue)
        control.validate_policy(self.policy)
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
        broken["flows"][1]["status"] = "active"
        broken["active_flow_id"] = broken["flows"][0]["flow_id"]
        with self.assertRaisesRegex(control.FlowDeliveryError, "exactly one or zero"):
            control.validate_queue(broken)

    def test_deterministic_selection_and_active_resume(self) -> None:
        controller = control.FlowDeliveryController()
        first = controller.select_next(self.queue)
        if self.queue.get("active_flow_id"):
            self.assertEqual(first["flow_id"], self.queue["active_flow_id"])
        else:
            expected = min(
                (flow for flow in self.queue["flows"] if flow["status"] == "ready"),
                key=lambda flow: (flow["priority"], flow["flow_id"]),
            )
            self.assertEqual(first["flow_id"], expected["flow_id"])
        active = deepcopy(self.queue)
        for flow in active["flows"]:
            if flow["status"] == "active":
                flow["status"] = "ready"
                flow["last_completed_stage"] = "selected"
        active["flows"][4]["status"] = "active"
        active["flows"][4]["last_completed_stage"] = "implementation"
        active["active_flow_id"] = active["flows"][4]["flow_id"]
        self.assertEqual(
            controller.select_next(active)["flow_id"],
            "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION",
        )

    def test_blocked_and_policy_disabled_flows_are_skipped(self) -> None:
        queue = deepcopy(self.queue)
        queue["flows"][0]["status"] = "blocked"
        queue["flows"][0]["blocked_reason"] = "test blocker"
        queue["flows"][1]["status"] = "blocked"
        queue["flows"][1]["product_policy_status"] = "prohibited"
        queue["flows"][1]["blocked_reason"] = "test policy"
        selected = control.FlowDeliveryController().select_next(queue)
        expected = min(
            (flow for flow in queue["flows"] if flow["status"] == "ready"),
            key=lambda flow: (flow["priority"], flow["flow_id"]),
        )
        self.assertEqual(selected["flow_id"], expected["flow_id"])

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
            "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION",
            "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION",
            "NOVA-PRAISE-HOME-ATLAS-MIGRATION",
            "NOAHS-TAVERN-HOME-ATLAS-MIGRATION",
            "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION",
            "TROOP-TRAINING-VERIFIED-NAVIGATION-CONVERGENCE",
            "SUPPLY-DEPOT-LEGACY-ADAPTER-RETIREMENT",
            "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
            "DAILY-MILESTONE-CLAIM-BLUESTACKS-INTEGRATION",
            "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION",
            "NANOWEAPON-BLUESTACKS-INTEGRATION",
            "RECRUITMENT-BLUESTACKS-INTEGRATION",
            "WORLD-MAP-NAVIGATION-FOUNDATION",
            "GATHERING-BLUESTACKS-INTEGRATION",
            "ZOMBIE-LAIR-BLUESTACKS-INTEGRATION",
        ]
        self.assertEqual([item["flow_id"] for item in self.queue["flows"]], expected)
        counts = {
            status: sum(item["status"] == status for item in self.queue["flows"])
            for status in control.QUEUE_STATUSES
        }
        self.assertIn(counts["active"], (0, 1))
        # Campaign, Ultimate Challenge, Nova, and two Daily claim flows are blocked.
        self.assertEqual(counts["ready"] + counts["active"], 6)
        self.assertEqual(counts["blocked"], 5)
        self.assertEqual(counts["needs_product_decision"], 4)

    def test_campaign_destinations_are_exact_and_legacy_pan_is_recorded(self) -> None:
        campaign = self.queue["flows"][0]
        scope = campaign["live_validation_scope"]
        for destination in ("1-20-9", "1-15-9", "2-2-9"):
            self.assertIn(destination, scope)
            self.assertIn(destination, campaign["supported_story_destinations"])
        for rejected in ("1-2-9", "ultimate-challenge"):
            self.assertNotIn(rejected, campaign["supported_story_destinations"])
            self.assertIn(rejected, campaign["rejected_destinations"])
        self.assertNotIn("1-2-9", scope)
        self.assertNotIn("ultimate-challenge", scope)
        campaign_source = (ROOT / "scripts" / "bluestacks_campaign_ap.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("--stage", campaign_source)
        self.assertIn("parse_supported_campaign_story_destination", campaign_source)
        runtime_source = (
            ROOT / "tasks" / "campaign_auto_battle_runtime.py"
        ).read_text(encoding="utf-8")
        self.assertIn("HOME_PAN_GESTURES", runtime_source)

    def test_ultimate_challenge_blocked_metadata_is_retained(self) -> None:
        ultimate = self.queue["flows"][1]
        self.assertEqual(
            ultimate["flow_id"],
            "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION",
        )
        self.assertEqual(ultimate["status"], "blocked")
        self.assertEqual(ultimate["last_completed_stage"], "blocked")
        self.assertTrue(ultimate["blocked_reason"])
        self.assertEqual(ultimate["priority"], 15)
        self.assertEqual(ultimate["product_policy_status"], "navigation_only_validation")
        policy_ids = {item["policy_id"] for item in self.policy["policies"]}
        self.assertIn("ultimate-challenge-flow-separation", policy_ids)
        registry = json.loads(
            (ROOT / "tasks" / "flow_delivery_bluestacks_registry.json").read_text(
                encoding="utf-8"
            )
        )
        uc_registry = registry["flows"]["ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION"]
        self.assertEqual(uc_registry["consequence_class"], "navigation_only")
        self.assertEqual(
            uc_registry["runner"], "ultimate_challenge_navigation_only_runner"
        )
        self.assertTrue(
            (ROOT / "scripts" / "bluestacks_ultimate_challenge.py").is_file()
        )
        self.assertTrue(
            (ROOT / "scripts" / "flow_delivery_ultimate_challenge_bluestacks.py").is_file()
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
        queue.write_bytes(QUEUE_PATH.read_bytes())
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
                with self.assertRaisesRegex(control.FlowDeliveryError, "invalid stage transition"):
                    controller.record_stage(owner="parent", stage="implementation")
            self.assertEqual(controller.queue_path.read_bytes(), before)

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
                with self.assertRaisesRegex(control.FlowDeliveryError, "lease conflict"):
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
        source = (ROOT / "scripts" / "flow_delivery_control.py").read_text(encoding="utf-8")
        self.assertNotIn("runtime.tap", source)
        self.assertNotIn("runtime.swipe", source)
        self.assertNotIn("HD-Adb", source)
        self.assertIn('["rev-parse", "HEAD"]', source)


class FlowDeliveryCursorContractTests(unittest.TestCase):
    def test_custom_agents_are_unique_grok_high_and_single_writer(self) -> None:
        paths = sorted((ROOT / ".cursor" / "agents").glob("*.md"))
        self.assertEqual(
            [path.stem for path in paths],
            [
                "pns-evidence-reviewer",
                "pns-flow-implementer",
                "pns-flow-recon",
                "pns-flow-reviewer",
            ],
        )
        writable = []
        names = set()
        for path in paths:
            text = path.read_text(encoding="utf-8")
            name = re.search(r"(?m)^name:\s*(\S+)$", text).group(1)
            model = re.search(r"(?m)^model:\s*(\S+)$", text).group(1)
            readonly = re.search(r"(?m)^readonly:\s*(\S+)$", text).group(1)
            self.assertNotIn(name, names)
            names.add(name)
            self.assertEqual(model, "cursor-grok-4.5-high")
            if readonly == "false":
                writable.append(name)
            self.assertIn("invoke another subagent", text)
        self.assertEqual(writable, ["pns-flow-implementer"])

    def test_skill_names_only_allowlisted_subagents(self) -> None:
        skill = (
            ROOT / ".cursor" / "skills" / "pns-flow-delivery" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertNotRegex(skill, r"/pns-[a-z-]+")
        for agent in (
            "pns-flow-recon",
            "pns-flow-implementer",
            "pns-flow-reviewer",
            "pns-evidence-reviewer",
        ):
            self.assertIn(f"`{agent}`", skill)
        self.assertIn("native `Subagent`/`Task` tool", skill)
        self.assertIn("IDE_NATIVE_SUBAGENT_TOOL_UNAVAILABLE", skill)
        for built_in in ("generalPurpose", "/explore", "/shell"):
            self.assertNotIn(built_in, skill)

    def test_hook_is_scoped_and_uses_installed_schema_fields(self) -> None:
        hooks = json.loads((ROOT / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
        pre = hooks["hooks"]["preToolUse"][0]
        self.assertTrue(pre["failClosed"])
        self.assertEqual(pre.get("matcher"), "Task")
        start = hooks["hooks"]["subagentStart"][0]
        self.assertFalse(start["failClosed"])
        guard = (
            ROOT / ".cursor" / "hooks" / "pns_flow_subagent_guard.py"
        ).read_text(encoding="utf-8")
        self.assertIn("authorize_task_call", guard)
        self.assertIn("preToolUse", guard)
        self.assertIn("audit_only", guard)
        self.assertIn("delivery_lease_active()", guard)
        self.assertIn("Path(__file__).resolve().parents[2]", guard)
        self.assertNotIn("ROOT = Path.cwd()", guard)

    def test_hook_fails_closed_on_model_fallback_and_duplicate_writer(self) -> None:
        guard = (
            ROOT / ".cursor" / "hooks" / "pns_flow_subagent_guard.py"
        ).read_text(encoding="utf-8")
        self.assertIn("subagent routing state lock is unavailable", guard)
        self.assertIn("a writable PnS flow implementer marker remains unresolved", guard)
        self.assertIn("unapproved model is denied", guard)
        self.assertIn("audit_only", guard)
        for field in (
            "lease_owner",
            "lease_session",
            "parent_conversation_id",
            "active_flow",
            "subagent_id",
            "created_at",
        ):
            self.assertIn(f'"{field}"', guard)

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
            ROOT / ".cursor" / "agents" / "pns-flow-recon.md",
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
        self.assertIn(state["first_ready_flow"], handoff)
        self.assertNotIn("actions_already_performed", handoff)
        # Historical Ruins/troop handoff ledgers live in Git history, not the compact volatile handoff.


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
        with patch("scripts.pnsctl._load_flow_delivery_state") as state, patch(
            "scripts.pnsctl.subprocess.run"
        ) as run:
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
        self.assertNotIn("add_argument(\"--coordinate", source)
        self.assertNotIn("add_argument(\"--tap", source)
        self.assertNotIn("add_argument(\"--swipe", source)


if __name__ == "__main__":
    unittest.main()
