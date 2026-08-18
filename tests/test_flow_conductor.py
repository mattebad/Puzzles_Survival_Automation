"""Focused tests for the autonomous flow-delivery conductor."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import pnsctl
from tasks.flow_conductor import (
    ConductorDecision,
    FramingChecklist,
    apply_framing,
    classify_summary,
    load_state,
    record_iteration,
    save_state,
)


class FlowConductorTests(unittest.TestCase):
    def test_framing_incomplete_blocks_continue(self) -> None:
        state = load_state("ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION")
        state = apply_framing(
            state,
            FramingChecklist(intent_match=True),
        )
        self.assertEqual(
            state.last_decision, ConductorDecision.FRAMING_INCOMPLETE.value
        )

    def test_classify_done_and_external_block(self) -> None:
        state = load_state("NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE")
        done, _ = classify_summary(
            {"status": "completed", "terminal_home_verified": True},
            state=state,
        )
        self.assertEqual(done, ConductorDecision.DONE)
        blocked, reason = classify_summary(
            {"status": "blocked", "blocker": "manual_only_state"},
            state=state,
        )
        self.assertEqual(blocked, ConductorDecision.EXTERNAL_BLOCK)
        self.assertIn("manual", reason)

    def test_repeat_defect_triggers_step_back_then_escalate(self) -> None:
        state = load_state("FLOW-A")
        state = record_iteration(
            state,
            summary={"status": "blocked", "blocker": "initial_surface_not_home"},
        )
        self.assertEqual(state.last_decision, ConductorDecision.CONTINUE.value)
        state = record_iteration(
            state,
            summary={"status": "blocked", "blocker": "initial_surface_not_home"},
        )
        self.assertEqual(state.last_decision, ConductorDecision.STEP_BACK.value)
        self.assertEqual(state.step_backs_spent, 1)
        state = record_iteration(
            state,
            summary={"status": "blocked", "blocker": "initial_surface_not_home"},
        )
        self.assertEqual(state.last_decision, ConductorDecision.ESCALATE.value)

    def test_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = load_state("FLOW-B", root=root)
            state = apply_framing(
                state,
                FramingChecklist(
                    intent_match=True,
                    no_documented_unsafe_input=True,
                    no_manual_only_precondition=True,
                    consequential_actions_enumerated=True,
                    durable_knowledge_consulted=True,
                ),
            )
            path = save_state(state, root=root)
            loaded = load_state("FLOW-B", root=root)
            self.assertEqual(loaded.status, "framed")
            self.assertTrue(path.is_file())

    def test_pnsctl_conduct_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code = pnsctl.main(
                [
                    "conduct",
                    "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION",
                    "--state-root",
                    str(root),
                ]
            )
            self.assertEqual(code, 0)
            state = load_state(
                "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION", root=root
            )
            self.assertEqual(state.status, "framed")

    def test_pnsctl_conduct_classifies_summary_without_live(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = Path(directory) / "summary.json"
            summary.write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "blocker": "initial_surface_not_home_or_known_nova_context",
                    }
                ),
                encoding="utf-8",
            )
            code = pnsctl.main(
                [
                    "conduct",
                    "NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE",
                    "--summary",
                    str(summary),
                    "--state-root",
                    str(root),
                ]
            )
            self.assertEqual(code, 0)
            state = load_state("NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE", root=root)
            self.assertEqual(state.last_decision, ConductorDecision.CONTINUE.value)
            self.assertEqual(state.status, "local_defect")


if __name__ == "__main__":
    unittest.main()
