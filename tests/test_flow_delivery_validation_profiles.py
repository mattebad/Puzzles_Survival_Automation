"""Focused tests for the proportionate flow-delivery validation profiles (Phase 4b).

These assert resolution and stage mapping only; they do not spawn the unittest subprocess.
"""

from __future__ import annotations

import unittest

from scripts import run_flow_delivery_validation as runner


_QUEUE = {"flows": [{"flow_id": "SYNTHETIC-FLOW", "focused_tests": []}]}


def _resolve(profile: str) -> list[str]:
    profiles = runner._load_profiles()
    return runner._resolve_unittest_targets(
        profiles,
        profile=profile,
        flow_id="SYNTHETIC-FLOW",
        queue=_QUEUE,
    )


class ProportionateProfileTests(unittest.TestCase):
    def test_aliases_map_to_expected_profiles(self) -> None:
        self.assertEqual(runner.PROFILE_ALIASES["shared-navigation"], "shared_navigation")
        self.assertEqual(runner.PROFILE_ALIASES["task-navigation"], "focused_tests")
        self.assertEqual(runner.PROFILE_ALIASES["promotion"], "promotion")
        self.assertEqual(runner.PROFILE_ALIASES["detector"], "detector")
        self.assertEqual(runner.PROFILE_ALIASES["consequential"], "consequential")
        for resolved in ("shared_navigation", "promotion", "detector", "consequential"):
            self.assertIn(resolved, runner.ALLOWED_PROFILES)
        # Existing vocabulary must remain intact.
        for resolved in ("focused_tests", "architecture_tests", "full_suite", "governance"):
            self.assertIn(resolved, runner.ALLOWED_PROFILES)

    def test_shared_navigation_resolves_to_boundary_only(self) -> None:
        self.assertEqual(_resolve("shared_navigation"), ["tests.test_navigation_development_boundary"])

    def test_promotion_bundles_architecture_and_governance(self) -> None:
        targets = _resolve("promotion")
        self.assertIn("tests.test_governance_validation", targets)
        self.assertIn("tests.test_flow_delivery_orchestrator", targets)
        self.assertNotIn("discover", targets)

    def test_flow_declared_profiles_without_targets_fail_closed(self) -> None:
        for profile in ("detector", "consequential"):
            with self.assertRaisesRegex(runner.ValidationRunnerError, "no checked-in targets"):
                _resolve(profile)

    def test_stage_mapping_is_proportionate(self) -> None:
        self.assertEqual(runner._stage_for_profile("shared_navigation"), "navigation_validation")
        self.assertEqual(runner._stage_for_profile("detector"), "navigation_validation")
        self.assertEqual(runner._stage_for_profile("consequential"), "consequential_validation")
        self.assertEqual(runner._stage_for_profile("promotion"), "promotion_validation")
        self.assertEqual(runner._stage_for_profile("full_suite"), "full_validation")
        for focused in ("focused_tests", "architecture_tests", "governance"):
            self.assertEqual(runner._stage_for_profile(focused), "focused_validation")

    def test_full_suite_still_requires_discover_only(self) -> None:
        self.assertEqual(_resolve("full_suite"), ["discover"])

    def test_full_suite_is_manual_opt_in(self) -> None:
        with self.assertRaisesRegex(
            runner.ValidationRunnerError,
            "full_suite is manual-only",
        ):
            runner.run_profile(
                flow_id="SYNTHETIC-FLOW",
                profile_alias="full",
            )


if __name__ == "__main__":
    unittest.main()
