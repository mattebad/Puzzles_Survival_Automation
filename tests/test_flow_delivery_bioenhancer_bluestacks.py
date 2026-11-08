"""Focused tests for the BlueStacks Bioenhancer flow-delivery adapter."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import cv2


import scripts.pnsctl as pnsctl
import scripts.flow_delivery_bioenhancer_bluestacks as delivery
import scripts.navigation_development_boundary as boundary
import scripts.bioenhancer_free_research_route as bio_route
from scripts.bioenhancer_free_research_route import (
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
from tasks.home_atlas_planner import PlanDisposition, SafeInteractionRegion
from tasks.perception_bundle import PerceptionBundleError
from tests.support.environment import requires_tesseract



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
    # plan_research_lab_pan reads the navigator's safe region and calibration
    # to preview the right-HUD waypoint before it asks the navigator to plan.
    safe_region = SafeInteractionRegion("home-default", (145, 180, 650, 1010), (400, 600))
    calibration = object()

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
            patch.object(bio_route, "load_home_atlas", return_value=atlas),
            patch.object(bio_route, "normalize_home_atlas_startup", return_value=(object(), object())),
            patch.object(bio_route, "DirectPanNavigator", return_value=navigator),
            patch.object(bio_route, "BlueStacksHomeLocalizer", return_value=localizer),
            patch.object(bio_route, "_atlas_stack", return_value=(atlas, localization)),
            # Binding is None here, so the waypoint is never admitted; the
            # preview of the normal plan must not need a real atlas.
            patch.object(
                bio_route,
                "plan_direct_pan",
                return_value=SimpleNamespace(
                    disposition=PlanDisposition.PAN,
                    reason="calculated_direct_pan",
                    viewport=SimpleNamespace(rejection_counts=()),
                ),
            ),
            patch.object(bio_route, "bind_bioenhancer_back", return_value=None),
            patch.object(bio_route, "bind_visible_building", return_value=None),
            patch.object(bio_route, "bind_research_radial_option", return_value=None),
            patch.object(bio_route, "bind_research_lab", return_value=None),
            patch.object(bio_route, "recognize_free_research_cooldown", return_value=None),
            patch.object(bio_route, "is_clean_home_frame", side_effect=clean_home),
        ):
            with DevelopmentSession(
                owner="bio-pan-test",
                invocation_id="bio-pan-test",
                session_directory=root / "session",
                max_inputs=4,
            ) as session:
                try:
                    result = bio_route.run(
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
                lambda frame: int(frame[0, 0, 0]) != 2,
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
                lambda frame: int(frame[0, 0, 0]) != 3,
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
        self.assertEqual(runtime.swipes[0]["marker"], 3)


    def test_registry_binds_consequential_runner_without_promotion(self):
        contract = pnsctl._load_bluestacks_flow_registry()[FLOW_ID]
        self.assertEqual(contract["runner"], RUNNER_ID)
        self.assertEqual(contract["consequence_class"], "consequential")
        self.assertIn(RUNNER_ID, pnsctl._BLUESTACKS_FLOW_RUNNERS)

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
                            "scripts.bioenhancer_free_research_route.run",
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
            with patch.object(pnsctl, "REPO_ROOT", root):
                verdict = json.loads(pnsctl.bluestacks_verify_flow(session))
            self.assertEqual(verdict["status"], "verified")
            self.assertEqual(verdict["flow_id"], FLOW_ID)

            broken = json.loads((session / "flow-delivery-result.json").read_text())
            broken["semantic_postcondition"]["timer_proven"] = False
            verdict = verify_bioenhancer_free_research(
                {"result": broken, "session_directory": str(session)}, {}, {}
            )
            self.assertEqual(verdict["status"], "evidence_required")


class BioenhancerCooldownTests(unittest.TestCase):
    NOW = datetime(2026, 10, 29, 7, 10, tzinfo=timezone.utc)

    def test_unique_bounded_timer_has_exact_utc_next_due(self):
        for text, seconds in (("Free in 16:57:15", 61035), ("Free in 01:30", 90), ("Free in 24:00:00", 86400)):
            result = bio_route.parse_free_research_cooldown(text, now=self.NOW)
            self.assertEqual(result["seconds_remaining"], seconds)
            self.assertEqual(datetime.fromisoformat(result["next_due_utc"]), self.NOW + timedelta(seconds=seconds))
        for text in ("Free in 00:00", "Free in 25:00:00", "Free in 16:99:00", "Free in 01:60", "Free in 99:10", "Free in 16:57:15 Free in 10:00", "Free in 16:57:15 Free in unknown", "2/100", "Free Research 1x"):
            with self.subTest(text=text):
                self.assertIsNone(bio_route.parse_free_research_cooldown(text, now=self.NOW))
        with self.assertRaises(ValueError):
            bio_route.parse_free_research_cooldown("Free in 16:57:15", now=self.NOW.replace(tzinfo=None))

    def test_timer_requires_exact_bioenhancer_context(self):
        frame = np.zeros((1280, 800, 3), np.uint8)
        tokens = [{"text_cf": value, "text": value} for value in ("Free", "in", "16:57:15")]
        with patch.object(bio_route, "_ocr_tokens", return_value=tokens), patch.object(bio_route, "bind_bioenhancer_back", return_value=None):
            self.assertIsNone(bio_route.recognize_free_research_cooldown(frame, now=self.NOW))
        with patch.object(bio_route, "_ocr_tokens", return_value=tokens), patch.object(bio_route, "bind_bioenhancer_back", return_value=object()):
            self.assertEqual(bio_route.recognize_free_research_cooldown(frame, now=self.NOW)["seconds_remaining"], 61035)

    def _route_case(self, root, *, already_open, ready_startup=False):
        class Runtime:
            def __init__(self):
                self.session = root / "runtime"
                (self.session / "frames").mkdir(parents=True)
                self.phase = 0 if ready_startup else 3 if already_open else 1
                self.ordinal = 0
                self.taps = []
                self.home_captures = 0

            def capture(self, label):
                if self.phase == 4:
                    self.home_captures += 1
                    if self.home_captures > 1:
                        raise TimeoutError("redundant capture after verified Home")
                self.ordinal += 1
                frame = np.full((1280, 800, 3), self.phase, np.uint8)
                raw = cv2.imencode(".png", frame)[1].tobytes()
                path = self.session / "frames" / f"{self.ordinal:04}-{label}.png"
                path.write_bytes(raw)
                return CapturedNativeFrame(frame, raw, hashlib.sha256(raw).hexdigest(), float(self.ordinal), path)

            def tap(self, _before, *, target_identity, **_kwargs):
                self.taps.append(target_identity)
                self.phase = {bio_route.RESEARCH_LAB_ID: 2, "research-lab-radial-research": 3,
                    "bioenhancer-in-game-back": 1 if self.phase == 0 else 4}[target_identity]

        runtime = Runtime()
        cooldown = bio_route.parse_free_research_cooldown("Free in 16:57:15", now=self.NOW)
        def control(frame, phase, identity):
            return bio_route.BoundControl(identity, (200, 300, 260, 360), (), .9) if int(frame[0, 0, 0]) == phase else None
        with (
            patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"),
            patch.object(bio_route, "recognize_free_research_cooldown", side_effect=lambda frame: dict(cooldown) if int(frame[0, 0, 0]) == 3 else None),
            patch.object(bio_route, "is_clean_home_frame", side_effect=lambda frame: int(frame[0, 0, 0]) in (1, 4)),
            patch.object(bio_route, "bind_bioenhancer_back", side_effect=lambda frame: control(
                frame, 0 if int(frame[0, 0, 0]) == 0 else 3, "bioenhancer-in-game-back")),
            patch.object(bio_route, "load_home_atlas", return_value=object()),
            patch.object(bio_route, "normalize_home_atlas_startup", return_value=(object(), object())) as normalize,
            patch.object(bio_route, "DirectPanNavigator", return_value=object()),
            patch.object(bio_route, "plan_research_lab_pan", return_value=(object(), None, SimpleNamespace(disposition=PlanDisposition.BIND, reason="bound", drag_start=None, drag_end=None))),
            patch.object(bio_route, "bind_research_lab", side_effect=lambda frame: control(frame, 1, bio_route.RESEARCH_LAB_ID)),
            patch.object(bio_route, "bind_research_radial_option", side_effect=lambda frame: control(frame, 2, "research-lab-radial-research")),
            patch.object(bio_route, "bind_free_research", side_effect=lambda frame: control(
                frame, 0, "bioenhancer-free-research")) as free,
            patch.object(bio_route, "_ocr_tokens", return_value=[]),
        ):
            with DevelopmentSession(owner="bio-cooldown-test", invocation_id="bio-cooldown-test", session_directory=root / "outer", max_inputs=8) as session:
                result = bio_route.run(session=session, runtime=runtime, session_directory=runtime.session, settle_seconds=0)
                inputs = session.input_count
        return result, inputs, runtime.taps, normalize.call_count, free.call_count

    def test_ready_startup_returns_home_once_before_normal_navigation_without_consuming(self):
        with tempfile.TemporaryDirectory() as directory:
            result, inputs, taps, normalized, _ = self._route_case(
                Path(directory), already_open=False, ready_startup=True)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["no_work"])
        self.assertEqual(result["startup_return_home"]["status"], "home_returned")
        self.assertEqual(result["startup_return_home"]["input_count"], 1)
        self.assertEqual(inputs, 4)
        self.assertEqual(normalized, 1)
        self.assertEqual(taps, ["bioenhancer-in-game-back", bio_route.RESEARCH_LAB_ID,
            "research-lab-radial-research", "bioenhancer-in-game-back"])

    def test_already_open_and_home_full_repeat_return_home_without_research(self):
        for already_open in (True, False):
            with self.subTest(already_open=already_open), tempfile.TemporaryDirectory() as directory:
                result, inputs, taps, normalized, free_checks = self._route_case(Path(directory), already_open=already_open)
            self.assertEqual(result["status"], "completed")
            self.assertTrue(result["no_work"])
            self.assertTrue(result["terminal_home_verified"])
            self.assertEqual(inputs, 1 if already_open else 3)
            self.assertEqual(normalized, 0 if already_open else 1)
            self.assertEqual(taps[-1], "bioenhancer-in-game-back")
            self.assertNotIn("bioenhancer-free-research", taps)

    def test_no_work_verifier_replays_cooldown_and_home_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            (session / "frames").mkdir()
            records = {}
            for label, marker in (("cooldown", 3), ("home", 4)):
                raw = cv2.imencode(".png", np.full((1280, 800, 3), marker, np.uint8))[1].tobytes()
                (session / "frames" / f"{label}.png").write_bytes(raw)
                records[label] = {"frame_path": f"frames/{label}.png", "frame_sha256": hashlib.sha256(raw).hexdigest()}
            cooldown = {**bio_route.parse_free_research_cooldown("Free in 16:57:15", now=self.NOW), **records["cooldown"]}
            (session / "events.jsonl").write_text(json.dumps({"type": "dispatch", "execute": True, "action_key": "bioenhancer-return-home:1"}) + "\n")
            payload = delivery._result_payload({"status": "completed", "no_work": True, "cooldown": cooldown, "terminal_home_verified": True, "terminal_home_frame": records["home"]}, session_directory=session, input_count=1, free_calls=0, maximum=8)
            initial = {"frame_path": records["cooldown"]["frame_path"], "frame_sha256": records["cooldown"]["frame_sha256"], "invocation_id": "bio-cooldown"}
            payload.update(initial_observation=initial, initial_frame_sha256=initial["frame_sha256"], proof_topology="continuous", causal_trace_count=1)
            payload["causal_trace"] = delivery._write_read_only_causal_trace(session, flow_result=payload, initial_observation=initial)
            delivery._write_delivery_result(session, payload, lease={"owner": "test"}, maximum=8)
            retained = json.loads((session / "flow-delivery-result.json").read_text())
            with (
                patch.object(bio_route, "recognize_free_research_cooldown", side_effect=lambda frame, **_kwargs: cooldown if int(frame[0, 0, 0]) == 3 else None),
                patch("scripts.startup_normalization.is_clean_home_frame", side_effect=lambda frame: int(frame[0, 0, 0]) == 4),
            ):
                verdict = verify_bioenhancer_free_research({"result": retained, "session_directory": str(session)}, {}, {})
                self.assertEqual(verdict["status"], "verified")
                self.assertEqual(verdict["free_research_transport_calls"], 0)
                self.assertTrue(verdict["no_work_proof_verified"])
                retained["cooldown"]["frame_sha256"] = "0" * 64
                verdict = verify_bioenhancer_free_research({"result": retained, "session_directory": str(session)}, {}, {})
                self.assertEqual(verdict["status"], "evidence_required")
                retained["cooldown"]["frame_sha256"] = records["cooldown"]["frame_sha256"]
                wrong_home = cv2.imencode(".png", np.full((1280, 800, 3), 3, np.uint8))[1].tobytes()
                (session / "frames" / "home.png").write_bytes(wrong_home)
                retained["terminal_home_frame"]["frame_sha256"] = hashlib.sha256(wrong_home).hexdigest()
                verdict = verify_bioenhancer_free_research({"result": retained, "session_directory": str(session)}, {}, {})
                self.assertEqual(verdict["status"], "evidence_required")

    def test_no_work_cannot_relabel_a_research_dispatch_or_unproved_home(self):
        base = {"status": "completed", "no_work": True, "cooldown": bio_route.parse_free_research_cooldown("Free in 16:57:15", now=self.NOW), "terminal_home_verified": True, "terminal_home_frame": {}, "semantic_postcondition": {"proven": True, "timer_proven": True}}
        result = delivery._result_payload(base, session_directory="test", input_count=2, free_calls=1, maximum=8)
        self.assertEqual(result["status"], "effect_reconciliation_required")
        base["terminal_home_verified"] = False
        result = delivery._result_payload(base, session_directory="test", input_count=1, free_calls=0, maximum=8)
        self.assertEqual(result["status"], "blocked")

    def test_no_work_requires_the_returned_home_frame_proof_without_recapture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = SimpleNamespace(path=root / "cooldown.png", sha256="1" * 64)
            session = SimpleNamespace(input_count=1, terminal_status=None)
            with (
                patch.object(bio_route, "_return_to_home", return_value={"status": "home_returned"}),
                patch.object(bio_route, "is_clean_home_frame") as recognize,
            ):
                def capture(_label):
                    self.fail("verified return must not trigger another capture")
                result = bio_route._complete_cooldown_no_work(
                    {}, bio_route.parse_free_research_cooldown("Free in 16:57:15", now=self.NOW), source,
                    session=session, runtime=object(), capture=capture,
                    session_directory=root, settle_seconds=0,
                )
            recognize.assert_not_called()
            self.assertEqual(result["status"], "evidence_required")
            self.assertFalse(result["terminal_home_verified"])


class BioenhancerVisibleExitTests(unittest.TestCase):
    @requires_tesseract
    def test_back_binding_requires_exact_title_arrow_and_no_modal(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        frame[15:50, 20:75] = 220
        title = [{"text_cf": "bioenhancer"}]
        with (
            patch.object(bio_route, "_ocr_tokens", return_value=title) as ocr,
            patch.object(bio_route, "_generic_modal_overlay_evidence", return_value={"recognized": False}) as modal,
        ):
            control = bio_route.bind_bioenhancer_back(frame)
            self.assertIsNotNone(control)
            self.assertEqual(control.identity, "bioenhancer-in-game-back")
            variant = frame.copy()
            variant[300:900, 200:600] = 130
            self.assertEqual(bio_route.bind_bioenhancer_back(variant).target_roi, control.target_roi)
            missing_arrow = variant.copy()
            missing_arrow[:90, :140] = 0
            self.assertIsNone(bio_route.bind_bioenhancer_back(missing_arrow))
            ocr.return_value = [{"text_cf": "research"}]
            self.assertIsNone(bio_route.bind_bioenhancer_back(frame))
            ocr.return_value = title
            modal.return_value = {"recognized": True}
            self.assertIsNone(bio_route.bind_bioenhancer_back(frame))
        self.assertIsNone(bio_route.bind_bioenhancer_back(frame[:640]))

    def _return_case(self, root, *, bind=True, home_marker=3, changed_source=False):
        class ExitRuntime(_PanRuntime):
            def __init__(self):
                super().__init__(root / "session" / "runtime")
                self.taps = []

            def tap(self, captured, **kwargs):
                self.taps.append((int(captured.frame[0, 0, 0]), kwargs))

            def back(self, *_args, **_kwargs):
                raise AssertionError("Bioenhancer must never use Android Back")

        runtime = ExitRuntime()
        control = bio_route.BoundControl("bioenhancer-in-game-back", (10, 5, 90, 60), (), .9)

        def binding(frame):
            return control if bind and not (changed_source and int(frame[0, 0, 0]) == 2) else None

        with (
            patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"),
            patch.object(bio_route, "bind_bioenhancer_back", side_effect=binding),
            patch.object(bio_route, "is_clean_home_frame", side_effect=lambda frame: int(frame[0, 0, 0]) == home_marker),
        ):
            with DevelopmentSession(
                owner="bio-exit-test", invocation_id="bio-exit-test",
                session_directory=root / "session", max_inputs=2,
            ) as session:
                try:
                    result = bio_route._return_to_home(
                        session=session, runtime=runtime, capture=runtime.capture,
                        session_directory=root / "session", settle_seconds=0,
                    )
                    error = None
                except RuntimeError as exc:
                    result, error = None, exc
                count = session.input_count
        return result, error, count, runtime.taps

    def test_visible_exit_uses_fresh_frame_and_verifies_home(self):
        with tempfile.TemporaryDirectory() as directory:
            result, error, count, taps = self._return_case(Path(directory))
        self.assertIsNone(error)
        self.assertEqual(result["status"], "home_returned")
        self.assertEqual(result["input_count"], 1)
        self.assertEqual(count, 1)
        self.assertEqual(taps[0][0], 2)
        self.assertEqual(taps[0][1]["target_identity"], "bioenhancer-in-game-back")
        self.assertEqual(result["terminal_home_frame"]["frame_sha256"], result["attempts"][-1]["frame_sha256"])

    def test_settled_home_proof_is_the_frame_already_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            result, error, count, taps = self._return_case(Path(directory), home_marker=4)
        self.assertIsNone(error)
        self.assertEqual(result["status"], "home_returned")
        self.assertEqual(count, 1)
        self.assertEqual(len(taps), 1)
        self.assertEqual(result["terminal_home_frame"]["frame_sha256"], result["attempts"][-1]["frame_sha256"])
        self.assertTrue(result["terminal_home_frame"]["frame_path"].endswith("return-home-settled.png"))

    def test_unknown_source_and_lost_binding_dispatch_nothing(self):
        for changed_source in (False, True):
            with self.subTest(changed_source=changed_source), tempfile.TemporaryDirectory() as directory:
                result, error, count, taps = self._return_case(
                    Path(directory), bind=changed_source, changed_source=changed_source,
                )
            self.assertEqual(count, 0)
            self.assertEqual(taps, [])
            if changed_source:
                self.assertIsInstance(error, RuntimeError)
            else:
                self.assertEqual(result["status"], "home_return_not_proven")

    def test_unknown_successor_never_retries_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            result, error, count, taps = self._return_case(Path(directory), home_marker=99)
        self.assertIsNone(error)
        self.assertEqual(result["status"], "home_return_not_proven")
        self.assertEqual(count, 1)
        self.assertEqual(len(taps), 1)

    def test_already_home_requires_no_exit_input(self):
        with tempfile.TemporaryDirectory() as directory:
            result, error, count, taps = self._return_case(Path(directory), home_marker=1)
        self.assertIsNone(error)
        self.assertEqual(result["status"], "home_returned")
        self.assertEqual(count, 0)
        self.assertEqual(taps, [])
        self.assertTrue(result["terminal_home_frame"]["frame_path"].endswith("bioenhancer-return-home-source.png"))


if __name__ == "__main__":
    unittest.main()
