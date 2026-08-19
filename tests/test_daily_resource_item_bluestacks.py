from __future__ import annotations

from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts import daily_resource_item_bluestacks as route


def _ocr(*rows: tuple[str, int, int, int, int]):
    def recognize(_frame):
        return {
            "text": [row[0] for row in rows],
            "left": [row[1] for row in rows],
            "top": [row[2] for row in rows],
            "width": [row[3] for row in rows],
            "height": [row[4] for row in rows],
        }

    return recognize


def _blank_frame() -> np.ndarray:
    return np.zeros((1280, 800, 3), dtype=np.uint8)


def _frame() -> np.ndarray:
    frame = _blank_frame()
    cv2.rectangle(frame, (70, 440), (730, 620), (100, 100, 100), -1)
    return frame


def _item_rows(item_line: str = "1K Food x 1 Use", owned: int = 2):
    rows = []
    x = 100
    for word in item_line.split():
        width = max(24, len(word) * 10)
        rows.append((word, x, 500, width, 28))
        x += max(34, width + 8)
    rows.append(("owned", 100, 550, 60, 28))
    rows.append((str(owned), 165, 550, 15, 28))
    return tuple(rows)


def _bag_category_rows():
    return (
        ("Diamond", 497, 120, 100, 28),
        ("Shop", 636, 120, 70, 28),
        ("Bag", 300, 20, 50, 28),
        ("Resource", 8, 190, 70, 28),
        ("&", 82, 190, 18, 28),
        ("Speedup", 104, 190, 85, 28),
        ("Military", 200, 190, 90, 28),
        ("Gadget", 360, 190, 80, 28),
        ("Other", 530, 190, 70, 28),
        ("Recent", 680, 190, 80, 28),
    )


def _resource_list_rows(*, item: str = "10% Build Speedup", use_x: int = 462):
    return (
        *_bag_category_rows(),
        *tuple(
            (word, 140 + index * 34, 320, max(24, len(word) * 10), 28)
            for index, word in enumerate(item.split())
        ),
        ("Use", use_x, 320, 55, 28),
    )


def _paint_selected_bag_category(
    frame: np.ndarray, category: str = "resource_speedup"
) -> np.ndarray:
    rois = {
        "resource_speedup": (1, 160, 159, 228),
        "military": (183, 154, 298, 235),
        "gadget": (344, 154, 458, 235),
        "other": (516, 154, 605, 229),
        "recent": (668, 156, 774, 229),
    }
    x0, y0, x1, y1 = rois[category]
    # BGR with elevated red channel for selected-tab dominance.
    frame[y0:y1, x0:x1] = (40, 40, 140)
    return frame


def _resources_selected_frame() -> np.ndarray:
    return _paint_selected_bag_category(_blank_frame(), "resource_speedup")


def _military_selected_bag_frame() -> np.ndarray:
    return _paint_selected_bag_category(_blank_frame(), "military")


class DailyResourceItemRecognitionTests(unittest.TestCase):
    def test_exact_measured_card_authorizes_one_food_use(self):
        measured = {
            "proven": True,
            "source": "visual-horizontal-separators",
            "bounds": (70, 440, 730, 620),
            "horizontal_separators": (440, 620),
        }
        with patch.object(route, "_measure_resource_item_card", return_value=measured):
            recognition = route.recognize_food_item(
                _frame(),
                ocr=_ocr(*_item_rows()),
            )
        self.assertTrue(recognition.recognized)
        self.assertTrue(route.resource_item_authorizeable(recognition))
        self.assertEqual(recognition.item_name, "1K Food")
        self.assertEqual(recognition.owned_quantity, 2)
        self.assertEqual(recognition.quantity, 1)
        self.assertEqual(recognition.use_roi, (250, 500, 280, 528))

    def test_exact_item_name_and_quantity_are_required(self):
        measured = {
            "proven": True,
            "source": "visual-horizontal-separators",
            "bounds": (70, 440, 730, 620),
            "horizontal_separators": (440, 620),
        }
        with patch.object(route, "_measure_resource_item_card", return_value=measured):
            for item_line in (
                "1K Food Pack x 1 Use",
                "Premium 1K Food x 1 Use",
                "Food 1K x 1 Use",
            ):
                with self.subTest(item_line=item_line):
                    rejected = route.recognize_food_item(
                        _frame(),
                        ocr=_ocr(*_item_rows(item_line)),
                    )
                    self.assertFalse(rejected.recognized)
                    self.assertFalse(route.resource_item_authorizeable(rejected))

            wrong_quantity = route.recognize_food_item(
                _frame(),
                ocr=_ocr(*_item_rows("1K Food x 2 Use")),
            )
        self.assertFalse(wrong_quantity.recognized)
        self.assertEqual(wrong_quantity.quantity, 2)

    def test_ordinary_use_implies_quantity_one_only_with_exact_card(self):
        measured = {
            "proven": True,
            "source": "visual-horizontal-separators",
            "bounds": (70, 440, 730, 620),
            "horizontal_separators": (440, 620),
        }
        with patch.object(route, "_measure_resource_item_card", return_value=measured):
            recognition = route.recognize_food_item(
                _frame(),
                ocr=_ocr(*_item_rows("1K Food Use")),
            )
        self.assertTrue(recognition.recognized)
        self.assertEqual(recognition.quantity, 1)
        self.assertEqual(recognition.quantity_source, "ordinary-use-implied-one")
        self.assertTrue(recognition.single_use_semantics_proven)
        self.assertTrue(route.resource_item_authorizeable(recognition))

        with patch.object(route, "_measure_resource_item_card", return_value=measured):
            with_bulk = route.recognize_food_item(
                _frame(),
                ocr=_ocr(
                    *_item_rows("1K Food Use"),
                    ("In", 520, 500, 22, 28),
                    ("bulk", 546, 500, 45, 28),
                ),
            )
        self.assertTrue(with_bulk.recognized)
        self.assertTrue(with_bulk.bulk_visible)
        self.assertTrue(with_bulk.bulk_disjoint_from_use)
        self.assertTrue(route.resource_item_authorizeable(with_bulk))

        unmeasured = route.recognize_food_item(
            _blank_frame(),
            ocr=_ocr(*_item_rows("1K Food Use")),
        )
        self.assertFalse(unmeasured.recognized)
        self.assertFalse(route.resource_item_authorizeable(unmeasured))

    def test_resource_list_lane_is_current_and_disjoint_from_controls(self):
        binding = route.bind_resource_list_swipe(
            _resources_selected_frame(),
            ocr=_ocr(*_resource_list_rows()),
        )
        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(binding.start[0], binding.end[0])
        self.assertLess(binding.end[1], binding.start[1])
        self.assertEqual(binding.direction, "forward")
        self.assertTrue(
            all(
                not route._boxes_overlap(binding.lane, roi)
                for roi in (*binding.use_rois, *binding.bulk_rois)
            )
        )
        self.assertEqual(binding.source, "current-frame-resources-content")

        reverse = route.bind_resource_list_swipe(
            _resources_selected_frame(),
            ocr=_ocr(
                *_resource_list_rows(item="Gas Canister"),
            ),
        )
        self.assertIsNotNone(reverse)
        assert reverse is not None
        self.assertEqual(reverse.direction, "reverse")
        self.assertGreater(reverse.end[1], reverse.start[1])
        self.assertTrue(
            all(
                not route._boxes_overlap(reverse.lane, roi)
                for roi in (*reverse.use_rois, *reverse.bulk_rois)
            )
        )

        blocked = route.bind_resource_list_swipe(
            _resources_selected_frame(),
            ocr=_ocr(*_resource_list_rows(use_x=250)),
        )
        self.assertIsNone(blocked)

    def test_progress_signature_rejects_stall_and_accepts_material_change(self):
        before = route.resource_list_content_signature(
            _resources_selected_frame(),
            ocr=_ocr(*_resource_list_rows(item="10% Build Speedup")),
        )
        same = route.resource_list_content_signature(
            _resources_selected_frame(),
            ocr=_ocr(*_resource_list_rows(item="10% Build Speedup")),
        )
        changed = route.resource_list_content_signature(
            _resources_selected_frame(),
            ocr=_ocr(*_resource_list_rows(item="1K Food")),
        )
        self.assertIsNotNone(before)
        self.assertEqual(before, same)
        self.assertFalse(route.resource_list_progressed(before, same))
        self.assertTrue(route.resource_list_progressed(before, changed))

    def test_resources_surface_requires_clear_modal_detector_and_ocr(self):
        rows = _resource_list_rows()
        recognized = route.recognize_resources_screen(
            _resources_selected_frame(),
            ocr=_ocr(*rows),
        )
        self.assertTrue(recognized.recognized)

        with patch.object(
            route,
            "_generic_modal_overlay_evidence",
            return_value={
                "recognized": True,
                "state": "unknown",
                "panel_candidates": (),
            },
        ):
            unknown_detector = route.recognize_resources_screen(
                _resources_selected_frame(),
                ocr=_ocr(*rows),
            )
        self.assertFalse(unknown_detector.recognized)

        with_marker = route.recognize_resources_screen(
            _resources_selected_frame(),
            ocr=_ocr(*rows, ("Cancel", 600, 600, 70, 28)),
        )
        self.assertFalse(with_marker.recognized)

    def test_wrong_bag_category_binds_resources_tab_and_rejects_resources_state(self):
        rows = _resource_list_rows()
        military = _military_selected_bag_frame()
        self.assertEqual(
            route.classify_selected_bag_category(military, ocr=_ocr(*rows)),
            "military",
        )
        self.assertFalse(
            route.recognize_resources_screen(military, ocr=_ocr(*rows)).recognized
        )
        self.assertEqual(
            route.bind_resources_category_tab(military, ocr=_ocr(*rows)),
            (8, 190, 189, 218),
        )
        self.assertIsNone(
            route.bind_resources_category_tab(
                _resources_selected_frame(), ocr=_ocr(*rows)
            )
        )

    def test_measured_card_and_pixels_are_required(self):
        rows = _item_rows()
        rejected = route.recognize_food_item(_blank_frame(), ocr=_ocr(*rows))
        self.assertFalse(rejected.recognized)
        self.assertEqual(
            rejected.reason,
            "current-resource-item-card-not-visually-proven",
        )

    def test_bulk_is_disjoint_and_never_selected(self):
        measured = {
            "proven": True,
            "source": "visual-horizontal-separators",
            "bounds": (70, 440, 730, 620),
            "horizontal_separators": (440, 620),
        }
        rows = (*_item_rows(), ("bulk", 520, 500, 55, 28))
        with patch.object(route, "_measure_resource_item_card", return_value=measured):
            recognition = route.recognize_food_item(_frame(), ocr=_ocr(*rows))
        self.assertTrue(recognition.recognized)
        self.assertTrue(recognition.bulk_visible)
        self.assertTrue(recognition.bulk_disjoint_from_use)

    def test_overlapping_bulk_and_multiple_use_fail_closed(self):
        measured = {
            "proven": True,
            "source": "visual-horizontal-separators",
            "bounds": (70, 440, 730, 620),
            "horizontal_separators": (440, 620),
        }
        overlap = (*_item_rows(), ("bulk", 226, 500, 40, 28))
        multiple = (*_item_rows(), ("Use", 300, 500, 40, 28))
        with patch.object(route, "_measure_resource_item_card", return_value=measured):
            with self.subTest(case="bulk"):
                self.assertFalse(route.recognize_food_item(_frame(), ocr=_ocr(*overlap)).recognized)
            with self.subTest(case="multiple-use"):
                self.assertFalse(route.recognize_food_item(_frame(), ocr=_ocr(*multiple)).recognized)

    def test_forbidden_item_and_confirmation_overlay_fail_closed(self):
        measured = {
            "proven": True,
            "source": "visual-horizontal-separators",
            "bounds": (70, 440, 730, 620),
            "horizontal_separators": (440, 620),
        }
        with patch.object(route, "_measure_resource_item_card", return_value=measured):
            forbidden = route.recognize_food_item(
                _frame(),
                ocr=_ocr(*_item_rows(), ("AP", 400, 580, 30, 28)),
            )
            overlay = route.recognize_food_item(
                _frame(),
                ocr=_ocr(*_item_rows(), ("Confirm", 400, 700, 70, 28)),
            )
        self.assertFalse(forbidden.recognized)
        self.assertFalse(overlay.recognized)

    def test_postcondition_requires_exact_owned_decrement_and_home(self):
        before = {"inventory_quantity": 2, "food_resource": 100}
        after = {
            "inventory_quantity": 1,
            "food_resource": 100,
            "home_verified": True,
        }
        self.assertTrue(route.resource_item_postcondition_verified(before, after))
        self.assertFalse(
            route.resource_item_postcondition_verified(
                before,
                {"inventory_quantity": 2, "food_resource": 100, "home_verified": True},
            )
        )
        self.assertFalse(
            route.resource_item_postcondition_verified(
                before,
                {"inventory_quantity": 0, "food_resource": 100, "home_verified": True},
            )
        )
        self.assertFalse(
            route.resource_item_postcondition_verified(
                before,
                {"inventory_quantity": 1, "food_resource": 100},
            )
        )
        self.assertFalse(
            route._resource_delta_verified(
                {"inventory_quantity": 10, "food_resource": 100},
                {"inventory_quantity": 9, "food_resource": 50},
            )
        )
        self.assertFalse(
            route._resource_delta_verified(
                {"food_resource": 100},
                {"food_resource": 1100},
            )
        )
        self.assertTrue(
            route._resource_delta_verified(
                {"inventory_quantity": 129680},
                {"inventory_quantity": 129679},
            )
        )

    def test_unknown_source_stops_before_any_input(self):
        class Runtime:
            execute = True
            frame_max_age_seconds = 30
            input_count = 0

            def capture(self, _label):
                return object()

            def tap(self, *args, **kwargs):
                raise AssertionError("unknown source must not tap")

        class Session:
            input_count = 0
            actions = []
            session_directory = Path.cwd()
            terminal_status = None
            blocker = None
            next_action = None

            def observe(self, capture, *, label):
                return capture(label)

        result = route.run_daily_resource_item(Runtime(), Session())
        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(result["item_use_transport_calls"], 0)

    def test_home_bag_target_requires_unique_current_frame_visual_match(self):
        frame_path = (
            Path(__file__).resolve().parents[1]
            / ".local-captures"
            / "development-sessions"
            / "observe-20260819T030029178669Z"
            / "observe.png"
        )
        if not frame_path.is_file():
            self.skipTest("retained Home frame is unavailable")
        retained = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        self.assertIsNotNone(retained)
        assert retained is not None

        recognized_home = type(
            "HomeRecognition",
            (),
            {"is_home": True, "native_ok": True},
        )()
        altered = retained.copy()
        cv2.rectangle(
            altered,
            (route.HOME_BAG_ICON_ROI[0], route.HOME_BAG_ICON_ROI[1]),
            (route.HOME_BAG_ICON_ROI[2] - 1, route.HOME_BAG_ICON_ROI[3] - 1),
            (0, 0, 0),
            -1,
        )
        with patch.object(route, "recognize_home_nav", return_value=recognized_home):
            target = route._home_bag_target(retained, ocr=_ocr())
            altered_target = route._home_bag_target(altered, ocr=_ocr())
            blank_target = route._home_bag_target(_blank_frame(), ocr=_ocr())

        self.assertEqual(target, route.HOME_BAG_ICON_ROI)
        self.assertIsNone(altered_target)
        self.assertIsNone(blank_target)

    def test_retained_home_frame_binds_measured_bag_icon(self):
        frame_path = (
            Path(__file__).resolve().parents[1]
            / ".local-captures"
            / "development-sessions"
            / "observe-20260819T030029178669Z"
            / "observe.png"
        )
        if not frame_path.is_file():
            self.skipTest("retained Home Bag frame is unavailable")
        frame = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame)
        assert frame is not None
        recognized_home = type(
            "HomeRecognition",
            (),
            {"is_home": True, "native_ok": True},
        )()
        with patch.object(route, "recognize_home_nav", return_value=recognized_home):
            target = route._home_bag_target(frame, ocr=_ocr())
        self.assertEqual(target, route.HOME_BAG_ICON_ROI)
        self.assertNotEqual(target, (407, 1227, 455, 1267))

    def test_return_home_binding_fails_closed_without_proven_control(self):
        for label in ("home", "base", "close", "return"):
            with self.subTest(label=label):
                self.assertIsNone(
                    route._return_home_target(
                        _blank_frame(),
                        ocr=_ocr((label, 100, 100, 60, 28)),
                    )
                )

    def test_retained_resources_frame_binds_measured_back_arrow(self):
        frame_path = (
            Path(__file__).resolve().parents[1]
            / ".local-captures"
            / "development-sessions"
            / "observe-20260819T025359621634Z"
            / "observe.png"
        )
        if not frame_path.is_file():
            self.skipTest("retained Resources frame is unavailable")
        frame = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame)
        assert frame is not None

        target = route._return_home_target(frame)
        bag = route._recognize_bag(frame)

        self.assertIsNotNone(target)
        self.assertTrue(bag["recognized"])
        assert target is not None
        self.assertLess(target[0], 20)
        self.assertLess(target[1], 10)
        self.assertGreater(target[2], 85)
        self.assertGreater(target[3], 55)
        binding = route.bind_resource_list_swipe(frame)
        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertTrue(binding.use_rois)
        self.assertTrue(
            all(
                not route._boxes_overlap(binding.lane, roi)
                for roi in binding.use_rois
            )
        )

    def test_return_home_binding_rejects_simulated_large_modal(self):
        frame_path = (
            Path(__file__).resolve().parents[1]
            / ".local-captures"
            / "development-sessions"
            / "observe-20260819T025359621634Z"
            / "observe.png"
        )
        if not frame_path.is_file():
            self.skipTest("retained Resources frame is unavailable")
        normal = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        self.assertIsNotNone(normal)
        assert normal is not None

        modal = normal.copy()
        cv2.rectangle(modal, (50, 200), (750, 1050), (20, 20, 20), -1)
        cv2.rectangle(modal, (50, 200), (750, 1050), (240, 240, 240), 12)
        resources_ocr = _ocr(*_resource_list_rows())

        self.assertIsNotNone(
            route._return_home_target(normal, ocr=resources_ocr)
        )
        self.assertIsNone(route._return_home_target(modal, ocr=resources_ocr))

        with patch.object(
            route,
            "_generic_modal_overlay_evidence",
            return_value={
                "recognized": True,
                "state": "unknown",
                "panel_candidates": (),
            },
        ):
            self.assertIsNone(
                route._return_home_target(normal, ocr=resources_ocr)
            )

    def test_direct_route_skips_redundant_tab_tap_when_resources_already_selected(self):
        frame = CapturedNativeFrame(
            frame=_frame(),
            png=b"",
            sha256="a" * 64,
            captured_monotonic=time.monotonic(),
            path=Path.cwd() / "daily-resource-item-test-frame.png",
        )
        item_before = route.ResourceItemRecognition(
            route.RESOURCE_ITEM_STATE,
            True,
            target_identity=route.ITEM_TARGET_IDENTITY,
            target_roi=(70, 440, 730, 620),
            item_name="1K Food",
            owned_quantity=2,
            quantity=1,
            use_roi=(430, 500, 485, 528),
            inventory_quantity=2,
            food_resource=100,
            visual_evidence={
                "item_card": {
                    "proven": True,
                    "source": "visual-horizontal-separators",
                    "bounds": (70, 440, 730, 620),
                },
                "card_ownership_proven": True,
                "use_count": 1,
                "quantity_source": "explicit",
            },
            quantity_source="explicit",
            single_use_semantics_proven=True,
        )
        item_after = route.ResourceItemRecognition(
            route.RESOURCE_SUCCESSOR_STATE,
            False,
            item_name="1K Food",
            owned_quantity=1,
            quantity=1,
            inventory_quantity=1,
            food_resource=100,
        )
        home = {
            "state": "HOME",
            "recognized": True,
            "home_verified": True,
            "target_identity": route.HOME_TARGET_IDENTITY,
            "target_roi": (0, 1213, 800, 1280),
        }
        bag = {
            "state": "BAG",
            "recognized": True,
            "target_identity": route.BAG_TARGET_IDENTITY,
            "target_roi": (100, 100, 140, 140),
        }
        resources = route.ResourceItemRecognition(
            "RESOURCES",
            True,
            target_identity=route.RESOURCES_TARGET_IDENTITY,
            target_roi=(150, 150, 190, 190),
        )

        class Runtime:
            execute = True
            frame_max_age_seconds = 30

            def __init__(self, session):
                self.session = session
                self.input_count = 0
                self.capture_count = 0

            def capture(self, _label):
                self.capture_count += 1
                return CapturedNativeFrame(
                    frame=frame.frame,
                    png=b"",
                    sha256=f"{self.capture_count:064x}",
                    captured_monotonic=time.monotonic(),
                    path=Path.cwd() / f"daily-resource-item-test-frame-{self.capture_count}.png",
                )

            def tap(self, _source, **kwargs):
                self.input_count += 1
                self.session.input_count = self.input_count
                self.session.actions.append(
                    {
                        "label": kwargs["action_key"],
                        "action_key": kwargs["action_key"],
                    }
                )

        class Session:
            input_count = 0
            actions = []
            session_directory = Path.cwd()
            terminal_status = None
            blocker = None
            next_action = None

            def observe(self, capture, *, label):
                return capture(label)

            def run_action(self, **kwargs):
                before = kwargs["capture"]("before")
                kwargs["dispatch"](before)
                after = kwargs["capture"]("after")
                return {"state": kwargs["recognize"](after)}

        session = Session()
        runtime = Runtime(session)
        food_calls = {"n": 0}

        def food_side_effect(frame, *, ocr=None):
            del frame, ocr
            food_calls["n"] += 1
            # First recognitions are pre-use; once Use has been dispatched the
            # successor frames must show the decremented owned count.
            if any(
                row.get("action_key") == route.ITEM_USE_ACTION_KEY
                for row in session.actions
            ):
                return item_after
            return item_before

        with patch.object(route, "_recognize_home", return_value=home), patch.object(
            route, "_recognize_bag", return_value=bag
        ), patch.object(
            route, "recognize_resources_screen", return_value=resources
        ), patch.object(
            route, "_home_bag_target", return_value=(100, 100, 140, 140)
        ), patch.object(
            route, "_return_home_target", return_value=(700, 1200, 760, 1260)
        ), patch.object(
            route,
            "recognize_food_item_in_resources",
            side_effect=food_side_effect,
        ):
            result = route.run_daily_resource_item(runtime, session)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(session.input_count, 3)
        self.assertEqual(result["max_inputs"], 10)
        self.assertEqual(result["item_use_transport_calls"], 1)
        self.assertTrue(result["resource_delta_verified"])
        self.assertTrue(result["terminal_home_verified"])
        self.assertIn("item-before", result["frames"])
        self.assertIn("item-after", result["frames"])
        self.assertIn("home", result["frames"])
        self.assertNotEqual(
            result["frames"]["item-before"]["sha256"],
            result["frames"]["item-after"]["sha256"],
        )
        action_keys = [row["action_key"] for row in session.actions]
        self.assertEqual(
            action_keys,
            [
                "daily-resource-item:open-bag",
                route.ITEM_USE_ACTION_KEY,
                "daily-resource-item:return-home",
            ],
        )
        joined_actions = " ".join(action_keys).casefold()
        self.assertNotIn("quest", joined_actions)
        self.assertNotIn("open-daily", joined_actions)
        self.assertNotIn("select-resources-tab", joined_actions)

    def test_observed_list_loop_caps_at_bounded_progressing_swipes(self):
        home = {
            "state": "HOME",
            "recognized": True,
            "home_verified": True,
        }
        bag = {
            "state": "BAG",
            "recognized": True,
            "target_identity": route.BAG_TARGET_IDENTITY,
        }
        resources = route.ResourceItemRecognition(
            "RESOURCES",
            True,
            target_identity=route.RESOURCES_TARGET_IDENTITY,
            target_roi=(8, 160, 153, 188),
        )
        not_food = route.ResourceItemRecognition(
            route.RESOURCE_ITEM_STATE,
            False,
            item_name="1K Food",
        )

        class Runtime:
            execute = True
            frame_max_age_seconds = 30

            def __init__(self, session):
                self.session = session
                self.state = 0
                self.swipes = 0

            def capture(self, _label):
                image = _blank_frame()
                image[0, 0, 0] = self.state
                return CapturedNativeFrame(
                    frame=image,
                    png=b"",
                    sha256=f"{self.state:064x}",
                    captured_monotonic=time.monotonic(),
                    path=Path.cwd() / f"daily-resource-item-scroll-{self.state}.png",
                )

            def tap(self, _source, **kwargs):
                self.session.input_count += 1
                self.session.actions.append(
                    {"label": kwargs["action_key"], "action_key": kwargs["action_key"]}
                )
                self.state = 1

            def swipe(self, _source, **kwargs):
                self.session.input_count += 1
                self.session.actions.append(
                    {"label": kwargs["action_key"], "action_key": kwargs["action_key"]}
                )
                self.swipes += 1
                self.state += 1

        class Session:
            input_count = 0
            actions = []
            session_directory = Path.cwd()
            terminal_status = None
            blocker = None
            next_action = None

            def observe(self, capture, *, label):
                return capture(label)

            def run_action(self, **kwargs):
                before = kwargs["capture"]("before")
                kwargs["dispatch"](before)
                after = kwargs["capture"]("after")
                kwargs["recognize"](after)
                return SimpleNamespace(status="completed")

        session = Session()
        runtime = Runtime(session)

        def signature(frame, *, ocr=None):
            del ocr
            state = int(frame[0, 0, 0])
            return ((f"row-{state}", state, 0, state + 1, 1),)

        def binding(frame, *, ocr=None):
            del ocr
            state = int(frame[0, 0, 0])
            return route.ResourceListSwipeBinding(
                lane=(360, 560, 432, 1177),
                start=(396, 1176),
                end=(396, 560),
                content_roi=(0, 200, 800, 1200),
                use_rois=((462, 300, 517, 348),),
                bulk_rois=(),
                signature=signature(frame),
            )

        with patch.object(route, "_recognize_home", return_value=home), patch.object(
            route, "_home_bag_target", return_value=(396, 1213, 462, 1247)
        ), patch.object(route, "_recognize_bag", return_value=bag), patch.object(
            route, "recognize_resources_screen", return_value=resources
        ), patch.object(
            route, "recognize_food_item_in_resources", return_value=not_food
        ), patch.object(
            route, "resource_list_content_signature", side_effect=signature
        ), patch.object(
            route, "bind_resource_list_swipe", side_effect=binding
        ), patch.object(route.time, "sleep"):
            result = route.run_daily_resource_item(runtime, session)

        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(runtime.swipes, route.MAX_RESOURCE_LIST_SWIPES)
        self.assertEqual(runtime.swipes, 6)
        self.assertEqual(session.input_count, 1 + 6)
        self.assertEqual(result["max_inputs"], 10)
        self.assertEqual(result["item_use_transport_calls"], 0)
        self.assertEqual(
            [row["action_key"] for row in session.actions],
            [
                "daily-resource-item:open-bag",
                *[
                    f"daily-resource-item:scroll:{index}:{index:064x}"
                    for index in range(1, 7)
                ],
            ],
        )

    def test_route_selects_resources_tab_when_bag_opens_on_other_category(self):
        frame = CapturedNativeFrame(
            frame=_frame(),
            png=b"",
            sha256="a" * 64,
            captured_monotonic=time.monotonic(),
            path=Path.cwd() / "daily-resource-item-tab-select-frame.png",
        )
        item_before = route.ResourceItemRecognition(
            route.RESOURCE_ITEM_STATE,
            True,
            target_identity=route.ITEM_TARGET_IDENTITY,
            target_roi=(70, 440, 730, 620),
            item_name="1K Food",
            owned_quantity=2,
            quantity=1,
            use_roi=(430, 500, 485, 528),
            inventory_quantity=2,
            food_resource=100,
            visual_evidence={
                "item_card": {
                    "proven": True,
                    "source": "visual-horizontal-separators",
                    "bounds": (70, 440, 730, 620),
                },
                "card_ownership_proven": True,
                "use_count": 1,
                "quantity_source": "explicit",
            },
            quantity_source="explicit",
            single_use_semantics_proven=True,
        )
        item_after = route.ResourceItemRecognition(
            route.RESOURCE_SUCCESSOR_STATE,
            False,
            item_name="1K Food",
            owned_quantity=1,
            quantity=1,
            inventory_quantity=1,
            food_resource=100,
        )
        home = {
            "state": "HOME",
            "recognized": True,
            "home_verified": True,
            "target_identity": route.HOME_TARGET_IDENTITY,
            "target_roi": (0, 1213, 800, 1280),
        }
        bag = {
            "state": "BAG",
            "recognized": True,
            "target_identity": route.BAG_TARGET_IDENTITY,
            "target_roi": (8, 190, 189, 218),
        }
        resources_ready = route.ResourceItemRecognition(
            "RESOURCES",
            True,
            target_identity=route.RESOURCES_TARGET_IDENTITY,
            target_roi=(8, 190, 189, 218),
        )
        resources_missing = route.ResourceItemRecognition(
            "UNKNOWN",
            False,
            reason="resources-tab-is-missing-or-ambiguous",
        )

        class Runtime:
            execute = True
            frame_max_age_seconds = 30

            def __init__(self, session):
                self.session = session
                self.input_count = 0
                self.capture_count = 0

            def capture(self, _label):
                self.capture_count += 1
                return CapturedNativeFrame(
                    frame=frame.frame,
                    png=b"",
                    sha256=f"{self.capture_count:064x}",
                    captured_monotonic=time.monotonic(),
                    path=Path.cwd()
                    / f"daily-resource-item-tab-select-{self.capture_count}.png",
                )

            def tap(self, _source, **kwargs):
                self.input_count += 1
                self.session.input_count = self.input_count
                self.session.actions.append(
                    {
                        "label": kwargs["action_key"],
                        "action_key": kwargs["action_key"],
                    }
                )

        class Session:
            input_count = 0
            actions = []
            session_directory = Path.cwd()
            terminal_status = None
            blocker = None
            next_action = None

            def observe(self, capture, *, label):
                return capture(label)

            def run_action(self, **kwargs):
                before = kwargs["capture"]("before")
                kwargs["dispatch"](before)
                after = kwargs["capture"]("after")
                return {"state": kwargs["recognize"](after)}

        session = Session()
        runtime = Runtime(session)
        resources_calls = {"n": 0}

        def resources_side_effect(frame, *, ocr=None):
            del frame, ocr
            resources_calls["n"] += 1
            # Settled observe before the optional tab tap sees another category.
            if resources_calls["n"] == 1:
                return resources_missing
            return resources_ready

        def food_side_effect(frame, *, ocr=None):
            del frame, ocr
            if any(
                row.get("action_key") == route.ITEM_USE_ACTION_KEY
                for row in session.actions
            ):
                return item_after
            return item_before

        with patch.object(route, "_recognize_home", return_value=home), patch.object(
            route, "_recognize_bag", return_value=bag
        ), patch.object(
            route, "recognize_resources_screen", side_effect=resources_side_effect
        ), patch.object(
            route,
            "bind_resources_category_tab",
            return_value=(8, 190, 189, 218),
        ), patch.object(
            route, "_home_bag_target", return_value=(100, 100, 140, 140)
        ), patch.object(
            route, "_return_home_target", return_value=(700, 1200, 760, 1260)
        ), patch.object(
            route,
            "recognize_food_item_in_resources",
            side_effect=food_side_effect,
        ), patch.object(route.time, "sleep"):
            result = route.run_daily_resource_item(runtime, session)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(session.input_count, 4)
        action_keys = [row["action_key"] for row in session.actions]
        self.assertEqual(
            action_keys,
            [
                "daily-resource-item:open-bag",
                "daily-resource-item:select-resources-tab",
                route.ITEM_USE_ACTION_KEY,
                "daily-resource-item:return-home",
            ],
        )


if __name__ == "__main__":
    unittest.main()
