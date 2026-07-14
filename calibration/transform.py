"""Reference-coordinate calibration for development reports.

Outputs are deliberately provisional. Production input must bind a candidate to a current
Bliss-native anchor or target and cannot authorize from this module alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Iterable, Optional, Sequence, Tuple

Point = Tuple[float, float]
ROI = Tuple[float, float, float, float]


@dataclass(frozen=True)
class Insets:
    left: float = 0.0
    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0

    def __post_init__(self) -> None:
        if min(self.left, self.top, self.right, self.bottom) < 0:
            raise ValueError("viewport insets cannot be negative")


@dataclass(frozen=True)
class ScreenGeometry:
    width: float
    height: float
    insets: Insets = Insets()

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("screen dimensions must be positive")
        if self.viewport_width <= 0 or self.viewport_height <= 0:
            raise ValueError("insets must leave a positive viewport")

    @property
    def viewport_width(self) -> float:
        return self.width - self.insets.left - self.insets.right

    @property
    def viewport_height(self) -> float:
        return self.height - self.insets.top - self.insets.bottom


@dataclass(frozen=True)
class ScreenFamilyCorrection:
    name: str
    offset_x: float
    offset_y: float
    supporting_anchor_ids: Tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("screen-family correction requires a name")
        if (self.offset_x or self.offset_y) and len(set(self.supporting_anchor_ids)) < 2:
            raise ValueError("nonzero screen-family correction requires at least two anchors")


@dataclass(frozen=True)
class CalibrationCandidate:
    point: Point
    transform_name: str
    manifest_id: str
    screen_family: Optional[str] = None
    production_authorized: bool = False

    def __post_init__(self) -> None:
        if self.production_authorized:
            raise ValueError("calibration candidates cannot authorize production input")


@dataclass(frozen=True)
class AffineCorrespondence:
    anchor_id: str
    source: Point
    observed: Point
    evidence_path: str


@dataclass(frozen=True)
class Residual:
    anchor_id: str
    source: Point
    observed: Point
    transformed: Point
    error_x: float
    error_y: float
    total_error: float


@dataclass(frozen=True)
class CoordinateTransform:
    name: str
    source: ScreenGeometry
    destination: ScreenGeometry
    scale_x: float
    scale_y: float
    offset_x: float = 0.0
    offset_y: float = 0.0
    correction: Optional[ScreenFamilyCorrection] = None

    def __post_init__(self) -> None:
        if not self.name or self.scale_x <= 0 or self.scale_y <= 0:
            raise ValueError("transform requires a name and positive scales")

    @classmethod
    def from_viewports(
        cls,
        name: str,
        source: ScreenGeometry,
        destination: ScreenGeometry,
        *,
        correction: Optional[ScreenFamilyCorrection] = None,
    ) -> "CoordinateTransform":
        return cls(
            name=name,
            source=source,
            destination=destination,
            scale_x=destination.viewport_width / source.viewport_width,
            scale_y=destination.viewport_height / source.viewport_height,
            correction=correction,
        )

    def transform_point(self, point: Point) -> Point:
        x, y = point
        correction_x = self.correction.offset_x if self.correction else 0.0
        correction_y = self.correction.offset_y if self.correction else 0.0
        return (
            self.destination.insets.left
            + (x - self.source.insets.left) * self.scale_x
            + self.offset_x
            + correction_x,
            self.destination.insets.top
            + (y - self.source.insets.top) * self.scale_y
            + self.offset_y
            + correction_y,
        )

    def candidate(self, point: Point, manifest_id: str) -> CalibrationCandidate:
        return CalibrationCandidate(
            point=self.transform_point(point),
            transform_name=self.name,
            manifest_id=manifest_id,
            screen_family=self.correction.name if self.correction else None,
        )

    def transform_xyxy(self, roi: ROI) -> ROI:
        x1, y1, x2, y2 = roi
        if x2 <= x1 or y2 <= y1:
            raise ValueError("ROI must be normalized xyxy with positive area")
        tx1, ty1 = self.transform_point((x1, y1))
        tx2, ty2 = self.transform_point((x2, y2))
        return tx1, ty1, tx2, ty2

    def residuals(self, correspondences: Iterable[AffineCorrespondence]) -> Tuple[Residual, ...]:
        output = []
        for item in correspondences:
            transformed = self.transform_point(item.source)
            error_x = item.observed[0] - transformed[0]
            error_y = item.observed[1] - transformed[1]
            output.append(
                Residual(
                    anchor_id=item.anchor_id,
                    source=item.source,
                    observed=item.observed,
                    transformed=transformed,
                    error_x=error_x,
                    error_y=error_y,
                    total_error=hypot(error_x, error_y),
                )
            )
        return tuple(output)

    @staticmethod
    def point_inside_roi(point: Point, roi: ROI, margin: float = 0.0) -> bool:
        if margin < 0:
            raise ValueError("margin cannot be negative")
        x, y = point
        x1, y1, x2, y2 = roi
        return x1 + margin <= x <= x2 - margin and y1 + margin <= y <= y2 - margin


def _fit_axis(values: Sequence[Tuple[float, float]]) -> Tuple[float, float]:
    if len(values) < 2:
        raise ValueError("affine fitting requires at least two correspondences")
    source_mean = sum(source for source, _ in values) / len(values)
    observed_mean = sum(observed for _, observed in values) / len(values)
    denominator = sum((source - source_mean) ** 2 for source, _ in values)
    if denominator == 0:
        raise ValueError("affine fitting requires varying source coordinates")
    scale = sum(
        (source - source_mean) * (observed - observed_mean)
        for source, observed in values
    ) / denominator
    if scale <= 0:
        raise ValueError("fitted scale must be positive")
    return scale, observed_mean - scale * source_mean


def fit_axis_aligned_affine(
    name: str,
    source: ScreenGeometry,
    destination: ScreenGeometry,
    correspondences: Sequence[AffineCorrespondence],
) -> CoordinateTransform:
    scale_x, offset_x = _fit_axis([(item.source[0], item.observed[0]) for item in correspondences])
    scale_y, offset_y = _fit_axis([(item.source[1], item.observed[1]) for item in correspondences])
    return CoordinateTransform(
        name=name,
        source=source,
        destination=destination,
        scale_x=scale_x,
        scale_y=scale_y,
        offset_x=offset_x,
        offset_y=offset_y,
    )
