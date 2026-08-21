from __future__ import annotations

import unittest

from tasks.list_search import (
    ListObservation,
    SearchDirection,
    SearchStatus,
    inspect_list,
)


class ListSearchTests(unittest.TestCase):
    def test_inspects_before_motion_and_stops_on_target(self):
        result = inspect_list(
            [
                ListObservation("frame-1", "cards-1"),
                ListObservation("frame-2", "cards-2", displacement=80, direction=SearchDirection.FORWARD),
                ListObservation("frame-3", "cards-3", target_visible=True, displacement=80, direction=SearchDirection.FORWARD),
            ]
        )
        self.assertEqual(result.status, SearchStatus.TARGET_VISIBLE)
        self.assertTrue(result.inspected_before_motion)
        self.assertFalse(result.dispatch_allowed)
        self.assertEqual(result.input_count, 0)

    def test_no_motion_and_repeated_state_are_fail_closed(self):
        no_motion = inspect_list(
            [
                ListObservation("frame-1", "cards-1"),
                ListObservation("frame-2", "cards-1", displacement=0, direction=SearchDirection.FORWARD),
            ]
        )
        repeated = inspect_list(
            [
                ListObservation("frame-1", "cards-1"),
                ListObservation("frame-2", "cards-2", displacement=10, direction=SearchDirection.FORWARD),
                ListObservation("frame-3", "cards-1", displacement=10, direction=SearchDirection.FORWARD),
            ]
        )
        self.assertEqual(no_motion.status, SearchStatus.NO_MOTION)
        self.assertEqual(repeated.status, SearchStatus.REPEATED_STATE)
        self.assertEqual(no_motion.input_count, 0)

    def test_only_one_direction_reversal_is_allowed(self):
        result = inspect_list(
            [
                ListObservation("f1", "a"),
                ListObservation("f2", "b", displacement=5, direction="forward"),
                ListObservation("f3", "a", displacement=-5, direction="reverse"),
                ListObservation("f4", "b", displacement=5, direction="forward"),
            ]
        )
        self.assertEqual(result.status, SearchStatus.CONTRADICTORY)
        self.assertEqual(result.reversal_count, 1)


if __name__ == "__main__":
    unittest.main()
