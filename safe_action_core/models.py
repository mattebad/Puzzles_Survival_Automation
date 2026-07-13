"""Immutable data contracts for policy, journal, and executor boundaries."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from typing import Any, Dict, Optional, Tuple

ROI = Tuple[int, int, int, int]


class ActionStatus(str, Enum):
    PREPARED = "prepared"
    INPUT_SENT = "input_sent"
    CONFIRMED = "confirmed"
    UNRESOLVED = "unresolved"
    CANCELLED = "cancelled"


class ActionClass(str, Enum):
    NAVIGATION_ONLY = "navigation_only"
    ZERO_COST_CONSEQUENTIAL = "zero_cost_consequential"
    SPEND_OR_STRATEGIC = "spend_or_strategic"


class PolicyDecision(str, Enum):
    AUTHORIZE = "authorize"
    DENY = "deny"
    GLOBAL_INPUT_LOCK = "global_input_lock"


@dataclass(frozen=True)
class Observation:
    frame_sha256: str
    capture_completed_monotonic: float
    runtime_profile_id: str
    width: int
    height: int
    valid_png: bool
    corrupt: bool
    black: bool
    source_state: str
    overlay_state: str
    target_identity: Optional[str]
    target_roi: Optional[ROI]
    recognized: bool = True
    clipped: bool = False
    ambiguous: bool = False
    control_class: Optional[str] = None
    consequence: Optional[str] = None
    cost_type: Optional[str] = None
    cost_amount: Optional[float] = None
    quantity: Optional[int] = None
    expected_postcondition: Optional[str] = None
    evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    critical_roi_hashes: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)
    ocr_result_frame_sha256: Optional[str] = None
    ocr_result_capture_completed_monotonic: Optional[float] = None
    ocr_reused: bool = False
    source_family: Optional[str] = None
    target_isolated: bool = False
    forbidden_region_intersects_target: bool = False
    arrow_geometry: Optional[str] = None
    forbidden_regions: Tuple[Tuple[str, ROI], ...] = field(default_factory=tuple)
    package_foreground: bool = True
    os_surface: bool = False
    hard_stop_detected: bool = False


@dataclass(frozen=True)
class PolicyRequest:
    action_id: str
    action_key: str
    task_id: str
    task_mode: str
    semantic_action: str
    expected_runtime_profile_id: str
    observation: Observation
    monotonic_now: float
    observation_max_age_seconds: float
    dispatch_max_age_seconds: float
    lease_owner: Optional[str]
    lease_valid: bool
    unresolved_action: bool
    duplicate_action_key: bool
    game_day_id: Optional[str] = None
    policy_phase: str = "proposal"
    promotional_back_count: int = 0
    action_class: ActionClass = ActionClass.ZERO_COST_CONSEQUENTIAL
    action_kind: Optional[str] = None
    subject: Optional[str] = None
    resource_or_currency: Optional[str] = None
    maximum_cost: Optional[float] = None
    free_only: bool = False
    allowed_confirmation_dialogs: Tuple[str, ...] = field(default_factory=tuple)
    semantic_preconditions: Tuple[str, ...] = field(default_factory=tuple)
    semantic_postconditions: Tuple[str, ...] = field(default_factory=tuple)

    def with_observation(
        self, observation: Observation, monotonic_now: float, policy_phase: str = "pre_dispatch"
    ) -> "PolicyRequest":
        return replace(
            self,
            observation=observation,
            monotonic_now=monotonic_now,
            policy_phase=policy_phase,
        )


@dataclass(frozen=True)
class PolicyResult:
    decision: PolicyDecision
    reason_code: str
    reason: str
    evaluated_at: float
    request_snapshot: Dict[str, Any]

    @property
    def authorized(self) -> bool:
        return self.decision == PolicyDecision.AUTHORIZE


@dataclass(frozen=True)
class ActionIntent:
    action_id: str
    action_key: str
    task_id: str
    semantic_action: str
    source_state: str
    target_identity: str
    target_roi: ROI
    source_frame_sha256: str
    source_frame_captured_at: float
    runtime_profile_id: str
    game_day_id: Optional[str]
    expected_postcondition: str
    consequence: str
    cost_type: str
    cost_amount: float
    quantity: int
    evidence_refs: Tuple[str, ...]
    consequential: bool = True
    source_family: Optional[str] = None
    target_isolated: bool = False
    forbidden_region_intersects_target: bool = False
    arrow_geometry: Optional[str] = None
    promotional_back_count: int = 0
    action_class: ActionClass = ActionClass.ZERO_COST_CONSEQUENTIAL
    action_kind: Optional[str] = None
    subject: Optional[str] = None
    resource_or_currency: Optional[str] = None
    maximum_cost: Optional[float] = None
    free_only: bool = False
    allowed_confirmation_dialogs: Tuple[str, ...] = field(default_factory=tuple)
    semantic_preconditions: Tuple[str, ...] = field(default_factory=tuple)
    semantic_postconditions: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TransportResult:
    dispatched: bool
    transport_code: str
    detail: str = ""


def snapshot(value: Any) -> Any:
    """Return a JSON-safe deterministic representation of a model value."""
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [snapshot(item) for item in value]
    if isinstance(value, list):
        return [snapshot(item) for item in value]
    if isinstance(value, dict):
        return {str(key): snapshot(item) for key, item in value.items()}
    return value
