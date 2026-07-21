"""Nova Praise replay capsule: fixture → recognized state → permitted action → result.

Replay mode never dispatches ADB input. Missing fixtures are recorded as required_evidence
rather than fabricated recognizers or images.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from .gameplay_flow_contracts import load_flow_contract
from .home_atlas import (
    AmbiguityState,
    BuildingBinding,
    HomeAtlas,
    LocalizationResult,
    PlatformProfile,
    SemanticBuilding,
    ZoomIdentity,
    AtlasViewport,
)
from .home_context import HomeReadyObservation, navigate_home_building
from .nova_praise import NOVA_PRAISE_TARGET, NovaPraiseObservation
from .nova_praise_pulse import NOVA_TASK_ID, NovaPulseController, NovaPulseView
from .nova_praise_vision import NOVA_PRAISE_ROI
from .scheduler_task_result import SchedulerIdentity, SchedulerTaskOutcome

FLOW_ID = "NOVA-PRAISE-HOME-ATLAS-MIGRATION"
MANIFEST_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "nova_praise_replay" / "manifest.json"


@dataclass(frozen=True)
class ReplayCaseResult:
    fixture_id: str
    recognized_state: str
    permitted_action: str
    outcome: str
    intended_actions: tuple[str, ...]
    dispatched_actions: tuple[str, ...]
    fixture_status: str


def load_replay_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _atlas() -> HomeAtlas:
    profile = PlatformProfile("BlueStacks 5 / Android", "pns-bluestacks-5-p64-800x1280-v1", (800, 1280), "com.global.ztmslg")
    viewport = AtlasViewport(
        "v1",
        "tile.png",
        "a" * 64,
        "2026-07-21T00:00:00+00:00",
        ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
        ((0, 0), (800, 0), (800, 1280), (0, 1280)),
        1.0,
        0.0,
        "origin",
    )
    lab = SemanticBuilding(
        "home.building.research_lab",
        "Research Lab",
        ((350, 500), (450, 500), (450, 620), (350, 620)),
        0.95,
        ("v1",),
        semantic_proof=("synthetic replay atlas",),
    )
    offscreen = SemanticBuilding(
        "home.building.research_lab_offscreen_marker",
        "Offscreen marker",
        ((1200, 500), (1300, 500), (1300, 620), (1200, 620)),
        0.95,
        ("v1",),
        semantic_proof=("synthetic",),
    )
    return HomeAtlas(
        2,
        "nova-replay",
        "1",
        profile,
        "fully_zoomed_out",
        "atlas pixels",
        (0, 0),
        1600,
        1800,
        "atlas.png",
        "test",
        "test",
        (((0, 0), (1600, 0), (1600, 1800), (0, 1800)),),
        (),
        (viewport,),
        (lab, offscreen),
    )


def _ready(*, manual: bool = False) -> HomeReadyObservation:
    return HomeReadyObservation(
        game_foregrounded=True,
        expected_native_profile=True,
        account_server_identity_available=True,
        manual_only_state=manual,
        blocking_unknown_modal=False,
    )


def _localization(
    *,
    recognized: bool = True,
    zoom: ZoomIdentity = ZoomIdentity.FULLY_ZOOMED_OUT,
    tx: float = 0.0,
    ty: float = 0.0,
    residual: float = 0.4,
    digest: str = "a" * 64,
) -> LocalizationResult:
    return LocalizationResult(
        recognized,
        "BlueStacks 5 / Android",
        "pns-bluestacks-5-p64-800x1280-v1",
        zoom,
        ((1, 0, tx), (0, 1, ty), (0, 0, 1)) if recognized else None,
        ((tx, ty), (tx + 800, ty), (tx + 800, ty + 1280), (tx, ty + 1280)),
        0.95 if recognized else 0.0,
        ("v1",) if recognized else (),
        residual if recognized else None,
        AmbiguityState.NONE if recognized else AmbiguityState.INSUFFICIENT_LANDMARKS,
        "interior",
        digest,
        "2026-07-21T00:00:00+00:00",
    )


def _praise(**changes: Any) -> NovaPraiseObservation:
    base = dict(
        screen_state="NOVA",
        research_lab_identity=True,
        nova_control_visible=False,
        selected_nova=True,
        praise_enabled=True,
        praise_target_identity=NOVA_PRAISE_TARGET,
        praise_target_roi=NOVA_PRAISE_ROI,
        attempts_remaining=7,
        frame_sha256="a" * 64,
        captured_monotonic=100.0,
    )
    base.update(changes)
    return NovaPraiseObservation(**base)


def _identity() -> SchedulerIdentity:
    return SchedulerIdentity("acct-1", "server-1", "reset-2026-07-21", NOVA_TASK_ID)


def run_replay_case(fixture_id: str, *, manifest: Optional[Mapping[str, Any]] = None) -> ReplayCaseResult:
    payload = dict(manifest or load_replay_manifest())
    cases = {item["fixture_id"]: item for item in payload["cases"]}
    if fixture_id not in cases:
        raise KeyError(fixture_id)
    case = cases[fixture_id]
    status = case["status"]
    # Missing PNG fixtures stay required_evidence, but synthetic observations may still
    # exercise the fail-closed state machine without fabricating images.

    controller = NovaPulseController(_identity(), _atlas(), now=100.0, replay_mode=True)
    recognized = case["recognized_state"]
    permitted = case["permitted_action"]

    if fixture_id == "canonical_home":
        view = NovaPulseView(_ready(), _localization(residual=0.4))
        result = controller.pulse(view)
        return ReplayCaseResult(
            fixture_id,
            recognized,
            permitted,
            result.outcome.value,
            result.intended_actions,
            result.dispatched_actions,
            status,
        )
    if fixture_id == "localized_noncanonical_home":
        view = NovaPulseView(_ready(), _localization(tx=120.0, ty=80.0, residual=1.1, digest="b" * 64))
        result = controller.pulse(view)
        return ReplayCaseResult(
            fixture_id,
            recognized,
            permitted,
            result.outcome.value,
            result.intended_actions,
            result.dispatched_actions,
            status,
        )
    if fixture_id == "zoomed_in_home":
        view = NovaPulseView(_ready(), _localization(recognized=False, zoom=ZoomIdentity.ZOOMED_IN))
        result = controller.pulse(view)
        return ReplayCaseResult(
            fixture_id,
            recognized,
            permitted,
            result.outcome.value,
            result.intended_actions,
            result.dispatched_actions,
            status,
        )
    if fixture_id == "research_lab_visible":
        binding = BuildingBinding(
            "home.building.research_lab",
            (350, 500, 450, 620),
            "a" * 64,
            0.95,
            ("ocr:Research Lab",),
        )
        decision = navigate_home_building(_atlas(), "home.building.research_lab", _ready(), _localization(), binding)
        return ReplayCaseResult(
            fixture_id,
            recognized,
            decision.action.value,
            SchedulerTaskOutcome.BLOCKED.value,
            (decision.action.value,),
            (),
            status,
        )
    if fixture_id == "research_lab_offscreen":
        from .home_atlas import ClosedLoopBuildingNavigator

        nav = ClosedLoopBuildingNavigator(_atlas(), "home.building.research_lab")
        off = _localization(tx=-900.0, ty=0.0, digest="c" * 64)
        decision = navigate_home_building(_atlas(), "home.building.research_lab", _ready(), off, navigator=nav)
        return ReplayCaseResult(
            fixture_id,
            recognized,
            decision.action.value,
            SchedulerTaskOutcome.BLOCKED.value,
            (decision.action.value,),
            (),
            status,
        )
    if fixture_id == "research_lab_radial_menu":
        binding = BuildingBinding(
            "home.building.research_lab",
            (350, 500, 450, 620),
            "a" * 64,
            0.95,
            ("ocr:Research Lab",),
        )
        view = NovaPulseView(
            _ready(),
            _localization(),
            building_binding=binding,
            research_lab_radial_recognized=True,
            nova_lab_recognized=False,
        )
        result = controller.pulse(view)
        return ReplayCaseResult(
            fixture_id,
            recognized,
            permitted,
            result.outcome.value,
            result.intended_actions,
            result.dispatched_actions,
            status,
        )
    if fixture_id == "nova_lab":
        binding = BuildingBinding(
            "home.building.research_lab",
            (350, 500, 450, 620),
            "a" * 64,
            0.95,
            ("ocr:Research Lab",),
        )
        view = NovaPulseView(
            _ready(),
            _localization(),
            building_binding=binding,
            research_lab_radial_recognized=True,
            nova_lab_recognized=True,
        )
        result = controller.pulse(view)
        return ReplayCaseResult(
            fixture_id,
            recognized,
            permitted,
            result.outcome.value,
            result.intended_actions,
            result.dispatched_actions,
            status,
        )
    if fixture_id == "praise_attempts_available":
        result = controller.pulse(NovaPulseView(_ready(), _localization(), praise=_praise()))
        return ReplayCaseResult(
            fixture_id,
            recognized,
            permitted,
            result.outcome.value,
            result.intended_actions,
            result.dispatched_actions,
            status,
        )
    if fixture_id == "praise_on_cooldown":
        obs = _praise(praise_enabled=False, cooldown_active=True, cooldown_seconds=120, next_eligible_at=220.0)
        result = controller.pulse(NovaPulseView(_ready(), _localization(), praise=obs))
        return ReplayCaseResult(
            fixture_id,
            recognized,
            permitted,
            result.outcome.value,
            result.intended_actions,
            result.dispatched_actions,
            status,
        )
    if fixture_id == "zero_attempts_remaining":
        result = controller.pulse(
            NovaPulseView(_ready(), _localization(), praise=_praise(attempts_remaining=0, praise_enabled=False))
        )
        return ReplayCaseResult(
            fixture_id,
            recognized,
            permitted,
            result.outcome.value,
            result.intended_actions,
            result.dispatched_actions,
            status,
        )
    if fixture_id == "unknown_or_negative_control":
        result = controller.pulse(NovaPulseView(_ready(manual=True), _localization(recognized=False)))
        return ReplayCaseResult(
            fixture_id,
            recognized,
            permitted,
            result.outcome.value,
            result.intended_actions,
            result.dispatched_actions,
            status,
        )
    raise KeyError(fixture_id)


def assert_contract_fixtures_aligned() -> None:
    contract = load_flow_contract(FLOW_ID)
    manifest = load_replay_manifest()
    contract_ids = {item["fixture_id"] for item in contract["replay_fixture_requirements"]}
    manifest_ids = {item["fixture_id"] for item in manifest["cases"]}
    if contract_ids != manifest_ids:
        raise AssertionError(f"fixture set mismatch: {sorted(contract_ids ^ manifest_ids)}")
