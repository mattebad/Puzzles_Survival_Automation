#!/usr/bin/env python3
"""Read-only replay of retained native Ruins route frames.

The utility validates retained 800x1280 PNG captures and classifies list,
challenge-detail, result, and reward surfaces with production recognizers.
Result replay requires an explicit challenge identity; the tool never imports
a live runtime, executes inputs, or writes state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Sequence

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tasks.ruins_challenge import KNOWN_CHALLENGE_IDENTITIES, RuinsResult
from tasks.ruins_challenge_vision import (
    recognize_any_ruins_reward_frame,
    recognize_ruins_detail_with_targets,
    recognize_ruins_frame,
    recognize_ruins_result_with_targets,
)


NATIVE_SIZE = (800, 1280)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Keep this a mutable-at-test-boundary tuple rather than deriving roots from an
# arbitrary command-line path.  A caller may pass ``allowed_roots`` to the
# pure helpers for an isolated retained-root fixture.
RETAINED_ROOTS: tuple[Path, ...] = (ROOT / ".local-captures",)


class ReplayError(ValueError):
    """Input or recognition validation failed before replay could complete."""


def _canonical(path: Path, *, label: str) -> Path:
    try:
        return path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise ReplayError(f"{label} does not exist or cannot be resolved: {path}") from exc


def _inside(path: Path, roots: Sequence[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(_canonical(root, label="retained root"))
        except (ValueError, ReplayError):
            continue
        return True
    return False


def _validate_retained(path: Path, *, label: str, allowed_roots: Sequence[Path]) -> Path:
    canonical = _canonical(path, label=label)
    if not _inside(canonical, allowed_roots):
        roots = ", ".join(str(Path(root)) for root in allowed_roots)
        raise ReplayError(f"{label} is outside allowed retained roots: {path} (roots: {roots})")
    return canonical


def _validate_png(path: Path) -> Path:
    if not path.is_file():
        raise ReplayError(f"frame path is not a file: {path}")
    if path.suffix.lower() != ".png":
        raise ReplayError(f"unsupported frame extension (PNG required): {path}")
    payload = path.read_bytes()
    if not payload.startswith(PNG_SIGNATURE):
        raise ReplayError(f"frame is not a PNG image: {path}")
    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ReplayError(f"frame is not a decodable PNG image: {path}")
    height, width = image.shape[:2]
    if (width, height) != NATIVE_SIZE:
        raise ReplayError(
            f"frame must be native 800x1280 (got {width}x{height}): {path}"
        )
    return path


def resolve_frame_paths(
    frame_paths: Iterable[Path] = (),
    *,
    frames_dir: Path | None = None,
    allowed_roots: Sequence[Path] | None = None,
) -> tuple[Path, ...]:
    """Validate and deterministically resolve explicit frame input.

    ``frame_paths`` preserves the caller's explicit order.  A directory is
    enumerated directly (never recursively) in case-insensitive filename order
    with a case-sensitive tie-breaker.  Exactly one source mode is required.
    """

    roots = tuple(allowed_roots) if allowed_roots is not None else RETAINED_ROOTS
    explicit = tuple(Path(item) for item in frame_paths)
    if explicit and frames_dir is not None:
        raise ReplayError("provide explicit PNG paths or --frames-dir, not both")
    if not explicit and frames_dir is None:
        raise ReplayError("no frames supplied; provide PNG paths or --frames-dir")

    if frames_dir is not None:
        directory = _validate_retained(frames_dir, label="frames directory", allowed_roots=roots)
        if not directory.is_dir():
            raise ReplayError(f"frames directory is not a directory: {frames_dir}")
        children = sorted(
            (
                _validate_retained(item, label="frame path", allowed_roots=roots)
                for item in directory.iterdir()
                if item.is_file()
            ),
            key=lambda item: (item.name.casefold(), item.name),
        )
        if not children:
            raise ReplayError(f"frames directory is empty: {frames_dir}")
        unsupported = [item for item in children if item.suffix.lower() != ".png"]
        if unsupported:
            raise ReplayError(f"unsupported extension in frames directory: {unsupported[0]}")
        paths = tuple(children)
    else:
        paths = tuple(
            _validate_retained(item, label="frame path", allowed_roots=roots)
            for item in explicit
        )
        if not paths:
            raise ReplayError("no frames supplied")

    seen: set[Path] = set()
    validated: list[Path] = []
    for path in paths:
        if path in seen:
            raise ReplayError(f"duplicate frame path: {path}")
        seen.add(path)
        validated.append(_validate_png(path))
    return tuple(validated)


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _roi(value: Any) -> list[int] | None:
    if value is None:
        return None
    return [int(item) for item in value]


def _row_payload(row: Any) -> dict[str, Any]:
    return {
        "identity": row.identity,
        "day": row.day_label,
        "availability": _enum_value(row.availability),
        "progress": [int(row.progress_current), int(row.progress_maximum)],
        "challenge_control": _enum_value(row.challenge_control),
        "chest_state": _enum_value(row.chest_state),
        "target_roi": _roi(row.target_roi),
    }


def recognize_ruins_surface(
    frame: np.ndarray,
    *,
    reset_identity: str | None = None,
    challenge_identity: str | None = None,
) -> tuple[str, Any, tuple[tuple[str, Any], ...]]:
    """Classify one retained frame without authorizing route actions."""

    list_recognition = recognize_ruins_frame(frame, reset_identity=reset_identity)
    if list_recognition.observation.recognized and list_recognition.observation.screen_identity == "RUINS_CHALLENGE":
        return "RUINS_CHALLENGE", list_recognition.observation, list_recognition.targets

    if challenge_identity is not None:
        result = recognize_ruins_result_with_targets(
            frame, challenge_identity, reset_identity=reset_identity,
        )
        if result.observation.result in {RuinsResult.SUCCESS, RuinsResult.FAILURE}:
            return "RUINS_CHALLENGE_RESULT", result.observation, result.targets

    for identity in KNOWN_CHALLENGE_IDENTITIES:
        detail = recognize_ruins_detail_with_targets(
            frame, identity, reset_identity=reset_identity,
        )
        if detail.observation.recognized:
            return "RUINS_CHALLENGE_DETAIL", detail.observation, detail.targets

    reward = recognize_any_ruins_reward_frame(frame, reset_identity=reset_identity)
    if reward.recognized:
        return "RUINS_REWARD_MODAL", reward, reward.targets
    return "UNKNOWN", list_recognition.observation, list_recognition.targets


def _recognition_payload(
    path: Path,
    order: int,
    payload: bytes,
    surface: str,
    observation: Any,
    targets: Sequence[tuple[str, Any]],
) -> dict[str, Any]:
    result = {
        "order": order,
        "path": _display_path(path),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "recognized": bool(getattr(observation, "recognized", surface != "UNKNOWN")),
        "surface": surface,
        "screen_identity": getattr(observation, "screen_identity", surface),
        "rows": [_row_payload(row) for row in getattr(observation, "rows", ())],
        "targets": [
            {"identity": identity, "roi": _roi(roi)}
            for identity, roi in targets
        ],
    }
    for field in (
        "identity",
        "result",
        "floor_current",
        "floor_maximum",
        "attack_control",
        "dispatch_control",
        "npc_troops_provided",
        "npc_troops_current",
        "npc_troops_maximum",
        "skip_battle_enabled",
        "medal_amount",
        "reset_identity",
    ):
        value = getattr(observation, field, None)
        if value is not None:
            result[field] = _enum_value(value)
    return result

def _display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def replay_frames(
    frame_paths: Iterable[Path] = (),
    *,
    frames_dir: Path | None = None,
    reset_identity: str | None = None,
    challenge_identity: str | None = None,
    allowed_roots: Sequence[Path] | None = None,
) -> dict[str, Any]:
    """Replay validated retained frames and return a compact JSON-ready object."""

    if challenge_identity is not None and challenge_identity not in KNOWN_CHALLENGE_IDENTITIES:
        raise ReplayError("challenge identity is not a canonical Ruins category")
    paths = resolve_frame_paths(frame_paths, frames_dir=frames_dir, allowed_roots=allowed_roots)
    frames: list[dict[str, Any]] = []
    for order, path in enumerate(paths, start=1):
        payload = path.read_bytes()
        if not payload.startswith(PNG_SIGNATURE):
            raise ReplayError(f"frame changed or is not a PNG image: {path}")
        image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        # resolve_frame_paths already checked this shape; retain the check here
        # so a file replaced between validation and read cannot reach OCR.
        if image is None or image.shape[:2] != (NATIVE_SIZE[1], NATIVE_SIZE[0]):
            raise ReplayError(f"frame changed or is not native 800x1280: {path}")
        surface, observation, targets = recognize_ruins_surface(
            image,
            reset_identity=reset_identity,
            challenge_identity=challenge_identity,
        )
        frames.append(_recognition_payload(path, order, payload, surface, observation, targets))
    return {"frame_count": len(frames), "frames": frames}


def serialize_replay(payload: dict[str, Any]) -> str:
    """Serialize replay output without whitespace or nondeterministic fields."""

    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frames", nargs="*", type=Path, help="explicit retained PNG frame path(s)")
    parser.add_argument("--frames-dir", type=Path, help="explicit retained directory containing PNG frames")
    parser.add_argument(
        "--challenge-identity",
        choices=KNOWN_CHALLENGE_IDENTITIES,
        help="identity bound to retained challenge result frames",
    )
    parser.add_argument("--reset-identity", help="reset identity to bind to retained frames")
    args = parser.parse_args(argv)
    try:
        payload = replay_frames(
            args.frames,
            frames_dir=args.frames_dir,
            reset_identity=args.reset_identity,
            challenge_identity=args.challenge_identity,
        )
    except ReplayError as exc:
        parser.error(str(exc))
    print(serialize_replay(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
