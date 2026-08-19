"""Thin pnsctl conduct adapter for the Daily 1K Food flow."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
from scripts.daily_resource_item_bluestacks import (
    MAX_RESOURCE_LIST_SWIPES as ROUTE_MAX_RESOURCE_LIST_SWIPES,
    MAX_ROUTE_INPUTS as ROUTE_MAX_ROUTE_INPUTS,
    _resource_delta_verified,
)


FLOW_ID = "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION"
RUNNER_ID = "daily_resource_item_bluestacks_runner"
VALIDATOR_ID = "daily_resource_item_bluestacks_evidence"
RECOVERY_ID = "daily_resource_item_bluestacks_recovery"
MAX_INPUTS = ROUTE_MAX_ROUTE_INPUTS
MAX_RESOURCE_LIST_SWIPES = ROUTE_MAX_RESOURCE_LIST_SWIPES
ITEM_USE_ACTION_KEY = "daily-resource-item:use-1k-food"
MAX_ITEM_USE_TRANSPORT_CALLS = 1


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
            and row.get("action_key") == ITEM_USE_ACTION_KEY
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


def _frame_exists(session: Path, frame_ref: object) -> bool:
    if not isinstance(frame_ref, Mapping):
        return False
    path_value = frame_ref.get("path")
    sha = frame_ref.get("sha256")
    if not isinstance(path_value, str) or not isinstance(sha, str) or len(sha) != 64:
        return False
    path = Path(path_value)
    candidates = [path]
    if not path.is_absolute():
        candidates.extend((session / path, session / "frames" / Path(path_value).name))
    for candidate in candidates:
        if candidate.is_file() and candidate.stat().st_size > 0:
            return True
    return False


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
        "semantic_evidence": _semantic_from_result(result),
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

        route_result = route.run_daily_resource_item(runtime, outer_session)
        item_use_calls = _item_use_calls(runtime_session)
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
    except Exception as exc:
        item_use_calls = _item_use_calls(runtime_session)
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
    events_file = session / str(events_rel)
    item_use_calls = _item_use_calls(
        events_file.parent if events_file.is_file() else session
    )

    semantic = result.get("semantic_evidence")
    if not isinstance(semantic, Mapping):
        semantic = {}
    recomputed_delta = _resource_delta_verified(
        {
            "inventory_quantity": semantic.get("before_owned_quantity"),
            "food_resource": semantic.get("before_food_resource"),
        },
        {
            "inventory_quantity": semantic.get("after_owned_quantity"),
            "food_resource": semantic.get("after_food_resource"),
        },
    )
    home_ok = bool(
        result.get("terminal_home_verified") is True
        and result.get("terminal_runtime_state") == "recognized_home"
        and _frame_exists(session, semantic.get("terminal_home_frame"))
    )
    frames_ok = _frame_exists(
        session, semantic.get("item_before_frame")
    ) and _frame_exists(session, semantic.get("item_after_frame"))
    verified = bool(
        result.get("status") == "completed"
        and item_use_calls == MAX_ITEM_USE_TRANSPORT_CALLS
        and recomputed_delta
        and result.get("resource_delta_verified") is True
        and home_ok
        and frames_ok
        and result.get("production_registration") == "NOT_REGISTERED"
        and result.get("scheduler_enabled") is False
    )
    return {
        "status": "verified" if verified else "evidence_required",
        "flow_id": FLOW_ID,
        "session_directory": structure.get("session_directory"),
        "item_use_transport_calls": item_use_calls,
        "resource_delta_recomputed": recomputed_delta,
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
