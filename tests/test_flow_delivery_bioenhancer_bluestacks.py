"""Focused tests for the BlueStacks Bioenhancer flow-delivery adapter."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
import numpy as np


import scripts.pnsctl as pnsctl
import scripts.flow_delivery_bioenhancer_bluestacks as delivery
import scripts.navigation_development_boundary as boundary
import scripts.bioenhancer_free_research_canary as canary
from scripts.bioenhancer_free_research_canary import (
    _free_research_cooldown_visible,
    evaluate_free_research_postcondition,
)
from scripts.flow_delivery_bioenhancer_bluestacks import (
    FLOW_ID,
    MAX_INPUTS,
    RUNNER_ID,
    _initial_observation,
    _write_delivery_result,
    _max_inputs,
    run_bioenhancer_free_research,
    verify_bioenhancer_free_research,
)
from scripts.navigation_development_boundary import (
    DevelopmentInitialObservation,
    DevelopmentSession,
)
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from tasks.home_atlas_planner import PlanDisposition
from tasks.perception_bundle import PerceptionBundleError


class _PanRuntime:
    execute = True

    def __init__(self, session: Path, *, swipe_error: BaseException | None = None) -> None:
        self.session = session
        self.ordinal = 0
        self.swipe_error = swipe_error
        self.swipes: list[dict[str, object]] = []

    def capture(self, label: str) -> CapturedNativeFrame:
        self.ordinal += 1
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        frame[0, 0, 0] = self.ordinal
        payload = f"frame-{self.ordinal}".encode()
        return CapturedNativeFrame(
            frame,
            payload,
            hashlib.sha256(payload).hexdigest(),
            float(self.ordinal),
            self.session / f"{label}.png",
        )

    def swipe(self, captured, *, start, end, action_key, target_identity) -> None:
        if self.swipe_error is not None:
            raise self.swipe_error
        self.swipes.append(
            {
                "marker": int(captured.frame[0, 0, 0]),
                "start": start,
                "end": end,
                "action_key": action_key,
                "target_identity": target_identity,
            }
        )


class _PanNavigator:
    def __init__(self, plans) -> None:
        self._plans = iter(plans)
        self.plan_calls = 0

    def plan(self, _localization, _binding):
        self.plan_calls += 1
        return next(self._plans)

    def record_progress(self, _before, _after):
        return SimpleNamespace(accepted=True, reason="progress_observed")


def _run_bio_pan_case(
    root: Path,
    clean_home,
    *,
    swipe_error: BaseException | None = None,
):
    runtime = _PanRuntime(root / "runtime", swipe_error=swipe_error)
    localization = SimpleNamespace(recognized=True, frame_sha256="localization")
    localizer = SimpleNamespace(localize=lambda _frame: localization)
    atlas = SimpleNamespace(lookup_building=lambda _building_id: SimpleNamespace())
    pan_plan = SimpleNamespace(
        disposition=PlanDisposition.PAN,
        reason="calculated_direct_pan",
        drag_start=(200, 600),
        drag_end=(300, 600),
    )
    complete_plan = SimpleNamespace(
        disposition=PlanDisposition.COMPLETE,
        reason="current_frame_semantic_building_bound",
        drag_start=None,
        drag_end=None,
    )
    navigator = _PanNavigator((pan_plan, complete_plan, complete_plan))
    result = None
    error = None
    terminal_status = None
    with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
        with (
            patch.object(canary, "load_home_atlas", return_value=atlas),
            patch.object(canary, "normalize_home_atlas_startup", return_value=(object(), object())),
            patch.object(canary, "DirectPanNavigator", return_value=navigator),
            patch.object(canary, "BlueStacksHomeLocalizer", return_value=localizer),
            patch.object(canary, "_atlas_stack", return_value=(atlas, localization)),
            patch.object(canary, "bind_visible_building", return_value=None),
            patch.object(canary, "bind_research_radial_option", return_value=None),
            patch.object(canary, "bind_research_lab", return_value=None),
            patch.object(canary, "is_clean_home_frame", side_effect=clean_home),
        ):
            with DevelopmentSession(
                owner="bio-pan-test",
                invocation_id="bio-pan-test",
                session_directory=root / "session",
                max_inputs=4,
            ) as session:
                try:
                    result = canary.run(
                        max_inputs=4,
                        settle_seconds=0,
                        session=session,
                        runtime=runtime,
                        session_directory=root / "session",
                    )
                except (RuntimeError, PerceptionBundleError) as exc:
                    error = exc
                input_count = session.input_count
                terminal_status = session.terminal_status
    persisted_path = root / "session" / "result.json"
    persisted = (
        json.loads(persisted_path.read_text(encoding="utf-8"))
        if persisted_path.is_file()
        else None
    )
    return result, error, runtime, navigator, input_count, persisted, terminal_status


class BioenhancerFlowDeliveryTests(unittest.TestCase):
    def _lease(self, *, maximum: int = 8):
        return {
            "owner": "outer-development-session",
            "max_inputs": maximum,
            "development_session": SimpleNamespace(
                session_directory=Path("tests") / "bioenhancer-dry-run-session",
                run_action=lambda **_kwargs: None,
            ),
        }
    def test_pan_rejects_unclean_planning_home_before_planner(self):
        with tempfile.TemporaryDirectory() as directory:
            (
                result,
                error,
                runtime,
                navigator,
                input_count,
                _persisted,
                _terminal_status,
            ) = _run_bio_pan_case(
                Path(directory),
                lambda frame: int(frame[0, 0, 0]) != 1,
            )

        self.assertIsNone(error)
        self.assertIsNotNone(result)
        self.assertEqual(result["reason"], "home_not_clean_before_pan")
        self.assertEqual(input_count, 0)
        self.assertEqual(runtime.swipes, [])
        self.assertEqual(navigator.plan_calls, 0)

    def test_pan_rejects_unclean_fresh_home_before_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            (
                result,
                error,
                runtime,
                navigator,
                input_count,
                persisted,
                terminal_status,
            ) = _run_bio_pan_case(
                Path(directory),
                lambda frame: int(frame[0, 0, 0]) != 2,
            )

        self.assertIsNone(error)
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "PRE_DISPATCH_HOME_NOT_CLEAN")
        self.assertEqual(persisted, result)
        self.assertEqual(terminal_status, "evidence_required")
        self.assertEqual(input_count, 0)
        self.assertEqual(result["input_count"], 0)
        self.assertFalse(result["transport_dispatched"])
        self.assertEqual(runtime.swipes, [])
        self.assertEqual(navigator.plan_calls, 1)

    def test_pan_transport_runtime_error_still_propagates(self):
        with tempfile.TemporaryDirectory() as directory:
            (
                result,
                error,
                runtime,
                navigator,
                input_count,
                persisted,
                _terminal_status,
            ) = _run_bio_pan_case(
                Path(directory),
                lambda _frame: True,
                swipe_error=RuntimeError("pan transport failed"),
            )

        self.assertIsNone(result)
        self.assertIsInstance(error, RuntimeError)
        self.assertIn("pan transport failed", str(error))
        self.assertIsNone(persisted)
        self.assertEqual(input_count, 1)
        self.assertEqual(runtime.swipes, [])
        self.assertEqual(navigator.plan_calls, 1)

    def test_typed_pan_transport_error_after_input_is_not_reclassified(self):
        with tempfile.TemporaryDirectory() as directory:
            (
                result,
                error,
                runtime,
                navigator,
                input_count,
                persisted,
                _terminal_status,
            ) = _run_bio_pan_case(
                Path(directory),
                lambda _frame: True,
                swipe_error=PerceptionBundleError(
                    "PRE_DISPATCH_HOME_NOT_CLEAN",
                    "typed pan transport failed",
                ),
            )

        self.assertIsNone(result)
        self.assertIsInstance(error, PerceptionBundleError)
        self.assertEqual(error.reason_code, "PRE_DISPATCH_HOME_NOT_CLEAN")
        self.assertIn("typed pan transport failed", str(error))
        self.assertIsNone(persisted)
        self.assertEqual(input_count, 1)
        self.assertEqual(runtime.swipes, [])
        self.assertEqual(navigator.plan_calls, 1)

    def test_clean_pan_remains_allowed_and_uses_fresh_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            (
                result,
                error,
                runtime,
                _navigator,
                input_count,
                _persisted,
                _terminal_status,
            ) = _run_bio_pan_case(
                Path(directory),
                lambda _frame: True,
            )

        self.assertIsNone(error)
        self.assertIsNotNone(result)
        self.assertEqual(input_count, 1)
        self.assertEqual(len(runtime.swipes), 1)
        self.assertEqual(runtime.swipes[0]["marker"], 2)


    def test_registry_binds_consequential_runner_without_promotion(self):
        contract = pnsctl._load_bluestacks_flow_registry()[FLOW_ID]
        self.assertEqual(contract["runner"], RUNNER_ID)
        self.assertEqual(contract["consequence_class"], "consequential")
        self.assertIn(RUNNER_ID, pnsctl._BLUESTACKS_FLOW_RUNNERS)
        self.assertEqual(
            contract["recovery_handler"],
            "bioenhancer_free_research_bluestacks_recovery",
        )

    def test_dry_run_is_zero_transport_and_preserves_disabled_state(self):
        result = run_bioenhancer_free_research(
            {"active_flow_id": FLOW_ID},
            self._lease(),
            live=False,
        )
        self.assertIn('"status": "dry_run"', result)
        self.assertIn('"input_count": 0', result)
        self.assertIn('"free_research_transport_calls": 0', result)
        self.assertIn('"production_registration": "NOT_REGISTERED"', result)
        self.assertIn('"scheduler_enabled": false', result)

    def test_max_inputs_is_bounded(self):
        self.assertEqual(_max_inputs(self._lease(maximum=MAX_INPUTS)), MAX_INPUTS)
        with self.assertRaises(pnsctl.OperatorError):
            _max_inputs(self._lease(maximum=MAX_INPUTS + 1))
        with self.assertRaises(pnsctl.OperatorError):
            _max_inputs(self._lease(maximum=0))

    def test_free_research_postcondition_requires_cooldown_timer(self):
        self.assertEqual(
            evaluate_free_research_postcondition("Free in 18:12:44"),
            {
                "count_observed": False,
                "timer_proven": True,
                "proven": True,
            },
        )
        for token_text in ("2/100", "1/100"):
            with self.subTest(token_text=token_text):
                self.assertEqual(
                    evaluate_free_research_postcondition(token_text),
                    {
                        "count_observed": True,
                        "timer_proven": False,
                        "proven": False,
                    },
                )

    def test_free_research_cooldown_rejects_binding_evidence(self):
        self.assertTrue(_free_research_cooldown_visible("Free in 18:11:52 2/100"))
        self.assertFalse(_free_research_cooldown_visible("Free Research 1x"))

    def test_live_route_requires_real_active_session_and_exact_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with DevelopmentSession(
                    owner=f"pnsctl-development-session:{FLOW_ID}",
                    invocation_id="bio-bound",
                    session_directory=root / "outer",
                    max_inputs=MAX_INPUTS,
                ) as session:
                    digest = hashlib.sha256(b"initial").hexdigest()
                    initial = DevelopmentInitialObservation(
                        {"frame_sha256": digest},
                        digest,
                        invocation_id=session.invocation_id,
                    )
                    session.set_initial_observation(initial)
                    lease = {
                        "development_session": session,
                        "initial_observation": initial,
                        "initial_frame_sha256": digest,
                        "max_inputs": MAX_INPUTS,
                    }
                    self.assertEqual(
                        _initial_observation(lease, session)["frame_sha256"], digest
                    )
                    mismatched = dict(lease)
                    mismatched["initial_observation"] = DevelopmentInitialObservation(
                        {"frame_sha256": digest},
                        digest,
                        invocation_id=session.invocation_id,
                    )
                    with self.assertRaises(pnsctl.OperatorError):
                        _initial_observation(mismatched, session)
            with patch.object(delivery.LocalBlueStacksRuntime, "connect") as connect:
                with self.assertRaises(pnsctl.OperatorError):
                    run_bioenhancer_free_research(
                        {},
                        {
                            "development_session": SimpleNamespace(run_action=lambda: None),
                            "max_inputs": MAX_INPUTS,
                        },
                        live=True,
                    )
                connect.assert_not_called()

    def test_live_route_binds_one_session_trace_and_semantic_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = root / "runtime"
            child.mkdir()
            events = [
                {"type": "dispatch", "execute": True, "action_key": "home-pan:1"},
                {"type": "dispatch", "execute": True, "action_key": "open-research-lab:1"},
                {"type": "dispatch", "execute": True, "action_key": "open-research:1"},
                {"type": "dispatch", "execute": True, "action_key": "free-research-1x:1"},
                {"type": "dispatch", "execute": True, "action_key": "bioenhancer-return-home:1"},
            ]
            (child / "events.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in events), encoding="utf-8"
            )
            initial_bytes = b"typed-bioenhancer-initial"
            digest = hashlib.sha256(initial_bytes).hexdigest()
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with DevelopmentSession(
                    owner=f"pnsctl-development-session:{FLOW_ID}",
                    invocation_id="bio-continuous",
                    session_directory=root / "outer",
                    max_inputs=MAX_INPUTS,
                ) as session:
                    (session.session_directory / "source.png").write_bytes(initial_bytes)
                    initial = DevelopmentInitialObservation(
                        {"frame_sha256": digest},
                        digest,
                        frame_path="source.png",
                        invocation_id=session.invocation_id,
                    )
                    session.set_initial_observation(initial)
                    session.adopt_retained_transport_count(5, source="test-events")
                    lease = {
                        "owner": session.owner,
                        "development_session": session,
                        "initial_observation": initial,
                        "initial_frame_sha256": digest,
                        "max_inputs": MAX_INPUTS,
                    }
                    with (
                        patch.object(
                            delivery.LocalBlueStacksRuntime,
                            "connect",
                            return_value=SimpleNamespace(session=child),
                        ),
                        patch(
                            "scripts.bioenhancer_free_research_canary.run",
                            return_value={
                                "status": "completed",
                                "semantic_postcondition": {
                                    "proven": True,
                                    "timer_proven": True,
                                    "count_observed": True,
                                },
                                "return_home": {"status": "home_returned"},
                            },
                        ),
                    ):
                        result = json.loads(
                            run_bioenhancer_free_research({}, lease, live=True)
                        )
                    self.assertEqual(result["status"], "completed")
                    self.assertEqual(result["proof_topology"], "continuous")
                    self.assertIs(initial, session.initial_observation)
                    self.assertEqual(result["initial_frame_sha256"], digest)
                    self.assertEqual(result["input_count"], 5)
                    self.assertEqual(result["free_research_transport_calls"], 1)
                    self.assertEqual(result["causal_trace_count"], 1)
                    self.assertTrue(result["causal_trace"]["read_only"])
                    self.assertFalse(result["causal_trace"]["input_authority"])
                    self.assertEqual(result["causal_trace"]["transport_count"], 5)
                    self.assertEqual(session.causal_trace, result["causal_trace"])

    def test_dispatch_without_cooldown_requires_reconciliation_and_denies_retry(self):
        result = delivery._result_payload(
            {
                "status": "completed",
                "semantic_postcondition": {"proven": False, "timer_proven": False},
                "return_home": {"status": "home_returned"},
            },
            session_directory="runtime",
            input_count=4,
            free_calls=1,
            maximum=MAX_INPUTS,
        )
        self.assertEqual(result["status"], "effect_reconciliation_required")
        self.assertTrue(result["effect_reconciliation_required"])
        self.assertTrue(result["identical_retry_denied"])

    def test_completed_artifact_passes_operational_generic_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / ".local-captures" / "bioenhancer-completed"
            (session / "frames").mkdir(parents=True)
            (session / "frames" / "terminal.png").write_bytes(b"native-frame")
            initial_bytes = b"typed-initial"
            (session / "frames" / "initial.png").write_bytes(initial_bytes)
            digest = hashlib.sha256(initial_bytes).hexdigest()
            events = [
                {"type": "dispatch", "execute": True, "action_key": "open-research-lab:1"},
                {"type": "dispatch", "execute": True, "action_key": "open-research:1"},
                {"type": "dispatch", "execute": True, "action_key": "free-research-1x:1"},
                {"type": "dispatch", "execute": True, "action_key": "bioenhancer-return-home:1"},
            ]
            (session / "events.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in events), encoding="utf-8"
            )
            trace = {
                "trace_count": 1,
                "read_only": True,
                "input_authority": False,
                "proof_topology": "continuous",
                "initial_frame_sha256": digest,
                "transport_count": 4,
                "free_research_transport_calls": 1,
            }
            (session / "causal-trace.json").write_text(
                json.dumps(trace) + "\n", encoding="utf-8"
            )
            _write_delivery_result(
                session,
                {
                    "status": "completed",
                    "free_research_transport_calls": 1,
                    "input_count": 4,
                    "terminal_home_verified": True,
                    "semantic_postcondition": {"proven": True, "timer_proven": True},
                    "proof_topology": "continuous",
                    "initial_observation": {
                        "frame_sha256": digest,
                        "frame_path": "frames/initial.png",
                        "invocation_id": "test-bioenhancer",
                    },
                    "initial_frame_sha256": digest,
                    "causal_trace_count": 1,
                    "causal_trace": trace,
                    "effect_reconciliation_required": False,
                    "reason": "free_research_postcondition_verified",
                },
                lease={"owner": "test-owner"},
                maximum=8,
            )
            with (
                patch.object(pnsctl, "REPO_ROOT", root),
                patch.object(
                    pnsctl,
                    "_load_flow_delivery_state",
                    side_effect=pnsctl.OperatorError("no active delivery"),
                ),
            ):
                verdict = json.loads(pnsctl.bluestacks_verify_flow(session))
            self.assertEqual(verdict["status"], "verified")
            self.assertEqual(verdict["flow_id"], FLOW_ID)

            broken = json.loads((session / "flow-delivery-result.json").read_text())
            broken["semantic_postcondition"]["timer_proven"] = False
            verdict = verify_bioenhancer_free_research(
                {"result": broken, "session_directory": str(session)}, {}, {}
            )
            self.assertEqual(verdict["status"], "evidence_required")


if __name__ == "__main__":
    unittest.main()
