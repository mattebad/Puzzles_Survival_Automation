"""Identity-neutral startup zoom policy for Home/world Atlas consumers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math

import numpy as np

from tasks.home_atlas import AmbiguityState, LocalizationResult, ZoomIdentity
from tasks.home_atlas_vision import (
    BlueStacksHomeLocalizer,
    classify_zoom,
    frame_digest,
)


class AtlasStartupDisposition(str, Enum):
    READY = "ready"
    RECOVER_ZOOM = "recover_zoom"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class AtlasStartupResult:
    localization: LocalizationResult
    source_frame_sha256: str
    disposition: AtlasStartupDisposition
    reason: str
    recovery_input_ordinal: int | None = None


class BlueStacksAtlasStartupNormalizer:
    """Classify current Home zoom and plan, but never dispatch, recovery inputs."""

    def __init__(
        self,
        localizer: BlueStacksHomeLocalizer,
        maximum_zoom_inputs: int = 2,
        zoom_classifier=None,
    ) -> None:
        if maximum_zoom_inputs < 1:
            raise ValueError("maximum_zoom_inputs must be positive")
        self.localizer = localizer
        self.zoom_classifier = zoom_classifier or classify_zoom
        self.maximum_zoom_inputs = min(maximum_zoom_inputs, 2)
        self.zoom_inputs = 0
        self._seen_recovery_frames: set[str] = set()
        self._planned_recovery_source: str | None = None

    @staticmethod
    def _zoom_value(localization: LocalizationResult) -> str:
        return str(
            getattr(localization.zoom_identity, "value", localization.zoom_identity)
        )

    @staticmethod
    def _current_and_unambiguous(
        localization: LocalizationResult,
        digest: str,
    ) -> bool:
        try:
            confidence = float(localization.confidence)
        except (TypeError, ValueError):
            return False
        residual = localization.residual_px
        if residual is not None:
            try:
                residual = float(residual)
            except (TypeError, ValueError):
                return False
            if not math.isfinite(residual):
                return False
        return bool(
            math.isfinite(confidence)
            and localization.frame_sha256 == digest
            and localization.ambiguity_state is AmbiguityState.NONE
            and not localization.stale
            and not localization.overlay
        )

    def _blocked(
        self,
        localization: LocalizationResult,
        digest: str,
    ) -> AtlasStartupResult:
        return AtlasStartupResult(
            localization,
            digest,
            AtlasStartupDisposition.BLOCKED,
            f"home_localization_ambiguous:{self._zoom_value(localization)}",
        )

    def observe(
        self,
        frame: np.ndarray,
        *,
        localization: LocalizationResult | None = None,
    ) -> AtlasStartupResult:
        digest = frame_digest(frame)
        localization = localization or self.localizer.localize(frame)
        if not self._current_and_unambiguous(localization, digest):
            return self._blocked(localization, digest)
        if (
            localization.recognized
            and localization.zoom_identity is ZoomIdentity.FULLY_ZOOMED_OUT
        ):
            return AtlasStartupResult(
                localization,
                digest,
                AtlasStartupDisposition.READY,
                "canonical_zoom_ready",
            )

        zoom_identity = localization.zoom_identity
        try:
            zoom_confidence = float(localization.confidence)
        except (TypeError, ValueError):
            zoom_confidence = math.nan
        recoverable_zoom = zoom_identity in {
            ZoomIdentity.ZOOMED_IN,
            ZoomIdentity.INTERMEDIATE,
        }
        corroborated_zoom = False
        geometry_confirmed_zoom = False
        if not recoverable_zoom or zoom_confidence < 0.85:
            canonical_reference = getattr(self.localizer, "canonical_reference", None)
            if canonical_reference is None:
                return self._blocked(localization, digest)
            zoom = self.zoom_classifier(frame, canonical_reference)
            geometry_confirmed_zoom = bool(
                zoom.identity in {ZoomIdentity.ZOOMED_IN, ZoomIdentity.INTERMEDIATE}
                and getattr(zoom, "scale", None) is not None
                and 0.20 <= zoom.scale < 0.965
                and getattr(zoom, "residual_px", None) is not None
                and zoom.residual_px <= 0.35
                and len(getattr(zoom, "supporting_landmarks", ())) >= 12
            )
            if not recoverable_zoom:
                zoom_identity = zoom.identity
                try:
                    zoom_confidence = float(zoom.confidence)
                except (TypeError, ValueError):
                    zoom_confidence = math.nan
                recoverable_zoom = zoom_identity in {
                    ZoomIdentity.ZOOMED_IN,
                    ZoomIdentity.INTERMEDIATE,
                }
            else:
                try:
                    corroborated_zoom = bool(
                        zoom.identity is zoom_identity
                        and zoom_confidence >= 0.70
                        and float(zoom.confidence) >= 0.70
                    )
                except (TypeError, ValueError):
                    corroborated_zoom = False

        if recoverable_zoom and (
            zoom_confidence >= 0.85
            or corroborated_zoom
            or geometry_confirmed_zoom
        ):
            if digest in self._seen_recovery_frames:
                return AtlasStartupResult(
                    localization,
                    digest,
                    AtlasStartupDisposition.BLOCKED,
                    "repeated_zoom_recovery_frame",
                )
            if self.zoom_inputs >= self.maximum_zoom_inputs:
                return AtlasStartupResult(
                    localization,
                    digest,
                    AtlasStartupDisposition.BLOCKED,
                    "maximum_zoom_recovery_inputs",
                )
            self._seen_recovery_frames.add(digest)
            self._planned_recovery_source = digest
            return AtlasStartupResult(
                localization,
                digest,
                AtlasStartupDisposition.RECOVER_ZOOM,
                "unsupported_zoom_requires_bounded_canonical_recovery",
                self.zoom_inputs + 1,
            )
        return self._blocked(localization, digest)

    def record_zoom_input_dispatched(self, source_frame_sha256: str) -> None:
        if source_frame_sha256 != self._planned_recovery_source:
            raise ValueError("zoom input does not match the planned current frame")
        self.zoom_inputs += 1
        self._planned_recovery_source = None
