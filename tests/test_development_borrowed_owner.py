"""Existing development actions may borrow, but never replace, a live service owner."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

from scripts import navigation_development_boundary as boundary
from scripts.bluestacks_native_runtime import CapturedNativeFrame


class DevelopmentBorrowedOwnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.patch = patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", self.root / "lock.sqlite3")
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.owner = boundary.RuntimeInputLock(owner="service", invocation_id="service-invocation")
        self.addCleanup(self.owner.release)

    def session(self, checkpoint=lambda: None, **kwargs):
        return boundary.DevelopmentSession(
            owner="route", invocation_id="route-invocation", session_directory=self.root / "route",
            runtime_input_lock=self.owner, checkpoint=checkpoint, **kwargs,
        )

    def capture(self, label):
        raw = label.encode()
        return CapturedNativeFrame(np.zeros((1280, 800, 3), np.uint8), raw, hashlib.sha256(raw).hexdigest(), 1., self.root / f"{label}.png")

    def test_borrowed_session_retains_real_singleton_owner_on_normal_and_exception_exit(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                self.owner.acquire()
                session = self.session()
                session.session_directory = self.root / f"route-{fail}"
                try:
                    with session:
                        self.assertIs(session.runtime_input_lock, self.owner)
                        self.assertTrue(session.is_active)
                        with self.assertRaises(boundary.NavigationBoundaryError):
                            boundary.RuntimeInputLock(owner="second", invocation_id="second").acquire()
                        if fail:
                            raise RuntimeError("route stopped")
                except RuntimeError:
                    self.assertTrue(fail)
                self.owner.assert_held("service", "service-invocation")
                self.assertFalse(session.is_active)
                summary = json.loads((session.session_directory / "summary.json").read_text())
                self.assertEqual(summary["runtime_ownership"], "borrowed")
                self.assertFalse(summary["ownership_released"])
                self.assertTrue(summary["borrowed_owner_retained"])
                self.owner.release()

    def test_borrowing_requires_real_held_owner_and_checkpoint_pair(self):
        with self.assertRaises(boundary.NavigationBoundaryError):
            with self.session():
                self.fail("unheld lock admitted")
        self.assertFalse((self.root / "route").exists())
        for kwargs in ({"runtime_input_lock": self.owner}, {"checkpoint": lambda: None}, {"runtime_input_lock": object(), "checkpoint": lambda: None}):
            with self.subTest(kwargs=kwargs), self.assertRaises(boundary.DevelopmentSessionError):
                boundary.DevelopmentSession(owner="route", invocation_id="route", session_directory=self.root / "route", **kwargs)

    def test_stop_during_capture_or_authorization_blocks_before_dispatch_and_accounting(self):
        for stage in ("capture", "authorize"):
            with self.subTest(stage=stage):
                stopped = False
                def checkpoint():
                    if stopped:
                        raise RuntimeError("stop requested")
                def capture(label):
                    nonlocal stopped
                    frame = self.capture(label)
                    stopped = stage == "capture"
                    return frame
                def authorize(_frame):
                    nonlocal stopped
                    stopped = True
                dispatch = Mock()
                self.owner.acquire()
                session = self.session(checkpoint)
                session.session_directory = self.root / stage
                with session:
                    with self.assertRaisesRegex(RuntimeError, "stop requested"):
                        session.run_action(action_class="navigation", label="exit", capture=capture,
                                           dispatch=dispatch, recognize=lambda _frame: "home", authorize=authorize)
                    self.assertEqual(session.input_count, 0)
                dispatch.assert_not_called()
                self.assertTrue(self.owner.held)
                self.owner.release()

    def test_lost_owner_prevents_capture_and_nested_session_is_still_denied(self):
        self.owner.acquire()
        with self.session() as session:
            with self.assertRaises(boundary.DevelopmentSessionError):
                session.assert_held(self.owner.owner, self.owner.invocation_id)
            with self.assertRaisesRegex(boundary.DevelopmentSessionError, "nested"):
                with boundary.DevelopmentSession(owner="nested", invocation_id="nested", session_directory=self.root / "nested"):
                    self.fail("nested session admitted")
            self.owner.release()
            with self.assertRaises(boundary.NavigationBoundaryError):
                session.assert_held(session.owner, session.invocation_id)
            capture = Mock()
            with self.assertRaises(boundary.NavigationBoundaryError):
                session.observe(capture, label="denied")
            capture.assert_not_called()

    def test_summary_failure_clears_session_context_but_preserves_borrowed_owner(self):
        self.owner.acquire()
        session = self.session()
        with patch.object(session, "_write_summary", side_effect=OSError("evidence disk unavailable")):
            with self.assertRaises(OSError):
                with session:
                    pass
        self.assertFalse(session.is_active)
        self.owner.assert_held("service", "service-invocation")
        next_session = self.session()
        next_session.session_directory = self.root / "next-route"
        with next_session:
            self.assertIs(next_session.runtime_input_lock, self.owner)


if __name__ == "__main__":
    unittest.main()
