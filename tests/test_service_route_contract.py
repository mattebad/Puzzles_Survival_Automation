"""Cross-route service safety invariants; no transport or device access."""
from __future__ import annotations

import importlib
import unittest

from automation_service.registry import CANONICAL_FLOW_REGISTRY, ULTIMATE_FLOW_ID
from tests.support.service_route_contract import EXCEPTIONS, NOT_SERVABLE, ROUTES, RouteRig


class RouteTableTests(unittest.TestCase):
    def test_every_registered_route_is_in_the_contract_or_explicitly_excluded(self):
        self.assertEqual(
            set(ROUTES) | set(NOT_SERVABLE),
            {entry.flow_id for entry in CANONICAL_FLOW_REGISTRY},
        )
        self.assertTrue(set(ROUTES).isdisjoint(NOT_SERVABLE))
        for flow_id, spec in ROUTES.items():
            with self.subTest(route=flow_id):
                self.assertEqual(spec.flow_id, flow_id)

    def test_every_exception_names_a_reason_and_an_existing_test(self):
        for (flow_id, invariant), (reason, covered_by) in EXCEPTIONS.items():
            with self.subTest(route=flow_id, invariant=invariant):
                self.assertTrue(reason.strip())
                module, class_name, method_name = covered_by.rsplit(".", 2)
                test_class = getattr(importlib.import_module(module), class_name)
                self.assertTrue(issubclass(test_class, unittest.TestCase))
                self.assertTrue(method_name.startswith("test_"))
                self.assertTrue(callable(getattr(test_class, method_name)))


class GenerationChangeTests(unittest.TestCase):
    def test_generation_change_after_first_input_stops_further_input(self):
        for flow_id, spec in ROUTES.items():
            with self.subTest(route=flow_id):
                if (flow_id, "generation_change") in EXCEPTIONS:
                    continue
                with RouteRig(self, spec) as rig:
                    spec.work(rig.runner)
                    def toggle(_index):
                        rig.state.set_flow_enabled(flow_id, False)
                        rig.state.set_flow_enabled(flow_id, True)
                    rig.runner.on_input = toggle
                    reports = rig.once()
                    self.assertEqual(reports[0]["status"], "blocked", reports)
                    run, = rig.runs()
                    self.assertEqual((run.consumed_inputs, run.consumed_actions), spec.generation_counts)
                    self.assertEqual(len(rig.runner.inputs), 1)
                    self.assertEqual(rig.runner.effects, 0)
                    if flow_id == ULTIMATE_FLOW_ID:
                        self.assertEqual(rig.runner.flee_calls, 0)


if __name__ == "__main__":
    unittest.main()
