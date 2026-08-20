"""Pure runtime identity assurance and preflight policy.

Configuration names the expected scope; it never proves the observed account, server, or reset.
Supervised navigation binding, production-observed identity, and the Resource-specific fixed
runtime binding plus observed reset are distinct fail-closed assurances.  This module performs no
capture, transport, persistence, or account-screen automation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
from typing import Optional


RUNTIME_IDENTITY_BEHAVIOR_VERSION = "runtime-identity-v1"
EXPECTED_NATIVE_SIZE = (800, 1280)
FIXED_RUNTIME_SCOPE = "local-bluestacks-primary-login-slot-v1"
FIXED_RUNTIME_BINDING_VERSION = "v1"
FIXED_RUNTIME_BINDING_KIND = "fixed_runtime_slot_binding"
FIXED_RUNTIME_IDENTITY_SEMANTICS = "fixed_runtime_binding_plus_observed_daily_reset"
RESOURCE_IDENTITY_MIN_RESET_REMAINING_SECONDS = 1.0


class RuntimeIdentityAssurance(str, Enum):
    CONFIGURATION_ONLY = "configuration_only"
    SUPERVISED_NAVIGATION_BINDING = "supervised_navigation_binding"
    PRODUCTION_OBSERVED = "production_observed"
    FIXED_RUNTIME_BINDING_RESET_OBSERVED = "fixed_runtime_binding_reset_observed"


@dataclass(frozen=True)
class FixedRuntimeBinding:
    """Deterministic identity for this private, fixed BlueStacks login slot.

    The serial, native profile, package, and versioned login-slot discriminator are binding
    inputs.  They identify the automation slot, not a game account or server observed on screen.
    """

    serial: str
    runtime_profile_id: str
    package_id: str
    login_slot_version: str

    def __post_init__(self) -> None:
        for name, value in (
            ("serial", self.serial),
            ("runtime_profile_id", self.runtime_profile_id),
            ("package_id", self.package_id),
            ("login_slot_version", self.login_slot_version),
        ):
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"{name} must be a non-empty normalized string")

    @property
    def canonical_payload(self) -> dict[str, str]:
        return {
            "login_slot_version": self.login_slot_version,
            "package_id": self.package_id,
            "runtime_profile_id": self.runtime_profile_id,
            "serial": self.serial,
        }

    @property
    def canonical_json(self) -> str:
        return json.dumps(
            self.canonical_payload,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def binding_digest(self) -> str:
        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()

    @property
    def runtime_scope(self) -> str:
        return FIXED_RUNTIME_SCOPE

    @property
    def account_id(self) -> str:
        return f"fixed-login-slot:{FIXED_RUNTIME_BINDING_VERSION}:{self.binding_digest}"

    @property
    def server_id(self) -> str:
        return f"fixed-server-slot:{FIXED_RUNTIME_BINDING_VERSION}:{self.binding_digest}"

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": FIXED_RUNTIME_BINDING_KIND,
            "version": FIXED_RUNTIME_BINDING_VERSION,
            "serial": self.serial,
            "runtime_profile_id": self.runtime_profile_id,
            "package_id": self.package_id,
            "login_slot_version": self.login_slot_version,
            "canonical_payload": self.canonical_payload,
            "canonical_json": self.canonical_json,
            "binding_digest": self.binding_digest,
            "runtime_scope": self.runtime_scope,
            "account_id": self.account_id,
            "server_id": self.server_id,
        }


def derive_fixed_runtime_binding(
    serial: str,
    runtime_profile_id: str,
    package_id: str,
    login_slot_version: str,
) -> FixedRuntimeBinding:
    """Derive the immutable local runtime-slot binding from checked-in constants."""

    return FixedRuntimeBinding(
        serial=serial,
        runtime_profile_id=runtime_profile_id,
        package_id=package_id,
        login_slot_version=login_slot_version,
    )


class RuntimePreflightStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"
    MANUAL_REQUIRED = "manual_required"


@dataclass(frozen=True)
class RuntimeIdentityConfiguration:
    runtime_scope: str
    account_id: str
    server_id: str
    reset_id: Optional[str] = None

    def __post_init__(self) -> None:
        for name, value in (
            ("runtime_scope", self.runtime_scope),
            ("account_id", self.account_id),
            ("server_id", self.server_id),
        ):
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"{name} must be a non-empty normalized string")
        if self.reset_id is not None and (
            not isinstance(self.reset_id, str)
            or not self.reset_id.strip()
            or self.reset_id != self.reset_id.strip()
        ):
            raise ValueError("reset_id must be absent or a non-empty normalized string")


@dataclass(frozen=True)
class RuntimeIdentityObservation:
    account_id: str
    server_id: str
    reset_id: Optional[str]
    evidence_refs: tuple[str, ...]
    operator_bound: bool = False
    machine_observed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, str) or not self.account_id.strip():
            raise ValueError("observed account_id required")
        if not isinstance(self.server_id, str) or not self.server_id.strip():
            raise ValueError("observed server_id required")
        if self.reset_id is not None and (
            not isinstance(self.reset_id, str) or not self.reset_id.strip()
        ):
            raise ValueError("observed reset_id must be absent or non-empty")
        if not self.evidence_refs or any(
            not isinstance(item, str) or not item.strip() for item in self.evidence_refs
        ):
            raise ValueError("identity observation requires evidence references")
        if self.operator_bound and self.machine_observed:
            raise ValueError("identity observation must use one assurance source")


@dataclass(frozen=True)
class VerifiedRuntimeIdentity:
    runtime_scope: str
    account_id: str
    server_id: str
    reset_id: Optional[str]
    assurance: RuntimeIdentityAssurance
    evidence_refs: tuple[str, ...]
    content_digest: Optional[str] = None
    observed_utc: Optional[str] = None
    expires_utc: Optional[str] = None
    runtime_binding_digest: Optional[str] = None

    def __post_init__(self) -> None:
        for name, value in (
            ("runtime_scope", self.runtime_scope),
            ("account_id", self.account_id),
            ("server_id", self.server_id),
        ):
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"verified {name} must be a non-empty normalized string")
        if not self.evidence_refs or any(
            not isinstance(item, str) or not item.strip() for item in self.evidence_refs
        ):
            raise ValueError("verified identity requires evidence references")
        if self.assurance in {
            RuntimeIdentityAssurance.PRODUCTION_OBSERVED,
            RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_RESET_OBSERVED,
        } and (not isinstance(self.reset_id, str) or not self.reset_id.strip()):
            raise ValueError("observed identity requires reset_id")
        if self.assurance is RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_RESET_OBSERVED:
            if (
                not isinstance(self.runtime_binding_digest, str)
                or len(self.runtime_binding_digest) != 64
                or any(ch not in "0123456789abcdef" for ch in self.runtime_binding_digest)
            ):
                raise ValueError("fixed runtime binding identity requires a SHA-256 digest")
            if (
                not isinstance(self.content_digest, str)
                or len(self.content_digest) != 64
                or any(ch not in "0123456789abcdef" for ch in self.content_digest)
            ):
                raise ValueError("fixed runtime binding identity requires evidence digest")
            if not isinstance(self.observed_utc, str) or not isinstance(self.expires_utc, str):
                raise ValueError("fixed runtime binding identity requires freshness timestamps")
            try:
                observed = _identity_utc(self.observed_utc)
                expires = _identity_utc(self.expires_utc)
            except (TypeError, ValueError) as exc:
                raise ValueError("fixed runtime binding identity timestamps are invalid") from exc
            if expires <= observed:
                raise ValueError("fixed runtime binding identity expires before its observation")

    @property
    def permits_supervised_navigation(self) -> bool:
        return self.assurance in {
            RuntimeIdentityAssurance.SUPERVISED_NAVIGATION_BINDING,
            RuntimeIdentityAssurance.PRODUCTION_OBSERVED,
            RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_RESET_OBSERVED,
        }

    @property
    def permits_production_consequential(self) -> bool:
        if self.assurance is RuntimeIdentityAssurance.PRODUCTION_OBSERVED:
            return (
                isinstance(self.reset_id, str)
                and bool(self.reset_id.strip())
            )
        if self.assurance is not RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_RESET_OBSERVED:
            return False
        if (
            not isinstance(self.reset_id, str)
            or not self.reset_id.strip()
            or not isinstance(self.content_digest, str)
            or len(self.content_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in self.content_digest)
            or not isinstance(self.runtime_binding_digest, str)
            or len(self.runtime_binding_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in self.runtime_binding_digest)
            or not self.evidence_refs
            or not isinstance(self.observed_utc, str)
            or not isinstance(self.expires_utc, str)
        ):
            return False
        try:
            return _identity_utc(self.expires_utc) > _identity_utc(self.observed_utc)
        except (TypeError, ValueError):
            return False


@dataclass(frozen=True)
class IdentityVerificationResult:
    identity: Optional[VerifiedRuntimeIdentity]
    reason: str


def verify_runtime_identity(
    configuration: RuntimeIdentityConfiguration,
    observation: Optional[RuntimeIdentityObservation],
    *,
    required_assurance: RuntimeIdentityAssurance,
) -> IdentityVerificationResult:
    """Bind expected configuration to observed evidence without upgrading assurance."""

    if required_assurance is RuntimeIdentityAssurance.CONFIGURATION_ONLY:
        return IdentityVerificationResult(None, "configuration_is_not_observed_identity")
    if observation is None:
        return IdentityVerificationResult(None, "identity_observation_missing")
    if observation.account_id != configuration.account_id:
        return IdentityVerificationResult(None, "account_identity_mismatch")
    if observation.server_id != configuration.server_id:
        return IdentityVerificationResult(None, "server_identity_mismatch")

    if required_assurance is RuntimeIdentityAssurance.SUPERVISED_NAVIGATION_BINDING:
        if not observation.operator_bound:
            return IdentityVerificationResult(None, "supervised_operator_binding_missing")
        if (
            configuration.reset_id is not None
            and observation.reset_id is not None
            and observation.reset_id != configuration.reset_id
        ):
            return IdentityVerificationResult(None, "reset_identity_mismatch")
        return IdentityVerificationResult(
            VerifiedRuntimeIdentity(
                configuration.runtime_scope,
                observation.account_id,
                observation.server_id,
                observation.reset_id,
                RuntimeIdentityAssurance.SUPERVISED_NAVIGATION_BINDING,
                observation.evidence_refs,
            ),
            "supervised_navigation_identity_verified",
        )

    if required_assurance is RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_RESET_OBSERVED:
        return IdentityVerificationResult(
            None,
            "fixed_runtime_binding_requires_resource_producer",
        )

    if not observation.machine_observed:
        return IdentityVerificationResult(None, "production_machine_observation_missing")
    if not configuration.reset_id or not observation.reset_id:
        return IdentityVerificationResult(None, "production_reset_identity_missing")
    if observation.reset_id != configuration.reset_id:
        return IdentityVerificationResult(None, "reset_identity_mismatch")
    return IdentityVerificationResult(
        VerifiedRuntimeIdentity(
            configuration.runtime_scope,
            observation.account_id,
            observation.server_id,
            observation.reset_id,
            RuntimeIdentityAssurance.PRODUCTION_OBSERVED,
            observation.evidence_refs,
        ),
        "production_identity_verified",
    )


@dataclass(frozen=True)
class ResourceIdentityEvidence:
    """Fixed runtime-slot binding plus machine-observed selected-Daily reset evidence."""

    account_id: str
    server_id: str
    reset_id: str
    evidence_refs: tuple[str, ...]
    observed_utc: str
    expires_utc: str
    content_digest: str
    runtime_scope: str
    runtime_binding_digest: str
    identity_semantics: str = FIXED_RUNTIME_IDENTITY_SEMANTICS
    assurance: str = RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_RESET_OBSERVED.value
    machine_observed: bool = True
    operator_bound: bool = False

    def __post_init__(self) -> None:
        for name in (
            "account_id",
            "server_id",
            "reset_id",
            "observed_utc",
            "expires_utc",
            "content_digest",
            "runtime_scope",
            "runtime_binding_digest",
            "identity_semantics",
            "assurance",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"{name} must be a normalized non-empty string")
        if self.identity_semantics != FIXED_RUNTIME_IDENTITY_SEMANTICS:
            raise ValueError("Resource identity evidence semantics are not fixed-slot binding plus reset")
        if self.assurance != RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_RESET_OBSERVED.value:
            raise ValueError("Resource identity evidence assurance is not fixed-slot binding plus reset")
        for name in ("content_digest", "runtime_binding_digest"):
            value = getattr(self, name)
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        if not self.evidence_refs or any(
            not isinstance(item, str) or not item.strip() for item in self.evidence_refs
        ):
            raise ValueError("Resource identity evidence requires references")
        if self.machine_observed is not True or self.operator_bound is not False:
            raise ValueError("Resource identity evidence must be machine-observed and not operator-only")

    def as_dict(self) -> dict[str, object]:
        return {
            "account_id": self.account_id,
            "server_id": self.server_id,
            "reset_id": self.reset_id,
            "evidence_refs": self.evidence_refs,
            "observed_utc": self.observed_utc,
            "expires_utc": self.expires_utc,
            "machine_observed": self.machine_observed,
            "operator_bound": self.operator_bound,
            "runtime_scope": self.runtime_scope,
            "runtime_binding_digest": self.runtime_binding_digest,
            "identity_semantics": self.identity_semantics,
            "assurance": self.assurance,
        }

    def computed_digest(self) -> str:
        encoded = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def reset_identity_id(self) -> str:
        return self.reset_id


def _identity_utc(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("identity UTC value must be datetime or ISO string")
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def produce_resource_runtime_identity(
    configuration: RuntimeIdentityConfiguration,
    evidence: ResourceIdentityEvidence,
    current_reset_deadline_evidence: dict[str, object],
    evaluated_utc: datetime | str,
    expected_binding: FixedRuntimeBinding | None = None,
) -> VerifiedRuntimeIdentity:
    """Produce one fresh fixed-slot identity with a machine-observed Daily reset."""

    if not isinstance(configuration, RuntimeIdentityConfiguration):
        raise ValueError("Resource identity configuration is required")
    if not isinstance(evidence, ResourceIdentityEvidence):
        raise ValueError("Resource identity evidence is required")
    if not isinstance(expected_binding, FixedRuntimeBinding):
        raise ValueError("Resource expected fixed runtime binding is required")
    if not isinstance(current_reset_deadline_evidence, dict):
        raise ValueError("current machine-observed Daily reset deadline evidence is required")
    if (
        configuration.runtime_scope != expected_binding.runtime_scope
        or configuration.account_id != expected_binding.account_id
        or configuration.server_id != expected_binding.server_id
    ):
        raise ValueError("Resource configuration does not match the fixed runtime binding")
    if (
        evidence.runtime_scope != expected_binding.runtime_scope
        or evidence.runtime_binding_digest != expected_binding.binding_digest
        or evidence.account_id != expected_binding.account_id
        or evidence.server_id != expected_binding.server_id
    ):
        raise ValueError("Resource evidence does not match the fixed runtime binding")
    if evidence.computed_digest() != evidence.content_digest:
        raise ValueError("Resource identity evidence digest mismatch")
    if current_reset_deadline_evidence.get("machine_observed") is not True:
        raise ValueError("current Daily reset evidence is not machine-observed")
    daily_frame = current_reset_deadline_evidence.get("daily_frame")
    if not isinstance(daily_frame, dict):
        raise ValueError("current Daily reset evidence is not hash-bound to a frame")
    frame_path = daily_frame.get("path")
    frame_digest = daily_frame.get("sha256")
    frame_captured = daily_frame.get("captured_utc")
    frame_observed = daily_frame.get("observed_utc")
    if (
        not isinstance(frame_path, str)
        or not frame_path.strip()
        or not isinstance(frame_digest, str)
        or len(frame_digest) != 64
        or any(ch not in "0123456789abcdef" for ch in frame_digest)
        or not isinstance(frame_captured, str)
        or not isinstance(frame_observed, str)
    ):
        raise ValueError("current Daily reset frame provenance is missing")
    try:
        frame_captured_utc = _identity_utc(frame_captured)
        frame_observed_utc = _identity_utc(frame_observed)
    except (TypeError, ValueError) as exc:
        raise ValueError("current Daily reset frame provenance timestamps are invalid") from exc
    if frame_captured_utc > frame_observed_utc:
        raise ValueError("current Daily reset frame observation precedes capture")
    normalized_deadline = current_reset_deadline_evidence.get(
        "normalized_deadline_utc",
        current_reset_deadline_evidence.get("reset_deadline_utc"),
    )
    if not isinstance(normalized_deadline, str) or not normalized_deadline.strip():
        raise ValueError("current Daily reset deadline is missing")
    try:
        deadline_utc = _identity_utc(normalized_deadline)
    except (TypeError, ValueError) as exc:
        raise ValueError("current Daily reset deadline is invalid") from exc
    canonical_deadline = deadline_utc.isoformat().replace("+00:00", "Z")
    if normalized_deadline != canonical_deadline:
        raise ValueError("current Daily reset deadline is not an exact UTC timestamp")
    deadline_identity = current_reset_deadline_evidence.get(
        "deadline_identity",
        current_reset_deadline_evidence.get("reset_deadline_identity"),
    )
    if not isinstance(deadline_identity, str) or not deadline_identity.strip():
        raise ValueError("current machine-observed reset deadline identity is missing")
    if deadline_identity != f"reset-deadline:{canonical_deadline}":
        raise ValueError("current Daily reset deadline identity is not deadline-bound")
    timer_seconds = current_reset_deadline_evidence.get("reset_timer_seconds")
    if (
        type(timer_seconds) is not int
        or timer_seconds <= 0
        or deadline_utc != frame_observed_utc + timedelta(seconds=timer_seconds)
    ):
        raise ValueError("current Daily reset deadline is not timer-derived")
    if (
        deadline_utc - frame_observed_utc
    ).total_seconds() <= RESOURCE_IDENTITY_MIN_RESET_REMAINING_SECONDS:
        raise ValueError("current Daily reset deadline is expired or too close to observation")
    if current_reset_deadline_evidence.get("recurrence_class") != "daily_reset":
        raise ValueError("current Daily reset evidence is not a daily reset")
    current_observed = current_reset_deadline_evidence.get(
        "observed_utc",
        current_reset_deadline_evidence.get("reset_observed_utc"),
    )
    if not isinstance(current_observed, str) or current_observed != frame_observed:
        raise ValueError("current Daily reset evidence is not frame-bound")
    if evidence.reset_id != deadline_identity:
        raise ValueError("Resource reset identity does not match current Daily deadline evidence")
    if configuration.reset_id is None:
        raise ValueError("Resource configuration reset identity is unbound")
    if configuration.reset_id != evidence.reset_id:
        raise ValueError("Resource reset identity does not match configuration")
    observed = _identity_utc(evidence.observed_utc)
    expires = _identity_utc(evidence.expires_utc)
    evaluated = _identity_utc(evaluated_utc)
    if evaluated >= deadline_utc:
        raise ValueError("Resource identity was evaluated at or after the reset deadline")
    if expires <= observed or evaluated < observed or evaluated > expires:
        raise ValueError("Resource identity evidence is stale or outside its validity window")
    try:
        deadline_observed_utc = _identity_utc(current_observed)
    except (TypeError, ValueError) as exc:
        raise ValueError("current reset observation timestamp is invalid") from exc
    if frame_observed_utc != deadline_observed_utc:
        raise ValueError("current Daily reset frame is not bound to reset observation")
    if evaluated < deadline_observed_utc:
        raise ValueError("Resource identity was evaluated before current reset observation")
    return VerifiedRuntimeIdentity(
        expected_binding.runtime_scope,
        expected_binding.account_id,
        expected_binding.server_id,
        evidence.reset_id,
        RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_RESET_OBSERVED,
        evidence.evidence_refs,
        evidence.content_digest,
        evidence.observed_utc,
        evidence.expires_utc,
        expected_binding.binding_digest,
    )


@dataclass(frozen=True)
class RuntimePreflightObservation:
    expected_package: str
    observed_package: Optional[str]
    expected_profile_id: str
    observed_profile_id: Optional[str]
    native_width: int
    native_height: int
    game_foregrounded: bool
    manual_only_state: bool
    blocking_unknown_modal: bool
    captured_monotonic: float
    evaluated_monotonic: float
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class RuntimePreflightDecision:
    status: RuntimePreflightStatus
    reason: str
    identity: Optional[VerifiedRuntimeIdentity]
    navigation_authorized: bool
    production_consequential_authorized: bool


def evaluate_runtime_preflight(
    observation: RuntimePreflightObservation,
    identity: Optional[VerifiedRuntimeIdentity],
    *,
    maximum_age_seconds: float = 3.0,
) -> RuntimePreflightDecision:
    """Evaluate current package/profile/manual state and identity assurance without input."""

    if observation.manual_only_state:
        return RuntimePreflightDecision(
            RuntimePreflightStatus.MANUAL_REQUIRED,
            "manual_only_state",
            identity,
            False,
            False,
        )
    if observation.blocking_unknown_modal:
        return RuntimePreflightDecision(
            RuntimePreflightStatus.BLOCKED,
            "blocking_unknown_modal",
            identity,
            False,
            False,
        )
    if not observation.game_foregrounded:
        return RuntimePreflightDecision(
            RuntimePreflightStatus.BLOCKED,
            "game_not_foregrounded",
            identity,
            False,
            False,
        )
    if observation.observed_package != observation.expected_package:
        return RuntimePreflightDecision(
            RuntimePreflightStatus.BLOCKED,
            "unexpected_foreground_package",
            identity,
            False,
            False,
        )
    if (
        observation.observed_profile_id != observation.expected_profile_id
        or (observation.native_width, observation.native_height) != EXPECTED_NATIVE_SIZE
    ):
        return RuntimePreflightDecision(
            RuntimePreflightStatus.BLOCKED,
            "unexpected_native_profile",
            identity,
            False,
            False,
        )
    age = observation.evaluated_monotonic - observation.captured_monotonic
    if age < 0 or age > maximum_age_seconds:
        return RuntimePreflightDecision(
            RuntimePreflightStatus.BLOCKED,
            "stale_preflight_observation",
            identity,
            False,
            False,
        )
    if not observation.evidence_refs:
        return RuntimePreflightDecision(
            RuntimePreflightStatus.BLOCKED,
            "preflight_evidence_missing",
            identity,
            False,
            False,
        )
    if identity is None or not identity.permits_supervised_navigation:
        return RuntimePreflightDecision(
            RuntimePreflightStatus.BLOCKED,
            "verified_identity_unavailable",
            identity,
            False,
            False,
        )
    return RuntimePreflightDecision(
        RuntimePreflightStatus.READY,
        "runtime_preflight_ready",
        identity,
        True,
        identity.permits_production_consequential,
    )
