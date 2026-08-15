from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import hashlib
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
        self.assertEqual(
            graph["home_zoom_recovery"],
            "scripts.flow_delivery_campaign_atlas_bluestacks.recover_home_zoom_before_campaign_entry",
        )
        self.assertEqual(
            graph["home_zoom_driver"],
            "scripts.home_atlas_bluestacks.BlueStacksLocalizeFirstHomeDriver",
        )
        self.assertEqual(
            graph["home_zoom_transport"],
            "scripts.home_atlas_bluestacks.ScrcpyMotionEventZoomTransport",
        )
        self.assertIn("NavigationGuardedRuntime.dispatch_zoom_out", graph["home_zoom_firewall"])
        self.assertEqual(
            graph["vip_reset_dismiss"],
            "scripts.flow_delivery_campaign_atlas_bluestacks.dismiss_campaign_vip_reset_popup",
        )
        self.assertEqual(
            graph["vip_reset_recognizer"],
            "scripts.personal_might_praise_live.recognize_reset_popup",
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

        with self.assertRaises(RuntimeError):
            require_bound_survey_target(
                SimpleNamespace(targets=(("campaign-challenge-x", (1, 2, 3, 4)),)),
                "campaign-challenge-x",
                frame=None,
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

            # Reconciled prior transport + later zero-input exception => safe failed terminal.
            (session / "survey-accounting.json").write_text(
                json.dumps(
                    {
                        "transport_inputs_used": 1,
                        "transport_dispatched": True,
                        "unresolved": False,
                        "open_prepared": False,
                    }
                ),
                encoding="utf-8",
            )
            (session / "survey-lifecycle.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "lifecycle": "prepared",
                                "input_ordinal": 1,
                                "phase": "home_zoom",
                            }
                        ),
                        json.dumps(
                            {
                                "lifecycle": "input_sent",
                                "input_ordinal": 1,
                                "phase": "home_zoom",
                            }
                        ),
                        json.dumps(
                            {
                                "lifecycle": "terminal",
                                "input_ordinal": 1,
                                "phase": "home_zoom",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            frames = session / "runtime" / "frames"
            frames.mkdir(parents=True)
            (frames / "0001.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 24)
            reconciled = _failure_delivery_from_session(
                session,
                serial="test",
                runtime_owner="owner",
                exc=RuntimeError("later zero-input exception"),
            )
            self.assertEqual(reconciled["survey_result"]["navigation_inputs_used"], 1)
            self.assertTrue(reconciled["survey_result"]["transport_dispatched"])
            self.assertFalse(reconciled["survey_result"]["unresolved"])
            self.assertFalse(reconciled["survey_result"]["open_prepared"])
            self.assertEqual(reconciled["terminal_runtime_state"], "safe_blocked_terminal")
            self.assertEqual(reconciled["survey_result"]["terminal"], "blocked_fail_closed")
            self.assertEqual(reconciled["status"], "failed")
            self.assertTrue(reconciled["frames"])

            # True durable unresolved after transport => unresolved_unsafe.
            (session / "survey-accounting.json").write_text(
                json.dumps(
                    {
                        "transport_inputs_used": 4,
                        "transport_dispatched": True,
                        "unresolved": True,
                        "open_prepared": False,
                    }
                ),
                encoding="utf-8",
            )
            (session / "survey-lifecycle.jsonl").write_text("", encoding="utf-8")
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

    def test_measured_exit_at_canonical_hud_box_is_accepted(self) -> None:
        """Provenance wins: template match at CAMPAIGN_EXIT_ROI must bind."""

        import cv2
        import numpy as np
        from types import SimpleNamespace
        from scripts.flow_delivery_campaign_atlas_bluestacks import require_bound_survey_target
        from tasks.campaign_auto_battle_vision import ASSET_ROOT, CAMPAIGN_EXIT_ROI
        from tasks.campaign_atlas_vision import (
            COMPILE_TIME_STATIC_SURVEY_TARGET_ROIS,
            is_compile_time_static_survey_roi,
            require_measured_nonstatic_survey_target,
        )

        template = cv2.imread(str(ASSET_ROOT / "campaign_exit.png"), cv2.IMREAD_COLOR)
        self.assertIsNotNone(template)
        assert template is not None
        left, top, right, bottom = CAMPAIGN_EXIT_ROI
        self.assertEqual(template.shape[1], right - left)
        self.assertEqual(template.shape[0], bottom - top)

        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        frame[top:bottom, left:right] = template
        bound = require_bound_survey_target(
            SimpleNamespace(targets=()),
            "campaign-exit-base",
            frame=frame,
        )
        self.assertEqual(bound, CAMPAIGN_EXIT_ROI)
        self.assertTrue(is_compile_time_static_survey_roi("campaign-exit-base", bound))

        # Recognizer-only / no-frame static fallback remains rejected.
        with self.assertRaises(RuntimeError) as no_frame:
            require_bound_survey_target(
                SimpleNamespace(targets=(("campaign-exit-base", CAMPAIGN_EXIT_ROI),)),
                "campaign-exit-base",
                frame=None,
            )
        self.assertIn("current native frame is required", str(no_frame.exception))
        for identity, roi in COMPILE_TIME_STATIC_SURVEY_TARGET_ROIS.items():
            with self.subTest(identity=identity):
                with self.assertRaises(RuntimeError) as static_ctx:
                    require_measured_nonstatic_survey_target(
                        SimpleNamespace(targets=((identity, roi),)),
                        identity,
                    )
                self.assertIn("static ROI", str(static_ctx.exception))

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
        self.assertIn("loop_closure_accepted", source)
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

    def test_preflight_is_admissible_after_gate_closure(self) -> None:
        from tasks.campaign_atlas import (
            live_survey_preflight_blockers,
            live_survey_preflight_is_admissible,
        )

        self.assertTrue(live_survey_preflight_is_admissible())
        self.assertEqual(live_survey_preflight_blockers(), ())

    def test_require_survey_budget_accepts_one_opened_unfinished_attempt(self) -> None:
        from scripts.flow_delivery_campaign_atlas_bluestacks import _require_survey_budget
        from scripts import pnsctl
        from tasks.campaign_atlas import ACTIVATED_TRANSPORT_INPUT_CEILING

        opened = {
            "ordinal": 1,
            "finished_at": None,
            "terminal_outcome": None,
            "session_directory": None,
        }

        def base_flow(**overrides: object) -> dict:
            flow = {
                "maximum_navigation_inputs": ACTIVATED_TRANSPORT_INPUT_CEILING,
                "navigation_inputs_used": 0,
                "navigation_budget_disposition": "authorized_navigation_only_survey",
                "maximum_live_attempts": 1,
                "live_attempt_count": 1,
                "live_attempts": [dict(opened)],
            }
            flow.update(overrides)
            return flow

        _require_survey_budget(base_flow())

        with self.assertRaises(pnsctl.OperatorError) as no_attempt:
            _require_survey_budget(base_flow(live_attempt_count=0, live_attempts=[]))
        self.assertIn("exactly one opened unfinished", str(no_attempt.exception))

        with self.assertRaises(pnsctl.OperatorError) as too_many:
            _require_survey_budget(
                base_flow(
                    live_attempt_count=2,
                    live_attempts=[dict(opened), dict(opened, ordinal=2)],
                )
            )
        self.assertIn("exactly one opened unfinished", str(too_many.exception))

        with self.assertRaises(pnsctl.OperatorError) as finished:
            _require_survey_budget(
                base_flow(
                    live_attempts=[
                        {
                            **opened,
                            "finished_at": "2026-07-23T23:10:00Z",
                            "terminal_outcome": "blocked",
                        }
                    ]
                )
            )
        self.assertIn("already consumed", str(finished.exception))

        with self.assertRaises(pnsctl.OperatorError) as enlarged:
            _require_survey_budget(base_flow(maximum_live_attempts=2))
        self.assertIn("exactly one live session", str(enlarged.exception))

    def test_overlap_screen_revalidation_helper_is_present(self) -> None:
        from pathlib import Path
        import scripts.flow_delivery_campaign_atlas_bluestacks as mod

        source = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertIn("survey tap immediate-before is not TIER_MAP", source)
        self.assertIn("left TIER_MAP during", source)
        self.assertIn("overlap association unresolved", source)
        self.assertIn("unexpected_successor", Path("safe_action_core/executor.py").read_text())

    def test_dispatch_bound_tap_recapture_rejects_moved_roi_before_transport(self) -> None:
        from pathlib import Path
        import scripts.flow_delivery_campaign_atlas_bluestacks as mod
        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            require_stable_survey_tap_rebound,
        )

        proposal = (100, 200, 140, 240)
        moved = (101, 200, 141, 240)
        with self.assertRaises(RuntimeError) as raised:
            require_stable_survey_tap_rebound(proposal_roi=proposal, rebound_roi=moved)
        message = str(raised.exception)
        self.assertIn("unstable/current-target-moved", message)
        self.assertIn("zero transport", message)

        stable = require_stable_survey_tap_rebound(
            proposal_roi=proposal, rebound_roi=proposal
        )
        self.assertEqual(stable, proposal)

        source = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertIn("require_stable_survey_tap_rebound", source)
        self.assertIn("proposal_roi=observation.target_roi", source)
        self.assertIn('dispatch_holder["roi"] = verified_roi', source)
        # Stable continuity: rebuilt Observation keeps proposal target_roi (no rebound rewrite).
        self.assertNotIn("target_roi=rebound", source)
        # Same fresh identity for issue + remeasure + rebuild; no second live grab.
        self.assertIn("frame_sha256=fresh.sha256", source)
        self.assertIn("capture_completed_monotonic=fresh.captured_monotonic", source)
        self.assertIn(
            "del before, before_rel  # planning frame is not the issuance capture",
            source,
        )
        self.assertNotIn(
            'self.capture(f"{action_key}-immediate-before")\n            immediate_recognition',
            source,
        )
        # Do not expand SafeAction ROI-change allowlists for campaign taps.
        executor = Path("safe_action_core/executor.py").read_text(encoding="utf-8")
        self.assertNotIn("CAMPAIGN_ATLAS_MAP_TAP", executor)

    def test_zero_transport_terminal_does_not_inflate_durable_accounting(self) -> None:
        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            _SurveyState,
            _count_durable_input_sent,
            _write_accounting,
            load_durable_survey_accounting,
        )
        from tasks.campaign_atlas import (
            InputBudgetAccounting,
            InputBudgetCategory,
            InputLifecycle,
            NavigationEvidenceSequence,
            NavigationJournalEntry,
            SurveyPhase,
        )

        evidence = NavigationEvidenceSequence(
            source_path="s.png",
            immediate_before_path="b.png",
            transport_record_path="t.json",
            immediate_post_path="b.png",
            semantic_result_path="t.json",
        )
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            state = _SurveyState(accounting=InputBudgetAccounting())
            state.journal.append(
                NavigationJournalEntry(
                    input_ordinal=1,
                    phase=SurveyPhase.DIFFICULTY_GEOMETRY_PAIR,
                    budget_category=InputBudgetCategory.AUXILIARY,
                    evidence=evidence,
                    terminal_classification=(
                        "blocked_fail_closed_zero_transport:"
                        "survey tap immediate-before unstable/current-target-moved; zero transport"
                    ),
                    lifecycle=InputLifecycle.TERMINAL,
                )
            )
            (session / "survey-lifecycle.jsonl").write_text(
                json.dumps(
                    {
                        "lifecycle": "prepared",
                        "input_ordinal": 1,
                        "phase": "difficulty_geometry_pair",
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "lifecycle": "terminal",
                        "input_ordinal": 1,
                        "terminal": "blocked_fail_closed_zero_transport:moved",
                        "unresolved": False,
                        "transport_inputs_used": 0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(_count_durable_input_sent(session, state), 0)
            _write_accounting(session, state)
            durable = load_durable_survey_accounting(session)
            self.assertEqual(durable["transport_inputs_used"], 0)
            self.assertFalse(durable["transport_dispatched"])
            self.assertFalse(durable["unresolved"])

            # Durable INPUT_SENT ordinals are counted even after journal becomes TERMINAL.
            state.accounting = state.accounting.record(InputBudgetCategory.AUXILIARY)
            state.transport_dispatched = True
            state.journal[0] = NavigationJournalEntry(
                input_ordinal=1,
                phase=SurveyPhase.DIFFICULTY_GEOMETRY_PAIR,
                budget_category=InputBudgetCategory.AUXILIARY,
                evidence=evidence,
                terminal_classification="campaign-exit-base",
                lifecycle=InputLifecycle.TERMINAL,
            )
            (session / "survey-lifecycle.jsonl").write_text(
                json.dumps({"lifecycle": "prepared", "input_ordinal": 1})
                + "\n"
                + json.dumps({"lifecycle": "input_sent", "input_ordinal": 1})
                + "\n"
                + json.dumps({"lifecycle": "terminal", "input_ordinal": 1})
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(_count_durable_input_sent(session, state), 1)
            _write_accounting(session, state)
            durable = load_durable_survey_accounting(session)
            self.assertEqual(durable["transport_inputs_used"], 1)
            self.assertTrue(durable["transport_dispatched"])

        import scripts.flow_delivery_campaign_atlas_bluestacks as mod

        source = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertIn("def _close_dispatch_exception", source)
        self.assertIn("blocked_fail_closed_zero_transport", source)
        self.assertIn('transport_gate: dict[str, bool] = {"attempted": False, "input_sent": False}', source)
        self.assertIn('transport_gate["input_sent"] = True', source)

    def test_overlap_no_progress_clamps_excluded_from_overlap_reports(self) -> None:
        import scripts.flow_delivery_campaign_atlas_bluestacks as mod

        source = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertIn('if outcome == "progress":', source)
        self.assertIn("op.state.overlaps.append(", source)
        self.assertIn(
            "# no_progress clamp steps are boundary evidence only — not overlap pairs.",
            source,
        )
        # Progress-only append precedes the no_progress comment; clamps are not appended.
        progress_idx = source.index('if outcome == "progress":')
        append_idx = source.index("op.state.overlaps.append(", progress_idx)
        clamp_note_idx = source.index(
            "# no_progress clamp steps are boundary evidence only — not overlap pairs.",
            append_idx,
        )
        self.assertLess(progress_idx, append_idx)
        self.assertLess(append_idx, clamp_note_idx)
        # Edge clamps remain separate boundary evidence.
        self.assertIn("op.state.edge_clamps.append(", source)
        self.assertIn("loop_closure_accepted", source)

    def test_accepted_success_requires_recognized_home_terminal(self) -> None:
        from dataclasses import replace
        import scripts.flow_delivery_campaign_atlas_bluestacks as mod
        from tasks.campaign_atlas import (
            CollectorDisposition,
            SafeTerminalReport,
            validate_survey_session_report,
        )

        source = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertIn('identity="campaign-exit-base"', source)
        self.assertIn(
            "expected_successor=lambda rec: rec.observation.screen == CampaignScreen.HOME_BASE",
            source,
        )
        self.assertIn('terminal_runtime_state": "recognized_home"', source)
        self.assertIn("terminal_state=CampaignScreen.HOME_BASE.value", source)
        self.assertIn('campaign-base-request static/base-request fallback is prohibited', source)
        self.assertNotIn('terminal_state="campaign_tier_map"', source)

        report = build_empty_activated_session_report(
            session_id="campaign-atlas-home-terminal-gate",
            created_at_utc="2026-07-23T23:00:00Z",
        )
        with self.assertRaises(ValueError) as raised:
            validate_survey_session_report(
                replace(
                    report,
                    disposition=CollectorDisposition.NATIVE_SURVEY_COMPLETE,
                    reason="invalid-no-home",
                    safe_terminal=SafeTerminalReport(
                        recognized=True,
                        terminal_state="campaign_tier_map",
                        supporting_frame_sha256="a" * 64,
                    ),
                )
            )
        self.assertIn("Home-bound", str(raised.exception))

    def test_live_survey_invokes_standard_home_zoom_before_campaign_entry(self) -> None:
        import scripts.flow_delivery_campaign_atlas_bluestacks as mod

        source = Path(mod.__file__).read_text(encoding="utf-8")
        recover_idx = source.index("zoom_recovery = recover_home_zoom_before_campaign_entry(")
        entry_idx = source.index(
            "entry = run_verified_campaign_home_atlas_entry(",
            recover_idx,
        )
        self.assertLess(recover_idx, entry_idx)
        localized_gate = source.index(
            'zoom_recovery.get("status") != "localized"',
            recover_idx,
        )
        post_zoom_before = source.index(
            'before, _ = op.capture("entry-immediate-before")',
            localized_gate,
        )
        self.assertLess(post_zoom_before, entry_idx)
        self.assertIn("BlueStacksLocalizeFirstHomeDriver", source)
        self.assertIn("HomeDriverDisposition.RECOVER_ZOOM", source)
        self.assertIn("ScrcpyMotionEventZoomTransport", source)
        self.assertIn("dispatch_zoom_out(", source)
        self.assertIn("InputBudgetCategory.AUXILIARY", source)
        self.assertIn("maximum_zoom_inputs=4", source)

    def test_post_zoom_entry_before_preserves_auxiliary_zoom_accounting(self) -> None:
        """Post-zoom entry bookkeeping must not wipe already-recorded AUXILIARY zoom inputs."""

        from types import SimpleNamespace

        from scripts.flow_delivery_campaign_atlas_bluestacks import _SurveyOperator
        from tasks.campaign_atlas import InputBudgetAccounting, InputBudgetCategory

        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            (session / "runtime" / "frames").mkdir(parents=True)
            op = _SurveyOperator(
                session,
                runtime=SimpleNamespace(session=session / "runtime", capture=lambda *_a, **_k: None),
                session_id="campaign-atlas-aux-preserve",
                lease_owner="test-owner",
            )
            op.state.accounting = InputBudgetAccounting().record(InputBudgetCategory.AUXILIARY)
            op.state.transport_dispatched = True
            self.assertEqual(op.state.accounting.auxiliary_used, 1)
            self.assertEqual(op.state.accounting.transport_inputs_used, 1)

            imported = op.import_home_entry_accounting(
                entry={
                    "status": "opened",
                    "records": [{"disposition": "complete", "reason": "bound"}],
                    "tap_telemetry": {"transport_calls": 1},
                },
                source_rel="runtime/frames/0001-source.png",
                before_rel="runtime/frames/0008-entry-immediate-before.png",
                transport_rel="entry-transport.json",
                post_rel="runtime/frames/0009-entry-immediate-post.png",
            )
            self.assertEqual(imported, 1)
            self.assertEqual(op.state.accounting.auxiliary_used, 2)
            self.assertEqual(op.state.accounting.transport_inputs_used, 2)
            self.assertEqual(len(op.state.journal), 1)
            self.assertEqual(
                op.state.journal[0].terminal_classification,
                "imported_home_atlas_safe_action",
            )
            op.close()

    def test_home_zoom_recovery_zoomed_in_then_continues_to_localized(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        import numpy as np

        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            recover_home_zoom_before_campaign_entry,
            _SurveyOperator,
        )
        from scripts.home_atlas_bluestacks import HomeDriverDisposition, HomeDriverStep
        from tasks.campaign_atlas import InputBudgetAccounting, InputBudgetCategory
        from tasks.campaign_auto_battle import CampaignScreen

        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            frames = session / "runtime" / "frames"
            frames.mkdir(parents=True)

            digests = ["a" * 64, "b" * 64, "c" * 64, "d" * 64, "e" * 64, "f" * 64]
            captures: list[str] = []

            def capture(label: str):
                captures.append(label)
                digest = digests[len(captures) - 1]
                path = frames / f"{label}.png"
                path.write_bytes(b"\x89PNG\r\n\x1a\n" + digest.encode()[:24])
                frame = SimpleNamespace(
                    label=label,
                    path=path,
                    frame=np.zeros((1280, 800, 3), np.uint8),
                    sha256=digest,
                    captured_monotonic=100.0 + len(captures),
                )
                return frame, SimpleNamespace()

            localization = MagicMock()
            steps = [
                HomeDriverStep(
                    HomeDriverDisposition.RECOVER_ZOOM,
                    "unsupported_zoom_requires_bounded_canonical_recovery",
                    "a" * 64,
                    localization,
                    recovery_input_ordinal=1,
                ),
                HomeDriverStep(
                    HomeDriverDisposition.PAN,
                    "localized_after_zoom",
                    "d" * 64,
                    localization,
                ),
            ]
            driver = MagicMock()
            driver.observe.side_effect = steps
            driver.record_zoom_input_dispatched = MagicMock()

            zoom_calls: list[str] = []

            class _Zoom:
                def zoom_out_once(self) -> None:
                    zoom_calls.append("zoom")

            guarded = MagicMock()

            def dispatch_zoom_out(before, facts, *, transport, target_identity="home-zoom-out"):
                self.assertEqual(facts.source_state, "HOME_BASE")
                self.assertTrue(facts.recognized)
                transport()

            guarded.dispatch_zoom_out.side_effect = dispatch_zoom_out

            real = object.__new__(_SurveyOperator)
            real.session = session
            real.session_id = "zoom-test"
            real.lease_owner = "owner"
            real.runtime = SimpleNamespace(session=session)
            real.state = SimpleNamespace(
                accounting=InputBudgetAccounting(),
                journal=[],
                transport_dispatched=False,
                unresolved=False,
                last_swipe=None,
                last_progress_proven=False,
                capture_ordinal=0,
                accepted=[],
            )
            real.lifecycle_path = session / "survey-lifecycle.jsonl"
            real.journal_path = session / "journal.jsonl"
            real.events_path = session / "events.jsonl"
            real.lifecycle_path.write_text("", encoding="utf-8")
            real.journal_path.write_text("", encoding="utf-8")
            real.events_path.write_text("", encoding="utf-8")
            real.capture = capture
            real.recognize = lambda _frame: SimpleNamespace(
                observation=SimpleNamespace(screen=CampaignScreen.HOME_BASE)
            )
            real.prepare_input = _SurveyOperator.prepare_input.__get__(real, _SurveyOperator)
            real.mark_input_sent = _SurveyOperator.mark_input_sent.__get__(real, _SurveyOperator)
            real.mark_terminal = _SurveyOperator.mark_terminal.__get__(real, _SurveyOperator)
            real._persist_lifecycle = _SurveyOperator._persist_lifecycle.__get__(
                real, _SurveyOperator
            )
            real._close_dispatch_exception = _SurveyOperator._close_dispatch_exception.__get__(
                real, _SurveyOperator
            )

            result = recover_home_zoom_before_campaign_entry(
                real,
                source_rel="source.png",
                atlas_path=Path("atlas.json"),
                maximum_zoom_inputs=4,
                settle_seconds=0.0,
                home_driver=driver,
                zoom_transport=_Zoom(),
                guarded_runtime=guarded,
            )
            self.assertEqual(result["status"], "localized")
            self.assertEqual(result["zoom_inputs"], 1)
            self.assertEqual(zoom_calls, ["zoom"])
            self.assertEqual(real.state.accounting.auxiliary_used, 1)
            self.assertEqual(real.state.accounting.transport_inputs_used, 1)
            self.assertTrue(real.state.transport_dispatched)
            self.assertEqual(len(real.state.journal), 1)
            self.assertEqual(
                real.state.journal[0].budget_category, InputBudgetCategory.AUXILIARY
            )
            self.assertEqual(
                real.state.journal[0].terminal_classification, "bounded_home_zoom_out"
            )
            driver.record_zoom_input_dispatched.assert_called_once_with("a" * 64)
            guarded.dispatch_zoom_out.assert_called_once()

    def test_home_zoom_recovery_fail_closed_unknown_repeated_and_max(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        import numpy as np

        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            recover_home_zoom_before_campaign_entry,
            _SurveyOperator,
        )
        from scripts.home_atlas_bluestacks import HomeDriverDisposition, HomeDriverStep
        from tasks.campaign_atlas import InputBudgetAccounting
        from tasks.campaign_auto_battle import CampaignScreen

        localization = MagicMock()

        def _run(driver_steps, *, max_inputs: int = 4):
            with tempfile.TemporaryDirectory() as directory:
                session = Path(directory)
                frames = session / "runtime" / "frames"
                frames.mkdir(parents=True)
                digests = [f"{i:064d}" for i in range(1, 20)]
                captures: list[str] = []

                def capture(label: str):
                    captures.append(label)
                    digest = digests[len(captures) - 1]
                    path = frames / f"{label}.png"
                    path.write_bytes(b"\x89PNG\r\n\x1a\n" + digest.encode()[:24])
                    return SimpleNamespace(
                        label=label,
                        path=path,
                        frame=np.zeros((1280, 800, 3), np.uint8),
                        sha256=digest,
                        captured_monotonic=10.0 + len(captures),
                    ), SimpleNamespace()

                driver = MagicMock()
                driver.observe.side_effect = list(driver_steps)
                driver.record_zoom_input_dispatched = MagicMock()
                guarded = MagicMock()
                zoom_transport = MagicMock()
                zoom_transport.zoom_out_once = MagicMock()
                guarded.dispatch_zoom_out.side_effect = (
                    lambda before, facts, *, transport, target_identity="home-zoom-out": transport()
                )

                real = object.__new__(_SurveyOperator)
                real.session = session
                real.session_id = "zoom-fail"
                real.lease_owner = "owner"
                real.runtime = SimpleNamespace(session=session)
                real.state = SimpleNamespace(
                    accounting=InputBudgetAccounting(),
                    journal=[],
                    transport_dispatched=False,
                    unresolved=False,
                    last_swipe=None,
                    last_progress_proven=False,
                    capture_ordinal=0,
                    accepted=[],
                )
                real.lifecycle_path = session / "survey-lifecycle.jsonl"
                real.journal_path = session / "journal.jsonl"
                real.events_path = session / "events.jsonl"
                real.lifecycle_path.write_text("", encoding="utf-8")
                real.journal_path.write_text("", encoding="utf-8")
                real.events_path.write_text("", encoding="utf-8")
                real.capture = capture
                real.recognize = lambda _frame: SimpleNamespace(
                    observation=SimpleNamespace(screen=CampaignScreen.HOME_BASE)
                )
                real.prepare_input = _SurveyOperator.prepare_input.__get__(real, _SurveyOperator)
                real.mark_input_sent = _SurveyOperator.mark_input_sent.__get__(
                    real, _SurveyOperator
                )
                real.mark_terminal = _SurveyOperator.mark_terminal.__get__(real, _SurveyOperator)
                real._persist_lifecycle = _SurveyOperator._persist_lifecycle.__get__(
                    real, _SurveyOperator
                )
                real._close_dispatch_exception = _SurveyOperator._close_dispatch_exception.__get__(
                    real, _SurveyOperator
                )
                return recover_home_zoom_before_campaign_entry(
                    real,
                    source_rel="source.png",
                    atlas_path=Path("atlas.json"),
                    maximum_zoom_inputs=max_inputs,
                    settle_seconds=0.0,
                    home_driver=driver,
                    zoom_transport=zoom_transport,
                    guarded_runtime=guarded,
                ), real

        unknown = HomeDriverStep(
            HomeDriverDisposition.BLOCKED,
            "home_localization_ambiguous:unknown",
            "u" * 64,
            localization,
        )
        with self.assertRaises(RuntimeError) as unknown_exc:
            _run([unknown])
        self.assertIn("home_localization_ambiguous", str(unknown_exc.exception))

        repeated = HomeDriverStep(
            HomeDriverDisposition.BLOCKED,
            "repeated_zoom_recovery_frame",
            "r" * 64,
            localization,
        )
        with self.assertRaises(RuntimeError) as repeated_exc:
            _run([repeated])
        self.assertIn("repeated_zoom_recovery_frame", str(repeated_exc.exception))

        maxed = HomeDriverStep(
            HomeDriverDisposition.BLOCKED,
            "maximum_zoom_recovery_inputs",
            "m" * 64,
            localization,
        )
        with self.assertRaises(RuntimeError) as max_exc:
            _run([maxed], max_inputs=1)
        self.assertIn("maximum_zoom_recovery_inputs", str(max_exc.exception))

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

    def _write_known_prior_aux_sessions(self, artifact_root: Path, *, mutate=None) -> tuple[Path, Path]:
        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            FLOW_ID,
            KNOWN_CONTINUATION_PRIOR_SESSION_IDS,
            LIFECYCLE_PATH,
            ACCOUNTING_PATH,
        )

        zoom_id, entry_id = KNOWN_CONTINUATION_PRIOR_SESSION_IDS
        zoom_session = artifact_root / FLOW_ID / zoom_id
        entry_session = artifact_root / FLOW_ID / entry_id
        zoom_session.mkdir(parents=True, exist_ok=True)
        entry_session.mkdir(parents=True, exist_ok=True)

        zoom_lifecycle = [
            {
                "category": "auxiliary",
                "input_ordinal": 1,
                "lifecycle": "prepared",
                "phase": "safe_terminal",
                "prior_progress_proven": False,
                "swipe": None,
            },
            {
                "budget_error": None,
                "input_ordinal": 1,
                "lifecycle": "input_sent",
                "transport_inputs_used": 1,
            },
            {
                "input_ordinal": 1,
                "lifecycle": "terminal",
                "terminal": "bounded_home_zoom_out",
                "transport_inputs_used": 1,
                "unresolved": False,
            },
        ]
        zoom_accounting = {
            "accounting": {
                "auxiliary_used": 1,
                "edge_clamp_used": 0,
                "maximum_auxiliary": 16,
                "maximum_edge_clamp": 128,
                "maximum_overlap": 128,
                "maximum_transport_inputs": 272,
                "overlap_used": 0,
                "transport_inputs_used": 1,
            },
            "input_sent_count": 1,
            "journal_len": 1,
            "open_prepared": False,
            "transport_dispatched": True,
            "transport_inputs_used": 1,
            "unresolved": False,
            "updated_at_utc": "2026-07-23T23:22:25Z",
        }

        entry_lifecycle = []
        entry_journal = []
        for ordinal in (1, 2, 3):
            entry_lifecycle.append(
                {
                    "imported_from": "run_verified_campaign_home_atlas_entry",
                    "input_ordinal": ordinal,
                    "lifecycle": "terminal",
                    "terminal": "imported_home_atlas_safe_action",
                    "transport_inputs_used": ordinal + 1,
                    "unresolved": False,
                }
            )
            entry_journal.append(
                {
                    "budget_category": "auxiliary",
                    "evidence": {
                        "immediate_before_path": "runtime/frames/entry-immediate-before.png",
                        "immediate_post_path": "runtime/frames/entry-immediate-post.png",
                        "semantic_result_path": f"entry-transport.json#home_atlas_safe_action={ordinal}",
                        "source_path": "runtime/frames/source.png",
                        "transport_record_path": f"entry-transport.json#home_atlas_safe_action={ordinal}",
                    },
                    "identical_retry": False,
                    "input_ordinal": ordinal,
                    "lifecycle": "terminal",
                    "phase": "safe_terminal",
                    "prior_progress_proven": False,
                    "swipe_geometry": None,
                    "terminal_classification": "imported_home_atlas_safe_action",
                    "unresolved": False,
                }
            )
        # Preserve edge-top-00 zero-transport terminal history; never count it.
        entry_lifecycle.extend(
            [
                {
                    "category": "edge_clamp",
                    "input_ordinal": 4,
                    "lifecycle": "prepared",
                    "phase": "edge_top",
                    "prior_progress_proven": False,
                    "swipe": [357, 560, 357, 720, 350],
                },
                {
                    "input_ordinal": 4,
                    "lifecycle": "terminal",
                    "terminal": (
                        "blocked_fail_closed_zero_transport:"
                        "SafeActionExecutor issued zero transport for edge-top-00"
                    ),
                    "transport_inputs_used": 4,
                    "unresolved": False,
                },
            ]
        )
        entry_journal.append(
            {
                "budget_category": "edge_clamp",
                "evidence": {
                    "immediate_before_path": "runtime/frames/edge-top-before-00.png",
                    "immediate_post_path": "runtime/frames/edge-top-before-00.png",
                    "semantic_result_path": "edge-top-00-transport.json",
                    "source_path": "runtime/frames/source.png",
                    "transport_record_path": "edge-top-00-transport.json",
                },
                "identical_retry": False,
                "input_ordinal": 4,
                "lifecycle": "terminal",
                "phase": "edge_top",
                "prior_progress_proven": False,
                "swipe_geometry": [357, 560, 357, 720, 350],
                "terminal_classification": (
                    "blocked_fail_closed_zero_transport:"
                    "SafeActionExecutor issued zero transport for edge-top-00"
                ),
                "unresolved": False,
            }
        )
        entry_accounting = {
            "accounting": {
                "auxiliary_used": 4,
                "edge_clamp_used": 0,
                "maximum_auxiliary": 16,
                "maximum_edge_clamp": 128,
                "maximum_overlap": 128,
                "maximum_transport_inputs": 272,
                "overlap_used": 0,
                "transport_inputs_used": 4,
            },
            "input_sent_count": 3,
            "journal_len": 4,
            "open_prepared": False,
            "prior_inputs_seeded": 1,
            "session_navigation_inputs_sent": 3,
            "transport_dispatched": True,
            "transport_inputs_used": 4,
            "unresolved": False,
            "updated_at_utc": "2026-07-24T00:04:30Z",
        }

        if mutate is not None:
            (
                zoom_lifecycle,
                zoom_accounting,
                entry_lifecycle,
                entry_journal,
                entry_accounting,
            ) = mutate(
                zoom_lifecycle,
                zoom_accounting,
                entry_lifecycle,
                entry_journal,
                entry_accounting,
            )

        (zoom_session / LIFECYCLE_PATH).write_text(
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in zoom_lifecycle),
            encoding="utf-8",
        )
        (zoom_session / ACCOUNTING_PATH).write_text(
            json.dumps(zoom_accounting, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (entry_session / LIFECYCLE_PATH).write_text(
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in entry_lifecycle),
            encoding="utf-8",
        )
        (entry_session / "journal.jsonl").write_text(
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in entry_journal),
            encoding="utf-8",
        )
        (entry_session / ACCOUNTING_PATH).write_text(
            json.dumps(entry_accounting, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return zoom_session, entry_session

    def test_evidence_backed_prior_auxiliary_seed_accepts_known_sessions(self) -> None:
        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            KNOWN_CONTINUATION_PRIOR_SESSION_IDS,
            resolve_evidence_backed_prior_auxiliary_seed,
        )
        from tasks.campaign_atlas import ACTIVATED_AUXILIARY_INPUTS, ACTIVATED_TRANSPORT_INPUT_CEILING

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_known_prior_aux_sessions(root)
            accounting, meta = resolve_evidence_backed_prior_auxiliary_seed(
                artifact_root=root,
                claimed_navigation_inputs_used=4,
            )
            self.assertEqual(accounting.auxiliary_used, 4)
            self.assertEqual(accounting.edge_clamp_used, 0)
            self.assertEqual(accounting.overlap_used, 0)
            self.assertEqual(accounting.transport_inputs_used, 4)
            self.assertEqual(
                accounting.maximum_auxiliary - accounting.auxiliary_used,
                ACTIVATED_AUXILIARY_INPUTS - 4,
            )
            self.assertEqual(
                accounting.maximum_transport_inputs - accounting.transport_inputs_used,
                ACTIVATED_TRANSPORT_INPUT_CEILING - 4,
            )
            self.assertEqual(meta["prior_inputs_seeded"], 4)
            self.assertEqual(meta["prior_session_ids"], list(KNOWN_CONTINUATION_PRIOR_SESSION_IDS))
            self.assertEqual(len(meta["prior_sessions"]), 2)
            self.assertEqual(meta["prior_sessions"][0]["count"], 1)
            self.assertEqual(meta["prior_sessions"][0]["terminal"], "bounded_home_zoom_out")
            self.assertEqual(meta["prior_sessions"][1]["count"], 3)
            self.assertEqual(
                meta["prior_sessions"][1]["terminal"], "imported_home_atlas_safe_action"
            )
            self.assertEqual(meta["prior_category"], "auxiliary")
            self.assertIsNone(meta["prior_session_id"])

            zero, zero_meta = resolve_evidence_backed_prior_auxiliary_seed(
                artifact_root=root,
                claimed_navigation_inputs_used=0,
            )
            self.assertEqual(zero.transport_inputs_used, 0)
            self.assertEqual(zero_meta["prior_inputs_seeded"], 0)

    def test_evidence_backed_prior_auxiliary_seed_fail_closed_on_mismatch(self) -> None:
        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            resolve_evidence_backed_prior_auxiliary_seed,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(RuntimeError) as missing:
                resolve_evidence_backed_prior_auxiliary_seed(
                    artifact_root=root,
                    claimed_navigation_inputs_used=4,
                )
            self.assertIn("known prior survey session is missing", str(missing.exception))

            with self.assertRaises(RuntimeError) as wrong_count:
                resolve_evidence_backed_prior_auxiliary_seed(
                    artifact_root=root,
                    claimed_navigation_inputs_used=1,
                )
            self.assertIn("claimed=1", str(wrong_count.exception))

            with self.assertRaises(RuntimeError) as wrong_count_two:
                resolve_evidence_backed_prior_auxiliary_seed(
                    artifact_root=root,
                    claimed_navigation_inputs_used=2,
                )
            self.assertIn("claimed=2", str(wrong_count_two.exception))

            with self.assertRaises(RuntimeError) as claimed_five_without_receipt:
                self._write_known_prior_aux_sessions(root)
                resolve_evidence_backed_prior_auxiliary_seed(
                    artifact_root=root,
                    claimed_navigation_inputs_used=5,
                )
            self.assertTrue(
                "receipt" in str(claimed_five_without_receipt.exception).casefold()
                or "missing" in str(claimed_five_without_receipt.exception).casefold()
            )

            def bad_terminal(zoom_lifecycle, zoom_accounting, entry_lifecycle, entry_journal, entry_accounting):
                zoom_lifecycle[-1]["terminal"] = "some_other_terminal"
                return (
                    zoom_lifecycle,
                    zoom_accounting,
                    entry_lifecycle,
                    entry_journal,
                    entry_accounting,
                )

            self._write_known_prior_aux_sessions(root, mutate=bad_terminal)
            with self.assertRaises(RuntimeError) as terminal_exc:
                resolve_evidence_backed_prior_auxiliary_seed(
                    artifact_root=root,
                    claimed_navigation_inputs_used=4,
                )
            self.assertIn("terminal", str(terminal_exc.exception).casefold())

            def non_aux(zoom_lifecycle, zoom_accounting, entry_lifecycle, entry_journal, entry_accounting):
                zoom_lifecycle[0]["category"] = "edge_clamp"
                return (
                    zoom_lifecycle,
                    zoom_accounting,
                    entry_lifecycle,
                    entry_journal,
                    entry_accounting,
                )

            self._write_known_prior_aux_sessions(root, mutate=non_aux)
            with self.assertRaises(RuntimeError) as category_exc:
                resolve_evidence_backed_prior_auxiliary_seed(
                    artifact_root=root,
                    claimed_navigation_inputs_used=4,
                )
            self.assertIn("not AUXILIARY", str(category_exc.exception))

            def open_prepared(zoom_lifecycle, zoom_accounting, entry_lifecycle, entry_journal, entry_accounting):
                zoom_lifecycle = zoom_lifecycle[:1]  # prepared only
                zoom_accounting["open_prepared"] = True
                zoom_accounting["unresolved"] = True
                return (
                    zoom_lifecycle,
                    zoom_accounting,
                    entry_lifecycle,
                    entry_journal,
                    entry_accounting,
                )

            self._write_known_prior_aux_sessions(root, mutate=open_prepared)
            with self.assertRaises(RuntimeError) as prepared_exc:
                resolve_evidence_backed_prior_auxiliary_seed(
                    artifact_root=root,
                    claimed_navigation_inputs_used=4,
                )
            self.assertIn("open prepared", str(prepared_exc.exception).casefold())

            def entry_count_mismatch(
                zoom_lifecycle, zoom_accounting, entry_lifecycle, entry_journal, entry_accounting
            ):
                entry_journal = entry_journal[:2]  # drop one AUX
                entry_accounting["session_navigation_inputs_sent"] = 2
                entry_accounting["input_sent_count"] = 2
                return (
                    zoom_lifecycle,
                    zoom_accounting,
                    entry_lifecycle,
                    entry_journal,
                    entry_accounting,
                )

            self._write_known_prior_aux_sessions(root, mutate=entry_count_mismatch)
            with self.assertRaises(RuntimeError) as entry_exc:
                resolve_evidence_backed_prior_auxiliary_seed(
                    artifact_root=root,
                    claimed_navigation_inputs_used=4,
                )
            self.assertTrue(
                "count" in str(entry_exc.exception).casefold()
                or "journal" in str(entry_exc.exception).casefold()
            )

    def test_seeded_prior_auxiliary_enforces_remaining_budget_and_cumulative_result(self) -> None:
        from types import SimpleNamespace

        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            CONTINUATION_PATH,
            KNOWN_CONTINUATION_PRIOR_SESSION_IDS,
            _SurveyOperator,
            _budget_has_capacity,
            _failure_delivery_from_session,
            resolve_evidence_backed_prior_auxiliary_seed,
        )
        from tasks.campaign_atlas import (
            ACTIVATED_AUXILIARY_INPUTS,
            InputBudgetAccounting,
            InputBudgetCategory,
            SurveyPhase,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_known_prior_aux_sessions(root)
            prior_accounting, prior_continuation = resolve_evidence_backed_prior_auxiliary_seed(
                artifact_root=root,
                claimed_navigation_inputs_used=4,
            )
            session = root / "continuation-session"
            session.mkdir(parents=True)
            (session / "runtime" / "frames").mkdir(parents=True)
            op = _SurveyOperator(
                session,
                runtime=SimpleNamespace(
                    session=session / "runtime", capture=lambda *_a, **_k: None
                ),
                session_id="campaign-atlas-continuation",
                lease_owner="test-owner",
                prior_accounting=prior_accounting,
                prior_continuation=prior_continuation,
            )
            self.assertEqual(op.state.prior_inputs_seeded, 4)
            self.assertEqual(op.state.accounting.auxiliary_used, 4)
            self.assertEqual(op.state.cumulative_navigation_inputs_used, 4)
            self.assertEqual(op.state.session_navigation_inputs_sent, 0)
            self.assertTrue((session / CONTINUATION_PATH).is_file())
            continuation_payload = json.loads(
                (session / CONTINUATION_PATH).read_text(encoding="utf-8")
            )
            self.assertEqual(
                continuation_payload["prior_session_ids"],
                list(KNOWN_CONTINUATION_PRIOR_SESSION_IDS),
            )
            durable_seeded = json.loads(
                (session / "survey-accounting.json").read_text(encoding="utf-8")
            )
            self.assertEqual(durable_seeded["transport_inputs_used"], 4)
            self.assertEqual(durable_seeded["input_sent_count"], 0)
            self.assertEqual(durable_seeded["session_navigation_inputs_sent"], 0)
            self.assertFalse(durable_seeded["transport_dispatched"])
            self.assertFalse(durable_seeded["unresolved"])

            pre_input_failure = _failure_delivery_from_session(
                session,
                serial="emulator-5554",
                runtime_owner="test-owner",
                exc=RuntimeError("seeded pre-input stop"),
            )
            self.assertEqual(pre_input_failure["survey_result"]["navigation_inputs_used"], 4)
            self.assertEqual(
                pre_input_failure["survey_result"]["session_navigation_inputs_sent"], 0
            )
            self.assertFalse(pre_input_failure["survey_result"]["transport_dispatched"])
            self.assertFalse(pre_input_failure["survey_result"]["unresolved"])
            self.assertEqual(
                pre_input_failure["terminal_runtime_state"], "safe_blocked_terminal"
            )
            self.assertEqual(
                pre_input_failure["survey_result"]["terminal"], "blocked_fail_closed"
            )

            for _ in range(ACTIVATED_AUXILIARY_INPUTS - 4):
                self.assertTrue(
                    _budget_has_capacity(op.state.accounting, InputBudgetCategory.AUXILIARY)
                )
                op.state.accounting = op.state.accounting.record(InputBudgetCategory.AUXILIARY)
            self.assertEqual(op.state.accounting.auxiliary_used, ACTIVATED_AUXILIARY_INPUTS)
            self.assertFalse(
                _budget_has_capacity(op.state.accounting, InputBudgetCategory.AUXILIARY)
            )
            self.assertEqual(op.state.accounting.transport_inputs_used, ACTIVATED_AUXILIARY_INPUTS)
            op.close()

            session2 = root / "continuation-session-2"
            session2.mkdir(parents=True)
            (session2 / "runtime" / "frames").mkdir(parents=True)
            accounting = InputBudgetAccounting(auxiliary_used=4)
            op2 = _SurveyOperator(
                session2,
                runtime=SimpleNamespace(
                    session=session2 / "runtime", capture=lambda *_a, **_k: None
                ),
                session_id="campaign-atlas-continuation-2",
                lease_owner="test-owner",
                prior_accounting=accounting,
                prior_continuation=prior_continuation,
            )
            ordinal = op2.prepare_input(
                phase=SurveyPhase.SAFE_TERMINAL,
                category=InputBudgetCategory.AUXILIARY,
                before_rel="runtime/frames/before.png",
                transport_rel="transport.json",
                source_rel="runtime/frames/source.png",
                swipe=None,
                prior_progress_proven=False,
                planned_terminal="test_terminal",
            )
            self.assertEqual(ordinal, 1)
            op2.mark_input_sent(ordinal, category=InputBudgetCategory.AUXILIARY)
            self.assertEqual(op2.state.cumulative_navigation_inputs_used, 5)
            self.assertEqual(op2.state.session_navigation_inputs_sent, 1)
            op2.close()
            failure = _failure_delivery_from_session(
                session2,
                serial="emulator-5554",
                runtime_owner="test-owner",
                exc=RuntimeError("forced stop"),
            )
            self.assertEqual(failure["survey_result"]["navigation_inputs_used"], 5)
            self.assertEqual(failure["survey_result"]["session_navigation_inputs_sent"], 1)
            self.assertTrue(failure["survey_result"]["transport_dispatched"])
            self.assertEqual(
                failure["survey_result"]["prior_continuation"]["prior_session_ids"],
                list(KNOWN_CONTINUATION_PRIOR_SESSION_IDS),
            )
            for session_id in KNOWN_CONTINUATION_PRIOR_SESSION_IDS:
                self.assertTrue(
                    (
                        root
                        / "CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION"
                        / session_id
                        / "survey-accounting.json"
                    ).is_file()
                )

    def test_seeded_preflight_blocked_preserves_cumulative_without_session_dispatch(self) -> None:
        from unittest.mock import patch

        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            CONTINUATION_PATH,
            KNOWN_CONTINUATION_PRIOR_SESSION_IDS,
            _preflight_blocked_delivery,
            resolve_evidence_backed_prior_auxiliary_seed,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_known_prior_aux_sessions(root)
            prior_accounting, prior_continuation = resolve_evidence_backed_prior_auxiliary_seed(
                artifact_root=root,
                claimed_navigation_inputs_used=4,
            )
            session = root / "preflight-continuation"
            session.mkdir(parents=True)
            with patch(
                "scripts.flow_delivery_campaign_atlas_bluestacks.live_survey_preflight_blockers",
                return_value=("measured_selectors_required",),
            ):
                delivery = _preflight_blocked_delivery(
                    session=session,
                    serial="emulator-5554",
                    runtime_owner="test-owner",
                    prior_accounting=prior_accounting,
                    prior_continuation=prior_continuation,
                )
            survey = delivery["survey_result"]
            self.assertEqual(survey["navigation_inputs_used"], 4)
            self.assertEqual(survey["session_navigation_inputs_sent"], 0)
            self.assertFalse(survey["transport_dispatched"])
            self.assertFalse(survey["unresolved"])
            self.assertTrue(survey["live_preflight_inadmissible"])
            self.assertEqual(delivery["terminal_runtime_state"], "safe_blocked_terminal")
            self.assertEqual(
                survey["prior_continuation"]["prior_session_ids"],
                list(KNOWN_CONTINUATION_PRIOR_SESSION_IDS),
            )
            self.assertTrue((session / CONTINUATION_PATH).is_file())
            durable = json.loads((session / "survey-accounting.json").read_text(encoding="utf-8"))
            self.assertEqual(durable["transport_inputs_used"], 4)
            self.assertEqual(durable["input_sent_count"], 0)
            self.assertFalse(durable["transport_dispatched"])
            self.assertEqual(durable["prior_inputs_seeded"], 4)
            for session_id, expected_used in zip(
                KNOWN_CONTINUATION_PRIOR_SESSION_IDS, (1, 4)
            ):
                prior_accounting_path = (
                    root
                    / "CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION"
                    / session_id
                    / "survey-accounting.json"
                )
                prior_durable = json.loads(prior_accounting_path.read_text(encoding="utf-8"))
                self.assertEqual(prior_durable["transport_inputs_used"], expected_used)
                self.assertTrue(prior_durable["transport_dispatched"])

    def test_seeded_native_survey_complete_packaging_and_verification(self) -> None:
        """Seeded full-success: session report journal-scoped; delivery cumulative."""

        from types import SimpleNamespace

        from scripts.campaign_atlas_bluestacks import report_from_dict
        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            FLOW_ID,
            KNOWN_CONTINUATION_PRIOR_SESSION_IDS,
            _SurveyOperator,
            _finalize_survey_delivery,
            resolve_evidence_backed_prior_auxiliary_seed,
            verify_campaign_atlas_native_survey,
        )
        from tasks.campaign_atlas import (
            ACTIVATED_TRANSPORT_INPUT_CEILING,
            CrossDifficultyGeometryReport,
            EdgeClampReport,
            InputBudgetCategory,
            LandmarkBindingReport,
            LandmarkKind,
            LoopClosureReport,
            NavigationEvidenceSequence,
            OverlapAssociationReport,
            SafeTerminalReport,
            SurveyPhase,
        )

        digest = "a" * 64
        evidence = NavigationEvidenceSequence(
            source_path="runtime/frames/source.png",
            immediate_before_path="runtime/frames/before.png",
            transport_record_path="transport.json",
            immediate_post_path="runtime/frames/post.png",
            semantic_result_path="result.json",
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_known_prior_aux_sessions(root)
            prior_accounting, prior_continuation = resolve_evidence_backed_prior_auxiliary_seed(
                artifact_root=root,
                claimed_navigation_inputs_used=4,
            )
            session = root / "seeded-complete-session"
            session.mkdir(parents=True)
            (session / "runtime" / "frames").mkdir(parents=True)
            op = _SurveyOperator(
                session,
                runtime=SimpleNamespace(
                    session=session / "runtime", capture=lambda *_a, **_k: None
                ),
                session_id="campaign-atlas-seeded-complete",
                lease_owner="test-owner",
                prior_accounting=prior_accounting,
                prior_continuation=prior_continuation,
            )
            ordinal = op.prepare_input(
                phase=SurveyPhase.EDGE_TOP,
                category=InputBudgetCategory.EDGE_CLAMP,
                before_rel="runtime/frames/before.png",
                transport_rel="transport.json",
                source_rel="runtime/frames/source.png",
                swipe=(400, 900, 400, 400, 300),
                prior_progress_proven=False,
                planned_terminal="edge_top",
            )
            self.assertEqual(ordinal, 1)
            op.mark_input_sent(ordinal, category=InputBudgetCategory.EDGE_CLAMP)
            op.mark_terminal(
                ordinal,
                evidence=evidence,
                terminal="edge_top",
                unresolved=False,
                progress_proven=True,
            )
            self.assertEqual(op.state.cumulative_navigation_inputs_used, 5)
            self.assertEqual(op.state.session_navigation_inputs_sent, 1)
            self.assertEqual(len(op.state.journal), 1)

            op.state.edge_clamps = [
                EdgeClampReport(direction=d, clamp_observed=True, supporting_frame_sha256=digest)
                for d in ("top", "right", "bottom", "left")
            ]
            op.state.overlaps = [
                OverlapAssociationReport(
                    reference_sha256=digest,
                    candidate_sha256=digest,
                    overlap_ratio=0.42,
                    associated=True,
                )
            ]
            op.state.loop_closure = LoopClosureReport(
                closed=True, residual_px=1.0, supporting_frame_sha256=digest
            )
            op.state.cross_difficulty = CrossDifficultyGeometryReport(
                difficulty_a=1,
                difficulty_b=2,
                compared=True,
                used_as_recenter=False,
                conclusion="geometry compared",
            )
            op.state.landmarks = [
                LandmarkBindingReport(
                    kind=LandmarkKind.CHAPTER,
                    label="Chapter 1",
                    supporting_frame_sha256=digest,
                    spatially_associated=True,
                ),
                LandmarkBindingReport(
                    kind=LandmarkKind.PRISON_TRIAL,
                    label="Prison Trial",
                    supporting_frame_sha256=digest,
                    spatially_associated=True,
                ),
            ]
            op.state.safe_terminal = SafeTerminalReport(
                recognized=True,
                terminal_state="HOME_BASE",
                supporting_frame_sha256=digest,
            )
            op.state.coverage_gaps = []

            delivery = _finalize_survey_delivery(
                op=op,
                session=session,
                session_id="campaign-atlas-seeded-complete",
                source_rel="runtime/frames/source.png",
                first_map_sha=digest,
                first_map_path=session / "runtime" / "frames" / "source.png",
                serial="emulator-5554",
                runtime_owner="test-owner",
            )
            op.close()

            survey = delivery["survey_result"]
            self.assertEqual(survey["terminal"], "native_survey_complete")
            self.assertEqual(survey["navigation_inputs_used"], 5)
            self.assertEqual(survey["session_navigation_inputs_sent"], 1)
            self.assertEqual(survey["maximum_navigation_inputs"], ACTIVATED_TRANSPORT_INPUT_CEILING)
            self.assertTrue(survey["transport_dispatched"])
            self.assertEqual(
                survey["prior_continuation"]["prior_session_ids"],
                list(KNOWN_CONTINUATION_PRIOR_SESSION_IDS),
            )
            self.assertEqual(survey["accounting"]["transport_inputs_used"], 5)
            self.assertEqual(survey["accounting"]["auxiliary_used"], 4)
            self.assertEqual(survey["accounting"]["edge_clamp_used"], 1)
            self.assertEqual(survey["accounting"]["maximum_transport_inputs"], 272)

            report_payload = json.loads(
                (session / "survey-session-report.json").read_text(encoding="utf-8")
            )
            report = report_from_dict(report_payload)
            self.assertEqual(report.accounting.transport_inputs_used, 1)
            self.assertEqual(len(report.journal), 1)
            self.assertEqual(report.accounting.edge_clamp_used, 1)
            self.assertEqual(report.accounting.auxiliary_used, 0)
            self.assertEqual(report.accounting.maximum_transport_inputs, 272)
            self.assertEqual(
                [entry.budget_category for entry in report.journal],
                [InputBudgetCategory.EDGE_CLAMP],
            )

            verified = verify_campaign_atlas_native_survey(
                {
                    "session_directory": str(session),
                    "result": delivery,
                },
                {"flows": [{"flow_id": FLOW_ID}]},
                {},
            )
            self.assertEqual(verified["status"], "verified")
            self.assertEqual(verified["terminal"], "native_survey_complete")
            self.assertEqual(verified["navigation_inputs_used"], 5)

    def test_survey_pan_binds_issue_and_consume_to_one_immediate_before(self) -> None:
        """HUD digest drift: issue+consume share one immediate-before; one transport."""

        from dataclasses import dataclass
        from types import SimpleNamespace
        from unittest.mock import patch

        import numpy as np

        from scripts.bluestacks_native_runtime import CapturedNativeFrame
        from scripts.flow_delivery_campaign_atlas_bluestacks import _SurveyOperator
        from tasks.campaign_atlas import InputBudgetCategory, SurveyPhase
        from tasks.campaign_auto_battle_vision import CampaignScreen

        @dataclass
        class _FakeMeasurement:
            overlap_ratio: float = 0.0
            residual_px: float = 0.0

        class _FakeRuntime:
            def __init__(self, session: Path) -> None:
                self.session = session
                self.ordinal = 0
                self.swipes: list[dict[str, object]] = []
                self.captured_frames: list[tuple[str, CapturedNativeFrame]] = []

            def capture(self, label: str) -> CapturedNativeFrame:
                import time as time_module

                self.ordinal += 1
                frame = np.zeros((1280, 800, 3), np.uint8)
                frame[0, 0] = (self.ordinal % 200, 10, 10)
                digest = f"{self.ordinal:064x}"
                path = self.session / "frames" / f"{self.ordinal:04d}-{label}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"png")
                captured = CapturedNativeFrame(
                    frame,
                    f"png-{self.ordinal}".encode(),
                    digest,
                    float(time_module.monotonic()),
                    path,
                )
                self.captured_frames.append((label, captured))
                return captured

            def swipe(self, captured, *, start, end, action_key, target_identity):
                self.swipes.append(
                    {
                        "sha256": captured.sha256,
                        "start": start,
                        "end": end,
                        "action_key": action_key,
                        "target_identity": target_identity,
                    }
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "pan-bind-session"
            session.mkdir(parents=True)
            runtime = _FakeRuntime(session / "runtime")
            planning = runtime.capture("edge-top-before-00")
            op = _SurveyOperator(
                session,
                runtime=runtime,
                session_id="campaign-atlas-pan-bind",
                lease_owner="test-owner",
            )
            tier_map = SimpleNamespace(
                observation=SimpleNamespace(screen=CampaignScreen.TIER_MAP)
            )
            try:
                with patch.object(op, "recognize", return_value=tier_map), patch(
                    "scripts.flow_delivery_campaign_atlas_bluestacks.measure_campaign_frame_pair",
                    return_value=SimpleNamespace(measurement=_FakeMeasurement()),
                ), patch(
                    "scripts.flow_delivery_campaign_atlas_bluestacks.registration_progress_outcome",
                    return_value="no_progress",
                ), patch(
                    "scripts.flow_delivery_campaign_atlas_bluestacks.registration_residual_report",
                    return_value=SimpleNamespace(
                        to_dict=lambda: {},
                        residual_px=0.0,
                        authorizes_input=False,
                    ),
                ), patch(
                    "scripts.flow_delivery_campaign_atlas_bluestacks.time.sleep",
                    return_value=None,
                ), patch(
                    "scripts.flow_delivery_campaign_atlas_bluestacks.asdict",
                    return_value={"residual_px": 0.0},
                ):
                    post, _prov, outcome, _measurement = op.dispatch_swipe(
                        phase=SurveyPhase.EDGE_TOP,
                        category=InputBudgetCategory.EDGE_CLAMP,
                        source_rel="runtime/frames/0001-source.png",
                        before=planning,
                        before_prov=SimpleNamespace(),
                        before_rel="runtime/frames/0001-edge-top-before-00.png",
                        swipe=(357, 560, 357, 720, 350),
                        action_key="edge-top-00",
                        target_identity="campaign-atlas-edge-top",
                        prior_progress_proven=False,
                    )
            finally:
                op.close()
            self.assertEqual(outcome, "no_progress")
            immediate_labels = [
                label
                for label, _ in runtime.captured_frames
                if label == "edge-top-00-immediate-before"
            ]
            self.assertEqual(len(immediate_labels), 1)
            fresh = next(
                captured
                for label, captured in runtime.captured_frames
                if label == "edge-top-00-immediate-before"
            )
            self.assertNotEqual(planning.sha256, fresh.sha256)
            self.assertEqual(len(runtime.swipes), 1)
            self.assertEqual(runtime.swipes[0]["sha256"], fresh.sha256)
            self.assertEqual(post.sha256, runtime.captured_frames[-1][1].sha256)
            labels_before_post = [label for label, _ in runtime.captured_frames[:-1]]
            self.assertEqual(labels_before_post.count("edge-top-00-immediate-before"), 1)

    def test_survey_tap_binds_issue_and_consume_to_one_immediate_before(self) -> None:
        """HUD digest drift: difficulty tap issue+consume share one fresh identity; one transport."""

        from types import SimpleNamespace
        from unittest.mock import patch

        import numpy as np

        from scripts.bluestacks_native_runtime import CapturedNativeFrame
        from scripts.flow_delivery_campaign_atlas_bluestacks import _SurveyOperator
        from tasks.campaign_atlas import InputBudgetCategory, SurveyPhase
        from tasks.campaign_auto_battle_vision import CampaignScreen

        stable_roi = (120, 220, 180, 280)

        class _FakeRuntime:
            def __init__(self, session: Path) -> None:
                self.session = session
                self.ordinal = 0
                self.taps: list[dict[str, object]] = []
                self.captured_frames: list[tuple[str, CapturedNativeFrame]] = []

            def capture(self, label: str) -> CapturedNativeFrame:
                import time as time_module

                self.ordinal += 1
                frame = np.zeros((1280, 800, 3), np.uint8)
                # Distinct pixels per capture simulate HUD digest drift across grabs.
                frame[0, 0] = (self.ordinal % 200, 20, 20)
                digest = f"{self.ordinal:064x}"
                path = self.session / "frames" / f"{self.ordinal:04d}-{label}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"png")
                captured = CapturedNativeFrame(
                    frame,
                    f"png-{self.ordinal}".encode(),
                    digest,
                    float(time_module.monotonic()),
                    path,
                )
                self.captured_frames.append((label, captured))
                return captured

            def tap(self, captured, *, target_identity, target_roi, action_key, consequential):
                self.taps.append(
                    {
                        "sha256": captured.sha256,
                        "target_identity": target_identity,
                        "target_roi": tuple(target_roi),
                        "action_key": action_key,
                        "consequential": consequential,
                    }
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "tap-bind-session"
            session.mkdir(parents=True)
            runtime = _FakeRuntime(session / "runtime")
            planning = runtime.capture("difficulty-tier-1-before")
            op = _SurveyOperator(
                session,
                runtime=runtime,
                session_id="campaign-atlas-tap-bind",
                lease_owner="test-owner",
            )
            tier_map = SimpleNamespace(
                observation=SimpleNamespace(
                    screen=CampaignScreen.TIER_MAP,
                    selected_tier=1,
                )
            )
            try:
                with patch.object(op, "recognize", return_value=tier_map), patch(
                    "scripts.flow_delivery_campaign_atlas_bluestacks.require_bound_survey_target",
                    return_value=stable_roi,
                ), patch(
                    "scripts.flow_delivery_campaign_atlas_bluestacks.time.sleep",
                    return_value=None,
                ), patch(
                    "scripts.flow_delivery_campaign_atlas_bluestacks._annotate_roi",
                    return_value="annotations/campaign-tier-1.png",
                ):
                    post, _prov = op.dispatch_bound_tap(
                        phase=SurveyPhase.DIFFICULTY_GEOMETRY_PAIR,
                        category=InputBudgetCategory.AUXILIARY,
                        source_rel="runtime/frames/0001-source.png",
                        before=planning,
                        before_rel="runtime/frames/0001-difficulty-tier-1-before.png",
                        identity="campaign-tier-1",
                        action_key="difficulty-tier-1",
                        expected_successor=lambda rec: (
                            rec.observation.screen == CampaignScreen.TIER_MAP
                            and rec.observation.selected_tier == 1
                        ),
                    )
            finally:
                op.close()
            immediate_labels = [
                label
                for label, _ in runtime.captured_frames
                if label == "difficulty-tier-1-immediate-before"
            ]
            self.assertEqual(len(immediate_labels), 1)
            fresh = next(
                captured
                for label, captured in runtime.captured_frames
                if label == "difficulty-tier-1-immediate-before"
            )
            self.assertNotEqual(planning.sha256, fresh.sha256)
            self.assertEqual(len(runtime.taps), 1)
            self.assertEqual(runtime.taps[0]["sha256"], fresh.sha256)
            self.assertEqual(runtime.taps[0]["target_roi"], stable_roi)
            self.assertEqual(post.sha256, runtime.captured_frames[-1][1].sha256)
            labels_before_post = [label for label, _ in runtime.captured_frames[:-1]]
            self.assertEqual(
                labels_before_post.count("difficulty-tier-1-immediate-before"), 1
            )

    def test_survey_tap_roi_drift_or_unknown_target_zero_transport(self) -> None:
        """ROI remeasure drift / unknown target fail closed with zero transport."""

        from types import SimpleNamespace
        from unittest.mock import patch

        import numpy as np

        from scripts.bluestacks_native_runtime import CapturedNativeFrame
        from scripts.flow_delivery_campaign_atlas_bluestacks import _SurveyOperator
        from tasks.campaign_atlas import InputBudgetCategory, SurveyPhase
        from tasks.campaign_auto_battle_vision import CampaignScreen

        proposal_roi = (120, 220, 180, 280)
        drifted_roi = (121, 220, 181, 280)

        class _FakeRuntime:
            def __init__(self, session: Path) -> None:
                self.session = session
                self.ordinal = 0
                self.taps: list[dict[str, object]] = []
                self.captured_frames: list[tuple[str, CapturedNativeFrame]] = []

            def capture(self, label: str) -> CapturedNativeFrame:
                import time as time_module

                self.ordinal += 1
                frame = np.zeros((1280, 800, 3), np.uint8)
                frame[0, 0] = (self.ordinal % 200, 30, 30)
                digest = f"{self.ordinal:064x}"
                path = self.session / "frames" / f"{self.ordinal:04d}-{label}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"png")
                captured = CapturedNativeFrame(
                    frame,
                    f"png-{self.ordinal}".encode(),
                    digest,
                    float(time_module.monotonic()),
                    path,
                )
                self.captured_frames.append((label, captured))
                return captured

            def tap(self, captured, **kwargs):
                self.taps.append({"sha256": captured.sha256, **kwargs})

        def _run_tap(*, measure_side_effect):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                session = root / "tap-fail-session"
                session.mkdir(parents=True)
                runtime = _FakeRuntime(session / "runtime")
                planning = runtime.capture("difficulty-tier-2-before")
                op = _SurveyOperator(
                    session,
                    runtime=runtime,
                    session_id="campaign-atlas-tap-fail",
                    lease_owner="test-owner",
                )
                tier_map = SimpleNamespace(
                    observation=SimpleNamespace(
                        screen=CampaignScreen.TIER_MAP,
                        selected_tier=2,
                    )
                )
                try:
                    with patch.object(op, "recognize", return_value=tier_map), patch(
                        "scripts.flow_delivery_campaign_atlas_bluestacks.require_bound_survey_target",
                        side_effect=measure_side_effect,
                    ), patch(
                        "scripts.flow_delivery_campaign_atlas_bluestacks.time.sleep",
                        return_value=None,
                    ):
                        with self.assertRaises(RuntimeError):
                            op.dispatch_bound_tap(
                                phase=SurveyPhase.DIFFICULTY_GEOMETRY_PAIR,
                                category=InputBudgetCategory.AUXILIARY,
                                source_rel="runtime/frames/0001-source.png",
                                before=planning,
                                before_rel="runtime/frames/0001-difficulty-tier-2-before.png",
                                identity="campaign-tier-2",
                                action_key="difficulty-tier-2",
                                expected_successor=lambda _rec: True,
                            )
                finally:
                    op.close()
                self.assertEqual(runtime.taps, [])
                immediate_count = sum(
                    1
                    for label, _ in runtime.captured_frames
                    if label == "difficulty-tier-2-immediate-before"
                )
                self.assertEqual(immediate_count, 1)
                return runtime

        # Remeasure on the same fresh frame drifts → zero transport.
        measure_calls = {"n": 0}

        def drifted_measure(*_args, **_kwargs):
            measure_calls["n"] += 1
            if measure_calls["n"] == 1:
                return proposal_roi
            return drifted_roi

        _run_tap(measure_side_effect=drifted_measure)
        self.assertGreaterEqual(measure_calls["n"], 2)

        # Unknown / unmeasurable target on the fresh frame → zero transport, no issue path transport.
        def unknown_measure(*_args, **_kwargs):
            raise RuntimeError("unknown survey target; zero transport")

        _run_tap(measure_side_effect=unknown_measure)


class CampaignAtlasVipResetDismissTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.popup_fixture = (
            cls.root / "tasks/assets/navigation/800x1280/reset_popup_source.png"
        )

    def test_known_continuation_seed_excludes_zero_input_vip_session(self) -> None:
        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            KNOWN_CONTINUATION_CUMULATIVE_SESSION_IDS,
            KNOWN_CONTINUATION_EXCLUDED_ZERO_INPUT_POPUP_SESSION_ID,
            KNOWN_CONTINUATION_PRIOR_COUNT,
            KNOWN_CONTINUATION_PRIOR_SESSION_IDS,
            KNOWN_CONTINUATION_RECONCILED_EDGE_CANDIDATE,
        )

        self.assertEqual(KNOWN_CONTINUATION_PRIOR_COUNT, 4)
        self.assertEqual(len(KNOWN_CONTINUATION_PRIOR_SESSION_IDS), 2)
        self.assertNotIn(
            KNOWN_CONTINUATION_EXCLUDED_ZERO_INPUT_POPUP_SESSION_ID,
            KNOWN_CONTINUATION_PRIOR_SESSION_IDS,
        )
        self.assertNotIn(
            KNOWN_CONTINUATION_EXCLUDED_ZERO_INPUT_POPUP_SESSION_ID,
            KNOWN_CONTINUATION_CUMULATIVE_SESSION_IDS,
        )
        self.assertEqual(
            KNOWN_CONTINUATION_CUMULATIVE_SESSION_IDS[-1],
            KNOWN_CONTINUATION_RECONCILED_EDGE_CANDIDATE["session_id"],
        )

    def test_vip_reset_dismiss_continues_after_confirmed_close(self) -> None:
        """Exact VIP modal Close: one AUX transport, TIER_MAP successor, continue-ready."""

        from types import SimpleNamespace
        from unittest.mock import patch

        import cv2
        import numpy as np

        from scripts.bluestacks_native_runtime import CapturedNativeFrame
        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            _SurveyOperator,
            dismiss_campaign_vip_reset_popup,
        )
        from tasks.campaign_atlas import InputBudgetCategory, InputLifecycle
        from tasks.campaign_auto_battle_vision import CampaignScreen

        popup = cv2.imread(str(self.popup_fixture))
        self.assertIsNotNone(popup)
        clear = np.zeros((1280, 800, 3), np.uint8)
        clear[:] = (30, 40, 50)

        class _FakeRuntime:
            def __init__(self, session: Path) -> None:
                self.session = session
                self.ordinal = 0
                self.taps: list[dict[str, object]] = []
                self.captured_frames: list[tuple[str, CapturedNativeFrame]] = []
                self._queue = [popup.copy(), clear.copy()]

            def capture(self, label: str) -> CapturedNativeFrame:
                import time as time_module

                self.ordinal += 1
                frame = self._queue.pop(0) if self._queue else clear.copy()
                digest = f"{self.ordinal:064x}"
                path = self.session / "frames" / f"{self.ordinal:04d}-{label}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"png")
                captured = CapturedNativeFrame(
                    frame,
                    f"png-{self.ordinal}".encode(),
                    digest,
                    float(time_module.monotonic()),
                    path,
                )
                self.captured_frames.append((label, captured))
                return captured

            def tap(self, captured, *, target_identity, target_roi, action_key, consequential):
                self.taps.append(
                    {
                        "sha256": captured.sha256,
                        "target_identity": target_identity,
                        "target_roi": tuple(target_roi),
                        "action_key": action_key,
                        "consequential": consequential,
                    }
                )

        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            runtime = _FakeRuntime(session / "runtime")
            op = _SurveyOperator(
                session,
                runtime=runtime,
                session_id="campaign-atlas-vip-dismiss",
                lease_owner="test-owner",
            )
            try:
                with patch(
                    "scripts.flow_delivery_campaign_atlas_bluestacks.time.sleep",
                    return_value=None,
                ), patch.object(
                    op,
                    "recognize",
                    side_effect=[
                        SimpleNamespace(
                            observation=SimpleNamespace(screen=CampaignScreen.TIER_MAP)
                        )
                    ],
                ):
                    result = dismiss_campaign_vip_reset_popup(
                        op, source_rel="runtime/frames/0001-source.png"
                    )
            finally:
                op.close()

            self.assertEqual(result["status"], "dismissed")
            self.assertTrue(result["transport_dispatched"])
            self.assertEqual(len(runtime.taps), 1)
            self.assertEqual(runtime.taps[0]["target_identity"], "reset-popup-close")
            self.assertEqual(runtime.taps[0]["action_key"], "vip-reset-close")
            self.assertEqual(op.vip_popup_input_count, 1)
            self.assertEqual(len(op.state.journal), 1)
            entry = op.state.journal[0]
            self.assertEqual(entry.budget_category, InputBudgetCategory.AUXILIARY)
            self.assertEqual(entry.lifecycle, InputLifecycle.TERMINAL)
            self.assertEqual(entry.terminal_classification, "dismissed_vip_reset_popup")
            self.assertFalse(op.state.unresolved)
            immediate = [
                label
                for label, _ in runtime.captured_frames
                if label == "vip-reset-close-immediate-before"
            ]
            self.assertEqual(len(immediate), 1)
            self.assertEqual(runtime.taps[0]["sha256"], runtime.captured_frames[0][1].sha256)

    def test_vip_reset_dismiss_wrong_text_zero_transport(self) -> None:
        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            _SurveyOperator,
            dismiss_campaign_vip_reset_popup,
        )
        from scripts.bluestacks_native_runtime import CapturedNativeFrame
        import numpy as np

        class _FakeRuntime:
            def __init__(self, session: Path) -> None:
                self.session = session
                self.ordinal = 0
                self.taps: list = []
                self.captured_frames: list = []

            def capture(self, label: str) -> CapturedNativeFrame:
                import time as time_module

                self.ordinal += 1
                frame = np.zeros((1280, 800, 3), np.uint8)
                digest = f"{self.ordinal:064x}"
                path = self.session / "frames" / f"{self.ordinal:04d}-{label}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"png")
                captured = CapturedNativeFrame(
                    frame,
                    f"png-{self.ordinal}".encode(),
                    digest,
                    float(time_module.monotonic()),
                    path,
                )
                self.captured_frames.append((label, captured))
                return captured

            def tap(self, *args, **kwargs):
                self.taps.append(kwargs)

        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            runtime = _FakeRuntime(session / "runtime")
            op = _SurveyOperator(
                session,
                runtime=runtime,
                session_id="campaign-atlas-vip-wrong",
                lease_owner="test-owner",
            )
            try:
                result = dismiss_campaign_vip_reset_popup(
                    op, source_rel="runtime/frames/0001-source.png"
                )
            finally:
                op.close()
            self.assertEqual(result["status"], "blocked")
            self.assertFalse(result["transport_dispatched"])
            self.assertEqual(result["reason"], "vip_popup_not_recognized")
            self.assertEqual(runtime.taps, [])
            self.assertEqual(op.vip_popup_input_count, 0)
            self.assertEqual(op.state.journal, [])

    def test_vip_reset_dismiss_unknown_successor_unresolved_after_transport(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import patch

        import cv2
        import numpy as np

        from scripts.bluestacks_native_runtime import CapturedNativeFrame
        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            _SurveyOperator,
            dismiss_campaign_vip_reset_popup,
        )
        from tasks.campaign_atlas import InputLifecycle
        from tasks.campaign_auto_battle_vision import CampaignScreen

        popup = cv2.imread(str(self.popup_fixture))
        self.assertIsNotNone(popup)
        # Post frame still looks like VIP (popup persists) → wrong successor.
        post_still = popup.copy()

        class _FakeRuntime:
            def __init__(self, session: Path) -> None:
                self.session = session
                self.ordinal = 0
                self.taps: list = []
                self.captured_frames: list = []
                self._queue = [popup.copy(), post_still]

            def capture(self, label: str) -> CapturedNativeFrame:
                import time as time_module

                self.ordinal += 1
                frame = self._queue.pop(0) if self._queue else post_still.copy()
                digest = f"{self.ordinal:064x}"
                path = self.session / "frames" / f"{self.ordinal:04d}-{label}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"png")
                captured = CapturedNativeFrame(
                    frame,
                    f"png-{self.ordinal}".encode(),
                    digest,
                    float(time_module.monotonic()),
                    path,
                )
                self.captured_frames.append((label, captured))
                return captured

            def tap(self, captured, *, target_identity, target_roi, action_key, consequential):
                self.taps.append({"sha256": captured.sha256, "action_key": action_key})

        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            runtime = _FakeRuntime(session / "runtime")
            op = _SurveyOperator(
                session,
                runtime=runtime,
                session_id="campaign-atlas-vip-unresolved",
                lease_owner="test-owner",
            )
            try:
                with patch(
                    "scripts.flow_delivery_campaign_atlas_bluestacks.time.sleep",
                    return_value=None,
                ), patch.object(
                    op,
                    "recognize",
                    return_value=SimpleNamespace(
                        observation=SimpleNamespace(screen=CampaignScreen.UNKNOWN)
                    ),
                ):
                    result = dismiss_campaign_vip_reset_popup(
                        op, source_rel="runtime/frames/0001-source.png"
                    )
            finally:
                op.close()
            self.assertEqual(result["status"], "unresolved")
            self.assertTrue(result["transport_dispatched"])
            self.assertEqual(len(runtime.taps), 1)
            self.assertEqual(op.vip_popup_input_count, 1)
            self.assertTrue(op.state.unresolved)
            self.assertEqual(op.state.journal[0].lifecycle, InputLifecycle.UNRESOLVED)

    def test_vip_reset_dismiss_one_input_maximum(self) -> None:
        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            _SurveyOperator,
            dismiss_campaign_vip_reset_popup,
        )
        from scripts.bluestacks_native_runtime import CapturedNativeFrame
        import numpy as np

        class _FakeRuntime:
            def __init__(self, session: Path) -> None:
                self.session = session
                self.taps: list = []

            def capture(self, label: str) -> CapturedNativeFrame:
                raise AssertionError("must not capture after input limit")

            def tap(self, *args, **kwargs):
                self.taps.append(kwargs)

        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            runtime = _FakeRuntime(session / "runtime")
            op = _SurveyOperator(
                session,
                runtime=runtime,
                session_id="campaign-atlas-vip-limit",
                lease_owner="test-owner",
            )
            op.vip_popup_input_count = 1
            try:
                result = dismiss_campaign_vip_reset_popup(
                    op, source_rel="runtime/frames/0001-source.png"
                )
            finally:
                op.close()
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["reason"], "vip_popup_input_limit_reached")
            self.assertFalse(result["transport_dispatched"])
            self.assertEqual(runtime.taps, [])

    def test_live_survey_wires_vip_dismiss_before_unsupported_start(self) -> None:
        import scripts.flow_delivery_campaign_atlas_bluestacks as mod

        source = Path(mod.__file__).read_text(encoding="utf-8")
        unsupported = source.index('unsupported survey start screen:')
        vip_call = source.index("dismiss_campaign_vip_reset_popup(")
        self.assertLess(vip_call, unsupported)
        self.assertIn("recognize_reset_popup(before.frame)", source)
        self.assertIn('vip_dismiss.get("status") != "dismissed"', source)
        self.assertIn("DISMISS_RESET_POPUP", source)
        self.assertIn("CAMPAIGN_TIER_MAP", source)


class CampaignAtlasOfflineReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.retained = (
            cls.root
            / ".local-captures"
            / "flow-delivery"
            / "CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION"
            / "survey-20260724T004227747200Z"
        )

    def _require_retained(self) -> Path:
        if not self.retained.is_dir():
            self.skipTest("retained edge-top survey session fixtures unavailable")
        before = self.retained / "runtime/frames/0003-edge-top-00-immediate-before.png"
        post = self.retained / "runtime/frames/0004-edge-top-00-post.png"
        if not before.is_file() or not post.is_file():
            self.skipTest("retained edge-top before/post frames unavailable")
        return self.retained

    def _seed_unresolved_store(
        self,
        session: Path,
        *,
        action_key: str,
        frame_sha256: str,
    ) -> str:
        from safe_action_core import (
            ActionClass,
            ActionIntent,
            CentralPolicy,
            Observation,
            PolicyRequest,
            SafetyStore,
            TransportResult,
        )
        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            CAMPAIGN_PROFILE_ID,
            FLOW_ID,
            SURVEY_PAN_POSTCONDITION,
            SURVEY_PAN_SEMANTIC_ACTION,
        )

        observation = Observation(
            frame_sha256=frame_sha256,
            capture_completed_monotonic=1.0,
            runtime_profile_id=CAMPAIGN_PROFILE_ID,
            width=800,
            height=1280,
            valid_png=True,
            corrupt=False,
            black=False,
            source_state="CAMPAIGN_TIER_MAP",
            overlay_state="none_observed",
            target_identity="edge-top",
            target_roi=(300, 500, 400, 600),
            recognized=True,
            consequence="navigate_zero_cost",
            cost_type="none",
            cost_amount=0,
            quantity=1,
            expected_postcondition=SURVEY_PAN_POSTCONDITION,
            evidence_refs=("campaign-atlas:test",),
            package_foreground=True,
            os_surface=False,
            hard_stop_detected=False,
        )
        action_id = f"{FLOW_ID}:{action_key}:testrecon01"
        request = PolicyRequest(
            action_id=action_id,
            action_key=action_key,
            task_id=FLOW_ID,
            task_mode="supervised_validation",
            semantic_action=SURVEY_PAN_SEMANTIC_ACTION,
            expected_runtime_profile_id=CAMPAIGN_PROFILE_ID,
            observation=observation,
            monotonic_now=2.0,
            observation_max_age_seconds=30.0,
            dispatch_max_age_seconds=15.0,
            lease_owner="test-reconcile",
            lease_valid=True,
            unresolved_action=False,
            duplicate_action_key=False,
            action_class=ActionClass.NAVIGATION_ONLY,
            runtime_session_id=session.name,
        )
        policy = CentralPolicy(supervised_tasks=frozenset({FLOW_ID, "MVP-QUEST-TO-CLAIM"}))
        decision = policy.evaluate(request)
        intent = ActionIntent(
            action_id=action_id,
            action_key=action_key,
            task_id=FLOW_ID,
            semantic_action=SURVEY_PAN_SEMANTIC_ACTION,
            source_state=observation.source_state,
            target_identity=observation.target_identity,
            target_roi=observation.target_roi,
            source_frame_sha256=observation.frame_sha256,
            source_frame_captured_at=observation.capture_completed_monotonic,
            runtime_profile_id=observation.runtime_profile_id,
            game_day_id="test-day",
            expected_postcondition=observation.expected_postcondition,
            consequence=observation.consequence,
            cost_type=observation.cost_type,
            cost_amount=observation.cost_amount,
            quantity=observation.quantity,
            evidence_refs=observation.evidence_refs,
            consequential=False,
        )
        store = SafetyStore(session / "campaign-atlas-survey-safety.sqlite3")
        try:
            store.acquire_lease("test-reconcile", 1000.0, 60.0)
            store.prepare_action(intent, decision, 1000.0)
            store.mark_input_sent(
                action_id,
                1000.1,
                TransportResult(True, "CAMPAIGN_ATLAS_PAN_DISPATCHED"),
            )
            store.mark_unresolved(
                action_id,
                1000.2,
                "postcondition_observation_failure",
                {"exception_type": "ValueError"},
            )
        finally:
            store.close()
        return action_id

    def _build_retained_style_session(self, dest_root: Path) -> Path:
        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            FLOW_ID,
            KNOWN_CONTINUATION_RECONCILED_EDGE_CANDIDATE,
        )

        retained = self._require_retained()
        action_key = str(KNOWN_CONTINUATION_RECONCILED_EDGE_CANDIDATE["action_key"])
        session = dest_root / FLOW_ID / str(KNOWN_CONTINUATION_RECONCILED_EDGE_CANDIDATE["session_id"])
        frames = session / "runtime" / "frames"
        frames.mkdir(parents=True)
        before_src = retained / "runtime/frames/0003-edge-top-00-immediate-before.png"
        post_src = retained / "runtime/frames/0004-edge-top-00-post.png"
        before_dst = frames / "0003-edge-top-00-immediate-before.png"
        post_dst = frames / "0004-edge-top-00-post.png"
        before_dst.write_bytes(before_src.read_bytes())
        post_dst.write_bytes(post_src.read_bytes())
        # Ensure post mtime is not earlier than before.
        import os
        import time as time_module

        now = time_module.time()
        os.utime(before_dst, (now - 2, now - 2))
        os.utime(post_dst, (now - 1, now - 1))
        (session / f"{action_key}-transport.json").write_text(
            json.dumps(
                {
                    "action_key": action_key,
                    "authority": "SafeActionExecutor",
                    "swipe": [357, 560, 357, 720, 350],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        (session / "survey-lifecycle.jsonl").write_text(
            json.dumps(
                {
                    "lifecycle": "prepared",
                    "input_ordinal": 1,
                    "phase": "edge_top",
                    "category": "edge_clamp",
                    "swipe": [357, 560, 357, 720, 350],
                    "prior_progress_proven": False,
                },
                sort_keys=True,
            )
            + "\n"
            + json.dumps(
                {
                    "budget_error": None,
                    "input_ordinal": 1,
                    "lifecycle": "input_sent",
                    "transport_inputs_used": 5,
                },
                sort_keys=True,
            )
            + "\n"
            + json.dumps(
                {
                    "input_ordinal": 1,
                    "lifecycle": "unresolved",
                    "terminal": "unresolved_safe_action:SafeActionExecutor unresolved",
                    "transport_inputs_used": 5,
                    "unresolved": True,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        # Historical journal intentionally wrong (planning frame both sides).
        (session / "journal.jsonl").write_text(
            json.dumps(
                {
                    "budget_category": "edge_clamp",
                    "evidence": {
                        "immediate_before_path": "runtime/frames/0002-edge-top-before-00.png",
                        "immediate_post_path": "runtime/frames/0002-edge-top-before-00.png",
                        "semantic_result_path": f"{action_key}-transport.json",
                        "source_path": "runtime/frames/0001-source.png",
                        "transport_record_path": f"{action_key}-transport.json",
                    },
                    "identical_retry": False,
                    "input_ordinal": 1,
                    "lifecycle": "unresolved",
                    "phase": "edge_top",
                    "prior_progress_proven": False,
                    "swipe_geometry": [357, 560, 357, 720, 350],
                    "terminal_classification": "unresolved_safe_action:test",
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (session / "survey-accounting.json").write_text(
            json.dumps(
                {
                    "accounting": {
                        "auxiliary_used": 4,
                        "edge_clamp_used": 1,
                        "maximum_auxiliary": 16,
                        "maximum_edge_clamp": 128,
                        "maximum_overlap": 128,
                        "maximum_transport_inputs": 272,
                        "overlap_used": 0,
                        "transport_inputs_used": 5,
                    },
                    "input_sent_count": 1,
                    "journal_len": 1,
                    "open_prepared": False,
                    "prior_inputs_seeded": 4,
                    "session_navigation_inputs_sent": 1,
                    "transport_dispatched": True,
                    "transport_inputs_used": 5,
                    "unresolved": True,
                    "updated_at_utc": "2026-07-24T00:42:40Z",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        self._seed_unresolved_store(
            session,
            action_key=action_key,
            frame_sha256="a" * 64,
        )
        return session

    def test_capture_provenance_separates_transport_and_semantic_sha(self) -> None:
        from types import SimpleNamespace

        import hashlib
        import numpy as np

        from scripts.bluestacks_native_runtime import CapturedNativeFrame
        from scripts.flow_delivery_campaign_atlas_bluestacks import _SurveyOperator
        from tasks.campaign_atlas_vision import frame_digest

        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            (session / "runtime" / "frames").mkdir(parents=True)
            frame = np.zeros((1280, 800, 3), dtype=np.uint8)
            frame[600:700, 350:450] = (40, 80, 120)
            payload = b"\x89PNG\r\n\x1a\n" + b"not-decoded-payload-for-hash-only"
            path = session / "runtime" / "frames" / "0001-test.png"
            path.write_bytes(payload)
            captured = CapturedNativeFrame(
                frame,
                payload,
                hashlib.sha256(payload).hexdigest(),
                1.5,
                path,
            )

            class _Runtime:
                def __init__(self) -> None:
                    self.session = session / "runtime"

                def capture(self, label: str):
                    del label
                    return captured

            op = _SurveyOperator(
                session,
                runtime=_Runtime(),
                session_id="campaign-atlas-prov",
                lease_owner="test-owner",
            )
            try:
                out, prov = op.capture("label")
            finally:
                op.close()
            self.assertIs(out, captured)
            self.assertEqual(prov.transport_sha256, captured.sha256)
            self.assertEqual(prov.semantic_sha256, frame_digest(frame))
            self.assertNotEqual(prov.transport_sha256, prov.semantic_sha256)
            self.assertEqual((prov.width, prov.height), (800, 1280))

    def test_close_dispatch_exception_keeps_fresh_before_and_post_paths(self) -> None:
        from types import SimpleNamespace

        from scripts.flow_delivery_campaign_atlas_bluestacks import _SurveyOperator
        from tasks.campaign_atlas import (
            InputBudgetCategory,
            InputLifecycle,
            SurveyPhase,
        )

        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            (session / "runtime").mkdir(parents=True)
            op = _SurveyOperator(
                session,
                runtime=SimpleNamespace(session=session / "runtime", capture=lambda *_a, **_k: None),
                session_id="campaign-atlas-journal-paths",
                lease_owner="test-owner",
            )
            try:
                ordinal = op.prepare_input(
                    phase=SurveyPhase.EDGE_TOP,
                    category=InputBudgetCategory.EDGE_CLAMP,
                    before_rel="runtime/frames/0003-edge-top-00-immediate-before.png",
                    transport_rel="edge-top-00-transport.json",
                    source_rel="runtime/frames/0001-source.png",
                    swipe=(1, 2, 3, 4, 5),
                    prior_progress_proven=False,
                    planned_terminal="edge-top",
                )
                op.mark_input_sent(ordinal, category=InputBudgetCategory.EDGE_CLAMP)
                op._close_dispatch_exception(
                    ordinal=ordinal,
                    source_rel="runtime/frames/0001-source.png",
                    before_rel="runtime/frames/0003-edge-top-00-immediate-before.png",
                    transport_rel="edge-top-00-transport.json",
                    exc=RuntimeError("postcondition boom"),
                    transport_gate={"attempted": True, "input_sent": True},
                    post_rel="runtime/frames/0004-edge-top-00-post.png",
                )
                entry = op.state.journal[0]
            finally:
                op.close()
            self.assertEqual(entry.lifecycle, InputLifecycle.UNRESOLVED)
            self.assertEqual(
                entry.evidence.immediate_before_path,
                "runtime/frames/0003-edge-top-00-immediate-before.png",
            )
            self.assertEqual(
                entry.evidence.immediate_post_path,
                "runtime/frames/0004-edge-top-00-post.png",
            )
            self.assertNotEqual(
                entry.evidence.immediate_before_path,
                entry.evidence.immediate_post_path,
            )
            # Planning frame must not be used for both sides.
            self.assertNotIn("0002-edge-top-before", entry.evidence.immediate_before_path)
            self.assertNotIn("0002-edge-top-before", entry.evidence.immediate_post_path)

    def test_offline_reconciliation_happy_path_and_seed_gate(self) -> None:
        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            KNOWN_CONTINUATION_CUMULATIVE_WITH_RECONCILED_EDGE,
            KNOWN_CONTINUATION_MIXED_CATEGORY,
            KNOWN_CONTINUATION_RECONCILED_EDGE_CANDIDATE,
            reconcile_campaign_atlas_survey_action_offline,
            resolve_evidence_backed_prior_auxiliary_seed,
        )
        from tasks.campaign_atlas import (
            ACTIVATED_AUXILIARY_INPUTS,
            ACTIVATED_EDGE_STEPS_TOTAL,
            ACTIVATED_TRANSPORT_INPUT_CEILING,
        )
        from safe_action_core import SafetyStore

        retained = self._require_retained()
        del retained
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Reuse existing aux prior writer from collector suite.
            suite = CampaignAtlasCollectorTests()
            suite._write_known_prior_aux_sessions(root)
            session = self._build_retained_style_session(root)
            action_key = str(KNOWN_CONTINUATION_RECONCILED_EDGE_CANDIDATE["action_key"])

            with self.assertRaises(RuntimeError):
                resolve_evidence_backed_prior_auxiliary_seed(
                    artifact_root=root,
                    claimed_navigation_inputs_used=5,
                )

            result = reconcile_campaign_atlas_survey_action_offline(
                session, action_key=action_key
            )
            self.assertEqual(result["status"], "reconciled")
            self.assertTrue(result["zero_input"])
            self.assertEqual(result["outcome"], "progress")
            self.assertTrue((session / result["receipt"]).is_file())
            durable = json.loads((session / "survey-accounting.json").read_text(encoding="utf-8"))
            self.assertFalse(durable["unresolved"])
            self.assertFalse(durable["open_prepared"])
            # Historical wrong journal row preserved; reconciliation appends.
            journal_lines = [
                line
                for line in (session / "journal.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertGreaterEqual(len(journal_lines), 2)
            historical = json.loads(journal_lines[0])
            self.assertEqual(
                historical["evidence"]["immediate_before_path"],
                "runtime/frames/0002-edge-top-before-00.png",
            )
            receipt_row = json.loads(journal_lines[-1])
            self.assertEqual(
                receipt_row["evidence"]["immediate_before_path"],
                "runtime/frames/0003-edge-top-00-immediate-before.png",
            )
            self.assertEqual(
                receipt_row["evidence"]["immediate_post_path"],
                "runtime/frames/0004-edge-top-00-post.png",
            )
            store = SafetyStore(session / "campaign-atlas-survey-safety.sqlite3")
            try:
                row = store.get_action_by_key(action_key)
                self.assertEqual(row["final_status"], "confirmed")
            finally:
                store.close()

            accounting, meta = resolve_evidence_backed_prior_auxiliary_seed(
                artifact_root=root,
                claimed_navigation_inputs_used=KNOWN_CONTINUATION_CUMULATIVE_WITH_RECONCILED_EDGE,
            )
            self.assertEqual(accounting.transport_inputs_used, 5)
            self.assertEqual(accounting.auxiliary_used, 4)
            self.assertEqual(accounting.edge_clamp_used, 1)
            self.assertEqual(meta["prior_category"], KNOWN_CONTINUATION_MIXED_CATEGORY)
            self.assertEqual(
                accounting.maximum_transport_inputs - accounting.transport_inputs_used,
                ACTIVATED_TRANSPORT_INPUT_CEILING - 5,
            )
            self.assertEqual(
                accounting.maximum_edge_clamp - accounting.edge_clamp_used,
                ACTIVATED_EDGE_STEPS_TOTAL - 1,
            )
            self.assertEqual(
                accounting.maximum_auxiliary - accounting.auxiliary_used,
                ACTIVATED_AUXILIARY_INPUTS - 4,
            )
            self.assertEqual(
                result["continuation_seed_after_receipt"]["remaining_transport"],
                267,
            )
            self.assertEqual(
                result["continuation_seed_after_receipt"]["remaining_edge_clamp"],
                127,
            )
            self.assertEqual(
                result["continuation_seed_after_receipt"]["remaining_auxiliary"],
                12,
            )

    def test_offline_reconciliation_rejects_no_transport_and_ambiguous(self) -> None:
        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            FLOW_ID,
            KNOWN_CONTINUATION_RECONCILED_EDGE_CANDIDATE,
            reconcile_campaign_atlas_survey_action_offline,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = self._build_retained_style_session(root)
            action_key = str(KNOWN_CONTINUATION_RECONCILED_EDGE_CANDIDATE["action_key"])
            # No transport receipt.
            (session / f"{action_key}-transport.json").unlink()
            with self.assertRaises(RuntimeError) as missing_transport:
                reconcile_campaign_atlas_survey_action_offline(session, action_key=action_key)
            self.assertIn("transport", str(missing_transport.exception).casefold())

            session2 = root / FLOW_ID / "survey-20260724T009999999999Z"
            # Rebuild with clamp-like identical frames for ambiguous/no-progress reject.
            frames = session2 / "runtime" / "frames"
            frames.mkdir(parents=True)
            retained = self._require_retained()
            payload = (
                retained / "runtime/frames/0003-edge-top-00-immediate-before.png"
            ).read_bytes()
            (frames / "0003-edge-top-00-immediate-before.png").write_bytes(payload)
            (frames / "0004-edge-top-00-post.png").write_bytes(payload)
            (session2 / "edge-top-00-transport.json").write_text(
                json.dumps(
                    {
                        "action_key": "edge-top-00",
                        "authority": "SafeActionExecutor",
                        "swipe": [1, 2, 3, 4, 5],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            (session2 / "survey-lifecycle.jsonl").write_text(
                json.dumps({"lifecycle": "prepared", "input_ordinal": 1, "category": "edge_clamp"})
                + "\n"
                + json.dumps({"lifecycle": "input_sent", "input_ordinal": 1})
                + "\n"
                + json.dumps(
                    {
                        "lifecycle": "unresolved",
                        "input_ordinal": 1,
                        "unresolved": True,
                        "terminal": "x",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (session2 / "journal.jsonl").write_text("", encoding="utf-8")
            (session2 / "survey-accounting.json").write_text(
                json.dumps(
                    {
                        "transport_inputs_used": 1,
                        "unresolved": True,
                        "transport_dispatched": True,
                        "open_prepared": False,
                        "accounting": {
                            "auxiliary_used": 0,
                            "edge_clamp_used": 1,
                            "overlap_used": 0,
                            "maximum_auxiliary": 16,
                            "maximum_edge_clamp": 128,
                            "maximum_overlap": 128,
                            "maximum_transport_inputs": 272,
                            "transport_inputs_used": 1,
                        },
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            self._seed_unresolved_store(
                session2, action_key="edge-top-00", frame_sha256="b" * 64
            )
            with self.assertRaises(RuntimeError) as clamp:
                reconcile_campaign_atlas_survey_action_offline(
                    session2, action_key="edge-top-00"
                )
            message = str(clamp.exception).casefold()
            self.assertTrue("clamp" in message or "progress" in message or "no_progress" in message)

    def test_reconciled_edge_continuation_resumes_at_edge_top_01(self) -> None:
        """claimed=5 seed + TIER_MAP resume skips edge-top-00 and starts edge-top-01."""

        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            KNOWN_CONTINUATION_CUMULATIVE_WITH_RECONCILED_EDGE,
            KNOWN_CONTINUATION_MIXED_CATEGORY,
            KNOWN_CONTINUATION_RECONCILED_EDGE_CANDIDATE,
            reconcile_campaign_atlas_survey_action_offline,
            resolve_evidence_backed_prior_auxiliary_seed,
            resolve_reconciled_edge_coverage_resume,
        )
        from tasks.campaign_auto_battle import CampaignScreen

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            suite = CampaignAtlasCollectorTests()
            suite._write_known_prior_aux_sessions(root)
            session = self._build_retained_style_session(root)
            action_key = str(KNOWN_CONTINUATION_RECONCILED_EDGE_CANDIDATE["action_key"])
            reconcile_campaign_atlas_survey_action_offline(session, action_key=action_key)
            accounting, meta = resolve_evidence_backed_prior_auxiliary_seed(
                artifact_root=root,
                claimed_navigation_inputs_used=KNOWN_CONTINUATION_CUMULATIVE_WITH_RECONCILED_EDGE,
            )
            self.assertEqual(accounting.transport_inputs_used, 5)
            self.assertEqual(accounting.auxiliary_used, 4)
            self.assertEqual(accounting.edge_clamp_used, 1)
            self.assertEqual(meta["prior_category"], KNOWN_CONTINUATION_MIXED_CATEGORY)
            self.assertEqual(meta["reconciled_edge_action_key"], action_key)
            self.assertTrue(str(meta["reconciled_edge_receipt"]).endswith(".json"))

            resume = resolve_reconciled_edge_coverage_resume(
                meta, current_screen=CampaignScreen.TIER_MAP
            )
            self.assertTrue(resume["required"])
            self.assertEqual(resume["reconciled_action_key"], "edge-top-00")
            self.assertEqual(resume["next_action_key"], "edge-top-01")
            self.assertEqual(resume["edge_start_step_by_direction"]["top"], 1)
            self.assertEqual(resume["edge_start_step_by_direction"]["right"], 0)
            self.assertIsNotNone(resume["prior_progress_swipe"])

            with self.assertRaises(RuntimeError) as home_block:
                resolve_reconciled_edge_coverage_resume(
                    meta, current_screen=CampaignScreen.HOME_BASE
                )
            self.assertIn("TIER_MAP", str(home_block.exception))

            broken = dict(meta)
            broken.pop("reconciled_edge_receipt", None)
            with self.assertRaises(RuntimeError) as missing_receipt:
                resolve_reconciled_edge_coverage_resume(
                    broken, current_screen=CampaignScreen.TIER_MAP
                )
            self.assertIn("progress state", str(missing_receipt.exception).casefold())

            aux_only = {
                "prior_category": "auxiliary",
                "prior_inputs_seeded": 4,
                "prior_edge_clamp_seeded": 0,
            }
            empty = resolve_reconciled_edge_coverage_resume(
                aux_only, current_screen=CampaignScreen.HOME_BASE
            )
            self.assertFalse(empty["required"])
            self.assertEqual(empty["edge_start_step_by_direction"]["top"], 0)

    def test_pnsctl_offline_reconcile_command_is_zero_input(self) -> None:
        import scripts.pnsctl as pnsctl
        import scripts.flow_delivery_campaign_atlas_bluestacks as mod

        source = Path(pnsctl.__file__).read_text(encoding="utf-8")
        self.assertIn("reconcile-campaign-atlas-survey-action", source)
        self.assertIn("bluestacks_reconcile_campaign_atlas_survey_action", source)
        self.assertIn("zero_input", source)
        mod_source = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertIn("def reconcile_campaign_atlas_survey_action_offline", mod_source)
        self.assertNotIn("runtime.swipe", mod_source[mod_source.index("def reconcile_campaign_atlas_survey_action_offline"):])
        self.assertNotIn(
            "runtime.tap",
            mod_source[mod_source.index("def reconcile_campaign_atlas_survey_action_offline") :],
        )

    def test_traversal_seed_91_resumes_at_difficulty_tier2_only(self) -> None:
        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            KNOWN_CONTINUATION_CUMULATIVE_WITH_TRAVERSAL,
            KNOWN_CONTINUATION_TRAVERSAL_RESUME_CATEGORY,
            KNOWN_CONTINUATION_TRAVERSAL_SESSION,
            resolve_difficulty_tier2_coverage_resume,
            resolve_evidence_backed_prior_auxiliary_seed,
            resolve_reconciled_edge_coverage_resume,
            write_survey_continuation_reference,
            _seeded_complete_accounting_reconciles,
            _session_scoped_report_accounting,
        )
        from tasks.campaign_atlas import InputBudgetAccounting
        from tasks.campaign_auto_battle import CampaignScreen
        from types import SimpleNamespace

        artifact_root = (
            Path(__file__).resolve().parents[1] / ".local-captures" / "flow-delivery"
        )
        session = (
            artifact_root
            / "CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION"
            / str(KNOWN_CONTINUATION_TRAVERSAL_SESSION["session_id"])
        )
        if not session.is_dir():
            self.skipTest("accepted traversal session unavailable")

        accounting, meta = resolve_evidence_backed_prior_auxiliary_seed(
            artifact_root=artifact_root,
            claimed_navigation_inputs_used=KNOWN_CONTINUATION_CUMULATIVE_WITH_TRAVERSAL,
        )
        self.assertEqual(accounting.transport_inputs_used, 91)
        self.assertEqual(accounting.auxiliary_used, 5)
        self.assertEqual(accounting.edge_clamp_used, 24)
        self.assertEqual(accounting.overlap_used, 62)
        self.assertEqual(meta["prior_category"], KNOWN_CONTINUATION_TRAVERSAL_RESUME_CATEGORY)
        self.assertEqual(meta["resume_action_key"], "difficulty-tier-2")
        skip = set(meta["skip_prior_action_keys"])
        self.assertIn("difficulty-tier-1", skip)
        self.assertNotIn("difficulty-tier-2", skip)
        self.assertTrue(any(k.startswith("edge-") for k in skip))
        self.assertTrue(any(k.startswith("overlap-") for k in skip))
        self.assertEqual(len(skip), 86)

        resume = resolve_difficulty_tier2_coverage_resume(
            meta, current_screen=CampaignScreen.TIER_MAP
        )
        self.assertTrue(resume["required"])
        self.assertEqual(resume["resume_action_key"], "difficulty-tier-2")
        edge = resolve_reconciled_edge_coverage_resume(
            meta, current_screen=CampaignScreen.TIER_MAP
        )
        self.assertFalse(edge["required"])

        with self.assertRaises(RuntimeError) as home_block:
            resolve_difficulty_tier2_coverage_resume(
                meta, current_screen=CampaignScreen.HOME_BASE
            )
        self.assertIn("TIER_MAP", str(home_block.exception))

        with self.assertRaises(RuntimeError):
            resolve_evidence_backed_prior_auxiliary_seed(
                artifact_root=artifact_root,
                claimed_navigation_inputs_used=90,
            )

        with tempfile.TemporaryDirectory() as directory:
            cont_session = Path(directory) / "continuation"
            cont_session.mkdir()
            ref = write_survey_continuation_reference(cont_session, meta)
            self.assertEqual(ref, "survey-continuation.json")
            payload = json.loads(
                (cont_session / "survey-continuation.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                payload["continuation_kind"],
                "evidence_backed_traversal_resume_difficulty_tier2",
            )
            self.assertEqual(payload["prior_inputs_seeded"], 91)
            # Session-vs-cumulative: empty continuation journal + prior 91 == cumulative 91.
            state = SimpleNamespace(
                prior_inputs_seeded=91,
                prior_continuation=meta,
                accounting=accounting,
                journal=[],
            )
            session_accounting = _session_scoped_report_accounting(state)
            self.assertEqual(session_accounting.transport_inputs_used, 0)
            self.assertTrue(
                _seeded_complete_accounting_reconciles(
                    report_accounting=session_accounting,
                    delivery_accounting=accounting.to_dict(),
                    prior_continuation=meta,
                    cumulative_used=91,
                    session_sent=0,
                )
            )
            # After one new AUX (tier2), session=1 and cumulative=92 without fabricating prior rows.
            after = InputBudgetAccounting(
                auxiliary_used=6,
                edge_clamp_used=24,
                overlap_used=62,
            )
            state_after = SimpleNamespace(
                prior_inputs_seeded=91,
                prior_continuation=meta,
                accounting=after,
                journal=[SimpleNamespace(budget_category=__import__(
                    "tasks.campaign_atlas", fromlist=["InputBudgetCategory"]
                ).InputBudgetCategory.AUXILIARY)],
            )
            session_after = _session_scoped_report_accounting(state_after)
            self.assertEqual(session_after.transport_inputs_used, 1)
            self.assertEqual(session_after.auxiliary_used, 1)
            self.assertEqual(session_after.edge_clamp_used, 0)
            self.assertEqual(session_after.overlap_used, 0)
            self.assertTrue(
                _seeded_complete_accounting_reconciles(
                    report_accounting=session_after,
                    delivery_accounting=after.to_dict(),
                    prior_continuation=meta,
                    cumulative_used=92,
                    session_sent=1,
                )
            )

    def test_exit_only_seed_92_skips_traversal_and_both_difficulty_taps(self) -> None:
        from scripts.flow_delivery_campaign_atlas_bluestacks import (
            KNOWN_CONTINUATION_CUMULATIVE_WITH_TIER2_EXIT,
            KNOWN_CONTINUATION_EXIT_RESUME_CATEGORY,
            KNOWN_CONTINUATION_EXIT_SESSION_IDS,
            resolve_campaign_exit_only_resume,
            resolve_difficulty_tier2_coverage_resume,
            resolve_evidence_backed_prior_auxiliary_seed,
            resolve_reconciled_edge_coverage_resume,
            write_survey_continuation_reference,
            _seeded_complete_accounting_reconciles,
            _session_scoped_report_accounting,
        )
        from tasks.campaign_atlas import InputBudgetAccounting, InputBudgetCategory
        from tasks.campaign_auto_battle import CampaignScreen
        from types import SimpleNamespace

        artifact_root = (
            Path(__file__).resolve().parents[1] / ".local-captures" / "flow-delivery"
        )
        session = (
            artifact_root
            / "CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION"
            / "survey-20260724T021222146973Z"
        )
        if not session.is_dir():
            self.skipTest("accepted tier2-exit session unavailable")

        accounting, meta = resolve_evidence_backed_prior_auxiliary_seed(
            artifact_root=artifact_root,
            claimed_navigation_inputs_used=KNOWN_CONTINUATION_CUMULATIVE_WITH_TIER2_EXIT,
        )
        self.assertEqual(accounting.transport_inputs_used, 92)
        self.assertEqual(accounting.auxiliary_used, 6)
        self.assertEqual(accounting.edge_clamp_used, 24)
        self.assertEqual(accounting.overlap_used, 62)
        self.assertEqual(meta["prior_category"], KNOWN_CONTINUATION_EXIT_RESUME_CATEGORY)
        self.assertEqual(meta["resume_action_key"], "campaign-exit-home")
        self.assertEqual(list(meta["prior_session_ids"]), list(KNOWN_CONTINUATION_EXIT_SESSION_IDS))
        skip = set(meta["skip_prior_action_keys"])
        self.assertIn("difficulty-tier-1", skip)
        self.assertIn("difficulty-tier-2", skip)
        self.assertNotIn("campaign-exit-home", skip)
        self.assertTrue(any(k.startswith("edge-") for k in skip))
        self.assertTrue(any(k.startswith("overlap-") for k in skip))

        resume = resolve_campaign_exit_only_resume(
            meta, current_screen=CampaignScreen.TIER_MAP
        )
        self.assertTrue(resume["required"])
        self.assertEqual(resume["resume_action_key"], "campaign-exit-home")
        self.assertFalse(
            resolve_difficulty_tier2_coverage_resume(
                meta, current_screen=CampaignScreen.TIER_MAP
            )["required"]
        )
        self.assertFalse(
            resolve_reconciled_edge_coverage_resume(
                meta, current_screen=CampaignScreen.TIER_MAP
            )["required"]
        )
        with self.assertRaises(RuntimeError) as home_block:
            resolve_campaign_exit_only_resume(
                meta, current_screen=CampaignScreen.HOME_BASE
            )
        self.assertIn("TIER_MAP", str(home_block.exception))

        source = Path(
            __file__
        ).resolve().parents[1] / "scripts" / "flow_delivery_campaign_atlas_bluestacks.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn("def resolve_campaign_exit_only_resume", text)
        self.assertIn('action_key="campaign-exit-home"', text)
        self.assertIn("campaign_exit_only_coverage_resume", text)
        self.assertIn("_hydrate_retained_survey_completion_evidence", text)

        with tempfile.TemporaryDirectory() as directory:
            cont_session = Path(directory) / "continuation"
            cont_session.mkdir()
            ref = write_survey_continuation_reference(cont_session, meta)
            self.assertEqual(ref, "survey-continuation.json")
            payload = json.loads(
                (cont_session / "survey-continuation.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                payload["continuation_kind"],
                "evidence_backed_traversal_resume_campaign_exit",
            )
            self.assertEqual(payload["prior_inputs_seeded"], 92)
            state = SimpleNamespace(
                prior_inputs_seeded=92,
                prior_continuation=meta,
                accounting=accounting,
                journal=[],
            )
            session_accounting = _session_scoped_report_accounting(state)
            self.assertEqual(session_accounting.transport_inputs_used, 0)
            self.assertTrue(
                _seeded_complete_accounting_reconciles(
                    report_accounting=session_accounting,
                    delivery_accounting=accounting.to_dict(),
                    prior_continuation=meta,
                    cumulative_used=92,
                    session_sent=0,
                )
            )
            after = InputBudgetAccounting(
                auxiliary_used=7,
                edge_clamp_used=24,
                overlap_used=62,
            )
            state_after = SimpleNamespace(
                prior_inputs_seeded=92,
                prior_continuation=meta,
                accounting=after,
                journal=[
                    SimpleNamespace(budget_category=InputBudgetCategory.AUXILIARY)
                ],
            )
            session_after = _session_scoped_report_accounting(state_after)
            self.assertEqual(session_after.transport_inputs_used, 1)
            self.assertEqual(session_after.auxiliary_used, 1)
            self.assertTrue(
                _seeded_complete_accounting_reconciles(
                    report_accounting=session_after,
                    delivery_accounting=after.to_dict(),
                    prior_continuation=meta,
                    cumulative_used=93,
                    session_sent=1,
                )
            )


if __name__ == "__main__":
    unittest.main()
