"""Focused offline tests for the retained Ruins challenge replay CLI."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import ruins_challenge_replay as replay
from scripts import ruins_challenge_bluestacks as native_route
from scripts.bluestacks_native_runtime import CapturedNativeFrame, IntegratedRouteResult
from scripts import navigation_development_boundary as development
from scripts.home_atlas_bluestacks import HomeDriverDisposition
from tasks.ruins_challenge import (
    RuinsAvailability,
    RuinsChallengeRow,
    RuinsChestState,
    RuinsControlState,
    RuinsDetailObservation,
    RuinsResult,
    RuinsResultObservation,
    RuinsScreenObservation,
)
from tasks.runtime_identity import (
    derive_resource_runtime_identity,
    resource_fixed_runtime_binding,
)
from tasks.ruins_challenge_vision import (
    RuinsDetailRecognition,
    RuinsFrameRecognition,
    RuinsResultRecognition,
    RuinsRewardRecognition,
)


def _native_png(path: Path, *, color: tuple[int, int, int]) -> bytes:
    frame = np.zeros((1280, 800, 3), dtype=np.uint8)
    frame[:, :] = color
    encoded, buffer = cv2.imencode(".png", frame)
    if not encoded:
        raise AssertionError("test PNG encoding failed")
    path.write_bytes(buffer.tobytes())
    return path.read_bytes()


def _recognition(frame: np.ndarray, *, reset_identity: str | None = None):
    row = RuinsChallengeRow(
        "Hero Challenge",
        "Mon",
        RuinsAvailability.AVAILABLE,
        6,
        60,
        None,
        RuinsControlState.VISIBLE_ENABLED,
        RuinsChestState.UNKNOWN,
        (18, 220, 780, 410),
        reset_identity=reset_identity,
    )
    observation = RuinsScreenObservation(
        True,
        "RUINS_CHALLENGE",
        True,
        1234,
        RuinsControlState.VISIBLE_ENABLED,
        RuinsControlState.VISIBLE_ENABLED,
        RuinsControlState.VISIBLE_ENABLED,
        (row,),
        "none",
        "pixel-hash",
        reset_identity,
    )
    return SimpleNamespace(
        observation=observation,
        targets=(("challenge:Hero Challenge", (560, 290, 780, 390)),),
    )


def _tree_snapshot(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(path.relative_to(root)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


class _FakeRuinsRuntime:
    def __init__(self, session: Path):
        self.session = session
        self.session.mkdir(parents=True, exist_ok=True)
        self.execute = True
        self.state = "home"
        self.ordinal = 0
        self.input_count = 0
        self.claimed: set[str] = set()
        self.modal_identity = ""
        self.points = 1000
        self.rewards = {"Hero Challenge": 11, "Weapon Trial": 22}
        self.consequential_targets: list[str] = []
        self.max_inputs = 48
        self.progress = 6
        self.wins_before_loss = 0
        self.stages_dispatched = 0
        self.last_result = "failure"

    def swipe(self, *_args, **_kwargs):
        self.input_count += 1

    def back(self, *_args, **_kwargs):
        self.input_count += 1
        self.state = "list"

    def measure_foreground_package(self):
        return "com.global.ztmslg"

    def capture(self, label: str):
        del label
        self.ordinal += 1
        state_code = {
            "home": 0,
            "list": 1,
            "detail": 2,
            "result": 3,
            "modal": 4,
        }[self.state]
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        frame[0, 0, 0] = state_code
        frame[0, 1, 0] = self.ordinal % 256
        digest = hashlib.sha256(frame.tobytes()).hexdigest()
        return CapturedNativeFrame(
            frame=frame,
            png=b"offline-replay-frame",
            sha256=digest,
            captured_monotonic=float(self.ordinal),
            path=self.session / f"frame-{self.ordinal:04d}.png",
        )

    def tap(self, _source, *, target_identity: str, consequential: bool = False, **_kwargs):
        self.input_count += 1
        if consequential:
            self.consequential_targets.append(target_identity)
        if target_identity == native_route.RUINS_HOME_ATLAS_BUILDING_ID:
            self.state = "list"
        elif target_identity.startswith("challenge:") or target_identity == "ruins-attack":
            self.state = "detail"
        elif target_identity == "ruins-dispatch":
            self.stages_dispatched += 1
            self.last_result = "success" if self.stages_dispatched <= self.wins_before_loss else "failure"
            self.state = "result"
        elif target_identity == "ruins-result-continue":
            if self.last_result == "success":
                self.progress += 1
            self.state = "list"
        elif target_identity.startswith("chest:"):
            self.modal_identity = target_identity.split(":", 1)[1]
            self.state = "modal"
        elif target_identity == "ruins-reward-claim":
            self.claimed.add(self.modal_identity)
            self.points += self.rewards[self.modal_identity]
            self.state = "list"


class _FakeCanonicalActionExecutor:
    def __init__(self, runtime: _FakeRuinsRuntime, *, unknown_challenge: bool):
        self.runtime = runtime
        self.unknown_challenge = unknown_challenge
        self.confirmed: dict[str, dict[str, str]] = {}
        self.transport_calls_by_category = {"challenge": 0, "chest": 0}
        self.unresolved = False
        self.prior_result = None

    def reset_progress(self, _legacy_action_key):
        results = [proof["result"] for proof in self.confirmed.values() if proof["result"] in {"success", "failure"}]
        if self.prior_result:
            results.append(self.prior_result)
        return {
            "stages_confirmed": len(results),
            "stages_won": results.count("success"),
            "finished": "failure" in results,
            "unresolved": self.unresolved,
        }

    def status(self, spec):
        proof = self.confirmed.get(spec["action_key"])
        return {"status": "confirmed", "result": proof} if proof is not None else {"status": "new"}

    def execute(self, *, spec, capture, observe, dispatch, successor, **_kwargs):
        previous = self.status(spec)
        if previous["status"] != "new":
            return {**previous, "transport_calls": 0}
        immediate = capture("offline-immediate-before")
        observation = observe(immediate)
        if observation is None:
            return {"status": "blocked", "reason": "fake_observation_missing", "transport_calls": 0}
        dispatch(immediate, observation)
        category = spec["category"]
        self.transport_calls_by_category[category] += 1
        if category == "challenge" and self.unknown_challenge:
            self.unresolved = True
            return {"status": "unresolved", "reason": "fake_result_unknown", "transport_calls": 1}
        post = capture("offline-postcondition")
        if successor(post) != spec["expected_postcondition"]:
            self.unresolved = True
            return {"status": "unresolved", "reason": "fake_postcondition_missing", "transport_calls": 1}
        proof = {"result": spec["result"]} if category == "challenge" else {"result": "confirmed"}
        self.confirmed[spec["action_key"]] = proof
        return {"status": "confirmed", "reason": "fake_postcondition_confirmed", "transport_calls": 1}


def _run_native_fake_visit(
    root: Path,
    *,
    unknown_challenge: bool = False,
    challenge_available: bool = True,
    wrong_reward_modal: bool = False,
    retain_claimed_target: bool = False,
    hide_claimed_row: bool = False,
    wins_before_loss: int = 0,
    maximum_inputs: int = 48,
    unavailable_detail: bool = False,
    prior_result: str | None = None,
    challenge_after_claim: bool = False,
    resume=None,
):
    reset_identity = "game-day-2026-07-16"
    current_day = "Thu"
    if resume is None:
        runtime = _FakeRuinsRuntime(root / "fake-native-session")
        runtime.wins_before_loss = wins_before_loss
        executor = _FakeCanonicalActionExecutor(runtime, unknown_challenge=unknown_challenge)
        executor.prior_result = prior_result
    else:
        runtime, executor = resume
        runtime.state = "home"
        runtime.input_count = 0
    runtime.max_inputs = maximum_inputs
    binding = resource_fixed_runtime_binding()
    backend = derive_resource_runtime_identity(
        binding,
        datetime(2026, 7, 16, 12, tzinfo=timezone.utc),
    )
    home_driver = SimpleNamespace(
        observe=lambda _frame: SimpleNamespace(disposition=HomeDriverDisposition.COMPLETE)
    )
    session = development.DevelopmentSession(
        owner="ruins-offline-replay",
        invocation_id=f"visit-{runtime.ordinal}",
        session_directory=root / f"development-{runtime.ordinal}",
        max_inputs=maximum_inputs,
    )
    route = native_route.RuinsIntegratedRoute(
        runtime,
        reset_identity=reset_identity,
        current_day=current_day,
        account_id=backend.account_id,
        server_id=backend.server_id,
        runtime_scope=backend.runtime_scope,
        product_id=native_route.RUINS_PRODUCT_ID,
        product_revision=native_route.RUINS_PRODUCT_REVISION,
        runtime_identity=backend,
        action_executor=executor,
        session=session,
        initial_capture=runtime.capture("offline-home"),
        home_driver=home_driver,
        post_input_delay=0,
    )
    route.runtime = runtime
    route._prepare_navigation = lambda _captured, **_kwargs: None
    route._current_frame_ruins_binding = lambda _captured: (80, 900, 160, 970)

    def return_home(_captured, _recognition, actions):
        runtime.state = "home"
        route.terminal_home_verified = True
        route.terminal_home_capture = runtime.capture("offline-terminal-home")
        return IntegratedRouteResult("completed", "fake_home_reconciled", actions, str(runtime.session))

    route._return_home = return_home
    ready_categories = {"Hero Challenge", "Weapon Trial"}

    def recognize_list(frame, *, reset_identity=None):
        digest = hashlib.sha256(frame.tobytes()).hexdigest()
        if int(frame[0, 0, 0]) != 1:
            empty = RuinsScreenObservation(
                False, "UNKNOWN", False, None,
                RuinsControlState.UNKNOWN, RuinsControlState.UNKNOWN, RuinsControlState.UNKNOWN,
                (), "none", digest, reset_identity,
            )
            return RuinsFrameRecognition(empty, digest, (), {})
        rows = []
        targets = []
        # Only current visible categories are observed; unrelated categories
        # are not a completion census prerequisite.
        for identity in ("Hero Challenge", "Weapon Trial", "Nova Challenge"):
            if hide_claimed_row and identity in runtime.claimed:
                continue
            is_challenge = (identity == "Nova Challenge" and challenge_available) or (
                challenge_after_claim and identity in runtime.claimed
            )
            chest_state = (
                RuinsChestState.UNKNOWN
                if identity in runtime.claimed or identity not in ready_categories
                else RuinsChestState.AVAILABLE
            )
            row = RuinsChallengeRow(
                identity=identity,
                day_label=current_day if is_challenge else None,
                availability=RuinsAvailability.AVAILABLE if is_challenge else RuinsAvailability.UNAVAILABLE,
                progress_current=runtime.progress if is_challenge else 6,
                progress_maximum=60,
                last_successful_level=runtime.progress if is_challenge else 6,
                challenge_control=(
                    RuinsControlState.VISIBLE_ENABLED if is_challenge else RuinsControlState.HIDDEN
                ),
                chest_state=chest_state,
                target_roi=(18, 220, 780, 410),
                source_frame_sha256=digest,
                reset_identity=reset_identity,
            )
            rows.append(row)
            if is_challenge:
                targets.append((f"challenge:{identity}", (560, 290, 780, 390)))
            if chest_state == RuinsChestState.AVAILABLE or (
                retain_claimed_target and identity in runtime.claimed
            ):
                targets.append((f"chest:{identity}", (600, 230, 780, 380)))
        observation = RuinsScreenObservation(
            True,
            "RUINS_CHALLENGE",
            True,
            runtime.points,
            RuinsControlState.VISIBLE_ENABLED,
            RuinsControlState.VISIBLE_ENABLED,
            RuinsControlState.VISIBLE_ENABLED,
            tuple(rows),
            "none",
            digest,
            reset_identity,
            safe_back_control=RuinsControlState.VISIBLE_ENABLED,
        )
        return RuinsFrameRecognition(observation, digest, tuple(targets), {})

    def recognize_detail(frame, identity, *, reset_identity=None):
        digest = hashlib.sha256(frame.tobytes()).hexdigest()
        observation = RuinsDetailObservation(
            identity=identity,
            recognized=True,
            floor_current=runtime.progress,
            floor_maximum=60,
            attack_control=RuinsControlState.HIDDEN if unavailable_detail else RuinsControlState.VISIBLE_ENABLED,
            dispatch_control=RuinsControlState.VISIBLE_ENABLED,
            npc_troops_provided=True,
            npc_troops_current=200200,
            npc_troops_maximum=200200,
            skip_battle_enabled=True,
            resource_cost=0,
            source_frame_sha256=digest,
            reset_identity=reset_identity,
        )
        return RuinsDetailRecognition(
            observation,
            digest,
            (("ruins-attack", (250, 900, 550, 1000)), ("ruins-dispatch", (250, 1125, 550, 1230))),
            {},
        )

    def recognize_result(frame, identity, **_kwargs):
        digest = hashlib.sha256(frame.tobytes()).hexdigest()
        valid = int(frame[0, 0, 0]) == 3 and identity == "Nova Challenge"
        observation = RuinsResultObservation(
            identity=identity,
            result=RuinsResult(runtime.last_result) if valid else RuinsResult.AMBIGUOUS,
            progress_after=None,
            maximum_after=None,
            level_after=None,
            explicit_success_text=valid and runtime.last_result == "success",
            source_frame_sha256=digest,
            reset_identity=reset_identity,
            explicit_failure_text=valid and runtime.last_result == "failure",
            tap_to_continue_visible=valid,
        )
        targets = (("ruins-result-continue", (250, 1100, 550, 1220)),) if valid else ()
        return RuinsResultRecognition(observation, digest, targets, {})

    def recognize_reward(frame, identity, *, reset_identity=None):
        digest = hashlib.sha256(frame.tobytes()).hexdigest()
        modal_identity = (
            "Weapon Trial"
            if wrong_reward_modal and identity == "Hero Challenge"
            else identity
        )
        medal_amount = runtime.rewards[identity]
        return RuinsRewardRecognition(
            modal_identity == identity,
            modal_identity,
            medal_amount,
            digest,
            reset_identity,
            (("ruins-reward-claim", (250, 680, 550, 790)),),
            {},
        )

    with patch.object(native_route, "is_clean_home_frame", side_effect=lambda frame: int(frame[0, 0, 0]) == 0), patch.object(
        native_route, "recognize_ruins_frame", side_effect=recognize_list,
    ), patch.object(
        native_route, "recognize_ruins_detail_with_targets", side_effect=recognize_detail,
    ), patch.object(
        native_route, "recognize_ruins_result_with_targets", side_effect=recognize_result,
    ), patch.object(
        native_route, "recognize_ruins_reward_frame", side_effect=recognize_reward,
    ), patch.object(development, "RUNTIME_INPUT_LOCK_PATH", root / "input-lock.sqlite3"), session:
        outcome = route.run()
    return route, runtime, executor, outcome


class RuinsChallengeReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = (Path(self.temp.name) / "retained").resolve()
        self.root.mkdir()
        self.frames = self.root / "frames"
        self.frames.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_directory_replay_is_sorted_and_compact_with_file_hashes(self) -> None:
        first = self.frames / "002-second.png"
        second = self.frames / "001-first.png"
        first_bytes = _native_png(first, color=(1, 2, 3))
        second_bytes = _native_png(second, color=(4, 5, 6))

        before = _tree_snapshot(self.root)

        def reject_live_command(*args, **kwargs):  # type: ignore[no-untyped-def]
            command = f"{args!r} {kwargs!r}".lower()
            if any(token in command for token in ("adb", "hd-adb", "pnsctl")):
                raise AssertionError(f"replay attempted a live command: {command}")
            raise AssertionError(f"unexpected subprocess command: {command}")

        # The recognizer is guarded here so this test remains fast; a real
        # recognizer may legitimately use pytesseract's local subprocess.
        with patch.object(replay, "recognize_ruins_frame", side_effect=_recognition) as recognizer, patch.object(
            subprocess, "run", side_effect=reject_live_command
        ):
            payload = replay.replay_frames(frames_dir=self.frames, allowed_roots=(self.root,))

        self.assertEqual(payload["frame_count"], 2)
        self.assertEqual([item["order"] for item in payload["frames"]], [1, 2])
        self.assertEqual(
            [item["path"] for item in payload["frames"]],
            [(self.frames / "001-first.png").as_posix(), (self.frames / "002-second.png").as_posix()],
        )
        self.assertEqual(payload["frames"][0]["sha256"], hashlib.sha256(second_bytes).hexdigest())
        self.assertEqual(payload["frames"][1]["sha256"], hashlib.sha256(first_bytes).hexdigest())
        self.assertEqual(payload["frames"][0]["screen_identity"], "RUINS_CHALLENGE")
        self.assertEqual(payload["frames"][0]["surface"], "RUINS_CHALLENGE")
        self.assertEqual(payload["frames"][0]["rows"][0]["identity"], "Hero Challenge")
        self.assertEqual(payload["frames"][0]["rows"][0]["availability"], "available")
        self.assertEqual(payload["frames"][0]["targets"][0]["roi"], [560, 290, 780, 390])
        self.assertEqual(replay.serialize_replay(payload), replay.serialize_replay(payload))
        self.assertEqual(recognizer.call_count, 2)
        self.assertEqual(_tree_snapshot(self.root), before)
        self.assertNotIn("subprocess", replay.__dict__)
        self.assertNotIn("scripts.bluestacks_native_runtime", replay.__dict__)
        self.assertNotIn("scripts.pnsctl", replay.__dict__)

    def test_result_replay_requires_and_preserves_explicit_challenge_identity(self) -> None:
        frame_path = self.frames / "result.png"
        _native_png(frame_path, color=(7, 8, 9))
        list_result = SimpleNamespace(
            observation=SimpleNamespace(recognized=False, screen_identity="UNKNOWN", rows=()),
            targets=(),
        )
        result = SimpleNamespace(
            observation=SimpleNamespace(
                identity="Hero Challenge",
                result=RuinsResult.FAILURE,
                explicit_failure_text=True,
                reset_identity="game-day-2026-01-12",
            ),
            targets=(),
        )
        with patch.object(replay, "recognize_ruins_frame", return_value=list_result), patch.object(
            replay, "recognize_ruins_result_with_targets", return_value=result
        ) as result_recognizer:
            payload = replay.replay_frames(
                (frame_path,),
                reset_identity="game-day-2026-01-12",
                challenge_identity="Hero Challenge",
                allowed_roots=(self.root,),
            )
        result_recognizer.assert_called_once()
        self.assertEqual(payload["frames"][0]["surface"], "RUINS_CHALLENGE_RESULT")
        self.assertEqual(payload["frames"][0]["identity"], "Hero Challenge")
        self.assertEqual(payload["frames"][0]["result"], "failure")

    def test_explicit_paths_preserve_order_and_cli_json_is_parseable(self) -> None:
        one = self.frames / "one.png"
        two = self.frames / "two.png"
        _native_png(one, color=(10, 11, 12))
        _native_png(two, color=(13, 14, 15))
        with patch.object(replay, "recognize_ruins_frame", side_effect=_recognition):
            payload = replay.replay_frames((two, one), allowed_roots=(self.root,))
        self.assertEqual([item["path"] for item in payload["frames"]], [two.as_posix(), one.as_posix()])

        with patch.object(replay, "recognize_ruins_frame", side_effect=_recognition), patch.object(
            replay, "RETAINED_ROOTS", (self.root,)
        ), patch("sys.stdout.write") as output:
            self.assertEqual(replay.main(["--frames-dir", str(self.frames)]), 0)
        emitted = "".join(call.args[0] for call in output.call_args_list)
        self.assertEqual(json.loads(emitted)["frame_count"], 2)

    def test_rejects_empty_dir_bad_extension_escape_and_nonnative_dimensions(self) -> None:
        with self.assertRaisesRegex(replay.ReplayError, "empty"):
            replay.resolve_frame_paths(frames_dir=self.frames, allowed_roots=(self.root,))

        bad = self.frames / "not-a-frame.jpg"
        bad.write_bytes(b"junk")
        with self.assertRaisesRegex(replay.ReplayError, "unsupported extension"):
            replay.resolve_frame_paths(frames_dir=self.frames, allowed_roots=(self.root,))

        outside = Path(self.temp.name) / "outside.png"
        _native_png(outside, color=(7, 8, 9))
        with self.assertRaisesRegex(replay.ReplayError, "outside allowed retained roots"):
            replay.resolve_frame_paths((outside,), allowed_roots=(self.root,))

        png_directory = self.root / "directory.png"
        png_directory.mkdir()
        with self.assertRaisesRegex(replay.ReplayError, "not a file"):
            replay.resolve_frame_paths((png_directory,), allowed_roots=(self.root,))

        wrong = self.frames / "wrong.png"
        wrong_frame = np.zeros((640, 800, 3), dtype=np.uint8)
        encoded, buffer = cv2.imencode(".png", wrong_frame)
        self.assertTrue(encoded)
        wrong.write_bytes(buffer.tobytes())
        with self.assertRaisesRegex(replay.ReplayError, "native 800x1280"):
            replay.resolve_frame_paths((wrong,), allowed_roots=(self.root,))

    def test_rejects_mixed_sources_and_duplicate_explicit_paths(self) -> None:
        frame = self.frames / "frame.png"
        _native_png(frame, color=(20, 21, 22))
        with self.assertRaisesRegex(replay.ReplayError, "not both"):
            replay.resolve_frame_paths((frame,), frames_dir=self.frames, allowed_roots=(self.root,))
        with self.assertRaisesRegex(replay.ReplayError, "duplicate"):
            replay.resolve_frame_paths((frame, frame), allowed_roots=(self.root,))

    def test_production_route_offline_replay_handles_loss_and_independent_green_chests(self):
        route, runtime, executor, outcome = _run_native_fake_visit(self.root)
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(route.challenge_status, "finished")
        self.assertEqual(route.challenge_stages[-1]["result"], "failure")
        self.assertTrue(route.challenge_participation_confirmed)
        self.assertEqual(route.challenge_transport_calls, 1)
        self.assertEqual(route.chest_claim_transport_calls, 2)
        self.assertEqual(route.challenge_transport_calls + route.chest_claim_transport_calls, 3)
        self.assertTrue(route.terminal_home_verified)
        self.assertEqual(len(runtime.consequential_targets), 3)
        self.assertEqual(runtime.consequential_targets,
            ["ruins-dispatch", "ruins-reward-claim", "ruins-reward-claim"])
        self.assertEqual(executor.transport_calls_by_category, {"challenge": 1, "chest": 2})

    def test_production_route_offline_unavailable_challenge_keeps_ready_chests(self):
        route, runtime, executor, outcome = _run_native_fake_visit(
            self.root, challenge_available=False,
        )
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(route.challenge_status, "unavailable")
        self.assertFalse(route.challenge_participation_confirmed)
        self.assertEqual(route.challenge_transport_calls, 0)
        self.assertEqual(route.chest_claim_transport_calls, 2)
        self.assertEqual(len(runtime.consequential_targets), 2)
        self.assertEqual(executor.transport_calls_by_category, {"challenge": 0, "chest": 2})
        self.assertTrue(route.terminal_home_verified)

    def test_production_route_offline_unknown_never_retries_and_returns_home(self):
        route, runtime, executor, outcome = _run_native_fake_visit(
            self.root, unknown_challenge=True,
        )
        self.assertEqual(outcome.status, "unresolved")
        self.assertTrue(route.unresolved_action)
        self.assertEqual(route.challenge_transport_calls, 1)
        self.assertEqual(route.chest_claim_transport_calls, 0)
        self.assertEqual(runtime.consequential_targets, ["ruins-dispatch"])
        self.assertEqual(executor.transport_calls_by_category, {"challenge": 1, "chest": 0})
        self.assertTrue(route.terminal_home_verified)

    def test_production_route_blocks_wrong_reward_identity_before_claim_dispatch(self):
        route, runtime, executor, outcome = _run_native_fake_visit(
            self.root, wrong_reward_modal=True,
        )
        self.assertEqual(outcome.status, "unresolved")
        self.assertIn("ruins_reward_modal_not_exact_zero_cost_identity", outcome.reason)
        self.assertEqual(route.challenge_stages[-1]["result"], "failure")
        self.assertTrue(route.challenge_participation_confirmed)
        self.assertEqual(route.chest_claim_transport_calls, 0)
        self.assertEqual(runtime.consequential_targets, ["ruins-dispatch"])
        self.assertEqual(executor.transport_calls_by_category, {"challenge": 1, "chest": 0})
        self.assertEqual(route.newly_claimed_chests, [])

    def test_native_visible_unknown_row_reconciles_only_with_exact_owned_successor(self):
        # These rows use vision's actual UNKNOWN post-claim presentation, not
        # a synthetic CLAIMED label; the sibling stays independently ready.
        route, runtime, _executor, outcome = _run_native_fake_visit(self.root)
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(route.chest_claim_transport_calls, 2)
        self.assertEqual([item["identity"] for item in route.newly_claimed_chests],
            ["Hero Challenge", "Weapon Trial"])
        self.assertEqual(runtime.consequential_targets[0], "ruins-dispatch")

    def test_green_target_retained_or_exact_row_hidden_stays_unknown(self):
        for options in ({"retain_claimed_target": True}, {"hide_claimed_row": True}):
            with self.subTest(options=options):
                route, runtime, _executor, outcome = _run_native_fake_visit(self.root, **options)
                self.assertEqual(outcome.status, "unresolved")
                self.assertTrue(route.unresolved_action)
                self.assertEqual(route.chest_claim_transport_calls, 1)
                self.assertEqual(route.newly_claimed_chests, [])
                self.assertEqual(runtime.consequential_targets,
                    ["ruins-dispatch", "ruins-reward-claim"])

    def test_wins_continue_to_first_loss_then_claims_and_restart_preserves_stop(self):
        route, runtime, executor, outcome = _run_native_fake_visit(self.root, wins_before_loss=2)
        self.assertEqual(outcome.status, "completed")
        self.assertEqual([stage["result"] for stage in route.challenge_stages],
                         ["success", "success", "failure"])
        self.assertEqual([stage["stage_cleared"] for stage in route.challenge_stages], [6, 7, 8])
        self.assertEqual(route.challenge_transport_calls, 3)
        self.assertEqual(route.chest_claim_transport_calls, 2)
        self.assertEqual(runtime.consequential_targets[:3], ["ruins-dispatch"] * 3)
        resumed, _runtime, _executor, second = _run_native_fake_visit(
            self.root, resume=(runtime, executor),
        )
        self.assertEqual(second.status, "completed")
        self.assertEqual(resumed.challenge_status, "finished")
        self.assertEqual(resumed.challenge_stages, [])
        self.assertEqual(resumed.challenge_transport_calls, 0)
        self.assertEqual(resumed.chest_claim_transport_calls, 0)

    def test_budget_pause_resumes_at_observed_next_stage_not_one_daily_attempt(self):
        first, runtime, executor, outcome = _run_native_fake_visit(
            self.root, wins_before_loss=2, maximum_inputs=14,
        )
        self.assertEqual(outcome.status, "unresolved")
        self.assertEqual(first.challenge_status, "paused")
        self.assertFalse(first.unresolved_action)
        self.assertEqual(first.challenge_transport_calls, 1)
        self.assertEqual(first.chest_claim_transport_calls, 2)
        self.assertTrue(first.terminal_home_verified)
        resumed, _runtime, _executor, second = _run_native_fake_visit(
            self.root, resume=(runtime, executor),
        )
        self.assertEqual(second.status, "completed")
        self.assertEqual([stage["stage_cleared"] for stage in resumed.challenge_stages], [7, 8])
        self.assertEqual([stage["result"] for stage in resumed.challenge_stages], ["success", "failure"])
        self.assertEqual(resumed.chest_claim_transport_calls, 0)

    def test_never_sent_unavailable_detail_releases_plan_for_independent_chests(self):
        route, runtime, _executor, outcome = _run_native_fake_visit(
            self.root, unavailable_detail=True,
        )
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(route.challenge_status, "unavailable")
        self.assertEqual(route.challenge_transport_calls, 0)
        self.assertEqual(route.chest_claim_transport_calls, 2)
        self.assertFalse(route.unresolved_action)
        self.assertEqual(runtime.consequential_targets, ["ruins-reward-claim"] * 2)

    def test_true_unknown_survives_another_visit_without_dispatch(self):
        _first, runtime, executor, _outcome = _run_native_fake_visit(self.root, unknown_challenge=True)
        second, _runtime, _executor, outcome = _run_native_fake_visit(
            self.root, resume=(runtime, executor),
        )
        self.assertEqual(outcome.status, "unresolved")
        self.assertTrue(second.unresolved_action)
        self.assertEqual(second.challenge_transport_calls, 0)
        self.assertEqual(second.chest_claim_transport_calls, 0)
        self.assertEqual(runtime.consequential_targets, ["ruins-dispatch"])

    def test_spent_green_chest_successor_does_not_require_challenge_unavailable(self):
        route, _runtime, _executor, outcome = _run_native_fake_visit(self.root, challenge_after_claim=True)
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(route.chest_claim_transport_calls, 2)
        self.assertFalse(route.unresolved_action)



if __name__ == "__main__":
    unittest.main()
