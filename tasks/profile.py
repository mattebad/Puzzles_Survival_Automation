"""Bliss 800x1280 local navigation profile.

These coordinates are bound to independently captured Bliss evidence, not vendor assets.
"""

from .contracts import AnchorSpec

PROFILE_ID = "pns-blissos-poc-virgl-800x1280-v1"
M6_ASSET_ROOT = "evidence/sessions/20260712-m6-dq-bootstrap/assets"
PRAISE_EVIDENCE_DEPENDENCY = (
    "raw Bliss Personal Might Rankings row, Check destination, leaderboard, Praise, and Back states"
)

HOME_QUEST = AnchorSpec(
    "home-quest-entry", (250, 1130, 410, 1280), 0.94,
    template=f"{M6_ASSET_ROOT}/home-base-settled.png#quest-entry-roi",
    asset_provenance=f"{M6_ASSET_ROOT}/home-base-settled.png",
    reference_manifest_ids=("GNB-DAILY-QUEST-CLAIMS",),
)
HOME_LEFT = AnchorSpec(
    "home-left-navigation-anchor", (0, 1130, 250, 1280), 0.90,
    template=f"{M6_ASSET_ROOT}/home-base-settled.png#left-navigation-roi",
    asset_provenance=f"{M6_ASSET_ROOT}/home-base-settled.png",
)
HOME_RIGHT = AnchorSpec(
    "home-right-navigation-anchor", (410, 1130, 800, 1280), 0.90,
    template=f"{M6_ASSET_ROOT}/home-base-settled.png#right-navigation-roi",
    asset_provenance=f"{M6_ASSET_ROOT}/home-base-settled.png",
)
QUEST_DAILY = AnchorSpec(
    # The live Main Quest tab label is centered near (400,105). Keep this
    # local target ROI tight so its center is an actual tab hit point rather
    # than the middle of the whole header/row region.
    "quest-daily-tab", (300, 70, 500, 140), 0.90,
    template=f"{M6_ASSET_ROOT}/quest-main-settled.png#daily-tab-roi",
    asset_provenance=f"{M6_ASSET_ROOT}/quest-main-settled.png",
    reference_manifest_ids=("GNB-DAILY-QUEST-CLAIMS",),
)
DAILY_SELECTED_TAB = AnchorSpec(
    "daily-quest-selected-state", (260, 80, 540, 200), 0.95,
    template=f"{M6_ASSET_ROOT}/daily-quest-settled.png#selected-tab-state-roi",
    asset_provenance=f"{M6_ASSET_ROOT}/daily-quest-settled.png",
)
QUEST_HEADER = AnchorSpec(
    "quest-header", (0, 0, 800, 180), 0.88,
    template=f"{M6_ASSET_ROOT}/quest-main-settled.png#header-roi",
    asset_provenance=f"{M6_ASSET_ROOT}/quest-main-settled.png",
)
DAILY_HEADER = AnchorSpec(
    "daily-quest-header", (0, 0, 800, 450), 0.88,
    template=f"{M6_ASSET_ROOT}/daily-quest-settled.png#header-roi",
    asset_provenance=f"{M6_ASSET_ROOT}/daily-quest-settled.png",
)

GAME_BACK = AnchorSpec(
    "standard-game-back-arrow", (45, 5, 130, 60), 0.898,
    template="evidence/sessions/20260712-mvp-quest-to-claim/reset-reconcile-current.png#back-arrow-roi",
    tap_offset=(0, 0),
    asset_provenance="evidence/sessions/20260712-mvp-quest-to-claim/reset-reconcile-current.png",
    reference_manifest_ids=("GNB-DAILY-CHAPTER",),
)

INDIVIDUAL_HELP_ACTION = AnchorSpec(
    "alliance-help-individual", (556, 274, 727, 330), 0.90,
    template="evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/help-all-validation-20260713/remote/alliance-help-1783981635-source.png#individual-help-button",
    ocr_rule="Help",
    required_confirmation_frames=1,
    polling_interval_seconds=0.15,
    timeout_seconds=3.0,
    tap_offset=(0, 0),
    asset_provenance="evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/help-all-validation-20260713/remote/alliance-help-1783981635-source.png",
)

# Speedup Help is recognized independently from either consequential action target.
SPEEDUP_HELP_SCREEN = AnchorSpec(
    "speedup-help-screen", (250, 0, 550, 120), 0.88,
    template="evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/help-go-post-002.png#speedup-help-header",
    ocr_rule="Speedup Help",
    required_confirmation_frames=1,
    polling_interval_seconds=0.15,
    timeout_seconds=3.0,
    asset_provenance="evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/remote-complete/help-go-post-002.png",
)

HELP_ALL_ACTION = AnchorSpec(
    "alliance-help-all", (277, 1188, 523, 1268), 0.92,
    template="evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/help-all-validation-20260713/remote/alliance-help-1783981635-source.png#bottom-help-all-button",
    ocr_rule="Help All",
    required_confirmation_frames=1,
    polling_interval_seconds=0.15,
    timeout_seconds=3.0,
    tap_offset=(0, 0),
    asset_provenance="evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/help-all-validation-20260713/remote/alliance-help-1783981635-source.png",
)

# Praise route anchors use bounded local ROIs and constrained OCR.  Template references bind
# these controls to the locked Bliss profile; the live adapter still requires fresh semantic
# recognition before every input.
HOME_MORE = AnchorSpec(
    "home-more-navigation", (680, 1130, 800, 1280), 0.90,
    template=f"{M6_ASSET_ROOT}/home-base-settled.png#more-navigation-roi",
    ocr_rule="More",
    asset_provenance=f"{M6_ASSET_ROOT}/home-base-settled.png",
    reference_manifest_ids=("GNB-DAILY-LEADERBOARD-PRAISE",),
)
RANKINGS_ENTRY = AnchorSpec(
    "rankings-entry", (602, 1138, 690, 1167), 0.85,
    template="evidence/sessions/20260713-personal-might-praise/live-route-recovery-014/more-to-rankings-game-attempt-1-attempt-3-source-011.png#rankings-word-roi",
    ocr_rule="Rankings",
    asset_provenance="evidence/sessions/20260713-personal-might-praise/live-route-recovery-014/more-to-rankings-game-attempt-1-attempt-3-source-011.png",
    reference_manifest_ids=("GNB-DAILY-LEADERBOARD-PRAISE",),
)
PERSONAL_MIGHT_ROW = AnchorSpec(
    "personal-might-rank-row", (0, 180, 800, 1000), 0.92,
    template=f"{M6_ASSET_ROOT}/home-base-settled.png#personal-might-row-roi",
    ocr_rule="Personal Might Rank",
    asset_provenance=f"{M6_ASSET_ROOT}/home-base-settled.png",
    reference_manifest_ids=("GNB-DAILY-LEADERBOARD-PRAISE",),
    production_validated=False,
    evidence_dependency=PRAISE_EVIDENCE_DEPENDENCY,
)
PERSONAL_MIGHT_CHECK = AnchorSpec(
    "personal-might-rank-check", (560, 180, 800, 1000), 0.92,
    template=f"{M6_ASSET_ROOT}/home-base-settled.png#personal-might-check-roi",
    ocr_rule="Check",
    asset_provenance=f"{M6_ASSET_ROOT}/home-base-settled.png",
    reference_manifest_ids=("GNB-DAILY-LEADERBOARD-PRAISE",),
    production_validated=False,
    evidence_dependency=PRAISE_EVIDENCE_DEPENDENCY,
)
PERSONAL_MIGHT_LEADERBOARD = AnchorSpec(
    "personal-might-leaderboard", (0, 0, 800, 500), 0.92,
    template=f"{M6_ASSET_ROOT}/home-base-settled.png#personal-might-leaderboard-roi",
    ocr_rule="Personal Might",
    asset_provenance=f"{M6_ASSET_ROOT}/home-base-settled.png",
    reference_manifest_ids=("GNB-DAILY-LEADERBOARD-PRAISE",),
    production_validated=False,
    evidence_dependency=PRAISE_EVIDENCE_DEPENDENCY,
)
MIGHT_PRAISE_ACTION = AnchorSpec(
    "personal-might-praise", (560, 80, 780, 430), 0.94,
    template=f"{M6_ASSET_ROOT}/home-base-settled.png#personal-might-praise-roi",
    ocr_rule="Praise",
    required_confirmation_frames=1,
    polling_interval_seconds=0.15,
    timeout_seconds=3.0,
    tap_offset=(0, 0),
    asset_provenance=f"{M6_ASSET_ROOT}/home-base-settled.png",
    reference_manifest_ids=("GNB-DAILY-LEADERBOARD-PRAISE",),
    production_validated=False,
    evidence_dependency=PRAISE_EVIDENCE_DEPENDENCY,
)
PERSONAL_MIGHT_BACK = AnchorSpec(
    "personal-might-back", (35, 0, 160, 90), 0.90,
    template=f"{M6_ASSET_ROOT}/home-base-settled.png#personal-might-back-roi",
    ocr_rule="Back",
    asset_provenance=f"{M6_ASSET_ROOT}/home-base-settled.png",
    reference_manifest_ids=("GNB-DAILY-LEADERBOARD-PRAISE",),
    production_validated=False,
    evidence_dependency=PRAISE_EVIDENCE_DEPENDENCY,
)
RANKINGS_BACK = AnchorSpec(
    "rankings-back", (35, 0, 160, 90), 0.90,
    template=f"{M6_ASSET_ROOT}/home-base-settled.png#rankings-back-roi",
    ocr_rule="Back",
    asset_provenance=f"{M6_ASSET_ROOT}/home-base-settled.png",
    reference_manifest_ids=("GNB-DAILY-LEADERBOARD-PRAISE",),
    production_validated=False,
    evidence_dependency="raw Bliss Rankings Back state",
)
RESET_POPUP_CLOSE = AnchorSpec(
    "reset-popup-close", (260, 750, 540, 870), 0.90,
    template="evidence/sessions/20260713-personal-might-praise/live-corrected-popup-006/reset-popup-source-002.png#close-button-roi",
    ocr_rule="Close",
    required_confirmation_frames=1,
    polling_interval_seconds=0.15,
    timeout_seconds=3.0,
    tap_offset=(0, 0),
    asset_provenance="evidence/sessions/20260713-personal-might-praise/live-corrected-popup-006/reset-popup-source-002.png",
)
