"""Bounded Home Atlas startup normalization for direct native runtimes."""

from __future__ import annotations

import time
from pathlib import Path

from scripts.atlas_startup_normalizer import (
    AtlasStartupDisposition,
    BlueStacksAtlasStartupNormalizer,
)
from scripts.home_atlas_bluestacks import ScrcpyMotionEventZoomTransport
from scripts.navigation_development_boundary import (
    NavigationGuardedRuntime,
    NavigationRouteDeclaration,
    make_source_safety_facts,
)
from scripts.startup_normalization import classify_home_base_live


class AtlasRuntimeStartupError(RuntimeError):
    """Fail-closed startup error retaining all observations made before the block."""

    def __init__(self, reason: str, records: list[dict[str, object]]) -> None:
        super().__init__(reason)
        self.records = tuple(dict(record) for record in records)


def normalize_runtime_home_atlas_startup(
    *,
    runtime,
    atlas,
    atlas_path: Path,
    execute: bool,
    settle_seconds: float,
    maximum_zoom_inputs: int = 2,
):
    """Return a localizer and evidence after canonical readiness or a safe block."""

    localizer = __import__(
        "scripts.home_atlas_bluestacks",
        fromlist=["BlueStacksHomeLocalizer"],
    ).BlueStacksHomeLocalizer(atlas, atlas_path)
    normalizer = BlueStacksAtlasStartupNormalizer(
        localizer,
        maximum_zoom_inputs=maximum_zoom_inputs,
    )
    guarded = NavigationGuardedRuntime(
        runtime,
        NavigationRouteDeclaration(
            allowed_source_states=frozenset({"HOME_BASE"}),
            allowed_target_identities=frozenset({"home-zoom-out"}),
            allowed_gesture_classes=frozenset({"zoom_out"}),
        ),
    )
    transport = None
    records: list[dict[str, object]] = []
    current = runtime.capture("home-atlas-startup-zoom-01-immediate-before")

    for ordinal in range(1, maximum_zoom_inputs + 2):
        step = normalizer.observe(current.frame)
        row: dict[str, object] = {
            "phase": "atlas_startup_zoom_normalization",
            "ordinal": ordinal,
            "disposition": step.disposition.value,
            "reason": step.reason,
            "source_frame_sha256": step.source_frame_sha256,
            "runtime_source_sha256": current.sha256,
            "recovery_input_ordinal": step.recovery_input_ordinal,
        }
        records.append(row)
        if step.disposition is AtlasStartupDisposition.READY:
            return localizer, records
        if step.disposition is AtlasStartupDisposition.BLOCKED:
            raise AtlasRuntimeStartupError(
                f"Home Atlas startup blocked: {step.reason}", records
            )
        if normalizer.zoom_inputs >= maximum_zoom_inputs or not execute:
            raise AtlasRuntimeStartupError(
                "Home Atlas startup requires unavailable bounded zoom recovery",
                records,
            )

        home = classify_home_base_live(
            current.frame,
            cash_mall_rejected=True,
            safe_os_surface=True,
        )
        row["home_source_facts"] = dict(home)
        if (
            home.get("state") != "HOME_BASE"
            or not home.get("recognized")
            or home.get("overlay")
            or home.get("blocking_unknown_modal")
            or home.get("manual_only_state")
        ):
            row["reason"] = "zoom_source_not_positively_recognized_clean_home"
            raise AtlasRuntimeStartupError(
                "Home Atlas zoom source is not positively recognized clean Home",
                records,
            )
        if transport is None:
            transport = ScrcpyMotionEventZoomTransport(
                adb=runtime.runner.executable,
                serial=runtime.runner.serial,
                evidence_directory=runtime.session / "scrcpy-zoom",
            )
        guarded.dispatch_zoom_out(
            current,
            make_source_safety_facts(
                recognized=True,
                source_state="HOME_BASE",
                overlay_state="none_observed",
                frame_sha256=current.sha256,
                captured_monotonic=current.captured_monotonic,
            ),
            transport=transport.zoom_out_once,
        )
        normalizer.record_zoom_input_dispatched(step.source_frame_sha256)
        immediate_post = runtime.capture(
            f"home-atlas-startup-zoom-{ordinal:02d}-immediate-post"
        )
        if settle_seconds > 0:
            time.sleep(settle_seconds)
        settled = runtime.capture(f"home-atlas-startup-zoom-{ordinal:02d}-settled")
        row["immediate_post_sha256"] = immediate_post.sha256
        row["settled_sha256"] = settled.sha256
        if settled.sha256 == current.sha256:
            row["reason"] = "home_zoom_recovery_no_progress"
            raise AtlasRuntimeStartupError(
                "Home Atlas zoom recovery produced no frame progress", records
            )
        current = settled

    return localizer, records
