from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from scripts import pnsctl
from tasks.catalog import CATALOG_PATH, catalog_summary, load_catalog, objective_for_text
from tasks.daily_quest import AllianceHelpHandler, AllianceHelpObservation
from tasks.profile import HELP_ALL_ACTION, INDIVIDUAL_HELP_ACTION


class CatalogTests(unittest.TestCase):
    def test_retained_inventory_is_durable_and_complete(self):
        catalog = load_catalog()
        self.assertEqual(catalog_summary()["count"], len(catalog))
        self.assertEqual(objective_for_text("  Help   allies ").objective_key, "help_allies")
        self.assertEqual(objective_for_text("Gather Gas").progress_format, "current/1500")
        self.assertIsNone(objective_for_text("Gathered Food"))

    def test_disabled_consequences_are_explicit(self):
        by_key = {item.objective_key: item for item in load_catalog()}
        self.assertEqual(by_key["help_allies"].policy_mode, "supervised_zero_cost")
        self.assertEqual(by_key["help_allies"].implementation_status, "LIVE_VALIDATED")
        self.assertEqual(by_key["buy_box"].implementation_status, "DISABLED_POLICY")
        self.assertEqual(by_key["gather_wood"].consequence_class, "spend_or_strategic")

    def test_loader_rejects_row_without_selected_daily_provenance(self):
        raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        raw["objectives"][0]["evidence_provenance"] = "planning-document.md"
        with patch("tasks.catalog._load_raw", return_value=raw):
            with self.assertRaisesRegex(ValueError, "selected-Daily provenance"):
                load_catalog()


class OperatorCliTests(unittest.TestCase):
    def test_required_operator_subcommands_exist(self):
        for name in (
            "preflight", "worker-start", "worker-status", "worker-stop", "adb-start", "launch",
            "capture", "observe", "navigate", "run-task", "test-focused", "test-full", "validate",
            "preserve-evidence", "cleanup",
        ):
            extra = []
            if name == "navigate":
                extra = ["--step", "home-quest"]
            elif name == "run-task":
                extra = ["--task", "alliance-help"]
            elif name == "preserve-evidence":
                extra = ["--destination", "/tmp/pnsctl-test-evidence"]
            parsed = pnsctl.parser().parse_args([name] + extra)
            self.assertEqual(parsed.command, name)
        self.assertEqual(
            pnsctl.parser().parse_args(["run-task", "--task", "praise"]).task,
            "praise",
        )
        self.assertEqual(
            pnsctl.parser().parse_args(["run-task", "--task", "praise-route-evidence"]).task,
            "praise-route-evidence",
        )
        self.assertEqual(
            pnsctl.parser().parse_args(["run-task", "--task", "praise-leaderboard-evidence"]).task,
            "praise-leaderboard-evidence",
        )
        self.assertEqual(
            pnsctl.parser().parse_args(["run-task", "--task", "personal-might-claim"]).task,
            "personal-might-claim",
        )

    def test_worker_command_is_private_and_bounded(self):
        cfg = pnsctl.OperatorConfig()
        with patch("scripts.pnsctl.sync_workspace"), patch("scripts.pnsctl.run_remote", return_value="") as remote:
            pnsctl.worker_start(cfg)
        command = remote.call_args.args[1]
        self.assertIn("--user 65534:65534", command)
        self.assertIn("--read-only", command)
        self.assertIn("--tmpfs /tmp:rw,noexec,nosuid,size=256m", command)
        self.assertIn("--network host", command)
        self.assertNotIn(":5037", command)

    def test_workspace_sync_includes_praise_reference_assets(self):
        cfg = pnsctl.OperatorConfig()
        with patch("scripts.pnsctl.run_remote", return_value=""), patch(
            "scripts.pnsctl.run_pscp"
        ) as transfer:
            pnsctl.sync_workspace(cfg)
        transferred_sources = {
            source
            for call in transfer.call_args_list
            for source in call.args[1]
        }
        for asset in pnsctl.PRAISE_REFERENCE_ASSETS:
            self.assertIn(str(cfg.repo_root / asset), transferred_sources)

    def test_navigation_runs_from_synced_workspace(self):
        cfg = pnsctl.OperatorConfig()
        with patch("scripts.pnsctl.run_remote", return_value="") as remote:
            pnsctl.navigate(cfg, "quest-daily")
        command = remote.call_args.args[1]
        self.assertIn("-e PYTHONPATH=/workspace", command)
        self.assertIn("-w /workspace", command)
        self.assertIn("scripts/mvp_quest_to_claim.py", command)
        self.assertIn("/evidence/actions-nav-quest-daily-", command)
        self.assertNotIn("--database /evidence/actions.sqlite3", command)

    def test_daily_scroll_uses_bounded_swipe_navigation(self):
        cfg = pnsctl.OperatorConfig()
        with patch("scripts.pnsctl.run_remote", return_value="") as remote:
            pnsctl.navigate(cfg, "daily-scroll-up")
        command = remote.call_args.args[1]
        self.assertIn("--source-mode daily", command)
        self.assertIn("--expected-mode daily", command)
        self.assertIn("--semantic-action SCROLL_DAILY_QUEST", command)
        self.assertIn("--input-kind swipe --swipe 400 1000 400 500 350", command)
        self.assertNotIn("--consequence spend_or_strategic", command)

    def test_credentials_are_redacted_from_operator_output(self):
        rendered = " ".join(pnsctl.redact_argv(["plink", "-pw", "secret", "root@nas.local", "date"]))
        self.assertNotIn("secret", rendered)
        self.assertIn("<process-only-password>", rendered)

    def test_test_command_quotes_the_complete_shell_program(self):
        cfg = pnsctl.OperatorConfig()
        with patch("scripts.pnsctl.run_remote", return_value="") as remote:
            pnsctl.test_command(cfg, focused=False)
        command = remote.call_args.args[1]
        expected = pnsctl.quote("python3 -m unittest discover -s tests -p 'test_*.py' 2>&1")
        self.assertIn("sh -lc " + expected, command)
        self.assertEqual(command.count("python3 -m unittest discover"), 1)

    def test_praise_task_uses_checked_in_adapter(self):
        cfg = pnsctl.OperatorConfig()
        with patch("scripts.pnsctl.run_remote", return_value="") as remote:
            pnsctl.run_task(cfg, "praise")
        command = remote.call_args.args[1]
        self.assertIn("personal_might_praise_live.py", command)
        self.assertIn("--daily-reference", command)
        self.assertNotIn("input tap", command)

    def test_personal_might_claim_uses_explicit_claim_only_mode(self):
        cfg = pnsctl.OperatorConfig()
        with patch("scripts.pnsctl.run_remote", return_value="") as remote:
            pnsctl.run_task(cfg, "personal-might-claim")
        command = remote.call_args.args[1]
        self.assertIn("personal_might_praise_live.py", command)
        self.assertIn("--claim-only", command)

    def test_route_evidence_task_stops_before_praise(self):
        cfg = pnsctl.OperatorConfig()
        with patch("scripts.pnsctl.run_remote", return_value="") as remote:
            pnsctl.run_task(cfg, "praise-route-evidence")
        command = remote.call_args.args[1]
        self.assertIn("personal_might_praise_live.py", command)
        self.assertIn("--navigation-evidence-only", command)

    def test_leaderboard_evidence_task_stops_before_praise(self):
        cfg = pnsctl.OperatorConfig()
        with patch("scripts.pnsctl.run_remote", return_value="") as remote:
            pnsctl.run_task(cfg, "praise-leaderboard-evidence")
        self.assertIn("--leaderboard-evidence-only", remote.call_args.args[1])


class HelpAllContractTests(unittest.TestCase):
    def _observation(self, **changes):
        values = dict(
            screen_state="SPEEDUP_HELP", objective_name="Help allies", current_progress=0,
            required_progress=10, target_identity=HELP_ALL_ACTION.name, target_roi=HELP_ALL_ACTION.roi,
            zero_cost_evidence=True, available_request_count=1, help_all_visible=True,
            request_controls_count=1,
        )
        values.update(changes)
        return AllianceHelpObservation(**values)

    def test_upper_button_is_individual_help_not_help_all(self):
        self.assertTrue(INDIVIDUAL_HELP_ACTION.roi[0] <= 641 < INDIVIDUAL_HELP_ACTION.roi[2])
        self.assertTrue(INDIVIDUAL_HELP_ACTION.roi[1] <= 302 < INDIVIDUAL_HELP_ACTION.roi[3])
        self.assertFalse(HELP_ALL_ACTION.roi[1] <= 302 < HELP_ALL_ACTION.roi[3])
        old = self._observation(target_identity=INDIVIDUAL_HELP_ACTION.name,
                                target_roi=INDIVIDUAL_HELP_ACTION.roi,
                                help_all_visible=False, individual_help_visible=True)
        self.assertTrue(AllianceHelpHandler.authorizeable(old))
        self.assertEqual(AllianceHelpHandler.transaction_spec(old).action_kind, "ALLIANCE_HELP_ONE")

    def test_help_all_disappearance_is_a_positive_postcondition(self):
        before = self._observation()
        after = self._observation(help_all_visible=False, available_request_count=0, request_controls_count=0, empty_state=True)
        self.assertTrue(AllianceHelpHandler.postcondition_verified(before, after))
        self.assertEqual(AllianceHelpHandler.perform_one_pulse(before, after).outcome.value, "progress")

    def test_help_all_requires_zero_cost_and_exact_target(self):
        self.assertTrue(AllianceHelpHandler.authorizeable(self._observation()))
        self.assertFalse(AllianceHelpHandler.authorizeable(self._observation(zero_cost_evidence=False)))
        self.assertFalse(AllianceHelpHandler.authorizeable(self._observation(help_all_visible=False)))


if __name__ == "__main__":
    unittest.main()
