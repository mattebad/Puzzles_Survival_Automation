"""Shared Home Atlas fixtures for offline tests."""

from __future__ import annotations

from safe_action_core import CentralPolicy
from scripts import home_atlas_bluestacks as home
from tasks.home_atlas import AmbiguityState, LocalizationResult, SemanticBuilding, ZoomIdentity
from tasks.home_atlas_vision import BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID
from tasks.home_context import HomeReadyObservation
from tasks.runtime_identity import RuntimeIdentityAssurance, VerifiedRuntimeIdentity


def building(*, semantic_id: str = "home.building.bank", polygon=((900, 700), (1040, 700), (1040, 840), (900, 840)), eligible: bool = True) -> SemanticBuilding:
    return SemanticBuilding(
        semantic_id,
        "Bank",
        polygon,
        0.98,
        ("v1",),
        recognition={"bluestacks": {"label": "Bank"}},
        semantic_proof=("visible Bank label",),
        interaction_eligible=eligible,
        platform_binding_policy={"bluestacks": {"label": "Bank"}},
    )


def localization(x: float = 0, y: float = 0, digest: str = "a" * 64) -> LocalizationResult:
    return LocalizationResult(True, BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, ZoomIdentity.FULLY_ZOOMED_OUT, ((1, 0, x), (0, 1, y), (0, 0, 1)), ((x, y), (x + 800, y), (x + 800, y + 1280), (x, y + 1280)), 0.95, ("v1",), 0.4, AmbiguityState.NONE, "interior", digest, "now")


def _ready() -> HomeReadyObservation:
    return HomeReadyObservation(
        True,
        True,
        VerifiedRuntimeIdentity(
            "test-runtime",
            "acct-1",
            "server-1",
            "reset-1",
            RuntimeIdentityAssurance.SUPERVISED_NAVIGATION_BINDING,
            ("test-identity",),
        ),
        False,
        False,
    )


class _RecordingPolicy(CentralPolicy):
    """Record evaluated evidence while retaining the real policy and capability checks."""

    def __init__(self) -> None:
        super().__init__(supervised_tasks={home.SUPPLY_DEPOT_ROUTE_TASK_ID})
        self.requests = []

    def evaluate(self, request):
        self.requests.append(request)
        return super().evaluate(request)
