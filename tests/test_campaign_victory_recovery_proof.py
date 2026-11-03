"""Read-only prior-battle proof rejects altered or ambiguous recovery sources."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from automation_service.registry import CAMPAIGN_FLOW_ID
from tasks.campaign_auto_battle import CAMPAIGN_STAGE_COSTS, CampaignRouteObservation, CampaignScreen, CampaignStage
from tasks.campaign_auto_battle_vision import CampaignFrameRecognition
from tasks.campaign_victory_recovery import load_victory_recovery_proof
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID


NOW = datetime(2026, 10, 29, 6, tzinfo=timezone.utc)
STAGE = CampaignStage(1, 15, 9)


def _png(path: Path, marker: int) -> tuple[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = np.full((1280, 800, 3), marker, np.uint8)
    raw = cv2.imencode(".png", frame)[1].tobytes()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest(), hashlib.sha256(frame.tobytes()).hexdigest()


def _recognize(frame, stage):
    marker = int(frame[0, 0, 0])
    targets = ()
    if marker == 7:
        obs = CampaignRouteObservation(screen=CampaignScreen.STAGE_DIALOG, stage_dialog=stage, ap_current=120, ap_cost=CAMPAIGN_STAGE_COSTS[stage.identity], challenge_ready=True)
        targets = ((f"campaign-challenge-{stage.identity}", (100, 800, 300, 900)),)
    elif marker == 8:
        obs = CampaignRouteObservation(screen=CampaignScreen.HERO_LINEUP, lineup_challenge_ready=True)
        targets = (("campaign-lineup-challenge", (260, 1160, 540, 1250)),)
    elif marker == 9:
        obs = CampaignRouteObservation(screen=CampaignScreen.BATTLE)
    else:
        obs = CampaignRouteObservation(screen=CampaignScreen.UNKNOWN, recognized=False)
    return CampaignFrameRecognition(obs, hashlib.sha256(frame.tobytes()).hexdigest(), targets, {})


class CampaignVictoryRecoveryProofTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.session = self.root / f"{CAMPAIGN_FLOW_ID}-20261029T053617951795Z"
        self.leaf = self.session / "runtime" / "1-15-9-20261029T053638018462Z"
        source_sha, _ = _png(self.session / "source.png", 1)
        initial = {
            "device_state": "device", "foreground_package": "com.global.ztmslg",
            "native_width": 800, "native_height": 1280,
            "invocation_id": self.session.name, "frame_path": "source.png",
            "frame_sha256": source_sha,
        }
        # Fixed snapshot constructor validates the exact Campaign binding.
        snapshot = {
            "flow_id": CAMPAIGN_FLOW_ID, "product_id": "campaign_ap", "product_revision": "campaign_ap-v1",
            "production_handler": "campaign_ap_selection_handler", "profile": ACTIVE_RUNTIME_PROFILE_ID,
            "mode": "phase_canary", "registration_status": "REGISTERED", "scheduler_eligible": True,
        }
        self.delivery = {
            "flow_id": CAMPAIGN_FLOW_ID, "serial": "emulator-5554", "native_width": 800, "native_height": 1280,
            "destination": "1-15-9", "ap_cost": 14, "status": "effect_reconciliation_required",
            "effect_reconciliation_required": True, "registration_snapshot": snapshot,
            "initial_observation": initial, "initial_frame_sha256": source_sha,
        }
        self.outer = {
            "flow_id": CAMPAIGN_FLOW_ID, "status": "effect_reconciliation_required",
            "initial_observation": deepcopy(initial), "initial_frame_sha256": source_sha,
            "result": deepcopy(self.delivery),
        }
        self.rows = []
        progress = {"initial_ap": 120, "current_ap": 120, "ap_spent": 0, "ap_regenerated": 0, "completed_runs": 0, "loss_seen": False}
        for marker, screen, action, target, roi in (
            (7, CampaignScreen.STAGE_DIALOG, "CHALLENGE_STAGE", "campaign-challenge-1-15-9", [100, 800, 300, 900]),
            (8, CampaignScreen.HERO_LINEUP, "CONFIRM_LINEUP", "campaign-lineup-challenge", [260, 1160, 540, 1250]),
            (9, CampaignScreen.BATTLE, None, None, None),
        ):
            path = self.leaf / "frames" / f"{marker}.png"
            _, pixel_sha = _png(path, marker)
            self.rows.append({"type": "observation", "step": marker, "screen": screen.value, "recognized": True, "frame": str(path), "frame_sha256": pixel_sha})
            if action:
                self.rows.append({"type": "command", "step": marker, "action": action, "kind": "tap", "target_identity": target, "target_roi": roi, "progress": deepcopy(progress)})
        self._save()

    def _save(self):
        (self.session / "result.json").write_text(json.dumps(self.outer), encoding="utf-8")
        (self.session / "runtime" / "flow-delivery-result.json").write_text(json.dumps(self.delivery), encoding="utf-8")
        (self.leaf / "events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in self.rows), encoding="utf-8")

    def _load(self, **kwargs):
        return load_victory_recovery_proof(self.session, now=kwargs.get("now", NOW), sessions_root=self.root, recognizer=kwargs.get("recognizer", _recognize))

    def test_pending_battle_returns_hash_bound_read_only_proof(self):
        originals = {path: path.read_bytes() for path in self.session.rglob("*") if path.is_file()}
        proof = self._load()
        self.assertEqual((proof["baseline_ap"], proof["ap_cost"], proof["destination"]), (120, 14, "1-15-9"))
        self.assertEqual(proof["new_battle_count"], 0)
        self.assertEqual(proof["game_day_id"], "game-day-2026-10-29")
        self.assertEqual(set(proof["frame_refs"]), {"initial", "stage", "lineup", "battle"})
        for path, raw in originals.items():
            self.assertEqual(path.read_bytes(), raw)

    def test_tampered_png_or_pixel_hash_fails(self):
        stage_path = Path(self.rows[0]["frame"])
        _png(stage_path, 99)
        with self.assertRaises(ValueError):
            self._load()
        self.rows[0]["frame_sha256"] = hashlib.sha256(np.full((1280, 800, 3), 99, np.uint8).tobytes()).hexdigest()
        self._save()
        with self.assertRaises(ValueError):
            self._load()

    def test_bad_flow_profile_device_cost_package_or_baseline_fails(self):
        mutations = (
            lambda: self.outer.update(flow_id="NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE"),
            lambda: self.outer["result"]["registration_snapshot"].update(profile="wrong-profile"),
            lambda: self.delivery.update(serial="emulator-5556"),
            lambda: self.delivery.update(ap_cost=16),
            lambda: self.outer["initial_observation"].update(foreground_package="other.package"),
            lambda: self.rows[3]["progress"].update(initial_ap=-1),
            lambda: self.rows[3]["progress"].update(ap_spent=False),
            lambda: self.rows[3].update(target_identity="refill"),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                original = deepcopy((self.outer, self.delivery, self.rows))
                mutate()
                self._save()
                with self.assertRaises(ValueError):
                    self._load()
                self.outer, self.delivery, self.rows = original

    def test_reset_future_and_naive_time_fail(self):
        for current in (NOW - timedelta(days=1), NOW + timedelta(days=1), NOW.replace(hour=5, minute=30), NOW.replace(tzinfo=None)):
            with self.subTest(current=current), self.assertRaises(ValueError):
                self._load(now=current)

    def test_non_full_baseline_and_known_pre_battle_regeneration_are_preserved(self):
        for regenerated in (0, 1):
            for row in (self.rows[1], self.rows[3]):
                row["progress"].update(initial_ap=95, current_ap=95 + regenerated, ap_regenerated=regenerated)
            self._save()
            def current_ap(frame, stage):
                result = _recognize(frame, stage)
                if int(frame[0, 0, 0]) == 7:
                    result = replace(result, observation=replace(result.observation, ap_current=95 + regenerated))
                return result
            proof = self._load(recognizer=current_ap)
            self.assertEqual(proof["baseline_ap"], 95)
            self.assertEqual(proof["pre_battle_ap"], 95 + regenerated)
            self.assertEqual(proof["ap_regenerated_before_battle"], regenerated)
            self.assertEqual(proof["new_battle_count"], 0)

    def test_pending_progress_requires_typed_nonnegative_conserved_balance(self):
        original = deepcopy(self.rows)
        for changes in (
            {"initial_ap": -1}, {"initial_ap": 13, "current_ap": 13},
            {"initial_ap": "95"}, {"initial_ap": 95, "current_ap": 96, "ap_regenerated": 0},
            {"ap_regenerated": -1}, {"ap_spent": 14}, {"completed_runs": 1},
        ):
            self.rows = deepcopy(original)
            for row in (self.rows[1], self.rows[3]):
                row["progress"].update(changes)
            self._save()
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self._load()

    def test_existing_three_destinations_use_shared_cost_contract(self):
        for destination, cost in CAMPAIGN_STAGE_COSTS.items():
            previous_leaf = self.leaf
            self.leaf = self.leaf.with_name(f"{destination}-20261029T053638018462Z")
            if previous_leaf != self.leaf:
                previous_leaf.rename(self.leaf)
            for row in self.rows:
                if row["type"] == "observation":
                    row["frame"] = str(self.leaf / "frames" / Path(row["frame"]).name)
            for result in (self.delivery, self.outer["result"]):
                result.update(destination=destination, ap_cost=cost)
            self.rows[1]["target_identity"] = f"campaign-challenge-{destination}"
            self._save()
            proof = self._load()
            self.assertEqual((proof["destination"], proof["ap_cost"]), (destination, cost))
        for result in (self.delivery, self.outer["result"]):
            result.update(destination="1-2-9")
        self._save()
        with self.assertRaises(ValueError):
            self._load()

    def test_two_confirms_or_continue_fail(self):
        for extra in (deepcopy(self.rows[3]), {"type": "command", "action": "CONTINUE_VICTORY"}):
            self.rows.append(extra)
            self._save()
            with self.assertRaises(ValueError):
                self._load()
            self.rows.pop()

    def test_battle_must_be_positive_in_retained_record_and_current_replay(self):
        self.rows[-1]["recognized"] = False
        self._save()
        with self.assertRaises(ValueError):
            self._load()
        self.rows[-1]["recognized"] = True
        self._save()
        def bad_battle(frame, stage):
            return _recognize(frame if int(frame[0, 0, 0]) != 9 else np.zeros_like(frame), stage)
        with self.assertRaises(ValueError):
            self._load(recognizer=bad_battle)

    def test_replayed_cost_baseline_stage_and_lineup_are_required(self):
        for marker, changes in (
            (7, {"ap_cost": 16}), (7, {"ap_current": 119}),
            (7, {"stage_dialog": CampaignStage(1, 20, 9)}),
            (8, {"lineup_challenge_ready": False}),
        ):
            def altered(frame, stage):
                result = _recognize(frame, stage)
                if int(frame[0, 0, 0]) == marker:
                    result = replace(result, observation=replace(result.observation, **changes))
                return result
            with self.subTest(marker=marker, changes=changes), self.assertRaises(ValueError):
                self._load(recognizer=altered)

    def test_traversal_and_ambiguous_route_leaf_fail(self):
        self.rows[0]["frame"] = "../../outside.png"
        self._save()
        with self.assertRaises(ValueError):
            self._load()
        (self.session / "runtime" / "1-15-9-20261029T054000000000Z").mkdir()
        with self.assertRaises(ValueError):
            self._load()


if __name__ == "__main__":
    unittest.main()
