from __future__ import annotations

import unittest

from tasks.transition_stability import (
    StableTransitionPoller,
    TransitionObservation,
    TransitionStatus,
    poll_stable_transition,
)


class TransitionStabilityTests(unittest.TestCase):
    def test_delayed_successor_is_stable_and_typed_observations_are_retained(self):
        loading = {"state": "loading", "typed": "spinner"}
        ready = {"state": "ready", "typed": "commander"}
        result = poll_stable_transition(
            [
                TransitionObservation(loading, evidence_ref="before"),
                TransitionObservation(ready, evidence_ref="post-1"),
                TransitionObservation(ready, evidence_ref="settled"),
            ],
            stable_polls=2,
        )
        self.assertEqual(result.status, TransitionStatus.STABLE)
        self.assertEqual(result.successor, ready)
        self.assertEqual(result.observations[-1].evidence_ref, "settled")
        self.assertEqual(result.input_count, 0)

    def test_transient_and_timeout_are_distinct(self):
        transient = poll_stable_transition(["loading", "transitioning"], stable_polls=2)
        timeout = poll_stable_transition(["loading", "loading"], stable_polls=3, timeout_polls=2)
        self.assertEqual(transient.status, TransitionStatus.TRANSIENT)
        self.assertEqual(timeout.status, TransitionStatus.TIMEOUT)
        self.assertEqual(timeout.input_count, 0)

    def test_expected_successor_mismatch_is_contradictory(self):
        result = poll_stable_transition(
            ["unexpected", "unexpected"], stable_polls=2, expected_signature="expected"
        )
        self.assertEqual(result.status, TransitionStatus.CONTRADICTORY)

    def test_poller_is_input_free(self):
        result = StableTransitionPoller(stable_polls=2)(["ready", "ready"])
        self.assertEqual(result.status, TransitionStatus.STABLE)
        self.assertEqual(result.input_count, 0)


if __name__ == "__main__":
    unittest.main()
