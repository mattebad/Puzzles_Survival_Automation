"""Lean BlueStacks Supply Depot flow: Home -> Depot -> exhaust Free -> Home."""

from __future__ import annotations


from dataclasses import asdict, replace
import json
import math
import re
from pathlib import Path
import time
from typing import Any

import cv2
import numpy as np
import pytesseract

from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
from scripts.atlas_startup_normalizer import (
    AtlasStartupDisposition,
    BlueStacksAtlasStartupNormalizer,
)
from scripts.home_atlas_bluestacks import (
    ScrcpyMotionEventZoomTransport,
    bluestacks_direct_pan_contract,
    build_supply_depot_facility_safe_exit_probe,
    identity_from_captured,
    inward_rounded_camera_pan,
    recognize_supply_depot_home_successor,
    require_binder_selected_safe_exit_roi,
)
from scripts.navigation_development_boundary import DevelopmentSession, NavigationGuardedRuntime, NavigationRouteDeclaration, make_source_safety_facts
from tasks.home_atlas import load_home_atlas
from tasks.home_atlas_planner import DirectPanNavigator, PlanDisposition, camera_origin, plan_direct_pan
from scripts.startup_normalization import is_clean_home_frame
from tasks.home_atlas_vision import BlueStacksHomeLocalizer, bind_visible_building, frame_digest
from tasks.perception_bundle import PerceptionBundleError
from tasks.supply_depot import SupplyDepotHoldConfig
from tasks.supply_depot_vision import (
    SUPPLY_DEPOT_BUILDING_ID,
    bind_supply_depot_claim_supply,
    bind_home_event_drawer_toggle,
    recognize_supply_depot_screen,
    recognize_supply_depot_radial,
    _safe_claim_label_region,
)
from tasks.runtime_identity import BLUESTACKS_ADB, BLUESTACKS_SERIAL


PAN_PRE_DISPATCH_REASON_CODE = "PRE_DISPATCH_HOME_NOT_CLEAN"

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
        source_png=captured.png,
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
        adb=str(BLUESTACKS_ADB),
        serial=BLUESTACKS_SERIAL,
        evidence_directory=runtime.session / "scrcpy-zoom",
    )


def _supply_pan_contract():
    safe, calibration = bluestacks_direct_pan_contract()
    # Current native menus place the Supply label about 52 px right and 130 px
    # below the mapped anchor. Leave a real label interior before the fixed
    # lower-right HUD, rather than accepting the building's visible edge alone.
    return replace(safe, screen_box=(safe.screen_box[0], safe.screen_box[1], 604, 820)), calibration


def _supply_entry_viewport_safe(atlas, localization) -> bool:
    """Geometry-only menu forecast; current measured controls still own taps."""
    if (not localization.recognized or localization.stale or localization.overlay
            or localization.screen_to_atlas is None):
        return False
    try:
        matrix = np.asarray(localization.screen_to_atlas, dtype=float)
        anchor = np.linalg.solve(matrix, (*atlas.lookup_building(SUPPLY_DEPOT_BUILDING_ID).interaction_anchor, 1.))
        if not np.isfinite(anchor).all() or not math.isclose(float(anchor[2]), 1.):
            return False
        x, y = map(float, anchor[:2])
        # Measured label envelope from retained native raised/current radials.
        # It never replaces the actual exact Claim+Supply OCR binding.
        predicted_label = (math.floor(x + 50), math.floor(y + 125),
                           math.ceil(x + 125), math.ceil(y + 160))
        return _safe_claim_label_region(predicted_label) is not None
    except (TypeError, ValueError, IndexError, np.linalg.LinAlgError):
        return False


def _plan_supply_entry(navigator, localization, *, reframe_used: bool):
    """Permit one camera-only waypoint when the final drag is below calibration."""
    plan = navigator.plan(localization, None)
    too_short = plan.reason == "gesture_below_effective_minimum" or (
        plan.reason == "no_recoverable_actionable_viewport"
        and dict(plan.viewport.rejection_counts).get("gesture_below_effective_minimum", 0) > 0)
    if (not too_short or reframe_used or navigator.pan_count >= navigator.maximum_pans):
        return _checked_supply_camera_plan(navigator, localization, plan), navigator, False
    # The low waypoint makes the following final approach a real >=65 px drag.
    # No building or Claim tap is permitted there. Fresh Home and measured
    # progress are required before the normal final-placement planner resumes.
    waypoint = replace(navigator.safe_region, screen_box=(145, 900, 650, 1010),
                       placement_anchor=(602, 956), planning_policy=None)
    camera_only = DirectPanNavigator(navigator.atlas, SUPPLY_DEPOT_BUILDING_ID,
        waypoint, navigator.calibration, maximum_pans=1)
    candidate = camera_only.plan(localization, None)
    if candidate.disposition is not PlanDisposition.PAN:
        return plan, navigator, False
    return _checked_supply_camera_plan(camera_only, localization, candidate), camera_only, True


def _checked_supply_camera_plan(navigator, localization, plan):
    if plan.disposition is not PlanDisposition.PAN:
        return plan
    candidate = inward_rounded_camera_pan(navigator, localization, plan)
    try:
        current = camera_origin(localization)
        desired = candidate.viewport.desired_camera_origin
        bounds = navigator.atlas.camera_origin_bounds
        predicted = tuple(current[axis] + candidate.predicted_camera_displacement[axis] for axis in (0, 1))
        valid = bounds is not None and desired is not None and all(
            math.isfinite(value) and bounds[axis] <= value <= bounds[axis + 2]
            for point in (current, desired, predicted) for axis, value in enumerate(point))
        valid = bool(valid and math.dist(predicted, desired) < math.dist(current, desired))
    except (TypeError, ValueError, IndexError):
        valid = False
    if not valid:
        return replace(candidate, disposition=PlanDisposition.REJECTED,
            reason="supply_camera_pan_geometry_unsafe", viewport=replace(candidate.viewport,
                disposition=PlanDisposition.REJECTED, reason="supply_camera_pan_geometry_unsafe"))
    navigator.last_plan = candidate
    return candidate


def _dispatch_home_zoom_out(runtime: LocalBlueStacksRuntime, before, *, zoom_transport) -> None:
    guarded = NavigationGuardedRuntime(
        runtime,
        NavigationRouteDeclaration(
            allowed_source_states=frozenset({"HOME_BASE"}),
            allowed_target_identities=frozenset({"home-zoom-out"}),
            allowed_gesture_classes=frozenset({"zoom_out"}),
        ),
    )
    guarded.dispatch_zoom_out(
        before,
        make_source_safety_facts(
            recognized=True,
            source_state="HOME_BASE",
            overlay_state="none_observed",
            frame_sha256=before.sha256,
            captured_monotonic=before.captured_monotonic,
        ),
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
        bind_visible_building(captured.frame,
        localization,
        atlas.lookup_building(SUPPLY_DEPOT_BUILDING_ID), home_is_clean=is_clean_home_frame),
    )


def _arena_exit_target(frame):
    """Bind the visible game arrow only on the exact Arena landing page."""
    from scripts.bluestacks_popup_recognition import recognize_reset_popup
    from scripts.daily_resource_item_bluestacks import _bag_back_arrow_visual

    target = _bag_back_arrow_visual(frame, maximum_left=90, search_right=180)
    if target is None:
        return None
    popup = recognize_reset_popup(frame)
    if popup.get("recognized") or popup.get("blocking_unknown_modal"):
        return None
    for box, expected in (
        ((335, 7, 480, 56), "arena"),
        ((170, 87, 300, 140), "arena"),
        ((470, 85, 710, 138), "exchange shop"),
    ):
        x0, y0, x1, y1 = box
        crop = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        crop = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        try:
            text = pytesseract.image_to_string(crop, config="--psm 7", timeout=2)
        except (RuntimeError, OSError, ValueError):
            return None
        if " ".join(re.findall(r"[a-z]+", text.lower())) != expected:
            return None
    return target


def _recover_arena_home(session, runtime, capture, *, settle_seconds: float):
    binding = {}

    def authorize(before):
        target = _arena_exit_target(before.frame)
        if target is None:
            raise PerceptionBundleError("ARENA_VISIBLE_BACK_NOT_BOUND")
        binding["roi"] = target

    def dispatch(before):
        runtime.tap(
            before, target_identity="arena-visible-back",
            target_roi=binding["roi"],
            action_key=f"supply-recovery:arena-back:{before.sha256[:12]}",
        )

    def settled():
        time.sleep(settle_seconds)
        return capture("arena-return-home-settled")

    return session.run_action(
        action_class="navigation", label="supply-recovery-arena-back",
        capture=capture, authorize=authorize, dispatch=dispatch,
        recognize=lambda after: "home_after_arena" if is_clean_home_frame(after.frame) else "unknown",
        settled_successor=settled, consequence_class="navigation_only",
    )


def _collapse_home_event_drawer(session, runtime, capture, *, settle_seconds: float):
    binding = {}

    def authorize(before):
        target = bind_home_event_drawer_toggle(before.frame, expanded=True)
        if not is_clean_home_frame(before.frame) or target is None:
            raise PerceptionBundleError("HOME_EVENT_DRAWER_COLLAPSE_NOT_BOUND")
        binding["roi"] = target

    def dispatch(before):
        runtime.tap(before, target_identity="home-event-drawer-collapse", target_roi=binding["roi"],
                    action_key=f"supply-event-drawer-collapse:{before.sha256[:12]}")

    def recognize(after):
        return "home_event_drawer_collapsed" if (
            is_clean_home_frame(after.frame)
            and bind_home_event_drawer_toggle(after.frame, expanded=False) is not None
            and bind_home_event_drawer_toggle(after.frame, expanded=True) is None
        ) else "unknown"

    def settled():
        time.sleep(settle_seconds)
        return capture("supply-event-drawer-collapse-settled")

    return session.run_action(action_class="navigation", label="supply-event-drawer-collapse",
        capture=capture, authorize=authorize, dispatch=dispatch, recognize=recognize,
        settled_successor=settled, consequence_class="navigation_only")


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
    safe, calibration = _supply_pan_contract()
    navigator = DirectPanNavigator(
        atlas,
        SUPPLY_DEPOT_BUILDING_ID,
        safe,
        calibration,
        maximum_pans=MAX_PANS,
    )

    current = session.observe(capture, label="supply-depot-source")
    if _arena_exit_target(current.frame) is not None:
        recovered = _recover_arena_home(session, runtime, capture, settle_seconds=settle_seconds)
        result["steps"].append({"step": "arena_visible_back_recovery", "status": recovered.status})
        if recovered.status != "completed":
            result["reason"] = "arena_return_home_not_verified"
            session.terminal_status = "evidence_required"
            return result
        current = session.observe(capture, label="supply-depot-after-arena-recovery")
    if bind_home_event_drawer_toggle(current.frame, expanded=True) is not None:
        collapsed = _collapse_home_event_drawer(session, runtime, capture, settle_seconds=settle_seconds)
        result["steps"].append({"step": "collapse_home_event_drawer", "status": collapsed.status})
        if collapsed.status != "completed":
            result["reason"] = "home_event_drawer_collapse_not_verified"
            session.terminal_status = "evidence_required"
            return result
        current = session.observe(capture, label="supply-depot-after-event-drawer-collapse")
    current_screen = _recognize(runtime, current, "supply-depot-source")
    if not current_screen.recognized:
        radial = bind_supply_depot_claim_supply(
            current.frame, source_frame=_identity(runtime, current, "supply-depot-source"), source_png=current.png
        )
        if radial is None and recognize_supply_depot_radial(
            current.frame, source_frame=_identity(runtime, current, "supply-depot-source"), source_png=current.png
        ):
            result["reason"] = "supply_radial_not_actionable_no_proven_close"
            session.terminal_status = "evidence_required"
            return result

        if radial is None:

            startup_normalizer = BlueStacksAtlasStartupNormalizer(BlueStacksHomeLocalizer(atlas, ATLAS_PATH),
            maximum_zoom_inputs=2, home_is_clean=is_clean_home_frame)
            startup_frame = current
            startup_step = startup_normalizer.observe(startup_frame.frame)
            while startup_step.disposition is AtlasStartupDisposition.RECOVER_ZOOM:
                if not is_clean_home_frame(startup_frame.frame):
                    result["reason"] = "home_zoom_source_not_recognized"
                    session.terminal_status = "evidence_required"
                    return result
                zoom_transport = _build_home_zoom_transport(runtime)
                cached_before = [startup_frame]
                successor = {}

                def action_capture(label):
                    if cached_before:
                        return cached_before.pop()
                    return capture(label)

                def authorize_zoom(before, planned=startup_step):
                    if before is not startup_frame or planned.source_frame_sha256 != frame_digest(before.frame):
                        raise RuntimeError("home_zoom_source_changed_before_dispatch")

                def dispatch_zoom(before, planned=startup_step):
                    _dispatch_home_zoom_out(runtime, before, zoom_transport=zoom_transport)
                    startup_normalizer.record_zoom_input_dispatched(planned.source_frame_sha256)

                def recognize_zoom(after):
                    if "immediate_post" not in successor:
                        successor["immediate_post"] = after
                        return "unknown"
                    successor["settled"] = after
                    successor["step"] = startup_normalizer.observe(after.frame)
                    if after.sha256 == startup_frame.sha256:
                        successor["no_progress"] = True
                        return "unknown"
                    if successor["step"].disposition is AtlasStartupDisposition.READY:
                        return "home_canonical"
                    if successor["step"].disposition is AtlasStartupDisposition.RECOVER_ZOOM:
                        return "home_zoom_recovery_required"
                    return "unknown"

                def settled_successor():
                    if settle_seconds > 0:
                        time.sleep(settle_seconds)
                    return capture("supply-depot-home-zoom-settled")

                try:
                    action = session.run_action(
                        action_class="navigation",
                        label=f"supply-depot-home-zoom-out:{startup_step.recovery_input_ordinal}",
                        capture=action_capture,
                        dispatch=dispatch_zoom,
                        recognize=recognize_zoom,
                        authorize=authorize_zoom,
                        consequence_class="navigation_only",
                        settled_successor=settled_successor,
                    )
                except Exception as exc:
                    result["reason"] = f"home_zoom_out_blocked:{type(exc).__name__}"
                    session.terminal_status = "evidence_required"
                    return result
                result["steps"].append(
                    {
                        "step": "home_atlas_zoom_normalization",
                        "disposition": startup_step.disposition.value,
                        "reason": startup_step.reason,
                        "source_frame_sha256": startup_step.source_frame_sha256,
                        "recovery_input_ordinal": startup_step.recovery_input_ordinal,
                        "action_status": action.status,
                        "settled_sha256": getattr(successor.get("settled"), "sha256", None),
                    }
                )
                next_step = successor.get("step")
                if action.status != "completed" or next_step is None:
                    result["reason"] = (
                        "home_zoom_out_no_progress"
                        if successor.get("no_progress")
                        else "home_zoom_out_not_verified"
                    )
                    session.terminal_status = "evidence_required"
                    return result
                startup_frame = successor["settled"]
                startup_step = next_step
            result["steps"].append(
                {
                    "step": "home_atlas_zoom_normalization",
                    "disposition": startup_step.disposition.value,
                    "reason": startup_step.reason,
                    "source_frame_sha256": startup_step.source_frame_sha256,
                    "recovery_input_ordinal": startup_step.recovery_input_ordinal,
                }
            )
            if startup_step.disposition is not AtlasStartupDisposition.READY:
                result["reason"] = f"home_zoom_normalization_blocked:{startup_step.reason}"
                session.terminal_status = "evidence_required"
                return result

            reframe_used = False
            for pan_index in range(MAX_PANS):
                current = session.observe(
                    capture, label=f"supply-depot-pan-{pan_index}-source"
                )
                if not is_clean_home_frame(current.frame):
                    result["reason"] = "home_not_clean_before_pan"
                    session.terminal_status = "evidence_required"
                    return result
                localization, binding = _bind_home_building(runtime, current)
                if not localization.recognized:
                    result["reason"] = "home_not_localized"
                    session.terminal_status = "evidence_required"
                    return result
                plan, progress_navigator, is_reframe = _plan_supply_entry(
                    navigator, localization, reframe_used=reframe_used)
                reframe_used = reframe_used or is_reframe
                result["steps"].append(
                    {
                        "step": f"pan_plan_{pan_index}",
                        "disposition": plan.disposition.value,
                        "reason": plan.reason,
                        "camera_only_reframe": is_reframe,
                    }
                )
                if plan.disposition in {
                    PlanDisposition.COMPLETE,
                    PlanDisposition.BIND,
                    PlanDisposition.ALREADY_SAFE,
                }:
                    if not _supply_entry_viewport_safe(atlas, localization):
                        result["reason"] = "supply_menu_viewport_not_safe"
                        session.terminal_status = "evidence_required"
                        return result
                    break
                if (
                    plan.disposition is not PlanDisposition.PAN
                    or plan.drag_start is None
                    or plan.drag_end is None
                ):
                    result["reason"] = f"pan_blocked:{plan.reason}"
                    result["terminal_home_verified"] = is_clean_home_frame(current.frame)
                    session.terminal_status = "evidence_required"
                    return result

                pan_dispatch = {}

                def dispatch_pan(before, index=pan_index):
                    actual = pan_dispatch["plan"]
                    runtime.swipe(
                        before,
                        start=actual.drag_start,
                        end=actual.drag_end,
                        action_key=f"supply-depot-pan:{index}:{before.sha256[:12]}",
                        target_identity="home-camera-click-drag",
                    )
                def authorize_pan(before):
                    if not is_clean_home_frame(before.frame):
                        raise PerceptionBundleError(PAN_PRE_DISPATCH_REASON_CODE)
                    fresh = BlueStacksHomeLocalizer(atlas, ATLAS_PATH).localize(before.frame)
                    actual = _checked_supply_camera_plan(progress_navigator, fresh,
                        plan_direct_pan(atlas, fresh, SUPPLY_DEPOT_BUILDING_ID,
                                        progress_navigator.safe_region, calibration))
                    if (actual.disposition is not PlanDisposition.PAN
                            or actual.viewport.desired_camera_origin != plan.viewport.desired_camera_origin):
                        raise PerceptionBundleError("SUPPLY_CAMERA_PLAN_CHANGED_BEFORE_DISPATCH")
                    pan_dispatch.update(plan=actual, localization=fresh)


                def recognize_pan(_after, before_loc=localization):
                    time.sleep(settle_seconds)
                    settled = capture(f"supply-depot-pan-{pan_index}-settled")
                    after_loc = BlueStacksHomeLocalizer(atlas, ATLAS_PATH).localize(
                        settled.frame
                    )
                    progress = progress_navigator.record_progress(pan_dispatch["localization"], after_loc)
                    return "home_panned" if progress.accepted else "unknown"

                before_input_count = session.input_count
                try:
                    action = session.run_action(
                        action_class="navigation",
                        label=f"supply-depot-pan-{pan_index}",
                        capture=capture,
                        dispatch=dispatch_pan,
                        recognize=recognize_pan,
                        authorize=authorize_pan,
                        consequence_class="navigation_only",
                    )
                except PerceptionBundleError as exc:
                    if (
                        exc.reason_code != PAN_PRE_DISPATCH_REASON_CODE
                        or session.input_count != before_input_count
                    ):
                        raise
                    result.update(
                        {
                            "status": "blocked",
                            "reason": exc.reason_code,
                            "input_count": session.input_count,
                            "transport_dispatched": False,
                        }
                    )
                    session.terminal_status = "evidence_required"
                    session.blocker = exc.reason_code
                    (session_directory / "result.json").write_text(
                        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
                        encoding="utf-8",
                    )
                    return result
                if action.status != "completed":
                    result["reason"] = f"pan_no_progress:{pan_index}"
                    session.terminal_status = "evidence_required"
                    return result
            else:
                result["reason"] = "maximum_pans_exhausted"

            home = session.observe(capture, label="supply-depot-home-bound")
            _localization, building = _bind_home_building(runtime, home)
            radial = bind_supply_depot_claim_supply(
                home.frame,
                source_frame=_identity(runtime, home, "supply-depot-home-bound"),
                source_png=home.png,
            )
            if radial is None:
                if building is None:
                    result["reason"] = "supply_depot_building_not_bound"
                    session.terminal_status = "evidence_required"
                    return result

                building_dispatch = {}

                def authorize_building(before):
                    _loc, rebound = _bind_home_building(runtime, before)
                    if rebound is None:
                        raise RuntimeError("Supply Depot building rebound failed")
                    fresh_plan = plan_direct_pan(atlas, _loc, SUPPLY_DEPOT_BUILDING_ID, safe, calibration)
                    if fresh_plan.disposition not in {PlanDisposition.BIND, PlanDisposition.COMPLETE, PlanDisposition.ALREADY_SAFE}:
                        raise RuntimeError("Supply Depot menu placement changed before dispatch")
                    if not _supply_entry_viewport_safe(atlas, _loc):
                        raise RuntimeError("Supply Depot menu viewport is not safe before dispatch")
                    building_dispatch["binding"] = rebound

                def dispatch_building(before):
                    rebound = building_dispatch["binding"]
                    if rebound.frame_sha256 != frame_digest(before.frame):
                        raise RuntimeError("Supply Depot building binding changed before dispatch")
                    runtime.tap(
                        before,
                        target_identity=SUPPLY_DEPOT_BUILDING_ID,
                        target_roi=tuple(int(value) for value in rebound.target_roi),
                        action_key=f"open-supply-depot:{before.sha256[:12]}",
                    )

                radial_successor = {}

                def recognize_radial(_after):
                    time.sleep(settle_seconds)
                    settled = capture("supply-depot-radial-settled")
                    rebound = bind_supply_depot_claim_supply(
                        settled.frame,
                        source_frame=_identity(
                            runtime, settled, "supply-depot-radial-settled"
                        ),
                        source_png=settled.png,
                    )
                    if rebound is None:
                        radial_successor["identity_recognized"] = recognize_supply_depot_radial(
                            settled.frame, source_frame=_identity(runtime, settled, "supply-depot-radial-settled"),
                            source_png=settled.png,
                        )
                    return "supply_depot_radial" if rebound is not None else "unknown"

                action = session.run_action(
                    action_class="navigation",
                    label="open-supply-depot-building",
                    capture=capture,
                    dispatch=dispatch_building,
                    authorize=authorize_building,
                    recognize=recognize_radial,
                    target_roi=tuple(int(value) for value in building.target_roi),
                    consequence_class="navigation_only",
                )
                if action.status != "completed":
                    result["reason"] = ("supply_depot_radial_control_not_actionable"
                        if radial_successor.get("identity_recognized") else "supply_depot_radial_not_recognized")
                    session.terminal_status = "evidence_required"
                    return result

        radial_dispatch = {}

        def authorize_radial(before):
            rebound = bind_supply_depot_claim_supply(
                before.frame,
                source_frame=_identity(runtime, before, "supply-depot-radial-before"),
                source_png=before.png,
            )
            if rebound is None:
                raise RuntimeError("Claim Supply rebound failed")
            radial_dispatch["binding"] = rebound

        def dispatch_radial(before):
            rebound = radial_dispatch["binding"]
            if rebound.frame_sha256 != frame_digest(before.frame):
                raise RuntimeError("Claim Supply binding changed before dispatch")
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
            authorize=authorize_radial,
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
