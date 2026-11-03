from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import flow_delivery_ultimate_challenge_bluestacks as delivery
from scripts import navigation_development_boundary as boundary
from scripts import pnsctl
from scripts.navigation_development_boundary import DevelopmentInitialObservation, DevelopmentSession
from tasks.ultimate_challenge_daily import (
    COMPLETION_UNKNOWN, TERMINAL_BLOCKED, empty_reset_window_state,
    evaluate_already_completed, load_reset_window_state, record_pending_home,
    save_reset_window_state,
)
from tasks.runtime_identity import BLUESTACKS_SERIAL


RESET = "game-day-2026-10-29"
ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "tests/fixtures/nova_praise_preflight/zoomed-home-a.png"


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


class UltimateRecoveryTests(unittest.TestCase):
    @contextmanager
    def runtime(self, root, state_path):
        with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
            with DevelopmentSession(owner=f"pnsctl-development-session:{delivery.FLOW_ID}",
                                    invocation_id=root.name, session_directory=root / "outer", max_inputs=16) as session:
                data = HOME.read_bytes()
                (session.session_directory / "source.png").write_bytes(data)
                digest = hashlib.sha256(data).hexdigest()
                initial = DevelopmentInitialObservation({"frame_sha256": digest}, digest, frame_path="source.png", invocation_id=session.invocation_id)
                session.set_initial_observation(initial)
                lease = {"owner": session.owner, "runtime_ownership_state": "held", "max_inputs": 16,
                         "development_session": session, "initial_observation": initial, "initial_frame_sha256": digest}
                with patch.object(delivery, "_reset_window_state_path", return_value=state_path), \
                     patch.object(delivery, "_current_reset_identity", return_value=RESET), \
                     patch.object(pnsctl, "BLUESTACKS_ARTIFACT_ROOT", root / "artifacts"):
                    yield lease

    def child(self, command, **_kwargs):
        output = Path(command[command.index("--output-directory") + 1]) / "child"
        if "--daily" in command:
            flee_proof(output)
            return SimpleNamespace(returncode=3, stdout="", stderr="Home exit blocked")
        self.assertIn("--post-flee-home-only", command)
        self.assertNotIn("--reset-state-path", command)
        output.mkdir(parents=True)
        frames = output / "frames"
        frames.mkdir()
        (frames / "home.png").write_bytes(HOME.read_bytes())
        result = {"flow_id": delivery.FLOW_ID, "reset_identity": RESET, "terminal": "complete_for_reset",
                  "input_count": 0, "home_nav_recognized": True, "home_frame": "frames/home.png",
                  "home_frame_sha256": hashlib.sha256(HOME.read_bytes()).hexdigest(), "completed_actions": []}
        write_result(output, result, [])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def test_failed_home_records_pending_and_default_resumes_without_another_flee(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "reset.json"
            commands = []
            def child(command, **kwargs):
                commands.append(command)
                return self.child(command, **kwargs)
            with self.runtime(root / "first", state_path) as lease, patch.object(delivery.subprocess, "run", side_effect=child):
                first = json.loads(delivery.run_ultimate_challenge_daily({"development_session": True, "active_flow_id": delivery.FLOW_ID}, lease))
            self.assertEqual(first["status"], "effect_reconciliation_required")
            pending = load_reset_window_state(state_path)
            self.assertEqual(pending.completion_state, COMPLETION_UNKNOWN)
            self.assertEqual(evaluate_already_completed(pending, current_reset_identity=RESET).terminal, TERMINAL_BLOCKED)
            with self.runtime(root / "second", state_path) as lease, patch.object(delivery.subprocess, "run", side_effect=child):
                recovered = json.loads(delivery.run_ultimate_challenge_daily({"development_session": True, "active_flow_id": delivery.FLOW_ID}, lease))
            self.assertEqual(recovered["status"], "completed")
            self.assertEqual(recovered["proof_topology"], "composite")
            final_dir = Path(recovered["session_directory"])
            result = json.loads((final_dir / "flow-delivery-result.json").read_text())
            self.assertEqual(result["new_flee_transport_count"], 0)
            verdict = delivery.verify_ultimate_challenge_daily({"result": result, "session_directory": str(final_dir)}, {}, {})
            self.assertEqual(verdict["status"], "verified")
            self.assertTrue(verdict["terminal_recovery_verified"])
            done = load_reset_window_state(state_path)
            self.assertIsNone(done.pending_home_session)
            self.assertEqual(done.last_success_reset_identity, RESET)
            self.assertIn("--daily", commands[0])
            self.assertIn("--post-flee-home-only", commands[1])

    def test_explicit_recovery_adopts_existing_confirmed_flee(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prior = root / "prior"
            flee_proof(prior)
            with self.runtime(root / "recovery", root / "reset.json") as lease, patch.object(delivery.subprocess, "run", side_effect=self.child) as child:
                lease.update(recovery_only=True, recovery_session=str(prior))
                result = json.loads(delivery.run_ultimate_challenge_daily({"development_session": True, "active_flow_id": delivery.FLOW_ID}, lease))
            self.assertEqual(result["status"], "completed")
            child.assert_called_once()
            self.assertIn("--post-flee-home-only", child.call_args.args[0])

    def test_bad_prior_or_pending_proof_blocks_before_any_child(self):
        for mutation in ("reset", "profile", "unknown", "corrupt", "digest", "state_reset"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                prior = root / "prior"
                result = flee_proof(prior)
                proof_hash = hashlib.sha256((prior / "result.json").read_bytes()).hexdigest()
                if mutation == "corrupt":
                    (prior / "frames/before.png").write_bytes(b"broken")
                elif mutation == "unknown":
                    path = prior / "runtime/events.jsonl"
                    path.write_text(path.read_text().replace('"confirmed"', '"unresolved"'))
                elif mutation in {"reset", "profile"}:
                    path = prior / "flow-delivery-result.json"
                    wrapper = json.loads(path.read_text())
                    if mutation == "profile":
                        wrapper["native_width"] = 720
                    else:
                        result["reset_identity"] = "game-day-2026-10-28"
                        (prior / "result.json").write_text(json.dumps(result))
                        wrapper["ultimate_challenge_result"] = result
                    path.write_text(json.dumps(wrapper))
                state_path = root / "reset.json"
                pending = record_pending_home(empty_reset_window_state(), reset_identity="game-day-2026-10-28" if mutation == "state_reset" else RESET, session_directory=str(prior),
                                              result_sha256="0" * 64 if mutation == "digest" else proof_hash)
                save_reset_window_state(state_path, pending)
                with self.runtime(root / "attempt", state_path) as lease, patch.object(delivery.subprocess, "run") as child:
                    with self.assertRaises(pnsctl.OperatorError):
                        delivery.run_ultimate_challenge_daily({"development_session": True, "active_flow_id": delivery.FLOW_ID}, lease)
                    child.assert_not_called()

    def test_missing_recovery_reference_and_malformed_pending_stop_before_runtime(self):
        with patch.object(pnsctl, "_development_runtime_observation") as observe:
            with self.assertRaisesRegex(pnsctl.OperatorError, "requires --recovery-session"):
                pnsctl.development_session_run_flow(delivery.FLOW_ID, live=True, yes=True,
                                                   max_inputs=16, recovery_only=True)
            observe.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "reset.json"
            raw = {**empty_reset_window_state().__dict__, "completion_state": "unknown", "pending_home_session": "missing"}
            state_path.write_text(json.dumps(raw))
            with self.runtime(root / "attempt", state_path) as lease, patch.object(delivery.subprocess, "run") as child:
                with self.assertRaisesRegex(ValueError, "invalid.*pending Home"):
                    delivery.run_ultimate_challenge_daily({"development_session": True, "active_flow_id": delivery.FLOW_ID}, lease)
                child.assert_not_called()


if __name__ == "__main__":
    unittest.main()
