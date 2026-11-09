from __future__ import annotations

from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts import daily_resource_item_bluestacks as route

from tests.support.environment import requires_tesseract

PORTABLE_FIXTURES = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "resource_effect_authority"
    / "portable"
)


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
    @requires_tesseract
    def test_actual_native_inset_bag_binds_one_food_not_adjacent_use_or_bulk(self):
        # Unmodified #66 canary successor before any Use; not acceptance evidence.
        frame = cv2.imread(str(
            PORTABLE_FIXTURES / "native-bag-resource66-before-use-20261107.png"
        ))
        self.assertIsNotNone(frame)
        self.assertTrue(route._recognize_bag(frame)["recognized"])
        ready = route.recognize_food_item_in_resources(frame)
        self.assertTrue(route.resource_item_authorizeable(ready), ready)
        self.assertEqual((ready.item_name, ready.owned_quantity, ready.quantity), ("1K Food", 129810, 1))
        self.assertTrue(ready.bulk_visible)
        self.assertTrue(ready.bulk_disjoint_from_use)

        # Counterfactual only in test memory: other Use controls remain visible.
        missing = frame.copy()
        left, top, right, bottom = ready.target_roi
        missing[top:bottom, left:right] = (29, 29, 29)
        rejected = route.recognize_food_item_in_resources(missing)
        self.assertFalse(route.resource_item_authorizeable(rejected))

    @requires_tesseract
    def test_actual_bag_successor_binds_fragmented_resource_category(self):
        # Unmodified failed #66 canary, one Bag navigation and zero item Uses:
        # owner-plan-resource66-20261109T031902577493Z/native/
        # DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION-20261109T032157116950Z-c792ca4e/
        # daily-resource-item-native-20261109T032157219542Z/frames/
        # 0005-daily-resource-item-open-bag-settled.png
        # SHA256: a8617933ecd517d3c8c636fdc86b1370a1996c3d689629d7b3906430250b5383
        frame = cv2.imread(str(
            PORTABLE_FIXTURES / "native-bag-resource66-fragmented-category-20261109.png"
        ))
        self.assertIsNotNone(frame)
        bag = route._recognize_bag(frame)
        self.assertTrue(bag["recognized"], bag)
        self.assertEqual(
            bag["visual_evidence"]["selected_bag_category"], "resource_speedup",
        )
        resources = route.recognize_resources_screen(frame)
        self.assertTrue(resources.recognized, resources)
        # Recognizing the page must not authorize the clipped 1K Food row.
        self.assertFalse(route.resource_item_authorizeable(
            route.recognize_food_item_in_resources(frame),
        ))

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
        missing_count_rows = tuple(
            row for row in _item_rows("1K Food Use") if row[0] not in {"owned", "2"}
        )
        with patch.object(route, "_measure_resource_item_card", return_value=measured):
            missing_count = route.recognize_food_item(
                _frame(),
                ocr=_ocr(*missing_count_rows),
            )
        self.assertFalse(missing_count.recognized)
        self.assertIsNone(missing_count.owned_quantity)

        ambiguous_count_rows = (
            *_item_rows("1K Food Use"),
            ("owned", 100, 580, 60, 28),
            ("3", 165, 580, 15, 28),
        )
        with patch.object(route, "_measure_resource_item_card", return_value=measured):
            ambiguous_count = route.recognize_food_item(
                _frame(),
                ocr=_ocr(*ambiguous_count_rows),
            )
        self.assertFalse(ambiguous_count.recognized)
        self.assertIsNone(ambiguous_count.owned_quantity)

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
        before = {"inventory_quantity": 2}
        after = {"inventory_quantity": 1, "home_verified": True}
        self.assertTrue(route.resource_item_postcondition_verified(before, after))
        self.assertFalse(
            route.resource_item_postcondition_verified(
                before,
                {"inventory_quantity": 2, "home_verified": True},
            )
        )
        self.assertFalse(
            route.resource_item_postcondition_verified(
                before,
                {"inventory_quantity": 0, "home_verified": True},
            )
        )
        self.assertFalse(
            route.resource_item_postcondition_verified(
                before,
                {"inventory_quantity": 1},
            )
        )
        self.assertFalse(
            route._resource_delta_verified(
                {"inventory_quantity": 10},
                {"inventory_quantity": 8},
            )
        )
        self.assertFalse(
            route._resource_delta_verified(
                {"inventory_quantity": 10},
                {"inventory_quantity": 10},
            )
        )
        self.assertFalse(
            route._resource_delta_verified(
                {},
                {"inventory_quantity": 1},
            )
        )
        self.assertTrue(
            route._resource_delta_verified(
                {"inventory_quantity": 129680},
                {"inventory_quantity": 129679},
            )
        )

    def test_last_item_zero_after_keeps_pre_bound_identity_only_when_row_collapses(self):
        # Known 1->0 defect: the consumed last card disappears, so the zero
        # successor must come from the pre-Use binding plus an in-place collapse.
        measured = {
            "proven": True,
            "source": "visual-horizontal-separators",
            "bounds": (48, 440, 752, 600),
            "horizontal_separators": (440, 600),
        }
        above = (("10%", 140, 320, 40, 28), ("Build", 186, 320, 60, 28))

        def below(shift: int):
            return (
                ("2K", 100, 660 + shift, 30, 28),
                ("Food", 136, 660 + shift, 50, 28),
                ("Owned", 100, 710 + shift, 60, 28),
                ("10350", 165, 710 + shift, 60, 28),
            )

        frame = _paint_selected_bag_category(_frame())
        with patch.object(route, "_measure_resource_item_card", return_value=measured):
            before = route.recognize_food_item_in_resources(
                frame,
                ocr=_ocr(*_bag_category_rows(), *above, *_item_rows(owned=1), *below(0)),
            )
        self.assertTrue(route.resource_item_authorizeable(before), before)
        self.assertEqual(before.owned_quantity, 1)

        collapsed = route.recognize_food_item_after_use(
            frame, before=before, ocr=_ocr(*_bag_category_rows(), *above, *below(-169)),
        )
        self.assertTrue(collapsed.recognized, collapsed)
        self.assertEqual(collapsed.state, route.LAST_ITEM_CONSUMED_STATE)
        self.assertEqual(collapsed.target_identity, route.ITEM_TARGET_IDENTITY)
        self.assertEqual((collapsed.owned_quantity, collapsed.inventory_quantity), (0, 0))
        self.assertEqual(collapsed.visual_evidence["consumed_item_card_bounds"], before.target_roi)
        self.assertNotIn("item_card", collapsed.visual_evidence)
        self.assertTrue(route._resource_delta_verified(before, collapsed))

        shifted_above = tuple((text, x, y - 169, w, h) for text, x, y, w, h in above)
        for name, rows in (
            ("list scrolled", (*shifted_above, *below(-169))),
            ("card vanished without collapse", (*above, *below(0))),
        ):
            with self.subTest(name=name):
                rejected = route.recognize_food_item_after_use(
                    frame, before=before, ocr=_ocr(*_bag_category_rows(), *rows),
                )
                self.assertFalse(rejected.recognized)
                self.assertFalse(route._resource_delta_verified(before, rejected))

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
        frame_path = PORTABLE_FIXTURES / "session-2-terminal-home.png"
        retained = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        self.assertIsNotNone(retained)
        assert retained is not None

        altered = retained.copy()
        cv2.rectangle(
            altered,
            (route.HOME_BAG_ICON_ROI[0], route.HOME_BAG_ICON_ROI[1]),
            (route.HOME_BAG_ICON_ROI[2] - 1, route.HOME_BAG_ICON_ROI[3] - 1),
            (0, 0, 0),
            -1,
        )
        target = route._home_bag_target(retained, ocr=_ocr())
        altered_target = route._home_bag_target(altered, ocr=_ocr())
        blank_target = route._home_bag_target(_blank_frame(), ocr=_ocr())

        self.assertEqual(target, route.HOME_BAG_ICON_ROI)
        self.assertIsNone(altered_target)
        self.assertIsNone(blank_target)

    def test_current_compact_home_binds_bag_but_daily_screen_cannot(self):
        fixtures = Path(__file__).parent / "fixtures" / "daily_rewards_native"
        home = cv2.imread(str(fixtures / "native-home-compact-footer.png"))
        daily = cv2.imread(str(fixtures / "native-chest1-claimed-after-20261107.png"))
        self.assertEqual(route._home_bag_target(home, ocr=_ocr()), route.HOME_BAG_ICON_ROI)
        duplicate = home.copy()
        x0, y0, x1, y1 = route.HOME_BAG_ICON_ROI
        duplicate[y0:y1, 150:150 + x1 - x0] = home[y0:y1, x0:x1]
        self.assertIsNone(route._home_bag_target(duplicate, ocr=_ocr()))
        self.assertIsNone(route._home_bag_target(daily, ocr=_ocr()))

    def test_return_home_binding_fails_closed_without_proven_control(self):
        for label in ("home", "base", "close", "return"):
            with self.subTest(label=label):
                self.assertIsNone(
                    route._return_home_target(
                        _blank_frame(),
                        ocr=_ocr((label, 100, 100, 60, 28)),
                    )
                )

    @requires_tesseract
    def test_retained_resources_frame_binds_measured_back_arrow(self):
        frame_path = PORTABLE_FIXTURES / "session-1-transport-source.png"
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
        frame_path = PORTABLE_FIXTURES / "session-1-transport-source.png"
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
        ), patch.object(
            route, "resource_list_content_signature", return_value="synthetic-resource-list"
        ), patch.object(
            route, "time", SimpleNamespace(monotonic=time.monotonic, sleep=lambda _seconds: None)
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
                state = kwargs["recognize"](after)
                if (
                    str(state).casefold() == "unknown"
                    and kwargs.get("settled_successor") is not None
                ):
                    after = kwargs["settled_successor"]()
                    state = kwargs["recognize"](after)
                return SimpleNamespace(
                    status="completed"
                    if str(state).casefold() != "unknown"
                    else "unknown"
                )

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
        ), patch.object(route.time, "sleep", return_value=None):
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

    def test_swipe_ignores_mid_animation_item_until_settled(self):
        not_food = route.ResourceItemRecognition(
            route.RESOURCE_ITEM_STATE,
            False,
            item_name="1K Food",
        )
        ready_food = route.ResourceItemRecognition(
            route.RESOURCE_ITEM_STATE,
            True,
            target_identity=route.ITEM_TARGET_IDENTITY,
            target_roi=(0, 735, 800, 975),
            item_name="1K Food",
            owned_quantity=10,
            quantity=1,
            use_roi=(577, 833, 768, 897),
            inventory_quantity=10,
            visual_evidence={
                "item_card": {
                    "proven": True,
                    "source": "visual-horizontal-separators",
                    "bounds": (0, 735, 800, 975),
                },
                "card_ownership_proven": True,
                "use_count": 1,
                "quantity_source": "ordinary-use-implied-one",
            },
            quantity_source="ordinary-use-implied-one",
            single_use_semantics_proven=True,
        )

        class Runtime:
            frame_max_age_seconds = 30

            def __init__(self):
                self.state = 0

            def capture(self, label):
                if label.endswith("-settled"):
                    self.state = 2
                image = _blank_frame()
                image[0, 0, 0] = self.state
                return CapturedNativeFrame(
                    frame=image,
                    png=b"",
                    sha256=f"{self.state:064x}",
                    captured_monotonic=time.monotonic(),
                    path=Path.cwd() / f"{label}.png",
                )

            def swipe(self, _source, **_kwargs):
                self.state = 1

        class Session:
            def run_action(self, **kwargs):
                before = kwargs["capture"]("before")
                kwargs["dispatch"](before)
                immediate = kwargs["capture"]("after")
                state = kwargs["recognize"](immediate)
                self.assert_unknown = state
                settled = kwargs["settled_successor"]()
                state = kwargs["recognize"](settled)
                return SimpleNamespace(
                    status="completed"
                    if str(state).casefold() != "unknown"
                    else "unknown"
                )

        runtime = Runtime()
        session = Session()

        def signature(frame, *, ocr=None):
            del ocr
            state = int(frame[0, 0, 0])
            return ((f"row-{state}", state, 0, state + 1, 1),)

        def item(frame, *, ocr=None):
            del ocr
            return ready_food if int(frame[0, 0, 0]) == 1 else not_food

        binding = route.ResourceListSwipeBinding(
            lane=(360, 560, 432, 1177),
            start=(396, 1176),
            end=(396, 560),
            content_roi=(0, 200, 800, 1200),
            use_rois=((577, 833, 768, 897),),
            bulk_rois=(),
            signature=(("row-0", 0, 0, 1, 1),),
        )
        with patch.object(
            route, "recognize_resources_screen", return_value=SimpleNamespace(recognized=True)
        ), patch.object(
            route, "recognize_food_item_in_resources", side_effect=item
        ), patch.object(
            route, "resource_list_content_signature", side_effect=signature
        ), patch.object(
            route, "bind_resource_list_swipe", return_value=binding
        ), patch.object(route.time, "sleep", return_value=None):
            action, _before, after, settled_item, holder = route._swipe_list_action(
                runtime,
                session,
                ordinal=1,
                before_signature=binding.signature,
                ocr=None,
            )

        self.assertEqual(session.assert_unknown, "UNKNOWN")
        self.assertEqual(int(after.frame[0, 0, 0]), 2)
        self.assertTrue(route.resource_item_authorizeable(holder["immediate_post_item"]))
        self.assertFalse(route.resource_item_authorizeable(settled_item))
        self.assertTrue(holder["progressed"])
        self.assertEqual(action.status, "completed")

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
        ), patch.object(route.time, "sleep"), patch.object(
            route, "resource_list_content_signature", return_value="synthetic-resource-list"
        ):
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


class ResourceHomeRecoveryTests(unittest.TestCase):
    def _recover(self, *, source="bag", immediate="bag", successor="home"):
        from scripts import navigation_development_boundary as boundary
        from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime

        payloads = {
            "bag": (PORTABLE_FIXTURES / "native-bag-resource66-before-use-20261107.png").read_bytes(),
            "home": (PORTABLE_FIXTURES / "session-2-terminal-home.png").read_bytes(),
            "unknown": cv2.imencode(".png", _blank_frame())[1].tobytes(),
        }

        class Transport:
            def __init__(self):
                self.captures = 0
                self.taps = []

            def capture_png(self):
                self.captures += 1
                state = successor if self.taps else (source if self.captures == 1 else immediate)
                return payloads[state]

            def dispatch_tap(self, point):
                self.taps.append(point)

        transport = Transport()
        with tempfile.TemporaryDirectory() as directory, patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", Path(directory) / "lock.sqlite3"
        ), patch.object(route.time, "sleep", return_value=None):
            with boundary.DevelopmentSession(
                owner="resource-recovery-test", invocation_id="one-back",
                session_directory=Path(directory) / "session", max_inputs=1,
            ) as session:
                runtime = LocalBlueStacksRuntime(transport, Path(directory) / "native", execute=True)
                runtime.max_inputs = 1
                result = route.recover_resource_item_home(runtime, session)
                return result, transport.taps

    @requires_tesseract
    def test_actual_bag_one_back_proves_home_without_any_food_effect(self):
        result, taps = self._recover()
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["terminal_home_verified"])
        self.assertEqual(result["completion_scope"], "navigation_only")
        self.assertEqual(result["input_count"], 1)
        self.assertEqual(result["item_use_transport_calls"], 0)
        self.assertFalse(result["resource_delta_verified"])
        self.assertEqual(len(taps), 1)
        self.assertLess(taps[0][0], 140)
        self.assertLess(taps[0][1], 90)

    @requires_tesseract
    def test_already_home_requires_no_back_or_route_entry(self):
        result, taps = self._recover(source="home", immediate="home")
        self.assertTrue(result["terminal_home_verified"])
        self.assertEqual(result["input_count"], 0)
        self.assertEqual(taps, [])

    @requires_tesseract
    def test_unknown_source_cannot_dismiss_or_use_anything(self):
        result, taps = self._recover(source="unknown", immediate="unknown")
        self.assertEqual(result["status"], "evidence_required")
        self.assertFalse(result["terminal_home_verified"])
        self.assertEqual(taps, [])

    @requires_tesseract
    def test_changed_immediate_source_prevents_transport(self):
        with self.assertRaises(route.DailyResourceItemRecognitionError):
            self._recover(immediate="unknown")

    @requires_tesseract
    def test_unrecognized_successor_stops_after_one_back_without_retry(self):
        result, taps = self._recover(successor="unknown")
        self.assertEqual(result["status"], "evidence_required")
        self.assertFalse(result["terminal_home_verified"])
        self.assertEqual(len(taps), 1)
        self.assertEqual(result["item_use_transport_calls"], 0)

    def test_missing_live_authorization_rejects_before_opening_runtime(self):
        from scripts import pnsctl
        from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime

        for live, yes in ((False, False), (True, False), (False, True)):
            with self.subTest(live=live, yes=yes), patch.object(
                LocalBlueStacksRuntime, "connect"
            ) as connect:
                with self.assertRaises(pnsctl.OperatorError):
                    pnsctl.development_session_recover_resource_home(live=live, yes=yes)
                connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
