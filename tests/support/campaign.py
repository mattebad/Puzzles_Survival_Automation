"""Shared campaign fixtures for offline tests."""

from __future__ import annotations

from tasks.campaign_auto_battle import CampaignRouteObservation
from tasks.campaign_auto_battle_vision import CampaignFrameRecognition


def recognized(
    observation: CampaignRouteObservation,
    *targets: tuple[str, tuple[int, int, int, int]],
    frame_hash: str = "frame",
) -> CampaignFrameRecognition:
    return CampaignFrameRecognition(observation, frame_hash, targets, {})
