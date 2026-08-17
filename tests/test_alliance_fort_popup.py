from __future__ import annotations

import unittest

from safe_action_core.popup import (
    ALLIANCE_FORT_WAVE_ALERT,
    UPDATE_RESTART_ALERT,
    PopupController,
    PopupObservation,
    alliance_fort_dismissal_allowed,
    classify_popup_semantics,
    popup_dismissal_verified,
)
from tasks.contracts import PopupMode, PopupOutcome


ALLIANCE_BODY = (
    "The next wave (Lv.20 Mutant Zombie) is about to attack Alliance Fort. "
    "Send your army to defend it!"
)


class AllianceFortPopupTests(unittest.TestCase):
    def test_exact_wave_semantics_allow_both_dismissal_controls(self):
        self.assertEqual(classify_popup_semantics("", ALLIANCE_BODY), ALLIANCE_FORT_WAVE_ALERT)
        self.assertTrue(alliance_fort_dismissal_allowed(ALLIANCE_FORT_WAVE_ALERT, "X"))
        self.assertTrue(alliance_fort_dismissal_allowed(ALLIANCE_FORT_WAVE_ALERT, "Confirm"))

    def test_update_restart_semantics_are_separate_and_blocked(self):
        update = "A new version is available. Download update and restart the game."
        self.assertEqual(classify_popup_semantics("", update), UPDATE_RESTART_ALERT)
        self.assertFalse(alliance_fort_dismissal_allowed(UPDATE_RESTART_ALERT, "Confirm"))
        self.assertFalse(
            alliance_fort_dismissal_allowed(
                classify_popup_semantics("", "Confirm"), "Confirm"
            )
        )

    def test_popup_controller_handles_only_exact_alliance_popup(self):
        controller = PopupController(PopupMode.NAVIGATION)
        self.assertEqual(
            controller.inspect(PopupObservation(ALLIANCE_FORT_WAVE_ALERT, benign=True)),
            PopupOutcome.HANDLED,
        )
        self.assertEqual(
            controller.inspect(PopupObservation("generic-confirm", benign=True)),
            PopupOutcome.UNKNOWN,
        )

    def test_popup_disappearance_and_successor_are_required(self):
        self.assertTrue(
            popup_dismissal_verified(ALLIANCE_FORT_WAVE_ALERT, True, False, True)
        )
        self.assertFalse(
            popup_dismissal_verified(ALLIANCE_FORT_WAVE_ALERT, True, True, True)
        )
        self.assertFalse(
            popup_dismissal_verified(ALLIANCE_FORT_WAVE_ALERT, True, False, False)
        )

if __name__ == "__main__":
    unittest.main()
