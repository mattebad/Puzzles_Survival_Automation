from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
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
            "SUPPLY-DEPOT-BLUESTACKS-INTEGRATION",
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
            "BIOENHANCER-FREE-RESEARCH-BLUESTACKS-INTEGRATION",
            "VIP-GET-PTS-POPUP-DISMISSAL",
        ]
        self.assertEqual([item["flow_id"] for item in self.queue["flows"]], expected)
        counts = {
            status: sum(item["status"] == status for item in self.queue["flows"])
            for status in control.QUEUE_STATUSES
        }
        self.assertIn(counts["active"], (0, 1))
        self.assertEqual(counts["ready"] + counts["active"], 0)
        self.assertEqual(counts["blocked"], 15)
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

    def test_run_flow_live_is_retired_before_observation_or_admission(self) -> None:
        with (
            patch("scripts.pnsctl._load_bluestacks_flow_registry") as registry,
            patch("scripts.pnsctl._load_flow_delivery_state") as state,
            patch("scripts.pnsctl._development_runtime_observation") as observe,
        ):
            with self.assertRaisesRegex(
                pnsctl.OperatorError,
                "legacy bluestacks run-flow --live is retired",
            ):
                pnsctl.bluestacks_run_flow(
                    "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION",
                    live=True,
                )
        registry.assert_not_called()
        state.assert_not_called()
        observe.assert_not_called()

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
