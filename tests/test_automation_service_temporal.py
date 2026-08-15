from __future__ import annotations

from dataclasses import replace
import unittest

from automation_service.temporal import (
    CandidateEvidence,
    CaptureProvenance,
    TemporalObservation,
    TemporalPerception,
    TemporalPolicy,
)


def provenance(ordinal: int, captured: float = 10.0, session: str = "session") -> CaptureProvenance:
    digest = f"{ordinal:064x}"
    return CaptureProvenance(
        f"capture-{ordinal}",
        session,
        ordinal,
        captured,
        "profile",
        800,
        1280,
        digest,
        digest[::-1],
    )


class AutomationServiceTemporalTests(unittest.TestCase):
    def test_transient_candidate_requires_consecutive_agreement(self) -> None:
        temporal = TemporalPerception(TemporalPolicy(consecutive_agreement=2, settle_polls=2))
        candidate = CandidateEvidence("home", 0.95, 0.1)
        first = temporal.observe(
            TemporalObservation(provenance(1), candidate, transient=False),
            now_monotonic=10.1,
        )
        second = temporal.observe(
            TemporalObservation(provenance(2), candidate, transient=False),
            now_monotonic=10.2,
        )
        self.assertFalse(first.settled)
        self.assertEqual(first.reason_code, "TRANSIENT_WAIT")
        self.assertTrue(second.settled)
        self.assertEqual(second.reason_code, "SETTLED")

    def test_runner_up_and_stale_evidence_fail_closed(self) -> None:
        temporal = TemporalPerception()
        close = CandidateEvidence("home", 0.85, 0.80)
        decision = temporal.observe(
            TemporalObservation(provenance(1), close, transient=False),
            now_monotonic=10.0,
        )
        self.assertEqual(decision.reason_code, "RUNNER_UP_TOO_CLOSE")
        stale = temporal.observe(
            TemporalObservation(provenance(2, 1.0), CandidateEvidence("home", 0.99, 0.0), transient=False),
            now_monotonic=100.0,
        )
        self.assertEqual(stale.reason_code, "STALE_CAPTURE")

    def test_input_invalidates_prior_authority(self) -> None:
        temporal = TemporalPerception()
        temporal.invalidate_after_input()
        decision = temporal.observe(
            TemporalObservation(provenance(1), CandidateEvidence("home", 0.99), transient=False),
            now_monotonic=10.0,
        )
        self.assertEqual(decision.reason_code, "INVALIDATED_AFTER_INPUT")
        self.assertIsNone(temporal.settled_candidate(now_monotonic=10.0))

    def test_invalid_observations_never_seed_later_settlement(self) -> None:
        candidate = CandidateEvidence("home", 0.99, 0.0)
        temporal = TemporalPerception(TemporalPolicy(consecutive_agreement=2, settle_polls=2))
        self.assertEqual(
            temporal.observe(
                TemporalObservation(provenance(1), candidate, transient=True),
                now_monotonic=10.0,
            ).reason_code,
            "TRANSIENT_OBSERVATION",
        )
        self.assertEqual(
            temporal.observe(
                TemporalObservation(provenance(2), candidate, transient=False),
                now_monotonic=10.0,
            ).agreement_count,
            1,
        )
        self.assertTrue(
            temporal.observe(
                TemporalObservation(provenance(3), candidate, transient=False),
                now_monotonic=10.0,
            ).settled
        )

    def test_session_order_digest_and_negative_evidence_gates(self) -> None:
        candidate = CandidateEvidence("home", 0.99, 0.0)
        temporal = TemporalPerception()
        first = provenance(1)
        temporal.observe(TemporalObservation(first, candidate, transient=False), now_monotonic=10.0)
        duplicate = replace(
            provenance(2),
            capture_id=first.capture_id,
            transport_sha256=first.transport_sha256,
            semantic_sha256=first.semantic_sha256,
        )
        self.assertEqual(
            temporal.observe(
                TemporalObservation(duplicate, candidate, transient=False),
                now_monotonic=10.0,
            ).reason_code,
            "DUPLICATE_CAPTURE",
        )
        temporal = TemporalPerception()
        self.assertEqual(
            temporal.observe(
                TemporalObservation(provenance(1, session="one"), candidate, transient=False),
                now_monotonic=10.0,
            ).agreement_count,
            1,
        )
        self.assertEqual(
            temporal.observe(
                TemporalObservation(provenance(1, session="two"), candidate, transient=False),
                now_monotonic=10.0,
            ).reason_code,
            "CROSS_SESSION",
        )
        self.assertEqual(
            temporal.observe(
                TemporalObservation(
                    provenance(2),
                    CandidateEvidence("home", 0.99, 0.0, negative_evidence=("overlay",)),
                    transient=False,
                ),
                now_monotonic=10.0,
            ).reason_code,
            "NEGATIVE_EVIDENCE",
        )

    def test_settled_candidate_requires_current_freshness(self) -> None:
        candidate = CandidateEvidence("home", 0.99, 0.0)
        temporal = TemporalPerception(
            TemporalPolicy(
                consecutive_agreement=2,
                settle_polls=2,
                max_age_seconds=5.0,
            )
        )
        temporal.observe(
            TemporalObservation(provenance(1, captured=10.0), candidate, transient=False),
            now_monotonic=10.1,
        )
        temporal.observe(
            TemporalObservation(provenance(2, captured=10.2), candidate, transient=False),
            now_monotonic=10.3,
        )
        self.assertEqual(
            temporal.settled_candidate(now_monotonic=10.4),
            candidate,
        )
        self.assertIsNone(temporal.settled_candidate(now_monotonic=20.0))


if __name__ == "__main__":
    unittest.main()

