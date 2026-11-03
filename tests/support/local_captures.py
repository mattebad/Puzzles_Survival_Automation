"""Explicit opt-in for tests that read gitignored, machine-local captures.

``.local-captures/`` is gitignored and empty in CI. Tests that need it are
skipped unless ``PNS_LOCAL_CAPTURES=1`` is set; once opted in, a missing
capture is a failure, never a silent skip.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_CAPTURES = REPO_ROOT / ".local-captures"

requires_local_captures = unittest.skipUnless(
    os.environ.get("PNS_LOCAL_CAPTURES") == "1",
    "opt-in: set PNS_LOCAL_CAPTURES=1 to run tests that read gitignored .local-captures",
)


def require_capture(path: Path | str) -> Path:
    """Return ``path`` as a Path, failing the test if it is missing."""
    resolved = Path(path)
    if not resolved.exists():
        raise AssertionError(f"required local capture is missing: {resolved}")
    return resolved
