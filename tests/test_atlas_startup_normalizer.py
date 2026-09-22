from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from scripts.atlas_startup_normalizer import (
    AtlasStartupDisposition,
    BlueStacksAtlasStartupNormalizer,
)
from tasks.home_atlas import AmbiguityState, ZoomIdentity
from tasks.home_atlas_vision import frame_digest


def _localizer(state):
    class Localizer:
        canonical_reference = np.full((1280, 800, 3), 7, dtype=np.uint8)

        def localize(self, frame):
            return SimpleNamespace(
                recognized=state.get("recognized", False),
                zoom_identity=state.get("zoom_identity", ZoomIdentity.UNKNOWN),
                confidence=state.get("confidence", 0.0),
                residual_px=state.get("residual_px", 1.0),
                frame_sha256=state.get("frame_sha256", frame_digest(frame)),
                ambiguity_state=state.get("ambiguity_state", AmbiguityState.NONE),
                stale=state.get("stale", False),
                overlay=state.get("overlay", False),
            )

    return Localizer()


class AtlasStartupNormalizerTests(unittest.TestCase):
    def test_positive_overlay_blocks_canonical_startup_and_building_binding(self):
        from dataclasses import replace
        from scripts.startup_normalization import is_clean_home_frame
        from tasks.home_atlas_vision import bind_visible_building
        from tests.test_home_atlas_planner import building, localization

        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        canonical = replace(localization(), frame_sha256=frame_digest(frame))
        target = building(polygon=((300, 400), (440, 400), (440, 540), (300, 540)))
        normalizer = BlueStacksAtlasStartupNormalizer(
            _localizer({}), home_is_clean=is_clean_home_frame
        )
        with patch(
            "scripts.startup_normalization.classify_home_base_live",
            return_value={"state": "HOME_BASE", "recognized": True, "overlay": True},
        ):
            with self.subTest(admission="startup"):
                step = normalizer.observe(frame, localization=canonical)
                self.assertIs(step.disposition, AtlasStartupDisposition.BLOCKED)
            with self.subTest(admission="building_binding"):
                self.assertIsNone(
                    bind_visible_building(
                        frame, canonical, target, home_is_clean=is_clean_home_frame
                    )
                )

    def test_canonical_current_clean_home_is_ready(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        step = BlueStacksAtlasStartupNormalizer(_localizer(
            {
                "recognized": True,
                "zoom_identity": ZoomIdentity.FULLY_ZOOMED_OUT,
                "confidence": 0.6,
            }
        ), home_is_clean=lambda _frame: True).observe(frame)
        self.assertIs(step.disposition, AtlasStartupDisposition.READY)
        self.assertEqual(step.source_frame_sha256, frame_digest(frame))

    def test_current_frame_localization_can_be_reused_without_recomputing(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        provided = _localizer(
            {
                "recognized": True,
                "zoom_identity": ZoomIdentity.FULLY_ZOOMED_OUT,
                "confidence": 0.9,
            }
        ).localize(frame)

        class FailingLocalizer:
            canonical_reference = frame

            def localize(self, _frame):
                raise AssertionError("localization was recomputed")

        step = BlueStacksAtlasStartupNormalizer(FailingLocalizer(), home_is_clean=lambda _frame: True).observe(
            frame,
            localization=provided,
        )

        self.assertIs(step.disposition, AtlasStartupDisposition.READY)

    def test_supported_noncanonical_zoom_is_recoverable(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        for identity in (ZoomIdentity.ZOOMED_IN, ZoomIdentity.INTERMEDIATE):
            with self.subTest(identity=identity):
                step = BlueStacksAtlasStartupNormalizer(_localizer(
                    {
                        "recognized": False,
                        "zoom_identity": identity,
                        "confidence": 0.92,
                    }
                ), home_is_clean=lambda _frame: True).observe(frame)
                self.assertIs(step.disposition, AtlasStartupDisposition.RECOVER_ZOOM)
                self.assertEqual(step.recovery_input_ordinal, 1)

    def test_unknown_overlay_stale_ambiguous_and_nonfinite_block(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        states = (
            {"zoom_identity": ZoomIdentity.UNKNOWN, "confidence": 0.0},
            {
                "zoom_identity": ZoomIdentity.ZOOMED_IN,
                "confidence": 0.95,
                "overlay": True,
            },
            {
                "zoom_identity": ZoomIdentity.ZOOMED_IN,
                "confidence": 0.95,
                "stale": True,
            },
            {
                "zoom_identity": ZoomIdentity.ZOOMED_IN,
                "confidence": 0.95,
                "ambiguity_state": AmbiguityState.CONFLICTING_TRANSFORMS,
            },
            {
                "recognized": True,
                "zoom_identity": ZoomIdentity.FULLY_ZOOMED_OUT,
                "confidence": float("nan"),
            },
        )
        with patch(
            "scripts.home_atlas_bluestacks.classify_zoom",
            return_value=SimpleNamespace(identity=ZoomIdentity.UNKNOWN, confidence=0.0),
        ):
            for state in states:
                with self.subTest(state=state):
                    step = BlueStacksAtlasStartupNormalizer(_localizer(state), home_is_clean=lambda _frame: True).observe(
                        frame
                    )
                    self.assertIs(step.disposition, AtlasStartupDisposition.BLOCKED)

    def test_repeated_frame_and_maximum_input_exhaustion_block(self):
        first = np.zeros((1280, 800, 3), dtype=np.uint8)
        second = np.full((1280, 800, 3), 1, dtype=np.uint8)
        normalizer = BlueStacksAtlasStartupNormalizer(_localizer(
            {
                "zoom_identity": ZoomIdentity.INTERMEDIATE,
                "confidence": 0.92,
            }
        ), home_is_clean=lambda _frame: True, maximum_zoom_inputs=1,)
        planned = normalizer.observe(first)
        repeated = normalizer.observe(first)
        self.assertEqual(repeated.reason, "repeated_zoom_recovery_frame")
        normalizer.record_zoom_input_dispatched(planned.source_frame_sha256)
        exhausted = normalizer.observe(second)
        self.assertEqual(exhausted.reason, "maximum_zoom_recovery_inputs")

    def test_dispatch_accounting_requires_semantic_digest(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        normalizer = BlueStacksAtlasStartupNormalizer(_localizer(
            {
                "zoom_identity": ZoomIdentity.ZOOMED_IN,
                "confidence": 0.92,
            }
        ), home_is_clean=lambda _frame: True)
        planned = normalizer.observe(frame)
        with self.assertRaises(ValueError):
            normalizer.record_zoom_input_dispatched("png-byte-digest")
        normalizer.record_zoom_input_dispatched(planned.source_frame_sha256)
        self.assertEqual(normalizer.zoom_inputs, 1)

    def test_recovery_ceiling_is_two_even_for_legacy_larger_request(self):
        normalizer = BlueStacksAtlasStartupNormalizer(_localizer(ZoomIdentity.ZOOMED_IN), home_is_clean=lambda _frame: True, maximum_zoom_inputs=4,)

        self.assertEqual(normalizer.maximum_zoom_inputs, 2)


if __name__ == "__main__":
    unittest.main()
