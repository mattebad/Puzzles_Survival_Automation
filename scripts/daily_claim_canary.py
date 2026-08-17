"""Thin BlueStacks canary: Home -> Quest -> Daily tab -> aggregate Claim.

Ordinary development-session path (a Daily Claim is an ordinary development
interaction per docs/runtime-input-safety-policy.md). Reuses the deterministic
template Home recognizer for the Home->Quest tap and OCR-bound controls for the
Daily tab and Claim button. No registration, no scheduler, no receipt ceremony.

Modes:
  --recon  : navigate to the Daily screen, bind+annotate Claim control(s),
             then STOP before any Claim tap (default).
  --claim  : recon, then tap the bound Claim, verify the postcondition, and
             return Home.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
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
from scripts.navigation_development_boundary import DevelopmentSession
from tasks.home_nav_recognition import recognize_home_nav

BLUESTACKS_ADB = Path(r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe")
BLUESTACKS_SERIAL = "emulator-5554"

NATIVE_WIDTH = 800
NATIVE_HEIGHT = 1280
# Quest/Daily tabs live in the top band on the 800x1280 profile.
TAB_SEARCH_ROI = (0, 35, NATIVE_WIDTH, 230)
# Body region below the point-milestone chest bar; per-objective Claim buttons.
CLAIM_BODY_MIN_Y = 340
FULL_FRAME_ROI = (0, 0, NATIVE_WIDTH, NATIVE_HEIGHT)

# Right-side action-button column on the Daily objective rows.
CLAIM_BUTTON_COLUMN = (560, 780)
CLAIM_SCAN_TOP_Y = 440
# The stylized button text is unreadable by OCR, but colour is unambiguous:
# actionable Claim buttons are gold/orange (hue ~15); "Go" buttons that navigate
# into a task are red (hue ~3-5). Bind Claim by colour and never tap a red Go.
CLAIM_HUE_RANGE = (10, 22)
CLAIM_MIN_SAT = 120
CLAIM_MIN_VAL = 140
CLAIM_MIN_WIDTH = 60
CLAIM_MIN_HEIGHT = 25


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
    return ROOT / ".local-captures" / "development-sessions" / f"daily-claim-{stamp}"


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


def _annotate(frame_bgr: np.ndarray, controls: list[BoundControl], path: Path, *, primary: BoundControl | None = None) -> None:
    out = frame_bgr.copy()
    for control in controls:
        x0, y0, x1, y1 = control.target_roi
        colour = (0, 255, 0) if control is primary else (0, 200, 255)
        cv2.rectangle(out, (x0, y0), (x1, y1), colour, 2)
        cx, cy = control.tap_point
        cv2.circle(out, (cx, cy), 6, (0, 0, 255), -1)
        cv2.putText(out, control.identity, (x0, max(18, y0 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 2)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), out)


def bind_daily_tab(frame_bgr: np.ndarray) -> BoundControl | None:
    tokens = _ocr_tokens(frame_bgr, TAB_SEARCH_ROI)
    daily = next((t for t in tokens if t["text_cf"] == "daily"), None)
    if daily is None:
        return None
    x0, y0, x1, y1 = daily["roi"]
    # Expand slightly for a stable tap target on the tab label.
    pad_x, pad_y = 18, 10
    roi = (max(0, x0 - pad_x), max(0, y0 - pad_y), min(NATIVE_WIDTH, x1 + pad_x), min(NATIVE_HEIGHT, y1 + pad_y))
    return BoundControl(
        identity="quest-daily-tab",
        target_roi=roi,
        evidence=(f"ocr:daily:{daily['roi']}", f"conf:{daily['conf']}"),
        confidence=min(1.0, daily["conf"] / 100.0),
    )


def bind_claim_controls(frame_bgr: np.ndarray) -> list[BoundControl]:
    """Bind each actionable gold 'Claim' button by colour (never a red 'Go').

    OCR cannot read the stylized button text, but the gold Claim buttons and red
    Go buttons are cleanly separable by hue. This detects gold button bands in
    the right-side action column and excludes red navigation buttons.
    """
    if frame_bgr.shape[:2] != (NATIVE_HEIGHT, NATIVE_WIDTH):
        return []
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    x0, x1 = CLAIM_BUTTON_COLUMN
    region = hsv[CLAIM_SCAN_TOP_Y:NATIVE_HEIGHT, x0:x1]
    h, s, v = region[:, :, 0], region[:, :, 1], region[:, :, 2]
    gold = (
        (h >= CLAIM_HUE_RANGE[0])
        & (h <= CLAIM_HUE_RANGE[1])
        & (s >= CLAIM_MIN_SAT)
        & (v >= CLAIM_MIN_VAL)
    ).astype(np.uint8) * 255
    full = np.zeros((NATIVE_HEIGHT, NATIVE_WIDTH), np.uint8)
    full[CLAIM_SCAN_TOP_Y:NATIVE_HEIGHT, x0:x1] = gold
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (31, 15))
    closed = cv2.morphologyEx(full, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rows: list[tuple[int, int, int, int]] = []
    for contour in contours:
        bx, by, bw, bh = cv2.boundingRect(contour)
        if bw >= CLAIM_MIN_WIDTH and bh >= CLAIM_MIN_HEIGHT:
            rows.append((bx, by, bw, bh))
    rows.sort(key=lambda r: r[1])
    controls: list[BoundControl] = []
    for ordinal, (bx, by, bw, bh) in enumerate(rows, start=1):
        roi = (bx, by, bx + bw, by + bh)
        controls.append(
            BoundControl(
                identity=f"daily-claim-{ordinal}",
                target_roi=roi,
                evidence=(
                    "color_gold_claim_button",
                    f"hue_range:{CLAIM_HUE_RANGE}",
                    f"roi:{roi}",
                ),
                confidence=0.95,
            )
        )
    return controls


def _navigate_to_daily(
    *,
    session: DevelopmentSession,
    runtime: LocalBlueStacksRuntime,
    capture,
    session_directory: Path,
    result: dict[str, Any],
    settle_seconds: float,
) -> bool:
    # --- Home proof (deterministic template) ---
    home = session.observe(capture, label="home-source")
    (session_directory / "home-source.png").write_bytes(home.png)
    nav = recognize_home_nav(home.frame)
    result["steps"].append(
        {"step": "home", "is_home": nav.is_home, "correlation": nav.correlation, "reason": nav.reason}
    )
    if not nav.is_home:
        result["reason"] = f"not_home:{nav.reason}"
        return False

    quest_point = nav.quest_tap_point()
    if quest_point is None:
        result["reason"] = "quest_tap_point_unavailable"
        return False
    qx, qy = quest_point
    quest_roi = (qx - 30, qy - 24, qx + 30, qy + 24)

    def dispatch_quest(before) -> None:
        rebound = recognize_home_nav(before.frame)
        if not rebound.is_home:
            raise RuntimeError("home rebound failed pre-dispatch")
        runtime.tap(
            before,
            target_identity="home-quest-entry",
            target_roi=quest_roi,
            action_key=f"home-quest-entry:{before.sha256[:12]}",
            consequential=False,
        )

    def recognize_quest(after) -> str:
        time.sleep(settle_seconds)
        settled = capture("quest-settled")
        (session_directory / "quest-settled.png").write_bytes(settled.png)
        tab = bind_daily_tab(settled.frame)
        tokens = _ocr_tokens(settled.frame, TAB_SEARCH_ROI)
        (session_directory / "quest-tab-ocr.json").write_text(
            json.dumps(tokens, indent=2), encoding="utf-8"
        )
        if tab is None:
            return "unknown"
        result["quest"] = {"daily_tab_roi": list(tab.target_roi), "frame_sha256": settled.sha256}
        _annotate(settled.frame, [tab], session_directory / "annotate-daily-tab.png", primary=tab)
        return "quest_daily_tab_visible"

    action = session.run_action(
        action_class="navigation",
        label="home-quest-entry",
        capture=capture,
        dispatch=dispatch_quest,
        recognize=recognize_quest,
        consequence_class="navigation_only",
    )
    result["steps"].append({"step": "tap_quest", "status": getattr(action, "status", None)})
    if "quest" not in result:
        result["reason"] = "daily_tab_not_visible_on_quest"
        return False

    daily_tab = BoundControl(
        identity="quest-daily-tab",
        target_roi=tuple(result["quest"]["daily_tab_roi"]),  # type: ignore[arg-type]
        evidence=("quest_daily_tab",),
        confidence=0.9,
    )

    def dispatch_daily(before) -> None:
        rebound = bind_daily_tab(before.frame)
        if rebound is None:
            raise RuntimeError("daily tab rebound failed pre-dispatch")
        runtime.tap(
            before,
            target_identity=rebound.identity,
            target_roi=rebound.target_roi,
            action_key=f"quest-daily-tab:{before.sha256[:12]}",
            consequential=False,
        )

    def recognize_daily(after) -> str:
        time.sleep(settle_seconds)
        settled = capture("daily-settled")
        (session_directory / "daily-settled.png").write_bytes(settled.png)
        claims = bind_claim_controls(settled.frame)
        body_tokens = _ocr_tokens(settled.frame, (0, CLAIM_BODY_MIN_Y, NATIVE_WIDTH, NATIVE_HEIGHT))
        (session_directory / "daily-body-ocr.json").write_text(
            json.dumps(body_tokens, indent=2), encoding="utf-8"
        )
        result["daily"] = {
            "frame_sha256": settled.sha256,
            "claim_controls": [
                {"identity": c.identity, "roi": list(c.target_roi), "tap": list(c.tap_point), "evidence": list(c.evidence)}
                for c in claims
            ],
        }
        _annotate(
            settled.frame,
            claims,
            session_directory / "annotate-daily-claims.png",
            primary=claims[0] if claims else None,
        )
        return "daily_selected"

    action2 = session.run_action(
        action_class="navigation",
        label="quest-daily-tab",
        capture=capture,
        dispatch=dispatch_daily,
        recognize=recognize_daily,
        target_roi=daily_tab.target_roi,
        consequence_class="navigation_only",
    )
    result["steps"].append({"step": "tap_daily_tab", "status": getattr(action2, "status", None)})
    if "daily" not in result:
        result["reason"] = "daily_screen_not_bound"
        return False
    return True


def _return_to_home(
    *,
    session: DevelopmentSession,
    runtime: LocalBlueStacksRuntime,
    capture,
    session_directory: Path,
    settle_seconds: float,
    maximum_backs: int = 3,
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for ordinal in range(maximum_backs):
        def dispatch_back(before, index=ordinal) -> None:
            runtime.back(before, action_key=f"daily-return-home:{index}:{before.sha256[:12]}")

        def recognize_successor(after, index=ordinal) -> str:
            time.sleep(settle_seconds)
            settled = capture(f"return-home-{index}-settled")
            (session_directory / f"return-home-{index}-settled.png").write_bytes(settled.png)
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
            label=f"daily-return-home-{ordinal}",
            capture=capture,
            dispatch=dispatch_back,
            recognize=recognize_successor,
            consequence_class="navigation_only",
        )
        if attempts and attempts[-1]["is_home"]:
            return {"status": "home_returned", "input_count": ordinal + 1, "attempts": attempts}
        if getattr(action, "status", None) != "completed":
            break
    return {"status": "home_return_not_proven", "input_count": len(attempts), "attempts": attempts}


def return_home(*, max_inputs: int = 4, settle_seconds: float = 1.5) -> dict[str, Any]:
    """Back out of the current screen and prove native Home."""
    session_directory = _session_root()
    invocation_id = session_directory.name
    previous_limit = os.environ.get("PNS_DEVELOPMENT_MAX_INPUTS")
    os.environ["PNS_DEVELOPMENT_MAX_INPUTS"] = str(max_inputs)
    try:
        with DevelopmentSession(
            owner="pnsctl-development-session:daily-claim-return-home",
            invocation_id=invocation_id,
            session_directory=session_directory,
            max_inputs=max_inputs,
        ) as session:
            runtime = LocalBlueStacksRuntime.connect(
                adb=str(BLUESTACKS_ADB),
                serial=BLUESTACKS_SERIAL,
                output_directory=session_directory / "runtime",
                workflow="daily-claim-return-home",
                execute=True,
            )

            def capture(label: str):
                return runtime.capture(label)

            result = {"session_directory": str(session_directory)}
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
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            return result
    finally:
        if previous_limit is None:
            os.environ.pop("PNS_DEVELOPMENT_MAX_INPUTS", None)
        else:
            os.environ["PNS_DEVELOPMENT_MAX_INPUTS"] = previous_limit


def run(*, mode: str = "recon", max_inputs: int = 8, settle_seconds: float = 1.5) -> dict[str, Any]:
    session_directory = _session_root()
    invocation_id = session_directory.name
    owner = f"pnsctl-development-session:daily-claim-{mode}"
    result: dict[str, Any] = {
        "status": "evidence_required",
        "mode": mode,
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
                workflow=f"daily-claim-{mode}",
                execute=True,
            )

            def capture(label: str):
                return runtime.capture(label)

            navigated = _navigate_to_daily(
                session=session,
                runtime=runtime,
                capture=capture,
                session_directory=session_directory,
                result=result,
                settle_seconds=settle_seconds,
            )
            if not navigated:
                session.terminal_status = "evidence_required"
                (session_directory / "result.json").write_text(
                    json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
                return result

            claim_controls = result.get("daily", {}).get("claim_controls", [])
            if mode == "recon":
                result["status"] = "observed"
                result["reason"] = "daily claim controls bound; stopped before claim tap"
                session.terminal_status = "observed"
                result["input_count"] = session.input_count
                (session_directory / "result.json").write_text(
                    json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
                return result

            # --- claim mode: claim every available gold Claim button ---
            if not claim_controls:
                result["reason"] = "no_claimable_control_bound"
                session.terminal_status = "evidence_required"
                (session_directory / "result.json").write_text(
                    json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
                return result

            claims_done: list[dict[str, Any]] = []
            result["claims"] = claims_done
            maximum_claims = len(claim_controls)
            for claim_ordinal in range(maximum_claims):
                before_scan = session.observe(capture, label=f"claim-{claim_ordinal}-scan")
                controls_now = bind_claim_controls(before_scan.frame)
                (session_directory / f"annotate-claim-{claim_ordinal}-scan.png").write_bytes(
                    before_scan.png
                )
                if not controls_now:
                    break
                before_count = len(controls_now)

                def dispatch_claim(before, idx=claim_ordinal) -> None:
                    rebound = bind_claim_controls(before.frame)
                    if not rebound:
                        raise RuntimeError("claim control rebound failed pre-dispatch")
                    _annotate(
                        before.frame,
                        rebound,
                        session_directory / f"annotate-claim-{idx}-pre.png",
                        primary=rebound[0],
                    )
                    runtime.tap(
                        before,
                        target_identity=rebound[0].identity,
                        target_roi=rebound[0].target_roi,
                        action_key=f"daily-claim-{idx}:{before.sha256[:12]}",
                        action_class="reward_claim",
                        consequential=False,
                    )

                def recognize_after_claim(after, idx=claim_ordinal, expected=before_count) -> str:
                    time.sleep(settle_seconds)
                    settled = capture(f"daily-claim-{idx}-post")
                    (session_directory / f"daily-claim-{idx}-post.png").write_bytes(settled.png)
                    remaining = bind_claim_controls(settled.frame)
                    claims_done.append(
                        {
                            "ordinal": idx,
                            "before_controls": expected,
                            "remaining_controls": len(remaining),
                            "post_sha256": settled.sha256,
                        }
                    )
                    _annotate(
                        settled.frame,
                        remaining,
                        session_directory / f"annotate-claim-{idx}-post.png",
                    )
                    return "daily_claim_effect" if len(remaining) < expected else "unknown"

                action = session.run_action(
                    action_class="reward_claim",
                    label=f"daily-claim-{claim_ordinal}",
                    capture=capture,
                    dispatch=dispatch_claim,
                    recognize=recognize_after_claim,
                    target_roi=tuple(controls_now[0].target_roi),
                    consequence_class="ordinary_development",
                )
                result["steps"].append(
                    {"step": f"tap_claim_{claim_ordinal}", "status": getattr(action, "status", None)}
                )
                if getattr(action, "status", None) != "completed":
                    result["reason"] = f"daily_claim_effect_not_proven:{claim_ordinal}"
                    session.terminal_status = "evidence_required"
                    (session_directory / "result.json").write_text(
                        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                    )
                    return result

            result["return_home"] = _return_to_home(
                session=session,
                runtime=runtime,
                capture=capture,
                session_directory=session_directory,
                settle_seconds=settle_seconds,
            )
            result["status"] = "completed" if result["return_home"]["status"] == "home_returned" else "claimed_home_return_not_proven"
            session.terminal_status = result["status"]
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
    parser.add_argument("--claim", action="store_true", help="Tap the bound Claim after recon")
    parser.add_argument("--return-home", action="store_true", help="Back out to Home only")
    args = parser.parse_args()
    if args.return_home:
        payload = return_home()
    else:
        payload = run(mode="claim" if args.claim else "recon", max_inputs=12 if args.claim else 8)
    print(json.dumps(payload, sort_keys=True, default=str))
    ok = payload.get("status") in {"observed", "completed", "home_returned"}
    raise SystemExit(0 if ok else 2)
