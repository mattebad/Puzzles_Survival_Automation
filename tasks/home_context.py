"""Shared Home context levels and navigation primitives.

Adapts existing Home Atlas localization/navigation. Does not dispatch ADB input and does
not replace the verified navigate-building runtime path. Canonical Home is recovery only.

Three facts stay distinct:
- Base-surface identity (zoom-independent; see ``tasks.home_base_vision``)
- Atlas localization / camera pose (``is_home_localized`` / ``is_atlas_localized``)
- Canonical Home (fully zoomed out + near-origin; terminal / recovery only)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Optional

from .home_atlas import (
    AmbiguityState,
    BuildingBinding,
    ClosedLoopBuildingNavigator,
    HomeAtlas,
    LocalizationResult,
    NavigationAction,
    NavigationCommand,
    ZoomIdentity,
)
from .runtime_identity import VerifiedRuntimeIdentity


# Bump intentionally when shared Home navigation policy changes; dependent flow contracts
# that pin HOME_NAVIGATION_PRIMITIVES_DIGEST must move to regression_required.
HOME_NAVIGATION_PRIMITIVES_DIGEST = sha256(
    b"home_context:v3:verified_identity|fully_out_localization_only|"
    b"home_ready|home_localized|home_canonical|"
    b"ensure_home_ready|localize_home|ensure_canonical_home|navigate_home_building|"
    b"canonical_is_recovery_only"
).hexdigest()

LOCALIZATION_CONFIDENCE_FLOOR = 0.80


class HomeContextLevel(str, Enum):
    HOME_READY = "home_ready"
    HOME_LOCALIZED = "home_localized"
    HOME_CANONICAL = "home_canonical"


class HomePrimitiveAction(str, Enum):
    NONE = "none"
    LOCALIZE = "localize"
    RECOVER_CANONICAL = "recover_canonical"
    BIND_BUILDING = "bind_building"
    PAN = "pan"
    TAP_BUILDING = "tap_building"
    STOP = "stop"


@dataclass(frozen=True)
class HomeReadyObservation:
    """Positive Home-ready facts; unknowns fail closed."""

    game_foregrounded: bool
    expected_native_profile: bool
    identity: VerifiedRuntimeIdentity | None
    manual_only_state: bool
    blocking_unknown_modal: bool


@dataclass(frozen=True)
class HomeContextDecision:
    level: Optional[HomeContextLevel]
    reason: str
    action: HomePrimitiveAction = HomePrimitiveAction.NONE
    navigation: Optional[NavigationCommand] = None
    requires_canonical_recovery: bool = False


def ensure_home_ready(observation: HomeReadyObservation) -> HomeContextDecision:
    if observation.manual_only_state:
        return HomeContextDecision(None, "manual_only_state", HomePrimitiveAction.STOP)
    if observation.blocking_unknown_modal:
        return HomeContextDecision(None, "blocking_unknown_modal", HomePrimitiveAction.STOP)
    if not observation.game_foregrounded:
        return HomeContextDecision(None, "game_not_foregrounded", HomePrimitiveAction.STOP)
    if not observation.expected_native_profile:
        return HomeContextDecision(None, "unexpected_native_profile", HomePrimitiveAction.STOP)
    if observation.identity is None or not observation.identity.permits_supervised_navigation:
        return HomeContextDecision(None, "account_server_identity_unavailable", HomePrimitiveAction.STOP)
    return HomeContextDecision(HomeContextLevel.HOME_READY, "home_ready")


def is_home_localized(localization: LocalizationResult, *, confidence_floor: float = LOCALIZATION_CONFIDENCE_FLOOR) -> bool:
    """Atlas pose is fully zoomed out and positively localized (not Base-surface identity)."""

    return bool(
        localization.recognized
        and localization.screen_to_atlas is not None
        and localization.confidence >= confidence_floor
        and localization.ambiguity_state is AmbiguityState.NONE
        and not localization.stale
        and not localization.overlay
        and localization.zoom_identity is ZoomIdentity.FULLY_ZOOMED_OUT
    )


def is_atlas_localized(
    localization: LocalizationResult, *, confidence_floor: float = LOCALIZATION_CONFIDENCE_FLOOR
) -> bool:
    """Alias for atlas-localized Home; keep Base-surface recognition separate."""

    return is_home_localized(localization, confidence_floor=confidence_floor)


def is_home_canonical(localization: LocalizationResult, *, confidence_floor: float = LOCALIZATION_CONFIDENCE_FLOOR) -> bool:
    """Terminal/recovery Home: fully zoomed out and near the calibration origin."""

    if not is_home_localized(localization, confidence_floor=confidence_floor):
        return False
    if localization.zoom_identity is not ZoomIdentity.FULLY_ZOOMED_OUT:
        return False
    if localization.overlay or localization.screen_to_atlas is None:
        return False
    if localization.residual_px is None or localization.residual_px > 2.0:
        return False
    # Canonical atlas camera pose: near-origin translation. Localized noncanonical Home may
    # share zoom/confidence while remaining away from the calibration pose.
    tx = localization.screen_to_atlas[0][2]
    ty = localization.screen_to_atlas[1][2]
    return abs(tx) <= 8.0 and abs(ty) <= 8.0


def is_canonical_home(
    localization: LocalizationResult, *, confidence_floor: float = LOCALIZATION_CONFIDENCE_FLOOR
) -> bool:
    """Alias for terminal canonical Home."""

    return is_home_canonical(localization, confidence_floor=confidence_floor)


def classify_home_context(
    ready: HomeReadyObservation,
    localization: Optional[LocalizationResult] = None,
    *,
    confidence_floor: float = LOCALIZATION_CONFIDENCE_FLOOR,
) -> HomeContextDecision:
    ready_decision = ensure_home_ready(ready)
    if ready_decision.level is None:
        return ready_decision
    if localization is None:
        return HomeContextDecision(HomeContextLevel.HOME_READY, "home_ready_awaiting_localization", HomePrimitiveAction.LOCALIZE)
    if is_home_canonical(localization, confidence_floor=confidence_floor):
        return HomeContextDecision(HomeContextLevel.HOME_CANONICAL, "home_canonical")
    if is_home_localized(localization, confidence_floor=confidence_floor):
        return HomeContextDecision(HomeContextLevel.HOME_LOCALIZED, "home_localized")
    return HomeContextDecision(
        HomeContextLevel.HOME_READY,
        f"localization_insufficient:{localization.ambiguity_state.value}",
        HomePrimitiveAction.RECOVER_CANONICAL,
        requires_canonical_recovery=True,
    )


def localize_home(
    ready: HomeReadyObservation,
    localization: LocalizationResult,
    *,
    confidence_floor: float = LOCALIZATION_CONFIDENCE_FLOOR,
) -> HomeContextDecision:
    """Establish home_localized from a current frame, without forcing canonical pose."""

    ready_decision = ensure_home_ready(ready)
    if ready_decision.level is None:
        return ready_decision
    if is_home_localized(localization, confidence_floor=confidence_floor):
        level = (
            HomeContextLevel.HOME_CANONICAL
            if is_home_canonical(localization, confidence_floor=confidence_floor)
            else HomeContextLevel.HOME_LOCALIZED
        )
        return HomeContextDecision(level, level.value)
    return HomeContextDecision(
        HomeContextLevel.HOME_READY,
        f"localize_home_failed:{localization.zoom_identity.value}:{localization.ambiguity_state.value}",
        HomePrimitiveAction.RECOVER_CANONICAL,
        requires_canonical_recovery=True,
    )


def ensure_canonical_home(
    ready: HomeReadyObservation,
    localization: LocalizationResult,
    *,
    confidence_floor: float = LOCALIZATION_CONFIDENCE_FLOOR,
) -> HomeContextDecision:
    """Recovery/calibration only: fully zoomed out, recognized, no overlay."""

    ready_decision = ensure_home_ready(ready)
    if ready_decision.level is None:
        return ready_decision
    if is_home_canonical(localization, confidence_floor=confidence_floor):
        return HomeContextDecision(HomeContextLevel.HOME_CANONICAL, "home_canonical")
    return HomeContextDecision(
        HomeContextLevel.HOME_READY,
        "canonical_home_not_established",
        HomePrimitiveAction.RECOVER_CANONICAL,
        requires_canonical_recovery=True,
    )


def navigate_home_building(
    atlas: HomeAtlas,
    building_id: str,
    ready: HomeReadyObservation,
    localization: LocalizationResult,
    binding: BuildingBinding | None = None,
    *,
    navigator: ClosedLoopBuildingNavigator | None = None,
    confidence_floor: float = LOCALIZATION_CONFIDENCE_FLOOR,
) -> HomeContextDecision:
    """Navigate from the current localized viewport; canonical only on localization failure.

    Already-visible buildings bind/tap without pan. Offscreen buildings use the existing
    closed-loop atlas navigator. This primitive never dispatches transport itself.
    """

    ready_decision = ensure_home_ready(ready)
    if ready_decision.level is None:
        return ready_decision

    localized = is_home_localized(localization, confidence_floor=confidence_floor)
    if not localized:
        # Zoomed-in / failed localization: recover through canonical, do not invent pans.
        return HomeContextDecision(
            HomeContextLevel.HOME_READY,
            "navigate_requires_canonical_recovery",
            HomePrimitiveAction.RECOVER_CANONICAL,
            requires_canonical_recovery=True,
        )

    controller = navigator or ClosedLoopBuildingNavigator(atlas, building_id)
    if localization.zoom_identity is not ZoomIdentity.FULLY_ZOOMED_OUT:
        return HomeContextDecision(
            HomeContextLevel.HOME_READY,
            "unsupported_zoom_requires_canonical_recovery",
            HomePrimitiveAction.RECOVER_CANONICAL,
            requires_canonical_recovery=True,
        )
    command = controller.next_command(localization, binding)

    if command.action is NavigationAction.BIND_TARGET:
        return HomeContextDecision(
            HomeContextLevel.HOME_LOCALIZED,
            command.reason,
            HomePrimitiveAction.BIND_BUILDING,
            navigation=command,
        )
    if command.action is NavigationAction.TAP_TARGET:
        return HomeContextDecision(
            HomeContextLevel.HOME_LOCALIZED,
            command.reason,
            HomePrimitiveAction.TAP_BUILDING,
            navigation=command,
        )
    if command.action is NavigationAction.PAN:
        return HomeContextDecision(
            HomeContextLevel.HOME_LOCALIZED,
            command.reason,
            HomePrimitiveAction.PAN,
            navigation=command,
        )
    if command.reason.startswith("localization_failed") or command.reason == "canonical_zoom_required":
        return HomeContextDecision(
            HomeContextLevel.HOME_READY,
            command.reason,
            HomePrimitiveAction.RECOVER_CANONICAL,
            navigation=command,
            requires_canonical_recovery=True,
        )
    return HomeContextDecision(
        HomeContextLevel.HOME_LOCALIZED,
        command.reason,
        HomePrimitiveAction.STOP,
        navigation=command,
        requires_canonical_recovery=command.terminal and "localization" in command.reason,
    )


def home_levels_are_distinct() -> bool:
    return (
        HomeContextLevel.HOME_READY.value
        != HomeContextLevel.HOME_LOCALIZED.value
        != HomeContextLevel.HOME_CANONICAL.value
        and HomeContextLevel.HOME_READY.value != HomeContextLevel.HOME_CANONICAL.value
    )
