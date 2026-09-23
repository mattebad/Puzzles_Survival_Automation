"""Bounded live Home Atlas startup normalization for DevelopmentSession flows."""

from __future__ import annotations

from scripts.startup_normalization import is_clean_home_frame

import time
from pathlib import Path
from typing import Any, Callable

from scripts.atlas_startup_normalizer import (
    AtlasStartupDisposition,
    BlueStacksAtlasStartupNormalizer,
)
from scripts.home_atlas_bluestacks import (
    ScrcpyMotionEventZoomTransport,
    bluestacks_direct_pan_contract,
)
from scripts.navigation_development_boundary import (
    DevelopmentSession,
    NavigationGuardedRuntime,
    NavigationRouteDeclaration,
    make_source_safety_facts,
)
from tasks.home_atlas_vision import BlueStacksHomeLocalizer, frame_digest
from tasks.home_nav_recognition import recognize_home_nav


class AtlasStartupNormalizationError(RuntimeError):
    """Raised after a fail-closed Atlas startup decision."""


def normalize_home_atlas_startup(
    *,
    session: DevelopmentSession,
    runtime,
    capture: Callable[[str], Any],
    atlas,
    atlas_path: Path,
    settle_seconds: float,
    evidence_records: list[dict[str, Any]],
    adb: str,
    serial: str,
    maximum_zoom_inputs: int = 2,
):
    """Normalize clean Home to canonical zoom, then return direct-pan geometry."""

    localizer = BlueStacksHomeLocalizer(atlas, atlas_path)
    normalizer = BlueStacksAtlasStartupNormalizer(localizer,
    maximum_zoom_inputs=maximum_zoom_inputs, home_is_clean=is_clean_home_frame)
    guarded = NavigationGuardedRuntime(
        runtime,
        NavigationRouteDeclaration(
            allowed_source_states=frozenset({"HOME_BASE"}),
            allowed_target_identities=frozenset({"home-zoom-out"}),
            allowed_gesture_classes=frozenset({"zoom_out"}),
        ),
    )
    transport = ScrcpyMotionEventZoomTransport(
        adb=adb,
        serial=serial,
        evidence_directory=runtime.session / "scrcpy-zoom",
    )
    current = session.observe(capture, label="home-atlas-startup-source")
    step = normalizer.observe(current.frame)

    while step.disposition is AtlasStartupDisposition.RECOVER_ZOOM:
        cached_before = [current]
        successor: dict[str, Any] = {}

        def action_capture(label: str):
            if cached_before:
                return cached_before.pop()
            return capture(label)

        def authorize_zoom(before, planned=step):
            home = recognize_home_nav(before.frame)
            if not home.is_home or getattr(home, "overlay", False):
                raise AtlasStartupNormalizationError(
                    "Home Atlas zoom source is not positively recognized clean Home"
                )
            if (
                before is not current
                or frame_digest(before.frame) != planned.source_frame_sha256
            ):
                raise AtlasStartupNormalizationError(
                    "Home Atlas zoom source changed before dispatch"
                )

        def dispatch_zoom(before, planned=step):
            guarded.dispatch_zoom_out(
                before,
                make_source_safety_facts(
                    recognized=True,
                    source_state="HOME_BASE",
                    overlay_state="none_observed",
                    frame_sha256=before.sha256,
                    captured_monotonic=before.captured_monotonic,
                ),
                transport=transport.zoom_out_once,
            )
            normalizer.record_zoom_input_dispatched(planned.source_frame_sha256)

        def recognize_zoom(after):
            if "immediate_post" not in successor:
                successor["immediate_post"] = after
                return "unknown"
            successor["settled"] = after
            successor["step"] = normalizer.observe(after.frame)
            repeated = (
                after.sha256 == current.sha256
                or successor["step"].source_frame_sha256 == step.source_frame_sha256
            )
            if repeated:
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
            return capture("home-atlas-startup-zoom-settled")

        action = session.run_action(
            action_class="navigation",
            label=f"home-atlas-startup-zoom:{step.recovery_input_ordinal}",
            capture=action_capture,
            dispatch=dispatch_zoom,
            recognize=recognize_zoom,
            authorize=authorize_zoom,
            consequence_class="navigation_only",
            settled_successor=settled_successor,
        )
        evidence_records.append(
            {
                "step": "home_atlas_zoom_normalization",
                "disposition": step.disposition.value,
                "reason": step.reason,
                "source_frame_sha256": step.source_frame_sha256,
                "recovery_input_ordinal": step.recovery_input_ordinal,
                "action_status": action.status,
                "immediate_post_sha256": getattr(
                    successor.get("immediate_post"), "sha256", None
                ),
                "settled_sha256": getattr(successor.get("settled"), "sha256", None),
            }
        )
        next_step = successor.get("step")
        if action.status != "completed" or next_step is None:
            session.terminal_status = "evidence_required"
            reason = (
                "Home Atlas zoom produced no progress"
                if successor.get("no_progress")
                else "Home Atlas zoom successor was not verified"
            )
            raise AtlasStartupNormalizationError(reason)
        current = successor["settled"]
        step = next_step

    evidence_records.append(
        {
            "step": "home_atlas_zoom_normalization",
            "disposition": step.disposition.value,
            "reason": step.reason,
            "source_frame_sha256": step.source_frame_sha256,
            "recovery_input_ordinal": step.recovery_input_ordinal,
        }
    )
    if step.disposition is not AtlasStartupDisposition.READY:
        session.terminal_status = "evidence_required"
        raise AtlasStartupNormalizationError(
            f"Home Atlas startup blocked: {step.reason}"
        )
    return bluestacks_direct_pan_contract()
