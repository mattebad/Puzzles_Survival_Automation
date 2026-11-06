"""Consumer-visible scope and fail-closed behavior for offline CI selection."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import offline_selection as selection


def case(module: str, method: str = "test_case") -> str:
    return f"tests.test_{module}.Cases.{method}"


class OfflineSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ("WINDOWS_BASELINE", "LINUX_BASELINE"):
            patched = patch.object(selection, name, ("tests.test_baseline",))
            patched.start()
            self.addCleanup(patched.stop)

    def write(self, path: str, source: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")

    def select(self, modules: list[str], paths: list[str] | None, platform: str = "windows") -> selection.Selection:
        return selection.build_selection(
            [case("baseline"), *(case(module) for module in modules)], paths, platform, self.root,
        )

    def test_documentation_and_empty_changes_keep_platform_baseline(self) -> None:
        for platform in ("windows", "linux"):
            for paths in ([], ["docs/agent/CURRENT_HANDOFF.md", "README.md", ".gitattributes"]):
                with self.subTest(platform=platform, paths=paths):
                    result = self.select(["campaign_native"], paths, platform)
                    self.assertEqual(result.intended_ids, (case("baseline"),))
                    self.assertEqual(result.omitted_ids, (case("campaign_native"),))
                    self.assertEqual(result.profile, "risk-based")

    def test_platform_baselines_are_independent(self) -> None:
        with patch.object(selection, "LINUX_BASELINE", ("tests.test_linux",)):
            result = self.select(["linux", "campaign_native"], [], "linux")
        self.assertEqual(result.intended_ids, (case("linux"),))

    def test_route_family_includes_transitive_consumers_without_lazy_fanout(self) -> None:
        self.write("tasks/campaign_new.py", "VALUE = 1\n")
        self.write("tasks/bridge.py", "if True:\n    from . import campaign_new\n")
        self.write("tests/test_consumer.py", "def test_lazy():\n    from tasks import bridge\n")
        self.write("scripts/pnsctl.py", "from tasks import campaign_new\n")
        self.write("scripts/route_wrapper.py", "def operator():\n    from scripts import pnsctl\n")
        self.write("tests/test_unrelated.py", "from scripts import route_wrapper\n")
        result = self.select(["campaign_native", "consumer", "unrelated", "nova_native"], ["tasks/campaign_new.py"])
        self.assertEqual(result.intended_ids, (case("baseline"), case("campaign_native"), case("consumer")))
        self.assertEqual(result.omitted_ids, (case("unrelated"), case("nova_native")))

    def test_new_import_dependency_changes_are_seen_without_name_heuristics(self) -> None:
        self.write("tasks/new_dependency.py", "VALUE = 1\n")
        self.write("automation_service/nova.py", "from tasks.new_dependency import VALUE\n")
        self.write("tests/test_custom_consumer.py", "import automation_service.nova\n")
        result = self.select(["custom_consumer", "campaign_native"], ["tasks/new_dependency.py"])
        self.assertEqual(result.profile, "risk-based")
        self.assertIn(case("custom_consumer"), result.intended_ids)
        self.assertIn(case("campaign_native"), result.omitted_ids)

    def test_relative_from_import_resolves_nested_package(self) -> None:
        self.write("tasks/route/dependency.py", "VALUE = 1\n")
        self.write("tasks/route/bridge.py", "from .dependency import VALUE\n")
        self.write("tests/test_nested_consumer.py", "from tasks.route import bridge\n")
        result = self.select(["nested_consumer", "unrelated"], ["tasks/route/dependency.py"])
        self.assertEqual(result.intended_ids, (case("baseline"), case("nested_consumer")))

    def test_shared_core_selects_owners_and_dispatch_without_historical_routes(self) -> None:
        result = self.select([
            "safe_action_core", "automation_service_state", "service_route_contract",
            "service_supply_dispatch", "campaign_victory_native", "nova_zero_counter",
        ], ["safe_action_core/executor.py"])
        for module in ("safe_action_core", "automation_service_state", "service_route_contract", "service_supply_dispatch"):
            self.assertIn(case(module), result.intended_ids)
        self.assertEqual(result.omitted_ids, (case("campaign_victory_native"), case("nova_zero_counter")))

    def test_shared_home_and_ocr_keep_bounded_owners(self) -> None:
        home = self.select(["home_atlas", "navigation_session", "perception_bundle", "radial_semantics", "campaign_victory_native"], ["tasks/home_base_vision.py"])
        self.assertIn(case("home_atlas"), home.intended_ids)
        self.assertIn(case("navigation_session"), home.intended_ids)
        self.assertIn(case("perception_bundle"), home.intended_ids)
        self.assertIn(case("radial_semantics"), home.intended_ids)
        self.assertEqual(home.omitted_ids, (case("campaign_victory_native"),))
        ocr = self.select(["bounded_ocr_architecture", "semantic_ocr_crop", "ocr_memo", "test_environment", "campaign_victory_native"], ["scripts/bounded_tesseract.py"])
        self.assertEqual(ocr.omitted_ids, (case("campaign_victory_native"),))

    def test_linux_core_change_selects_full_ocr_crop_and_deadline_owners(self) -> None:
        owners = ["semantic_ocr_crop", "enhancement_material_label_crop", "enhancement_ocr_deadline", "ocr_memo"]
        result = self.select([*owners, "campaign_victory_native"], ["safe_action_core/semantic_ocr_crop.py"], "linux")
        self.assertEqual(result.profile, "risk-based")
        for module in owners:
            self.assertIn(case(module), result.intended_ids)
        self.assertEqual(result.omitted_ids, (case("campaign_victory_native"),))

    def test_profile_geometry_change_includes_all_route_consumers(self) -> None:
        result = self.select(["home_base_vision", "campaign_victory_native", "nova", "troop_training"], ["tasks/profile.py"])
        self.assertEqual(result.profile, "full-fallback")
        self.assertFalse(result.omitted_ids)
        self.assertTrue(any("profile and geometry" in reason for reason in result.reasons))

    def test_popup_selects_real_two_overlay_representatives(self) -> None:
        representatives = selection.POPUP_REPRESENTATIVES
        ids = (case("baseline"), case("startup_recovery"), *representatives, case("enhancement_native_history"))
        result = selection.build_selection(ids, ["scripts/bluestacks_popup_recognition.py"], "windows", self.root)
        self.assertEqual(result.intended_ids, ids[:-1])
        self.assertEqual(result.omitted_ids, ids[-1:])

    def test_runtime_boundary_selects_shared_owners_and_dispatch_adapters(self) -> None:
        result = self.select(["development_session", "pnsctl_canonical_serve", "route_metadata_consistency", "service_enhancement_dispatch", "enhancement_native_history"], ["scripts/navigation_development_boundary.py"])
        self.assertEqual(result.omitted_ids, (case("enhancement_native_history"),))

    def test_route_fixtures_and_assets_trigger_family(self) -> None:
        for path in ("tests/fixtures/enhancement_item_modal/frame.png", "tasks/assets/enhancement/800x1280/button.png"):
            with self.subTest(path=path):
                result = self.select(["enhancement", "service_enhancement", "flow_delivery_enhancement", "daily_enhancement", "bioenhancer"], [path])
                self.assertEqual(result.omitted_ids, (case("bioenhancer"),))

    def test_nanoweapon_is_distinct_from_enhancement_family(self) -> None:
        for path, intended, omitted in (
            ("tasks/enhancement.py", "enhancement", "nanoweapon"),
            ("tasks/nanoweapon.py", "nanoweapon", "enhancement"),
        ):
            with self.subTest(path=path):
                result = self.select(["enhancement", "nanoweapon"], [path])
                self.assertIn(case(intended), result.intended_ids)
                self.assertIn(case(omitted), result.omitted_ids)

    def test_shared_resource_and_runtime_fixtures_select_known_owners(self) -> None:
        for path, intended in (
            ("tests/fixtures/resource_effect_authority/history.json", "resource_effect_authority_history"),
            ("tests/fixtures/runtime_control_sequences/manifest.json", "runtime_trace_projection"),
            ("tests/fixtures/runtime_trace_projection/vip_popup_ocr_snapshot.json", "runtime_trace_projection"),
        ):
            with self.subTest(path=path):
                result = self.select([intended, "campaign_victory_native"], [path])
                self.assertEqual(result.profile, "risk-based")
                self.assertIn(case(intended), result.intended_ids)
                self.assertEqual(result.omitted_ids, (case("campaign_victory_native"),))

    def test_mixed_fixture_and_unknown_assets_fall_back(self) -> None:
        for path in ("tests/fixtures/nova_praise_preflight/frame.png", "tasks/assets/unknown/button.png"):
            with self.subTest(path=path):
                result = self.select(["nova", "campaign_native"], [path])
                self.assertEqual(result.profile, "full-fallback")
                self.assertFalse(result.omitted_ids)

    def test_contract_metadata_selects_metadata_and_route_owners(self) -> None:
        result = self.select(["gameplay_flow_contracts", "product_authority", "route_metadata_consistency", "campaign_native", "nova"], ["tasks/gameplay_flow_contracts/CAMPAIGN-AP-AUTO-BATTLE.json"])
        self.assertEqual(result.omitted_ids, (case("nova"),))

    def test_changed_new_test_module_is_always_selected_and_deleted_is_harmless(self) -> None:
        result = self.select(["brand_new", "unrelated"], ["tests/test_brand_new.py", "tests/test_deleted.py"])
        self.assertEqual(result.intended_ids, (case("baseline"), case("brand_new")))
        self.assertEqual(result.profile, "risk-based")

    def test_check_policy_changes_select_gate_owners_without_full_suite(self) -> None:
        for path in (".github/workflows/offline.yml", "scripts/offline_selection.py", "scripts/check.py"):
            with self.subTest(path=path):
                result = self.select(["offline_selection", "test_discovery", "check_entrypoint", "static_checks", "campaign_native"], [path])
                self.assertEqual(result.omitted_ids, (case("campaign_native"),))

    def test_unknown_production_and_unreliable_changes_fall_back(self) -> None:
        for paths in (None, ["tasks/unowned.py"], ["settings.json"], ["custom_runtime.cpp"]):
            with self.subTest(paths=paths):
                result = self.select(["unrelated"], paths)
                self.assertEqual(result.profile, "full-fallback")
                self.assertFalse(result.omitted_ids)
                self.assertGreater(len(result.reasons), 1)

    def test_unreadable_import_graph_falls_back(self) -> None:
        self.write("tasks/campaign.py", "not valid python (\n")
        result = self.select(["campaign", "unrelated"], ["tasks/campaign.py"])
        self.assertEqual(result.profile, "full-fallback")

    def test_package_dependency_and_test_support_changes_fall_back(self) -> None:
        for path in ("tasks/__init__.py", "requirements-dev.txt", "pyproject.toml", "tests/support/navigation.py", "tests/ocr_memo.py"):
            with self.subTest(path=path):
                result = self.select(["unrelated"], [path])
                self.assertEqual(result.profile, "full-fallback")

    def test_malformed_paths_are_rejected_and_windows_separators_normalize(self) -> None:
        for path in ("../outside.py", "tasks/../../outside.py", "/absolute.py", "C:\\absolute.py", "C:relative.py", "\\\\server\\share\\x", "", " tasks/foo.py", "tasks/\x00x"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.select(["unrelated"], [path])
        result = self.select(["new"], ["tests\\test_new.py"])
        self.assertIn(case("new"), result.intended_ids)

    def test_missing_baseline_selector_and_duplicate_discovery_are_errors(self) -> None:
        with patch.object(selection, "WINDOWS_BASELINE", ("tests.test_missing",)):
            with self.assertRaises(ValueError):
                self.select(["unrelated"], [])
        with self.assertRaises(ValueError):
            selection.build_selection([case("baseline"), case("baseline")], None, "windows", self.root)

    def test_baseline_method_and_class_selectors_are_strict(self) -> None:
        ids = (case("baseline", "test_second"), case("baseline", "test_first"), case("other"))
        with patch.object(selection, "WINDOWS_BASELINE", ("tests.test_baseline.Cases",)):
            result = selection.build_selection(ids, [], "windows", self.root)
            self.assertEqual(result.intended_ids, ids[:2])
        with patch.object(selection, "WINDOWS_BASELINE", (ids[1],)):
            result = selection.build_selection(ids, [], "windows", self.root)
            self.assertEqual(result.intended_ids, (ids[1],))

    def test_calibration_research_is_explicitly_outside_runtime_coverage(self) -> None:
        result = self.select(["unrelated"], ["calibration/transform.py"])
        self.assertEqual(result.intended_ids, (case("baseline"),))
        self.assertTrue(any("calibration" in reason for reason in result.reasons))


class RegisteredRouteSelectionTests(unittest.TestCase):
    def test_registered_executors_have_required_consumer_boundaries(self):
        from automation_service.registry import CANONICAL_FLOW_REGISTRY

        servable = {entry.cli_name for entry in CANONICAL_FLOW_REGISTRY if entry.cli_name is not None}
        self.assertEqual(set(selection.ROUTE_BOUNDARIES), servable)
        for route, selector in selection.ROUTE_BOUNDARIES.items():
            with self.subTest(route=route):
                self.assertIn(selector, selection.WINDOWS_BASELINE)


if __name__ == "__main__":
    unittest.main()
