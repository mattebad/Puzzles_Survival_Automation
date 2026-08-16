"""Fixed flow-delivery binding for the World-map navigation foundation."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import os
from typing import Any, Mapping

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import NATIVE_HEIGHT, NATIVE_WIDTH, LocalBlueStacksRuntime
from scripts.world_map_navigation_bluestacks import (
    ALLOWED_CONTROL_IDENTITIES,
    BLOCKED_FAIL_CLOSED,
    FLOW_ID,
    HOME_READY,
    MAX_ROUTE_INPUTS,
    NAVIGATION_ONLY_COMPLETE,
    POPUP_CLOSE,
    RUNNER_ID,
    RECOVERY_ID,
    VALIDATOR_ID,
    recover_world_map_home,
    run_world_map_navigation,
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


def _pnsctl():
    from scripts import pnsctl

    return pnsctl


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _maximum_inputs(lease: Mapping[str, Any]) -> int:
    value = lease.get("max_inputs", os.environ.get("PNS_DEVELOPMENT_MAX_INPUTS", MAX_ROUTE_INPUTS))
    try:
        maximum = int(value)
    except (TypeError, ValueError) as exc:
        raise _pnsctl().OperatorError("World navigation max_inputs must be an integer") from exc
    if not 1 <= maximum <= MAX_ROUTE_INPUTS:
        raise _pnsctl().OperatorError("World navigation max_inputs must be between 1 and 20")
    return maximum


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _native_frames(session: Path) -> list[str]:
    frames = sorted(
        path for path in (session / "frames").glob("*.png")
        if path.is_file() and not path.is_symlink()
    )
    if not frames:
        raise _pnsctl().OperatorError("World navigation route produced no native frame evidence")
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
) -> dict[str, Any]:
    frames = _native_frames(session)
    status = str(route.get("status") or BLOCKED_FAIL_CLOSED)
    delivery_status = "completed" if status == NAVIGATION_ONLY_COMPLETE else "blocked"
    delivery = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "status": delivery_status,
        "serial": _pnsctl().BLUESTACKS_SERIAL,
        "native_width": NATIVE_WIDTH,
        "native_height": NATIVE_HEIGHT,
        "runtime_owner": str(lease.get("owner") or "pnsctl-development-session"),
        "terminal_runtime_state": (
            HOME_READY
            if delivery_status == "completed"
            else "safe_blocked_terminal"
        ),
        "actions": [
            {
                "action_class": "navigation_only",
                "path": (
                    "world_ready_to_home_recovery"
                    if recovery_only
                    else "home_ready_to_world_to_search_to_home_ready"
                ),
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
        "dispatch": int(route.get("input_count") or 0) > 0,
        "dispatch_count": int(route.get("input_count") or 0),
        "input_count": int(route.get("input_count") or 0),
        "navigation_input_count": int(route.get("navigation_input_count") or 0),
        "safe_popup_input_count": int(route.get("safe_popup_input_count") or 0),
        "operator_returncode": operator_returncode,
        "production_registration": "NOT_REGISTERED",
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
    }
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
    maximum = _maximum_inputs(lease)
    root = pnsctl.BLUESTACKS_ARTIFACT_ROOT / FLOW_ID / f"run-{_stamp()}"
    root.mkdir(parents=True, exist_ok=False)
    if not live:
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
            "session_directory": str(root),
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        }
        _write_json(root / "dry-run-result.json", result)
        return json.dumps(result, sort_keys=True)

    try:
        runtime = LocalBlueStacksRuntime.connect(
            adb=str(pnsctl.BLUESTACKS_ADB),
            serial=pnsctl.BLUESTACKS_SERIAL,
            output_directory=root,
            workflow="world-map-navigation",
            execute=True,
        )
        recovery_only = bool(lease.get("recovery_only"))
        route = (
            recover_world_map_home(runtime, maximum_inputs=maximum)
            if recovery_only
            else run_world_map_navigation(
                runtime,
                maximum_inputs=maximum,
                maximum_popup_inputs=min(4, maximum),
            )
        )
        session = runtime.session
        delivery = _run_result(
            route,
            session=session,
            lease=lease,
            operator_returncode=0,
            recovery_only=recovery_only,
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
        "terminal_runtime_state": delivery["terminal_runtime_state"],
    }
    return json.dumps(result, sort_keys=True)


def _hash_native(path: Path) -> str:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.shape[:2] != (NATIVE_HEIGHT, NATIVE_WIDTH):
        raise _pnsctl().OperatorError("World navigation evidence is not native 800x1280 PNG")
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


def _verify_route_result(result: Mapping[str, Any], session: Path) -> tuple[list[dict[str, Any]], set[str]]:
    route = result.get("world_navigation_result")
    if not isinstance(route, Mapping):
        raise _pnsctl().OperatorError("World navigation semantic result is missing")
    if route.get("flow_id") != FLOW_ID:
        raise _pnsctl().OperatorError("World navigation semantic result identity mismatch")
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
    if result.get("forbidden_input_classes") != [] or route.get(
        "forbidden_input_classes"
    ) != []:
        raise _pnsctl().OperatorError("World navigation forbidden classes are nonempty")
    frame_refs = result.get("frames")
    if not isinstance(frame_refs, list) or not frame_refs:
        raise _pnsctl().OperatorError("World navigation native frames are required")
    hashes: set[str] = set()
    for ref in frame_refs:
        if not isinstance(ref, str) or Path(ref).is_absolute():
            raise _pnsctl().OperatorError("World navigation frame reference is not relative")
        path = (session / ref).resolve()
        try:
            path.relative_to(session.resolve())
        except ValueError as exc:
            raise _pnsctl().OperatorError("World navigation frame escaped session") from exc
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
                raise _pnsctl().OperatorError("World navigation capture hash is not retained")
            captures.append((index, event))
        elif kind == "dispatch":
            dispatches.append((index, event))
        elif kind == "semantic":
            identity = str(event.get("target_identity") or "")
            if any(marker in identity.casefold() for marker in _FORBIDDEN_MARKERS):
                raise _pnsctl().OperatorError("forbidden semantic target identity in events")

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
            and event.get("event")
            in {"navigation_prepared", "safe_popup_prepared"}
        ]
        if len(prepared_for_identity) != 1:
            raise _pnsctl().OperatorError("World navigation prepare identity is missing")
        capture_identity = _capture_identity(prepared_for_identity[0])
        if capture_identity in seen_captures:
            raise _pnsctl().OperatorError("World navigation reuses a stale capture identity")
        seen_captures.add(capture_identity)
        if identity not in ALLOWED_CONTROL_IDENTITIES and identity != "android-back":
            raise _pnsctl().OperatorError(
                f"World navigation target identity is not allowlisted: {identity}"
            )
        if any(marker in identity.casefold() for marker in _FORBIDDEN_MARKERS):
            raise _pnsctl().OperatorError("forbidden resource/combat identity in events")
        if identity != "android-back" and not _valid_native_roi(dispatch.get("target_roi")):
            raise _pnsctl().OperatorError(
                "World navigation dispatch lacks an exact native target ROI"
            )
        if dispatch.get("consequential") is True:
            raise _pnsctl().OperatorError("navigation route contains consequential input")
        _verify_dispatch_chain(events, captures, dispatch_index, dispatch, frame_hashes)

    declared = route.get("input_count")
    if type(declared) is not int or declared != len(dispatches):
        raise _pnsctl().OperatorError("World navigation input count does not match events")
    popup_count = sum(
        1 for _index, event in dispatches if event.get("target_identity") == POPUP_CLOSE
    )
    if route.get("safe_popup_input_count") != popup_count:
        raise _pnsctl().OperatorError("World navigation popup count does not match events")
    if route.get("navigation_input_count") != len(dispatches) - popup_count:
        raise _pnsctl().OperatorError("World navigation navigation count does not match events")
    if (
        type(route.get("safe_popup_input_count")) is not int
        or not 0 <= route["safe_popup_input_count"] <= 4
        or type(route.get("max_inputs")) is not int
        or route["input_count"] > route["max_inputs"]
    ):
        raise _pnsctl().OperatorError("World navigation input budget accounting is invalid")
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
        raise _pnsctl().OperatorError("World navigation forbidden input accounting is nonzero")
    if route.get("forbidden_input_classes") != []:
        raise _pnsctl().OperatorError("World navigation reports forbidden input classes")

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
        expected = ["home-to-world", "world-search-entry", "android-back", "world-to-home"]
        if [str(item.get("target_identity")) for item in transitions] != expected:
            raise _pnsctl().OperatorError("World navigation dispatch order is not canonical")
        terminal = [
            (index, event)
            for index, event in enumerate(events)
            if event.get("type") == "semantic" and event.get("event") == "route_terminal"
        ]
        if len(terminal) != 1:
            raise _pnsctl().OperatorError("World navigation terminal event is missing or duplicated")
        terminal_index, terminal_event = terminal[0]
        if terminal_index <= max(
            index
            for index, event in enumerate(events)
            if event.get("type") == "semantic"
            and event.get("event") == "navigation_reconciled"
        ):
            raise _pnsctl().OperatorError("World navigation terminal event is out of order")
        if (
            terminal_event.get("state") != HOME_READY
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
        if event.get("type") == "semantic"
        and event.get("action_key") == action_key
    ]
    prepared = [
        item
        for item in semantic
        if item[1].get("event")
        in {"navigation_prepared", "safe_popup_prepared"}
    ]
    planned = [
        item
        for item in semantic
        if item[1].get("event") in {"navigation_planned", "safe_popup_planned"}
    ]
    if len(prepared) != 1 or len(planned) != 1:
        raise _pnsctl().OperatorError("World navigation dispatch lacks one planning/prepare chain")
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
        raise _pnsctl().OperatorError("World navigation target changed after preparation")
    if identity == POPUP_CLOSE:
        popup_evidence = prepared_event.get("popup_semantic_evidence") or ()
        if (
            prepared_event.get("popup_contract_version") != "vip-points-get-pts-close-v1"
            or prepared_event.get("target_geometry_source")
            != "current-frame-bounded-candidate"
            or prepared_event.get("popup_context_state")
            != prepared_event.get("expected_successor_state")
            or not all(
                any(marker.casefold() in str(item).casefold() for item in popup_evidence)
                for marker in ("Get Pts", "VIP pts", "Close")
            )
            or prepared_event.get("target_roi") != dispatch.get("target_roi")
        ):
            raise _pnsctl().OperatorError("World navigation popup semantic evidence is invalid")
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
        raise _pnsctl().OperatorError("World navigation source capture is stale or duplicated")
    source_index, source_event = source_captures[0]
    if any(
        index > source_index and index < prepared_index and event.get("type") == "capture"
        for index, event in enumerate(events)
    ):
        raise _pnsctl().OperatorError("World navigation source is not the fresh immediate-before")
    for key in ("capture_session", "capture_ordinal", "capture_frame_sha256"):
        if key in prepared_event and key == "capture_frame_sha256":
            if prepared_event[key] != source:
                raise _pnsctl().OperatorError("World navigation capture identity is inconsistent")
        if key in prepared_event and key in source_event:
            if prepared_event[key] != source_event[key]:
                raise _pnsctl().OperatorError("World navigation session/ordinal is inconsistent")

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
        raise _pnsctl().OperatorError("World navigation semantic reconcile is missing or duplicated")
    reconcile_index, reconcile_event = reconciled[0]
    if reconcile_index <= dispatch_index:
        raise _pnsctl().OperatorError("World navigation reconcile precedes dispatch")
    post_key = (
        "post_frame_sha256" if identity == POPUP_CLOSE else "immediate_post_frame_sha256"
    )
    post_hash = reconcile_event.get(post_key)
    if not isinstance(post_hash, str) or post_hash not in frame_hashes:
        raise _pnsctl().OperatorError("World navigation immediate post capture is missing")
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
        raise _pnsctl().OperatorError("World navigation post capture is stale or missing")
    runtime_reconciles = [
        (index, event)
        for index, event in enumerate(events)
        if event.get("type") == "reconcile"
        and event.get("action_key") == action_key
    ]
    if len(runtime_reconciles) != 1 or runtime_reconciles[0][0] >= reconcile_index:
        raise _pnsctl().OperatorError("World navigation transport reconciliation is missing")
    runtime_event = runtime_reconciles[0][1]
    expected_post = (
        reconcile_event.get("successor_frame_sha256")
        if identity != POPUP_CLOSE
        else reconcile_event.get("post_frame_sha256")
    )
    if runtime_event.get("status") != "confirmed" or runtime_event.get(
        "post_sha256"
    ) != expected_post:
        raise _pnsctl().OperatorError("World navigation post hash is not exactly reconciled")
    if identity == POPUP_CLOSE and (
        reconcile_event.get("popup_absent_verified") is not True
        or not reconcile_event.get("successor_state")
    ):
        raise _pnsctl().OperatorError("World navigation popup dismissal lacks successor proof")


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
        if len(reconciled) != 1 or reconciled[0].get(
            "popup_absent_verified"
        ) is not True:
            raise _pnsctl().OperatorError(
                "World navigation popup lacks verified dismissal successor evidence"
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
        expected = ["home-to-world", "world-search-entry", "android-back", "world-to-home"]
        if identities != expected:
            raise _pnsctl().OperatorError("World navigation transition order is not canonical")
        expected_contract = [
            ("HOME_READY", "home-to-world", "WORLD_READY", "WORLD_READY"),
            ("WORLD_READY", "world-search-entry", "WORLD_SEARCH_OPEN", "WORLD_SEARCH_OPEN"),
            ("WORLD_SEARCH_OPEN", "android-back", "WORLD_READY", "WORLD_READY"),
            ("WORLD_READY", "world-to-home", "HOME_READY", "HOME_READY"),
        ]
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
            raise _pnsctl().OperatorError("World navigation transition contract is invalid")
        if any(
            item.get("successor_overlay_state") not in _OVERLAY_ABSENT
            for item in transitions
        ):
            raise _pnsctl().OperatorError(
                "World navigation successor overlay is not absent"
            )
        if route.get("final_state") != HOME_READY:
            raise _pnsctl().OperatorError("World navigation lacks final HOME_READY proof")
        if route.get("final_overlay_state") not in _OVERLAY_ABSENT:
            raise _pnsctl().OperatorError(
                "World navigation final HOME_READY overlay is not absent"
            )
        if route.get("terminal_runtime_state") != HOME_READY:
            raise _pnsctl().OperatorError("World navigation terminal HOME_READY state is unsafe")
        if result.get("terminal_runtime_state") != HOME_READY:
            raise _pnsctl().OperatorError("World navigation delivery terminal state is unsafe")
        if route.get("reason") != "verified_hud_home_round_trip":
            raise _pnsctl().OperatorError("World navigation completion reason is invalid")
    elif route.get("status") != BLOCKED_FAIL_CLOSED:
        raise _pnsctl().OperatorError("World navigation status is not terminal")
    if result.get("production_registration") != "NOT_REGISTERED":
        raise _pnsctl().OperatorError("World navigation production registration changed")
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
        raise _pnsctl().OperatorError("World navigation evidence belongs to another flow")
    session = Path(str(structure.get("session_directory") or "")).resolve()
    if not session.is_dir() or session.is_symlink():
        raise _pnsctl().OperatorError("World navigation evidence session is unavailable")
    retained = session / "flow-delivery-result.json"
    if not retained.is_file() or json.loads(retained.read_text(encoding="utf-8")) != dict(result):
        raise _pnsctl().OperatorError("World navigation retained result does not match verifier input")
    if result.get("serial") != _pnsctl().BLUESTACKS_SERIAL or (
        result.get("native_width"), result.get("native_height")
    ) != (NATIVE_WIDTH, NATIVE_HEIGHT):
        raise _pnsctl().OperatorError("World navigation runtime profile is invalid")
    events, hashes = _verify_route_result(result, session)
    _verify_event_order(events, result["world_navigation_result"], hashes)
    _verify_popup_successors(events, result["world_navigation_result"], hashes)
    _verify_route_semantics(result, events)
    route = result["world_navigation_result"]
    if route.get("status") != NAVIGATION_ONLY_COMPLETE:
        return {
            "status": "evidence_required",
            "flow_id": FLOW_ID,
            "reason": str(route.get("reason") or "blocked_fail_closed"),
            "session_directory": str(session),
            "navigation_input_count": route.get("navigation_input_count", 0),
            "safe_popup_input_count": route.get("safe_popup_input_count", 0),
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
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
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

