"""Canonical, observe-only authorization support for the direct 1K Food route."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Callable, Mapping

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import CapturedNativeFrame, LocalBlueStacksRuntime, NativeBox
from scripts.daily_resource_item_bluestacks import (
    ITEM_USE_ACTION_KEY,
    USE_TARGET_IDENTITY,
    _recognize_home,
    _resource_delta_verified,
    recognize_food_item_in_resources,
    resource_item_authorizeable,
)
from scripts.evidence_hygiene import sha256_stream


RESOURCE_AUTHORIZATION_SAFETY_MARGIN_SECONDS = 2.0
RESOURCE_AUTHORIZATION_FRESHNESS_SECONDS = 600.0
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ResourceItemAuthorizationError(RuntimeError):
    """Resource identity, authorization, or existing-store admission failed."""


class ResourceAuthorizationWindowError(ResourceItemAuthorizationError):
    """The Resource authorization window is no longer current."""


def _normalize_resource_wall_clock(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ResourceAuthorizationWindowError(
            "Resource authorization wall clock must return a datetime"
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise ResourceAuthorizationWindowError(
            "Resource authorization wall clock must be timezone-aware UTC"
        )
    try:
        return value.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResourceAuthorizationWindowError(
            "Resource authorization wall clock must be timezone-aware UTC"
        ) from exc


@dataclass(frozen=True)
class ResourceAuthorizationWindow:
    """Immutable authorization/reset bounds carried to the exact Resource Use seam."""

    reset_deadline_utc: datetime
    authorization_expires_utc: datetime
    safety_margin_seconds: float = RESOURCE_AUTHORIZATION_SAFETY_MARGIN_SECONDS

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "reset_deadline_utc", _normalize_resource_wall_clock(self.reset_deadline_utc)
        )
        object.__setattr__(
            self,
            "authorization_expires_utc",
            _normalize_resource_wall_clock(self.authorization_expires_utc),
        )
        if type(self.safety_margin_seconds) not in {int, float} or not float(self.safety_margin_seconds) > 0.0:
            raise ValueError("Resource authorization safety margin must be positive")

    @property
    def authorization_expiry_utc(self) -> datetime:
        return self.authorization_expires_utc

    @property
    def safety_margin(self) -> timedelta:
        return timedelta(seconds=float(self.safety_margin_seconds))

    @staticmethod
    def sample_current_utc(
        wall_clock: Callable[[], datetime] | None = None,
    ) -> datetime:
        """Sample production UTC time, or a deterministic test clock."""
        value = datetime.now(timezone.utc) if wall_clock is None else wall_clock()
        return _normalize_resource_wall_clock(value)

    def require_current(self, current_utc: datetime) -> datetime:
        """Require strict margin before both authorization and reset bounds."""
        current = _normalize_resource_wall_clock(current_utc)
        if (
            current + self.safety_margin >= self.reset_deadline_utc
            or current + self.safety_margin >= self.authorization_expires_utc
        ):
            raise ResourceAuthorizationWindowError(
                "Resource authorization denied: current UTC is at or inside the "
                "authorization/reset safety margin"
            )
        return current


class AuthorizedResourceItemRuntime:
    """Resource route adapter with a single durable, fenced Use seam."""

    def __init__(
        self,
        inner: LocalBlueStacksRuntime,
        *,
        authority: Any | None = None,
        prepared: Any | None = None,
        controller_lease: Mapping[str, Any] | None = None,
        runtime_lock: Any | None = None,
        capability: Any | None = None,
        policy: Any | None = None,
        request: Any | None = None,
        prepare: Any | None = None,
        now: float | Callable[[], float] = 0.0,
        authorization_window: ResourceAuthorizationWindow | None = None,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._inner = inner
        self._authority = authority
        self._prepared = prepared
        self._controller_lease = controller_lease
        self._runtime_lock = runtime_lock
        self._capability = capability
        self._policy = policy
        self._request = request
        self._prepare = prepare
        self._now = now
        self._authorization_window = authorization_window
        self._wall_clock = wall_clock
        self._preparation_used = False

    @property
    def execute(self) -> bool:
        return self._inner.execute

    @property
    def frame_max_age_seconds(self) -> float:
        return self._inner.frame_max_age_seconds

    @property
    def input_count(self) -> int:
        return self._inner.input_count

    @property
    def action_keys(self) -> set[str]:
        return self._inner.action_keys

    @property
    def frame_actions(self) -> set[tuple[str, str, NativeBox | None]]:
        return self._inner.frame_actions

    @property
    def events(self) -> Path:
        return self._inner.events

    @property
    def prepared_action_key(self) -> str | None:
        return self._prepared.action_key if self._prepared is not None else None

    @property
    def prepared_effect(self) -> Any | None:
        """Expose the immutable reservation only for observe-only reconciliation."""
        return self._prepared

    @property
    def session(self) -> Path:
        return self._inner.session

    def capture(self, label: str) -> CapturedNativeFrame:
        return self._inner.capture(label)

    def tap(self, source: CapturedNativeFrame, **kwargs: Any) -> None:
        if (
            kwargs.get("action_class") == "resource_item_use"
            or kwargs.get("target_identity") == USE_TARGET_IDENTITY
        ):
            raise RuntimeError("generic Resource Use tap is forbidden")
        self._inner.tap(source, **kwargs)

    def tap_navigation(self, source: CapturedNativeFrame, **kwargs: Any) -> None:
        kwargs = dict(kwargs)
        kwargs["action_class"] = "navigation"
        kwargs["consequential"] = False
        self._inner.tap(source, **kwargs)

    def swipe(self, source: CapturedNativeFrame, **kwargs: Any) -> None:
        self._inner.swipe(source, **kwargs)

    def swipe_navigation(self, source: CapturedNativeFrame, **kwargs: Any) -> None:
        self._inner.swipe(source, **kwargs)

    def dispatch_one_food_use(
        self,
        source: CapturedNativeFrame,
        *,
        target_roi: NativeBox,
        action_key: str,
        prepared: Any | None = None,
        request: Any | None = None,
        capability: Any | None = None,
        now: float | None = None,
    ) -> Any:
        authority = self._authority
        prepared_effect = prepared or self._prepared
        controller_lease = self._controller_lease
        runtime_lock = self._runtime_lock
        policy = self._policy
        request_value = request if request is not None else self._request
        capability_value = capability if capability is not None else self._capability
        if prepared_effect is None and callable(self._prepare):
            if self._preparation_used:
                raise RuntimeError("Resource preparation callback is one-shot")
            self._preparation_used = True
            bundle = self._prepare(source, target_roi, action_key)
            from safe_action_core.resource_effect_authority import PreparedResourceAuthorization

            if type(bundle) is not PreparedResourceAuthorization:
                raise RuntimeError("Resource preparation callback returned no typed bundle")
            prepared_effect = bundle.prepared
            request_value = bundle.request
            capability_value = bundle.capability
            self._prepared = prepared_effect
        if prepared_effect is None and self._authorization_window is not None:
            try:
                self._authorization_window.require_current(
                    ResourceAuthorizationWindow.sample_current_utc(self._wall_clock)
                )
            except ResourceAuthorizationWindowError as exc:
                raise RuntimeError(str(exc)) from exc
        if (
            authority is None
            or prepared_effect is None
            or not isinstance(controller_lease, Mapping)
            or runtime_lock is None
            or policy is None
            or request_value is None
            or capability_value is None
        ):
            raise RuntimeError("prepared Resource authority, fence, capability, and lock are required")
        if request_value.resource_authorization_context != prepared_effect.context:
            raise RuntimeError("Resource request context does not match prepared authority")
        if request_value.effect_dispatch_fence != prepared_effect.fence:
            raise RuntimeError("Resource request fence does not match prepared authority")
        if source.sha256 != prepared_effect.fence.immediate_before_sha256:
            raise RuntimeError("actual Resource adapter source frame is not the prepared fence")
        observation = getattr(request_value, "observation", None)
        if (
            observation is None
            or observation.frame_sha256 != source.sha256
            or observation.target_roi != target_roi
        ):
            raise RuntimeError("actual Resource source does not match the request observation")
        if action_key != prepared_effect.action_key and action_key != ITEM_USE_ACTION_KEY:
            raise RuntimeError("Resource action key does not match prepared authority")
        if self._authorization_window is None:
            raise RuntimeError("Resource authorization window is required")
        effective_now = self._now if now is None else now
        if callable(effective_now):
            effective_now = effective_now()
        try:
            self._authorization_window.require_current(
                ResourceAuthorizationWindow.sample_current_utc(self._wall_clock)
            )
        except ResourceAuthorizationWindowError as exc:
            try:
                authority.cancel_prepared_resource_effect(
                    prepared_effect,
                    controller_lease=controller_lease,
                    runtime_lock=runtime_lock,
                    reason="resource_authorization_expired",
                    now=float(effective_now),
                )
            except BaseException as cleanup_exc:
                raise RuntimeError(
                    "Resource authorization denied and pre-intent cancellation failed"
                ) from cleanup_exc
            raise RuntimeError(str(exc)) from exc
        return authority.dispatch_prepared_resource_item_use(
            prepared_effect,
            controller_lease=controller_lease,
            runtime_lock=runtime_lock,
            capability=capability_value,
            request=request_value,
            policy=policy,
            adapter=lambda token: self._inner.dispatch_prepared_resource_item_use(
                source,
                target_identity=USE_TARGET_IDENTITY,
                target_roi=target_roi,
                action_key=prepared_effect.action_key,
                transport_intent_token=token,
            ),
            now=float(effective_now),
        )


def resource_identity_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ResourceItemAuthorizationError(f"{label} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ResourceItemAuthorizationError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise ResourceItemAuthorizationError(f"{label} must be UTC")
    parsed = parsed.astimezone(timezone.utc)
    canonical = parsed.isoformat().replace("+00:00", "Z")
    if value != canonical:
        raise ResourceItemAuthorizationError(f"{label} is not an exact UTC timestamp")
    return parsed


def resource_wall_clock(wall_clock: Callable[[], datetime] | None = None) -> datetime:
    value = datetime.now(timezone.utc) if wall_clock is None else wall_clock()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ResourceItemAuthorizationError(
            "Resource authorization wall clock must be timezone-aware UTC"
        )
    try:
        return value.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResourceItemAuthorizationError(
            "Resource authorization wall clock must be timezone-aware UTC"
        ) from exc


def load_resource_daily_reset_authority() -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the checked-in product authority before deriving Resource reset bounds."""
    from tasks.product_authority import (
        ProductAuthorityError,
        get_daily_reset_policy,
        load_product_authority,
    )

    try:
        authority = load_product_authority()
        policy = get_daily_reset_policy(authority)
    except ProductAuthorityError as exc:
        raise ResourceItemAuthorizationError(
            "Resource product authority or static UTC reset policy is invalid"
        ) from exc
    return authority, policy


def resource_deadline_evidence(payload: Mapping[str, Any]) -> tuple[str, datetime]:
    """Validate the static UTC reset payload without consulting runtime visuals."""
    from tasks.runtime_identity import derive_static_utc_reset

    authority, reset_policy = load_resource_daily_reset_authority()
    if not isinstance(payload, Mapping):
        raise ResourceItemAuthorizationError("Resource static reset payload is malformed")
    deadline_identity = payload.get(
        "reset_identity_id", payload.get("deadline_identity", payload.get("reset_deadline_identity"))
    )
    normalized = payload.get("reset_deadline_utc", payload.get("normalized_deadline_utc"))
    start_value = payload.get("reset_start_utc")
    if not isinstance(deadline_identity, str) or not deadline_identity.strip():
        raise ResourceItemAuthorizationError("Resource reset deadline identity is missing")
    if not isinstance(normalized, str) or not normalized.strip():
        raise ResourceItemAuthorizationError("Resource reset deadline is missing")
    if not isinstance(start_value, str) or not start_value.strip():
        raise ResourceItemAuthorizationError("Resource reset start is missing")
    deadline = resource_identity_timestamp(normalized, "Resource reset deadline")
    start = resource_identity_timestamp(start_value, "Resource reset start")
    if (
        deadline_identity != f"reset-deadline:{normalized}"
        or deadline != start + timedelta(days=1)
        or start.hour != 0
        or start.minute != 0
        or start.second != 0
        or start.microsecond != 0
        or payload.get("recurrence_class") != "daily_reset"
        or payload.get("recurrence_interval_seconds") != reset_policy["interval_seconds"]
        or payload.get("recurrence_interval_hours") != 24
        or payload.get("reset_timezone") != reset_policy["timezone"]
        or payload.get("reset_time") != reset_policy["reset_time"]
        or payload.get("product_authority_revision") != authority["authority_revision"]
        or payload.get("product_authority_digest") != authority["authority_digest"]
        or payload.get("product_policy_id") != reset_policy["policy_id"]
        or payload.get("reset_policy_id") != reset_policy["policy_id"]
        or payload.get("assurance") != "fixed_runtime_binding_static_utc_reset"
        or payload.get("identity_semantics") != "fixed_runtime_binding_plus_static_utc_reset"
    ):
        raise ResourceItemAuthorizationError("Resource reset payload is not the static UTC daily rule")
    evaluated_value = payload.get("_evaluated_utc", payload.get("evaluated_utc"))
    if evaluated_value is not None:
        evaluated = resource_identity_timestamp(evaluated_value, "Resource reset evaluation timestamp")
        try:
            expected = derive_static_utc_reset(evaluated)
        except ValueError as exc:
            raise ResourceItemAuthorizationError(
                "Resource reset evaluation timestamp is invalid"
            ) from exc
        if (
            expected.reset_identity_id != deadline_identity
            or expected.reset_start_utc != start
            or expected.reset_deadline_utc != deadline
        ):
            raise ResourceItemAuthorizationError(
                "Resource reset payload does not match its UTC wall-clock sample"
            )
    return deadline_identity, deadline


def produce_resource_runtime_identity(
    *,
    session: Any,
    wall_clock: Callable[[], datetime] | None = None,
    return_deadline_evidence: bool = False,
):
    """Produce fixed-binding Resource identity inside the already-entered session."""
    from tasks.runtime_identity import (
        RuntimeIdentityAssurance,
        derive_resource_runtime_identity,
        derive_static_utc_reset,
        resource_fixed_runtime_binding,
    )

    if session is None:
        raise ResourceItemAuthorizationError("Resource identity requires the current session")
    owner = str(getattr(session, "owner", "") or "")
    invocation_id = str(getattr(session, "invocation_id", "") or "")
    if not owner or not invocation_id:
        raise ResourceItemAuthorizationError("Resource identity requires the current session binding")
    binding = resource_fixed_runtime_binding()
    evaluated = resource_wall_clock(wall_clock)
    authority, reset_policy = load_resource_daily_reset_authority()
    try:
        window = derive_static_utc_reset(evaluated)
        identity = derive_resource_runtime_identity(
            binding,
            evaluated,
            authorization_freshness_seconds=RESOURCE_AUTHORIZATION_FRESHNESS_SECONDS,
            evidence_refs=(
                "identity-source:fixed-runtime-binding",
                "identity-source:static-utc-midnight-reset",
                f"product-authority-revision:{authority['authority_revision']}",
                f"product-authority-digest:{authority['authority_digest']}",
                f"product-policy-id:{reset_policy['policy_id']}",
                f"session-owner:{owner}",
                f"session-invocation:{invocation_id}",
            ),
        )
    except (TypeError, ValueError) as exc:
        raise ResourceItemAuthorizationError(f"Resource production identity denied: {exc}") from exc
    deadline_payload: dict[str, Any] = {
        "reset_identity_id": window.reset_identity_id,
        "deadline_identity": window.reset_identity_id,
        "reset_deadline_identity": window.reset_identity_id,
        "reset_start_utc": window.reset_start_text,
        "reset_deadline_utc": window.reset_deadline_text,
        "normalized_deadline_utc": window.reset_deadline_text,
        "evaluated_utc": window.evaluated_utc.isoformat().replace("+00:00", "Z"),
        "_evaluated_utc": window.evaluated_utc.isoformat().replace("+00:00", "Z"),
        "authorization_expires_utc": identity.expires_utc,
        "recurrence_class": "daily_reset",
        "recurrence_interval_seconds": reset_policy["interval_seconds"],
        "recurrence_interval_hours": 24,
        "reset_timezone": reset_policy["timezone"],
        "reset_time": reset_policy["reset_time"],
        "product_authority_revision": authority["authority_revision"],
        "product_authority_digest": authority["authority_digest"],
        "product_policy_id": reset_policy["policy_id"],
        "reset_policy_id": reset_policy["policy_id"],
        "assurance": identity.assurance.value,
        "identity_semantics": "fixed_runtime_binding_plus_static_utc_reset",
        "runtime_scope": binding.runtime_scope,
        "account_id": binding.account_id,
        "server_id": binding.server_id,
    }
    if identity.assurance is not RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_STATIC_UTC_RESET:
        raise ResourceItemAuthorizationError("Resource identity assurance is not static UTC")
    resource_deadline_evidence(deadline_payload)
    if return_deadline_evidence:
        return identity, deadline_payload
    return identity


def inspect_admitted_resource_store(path: Path, *, fixed_canonical: bool) -> None:
    """Read the canonical Resource store schema without creating or migrating it."""
    if fixed_canonical:
        from scripts.navigation_development_boundary import (
            CANONICAL_ACTION_STORE_PATH,
            require_fixed_orchestrator_path,
        )

        path = require_fixed_orchestrator_path(
            path, CANONICAL_ACTION_STORE_PATH, "canonical Resource SafetyStore"
        )
    if path.is_symlink() or not path.is_file():
        raise ResourceItemAuthorizationError("canonical Resource SafetyStore v4 is not already admitted")
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0)
    except sqlite3.Error as exc:
        raise ResourceItemAuthorizationError(
            "canonical Resource SafetyStore cannot be inspected read-only"
        ) from exc
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        version_row = connection.execute(
            "SELECT version FROM schema_version WHERE singleton=1"
        ).fetchone()
        if version_row is None or int(version_row["version"]) != 4:
            raise ResourceItemAuthorizationError(
                "canonical Resource SafetyStore must already be schema v4; migration is disabled"
            )
        tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        required = {
            "actions", "controller_lease", "resource_reset_identities", "resource_occurrences",
            "resource_attempts", "resource_attempt_claims", "resource_reservations",
            "resource_transport_facts", "resource_transport_outcomes", "resource_live_effects",
        }
        if not required.issubset(tables):
            raise ResourceItemAuthorizationError(
                "canonical Resource SafetyStore v4 is incomplete; migration is disabled"
            )
    except sqlite3.Error as exc:
        raise ResourceItemAuthorizationError("canonical Resource SafetyStore schema is unreadable") from exc
    finally:
        connection.close()


def open_admitted_resource_store(
    *,
    store_path: Path | None = None,
    store_factory: Callable[[Path], Any] | None = None,
) -> Any:
    """Open pre-admitted v4 canonical Resource SafetyStore; test paths are explicit."""
    from safe_action_core import SafetyStore
    from safe_action_core.store import SchemaVersionError
    from scripts.navigation_development_boundary import CANONICAL_ACTION_STORE_PATH

    injected = store_factory is not None
    path = Path(store_path) if store_path is not None else Path(CANONICAL_ACTION_STORE_PATH)
    inspect_admitted_resource_store(path, fixed_canonical=not injected)
    factory = store_factory or SafetyStore
    try:
        store = factory(path)
    except (OSError, SchemaVersionError) as exc:
        raise ResourceItemAuthorizationError(
            "canonical Resource SafetyStore v4 could not be opened"
        ) from exc
    if getattr(store, "schema_version", None) != 4:
        try:
            store.close()
        except BaseException:
            pass
        raise ResourceItemAuthorizationError("canonical Resource SafetyStore must already be schema v4")
    return store


def resource_reset_identity(verified_identity: Any, deadline_payload: Mapping[str, Any]) -> Any:
    """Bind one Resource reset to its exact static UTC midnight interval."""
    from safe_action_core.resource_effect_authority import ResourceResetIdentity
    from tasks.runtime_identity import RuntimeIdentityAssurance, VerifiedRuntimeIdentity

    if type(verified_identity) is not VerifiedRuntimeIdentity:
        raise ResourceItemAuthorizationError("Resource runtime identity is missing or not verified")
    if verified_identity.assurance is not RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_STATIC_UTC_RESET:
        raise ResourceItemAuthorizationError(
            "Resource runtime identity is not FIXED_RUNTIME_BINDING_STATIC_UTC_RESET"
        )
    deadline_identity, deadline = resource_deadline_evidence(deadline_payload)
    reset_start = resource_identity_timestamp(
        str(getattr(verified_identity, "reset_start_utc", "") or ""),
        "Resource runtime identity reset_start_utc",
    )
    identity_deadline = resource_identity_timestamp(
        str(getattr(verified_identity, "reset_deadline_utc", "") or ""),
        "Resource runtime identity reset_deadline_utc",
    )
    if (
        verified_identity.reset_id != deadline_identity
        or identity_deadline != deadline
        or deadline_payload.get("reset_start_utc") != reset_start.isoformat().replace("+00:00", "Z")
    ):
        raise ResourceItemAuthorizationError(
            "Resource runtime identity does not match the static UTC reset"
        )
    if not verified_identity.observed_utc or not verified_identity.expires_utc:
        raise ResourceItemAuthorizationError("Resource runtime identity freshness evidence is incomplete")
    observed = resource_identity_timestamp(verified_identity.observed_utc, "Resource runtime identity observed_utc")
    expires = resource_identity_timestamp(verified_identity.expires_utc, "Resource runtime identity expires_utc")
    evaluated_value = deadline_payload.get("_evaluated_utc")
    evaluated = (
        datetime.now(timezone.utc)
        if evaluated_value is None
        else resource_identity_timestamp(evaluated_value, "Resource identity evaluation timestamp")
    )
    if observed > evaluated or expires <= evaluated or expires <= observed:
        raise ResourceItemAuthorizationError("Resource runtime identity is stale")
    if evaluated >= deadline:
        raise ResourceItemAuthorizationError("Resource reset deadline has been reached")
    if reset_start + timedelta(days=1) != deadline or evaluated < reset_start:
        raise ResourceItemAuthorizationError("Resource reset is not the active static UTC window")
    evidence_refs = tuple(dict.fromkeys((*tuple(verified_identity.evidence_refs), deadline_identity)))
    return ResourceResetIdentity(
        reset_identity_id=deadline_identity,
        account_id=verified_identity.account_id,
        server_id=verified_identity.server_id,
        runtime_scope=verified_identity.runtime_scope,
        reset_start_utc=(deadline - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        reset_deadline_utc=deadline.isoformat().replace("+00:00", "Z"),
        assurance=RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_STATIC_UTC_RESET.value,
        observed_at=max(0.0, observed.timestamp()),
        expires_at=expires.timestamp(),
        evidence_refs=evidence_refs,
    )


def build_resource_runtime_components(
    *,
    session: Any,
    verified_identity: Any,
    deadline_payload: Mapping[str, Any],
    store_path: Path | None = None,
    store_factory: Callable[[Path], Any] | None = None,
    action_store: Any | None = None,
    wall_clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Construct the existing ResourceEffectAuthority and its one-use runtime."""
    from safe_action_core.models import ActionClass, ActionIntent, Observation, PolicyRequest
    from safe_action_core.policy import ACTIVE_RUNTIME_PROFILE_ID, CentralPolicy
    from safe_action_core.resource_effect_authority import (
        PreparedResourceAuthorization,
        ResourceEffectAuthority,
        ResourceOccurrenceIdentity,
        ResourceReservationSpec,
        RESOURCE_FLOW_ID,
        RESOURCE_OBJECTIVE_ACTION_ID,
        RESOURCE_PRODUCT_POLICY_REVISION,
        RESOURCE_RECURRENCE_CLASS,
        RESOURCE_RECURRENCE_POLICY_REVISION,
        RESOURCE_TARGET_VARIANT,
    )
    from scripts.navigation_development_boundary import DevelopmentSessionError

    if not hasattr(session, "runtime_input_lock"):
        raise ResourceItemAuthorizationError("DevelopmentSession cannot expose its held runtime lock")
    try:
        runtime_lock = session.runtime_input_lock
    except DevelopmentSessionError as exc:
        raise ResourceItemAuthorizationError(
            "Resource authority requires the entered DevelopmentSession"
        ) from exc
    owner = str(getattr(session, "owner", "") or "")
    session_invocation_id = str(getattr(session, "invocation_id", "") or "")
    if not owner or not session_invocation_id:
        raise ResourceItemAuthorizationError("Resource authority requires exact owner and invocation")
    # Borrowed native sessions retain their route action-store lease owner,
    # while the Resource controller/fence belongs to the actual input operator.
    runtime_owner = runtime_lock.owner
    invocation_id = runtime_lock.invocation_id
    runtime_lock.assert_held(runtime_owner, invocation_id)
    reset_identity = resource_reset_identity(verified_identity, deadline_payload)
    authorization_window = ResourceAuthorizationWindow(
        reset_deadline_utc=resource_identity_timestamp(
            reset_identity.reset_deadline_utc, "Resource reset deadline"
        ),
        authorization_expires_utc=resource_identity_timestamp(
            verified_identity.expires_utc, "Resource authorization expiry"
        ),
    )
    try:
        authorization_window.require_current(ResourceAuthorizationWindow.sample_current_utc(wall_clock))
    except ResourceAuthorizationWindowError as exc:
        raise ResourceItemAuthorizationError(
            "Resource authorization window denied before Resource SafetyStore open"
        ) from exc
    owns_store = action_store is None
    store = (
        open_admitted_resource_store(store_path=store_path, store_factory=store_factory)
        if owns_store
        else action_store
    )
    if getattr(store, "schema_version", None) != 4:
        if owns_store:
            try:
                store.close()
            except BaseException:
                pass
        raise ResourceItemAuthorizationError(
            "Resource authority requires the already admitted canonical SafetyStore v4"
        )
    authority = None
    controller_lease: Mapping[str, Any] | None = None
    try:
        authority = ResourceEffectAuthority(store)
        now = time.monotonic()
        controller_lease = authority.acquire_resource_controller_lease(
            owner_id=runtime_owner,
            now=now,
            ttl_seconds=600.0,
            mode="execute",
            runtime_invocation_id=invocation_id,
            block_keys={
                "account_id": reset_identity.account_id,
                "server_id": reset_identity.server_id,
                "reset_identity_id": reset_identity.reset_identity_id,
            },
        )
        policy = CentralPolicy(supervised_tasks={RESOURCE_FLOW_ID})
        preparation_used = False

        def prepare_resource_effect(
            source: CapturedNativeFrame,
            target_roi: tuple[int, int, int, int],
            requested_action_key: str,
        ) -> Any:
            nonlocal preparation_used
            if preparation_used:
                raise ResourceItemAuthorizationError("Resource preparation callback is one-shot")
            preparation_used = True
            if type(source) is not CapturedNativeFrame:
                raise ResourceItemAuthorizationError(
                    "Resource preparation requires the captured immediate-before frame"
                )
            if requested_action_key != ITEM_USE_ACTION_KEY:
                raise ResourceItemAuthorizationError("Resource preparation action key is not exact")
            runtime_lock.assert_held(runtime_owner, invocation_id)
            now = time.monotonic()
            authority.ensure_static_utc_reset_identity(reset_identity)
            occurrence = authority.create_resource_occurrence(
                ResourceOccurrenceIdentity(
                    reset_identity.account_id,
                    reset_identity.server_id,
                    RESOURCE_FLOW_ID,
                    reset_identity.reset_identity_id,
                    product_policy_revision=RESOURCE_PRODUCT_POLICY_REVISION,
                    recurrence_policy_revision=RESOURCE_RECURRENCE_POLICY_REVISION,
                    recurrence_class=RESOURCE_RECURRENCE_CLASS,
                    objective_action_id=RESOURCE_OBJECTIVE_ACTION_ID,
                    target_variant=RESOURCE_TARGET_VARIANT,
                ),
                now=now,
            )
            occurrence_id = str(occurrence["occurrence_id"])
            hypothesis_digest = hashlib.sha256(
                json.dumps(
                    {
                        "source_sha256": source.sha256,
                        "target_roi": tuple(target_roi),
                        "target_identity": USE_TARGET_IDENTITY,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            claim = authority.claim_resource_attempt(
                occurrence_id,
                owner,
                expected_revision=int(occurrence["state_revision"]),
                now=now,
                hypothesis_digest=hypothesis_digest,
            )
            if claim.state != "ACTIVE" or not claim.can_dispatch:
                raise ResourceItemAuthorizationError(
                    "Resource occurrence did not grant one dispatch claim"
                )
            context = authority.occurrence_context(occurrence_id)
            controller_token = str(
                controller_lease.get("controller_token") or controller_lease.get("lease_token") or ""
            )
            controller_generation = int(
                controller_lease.get("controller_generation", controller_lease.get("generation", 0))
            )
            authorization_generation = authority.next_resource_authorization_generation(context)
            reservation_spec = ResourceReservationSpec(
                authorization_generation=authorization_generation,
                immediate_before_sha256=source.sha256,
                runtime_invocation_id=invocation_id,
                controller_token=controller_token,
                controller_generation=controller_generation,
            )
            fence = authority.resource_dispatch_fence(
                context, claim, controller_lease, reservation_spec
            )
            height, width = source.frame.shape[:2]
            observation = Observation(
                frame_sha256=source.sha256,
                capture_completed_monotonic=float(source.captured_monotonic),
                runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
                width=int(width),
                height=int(height),
                valid_png=source.png[:8] == b"\x89PNG\r\n\x1a\n",
                corrupt=False,
                black=not bool(source.frame.any()),
                source_state="RESOURCES_1K_FOOD_READY",
                overlay_state="none",
                target_identity=USE_TARGET_IDENTITY,
                target_roi=tuple(target_roi),
                recognized=True,
                control_class="USE",
                consequence="ordinary_non_idempotent_resource_item_use",
                cost_type="owned_inventory_item",
                cost_amount=1,
                quantity=1,
                expected_postcondition="RESOURCES_1K_FOOD_USED",
                evidence_refs=(*tuple(verified_identity.evidence_refs), f"frame:{source.sha256}"),
                package_foreground=True,
            )
            action_key = authority.resource_action_key(context, authorization_generation)
            action_id = "resource-action:v1:" + hashlib.sha256(
                json.dumps(
                    {"action_key": action_key, "context": context.as_dict()},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            intent = ActionIntent(
                action_id=action_id,
                action_key=action_key,
                task_id=RESOURCE_FLOW_ID,
                semantic_action="USE_RESOURCE_ITEM",
                source_state="RESOURCES_1K_FOOD_READY",
                target_identity=USE_TARGET_IDENTITY,
                target_roi=tuple(target_roi),
                source_frame_sha256=source.sha256,
                source_frame_captured_at=float(source.captured_monotonic),
                runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
                game_day_id=reset_identity.reset_identity_id,
                expected_postcondition="RESOURCES_1K_FOOD_USED",
                consequence="ordinary_non_idempotent_resource_item_use",
                cost_type="owned_inventory_item",
                cost_amount=1,
                quantity=1,
                evidence_refs=observation.evidence_refs,
                consequential=False,
                action_class=ActionClass.OWNED_ITEM_NON_IDEMPOTENT,
                action_kind="USE_RESOURCE_ITEM",
                subject="1k_food",
                resource_or_currency="1k_food",
                maximum_cost=1,
                free_only=False,
                semantic_preconditions=("exact_owned_1k_food", "single_use"),
                semantic_postconditions=("RESOURCES_1K_FOOD_USED",),
                resource_authorization_context=context,
            )
            duplicate = store.connection.execute(
                "SELECT 1 FROM actions WHERE action_key=?", (action_key,)
            ).fetchone() is not None
            request = PolicyRequest(
                action_id=action_id,
                action_key=action_key,
                task_id=RESOURCE_FLOW_ID,
                task_mode="supervised_validation",
                semantic_action="USE_RESOURCE_ITEM",
                expected_runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
                observation=observation,
                monotonic_now=now,
                observation_max_age_seconds=30.0,
                dispatch_max_age_seconds=30.0,
                lease_owner=owner,
                lease_valid=True,
                unresolved_action=False,
                duplicate_action_key=duplicate,
                game_day_id=reset_identity.reset_identity_id,
                policy_phase="pre_dispatch",
                action_class=ActionClass.OWNED_ITEM_NON_IDEMPOTENT,
                action_kind="USE_RESOURCE_ITEM",
                subject="1k_food",
                resource_or_currency="1k_food",
                maximum_cost=1,
                free_only=False,
                semantic_preconditions=("exact_owned_1k_food", "single_use"),
                semantic_postconditions=("RESOURCES_1K_FOOD_USED",),
                runtime_session_id=invocation_id,
                resource_authorization_context=context,
                effect_dispatch_fence=fence,
            )
            issued = policy.issue_capability(request)
            if not issued.authorized or issued.capability is None:
                raise ResourceItemAuthorizationError(
                    f"Resource capability denied: {issued.reason_code}"
                )
            prepared = authority.prepare_resource_effect_action(
                context,
                claim,
                claim,
                controller_lease,
                intent,
                issued.policy_result,
                reservation_spec,
                now=now,
            )
            if prepared.fence != fence:
                raise ResourceItemAuthorizationError(
                    "Resource preparation fence changed during atomic preparation"
                )
            return PreparedResourceAuthorization(
                prepared=prepared, request=request, capability=issued.capability
            )

        def runtime_factory(inner: LocalBlueStacksRuntime) -> AuthorizedResourceItemRuntime:
            return AuthorizedResourceItemRuntime(
                inner,
                authority=authority,
                controller_lease=controller_lease,
                runtime_lock=runtime_lock,
                policy=policy,
                prepare=prepare_resource_effect,
                now=time.monotonic,
                authorization_window=authorization_window,
                wall_clock=wall_clock,
            )

        return {
            "runtime_factory": runtime_factory,
            "authority": authority,
            "store": store,
            "owns_store": owns_store,
            "controller_lease": controller_lease,
            "authorization_window": authorization_window,
            "reset_identity": reset_identity,
        }
    except BaseException:
        if authority is not None and controller_lease is not None:
            try:
                authority.release_resource_controller_lease(
                    owner,
                    str(controller_lease.get("controller_token") or controller_lease.get("lease_token") or ""),
                    time.monotonic(),
                )
            except BaseException:
                pass
        if owns_store:
            store.close()
        raise


def release_resource_runtime_components(components: Mapping[str, Any]) -> None:
    """Release the Resource controller lease and any owned SafetyStore."""
    authority = components.get("authority")
    controller = components.get("controller_lease")
    store = components.get("store")
    try:
        if authority is not None and isinstance(controller, Mapping):
            authority.release_resource_controller_lease(
                str(controller.get("owner_id") or ""),
                str(controller.get("controller_token") or controller.get("lease_token") or ""),
                time.monotonic(),
            )
    finally:
        if store is not None and components.get("owns_store") is True:
            store.close()




def item_use_transport_calls(session: Path) -> int:
    events = Path(session) / "events.jsonl"
    if not events.is_file():
        return 0
    calls = 0
    for line in events.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if (
            isinstance(row, Mapping)
            and row.get("type") == "dispatch"
            and row.get("execute") is not False
            and (
                row.get("action_key") == ITEM_USE_ACTION_KEY
                or (
                    row.get("target_identity") == USE_TARGET_IDENTITY
                    and str(row.get("action_key") or "").startswith("occ:v1:")
                )
            )
        ):
            calls += 1
    return calls


def _as_int(value: object) -> int | None:
    return value if type(value) is int else None


def semantic_from_result(result: Mapping[str, Any]) -> dict[str, Any]:
    semantic = result.get("semantic_evidence")
    if isinstance(semantic, Mapping) and semantic:
        return dict(semantic)
    recognitions = result.get("recognitions")
    if not isinstance(recognitions, Mapping):
        recognitions = {}
    before = recognitions.get("item-before") or recognitions.get("item-ready") or {}
    after = recognitions.get("item-after") or {}
    if not isinstance(before, Mapping):
        before = {}
    if not isinstance(after, Mapping):
        after = {}
    frames = result.get("frames")
    frame_map = frames if isinstance(frames, Mapping) else {}
    return {
        "before_owned_quantity": _as_int(before.get("inventory_quantity", before.get("owned_quantity"))),
        "after_owned_quantity": _as_int(after.get("inventory_quantity", after.get("owned_quantity"))),
        "resource_delta_verified": result.get("resource_delta_verified") is True,
        "terminal_home_verified": result.get("terminal_home_verified") is True,
        "home_verified": result.get("terminal_home_verified") is True,
        "item_before_frame": frame_map.get("item-before"),
        "item_after_frame": frame_map.get("item-after"),
        "terminal_home_frame": frame_map.get("home") or frame_map.get("return-home-immediate-post"),
    }


def _bound_retained_frame(session: Path, frame_ref: object) -> Path | None:
    if not isinstance(frame_ref, Mapping):
        return None
    path_value, sha = frame_ref.get("path"), frame_ref.get("sha256")
    if not isinstance(path_value, str) or not isinstance(sha, str):
        return None
    digest_expected = sha.casefold()
    if not _SHA256_RE.fullmatch(digest_expected):
        return None
    candidate = Path(path_value)
    if candidate.is_absolute():
        return None
    try:
        root = Path(session).resolve()
        resolved = (root / candidate).resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    if os.path.islink(resolved) or not resolved.is_file() or resolved.stat().st_size <= 0:
        return None
    try:
        digest, size = sha256_stream(resolved)
    except Exception:
        return None
    if size <= 0 or digest.casefold() != digest_expected:
        return None
    return resolved


def _relocate_frame_ref_into_session(session: Path, frame_ref: object) -> dict[str, Any] | None:
    if not isinstance(frame_ref, Mapping):
        return None
    path_value, sha = frame_ref.get("path"), frame_ref.get("sha256")
    if not isinstance(path_value, str) or not isinstance(sha, str):
        return None
    digest_expected = sha.casefold()
    if not _SHA256_RE.fullmatch(digest_expected):
        return None
    raw = Path(path_value)
    session_resolved = Path(session).resolve()
    candidates = [raw] if raw.is_absolute() else [Path(session) / raw, Path(session).parent / raw, Path(session) / "frames" / raw.name]
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            resolved.relative_to(session_resolved)
        except (OSError, ValueError):
            continue
        if os.path.islink(resolved) or not resolved.is_file() or resolved.stat().st_size <= 0:
            continue
        try:
            digest, size = sha256_stream(resolved)
        except Exception:
            continue
        if size <= 0 or digest.casefold() != digest_expected:
            continue
        relocated = {"path": resolved.relative_to(session_resolved).as_posix(), "sha256": digest.casefold()}
        if "captured_monotonic" in frame_ref:
            relocated["captured_monotonic"] = frame_ref.get("captured_monotonic")
        return relocated
    return None


def _load_bound_native_frame(session: Path, frame_ref: object) -> tuple[Path, np.ndarray] | None:
    bound = _bound_retained_frame(session, frame_ref)
    if bound is None:
        return None
    image = cv2.imread(str(bound), cv2.IMREAD_COLOR)
    if image is None or not isinstance(image, np.ndarray):
        return None
    from scripts.bluestacks_native_runtime import NATIVE_HEIGHT, NATIVE_WIDTH

    if image.shape[:2] != (NATIVE_HEIGHT, NATIVE_WIDTH):
        return None
    return bound, image


def _normalize_semantic_for_session(session: Path, semantic: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(semantic)
    for key in ("item_before_frame", "item_after_frame", "terminal_home_frame"):
        normalized[key] = _relocate_frame_ref_into_session(session, semantic.get(key))
    return normalized


def reconcile_resource_route(
    *,
    runtime: AuthorizedResourceItemRuntime,
    session: Path,
    route_result: Mapping[str, Any],
    item_use_calls: int,
) -> dict[str, Any] | None:
    """Persist only current retained evidence; never obtains transport authority."""
    prepared = runtime.prepared_effect
    authority = runtime._authority
    if prepared is None or authority is None or item_use_calls <= 0:
        return None
    semantic = _normalize_semantic_for_session(Path(session), semantic_from_result(route_result))
    before_ref = semantic.get("item_before_frame")
    before_loaded = _load_bound_native_frame(Path(session), before_ref)
    after_loaded = _load_bound_native_frame(Path(session), semantic.get("item_after_frame"))
    evidence_refs = tuple(
        reference
        for frame in (before_ref, semantic.get("item_after_frame"), semantic.get("terminal_home_frame"))
        if isinstance(frame, Mapping)
        for reference in (f"frame-path:{frame.get('path')}", f"frame-sha256:{frame.get('sha256')}")
    )
    evidence: dict[str, Any] = {
        "observe_only": True,
        "transport_calls": item_use_calls,
        "before_owned_quantity": semantic.get("before_owned_quantity"),
        "after_owned_quantity": semantic.get("after_owned_quantity"),
        "evidence_refs": evidence_refs,
    }
    confirmed = False
    if (
        item_use_calls == 1
        and isinstance(before_ref, Mapping)
        and before_ref.get("sha256") == prepared.fence.immediate_before_sha256
        and before_loaded is not None
        and after_loaded is not None
    ):
        _, before_image = before_loaded
        _, after_image = after_loaded
        try:
            before_item = recognize_food_item_in_resources(before_image)
            after_item = recognize_food_item_in_resources(after_image)
            before_count = _as_int(before_item.inventory_quantity if before_item.inventory_quantity is not None else before_item.owned_quantity)
            after_count = _as_int(after_item.inventory_quantity if after_item.inventory_quantity is not None else after_item.owned_quantity)
            after_visual = after_item.visual_evidence if isinstance(after_item.visual_evidence, Mapping) else {}
            after_card = after_visual.get("item_card")
            confirmed = bool(
                resource_item_authorizeable(before_item)
                and after_item.item_name == "1K Food"
                and after_item.target_identity == "daily-resource-item:1k-food"
                and isinstance(after_card, Mapping)
                and after_card.get("proven") is True
                and after_count is not None
                and before_count == _as_int(semantic.get("before_owned_quantity"))
                and after_count == _as_int(semantic.get("after_owned_quantity"))
                and _resource_delta_verified(
                    {"inventory_quantity": before_count},
                    {"inventory_quantity": after_count},
                )
            )
            evidence.update(
                before_owned_quantity=before_count,
                after_owned_quantity=after_count,
            )
        except Exception:
            confirmed = False
    evidence["effect_state"] = "EFFECT_CONFIRMED" if confirmed else "UNRESOLVED"
    evidence["proven_no_effect"] = False
    reconciled = authority.reconcile_resource_effect_observe_only(
        prepared.reservation_id, evidence, now=time.monotonic()
    )
    home_ref = semantic.get("terminal_home_frame")
    if confirmed:
        home_loaded = _load_bound_native_frame(Path(session), home_ref)
        if home_loaded is not None and isinstance(home_ref, Mapping):
            _, home_image = home_loaded
            home = _recognize_home(home_image)
            if home.get("recognized") is True and home.get("home_verified") is True:
                authority.terminal_observation(
                    {
                        "occurrence_id": prepared.occurrence_id,
                        "terminal_state": "HOME_CANONICAL",
                        "frame_sha256": str(home_ref["sha256"]),
                        "evidence_refs": evidence_refs,
                    },
                    now=time.monotonic(),
                )
    return dict(reconciled)


__all__ = [
    "AuthorizedResourceItemRuntime",
    "ResourceAuthorizationWindow",
    "ResourceAuthorizationWindowError",
    "ResourceItemAuthorizationError",
    "build_resource_runtime_components",
    "item_use_transport_calls",
    "open_admitted_resource_store",
    "produce_resource_runtime_identity",
    "reconcile_resource_route",
    "release_resource_runtime_components",
    "resource_deadline_evidence",
    "resource_identity_timestamp",
    "resource_reset_identity",
    "resource_wall_clock",
]
