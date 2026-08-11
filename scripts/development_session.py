"""Lean, flow-agnostic runtime session for ordinary gameplay development.

The session owns singleton runtime access, compact action accounting, native-frame
validation, bounded input, and terminal summarization.  It deliberately has no
per-action lease, journal lifecycle, unresolved-action gate, queue, or handoff
dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

from scripts.bluestacks_native_runtime import CapturedNativeFrame, NATIVE_HEIGHT, NATIVE_WIDTH
from scripts.navigation_development_boundary import NavigationDevelopmentSession


ORDINARY_DEVELOPMENT_ACTIONS = frozenset(
    {
        "navigation",
        "combat",
        "claim",
        "reward",
        "recruitment",
        "resource_collection",
        "in_game_currency",
        "maintenance",
        "recovery",
    }
)
REAL_MONEY_CASH_MALL_CONFIRMATION = "real_money_cash_mall_confirmation"


class DevelopmentSessionError(RuntimeError):
    """A bounded development-session safeguard rejected an operation."""


def validate_development_action(action_class: str) -> str:
    normalized = str(action_class).strip().lower()
    if normalized == REAL_MONEY_CASH_MALL_CONFIRMATION:
        raise DevelopmentSessionError("real-money Cash Mall confirmation is unsupported")
    if normalized not in ORDINARY_DEVELOPMENT_ACTIONS:
        raise DevelopmentSessionError(f"unknown development action class: {action_class}")
    return normalized


def _validate_native_frame(frame: CapturedNativeFrame) -> None:
    height = int(frame.frame.shape[0])
    width = int(frame.frame.shape[1])
    if (width, height) != (NATIVE_WIDTH, NATIVE_HEIGHT):
        raise DevelopmentSessionError("development input requires a native 800x1280 frame")


def _validate_roi(roi: tuple[int, int, int, int] | None) -> None:
    if roi is None:
        return
    x0, y0, x1, y1 = roi
    if not (0 <= x0 < x1 <= NATIVE_WIDTH and 0 <= y0 < y1 <= NATIVE_HEIGHT):
        raise DevelopmentSessionError("development target is outside native-frame bounds")


@dataclass(frozen=True)
class DevelopmentActionResult:
    status: str
    reason: str
    state: str
    before_sha256: str
    after_sha256: str
    recovery_used: bool = False


class DevelopmentSession:
    """Run multiple ordinary interactions under one automatically released lock."""

    def __init__(
        self,
        *,
        owner: str,
        invocation_id: str,
        session_directory: Path,
        max_inputs: int = 12,
    ) -> None:
        if not 1 <= int(max_inputs) <= 100:
            raise DevelopmentSessionError("max_inputs must be between 1 and 100")
        self.owner = owner
        self.invocation_id = invocation_id
        self.session_directory = Path(session_directory)
        self.max_inputs = int(max_inputs)
        self.input_count = 0
        self.actions: list[dict[str, Any]] = []
        self.terminal_status: str | None = None
        self.blocker: str | None = None
        self.next_action: str | None = None
        self._ownership = NavigationDevelopmentSession(owner=owner, invocation_id=invocation_id)
        self._entered = False

    def __enter__(self) -> "DevelopmentSession":
        self._ownership.__enter__()
        try:
            self.session_directory.mkdir(parents=True, exist_ok=False)
        except Exception:
            self._ownership.__exit__(None, None, None)
            raise
        self._entered = True
        return self

    def observe(self, capture: Callable[[str], CapturedNativeFrame], *, label: str) -> CapturedNativeFrame:
        if not self._entered:
            raise DevelopmentSessionError("development session is not active")
        frame = capture(label)
        _validate_native_frame(frame)
        return frame

    def run_action(
        self,
        *,
        action_class: str,
        label: str,
        capture: Callable[[str], CapturedNativeFrame],
        dispatch: Callable[[CapturedNativeFrame], None],
        recognize: Callable[[CapturedNativeFrame], str],
        target_roi: tuple[int, int, int, int] | None = None,
        recover: Callable[[CapturedNativeFrame], bool | int] | None = None,
    ) -> DevelopmentActionResult:
        normalized = validate_development_action(action_class)
        if self.input_count >= self.max_inputs:
            raise DevelopmentSessionError("development session input limit reached")
        _validate_roi(target_roi)
        before = self.observe(capture, label=f"{label}-immediate-before")
        self.input_count += 1
        dispatch(before)
        after = self.observe(capture, label=f"{label}-immediate-post")
        state = str(recognize(after) or "unknown")
        recovery_used = False
        if state.lower() == "unknown" and recover is not None:
            if self.input_count >= self.max_inputs:
                raise DevelopmentSessionError("development session input limit reached before recovery")
            recovery_result = recover(after)
            recovery_inputs = (
                1 if recovery_result is True else 0 if recovery_result is False else int(recovery_result)
            )
            if recovery_inputs not in {0, 1}:
                raise DevelopmentSessionError("recovery must report zero or one bounded input")
            self.input_count += recovery_inputs
            recovery_used = recovery_inputs == 1
            if recovery_used:
                after = self.observe(capture, label=f"{label}-recovery-post")
                state = str(recognize(after) or "unknown")
        status = "completed" if state.lower() != "unknown" else "unknown"
        reason = "recognized_successor" if status == "completed" else "unknown_successor"
        row = {
            "ordinal": len(self.actions) + 1,
            "action_class": normalized,
            "label": label,
            "status": status,
            "reason": reason,
            "state": state,
            "before_sha256": before.sha256,
            "after_sha256": after.sha256,
            "recovery_used": recovery_used,
        }
        self.actions.append(row)
        with (self.session_directory / "actions.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        return DevelopmentActionResult(
            status=status,
            reason=reason,
            state=state,
            before_sha256=before.sha256,
            after_sha256=after.sha256,
            recovery_used=recovery_used,
        )

    def _write_summary(self, exception: BaseException | None) -> None:
        unknown = next(
            (row for row in reversed(self.actions) if row.get("status") == "unknown"),
            None,
        )
        terminal_status = self.terminal_status or ("blocked" if unknown else "completed")
        summary: dict[str, Any] = {
            "schema_version": 1,
            "session_kind": "ordinary_development",
            "owner": self.owner,
            "invocation_id": self.invocation_id,
            "status": "failed" if exception else terminal_status,
            "input_count": self.input_count,
            "max_inputs": self.max_inputs,
            "action_count": len(self.actions),
            "ownership_released": True,
            "lifecycle_state_created": False,
            "terminal_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if unknown:
            summary["blocker"] = unknown["reason"]
            summary["next_action"] = "repair recognition or recovery and rerun materially changed behavior"
        if self.blocker:
            summary["blocker"] = self.blocker
        if self.next_action:
            summary["next_action"] = self.next_action
        if exception:
            summary["blocker"] = f"{type(exception).__name__}: {exception}"
            summary["next_action"] = "repair the reported development failure"
        (self.session_directory / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self._ownership.__exit__(exc_type, exc, tb)
        finally:
            self._write_summary(exc)
            self._entered = False
