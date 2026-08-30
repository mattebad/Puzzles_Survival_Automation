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
        normalized_agents = " ".join(self.agents.split())
        for marker in (
            "| Routine live flow delivery / lean reproof of an already-contracted flow | Medium via `pnsctl conduct`",
            "Promote to Heavy only for architecture, safety-boundary, cross-contract redesign, or `diminishing_returns` STEP_BACK",
            "| New architecture, safety-boundary, or cross-contract redesign | Heavy; Sol control-plane with bounded Luna + Terra",
            "One initial live failure alone",
            "the parent performs the integration review and owns the final integration decision",
            "The Sol parent owns architecture and one coherent pre-canary integration acceptance",
            "one parent integration gate",
            "do not automatically spawn a child `executor_sol`",
            "no child Sol review is automatic",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, normalized_agents)
        self.assertNotIn(
            "exactly one coherent pre-canary `executor_sol` integration gate",
            normalized_agents,
        )
        self.assertNotIn(
            "must trigger a dedicated `executor_sol` integration review",
            normalized_agents,
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

    def test_explicit_solo_route_overrides_ceremony_not_safety(self) -> None:
        normalized_agents = " ".join(self.agents.split())
        normalized_policy = " ".join(self.policy.split())
        for marker in (
            "Recognized `Solo` route override",
            "`Route: Solo`",
            "One named agent serially owns planning, architecture, implementation",
            "overrides Light/Medium/Heavy role choreography",
            "never silently substitute another model",
            "review as pending rather than claiming it occurred",
            "hard safety/manual/user-decision blockers still stop",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, normalized_agents)
        for marker in (
            "explicitly selected `Solo` route",
            "does not waive this validation ladder",
            "closure records it as pending",
            "Absent an explicit `Solo` selection",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, normalized_policy)

    def test_runtime_phases_keep_current_bluestacks_and_future_bliss_distinct(self) -> None:
        normalized = " ".join(self.agents.split())
        for marker in (
            "current active-development runtime is the private local BlueStacks instance",
            "Current reconnaissance, implementation canaries, and flow acceptance run on BlueStacks",
            "Use the local BlueStacks / P&S emulator for current live verification",
            "future porting and deployment-acceptance target",
            "Do not substitute Bliss for an active BlueStacks development task",
            "A BlueStacks pass does not prove Bliss acceptance",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, normalized)
        self.assertNotIn(
            "Production runtime is the Unraid-hosted Bliss OS VM",
            self.agents,
        )
        self.assertNotIn(
            "Use the Bliss OS / P&S emulator only when actual runtime behavior requires live verification",
            self.agents,
        )


if __name__ == "__main__":
    unittest.main()
