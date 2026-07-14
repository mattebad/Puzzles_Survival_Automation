"""Offline Zombie Lair participation contract.

This module composes the shared World/stamina recognizer with explicit Lair identity, level,
march-slot, and stamina policy.  It owns no combat or transport, runtime registration, persistence,
or live evidence capture.  Main-Quest wording, level 60, and ambiguous combat states fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .contracts import ActionTransactionSpec, ROI, TaskOutcome, TaskResult
from .profile import PROFILE_ID
from .world_stamina import WorldStaminaObservation, world_route_authorizeable


ZOMBIE_LAIR_SCREEN = "WORLD"
ZOMBIE_LAIR_DESTINATION = "ZOMBIE_LAIR"
ZOMBIE_LAIR_JOIN_TARGET = "zombie-lair-join"
BLISS_NATIVE_TARGET_PROVENANCE = "bliss-native"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ZombieLairObservation:
    """Semantic evidence for one recognized, policy-allowlisted Lair join."""

    screen_state: str
    selected_world: bool
    route_identity: str
    lair_identity: str
    lair_level: Optional[int]
    level_allowlisted: bool
    target_roi: ROI
    panel_bounds: ROI
    action_target_identity: str
    control_class: str
    action_ready: bool
    march_slot_available: bool
    stamina_before: int
    stamina_cost: Optional[int]
    stamina_budget: int
    combat_mode_visible: bool = False
    defeat_confirmed: bool = False
    result_identity: str = ""
    game_day_id: Optional[str] = None
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    overlay_state: str = "none_observed"
    reset_guard_active: bool = False
    runtime_profile_id: str = PROFILE_ID
    recognized: bool = True


def _target_inside_panel(observation: ZombieLairObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1)


def _has_bliss_native_source(observation: ZombieLairObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLISS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == PROFILE_ID
    )


def _world_observation(observation: ZombieLairObservation) -> WorldStaminaObservation:
    return WorldStaminaObservation(
        screen_state=observation.screen_state,
        selected_world=observation.selected_world,
        route_identity=observation.route_identity,
        destination_kind=ZOMBIE_LAIR_DESTINATION,
        target_identity=observation.lair_identity,
        target_roi=observation.target_roi,
        panel_bounds=observation.panel_bounds,
        resource_name="STAMINA",
        current_resource=observation.stamina_before,
        resource_budget=observation.stamina_budget,
        refill_visible=False,
        game_day_id=observation.game_day_id,
        target_provenance=observation.target_provenance,
        source_frame_sha256=observation.source_frame_sha256,
        evidence_refs=observation.evidence_refs,
        overlay_state=observation.overlay_state,
        reset_guard_active=observation.reset_guard_active,
        runtime_profile_id=observation.runtime_profile_id,
        recognized=observation.recognized,
    )


def zombie_lair_authorizeable(observation: ZombieLairObservation) -> bool:
    """Require exact Lair identity, safe level, march slot, and bounded stamina cost."""

    return bool(
        world_route_authorizeable(
            _world_observation(observation),
            destination_kind=ZOMBIE_LAIR_DESTINATION,
        )
        and bool(observation.lair_identity.strip())
        and observation.lair_level is not None
        and observation.lair_level > 0
        and observation.lair_level != 60
        and observation.lair_identity == f"lair-level-{observation.lair_level}"
        and observation.level_allowlisted
        and observation.action_target_identity == ZOMBIE_LAIR_JOIN_TARGET
        and observation.control_class == "JOIN_LAIR"
        and observation.action_ready
        and observation.march_slot_available
        and observation.stamina_cost is not None
        and observation.stamina_cost > 0
        and observation.stamina_cost <= observation.stamina_before
        and observation.stamina_cost <= observation.stamina_budget
        and not observation.combat_mode_visible
        and _target_inside_panel(observation)
        and observation.overlay_state in {"none", "none_observed"}
        and bool(observation.game_day_id)
        and not observation.reset_guard_active
        and observation.recognized
        and _has_bliss_native_source(observation)
    )


def zombie_lair_transaction_spec(
    observation: ZombieLairObservation,
) -> ActionTransactionSpec:
    if not zombie_lair_authorizeable(observation):
        raise ValueError("Zombie Lair preconditions are not positively recognized")
    return ActionTransactionSpec(
        action_kind="JOIN_ZOMBIE_LAIR",
        expected_source_screen=ZOMBIE_LAIR_SCREEN,
        subject=observation.lair_identity,
        quantity=1,
        resource_or_currency="STAMINA",
        maximum_cost=observation.stamina_budget,
        free_only=False,
        allowed_confirmation_dialogs=(),
        semantic_preconditions=(
            "world_zombie_lair_route",
            "exact_lair_identity",
            "allowlisted_lair_level",
            "available_march_slot",
            "stamina_cost_within_budget",
            "no_combat_dispatch",
            "bliss_native_target_evidence",
        ),
        semantic_postconditions=("lair_defeat_or_participation_result",),
    )


def zombie_lair_postcondition_verified(
    before: ZombieLairObservation,
    after: ZombieLairObservation | None,
) -> bool:
    """Require same-day same-Lair exact stamina delta and confirmed defeat/result."""

    if not zombie_lair_authorizeable(before) or after is None:
        return False
    if (
        not zombie_lair_authorizeable(after)
        or after.lair_identity != before.lair_identity
        or after.lair_level != before.lair_level
        or after.game_day_id != before.game_day_id
        or after.stamina_before
        != before.stamina_before - before.stamina_cost
    ):
        return False
    return bool(after.defeat_confirmed or after.result_identity.strip())


def zombie_lair_perform_one_pulse(
    before: ZombieLairObservation,
    after: ZombieLairObservation | None = None,
) -> TaskResult:
    """Return a pure result; Lair transport and combat remain evidence-gated."""

    if not zombie_lair_authorizeable(before):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_AUTHORIZED_ZOMBIE_LAIR_ACTION",
            verified=True,
            state=ZOMBIE_LAIR_SCREEN,
        )
    if after is None:
        return TaskResult.progress(
            "JOIN_ZOMBIE_LAIR is authorized by the offline contract; dispatch remains evidence-gated",
            ZOMBIE_LAIR_SCREEN,
        )
    if not zombie_lair_postcondition_verified(before, after):
        return TaskResult(
            TaskOutcome.FAILED_SAFE,
            "ZOMBIE_LAIR_POSTCONDITION_NOT_PROVEN",
            state=ZOMBIE_LAIR_SCREEN,
        )
    return TaskResult.done(
        "Zombie Lair postcondition verified",
        f"zombie-lair:{before.lair_identity}:completed",
        ZOMBIE_LAIR_SCREEN,
    )
