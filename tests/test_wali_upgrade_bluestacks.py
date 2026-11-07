"""Replay-only OCR/template tests; synthetic frames are never runtime acceptance evidence."""
from __future__ import annotations

import tempfile
import unittest
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from automation_service.native_execution import NativeRouteRequest
from automation_service.wali_upgrade import _validate_result
from safe_action_core import SafetyStore
from scripts import base_route_native_runtime as boundary
from scripts import navigation_development_boundary as sdk
from scripts import wali_upgrade_bluestacks as route
from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
from tasks.hero_upgrade_disabled import ANTISERUM
from tasks.runtime_identity import BLUESTACKS_ADB, BLUESTACKS_SERIAL


class WaliManualCardRecognitionTests(unittest.TestCase):
    @staticmethod
    def _word(text: str, x: int, y: int, width: int, line: int = 1) -> route._Word:
        return route._Word(text, 99.0, (x, y, x + width, y + 18), (1, 1, line))

    @staticmethod
    def _paint_manual(frame: np.ndarray, material: str, x: int, y: int) -> None:
        template, _tier, _score, _tier_score, _tx, _ty = route._MANUAL_TEMPLATES[material]
        height, width = template.shape[:2]
        frame[y:y + height, x:x + width] = template

    @staticmethod
    def _paint_antiserum_marker(frame: np.ndarray, x: int, y: int) -> None:
        template, _score = route._ANTISERUM_TEMPLATES[0]
        height, width = template.shape[:2]
        frame[y:y + height, x:x + width] = template

    def test_whole_icon_and_tier_region_identify_each_supported_manual(self):
        self.assertIsNotNone(route._MANUAL_TEMPLATES)
        pair_box = (210, 640, 285, 658)
        for material, (template, tier, _score, _tier_score, _tx, _ty) in route._MANUAL_TEMPLATES.items():
            with self.subTest(material=material):
                frame = np.zeros((1280, 800, 3), dtype=np.uint8)
                self._paint_manual(frame, material, 200, 680)
                self.assertEqual(material, route._manual_card_identity(frame, pair_box))
                frame[723:723 + tier.shape[0], 210:210 + tier.shape[1]] = 0
                self.assertIsNone(route._manual_card_identity(frame, pair_box))

    def test_multicard_shared_ocr_line_accounts_every_exact_cost_pair(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        self._paint_manual(frame, "COMBAT_MANUAL_I", 200, 680)
        self._paint_manual(frame, "COMBAT_MANUAL_II", 325, 680)
        self._paint_antiserum_marker(frame, 465, 642)
        text = "4600/30 800/120 1169457/200"
        words = (
            self._word("4600/30", 210, 640, 60),
            self._word("800/120", 335, 640, 60),
            self._word("1169457/200", 530, 640, 100),
        )

        costs, balances, complete, identity_unproven = route._parse_material_rows(
            frame, ((text, words),), preview=True,
        )

        self.assertTrue(complete)
        self.assertFalse(identity_unproven)
        self.assertEqual(
            costs,
            {"COMBAT_MANUAL_I": 30, "COMBAT_MANUAL_II": 120, ANTISERUM: 200},
        )
        self.assertEqual(
            balances,
            {"COMBAT_MANUAL_I": 4600, "COMBAT_MANUAL_II": 800, ANTISERUM: 1_169_457},
        )

    def test_duplicate_manual_identity_blocks_the_complete_vector(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        self._paint_manual(frame, "COMBAT_MANUAL_I", 200, 680)
        self._paint_manual(frame, "COMBAT_MANUAL_I", 325, 680)
        self._paint_antiserum_marker(frame, 465, 642)
        text = "4600/30 900/60 1169457/200"
        words = (
            self._word("4600/30", 210, 640, 60),
            self._word("900/60", 335, 640, 60),
            self._word("1169457/200", 530, 640, 100),
        )

        costs, _balances, complete, identity_unproven = route._parse_material_rows(
            frame, ((text, words),), preview=True,
        )

        self.assertFalse(complete)
        self.assertFalse(identity_unproven)
        self.assertNotIn("COMBAT_MANUAL_II", costs)

    def test_unmatched_manual_cost_is_incomplete_and_requires_source_proof(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        self._paint_antiserum_marker(frame, 465, 642)
        text = "4600/30 1169457/200"
        words = (
            self._word("4600/30", 210, 640, 60),
            self._word("1169457/200", 530, 640, 100),
        )

        costs, _balances, complete, identity_unproven = route._parse_material_rows(
            frame, ((text, words),), preview=True,
        )

        self.assertFalse(complete)
        self.assertTrue(identity_unproven)
        self.assertEqual(costs, {ANTISERUM: 200})

    def test_nonpreview_cost_requires_one_exact_antiserum_row(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        self._paint_antiserum_marker(frame, 465, 1022)
        word = self._word("1169457/200", 530, 1020, 100)

        costs, balances, complete, identity_unproven = route._parse_material_rows(
            frame, ((word.text, (word,)),), preview=False,
        )

        self.assertTrue(complete)
        self.assertFalse(identity_unproven)
        self.assertEqual(costs, {ANTISERUM: 200})
        self.assertEqual(balances, {ANTISERUM: 1_169_457})

    def test_unpaired_source_proven_manual_icon_keeps_the_material_vector_incomplete(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        self._paint_manual(frame, "COMBAT_MANUAL_IV", 200, 680)
        self._paint_antiserum_marker(frame, 465, 642)
        word = self._word("1169457/200", 530, 640, 100)

        costs, _balances, complete, identity_unproven = route._parse_material_rows(
            frame, ((word.text, (word,)),), preview=True,
        )

        self.assertFalse(complete)
        self.assertFalse(identity_unproven)
        self.assertEqual(costs, {ANTISERUM: 200})

    def test_confirmation_overlay_text_is_not_a_clean_action_surface(self):
        confirm = self._word("Confirm evolution", 300, 500, 150)
        hero_title = self._word("Wali", 300, 150, 45)

        self.assertEqual(route._overlay_state((("Confirm evolution", (confirm,)),)), "unknown")
        self.assertEqual(route._overlay_state((("Wali", (hero_title,)),)), "none_observed")

    def test_green_shape_without_the_proven_tube_cannot_authorize_antiserum(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        frame[1022:1068, 465:515] = (0, 255, 0)
        word = self._word("1169457/200", 530, 1020, 100)
        costs, _balances, complete, _unproven = route._parse_material_rows(frame, ((word.text, (word,)),), preview=False)
        self.assertFalse(complete)
        self.assertEqual(costs, {})

    def test_disagreeing_current_numeric_reads_cannot_supply_a_material_quote(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        first = (self._word("100/30", 200, 500, 100),)
        conflicting = (self._word("100/80", 200, 500, 100),)
        with patch.object(route, "_ocr_region", side_effect=(first, conflicting)):
            self.assertEqual(route._numeric_words(frame, (190, 490, 310, 530), field=1), ())


class _WaliModel:
    """Deterministic screen/effect model behind the real native transport guards."""

    def __init__(
        self, level: int = 5, balance: int = 10000, unknown: bool = False,
        bulk_mode: str = "detail", price_step: int = 0,
    ) -> None:
        self.page, self.level, self.cap = 1, level, 10
        self.balance, self.manual, self.receipt = balance, 50, 0
        self.normal = self.evolutions = 0
        self.inputs: list[tuple[object, ...]] = []
        self.unknown = unknown
        self.bulk, self.bulk_mode, self.price_step = False, bulk_mode, price_step

    def get_state(self) -> str:
        return "device"

    def shell_text(self, *_args) -> str:
        return "mCurrentFocus=Window{0 u0 com.global.ztmslg/.MainActivity}"

    def capture_png(self) -> bytes:
        frame = np.full((1280, 800, 3), 20, dtype=np.uint8)
        # OCR reads the immutable captured snapshot, never this model's later state.
        snapshot = (self.page, self.level, self.cap, self.balance // 256,
                    self.balance % 256, self.manual, self.receipt, int(self.bulk), self.price_step)
        for index, value in enumerate(snapshot):
            frame[0, index, 0] = value
        if self.page == 4 or (self.page == 3 and not self.bulk):
            template = route._ANTISERUM_TEMPLATES[0 if self.page == 3 else 1][0]
            x, y = (245, 1100) if self.page == 3 else (285, 792)
            height, width = template.shape[:2]
            frame[y:y + height, x:x + width] = template
        if self.page == 4:
            template = route._MANUAL_TEMPLATES["COMBAT_MANUAL_I"][0]
            height, width = template.shape[:2]
            frame[702:702 + height, 357:357 + width] = template
        return cv2.imencode(".png", frame)[1].tobytes()

    def dispatch_tap(self, point: tuple[int, int]) -> None:
        self.inputs.append(("tap", self.page, point))
        x, y = point
        if self.page == 1:
            assert 650 <= x <= 740 and 1150 <= y <= 1200
            self.page = 2
        elif self.page == 2:
            assert 90 <= x <= 220 and 290 <= y <= 340
            self.page = 3
        elif self.page == 3 and x > 400:
            assert 480 <= x <= 660 and 1175 <= y <= 1230
            self.page = 4
        elif self.page == 3:
            assert 100 <= x <= 330 and 1175 <= y <= 1230
            cost = 100 + self.price_step * self.level
            assert not self.bulk and self.level < self.cap and self.balance >= cost
            self.normal += 1
            self.bulk = True
            if not self.unknown:
                self.level += 1
                self.balance -= cost
                self.receipt = 0
        elif self.page == 4:
            assert 250 <= x <= 550 and 840 <= y <= 920
            assert self.level == self.cap and self.balance >= 200 and self.manual >= 30
            self.evolutions += 1
            self.level += 1
            self.cap = 30
            self.balance -= 200
            self.manual -= 30
            self.receipt, self.page = 1, 3
        else:
            raise AssertionError(("unexpected tap", point, self.page))

    def dispatch_back(self) -> None:
        self.inputs.append(("back", self.page))
        if self.bulk:
            if self.bulk_mode == "detail":
                self.bulk = False
            elif self.bulk_mode == "roster":
                self.bulk, self.page = False, 2
            elif self.bulk_mode != "unknown":
                raise AssertionError(self.bulk_mode)
        else:
            self.page = {4: 3, 3: 2, 2: 1}[self.page]

    def dispatch_swipe(self, *_args) -> None:
        raise AssertionError("visible Wali must not be scrolled")


def _model_words(frame: np.ndarray) -> tuple[route._Word, ...]:
    page, level, cap, high, low, manual, receipt, bulk, price_step = (
        int(frame[0, index, 0]) for index in range(9)
    )
    balance = high * 256 + low
    rows = []

    def add(text: str, x: int, y: int, width: int = 180) -> None:
        line = len(rows) + 1
        rows.append(route._Word(text, 99, (x, y, x + width, y + 18), (line, 1, 1)))

    if page == 1:
        add("Hero", 650, 1160, 90)
    if page == 2:
        add("Hero", 350, 40, 100)
        add("Wali", 100, 300, 100)
    if page == 3:
        add("Hero", 350, 40, 100)
        add("Wali", 350, 84, 100)
        add("om", 224, 75, 36)  # Actual class-icon OCR must not become a second hero name.
        add(f"Lv.{level}", 300, 1000)
        add(f"(max Lv.{cap})", 300, 1050)
        add("Upgrade", 150, 1190, 130)
        add("Evolve", 500, 1190, 120)
        if bulk:
            add(f"Upgrade to Lv.{cap}", 100, 1100, 300)
        else:
            add(f"{balance}/{100 + price_step * level}", 310, 1115, 200)
        if receipt:
            add("[Combat Manual I] used", 220, 450, 350)
    if page == 4:
        add("Evolution Preview", 250, 235, 300)
        add(f"max Lv.{cap} max Lv.30", 180, 315, 450)
        add(f"{manual}/30", 365, 675, 80)
        add(f"{balance}/200", 340, 805, 200)
        add("Evolve", 330, 870, 130)
    return tuple(rows)


def _run_native_model(model: _WaliModel, store_path: Path, out: Path, day: str, previous: str | None = None):
    runtimes = []
    tick = count(1000.0, 0.001)
    clock = lambda: next(tick)

    def connect(**kwargs):
        runtime = LocalBlueStacksRuntime(model, kwargs["output_directory"] / "runtime", execute=True)
        runtimes.append(runtime)
        return runtime

    def make(**kwargs):
        return boundary.make_native_route_binding(**kwargs, action_store_factory=lambda _: SafetyStore(store_path))

    binding = route.create_service_binding(make)
    config = binding._config
    with patch.object(sdk, "RUNTIME_INPUT_LOCK_PATH", out / "input-lock.sqlite3"):
        lock = sdk.RuntimeInputLock(owner="automation-service", invocation_id="offline-wali-sdk").acquire()
        try:
            request = NativeRouteRequest(
                flow_id=config.flow_id, product_id=config.product_id,
                product_revision=config.product_revision, runtime_profile_id=config.runtime_profile_id,
                identity=SimpleNamespace(account_id="offline-account", server_id="offline-server", reset_id=day),
                previous_reset_id=previous, occurrence_key=f"offline-{day}-{len(model.inputs)}",
                checkpoint=lambda: None, validate_identity=lambda: None, runtime_input_lock=lock,
                adb=str(BLUESTACKS_ADB), serial=BLUESTACKS_SERIAL, output_directory=out / "sessions",
                max_inputs=config.max_inputs, max_actions=config.max_actions, settle_seconds=0,
                utc_clock=lambda: 1700000000.0, monotonic_clock=clock,
            )
            with (
                patch.object(boundary.LocalBlueStacksRuntime, "connect", side_effect=connect),
                patch.object(boundary, "is_clean_home_frame", lambda frame: int(frame[0, 0, 0]) == 1),
                patch.object(route, "_ocr_words", side_effect=_model_words),
                patch.object(route, "_MIN_SETTLE_SECONDS", 0),
                patch("scripts.bluestacks_native_runtime.time.monotonic", clock),
            ):
                result = binding.run(request)
            native = result.native_result
            if native:
                _validate_result(native, game_day_id=day, occurrence_key=request.occurrence_key)
            return {
                "failure": result.failure, "accounting_verified": result.accounting_verified,
                "input_count": result.input_count, "native": dict(native), "runtime_created": len(runtimes),
            }
        finally:
            lock.release()



class WaliNativeDurabilityTests(unittest.TestCase):
    """Actual boundary/SDK/runtime/Core/SQLite; fake transport and OCR/Home ports."""

    def test_three_normals_survive_evolution_reopen_and_the_next_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = _WaliModel(level=9)
            first = _run_native_model(model, root / "safety.sqlite3", root, "day-1")
            self.assertIsNone(first["failure"])
            self.assertTrue(first["accounting_verified"])
            self.assertEqual(first["native"]["status"], "completed")
            self.assertEqual(first["native"]["confirmed_upgrades"], 3)
            self.assertEqual(first["native"]["evolution_committed_count"], 1)
            self.assertEqual((model.normal, model.evolutions, model.level), (3, 1, 13))
            repeated = _run_native_model(model, root / "safety.sqlite3", root, "day-1")
            self.assertEqual(repeated["input_count"], 0)
            self.assertEqual(repeated["native"]["confirmed_upgrades"], 3)
            self.assertEqual(model.normal, 3)
            next_reset = _run_native_model(model, root / "safety.sqlite3", root, "day-2", previous="day-1")
            self.assertEqual(next_reset["native"]["status"], "completed")
            self.assertEqual(next_reset["native"]["prior_confirmed_upgrades"], 0)
            self.assertEqual((model.normal, model.evolutions, model.level), (6, 1, 16))

    def test_costs_are_reread_after_bulk_dismissal_and_current_wali_reselection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = _WaliModel(bulk_mode="roster", price_step=7)
            result = _run_native_model(model, root / "safety.sqlite3", root, "day-1")
            self.assertIsNone(result["failure"])
            self.assertTrue(result["accounting_verified"])
            self.assertEqual(result["native"]["status"], "completed")
            self.assertEqual((model.normal, model.level, model.balance), (3, 8, 9574))
            self.assertEqual(
                [row["before"]["material_costs"]["ANTISERUM"]
                 for row in result["native"]["level_upgrades"]],
                [135, 142, 149],
            )
            self.assertTrue(result["native"]["terminal_home_verified"])

    def test_unknown_bulk_dismissal_never_repeats_back_or_the_spending_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = _WaliModel(bulk_mode="unknown")
            first = _run_native_model(model, root / "safety.sqlite3", root, "day-1")
            self.assertEqual(first["native"]["status"], "unknown")
            self.assertEqual(first["native"]["confirmed_upgrades"], 0)
            self.assertEqual((model.normal, model.level, model.balance), (1, 6, 9900))
            self.assertEqual(sum(row[0] == "back" for row in model.inputs), 1)
            repeated = _run_native_model(model, root / "safety.sqlite3", root, "day-1")
            self.assertEqual((repeated["input_count"], repeated["runtime_created"]), (0, 0))
            self.assertEqual(sum(row[0] == "back" for row in model.inputs), 1)

    def test_known_shortage_preserves_one_and_reopen_performs_only_remaining_two(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = _WaliModel(balance=100)
            first = _run_native_model(model, root / "safety.sqlite3", root, "day-1")
            self.assertEqual(first["native"]["status"], "deferred")
            self.assertTrue(first["native"]["terminal_home_verified"])
            self.assertEqual(first["native"]["confirmed_upgrades"], 1)
            self.assertEqual(model.normal, 1)
            model.balance = 10000
            resumed = _run_native_model(model, root / "safety.sqlite3", root, "day-1")
            self.assertEqual(resumed["native"]["status"], "completed")
            self.assertEqual(resumed["native"]["prior_confirmed_upgrades"], 1)
            self.assertEqual(resumed["native"]["level_upgrade_committed_count"], 2)
            self.assertEqual(model.normal, 3)

    def test_unknown_single_effect_is_unresolved_and_not_retried_after_restart_or_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = _WaliModel(unknown=True)
            first = _run_native_model(model, root / "safety.sqlite3", root, "day-1")
            self.assertEqual(first["native"]["status"], "unknown")
            self.assertEqual(first["native"]["total_action_count"], 1)
            self.assertEqual(first["native"]["confirmed_upgrades"], 0)
            for day in ("day-1", "day-2"):
                retry = _run_native_model(model, root / "safety.sqlite3", root, day)
                self.assertEqual(retry["input_count"], 0)
                self.assertEqual(retry["runtime_created"], 0)
            self.assertEqual(model.normal, 1)
            store = SafetyStore(root / "safety.sqlite3")
            try:
                self.assertEqual([row["final_status"] for row in store.list_actions_for_task(route.FLOW_ID)], ["unresolved"])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
