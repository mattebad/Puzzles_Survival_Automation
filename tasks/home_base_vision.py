"""Zoom-independent Base/town surface recognition for BlueStacks 800x1280.

Answers only: "are we on the town/base screen?"  It does not classify camera zoom,
produce atlas transforms, bind buildings, or authorize transport.  Canonical Home
and atlas localization remain separate facts in ``tasks.home_context``.

The global bottom navigation strip is deliberately never consulted: it is present
on non-Base screens and must not establish Base identity.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import unicodedata

import cv2
import numpy as np
import pytesseract


NATIVE_WIDTH = 800
NATIVE_HEIGHT = 1280
PROFILE_SIZE = (NATIVE_WIDTH, NATIVE_HEIGHT)
Box = tuple[int, int, int, int]

# Left Home quick-action stack (Build / Research / Pit).
LEFT_STACK_BAND: Box = (0, 260, 160, 720)
# Headquarters label neighborhood across common zoomed poses.
HEADQUARTERS_BAND: Box = (220, 380, 600, 640)
# Mid-field landmark band (Watch Tower, camps, tavern, etc.).
LANDMARK_BAND: Box = (80, 200, 720, 900)
# Top resource HUD — corroborating only, never sufficient alone.
HUD_BAND: Box = (0, 0, 800, 70)

LEFT_CONTROL_TOKENS = ("build", "research", "pit", "idle")
LANDMARK_TOKENS = (
    "headquarter",
    "watch tower",
    "watch",
    "shooter",
    "fighter",
    "rider",
    "vehicle",
    "noah",
    "tavern",
    "warehouse",
)
NEGATIVE_SURFACE_TOKENS = (
    "exit the game",
    "cash mall",
    "purchase",
    "nova",
    "praise",
    "captcha",
    "login",
)


@dataclass(frozen=True)
class BaseSurfaceRecognition:
    recognized: bool
    confidence: float
    evidence: tuple[str, ...]
    reason: str
    frame_sha256: str
    native_ok: bool
    overlay: bool = False


def _normalized(text: str) -> str:
    folded = unicodedata.normalize("NFKD", str(text).casefold())
    return " ".join(
        "".join(char for char in folded if not unicodedata.combining(char)).split()
    )


def _digest(frame: np.ndarray) -> str:
    ok, encoded = cv2.imencode(".png", frame)
    if not ok:
        raise ValueError("failed to encode frame for digest")
    return hashlib.sha256(encoded.tobytes()).hexdigest()


def _ocr(frame: np.ndarray, box: Box, *, psm: int = 6) -> str:
    image = frame[box[1] : box[3], box[0] : box[2]]
    enlarged = cv2.resize(image, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
    return _normalized(pytesseract.image_to_string(enlarged, config=f"--psm {psm}"))


def _band_text(frame: np.ndarray, box: Box) -> str:
    return " ".join((_ocr(frame, box, psm=6), _ocr(frame, box, psm=11)))


def _hud_signal(text: str) -> bool:
    values = re.findall(r"\b\d+(?:\.\d+)?\s*[kmb]\b", text)
    return len(values) >= 3 and "+" in text


def recognize_base_surface(
    frame: np.ndarray,
    *,
    stale: bool = False,
    overlay: bool = False,
) -> BaseSurfaceRecognition:
    """Recognize the Base/town surface without requiring fully-zoomed-out atlas pose."""

    if frame is None or not isinstance(frame, np.ndarray) or frame.ndim != 3:
        return BaseSurfaceRecognition(
            False,
            0.0,
            (),
            "invalid_frame",
            "",
            False,
            overlay=overlay,
        )
    if frame.shape[:2] != (NATIVE_HEIGHT, NATIVE_WIDTH):
        return BaseSurfaceRecognition(
            False,
            0.0,
            (),
            "unexpected_native_profile",
            "",
            False,
            overlay=overlay,
        )
    digest = _digest(frame)
    if stale:
        return BaseSurfaceRecognition(
            False,
            0.0,
            (),
            "stale_frame",
            digest,
            True,
            overlay=overlay,
        )
    if overlay:
        return BaseSurfaceRecognition(
            False,
            0.0,
            (),
            "overlay_present",
            digest,
            True,
            overlay=True,
        )

    left_text = _band_text(frame, LEFT_STACK_BAND)
    hq_text = _band_text(frame, HEADQUARTERS_BAND)
    landmark_text = _band_text(frame, LANDMARK_BAND)
    hud_text = _band_text(frame, HUD_BAND)
    combined = " ".join((left_text, hq_text, landmark_text, hud_text))

    negative_hits = tuple(
        token for token in NEGATIVE_SURFACE_TOKENS if token in combined
    )
    # "nova"/"praise" can appear in chat; require strong modal negatives only.
    hard_negatives = tuple(
        token
        for token in negative_hits
        if token in {"exit the game", "cash mall", "purchase", "captcha", "login"}
    )
    if hard_negatives:
        return BaseSurfaceRecognition(
            False,
            0.0,
            hard_negatives,
            "negative_surface",
            digest,
            True,
            overlay=overlay,
        )

    left_hits = tuple(
        token for token in ("build", "research", "pit") if token in left_text
    )
    if "idle" in left_text and "pit" not in left_hits:
        left_hits = left_hits + ("idle",)
    headquarters = "headquarter" in hq_text or "headquarter" in landmark_text
    landmark_hits = tuple(
        token
        for token in (
            "watch tower",
            "shooter",
            "fighter",
            "rider",
            "vehicle",
            "noah",
            "tavern",
            "warehouse",
        )
        if token in landmark_text
    )
    # Collapse "watch" alone only when "watch tower" missed.
    if "watch tower" not in landmark_hits and "watch" in landmark_text:
        landmark_hits = landmark_hits + ("watch",)
    hud = _hud_signal(hud_text)

    evidence: list[str] = []
    evidence.extend(f"left:{token}" for token in left_hits)
    if headquarters:
        evidence.append("headquarters")
    evidence.extend(f"landmark:{token}" for token in landmark_hits)
    if hud:
        evidence.append("resource_hud")

    left_ok = len(left_hits) >= 2
    identity_ok = headquarters or len(landmark_hits) >= 2
    recognized = bool(left_ok and identity_ok)
    if not recognized:
        return BaseSurfaceRecognition(
            False,
            0.0,
            tuple(evidence),
            "insufficient_base_evidence",
            digest,
            True,
            overlay=overlay,
        )

    confidence = 0.55
    confidence += 0.1 * min(len(left_hits), 3)
    if headquarters:
        confidence += 0.15
    confidence += 0.05 * min(len(landmark_hits), 3)
    if hud:
        confidence += 0.05
    confidence = min(confidence, 0.99)
    return BaseSurfaceRecognition(
        True,
        confidence,
        tuple(evidence),
        "base_surface_recognized",
        digest,
        True,
        overlay=overlay,
    )
