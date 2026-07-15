import unittest

from tasks.daily_quest_state import (
    DailyObjectiveRow,
    DailyObjectiveState,
    claim_requires_separate_transaction,
    classify_daily_objective,
    validate_daily_row_order,
)


class DailyQuestStateTests(unittest.TestCase):
    def test_completed_unclaimed_row_is_claim_ready(self):
        row = DailyObjectiveRow("bioenhancer_research", 1, 1, "Claim")
        self.assertEqual(
            classify_daily_objective(row),
            DailyObjectiveState.READY_TO_CLAIM,
        )

    def test_incomplete_go_is_actionable_but_go_is_optional(self):
        self.assertEqual(
            classify_daily_objective(DailyObjectiveRow("a", 0, 1, "Go")),
            DailyObjectiveState.INCOMPLETE,
        )
        self.assertEqual(
            classify_daily_objective(DailyObjectiveRow("b", 0, 1)),
            DailyObjectiveState.INCOMPLETE,
        )

    def test_gated_row_is_distinct(self):
        row = DailyObjectiveRow("a", 0, 1, gated=True)
        self.assertEqual(classify_daily_objective(row), DailyObjectiveState.GATED)

    def test_claim_ready_rows_sort_before_incomplete_and_claimed_rows(self):
        rows = [
            DailyObjectiveRow("ready", 1, 1, "Claim"),
            DailyObjectiveRow("incomplete", 0, 1, "Go"),
            DailyObjectiveRow("gated", 0, 1, gated=True),
            DailyObjectiveRow("claimed", 1, 1, "Claimed"),
        ]
        self.assertTrue(validate_daily_row_order(rows))
        self.assertFalse(validate_daily_row_order(list(reversed(rows))))

    def test_completion_alone_cannot_be_claimed_or_inferred(self):
        with self.assertRaises(ValueError):
            classify_daily_objective(DailyObjectiveRow("a", 1, 1))

    def test_claim_requires_a_separate_transaction(self):
        incomplete = DailyObjectiveRow("a", 0, 1, "Go")
        ready = DailyObjectiveRow("a", 1, 1, "Claim")
        claimed = DailyObjectiveRow("a", 1, 1, "Claimed")
        self.assertFalse(claim_requires_separate_transaction(incomplete, ready))
        self.assertTrue(claim_requires_separate_transaction(ready, claimed))

    def test_viewport_absence_has_no_semantic_state(self):
        self.assertEqual(
            classify_daily_objective(DailyObjectiveRow("outside_viewport", 0, 1)),
            DailyObjectiveState.INCOMPLETE,
        )

    def test_row_position_does_not_override_row_control(self):
        row = DailyObjectiveRow("claimed", 1, 1, "Claimed")
        self.assertEqual(classify_daily_objective(row), DailyObjectiveState.CLAIMED)


if __name__ == "__main__":
    unittest.main()
