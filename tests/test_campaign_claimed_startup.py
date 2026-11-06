"""Offline claimed-startup ledger tests; fabricated successors are not live evidence."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from automation_service.campaign import CampaignRunner
from scripts.bluestacks_native_runtime import captured_native_frame_from_png
from scripts.bluestacks_popup_recognition import recognize_reset_popup
from tasks.campaign_auto_battle import CampaignScreen
from tests.ocr_memo import install_module_memo


def setUpModule():
    # Identical frames are replayed across tests; run real Tesseract once per unique input.
    install_module_memo()

FIXTURE = Path(__file__).parent / "fixtures/campaign_startup_recovery/vip-chapter-source.png"


class ClaimedNormalizationLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.session = Path(self.tmp.name)
        self.events = self.session / "events.jsonl"
        self.runner = CampaignRunner(adb="forbidden", serial="forbidden", output_directory=self.session,
                                     cadence_seconds=60, settle_seconds=0)
        self.key = "campaign-initial-startup-overlay"
        self.runtime = SimpleNamespace(events=self.events, session=self.session, input_count=1,
                                       action_keys={self.key})
        self.popup = FIXTURE.read_bytes()
        self.assertEqual(hashlib.sha256(self.popup).hexdigest(),
                         "71d306b16a24af414a5c6cf17771cdfcda6a579792c105551260439135faeb4f")
        self.popup_detail = recognize_reset_popup(cv2.imdecode(np.frombuffer(self.popup, np.uint8), cv2.IMREAD_COLOR))
        self.assertTrue(self.popup_detail.get("recognized"))
        ok, encoded = cv2.imencode(".png", np.zeros((1280, 800, 3), dtype=np.uint8))
        self.assertTrue(ok)
        self.after = encoded.tobytes()

    def capture(self, name, png, stamp, label=None):
        path = self.session / name
        path.write_bytes(png)
        row = {"type": "capture", "path": str(path), "sha256": hashlib.sha256(png).hexdigest(),
               "captured_monotonic": stamp}
        if label is not None:
            row["label"] = label
        return row

    def build(self, **changes):
        # Mirrors the journal recover_contextual_startup_overlay writes through the native runtime:
        # proposal capture, labelled dispatch-before capture, dispatch, labelled post capture,
        # confirmed reconcile, then the settled frame the service hands to the ledger.
        proposal = self.capture("proposal.png", self.popup, 0.5, "contextual-source")
        source = self.capture("source.png", self.popup, 1.0, "contextual-vip-popup-dispatch-before")
        post = self.capture("post.png", self.after, 2.0, "contextual-vip-popup-post")
        final = self.capture("successor.png", self.after, 3.0, "campaign-service-initial-home")
        target = self.popup_detail["target"]
        dispatch = {"type": "dispatch", "source_sha256": source["sha256"], "action_key": self.key,
                    "target_identity": "reset-popup-close", "target_roi": target,
                    "point": [(target[0] + target[2]) // 2, (target[1] + target[3]) // 2],
                    "action_class": "navigation", "consequential": False, "continuation_of": None,
                    "execute": True}
        dispatch.update(changes)
        reconcile = {"type": "reconcile", "action_key": dispatch["action_key"], "status": "confirmed",
                     "post_sha256": post["sha256"], "post_path": post["path"], "reason": "vip_popup_dismissed"}
        self.events.write_text("".join(json.dumps(row) + "\n"
                                       for row in (proposal, source, dispatch, post, reconcile, final)))
        return captured_native_frame_from_png(self.after, captured_monotonic=3.0, path=Path(final["path"]))

    def check(self, frame):
        found = SimpleNamespace(observation=SimpleNamespace(recognized=True, screen=CampaignScreen.CHAPTER_MAP,
                                                            overlay_state="none"), targets=())
        with patch("automation_service.campaign.recognize_campaign_frame", return_value=found):
            return self.runner._normalization_ledger(self.runtime, b"", 0, frame, "initial")

    def test_exact_popup_dispatch_and_fresh_successor_are_bound(self):
        ledger = self.check(self.build())
        self.assertEqual(ledger["input_count"], 1)
        self.assertEqual(ledger["dispatches"][0]["surface"], "VIP_POINTS_GET_PTS")
        self.assertEqual(ledger["dispatches"][0]["native_after"], 1)

    def test_dismissal_without_retained_labelled_proposal_fails_closed(self):
        frame = self.build()
        rows = [json.loads(line) for line in self.events.read_text().splitlines()]
        self.events.write_text("".join(json.dumps(row) + "\n" for row in rows[1:]))
        with self.assertRaisesRegex(ValueError, "no retained proposal"):
            self.check(frame)
        rows[1]["label"] = "contextual-source"
        self.events.write_text("".join(json.dumps(row) + "\n" for row in rows))
        with self.assertRaisesRegex(ValueError, "not continuous"):
            self.check(frame)

    def test_wrong_roi_target_and_unexplained_count_fail_closed(self):
        for change in ({"target_roi": [1, 2, 3, 4]}, {"target_identity": "arbitrary-navigation"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.check(self.build(**change))
        self.runtime.input_count = 2
        with self.assertRaises(ValueError):
            self.check(self.build())

    def test_changed_source_and_duplicate_key_fail_closed(self):
        frame = self.build()
        (self.session / "source.png").write_bytes(self.after)
        with self.assertRaises(ValueError):
            self.check(frame)
        self.runtime.action_keys.clear()
        with self.assertRaises(ValueError):
            self.check(self.build())

    def test_checkpoint_loss_during_journal_replay_fails_closed(self):
        frame = self.build()
        calls = []
        def checkpoint():
            calls.append(1)
            if len(calls) == 3:
                raise RuntimeError("lease lost")
        self.runtime.checkpoint = checkpoint
        with self.assertRaisesRegex(RuntimeError, "lease lost"):
            self.check(frame)
        self.assertEqual(len(calls), 3)

    def test_zero_input_requires_journal_bound_settled_frame(self):
        self.runtime.input_count = 0
        final = self.capture("home.png", self.after, 1.0)
        self.events.write_text(json.dumps(final) + "\n")
        frame = captured_native_frame_from_png(self.after, captured_monotonic=1.0, path=Path(final["path"]))
        self.assertEqual(self.check(frame)["input_count"], 0)
        self.events.write_text("")
        with self.assertRaises(ValueError):
            self.check(frame)


class ClaimedHomeHelperTests(unittest.TestCase):
    def test_campaign_parent_unwinds_on_the_supplied_runtime(self):
        from scripts.flow_delivery_campaign_bluestacks import _ensure_home_surface_before_prep
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            source = SimpleNamespace(frame="chapter")
            home = SimpleNamespace(frame="home")
            runtime = SimpleNamespace(session=session, capture=unittest.mock.Mock(side_effect=[source, home]),
                                      tap=unittest.mock.Mock())
            def recognize(frame, stage):
                screen = CampaignScreen.CHAPTER_MAP if frame == "chapter" else CampaignScreen.HOME_BASE
                targets = (("campaign-chapter-back", (10, 20, 40, 50)),) if frame == "chapter" else ()
                return SimpleNamespace(observation=SimpleNamespace(screen=screen, recognized=True,
                    overlay_state="none"), targets=targets, frame_sha256="a" * 64)
            with patch("tasks.campaign_auto_battle_vision.recognize_campaign_frame", side_effect=recognize), \
                    patch("time.sleep"), \
                    patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect",
                          side_effect=AssertionError("nested runtime forbidden")):
                _ensure_home_surface_before_prep(session, runtime=runtime, max_inputs=1)
            runtime.tap.assert_called_once()
            self.assertEqual(runtime.tap.call_args.kwargs["target_identity"], "campaign-chapter-back")
            self.assertEqual(runtime.tap.call_args.kwargs["target_roi"], (10, 20, 40, 50))

    def test_unknown_or_overlay_parent_cannot_dispatch(self):
        from scripts.flow_delivery_campaign_bluestacks import _ensure_home_surface_before_prep
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            runtime = SimpleNamespace(session=session, capture=unittest.mock.Mock(return_value=SimpleNamespace(frame=0)),
                                      tap=unittest.mock.Mock())
            for recognized, overlay in ((False, "none"), (True, "modal")):
                found = SimpleNamespace(observation=SimpleNamespace(screen=CampaignScreen.CHAPTER_MAP,
                    recognized=recognized, overlay_state=overlay), targets=(), frame_sha256="a" * 64)
                with patch("tasks.campaign_auto_battle_vision.recognize_campaign_frame", return_value=found):
                    with self.assertRaises(Exception):
                        _ensure_home_surface_before_prep(session, runtime=runtime)
            runtime.tap.assert_not_called()
