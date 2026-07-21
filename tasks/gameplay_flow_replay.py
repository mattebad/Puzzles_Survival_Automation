"""Zero-transport runtime port over immutable retained native frames."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from scripts.bluestacks_native_runtime import (
    CapturedNativeFrame,
    captured_native_frame_from_png,
)


@dataclass(frozen=True)
class IntendedReplayInput:
    kind: str
    source_frame_sha256: str
    target_identity: str
    action_key: str
    target_roi: tuple[int, int, int, int] | None = None
    start: tuple[int, int] | None = None
    end: tuple[int, int] | None = None
    consequential: bool = False


def load_retained_native_frame(
    path: Path,
    *,
    captured_monotonic: float,
    expected_sha256: str | None = None,
) -> CapturedNativeFrame:
    captured = captured_native_frame_from_png(
        path.read_bytes(),
        captured_monotonic=captured_monotonic,
        path=path,
    )
    if expected_sha256 is not None and captured.sha256 != expected_sha256:
        raise ValueError(f"retained frame digest mismatch: {path}")
    return captured


class ReplayNativeRuntime:
    """NativeRuntimePort implementation that records intent and dispatches nothing."""

    execute = False
    dispatches_transport = False
    in_flight_action = None

    def __init__(
        self,
        session: Path,
        captures: Iterable[CapturedNativeFrame] = (),
    ) -> None:
        self.session = session
        self._captures = list(captures)
        self._capture_index = 0
        self.intended_inputs: list[IntendedReplayInput] = []
        self.transport_calls = 0

    def capture(self, _label: str) -> CapturedNativeFrame:
        if self._capture_index >= len(self._captures):
            raise RuntimeError("replay capture sequence exhausted")
        captured = self._captures[self._capture_index]
        self._capture_index += 1
        return captured

    def tap(
        self,
        source: CapturedNativeFrame,
        *,
        target_identity: str,
        target_roi: tuple[int, int, int, int],
        action_key: str,
        consequential: bool = False,
        continuation_of: str | None = None,
    ) -> None:
        if continuation_of is not None:
            raise RuntimeError("replay cannot continue an operational in-flight action")
        self.intended_inputs.append(
            IntendedReplayInput(
                "tap",
                source.sha256,
                target_identity,
                action_key,
                target_roi=target_roi,
                consequential=consequential,
            )
        )

    def swipe(
        self,
        source: CapturedNativeFrame,
        *,
        start: tuple[int, int],
        end: tuple[int, int],
        action_key: str,
        target_identity: str = "tier-carousel-swipe",
    ) -> None:
        self.intended_inputs.append(
            IntendedReplayInput(
                "swipe",
                source.sha256,
                target_identity,
                action_key,
                start=start,
                end=end,
            )
        )

    def back(
        self,
        source: CapturedNativeFrame,
        *,
        action_key: str,
        continuation_of: str | None = None,
    ) -> None:
        if continuation_of is not None:
            raise RuntimeError("replay cannot continue an operational in-flight action")
        self.intended_inputs.append(
            IntendedReplayInput("back", source.sha256, "android-back", action_key)
        )

    def reconcile(self, *_args, **_kwargs) -> None:
        raise RuntimeError("replay must not reconcile operational action state")

    def record_recovery(self, **_kwargs) -> None:
        raise RuntimeError("replay must not write operational recovery state")
