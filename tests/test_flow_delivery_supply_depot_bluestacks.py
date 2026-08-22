from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

from scripts import flow_delivery_supply_depot_bluestacks as delivery
from scripts import pnsctl
from scripts import supply_depot_free_canary as canary
import scripts.navigation_development_boundary as boundary
from scripts.navigation_development_boundary import (
    DevelopmentInitialObservation,
    DevelopmentSession,
)
from scripts.supply_depot_free_canary import (
    exhausted_free_state,
    select_free_food_control,
)


def _control(kind: str, *, free: bool):
    return SimpleNamespace(
        reward_kind=kind,
        state="available_free" if free else "paid_or_purchase",
        zero_cost=free,
        roi=(10, 1100, 190, 1270),
    )


def _recognition(*, attempts: int, free: bool):
    return SimpleNamespace(
        recognized=True,
        state="available" if free else "paid_or_purchase",
        overlay=False,
        premium_or_purchase_visible=not free,
        ambiguity="none",
        daily_free_attempts=attempts,
        controls=tuple(
            _control(kind, free=free) for kind in ("food", "wood", "steel", "gas")
        ),
    )


class SupplyDepotFlowDeliveryTests(unittest.TestCase):
    def test_selects_only_exact_free_food_control(self):
        recognition = _recognition(attempts=9, free=True)
        selected = select_free_food_control(recognition)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.reward_kind, "food")

        recognition.controls = recognition.controls[1:]
        self.assertIsNone(select_free_food_control(recognition))

    def test_exhausted_requires_zero_and_every_free_control_absent(self):
        self.assertTrue(exhausted_free_state(_recognition(attempts=0, free=False)))
        self.assertFalse(exhausted_free_state(_recognition(attempts=1, free=True)))

    def test_home_zoom_builds_scrcpy_transport_in_runtime_session(self):
        runtime = SimpleNamespace(session=Path("runtime-session"))
        adb = Path(r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe")
        pnsctl = SimpleNamespace(
            BLUESTACKS_ADB=adb,
            BLUESTACKS_SERIAL="emulator-5554",
        )
        with (
            patch.object(canary, "_pnsctl", return_value=pnsctl),
            patch.object(
                canary,
                "ScrcpyMotionEventZoomTransport",
                return_value=object(),
            ) as constructor,
        ):
            transport = canary._build_home_zoom_transport(runtime)

        self.assertIsNotNone(transport)
        constructor.assert_called_once_with(
            adb=str(adb),
            serial="emulator-5554",
            evidence_directory=runtime.session / "scrcpy-zoom",
        )

    def test_home_zoom_dispatches_scrcpy_callable_through_runtime(self):
        calls = []

        class Runtime:
            def dispatch_external_zoom(self, source, *, action_key, transport):
                calls.append((source, action_key, transport))
                transport()

        class ScrcpyTransport:
            def __init__(self):
                self.calls = 0

            def zoom_out_once(self):
                self.calls += 1

        source = SimpleNamespace(frame=object(), sha256="a" * 64)
        runtime = Runtime()
        transport = ScrcpyTransport()
        with patch.object(
            canary,
            "recognize_home_nav",
            return_value=SimpleNamespace(is_home=True),
        ):
            canary._dispatch_home_zoom_out(
                runtime,
                source,
                zoom_transport=transport,
            )

        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0][0], source)
        self.assertEqual(calls[0][1], "supply-depot-home-zoom-out:aaaaaaaaaaaa")
        self.assertIs(calls[0][2].__self__, transport)
        self.assertIs(calls[0][2].__func__, ScrcpyTransport.zoom_out_once)
        self.assertEqual(transport.calls, 1)

    def test_result_requires_zero_attempts_and_terminal_home(self):
        accepted = delivery._payload(
            {
                "status": "completed",
                "free_attempts_after": 0,
                "terminal_home_verified": True,
            },
            session_directory="session",
            input_count=4,
            hold_calls=1,
            maximum=10,
        )
        self.assertEqual(accepted["status"], "completed")
        self.assertEqual(accepted["hold_transport_calls"], 1)

        unresolved = delivery._payload(
            {
                "status": "completed",
                "free_attempts_after": 1,
                "terminal_home_verified": True,
            },
            session_directory="session",
            input_count=4,
            hold_calls=1,
            maximum=10,
        )
        self.assertEqual(unresolved["status"], "effect_reconciliation_required")
        self.assertTrue(unresolved["identical_retry_denied"])

    def test_live_route_requires_exact_session_observation_and_retained_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = root / "runtime"
            child.mkdir()
            events = [
                {"type": "dispatch", "execute": True, "action_key": "open-supply-depot:1"},
                {"type": "dispatch", "execute": True, "action_key": "open-supply-depot-screen:1"},
                {"type": "dispatch", "execute": True, "action_key": "supply-depot-free-hold:5:1"},
                {"type": "dispatch", "execute": True, "action_key": "supply-depot-visible-exit:1"},
            ]
            (child / "events.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in events), encoding="utf-8"
            )
            initial_bytes = b"typed-supply-initial"
            digest = hashlib.sha256(initial_bytes).hexdigest()
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with DevelopmentSession(
                    owner=f"pnsctl-development-session:{delivery.FLOW_ID}",
                    invocation_id="supply-continuous",
                    session_directory=root / "outer",
                    max_inputs=delivery.MAX_INPUTS,
                ) as session:
                    (session.session_directory / "source.png").write_bytes(initial_bytes)
                    initial = DevelopmentInitialObservation(
                        {"frame_sha256": digest},
                        digest,
                        frame_path="source.png",
                        invocation_id=session.invocation_id,
                    )
                    session.set_initial_observation(initial)
                    session.adopt_retained_transport_count(4, source="test-events")
                    lease = {
                        "owner": session.owner,
                        "max_inputs": delivery.MAX_INPUTS,
                        "development_session": session,
                        "initial_observation": initial,
                        "initial_frame_sha256": digest,
                    }
                    with (
                        patch.object(
                            delivery.LocalBlueStacksRuntime,
                            "connect",
                            return_value=SimpleNamespace(session=child),
                        ),
                        patch.object(
                            canary,
                            "run",
                            return_value={
                                "status": "completed",
                                "free_attempts_before": 5,
                                "free_attempts_after": 0,
                                "terminal_home_verified": True,
                            },
                        ),
                    ):
                        result = json.loads(delivery.run_supply_depot({}, lease, live=True))
                    self.assertEqual(result["status"], "completed")
                    self.assertEqual(result["input_count"], 4)
                    self.assertEqual(result["hold_transport_calls"], 1)
                    self.assertEqual(result["proof_topology"], "continuous")
                    self.assertEqual(result["initial_frame_sha256"], digest)
                    self.assertEqual(result["causal_trace_count"], 1)
                    self.assertTrue(result["causal_trace"]["read_only"])
                    self.assertFalse(result["causal_trace"]["input_authority"])
                    self.assertEqual(session.causal_trace, result["causal_trace"])

            with patch.object(delivery.LocalBlueStacksRuntime, "connect") as connect:
                with self.assertRaises(pnsctl.OperatorError):
                    delivery.run_supply_depot(
                        {},
                        {
                            "max_inputs": delivery.MAX_INPUTS,
                            "development_session": SimpleNamespace(run_action=lambda: None),
                        },
                        live=True,
                    )
                connect.assert_not_called()

    def test_registration_is_fixed_and_scheduler_stays_off(self):
        runners = {}
        validators = {}
        recoveries = {}
        delivery.register(runners, validators, recoveries)
        self.assertIs(runners[delivery.RUNNER_ID], delivery.run_supply_depot)
        self.assertIs(
            validators[delivery.VALIDATOR_ID], delivery.verify_supply_depot
        )
        self.assertIs(
            recoveries[delivery.RECOVERY_ID], delivery.recover_supply_depot
        )

        self.assertEqual(
            delivery.verify_supply_depot(
                {"result": {}, "session_directory": "session"}, {}, {}
            )["status"],
            "evidence_required",
        )

    def test_completed_artifact_passes_operational_generic_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / ".local-captures" / "supply-depot-completed"
            (session / "frames").mkdir(parents=True)
            (session / "frames" / "terminal.png").write_bytes(b"native-frame")
            initial_bytes = b"typed-initial"
            (session / "frames" / "initial.png").write_bytes(initial_bytes)
            digest = hashlib.sha256(initial_bytes).hexdigest()
            events = [
                {"type": "dispatch", "execute": True, "action_key": "open-supply-depot:1"},
                {"type": "dispatch", "execute": True, "action_key": "supply-depot-free-hold:5:1"},
                {"type": "dispatch", "execute": True, "action_key": "supply-depot-visible-exit:1"},
            ]
            (session / "events.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in events), encoding="utf-8"
            )
            trace = {
                "trace_count": 1,
                "read_only": True,
                "input_authority": False,
                "proof_topology": "continuous",
                "initial_frame_sha256": digest,
                "transport_count": 3,
                "hold_transport_calls": 1,
            }
            (session / "causal-trace.json").write_text(
                json.dumps(trace) + "\n", encoding="utf-8"
            )
            delivery._write_delivery_result(
                session,
                {
                    "status": "completed",
                    "input_count": 3,
                    "max_inputs": 10,
                    "hold_transport_calls": 1,
                    "free_attempts_after": 0,
                    "terminal_home_verified": True,
                    "proof_topology": "continuous",
                    "initial_observation": {
                        "frame_sha256": digest,
                        "frame_path": "frames/initial.png",
                        "invocation_id": "test-supply",
                    },
                    "initial_frame_sha256": digest,
                    "causal_trace_count": 1,
                    "causal_trace": trace,
                    "effect_reconciliation_required": False,
                    "production_registration": "NOT_REGISTERED",
                    "scheduler_enabled": False,
                },
                lease={"owner": "test-owner"},
            )
            with (
                patch.object(pnsctl, "REPO_ROOT", root),
                patch.object(
                    pnsctl,
                    "_load_flow_delivery_state",
                    side_effect=pnsctl.OperatorError("no active delivery"),
                ),
            ):
                verdict = json.loads(pnsctl.bluestacks_verify_flow(session))
            self.assertEqual(verdict["status"], "verified")
            self.assertEqual(verdict["flow_id"], delivery.FLOW_ID)


if __name__ == "__main__":
    unittest.main()
