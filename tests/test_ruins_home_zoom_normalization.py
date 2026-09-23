from __future__ import annotations

from types import SimpleNamespace
import unittest

import numpy as np

from scripts.home_atlas_bluestacks import HomeDriverDisposition
from scripts.ruins_challenge_bluestacks import RuinsIntegratedRoute


class RuinsHomeZoomNormalizationTests(unittest.TestCase):
    @staticmethod
    def _frame(digest: str):
        return SimpleNamespace(
            frame=np.zeros((1280, 800, 3), dtype=np.uint8),
            sha256=digest,
            captured_monotonic=1.0,
        )

    @staticmethod
    def _step(disposition: HomeDriverDisposition, digest: str, reason: str = "test"):
        return SimpleNamespace(
            disposition=disposition,
            source_frame_sha256=digest,
            reason=reason,
        )

    @staticmethod
    def _route(frames, steps):
        runtime = SimpleNamespace(captures=list(frames), zoom_calls=[])
        runtime.capture = lambda _label: runtime.captures.pop(0)
        runtime.dispatch_zoom_out = lambda source, facts, transport=None: (
            runtime.zoom_calls.append((source, facts, transport))
        )
        driver = SimpleNamespace(steps=list(steps), recorded=[])
        driver.observe = lambda _frame: driver.steps.pop(0)
        driver.record_zoom_input_dispatched = lambda digest: driver.recorded.append(
            digest
        )
        route = RuinsIntegratedRoute.__new__(RuinsIntegratedRoute)
        route.runtime = runtime
        route.home_driver = driver
        route.zoom_transport = None
        route.post_input_delay = 0.0
        return route, runtime, driver

    def test_canonical_home_requires_no_zoom(self):
        before = self._frame("a" * 64)
        route, runtime, _driver = self._route(
            [before], [self._step(HomeDriverDisposition.BIND, before.sha256)]
        )

        captured, reason = route._recover_home_zoom_before_ruins_binding()

        self.assertIs(captured, before)
        self.assertIsNone(reason)
        self.assertEqual(runtime.zoom_calls, [])

    def test_unknown_localization_blocks_without_campaign_bypass(self):
        before = self._frame("a" * 64)
        route, runtime, _driver = self._route(
            [before],
            [
                self._step(
                    HomeDriverDisposition.BLOCKED,
                    before.sha256,
                    "home_localization_ambiguous:unknown",
                )
            ],
        )

        captured, reason = route._recover_home_zoom_before_ruins_binding()

        self.assertIsNone(captured)
        self.assertEqual(
            reason, "home_zoom_recovery_blocked:home_localization_ambiguous:unknown"
        )
        self.assertEqual(runtime.zoom_calls, [])

    def test_supported_noncanonical_home_recovers_to_settled_frame(self):
        before = self._frame("a" * 64)
        immediate = self._frame("b" * 64)
        settled = self._frame("c" * 64)
        route, runtime, driver = self._route(
            [before, immediate, settled],
            [
                self._step(HomeDriverDisposition.RECOVER_ZOOM, "semantic-before"),
                self._step(HomeDriverDisposition.PAN, "semantic-settled"),
            ],
        )

        captured, reason = route._recover_home_zoom_before_ruins_binding()

        self.assertIs(captured, settled)
        self.assertIsNone(reason)
        self.assertEqual(driver.recorded, ["semantic-before"])
        self.assertEqual(len(runtime.zoom_calls), 1)

    def test_unchanged_settled_frame_blocks_after_one_zoom(self):
        before = self._frame("a" * 64)
        route, runtime, driver = self._route(
            [before, self._frame("b" * 64), self._frame("a" * 64)],
            [self._step(HomeDriverDisposition.RECOVER_ZOOM, "semantic-before")],
        )

        captured, reason = route._recover_home_zoom_before_ruins_binding()

        self.assertIsNone(captured)
        self.assertEqual(reason, "home_zoom_recovery_no_progress")
        self.assertEqual(driver.recorded, ["semantic-before"])
        self.assertEqual(len(runtime.zoom_calls), 1)


if __name__ == "__main__":
    unittest.main()
