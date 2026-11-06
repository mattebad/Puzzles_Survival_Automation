"""Scripted Noah's Tavern runtime and observation fixtures."""
from __future__ import annotations

import hashlib
from pathlib import Path
import time
from dataclasses import replace

import numpy as np

from scripts.bluestacks_flow_collector import EXPECTED_PACKAGE
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from tasks.noahs_tavern_recruit import (
    HERO_RECRUIT_RESULT_SCREEN,
    HOME_BASE_SCREEN,
    NOAHS_TAVERN_FREE_TARGET,
    NOAHS_TAVERN_SCREEN,
    NoahTavernObservation,
    NoahTierObservation,
    RecruitTier,
    TIER_ATTEMPT_MAXIMUMS,
    parse_cooldown_seconds,
)


def _tiers() -> tuple[NoahTierObservation, ...]:
    return tuple(
        NoahTierObservation(
            tier=tier,
            daily_attempt_maximum=TIER_ATTEMPT_MAXIMUMS[tier],
            attempts_remaining=None,
        )
        for tier in RecruitTier
    )


def _observation(screen: str, captured_monotonic: float | None) -> NoahTavernObservation:
    if screen == "HOME_BASE":
        return NoahTavernObservation(
            screen_state=HOME_BASE_SCREEN,
            selected_tier=None,
            tiers=_tiers(),
            frame_sha256="a" * 64,
            captured_monotonic=captured_monotonic,
            recognized=True,
            home_tavern_target_roi=(100, 300, 260, 470),
        )
    if screen == "HOME_NO_ROI":
        return NoahTavernObservation(
            screen_state=HOME_BASE_SCREEN,
            selected_tier=None,
            tiers=_tiers(),
            frame_sha256="a" * 64,
            captured_monotonic=captured_monotonic,
            recognized=True,
            home_tavern_target_roi=None,
        )
    if screen == "NOAHS_TAVERN":
        return NoahTavernObservation(
            screen_state=NOAHS_TAVERN_SCREEN,
            selected_tier=RecruitTier.BASIC,
            tiers=_tiers(),
            frame_sha256="b" * 64,
            captured_monotonic=captured_monotonic,
            recognized=True,
            overlay_state="none",
        )
    return NoahTavernObservation(
        screen_state="UNKNOWN",
        selected_tier=None,
        tiers=_tiers(),
        frame_sha256="c" * 64,
        captured_monotonic=captured_monotonic,
        recognized=False,
    )


class ScriptedTavernRuntime:
    """Minimal NativeRuntimePort fake that advances a scripted screen list on each nav input."""

    execute = True
    in_flight_action = None
    session = Path("synthetic-tavern-session")

    def __init__(self, screens: list[str]) -> None:
        self.screens = list(screens)
        self.pos = 0
        self.calls: list[tuple[str, dict]] = []
        self.reconciles: list[tuple[object, ...]] = []
        self._device_state = "device"
        self._foreground_package = EXPECTED_PACKAGE
        self._n = 0

    def measure_device_state(self) -> str:
        return self._device_state

    def measure_foreground_package(self) -> str:
        return self._foreground_package

    def _screen(self) -> str:
        return self.screens[min(self.pos, len(self.screens) - 1)]

    def capture(self, label: str) -> CapturedNativeFrame:
        self._n += 1
        frame = np.zeros((1280, 800, 3), np.uint8)
        frame[0, 0, 0] = self._n % 256
        frame[0, 0, 1] = (self._n // 256) % 256
        payload = f"{self._screen()}:{self._n}".encode()
        return CapturedNativeFrame(
            frame,
            payload,
            hashlib.sha256(frame.tobytes()).hexdigest(),
            time.monotonic(),
            Path(f"{label}.png"),
        )

    def recognizer(self, frame, *, captured_monotonic=None, stale=False):
        return _observation(self._screen(), captured_monotonic)

    def _advance(self) -> None:
        self.pos = min(self.pos + 1, len(self.screens) - 1)

    def tap(self, source, **kwargs) -> None:
        self.calls.append(("tap", dict(kwargs)))
        self._advance()

    def back(self, source, **kwargs) -> None:
        self.calls.append(("back", dict(kwargs)))
        self._advance()

    def reconcile(self, *args, **kwargs) -> None:
        self.reconciles.append(tuple(args))

    def record_recovery(self, **kwargs) -> None:
        return None


class NoahFixtures:
    def tier(self, tier, *, remaining=None, cooldown_text="", cooldown=False, enabled=False, **changes):
        if remaining is None:
            remaining = TIER_ATTEMPT_MAXIMUMS[tier]
        base = NoahTierObservation(
            tier=tier,
            daily_attempt_maximum=TIER_ATTEMPT_MAXIMUMS[tier],
            attempts_remaining=remaining,
            cooldown_text=cooldown_text,
            cooldown_duration_seconds=parse_cooldown_seconds(cooldown_text),
            cooldown_active=cooldown,
            next_eligible_timestamp=130.0 if cooldown else None,
            free_control_visible=enabled,
            free_control_enabled=enabled,
            target_roi=(100, 950, 370, 1040),
            panel_roi=(40, 840, 760, 1070),
            target_identity=NOAHS_TAVERN_FREE_TARGET,
            control_class=NOAHS_TAVERN_FREE_TARGET,
            cost_type="none",
            cost_amount=0,
            quantity=1,
            premium_control_visible=True,
            recognized=True,
            **changes,
        )
        return base

    def tavern(self, selected=RecruitTier.BASIC, *, basic_remaining=5, digest="a" * 64, **changes):
        tiers = {
            RecruitTier.BASIC: self.tier(RecruitTier.BASIC, remaining=basic_remaining, enabled=selected == RecruitTier.BASIC),
            RecruitTier.INT: self.tier(RecruitTier.INT, remaining=1, enabled=selected == RecruitTier.INT),
            RecruitTier.ADV: self.tier(RecruitTier.ADV, remaining=1, enabled=selected == RecruitTier.ADV),
        }
        if selected is not None:
            tiers[selected] = replace(tiers[selected], free_control_visible=True, free_control_enabled=True)
        return NoahTavernObservation(
            screen_state=NOAHS_TAVERN_SCREEN,
            selected_tier=selected,
            tiers=tuple(tiers.values()),
            frame_sha256=digest,
            captured_monotonic=100.0,
            recognized=True,
            **changes,
        )

    def result(self, tier=RecruitTier.BASIC, digest="b" * 64):
        return NoahTavernObservation(
            screen_state=HERO_RECRUIT_RESULT_SCREEN,
            selected_tier=None,
            tiers=tuple(self.tier(item, remaining=None, enabled=False) for item in RecruitTier),
            frame_sha256=digest,
            captured_monotonic=101.0,
            recognized=True,
            result_tier=tier,
            safe_close_visible=True,
            safe_close_roi=(100, 1000, 340, 1070),
            premium_result_control_visible=True,
        )

    def after(self, before, tier=RecruitTier.BASIC, digest="c" * 64, cooldown_text="00:09:52"):
        tiers = list(before.tiers)
        index = next(i for i, item in enumerate(tiers) if item.tier == tier)
        tiers[index] = replace(
            tiers[index],
            attempts_remaining=(before.tier(tier).attempts_remaining - 1),
            cooldown_text=f"Free in {cooldown_text}",
            cooldown_duration_seconds=parse_cooldown_seconds(cooldown_text),
            cooldown_active=True,
            next_eligible_timestamp=130.0,
            free_control_enabled=False,
        )
        return NoahTavernObservation(
            screen_state=NOAHS_TAVERN_SCREEN,
            selected_tier=tier,
            tiers=tuple(tiers),
            frame_sha256=digest,
            captured_monotonic=102.0,
            recognized=True,
        )
