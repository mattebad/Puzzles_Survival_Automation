"""Bliss 800x1280 local navigation profile.

These coordinates are bound to independently captured Bliss evidence, not vendor assets.
"""

from .contracts import AnchorSpec

PROFILE_ID = "pns-blissos-poc-virgl-800x1280-v1"
M6_ASSET_ROOT = "evidence/sessions/20260712-m6-dq-bootstrap/assets"

HOME_QUEST = AnchorSpec(
    "home-quest-entry", (250, 1130, 410, 1280), 0.94,
    template=f"{M6_ASSET_ROOT}/home-base-settled.png#quest-entry-roi",
    asset_provenance=f"{M6_ASSET_ROOT}/home-base-settled.png",
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
)

ALLIANCE_HELP_ACTION = AnchorSpec(
    "alliance-help-action", (580, 320, 720, 380), 0.92,
    template="evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/help-go-post-1.png#alliance-help-roi",
    ocr_rule="Help <current>/<total>",
    required_confirmation_frames=1,
    polling_interval_seconds=0.15,
    timeout_seconds=3.0,
    tap_offset=(0, 0),
    asset_provenance="evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/help-go-post-1.png",
)

# The retained route evidence shows that the old (580,320)-(720,380) point is passive text,
# not an action. Help All is the orange control on the independently captured Speedup Help
# surface. This is intentionally a separate anchor so the old mistarget cannot be reused.
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
    "speedup-help-all", (556, 274, 727, 330), 0.90,
    template="evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/help-go-post-002.png#help-all-button",
    ocr_rule="Help All",
    required_confirmation_frames=1,
    polling_interval_seconds=0.15,
    timeout_seconds=3.0,
    tap_offset=(0, 0),
    asset_provenance="evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/remote-complete/help-go-post-002.png",
)
