"""Pixel-backed exhausted Nova counter and original 1→0 successor regression."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import pytesseract

from tasks.nova_praise import nova_postcondition_verified
from tasks import nova_praise_vision as vision
from tests.support.environment import requires_tesseract


FIXTURES = Path(__file__).parent / "fixtures/nova_zero_counter"


class NovaZeroCounterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provenance = json.loads((FIXTURES / "provenance.json").read_text())
        cls.before = cv2.imread(str(FIXTURES / "native-before-one.png"))
        cls.after = cv2.imread(str(FIXTURES / "native-after-zero.png"))

    @requires_tesseract
    def test_current_seven_attempt_screen_is_actionable(self):
        provenance = json.loads((FIXTURES / "native-current-seven.provenance.json").read_text())
        path = FIXTURES / "native-current-seven.png"
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), provenance["sha256"])
        result = vision.recognize_nova_frame(cv2.imread(str(path)), captured_monotonic=100.)
        self.assertTrue(result.observation.recognized)
        self.assertTrue(result.observation.praise_enabled)
        self.assertEqual(result.observation.attempts_remaining, 7)
        self.assertEqual(result.target(vision.NOVA_PRAISE_TARGET), vision.NOVA_PRAISE_ROI)

    @requires_tesseract
    def test_current_header_and_praise_label_are_both_required(self):
        original = cv2.imread(str(FIXTURES / "native-current-seven.png"))
        for roi in (vision.NOVA_HEADER_ROI, vision.NOVA_PRAISE_ROI):
            with self.subTest(roi=roi):
                frame = original.copy()
                x0, y0, x1, y1 = roi
                frame[y0:y1, x0:x1] = 0
                result = vision.recognize_nova_frame(frame, captured_monotonic=100.)
                self.assertFalse(result.observation.recognized)
                self.assertFalse(result.observation.praise_enabled)

    @requires_tesseract
    def test_actual_last_praise_has_exact_decrement_and_observed_cooldown(self):
        observations = []
        for frame, record in zip((self.before, self.after), self.provenance["frames"]):
            self.assertEqual(hashlib.sha256((FIXTURES / record["fixture"]).read_bytes()).hexdigest(),
                             record["transport_sha256"])
            observations.append(vision.recognize_nova_frame(
                frame, captured_monotonic=record["captured_monotonic"],
            ).observation)
        before, after = observations
        self.assertEqual(before.attempts_remaining, 1)
        self.assertTrue(before.praise_enabled)
        self.assertEqual(after.attempts_remaining, 0)
        self.assertTrue(after.recognized)
        self.assertFalse(after.praise_enabled)
        self.assertEqual(after.cooldown_seconds, 291)
        self.assertTrue(nova_postcondition_verified(before, after, now=after.captured_monotonic))

    @requires_tesseract
    def test_unknown_row_character_is_not_a_zero_without_the_visible_digit(self):
        missing = self.after.copy()
        missing[1180:1210, 550:580] = (30, 30, 30)
        self.assertIsNone(vision._attempts_from_frame(missing, "interaction attempts left: ©"))
        self.assertIsNone(vision._attempts_from_frame(missing, "interaction attempts left: 0"))
        result = vision.recognize_nova_frame(missing, captured_monotonic=100.)
        self.assertIsNone(result.observation.attempts_remaining)
        self.assertFalse(result.observation.recognized)

    @requires_tesseract
    def test_red_nonzero_nondigit_and_multiple_glyphs_cannot_supply_zero(self):
        for value in ("C", "Q", "O", "8", "00"):
            with self.subTest(value=value):
                changed = self.after.copy()
                changed[1180:1210, 550:600] = (30, 30, 30)
                cv2.putText(changed, value, (558, 1204), cv2.FONT_HERSHEY_SIMPLEX,
                            .75, (0, 0, 255), 2, cv2.LINE_AA)
                self.assertIsNone(vision._attempts_from_frame(changed, "interaction attempts left: ©"))

    @requires_tesseract
    def test_pixel_zero_cannot_override_conflicting_or_multiple_row_values(self):
        for text in ("interaction attempts left: 1", "interaction attempts left: 0 1",
                     "interaction attempts left: ©1", "interaction attempts left: © ©",
                     "attempts left: ©", "attempts left: 0", "interaction 0",
                     "interaction attempts left:"):
            with self.subTest(text=text):
                self.assertIsNone(vision._attempts_from_frame(self.after, text))

    def test_clipped_or_unassociated_red_zero_is_denied(self):
        glyph = self.after[1185:1205, 558:571].copy()
        for x, y in ((150, 1185), (640, 1185), (558, 1130)):
            with self.subTest(position=(x, y)):
                changed = self.after.copy()
                changed[1180:1210, 550:580] = (30, 30, 30)
                changed[y:y + 20, x:x + 13] = glyph
                self.assertIsNone(vision._attempts_from_frame(changed, "interaction attempts left: ©"))

    def test_digit_ocr_modes_must_agree(self):
        for readings in (("0", "8"), ("0", ""), ("O", "O")):
            with self.subTest(readings=readings), patch.object(
                pytesseract, "image_to_string", side_effect=readings,
            ):
                self.assertIsNone(vision._attempts_from_frame(self.after, "interaction attempts left: ©"))

    def test_stale_or_incompatible_frame_stays_unknown_despite_zero(self):
        for arguments in ({"stale": True}, {"incompatible_state": True}):
            with self.subTest(arguments=arguments):
                result = vision.recognize_nova_frame(self.after, captured_monotonic=100., **arguments)
                self.assertFalse(result.observation.recognized)
                self.assertIsNone(result.observation.attempts_remaining)


if __name__ == "__main__":
    unittest.main()
