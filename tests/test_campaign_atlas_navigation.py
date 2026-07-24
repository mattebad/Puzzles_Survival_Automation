from __future__ import annotations

import unittest
from pathlib import Path

from tasks.campaign_atlas import (
    CAMPAIGN_PACKAGE,
    CAMPAIGN_PLATFORM,
    CAMPAIGN_PROFILE_ID,
    INTEGRATION_FLOW_ID,
    CampaignAmbiguityState,
    CampaignAtlas,
    CampaignAtlasLandmark,
    CampaignAtlasViewport,
    CampaignDestinationBinding,
    CampaignDestinationKind,
    CampaignLocalizationResult,
    LandmarkKind,
    NAVIGATION_BLOCKED_FAIL_CLOSED,
    NAVIGATION_EVIDENCE_REQUIRED,
    ZERO_TRANSPORT_REPLAY_COMPLETE,
    load_campaign_atlas,
    plan_shared_campaign_destination_navigation,
    project_landmark_search_roi,
    resolve_campaign_consumer_destination,
    summarize_zero_transport_replay,
)
from tasks.campaign_auto_battle import plan_campaign_ap_atlas_navigation
from tasks.ultimate_challenge_daily import plan_ultimate_challenge_atlas_navigation

ATLAS_MANIFEST = Path(
    ".local-captures/flow-delivery/CAMPAIGN-ATLAS-NAVIGATION-INTEGRATION-AND-REPLAY/"
    "campaign-atlas-native-800x1280-v4/atlas.json"
)
IDENTITY = (
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, 0.0, 1.0),
)


def _atlas(*, chapter_label: str = "Chapter 21") -> CampaignAtlas:
    viewport = CampaignAtlasViewport(
        viewport_id="viewport-001",
        image_path="tiles/viewport-001.png",
        source_sha256="a" * 64,
        transport_sha256="b" * 64,
        transform_to_atlas=IDENTITY,
        residual_px=0.0,
        overlap_ratio=1.0,
        source_session_id="survey-test",
    )
    landmarks = (
        CampaignAtlasLandmark(
            landmark_id="chapter-21",
            kind=LandmarkKind.CHAPTER,
            label=chapter_label,
            atlas_roi=(100, 200, 160, 260),
            supporting_frame_sha256="a" * 64,
            source_viewport_id="viewport-001",
        ),
        CampaignAtlasLandmark(
            landmark_id="ultimate-challenge",
            kind=LandmarkKind.ULTIMATE_CHALLENGE,
            label="Ultimate Challenge",
            atlas_roi=(400, 500, 520, 560),
            supporting_frame_sha256="a" * 64,
            source_viewport_id="viewport-001",
        ),
    )
    return CampaignAtlas(
        schema_version=1,
        atlas_id="campaign-atlas-test",
        flow_id=INTEGRATION_FLOW_ID,
        profile_id=CAMPAIGN_PROFILE_ID,
        platform=CAMPAIGN_PLATFORM,
        package=CAMPAIGN_PACKAGE,
        native_width=800,
        native_height=1280,
        width=800,
        height=1280,
        source_survey_session_ids=("survey-test",),
        viewports=(viewport,),
        landmarks=landmarks,
        loop_closure_residual_px=0.0,
        cross_difficulty_compared=True,
        difficulty_used_as_recenter=False,
    )


def _localized() -> CampaignLocalizationResult:
    return CampaignLocalizationResult(
        True,
        CAMPAIGN_PROFILE_ID,
        IDENTITY,
        0.9,
        1.0,
        ("viewport-001",),
        CampaignAmbiguityState.NONE,
        "c" * 64,
    )


def _bound(*, kind: CampaignDestinationKind, label: str, roi=(100, 200, 160, 260)) -> CampaignDestinationBinding:
    return CampaignDestinationBinding(
        kind,
        label,
        True,
        roi,
        "c" * 64,
        0.95,
        True,
        (80, 180, 180, 280),
        "current-frame bound",
    )


class CampaignAtlasNavigationTests(unittest.TestCase):
    def test_atlas_rejects_difficulty_as_recenter(self) -> None:
        with self.assertRaises(ValueError):
            CampaignAtlas(
                schema_version=1,
                atlas_id="bad",
                flow_id=INTEGRATION_FLOW_ID,
                profile_id=CAMPAIGN_PROFILE_ID,
                platform=CAMPAIGN_PLATFORM,
                package=CAMPAIGN_PACKAGE,
                native_width=800,
                native_height=1280,
                width=800,
                height=1280,
                source_survey_session_ids=("survey-test",),
                viewports=(
                    CampaignAtlasViewport(
                        "viewport-001",
                        "tiles/x.png",
                        "a" * 64,
                        "b" * 64,
                        IDENTITY,
                        0.0,
                        1.0,
                    ),
                ),
                landmarks=(),
                loop_closure_residual_px=0.0,
                cross_difficulty_compared=False,
                difficulty_used_as_recenter=True,
            )

    def test_resolve_consumer_destinations(self) -> None:
        kind, label = resolve_campaign_consumer_destination("campaign_ap", "1-21-9")
        self.assertIs(kind, CampaignDestinationKind.CHAPTER)
        self.assertEqual(label, "Chapter 21")
        kind, label = resolve_campaign_consumer_destination("campaign_ap", "1-20-9")
        self.assertEqual(label, "Chapter 20")
        kind, label = resolve_campaign_consumer_destination("ultimate_challenge", "prison-trial")
        self.assertIs(kind, CampaignDestinationKind.ULTIMATE_CHALLENGE)
        self.assertEqual(label, "Ultimate Challenge")
        with self.assertRaises(ValueError):
            resolve_campaign_consumer_destination("campaign_ap", "ultimate-challenge")

    def test_projection_narrows_search_without_authority(self) -> None:
        atlas = _atlas()
        landmark = atlas.lookup_landmark(kind=LandmarkKind.CHAPTER, label="Chapter 21")
        assert landmark is not None
        localization = _localized()
        search = project_landmark_search_roi(localization, landmark, pad_px=10)
        self.assertEqual(search, (90, 190, 170, 270))
        self.assertFalse(localization.authorizes_input)

    def test_shared_seam_requires_localization_and_binding(self) -> None:
        atlas = _atlas()
        missing = plan_shared_campaign_destination_navigation(
            consumer="campaign_ap",
            destination_id="1-21-9",
            localization=None,
            binding=None,
            atlas=atlas,
        )
        self.assertEqual(missing.terminal, NAVIGATION_EVIDENCE_REQUIRED)
        self.assertTrue(missing.evidence_required)
        self.assertFalse(missing.dispatch_authorized)
        self.assertEqual(missing.transport_count, 0)

        unbound = plan_shared_campaign_destination_navigation(
            consumer="campaign_ap",
            destination_id="1-21-9",
            localization=_localized(),
            binding=CampaignDestinationBinding(
                CampaignDestinationKind.CHAPTER,
                "Chapter 21",
                False,
                None,
                "c" * 64,
                0.0,
                True,
                (90, 190, 170, 270),
                "ambiguous",
            ),
            atlas=atlas,
        )
        self.assertEqual(unbound.terminal, NAVIGATION_EVIDENCE_REQUIRED)
        self.assertIn("current-frame", unbound.reason)

    def test_shared_seam_completes_zero_transport_without_dispatch(self) -> None:
        atlas = _atlas()
        campaign = plan_shared_campaign_destination_navigation(
            consumer="campaign_ap",
            destination_id="1-21-9",
            localization=_localized(),
            binding=_bound(kind=CampaignDestinationKind.CHAPTER, label="Chapter 21"),
            atlas=atlas,
        )
        ultimate = plan_shared_campaign_destination_navigation(
            consumer="ultimate_challenge",
            destination_id="ultimate-challenge",
            localization=_localized(),
            binding=_bound(
                kind=CampaignDestinationKind.ULTIMATE_CHALLENGE,
                label="Ultimate Challenge",
                roi=(400, 500, 520, 560),
            ),
            atlas=atlas,
        )
        self.assertEqual(campaign.terminal, ZERO_TRANSPORT_REPLAY_COMPLETE)
        self.assertEqual(ultimate.terminal, ZERO_TRANSPORT_REPLAY_COMPLETE)
        self.assertFalse(campaign.dispatch_authorized)
        self.assertFalse(ultimate.dispatch_authorized)
        report = summarize_zero_transport_replay(atlas=atlas, decisions=(campaign, ultimate))
        self.assertEqual(report.status, ZERO_TRANSPORT_REPLAY_COMPLETE)
        self.assertEqual(report.transport_count, 0)
        self.assertFalse(report.dispatch_authorized)

    def test_missing_product_chapter_is_evidence_required(self) -> None:
        atlas = _atlas(chapter_label="Chapter 21")
        decision = plan_shared_campaign_destination_navigation(
            consumer="campaign_ap",
            destination_id="1-20-9",
            localization=_localized(),
            binding=None,
            atlas=atlas,
        )
        self.assertEqual(decision.terminal, NAVIGATION_EVIDENCE_REQUIRED)
        self.assertIn("Chapter 20", decision.reason)

    def test_consumer_wrappers_reuse_shared_seam(self) -> None:
        atlas = _atlas()
        campaign = plan_campaign_ap_atlas_navigation(
            destination="1-20-9",
            localization=_localized(),
            binding=None,
            atlas=atlas,
        )
        self.assertEqual(campaign.terminal, NAVIGATION_EVIDENCE_REQUIRED)
        self.assertIn("Chapter 20", campaign.reason)
        ultimate = plan_ultimate_challenge_atlas_navigation(
            localization=_localized(),
            binding=_bound(
                kind=CampaignDestinationKind.ULTIMATE_CHALLENGE,
                label="Ultimate Challenge",
                roi=(400, 500, 520, 560),
            ),
            atlas=atlas,
        )
        self.assertEqual(ultimate.terminal, ZERO_TRANSPORT_REPLAY_COMPLETE)
        self.assertFalse(ultimate.dispatch_authorized)

    def test_binding_mismatch_fails_closed(self) -> None:
        atlas = _atlas()
        decision = plan_shared_campaign_destination_navigation(
            consumer="campaign_ap",
            destination_id="1-21-9",
            localization=_localized(),
            binding=_bound(kind=CampaignDestinationKind.CHAPTER, label="Chapter 7"),
            atlas=atlas,
        )
        self.assertEqual(decision.terminal, NAVIGATION_BLOCKED_FAIL_CLOSED)

    def test_accepted_atlas_artifact_has_landmarks_and_no_chapter_nine(self) -> None:
        if not ATLAS_MANIFEST.is_file():
            self.skipTest("accepted Campaign atlas artifact not built in this workspace")
        atlas = load_campaign_atlas(ATLAS_MANIFEST)
        self.assertEqual(atlas.atlas_id, "campaign-atlas-native-800x1280-v4")
        self.assertFalse(atlas.difficulty_used_as_recenter)
        labels = {item.label for item in atlas.landmarks}
        self.assertIn("Ultimate Challenge", labels)
        self.assertIn("Chapter 21", labels)
        self.assertIn("Chapter 20", labels)
        self.assertIn("Chapter 15", labels)
        self.assertIn("Chapter 2", labels)
        self.assertIsNone(
            atlas.lookup_landmark(kind=LandmarkKind.CHAPTER, label="Chapter 9")
        )
        self.assertGreaterEqual(len(atlas.viewports), 8)
        self.assertGreaterEqual(len(atlas.landmarks), 12)
        self.assertEqual(atlas.image_path, "atlas.png")
        self.assertTrue((ATLAS_MANIFEST.parent / "atlas.png").is_file())


if __name__ == "__main__":
    unittest.main()
