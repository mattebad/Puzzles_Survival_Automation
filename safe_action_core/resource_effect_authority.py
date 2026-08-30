"""Resource-only occurrence/effect authority over the v4 SafetyStore.

This module deliberately owns no device transport.  It persists the identity,
claim, reservation, transport-intent, effect, block, and observation facts that
make the existing Resource route fail closed without pretending that SQLite and
the external game are one transaction.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from .models import (
    ActionClass,
    ActionIntent,
    CapabilityConsumeResult,
    EffectDispatchFence,
    InputCapability,
    PolicyResult,
    PolicyRequest,
    ResourceAuthorizationContext,
    TransportResult,
    snapshot,
)
from .store import SafetyStore, StoreError


RESOURCE_FLOW_ID = "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION"
RESOURCE_RECURRENCE_CLASS = "daily_reset"
RESOURCE_OBJECTIVE_ACTION_ID = "use_resource_item"
RESOURCE_TARGET_VARIANT = "1k_food"
RESOURCE_EFFECT_ORDINAL = 1
RESOURCE_QUANTITY = 1
RESOURCE_PRODUCT_POLICY_REVISION = "use_resource_item-v1"
RESOURCE_RECURRENCE_POLICY_REVISION = "daily_reset-v1"
RESOURCE_BLOCK_SCOPE = "runtime-objective"
RESOURCE_BLOCK_OBJECTIVE = "use_resource_item"
RESOURCE_STATIC_UTC_ASSURANCE = "fixed_runtime_binding_static_utc_reset"


class ResourceAuthorityError(StoreError):
    """Fail-closed Resource authority or integrity error."""


class ResourceIntegrityError(ResourceAuthorityError):
    """An immutable digest or composite relationship was inconsistent."""


class ResourceAuthorizationDenied(ResourceAuthorityError):
    """A Resource occurrence or reservation is not dispatch eligible."""


class ResourceFenceError(ResourceAuthorityError):
    """A claim, controller, reservation, frame, or invocation fence failed."""


RESOURCE_PRE_INTENT_CANCELLATION_REASON = "resource_authorization_expired"


def _canonical(value: Any) -> Any:
    return snapshot(value)


def _json(value: Any) -> str:
    return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _id(prefix: str, value: Any) -> str:
    return f"{prefix}:{_digest(value)}"


def _text(value: Any, field: str, *, allow_none: bool = False) -> Optional[str]:
    if value is None and allow_none:
        return None
    if type(value) is not str or not value or value != value.strip() or any(ch.isspace() for ch in value):
        raise ResourceAuthorityError(f"{field} must be a normalized non-empty string")
    return value


def _sha(value: Any, field: str, *, allow_none: bool = False) -> Optional[str]:
    result = _text(value, field, allow_none=allow_none)
    if result is None:
        return None
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise ResourceAuthorityError(f"{field} must be a lowercase SHA-256 digest")
    return result


def _utc(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResourceAuthorityError(f"{field} must be an ISO-8601 UTC value")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResourceAuthorityError(f"{field} must be an ISO-8601 UTC value") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _field_refs(value: Any, field: str) -> tuple[str, ...]:
    if isinstance(value, str):
        value = (value,)
    if not isinstance(value, (tuple, list)) or any(
        type(item) is not str or not item.strip() for item in value
    ):
        raise ResourceAuthorityError(f"{field} must contain explicit evidence references")
    return tuple(str(item) for item in value)


def _unknown_fields(value: Any) -> tuple[str, ...]:
    if isinstance(value, Mapping):
        value = value.keys()
    if value is None:
        return ()
    if not isinstance(value, (tuple, list, set)) or any(
        type(item) is not str or not item.strip() for item in value
    ):
        raise ResourceAuthorityError("unknown_fields must contain field names")
    return tuple(sorted(set(value)))


def _row(db: sqlite3.Connection, sql: str, params: Sequence[Any]) -> Optional[dict[str, Any]]:
    value = db.execute(sql, tuple(params)).fetchone()
    return dict(value) if value is not None else None


def _immutable_insert(
    db: sqlite3.Connection,
    *,
    table: str,
    id_column: str,
    object_id: str,
    columns: Sequence[str],
    values: Sequence[Any],
    payload: Any,
    digest: str,
) -> bool:
    """INSERT OR IGNORE, then compare the complete immutable payload exactly."""

    encoded = _json(payload)
    encoded_columns = ",".join(columns)
    placeholders = ",".join("?" for _ in columns)
    db.execute(
        f"INSERT OR IGNORE INTO {table}({encoded_columns}) VALUES ({placeholders})",
        tuple(values),
    )
    existing = _row(
        db,
        f"SELECT * FROM {table} WHERE {id_column}=?",
        (object_id,),
    )
    if existing is None:
        raise ResourceIntegrityError(
            f"{table} immutable identity conflicts with an existing unique row"
        )
    if existing.get("content_digest") != digest or existing.get("payload_json") != encoded:
        raise ResourceIntegrityError(f"{table} immutable payload mismatch")
    return existing.get(id_column) == object_id and existing.get("payload_json") == encoded


@dataclass(frozen=True)
class ResourceResetIdentity:
    reset_identity_id: str
    account_id: str
    server_id: str
    runtime_scope: str
    reset_start_utc: str
    reset_deadline_utc: str
    assurance: str = RESOURCE_STATIC_UTC_ASSURANCE
    observed_at: float = 0.0
    expires_at: float | None = None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field in ("reset_identity_id", "account_id", "server_id", "runtime_scope", "assurance"):
            _text(getattr(self, field), field)
        object.__setattr__(self, "reset_start_utc", _utc(self.reset_start_utc, "reset_start_utc"))
        object.__setattr__(
            self,
            "reset_deadline_utc",
            _utc(self.reset_deadline_utc, "reset_deadline_utc"),
        )
        if type(self.observed_at) not in (int, float) or self.observed_at < 0:
            raise ResourceAuthorityError("observed_at must be a finite non-negative number")
        if self.expires_at is not None and (
            type(self.expires_at) not in (int, float) or self.expires_at < self.observed_at
        ):
            raise ResourceAuthorityError("expires_at must be absent or after observed_at")
        object.__setattr__(self, "evidence_refs", _field_refs(self.evidence_refs, "evidence_refs"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "reset_identity_id": self.reset_identity_id,
            "account_id": self.account_id,
            "server_id": self.server_id,
            "runtime_scope": self.runtime_scope,
            "reset_start_utc": self.reset_start_utc,
            "reset_deadline_utc": self.reset_deadline_utc,
            "assurance": self.assurance,
            "observed_at": self.observed_at,
            "expires_at": self.expires_at,
            "evidence_refs": self.evidence_refs,
        }


@dataclass(frozen=True)
class ResourceOccurrenceIdentity:
    account_id: str
    server_id: str
    flow_id: str
    reset_identity_id: str
    product_policy_revision: str = RESOURCE_PRODUCT_POLICY_REVISION
    recurrence_policy_revision: str = RESOURCE_RECURRENCE_POLICY_REVISION
    recurrence_class: str = RESOURCE_RECURRENCE_CLASS
    objective_action_id: str = RESOURCE_OBJECTIVE_ACTION_ID
    target_variant: str = RESOURCE_TARGET_VARIANT
    effect_ordinal: int = RESOURCE_EFFECT_ORDINAL
    quantity: int = RESOURCE_QUANTITY

    def __post_init__(self) -> None:
        for field in (
            "account_id",
            "server_id",
            "flow_id",
            "reset_identity_id",
            "product_policy_revision",
            "recurrence_policy_revision",
            "recurrence_class",
            "objective_action_id",
            "target_variant",
        ):
            _text(getattr(self, field), field)
        if self.recurrence_class != RESOURCE_RECURRENCE_CLASS:
            raise ResourceAuthorityError("Resource recurrence class is not daily_reset")
        if self.objective_action_id != RESOURCE_OBJECTIVE_ACTION_ID:
            raise ResourceAuthorityError("Resource objective action is not use_resource_item")
        if self.target_variant != RESOURCE_TARGET_VARIANT:
            raise ResourceAuthorityError("Resource target variant is not 1k_food")
        if self.effect_ordinal != RESOURCE_EFFECT_ORDINAL or self.quantity != RESOURCE_QUANTITY:
            raise ResourceAuthorityError("Resource effect ordinal and quantity must both be one")

    def canonical_tuple(self) -> tuple[Any, ...]:
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

    def occurrence_key(self) -> str:
        return "occ:v1:" + hashlib.sha256(
            json.dumps(list(self.canonical_tuple()), ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()

    def occurrence_id(self) -> str:
        return _id("occurrence:v1", self.occurrence_key())

    def as_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "server_id": self.server_id,
            "flow_id": self.flow_id,
            "recurrence_class": self.recurrence_class,
            "reset_identity_id": self.reset_identity_id,
            "objective_action_id": self.objective_action_id,
            "target_variant": self.target_variant,
            "effect_ordinal": self.effect_ordinal,
            "quantity": self.quantity,
            "product_policy_revision": self.product_policy_revision,
            "recurrence_policy_revision": self.recurrence_policy_revision,
            "occurrence_key": self.occurrence_key(),
            "occurrence_id": self.occurrence_id(),
        }

    def authorization_context(self) -> ResourceAuthorizationContext:
        return ResourceAuthorizationContext(
            account_id=self.account_id,
            server_id=self.server_id,
            flow_id=self.flow_id,
            recurrence_class=self.recurrence_class,
            reset_identity_id=self.reset_identity_id,
            objective_action_id=self.objective_action_id,
            target_variant=self.target_variant,
            effect_ordinal=self.effect_ordinal,
            quantity=self.quantity,
            product_policy_revision=self.product_policy_revision,
            recurrence_policy_revision=self.recurrence_policy_revision,
            occurrence_id=self.occurrence_id(),
            occurrence_key=self.occurrence_key(),
        )


@dataclass(frozen=True)
class ResourceAttemptClaim:
    claim_id: str
    attempt_id: str
    occurrence_id: str
    owner_id: str
    claim_epoch: int
    state: str
    expires_at: float
    claim_token: str | None = None
    can_dispatch: bool = False
    reservation_id: str | None = None

    @property
    def claim_token_digest(self) -> str:
        return (
            hashlib.sha256(self.claim_token.encode("utf-8")).hexdigest()
            if self.claim_token
            else ""
        )


ClaimLease = ResourceAttemptClaim


@dataclass(frozen=True)
class ResourceReservationSpec:
    authorization_generation: int = 1
    immediate_before_sha256: str = ""
    runtime_invocation_id: str = ""
    controller_token: str = ""
    controller_generation: int = 1

    def __post_init__(self) -> None:
        if type(self.authorization_generation) is not int or self.authorization_generation < 1:
            raise ResourceAuthorityError("authorization_generation must be positive")
        _sha(self.immediate_before_sha256, "immediate_before_sha256")
        _text(self.runtime_invocation_id, "runtime_invocation_id")
        _text(self.controller_token, "controller_token")
        if type(self.controller_generation) is not int or self.controller_generation < 1:
            raise ResourceAuthorityError("controller_generation must be positive")


@dataclass(frozen=True)
class PreparedResourceEffect:
    occurrence_id: str
    attempt_id: str
    reservation_id: str
    action_id: str
    action_key: str
    authorization_generation: int
    reservation_state_revision: int
    context: ResourceAuthorizationContext
    fence: EffectDispatchFence


@dataclass(frozen=True)
class PreparedResourceAuthorization:
    """One immutable proposal/capability bundle for the exact Resource Use."""

    prepared: PreparedResourceEffect
    request: PolicyRequest
    capability: InputCapability

    def __post_init__(self) -> None:
        if type(self.prepared) is not PreparedResourceEffect:
            raise ResourceAuthorityError("prepared Resource effect is required")
        if type(self.request) is not PolicyRequest:
            raise ResourceAuthorityError("typed Resource policy request is required")
        if type(self.capability) is not InputCapability:
            raise ResourceAuthorityError("one-shot Resource capability is required")


@dataclass(frozen=True)
class HistoricalResourceTransportFact:
    historical_session_id: str
    action_key: str
    transport_at_utc: str | None = None
    source_frame_sha256: str | None = None
    transport_result: Mapping[str, Any] | None = None
    unknown_fields: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    transport_fact_id: str | None = None


@dataclass(frozen=True)
class HistoricalResourceEffect:
    historical_session_id: str
    transport_fact_id: str
    before_owned_quantity: int | None
    after_owned_quantity: int | None
    occurrence_id: str | None = None
    before_resource_quantity: int | None = None
    after_resource_quantity: int | None = None
    effect_state: str = "CONFIRMED"
    account_id: str | None = None
    server_id: str | None = None
    reset_identity_id: str | None = None
    unknown_fields: tuple[str, ...] = ()
    historical_effect_id: str | None = None


@dataclass(frozen=True)
class HistoricalPolicyClassification:
    historical_effect_id: str
    classification_code: str = "SUSPECTED_SAME_CYCLE_DUPLICATE"
    scope_key: str = "runtime-objective:unknown|use_resource_item"
    classification_id: str | None = None
    effect_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResetBindingAssertion:
    effect_kind: str
    effect_id: str
    assertion_state: str = "UNRESOLVED"
    account_id: str | None = None
    server_id: str | None = None
    reset_identity_id: str | None = None
    evidence_refs: tuple[str, ...] = ()
    unknown_fields: tuple[str, ...] = ()
    assertion_id: str | None = None


@dataclass(frozen=True)
class TerminalObservation:
    occurrence_id: str
    terminal_state: str
    frame_sha256: str | None = None
    evidence_refs: tuple[str, ...] = ()
    observation_id: str | None = None


@dataclass(frozen=True)
class ResourceBlockResolution:
    block_id: str
    decision: str
    authoritative_evidence: Mapping[str, Any]
    current_reset_id: str | None = None
    supersedes_resolution_id: str | None = None
    resolution_id: str | None = None


class ResourceTransportIntentToken:
    """Opaque single-use token accepted only by the narrow Resource adapter."""

    __slots__ = ("_authority_marker", "_reservation_id", "_transport_fact_id", "_invocation_id", "_consumed")

    def __new__(cls, *args: Any, **kwargs: Any) -> "ResourceTransportIntentToken":
        raise TypeError("ResourceTransportIntentToken cannot be constructed publicly")

    @classmethod
    def _mint(
        cls,
        marker: object,
        reservation_id: str,
        transport_fact_id: str,
        invocation_id: str,
    ) -> "ResourceTransportIntentToken":
        obj = object.__new__(cls)
        object.__setattr__(obj, "_authority_marker", marker)
        object.__setattr__(obj, "_reservation_id", reservation_id)
        object.__setattr__(obj, "_transport_fact_id", transport_fact_id)
        object.__setattr__(obj, "_invocation_id", invocation_id)
        object.__setattr__(obj, "_consumed", False)
        return obj

    @property
    def consumed(self) -> bool:
        return bool(getattr(self, "_consumed", False))

    @property
    def reservation_id(self) -> str:
        return str(getattr(self, "_reservation_id", ""))

    @property
    def transport_fact_id(self) -> str:
        return str(getattr(self, "_transport_fact_id", ""))

    @property
    def runtime_invocation_id(self) -> str:
        return str(getattr(self, "_invocation_id", ""))


class ResourceEffectAuthority:
    """Typed Resource repositories and the two-database dispatch coordinator."""

    def __init__(self, store: SafetyStore) -> None:
        if not isinstance(store, SafetyStore):
            raise TypeError("ResourceEffectAuthority requires the existing SafetyStore")
        self.store = store
        self._transport_marker = object()

    def _assert_v4(self) -> None:
        if self.store.schema_version != 4:
            raise ResourceAuthorityError("Resource authority requires SafetyStore schema v4")

    def acquire_resource_controller_lease(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.store.acquire_resource_controller_lease(*args, **kwargs)

    def release_resource_controller_lease(self, *args: Any, **kwargs: Any) -> None:
        return self.store.release_resource_controller_lease(*args, **kwargs)

    def heartbeat_resource_controller_lease(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.store.heartbeat_resource_controller_lease(*args, **kwargs)

    @staticmethod
    def _identity(value: ResourceOccurrenceIdentity | Mapping[str, Any]) -> ResourceOccurrenceIdentity:
        if isinstance(value, ResourceOccurrenceIdentity):
            return value
        if not isinstance(value, Mapping):
            raise ResourceAuthorityError("Resource occurrence identity must be typed")
        return ResourceOccurrenceIdentity(
            account_id=value.get("account_id"),
            server_id=value.get("server_id"),
            flow_id=value.get("flow_id", RESOURCE_FLOW_ID),
            reset_identity_id=value.get("reset_identity_id", value.get("recurrence_epoch")),
            product_policy_revision=value.get(
                "product_policy_revision", RESOURCE_PRODUCT_POLICY_REVISION
            ),
            recurrence_policy_revision=value.get(
                "recurrence_policy_revision", RESOURCE_RECURRENCE_POLICY_REVISION
            ),
            recurrence_class=value.get("recurrence_class", RESOURCE_RECURRENCE_CLASS),
            objective_action_id=value.get("objective_action_id", RESOURCE_OBJECTIVE_ACTION_ID),
            target_variant=value.get("target_variant", RESOURCE_TARGET_VARIANT),
            effect_ordinal=value.get("effect_ordinal", RESOURCE_EFFECT_ORDINAL),
            quantity=value.get("quantity", RESOURCE_QUANTITY),
        )

    @staticmethod
    def _reset(value: ResourceResetIdentity | Mapping[str, Any]) -> ResourceResetIdentity:
        if isinstance(value, ResourceResetIdentity):
            return value
        if not isinstance(value, Mapping):
            raise ResourceAuthorityError("reset identity must be typed")
        return ResourceResetIdentity(
            reset_identity_id=value.get("reset_identity_id", value.get("reset_id")),
            account_id=value.get("account_id"),
            server_id=value.get("server_id"),
            runtime_scope=value.get("runtime_scope"),
            reset_start_utc=value.get("reset_start_utc", value.get("start_utc")),
            reset_deadline_utc=value.get("reset_deadline_utc", value.get("deadline_utc")),
            assurance=value.get("assurance", RESOURCE_STATIC_UTC_ASSURANCE),
            observed_at=value.get("observed_at", 0.0),
            expires_at=value.get("expires_at"),
            evidence_refs=tuple(value.get("evidence_refs", ())),
        )

    def append_reset_identity(
        self,
        identity: ResourceResetIdentity | Mapping[str, Any],
    ) -> ResourceResetIdentity:
        self._assert_v4()
        value = self._reset(identity)
        with self.store.transaction() as db:
            self._insert_reset_identity(db, value)
        return value

    @staticmethod
    def _reset_from_row(row: Mapping[str, Any]) -> ResourceResetIdentity:
        try:
            evidence_refs = json.loads(str(row.get("evidence_refs_json") or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ResourceIntegrityError("resource reset identity evidence is malformed") from exc
        if not isinstance(evidence_refs, (list, tuple)):
            raise ResourceIntegrityError("resource reset identity evidence is malformed")
        return ResourceResetIdentity(
            reset_identity_id=row.get("reset_identity_id"),
            account_id=row.get("account_id"),
            server_id=row.get("server_id"),
            runtime_scope=row.get("runtime_scope"),
            reset_start_utc=row.get("reset_start_utc"),
            reset_deadline_utc=row.get("reset_deadline_utc"),
            assurance=row.get("assurance"),
            observed_at=row.get("observed_at"),
            expires_at=row.get("expires_at"),
            evidence_refs=tuple(evidence_refs),
        )

    def _insert_reset_identity(
        self,
        db: sqlite3.Connection,
        value: ResourceResetIdentity,
    ) -> None:
        payload = value.as_dict()
        content_digest = _digest(payload)
        _immutable_insert(
            db,
            table="resource_reset_identities",
            id_column="reset_identity_id",
            object_id=value.reset_identity_id,
            columns=(
                "reset_identity_id",
                "account_id",
                "server_id",
                "runtime_scope",
                "reset_start_utc",
                "reset_deadline_utc",
                "assurance",
                "observed_at",
                "expires_at",
                "evidence_refs_json",
                "content_digest",
                "payload_json",
            ),
            values=(
                value.reset_identity_id,
                value.account_id,
                value.server_id,
                value.runtime_scope,
                value.reset_start_utc,
                value.reset_deadline_utc,
                value.assurance,
                value.observed_at,
                value.expires_at,
                _json(value.evidence_refs),
                content_digest,
                _json(payload),
            ),
            payload=payload,
            digest=content_digest,
        )

    def ensure_static_utc_reset_identity(
        self,
        identity: ResourceResetIdentity | Mapping[str, Any],
    ) -> ResourceResetIdentity:
        """Ensure one Resource reset under the static UTC product rule.

        A retained row may carry the exact historical screen-observed assurance/evidence. It is
        reusable only when the account, server, runtime scope, and exact UTC reset bounds match.
        Neither the candidate nor a retained row is rewritten.
        """

        self._assert_v4()
        value = self._reset(identity)
        if value.assurance != RESOURCE_STATIC_UTC_ASSURANCE:
            raise ResourceIntegrityError(
                "static UTC Resource reset requires the static UTC assurance"
            )
        try:
            start = datetime.fromisoformat(value.reset_start_utc.replace("Z", "+00:00"))
            deadline = datetime.fromisoformat(value.reset_deadline_utc.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ResourceIntegrityError(
                "static UTC Resource reset bounds are malformed"
            ) from exc
        if (
            start.tzinfo is None
            or deadline.tzinfo is None
            or start.hour != 0
            or start.minute != 0
            or start.second != 0
            or start.microsecond != 0
            or deadline != start + timedelta(days=1)
        ):
            raise ResourceIntegrityError(
                "static UTC Resource reset must span one exact UTC day"
            )
        if value.reset_identity_id != f"reset-deadline:{value.reset_deadline_utc}":
            raise ResourceIntegrityError(
                "static UTC Resource reset identity ID does not match its deadline"
            )
        with self.store.transaction() as db:
            existing = _row(
                db,
                "SELECT * FROM resource_reset_identities WHERE reset_identity_id=?",
                (value.reset_identity_id,),
            )
            if existing is None:
                self._insert_reset_identity(db, value)
                return value
            if existing["assurance"] not in {
                RESOURCE_STATIC_UTC_ASSURANCE,
                "FIXED_RUNTIME_BINDING_RESET_OBSERVED",
            }:
                raise ResourceIntegrityError(
                    "existing Resource reset assurance is not reusable"
                )
            core_fields = (
                "account_id",
                "server_id",
                "runtime_scope",
                "reset_start_utc",
                "reset_deadline_utc",
            )
            if any(existing[field] != getattr(value, field) for field in core_fields):
                raise ResourceIntegrityError(
                    "existing Resource reset identity does not match the static UTC core binding"
                )
            return self._reset_from_row(existing)

    ensure_reset_identity = ensure_static_utc_reset_identity
    create_reset_identity = append_reset_identity

    def create_resource_occurrence(
        self,
        identity: ResourceOccurrenceIdentity | Mapping[str, Any],
        policy_revision: str | None = None,
        *,
        recurrence_policy_revision: str | None = None,
        now: float = 0.0,
    ) -> dict[str, Any]:
        self._assert_v4()
        value = self._identity(identity)
        if policy_revision is not None:
            value = replace(value, product_policy_revision=policy_revision)
        if recurrence_policy_revision is not None:
            value = replace(value, recurrence_policy_revision=recurrence_policy_revision)
        context = value.authorization_context()
        payload = {
            **value.as_dict(),
            "state": "ELIGIBLE",
            "state_revision": 0,
        }
        content_digest = _digest(payload)
        with self.store.transaction() as db:
            reset = _row(
                db,
                """SELECT * FROM resource_reset_identities
                   WHERE account_id=? AND server_id=? AND reset_identity_id=?""",
                (value.account_id, value.server_id, value.reset_identity_id),
            )
            if reset is None:
                raise ResourceAuthorizationDenied(
                    "authoritative reset identity is required before occurrence creation"
                )
            _immutable_insert(
                db,
                table="resource_occurrences",
                id_column="occurrence_id",
                object_id=context.occurrence_id,
                columns=(
                    "occurrence_id",
                    "occurrence_key",
                    "account_id",
                    "server_id",
                    "flow_id",
                    "recurrence_class",
                    "recurrence_epoch",
                    "objective_action_id",
                    "target_variant",
                    "effect_ordinal",
                    "quantity",
                    "product_policy_revision",
                    "recurrence_policy_revision",
                    "state",
                    "state_revision",
                    "reset_identity_id",
                    "created_at",
                    "updated_at",
                    "content_digest",
                    "payload_json",
                ),
                values=(
                    context.occurrence_id,
                    context.occurrence_key,
                    context.account_id,
                    context.server_id,
                    context.flow_id,
                    context.recurrence_class,
                    context.reset_identity_id,
                    context.objective_action_id,
                    context.target_variant,
                    context.effect_ordinal,
                    context.quantity,
                    context.product_policy_revision,
                    context.recurrence_policy_revision,
                    "ELIGIBLE",
                    0,
                    context.reset_identity_id,
                    now,
                    now,
                    content_digest,
                    _json(payload),
                ),
                payload=payload,
                digest=content_digest,
            )
            self._append_transition(
                db,
                entity_type="occurrence",
                entity_id=context.occurrence_id,
                state_from=None,
                state_to="ELIGIBLE",
                state_revision=0,
                recorded_at=now,
                payload=payload,
            )
        return self.get_occurrence(context.occurrence_id) or payload

    def get_occurrence(self, occurrence_id: str) -> Optional[dict[str, Any]]:
        return _row(
            self.store.connection,
            "SELECT * FROM resource_occurrences WHERE occurrence_id=?",
            (occurrence_id,),
        )

    def occurrence_context(self, occurrence_id: str) -> ResourceAuthorizationContext:
        row = self.get_occurrence(occurrence_id)
        if row is None:
            raise ResourceAuthorityError("unknown Resource occurrence")
        return ResourceAuthorizationContext(
            account_id=row["account_id"],
            server_id=row["server_id"],
            flow_id=row["flow_id"],
            recurrence_class=row["recurrence_class"],
            reset_identity_id=row["recurrence_epoch"],
            objective_action_id=row["objective_action_id"],
            target_variant=row["target_variant"],
            effect_ordinal=int(row["effect_ordinal"]),
            quantity=int(row["quantity"]),
            product_policy_revision=row["product_policy_revision"],
            recurrence_policy_revision=row["recurrence_policy_revision"],
            occurrence_id=row["occurrence_id"],
            occurrence_key=row["occurrence_key"],
        )

    def _append_transition(
        self,
        db: sqlite3.Connection,
        *,
        entity_type: str,
        entity_id: str,
        state_from: str | None,
        state_to: str,
        state_revision: int,
        recorded_at: float,
        payload: Any,
    ) -> None:
        transition_payload = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "state_from": state_from,
            "state_to": state_to,
            "state_revision": state_revision,
            "recorded_at": recorded_at,
            "payload": _canonical(payload),
        }
        transition_id = _id("transition:v1", transition_payload)
        digest = _digest(transition_payload)
        _immutable_insert(
            db,
            table="resource_transition_history",
            id_column="transition_id",
            object_id=transition_id,
            columns=(
                "transition_id",
                "entity_type",
                "entity_id",
                "state_from",
                "state_to",
                "state_revision",
                "recorded_at",
                "payload_json",
                "content_digest",
            ),
            values=(
                transition_id,
                entity_type,
                entity_id,
                state_from,
                state_to,
                state_revision,
                recorded_at,
                _json(transition_payload),
                digest,
            ),
            payload=transition_payload,
            digest=digest,
        )

    def _next_attempt_generation(self, db: sqlite3.Connection, occurrence_id: str) -> int:
        row = db.execute(
            "SELECT COALESCE(MAX(attempt_generation),0) AS generation FROM resource_attempts WHERE occurrence_id=?",
            (occurrence_id,),
        ).fetchone()
        return int(row["generation"]) + 1

    def _insert_attempt(
        self,
        db: sqlite3.Connection,
        *,
        occurrence_id: str,
        generation: int,
        state: str,
        owner_id: str | None,
        hypothesis_digest: str,
        now: float,
    ) -> str:
        payload = {
            "occurrence_id": occurrence_id,
            "attempt_generation": generation,
            "state": state,
            "owner_id": owner_id,
            "hypothesis_digest": hypothesis_digest,
            "state_revision": 0,
        }
        attempt_id = _id("attempt:v1", payload)
        digest = _digest(payload)
        _immutable_insert(
            db,
            table="resource_attempts",
            id_column="attempt_id",
            object_id=attempt_id,
            columns=(
                "attempt_id",
                "occurrence_id",
                "attempt_generation",
                "state",
                "hypothesis_digest",
                "owner_id",
                "state_revision",
                "created_at",
                "updated_at",
                "content_digest",
                "payload_json",
            ),
            values=(
                attempt_id,
                occurrence_id,
                generation,
                state,
                hypothesis_digest,
                owner_id,
                0,
                now,
                now,
                digest,
                _json(payload),
            ),
            payload=payload,
            digest=digest,
        )
        self._append_transition(
            db,
            entity_type="attempt",
            entity_id=attempt_id,
            state_from=None,
            state_to=state,
            state_revision=0,
            recorded_at=now,
            payload=payload,
        )
        return attempt_id

    def claim_resource_attempt(
        self,
        occurrence_id: str,
        owner: str,
        expected_revision: int | None = None,
        *,
        now: float = 0.0,
        ttl_seconds: float = 30.0,
        hypothesis_digest: str | None = None,
    ) -> ResourceAttemptClaim:
        self._assert_v4()
        _text(owner, "owner")
        if ttl_seconds <= 0:
            raise ResourceAuthorityError("claim TTL must be positive")
        with self.store.transaction() as db:
            occurrence = _row(
                db,
                "SELECT * FROM resource_occurrences WHERE occurrence_id=?",
                (occurrence_id,),
            )
            if occurrence is None:
                raise ResourceAuthorityError("unknown Resource occurrence")
            if expected_revision is not None and int(occurrence["state_revision"]) != expected_revision:
                raise ResourceFenceError("occurrence state revision is stale")
            generation = self._next_attempt_generation(db, occurrence_id)
            hypothesis_is_nonempty = (
                type(hypothesis_digest) is str and bool(hypothesis_digest.strip())
            )
            if occurrence["state"] in {"COMPLETED", "BLOCKED"}:
                attempt_id = self._insert_attempt(
                    db,
                    occurrence_id=occurrence_id,
                    generation=generation,
                    state="DENIED",
                    owner_id=owner,
                    hypothesis_digest=hypothesis_digest or _digest({"owner": owner, "terminal": occurrence["state"]}),
                    now=now,
                )
                return ResourceAttemptClaim("", attempt_id, occurrence_id, owner, 0, "DENIED", now, None, False)
            if occurrence["state"] == "NO_EFFECT":
                no_effect = _row(
                    db,
                    """SELECT e.*,r.product_policy_revision,r.recurrence_policy_revision,
                              r.account_id AS reservation_account_id,
                              r.server_id AS reservation_server_id,
                              r.reset_identity_id AS reservation_reset_identity_id
                       FROM resource_live_effects e
                       JOIN resource_reservations r ON r.reservation_id=e.reservation_id
                       JOIN resource_transport_outcomes o
                         ON o.reservation_id=e.reservation_id
                        AND o.transport_fact_id=e.transport_fact_id
                       WHERE e.occurrence_id=? AND e.effect_ordinal=?
                         AND e.effect_state='NO_EFFECT'
                       ORDER BY e.created_at DESC LIMIT 1""",
                    (occurrence_id, int(occurrence["effect_ordinal"])),
                )
                proven_no_effect = False
                if no_effect is not None:
                    try:
                        no_effect_payload = json.loads(str(no_effect["payload_json"]))
                    except (TypeError, ValueError, json.JSONDecodeError):
                        no_effect_payload = {}
                    proven_no_effect = (
                        no_effect_payload.get("proven_no_effect") is True
                        and no_effect["product_policy_revision"]
                        == occurrence["product_policy_revision"]
                        and no_effect["recurrence_policy_revision"]
                        == occurrence["recurrence_policy_revision"]
                        and no_effect["reservation_account_id"] == occurrence["account_id"]
                        and no_effect["reservation_server_id"] == occurrence["server_id"]
                        and no_effect["reservation_reset_identity_id"]
                        == occurrence["reset_identity_id"]
                    )
                prior_attempt = _row(
                    db,
                    """SELECT hypothesis_digest FROM resource_attempts
                       WHERE occurrence_id=? ORDER BY attempt_generation DESC LIMIT 1""",
                    (occurrence_id,),
                )
                if (
                    not proven_no_effect
                    or not hypothesis_is_nonempty
                    or prior_attempt is not None
                    and prior_attempt["hypothesis_digest"] == hypothesis_digest
                ):
                    attempt_id = self._insert_attempt(
                        db,
                        occurrence_id=occurrence_id,
                        generation=generation,
                        state="DENIED",
                        owner_id=owner,
                        hypothesis_digest=hypothesis_digest or _digest({"owner": owner, "retry": False}),
                        now=now,
                    )
                    return ResourceAttemptClaim("", attempt_id, occurrence_id, owner, 0, "DENIED", now, None, False)
            active = db.execute(
                """SELECT * FROM resource_attempt_claims
                   WHERE occurrence_id=? AND state='ACTIVE'""",
                (occurrence_id,),
            ).fetchone()
            if active is not None:
                if float(active["expires_at"]) <= now:
                    if active["reservation_id"] is None:
                        db.execute(
                            "UPDATE resource_attempt_claims SET state='EXPIRED' WHERE claim_id=?",
                            (active["claim_id"],),
                        )
                    else:
                        attempt_id = self._insert_attempt(
                            db,
                            occurrence_id=occurrence_id,
                            generation=generation,
                            state="RECONCILING",
                            owner_id=owner,
                            hypothesis_digest=hypothesis_digest or _digest({"owner": owner}),
                            now=now,
                        )
                        claim_id = _id(
                            "claim:v1",
                            {"attempt_id": attempt_id, "claim_epoch": 1, "mode": "reconcile"},
                        )
                        payload = {
                            "claim_id": claim_id,
                            "attempt_id": attempt_id,
                            "occurrence_id": occurrence_id,
                            "owner_id": owner,
                            "claim_epoch": 1,
                            "state": "RECONCILIATION_ONLY",
                            "reservation_id": active["reservation_id"],
                        }
                        token = secrets.token_hex(32)
                        digest = _digest({**payload, "claim_token_digest": hashlib.sha256(token.encode()).hexdigest()})
                        _immutable_insert(
                            db,
                            table="resource_attempt_claims",
                            id_column="claim_id",
                            object_id=claim_id,
                            columns=(
                                "claim_id",
                                "attempt_id",
                                "occurrence_id",
                                "owner_id",
                                "claim_token_digest",
                                "claim_epoch",
                                "acquired_at",
                                "expires_at",
                                "state",
                                "reservation_id",
                                "content_digest",
                                "payload_json",
                            ),
                            values=(
                                claim_id,
                                attempt_id,
                                occurrence_id,
                                owner,
                                hashlib.sha256(token.encode()).hexdigest(),
                                1,
                                now,
                                now + ttl_seconds,
                                "RECONCILIATION_ONLY",
                                active["reservation_id"],
                                digest,
                                _json({**payload, "claim_token_digest": hashlib.sha256(token.encode()).hexdigest()}),
                            ),
                            payload={**payload, "claim_token_digest": hashlib.sha256(token.encode()).hexdigest()},
                            digest=digest,
                        )
                        return ResourceAttemptClaim(
                            claim_id,
                            attempt_id,
                            occurrence_id,
                            owner,
                            1,
                            "RECONCILIATION_ONLY",
                            now + ttl_seconds,
                            token,
                            False,
                            active["reservation_id"],
                        )
                else:
                    attempt_id = self._insert_attempt(
                        db,
                        occurrence_id=occurrence_id,
                        generation=generation,
                        state="DENIED",
                        owner_id=owner,
                        hypothesis_digest=hypothesis_digest or _digest({"owner": owner, "denied": True}),
                        now=now,
                    )
                    return ResourceAttemptClaim(
                        "",
                        attempt_id,
                        occurrence_id,
                        owner,
                        0,
                        "DENIED",
                        float(active["expires_at"]),
                        None,
                        False,
                        active["reservation_id"],
                    )
            if db.execute(
                """SELECT 1 FROM resource_live_effects
                   WHERE occurrence_id=? AND effect_ordinal=? AND effect_state='CONFIRMED'""",
                (occurrence_id, int(occurrence["effect_ordinal"])),
            ).fetchone() is not None:
                attempt_id = self._insert_attempt(
                    db,
                    occurrence_id=occurrence_id,
                    generation=generation,
                    state="DENIED",
                    owner_id=owner,
                    hypothesis_digest=hypothesis_digest or _digest({"owner": owner, "completed": True}),
                    now=now,
                )
                return ResourceAttemptClaim("", attempt_id, occurrence_id, owner, 0, "DENIED", now, None, False)
            attempt_id = self._insert_attempt(
                db,
                occurrence_id=occurrence_id,
                generation=generation,
                state="CLAIMED",
                owner_id=owner,
                hypothesis_digest=hypothesis_digest or _digest({"owner": owner, "generation": generation}),
                now=now,
            )
            token = secrets.token_hex(32)
            token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            claim_id = _id(
                "claim:v1",
                {"attempt_id": attempt_id, "claim_epoch": 1, "owner_id": owner},
            )
            payload = {
                "claim_id": claim_id,
                "attempt_id": attempt_id,
                "occurrence_id": occurrence_id,
                "owner_id": owner,
                "claim_epoch": 1,
                "state": "ACTIVE",
            }
            digest = _digest({**payload, "claim_token_digest": token_digest})
            _immutable_insert(
                db,
                table="resource_attempt_claims",
                id_column="claim_id",
                object_id=claim_id,
                columns=(
                    "claim_id",
                    "attempt_id",
                    "occurrence_id",
                    "owner_id",
                    "claim_token_digest",
                    "claim_epoch",
                    "acquired_at",
                    "expires_at",
                    "state",
                    "reservation_id",
                    "content_digest",
                    "payload_json",
                ),
                values=(
                    claim_id,
                    attempt_id,
                    occurrence_id,
                    owner,
                    token_digest,
                    1,
                    now,
                    now + ttl_seconds,
                    "ACTIVE",
                    None,
                    digest,
                    _json({**payload, "claim_token_digest": token_digest}),
                ),
                payload={**payload, "claim_token_digest": token_digest},
                digest=digest,
            )
            return ResourceAttemptClaim(
                claim_id,
                attempt_id,
                occurrence_id,
                owner,
                1,
                "ACTIVE",
                now + ttl_seconds,
                token,
                True,
            )

    def transition_resource_attempt(
        self,
        attempt_id: str,
        state: str,
        *,
        now: float = 0.0,
        expected_revision: int | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        if state not in {"DENIED", "ABANDONED", "COMPLETED", "NO_EFFECT", "UNRESOLVED", "RECONCILING"}:
            raise ResourceAuthorityError("invalid Resource attempt terminal state")
        with self.store.transaction() as db:
            current = _row(
                db,
                "SELECT * FROM resource_attempts WHERE attempt_id=?",
                (attempt_id,),
            )
            if current is None:
                raise ResourceAuthorityError("unknown Resource attempt")
            revision = int(current["state_revision"])
            if expected_revision is not None and revision != expected_revision:
                raise ResourceFenceError("attempt state revision is stale")
            if current["state"] == state:
                return current
            next_revision = revision + 1
            changed = db.execute(
                """UPDATE resource_attempts
                   SET state=?, state_revision=?, updated_at=?
                   WHERE attempt_id=? AND state=? AND state_revision=?""",
                (
                    state,
                    next_revision,
                    now,
                    attempt_id,
                    current["state"],
                    revision,
                ),
            ).rowcount
            if changed != 1:
                raise ResourceFenceError("attempt compare-and-swap failed")
            self._append_transition(
                db,
                entity_type="attempt",
                entity_id=attempt_id,
                state_from=current["state"],
                state_to=state,
                state_revision=next_revision,
                recorded_at=now,
                payload={"reason": reason},
            )
            return _row(
                db,
                "SELECT * FROM resource_attempts WHERE attempt_id=?",
                (attempt_id,),
            ) or {}

    def _historical_transport(
        self,
        value: HistoricalResourceTransportFact | Mapping[str, Any],
    ) -> HistoricalResourceTransportFact:
        if isinstance(value, HistoricalResourceTransportFact):
            result = value
        elif isinstance(value, Mapping):
            result = HistoricalResourceTransportFact(
                historical_session_id=value.get("historical_session_id", value.get("session_id")),
                action_key=value.get("action_key", "daily-resource-item:use-1k-food"),
                transport_at_utc=value.get("transport_at_utc", value.get("transport_timestamp_utc")),
                source_frame_sha256=value.get("source_frame_sha256"),
                transport_result=value.get("transport_result", value.get("transport_result_json")),
                unknown_fields=tuple(value.get("unknown_fields", ())),
                evidence_refs=tuple(value.get("evidence_refs", ())),
                transport_fact_id=value.get("transport_fact_id"),
            )
        else:
            raise ResourceAuthorityError("historical transport fact must be typed")
        _text(result.historical_session_id, "historical_session_id")
        _text(result.action_key, "action_key")
        if result.transport_at_utc is not None:
            result = replace(result, transport_at_utc=_utc(result.transport_at_utc, "transport_at_utc"))
        if result.source_frame_sha256 is not None:
            result = replace(result, source_frame_sha256=_sha(result.source_frame_sha256, "source_frame_sha256"))
        return replace(
            result,
            unknown_fields=_unknown_fields(result.unknown_fields),
            evidence_refs=_field_refs(result.evidence_refs, "evidence_refs")
            if result.evidence_refs
            else (),
        )

    def import_historical_resource_transport(
        self,
        fact: HistoricalResourceTransportFact | Mapping[str, Any],
    ) -> dict[str, Any]:
        self._assert_v4()
        value = self._historical_transport(fact)
        payload = {
            "historical_session_id": value.historical_session_id,
            "action_key": value.action_key,
            "transport_at_utc": value.transport_at_utc,
            "source_frame_sha256": value.source_frame_sha256,
            "transport_result": value.transport_result,
            "unknown_fields": value.unknown_fields,
            "evidence_refs": value.evidence_refs,
        }
        object_id = value.transport_fact_id or _id("historical-transport:v1", payload)
        content_digest = _digest(payload)
        with self.store.transaction() as db:
            _immutable_insert(
                db,
                table="resource_historical_transport_facts",
                id_column="transport_fact_id",
                object_id=object_id,
                columns=(
                    "transport_fact_id",
                    "historical_session_id",
                    "action_key",
                    "transport_at_utc",
                    "source_frame_sha256",
                    "transport_result_json",
                    "unknown_fields_json",
                    "evidence_refs_json",
                    "content_digest",
                    "payload_json",
                ),
                values=(
                    object_id,
                    value.historical_session_id,
                    value.action_key,
                    value.transport_at_utc,
                    value.source_frame_sha256,
                    _json(value.transport_result),
                    _json(value.unknown_fields),
                    _json(value.evidence_refs),
                    content_digest,
                    _json(payload),
                ),
                payload=payload,
                digest=content_digest,
            )
        return _row(
            self.store.connection,
            "SELECT * FROM resource_historical_transport_facts WHERE transport_fact_id=?",
            (object_id,),
        ) or {}

    def _historical_effect(
        self,
        value: HistoricalResourceEffect | Mapping[str, Any],
    ) -> HistoricalResourceEffect:
        if isinstance(value, HistoricalResourceEffect):
            result = value
        elif isinstance(value, Mapping):
            result = HistoricalResourceEffect(
                historical_session_id=value.get("historical_session_id", value.get("session_id")),
                transport_fact_id=value.get("transport_fact_id"),
                occurrence_id=value.get("occurrence_id"),
                before_owned_quantity=value.get("before_owned_quantity"),
                after_owned_quantity=value.get("after_owned_quantity"),
                before_resource_quantity=value.get("before_resource_quantity"),
                after_resource_quantity=value.get("after_resource_quantity"),
                effect_state=value.get("effect_state", "CONFIRMED"),
                account_id=value.get("account_id"),
                server_id=value.get("server_id"),
                reset_identity_id=value.get("reset_identity_id"),
                unknown_fields=tuple(value.get("unknown_fields", ())),
                historical_effect_id=value.get("historical_effect_id"),
            )
        else:
            raise ResourceAuthorityError("historical effect must be typed")
        _text(result.historical_session_id, "historical_session_id")
        _text(result.transport_fact_id, "transport_fact_id")
        occurrence_id = result.occurrence_id or f"historical:{result.historical_session_id}"
        _text(occurrence_id, "occurrence_id")
        if result.effect_state not in {"CONFIRMED", "UNRESOLVED"}:
            raise ResourceAuthorityError("historical effect state is invalid")
        for field in ("account_id", "server_id", "reset_identity_id"):
            if getattr(result, field) is not None:
                _text(getattr(result, field), field)
        return replace(
            result,
            occurrence_id=occurrence_id,
            unknown_fields=_unknown_fields(result.unknown_fields),
        )

    def import_historical_resource_effect(
        self,
        effect: HistoricalResourceEffect | Mapping[str, Any],
        *,
        create_unresolved_block: bool = True,
        runtime_scope: str = "unknown",
    ) -> dict[str, Any]:
        self._assert_v4()
        value = self._historical_effect(effect)
        payload = {
            "historical_session_id": value.historical_session_id,
            "occurrence_id": value.occurrence_id,
            "transport_fact_id": value.transport_fact_id,
            "effect_kind": "historical",
            "effect_ordinal": RESOURCE_EFFECT_ORDINAL,
            "before_owned_quantity": value.before_owned_quantity,
            "after_owned_quantity": value.after_owned_quantity,
            "before_resource_quantity": value.before_resource_quantity,
            "after_resource_quantity": value.after_resource_quantity,
            "effect_state": value.effect_state,
            "account_id": value.account_id,
            "server_id": value.server_id,
            "reset_identity_id": value.reset_identity_id,
            "unknown_fields": value.unknown_fields,
        }
        object_id = value.historical_effect_id or _id("historical-effect:v1", payload)
        content_digest = _digest(payload)
        with self.store.transaction() as db:
            transport = _row(
                db,
                "SELECT * FROM resource_historical_transport_facts WHERE transport_fact_id=?",
                (value.transport_fact_id,),
            )
            if transport is None:
                raise ResourceIntegrityError("historical effect references unknown transport fact")
            _immutable_insert(
                db,
                table="resource_historical_effects",
                id_column="historical_effect_id",
                object_id=object_id,
                columns=(
                    "historical_effect_id",
                    "transport_fact_id",
                    "historical_session_id",
                    "occurrence_id",
                    "effect_kind",
                    "effect_ordinal",
                    "before_owned_quantity",
                    "after_owned_quantity",
                    "before_resource_quantity",
                    "after_resource_quantity",
                    "effect_state",
                    "account_id",
                    "server_id",
                    "reset_identity_id",
                    "unknown_fields_json",
                    "content_digest",
                    "payload_json",
                ),
                values=(
                    object_id,
                    value.transport_fact_id,
                    value.historical_session_id,
                    value.occurrence_id,
                    "historical",
                    RESOURCE_EFFECT_ORDINAL,
                    value.before_owned_quantity,
                    value.after_owned_quantity,
                    value.before_resource_quantity,
                    value.after_resource_quantity,
                    value.effect_state,
                    value.account_id,
                    value.server_id,
                    value.reset_identity_id,
                    _json(value.unknown_fields),
                    content_digest,
                    _json(payload),
                ),
                payload=payload,
                digest=content_digest,
            )
        if create_unresolved_block and (
            value.account_id is None or value.server_id is None or value.reset_identity_id is None
        ):
            self._ensure_historical_unresolved_block(runtime_scope=runtime_scope)
            self.append_reset_binding_assertion(
                ResetBindingAssertion(
                    effect_kind="historical",
                    effect_id=object_id,
                    assertion_state="UNRESOLVED",
                    account_id=value.account_id,
                    server_id=value.server_id,
                    reset_identity_id=value.reset_identity_id,
                    evidence_refs=(),
                    unknown_fields=value.unknown_fields
                    or ("account_id", "server_id", "reset_identity_id"),
                )
            )
        effect_rows = self.store.connection.execute(
            """SELECT historical_effect_id FROM resource_historical_effects
               ORDER BY rowid"""
        ).fetchall()
        if len(effect_rows) >= 2:
            first_id = str(effect_rows[0]["historical_effect_id"])
            second_id = str(effect_rows[1]["historical_effect_id"])
            scope_key = f"{RESOURCE_BLOCK_SCOPE}:{runtime_scope}|{RESOURCE_OBJECTIVE_ACTION_ID}"
            classification_payload = {
                "historical_effect_id": second_id,
                "effect_ids": [first_id, second_id],
                "classification_code": "SUSPECTED_SAME_CYCLE_DUPLICATE",
                "scope_key": scope_key,
            }
            self.append_policy_classification(
                HistoricalPolicyClassification(
                    historical_effect_id=second_id,
                    scope_key=scope_key,
                    classification_id=_id("classification:v1", classification_payload),
                    effect_ids=(first_id, second_id),
                )
            )
        return _row(
            self.store.connection,
            "SELECT * FROM resource_historical_effects WHERE historical_effect_id=?",
            (object_id,),
        ) or {}

    def import_historical_sessions(
        self,
        fixture_path: str | Path,
        *,
        runtime_scope: str = "unknown",
    ) -> dict[str, list[dict[str, Any]]]:
        """Import only the exact files named by a retained-session manifest."""

        path = Path(fixture_path)
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ResourceAuthorityError("historical Resource fixture is unreadable") from exc
        if not isinstance(manifest, Mapping) or not isinstance(manifest.get("sessions"), list):
            raise ResourceAuthorityError("historical Resource fixture sessions are missing")
        transports: list[dict[str, Any]] = []
        effects: list[dict[str, Any]] = []
        validated_sessions: list[Mapping[str, Any]] = []
        for session in manifest["sessions"]:
            if not isinstance(session, Mapping):
                raise ResourceAuthorityError("historical Resource session entry is malformed")
            for artifact_name in ("summary", "events", "transport_source_frame", "settled_post"):
                artifact = session.get(artifact_name)
                if not isinstance(artifact, Mapping):
                    raise ResourceAuthorityError(f"historical {artifact_name} artifact is missing")
                artifact_path = Path(str(artifact.get("path") or ""))
                if not artifact_path.is_file() or artifact_path.is_symlink():
                    raise ResourceAuthorityError(
                        f"named retained historical {artifact_name} file is unavailable"
                    )
                expected = str(artifact.get("sha256") or "")
                actual = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
                if actual.casefold() != expected.casefold():
                    raise ResourceIntegrityError(
                        f"named retained historical {artifact_name} hash mismatch"
                    )
            terminal_home = session.get("terminal_home")
            if terminal_home is not None:
                if not isinstance(terminal_home, Mapping):
                    raise ResourceAuthorityError("historical terminal Home artifact is malformed")
                terminal_path = Path(str(terminal_home.get("path") or ""))
                if not terminal_path.is_file() or terminal_path.is_symlink():
                    raise ResourceAuthorityError(
                        "named retained historical terminal Home file is unavailable"
                    )
                expected_terminal = str(terminal_home.get("sha256") or "")
                actual_terminal = hashlib.sha256(terminal_path.read_bytes()).hexdigest()
                if actual_terminal.casefold() != expected_terminal.casefold():
                    raise ResourceIntegrityError(
                        "named retained historical terminal Home hash mismatch"
                    )
            validated_sessions.append(session)
        for session in validated_sessions:
            source = session["transport_source_frame"]
            settled = session["settled_post"]
            transport = self.import_historical_resource_transport(
                HistoricalResourceTransportFact(
                    historical_session_id=str(session.get("session_id") or ""),
                    action_key=str(session.get("action_key") or ""),
                    transport_at_utc=str(session.get("transport_at_utc") or ""),
                    source_frame_sha256=str(source.get("sha256") or ""),
                    transport_result={"dispatched": True, "transport_code": "native_tap"},
                    unknown_fields=tuple(
                        key
                        for key, value in dict(session.get("unknown_fields") or {}).items()
                        if value is None
                    ),
                    evidence_refs=(
                        str(session["events"]["path"]),
                        str(source["path"]),
                        str(settled["path"]),
                    ),
                )
            )
            effect = self.import_historical_resource_effect(
                HistoricalResourceEffect(
                    historical_session_id=str(session.get("session_id") or ""),
                    transport_fact_id=transport["transport_fact_id"],
                    before_owned_quantity=int(session["owned_quantity"]["before"]),
                    after_owned_quantity=int(session["owned_quantity"]["after"]),
                    # A proven decrement is a confirmed semantic effect even
                    # when terminal Home/parser completion was incomplete.
                    effect_state="CONFIRMED",
                    unknown_fields=tuple(
                        key
                        for key, value in dict(session.get("unknown_fields") or {}).items()
                        if value is None
                    ),
                ),
                runtime_scope=runtime_scope,
            )
            transports.append(transport)
            effects.append(effect)
        if len(effects) >= 2:
            first_id = effects[0]["historical_effect_id"]
            second_id = effects[1]["historical_effect_id"]
            classification_payload = {
                "historical_effect_id": second_id,
                "effect_ids": [first_id, second_id],
                "classification_code": "SUSPECTED_SAME_CYCLE_DUPLICATE",
                "scope_key": f"{RESOURCE_BLOCK_SCOPE}:{runtime_scope}|{RESOURCE_OBJECTIVE_ACTION_ID}",
            }
            self.append_policy_classification(
                HistoricalPolicyClassification(
                    historical_effect_id=second_id,
                    scope_key=classification_payload["scope_key"],
                    classification_id=_id("classification:v1", classification_payload),
                    effect_ids=(first_id, second_id),
                )
            )
            self._ensure_historical_unresolved_block(runtime_scope=runtime_scope)
        return {"transports": transports, "effects": effects}

    def append_policy_classification(
        self,
        classification: HistoricalPolicyClassification | Mapping[str, Any],
    ) -> dict[str, Any]:
        if isinstance(classification, HistoricalPolicyClassification):
            value = classification
        elif isinstance(classification, Mapping):
            value = HistoricalPolicyClassification(
                historical_effect_id=classification.get("historical_effect_id", classification.get("effect_id")),
                classification_code=classification.get(
                    "classification_code", "SUSPECTED_SAME_CYCLE_DUPLICATE"
                ),
                scope_key=classification.get(
                    "scope_key", f"{RESOURCE_BLOCK_SCOPE}:unknown|{RESOURCE_OBJECTIVE_ACTION_ID}"
                ),
                classification_id=classification.get("classification_id"),
                effect_ids=tuple(classification.get("effect_ids", ())),
            )
        else:
            raise ResourceAuthorityError("classification must be typed")
        if value.classification_code != "SUSPECTED_SAME_CYCLE_DUPLICATE":
            raise ResourceAuthorityError("unsupported historical Resource classification")
        payload = {
            "historical_effect_id": value.historical_effect_id,
            "classification_code": value.classification_code,
            "scope_key": value.scope_key,
            "effect_ids": tuple(value.effect_ids) or (value.historical_effect_id,),
        }
        object_id = value.classification_id or _id("classification:v1", payload)
        digest = _digest(payload)
        with self.store.transaction() as db:
            _immutable_insert(
                db,
                table="resource_historical_classifications",
                id_column="classification_id",
                object_id=object_id,
                columns=(
                    "classification_id",
                    "historical_effect_id",
                    "classification_code",
                    "scope_key",
                    "payload_json",
                    "content_digest",
                ),
                values=(
                    object_id,
                    value.historical_effect_id,
                    value.classification_code,
                    value.scope_key,
                    _json(payload),
                    digest,
                ),
                payload=payload,
                digest=digest,
            )
        return _row(
            self.store.connection,
            "SELECT * FROM resource_historical_classifications WHERE classification_id=?",
            (object_id,),
        ) or {}

    def _ensure_historical_unresolved_block(self, *, runtime_scope: str) -> dict[str, Any]:
        scope_key = f"{RESOURCE_BLOCK_SCOPE}:{runtime_scope}|{RESOURCE_OBJECTIVE_ACTION_ID}"
        payload = {
            "scope_key": scope_key,
            "runtime_scope": runtime_scope,
            "objective_action_id": RESOURCE_OBJECTIVE_ACTION_ID,
            "reason": "historical_reset_account_server_unresolved",
        }
        block_id = _id("block:v1", payload)
        digest = _digest(payload)
        with self.store.transaction() as db:
            _immutable_insert(
                db,
                table="resource_effect_block_facts",
                id_column="block_id",
                object_id=block_id,
                columns=(
                    "block_id",
                    "scope_key",
                    "account_id",
                    "server_id",
                    "reset_identity_id",
                    "occurrence_key",
                    "block_reason",
                    "active",
                    "content_digest",
                    "payload_json",
                ),
                values=(
                    block_id,
                    scope_key,
                    None,
                    None,
                    None,
                    None,
                    payload["reason"],
                    1,
                    digest,
                    _json(payload),
                ),
                payload=payload,
                digest=digest,
            )
            projection = _row(
                db,
                "SELECT * FROM resource_effect_block_projection WHERE block_id=?",
                (block_id,),
            )
            if projection is None:
                db.execute(
                    """INSERT INTO resource_effect_block_projection(
                        block_id,scope_key,projection_state,current_reset_id,
                        source_resolution_id,state_revision,updated_at
                    ) VALUES(?,?,?,?,?,?,?)""",
                    (block_id, scope_key, "ACTIVE", None, None, 0, 0.0),
                )
                self._append_transition(
                    db,
                    entity_type="block",
                    entity_id=block_id,
                    state_from=None,
                    state_to="ACTIVE",
                    state_revision=0,
                    recorded_at=0.0,
                    payload=payload,
                )
        return _row(
            self.store.connection,
            "SELECT * FROM resource_effect_block_facts WHERE block_id=?",
            (block_id,),
        ) or {}

    def append_reset_binding_assertion(
        self,
        assertion: ResetBindingAssertion | Mapping[str, Any],
        *,
        now: float = 0.0,
        expected_projection_revision: int | None = None,
    ) -> dict[str, Any]:
        if isinstance(assertion, ResetBindingAssertion):
            value = assertion
        elif isinstance(assertion, Mapping):
            value = ResetBindingAssertion(
                effect_kind=assertion.get("effect_kind"),
                effect_id=assertion.get("effect_id"),
                assertion_state=assertion.get("assertion_state", assertion.get("state", "UNRESOLVED")),
                account_id=assertion.get("account_id"),
                server_id=assertion.get("server_id"),
                reset_identity_id=assertion.get("reset_identity_id"),
                evidence_refs=tuple(assertion.get("evidence_refs", ())),
                unknown_fields=tuple(assertion.get("unknown_fields", ())),
                assertion_id=assertion.get("assertion_id"),
            )
        else:
            raise ResourceAuthorityError("reset binding assertion must be typed")
        if value.effect_kind not in {"historical", "live"}:
            raise ResourceAuthorityError("reset binding effect kind is invalid")
        if value.assertion_state not in {"UNRESOLVED", "BOUND", "CONFLICT"}:
            raise ResourceAuthorityError("reset binding assertion state is invalid")
        _text(value.effect_id, "effect_id")
        for field in ("account_id", "server_id", "reset_identity_id"):
            if getattr(value, field) is not None:
                _text(getattr(value, field), field)
        if value.assertion_state == "BOUND" and (
            value.account_id is None or value.server_id is None or value.reset_identity_id is None
        ):
            raise ResourceAuthorityError("BOUND reset assertion requires account/server/reset")
        if value.assertion_state == "BOUND":
            reset = _row(
                self.store.connection,
                """SELECT 1 FROM resource_reset_identities
                   WHERE account_id=? AND server_id=? AND reset_identity_id=?""",
                (value.account_id, value.server_id, value.reset_identity_id),
            )
            if reset is None:
                raise ResourceAuthorizationDenied(
                    "BOUND reset assertion requires an authoritative reset identity"
                )
        payload = {
            "effect_kind": value.effect_kind,
            "effect_id": value.effect_id,
            "assertion_state": value.assertion_state,
            "account_id": value.account_id,
            "server_id": value.server_id,
            "reset_identity_id": value.reset_identity_id,
            "evidence_refs": _field_refs(value.evidence_refs, "evidence_refs")
            if value.evidence_refs
            else (),
            "unknown_fields": _unknown_fields(value.unknown_fields),
        }
        object_id = value.assertion_id or _id("reset-assertion:v1", payload)
        digest = _digest(payload)
        with self.store.transaction() as db:
            _immutable_insert(
                db,
                table="resource_reset_binding_assertions",
                id_column="assertion_id",
                object_id=object_id,
                columns=(
                    "assertion_id",
                    "effect_kind",
                    "effect_id",
                    "account_id",
                    "server_id",
                    "reset_identity_id",
                    "assertion_state",
                    "evidence_refs_json",
                    "unknown_fields_json",
                    "content_digest",
                    "payload_json",
                ),
                values=(
                    object_id,
                    value.effect_kind,
                    value.effect_id,
                    value.account_id,
                    value.server_id,
                    value.reset_identity_id,
                    value.assertion_state,
                    _json(payload["evidence_refs"]),
                    _json(payload["unknown_fields"]),
                    digest,
                    _json(payload),
                ),
                payload=payload,
                digest=digest,
            )
            projection = _row(
                db,
                """SELECT * FROM resource_reset_binding_projection
                   WHERE effect_kind=? AND effect_id=?""",
                (value.effect_kind, value.effect_id),
            )
            if projection is None:
                db.execute(
                    """INSERT INTO resource_reset_binding_projection(
                        effect_kind,effect_id,assertion_id,account_id,server_id,
                        reset_identity_id,projection_state,state_revision,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        value.effect_kind,
                        value.effect_id,
                        object_id,
                        value.account_id,
                        value.server_id,
                        value.reset_identity_id,
                        value.assertion_state,
                        0,
                        now,
                    ),
                )
                self._append_transition(
                    db,
                    entity_type="reset_binding",
                    entity_id=f"{value.effect_kind}:{value.effect_id}",
                    state_from=None,
                    state_to=value.assertion_state,
                    state_revision=0,
                    recorded_at=now,
                    payload=payload,
                )
            else:
                revision = int(projection["state_revision"])
                if expected_projection_revision is not None and revision != expected_projection_revision:
                    raise ResourceFenceError("reset binding projection revision is stale")
                if (
                    projection["assertion_id"] == object_id
                    and projection["projection_state"] == value.assertion_state
                    and projection["account_id"] == value.account_id
                    and projection["server_id"] == value.server_id
                    and projection["reset_identity_id"] == value.reset_identity_id
                ):
                    return projection
                next_revision = revision + 1
                changed = db.execute(
                    """UPDATE resource_reset_binding_projection
                       SET assertion_id=?,account_id=?,server_id=?,reset_identity_id=?,
                           projection_state=?,state_revision=?,updated_at=?
                       WHERE effect_kind=? AND effect_id=?
                         AND state_revision=?""",
                    (
                        object_id,
                        value.account_id,
                        value.server_id,
                        value.reset_identity_id,
                        value.assertion_state,
                        next_revision,
                        now,
                        value.effect_kind,
                        value.effect_id,
                        revision,
                    ),
                ).rowcount
                if changed != 1:
                    raise ResourceFenceError("reset binding projection compare-and-swap failed")
                self._append_transition(
                    db,
                    entity_type="reset_binding",
                    entity_id=f"{value.effect_kind}:{value.effect_id}",
                    state_from=projection["projection_state"],
                    state_to=value.assertion_state,
                    state_revision=next_revision,
                    recorded_at=now,
                    payload=payload,
                )
        return _row(
            self.store.connection,
            """SELECT * FROM resource_reset_binding_projection
               WHERE effect_kind=? AND effect_id=?""",
            (value.effect_kind, value.effect_id),
        ) or {}

    def _historical_effect_times(self, db: sqlite3.Connection, block_id: str) -> list[datetime]:
        rows = db.execute(
            """SELECT t.transport_at_utc
               FROM resource_historical_effects e
               JOIN resource_historical_transport_facts t
                 ON t.transport_fact_id=e.transport_fact_id
               JOIN resource_historical_classifications c
                 ON c.historical_effect_id=e.historical_effect_id
               WHERE c.scope_key=(SELECT scope_key FROM resource_effect_block_facts WHERE block_id=?)""",
            (block_id,),
        ).fetchall()
        result: list[datetime] = []
        for row in rows:
            if row["transport_at_utc"]:
                try:
                    value = datetime.fromisoformat(str(row["transport_at_utc"]).replace("Z", "+00:00"))
                    if value.tzinfo is None:
                        value = value.replace(tzinfo=timezone.utc)
                    result.append(value.astimezone(timezone.utc))
                except ValueError:
                    continue
        return result

    def append_historical_block_resolution(
        self,
        resolution: ResourceBlockResolution | Mapping[str, Any],
        *,
        now: float = 0.0,
    ) -> dict[str, Any]:
        if isinstance(resolution, ResourceBlockResolution):
            value = resolution
        elif isinstance(resolution, Mapping):
            value = ResourceBlockResolution(
                block_id=resolution.get("block_id"),
                decision=resolution.get("decision"),
                authoritative_evidence=resolution.get("authoritative_evidence", {}),
                current_reset_id=resolution.get("current_reset_id"),
                supersedes_resolution_id=resolution.get("supersedes_resolution_id"),
                resolution_id=resolution.get("resolution_id"),
            )
        else:
            raise ResourceAuthorityError("block resolution must be typed")
        if value.decision not in {
            "KEEP_ACTIVE",
            "CLEAR_FOR_PROVEN_LATER_RESET",
            "SUPERSEDE_SCOPE",
            "CONFLICT",
        }:
            raise ResourceAuthorityError("unsupported Resource block resolution")
        if (
            not isinstance(value.authoritative_evidence, Mapping)
            or not value.authoritative_evidence.get("evidence_refs")
        ):
            raise ResourceAuthorizationDenied(
                "Resource block resolution requires explicit authoritative evidence"
            )
        with self.store.transaction() as db:
            block = _row(
                db,
                "SELECT * FROM resource_effect_block_facts WHERE block_id=?",
                (value.block_id,),
            )
            if block is None:
                raise ResourceAuthorityError("unknown Resource block")
            if not str(block["scope_key"]).startswith(f"{RESOURCE_BLOCK_SCOPE}:"):
                raise ResourceAuthorizationDenied(
                    "historical block resolution cannot rewrite a live occurrence scope"
                )
            if value.decision == "CLEAR_FOR_PROVEN_LATER_RESET":
                if not value.current_reset_id:
                    raise ResourceAuthorityError("later-reset clearing requires a current reset identity")
                reset = _row(
                    db,
                    "SELECT * FROM resource_reset_identities WHERE reset_identity_id=?",
                    (value.current_reset_id,),
                )
                evidence = value.authoritative_evidence
                if reset is None or not isinstance(evidence, Mapping):
                    raise ResourceAuthorizationDenied("authoritative later-reset evidence is incomplete")
                if (
                    evidence.get("account_id") != reset["account_id"]
                    or evidence.get("server_id") != reset["server_id"]
                ):
                    raise ResourceAuthorizationDenied("later-reset evidence is not account/server bound")
                reset_start = datetime.fromisoformat(reset["reset_start_utc"].replace("Z", "+00:00"))
                if any(reset_start <= timestamp for timestamp in self._historical_effect_times(db, value.block_id)):
                    raise ResourceAuthorizationDenied(
                        "later reset does not start strictly after every historical effect"
                    )
            payload = {
                "block_id": value.block_id,
                "decision": value.decision,
                "authoritative_evidence": value.authoritative_evidence,
                "current_reset_id": value.current_reset_id,
                "supersedes_resolution_id": value.supersedes_resolution_id,
            }
            object_id = value.resolution_id or _id("block-resolution:v1", payload)
            digest = _digest(payload)
            _immutable_insert(
                db,
                table="resource_effect_block_resolutions",
                id_column="resolution_id",
                object_id=object_id,
                columns=(
                    "resolution_id",
                    "block_id",
                    "decision",
                    "authoritative_evidence_json",
                    "current_reset_id",
                    "supersedes_resolution_id",
                    "content_digest",
                    "payload_json",
                ),
                values=(
                    object_id,
                    value.block_id,
                    value.decision,
                    _json(value.authoritative_evidence),
                    value.current_reset_id,
                    value.supersedes_resolution_id,
                    digest,
                    _json(payload),
                ),
                payload=payload,
                digest=digest,
            )
            projection = _row(
                db,
                "SELECT * FROM resource_effect_block_projection WHERE block_id=?",
                (value.block_id,),
            )
            if projection is None:
                raise ResourceIntegrityError("Resource block projection is missing")
            if (
                projection["source_resolution_id"] == object_id
                and projection["projection_state"]
                == ("ACTIVE" if value.decision in {"KEEP_ACTIVE", "CONFLICT"} else "CLEARED")
            ):
                return projection
            next_state = "ACTIVE" if value.decision in {"KEEP_ACTIVE", "CONFLICT"} else "CLEARED"
            next_revision = int(projection["state_revision"]) + 1
            changed = db.execute(
                """UPDATE resource_effect_block_projection
                   SET projection_state=?,current_reset_id=?,source_resolution_id=?,
                       state_revision=?,updated_at=?
                   WHERE block_id=? AND state_revision=?""",
                (
                    next_state,
                    value.current_reset_id,
                    object_id,
                    next_revision,
                    now,
                    value.block_id,
                    int(projection["state_revision"]),
                ),
            ).rowcount
            if changed != 1:
                raise ResourceFenceError("Resource block projection compare-and-swap failed")
            self._append_transition(
                db,
                entity_type="block",
                entity_id=value.block_id,
                state_from=projection["projection_state"],
                state_to=next_state,
                state_revision=next_revision,
                recorded_at=now,
                payload=payload,
            )
            return _row(
                db,
                "SELECT * FROM resource_effect_block_projection WHERE block_id=?",
                (value.block_id,),
            ) or {}

    def has_scoped_resource_block(
        self,
        block_keys: Mapping[str, Any] | Sequence[str] = (),
    ) -> bool:
        """Check only matching Resource scopes; unrelated navigation is unaffected."""

        if isinstance(block_keys, Mapping):
            requested = dict(block_keys)
            scope_values = {
                str(value)
                for key, value in requested.items()
                if value is not None and key not in {"reset_identity_id", "reset_id"}
            }
            requested_reset = requested.get("reset_identity_id", requested.get("reset_id"))
            requested_scope = requested.get("scope_key")
        else:
            requested = {}
            scope_values = {str(value) for value in block_keys}
            requested_reset = None
            requested_scope = None
        rows = self.store.connection.execute(
            """SELECT p.*,b.scope_key,b.account_id,b.server_id,b.reset_identity_id,b.occurrence_key
               FROM resource_effect_block_projection p
               JOIN resource_effect_block_facts b ON b.block_id=p.block_id
               WHERE p.projection_state IN ('ACTIVE','CONFLICT','CLEARED')"""
        ).fetchall()
        for row in rows:
            if requested_scope and row["scope_key"] != requested_scope:
                continue
            if scope_values:
                matches = any(
                    value in scope_values
                    for value in (
                        row["scope_key"],
                        row["account_id"],
                        row["server_id"],
                        row["reset_identity_id"],
                        row["occurrence_key"],
                    )
                    if value is not None
                )
                broad_unknown = (
                    str(row["scope_key"]).startswith(f"{RESOURCE_BLOCK_SCOPE}:")
                    and row["account_id"] is None
                    and row["server_id"] is None
                    and row["reset_identity_id"] is None
                    and row["occurrence_key"] is None
                )
                if not matches and not broad_unknown:
                    continue
            if requested_reset is not None and row["projection_state"] == "CLEARED":
                if row["current_reset_id"] == requested_reset:
                    continue
            if row["projection_state"] in {"ACTIVE", "CONFLICT"}:
                return True
            if row["projection_state"] == "CLEARED" and requested_reset is None:
                return True
            if row["projection_state"] == "CLEARED" and row["current_reset_id"] != requested_reset:
                return True
        return False

    @staticmethod
    def resource_action_key(context: ResourceAuthorizationContext, authorization_generation: int) -> str:
        if type(context) is not ResourceAuthorizationContext:
            raise ResourceAuthorityError("Resource action key requires a typed context")
        if type(authorization_generation) is not int or authorization_generation < 1:
            raise ResourceAuthorityError("authorization generation must be positive")
        return (
            f"{context.occurrence_key}:effect:{context.effect_ordinal}:"
            f"generation:{authorization_generation}"
        )

    @staticmethod
    def resource_reservation_id(
        context: ResourceAuthorizationContext,
        authorization_generation: int,
    ) -> str:
        if type(context) is not ResourceAuthorizationContext:
            raise ResourceAuthorityError("Resource reservation id requires a typed context")
        if type(authorization_generation) is not int or authorization_generation < 1:
            raise ResourceAuthorityError("authorization generation must be positive")
        return _id(
            "reservation:v1",
            {
                "occurrence_id": context.occurrence_id,
                "effect_ordinal": context.effect_ordinal,
                "authorization_generation": authorization_generation,
            },
        )

    def next_resource_authorization_generation(
        self,
        occurrence: ResourceAuthorizationContext | Mapping[str, Any] | str,
    ) -> int:
        """Return the next durable generation for one occurrence/effect ordinal.

        The read is performed in a transaction so callers never derive a
        generation from an unrelated occurrence.  The immutable reservation
        unique constraint and the atomic preparation transaction remain the
        final concurrency authority when two callers race.
        """

        context = (
            occurrence
            if isinstance(occurrence, ResourceAuthorizationContext)
            else self.occurrence_context(str(occurrence))
            if isinstance(occurrence, str)
            else ResourceAuthorizationContext(**dict(occurrence))
        )
        with self.store.transaction() as db:
            row = db.execute(
                """SELECT MAX(authorization_generation) AS maximum_generation
                   FROM resource_reservations
                   WHERE occurrence_id=? AND effect_ordinal=?""",
                (context.occurrence_id, context.effect_ordinal),
            ).fetchone()
            maximum = int(row["maximum_generation"] or 0) if row is not None else 0
            return maximum + 1

    @staticmethod
    def resource_dispatch_fence(
        context: ResourceAuthorizationContext,
        claim: ResourceAttemptClaim,
        controller_lease: Mapping[str, Any],
        reservation_spec: ResourceReservationSpec,
    ) -> EffectDispatchFence:
        """Derive the pre-authorization fence used by atomic preparation."""

        if type(context) is not ResourceAuthorizationContext:
            raise ResourceFenceError("Resource dispatch fence requires a typed context")
        if type(claim) is not ResourceAttemptClaim:
            raise ResourceFenceError("Resource dispatch fence requires a typed claim")
        if type(reservation_spec) is not ResourceReservationSpec:
            raise ResourceFenceError("Resource dispatch fence requires a typed reservation spec")
        controller_token = str(
            controller_lease.get("controller_token")
            or controller_lease.get("lease_token")
            or ""
        )
        try:
            controller_generation = int(
                controller_lease.get(
                    "controller_generation",
                    controller_lease.get("generation", 0),
                )
            )
        except (TypeError, ValueError) as exc:
            raise ResourceFenceError("Resource controller generation is malformed") from exc
        if not controller_token or controller_generation < 1:
            raise ResourceFenceError("Resource controller token and generation are required")
        if reservation_spec.controller_token != controller_token:
            raise ResourceFenceError("Resource reservation controller token is stale")
        if reservation_spec.controller_generation != controller_generation:
            raise ResourceFenceError("Resource reservation controller generation is stale")
        return EffectDispatchFence(
            occurrence_id=context.occurrence_id,
            attempt_id=claim.attempt_id,
            reservation_id=ResourceEffectAuthority.resource_reservation_id(
                context,
                reservation_spec.authorization_generation,
            ),
            claim_token_digest=claim.claim_token_digest,
            claim_epoch=claim.claim_epoch,
            controller_token_digest=hashlib.sha256(
                controller_token.encode("utf-8")
            ).hexdigest(),
            controller_generation=controller_generation,
            runtime_invocation_id=reservation_spec.runtime_invocation_id,
            reservation_state_revision=0,
            immediate_before_sha256=reservation_spec.immediate_before_sha256,
        )

    def _assert_claim(self, claim: ResourceAttemptClaim, *, now: float) -> None:
        if type(claim) is not ResourceAttemptClaim or not claim.can_dispatch:
            raise ResourceFenceError("Resource attempt claim has no dispatch authority")
        if claim.state != "ACTIVE" or claim.claim_token is None or claim.expires_at <= now:
            raise ResourceFenceError("Resource attempt claim is expired or not active")
        row = _row(
            self.store.connection,
            """SELECT * FROM resource_attempt_claims
               WHERE claim_id=? AND attempt_id=? AND occurrence_id=?""",
            (claim.claim_id, claim.attempt_id, claim.occurrence_id),
        )
        if row is None or row["state"] != "ACTIVE" or float(row["expires_at"]) <= now:
            raise ResourceFenceError("durable Resource claim lease is stale")
        if row["claim_token_digest"] != claim.claim_token_digest:
            raise ResourceFenceError("Resource claim token does not match durable digest")
        if int(row["claim_epoch"]) != claim.claim_epoch:
            raise ResourceFenceError("Resource claim epoch is stale")

    def _assert_controller(
        self,
        controller_lease: Mapping[str, Any],
        *,
        now: float,
        mode: str = "execute",
    ) -> None:
        if not isinstance(controller_lease, Mapping):
            raise ResourceFenceError("Resource controller lease is required")
        try:
            generation = int(
                controller_lease.get("controller_generation", controller_lease.get("generation", 0))
            )
        except (TypeError, ValueError) as exc:
            raise ResourceFenceError("Resource controller generation is malformed") from exc
        if not self.store.resource_controller_lease_valid(
            str(controller_lease.get("owner_id") or ""),
            str(controller_lease.get("controller_token") or controller_lease.get("lease_token") or ""),
            generation,
            str(controller_lease.get("runtime_invocation_id") or ""),
            now,
            mode=mode,
        ):
            raise ResourceFenceError("Resource controller lease token or generation is stale")

    def _cas_occurrence(
        self,
        db: sqlite3.Connection,
        *,
        occurrence_id: str,
        expected_states: set[str],
        next_state: str,
        now: float,
        reason: str,
    ) -> dict[str, Any]:
        current = _row(
            db,
            "SELECT * FROM resource_occurrences WHERE occurrence_id=?",
            (occurrence_id,),
        )
        if current is None:
            raise ResourceAuthorityError("unknown Resource occurrence")
        if current["state"] not in expected_states:
            raise ResourceAuthorizationDenied(
                f"Resource occurrence state {current['state']} is not eligible for {next_state}"
            )
        revision = int(current["state_revision"])
        next_revision = revision + 1
        changed = db.execute(
            """UPDATE resource_occurrences
               SET state=?,state_revision=?,updated_at=?
               WHERE occurrence_id=? AND state=? AND state_revision=?""",
            (
                next_state,
                next_revision,
                now,
                occurrence_id,
                current["state"],
                revision,
            ),
        ).rowcount
        if changed != 1:
            raise ResourceFenceError("Resource occurrence compare-and-swap failed")
        self._append_transition(
            db,
            entity_type="occurrence",
            entity_id=occurrence_id,
            state_from=current["state"],
            state_to=next_state,
            state_revision=next_revision,
            recorded_at=now,
            payload={"reason": reason},
        )
        return _row(
            db,
            "SELECT * FROM resource_occurrences WHERE occurrence_id=?",
            (occurrence_id,),
        ) or {}

    def prepare_resource_effect_action(
        self,
        occurrence: ResourceAuthorizationContext | Mapping[str, Any] | str,
        attempt: ResourceAttemptClaim | Mapping[str, Any],
        claim_lease: ResourceAttemptClaim | Mapping[str, Any] | None,
        controller_lease: Mapping[str, Any],
        intent: ActionIntent,
        policy: PolicyResult,
        reservation_spec: ResourceReservationSpec | Mapping[str, Any],
        now: float = 0.0,
    ) -> PreparedResourceEffect:
        """Atomically insert v3 action + Resource reservation + audit/projections."""

        self._assert_v4()
        context = (
            occurrence
            if isinstance(occurrence, ResourceAuthorizationContext)
            else self.occurrence_context(str(occurrence))
            if isinstance(occurrence, str)
            else ResourceAuthorizationContext(**dict(occurrence))
        )
        if isinstance(reservation_spec, ResourceReservationSpec):
            spec = reservation_spec
        else:
            spec = ResourceReservationSpec(**dict(reservation_spec))
        claim = claim_lease
        if claim is None and isinstance(attempt, ResourceAttemptClaim):
            claim = attempt
        if not isinstance(claim, ResourceAttemptClaim):
            raise ResourceFenceError("Resource claim lease is required")
        self._assert_claim(claim, now=now)
        self._assert_controller(controller_lease, now=now, mode="execute")
        if type(intent) is not ActionIntent or type(policy) is not PolicyResult:
            raise ResourceAuthorityError("typed action intent and policy result are required")
        if (
            policy.decision.value != "authorize"
            or intent.action_class is not ActionClass.OWNED_ITEM_NON_IDEMPOTENT
            or intent.consequential is not False
        ):
            raise ResourceAuthorizationDenied("Resource action policy did not authorize the dedicated action class")
        if intent.resource_authorization_context != context:
            raise ResourceFenceError("ActionIntent Resource context does not match occurrence")
        if policy.request_snapshot.get("resource_authorization_context", {}).get(
            "occurrence_key"
        ) not in {None, context.occurrence_key}:
            raise ResourceFenceError("Policy snapshot Resource context does not match occurrence")
        expected_key = self.resource_action_key(context, spec.authorization_generation)
        if intent.action_key != expected_key:
            raise ResourceFenceError("Resource action key is not occurrence/effect/generation bound")
        if self.has_scoped_resource_block(
            {
                "scope_key": f"{RESOURCE_BLOCK_SCOPE}:unknown|{RESOURCE_OBJECTIVE_ACTION_ID}",
                "account_id": context.account_id,
                "server_id": context.server_id,
                "reset_identity_id": context.reset_identity_id,
                "occurrence_key": context.occurrence_key,
            }
        ) or self.has_scoped_resource_block(
            {
                "scope_key": f"occurrence:{context.occurrence_key}|{RESOURCE_OBJECTIVE_ACTION_ID}",
                "occurrence_key": context.occurrence_key,
                "reset_identity_id": context.reset_identity_id,
            }
        ):
            raise ResourceAuthorizationDenied("active scoped Resource effect block prevents reservation")
        if self.store.has_action_block():
            raise ResourceAuthorizationDenied(
                "legacy global consequential action block prevents Resource execution"
            )
        controller_token = str(
            controller_lease.get("controller_token") or controller_lease.get("lease_token") or ""
        )
        controller_generation = int(
            controller_lease.get("controller_generation", controller_lease.get("generation", 0))
        )
        fence = self.resource_dispatch_fence(context, claim, controller_lease, spec)
        reservation_id = fence.reservation_id
        payload = {
            "reservation_id": reservation_id,
            "occurrence_id": context.occurrence_id,
            "attempt_id": claim.attempt_id,
            "action_id": intent.action_id,
            "action_key": intent.action_key,
            "effect_ordinal": context.effect_ordinal,
            "authorization_generation": spec.authorization_generation,
            "state": "RESERVED",
            "state_revision": 0,
            "account_id": context.account_id,
            "server_id": context.server_id,
            "reset_identity_id": context.reset_identity_id,
            "product_policy_revision": context.product_policy_revision,
            "recurrence_policy_revision": context.recurrence_policy_revision,
            "authorization_context_digest": context.digest(),
            "claim_token_digest": claim.claim_token_digest,
            "claim_epoch": claim.claim_epoch,
            "controller_token_digest": fence.controller_token_digest,
            "controller_generation": controller_generation,
            "runtime_invocation_id": spec.runtime_invocation_id,
            "immediate_before_sha256": spec.immediate_before_sha256,
        }
        digest = _digest(payload)
        with self.store.transaction() as db:
            existing_effect = db.execute(
                """SELECT 1 FROM resource_live_effects
                   WHERE occurrence_id=? AND effect_ordinal=? AND effect_state='CONFIRMED'""",
                (context.occurrence_id, context.effect_ordinal),
            ).fetchone()
            if existing_effect is not None:
                raise ResourceAuthorizationDenied("one Resource effect already exists for this occurrence")
            existing_reservation = db.execute(
                """SELECT * FROM resource_reservations
                   WHERE occurrence_id=? AND effect_ordinal=? AND authorization_generation=?""",
                (context.occurrence_id, context.effect_ordinal, spec.authorization_generation),
            ).fetchone()
            if existing_reservation is not None:
                raise ResourceAuthorizationDenied("Resource authorization generation was already reserved")
            self.store._insert_action(db, intent, policy, now)
            _immutable_insert(
                db,
                table="resource_reservations",
                id_column="reservation_id",
                object_id=reservation_id,
                columns=(
                    "reservation_id",
                    "occurrence_id",
                    "attempt_id",
                    "action_id",
                    "effect_ordinal",
                    "authorization_generation",
                    "state",
                    "state_revision",
                    "account_id",
                    "server_id",
                    "reset_identity_id",
                    "product_policy_revision",
                    "recurrence_policy_revision",
                    "authorization_context_digest",
                    "claim_token_digest",
                    "claim_epoch",
                    "controller_token_digest",
                    "controller_generation",
                    "runtime_invocation_id",
                    "immediate_before_sha256",
                    "created_at",
                    "updated_at",
                    "content_digest",
                    "payload_json",
                ),
                values=(
                    reservation_id,
                    context.occurrence_id,
                    claim.attempt_id,
                    intent.action_id,
                    context.effect_ordinal,
                    spec.authorization_generation,
                    "RESERVED",
                    0,
                    context.account_id,
                    context.server_id,
                    context.reset_identity_id,
                    context.product_policy_revision,
                    context.recurrence_policy_revision,
                    context.digest(),
                    claim.claim_token_digest,
                    claim.claim_epoch,
                    fence.controller_token_digest,
                    controller_generation,
                    spec.runtime_invocation_id,
                    spec.immediate_before_sha256,
                    now,
                    now,
                    digest,
                    _json(payload),
                ),
                payload=payload,
                digest=digest,
            )
            self._append_transition(
                db,
                entity_type="reservation",
                entity_id=reservation_id,
                state_from=None,
                state_to="RESERVED",
                state_revision=0,
                recorded_at=now,
                payload=payload,
            )
            updated_claim = db.execute(
                """UPDATE resource_attempt_claims
                   SET reservation_id=?
                   WHERE claim_id=? AND attempt_id=? AND state='ACTIVE'""",
                (reservation_id, claim.claim_id, claim.attempt_id),
            ).rowcount
            if updated_claim != 1:
                raise ResourceFenceError("claim was lost before reservation binding")
            self._cas_occurrence(
                db,
                occurrence_id=context.occurrence_id,
                expected_states={"ELIGIBLE", "NO_EFFECT"},
                next_state="RESERVED",
                now=now,
                reason="resource_reservation_prepared",
            )
        return PreparedResourceEffect(
            context.occurrence_id,
            claim.attempt_id,
            reservation_id,
            intent.action_id,
            intent.action_key,
            spec.authorization_generation,
            0,
            context,
            fence,
        )

    def cancel_prepared_resource_effect(
        self,
        prepared: PreparedResourceEffect,
        *,
        controller_lease: Mapping[str, Any],
        runtime_lock: Any,
        reason: str,
        now: float = 0.0,
    ) -> dict[str, Any]:
        """Atomically close one prepared effect before any transport intent.

        This is deliberately narrower than transport outcome handling: the
        exact prepared fence, live controller lease, and held runtime lock are
        required, and any transport fact makes cancellation fail closed.
        """

        if type(prepared) is not PreparedResourceEffect:
            raise ResourceFenceError("typed prepared Resource effect is required")
        if reason != RESOURCE_PRE_INTENT_CANCELLATION_REASON:
            raise ResourceAuthorizationDenied(
                "unsupported prepared Resource cancellation reason"
            )
        if (
            prepared.fence.occurrence_id != prepared.occurrence_id
            or prepared.fence.attempt_id != prepared.attempt_id
            or prepared.fence.reservation_id != prepared.reservation_id
            or prepared.fence.reservation_state_revision
            != prepared.reservation_state_revision
        ):
            raise ResourceFenceError(
                "prepared Resource fence identity does not match prepared effect"
            )
        if not isinstance(controller_lease, Mapping):
            raise ResourceFenceError("Resource controller lease is required")
        try:
            owner_id = str(controller_lease.get("owner_id") or "")
            controller_token = str(
                controller_lease.get("controller_token")
                or controller_lease.get("lease_token")
                or ""
            )
            controller_generation = int(
                controller_lease.get(
                    "controller_generation", controller_lease.get("generation", 0)
                )
            )
        except (TypeError, ValueError) as exc:
            raise ResourceFenceError("Resource controller lease is malformed") from exc
        if not owner_id or not controller_token or controller_generation < 1:
            raise ResourceFenceError("Resource controller lease is incomplete")
        assert_held = getattr(runtime_lock, "assert_held", None)
        if not callable(assert_held):
            raise ResourceFenceError("held Resource runtime lock is required")
        try:
            assert_held(owner_id, prepared.fence.runtime_invocation_id)
        except BaseException as exc:
            raise ResourceFenceError("Resource runtime lock is not held") from exc

        cancellation_payload = {
            "reason": reason,
            "adapter_invoked": False,
            "transport_intent_absent": True,
            "prepared_effect": {
                "occurrence_id": prepared.occurrence_id,
                "attempt_id": prepared.attempt_id,
                "reservation_id": prepared.reservation_id,
                "action_id": prepared.action_id,
                "action_key": prepared.action_key,
                "authorization_generation": prepared.authorization_generation,
                "reservation_state_revision": prepared.reservation_state_revision,
                "fence": prepared.fence.as_dict(),
            },
        }

        with self.store.transaction() as db:
            lease = _row(
                db,
                "SELECT * FROM controller_lease WHERE singleton=1",
                (),
            )
            if (
                lease is None
                or lease["owner_id"] != owner_id
                or lease["released_at"] is not None
                or float(lease["expires_at"]) <= now
                or int(lease["generation"]) != controller_generation
                or lease["runtime_invocation_id"] != prepared.fence.runtime_invocation_id
                or lease["lease_mode"] != "execute"
                or lease["lease_token_digest"] != self.store._lease_token_digest(controller_token)
            ):
                raise ResourceFenceError("Resource controller lease is stale")

            reservation = _row(
                db,
                "SELECT * FROM resource_reservations WHERE reservation_id=?",
                (prepared.reservation_id,),
            )
            if reservation is None:
                raise ResourceFenceError("prepared Resource reservation disappeared")
            if (
                reservation["occurrence_id"] != prepared.occurrence_id
                or reservation["attempt_id"] != prepared.attempt_id
                or reservation["action_id"] != prepared.action_id
                or int(reservation["effect_ordinal"]) != prepared.context.effect_ordinal
                or int(reservation["authorization_generation"])
                != prepared.authorization_generation
                or reservation["authorization_context_digest"] != prepared.context.digest()
                or reservation["claim_token_digest"] != prepared.fence.claim_token_digest
                or int(reservation["claim_epoch"]) != prepared.fence.claim_epoch
                or reservation["controller_token_digest"]
                != prepared.fence.controller_token_digest
                or int(reservation["controller_generation"])
                != prepared.fence.controller_generation
                or reservation["runtime_invocation_id"]
                != prepared.fence.runtime_invocation_id
                or reservation["immediate_before_sha256"]
                != prepared.fence.immediate_before_sha256
            ):
                raise ResourceFenceError("prepared Resource fence binding is inconsistent")

            occurrence = _row(
                db,
                "SELECT * FROM resource_occurrences WHERE occurrence_id=?",
                (prepared.occurrence_id,),
            )
            attempt = _row(
                db,
                "SELECT * FROM resource_attempts WHERE attempt_id=? AND occurrence_id=?",
                (prepared.attempt_id, prepared.occurrence_id),
            )
            claim = _row(
                db,
                """SELECT * FROM resource_attempt_claims
                   WHERE attempt_id=? AND occurrence_id=? AND claim_epoch=?
                     AND claim_token_digest=?""",
                (
                    prepared.attempt_id,
                    prepared.occurrence_id,
                    prepared.fence.claim_epoch,
                    prepared.fence.claim_token_digest,
                ),
            )
            action = _row(
                db,
                "SELECT * FROM actions WHERE action_id=? AND action_key=?",
                (prepared.action_id, prepared.action_key),
            )
            if occurrence is None or attempt is None or claim is None or action is None:
                raise ResourceFenceError("prepared Resource entity binding is incomplete")
            if (
                occurrence["account_id"] != prepared.context.account_id
                or occurrence["server_id"] != prepared.context.server_id
                or occurrence["reset_identity_id"] != prepared.context.reset_identity_id
                or occurrence["occurrence_key"] != prepared.context.occurrence_key
            ):
                raise ResourceFenceError("prepared Resource occurrence fence is stale")
            if db.execute(
                "SELECT 1 FROM resource_transport_facts WHERE reservation_id=?",
                (prepared.reservation_id,),
            ).fetchone() is not None or db.execute(
                "SELECT 1 FROM resource_transport_outcomes WHERE reservation_id=?",
                (prepared.reservation_id,),
            ).fetchone() is not None:
                raise ResourceFenceError(
                    "Resource transport already exists for prepared cancellation"
                )

            # A second call is safe only when the exact prior terminalization
            # is present.  Any other terminal state is a stale fence.
            if reservation["state"] == "CLOSED":
                prior = _row(
                    db,
                    """SELECT payload_json FROM resource_transition_history
                       WHERE entity_type='reservation' AND entity_id=?
                         AND state_from='RESERVED' AND state_to='CLOSED'
                         AND state_revision=?""",
                    (prepared.reservation_id, prepared.reservation_state_revision + 1),
                )
                try:
                    prior_payload = (
                        json.loads(str(prior["payload_json"])) if prior is not None else {}
                    )
                except (TypeError, ValueError, json.JSONDecodeError):
                    prior_payload = {}
                if (
                    prior_payload.get("payload", {}).get("reason") != reason
                    or attempt["state"] != "ABANDONED"
                    or claim["state"] != "RELEASED"
                    or occurrence["state"] != "BLOCKED"
                    or action["final_status"] != "cancelled"
                ):
                    raise ResourceFenceError("prepared Resource cancellation is not repeatable")
                return {
                    "reservation_id": prepared.reservation_id,
                    "action_id": prepared.action_id,
                    "idempotent": True,
                    "reason": reason,
                    "adapter_invoked": False,
                    "transport_intent_absent": True,
                }

            if (
                reservation["state"] != "RESERVED"
                or int(reservation["state_revision"])
                != prepared.reservation_state_revision
                or occurrence["state"] != "RESERVED"
                or attempt["state"] != "CLAIMED"
                or claim["state"] != "ACTIVE"
                or claim["reservation_id"] != prepared.reservation_id
                or action["final_status"] != "prepared"
                or action["input_attempt_at"] is not None
                or action["transport_result_json"] is not None
            ):
                raise ResourceFenceError("prepared Resource effect is no longer pre-input")

            reservation_revision = int(reservation["state_revision"]) + 1
            if db.execute(
                """UPDATE resource_reservations
                   SET state='CLOSED',state_revision=?,updated_at=?
                   WHERE reservation_id=? AND state='RESERVED' AND state_revision=?""",
                (
                    reservation_revision,
                    now,
                    prepared.reservation_id,
                    prepared.reservation_state_revision,
                ),
            ).rowcount != 1:
                raise ResourceFenceError("Resource reservation close compare-and-swap failed")
            self._append_transition(
                db,
                entity_type="reservation",
                entity_id=prepared.reservation_id,
                state_from="RESERVED",
                state_to="CLOSED",
                state_revision=reservation_revision,
                recorded_at=now,
                payload=cancellation_payload,
            )

            attempt_revision = int(attempt["state_revision"]) + 1
            if db.execute(
                """UPDATE resource_attempts
                   SET state='ABANDONED',state_revision=?,updated_at=?
                   WHERE attempt_id=? AND occurrence_id=? AND state='CLAIMED'
                     AND state_revision=?""",
                (
                    attempt_revision,
                    now,
                    prepared.attempt_id,
                    prepared.occurrence_id,
                    int(attempt["state_revision"]),
                ),
            ).rowcount != 1:
                raise ResourceFenceError("Resource attempt abandon compare-and-swap failed")
            self._append_transition(
                db,
                entity_type="attempt",
                entity_id=prepared.attempt_id,
                state_from="CLAIMED",
                state_to="ABANDONED",
                state_revision=attempt_revision,
                recorded_at=now,
                payload=cancellation_payload,
            )

            if db.execute(
                """UPDATE resource_attempt_claims SET state='RELEASED'
                   WHERE claim_id=? AND attempt_id=? AND occurrence_id=?
                     AND state='ACTIVE' AND reservation_id=?""",
                (
                    claim["claim_id"],
                    prepared.attempt_id,
                    prepared.occurrence_id,
                    prepared.reservation_id,
                ),
            ).rowcount != 1:
                raise ResourceFenceError("Resource claim release compare-and-swap failed")
            self._append_transition(
                db,
                entity_type="claim",
                entity_id=claim["claim_id"],
                state_from="ACTIVE",
                state_to="RELEASED",
                state_revision=int(claim["claim_epoch"]),
                recorded_at=now,
                payload=cancellation_payload,
            )

            self._cas_occurrence(
                db,
                occurrence_id=prepared.occurrence_id,
                expected_states={"RESERVED"},
                next_state="BLOCKED",
                now=now,
                reason=reason,
            )
            # The action is transitioned directly because the surrounding
            # Resource transaction must include every linked state change.
            if db.execute(
                """UPDATE actions SET final_status='cancelled',final_reason=?,updated_at=?
                   WHERE action_id=? AND action_key=? AND final_status='prepared'
                     AND input_attempt_at IS NULL AND transport_result_json IS NULL""",
                (reason, now, prepared.action_id, prepared.action_key),
            ).rowcount != 1:
                raise ResourceFenceError("prepared action cancellation compare-and-swap failed")
            self.store._insert_audit(
                db,
                action["task_id"],
                "action_transition",
                now,
                {
                    "reason": reason,
                    "adapter_invoked": False,
                    "transport_intent_absent": True,
                },
                prepared.action_id,
                "prepared",
                "cancelled",
            )
            return {
                "reservation_id": prepared.reservation_id,
                "action_id": prepared.action_id,
                "idempotent": False,
                "reason": reason,
                "adapter_invoked": False,
                "transport_intent_absent": True,
            }

    def _reservation(self, reservation_id: str) -> dict[str, Any]:
        value = _row(
            self.store.connection,
            "SELECT * FROM resource_reservations WHERE reservation_id=?",
            (reservation_id,),
        )
        if value is None:
            raise ResourceAuthorityError("unknown Resource reservation")
        return value

    def _assert_prepared_fence(
        self,
        prepared: PreparedResourceEffect,
        *,
        controller_lease: Mapping[str, Any],
        now: float,
        runtime_invocation_id: str,
    ) -> dict[str, Any]:
        if prepared.fence.runtime_invocation_id != runtime_invocation_id:
            raise ResourceFenceError("runtime invocation does not match Resource fence")
        self._assert_controller(controller_lease, now=now, mode="execute")
        row = self._reservation(prepared.reservation_id)
        if row["occurrence_id"] != prepared.occurrence_id or row["attempt_id"] != prepared.attempt_id:
            raise ResourceFenceError("reservation occurrence/attempt binding is inconsistent")
        if row["state"] != "RESERVED" or int(row["state_revision"]) != prepared.reservation_state_revision:
            raise ResourceFenceError("reservation is stale or already consumed")
        if row["authorization_context_digest"] != prepared.context.digest():
            raise ResourceFenceError("reservation context digest mismatch")
        if row["immediate_before_sha256"] != prepared.fence.immediate_before_sha256:
            raise ResourceFenceError("immediate-before frame digest mismatch")
        if row["controller_token_digest"] != prepared.fence.controller_token_digest:
            raise ResourceFenceError("controller token digest mismatch")
        if int(row["controller_generation"]) != prepared.fence.controller_generation:
            raise ResourceFenceError("controller lease generation mismatch")
        if row["runtime_invocation_id"] != runtime_invocation_id:
            raise ResourceFenceError("reservation runtime invocation mismatch")
        return row

    def record_resource_transport_intent(
        self,
        prepared: PreparedResourceEffect,
        *,
        controller_lease: Mapping[str, Any],
        runtime_lock: Any,
        capability: Any,
        request: Any,
        policy: Any,
        now: float,
    ) -> ResourceTransportIntentToken:
        """Persist one intent before the adapter is permitted to run."""

        runtime_invocation_id = prepared.fence.runtime_invocation_id
        assert_held = getattr(runtime_lock, "assert_held", None)
        if not callable(assert_held):
            raise ResourceFenceError("same-connection RuntimeInputLock assertion is required")
        assert_held(str(controller_lease.get("owner_id") or ""), runtime_invocation_id)
        row = self._assert_prepared_fence(
            prepared,
            controller_lease=controller_lease,
            now=now,
            runtime_invocation_id=runtime_invocation_id,
        )
        request_context = getattr(request, "resource_authorization_context", None)
        request_fence = getattr(request, "effect_dispatch_fence", None)
        if request_context != prepared.context:
            raise ResourceFenceError("PolicyRequest Resource context does not match prepared context")
        if request_fence != prepared.fence:
            raise ResourceFenceError("PolicyRequest effect fence does not match prepared fence")
        observation = getattr(request, "observation", None)
        if (
            observation is None
            or getattr(observation, "frame_sha256", None)
            != prepared.fence.immediate_before_sha256
        ):
            raise ResourceFenceError("adapter source frame is not the prepared immediate-before frame")
        if capability is None or not callable(getattr(policy, "evaluate_capability", None)):
            raise ResourceFenceError("policy capability evaluator is required")
        evaluated = policy.evaluate_capability(capability, request)
        if not evaluated.binding_matched or evaluated.reason_code != "CAPABILITY_AUTHORIZED":
            raise ResourceFenceError("capability binding failed before transport intent")
        transport_payload = {
            "reservation_id": prepared.reservation_id,
            "occurrence_id": prepared.occurrence_id,
            "attempt_id": prepared.attempt_id,
            "authorization_context_digest": prepared.context.digest(),
            "runtime_invocation_id": runtime_invocation_id,
            "state": "INTENT_RECORDED",
            "reservation_state_revision": int(row["state_revision"]) + 1,
            "fence": prepared.fence.as_dict(),
        }
        transport_fact_id = _id("transport:v1", transport_payload)
        digest = _digest(transport_payload)
        with self.store.transaction() as db:
            current = _row(
                db,
                "SELECT * FROM resource_reservations WHERE reservation_id=?",
                (prepared.reservation_id,),
            )
            if current is None or current["state"] != "RESERVED" or int(current["state_revision"]) != prepared.reservation_state_revision:
                raise ResourceFenceError("reservation changed before intent commit")
            if db.execute(
                "SELECT 1 FROM resource_transport_facts WHERE reservation_id=?",
                (prepared.reservation_id,),
            ).fetchone():
                raise ResourceFenceError("one transport intent already exists for reservation")
            next_revision = int(current["state_revision"]) + 1
            changed = db.execute(
                """UPDATE resource_reservations
                   SET state='DISPATCHING',state_revision=?,updated_at=?
                   WHERE reservation_id=? AND state='RESERVED' AND state_revision=?""",
                (next_revision, now, prepared.reservation_id, prepared.reservation_state_revision),
            ).rowcount
            if changed != 1:
                raise ResourceFenceError("reservation intent compare-and-swap failed")
            _immutable_insert(
                db,
                table="resource_transport_facts",
                id_column="transport_fact_id",
                object_id=transport_fact_id,
                columns=(
                    "transport_fact_id",
                    "reservation_id",
                    "occurrence_id",
                    "attempt_id",
                    "account_id",
                    "server_id",
                    "state",
                    "runtime_invocation_id",
                    "adapter_invoked",
                    "transport_result_json",
                    "recorded_at",
                    "content_digest",
                    "payload_json",
                ),
                values=(
                    transport_fact_id,
                    prepared.reservation_id,
                    prepared.occurrence_id,
                    prepared.attempt_id,
                    prepared.context.account_id,
                    prepared.context.server_id,
                    "INTENT_RECORDED",
                    runtime_invocation_id,
                    0,
                    None,
                    now,
                    digest,
                    _json(transport_payload),
                ),
                payload=transport_payload,
                digest=digest,
            )
            self._append_transition(
                db,
                entity_type="reservation",
                entity_id=prepared.reservation_id,
                state_from="RESERVED",
                state_to="DISPATCHING",
                state_revision=next_revision,
                recorded_at=now,
                payload=transport_payload,
            )
        return ResourceTransportIntentToken._mint(
            self._transport_marker,
            prepared.reservation_id,
            transport_fact_id,
            runtime_invocation_id,
        )

    def consume_transport_intent(
        self,
        token: ResourceTransportIntentToken,
        *,
        reservation_id: str,
        runtime_invocation_id: str,
    ) -> ResourceTransportIntentToken:
        if type(token) is not ResourceTransportIntentToken:
            raise ResourceFenceError("opaque Resource transport-intent token is required")
        if getattr(token, "_authority_marker", None) is not self._transport_marker:
            raise ResourceFenceError("transport-intent token belongs to another authority")
        if token.consumed or token.reservation_id != reservation_id or token.runtime_invocation_id != runtime_invocation_id:
            raise ResourceFenceError("transport-intent token is stale or already consumed")
        object.__setattr__(token, "_consumed", True)
        return token

    def _append_closure(
        self,
        db: sqlite3.Connection,
        *,
        reservation: Mapping[str, Any],
        closure_kind: str,
        reason: str,
        payload: Any,
    ) -> None:
        closure_payload = {
            "reservation_id": reservation["reservation_id"],
            "occurrence_id": reservation["occurrence_id"],
            "attempt_id": reservation["attempt_id"],
            "closure_kind": closure_kind,
            "reason": reason,
            "payload": _canonical(payload),
        }
        closure_id = _id("closure:v1", closure_payload)
        digest = _digest(closure_payload)
        _immutable_insert(
            db,
            table="resource_closures",
            id_column="closure_id",
            object_id=closure_id,
            columns=(
                "closure_id",
                "reservation_id",
                "occurrence_id",
                "attempt_id",
                "closure_kind",
                "reason",
                "content_digest",
                "payload_json",
            ),
            values=(
                closure_id,
                reservation["reservation_id"],
                reservation["occurrence_id"],
                reservation["attempt_id"],
                closure_kind,
                reason,
                digest,
                _json(closure_payload),
            ),
            payload=closure_payload,
            digest=digest,
        )

    def _finish_resource_transport(
        self,
        prepared: PreparedResourceEffect,
        *,
        state: str,
        result: Any,
        now: float,
        adapter_invoked: bool,
    ) -> None:
        if state not in {"NOT_SENT", "SENT_ACKNOWLEDGED", "TRANSPORT_UNKNOWN"}:
            raise ResourceAuthorityError("invalid Resource transport outcome")
        if state == "NOT_SENT" and adapter_invoked:
            raise ResourceIntegrityError(
                "RELEASED_NOT_SENT requires durable proof that the adapter was not invoked"
            )
        with self.store.transaction() as db:
            reservation = _row(
                db,
                "SELECT * FROM resource_reservations WHERE reservation_id=?",
                (prepared.reservation_id,),
            )
            if reservation is None:
                raise ResourceAuthorityError("Resource reservation disappeared")
            transport = _row(
                db,
                "SELECT * FROM resource_transport_facts WHERE reservation_id=?",
                (prepared.reservation_id,),
            )
            if transport is None:
                raise ResourceIntegrityError("transport outcome has no durable intent")
            result_payload = _canonical(result)
            outcome_payload = {
                "transport_fact_id": transport["transport_fact_id"],
                "reservation_id": reservation["reservation_id"],
                "occurrence_id": reservation["occurrence_id"],
                "attempt_id": reservation["attempt_id"],
                "account_id": reservation["account_id"],
                "server_id": reservation["server_id"],
                "runtime_invocation_id": reservation["runtime_invocation_id"],
                "state": state,
                "adapter_invoked": bool(adapter_invoked),
                "result": result_payload,
            }
            outcome_id = _id("transport-outcome:v1", outcome_payload)
            outcome_digest = _digest(result_payload)
            outcome_content_digest = _digest(outcome_payload)
            _immutable_insert(
                db,
                table="resource_transport_outcomes",
                id_column="outcome_id",
                object_id=outcome_id,
                columns=(
                    "outcome_id", "transport_fact_id", "reservation_id",
                    "occurrence_id", "attempt_id", "account_id", "server_id",
                    "runtime_invocation_id", "state", "adapter_invoked",
                    "result_json", "result_digest", "recorded_at",
                    "content_digest", "payload_json",
                ),
                values=(
                    outcome_id, transport["transport_fact_id"],
                    reservation["reservation_id"], reservation["occurrence_id"],
                    reservation["attempt_id"], reservation["account_id"],
                    reservation["server_id"], reservation["runtime_invocation_id"],
                    state, int(bool(adapter_invoked)), _json(result_payload),
                    outcome_digest, now, outcome_content_digest, _json(outcome_payload),
                ),
                payload=outcome_payload,
                digest=outcome_content_digest,
            )
            if reservation["state"] not in {"DISPATCHING", "UNRESOLVED"}:
                if reservation["state"] == "RELEASED_NOT_SENT" and state == "NOT_SENT":
                    return
                raise ResourceFenceError("Resource reservation is not awaiting transport outcome")
            next_state = {
                "NOT_SENT": "RELEASED_NOT_SENT",
                "SENT_ACKNOWLEDGED": "SENT_ACKNOWLEDGED",
                "TRANSPORT_UNKNOWN": "TRANSPORT_UNKNOWN",
            }[state]
            revision = int(reservation["state_revision"])
            next_revision = revision + 1
            changed = db.execute(
                """UPDATE resource_reservations
                   SET state=?,state_revision=?,updated_at=?
                   WHERE reservation_id=? AND state=? AND state_revision=?""",
                (
                    next_state,
                    next_revision,
                    now,
                    prepared.reservation_id,
                    reservation["state"],
                    revision,
                ),
            ).rowcount
            if changed != 1:
                raise ResourceFenceError("Resource transport outcome compare-and-swap failed")
            self._append_closure(
                db,
                reservation=reservation,
                closure_kind=(
                    "RELEASED_NOT_SENT"
                    if next_state == "RELEASED_NOT_SENT"
                    else "UNRESOLVED"
                ),
                reason="transport_outcome",
                payload={
                    "transport_state": state,
                    "adapter_invoked": adapter_invoked,
                    "result": result,
                },
            )
            self._append_transition(
                db,
                entity_type="reservation",
                entity_id=prepared.reservation_id,
                state_from=reservation["state"],
                state_to=next_state,
                state_revision=next_revision,
                recorded_at=now,
                payload={"result": result, "adapter_invoked": adapter_invoked},
            )
        if state == "TRANSPORT_UNKNOWN":
            self._ensure_live_unresolved_block(
                prepared.context,
                reason="resource_transport_unknown",
                now=now,
            )
        try:
            if state == "SENT_ACKNOWLEDGED":
                self.store.mark_input_sent(prepared.action_id, now, result)
            elif state == "NOT_SENT":
                self.store.mark_cancelled(prepared.action_id, now, "transport_conclusively_not_dispatched")
            else:
                self.store.mark_unresolved(prepared.action_id, now, "ambiguous_resource_transport", result)
        except BaseException as exc:
            if state != "NOT_SENT":
                try:
                    self.store.mark_unresolved(
                        prepared.action_id,
                        now,
                        "resource_transport_persistence_failure",
                        {"exception_type": type(exc).__name__},
                    )
                except BaseException:
                    pass
            raise

    def _ensure_live_unresolved_block(
        self,
        context: ResourceAuthorizationContext,
        *,
        reason: str,
        now: float,
    ) -> dict[str, Any]:
        scope_key = f"occurrence:{context.occurrence_key}|{RESOURCE_OBJECTIVE_ACTION_ID}"
        payload = {
            "scope_key": scope_key,
            "account_id": context.account_id,
            "server_id": context.server_id,
            "reset_identity_id": context.reset_identity_id,
            "occurrence_key": context.occurrence_key,
            "objective_action_id": RESOURCE_OBJECTIVE_ACTION_ID,
            "reason": reason,
        }
        block_id = _id("block:v1", payload)
        digest = _digest(payload)
        with self.store.transaction() as db:
            _immutable_insert(
                db,
                table="resource_effect_block_facts",
                id_column="block_id",
                object_id=block_id,
                columns=(
                    "block_id",
                    "scope_key",
                    "account_id",
                    "server_id",
                    "reset_identity_id",
                    "occurrence_key",
                    "block_reason",
                    "active",
                    "content_digest",
                    "payload_json",
                ),
                values=(
                    block_id,
                    scope_key,
                    context.account_id,
                    context.server_id,
                    context.reset_identity_id,
                    context.occurrence_key,
                    reason,
                    1,
                    digest,
                    _json(payload),
                ),
                payload=payload,
                digest=digest,
            )
            if _row(
                db,
                "SELECT * FROM resource_effect_block_projection WHERE block_id=?",
                (block_id,),
            ) is None:
                db.execute(
                    """INSERT INTO resource_effect_block_projection(
                        block_id,scope_key,projection_state,current_reset_id,
                        source_resolution_id,state_revision,updated_at
                    ) VALUES(?,?,?,?,?,?,?)""",
                    (block_id, scope_key, "ACTIVE", context.reset_identity_id, None, 0, now),
                )
                self._append_transition(
                    db,
                    entity_type="block",
                    entity_id=block_id,
                    state_from=None,
                    state_to="ACTIVE",
                    state_revision=0,
                    recorded_at=now,
                    payload=payload,
                )
        return _row(
            self.store.connection,
            "SELECT * FROM resource_effect_block_facts WHERE block_id=?",
            (block_id,),
        ) or {}

    def dispatch_prepared_resource_item_use(
        self,
        prepared: PreparedResourceEffect,
        *,
        controller_lease: Mapping[str, Any],
        runtime_lock: Any,
        capability: Any,
        request: Any,
        policy: Any,
        adapter: Callable[[ResourceTransportIntentToken], Any],
        now: float,
    ) -> Any:
        """Run the exact lock → intent → capability → adapter → outcome sequence."""

        if not callable(adapter):
            raise ResourceAuthorityError("Resource adapter callable is required")
        assert_held = getattr(runtime_lock, "assert_held", None)
        if not callable(assert_held):
            raise ResourceFenceError("same-live-connection RuntimeInputLock assertion is required")
        owner = str(controller_lease.get("owner_id") or "")
        invocation_id = prepared.fence.runtime_invocation_id
        assert_held(owner, invocation_id)
        token = self.record_resource_transport_intent(
            prepared,
            controller_lease=controller_lease,
            runtime_lock=runtime_lock,
            capability=capability,
            request=request,
            policy=policy,
            now=now,
        )
        consume = getattr(policy, "consume_capability", None)
        if not callable(consume):
            self._finish_resource_transport(
                prepared,
                state="TRANSPORT_UNKNOWN",
                result={"reason": "capability_consumer_missing"},
                now=now,
                adapter_invoked=False,
            )
            raise ResourceFenceError("policy capability consumer is required")
        try:
            consumed: CapabilityConsumeResult = consume(capability, request)
        except BaseException as exc:
            self._finish_resource_transport(
                prepared,
                state="TRANSPORT_UNKNOWN",
                result={
                    "reason": "capability_consumption_failed",
                    "exception_type": type(exc).__name__,
                },
                now=now,
                adapter_invoked=False,
            )
            raise
        if not consumed.allow_dispatch:
            self._finish_resource_transport(
                prepared,
                state="TRANSPORT_UNKNOWN",
                result={"reason": consumed.reason_code},
                now=now,
                adapter_invoked=False,
            )
            raise ResourceFenceError("capability was not consumable after durable intent")
        self.consume_transport_intent(
            token,
            reservation_id=prepared.reservation_id,
            runtime_invocation_id=invocation_id,
        )
        assert_held(owner, invocation_id)
        try:
            result = adapter(token)
        except BaseException as exc:
            self._finish_resource_transport(
                prepared,
                state="TRANSPORT_UNKNOWN",
                result={"exception_type": type(exc).__name__},
                now=now,
                adapter_invoked=True,
            )
            raise
        dispatched = (
            result.dispatched
            if isinstance(result, TransportResult)
            else result is not False
        )
        self._finish_resource_transport(
            prepared,
            state="SENT_ACKNOWLEDGED"
            if dispatched
            else "TRANSPORT_UNKNOWN",
            result=result,
            now=now,
            adapter_invoked=True,
        )
        return result

    def _insert_live_effect(
        self,
        db: sqlite3.Connection,
        *,
        reservation: Mapping[str, Any],
        transport_fact_id: str,
        effect_state: str,
        evidence: Mapping[str, Any],
        now: float,
    ) -> str:
        if effect_state not in {"CONFIRMED", "NO_EFFECT", "UNRESOLVED"}:
            raise ResourceAuthorityError("invalid live Resource effect state")
        payload = {
            "reservation_id": reservation["reservation_id"],
            "transport_fact_id": transport_fact_id,
            "occurrence_id": reservation["occurrence_id"],
            "attempt_id": reservation["attempt_id"],
            "authorization_context_digest": reservation["authorization_context_digest"],
            "account_id": reservation["account_id"],
            "server_id": reservation["server_id"],
            "effect_ordinal": int(reservation["effect_ordinal"]),
            "effect_state": effect_state,
            "proven_no_effect": (
                evidence.get("proven_no_effect") is True
                if effect_state == "NO_EFFECT"
                else None
            ),
            "before_owned_quantity": evidence.get("before_owned_quantity"),
            "after_owned_quantity": evidence.get("after_owned_quantity"),
            "evidence_refs": tuple(evidence.get("evidence_refs", ())),
        }
        effect_id = _id("live-effect:v1", payload)
        digest = _digest(payload)
        _immutable_insert(
            db,
            table="resource_live_effects",
            id_column="live_effect_id",
            object_id=effect_id,
            columns=(
                "live_effect_id",
                "reservation_id",
                "transport_fact_id",
                "occurrence_id",
                "attempt_id",
                "account_id",
                "server_id",
                "effect_ordinal",
                "effect_state",
                "before_owned_quantity",
                "after_owned_quantity",
                "evidence_refs_json",
                "created_at",
                "content_digest",
                "payload_json",
            ),
            values=(
                effect_id,
                reservation["reservation_id"],
                transport_fact_id,
                reservation["occurrence_id"],
                reservation["attempt_id"],
                reservation["account_id"],
                reservation["server_id"],
                int(reservation["effect_ordinal"]),
                effect_state,
                evidence.get("before_owned_quantity"),
                evidence.get("after_owned_quantity"),
                _json(tuple(evidence.get("evidence_refs", ()))),
                now,
                digest,
                _json(payload),
            ),
            payload=payload,
            digest=digest,
        )
        assertion_payload = {
            "effect_kind": "live",
            "effect_id": effect_id,
            "assertion_state": "BOUND",
            "account_id": reservation["account_id"],
            "server_id": reservation["server_id"],
            "reset_identity_id": reservation["reset_identity_id"],
            "evidence_refs": tuple(evidence.get("evidence_refs", ())),
            "unknown_fields": (),
        }
        assertion_id = _id("reset-assertion:v1", assertion_payload)
        assertion_digest = _digest(assertion_payload)
        _immutable_insert(
            db,
            table="resource_reset_binding_assertions",
            id_column="assertion_id",
            object_id=assertion_id,
            columns=(
                "assertion_id",
                "effect_kind",
                "effect_id",
                "account_id",
                "server_id",
                "reset_identity_id",
                "assertion_state",
                "evidence_refs_json",
                "unknown_fields_json",
                "content_digest",
                "payload_json",
            ),
            values=(
                assertion_id,
                "live",
                effect_id,
                reservation["account_id"],
                reservation["server_id"],
                reservation["reset_identity_id"],
                "BOUND",
                _json(assertion_payload["evidence_refs"]),
                "[]",
                assertion_digest,
                _json(assertion_payload),
            ),
            payload=assertion_payload,
            digest=assertion_digest,
        )
        if _row(
            db,
            """SELECT * FROM resource_reset_binding_projection
               WHERE effect_kind='live' AND effect_id=?""",
            (effect_id,),
        ) is None:
            db.execute(
                """INSERT INTO resource_reset_binding_projection(
                    effect_kind,effect_id,assertion_id,account_id,server_id,
                    reset_identity_id,projection_state,state_revision,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    "live",
                    effect_id,
                    assertion_id,
                    reservation["account_id"],
                    reservation["server_id"],
                    reservation["reset_identity_id"],
                    "BOUND",
                    0,
                    now,
                ),
            )
            self._append_transition(
                db,
                entity_type="reset_binding",
                entity_id=f"live:{effect_id}",
                state_from=None,
                state_to="BOUND",
                state_revision=0,
                recorded_at=now,
                payload=assertion_payload,
            )
        return effect_id

    def _cas_attempt_in_transaction(
        self,
        db: sqlite3.Connection,
        *,
        attempt_id: str,
        next_state: str,
        now: float,
        reason: str,
    ) -> None:
        current = _row(
            db,
            "SELECT * FROM resource_attempts WHERE attempt_id=?",
            (attempt_id,),
        )
        if current is None:
            raise ResourceAuthorityError("unknown Resource attempt")
        if current["state"] == next_state:
            return
        revision = int(current["state_revision"])
        changed = db.execute(
            """UPDATE resource_attempts
               SET state=?,state_revision=?,updated_at=?
               WHERE attempt_id=? AND state=? AND state_revision=?""",
            (
                next_state,
                revision + 1,
                now,
                attempt_id,
                current["state"],
                revision,
            ),
        ).rowcount
        if changed != 1:
            raise ResourceFenceError("attempt compare-and-swap failed during reconciliation")
        self._append_transition(
            db,
            entity_type="attempt",
            entity_id=attempt_id,
            state_from=current["state"],
            state_to=next_state,
            state_revision=revision + 1,
            recorded_at=now,
            payload={"reason": reason},
        )

    def _release_reconciled_reservation_claims(
        self,
        db: sqlite3.Connection,
        *,
        reservation: Mapping[str, Any],
        effect_state: str,
        now: float,
    ) -> None:
        """Release every still-authorizing claim for one reconciled reservation."""

        normalized = str(effect_state).upper()
        if normalized not in {"CONFIRMED", "NO_EFFECT", "UNRESOLVED"}:
            raise ResourceIntegrityError("reconciled claim release effect state is invalid")
        claims = db.execute(
            """SELECT * FROM resource_attempt_claims
               WHERE reservation_id=? ORDER BY claim_id""",
            (reservation["reservation_id"],),
        ).fetchall()
        payload_base = {
            "reason": "observe_only_effect_reconciled",
            "effect_state": normalized,
            "reservation_id": reservation["reservation_id"],
            "occurrence_id": reservation["occurrence_id"],
        }
        for claim_row in claims:
            claim = dict(claim_row)
            state = str(claim["state"])
            if state in {"RELEASED", "EXPIRED"}:
                continue
            if state not in {"ACTIVE", "RECONCILIATION_ONLY"}:
                raise ResourceIntegrityError(
                    "Resource reservation claim has an unsupported terminalization state"
                )
            if (
                claim["occurrence_id"] != reservation["occurrence_id"]
                or claim["reservation_id"] != reservation["reservation_id"]
            ):
                raise ResourceIntegrityError(
                    "Resource reservation claim binding is inconsistent"
                )
            changed = db.execute(
                """UPDATE resource_attempt_claims
                   SET state='RELEASED'
                   WHERE claim_id=? AND attempt_id=? AND occurrence_id=?
                     AND reservation_id=? AND state=?""",
                (
                    claim["claim_id"],
                    claim["attempt_id"],
                    reservation["occurrence_id"],
                    reservation["reservation_id"],
                    state,
                ),
            ).rowcount
            if changed != 1:
                raise ResourceFenceError(
                    "reconciled Resource claim release compare-and-swap failed"
                )
            self._append_transition(
                db,
                entity_type="claim",
                entity_id=claim["claim_id"],
                state_from=state,
                state_to="RELEASED",
                state_revision=int(claim["claim_epoch"]),
                recorded_at=now,
                payload={
                    **payload_base,
                    "claim_id": claim["claim_id"],
                    "attempt_id": claim["attempt_id"],
                },
            )

    def reconcile_resource_effect_observe_only(
        self,
        reservation_id: str,
        evidence: Mapping[str, Any],
        now: float = 0.0,
    ) -> dict[str, Any]:
        """Append evidence only; this method has no transport callable."""

        if not isinstance(evidence, Mapping):
            raise ResourceAuthorityError("observe-only evidence must be a mapping")
        reservation = self._reservation(reservation_id)
        transport = _row(
            self.store.connection,
            "SELECT * FROM resource_transport_facts WHERE reservation_id=?",
            (reservation_id,),
        )
        if transport is None:
            raise ResourceAuthorityError("observe-only reconciliation requires a durable transport fact")
        outcome = _row(
            self.store.connection,
            "SELECT * FROM resource_transport_outcomes WHERE reservation_id=?",
            (reservation_id,),
        )
        if outcome is None:
            raise ResourceAuthorityError(
                "observe-only reconciliation requires a durable transport outcome"
            )
        requested = str(evidence.get("effect_state") or evidence.get("state") or "UNRESOLVED").upper()
        state = {
            "EFFECT_CONFIRMED": "CONFIRMED",
            "CONFIRMED": "CONFIRMED",
            "NO_EFFECT_CONFIRMED": "NO_EFFECT",
            "NO_EFFECT": "NO_EFFECT",
            "UNRESOLVED": "UNRESOLVED",
            "UNKNOWN": "UNRESOLVED",
        }.get(requested)
        if state is None:
            raise ResourceAuthorityError("observe-only effect state is invalid")
        with self.store.transaction() as db:
            current = _row(
                db,
                "SELECT * FROM resource_reservations WHERE reservation_id=?",
                (reservation_id,),
            )
            if current is None:
                raise ResourceAuthorityError("Resource reservation disappeared")
            prior = current["state"]
            if prior in {"EFFECT_CONFIRMED", "NO_EFFECT_CONFIRMED"}:
                existing = _row(
                    db,
                    """SELECT * FROM resource_live_effects
                       WHERE reservation_id=?""",
                    (reservation_id,),
                )
                if existing is None:
                    raise ResourceIntegrityError(
                        "terminal Resource reservation has no immutable live effect"
                    )
                self._release_reconciled_reservation_claims(
                    db,
                    reservation=current,
                    effect_state=str(existing["effect_state"]),
                    now=now,
                )
                self._terminalize_linked_action(
                    db,
                    reservation=current,
                    effect_state=str(existing["effect_state"]),
                    evidence=evidence,
                    now=now,
                )
                return existing or current
            revision = int(current["state_revision"])
            if prior != "RECONCILING":
                changed = db.execute(
                    """UPDATE resource_reservations
                       SET state='RECONCILING',state_revision=?,updated_at=?
                       WHERE reservation_id=? AND state=? AND state_revision=?""",
                    (revision + 1, now, reservation_id, prior, revision),
                ).rowcount
                if changed != 1:
                    raise ResourceFenceError("observe-only reconciliation compare-and-swap failed")
                self._append_transition(
                    db,
                    entity_type="reservation",
                    entity_id=reservation_id,
                    state_from=prior,
                    state_to="RECONCILING",
                    state_revision=revision + 1,
                    recorded_at=now,
                    payload={"observe_only": True},
                )
                current = _row(
                    db,
                    "SELECT * FROM resource_reservations WHERE reservation_id=?",
                    (reservation_id,),
                ) or current
            if state == "UNRESOLVED":
                self._append_closure(
                    db,
                    reservation=current,
                    closure_kind="UNRESOLVED",
                    reason="observe_only_unknown",
                    payload=dict(evidence),
                )
                revision = int(current["state_revision"])
                changed = db.execute(
                    """UPDATE resource_reservations
                       SET state='UNRESOLVED',state_revision=?,updated_at=?
                       WHERE reservation_id=? AND state='RECONCILING' AND state_revision=?""",
                    (revision + 1, now, reservation_id, revision),
                ).rowcount
                if changed != 1:
                    raise ResourceFenceError("observe-only unresolved compare-and-swap failed")
                self._append_transition(
                    db,
                    entity_type="reservation",
                    entity_id=reservation_id,
                    state_from="RECONCILING",
                    state_to="UNRESOLVED",
                    state_revision=revision + 1,
                    recorded_at=now,
                    payload={"observe_only": True, "unknown": True},
                )
                self._release_reconciled_reservation_claims(
                    db,
                    reservation=current,
                    effect_state="UNRESOLVED",
                    now=now,
                )
                self._terminalize_linked_action(
                    db,
                    reservation=current,
                    effect_state="UNRESOLVED",
                    evidence=evidence,
                    now=now,
                )
                return _row(
                    db,
                    "SELECT * FROM resource_reservations WHERE reservation_id=?",
                    (reservation_id,),
                ) or current
            if state == "NO_EFFECT" and evidence.get("proven_no_effect") is not True:
                raise ResourceAuthorizationDenied(
                    "NO_EFFECT_CONFIRMED requires durable explicit no-effect evidence"
                )
            effect_id = self._insert_live_effect(
                db,
                reservation=current,
                transport_fact_id=transport["transport_fact_id"],
                effect_state=state,
                evidence=evidence,
                now=now,
            )
            next_state = "EFFECT_CONFIRMED" if state == "CONFIRMED" else "NO_EFFECT_CONFIRMED"
            revision = int(current["state_revision"])
            next_revision = revision + 1
            changed = db.execute(
                """UPDATE resource_reservations
                   SET state=?,state_revision=?,updated_at=?
                   WHERE reservation_id=? AND state='RECONCILING' AND state_revision=?""",
                (next_state, next_revision, now, reservation_id, revision),
            ).rowcount
            if changed != 1:
                raise ResourceFenceError("observe-only terminal compare-and-swap failed")
            self._append_closure(
                db,
                reservation=current,
                closure_kind=next_state,
                reason="observe_only_effect_reconciled",
                payload={"live_effect_id": effect_id, "evidence": dict(evidence)},
            )
            self._append_transition(
                db,
                entity_type="reservation",
                entity_id=reservation_id,
                state_from="RECONCILING",
                state_to=next_state,
                state_revision=next_revision,
                recorded_at=now,
                payload={"live_effect_id": effect_id, "observe_only": True},
            )
            occurrence_state = "COMPLETED" if state == "CONFIRMED" else "NO_EFFECT"
            occurrence = _row(
                db,
                "SELECT * FROM resource_occurrences WHERE occurrence_id=?",
                (current["occurrence_id"],),
            )
            if occurrence is not None and occurrence["state"] in {"RESERVED", "UNRESOLVED", "NO_EFFECT"}:
                self._cas_occurrence(
                    db,
                    occurrence_id=current["occurrence_id"],
                    expected_states={occurrence["state"]},
                    next_state=occurrence_state,
                    now=now,
                    reason="observe_only_effect_reconciled",
                )
            self._cas_attempt_in_transaction(
                db,
                attempt_id=current["attempt_id"],
                next_state="COMPLETED" if state == "CONFIRMED" else "NO_EFFECT",
                now=now,
                reason="observe_only_effect_reconciled",
            )
            self._release_reconciled_reservation_claims(
                db,
                reservation=current,
                effect_state=state,
                now=now,
            )
            self._terminalize_linked_action(
                db,
                reservation=current,
                effect_state=state,
                evidence=evidence,
                now=now,
            )
            return _row(
                db,
                "SELECT * FROM resource_reservations WHERE reservation_id=?",
                (reservation_id,),
            ) or {}

    def _terminalize_linked_action(
        self,
        db: sqlite3.Connection,
        *,
        reservation: Mapping[str, Any],
        effect_state: str,
        evidence: Mapping[str, Any],
        now: float,
    ) -> None:
        """Close the generic action in the same transaction as Resource reconciliation."""

        normalized = str(effect_state).upper()
        target = {
            "CONFIRMED": ("confirmed", "positive_postcondition"),
            "NO_EFFECT": ("cancelled", "proven_no_effect_resource_reconciliation"),
            "UNRESOLVED": ("unresolved", "ambiguous_resource_effect"),
        }.get(normalized)
        if target is None:
            raise ResourceIntegrityError("linked action effect state is invalid")
        target_status, reason = target
        action = _row(
            db,
            "SELECT * FROM actions WHERE action_id=?",
            (reservation["action_id"],),
        )
        if action is None:
            raise ResourceIntegrityError("Resource reservation has no linked action")
        prior = str(action["final_status"])
        if prior == target_status:
            return
        permitted_prior = {
            "confirmed": {"input_sent", "unresolved"},
            "cancelled": {"input_sent", "unresolved"},
            "unresolved": {"input_sent"},
        }[target_status]
        if prior not in permitted_prior:
            raise ResourceIntegrityError(
                "linked Resource action terminal state conflicts with effect reconciliation"
            )
        reconciliation = {
            "confirmed": normalized == "CONFIRMED",
            "effect_state": normalized,
            "reservation_id": reservation["reservation_id"],
            "occurrence_id": reservation["occurrence_id"],
            "evidence_refs": tuple(evidence.get("evidence_refs", ())),
        }
        if normalized == "NO_EFFECT":
            reconciliation["proven_no_effect"] = True
        if db.execute(
            """UPDATE actions
               SET final_status=?,final_reason=?,reconciliation_result_json=?,updated_at=?
               WHERE action_id=? AND final_status=?""",
            (
                target_status,
                reason,
                _json(reconciliation),
                now,
                reservation["action_id"],
                prior,
            ),
        ).rowcount != 1:
            raise ResourceFenceError("linked Resource action compare-and-swap failed")
        self.store._insert_audit(
            db,
            action["task_id"],
            "action_transition",
            now,
            {"reason": reason, "fields": reconciliation},
            reservation["action_id"],
            prior,
            target_status,
        )

    def terminal_observation(
        self,
        observation: TerminalObservation | Mapping[str, Any],
        *,
        now: float = 0.0,
        expected_projection_revision: int | None = None,
    ) -> dict[str, Any]:
        if isinstance(observation, TerminalObservation):
            value = observation
        elif isinstance(observation, Mapping):
            value = TerminalObservation(
                occurrence_id=observation.get("occurrence_id"),
                terminal_state=observation.get("terminal_state", observation.get("state")),
                frame_sha256=observation.get("frame_sha256"),
                evidence_refs=tuple(observation.get("evidence_refs", ())),
                observation_id=observation.get("observation_id"),
            )
        else:
            raise ResourceAuthorityError("terminal observation must be typed")
        _text(value.occurrence_id, "occurrence_id")
        if value.terminal_state not in {"HOME_CANONICAL", "HOME_READY", "UNKNOWN", "MANUAL_REQUIRED"}:
            raise ResourceAuthorityError("terminal observation state is invalid")
        if value.frame_sha256 is not None:
            _sha(value.frame_sha256, "frame_sha256")
        payload = {
            "occurrence_id": value.occurrence_id,
            "terminal_state": value.terminal_state,
            "frame_sha256": value.frame_sha256,
            "evidence_refs": _field_refs(value.evidence_refs, "evidence_refs")
            if value.evidence_refs
            else (),
        }
        observation_id = value.observation_id or _id("terminal-observation:v1", payload)
        digest = _digest(payload)
        with self.store.transaction() as db:
            _immutable_insert(
                db,
                table="resource_terminal_observations",
                id_column="observation_id",
                object_id=observation_id,
                columns=(
                    "observation_id",
                    "occurrence_id",
                    "terminal_state",
                    "frame_sha256",
                    "evidence_refs_json",
                    "content_digest",
                    "payload_json",
                ),
                values=(
                    observation_id,
                    value.occurrence_id,
                    value.terminal_state,
                    value.frame_sha256,
                    _json(payload["evidence_refs"]),
                    digest,
                    _json(payload),
                ),
                payload=payload,
                digest=digest,
            )
            projection = _row(
                db,
                "SELECT * FROM resource_terminal_projection WHERE occurrence_id=?",
                (value.occurrence_id,),
            )
            if projection is None:
                db.execute(
                    """INSERT INTO resource_terminal_projection(
                        occurrence_id,observation_id,terminal_state,state_revision,updated_at
                    ) VALUES(?,?,?,?,?)""",
                    (value.occurrence_id, observation_id, value.terminal_state, 0, now),
                )
                self._append_transition(
                    db,
                    entity_type="terminal",
                    entity_id=value.occurrence_id,
                    state_from=None,
                    state_to=value.terminal_state,
                    state_revision=0,
                    recorded_at=now,
                    payload=payload,
                )
            else:
                revision = int(projection["state_revision"])
                if expected_projection_revision is not None and revision != expected_projection_revision:
                    raise ResourceFenceError("terminal projection revision is stale")
                if (
                    projection["observation_id"] == observation_id
                    and projection["terminal_state"] == value.terminal_state
                ):
                    return projection
                next_revision = revision + 1
                changed = db.execute(
                    """UPDATE resource_terminal_projection
                       SET observation_id=?,terminal_state=?,state_revision=?,updated_at=?
                       WHERE occurrence_id=? AND state_revision=?""",
                    (
                        observation_id,
                        value.terminal_state,
                        next_revision,
                        now,
                        value.occurrence_id,
                        revision,
                    ),
                ).rowcount
                if changed != 1:
                    raise ResourceFenceError("terminal projection compare-and-swap failed")
                self._append_transition(
                    db,
                    entity_type="terminal",
                    entity_id=value.occurrence_id,
                    state_from=projection["terminal_state"],
                    state_to=value.terminal_state,
                    state_revision=next_revision,
                    recorded_at=now,
                    payload=payload,
                )
        return _row(
            self.store.connection,
            "SELECT * FROM resource_terminal_projection WHERE occurrence_id=?",
            (value.occurrence_id,),
        ) or {}

    append_terminal_observation = terminal_observation

    def get_resource_transport(self, reservation_id: str) -> Optional[dict[str, Any]]:
        return _row(
            self.store.connection,
            "SELECT * FROM resource_transport_facts WHERE reservation_id=?",
            (reservation_id,),
        )

    def get_resource_transport_outcome(
        self, reservation_id: str
    ) -> Optional[dict[str, Any]]:
        return _row(
            self.store.connection,
            "SELECT * FROM resource_transport_outcomes WHERE reservation_id=?",
            (reservation_id,),
        )


class ResourceEffectReconciler:
    """Observe-only facade; deliberately exposes no adapter/transport callable."""

    def __init__(
        self,
        authority: ResourceEffectAuthority,
        capture: Callable[..., Any] | None = None,
        evidence_reader: Callable[..., Mapping[str, Any]] | None = None,
    ) -> None:
        self.authority = authority
        self.capture = capture
        self.evidence_reader = evidence_reader

    def reconcile(self, reservation_id: str, evidence: Mapping[str, Any], now: float = 0.0) -> dict[str, Any]:
        return self.authority.reconcile_resource_effect_observe_only(reservation_id, evidence, now)

    reconcile_resource_effect_observe_only = reconcile


def occurrence_key(identity: ResourceOccurrenceIdentity | Mapping[str, Any]) -> str:
    return ResourceEffectAuthority._identity(identity).occurrence_key()


def canonical_resource_identity(identity: ResourceOccurrenceIdentity | Mapping[str, Any]) -> str:
    return ResourceEffectAuthority._identity(identity).canonical_identity()


def resource_reservation_id(
    context: ResourceAuthorizationContext,
    authorization_generation: int,
) -> str:
    return ResourceEffectAuthority.resource_reservation_id(context, authorization_generation)


def import_historical_resource_transport(
    authority: ResourceEffectAuthority,
    fact: HistoricalResourceTransportFact | Mapping[str, Any],
) -> dict[str, Any]:
    return authority.import_historical_resource_transport(fact)


def import_historical_resource_effect(
    authority: ResourceEffectAuthority,
    effect: HistoricalResourceEffect | Mapping[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    return authority.import_historical_resource_effect(effect, **kwargs)


def import_historical_sessions(
    authority: ResourceEffectAuthority,
    fixture_path: str | Path,
    **kwargs: Any,
) -> dict[str, list[dict[str, Any]]]:
    return authority.import_historical_sessions(fixture_path, **kwargs)


def append_reset_binding_assertion(
    authority: ResourceEffectAuthority,
    assertion: ResetBindingAssertion | Mapping[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    return authority.append_reset_binding_assertion(assertion, **kwargs)


def append_policy_classification(
    authority: ResourceEffectAuthority,
    classification: HistoricalPolicyClassification | Mapping[str, Any],
) -> dict[str, Any]:
    return authority.append_policy_classification(classification)


def create_resource_occurrence(
    authority: ResourceEffectAuthority,
    identity: ResourceOccurrenceIdentity | Mapping[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    return authority.create_resource_occurrence(identity, **kwargs)


def claim_resource_attempt(
    authority: ResourceEffectAuthority,
    occurrence_id: str,
    owner: str,
    expected_revision: int | None = None,
    **kwargs: Any,
) -> ResourceAttemptClaim:
    return authority.claim_resource_attempt(occurrence_id, owner, expected_revision, **kwargs)


def append_terminal_observation(
    authority: ResourceEffectAuthority,
    observation: TerminalObservation | Mapping[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    return authority.append_terminal_observation(observation, **kwargs)


def has_scoped_resource_block(
    authority: ResourceEffectAuthority,
    block_keys: Mapping[str, Any] | Sequence[str] = (),
) -> bool:
    return authority.has_scoped_resource_block(block_keys)


def append_historical_block_resolution(
    authority: ResourceEffectAuthority,
    resolution: ResourceBlockResolution | Mapping[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    return authority.append_historical_block_resolution(resolution, **kwargs)


def get_resource_transport_outcome(
    authority: ResourceEffectAuthority, reservation_id: str
) -> Optional[dict[str, Any]]:
    return authority.get_resource_transport_outcome(reservation_id)


__all__ = [
    "RESOURCE_FLOW_ID",
    "RESOURCE_RECURRENCE_CLASS",
    "RESOURCE_OBJECTIVE_ACTION_ID",
    "RESOURCE_TARGET_VARIANT",
    "RESOURCE_EFFECT_ORDINAL",
    "RESOURCE_QUANTITY",
    "RESOURCE_PRODUCT_POLICY_REVISION",
    "RESOURCE_RECURRENCE_POLICY_REVISION",
    "ResourceAuthorityError",
    "ResourceIntegrityError",
    "ResourceAuthorizationDenied",
    "ResourceFenceError",
    "ResourceResetIdentity",
    "ResourceOccurrenceIdentity",
    "ResourceAttemptClaim",
    "ClaimLease",
    "ResourceReservationSpec",
    "PreparedResourceEffect",
    "PreparedResourceAuthorization",
    "HistoricalResourceTransportFact",
    "HistoricalResourceEffect",
    "HistoricalPolicyClassification",
    "ResetBindingAssertion",
    "TerminalObservation",
    "ResourceBlockResolution",
    "ResourceTransportIntentToken",
    "ResourceEffectAuthority",
    "ResourceEffectReconciler",
    "occurrence_key",
    "canonical_resource_identity",
    "resource_reservation_id",
    "import_historical_resource_transport",
    "import_historical_resource_effect",
    "import_historical_sessions",
    "append_reset_binding_assertion",
    "append_policy_classification",
    "create_resource_occurrence",
    "claim_resource_attempt",
    "append_terminal_observation",
    "has_scoped_resource_block",
    "append_historical_block_resolution",
    "get_resource_transport_outcome",
]
