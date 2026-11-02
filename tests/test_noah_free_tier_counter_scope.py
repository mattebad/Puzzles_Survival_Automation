from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np
import pytesseract

from tasks.noahs_tavern_recruit import (
    NOAHS_TAVERN_FREE_TARGET,
    NOAHS_TAVERN_SCREEN,
    RecruitTier,
    noah_recruit_authorizeable,
)
from tasks.noahs_tavern_recruit_maintenance import NoahMaintenanceState, PersistedTierState
from tasks.noahs_tavern_recruit_runtime import NoahAction, NoahTavernRecruitRuntimeController
from tasks.noahs_tavern_recruit_vision import (
    TAVERN_ATTEMPTS_ROI,
    TAVERN_FREE_ROI,
    TAVERN_HEADER_ROI,
    TAVERN_PAID_ROI,
    TAVERN_TITLE_ROI,
    recognize_noahs_tavern_frame,
)


FIXTURES = Path(__file__).with_name("fixtures") / "noah_free_tier_counter_scope"
INT_DEADLINE = 1793348459.2625244
ADV_DEADLINE = 1793434088.0746179


def recognized_source(tier, counter="0", *, control="Free Recruit 1x", enabled=True,
                      attempts_text=None, header="Noah's Tavern", title=None):
    frame = np.zeros((1280, 800, 3), dtype=np.uint8)
    labels = {
        11: header,
        29: title or tier.value,
        47: attempts_text if attempts_text is not None else f"Daily free attempts: {counter}",
        73: "9 Recruit 10x",
    }
    for box, marker in ((TAVERN_HEADER_ROI, 11), (TAVERN_TITLE_ROI, 29),
                        (TAVERN_ATTEMPTS_ROI, 47), (TAVERN_PAID_ROI, 73)):
        x0, y0, _, _ = box
        frame[y0:y0 + 8, x0:x0 + 8] = marker
    color = (180, 0, 180) if enabled else (80, 80, 80)
    x0, y0, x1, y1 = TAVERN_FREE_ROI
    frame[y0:y1, x0:x1] = color
    labels[color[0]] = control

    def ocr(image, _psm):
        return labels.get(int(image[5, 5, 0]), "")

    return recognize_noahs_tavern_frame(frame, captured_monotonic=100.0, ocr=ocr,
                                       include_home_ocr=False)


def exhausted_state():
    state = NoahMaintenanceState("offline-account", "offline-server", "offline-reset",
                                 basic_daily_count=5, revision=7)
    state.tiers = {
        RecruitTier.BASIC: PersistedTierState(0, None, 600, "action_performed"),
        RecruitTier.INT: PersistedTierState(0, INT_DEADLINE, 86400, "action_performed"),
        RecruitTier.ADV: PersistedTierState(0, ADV_DEADLINE, 172800, "action_performed"),
    }
    return state


class NoahFreeTierCounterScopeTests(unittest.TestCase):
    def assert_matured_intermediate_command(self, observed):
        state = exhausted_state()
        before_basic = state.tiers[RecruitTier.BASIC]
        before_advanced = state.tiers[RecruitTier.ADV]
        controller = NoahTavernRecruitRuntimeController(now=INT_DEADLINE + 60,
                                                       maintenance_state=state)
        command = controller.next_command(SimpleNamespace(
            observation=observed, frame_sha256=observed.frame_sha256,
        ))
        self.assertEqual(command.action, NoahAction.RECRUIT_FREE)
        self.assertEqual(command.tier, RecruitTier.INT)
        self.assertEqual(command.target_identity, "noahs-tavern-daily-free")
        self.assertEqual(command.target_roi, TAVERN_FREE_ROI)
        self.assertEqual(state.tiers[RecruitTier.INT], PersistedTierState(1, None, 86400, "rearmed"))
        self.assertEqual(state.tiers[RecruitTier.BASIC], before_basic)
        self.assertEqual(state.tiers[RecruitTier.ADV], before_advanced)
        self.assertEqual(state.basic_daily_count, 5)
        self.assertEqual(state.revision, 7)

    def test_retained_native_intermediate_source_with_basic_zero_is_eligible(self):
        path = FIXTURES / "intermediate-free-basic-zero-20261030.png"
        provenance = json.loads(path.with_suffix(".provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), provenance["transport_sha256"])
        original = Path(__file__).parents[1] / provenance["source"]
        if original.exists():
            self.assertEqual(original.read_bytes(), path.read_bytes())
        tesseract = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")
        with patch.object(pytesseract.pytesseract, "tesseract_cmd",
                          str(tesseract) if tesseract.exists() else "tesseract"):
            try:
                pytesseract.get_tesseract_version()
            except (OSError, RuntimeError, pytesseract.TesseractNotFoundError):
                self.skipTest("Tesseract unavailable for retained native OCR")
            frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
            self.assertIsNotNone(frame)
            observed = recognize_noahs_tavern_frame(frame, captured_monotonic=100.0)
        self.assertEqual(observed.frame_sha256, provenance["decoded_frame_sha256"])
        self.assertEqual(observed.screen_state, NOAHS_TAVERN_SCREEN)
        self.assertEqual(observed.selected_tier, RecruitTier.INT)
        selected = observed.tier(RecruitTier.INT)
        self.assertEqual(selected.attempts_remaining, 1)
        self.assertTrue(selected.free_control_visible)
        self.assertTrue(selected.free_control_enabled)
        self.assertEqual(selected.target_identity, NOAHS_TAVERN_FREE_TARGET)
        self.assertFalse(selected.cooldown_active)
        self.assertEqual((selected.cost_type, selected.cost_amount, selected.quantity), ("none", 0, 1))
        self.assertTrue(noah_recruit_authorizeable(observed, RecruitTier.INT))
        self.assert_matured_intermediate_command(observed)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), provenance["transport_sha256"])

    def test_single_tiers_use_enabled_free_control_independently_of_basic_counter(self):
        for tier in (RecruitTier.INT, RecruitTier.ADV):
            for counter in ("0", "3", "5", "|", ""):
                with self.subTest(tier=tier, basic_counter=counter):
                    observed = recognized_source(tier, counter)
                    self.assertEqual(observed.tier(tier).attempts_remaining, 1)
                    self.assertTrue(noah_recruit_authorizeable(observed, tier))

    def test_basic_free_button_with_zero_or_missing_counter_is_eligible_without_inventing_usage(self):
        for counter, remaining in (("0", 0), ("|", None), ("", None)):
            with self.subTest(counter=counter):
                observed = recognized_source(RecruitTier.BASIC, counter)
                self.assertEqual(observed.tier(RecruitTier.BASIC).attempts_remaining, remaining)
                self.assertTrue(noah_recruit_authorizeable(observed, RecruitTier.BASIC))
                state = exhausted_state()
                state.basic_daily_count = 0
                state.tiers[RecruitTier.BASIC] = PersistedTierState(5, None, 600, "reset_rollover")
                controller = NoahTavernRecruitRuntimeController(now=INT_DEADLINE - 60, maintenance_state=state)
                command = controller.next_command(SimpleNamespace(observation=observed, frame_sha256=observed.frame_sha256))
                self.assertEqual(command.action, NoahAction.RECRUIT_FREE)
                self.assertEqual(state.basic_daily_count, 0)
                # Saved five-action ownership still prevents a sixth single.
                capped = exhausted_state()
                controller = NoahTavernRecruitRuntimeController(now=INT_DEADLINE - 60, maintenance_state=capped)
                self.assertNotEqual(controller.next_command(SimpleNamespace(observation=observed, frame_sha256=observed.frame_sha256)).action, NoahAction.RECRUIT_FREE)
                self.assertEqual(capped.basic_daily_count, 5)

    def test_single_tier_paid_disabled_unknown_and_cooldown_sources_stay_blocked(self):
        cases = (
            {"control": "Recruit 1x"},
            {"enabled": False},
            {"control": "Free in ??? Recruit 1x"},
            {"attempts_text": "Daily free attempts: 0 Free in 00:09:52"},
            {"control": "Free in 23:59:51 Recruit 1x"},
        )
        for tier in RecruitTier:
            for changes in cases:
                with self.subTest(tier=tier, changes=changes):
                    observed = recognized_source(tier, **changes)
                    self.assertFalse(observed.tier(tier).free_control_enabled)
                    self.assertFalse(noah_recruit_authorizeable(observed, tier))

    def test_matured_intermediate_rearms_only_itself_from_current_source(self):
        self.assert_matured_intermediate_command(recognized_source(RecruitTier.INT))

    def test_enabled_control_does_not_bypass_future_persisted_deadline(self):
        observed = recognized_source(RecruitTier.INT)
        state = exhausted_state()
        before = state.to_json()
        controller = NoahTavernRecruitRuntimeController(now=INT_DEADLINE - 1,
                                                       maintenance_state=state)
        command = controller.next_command(SimpleNamespace(
            observation=observed, frame_sha256=observed.frame_sha256,
        ))
        self.assertNotEqual(command.action, NoahAction.RECRUIT_FREE)
        self.assertEqual(state.to_json(), before)


if __name__ == "__main__":
    unittest.main()
