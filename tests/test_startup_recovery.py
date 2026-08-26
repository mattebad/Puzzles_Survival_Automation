from __future__ import annotations

import json
import hashlib
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
    StartupRecoveryError,
    classify_startup_frame,
    recover_known_startup_overlay,
)
from scripts.startup_surface_recognition import (
    SCARLETT_CRITICAL_ROI_HASHES,
    SCARLETT_EXPECTED_SUCCESSOR,
    SCARLETT_FORBIDDEN_PURCHASE_ROIS,
    SCARLETT_FRAME_SHA256,
    SCARLETT_MAX_INPUTS,
    SCARLETT_SAFE_BACK_ROI,
    SCARLETT_SAFE_BACK_TARGET_IDENTITY,
    SCARLETT_THREE_DAY_PACK,
    is_exact_scarlett_recognition,
    recognize_scarlett_three_day_pack,
)


TARGET = (263, 781, 537, 869)


def popup(*, target=TARGET) -> dict[str, object]:
    return {
        "recognized": True,
        "popup_identity": "VIP_POINTS_GET_PTS",
        "target_identity": "reset-popup-close",
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
        self.started = time.monotonic()
        self.keys: set[str] = set()
        self.reconciliations: list[str] = []

    def capture(self, label: str) -> CapturedNativeFrame:
        self.ordinal += 1
        frame = np.full((1280, 800, 3), self.ordinal, np.uint8)
        payload = f"{label}:{self.ordinal}".encode()
        path = self.session / f"{self.ordinal:04d}-{label}.png"
        path.write_bytes(payload)
        return CapturedNativeFrame(
            frame,
            payload,
            hashlib.sha256(payload).hexdigest(),
            self.started + self.ordinal * 0.001,
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
        self.assertEqual(world.status, "route_owned")
        self.assertEqual(world.recovery_owner, "flow_specific_popup_recovery")
        self.assertEqual(daily_row.status, "blocked")
        self.assertEqual(unsupported.status, "blocked")
        self.assertIsNone(unsupported.recovery_owner)

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
            ),
            "safe_exit_target_identity": SCARLETT_SAFE_BACK_TARGET_IDENTITY,
            "safe_exit_roi": SCARLETT_SAFE_BACK_ROI,
            "forbidden_purchase_rois": SCARLETT_FORBIDDEN_PURCHASE_ROIS,
            "purchase_exclusion_verified": True,
            "critical_roi_hashes": SCARLETT_CRITICAL_ROI_HASHES,
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
            "wrong_stable_roi_signature": {
                "critical_roi_hashes": (
                    ("title", "0" * 64),
                    *SCARLETT_CRITICAL_ROI_HASHES[1:],
                )
            },
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
        self.assertEqual(fixture_result["critical_roi_hashes"], animated_result["critical_roi_hashes"])
        self.assertEqual(animated_result["critical_roi_hashes"], SCARLETT_CRITICAL_ROI_HASHES)
        self.assertEqual(animated_result["frame_sha256"], hashlib.sha256(animated_payload).hexdigest())

    def test_scarlett_recognition_rejects_stable_surface_anchor_drift(self) -> None:
        frame, _payload = self._scarlett_fixture()
        drifted = frame.copy(); drifted[180:220, 300:340] = 0
        ok, encoded = cv2.imencode(".png", drifted); self.assertTrue(ok)
        with patch("scripts.startup_surface_recognition._title_text", return_value="Scarlett 3-Day Pack"):
            result = recognize_scarlett_three_day_pack(drifted, encoded.tobytes())
        self.assertFalse(result["recognized"])
        self.assertEqual(result["reason"], "stable_scarlett_roi_signature_mismatch")

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
            authorization = dict(probe, frame_sha256="1" * 64)
            dispatch = dict(probe, frame_sha256="2" * 64)
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


if __name__ == "__main__":
    unittest.main()
