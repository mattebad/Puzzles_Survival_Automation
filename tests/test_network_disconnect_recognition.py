from __future__ import annotations

import unittest
from unittest import mock

import numpy as np

from scripts import bluestacks_popup_recognition as recognition
from scripts.bluestacks_popup_recognition import (
    DISCONNECT_BUTTON_EXPECTED,
    DISCONNECT_PANEL_EXPECTED,
    NETWORK_DISCONNECT_IDENTITY,
    NETWORK_DISCONNECT_TARGET,
    parse_disconnect_message,
    recognize_network_disconnect,
)


EXACT_MESSAGE = "Disconnected. Reconnect now?[10054]"
BACKGROUND = 18
PANEL_GRAY = 44
GOLD_BGR = (60, 123, 180)
LABEL_GRAY = 245


def disconnect_frame(
    *,
    panel: bool = True,
    buttons: tuple[tuple[int, int, int, int], ...] = (DISCONNECT_BUTTON_EXPECTED,),
    centered_label: bool = True,
) -> np.ndarray:
    """Synthetic native 800x1280 frame shaped like the calibrated 10054 modal."""
    frame = np.full((1280, 800, 3), BACKGROUND, np.uint8)
    if panel:
        x0, y0, x1, y1 = DISCONNECT_PANEL_EXPECTED
        frame[y0:y1, x0:x1] = PANEL_GRAY
    for x0, y0, x1, y1 in buttons:
        frame[y0:y1, x0:x1] = GOLD_BGR
        if centered_label:
            cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
            frame[cy - 11:cy + 11, cx - 50:cx + 50] = LABEL_GRAY
    return frame


class NetworkDisconnectRecognitionTests(unittest.TestCase):
    def recognize(
        self,
        frame: np.ndarray,
        *,
        message: str = EXACT_MESSAGE,
        confirm: str = "confirm",
    ) -> tuple[dict, mock.MagicMock, mock.MagicMock]:
        with mock.patch.object(
            recognition, "_read_disconnect_message", return_value=message
        ) as read_message, mock.patch.object(
            recognition, "_read_disconnect_confirm", return_value=confirm
        ) as read_confirm:
            detail = recognize_network_disconnect(frame)
        return detail, read_message, read_confirm

    def assert_not_authorized(self, detail: dict) -> None:
        self.assertFalse(detail["recognized"])
        self.assertIsNone(detail["popup_identity"])
        self.assertIsNone(detail["target_identity"])
        self.assertIsNone(detail["target"])
        self.assertIsNone(detail["target_center"])

    def test_identity_constants(self):
        self.assertEqual(NETWORK_DISCONNECT_IDENTITY, "NETWORK_DISCONNECTED_10054")
        self.assertEqual(NETWORK_DISCONNECT_TARGET, "network-disconnect-confirm")

    def test_exact_disconnect_modal_is_recognized_with_measured_confirm(self):
        detail, read_message, read_confirm = self.recognize(disconnect_frame())
        self.assertTrue(detail["recognized"])
        self.assertEqual(detail["popup_identity"], NETWORK_DISCONNECT_IDENTITY)
        self.assertEqual(detail["target_identity"], NETWORK_DISCONNECT_TARGET)
        self.assertEqual(detail["target"], (278, 672, 522, 750))
        self.assertEqual(detail["target_center"], (400, 711))
        self.assertFalse(detail["blocking_unknown_modal"])
        self.assertEqual(detail["reason"], "network_disconnect_10054_recognized")
        self.assertEqual(detail["code_text"], "10054")
        self.assertTrue(detail["code_identity"])
        self.assertTrue(detail["message_identity"])
        self.assertTrue(detail["literal_confirm"])
        self.assertTrue(detail["label_isolated"])
        self.assertEqual(detail["panel_bounds"], DISCONNECT_PANEL_EXPECTED)
        self.assertEqual(detail["button_candidates"], 1)
        read_message.assert_called_once()
        read_confirm.assert_called_once()
        self.assertEqual(read_confirm.call_args.args[1], (278, 672, 522, 750))

    def test_target_follows_current_pixels_not_a_fixed_point(self):
        shifted = (284, 676, 528, 754)
        detail, _read_message, _read_confirm = self.recognize(disconnect_frame(buttons=(shifted,)))
        self.assertTrue(detail["recognized"])
        self.assertEqual(detail["target"], shifted)
        self.assertEqual(detail["target_center"], (406, 715))

    def test_ocr_spacing_and_bracket_variants_still_require_exact_words_and_code(self):
        for message in (
            "disconnected. reconnect now?[10054]",
            "Disconnected.  Reconnect now? [ 10054 ]",
            "Disconnected Reconnect now (10054)",
        ):
            with self.subTest(message=message):
                detail, _read_message, _read_confirm = self.recognize(disconnect_frame(), message=message)
                self.assertTrue(detail["recognized"])

    def test_wrong_or_missing_code_is_rejected_and_blocks(self):
        cases = {
            "Disconnected. Reconnect now?[100540]": "disconnect_code_mismatch",
            "Disconnected. Reconnect now?[010054]": "disconnect_code_mismatch",
            "Disconnected. Reconnect now?[10053]": "disconnect_code_mismatch",
            "Disconnected. Reconnect now?[1005]": "disconnect_code_mismatch",
            "Disconnected. Reconnect now?": "disconnect_code_missing",
            "Disconnected. Reconnect now?[]": "disconnect_text_mismatch",
            "Disconnected. Reconnect now?10054": "disconnect_text_mismatch",
        }
        for message, reason in cases.items():
            with self.subTest(message=message):
                detail, _read_message, _read_confirm = self.recognize(disconnect_frame(), message=message)
                self.assert_not_authorized(detail)
                self.assertEqual(detail["reason"], reason)
                self.assertTrue(detail["blocking_unknown_modal"])

    def test_100540_is_not_10054(self):
        identity, code = parse_disconnect_message("Disconnected. Reconnect now?[100540]")
        self.assertTrue(identity)
        self.assertEqual(code, "100540")
        detail, _read_message, _read_confirm = self.recognize(
            disconnect_frame(), message="Disconnected. Reconnect now?[100540]"
        )
        self.assertFalse(detail["code_identity"])
        self.assert_not_authorized(detail)

    def test_wrong_or_missing_message_text_is_rejected_and_blocks(self):
        for message in (
            "",
            "Reconnect now?[10054]",
            "Disconnected.[10054]",
            "Connection lost. Reconnect now?[10054]",
            "Disconnected. Reconnecting now?[10054]",
            "Disconnected. Reconnect later?[10054]",
            "Disconnected. Reconnect now? Contact support[10054]",
            "Account logged in elsewhere. Reconnect now?[10054]",
        ):
            with self.subTest(message=message):
                detail, _read_message, _read_confirm = self.recognize(disconnect_frame(), message=message)
                self.assert_not_authorized(detail)
                self.assertFalse(detail["message_identity"])
                self.assertEqual(detail["reason"], "disconnect_text_mismatch")
                self.assertTrue(detail["blocking_unknown_modal"])

    def test_unrelated_confirm_on_same_dialog_layout_does_not_authorize(self):
        detail, _read_message, read_confirm = self.recognize(
            disconnect_frame(), message="Are you sure you want to exit the game?"
        )
        read_confirm.assert_called_once()
        self.assertTrue(detail["literal_confirm"])
        self.assertTrue(detail["button_geometry_valid"])
        self.assert_not_authorized(detail)
        self.assertEqual(detail["reason"], "disconnect_text_mismatch")
        self.assertTrue(detail["blocking_unknown_modal"])

    def test_non_literal_confirm_button_text_is_rejected(self):
        for confirm in ("", "cancel", "confirm purchase", "confirm!", "reconnect", "ok"):
            with self.subTest(confirm=confirm):
                detail, _read_message, _read_confirm = self.recognize(disconnect_frame(), confirm=confirm)
                self.assert_not_authorized(detail)
                self.assertFalse(detail["literal_confirm"])
                self.assertEqual(detail["reason"], "confirm_text_mismatch")
                self.assertTrue(detail["blocking_unknown_modal"])

    def test_off_center_button_label_is_not_isolated_confirm(self):
        frame = disconnect_frame(centered_label=False)
        frame[700:722, 296:340] = LABEL_GRAY
        detail, _read_message, _read_confirm = self.recognize(frame)
        self.assert_not_authorized(detail)
        self.assertFalse(detail["label_isolated"])
        self.assertEqual(detail["reason"], "confirm_label_not_isolated")
        self.assertTrue(detail["blocking_unknown_modal"])

    def test_missing_button_is_rejected_and_blocks(self):
        detail, _read_message, read_confirm = self.recognize(disconnect_frame(buttons=()))
        read_confirm.assert_not_called()
        self.assert_not_authorized(detail)
        self.assertEqual(detail["button_candidates"], 0)
        self.assertEqual(detail["reason"], "confirm_button_missing")
        self.assertTrue(detail["blocking_unknown_modal"])

    def test_ambiguous_buttons_are_rejected_and_block(self):
        frame = disconnect_frame(buttons=((190, 672, 390, 750), (410, 672, 610, 750)))
        detail, _read_message, read_confirm = self.recognize(frame)
        read_confirm.assert_not_called()
        self.assert_not_authorized(detail)
        self.assertEqual(detail["button_candidates"], 2)
        self.assertIsNone(detail["measured_button_bounds"])
        self.assertEqual(detail["reason"], "confirm_button_ambiguous")
        self.assertTrue(detail["blocking_unknown_modal"])

    def test_button_geometry_drift_is_rejected(self):
        for bounds in ((338, 672, 582, 750), (278, 700, 522, 770), (300, 680, 500, 740)):
            with self.subTest(bounds=bounds):
                detail, _read_message, read_confirm = self.recognize(disconnect_frame(buttons=(bounds,)))
                read_confirm.assert_not_called()
                self.assert_not_authorized(detail)
                self.assertFalse(detail["button_geometry_valid"])
                self.assertEqual(detail["reason"], "confirm_button_geometry_mismatch")
                self.assertTrue(detail["blocking_unknown_modal"])

    def test_extra_body_content_is_layout_mismatch_and_blocks(self):
        frame = disconnect_frame()
        frame[580:600, 120:600] = 140
        detail, _read_message, _read_confirm = self.recognize(frame)
        self.assert_not_authorized(detail)
        self.assertFalse(detail["body_blank"])
        self.assertEqual(detail["reason"], "disconnect_layout_mismatch")
        self.assertTrue(detail["blocking_unknown_modal"])

    def test_confirm_without_disconnect_panel_is_not_recognized(self):
        detail, _read_message, _read_confirm = self.recognize(disconnect_frame(panel=False))
        self.assert_not_authorized(detail)
        self.assertFalse(detail["panel_geometry_valid"])
        self.assertEqual(detail["reason"], "disconnect_panel_geometry_mismatch")

    def test_absent_dialog_is_not_recognized_and_not_blocking(self):
        for frame in (
            disconnect_frame(panel=False, buttons=()),
            np.tile(np.linspace(0, 90, 800, dtype=np.uint8)[None, :, None], (1280, 1, 3)),
        ):
            with self.subTest():
                detail, read_message, read_confirm = self.recognize(frame)
                read_message.assert_not_called()
                read_confirm.assert_not_called()
                self.assert_not_authorized(detail)
                self.assertFalse(detail["blocking_unknown_modal"])
                self.assertEqual(detail["reason"], "disconnect_dialog_absent")

    def test_bad_dimensions_and_types_are_rejected_without_ocr(self):
        native = disconnect_frame()
        for frame in (
            native[::2, ::2],
            native[:, :, 0],
            np.ascontiguousarray(np.transpose(native, (1, 0, 2))),
            np.dstack([native, native[:, :, :1]]),
            native.astype(np.float32),
            native.tolist(),
            None,
        ):
            with self.subTest(shape=getattr(frame, "shape", type(frame).__name__)):
                detail, read_message, read_confirm = self.recognize(frame)
                read_message.assert_not_called()
                read_confirm.assert_not_called()
                self.assert_not_authorized(detail)
                self.assertFalse(detail["blocking_unknown_modal"])
                self.assertEqual(detail["reason"], "profile_dimensions_mismatch")



if __name__ == "__main__":
    unittest.main()
