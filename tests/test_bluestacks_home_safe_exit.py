"""Offline tests for BlueStacks-only Home safe-exit binder."""

from __future__ import annotations

from dataclasses import replace
import inspect
import json
import math
from pathlib import Path
from types import MappingProxyType
import unittest
import numpy as np

from tasks.bluestacks_home_safe_exit import (
    BLISS_REJECTED_PLATFORM,
    BLISS_REJECTED_PROFILE_ID,
    BLUESTACKS_SAFE_EXIT_HEIGHT,
    BLUESTACKS_SAFE_EXIT_PLATFORM,
    BLUESTACKS_SAFE_EXIT_PROFILE_ID,
    BLUESTACKS_SAFE_EXIT_WIDTH,
    CONSERVATIVE_GEOMETRY_POLICY,
    PROJECTION_PROVENANCE_HONESTY,
    SCHEMA_NAME,
    SCHEMA_VERSION,
    BlueStacksSafeExitProfile,
    BoundSafeExitCandidate,
    CategoryCoverageProof,
    ExclusionCategory,
    ExclusionInventory,
    ExclusionRegion,
    ProjectedRecoverySearchEnvelope,
    REQUIRED_EXCLUSION_CATEGORIES,
    SafeExitActionability,
    SafeExitBindingError,
    SafeExitBindingResult,
    SafeExitBindingStatus,
    SafeExitCandidateProposal,
    assert_safe_exit_does_not_authorize,
    bind_bluestacks_home_safe_exit,
    bluestacks_safe_exit_profile,
    projected_recovery_zone_as_search_envelope,
    safe_exit_authorize_dispatch,
    safe_exit_evidence_snapshot,
)
from tasks.home_atlas_planner import (
    PredictedRecoverySearchZone,
    assert_predicted_recovery_search_zone_non_authorizing,
)
from tasks.home_atlas_vision import BLUESTACKS_SAFE_INTERACTION_BOX
from tasks.perception_bundle import NativeFrameIdentity


ROOT = Path(__file__).resolve().parents[1]
REPLAY_MANIFEST = ROOT / "tests" / "fixtures" / "native_frame_replay_manifest.json"
SAFE = BLUESTACKS_SAFE_INTERACTION_BOX


def _load_replay_fixture_identity(ordinal: int = 1) -> NativeFrameIdentity:
    payload = json.loads(REPLAY_MANIFEST.read_text(encoding="utf-8"))
    source = next(item for item in payload["sources"] if item["ordinal"] == ordinal)
    digest = source["source_sha256"]
    return NativeFrameIdentity(
        capture_kind="fixture",
        runtime_session_id=payload["fixture_session_id"],
        capture_ordinal=int(source["ordinal"]),
        capture_completed_monotonic=float(source["capture_completed_monotonic"]),
        transport_sha256=digest,
        semantic_sha256=digest,
        runtime_profile_id=payload["runtime_profile_id"],
        width=int(source["width"]),
        height=int(source["height"]),
        label=str(source["label"]),
    )


def _region(
    identity: NativeFrameIdentity,
    category: ExclusionCategory,
    region_id: str,
    box: tuple[int, int, int, int],
) -> ExclusionRegion:
    return ExclusionRegion(
        source_frame=identity,
        category=category,
        region_id=region_id,
        box=box,
    )


def _full_inventory(
    identity: NativeFrameIdentity,
    *,
    hud: tuple[ExclusionRegion, ...] | None = None,
    buildings: tuple[ExclusionRegion, ...] | None = None,
    radial: tuple[ExclusionRegion, ...] | None = None,
    semantic: tuple[ExclusionRegion, ...] | None = None,
    interactive: tuple[ExclusionRegion, ...] | None = None,
    empty: frozenset[ExclusionCategory] | None = None,
) -> ExclusionInventory:
    empty = empty or frozenset()
    defaults = {
        ExclusionCategory.HUD: hud
        if hud is not None
        else (
            _region(identity, ExclusionCategory.HUD, "hud-top", (0, 0, 800, 150)),
            _region(identity, ExclusionCategory.HUD, "hud-left", (0, 150, 138, 1020)),
            _region(identity, ExclusionCategory.HUD, "hud-right", (650, 150, 800, 1020)),
            _region(identity, ExclusionCategory.HUD, "hud-bottom", (0, 1020, 800, 1280)),
        ),
        ExclusionCategory.BUILDINGS: buildings
        if buildings is not None
        else (_region(identity, ExclusionCategory.BUILDINGS, "building-a", (300, 400, 440, 520)),),
        ExclusionCategory.RADIAL_CONTROLS: radial
        if radial is not None
        else (_region(identity, ExclusionCategory.RADIAL_CONTROLS, "radial-close", (360, 560, 420, 620)),),
        ExclusionCategory.SEMANTIC_TARGETS: semantic
        if semantic is not None
        else (_region(identity, ExclusionCategory.SEMANTIC_TARGETS, "semantic-label", (310, 380, 430, 410)),),
        ExclusionCategory.KNOWN_INTERACTIVE_REGIONS: interactive
        if interactive is not None
        else (
            _region(
                identity,
                ExclusionCategory.KNOWN_INTERACTIVE_REGIONS,
                "interactive-dock",
                (200, 900, 600, 980),
            ),
        ),
    }
    coverage = []
    for category in sorted(REQUIRED_EXCLUSION_CATEGORIES, key=lambda item: item.value):
        regions = defaults[category]
        if category in empty:
            coverage.append(
                CategoryCoverageProof(
                    source_frame=identity,
                    category=category,
                    regions=(),
                    observed_empty=True,
                )
            )
        else:
            coverage.append(
                CategoryCoverageProof(
                    source_frame=identity,
                    category=category,
                    regions=regions,
                    observed_empty=False,
                )
            )
    return ExclusionInventory(source_frame=identity, coverage=tuple(coverage))


def _proposal(
    identity: NativeFrameIdentity,
    candidate_id: str,
    box: tuple[int, int, int, int],
) -> SafeExitCandidateProposal:
    return SafeExitCandidateProposal(
        source_frame=identity,
        candidate_id=candidate_id,
        box=box,
    )


class BlueStacksHomeSafeExitTests(unittest.TestCase):
    def test_valid_binding_with_full_exclusion_categories(self) -> None:
        identity = _load_replay_fixture_identity(1)
        inventory = _full_inventory(identity)
        # Clear open space inside safe region, away from building/radial/HUD.
        result = bind_bluestacks_home_safe_exit(
            source_frame=identity,
            permitted_safe_space=SAFE,
            exclusion_inventory=inventory,
            proposed_candidates=(
                _proposal(identity, "exit-a", (500, 250, 540, 290)),
            ),
        )
        self.assertEqual(result.status, SafeExitBindingStatus.BOUND)
        self.assertEqual(result.reason_code, "SAFE_EXIT_CANDIDATE_BOUND")
        self.assertIsNotNone(result.candidate)
        assert result.candidate is not None
        self.assertEqual(result.candidate.box, (500, 250, 540, 290))
        self.assertEqual(result.geometry_policy, CONSERVATIVE_GEOMETRY_POLICY)
        self.assertFalse(result.authorize_dispatch)
        self.assertFalse(safe_exit_authorize_dispatch(result))
        assert_safe_exit_does_not_authorize(result)
        covered = {entry.category for entry in inventory.coverage}
        self.assertEqual(covered, REQUIRED_EXCLUSION_CATEGORIES)

    def test_current_frame_identity_association(self) -> None:
        identity = _load_replay_fixture_identity(1)
        inventory = _full_inventory(identity)
        result = bind_bluestacks_home_safe_exit(
            source_frame=identity,
            permitted_safe_space=SAFE,
            exclusion_inventory=inventory,
            proposed_candidates=(_proposal(identity, "exit-a", (500, 250, 540, 290)),),
        )
        self.assertTrue(result.source_frame.same_capture_event(identity))
        assert result.candidate is not None
        self.assertTrue(result.candidate.source_frame.same_capture_event(identity))

    def test_complete_containment_required(self) -> None:
        identity = _load_replay_fixture_identity(1)
        inventory = _full_inventory(identity)
        # Extends outside permitted safe space.
        result = bind_bluestacks_home_safe_exit(
            source_frame=identity,
            permitted_safe_space=SAFE,
            exclusion_inventory=inventory,
            proposed_candidates=(_proposal(identity, "outside", (140, 250, 180, 290)),),
        )
        self.assertEqual(result.status, SafeExitBindingStatus.UNAVAILABLE)
        self.assertEqual(result.reason_code, "NO_VALID_SAFE_EXIT_CANDIDATE")
        self.assertEqual(result.rejected_candidates[0][1], "PARTIAL_SAFE_SPACE_OVERLAP")

    def test_each_exclusion_category_blocks_overlap(self) -> None:
        identity = _load_replay_fixture_identity(1)
        # Place one in-safe-space blocker per category so containment is not the failure mode.
        blockers = {
            ExclusionCategory.HUD: _region(
                identity, ExclusionCategory.HUD, "hud-intrusion", (200, 200, 280, 260)
            ),
            ExclusionCategory.BUILDINGS: _region(
                identity, ExclusionCategory.BUILDINGS, "building-block", (200, 200, 280, 260)
            ),
            ExclusionCategory.RADIAL_CONTROLS: _region(
                identity, ExclusionCategory.RADIAL_CONTROLS, "radial-block", (200, 200, 280, 260)
            ),
            ExclusionCategory.SEMANTIC_TARGETS: _region(
                identity, ExclusionCategory.SEMANTIC_TARGETS, "semantic-block", (200, 200, 280, 260)
            ),
            ExclusionCategory.KNOWN_INTERACTIVE_REGIONS: _region(
                identity,
                ExclusionCategory.KNOWN_INTERACTIVE_REGIONS,
                "interactive-block",
                (200, 200, 280, 260),
            ),
        }
        hit = (220, 220, 260, 250)
        for category, blocker in blockers.items():
            with self.subTest(category=category.value):
                empty = frozenset(REQUIRED_EXCLUSION_CATEGORIES - {category})
                inventory = _full_inventory(
                    identity,
                    empty=empty,
                    hud=(blocker,) if category is ExclusionCategory.HUD else None,
                    buildings=(blocker,) if category is ExclusionCategory.BUILDINGS else None,
                    radial=(blocker,) if category is ExclusionCategory.RADIAL_CONTROLS else None,
                    semantic=(blocker,) if category is ExclusionCategory.SEMANTIC_TARGETS else None,
                    interactive=(blocker,)
                    if category is ExclusionCategory.KNOWN_INTERACTIVE_REGIONS
                    else None,
                )
                result = bind_bluestacks_home_safe_exit(
                    source_frame=identity,
                    permitted_safe_space=SAFE,
                    exclusion_inventory=inventory,
                    proposed_candidates=(_proposal(identity, f"hit-{category.value}", hit),),
                )
                self.assertEqual(result.status, SafeExitBindingStatus.UNAVAILABLE)
                self.assertIn(blocker.region_id, result.rejected_candidates[0][1])

    def test_edge_touch_with_exclusion_rejected(self) -> None:
        identity = _load_replay_fixture_identity(1)
        inventory = _full_inventory(identity)
        # Touches building-a right edge at x=440 without interior overlap.
        result = bind_bluestacks_home_safe_exit(
            source_frame=identity,
            permitted_safe_space=SAFE,
            exclusion_inventory=inventory,
            proposed_candidates=(_proposal(identity, "touch", (440, 430, 480, 470)),),
        )
        self.assertEqual(result.status, SafeExitBindingStatus.UNAVAILABLE)
        self.assertIn("EDGE_TOUCH_OR_OVERLAP", result.rejected_candidates[0][1])

    def test_partial_box_overlap_rejected(self) -> None:
        identity = _load_replay_fixture_identity(1)
        inventory = _full_inventory(identity)
        # Partially overlaps building-a.
        result = bind_bluestacks_home_safe_exit(
            source_frame=identity,
            permitted_safe_space=SAFE,
            exclusion_inventory=inventory,
            proposed_candidates=(_proposal(identity, "partial", (420, 480, 460, 540)),),
        )
        self.assertEqual(result.status, SafeExitBindingStatus.UNAVAILABLE)
        self.assertIn("PARTIAL_EXCLUSION_OVERLAP", result.rejected_candidates[0][1])

    def test_malformed_nan_inf_bool_geometry_rejected(self) -> None:
        identity = _load_replay_fixture_identity(1)
        bad_boxes = (
            (True, 1, 2, 3),
            (1.5, 2, 3, 4),
            (1, 2, float("nan"), 4),
            (1, 2, float("inf"), 4),
            (10, 10, 10, 20),
            (0, 0, 800),
        )
        for box in bad_boxes:
            with self.subTest(box=box):
                with self.assertRaises(SafeExitBindingError) as raised:
                    SafeExitCandidateProposal(
                        source_frame=identity,
                        candidate_id="bad",
                        box=box,  # type: ignore[arg-type]
                    )
                self.assertIn(
                    raised.exception.reason_code,
                    {
                        "INVALID_GEOMETRY",
                        "INVALID_BOX",
                        "DEGENERATE_BOX",
                    },
                )

    def test_missing_category_proof_fails_closed(self) -> None:
        identity = _load_replay_fixture_identity(1)
        with self.assertRaises(SafeExitBindingError) as raised:
            CategoryCoverageProof(
                source_frame=identity,
                category=ExclusionCategory.BUILDINGS,
                regions=(),
                observed_empty=False,
            )
        self.assertEqual(raised.exception.reason_code, "MISSING_CATEGORY_PROOF")

        partial = (
            CategoryCoverageProof(
                source_frame=identity,
                category=ExclusionCategory.HUD,
                regions=(_region(identity, ExclusionCategory.HUD, "hud-top", (0, 0, 800, 150)),),
                observed_empty=False,
            ),
        )
        with self.assertRaises(SafeExitBindingError) as raised:
            ExclusionInventory(source_frame=identity, coverage=partial)
        self.assertEqual(raised.exception.reason_code, "MISSING_CATEGORY_PROOF")

    def test_observed_empty_category_is_explicit(self) -> None:
        identity = _load_replay_fixture_identity(1)
        inventory = _full_inventory(
            identity,
            empty=frozenset({ExclusionCategory.SEMANTIC_TARGETS}),
        )
        proof = next(
            entry
            for entry in inventory.coverage
            if entry.category is ExclusionCategory.SEMANTIC_TARGETS
        )
        self.assertTrue(proof.observed_empty)
        self.assertEqual(proof.regions, ())
        result = bind_bluestacks_home_safe_exit(
            source_frame=identity,
            permitted_safe_space=SAFE,
            exclusion_inventory=inventory,
            proposed_candidates=(_proposal(identity, "exit-a", (500, 250, 540, 290)),),
        )
        self.assertEqual(result.status, SafeExitBindingStatus.BOUND)

    def test_duplicate_ambiguous_candidates_fail_closed(self) -> None:
        identity = _load_replay_fixture_identity(1)
        inventory = _full_inventory(identity)
        box = (500, 250, 540, 290)
        result = bind_bluestacks_home_safe_exit(
            source_frame=identity,
            permitted_safe_space=SAFE,
            exclusion_inventory=inventory,
            proposed_candidates=(
                _proposal(identity, "exit-a", box),
                _proposal(identity, "exit-b", box),
            ),
        )
        self.assertEqual(result.status, SafeExitBindingStatus.UNAVAILABLE)
        self.assertEqual(
            result.reason_code, "AMBIGUOUS_MULTIPLE_VALID_CANDIDATES"
        )

        dup_id = bind_bluestacks_home_safe_exit(
            source_frame=identity,
            permitted_safe_space=SAFE,
            exclusion_inventory=inventory,
            proposed_candidates=(
                _proposal(identity, "exit-a", box),
                _proposal(identity, "exit-a", (510, 260, 550, 300)),
            ),
        )
        self.assertEqual(dup_id.reason_code, "DUPLICATE_CANDIDATE_ID")

    def test_stale_cross_capture_and_digest_only_rejected(self) -> None:
        first = _load_replay_fixture_identity(1)
        second = _load_replay_fixture_identity(2)
        inventory = _full_inventory(first)
        with self.assertRaises(SafeExitBindingError) as raised:
            bind_bluestacks_home_safe_exit(
                source_frame=first,
                permitted_safe_space=SAFE,
                exclusion_inventory=inventory,
                proposed_candidates=(_proposal(second, "cross", (500, 250, 540, 290)),),
            )
        self.assertIn(
            raised.exception.reason_code,
            {"CAPTURE_EVENT_MISMATCH", "DIGEST_ONLY_JOIN_REJECTED"},
        )

        digest_only = replace(
            first,
            capture_ordinal=99,
            capture_completed_monotonic=first.capture_completed_monotonic + 1.0,
            runtime_session_id="other-session",
        )
        with self.assertRaises(SafeExitBindingError) as raised:
            ExclusionRegion(
                source_frame=digest_only,
                category=ExclusionCategory.HUD,
                region_id="stale-hud",
                box=(0, 0, 800, 150),
            )
            # Force inventory association against first capture.
            CategoryCoverageProof(
                source_frame=first,
                category=ExclusionCategory.HUD,
                regions=(
                    ExclusionRegion(
                        source_frame=digest_only,
                        category=ExclusionCategory.HUD,
                        region_id="stale-hud",
                        box=(0, 0, 800, 150),
                    ),
                ),
                observed_empty=False,
            )
        self.assertEqual(raised.exception.reason_code, "DIGEST_ONLY_JOIN_REJECTED")

    def test_wrong_bluestacks_profile_geometry_platform_rejected(self) -> None:
        identity = _load_replay_fixture_identity(1)
        wrong_profile = replace(identity, runtime_profile_id="pns-bluestacks-other-v1")
        with self.assertRaises(SafeExitBindingError) as raised:
            _proposal(wrong_profile, "bad", (500, 250, 540, 290))
        self.assertEqual(raised.exception.reason_code, "WRONG_BLUESTACKS_PROFILE")

        wrong_geometry = replace(identity, width=720, height=1280)
        with self.assertRaises(SafeExitBindingError) as raised:
            _proposal(wrong_geometry, "bad", (500, 250, 540, 290))
        self.assertEqual(raised.exception.reason_code, "WRONG_BLUESTACKS_GEOMETRY")

        with self.assertRaises(SafeExitBindingError):
            replace(
                bluestacks_safe_exit_profile(),
                platform="Some Other Emulator",
            )

    def test_bliss_rejection(self) -> None:
        identity = _load_replay_fixture_identity(1)
        bliss = replace(
            identity,
            runtime_profile_id=BLISS_REJECTED_PROFILE_ID,
            label=BLISS_REJECTED_PLATFORM,
        )
        with self.assertRaises(SafeExitBindingError) as raised:
            _proposal(bliss, "bliss", (500, 250, 540, 290))
        self.assertEqual(raised.exception.reason_code, "BLISS_PROFILE_REJECTED")
        self.assertNotEqual(BLISS_REJECTED_PROFILE_ID, BLUESTACKS_SAFE_EXIT_PROFILE_ID)
        self.assertNotEqual(BLISS_REJECTED_PLATFORM, BLUESTACKS_SAFE_EXIT_PLATFORM)

    def test_projection_non_authorization(self) -> None:
        identity = _load_replay_fixture_identity(1)
        inventory = _full_inventory(identity)
        envelope = ProjectedRecoverySearchEnvelope(
            source_frame=identity,
            available=True,
            zone_box=(220, 250, 575, 650),
            executable_recovery_coordinate=None,
        )
        self.assertIsNone(envelope.executable_recovery_coordinate)
        self.assertFalse(envelope.derived_directly_from_projection)

        # Using the envelope zone itself as the candidate ROI is rejected.
        as_roi = bind_bluestacks_home_safe_exit(
            source_frame=identity,
            permitted_safe_space=SAFE,
            exclusion_inventory=inventory,
            proposed_candidates=(_proposal(identity, "zone-as-roi", envelope.zone_box),),
            search_envelope=envelope,
        )
        self.assertEqual(as_roi.status, SafeExitBindingStatus.UNAVAILABLE)
        self.assertEqual(
            as_roi.rejected_candidates[0][1],
            "PROJECTION_ZONE_MUST_NOT_BECOME_CANDIDATE_ROI",
        )

        ok = bind_bluestacks_home_safe_exit(
            source_frame=identity,
            permitted_safe_space=SAFE,
            exclusion_inventory=inventory,
            proposed_candidates=(_proposal(identity, "exit-a", (500, 250, 540, 290)),),
            search_envelope=envelope,
        )
        self.assertEqual(ok.status, SafeExitBindingStatus.BOUND)
        assert ok.candidate is not None
        self.assertNotEqual(ok.candidate.box, envelope.zone_box)
        self.assertTrue(ok.candidate.search_envelope_applied)
        self.assertIn(
            "planner_projected_recovery_search_zone_is_non_authorizing_provenance_only",
            ok.projection_honesty,
        )

        planner_zone = PredictedRecoverySearchZone(
            available=True,
            clearance_px=25.0,
            zone_box=(220, 250, 575, 650),
            executable_recovery_coordinate=None,
        )
        assert_predicted_recovery_search_zone_non_authorizing(planner_zone)
        adapted = projected_recovery_zone_as_search_envelope(
            planner_zone, source_frame=identity
        )
        self.assertIsNotNone(adapted)
        assert adapted is not None
        self.assertIsNone(adapted.executable_recovery_coordinate)
        self.assertFalse(adapted.derived_directly_from_projection)

        with self.assertRaises(SafeExitBindingError):
            ProjectedRecoverySearchEnvelope(
                source_frame=identity,
                available=True,
                zone_box=(220, 250, 575, 650),
                executable_recovery_coordinate=(400, 300),  # type: ignore[arg-type]
            )

    def test_search_envelope_requires_same_complete_capture(self) -> None:
        first = _load_replay_fixture_identity(1)
        second = _load_replay_fixture_identity(2)
        inventory = _full_inventory(first)
        same_capture = ProjectedRecoverySearchEnvelope(
            source_frame=first,
            available=True,
            zone_box=(220, 250, 575, 650),
        )
        result = bind_bluestacks_home_safe_exit(
            source_frame=first,
            permitted_safe_space=SAFE,
            exclusion_inventory=inventory,
            proposed_candidates=(
                _proposal(first, "same-capture", (500, 250, 540, 290)),
            ),
            search_envelope=same_capture,
        )
        self.assertEqual(result.status, SafeExitBindingStatus.BOUND)
        self.assertTrue(
            result.search_envelope.source_frame.same_capture_event(first)
        )

        cross_capture = ProjectedRecoverySearchEnvelope(
            source_frame=second,
            available=True,
            zone_box=(220, 250, 575, 650),
        )
        with self.assertRaises(SafeExitBindingError) as raised:
            bind_bluestacks_home_safe_exit(
                source_frame=first,
                permitted_safe_space=SAFE,
                exclusion_inventory=inventory,
                proposed_candidates=(
                    _proposal(first, "cross-capture", (500, 250, 540, 290)),
                ),
                search_envelope=cross_capture,
            )
        self.assertEqual(raised.exception.reason_code, "CAPTURE_EVENT_MISMATCH")

        same_digest_different_event = replace(
            first,
            runtime_session_id="different-event",
            capture_ordinal=99,
            capture_completed_monotonic=first.capture_completed_monotonic + 1.0,
        )
        digest_only = ProjectedRecoverySearchEnvelope(
            source_frame=same_digest_different_event,
            available=True,
            zone_box=(220, 250, 575, 650),
        )
        with self.assertRaises(SafeExitBindingError) as raised:
            bind_bluestacks_home_safe_exit(
                source_frame=first,
                permitted_safe_space=SAFE,
                exclusion_inventory=inventory,
                proposed_candidates=(
                    _proposal(first, "digest-only", (500, 250, 540, 290)),
                ),
                search_envelope=digest_only,
            )
        self.assertEqual(raised.exception.reason_code, "DIGEST_ONLY_JOIN_REJECTED")

    def test_planner_adapter_requires_explicit_identity_and_exact_geometry(self) -> None:
        identity = _load_replay_fixture_identity(1)
        second = _load_replay_fixture_identity(2)
        inventory = _full_inventory(identity)
        zone = PredictedRecoverySearchZone(
            True, 25.0, (220, 250, 575, 650), None
        )
        envelope = projected_recovery_zone_as_search_envelope(
            zone, source_frame=identity
        )
        self.assertIsNotNone(envelope)
        assert envelope is not None
        self.assertTrue(envelope.source_frame.same_capture_event(identity))
        bound = bind_bluestacks_home_safe_exit(
            source_frame=identity,
            permitted_safe_space=SAFE,
            exclusion_inventory=inventory,
            proposed_candidates=(
                _proposal(identity, "adapted-same", (500, 250, 540, 290)),
            ),
            search_envelope=envelope,
        )
        self.assertEqual(bound.status, SafeExitBindingStatus.BOUND)

        cross_envelope = projected_recovery_zone_as_search_envelope(
            zone, source_frame=second
        )
        with self.assertRaises(SafeExitBindingError) as raised:
            bind_bluestacks_home_safe_exit(
                source_frame=identity,
                permitted_safe_space=SAFE,
                exclusion_inventory=inventory,
                proposed_candidates=(
                    _proposal(identity, "adapted-cross", (500, 250, 540, 290)),
                ),
                search_envelope=cross_envelope,
            )
        self.assertEqual(raised.exception.reason_code, "CAPTURE_EVENT_MISMATCH")

        same_digest_different_event = replace(
            identity,
            runtime_session_id="adapter-digest-only",
            capture_ordinal=101,
            capture_completed_monotonic=identity.capture_completed_monotonic + 2.0,
        )
        digest_envelope = projected_recovery_zone_as_search_envelope(
            zone, source_frame=same_digest_different_event
        )
        with self.assertRaises(SafeExitBindingError) as raised:
            bind_bluestacks_home_safe_exit(
                source_frame=identity,
                permitted_safe_space=SAFE,
                exclusion_inventory=inventory,
                proposed_candidates=(
                    _proposal(identity, "adapted-digest", (500, 250, 540, 290)),
                ),
                search_envelope=digest_envelope,
            )
        self.assertEqual(raised.exception.reason_code, "DIGEST_ONLY_JOIN_REJECTED")

        invalid_boxes = (
            (220.9, 250, 575, 650),
            (220.0, 250, 575, 650),
            (np.int64(220), 250, 575, 650),
            ("220", 250, 575, 650),
            (True, 250, 575, 650),
            (float("nan"), 250, 575, 650),
            (float("inf"), 250, 575, 650),
        )
        for box in invalid_boxes:
            with self.subTest(box=box):
                with self.assertRaises(SafeExitBindingError) as raised:
                    projected_recovery_zone_as_search_envelope(
                        PredictedRecoverySearchZone(
                            True, 25.0, box, None  # type: ignore[arg-type]
                        ),
                        source_frame=identity,
                    )
                self.assertEqual(raised.exception.reason_code, "INVALID_GEOMETRY")

        with self.assertRaises(TypeError):
            projected_recovery_zone_as_search_envelope(zone)  # type: ignore[call-arg]

    def test_public_records_reject_malformed_direct_construction(self) -> None:
        identity = _load_replay_fixture_identity(1)
        inventory = _full_inventory(identity)
        valid = bind_bluestacks_home_safe_exit(
            source_frame=identity,
            permitted_safe_space=SAFE,
            exclusion_inventory=inventory,
            proposed_candidates=(
                _proposal(identity, "exit-a", (500, 250, 540, 290)),
            ),
        )
        assert valid.candidate is not None

        bad_profiles = (
            {"width": True},
            {"width": 800.0},
            {"height": np.int64(1280)},
            {"platform": 7},
            {"profile_id": " wrong "},
            {"geometry_policy": 1},
        )
        for changes in bad_profiles:
            with self.subTest(profile=changes):
                values = {
                    "platform": BLUESTACKS_SAFE_EXIT_PLATFORM,
                    "profile_id": BLUESTACKS_SAFE_EXIT_PROFILE_ID,
                    "width": 800,
                    "height": 1280,
                    "geometry_policy": CONSERVATIVE_GEOMETRY_POLICY,
                }
                values.update(changes)
                with self.assertRaises(SafeExitBindingError):
                    BlueStacksSafeExitProfile(**values)  # type: ignore[arg-type]

        with self.assertRaises(SafeExitBindingError):
            ProjectedRecoverySearchEnvelope(
                source_frame=identity,
                available=1,  # type: ignore[arg-type]
                zone_box=(220, 250, 575, 650),
            )
        with self.assertRaises(SafeExitBindingError):
            ProjectedRecoverySearchEnvelope(
                source_frame=identity,
                available=True,
                zone_box=(220, 250, 575, 650),
                provenance=("projection_does_not_authorize_safe_exit_input",),
            )
        with self.assertRaises(SafeExitBindingError):
            replace(valid.candidate, authorize_dispatch=0)  # type: ignore[arg-type]
        with self.assertRaises(SafeExitBindingError):
            replace(valid.candidate, search_envelope_applied=1)  # type: ignore[arg-type]
        with self.assertRaises(SafeExitBindingError):
            replace(valid.candidate, cleared_exclusion_ids=("z:id", "a:id"))
        with self.assertRaises(SafeExitBindingError):
            replace(valid.candidate, box=(790, 1200, 810, 1250))
        with self.assertRaises(SafeExitBindingError):
            replace(valid, status="bound")  # type: ignore[arg-type]
        with self.assertRaises(SafeExitBindingError):
            replace(valid, reason_code=" ARBITRARY ")
        with self.assertRaises(SafeExitBindingError):
            replace(valid, actionability="candidate")  # type: ignore[arg-type]
        with self.assertRaises(SafeExitBindingError):
            replace(valid, authorize_dispatch=0)  # type: ignore[arg-type]
        with self.assertRaises(SafeExitBindingError):
            replace(valid, projection_honesty=tuple(reversed(PROJECTION_PROVENANCE_HONESTY)))
        with self.assertRaises(SafeExitBindingError):
            replace(valid, metadata={"count": 1})  # type: ignore[dict-item]
        with self.assertRaises(SafeExitBindingError):
            replace(valid, rejected_candidates=[("x", "reason")])  # type: ignore[arg-type]
        with self.assertRaises(SafeExitBindingError):
            replace(valid, rejected_candidates=(("x", "arbitrary-reason"),))

    def test_result_rejects_cross_capture_nested_records(self) -> None:
        first = _load_replay_fixture_identity(1)
        second = _load_replay_fixture_identity(2)
        inventory = _full_inventory(first)
        valid = bind_bluestacks_home_safe_exit(
            source_frame=first,
            permitted_safe_space=SAFE,
            exclusion_inventory=inventory,
            proposed_candidates=(
                _proposal(first, "exit-a", (500, 250, 540, 290)),
            ),
        )
        assert valid.candidate is not None
        with self.assertRaises(SafeExitBindingError) as raised:
            replace(
                valid,
                candidate=replace(valid.candidate, source_frame=second),
            )
        self.assertEqual(raised.exception.reason_code, "CAPTURE_EVENT_MISMATCH")
        with self.assertRaises(SafeExitBindingError) as raised:
            replace(
                valid,
                search_envelope=ProjectedRecoverySearchEnvelope(
                    source_frame=second,
                    available=True,
                    zone_box=(220, 250, 575, 650),
                ),
            )
        self.assertEqual(raised.exception.reason_code, "CAPTURE_EVENT_MISMATCH")

    def test_snapshot_rejects_object_setattr_forgery(self) -> None:
        identity = _load_replay_fixture_identity(1)
        valid = bind_bluestacks_home_safe_exit(
            source_frame=identity,
            permitted_safe_space=SAFE,
            exclusion_inventory=_full_inventory(identity),
            proposed_candidates=(
                _proposal(identity, "exit-a", (500, 250, 540, 290)),
            ),
        )
        object.__setattr__(valid, "authorize_dispatch", True)
        with self.assertRaises(SafeExitBindingError) as raised:
            safe_exit_evidence_snapshot(valid)
        self.assertEqual(raised.exception.reason_code, "SAFE_EXIT_MUST_NOT_AUTHORIZE")

        valid_nested = bind_bluestacks_home_safe_exit(
            source_frame=identity,
            permitted_safe_space=SAFE,
            exclusion_inventory=_full_inventory(identity),
            proposed_candidates=(
                _proposal(identity, "exit-a", (500, 250, 540, 290)),
            ),
        )
        assert valid_nested.candidate is not None
        object.__setattr__(valid_nested.candidate, "box", (790, 1200, 810, 1250))
        with self.assertRaises(SafeExitBindingError):
            safe_exit_evidence_snapshot(valid_nested)

    def test_exclusion_provenance_is_global_and_canonical(self) -> None:
        identity = _load_replay_fixture_identity(1)
        duplicate_hud = _region(
            identity, ExclusionCategory.HUD, "shared-id", (0, 0, 800, 150)
        )
        duplicate_building = _region(
            identity,
            ExclusionCategory.BUILDINGS,
            "shared-id",
            (300, 400, 440, 520),
        )
        with self.assertRaises(SafeExitBindingError) as raised:
            _full_inventory(
                identity,
                hud=(duplicate_hud,),
                buildings=(duplicate_building,),
            )
        self.assertEqual(
            raised.exception.reason_code, "DUPLICATE_EXCLUSION_REGION_ID"
        )

        first_inventory = _full_inventory(identity)
        reversed_proofs = []
        for proof in reversed(first_inventory.coverage):
            reversed_proofs.append(
                CategoryCoverageProof(
                    source_frame=identity,
                    category=proof.category,
                    regions=tuple(reversed(proof.regions)),
                    observed_empty=proof.observed_empty,
                )
            )
        second_inventory = ExclusionInventory(
            source_frame=identity,
            coverage=tuple(reversed_proofs),
        )
        first = bind_bluestacks_home_safe_exit(
            source_frame=identity,
            permitted_safe_space=SAFE,
            exclusion_inventory=first_inventory,
            proposed_candidates=(
                _proposal(identity, "exit-a", (500, 250, 540, 290)),
            ),
        )
        second = bind_bluestacks_home_safe_exit(
            source_frame=identity,
            permitted_safe_space=SAFE,
            exclusion_inventory=second_inventory,
            proposed_candidates=(
                _proposal(identity, "exit-a", (500, 250, 540, 290)),
            ),
        )
        self.assertEqual(
            safe_exit_evidence_snapshot(first),
            safe_exit_evidence_snapshot(second),
        )
        assert first.candidate is not None
        self.assertEqual(
            first.candidate.cleared_exclusion_ids,
            tuple(sorted(first.candidate.cleared_exclusion_ids)),
        )
        self.assertTrue(
            all(":" in value for value in first.candidate.cleared_exclusion_ids)
        )

    def test_no_dispatch_api(self) -> None:
        identity = _load_replay_fixture_identity(1)
        inventory = _full_inventory(identity)
        result = bind_bluestacks_home_safe_exit(
            source_frame=identity,
            permitted_safe_space=SAFE,
            exclusion_inventory=inventory,
            proposed_candidates=(_proposal(identity, "exit-a", (500, 250, 540, 290)),),
        )
        source = Path(inspect.getsourcefile(bind_bluestacks_home_safe_exit) or "").read_text(
            encoding="utf-8"
        )
        forbidden = (
            "adb ",
            "pnsctl",
            "dispatch_tap",
            "input tap",
            "LocalBlueStacksRuntime",
            "connect_runtime",
        )
        lowered = source.lower()
        for token in forbidden:
            self.assertNotIn(token.lower(), lowered)
        self.assertFalse(hasattr(result, "dispatch"))
        self.assertFalse(hasattr(result.candidate, "tap_xy"))
        self.assertIsNone(result.candidate.capability_grant)
        self.assertIsNone(result.candidate.policy_grant)
        self.assertFalse(safe_exit_authorize_dispatch(result))

    def test_immutability(self) -> None:
        identity = _load_replay_fixture_identity(1)
        inventory = _full_inventory(identity)
        result = bind_bluestacks_home_safe_exit(
            source_frame=identity,
            permitted_safe_space=SAFE,
            exclusion_inventory=inventory,
            proposed_candidates=(_proposal(identity, "exit-a", (500, 250, 540, 290)),),
            metadata={"note": "immutable"},
        )
        with self.assertRaises(Exception):
            result.authorize_dispatch = True  # type: ignore[misc]
        with self.assertRaises(Exception):
            result.metadata["note"] = "mutated"  # type: ignore[index]
        self.assertIsInstance(result.metadata, MappingProxyType)
        assert result.candidate is not None
        with self.assertRaises(Exception):
            result.candidate.box = (1, 2, 3, 4)  # type: ignore[misc]

    def test_deterministic_serialization(self) -> None:
        identity = _load_replay_fixture_identity(1)
        inventory = _full_inventory(identity)
        result = bind_bluestacks_home_safe_exit(
            source_frame=identity,
            permitted_safe_space=SAFE,
            exclusion_inventory=inventory,
            proposed_candidates=(_proposal(identity, "exit-a", (500, 250, 540, 290)),),
        )
        first = safe_exit_evidence_snapshot(result)
        second = safe_exit_evidence_snapshot(result)
        self.assertEqual(first, second)
        encoded = json.dumps(first, sort_keys=True)
        self.assertEqual(encoded, json.dumps(second, sort_keys=True))
        self.assertEqual(first["schema_name"], SCHEMA_NAME)
        self.assertEqual(first["schema_version"], SCHEMA_VERSION)
        self.assertFalse(first["authorize_dispatch"])
        self.assertEqual(first["profile_id"], BLUESTACKS_SAFE_EXIT_PROFILE_ID)
        self.assertEqual(first["platform"], BLUESTACKS_SAFE_EXIT_PLATFORM)

    def test_profile_constants_match_native_geometry(self) -> None:
        profile = bluestacks_safe_exit_profile()
        self.assertEqual(profile.width, BLUESTACKS_SAFE_EXIT_WIDTH)
        self.assertEqual(profile.height, BLUESTACKS_SAFE_EXIT_HEIGHT)
        self.assertEqual(profile.width, 800)
        self.assertEqual(profile.height, 1280)
        self.assertEqual(profile.geometry_policy, CONSERVATIVE_GEOMETRY_POLICY)

    def test_planner_honesty_regression_projection_remains_none(self) -> None:
        zone = PredictedRecoverySearchZone(True, 25.0, (220, 250, 575, 650), None)
        self.assertIsNone(zone.executable_recovery_coordinate)
        assert_predicted_recovery_search_zone_non_authorizing(zone)
        with self.assertRaises(ValueError):
            PredictedRecoverySearchZone(True, 25.0, (220, 250, 575, 650), (1, 2))  # type: ignore[arg-type]

    def test_adapter_profile_adoption_without_runtime(self) -> None:
        import importlib
        import sys

        # Import adapter module for the pure helper only; do not invoke CLI/runtime.
        module_name = "scripts.home_atlas_bluestacks"
        if module_name in sys.modules:
            module = sys.modules[module_name]
        else:
            module = importlib.import_module(module_name)
        payload = module.bluestacks_home_safe_exit_adapter_profile()
        self.assertEqual(payload["profile_id"], BLUESTACKS_SAFE_EXIT_PROFILE_ID)
        self.assertEqual(payload["width"], 800)
        self.assertEqual(payload["height"], 1280)
        self.assertFalse(payload["authorize_dispatch"])
        self.assertIsNone(payload["executable_recovery_coordinate"])
        self.assertEqual(payload["default_permitted_safe_space"], SAFE)

    def test_multiple_valid_candidates_are_deterministically_ambiguous(self) -> None:
        identity = _load_replay_fixture_identity(1)
        inventory = _full_inventory(identity)
        proposals = (
            _proposal(identity, "exit-b", (520, 300, 560, 340)),
            _proposal(identity, "exit-a", (500, 250, 540, 290)),
        )
        first = bind_bluestacks_home_safe_exit(
            source_frame=identity,
            permitted_safe_space=SAFE,
            exclusion_inventory=inventory,
            proposed_candidates=proposals,
        )
        second = bind_bluestacks_home_safe_exit(
            source_frame=identity,
            permitted_safe_space=SAFE,
            exclusion_inventory=inventory,
            proposed_candidates=tuple(reversed(proposals)),
        )
        self.assertEqual(first.status, SafeExitBindingStatus.UNAVAILABLE)
        self.assertEqual(
            first.reason_code, "AMBIGUOUS_MULTIPLE_VALID_CANDIDATES"
        )
        self.assertIsNone(first.candidate)
        self.assertEqual(
            safe_exit_evidence_snapshot(first),
            safe_exit_evidence_snapshot(second),
        )

    def test_unavailable_when_uncertainty_no_valid_candidate(self) -> None:
        identity = _load_replay_fixture_identity(1)
        inventory = _full_inventory(identity)
        result = bind_bluestacks_home_safe_exit(
            source_frame=identity,
            permitted_safe_space=SAFE,
            exclusion_inventory=inventory,
            proposed_candidates=(),
        )
        self.assertEqual(result.status, SafeExitBindingStatus.UNAVAILABLE)
        self.assertEqual(result.actionability, SafeExitActionability.NON_ACTIONABLE)
        self.assertFalse(result.authorize_dispatch)


if __name__ == "__main__":
    unittest.main()
