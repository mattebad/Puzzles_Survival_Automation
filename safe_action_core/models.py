"""Immutable data contracts for policy, journal, and executor boundaries."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass, field, fields as dataclass_fields, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple

ROI = Tuple[int, int, int, int]

# Stable capability firewall reason codes (no secrets).
CAPABILITY_AUTHORIZED = "CAPABILITY_AUTHORIZED"
CAPABILITY_DENIED = "CAPABILITY_DENIED"
CAPABILITY_ALREADY_CONSUMED = "CAPABILITY_ALREADY_CONSUMED"
CAPABILITY_FORGERY = "CAPABILITY_FORGERY"
CAPABILITY_BINDING_MISMATCH = "CAPABILITY_BINDING_MISMATCH"
CAPABILITY_SESSION_MISMATCH = "CAPABILITY_SESSION_MISMATCH"
CAPABILITY_TASK_MISMATCH = "CAPABILITY_TASK_MISMATCH"
CAPABILITY_ACTION_MISMATCH = "CAPABILITY_ACTION_MISMATCH"
CAPABILITY_ACTION_KEY_MISMATCH = "CAPABILITY_ACTION_KEY_MISMATCH"
CAPABILITY_SEMANTIC_ACTION_MISMATCH = "CAPABILITY_SEMANTIC_ACTION_MISMATCH"
CAPABILITY_ACTION_CLASS_MISMATCH = "CAPABILITY_ACTION_CLASS_MISMATCH"
CAPABILITY_TARGET_MISMATCH = "CAPABILITY_TARGET_MISMATCH"
CAPABILITY_CAPTURE_MISMATCH = "CAPABILITY_CAPTURE_MISMATCH"
CAPABILITY_COORDINATE_MISMATCH = "CAPABILITY_COORDINATE_MISMATCH"
CAPABILITY_PROFILE_MISMATCH = "CAPABILITY_PROFILE_MISMATCH"
CAPABILITY_GEOMETRY_MISMATCH = "CAPABILITY_GEOMETRY_MISMATCH"
CAPABILITY_DIGEST_ONLY_REJECTED = "CAPABILITY_DIGEST_ONLY_REJECTED"
CAPABILITY_STALE_OBSERVATION = "CAPABILITY_STALE_OBSERVATION"
CAPABILITY_NAVIGATION_CONSEQUENTIAL_DENIED = "CAPABILITY_NAVIGATION_CONSEQUENTIAL_DENIED"
CAPABILITY_UNKNOWN_CLASS_DENIED = "CAPABILITY_UNKNOWN_CLASS_DENIED"
CAPABILITY_RUNTIME_SESSION_REQUIRED = "CAPABILITY_RUNTIME_SESSION_REQUIRED"
CAPABILITY_CANDIDATE_CLAIMS_AUTHORITY = "CAPABILITY_CANDIDATE_CLAIMS_AUTHORITY"
CAPABILITY_SCHEMA_INVALID = "CAPABILITY_SCHEMA_INVALID"
CAPABILITY_DRY_RUN_ZERO_TRANSPORT = "CAPABILITY_DRY_RUN_ZERO_TRANSPORT"
CAPABILITY_DISPATCH_ALLOWED = "CAPABILITY_DISPATCH_ALLOWED"
CAPABILITY_DISPATCH_REJECTED = "CAPABILITY_DISPATCH_REJECTED"
CAPABILITY_CONSUMED = "CAPABILITY_CONSUMED"
CAPABILITY_RETIRED_NO_DISPATCH = "CAPABILITY_RETIRED_NO_DISPATCH"
CAPABILITY_PRE_DISPATCH_PHASE_REQUIRED = "CAPABILITY_PRE_DISPATCH_PHASE_REQUIRED"
CAPABILITY_TIMING_INVALID = "CAPABILITY_TIMING_INVALID"
CAPABILITY_ISSUED = "CAPABILITY_ISSUED"
CAPABILITY_EVALUATED = "CAPABILITY_EVALUATED"
CAPABILITY_EXECUTOR_DRY_RUN = "CAPABILITY_EXECUTOR_DRY_RUN"
CAPABILITY_RESOURCE_CONTEXT_REQUIRED = "CAPABILITY_RESOURCE_CONTEXT_REQUIRED"
CAPABILITY_RESOURCE_CONTEXT_MISMATCH = "CAPABILITY_RESOURCE_CONTEXT_MISMATCH"
CAPABILITY_EFFECT_FENCE_REQUIRED = "CAPABILITY_EFFECT_FENCE_REQUIRED"
CAPABILITY_EFFECT_FENCE_MISMATCH = "CAPABILITY_EFFECT_FENCE_MISMATCH"

_NAVIGATION_CONTROL_ALLOWLIST = frozenset(
    {
        "GO",
        "SAFE_PROMOTIONAL_BACK",
        "POPUP_DISMISS_X",
        "POPUP_DISMISS_CONFIRM",
        "RESET_CLOSE",
        "CLOSE",
    }
)
_NAVIGATION_FORBIDDEN_CONTROL_CLASSES = frozenset(
    {
        "CLAIM",
        "TRAIN",
        "UPGRADE",
        "BUY",
        "PURCHASE",
        "PREMIUM",
        "RESEARCH_FREE",
        "UNKNOWN",
    }
)
_NAV_FORBIDDEN_SEMANTIC_MARKERS = frozenset(
    {
        "CLAIM",
        "TRAIN",
        "UPGRADE",
        "PURCHASE",
        "PREMIUM",
        "BUY",
        "STRATEGIC",
        "RESEARCH_BIOENHANCER",
        "SUPPLY_DEPOT",
    }
)

_CAPABILITY_MINT_SEAL = object()
_AUDIT_EVENTS = frozenset(
    {
        CAPABILITY_ISSUED,
        CAPABILITY_EVALUATED,
        CAPABILITY_CONSUMED,
        CAPABILITY_DISPATCH_ALLOWED,
        CAPABILITY_DISPATCH_REJECTED,
        CAPABILITY_EXECUTOR_DRY_RUN,
    }
)
_AUDIT_DECISIONS = frozenset({"authorize", "deny", "allow", "dry_run"})
_AUDIT_DETAIL_KEYS = frozenset(
    {
        "action_class",
        "policy_reason_code",
        "consumed",
        "binding_matched",
        "executor_transport_calls",
    }
)


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
    OWNED_ITEM_NON_IDEMPOTENT = "owned_item_non_idempotent"


class PolicyDecision(str, Enum):
    AUTHORIZE = "authorize"
    DENY = "deny"
    GLOBAL_INPUT_LOCK = "global_input_lock"


@dataclass(frozen=True)
class ResourceAuthorizationContext:
    """Complete immutable identity for one reset-scoped Resource effect."""

    account_id: str
    server_id: str
    flow_id: str
    recurrence_class: str
    reset_identity_id: str
    objective_action_id: str
    target_variant: str
    effect_ordinal: int
    quantity: int
    product_policy_revision: str
    recurrence_policy_revision: str
    occurrence_id: str
    occurrence_key: str

    def __post_init__(self) -> None:
        for name in (
            "account_id",
            "server_id",
            "flow_id",
            "recurrence_class",
            "reset_identity_id",
            "objective_action_id",
            "target_variant",
            "product_policy_revision",
            "recurrence_policy_revision",
            "occurrence_id",
            "occurrence_key",
        ):
            object.__setattr__(self, name, _require_exact_str(getattr(self, name), name))
        if self.recurrence_class != "daily_reset":
            raise ValueError("Resource recurrence_class must be daily_reset")
        if self.objective_action_id != "use_resource_item":
            raise ValueError("Resource objective_action_id must be use_resource_item")
        if self.target_variant != "1k_food":
            raise ValueError("Resource target_variant must be 1k_food")
        if type(self.effect_ordinal) is not int or self.effect_ordinal != 1:
            raise ValueError("Resource effect_ordinal must be exactly one")
        if type(self.quantity) is not int or self.quantity != 1:
            raise ValueError("Resource quantity must be exactly one")
        if self.occurrence_key != self.expected_occurrence_key():
            raise ValueError("Resource occurrence_key does not match the complete canonical identity")

    def canonical_tuple(self) -> Tuple[Any, ...]:
        return (
            self.account_id,
            self.server_id,
            self.flow_id,
            self.recurrence_class,
            self.reset_identity_id,
            self.objective_action_id,
            self.target_variant,
            self.effect_ordinal,
        )

    def canonical_identity(self) -> str:
        return "|".join(str(item) for item in self.canonical_tuple())

    def expected_occurrence_key(self) -> str:
        encoded = json.dumps(
            list(self.canonical_tuple()),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return "occ:v1:" + hashlib.sha256(encoded).hexdigest()

    def as_dict(self) -> Dict[str, Any]:
        return {
            name: snapshot(getattr(self, name))
            for name in (
                "account_id",
                "server_id",
                "flow_id",
                "recurrence_class",
                "reset_identity_id",
                "objective_action_id",
                "target_variant",
                "effect_ordinal",
                "quantity",
                "product_policy_revision",
                "recurrence_policy_revision",
                "occurrence_id",
                "occurrence_key",
            )
        }

    def digest(self) -> str:
        encoded = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def canonical_digest(self) -> str:
        return self.digest()


@dataclass(frozen=True)
class EffectDispatchFence:
    """Opaque durable join across claim, controller, runtime, reservation, and frame."""

    occurrence_id: str
    attempt_id: str
    reservation_id: str
    claim_token_digest: str
    claim_epoch: int
    controller_token_digest: str
    controller_generation: int
    runtime_invocation_id: str
    reservation_state_revision: int
    immediate_before_sha256: str

    def __post_init__(self) -> None:
        for name in (
            "occurrence_id",
            "attempt_id",
            "reservation_id",
            "claim_token_digest",
            "controller_token_digest",
            "runtime_invocation_id",
            "immediate_before_sha256",
        ):
            object.__setattr__(self, name, _require_exact_str(getattr(self, name), name))
        for name in ("claim_token_digest", "controller_token_digest", "immediate_before_sha256"):
            _require_sha256(getattr(self, name), name)
        for name in ("claim_epoch", "controller_generation", "reservation_state_revision"):
            value = getattr(self, name)
            if type(value) is not int or value < 0 or (
                name in {"claim_epoch", "controller_generation"} and value < 1
            ):
                raise ValueError(f"{name} must be a valid non-negative integer")

    def as_dict(self) -> Dict[str, Any]:
        return {
            name: snapshot(getattr(self, name))
            for name in (
                "occurrence_id",
                "attempt_id",
                "reservation_id",
                "claim_token_digest",
                "claim_epoch",
                "controller_token_digest",
                "controller_generation",
                "runtime_invocation_id",
                "reservation_state_revision",
                "immediate_before_sha256",
            )
        }

    def digest(self) -> str:
        encoded = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


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
    runtime_session_id: Optional[str] = None
    resource_authorization_context: Optional[ResourceAuthorizationContext] = None
    effect_dispatch_fence: Optional[EffectDispatchFence] = None

    def with_observation(
        self, observation: Observation, monotonic_now: float, policy_phase: str = "pre_dispatch"
    ) -> "PolicyRequest":
        return replace(
            self,
            observation=observation,
            monotonic_now=monotonic_now,
            policy_phase=policy_phase,
        )

    @property
    def resource_authorization_context_digest(self) -> Optional[str]:
        return (
            self.resource_authorization_context.digest()
            if self.resource_authorization_context is not None
            else None
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


def _require_exact_str(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a non-empty whitespace-free str")
    return value


def _require_exact_bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{field_name} must be an exact bool")
    return value


def _require_exact_float(value: object, field_name: str) -> float:
    if type(value) is bool or type(value) not in (int, float):
        raise ValueError(f"{field_name} must be an exact finite number")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")) or result < 0:
        raise ValueError(f"{field_name} must be finite and non-negative")
    return result


def _require_exact_dimension(value: object, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} must be an exact positive int")
    return value


def _require_exact_roi(value: object, field_name: str) -> ROI:
    if type(value) is not tuple or len(value) != 4:
        raise ValueError(f"{field_name} must be an exact 4-tuple ROI")
    for item in value:
        if type(item) is not int:
            raise ValueError(f"{field_name} coordinates must be exact ints")
    x0, y0, x1, y1 = value
    if x0 >= x1 or y0 >= y1:
        raise ValueError(f"{field_name} is an invalid ROI")
    return (x0, y0, x1, y1)


def _require_action_class(value: object, field_name: str) -> ActionClass:
    if type(value) is not ActionClass:
        raise ValueError(f"{field_name} must be an ActionClass enum member")
    return value


def _require_sha256(value: object, field_name: str) -> str:
    text = _require_exact_str(value, field_name)
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ValueError(f"{field_name} must be a lowercase sha256 hex digest")
    return text


@dataclass(frozen=True)
class CapabilityAuthorityBinding:
    """Public, secret-free authority binding for a one-shot input capability."""

    task_id: str
    runtime_session_id: str
    action_class: ActionClass
    action_id: str
    action_key: str
    semantic_action: str
    target_identity: str
    capture_frame_sha256: str
    capture_completed_monotonic: float
    runtime_profile_id: str
    width: int
    height: int
    target_roi: ROI
    resource_authorization_context_digest: Optional[str] = None
    effect_dispatch_fence: Optional[EffectDispatchFence] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _require_exact_str(self.task_id, "task_id"))
        object.__setattr__(
            self, "runtime_session_id", _require_exact_str(self.runtime_session_id, "runtime_session_id")
        )
        object.__setattr__(self, "action_class", _require_action_class(self.action_class, "action_class"))
        object.__setattr__(self, "action_id", _require_exact_str(self.action_id, "action_id"))
        object.__setattr__(self, "action_key", _require_exact_str(self.action_key, "action_key"))
        object.__setattr__(
            self, "semantic_action", _require_exact_str(self.semantic_action, "semantic_action")
        )
        object.__setattr__(self, "target_identity", _require_exact_str(self.target_identity, "target_identity"))
        object.__setattr__(
            self, "capture_frame_sha256", _require_sha256(self.capture_frame_sha256, "capture_frame_sha256")
        )
        object.__setattr__(
            self,
            "capture_completed_monotonic",
            _require_exact_float(self.capture_completed_monotonic, "capture_completed_monotonic"),
        )
        object.__setattr__(
            self, "runtime_profile_id", _require_exact_str(self.runtime_profile_id, "runtime_profile_id")
        )
        object.__setattr__(self, "width", _require_exact_dimension(self.width, "width"))
        object.__setattr__(self, "height", _require_exact_dimension(self.height, "height"))
        roi = _require_exact_roi(self.target_roi, "target_roi")
        if roi[0] < 0 or roi[1] < 0 or roi[2] > self.width or roi[3] > self.height:
            raise ValueError("target_roi must be inside native frame geometry")
        object.__setattr__(self, "target_roi", roi)
        if self.resource_authorization_context_digest is not None:
            object.__setattr__(
                self,
                "resource_authorization_context_digest",
                _require_sha256(
                    self.resource_authorization_context_digest,
                    "resource_authorization_context_digest",
                ),
            )
        if self.effect_dispatch_fence is not None and type(self.effect_dispatch_fence) is not EffectDispatchFence:
            raise ValueError("effect_dispatch_fence must be an EffectDispatchFence or None")
        if self.action_class is ActionClass.OWNED_ITEM_NON_IDEMPOTENT:
            if self.resource_authorization_context_digest is None:
                raise ValueError(CAPABILITY_RESOURCE_CONTEXT_REQUIRED)
            if self.effect_dispatch_fence is None:
                raise ValueError(CAPABILITY_EFFECT_FENCE_REQUIRED)
        elif (
            self.resource_authorization_context_digest is not None
            or self.effect_dispatch_fence is not None
        ):
            raise ValueError("Resource authority fields are forbidden for non-Resource capabilities")

    def _canonical_items(self) -> Tuple[Tuple[str, Any], ...]:
        return (
            ("action_class", self.action_class.value),
            ("action_id", self.action_id),
            ("action_key", self.action_key),
            ("capture_completed_monotonic", self.capture_completed_monotonic),
            ("capture_frame_sha256", self.capture_frame_sha256),
            ("height", self.height),
            ("runtime_profile_id", self.runtime_profile_id),
            ("runtime_session_id", self.runtime_session_id),
            ("semantic_action", self.semantic_action),
            ("target_identity", self.target_identity),
            ("target_roi", self.target_roi),
            ("task_id", self.task_id),
            ("width", self.width),
            (
                "resource_authorization_context_digest",
                self.resource_authorization_context_digest,
            ),
            (
                "effect_dispatch_fence",
                self.effect_dispatch_fence.as_dict()
                if self.effect_dispatch_fence is not None
                else None,
            ),
        )

    def fingerprint(self) -> str:
        self.__post_init__()
        payload = dict(self._canonical_items())
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def as_audit_dict(self) -> Mapping[str, Any]:
        self.__post_init__()
        payload = dict(self._canonical_items())
        payload["binding_fingerprint"] = self.fingerprint()
        return MappingProxyType(dict(sorted(payload.items())))


@dataclass(frozen=True)
class CapabilityAuditRecord:
    """Deterministic immutable audit payload without capability secrets."""

    event: str
    reason_code: str
    decision: str
    binding_fingerprint: str
    capability_ref: str
    transport_calls: int
    dry_run: bool
    policy_authorized: bool
    transport_occurred: Optional[bool]
    details: Tuple[Tuple[str, object], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        event = _require_exact_str(self.event, "event")
        if event not in _AUDIT_EVENTS:
            raise ValueError("event is outside the closed capability audit schema")
        object.__setattr__(self, "event", event)
        object.__setattr__(self, "reason_code", _require_exact_str(self.reason_code, "reason_code"))
        decision = _require_exact_str(self.decision, "decision")
        if decision not in _AUDIT_DECISIONS:
            raise ValueError("decision is outside the closed capability audit schema")
        object.__setattr__(self, "decision", decision)
        object.__setattr__(
            self, "binding_fingerprint", _require_sha256(self.binding_fingerprint, "binding_fingerprint")
        )
        object.__setattr__(self, "capability_ref", _require_exact_str(self.capability_ref, "capability_ref"))
        if (
            not self.capability_ref.startswith("cap:")
            or any(
                marker in self.capability_ref.casefold()
                for marker in ("secret", "token", "password", "credential")
            )
        ):
            raise ValueError("capability_ref must be an explicitly redacted reference")
        if type(self.transport_calls) is not int or type(self.transport_calls) is bool or self.transport_calls < 0:
            raise ValueError("transport_calls must be a non-negative int")
        object.__setattr__(self, "dry_run", _require_exact_bool(self.dry_run, "dry_run"))
        object.__setattr__(
            self, "policy_authorized", _require_exact_bool(self.policy_authorized, "policy_authorized")
        )
        if self.transport_occurred is not None and type(self.transport_occurred) is not bool:
            raise ValueError("transport_occurred must be bool or None")
        if self.event != CAPABILITY_EXECUTOR_DRY_RUN and self.transport_occurred is not None:
            raise ValueError("policy-only capability audits cannot assert transport occurrence")
        if self.event == CAPABILITY_EXECUTOR_DRY_RUN:
            if not self.dry_run or self.transport_calls != 0 or self.transport_occurred is not False:
                raise ValueError("executor dry-run audit must prove exactly zero transport calls")
        elif self.dry_run or self.transport_calls != 0:
            raise ValueError("policy-only audits cannot certify dry-run or transport counts")
        if type(self.details) is not tuple:
            raise ValueError("details must be an exact immutable tuple")
        canonical = []
        seen = set()
        for entry in self.details:
            if type(entry) is not tuple or len(entry) != 2:
                raise ValueError("audit detail entries must be exact key/value tuples")
            key, value = entry
            key = _require_exact_str(key, "details.key")
            if key not in _AUDIT_DETAIL_KEYS or key in seen:
                raise ValueError("audit detail key is duplicate or outside the closed schema")
            if type(value) not in (str, int, bool) and value is not None:
                raise ValueError("audit detail values must be exact JSON scalars")
            if type(value) is str and (
                not value
                or "secret" in value.casefold()
                or "token" in value.casefold()
                or "api_key" in value.casefold()
                or "password" in value.casefold()
                or "credential" in value.casefold()
            ):
                raise ValueError("audit details cannot contain secret or token material")
            if key == "action_class" and (
                type(value) is not str or value not in {item.value for item in ActionClass}
            ):
                raise ValueError("action_class audit detail is invalid")
            if key == "policy_reason_code" and (
                type(value) is not str or not value or value != value.upper()
            ):
                raise ValueError("policy_reason_code audit detail is invalid")
            if key in {"consumed", "binding_matched"} and type(value) is not bool:
                raise ValueError(f"{key} audit detail must be an exact bool")
            if key == "executor_transport_calls" and (
                type(value) is not int or type(value) is bool or value != 0
            ):
                raise ValueError("executor_transport_calls audit detail must be exact zero")
            seen.add(key)
            canonical.append((key, value))
        object.__setattr__(self, "details", tuple(sorted(canonical)))

    def as_dict(self) -> Dict[str, Any]:
        self.__post_init__()
        return {
            "event": self.event,
            "reason_code": self.reason_code,
            "decision": self.decision,
            "binding_fingerprint": self.binding_fingerprint,
            "capability_ref": self.capability_ref,
            "transport_calls": self.transport_calls,
            "dry_run": self.dry_run,
            "policy_authorized": self.policy_authorized,
            "transport_occurred": self.transport_occurred,
            "details": {key: value for key, value in self.details},
            # Explicit honesty: policy allow never proves transport did not occur.
            "policy_allow_is_not_non_dispatch_proof": True,
        }


@dataclass(frozen=True)
class CapabilityIssueResult:
    authorized: bool
    reason_code: str
    policy_result: PolicyResult
    capability: Optional["InputCapability"]
    audit: CapabilityAuditRecord
    binding: Optional[CapabilityAuthorityBinding] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "authorized", _require_exact_bool(self.authorized, "authorized"))
        object.__setattr__(self, "reason_code", _require_exact_str(self.reason_code, "reason_code"))
        if type(self.policy_result) is not PolicyResult or type(self.audit) is not CapabilityAuditRecord:
            raise ValueError("issue result nested records must have exact public types")
        if self.reason_code != self.audit.reason_code or self.audit.event != CAPABILITY_ISSUED:
            raise ValueError("issue result and audit reason codes must match")
        if self.authorized:
            if (
                type(self.capability) is not InputCapability
                or type(self.binding) is not CapabilityAuthorityBinding
                or self.reason_code != CAPABILITY_AUTHORIZED
                or not self.policy_result.authorized
                or self.audit.decision != "authorize"
                or self.capability.consumed
                or self.capability.binding_fingerprint != self.binding.fingerprint()
                or self.audit.binding_fingerprint != self.binding.fingerprint()
                or self.audit.capability_ref != self.capability.redacted_ref
            ):
                raise ValueError("authorized issue result state is inconsistent")
        elif self.capability is not None or self.binding is not None or self.audit.decision != "deny":
            raise ValueError("denied issue result state is inconsistent")


@dataclass(frozen=True)
class CapabilityConsumeResult:
    consumed: bool
    binding_matched: bool
    reason_code: str
    audit: CapabilityAuditRecord
    allow_dispatch: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "consumed", _require_exact_bool(self.consumed, "consumed"))
        object.__setattr__(
            self, "binding_matched", _require_exact_bool(self.binding_matched, "binding_matched")
        )
        object.__setattr__(self, "allow_dispatch", _require_exact_bool(self.allow_dispatch, "allow_dispatch"))
        object.__setattr__(self, "reason_code", _require_exact_str(self.reason_code, "reason_code"))
        if type(self.audit) is not CapabilityAuditRecord or self.reason_code != self.audit.reason_code:
            raise ValueError("consume result nested audit is invalid or inconsistent")
        if self.audit.event not in {
            CAPABILITY_EVALUATED,
            CAPABILITY_CONSUMED,
            CAPABILITY_DISPATCH_ALLOWED,
            CAPABILITY_DISPATCH_REJECTED,
        }:
            raise ValueError("consume result audit event is invalid")
        if self.allow_dispatch and (
            not self.consumed
            or not self.binding_matched
            or self.reason_code != CAPABILITY_DISPATCH_ALLOWED
            or self.audit.event != CAPABILITY_DISPATCH_ALLOWED
            or self.audit.decision != "allow"
        ):
            raise ValueError("dispatch allow requires exact consumed and matched state")


class InputCapability:
    """Opaque, process-local, one-shot authority. Not publicly constructible or reusable."""

    __slots__ = (
        "_binding",
        "_issuer_handle",
        "_mint_marker",
        "_consumed",
        "_lock",
        "_redacted_ref",
        "__weakref__",
    )

    def __new__(cls, *args: Any, **kwargs: Any) -> "InputCapability":
        raise TypeError("InputCapability cannot be constructed publicly")

    @classmethod
    def _mint(
        cls,
        binding: CapabilityAuthorityBinding,
        issuer_handle: object,
        redacted_ref: str,
        mint_seal: object,
    ) -> "InputCapability":
        if mint_seal is not _CAPABILITY_MINT_SEAL:
            raise TypeError("InputCapability minting is policy-internal")
        if type(binding) is not CapabilityAuthorityBinding:
            raise ValueError("binding must be CapabilityAuthorityBinding")
        if type(issuer_handle) is not object:
            raise ValueError("issuer_handle must be an opaque process-local object")
        ref = _require_exact_str(redacted_ref, "redacted_ref")
        if not ref.startswith("cap:"):
            raise ValueError("redacted_ref must use the cap: prefix")
        obj = object.__new__(cls)
        object.__setattr__(obj, "_binding", binding)
        object.__setattr__(obj, "_issuer_handle", issuer_handle)
        object.__setattr__(obj, "_mint_marker", mint_seal)
        object.__setattr__(obj, "_consumed", False)
        object.__setattr__(obj, "_lock", threading.Lock())
        object.__setattr__(obj, "_redacted_ref", ref)
        return obj

    @property
    def consumed(self) -> bool:
        return getattr(self, "_consumed", False) is True

    @property
    def redacted_ref(self) -> str:
        return getattr(self, "_redacted_ref", "cap:invalid")

    @property
    def binding_fingerprint(self) -> str:
        binding = getattr(self, "_binding", None)
        return binding.fingerprint() if type(binding) is CapabilityAuthorityBinding else ("0" * 64)

    def binding_audit_dict(self) -> Mapping[str, Any]:
        return self._binding.as_audit_dict()

    def __repr__(self) -> str:
        return (
            f"InputCapability(ref={self.redacted_ref!r}, consumed={self.consumed}, "
            f"binding_fingerprint={self.binding_fingerprint!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()

    def __copy__(self) -> "InputCapability":
        raise TypeError("InputCapability cannot be copied")

    def __deepcopy__(self, memo: Any) -> "InputCapability":
        raise TypeError("InputCapability cannot be deep-copied")

    def __reduce__(self) -> Any:
        raise TypeError("InputCapability cannot be pickled")

    def __reduce_ex__(self, protocol: Any) -> Any:
        raise TypeError("InputCapability cannot be pickled")

    def __getstate__(self) -> Any:
        raise TypeError("InputCapability cannot be serialized")

    def __setstate__(self, state: Any) -> None:
        raise TypeError("InputCapability cannot be deserialized")

    def __iter__(self) -> Any:
        raise TypeError("InputCapability is not iterable")

    def to_json(self) -> None:
        raise TypeError("InputCapability cannot be JSON serialized")

    def as_dict(self) -> None:
        raise TypeError("InputCapability cannot expose token fields")


def navigation_capability_forbidden_reason(request: "PolicyRequest") -> Optional[str]:
    """Return a stable deny code when navigation authority would cover a consequential control."""
    if type(request.action_class) is not ActionClass:
        return CAPABILITY_UNKNOWN_CLASS_DENIED
    if request.action_class is ActionClass.SPEND_OR_STRATEGIC:
        return CAPABILITY_NAVIGATION_CONSEQUENTIAL_DENIED
    if request.action_class is ActionClass.ZERO_COST_CONSEQUENTIAL:
        return CAPABILITY_NAVIGATION_CONSEQUENTIAL_DENIED
    if request.action_class is not ActionClass.NAVIGATION_ONLY:
        return CAPABILITY_UNKNOWN_CLASS_DENIED
    control = request.observation.control_class
    if control is not None:
        if type(control) is not str or not control or control != control.strip():
            return CAPABILITY_NAVIGATION_CONSEQUENTIAL_DENIED
        normalized_control = control.upper().replace("-", "_").replace(" ", "_")
        # The historical Supply Depot radial label is visually "Claim Supply",
        # but this exact action identity is a navigation-only facility entry.
        # Keep the control classified as CLAIM for semantic honesty while
        # requiring the complete non-consequential route contract here.
        if normalized_control == "CLAIM":
            if not (
                control == "CLAIM"
                and request.semantic_action == "SUPPLY_DEPOT_RADIAL_NAVIGATION"
                and request.observation.target_identity
                == "supply-depot-claim-supply-navigation"
                and request.observation.source_state == "HOME_BASE"
                and request.observation.recognized is True
                and request.observation.consequence == "navigate_zero_cost"
                and request.observation.expected_postcondition
                == "SUPPLY_DEPOT_SCREEN"
            ):
                return CAPABILITY_NAVIGATION_CONSEQUENTIAL_DENIED
            return None
        if request.semantic_action == "SUPPLY_DEPOT_BUILDING_NAVIGATION":
            if not (
                control == "GO"
                and request.observation.target_identity
                == "home.building.supply_depot"
                and request.observation.source_state == "HOME_BASE"
                and request.observation.recognized is True
                and request.observation.consequence == "navigate_zero_cost"
                and request.observation.expected_postcondition
                == "SUPPLY_DEPOT_RADIAL"
            ):
                return CAPABILITY_NAVIGATION_CONSEQUENTIAL_DENIED
            return None
        if request.semantic_action == "SUPPLY_DEPOT_SAFE_EXIT":
            if not (
                control == "CLOSE"
                and request.observation.target_identity
                == "supply-depot-back-arrow"
                and request.observation.source_state == "SUPPLY_DEPOT_SCREEN"
                and request.observation.recognized is True
                and request.observation.consequence == "navigate_zero_cost"
                and request.observation.expected_postcondition == "HOME_BASE"
            ):
                return CAPABILITY_NAVIGATION_CONSEQUENTIAL_DENIED
            return None
        if (
            normalized_control in _NAVIGATION_FORBIDDEN_CONTROL_CLASSES
            or control not in _NAVIGATION_CONTROL_ALLOWLIST
        ):
            return CAPABILITY_NAVIGATION_CONSEQUENTIAL_DENIED
    if type(request.semantic_action) is not str:
        return CAPABILITY_SCHEMA_INVALID
    semantic = request.semantic_action.upper().replace("-", "_")
    for marker in _NAV_FORBIDDEN_SEMANTIC_MARKERS:
        if marker in semantic:
            return CAPABILITY_NAVIGATION_CONSEQUENTIAL_DENIED
    return None


def binding_from_request(request: "PolicyRequest") -> CapabilityAuthorityBinding:
    """Build a validated binding from a policy request, failing closed on partial authority."""
    session = request.runtime_session_id
    if session is None:
        raise ValueError(CAPABILITY_RUNTIME_SESSION_REQUIRED)
    obs = request.observation
    if obs.target_identity is None or obs.target_roi is None:
        raise ValueError(CAPABILITY_SCHEMA_INVALID)
    context = request.resource_authorization_context
    fence = request.effect_dispatch_fence
    context_digest = None
    if request.action_class is ActionClass.OWNED_ITEM_NON_IDEMPOTENT:
        if type(context) is not ResourceAuthorizationContext:
            raise ValueError(CAPABILITY_RESOURCE_CONTEXT_REQUIRED)
        if type(fence) is not EffectDispatchFence:
            raise ValueError(CAPABILITY_EFFECT_FENCE_REQUIRED)
        context_digest = context.digest()
    return CapabilityAuthorityBinding(
        task_id=request.task_id,
        runtime_session_id=session,
        action_class=request.action_class,
        action_id=request.action_id,
        action_key=request.action_key,
        semantic_action=request.semantic_action,
        target_identity=obs.target_identity,
        capture_frame_sha256=obs.frame_sha256,
        capture_completed_monotonic=obs.capture_completed_monotonic,
        runtime_profile_id=obs.runtime_profile_id,
        width=obs.width,
        height=obs.height,
        target_roi=obs.target_roi,
        resource_authorization_context_digest=context_digest,
        effect_dispatch_fence=fence,
    )


def compare_capability_binding(
    binding: CapabilityAuthorityBinding,
    request: "PolicyRequest",
) -> str:
    """Return a stable mismatch reason code, or CAPABILITY_AUTHORIZED when exact."""
    try:
        monotonic_now = _require_exact_float(request.monotonic_now, "monotonic_now")
        observation_limit = _require_exact_float(
            request.observation_max_age_seconds, "observation_max_age_seconds"
        )
        dispatch_limit = _require_exact_float(
            request.dispatch_max_age_seconds, "dispatch_max_age_seconds"
        )
    except (AttributeError, TypeError, ValueError):
        return CAPABILITY_TIMING_INVALID
    if request.policy_phase not in {"proposal", "pre_dispatch"}:
        return CAPABILITY_TIMING_INVALID
    try:
        _require_exact_str(request.task_id, "task_id")
        _require_exact_str(request.action_id, "action_id")
        _require_exact_str(request.action_key, "action_key")
        _require_exact_str(request.semantic_action, "semantic_action")
        if request.runtime_session_id is None:
            return CAPABILITY_RUNTIME_SESSION_REQUIRED
        _require_exact_str(request.runtime_session_id, "runtime_session_id")
        _require_action_class(request.action_class, "action_class")
        obs = request.observation
        _require_exact_str(obs.target_identity, "target_identity")
        _require_sha256(obs.frame_sha256, "frame_sha256")
        _require_exact_float(obs.capture_completed_monotonic, "capture_completed_monotonic")
        _require_exact_str(obs.runtime_profile_id, "runtime_profile_id")
        width = _require_exact_dimension(obs.width, "width")
        height = _require_exact_dimension(obs.height, "height")
        roi = _require_exact_roi(obs.target_roi, "target_roi")
        if roi[0] < 0 or roi[1] < 0 or roi[2] > width or roi[3] > height:
            return CAPABILITY_COORDINATE_MISMATCH
    except (AttributeError, TypeError, ValueError):
        return CAPABILITY_SCHEMA_INVALID
    if request.runtime_session_id != binding.runtime_session_id:
        return CAPABILITY_SESSION_MISMATCH
    if request.task_id != binding.task_id:
        return CAPABILITY_TASK_MISMATCH
    if request.action_id != binding.action_id:
        return CAPABILITY_ACTION_MISMATCH
    if request.action_key != binding.action_key:
        return CAPABILITY_ACTION_KEY_MISMATCH
    if request.semantic_action != binding.semantic_action:
        return CAPABILITY_SEMANTIC_ACTION_MISMATCH
    if request.action_class is not binding.action_class:
        return CAPABILITY_ACTION_CLASS_MISMATCH
    if request.action_class is ActionClass.OWNED_ITEM_NON_IDEMPOTENT:
        context = request.resource_authorization_context
        fence = request.effect_dispatch_fence
        if type(context) is not ResourceAuthorizationContext:
            return CAPABILITY_RESOURCE_CONTEXT_REQUIRED
        if type(fence) is not EffectDispatchFence:
            return CAPABILITY_EFFECT_FENCE_REQUIRED
        if context.digest() != binding.resource_authorization_context_digest:
            return CAPABILITY_RESOURCE_CONTEXT_MISMATCH
        if fence != binding.effect_dispatch_fence:
            return CAPABILITY_EFFECT_FENCE_MISMATCH
    if binding.action_class is ActionClass.NAVIGATION_ONLY:
        forbidden = navigation_capability_forbidden_reason(request)
        if forbidden is not None:
            return forbidden
    if obs.target_identity != binding.target_identity:
        return CAPABILITY_TARGET_MISMATCH
    if obs.runtime_profile_id != binding.runtime_profile_id:
        return CAPABILITY_PROFILE_MISMATCH
    if obs.width != binding.width or obs.height != binding.height:
        return CAPABILITY_GEOMETRY_MISMATCH
    if obs.target_roi is None or obs.target_roi != binding.target_roi:
        return CAPABILITY_COORDINATE_MISMATCH
    digest_match = obs.frame_sha256 == binding.capture_frame_sha256
    mono_match = obs.capture_completed_monotonic == binding.capture_completed_monotonic
    if digest_match and not mono_match:
        return CAPABILITY_DIGEST_ONLY_REJECTED
    if mono_match and not digest_match:
        return CAPABILITY_CAPTURE_MISMATCH
    if not digest_match or not mono_match:
        return CAPABILITY_CAPTURE_MISMATCH
    age = monotonic_now - obs.capture_completed_monotonic
    limit = (
        dispatch_limit
        if request.policy_phase == "pre_dispatch"
        else observation_limit
    )
    if age < 0 or age > limit:
        return CAPABILITY_STALE_OBSERVATION
    return CAPABILITY_AUTHORIZED


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
    resource_authorization_context: Optional[ResourceAuthorizationContext] = None

    @property
    def resource_authorization_context_digest(self) -> Optional[str]:
        return (
            self.resource_authorization_context.digest()
            if self.resource_authorization_context is not None
            else None
        )


@dataclass(frozen=True)
class TransportResult:
    dispatched: bool
    transport_code: str
    detail: str = ""


def snapshot(value: Any) -> Any:
    """Return a JSON-safe deterministic representation of a model value."""
    if isinstance(value, InputCapability):
        raise TypeError("InputCapability cannot be snapshotted or serialized")
    if isinstance(value, ResourceAuthorizationContext):
        result = value.as_dict()
        result["canonical_digest"] = value.digest()
        return result
    if isinstance(value, EffectDispatchFence):
        result = value.as_dict()
        result["fence_digest"] = value.digest()
        return result
    if isinstance(value, CapabilityAuditRecord):
        return value.as_dict()
    if hasattr(value, "__dataclass_fields__"):
        # Recurse field-by-field instead of dataclasses.asdict: immutable
        # MappingProxyType values are intentionally not deepcopy-able.
        return {
            item.name: snapshot(getattr(value, item.name))
            for item in dataclass_fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [snapshot(item) for item in value]
    if isinstance(value, list):
        return [snapshot(item) for item in value]
    if isinstance(value, dict):
        return {str(key): snapshot(item) for key, item in value.items()}
    if isinstance(value, MappingProxyType):
        return {str(key): snapshot(item) for key, item in value.items()}
    return value
