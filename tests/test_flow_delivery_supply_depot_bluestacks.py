from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import flow_delivery_supply_depot_bluestacks as delivery
from scripts import supply_depot_free_canary as canary
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
        self.assertEqual(unresolved["status"], "unresolved")

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

        verified = delivery.verify_supply_depot(
            {
                "result": {
                    "status": "completed",
                    "free_attempts_after": 0,
                    "terminal_home_verified": True,
                    "hold_transport_calls": 1,
                },
                "session_directory": "session",
            },
            {},
            {},
        )
        self.assertEqual(verified["status"], "verified")
        self.assertEqual(verified["production_registration"], "NOT_REGISTERED")
        self.assertFalse(verified["scheduler_enabled"])


if __name__ == "__main__":
    unittest.main()
