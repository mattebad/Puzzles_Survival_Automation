"""Offline tests for Ultimate Challenge daily contracts."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tasks.campaign_auto_battle import (
    REJECTED_CAMPAIGN_AP_DESTINATIONS,
    parse_supported_campaign_story_destination,
)
from tasks.ultimate_challenge_daily import (
    ACTION_RETURN_CANONICAL_HOME,
    ACTION_TAP_CHALLENGE,
    ACTION_TAP_FLEE,
    ACTION_TAP_LINEUP_CHALLENGE,
    ACTION_TAP_UPPER_RIGHT_EXIT,
    ACTIVE_CHALLENGE_STATE,
    COMPLETION_COMPLETED,
    COMPLETION_NOT_COMPLETED,
    COMPLETION_UNKNOWN,
    FLEE_CONFIRMED_STATE,
    FLEE_WARNING_STATE,
    FLOW_ID,
    HERO_LINEUP_STATE,
    HOME_RETURNED_STATE,
    REPLAY_EVIDENCE_REQUIRED,
    TERMINAL_ALREADY_COMPLETED,
    TERMINAL_BLOCKED,
    TERMINAL_COMPLETE_FOR_RESET,
    TERMINAL_NAVIGATION_ONLY_COMPLETE,
    ULTIMATE_CHALLENGE_STATE,
    ULTIMATE_CHALLENGE_ENTRY_IDENTITY,
    ULTIMATE_CHALLENGE_OBJECTIVE,
    UltimateChallengeExecutionObservation,
    UltimateChallengeEntryObservation,
    UltimateChallengeResetWindowState,
    evaluate_execution_step,
    empty_reset_window_state,
    evaluate_already_completed,
    evaluate_navigation_only,
    load_reset_window_state,
    record_verified_success,
    ultimate_challenge_zero_transport_replay_gate,
    recognize_ultimate_challenge_entry_from_texts,
    save_reset_window_state,
    ultimate_challenge_already_completed_from_ocr_hits,
    ultimate_challenge_entry_roi_from_ocr_hits,
)


FRAME = "a" * 64
TARGET_ROI = (200, 400, 600, 520)
RESET_IDENTITY = "game-day-2026-07-20"


def _execution_decision(
    observation: UltimateChallengeExecutionObservation,
    *,
    prior_state: str | None = None,
):
    return evaluate_execution_step(
        observation,
        current_reset_identity=RESET_IDENTITY,
        prior_state=prior_state,
    )


def _bound_entry(**overrides) -> UltimateChallengeEntryObservation:
    base = dict(
        campaign_screen_recognized=True,
        entry_control_visible=True,
        entry_control_identity=ULTIMATE_CHALLENGE_ENTRY_IDENTITY,
        entry_roi=(200, 400, 600, 520),
        already_completed_marker=False,
        reset_identity="game-day-2026-07-20",
        source_frame_sha256=FRAME,
    )
    base.update(overrides)
    return UltimateChallengeEntryObservation(**base)


class UltimateChallengeDailyContractTests(unittest.TestCase):
    def test_already_completed_for_matching_reset_window(self) -> None:
        state = UltimateChallengeResetWindowState(
            reset_identity="game-day-2026-07-20",
            last_success_reset_identity="game-day-2026-07-20",
            last_success_at="2026-07-20T12:00:00Z",
            completion_state=COMPLETION_COMPLETED,
        )
        decision = evaluate_already_completed(
            state, current_reset_identity="game-day-2026-07-20"
        )
        self.assertEqual(decision.terminal, TERMINAL_ALREADY_COMPLETED)
        self.assertFalse(decision.dispatch_authorized)

    def test_ambiguous_reset_identity_fails_closed(self) -> None:
        state = UltimateChallengeResetWindowState(
            reset_identity=None,
            last_success_reset_identity="game-day-2026-07-20",
            last_success_at="2026-07-20T12:00:00Z",
            completion_state=COMPLETION_COMPLETED,
        )
        decision = evaluate_already_completed(state, current_reset_identity=None)
        self.assertEqual(decision.terminal, TERMINAL_BLOCKED)
        self.assertIn("ambiguous reset identity", decision.reason)

    def test_stale_completion_outside_current_window_fails_closed(self) -> None:
        state = UltimateChallengeResetWindowState(
            reset_identity="game-day-2026-07-19",
            last_success_reset_identity="game-day-2026-07-19",
            last_success_at="2026-07-19T12:00:00Z",
            completion_state=COMPLETION_COMPLETED,
        )
        decision = evaluate_already_completed(
            state, current_reset_identity="game-day-2026-07-20"
        )
        self.assertEqual(decision.terminal, TERMINAL_BLOCKED)
        self.assertIn("outside current reset window", decision.reason)

    def test_unknown_completion_with_last_success_fails_closed(self) -> None:
        state = UltimateChallengeResetWindowState(
            reset_identity="game-day-2026-07-20",
            last_success_reset_identity="game-day-2026-07-20",
            last_success_at="2026-07-20T12:00:00Z",
            completion_state=COMPLETION_UNKNOWN,
        )
        decision = evaluate_already_completed(
            state, current_reset_identity="game-day-2026-07-20"
        )
        self.assertEqual(decision.terminal, TERMINAL_BLOCKED)
        self.assertIn("ambiguous completion_state", decision.reason)

    def test_navigation_only_complete_when_entry_bound(self) -> None:
        state = empty_reset_window_state()
        decision = evaluate_navigation_only(state, _bound_entry())
        self.assertEqual(decision.terminal, TERMINAL_NAVIGATION_ONLY_COMPLETE)
        self.assertFalse(decision.dispatch_authorized)
        self.assertEqual(decision.entry_roi, (200, 400, 600, 520))

    def test_navigation_only_rejects_unbound_entry(self) -> None:
        state = empty_reset_window_state()
        decision = evaluate_navigation_only(
            state,
            _bound_entry(
                entry_control_visible=False,
                entry_control_identity="",
                entry_roi=None,
            ),
        )
        self.assertEqual(decision.terminal, TERMINAL_BLOCKED)

    def test_one_success_per_reset_persistence_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "uc-reset.json"
            state = empty_reset_window_state()
            self.assertEqual(state.completion_state, COMPLETION_NOT_COMPLETED)
            updated = record_verified_success(
                state,
                reset_identity="game-day-2026-07-20",
                terminal_state=HOME_RETURNED_STATE,
            )
            save_reset_window_state(path, updated)
            loaded = load_reset_window_state(path)
            self.assertEqual(loaded.completion_state, COMPLETION_COMPLETED)
            self.assertEqual(loaded.last_success_reset_identity, "game-day-2026-07-20")
            self.assertEqual(loaded.flow_id, FLOW_ID)
            with self.assertRaisesRegex(ValueError, "same reset window"):
                record_verified_success(
                    loaded,
                    reset_identity="game-day-2026-07-20",
                    terminal_state=HOME_RETURNED_STATE,
                )

    def test_record_success_requires_positive_reset_identity(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive reset identity"):
            record_verified_success(
                empty_reset_window_state(),
                reset_identity="",
                terminal_state=HOME_RETURNED_STATE,
            )

    def test_ocr_text_hits_bind_entry_without_campaign_destination(self) -> None:
        observation = recognize_ultimate_challenge_entry_from_texts(
            campaign_screen_recognized=True,
            ocr_hits={"Ultimate Challenge": (180, 420, 620, 500)},
            source_frame_sha256=FRAME,
            reset_identity="game-day-2026-07-20",
        )
        self.assertTrue(observation.entry_control_visible)
        self.assertEqual(observation.entry_control_identity, ULTIMATE_CHALLENGE_ENTRY_IDENTITY)
        decision = evaluate_navigation_only(empty_reset_window_state(), observation)
        self.assertEqual(decision.terminal, TERMINAL_NAVIGATION_ONLY_COMPLETE)

    def test_lone_ultimate_or_ultim_does_not_bind_entry(self) -> None:
        for lone in ("Ultimate", "ultim", "ULTIMATE"):
            observation = recognize_ultimate_challenge_entry_from_texts(
                campaign_screen_recognized=True,
                ocr_hits={lone: (180, 420, 320, 460)},
                source_frame_sha256=FRAME,
            )
            self.assertFalse(
                observation.entry_control_visible,
                msg=f"lone {lone!r} must not satisfy UC entry identity",
            )
            self.assertEqual(observation.entry_control_identity, "")

    def test_split_ultimate_and_challenge_hits_bind_entry(self) -> None:
        observation = recognize_ultimate_challenge_entry_from_texts(
            campaign_screen_recognized=True,
            ocr_hits={
                "Ultimate": (180, 420, 320, 460),
                "Challenge": (330, 420, 520, 460),
            },
            source_frame_sha256=FRAME,
        )
        self.assertTrue(observation.entry_control_visible)
        self.assertEqual(observation.entry_control_identity, ULTIMATE_CHALLENGE_ENTRY_IDENTITY)

    def test_not_routed_through_campaign_story_destination_parser(self) -> None:
        self.assertIn("ultimate-challenge", REJECTED_CAMPAIGN_AP_DESTINATIONS)
        with self.assertRaises(ValueError):
            parse_supported_campaign_story_destination("ultimate-challenge")

    def test_campaign_ap_completion_does_not_complete_uc(self) -> None:
        # A Campaign-looking identity must not satisfy UC already_completed.
        state = empty_reset_window_state()
        decision = evaluate_already_completed(
            state, current_reset_identity="campaign-ap-1-20-9-complete"
        )
        self.assertNotEqual(decision.terminal, TERMINAL_ALREADY_COMPLETED)

    def test_campaign_completion_reset_artifacts_cannot_satisfy_uc_contracts(self) -> None:
        """Campaign completion/reset JSON must not load or terminal as UC already_completed."""

        campaign_artifact = {
            "reset_identity": "game-day-2026-07-20",
            "last_success_reset_identity": "game-day-2026-07-20",
            "last_success_at": "2026-07-20T12:00:00Z",
            "completion_state": COMPLETION_COMPLETED,
            "schema_version": 1,
            "flow_id": "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION",
            "objective": "campaign_ap_farming",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign-reset.json"
            path.write_text(json.dumps(campaign_artifact) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "UC flow id"):
                load_reset_window_state(path)

        with self.assertRaisesRegex(ValueError, "UC flow id"):
            UltimateChallengeResetWindowState(
                reset_identity="game-day-2026-07-20",
                last_success_reset_identity="game-day-2026-07-20",
                last_success_at="2026-07-20T12:00:00Z",
                completion_state=COMPLETION_COMPLETED,
                flow_id="CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION",
                objective="campaign_ap_farming",
            )

        # Campaign-looking OCR completion text without UC entry must not terminal.
        unbound = recognize_ultimate_challenge_entry_from_texts(
            campaign_screen_recognized=True,
            ocr_hits={
                "Claimed": (100, 200, 200, 240),
                "Already Completed": (100, 250, 400, 290),
                "Stage 1-20-9": (100, 300, 280, 340),
            },
            source_frame_sha256=FRAME,
            reset_identity="game-day-2026-07-20",
        )
        self.assertFalse(unbound.entry_control_visible)
        self.assertFalse(unbound.already_completed_marker)
        decision = evaluate_already_completed(
            empty_reset_window_state(),
            current_reset_identity="game-day-2026-07-20",
            observation=unbound,
        )
        self.assertNotEqual(decision.terminal, TERMINAL_ALREADY_COMPLETED)

    def test_generic_claimed_ocr_requires_bound_uc_entry_for_already_completed(self) -> None:
        self.assertFalse(
            ultimate_challenge_already_completed_from_ocr_hits(
                ["Claimed", "Already Completed"],
                entry_control_visible=False,
            )
        )
        self.assertTrue(
            ultimate_challenge_already_completed_from_ocr_hits(
                ["Claimed"],
                entry_control_visible=True,
            )
        )
        # Strong UC-scoped phrase may qualify even before a separate bind flag.
        self.assertTrue(
            ultimate_challenge_already_completed_from_ocr_hits(
                ["Ultimate Challenge", "Already Completed"],
                entry_control_visible=False,
            )
        )

        unbound_marker = _bound_entry(
            entry_control_visible=False,
            entry_control_identity="",
            entry_roi=None,
            already_completed_marker=True,
        )
        decision = evaluate_already_completed(
            empty_reset_window_state(),
            current_reset_identity="game-day-2026-07-20",
            observation=unbound_marker,
        )
        self.assertEqual(decision.terminal, TERMINAL_BLOCKED)
        self.assertIn("bound Ultimate Challenge entry identity", decision.reason)

        bound_marker = _bound_entry(already_completed_marker=True)
        decision = evaluate_already_completed(
            empty_reset_window_state(),
            current_reset_identity="game-day-2026-07-20",
            observation=bound_marker,
        )
        self.assertEqual(decision.terminal, TERMINAL_ALREADY_COMPLETED)

    def test_unclaimed_ocr_does_not_set_already_completed_marker(self) -> None:
        """Substring "claimed" inside "Unclaimed" must not terminal as claimed."""

        self.assertFalse(
            ultimate_challenge_already_completed_from_ocr_hits(
                ["Unclaimed"],
                entry_control_visible=True,
            )
        )
        self.assertFalse(
            ultimate_challenge_already_completed_from_ocr_hits(
                ["Ultimate Challenge", "Unclaimed"],
                entry_control_visible=True,
            )
        )
        observation = recognize_ultimate_challenge_entry_from_texts(
            campaign_screen_recognized=True,
            ocr_hits={
                "Ultimate Challenge": (180, 420, 620, 500),
                "Unclaimed": (180, 520, 320, 560),
            },
            source_frame_sha256=FRAME,
            reset_identity="game-day-2026-07-20",
        )
        self.assertTrue(observation.entry_control_visible)
        self.assertFalse(observation.already_completed_marker)

    def test_incomplete_ocr_does_not_set_already_completed_marker(self) -> None:
        """Substring "complet" inside "Incomplete" must not terminal as already_completed."""

        self.assertFalse(
            ultimate_challenge_already_completed_from_ocr_hits(
                ["Already Incomplete"],
                entry_control_visible=True,
            )
        )
        self.assertFalse(
            ultimate_challenge_already_completed_from_ocr_hits(
                ["Already", "Incomplete"],
                entry_control_visible=True,
            )
        )
        self.assertFalse(
            ultimate_challenge_already_completed_from_ocr_hits(
                ["Ultimate Challenge", "Already Incomplete"],
                entry_control_visible=True,
            )
        )
        # Positive controls: word-boundary already+completed still works.
        self.assertTrue(
            ultimate_challenge_already_completed_from_ocr_hits(
                ["Already Completed"],
                entry_control_visible=True,
            )
        )
        self.assertTrue(
            ultimate_challenge_already_completed_from_ocr_hits(
                ["Already", "Complete"],
                entry_control_visible=True,
            )
        )
        observation = recognize_ultimate_challenge_entry_from_texts(
            campaign_screen_recognized=True,
            ocr_hits={
                "Ultimate Challenge": (180, 420, 620, 500),
                "Already Incomplete": (180, 520, 420, 560),
            },
            source_frame_sha256=FRAME,
            reset_identity="game-day-2026-07-20",
        )
        self.assertTrue(observation.entry_control_visible)
        self.assertFalse(observation.already_completed_marker)

    def test_claimed_plus_incomplete_rejects_already_completed_on_all_paths(self) -> None:
        """Incomplete must veto claimed on bound-entry and UC-scoped paths alike."""

        # Bound-entry claimed path: Claimed alone still terminals; +Incomplete must not.
        self.assertTrue(
            ultimate_challenge_already_completed_from_ocr_hits(
                ["Claimed"],
                entry_control_visible=True,
            )
        )
        self.assertFalse(
            ultimate_challenge_already_completed_from_ocr_hits(
                ["Claimed", "Incomplete"],
                entry_control_visible=True,
            )
        )
        # UC-scoped claimed path previously false-terminaled on Claimed despite Incomplete.
        self.assertFalse(
            ultimate_challenge_already_completed_from_ocr_hits(
                ["Ultimate Challenge", "Claimed", "Incomplete"],
                entry_control_visible=False,
            )
        )
        self.assertFalse(
            ultimate_challenge_already_completed_from_ocr_hits(
                ["Ultimate Challenge", "Claimed", "Incomplete"],
                entry_control_visible=True,
            )
        )
        observation = recognize_ultimate_challenge_entry_from_texts(
            campaign_screen_recognized=True,
            ocr_hits={
                "Ultimate Challenge": (180, 420, 620, 500),
                "Claimed": (180, 520, 300, 560),
                "Incomplete": (320, 520, 460, 560),
            },
            source_frame_sha256=FRAME,
            reset_identity="game-day-2026-07-20",
        )
        self.assertTrue(observation.entry_control_visible)
        self.assertFalse(observation.already_completed_marker)

    def test_load_reset_window_state_requires_explicit_flow_id_and_objective(self) -> None:
        """Missing flow_id/objective must fail closed, not default to UC completed."""

        base = {
            "reset_identity": "game-day-2026-07-20",
            "last_success_reset_identity": "game-day-2026-07-20",
            "last_success_at": "2026-07-20T12:00:00Z",
            "completion_state": COMPLETION_COMPLETED,
            "schema_version": 1,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "uc-reset-missing-identity.json"
            path.write_text(json.dumps(base) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "explicit flow_id"):
                load_reset_window_state(path)

            missing_objective = dict(base, flow_id=FLOW_ID)
            path.write_text(json.dumps(missing_objective) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "explicit objective"):
                load_reset_window_state(path)

            missing_flow = dict(base, objective=ULTIMATE_CHALLENGE_OBJECTIVE)
            path.write_text(json.dumps(missing_flow) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "explicit flow_id"):
                load_reset_window_state(path)

            complete = dict(
                base,
                flow_id=FLOW_ID,
                objective=ULTIMATE_CHALLENGE_OBJECTIVE,
            )
            path.write_text(json.dumps(complete) + "\n", encoding="utf-8")
            loaded = load_reset_window_state(path)
            self.assertEqual(loaded.flow_id, FLOW_ID)
            self.assertEqual(loaded.objective, ULTIMATE_CHALLENGE_OBJECTIVE)
            self.assertEqual(loaded.completion_state, COMPLETION_COMPLETED)

    def test_ultimately_plus_challenge_does_not_bind_entry(self) -> None:
        """"ultimate" substring inside "Ultimately" must not bind UC entry."""

        self.assertIsNone(
            ultimate_challenge_entry_roi_from_ocr_hits(
                {
                    "Ultimately": (180, 420, 320, 460),
                    "Challenge": (330, 420, 520, 460),
                }
            )
        )
        self.assertIsNone(
            ultimate_challenge_entry_roi_from_ocr_hits(
                {"Ultimately Challenge": (180, 420, 620, 500)}
            )
        )
        for hits in (
            {"Ultimately": (180, 420, 320, 460), "Challenge": (330, 420, 520, 460)},
            {"Ultimately Challenge": (180, 420, 620, 500)},
        ):
            observation = recognize_ultimate_challenge_entry_from_texts(
                campaign_screen_recognized=True,
                ocr_hits=hits,
                source_frame_sha256=FRAME,
            )
            self.assertFalse(observation.entry_control_visible)
            self.assertEqual(observation.entry_control_identity, "")

    # Policy/gate tests below intentionally use semantic observations only;
    # they do not claim visual, live, or production-controller evidence.
    def test_policy_exact_order_and_zero_resource_route(self) -> None:
        states = [
            ULTIMATE_CHALLENGE_STATE,
            HERO_LINEUP_STATE,
            ACTIVE_CHALLENGE_STATE,
            FLEE_WARNING_STATE,
            FLEE_CONFIRMED_STATE,
        ]
        actions = [
            ACTION_TAP_CHALLENGE,
            ACTION_TAP_LINEUP_CHALLENGE,
            ACTION_TAP_UPPER_RIGHT_EXIT,
            ACTION_TAP_FLEE,
            ACTION_RETURN_CANONICAL_HOME,
        ]
        expected_successors = [
            HERO_LINEUP_STATE,
            ACTIVE_CHALLENGE_STATE,
            FLEE_WARNING_STATE,
            FLEE_CONFIRMED_STATE,
            HOME_RETURNED_STATE,
        ]
        prior_state = None
        for state, action, successor in zip(states, actions, expected_successors):
            decision = _execution_decision(
                UltimateChallengeExecutionObservation(
                    state=state,
                    target_bound=True,
                    native_selector_evidence=True,
                    reset_identity="game-day-2026-07-20",
                    source_frame_sha256=FRAME,
                    target_roi=TARGET_ROI,
                ),
                prior_state=prior_state,
            )
            self.assertFalse(decision.dispatch_authorized)
            self.assertEqual(decision.action, action)
            self.assertEqual(decision.successor_state, successor)
            self.assertFalse(decision.completion_recordable)
            prior_state = state

    def test_policy_wrong_valid_state_fails_closed(self) -> None:
        decision = _execution_decision(
            UltimateChallengeExecutionObservation(
                state=ACTIVE_CHALLENGE_STATE,
                target_bound=True,
                native_selector_evidence=True,
                reset_identity="game-day-2026-07-20",
                source_frame_sha256=FRAME,
                target_roi=TARGET_ROI,
            ),
            prior_state=ULTIMATE_CHALLENGE_STATE,
        )
        self.assertFalse(decision.dispatch_authorized)
        self.assertEqual(decision.terminal, TERMINAL_BLOCKED)

    def test_policy_requires_explicit_matching_current_and_observation_reset(self) -> None:
        base = dict(
            state=ULTIMATE_CHALLENGE_STATE,
            target_bound=True,
            native_selector_evidence=True,
            source_frame_sha256=FRAME,
            target_roi=TARGET_ROI,
        )
        for current, observed in (
            (None, RESET_IDENTITY),
            ("", RESET_IDENTITY),
            (RESET_IDENTITY, None),
            (RESET_IDENTITY, "game-day-2026-07-19"),
        ):
            with self.subTest(current=current, observed=observed):
                decision = evaluate_execution_step(
                    UltimateChallengeExecutionObservation(
                        **base,
                        reset_identity=observed,
                    ),
                    current_reset_identity=current,
                )
                self.assertFalse(decision.dispatch_authorized)
                self.assertEqual(decision.terminal, TERMINAL_BLOCKED)

    def test_policy_completion_requires_home_after_flee(self) -> None:
        flee = _execution_decision(
            UltimateChallengeExecutionObservation(
                state=FLEE_CONFIRMED_STATE,
                target_bound=True,
                native_selector_evidence=True,
                reset_identity="game-day-2026-07-20",
                source_frame_sha256=FRAME,
                target_roi=TARGET_ROI,
            ),
            prior_state=FLEE_WARNING_STATE,
        )
        self.assertFalse(flee.completion_recordable)
        home = _execution_decision(
            UltimateChallengeExecutionObservation(
                state=HOME_RETURNED_STATE,
                target_bound=False,
                native_selector_evidence=True,
                reset_identity="game-day-2026-07-20",
                source_frame_sha256=FRAME,
                target_roi=None,
            ),
            prior_state=FLEE_CONFIRMED_STATE,
        )
        self.assertEqual(home.terminal, TERMINAL_BLOCKED)
        self.assertFalse(home.completion_recordable)
        self.assertIn(TERMINAL_COMPLETE_FOR_RESET, home.reason)
        with self.assertRaisesRegex(ValueError, "canonical Home"):
            record_verified_success(
                empty_reset_window_state(),
                reset_identity="game-day-2026-07-20",
                terminal_state=FLEE_CONFIRMED_STATE,
            )
        with self.assertRaisesRegex(ValueError, "canonical Home"):
            record_verified_success(
                empty_reset_window_state(),
                reset_identity="game-day-2026-07-20",
            )

    def test_policy_rejects_resources_auto_battle_and_missing_native_bind(self) -> None:
        base = dict(
            state=ULTIMATE_CHALLENGE_STATE,
            target_bound=True,
            native_selector_evidence=True,
            reset_identity="game-day-2026-07-20",
            source_frame_sha256=FRAME,
            target_roi=TARGET_ROI,
        )
        for changes in (
            {"resource_prompt_visible": True},
            {"resource_cost": 0},
            {"auto_battle_visible": True},
            {"refill_visible": True},
            {"target_bound": False},
            {"target_roi": None},
            {"native_selector_evidence": False},
            {"source_frame_sha256": ""},
            {"overlay_state": "warning"},
            {"recognized": False},
        ):
            decision = _execution_decision(
                UltimateChallengeExecutionObservation(**{**base, **changes})
            )
            self.assertFalse(decision.dispatch_authorized, changes)
            self.assertEqual(decision.terminal, TERMINAL_BLOCKED)

    def test_policy_already_complete_is_home_only_idempotent_noop(self) -> None:
        entry = _execution_decision(
            UltimateChallengeExecutionObservation(
                state=ULTIMATE_CHALLENGE_STATE,
                target_bound=True,
                native_selector_evidence=True,
                reset_identity="game-day-2026-07-20",
                source_frame_sha256=FRAME,
                target_roi=TARGET_ROI,
                already_complete=True,
            )
        )
        self.assertFalse(entry.dispatch_authorized)
        self.assertEqual(entry.action, ACTION_RETURN_CANONICAL_HOME)
        self.assertEqual(entry.successor_state, HOME_RETURNED_STATE)
        intermediate = _execution_decision(
            UltimateChallengeExecutionObservation(
                state=FLEE_WARNING_STATE,
                target_bound=True,
                native_selector_evidence=True,
                reset_identity="game-day-2026-07-20",
                source_frame_sha256=FRAME,
                target_roi=TARGET_ROI,
                already_complete=True,
            )
        )
        self.assertFalse(intermediate.dispatch_authorized)
        self.assertEqual(intermediate.terminal, TERMINAL_BLOCKED)
        home = _execution_decision(
            UltimateChallengeExecutionObservation(
                state=HOME_RETURNED_STATE,
                target_bound=False,
                native_selector_evidence=True,
                reset_identity="game-day-2026-07-20",
                source_frame_sha256=FRAME,
                target_roi=None,
                already_complete=True,
            ),
            prior_state=ULTIMATE_CHALLENGE_STATE,
        )
        self.assertFalse(home.dispatch_authorized)
        self.assertEqual(home.terminal, TERMINAL_BLOCKED)
        self.assertIn("native replay evidence", home.reason)

    def test_replay_gate_truthfully_requires_missing_native_fixture(self) -> None:
        gate = ultimate_challenge_zero_transport_replay_gate()
        self.assertEqual(gate.status, REPLAY_EVIDENCE_REQUIRED)
        self.assertEqual(gate.transport_count, 0)
        self.assertFalse(gate.dispatch_authorized)
        self.assertTrue(gate.evidence_required)
        self.assertEqual(
            ultimate_challenge_zero_transport_replay_gate({"native_hash_bound": False}).status,
            REPLAY_EVIDENCE_REQUIRED,
        )
        self.assertEqual(
            ultimate_challenge_zero_transport_replay_gate(
                {"native_hash_bound": True, "source_frame_sha256": FRAME}
            ).status,
            REPLAY_EVIDENCE_REQUIRED,
        )


if __name__ == "__main__":
    unittest.main()
