"""Noah navigation adapter for shared direct-runtime Atlas normalization."""

from __future__ import annotations

from pathlib import Path

from scripts.atlas_runtime_startup import (
    AtlasRuntimeStartupError,
    normalize_runtime_home_atlas_startup,
)
def prepare_noah_home_atlas_startup(
    *,
    runtime,
    atlas,
    atlas_path: Path,
    settle_seconds: float,
):
    """Return a localizer and startup records only after canonical readiness."""

    return normalize_runtime_home_atlas_startup(
        runtime=runtime,
        atlas=atlas,
        atlas_path=atlas_path,
        execute=True,
        settle_seconds=settle_seconds,
        maximum_zoom_inputs=2,
    )


def bind_noah_route_startup(route, *, runtime, settle_seconds: float) -> None:
    """Normalize before route execution and seed its existing evidence ledger."""

    try:
        localizer, records = prepare_noah_home_atlas_startup(
            runtime=runtime,
            atlas=route.atlas,
            atlas_path=route.atlas_path,
            settle_seconds=settle_seconds,
        )
    except AtlasRuntimeStartupError as exc:
        route.records.extend(exc.records)
        route.input_count = runtime.input_count
        raise
    route.home_localizer = localizer
    route._home_localizer_injected = True
    route.records.extend(records)
    route.input_count = runtime.input_count
