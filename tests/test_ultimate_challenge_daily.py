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
    COMPLETION_COMPLETED,
    COMPLETION_NOT_COMPLETED,
    COMPLETION_UNKNOWN,
    FLOW_ID,
    TERMINAL_ALREADY_COMPLETED,
    TERMINAL_BLOCKED,
    TERMINAL_NAVIGATION_ONLY_COMPLETE,
    ULTIMATE_CHALLENGE_ENTRY_IDENTITY,
    ULTIMATE_CHALLENGE_OBJECTIVE,
    UltimateChallengeEntryObservation,
    UltimateChallengeResetWindowState,
    empty_reset_window_state,
    evaluate_already_completed,
    evaluate_navigation_only,
    load_reset_window_state,
    record_verified_success,
    recognize_ultimate_challenge_entry_from_texts,
    save_reset_window_state,
    ultimate_challenge_already_completed_from_ocr_hits,
    ultimate_challenge_entry_roi_from_ocr_hits,
)


FRAME = "a" * 64


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
            updated = record_verified_success(state, reset_identity="game-day-2026-07-20")
            save_reset_window_state(path, updated)
            loaded = load_reset_window_state(path)
            self.assertEqual(loaded.completion_state, COMPLETION_COMPLETED)
            self.assertEqual(loaded.last_success_reset_identity, "game-day-2026-07-20")
            self.assertEqual(loaded.flow_id, FLOW_ID)
            with self.assertRaisesRegex(ValueError, "same reset window"):
                record_verified_success(loaded, reset_identity="game-day-2026-07-20")

    def test_record_success_requires_positive_reset_identity(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive reset identity"):
            record_verified_success(empty_reset_window_state(), reset_identity="")

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


if __name__ == "__main__":
    unittest.main()
