"""Lean BlueStacks Supply Depot flow: Home -> Depot -> exhaust Free -> Home."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import time
from typing import Any

from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
from scripts.home_atlas_bluestacks import (
    ScrcpyMotionEventZoomTransport,
    bluestacks_direct_pan_contract,
    build_supply_depot_facility_safe_exit_probe,
    identity_from_captured,
    recognize_supply_depot_home_successor,
    require_binder_selected_safe_exit_roi,
)
from scripts.navigation_development_boundary import DevelopmentSession
from tasks.home_atlas import load_home_atlas
from tasks.home_atlas_planner import DirectPanNavigator, PlanDisposition
from tasks.home_atlas_vision import BlueStacksHomeLocalizer
from tasks.home_nav_recognition import recognize_home_nav
from tasks.supply_depot import SupplyDepotHoldConfig
from tasks.supply_depot_vision import (
    SUPPLY_DEPOT_BUILDING_ID,
    bind_supply_depot_building,
    bind_supply_depot_claim_supply,
    recognize_supply_depot_screen,
)


ROOT = Path(__file__).resolve().parents[1]
ATLAS_PATH = (
    ROOT / "tasks" / "assets" / "home_atlas" / "bluestacks" / "800x1280" / "atlas.json"
)
MAX_PANS = 6


def _identity(runtime: LocalBlueStacksRuntime, captured, label: str):
    return identity_from_captured(
        captured,
        session_id=str(runtime.session),
        ordinal=int(runtime.ordinal),
        label=label,
    )


def _recognize(runtime: LocalBlueStacksRuntime, captured, label: str):
    return recognize_supply_depot_screen(
        captured.frame,
        source_frame=_identity(runtime, captured, label),
    )


def select_free_food_control(recognition):
    """Select only the exact free Food control from a fully recognized screen."""

    if (
        not recognition.recognized
        or recognition.state != "available"
        or recognition.overlay
        or recognition.premium_or_purchase_visible
        or recognition.ambiguity != "none"
        or recognition.daily_free_attempts is None
        or not 1 <= recognition.daily_free_attempts <= 10
        or len(recognition.controls) != 4
    ):
        return None
    matches = [
        control
        for control in recognition.controls
        if control.reward_kind == "food"
        and control.state == "available_free"
        and control.zero_cost
    ]
    return matches[0] if len(matches) == 1 else None


def exhausted_free_state(recognition) -> bool:
    """Prove Free has disappeared after the observed attempts reach zero."""

    return bool(
        recognition.recognized
        and not recognition.overlay
        and recognition.ambiguity == "none"
        and recognition.daily_free_attempts == 0
        and tuple(control.reward_kind for control in recognition.controls)
        == ("food", "wood", "steel", "gas")
        and all(not control.zero_cost for control in recognition.controls)
    )


def _pnsctl():
    from scripts import pnsctl

    return pnsctl


def _build_home_zoom_transport(runtime: LocalBlueStacksRuntime):
    pnsctl = _pnsctl()
    return ScrcpyMotionEventZoomTransport(
        adb=str(pnsctl.BLUESTACKS_ADB),
        serial=pnsctl.BLUESTACKS_SERIAL,
        evidence_directory=runtime.session / "scrcpy-zoom",
    )


def _dispatch_home_zoom_out(
    runtime: LocalBlueStacksRuntime,
    before,
    *,
    zoom_transport,
) -> None:
    if not recognize_home_nav(before.frame).is_home:
        raise RuntimeError("Home context lost before zoom")
    runtime.dispatch_external_zoom(
        before,
        action_key=f"supply-depot-home-zoom-out:{before.sha256[:12]}",
        transport=zoom_transport.zoom_out_once,
    )


def _bind_home_building(runtime: LocalBlueStacksRuntime, captured):
    identity = _identity(runtime, captured, "supply-depot-home")
    atlas = load_home_atlas(ATLAS_PATH)
    localization = BlueStacksHomeLocalizer(atlas, ATLAS_PATH).localize(captured.frame)
    if (
        not localization.recognized
        or localization.frame_sha256 != identity.semantic_sha256
    ):
        return localization, None
    return (
        localization,
        bind_supply_depot_building(
            captured.frame,
            localization,
            atlas.lookup_building(SUPPLY_DEPOT_BUILDING_ID),
            source_frame=identity,
        ),
    )


def run(
    *,
    session: DevelopmentSession,
    runtime: LocalBlueStacksRuntime,
    session_directory: Path,
    settle_seconds: float = 1.5,
) -> dict[str, Any]:
    """Execute one bounded all-free-attempt collection pass."""

    result: dict[str, Any] = {
        "status": "blocked",
        "reason": "not_started",
        "steps": [],
        "terminal_home_verified": False,
        "free_attempts_before": None,
        "free_attempts_after": None,
        "hold_transport_calls": 0,
    }

    def capture(label: str):
        return runtime.capture(label)

    atlas = load_home_atlas(ATLAS_PATH)
    safe, calibration = bluestacks_direct_pan_contract()
    navigator = DirectPanNavigator(
        atlas,
        SUPPLY_DEPOT_BUILDING_ID,
        safe,
        calibration,
        maximum_pans=MAX_PANS,
    )

    current = session.observe(capture, label="supply-depot-source")
    current_screen = _recognize(runtime, current, "supply-depot-source")
    if not current_screen.recognized:
        initial_localization = BlueStacksHomeLocalizer(atlas, ATLAS_PATH).localize(
            current.frame
        )
        if not initial_localization.recognized:
            home_context = recognize_home_nav(current.frame)
            if not home_context.is_home:
                result["reason"] = "source_is_not_home_or_supply_depot"
                session.terminal_status = "evidence_required"
                return result

            zoom_transport = _build_home_zoom_transport(runtime)

            def dispatch_zoom(before):
                _dispatch_home_zoom_out(
                    runtime,
                    before,
                    zoom_transport=zoom_transport,
                )

            def recognize_zoom(_after):
                time.sleep(settle_seconds)
                settled = capture("supply-depot-home-zoom-settled")
                localization = BlueStacksHomeLocalizer(
                    atlas, ATLAS_PATH
                ).localize(settled.frame)
                return "home_canonical" if localization.recognized else "unknown"

            action = session.run_action(
                action_class="navigation",
                label="supply-depot-home-zoom-out",
                capture=capture,
                dispatch=dispatch_zoom,
                recognize=recognize_zoom,
                consequence_class="navigation_only",
            )
            if action.status != "completed":
                result["reason"] = "home_zoom_out_not_verified"
                session.terminal_status = "evidence_required"
                return result

        for pan_index in range(MAX_PANS):
            current = session.observe(
                capture, label=f"supply-depot-pan-{pan_index}-source"
            )
            localization, binding = _bind_home_building(runtime, current)
            if not localization.recognized:
                result["reason"] = "home_not_localized"
                break
            plan = navigator.plan(localization, None)
            result["steps"].append(
                {
                    "step": f"pan_plan_{pan_index}",
                    "disposition": plan.disposition.value,
                    "reason": plan.reason,
                }
            )
            if plan.disposition in {
                PlanDisposition.COMPLETE,
                PlanDisposition.BIND,
                PlanDisposition.ALREADY_SAFE,
            }:
                break
            if (
                plan.disposition is not PlanDisposition.PAN
                or plan.drag_start is None
                or plan.drag_end is None
            ):
                result["reason"] = f"pan_blocked:{plan.reason}"
                break

            def dispatch_pan(
                before,
                start=plan.drag_start,
                end=plan.drag_end,
                index=pan_index,
            ):
                runtime.swipe(
                    before,
                    start=start,
                    end=end,
                    action_key=f"supply-depot-pan:{index}:{before.sha256[:12]}",
                    target_identity="home-camera-click-drag",
                )

            def recognize_pan(_after, before_loc=localization):
                time.sleep(settle_seconds)
                settled = capture(f"supply-depot-pan-{pan_index}-settled")
                after_loc = BlueStacksHomeLocalizer(atlas, ATLAS_PATH).localize(
                    settled.frame
                )
                progress = navigator.record_progress(before_loc, after_loc)
                return "home_panned" if progress.accepted else "unknown"

            action = session.run_action(
                action_class="navigation",
                label=f"supply-depot-pan-{pan_index}",
                capture=capture,
                dispatch=dispatch_pan,
                recognize=recognize_pan,
                consequence_class="navigation_only",
            )
            if action.status != "completed":
                result["reason"] = f"pan_no_progress:{pan_index}"
                break
        else:
            result["reason"] = "maximum_pans_exhausted"

        home = session.observe(capture, label="supply-depot-home-bound")
        _localization, building = _bind_home_building(runtime, home)
        radial = bind_supply_depot_claim_supply(
            home.frame,
            source_frame=_identity(runtime, home, "supply-depot-home-bound"),
        )
        if radial is None:
            if building is None:
                result["reason"] = "supply_depot_building_not_bound"
                session.terminal_status = "evidence_required"
                return result

            def dispatch_building(before):
                _loc, rebound = _bind_home_building(runtime, before)
                if rebound is None:
                    raise RuntimeError("Supply Depot building rebound failed")
                runtime.tap(
                    before,
                    target_identity=SUPPLY_DEPOT_BUILDING_ID,
                    target_roi=tuple(int(value) for value in rebound.target_roi),
                    action_key=f"open-supply-depot:{before.sha256[:12]}",
                )

            def recognize_radial(_after):
                time.sleep(settle_seconds)
                settled = capture("supply-depot-radial-settled")
                rebound = bind_supply_depot_claim_supply(
                    settled.frame,
                    source_frame=_identity(
                        runtime, settled, "supply-depot-radial-settled"
                    ),
                )
                return "supply_depot_radial" if rebound is not None else "unknown"

            action = session.run_action(
                action_class="navigation",
                label="open-supply-depot-building",
                capture=capture,
                dispatch=dispatch_building,
                recognize=recognize_radial,
                target_roi=tuple(int(value) for value in building.target_roi),
                consequence_class="navigation_only",
            )
            if action.status != "completed":
                result["reason"] = "supply_depot_radial_not_recognized"
                session.terminal_status = "evidence_required"
                return result

        def dispatch_radial(before):
            rebound = bind_supply_depot_claim_supply(
                before.frame,
                source_frame=_identity(runtime, before, "supply-depot-radial-before"),
            )
            if rebound is None:
                raise RuntimeError("Claim Supply rebound failed")
            runtime.tap(
                before,
                target_identity="supply-depot-claim-supply-navigation",
                target_roi=tuple(int(value) for value in rebound.target_roi),
                action_key=f"open-supply-depot-screen:{before.sha256[:12]}",
            )

        def recognize_facility(_after):
            time.sleep(settle_seconds)
            settled = capture("supply-depot-facility-settled")
            recognized = _recognize(
                runtime, settled, "supply-depot-facility-settled"
            )
            return "supply_depot" if recognized.recognized else "unknown"

        action = session.run_action(
            action_class="navigation",
            label="open-supply-depot-screen",
            capture=capture,
            dispatch=dispatch_radial,
            recognize=recognize_facility,
            consequence_class="navigation_only",
        )
        if action.status != "completed":
            result["reason"] = "supply_depot_screen_not_recognized"
            session.terminal_status = "evidence_required"
            return result

    facility = session.observe(capture, label="supply-depot-free-source")
    recognition = _recognize(runtime, facility, "supply-depot-free-source")
    result["source_recognition"] = asdict(recognition)

    if exhausted_free_state(recognition):
        result["free_attempts_before"] = 0
        result["free_attempts_after"] = 0
        result["reason"] = "free_attempts_already_exhausted"
    else:
        control = select_free_food_control(recognition)
        if control is None:
            result["reason"] = "exact_free_food_control_not_authorized"
            session.terminal_status = "evidence_required"
            return result
        attempts = int(recognition.daily_free_attempts)
        duration_ms = SupplyDepotHoldConfig().duration_ms(attempts)
        result["free_attempts_before"] = attempts

        def dispatch_hold(before):
            fresh = _recognize(runtime, before, "supply-depot-hold-before")
            fresh_control = select_free_food_control(fresh)
            if (
                fresh_control is None
                or fresh.daily_free_attempts != attempts
                or fresh_control.roi != control.roi
            ):
                raise RuntimeError("Supply Depot free target changed before hold")
            runtime.long_press(
                before,
                target_identity="supply-depot-free-food-hold",
                target_roi=fresh_control.roi,
                duration_ms=duration_ms,
                action_key=f"supply-depot-free-hold:{attempts}:{before.sha256[:12]}",
                consequential=False,
            )

        successor: dict[str, Any] = {}

        def recognize_exhausted(_after):
            time.sleep(settle_seconds)
            settled = capture("supply-depot-free-settled")
            observed = _recognize(
                runtime, settled, "supply-depot-free-settled"
            )
            successor["recognition"] = observed
            return "supply_depot_free_exhausted" if exhausted_free_state(observed) else "unknown"

        action = session.run_action(
            action_class="resource_collection",
            label="supply-depot-free-hold",
            capture=capture,
            dispatch=dispatch_hold,
            recognize=recognize_exhausted,
            target_roi=control.roi,
            consequence_class="ordinary_development",
        )
        result["hold_transport_calls"] = 1
        observed = successor.get("recognition")
        if observed is not None:
            result["successor_recognition"] = asdict(observed)
            result["free_attempts_after"] = observed.daily_free_attempts
        if action.status != "completed":
            result["reason"] = "free_attempt_exhaustion_not_proven"
            session.terminal_status = "evidence_required"
            return result
        result["reason"] = "all_observed_free_attempts_exhausted"

    def dispatch_exit(before):
        exact = _recognize(runtime, before, "supply-depot-exit-before")
        if not exact.recognized:
            raise RuntimeError("Supply Depot screen not recognized before exit")
        identity = _identity(runtime, before, "supply-depot-exit-before")
        roi = require_binder_selected_safe_exit_roi(
            build_supply_depot_facility_safe_exit_probe(identity)
        )
        runtime.tap(
            before,
            target_identity="supply-depot-back-arrow",
            target_roi=roi,
            action_key=f"supply-depot-visible-exit:{before.sha256[:12]}",
        )

    home_result: dict[str, Any] = {}

    def recognize_home(_after):
        time.sleep(settle_seconds)
        settled = capture("supply-depot-home-settled")
        identity = _identity(runtime, settled, "supply-depot-home-settled")
        home = recognize_supply_depot_home_successor(
            settled.frame,
            atlas_path=ATLAS_PATH,
            source_frame=identity,
        )
        home_result["verified"] = home is not None and home.recognized
        return "home_verified" if home_result["verified"] else "unknown"

    action = session.run_action(
        action_class="navigation",
        label="supply-depot-visible-exit",
        capture=capture,
        dispatch=dispatch_exit,
        recognize=recognize_home,
        consequence_class="navigation_only",
    )
    result["terminal_home_verified"] = bool(home_result.get("verified"))
    if action.status == "completed" and result["terminal_home_verified"]:
        result["status"] = "completed"
        session.terminal_status = "completed"
    else:
        result["status"] = "blocked"
        result["reason"] = "terminal_home_not_verified"
        session.terminal_status = "evidence_required"

    (session_directory / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return result
