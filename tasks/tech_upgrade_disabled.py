"""Typed recommendation, prerequisite, ordinary-cost, and effect checks for Research."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Optional

from .contracts import ROI
from .profile import ACTIVE_RUNTIME_PROFILE_ID, BLUESTACKS_NATIVE_TARGET_PROVENANCE


RESEARCH_RESOURCES = ("food", "wood", "steel", "gas")
LIST_SCREEN = "RECOMMENDED_LIST"
DETAIL_SCREEN = "RESEARCH_DETAIL"
ACTIVE_SCREEN = "RESEARCH_ACTIVE"
RESEARCH_START_CONTROL = "RESEARCH_START"
RESEARCH_START_SUFFIX = ":detail-research-button"
LIST_RESEARCH_SUFFIX = ":list-research-button"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class ResearchResourceRow:
    """One visible detail-body balance/cost pair; amounts are never inferred."""

    resource: str
    cost: Optional[int]
    balance: Optional[int]


@dataclass(frozen=True)
class RecommendedResearchListObservation:
    """Fresh, current Research Center list with its first displayed recommendation."""

    screen_state: str
    recomd_section_visible: bool
    first_recommendation_title: str
    first_recommendation_identity: str
    recommendation_position: int
    target_identity: str
    target_roi: ROI
    panel_bounds: ROI
    control_class: str
    target_provenance: str
    source_frame_sha256: str
    evidence_refs: tuple[str, ...]
    overlay_state: str = "none_observed"
    runtime_profile_id: str = ACTIVE_RUNTIME_PROFILE_ID
    recognized: bool = True


@dataclass(frozen=True)
class TechUpgradeObservation:
    """The exact first recommendation after list navigation, with complete current detail."""

    screen_state: str
    recommendation_frame_sha256: str
    first_recommendation_title: str
    first_recommendation_identity: str
    recommendation_position: int
    selected_technology_title: str
    selected_technology_identity: str
    current_level: Optional[int]
    target_level: Optional[int]
    prerequisites_known: bool
    prerequisites_met: bool
    prerequisite_evidence: tuple[str, ...]
    queue1_state: str
    queue1_remaining_seconds: Optional[int]
    queue2_activate_tapped: bool
    requirements_scrolled: bool
    resource_rows: tuple[ResearchResourceRow, ...]
    duration_seconds: Optional[int]
    target_identity: str
    target_roi: ROI
    panel_bounds: ROI
    control_class: str
    research_start_visible: bool
    research_now_diamonds: Optional[int]
    research_now_target_identity: str
    research_now_tapped: bool
    target_provenance: str
    source_frame_sha256: str
    evidence_refs: tuple[str, ...]
    overlay_state: str = "none_observed"
    runtime_profile_id: str = ACTIVE_RUNTIME_PROFILE_ID
    recognized: bool = True


@dataclass(frozen=True)
class ResearchActiveObservation:
    """A fresh active-queue reading paired to the exact pre-dispatch costs."""

    screen_state: str
    active_technology_title: str
    active_technology_identity: str
    queue1_state: str
    remaining_seconds: Optional[int]
    resource_rows: tuple[ResearchResourceRow, ...]
    target_provenance: str
    source_frame_sha256: str
    evidence_refs: tuple[str, ...]
    overlay_state: str = "none_observed"
    runtime_profile_id: str = ACTIVE_RUNTIME_PROFILE_ID
    recognized: bool = True


def research_identity(title: str) -> str | None:
    """Return a stable ASCII target key, refusing titles with unrepresentable text."""

    if type(title) is not str or not title or title != title.strip():
        return None
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")
    return slug if slug and _SLUG_RE.fullmatch(slug) else None


def _target_inside_panel(target_roi: ROI, panel_bounds: ROI) -> bool:
    try:
        px0, py0, px1, py1 = panel_bounds
        tx0, ty0, tx1, ty1 = target_roi
    except (TypeError, ValueError):
        return False
    return bool(
        all(type(value) is int for value in (*panel_bounds, *target_roi))
        and px0 <= tx0 < tx1 <= px1
        and py0 <= ty0 < ty1 <= py1
    )


def _has_bluestacks_native_source(
    *, target_provenance: str, source_frame_sha256: str,
    evidence_refs: tuple[str, ...], runtime_profile_id: str,
) -> bool:
    refs = tuple(str(ref) for ref in evidence_refs)
    return bool(
        target_provenance == BLUESTACKS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "native:", "synthetic:")) for ref in refs)
        and runtime_profile_id == ACTIVE_RUNTIME_PROFILE_ID
    )

def _valid_resource_rows(
    rows: object,
    *,
    require_affordable: bool,
    require_costs: bool = True,
) -> bool:
    if not isinstance(rows, tuple) or len(rows) != len(RESEARCH_RESOURCES):
        return False
    if any(not isinstance(row, ResearchResourceRow) for row in rows):
        return False
    if {row.resource for row in rows} != set(RESEARCH_RESOURCES):
        return False
    if len({row.resource for row in rows}) != len(rows):
        return False
    return all(
        (type(row.cost) is int and row.cost >= 0)
        if require_costs
        else (row.cost is None or (type(row.cost) is int and row.cost >= 0))
        for row in rows
    ) and all(
        type(row.balance) is int
        and row.balance >= (row.cost if require_affordable else 0)
        for row in rows
    )




def tech_upgrade_queue_deferral(
    observation: TechUpgradeObservation,
) -> tuple[str, int | None] | None:
    """Return a busy queue's exact timer, or None when its current state is unknown."""

    state = observation.queue1_state
    remaining = observation.queue1_remaining_seconds
    if state == "idle" and remaining is None:
        return ("idle", None)
    if state in {"active", "busy"} and type(remaining) is int and remaining > 0:
        return ("busy", remaining)
    return None

def _queue1_idle(observation: TechUpgradeObservation) -> bool:
    if observation.queue1_state != "idle":
        return False
    return observation.queue1_remaining_seconds is None


def research_list_navigation_authorizeable(
    observation: RecommendedResearchListObservation,
) -> bool:
    """Admit only the first Recom'd row's Research navigation control."""

    slug = research_identity(observation.first_recommendation_title)
    expected = f"recommended-research:{slug}{LIST_RESEARCH_SUFFIX}" if slug else ""
    return bool(
        observation.recomd_section_visible is True
        and slug is not None
        and observation.first_recommendation_identity == slug
        and observation.screen_state == LIST_SCREEN
        and type(observation.recommendation_position) is int
        and observation.recommendation_position == 1
        and observation.target_identity == expected
        and observation.control_class == "RESEARCH_NAVIGATE"
        and _target_inside_panel(observation.target_roi, observation.panel_bounds)
        and observation.overlay_state in {"none", "none_observed"}
        and observation.recognized is True
        and _has_bluestacks_native_source(
            target_provenance=observation.target_provenance,
            source_frame_sha256=observation.source_frame_sha256,
            evidence_refs=observation.evidence_refs,
            runtime_profile_id=observation.runtime_profile_id,
        )
    )


def research_list_navigation_verified(
    before: RecommendedResearchListObservation,
    after: TechUpgradeObservation | None,
) -> bool:
    """Prove the list's Research control opened detail for that exact first row."""

    if not research_list_navigation_authorizeable(before) or after is None:
        return False
    slug = before.first_recommendation_identity
    return bool(
        after.screen_state == DETAIL_SCREEN
        and after.recommendation_frame_sha256 == before.source_frame_sha256
        and after.first_recommendation_title == before.first_recommendation_title
        and after.first_recommendation_identity == slug
        and research_identity(after.selected_technology_title) == slug
        and after.selected_technology_identity == slug
        and after.recommendation_position == 1
        and after.target_identity == f"recommended-research:{slug}{RESEARCH_START_SUFFIX}"
        and after.control_class == RESEARCH_START_CONTROL
        and after.research_start_visible is True
        and after.research_now_tapped is False
        and after.overlay_state in {"none", "none_observed"}
        and after.recognized is True
        and _has_bluestacks_native_source(
            target_provenance=after.target_provenance,
            source_frame_sha256=after.source_frame_sha256,
            evidence_refs=after.evidence_refs,
            runtime_profile_id=after.runtime_profile_id,
        )
    )


def tech_upgrade_authorizeable(
    observation: TechUpgradeObservation,
    recommendation: RecommendedResearchListObservation,
) -> bool:
    """Check a fresh first-recommendation detail and every ordinary-resource row."""

    if not research_list_navigation_verified(recommendation, observation):
        return False
    slug = research_identity(observation.first_recommendation_title)
    selected_slug = research_identity(observation.selected_technology_title)
    expected_target = f"recommended-research:{slug}{RESEARCH_START_SUFFIX}" if slug else ""
    return bool(
        observation.screen_state == DETAIL_SCREEN
        and observation.recommendation_frame_sha256 == recommendation.source_frame_sha256
        and slug is not None
        and slug == observation.first_recommendation_identity == selected_slug == observation.selected_technology_identity
        and type(observation.recommendation_position) is int and observation.recommendation_position == 1
        and type(observation.current_level) is int and observation.current_level >= 0
        and type(observation.target_level) is int and observation.target_level > observation.current_level
        and observation.prerequisites_known is True
        and observation.prerequisites_met is True
        and isinstance(observation.prerequisite_evidence, tuple)
        and bool(observation.prerequisite_evidence)
        and all(type(item) is str and item.strip() for item in observation.prerequisite_evidence)
        and _queue1_idle(observation)
        and observation.queue2_activate_tapped is False
        and observation.requirements_scrolled is True
        and _valid_resource_rows(observation.resource_rows, require_affordable=True)
        and type(observation.duration_seconds) is int and observation.duration_seconds > 0
        and observation.target_identity == expected_target
        and observation.control_class == RESEARCH_START_CONTROL
        and observation.research_start_visible is True
        and type(observation.research_now_diamonds) is int and observation.research_now_diamonds > 0
        and observation.research_now_target_identity == "research-now-diamonds"
        and observation.research_now_tapped is False
        and _target_inside_panel(observation.target_roi, observation.panel_bounds)
        and observation.overlay_state in {"none", "none_observed"}
        and observation.recognized is True
        and _has_bluestacks_native_source(
            target_provenance=observation.target_provenance,
            source_frame_sha256=observation.source_frame_sha256,
            evidence_refs=observation.evidence_refs,
            runtime_profile_id=observation.runtime_profile_id,
        )
    )


def tech_upgrade_shortages(
    observation: TechUpgradeObservation,
    recommendation: RecommendedResearchListObservation,
) -> tuple[tuple[str, int], ...] | None:
    """Return exact ordinary-resource shortages, or None when any row is unknown."""

    if (
        not research_list_navigation_verified(recommendation, observation)
        or observation.screen_state != DETAIL_SCREEN
        or observation.requirements_scrolled is not True
        or not _valid_resource_rows(observation.resource_rows, require_affordable=False)
    ):
        return None
    return tuple(
        (row.resource, row.cost - row.balance)
        for row in observation.resource_rows
        if row.balance < row.cost
    )


def tech_upgrade_postcondition_verified(
    before: TechUpgradeObservation,
    after: ResearchActiveObservation | None,
    recommendation: RecommendedResearchListObservation,
) -> bool:
    """Require exact active target/timer and the paired, full four-resource debit."""

    if not tech_upgrade_authorizeable(before, recommendation) or after is None:
        return False
    before_rows = {row.resource: row for row in before.resource_rows}
    if not _valid_resource_rows(
        after.resource_rows, require_affordable=False, require_costs=False
    ):
        return False
    if any(type(row.balance) is not int or row.balance < 0 for row in after.resource_rows):
        return False
    after_balances = {row.resource: row.balance for row in after.resource_rows}
    return bool(
        after.screen_state == ACTIVE_SCREEN
        and after.active_technology_identity == before.first_recommendation_identity
        and research_identity(after.active_technology_title) == before.first_recommendation_identity
        and after.queue1_state == "active"
        and type(after.remaining_seconds) is int
        and 0 < after.remaining_seconds <= before.duration_seconds
        and all(
            before_rows[resource].balance - after_balances[resource] == before_rows[resource].cost
            for resource in RESEARCH_RESOURCES
        )
        and after.overlay_state in {"none", "none_observed"}
        and after.recognized is True
        and _has_bluestacks_native_source(
            target_provenance=after.target_provenance,
            source_frame_sha256=after.source_frame_sha256,
            evidence_refs=after.evidence_refs,
            runtime_profile_id=after.runtime_profile_id,
        )
    )
