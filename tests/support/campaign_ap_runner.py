"""Campaign AP runner fakes: scripted phases, fake ADB worlds, and frame recognizers."""
from dataclasses import replace
import hashlib

import cv2
import numpy as np

from tasks.campaign_auto_battle import (CampaignRouteObservation, CampaignScreen, CampaignStage)
from tasks.campaign_auto_battle_vision import CampaignFrameRecognition


STAGE = CampaignStage(1, 15, 9)
PHASES = ("home", "stage", "lineup", "battle", "winner", "chapter", "tier", "returned-home",
          "wrong-stage", "lineup-again")
STAGE_ROI = (119, 842, 365, 921)


def recognize(frame, _stage, **_kwargs):
    phase = PHASES[int(frame[0, 0, 0])]
    if phase in {"home", "returned-home"}:
        observation = CampaignRouteObservation(screen=CampaignScreen.HOME_BASE,
                                               ap_current=120 if phase == "home" else 107)
        targets = ()
    elif phase in {"stage", "wrong-stage"}:
        observation = CampaignRouteObservation(screen=CampaignScreen.STAGE_DIALOG, stage_dialog=STAGE,
                                               ap_current=120, ap_cost=20 if phase == "wrong-stage" else 14,
                                               challenge_ready=True)
        targets = (("campaign-challenge-1-15-9", STAGE_ROI),)
    elif phase in {"lineup", "lineup-again"}:
        observation = CampaignRouteObservation(screen=CampaignScreen.HERO_LINEUP, lineup_challenge_ready=True)
        targets = (("campaign-lineup-challenge", (276, 1168, 524, 1252)),)
    elif phase == "battle":
        observation = CampaignRouteObservation(screen=CampaignScreen.BATTLE, auto_enabled=True)
        targets = ()
    elif phase == "winner":
        observation = CampaignRouteObservation(screen=CampaignScreen.RESULT, winner_visible=True,
                                               loot_visible=True, tap_to_continue_visible=True)
        targets = (("campaign-victory-continue", (300, 1133, 500, 1158)),)
    elif phase == "chapter":
        observation = CampaignRouteObservation(screen=CampaignScreen.CHAPTER_MAP, selected_tier=1,
                                               chapter_number=15, ap_current=107)
        targets = (("campaign-chapter-back", (705, 1028, 767, 1084)),)
    else:
        observation = CampaignRouteObservation(screen=CampaignScreen.TIER_MAP, selected_tier=1, ap_current=107)
        targets = (("campaign-exit-base", (700, 950, 790, 1050)),)
    return CampaignFrameRecognition(observation, hashlib.sha256(frame.tobytes()).hexdigest(), targets, {})


class FakeADB:
    """Only PNG bytes and transport observations; no device API is available."""
    def __init__(self, phase="stage"):
        self.phase = phase
        self.inputs = []
        self.capture_count = 0
        self.on_capture = None
        self.on_input = None
        self.repeat_lineup = False

    def capture_png(self):
        self.capture_count += 1
        if self.on_capture:
            self.on_capture(self.capture_count)
        phase = self.phase
        frame = np.full((1280, 800, 3), PHASES.index(phase), np.uint8)
        frame[1, 1] = self.capture_count % 255  # Fresh animation does not change semantic phase.
        if hasattr(self, "ap"):
            frame[2, 2] = (self.ap, self.cost, 0)
        success, png = cv2.imencode(".png", frame)
        assert success
        if phase == "battle":
            self.phase = "winner"
        return png.tobytes()

    def dispatch_tap(self, point):
        before = self.phase
        self.inputs.append(("tap", point))
        self.phase = {"home": "stage", "stage": "lineup", "lineup": "lineup-again" if self.repeat_lineup else "battle",
                      "winner": "chapter", "chapter": "tier", "tier": "returned-home"}.get(before, before)
        if self.on_input:
            self.on_input(len(self.inputs))

    def dispatch_swipe(self, start, end, duration=500):
        self.inputs.append(("swipe", start, end, duration))
        if self.on_input:
            self.on_input(len(self.inputs))


class DrainFakeADB(FakeADB):
    """Mutable AP and chapter-local repeat navigation; transport stays fake."""
    def __init__(self, ap=120, cost=14, regen_per_battle=0, phase="home"):
        super().__init__(phase)
        self.ap, self.cost, self.regen_per_battle = ap, cost, regen_per_battle
        self.battles_started = self.victories = 0

    def dispatch_tap(self, point):
        before = self.phase
        if before == "lineup":
            self.battles_started += 1
            self.ap -= self.cost
        elif before == "winner":
            self.victories += 1
            regeneration = (self.regen_per_battle[self.victories - 1]
                            if isinstance(self.regen_per_battle, (tuple, list))
                            and self.victories <= len(self.regen_per_battle)
                            else self.regen_per_battle if type(self.regen_per_battle) is int else 0)
            self.ap = min(120, self.ap + regeneration)
        if before == "chapter" and point[1] < 900:
            self.inputs.append(("tap", point))
            self.phase = "stage"
            if self.on_input:
                self.on_input(len(self.inputs))
            return
        if before == "returned-home":
            self.phase = "home"
        super().dispatch_tap(point)


def recognize_drain(frame, stage, *, world, **kwargs):
    found = recognize(frame, stage, **kwargs)
    phase = PHASES[int(frame[0, 0, 0])]
    observation = found.observation
    if phase in {"home", "returned-home", "chapter", "stage", "wrong-stage"}:
        observation = replace(observation, ap_current=int(frame[2, 2, 0]))
    if phase in {"stage", "wrong-stage"}:
        cost = int(frame[2, 2, 1])
        observation = replace(observation, stage_dialog=stage, ap_cost=cost if phase == "stage" else cost + 1)
    targets = found.targets
    if phase == "chapter":
        observation = replace(observation, selected_tier=stage.tier, chapter_number=stage.chapter,
                              visible_stage_numbers=(stage.stage,))
        targets = (*targets, (f"campaign-stage-{stage.identity}", (179, 407, 221, 449)))
    return replace(found, observation=observation, targets=targets)
