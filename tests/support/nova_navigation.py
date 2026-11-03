"""Shared Nova navigation route fixtures for offline tests."""

from __future__ import annotations

from pathlib import Path

from tasks.runtime_identity import RuntimeIdentityAssurance, VerifiedRuntimeIdentity


ROOT = Path(__file__).resolve().parents[2]
ATLAS_PATH = ROOT / "tasks/assets/home_atlas/bluestacks/800x1280/atlas.json"


def _identity() -> VerifiedRuntimeIdentity:
    return VerifiedRuntimeIdentity(
        "bluestacks-dev-primary",
        "acct-1",
        "server-1",
        "reset-1",
        RuntimeIdentityAssurance.SUPERVISED_NAVIGATION_BINDING,
        ("operator-bound-current-frame",),
    )
