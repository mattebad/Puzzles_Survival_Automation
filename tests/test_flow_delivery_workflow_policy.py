"""Literal guardrails for the project-local flow-delivery workflow policy."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FlowDeliveryWorkflowPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        cls.policy = (ROOT / "docs" / "flow-delivery-validation-policy.md").read_text(
            encoding="utf-8"
        )

    def test_route_and_review_guardrails_are_project_local(self) -> None:
        for marker in (
            "| Substantive live gameplay-flow development | Heavy; parent orchestration with `executor_luna`",
            "Promote Medium to Heavy",
            "second materially distinct live failure",
            "One initial live failure alone",
            "exactly one coherent pre-canary `executor_sol` integration gate",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.agents)

    def test_compact_ladder_and_manual_full_rule_are_explicit(self) -> None:
        for marker in (
            "exact failing regression",
            "each affected package suite once",
            "focused flow profile once before canary",
            "shared-navigation",
            "zero-input observation",
            "semantic result",
            "manual-only",
            "explicit user route selection wins",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.policy)
        self.assertIn("python scripts/run_flow_delivery_validation.py full", self.policy)
        self.assertIn("--manual", self.policy)
        self.assertIn("do not create a second validation framework", self.agents.lower())


if __name__ == "__main__":
    unittest.main()
