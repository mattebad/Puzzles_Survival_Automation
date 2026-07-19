"""Single central authorization boundary for supervised R1 input."""

from __future__ import annotations

import math
import re
import threading
import uuid
from dataclasses import dataclass, replace
from typing import Any, List, Optional, Tuple

from .models import (
    CAPABILITY_ALREADY_CONSUMED,
    CAPABILITY_AUTHORIZED,
    CAPABILITY_CANDIDATE_CLAIMS_AUTHORITY,
    CAPABILITY_CONSUMED,
    CAPABILITY_DISPATCH_ALLOWED,
    CAPABILITY_DISPATCH_REJECTED,
    CAPABILITY_DRY_RUN_ZERO_TRANSPORT,
    CAPABILITY_EVALUATED,
    CAPABILITY_FORGERY,
    CAPABILITY_ISSUED,
    CAPABILITY_PRE_DISPATCH_PHASE_REQUIRED,
    CAPABILITY_RETIRED_NO_DISPATCH,
    CAPABILITY_RUNTIME_SESSION_REQUIRED,
    CAPABILITY_SCHEMA_INVALID,
    CAPABILITY_TIMING_INVALID,
    CAPABILITY_UNKNOWN_CLASS_DENIED,
    _CAPABILITY_MINT_SEAL,
    ActionClass,
    CapabilityAuditRecord,
    CapabilityAuthorityBinding,
    CapabilityConsumeResult,
    CapabilityIssueResult,
    InputCapability,
    Observation,
    PolicyDecision,
    PolicyRequest,
    PolicyResult,
    binding_from_request,
    compare_capability_binding,
    navigation_capability_forbidden_reason,
    snapshot,
)
from .promotional import (
    MAX_PROMOTIONAL_BACKS,
    PROMOTIONAL_BACK_GEOMETRY,
    PROMOTIONAL_BACK_TARGET_ROI,
    PROMOTIONAL_STATE,
    SAFE_PROMOTIONAL_BACK,
)

SHA256 = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_SIZE = (800, 1280)
DEFAULT_SUPERVISED_TASKS = frozenset({"MVP-QUEST-TO-CLAIM"})
ALLOWED_R1_CONSEQUENCES = frozenset(
    {
        "claim_zero_cost_reward",
        "alliance_help_zero_cost",
        "praise_zero_cost",
        "supply_depot_free_claim",
        "bioenhancer_research_free",
        "navigate_zero_cost",
    }
)


def _exact_string(value: object, *, optional: bool = False) -> bool:
    if optional:
        return value is None or (
            type(value) is str
            and value == value.strip()
            and (not value or not any(character.isspace() for character in value))
        )
    return (
        type(value) is str
        and bool(value)
        and value == value.strip()
        and not any(character.isspace() for character in value)
    )


def _exact_bool(value: object) -> bool:
    return type(value) is bool


def _exact_number(value: object, *, nonnegative: bool = False) -> bool:
    return (
        type(value) in (int, float)
        and type(value) is not bool
        and math.isfinite(float(value))
        and (not nonnegative or float(value) >= 0)
    )


def _exact_roi(value: object, *, optional: bool = False) -> bool:
    if optional and value is None:
        return True
    return (
        type(value) is tuple
        and len(value) == 4
        and all(type(item) is int for item in value)
    )


def _string_tuple(value: object) -> bool:
    return type(value) is tuple and all(_exact_string(item) for item in value)


def _request_schema_valid(request: object) -> bool:
    """Validate the exact public request/observation shape without coercion."""
    if type(request) is not PolicyRequest:
        return False
    try:
        observation = request.observation
        if type(observation) is not Observation:
            return False
        request_strings = (
            request.action_id,
            request.action_key,
            request.task_id,
            request.task_mode,
            request.semantic_action,
            request.expected_runtime_profile_id,
            request.policy_phase,
        )
        if not all(_exact_string(value) for value in request_strings):
            return False
        if not _exact_string(request.lease_owner, optional=True):
            return False
        if not _exact_string(request.game_day_id, optional=True):
            return False
        if not _exact_string(request.runtime_session_id, optional=True):
            return False
        if not all(
            _exact_string(value, optional=True)
            for value in (
                request.action_kind,
                request.subject,
                request.resource_or_currency,
            )
        ):
            return False
        if not all(
            _exact_bool(value)
            for value in (
                request.lease_valid,
                request.unresolved_action,
                request.duplicate_action_key,
                request.free_only,
            )
        ):
            return False
        if type(request.promotional_back_count) is not int or request.promotional_back_count < 0:
            return False
        if request.maximum_cost is not None and not _exact_number(
            request.maximum_cost, nonnegative=True
        ):
            return False
        if not all(
            _string_tuple(value)
            for value in (
                request.allowed_confirmation_dialogs,
                request.semantic_preconditions,
                request.semantic_postconditions,
            )
        ):
            return False

        if not all(
            _exact_string(value)
            for value in (
                observation.frame_sha256,
                observation.runtime_profile_id,
                observation.source_state,
                observation.overlay_state,
            )
        ):
            return False
        if type(observation.width) is not int or type(observation.height) is not int:
            return False
        if observation.width <= 0 or observation.height <= 0:
            return False
        if not all(
            _exact_bool(value)
            for value in (
                observation.valid_png,
                observation.corrupt,
                observation.black,
                observation.recognized,
                observation.clipped,
                observation.ambiguous,
                observation.ocr_reused,
                observation.target_isolated,
                observation.forbidden_region_intersects_target,
                observation.package_foreground,
                observation.os_surface,
                observation.hard_stop_detected,
            )
        ):
            return False
        if not all(
            _exact_string(value, optional=True)
            for value in (
                observation.target_identity,
                observation.control_class,
                observation.consequence,
                observation.cost_type,
                observation.expected_postcondition,
                observation.ocr_result_frame_sha256,
                observation.source_family,
                observation.arrow_geometry,
            )
        ):
            return False
        if not _exact_roi(observation.target_roi, optional=True):
            return False
        if observation.cost_amount is not None and not _exact_number(
            observation.cost_amount, nonnegative=True
        ):
            return False
        if observation.quantity is not None and (
            type(observation.quantity) is not int or observation.quantity <= 0
        ):
            return False
        if observation.ocr_result_capture_completed_monotonic is not None and not _exact_number(
            observation.ocr_result_capture_completed_monotonic, nonnegative=True
        ):
            return False
        if not _string_tuple(observation.evidence_refs):
            return False
        if type(observation.critical_roi_hashes) is not tuple or any(
            type(entry) is not tuple
            or len(entry) != 2
            or not _exact_string(entry[0])
            or not _exact_string(entry[1])
            for entry in observation.critical_roi_hashes
        ):
            return False
        if type(observation.forbidden_regions) is not tuple or any(
            type(entry) is not tuple
            or len(entry) != 2
            or not _exact_string(entry[0])
            or not _exact_roi(entry[1])
            for entry in observation.forbidden_regions
        ):
            return False
    except (AttributeError, TypeError, ValueError):
        return False
    return True


@dataclass(frozen=True)
class _CapabilityRegistryRecord:
    capability: InputCapability
    binding: CapabilityAuthorityBinding
    binding_fingerprint: str
    issuer_handle: object
    redacted_ref: str
    mint_marker: object
    capability_lock: object
    consumed: bool = False


class CentralPolicy:
    """Fail closed unless every supervised zero-cost condition is explicit."""

    def __init__(self, supervised_tasks=None):
        selected = DEFAULT_SUPERVISED_TASKS if supervised_tasks is None else supervised_tasks
        self.supervised_tasks = frozenset(selected)
        self._issuer_handle = object()
        self._capability_audits: List[CapabilityAuditRecord] = []
        self._capability_lock = threading.RLock()
        self._capability_registry: dict[InputCapability, _CapabilityRegistryRecord] = {}

    def evaluate(self, request: PolicyRequest) -> PolicyResult:
        if not _request_schema_valid(request):
            return self._schema_policy_result(request)
        try:
            decision, code, reason = self._decide(request)
            request_snapshot = snapshot(request)
        except (AttributeError, TypeError, ValueError):
            return self._schema_policy_result(request)
        return PolicyResult(
            decision=decision,
            reason_code=code,
            reason=reason,
            evaluated_at=request.monotonic_now,
            request_snapshot=request_snapshot,
        )

    @staticmethod
    def _schema_policy_result(request: object) -> PolicyResult:
        evaluated_at = 0.0
        try:
            candidate = getattr(request, "monotonic_now")
            if _exact_number(candidate, nonnegative=True):
                evaluated_at = float(candidate)
        except (AttributeError, TypeError, ValueError):
            pass
        return PolicyResult(
            decision=PolicyDecision.DENY,
            reason_code=CAPABILITY_SCHEMA_INVALID,
            reason="public policy request or observation schema is malformed",
            evaluated_at=evaluated_at,
            request_snapshot={
                "schema_valid": False,
                "request_type": type(request).__name__,
            },
        )

    @property
    def capability_audits(self) -> Tuple[CapabilityAuditRecord, ...]:
        with self._capability_lock:
            return tuple(self._capability_audits)

    def _record_audit(self, audit: CapabilityAuditRecord) -> CapabilityAuditRecord:
        with self._capability_lock:
            self._capability_audits.append(audit)
        return audit

    def _audit(
        self,
        *,
        event: str,
        reason_code: str,
        decision: str,
        binding: Optional[CapabilityAuthorityBinding],
        capability_ref: str,
        policy_authorized: bool = False,
        details: Tuple[Tuple[str, object], ...] = (),
    ) -> CapabilityAuditRecord:
        fingerprint = binding.fingerprint() if binding is not None else ("0" * 64)
        audit = CapabilityAuditRecord(
            event=event,
            reason_code=reason_code,
            decision=decision,
            binding_fingerprint=fingerprint,
            capability_ref=capability_ref,
            transport_calls=0,
            dry_run=False,
            policy_authorized=policy_authorized,
            transport_occurred=None,
            details=details,
        )
        return self._record_audit(audit)

    @staticmethod
    def _candidate_claims_authority(candidate: Any) -> bool:
        """Safe-exit and similar candidates must never mint or imply policy authority."""
        if candidate is None:
            return False
        for attr in ("authorize_dispatch", "safe_exit_authorize_dispatch", "capability_grant", "policy_grant"):
            if not hasattr(candidate, attr):
                continue
            value = getattr(candidate, attr)
            if callable(value):
                try:
                    value = value()
                except TypeError:
                    continue
            if value not in (False, None):
                return True
        return False

    def issue_capability(
        self,
        request: PolicyRequest,
        *,
        non_authorizing_candidate: Any = None,
    ) -> CapabilityIssueResult:
        """Evaluate policy and mint a one-shot capability only when fully authorized."""
        policy_result = self.evaluate(request)
        if policy_result.reason_code == CAPABILITY_SCHEMA_INVALID:
            audit = self._audit(
                event=CAPABILITY_ISSUED,
                reason_code=CAPABILITY_SCHEMA_INVALID,
                decision="deny",
                binding=None,
                capability_ref="cap:none",
                policy_authorized=False,
            )
            return CapabilityIssueResult(
                authorized=False,
                reason_code=CAPABILITY_SCHEMA_INVALID,
                policy_result=policy_result,
                capability=None,
                audit=audit,
            )
        if self._candidate_claims_authority(non_authorizing_candidate):
            policy_result = PolicyResult(
                decision=PolicyDecision.DENY,
                reason_code=CAPABILITY_CANDIDATE_CLAIMS_AUTHORITY,
                reason="non-authorizing candidate claimed dispatch or capability authority",
                evaluated_at=request.monotonic_now,
                request_snapshot=snapshot(request),
            )
            audit = self._audit(
                event=CAPABILITY_ISSUED,
                reason_code=CAPABILITY_CANDIDATE_CLAIMS_AUTHORITY,
                decision="deny",
                binding=None,
                capability_ref="cap:none",
                policy_authorized=False,
            )
            return CapabilityIssueResult(
                authorized=False,
                reason_code=CAPABILITY_CANDIDATE_CLAIMS_AUTHORITY,
                policy_result=policy_result,
                capability=None,
                audit=audit,
            )

        if (
            request.runtime_session_id is None
            or type(request.runtime_session_id) is not str
            or not request.runtime_session_id
        ):
            audit = self._audit(
                event=CAPABILITY_ISSUED,
                reason_code=CAPABILITY_RUNTIME_SESSION_REQUIRED,
                decision="deny",
                binding=None,
                capability_ref="cap:none",
                policy_authorized=False,
            )
            return CapabilityIssueResult(
                authorized=False,
                reason_code=CAPABILITY_RUNTIME_SESSION_REQUIRED,
                policy_result=policy_result,
                capability=None,
                audit=audit,
            )

        if type(request.action_class) is not ActionClass:
            audit = self._audit(
                event=CAPABILITY_ISSUED,
                reason_code=CAPABILITY_UNKNOWN_CLASS_DENIED,
                decision="deny",
                binding=None,
                capability_ref="cap:none",
                policy_authorized=False,
            )
            return CapabilityIssueResult(
                authorized=False,
                reason_code=CAPABILITY_UNKNOWN_CLASS_DENIED,
                policy_result=policy_result,
                capability=None,
                audit=audit,
            )

        if request.action_class is ActionClass.NAVIGATION_ONLY:
            forbidden = navigation_capability_forbidden_reason(request)
            if forbidden is not None:
                audit = self._audit(
                    event=CAPABILITY_ISSUED,
                    reason_code=forbidden,
                    decision="deny",
                    binding=None,
                    capability_ref="cap:none",
                    policy_authorized=False,
                    details=(("policy_reason_code", policy_result.reason_code),),
                )
                return CapabilityIssueResult(
                    authorized=False,
                    reason_code=forbidden,
                    policy_result=policy_result,
                    capability=None,
                    audit=audit,
                )

        try:
            binding = binding_from_request(request)
        except (AttributeError, TypeError, ValueError) as exc:
            code = str(exc) if str(exc).startswith("CAPABILITY_") else CAPABILITY_SCHEMA_INVALID
            audit = self._audit(
                event=CAPABILITY_ISSUED,
                reason_code=code,
                decision="deny",
                binding=None,
                capability_ref="cap:none",
                policy_authorized=True,
            )
            return CapabilityIssueResult(
                authorized=False,
                reason_code=code,
                policy_result=policy_result,
                capability=None,
                audit=audit,
            )

        if not policy_result.authorized:
            audit = self._audit(
                event=CAPABILITY_ISSUED,
                reason_code=policy_result.reason_code,
                decision="deny",
                binding=binding,
                capability_ref="cap:none",
                policy_authorized=False,
            )
            return CapabilityIssueResult(
                authorized=False,
                reason_code=policy_result.reason_code,
                policy_result=policy_result,
                capability=None,
                audit=audit,
            )

        redacted_ref = "cap:" + uuid.uuid4().hex
        capability = InputCapability._mint(
            binding,
            self._issuer_handle,
            redacted_ref,
            _CAPABILITY_MINT_SEAL,
        )
        registry_record = _CapabilityRegistryRecord(
            capability=capability,
            binding=binding,
            binding_fingerprint=binding.fingerprint(),
            issuer_handle=self._issuer_handle,
            redacted_ref=redacted_ref,
            mint_marker=_CAPABILITY_MINT_SEAL,
            capability_lock=getattr(capability, "_lock"),
        )
        with self._capability_lock:
            self._capability_registry[capability] = registry_record
        audit = self._audit(
            event=CAPABILITY_ISSUED,
            reason_code=CAPABILITY_AUTHORIZED,
            decision="authorize",
            binding=binding,
            capability_ref=capability.redacted_ref,
            policy_authorized=True,
            details=(("action_class", binding.action_class.value),),
        )
        return CapabilityIssueResult(
            authorized=True,
            reason_code=CAPABILITY_AUTHORIZED,
            policy_result=policy_result,
            capability=capability,
            audit=audit,
            binding=binding,
        )

    def evaluate_capability(
        self,
        capability: InputCapability,
        request: PolicyRequest,
    ) -> CapabilityConsumeResult:
        """Evaluate binding without consuming. Forgery and consumed tokens fail closed."""
        with self._capability_lock:
            record = self._registered_integrity_record(capability)
            if record is None:
                return self._forgery_result(CAPABILITY_EVALUATED)
            if record.consumed:
                audit = self._audit(
                    event=CAPABILITY_EVALUATED,
                    reason_code=CAPABILITY_ALREADY_CONSUMED,
                    decision="deny",
                    binding=record.binding,
                    capability_ref=record.redacted_ref,
                    policy_authorized=False,
                )
                return CapabilityConsumeResult(
                    consumed=True,
                    binding_matched=False,
                    reason_code=CAPABILITY_ALREADY_CONSUMED,
                    audit=audit,
                    allow_dispatch=False,
                )
            match_code = compare_capability_binding(record.binding, request)
            matched = match_code == CAPABILITY_AUTHORIZED
            policy_result = self.evaluate(request)
            fully_authorized = matched and policy_result.authorized
            reason = (
                CAPABILITY_SCHEMA_INVALID
                if policy_result.reason_code == CAPABILITY_SCHEMA_INVALID
                else (
                    match_code
                    if not matched
                    else (
                        CAPABILITY_AUTHORIZED
                        if policy_result.authorized
                        else policy_result.reason_code
                    )
                )
            )
            audit = self._audit(
                event=CAPABILITY_EVALUATED,
                reason_code=reason,
                decision="authorize" if fully_authorized else "deny",
                binding=record.binding,
                capability_ref=record.redacted_ref,
                policy_authorized=policy_result.authorized,
            )
            return CapabilityConsumeResult(
                consumed=False,
                binding_matched=matched,
                reason_code=reason,
                audit=audit,
                allow_dispatch=False,
            )

    def consume_capability(
        self,
        capability: InputCapability,
        request: PolicyRequest,
    ) -> CapabilityConsumeResult:
        """Atomically consume one-shot capability after final revalidation."""
        with self._capability_lock:
            record = self._registered_integrity_record(capability)
            if record is None:
                return self._forgery_result(CAPABILITY_CONSUMED)
            if record.consumed:
                audit = self._audit(
                    event=CAPABILITY_CONSUMED,
                    reason_code=CAPABILITY_ALREADY_CONSUMED,
                    decision="deny",
                    binding=record.binding,
                    capability_ref=record.redacted_ref,
                    policy_authorized=False,
                )
                return CapabilityConsumeResult(
                    consumed=True,
                    binding_matched=False,
                    reason_code=CAPABILITY_ALREADY_CONSUMED,
                    audit=audit,
                    allow_dispatch=False,
                )

            object.__setattr__(capability, "_consumed", True)
            self._capability_registry[capability] = replace(record, consumed=True)
            phase_valid = (
                type(request) is PolicyRequest
                and getattr(request, "policy_phase", None) == "pre_dispatch"
            )
            match_code = compare_capability_binding(record.binding, request)
            matched = match_code == CAPABILITY_AUTHORIZED
            policy_result = self.evaluate(request)
            policy_authorized = policy_result.authorized
            allow_dispatch = phase_valid and matched and policy_authorized
            if policy_result.reason_code == CAPABILITY_SCHEMA_INVALID:
                reason = CAPABILITY_SCHEMA_INVALID
            elif not phase_valid:
                reason = CAPABILITY_PRE_DISPATCH_PHASE_REQUIRED
            elif not policy_authorized:
                reason = policy_result.reason_code
            elif not matched:
                reason = match_code
            else:
                reason = CAPABILITY_DISPATCH_ALLOWED
            event = CAPABILITY_DISPATCH_ALLOWED if allow_dispatch else CAPABILITY_DISPATCH_REJECTED
            audit = self._audit(
                event=event,
                reason_code=reason,
                decision="allow" if allow_dispatch else "deny",
                binding=record.binding,
                capability_ref=record.redacted_ref,
                policy_authorized=policy_authorized,
                details=(("binding_matched", matched), ("consumed", True)),
            )
            return CapabilityConsumeResult(
                consumed=True,
                binding_matched=matched,
                reason_code=reason,
                audit=audit,
                allow_dispatch=allow_dispatch,
            )

    def retire_capability(
        self,
        capability: InputCapability,
        request: PolicyRequest,
    ) -> CapabilityConsumeResult:
        """Consume capability without granting dispatch authority on a terminal path."""
        with self._capability_lock:
            record = self._registered_integrity_record(capability)
            if record is None:
                return self._forgery_result(CAPABILITY_CONSUMED)
            if record.consumed:
                audit = self._audit(
                    event=CAPABILITY_CONSUMED,
                    reason_code=CAPABILITY_ALREADY_CONSUMED,
                    decision="deny",
                    binding=record.binding,
                    capability_ref=record.redacted_ref,
                    policy_authorized=False,
                )
                return CapabilityConsumeResult(
                    consumed=True,
                    binding_matched=False,
                    reason_code=CAPABILITY_ALREADY_CONSUMED,
                    audit=audit,
                    allow_dispatch=False,
                )
            object.__setattr__(capability, "_consumed", True)
            self._capability_registry[capability] = replace(record, consumed=True)
            match_code = compare_capability_binding(record.binding, request)
            matched = match_code == CAPABILITY_AUTHORIZED
            retirement_reason = (
                CAPABILITY_RETIRED_NO_DISPATCH if matched else match_code
            )
            audit = self._audit(
                event=CAPABILITY_CONSUMED,
                reason_code=retirement_reason,
                decision="deny",
                binding=record.binding,
                capability_ref=record.redacted_ref,
                policy_authorized=False,
                details=(("binding_matched", matched), ("consumed", True)),
            )
            return CapabilityConsumeResult(
                consumed=True,
                binding_matched=matched,
                reason_code=retirement_reason,
                audit=audit,
                allow_dispatch=False,
            )

    def _registered_integrity_record(
        self, capability: object
    ) -> Optional[_CapabilityRegistryRecord]:
        """Return the exact registered record only when every object field is intact."""
        if type(capability) is not InputCapability:
            return None
        record = self._capability_registry.get(capability)
        if record is None or record.capability is not capability:
            return None
        try:
            binding = getattr(capability, "_binding")
            issuer_handle = getattr(capability, "_issuer_handle")
            mint_marker = getattr(capability, "_mint_marker")
            redacted_ref = getattr(capability, "_redacted_ref")
            consumed = getattr(capability, "_consumed")
            capability_lock = getattr(capability, "_lock")
            fingerprint = binding.fingerprint()
        except (AttributeError, TypeError, ValueError):
            return None
        if (
            binding is not record.binding
            or type(binding) is not CapabilityAuthorityBinding
            or fingerprint != record.binding_fingerprint
            or issuer_handle is not record.issuer_handle
            or issuer_handle is not self._issuer_handle
            or mint_marker is not record.mint_marker
            or mint_marker is not _CAPABILITY_MINT_SEAL
            or redacted_ref != record.redacted_ref
            or type(consumed) is not bool
            or consumed is not record.consumed
            or capability_lock is not record.capability_lock
        ):
            return None
        return record

    def _forgery_result(self, event: str) -> CapabilityConsumeResult:
        audit = self._audit(
            event=event,
            reason_code=CAPABILITY_FORGERY,
            decision="deny",
            binding=None,
            capability_ref="cap:forged",
            policy_authorized=False,
        )
        return CapabilityConsumeResult(
            consumed=False,
            binding_matched=False,
            reason_code=CAPABILITY_FORGERY,
            audit=audit,
            allow_dispatch=False,
        )

    def _decide(self, req: PolicyRequest) -> Tuple[PolicyDecision, str, str]:
        lock = PolicyDecision.GLOBAL_INPUT_LOCK
        deny = PolicyDecision.DENY
        if type(req.action_class) is not ActionClass:
            return deny, CAPABILITY_UNKNOWN_CLASS_DENIED, "action class must be an exact ActionClass"
        try:
            obs = req.observation
            timing_values = (
                req.monotonic_now,
                req.observation_max_age_seconds,
                req.dispatch_max_age_seconds,
                obs.capture_completed_monotonic,
            )
            if (
                type(req.policy_phase) is not str
                or req.policy_phase not in {"proposal", "pre_dispatch"}
                or any(
                    type(value) not in (int, float)
                    or type(value) is bool
                    or not math.isfinite(float(value))
                    or float(value) < 0
                    for value in timing_values
                )
            ):
                return deny, CAPABILITY_TIMING_INVALID, "policy timing fields must be exact finite nonnegative numbers"
        except (AttributeError, TypeError, ValueError):
            return deny, CAPABILITY_TIMING_INVALID, "policy timing fields are malformed"

        if obs.runtime_profile_id != req.expected_runtime_profile_id:
            return lock, "PROFILE_MISMATCH", "runtime profile does not match the locked profile"
        if not obs.valid_png or obs.corrupt or obs.black or (obs.width, obs.height) != EXPECTED_SIZE:
            return lock, "INVALID_FRAME", "frame is corrupt, black, invalid, or profile-sized incorrectly"
        if req.unresolved_action:
            return lock, "UNRESOLVED_ACTION", "an unresolved consequential action blocks input"
        if not req.lease_valid or not req.lease_owner:
            return deny, "LEASE_REQUIRED", "an exclusive valid controller lease is required"
        if req.duplicate_action_key:
            return deny, "DUPLICATE_ACTION_KEY", "the deterministic action key already exists"
        if req.task_mode != "supervised_validation":
            return deny, "TASK_MODE_DENIED", "task is not enabled for supervised validation"
        if req.task_id not in self.supervised_tasks:
            return deny, "TASK_NOT_ENABLED", "task identity is not explicitly enabled for supervised validation"
        age = req.monotonic_now - obs.capture_completed_monotonic
        limit = (
            req.dispatch_max_age_seconds
            if req.policy_phase == "pre_dispatch"
            else req.observation_max_age_seconds
        )
        if age < 0 or age > limit:
            return deny, "STALE_FRAME", "source frame is stale or timestamped in the future"
        if not SHA256.fullmatch(obs.frame_sha256):
            return deny, "INVALID_FRAME_HASH", "source frame hash is missing or malformed"
        if obs.ocr_result_frame_sha256 is not None and not SHA256.fullmatch(obs.ocr_result_frame_sha256):
            return deny, "INVALID_PERCEPTION_BINDING", "OCR result frame binding is malformed"
        if obs.ocr_result_frame_sha256 is not None and obs.ocr_result_capture_completed_monotonic is None:
            return deny, "INVALID_PERCEPTION_BINDING", "OCR result capture binding is missing"
        if not obs.ocr_reused and obs.ocr_result_frame_sha256 is not None and (
            obs.ocr_result_frame_sha256 != obs.frame_sha256
            or obs.ocr_result_capture_completed_monotonic != obs.capture_completed_monotonic
        ):
            return deny, "INVALID_PERCEPTION_BINDING", "fresh OCR must bind to the immediate frame and capture"
        if obs.ocr_reused and (
            obs.ocr_result_capture_completed_monotonic is None
            or obs.ocr_result_capture_completed_monotonic >= obs.capture_completed_monotonic
        ):
            return deny, "INVALID_PERCEPTION_BINDING", "OCR reuse must identify an earlier completed capture"
        if any(not name or not SHA256.fullmatch(digest) for name, digest in obs.critical_roi_hashes):
            return deny, "INVALID_PERCEPTION_BINDING", "critical ROI bindings are missing or malformed"
        if req.action_class == ActionClass.SPEND_OR_STRATEGIC:
            return deny, "SPEND_OR_STRATEGIC_DISABLED", "spend and strategic actions remain disabled"
        if req.semantic_action == SAFE_PROMOTIONAL_BACK:
            return self._decide_promotional_back(req)
        if not obs.recognized or not obs.source_state or obs.source_state == "UNKNOWN":
            return deny, "UNKNOWN_SOURCE", "source state is not positively recognized"
        if obs.overlay_state not in ("none", "none_observed"):
            if not (
                req.semantic_action == "DISMISS_RESET_POPUP"
                and obs.overlay_state == "known_reset_popup"
            ) and not (
                req.semantic_action == "DISMISS_ALLIANCE_FORT_WAVE"
                and obs.overlay_state == "alliance_fort_wave_alert"
            ):
                return deny, "UNKNOWN_OVERLAY", "overlay state is not an exact clear state"
        if not obs.target_identity or not obs.target_roi:
            return deny, "SEMANTIC_TARGET_REQUIRED", "coordinate-only or unknown targets are denied"
        if len(obs.target_roi) != 4 or obs.target_roi[0] >= obs.target_roi[2] or obs.target_roi[1] >= obs.target_roi[3]:
            return deny, "INVALID_TARGET_ROI", "target ROI is invalid"
        if obs.target_roi[0] < 0 or obs.target_roi[1] < 0 or obs.target_roi[2] > obs.width or obs.target_roi[3] > obs.height:
            return deny, "INVALID_TARGET_ROI", "target ROI is outside the source frame"
        if obs.clipped:
            return deny, "CLIPPED_TARGET", "clipped rows cannot authorize input"
        if obs.ambiguous:
            return deny, "AMBIGUOUS_TARGET", "ambiguous rows or targets cannot authorize input"
        if obs.control_class == "GO" and req.semantic_action == "CLAIM_DAILY_QUEST":
            return deny, "GO_NOT_CLAIM", "Go cannot be classified or authorized as Claim"
        if req.semantic_action == "CLAIM_DAILY_QUEST" and obs.control_class != "CLAIM":
            return deny, "CLAIM_TARGET_NOT_RECOGNIZED", "Claim requires an exact Claim control classification"
        if req.action_class == ActionClass.NAVIGATION_ONLY:
            if obs.os_surface or obs.hard_stop_detected or not obs.package_foreground:
                return lock, "NAVIGATION_HARD_STOP", "foreground, OS, or account/session safety is not proven"
            if obs.forbidden_region_intersects_target:
                return deny, "NAVIGATION_TARGET_DANGEROUS", "the local target intersects a dangerous control"
            if req.semantic_action == "DISMISS_ALLIANCE_FORT_WAVE":
                if (
                    obs.source_state != "ALLIANCE_FORT_WAVE_ALERT"
                    or obs.target_identity not in {
                        "alliance-fort-wave-dismiss-x",
                        "alliance-fort-wave-dismiss-confirm",
                    }
                    or obs.control_class not in {"POPUP_DISMISS_X", "POPUP_DISMISS_CONFIRM"}
                    or obs.expected_postcondition != "ALLIANCE_FORT_DISMISSED"
                ):
                    return deny, "ALLIANCE_FORT_DISMISSAL_NOT_EXACT", "only exact Alliance Fort X or Confirm dismissal is allowed"
            if obs.consequence != "navigate_zero_cost" or not obs.expected_postcondition:
                return deny, "NAVIGATION_CONTRACT_INVALID", "navigation requires a zero-cost bounded successor"
            if obs.cost_type != "none" or obs.cost_amount != 0 or obs.quantity != 1:
                return deny, "NAVIGATION_COST_DENIED", "navigation must be one zero-cost input"
            if req.semantic_action == "DISMISS_RESET_POPUP":
                if obs.source_state != "RESET_POPUP" or obs.target_identity != "reset-popup-close":
                    return deny, "RESET_POPUP_CLOSE_REQUIRED", "only the recognized reset popup Close control is allowed"
                if obs.expected_postcondition != "HOME_BASE":
                    return deny, "RESET_POPUP_SUCCESSOR_REQUIRED", "reset popup dismissal must return to Home/Base"
                x0, y0, x1, y1 = obs.target_roi
                if x0 < 200 or y0 < 700 or x1 > 600 or y1 > 920:
                    return deny, "RESET_POPUP_CLOSE_ROI_INVALID", "reset popup Close target is outside its bounded ROI"
            return PolicyDecision.AUTHORIZE, "AUTHORIZED_NAVIGATION_ONLY", "local source, target, overlay, and successor guards passed"
        if req.semantic_action == "RESEARCH_BIOENHANCER_FREE":
            if not req.game_day_id:
                return deny, "GAME_DAY_REQUIRED", "Bioenhancer research requires a current game-day identity"
            if (
                obs.source_state != "BIOENHANCER"
                or obs.target_identity != "bioenhancer-free-research"
                or obs.control_class != "RESEARCH_FREE"
                or obs.expected_postcondition != "BIOENHANCER_RESEARCH_SUCCESS"
            ):
                return deny, "BIOENHANCER_TARGET_NOT_EXACT", "only the exact current-frame Free Research 1x target is allowed"
        if not obs.consequence or obs.consequence == "unknown":
            return deny, "UNKNOWN_CONSEQUENCE", "consequence must be exact and known"
        if not obs.expected_postcondition:
            return deny, "POSTCONDITION_REQUIRED", "an exact expected postcondition is required"
        if obs.cost_type is None or obs.cost_amount is None:
            return deny, "UNKNOWN_COST", "cost type and amount must be known"
        if obs.quantity is None or obs.quantity <= 0:
            return deny, "UNKNOWN_QUANTITY", "quantity must be known and positive"
        if obs.cost_type != "none" or obs.cost_amount != 0:
            code = "PREMIUM_COST_DENIED" if obs.cost_type in ("premium", "real_money") else "RESOURCE_COST_DENIED"
            return deny, code, "premium, resource, item, AP, stamina, march, queue, combat, and strategic costs are denied"
        if obs.consequence not in ALLOWED_R1_CONSEQUENCES:
            return deny, "CONSEQUENCE_DENIED", "the consequence is not allowlisted for supervised zero-cost R1"
        return PolicyDecision.AUTHORIZE, "AUTHORIZED_ZERO_COST_R1", "all supervised zero-cost R1 guards passed"

    @staticmethod
    def _decide_promotional_back(req: PolicyRequest) -> Tuple[PolicyDecision, str, str]:
        """Authorize only an isolated standard game arrow on an unknown promotion."""
        obs = req.observation
        deny = PolicyDecision.DENY
        lock = PolicyDecision.GLOBAL_INPUT_LOCK
        if req.promotional_back_count >= MAX_PROMOTIONAL_BACKS:
            return deny, "PROMOTIONAL_BACK_LIMIT", "the bounded promotional escape limit was reached"
        if obs.os_surface or obs.hard_stop_detected or not obs.package_foreground:
            return lock, "PROMOTIONAL_HARD_STOP", "OS, account/session, or foreground safety is not proven"
        if not obs.recognized or obs.source_state != PROMOTIONAL_STATE or obs.source_family != "promotional":
            return deny, "PROMOTIONAL_SOURCE_NOT_RECOGNIZED", "the source is not an independently recognized promotional surface"
        if obs.overlay_state != "promotional_unknown_nonintersecting":
            return deny, "PROMOTIONAL_OVERLAY_NOT_SAFE", "an unknown overlay is not proven separate from the arrow"
        if obs.target_identity != "standard-game-back-arrow" or obs.control_class != SAFE_PROMOTIONAL_BACK:
            return deny, "PROMOTIONAL_ARROW_TARGET_REQUIRED", "only the recognized standard game Back arrow is allowed"
        if obs.target_roi != PROMOTIONAL_BACK_TARGET_ROI:
            return deny, "PROMOTIONAL_ARROW_ROI_INVALID", "the arrow target must use the locked isolated ROI"
        if obs.clipped:
            return deny, "CLIPPED_TARGET", "the promotional Back arrow is clipped"
        if obs.ambiguous:
            return deny, "AMBIGUOUS_TARGET", "the promotional Back arrow is ambiguous"
        if obs.arrow_geometry != PROMOTIONAL_BACK_GEOMETRY:
            return deny, "PROMOTIONAL_ARROW_GEOMETRY_INVALID", "the standard game Back arrow geometry did not pass"
        if not obs.forbidden_regions:
            return deny, "PROMOTIONAL_FORBIDDEN_REGIONS_REQUIRED", "forbidden interactive regions must be explicitly bound"
        x0, y0, x1, y1 = obs.target_roi
        for _name, region in obs.forbidden_regions:
            if len(region) != 4 or region[0] >= region[2] or region[1] >= region[3]:
                return deny, "PROMOTIONAL_FORBIDDEN_REGION_INVALID", "forbidden region metadata is invalid"
            fx0, fy0, fx1, fy1 = region
            if not (x1 <= fx0 or fx1 <= x0 or y1 <= fy0 or fy1 <= y0):
                return deny, "PROMOTIONAL_TARGET_NOT_ISOLATED", "the arrow ROI intersects a forbidden control region"
        if not obs.target_isolated or obs.forbidden_region_intersects_target:
            return deny, "PROMOTIONAL_TARGET_NOT_ISOLATED", "the arrow ROI is not separated from forbidden controls"
        if not obs.consequence or obs.consequence != "navigate_zero_cost":
            return deny, "PROMOTIONAL_CONSEQUENCE_DENIED", "promotional escape is navigation-only"
        if obs.cost_type != "none" or obs.cost_amount != 0:
            return deny, "PROMOTIONAL_COST_DENIED", "promotional escape must have exactly zero cost"
        if obs.quantity != 1:
            return deny, "PROMOTIONAL_QUANTITY_DENIED", "promotional escape quantity must be exactly one"
        if not obs.expected_postcondition:
            return deny, "PROMOTIONAL_SUCCESSOR_REQUIRED", "a bounded expected successor is required"
        successor = obs.expected_postcondition.upper().replace("-", "_")
        allowed_successors = {
            "CASH_MALL", "HOME_BASE", "QUEST", "DAILY_QUEST",
            "UNKNOWN_PROMOTIONAL_WITH_VERIFIED_BACK", "RECOGNIZED_NAVIGATION_STATE",
        }
        if successor not in allowed_successors:
            return deny, "PROMOTIONAL_SUCCESSOR_DENIED", "successor is outside the bounded navigation-only set"
        return PolicyDecision.AUTHORIZE, "AUTHORIZED_SAFE_PROMOTIONAL_BACK", "isolated verified promotional Back guards passed"
