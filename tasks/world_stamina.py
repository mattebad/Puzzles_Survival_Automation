"""Offline shared World and stamina/AP accounting primitive.

This module recognizes route and resource state for future Daily world flows.  It performs no
resource transaction, owns no transport or runtime registration, and never authorizes a coordinate
tap.  Stale, ambiguous, Main-Quest, and static-reference observations fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Mapping, Optional

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


# Navigation foundation primitives are deliberately separate from the resource
# accounting above.  They recognize/bind World controls and future node targets,
# but never authorize a resource, march, or combat action.
WORLD_NAVIGATION_STATES = frozenset(
    {
        "HOME_READY",
        "HOME_CANONICAL",
        "WORLD_READY",
        "WORLD_SEARCH_OPEN",
        "BLOCKED_FAIL_CLOSED",
    }
)
WORLD_ZOOM_SUPPORTED = "WORLD_ZOOM_SUPPORTED"
WORLD_ZOOM_UNKNOWN = "WORLD_ZOOM_UNKNOWN"
WORLD_NAVIGATION_TARGETS = frozenset(
    {
        "home-to-world",
        "world-search-entry",
        "world-search-close",
        "world-to-home",
        "reset-popup-close",
    }
)
WORLD_FORBIDDEN_IDENTITIES = frozenset(
    {
        "gather",
        "gathering",
        "resource-node",
        "march",
        "combat",
        "attack",
        "dispatch",
        "stamina",
        "ap",
    }
)
WORLD_FORBIDDEN_NODE_ACTION_MARKERS = frozenset(
    {
        "march",
        "formation",
        "occupancy",
        "combat",
        "attack",
        "dispatch",
        "stamina",
        "ap",
        "currency",
    }
)
NATIVE_WORLD_WIDTH = 800
NATIVE_WORLD_HEIGHT = 1280


def _valid_native_roi(value: object) -> bool:
    try:
        x0, y0, x1, y1 = tuple(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return bool(
        type(x0) is int
        and type(y0) is int
        and type(x1) is int
        and type(y1) is int
        and 0 <= x0 < x1 <= NATIVE_WORLD_WIDTH
        and 0 <= y0 < y1 <= NATIVE_WORLD_HEIGHT
    )


def _valid_sha256(value: object) -> bool:
    return bool(isinstance(value, str) and _SHA256_RE.fullmatch(value))


@dataclass(frozen=True)
class WorldNavigationObservation:
    """Current native-frame facts used by the navigation-only route.

    ``controls`` and node fields are frame-local.  A retained coordinate is never
    enough to construct this object without the matching current-frame digest.
    """

    state: str
    source_frame_sha256: str
    evidence_ref: str
    runtime_profile_id: str = "pns-bluestacks-5-p64-800x1280-v1"
    frame_width: int = NATIVE_WORLD_WIDTH
    frame_height: int = NATIVE_WORLD_HEIGHT
    recognized: bool = True
    overlay_state: str = "none_observed"
    unknown_modal: bool = False
    zoom_identity: str = WORLD_ZOOM_SUPPORTED
    controls: Mapping[str, tuple[int, int, int, int]] = ()
    node_identity: str | None = None
    node_roi: tuple[int, int, int, int] | None = None
    node_source_frame_sha256: str | None = None
    semantic_evidence: tuple[str, ...] = ()
    control_semantics: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    control_geometry_source: Mapping[str, str] = field(default_factory=dict)
    zoom_evidence: tuple[str, ...] = ()
    localization_evidence: tuple[str, ...] = ()
    node_label: str | None = None
    node_label_roi: tuple[int, int, int, int] | None = None
    node_semantic_evidence: tuple[str, ...] = ()

    def control_roi(self, identity: str) -> tuple[int, int, int, int] | None:
        value = self.controls.get(identity) if hasattr(self.controls, "get") else None
        if value is None:
            return None
        return tuple(value)


def world_navigation_observation_from_mapping(
    payload: Mapping[str, object],
) -> WorldNavigationObservation:
    """Parse an independently authored observation without trusting its geometry."""

    controls_raw = payload.get("controls") or {}
    if not isinstance(controls_raw, Mapping):
        controls_raw = {}
    controls: dict[str, tuple[int, int, int, int]] = {}
    for identity, roi in controls_raw.items():
        if isinstance(identity, str):
            try:
                controls[identity] = tuple(int(item) for item in roi)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                controls[identity] = ()
    node_roi = payload.get("node_roi")
    if node_roi is not None:
        try:
            node_roi = tuple(int(item) for item in node_roi)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            node_roi = None
    evidence = payload.get("semantic_evidence") or ()
    if isinstance(evidence, str):
        evidence = (evidence,)
    control_semantics_raw = payload.get("control_semantics") or {}
    if not isinstance(control_semantics_raw, Mapping):
        control_semantics_raw = {}
    control_semantics: dict[str, tuple[str, ...]] = {}
    for identity, values in control_semantics_raw.items():
        if isinstance(identity, str):
            if isinstance(values, str):
                values = (values,)
            try:
                control_semantics[identity] = tuple(str(item) for item in values)
            except TypeError:
                control_semantics[identity] = ()
    geometry_raw = payload.get("control_geometry_source") or {}
    if not isinstance(geometry_raw, Mapping):
        geometry_raw = {}
    control_geometry_source = {
        str(identity): str(source)
        for identity, source in geometry_raw.items()
    }
    zoom_evidence = payload.get("zoom_evidence") or ()
    if isinstance(zoom_evidence, str):
        zoom_evidence = (zoom_evidence,)
    localization_evidence = payload.get("localization_evidence") or ()
    if isinstance(localization_evidence, str):
        localization_evidence = (localization_evidence,)
    node_label_roi = payload.get("node_label_roi")
    if node_label_roi is not None:
        try:
            node_label_roi = tuple(int(item) for item in node_label_roi)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            node_label_roi = None
    return WorldNavigationObservation(
        state=str(payload.get("state") or ""),
        source_frame_sha256=str(payload.get("source_frame_sha256") or ""),
        evidence_ref=str(payload.get("evidence_ref") or ""),
        runtime_profile_id=str(
            payload.get("runtime_profile_id") or "pns-bluestacks-5-p64-800x1280-v1"
        ),
        frame_width=int(payload.get("frame_width") or NATIVE_WORLD_WIDTH),
        frame_height=int(payload.get("frame_height") or NATIVE_WORLD_HEIGHT),
        recognized=payload.get("recognized") is not False,
        overlay_state=str(payload.get("overlay_state") or "none_observed"),
        unknown_modal=payload.get("unknown_modal") is True,
        zoom_identity=str(payload.get("zoom_identity") or WORLD_ZOOM_UNKNOWN),
        controls=controls,
        node_identity=(
            str(payload["node_identity"])
            if payload.get("node_identity") is not None
            else None
        ),
        node_roi=node_roi,  # type: ignore[arg-type]
        node_source_frame_sha256=(
            str(payload["node_source_frame_sha256"])
            if payload.get("node_source_frame_sha256") is not None
            else None
        ),
        semantic_evidence=tuple(str(item) for item in evidence),
        control_semantics=control_semantics,
        control_geometry_source=control_geometry_source,
        zoom_evidence=tuple(str(item) for item in zoom_evidence),
        localization_evidence=tuple(str(item) for item in localization_evidence),
        node_label=(
            str(payload["node_label"])
            if payload.get("node_label") is not None
            else None
        ),
        node_label_roi=node_label_roi,  # type: ignore[arg-type]
        node_semantic_evidence=tuple(
            str(item) for item in (payload.get("node_semantic_evidence") or ())
        ),
    )


def world_navigation_observation_authorizeable(
    observation: WorldNavigationObservation,
    *,
    expected_state: str,
    required_target_identity: str | None = None,
    require_supported_zoom: bool = False,
) -> bool:
    """Fail-closed current-frame recognition for an ordinary navigation target."""

    if (
        observation.state != expected_state
        or expected_state not in WORLD_NAVIGATION_STATES
        or not observation.recognized
        or observation.unknown_modal
        or observation.overlay_state not in {"none", "none_observed", ""}
        or observation.runtime_profile_id != "pns-bluestacks-5-p64-800x1280-v1"
        or (observation.frame_width, observation.frame_height)
        != (NATIVE_WORLD_WIDTH, NATIVE_WORLD_HEIGHT)
        or not _valid_sha256(observation.source_frame_sha256)
        or not observation.evidence_ref
        or "local-reference" in observation.evidence_ref
    ):
        return False
    if not observation.semantic_evidence:
        return False
    if expected_state == "HOME_CANONICAL" and not any(
        "canonical" in str(item).casefold()
        or "home" in str(item).casefold()
        for item in observation.semantic_evidence
    ):
        return False
    if require_supported_zoom and (
        observation.zoom_identity != WORLD_ZOOM_SUPPORTED
        or not observation.zoom_evidence
        or not observation.localization_evidence
        or not any(
            "current" in str(item).casefold()
            or "frame" in str(item).casefold()
            for item in observation.localization_evidence
        )
    ):
        return False
    if required_target_identity is not None:
        if required_target_identity not in WORLD_NAVIGATION_TARGETS:
            return False
        roi = observation.control_roi(required_target_identity)
        semantics = observation.control_semantics.get(required_target_identity, ())
        geometry_source = observation.control_geometry_source.get(required_target_identity)
        if (
            roi is None
            or not _valid_native_roi(roi)
            or not semantics
            or geometry_source != "current-frame-bounded-candidate"
        ):
            return False
        required_terms = {
            "home-to-world": ("world",),
            "world-search-entry": ("search",),
            "world-search-close": ("close",),
            "world-to-home": ("home", "base"),
            "reset-popup-close": ("close",),
        }[required_target_identity]
        semantic_text = " ".join(str(item).casefold() for item in semantics)
        if not any(term in semantic_text for term in required_terms):
            return False
    return True


def world_node_binding_authorizeable(
    observation: WorldNavigationObservation,
) -> bool:
    """Bind a future node only when identity and ROI came from one current frame."""

    return bool(
        world_navigation_observation_authorizeable(
            observation,
            expected_state="WORLD_READY",
            require_supported_zoom=True,
        )
        and observation.node_identity
        and observation.node_identity.strip()
        and not any(
            marker in observation.node_identity.casefold()
            for marker in WORLD_FORBIDDEN_NODE_ACTION_MARKERS
        )
        and observation.node_label
        and observation.node_label.strip()
        and _valid_native_roi(observation.node_roi)
        and _valid_native_roi(observation.node_label_roi)
        and observation.node_source_frame_sha256
        == observation.source_frame_sha256
        and observation.node_semantic_evidence
        and any(
            "spatial" in str(item).casefold()
            or "associated" in str(item).casefold()
            for item in observation.node_semantic_evidence
        )
        and _roi_intersects(observation.node_roi, observation.node_label_roi)
    )


def _roi_intersects(
    first: tuple[int, int, int, int] | None,
    second: tuple[int, int, int, int] | None,
) -> bool:
    if not (_valid_native_roi(first) and _valid_native_roi(second)):
        return False
    ax0, ay0, ax1, ay1 = first  # type: ignore[misc]
    bx0, by0, bx1, by1 = second  # type: ignore[misc]
    return max(ax0, bx0) < min(ax1, bx1) and max(ay0, by0) < min(ay1, by1)


@dataclass(frozen=True)
class WorldPanPlan:
    """Bounded planning output; a plan is not an input authorization."""

    source_frame_sha256: str
    direction: str
    start: tuple[int, int]
    end: tuple[int, int]
    maximum_steps: int
    target_identity: str = "world-camera-pan-plan"


def plan_bounded_world_pan(
    observation: WorldNavigationObservation,
    *,
    direction: str,
    maximum_steps: int = 1,
) -> WorldPanPlan | None:
    """Produce at most one evidence-bound plan for later node localization."""

    if not world_navigation_observation_authorizeable(
        observation,
        expected_state="WORLD_READY",
        require_supported_zoom=True,
    ):
        return None
    normalized = str(direction).strip().lower()
    if normalized not in {"left", "right", "up", "down"}:
        return None
    if type(maximum_steps) is not int or not 1 <= maximum_steps <= 3:
        return None
    center = (400, 640)
    delta = {
        "left": (-180, 0),
        "right": (180, 0),
        "up": (0, -180),
        "down": (0, 180),
    }[normalized]
    return WorldPanPlan(
        observation.source_frame_sha256,
        normalized,
        center,
        (center[0] + delta[0], center[1] + delta[1]),
        maximum_steps,
    )


def plan_bounded_world_search(
    observation: WorldNavigationObservation,
) -> tuple[str, tuple[int, int], str] | None:
    """Return a current-frame Search tap plan without accepting query/node input."""

    if not world_navigation_observation_authorizeable(
        observation,
        expected_state="WORLD_READY",
        required_target_identity="world-search-entry",
        require_supported_zoom=True,
    ):
        return None
    roi = observation.control_roi("world-search-entry")
    assert roi is not None
    return (
        observation.source_frame_sha256,
        roi,
        "world-search-entry",
    )
