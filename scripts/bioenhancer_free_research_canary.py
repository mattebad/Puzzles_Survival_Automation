"""Thin BlueStacks canary: Home atlas -> pan Lab into view -> Research radial -> Free Research 1x.

Ordinary development-session path. Pans the Research Lab into the safe radial footprint
before tapping. No registration, no scheduler, no Heavy ceremony.
"""

from __future__ import annotations

import json
import os
import sys
import time
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
from scripts.home_atlas_bluestacks import bluestacks_direct_pan_contract
from scripts.navigation_development_boundary import DevelopmentSession
from tasks.home_atlas import load_home_atlas
from tasks.home_atlas_planner import DirectPanNavigator, PlanDisposition
from tasks.home_atlas_vision import BlueStacksHomeLocalizer, bind_visible_building
from tasks.home_nav_recognition import recognize_home_nav
from tasks.nova_praise_vision import recognize_nova_frame

BLUESTACKS_ADB = Path(r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe")
BLUESTACKS_SERIAL = "emulator-5554"
ATLAS_PATH = ROOT / "tasks" / "assets" / "home_atlas" / "bluestacks" / "800x1280" / "atlas.json"
RESEARCH_LAB_ID = "home.building.research_lab"
FREE_RESEARCH_SEED_ROI = (94, 1133, 345, 1216)
# Facility radial cluster once Lab is centered; avoid left HUD and right event strip.
RADIAL_SEARCH_ROI = (250, 400, 700, 900)
# Measured from the retained native radial fixture:
# Nova target center (248, 662) -> Research target center (423, 576).
RESEARCH_TO_NOVA_CENTER = (175, -86)
RADIAL_TARGET_HALF_SIZE = 32


@dataclass(frozen=True)
class BoundControl:
    identity: str
    target_roi: tuple[int, int, int, int]
    evidence: tuple[str, ...]
    confidence: float

    @property
    def tap_point(self) -> tuple[int, int]:
        x0, y0, x1, y1 = self.target_roi
        return (x0 + x1) // 2, (y0 + y1) // 2


def _session_root() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return ROOT / ".local-captures" / "development-sessions" / f"bioenhancer-free-{stamp}"


def _ocr_tokens(frame_bgr: np.ndarray, roi: tuple[int, int, int, int]) -> list[dict[str, Any]]:
    x0, y0, x1, y1 = roi
    crop = frame_bgr[y0:y1, x0:x1]
    if crop.size == 0:
        return []
    scale = 2
    up = cv2.resize(crop, (crop.shape[1] * scale, crop.shape[0] * scale), interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(up, cv2.COLOR_BGR2GRAY)
    data = pytesseract.image_to_data(gray, output_type=Output.DICT, config="--psm 11")
    tokens: list[dict[str, Any]] = []
    n = len(data.get("text", []))
    for i in range(n):
        text = str(data["text"][i] or "").strip()
        if not text:
            continue
        conf = float(data["conf"][i]) if str(data["conf"][i]).lstrip("-").isdigit() else -1.0
        if conf < 40:
            continue
        left = x0 + int(data["left"][i]) // scale
        top = y0 + int(data["top"][i]) // scale
        width = max(1, int(data["width"][i]) // scale)
        height = max(1, int(data["height"][i]) // scale)
        tokens.append(
            {
                "text": text,
                "text_cf": text.casefold().replace(" ", ""),
                "conf": conf,
                "roi": (left, top, left + width, top + height),
            }
        )
    return tokens


def _union_roi(rois: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    return (
        min(r[0] for r in rois),
        min(r[1] for r in rois),
        max(r[2] for r in rois),
        max(r[3] for r in rois),
    )


def _annotate(frame_bgr: np.ndarray, control: BoundControl, path: Path) -> None:
    out = frame_bgr.copy()
    x0, y0, x1, y1 = control.target_roi
    cv2.rectangle(out, (x0, y0), (x1, y1), (0, 255, 0), 2)
    cx, cy = control.tap_point
    cv2.circle(out, (cx, cy), 8, (0, 0, 255), -1)
    cv2.putText(
        out,
        control.identity,
        (x0, max(20, y0 - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (0, 255, 0),
        2,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), out)


def _atlas_stack(frame_bgr: np.ndarray):
    atlas = load_home_atlas(ATLAS_PATH)
    localization = BlueStacksHomeLocalizer(atlas, ATLAS_PATH).localize(frame_bgr)
    return atlas, localization


def bind_research_lab(frame_bgr: np.ndarray) -> BoundControl | None:
    nav = recognize_home_nav(frame_bgr)
    if not nav.is_home:
        return None
    atlas, localization = _atlas_stack(frame_bgr)
    if not localization.recognized:
        return None
    binding = bind_visible_building(
        frame_bgr, localization, atlas.lookup_building(RESEARCH_LAB_ID)
    )
    if binding is None:
        return None
    return BoundControl(
        identity=RESEARCH_LAB_ID,
        target_roi=tuple(int(v) for v in binding.target_roi),  # type: ignore[arg-type]
        evidence=tuple(str(v) for v in binding.semantic_evidence),
        confidence=float(binding.confidence),
    )


def plan_research_lab_pan(frame_bgr: np.ndarray, navigator: DirectPanNavigator):
    atlas, localization = _atlas_stack(frame_bgr)
    if not localization.recognized:
        return None, None, None
    binding = bind_visible_building(
        frame_bgr, localization, atlas.lookup_building(RESEARCH_LAB_ID)
    )
    # Plan without accepting a clipped binding as complete — radial footprint matters.
    plan = navigator.plan(localization, None)
    return localization, binding, plan


def bind_research_radial_option(frame_bgr: np.ndarray) -> BoundControl | None:
    """Bind the Research radial control, not the Bioenhancer/Nova control.

    The existing Nova radial recognizer provides a template-bound current-frame
    anchor. Research is the neighboring static radial control at the measured
    offset from that anchor; OCR is only corroboration and cannot select a map
    label such as Research Center.
    """

    recognition = recognize_nova_frame(
        frame_bgr,
        captured_monotonic=1.0,
        home_context_visible=True,
    )
    nova = recognition.target("research-lab-nova")
    radial = recognition.diagnostics.get("research_lab_radial") or {}
    if (
        not recognition.observation.recognized
        or recognition.observation.screen_state != "RESEARCH_LAB_MENU"
        or nova is None
        or radial.get("template_match_roi") is None
    ):
        return None

    nx = (nova[0] + nova[2]) // 2
    ny = (nova[1] + nova[3]) // 2
    cx = nx + RESEARCH_TO_NOVA_CENTER[0]
    cy = ny + RESEARCH_TO_NOVA_CENTER[1]
    half = RADIAL_TARGET_HALF_SIZE
    if not (half <= cx < 800 - half and half <= cy < 1280 - half):
        return None
    ocr_terms = tuple(radial.get("ocr_terms") or ())
    hough_terms = tuple(radial.get("hough_only_anchors") or ())
    return BoundControl(
        identity="research-lab-radial-research",
        target_roi=(cx - half, cy - half, cx + half, cy + half),
        evidence=(
            f"template_nova_roi:{tuple(nova)}",
            f"research_offset:{RESEARCH_TO_NOVA_CENTER}",
            "radial_research_control",
            f"ocr_terms:{ocr_terms}",
            f"radial_terms:{hough_terms}",
        ),
        confidence=float(radial.get("template_score") or 0.0),
    )


def bind_free_research(frame_bgr: np.ndarray) -> BoundControl | None:
    x0, y0, x1, y1 = FREE_RESEARCH_SEED_ROI
    search = (max(0, x0 - 40), max(0, y0 - 80), min(800, x1 + 80), min(1280, y1 + 40))
    tokens = _ocr_tokens(frame_bgr, search)
    texts = [t["text_cf"] for t in tokens]
    blob = " ".join(texts)
    if "free" not in blob:
        return None
    free_token = next((t for t in tokens if t["text_cf"] == "free"), None)
    if free_token is None:
        leftish = [t for t in tokens if t["roi"][2] < 420]
        if not leftish:
            return None
        roi = _union_roi([t["roi"] for t in leftish])
    else:
        neighbors = [
            t
            for t in tokens
            if abs(((t["roi"][1] + t["roi"][3]) // 2) - ((free_token["roi"][1] + free_token["roi"][3]) // 2))
            < 80
            and t["roi"][0] < 420
        ]
        roi = (
            _union_roi([free_token["roi"], *[t["roi"] for t in neighbors]])
            if neighbors
            else free_token["roi"]
        )
    roi = (roi[0], roi[1], min(roi[2], 420), roi[3])
    if roi[2] - roi[0] < 40 or roi[3] - roi[1] < 20:
        roi = FREE_RESEARCH_SEED_ROI
    return BoundControl(
        identity="bioenhancer-free-research",
        target_roi=roi,
        evidence=tuple(f"ocr:{t}" for t in texts[:12]) or ("seed_roi_free_research",),
        confidence=0.9,
    )


def _dispatch_tap(runtime: LocalBlueStacksRuntime, before, control: BoundControl, action_key: str) -> None:
    runtime.tap(
        before,
        target_identity=control.identity,
        target_roi=control.target_roi,
        action_key=action_key,
        consequential=False,
    )


def _return_to_home(
    *,
    session: DevelopmentSession,
    runtime: LocalBlueStacksRuntime,
    capture,
    session_directory: Path,
    settle_seconds: float,
    maximum_backs: int = 2,
) -> dict[str, Any]:
    """Back out of Bioenhancer/radial surfaces and prove native Home."""

    attempts: list[dict[str, Any]] = []
    for ordinal in range(maximum_backs):
        def dispatch_back(before, index=ordinal) -> None:
            runtime.back(
                before,
                action_key=f"bioenhancer-return-home:{index}:{before.sha256[:12]}",
            )

        def recognize_successor(after, index=ordinal) -> str:
            time.sleep(settle_seconds)
            settled = capture(f"return-home-{index}-settled")
            (session_directory / f"return-home-{index}-settled.png").write_bytes(
                settled.png
            )
            recognition = recognize_home_nav(settled.frame)
            attempts.append(
                {
                    "ordinal": index,
                    "frame_sha256": settled.sha256,
                    "is_home": recognition.is_home,
                    "correlation": recognition.correlation,
                    "reason": recognition.reason,
                }
            )
            return "home_nav_recognized" if recognition.is_home else "unknown"

        action = session.run_action(
            action_class="navigation",
            label=f"bioenhancer-return-home-{ordinal}",
            capture=capture,
            dispatch=dispatch_back,
            recognize=recognize_successor,
            consequence_class="navigation_only",
        )
        if attempts and attempts[-1]["is_home"]:
            return {
                "status": "home_returned",
                "input_count": ordinal + 1,
                "attempts": attempts,
            }
        if getattr(action, "status", None) != "completed":
            break
    return {
        "status": "home_return_not_proven",
        "input_count": len(attempts),
        "attempts": attempts,
    }


def return_to_home_only(*, max_inputs: int = 2, settle_seconds: float = 1.5) -> dict[str, Any]:
    """Recover an already-open Bioenhancer screen without repeating research."""

    session_directory = _session_root()
    invocation_id = session_directory.name
    previous_limit = os.environ.get("PNS_DEVELOPMENT_MAX_INPUTS")
    os.environ["PNS_DEVELOPMENT_MAX_INPUTS"] = str(max_inputs)
    try:
        with DevelopmentSession(
            owner="pnsctl-development-session:bioenhancer-return-home",
            invocation_id=invocation_id,
            session_directory=session_directory,
            max_inputs=max_inputs,
        ) as session:
            runtime = LocalBlueStacksRuntime.connect(
                adb=str(BLUESTACKS_ADB),
                serial=BLUESTACKS_SERIAL,
                output_directory=session_directory / "runtime",
                workflow="bioenhancer-return-home",
                execute=True,
            )
            result: dict[str, Any] = {
                "session_directory": str(session_directory),
            }

            def capture(label: str):
                return runtime.capture(label)

            result.update(
                _return_to_home(
                    session=session,
                    runtime=runtime,
                    capture=capture,
                    session_directory=session_directory,
                    settle_seconds=settle_seconds,
                    maximum_backs=max_inputs,
                )
            )
            session.terminal_status = str(result["status"])
            (session_directory / "result.json").write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return result
    finally:
        if previous_limit is None:
            os.environ.pop("PNS_DEVELOPMENT_MAX_INPUTS", None)
        else:
            os.environ["PNS_DEVELOPMENT_MAX_INPUTS"] = previous_limit


def run(*, max_inputs: int = 10, settle_seconds: float = 1.5) -> dict[str, Any]:
    session_directory = _session_root()
    invocation_id = session_directory.name
    owner = "pnsctl-development-session:bioenhancer-free-research"
    result: dict[str, Any] = {
        "status": "evidence_required",
        "session_directory": str(session_directory),
        "steps": [],
    }
    previous_limit = os.environ.get("PNS_DEVELOPMENT_MAX_INPUTS")
    os.environ["PNS_DEVELOPMENT_MAX_INPUTS"] = str(max_inputs)
    try:
        with DevelopmentSession(
            owner=owner,
            invocation_id=invocation_id,
            session_directory=session_directory,
            max_inputs=max_inputs,
        ) as session:
            runtime = LocalBlueStacksRuntime.connect(
                adb=str(BLUESTACKS_ADB),
                serial=BLUESTACKS_SERIAL,
                output_directory=session_directory / "runtime",
                workflow="bioenhancer-free-research",
                execute=True,
            )

            def capture(label: str):
                return runtime.capture(label)

            atlas = load_home_atlas(ATLAS_PATH)
            safe, calibration = bluestacks_direct_pan_contract()
            navigator = DirectPanNavigator(
                atlas,
                RESEARCH_LAB_ID,
                safe,
                calibration,
                maximum_pans=6,
            )

            # --- 1) Pan Lab into a radial-safe viewport ---
            for pan_i in range(6):
                before = session.observe(capture, label=f"pan-{pan_i:02d}-before")
                (session_directory / f"pan-{pan_i:02d}-before.png").write_bytes(before.png)
                localization, binding, plan = plan_research_lab_pan(before.frame, navigator)
                if plan is None:
                    result["reason"] = "localization_failed_before_pan"
                    break
                result["steps"].append(
                    {
                        "step": f"pan_plan_{pan_i}",
                        "disposition": str(plan.disposition),
                        "reason": plan.reason,
                        "drag_start": list(plan.drag_start) if plan.drag_start else None,
                        "drag_end": list(plan.drag_end) if plan.drag_end else None,
                        "binding_roi": list(binding.target_roi) if binding is not None else None,
                    }
                )
                if plan.disposition in {PlanDisposition.COMPLETE, PlanDisposition.BIND, PlanDisposition.ALREADY_SAFE}:
                    result["viewport"] = "radial_safe"
                    break
                if plan.disposition is not PlanDisposition.PAN or plan.drag_start is None or plan.drag_end is None:
                    result["reason"] = f"pan_blocked:{plan.reason}"
                    break

                def dispatch_pan(frame=before, start=plan.drag_start, end=plan.drag_end, idx=pan_i):
                    runtime.swipe(
                        frame,
                        start=start,
                        end=end,
                        action_key=f"home-pan-research-lab:{idx}:{frame.sha256[:12]}",
                        target_identity="home-camera-click-drag",
                    )

                def recognize_pan(after, before_loc=localization, idx=pan_i):
                    time.sleep(settle_seconds)
                    settled = capture(f"pan-{idx:02d}-settled")
                    (session_directory / f"pan-{idx:02d}-after.png").write_bytes(settled.png)
                    after_loc = BlueStacksHomeLocalizer(atlas, ATLAS_PATH).localize(settled.frame)
                    progress = navigator.record_progress(before_loc, after_loc)
                    result["steps"].append(
                        {
                            "step": f"pan_progress_{idx}",
                            "accepted": progress.accepted,
                            "reason": progress.reason,
                        }
                    )
                    return "home_panned" if progress.accepted else "unknown"

                action = session.run_action(
                    action_class="navigation",
                    label=f"home-pan-research-lab-{pan_i}",
                    capture=capture,
                    dispatch=dispatch_pan,
                    recognize=recognize_pan,
                    consequence_class="navigation_only",
                )
                if getattr(action, "status", None) != "completed":
                    result["reason"] = f"pan_no_progress:{pan_i}"
                    (session_directory / "result.json").write_text(
                        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                    )
                    session.terminal_status = "evidence_required"
                    return result
            else:
                result["reason"] = "maximum_pans_exhausted"

            if result.get("viewport") != "radial_safe" and "reason" in result and result["reason"]:
                (session_directory / "result.json").write_text(
                    json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
                session.terminal_status = "evidence_required"
                return result

            # Fresh post-pan frame: either radial already visible, or tap Lab.
            home = session.observe(capture, label="post-pan-home")
            (session_directory / "post-pan-home.png").write_bytes(home.png)
            radial = bind_research_radial_option(home.frame)
            if radial is None:
                lab = bind_research_lab(home.frame)
                if lab is None:
                    # Lab may still be unbound under radial overlay; use planner binding seed.
                    _, binding, _ = plan_research_lab_pan(home.frame, navigator)
                    if binding is None:
                        result["reason"] = "research_lab_unbound_after_pan"
                        (session_directory / "result.json").write_text(
                            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                        )
                        session.terminal_status = "evidence_required"
                        return result
                    lab = BoundControl(
                        identity=RESEARCH_LAB_ID,
                        target_roi=tuple(int(v) for v in binding.target_roi),  # type: ignore[arg-type]
                        evidence=("atlas_binding_after_pan",),
                        confidence=float(binding.confidence),
                    )
                _annotate(home.frame, lab, session_directory / "annotate-research-lab.png")
                result["steps"].append(
                    {
                        "step": "bind_research_lab",
                        "roi": list(lab.target_roi),
                        "tap": list(lab.tap_point),
                        "evidence": list(lab.evidence),
                    }
                )

                def dispatch_lab(before) -> None:
                    rebound = bind_research_lab(before.frame)
                    if rebound is None:
                        # Fall back to planned ROI only after a fresh same-frame failure.
                        raise RuntimeError("Research Lab rebound failed pre-dispatch")
                    _annotate(before.frame, rebound, session_directory / "annotate-research-lab-pre.png")
                    _dispatch_tap(
                        runtime,
                        before,
                        rebound,
                        action_key=f"open-research-lab:{before.sha256[:12]}",
                    )

                def recognize_after_lab(after) -> str:
                    time.sleep(settle_seconds)
                    settled = capture("research-lab-radial-settled")
                    (session_directory / "research-lab-radial.png").write_bytes(settled.png)
                    bound = bind_research_radial_option(settled.frame)
                    tokens = _ocr_tokens(settled.frame, RADIAL_SEARCH_ROI)
                    (session_directory / "radial-ocr.json").write_text(
                        json.dumps(tokens, indent=2) + "\n", encoding="utf-8"
                    )
                    if bound is None:
                        return "unknown"
                    _annotate(settled.frame, bound, session_directory / "annotate-research-radial.png")
                    result["radial"] = {
                        "roi": list(bound.target_roi),
                        "tap": list(bound.tap_point),
                        "evidence": list(bound.evidence),
                        "frame_sha256": settled.sha256,
                    }
                    return "research_lab_radial"

                action = session.run_action(
                    action_class="navigation",
                    label="open-research-lab",
                    capture=capture,
                    dispatch=dispatch_lab,
                    recognize=recognize_after_lab,
                    target_roi=lab.target_roi,
                    consequence_class="navigation_only",
                )
                result["steps"].append({"step": "tap_research_lab", "status": getattr(action, "status", None)})
                if "radial" not in result:
                    result["reason"] = "research_lab_radial_not_bound"
                    (session_directory / "result.json").write_text(
                        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                    )
                    session.terminal_status = "evidence_required"
                    return result
            else:
                _annotate(home.frame, radial, session_directory / "annotate-research-radial.png")
                result["radial"] = {
                    "roi": list(radial.target_roi),
                    "tap": list(radial.tap_point),
                    "evidence": list(radial.evidence),
                    "frame_sha256": home.sha256,
                }
                tokens = _ocr_tokens(home.frame, RADIAL_SEARCH_ROI)
                (session_directory / "radial-ocr.json").write_text(
                    json.dumps(tokens, indent=2) + "\n", encoding="utf-8"
                )

            radial_ctrl = BoundControl(
                identity="research-lab-radial-research",
                target_roi=tuple(result["radial"]["roi"]),  # type: ignore[arg-type]
                evidence=tuple(result["radial"]["evidence"]),
                confidence=0.9,
            )

            def dispatch_radial(before) -> None:
                rebound = bind_research_radial_option(before.frame)
                if rebound is None:
                    raise RuntimeError("Research radial rebound failed pre-dispatch")
                _annotate(before.frame, rebound, session_directory / "annotate-research-radial-pre.png")
                _dispatch_tap(
                    runtime,
                    before,
                    rebound,
                    action_key=f"open-research:{before.sha256[:12]}",
                )

            def recognize_after_radial(after) -> str:
                time.sleep(settle_seconds)
                settled = capture("bioenhancer-screen-settled")
                (session_directory / "bioenhancer-screen.png").write_bytes(settled.png)
                free = bind_free_research(settled.frame)
                tokens = _ocr_tokens(settled.frame, (0, 1000, 800, 1280))
                (session_directory / "free-research-ocr.json").write_text(
                    json.dumps(tokens, indent=2) + "\n", encoding="utf-8"
                )
                if free is None:
                    return "unknown"
                _annotate(settled.frame, free, session_directory / "annotate-free-research.png")
                result["free_research"] = {
                    "roi": list(free.target_roi),
                    "tap": list(free.tap_point),
                    "evidence": list(free.evidence),
                    "frame_sha256": settled.sha256,
                }
                return "bioenhancer_free_research"

            action2 = session.run_action(
                action_class="navigation",
                label="open-research",
                capture=capture,
                dispatch=dispatch_radial,
                recognize=recognize_after_radial,
                target_roi=radial_ctrl.target_roi,
                consequence_class="navigation_only",
            )
            result["steps"].append({"step": "tap_research_radial", "status": getattr(action2, "status", None)})
            if "free_research" not in result:
                result["reason"] = "free_research_not_bound"
                (session_directory / "result.json").write_text(
                    json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
                session.terminal_status = "evidence_required"
                return result

            free = BoundControl(
                identity="bioenhancer-free-research",
                target_roi=tuple(result["free_research"]["roi"]),  # type: ignore[arg-type]
                evidence=tuple(result["free_research"]["evidence"]),
                confidence=0.9,
            )

            def dispatch_free(before) -> None:
                rebound = bind_free_research(before.frame)
                if rebound is None:
                    raise RuntimeError("Free Research rebound failed pre-dispatch")
                _annotate(before.frame, rebound, session_directory / "annotate-free-research-pre.png")
                runtime.tap(
                    before,
                    target_identity=rebound.identity,
                    target_roi=rebound.target_roi,
                    action_key=f"free-research-1x:{before.sha256[:12]}",
                    action_class="zero_cost_consequential",
                    consequential=True,
                )

            def recognize_after_free(after) -> str:
                time.sleep(settle_seconds)
                settled = capture("free-research-post-settled")
                (session_directory / "free-research-post.png").write_bytes(settled.png)
                result["post_sha256"] = settled.sha256
                tokens = _ocr_tokens(settled.frame, (0, 700, 800, 1280))
                token_text = " ".join(token["text_cf"] for token in tokens)
                count_proven = "1/100" in token_text or "1 / 100" in token_text
                timer_proven = "free" in token_text and "in" in token_text
                result["semantic_postcondition"] = {
                    "count_proven": count_proven,
                    "timer_proven": timer_proven,
                    "ocr_tokens": [token["text"] for token in tokens],
                }
                return (
                    "free_research_postcondition"
                    if count_proven and timer_proven
                    else "unknown"
                )

            action3 = session.run_action(
                action_class="navigation",
                label="free-research-1x",
                capture=capture,
                dispatch=dispatch_free,
                recognize=recognize_after_free,
                target_roi=free.target_roi,
                consequence_class="navigation_only",
            )
            result["steps"].append({"step": "tap_free_research", "status": getattr(action3, "status", None)})
            if getattr(action3, "status", None) != "completed":
                result["reason"] = "free_research_postcondition_not_proven"
                (session_directory / "result.json").write_text(
                    json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
                session.terminal_status = "evidence_required"
                return result

            result["return_home"] = _return_to_home(
                session=session,
                runtime=runtime,
                capture=capture,
                session_directory=session_directory,
                settle_seconds=settle_seconds,
            )
            if result["return_home"]["status"] != "home_returned":
                result["status"] = "evidence_required"
                result["reason"] = "bioenhancer_return_home_not_proven"
                (session_directory / "result.json").write_text(
                    json.dumps(result, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                session.terminal_status = "evidence_required"
                return result
            session.terminal_status = "completed"
            result["status"] = "completed"
            result["input_count"] = session.input_count
            (session_directory / "result.json").write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            return result
    finally:
        if previous_limit is None:
            os.environ.pop("PNS_DEVELOPMENT_MAX_INPUTS", None)
        else:
            os.environ["PNS_DEVELOPMENT_MAX_INPUTS"] = previous_limit


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--return-home-only",
        action="store_true",
        help="Back out of the current Bioenhancer screen without repeating research",
    )
    args = parser.parse_args()
    payload = return_to_home_only() if args.return_home_only else run()
    print(json.dumps(payload, sort_keys=True, default=str))
    successful = payload.get("status") in {"completed", "home_returned"}
    raise SystemExit(0 if successful else 2)
