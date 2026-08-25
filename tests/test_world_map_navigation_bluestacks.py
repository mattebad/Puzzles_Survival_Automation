from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.flow_delivery_world_map_bluestacks import (
    FLOW_ID,
    RUNNER_ID,
    RECOVERY_ID,
    VALIDATOR_ID,
    _run_result,
    _verify_registration_evidence,
    _write_read_only_causal_trace,
    _verify_event_order,
    _verify_route_semantics,
    run_world_map_navigation_foundation,
    verify_world_map_navigation_foundation,
)
from scripts import pnsctl
from scripts import navigation_development_boundary as boundary
from scripts.navigation_development_boundary import (
    DevelopmentInitialObservation,
    DevelopmentSession,
)
from scripts import world_map_navigation_bluestacks as navigation
from scripts.world_map_navigation_bluestacks import (
    ALLOWED_CONTROL_IDENTITIES,
    ANDROID_BACK,
    BLOCKED_FAIL_CLOSED,
    HOME_TO_WORLD,
    HOME_CANONICAL,
    HOME_READY,
    NAVIGATION_ONLY_COMPLETE,
    POPUP_CLOSE,
    RECOVERY_PATH,
    SafePopupHandler,
    SEARCH_ENTRY_ONLY_PATH,
    WorldNavigationBlocked,
    WORLD_READY,
    WORLD_SEARCH_ENTRY,
    WORLD_SEARCH_OPEN,
    WORLD_TO_HOME,
    _group_spatial_ocr_hits,
    _coordinate_hud_evidence,
    _world_search_menu_evidence,
    _visual_search_entry_binding,
    recover_world_map_home,
    recognize_allowlisted_popup,
    recognize_world_frame,
    recognize_world_home_recovery,
    route_declaration,
    run_world_map_navigation,
    run_world_map_search_entry_only,
)
from tasks.world_stamina import (
    WORLD_ZOOM_SUPPORTED,
    WorldNavigationObservation,
    plan_bounded_world_pan,
    world_navigation_observation_authorizeable,
    world_navigation_observation_from_mapping,
    world_node_binding_authorizeable,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "world_map_navigation_observations.json"
PROFILE = "pns-bluestacks-5-p64-800x1280-v1"


def observation(
    state: str,
    *,
    controls: dict[str, tuple[int, int, int, int]] | None = None,
    zoom: str = WORLD_ZOOM_SUPPORTED,
    recognized: bool = True,
    unknown_modal: bool = False,
    popup: dict | None = None,
    node_identity: str | None = None,
    node_roi: tuple[int, int, int, int] | None = None,
    node_source: str | None = None,
) -> dict:
    control_semantics = {
        identity: (
            ["World map"]
            if identity == "home-to-world"
            else ["Search"]
            if identity == "world-search-entry"
            else ["Close"]
            if identity == "world-search-close"
            else ["Home"]
        )
        for identity in (controls or {})
    }
    payload = {
        "state": state,
        "recognized": recognized,
        "unknown_modal": unknown_modal,
        "overlay_state": "unknown" if unknown_modal else "none_observed",
        "zoom_identity": zoom,
        "runtime_profile_id": PROFILE,
        "frame_width": 800,
        "frame_height": 1280,
        "controls": controls or {},
        "semantic_evidence": [
            "Home" if state in {HOME_READY, HOME_CANONICAL} else state,
            "Canonical Home" if state == HOME_CANONICAL else state,
        ],
        "control_semantics": control_semantics,
        "control_geometry_source": {
            identity: "current-frame-bounded-candidate" for identity in (controls or {})
        },
    }
    if state in {"WORLD_READY", "WORLD_SEARCH_OPEN"}:
        payload["zoom_evidence"] = ["supported-world-zoom-visual-landmarks"]
        payload["localization_evidence"] = ["current-frame-world-localization"]
    if popup is not None:
        payload["popup"] = popup
    if node_identity is not None:
        payload["node_identity"] = node_identity
    if node_roi is not None:
        payload["node_roi"] = node_roi
    if node_source is not None:
        payload["node_source_frame_sha256"] = node_source
    return payload


class FakeRuntime:
    execute = True

    def __init__(self, frames: list[dict]) -> None:
        self.frames = list(frames)
        self.ordinal = 0
        self.session = Path("synthetic-world-session")
        self.calls: list[tuple[str, dict]] = []
        self.reconciliations: list[tuple[str, str]] = []

    def capture(self, label: str) -> CapturedNativeFrame:
        if not self.frames:
            raise AssertionError(f"unexpected capture: {label}")
        self.ordinal += 1
        frame = self.frames.pop(0)
        payload = f"synthetic-png-{self.ordinal}".encode()
        return CapturedNativeFrame(
            frame,
            payload,
            f"{self.ordinal:064x}"[-64:],
            float(self.ordinal),
            self.session / f"{self.ordinal:04d}-{label}.png",
        )

    def tap(self, source, **kwargs) -> None:
        self.calls.append(("tap", kwargs))

    def back(self, source, **kwargs) -> None:
        self.calls.append(("back", kwargs))

    def reconcile(self, action_key, status, post, reason) -> None:
        self.reconciliations.append((action_key, status))


def scripted_recognizer(frame, **_kwargs):
    if not isinstance(frame, dict):
        raise AssertionError("scripted recognizer received an unexpected frame")
    if frame.get("popup"):
        obscured = dict(frame)
        obscured.update(
            state="UNKNOWN",
            recognized=False,
            unknown_modal=True,
            overlay_state="unknown",
            controls={},
            control_semantics={},
            control_geometry_source={},
        )
        return obscured
    return frame


def route_frames(*, popup_at_start: bool = False) -> list[dict]:
    home = observation(
        HOME_READY,
        controls={"home-to-world": (100, 100, 220, 160)},
    )
    if popup_at_start:
        home["popup"] = {
            "popup_identity": "VIP_POINTS_GET_PTS",
            "title_identity": True,
            "body_identity": True,
            "close_identity": POPUP_CLOSE,
            "literal_close": True,
            "target_roi": (260, 768, 540, 842),
            "panel_roi": (80, 300, 720, 940),
            "target_geometry_source": "current-frame-bounded-candidate",
            "context_state": HOME_READY,
            "semantic_evidence": [
                "Get Pts",
                "Log in every day to get VIP pts",
                "Close",
            ],
        }
    frames = [home]
    if popup_at_start:
        frames.append(
            observation(
                HOME_READY,
                controls={"home-to-world": (100, 100, 220, 160)},
            )
        )
    frames.extend(
        [
            observation(
                "WORLD_READY",
                controls={
                    "world-search-entry": (600, 100, 760, 170),
                    "world-to-home": (20, 25, 110, 100),
                },
            ),
            observation(
                "WORLD_READY",
                controls={
                    "world-search-entry": (600, 100, 760, 170),
                    "world-to-home": (20, 25, 110, 100),
                },
            ),
            observation(
                "WORLD_SEARCH_OPEN",
                controls={"world-search-close": (660, 30, 760, 100)},
            ),
            observation(
                "WORLD_SEARCH_OPEN",
                controls={"world-search-close": (660, 30, 760, 100)},
            ),
            observation(
                "WORLD_READY",
                controls={
                    "world-search-entry": (600, 100, 760, 170),
                    "world-to-home": (20, 25, 110, 100),
                },
            ),
            observation(
                "WORLD_READY",
                controls={
                    "world-search-entry": (600, 100, 760, 170),
                    "world-to-home": (20, 25, 110, 100),
                },
            ),
            observation(HOME_READY),
        ]
    )
    return frames


def hud_validator_events() -> tuple[list[dict], dict, set[str]]:
    steps = (
        ("home-to-world", "HOME_READY", "WORLD_READY"),
        ("world-search-entry", "WORLD_READY", "WORLD_SEARCH_OPEN"),
        ("android-back", "WORLD_SEARCH_OPEN", "WORLD_READY"),
        ("world-to-home", "WORLD_READY", "HOME_READY"),
    )
    events: list[dict] = []
    hashes: set[str] = set()
    transitions: list[dict] = []
    for ordinal, (target, source_state, successor_state) in enumerate(steps, 1):
        source = f"{ordinal:x}" * 64
        post = f"{ordinal + 4:x}" * 64
        action = f"action-{ordinal}"
        source_path = f"/session/frames/{ordinal:04d}-source.png"
        post_path = f"/session/frames/{ordinal + 4:04d}-post.png"
        hashes.update((source, post))
        events.extend(
            [
                {
                    "type": "capture",
                    "sha256": source,
                    "path": source_path,
                },
                {
                    "type": "semantic",
                    "event": "navigation_planned",
                    "action_key": action,
                    "target_identity": target,
                    "source_frame_sha256": source,
                    "target_roi": None
                    if target == "android-back"
                    else (10, 10, 50, 50),
                    "capture_session": "/session",
                    "capture_ordinal": f"{ordinal:04d}",
                    "capture_frame_sha256": source,
                },
                {
                    "type": "semantic",
                    "event": "navigation_prepared",
                    "action_key": action,
                    "target_identity": target,
                    "source_state": source_state,
                    "source_frame_sha256": source,
                    "target_roi": None
                    if target == "android-back"
                    else (10, 10, 50, 50),
                    "expected_successor_state": successor_state,
                    "capture_session": "/session",
                    "capture_ordinal": f"{ordinal:04d}",
                    "capture_frame_sha256": source,
                },
                {
                    "type": "dispatch",
                    "action_key": action,
                    "target_identity": target,
                    **(
                        {"target_roi": (10, 10, 50, 50)}
                        if target != "android-back"
                        else {}
                    ),
                    "source_sha256": source,
                    "consequential": False,
                },
                {
                    "type": "capture",
                    "sha256": post,
                    "path": post_path,
                },
                {
                    "type": "reconcile",
                    "action_key": action,
                    "status": "confirmed",
                    "post_sha256": post,
                },
                {
                    "type": "semantic",
                    "event": "navigation_reconciled",
                    "action_key": action,
                    "target_identity": target,
                    "source_state": source_state,
                    "source_frame_sha256": source,
                    "immediate_post_frame_sha256": post,
                    "successor_frame_sha256": post,
                    "expected_successor_state": successor_state,
                    "successor_state": successor_state,
                    "successor_overlay_state": "none_observed",
                },
            ]
        )
        transitions.append(
            {
                "event": "navigation_reconciled",
                "target_identity": target,
                "source_state": source_state,
                "expected_successor_state": successor_state,
                "successor_state": successor_state,
                "successor_overlay_state": "none_observed",
                "source_frame_sha256": source,
                "successor_frame_sha256": post,
            }
        )
    events.append(
        {
            "type": "semantic",
            "event": "route_terminal",
            "state": "HOME_READY",
            "overlay_state": "none_observed",
            "frame_sha256": "8" * 64,
        }
    )
    hashes.add("8" * 64)
    route = {
        "flow_id": "WORLD-MAP-NAVIGATION-FOUNDATION",
        "status": NAVIGATION_ONLY_COMPLETE,
        "input_count": 4,
        "max_inputs": 4,
        "navigation_input_count": 4,
        "safe_popup_input_count": 0,
        "resource_actions": 0,
        "combat_actions": 0,
        "node_inputs": 0,
        "resource_node_selection_inputs": 0,
        "march_inputs": 0,
        "formation_inputs": 0,
        "occupancy_override_inputs": 0,
        "stamina_inputs": 0,
        "ap_inputs": 0,
        "currency_inputs": 0,
        "forbidden_input_classes": [],
        "final_frame_sha256": "8" * 64,
        "final_state": HOME_READY,
        "final_overlay_state": "none_observed",
        "terminal_runtime_state": HOME_READY,
        "reason": "verified_hud_home_round_trip",
    }
    return events, route, hashes


def recovery_validator_events(
    *,
    menu_open: bool,
) -> tuple[list[dict], dict, set[str]]:
    events, route, hashes = hud_validator_events()
    action_keys = {"action-3", "action-4"} if menu_open else {"action-4"}
    retained_hashes = (
        {"3" * 64, "4" * 64, "7" * 64, "8" * 64} if menu_open else {"4" * 64, "8" * 64}
    )
    filtered = [
        event
        for event in events
        if event.get("action_key") in action_keys
        or event.get("event") == "route_terminal"
        or (event.get("type") == "capture" and event.get("sha256") in retained_hashes)
    ]
    input_count = 2 if menu_open else 1
    recovery_route = dict(
        route,
        path=RECOVERY_PATH,
        input_count=input_count,
        max_inputs=input_count,
        navigation_input_count=input_count,
        reason="verified_world_to_home_recovery",
    )
    return filtered, recovery_route, hashes


class WorldMapNavigationTests(unittest.TestCase):
    def test_post_consumption_verifier_accepts_only_fixed_dispatch_snapshot(self):
        snapshot = {
            "flow_id": FLOW_ID,
            "product_id": "world_map_navigation",
            "product_revision": "world_map_navigation-v1",
            "production_handler": "world_map_navigation_foundation_selection_handler",
            "profile": PROFILE,
            "mode": "phase_canary",
            "registration_status": "REGISTERED",
            "scheduler_eligible": True,
        }
        result = {
            "production_registration": "REGISTERED",
            "registration_snapshot": snapshot,
            "dispatch_registration": snapshot,
        }
        trace = {
            "registration_snapshot": snapshot,
            "dispatch_registration": snapshot,
        }
        _verify_registration_evidence(result, trace)

        forged = dict(snapshot, profile="untrusted-profile")
        with self.assertRaises(pnsctl.OperatorError):
            _verify_registration_evidence(
                dict(result, registration_snapshot=forged),
                trace,
            )

    def test_atomic_world_canary_claim_rejects_before_observation_and_runner(self):
        runner = unittest.mock.Mock()
        with (
            patch(
                "automation_service.registry.consume_world_registration",
                return_value=None,
            ) as consume,
            patch.object(pnsctl, "_development_runtime_observation") as observation,
            patch.dict(pnsctl._BLUESTACKS_FLOW_RUNNERS, {RUNNER_ID: runner}),
        ):
            with self.assertRaisesRegex(
                pnsctl.OperatorError,
                "not registered for a phase canary",
            ):
                pnsctl.development_session_run_flow(
                    FLOW_ID,
                    live=True,
                    yes=True,
                    max_inputs=20,
                )

        consume.assert_called_once_with()
        observation.assert_not_called()
        runner.assert_not_called()

    def test_search_entry_delivery_and_trace_are_diagnostic_non_accepting(self):
        route = {
            "path": SEARCH_ENTRY_ONLY_PATH,
            "status": NAVIGATION_ONLY_COMPLETE,
            "input_count": 1,
            "navigation_input_count": 1,
            "safe_popup_input_count": 0,
        }
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            (session / "frames").mkdir()
            (session / "events.jsonl").write_text(
                json.dumps({"type": "dispatch", "execute": True}) + "\n",
                encoding="utf-8",
            )
            trace = _write_read_only_causal_trace(
                session,
                route=route,
                initial_observation={"invocation_id": "test", "frame_sha256": "a" * 64},
            )
            with patch(
                "scripts.flow_delivery_world_map_bluestacks._native_frames",
                return_value=["frames/0000.png"],
            ):
                delivery = _run_result(
                    route,
                    session=session,
                    lease={"owner": "test-owner"},
                    operator_returncode=0,
                    initial_observation={"frame_sha256": "a" * 64},
                    causal_trace=trace,
                )
            self.assertEqual(trace["proof_topology"], "diagnostic")
            self.assertFalse(trace["acceptance_eligible"])
            self.assertEqual(delivery["proof_topology"], "diagnostic")
            self.assertFalse(delivery["acceptance_eligible"])

    def test_search_entry_verifier_returns_diagnostic_verified(self):
        events, base_route, hashes = hud_validator_events()
        search_events = [
            event
            for event in events
            if event.get("action_key") == "action-2"
            or (
                event.get("type") == "capture"
                and event.get("sha256") in {"2" * 64, "6" * 64, "8" * 64}
            )
            or event.get("event") == "route_terminal"
        ]
        search_events[-1] = dict(
            search_events[-1],
            state=WORLD_SEARCH_OPEN,
            frame_sha256="8" * 64,
        )
        route = dict(
            base_route,
            path=SEARCH_ENTRY_ONLY_PATH,
            input_count=1,
            max_inputs=1,
            navigation_input_count=1,
            final_state=WORLD_SEARCH_OPEN,
            terminal_runtime_state=WORLD_SEARCH_OPEN,
            reason="verified_world_ready_to_search_open",
        )
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            (session / "frames").mkdir()
            for ordinal in (2, 6, 8):
                (session / "frames" / f"{ordinal:04d}.png").write_bytes(b"frame")
            (session / "events.jsonl").write_text(
                "".join(json.dumps(event) + "\n" for event in search_events),
                encoding="utf-8",
            )
            result = {
                "schema_version": 1,
                "flow_id": FLOW_ID,
                "status": "completed",
                "serial": pnsctl.BLUESTACKS_SERIAL,
                "native_width": 800,
                "native_height": 1280,
                "dispatch_count": 1,
                "input_count": 1,
                "navigation_input_count": 1,
                "safe_popup_input_count": 0,
                "resource_actions": 0,
                "combat_actions": 0,
                "node_inputs": 0,
                "resource_node_selection_inputs": 0,
                "march_inputs": 0,
                "formation_inputs": 0,
                "occupancy_override_inputs": 0,
                "stamina_inputs": 0,
                "ap_inputs": 0,
                "currency_inputs": 0,
                "forbidden_input_classes": [],
                "frames": [
                    "frames/0002.png",
                    "frames/0006.png",
                    "frames/0008.png",
                ],
                "events_path": "events.jsonl",
                "world_navigation_result": route,
                "terminal_runtime_state": WORLD_SEARCH_OPEN,
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
                "proof_topology": "diagnostic",
                "acceptance_eligible": False,
                "causal_trace": {
                    "proof_topology": "diagnostic",
                    "acceptance_eligible": False,
                },
            }
            (session / "flow-delivery-result.json").write_text(
                json.dumps(result), encoding="utf-8"
            )
            frame_hashes = {
                "0002.png": "2" * 64,
                "0006.png": "6" * 64,
                "0008.png": "8" * 64,
            }
            with patch(
                "scripts.flow_delivery_world_map_bluestacks._hash_native",
                side_effect=lambda path: frame_hashes[path.name],
            ):
                verdict = verify_world_map_navigation_foundation(
                    {"result": result, "session_directory": str(session)},
                    {},
                    {},
                )
        self.assertEqual(verdict["status"], "diagnostic_verified")
        self.assertFalse(verdict["acceptance_eligible"])

    def test_continuous_verifier_rejects_contradictory_acceptance_metadata(self):
        events, base_route, hashes = hud_validator_events()
        route = dict(base_route, home_recovery_latency_seconds=1.0)
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            (session / "frames").mkdir()
            frame_refs = []
            frame_hashes = {}
            for ordinal, digest in enumerate(sorted(hashes), start=1):
                filename = f"{ordinal:04d}.png"
                (session / "frames" / filename).write_bytes(b"frame")
                frame_refs.append(f"frames/{filename}")
                frame_hashes[filename] = digest
            (session / "events.jsonl").write_text(
                "".join(json.dumps(event) + "\n" for event in events),
                encoding="utf-8",
            )

            base_result = {
                "schema_version": 1,
                "flow_id": FLOW_ID,
                "status": "completed",
                "serial": pnsctl.BLUESTACKS_SERIAL,
                "native_width": 800,
                "native_height": 1280,
                "dispatch_count": 4,
                "input_count": 4,
                "navigation_input_count": 4,
                "safe_popup_input_count": 0,
                "resource_actions": 0,
                "combat_actions": 0,
                "node_inputs": 0,
                "resource_node_selection_inputs": 0,
                "march_inputs": 0,
                "formation_inputs": 0,
                "occupancy_override_inputs": 0,
                "stamina_inputs": 0,
                "ap_inputs": 0,
                "currency_inputs": 0,
                "forbidden_input_classes": [],
                "frames": frame_refs,
                "events_path": "events.jsonl",
                "world_navigation_result": route,
                "terminal_runtime_state": HOME_READY,
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
                "proof_topology": "continuous",
                "causal_trace": {"proof_topology": "continuous"},
            }

            def verify_result(result):
                (session / "flow-delivery-result.json").write_text(
                    json.dumps(result), encoding="utf-8"
                )
                with patch(
                    "scripts.flow_delivery_world_map_bluestacks._hash_native",
                    side_effect=lambda path: frame_hashes[path.name],
                ):
                    return verify_world_map_navigation_foundation(
                        {"result": result, "session_directory": str(session)},
                        {},
                        {},
                    )

            self.assertEqual(verify_result(dict(base_result))["status"], "verified")
            result_contradiction = dict(base_result, acceptance_eligible=False)
            with self.assertRaises(pnsctl.OperatorError):
                verify_result(result_contradiction)
            trace_contradiction = dict(base_result)
            trace_contradiction["causal_trace"] = {
                "proof_topology": "continuous",
                "acceptance_eligible": False,
            }
            with self.assertRaises(pnsctl.OperatorError):
                verify_result(trace_contradiction)
            route_contradiction = dict(base_result)
            route_contradiction["world_navigation_result"] = dict(
                route,
                proof_topology="diagnostic",
            )
            with self.assertRaises(pnsctl.OperatorError):
                verify_result(route_contradiction)

    def test_live_admission_rejects_unbound_or_fabricated_sessions_before_connect(self):
        fabricated = type(
            "FabricatedSession",
            (),
            {
                "owner": "pnsctl-development-session:fake",
                "is_active": True,
                "run_action": lambda self, **kwargs: None,
            },
        )()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(pnsctl, "BLUESTACKS_ARTIFACT_ROOT", root / "artifacts"):
                with patch(
                    "scripts.flow_delivery_world_map_bluestacks.LocalBlueStacksRuntime.connect"
                ) as connect:
                    for label, lease in (
                        ("missing", {}),
                        ("fabricated", {"development_session": fabricated}),
                        (
                            "inactive",
                            {
                                "development_session": DevelopmentSession(
                                    owner="pnsctl-development-session:inactive",
                                    invocation_id="inactive",
                                    session_directory=root / "inactive",
                                    max_inputs=12,
                                )
                            },
                        ),
                    ):
                        with (
                            self.subTest(label=label),
                            self.assertRaises(pnsctl.OperatorError),
                        ):
                            with patch.object(
                                pnsctl,
                                "BLUESTACKS_ARTIFACT_ROOT",
                                root / f"artifacts-{label}",
                            ):
                                run_world_map_navigation_foundation(
                                    {}, {**lease, "max_inputs": 12}, live=True
                                )
                    connect.assert_not_called()

            with patch.object(
                boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"
            ):
                with DevelopmentSession(
                    owner=f"pnsctl-development-session:{FLOW_ID}",
                    invocation_id="bound",
                    session_directory=root / "bound",
                    max_inputs=12,
                ) as session:
                    digest = hashlib.sha256(b"initial").hexdigest()
                    bound = DevelopmentInitialObservation(
                        {"frame_sha256": digest},
                        digest,
                        invocation_id=session.invocation_id,
                    )
                    session.set_initial_observation(bound)
                    base = {
                        "development_session": session,
                        "initial_frame_sha256": digest,
                        "max_inputs": 12,
                    }
                    for label, observation_value in (
                        ("missing-observation", None),
                        (
                            "mismatched-observation",
                            DevelopmentInitialObservation(
                                {"frame_sha256": digest},
                                digest,
                                invocation_id=session.invocation_id,
                            ),
                        ),
                    ):
                        with self.subTest(label=label):
                            lease = dict(base)
                            if observation_value is not None:
                                lease["initial_observation"] = observation_value
                            with patch(
                                "scripts.flow_delivery_world_map_bluestacks.LocalBlueStacksRuntime.connect"
                            ) as connect:
                                with patch.object(
                                    pnsctl,
                                    "BLUESTACKS_ARTIFACT_ROOT",
                                    root / f"artifacts-{label}",
                                ):
                                    with self.assertRaises(pnsctl.OperatorError):
                                        run_world_map_navigation_foundation(
                                            {}, lease, live=True
                                        )
                            connect.assert_not_called()

    def test_search_entry_only_taps_search_once_and_stops_open(self):
        runtime = FakeRuntime(
            [
                observation(
                    WORLD_READY,
                    controls={"world-search-entry": (600, 100, 760, 170)},
                ),
                observation(
                    WORLD_SEARCH_OPEN,
                    controls={"world-search-close": (660, 30, 760, 100)},
                ),
            ]
        )
        result = run_world_map_search_entry_only(
            runtime,
            maximum_inputs=1,
            recognizer=scripted_recognizer,
        )
        self.assertEqual(result["status"], NAVIGATION_ONLY_COMPLETE)
        self.assertEqual(result["path"], SEARCH_ENTRY_ONLY_PATH)
        self.assertEqual(result["navigation_input_count"], 1)
        self.assertEqual(result["safe_popup_input_count"], 0)
        self.assertEqual(result["input_count"], 1)
        self.assertEqual(result["max_inputs"], 1)
        self.assertEqual(result["terminal_runtime_state"], WORLD_SEARCH_OPEN)
        self.assertEqual(result["final_state"], WORLD_SEARCH_OPEN)
        self.assertEqual(
            [call[1]["target_identity"] for call in runtime.calls],
            [WORLD_SEARCH_ENTRY],
        )
        self.assertEqual([call[0] for call in runtime.calls], ["tap"])
        self.assertEqual(
            [event["target_identity"] for event in result["route_transitions"]],
            [WORLD_SEARCH_ENTRY],
        )

    def test_search_entry_only_disables_popup_inputs(self):
        runtime = FakeRuntime(
            [
                observation(
                    WORLD_READY,
                    controls={"world-search-entry": (600, 100, 760, 170)},
                    popup={"popup_identity": "VIP_POINTS_GET_PTS"},
                )
            ]
        )
        result = run_world_map_search_entry_only(
            runtime,
            maximum_inputs=1,
            recognizer=scripted_recognizer,
        )
        self.assertEqual(result["status"], BLOCKED_FAIL_CLOSED)
        self.assertEqual(result["navigation_input_count"], 0)
        self.assertEqual(result["safe_popup_input_count"], 0)
        self.assertEqual(result["input_count"], 0)
        self.assertEqual(runtime.calls, [])

    def test_search_entry_only_cli_propagates_and_is_mutually_exclusive(self):
        parsed = pnsctl.parser().parse_args(
            [
                "development-session",
                "run-flow",
                "WORLD-MAP-NAVIGATION-FOUNDATION",
                "--search-entry-only",
            ]
        )
        self.assertTrue(parsed.search_entry_only)
        self.assertFalse(parsed.recovery_only)
        with patch.object(
            pnsctl,
            "development_session_run_flow",
            return_value="{}",
        ) as run_flow:
            self.assertEqual(
                pnsctl.main(
                    [
                        "development-session",
                        "run-flow",
                        "WORLD-MAP-NAVIGATION-FOUNDATION",
                        "--search-entry-only",
                    ]
                ),
                0,
            )
        self.assertTrue(run_flow.call_args.kwargs["search_entry_only"])
        with self.assertRaises(SystemExit):
            pnsctl.parser().parse_args(
                [
                    "development-session",
                    "run-flow",
                    "WORLD-MAP-NAVIGATION-FOUNDATION",
                    "--search-entry-only",
                    "--recovery-only",
                ]
            )

    def test_hud_home_route_requires_exact_successors_and_counts_inputs(self):
        runtime = FakeRuntime(route_frames())
        result = run_world_map_navigation(
            runtime,
            recognizer=scripted_recognizer,
            maximum_inputs=4,
        )
        self.assertEqual(result["status"], NAVIGATION_ONLY_COMPLETE)
        self.assertEqual(result["navigation_input_count"], 4)
        self.assertEqual(result["safe_popup_input_count"], 0)
        self.assertEqual(result["final_state"], HOME_READY)
        self.assertEqual(route_declaration()["required_start_state"], HOME_READY)
        self.assertEqual(
            result["route_transitions"][0]["source_state"],
            HOME_READY,
        )
        self.assertEqual(
            result["route_transitions"][-1]["successor_state"],
            HOME_READY,
        )
        self.assertEqual(
            [row["target_identity"] for row in result["route_transitions"]],
            ["home-to-world", "world-search-entry", "android-back", "world-to-home"],
        )

    def test_recognized_route_frame_skips_expensive_popup_scan(self):
        runtime = FakeRuntime(route_frames())
        with patch.object(
            SafePopupHandler,
            "handle",
            side_effect=AssertionError("popup scan must be fallback-only"),
        ):
            result = run_world_map_navigation(
                runtime,
                recognizer=scripted_recognizer,
                maximum_inputs=4,
            )
        self.assertEqual(result["status"], NAVIGATION_ONLY_COMPLETE)
        self.assertEqual(result["navigation_input_count"], 4)

    def test_navigation_waits_for_delayed_successor_without_second_tap(self):
        frames = route_frames()
        frames.insert(
            1,
            observation(
                HOME_READY,
                controls={"home-to-world": (100, 100, 220, 160)},
            ),
        )
        runtime = FakeRuntime(frames)
        with patch(
            "scripts.world_map_navigation_bluestacks.time.sleep",
            return_value=None,
        ):
            result = run_world_map_navigation(
                runtime,
                recognizer=scripted_recognizer,
                maximum_inputs=4,
            )
        self.assertEqual(result["status"], NAVIGATION_ONLY_COMPLETE)
        self.assertEqual(result["navigation_input_count"], 4)
        self.assertEqual(len(runtime.calls), 4)
        self.assertEqual(runtime.calls[0][1]["target_identity"], "home-to-world")

    def test_world_recovery_taps_home_once(self):
        runtime = FakeRuntime(
            [
                observation(
                    "WORLD_READY",
                    controls={
                        "world-search-entry": (600, 100, 760, 170),
                        "world-to-home": (20, 25, 110, 100),
                    },
                ),
                observation(HOME_READY),
            ]
        )
        result = recover_world_map_home(
            runtime,
            maximum_inputs=1,
            recognizer=scripted_recognizer,
        )
        self.assertEqual(result["status"], NAVIGATION_ONLY_COMPLETE)
        self.assertEqual(result["navigation_input_count"], 1)
        self.assertEqual(len(runtime.calls), 1)
        self.assertEqual(runtime.calls[0][1]["target_identity"], "world-to-home")
        self.assertEqual(result["final_state"], HOME_READY)

    def test_world_search_recovery_backs_out_then_taps_home(self):
        runtime = FakeRuntime(
            [
                observation(WORLD_SEARCH_OPEN),
                observation(
                    WORLD_READY,
                    controls={"world-to-home": (20, 25, 110, 100)},
                ),
                observation(
                    WORLD_READY,
                    controls={"world-to-home": (20, 25, 110, 100)},
                ),
                observation(HOME_READY),
            ]
        )
        result = recover_world_map_home(
            runtime,
            maximum_inputs=2,
            recognizer=scripted_recognizer,
        )
        self.assertEqual(result["status"], NAVIGATION_ONLY_COMPLETE)
        self.assertEqual(result["path"], RECOVERY_PATH)
        self.assertEqual(result["navigation_input_count"], 2)
        self.assertEqual(result["safe_popup_input_count"], 0)
        self.assertEqual(result["input_count"], 2)
        self.assertEqual(result["terminal_runtime_state"], HOME_READY)
        self.assertEqual(
            [call[0] for call in runtime.calls],
            ["back", "tap"],
        )
        self.assertEqual(
            [call[1].get("target_identity", ANDROID_BACK) for call in runtime.calls],
            [ANDROID_BACK, WORLD_TO_HOME],
        )
        self.assertEqual(
            [item["target_identity"] for item in result["route_transitions"]],
            [ANDROID_BACK, WORLD_TO_HOME],
        )
        self.assertTrue(
            all(
                item["successor_overlay_state"] == "none_observed"
                for item in result["route_transitions"]
            )
        )

    def test_popup_is_handled_at_checkpoint_and_counts_against_total_budget(self):
        runtime = FakeRuntime(route_frames(popup_at_start=True))
        result = run_world_map_navigation(
            runtime,
            recognizer=scripted_recognizer,
            maximum_inputs=5,
            maximum_popup_inputs=1,
        )
        self.assertEqual(result["status"], NAVIGATION_ONLY_COMPLETE)
        self.assertEqual(result["safe_popup_input_count"], 1)
        self.assertEqual(result["navigation_input_count"], 4)
        self.assertEqual(runtime.calls[0][1]["target_identity"], POPUP_CLOSE)

    def test_popup_close_settles_after_transient_immediate_post_without_retry(self):
        popup = {
            "popup_identity": "VIP_POINTS_GET_PTS",
            "title_identity": True,
            "body_identity": True,
            "close_identity": POPUP_CLOSE,
            "literal_close": True,
            "target_roi": (263, 781, 537, 869),
            "panel_roi": (80, 300, 720, 940),
            "target_geometry_source": "current-frame-bounded-candidate",
            "context_state": "WORLD_READY",
            "semantic_evidence": [
                "Get Pts",
                "Log in every day to get VIP pts",
                "Close",
            ],
        }
        runtime = FakeRuntime(
            [
                observation("WORLD_READY", popup=popup),
                observation("WORLD_READY", popup=dict(popup)),
                observation("WORLD_READY"),
            ]
        )
        source = runtime.capture("popup-source")
        handler = SafePopupHandler(maximum_inputs=1)
        events: list[dict] = []
        with patch(
            "scripts.world_map_navigation_bluestacks.time.sleep",
            return_value=None,
        ):
            checkpoint = handler.handle(
                runtime,
                source,
                expected_state="WORLD_READY",
                recognizer=scripted_recognizer,
                route_input_count=0,
                route_input_limit=4,
                route_events=events,
            )
        self.assertIsNotNone(checkpoint)
        self.assertEqual(handler.input_count, 1)
        self.assertEqual([call[0] for call in runtime.calls], ["tap"])
        post_events = [
            event
            for event in events
            if event.get("event") == "safe_popup_post_observed"
        ]
        self.assertEqual(
            [event["post_phase"] for event in post_events], ["immediate", "settle"]
        )
        reconciled = [
            event for event in events if event.get("event") == "safe_popup_reconciled"
        ]
        self.assertEqual(len(reconciled), 1)
        self.assertEqual(reconciled[0]["post_observation_count"], 2)
        self.assertEqual(
            reconciled[0]["immediate_post_frame_sha256"],
            post_events[0]["post_frame_sha256"],
        )
        self.assertEqual(
            reconciled[0]["post_frame_sha256"],
            post_events[-1]["post_frame_sha256"],
        )

    def test_persistent_popup_blocks_at_settle_bound_without_second_tap(self):
        popup = {
            "popup_identity": "VIP_POINTS_GET_PTS",
            "title_identity": True,
            "body_identity": True,
            "close_identity": POPUP_CLOSE,
            "literal_close": True,
            "target_roi": (263, 781, 537, 869),
            "panel_roi": (80, 300, 720, 940),
            "target_geometry_source": "current-frame-bounded-candidate",
            "context_state": "WORLD_READY",
            "semantic_evidence": [
                "Get Pts",
                "Log in every day to get VIP pts",
                "Close",
            ],
        }
        runtime = FakeRuntime(
            [
                observation("WORLD_READY", popup=popup),
                observation("WORLD_READY", popup=dict(popup)),
                observation("WORLD_READY", popup=dict(popup)),
                observation("WORLD_READY", popup=dict(popup)),
            ]
        )
        source = runtime.capture("popup-source")
        handler = SafePopupHandler(maximum_inputs=1)
        events: list[dict] = []
        with (
            patch(
                "scripts.world_map_navigation_bluestacks.time.sleep",
                return_value=None,
            ),
            self.assertRaisesRegex(
                WorldNavigationBlocked, "popup_transport_without_verified_dismissal"
            ),
        ):
            handler.handle(
                runtime,
                source,
                expected_state="WORLD_READY",
                recognizer=scripted_recognizer,
                route_input_count=0,
                route_input_limit=4,
                route_events=events,
            )
        self.assertEqual([call[0] for call in runtime.calls], ["tap"])
        self.assertEqual(handler.input_count, 1)
        self.assertEqual(
            len(
                [
                    event
                    for event in events
                    if event.get("event") == "safe_popup_post_observed"
                ]
            ),
            3,
        )

    def test_unknown_popup_post_state_blocks_without_second_tap(self):
        popup = {
            "popup_identity": "VIP_POINTS_GET_PTS",
            "title_identity": True,
            "body_identity": True,
            "close_identity": POPUP_CLOSE,
            "literal_close": True,
            "target_roi": (263, 781, 537, 869),
            "panel_roi": (80, 300, 720, 940),
            "target_geometry_source": "current-frame-bounded-candidate",
            "context_state": "WORLD_READY",
            "semantic_evidence": [
                "Get Pts",
                "Log in every day to get VIP pts",
                "Close",
            ],
        }
        lookalike = observation(
            "WORLD_READY",
            popup={
                "popup_identity": "UNKNOWN_LOOKALIKE",
                "title_identity": True,
                "body_identity": False,
                "close_identity": "x",
                "literal_close": False,
            },
        )
        runtime = FakeRuntime(
            [
                observation("WORLD_READY", popup=popup),
                observation("WORLD_READY", popup=dict(popup)),
                lookalike,
            ]
        )
        source = runtime.capture("popup-source")
        handler = SafePopupHandler(maximum_inputs=1)
        with (
            patch(
                "scripts.world_map_navigation_bluestacks.time.sleep",
                return_value=None,
            ),
            self.assertRaisesRegex(
                WorldNavigationBlocked, "popup_successor_unknown_or_lookalike"
            ),
        ):
            handler.handle(
                runtime,
                source,
                expected_state="WORLD_READY",
                recognizer=scripted_recognizer,
                route_input_count=0,
                route_input_limit=4,
                route_events=[],
            )
        self.assertEqual([call[0] for call in runtime.calls], ["tap"])
        self.assertEqual(handler.input_count, 1)

    def test_same_frame_popup_close_and_unknown_popup_fail_closed(self):
        handler = SafePopupHandler(maximum_inputs=2)
        runtime = FakeRuntime(
            [
                observation(
                    "WORLD_READY",
                    popup={
                        "popup_identity": "VIP_POINTS_GET_PTS",
                        "title_identity": True,
                        "body_identity": True,
                        "close_identity": POPUP_CLOSE,
                        "literal_close": True,
                        "target_roi": (260, 768, 540, 842),
                        "panel_roi": (80, 300, 720, 940),
                        "target_geometry_source": "current-frame-bounded-candidate",
                        "context_state": "WORLD_READY",
                        "semantic_evidence": [
                            "Get Pts",
                            "Log in every day to get VIP pts",
                            "Close",
                        ],
                    },
                ),
                observation("WORLD_READY"),
            ]
        )
        source = runtime.capture("popup")
        handler.handle(
            runtime,
            source,
            expected_state="WORLD_READY",
            recognizer=scripted_recognizer,
            route_input_count=0,
            route_input_limit=4,
            route_events=[],
        )
        with self.assertRaisesRegex(WorldNavigationBlocked, "same_frame"):
            handler.handle(
                runtime,
                source,
                expected_state="WORLD_READY",
                recognizer=scripted_recognizer,
                route_input_count=0,
                route_input_limit=4,
                route_events=[],
            )
        unknown = FakeRuntime(
            [
                observation(
                    "WORLD_READY",
                    unknown_modal=True,
                    popup={
                        "popup_identity": "UNKNOWN_LOOKALIKE",
                        "title_identity": True,
                    },
                )
            ]
        )
        with self.assertRaisesRegex(WorldNavigationBlocked, "unknown_popup"):
            handler.handle(
                unknown,
                unknown.capture("unknown-popup"),
                expected_state="WORLD_READY",
                recognizer=scripted_recognizer,
                route_input_count=0,
                route_input_limit=4,
                route_events=[],
            )

    def test_same_popup_can_recur_only_on_a_distinct_verified_capture(self):
        popup = {
            "popup_identity": "VIP_POINTS_GET_PTS",
            "title_identity": True,
            "body_identity": True,
            "close_identity": POPUP_CLOSE,
            "literal_close": True,
            "target_roi": (260, 768, 540, 842),
            "panel_roi": (80, 300, 720, 940),
            "target_geometry_source": "current-frame-bounded-candidate",
            "context_state": "WORLD_READY",
            "semantic_evidence": [
                "Get Pts",
                "Log in every day to get VIP pts",
                "Close",
            ],
        }
        first = observation(
            "WORLD_READY",
            popup=popup,
        )
        second = dict(first)
        second["popup"] = dict(popup)
        runtime = FakeRuntime(
            [first, observation("WORLD_READY"), second, observation("WORLD_READY")]
        )
        handler = SafePopupHandler(maximum_inputs=2)
        events: list[dict] = []
        first_source = runtime.capture("first")
        handler.handle(
            runtime,
            first_source,
            expected_state="WORLD_READY",
            recognizer=scripted_recognizer,
            route_input_count=0,
            route_input_limit=4,
            route_events=events,
        )
        second_source = runtime.capture("second")
        handler.handle(
            runtime,
            second_source,
            expected_state="WORLD_READY",
            recognizer=scripted_recognizer,
            route_input_count=0,
            route_input_limit=4,
            route_events=events,
        )
        self.assertEqual(handler.input_count, 2)

    def test_home_ready_requires_exact_current_frame_world_control_before_input(self):
        missing_control = route_frames()
        missing_control[0] = observation(HOME_READY)
        runtime = FakeRuntime(missing_control)
        result = run_world_map_navigation(
            runtime,
            recognizer=scripted_recognizer,
            maximum_inputs=4,
        )
        self.assertEqual(result["status"], BLOCKED_FAIL_CLOSED)
        self.assertEqual(result["navigation_input_count"], 0)
        self.assertEqual(runtime.calls, [])

        missing_evidence = route_frames()
        missing_evidence[0]["semantic_evidence"] = []
        evidence_runtime = FakeRuntime(missing_evidence)
        evidence_result = run_world_map_navigation(
            evidence_runtime,
            recognizer=scripted_recognizer,
            maximum_inputs=4,
        )
        self.assertEqual(evidence_result["status"], BLOCKED_FAIL_CLOSED)
        self.assertEqual(evidence_result["navigation_input_count"], 0)
        self.assertEqual(evidence_runtime.calls, [])

        for identity in ("atlas", "building", "atlas-building"):
            with self.subTest(identity=identity):
                wrong_identity = route_frames()
                wrong_identity[0] = observation(
                    HOME_READY,
                    controls={identity: (100, 100, 220, 160)},
                )
                wrong_runtime = FakeRuntime(wrong_identity)
                wrong_result = run_world_map_navigation(
                    wrong_runtime,
                    recognizer=scripted_recognizer,
                    maximum_inputs=4,
                )
                self.assertEqual(wrong_result["status"], BLOCKED_FAIL_CLOSED)
                self.assertEqual(wrong_result["navigation_input_count"], 0)
                self.assertEqual(wrong_runtime.calls, [])

        wrong_semantics = route_frames()
        wrong_semantics[0]["control_semantics"]["home-to-world"] = ("Atlas",)
        semantic_runtime = FakeRuntime(wrong_semantics)
        semantic_result = run_world_map_navigation(
            semantic_runtime,
            recognizer=scripted_recognizer,
            maximum_inputs=4,
        )
        self.assertEqual(semantic_result["status"], BLOCKED_FAIL_CLOSED)
        self.assertEqual(semantic_result["navigation_input_count"], 0)
        self.assertEqual(semantic_runtime.calls, [])

    def test_home_canonical_is_only_a_stronger_home_ready_source(self):
        stronger = route_frames()
        stronger[0] = observation(
            HOME_CANONICAL,
            controls={"home-to-world": (100, 100, 220, 160)},
        )
        runtime = FakeRuntime(stronger)
        result = run_world_map_navigation(
            runtime,
            recognizer=scripted_recognizer,
            maximum_inputs=4,
        )
        self.assertEqual(result["status"], NAVIGATION_ONLY_COMPLETE)
        self.assertEqual(result["route_transitions"][0]["source_state"], HOME_READY)
        self.assertEqual(result["final_state"], HOME_READY)

    def test_wrong_zoom_stale_roi_and_missing_successor_block_without_retry(self):
        wrong_zoom = route_frames()
        wrong_zoom[1]["zoom_identity"] = "WORLD_ZOOM_UNKNOWN"
        result = run_world_map_navigation(
            FakeRuntime(wrong_zoom),
            recognizer=scripted_recognizer,
            maximum_inputs=4,
        )
        self.assertEqual(result["status"], BLOCKED_FAIL_CLOSED)
        self.assertEqual(result["navigation_input_count"], 1)

        stale_runtime = FakeRuntime(route_frames())
        recognizer = scripted_recognizer
        original = recognizer

        def stale(frame, **kwargs):
            value = original(frame, **kwargs)
            if value["state"] == "WORLD_READY" and "world-search-entry" in value.get(
                "controls", {}
            ):
                value = dict(value)
                value["source_frame_sha256"] = "different"
            return value

        stale_result = run_world_map_navigation(
            stale_runtime,
            recognizer=stale,
            maximum_inputs=4,
        )
        self.assertEqual(stale_result["status"], BLOCKED_FAIL_CLOSED)
        self.assertEqual(stale_result["navigation_input_count"], 1)

        missing_home = route_frames()
        missing_home[-1] = observation("WORLD_READY")
        missing_home.extend([observation("WORLD_READY"), observation("WORLD_READY")])
        missing_result = run_world_map_navigation(
            FakeRuntime(missing_home),
            recognizer=scripted_recognizer,
            maximum_inputs=4,
        )
        self.assertEqual(missing_result["status"], BLOCKED_FAIL_CLOSED)
        self.assertEqual(
            missing_result["reason"],
            "unexpected_successor:WORLD_READY:HOME_READY",
        )

    def test_budget_exhaustion_and_forbidden_identity_are_closed(self):
        runtime = FakeRuntime(route_frames())
        result = run_world_map_navigation(
            runtime,
            recognizer=scripted_recognizer,
            maximum_inputs=3,
        )
        self.assertEqual(result["status"], BLOCKED_FAIL_CLOSED)
        self.assertEqual(result["navigation_input_count"], 3)
        self.assertEqual(len(runtime.calls), 3)
        self.assertEqual(
            set(route_declaration()["allowed_target_identities"]),
            ALLOWED_CONTROL_IDENTITIES,
        )

        bad = observation(
            "WORLD_READY",
            controls={"resource-node-dispatch": (10, 10, 50, 50)},
        )
        self.assertFalse(
            world_navigation_observation_authorizeable(
                WorldNavigationObservation(
                    "WORLD_READY",
                    "a" * 64,
                    "current.png",
                    controls={"resource-node-dispatch": (10, 10, 50, 50)},
                ),
                expected_state="WORLD_READY",
                required_target_identity="resource-node-dispatch",
                require_supported_zoom=True,
            )
        )
        self.assertEqual(bad["state"], "WORLD_READY")

    def test_node_binding_and_pan_are_planning_only_and_current_frame_bound(self):
        digest = "b" * 64
        node = WorldNavigationObservation(
            "WORLD_READY",
            digest,
            "current.png",
            controls={},
            node_identity="node-17",
            node_roi=(300, 500, 380, 580),
            node_source_frame_sha256=digest,
            node_label="Resource",
            node_label_roi=(310, 510, 370, 535),
            node_semantic_evidence=("resource node label spatially associated",),
            zoom_evidence=("supported-world-zoom-visual-landmarks",),
            localization_evidence=("current-frame-world-localization",),
            semantic_evidence=("World", "resource node label spatially associated"),
        )
        self.assertTrue(world_node_binding_authorizeable(node))
        plan = plan_bounded_world_pan(node, direction="left", maximum_steps=2)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.source_frame_sha256, digest)
        self.assertIsNone(
            plan_bounded_world_pan(node, direction="left", maximum_steps=4)
        )
        self.assertFalse(
            world_node_binding_authorizeable(
                replace(node, node_source_frame_sha256="c" * 64)
            )
        )
        self.assertFalse(
            world_node_binding_authorizeable(replace(node, node_roi=(1, 1, 900, 2)))
        )

    def test_independent_fixture_expectations_are_loaded_and_not_production_defaults(
        self,
    ):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        observations = fixture["observations"]
        home = observations["home_canonical"]
        home_observation = WorldNavigationObservation(
            **{
                key: value
                for key, value in {
                    "state": home["state"],
                    "source_frame_sha256": "c" * 64,
                    "evidence_ref": "independent-fixture-home.png",
                    "zoom_identity": home["zoom_identity"],
                    "controls": {
                        key: tuple(value) for key, value in home["controls"].items()
                    },
                    "control_semantics": home["control_semantics"],
                    "control_geometry_source": home["control_geometry_source"],
                    "semantic_evidence": tuple(home["semantic_evidence"]),
                }.items()
            }
        )
        self.assertTrue(
            world_navigation_observation_authorizeable(
                home_observation,
                expected_state="HOME_CANONICAL",
                required_target_identity="home-to-world",
            )
        )
        home_ready_observation = replace(
            home_observation,
            state=HOME_READY,
            semantic_evidence=tuple(observations["home_ready"]["semantic_evidence"]),
        )
        self.assertTrue(
            world_navigation_observation_authorizeable(
                home_ready_observation,
                expected_state=HOME_READY,
                required_target_identity="home-to-world",
            )
        )
        wrong_zoom = observations["wrong_zoom"]
        wrong = WorldNavigationObservation(
            "WORLD_READY",
            "d" * 64,
            "independent-fixture-world.png",
            zoom_identity=wrong_zoom["zoom_identity"],
            controls={
                key: tuple(value) for key, value in wrong_zoom["controls"].items()
            },
            control_semantics={"world-search-entry": ("Search",)},
            control_geometry_source={
                "world-search-entry": "current-frame-bounded-candidate"
            },
            semantic_evidence=tuple(wrong_zoom["semantic_evidence"]),
            zoom_evidence=("unsupported",),
            localization_evidence=("current-frame-world-localization",),
        )
        self.assertFalse(
            world_navigation_observation_authorizeable(
                wrong,
                expected_state="WORLD_READY",
                required_target_identity="world-search-entry",
                require_supported_zoom=True,
            )
        )
        node_payload = dict(observations["node_binding"])
        node_observation = world_navigation_observation_from_mapping(node_payload)
        self.assertTrue(world_node_binding_authorizeable(node_observation))

    def test_event_validator_derives_route_and_rejects_adversarial_proof(self):
        events, route, hashes = hud_validator_events()
        _verify_event_order(events, route, hashes)
        result_payload = {
            "world_navigation_result": route,
            "terminal_runtime_state": HOME_READY,
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        }
        _verify_route_semantics(
            result_payload,
            events,
        )

        canonical_terminal = [dict(event) for event in events]
        terminal_event = next(
            event
            for event in canonical_terminal
            if event.get("event") == "route_terminal"
        )
        terminal_event["state"] = HOME_CANONICAL
        with self.assertRaises(pnsctl.OperatorError):
            _verify_event_order(canonical_terminal, route, hashes)

        canonical_result = dict(
            route,
            final_state=HOME_CANONICAL,
            terminal_runtime_state=HOME_CANONICAL,
        )
        with self.assertRaises(pnsctl.OperatorError):
            _verify_route_semantics(
                dict(
                    result_payload,
                    world_navigation_result=canonical_result,
                    terminal_runtime_state=HOME_CANONICAL,
                ),
                events,
            )

        stale = [dict(event) for event in events]
        dispatches = [event for event in stale if event.get("type") == "dispatch"]
        second = dispatches[1]
        second["source_sha256"] = dispatches[0]["source_sha256"]
        with self.assertRaises(pnsctl.OperatorError):
            _verify_event_order(stale, route, hashes)

        wrong_order = [dict(event) for event in events]
        navigation = [
            event
            for event in wrong_order
            if event.get("type") == "semantic"
            and event.get("event") == "navigation_reconciled"
        ]
        navigation[0]["target_identity"] = "world-search-entry"
        with self.assertRaises(pnsctl.OperatorError):
            _verify_event_order(wrong_order, route, hashes)

        missing_post = [
            event
            for event in events
            if not (event.get("type") == "capture" and event.get("sha256") == "5" * 64)
        ]
        with self.assertRaises(pnsctl.OperatorError):
            _verify_event_order(missing_post, route, hashes - {"5" * 64})

        missing_reconcile = [
            event
            for event in events
            if not (
                event.get("type") == "reconcile"
                and event.get("action_key") == "action-2"
            )
        ]
        with self.assertRaises(pnsctl.OperatorError):
            _verify_event_order(missing_reconcile, route, hashes)

        missing_terminal = [
            event for event in events if event.get("event") != "route_terminal"
        ]
        with self.assertRaises(pnsctl.OperatorError):
            _verify_event_order(missing_terminal, route, hashes)

        extra_dispatch = [dict(event) for event in events]
        extra_dispatch.insert(
            4,
            {
                "type": "dispatch",
                "action_key": "extra",
                "target_identity": "home-to-world",
                "target_roi": (10, 10, 50, 50),
                "source_sha256": "1" * 64,
                "consequential": False,
            },
        )
        extra_route = dict(route, input_count=5, navigation_input_count=5)
        with self.assertRaises(pnsctl.OperatorError):
            _verify_event_order(extra_dispatch, extra_route, hashes)

    def test_recovery_contract_accepts_world_ready_and_search_menu_paths(self):
        for menu_open in (False, True):
            with self.subTest(menu_open=menu_open):
                events, route, hashes = recovery_validator_events(
                    menu_open=menu_open,
                )
                _verify_event_order(events, route, hashes)
                _verify_route_semantics(
                    {
                        "world_navigation_result": route,
                        "terminal_runtime_state": HOME_READY,
                        "production_registration": "NOT_REGISTERED",
                        "scheduler_enabled": False,
                    },
                    events,
                )

    def test_development_runtime_observation_accepts_standard_png_frame(self):
        frame = bytearray(24)
        frame[:8] = b"\x89PNG\r\n\x1a\n"
        frame[16:20] = (800).to_bytes(4, "big")
        frame[20:24] = (1280).to_bytes(4, "big")
        expected_frame = bytes(frame)
        outputs = (
            "device\n",
            expected_frame,
            "mCurrentFocus=Window{123 u0 com.global.ztmslg/.MainActivity}\n",
        )

        with patch.object(
            pnsctl,
            "_run_fixed_bluestacks_adb",
            side_effect=outputs,
        ):
            result, returned_frame = pnsctl._development_runtime_observation()

        self.assertEqual(returned_frame, expected_frame)
        self.assertEqual(
            result,
            {
                "device_state": "device",
                "foreground_package": "com.global.ztmslg",
                "native_width": 800,
                "native_height": 1280,
                "frame_sha256": hashlib.sha256(expected_frame).hexdigest(),
            },
        )

    def test_registry_and_dry_run_are_fixed_and_unregistered(self):
        self.assertIn(RUNNER_ID, pnsctl._BLUESTACKS_FLOW_RUNNERS)
        self.assertIn(VALIDATOR_ID, pnsctl._BLUESTACKS_EVIDENCE_VALIDATORS)
        self.assertIn(RECOVERY_ID, pnsctl._BLUESTACKS_RECOVERY_HANDLERS)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                pnsctl,
                "BLUESTACKS_ARTIFACT_ROOT",
                Path(directory),
            ):
                result = json.loads(
                    run_world_map_navigation_foundation(
                        {},
                        {"owner": "test-owner", "max_inputs": 7},
                        live=False,
                    )
                )
        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(result["dispatch"])
        self.assertEqual(result["input_count"] if "input_count" in result else 0, 0)
        self.assertEqual(result["production_registration"], "NOT_REGISTERED")
        self.assertFalse(result["scheduler_enabled"])

    def test_search_entry_only_flow_lease_forces_one_input_and_path(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                pnsctl,
                "BLUESTACKS_ARTIFACT_ROOT",
                Path(directory),
            ):
                result = json.loads(
                    run_world_map_navigation_foundation(
                        {},
                        {
                            "owner": "test-owner",
                            "max_inputs": 20,
                            "search_entry_only": True,
                        },
                        live=False,
                    )
                )
        self.assertEqual(result["max_inputs"], 1)
        self.assertEqual(result["path"], SEARCH_ENTRY_ONLY_PATH)
        self.assertEqual(result["input_count"], 0)
        self.assertEqual(result["proof_topology"], "diagnostic")
        self.assertFalse(result["acceptance_eligible"])

    def test_retained_popup_recognizer_rejects_non_native_frame(self):
        result = recognize_allowlisted_popup(
            np.zeros((100, 100, 3), dtype=np.uint8), source_frame_sha256="a" * 64
        )
        self.assertEqual(result.status, "unknown")

    def test_split_ocr_words_are_grouped_into_spatial_phrase_lines(self):
        grouped = _group_spatial_ocr_hits(
            [
                ("log", (100, 100, 140, 124)),
                ("in", (142, 99, 170, 123)),
                ("every", (172, 101, 230, 125)),
                ("day", (232, 99, 274, 124)),
                ("to", (276, 100, 300, 123)),
                ("get", (302, 100, 340, 124)),
                ("vip", (342, 100, 378, 124)),
                ("pts", (380, 99, 418, 124)),
                ("other", (105, 155, 150, 178)),
            ]
        )
        self.assertIn(
            ("log in every day to get vip pts", (100, 99, 418, 125)),
            grouped,
        )
        self.assertNotIn(("log", (100, 100, 140, 124)), grouped)

    def test_popup_uses_panel_local_semantics_and_independent_button_geometry(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        panel = (96, 260, 704, 948)
        button = (228, 772, 572, 856)

        def local_ocr(_frame, roi, *, psm):
            if roi == panel and psm == 11:
                return "Get Pts\nLog in every day to get VIP pts"
            if psm == 7:
                return "Close"
            return ""

        with (
            patch(
                "scripts.world_map_navigation_bluestacks._ocr_hits",
                return_value=[],
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._visual_popup_panel_candidates",
                return_value=[panel],
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._visual_candidate_boxes",
                return_value=[button],
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._ocr_text_in_roi",
                side_effect=local_ocr,
            ),
        ):
            result = recognize_allowlisted_popup(
                frame,
                source_frame_sha256="b" * 64,
            )

        self.assertEqual(result.status, "allowed")
        self.assertEqual(result.popup_identity, "VIP_POINTS_GET_PTS")
        self.assertEqual(result.target_identity, POPUP_CLOSE)
        self.assertEqual(result.target_roi, button)
        self.assertIn("Get Pts", result.semantic_evidence)
        self.assertIn("Log in every day to get VIP pts", result.semantic_evidence)
        self.assertIn("Close", result.semantic_evidence)

    def test_popup_accepts_merged_getpts_only_with_exact_body_and_close(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        panel = (96, 260, 704, 948)
        button = (228, 772, 572, 856)
        cases = (
            (
                "GetPts\nLog in every day to get VIP pts",
                "Close",
                "allowed",
            ),
            ("GetPts", "Close", "unknown"),
            ("GetPts\nLog in every day to get VIP rewards", "Close", "unknown"),
            (
                "GetPts\nLog in every day to get VIP pts",
                "Dismiss",
                "unknown",
            ),
        )
        for panel_text, close_text, expected_status in cases:
            with self.subTest(panel_text=panel_text, close_text=close_text):

                def local_ocr(_frame, roi, *, psm):
                    if roi == panel and psm == 11:
                        return panel_text
                    if psm == 7:
                        return close_text
                    return ""

                with (
                    patch(
                        "scripts.world_map_navigation_bluestacks._ocr_hits",
                        return_value=[],
                    ),
                    patch(
                        "scripts.world_map_navigation_bluestacks._visual_popup_panel_candidates",
                        return_value=[panel],
                    ),
                    patch(
                        "scripts.world_map_navigation_bluestacks._visual_candidate_boxes",
                        return_value=[button],
                    ),
                    patch(
                        "scripts.world_map_navigation_bluestacks._ocr_text_in_roi",
                        side_effect=local_ocr,
                    ),
                ):
                    result = recognize_allowlisted_popup(
                        frame,
                        source_frame_sha256="e" * 64,
                    )
                self.assertEqual(result.status, expected_status)
                if expected_status == "allowed":
                    self.assertEqual(result.popup_identity, "VIP_POINTS_GET_PTS")
                    self.assertEqual(result.target_identity, POPUP_CLOSE)
                    self.assertEqual(result.target_roi, button)
                    self.assertEqual(result.source_frame_sha256, "e" * 64)

    def test_popup_lookalike_partial_and_unbacked_panel_evidence_fail_closed(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        panel = (96, 260, 704, 948)
        button = (228, 772, 572, 856)

        cases = (
            ("Get Rewards\nLog in every day to get VIP pts", "Close", "unknown"),
            ("Get Pts\nLog in every day to get VIP pts", "Dismiss", "unknown"),
            ("Get Rewards\nDaily rewards", "Close", "absent"),
        )
        for panel_text, close_text, expected in cases:
            with self.subTest(panel_text=panel_text, close_text=close_text):

                def local_ocr(_frame, roi, *, psm):
                    if roi == panel and psm == 11:
                        return panel_text
                    if psm == 7:
                        return close_text
                    return ""

                with (
                    patch(
                        "scripts.world_map_navigation_bluestacks._ocr_hits",
                        return_value=[],
                    ),
                    patch(
                        "scripts.world_map_navigation_bluestacks._visual_popup_panel_candidates",
                        return_value=[panel],
                    ),
                    patch(
                        "scripts.world_map_navigation_bluestacks._visual_candidate_boxes",
                        return_value=[button],
                    ),
                    patch(
                        "scripts.world_map_navigation_bluestacks._ocr_text_in_roi",
                        side_effect=local_ocr,
                    ),
                ):
                    result = recognize_allowlisted_popup(
                        frame,
                        source_frame_sha256="c" * 64,
                    )
                self.assertEqual(result.status, expected)

    def test_popup_close_roi_follows_moved_current_frame_button_geometry(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        panel = (70, 220, 730, 980)
        for button in ((160, 760, 390, 836), (414, 804, 650, 884)):
            with self.subTest(button=button):

                def local_ocr(_frame, roi, *, psm):
                    if roi == panel and psm == 11:
                        return "Get Pts\nLog in every day to get VIP pts"
                    if psm == 7:
                        return "Close"
                    return ""

                with (
                    patch(
                        "scripts.world_map_navigation_bluestacks._ocr_hits",
                        return_value=[],
                    ),
                    patch(
                        "scripts.world_map_navigation_bluestacks._visual_popup_panel_candidates",
                        return_value=[panel],
                    ),
                    patch(
                        "scripts.world_map_navigation_bluestacks._visual_candidate_boxes",
                        return_value=[button],
                    ),
                    patch(
                        "scripts.world_map_navigation_bluestacks._ocr_text_in_roi",
                        side_effect=local_ocr,
                    ),
                ):
                    result = recognize_allowlisted_popup(
                        frame,
                        source_frame_sha256="d" * 64,
                    )
                self.assertEqual(result.status, "allowed")
                self.assertEqual(result.target_roi, button)

    def test_retained_native_close_roi_matches_independent_button_measurement(self):
        geometry = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][
            "retained_source_popup_geometry"
        ]
        source = (
            ROOT
            / ".local-captures"
            / "flow-delivery"
            / "WORLD-MAP-NAVIGATION-FOUNDATION"
            / "run-20260816T030538631368Z"
            / "world-map-navigation-20260816T030538742441Z"
            / "frames"
            / "0001-world-navigation-source.png"
        )
        if not source.is_file():
            self.skipTest("retained live source frame is unavailable")
        raw = source.read_bytes()
        self.assertEqual(
            hashlib.sha256(raw).hexdigest(),
            geometry["source_frame_sha256"],
        )
        frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame)
        self.assertEqual(
            frame.shape[:2], (geometry["native_height"], geometry["native_width"])
        )

        # Independently measure the orange Close button in native pixels.  These
        # bounds are fixture ground truth, not production recognition constants.
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        orange = cv2.inRange(
            hsv,
            np.array([5, 80, 80], dtype=np.uint8),
            np.array([35, 255, 255], dtype=np.uint8),
        )
        _count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
            orange, connectivity=8
        )
        measured_boxes = {
            (
                int(x),
                int(y),
                int(x + width),
                int(y + height),
            )
            for x, y, width, height, area in stats[1:]
            if int(area) > 10_000 and int(y) > 700
        }
        measured = tuple(geometry["close_button_roi"])
        self.assertIn(measured, measured_boxes)

        def local_ocr(_frame, _roi, *, psm):
            if psm == 11:
                return "Get Pts\nLog in every day to get VIP pts"
            if psm == 7:
                return "Close"
            return ""

        with (
            patch(
                "scripts.world_map_navigation_bluestacks._ocr_hits",
                return_value=[],
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._ocr_text_in_roi",
                side_effect=local_ocr,
            ),
        ):
            result = recognize_allowlisted_popup(
                frame,
                source_frame_sha256=geometry["source_frame_sha256"],
            )
        self.assertEqual(result.status, "allowed")
        self.assertEqual(result.target_roi, measured)

    def test_world_text_alone_cannot_authorize_supported_zoom_or_targets(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        with (
            patch(
                "scripts.world_map_navigation_bluestacks._ocr_hits",
                return_value=[
                    ("World", (100, 100, 180, 140)),
                    ("Search", (600, 100, 700, 140)),
                ],
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._visual_candidate_boxes",
                return_value=[],
            ),
        ):
            result = recognize_world_frame(
                frame,
                source_frame_sha256="e" * 64,
                evidence_ref="independent-native-frame.png",
            )
        self.assertNotEqual(result.zoom_identity, WORLD_ZOOM_SUPPORTED)
        self.assertFalse(result.recognized)
        self.assertEqual(
            recognize_allowlisted_popup(
                frame,
                source_frame_sha256="e" * 64,
            ).status,
            "absent",
        )

    def test_footer_fallback_binds_exact_world_to_current_footer_candidate(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        candidate = (36, 1242, 112, 1265)
        text_roi = (39, 1242, 108, 1261)
        with (
            patch(
                "scripts.world_map_navigation_bluestacks._ocr_hits",
                return_value=[],
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._visual_candidate_boxes",
                return_value=[candidate],
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._footer_navigation_ocr_hits",
                return_value=[("World", text_roi)],
            ) as fallback,
            patch(
                "scripts.world_map_navigation_bluestacks._footer_control_binding",
                wraps=navigation._footer_control_binding,
            ) as footer_binding,
        ):
            result = recognize_world_frame(
                frame,
                source_frame_sha256="7" * 64,
                evidence_ref="current-home-frame.png",
            )
        self.assertEqual(result.state, HOME_READY)
        self.assertEqual(result.controls[HOME_TO_WORLD], candidate)
        self.assertEqual(result.control_semantics[HOME_TO_WORLD], ("World",))
        self.assertEqual(
            result.control_geometry_source[HOME_TO_WORLD],
            "current-frame-bounded-candidate",
        )
        fallback.assert_called_once_with(frame)
        footer_binding.assert_called_once()
        self.assertEqual(footer_binding.call_args.args[1], HOME_TO_WORLD)

    def test_normal_world_footer_binding_skips_home_fallback(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        home_candidate = (20, 1167, 128, 1258)
        with (
            patch(
                "scripts.world_map_navigation_bluestacks._ocr_hits",
                return_value=[("Home", (20, 1220, 120, 1270))],
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._visual_candidate_boxes",
                return_value=[home_candidate],
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._footer_navigation_ocr_hits",
                side_effect=AssertionError(
                    "fallback must not run after normal World binding"
                ),
            ),
        ):
            result = recognize_world_frame(
                frame,
                source_frame_sha256="a" * 64,
                evidence_ref="current-world-frame.png",
            )
        self.assertEqual(result.controls[WORLD_TO_HOME], home_candidate)

    def test_normal_home_footer_binding_skips_world_fallback(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        world_candidate = (36, 1242, 112, 1265)
        with (
            patch(
                "scripts.world_map_navigation_bluestacks._ocr_hits",
                return_value=[("World", (39, 1242, 108, 1261))],
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._visual_candidate_boxes",
                return_value=[world_candidate],
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._footer_navigation_ocr_hits",
                side_effect=AssertionError(
                    "fallback must not run after normal Home binding"
                ),
            ),
        ):
            result = recognize_world_frame(
                frame,
                source_frame_sha256="b" * 64,
                evidence_ref="current-home-frame.png",
            )
        self.assertEqual(result.controls[HOME_TO_WORLD], world_candidate)

    def test_normal_footer_binding_clips_broad_candidate_to_world_control_region(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        broad_footer_candidate = (0, 1167, 631, 1268)
        with (
            patch(
                "scripts.world_map_navigation_bluestacks._ocr_hits",
                return_value=[("World", (39, 1231, 108, 1265))],
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._visual_candidate_boxes",
                return_value=[broad_footer_candidate],
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._footer_navigation_ocr_hits",
                side_effect=AssertionError(
                    "fallback must not run after normal Home binding"
                ),
            ),
        ):
            result = recognize_world_frame(
                frame,
                source_frame_sha256="3" * 64,
                evidence_ref="current-home-frame.png",
            )
        self.assertEqual(
            result.controls[HOME_TO_WORLD],
            (0, 1167, 150, 1268),
        )

    def test_footer_fallback_rejects_mixed_ambiguous_unrelated_or_unbound_labels(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        candidate = (36, 1242, 112, 1265)
        text_roi = (39, 1242, 108, 1261)
        cases = (
            (
                [("World", text_roi), ("Home", (28, 1220, 75, 1240))],
                [candidate],
            ),
            (
                [("World", text_roi), ("World", (38, 1242, 109, 1261))],
                [candidate],
            ),
            ([("Quest", text_roi)], [candidate]),
            ([("World", text_roi)], []),
        )
        for footer_hits, candidates in cases:
            with self.subTest(footer_hits=footer_hits, candidates=candidates):
                with (
                    patch(
                        "scripts.world_map_navigation_bluestacks._ocr_hits",
                        return_value=[],
                    ),
                    patch(
                        "scripts.world_map_navigation_bluestacks._visual_candidate_boxes",
                        return_value=candidates,
                    ),
                    patch(
                        "scripts.world_map_navigation_bluestacks._footer_navigation_ocr_hits",
                        return_value=footer_hits,
                    ),
                ):
                    result = recognize_world_frame(
                        frame,
                        source_frame_sha256="8" * 64,
                        evidence_ref="current-home-frame.png",
                    )
                self.assertEqual(result.state, "UNKNOWN")
                self.assertNotIn(HOME_TO_WORLD, result.controls)

    def test_footer_fallback_binds_base_for_world_recovery_without_atlas_authority(
        self,
    ):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        home_candidate = (20, 1167, 128, 1258)
        coordinate_hits = [
            ("X:299", (290, 70, 360, 115)),
            ("Y:495", (360, 70, 430, 115)),
        ]
        with (
            patch(
                "scripts.world_map_navigation_bluestacks._ocr_hits",
                return_value=coordinate_hits,
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._visual_candidate_boxes",
                return_value=[home_candidate],
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._footer_navigation_ocr_hits",
                return_value=[("Base", (30, 1243, 100, 1267))],
            ),
        ):
            result = recognize_world_home_recovery(
                frame,
                source_frame_sha256="9" * 64,
                evidence_ref="current-world-recovery-frame.png",
            )
        self.assertEqual(result.state, WORLD_READY)
        self.assertEqual(result.controls[WORLD_TO_HOME], home_candidate)
        self.assertEqual(result.control_semantics[WORLD_TO_HOME], ("Base",))
        self.assertNotEqual(result.zoom_identity, WORLD_ZOOM_SUPPORTED)

    def test_footer_binding_rejects_distinct_candidates_but_deduplicates_nested_equivalents(
        self,
    ):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        text_roi = (39, 1242, 108, 1261)
        exact = (36, 1242, 112, 1265)
        nested_equivalent = (35, 1241, 113, 1266)
        distinct = (50, 1242, 126, 1265)

        with (
            patch(
                "scripts.world_map_navigation_bluestacks._ocr_hits",
                return_value=[],
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._visual_candidate_boxes",
                return_value=[exact, nested_equivalent],
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._footer_navigation_ocr_hits",
                return_value=[("World", text_roi)],
            ),
        ):
            resolved = recognize_world_frame(
                frame,
                source_frame_sha256="c" * 64,
                evidence_ref="current-home-frame.png",
            )
        self.assertEqual(resolved.state, HOME_READY)
        self.assertEqual(resolved.controls[HOME_TO_WORLD], exact)

        with (
            patch(
                "scripts.world_map_navigation_bluestacks._ocr_hits",
                return_value=[],
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._visual_candidate_boxes",
                return_value=[exact, distinct],
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._footer_navigation_ocr_hits",
                return_value=[("World", text_roi)],
            ),
        ):
            ambiguous = recognize_world_frame(
                frame,
                source_frame_sha256="d" * 64,
                evidence_ref="current-home-frame.png",
            )
        self.assertEqual(ambiguous.state, "UNKNOWN")
        self.assertNotIn(HOME_TO_WORLD, ambiguous.controls)

    def test_current_frame_magnifier_binds_search_without_zoom_authority(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        search_button = (94, 1026, 190, 1093)
        home_button = (20, 1167, 132, 1258)
        cv2.rectangle(frame, search_button[:2], search_button[2:], (50, 50, 50), -1)
        cv2.circle(frame, (126, 1058), 16, (230, 230, 230), 3)
        cv2.line(frame, (137, 1069), (150, 1082), (230, 230, 230), 3)
        with (
            patch(
                "scripts.world_map_navigation_bluestacks._ocr_hits",
                return_value=[
                    ("X:299", (290, 110, 350, 145)),
                    ("Y:495", (360, 110, 420, 145)),
                    ("Home", (20, 1220, 120, 1270)),
                ],
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._visual_candidate_boxes",
                return_value=[search_button, home_button],
            ),
        ):
            result = recognize_world_frame(
                frame,
                source_frame_sha256="1" * 64,
                evidence_ref="current-native-world.png",
            )
        self.assertEqual(result.state, WORLD_READY)
        self.assertEqual(result.zoom_identity, "WORLD_ZOOM_UNKNOWN")
        self.assertEqual(result.zoom_evidence, ())
        self.assertEqual(result.localization_evidence, ())
        self.assertEqual(
            result.controls[WORLD_SEARCH_ENTRY],
            (100, 1030, 152, 1086),
        )
        self.assertNotEqual(result.controls[WORLD_SEARCH_ENTRY], search_button)
        self.assertEqual(result.controls[WORLD_TO_HOME], home_button)
        self.assertIn("magnifying-glass lens", result.semantic_evidence)
        self.assertIn("magnifying-glass handle", result.semantic_evidence)
        self.assertIn("fixed native Search HUD slot", result.semantic_evidence)

    def test_magnifier_binding_ignores_broad_or_missing_contours(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        broad_toolbar = (0, 1025, 161, 1100)
        cv2.rectangle(frame, (94, 1026), (190, 1093), (50, 50, 50), -1)
        cv2.circle(frame, (126, 1058), 16, (230, 230, 230), 3)
        cv2.line(frame, (137, 1069), (150, 1082), (230, 230, 230), 3)

        self.assertEqual(
            _visual_search_entry_binding(frame, candidates=[broad_toolbar])[0],
            (100, 1030, 152, 1086),
        )
        with (
            patch(
                "scripts.world_map_navigation_bluestacks._ocr_hits",
                return_value=[
                    ("X:299", (290, 110, 350, 145)),
                    ("Y:495", (360, 110, 420, 145)),
                ],
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._visual_candidate_boxes",
                return_value=[],
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._footer_navigation_ocr_hits",
                return_value=[],
            ),
        ):
            result = recognize_world_frame(
                frame,
                source_frame_sha256="2" * 64,
                evidence_ref="current-native-world.png",
            )
        self.assertEqual(result.state, WORLD_READY)
        self.assertEqual(
            result.controls[WORLD_SEARCH_ENTRY],
            (100, 1030, 152, 1086),
        )
        self.assertNotIn(WORLD_TO_HOME, result.controls)
        self.assertFalse(
            world_navigation_observation_authorizeable(
                result,
                expected_state=WORLD_READY,
                required_target_identity=WORLD_TO_HOME,
            )
        )

    def test_retained_world_frame_binds_hud_only_search_entry(self):
        source = (
            ROOT
            / ".local-captures"
            / "development-sessions"
            / "observe-20260816T055857724262Z"
            / "observe.png"
        )
        if not source.is_file():
            self.fail(f"required retained World frame is absent: {source}")
        raw = source.read_bytes()
        frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(
            frame,
            f"required retained World frame is unreadable: {source}",
        )
        result = recognize_world_frame(
            frame,
            source_frame_sha256=hashlib.sha256(raw).hexdigest(),
            evidence_ref=str(source),
        )
        self.assertEqual(result.state, WORLD_READY)
        self.assertEqual(
            result.controls,
            {WORLD_SEARCH_ENTRY: (100, 1030, 152, 1086)},
        )
        self.assertEqual(set(result.control_semantics), {WORLD_SEARCH_ENTRY})
        self.assertEqual(
            result.control_semantics[WORLD_SEARCH_ENTRY][0],
            "Search",
        )
        self.assertEqual(
            set(result.control_geometry_source),
            {WORLD_SEARCH_ENTRY},
        )
        self.assertEqual(result.zoom_evidence, ())
        self.assertEqual(result.localization_evidence, ())
        self.assertFalse(
            world_navigation_observation_authorizeable(
                result,
                expected_state=WORLD_READY,
                required_target_identity=WORLD_TO_HOME,
            )
        )
        for forbidden_identity in (
            "zombie",
            "resource-node-dispatch",
            "combat-dispatch",
        ):
            with self.subTest(forbidden_identity=forbidden_identity):
                self.assertFalse(
                    world_navigation_observation_authorizeable(
                        result,
                        expected_state=WORLD_READY,
                        required_target_identity=forbidden_identity,
                    )
                )

    def test_coordinate_hud_accepts_merged_y_prefix_with_current_control_geometry(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        search_button = (94, 1024, 190, 1093)
        home_button = (20, 1167, 128, 1258)
        cv2.rectangle(frame, search_button[:2], search_button[2:], (50, 50, 50), -1)
        cv2.circle(frame, (126, 1058), 16, (230, 230, 230), 3)
        cv2.line(frame, (137, 1069), (150, 1082), (230, 230, 230), 3)
        hits = [
            ("x:299", (323, 99, 427, 205)),
            ("1.495", (424, 104, 520, 198)),
            ("Home", (20, 1220, 120, 1270)),
        ]
        self.assertEqual(
            _coordinate_hud_evidence(frame, hits[:2]),
            ("spatially-bounded-top-coordinate-hud",),
        )
        with (
            patch(
                "scripts.world_map_navigation_bluestacks._ocr_hits",
                return_value=hits,
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._visual_candidate_boxes",
                return_value=[search_button, home_button],
            ),
        ):
            result = recognize_world_frame(
                frame,
                source_frame_sha256="6" * 64,
                evidence_ref="current-native-world.png",
            )
        self.assertEqual(result.state, WORLD_READY)
        self.assertTrue(result.recognized)
        self.assertEqual(
            result.controls[WORLD_SEARCH_ENTRY],
            (100, 1030, 152, 1086),
        )
        self.assertEqual(result.controls[WORLD_TO_HOME], home_button)

    def test_coordinate_hud_rejects_far_or_unusable_y_value_tokens(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        x_hit = ("x:299", (323, 99, 427, 205))
        cases = (
            [x_hit, ("1.495", (548, 104, 596, 198))],
            [("1495", (424, 104, 520, 198))],
            [x_hit, ("49", (424, 104, 520, 198))],
            [x_hit, ("14950", (424, 104, 520, 198))],
            [x_hit, ("1.a95", (424, 104, 520, 198))],
        )
        for hits in cases:
            with self.subTest(hits=hits):
                self.assertEqual(_coordinate_hud_evidence(frame, hits), ())

    def test_magnifier_missing_handle_and_ambiguous_candidates_fail_closed(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        first = (64, 1026, 134, 1093)
        second = (150, 1026, 220, 1093)
        for x0, y0, x1, y1 in (first, second):
            cv2.rectangle(frame, (x0, y0), (x1, y1), (50, 50, 50), -1)
            cv2.circle(frame, (x0 + 28, y0 + 26), 16, (230, 230, 230), 3)
        self.assertIsNone(_visual_search_entry_binding(frame, candidates=[first]))
        cv2.line(
            frame,
            (first[0] + 39, first[1] + 37),
            (first[0] + 57, first[1] + 55),
            (230, 230, 230),
            3,
        )
        cv2.circle(frame, (second[0] + 28, second[1] + 26), 16, (230, 230, 230), 3)
        cv2.line(
            frame,
            (second[0] + 39, second[1] + 37),
            (second[0] + 57, second[1] + 55),
            (230, 230, 230),
            3,
        )
        self.assertIsNone(
            _visual_search_entry_binding(frame, candidates=[first, second])
        )

    def test_world_context_requires_coordinate_hud_and_independent_home_binding(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        search_button = (94, 1026, 190, 1093)
        home_button = (20, 1167, 132, 1258)
        cv2.rectangle(frame, search_button[:2], search_button[2:], (50, 50, 50), -1)
        cv2.circle(frame, (126, 1058), 16, (230, 230, 230), 3)
        cv2.line(frame, (137, 1069), (150, 1082), (230, 230, 230), 3)
        common_hits = [
            ("X:299", (290, 110, 350, 145)),
            ("Y:495", (360, 110, 420, 145)),
        ]
        with (
            patch(
                "scripts.world_map_navigation_bluestacks._ocr_hits",
                return_value=common_hits,
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._visual_candidate_boxes",
                return_value=[search_button, home_button],
            ),
        ):
            missing_home = recognize_world_frame(
                frame,
                source_frame_sha256="2" * 64,
                evidence_ref="current-native-world.png",
            )
        self.assertEqual(missing_home.state, WORLD_READY)
        self.assertIn(WORLD_SEARCH_ENTRY, missing_home.controls)
        self.assertNotIn(WORLD_TO_HOME, missing_home.controls)

        with (
            patch(
                "scripts.world_map_navigation_bluestacks._ocr_hits",
                return_value=[
                    ("Home", (20, 1220, 120, 1270)),
                ],
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._visual_candidate_boxes",
                return_value=[search_button, home_button],
            ),
        ):
            missing_hud = recognize_world_frame(
                frame,
                source_frame_sha256="3" * 64,
                evidence_ref="current-native-world.png",
            )
        self.assertEqual(missing_hud.state, WORLD_READY)

    def test_search_menu_requires_visible_categories_without_gas_or_category_binding(
        self,
    ):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        home_button = (20, 1167, 132, 1258)
        category_hits = [
            ("X:299", (290, 110, 350, 145)),
            ("Y:495", (360, 110, 420, 145)),
            ("Home", (20, 1220, 120, 1270)),
            ("Zombie", (180, 300, 300, 340)),
            ("Zombie Lair", (180, 360, 340, 400)),
            ("Food", (180, 420, 250, 460)),
            ("Wood", (180, 480, 260, 520)),
            ("Steel", (180, 540, 270, 580)),
        ]
        with (
            patch(
                "scripts.world_map_navigation_bluestacks._ocr_hits",
                return_value=category_hits,
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._visual_candidate_boxes",
                return_value=[home_button],
            ),
        ):
            result = recognize_world_frame(
                frame,
                source_frame_sha256="4" * 64,
                evidence_ref="current-native-search.png",
            )
        self.assertEqual(result.state, WORLD_SEARCH_OPEN)
        self.assertEqual(result.zoom_identity, "WORLD_ZOOM_UNKNOWN")
        self.assertEqual(result.zoom_evidence, ())
        self.assertEqual(result.localization_evidence, ())
        self.assertNotIn("food", result.controls)
        self.assertNotIn("wood", result.controls)
        self.assertNotIn("steel", result.controls)
        self.assertNotIn("zombie", result.controls)

        gas_only = [
            ("X:299", (290, 110, 350, 145)),
            ("Y:495", (360, 110, 420, 145)),
            ("Home", (20, 1220, 120, 1270)),
            ("Zombie", (180, 300, 300, 340)),
            ("Gas", (180, 360, 250, 400)),
        ]
        with (
            patch(
                "scripts.world_map_navigation_bluestacks._ocr_hits",
                return_value=gas_only,
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._visual_candidate_boxes",
                return_value=[home_button],
            ),
        ):
            gas_result = recognize_world_frame(
                frame,
                source_frame_sha256="5" * 64,
                evidence_ref="current-native-search.png",
            )
        self.assertEqual(gas_result.state, "UNKNOWN")

    def test_retained_search_menu_recognizes_without_footer_binding(self):
        source = (
            ROOT
            / ".local-captures"
            / "development-sessions"
            / "observe-20260816T064109887154Z"
            / "observe.png"
        )
        self.assertTrue(
            source.is_file(), f"required Search menu frame absent: {source}"
        )
        raw = source.read_bytes()
        frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        result = recognize_world_frame(
            frame,
            source_frame_sha256=hashlib.sha256(raw).hexdigest(),
            evidence_ref=str(source),
        )
        self.assertEqual(result.state, WORLD_SEARCH_OPEN)
        self.assertEqual(result.controls, {})
        self.assertEqual(result.zoom_evidence, ())
        self.assertEqual(result.localization_evidence, ())

    def test_lone_zombie_lair_menu_hit_fails_closed(self):
        self.assertEqual(
            _world_search_menu_evidence([("Zombie Lair", (180, 300, 340, 340))]),
            (),
        )

    def test_duplicate_category_hits_at_one_roi_fail_closed(self):
        roi = (180, 300, 300, 340)
        self.assertEqual(
            _world_search_menu_evidence([("Zombie", roi), ("Food", roi)]),
            (),
        )

    def test_zombie_lair_and_food_at_distinct_rois_recognize_menu(self):
        evidence = _world_search_menu_evidence(
            [
                ("Zombie Lair", (180, 300, 340, 340)),
                ("Food", (180, 360, 250, 400)),
            ]
        )
        self.assertIn("visible Search category semantics", evidence)
        self.assertIn("Search category: zombie lair", evidence)
        self.assertIn("Search category: food", evidence)

    def test_hud_only_world_route_accepts_unknown_zoom_without_extra_inputs(self):
        frames = route_frames()
        for value in frames:
            if value["state"] in {"WORLD_READY", "WORLD_SEARCH_OPEN"}:
                value["zoom_identity"] = "WORLD_ZOOM_UNKNOWN"
                value.pop("zoom_evidence", None)
                value.pop("localization_evidence", None)
        runtime = FakeRuntime(frames)
        result = run_world_map_navigation(
            runtime,
            recognizer=scripted_recognizer,
            maximum_inputs=4,
        )
        self.assertEqual(result["status"], NAVIGATION_ONLY_COMPLETE)
        self.assertEqual(result["navigation_input_count"], 4)
        self.assertEqual(
            [call[1].get("target_identity", "android-back") for call in runtime.calls],
            [
                "home-to-world",
                "world-search-entry",
                "android-back",
                "world-to-home",
            ],
        )

    def test_world_recovery_binds_home_without_atlas_authority(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        home_button = (20, 1167, 128, 1258)
        with (
            patch(
                "scripts.world_map_navigation_bluestacks._ocr_hits",
                return_value=[
                    ("X:299", (290, 70, 360, 115)),
                    ("Home", (18, 1232, 148, 1277)),
                ],
            ),
            patch(
                "scripts.world_map_navigation_bluestacks._visual_candidate_boxes",
                return_value=[home_button],
            ),
        ):
            result = recognize_world_home_recovery(
                frame,
                source_frame_sha256="f" * 64,
                evidence_ref="current-world-recovery-frame.png",
            )
        self.assertEqual(result.state, "WORLD_READY")
        self.assertEqual(result.controls["world-to-home"], home_button)
        self.assertNotEqual(result.zoom_identity, WORLD_ZOOM_SUPPORTED)
        self.assertEqual(result.zoom_evidence, ())
        self.assertEqual(result.localization_evidence, ())


if __name__ == "__main__":
    unittest.main()
