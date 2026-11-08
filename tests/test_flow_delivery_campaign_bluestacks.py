"""Focused tests for Campaign AP continuous-session flow delivery."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

import scripts.flow_delivery_campaign_bluestacks as delivery
import scripts.navigation_development_boundary as boundary
import scripts.pnsctl as pnsctl
from automation_service.registry import (
    CAMPAIGN_FLOW_ID,
    CAMPAIGN_HANDLER_ID,
    CAMPAIGN_PHASE_MODE,
    CAMPAIGN_PRODUCT_ID,
    CAMPAIGN_PRODUCT_REVISION,
    CAMPAIGN_PROFILE_ID,
    RegisteredDispatchSnapshot,
)
from scripts.navigation_development_boundary import (
    DevelopmentInitialObservation,
    DevelopmentSession,
)
from tasks.campaign_auto_battle import CampaignScreen


class CampaignFlowDeliveryTests(unittest.TestCase):
    def test_native_transport_ledger_does_not_double_count_semantic_steps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            steps = [{"type": "command", "kind": "tap", "action": "CHALLENGE_STAGE"},
                     {"type": "command", "kind": "tap", "action": "CONFIRM_LINEUP"}]
            native = [{"type": "capture"}, {"type": "dispatch", "execute": True},
                      {"type": "dispatch", "execute": True}]
            (root / "events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in steps))
            self.assertEqual(delivery._campaign_transport_count(root), 2)
            ledger = root / "native-events.jsonl"
            ledger.write_text("".join(json.dumps(row) + "\n" for row in native))
            self.assertEqual(delivery._campaign_transport_count(root), 2)
            self.assertEqual(delivery._campaign_event_rows(root), steps)
            # One additional native reservation stopped before its ledger write.
            (root / "result.json").write_text(json.dumps({
                "input_count": 3, "total_input_count": 3, "native_events_path": str(ledger)}))
            self.assertEqual(delivery._campaign_transport_count(root), 3)
            # A malformed lower count cannot erase an observed dispatch.
            (root / "result.json").write_text(json.dumps({
                "input_count": 1, "total_input_count": 1, "native_events_path": str(ledger)}))
            self.assertEqual(delivery._campaign_transport_count(root), 2)

    def _run_home_prep(self, root, screens, *, legacy_exit_score=None, max_inputs=6,
                       lineup_back_visible=True, unrecognized_indices=()):
        base = ("campaign-base-request", (0, 1170, 132, 1280))
        exit_target = ("campaign-exit-base", (690, 920, 800, 1060))
        lineup_targets = (("campaign-lineup-challenge", (276, 1168, 524, 1252)),)
        if lineup_back_visible:
            lineup_targets += (("campaign-lineup-back", (47, 2, 128, 61)),)
        source_targets = {
            CampaignScreen.HERO_LINEUP: lineup_targets,
            CampaignScreen.STAGE_DIALOG: (("campaign-stage-dialog-close", (675, 228, 764, 289)),),
            CampaignScreen.CHAPTER_MAP: (("campaign-chapter-back", (705, 1028, 767, 1084)),),
        }
        recognitions = [
            SimpleNamespace(
                observation=SimpleNamespace(screen=screen, recognized=index not in unrecognized_indices),
                frame_sha256=str(index),
                targets=(*source_targets.get(screen, ()), base, *((exit_target,) if exit_visible else ())),
                diagnostics={"campaign_exit_score": legacy_exit_score} if legacy_exit_score is not None else {},
            )
            for index, (screen, exit_visible) in enumerate(screens)
        ]
        runtime = SimpleNamespace(
            session=root / "runtime",
            capture=Mock(side_effect=[SimpleNamespace(frame=object()) for _ in screens]),
            tap=Mock(),
        )
        recovery = {"status": "shared_pre_flow_startup_recovery", "input_count": 0}
        with (
            patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", return_value=runtime),
            patch("tasks.campaign_auto_battle_vision.recognize_campaign_frame", side_effect=recognitions),
            patch("time.sleep"),
        ):
            try:
                result = delivery._ensure_home_surface_before_prep(root, startup_recovery=recovery, max_inputs=max_inputs)
            except pnsctl.OperatorError as exc:
                return runtime, None, exc
        return runtime, result, None

    def test_home_prep_unwinds_lineup_once_then_existing_story_surfaces_without_challenge(self):
        for stage_dialog in (False, True):
            with self.subTest(stage_dialog=stage_dialog), tempfile.TemporaryDirectory() as directory:
                screens = [(CampaignScreen.HERO_LINEUP, False)]
                if stage_dialog:
                    screens.append((CampaignScreen.STAGE_DIALOG, False))
                screens.extend(((CampaignScreen.CHAPTER_MAP, False), (CampaignScreen.TIER_MAP, True),
                                (CampaignScreen.HOME_BASE, False)))
                runtime, result, error = self._run_home_prep(Path(directory), screens)
                self.assertIsNone(error)
                self.assertIsNotNone(result)
                expected = ["campaign-lineup-back"]
                if stage_dialog:
                    expected.append("campaign-stage-dialog-close")
                expected.extend(("campaign-chapter-back", "campaign-exit-base"))
                self.assertEqual([call.kwargs["target_identity"] for call in runtime.tap.call_args_list], expected)
                self.assertTrue(all(call.kwargs["consequential"] is False for call in runtime.tap.call_args_list))

    def test_home_prep_lineup_requires_bound_arrow_and_positive_source(self):
        for options in ({"lineup_back_visible": False}, {"unrecognized_indices": (0,)}):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as directory:
                runtime, result, error = self._run_home_prep(
                    Path(directory), [(CampaignScreen.HERO_LINEUP, False)], **options)
                self.assertIsNone(result)
                self.assertIsInstance(error, pnsctl.OperatorError)
                runtime.tap.assert_not_called()

    def test_home_prep_lineup_back_rejects_unexpected_or_unrecognized_parent_without_retry(self):
        cases = [(screen, ()) for screen in (CampaignScreen.HERO_LINEUP, CampaignScreen.UNKNOWN,
                 CampaignScreen.BATTLE, CampaignScreen.TIER_MAP, CampaignScreen.HOME_BASE)]
        cases.append((CampaignScreen.CHAPTER_MAP, (1,)))
        for successor, unrecognized in cases:
            with self.subTest(successor=successor, unrecognized=unrecognized), tempfile.TemporaryDirectory() as directory:
                runtime, result, error = self._run_home_prep(Path(directory),
                    [(CampaignScreen.HERO_LINEUP, False), (successor, True)],
                    unrecognized_indices=unrecognized)
                self.assertIsNone(result)
                self.assertIsInstance(error, pnsctl.OperatorError)
                runtime.tap.assert_called_once()
                self.assertEqual(runtime.tap.call_args.kwargs["target_identity"], "campaign-lineup-back")

    def test_home_prep_never_repeats_base_request_on_unchanged_tier_map(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, result, error = self._run_home_prep(
                Path(directory),
                [(CampaignScreen.TIER_MAP, False), (CampaignScreen.TIER_MAP, False)],
            )
        self.assertIsNone(result)
        self.assertIsInstance(error, pnsctl.OperatorError)
        self.assertIn("after one Base request", str(error))
        self.assertEqual(runtime.capture.call_count, 2)
        runtime.tap.assert_called_once()
        self.assertEqual(runtime.tap.call_args.kwargs["target_identity"], "campaign-base-request")

    def test_home_prep_accepts_base_request_then_fresh_exit_and_home(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, result, error = self._run_home_prep(
                Path(directory),
                [
                    (CampaignScreen.TIER_MAP, False),
                    (CampaignScreen.TIER_MAP, True),
                    (CampaignScreen.HOME_BASE, False),
                ],
            )
        self.assertIsNone(error)
        self.assertEqual(result["input_count"], 0)
        self.assertEqual(runtime.capture.call_count, 3)
        self.assertEqual(
            [call.kwargs["target_identity"] for call in runtime.tap.call_args_list],
            ["campaign-base-request", "campaign-exit-base"],
        )

    def test_home_prep_never_turns_a_legacy_score_into_a_static_exit_target(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, result, error = self._run_home_prep(
                Path(directory),
                [(CampaignScreen.TIER_MAP, False), (CampaignScreen.TIER_MAP, False)],
                legacy_exit_score=0.99,
            )
        self.assertIsNone(result)
        self.assertIsInstance(error, pnsctl.OperatorError)
        runtime.tap.assert_called_once()
        self.assertEqual(runtime.tap.call_args.kwargs["target_identity"], "campaign-base-request")

    def test_home_prep_stops_before_dispatch_beyond_its_remaining_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, result, error = self._run_home_prep(
                Path(directory),
                [(CampaignScreen.TIER_MAP, False), (CampaignScreen.TIER_MAP, True)],
                max_inputs=1,
            )
        self.assertIsNone(result)
        self.assertIsInstance(error, pnsctl.OperatorError)
        runtime.tap.assert_called_once()
        self.assertEqual(runtime.tap.call_args.kwargs["target_identity"], "campaign-base-request")
        with tempfile.TemporaryDirectory() as directory:
            runtime, result, error = self._run_home_prep(
                Path(directory), [(CampaignScreen.TIER_MAP, True)], max_inputs=0,
            )
        self.assertIsNone(result)
        self.assertIsInstance(error, pnsctl.OperatorError)
        runtime.tap.assert_not_called()

    def test_direct_campaign_session_uses_the_route_default_budget(self):
        class SessionInspected(Exception):
            pass

        for invoke in (
            lambda: pnsctl.development_session_run_flow(delivery.AUTO_BATTLE_FLOW_ID, live=False, yes=False),
            lambda: pnsctl.main(["development-session", "run-flow", delivery.AUTO_BATTLE_FLOW_ID]),
        ):
            with patch.object(boundary, "DevelopmentSession", side_effect=SessionInspected) as session:
                with self.assertRaises(SessionInspected):
                    invoke()
            self.assertEqual(session.call_args.kwargs["max_inputs"], 16)

    def _registration(self) -> RegisteredDispatchSnapshot:
        return RegisteredDispatchSnapshot(
            CAMPAIGN_FLOW_ID,
            CAMPAIGN_PRODUCT_ID,
            CAMPAIGN_PRODUCT_REVISION,
            CAMPAIGN_HANDLER_ID,
            CAMPAIGN_PROFILE_ID,
            CAMPAIGN_PHASE_MODE,
            "REGISTERED",
            True,
        )

    def _session(self, root: Path, *, invocation_id="campaign-continuous"):
        digest = hashlib.sha256(b"campaign-initial").hexdigest()
        with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
            session = DevelopmentSession(
                owner=f"pnsctl-development-session:{delivery.AUTO_BATTLE_FLOW_ID}",
                invocation_id=invocation_id,
                session_directory=root / "outer",
                max_inputs=delivery.MAX_INPUTS,
            )
            session.__enter__()
        (session.session_directory / "source.png").write_bytes(b"campaign-initial")
        initial = DevelopmentInitialObservation(
            {"frame_sha256": digest},
            digest,
            frame_path="source.png",
            invocation_id=session.invocation_id,
        )
        session.set_initial_observation(initial)
        return session, initial

    def _child_result(self, child: Path, *, ap_after: int = 106) -> None:
        child.mkdir(parents=True, exist_ok=True)
        (child / "frames").mkdir()
        events = [
            {"type": "command", "kind": "tap", "action": "OPEN_CAMPAIGN"},
            {"type": "command", "kind": "swipe", "action": "NAVIGATE_CHAPTER"},
            {"type": "command", "kind": "tap", "action": "ENABLE_AUTO"},
        ]
        (child / "events.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in events),
            encoding="utf-8",
        )
        result = {
            "status": "completed",
            "terminal": "completed",
            "navigation_only": False,
            "battle_outcome": "victory",
            "destination": "1-15-9",
            "ap_before": 120,
            "ap_after": ap_after,
            "ap_cost": 14,
            "progress": {
                "initial_ap": 120,
                "current_ap": ap_after,
                "completed_runs": 1,
                "ap_spent": 14,
                "ap_regenerated": 0,
                "loss_seen": False,
            },
        }
        (child / "result.json").write_text(
            json.dumps(result, sort_keys=True) + "\n", encoding="utf-8"
        )

    def test_registry_and_dry_run_keep_campaign_disabled(self):
        contract = pnsctl._load_bluestacks_flow_registry()[delivery.AUTO_BATTLE_FLOW_ID]
        self.assertEqual(contract["runner"], delivery.AUTO_BATTLE_RUNNER_ID)
        self.assertEqual(contract["consequence_class"], "consequential")
        result = json.loads(delivery.run_campaign_auto_battle_live({}, {}, live=False))
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["input_count"], 0)
        self.assertEqual(result["max_inputs"], delivery.MAX_INPUTS)
        self.assertEqual(result["proof_topology"], "continuous")
        self.assertEqual(result["production_registration"], "NOT_REGISTERED")
        self.assertFalse(result["scheduler_enabled"])

    def test_live_route_rejects_sessionless_dispatch(self):
        with self.assertRaisesRegex(
            pnsctl.OperatorError, "active pnsctl-owned DevelopmentSession"
        ):
            delivery.run_campaign_auto_battle_live({}, {"recovery_only": True}, live=True)

    def test_campaign_honors_bounded_shared_and_route_ceilings(self):
        self.assertEqual(delivery._campaign_maximum({"max_inputs": delivery.MAX_INPUTS}), delivery.MAX_INPUTS)
        self.assertEqual(delivery._campaign_maximum({"max_inputs": 16}), 16)
        self.assertEqual(delivery._campaign_maximum({"max_inputs": 12}), 12)
        self.assertEqual(delivery._campaign_maximum({"max_inputs": 16, "route_max_inputs": 9}), 9)
        for maximum in (0, delivery.MAX_INPUTS + 1):
            with self.subTest(maximum=maximum), self.assertRaises(pnsctl.OperatorError):
                delivery._campaign_maximum({"max_inputs": maximum})
        with self.assertRaises(pnsctl.OperatorError):
            delivery._campaign_maximum({"max_inputs": 16, "route_max_inputs": 17})

    def test_historical_continuous_receipt_still_validates_without_a_live_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, initial = self._session(root)
            child = root / "outer" / "runtime" / "1-15-9-run"
            self._child_result(child)
            prep = root / "outer" / "runtime" / "campaign-exit-to-home"
            prep.mkdir()
            (prep / "events.jsonl").write_text(
                json.dumps(
                    {"type": "command", "kind": "tap", "action": "RETURN_HOME"}
                )
                + "\n",
                encoding="utf-8",
            )
            lease = {
                "owner": session.owner,
                "development_session": session,
                "initial_observation": initial,
                "initial_frame_sha256": initial.frame_sha256,
                "max_inputs": delivery.MAX_INPUTS,
                "registration_snapshot": self._registration(),
            }
            try:
                result = delivery._campaign_result_payload(
                    {"status": "completed", "terminal": "completed", "navigation_only": False,
                     "terminal_runtime_state": "recognized_home",
                     "campaign_result": json.loads((child / "result.json").read_text())},
                    session_directory=child, input_count=4, maximum=delivery.MAX_INPUTS,
                    destination="1-15-9", ap_cost=14,
                    registration_snapshot=self._registration().to_mapping(),
                )
                retained_initial = delivery._campaign_initial_observation(lease, session)
                (child / "frames" / "0000-initial-observation.png").write_bytes(b"campaign-initial")
                retained_initial["frame_path"] = "frames/0000-initial-observation.png"
                result.update(initial_observation=retained_initial,
                    initial_frame_sha256=initial.frame_sha256, campaign_transport_count=4,
                    recovery_input_count=0, route_input_count=4, total_input_count=4)
                trace = delivery._campaign_causal_trace(child, result=result,
                    initial_observation=retained_initial,
                    registration_snapshot=self._registration().to_mapping())
                result.update(causal_trace=trace, causal_trace_count=1)
                self.assertIs(initial, session.initial_observation)
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["input_count"], 4)
                self.assertEqual(result["campaign_transport_count"], 4)
                self.assertEqual(result["campaign_action_count"], 1)
                self.assertTrue(result["exact_ap_delta"])
                self.assertTrue(result["result_successor_verified"])
                self.assertTrue(result["terminal_home_verified"])
                self.assertTrue(result["refill_forbidden_verified"])
                self.assertEqual(result["production_registration"], "NOT_REGISTERED")
                self.assertFalse(result["scheduler_enabled"])
                self.assertEqual(
                    result["registration_snapshot"],
                    self._registration().to_mapping(),
                )
                self.assertEqual(
                    result["causal_trace"]["registration_snapshot"],
                    result["registration_snapshot"],
                )
                self.assertEqual(result["causal_trace_count"], 1)
                self.assertTrue(result["causal_trace"]["read_only"])
                self.assertFalse(result["causal_trace"]["input_authority"])
                verdict = delivery.verify_campaign_auto_battle_live(
                    {"result": result, "session_directory": str(child)}, {}, {}
                )
                self.assertEqual(verdict["status"], "verified")
                forged = dict(result)
                forged["registration_snapshot"] = dict(result["registration_snapshot"])
                forged["registration_snapshot"]["flow_id"] = (
                    "RECRUITMENT-FREE-ATTEMPT-MAINTENANCE"
                )
                forged_verdict = delivery.verify_campaign_auto_battle_live(
                    {"result": forged, "session_directory": str(child)}, {}, {}
                )
                self.assertEqual(forged_verdict["status"], "evidence_required")
                self.assertFalse(forged_verdict["registration_verified"])
            finally:
                session.__exit__(None, None, None)

    def test_dispatch_without_exact_ap_successor_requires_reconciliation(self):
        result = delivery._campaign_result_payload(
            {
                "status": "completed",
                "reason": "Campaign Home prep source was not recognized",
                "terminal": "completed",
                "navigation_only": False,
                "terminal_runtime_state": "recognized_home",
                "campaign_result": {
                    "ap_before": 120,
                    "ap_after": 107,
                    "battle_outcome": "victory",
                    "progress": {"completed_runs": 1},
                },
            },
            session_directory=Path("runtime"),
            input_count=3,
            maximum=delivery.MAX_INPUTS,
            destination="1-15-9",
            ap_cost=14,
            registration_snapshot=self._registration().to_mapping(),
        )
        self.assertEqual(result["status"], "effect_reconciliation_required")
        self.assertTrue(result["effect_reconciliation_required"])
        self.assertTrue(result["identical_retry_denied"])
        self.assertEqual(
            result["reason"],
            "Campaign Home prep source was not recognized",
        )

    def test_refill_marker_and_forged_registration_cannot_verify(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "events.jsonl").write_text(
                json.dumps(
                    {"type": "command", "kind": "tap", "action": "AP_REFILL"}
                )
                + "\n",
                encoding="utf-8",
            )
            result = delivery._campaign_result_payload(
                {
                    "status": "completed",
                    "terminal": "completed",
                    "navigation_only": False,
                    "terminal_runtime_state": "recognized_home",
                    "campaign_result": {
                        "destination": "1-15-9",
                        "ap_cost": 14,
                        "ap_before": 120,
                        "ap_after": 106,
                        "battle_outcome": "victory",
                        "progress": {"completed_runs": 1, "ap_spent": 14},
                    },
                },
                session_directory=root,
                input_count=1,
                maximum=delivery.MAX_INPUTS,
                destination="1-15-9",
                ap_cost=14,
                registration_snapshot=self._registration().to_mapping(),
            )
            self.assertFalse(result["refill_forbidden_verified"])
            self.assertEqual(result["status"], "effect_reconciliation_required")

    def test_ordinary_legacy_ap_refuses_before_proof_session_preparation_or_process(self):
        for entrypoint in (delivery.run_campaign_auto_battle_live, delivery._run_campaign_victory_home_recovery):
            for recovery in (None, False, 1, "true"):
                with (
                    self.subTest(entrypoint=entrypoint.__name__, recovery=recovery),
                    patch("tasks.campaign_victory_recovery.load_victory_recovery_proof") as proof,
                    patch.object(delivery, "_campaign_outer_session") as session,
                    patch.object(delivery, "_ensure_home_surface_before_prep") as prep,
                    patch.object(delivery.subprocess, "run") as process,
                ):
                    lease = {"max_inputs": delivery.MAX_INPUTS, "recovery_only": recovery,
                             "development_session": object()}
                    with self.assertRaisesRegex(pnsctl.OperatorError, "automation-service serve"):
                        entrypoint({}, lease)
                    for operation in (proof, session, prep, process):
                        operation.assert_not_called()

    def test_victory_recovery_skips_entry_and_preserves_one_original_battle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, initial = self._session(
                root, invocation_id=f"{delivery.AUTO_BATTLE_FLOW_ID}-20261029T060000000000Z"
            )
            child = root / "outer" / "runtime" / "1-15-9-recovery"
            self._child_result(child, ap_after=107)
            campaign = json.loads((child / "result.json").read_text())
            campaign.update(victory_home_only=True, new_battle_count=0)
            campaign["progress"]["ap_regenerated"] = 1
            (child / "result.json").write_text(json.dumps(campaign), encoding="utf-8")
            rows = [
                {"type": "command", "kind": "tap", "action": action, "target_identity": target}
                for action, target in (
                    ("CONTINUE_VICTORY", "campaign-victory-continue"),
                    ("LEAVE_CHAPTER_MAP", "campaign-chapter-back"),
                    ("RETURN_HOME", "campaign-exit-base"),
                )
            ]
            (child / "events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            proof = {
                "source_session": str(root / "prior"), "baseline_ap": 120,
                "destination": "1-15-9", "ap_cost": 14, "new_battle_count": 0,
                "registration_snapshot": self._registration().to_mapping(),
            }
            lease = {
                "owner": session.owner, "development_session": session,
                "initial_observation": initial, "initial_frame_sha256": initial.frame_sha256,
                "max_inputs": delivery.MAX_INPUTS, "recovery_only": True,
                "recovery_session": str(root / "prior"),
            }
            try:
                with (
                    patch("tasks.campaign_victory_recovery.load_victory_recovery_proof", return_value=proof),
                    patch.object(delivery, "_ensure_home_surface_before_prep", side_effect=AssertionError("no entry during recovery")),
                    patch.object(delivery.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")) as run,
                ):
                    result = json.loads(delivery.run_campaign_auto_battle_live({}, lease))
                    verdict = delivery.verify_campaign_auto_battle_live({"result": result, "session_directory": str(child)}, {}, {})
                    for outcome, loss in (("defeat", False), ("victory", True)):
                        forged = json.loads(json.dumps(result))
                        forged["campaign_result"]["battle_outcome"] = outcome
                        forged["campaign_result"]["progress"]["loss_seen"] = loss
                        rejected = delivery._campaign_result_payload(
                            forged, session_directory=child, input_count=3, maximum=16,
                            destination="1-15-9", ap_cost=14, registration_snapshot=proof["registration_snapshot"],
                        )
                        self.assertEqual(rejected["status"], "effect_reconciliation_required")
                        self.assertEqual(delivery.verify_campaign_auto_battle_live({"result": forged, "session_directory": str(child)}, {}, {})["status"], "evidence_required")
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["proof_topology"], "composite")
                self.assertEqual(result["new_battle_count"], 0)
                self.assertEqual(result["campaign_action_count"], 1)
                self.assertEqual(result["ap_regenerated"], 1)
                self.assertFalse(result["exact_ap_delta"])
                self.assertTrue(result["ap_cost_reconciled"])
                self.assertEqual(verdict["status"], "verified")
                command = run.call_args.args[0]
                self.assertIn("--victory-home-only", command)
                self.assertEqual(command[command.index("--initial-ap") + 1], "120")
                rows[0]["target_identity"] = "campaign-lineup-challenge"
                (child / "events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
                rejected = delivery._campaign_result_payload(
                    result, session_directory=child, input_count=3, maximum=16,
                    destination="1-15-9", ap_cost=14, registration_snapshot=proof["registration_snapshot"],
                )
                self.assertFalse(rejected["safe_action_policy"])
                self.assertEqual(rejected["status"], "effect_reconciliation_required")
                rows[0]["target_identity"] = "campaign-victory-continue"
                rows.append({"type": "command", "kind": "shell", "action": "UNKNOWN"})
                self.assertFalse(delivery._campaign_victory_recovery_inputs(rows))
            finally:
                session.__exit__(None, None, None)

    def test_invalid_recovery_proof_stops_before_runtime_ownership(self):
        with (
            patch("tasks.campaign_victory_recovery.load_victory_recovery_proof", side_effect=ValueError("bad proof")),
            patch.object(boundary, "DevelopmentSession", side_effect=AssertionError("must not acquire runtime")),
        ):
            with self.assertRaises(pnsctl.OperatorError):
                pnsctl.development_session_run_flow(
                    delivery.AUTO_BATTLE_FLOW_ID, live=True, yes=True,
                    recovery_only=True, recovery_session=Path("untrusted"),
                )

    def test_retained_campaign_verification_grants_no_runtime_authority(self):
        retained = {"flow_id": delivery.AUTO_BATTLE_FLOW_ID}
        validator = Mock(return_value={"status": "verified"})
        with (
            patch.object(pnsctl, "_retained_flow_result", return_value=(Path("retained"), retained)),
            patch.object(pnsctl, "_verify_flow_structure", return_value={"result": retained}),
            patch.dict(pnsctl._BLUESTACKS_EVIDENCE_VALIDATORS, {
                "campaign_auto_battle_live_evidence": validator,
            }),
        ):
            result = json.loads(pnsctl.bluestacks_verify_flow(Path("retained")))
        self.assertEqual(result["status"], "verified")
        _structure, flow_context, evidence_context = validator.call_args.args
        for context in (flow_context, evidence_context):
            self.assertEqual(context["flow_id"], delivery.AUTO_BATTLE_FLOW_ID)
            self.assertIs(context["input_authority"], False)
            self.assertNotIn("runtime_ownership_state", context)
            self.assertNotIn("unresolved_action_state", context)

    def test_retained_queue_dependent_validator_fails_closed_without_legacy_queue(self):
        from scripts.flow_delivery_campaign_atlas_bluestacks import FLOW_ID as ATLAS_FLOW_ID

        retained = {"flow_id": ATLAS_FLOW_ID}
        with (
            patch.object(pnsctl, "_retained_flow_result", return_value=(Path("retained"), retained)),
            patch.object(
                pnsctl,
                "_verify_flow_structure",
                side_effect=AssertionError("unsupported evidence must not be read"),
            ),
            self.assertRaisesRegex(pnsctl.OperatorError, "no offline evidence adapter"),
        ):
            pnsctl.bluestacks_verify_flow(Path("retained"))


if __name__ == "__main__":
    unittest.main()
