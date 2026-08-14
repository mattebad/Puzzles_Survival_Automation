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

    def test_route_and_parent_integration_guardrails_are_project_local(self) -> None:
        for marker in (
            "| Substantive live gameplay-flow development | Heavy; parent orchestration with `executor_luna`",
            "Promote Medium to Heavy",
            "second materially distinct live failure",
            "One initial live failure alone",
            "the parent performs the integration review and owns the final integration decision",
            "one coherent pre-canary integration acceptance",
            "one parent integration gate",
            "do not automatically spawn a child `executor_sol`",
            "no child Sol review is automatic",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.agents)
        self.assertNotIn(
            "exactly one coherent pre-canary `executor_sol` integration gate",
            self.agents,
        )
        self.assertNotIn(
            "must trigger a dedicated `executor_sol` integration review",
            self.agents,
        )

    def test_compact_ladder_and_manual_full_rule_are_explicit(self) -> None:
        for marker in (
            "exact failing regression",
            "each affected package suite once",
            "focused flow profile once before canary",
            "shared-navigation",
            "parent-owned integration gate",
            "zero-input observation",
            "semantic result",
            "manual-only",
            "explicit user route selection wins",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.policy)
        self.assertIn("python scripts/run_flow_delivery_validation.py full", self.policy)
        self.assertIn("--manual", self.policy)
        self.assertNotIn("Sol gate", self.policy)
        self.assertIn("do not create a second validation framework", self.agents.lower())


if __name__ == "__main__":
    unittest.main()
