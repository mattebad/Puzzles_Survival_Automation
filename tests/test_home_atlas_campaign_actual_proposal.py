"""Actual native Campaign P/I pixels rebind through test-only clocks and transport."""

from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Iterator
import unittest

import cv2

from safe_action_core import ActionStatus, SafetyStore
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts import home_atlas_bluestacks as home
from tasks.campaign_auto_battle import CampaignScreen, CampaignStage
from tasks.campaign_auto_battle_vision import recognize_campaign_frame
from tasks.home_atlas_vision import bind_visible_building, frame_digest
from tasks.perception_bundle import PerceptionBundleError
from tests.support.home_atlas import _RecordingPolicy
from tests.support.environment import requires_tesseract


ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "tasks/assets/home_atlas/bluestacks/800x1280/atlas.json"
HOME_FRAME = ROOT / "tests/fixtures/campaign_home_entry/canonical-home-20261029.png"
CAMPAIGN_FRAME = ROOT / "tests/fixtures/campaign_tier_controls/current-tier-map.png"
PAIR_PROPOSAL = HOME_FRAME.parent / "campaign-home-rebind-proposal-20261029.png"
PAIR_IMMEDIATE = HOME_FRAME.parent / "campaign-home-rebind-immediate-20261029.png"


class _CampaignNativeRuntime:
    execute = True
    in_flight_action = None
    atlas_path = ATLAS

    def __init__(self, directory: Path, *, native_pair: bool) -> None:
        self.session = directory
        self.native_pair = native_pair
        self.ordinal = 0
        self.now = 100.0
        self.captures: list[tuple[str, CapturedNativeFrame]] = []
        self.taps: list[tuple[CapturedNativeFrame, dict[str, object]]] = []

    def capture(self, label: str) -> CapturedNativeFrame:
        self.ordinal += 1
        self.now += 0.25
        fixture = CAMPAIGN_FRAME if "post" in label or label.endswith("settled") else HOME_FRAME
        if self.native_pair and fixture == HOME_FRAME:
            fixture = PAIR_IMMEDIATE if label == "campaign-home-building-pre-dispatch" else PAIR_PROPOSAL
        png = fixture.read_bytes()
        frame = cv2.imread(str(fixture))
        path = self.session / f"{self.ordinal:04d}-{label}.png"
        path.write_bytes(png)
        captured = CapturedNativeFrame(frame, png, hashlib.sha256(png).hexdigest(), self.now, path)
        self.captures.append((label, captured))
        return captured

    def tap(self, captured: CapturedNativeFrame, **target: object) -> None:
        self.taps.append((captured, target))

    def clock(self) -> float:
        return self.now + 0.01


class _CampaignCase:
    def __init__(self, directory: Path, binding, *, native_pair: bool) -> None:
        self.runtime = _CampaignNativeRuntime(directory, native_pair=native_pair)
        self.planning = self.runtime.capture("campaign-home-planning")
        self.identity = home.identity_from_captured(
            self.planning, session_id=str(directory), ordinal=self.runtime.ordinal, label="campaign-home-planning",
        )
        self.binding = binding
        self.policy = _RecordingPolicy()
        self.store = SafetyStore(directory / "campaign-safety.sqlite3")
        self.store.acquire_lease("owner", 1000.0, 100.0)
        self.successors = []

    def campaign_successor(self, frame):
        recognition = recognize_campaign_frame(frame, CampaignStage(1, 20, 9))
        self.successors.append(recognition)
        return recognition.observation.screen is CampaignScreen.TIER_MAP

    def dispatch(self):
        return home.dispatch_verified_campaign_home_building_tap(
            runtime=self.runtime, immediate_before=self.planning, identity=self.identity, binding=self.binding,
            action_id="native-campaign-entry", action_key="native-campaign-entry-key",
            task_id=home.SUPPLY_DEPOT_ROUTE_TASK_ID, navigation_session_id="native-campaign-entry-session",
            lease_owner="owner", policy=self.policy, store=self.store,
            monotonic_clock=self.runtime.clock, wall_clock=lambda: 1000.0,
            semantic_opened_check=self.campaign_successor,
        )


class CampaignNativeActualProposalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.original_png = HOME_FRAME.read_bytes()
        cls.frame = cv2.imread(str(HOME_FRAME))
        cls.atlas = home.load_home_atlas(ATLAS)
        cls.localizer = home.BlueStacksHomeLocalizer(cls.atlas, ATLAS)
        cls.building = cls.atlas.lookup_building(home.CAMPAIGN_HOME_ATLAS_BUILDING_ID)
        cls.localization = cls.localizer.localize(cls.frame)
        cls.binding = bind_visible_building(
            cls.frame, cls.localization, cls.building, home_is_clean=lambda _frame: True,
        )
        cls.pair_pngs = {path: path.read_bytes() for path in (PAIR_PROPOSAL, PAIR_IMMEDIATE)}
        pair_frame = cv2.imread(str(PAIR_PROPOSAL))
        pair_localization = cls.localizer.localize(pair_frame)
        cls.pair_binding = bind_visible_building(
            pair_frame, pair_localization, cls.building, home_is_clean=lambda _frame: True,
        )

    @contextmanager
    def case(self, *, native_pair=False) -> Iterator[_CampaignCase]:
        with tempfile.TemporaryDirectory() as directory:
            binding = self.pair_binding if native_pair else self.binding
            self.assertIsNotNone(binding)
            self.assertEqual(binding.target_roi, (402, 183, 560, 342) if native_pair else (411, 356, 560, 506))
            case = _CampaignCase(Path(directory), binding, native_pair=native_pair)
            try:
                yield case
            finally:
                case.store.close()
                self.assertEqual(HOME_FRAME.read_bytes(), self.original_png)
                for path, png in self.pair_pngs.items():
                    self.assertEqual(path.read_bytes(), png)

    @requires_tesseract
    def test_native_independent_unchanged_capture_dispatches_once_and_confirms_real_campaign(self) -> None:
        with self.case() as case:
            issued, execution, immediate, telemetry = case.dispatch()
            self.assertTrue(issued.authorized)
            self.assertEqual(execution.status, ActionStatus.CONFIRMED)
            self.assertEqual(execution.transport_calls, 1)
            self.assertEqual(len(case.runtime.taps), 1)
            fresh = case.runtime.captures[1][1]
            self.assertIsNot(fresh, case.planning)
            self.assertIs(case.runtime.taps[0][0], fresh)
            self.assertEqual(immediate.target_roi, case.binding.target_roi)
            self.assertEqual(immediate.capture_completed_monotonic, fresh.captured_monotonic)
            self.assertTrue(any(request.policy_phase == "pre_dispatch" and request.observation is immediate
                                for request in case.policy.requests))
            action = case.store.get_action("native-campaign-entry")
            self.assertEqual(action["source_frame_sha256"], case.identity.semantic_sha256)
            self.assertEqual(action["source_frame_captured_at"], case.planning.captured_monotonic)
            self.assertLess(action["source_frame_captured_at"], immediate.capture_completed_monotonic)
            self.assertEqual(len(case.successors), 1)
            self.assertEqual(case.successors[0].observation.screen, CampaignScreen.TIER_MAP)
            settled = case.runtime.captures[-1][1]
            self.assertEqual(json.loads(action["reconciliation_result_json"])["frame_sha256"], frame_digest(settled.frame))
            self.assertEqual(telemetry["settled_identity"].capture_completed_monotonic, settled.captured_monotonic)
            self.assertTrue(telemetry["completed"])

    @requires_tesseract
    def test_actual_native_pair_dispatches_only_fresh_bound_target(self) -> None:
        with self.case(native_pair=True) as case:
            issued, execution, immediate, telemetry = case.dispatch()
            self.assertTrue(issued.authorized)
            # Production dispatch independently ran the real localizer and binder
            # on I; no Observation geometry or timestamp is edited by this test.
            self.assertEqual(immediate.target_roi, (402, 184, 560, 343))
            self.assertEqual(immediate.target_roi,
                             tuple(value + (1 if index in (1, 3) else 0)
                                   for index, value in enumerate(case.binding.target_roi)))
            self.assertEqual(execution.status, ActionStatus.CONFIRMED)
            self.assertEqual(execution.transport_calls, 1)
            self.assertEqual(len(case.runtime.taps), 1)
            fresh = case.runtime.captures[1][1]
            self.assertIs(case.runtime.taps[0][0], fresh)
            self.assertEqual(case.runtime.taps[0][1]["target_roi"], immediate.target_roi)
            self.assertEqual(len(case.successors), 1)
            self.assertEqual(len(case.runtime.captures), 4)
            self.assertEqual(case.planning.png, PAIR_PROPOSAL.read_bytes())
            self.assertEqual(fresh.png, PAIR_IMMEDIATE.read_bytes())
            provenance = json.loads((HOME_FRAME.parent / "campaign-home-rebind-20261029.provenance.json").read_text())
            for record, capture in zip(provenance["frames"], (case.planning, fresh)):
                self.assertEqual(record["transport_sha256"], capture.sha256)
            self.assertNotEqual(immediate.frame_sha256, case.identity.semantic_sha256)
            self.assertTrue(telemetry["dispatched"])
            self.assertEqual(telemetry["executor_status"], "confirmed")
            self.assertEqual(telemetry["executor_reason"], execution.reason)
            self.assertEqual(telemetry["transport_calls"], 1)
            action = case.store.get_action("native-campaign-entry")
            self.assertEqual(action["source_frame_captured_at"], case.planning.captured_monotonic)
            self.assertEqual(action["source_frame_sha256"], case.identity.semantic_sha256)

    def test_wrong_planning_owner_or_stale_binding_stops_before_new_capture_or_input(self) -> None:
        from unittest.mock import patch
        for invalid in ({"building_id": "home.building.research_lab"}, {"frame_sha256": "0" * 64}):
            with self.subTest(invalid=invalid), self.case() as case:
                case.binding = replace(case.binding, **invalid)
                with patch.object(home, "is_clean_home_frame", return_value=True), self.assertRaises(
                    PerceptionBundleError
                ):
                    case.dispatch()
                self.assertEqual(len(case.runtime.captures), 1)
                self.assertFalse(case.runtime.taps)
                self.assertFalse(case.policy.requests)


if __name__ == "__main__":
    unittest.main()
