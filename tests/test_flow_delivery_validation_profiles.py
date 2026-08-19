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

    def test_unregistered_development_flows_have_focused_profiles(self) -> None:
        profiles = runner._load_profiles()
        for flow_id, target in (
            (
                "BIOENHANCER-FREE-RESEARCH-BLUESTACKS-INTEGRATION",
                "tests.test_flow_delivery_bioenhancer_bluestacks",
            ),
            (
                "SUPPLY-DEPOT-BLUESTACKS-INTEGRATION",
                "tests.test_flow_delivery_supply_depot_bluestacks",
            ),
        ):
            with self.subTest(flow_id=flow_id):
                self.assertEqual(
                    runner._resolve_unittest_targets(
                        profiles,
                        profile="focused_tests",
                        flow_id=flow_id,
                        queue={"flows": []},
                    ),
                    [target],
                )

    def test_daily_resource_item_profile_is_focused_and_consequential(self) -> None:
        profiles = runner._load_profiles()
        profile = profiles["flow_profiles"]["DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION"]
        self.assertEqual(profile["maximum_inputs"], 11)
        self.assertEqual(profile["maximum_resource_list_swipes"], 8)
        self.assertEqual(
            runner._resolve_unittest_targets(
                profiles,
                profile="focused_tests",
                flow_id="DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION",
                queue={"flows": []},
            ),
            [
                "tests.test_daily_resource_item_bluestacks",
                "tests.test_flow_delivery_daily_resource_item_bluestacks",
                "tests.test_gameplay_flow_contracts",
                "tests.test_flow_delivery_validation_profiles",
            ],
        )
        self.assertEqual(
            runner._resolve_unittest_targets(
                profiles,
                profile="consequential",
                flow_id="DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION",
                queue={"flows": []},
            ),
            ["tests.test_flow_delivery_daily_resource_item_bluestacks"],
        )

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
