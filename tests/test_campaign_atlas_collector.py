from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from scripts import campaign_atlas_bluestacks
from tasks.campaign_atlas import (
    ACTIVATED_TRANSPORT_INPUT_CEILING,
    build_empty_activated_session_report,
)


class CampaignAtlasCollectorTests(unittest.TestCase):
    def test_dry_run_is_evidence_required_and_zero_input(self) -> None:
        payload = campaign_atlas_bluestacks.build_dry_run_payload()
        self.assertEqual(payload["disposition"], "evidence_required")
        self.assertFalse(payload["transport_dispatched"])
        self.assertEqual(payload["transport_input_count"], 0)
        self.assertEqual(payload["native_frames_acquired"], 0)
        self.assertEqual(payload["evidence_artifacts"], [])
        self.assertFalse(payload["atlas_created"])

    def test_cli_prints_only_offline_report(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            result = campaign_atlas_bluestacks.main(["dry-run"])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["transport_input_count"], 0)

    def test_cli_rejects_live_transport_options_on_dry_run(self) -> None:
        for option in ("--execute", "--serial", "--adb"):
            with self.subTest(option=option), redirect_stderr(StringIO()), self.assertRaises(
                SystemExit
            ):
                campaign_atlas_bluestacks.main(["dry-run", option])

    def test_collector_source_has_no_runtime_transport_imports(self) -> None:
        source = Path(campaign_atlas_bluestacks.__file__).read_text(encoding="utf-8")
        for forbidden in ("import subprocess", "ADBRunner", "LocalBlueStacksRuntime", "input tap"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_activated_contract_payload_matches_272_partitions(self) -> None:
        payload = campaign_atlas_bluestacks.build_activated_contract_payload()
        self.assertEqual(payload["contract_kind"], "activated")
        self.assertEqual(payload["maximum_transport_inputs"], ACTIVATED_TRANSPORT_INPUT_CEILING)
        self.assertEqual(payload["budget_partitions"]["edge_clamp"], 128)
        self.assertEqual(payload["budget_partitions"]["overlap"], 128)
        self.assertEqual(
            payload["budget_partitions"]["auxiliary_entry_difficulty_terminal_recovery"],
            16,
        )
        self.assertEqual(payload["budget_partitions"]["total"], 272)
        self.assertFalse(payload["transport_dispatched"])

    def test_activated_survey_readiness_is_zero_input_and_refuses_direct_execute(self) -> None:
        ready = campaign_atlas_bluestacks.build_activated_survey_readiness_payload()
        self.assertEqual(ready["disposition"], "evidence_required")
        self.assertEqual(ready["transport_input_count"], 0)
        self.assertIn("pnsctl.py", ready["live_interface"])
        blocked = campaign_atlas_bluestacks.build_activated_survey_readiness_payload(execute=True)
        self.assertEqual(blocked["disposition"], "blocked_fail_closed")
        self.assertFalse(blocked["transport_dispatched"])
        output = StringIO()
        with redirect_stdout(output):
            code = campaign_atlas_bluestacks.main(["activated-survey", "--execute"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["transport_dispatched"], False)

    def test_production_survey_call_graph_is_bound_to_checked_in_seams(self) -> None:
        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            production_survey_call_graph,
            SURVEY_RUNNER_ID,
            SURVEY_EVIDENCE_VALIDATOR_ID,
            SURVEY_RECOVERY_HANDLER_ID,
            assert_swipe_not_blind_retry,
            count_home_entry_transports,
            require_bound_survey_target,
            _failure_delivery_from_session,
            load_durable_survey_accounting,
        )
        from scripts import pnsctl
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace

        graph = production_survey_call_graph()
        self.assertEqual(
            graph["home_to_campaign_entry"],
            "scripts.home_atlas_bluestacks.run_verified_campaign_home_atlas_entry",
        )
        self.assertIn(SURVEY_RUNNER_ID, pnsctl._BLUESTACKS_FLOW_RUNNERS)
        self.assertIn(SURVEY_EVIDENCE_VALIDATOR_ID, pnsctl._BLUESTACKS_EVIDENCE_VALIDATORS)
        self.assertIn(SURVEY_RECOVERY_HANDLER_ID, pnsctl._BLUESTACKS_RECOVERY_HANDLERS)

        swipe = (400, 400, 400, 540, 350)
        with self.assertRaises(RuntimeError):
            assert_swipe_not_blind_retry(
                swipe=swipe, last_swipe=swipe, prior_progress_proven=False
            )
        assert_swipe_not_blind_retry(
            swipe=swipe, last_swipe=swipe, prior_progress_proven=True
        )

        self.assertEqual(
            count_home_entry_transports(
                {
                    "status": "opened",
                    "records": [
                        {"disposition": "pan"},
                        {"disposition": "pan"},
                        {"disposition": "bind"},
                        {"disposition": "complete"},
                    ],
                }
            ),
            3,
        )

        recognition = SimpleNamespace(
            targets=(("campaign-tier-1", (415, 65, 515, 132)),)
        )
        with self.assertRaises(RuntimeError) as static_ctx:
            require_bound_survey_target(recognition, "campaign-tier-1")
        self.assertIn("static ROI", str(static_ctx.exception))
        measured = SimpleNamespace(targets=(("campaign-tier-1", (411, 70, 509, 130)),))
        self.assertEqual(
            require_bound_survey_target(measured, "campaign-tier-1"),
            (411, 70, 509, 130),
        )
        with self.assertRaises(RuntimeError):
            require_bound_survey_target(recognition, "campaign-tier-2")
        with self.assertRaises(RuntimeError):
            require_bound_survey_target(
                SimpleNamespace(targets=(("campaign-challenge-x", (1, 2, 3, 4)),)),
                "campaign-challenge-x",
            )

        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            # Pre-input failure: no accounting file => zero-input safe block.
            failure = _failure_delivery_from_session(
                session,
                serial="test",
                runtime_owner="owner",
                exc=RuntimeError("pre-input"),
            )
            self.assertEqual(failure["survey_result"]["navigation_inputs_used"], 0)
            self.assertFalse(failure["survey_result"]["transport_dispatched"])
            self.assertEqual(failure["terminal_runtime_state"], "safe_blocked_terminal")
            self.assertEqual(failure["survey_result"]["terminal"], "blocked_fail_closed")

            # Crash window: prepared without input_sent must reconcile unresolved.
            (session / "survey-lifecycle.jsonl").write_text(
                json.dumps(
                    {"lifecycle": "prepared", "input_ordinal": 1, "phase": "edge_top"}
                )
                + "\n",
                encoding="utf-8",
            )
            (session / "survey-accounting.json").write_text(
                json.dumps(
                    {
                        "transport_inputs_used": 0,
                        "transport_dispatched": False,
                        "unresolved": False,
                        "open_prepared": False,
                    }
                ),
                encoding="utf-8",
            )
            crash = _failure_delivery_from_session(
                session,
                serial="test",
                runtime_owner="owner",
                exc=RuntimeError("crash after prepare"),
            )
            self.assertTrue(crash["survey_result"]["unresolved"])
            self.assertTrue(crash["survey_result"]["transport_dispatched"])
            self.assertEqual(crash["terminal_runtime_state"], "unresolved_unsafe")
            self.assertEqual(crash["survey_result"]["terminal"], "unresolved")
            self.assertNotEqual(crash["terminal_runtime_state"], "safe_blocked_terminal")

            # Post-transport failure: durable accounting shows inputs used.
            (session / "survey-accounting.json").write_text(
                json.dumps(
                    {
                        "transport_inputs_used": 4,
                        "transport_dispatched": True,
                        "unresolved": True,
                    }
                ),
                encoding="utf-8",
            )
            (session / "survey-lifecycle.jsonl").write_text("", encoding="utf-8")
            frames = session / "runtime" / "frames"
            frames.mkdir(parents=True)
            (frames / "0001.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 24)
            failure2 = _failure_delivery_from_session(
                session,
                serial="test",
                runtime_owner="owner",
                exc=RuntimeError("post failed"),
            )
            self.assertEqual(failure2["survey_result"]["navigation_inputs_used"], 4)
            self.assertTrue(failure2["survey_result"]["transport_dispatched"])
            self.assertEqual(failure2["terminal_runtime_state"], "unresolved_unsafe")
            self.assertEqual(failure2["survey_result"]["terminal"], "unresolved")
            self.assertTrue(failure2["frames"])
            durable = load_durable_survey_accounting(session)
            self.assertEqual(durable["transport_inputs_used"], 4)

    def test_annotation_metadata_and_spatial_helpers(self) -> None:
        import tempfile
        from pathlib import Path
        import numpy as np
        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            _annotate_roi,
            _chapter_roi_from_recognition,
            _prison_trial_roi_from_hits,
        )

        digest = "a" * 64
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            frame = np.zeros((1280, 800, 3), dtype=np.uint8)
            rel = _annotate_roi(
                session,
                frame,
                label="campaign-chapter-7",
                roi=(100, 200, 180, 260),
                digest=digest,
            )
            meta_path = session / Path(rel).with_suffix(".json")
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self.assertEqual(meta["source_sha256"], digest)
            self.assertEqual(meta["roi"], [100, 200, 180, 260])
            self.assertTrue((session / rel).is_file())

        self.assertEqual(
            _chapter_roi_from_recognition(
                number=7,
                targets={"campaign-chapter-7": (10, 20, 30, 40)},
                hits={},
            ),
            (10, 20, 30, 40),
        )
        self.assertEqual(
            _chapter_roi_from_recognition(
                number=7,
                targets={},
                hits={"Chapter 7": (50, 60, 90, 100)},
            ),
            (50, 60, 90, 100),
        )
        self.assertIsNone(
            _chapter_roi_from_recognition(number=7, targets={}, hits={"Other": (1, 2, 3, 4)})
        )
        self.assertIsNone(
            _chapter_roi_from_recognition(number=7, targets={}, hits={"7": (1, 2, 3, 4)})
        )
        self.assertEqual(
            _prison_trial_roi_from_hits({"Prison Trial": (1, 2, 40, 20)}),
            (1, 2, 40, 20),
        )
        self.assertEqual(
            _prison_trial_roi_from_hits(
                {"Prison": (10, 20, 40, 40), "Trial": (45, 22, 80, 42)}
            ),
            (10, 20, 80, 42),
        )
        self.assertIsNone(_prison_trial_roi_from_hits({"Prison": (1, 2, 3, 4)}))
        # No invented closed claim helper: LoopClosureReport requires explicit closed flag.
        from tasks.campaign_atlas import LoopClosureReport as SchemaLoop

        report = SchemaLoop(closed=False, residual_px=12.5, supporting_frame_sha256=digest)
        self.assertFalse(report.closed)

    def test_verify_rejects_zero_input_scaffold_and_false_safe_terminal(self) -> None:
        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            verify_campaign_atlas_native_survey,
        )
        from scripts import pnsctl

        with self.assertRaises(pnsctl.OperatorError):
            verify_campaign_atlas_native_survey(
                {
                    "result": {
                        "flow_id": "CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION",
                        "terminal_runtime_state": "safe_blocked_terminal",
                        "survey_result": {
                            "terminal": "evidence_required",
                            "transport_dispatched": False,
                            "navigation_inputs_used": 0,
                            "maximum_navigation_inputs": 272,
                        },
                    },
                    "session_directory": ".",
                    "actions": 0,
                },
                {"flows": []},
                {},
            )

        # Preflight evidence_required with zero inputs is admissible for verify.
        verified = verify_campaign_atlas_native_survey(
            {
                "result": {
                    "flow_id": "CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION",
                    "terminal_runtime_state": "safe_blocked_terminal",
                    "survey_result": {
                        "terminal": "evidence_required",
                        "transport_dispatched": False,
                        "navigation_inputs_used": 0,
                        "maximum_navigation_inputs": 272,
                        "live_preflight_inadmissible": True,
                        "preflight_blockers": ["evidence_required: test"],
                    },
                },
                "session_directory": ".",
                "actions": 0,
            },
            {
                "flows": [
                    {"flow_id": "CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION"}
                ]
            },
            {},
        )
        self.assertTrue(verified["live_preflight_inadmissible"])

        # unresolved must not claim safe terminal
        with self.assertRaises(pnsctl.OperatorError):
            verify_campaign_atlas_native_survey(
                {
                    "result": {
                        "flow_id": "CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION",
                        "terminal_runtime_state": "safe_blocked_terminal",
                        "survey_result": {
                            "terminal": "unresolved",
                            "transport_dispatched": True,
                            "navigation_inputs_used": 2,
                            "maximum_navigation_inputs": 272,
                        },
                    },
                    "session_directory": ".",
                    "actions": 0,
                },
                {"flows": []},
                {},
            )

        # false transport_dispatched with zero inputs on blocked path
        with self.assertRaises(pnsctl.OperatorError):
            verify_campaign_atlas_native_survey(
                {
                    "result": {
                        "flow_id": "CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION",
                        "terminal_runtime_state": "safe_blocked_terminal",
                        "survey_result": {
                            "terminal": "blocked_fail_closed",
                            "transport_dispatched": True,
                            "navigation_inputs_used": 0,
                            "maximum_navigation_inputs": 272,
                        },
                    },
                    "session_directory": ".",
                    "actions": 0,
                },
                {"flows": []},
                {},
            )

    def test_no_static_roi_fallback_imports_in_runner(self) -> None:
        from pathlib import Path
        import scripts.flow_delivery_campaign_atlas_bluestacks as mod

        source = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("CAMPAIGN_EXIT_ROI", source)
        self.assertNotIn("TIER_ONE_ROI", source)
        self.assertNotIn("TIER_TWO_ROI", source)
        self.assertNotIn("overlap_ratio >= 0.2", source)
        self.assertNotIn("closed=True", source)
        self.assertIn("SafeActionExecutor", source)
        self.assertIn("reject_direct_survey_transport", source)
        self.assertIn("live_preflight_inadmissible", source)

    def test_safe_action_executor_is_action_authority_not_direct_runtime(self) -> None:
        from pathlib import Path
        import scripts.flow_delivery_campaign_atlas_bluestacks as mod

        source = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertIn("self._execute_via_safe_action", source)
        self.assertIn("authority\": \"SafeActionExecutor\"", source)
        # Direct swipe/tap remain only inside sealed transport callbacks.
        self.assertIn("reject_direct_survey_transport(authorized_token=_SURVEY_TRANSPORT_SEAL)", source)

    def test_preflight_blocks_live_survey_before_input(self) -> None:
        import tempfile
        from pathlib import Path
        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            run_bounded_campaign_atlas_survey,
        )
        from tasks.campaign_atlas import live_survey_preflight_is_admissible

        self.assertFalse(live_survey_preflight_is_admissible())
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "survey"
            session.mkdir()
            delivery = run_bounded_campaign_atlas_survey(
                session=session,
                adb="adb",
                serial="serial",
                runtime_owner="owner",
            )
            self.assertEqual(delivery["survey_result"]["terminal"], "evidence_required")
            self.assertTrue(delivery["survey_result"]["live_preflight_inadmissible"])
            self.assertFalse(delivery["survey_result"]["transport_dispatched"])
            self.assertEqual(delivery["survey_result"]["navigation_inputs_used"], 0)
            self.assertTrue((session / "retained-frame-classification.json").is_file())
            blockers = delivery["survey_result"]["preflight_blockers"]
            self.assertTrue(any("overlap_association" in item for item in blockers))
            self.assertTrue(any("static_rois" in item for item in blockers))
            self.assertTrue(any("successor_reconciliation" in item for item in blockers))

    def test_overlap_screen_revalidation_helper_is_present(self) -> None:
        from pathlib import Path
        import scripts.flow_delivery_campaign_atlas_bluestacks as mod

        source = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertIn("TIER_MAP required before difficulty comparison", source)
        self.assertIn("left TIER_MAP during", source)
        self.assertIn("no overlap budget spent", source)

    def test_validate_session_accepts_empty_activated_report(self) -> None:
        report = build_empty_activated_session_report(
            session_id="campaign-atlas-collector-test",
            created_at_utc="2026-07-23T21:00:00Z",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "survey-session-report.json"
            path.write_text(json.dumps(report.to_dict()), encoding="utf-8")
            payload = campaign_atlas_bluestacks.validate_session_payload(path)
        self.assertEqual(payload["status"], "validated")
        self.assertEqual(payload["transport_inputs_used"], 0)
        self.assertEqual(payload["maximum_transport_inputs"], 272)


if __name__ == "__main__":
    unittest.main()
