"""Behavioral coverage checks against real unittest discovery."""
from copy import deepcopy
import io
from pathlib import Path
import sys
import tempfile
import unittest
from types import ModuleType
from unittest.mock import patch

from scripts.check_test_discovery import validate_discovery
from scripts.offline_suite import (
    ExecutionResult, partition_modules, select_suite, validate_receipts,
)


TEST_MODULE = """import unittest
class Example(unittest.TestCase):
    def test_behavior(self):
        self.fail("discovery must not execute fixture test bodies")
"""


class DiscoveryCoverageTests(unittest.TestCase):
    def discover(self, sources):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        directory = root / "fixture_suite"
        directory.mkdir()
        (directory / "__init__.py").write_text("", encoding="utf-8")
        for name, source in sources.items():
            (directory / name).write_text(source, encoding="utf-8")
        with patch.dict(sys.modules), patch.object(sys, "path", list(sys.path)):
            loader = unittest.TestLoader()
            suite = loader.discover(str(directory), pattern="test_*.py", top_level_dir=str(root))
        self.assertEqual(loader.errors, [])
        return directory, suite

    def test_all_discovered_modules_are_counted(self):
        directory, suite = self.discover({"test_first.py": TEST_MODULE, "test_second.py": TEST_MODULE})
        self.assertEqual(validate_discovery(directory, suite), (2, 2))

    def test_empty_module_cannot_silently_disappear(self):
        directory, suite = self.discover({"test_first.py": TEST_MODULE, "test_empty.py": ""})
        with self.assertRaises(RuntimeError) as caught:
            validate_discovery(directory, suite)
        self.assertIn("fixture_suite.test_empty", str(caught.exception))

    def test_load_tests_cannot_hide_a_modules_cases(self):
        hidden = TEST_MODULE + "\ndef load_tests(loader, tests, pattern):\n    return unittest.TestSuite()\n"
        directory, suite = self.discover({"test_first.py": TEST_MODULE, "test_hidden.py": hidden})
        with self.assertRaises(RuntimeError) as caught:
            validate_discovery(directory, suite)
        self.assertIn("fixture_suite.test_hidden", str(caught.exception))

    def test_duplicate_discovered_case_ids_are_rejected(self):
        repeated = TEST_MODULE + (
            "\ndef load_tests(loader, tests, pattern):\n"
            "    first = loader.loadTestsFromTestCase(Example)\n"
            "    second = loader.loadTestsFromTestCase(Example)\n"
            "    return unittest.TestSuite([first, second])\n"
        )
        directory, suite = self.discover({"test_repeated.py": repeated})
        with self.assertRaises(RuntimeError) as caught:
            validate_discovery(directory, suite)
        self.assertIn("fixture_suite.test_repeated.Example.test_behavior", str(caught.exception))


class OfflineShardCoverageTests(unittest.TestCase):
    def receipts(self):
        ids = ["tests.test_first.Example.test_a", "tests.test_first.Example.test_b",
               "tests.test_second.Example.test_c"]
        reports = []
        for index, selected in enumerate((ids[:2], ids[2:])):
            reports.append({
                "schema": 1, "index": index, "count": 2, "platform": "Linux",
                "revision": "same-revision", "discovered_ids": ids[:],
                "selected_ids": selected[:], "executed_ids": selected[:],
                "tests_run": len(selected), "success": True,
                "failures": [], "errors": [], "skipped_ids": [],
            })
        return reports

    def verify(self, reports, **changes):
        return validate_receipts(
            reports, count=2, platform_name="Linux", allowed_skips=(),
            **changes,
        )

    def test_new_modules_are_assigned_without_a_timing_allowlist(self):
        modules = ["tests.test_known", "tests.test_new", "tests.test_other"]
        shards = partition_modules(modules, {"tests.test_known": 20}, 2)
        self.assertCountEqual([name for shard in shards for name in shard], modules)

    def test_reserved_checks_are_included_when_balancing_modules(self):
        weights = {"a": 9, "b": 8, "c": 7, "d": 6}
        shards = partition_modules(weights, weights, 2, reserved_seconds=20)
        loads = [sum(weights[name] for name in shard) + (20 if index == 0 else 0)
                 for index, shard in enumerate(shards)]
        self.assertLessEqual(max(loads), 26)

    def test_missing_repeated_and_incomplete_execution_are_rejected(self):
        complete = self.receipts()
        self.assertEqual(self.verify(complete), (3, 0))
        mutations = {}
        mutations["missing-shard"] = deepcopy(complete[:1])
        duplicate = deepcopy(complete)
        duplicate[1]["index"] = 0
        mutations["duplicate-shard"] = duplicate
        hidden = deepcopy(complete)
        hidden[1].update(selected_ids=[], executed_ids=[], tests_run=0)
        mutations["omitted-case"] = hidden
        repeated = deepcopy(complete)
        repeated[1]["selected_ids"].append(complete[0]["selected_ids"][0])
        repeated[1]["executed_ids"].append(complete[0]["executed_ids"][0])
        repeated[1]["tests_run"] += 1
        mutations["repeated-case"] = repeated
        unexecuted = deepcopy(complete)
        unexecuted[1].update(executed_ids=[], tests_run=0)
        mutations["planned-but-not-run"] = unexecuted
        different = deepcopy(complete)
        different[1]["discovered_ids"].pop()
        mutations["different-discovery"] = different
        failed = deepcopy(complete)
        failed[0]["success"] = False
        mutations["failed-shard"] = failed
        inconsistent = deepcopy(complete)
        inconsistent[0]["tests_run"] -= 1
        mutations["wrong-execution-count"] = inconsistent
        for name, reports in mutations.items():
            with self.subTest(case=name), self.assertRaises(ValueError):
                self.verify(reports)

    def test_new_skips_fail_even_when_total_skip_count_is_unchanged(self):
        reports = self.receipts()
        reports[1]["skipped_ids"] = reports[1]["selected_ids"][:]
        with self.assertRaises(ValueError):
            validate_receipts(
                reports, count=2, platform_name="Linux",
                allowed_skips=(reports[0]["selected_ids"][0],),
            )

    def test_receipts_from_another_revision_cannot_satisfy_coverage(self):
        reports = self.receipts()
        reports[1]["revision"] = "another-revision"
        with self.assertRaises(ValueError):
            self.verify(reports, revision="same-revision")

    def test_duplicate_discovery_cannot_authorize_duplicate_execution(self):
        bodies = []

        class RepeatedCase(unittest.TestCase):
            def test_body(self):
                bodies.append("executed")

        cases = [RepeatedCase("test_body"), RepeatedCase("test_body")]
        case_id = cases[0].id()
        result = unittest.TextTestRunner(
            stream=io.StringIO(), resultclass=ExecutionResult,
        ).run(unittest.TestSuite(cases))
        self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
        self.assertEqual(bodies, ["executed", "executed"])
        receipt = {
            "schema": 1, "index": 0, "count": 1, "platform": "Linux",
            "revision": "same-revision", "discovered_ids": [case_id, case_id],
            "selected_ids": [case_id, case_id], "executed_ids": result.executed_ids,
            "tests_run": result.testsRun, "success": result.wasSuccessful(),
            "failures": [], "errors": [], "skipped_ids": [],
        }
        with self.assertRaises(ValueError) as caught:
            validate_receipts(
                [receipt], count=1, platform_name="Linux", allowed_skips=(),
                revision="same-revision",
            )
        self.assertIn(case_id, str(caught.exception))

    def test_selected_modules_keep_real_module_and_class_fixtures(self):
        events = []
        state = {}

        def fixture(name, allowed):
            module = ModuleType(name)

            def module_setup():
                state[name] = "module"
                events.append("module-setup")

            def module_teardown():
                del state[name]
                events.append("module-teardown")

            def class_setup(_cls):
                self.assertEqual(state[name], "module")
                state[name] = "class"
                events.append("class-setup")

            def class_teardown(_cls):
                self.assertEqual(state[name], "class")
                state[name] = "module"
                events.append("class-teardown")

            def body(case):
                case.assertTrue(allowed, "unselected module executed")
                case.assertEqual(state[name], "class")
                events.append("body")

            module.setUpModule = module_setup
            module.tearDownModule = module_teardown
            example = type("Example", (unittest.TestCase,), {
                "__module__": name, "setUpClass": classmethod(class_setup),
                "tearDownClass": classmethod(class_teardown),
                "test_first": body, "test_second": body,
            })
            return module, [example("test_first"), example("test_second")]

        first_module, first = fixture("fixture_shard_first", True)
        second_module, second = fixture("fixture_shard_second", False)
        suite = unittest.TestSuite([
            unittest.TestSuite([first[0], unittest.TestSuite([first[1]])]),
            unittest.TestSuite(second),
        ])
        with patch.dict(sys.modules, {
            first_module.__name__: first_module, second_module.__name__: second_module,
        }):
            result = unittest.TextTestRunner(
                stream=io.StringIO(), resultclass=ExecutionResult,
            ).run(select_suite(suite, (first_module.__name__,)))
        self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
        self.assertEqual(result.executed_ids, [case.id() for case in first])
        self.assertEqual(events, [
            "module-setup", "class-setup", "body", "body",
            "class-teardown", "module-teardown",
        ])
        self.assertEqual(state, {})
