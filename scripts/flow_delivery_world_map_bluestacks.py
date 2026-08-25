"""Fixed flow-delivery binding for the World-map navigation foundation."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import os
import shutil
from typing import Any, Mapping

import cv2
import numpy as np

from automation_service.registry import (
    RegisteredDispatchSnapshot,
    WORLD_FLOW_ID,
    WORLD_HANDLER_ID,
    WORLD_PHASE_MODE,
    WORLD_PRODUCT_ID,
    WORLD_PRODUCT_REVISION,
    WORLD_PROFILE_ID,
    consume_world_registration,
)
from scripts.bluestacks_native_runtime import (
    NATIVE_HEIGHT,
    NATIVE_WIDTH,
    LocalBlueStacksRuntime,
)
from scripts.world_map_navigation_bluestacks import (
    ALLOWED_CONTROL_IDENTITIES,
    BLOCKED_FAIL_CLOSED,
    FLOW_ID,
    HOME_READY,
    MAX_ROUTE_INPUTS,
    NAVIGATION_ONLY_COMPLETE,
    POPUP_CLOSE,
    RECOVERY_PATH,
    RUNNER_ID,
    RECOVERY_ID,
    SEARCH_ENTRY_ONLY_PATH,
    FULL_ROUTE_PATH,
    VALIDATOR_ID,
    recover_world_map_home,
    run_world_map_navigation,
    run_world_map_search_entry_only,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
_HASH_RE = r"^[0-9a-f]{64}$"
_FORBIDDEN_MARKERS = (
    "gather",
    "resource",
    "march",
    "combat",
    "attack",
    "stamina",
    "ap",
    "formation",
    "troop",
    "purchase",
    "payment",
)
_OVERLAY_ABSENT = frozenset({"none", "none_observed", ""})


def _is_diagnostic_route(route: Mapping[str, Any]) -> bool:
    """Return whether the retained route is the one-input search diagnostic."""

    return str(route.get("path") or "") == SEARCH_ENTRY_ONLY_PATH


def _pnsctl():
    from scripts import pnsctl

    return pnsctl


_WORLD_REGISTRATION_SNAPSHOT_FIELDS = frozenset(
    {
        "flow_id",
        "product_id",
        "product_revision",
        "production_handler",
        "profile",
        "mode",
        "registration_status",
        "scheduler_eligible",
    }
)
_WORLD_REGISTRATION_SNAPSHOT = {
    "flow_id": WORLD_FLOW_ID,
    "product_id": WORLD_PRODUCT_ID,
    "product_revision": WORLD_PRODUCT_REVISION,
    "production_handler": WORLD_HANDLER_ID,
    "profile": WORLD_PROFILE_ID,
    "mode": WORLD_PHASE_MODE,
    "registration_status": "REGISTERED",
    "scheduler_eligible": True,
}


def _validated_registration_snapshot(value: object) -> dict[str, Any]:
    if isinstance(value, RegisteredDispatchSnapshot):
        value = value.to_mapping()
    if (
        not isinstance(value, Mapping)
        or set(value) != _WORLD_REGISTRATION_SNAPSHOT_FIELDS
    ):
        raise _pnsctl().OperatorError(
            "World navigation dispatch registration snapshot is incomplete"
        )
    snapshot = dict(value)
    if snapshot != _WORLD_REGISTRATION_SNAPSHOT:
        raise _pnsctl().OperatorError(
            "World navigation dispatch registration snapshot is not the fixed World binding"
        )
    return snapshot


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _maximum_inputs(lease: Mapping[str, Any]) -> int:
    value = lease.get(
        "max_inputs", os.environ.get("PNS_DEVELOPMENT_MAX_INPUTS", MAX_ROUTE_INPUTS)
    )
    try:
        maximum = int(value)
    except (TypeError, ValueError) as exc:
        raise _pnsctl().OperatorError(
            "World navigation max_inputs must be an integer"
        ) from exc
    if not 1 <= maximum <= MAX_ROUTE_INPUTS:
        raise _pnsctl().OperatorError(
            "World navigation max_inputs must be between 1 and 20"
        )
    return maximum


def _outer_session(lease: Mapping[str, Any]) -> Any:
    from scripts.navigation_development_boundary import DevelopmentSession

    session = lease.get("development_session")
    if (
        not isinstance(session, DevelopmentSession)
        or session.is_active is not True
        or str(session.owner) != f"pnsctl-development-session:{FLOW_ID}"
        or not callable(getattr(session, "run_action", None))
    ):
        raise _pnsctl().OperatorError(
            "World navigation requires the active pnsctl-owned DevelopmentSession"
        )
    return session


def _initial_observation(lease: Mapping[str, Any], session: Any) -> dict[str, Any]:
    from scripts.navigation_development_boundary import DevelopmentInitialObservation

    value = lease.get("initial_observation")
    bound = session.initial_observation
    if not isinstance(value, DevelopmentInitialObservation):
        raise _pnsctl().OperatorError(
            "World navigation initial observation must be typed session evidence"
        )
    if not isinstance(bound, DevelopmentInitialObservation) or value is not bound:
        raise _pnsctl().OperatorError(
            "World navigation initial observation is not exactly session-bound"
        )
    digest = str(value.frame_sha256 or "")
    if (
        len(digest) != 64
        or digest != str(lease.get("initial_frame_sha256") or "")
        or value.invocation_id != session.invocation_id
    ):
        raise _pnsctl().OperatorError(
            "World navigation initial observation hash or invocation binding is invalid"
        )
    return value.to_mapping()


def _write_read_only_causal_trace(
    session: Path,
    *,
    route: Mapping[str, Any],
    initial_observation: Mapping[str, Any],
    registration_snapshot: object | None = None,
) -> dict[str, Any]:
    events = _read_events(session / "events.jsonl")
    transport_count = sum(
        1
        for event in events
        if event.get("type") == "dispatch" and event.get("execute") is not False
    )
    diagnostic = _is_diagnostic_route(route)
    trace = {
        "schema_version": 1,
        "trace_count": 1,
        "read_only": True,
        "input_authority": False,
        "stages": [
            "observation",
            "intent",
            "transport",
            "settled_successor",
            "semantic_result",
            "terminal_result",
        ],
        "proof_topology": "diagnostic" if diagnostic else "continuous",
        "flow_id": FLOW_ID,
        "invocation_id": str(initial_observation.get("invocation_id") or ""),
        "initial_frame_sha256": str(initial_observation.get("frame_sha256") or ""),
        "transport_count": transport_count,
        "event_count": len(events),
        "status": str(route.get("status") or "unknown"),
        "effect_classes": [],
    }
    if registration_snapshot is not None:
        snapshot = _validated_registration_snapshot(registration_snapshot)
        trace["registration_snapshot"] = snapshot
        trace["dispatch_registration"] = dict(snapshot)
    if diagnostic:
        trace["acceptance_eligible"] = False
    _write_json(session / "causal-trace.json", trace)
    return trace


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _native_frames(session: Path) -> list[str]:
    frames = sorted(
        path
        for path in (session / "frames").glob("*.png")
        if path.is_file() and not path.is_symlink()
    )
    if not frames:
        raise _pnsctl().OperatorError(
            "World navigation route produced no native frame evidence"
        )
    return [path.relative_to(session).as_posix() for path in frames]


def _read_events(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise _pnsctl().OperatorError("World navigation events.jsonl is missing")
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise _pnsctl().OperatorError("World navigation event is not an object")
        rows.append(value)
    if not rows:
        raise _pnsctl().OperatorError("World navigation events.jsonl is empty")
    return rows


def _run_result(
    route: Mapping[str, Any],
    *,
    session: Path,
    lease: Mapping[str, Any],
    operator_returncode: int,
    recovery_only: bool = False,
    initial_observation: Mapping[str, Any] | None = None,
    causal_trace: Mapping[str, Any] | None = None,
    registration_snapshot: object | None = None,
) -> dict[str, Any]:
    frames = _native_frames(session)
    snapshot = (
        _validated_registration_snapshot(registration_snapshot)
        if registration_snapshot is not None
        else None
    )
    status = str(route.get("status") or BLOCKED_FAIL_CLOSED)
    diagnostic = _is_diagnostic_route(route)
    delivery_status = "completed" if status == NAVIGATION_ONLY_COMPLETE else "blocked"
    path = str(
        route.get("path") or (RECOVERY_PATH if recovery_only else FULL_ROUTE_PATH)
    )
    delivery = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "status": delivery_status,
        "serial": _pnsctl().BLUESTACKS_SERIAL,
        "native_width": NATIVE_WIDTH,
        "native_height": NATIVE_HEIGHT,
        "runtime_owner": str(lease.get("owner") or "pnsctl-development-session"),
        "terminal_runtime_state": (
            str(route.get("terminal_runtime_state") or HOME_READY)
            if delivery_status == "completed"
            else "safe_blocked_terminal"
        ),
        "actions": [
            {
                "action_class": "navigation_only",
                "path": path,
                "outcome": status,
            }
        ],
        "required_artifacts": ["events_path"],
        "events_path": "events.jsonl",
        "ledger_path": None,
        "capability_audit_path": None,
        "journal_path": None,
        "frames": frames,
        "world_navigation_result": dict(route),
        "path": path,
        "dispatch": int(route.get("input_count") or 0) > 0,
        "dispatch_count": int(route.get("input_count") or 0),
        "input_count": int(route.get("input_count") or 0),
        "navigation_input_count": int(route.get("navigation_input_count") or 0),
        "safe_popup_input_count": int(route.get("safe_popup_input_count") or 0),
        "operator_returncode": operator_returncode,
        "production_registration": (
            "REGISTERED" if snapshot is not None else "NOT_REGISTERED"
        ),
        "scheduler_enabled": False,
        "resource_actions": 0,
        "combat_actions": 0,
        "node_inputs": 0,
        "resource_node_selection_inputs": 0,
        "march_inputs": 0,
        "formation_inputs": 0,
        "occupancy_override_inputs": 0,
        "stamina_inputs": 0,
        "ap_inputs": 0,
        "currency_inputs": 0,
        "forbidden_input_classes": [],
        "proof_topology": "diagnostic" if diagnostic else "continuous",
        "initial_observation": dict(initial_observation or {}),
        "initial_frame_sha256": str(
            (initial_observation or {}).get("frame_sha256") or ""
        ),
        "causal_trace_count": 1 if causal_trace is not None else 0,
        "causal_trace": dict(causal_trace or {}),
    }
    if snapshot is not None:
        delivery["registration_snapshot"] = dict(snapshot)
        delivery["dispatch_registration"] = dict(snapshot)
    if diagnostic:
        delivery["acceptance_eligible"] = False
    _write_json(session / "flow-delivery-result.json", delivery)
    return delivery


def run_world_map_navigation_foundation(
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
    *,
    live: bool = True,
) -> str:
    """Run one bounded navigation-only session; dry-run never connects ADB."""

    del queue
    pnsctl = _pnsctl()
    recovery_only = bool(lease.get("recovery_only"))
    search_entry_only = bool(lease.get("search_entry_only"))
    if recovery_only and search_entry_only:
        raise pnsctl.OperatorError(
            "World navigation recovery-only and search-entry-only are mutually exclusive"
        )
    maximum = 1 if search_entry_only else _maximum_inputs(lease)
    root = pnsctl.BLUESTACKS_ARTIFACT_ROOT / FLOW_ID / f"run-{_stamp()}"
    root.mkdir(parents=True, exist_ok=False)
    if not live:
        diagnostic = search_entry_only
        result = {
            "status": "dry_run",
            "flow_id": FLOW_ID,
            "dispatch": False,
            "dispatch_count": 0,
            "input_count": 0,
            "navigation_input_count": 0,
            "safe_popup_input_count": 0,
            "resource_actions": 0,
            "combat_actions": 0,
            "node_inputs": 0,
            "resource_node_selection_inputs": 0,
            "march_inputs": 0,
            "formation_inputs": 0,
            "occupancy_override_inputs": 0,
            "stamina_inputs": 0,
            "ap_inputs": 0,
            "currency_inputs": 0,
            "forbidden_input_classes": [],
            "max_inputs": maximum,
            "path": (
                SEARCH_ENTRY_ONLY_PATH
                if search_entry_only
                else RECOVERY_PATH
                if recovery_only
                else FULL_ROUTE_PATH
            ),
            "proof_topology": "diagnostic" if diagnostic else "composite",
            "causal_trace_count": 0,
            "session_directory": str(root),
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        }
        if diagnostic:
            result["acceptance_eligible"] = False
        _write_json(root / "dry-run-result.json", result)
        return json.dumps(result, sort_keys=True)

    outer_session = _outer_session(lease)
    initial_observation = _initial_observation(lease, outer_session)
    registration_snapshot: dict[str, Any] | None = None
    if live and not recovery_only and not search_entry_only:
        provided_snapshot = lease.get("registration_snapshot")
        if provided_snapshot is None:
            consumed = consume_world_registration()
            if consumed is None:
                raise pnsctl.OperatorError(
                    "WORLD_NAVIGATION_REGISTRATION_ALREADY_CONSUMED"
                )
            provided_snapshot = consumed
        if not isinstance(provided_snapshot, RegisteredDispatchSnapshot):
            raise pnsctl.OperatorError(
                "World navigation requires the atomically consumed registration snapshot"
            )
        registration_snapshot = _validated_registration_snapshot(provided_snapshot)
        lease = dict(lease)
        lease["registration_snapshot"] = registration_snapshot
    try:
        runtime = LocalBlueStacksRuntime.connect(
            adb=str(pnsctl.BLUESTACKS_ADB),
            serial=pnsctl.BLUESTACKS_SERIAL,
            output_directory=root,
            workflow="world-map-navigation",
            execute=True,
        )
        route = (
            recover_world_map_home(runtime, maximum_inputs=maximum)
            if recovery_only
            else run_world_map_search_entry_only(
                runtime,
                maximum_inputs=maximum,
            )
            if search_entry_only
            else run_world_map_navigation(
                runtime,
                maximum_inputs=maximum,
                maximum_popup_inputs=min(4, maximum),
            )
        )
        session = runtime.session
        source_path = Path(str(outer_session.session_directory)) / "source.png"
        if source_path.is_file():
            retained_initial = session / "frames" / "0000-initial-observation.png"
            retained_initial.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, retained_initial)
            initial_observation["frame_path"] = "frames/0000-initial-observation.png"
        retained_events = _read_events(session / "events.jsonl")
        retained_keys: set[str] = set()
        retained_count = 0
        for event in retained_events:
            if event.get("type") != "dispatch" or event.get("execute") is False:
                continue
            identity = str(
                event.get("action_key")
                or f"{event.get('source_sha256', '')}:{event.get('target_identity', '')}:{retained_count}"
            )
            if identity in retained_keys:
                raise pnsctl.OperatorError(
                    "World navigation retained transport is duplicated"
                )
            retained_keys.add(identity)
            retained_count += 1
        if int(route.get("input_count") or 0) != retained_count:
            raise pnsctl.OperatorError(
                "World navigation route count does not match retained transports"
            )
        if hasattr(outer_session, "adopt_retained_transport_count"):
            outer_session.adopt_retained_transport_count(
                retained_count,
                source="runtime_session/events.jsonl",
            )
        elif int(getattr(outer_session, "input_count", 0)) != retained_count:
            raise pnsctl.OperatorError(
                "World navigation input count does not match retained transports"
            )
        causal_trace = _write_read_only_causal_trace(
            session,
            route=route,
            initial_observation=initial_observation,
            registration_snapshot=registration_snapshot,
        )
        if hasattr(outer_session, "set_causal_trace"):
            outer_session.set_causal_trace(causal_trace)
            outer_session.remember_control("world_route_status", route.get("status"))
            route_events = route.get("route_events")
            if isinstance(route_events, list):
                outer_session.remember_control(
                    "target_history",
                    [
                        str(event.get("target_identity") or "")
                        for event in route_events
                        if isinstance(event, Mapping) and event.get("target_identity")
                    ],
                )
            outer_session.remember_control(
                "recovery_result",
                route.get("reason")
                if route.get("status") != NAVIGATION_ONLY_COMPLETE
                else "terminal_home_verified",
            )
        delivery = _run_result(
            route,
            session=session,
            lease=lease,
            operator_returncode=0,
            recovery_only=recovery_only,
            initial_observation=initial_observation,
            causal_trace=causal_trace,
            registration_snapshot=registration_snapshot,
        )
    except Exception:
        # Do not invent a successful route result after a transport or capture
        # failure.  The parent development-session wrapper records the failure.
        raise
    result = {
        "status": delivery["status"],
        "flow_id": FLOW_ID,
        "session_directory": str(session),
        "dispatch": delivery["dispatch"],
        "dispatch_count": delivery["dispatch_count"],
        "navigation_input_count": delivery["navigation_input_count"],
        "safe_popup_input_count": delivery["safe_popup_input_count"],
        "reason": route.get("reason"),
        "path": route.get("path"),
        "terminal_runtime_state": delivery["terminal_runtime_state"],
        "proof_topology": delivery.get("proof_topology"),
        "initial_observation": delivery.get("initial_observation"),
        "initial_frame_sha256": delivery.get("initial_frame_sha256"),
        "causal_trace_count": delivery.get("causal_trace_count"),
        "causal_trace": delivery.get("causal_trace"),
        "production_registration": delivery.get("production_registration"),
        "scheduler_enabled": delivery.get("scheduler_enabled"),
    }
    if "registration_snapshot" in delivery:
        result["registration_snapshot"] = dict(delivery["registration_snapshot"])
        result["dispatch_registration"] = dict(delivery["registration_snapshot"])
    if "acceptance_eligible" in delivery:
        result["acceptance_eligible"] = delivery["acceptance_eligible"]
    return json.dumps(result, sort_keys=True)


def _hash_native(path: Path) -> str:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.shape[:2] != (NATIVE_HEIGHT, NATIVE_WIDTH):
        raise _pnsctl().OperatorError(
            "World navigation evidence is not native 800x1280 PNG"
        )
    return digest


def _valid_native_roi(value: object) -> bool:
    try:
        x0, y0, x1, y1 = tuple(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return bool(
        all(type(item) is int for item in (x0, y0, x1, y1))
        and 0 <= x0 < x1 <= NATIVE_WIDTH
        and 0 <= y0 < y1 <= NATIVE_HEIGHT
    )


def _capture_identity(event: Mapping[str, Any]) -> tuple[str, str, str]:
    path = str(event.get("path") or event.get("capture_path") or "")
    session = str(event.get("capture_session") or "")
    ordinal = str(event.get("capture_ordinal") or "")
    if path:
        path_object = Path(path)
        if not session:
            session = str(path_object.parent.parent)
        if not ordinal:
            ordinal = path_object.name.split("-", 1)[0]
    digest = str(event.get("capture_frame_sha256") or event.get("sha256") or "")
    return session.replace("\\", "/"), ordinal, digest


def _verify_route_result(
    result: Mapping[str, Any], session: Path
) -> tuple[list[dict[str, Any]], set[str]]:
    route = result.get("world_navigation_result")
    if not isinstance(route, Mapping):
        raise _pnsctl().OperatorError("World navigation semantic result is missing")
    if route.get("flow_id") != FLOW_ID:
        raise _pnsctl().OperatorError(
            "World navigation semantic result identity mismatch"
        )
    for result_key, route_key in (
        ("dispatch_count", "input_count"),
        ("input_count", "input_count"),
        ("navigation_input_count", "navigation_input_count"),
        ("safe_popup_input_count", "safe_popup_input_count"),
    ):
        if result.get(result_key) != route.get(route_key):
            raise _pnsctl().OperatorError(
                f"World navigation delivery/result metric mismatch: {result_key}"
            )
    for key in (
        "resource_actions",
        "combat_actions",
        "node_inputs",
        "resource_node_selection_inputs",
        "march_inputs",
        "formation_inputs",
        "occupancy_override_inputs",
        "stamina_inputs",
        "ap_inputs",
        "currency_inputs",
    ):
        if result.get(key) != 0 or route.get(key) != 0:
            raise _pnsctl().OperatorError(
                f"World navigation forbidden metric is nonzero: {key}"
            )
    if (
        result.get("forbidden_input_classes") != []
        or route.get("forbidden_input_classes") != []
    ):
        raise _pnsctl().OperatorError("World navigation forbidden classes are nonempty")
    frame_refs = result.get("frames")
    if not isinstance(frame_refs, list) or not frame_refs:
        raise _pnsctl().OperatorError("World navigation native frames are required")
    hashes: set[str] = set()
    for ref in frame_refs:
        if not isinstance(ref, str) or Path(ref).is_absolute():
            raise _pnsctl().OperatorError(
                "World navigation frame reference is not relative"
            )
        path = (session / ref).resolve()
        try:
            path.relative_to(session.resolve())
        except ValueError as exc:
            raise _pnsctl().OperatorError(
                "World navigation frame escaped session"
            ) from exc
        if path.is_symlink() or not path.is_file():
            raise _pnsctl().OperatorError("World navigation frame is missing or unsafe")
        hashes.add(_hash_native(path))
    events = _read_events(session / str(result.get("events_path") or "events.jsonl"))
    return events, hashes


def _verify_event_order(
    events: list[dict[str, Any]],
    route: Mapping[str, Any],
    frame_hashes: set[str],
) -> list[dict[str, Any]]:
    captures: list[tuple[int, dict[str, Any]]] = []
    dispatches: list[tuple[int, dict[str, Any]]] = []
    for index, event in enumerate(events):
        kind = event.get("type")
        if kind == "capture":
            digest = event.get("sha256")
            if not isinstance(digest, str) or digest not in frame_hashes:
                raise _pnsctl().OperatorError(
                    "World navigation capture hash is not retained"
                )
            captures.append((index, event))
        elif kind == "dispatch":
            dispatches.append((index, event))
        elif kind == "semantic":
            identity = str(event.get("target_identity") or "")
            if any(marker in identity.casefold() for marker in _FORBIDDEN_MARKERS):
                raise _pnsctl().OperatorError(
                    "forbidden semantic target identity in events"
                )

    seen_actions: set[str] = set()
    seen_captures: set[tuple[str, str, str]] = set()
    for dispatch_index, dispatch in dispatches:
        source = dispatch.get("source_sha256")
        action_key = str(dispatch.get("action_key") or "")
        identity = str(dispatch.get("target_identity") or "")
        if (
            not isinstance(source, str)
            or source not in frame_hashes
            or not action_key
            or action_key in seen_actions
        ):
            raise _pnsctl().OperatorError(
                "World navigation dispatch reuses an action or stale source"
            )
        seen_actions.add(action_key)
        prepared_for_identity = [
            event
            for event in events
            if event.get("type") == "semantic"
            and event.get("action_key") == action_key
            and event.get("event") in {"navigation_prepared", "safe_popup_prepared"}
        ]
        if len(prepared_for_identity) != 1:
            raise _pnsctl().OperatorError(
                "World navigation prepare identity is missing"
            )
        capture_identity = _capture_identity(prepared_for_identity[0])
        if capture_identity in seen_captures:
            raise _pnsctl().OperatorError(
                "World navigation reuses a stale capture identity"
            )
        seen_captures.add(capture_identity)
        if identity not in ALLOWED_CONTROL_IDENTITIES and identity != "android-back":
            raise _pnsctl().OperatorError(
                f"World navigation target identity is not allowlisted: {identity}"
            )
        if any(marker in identity.casefold() for marker in _FORBIDDEN_MARKERS):
            raise _pnsctl().OperatorError(
                "forbidden resource/combat identity in events"
            )
        if identity != "android-back" and not _valid_native_roi(
            dispatch.get("target_roi")
        ):
            raise _pnsctl().OperatorError(
                "World navigation dispatch lacks an exact native target ROI"
            )
        if dispatch.get("consequential") is True:
            raise _pnsctl().OperatorError(
                "navigation route contains consequential input"
            )
        _verify_dispatch_chain(events, captures, dispatch_index, dispatch, frame_hashes)

    declared = route.get("input_count")
    if type(declared) is not int or declared != len(dispatches):
        raise _pnsctl().OperatorError(
            "World navigation input count does not match events"
        )
    popup_count = sum(
        1 for _index, event in dispatches if event.get("target_identity") == POPUP_CLOSE
    )
    if route.get("safe_popup_input_count") != popup_count:
        raise _pnsctl().OperatorError(
            "World navigation popup count does not match events"
        )
    if route.get("navigation_input_count") != len(dispatches) - popup_count:
        raise _pnsctl().OperatorError(
            "World navigation navigation count does not match events"
        )
    if (
        type(route.get("safe_popup_input_count")) is not int
        or not 0 <= route["safe_popup_input_count"] <= 4
        or type(route.get("max_inputs")) is not int
        or route["input_count"] > route["max_inputs"]
    ):
        raise _pnsctl().OperatorError(
            "World navigation input budget accounting is invalid"
        )
    zero_metrics = (
        "resource_actions",
        "combat_actions",
        "node_inputs",
        "resource_node_selection_inputs",
        "march_inputs",
        "formation_inputs",
        "occupancy_override_inputs",
        "stamina_inputs",
        "ap_inputs",
        "currency_inputs",
    )
    if any(route.get(metric) != 0 for metric in zero_metrics):
        raise _pnsctl().OperatorError(
            "World navigation forbidden input accounting is nonzero"
        )
    if route.get("forbidden_input_classes") != []:
        raise _pnsctl().OperatorError(
            "World navigation reports forbidden input classes"
        )

    navigation = [
        event
        for _index, event in dispatches
        if event.get("target_identity") != POPUP_CLOSE
    ]
    reconciled = {
        str(event.get("action_key")): event
        for event in events
        if event.get("type") == "semantic"
        and event.get("event") == "navigation_reconciled"
    }
    transitions: list[dict[str, Any]] = []
    for dispatch in navigation:
        transition = reconciled.get(str(dispatch.get("action_key")))
        if transition is None:
            raise _pnsctl().OperatorError(
                "World navigation input lacks semantic successor reconciliation"
            )
        transitions.append(transition)
    if route.get("status") == NAVIGATION_ONLY_COMPLETE:
        route_path = str(route.get("path") or FULL_ROUTE_PATH)
        contracts = {
            FULL_ROUTE_PATH: (
                [
                    "home-to-world",
                    "world-search-entry",
                    "android-back",
                    "world-to-home",
                ],
                HOME_READY,
            ),
            RECOVERY_PATH: (["world-to-home"], HOME_READY),
            SEARCH_ENTRY_ONLY_PATH: (["world-search-entry"], "WORLD_SEARCH_OPEN"),
        }
        if route_path not in contracts:
            raise _pnsctl().OperatorError("World navigation route path is unsupported")
        expected, terminal_state = contracts[route_path]
        if (
            route_path in {RECOVERY_PATH, SEARCH_ENTRY_ONLY_PATH}
            and route.get("safe_popup_input_count") != 0
        ):
            raise _pnsctl().OperatorError(
                "World navigation bounded route contains popup input"
            )
        actual_path = [str(item.get("target_identity")) for item in transitions]
        expected_paths = (
            (expected, ["android-back", "world-to-home"])
            if route_path == RECOVERY_PATH
            else (expected,)
        )
        if actual_path not in expected_paths:
            raise _pnsctl().OperatorError(
                "World navigation dispatch order is not canonical"
            )
        terminal = [
            (index, event)
            for index, event in enumerate(events)
            if event.get("type") == "semantic"
            and event.get("event") == "route_terminal"
        ]
        if len(terminal) != 1:
            raise _pnsctl().OperatorError(
                "World navigation terminal event is missing or duplicated"
            )
        terminal_index, terminal_event = terminal[0]
        if terminal_index <= max(
            index
            for index, event in enumerate(events)
            if event.get("type") == "semantic"
            and event.get("event") == "navigation_reconciled"
        ):
            raise _pnsctl().OperatorError(
                "World navigation terminal event is out of order"
            )
        if (
            terminal_event.get("state") != terminal_state
            or terminal_event.get("overlay_state") not in _OVERLAY_ABSENT
            or terminal_event.get("frame_sha256") != route.get("final_frame_sha256")
            or route.get("final_overlay_state") not in _OVERLAY_ABSENT
        ):
            raise _pnsctl().OperatorError(
                "World navigation HOME_READY terminal proof is inconsistent"
            )
        terminal_hash = terminal_event.get("frame_sha256")
        terminal_captures = [
            (index, event)
            for index, event in captures
            if event.get("sha256") == terminal_hash and index < terminal_index
        ]
        if terminal_hash not in frame_hashes or not terminal_captures:
            raise _pnsctl().OperatorError(
                "World navigation terminal frame is not retained"
            )
    return transitions


def _verify_dispatch_chain(
    events: list[dict[str, Any]],
    captures: list[tuple[int, dict[str, Any]]],
    dispatch_index: int,
    dispatch: Mapping[str, Any],
    frame_hashes: set[str],
) -> None:
    action_key = str(dispatch.get("action_key") or "")
    source = str(dispatch.get("source_sha256") or "")
    identity = str(dispatch.get("target_identity") or "")
    semantic = [
        (index, event)
        for index, event in enumerate(events)
        if event.get("type") == "semantic" and event.get("action_key") == action_key
    ]
    prepared = [
        item
        for item in semantic
        if item[1].get("event") in {"navigation_prepared", "safe_popup_prepared"}
    ]
    planned = [
        item
        for item in semantic
        if item[1].get("event") in {"navigation_planned", "safe_popup_planned"}
    ]
    if len(prepared) != 1 or len(planned) != 1:
        raise _pnsctl().OperatorError(
            "World navigation dispatch lacks one planning/prepare chain"
        )
    prepared_index, prepared_event = prepared[0]
    if planned:
        plan_index, plan_event = planned[0]
        if not plan_index < prepared_index < dispatch_index:
            raise _pnsctl().OperatorError("World navigation planning order is invalid")
        if plan_event.get("source_frame_sha256") != source:
            raise _pnsctl().OperatorError("World navigation plan uses a stale source")
    else:
        plan_event = prepared_event
    if not prepared_index < dispatch_index:
        raise _pnsctl().OperatorError("World navigation prepare follows dispatch")
    if prepared_event.get("source_frame_sha256") != source:
        raise _pnsctl().OperatorError("World navigation prepare uses a stale source")
    if identity != POPUP_CLOSE and prepared_event.get("target_roi") != dispatch.get(
        "target_roi"
    ):
        raise _pnsctl().OperatorError(
            "World navigation target changed after preparation"
        )
    if identity == POPUP_CLOSE:
        popup_evidence = prepared_event.get("popup_semantic_evidence") or ()
        if (
            prepared_event.get("popup_contract_version")
            != "vip-points-get-pts-close-v1"
            or prepared_event.get("target_geometry_source")
            != "current-frame-bounded-candidate"
            or prepared_event.get("popup_context_state")
            != prepared_event.get("expected_successor_state")
            or not all(
                any(
                    marker.casefold() in str(item).casefold() for item in popup_evidence
                )
                for marker in ("Get Pts", "VIP pts", "Close")
            )
            or prepared_event.get("target_roi") != dispatch.get("target_roi")
        ):
            raise _pnsctl().OperatorError(
                "World navigation popup semantic evidence is invalid"
            )
    source_captures = [
        (index, event)
        for index, event in captures
        if event.get("sha256") == source and index < prepared_index
    ]
    prepared_capture_identity = _capture_identity(prepared_event)
    if (
        prepared_capture_identity[0]
        and prepared_capture_identity[1]
        and prepared_capture_identity[2] == source
    ):
        source_captures = [
            (index, event)
            for index, event in source_captures
            if _capture_identity(event) == prepared_capture_identity
        ]
    if len(source_captures) != 1:
        raise _pnsctl().OperatorError(
            "World navigation source capture is stale or duplicated"
        )
    source_index, source_event = source_captures[0]
    if any(
        index > source_index
        and index < prepared_index
        and event.get("type") == "capture"
        for index, event in enumerate(events)
    ):
        raise _pnsctl().OperatorError(
            "World navigation source is not the fresh immediate-before"
        )
    for key in ("capture_session", "capture_ordinal", "capture_frame_sha256"):
        if key in prepared_event and key == "capture_frame_sha256":
            if prepared_event[key] != source:
                raise _pnsctl().OperatorError(
                    "World navigation capture identity is inconsistent"
                )
        if key in prepared_event and key in source_event:
            if prepared_event[key] != source_event[key]:
                raise _pnsctl().OperatorError(
                    "World navigation session/ordinal is inconsistent"
                )

    if identity == POPUP_CLOSE:
        reconciled_name = "safe_popup_reconciled"
    else:
        reconciled_name = "navigation_reconciled"
    reconciled = [
        (index, event)
        for index, event in semantic
        if event.get("event") == reconciled_name
    ]
    if len(reconciled) != 1:
        raise _pnsctl().OperatorError(
            "World navigation semantic reconcile is missing or duplicated"
        )
    reconcile_index, reconcile_event = reconciled[0]
    if reconcile_index <= dispatch_index:
        raise _pnsctl().OperatorError("World navigation reconcile precedes dispatch")
    post_key = (
        "post_frame_sha256"
        if identity == POPUP_CLOSE
        else "immediate_post_frame_sha256"
    )
    post_hash = reconcile_event.get(post_key)
    if not isinstance(post_hash, str) or post_hash not in frame_hashes:
        raise _pnsctl().OperatorError(
            "World navigation immediate post capture is missing"
        )
    post_captures = [
        (index, event)
        for index, event in captures
        if event.get("sha256") == post_hash and dispatch_index < index < reconcile_index
    ]
    reconcile_capture_identity = _capture_identity(reconcile_event)
    if (
        reconcile_capture_identity[0]
        and reconcile_capture_identity[1]
        and reconcile_capture_identity[2] == post_hash
    ):
        post_captures = [
            (index, event)
            for index, event in post_captures
            if _capture_identity(event) == reconcile_capture_identity
        ]
    if len(post_captures) != 1:
        raise _pnsctl().OperatorError(
            "World navigation post capture is stale or missing"
        )
    runtime_reconciles = [
        (index, event)
        for index, event in enumerate(events)
        if event.get("type") == "reconcile" and event.get("action_key") == action_key
    ]
    if len(runtime_reconciles) != 1 or runtime_reconciles[0][0] >= reconcile_index:
        raise _pnsctl().OperatorError(
            "World navigation transport reconciliation is missing"
        )
    runtime_event = runtime_reconciles[0][1]
    expected_post = (
        reconcile_event.get("successor_frame_sha256")
        if identity != POPUP_CLOSE
        else reconcile_event.get("post_frame_sha256")
    )
    if (
        runtime_event.get("status") != "confirmed"
        or runtime_event.get("post_sha256") != expected_post
    ):
        raise _pnsctl().OperatorError(
            "World navigation post hash is not exactly reconciled"
        )
    if identity == POPUP_CLOSE and (
        reconcile_event.get("popup_absent_verified") is not True
        or not reconcile_event.get("successor_state")
    ):
        raise _pnsctl().OperatorError(
            "World navigation popup dismissal lacks successor proof"
        )


def _verify_popup_successors(
    events: list[dict[str, Any]],
    route: Mapping[str, Any],
    frame_hashes: set[str],
) -> None:
    popup_dispatches = [
        event
        for event in events
        if event.get("type") == "dispatch"
        and event.get("target_identity") == POPUP_CLOSE
    ]
    if len(popup_dispatches) != route.get("safe_popup_input_count"):
        raise _pnsctl().OperatorError(
            "World navigation popup dispatch accounting is inconsistent"
        )
    for event in popup_dispatches:
        action_key = str(event.get("action_key") or "")
        reconciled = [
            row
            for row in events
            if row.get("type") == "semantic"
            and row.get("event") == "safe_popup_reconciled"
            and row.get("action_key") == action_key
        ]
        if (
            len(reconciled) != 1
            or reconciled[0].get("popup_absent_verified") is not True
        ):
            raise _pnsctl().OperatorError(
                "World navigation popup lacks verified dismissal successor evidence"
            )


def _verify_registration_evidence(
    result: Mapping[str, Any],
    trace: Mapping[str, Any],
) -> None:
    result_snapshot = result.get("registration_snapshot")
    result_dispatch = result.get("dispatch_registration")
    trace_snapshot = trace.get("registration_snapshot")
    trace_dispatch = trace.get("dispatch_registration")
    if result.get("production_registration") == "REGISTERED":
        if result_snapshot is None and result_dispatch is None:
            raise _pnsctl().OperatorError(
                "World navigation dispatch registration snapshot is missing"
            )
        if trace_snapshot is None and trace_dispatch is None:
            raise _pnsctl().OperatorError(
                "World navigation causal trace registration snapshot is missing"
            )
        validated = _validated_registration_snapshot(
            result_snapshot if result_snapshot is not None else result_dispatch
        )
        if result_snapshot is not None:
            _validated_registration_snapshot(result_snapshot)
        if result_dispatch is not None:
            if _validated_registration_snapshot(result_dispatch) != validated:
                raise _pnsctl().OperatorError(
                    "World navigation result registration aliases disagree"
                )
        if (
            trace_snapshot is not None
            and _validated_registration_snapshot(trace_snapshot) != validated
        ):
            raise _pnsctl().OperatorError(
                "World navigation result and causal trace registration disagree"
            )
        if (
            trace_dispatch is not None
            and _validated_registration_snapshot(trace_dispatch) != validated
        ):
            raise _pnsctl().OperatorError(
                "World navigation result and causal trace registration disagree"
            )
        if (
            trace_snapshot is not None
            and trace_dispatch is not None
            and trace_snapshot != trace_dispatch
        ):
            raise _pnsctl().OperatorError(
                "World navigation causal trace registration aliases disagree"
            )
        return
    if (
        result_snapshot is not None
        or result_dispatch is not None
        or trace_snapshot is not None
        or trace_dispatch is not None
    ):
        raise _pnsctl().OperatorError(
            "World navigation retained registration evidence is forged or partial"
        )
    if result.get("production_registration") != "NOT_REGISTERED":
        raise _pnsctl().OperatorError(
            "World navigation production registration status is invalid"
        )


def _verify_route_semantics(
    result: Mapping[str, Any],
    events: list[dict[str, Any]],
) -> None:
    route = result["world_navigation_result"]
    transitions = [
        item
        for item in events
        if item.get("type") == "semantic"
        and item.get("event") == "navigation_reconciled"
    ]
    identities = [str(item.get("target_identity")) for item in transitions]
    if route.get("status") == NAVIGATION_ONLY_COMPLETE:
        route_path = str(route.get("path") or FULL_ROUTE_PATH)
        contracts = {
            FULL_ROUTE_PATH: (
                [
                    "home-to-world",
                    "world-search-entry",
                    "android-back",
                    "world-to-home",
                ],
                [
                    ("HOME_READY", "home-to-world", "WORLD_READY", "WORLD_READY"),
                    (
                        "WORLD_READY",
                        "world-search-entry",
                        "WORLD_SEARCH_OPEN",
                        "WORLD_SEARCH_OPEN",
                    ),
                    ("WORLD_SEARCH_OPEN", "android-back", "WORLD_READY", "WORLD_READY"),
                    ("WORLD_READY", "world-to-home", "HOME_READY", "HOME_READY"),
                ],
                HOME_READY,
                "verified_hud_home_round_trip",
            ),
            RECOVERY_PATH: (
                ["world-to-home"],
                [("WORLD_READY", "world-to-home", "HOME_READY", "HOME_READY")],
                HOME_READY,
                "verified_world_to_home_recovery",
            ),
            SEARCH_ENTRY_ONLY_PATH: (
                ["world-search-entry"],
                [
                    (
                        "WORLD_READY",
                        "world-search-entry",
                        "WORLD_SEARCH_OPEN",
                        "WORLD_SEARCH_OPEN",
                    )
                ],
                "WORLD_SEARCH_OPEN",
                "verified_world_ready_to_search_open",
            ),
        }
        if route_path not in contracts:
            raise _pnsctl().OperatorError("World navigation route path is unsupported")
        expected, expected_contract, terminal_state, expected_reason = contracts[
            route_path
        ]
        if route_path == RECOVERY_PATH and identities == [
            "android-back",
            "world-to-home",
        ]:
            expected_contract = [
                ("WORLD_SEARCH_OPEN", "android-back", "WORLD_READY", "WORLD_READY"),
                ("WORLD_READY", "world-to-home", "HOME_READY", "HOME_READY"),
            ]
        elif identities != expected:
            raise _pnsctl().OperatorError(
                "World navigation transition order is not canonical"
            )
        actual_contract = [
            (
                str(item.get("source_state")),
                str(item.get("target_identity")),
                str(item.get("expected_successor_state")),
                str(item.get("successor_state")),
            )
            for item in transitions
        ]
        if actual_contract != expected_contract:
            raise _pnsctl().OperatorError(
                "World navigation transition contract is invalid"
            )
        if any(
            item.get("successor_overlay_state") not in _OVERLAY_ABSENT
            for item in transitions
        ):
            raise _pnsctl().OperatorError(
                "World navigation successor overlay is not absent"
            )
        if route.get("final_state") != terminal_state:
            raise _pnsctl().OperatorError("World navigation lacks final terminal proof")
        if route.get("final_overlay_state") not in _OVERLAY_ABSENT:
            raise _pnsctl().OperatorError(
                "World navigation final HOME_READY overlay is not absent"
            )
        if route.get("terminal_runtime_state") != terminal_state:
            raise _pnsctl().OperatorError("World navigation terminal state is unsafe")
        if result.get("terminal_runtime_state") != terminal_state:
            raise _pnsctl().OperatorError(
                "World navigation delivery terminal state is unsafe"
            )
        if route.get("reason") != expected_reason:
            raise _pnsctl().OperatorError(
                "World navigation completion reason is invalid"
            )
    elif route.get("status") != BLOCKED_FAIL_CLOSED:
        raise _pnsctl().OperatorError("World navigation status is not terminal")
    if result.get("scheduler_enabled") is not False:
        raise _pnsctl().OperatorError("World navigation scheduler was enabled")


def verify_world_map_navigation_foundation(
    structure: Mapping[str, Any],
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> dict[str, Any]:
    del queue, lease
    result = structure.get("result")
    if not isinstance(result, Mapping) or result.get("flow_id") != FLOW_ID:
        raise _pnsctl().OperatorError(
            "World navigation evidence belongs to another flow"
        )
    session = Path(str(structure.get("session_directory") or "")).resolve()
    if not session.is_dir() or session.is_symlink():
        raise _pnsctl().OperatorError(
            "World navigation evidence session is unavailable"
        )
    retained = session / "flow-delivery-result.json"
    if not retained.is_file() or json.loads(
        retained.read_text(encoding="utf-8")
    ) != dict(result):
        raise _pnsctl().OperatorError(
            "World navigation retained result does not match verifier input"
        )
    if result.get("serial") != _pnsctl().BLUESTACKS_SERIAL or (
        result.get("native_width"),
        result.get("native_height"),
    ) != (NATIVE_WIDTH, NATIVE_HEIGHT):
        raise _pnsctl().OperatorError("World navigation runtime profile is invalid")
    events, hashes = _verify_route_result(result, session)
    _verify_event_order(events, result["world_navigation_result"], hashes)
    _verify_popup_successors(events, result["world_navigation_result"], hashes)
    _verify_route_semantics(result, events)
    route = result["world_navigation_result"]
    diagnostic = _is_diagnostic_route(route)
    expected_topology = "diagnostic" if diagnostic else "continuous"
    route_topology = route.get("proof_topology")
    if route_topology is not None and route_topology != expected_topology:
        raise _pnsctl().OperatorError(
            "World navigation route proof topology does not match route path"
        )
    if result.get("proof_topology") != expected_topology:
        raise _pnsctl().OperatorError(
            "World navigation proof topology does not match route path"
        )
    trace = result.get("causal_trace")
    if (
        not isinstance(trace, Mapping)
        or trace.get("proof_topology") != expected_topology
    ):
        raise _pnsctl().OperatorError(
            "World navigation causal trace topology does not match route path"
        )
    _verify_registration_evidence(result, trace)
    metadata_layers = (
        ("route", route),
        ("result", result),
        ("causal trace", trace),
    )
    if diagnostic:
        if result.get("acceptance_eligible") is not False:
            raise _pnsctl().OperatorError(
                "World navigation acceptance eligibility is invalid"
            )
        if trace.get("acceptance_eligible") is not False:
            raise _pnsctl().OperatorError(
                "World navigation causal trace acceptance eligibility is invalid"
            )
        if any(
            "acceptance_eligible" in layer
            and layer.get("acceptance_eligible") is not False
            for _label, layer in metadata_layers
        ):
            raise _pnsctl().OperatorError(
                "World navigation diagnostic acceptance metadata is inconsistent"
            )
    elif any(
        "acceptance_eligible" in layer and layer.get("acceptance_eligible") is not True
        for _label, layer in metadata_layers
    ):
        raise _pnsctl().OperatorError(
            "World navigation continuous acceptance metadata is contradictory"
        )
    if route.get("status") != NAVIGATION_ONLY_COMPLETE:
        blocked_verdict = {
            "status": "evidence_required",
            "flow_id": FLOW_ID,
            "reason": str(route.get("reason") or "blocked_fail_closed"),
            "session_directory": str(session),
            "navigation_input_count": route.get("navigation_input_count", 0),
            "safe_popup_input_count": route.get("safe_popup_input_count", 0),
            "production_registration": result.get(
                "production_registration", "NOT_REGISTERED"
            ),
            "scheduler_enabled": False,
        }
        if diagnostic:
            blocked_verdict["acceptance_eligible"] = False
        return blocked_verdict
    if diagnostic:
        return {
            "status": "diagnostic_verified",
            "acceptance_eligible": False,
            "flow_id": FLOW_ID,
            "terminal": NAVIGATION_ONLY_COMPLETE,
            "session_directory": str(session),
            "navigation_input_count": route["navigation_input_count"],
            "safe_popup_input_count": route["safe_popup_input_count"],
            "terminal_runtime_state": result["terminal_runtime_state"],
            "proof_topology": "diagnostic",
            "production_registration": result.get(
                "production_registration", "NOT_REGISTERED"
            ),
            "scheduler_enabled": False,
        }
    return {
        "status": "verified",
        "flow_id": FLOW_ID,
        "terminal": NAVIGATION_ONLY_COMPLETE,
        "session_directory": str(session),
        "navigation_input_count": route["navigation_input_count"],
        "safe_popup_input_count": route["safe_popup_input_count"],
        "home_recovery_latency_seconds": route["home_recovery_latency_seconds"],
        "terminal_runtime_state": result["terminal_runtime_state"],
        "production_registration": result.get(
            "production_registration", "NOT_REGISTERED"
        ),
        "scheduler_enabled": False,
        "registration_snapshot": dict(result["registration_snapshot"])
        if result.get("registration_snapshot") is not None
        else None,
    }


def recover_world_map_navigation_foundation(
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> str:
    """Observe-only recovery binding; it never sends Back or any game input."""

    del queue, lease
    pnsctl = _pnsctl()
    state = str(pnsctl._run_fixed_bluestacks_adb("get-state")).strip()
    if state != "device":
        raise pnsctl.OperatorError("approved BlueStacks serial is not in device state")
    return json.dumps(
        {
            "status": "recovered_or_already_safe",
            "flow_id": FLOW_ID,
            "dispatch": False,
            "recovery": "observe_only_no_input",
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
    runners[RUNNER_ID] = run_world_map_navigation_foundation
    validators[VALIDATOR_ID] = verify_world_map_navigation_foundation
    handlers[RECOVERY_ID] = recover_world_map_navigation_foundation


run_world_map_navigation_bluestacks = run_world_map_navigation_foundation
verify_world_map_navigation_bluestacks = verify_world_map_navigation_foundation
recover_world_map_navigation_bluestacks = recover_world_map_navigation_foundation
