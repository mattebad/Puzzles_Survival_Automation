"""Shared fixtures for the ultimate-challenge test modules."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from scripts import flow_delivery_ultimate_challenge_bluestacks as delivery
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from tasks.runtime_identity import BLUESTACKS_SERIAL


RESET = "game-day-2026-10-29"


def write_result(session, result, events):
    session.mkdir(parents=True, exist_ok=True)
    (session / "frames").mkdir(exist_ok=True)
    (session / "runtime").mkdir(exist_ok=True)
    (session / "result.json").write_text(json.dumps(result), encoding="utf-8")
    (session / "events.jsonl").write_text('{"type":"route"}\n', encoding="utf-8")
    (session / "runtime/events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in events), encoding="utf-8")
    for name in ("ledger.jsonl", "journal.jsonl", "capability-audit.jsonl"):
        (session / name).write_text('{"status":"retained"}\n', encoding="utf-8")


def flee_proof(session):
    session.mkdir(parents=True, exist_ok=True)
    frames = session / "frames"
    frames.mkdir(exist_ok=True)
    captures = []
    for name, shade in (("before", 50), ("after", 80)):
        path = frames / f"{name}.png"
        cv2.imwrite(str(path), np.full((1280, 800, 3), shade, dtype=np.uint8))
        captures.append({"type": "capture", "path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    before, after = [row["sha256"] for row in captures]
    result = {
        "flow_id": delivery.FLOW_ID, "reset_identity": RESET,
        "terminal": "blocked_fail_closed", "input_count": 1,
        "completed_actions": [{"action": "tap_flee", "before_sha256": before, "post_sha256": after}],
    }
    events = captures + [
        {"type": "dispatch", "target_identity": "tap_flee", "execute": True, "source_sha256": before, "action_key": "flee-one"},
        {"type": "reconcile", "action_key": "flee-one", "status": "confirmed", "post_sha256": after},
    ]
    write_result(session, result, events)
    wrapper = {"flow_id": delivery.FLOW_ID, "serial": BLUESTACKS_SERIAL,
               "native_width": 800, "native_height": 1280, "ultimate_challenge_result": result}
    (session / "flow-delivery-result.json").write_text(json.dumps(wrapper), encoding="utf-8")
    return result


def captured_native_frame(
    root: Path,
    frame: np.ndarray,
    label: str,
    ordinal: int,
) -> CapturedNativeFrame:
    encoded_ok, encoded = cv2.imencode(".png", frame)
    assert encoded_ok
    payload = encoded.tobytes()
    path = root / f"{ordinal:04d}-{label}.png"
    path.write_bytes(payload)
    return CapturedNativeFrame(
        frame=frame.copy(),
        png=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
        captured_monotonic=float(ordinal),
        path=path,
    )


class CampaignExitRuntime:
    def __init__(
        self,
        root: Path,
        frames: list[np.ndarray],
    ) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.frames = list(frames)
        self.captures: list[CapturedNativeFrame] = []
        self.taps: list[dict[str, object]] = []
        self.backs: list[dict[str, object]] = []
        self.reconciliations: list[
            tuple[str, str, CapturedNativeFrame, str]
        ] = []
        self.action_keys: set[str] = set()
        self.input_count = 0
        self.runner = SimpleNamespace()

    def capture(self, label: str) -> CapturedNativeFrame:
        frame = self.frames.pop(0) if self.frames else self.captures[-1].frame
        captured = captured_native_frame(
            self.root,
            frame,
            label,
            len(self.captures) + 1,
        )
        self.captures.append(captured)
        return captured

    def tap(self, source: CapturedNativeFrame, **kwargs) -> None:
        self.taps.append({"source": source, **kwargs})
        self.action_keys.add(str(kwargs["action_key"]))
        self.input_count += 1

    def back(self, source: CapturedNativeFrame, **kwargs) -> None:
        self.backs.append({"source": source, **kwargs})
        self.action_keys.add(str(kwargs["action_key"]))
        self.input_count += 1

    def reconcile(
        self,
        action_key: str,
        status: str,
        post: CapturedNativeFrame,
        reason: str,
    ) -> None:
        self.reconciliations.append((action_key, status, post, reason))
