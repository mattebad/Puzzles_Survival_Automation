"""Deterministic Home bottom-navigation recognition for the BlueStacks 800x1280 profile.

The bottom navigation bar (World | Hero | Quest | Bag | Mail | Alliance | More) is a
fixed, opaque UI overlay at a stable location on the locked runtime profile. It is
recognized by normalized template correlation of that fixed strip against a checked-in
ground-truth template -- NOT by OCR of a wide band that also captures the scrolling
world map and chat feed. Button tap points are fixed profile coordinates.

This intentionally replaces the earlier wide-band, PSM-11 OCR geometry that produced
nondeterministic results (e.g. missing a visible "Quest" label because the chat feed
flooded the tokens). Recognition never authorizes dispatch by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Optional, Tuple

import cv2
import numpy as np

NATIVE_WIDTH = 800
NATIVE_HEIGHT = 1280
RUNTIME_PROFILE_ID = "pns-bluestacks-5-p64-800x1280-v1"

# Fixed nav bar region on the native profile (half-open: [x0,x1) x [y0,y1)).
NAV_STRIP_BOX: Tuple[int, int, int, int] = (0, 1213, 800, 1280)

# Correlation floor. Observed on retained frames: real Home 0.973-1.000; a
# non-Home (Troop Training) frame scored -0.119. 0.90 separates them with wide margin.
HOME_CORRELATION_THRESHOLD = 0.90

# Fixed button tap points measured from the ground-truth template on this profile.
# x from OCR label centers; y is the nav-strip vertical center.
_TAP_Y = 1247
NAV_BUTTON_TAP_POINTS: Mapping[str, Tuple[int, int]] = {
    "world": (73, _TAP_Y),
    "hero": (197, _TAP_Y),
    "quest": (321, _TAP_Y),
    "bag": (431, _TAP_Y),
    "mail": (537, _TAP_Y),
    "alliance": (643, _TAP_Y),
    "more": (749, _TAP_Y),
}

_TEMPLATE_PATH = Path(__file__).with_suffix("").parent / "assets" / "home_nav" / "800x1280" / "home_nav_strip.png"


class HomeNavRecognitionError(ValueError):
    """Fail-closed recognition denial."""


@dataclass(frozen=True)
class HomeNavRecognition:
    is_home: bool
    correlation: float
    native_ok: bool
    reason: str

    def button_tap_point(self, name: str) -> Optional[Tuple[int, int]]:
        """Return the fixed tap point for a nav button, only when Home is recognized."""
        if not self.is_home:
            return None
        return NAV_BUTTON_TAP_POINTS.get(name.strip().lower())

    def quest_tap_point(self) -> Optional[Tuple[int, int]]:
        return self.button_tap_point("quest")


@lru_cache(maxsize=1)
def _load_template() -> np.ndarray:
    template = cv2.imread(str(_TEMPLATE_PATH), cv2.IMREAD_COLOR)
    if template is None:
        raise HomeNavRecognitionError(f"nav template not found: {_TEMPLATE_PATH}")
    x0, y0, x1, y1 = NAV_STRIP_BOX
    if template.shape[:2] != (y1 - y0, x1 - x0):
        raise HomeNavRecognitionError("nav template geometry does not match NAV_STRIP_BOX")
    return template


def nav_strip_correlation(frame_bgr: np.ndarray) -> float:
    """Normalized correlation of the fixed nav strip against the ground-truth template."""
    if not isinstance(frame_bgr, np.ndarray) or frame_bgr.ndim != 3:
        raise HomeNavRecognitionError("frame must be an HxWx3 BGR image")
    if frame_bgr.shape[:2] != (NATIVE_HEIGHT, NATIVE_WIDTH):
        raise HomeNavRecognitionError("frame geometry is not the native 800x1280 profile")
    x0, y0, x1, y1 = NAV_STRIP_BOX
    strip = frame_bgr[y0:y1, x0:x1]
    template = _load_template()
    result = cv2.matchTemplate(strip, template, cv2.TM_CCOEFF_NORMED)
    return float(result.max())


def recognize_home_nav(
    frame_bgr: np.ndarray,
    *,
    threshold: float = HOME_CORRELATION_THRESHOLD,
) -> HomeNavRecognition:
    """Recognize the Home bottom-navigation bar deterministically from a native frame."""
    try:
        correlation = nav_strip_correlation(frame_bgr)
    except HomeNavRecognitionError as exc:
        return HomeNavRecognition(False, 0.0, False, f"invalid_frame:{exc}")
    is_home = correlation >= threshold
    reason = "home_nav_recognized" if is_home else "home_nav_correlation_below_threshold"
    return HomeNavRecognition(
        is_home=is_home,
        correlation=correlation,
        native_ok=True,
        reason=reason,
    )
