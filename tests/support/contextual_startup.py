"""Contextual startup-recovery fakes: PNG device, frame markers, overlay recognizers."""
from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path
import unittest

import cv2
import numpy as np

from scripts import startup_recovery as recovery
from scripts.bluestacks_native_runtime import NATIVE_RUNTIME_PROFILE_ID
from scripts.startup_surface_recognition import (
    SCARLETT_EXPECTED_SUCCESSOR, SCARLETT_FORBIDDEN_PURCHASE_ROIS,
    SCARLETT_MAX_INPUTS, SCARLETT_SAFE_BACK_ROI, SCARLETT_SAFE_BACK_TARGET_IDENTITY,
    SCARLETT_THREE_DAY_PACK,
)


SCARLETT, ARTWORK, RETRY, RETRY_ART = 31, 71, 73, 74
MOVED, LOST, VIP, COMMERCIAL, MODAL, UNKNOWN, HOME = 81, 101, 91, 121, 161, 181, 211
VIP_ROI = (263, 781, 537, 869)


def marker(frame):
    return int(frame[200, 200, 0])


def windows_short_path(path):
    """Get a real filesystem alias; never substitute a textual approximation."""
    if os.name != "nt":
        raise unittest.SkipTest("Windows filesystem aliases require GetShortPathNameW")
    get_short = ctypes.WinDLL("kernel32", use_last_error=True).GetShortPathNameW
    get_short.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint)
    get_short.restype = ctypes.c_uint
    buffer = ctypes.create_unicode_buffer(32768)
    length = get_short(str(path), buffer, len(buffer))
    if not length or length >= len(buffer):
        raise OSError(ctypes.get_last_error(), "GetShortPathNameW failed")
    alias = Path(buffer.value)
    if alias == path.resolve():
        raise unittest.SkipTest("This filesystem has no short alias for the test path")
    return alias


class PngDevice:
    def __init__(self):
        self.frames = []
        self.current = HOME
        self.taps = []
        self.transport_failure = False

    def capture_png(self):
        if self.frames:
            self.current = self.frames.pop(0)
        frame = np.full((1280, 800, 3), 17, np.uint8)
        frame[100:1200, :, :] = self.current
        ok, encoded = cv2.imencode(".png", frame)
        assert ok
        return encoded.tobytes()

    def dispatch_tap(self, point):
        self.taps.append(point)
        if self.transport_failure:
            raise RuntimeError("transport completion uncertain")


def startup_surface(frame, payload=None):
    state = marker(frame)
    if state not in {SCARLETT, ARTWORK, RETRY, RETRY_ART, MOVED, LOST}:
        return {"recognized": False, "commercial_looking": state == COMMERCIAL}
    payload = payload if payload is not None else cv2.imencode(".png", frame)[1].tobytes()
    digest = hashlib.sha256(payload).hexdigest()
    detail = {
        "recognized": True, "surface_identity": SCARLETT_THREE_DAY_PACK,
        "surface_kind": "full_page", "runtime_profile_id": NATIVE_RUNTIME_PROFILE_ID,
        "width": 800, "height": 1280, "frame_sha256": digest,
        "title_text": "scarlett 3-day pack", "title_identity": True,
        "semantic_evidence": (
            "title:Scarlett 3-Day Pack", "full_page_real_money_promotion",
            "visible_in_game_back_upper_left", "purchase_regions_excluded",
            "current_offer_benefits_and_three_day_rows", "current_first_topup_notice",
        ),
        "safe_exit_target_identity": SCARLETT_SAFE_BACK_TARGET_IDENTITY,
        "safe_exit_roi": SCARLETT_SAFE_BACK_ROI,
        "forbidden_purchase_rois": SCARLETT_FORBIDDEN_PURCHASE_ROIS,
        "purchase_exclusion_verified": True, "critical_roi_hashes": (("artwork", digest),),
        "page_context_verified": True, "measured_back_roi": (47, 0, 128, 59),
        "expected_successor": SCARLETT_EXPECTED_SUCCESSOR,
        "max_inputs": SCARLETT_MAX_INPUTS, "target_count": 1,
    }
    if state == MOVED:
        detail.update(safe_exit_roi=(200, 100, 320, 160), measured_back_roi=(207, 100, 280, 150))
    elif state == LOST:
        detail["measured_back_roi"] = None
    return detail

def reset_popup(frame):
    if marker(frame) == VIP:
        return {
            "recognized": True, "popup_identity": "VIP_POINTS_GET_PTS",
            "target_identity": recovery.VIP_RESET_TARGET,
            "target": VIP_ROI, "target_center": (400, 825),
            "title_identity": True, "body_identity": True, "literal_close": True,
            "geometry_valid": True, "panel_present": True,
        }
    return {"recognized": False, "blocking_unknown_modal": marker(frame) == MODAL}
