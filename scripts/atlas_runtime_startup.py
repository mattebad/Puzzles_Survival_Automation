"""Bounded Home Atlas startup normalization for direct or session-owned native runtimes."""

from __future__ import annotations

from collections.abc import Callable
import time
from pathlib import Path

from scripts.atlas_startup_normalizer import (
    AtlasStartupDisposition,
    BlueStacksAtlasStartupNormalizer,
)
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.home_atlas_bluestacks import ScrcpyMotionEventZoomTransport
from scripts.navigation_development_boundary import (
    DevelopmentSession,
    NavigationGuardedRuntime,
    NavigationRouteDeclaration,
    make_source_safety_facts,
)
from scripts.startup_normalization import classify_home_base_live, is_clean_home_frame

_SESSION_ZOOM_SOURCES = "home_atlas_startup_zoom_sources"


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
    session: DevelopmentSession | None = None,
):
    """Return a localizer and evidence after canonical readiness or a safe block.

    Without ``session`` the caller owns cumulative input adoption.  With an
    existing ``DevelopmentSession`` every physical zoom is one ``run_action``
    input, so route inputs before and after normalization stay session-owned.
    """

    if session is not None:
        unresolved = [row for row in session.actions if row.get("status") != "completed"]
        if unresolved:
            raise AtlasRuntimeStartupError(
                "Home Atlas zoom is denied after an unresolved session action", []
            )

    def capture(label: str):
        if session is None:
            return runtime.capture(label)
        return session.observe(runtime.capture, label=label)

    localizer = __import__(
        "scripts.home_atlas_bluestacks",
        fromlist=["BlueStacksHomeLocalizer"],
    ).BlueStacksHomeLocalizer(atlas, atlas_path)
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
    transport = None
    records: list[dict[str, object]] = []
    current = capture("home-atlas-startup-zoom-01-immediate-before")

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
        if session is None:
            guarded.dispatch_zoom_out(
                current,
                _zoom_source_facts(current),
                transport=transport.zoom_out_once,
            )
            normalizer.record_zoom_input_dispatched(step.source_frame_sha256)
            immediate_post = runtime.capture(
                f"home-atlas-startup-zoom-{ordinal:02d}-immediate-post"
            )
            if settle_seconds > 0:
                time.sleep(settle_seconds)
            settled = runtime.capture(f"home-atlas-startup-zoom-{ordinal:02d}-settled")
        else:
            immediate_post, settled = _session_zoom(
                session=session,
                runtime=runtime,
                guarded=guarded,
                normalizer=normalizer,
                source=current,
                planned_sha256=step.source_frame_sha256,
                transport=transport.zoom_out_once,
                ordinal=ordinal,
                settle_seconds=settle_seconds,
                records=records,
            )
        row["immediate_post_sha256"] = immediate_post.sha256
        row["settled_sha256"] = settled.sha256
        if settled.sha256 == current.sha256:
            row["reason"] = "home_zoom_recovery_no_progress"
            raise AtlasRuntimeStartupError(
                "Home Atlas zoom recovery produced no frame progress", records
            )
        current = settled

    return localizer, records


def _zoom_source_facts(source: CapturedNativeFrame):
    return make_source_safety_facts(
        recognized=True,
        source_state="HOME_BASE",
        overlay_state="none_observed",
        frame_sha256=source.sha256,
        captured_monotonic=source.captured_monotonic,
    )


def _session_zoom(
    *,
    session: DevelopmentSession,
    runtime,
    guarded: NavigationGuardedRuntime,
    normalizer: BlueStacksAtlasStartupNormalizer,
    source: CapturedNativeFrame,
    planned_sha256: str,
    transport: Callable[[], None],
    ordinal: int,
    settle_seconds: float,
    records: list[dict[str, object]],
) -> tuple[CapturedNativeFrame, CapturedNativeFrame]:
    """Dispatch one planned zoom as one session input; never repeat a dispatched source."""

    dispatched = tuple(session.control_memory.get(_SESSION_ZOOM_SOURCES, ()))
    if source.sha256 in dispatched:
        records[-1]["reason"] = "identical_zoom_source_already_dispatched"
        raise AtlasRuntimeStartupError(
            "Home Atlas zoom source was already dispatched in this session", records
        )
    label = f"home-atlas-startup-zoom-{ordinal:02d}-{source.sha256[:16]}"
    planned = [source]
    immediate: list[CapturedNativeFrame] = []
    settled: list[CapturedNativeFrame] = []

    def capture(capture_label: str) -> CapturedNativeFrame:
        # The planned frame is run_action's immediate-before source; later frames are live.
        if planned:
            return planned.pop()
        frame = runtime.capture(capture_label)
        immediate.append(frame)
        return frame

    def dispatch(before: CapturedNativeFrame) -> None:
        if before is not source:
            raise AtlasRuntimeStartupError("Home Atlas zoom source differs from its plan", records)
        session.remember_control(_SESSION_ZOOM_SOURCES, (*dispatched, source.sha256))
        guarded.dispatch_zoom_out(before, _zoom_source_facts(before), transport=transport)
        normalizer.record_zoom_input_dispatched(planned_sha256)

    def settled_successor() -> CapturedNativeFrame:
        if settle_seconds > 0:
            time.sleep(settle_seconds)
        frame = session.observe(runtime.capture, label=f"{label}-settled")
        settled.append(frame)
        return frame

    def recognize(frame: CapturedNativeFrame) -> str:
        return "home_base" if is_clean_home_frame(frame.frame) else "unknown"

    session.run_action(
        action_class="navigation",
        label=label,
        capture=capture,
        dispatch=dispatch,
        recognize=recognize,
        consequence_class="navigation_only",
        settled_successor=settled_successor,
    )
    if not settled:
        settled_successor()
    return immediate[0], settled[-1]
