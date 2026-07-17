"""Executable, dry-run-by-default native BlueStacks route for Noah's Tavern recruits.

The adapter is deliberately unregistered and has no Claim or scheduler path.  A caller supplies
the frame capture and transport functions; transport is enabled only by an explicit config.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import json
from pathlib import Path
import sys
import time
from typing import Callable

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tasks.noahs_tavern_recruit_runtime import NoahAction, NoahTavernRecruitRuntimeController
from tasks.noahs_tavern_recruit import HERO_RECRUIT_RESULT_SCREEN, NOAHS_TAVERN_SCREEN, RecruitTier
from tasks.noahs_tavern_recruit_vision import recognize_noahs_tavern_frame
from scripts.bluestacks_native_runtime import IntegratedRouteResult, LocalBlueStacksRuntime, NativeRuntimePort


@dataclass(frozen=True)
class NoahAdapterConfig:
    dry_run: bool = True
    frame_max_age_seconds: float = 3.0


class BlueStacksNoahsTavernRecruitAdapter:
    """Native vision boundary with injected transport and dormant production registration."""

    def __init__(
        self,
        config: NoahAdapterConfig | None = None,
        *,
        transport: Callable[[tuple[int, int]], None] | None = None,
    ) -> None:
        self.config = config or NoahAdapterConfig()
        self.transport = transport
        self.controller = NoahTavernRecruitRuntimeController()

    def observe(self, frame, *, captured_monotonic: float | None = None, now: float | None = None):
        stale = bool(
            now is not None
            and captured_monotonic is not None
            and now - captured_monotonic > self.config.frame_max_age_seconds
        )
        return recognize_noahs_tavern_frame(frame, captured_monotonic=captured_monotonic, stale=stale)

    def command(self, recognition):
        command = self.controller.next_command(recognition)
        if command.action == NoahAction.RECRUIT_FREE and not self.config.dry_run:
            if self.transport is None:
                raise RuntimeError("Noah's Tavern transport is not configured")
            if command.target_roi is None:
                raise RuntimeError("Noah's Tavern command has no current-frame target")
            x0, y0, x1, y1 = command.target_roi
            self.transport(((x0 + x1) // 2, (y0 + y1) // 2))
        return command


class NoahTavernIntegratedRoute:
    """Drive navigation, one or more free recruits, result closure, and Home return."""

    def __init__(
        self,
        runtime: NativeRuntimePort,
        *,
        max_recruits: int = 1,
        controller: NoahTavernRecruitRuntimeController | None = None,
        recognizer=recognize_noahs_tavern_frame,
        post_input_delay: float = 1.0,
        result_timeout: float = 20.0,
    ) -> None:
        if max_recruits < 1 or max_recruits > 5:
            raise ValueError("Noah route max_recruits must be between 1 and 5")
        self.runtime = runtime
        self.max_recruits = max_recruits
        self.controller = controller or NoahTavernRecruitRuntimeController(now=time.monotonic())
        self.recognizer = recognizer
        self.post_input_delay = post_input_delay
        self.result_timeout = result_timeout
        self.pending_result = None
        self.pending_action_key: str | None = None

    @staticmethod
    def _wrap(observation):
        return type("NoahRecognition", (), {"observation": observation, "frame_sha256": observation.frame_sha256})()

    def _observe(self, label: str):
        captured = self.runtime.capture(label)
        observation = self.recognizer(captured.frame, captured_monotonic=captured.captured_monotonic)
        return captured, self._wrap(observation)

    def _wait_for_result(self):
        deadline = time.monotonic() + self.result_timeout
        while time.monotonic() < deadline:
            captured, recognition = self._observe("recruit-immediate-post")
            if recognition.observation.screen_state == "HERO_RECRUIT_RESULT" and recognition.observation.recognized:
                return captured, recognition
            time.sleep(min(0.5, self.post_input_delay))
        return None, None

    def _return_home(self, captured, recognition, actions: int) -> IntegratedRouteResult:
        for ordinal in range(1, 4):
            if recognition.observation.screen_state == "HOME_BASE":
                return IntegratedRouteResult("completed", "returned_home", actions, str(self.runtime.session))
            self.runtime.back(captured, action_key=f"noah:return-home:{ordinal}")
            time.sleep(self.post_input_delay)
            captured, recognition = self._observe(f"return-home-post-{ordinal}")
        return IntegratedRouteResult("blocked", "home_postcondition_not_recognized", actions, str(self.runtime.session))

    def resume_unresolved_result(
        self,
        *,
        before_frame: Path,
        result_frame: Path,
        action_key: str,
        tier: RecruitTier,
    ) -> IntegratedRouteResult:
        """Continue one retained unresolved recruit from its explicit result; never recruit again."""

        if not self.runtime.execute:
            return IntegratedRouteResult("dry-run", "resume_transport_disabled", 0, str(self.runtime.session))
        frame = read_frame(before_frame)
        before = self.recognizer(frame, captured_monotonic=time.monotonic())
        if before.screen_state != NOAHS_TAVERN_SCREEN or before.selected_tier != tier or not before.recognized:
            return IntegratedRouteResult("blocked", "retained_recruit_source_not_recognized", 0, str(self.runtime.session))
        self.controller.progress.awaiting_postcondition = True
        self.controller.progress.awaiting_tier = tier
        self.controller.progress.awaiting_before = before
        self.controller._remember_tier(before, tier)
        self.controller.progress.dispatched_action_keys.add(action_key)
        self.controller.progress.last_dispatch_state = "resumed_unresolved_result"
        self.runtime.in_flight_action = action_key

        captured, recognition = self._observe("resume-current-source")
        if recognition.observation.screen_state == NOAHS_TAVERN_SCREEN:
            retained_result = self.recognizer(read_frame(result_frame), captured_monotonic=captured.captured_monotonic)
            if retained_result.screen_state != HERO_RECRUIT_RESULT_SCREEN or not retained_result.recognized:
                return IntegratedRouteResult("unresolved", "retained_result_screen_not_recognized", 0, str(self.runtime.session))
            result_recognition = self._wrap(replace(retained_result, result_tier=tier))
            if not self.controller.accept_postcondition(result_recognition, recognition.observation):
                self.runtime.reconcile(action_key, "unresolved", captured, "retained result/cooldown not proven")
                return IntegratedRouteResult("unresolved", "retained_postcondition_not_proven", 0, str(self.runtime.session))
            self.runtime.reconcile(action_key, "confirmed", captured, "retained explicit result and active cooldown verified")
            return self._return_home(captured, recognition, 1)
        if recognition.observation.screen_state != HERO_RECRUIT_RESULT_SCREEN or not recognition.observation.recognized:
            return IntegratedRouteResult("unresolved", "current_result_screen_not_recognized", 0, str(self.runtime.session))
        result_observation = replace(recognition.observation, result_tier=tier)
        result_recognition = self._wrap(result_observation)
        command = self.controller.next_command(result_recognition, now=captured.captured_monotonic)
        if command.action != NoahAction.CLOSE_RESULT or command.target_roi is None:
            return IntegratedRouteResult("unresolved", command.reason or "safe_result_close_not_authorized", 0, str(self.runtime.session))
        self.runtime.tap(
            captured,
            target_identity=command.target_identity or "noahs-tavern-result-close",
            target_roi=command.target_roi,
            action_key=f"{action_key}:recovery-close",
            continuation_of=action_key,
        )
        time.sleep(self.post_input_delay)
        after_capture, after_recognition = self._observe("resume-after-close")
        if not self.controller.accept_postcondition(result_recognition, after_recognition.observation):
            self.runtime.reconcile(action_key, "unresolved", after_capture, "recovery decrement/cooldown not proven")
            return IntegratedRouteResult("unresolved", "recovery_postcondition_not_proven", 0, str(self.runtime.session))
        self.runtime.reconcile(action_key, "confirmed", after_capture, "retained result, decrement, and cooldown verified")
        return self._return_home(after_capture, after_recognition, 1)

    def run(self, *, max_steps: int = 40) -> IntegratedRouteResult:
        if not self.runtime.execute:
            _, recognition = self._observe("dry-run-source")
            status = "dry-run" if recognition.observation.recognized else "blocked"
            return IntegratedRouteResult(status, f"transport_disabled:{recognition.observation.screen_state}", 0, str(self.runtime.session))
        actions = 0
        for step in range(1, max_steps + 1):
            captured, recognition = self._observe(f"step-{step:03d}-source")
            command = self.controller.next_command(recognition, now=captured.captured_monotonic)
            if actions >= self.max_recruits and command.action not in {NoahAction.CLOSE_RESULT}:
                return self._return_home(captured, recognition, actions)
            if command.action == NoahAction.OPEN_TAVERN:
                self.runtime.tap(captured, target_identity=command.target_identity or "", target_roi=command.target_roi or (0, 0, 0, 0), action_key=f"noah:open:{captured.sha256}")
            elif command.action == NoahAction.SELECT_TIER:
                self.runtime.tap(captured, target_identity=command.target_identity or "", target_roi=command.target_roi or (0, 0, 0, 0), action_key=f"noah:tier:{command.tier.name}:{captured.sha256}")
            elif command.action == NoahAction.RECRUIT_FREE:
                action_key = command.action_key or f"noah:recruit:{captured.sha256}"
                self.runtime.tap(
                    captured,
                    target_identity=command.target_identity or "",
                    target_roi=command.target_roi or (0, 0, 0, 0),
                    action_key=action_key,
                    consequential=True,
                )
                self.pending_action_key = action_key
                time.sleep(self.post_input_delay)
                post, result = self._wait_for_result()
                if post is None or result is None:
                    unresolved = self.runtime.capture("recruit-result-unresolved")
                    self.runtime.reconcile(action_key, "unresolved", unresolved, "result screen not recognized")
                    return IntegratedRouteResult("unresolved", "recruit_result_not_recognized", actions, str(self.runtime.session))
                self.pending_result = result
                continue
            elif command.action == NoahAction.CLOSE_RESULT:
                if self.pending_result is None or self.pending_action_key is None:
                    return IntegratedRouteResult("blocked", "missing_pending_result", actions, str(self.runtime.session))
                self.runtime.tap(
                    captured,
                    target_identity=command.target_identity or "",
                    target_roi=command.target_roi or (0, 0, 0, 0),
                    action_key=f"{self.pending_action_key}:close",
                    continuation_of=self.pending_action_key,
                )
                time.sleep(self.post_input_delay)
                after_capture, after_recognition = self._observe("recruit-after-close")
                if not self.controller.accept_postcondition(self.pending_result, after_recognition.observation):
                    self.runtime.reconcile(self.pending_action_key, "unresolved", after_capture, "exact decrement/cooldown not proven")
                    return IntegratedRouteResult("unresolved", "recruit_postcondition_not_proven", actions, str(self.runtime.session))
                self.runtime.reconcile(self.pending_action_key, "confirmed", after_capture, "result, decrement, and cooldown verified")
                actions += 1
                self.pending_result = None
                self.pending_action_key = None
                if actions >= self.max_recruits:
                    return self._return_home(after_capture, after_recognition, actions)
                continue
            elif command.action == NoahAction.WAIT_COOLDOWN:
                return self._return_home(captured, recognition, actions)
            elif command.action == NoahAction.RETURN_HOME:
                return self._return_home(captured, recognition, actions)
            else:
                return IntegratedRouteResult("blocked", command.reason or command.action.value, actions, str(self.runtime.session))
            time.sleep(self.post_input_delay)
        return IntegratedRouteResult("blocked", "maximum controller steps exceeded", actions, str(self.runtime.session))


def read_frame(path: Path):
    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f"cannot read native BlueStacks frame: {path}")
    if frame.shape[:2] != (1280, 800):
        raise ValueError("BlueStacks frame must be native 800x1280")
    return frame


def load_unresolved_recruit(session: Path) -> tuple[Path, Path, str, RecruitTier]:
    events_path = session / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    unresolved = next((event for event in reversed(events) if event.get("type") == "reconcile" and event.get("status") == "unresolved"), None)
    if unresolved is None:
        raise RuntimeError("session has no unresolved recruit action")
    action_key = str(unresolved["action_key"])
    dispatch = next((event for event in events if event.get("type") == "dispatch" and event.get("action_key") == action_key and event.get("consequential") is True), None)
    if dispatch is None:
        raise RuntimeError("unresolved action has no retained consequential dispatch")
    source_hash = str(dispatch["source_sha256"])
    capture = next((event for event in events if event.get("type") == "capture" and event.get("sha256") == source_hash), None)
    if capture is None:
        raise RuntimeError("unresolved action source frame is missing")
    result_path = Path(str(unresolved["post_path"]))
    tier_name = action_key.split(":", 1)[0]
    try:
        tier = RecruitTier[tier_name]
    except KeyError as exc:
        raise RuntimeError("unresolved action tier is unknown") from exc
    source_path = Path(str(capture["path"]))
    if not source_path.is_absolute():
        source_path = ROOT / source_path
    if not result_path.is_absolute():
        result_path = ROOT / result_path
    return source_path, result_path, action_key, tier


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--max-recruits", type=int, default=1)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--yes", action="store_true", help="confirm the exact local BlueStacks target non-interactively")
    parser.add_argument("--resume-unresolved-session", type=Path)
    parser.add_argument("--output-directory", type=Path, default=Path(".local-captures/noahs-tavern-integrated"))
    args = parser.parse_args(argv)
    if args.execute and not args.yes:
        parser.error("--execute requires --yes")
    runtime = LocalBlueStacksRuntime.connect(
        adb=args.adb,
        serial=args.serial,
        output_directory=args.output_directory,
        workflow="noahs-tavern",
        execute=args.execute,
    )
    route = NoahTavernIntegratedRoute(runtime, max_recruits=args.max_recruits)
    if args.resume_unresolved_session is not None:
        before_frame, result_frame, action_key, tier = load_unresolved_recruit(args.resume_unresolved_session)
        result = route.resume_unresolved_result(before_frame=before_frame, result_frame=result_frame, action_key=action_key, tier=tier)
    else:
        result = route.run()
    print(json.dumps(result.__dict__, sort_keys=True))
    return 0 if result.status in {"completed", "dry-run"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
