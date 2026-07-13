#!/usr/bin/env python3
"""Fixed-profile, local-ROI recognizers for harmless navigation."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Dict, Tuple
import cv2
import numpy as np
from tasks.profile import (
    DAILY_HEADER,
    DAILY_SELECTED_TAB,
    HOME_LEFT,
    HOME_QUEST,
    HOME_RIGHT,
    QUEST_DAILY,
    QUEST_HEADER,
)

ROI = Tuple[int, int, int, int]
HOME_NAV_ROI: ROI = (0, 1120, 800, 1280)
H_QUEST_ROI: ROI = HOME_QUEST.roi
H_ANCHOR_ROIS: Tuple[ROI, ...] = (HOME_LEFT.roi, HOME_RIGHT.roi)
QUEST_TAB_ROI: ROI = QUEST_DAILY.roi
QUEST_HEADER_ROI: ROI = QUEST_HEADER.roi
DAILY_HEADER_ROI: ROI = DAILY_HEADER.roi
DAILY_SELECTED_TAB_ROI: ROI = DAILY_SELECTED_TAB.roi


@dataclass(frozen=True)
class LocalRecognition:
    state: str
    recognized: bool
    target_identity: str | None
    target_roi: ROI | None
    anchor_scores: Tuple[float, ...]
    target_score: float
    overlay_intersects: bool = False
    dangerous_intersects: bool = False

    def as_dict(self) -> Dict:
        return asdict(self)


def _crop(frame: np.ndarray, roi: ROI) -> np.ndarray:
    x0, y0, x1, y1 = roi
    return frame[y0:y1, x0:x1]


def similarity(candidate: np.ndarray, reference: np.ndarray) -> float:
    if candidate.shape != reference.shape or not candidate.size:
        return 0.0
    a, b = cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY), cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    pixel = 1.0 - float(np.mean(cv2.absdiff(a, b))) / 255.0
    edge = 1.0 - float(np.mean(cv2.absdiff(cv2.Canny(a, 80, 180), cv2.Canny(b, 80, 180)))) / 255.0
    return round(0.7 * pixel + 0.3 * edge, 6)


def recognize_home_quest(frame: np.ndarray, reference: np.ndarray, overlay_intersects=False, dangerous_intersects=False) -> LocalRecognition:
    if frame.shape != (1280, 800, 3) or reference.shape != frame.shape:
        return LocalRecognition("UNKNOWN", False, None, None, (), 0.0)
    anchors = tuple(similarity(_crop(frame, r), _crop(reference, r)) for r in H_ANCHOR_ROIS)
    target = similarity(_crop(frame, H_QUEST_ROI), _crop(reference, H_QUEST_ROI))
    ok = min(anchors) >= 0.90 and target >= 0.94 and not overlay_intersects and not dangerous_intersects
    return LocalRecognition("HOME_BASE" if ok else "UNKNOWN", ok, "home-quest-entry" if ok else None, H_QUEST_ROI if ok else None, anchors, target, overlay_intersects, dangerous_intersects)


def recognize_local_state(frame: np.ndarray, reference: np.ndarray, state: str, target_roi: ROI, target_id: str) -> LocalRecognition:
    """Recognize Quest navigation from a local header anchor and target only."""
    if frame.shape != (1280, 800, 3) or reference.shape != frame.shape:
        return LocalRecognition("UNKNOWN", False, None, None, (), 0.0)
    header_roi = QUEST_HEADER_ROI if state == "QUEST" else DAILY_HEADER_ROI
    header = similarity(_crop(frame, header_roi), _crop(reference, header_roi))
    target = similarity(_crop(frame, target_roi), _crop(reference, target_roi))
    ok = header >= 0.88 and target >= 0.90
    return LocalRecognition(state if ok else "UNKNOWN", ok, target_id if ok else None, target_roi if ok else None, (header,), target)


def recognize_daily_selected(
    frame: np.ndarray,
    daily_reference: np.ndarray,
    main_reference: np.ndarray,
) -> LocalRecognition:
    """Require the Daily tab's selected visual state, not merely its label."""
    shapes = (frame.shape, daily_reference.shape, main_reference.shape)
    if any(shape != (1280, 800, 3) for shape in shapes):
        return LocalRecognition("UNKNOWN", False, None, None, (), 0.0)
    selected = similarity(
        _crop(frame, DAILY_SELECTED_TAB_ROI),
        _crop(daily_reference, DAILY_SELECTED_TAB_ROI),
    )
    main_state = similarity(
        _crop(frame, DAILY_SELECTED_TAB_ROI),
        _crop(main_reference, DAILY_SELECTED_TAB_ROI),
    )
    # The Main Quest fixture is an explicit negative. The margin prevents a broad
    # header match from treating an unselected Daily label as a selected tab.
    ok = selected >= DAILY_SELECTED_TAB.threshold and selected >= main_state + 0.02
    return LocalRecognition(
        "DAILY_QUEST" if ok else "UNKNOWN",
        ok,
        "daily-quest-selected" if ok else None,
        DAILY_SELECTED_TAB_ROI if ok else None,
        (selected, main_state),
        selected,
    )
