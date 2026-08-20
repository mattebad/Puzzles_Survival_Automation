"""Pure runtime identity assurance and preflight policy.

Configuration names the expected scope; it never proves an observed account, server, or reset.
Resource identity is derived from the fixed local runtime binding and the product's static UTC
midnight reset rule.  This module performs no capture, transport, persistence, or account-screen
automation.
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
FIXED_RUNTIME_IDENTITY_SEMANTICS = "fixed_runtime_binding_plus_static_utc_reset"
RESOURCE_IDENTITY_AUTHORIZATION_FRESHNESS_SECONDS = 600.0


class RuntimeIdentityAssurance(str, Enum):
    CONFIGURATION_ONLY = "configuration_only"
    SUPERVISED_NAVIGATION_BINDING = "supervised_navigation_binding"
    PRODUCTION_OBSERVED = "production_observed"
    FIXED_RUNTIME_BINDING_RESET_OBSERVED = "fixed_runtime_binding_reset_observed"
    FIXED_RUNTIME_BINDING_STATIC_UTC_RESET = "fixed_runtime_binding_static_utc_reset"


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
    reset_start_utc: Optional[str] = None
    reset_deadline_utc: Optional[str] = None

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
            RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_STATIC_UTC_RESET,
        } and (not isinstance(self.reset_id, str) or not self.reset_id.strip()):
            raise ValueError("observed identity requires reset_id")
        if self.assurance in {
            RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_RESET_OBSERVED,
            RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_STATIC_UTC_RESET,
        }:
            if (
                not isinstance(self.runtime_binding_digest, str)
                or len(self.runtime_binding_digest) != 64
                or any(ch not in "0123456789abcdef" for ch in self.runtime_binding_digest)
            ):
                raise ValueError("fixed runtime binding identity requires a SHA-256 digest")
            if not isinstance(self.observed_utc, str) or not isinstance(self.expires_utc, str):
                raise ValueError("fixed runtime binding identity requires freshness timestamps")
            try:
                observed = _identity_utc(self.observed_utc)
                expires = _identity_utc(self.expires_utc)
            except (TypeError, ValueError) as exc:
                raise ValueError("fixed runtime binding identity timestamps are invalid") from exc
            if expires <= observed:
                raise ValueError("fixed runtime binding identity expires before its observation")
            if self.assurance is RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_STATIC_UTC_RESET:
                if (
                    not isinstance(self.reset_start_utc, str)
                    or not isinstance(self.reset_deadline_utc, str)
                ):
                    raise ValueError("static UTC identity requires reset bounds")
                try:
                    reset_start = _identity_utc(self.reset_start_utc)
                    reset_deadline = _identity_utc(self.reset_deadline_utc)
                except (TypeError, ValueError) as exc:
                    raise ValueError("static UTC identity reset bounds are invalid") from exc
                if (
                    reset_start.hour != 0
                    or reset_start.minute != 0
                    or reset_start.second != 0
                    or reset_start.microsecond != 0
                    or reset_deadline != reset_start + timedelta(days=1)
                    or self.reset_id
                    != f"reset-deadline:{reset_deadline.isoformat().replace('+00:00', 'Z')}"
                ):
                    raise ValueError("static UTC identity reset bounds are not a UTC midnight window")

    @property
    def permits_supervised_navigation(self) -> bool:
        return self.assurance in {
            RuntimeIdentityAssurance.SUPERVISED_NAVIGATION_BINDING,
            RuntimeIdentityAssurance.PRODUCTION_OBSERVED,
            RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_RESET_OBSERVED,
            RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_STATIC_UTC_RESET,
        }

    @property
    def permits_production_consequential(self) -> bool:
        if self.assurance is RuntimeIdentityAssurance.PRODUCTION_OBSERVED:
            return (
                isinstance(self.reset_id, str)
                and bool(self.reset_id.strip())
            )
        if self.assurance not in {
            RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_RESET_OBSERVED,
            RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_STATIC_UTC_RESET,
        }:
            return False
        if (
            not isinstance(self.reset_id, str)
            or not self.reset_id.strip()
            or not isinstance(self.runtime_binding_digest, str)
            or len(self.runtime_binding_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in self.runtime_binding_digest)
            or not self.evidence_refs
            or not isinstance(self.observed_utc, str)
            or not isinstance(self.expires_utc, str)
        ):
            return False
        try:
            expires = _identity_utc(self.expires_utc)
            observed = _identity_utc(self.observed_utc)
            if self.assurance is RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_STATIC_UTC_RESET:
                if not isinstance(self.reset_start_utc, str) or not isinstance(
                    self.reset_deadline_utc, str
                ):
                    return False
                return (
                    expires > observed
                    and _identity_utc(self.reset_deadline_utc)
                    > _identity_utc(self.reset_start_utc)
                    and _identity_utc(self.reset_deadline_utc) >= expires
                )
            return expires > observed
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

    if required_assurance in {
        RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_RESET_OBSERVED,
        RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_STATIC_UTC_RESET,
    }:
        return IdentityVerificationResult(
            None,
            "fixed_runtime_binding_requires_resource_identity_derivation",
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
class ResourceResetWindow:
    """The product-defined reset window selected from one UTC wall-clock sample."""

    evaluated_utc: datetime
    reset_start_utc: datetime
    reset_deadline_utc: datetime
    reset_identity_id: str

    def __post_init__(self) -> None:
        for name in ("evaluated_utc", "reset_start_utc", "reset_deadline_utc"):
            value = getattr(self, name)
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
            object.__setattr__(self, name, value.astimezone(timezone.utc))
        if (
            self.reset_start_utc.hour != 0
            or self.reset_start_utc.minute != 0
            or self.reset_start_utc.second != 0
            or self.reset_start_utc.microsecond != 0
            or self.reset_deadline_utc != self.reset_start_utc + timedelta(days=1)
            or self.evaluated_utc < self.reset_start_utc
            or self.evaluated_utc >= self.reset_deadline_utc
            or self.reset_identity_id
            != f"reset-deadline:{self.reset_deadline_utc.isoformat().replace('+00:00', 'Z')}"
        ):
            raise ValueError("Resource reset window is not an exact UTC midnight interval")

    @property
    def reset_start_text(self) -> str:
        return self.reset_start_utc.isoformat().replace("+00:00", "Z")

    @property
    def current_utc(self) -> datetime:
        return self.evaluated_utc

    @property
    def reset_id(self) -> str:
        return self.reset_identity_id

    @property
    def reset_deadline_text(self) -> str:
        return self.reset_deadline_utc.isoformat().replace("+00:00", "Z")

    def as_dict(self) -> dict[str, str]:
        return {
            "evaluated_utc": self.evaluated_utc.isoformat().replace("+00:00", "Z"),
            "reset_start_utc": self.reset_start_text,
            "reset_deadline_utc": self.reset_deadline_text,
            "reset_identity_id": self.reset_identity_id,
        }


def _identity_utc(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("identity UTC value must be datetime or ISO string")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("identity UTC value must be timezone-aware")
    return result.astimezone(timezone.utc)


def derive_static_utc_reset(evaluated_utc: datetime | str) -> ResourceResetWindow:
    """Select the active daily reset using a timezone-aware UTC wall-clock sample."""

    evaluated = _identity_utc(evaluated_utc)
    reset_start = evaluated.replace(hour=0, minute=0, second=0, microsecond=0)
    reset_deadline = reset_start + timedelta(days=1)
    deadline_text = reset_deadline.isoformat().replace("+00:00", "Z")
    return ResourceResetWindow(
        evaluated_utc=evaluated,
        reset_start_utc=reset_start,
        reset_deadline_utc=reset_deadline,
        reset_identity_id=f"reset-deadline:{deadline_text}",
    )


def derive_resource_runtime_identity(
    expected_binding: FixedRuntimeBinding,
    evaluated_utc: datetime | str,
    *,
    authorization_freshness_seconds: float = RESOURCE_IDENTITY_AUTHORIZATION_FRESHNESS_SECONDS,
    evidence_refs: tuple[str, ...] = (),
) -> VerifiedRuntimeIdentity:
    """Derive Resource authority from fixed-slot binding and static UTC reset policy."""

    if not isinstance(expected_binding, FixedRuntimeBinding):
        raise ValueError("Resource expected fixed runtime binding is required")
    if (
        type(authorization_freshness_seconds) not in {int, float}
        or float(authorization_freshness_seconds) <= 0.0
    ):
        raise ValueError("Resource authorization freshness must be positive")
    window = derive_static_utc_reset(evaluated_utc)
    expires = min(
        window.evaluated_utc + timedelta(seconds=float(authorization_freshness_seconds)),
        window.reset_deadline_utc,
    )
    refs = tuple(evidence_refs) or (
        "identity-source:fixed-runtime-binding",
        "identity-source:static-utc-midnight-reset",
    )
    if any(not isinstance(ref, str) or not ref.strip() for ref in refs):
        raise ValueError("Resource identity evidence references must be non-empty strings")
    return VerifiedRuntimeIdentity(
        runtime_scope=expected_binding.runtime_scope,
        account_id=expected_binding.account_id,
        server_id=expected_binding.server_id,
        reset_id=window.reset_identity_id,
        assurance=RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_STATIC_UTC_RESET,
        evidence_refs=refs,
        observed_utc=window.evaluated_utc.isoformat().replace("+00:00", "Z"),
        expires_utc=expires.isoformat().replace("+00:00", "Z"),
        runtime_binding_digest=expected_binding.binding_digest,
        reset_start_utc=window.reset_start_text,
        reset_deadline_utc=window.reset_deadline_text,
    )


# Explicit aliases keep the policy vocabulary discoverable to callers without reintroducing a
# receipt or screen-observation producer.
derive_static_utc_reset_identity = derive_static_utc_reset
derive_resource_reset_window = derive_static_utc_reset
derive_resource_reset_identity = derive_static_utc_reset
produce_resource_runtime_identity = derive_resource_runtime_identity


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
