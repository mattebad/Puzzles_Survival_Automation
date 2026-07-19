#!/usr/bin/env python3
"""Inspect or collect exact zero-cost Supply Depot rewards on local BlueStacks.

This executable route is local-only, unregistered, scheduler-ineligible, and dry-run by
default.  It never uses the Daily Quest Go route and never retries an ambiguous collection.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys
import time

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
from tasks.supply_depot import (
    BLUESTACKS_NATIVE_TARGET_PROVENANCE,
    BLUESTACKS_PROFILE_ID,
    SUPPLY_DEPOT_FREE_TARGET,
    SUPPLY_DEPOT_SCREEN,
    SupplyDepotConfig,
    SupplyDepotHoldConfig,
    SupplyDepotObservation,
    supply_depot_authorizeable,
    supply_depot_hold_postcondition_verified,
    supply_depot_postcondition_verified,
)
from tasks.supply_depot_vision import SupplyDepotControl, recognize_supply_depot_screen
from tasks.home_atlas_vision import frame_digest
from tasks.home_atlas import ZoomIdentity, load_home_atlas
from tasks.home_atlas_vision import BlueStacksHomeLocalizer


PANEL_BOUNDS = (0, 940, 800, 1280)
DEFAULT_OUTPUT = Path(".local-captures/supply-depot-direct-building")
ACTION_LEDGER_NAME = "supply-depot-action-keys.json"


def _json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _relative_evidence(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _load_ledger(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not all(isinstance(key, str) and isinstance(value, dict) for key, value in payload.items()):
        raise RuntimeError("Supply Depot action-key ledger is malformed")
    return payload


def _record_ledger(path: Path, ledger: dict[str, dict[str, object]], action_key: str, **record: object) -> None:
    ledger[action_key] = dict(record)
    _json(path, ledger)


def _select_authorized_control(recognition) -> SupplyDepotControl | None:
    if (
        not recognition.recognized
        or recognition.state != "available"
        or recognition.overlay
        or recognition.premium_or_purchase_visible
        or recognition.ambiguity != "none"
        or recognition.daily_free_attempts is None
        or recognition.daily_free_attempts <= 0
        or len(recognition.controls) != 4
    ):
        return None
    available = [control for control in recognition.controls if control.state == "available_free" and control.zero_cost]
    return min(available, key=lambda item: item.column) if available else None


def _observation(captured, recognition, control: SupplyDepotControl) -> SupplyDepotObservation:
    return SupplyDepotObservation(
        screen_state=SUPPLY_DEPOT_SCREEN,
        selected_supply_depot=recognition.recognized,
        target_identity=SUPPLY_DEPOT_FREE_TARGET,
        target_roi=control.roi,
        panel_bounds=PANEL_BOUNDS,
        control_class="COLLECT" if control.zero_cost else "",
        collection_ready=control.zero_cost,
        reward_kind=control.reward_kind,
        known_reward=control.reward_kind in {"food", "wood", "steel", "gas"},
        premium_reward=False,
        unknown_reward=False,
        cost_type="none" if control.zero_cost else "unknown",
        cost_amount=0 if control.zero_cost else None,
        quantity=1,
        game_day_id=None,
        target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
        source_frame_sha256=captured.sha256,
        evidence_refs=(_relative_evidence(captured.path),),
        overlay_state="none" if not recognition.overlay else "overlay",
        reset_guard_active=False,
        runtime_profile_id=BLUESTACKS_PROFILE_ID,
        recognized=recognition.recognized,
        reset_identity_required=False,
        daily_free_attempts=recognition.daily_free_attempts,
    )


def _successor_observation(before: SupplyDepotObservation, captured, recognition) -> SupplyDepotObservation | None:
    if not recognition.recognized or recognition.daily_free_attempts is None:
        return None
    return replace(
        before,
        selected_supply_depot=True,
        source_frame_sha256=captured.sha256,
        evidence_refs=(_relative_evidence(captured.path),),
        collection_ready=False,
        control_class="",
        daily_free_attempts=recognition.daily_free_attempts,
    )


def _recognition_payload(recognition) -> dict[str, object]:
    return asdict(recognition)


def _inspect_frame(path: Path):
    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError(f"could not read frame: {path}")
    return recognize_supply_depot_screen(frame)


def command_inspect(args) -> int:
    if args.frame is not None:
        recognition = _inspect_frame(args.frame)
        payload = {"status": "recognized" if recognition.recognized else "blocked", "recognition": _recognition_payload(recognition)}
    else:
        runtime = LocalBlueStacksRuntime.connect(
            adb=args.adb,
            serial=args.serial,
            output_directory=args.output_directory,
            workflow="supply-depot-inspect",
            execute=False,
        )
        captured = runtime.capture("inspect-source")
        recognition = recognize_supply_depot_screen(captured.frame)
        payload = {
            "status": "recognized" if recognition.recognized else "blocked",
            "recognition": _recognition_payload(recognition),
            "session": str(runtime.session),
        }
    print(json.dumps(payload, sort_keys=True, default=str))
    return 0 if recognition.recognized else 3


def command_collect_one(args) -> int:
    config = SupplyDepotConfig()
    if not args.execute or not args.yes:
        payload = {
            "status": "dry_run",
            "reason": "collect-one requires both --execute and --yes; no runtime input issued",
            "config": asdict(config),
        }
        print(json.dumps(payload, sort_keys=True))
        return 0
    if (
        not config.enabled
        or config.maximum_free_collections_per_run != 1
        or not config.direct_building_route_enabled
        or config.quest_go_fallback_enabled
        or config.production_registration_enabled
        or config.scheduler_eligible
    ):
        raise RuntimeError("unsafe Supply Depot configuration")

    runtime = LocalBlueStacksRuntime.connect(
        adb=args.adb,
        serial=args.serial,
        output_directory=args.output_directory,
        workflow="supply-depot-collect-one",
        execute=True,
    )
    result_path = runtime.session / "collect-one-result.json"
    source = runtime.capture("collection-source")
    source_recognition = recognize_supply_depot_screen(source.frame)
    source_control = _select_authorized_control(source_recognition)
    if source_control is None:
        result = {
            "status": "blocked",
            "reason": "source_exact_free_target_not_authorized",
            "recognition": _recognition_payload(source_recognition),
            "actions_dispatched": 0,
            "session": str(runtime.session),
        }
        _json(result_path, result)
        print(json.dumps(result, sort_keys=True, default=str))
        return 3

    immediate_before = runtime.capture("collection-immediate-before")
    before_recognition = recognize_supply_depot_screen(immediate_before.frame)
    before_control = _select_authorized_control(before_recognition)
    before = _observation(immediate_before, before_recognition, before_control) if before_control is not None else None
    if (
        before is None
        or before_control.reward_kind != source_control.reward_kind
        or before_recognition.daily_free_attempts != source_recognition.daily_free_attempts
        or before_recognition.frame_sha256 != frame_digest(immediate_before.frame)
        or not supply_depot_authorizeable(before)
    ):
        result = {
            "status": "blocked",
            "reason": "immediate_before_exact_free_target_not_authorized",
            "source_recognition": _recognition_payload(source_recognition),
            "before_recognition": _recognition_payload(before_recognition),
            "actions_dispatched": 0,
            "session": str(runtime.session),
        }
        _json(result_path, result)
        print(json.dumps(result, sort_keys=True, default=str))
        return 3

    action_key = (
        f"supply-depot-free:bluestacks:no-reset:attempts-"
        f"{before.daily_free_attempts}:{before.reward_kind}"
    )
    ledger_path = args.output_directory / ACTION_LEDGER_NAME
    ledger = _load_ledger(ledger_path)
    if action_key in ledger:
        result = {
            "status": "blocked",
            "reason": "duplicate_action_key",
            "action_key": action_key,
            "prior": ledger[action_key],
            "actions_dispatched": 0,
            "session": str(runtime.session),
        }
        _json(result_path, result)
        print(json.dumps(result, sort_keys=True, default=str))
        return 3

    _record_ledger(
        ledger_path,
        ledger,
        action_key,
        status="prepared",
        source_sha256=source.sha256,
        immediate_before_sha256=immediate_before.sha256,
        reward_kind=before.reward_kind,
        daily_free_attempts_before=before.daily_free_attempts,
        session=str(runtime.session),
    )
    runtime.tap(
        immediate_before,
        target_identity=SUPPLY_DEPOT_FREE_TARGET,
        target_roi=before.target_roi,
        action_key=action_key,
        consequential=True,
    )
    _record_ledger(
        ledger_path,
        ledger,
        action_key,
        status="dispatched",
        source_sha256=source.sha256,
        immediate_before_sha256=immediate_before.sha256,
        reward_kind=before.reward_kind,
        daily_free_attempts_before=before.daily_free_attempts,
        session=str(runtime.session),
    )
    immediate_post = runtime.capture("collection-immediate-post")
    time.sleep(args.settle_seconds)
    settled = runtime.capture("collection-settled")
    post_recognition = recognize_supply_depot_screen(immediate_post.frame)
    settled_recognition = recognize_supply_depot_screen(settled.frame)
    successor = _successor_observation(before, settled, settled_recognition)
    confirmed = supply_depot_postcondition_verified(before, successor)
    status = "confirmed" if confirmed else "unresolved"
    reason = "daily_free_attempts_decreased_exactly_one" if confirmed else "semantic_collection_result_ambiguous_no_retry"
    runtime.reconcile(action_key, status, settled, reason)
    _record_ledger(
        ledger_path,
        ledger,
        action_key,
        status=status,
        source_sha256=source.sha256,
        immediate_before_sha256=immediate_before.sha256,
        immediate_post_sha256=immediate_post.sha256,
        settled_sha256=settled.sha256,
        reward_kind=before.reward_kind,
        daily_free_attempts_before=before.daily_free_attempts,
        daily_free_attempts_after=settled_recognition.daily_free_attempts,
        reason=reason,
        session=str(runtime.session),
    )
    result = {
        "status": "completed" if confirmed else "unresolved",
        "reason": reason,
        "action_key": action_key,
        "actions_dispatched": 1,
        "free_collections_confirmed": 1 if confirmed else 0,
        "source_sha256": source.sha256,
        "immediate_before_sha256": immediate_before.sha256,
        "immediate_post_sha256": immediate_post.sha256,
        "settled_sha256": settled.sha256,
        "before": _recognition_payload(before_recognition),
        "immediate_post": _recognition_payload(post_recognition),
        "settled": _recognition_payload(settled_recognition),
        "config": asdict(config),
        "session": str(runtime.session),
    }
    _json(result_path, result)
    print(json.dumps(result, sort_keys=True, default=str))
    return 0 if confirmed else 4


def command_collect_free_hold(args) -> int:
    config = SupplyDepotHoldConfig()
    if not args.execute or not args.yes:
        payload = {
            "status": "dry_run",
            "reason": "collect-free-hold requires both --execute and --yes; no runtime input issued",
            "config": asdict(config),
        }
        print(json.dumps(payload, sort_keys=True))
        return 0
    if (
        not config.enabled
        or config.reward_kind != "food"
        or config.maximum_free_collections_per_hold > 10
        or config.maximum_hold_duration_ms > 12_000
        or not config.direct_building_route_enabled
        or config.quest_go_fallback_enabled
        or config.production_registration_enabled
        or config.scheduler_eligible
    ):
        raise RuntimeError("unsafe Supply Depot hold configuration")

    runtime = LocalBlueStacksRuntime.connect(
        adb=args.adb,
        serial=args.serial,
        output_directory=args.output_directory,
        workflow="supply-depot-collect-free-hold",
        execute=True,
    )
    result_path = runtime.session / "collect-free-hold-result.json"
    source = runtime.capture("hold-source")
    source_recognition = recognize_supply_depot_screen(source.frame)
    source_control = _select_authorized_control(source_recognition)
    if source_control is None or source_control.reward_kind != config.reward_kind:
        result = {
            "status": "blocked",
            "reason": "source_exact_food_free_target_not_authorized",
            "recognition": _recognition_payload(source_recognition),
            "actions_dispatched": 0,
            "session": str(runtime.session),
        }
        _json(result_path, result)
        print(json.dumps(result, sort_keys=True, default=str))
        return 3

    immediate_before = runtime.capture("hold-immediate-before")
    before_recognition = recognize_supply_depot_screen(immediate_before.frame)
    before_control = _select_authorized_control(before_recognition)
    before = _observation(immediate_before, before_recognition, before_control) if before_control is not None else None
    if (
        before is None
        or before.reward_kind != config.reward_kind
        or before_recognition.daily_free_attempts != source_recognition.daily_free_attempts
        or before_recognition.frame_sha256 != frame_digest(immediate_before.frame)
        or not supply_depot_authorizeable(before)
    ):
        result = {
            "status": "blocked",
            "reason": "immediate_before_exact_food_free_target_not_authorized",
            "source_recognition": _recognition_payload(source_recognition),
            "before_recognition": _recognition_payload(before_recognition),
            "actions_dispatched": 0,
            "session": str(runtime.session),
        }
        _json(result_path, result)
        print(json.dumps(result, sort_keys=True, default=str))
        return 3

    assert before.daily_free_attempts is not None
    try:
        duration_ms = config.duration_ms(before.daily_free_attempts)
    except ValueError:
        result = {
            "status": "blocked",
            "reason": "free_attempt_count_outside_hold_limit",
            "attempts": before.daily_free_attempts,
            "actions_dispatched": 0,
            "session": str(runtime.session),
        }
        _json(result_path, result)
        print(json.dumps(result, sort_keys=True, default=str))
        return 3

    action_key = (
        f"supply-depot-free-hold:bluestacks:no-reset:attempts-"
        f"{before.daily_free_attempts}:{before.reward_kind}"
    )
    ledger_path = args.output_directory / ACTION_LEDGER_NAME
    ledger = _load_ledger(ledger_path)
    active = {
        key: record
        for key, record in ledger.items()
        if record.get("status") in {"prepared", "dispatched", "unresolved"}
    }
    if active:
        result = {
            "status": "blocked",
            "reason": "active_or_unresolved_supply_depot_action",
            "active_action_keys": sorted(active),
            "actions_dispatched": 0,
            "session": str(runtime.session),
        }
        _json(result_path, result)
        print(json.dumps(result, sort_keys=True, default=str))
        return 3
    if action_key in ledger:
        result = {
            "status": "blocked",
            "reason": "duplicate_action_key",
            "action_key": action_key,
            "prior": ledger[action_key],
            "actions_dispatched": 0,
            "session": str(runtime.session),
        }
        _json(result_path, result)
        print(json.dumps(result, sort_keys=True, default=str))
        return 3

    common = {
        "source_sha256": source.sha256,
        "immediate_before_sha256": immediate_before.sha256,
        "reward_kind": before.reward_kind,
        "daily_free_attempts_before": before.daily_free_attempts,
        "hold_duration_ms": duration_ms,
        "session": str(runtime.session),
    }
    _record_ledger(ledger_path, ledger, action_key, status="prepared", **common)
    runtime.long_press(
        immediate_before,
        target_identity="supply-depot-free-hold-food",
        target_roi=before.target_roi,
        duration_ms=duration_ms,
        action_key=action_key,
        consequential=True,
    )
    _record_ledger(ledger_path, ledger, action_key, status="dispatched", **common)
    immediate_post = runtime.capture("hold-immediate-post")
    time.sleep(args.settle_seconds)
    settled = runtime.capture("hold-settled")
    post_recognition = recognize_supply_depot_screen(immediate_post.frame)
    settled_recognition = recognize_supply_depot_screen(settled.frame)
    successor = _successor_observation(before, settled, settled_recognition)
    settled_food = next((item for item in settled_recognition.controls if item.reward_kind == "food"), None)
    exact_settled = bool(
        settled_recognition.recognized
        and not settled_recognition.overlay
        and settled_recognition.ambiguity == "none"
        and settled_recognition.daily_free_attempts is not None
    )
    exhausted = bool(
        exact_settled
        and supply_depot_hold_postcondition_verified(
            before,
            successor,
            maximum_attempts=config.maximum_free_collections_per_hold,
        )
        and settled_food is not None
        and not settled_food.zero_cost
        and settled_food.state != "available_free"
    )
    attempts_after = settled_recognition.daily_free_attempts if exact_settled else None
    decrease = before.daily_free_attempts - attempts_after if attempts_after is not None else None
    partial = bool(exact_settled and decrease is not None and 0 < decrease < before.daily_free_attempts)
    runtime_status = "confirmed" if exhausted or partial else "unresolved"
    if exhausted:
        result_status = "completed"
        ledger_status = "confirmed_exhausted"
        reason = "food_hold_exhausted_exact_observed_free_attempts"
    elif partial:
        result_status = "partial"
        ledger_status = "confirmed_partial"
        reason = "food_hold_decreased_attempts_but_did_not_exhaust_no_retry"
    else:
        result_status = "unresolved"
        ledger_status = "unresolved"
        reason = "food_hold_semantic_result_ambiguous_no_retry"
    runtime.reconcile(action_key, runtime_status, settled, reason)
    _record_ledger(
        ledger_path,
        ledger,
        action_key,
        status=ledger_status,
        **common,
        immediate_post_sha256=immediate_post.sha256,
        settled_sha256=settled.sha256,
        daily_free_attempts_after=attempts_after,
        free_collections_confirmed=decrease if decrease is not None and decrease > 0 else 0,
        food_control_state_after=settled_food.state if settled_food is not None else None,
        reason=reason,
    )
    result = {
        "status": result_status,
        "reason": reason,
        "action_key": action_key,
        "actions_dispatched": 1,
        "hold_duration_ms": duration_ms,
        "free_collections_confirmed": decrease if decrease is not None and decrease > 0 else 0,
        "source_sha256": source.sha256,
        "immediate_before_sha256": immediate_before.sha256,
        "immediate_post_sha256": immediate_post.sha256,
        "settled_sha256": settled.sha256,
        "before": _recognition_payload(before_recognition),
        "immediate_post": _recognition_payload(post_recognition),
        "settled": _recognition_payload(settled_recognition),
        "config": asdict(config),
        "session": str(runtime.session),
    }
    _json(result_path, result)
    print(json.dumps(result, sort_keys=True, default=str))
    return 0 if exhausted else (5 if partial else 4)


def command_reconcile_free_hold(args) -> int:
    """Resolve one prior hold from a fresh exact exhausted-state capture; issue no input."""

    if not args.execute or not args.yes:
        print(json.dumps({"status": "dry_run", "reason": "reconciliation requires --execute and --yes; no runtime input issued"}, sort_keys=True))
        return 0
    ledger_path = args.output_directory / ACTION_LEDGER_NAME
    ledger = _load_ledger(ledger_path)
    unresolved = {
        key: record
        for key, record in ledger.items()
        if key.startswith("supply-depot-free-hold:") and record.get("status") == "unresolved"
    }
    if len(unresolved) != 1:
        print(json.dumps({"status": "blocked", "reason": "exactly_one_unresolved_food_hold_required", "action_keys": sorted(unresolved)}, sort_keys=True))
        return 3
    action_key, prior = next(iter(unresolved.items()))
    attempts_before = prior.get("daily_free_attempts_before")
    if prior.get("reward_kind") != "food" or not isinstance(attempts_before, int) or not 1 <= attempts_before <= 10:
        print(json.dumps({"status": "blocked", "reason": "unresolved_hold_record_is_not_bounded_food"}, sort_keys=True))
        return 3

    runtime = LocalBlueStacksRuntime.connect(
        adb=args.adb,
        serial=args.serial,
        output_directory=args.output_directory,
        workflow="supply-depot-reconcile-free-hold",
        execute=False,
    )
    captured = runtime.capture("reconcile-source")
    recognition = recognize_supply_depot_screen(captured.frame)
    exact_exhausted = bool(
        recognition.recognized
        and not recognition.overlay
        and recognition.ambiguity == "none"
        and recognition.daily_free_attempts == 0
        and tuple(control.reward_kind for control in recognition.controls) == ("food", "wood", "steel", "gas")
        and all(not control.zero_cost and control.state == "paid_or_purchase" for control in recognition.controls)
    )
    if not exact_exhausted:
        result = {
            "status": "blocked",
            "reason": "fresh_exact_exhausted_successor_not_proven",
            "action_key": action_key,
            "actions_dispatched": 0,
            "recognition": _recognition_payload(recognition),
            "session": str(runtime.session),
        }
        _json(runtime.session / "reconcile-free-hold-result.json", result)
        print(json.dumps(result, sort_keys=True, default=str))
        return 3

    reconciled = dict(prior)
    reconciled.update(
        status="confirmed_exhausted",
        reconciliation="fresh_exact_zero_attempts_and_all_controls_paid",
        reconciliation_frame_sha256=captured.sha256,
        reconciliation_evidence=_relative_evidence(captured.path),
        reconciliation_session=str(runtime.session),
        daily_free_attempts_after=0,
        free_collections_confirmed=attempts_before,
        food_control_state_after="paid_or_purchase",
        reason="food_hold_exhausted_exact_observed_free_attempts_reconciled",
    )
    _record_ledger(ledger_path, ledger, action_key, **reconciled)
    result = {
        "status": "completed",
        "reason": reconciled["reason"],
        "action_key": action_key,
        "actions_dispatched": 0,
        "free_collections_confirmed": attempts_before,
        "recognition": _recognition_payload(recognition),
        "session": str(runtime.session),
    }
    _json(runtime.session / "reconcile-free-hold-result.json", result)
    print(json.dumps(result, sort_keys=True, default=str))
    return 0


def command_return_home(args) -> int:
    if not args.execute or not args.yes:
        print(json.dumps({"status": "dry_run", "reason": "return-home requires both --execute and --yes; no runtime input issued"}, sort_keys=True))
        return 0
    atlas = load_home_atlas(args.atlas)
    localizer = BlueStacksHomeLocalizer(atlas, args.atlas)
    runtime = LocalBlueStacksRuntime.connect(
        adb=args.adb,
        serial=args.serial,
        output_directory=args.output_directory,
        workflow="supply-depot-return-home",
        execute=True,
    )
    source = runtime.capture("return-home-source")
    source_recognition = recognize_supply_depot_screen(source.frame)
    if not source_recognition.recognized or source_recognition.overlay or source_recognition.ambiguity != "none":
        result = {"status": "blocked", "reason": "source_supply_depot_not_exact", "recognition": _recognition_payload(source_recognition), "actions_dispatched": 0, "session": str(runtime.session)}
        _json(runtime.session / "return-home-result.json", result)
        print(json.dumps(result, sort_keys=True, default=str))
        return 3
    immediate_before = runtime.capture("return-home-immediate-before")
    before_recognition = recognize_supply_depot_screen(immediate_before.frame)
    if not before_recognition.recognized or before_recognition.overlay or before_recognition.ambiguity != "none":
        result = {"status": "blocked", "reason": "immediate_before_supply_depot_not_exact", "recognition": _recognition_payload(before_recognition), "actions_dispatched": 0, "session": str(runtime.session)}
        _json(runtime.session / "return-home-result.json", result)
        print(json.dumps(result, sort_keys=True, default=str))
        return 3
    action_key = f"supply-depot-return-home-{int(time.time() * 1000)}"
    runtime.back(immediate_before, action_key=action_key)
    immediate_post = runtime.capture("return-home-immediate-post")
    time.sleep(args.settle_seconds)
    settled = runtime.capture("return-home-settled")
    localization = localizer.localize(settled.frame)
    completed = localization.recognized and localization.zoom_identity is ZoomIdentity.FULLY_ZOOMED_OUT
    result = {
        "status": "completed" if completed else "blocked",
        "reason": "exact_canonical_zoom_home_successor" if completed else "home_successor_not_localized",
        "action_key": action_key,
        "actions_dispatched": 1,
        "source_sha256": source.sha256,
        "immediate_before_sha256": immediate_before.sha256,
        "immediate_post_sha256": immediate_post.sha256,
        "settled_sha256": settled.sha256,
        "localization": asdict(localization),
        "session": str(runtime.session),
    }
    _json(runtime.session / "return-home-result.json", result)
    print(json.dumps(result, sort_keys=True, default=str))
    return 0 if completed else 3


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect")
    inspect.add_argument("--frame", type=Path)
    inspect.add_argument("--adb")
    inspect.add_argument("--serial")
    inspect.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT)

    collect = sub.add_parser("collect-one")
    collect.add_argument("--adb")
    collect.add_argument("--serial")
    collect.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT)
    collect.add_argument("--settle-seconds", type=float, default=2.0)
    collect.add_argument("--execute", action="store_true")
    collect.add_argument("--yes", action="store_true")

    for name in ("collect-free", "collect-free-hold"):
        hold = sub.add_parser(name)
        hold.add_argument("--adb")
        hold.add_argument("--serial")
        hold.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT)
        hold.add_argument("--settle-seconds", type=float, default=3.0)
        hold.add_argument("--execute", action="store_true")
        hold.add_argument("--yes", action="store_true")

    reconcile = sub.add_parser("reconcile-free-hold")
    reconcile.add_argument("--adb")
    reconcile.add_argument("--serial")
    reconcile.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT)
    reconcile.add_argument("--execute", action="store_true")
    reconcile.add_argument("--yes", action="store_true")

    home = sub.add_parser("return-home")
    home.add_argument("--adb")
    home.add_argument("--serial")
    home.add_argument("--atlas", type=Path, required=True)
    home.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT)
    home.add_argument("--settle-seconds", type=float, default=2.0)
    home.add_argument("--execute", action="store_true")
    home.add_argument("--yes", action="store_true")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "inspect" and args.frame is None and (not args.adb or not args.serial):
        raise SystemExit("live inspect requires --adb and --serial")
    if args.command in {"collect-one", "collect-free", "collect-free-hold", "reconcile-free-hold", "return-home"} and args.execute and (not args.adb or not args.serial):
        raise SystemExit(f"executing {args.command} requires --adb and --serial")
    return {
        "inspect": command_inspect,
        "collect-one": command_collect_one,
        "collect-free": command_collect_free_hold,
        "collect-free-hold": command_collect_free_hold,
        "reconcile-free-hold": command_reconcile_free_hold,
        "return-home": command_return_home,
    }[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
