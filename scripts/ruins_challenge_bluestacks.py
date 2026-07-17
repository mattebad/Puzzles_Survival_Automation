#!/usr/bin/env python3
"""Executable, dry-run-by-default native BlueStacks route for Ruins Challenge."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.bluestacks_native_runtime import IntegratedRouteResult, LocalBlueStacksRuntime, NativeRuntimePort
from tasks.ruins_challenge import (
    RuinsAvailability,
    RuinsChestState,
    RuinsControlState,
    RuinsResult,
    current_day_allowed,
)
from tasks.ruins_challenge_runtime import RuinsRuntimeController
from tasks.ruins_challenge_vision import (
    recognize_ruins_detail_with_targets,
    recognize_ruins_frame,
    recognize_ruins_result_with_targets,
    recognize_ruins_reward_frame,
)


class RuinsIntegratedRoute:
    """Drive one bounded challenge and optional independently reconciled Ruins chests."""

    def __init__(
        self,
        runtime: NativeRuntimePort,
        *,
        reset_identity: str,
        current_day: str,
        claim_chests: bool = False,
        allow_optional_second: bool = False,
        excluded_challenges: set[str] | None = None,
        post_input_delay: float = 1.0,
        recognition_timeout: float = 25.0,
    ) -> None:
        self.runtime = runtime
        self.reset_identity = reset_identity
        self.current_day = current_day
        self.claim_chests = claim_chests
        self.allow_optional_second = allow_optional_second
        self.post_input_delay = post_input_delay
        self.recognition_timeout = recognition_timeout
        self.controller = RuinsRuntimeController(
            reset_identity=reset_identity,
            allow_optional_second=allow_optional_second,
        )
        self.controller.challenge_identities_attempted.update(excluded_challenges or set())

    def _observe_list(self, label: str):
        captured = self.runtime.capture(label)
        return captured, recognize_ruins_frame(captured.frame, reset_identity=self.reset_identity)

    def _return_home(self, captured, recognition, actions: int) -> IntegratedRouteResult:
        for ordinal in range(1, 4):
            if recognition.observation.home_base_recognized:
                return IntegratedRouteResult("completed", "returned_home", actions, str(self.runtime.session))
            self.runtime.back(captured, action_key=f"ruins:return-home:{ordinal}")
            time.sleep(self.post_input_delay)
            captured, recognition = self._observe_list(f"return-home-post-{ordinal}")
        return IntegratedRouteResult("blocked", "home_postcondition_not_recognized", actions, str(self.runtime.session))

    def _claim_one_chest(self, captured, recognition):
        observation = recognition.observation
        for row in observation.rows:
            if row.chest_state != RuinsChestState.AVAILABLE:
                continue
            target_identity = f"chest:{row.identity}"
            target = recognition.target(target_identity)
            if target is None:
                return "blocked", "available_chest_target_not_bound", captured, recognition
            action_key = f"ruins:chest:{self.reset_identity}:{row.identity}:{captured.sha256}"
            command = self.controller.plan_chest_claim(observation, row, action_key=action_key)
            if command.kind != "claim_chest":
                return "blocked", command.reason, captured, recognition
            self.runtime.tap(
                captured,
                target_identity=target_identity,
                target_roi=target,
                action_key=action_key,
                consequential=True,
            )
            time.sleep(self.post_input_delay)
            modal_capture = self.runtime.capture("chest-modal-immediate-post")
            modal = recognize_ruins_reward_frame(modal_capture.frame, row.identity, reset_identity=self.reset_identity)
            claim_target = modal.target("ruins-reward-claim")
            if not modal.recognized or claim_target is None:
                self.runtime.reconcile(action_key, "unresolved", modal_capture, "Ruins reward modal not positively recognized")
                return "unresolved", "chest_reward_modal_not_recognized", modal_capture, recognition
            self.runtime.tap(
                modal_capture,
                target_identity="ruins-reward-claim",
                target_roi=claim_target,
                action_key=f"{action_key}:claim",
                continuation_of=action_key,
            )
            time.sleep(self.post_input_delay)
            post_capture, post_recognition = self._observe_list("chest-claim-immediate-post")
            after = post_recognition.observation.row(row.identity)
            chest_target_absent = post_recognition.target(target_identity) is None
            if not post_recognition.observation.recognized or after is None or not chest_target_absent:
                self.runtime.reconcile(action_key, "unresolved", post_capture, "exact chest disappearance not proven")
                return "unresolved", "chest_postcondition_not_proven", post_capture, post_recognition
            after = replace(after, chest_state=RuinsChestState.CLAIMED)
            reconciled = self.controller.reconcile_chest(row, after, action_key=action_key)
            if reconciled.kind != "chest_reconciled":
                self.runtime.reconcile(action_key, "unresolved", post_capture, reconciled.reason)
                return "unresolved", reconciled.reason, post_capture, post_recognition
            self.runtime.reconcile(action_key, "confirmed", post_capture, "exact Ruins chest disappeared after Claim")
            return "claimed", row.identity, post_capture, post_recognition
        return "none", "no_available_chest", captured, recognition

    def _choose_challenge(self, recognition):
        candidates = []
        for row in recognition.observation.rows:
            if (
                row.availability == RuinsAvailability.AVAILABLE
                and row.challenge_control == RuinsControlState.VISIBLE_ENABLED
                and current_day_allowed(row, self.current_day)
                and row.identity not in self.controller.challenge_identities_attempted
                and recognition.target(f"challenge:{row.identity}") is not None
            ):
                candidates.append(row)
        return candidates[0] if candidates else None

    def _run_challenge(self, captured, recognition, row):
        action_key = f"ruins:challenge:{self.reset_identity}:{row.identity}:{captured.sha256}"
        planned = self.controller.plan_challenge(
            recognition.observation,
            row,
            current_day=self.current_day,
            action_key=action_key,
        )
        if planned.kind != "open_detail":
            return IntegratedRouteResult("blocked", planned.reason, 0, str(self.runtime.session))
        target = recognition.target(f"challenge:{row.identity}")
        self.runtime.tap(
            captured,
            target_identity=f"challenge:{row.identity}",
            target_roi=target or (0, 0, 0, 0),
            action_key=f"{action_key}:open",
        )
        time.sleep(self.post_input_delay)
        detail_capture = self.runtime.capture("challenge-detail-immediate-post")
        detail = recognize_ruins_detail_with_targets(
            detail_capture.frame,
            row.identity,
            reset_identity=self.reset_identity,
        )
        attack_target = detail.target("ruins-attack")
        attack = self.controller.plan_attack(detail.observation, action_key=action_key)
        if attack.kind != "attack" or attack_target is None:
            return IntegratedRouteResult("blocked", "detail or Attack target not positively recognized", 0, str(self.runtime.session))
        self.runtime.tap(
            detail_capture,
            target_identity="ruins-attack",
            target_roi=attack_target,
            action_key=f"{action_key}:attack",
        )
        time.sleep(self.post_input_delay)
        dispatch_capture = self.runtime.capture("dispatch-control-immediate-before")
        dispatch_recognition = recognize_ruins_detail_with_targets(
            dispatch_capture.frame,
            row.identity,
            reset_identity=self.reset_identity,
        )
        dispatch_observation = replace(
            dispatch_recognition.observation,
            floor_current=detail.observation.floor_current,
            floor_maximum=detail.observation.floor_maximum,
            attack_control=detail.observation.attack_control,
        )
        dispatch_target = dispatch_recognition.target("ruins-dispatch")
        dispatch = self.controller.plan_dispatch(dispatch_observation, action_key=action_key)
        if dispatch.kind != "dispatch" or dispatch_target is None:
            return IntegratedRouteResult("blocked", "Dispatch target or zero-cost NPC contract not proven", 0, str(self.runtime.session))
        self.runtime.tap(
            dispatch_capture,
            target_identity="ruins-dispatch",
            target_roi=dispatch_target,
            action_key=action_key,
            consequential=True,
        )
        deadline = time.monotonic() + self.recognition_timeout
        result_capture = None
        result_recognition = None
        while time.monotonic() < deadline:
            time.sleep(min(0.5, self.post_input_delay))
            candidate_capture = self.runtime.capture("challenge-result-immediate-post")
            candidate = recognize_ruins_result_with_targets(
                candidate_capture.frame,
                row.identity,
                before_progress=row.progress_current,
                reset_identity=self.reset_identity,
            )
            if candidate.observation.result != RuinsResult.AMBIGUOUS and candidate.target("ruins-result-continue") is not None:
                result_capture, result_recognition = candidate_capture, candidate
                break
        if result_capture is None or result_recognition is None:
            unresolved = self.runtime.capture("challenge-result-unresolved")
            self.runtime.reconcile(action_key, "unresolved", unresolved, "explicit result and safe continuation not recognized")
            return IntegratedRouteResult("unresolved", "challenge_result_not_recognized", 0, str(self.runtime.session))
        self.runtime.tap(
            result_capture,
            target_identity="ruins-result-continue",
            target_roi=result_recognition.target("ruins-result-continue") or (0, 0, 0, 0),
            action_key=f"{action_key}:continue",
            continuation_of=action_key,
        )
        time.sleep(self.post_input_delay)
        list_capture, list_recognition = self._observe_list("challenge-list-postcondition")
        result_observation = result_recognition.observation
        if result_observation.result == RuinsResult.SUCCESS:
            after_row = list_recognition.observation.row(row.identity)
            if after_row is None:
                self.runtime.reconcile(action_key, "unresolved", list_capture, "successful row progress not visible")
                return IntegratedRouteResult("unresolved", "successful_progress_not_visible", 0, str(self.runtime.session))
            result_observation = replace(
                result_observation,
                progress_after=after_row.progress_current,
                maximum_after=after_row.progress_maximum,
                level_after=after_row.progress_current,
            )
        reconciled = self.controller.reconcile_result(row, result_observation)
        if reconciled.kind != "reconciled":
            self.runtime.reconcile(action_key, "unresolved", list_capture, reconciled.reason)
            return IntegratedRouteResult("unresolved", reconciled.reason, 0, str(self.runtime.session))
        status = "confirmed" if result_observation.result == RuinsResult.SUCCESS else "failed_confirmed"
        self.runtime.reconcile(action_key, status, list_capture, f"explicit {result_observation.result.value} result reconciled")
        return list_capture, list_recognition, result_observation.result

    def run(self, *, max_steps: int = 30) -> IntegratedRouteResult:
        if not self.runtime.execute:
            _, recognition = self._observe_list("dry-run-source")
            status = "dry-run" if recognition.observation.recognized else "blocked"
            return IntegratedRouteResult(status, f"transport_disabled:{recognition.observation.screen_identity}", 0, str(self.runtime.session))
        actions = 0
        captured, recognition = self._observe_list("route-source")
        if recognition.observation.home_base_recognized:
            target = recognition.target("ruins-building")
            if target is None:
                return IntegratedRouteResult("blocked", "Ruins building target not bound", 0, str(self.runtime.session))
            self.runtime.tap(
                captured,
                target_identity="ruins-building",
                target_roi=target,
                action_key=f"ruins:open:{captured.sha256}",
            )
            time.sleep(self.post_input_delay)
            captured, recognition = self._observe_list("ruins-list-immediate-post")
        if not recognition.observation.recognized or recognition.observation.screen_identity != "RUINS_CHALLENGE":
            return IntegratedRouteResult("blocked", "Ruins list not positively recognized", 0, str(self.runtime.session))
        self.controller.observe_list(recognition.observation)
        if self.claim_chests:
            for _ in range(max_steps):
                chest_status, reason, captured, recognition = self._claim_one_chest(captured, recognition)
                if chest_status == "claimed":
                    actions += 1
                    self.controller.observe_list(recognition.observation)
                    continue
                if chest_status in {"blocked", "unresolved"}:
                    return IntegratedRouteResult(chest_status, reason, actions, str(self.runtime.session))
                break
        row = self._choose_challenge(recognition)
        if row is None:
            return self._return_home(captured, recognition, actions)
        challenge_result = self._run_challenge(captured, recognition, row)
        if isinstance(challenge_result, IntegratedRouteResult):
            return challenge_result
        captured, recognition, result = challenge_result
        actions += 1
        if result == RuinsResult.FAILURE and self.allow_optional_second:
            self.controller.observe_list(recognition.observation)
            second_row = self._choose_challenge(recognition)
            if second_row is not None:
                second_result = self._run_challenge(captured, recognition, second_row)
                if isinstance(second_result, IntegratedRouteResult):
                    return IntegratedRouteResult(
                        second_result.status,
                        second_result.reason,
                        actions + second_result.actions_completed,
                        second_result.session_directory,
                    )
                captured, recognition, _ = second_result
                actions += 1
        return self._return_home(captured, recognition, actions)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--reset-identity", required=True)
    parser.add_argument("--current-day", required=True, choices=("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"))
    parser.add_argument("--claim-chests", action="store_true")
    parser.add_argument("--allow-optional-second", action="store_true")
    parser.add_argument("--exclude-challenge", action="append", default=[])
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--yes", action="store_true", help="confirm the exact local BlueStacks target non-interactively")
    parser.add_argument("--output-directory", type=Path, default=Path(".local-captures/ruins-challenge-integrated"))
    args = parser.parse_args(argv)
    if args.execute and not args.yes:
        parser.error("--execute requires --yes")
    runtime = LocalBlueStacksRuntime.connect(
        adb=args.adb,
        serial=args.serial,
        output_directory=args.output_directory,
        workflow="ruins-challenge",
        execute=args.execute,
    )
    result = RuinsIntegratedRoute(
        runtime,
        reset_identity=args.reset_identity,
        current_day=args.current_day,
        claim_chests=args.claim_chests,
        allow_optional_second=args.allow_optional_second,
        excluded_challenges=set(args.exclude_challenge),
    ).run()
    print(json.dumps(result.__dict__, sort_keys=True))
    return 0 if result.status in {"completed", "dry-run"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
