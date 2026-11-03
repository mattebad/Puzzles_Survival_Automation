from __future__ import annotations

import json
import hashlib
from contextlib import closing
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from safe_action_core import SafetyStore
from scripts.bluestacks_native_runtime import (
    CapturedNativeFrame,
    NATIVE_RUNTIME_PROFILE_ID,
)
from scripts.startup_recovery import (
    ContextualPopupRecoveryResult,
    StartupRecoveryError,
    StartupRecoveryResult,
    classify_startup_frame,
    recover_contextual_vip_popup,
    recover_known_startup_overlay,
)
from scripts.startup_surface_recognition import (
    SCARLETT_EXPECTED_SUCCESSOR,
    SCARLETT_FORBIDDEN_PURCHASE_ROIS,
    SCARLETT_FRAME_SHA256,
    SCARLETT_MAX_INPUTS,
    SCARLETT_SAFE_BACK_ROI,
    SCARLETT_SAFE_BACK_TARGET_IDENTITY,
    SCARLETT_THREE_DAY_PACK,
    commercial_surface_signal,
    is_exact_scarlett_recognition,
    recognize_scarlett_three_day_pack,
)
from tests.ocr_memo import install_module_memo


def setUpModule():
    # Identical frames are replayed across tests; run real Tesseract once per unique input.
    install_module_memo()


TARGET = (263, 781, 537, 869)


def popup(
    *,
    target=TARGET,
    popup_identity: str = "VIP_POINTS_GET_PTS",
    target_identity: str = "reset-popup-close",
) -> dict[str, object]:
    return {
        "recognized": True,
        "popup_identity": popup_identity,
        "target_identity": target_identity,
        "target": target,
        "target_center": (400, 825),
    }


class FakeRuntime:
    def __init__(self, root: Path, *, max_inputs: int = 12) -> None:
        self.session = root
        self.session.mkdir()
        self.max_inputs = max_inputs
        self.input_count = 0
        self.ordinal = 0
        self.keys: set[str] = set()
        self.reconciliations: list[str] = []

    def capture(self, label: str) -> CapturedNativeFrame:
        # Windows monotonic clock resolution can otherwise give successive
        # synthetic captures identical timestamps, unlike device captures.
        time.sleep(0.02)
        self.ordinal += 1
        frame = np.full((1280, 800, 3), self.ordinal, np.uint8)
        payload = f"{label}:{self.ordinal}".encode()
        path = self.session / f"{self.ordinal:04d}-{label}.png"
        path.write_bytes(payload)
        return CapturedNativeFrame(
            frame,
            payload,
            hashlib.sha256(payload).hexdigest(),
            time.monotonic(),
            path,
        )

    def tap(self, source, *, target_identity, target_roi, action_key, **_kwargs) -> None:
        if action_key in self.keys:
            raise RuntimeError("duplicate action key")
        if self.input_count >= self.max_inputs:
            raise RuntimeError("input limit reached")
        self.keys.add(action_key)
        self.input_count += 1

    def reconcile(self, _action_key, status, _post, _reason) -> None:
        self.reconciliations.append(status)


class ContextualRuntime(FakeRuntime):
    def __init__(
        self,
        root: Path,
        *,
        max_inputs: int = 12,
        capture_failures: set[str] | None = None,
        deny_input: bool = False,
        uncertain_transport: bool = False,
    ) -> None:
        super().__init__(root, max_inputs=max_inputs)
        self.capture_failures = capture_failures or set()
        self.deny_input = deny_input
        self.uncertain_transport = uncertain_transport
        self.tap_calls: list[dict[str, object]] = []
        self.capture_labels: list[str] = []

    def capture(self, label: str) -> CapturedNativeFrame:
        self.capture_labels.append(label)
        if label in self.capture_failures:
            raise RuntimeError(f"capture failed: {label}")
        return super().capture(label)
    def tap(self, source, **kwargs) -> None:
        self.tap_calls.append(dict(kwargs))
        if self.deny_input:
            raise RuntimeError("input denied")
        super().tap(source, **kwargs)
        if self.uncertain_transport:
            raise RuntimeError("transport completion uncertain")
class StartupRecoveryTests(unittest.TestCase):
    def _recover(self, runtime: FakeRuntime, **kwargs):
        return recover_known_startup_overlay(
            runtime,
            recovery_scope="test-reset",
            action_store_factory=lambda: SafetyStore(
                runtime.session / "test-startup-actions.sqlite3"
            ),
            **kwargs,
        )

    def test_observation_only_seam_assigns_explicit_recovery_ownership(self) -> None:
        fixture = (
            Path(__file__).resolve().parents[1]
            / "tasks"
            / "assets"
            / "navigation"
            / "800x1280"
            / "reset_popup_source.png"
        ).read_bytes()
        recruitment = classify_startup_frame(
            "RECRUITMENT-FREE-ATTEMPT-MAINTENANCE",
            fixture,
        )
        world = classify_startup_frame("WORLD-MAP-NAVIGATION-FOUNDATION", fixture)
        daily_row = classify_startup_frame(
            "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
            fixture,
        )
        unsupported = classify_startup_frame("NEW-FLOW-WITHOUT-RECOVERY", fixture)

        self.assertEqual(recruitment.status, "recovery_required")
        self.assertEqual(recruitment.recovery_owner, "shared_home_startup_recovery")
        self.assertFalse(recruitment.input_authority)
        for plan in (world, daily_row, unsupported):
            self.assertEqual(plan.status, "recovery_required")
            self.assertEqual(plan.recovery_owner, "shared_home_startup_recovery")
            self.assertFalse(plan.input_authority)

    def test_home_routes_recover_exact_vip_popup_before_route_execution(self) -> None:
        fixture = (
            Path(__file__).resolve().parents[1]
            / "tasks/assets/navigation/800x1280/reset_popup_source.png"
        ).read_bytes()
        for flow_id in (
            "SUPPLY-DEPOT-BLUESTACKS-INTEGRATION",
            "BIOENHANCER-FREE-RESEARCH-BLUESTACKS-INTEGRATION",
            "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION",
            "NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE",
        ):
            with self.subTest(flow_id=flow_id):
                plan = classify_startup_frame(flow_id, fixture)
                self.assertEqual(plan.status, "recovery_required")
                self.assertEqual(plan.recovery_owner, "shared_home_startup_recovery")
                self.assertFalse(plan.input_authority)

    def test_all_flows_share_scarlett_and_vip_recovery(self) -> None:
        flow_id = "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION"
        _frame, payload = self._current_scarlett_fixture()
        for supported_flow in (
            flow_id,
            "WORLD-MAP-NAVIGATION-FOUNDATION",
            "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION",
            "CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION",
            "SUPPLY-DEPOT-BLUESTACKS-INTEGRATION",
            "NEW-FLOW-WITHOUT-RECOVERY",
        ):
            with self.subTest(flow_id=supported_flow):
                scarlett = classify_startup_frame(supported_flow, payload)
                self.assertEqual(scarlett.status, "recovery_required")
                self.assertEqual(scarlett.recovery_owner, "shared_startup_surface_recovery")
                self.assertFalse(scarlett.input_authority)
        vip_payload = (
            Path(__file__).resolve().parents[1]
            / "tasks/assets/navigation/800x1280/reset_popup_source.png"
        ).read_bytes()
        vip = classify_startup_frame(flow_id, vip_payload)
        self.assertEqual(vip.status, "recovery_required")
        self.assertEqual(vip.recovery_owner, "shared_home_startup_recovery")
        self.assertFalse(vip.input_authority)

    def test_operator_recovery_retains_successor_for_route_validation(self) -> None:
        from scripts import pnsctl

        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime(Path(directory) / "runtime")
            runtime.max_inputs = 12

            def recover(_runtime, *, recognize_successor, **_kwargs):
                lineup = cv2.imread(str(Path(__file__).resolve().parent / "fixtures" /
                                        "ultimate_lineup" / "hero-lineup-20261029-a.png"))
                self.assertIsNotNone(lineup)
                self.assertTrue(recognize_successor(lineup))
                self.assertFalse(recognize_successor(np.zeros((1280, 800, 3), dtype=np.uint8)))
                return StartupRecoveryResult(
                    "recovered", 1, "VIP_POINTS_GET_PTS", "RETAINED_STARTUP_SUCCESSOR",
                    "a" * 64, "b" * 64, "startup-vip-close", "test successor",
                )
            from types import SimpleNamespace
            with (
                patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", return_value=runtime),
                patch("scripts.startup_recovery.recover_known_startup_overlay", side_effect=recover),
                patch("scripts.startup_recovery.classify_startup_frame", return_value=SimpleNamespace(status="clear")),
            ):
                result = pnsctl._run_shared_startup_recovery(
                    flow_id="ANY-FLOW", task_id="test", session_directory=Path(directory),
                    max_inputs=10, recovery_scope="test",
                )
            self.assertEqual(result["recovery_input_count"], 1)
            self.assertEqual(result["successor_state"], "RETAINED_STARTUP_SUCCESSOR")
            self.assertEqual(runtime.max_inputs, 2)

    @staticmethod
    def _scarlett_fixture() -> tuple[np.ndarray, bytes]:
        path = (
            Path(__file__).resolve().parents[1]
            / "tasks"
            / "assets"
            / "navigation"
            / "800x1280"
            / "scarlett-three-day-pack-positive.png"
        )
        payload = path.read_bytes()
        frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        assert frame is not None
        return frame, payload

    @staticmethod
    def _scarlett_animation_fixture() -> tuple[np.ndarray, bytes]:
        path = (Path(__file__).resolve().parents[1] / "tasks" / "assets" / "navigation" / "800x1280" / "scarlett-three-day-pack-animation-positive.png")
        payload = path.read_bytes()
        frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        assert frame is not None
        return frame, payload

    @staticmethod
    def _scarlett_detail() -> dict[str, object]:
        return {
            "recognized": True,
            "surface_identity": SCARLETT_THREE_DAY_PACK,
            "surface_kind": "full_page",
            "runtime_profile_id": NATIVE_RUNTIME_PROFILE_ID,
            "width": 800,
            "height": 1280,
            "frame_sha256": SCARLETT_FRAME_SHA256,
            "title_text": "scarlett 3-day pack",
            "title_identity": True,
            "semantic_evidence": (
                "title:Scarlett 3-Day Pack",
                "full_page_real_money_promotion",
                "visible_in_game_back_upper_left",
                "purchase_regions_excluded",
                "current_offer_benefits_and_three_day_rows",
                "current_first_topup_notice",
            ),
            "safe_exit_target_identity": SCARLETT_SAFE_BACK_TARGET_IDENTITY,
            "safe_exit_roi": SCARLETT_SAFE_BACK_ROI,
            "forbidden_purchase_rois": SCARLETT_FORBIDDEN_PURCHASE_ROIS,
            "purchase_exclusion_verified": True,
            "critical_roi_hashes": (("title", "a" * 64),),
            "page_context_verified": True,
            "measured_back_roi": (47, 0, 128, 59),
            "expected_successor": SCARLETT_EXPECTED_SUCCESSOR,
            "max_inputs": SCARLETT_MAX_INPUTS,
            "target_count": 1,
        }

    def test_exact_scarlett_fixture_binds_hash_geometry_and_back_roi(self) -> None:
        frame, payload = self._scarlett_fixture()
        with patch(
            "scripts.startup_surface_recognition._title_text",
            return_value="Scarlett 3-Day Pack",
        ):
            result = recognize_scarlett_three_day_pack(frame, payload)

        self.assertTrue(result["recognized"])
        self.assertEqual(result["surface_identity"], SCARLETT_THREE_DAY_PACK)
        self.assertEqual(result["frame_sha256"], SCARLETT_FRAME_SHA256)
        self.assertEqual(result["safe_exit_roi"], SCARLETT_SAFE_BACK_ROI)
        self.assertEqual(result["forbidden_purchase_rois"], SCARLETT_FORBIDDEN_PURCHASE_ROIS)
        self.assertEqual(result["target_count"], 1)
        x0, y0, x1, y1 = SCARLETT_SAFE_BACK_ROI
        back = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
        visible_control_pixels = (back[:, :, 2] > 150) & (back[:, :, 1] < 130)
        self.assertGreater(int(visible_control_pixels.sum()), 700, "safe Back ROI must contain the visible Back control, not nearby body pixels")

    def test_scarlett_rejects_cross_frame_bytes_and_ambiguous_target(self) -> None:
        frame, payload = self._scarlett_fixture()
        with patch(
            "scripts.startup_surface_recognition._title_text",
            return_value="Scarlett 3-Day Pack",
        ):
            cross_frame_bytes = recognize_scarlett_three_day_pack(
                frame, b"not-the-retained-native-frame"
            )
            ambiguous_target = recognize_scarlett_three_day_pack(
                frame,
                payload,
                target_candidates=[
                    {
                        "target_identity": "purchase-button",
                        "roi": (78, 111, 200, 180),
                    }
                ],
            )

        self.assertFalse(cross_frame_bytes["recognized"])
        self.assertEqual(
            cross_frame_bytes["reason"],
            "frame_bytes_do_not_match_current_pixels",
        )
        self.assertFalse(ambiguous_target["recognized"])
        self.assertEqual(
            ambiguous_target["reason"],
            "safe_back_target_is_ambiguous_or_wrong_geometry",
        )
    def test_scarlett_contract_negatives_fail_closed(self) -> None:
        detail = self._scarlett_detail()
        variants = {
            "title_only": {"semantic_evidence": ("title:Scarlett 3-Day Pack",)},
            "price_only": {"title_text": "$4.99", "title_identity": False},
            "similar_shop": {"surface_identity": "SHOP_PAGE"},
            "wrong_back_geometry": {"safe_exit_roi": (40, 0, 169, 61)},
            "missing_purchase_exclusion": {
                "forbidden_purchase_rois": (),
                "purchase_exclusion_verified": False,
            },
            "missing_current_page_context": {"page_context_verified": False},
            "unmeasured_back": {"measured_back_roi": None},
            "arrow_outside_safe_region": {"measured_back_roi": (100, 10, 185, 60)},
            "ambiguous_targets": {"target_count": 2},
        }
        for name, changes in variants.items():
            candidate = dict(detail)
            candidate.update(changes)
            with self.subTest(name=name):
                self.assertFalse(is_exact_scarlett_recognition(candidate))

        frame, payload = self._scarlett_fixture()
        with patch(
            "scripts.startup_surface_recognition._title_text",
            return_value="Scarlett 3-Day Pack",
        ):
            scaled = cv2.resize(frame, (400, 640), interpolation=cv2.INTER_AREA)
            cropped = frame[10:-10, :, :]
            self.assertFalse(recognize_scarlett_three_day_pack(scaled, payload)["recognized"])
            self.assertFalse(recognize_scarlett_three_day_pack(cropped, payload)["recognized"])

    def test_scarlett_recognition_tolerates_animation_outside_stable_rois(self) -> None:
        frame, payload = self._scarlett_fixture()
        animated, animated_payload = self._scarlett_animation_fixture()
        self.assertNotEqual(hashlib.sha256(payload).hexdigest(), hashlib.sha256(animated_payload).hexdigest())
        self.assertFalse(np.array_equal(frame, animated))
        with patch("scripts.startup_surface_recognition._title_text", return_value="Scarlett 3-Day Pack"):
            fixture_result = recognize_scarlett_three_day_pack(frame, payload)
            animated_result = recognize_scarlett_three_day_pack(animated, animated_payload)
        self.assertTrue(fixture_result["recognized"])
        self.assertTrue(animated_result["recognized"])
        self.assertEqual(animated_result["frame_sha256"], hashlib.sha256(animated_payload).hexdigest())

    def test_scarlett_portrait_artwork_is_not_source_authority(self) -> None:
        frame, _payload = self._scarlett_fixture()
        drifted = frame.copy(); drifted[180:220, 300:340] = 0
        ok, encoded = cv2.imencode(".png", drifted); self.assertTrue(ok)
        with patch("scripts.startup_surface_recognition._title_text", return_value="Scarlett 3-Day Pack"):
            result = recognize_scarlett_three_day_pack(drifted, encoded.tobytes())
        self.assertTrue(result["recognized"])
        self.assertTrue(is_exact_scarlett_recognition(result))

    @staticmethod
    def _current_scarlett_fixture() -> tuple[np.ndarray, bytes]:
        path = Path(__file__).parent / "fixtures/startup/scarlett-current-20261029.png"
        payload = path.read_bytes()
        return cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR), payload

    def test_current_and_old_native_scarlett_pages_share_semantic_back_binding(self) -> None:
        old, old_payload = self._scarlett_fixture()
        current, current_payload = self._current_scarlett_fixture()
        self.assertNotEqual(hashlib.sha256(old_payload).hexdigest(), hashlib.sha256(current_payload).hexdigest())
        for frame, payload in ((old, old_payload), (current, current_payload)):
            with self.subTest(digest=hashlib.sha256(payload).hexdigest()):
                result = recognize_scarlett_three_day_pack(frame, payload)
                self.assertTrue(result["recognized"], result)
                self.assertTrue(is_exact_scarlett_recognition(result))
                self.assertEqual(result["safe_exit_roi"], SCARLETT_SAFE_BACK_ROI)
                self.assertEqual(result["measured_back_roi"], (47, 0, 128, 59))

    def test_current_scarlett_accepts_brightness_and_artwork_variance(self) -> None:
        frame, payload = self._current_scarlett_fixture()
        changed = cv2.convertScaleAbs(frame, alpha=0.9, beta=8)
        changed[120:240, 350:690] = (37, 88, 122)
        ok, encoded = cv2.imencode(".png", changed)
        self.assertTrue(ok)
        original = recognize_scarlett_three_day_pack(frame, payload)
        result = recognize_scarlett_three_day_pack(changed, encoded.tobytes())
        self.assertTrue(original["recognized"])
        self.assertTrue(result["recognized"], result)
        self.assertNotEqual(original["critical_roi_hashes"], result["critical_roi_hashes"])
        self.assertTrue(is_exact_scarlett_recognition(result))

    def test_scarlett_rejects_native_dialog_and_missing_or_unsafe_back(self) -> None:
        frame, _payload = self._current_scarlett_fixture()
        popup_frame = cv2.imread(str(Path(__file__).resolve().parents[1]
                                     / "tasks/assets/navigation/800x1280/reset_popup_source.png"))
        overlaid = frame.copy()
        overlaid[350:920, 50:750] = popup_frame[350:920, 50:750]
        destroyed = frame.copy()
        destroyed[0:90, 0:180] = 0
        moved = destroyed.copy()
        moved[0:90, 200:380] = frame[0:90, 0:180]
        wrong_page = frame.copy()
        wrong_page[80:1280] = 0
        confirmation = frame.copy()
        cv2.rectangle(confirmation, (180, 710), (640, 900), (30, 30, 30), -1)
        cv2.putText(confirmation, "Confirm", (240, 780), cv2.FONT_HERSHEY_SIMPLEX,
                    1.4, (255, 255, 255), 3)
        cv2.putText(confirmation, "Cancel", (260, 855), cv2.FONT_HERSHEY_SIMPLEX,
                    1.4, (255, 255, 255), 3)
        for name, candidate in (("native_dialog", overlaid), ("destroyed", destroyed),
                                ("unsafe_moved", moved), ("wrong_page", wrong_page),
                                ("confirmation", confirmation)):
            with self.subTest(name=name):
                ok, encoded = cv2.imencode(".png", candidate)
                self.assertTrue(ok)
                self.assertFalse(recognize_scarlett_three_day_pack(candidate, encoded.tobytes())["recognized"])

    def test_unknown_commercial_surface_blocks_before_route(self) -> None:
        _frame, payload = self._scarlett_fixture()
        with patch(
            "scripts.startup_recovery.recognize_startup_surface",
            return_value={"recognized": False, "commercial_looking": True},
        ):
            plan = classify_startup_frame("FLOW", payload)
        self.assertEqual(plan.status, "blocked")
        self.assertEqual(plan.reason, "unknown_commercial_startup_surface")
        self.assertFalse(plan.input_authority)

    @staticmethod
    def _home_supply_radial_fixture() -> np.ndarray:
        # Exact native source from observe-20261029T015823723191Z; historical
        # PNG bytes are preserved as a replay fixture, never as live authority.
        path = Path(__file__).parent / "fixtures/startup/home-supply-radial-event-hud.png"
        frame = cv2.imread(str(path))
        assert frame is not None
        return frame

    def test_native_home_event_offer_does_not_block_route_owned_radial_cleanup(self) -> None:
        import pytesseract

        frame = self._home_supply_radial_fixture()
        original_ocr = pytesseract.image_to_string

        def ocr(candidate, **kwargs):
            # Preserve the observed full-frame OCR false positive despite
            # nondeterministic detection of the small animated HUD label.
            if candidate.shape == frame.shape:
                return "Timed Top-Up"
            return original_ocr(candidate, **kwargs)

        with patch("pytesseract.image_to_string", side_effect=ocr):
            signal = commercial_surface_signal(frame)
        self.assertFalse(signal["commercial_looking"])

    def test_central_purchase_still_blocks_over_native_home_context(self) -> None:
        frame = self._home_supply_radial_fixture().copy()
        cv2.rectangle(frame, (120, 400), (580, 650), (20, 20, 20), -1)
        cv2.putText(frame, "Purchase $4.99", (130, 500),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.45, (255, 255, 255), 3)
        signal = commercial_surface_signal(frame)
        self.assertTrue(signal["commercial_looking"])
        self.assertIn("purchase", signal["terms"])

    def test_unknown_or_overlaid_source_retains_full_frame_commercial_stop(self) -> None:
        frame = self._home_supply_radial_fixture()
        for home in (
            {"state": "UNKNOWN", "recognized": False},
            {"state": "HOME_BASE", "recognized": True, "overlay": True},
            {"state": "HOME_BASE", "recognized": True, "blocking_unknown_modal": True},
        ):
            with self.subTest(home=home):
                with (
                    patch("scripts.startup_normalization.classify_home_base_live", return_value=home),
                    patch("pytesseract.image_to_string", return_value="Timed Top-Up") as ocr,
                ):
                    signal = commercial_surface_signal(frame)
                self.assertTrue(signal["commercial_looking"])
                self.assertIs(ocr.call_args.args[0], frame)
                self.assertGreater(ocr.call_args.kwargs["timeout"], 0)


    def test_blocking_unknown_modal_is_not_classified_as_clear(self) -> None:
        _frame, payload = self._scarlett_fixture()
        with patch(
            "scripts.startup_recovery.recognize_startup_surface",
            return_value={"recognized": False, "commercial_looking": False},
        ), patch(
            "scripts.startup_recovery.recognize_reset_popup",
            return_value={"recognized": False, "blocking_unknown_modal": True},
        ):
            plan = classify_startup_frame("FLOW", payload)
        self.assertEqual(plan.status, "blocked")
        self.assertEqual(plan.reason, "blocking_unknown_startup_modal")
        self.assertFalse(plan.input_authority)
        self.assertTrue(plan.recognition["blocking_unknown_modal"])

    def test_scarlett_one_input_captures_unknown_successor_without_dismissing_again(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime(Path(directory) / "runtime")
            detail = self._scarlett_detail()
            with patch(
                "scripts.startup_recovery.recognize_startup_surface",
                side_effect=(detail, detail, detail, {"recognized": False}),
            ):
                result = self._recover(
                    runtime,
                    task_id="RECRUITMENT-FREE-ATTEMPT-MAINTENANCE",
                    recognize_successor=lambda _frame: False,
                    sleep=lambda _seconds: None,
                )

            self.assertTrue(
                (runtime.session / "startup-recovery-result.json").is_file()
            )
            captured_labels = [path.name for path in runtime.session.glob("*.png")]

        self.assertEqual(result.status, "evidence_required")
        self.assertEqual(result.input_count, 1)
        self.assertTrue(result.successor_captured)
        self.assertIsNotNone(result.after_sha256)
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(runtime.reconciliations, ["confirmed"])
        self.assertTrue(
            any("startup-recovery-scarlett-post" in label for label in captured_labels)
        )

    def test_scarlett_successor_semantics_do_not_depend_on_full_frame_hash_change(self) -> None:
        class SameDigestPostRuntime(FakeRuntime):
            probe: CapturedNativeFrame | None = None

            def capture(self, label: str) -> CapturedNativeFrame:
                captured = super().capture(label)
                if label == "startup-recovery-probe":
                    self.probe = captured
                if label == "startup-recovery-scarlett-post":
                    assert self.probe is not None
                    return CapturedNativeFrame(
                        self.probe.frame.copy(),
                        self.probe.png,
                        self.probe.sha256,
                        captured.captured_monotonic,
                        captured.path,
                    )
                return captured

        with tempfile.TemporaryDirectory() as directory:
            runtime = SameDigestPostRuntime(Path(directory) / "runtime")
            detail = self._scarlett_detail()
            successor = {
                "recognized": False,
                "commercial_looking": False,
                "frame_sha256": detail["frame_sha256"],
            }
            with patch(
                "scripts.startup_recovery.recognize_startup_surface",
                side_effect=(detail, detail, detail, successor),
            ):
                result = self._recover(
                    runtime,
                    task_id="RECRUITMENT-FREE-ATTEMPT-MAINTENANCE",
                    recognize_successor=lambda _frame: True,
                    sleep=lambda _seconds: None,
                )

        self.assertEqual(result.status, "surface_dismissed_successor_captured")
        self.assertEqual(result.input_count, 1)
        self.assertIsNotNone(runtime.probe)
        self.assertEqual(result.after_sha256, runtime.probe.sha256)
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(runtime.reconciliations, ["confirmed"])

    def test_scarlett_recovery_allows_animation_between_current_frame_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime(Path(directory) / "runtime")
            probe = self._scarlett_detail()
            authorization = dict(probe, frame_sha256="1" * 64,
                                 critical_roi_hashes=(("title", "1" * 64),))
            dispatch = dict(probe, frame_sha256="2" * 64,
                            critical_roi_hashes=(("title", "2" * 64),))
            successor = {"recognized": False, "frame_sha256": "3" * 64}
            with patch("scripts.startup_recovery.recognize_startup_surface", side_effect=(probe, authorization, dispatch, successor)):
                result = self._recover(runtime, task_id="RECRUITMENT-FREE-ATTEMPT-MAINTENANCE", recognize_successor=lambda _frame: False, sleep=lambda _seconds: None, expected_source_sha256="0" * 64)
        self.assertEqual(result.status, "evidence_required")
        self.assertEqual(result.input_count, 1)
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(runtime.reconciliations, ["confirmed"])

    def test_scarlett_persistent_source_is_terminal_after_one_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime(Path(directory) / "runtime")
            detail = self._scarlett_detail()
            with patch(
                "scripts.startup_recovery.recognize_startup_surface",
                side_effect=(detail, detail, detail, detail),
            ):
                with self.assertRaisesRegex(StartupRecoveryError, "failed after dispatch"):
                    self._recover(
                        runtime,
                        task_id="RECRUITMENT-FREE-ATTEMPT-MAINTENANCE",
                        recognize_successor=lambda _frame: True,
                        sleep=lambda _seconds: None,
                    )
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(runtime.reconciliations, ["unresolved"])

    def _recover_known_with_store(self, runtime, store_path, kind, *, present_only=False,
                                  recovery_scope="same-runtime-account-scope"):
        options = dict(
            task_id="TEST-STARTUP-FLOW", recovery_scope=recovery_scope,
            recognize_successor=lambda _frame: True, sleep=lambda _seconds: None,
            action_store_factory=lambda: SafetyStore(store_path),
        )
        if kind == "scarlett":
            detail = self._scarlett_detail()
            with patch(
                "scripts.startup_recovery.recognize_startup_surface",
                return_value=detail if present_only else None,
                side_effect=None if present_only else (
                    detail, detail, detail, {"recognized": False, "commercial_looking": False}
                ),
            ):
                return recover_known_startup_overlay(runtime, **options)
        with (
            patch("scripts.startup_recovery.recognize_startup_surface", return_value={"recognized": False}),
            patch("scripts.startup_recovery.recognize_reset_popup",
                  return_value=popup() if present_only else None,
                  side_effect=None if present_only else (
                      popup(), popup(), popup(), {"recognized": False}
                  )),
        ):
            return recover_known_startup_overlay(runtime, **options)

    def test_known_startup_recovery_is_once_per_invocation_not_once_per_day(self):
        for kind in ("scarlett", "vip"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                database = root / "shared-startup.sqlite3"
                first = FakeRuntime(root / "first-invocation")
                result = self._recover_known_with_store(first, database, kind)
                self.assertEqual(result.input_count, 1)
                self.assertIn(result.status, {"recovered", "surface_dismissed_successor_captured"})
                with closing(SafetyStore(database)) as store:
                    retained_first = dict(store.get_action_by_key(result.action_key))
                with self.assertRaises(StartupRecoveryError):
                    self._recover_known_with_store(first, database, kind, present_only=True)
                self.assertEqual(first.input_count, 1)
                later = FakeRuntime(root / "later-invocation")
                later_result = self._recover_known_with_store(later, database, kind)
                self.assertEqual(later_result.input_count, 1)
                self.assertNotEqual(result.action_key, later_result.action_key)
                with closing(SafetyStore(database)) as store:
                    self.assertEqual(dict(store.get_action_by_key(result.action_key)), retained_first)
                    self.assertEqual(store.get_action_by_key(later_result.action_key)["final_status"], "confirmed")

    def test_new_startup_invocation_preserves_consequential_unresolved_block(self):
        from tests.test_safe_action_core import intent, request, TEST_TASK_ID
        from safe_action_core import CentralPolicy, TransportResult
        from safe_action_core.store import LeaseError

        for kind in ("scarlett", "vip"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                database = root / "shared-startup.sqlite3"
                with closing(SafetyStore(database)) as store:
                    store.prepare_action(intent(), CentralPolicy(supervised_tasks={TEST_TASK_ID}).evaluate(request()), time.time())
                    store.mark_input_sent("action-1", time.time(), TransportResult(True, "synthetic transport"))
                    store.mark_unresolved("action-1", time.time(), "unknown consequential result")
                    retained = dict(store.get_action("action-1"))
                runtime = FakeRuntime(root / "new-invocation")
                with self.assertRaises(LeaseError):
                    self._recover_known_with_store(runtime, database, kind, present_only=True)
                self.assertEqual(runtime.input_count, 0)
                with closing(SafetyStore(database)) as store:
                    self.assertTrue(store.has_action_block())
                    self.assertEqual(dict(store.get_action("action-1")), retained)

    def test_vip_same_invocation_is_not_rearmed_by_midnight(self):
        from datetime import datetime

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = FakeRuntime(root / "invocation")
            database = root / "shared-startup.sqlite3"
            with patch("scripts.startup_recovery.datetime") as clock:
                clock.now.return_value = datetime(2026, 10, 29, 23, 59, 59)
                self._recover_known_with_store(runtime, database, "vip", recovery_scope=None)
                clock.now.return_value = datetime(2026, 10, 30, 0, 0, 1)
                with self.assertRaises(StartupRecoveryError):
                    self._recover_known_with_store(runtime, database, "vip", present_only=True,
                                                   recovery_scope=None)
            self.assertEqual(runtime.input_count, 1)
    def test_scarlett_unknown_commercial_successor_is_retained_as_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime(Path(directory) / "runtime")
            detail = self._scarlett_detail()
            with patch(
                "scripts.startup_recovery.recognize_startup_surface",
                side_effect=(detail, detail, detail, {"recognized": False, "commercial_looking": True}),
            ):
                result = self._recover(
                    runtime,
                    task_id="RECRUITMENT-FREE-ATTEMPT-MAINTENANCE",
                    recognize_successor=lambda _frame: False,
                    sleep=lambda _seconds: None,
                )
            persisted = json.loads(
                (runtime.session / "startup-recovery-result.json").read_text(
                    encoding="utf-8"
                )
            )
        self.assertEqual(result.status, "evidence_required")
        self.assertEqual(result.reason, "evidence_required_unknown_scarlett_successor")
        self.assertEqual(result.input_count, 1)
        self.assertTrue(result.successor_captured)
        self.assertEqual(persisted["status"], "evidence_required")
        self.assertEqual(persisted["reason"], "evidence_required_unknown_scarlett_successor")
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(runtime.reconciliations, ["confirmed"])

    def test_vip_capture_exception_releases_safety_lease(self) -> None:
        class AuthorizationCaptureFailure(FakeRuntime):
            def capture(self, label: str) -> CapturedNativeFrame:
                if label == "startup-recovery-authorization-before":
                    raise RuntimeError("capture failed")
                return super().capture(label)

        with tempfile.TemporaryDirectory() as directory:
            runtime = AuthorizationCaptureFailure(Path(directory) / "runtime")
            store_path = runtime.session / "test-startup-actions.sqlite3"
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                return_value=popup(),
            ):
                with self.assertRaisesRegex(RuntimeError, "capture failed"):
                    self._recover(
                        runtime,
                        task_id="FLOW",
                        recognize_successor=lambda _frame: True,
                        sleep=lambda _seconds: None,
                    )
            reopened = SafetyStore(store_path)
            try:
                lease = reopened.get_lease(time.time())
            finally:
                reopened.close()

        self.assertIsNotNone(lease)
        assert lease is not None
        self.assertFalse(lease["valid"])
        self.assertIsNotNone(lease["released_at"])


    def test_non_popup_is_observation_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime(Path(directory) / "runtime")
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                return_value={"recognized": False},
            ):
                result = self._recover(
                    runtime,
                    task_id="FLOW",
                    recognize_successor=lambda _frame: False,
                    sleep=lambda _seconds: None,
                )
        self.assertEqual(result.status, "not_present")
        self.assertEqual(result.input_count, 0)
        self.assertEqual(runtime.input_count, 0)

    def test_exact_popup_closes_once_and_requires_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime(Path(directory) / "runtime")
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                side_effect=(popup(), popup(), popup(), {"recognized": False}),
            ):
                result = self._recover(
                    runtime,
                    task_id="FLOW",
                    recognize_successor=lambda _frame: True,
                    sleep=lambda _seconds: None,
                )
            self.assertTrue((runtime.session / "startup-recovery-result.json").is_file())
        self.assertEqual(result.status, "recovered")
        self.assertEqual(result.input_count, 1)
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(runtime.reconciliations, ["confirmed"])

    def test_vip_dismissal_retains_non_home_successor_for_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime(Path(directory) / "runtime")
            with patch("scripts.startup_recovery.recognize_reset_popup",
                       side_effect=(popup(), popup(), popup(), {"recognized": False})):
                result = self._recover(
                    runtime, task_id="FLOW", recognize_successor=lambda _frame: True,
                    successor_state="RETAINED_STARTUP_SUCCESSOR", sleep=lambda _: None,
                )
            self.assertEqual(result.status, "recovered")
            self.assertEqual(result.successor_state, "RETAINED_STARTUP_SUCCESSOR")
            self.assertEqual(runtime.input_count, 1)

    def test_vip_rejects_arbitrary_successor_without_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime(Path(directory) / "runtime")
            with patch("scripts.startup_recovery.recognize_startup_surface", return_value={"recognized": False}), \
                 patch("scripts.startup_recovery.recognize_reset_popup", return_value=popup()):
                with self.assertRaisesRegex(StartupRecoveryError, "RESET_POPUP_SUCCESSOR_REQUIRED"):
                    self._recover(runtime, task_id="FLOW", recognize_successor=lambda _: True,
                                  successor_state="UNTRUSTED_SUCCESSOR", sleep=lambda _: None)
            self.assertEqual(runtime.input_count, 0)

    def test_distinct_vip_then_scarlett_executor_actions_share_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime(Path(directory) / "runtime", max_inputs=2)
            detail = self._scarlett_detail()
            options = dict(task_id="FLOW", recognize_successor=lambda _: True,
                           successor_state="RETAINED_STARTUP_SUCCESSOR", sleep=lambda _: None)
            with patch("scripts.startup_recovery.recognize_startup_surface", return_value={"recognized": False}), \
                 patch("scripts.startup_recovery.recognize_reset_popup",
                       side_effect=(popup(), popup(), popup(), {"recognized": False})):
                vip = self._recover(runtime, **options)
            with patch("scripts.startup_recovery.recognize_startup_surface", side_effect=(
                detail, detail, detail, {"recognized": False, "commercial_looking": False}
            )):
                scarlett = self._recover(runtime, **options)
            self.assertEqual((vip.input_count, scarlett.input_count, runtime.input_count), (1, 1, 2))
            self.assertNotEqual(vip.action_key, scarlett.action_key)
            self.assertEqual(runtime.reconciliations, ["confirmed", "confirmed"])
            self.assertEqual(len(list(runtime.session.glob("startup-recovery-result*.json"))), 2)

    def test_shared_chain_counts_distinct_actions_and_stops_on_repeat(self) -> None:
        from types import SimpleNamespace
        from scripts import pnsctl

        for repeated in (False, True):
            with self.subTest(repeated=repeated), tempfile.TemporaryDirectory() as directory:
                runtime = FakeRuntime(Path(directory) / "runtime")
                identities = iter(("VIP_POINTS_GET_PTS", SCARLETT_THREE_DAY_PACK))

                def recover(_runtime, **_kwargs):
                    identity = next(identities)
                    runtime.input_count += 1
                    return StartupRecoveryResult(
                        "recovered", 1, identity, "RETAINED_STARTUP_SUCCESSOR",
                        "a" * 64, "b" * 64, identity, "confirmed",
                    )

                plans = [SimpleNamespace(status="recovery_required", popup_identity=(
                    "VIP_POINTS_GET_PTS" if repeated else SCARLETT_THREE_DAY_PACK
                ))]
                if not repeated:
                    plans.append(SimpleNamespace(status="clear", popup_identity=None))
                with patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", return_value=runtime), \
                     patch("scripts.startup_recovery.recover_known_startup_overlay", side_effect=recover), \
                     patch("scripts.startup_recovery.classify_startup_frame", side_effect=plans):
                    result = pnsctl._run_shared_startup_recovery(
                        flow_id="ANY-FLOW", task_id="test", session_directory=Path(directory),
                        max_inputs=2, recovery_scope="test",
                    )
                self.assertEqual(result["recovery_input_count"], 1 if repeated else 2)
                self.assertEqual(result["status"], "evidence_required" if repeated else "recovered")
                rows = pnsctl._startup_recovery_action_rows(result)
                self.assertEqual(len(rows), 1 if repeated else 2)
                self.assertEqual(len({row["action_key"] for row in rows}), len(rows))

    def test_persistent_popup_is_terminal_after_one_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime(Path(directory) / "runtime")
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                side_effect=(popup(), popup(), popup(), popup()),
            ):
                with self.assertRaisesRegex(StartupRecoveryError, "failed after dispatch"):
                    self._recover(
                        runtime,
                        task_id="FLOW",
                        recognize_successor=lambda _frame: False,
                        sleep=lambda _seconds: None,
                    )
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(runtime.reconciliations, ["unresolved"])

    def test_target_drift_blocks_before_transport(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime(Path(directory) / "runtime")
            moved = (270, 781, 544, 869)
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                side_effect=(popup(), popup(), popup(target=moved)),
            ):
                with self.assertRaises(StartupRecoveryError):
                    self._recover(
                        runtime,
                        task_id="FLOW",
                        recognize_successor=lambda _frame: True,
                        sleep=lambda _seconds: None,
                    )
        self.assertEqual(runtime.input_count, 0)

    def test_unknown_successor_is_terminal_after_one_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime(Path(directory) / "runtime")
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                side_effect=(popup(), popup(), popup(), {"recognized": False}),
            ):
                with self.assertRaisesRegex(StartupRecoveryError, "failed after dispatch"):
                    self._recover(
                        runtime,
                        task_id="FLOW",
                        recognize_successor=lambda _frame: False,
                        sleep=lambda _seconds: None,
                    )
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                return_value=popup(),
            ):
                with self.assertRaisesRegex(
                    StartupRecoveryError,
                    "occurrence_already_recorded",
                ):
                    self._recover(
                        runtime,
                        task_id="FLOW",
                        recognize_successor=lambda _frame: True,
                        sleep=lambda _seconds: None,
                    )
        self.assertEqual(runtime.input_count, 1)

    def test_exhausted_budget_blocks_without_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime(Path(directory) / "runtime", max_inputs=1)
            runtime.input_count = 1
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                return_value=popup(),
            ):
                with self.assertRaisesRegex(StartupRecoveryError, "budget is exhausted"):
                    self._recover(
                        runtime,
                        task_id="FLOW",
                        recognize_successor=lambda _frame: True,
                        sleep=lambda _seconds: None,
                    )
        self.assertEqual(runtime.input_count, 1)


    def test_contextual_absent_popup_returns_current_frame_without_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = ContextualRuntime(Path(directory) / "runtime")
            captured = runtime.capture("contextual-source")
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                return_value={"recognized": False},
            ):
                result = recover_contextual_vip_popup(
                    runtime,
                    captured,
                    source_context="home-or-tavern",
                    recognize_successor=lambda _frame: True,
                    action_key="noah:popup-close:home-or-tavern:source",
                    sleep=lambda _seconds: None,
                )
        self.assertIsInstance(result, ContextualPopupRecoveryResult)
        self.assertIs(result.settled_frame, captured)
        self.assertFalse(result.dismissed)
        self.assertTrue(result.popup_absent)
        self.assertTrue(result.resume_ready)
        self.assertEqual(result.input_count, 0)
        self.assertEqual(result.reason, "exact_vip_popup_absent")
        self.assertEqual(runtime.input_count, 0)

    def test_contextual_unknown_modal_never_promotes_vip_absence_to_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = ContextualRuntime(Path(directory) / "runtime")
            captured = runtime.capture("contextual-source")
            successor_calls = []
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                return_value={"recognized": False, "blocking_unknown_modal": True},
            ):
                result = recover_contextual_vip_popup(
                    runtime,
                    captured,
                    source_context="home-or-tavern",
                    recognize_successor=lambda _frame: successor_calls.append(True) or True,
                    action_key="noah:popup-close:home-or-tavern:source",
                    sleep=lambda _seconds: None,
                )
        self.assertEqual(result.reason, "blocking_unknown_modal_present")
        self.assertTrue(result.popup_absent)
        self.assertFalse(result.resume_ready)
        self.assertEqual(successor_calls, [])
        self.assertEqual(runtime.input_count, 0)

    def test_contextual_close_rebinds_moving_target_and_accepts_home_or_tavern(self) -> None:
        moved = (275, 786, 550, 868)
        for source_context in ("home-or-tavern", "home-normalization"):
            with self.subTest(source_context=source_context), tempfile.TemporaryDirectory() as directory:
                runtime = ContextualRuntime(Path(directory) / "runtime")
                captured = runtime.capture("contextual-source")
                with patch(
                    "scripts.startup_recovery.recognize_reset_popup",
                    side_effect=(
                        popup(),
                        popup(target=moved),
                        {"recognized": False},
                    ),
                ):
                    result = recover_contextual_vip_popup(
                        runtime,
                        captured,
                        source_context=source_context,
                        recognize_successor=lambda _frame: True,
                        action_key=f"noah:popup-close:{source_context}:source",
                        sleep=lambda _seconds: None,
                    )
                self.assertEqual(runtime.input_count, 1)
                self.assertEqual(runtime.tap_calls[0]["target_identity"], "reset-popup-close")
                self.assertEqual(runtime.tap_calls[0]["action_class"], "navigation")
                self.assertFalse(runtime.tap_calls[0]["consequential"])
                self.assertEqual(runtime.reconciliations, ["confirmed"])
                self.assertEqual(runtime.tap_calls[0]["target_roi"], moved)
                self.assertTrue(result.dismissed)
                self.assertTrue(result.popup_absent)
                self.assertTrue(result.resume_ready)
                self.assertEqual(result.reason, "popup_dismissed_resume_ready")

    def test_contextual_persistent_popup_is_unresolved_without_second_close(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = ContextualRuntime(Path(directory) / "runtime")
            captured = runtime.capture("contextual-source")
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                side_effect=(popup(), popup(), popup()),
            ):
                result = recover_contextual_vip_popup(
                    runtime,
                    captured,
                    source_context="home-or-tavern",
                    recognize_successor=lambda _frame: True,
                    action_key="noah:popup-close:home-or-tavern:source",
                    sleep=lambda _seconds: None,
                )
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(len(runtime.tap_calls), 1)
        self.assertEqual(runtime.reconciliations, ["unresolved"])
        self.assertTrue(result.dismissed)
        self.assertFalse(result.popup_absent)
        self.assertFalse(result.resume_ready)
        self.assertEqual(result.reason, "vip_popup_persisted")

    def test_contextual_revalidation_failure_does_not_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = ContextualRuntime(
                Path(directory) / "runtime",
                capture_failures={"contextual-vip-popup-dispatch-before"},
            )
            captured = runtime.capture("contextual-source")
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                return_value=popup(),
            ):
                result = recover_contextual_vip_popup(
                    runtime,
                    captured,
                    source_context="home-or-tavern",
                    recognize_successor=lambda _frame: True,
                    action_key="noah:popup-close:home-or-tavern:source",
                    sleep=lambda _seconds: None,
                )
        self.assertEqual(result.reason, "vip_popup_revalidation_failed")
        self.assertFalse(result.dismissed)
        self.assertIsNone(result.popup_absent)
        self.assertEqual(result.input_count, 0)
        self.assertEqual(runtime.input_count, 0)
        self.assertEqual(runtime.tap_calls, [])

    def test_contextual_input_denial_is_distinct_from_uncertain_transport(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = ContextualRuntime(Path(directory) / "runtime", deny_input=True)
            captured = runtime.capture("contextual-source")
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                side_effect=(popup(), popup()),
            ):
                result = recover_contextual_vip_popup(
                    runtime,
                    captured,
                    source_context="home-or-tavern",
                    recognize_successor=lambda _frame: True,
                    action_key="noah:popup-close:home-or-tavern:source",
                    sleep=lambda _seconds: None,
                )
        self.assertEqual(result.reason, "vip_popup_dispatch_not_authorized")
        self.assertFalse(result.dismissed)
        self.assertIsNone(result.popup_absent)
        self.assertEqual(result.input_count, 0)
        self.assertEqual(runtime.input_count, 0)

    def test_contextual_uncertain_transport_consumes_one_slot_without_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = ContextualRuntime(
                Path(directory) / "runtime",
                uncertain_transport=True,
            )
            captured = runtime.capture("contextual-source")
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                side_effect=(popup(), popup()),
            ):
                result = recover_contextual_vip_popup(
                    runtime,
                    captured,
                    source_context="home-or-tavern",
                    recognize_successor=lambda _frame: True,
                    action_key="noah:popup-close:home-or-tavern:source",
                    sleep=lambda _seconds: None,
                )
        self.assertIsNone(result.dismissed)
        self.assertIsNone(result.popup_absent)
        self.assertFalse(result.resume_ready)
        self.assertEqual(result.input_count, 1)
        self.assertEqual(result.reason, "vip_popup_transport_uncertain")
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(runtime.reconciliations, ["unresolved"])
        self.assertEqual(len(runtime.tap_calls), 1)

    def test_contextual_post_capture_failure_preserves_known_dismissal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = ContextualRuntime(
                Path(directory) / "runtime",
                capture_failures={"contextual-vip-popup-post"},
            )
            captured = runtime.capture("contextual-source")
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                side_effect=(popup(), popup()),
            ):
                result = recover_contextual_vip_popup(
                    runtime,
                    captured,
                    source_context="home-or-tavern",
                    recognize_successor=lambda _frame: True,
                    action_key="noah:popup-close:home-or-tavern:source",
                    sleep=lambda _seconds: None,
                )
        self.assertTrue(result.dismissed)
        self.assertIsNone(result.popup_absent)
        self.assertFalse(result.resume_ready)
        self.assertEqual(result.input_count, 1)
        self.assertEqual(result.reason, "vip_popup_post_capture_failed")
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(runtime.reconciliations, [])

    def test_contextual_unexpected_successor_confirms_absence_but_blocks_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = ContextualRuntime(Path(directory) / "runtime")
            captured = runtime.capture("contextual-source")
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                side_effect=(popup(), popup(), {"recognized": False}),
            ):
                result = recover_contextual_vip_popup(
                    runtime,
                    captured,
                    source_context="home-or-tavern",
                    recognize_successor=lambda _frame: False,
                    action_key="noah:popup-close:home-or-tavern:source",
                    sleep=lambda _seconds: None,
                )
        self.assertTrue(result.dismissed)
        self.assertTrue(result.popup_absent)
        self.assertFalse(result.resume_ready)
        self.assertEqual(result.reason, "popup_dismissed_context_not_ready")
        self.assertEqual(runtime.reconciliations, ["confirmed"])

    def test_contextual_dismissal_uses_one_fresh_pre_and_post_capture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = ContextualRuntime(Path(directory) / "runtime")
            captured = runtime.capture("contextual-source")
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                side_effect=(popup(), popup(), {"recognized": False}),
            ):
                result = recover_contextual_vip_popup(
                    runtime,
                    captured,
                    source_context="home-or-tavern",
                    recognize_successor=lambda _frame: True,
                    action_key="noah:popup-close:home-or-tavern:source",
                    sleep=lambda _seconds: None,
                )
        self.assertTrue(result.dismissed)
        self.assertEqual(
            runtime.capture_labels,
            [
                "contextual-source",
                "contextual-vip-popup-dispatch-before",
                "contextual-vip-popup-post",
            ],
        )

    def test_contextual_popup_identity_change_blocks_before_transport(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = ContextualRuntime(Path(directory) / "runtime")
            captured = runtime.capture("contextual-source")
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                side_effect=(popup(), popup(popup_identity="OTHER_MODAL")),
            ):
                result = recover_contextual_vip_popup(
                    runtime,
                    captured,
                    source_context="home-or-tavern",
                    recognize_successor=lambda _frame: True,
                    action_key="noah:popup-close:home-or-tavern:source",
                    sleep=lambda _seconds: None,
                )
        self.assertEqual(result.reason, "vip_popup_revalidation_failed")
        self.assertFalse(result.dismissed)
        self.assertIsNone(result.popup_absent)
        self.assertEqual(runtime.input_count, 0)
        self.assertEqual(runtime.tap_calls, [])

    def test_contextual_budget_denial_skips_fresh_capture_and_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = ContextualRuntime(Path(directory) / "runtime", max_inputs=1)
            runtime.input_count = 1
            captured = runtime.capture("contextual-source")
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                return_value=popup(),
            ):
                result = recover_contextual_vip_popup(
                    runtime,
                    captured,
                    source_context="home-or-tavern",
                    recognize_successor=lambda _frame: True,
                    action_key="noah:popup-close:home-or-tavern:source",
                    sleep=lambda _seconds: None,
                )
        self.assertEqual(result.reason, "vip_popup_dispatch_not_authorized")
        self.assertFalse(result.dismissed)
        self.assertIsNone(result.popup_absent)
        self.assertEqual(runtime.capture_labels, ["contextual-source"])
        self.assertEqual(runtime.input_count, 1)

    def test_contextual_stop_exception_propagates_without_later_capture(self) -> None:
        class StopRuntime(ContextualRuntime):
            def capture(self, label: str) -> CapturedNativeFrame:
                if label == "contextual-vip-popup-dispatch-before":
                    self.capture_labels.append(label)
                    raise RuntimeError("stop requested")
                return super().capture(label)

        with tempfile.TemporaryDirectory() as directory:
            runtime = StopRuntime(Path(directory) / "runtime")
            captured = runtime.capture("contextual-source")
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                return_value=popup(),
            ):
                with self.assertRaisesRegex(RuntimeError, "stop requested"):
                    recover_contextual_vip_popup(
                        runtime,
                        captured,
                        source_context="home-or-tavern",
                        recognize_successor=lambda _frame: True,
                        action_key="noah:popup-close:home-or-tavern:source",
                        sleep=lambda _seconds: None,
                    )
        self.assertEqual(runtime.input_count, 0)
        self.assertEqual(runtime.capture_labels, ["contextual-source", "contextual-vip-popup-dispatch-before"])


if __name__ == "__main__":
    unittest.main()
