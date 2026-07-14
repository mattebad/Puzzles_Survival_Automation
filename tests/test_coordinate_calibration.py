import json
import unittest
from pathlib import Path

from calibration import (
    AffineCorrespondence,
    CoordinateTransform,
    Insets,
    ScreenFamilyCorrection,
    ScreenGeometry,
    fit_axis_aligned_affine,
)


SOURCE = ScreenGeometry(400, 652)
DESTINATION = ScreenGeometry(800, 1280)
ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "research" / "gnbots_bliss_coordinate_calibration.json"


class CoordinateCalibrationTests(unittest.TestCase):
    def test_direct_two_x(self):
        transform = CoordinateTransform("direct-2x", SOURCE, DESTINATION, 2.0, 2.0)
        self.assertEqual(transform.transform_point((158, 621)), (316.0, 1242.0))

    def test_two_x_after_source_top_inset(self):
        transform = CoordinateTransform.from_viewports(
            "top-inset-12",
            ScreenGeometry(400, 652, Insets(top=12)),
            DESTINATION,
        )
        self.assertEqual(transform.transform_point((200, 57)), (400.0, 90.0))

    def test_two_x_after_source_bottom_inset(self):
        transform = CoordinateTransform.from_viewports(
            "bottom-inset-12",
            ScreenGeometry(400, 652, Insets(bottom=12)),
            DESTINATION,
        )
        self.assertEqual(transform.transform_point((200, 57)), (400.0, 114.0))

    def test_independent_axis_scaling(self):
        transform = CoordinateTransform(
            "independent",
            SOURCE,
            DESTINATION,
            scale_x=2.0,
            scale_y=1280 / 652,
        )
        x, y = transform.transform_point((200, 57))
        self.assertEqual(x, 400.0)
        self.assertAlmostEqual(y, 111.90184049079755)

    def test_axis_aligned_affine_fit_and_residuals(self):
        correspondences = (
            AffineCorrespondence("a", (10, 20), (25, 37), "a.png"),
            AffineCorrespondence("b", (50, 70), (105, 112), "b.png"),
            AffineCorrespondence("c", (90, 120), (185, 187), "c.png"),
        )
        transform = fit_axis_aligned_affine(
            "affine",
            SOURCE,
            DESTINATION,
            correspondences,
        )
        self.assertAlmostEqual(transform.scale_x, 2.0)
        self.assertAlmostEqual(transform.offset_x, 5.0)
        self.assertAlmostEqual(transform.scale_y, 1.5)
        self.assertAlmostEqual(transform.offset_y, 7.0)
        self.assertTrue(all(item.total_error < 1e-9 for item in transform.residuals(correspondences)))

    def test_normalized_roi_transform_rejects_xywh_mistake(self):
        transform = CoordinateTransform("direct-2x", SOURCE, DESTINATION, 2.0, 2.0)
        self.assertEqual(
            transform.transform_xyxy((282, 202, 385, 510)),
            (564.0, 404.0, 770.0, 1020.0),
        )
        with self.assertRaisesRegex(ValueError, "normalized xyxy"):
            transform.transform_xyxy((282, 202, 103, 308))

    def test_screen_family_correction_requires_multiple_anchors(self):
        with self.assertRaisesRegex(ValueError, "at least two anchors"):
            ScreenFamilyCorrection("quest", 2, -3, ("only-one",))
        correction = ScreenFamilyCorrection("quest", 2, -3, ("quest-open", "daily-tab"))
        transform = CoordinateTransform(
            "corrected",
            SOURCE,
            DESTINATION,
            2.0,
            2.0,
            correction=correction,
        )
        self.assertEqual(transform.transform_point((10, 10)), (22.0, 17.0))

    def test_candidates_are_never_production_authorized(self):
        transform = CoordinateTransform("direct-2x", SOURCE, DESTINATION, 2.0, 2.0)
        candidate = transform.candidate((158, 621), "GNB-DAILY-QUEST-CLAIMS")
        self.assertFalse(candidate.production_authorized)
        self.assertEqual(candidate.manifest_id, "GNB-DAILY-QUEST-CLAIMS")

    def test_safe_containment_uses_raw_target_geometry(self):
        self.assertTrue(CoordinateTransform.point_inside_roi((400, 105), (300, 70, 500, 140), 10))
        self.assertFalse(CoordinateTransform.point_inside_roi((400, 190), (300, 70, 500, 140), 10))

    def test_bottom_navigation_correction_has_two_real_anchors(self):
        correction = ScreenFamilyCorrection(
            "bottom-navigation",
            -3.5,
            -43.5,
            ("quest-open", "more-open"),
        )
        transform = CoordinateTransform(
            "direct-2x-bottom-navigation",
            SOURCE,
            DESTINATION,
            2.0,
            2.0,
            correction=correction,
        )
        self.assertEqual(transform.transform_point((158, 621)), (312.5, 1198.5))
        self.assertEqual(transform.transform_point((376, 623)), (748.5, 1202.5))
        self.assertTrue(transform.point_inside_roi((312.5, 1198.5), (250, 1130, 410, 1280), 10))
        self.assertTrue(transform.point_inside_roi((748.5, 1202.5), (680, 1130, 800, 1280), 10))

    def test_report_is_explicitly_non_authorizing(self):
        report = json.loads(REPORT.read_text(encoding="utf-8"))
        self.assertFalse(report["production_authorized"])
        self.assertEqual(report["selection"]["global_model"], "direct-2x")
        self.assertTrue(all(not item["production_authorized"] for item in report["screen_family_corrections"]))
        self.assertTrue(
            all(not item["production_authorized"] for item in report["provisional_roi_examples"])
        )


if __name__ == "__main__":
    unittest.main()
