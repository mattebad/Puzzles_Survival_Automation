"""Strict evidence-integrity checks for checked-in flow-delivery wrappers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FlowEvidenceIntegrityError(ValueError):
    pass


REQUIRED_OPERATOR_ARTIFACTS = (
    "events.jsonl",
    "ledger.jsonl",
    "capability-audit.jsonl",
    "journal.jsonl",
)


def _require_nonempty_file(path: Path, *, role: str) -> None:
    if not path.is_file():
        raise FlowEvidenceIntegrityError(f"required {role} is missing: {path.name}")
    if path.stat().st_size <= 0:
        raise FlowEvidenceIntegrityError(f"required {role} is zero-byte: {path.name}")


def require_operator_evidence(
    session: Path,
    *,
    result_name: str = "result.json",
) -> tuple[dict[str, Any], list[str]]:
    """Return parsed result and frame paths only when all operator evidence is substantive."""

    result_path = session / result_name
    _require_nonempty_file(result_path, role="operator result")
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FlowEvidenceIntegrityError("operator result is not valid JSON") from exc
    if not isinstance(result, dict) or not result:
        raise FlowEvidenceIntegrityError("operator result must be a non-empty object")

    for name in REQUIRED_OPERATOR_ARTIFACTS:
        _require_nonempty_file(session / name, role="operator evidence")

    frames_dir = session / "frames"
    frames = sorted(frames_dir.glob("*.png")) if frames_dir.is_dir() else []
    if not frames:
        frames_dir = session / "runtime" / "frames"
    if not frames_dir.is_dir():
        raise FlowEvidenceIntegrityError("required operator frames directory is missing")
    frames = sorted(frames_dir.glob("*.png"))
    if not frames:
        raise FlowEvidenceIntegrityError("required operator frames are missing")
    for frame in frames:
        _require_nonempty_file(frame, role="operator frame")
    return (
        result,
        [str(path.relative_to(session)).replace("\\", "/") for path in frames],
    )
