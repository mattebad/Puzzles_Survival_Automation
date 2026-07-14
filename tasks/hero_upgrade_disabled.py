"""Offline model for disabled Daily Hero upgrades.

Hero identity, material policy, and level arithmetic are replayable. Material spend, upgrade
dispatch, runtime registration, and scheduler eligibility remain blocked by policy.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .contracts import ROI, TaskOutcome, TaskResult
from .profile import PROFILE_ID


HERO_SCREEN = "HERO"
HERO_TARGET = "hero-upgrade"
DISABLED_POLICY_REASON = "HERO_UPGRADE_DISABLED_POLICY"
BLISS_NATIVE_TARGET_PROVENANCE = "bliss-native"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class HeroUpgradeObservation:
    """Semantic selected-hero evidence with no executable upgrade target."""

    screen_state: str
    selected_daily_row: bool
    objective_key: str
    hero_identity: str
    hero_selected: bool
    current_level: Optional[int]
    target_level: Optional[int]
    target_identity: str
    target_roi: ROI
    panel_bounds: ROI
    control_class: str
    upgrade_control_visible: bool
    material_known: bool
    material_identity: str
    material_amount: Optional[int]
    material_balance: Optional[int]
    daily_progress_before: int
    hero_level_after: Optional[int] = None
    daily_progress_after: Optional[int] = None
    successor_state: str = ""
    game_day_id: Optional[str] = None
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    overlay_state: str = "none_observed"
    reset_guard_active: bool = False
    runtime_profile_id: str = PROFILE_ID
    recognized: bool = True


def _target_inside_panel(observation: HeroUpgradeObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1)


def _has_bliss_native_source(observation: HeroUpgradeObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLISS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == PROFILE_ID
    )


def hero_upgrade_authorizeable(observation: HeroUpgradeObservation) -> bool:
    """Recognize exact selected-hero upgrade evidence; this does not authorize an upgrade."""

    return bool(
        observation.screen_state == HERO_SCREEN
        and observation.selected_daily_row
        and observation.objective_key == "upgrade_hero"
        and bool(observation.hero_identity.strip())
        and observation.hero_selected
        and observation.current_level is not None
        and observation.current_level >= 0
        and observation.target_level == observation.current_level + 1
        and observation.target_identity == HERO_TARGET
        and observation.control_class == "UPGRADE"
        and observation.upgrade_control_visible
        and _target_inside_panel(observation)
        and observation.material_known
        and bool(observation.material_identity.strip())
        and observation.material_amount is not None
        and observation.material_amount > 0
        and observation.material_balance is not None
        and observation.material_balance >= observation.material_amount
        and 0 <= observation.daily_progress_before < 3
        and observation.overlay_state in {"none", "none_observed"}
        and bool(observation.game_day_id)
        and not observation.reset_guard_active
        and observation.recognized
        and _has_bliss_native_source(observation)
    )


def hero_upgrade_postcondition_verified(
    before: HeroUpgradeObservation,
    after: HeroUpgradeObservation | None,
) -> bool:
    """Verify offline hero-level arithmetic without implying permission to spend."""

    if not hero_upgrade_authorizeable(before) or after is None:
        return False
    return bool(
        hero_upgrade_authorizeable(after)
        and after.hero_identity == before.hero_identity
        and after.game_day_id == before.game_day_id
        and after.current_level == before.target_level
        and after.hero_level_after == after.current_level
        and after.daily_progress_after == before.daily_progress_before + 1
        and after.daily_progress_after <= 3
        and after.successor_state == "HERO_LEVEL_RECONCILED"
    )


def hero_upgrade_disabled_dispatch(observation: HeroUpgradeObservation) -> TaskResult:
    """Always block hero upgrade dispatch under current policy."""

    if not hero_upgrade_authorizeable(observation):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_VALID_HERO_UPGRADE_OBSERVATION",
            verified=True,
            state=HERO_SCREEN,
        )
    return TaskResult(
        TaskOutcome.BLOCKED,
        DISABLED_POLICY_REASON,
        verified=True,
        state=HERO_SCREEN,
        details={"dispatch_count": 0},
    )
