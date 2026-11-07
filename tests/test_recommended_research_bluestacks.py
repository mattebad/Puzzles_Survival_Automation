from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import cv2
import numpy as np

from automation_service.registry import (
    RECOMMENDED_RESEARCH_FLOW_ID,
    RECOMMENDED_RESEARCH_PRODUCT_ID,
    RECOMMENDED_RESEARCH_PRODUCT_REVISION,
    RECOMMENDED_RESEARCH_PROFILE_ID,
)
from scripts import recommended_research_bluestacks as route
from tasks.home_atlas import point_in_polygon
from tasks.home_atlas_vision import BlueStacksHomeLocalizer, bind_visible_building
from tasks.tech_upgrade_disabled import (
    ACTIVE_SCREEN,
    DETAIL_SCREEN,
    LIST_SCREEN,
    RESEARCH_RESOURCES,
    ResearchResourceRow,
    RecommendedResearchListObservation,
    TechUpgradeObservation,
    research_identity,
    tech_upgrade_authorizeable,
    tech_upgrade_postcondition_verified,
    tech_upgrade_queue_deferral,
    tech_upgrade_shortages,
)
from tests.support.local_captures import require_capture, requires_local_captures


ROOT = Path(__file__).resolve().parents[1]
TASK_FIXTURE = ROOT / "tests/fixtures/phase_e_disabled_tech_upgrade_observations.json"
RESEARCH_CAPTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "Puzzle_Survival_Runtime_POC"
    / ".local-captures"
    / "development-sessions"
    / "investigation2-cua-owner-20261106T232501213650Z"
)


def _ocr(lines: list[tuple[str, int, int]]) -> dict[str, list[object]]:
    columns: dict[str, list[object]] = {
        name: [] for name in (
            "text", "left", "top", "width", "height", "conf", "block_num", "par_num", "line_num"
        )
    }
    for line_number, (text, x, y) in enumerate(lines, 1):
        for word in text.split():
            width = max(8, 8 * len(word))
            columns["text"].append(word)
            columns["left"].append(x)
            columns["top"].append(y)
            columns["width"].append(width)
            columns["height"].append(20)
            columns["conf"].append(98)
            columns["block_num"].append(1)
            columns["par_num"].append(1)
            columns["line_num"].append(line_number)
            x += width + 7
    return columns


def _frame() -> np.ndarray:
    return np.zeros((1280, 800, 3), dtype=np.uint8)


def _listing_ocr() -> dict[str, list[object]]:
    return _ocr([
        ("Research Center", 290, 35),
        ("Recom'd", 300, 125),
        ("Troop Load II", 160, 195),
        ("Research", 545, 195),
        ("Research Speed II", 160, 305),
        ("Research", 545, 305),
    ])


def _top_detail_ocr() -> dict[str, list[object]]:
    return _ocr([
        ("Development", 265, 35),
        ("Troop Load II (8/10)", 120, 650),
        ("Original Time 09:34:35", 120, 790),
        ("Actual Time 05:56:53", 360, 790),
        ("Research Center: Lv.24", 160, 875),
        ("3,003,682/0", 160, 930),
        ("757,050/0", 160, 985),
        ("Research Now", 160, 1125),
        ("714", 270, 1095),
        ("Research", 440, 1170),
    ])


def _scrolled_detail_ocr() -> dict[str, list[object]]:
    return _ocr([
        ("Development", 265, 35),
        ("Troop Load II (8/10)", 120, 650),
        ("757,050/0", 160, 850),
        ("129,702/0", 160, 925),
        ("47,775/0", 160, 1000),
        ("Research Now", 160, 1125),
        ("714", 270, 1095),
        ("Research", 440, 1170),
    ])


def _task_listing() -> RecommendedResearchListObservation:
    value = json.loads(TASK_FIXTURE.read_text(encoding="utf-8"))["observations"]["list"]
    for key in ("target_roi", "panel_bounds", "evidence_refs"):
        value[key] = tuple(value[key])
    return RecommendedResearchListObservation(**value)


def _task_detail() -> TechUpgradeObservation:
    value = json.loads(TASK_FIXTURE.read_text(encoding="utf-8"))["observations"]["valid"]
    for key in ("target_roi", "panel_bounds", "prerequisite_evidence", "evidence_refs"):
        value[key] = tuple(value[key])
    value["resource_rows"] = tuple(ResearchResourceRow(**row) for row in value["resource_rows"])
    return TechUpgradeObservation(**value)


class RecommendedResearchNativeParserTests(unittest.TestCase):
    def test_first_recommendation_research_navigates_then_detail_research_starts(self) -> None:
        listing_screen = route.recognize_research_screen(
            _frame(), source_frame_sha256="a" * 64, evidence_refs=("synthetic:list",), ocr_data=_listing_ocr()
        )
        self.assertEqual(listing_screen.screen_state, LIST_SCREEN)
        self.assertEqual(listing_screen.first_recommendation_title, "Troop Load II")
        self.assertEqual(listing_screen.first_recommendation_identity, research_identity("Troop Load II"))
        self.assertEqual(listing_screen.recommendation_position, 1)
        listing_action = route._page_plan(
            listing_screen,
            state=LIST_SCREEN,
            target=f"recommended-research:{listing_screen.first_recommendation_identity}:list-research-button",
            control="RESEARCH_NAVIGATE",
            postcondition="RESEARCH_DETAIL",
            semantic_action="OPEN_FIRST_RECOMMENDED_RESEARCH",
        )
        self.assertIsNotNone(listing_action)
        self.assertEqual(listing_action.control_class, "RESEARCH_NAVIGATE")
        self.assertTrue(listing_action.target_identity.endswith(":list-research-button"))

        top_detail = route.recognize_research_screen(
            _frame(), source_frame_sha256="b" * 64, evidence_refs=("synthetic:detail-top",), ocr_data=_top_detail_ocr()
        )
        self.assertEqual(top_detail.screen_state, "RESEARCH_DETAIL")
        self.assertEqual(top_detail.selected_technology_identity, listing_screen.first_recommendation_identity)
        self.assertEqual(top_detail.resource_pairs, ((3_003_682, 0), (757_050, 0)))
        self.assertEqual(top_detail.duration_seconds, 5 * 3600 + 56 * 60 + 53)
        self.assertEqual(top_detail.research_now_diamonds, 714)
        self.assertNotEqual(top_detail.research_now_target_roi, top_detail.detail_research_target_roi)
        start_action = route._page_plan(
            top_detail,
            state="RESEARCH_DETAIL",
            target=f"recommended-research:{top_detail.selected_technology_identity}:detail-research-button",
            control="RESEARCH_START",
            postcondition="RESEARCH_ACTIVE_WITH_TIMER_AND_MATCHED_RESOURCE_DEBIT",
            semantic_action="START_EXACT_FIRST_RECOMMENDED_RESEARCH",
        )
        self.assertIsNotNone(start_action)
        self.assertEqual(start_action.control_class, "RESEARCH_START")
        self.assertTrue(start_action.target_identity.endswith(":detail-research-button"))
        self.assertNotEqual(listing_action.target_identity, start_action.target_identity)
        self.assertNotEqual(start_action.target_roi, top_detail.research_now_target_roi)

    def test_unexpected_purchase_or_shortage_overlay_cannot_bind_research_controls(self) -> None:
        for marker in ("Insufficient resources", "Not enough resources", "Purchase", "Refill", "Open Box"):
            ocr_data = _top_detail_ocr()
            extra = _ocr([(marker, 300, 600)])
            for column in ocr_data:
                ocr_data[column].extend(extra[column])
            screen = route.recognize_research_screen(
                _frame(),
                source_frame_sha256="e" * 64,
                evidence_refs=("synthetic:unexpected-overlay",),
                ocr_data=ocr_data,
            )
            self.assertEqual(screen.screen_state, "UNKNOWN")
            self.assertEqual(screen.overlay_state, "unknown")
            self.assertFalse(screen.recognized)
            self.assertIsNone(screen.list_research_target_roi)
            self.assertIsNone(screen.detail_research_target_roi)


    def test_home_queue_counter_may_be_split_from_its_research_label(self) -> None:
        idle = route.recognize_research_screen(
            _frame(),
            source_frame_sha256="e" * 64,
            evidence_refs=("synthetic:home-queue-idle",),
            home_recognized=True,
            ocr_data=_ocr([("Research", 20, 350), ("(0/1)", 25, 375)]),
        )
        self.assertEqual(idle.screen_state, "HOME_BASE")
        self.assertEqual((idle.queue1_state, idle.queue1_remaining_seconds), ("idle", None))
        busy = route.recognize_research_screen(
            _frame(),
            source_frame_sha256="f" * 64,
            evidence_refs=("synthetic:home-queue-busy",),
            home_recognized=True,
            ocr_data=_ocr([("Research", 20, 350), ("(1/1)", 25, 375), ("00:12:11", 20, 405)]),
        )
        self.assertEqual((busy.queue1_state, busy.queue1_remaining_seconds), ("busy", 731))

    def test_scrolled_rows_merge_only_with_exact_unique_wood_overlap(self) -> None:
        top = route.recognize_research_screen(
            _frame(), source_frame_sha256="a" * 64, evidence_refs=("synthetic:top",), ocr_data=_top_detail_ocr()
        )
        scrolled = route.recognize_research_screen(
            _frame(),
            source_frame_sha256="b" * 64,
            evidence_refs=("synthetic:scrolled",),
            ocr_data=_scrolled_detail_ocr(),
            expected_detail_identity=research_identity("Troop Load II"),
        )
        self.assertEqual(scrolled.screen_state, DETAIL_SCREEN)
        self.assertTrue(scrolled.requirements_scrolled)
        self.assertEqual(scrolled.resource_pairs, ((757_050, 0), (129_702, 0), (47_775, 0)))
        rows = route._merge_top_and_scrolled_resource_rows(top.resource_pairs, scrolled.resource_pairs)
        self.assertEqual(tuple(row.resource for row in rows), RESEARCH_RESOURCES)
        self.assertEqual(tuple(row.cost for row in rows), (0, 0, 0, 0))
        self.assertEqual(tuple(row.balance for row in rows), (3_003_682, 757_050, 129_702, 47_775))
        self.assertEqual(route._merge_top_and_scrolled_resource_rows(top.resource_pairs, ((9, 9), (8, 8), (7, 7))), ())
        self.assertEqual(route._merge_top_and_scrolled_resource_rows(top.resource_pairs, ((757_050, 0), (757_050, 0), (47_775, 0))), ())

    def test_parsed_exact_detail_and_active_timer_include_all_paired_resources(self) -> None:
        listing_screen = route.recognize_research_screen(
            _frame(), source_frame_sha256="a" * 64, evidence_refs=("synthetic:list",), ocr_data=_listing_ocr()
        )
        listing = route._list_observation(listing_screen, SimpleNamespace())
        detail_screen = route.recognize_research_screen(
            _frame(), source_frame_sha256="b" * 64, evidence_refs=("synthetic:top",), ocr_data=_top_detail_ocr()
        )
        scrolled_screen = route.recognize_research_screen(
            _frame(),
            source_frame_sha256="c" * 64,
            evidence_refs=("synthetic:scrolled",),
            ocr_data=_scrolled_detail_ocr(),
            expected_detail_identity=listing.first_recommendation_identity,
        )
        costs = route._merge_top_and_scrolled_resource_rows(detail_screen.resource_pairs, scrolled_screen.resource_pairs)
        context = SimpleNamespace(
            _recommended_research_center_level=24,
            _recommended_research_queue1_state="idle",
            _recommended_research_queue1_remaining=None,
        )
        detail = route._detail_observation(detail_screen, listing, context, costs=costs, scrolled_refs=scrolled_screen.evidence_refs)
        self.assertIsNotNone(detail)
        self.assertTrue(detail.prerequisites_known)
        self.assertTrue(detail.prerequisites_met)
        self.assertEqual(tuple(row.cost for row in detail.resource_rows), (0, 0, 0, 0))
        self.assertTrue(tech_upgrade_authorizeable(detail, listing))
        tokens = route._research_start_preconditions(detail, "game-day-2026-11-07")
        for row in detail.resource_rows:
            self.assertIn(f"{row.resource}_cost={row.cost}", tokens)
            self.assertIn(f"{row.resource}_balance={row.balance}", tokens)
        self.assertIn("first_displayed_recommendation_identity=troop-load-ii", tokens)
        self.assertIn("queue2_activate_tapped=false", tokens)
        self.assertIn("food_cost=0", tokens)
        self.assertIn("gas_balance=47775", tokens)
        self.assertIn("research_now_diamonds_excluded=true", tokens)
        active_screen = route.recognize_research_screen(
            _frame(),
            source_frame_sha256="d" * 64,
            evidence_refs=("synthetic:active",),
            ocr_data=_ocr([
                ("Researching Troop Load II", 130, 650),
                ("05:55:00", 200, 690),
                ("3,003,682/0", 160, 800),
                ("757,050/0", 160, 850),
                ("129,702/0", 160, 900),
                ("47,775/0", 160, 950),
            ]),
        )
        self.assertEqual(active_screen.screen_state, ACTIVE_SCREEN)
        active = route._build_active_observation(active_screen)
        self.assertIsNotNone(active)
        self.assertEqual(active.active_technology_identity, detail.first_recommendation_identity)
        self.assertEqual(active.remaining_seconds, 5 * 3600 + 55 * 60)
        self.assertTrue(tech_upgrade_postcondition_verified(detail, active, listing))
        self.assertIsNone(route._build_active_observation(replace(active_screen, active_resource_rows=())))

    def test_home_hud_research_label_cannot_become_building_radial_or_successor(self) -> None:
        from tasks.home_atlas import BuildingBinding

        binding = BuildingBinding(
            building_id=route.RESEARCH_CENTER_ID,
            target_roi=(550, 520, 640, 620),
            frame_sha256="a" * 64,
            confidence=0.99,
            semantic_evidence=("fresh-atlas-projection",),
            atlas_anchor=(0.0, 0.0),
            screen_anchor=(595.0, 565.0),
        )
        hud_only = route.recognize_research_radial(
            _frame(),
            source_frame_sha256="a" * 64,
            evidence_refs=("synthetic:home-hud",),
            building_binding=binding,
            home_recognized=True,
            ocr_data=_ocr([("Research", 24, 375)]),
        )
        self.assertIsNone(hud_only)
        radial = route.recognize_research_radial(
            _frame(),
            source_frame_sha256="b" * 64,
            evidence_refs=("synthetic:owner-radial",),
            building_binding=binding,
            home_recognized=True,
            ocr_data=_ocr([("Research", 640, 550), ("Research Center", 520, 570)]),
        )
        self.assertIsNotNone(radial)
        self.assertEqual(radial.owner_building_id, route.RESEARCH_CENTER_ID)
        list_screen = route.recognize_research_screen(
            _frame(), source_frame_sha256="c" * 64, evidence_refs=("synthetic:list",), ocr_data=_listing_ocr()
        )
        self.assertTrue(route.research_center_successor_verified(radial, list_screen))
        self.assertFalse(route.research_center_successor_verified(radial, hud_only))
        self.assertIsNone(route.recognize_research_radial(
            _frame(), source_frame_sha256="d" * 64, evidence_refs=(), building_binding=binding,
            home_recognized=False, ocr_data=_ocr([("Research", 640, 550)]),
        ))

    def test_busy_queue_and_exact_shortage_contract_do_not_require_or_infer_free_costs(self) -> None:
        listing, detail = _task_listing(), _task_detail()
        costs = (100, 20, 0, 0)
        balances = (20, 80, 10, 10)
        rows = tuple(
            ResearchResourceRow(resource, cost, balance)
            for resource, cost, balance in zip(RESEARCH_RESOURCES, costs, balances)
        )
        short_detail = replace(detail, resource_rows=rows)
        self.assertEqual(tech_upgrade_shortages(short_detail, listing), (("food", 80),))
        self.assertIsNone(tech_upgrade_shortages(replace(short_detail, resource_rows=rows[:-1]), listing))
        self.assertEqual(
            tech_upgrade_queue_deferral(replace(detail, queue1_state="busy", queue1_remaining_seconds=731)),
            ("busy", 731),
        )
        self.assertEqual(tuple(row.cost for row in rows), costs)

    def test_confirmed_reset_scoped_start_restarts_home_without_another_effect(self) -> None:
        now = datetime.now(timezone.utc).timestamp()
        reset_id = "game-day-" + datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        identity = SimpleNamespace(account_id="account", server_id="server", reset_id=reset_id)
        with tempfile.TemporaryDirectory() as root:
            frame_path = Path(root) / "frames" / "home.png"
            frame_path.parent.mkdir()
            frame_path.write_bytes(b"retained home evidence")
            captured = SimpleNamespace(frame=object(), path=frame_path, sha256="f" * 64)
            session = SimpleNamespace(
                initial_observation={"bound": True},
                observe=lambda callback, *, label: captured,
            )
            runtime = SimpleNamespace(session=root, capture=lambda: captured, action_keys=())
            context = SimpleNamespace(
                flow_id=RECOMMENDED_RESEARCH_FLOW_ID,
                product_id=RECOMMENDED_RESEARCH_PRODUCT_ID,
                product_revision=RECOMMENDED_RESEARCH_PRODUCT_REVISION,
                runtime_profile_id=RECOMMENDED_RESEARCH_PROFILE_ID,
                occurrence_key="occurrence-1",
                initial_frame=captured,
                session=session,
                runtime=runtime,
                action_store=SimpleNamespace(get_action_by_key=lambda _key: {"final_status": "confirmed"}),
                identity=identity,
                utc_clock=lambda: now,
                checkpoint=lambda: None,
                validate_identity=lambda: None,
                is_clean_home=lambda _frame: True,
                accounting=lambda: SimpleNamespace(
                    input_count=0, session_input_count=0, runtime_input_count=0, verified=True
                ),
            )
            result = route.run_native_route(context, {})
            self.assertEqual(result["status"], "already_complete")
            self.assertTrue(result["already_confirmed"])
            self.assertEqual(result["research_transport_calls"], 0)
            self.assertFalse(result["effect_reconciliation_required"])
            self.assertTrue(result["terminal_home_verified"])
            self.assertIsNotNone(result["terminal_home_frame"])

            context.action_store = SimpleNamespace(get_action_by_key=lambda _key: {"final_status": "input_sent"})
            with self.assertRaises(route.RecommendedResearchRouteFailure) as failure:
                route.run_native_route(context, {})
            self.assertEqual(failure.exception.partial_result["status"], "unresolved")
            self.assertTrue(failure.exception.partial_result["effect_reconciliation_required"])
            self.assertEqual(failure.exception.partial_result["research_transport_calls"], 0)

    def test_corrected_research_anchor_hits_reference_dome_not_left_ground(self) -> None:
        atlas = route.load_home_atlas(route.ATLAS_PATH)
        localizer = BlueStacksHomeLocalizer(atlas, route.ATLAS_PATH)
        viewport = next(view for view in atlas.viewports if view.viewport_id == "viewport-009")
        frame = cv2.imread(str(route.ATLAS_PATH.parent / viewport.image_path), cv2.IMREAD_COLOR)
        localization = localizer.localize(frame, home_recognized=True)
        building = atlas.lookup_building(route.RESEARCH_CENTER_ID)
        binding = bind_visible_building(
            frame, localization, building, home_is_clean=lambda _frame: True,
        )
        self.assertIsNotNone(binding)
        sx, sy = binding.screen_anchor
        # Golden image annotation, not production input coordinates: the dome
        # is here; the superseded anchor projected onto ground to its left.
        self.assertTrue(320 <= sx <= 430 and 330 <= sy <= 465)
        self.assertTrue(point_in_polygon(binding.atlas_anchor, building.polygon))

    @requires_local_captures
    def test_current_native_research_anchor_hits_the_observed_dome(self) -> None:
        path = (
            RESEARCH_CAPTURE_DIR.parent
            / "gh72-76-step-20261106T225637718601Z"
            / "runtime/investigation-20261106T225637884285Z/frames"
            / "0001-home.building.research_center-immediate-before.png"
        )
        require_capture(path)
        frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
        atlas = route.load_home_atlas(route.ATLAS_PATH)
        localizer = BlueStacksHomeLocalizer(atlas, route.ATLAS_PATH)
        building = atlas.lookup_building(route.RESEARCH_CENTER_ID)
        localization = localizer.localize(frame, home_recognized=True)
        binding = bind_visible_building(
            frame, localization, building, home_is_clean=lambda _frame: True,
        )
        self.assertIsNotNone(binding)
        sx, sy = binding.screen_anchor
        # Independent current native-frame annotation of the same facility.
        self.assertTrue(340 <= sx <= 430 and 530 <= sy <= 630)

    @requires_local_captures
    def test_desktop_research_view_does_not_bind_through_fixed_hud(self) -> None:
        path = RESEARCH_CAPTURE_DIR / "0063-research-center-visual-entry-before.png"
        require_capture(path)
        source_frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
        # This historical desktop capture includes BlueStacks chrome. Remove
        # it only for offline replay; production still requires native frames.
        frame = cv2.resize(source_frame[34:1212, 0:738], (800, 1280), interpolation=cv2.INTER_CUBIC)
        atlas = route.load_home_atlas(route.ATLAS_PATH)
        localizer = BlueStacksHomeLocalizer(atlas, route.ATLAS_PATH)
        localization = localizer.localize(frame, home_recognized=True)
        self.assertTrue(localization.recognized)
        binding = bind_visible_building(
            frame, localization, atlas.lookup_building(route.RESEARCH_CENTER_ID),
            home_is_clean=lambda _frame: True,
        )
        self.assertIsNone(binding)



if __name__ == "__main__":
    unittest.main()
