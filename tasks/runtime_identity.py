"""Pure runtime identity assurance and preflight policy.

Configuration names the expected scope; it never proves the observed account, server, or reset.
Supervised navigation binding and production-observed identity are distinct fail-closed assurances.
This module performs no capture, transport, persistence, or account-screen automation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Optional


RUNTIME_IDENTITY_BEHAVIOR_VERSION = "runtime-identity-v1"
EXPECTED_NATIVE_SIZE = (800, 1280)


class RuntimeIdentityAssurance(str, Enum):
    CONFIGURATION_ONLY = "configuration_only"
    SUPERVISED_NAVIGATION_BINDING = "supervised_navigation_binding"
    PRODUCTION_OBSERVED = "production_observed"


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
        if (
            self.assurance is RuntimeIdentityAssurance.PRODUCTION_OBSERVED
            and (not isinstance(self.reset_id, str) or not self.reset_id.strip())
        ):
            raise ValueError("production-observed identity requires reset_id")

    @property
    def permits_supervised_navigation(self) -> bool:
        return self.assurance in {
            RuntimeIdentityAssurance.SUPERVISED_NAVIGATION_BINDING,
            RuntimeIdentityAssurance.PRODUCTION_OBSERVED,
        }

    @property
    def permits_production_consequential(self) -> bool:
        return (
            self.assurance is RuntimeIdentityAssurance.PRODUCTION_OBSERVED
            and isinstance(self.reset_id, str)
            and bool(self.reset_id.strip())
        )


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
    """Machine-observed account/server/reset evidence for the Resource route."""

    account_id: str
    server_id: str
    reset_id: str
    evidence_refs: tuple[str, ...]
    observed_utc: str
    expires_utc: str
    content_digest: str
    machine_observed: bool = True
    operator_bound: bool = False

    def __post_init__(self) -> None:
        for name in ("account_id", "server_id", "reset_id", "observed_utc", "expires_utc", "content_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"{name} must be a normalized non-empty string")
        if len(self.content_digest) != 64 or any(
            ch not in "0123456789abcdef" for ch in self.content_digest
        ):
            raise ValueError("content_digest must be a lowercase SHA-256 digest")
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
) -> VerifiedRuntimeIdentity:
    """Produce one fresh PRODUCTION_OBSERVED identity without performing input."""

    if not isinstance(configuration, RuntimeIdentityConfiguration):
        raise ValueError("Resource identity configuration is required")
    if not isinstance(evidence, ResourceIdentityEvidence):
        raise ValueError("Resource identity evidence is required")
    if not isinstance(current_reset_deadline_evidence, dict):
        raise ValueError("current machine-observed Daily reset deadline evidence is required")
    if evidence.computed_digest() != evidence.content_digest:
        raise ValueError("Resource identity evidence digest mismatch")
    deadline_identity = current_reset_deadline_evidence.get(
        "deadline_identity",
        current_reset_deadline_evidence.get("reset_deadline_identity"),
    )
    if not isinstance(deadline_identity, str) or not deadline_identity.strip():
        raise ValueError("current machine-observed reset deadline identity is missing")
    if evidence.reset_id != deadline_identity:
        raise ValueError("Resource reset identity does not match current Daily deadline evidence")
    if configuration.reset_id is None:
        raise ValueError("Resource configuration reset identity is unbound")
    if configuration.reset_id != evidence.reset_id:
        raise ValueError("Resource reset identity does not match configuration")
    observed = _identity_utc(evidence.observed_utc)
    expires = _identity_utc(evidence.expires_utc)
    evaluated = _identity_utc(evaluated_utc)
    if expires <= observed or evaluated < observed or evaluated > expires:
        raise ValueError("Resource identity evidence is stale or outside its validity window")
    deadline_observed = current_reset_deadline_evidence.get(
        "observed_utc",
        current_reset_deadline_evidence.get("reset_observed_utc"),
    )
    if deadline_observed is not None and evaluated < _identity_utc(str(deadline_observed)):
        raise ValueError("Resource identity was evaluated before current reset observation")
    observation = RuntimeIdentityObservation(
        evidence.account_id,
        evidence.server_id,
        evidence.reset_id,
        tuple(evidence.evidence_refs),
        operator_bound=False,
        machine_observed=True,
    )
    result = verify_runtime_identity(
        configuration,
        observation,
        required_assurance=RuntimeIdentityAssurance.PRODUCTION_OBSERVED,
    )
    if result.identity is None:
        raise ValueError(result.reason)
    return VerifiedRuntimeIdentity(
        result.identity.runtime_scope,
        result.identity.account_id,
        result.identity.server_id,
        result.identity.reset_id,
        result.identity.assurance,
        result.identity.evidence_refs,
        evidence.content_digest,
        evidence.observed_utc,
        evidence.expires_utc,
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
