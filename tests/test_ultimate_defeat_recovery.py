"""Offline Defeat recognition and post-Flee-only recovery safety."""

from contextlib import ExitStack, redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from scripts import bluestacks_ultimate_challenge as native
from scripts import flow_delivery_ultimate_challenge_bluestacks as delivery
from scripts import pnsctl
from scripts.startup_recovery import classify_startup_frame
from automation_service import ultimate as service
from tests import test_bluestacks_ultimate_challenge as helpers
from tests import test_ultimate_challenge_recovery as recovery_helpers


FIXTURES = Path(__file__).parent / "fixtures" / "ultimate_active_battle"
DEFEAT = FIXTURES / "native-defeat-after-flee-20261101.png"
WARNING = FIXTURES / "native-flee-warning-over-defeat-20261101.png"
RESET = "game-day-2026-11-01"


def read_frame(path):
    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None:
        raise AssertionError(f"Missing portable fixture: {path}")
    return frame


class RecoveryInputBudgetTests(unittest.TestCase):
    def test_cli_accepts_remaining_budget_after_shared_recovery_without_device_access(self):
        for budget in (1, 14, 15, 16):
            with self.subTest(budget=budget), patch.object(native, "ADBRunner") as device:
                output = io.StringIO()
                with redirect_stdout(output):
                    status = native.main([
                        "--adb", "unused-adb", "--serial", "127.0.0.1:5555",
                        "--post-flee-home-only", "--max-total-inputs", str(budget),
                    ])
                self.assertEqual(status, 0)
                self.assertFalse(json.loads(output.getvalue())["dispatch"])
                device.assert_not_called()

    def test_cli_rejects_empty_or_above_ceiling_budget_before_device_access(self):
        for budget in (0, -1, 17):
            with self.subTest(budget=budget), patch.object(native, "ADBRunner") as device:
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                    native.main([
                        "--adb", "unused-adb", "--serial", "127.0.0.1:5555",
                        "--post-flee-home-only", "--max-total-inputs", str(budget),
                    ])
                self.assertEqual(raised.exception.code, 2)
                device.assert_not_called()


class DefeatRecognitionTests(unittest.TestCase):
    def test_startup_routes_known_defeat_without_granting_input_or_allowing_other_flows(self):
        image = DEFEAT.read_bytes()
        plan = classify_startup_frame(delivery.FLOW_ID, image)
        self.assertEqual(plan.status, "route_owned")
        self.assertFalse(plan.input_authority)
        other = classify_startup_frame("SUPPLY-DEPOT-BLUESTACKS-INTEGRATION", image)
        self.assertEqual(other.status, "blocked")
        self.assertFalse(other.input_authority)

    def test_retained_defeat_binds_continue_but_warning_blocks(self):
        self.assertEqual(native._bind_ultimate_defeat_continue(read_frame(DEFEAT)),
                         (270, 1212, 530, 1270))
        self.assertIsNone(native._bind_ultimate_defeat_continue(read_frame(WARNING)))

    def test_each_required_visible_feature_is_necessary(self):
        original = read_frame(DEFEAT)
        # Blank one visible feature at a time, retaining the rest of the frame.
        for name, (x0, y0, x1, y1) in {
            "lose": (185, 65, 610, 200),
            "improve_might": (285, 292, 520, 330),
            "tap_to_continue": (275, 1220, 525, 1270),
        }.items():
            with self.subTest(missing=name):
                frame = original.copy()
                frame[y0:y1, x0:x1] = 0
                self.assertIsNone(native._bind_ultimate_defeat_continue(frame))


def failed_flee_receipt(session):
    """Build a disposable journal from portable visual fixtures, with no device input."""
    frames = session / "runtime" / "frames"
    frames.mkdir(parents=True)
    rows = []
    for ordinal, (label, fixture) in enumerate((
        ("flee-warning-resume-source", WARNING),
        ("flee-confirmed-successor-01", DEFEAT),
        ("flee-confirmed-successor-02", DEFEAT),
    ), 1):
        frame = read_frame(fixture).copy()
        # Distinct captures keep independent paths and digest evidence.
        frame[0, 0] = ordinal
        path = frames / f"{ordinal:04d}-{label}.png"
        if not cv2.imwrite(str(path), frame):
            raise AssertionError("could not write test frame")
        rows.append({"type": "capture", "label": label, "filename_component": label,
                     "path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "captured_monotonic": float(ordinal),
                     "timestamp": f"2026-11-01T03:17:0{ordinal}+00:00"})
    dispatch = {"type": "dispatch", "target_identity": "tap_flee", "execute": True,
                "source_sha256": rows[0]["sha256"], "action_key": "flee-once",
                "action_class": "navigation", "consequential": True,
                "point": [559, 668], "target_roi": [436, 628, 682, 708],
                "timestamp": "2026-11-01T03:17:01.5+00:00"}
    events = [rows[0], dispatch, *rows[1:]]
    result = {"flow_id": delivery.FLOW_ID, "reset_identity": RESET, "session": str(session.resolve()),
              "status": "blocked_fail_closed", "terminal": "blocked_fail_closed", "dispatch": False,
              "reason": "Flee completion not positively recognized", "input_count": 1,
              "navigation_input_count": 1, "navigation_only": False, "home_normalization": None,
              "flee_action_key": "flee-once", "completed_actions": []}
    (session / "result.json").write_text(json.dumps(result), encoding="utf-8")
    wrapper = {"flow_id": delivery.FLOW_ID, "serial": pnsctl.BLUESTACKS_SERIAL,
               "native_width": 800, "native_height": 1280, "ultimate_challenge_result": result}
    (session / "flow-delivery-result.json").write_text(json.dumps(wrapper), encoding="utf-8")
    for name in ("events.jsonl", "ledger.jsonl", "journal.jsonl", "capability-audit.jsonl"):
        (session / name).write_text('{"type":"retained"}\n', encoding="utf-8")
    write_events(session, events)
    return result, events


def write_events(session, events):
    (session / "runtime" / "events.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in events), encoding="utf-8")


class DefeatReceiptTests(unittest.TestCase):
    def setUp(self):
        clock = SimpleNamespace(fromisoformat=datetime.fromisoformat,
            now=lambda _tz: datetime(2026, 11, 1, 4, tzinfo=timezone.utc))
        scope = patch.object(delivery, "datetime", clock)
        scope.start()
        self.addCleanup(scope.stop)

    def test_service_retains_known_defeat_effect_but_rejects_warning_as_successor(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "prior"
            _result, events = failed_flee_receipt(session)
            events.append({"type": "reconcile", "action_key": "flee-once", "status": "confirmed",
                           "post_sha256": events[-1]["sha256"]})
            write_events(session, events)
            runtime = SimpleNamespace(session=session, events=session / "runtime/events.jsonl")
            with patch.object(native, "_recognize_ultimate_main", return_value=None):
                proof = service._current_flee_proof(runtime, native)
                self.assertEqual(proof["action"], "tap_flee")
                self.assertEqual(proof["post_sha256"], events[-1]["post_sha256"])
                events[-1]["post_sha256"] = events[0]["sha256"]
                write_events(session, events)
                with self.assertRaises(ValueError):
                    service._current_flee_proof(runtime, native)

    def test_confirmed_flee_proof_does_not_fall_back_after_metadata_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "confirmed"
            recovery_helpers.flee_proof(session)
            recovery = delivery._validated_flee_recovery(session, recovery_helpers.RESET)
            self.assertEqual(recovery["session_directory"], str(session.resolve()))
            wrapper_path = session / "flow-delivery-result.json"
            wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
            wrapper["native_width"] = 720
            wrapper_path.write_text(json.dumps(wrapper), encoding="utf-8")
            with self.assertRaises(pnsctl.OperatorError):
                delivery._validated_flee_recovery(session, recovery_helpers.RESET)

    def test_failed_one_flee_receipt_requires_two_retained_defeat_successors(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "prior"
            failed_flee_receipt(session)
            recovery = delivery._validated_flee_recovery(session, RESET)
            self.assertEqual(recovery["recovery_kind"], "defeat_after_flee")
            self.assertEqual(recovery["session_directory"], str(session.resolve()))

    def test_corrupted_or_ambiguous_receipt_cannot_authorize_recovery(self):
        for fault in ("duplicate_flee", "missing_successor", "foreign_frame", "tampered_frame",
                      "pre_dispatch_successor", "future_capture", "unaccounted_input", "unknown_event", "wrong_action_key", "wrong_reset"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                session = Path(directory) / "prior"
                _result, events = failed_flee_receipt(session)
                reset = RESET
                if fault == "duplicate_flee":
                    events.append(dict(events[1]))
                elif fault == "missing_successor":
                    events.pop()
                elif fault == "foreign_frame":
                    events[-1]["path"] = str(DEFEAT.resolve())
                elif fault == "tampered_frame":
                    Path(events[-1]["path"]).write_bytes(b"not the retained frame")
                elif fault == "pre_dispatch_successor":
                    events[2]["captured_monotonic"] = 0.5
                elif fault == "future_capture":
                    events[-1]["timestamp"] = "2099-01-01T00:00:00+00:00"
                elif fault == "unaccounted_input":
                    events.append({**events[1], "action_key": "extra", "target_identity": "other-control"})
                elif fault == "unknown_event":
                    events.append({"type": "unknown_input_record"})
                elif fault == "wrong_action_key":
                    events[1]["action_key"] = "foreign-key"
                else:
                    reset = "game-day-2026-10-31"
                write_events(session, events)
                with self.assertRaises(pnsctl.OperatorError):
                    delivery._validated_flee_recovery(session, reset)


class DefeatRouteTests(unittest.TestCase):
    def run_route(self, root, frames, runtime_type=None):
        session = root / "session"
        (session / "frames").mkdir(parents=True)
        runtime_class = runtime_type or helpers.UltimateCampaignExitRecoveryTests._Runtime
        runtime = runtime_class(root / "fake-runtime", frames)
        def main(frame):
            return (300, 1170, 500, 1260) if int(frame[0, 0, 0]) == 91 else None
        def campaign(frame):
            return int(frame[0, 0, 0]) == 92
        def home(frame):
            return int(frame[0, 0, 0]) == 93
        with patch.object(native, "_recognize_ultimate_main", side_effect=main), \
                patch.object(native, "_campaign_context_recognized", side_effect=campaign), \
                patch.object(native, "_home_nav_terminal", side_effect=home), \
                patch.object(native.campaign_atlas_vision, "measured_survey_target",
                             return_value=((715, 970, 767, 1024), 0.99)), \
                patch.object(native.time, "sleep", return_value=None):
            result = native._run_post_flee_home_route(
                runner=runtime.runner, session=session, events=session / "events.jsonl",
                reset_identity=RESET, post_input_delay=0, runtime=runtime)
        return runtime, result

    def test_continue_reaches_verified_home_without_new_flee_or_challenge(self):
        defeat = read_frame(DEFEAT)
        main, campaign, home = (np.full((1280, 800, 3), shade, dtype=np.uint8)
                                for shade in (91, 92, 93))
        with tempfile.TemporaryDirectory() as directory:
            runtime, (terminal, detail) = self.run_route(
                Path(directory), [defeat, defeat, main, main, campaign, campaign, home])
        self.assertEqual(terminal, native.TERMINAL_COMPLETE_FOR_RESET)
        self.assertTrue(detail["home_nav_recognized"])
        self.assertEqual([tap["target_identity"] for tap in runtime.taps],
                         ["ultimate-defeat-continue", "campaign-exit-base"])
        self.assertEqual(runtime.taps[0]["target_roi"], (270, 1212, 530, 1270))
        self.assertEqual([back["target_identity"] for back in runtime.backs], ["ultimate-challenge-back"])
        self.assertEqual(runtime.input_count, 3)

    def test_unexpected_successor_or_stop_after_continue_never_retries(self):
        base = helpers.UltimateCampaignExitRecoveryTests._Runtime
        class StopAfterContinue(base):
            def tap(self, source, **kwargs):
                super().tap(source, **kwargs)
                raise RuntimeError("STOP_REQUESTED")
        defeat = read_frame(DEFEAT)
        unknown = np.zeros((1280, 800, 3), dtype=np.uint8)
        for name, runtime_type in (("unexpected", base), ("stop", StopAfterContinue)):
            with self.subTest(case=name), tempfile.TemporaryDirectory() as directory:
                runtime, (terminal, _detail) = self.run_route(
                    Path(directory), [defeat, defeat, unknown], runtime_type)
                self.assertEqual(terminal, native.TERMINAL_BLOCKED)
                self.assertEqual([tap["target_identity"] for tap in runtime.taps], ["ultimate-defeat-continue"])
                self.assertEqual(runtime.backs, [])
                self.assertEqual(runtime.input_count, 1)

    def test_unaccounted_continue_transport_cannot_advance_to_back(self):
        base = helpers.UltimateCampaignExitRecoveryTests._Runtime
        class UnaccountedContinue(base):
            def tap(self, source, **kwargs):
                self.taps.append({"source": source, **kwargs})
        defeat = read_frame(DEFEAT)
        main = np.full((1280, 800, 3), 91, dtype=np.uint8)
        with tempfile.TemporaryDirectory() as directory:
            runtime, (terminal, _detail) = self.run_route(
                Path(directory), [defeat, defeat, main, main], UnaccountedContinue)
        self.assertEqual(terminal, native.TERMINAL_BLOCKED)
        self.assertEqual(len(runtime.taps), 1)
        self.assertEqual(runtime.backs, [])
