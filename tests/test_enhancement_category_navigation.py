"""Commander tabs select categories; only a fresh item frame grants an item target."""
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import enhancement_bluestacks as native
from scripts.bluestacks_native_runtime import captured_native_frame_from_png
from tests.support.enhancement import CategorySession


HOME, WRONG_TAB, CORRECT_TAB, CATEGORY_ITEM, ITEM_BEFORE = range(1, 6)
UNKNOWN, AMBIGUOUS, UNSELECTED_ITEM = range(6, 9)
PORTRAIT = (4, 40, 84, 123)
CATEGORY = (260, 75, 370, 135)
STALE_ITEM = (200, 250, 280, 330)
FRESH_ITEM = (430, 290, 510, 370)


class CategoryRuntime:
    def __init__(self, scenario):
        self.scenario = scenario
        self.session = Path("offline-category-navigation")
        self.inputs, self.captures, self.journal = [], [], []
        self.ordinal = 0

    def capture(self, label):
        if label == "home-source" or label == "home-to-commander-immediate-before":
            marker = HOME
        elif label.startswith("home-to-commander-"):
            marker = {"unknown_tab": UNKNOWN, "ambiguous_tab": AMBIGUOUS,
                      "correct_tab": CORRECT_TAB}.get(self.scenario, WRONG_TAB)
        elif label == "select-enhancement-category-immediate-before":
            marker = {"stale_category": UNKNOWN,
                      "already_selected_category": CORRECT_TAB}.get(self.scenario, WRONG_TAB)
        elif label.startswith("select-enhancement-category-"):
            if self.scenario == "unknown_category_post":
                marker = UNKNOWN
            elif self.scenario == "unselected_category_post":
                marker = UNSELECTED_ITEM
            elif self.scenario == "delayed_category" and (
                    label.endswith("immediate-post") or label.endswith("settled-1")):
                marker = UNSELECTED_ITEM
            else:
                marker = CATEGORY_ITEM
        elif label == "select-equipped-enhancement-item-immediate-before":
            marker = UNKNOWN if self.scenario == "unknown_item_before" else ITEM_BEFORE
        elif label.startswith("select-equipped-enhancement-item-"):
            marker = UNKNOWN
        else:
            raise AssertionError(f"route advanced beyond the unproven item successor: {label}")
        self.ordinal += 1
        image = np.full((1280, 800, 3), marker, np.uint8)
        image[0, 0] = self.ordinal
        ok, encoded = cv2.imencode(".png", image)
        assert ok
        capture = captured_native_frame_from_png(encoded.tobytes(),
            path=self.session / "frames" / f"{self.ordinal}-{label}.png",
            captured_monotonic=float(self.ordinal))
        self.captures.append((label, marker, capture))
        return capture

    def tap(self, before, **kwargs):
        if kwargs["target_identity"] not in {"commander-profile-portrait", "category-select:module", "item-select:module"}:
            raise AssertionError("unproven item successor cannot reach Enhance or Resource")
        self.inputs.append({**kwargs, "source_marker": int(before.frame[10, 10, 0]), "source_sha256": before.sha256})

    def reconcile(self, key, status, post, reason):
        self.journal.append((key, status, post.sha256))


class EnhancementCategoryNavigationTests(unittest.TestCase):
    def run_case(self, scenario):
        runtime, session = CategoryRuntime(scenario), CategorySession()
        calls = []
        def pixels(frame):
            return frame.frame if hasattr(frame, "frame") else frame
        def home(frame, *, source_frame_sha256, **kwargs):
            valid = int(pixels(frame)[10, 10, 0]) == HOME
            return native.HomeRecognition(valid, "HOME" if valid else "UNKNOWN", "fixture", source_frame_sha256,
                portrait_target=PORTRAIT if valid else None)
        def commander(frame, *, stage, source_frame_sha256, **kwargs):
            marker = int(pixels(frame)[10, 10, 0])
            calls.append((marker, stage))
            if stage == "tab" and marker in {WRONG_TAB, CORRECT_TAB}:
                return native.StageRecognition(stage, True, "fixture", source_frame_sha256,
                    category_selected=marker == CORRECT_TAB, category_target=CATEGORY)
            if stage == "item" and marker in {CATEGORY_ITEM, ITEM_BEFORE, UNSELECTED_ITEM}:
                return native.StageRecognition(stage, True, "fixture", source_frame_sha256,
                    category_selected=marker != UNSELECTED_ITEM, category_target=CATEGORY,
                    item_target=FRESH_ITEM if marker == ITEM_BEFORE else STALE_ITEM)
            return native.StageRecognition(stage, False, "fixture", source_frame_sha256)
        route = native.EnhancementIntegratedRoute(runtime, variant="module", reset_identity="current-reset", session=session)
        with patch.object(native, "recognize_home_frame", side_effect=home), \
                patch.object(native, "recognize_commander_stage", side_effect=commander), \
                patch.object(native, "_default_ocr", side_effect=AssertionError("OCR is outside these transition checks")), \
                patch.object(native.time, "sleep"):
            result = route._run_single()
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["terminal_recognized"])
        self.assertEqual(result["resource_affecting_dispatch_count"], 0)
        self.assertFalse(route.resource_dispatch_keys)
        self.assertEqual(result["dispatch_count"], len(runtime.inputs))
        self.assertEqual(session.input_count, len(runtime.inputs))
        return runtime, calls

    def test_wrong_tab_selects_category_once_then_binds_fresh_item_once(self):
        runtime, calls = self.run_case("wrong_tab")
        self.assertEqual([row["target_identity"] for row in runtime.inputs],
            ["commander-profile-portrait", "category-select:module", "item-select:module"])
        self.assertEqual([row["target_roi"] for row in runtime.inputs], [PORTRAIT, CATEGORY, FRESH_ITEM])
        self.assertEqual(runtime.inputs[-1]["source_marker"], ITEM_BEFORE)
        self.assertIn((WRONG_TAB, "tab"), calls)
        self.assertIn((CATEGORY_ITEM, "item"), calls)
        self.assertIn((ITEM_BEFORE, "item"), calls)
        self.assertNotIn((WRONG_TAB, "item"), calls)

    def test_correct_tab_skips_category_but_recaptures_a_fresh_item_target(self):
        runtime, calls = self.run_case("correct_tab")
        self.assertEqual([row["target_identity"] for row in runtime.inputs], ["commander-profile-portrait", "item-select:module"])
        self.assertEqual(runtime.inputs[-1]["target_roi"], FRESH_ITEM)
        self.assertEqual(runtime.inputs[-1]["source_marker"], ITEM_BEFORE)
        self.assertIn((CORRECT_TAB, "tab"), calls)
        self.assertIn((ITEM_BEFORE, "item"), calls)

    def test_unknown_or_ambiguous_tab_successor_stops_after_portrait(self):
        for scenario in ("unknown_tab", "ambiguous_tab"):
            with self.subTest(scenario=scenario):
                runtime, _ = self.run_case(scenario)
                self.assertEqual([row["target_identity"] for row in runtime.inputs], ["commander-profile-portrait"])
                polls = [label for label, _, _ in runtime.captures if label.startswith("home-to-commander-settled")]
                self.assertEqual(len(polls), native.MAX_SETTLE_POLLS)

    def test_unknown_or_changed_category_before_cannot_send_category_or_item(self):
        for scenario in ("stale_category", "already_selected_category"):
            with self.subTest(scenario=scenario):
                runtime, _ = self.run_case(scenario)
                self.assertEqual([row["target_identity"] for row in runtime.inputs], ["commander-profile-portrait"])

    def test_category_animation_is_observed_without_another_category_tap(self):
        runtime, _ = self.run_case("delayed_category")
        self.assertEqual([row["target_identity"] for row in runtime.inputs],
            ["commander-profile-portrait", "category-select:module", "item-select:module"])
        polls = [label for label, _, _ in runtime.captures if label.startswith("select-enhancement-category-settled")]
        self.assertEqual(len(polls), 2)
        self.assertEqual(runtime.inputs[-1]["target_roi"], FRESH_ITEM)

    def test_unknown_or_unselected_category_successor_cannot_grant_item_input(self):
        for scenario in ("unknown_category_post", "unselected_category_post"):
            with self.subTest(scenario=scenario):
                runtime, _ = self.run_case(scenario)
                self.assertEqual([row["target_identity"] for row in runtime.inputs],
                    ["commander-profile-portrait", "category-select:module"])
                polls = [label for label, _, _ in runtime.captures if label.startswith("select-enhancement-category-settled")]
                self.assertEqual(len(polls), native.MAX_SETTLE_POLLS)

    def test_unknown_fresh_item_frame_cannot_reuse_category_successor_target(self):
        runtime, _ = self.run_case("unknown_item_before")
        self.assertEqual([row["target_identity"] for row in runtime.inputs],
            ["commander-profile-portrait", "category-select:module"])


if __name__ == "__main__":
    unittest.main()
