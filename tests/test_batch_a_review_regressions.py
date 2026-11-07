from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2

from automation_service.daily_rewards import DailyRewardsRunner, PRODUCT_ID, daily_rewards_next_due
from automation_service.recruitment import recruitment_reset
from tasks.runtime_identity import derive_resource_runtime_identity, resource_fixed_runtime_binding
from tasks.scheduler_task_result import SchedulerIdentity
from tests import test_daily_row_claim_bluestacks as native_tests
from tests.test_service_daily_rewards import _FakeNative, _HeldLock
from tests.support.environment import requires_tesseract


class DailyKnownPartialNativeRegressionTests(unittest.TestCase):
    @requires_tesseract
    def test_new_ready_slot_at_home_boundary_preserves_real_native_confirmed_prefix(self):
        replay = native_tests.DailyMilestoneReadinessTests()
        wall_utc = 1794039692.0
        backend = derive_resource_runtime_identity(
            resource_fixed_runtime_binding(), datetime.fromtimestamp(wall_utc, timezone.utc),
        )
        identity = SchedulerIdentity(
            backend.account_id, backend.server_id, recruitment_reset(wall_utc), PRODUCT_ID,
        )
        original_frame = native_tests._frame
        ready_image = cv2.imread(str(
            replay.NATIVE_FIXTURE.parent / "native-chest1-ready-before-20261107.png"
        ))
        self.assertIsNotNone(ready_image)
        boundary_observations = []

        def capture(directory, label, *, image=None, **kwargs):
            if label == "daily-rewards_return-home-back-1-immediate-before":
                # Explicit offline counterfactual: a distinct second slot becomes
                # ready after the first chest is confirmed, before Back dispatch.
                image = image.copy()
                image[178:275, 224:324] = ready_image[178:275, 84:184]
                boundary_observations.append(label)
            return original_frame(directory, label, image=image, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(native_tests, "_frame", capture):
                partial, runtime, session = replay._run_fake_static_zero_claim_route(
                    root, return_home=True, ready_count=1, aggregate_ready=True,
                    reset_id=identity.reset_id, wall_utc=wall_utc,
                )
            self.assertEqual(len(boundary_observations), 1)
            self.assertEqual(partial["status"], "evidence_required")
            self.assertEqual(partial["committed_action_count"], 2)
            self.assertEqual((runtime.aggregate_attempts, runtime.claim_attempts), (1, 1))
            self.assertFalse(partial["effect_reconciliation_required"])
            self.assertFalse(partial["terminal_home_verified"])
            self.assertEqual(partial["unclaimed_ready_chest_count"], 1)
            self.assertEqual([row["final_status"] for row in runtime.journal_rows], ["confirmed"] * 2)
            partial["native_session_directory"] = str(session.session_directory)
            admitted = DailyRewardsRunner(
                native=_FakeNative(partial), output_directory=root, utc_clock=lambda: wall_utc,
            )(
                identity, None, lambda: None,
                runtime_input_lock=_HeldLock(), occurrence_key="occ:v1:native-known-partial",
            )
            self.assertEqual(admitted["status"], "deferred")
            self.assertEqual(admitted["committed_action_count"], 2)
            self.assertTrue(admitted["identical_retry_denied"])
            self.assertEqual(
                daily_rewards_next_due(admitted, identity, wall_utc), wall_utc + 300,
            )
