"""Behavioral boundaries for the static-debt ratchet, without starting analyzers."""
from __future__ import annotations

import unittest

from scripts.check_static import budget_changes


class StaticBudgetTests(unittest.TestCase):
    def test_new_file_rule_and_analyzer_cannot_spend_an_existing_allowance(self) -> None:
        allowed = {"ruff": {"scripts/old.py": {"F401": 1}}}
        current = {
            "ruff": {
                "scripts/old.py": {"F401": 2, "F841": 1},
                "scripts/new.py": {"F401": 1},
            },
            "vulture": {"scripts/unused.py": {"function:60": 1}},
        }
        increases, reductions = budget_changes(current, allowed)
        self.assertEqual(increases, {
            ("ruff", "scripts/old.py", "F401"): (1, 2),
            ("ruff", "scripts/old.py", "F841"): (0, 1),
            ("ruff", "scripts/new.py", "F401"): (0, 1),
            ("vulture", "scripts/unused.py", "function:60"): (0, 1),
        })
        self.assertEqual(reductions, {})

    def test_debt_reductions_include_removed_rules_and_entire_type_exceptions(self) -> None:
        allowed = {
            "mypy": {
                "safe_action_core/debt.py": {"arg-type": 4, "return-value": 1},
                "safe_action_core/now_clean.py": {"arg-type": 2},
            },
        }
        current = {"mypy": {"safe_action_core/debt.py": {"arg-type": 1}}}
        increases, reductions = budget_changes(current, allowed)
        self.assertEqual(increases, {})
        self.assertEqual(reductions, {
            ("mypy", "safe_action_core/debt.py", "arg-type"): (4, 1),
            ("mypy", "safe_action_core/debt.py", "return-value"): (1, 0),
            ("mypy", "safe_action_core/now_clean.py", "arg-type"): (2, 0),
        })

    def test_equal_totals_cannot_move_debt_between_files_or_analyzers(self) -> None:
        allowed = {"ruff": {"scripts/original.py": {"F401": 2}}}
        for tool_name, filename, rule in (
            ("ruff", "scripts/replacement.py", "F401"),
            ("vulture", "scripts/original.py", "function:60"),
        ):
            with self.subTest(tool=tool_name, path=filename):
                increases, reductions = budget_changes(
                    {tool_name: {filename: {rule: 2}}}, allowed,
                )
                self.assertEqual(increases, {(tool_name, filename, rule): (0, 2)})
                self.assertEqual(reductions, {("ruff", "scripts/original.py", "F401"): (2, 0)})


if __name__ == "__main__":
    unittest.main()
