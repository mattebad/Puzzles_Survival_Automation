from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from safe_action_core import (
    ActionClass,
    CentralPolicy,
    Observation,
    PolicyRequest,
    SafetyStore,
    TransportResult,
)
from safe_action_core.navigation import NavigationRunner, NavigationStatus, NavigationStep
from tasks.profile import HOME_MORE, HOME_QUEST


ROOT = Path(__file__).resolve().parents[1]
PROFILE = json.loads((ROOT / "runtime-profile/manifest.json").read_text())["profile_id"]
TEST_TASKS = frozenset({"TEST-NAVIGATION-RUNNER"})


def obs(**changes):
    base = Observation(
        frame_sha256="a" * 64,
        capture_completed_monotonic=1000.0,
        runtime_profile_id=PROFILE,
        width=800,
        height=1280,
        valid_png=True,
        corrupt=False,
        black=False,
        source_state="HOME_BASE",
        overlay_state="none_observed",
        target_identity="home-quest-entry",
        target_roi=(100, 100, 200, 200),
        recognized=True,
        consequence="navigate_zero_cost",
        cost_type="none",
        cost_amount=0,
        quantity=1,
        expected_postcondition="QUEST",
    )
    return replace(base, **changes)


def req(o):
    return PolicyRequest(
        action_id="nav-1",
        action_key="nav:home-quest",
        task_id="TEST-NAVIGATION-RUNNER",
        task_mode="supervised_validation",
        semantic_action="HOME_TO_QUEST",
        expected_runtime_profile_id=PROFILE,
        observation=o,
        monotonic_now=1000.1,
        observation_max_age_seconds=3,
        dispatch_max_age_seconds=2,
        lease_owner="nav",
        lease_valid=True,
        unresolved_action=False,
        duplicate_action_key=False,
        action_class=ActionClass.NAVIGATION_ONLY,
    )


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SafetyStore(Path(self.tmp.name) / "n.sqlite3")
        self.store.acquire_lease("nav", 1000, 30)
        self.clock = [1000.1]

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def runner(self):
        return NavigationRunner(
            self.store, CentralPolicy(TEST_TASKS), "nav", lambda: self.clock[0]
        )

    def test_exactly_one_dispatch(self):
        calls = []
        successor = obs(
            frame_sha256="c" * 64,
            capture_completed_monotonic=1000.3,
            source_state="QUEST",
            target_identity=None,
            target_roi=None,
        )
        result = self.runner().run(
            NavigationStep("home-quest", "HOME_BASE", "HOME_TO_QUEST", ("QUEST",)),
            req(obs()),
            lambda: obs(
                frame_sha256="b" * 64, capture_completed_monotonic=1000.05
            ),
            lambda roi: (calls.append(roi) or TransportResult(True, "OK")),
            lambda: [successor],
        )
        self.assertEqual(result.status, NavigationStatus.REACHED_SUCCESSOR)
        self.assertEqual(len(calls), 1)
        self.assertFalse(self.store.has_action_block())

    def test_safe_no_effect_allows_one_retry(self):
        calls = []
        posts = iter(
            [
                [obs(capture_completed_monotonic=1000.3)],
                [
                    obs(
                        capture_completed_monotonic=1000.4,
                        source_state="QUEST",
                        target_identity=None,
                        target_roi=None,
                    )
                ],
            ]
        )
        result = self.runner().run(
            NavigationStep("home-quest", "HOME_BASE", "HOME_TO_QUEST", ("QUEST",)),
            req(obs()),
            lambda: obs(
                frame_sha256="b" * 64, capture_completed_monotonic=1000.05
            ),
            lambda roi: (calls.append(roi) or TransportResult(True, "OK")),
            lambda: next(posts),
        )
        self.assertEqual(result.status, NavigationStatus.REACHED_SUCCESSOR)
        self.assertEqual(len(calls), 2)

    def test_unknown_successor_needs_recovery_not_global_block(self):
        result = self.runner().run(
            NavigationStep(
                "home-quest",
                "HOME_BASE",
                "HOME_TO_QUEST",
                ("QUEST",),
                allow_one_safe_retry=False,
            ),
            req(obs()),
            lambda: obs(
                frame_sha256="b" * 64, capture_completed_monotonic=1000.05
            ),
            lambda roi: TransportResult(True, "OK"),
            lambda: [
                obs(
                    source_state="UNKNOWN",
                    recognized=False,
                    target_identity=None,
                    target_roi=None,
                )
            ],
        )
        self.assertTrue(result.recovery_required)
        self.assertFalse(self.store.has_action_block())

    def test_local_change_and_spend_deny(self):
        result = self.runner().run(
            NavigationStep("home-quest", "HOME_BASE", "HOME_TO_QUEST", ("QUEST",)),
            req(obs()),
            lambda: obs(
                frame_sha256="b" * 64,
                capture_completed_monotonic=1000.05,
                target_roi=(0, 0, 1, 1),
            ),
            lambda roi: TransportResult(True, "OK"),
            lambda: [],
        )
        self.assertEqual(result.transport_calls, 0)
        self.assertEqual(
            CentralPolicy(TEST_TASKS)
            .evaluate(
                replace(req(obs()), action_class=ActionClass.SPEND_OR_STRATEGIC)
            )
            .reason_code,
            "SPEND_OR_STRATEGIC_DISABLED",
        )

    def test_declared_target_anchor_must_match_immediate_observation(self):
        calls = []
        step = NavigationStep(
            "home-more",
            "HOME_BASE",
            "HOME_TO_MORE",
            ("MORE",),
            target_anchor=HOME_MORE,
        )
        result = self.runner().run(
            step,
            req(obs()),
            lambda: obs(
                frame_sha256="b" * 64, capture_completed_monotonic=1000.05
            ),
            lambda roi: (calls.append(roi) or TransportResult(True, "OK")),
            lambda: [],
        )
        self.assertEqual(result.status, NavigationStatus.NAVIGATION_FAILED)
        self.assertEqual(result.reason, "STEP_TARGET_ANCHOR_MISMATCH")
        self.assertEqual(calls, [])

    def test_provisional_anchor_cannot_authorize_navigation(self):
        calls = []
        provisional = replace(
            HOME_QUEST,
            production_validated=False,
            evidence_dependency="missing platform screen",
        )
        step = NavigationStep(
            "home-quest",
            "HOME_BASE",
            "HOME_TO_QUEST",
            ("QUEST",),
            target_anchor=provisional,
        )
        result = self.runner().run(
            step,
            req(obs()),
            lambda: obs(
                frame_sha256="b" * 64, capture_completed_monotonic=1000.05
            ),
            lambda roi: (calls.append(roi) or TransportResult(True, "OK")),
            lambda: [],
        )
        self.assertEqual(result.status, NavigationStatus.NAVIGATION_FAILED)
        self.assertEqual(result.reason, "ANCHOR_EVIDENCE_REQUIRED")
        self.assertEqual(calls, [])

    def test_declared_postcondition_anchor_is_required(self):
        calls = []
        step = NavigationStep(
            "home-quest",
            "HOME_BASE",
            "HOME_TO_QUEST",
            ("QUEST",),
            postcondition_anchor=HOME_MORE,
            allow_one_safe_retry=False,
        )
        successor = obs(
            frame_sha256="c" * 64,
            capture_completed_monotonic=1000.3,
            source_state="QUEST",
            target_identity=None,
            target_roi=None,
        )
        result = self.runner().run(
            step,
            req(obs()),
            lambda: obs(
                frame_sha256="b" * 64, capture_completed_monotonic=1000.05
            ),
            lambda roi: (calls.append(roi) or TransportResult(True, "OK")),
            lambda: [successor],
        )
        self.assertEqual(result.status, NavigationStatus.NAVIGATION_FAILED)
        self.assertEqual(result.reason, "UNKNOWN_SUCCESSOR")
        self.assertEqual(len(calls), 1)

    def test_configured_old_anchor_must_disappear(self):
        calls = []
        step = NavigationStep(
            "home-quest",
            "HOME_BASE",
            "HOME_TO_QUEST",
            ("QUEST",),
            source_anchor=HOME_QUEST,
            old_anchor_must_disappear=True,
            allow_one_safe_retry=False,
        )
        successor = obs(
            frame_sha256="c" * 64,
            capture_completed_monotonic=1000.3,
            source_state="QUEST",
            target_identity=HOME_QUEST.name,
            target_roi=HOME_QUEST.roi,
        )
        result = self.runner().run(
            step,
            req(obs()),
            lambda: obs(
                frame_sha256="b" * 64, capture_completed_monotonic=1000.05
            ),
            lambda roi: (calls.append(roi) or TransportResult(True, "OK")),
            lambda: [successor],
        )
        self.assertEqual(result.status, NavigationStatus.NAVIGATION_FAILED)
        self.assertEqual(result.reason, "UNKNOWN_SUCCESSOR")
        self.assertEqual(len(calls), 1)

    def test_capability_firewall_does_not_add_parallel_executor(self):
        from safe_action_core import ActionTransaction, SafeActionExecutor

        self.assertIs(ActionTransaction, SafeActionExecutor)
        self.assertEqual(self.runner().__class__.__name__, "NavigationRunner")


if __name__ == "__main__":
    unittest.main()
