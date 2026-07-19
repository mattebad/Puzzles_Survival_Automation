"""Platform-neutral, crash-safe navigation session state.

This module records navigation intent and evidence only.  It never stores or returns
dispatchable target coordinates; current-frame interaction coordinates remain owned by
the platform adapter and the perception bundle.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path
import re
import uuid
from typing import Any, Callable, Mapping, Sequence

from tasks.home_atlas import BuildingBinding
from tasks.perception_bundle import (
    ContextualClass,
    FramePerceptionBundle,
    NativeFrameIdentity,
    PerceptionBundleError,
)


SCHEMA_NAME = "navigation_session"
SCHEMA_VERSION = 1

Point = tuple[float, float]
Box = tuple[int, int, int, int]
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class NavigationSessionError(ValueError):
    """Fail-closed navigation session denial with a stable reason code."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(detail or reason_code)


class NavigationCheckpoint(str, Enum):
    CREATED = "created"
    SOURCE_HOME_VERIFIED = "source_home_verified"
    PLAN_CREATED = "plan_created"
    PAN_DISPATCHED = "pan_dispatched"
    PAN_RELOCALIZED = "pan_relocalized"
    TARGET_BOUND = "target_bound"
    RADIAL_VERIFIED = "radial_verified"
    SAFE_EXIT_VERIFIED = "safe_exit_verified"
    HOME_RECOVERED = "home_recovered"


class SessionOutcome(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    UNCERTAIN = "uncertain"


class LedgerStatus(str, Enum):
    PREPARED = "prepared"
    DISPATCHED = "dispatched"
    RECONCILED = "reconciled"
    SUPPRESSED = "suppressed"


class ContinuationMode(str, Enum):
    NORMAL = "normal"
    RECOVERY_ONLY = "recovery_only"


class UncertainPreparedResolution(str, Enum):
    """Explicit observer resolution for uncertain PREPARED pans after restart."""

    CONFIRMED_DISPATCHED_AND_RELOCALIZED = "confirmed_dispatched_and_relocalized"
    CONFIRMED_NOT_DISPATCHED = "confirmed_not_dispatched"
    STILL_AMBIGUOUS = "still_ambiguous"


class ConclusiveNonDispatchReason(str, Enum):
    """Transport-layer outcomes that conclusively prove no input reached the device.

    Localization, unchanged pixels, zero displacement, timeouts, exceptions,
    missing ledger rows, clamped gestures, and no-op delivery are intentionally
    absent: they do not prove non-dispatch.
    """

    NEVER_SUBMITTED_TO_DEVICE = "never_submitted_to_device"
    REJECTED_PRE_DEVICE_BY_TRANSPORT = "rejected_pre_device_by_transport"
    CHANNEL_CLOSED_BEFORE_SUBMIT = "channel_closed_before_submit"


# Private mint token: only TrustedTransportNonDispatchAuthority may construct evidence.
_NON_DISPATCH_MINT_TOKEN = object()

# Adapter outcomes that are explicitly non-conclusive and must never mint evidence.
_NONCONCLUSIVE_TRANSPORT_OUTCOMES = frozenset(
    {
        "timeout",
        "exception",
        "missing_ledger",
        "missing_record",
        "clamped",
        "no_op",
        "noop",
        "zero_displacement",
        "unchanged_pixels",
        "localization_unchanged",
        "localization",
        "dispatched",
        "delivered",
    }
)

_CONCLUSIVE_TRANSPORT_OUTCOME_MAP: Mapping[str, ConclusiveNonDispatchReason] = {
    ConclusiveNonDispatchReason.NEVER_SUBMITTED_TO_DEVICE.value: (
        ConclusiveNonDispatchReason.NEVER_SUBMITTED_TO_DEVICE
    ),
    ConclusiveNonDispatchReason.REJECTED_PRE_DEVICE_BY_TRANSPORT.value: (
        ConclusiveNonDispatchReason.REJECTED_PRE_DEVICE_BY_TRANSPORT
    ),
    ConclusiveNonDispatchReason.CHANNEL_CLOSED_BEFORE_SUBMIT.value: (
        ConclusiveNonDispatchReason.CHANNEL_CLOSED_BEFORE_SUBMIT
    ),
}


LEGAL_TRANSITIONS: Mapping[NavigationCheckpoint, frozenset[NavigationCheckpoint]] = {
    NavigationCheckpoint.CREATED: frozenset({NavigationCheckpoint.SOURCE_HOME_VERIFIED}),
    NavigationCheckpoint.SOURCE_HOME_VERIFIED: frozenset({NavigationCheckpoint.PLAN_CREATED}),
    NavigationCheckpoint.PLAN_CREATED: frozenset(
        {NavigationCheckpoint.PAN_DISPATCHED, NavigationCheckpoint.TARGET_BOUND}
    ),
    NavigationCheckpoint.PAN_DISPATCHED: frozenset({NavigationCheckpoint.PAN_RELOCALIZED}),
    NavigationCheckpoint.PAN_RELOCALIZED: frozenset(
        {NavigationCheckpoint.PLAN_CREATED, NavigationCheckpoint.TARGET_BOUND}
    ),
    NavigationCheckpoint.TARGET_BOUND: frozenset({NavigationCheckpoint.RADIAL_VERIFIED}),
    NavigationCheckpoint.RADIAL_VERIFIED: frozenset({NavigationCheckpoint.SAFE_EXIT_VERIFIED}),
    NavigationCheckpoint.SAFE_EXIT_VERIFIED: frozenset({NavigationCheckpoint.HOME_RECOVERED}),
    NavigationCheckpoint.HOME_RECOVERED: frozenset(),
}

RECOVERY_ONLY_CHECKPOINTS = frozenset(
    {NavigationCheckpoint.RADIAL_VERIFIED, NavigationCheckpoint.SAFE_EXIT_VERIFIED}
)

_RECOVERY_TRANSITIONS = frozenset(
    {
        (NavigationCheckpoint.RADIAL_VERIFIED, NavigationCheckpoint.SAFE_EXIT_VERIFIED),
        (NavigationCheckpoint.SAFE_EXIT_VERIFIED, NavigationCheckpoint.HOME_RECOVERED),
    }
)


@dataclass(frozen=True)
class AuthorizationScope:
    task_id: str
    owner_operator: str
    action_class: str
    platform: str
    profile: str
    environment: str
    target_building_id: str

    def __post_init__(self) -> None:
        for name in (
            "task_id",
            "owner_operator",
            "action_class",
            "platform",
            "profile",
            "environment",
            "target_building_id",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise NavigationSessionError("INVALID_AUTHORIZATION_SCOPE", name)

    def matches(self, other: "AuthorizationScope") -> bool:
        return asdict(self) == asdict(other)


@dataclass(frozen=True)
class FrameIdentityRecord:
    """Persisted capture-event identity.  It contains no executable coordinates."""

    capture_kind: str
    runtime_capture_session_id: str
    capture_ordinal: int
    capture_completed_monotonic: float
    transport_sha256: str
    semantic_sha256: str
    runtime_profile_id: str
    width: int
    height: int
    label: str = ""

    @classmethod
    def from_native(cls, identity: NativeFrameIdentity) -> "FrameIdentityRecord":
        return cls(
            capture_kind=identity.capture_kind,
            runtime_capture_session_id=identity.runtime_session_id,
            capture_ordinal=identity.capture_ordinal,
            capture_completed_monotonic=identity.capture_completed_monotonic,
            transport_sha256=identity.transport_sha256,
            semantic_sha256=identity.semantic_sha256,
            runtime_profile_id=identity.runtime_profile_id,
            width=identity.width,
            height=identity.height,
            label=identity.label,
        )

    def to_native(self) -> NativeFrameIdentity:
        return NativeFrameIdentity(
            capture_kind=self.capture_kind,  # type: ignore[arg-type]
            runtime_session_id=self.runtime_capture_session_id,
            capture_ordinal=self.capture_ordinal,
            capture_completed_monotonic=self.capture_completed_monotonic,
            transport_sha256=self.transport_sha256,
            semantic_sha256=self.semantic_sha256,
            runtime_profile_id=self.runtime_profile_id,
            width=self.width,
            height=self.height,
            label=self.label,
        )

    def same_capture_event(self, other: "FrameIdentityRecord | NativeFrameIdentity") -> bool:
        if isinstance(other, NativeFrameIdentity):
            other = FrameIdentityRecord.from_native(other)
        return (
            self.capture_kind == other.capture_kind
            and self.runtime_capture_session_id == other.runtime_capture_session_id
            and self.capture_ordinal == other.capture_ordinal
            and self.capture_completed_monotonic == other.capture_completed_monotonic
            and self.transport_sha256 == other.transport_sha256
            and self.semantic_sha256 == other.semantic_sha256
            and self.runtime_profile_id == other.runtime_profile_id
            and self.width == other.width
            and self.height == other.height
        )


@dataclass(frozen=True)
class LatestObservation:
    frame: FrameIdentityRecord | None
    contextual_class: str = ""
    localization_recognized: bool | None = None
    localization_confidence: float | None = None
    localization_residual_px: float | None = None
    summary: str = ""


@dataclass(frozen=True)
class DisplacementRecord:
    pan_ordinal: int
    event_ordinal: int
    requested: Point = (0.0, 0.0)
    predicted: Point = (0.0, 0.0)
    measured: Point = (0.0, 0.0)
    residual: Point = (0.0, 0.0)
    progress_px: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class HistoricalBindingRecord:
    """Evidence-only binding snapshot.  It is always stale when persisted."""

    building_id: str
    frame_semantic_sha256: str
    confidence: float
    stale: bool = True
    historical_target_roi: Box | None = None


@dataclass(frozen=True)
class PanGestureFingerprint:
    """Semantic identity of a pan; it intentionally contains no screen coordinates."""

    route_id: str
    navigation_session_id: str
    pan_ordinal: int
    requested: Point
    predicted: Point
    source_transport_sha256: str
    source_semantic_sha256: str
    target_identity: str

    def payload(self) -> dict[str, Any]:
        return {
            "navigation_session_id": self.navigation_session_id,
            "pan_ordinal": self.pan_ordinal,
            "predicted": list(self.predicted),
            "requested": list(self.requested),
            "route_id": self.route_id,
            "source_semantic_sha256": self.source_semantic_sha256,
            "source_transport_sha256": self.source_transport_sha256,
            "target_identity": self.target_identity,
        }


@dataclass(frozen=True)
class ActionLedgerEntry:
    action_key: str
    kind: str
    status: LedgerStatus
    source_frame: FrameIdentityRecord
    target_identity: str
    pan_ordinal: int
    event_ordinal: int
    gesture_fingerprint: str = ""
    pre_uncertainty_status: str | None = None


@dataclass(frozen=True)
class ConclusiveNonDispatchEvidence:
    """Immutable attestation that a prepared pan never reached the device.

    Instances are mintable only by :class:`TrustedTransportNonDispatchAuthority`.
    Navigation callers cannot construct trusted evidence from arbitrary strings
    or booleans.
    """

    action_key: str
    gesture_fingerprint: str
    route_id: str
    navigation_session_id: str
    runtime_capture_session_id: str
    transport_attempt_id: str
    reason: ConclusiveNonDispatchReason
    authority_id: str
    attestation_digest: str
    _construction_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _NON_DISPATCH_MINT_TOKEN:
            raise NavigationSessionError("UNTRUSTED_NON_DISPATCH_EVIDENCE")
        if not self.action_key or not isinstance(self.action_key, str):
            raise NavigationSessionError("INVALID_NON_DISPATCH_EVIDENCE", "action_key")
        if not _SHA256_HEX.fullmatch(self.gesture_fingerprint or ""):
            raise NavigationSessionError("INVALID_NON_DISPATCH_EVIDENCE", "gesture_fingerprint")
        for name in (
            "route_id",
            "navigation_session_id",
            "runtime_capture_session_id",
            "transport_attempt_id",
            "authority_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise NavigationSessionError("INVALID_NON_DISPATCH_EVIDENCE", name)
        if not isinstance(self.reason, ConclusiveNonDispatchReason):
            raise NavigationSessionError("INVALID_NON_DISPATCH_EVIDENCE", "reason")
        if not _SHA256_HEX.fullmatch(self.attestation_digest or ""):
            raise NavigationSessionError("INVALID_NON_DISPATCH_EVIDENCE", "attestation_digest")


class TrustedTransportNonDispatchAuthority:
    """Reserved transport-ledger/adapter verification boundary.

    No authenticated runtime-owned verifier is wired yet, so callers cannot
    instantiate this authority. Crash-window pans must remain
    :attr:`UncertainPreparedResolution.STILL_AMBIGUOUS`.
    """

    def __init__(self, *, authority_id: str) -> None:
        raise NavigationSessionError(
            "NON_DISPATCH_AUTHORITY_UNAVAILABLE",
            authority_id if isinstance(authority_id, str) else "",
        )

    @property
    def authority_id(self) -> str:
        return self._authority_id

    def attest_conclusive_non_dispatch(
        self,
        *,
        session: "NavigationSession",
        action_key: str,
        transport_attempt_id: str,
        transport_outcome: str,
        authenticated_attestation_digest: str,
    ) -> ConclusiveNonDispatchEvidence:
        """Mint evidence only for conclusive pre-device transport outcomes."""

        validate_session(session)
        if not isinstance(transport_outcome, str) or not transport_outcome:
            raise NavigationSessionError("TRANSPORT_OUTCOME_NOT_CONCLUSIVE")
        outcome_key = transport_outcome.strip().lower()
        if outcome_key in _NONCONCLUSIVE_TRANSPORT_OUTCOMES:
            raise NavigationSessionError("TRANSPORT_OUTCOME_NOT_CONCLUSIVE", outcome_key)
        reason = _CONCLUSIVE_TRANSPORT_OUTCOME_MAP.get(outcome_key)
        if reason is None:
            raise NavigationSessionError("TRANSPORT_OUTCOME_NOT_CONCLUSIVE", outcome_key)
        if not isinstance(transport_attempt_id, str) or not transport_attempt_id:
            raise NavigationSessionError("INVALID_TRANSPORT_ATTEMPT_ID")
        if not _SHA256_HEX.fullmatch(authenticated_attestation_digest or ""):
            raise NavigationSessionError("INVALID_ATTESTATION_DIGEST")
        entry = _require_ledger_entry(session, action_key)
        if _underlying_status(entry) is not LedgerStatus.PREPARED:
            raise NavigationSessionError("NON_DISPATCH_REQUIRES_PREPARED", entry.status.value)
        if not entry.gesture_fingerprint:
            raise NavigationSessionError("MISSING_GESTURE_FINGERPRINT")
        runtime_id = entry.source_frame.runtime_capture_session_id
        if session.runtime_capture_session_id and session.runtime_capture_session_id != runtime_id:
            # Prefer the ledger source-frame runtime identity for the prepared attempt.
            pass
        return ConclusiveNonDispatchEvidence(
            action_key=entry.action_key,
            gesture_fingerprint=entry.gesture_fingerprint,
            route_id=session.route_id,
            navigation_session_id=session.navigation_session_id,
            runtime_capture_session_id=runtime_id,
            transport_attempt_id=transport_attempt_id,
            reason=reason,
            authority_id=self._authority_id,
            attestation_digest=authenticated_attestation_digest,
            _construction_token=_NON_DISPATCH_MINT_TOKEN,
        )


@dataclass(frozen=True)
class RouteResult:
    route_id: str
    status: str
    reason: str
    pan_count: int = 0
    corrections: tuple[str, ...] = ()
    continuations: int = 0
    building_id: str = ""
    building_opened: bool = False


@dataclass(frozen=True)
class ContinuationDecision:
    mode: ContinuationMode
    allowed_actions: tuple[str, ...]
    suppressed_action_keys: tuple[str, ...]
    current_binding: BuildingBinding | None
    require_observation: bool
    reason_code: str
    route_id: str
    navigation_session_id: str
    checkpoint: NavigationCheckpoint
    outcome: SessionOutcome


@dataclass
class NavigationSession:
    route_id: str
    navigation_session_id: str
    authorization: AuthorizationScope
    checkpoint: NavigationCheckpoint = NavigationCheckpoint.CREATED
    outcome: SessionOutcome = SessionOutcome.ACTIVE
    terminal_reason: str | None = None
    runtime_capture_session_id: str = ""
    event_ordinal: int = 0
    pan_ordinal: int = 0
    maximum_pans: int = 4
    continuation_mode: ContinuationMode = ContinuationMode.NORMAL
    latest_observation: LatestObservation = field(default_factory=lambda: LatestObservation(None))
    displacement_history: list[DisplacementRecord] = field(default_factory=list)
    seen_viewports: list[tuple[int, int]] = field(default_factory=list)
    action_ledger: list[ActionLedgerEntry] = field(default_factory=list)
    known_frame_identities: list[FrameIdentityRecord] = field(default_factory=list)
    historical_bindings: list[HistoricalBindingRecord] = field(default_factory=list)
    current_binding: HistoricalBindingRecord | None = None
    checkpoint_history: list[str] = field(default_factory=list)
    route_result: RouteResult | None = None
    pending_suppressions: list[str] = field(default_factory=list)
    pending_gesture_suppressions: list[str] = field(default_factory=list)
    continuation_ready_observation_frame: FrameIdentityRecord | None = None

    def __post_init__(self) -> None:
        if self.route_result is None:
            self.route_result = RouteResult(
                route_id=self.route_id,
                status="active",
                reason="created",
                building_id=self.authorization.target_building_id,
            )
        if not self.checkpoint_history:
            self.checkpoint_history = [self.checkpoint.value]

    def remember_frame(
        self, identity: NativeFrameIdentity | FrameIdentityRecord
    ) -> FrameIdentityRecord:
        record = _coerce_frame(identity)
        _validate_frame_record(record, "FRAME_IDENTITY_INVALID")
        if (
            self.runtime_capture_session_id
            and record.runtime_capture_session_id != self.runtime_capture_session_id
        ):
            self.runtime_capture_session_id = record.runtime_capture_session_id
        elif not self.runtime_capture_session_id:
            self.runtime_capture_session_id = record.runtime_capture_session_id
        if not any(existing.same_capture_event(record) for existing in self.known_frame_identities):
            self.known_frame_identities.append(record)
        return record

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_name": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "route_id": self.route_id,
            "navigation_session_id": self.navigation_session_id,
            "runtime_capture_session_id": self.runtime_capture_session_id,
            "authorization": asdict(self.authorization),
            "checkpoint": self.checkpoint.value,
            "outcome": self.outcome.value,
            "terminal_reason": self.terminal_reason,
            "event_ordinal": self.event_ordinal,
            "pan_ordinal": self.pan_ordinal,
            "maximum_pans": self.maximum_pans,
            "continuation_mode": self.continuation_mode.value,
            "latest_observation": _observation_to_dict(self.latest_observation),
            "displacement_history": [asdict(item) for item in self.displacement_history],
            "seen_viewports": [list(item) for item in self.seen_viewports],
            "action_ledger": [_ledger_to_dict(item) for item in self.action_ledger],
            "known_frame_identities": [asdict(item) for item in self.known_frame_identities],
            "historical_bindings": [asdict(item) for item in self.historical_bindings],
            "current_binding": asdict(self.current_binding) if self.current_binding else None,
            "checkpoint_history": list(self.checkpoint_history),
            "route_result": asdict(self.route_result) if self.route_result else None,
            "pending_suppressions": list(self.pending_suppressions),
            "pending_gesture_suppressions": list(self.pending_gesture_suppressions),
            "continuation_ready_observation_frame": (
                asdict(self.continuation_ready_observation_frame)
                if self.continuation_ready_observation_frame
                else None
            ),
        }


def create_session(
    authorization: AuthorizationScope,
    *,
    route_id: str | None = None,
    navigation_session_id: str | None = None,
    runtime_capture_session_id: str = "",
    maximum_pans: int = 4,
) -> NavigationSession:
    if maximum_pans < 1:
        raise NavigationSessionError("INVALID_MAXIMUM_PANS")
    if route_id is not None and not route_id:
        raise NavigationSessionError("INVALID_ROUTE_ID")
    if navigation_session_id is not None and not navigation_session_id:
        raise NavigationSessionError("INVALID_NAVIGATION_SESSION_ID")
    session = NavigationSession(
        route_id=route_id or str(uuid.uuid4()),
        navigation_session_id=navigation_session_id or str(uuid.uuid4()),
        authorization=authorization,
        runtime_capture_session_id=runtime_capture_session_id,
        maximum_pans=maximum_pans,
    )
    validate_session(session)
    return session


def save_session(
    session: NavigationSession,
    path: str | Path,
    *,
    replace: Callable[[str, str], None] | None = None,
) -> None:
    validate_session(session)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    payload = json.dumps(session.to_dict(), sort_keys=True, indent=2)
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        (replace or os.replace)(str(temporary), str(destination))
    except Exception as exc:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass
        if isinstance(exc, NavigationSessionError):
            raise
        raise NavigationSessionError("ATOMIC_REPLACE_FAILED", str(destination)) from None


def load_session(path: str | Path) -> NavigationSession:
    source = Path(path)
    try:
        raw = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise NavigationSessionError("SESSION_READ_FAILED", str(source)) from exc
    if not raw.strip():
        raise NavigationSessionError("CORRUPT_SESSION_JSON", "empty")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NavigationSessionError("CORRUPT_SESSION_JSON", str(exc)) from exc
    if not isinstance(payload, dict):
        raise NavigationSessionError("CORRUPT_SESSION_JSON", "not an object")
    if payload.get("schema_name") != SCHEMA_NAME:
        raise NavigationSessionError("UNSUPPORTED_SCHEMA", str(payload.get("schema_name")))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise NavigationSessionError(
            "UNSUPPORTED_SCHEMA_VERSION", str(payload.get("schema_version"))
        )
    try:
        session = _session_from_dict(payload)
    except NavigationSessionError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise NavigationSessionError("CORRUPT_SESSION_JSON", str(exc)) from None
    _apply_restart_uncertainty(session)
    validate_session(session)
    return session


def _apply_restart_uncertainty(session: NavigationSession) -> None:
    updated: list[ActionLedgerEntry] = []
    changed = False
    pending_keys = list(session.pending_suppressions)
    pending_fingerprints = list(session.pending_gesture_suppressions)
    for entry in session.action_ledger:
        if entry.status in (LedgerStatus.PREPARED, LedgerStatus.DISPATCHED):
            changed = True
            if entry.action_key not in pending_keys:
                pending_keys.append(entry.action_key)
            if entry.gesture_fingerprint and entry.gesture_fingerprint not in pending_fingerprints:
                pending_fingerprints.append(entry.gesture_fingerprint)
            updated.append(
                replace(
                    entry,
                    status=LedgerStatus.SUPPRESSED,
                    pre_uncertainty_status=entry.status.value,
                )
            )
        else:
            updated.append(entry)
    if not changed:
        return
    session.action_ledger = updated
    session.pending_suppressions = pending_keys
    session.pending_gesture_suppressions = pending_fingerprints
    if session.outcome is SessionOutcome.ACTIVE:
        session.outcome = SessionOutcome.UNCERTAIN
        session.terminal_reason = session.terminal_reason or "unreconciled_action_after_restart"
        _update_route_result(
            session,
            status="uncertain",
            reason=session.terminal_reason,
            pan_count=session.pan_ordinal,
        )


def advance_checkpoint(
    session: NavigationSession,
    next_checkpoint: NavigationCheckpoint,
    *,
    event_ordinal: int | None = None,
    pan_ordinal: int | None = None,
) -> None:
    validate_session(session)
    next_event, next_pan = _validate_advance(
        session,
        next_checkpoint,
        event_ordinal=event_ordinal,
        pan_ordinal=pan_ordinal,
    )
    session.event_ordinal = next_event
    session.pan_ordinal = next_pan
    session.checkpoint = next_checkpoint
    session.checkpoint_history.append(next_checkpoint.value)
    if next_checkpoint is NavigationCheckpoint.HOME_RECOVERED:
        session.outcome = SessionOutcome.COMPLETED
        session.terminal_reason = session.terminal_reason or "home_recovered"
        _update_route_result(
            session,
            status="completed",
            reason=session.terminal_reason,
            pan_count=session.pan_ordinal,
        )


def record_plan(
    session: NavigationSession,
    *,
    requested: Point = (0.0, 0.0),
    predicted: Point = (0.0, 0.0),
    remaining: Point = (0.0, 0.0),
    reason: str = "",
    seen_viewport: tuple[int, int] | None = None,
) -> None:
    validate_session(session)
    requested_point = _point(requested)
    predicted_point = _point(predicted)
    remaining_point = _point(remaining)
    if session.checkpoint not in (
        NavigationCheckpoint.SOURCE_HOME_VERIFIED,
        NavigationCheckpoint.PAN_RELOCALIZED,
        NavigationCheckpoint.PLAN_CREATED,
    ):
        raise NavigationSessionError("PLAN_NOT_PERMITTED", session.checkpoint.value)
    next_event = session.event_ordinal
    if session.checkpoint is not NavigationCheckpoint.PLAN_CREATED:
        next_event += 1
        _validate_advance(
            session,
            NavigationCheckpoint.PLAN_CREATED,
            event_ordinal=next_event,
            pan_ordinal=session.pan_ordinal,
        )
    if seen_viewport is not None:
        if len(seen_viewport) != 2:
            raise NavigationSessionError("INVALID_VIEWPORT")
        try:
            viewport = (int(seen_viewport[0]), int(seen_viewport[1]))
        except (TypeError, ValueError) as exc:
            raise NavigationSessionError("INVALID_VIEWPORT") from exc
    else:
        viewport = None
    if session.checkpoint is not NavigationCheckpoint.PLAN_CREATED:
        _advance_unchecked(
            session,
            NavigationCheckpoint.PLAN_CREATED,
            event_ordinal=next_event,
            pan_ordinal=session.pan_ordinal,
        )
    session.displacement_history.append(
        DisplacementRecord(
            pan_ordinal=session.pan_ordinal,
            event_ordinal=session.event_ordinal,
            requested=requested_point,
            predicted=predicted_point,
            residual=remaining_point,
            reason=reason,
        )
    )
    if viewport is not None and viewport not in session.seen_viewports:
        session.seen_viewports.append(viewport)


def record_pan_prepared(
    session: NavigationSession,
    *,
    action_key: str,
    source_frame: NativeFrameIdentity | FrameIdentityRecord,
    target_identity: str = "home-camera-click-drag",
    kind: str = "pan_swipe",
    requested: Point = (0.0, 0.0),
    predicted: Point = (0.0, 0.0),
    gesture_fingerprint: str | None = None,
) -> ActionLedgerEntry:
    validate_session(session)
    if not action_key:
        raise NavigationSessionError("MISSING_ACTION_KEY")
    if not target_identity or not isinstance(target_identity, str):
        raise NavigationSessionError("MISSING_TARGET_IDENTITY")
    if action_key in session.pending_suppressions:
        raise NavigationSessionError("DUPLICATE_INPUT_SUPPRESSED", action_key)
    if any(entry.action_key == action_key for entry in session.action_ledger):
        raise NavigationSessionError("DUPLICATE_ACTION_KEY", action_key)
    if session.checkpoint is not NavigationCheckpoint.PLAN_CREATED:
        raise NavigationSessionError("PREPARE_REQUIRES_PLAN", session.checkpoint.value)
    frame = _coerce_frame(source_frame)
    _validate_frame_record(frame, "FRAME_IDENTITY_INVALID")
    next_pan = session.pan_ordinal + 1
    next_event = session.event_ordinal + 1
    if next_pan > session.maximum_pans:
        raise NavigationSessionError("MAXIMUM_PAN_COUNT")
    requested_point = _point(requested)
    predicted_point = _point(predicted)
    computed = compute_pan_gesture_fingerprint(
        session,
        pan_ordinal=next_pan,
        requested=requested_point,
        predicted=predicted_point,
        source_frame=frame,
        target_identity=target_identity,
    )
    if gesture_fingerprint is not None:
        if gesture_fingerprint != computed:
            raise NavigationSessionError("GESTURE_FINGERPRINT_MISMATCH")
        fingerprint = gesture_fingerprint
    else:
        fingerprint = computed
    if fingerprint in session.pending_gesture_suppressions or any(
        entry.gesture_fingerprint == fingerprint
        for entry in session.action_ledger
        if entry.gesture_fingerprint
    ):
        raise NavigationSessionError("DUPLICATE_GESTURE_SUPPRESSED", fingerprint)
    entry = ActionLedgerEntry(
        action_key=action_key,
        kind=kind,
        status=LedgerStatus.PREPARED,
        source_frame=frame,
        target_identity=target_identity,
        pan_ordinal=next_pan,
        event_ordinal=next_event,
        gesture_fingerprint=fingerprint,
    )
    session.remember_frame(frame)
    session.action_ledger.append(entry)
    return entry


def record_pan_dispatched(session: NavigationSession, action_key: str) -> ActionLedgerEntry:
    validate_session(session)
    entry = _require_ledger_entry(session, action_key)
    if entry.status is not LedgerStatus.PREPARED:
        raise NavigationSessionError("DISPATCH_REQUIRES_PREPARED", entry.status.value)
    if entry.action_key in session.pending_suppressions:
        raise NavigationSessionError("DUPLICATE_INPUT_SUPPRESSED", action_key)
    updated = replace(entry, status=LedgerStatus.DISPATCHED)
    _validate_advance(
        session,
        NavigationCheckpoint.PAN_DISPATCHED,
        event_ordinal=updated.event_ordinal,
        pan_ordinal=updated.pan_ordinal,
    )
    session.action_ledger = [
        updated if item.action_key == action_key else item for item in session.action_ledger
    ]
    _advance_unchecked(
        session,
        NavigationCheckpoint.PAN_DISPATCHED,
        event_ordinal=updated.event_ordinal,
        pan_ordinal=updated.pan_ordinal,
    )
    return updated


def reconcile_pan(
    session: NavigationSession,
    action_key: str,
    *,
    post_frame: NativeFrameIdentity | FrameIdentityRecord,
    measured: Point = (0.0, 0.0),
    residual: Point = (0.0, 0.0),
    progress_px: float = 0.0,
    accepted: bool,
    reason: str,
    localization_confidence: float | None = None,
) -> None:
    validate_session(session)
    entry = _require_ledger_entry(session, action_key)
    if entry.status is LedgerStatus.SUPPRESSED and _underlying_status(entry) == LedgerStatus.DISPATCHED:
        reconcile_uncertain_pan(
            session,
            action_key=action_key,
            post_frame=post_frame,
            accepted=accepted,
            measured=measured,
            residual=residual,
            progress_px=progress_px,
            reason=reason,
            localization_confidence=localization_confidence,
        )
        return
    if entry.status is not LedgerStatus.DISPATCHED:
        raise NavigationSessionError("RECONCILE_REQUIRES_DISPATCHED", entry.status.value)
    post = _coerce_frame(post_frame)
    _validate_fresh_post(session, entry.source_frame, post)
    measured_point = _point(measured)
    residual_point = _point(residual)
    if not isinstance(progress_px, (int, float)) or not math.isfinite(float(progress_px)):
        raise NavigationSessionError("INVALID_PROGRESS")
    if not accepted:
        _validate_observation_frame(post)
        session.remember_frame(post)
        session.latest_observation = LatestObservation(
            frame=post,
            localization_recognized=False,
            localization_confidence=localization_confidence,
            summary=reason,
        )
        session.outcome = SessionOutcome.BLOCKED
        session.terminal_reason = reason
        _update_route_result(
            session,
            status="blocked",
            reason=reason,
            pan_count=session.pan_ordinal,
        )
        return
    _validate_advance(
        session,
        NavigationCheckpoint.PAN_RELOCALIZED,
        event_ordinal=session.event_ordinal + 1,
        pan_ordinal=session.pan_ordinal,
    )
    session.remember_frame(post)
    session.latest_observation = LatestObservation(
        frame=post,
        localization_recognized=True,
        localization_confidence=localization_confidence,
        summary=reason,
    )
    updated = replace(entry, status=LedgerStatus.RECONCILED)
    session.action_ledger = [
        updated if item.action_key == action_key else item for item in session.action_ledger
    ]
    session.displacement_history.append(
        DisplacementRecord(
            pan_ordinal=session.pan_ordinal,
            event_ordinal=session.event_ordinal + 1,
            measured=measured_point,
            residual=residual_point,
            progress_px=float(progress_px),
            reason=reason,
        )
    )
    _advance_unchecked(
        session,
        NavigationCheckpoint.PAN_RELOCALIZED,
        event_ordinal=session.event_ordinal + 1,
        pan_ordinal=session.pan_ordinal,
    )
    session.outcome = SessionOutcome.ACTIVE
    session.terminal_reason = None
    _update_route_result(
        session,
        status="active",
        reason="pan_relocalized",
        pan_count=session.pan_ordinal,
    )


def reconcile_uncertain_pan(
    session: NavigationSession,
    *,
    action_key: str | None = None,
    post_frame: NativeFrameIdentity | FrameIdentityRecord,
    accepted: bool | None = None,
    resolution: UncertainPreparedResolution | None = None,
    measured: Point = (0.0, 0.0),
    residual: Point = (0.0, 0.0),
    progress_px: float = 0.0,
    reason: str,
    localization_confidence: float | None = None,
    localization_recognized: bool | None = None,
    non_dispatch_evidence: ConclusiveNonDispatchEvidence | None = None,
    expected_transport_attempt_id: str | None = None,
) -> None:
    """Observation-only reconcile for uncertain pans after crash/restart.

    PREPARED pans require an explicit :class:`UncertainPreparedResolution`. Persisted
    PREPARED state and generic localization success never imply transport occurred.
    ``CONFIRMED_NOT_DISPATCHED`` remains unavailable until an authenticated,
    runtime-owned transport verifier exists. Zero measured progress and
    caller-supplied evidence never authorize that resolution.
    """

    validate_session(session)
    entry = _find_uncertain_entry(session, action_key)
    post = _coerce_frame(post_frame)
    _validate_fresh_post(session, entry.source_frame, post)
    if session.continuation_ready_observation_frame is not None and not post.same_capture_event(
        session.continuation_ready_observation_frame
    ):
        raise NavigationSessionError("RECONCILE_REQUIRES_CONTINUATION_OBSERVATION")
    measured_point = _point(measured)
    residual_point = _point(residual)
    if not isinstance(progress_px, (int, float)) or not math.isfinite(float(progress_px)):
        raise NavigationSessionError("INVALID_PROGRESS")
    progress_value = float(progress_px)
    underlying = _underlying_status(entry)
    if underlying not in (LedgerStatus.PREPARED, LedgerStatus.DISPATCHED):
        raise NavigationSessionError("RECONCILE_REQUIRES_UNCERTAIN_PAN", entry.status.value)

    recognized = localization_recognized
    if recognized is None and accepted is not None:
        recognized = bool(accepted)
    if recognized is None:
        recognized = True

    if underlying is LedgerStatus.DISPATCHED:
        if resolution is not None:
            raise NavigationSessionError("RESOLUTION_NOT_APPLICABLE_TO_DISPATCHED")
        if non_dispatch_evidence is not None:
            raise NavigationSessionError("NON_DISPATCH_EVIDENCE_NOT_APPLICABLE_TO_DISPATCHED")
        if accepted is None:
            raise NavigationSessionError("MISSING_ACCEPTED_FOR_DISPATCHED")
        if accepted and not recognized:
            raise NavigationSessionError("ACCEPTED_REQUIRES_RECOGNIZED_OBSERVATION")
        if accepted:
            if progress_value <= 0.0:
                raise NavigationSessionError("POSITIVE_PROGRESS_REQUIRED")
            if math.hypot(measured_point[0], measured_point[1]) <= 0.0:
                raise NavigationSessionError("POSITIVE_MEASURED_PROGRESS_REQUIRED")
            _validate_advance(
                session,
                NavigationCheckpoint.PAN_RELOCALIZED,
                event_ordinal=session.event_ordinal + 1,
                pan_ordinal=session.pan_ordinal,
            )
        _validate_observation_frame(post)
        # Mutate only after validation.
        session.remember_frame(post)
        session.latest_observation = LatestObservation(
            frame=post,
            localization_recognized=bool(accepted) and recognized,
            localization_confidence=localization_confidence,
            summary=reason,
        )
        if not accepted:
            session.outcome = SessionOutcome.BLOCKED
            session.terminal_reason = reason
            _update_route_result(
                session,
                status="blocked",
                reason=reason,
                pan_count=session.pan_ordinal,
            )
            return
        updated = replace(entry, status=LedgerStatus.RECONCILED)
        session.action_ledger = [
            updated if item.action_key == entry.action_key else item for item in session.action_ledger
        ]
        _clear_pending_suppression(session, entry)
        session.displacement_history.append(
            DisplacementRecord(
                pan_ordinal=session.pan_ordinal,
                event_ordinal=session.event_ordinal + 1,
                measured=measured_point,
                residual=residual_point,
                progress_px=progress_value,
                reason=reason,
            )
        )
        _advance_unchecked(
            session,
            NavigationCheckpoint.PAN_RELOCALIZED,
            event_ordinal=session.event_ordinal + 1,
            pan_ordinal=session.pan_ordinal,
        )
        session.outcome = SessionOutcome.ACTIVE
        session.terminal_reason = None
        _update_route_result(
            session,
            status="active",
            reason="pan_relocalized",
            pan_count=session.pan_ordinal,
        )
        return

    # PREPARED: explicit resolution only; never infer transport from ledger or localization.
    if accepted is not None and resolution is None:
        raise NavigationSessionError("PREPARED_REQUIRES_EXPLICIT_RESOLUTION")
    if resolution is None:
        raise NavigationSessionError("MISSING_PREPARED_RESOLUTION")
    if not isinstance(resolution, UncertainPreparedResolution):
        raise NavigationSessionError("INVALID_PREPARED_RESOLUTION")
    if session.checkpoint is not NavigationCheckpoint.PLAN_CREATED:
        raise NavigationSessionError(
            "UNCERTAIN_PREPARED_REQUIRES_PLAN_CREATED",
            session.checkpoint.value,
        )

    # Failed/unrecognized observation cannot confirm either transport outcome.
    effective = resolution
    if not recognized and resolution is not UncertainPreparedResolution.STILL_AMBIGUOUS:
        effective = UncertainPreparedResolution.STILL_AMBIGUOUS

    if effective is UncertainPreparedResolution.CONFIRMED_DISPATCHED_AND_RELOCALIZED:
        if non_dispatch_evidence is not None:
            raise NavigationSessionError("NON_DISPATCH_EVIDENCE_NOT_APPLICABLE")
        if progress_value <= 0.0:
            raise NavigationSessionError("POSITIVE_PROGRESS_REQUIRED")
        if math.hypot(measured_point[0], measured_point[1]) <= 0.0:
            raise NavigationSessionError("POSITIVE_MEASURED_PROGRESS_REQUIRED")
        _validate_advance(
            session,
            NavigationCheckpoint.PAN_DISPATCHED,
            event_ordinal=entry.event_ordinal,
            pan_ordinal=entry.pan_ordinal,
        )
        if NavigationCheckpoint.PAN_RELOCALIZED not in LEGAL_TRANSITIONS[NavigationCheckpoint.PAN_DISPATCHED]:
            raise NavigationSessionError("INVALID_CHECKPOINT_TRANSITION", "pan_dispatched->pan_relocalized")
        relocalized_event = entry.event_ordinal + 1
        if relocalized_event < entry.event_ordinal or entry.pan_ordinal > session.maximum_pans:
            raise NavigationSessionError("ORDINAL_REGRESSION")
    elif effective is UncertainPreparedResolution.CONFIRMED_NOT_DISPATCHED:
        # A module-local construction token is not a security boundary. Until a
        # runtime-owned verifier is available, suppression cannot be cleared by
        # any caller-provided transport claim.
        raise NavigationSessionError("NON_DISPATCH_AUTHORITY_UNAVAILABLE")
    elif effective is UncertainPreparedResolution.STILL_AMBIGUOUS:
        # Evidence is ignored; failed/unrecognized observations stay ambiguous.
        pass
    else:
        raise NavigationSessionError("INVALID_PREPARED_RESOLUTION", effective.value)

    _validate_observation_frame(post)

    # Mutate only after validation.
    session.remember_frame(post)
    session.latest_observation = LatestObservation(
        frame=post,
        localization_recognized=recognized,
        localization_confidence=localization_confidence,
        summary=reason,
    )

    if effective is UncertainPreparedResolution.STILL_AMBIGUOUS:
        session.outcome = SessionOutcome.UNCERTAIN
        session.terminal_reason = reason or "uncertain_prepared_still_ambiguous"
        _update_route_result(
            session,
            status="uncertain",
            reason=session.terminal_reason,
            pan_count=session.pan_ordinal,
        )
        return

    updated = replace(entry, status=LedgerStatus.RECONCILED)
    session.action_ledger = [
        updated if item.action_key == entry.action_key else item for item in session.action_ledger
    ]
    _clear_pending_suppression(session, entry)

    if effective is UncertainPreparedResolution.CONFIRMED_NOT_DISPATCHED:
        session.outcome = SessionOutcome.ACTIVE
        session.terminal_reason = None
        _update_route_result(
            session,
            status="active",
            reason="uncertain_prepared_confirmed_not_dispatched",
            pan_count=session.pan_ordinal,
        )
        return

    _advance_unchecked(
        session,
        NavigationCheckpoint.PAN_DISPATCHED,
        event_ordinal=entry.event_ordinal,
        pan_ordinal=entry.pan_ordinal,
    )
    session.displacement_history.append(
        DisplacementRecord(
            pan_ordinal=session.pan_ordinal,
            event_ordinal=session.event_ordinal + 1,
            measured=measured_point,
            residual=residual_point,
            progress_px=progress_value,
            reason=reason,
        )
    )
    _advance_unchecked(
        session,
        NavigationCheckpoint.PAN_RELOCALIZED,
        event_ordinal=session.event_ordinal + 1,
        pan_ordinal=session.pan_ordinal,
    )
    session.outcome = SessionOutcome.ACTIVE
    session.terminal_reason = None
    _update_route_result(
        session,
        status="active",
        reason="uncertain_prepared_confirmed_dispatched_and_relocalized",
        pan_count=session.pan_ordinal,
    )


def record_source_home_verified(
    session: NavigationSession,
    *,
    frame: NativeFrameIdentity | FrameIdentityRecord,
    localization_confidence: float | None = None,
    localization_residual_px: float | None = None,
    contextual_class: str = "",
) -> None:
    validate_session(session)
    if session.checkpoint is not NavigationCheckpoint.CREATED:
        raise NavigationSessionError("SOURCE_HOME_NOT_PERMITTED", session.checkpoint.value)
    record = _coerce_frame(frame)
    _validate_frame_record(record, "FRAME_IDENTITY_INVALID")
    _validate_advance(
        session,
        NavigationCheckpoint.SOURCE_HOME_VERIFIED,
        event_ordinal=session.event_ordinal + 1,
        pan_ordinal=session.pan_ordinal,
    )
    session.remember_frame(record)
    session.latest_observation = LatestObservation(
        frame=record,
        contextual_class=contextual_class,
        localization_recognized=True,
        localization_confidence=localization_confidence,
        localization_residual_px=localization_residual_px,
        summary="source_home_verified",
    )
    _advance_unchecked(
        session,
        NavigationCheckpoint.SOURCE_HOME_VERIFIED,
        event_ordinal=session.event_ordinal + 1,
        pan_ordinal=session.pan_ordinal,
    )


def record_target_bound(
    session: NavigationSession,
    *,
    binding: BuildingBinding,
    frame: NativeFrameIdentity | FrameIdentityRecord,
    historical_roi: Box | None = None,
) -> None:
    validate_session(session)
    if session.checkpoint not in (
        NavigationCheckpoint.PLAN_CREATED,
        NavigationCheckpoint.PAN_RELOCALIZED,
    ):
        raise NavigationSessionError("TARGET_BOUND_NOT_PERMITTED", session.checkpoint.value)
    record = _coerce_frame(frame)
    _validate_frame_record(record, "FRAME_IDENTITY_INVALID")
    if binding.building_id != session.authorization.target_building_id:
        raise NavigationSessionError("BINDING_BUILDING_MISMATCH")
    if binding.frame_sha256 != record.semantic_sha256:
        raise NavigationSessionError("STALE_BINDING")
    if historical_roi is not None:
        historical_roi = _box(historical_roi)
    else:
        historical_roi = _box(binding.target_roi)
    _validate_advance(
        session,
        NavigationCheckpoint.TARGET_BOUND,
        event_ordinal=session.event_ordinal + 1,
        pan_ordinal=session.pan_ordinal,
    )
    historical = HistoricalBindingRecord(
        building_id=binding.building_id,
        frame_semantic_sha256=binding.frame_sha256,
        confidence=binding.confidence,
        stale=True,
        historical_target_roi=historical_roi,
    )
    session.remember_frame(record)
    session.historical_bindings.append(historical)
    session.current_binding = historical
    session.latest_observation = LatestObservation(
        frame=record,
        localization_recognized=True,
        localization_confidence=binding.confidence,
        summary="target_bound",
    )
    _advance_unchecked(
        session,
        NavigationCheckpoint.TARGET_BOUND,
        event_ordinal=session.event_ordinal + 1,
        pan_ordinal=session.pan_ordinal,
    )
    session.outcome = SessionOutcome.ACTIVE
    session.terminal_reason = None
    _update_route_result(
        session,
        status="leg_complete",
        reason="current_frame_semantic_building_bound",
        pan_count=session.pan_ordinal,
    )


def complete_route_at_target_bound(session: NavigationSession) -> None:
    validate_session(session)
    if session.checkpoint is not NavigationCheckpoint.TARGET_BOUND:
        raise NavigationSessionError("TARGET_BOUND_COMPLETION_NOT_PERMITTED", session.checkpoint.value)
    if session.outcome is SessionOutcome.COMPLETED:
        raise NavigationSessionError("SESSION_ALREADY_COMPLETED")
    session.outcome = SessionOutcome.COMPLETED
    session.terminal_reason = "current_frame_semantic_building_bound"
    _update_route_result(
        session,
        status="completed",
        reason=session.terminal_reason,
        pan_count=session.pan_ordinal,
    )


def record_radial_verified(
    session: NavigationSession,
    *,
    frame: NativeFrameIdentity | FrameIdentityRecord,
) -> None:
    validate_session(session)
    if session.checkpoint is not NavigationCheckpoint.TARGET_BOUND:
        raise NavigationSessionError("RADIAL_NOT_PERMITTED", session.checkpoint.value)
    record = _coerce_frame(frame)
    _validate_frame_record(record, "FRAME_IDENTITY_INVALID")
    _validate_advance(
        session,
        NavigationCheckpoint.RADIAL_VERIFIED,
        event_ordinal=session.event_ordinal + 1,
        pan_ordinal=session.pan_ordinal,
    )
    session.remember_frame(record)
    session.latest_observation = replace(
        session.latest_observation,
        frame=record,
        summary="radial_verified",
    )
    _advance_unchecked(
        session,
        NavigationCheckpoint.RADIAL_VERIFIED,
        event_ordinal=session.event_ordinal + 1,
        pan_ordinal=session.pan_ordinal,
    )
    session.continuation_mode = ContinuationMode.RECOVERY_ONLY


def record_safe_exit(
    session: NavigationSession,
    *,
    frame: NativeFrameIdentity | FrameIdentityRecord,
) -> None:
    validate_session(session)
    if session.checkpoint is not NavigationCheckpoint.RADIAL_VERIFIED:
        raise NavigationSessionError("SAFE_EXIT_NOT_PERMITTED", session.checkpoint.value)
    record = _coerce_frame(frame)
    _validate_frame_record(record, "FRAME_IDENTITY_INVALID")
    _validate_advance(
        session,
        NavigationCheckpoint.SAFE_EXIT_VERIFIED,
        event_ordinal=session.event_ordinal + 1,
        pan_ordinal=session.pan_ordinal,
    )
    session.remember_frame(record)
    session.latest_observation = replace(
        session.latest_observation,
        frame=record,
        summary="safe_exit_verified",
    )
    _advance_unchecked(
        session,
        NavigationCheckpoint.SAFE_EXIT_VERIFIED,
        event_ordinal=session.event_ordinal + 1,
        pan_ordinal=session.pan_ordinal,
    )


def record_home_recovered(
    session: NavigationSession,
    *,
    frame: NativeFrameIdentity | FrameIdentityRecord,
) -> None:
    validate_session(session)
    if session.checkpoint is not NavigationCheckpoint.SAFE_EXIT_VERIFIED:
        raise NavigationSessionError("HOME_RECOVERY_NOT_PERMITTED", session.checkpoint.value)
    record = _coerce_frame(frame)
    _validate_frame_record(record, "FRAME_IDENTITY_INVALID")
    _validate_advance(
        session,
        NavigationCheckpoint.HOME_RECOVERED,
        event_ordinal=session.event_ordinal + 1,
        pan_ordinal=session.pan_ordinal,
    )
    session.remember_frame(record)
    session.latest_observation = replace(
        session.latest_observation,
        frame=record,
        summary="home_recovered",
    )
    _advance_unchecked(
        session,
        NavigationCheckpoint.HOME_RECOVERED,
        event_ordinal=session.event_ordinal + 1,
        pan_ordinal=session.pan_ordinal,
    )


def mark_blocked(
    session: NavigationSession,
    *,
    reason: str,
    observation: LatestObservation | None = None,
) -> None:
    validate_session(session)
    if not reason:
        raise NavigationSessionError("MISSING_BLOCK_REASON")
    prepared_observation = _prepare_observation(observation)
    session.outcome = SessionOutcome.BLOCKED
    session.terminal_reason = reason
    if prepared_observation is not None:
        session.latest_observation = prepared_observation
        if prepared_observation.frame is not None:
            session.remember_frame(prepared_observation.frame)
    if session.current_binding is not None:
        session.historical_bindings.append(replace(session.current_binding, stale=True))
        session.current_binding = None
    _update_route_result(
        session,
        status="blocked",
        reason=reason,
        pan_count=session.pan_ordinal,
    )


def mark_uncertain(
    session: NavigationSession,
    *,
    reason: str,
    observation: LatestObservation | None = None,
    suppress_action_keys: Sequence[str] = (),
) -> None:
    validate_session(session)
    if not reason:
        raise NavigationSessionError("MISSING_UNCERTAIN_REASON")
    keys = tuple(suppress_action_keys)
    entries = []
    for key in keys:
        entry = _require_ledger_entry(session, key)
        entries.append(entry)
    prepared_observation = _prepare_observation(observation)
    updated_entries = list(session.action_ledger)
    for entry in entries:
        if entry.status in (LedgerStatus.PREPARED, LedgerStatus.DISPATCHED):
            replacement = replace(
                entry,
                status=LedgerStatus.SUPPRESSED,
                pre_uncertainty_status=entry.status.value,
            )
            updated_entries = [
                replacement if item.action_key == entry.action_key else item
                for item in updated_entries
            ]
    session.action_ledger = updated_entries
    if prepared_observation is not None:
        session.latest_observation = prepared_observation
        if prepared_observation.frame is not None:
            session.remember_frame(prepared_observation.frame)
    session.outcome = SessionOutcome.UNCERTAIN
    session.terminal_reason = reason
    for entry in entries:
        if entry.action_key not in session.pending_suppressions:
            session.pending_suppressions.append(entry.action_key)
        if entry.gesture_fingerprint and entry.gesture_fingerprint not in session.pending_gesture_suppressions:
            session.pending_gesture_suppressions.append(entry.gesture_fingerprint)
    _update_route_result(
        session,
        status="uncertain",
        reason=reason,
        pan_count=session.pan_ordinal,
    )


def mark_dry_run(
    session: NavigationSession,
    *,
    reason: str = "calculated_pan_not_dispatched",
) -> None:
    """Persist a dry-run stop without marking any pan dispatched."""

    validate_session(session)
    if session.outcome is SessionOutcome.COMPLETED:
        raise NavigationSessionError("SESSION_ALREADY_COMPLETED")
    if _has_uncertain_pan(session):
        raise NavigationSessionError("UNCERTAIN_ACTION_PENDING")
    if not reason:
        raise NavigationSessionError("MISSING_DRY_RUN_REASON")
    session.outcome = SessionOutcome.COMPLETED
    session.terminal_reason = reason
    _update_route_result(
        session,
        status="dry_run",
        reason=reason,
        pan_count=session.pan_ordinal,
    )


def begin_continuation(
    session: NavigationSession,
    *,
    authorization: AuthorizationScope,
    fresh_identity: NativeFrameIdentity,
    perception_factory: Callable[[], FramePerceptionBundle],
) -> ContinuationDecision:
    """Validate a fresh observation completely before mutating continuation state."""

    validate_session(session)
    if session.outcome is SessionOutcome.COMPLETED:
        raise NavigationSessionError("SESSION_NOT_ACTIVE", session.outcome.value)
    if not authorization.matches(session.authorization):
        raise NavigationSessionError("AUTHORIZATION_MISMATCH")
    if fresh_identity.runtime_profile_id != authorization.profile:
        raise NavigationSessionError("RUNTIME_PROFILE_MISMATCH")
    if fresh_identity.runtime_profile_id != session.authorization.profile:
        raise NavigationSessionError("RUNTIME_PROFILE_MISMATCH")
    if not is_fresh_capture_event(session, fresh_identity):
        raise NavigationSessionError("STALE_OR_REUSED_CAPTURE")
    try:
        bundle = perception_factory()
    except Exception as exc:
        raise NavigationSessionError("PERCEPTION_FACTORY_FAILED", str(exc)) from None
    if not isinstance(bundle, FramePerceptionBundle):
        raise NavigationSessionError("PERCEPTION_FACTORY_INVALID")
    if bundle.invalidated_after_input:
        raise NavigationSessionError("BUNDLE_INVALIDATED_AFTER_INPUT")
    if not bundle.frame.same_capture_event(fresh_identity):
        raise NavigationSessionError("PERCEPTION_FRESH_IDENTITY_MISMATCH")
    try:
        localization, binding = bundle.checked_home_context_inputs(
            allowed_contextual_classes=_continuation_allowed_contexts(session.checkpoint)
        )
    except PerceptionBundleError as exc:
        if exc.reason_code == "WRONG_PLATFORM":
            raise NavigationSessionError("LOCALIZATION_PLATFORM_MISMATCH", str(exc)) from exc
        if exc.reason_code in {"WRONG_PROFILE", "WRONG_GEOMETRY_OR_PROFILE"}:
            raise NavigationSessionError("LOCALIZATION_PROFILE_MISMATCH", str(exc)) from exc
        raise NavigationSessionError(exc.reason_code, str(exc)) from exc
    if localization.platform != authorization.platform:
        raise NavigationSessionError("LOCALIZATION_PLATFORM_MISMATCH")
    if localization.profile_id != authorization.profile:
        raise NavigationSessionError("LOCALIZATION_PROFILE_MISMATCH")
    if binding is not None and binding.building_id != authorization.target_building_id:
        raise NavigationSessionError("BINDING_BUILDING_MISMATCH")
    if session.checkpoint is NavigationCheckpoint.RADIAL_VERIFIED:
        _require_authorized_radial(bundle, authorization=authorization, fresh_identity=fresh_identity)

    fresh_record = FrameIdentityRecord.from_native(fresh_identity)
    _validate_frame_record(fresh_record, "FRAME_IDENTITY_INVALID")
    updated_ledger: list[ActionLedgerEntry] = []
    suppressed_keys = list(session.pending_suppressions)
    suppressed_fingerprints = list(session.pending_gesture_suppressions)
    newly_suppressed = False
    for entry in session.action_ledger:
        if entry.status in (LedgerStatus.PREPARED, LedgerStatus.DISPATCHED):
            newly_suppressed = True
            if entry.action_key not in suppressed_keys:
                suppressed_keys.append(entry.action_key)
            if entry.gesture_fingerprint and entry.gesture_fingerprint not in suppressed_fingerprints:
                suppressed_fingerprints.append(entry.gesture_fingerprint)
            updated_ledger.append(
                replace(
                    entry,
                    status=LedgerStatus.SUPPRESSED,
                    pre_uncertainty_status=entry.status.value,
                )
            )
        else:
            updated_ledger.append(entry)

    has_uncertain = _has_uncertain_pan_values(updated_ledger, suppressed_keys)
    mode = (
        ContinuationMode.RECOVERY_ONLY
        if session.continuation_mode is ContinuationMode.RECOVERY_ONLY
        or session.checkpoint in RECOVERY_ONLY_CHECKPOINTS
        else ContinuationMode.NORMAL
    )
    if mode is ContinuationMode.RECOVERY_ONLY:
        allowed = _recovery_allowed_actions(session.checkpoint)
    else:
        allowed = derive_allowed_actions(
            session,
            action_ledger=updated_ledger,
            pending_suppressions=suppressed_keys,
        )

    # All rejection checks are above this point.  The continuation observation is
    # the only current binding source; persisted bindings are retained as stale history.
    session.action_ledger = updated_ledger
    session.pending_suppressions = suppressed_keys
    session.pending_gesture_suppressions = suppressed_fingerprints
    if session.current_binding is not None:
        session.historical_bindings.append(replace(session.current_binding, stale=True))
        session.current_binding = None
    session.remember_frame(fresh_record)
    session.latest_observation = LatestObservation(
        frame=fresh_record,
        contextual_class=bundle.context.contextual_class.value if bundle.context else "",
        localization_recognized=localization.recognized,
        localization_confidence=localization.confidence,
        localization_residual_px=localization.residual_px,
        summary="continuation_fresh_observation",
    )
    session.continuation_ready_observation_frame = fresh_record
    session.continuation_mode = mode
    if session.route_result is not None:
        session.route_result = replace(
            session.route_result,
            continuations=session.route_result.continuations + 1,
            corrections=session.route_result.corrections + ("continuation",),
        )
    if newly_suppressed and session.outcome is not SessionOutcome.COMPLETED:
        session.outcome = SessionOutcome.UNCERTAIN
        session.terminal_reason = "unreconciled_action_on_continuation"
        _update_route_result(
            session,
            status="uncertain",
            reason=session.terminal_reason,
            pan_count=session.pan_ordinal,
        )
    elif session.outcome is SessionOutcome.BLOCKED and not has_uncertain:
        session.outcome = SessionOutcome.ACTIVE
        session.terminal_reason = None
    elif session.outcome is SessionOutcome.UNCERTAIN and not has_uncertain:
        session.outcome = SessionOutcome.ACTIVE
        session.terminal_reason = None

    return ContinuationDecision(
        mode=mode,
        allowed_actions=allowed,
        suppressed_action_keys=tuple(suppressed_keys),
        current_binding=binding,
        require_observation=True,
        reason_code="continuation_ready",
        route_id=session.route_id,
        navigation_session_id=session.navigation_session_id,
        checkpoint=session.checkpoint,
        outcome=session.outcome,
    )


def is_fresh_capture_event(session: NavigationSession, identity: NativeFrameIdentity) -> bool:
    """Return true only for a new capture event in this runtime or a new runtime."""

    candidate = FrameIdentityRecord.from_native(identity)
    for known in session.known_frame_identities:
        if known.same_capture_event(candidate):
            return False
    if session.latest_observation.frame is not None and session.latest_observation.frame.same_capture_event(
        candidate
    ):
        return False
    if (
        session.continuation_ready_observation_frame is not None
        and session.continuation_ready_observation_frame.same_capture_event(candidate)
    ):
        return False
    if not session.runtime_capture_session_id:
        return True
    if candidate.runtime_capture_session_id != session.runtime_capture_session_id:
        return True
    maximum = 0
    for known in session.known_frame_identities:
        if known.runtime_capture_session_id == candidate.runtime_capture_session_id:
            maximum = max(maximum, known.capture_ordinal)
    if session.latest_observation.frame is not None:
        latest = session.latest_observation.frame
        if latest.runtime_capture_session_id == candidate.runtime_capture_session_id:
            maximum = max(maximum, latest.capture_ordinal)
    return candidate.capture_ordinal > maximum


def executable_tap_roi_from_session(_session: NavigationSession) -> None:
    """Sessions never expose a trusted tap ROI for dispatch."""

    return None


def compute_pan_gesture_fingerprint(
    session: NavigationSession | None = None,
    *,
    route_id: str | None = None,
    navigation_session_id: str | None = None,
    pan_ordinal: int | None = None,
    requested: Point = (0.0, 0.0),
    predicted: Point = (0.0, 0.0),
    source_frame: NativeFrameIdentity | FrameIdentityRecord | None = None,
    source_transport_sha256: str | None = None,
    source_semantic_sha256: str | None = None,
    target_identity: str = "home-camera-click-drag",
) -> str:
    """Return a deterministic SHA-256 identity for one semantic pan gesture."""

    resolved_route = route_id if route_id is not None else session.route_id if session else None
    resolved_session = (
        navigation_session_id
        if navigation_session_id is not None
        else session.navigation_session_id if session else None
    )
    if resolved_route is None or not resolved_route:
        raise NavigationSessionError("MISSING_ROUTE_ID")
    if resolved_session is None or not resolved_session:
        raise NavigationSessionError("MISSING_NAVIGATION_SESSION_ID")
    if pan_ordinal is None or pan_ordinal < 0:
        raise NavigationSessionError("INVALID_PAN_ORDINAL")
    if not target_identity or not isinstance(target_identity, str):
        raise NavigationSessionError("MISSING_TARGET_IDENTITY")
    if source_frame is not None:
        frame = _coerce_frame(source_frame)
        transport = frame.transport_sha256
        semantic = frame.semantic_sha256
    else:
        transport = source_transport_sha256
        semantic = source_semantic_sha256
    if transport is None or semantic is None:
        raise NavigationSessionError("MISSING_SOURCE_FRAME_DIGEST")
    _require_digest(transport, "source_transport_sha256")
    _require_digest(semantic, "source_semantic_sha256")
    fingerprint = PanGestureFingerprint(
        route_id=resolved_route,
        navigation_session_id=resolved_session,
        pan_ordinal=int(pan_ordinal),
        requested=_point(requested),
        predicted=_point(predicted),
        source_transport_sha256=transport,
        source_semantic_sha256=semantic,
        target_identity=target_identity,
    )
    canonical = json.dumps(fingerprint.payload(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def make_pan_action_key(
    session: NavigationSession,
    fingerprint_digest: str,
    pan_ordinal: int,
) -> str:
    if not session.route_id:
        raise NavigationSessionError("MISSING_ROUTE_ID")
    if not _SHA256_HEX.fullmatch(fingerprint_digest):
        raise NavigationSessionError("INVALID_GESTURE_FINGERPRINT")
    if pan_ordinal < 0:
        raise NavigationSessionError("INVALID_PAN_ORDINAL")
    return f"nav-pan:{session.route_id}:{pan_ordinal}:{fingerprint_digest[:16]}"


def derive_allowed_actions(
    session: NavigationSession,
    *,
    action_ledger: Sequence[ActionLedgerEntry] | None = None,
    pending_suppressions: Sequence[str] | None = None,
) -> tuple[str, ...]:
    """Derive safe semantic actions from the checkpoint and unresolved ledger."""

    ledger = tuple(action_ledger if action_ledger is not None else session.action_ledger)
    pending = tuple(
        pending_suppressions
        if pending_suppressions is not None
        else session.pending_suppressions
    )
    actions: list[str] = ["observe"]
    uncertain = _has_uncertain_pan_values(ledger, pending)
    if session.continuation_mode is ContinuationMode.RECOVERY_ONLY or session.checkpoint in (
        NavigationCheckpoint.RADIAL_VERIFIED,
        NavigationCheckpoint.SAFE_EXIT_VERIFIED,
    ):
        return _recovery_allowed_actions(session.checkpoint)
    if uncertain:
        actions.append("reconcile_observation")
        # Uncertain prepared/dispatched/suppressed pans must be observation-reconciled
        # before any new plan or bind is advertised.
        return tuple(dict.fromkeys(actions))
    if session.checkpoint is NavigationCheckpoint.CREATED:
        actions.append("verify_source")
    if session.checkpoint in (
        NavigationCheckpoint.SOURCE_HOME_VERIFIED,
        NavigationCheckpoint.PAN_RELOCALIZED,
        NavigationCheckpoint.PLAN_CREATED,
    ):
        actions.append("plan")
    if session.checkpoint in (
        NavigationCheckpoint.PLAN_CREATED,
        NavigationCheckpoint.PAN_RELOCALIZED,
    ):
        actions.append("bind")
    if session.checkpoint is NavigationCheckpoint.TARGET_BOUND:
        actions.extend(("radial", "complete"))
    return tuple(dict.fromkeys(actions))


def validate_session(session: NavigationSession) -> None:
    """Validate every persisted invariant without changing the supplied session."""

    if not isinstance(session, NavigationSession):
        raise NavigationSessionError("INVALID_SESSION")
    if not session.route_id:
        raise NavigationSessionError("MISSING_ROUTE_ID")
    if not session.navigation_session_id:
        raise NavigationSessionError("MISSING_NAVIGATION_SESSION_ID")
    if not isinstance(session.authorization, AuthorizationScope):
        raise NavigationSessionError("INVALID_AUTHORIZATION_SCOPE")
    for name, value in asdict(session.authorization).items():
        if not isinstance(value, str) or not value:
            raise NavigationSessionError("INVALID_AUTHORIZATION_SCOPE", name)
    if session.maximum_pans < 1:
        raise NavigationSessionError("INVALID_MAXIMUM_PANS")
    if session.event_ordinal < 0 or session.pan_ordinal < 0:
        raise NavigationSessionError("ORDINAL_NEGATIVE")
    if session.pan_ordinal > session.maximum_pans:
        raise NavigationSessionError("PAN_ORDINAL_EXCEEDS_MAXIMUM")
    if session.route_result is None or session.route_result.route_id != session.route_id:
        raise NavigationSessionError("ROUTE_RESULT_ID_MISMATCH")
    if not session.checkpoint_history:
        raise NavigationSessionError("CHECKPOINT_HISTORY_EMPTY")
    if session.checkpoint_history[0] != NavigationCheckpoint.CREATED.value:
        raise NavigationSessionError("CHECKPOINT_HISTORY_START_INVALID")
    if session.checkpoint_history[-1] != session.checkpoint.value:
        raise NavigationSessionError("CHECKPOINT_HISTORY_END_INVALID")
    expected_event_ordinal = len(session.checkpoint_history) - 1
    if session.event_ordinal != expected_event_ordinal:
        raise NavigationSessionError(
            "EVENT_ORDINAL_INCONSISTENT_WITH_HISTORY",
            f"event_ordinal={session.event_ordinal} expected={expected_event_ordinal}",
        )
    dispatched_count = sum(
        1
        for item in session.checkpoint_history
        if item == NavigationCheckpoint.PAN_DISPATCHED.value
    )
    if session.pan_ordinal != dispatched_count:
        raise NavigationSessionError(
            "PAN_ORDINAL_INCONSISTENT_WITH_HISTORY",
            f"pan_ordinal={session.pan_ordinal} dispatched_count={dispatched_count}",
        )
    previous: NavigationCheckpoint | None = None
    for history_index, raw_checkpoint in enumerate(session.checkpoint_history):
        try:
            current = NavigationCheckpoint(raw_checkpoint)
        except ValueError:
            raise NavigationSessionError("CHECKPOINT_HISTORY_INVALID", str(raw_checkpoint)) from None
        if previous is not None:
            if current is previous:
                raise NavigationSessionError("CHECKPOINT_HISTORY_DUPLICATE")
            if current not in LEGAL_TRANSITIONS[previous]:
                raise NavigationSessionError(
                    "CHECKPOINT_HISTORY_INVALID",
                    f"{previous.value}->{current.value}",
                )
        if current is NavigationCheckpoint.PAN_DISPATCHED:
            matches = [
                entry
                for entry in session.action_ledger
                if entry.kind.startswith("pan") and entry.pan_ordinal == (
                    sum(
                        1
                        for item in session.checkpoint_history[: history_index + 1]
                        if item == NavigationCheckpoint.PAN_DISPATCHED.value
                    )
                )
            ]
            if not matches:
                raise NavigationSessionError("LEDGER_MISSING_PAN_FOR_CHECKPOINT", str(history_index))
            if matches[0].event_ordinal != history_index:
                raise NavigationSessionError(
                    "LEDGER_EVENT_ORDINAL_CHECKPOINT_MISMATCH",
                    f"ledger={matches[0].event_ordinal} history_index={history_index}",
                )
        previous = current
    if session.current_binding is not None and not session.current_binding.stale:
        raise NavigationSessionError("CURRENT_BINDING_NOT_STALE")
    for binding in session.historical_bindings:
        if not binding.stale:
            raise NavigationSessionError("HISTORICAL_BINDING_NOT_STALE")
        _require_digest(binding.frame_semantic_sha256, "historical_binding.frame_semantic_sha256")

    for frame in _all_frames(session):
        _validate_frame_record(frame, "FRAME_IDENTITY_INVALID")
    seen_keys: set[str] = set()
    seen_fingerprints: set[str] = set()
    previous_event = -1
    previous_pan = -1
    for entry in session.action_ledger:
        if not entry.action_key or entry.action_key in seen_keys:
            raise NavigationSessionError("DUPLICATE_ACTION_KEY", entry.action_key)
        seen_keys.add(entry.action_key)
        if entry.gesture_fingerprint:
            if not _SHA256_HEX.fullmatch(entry.gesture_fingerprint):
                raise NavigationSessionError("INVALID_GESTURE_FINGERPRINT")
            if entry.gesture_fingerprint in seen_fingerprints:
                raise NavigationSessionError("DUPLICATE_GESTURE_FINGERPRINT")
            seen_fingerprints.add(entry.gesture_fingerprint)
        if entry.pan_ordinal < 0 or entry.event_ordinal < 0:
            raise NavigationSessionError("ORDINAL_NEGATIVE")
        if entry.pan_ordinal > session.maximum_pans:
            raise NavigationSessionError("PAN_ORDINAL_EXCEEDS_MAXIMUM")
        if entry.event_ordinal < previous_event or entry.pan_ordinal < previous_pan:
            raise NavigationSessionError("LEDGER_ORDINAL_REGRESSION")
        if entry.event_ordinal > session.event_ordinal + 1:
            raise NavigationSessionError("LEDGER_EVENT_ORDINAL_INVALID")
        if entry.pan_ordinal > session.pan_ordinal + 1:
            raise NavigationSessionError("LEDGER_PAN_ORDINAL_INVALID")
        if entry.status is LedgerStatus.SUPPRESSED:
            if entry.pre_uncertainty_status not in (
                LedgerStatus.PREPARED.value,
                LedgerStatus.DISPATCHED.value,
            ):
                raise NavigationSessionError("SUPPRESSED_STATUS_ORIGIN_INVALID")
        elif entry.pre_uncertainty_status is not None and entry.pre_uncertainty_status not in (
            LedgerStatus.PREPARED.value,
            LedgerStatus.DISPATCHED.value,
        ):
            raise NavigationSessionError("PRE_UNCERTAINTY_STATUS_INVALID")
        previous_event = entry.event_ordinal
        previous_pan = entry.pan_ordinal
    if any(key not in seen_keys for key in session.pending_suppressions):
        raise NavigationSessionError("PENDING_SUPPRESSION_UNKNOWN")
    if any(
        digest not in seen_fingerprints for digest in session.pending_gesture_suppressions
    ):
        raise NavigationSessionError("PENDING_GESTURE_SUPPRESSION_UNKNOWN")

    if session.outcome is SessionOutcome.COMPLETED:
        if session.checkpoint is not NavigationCheckpoint.HOME_RECOVERED and not (
            session.route_result.status == "dry_run"
            or session.checkpoint is NavigationCheckpoint.TARGET_BOUND
        ):
            raise NavigationSessionError("COMPLETED_CHECKPOINT_MISMATCH")
    if session.checkpoint is NavigationCheckpoint.HOME_RECOVERED and session.outcome is not SessionOutcome.COMPLETED:
        raise NavigationSessionError("HOME_RECOVERED_OUTCOME_MISMATCH")
    if session.outcome is SessionOutcome.UNCERTAIN and not (
        _has_uncertain_pan(session) or session.terminal_reason
    ):
        raise NavigationSessionError("UNCERTAIN_REASON_MISSING")
    if session.checkpoint is NavigationCheckpoint.TARGET_BOUND:
        if session.route_result.status not in ("leg_complete", "completed"):
            raise NavigationSessionError("TARGET_BOUND_ROUTE_RESULT_INVALID")
        if session.outcome is SessionOutcome.COMPLETED and session.route_result.status != "completed":
            raise NavigationSessionError("TARGET_BOUND_COMPLETION_RESULT_INVALID")
    if session.continuation_ready_observation_frame is not None:
        _validate_frame_record(
            session.continuation_ready_observation_frame,
            "FRAME_IDENTITY_INVALID",
        )


def _validate_advance(
    session: NavigationSession,
    next_checkpoint: NavigationCheckpoint,
    *,
    event_ordinal: int | None,
    pan_ordinal: int | None,
) -> tuple[int, int]:
    if session.outcome is SessionOutcome.COMPLETED:
        raise NavigationSessionError("SESSION_NOT_ACTIVE", session.outcome.value)
    allowed = LEGAL_TRANSITIONS.get(session.checkpoint, frozenset())
    if next_checkpoint not in allowed:
        raise NavigationSessionError(
            "INVALID_CHECKPOINT_TRANSITION",
            f"{session.checkpoint.value}->{next_checkpoint.value}",
        )
    if session.continuation_mode is ContinuationMode.RECOVERY_ONLY and (
        session.checkpoint,
        next_checkpoint,
    ) not in _RECOVERY_TRANSITIONS:
        raise NavigationSessionError("RECOVERY_ONLY_TRANSITION_DENIED", next_checkpoint.value)
    next_event = session.event_ordinal if event_ordinal is None else int(event_ordinal)
    next_pan = session.pan_ordinal if pan_ordinal is None else int(pan_ordinal)
    if next_event < session.event_ordinal or next_pan < session.pan_ordinal:
        raise NavigationSessionError("ORDINAL_REGRESSION")
    if next_pan > session.maximum_pans:
        raise NavigationSessionError("MAXIMUM_PAN_COUNT")
    if (
        session.checkpoint is NavigationCheckpoint.PAN_RELOCALIZED
        and next_checkpoint is NavigationCheckpoint.PLAN_CREATED
        and next_pan == session.pan_ordinal
        and next_event == session.event_ordinal
    ):
        raise NavigationSessionError("ORDINAL_REGRESSION", "multi-pan cycle requires ordinal progress")
    return next_event, next_pan


def _advance_unchecked(
    session: NavigationSession,
    next_checkpoint: NavigationCheckpoint,
    *,
    event_ordinal: int,
    pan_ordinal: int,
) -> None:
    session.event_ordinal = event_ordinal
    session.pan_ordinal = pan_ordinal
    session.checkpoint = next_checkpoint
    session.checkpoint_history.append(next_checkpoint.value)
    if next_checkpoint is NavigationCheckpoint.HOME_RECOVERED:
        session.outcome = SessionOutcome.COMPLETED
        session.terminal_reason = session.terminal_reason or "home_recovered"
        _update_route_result(
            session,
            status="completed",
            reason=session.terminal_reason,
            pan_count=session.pan_ordinal,
        )


def _coerce_frame(identity: NativeFrameIdentity | FrameIdentityRecord) -> FrameIdentityRecord:
    if isinstance(identity, FrameIdentityRecord):
        return identity
    if isinstance(identity, NativeFrameIdentity):
        return FrameIdentityRecord.from_native(identity)
    raise NavigationSessionError("FRAME_IDENTITY_INVALID")


def _validate_frame_record(record: FrameIdentityRecord, reason_code: str) -> None:
    if not record.runtime_capture_session_id or record.capture_ordinal < 1:
        raise NavigationSessionError(reason_code)
    if record.width <= 0 or record.height <= 0 or not record.runtime_profile_id:
        raise NavigationSessionError(reason_code)
    _require_digest(record.transport_sha256, "transport_sha256", reason_code)
    _require_digest(record.semantic_sha256, "semantic_sha256", reason_code)


def _require_digest(value: str, field: str, reason_code: str = "INVALID_DIGEST") -> None:
    if not isinstance(value, str) or not _SHA256_HEX.fullmatch(value):
        raise NavigationSessionError(reason_code, field)


def _point(value: Point) -> Point:
    try:
        if len(value) != 2:
            raise ValueError
        point = (float(value[0]), float(value[1]))
    except (TypeError, ValueError, IndexError):
        raise NavigationSessionError("INVALID_POINT") from None
    if not all(math.isfinite(item) for item in point):
        raise NavigationSessionError("INVALID_POINT")
    return point


def _box(value: Box) -> Box:
    try:
        if len(value) != 4:
            raise ValueError
        result = tuple(int(item) for item in value)
    except (TypeError, ValueError, IndexError):
        raise NavigationSessionError("INVALID_ROI") from None
    if result[2] < result[0] or result[3] < result[1]:
        raise NavigationSessionError("INVALID_ROI")
    return result  # type: ignore[return-value]


def _validate_observation_frame(frame: FrameIdentityRecord) -> None:
    _validate_frame_record(frame, "FRAME_IDENTITY_INVALID")


def _validate_fresh_post(
    session: NavigationSession,
    source: FrameIdentityRecord,
    post: FrameIdentityRecord,
) -> None:
    _validate_frame_record(post, "FRAME_IDENTITY_INVALID")
    if post.same_capture_event(source):
        raise NavigationSessionError("RECONCILE_REQUIRES_FRESH_POST")
    if not is_fresh_capture_event(session, post.to_native()) and not (
        session.continuation_ready_observation_frame is not None
        and post.same_capture_event(session.continuation_ready_observation_frame)
    ):
        raise NavigationSessionError("RECONCILE_REQUIRES_FRESH_POST")


def _prepare_observation(observation: LatestObservation | None) -> LatestObservation | None:
    if observation is None:
        return None
    if observation.frame is not None:
        _validate_frame_record(observation.frame, "FRAME_IDENTITY_INVALID")
    return observation


def _require_ledger_entry(session: NavigationSession, action_key: str) -> ActionLedgerEntry:
    for entry in session.action_ledger:
        if entry.action_key == action_key:
            return entry
    raise NavigationSessionError("UNKNOWN_ACTION_KEY", action_key)


def _underlying_status(entry: ActionLedgerEntry) -> LedgerStatus | None:
    if entry.status is LedgerStatus.SUPPRESSED:
        if entry.pre_uncertainty_status is None:
            return None
        try:
            return LedgerStatus(entry.pre_uncertainty_status)
        except ValueError:
            return None
    return entry.status


def _find_uncertain_entry(
    session: NavigationSession,
    action_key: str | None,
) -> ActionLedgerEntry:
    if action_key is not None:
        entry = _require_ledger_entry(session, action_key)
        if _underlying_status(entry) not in (LedgerStatus.PREPARED, LedgerStatus.DISPATCHED):
            raise NavigationSessionError("RECONCILE_REQUIRES_UNCERTAIN_PAN", entry.status.value)
        return entry
    for entry in reversed(session.action_ledger):
        if _underlying_status(entry) in (LedgerStatus.PREPARED, LedgerStatus.DISPATCHED):
            return entry
    raise NavigationSessionError("NO_UNCERTAIN_PAN")


def _remove_pending_key(session: NavigationSession, action_key: str) -> None:
    session.pending_suppressions = [
        key for key in session.pending_suppressions if key != action_key
    ]


def _clear_pending_suppression(session: NavigationSession, entry: ActionLedgerEntry) -> None:
    _remove_pending_key(session, entry.action_key)
    if entry.gesture_fingerprint:
        session.pending_gesture_suppressions = [
            digest
            for digest in session.pending_gesture_suppressions
            if digest != entry.gesture_fingerprint
        ]


def _validate_conclusive_non_dispatch_evidence(
    session: NavigationSession,
    entry: ActionLedgerEntry,
    evidence: ConclusiveNonDispatchEvidence,
) -> None:
    if not isinstance(evidence, ConclusiveNonDispatchEvidence):
        raise NavigationSessionError("INVALID_NON_DISPATCH_EVIDENCE")
    # Re-run construction invariants (rejects forged/malformed instances).
    if evidence._construction_token is not _NON_DISPATCH_MINT_TOKEN:
        raise NavigationSessionError("UNTRUSTED_NON_DISPATCH_EVIDENCE")
    if evidence.action_key != entry.action_key:
        raise NavigationSessionError("NON_DISPATCH_ACTION_KEY_MISMATCH")
    if evidence.gesture_fingerprint != entry.gesture_fingerprint:
        raise NavigationSessionError("NON_DISPATCH_GESTURE_MISMATCH")
    if evidence.route_id != session.route_id:
        raise NavigationSessionError("NON_DISPATCH_ROUTE_MISMATCH")
    if evidence.navigation_session_id != session.navigation_session_id:
        raise NavigationSessionError("NON_DISPATCH_SESSION_MISMATCH")
    if evidence.runtime_capture_session_id != entry.source_frame.runtime_capture_session_id:
        raise NavigationSessionError("NON_DISPATCH_RUNTIME_SESSION_MISMATCH")
    if not evidence.transport_attempt_id:
        raise NavigationSessionError("NON_DISPATCH_TRANSPORT_ATTEMPT_MISSING")
    if evidence.reason not in ConclusiveNonDispatchReason:
        raise NavigationSessionError("NON_DISPATCH_REASON_INVALID")
    if not evidence.authority_id:
        raise NavigationSessionError("NON_DISPATCH_AUTHORITY_MISSING")
    if not _SHA256_HEX.fullmatch(evidence.attestation_digest):
        raise NavigationSessionError("NON_DISPATCH_ATTESTATION_INVALID")


def _require_authorized_radial(
    bundle: FramePerceptionBundle,
    *,
    authorization: AuthorizationScope,
    fresh_identity: NativeFrameIdentity,
) -> None:
    radial = bundle.radial
    if radial is None:
        raise NavigationSessionError("RADIAL_OBSERVATION_MISSING")
    if not radial.source_frame.same_capture_event(fresh_identity):
        raise NavigationSessionError("RADIAL_CAPTURE_EVENT_MISMATCH")
    facility = radial.facility_identity
    if not isinstance(facility, str) or not facility.strip():
        raise NavigationSessionError("RADIAL_FACILITY_UNKNOWN")
    if facility != authorization.target_building_id:
        raise NavigationSessionError("RADIAL_FACILITY_MISMATCH", facility)


def _has_uncertain_pan(session: NavigationSession) -> bool:
    return _has_uncertain_pan_values(session.action_ledger, session.pending_suppressions)


def _has_uncertain_pan_values(
    ledger: Sequence[ActionLedgerEntry],
    pending_suppressions: Sequence[str],
) -> bool:
    pending = set(pending_suppressions)
    return any(
        entry.action_key in pending
        and entry.kind.startswith("pan")
        and _underlying_status(entry) in (LedgerStatus.PREPARED, LedgerStatus.DISPATCHED)
        for entry in ledger
    ) or any(
        entry.kind.startswith("pan")
        and entry.status in (LedgerStatus.PREPARED, LedgerStatus.DISPATCHED, LedgerStatus.SUPPRESSED)
        and _underlying_status(entry) in (LedgerStatus.PREPARED, LedgerStatus.DISPATCHED)
        for entry in ledger
    )


def _recovery_allowed_actions(checkpoint: NavigationCheckpoint) -> tuple[str, ...]:
    actions = ["observe"]
    if checkpoint is NavigationCheckpoint.RADIAL_VERIFIED:
        actions.append("safe_exit")
    elif checkpoint is NavigationCheckpoint.SAFE_EXIT_VERIFIED:
        actions.append("recover_home")
    return tuple(actions)


def _continuation_allowed_contexts(
    checkpoint: NavigationCheckpoint,
) -> frozenset[ContextualClass]:
    """Checkpoint-specific Home contexts accepted by begin_continuation."""

    if checkpoint is NavigationCheckpoint.RADIAL_VERIFIED:
        # Canonical Home is admitted only so a missing radial can fail the explicit
        # facility check with RADIAL_OBSERVATION_MISSING instead of a context error.
        return frozenset(
            {ContextualClass.HOME_WITH_KNOWN_RADIAL, ContextualClass.CANONICAL_HOME}
        )
    return frozenset({ContextualClass.CANONICAL_HOME})


def _all_frames(session: NavigationSession) -> tuple[FrameIdentityRecord, ...]:
    frames: list[FrameIdentityRecord] = list(session.known_frame_identities)
    if session.latest_observation.frame is not None:
        frames.append(session.latest_observation.frame)
    if session.current_binding is not None:
        pass
    if session.continuation_ready_observation_frame is not None:
        frames.append(session.continuation_ready_observation_frame)
    frames.extend(entry.source_frame for entry in session.action_ledger)
    return tuple(frames)


def _update_route_result(
    session: NavigationSession,
    *,
    status: str,
    reason: str,
    pan_count: int | None = None,
) -> None:
    current = session.route_result or RouteResult(
        route_id=session.route_id,
        status=status,
        reason=reason,
        building_id=session.authorization.target_building_id,
    )
    session.route_result = replace(
        current,
        route_id=session.route_id,
        status=status,
        reason=reason,
        pan_count=session.pan_ordinal if pan_count is None else pan_count,
    )


def _observation_to_dict(observation: LatestObservation) -> dict[str, Any]:
    return {
        "frame": asdict(observation.frame) if observation.frame else None,
        "contextual_class": observation.contextual_class,
        "localization_recognized": observation.localization_recognized,
        "localization_confidence": observation.localization_confidence,
        "localization_residual_px": observation.localization_residual_px,
        "summary": observation.summary,
    }


def _ledger_to_dict(entry: ActionLedgerEntry) -> dict[str, Any]:
    payload = asdict(entry)
    payload["status"] = entry.status.value
    return payload


def _session_from_dict(payload: Mapping[str, Any]) -> NavigationSession:
    required = (
        "route_id",
        "navigation_session_id",
        "authorization",
        "checkpoint",
        "outcome",
    )
    for key in required:
        if key not in payload:
            raise NavigationSessionError("CORRUPT_SESSION_JSON", key)
    auth_raw = payload["authorization"]
    if not isinstance(auth_raw, Mapping):
        raise NavigationSessionError("CORRUPT_SESSION_JSON", "authorization")
    auth = AuthorizationScope(**dict(auth_raw))
    latest_raw = payload.get("latest_observation") or {}
    if not isinstance(latest_raw, Mapping):
        raise NavigationSessionError("CORRUPT_SESSION_JSON", "latest_observation")
    latest_frame_raw = latest_raw.get("frame")
    latest = LatestObservation(
        frame=FrameIdentityRecord(**latest_frame_raw) if latest_frame_raw else None,
        contextual_class=str(latest_raw.get("contextual_class", "")),
        localization_recognized=latest_raw.get("localization_recognized"),
        localization_confidence=latest_raw.get("localization_confidence"),
        localization_residual_px=latest_raw.get("localization_residual_px"),
        summary=str(latest_raw.get("summary", "")),
    )
    ledger: list[ActionLedgerEntry] = []
    for item in payload.get("action_ledger") or []:
        if not isinstance(item, Mapping):
            raise NavigationSessionError("CORRUPT_SESSION_JSON", "action_ledger")
        ledger.append(
            ActionLedgerEntry(
                action_key=str(item["action_key"]),
                kind=str(item["kind"]),
                status=LedgerStatus(item["status"]),
                source_frame=FrameIdentityRecord(**item["source_frame"]),
                target_identity=str(item["target_identity"]),
                pan_ordinal=int(item["pan_ordinal"]),
                event_ordinal=int(item["event_ordinal"]),
                gesture_fingerprint=str(item.get("gesture_fingerprint", "")),
                pre_uncertainty_status=item.get("pre_uncertainty_status"),
            )
        )
    route_raw = payload.get("route_result")
    route = None
    if route_raw:
        route = RouteResult(
            route_id=str(route_raw["route_id"]),
            status=str(route_raw["status"]),
            reason=str(route_raw["reason"]),
            pan_count=int(route_raw.get("pan_count", 0)),
            corrections=tuple(route_raw.get("corrections") or ()),
            continuations=int(route_raw.get("continuations", 0)),
            building_id=str(route_raw.get("building_id", "")),
            building_opened=bool(route_raw.get("building_opened", False)),
        )
    current_binding_raw = payload.get("current_binding")
    current_binding = (
        HistoricalBindingRecord(**current_binding_raw) if current_binding_raw else None
    )
    continuation_frame_raw = payload.get("continuation_ready_observation_frame")
    continuation_frame = (
        FrameIdentityRecord(**continuation_frame_raw) if continuation_frame_raw else None
    )
    return NavigationSession(
        route_id=str(payload["route_id"]),
        navigation_session_id=str(payload["navigation_session_id"]),
        authorization=auth,
        checkpoint=NavigationCheckpoint(payload["checkpoint"]),
        outcome=SessionOutcome(payload["outcome"]),
        terminal_reason=payload.get("terminal_reason"),
        runtime_capture_session_id=str(payload.get("runtime_capture_session_id", "")),
        event_ordinal=int(payload.get("event_ordinal", 0)),
        pan_ordinal=int(payload.get("pan_ordinal", 0)),
        maximum_pans=int(payload.get("maximum_pans", 4)),
        continuation_mode=ContinuationMode(payload.get("continuation_mode", "normal")),
        latest_observation=latest,
        displacement_history=[
            DisplacementRecord(**item) for item in payload.get("displacement_history") or []
        ],
        seen_viewports=[tuple(item) for item in payload.get("seen_viewports") or []],
        action_ledger=ledger,
        known_frame_identities=[
            FrameIdentityRecord(**item)
            for item in payload.get("known_frame_identities") or []
        ],
        historical_bindings=[
            HistoricalBindingRecord(**item)
            for item in payload.get("historical_bindings") or []
        ],
        current_binding=current_binding,
        checkpoint_history=list(payload.get("checkpoint_history") or []),
        route_result=route,
        pending_suppressions=list(payload.get("pending_suppressions") or []),
        pending_gesture_suppressions=list(
            payload.get("pending_gesture_suppressions") or []
        ),
        continuation_ready_observation_frame=continuation_frame,
    )


__all__ = [
    "SCHEMA_NAME",
    "SCHEMA_VERSION",
    "LEGAL_TRANSITIONS",
    "AuthorizationScope",
    "FrameIdentityRecord",
    "LatestObservation",
    "DisplacementRecord",
    "HistoricalBindingRecord",
    "PanGestureFingerprint",
    "ActionLedgerEntry",
    "RouteResult",
    "ContinuationDecision",
    "NavigationCheckpoint",
    "SessionOutcome",
    "LedgerStatus",
    "ContinuationMode",
    "UncertainPreparedResolution",
    "ConclusiveNonDispatchReason",
    "ConclusiveNonDispatchEvidence",
    "TrustedTransportNonDispatchAuthority",
    "NavigationSession",
    "NavigationSessionError",
    "create_session",
    "save_session",
    "load_session",
    "advance_checkpoint",
    "record_plan",
    "record_pan_prepared",
    "record_pan_dispatched",
    "reconcile_pan",
    "reconcile_uncertain_pan",
    "record_source_home_verified",
    "record_target_bound",
    "complete_route_at_target_bound",
    "record_radial_verified",
    "record_safe_exit",
    "record_home_recovered",
    "mark_blocked",
    "mark_uncertain",
    "mark_dry_run",
    "begin_continuation",
    "is_fresh_capture_event",
    "executable_tap_roi_from_session",
    "compute_pan_gesture_fingerprint",
    "make_pan_action_key",
    "derive_allowed_actions",
    "validate_session",
]
