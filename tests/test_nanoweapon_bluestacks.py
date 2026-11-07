from __future__ import annotations

from pathlib import Path
from itertools import count
import hashlib
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

from safe_action_core import SafetyStore
from scripts import nano_material_production_bluestacks as production
from scripts import nanoweapon_bluestacks as route
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID


_STATE_CODE = {
    "production_active": 1,
    "production_idle": 9,
    "craft_idle": 2,
    "craft_claim": 3,
    "craft_active": 4,
    "craft_unknown": 5,
    "craft_partial_unspent": 6,
    "craft_shortage": 7,
    "home": 8,
}


def _ocr_rows(state: str, balance: int, craft_timer: int):
    if state == "home":
        return [("Home", 80, 100), ("Build", 180, 100), ("Research", 250, 100)]
    if state in {"production_active", "production_idle"}:
        rows = [
            ("Nanoweapon", 60, 100),
            ("Material Production", 145, 250),
            ("Craft Weapon", 205, 310),
            ("Production Slot 1 of 1", 300, 250),
            ("Duration 6 hours", 350, 250),
            ("Cost 0", 400, 250),
            ("No other costs", 430, 250),
        ]
        if state == "production_active":
            rows.extend((("Production Active", 500, 100), ("Timer 05:59:00", 610, 100)))
        else:
            rows.extend((("Production Idle", 500, 100), ("Timer 00:00:00", 610, 100), ("Start", 700, 500)))
        return rows
    if state == "craft_unknown":
        return [
            ("Nanoweapon", 60, 100),
            ("Material Production", 145, 100),
            ("Craft Weapon", 185, 310),
        ]

    rows = [
        ("Nanoweapon", 60, 100),
        ("Material Production", 145, 100),
        ("Craft Weapon", 185, 310),
        ("Normal Craft Selected", 245, 100),
        ("Nano Parts " + str(balance), 155, 100),
        ("Hydra", 430, 100),
        ("Cost 100 Nano Parts", 650, 100),
        ("Duration 12 hours", 700, 100),
        ("Quantity 1", 200, 100),
    ]
    if state == "craft_claim":
        rows.extend((("Craft Complete", 810, 100), ("Claim", 880, 500)))
    elif state in {"craft_active", "craft_partial_unspent"}:
        hours, remainder = divmod(craft_timer, 3600)
        minutes, seconds = divmod(remainder, 60)
        rows.append((f"Craft Timer {hours:02d}:{minutes:02d}:{seconds:02d}", 620, 100))
    else:
        rows.extend((("Craft Timer 00:00:00", 620, 100), ("Craft", 850, 500)))
    return rows


def _fake_tesseract(frame, *, timeout, config):
    del timeout, config
    state = next(name for name, value in _STATE_CODE.items() if value == int(frame[0, 0, 0]))
    balance = int(frame[0, 1, 0]) + int(frame[0, 2, 0]) * 256
    craft_timer = int(frame[0, 3, 0]) + int(frame[0, 4, 0]) * 256 + int(frame[0, 5, 0]) * 65536
    rows = _ocr_rows(state, balance, craft_timer)
    result = {
        key: []
        for key in ("text", "left", "top", "width", "height", "conf", "block_num", "par_num", "line_num")
    }
    for index, (text, y, x) in enumerate(rows):
        result["text"].append(text)
        result["left"].append(x)
        result["top"].append(y)
        result["width"].append(max(24, min(500, len(text) * 9)))
        result["height"].append(20)
        result["conf"].append(95)
        result["block_num"].append(1)
        result["par_num"].append(1)
        result["line_num"].append(index + 1)
    return result


class _Capture:
    def __init__(self, frame, digest, path, captured_monotonic, ordinal):
        self.frame = frame
        self.sha256 = digest
        self.path = path
        self.captured_monotonic = captured_monotonic
        self.ordinal = ordinal


class _Runtime:
    def __init__(
        self,
        session_directory: Path,
        *,
        balance: int,
        craft_state: str,
        production_state: str = "production_active",
        partial_start: bool = False,
        unknown_after_claim: bool = False,
    ):
        self.session = f"fake-runtime-{id(self)}"
        self.session_directory = session_directory
        self.state = production_state
        self.balance = balance
        self.craft_state = craft_state
        self.craft_timer = 43140 if craft_state == "craft_active" else 0
        self.partial_start = partial_start
        self.unknown_after_claim = unknown_after_claim
        self.input_count = 0
        self.max_inputs = route.MAX_INPUTS
        self.ordinal = 0
        self.captures: dict[str, _Capture] = {}
        self.actions: list[tuple[str, str, bool]] = []
        self.reconciliations: list[tuple[str, str]] = []

    def capture(self, label: str):
        self.ordinal += 1
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        frame[0, 0, 0] = _STATE_CODE[self.state]
        frame[0, 1, 0] = self.balance & 0xFF
        frame[0, 2, 0] = (self.balance >> 8) & 0xFF
        frame[0, 3, 0] = self.craft_timer & 0xFF
        frame[0, 4, 0] = (self.craft_timer >> 8) & 0xFF
        frame[0, 5, 0] = (self.craft_timer >> 16) & 0xFF
        if self.state == "craft_idle" and self.balance >= 100:
            # The OCR-bound Craft word is surrounded by an enabled orange CTA.
            frame[830:890, 456:589] = (0, 165, 255)
            frame[830:833, 456:589] = (0, 0, 0)
            frame[887:890, 456:589] = (0, 0, 0)
            frame[830:890, 456:459] = (0, 0, 0)
            frame[830:890, 586:589] = (0, 0, 0)
        digest = hashlib.sha256(frame.tobytes()).hexdigest()
        path = self.session_directory / "frames" / f"{self.ordinal:04d}-{label}.png"
        captured = _Capture(frame, digest, path, 100.0 + self.ordinal / 100.0, self.ordinal)
        self.captures[str(path)] = captured
        return captured

    def measure_foreground_package(self):
        return "com.global.ztmslg"

    def tap(self, _captured, *, target_identity, target_roi, action_key, action_class, consequential):
        del target_roi
        self.actions.append((str(action_class), str(action_key), bool(consequential)))
        self.input_count += 1
        if target_identity == "nanoweapon:material-production-tab":
            self.state = "production_active"
        elif target_identity == "nanoweapon:craft-weapon-tab":
            self.state = self.craft_state
        elif action_class == "START_NANO_MATERIAL_PRODUCTION":
            self.state = "production_active"
        elif action_class == "CLAIM_NANOWEAPON_COMPLETED":
            self.state = "craft_unknown" if self.unknown_after_claim else "craft_idle"
        elif action_class == "START_NORMAL_NANOWEAPON_CRAFT":
            if self.partial_start:
                self.state = "craft_partial_unspent"
                self.craft_timer = 43140
            else:
                self.balance -= 100
                self.state = "craft_active"
                self.craft_timer = 43140

    def press_key(self, _captured, *, key, action_key):
        self.actions.append((f"KEY:{key}", str(action_key), False))
        self.input_count += 1
        self.state = "home"

    def reconcile(self, action_key, status, _captured, _reason):
        self.reconciliations.append((str(action_key), str(status)))


class _Session:
    def __init__(self, runtime: _Runtime, owner: str, invocation_id: str):
        self.runtime = runtime
        self.owner = owner
        self.invocation_id = invocation_id
        self.session_directory = runtime.session_directory
        self.max_inputs = route.MAX_INPUTS
        self.input_count = 0
        self.initial_observation = None

    def observe(self, capture, *, label):
        return capture(label)

    def set_initial_observation(self, value):
        if self.initial_observation is not None:
            raise AssertionError("initial observation can only bind once")
        self.initial_observation = value

    def run_action(
        self,
        *,
        action_class,
        label,
        capture,
        authorize,
        dispatch,
        recognize,
        settled_successor,
        consequence_class,
    ):
        del action_class, consequence_class
        before = capture(f"{label}-before")
        admitted = authorize(before)
        if admitted is False:
            return SimpleNamespace(status="failed", state="unknown", before_sha256=before.sha256, after_sha256="")
        dispatch(before)
        self.input_count += 1
        after = capture(f"{label}-after")
        state = recognize(after)
        settled = settled_successor()
        state = recognize(settled)
        return SimpleNamespace(
            status="completed" if state != "unknown" else "failed",
            state=state,
            before_sha256=before.sha256,
            after_sha256=settled.sha256,
        )


class _Context:
    _invocations = count(1)

    def __init__(
        self,
        root: Path,
        *,
        balance: int = 250,
        craft_state: str = "craft_idle",
        production_state: str = "production_active",
        identity_reset: str = "game-day-2026-11-06",
        store: SafetyStore | None = None,
        partial_start: bool = False,
        unknown_after_claim: bool = False,
    ):
        self.runtime_profile_id = ACTIVE_RUNTIME_PROFILE_ID
        self.flow_id = route.FLOW_ID
        self.product_id = route.PRODUCT_ID
        self.product_revision = route.PRODUCT_REVISION
        self.occurrence_key = "NANOWEAPON-BLUESTACKS-INTEGRATION:daily_reset:game-day-2026-11-06"
        self.identity = SimpleNamespace(
            reset_id=identity_reset,
            account_id="account-1",
            server_id="server-1",
            runtime_scope="scope-1",
        )
        self.owner = "automation-service:nanoweapon"
        self.runtime = _Runtime(
            root,
            balance=balance,
            craft_state=craft_state,
            production_state=production_state,
            partial_start=partial_start,
            unknown_after_claim=unknown_after_claim,
        )
        self.invocation_id = f"smoke-{next(self._invocations)}"
        self.session = _Session(self.runtime, self.owner, self.invocation_id)
        self.action_store = store or SafetyStore(root / "action-store.sqlite")
        self._owns_store = store is None
        if self._owns_store:
            self.action_store.acquire_lease(self.owner, 1_793_923_200.0, 3600.0)
        self.max_inputs = route.MAX_INPUTS
        self.settle_seconds = 0.0
        self.runtime_input_lock = None
        self._utc = 1_793_923_200.0

    def close(self):
        if self._owns_store:
            self.action_store.close()

    def checkpoint(self):
        return None

    def validate_identity(self):
        return None

    def utc_clock(self):
        return self._utc

    def monotonic_clock(self):
        return 100.0 + self.runtime.ordinal / 100.0

    def is_clean_home(self, frame):
        return int(frame[0, 0, 0]) == _STATE_CODE["home"]

    def bind_initial_observation(self, captured):
        self.session.set_initial_observation(SimpleNamespace(frame_sha256=captured.sha256))

    def prepare_startup(self, **_kwargs):
        raise RuntimeError("smoke scenarios begin from the already-recognized production panel")

    def accounting(self):
        count = self.session.input_count
        return SimpleNamespace(
            input_count=count,
            session_input_count=count,
            runtime_input_count=self.runtime.input_count,
            verified=count == self.runtime.input_count,
        )

    def capture_reference(self, path, expected_sha256):
        captured = self.runtime.captures[str(path)]
        if captured.sha256 != expected_sha256:
            raise ValueError("captured Home digest changed")
        return captured.frame, SimpleNamespace(
            frame_path=f"frames/{Path(path).name}",
            frame_sha256=expected_sha256,
            observed_utc="2026-11-06T00:00:00Z",
            capture_ordinal=captured.ordinal,
        )


class NanoweaponNativeSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [
            mock.patch.object(production, "tesseract_data", _fake_tesseract),
            mock.patch.object(production, "_load_atlas", lambda _path: object()),
            mock.patch.object(production, "BlueStacksHomeLocalizer", _FakeHomeLocalizer),
            mock.patch.object(route, "tesseract_data", _fake_tesseract),
            mock.patch.object(route, "_overlay_clear", lambda _frame: True),
            mock.patch.object(route, "load_home_atlas", lambda _path: object()),
            mock.patch.object(route, "BlueStacksHomeLocalizer", _FakeHomeLocalizer),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()
        self.temp.cleanup()

    def _seed_previous_start(self, context, reset="game-day-2026-11-05"):
        previous = _Context(
            self.root, craft_state="craft_idle", identity_reset=reset,
            store=context.action_store,
        )
        result = route.run_nanoweapon_in_context(previous, occurrence_key=previous.occurrence_key)
        self.assertEqual(result["craft_start_transport_calls"], 1)
        return previous

    def test_same_visit_production_then_claim_and_exact_normal_start(self):
        context = _Context(
            self.root,
            craft_state="craft_claim",
            production_state="production_idle",
        )
        try:
            self._seed_previous_start(context)
            binding = route.create_service_binding(lambda **values: values)
            result = binding["driver"](context, {})
            consequential = [action for action in context.runtime.actions if action[2]]
            self.assertEqual(
                [action[0] for action in context.runtime.actions],
                [
                    "START_NANO_MATERIAL_PRODUCTION",
                    "navigation",
                    "CLAIM_NANOWEAPON_COMPLETED",
                    "START_NORMAL_NANOWEAPON_CRAFT",
                    "KEY:Escape",
                ],
            )
            self.assertEqual(
                [action[0] for action in consequential],
                [
                    "START_NANO_MATERIAL_PRODUCTION",
                    "CLAIM_NANOWEAPON_COMPLETED",
                    "START_NORMAL_NANOWEAPON_CRAFT",
                ],
            )
            production_actions = [
                action for action in consequential if action[0] == "START_NANO_MATERIAL_PRODUCTION"
            ]
            craft_actions = [
                action for action in consequential if action[0] != "START_NANO_MATERIAL_PRODUCTION"
            ]
            self.assertEqual(len(production_actions), 1)
            self.assertEqual(
                production_actions[0][1],
                f"{production.PRODUCT_ID}|{context.occurrence_key}|start",
            )
            self.assertIn(":claim-instance:game-day-2026-11-05:", craft_actions[0][1])
            self.assertIn(f":start:{context.identity.reset_id}:", craft_actions[1][1])
            self.assertEqual(result["native_occurrence_key"], context.occurrence_key)
            self.assertEqual(result["production_occurrence_key"], context.occurrence_key)
            self.assertEqual(
                result["production_target_identity"],
                production.NANO_MATERIAL_PRODUCTION_TARGET,
            )
            self.assertEqual(
                result["production_state_frame"]["frame_sha256"],
                result["production_state_observation_sha256"],
            )
            self.assertEqual(result["production_transport_calls"], 1)
            self.assertEqual(result["craft_claim_transport_calls"], 1)
            self.assertEqual(result["craft_start_transport_calls"], 1)
            self.assertEqual(result["craft_transport_calls"], 2)
            self.assertEqual(result["nanoweapon_dispatch_count"], 3)
            self.assertEqual(result["attempted_action_count"], 3)
            self.assertEqual(result["committed_action_count"], 3)
            self.assertTrue(result["prior_material_production_reconciled"])
            self.assertTrue(result["zero_resource_cost_confirmed"])
            self.assertEqual(result["production_duration_seconds"], 21600)
            craft_due = min(
                (int(context.utc_clock() // 86400) + 1) * 86400.0,
                context.utc_clock() + result["active_craft_timer_seconds_remaining"],
            )
            self.assertEqual(
                result["next_eligible_at"],
                min(result["production_next_eligible_at"], craft_due),
            )
            self.assertEqual(result["craft_duration_seconds"], 43200)
            self.assertEqual(result["precraft_nano_parts_balance"], 250)
            self.assertEqual(result["nano_parts_balance"], 150)
            self.assertEqual(result["due_reason"], "current_reset_start")
            self.assertTrue(result["terminal_home_verified"])
            self.assertEqual(result["terminal_home_state"], "HOME_BASE")
            self.assertTrue(result["accounting_verified"])
            self.assertEqual(result["session_input_count"], result["runtime_input_count"])
        finally:
            context.close()

    def test_confirmed_current_reset_start_survives_native_restart_without_replay(self):
        first = _Context(self.root, craft_state="craft_idle")
        try:
            initial = route.run_nanoweapon_in_context(first, occurrence_key=first.occurrence_key)
            self.assertEqual(initial["craft_start_transport_calls"], 1)
            starts_before = sum(action[0] == "START_NORMAL_NANOWEAPON_CRAFT" for action in first.runtime.actions)
            self.assertEqual(starts_before, 1)

            restarted = _Context(
                self.root,
                balance=150,
                craft_state="craft_active",
                store=first.action_store,
            )
            try:
                result = route.run_nanoweapon_in_context(restarted, occurrence_key=restarted.occurrence_key)
                self.assertEqual(result["status"], "deferred")
                self.assertEqual(result["due_reason"], "current_reset_start")
                self.assertEqual(result["craft_start_transport_calls"], 0)
                self.assertEqual(result["craft_claim_transport_calls"], 0)
                self.assertEqual(result["craft_transport_calls"], 0)
                self.assertEqual(result["nanoweapon_dispatch_count"], 0)
                self.assertTrue(result["craft_start_confirmed"])
                self.assertEqual(result["craft_start_reset_id"], restarted.identity.reset_id)
                self.assertEqual(result["starts_this_reset"], 1)
                self.assertEqual(result["craft_state"], "active")
                self.assertTrue(result["terminal_home_verified"])
                self.assertEqual(
                    sum(action[0] == "START_NORMAL_NANOWEAPON_CRAFT" for action in restarted.runtime.actions),
                    0,
                )
            finally:
                restarted.close()
        finally:
            first.close()

    def test_previous_reset_active_craft_uses_exact_observed_timer(self):
        previous = _Context(
            self.root,
            craft_state="craft_idle",
            identity_reset="game-day-2026-11-05",
        )
        try:
            prior = route.run_nanoweapon_in_context(previous, occurrence_key=previous.occurrence_key)
            self.assertEqual(prior["craft_start_transport_calls"], 1)
            current = _Context(
                self.root,
                balance=150,
                craft_state="craft_active",
                identity_reset="game-day-2026-11-06",
                store=previous.action_store,
            )
            try:
                result = route.run_nanoweapon_in_context(current, occurrence_key=current.occurrence_key)
                self.assertEqual(result["due_reason"], "previous_reset_active_timer")
                self.assertEqual(result["craft_start_reset_id"], "game-day-2026-11-05")
                self.assertEqual(result["starts_this_reset"], 0)
                self.assertEqual(result["craft_start_transport_calls"], 0)
                self.assertEqual(result["craft_claim_transport_calls"], 0)
                self.assertEqual(result["active_craft_timer_seconds_remaining"], 43140)
                self.assertEqual(
                    result["next_eligible_at"],
                    min(
                        result["production_next_eligible_at"],
                        current.utc_clock() + result["active_craft_timer_seconds_remaining"],
                    ),
                )
                self.assertEqual(result["craft_state"], "active")
                self.assertTrue(result["terminal_home_verified"])
            finally:
                current.close()
        finally:
            previous.close()

    def test_partial_start_successor_is_unresolved_and_restart_never_replays(self):
        first = _Context(self.root, craft_state="craft_idle", partial_start=True)
        try:
            partial = route.run_nanoweapon_in_context(first, occurrence_key=first.occurrence_key)
            self.assertEqual(partial["status"], "unresolved")
            self.assertIsNone(partial["next_eligible_at"])
            self.assertEqual(partial["craft_start_transport_calls"], 1)
            self.assertEqual(partial["craft_transport_calls"], 1)
            self.assertEqual(partial["attempted_action_count"], 1)
            self.assertEqual(partial["committed_action_count"], 0)
            self.assertTrue(partial["effect_reconciliation_required"])
            self.assertTrue(partial["identical_retry_denied"])
            self.assertEqual(
                sum(action[0] == "START_NORMAL_NANOWEAPON_CRAFT" for action in first.runtime.actions),
                1,
            )

            restarted = _Context(
                self.root,
                balance=250,
                craft_state="craft_idle",
                store=first.action_store,
            )
            try:
                retried = route.run_nanoweapon_in_context(restarted, occurrence_key=restarted.occurrence_key)
                self.assertEqual(retried["status"], "unresolved")
                self.assertEqual(retried["craft_start_transport_calls"], 0)
                self.assertEqual(retried["nanoweapon_dispatch_count"], 0)
                self.assertEqual(retried["attempted_action_count"], 0)
                self.assertEqual(retried["committed_action_count"], 0)
                self.assertTrue(retried["effect_reconciliation_required"])
                self.assertTrue(retried["identical_retry_denied"])
                self.assertFalse(any(action[0] == "START_NORMAL_NANOWEAPON_CRAFT" for action in restarted.runtime.actions))
            finally:
                restarted.close()
        finally:
            first.close()

    def test_unknown_claim_successor_stops_before_normal_start(self):
        context = _Context(self.root, craft_state="craft_claim", unknown_after_claim=True)
        try:
            self._seed_previous_start(context)
            result = route.run_nanoweapon_in_context(context, occurrence_key=context.occurrence_key)
            self.assertEqual(result["status"], "unresolved")
            self.assertIsNone(result["next_eligible_at"])
            self.assertEqual(result["craft_claim_transport_calls"], 1)
            self.assertEqual(result["craft_start_transport_calls"], 0)
            self.assertEqual(result["craft_transport_calls"], 1)
            self.assertEqual(result["attempted_action_count"], 1)
            self.assertEqual(result["committed_action_count"], 0)
            self.assertTrue(result["effect_reconciliation_required"])
            self.assertTrue(result["identical_retry_denied"])
            self.assertEqual(
                [action[0] for action in context.runtime.actions if action[2]],
                ["CLAIM_NANOWEAPON_COMPLETED"],
            )
            restarted = _Context(
                self.root, craft_state="craft_claim", store=context.action_store,
                identity_reset="game-day-2026-11-07",
            )
            retry = route.run_nanoweapon_in_context(restarted, occurrence_key=restarted.occurrence_key)
            self.assertEqual(retry["status"], "unresolved")
            self.assertEqual(retry["craft_claim_transport_calls"], 0)
            self.assertFalse(any(action[2] for action in restarted.runtime.actions))
        finally:
            context.close()

    def test_known_exact_parts_shortage_uses_fixed_observation_interval(self):
        context = _Context(self.root, balance=80, craft_state="craft_shortage")
        try:
            result = route.run_nanoweapon_in_context(context, occurrence_key=context.occurrence_key)
            self.assertEqual(result["status"], "deferred")
            self.assertEqual(result["due_reason"], "known_material_shortage")
            self.assertEqual(result["observation_interval_seconds"], 300)
            self.assertEqual(result["nano_parts_balance"], 80)
            self.assertEqual(result["craft_state"], "idle")
            self.assertEqual(result["craft_active_count"], 0)
            self.assertEqual(result["craft_transport_calls"], 0)
            self.assertEqual(result["nanoweapon_dispatch_count"], 0)
            self.assertEqual(result["next_eligible_at"], context.utc_clock() + 300)
            self.assertTrue(result["terminal_home_verified"])
        finally:
            context.close()

    def test_two_completions_in_one_reset_survive_database_reopen(self):
        first = _Context(self.root, craft_state="craft_claim")
        try:
            self._seed_previous_start(first)
            result = route.run_nanoweapon_in_context(first, occurrence_key=first.occurrence_key)
            self.assertEqual(result["craft_claim_transport_calls"], 1)
            self.assertEqual(result["craft_start_transport_calls"], 1)
            original = first.action_store.list_actions_for_task(route.FLOW_ID)
        finally:
            first.close()
        reopened = SafetyStore(self.root / "action-store.sqlite")
        try:
            second = _Context(
                self.root, balance=150, craft_state="craft_claim", store=reopened,
            )
            result = route.run_nanoweapon_in_context(second, occurrence_key=second.occurrence_key)
            self.assertEqual(result["status"], "deferred")
            self.assertEqual(result["craft_claim_transport_calls"], 1)
            self.assertEqual(result["craft_start_transport_calls"], 0)
            self.assertFalse(result["effect_reconciliation_required"])
            records = reopened.list_actions_for_task(route.FLOW_ID)
            claims = [row for row in records if row["semantic_action"] == "claim_completed_nanoweapon"]
            self.assertEqual(len(claims), 2)
            self.assertEqual(len({row["action_key"] for row in claims}), 2)
            for row in original:
                self.assertEqual(reopened.get_action_by_key(row["action_key"]), row)
            for reset in ("game-day-2026-11-06", "game-day-2026-11-07"):
                duplicate = _Context(
                    self.root, balance=150, craft_state="craft_claim", store=reopened,
                    identity_reset=reset,
                )
                result = route.run_nanoweapon_in_context(duplicate, occurrence_key=duplicate.occurrence_key)
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["craft_claim_transport_calls"], 0)
                self.assertEqual(result["craft_start_transport_calls"], 0)
                self.assertFalse(result["effect_reconciliation_required"])
                self.assertEqual(
                    {row["action_key"] for row in reopened.list_actions_for_task(route.FLOW_ID) if row["consequential"]},
                    {row["action_key"] for row in records if row["consequential"]},
                )
        finally:
            reopened.close()

    def test_legacy_claim_history_is_retained_and_old_unclaimed_start_is_claimable(self):
        context = _Context(self.root, balance=80, craft_state="craft_claim")
        try:
            self._seed_previous_start(context, "game-day-2026-11-01")
            context._utc += 10
            legacy_key = route._action_key(
                "claim", reset_id=context.identity.reset_id, identity=context.identity,
                result_identity="completed-normal-craft",
            )
            # Exercise the former persisted key format through the real executor.
            with mock.patch.object(route, "_claim_instance_key", return_value=legacy_key):
                result = route.run_nanoweapon_in_context(context, occurrence_key=context.occurrence_key)
            self.assertEqual(result["craft_claim_transport_calls"], 1)
            self.assertEqual(result["craft_start_transport_calls"], 0)
            legacy = context.action_store.get_action_by_key(legacy_key)
            self.assertEqual(legacy["final_status"], "confirmed")
            current = _Context(
                self.root, craft_state="craft_idle", store=context.action_store,
            )
            current._utc += 20
            result = route.run_nanoweapon_in_context(current, occurrence_key=current.occurrence_key)
            self.assertEqual(result["craft_start_transport_calls"], 1)
            completed = _Context(
                self.root, balance=150, craft_state="craft_claim", store=context.action_store,
            )
            completed._utc += 30
            result = route.run_nanoweapon_in_context(completed, occurrence_key=completed.occurrence_key)
            self.assertEqual(result["craft_claim_transport_calls"], 1)
            self.assertEqual(result["craft_start_transport_calls"], 0)
            self.assertFalse(result["effect_reconciliation_required"])
            self.assertEqual(context.action_store.get_action_by_key(legacy_key), legacy)
            self.assertEqual(
                len([
                    row for row in context.action_store.list_actions_for_task(route.FLOW_ID)
                    if row["semantic_action"] == "claim_completed_nanoweapon"
                ]),
                2,
            )
        finally:
            context.close()

    def test_unjournaled_manual_completion_requires_evidence_without_consequential_input(self):
        context = _Context(self.root, craft_state="craft_claim")
        try:
            result = route.run_nanoweapon_in_context(context, occurrence_key=context.occurrence_key)
            self.assertEqual(result["status"], "blocked")
            self.assertTrue(result["terminal_home_verified"])
            self.assertEqual(result["craft_claim_transport_calls"], 0)
            self.assertFalse(result["effect_reconciliation_required"])
            self.assertFalse(any(row["consequential"] for row in
                                 context.action_store.list_actions_for_task(route.FLOW_ID)))
        finally:
            context.close()

    def test_multiple_unclaimed_old_starts_are_ambiguous_not_guessed(self):
        context = _Context(self.root, craft_state="craft_claim")
        try:
            self._seed_previous_start(context, "game-day-2026-11-03")
            self._seed_previous_start(context, "game-day-2026-11-04")
            before = context.action_store.list_actions_for_task(route.FLOW_ID)
            result = route.run_nanoweapon_in_context(context, occurrence_key=context.occurrence_key)
            self.assertEqual(result["status"], "blocked")
            self.assertTrue(result["terminal_home_verified"])
            self.assertEqual(result["craft_claim_transport_calls"], 0)
            for row in before:
                self.assertEqual(context.action_store.get_action_by_key(row["action_key"]), row)
            self.assertFalse(any(action[2] for action in context.runtime.actions))
        finally:
            context.close()


class _FakeHomeLocalizer:
    def __init__(self, _atlas, _path):
        pass

    def localize(self, frame):
        valid = int(frame[0, 0, 0]) == _STATE_CODE["home"]
        return SimpleNamespace(recognized=valid, stale=False, overlay=False)


if __name__ == "__main__":
    unittest.main()
