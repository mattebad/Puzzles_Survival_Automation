from __future__ import annotations

import unittest
from pathlib import Path

from scripts.alliance_help_live import recognize_help_surface


ROOT = Path(__file__).resolve().parents[1]
RETAINED_SPEEDUP = ROOT / "evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/remote-complete/help-go-post-002.png"
LIVE_SOURCE = ROOT / "evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/help-all-validation-20260713/remote/alliance-help-1783981635-source.png"
LIVE_POST = ROOT / "evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/help-all-validation-20260713/remote/alliance-help-1783981635-post-1.png"


class AllianceHelpRecognitionTests(unittest.TestCase):
    def test_retained_speedup_surface_recognizes_help_all(self):
        result = recognize_help_surface(RETAINED_SPEEDUP, 1000.0, str(RETAINED_SPEEDUP))
        self.assertTrue(result["recognized"])
        self.assertTrue(result["help_all_visible"])
        self.assertGreaterEqual(result["orange_ratio"], 0.35)

    def test_post_frame_uses_local_header_and_accepts_help_all_disappearance(self):
        source = recognize_help_surface(LIVE_SOURCE, 1000.0, str(LIVE_SOURCE))
        post = recognize_help_surface(LIVE_POST, 1001.0, str(LIVE_POST), header_reference=LIVE_SOURCE)
        self.assertTrue(source["help_all_visible"])
        self.assertFalse(post["help_all_visible"])
        self.assertTrue(post["header_stable"])
        self.assertEqual(post["screen_state"], "SPEEDUP_HELP")


if __name__ == "__main__":
    unittest.main()
