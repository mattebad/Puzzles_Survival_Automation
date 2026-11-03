"""Actual Lab radial input must avoid the fixed event HUD."""

from pathlib import Path
import unittest

import cv2

from scripts import bioenhancer_free_research_route as bio


FIXTURES = Path(__file__).parent / "fixtures"


class BioenhancerRadialNativeTests(unittest.TestCase):
    def test_existing_clear_native_research_radial_still_binds(self):
        frame = cv2.imread(str(FIXTURES / "nova_praise_preflight/research-lab-radial-07f3d826.png"))
        control = bio.bind_research_radial_option(frame)
        self.assertIsNotNone(control)
        self.assertEqual(control.identity, "research-lab-radial-research")
        self.assertEqual(control.target_roi, (391, 544, 455, 608))

    def test_actual_event_covered_research_rejects_even_with_recognized_nova(self):
        frame = cv2.imread(str(FIXTURES / "bioenhancer_radial/radial-research-under-event-hud.png"))
        recognition = bio.recognize_nova_frame(frame, captured_monotonic=1., home_context_visible=True)
        self.assertTrue(recognition.observation.recognized)
        self.assertEqual(recognition.target("research-lab-nova"), (430, 578, 474, 622))
        self.assertIsNone(bio.bind_research_radial_option(frame))


if __name__ == "__main__":
    unittest.main()
