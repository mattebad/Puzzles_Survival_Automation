"""Startup-recovery fixtures: reset-popup recognition detail and Scarlett recognition detail."""
from __future__ import annotations

from scripts.bluestacks_native_runtime import NATIVE_RUNTIME_PROFILE_ID
from scripts.startup_surface_recognition import (
    SCARLETT_EXPECTED_SUCCESSOR,
    SCARLETT_FORBIDDEN_PURCHASE_ROIS,
    SCARLETT_FRAME_SHA256,
    SCARLETT_MAX_INPUTS,
    SCARLETT_SAFE_BACK_ROI,
    SCARLETT_SAFE_BACK_TARGET_IDENTITY,
    SCARLETT_THREE_DAY_PACK,
)


TARGET = (263, 781, 537, 869)


def popup(
    *,
    target=TARGET,
    popup_identity: str = "VIP_POINTS_GET_PTS",
    target_identity: str = "reset-popup-close",
) -> dict[str, object]:
    return {
        "recognized": True,
        "popup_identity": popup_identity,
        "target_identity": target_identity,
        "target": target,
        "target_center": (400, 825),
    }


def scarlett_detail() -> dict[str, object]:
    return {
        "recognized": True,
        "surface_identity": SCARLETT_THREE_DAY_PACK,
        "surface_kind": "full_page",
        "runtime_profile_id": NATIVE_RUNTIME_PROFILE_ID,
        "width": 800,
        "height": 1280,
        "frame_sha256": SCARLETT_FRAME_SHA256,
        "title_text": "scarlett 3-day pack",
        "title_identity": True,
        "semantic_evidence": (
            "title:Scarlett 3-Day Pack",
            "full_page_real_money_promotion",
            "visible_in_game_back_upper_left",
            "purchase_regions_excluded",
            "current_offer_benefits_and_three_day_rows",
            "current_first_topup_notice",
        ),
        "safe_exit_target_identity": SCARLETT_SAFE_BACK_TARGET_IDENTITY,
        "safe_exit_roi": SCARLETT_SAFE_BACK_ROI,
        "forbidden_purchase_rois": SCARLETT_FORBIDDEN_PURCHASE_ROIS,
        "purchase_exclusion_verified": True,
        "critical_roi_hashes": (("title", "a" * 64),),
        "page_context_verified": True,
        "measured_back_roi": (47, 0, 128, 59),
        "expected_successor": SCARLETT_EXPECTED_SUCCESSOR,
        "max_inputs": SCARLETT_MAX_INPUTS,
        "target_count": 1,
    }
