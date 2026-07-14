"""Offline shared World and stamina/AP accounting primitive.

This module recognizes route and resource state for future Daily world flows.  It performs no
resource transaction, owns no transport or runtime registration, and never authorizes a coordinate
tap.  Stale, ambiguous, Main-Quest, and static-reference observations fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .contracts import ROI, TaskOutcome, TaskResult
from .profile import PROFILE_ID


WORLD_SCREEN = "WORLD"
ALLOWED_DESTINATION_KINDS = frozenset({"ZOMBIE_LAIR", "RESOURCE_NODE", "CAMPAIGN"})
BLISS_NATIVE_TARGET_PROVENANCE = "bliss-native"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class WorldStaminaObservation:
    """Semantic evidence for one stable World route/resource state."""

    screen_state: str
    selected_world: bool
    route_identity: str
    destination_kind: str
    target_identity: str
    target_roi: ROI
    panel_bounds: ROI
    resource_name: str
    current_resource: int
    resource_budget: int
    refill_visible: bool = False
    game_day_id: Optional[str] = None
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    overlay_state: str = "none_observed"
    reset_guard_active: bool = False
    runtime_profile_id: str = PROFILE_ID
    recognized: bool = True


def _target_inside_panel(observation: WorldStaminaObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1)


def _has_bliss_native_source(observation: WorldStaminaObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLISS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == PROFILE_ID
    )


def world_route_authorizeable(
    observation: WorldStaminaObservation,
    *,
    destination_kind: str,
) -> bool:
    """Recognize a current-frame route without authorizing any input."""

    return bool(
        observation.screen_state == WORLD_SCREEN
        and observation.selected_world
        and destination_kind in ALLOWED_DESTINATION_KINDS
        and observation.destination_kind == destination_kind
        and bool(observation.route_identity.strip())
        and bool(observation.target_identity.strip())
        and _target_inside_panel(observation)
        and observation.resource_name in {"STAMINA", "AP"}
        and observation.current_resource >= 0
        and observation.resource_budget >= 0
        and not observation.refill_visible
        and observation.overlay_state in {"none", "none_observed"}
        and bool(observation.game_day_id)
        and not observation.reset_guard_active
        and observation.recognized
        and _has_bliss_native_source(observation)
    )


def world_resource_budget_authorizeable(
    observation: WorldStaminaObservation,
    *,
    resource_name: str,
    requested_cost: int,
) -> bool:
    """Check future resource use against explicit current and per-task budgets."""

    return bool(
        world_route_authorizeable(
            observation,
            destination_kind=observation.destination_kind,
        )
        and resource_name in {"STAMINA", "AP"}
        and observation.resource_name == resource_name
        and requested_cost > 0
        and requested_cost <= observation.current_resource
        and requested_cost <= observation.resource_budget
    )


def world_route_postcondition_verified(
    before: WorldStaminaObservation,
    after: WorldStaminaObservation | None,
    *,
    destination_kind: str,
) -> bool:
    """Require stable same-day route and resource state; no action is dispatched."""

    if (
        not world_route_authorizeable(before, destination_kind=destination_kind)
        or after is None
        or not world_route_authorizeable(after, destination_kind=destination_kind)
    ):
        return False
    return bool(
        after.game_day_id == before.game_day_id
        and after.route_identity == before.route_identity
        and after.target_identity == before.target_identity
        and after.resource_name == before.resource_name
        and after.current_resource == before.current_resource
    )


def world_stamina_replay_one_pulse(
    before: WorldStaminaObservation,
    after: WorldStaminaObservation | None = None,
    *,
    destination_kind: str,
) -> TaskResult:
    """Replay route recognition only; never dispatches resource or navigation input."""

    if not world_route_authorizeable(before, destination_kind=destination_kind):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_AUTHORIZED_WORLD_ROUTE",
            verified=True,
            state=WORLD_SCREEN,
        )
    if after is None:
        return TaskResult.progress(
            "World route recognized; navigation and resource transactions remain offline-only",
            WORLD_SCREEN,
        )
    if not world_route_postcondition_verified(
        before, after, destination_kind=destination_kind
    ):
        return TaskResult(
            TaskOutcome.FAILED_SAFE,
            "WORLD_ROUTE_POSTCONDITION_NOT_STABLE",
            state=WORLD_SCREEN,
        )
    return TaskResult.done(
        "World route and resource state replay verified",
        f"world-route:{destination_kind}:{before.target_identity}:stable",
        WORLD_SCREEN,
    )
