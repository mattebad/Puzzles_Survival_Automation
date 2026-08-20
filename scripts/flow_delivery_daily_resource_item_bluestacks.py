"""Thin pnsctl conduct adapter for the Daily 1K Food flow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time
from typing import Any, Callable, Mapping

from scripts.bluestacks_native_runtime import CapturedNativeFrame, LocalBlueStacksRuntime, NativeBox
from safe_action_core.resource_effect_authority import (
    PreparedResourceAuthorization,
    PreparedResourceEffect,
    ResourceEffectAuthority,
    ResourceTransportIntentToken,
)
from scripts.daily_resource_item_bluestacks import (
    MAX_RESOURCE_LIST_SWIPES as ROUTE_MAX_RESOURCE_LIST_SWIPES,
    MAX_ROUTE_INPUTS as ROUTE_MAX_ROUTE_INPUTS,
    _recognize_home,
    _resource_delta_verified,
    recognize_food_item_in_resources,
)
from scripts.evidence_hygiene import sha256_stream
import cv2
import numpy as np
import os
import re


FLOW_ID = "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION"
RUNNER_ID = "daily_resource_item_bluestacks_runner"
VALIDATOR_ID = "daily_resource_item_bluestacks_evidence"
RECOVERY_ID = "daily_resource_item_bluestacks_recovery"
MAX_INPUTS = ROUTE_MAX_ROUTE_INPUTS
MAX_RESOURCE_LIST_SWIPES = ROUTE_MAX_RESOURCE_LIST_SWIPES
ITEM_USE_ACTION_KEY = "daily-resource-item:use-1k-food"
MAX_ITEM_USE_TRANSPORT_CALLS = 1
RESOURCE_DISPATCH_SAFETY_MARGIN_SECONDS = 2.0


class ResourceDispatchWindowError(RuntimeError):
    """The current wall clock is outside the exact Resource dispatch window."""


def _normalize_resource_wall_clock(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ResourceDispatchWindowError(
            "Resource dispatch wall clock must return a datetime"
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise ResourceDispatchWindowError(
            "Resource dispatch wall clock must be timezone-aware UTC"
        )
    try:
        return value.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResourceDispatchWindowError(
            "Resource dispatch wall clock must be timezone-aware UTC"
        ) from exc


@dataclass(frozen=True)
class ResourceDispatchWindow:
    """Immutable receipt/reset bounds carried to the exact Resource Use seam."""

    reset_deadline_utc: datetime
    receipt_expires_utc: datetime
    safety_margin_seconds: float = RESOURCE_DISPATCH_SAFETY_MARGIN_SECONDS

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reset_deadline_utc",
            _normalize_resource_wall_clock(self.reset_deadline_utc),
        )
        object.__setattr__(
            self,
            "receipt_expires_utc",
            _normalize_resource_wall_clock(self.receipt_expires_utc),
        )
        if (
            type(self.safety_margin_seconds) not in {int, float}
            or not float(self.safety_margin_seconds) > 0.0
        ):
            raise ValueError("Resource dispatch safety margin must be positive")

    @property
    def receipt_expiry_utc(self) -> datetime:
        """Compatibility alias using the receipt's expiry terminology."""

        return self.receipt_expires_utc

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
        """Require strict margin before both receipt and reset bounds."""

        current = _normalize_resource_wall_clock(current_utc)
        if (
            current + self.safety_margin >= self.reset_deadline_utc
            or current + self.safety_margin >= self.receipt_expires_utc
        ):
            raise ResourceDispatchWindowError(
                "Resource dispatch denied: current UTC is at or inside the "
                "receipt/reset safety margin"
            )
        return current


class AuthorizedResourceItemRuntime:
    """Resource route adapter with a single fenced Use seam."""

    def __init__(
        self,
        inner: LocalBlueStacksRuntime,
        *,
        authority: ResourceEffectAuthority | None = None,
        prepared: PreparedResourceEffect | None = None,
        controller_lease: Mapping[str, Any] | None = None,
        runtime_lock: Any | None = None,
        capability: Any | None = None,
        policy: Any | None = None,
        request: Any | None = None,
        prepare: Any | None = None,
        now: float | Callable[[], float] = 0.0,
        dispatch_window: ResourceDispatchWindow | None = None,
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
        self._dispatch_window = dispatch_window
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
    def prepared_action_key(self) -> str | None:
        return self._prepared.action_key if self._prepared is not None else None

    @property
    def prepared_effect(self) -> PreparedResourceEffect | None:
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
            or kwargs.get("target_identity") == "daily-resource-item:use-1k-food"
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
        prepared: PreparedResourceEffect | None = None,
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
            if type(bundle) is not PreparedResourceAuthorization:
                raise RuntimeError("Resource preparation callback returned no typed bundle")
            prepared_effect = bundle.prepared
            request_value = bundle.request
            capability_value = bundle.capability
            self._prepared = prepared_effect
        if prepared_effect is None and self._dispatch_window is not None:
            try:
                self._dispatch_window.require_current(
                    ResourceDispatchWindow.sample_current_utc(self._wall_clock)
                )
            except ResourceDispatchWindowError as exc:
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
        dispatch_action_key = prepared_effect.action_key
        if self._dispatch_window is None:
            raise RuntimeError("Resource dispatch authorization window is required")
        effective_now = self._now if now is None else now
        if callable(effective_now):
            effective_now = effective_now()
        try:
            self._dispatch_window.require_current(
                ResourceDispatchWindow.sample_current_utc(self._wall_clock)
            )
        except ResourceDispatchWindowError as exc:
            try:
                authority.cancel_prepared_resource_effect(
                    prepared_effect,
                    controller_lease=controller_lease,
                    runtime_lock=runtime_lock,
                    reason="reset_dispatch_window_expired",
                    now=float(effective_now),
                )
            except BaseException as cleanup_exc:
                raise RuntimeError(
                    "Resource dispatch denied and pre-intent cancellation failed"
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
                target_identity="daily-resource-item:use-1k-food",
                target_roi=target_roi,
                action_key=dispatch_action_key,
                transport_intent_token=token,
            ),
            now=float(effective_now),
        )


def _pnsctl():
    from scripts import pnsctl

    return pnsctl


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _max_inputs(lease: Mapping[str, Any]) -> int:
    try:
        maximum = int(lease.get("max_inputs", MAX_INPUTS))
    except (TypeError, ValueError) as exc:
        raise _pnsctl().OperatorError(
            "Daily Resource Item max_inputs must be an integer"
        ) from exc
    if not 1 <= maximum <= MAX_INPUTS:
        raise _pnsctl().OperatorError(
            f"Daily Resource Item max_inputs must be between 1 and {MAX_INPUTS}"
        )
    return maximum


def _outer_session(lease: Mapping[str, Any]) -> Any:
    session = lease.get("development_session")
    if session is None or not callable(getattr(session, "run_action", None)):
        raise _pnsctl().OperatorError(
            "Daily Resource Item requires the pnsctl-owned DevelopmentSession"
        )
    return session


def _item_use_calls(session: Path) -> int:
    events = session / "events.jsonl"
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
                    row.get("target_identity") == "daily-resource-item:use-1k-food"
                    and str(row.get("action_key") or "").startswith("occ:v1:")
                )
            )
        ):
            calls += 1
    return calls


def _as_int(value: object) -> int | None:
    return value if type(value) is int else None


def _semantic_from_result(result: Mapping[str, Any]) -> dict[str, Any]:
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
        "before_owned_quantity": _as_int(
            before.get("inventory_quantity", before.get("owned_quantity"))
        ),
        "after_owned_quantity": _as_int(
            after.get("inventory_quantity", after.get("owned_quantity"))
        ),
        "before_food_resource": _as_int(before.get("food_resource")),
        "after_food_resource": _as_int(after.get("food_resource")),
        "resource_delta_verified": result.get("resource_delta_verified") is True,
        "terminal_home_verified": result.get("terminal_home_verified") is True,
        "home_verified": result.get("terminal_home_verified") is True,
        "item_before_frame": frame_map.get("item-before"),
        "item_after_frame": frame_map.get("item-after"),
        "terminal_home_frame": frame_map.get("home")
        or frame_map.get("return-home-immediate-post"),
    }


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _bound_retained_frame(session: Path, frame_ref: object) -> Path | None:
    """Resolve one session-relative frame ref and require an exact SHA-256 match.

    Reuses pnsctl session-relative path confinement and evidence_hygiene hashing.
    Absolute outside paths, ``..`` escapes, symlinks, basename fallbacks, and
    digest mismatches fail closed.
    """

    if not isinstance(frame_ref, Mapping):
        return None
    path_value = frame_ref.get("path")
    sha = frame_ref.get("sha256")
    if not isinstance(path_value, str) or not isinstance(sha, str):
        return None
    digest_expected = sha.casefold()
    if not _SHA256_RE.fullmatch(digest_expected):
        return None
    try:
        resolved = _pnsctl()._session_relative_path(session, path_value, "frame")
    except Exception:
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


def _relocate_frame_ref_into_session(
    session: Path, frame_ref: object
) -> dict[str, Any] | None:
    """Rewrite a producer frame ref to a hash-bound path under ``session``."""

    if not isinstance(frame_ref, Mapping):
        return None
    path_value = frame_ref.get("path")
    sha = frame_ref.get("sha256")
    if not isinstance(path_value, str) or not isinstance(sha, str):
        return None
    digest_expected = sha.casefold()
    if not _SHA256_RE.fullmatch(digest_expected):
        return None
    raw = Path(path_value)
    session_resolved = session.resolve()
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(session / raw)
        # Route frame refs are often relative to the outer development session.
        candidates.append(session.parent / raw)
        candidates.append(session / "frames" / raw.name)
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if os.path.islink(resolved) or not resolved.is_file() or resolved.stat().st_size <= 0:
            continue
        try:
            resolved.relative_to(session_resolved)
        except ValueError:
            continue
        try:
            digest, size = sha256_stream(resolved)
        except Exception:
            continue
        if size <= 0 or digest.casefold() != digest_expected:
            continue
        rel = resolved.relative_to(session_resolved).as_posix()
        relocated = {
            "path": rel,
            "sha256": digest.casefold(),
        }
        if "captured_monotonic" in frame_ref:
            relocated["captured_monotonic"] = frame_ref.get("captured_monotonic")
        return relocated
    return None


def _load_bound_native_frame(
    session: Path, frame_ref: object
) -> tuple[Path, np.ndarray] | None:
    bound = _bound_retained_frame(session, frame_ref)
    if bound is None:
        return None
    image = cv2.imread(str(bound), cv2.IMREAD_COLOR)
    if image is None or not isinstance(image, np.ndarray):
        return None
    expected = (
        int(_pnsctl().BLUESTACKS_NATIVE_HEIGHT),
        int(_pnsctl().BLUESTACKS_NATIVE_WIDTH),
    )
    if image.shape[:2] != expected:
        return None
    return bound, image


def _normalize_semantic_for_session(
    session: Path, semantic: Mapping[str, Any]
) -> dict[str, Any]:
    normalized = dict(semantic)
    for key in ("item_before_frame", "item_after_frame", "terminal_home_frame"):
        relocated = _relocate_frame_ref_into_session(session, semantic.get(key))
        normalized[key] = relocated
    return normalized


def _reconcile_resource_route(
    *,
    runtime: AuthorizedResourceItemRuntime,
    session: Path,
    route_result: Mapping[str, Any],
    item_use_calls: int,
) -> dict[str, Any] | None:
    """Persist post-transport semantics without acquiring transport authority."""

    prepared = runtime.prepared_effect
    authority = runtime._authority
    if prepared is None or authority is None or item_use_calls <= 0:
        return None
    semantic = _normalize_semantic_for_session(session, _semantic_from_result(route_result))
    before_loaded = _load_bound_native_frame(session, semantic.get("item_before_frame"))
    after_loaded = _load_bound_native_frame(session, semantic.get("item_after_frame"))
    evidence: dict[str, Any] = {
        "observe_only": True,
        "transport_calls": item_use_calls,
        "before_owned_quantity": semantic.get("before_owned_quantity"),
        "after_owned_quantity": semantic.get("after_owned_quantity"),
        "before_food_resource": semantic.get("before_food_resource"),
        "after_food_resource": semantic.get("after_food_resource"),
        "evidence_refs": tuple(
            ref
            for frame in (
                semantic.get("item_before_frame"),
                semantic.get("item_after_frame"),
                semantic.get("terminal_home_frame"),
            )
            if isinstance(frame, Mapping)
            for ref in (
                f"frame-path:{frame.get('path')}",
                f"frame-sha256:{frame.get('sha256')}",
            )
        ),
    }
    confirmed = False
    if before_loaded is not None and after_loaded is not None:
        _, before_image = before_loaded
        _, after_image = after_loaded
        try:
            before_item = recognize_food_item_in_resources(before_image)
            after_item = recognize_food_item_in_resources(after_image)
            before_count = _as_int(
                before_item.inventory_quantity
                if before_item.inventory_quantity is not None
                else before_item.owned_quantity
            )
            after_count = _as_int(
                after_item.inventory_quantity
                if after_item.inventory_quantity is not None
                else after_item.owned_quantity
            )
            confirmed = bool(
                before_count is not None
                and after_count is not None
                and before_count - after_count == 1
                and before_count == _as_int(semantic.get("before_owned_quantity"))
                and after_count == _as_int(semantic.get("after_owned_quantity"))
                and _resource_delta_verified(
                    {
                        "inventory_quantity": before_count,
                        "food_resource": before_item.food_resource,
                    },
                    {
                        "inventory_quantity": after_count,
                        "food_resource": after_item.food_resource,
                    },
                )
            )
            evidence.update(
                {
                    "before_owned_quantity": before_count,
                    "after_owned_quantity": after_count,
                    "before_food_resource": before_item.food_resource,
                    "after_food_resource": after_item.food_resource,
                }
            )
        except Exception:
            confirmed = False
    evidence["effect_state"] = "EFFECT_CONFIRMED" if confirmed else "UNRESOLVED"
    evidence["proven_no_effect"] = False
    reconciled = authority.reconcile_resource_effect_observe_only(
        prepared.reservation_id,
        evidence,
        now=time.monotonic(),
    )
    if confirmed:
        home_ref = semantic.get("terminal_home_frame")
        home_loaded = _load_bound_native_frame(session, home_ref)
        if home_loaded is not None:
            _, home_image = home_loaded
            home = _recognize_home(home_image)
            if home.get("recognized") is True and home.get("home_verified") is True:
                authority.terminal_observation(
                    {
                        "occurrence_id": prepared.occurrence_id,
                        "terminal_state": "HOME_CANONICAL",
                        "frame_sha256": str(home_ref["sha256"]),
                        "evidence_refs": evidence["evidence_refs"],
                    },
                    now=time.monotonic(),
                )
    return dict(reconciled)


def _result_payload(
    result: Mapping[str, Any],
    *,
    session_directory: Path | str,
    input_count: int,
    item_use_calls: int,
    maximum: int,
) -> dict[str, Any]:
    complete = bool(
        result.get("status") == "completed"
        and item_use_calls == MAX_ITEM_USE_TRANSPORT_CALLS
        and result.get("resource_delta_verified") is True
        and result.get("terminal_home_verified") is True
    )
    payload = dict(result)
    payload.update(
        {
            "status": "completed"
            if complete
            else "unresolved"
            if item_use_calls
            else "blocked",
            "flow_id": FLOW_ID,
            "session_directory": str(session_directory),
            "input_count": input_count,
            "max_inputs": maximum,
            "max_resource_list_swipes": MAX_RESOURCE_LIST_SWIPES,
            "item_use_transport_calls": item_use_calls,
            "dispatch": item_use_calls > 0,
            "semantic_evidence": _semantic_from_result(result),
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        }
    )
    return payload


def _write_delivery_result(
    session: Path,
    result: Mapping[str, Any],
    *,
    lease: Mapping[str, Any],
    maximum: int,
) -> None:
    session.mkdir(parents=True, exist_ok=True)
    frames = (
        sorted(
            path.relative_to(session).as_posix()
            for path in (session / "frames").glob("*.png")
            if path.is_file() and not path.is_symlink()
        )
        if (session / "frames").is_dir()
        else []
    )
    payload = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "status": result.get("status"),
        "serial": _pnsctl().BLUESTACKS_SERIAL,
        "native_width": _pnsctl().BLUESTACKS_NATIVE_WIDTH,
        "native_height": _pnsctl().BLUESTACKS_NATIVE_HEIGHT,
        "runtime_owner": str(lease.get("owner") or "pnsctl-development-session"),
        "terminal_runtime_state": (
            "recognized_home"
            if result.get("terminal_home_verified") is True
            else "safe_blocked_terminal"
        ),
        "actions": [
            {
                "action_class": "daily_resource_item_use",
                "path": "home_to_bag_selected_resource_observed_list_1k_food_to_home",
                "outcome": result.get("status"),
            }
        ],
        "frames": frames,
        "required_artifacts": ["events_path"],
        "events_path": "events.jsonl",
        "dispatch": bool(result.get("dispatch")),
        "dispatch_count": int(result.get("input_count") or 0),
        "input_count": int(result.get("input_count") or 0),
        "max_inputs": maximum,
        "max_resource_list_swipes": MAX_RESOURCE_LIST_SWIPES,
        "item_use_transport_calls": int(
            result.get("item_use_transport_calls") or 0
        ),
        "resource_delta_verified": result.get("resource_delta_verified") is True,
        "terminal_home_verified": result.get("terminal_home_verified") is True,
        "semantic_evidence": _normalize_semantic_for_session(
            session, _semantic_from_result(result)
        ),
        "reason": result.get("reason"),
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }
    (session / "flow-delivery-result.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def run_daily_resource_item(
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
    *,
    live: bool = True,
) -> str:
    """Run the route inside pnsctl's already-owned development session."""

    del queue
    maximum = _max_inputs(lease)
    if not live:
        return json.dumps(
            {
                "status": "dry_run",
                "flow_id": FLOW_ID,
                "dispatch": False,
                "input_count": 0,
                "max_inputs": maximum,
                "max_resource_list_swipes": MAX_RESOURCE_LIST_SWIPES,
                "item_use_transport_calls": 0,
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
            },
            sort_keys=True,
        )

    outer_session = _outer_session(lease)
    outer_directory = Path(outer_session.session_directory)
    runtime: LocalBlueStacksRuntime | None = None
    runtime_session = outer_directory
    try:
        pnsctl = _pnsctl()
        runtime = LocalBlueStacksRuntime.connect(
            adb=str(pnsctl.BLUESTACKS_ADB),
            serial=pnsctl.BLUESTACKS_SERIAL,
            output_directory=outer_directory / "runtime",
            workflow=f"daily-resource-item-{_stamp()}",
            execute=True,
        )
        runtime_session = runtime.session
        from scripts import daily_resource_item_bluestacks as route

        runtime_factory = lease.get("resource_runtime_factory")
        if not callable(runtime_factory):
            raise pnsctl.OperatorError(
                "pnsctl did not provide the production Resource runtime factory"
            )
        route_runtime = runtime_factory(runtime)
        if not isinstance(route_runtime, AuthorizedResourceItemRuntime):
            raise pnsctl.OperatorError(
                "pnsctl Resource runtime factory returned an invalid adapter"
            )
        route_result = route.run_daily_resource_item(route_runtime, outer_session)
        item_use_calls = _item_use_calls(runtime_session)
        reconciliation = _reconcile_resource_route(
            runtime=route_runtime,
            session=runtime_session,
            route_result=route_result,
            item_use_calls=item_use_calls,
        )
        input_count = int(getattr(outer_session, "input_count", 0))
        if input_count > maximum:
            raise pnsctl.OperatorError(
                "Daily Resource Item development-session exceeded max_inputs"
            )
        if item_use_calls > MAX_ITEM_USE_TRANSPORT_CALLS:
            raise pnsctl.OperatorError(
                "Daily Resource Item exceeded its one-use ceiling"
            )
        payload = _result_payload(
            route_result,
            session_directory=runtime_session,
            input_count=input_count,
            item_use_calls=item_use_calls,
            maximum=maximum,
        )
        if reconciliation is not None:
            payload["resource_reconciliation"] = reconciliation
    except Exception as exc:
        item_use_calls = _item_use_calls(runtime_session)
        reconciliation = None
        if runtime is not None and isinstance(locals().get("route_runtime"), AuthorizedResourceItemRuntime):
            try:
                reconciliation = _reconcile_resource_route(
                    runtime=route_runtime,
                    session=runtime_session,
                    route_result={
                        "semantic_evidence": {},
                        "status": "unresolved",
                    },
                    item_use_calls=item_use_calls,
                )
            except Exception:
                reconciliation = None
        input_count = int(getattr(outer_session, "input_count", 0))
        payload = _result_payload(
            {
                "status": "unresolved" if item_use_calls else "blocked",
                "reason": f"{type(exc).__name__}: {exc}",
                "resource_delta_verified": False,
                "terminal_home_verified": False,
            },
            session_directory=runtime_session,
            input_count=input_count,
            item_use_calls=item_use_calls,
            maximum=maximum,
        )
        if reconciliation is not None:
            payload["resource_reconciliation"] = reconciliation
    _write_delivery_result(
        runtime_session,
        payload,
        lease=lease,
        maximum=maximum,
    )
    return json.dumps(payload, sort_keys=True, default=str)


def verify_daily_resource_item(
    structure: Mapping[str, Any],
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> dict[str, Any]:
    del queue, lease
    result = structure.get("result")
    if not isinstance(result, Mapping):
        raise _pnsctl().OperatorError(
            "Daily Resource Item delivery result is missing"
        )
    session = Path(str(structure.get("session_directory") or ""))
    events_rel = result.get("events_path") or "events.jsonl"
    try:
        events_file = _pnsctl()._session_relative_path(session, str(events_rel), "events_path")
        item_use_calls = _item_use_calls(events_file.parent)
    except Exception:
        item_use_calls = 0

    semantic = result.get("semantic_evidence")
    if not isinstance(semantic, Mapping):
        semantic = {}

    before_loaded = _load_bound_native_frame(session, semantic.get("item_before_frame"))
    after_loaded = _load_bound_native_frame(session, semantic.get("item_after_frame"))
    home_loaded = _load_bound_native_frame(session, semantic.get("terminal_home_frame"))
    if before_loaded is None or after_loaded is None or home_loaded is None:
        return {
            "status": "evidence_required",
            "flow_id": FLOW_ID,
            "session_directory": structure.get("session_directory"),
            "item_use_transport_calls": item_use_calls,
            "resource_delta_recomputed": False,
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
            "reason": "hash-bound retained frame evidence is missing or mismatched",
        }

    _, before_image = before_loaded
    _, after_image = after_loaded
    _, home_image = home_loaded
    before_item = recognize_food_item_in_resources(before_image)
    after_item = recognize_food_item_in_resources(after_image)
    home = _recognize_home(home_image)
    derived_before = _as_int(
        before_item.inventory_quantity
        if before_item.inventory_quantity is not None
        else before_item.owned_quantity
    )
    derived_after = _as_int(
        after_item.inventory_quantity
        if after_item.inventory_quantity is not None
        else after_item.owned_quantity
    )
    recomputed_delta = _resource_delta_verified(
        {
            "inventory_quantity": derived_before,
            "food_resource": before_item.food_resource,
        },
        {
            "inventory_quantity": derived_after,
            "food_resource": after_item.food_resource,
        },
    )
    persisted_delta = _resource_delta_verified(
        {
            "inventory_quantity": semantic.get("before_owned_quantity"),
            "food_resource": semantic.get("before_food_resource"),
        },
        {
            "inventory_quantity": semantic.get("after_owned_quantity"),
            "food_resource": semantic.get("after_food_resource"),
        },
    )
    persisted_matches = (
        derived_before == _as_int(semantic.get("before_owned_quantity"))
        and derived_after == _as_int(semantic.get("after_owned_quantity"))
    )
    home_ok = bool(
        home.get("home_verified") is True
        and home.get("recognized") is True
        and result.get("terminal_home_verified") is True
        and result.get("terminal_runtime_state") == "recognized_home"
    )
    verified = bool(
        result.get("status") == "completed"
        and item_use_calls == MAX_ITEM_USE_TRANSPORT_CALLS
        and recomputed_delta
        and persisted_delta
        and persisted_matches
        and result.get("resource_delta_verified") is True
        and home_ok
        and result.get("production_registration") == "NOT_REGISTERED"
        and result.get("scheduler_enabled") is False
    )
    return {
        "status": "verified" if verified else "evidence_required",
        "flow_id": FLOW_ID,
        "session_directory": structure.get("session_directory"),
        "item_use_transport_calls": item_use_calls,
        "resource_delta_recomputed": recomputed_delta,
        "owned_before_rederived": derived_before,
        "owned_after_rederived": derived_after,
        "terminal_home_rerecognized": home.get("home_verified") is True,
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }


def recover_daily_resource_item(
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> str:
    del queue, lease
    return json.dumps(
        {
            "status": "blocked",
            "flow_id": FLOW_ID,
            "dispatch": False,
            "reason": "safe no-op recovery; use a fresh recognized conduct session",
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        },
        sort_keys=True,
    )


def register(
    runners: dict[str, Any],
    validators: dict[str, Any],
    handlers: dict[str, Any],
) -> None:
    runners[RUNNER_ID] = run_daily_resource_item
    validators[VALIDATOR_ID] = verify_daily_resource_item
    handlers[RECOVERY_ID] = recover_daily_resource_item
