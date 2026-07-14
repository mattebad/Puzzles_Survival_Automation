from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from scripts.alliance_help_live import create_predispatch_artifact, help_all_geometry, recognize_help_surface
from tasks.profile import HELP_ALL_ACTION, INDIVIDUAL_HELP_ACTION


ROOT = Path(__file__).resolve().parents[1]
LIVE_SOURCE = ROOT / "evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/help-all-validation-20260713/remote/alliance-help-1783981635-source.png"
LIVE_POST = ROOT / "evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/help-all-validation-20260713/remote/alliance-help-1783981635-post-1.png"
HISTORICAL_DB = ROOT / "evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/actions-after-release.sqlite3"


class AllianceHelpRecognitionTests(unittest.TestCase):
    def test_retained_source_distinguishes_both_buttons(self):
        result = recognize_help_surface(LIVE_SOURCE, 1000.0, str(LIVE_SOURCE))
        self.assertTrue(result["recognized"])
        self.assertTrue(result["help_all_visible"])
        self.assertTrue(result["individual_help_visible"])
        self.assertEqual(result["matched_text"], "Help All")

    def test_coordinates_and_lower_geometry_are_disjoint(self):
        self.assertTrue(INDIVIDUAL_HELP_ACTION.roi[0] <= 641 < INDIVIDUAL_HELP_ACTION.roi[2])
        self.assertTrue(INDIVIDUAL_HELP_ACTION.roi[1] <= 302 < INDIVIDUAL_HELP_ACTION.roi[3])
        self.assertFalse(HELP_ALL_ACTION.roi[1] <= 302 < HELP_ALL_ACTION.roi[3])
        geometry = help_all_geometry(HELP_ALL_ACTION.roi)
        self.assertEqual(geometry["center"], (400, 1228))
        self.assertTrue(geometry["center_y_gt_1150"])
        self.assertFalse(geometry["intersects_individual_region"])
        self.assertTrue(geometry["tap_inside_with_margin"])
        self.assertFalse(help_all_geometry(INDIVIDUAL_HELP_ACTION.roi)["valid"])

    def test_color_only_cannot_authorize_help_all(self):
        image = np.zeros((1280, 800, 3), dtype=np.uint8)
        x0, y0, x1, y1 = HELP_ALL_ACTION.roi
        image[y0:y1, x0:x1] = (0, 140, 255)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "orange-only.png"
            cv2.imwrite(str(path), image)
            result = recognize_help_surface(path, 1000.0, str(path))
        self.assertGreaterEqual(result["help_all_orange_ratio"], 0.35)
        self.assertFalse(result["help_all_visible"])
        self.assertIsNone(result["matched_text"])

    def test_predispatch_artifact_enforces_actual_help_all(self):
        detail = recognize_help_surface(LIVE_SOURCE, 1000.0, str(LIVE_SOURCE))
        with tempfile.TemporaryDirectory() as folder:
            artifact = create_predispatch_artifact(
                LIVE_SOURCE, detail, Path(folder) / "artifact.json", Path(folder) / "annotated.png"
            )
            self.assertEqual(artifact["target_action"], "ALLIANCE_HELP_ALL")
            self.assertEqual(artifact["matched_text"], "Help All")
            self.assertEqual(artifact["proposed_center"], [400, 1228])
            self.assertTrue((Path(folder) / "annotated.png").exists())

    def test_post_frame_proves_local_controls_disappeared(self):
        source = recognize_help_surface(LIVE_SOURCE, 1000.0, str(LIVE_SOURCE))
        post = recognize_help_surface(LIVE_POST, 1001.0, str(LIVE_POST), header_reference=LIVE_SOURCE)
        self.assertTrue(source["help_all_visible"])
        self.assertTrue(source["individual_help_visible"])
        self.assertTrue(post["help_all_visible"])
        self.assertFalse(post["individual_help_visible"])
        self.assertFalse(post["empty_state"])
        self.assertTrue(post["header_stable"])


    def test_first_lower_help_all_post_captures_no_request_popup(self):
        path = ROOT / "evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/help-all-semantic-fix-20260713/remote/alliance-help-1783986842-post-1.png"
        result = recognize_help_surface(path, 1001.0, str(path), header_reference=LIVE_SOURCE)
        self.assertTrue(result["no_help_request_visible"], result["transient_message_text"])
        self.assertIn("help", result["transient_message_text"])
        self.assertIn("request", result["transient_message_text"])

    def test_historical_journal_is_immutable(self):
        self.assertEqual(hashlib.sha256(HISTORICAL_DB.read_bytes()).hexdigest(),
                         "39c42b7a4c4f6d9ce135b397f364f4e4455b8050041a092835ccc49df1cf9790")


if __name__ == "__main__":
    unittest.main()
