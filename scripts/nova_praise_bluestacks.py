"""Executable, dry-run-by-default BlueStacks route for Nova Praise.

The adapter consumes current native 800x1280 frames and exposes bound commands to a caller.
It does not register a task or enable the production scheduler.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
import time
from typing import Callable

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tasks.nova_praise_runtime import NovaPraiseRuntimeController
from tasks.nova_praise import NOVA_SCREEN, nova_authorizeable
from tasks.nova_praise_vision import NovaFrameRecognition, recognize_nova_frame
from scripts.bluestacks_native_runtime import IntegratedRouteResult, LocalBlueStacksRuntime, NativeRuntimePort


@dataclass(frozen=True)
class NovaAdapterConfig:
    dry_run: bool = True
    frame_max_age_seconds: float = 3.0


class BlueStacksNovaPraiseAdapter:
    """Vision-only adapter; transport is an injected callable and disabled by default."""

    def __init__(self, config: NovaAdapterConfig | None = None, *, transport: Callable[[tuple[int, int]], None] | None = None) -> None:
        self.config = config or NovaAdapterConfig()
        self.transport = transport
        self.controller = NovaPraiseRuntimeController()

    def observe(self, frame, *, captured_monotonic: float | None = None, now: float | None = None) -> NovaFrameRecognition:
        stale = bool(
            now is not None
            and captured_monotonic is not None
            and now - captured_monotonic > self.config.frame_max_age_seconds
        )
        return recognize_nova_frame(frame, captured_monotonic=captured_monotonic, stale=stale)

    def command(self, recognition):
        command = self.controller.next_command(recognition)
        if command.action.value == "PRAISE" and not self.config.dry_run:
            if self.transport is None:
                raise RuntimeError("Nova Praise transport is not configured")
            x0, y0, x1, y1 = command.target_roi or (0, 0, 0, 0)
            self.transport(((x0 + x1) // 2, (y0 + y1) // 2))
        return command


class NovaPraiseIntegratedRoute:
    """Drive Home → Research Lab → Nova → one Praise → verified cooldown → Home."""

    def __init__(
        self,
        runtime: NativeRuntimePort,
        *,
        controller: NovaPraiseRuntimeController | None = None,
        recognizer=recognize_nova_frame,
        post_input_delay: float = 1.0,
        postcondition_timeout: float = 20.0,
    ) -> None:
        self.runtime = runtime
        self.controller = controller or NovaPraiseRuntimeController(now=time.monotonic())
        self.recognizer = recognizer
        self.post_input_delay = post_input_delay
        self.postcondition_timeout = postcondition_timeout

    def _observe(self, label: str):
        captured = self.runtime.capture(label)
        recognition = self.recognizer(
            captured.frame,
            captured_monotonic=captured.captured_monotonic,
            stale=False,
        )
        return captured, recognition

    def _return_home(self, captured, recognition, actions: int) -> IntegratedRouteResult:
        for ordinal in range(1, 4):
            if recognition.observation.screen_state == "HOME_BASE":
                return IntegratedRouteResult("completed", "returned_home", actions, str(self.runtime.session))
            self.runtime.back(captured, action_key=f"nova:return-home:{ordinal}")
            time.sleep(self.post_input_delay)
            captured, recognition = self._observe(f"return-home-post-{ordinal}")
        return IntegratedRouteResult("blocked", "home_postcondition_not_recognized", actions, str(self.runtime.session))

    def reconcile_unresolved_praise(self, *, before_frame: Path, action_key: str) -> IntegratedRouteResult:
        """Reconcile one retained Praise from the current cooldown frame; never Praise again."""

        if not self.runtime.execute:
            return IntegratedRouteResult("dry-run", "resume_transport_disabled", 0, str(self.runtime.session))
        captured, recognition = self._observe("resume-current-source")
        if recognition.observation.screen_state != NOVA_SCREEN or not recognition.observation.recognized:
            return IntegratedRouteResult("unresolved", "current_nova_postcondition_not_recognized", 0, str(self.runtime.session))
        before_frame_data = read_frame(before_frame)
        before = self.recognizer(
            before_frame_data,
            captured_monotonic=max(0.0, captured.captured_monotonic - 1.0),
            stale=False,
        ).observation
        if not nova_authorizeable(before):
            return IntegratedRouteResult("blocked", "retained_nova_source_not_authorized", 0, str(self.runtime.session))
        self.controller.progress.awaiting_postcondition = True
        self.controller.now = captured.captured_monotonic
        self.runtime.in_flight_action = action_key
        if not self.controller.accept_postcondition(before, recognition.observation):
            self.runtime.reconcile(action_key, "unresolved", captured, "retained decrement/cooldown not proven")
            return IntegratedRouteResult("unresolved", "retained_nova_postcondition_not_proven", 0, str(self.runtime.session))
        self.runtime.reconcile(action_key, "confirmed", captured, "retained exact decrement and cooldown verified")
        return self._return_home(captured, recognition, 1)

    def run(self, *, max_steps: int = 20) -> IntegratedRouteResult:
        if not self.runtime.execute:
            _, recognition = self._observe("dry-run-source")
            status = "dry-run" if recognition.observation.recognized else "blocked"
            return IntegratedRouteResult(status, f"transport_disabled:{recognition.observation.screen_state}", 0, str(self.runtime.session))
        actions = 0
        for step in range(1, max_steps + 1):
            captured, recognition = self._observe(f"step-{step:03d}-source")
            self.controller.now = captured.captured_monotonic
            command = self.controller.next_command(recognition)
            if command.action.value in {"OPEN_LAB", "OPEN_NOVA"}:
                target = recognition.target(command.target_identity or "") or command.target_roi
                self.runtime.tap(
                    captured,
                    target_identity=command.target_identity or "",
                    target_roi=target or (0, 0, 0, 0),
                    action_key=f"nova:{command.action.value.casefold()}:{captured.sha256}",
                )
            elif command.action.value == "PRAISE":
                before = recognition.observation
                action_key = f"nova:praise:{captured.sha256}:{before.attempts_remaining}"
                target = recognition.target(command.target_identity or "") or command.target_roi
                self.runtime.tap(
                    captured,
                    target_identity=command.target_identity or "",
                    target_roi=target or (0, 0, 0, 0),
                    action_key=action_key,
                    consequential=True,
                )
                deadline = time.monotonic() + self.postcondition_timeout
                after_capture = None
                after_recognition = None
                while time.monotonic() < deadline:
                    time.sleep(min(0.5, self.post_input_delay))
                    candidate_capture, candidate = self._observe("praise-immediate-post")
                    self.controller.now = candidate_capture.captured_monotonic
                    if self.controller.accept_postcondition(before, candidate.observation):
                        after_capture, after_recognition = candidate_capture, candidate
                        break
                if after_capture is None or after_recognition is None:
                    unresolved = self.runtime.capture("praise-postcondition-unresolved")
                    self.runtime.reconcile(action_key, "unresolved", unresolved, "attempt decrement/cooldown not proven")
                    return IntegratedRouteResult("unresolved", "praise_postcondition_not_proven", actions, str(self.runtime.session))
                self.runtime.reconcile(action_key, "confirmed", after_capture, "attempt decrement and cooldown verified")
                actions += 1
                return self._return_home(after_capture, after_recognition, actions)
            elif command.action.value in {"WAIT_COOLDOWN", "RETURN_HOME"}:
                return self._return_home(captured, recognition, actions)
            else:
                return IntegratedRouteResult("blocked", command.reason or command.action.value, actions, str(self.runtime.session))
            time.sleep(self.post_input_delay)
        return IntegratedRouteResult("blocked", "maximum controller steps exceeded", actions, str(self.runtime.session))


def read_frame(path: Path):
    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f"cannot read BlueStacks frame: {path}")
    return frame


def load_unresolved_praise(session: Path) -> tuple[Path, str]:
    events = [json.loads(line) for line in (session / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    unresolved = next((event for event in reversed(events) if event.get("type") == "reconcile" and event.get("status") == "unresolved"), None)
    if unresolved is None:
        raise RuntimeError("session has no unresolved Nova Praise")
    action_key = str(unresolved["action_key"])
    dispatch = next((event for event in events if event.get("type") == "dispatch" and event.get("action_key") == action_key and event.get("consequential") is True), None)
    if dispatch is None:
        raise RuntimeError("unresolved Nova action has no retained dispatch")
    capture = next((event for event in events if event.get("type") == "capture" and event.get("sha256") == dispatch.get("source_sha256")), None)
    if capture is None:
        raise RuntimeError("unresolved Nova source frame is missing")
    source = Path(str(capture["path"]))
    if not source.is_absolute():
        source = ROOT / source
    return source, action_key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--yes", action="store_true", help="confirm the exact local BlueStacks target non-interactively")
    parser.add_argument("--resume-unresolved-session", type=Path)
    parser.add_argument("--output-directory", type=Path, default=Path(".local-captures/nova-praise-integrated"))
    args = parser.parse_args(argv)
    if args.execute and not args.yes:
        parser.error("--execute requires --yes")
    runtime = LocalBlueStacksRuntime.connect(
        adb=args.adb,
        serial=args.serial,
        output_directory=args.output_directory,
        workflow="nova-praise",
        execute=args.execute,
    )
    route = NovaPraiseIntegratedRoute(runtime)
    if args.resume_unresolved_session is not None:
        before_frame, action_key = load_unresolved_praise(args.resume_unresolved_session)
        result = route.reconcile_unresolved_praise(before_frame=before_frame, action_key=action_key)
    else:
        result = route.run()
    print(json.dumps(result.__dict__, sort_keys=True))
    return 0 if result.status in {"completed", "dry-run"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
