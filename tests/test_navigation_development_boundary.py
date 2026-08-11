"""Focused offline tests for the flow-agnostic navigation-development boundary."""

from __future__ import annotations

import multiprocessing
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from safe_action_core import SafetyStore
from scripts.bluestacks_flow_collector import EXPECTED_PACKAGE
from scripts.bluestacks_native_runtime import CapturedNativeFrame, NATIVE_RUNTIME_PROFILE_ID
from scripts import navigation_development_boundary as boundary
from scripts.navigation_development_boundary import (
    NavigationBoundaryError,
    NavigationDevelopmentSession,
    NavigationGuardedRuntime,
    NavigationRouteDeclaration,
    RuntimeInputLock,
    SourceStateSafetyFacts,
    authorize_navigation_gesture,
    finalize_navigation_evidence,
    make_source_safety_facts,
    require_canonical_unresolved_clear,
    require_fixed_orchestrator_path,
)


def _declaration(**overrides) -> NavigationRouteDeclaration:
    payload = {
        "allowed_source_states": frozenset({"HOME_BASE", "DESTINATION_MENU"}),
        "allowed_target_identities": frozenset(
            {"building.target", "system-back", "home-camera-click-drag", "home-zoom-out"}
        ),
        "allowed_gesture_classes": frozenset({"tap", "swipe", "back", "zoom_out"}),
    }
    payload.update(overrides)
    return NavigationRouteDeclaration(**payload)


def _facts(**overrides) -> SourceStateSafetyFacts:
    now = time.monotonic()
    payload = {
        "recognized": True,
        "source_state": "HOME_BASE",
        "overlay_state": "none_observed",
        "manual_required": False,
        "hard_stop": False,
        "unknown_state": False,
        "runtime_profile_id": NATIVE_RUNTIME_PROFILE_ID,
        "foreground_package": EXPECTED_PACKAGE,
        "device_state": "device",
        "frame_width": 800,
        "frame_height": 1280,
        "frame_sha256": "a" * 64,
        "captured_monotonic": now,
        "now_monotonic": now,
        "target_roi": (10, 20, 30, 40),
    }
    payload.update(overrides)
    return SourceStateSafetyFacts(**payload)


def _frame(*, width: int = 800, height: int = 1280, captured_monotonic: float | None = None) -> CapturedNativeFrame:
    frame = np.zeros((height, width, 3), np.uint8)
    stamp = time.monotonic() if captured_monotonic is None else float(captured_monotonic)
    payload = f"frame-{stamp}".encode()
    import hashlib

    return CapturedNativeFrame(
        frame,
        payload,
        hashlib.sha256(payload).hexdigest(),
        stamp,
        Path(f"frame-{stamp}.png"),
    )


def _hold_lock(path: str, ready: multiprocessing.Event, release: multiprocessing.Event) -> None:
    boundary.RUNTIME_INPUT_LOCK_PATH = Path(path)
    lock = RuntimeInputLock(owner="peer", invocation_id="peer-1")
    lock.acquire()
    ready.set()
    release.wait(timeout=30)
    lock.release()


class FakeInnerRuntime:
    execute = True
    in_flight_action = None
    session = Path("synthetic-session")

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._device_state = "device"
        self._foreground_package = EXPECTED_PACKAGE

    def measure_device_state(self) -> str:
        return self._device_state

    def measure_foreground_package(self) -> str:
        return self._foreground_package

    def capture(self, label: str):
        raise AssertionError("capture unused")

    def tap(self, source, **kwargs):
        self.calls.append(("tap", kwargs))

    def swipe(self, source, **kwargs):
        self.calls.append(("swipe", kwargs))

    def back(self, source, **kwargs):
        self.calls.append(("back", kwargs))

    def long_press(self, *args, **kwargs):
        self.calls.append(("long_press", kwargs))

    def type_text(self, *args, **kwargs):
        self.calls.append(("type_text", kwargs))

    def clear_numeric_text(self, *args, **kwargs):
        self.calls.append(("clear_numeric", kwargs))

    def press_key(self, *args, **kwargs):
        self.calls.append(("press_key", kwargs))

    def reconcile(self, *args, **kwargs):
        return None

    def record_recovery(self, **kwargs):
        return None


class NavigationDevelopmentBoundaryTests(unittest.TestCase):
    def test_shared_source_has_no_task_specific_identifiers(self) -> None:
        source = Path(boundary.__file__).read_text(encoding="utf-8").lower()
        for needle in ("nova", "research lab", "praise"):
            self.assertNotIn(needle, source)
        self.assertNotRegex(source, r"\bresearch_lab\b")
        self.assertNotRegex(source, r"\bpraise\b")
        self.assertNotRegex(source, r"\bnova\b")

    def test_declaration_validation_rejects_bad_contracts(self) -> None:
        with self.assertRaisesRegex(NavigationBoundaryError, "allowed_source_states"):
            _declaration(allowed_source_states=frozenset()).validate()
        with self.assertRaisesRegex(NavigationBoundaryError, "navigation_only"):
            _declaration(consequence_class="consequential").validate()
        with self.assertRaisesRegex(NavigationBoundaryError, "forbidden gesture"):
            _declaration(allowed_gesture_classes=frozenset({"tap", "long_press"})).validate()

    def test_lock_contention_and_normal_exceptional_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lock.sqlite3"
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", path):
                first = RuntimeInputLock(owner="a", invocation_id="a1")
                first.acquire()
                self.assertTrue(first.held)
                second = RuntimeInputLock(owner="b", invocation_id="b1")
                with self.assertRaisesRegex(NavigationBoundaryError, "held by another owner"):
                    second.acquire()
                first.release()
                self.assertFalse(first.held)
                second.acquire()
                second.release()

                boom = RuntimeInputLock(owner="c", invocation_id="c1")
                boom.acquire()
                try:
                    raise RuntimeError("boom")
                except RuntimeError:
                    boom.release()
                third = RuntimeInputLock(owner="d", invocation_id="d1")
                third.acquire()
                third.release()

    def test_cross_process_lock_contention(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "cross.sqlite3")
            ready = multiprocessing.Event()
            release = multiprocessing.Event()
            peer = multiprocessing.Process(target=_hold_lock, args=(path, ready, release))
            peer.start()
            self.assertTrue(ready.wait(timeout=10))
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", Path(path)):
                local = RuntimeInputLock(owner="local", invocation_id="local-1")
                with self.assertRaisesRegex(NavigationBoundaryError, "held by another owner"):
                    local.acquire()
            release.set()
            peer.join(timeout=10)
            self.assertEqual(peer.exitcode, 0)
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", Path(path)):
                local = RuntimeInputLock(owner="local", invocation_id="local-1")
                local.acquire()
                local.release()

    def test_fixed_lock_and_action_store_paths_reject_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            other = Path(directory) / "other.sqlite3"
            with self.assertRaisesRegex(NavigationBoundaryError, "exactly"):
                require_fixed_orchestrator_path(
                    other,
                    boundary.RUNTIME_INPUT_LOCK_PATH,
                    "runtime input lock",
                )
            with self.assertRaisesRegex(NavigationBoundaryError, "exactly"):
                require_fixed_orchestrator_path(
                    other,
                    boundary.CANONICAL_ACTION_STORE_PATH,
                    "canonical action store",
                )

    def _try_symlink(self, link: Path, target: Path, *, target_is_directory: bool = False) -> None:
        try:
            link.symlink_to(target, target_is_directory=target_is_directory)
        except OSError as exc:
            winerror = getattr(exc, "winerror", None)
            if winerror == 1314 or isinstance(exc, NotImplementedError):
                self.skipTest("OS cannot create symlink for this test")
            # Privilege / platform refusal — skip rather than fail CI without symlink rights.
            if winerror is not None or "symbolic link" in str(exc).lower():
                self.skipTest(f"OS cannot create symlink for this test: {exc}")
            raise

    def test_fixed_paths_reject_symlinks_at_lock_and_action_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real_lock = root / "real-lock.sqlite3"
            real_actions = root / "real-actions.sqlite3"
            real_lock.write_bytes(b"lock")
            real_actions.write_bytes(b"actions")
            lock_link = root / "bluestacks-runtime-input-lock.sqlite3"
            actions_link = root / "bluestacks-actions.sqlite3"
            self._try_symlink(lock_link, real_lock)
            self._try_symlink(actions_link, real_actions)
            with self.assertRaisesRegex(NavigationBoundaryError, "symlink"):
                require_fixed_orchestrator_path(
                    lock_link,
                    lock_link,
                    "runtime input lock",
                )
            with self.assertRaisesRegex(NavigationBoundaryError, "symlink"):
                require_fixed_orchestrator_path(
                    actions_link,
                    actions_link,
                    "canonical action store",
                )

            real_parent = root / "real-parent"
            real_parent.mkdir()
            (real_parent / "nested.sqlite3").write_bytes(b"x")
            linked_parent = root / "linked-parent"
            self._try_symlink(linked_parent, real_parent, target_is_directory=True)
            nested = linked_parent / "nested.sqlite3"
            with self.assertRaisesRegex(NavigationBoundaryError, "symlink"):
                require_fixed_orchestrator_path(
                    nested,
                    nested,
                    "runtime input lock",
                )

    def test_canonical_unresolved_action_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store_path = Path(directory) / "actions.sqlite3"
            with patch.object(boundary, "CANONICAL_ACTION_STORE_PATH", store_path):
                store = SafetyStore(store_path)
                try:
                    store.connection.execute(
                        """
                        INSERT INTO actions(
                            action_id, action_key, task_id, semantic_action, source_state,
                            target_identity, target_roi_json, source_frame_sha256,
                            source_frame_captured_at, runtime_profile_id, game_day_id,
                            expected_postcondition, consequence, cost_type, cost_amount,
                            quantity, consequential, policy_request_json, policy_decision,
                            policy_reason, prepared_at, evidence_refs_json, final_status, updated_at
                        ) VALUES (
                            'block-1', 'block:1', 'synthetic', 'synthetic', 'HOME_BASE',
                            'synthetic', '[1,2,3,4]', ?, 1.0, ?, NULL,
                            'done', 'synthetic', 'none', 0, 1, 1, '{}', 'allow',
                            'seed', 1.0, '[]', 'prepared', 1.0
                        )
                        """,
                        ("b" * 64, NATIVE_RUNTIME_PROFILE_ID),
                    )
                    store.connection.commit()
                    self.assertTrue(store.has_action_block())
                finally:
                    store.close()
                with self.assertRaisesRegex(NavigationBoundaryError, "canonical unresolved"):
                    require_canonical_unresolved_clear()

                lock_path = Path(directory) / "runtime-lock.sqlite3"
                with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", lock_path):
                    with NavigationDevelopmentSession(owner="development", invocation_id="dev-1"):
                        self.assertTrue(lock_path.is_file())

    def test_missing_delivery_metadata_irrelevant_to_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock_path = root / "lock.sqlite3"
            actions = root / "actions.sqlite3"
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", lock_path):
                with patch.object(boundary, "CANONICAL_ACTION_STORE_PATH", actions):
                    with NavigationDevelopmentSession(owner="dev", invocation_id="dev-1"):
                        self.assertTrue(lock_path.is_file())

    def test_source_safety_denials(self) -> None:
        declaration = _declaration()
        cases = [
            ("unknown", {"unknown_state": True}),
            ("manual_required", {"manual_required": True}),
            ("hard_stop", {"hard_stop": True}),
            ("overlay", {"overlay_state": "modal"}),
            ("profile", {"runtime_profile_id": "wrong"}),
            ("package", {"foreground_package": "other.package"}),
            (
                "stale",
                {"captured_monotonic": time.monotonic() - 120, "now_monotonic": time.monotonic()},
            ),
            ("bounds", {"target_roi": (-1, 0, 10, 10)}),
            ("undeclared source", {"source_state": "UNKNOWN_SCREEN"}),
        ]
        for label, overrides in cases:
            with self.subTest(label):
                with self.assertRaises(NavigationBoundaryError):
                    authorize_navigation_gesture(
                        declaration=declaration,
                        facts=_facts(**overrides),
                        gesture_class="tap",
                        target_identity="building.target",
                    )

    def test_undeclared_target_gesture_and_consequential_denials(self) -> None:
        declaration = _declaration()
        facts = _facts()
        with self.assertRaisesRegex(NavigationBoundaryError, "undeclared target"):
            authorize_navigation_gesture(
                declaration=declaration,
                facts=facts,
                gesture_class="tap",
                target_identity="not-declared",
            )
        with self.assertRaisesRegex(NavigationBoundaryError, "undeclared gesture"):
            authorize_navigation_gesture(
                declaration=declaration,
                facts=facts,
                gesture_class="pinch",
                target_identity="building.target",
            )
        with self.assertRaisesRegex(NavigationBoundaryError, "consequential"):
            authorize_navigation_gesture(
                declaration=declaration,
                facts=facts,
                gesture_class="tap",
                target_identity="building.target",
                consequential=True,
            )

    def test_live_measurement_overrides_adapter_and_mismatches_deny_zero_transport(self) -> None:
        inner = FakeInnerRuntime()
        guarded = NavigationGuardedRuntime(inner, _declaration())
        source = _frame()
        # Adapter lies about package/device/profile/dims; live bind must overwrite then deny.
        guarded.prepare_source_safety(
            make_source_safety_facts(
                recognized=True,
                source_state="HOME_BASE",
                frame_sha256=source.sha256,
                captured_monotonic=source.captured_monotonic,
                runtime_profile_id="liar-profile",
                foreground_package="liar.package",
                device_state="offline",
                frame_width=1,
                frame_height=1,
            )
        )
        inner._foreground_package = "wrong.package"
        with self.assertRaisesRegex(NavigationBoundaryError, "package"):
            guarded.tap(
                source,
                target_identity="building.target",
                target_roi=(1, 2, 3, 4),
                action_key="k-deny",
            )
        self.assertEqual(inner.calls, [])

        inner._foreground_package = EXPECTED_PACKAGE
        inner._device_state = "offline"
        guarded.prepare_source_safety(
            make_source_safety_facts(
                recognized=True,
                source_state="HOME_BASE",
                frame_sha256=source.sha256,
                captured_monotonic=source.captured_monotonic,
            )
        )
        with self.assertRaisesRegex(NavigationBoundaryError, "device state"):
            guarded.tap(
                source,
                target_identity="building.target",
                target_roi=(1, 2, 3, 4),
                action_key="k-deny-2",
            )
        self.assertEqual(inner.calls, [])

        wrong = _frame(width=400, height=640)
        inner._device_state = "device"
        guarded.prepare_source_safety(
            make_source_safety_facts(
                recognized=True,
                source_state="HOME_BASE",
                frame_sha256=wrong.sha256,
                captured_monotonic=wrong.captured_monotonic,
            )
        )
        with self.assertRaisesRegex(NavigationBoundaryError, "native 800x1280|profile"):
            guarded.tap(
                wrong,
                target_identity="building.target",
                target_roi=(1, 2, 3, 4),
                action_key="k-deny-3",
            )
        self.assertEqual(inner.calls, [])

    def test_guarded_runtime_denies_stale_frame_despite_fresh_adapter_facts(self) -> None:
        inner = FakeInnerRuntime()
        guarded = NavigationGuardedRuntime(inner, _declaration())
        stale = _frame(captured_monotonic=time.monotonic() - 120.0)
        # Adapter claims zero age; live bind must use wall clock and deny without transport.
        guarded.prepare_source_safety(
            make_source_safety_facts(
                recognized=True,
                source_state="HOME_BASE",
                frame_sha256=stale.sha256,
                captured_monotonic=stale.captured_monotonic,
                now_monotonic=stale.captured_monotonic,
            )
        )
        with self.assertRaisesRegex(NavigationBoundaryError, "stale"):
            guarded.tap(
                stale,
                target_identity="building.target",
                target_roi=(1, 2, 3, 4),
                action_key="k-stale",
            )
        self.assertEqual(inner.calls, [])
        self.assertEqual(guarded.authorized_gestures, [])

    def test_guarded_runtime_rejects_forbidden_methods_and_requires_facts(self) -> None:
        inner = FakeInnerRuntime()
        guarded = NavigationGuardedRuntime(inner, _declaration())
        source = _frame()
        with self.assertRaisesRegex(NavigationBoundaryError, "source safety facts"):
            guarded.tap(
                source,
                target_identity="building.target",
                target_roi=(1, 2, 3, 4),
                action_key="k1",
            )
        with self.assertRaisesRegex(NavigationBoundaryError, "long_press"):
            guarded.long_press()
        with self.assertRaisesRegex(NavigationBoundaryError, "type_text"):
            guarded.type_text()
        with self.assertRaisesRegex(NavigationBoundaryError, "press_key"):
            guarded.press_key()
        guarded.prepare_source_safety(
            make_source_safety_facts(
                recognized=True,
                source_state="HOME_BASE",
                frame_sha256=source.sha256,
                captured_monotonic=source.captured_monotonic,
            )
        )
        with self.assertRaisesRegex(NavigationBoundaryError, "consequential"):
            guarded.tap(
                source,
                target_identity="building.target",
                target_roi=(1, 2, 3, 4),
                action_key="k1",
                consequential=True,
            )
        guarded.prepare_source_safety(
            make_source_safety_facts(
                recognized=True,
                source_state="HOME_BASE",
                frame_sha256=source.sha256,
                captured_monotonic=source.captured_monotonic,
            )
        )
        guarded.tap(
            source,
            target_identity="building.target",
            target_roi=(1, 2, 3, 4),
            action_key="k1",
            consequential=False,
        )
        self.assertEqual(inner.calls[0][0], "tap")
        self.assertFalse(inner.calls[0][1]["consequential"])
        self.assertTrue(guarded.authorized_gestures[0]["authorized"])
        self.assertTrue(guarded.authorized_gestures[0]["transport_observed"])

    def test_zoom_auth_failure_never_transports_and_failed_transport_not_observed(self) -> None:
        inner = FakeInnerRuntime()
        guarded = NavigationGuardedRuntime(inner, _declaration())
        source = _frame()
        transported = {"count": 0}

        def boom():
            transported["count"] += 1
            raise RuntimeError("host zoom failed")

        with self.assertRaisesRegex(RuntimeError, "host zoom failed"):
            guarded.dispatch_zoom_out(
                source,
                make_source_safety_facts(
                    recognized=True,
                    source_state="HOME_BASE",
                    frame_sha256=source.sha256,
                    captured_monotonic=source.captured_monotonic,
                ),
                transport=boom,
            )
        self.assertEqual(transported["count"], 1)
        self.assertTrue(guarded.authorized_gestures[-1]["authorized"])
        self.assertFalse(guarded.authorized_gestures[-1]["transport_observed"])

        # Authorization denial never reaches transport.
        transported["count"] = 0
        inner._device_state = "offline"
        with self.assertRaisesRegex(NavigationBoundaryError, "device state"):
            guarded.dispatch_zoom_out(
                source,
                make_source_safety_facts(
                    recognized=True,
                    source_state="HOME_BASE",
                    frame_sha256=source.sha256,
                    captured_monotonic=source.captured_monotonic,
                ),
                transport=boom,
            )
        self.assertEqual(transported["count"], 0)

    def test_zoom_uses_guarded_native_transport_when_not_injected(self) -> None:
        inner = FakeInnerRuntime()
        inner.zoom_out = lambda source, *, action_key: inner.calls.append(
            ("zoom_out", {"source": source, "action_key": action_key})
        )
        guarded = NavigationGuardedRuntime(inner, _declaration())
        source = _frame()

        guarded.dispatch_zoom_out(
            source,
            make_source_safety_facts(
                recognized=True,
                source_state="HOME_BASE",
                frame_sha256=source.sha256,
                captured_monotonic=source.captured_monotonic,
            ),
        )

        self.assertEqual(inner.calls[0][0], "zoom_out")
        self.assertEqual(inner.calls[0][1]["source"], source)
        self.assertTrue(inner.calls[0][1]["action_key"].startswith("home-zoom-out:"))
        self.assertTrue(guarded.authorized_gestures[-1]["transport_observed"])

    def test_finalizer_preserves_invalid_status_and_exception_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "session"
            blocked = finalize_navigation_evidence(
                session,
                status="blocked",
                reason="synthetic_block",
                records=({"action": "tap", "source_sha256": "a", "successor_sha256": "b"},),
                flow_id="FLOW-A",
                scenario_id="scenario_a",
            )
            self.assertEqual(blocked["status"], "blocked")
            self.assertTrue((session / "result.json").is_file())

            session2 = Path(directory) / "session-ex"
            failed = finalize_navigation_evidence(
                session2,
                status="completed",
                reason="ignored",
                exception=RuntimeError("explode"),
            )
            self.assertEqual(failed["status"], "failed")
            audit = (session2 / "capability-audit.jsonl").read_text(encoding="utf-8")
            self.assertIn("RuntimeError", audit)

            session3 = Path(directory) / "session-invalid"
            invalid = finalize_navigation_evidence(
                session3,
                status="weird_status",
                reason="caller_reason",
            )
            self.assertEqual(invalid["status"], "blocked")
            self.assertIn("invalid_terminal_status:weird_status", invalid["reason"])
            self.assertIn("caller_reason", invalid["reason"])

    def test_finalizer_does_not_synthesize_authorized_transport_from_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "session"
            finalize_navigation_evidence(
                session,
                status="completed",
                reason="route_ok",
                records=(
                    {
                        "action": "tap",
                        "source_sha256": "a" * 64,
                        "successor_sha256": "b" * 64,
                        "target_identity": "building.target",
                    },
                ),
                authorized_gestures=(),
            )
            ledger = (session / "ledger.jsonl").read_text(encoding="utf-8")
            self.assertIn("building.target", ledger)
            audit_text = (session / "capability-audit.jsonl").read_text(encoding="utf-8").strip()
            self.assertEqual(audit_text, "")
            self.assertNotIn("transport_observed", audit_text)
            self.assertNotIn('"authorized": true', audit_text.lower())

    def test_bluestacks_run_flow_live_acquires_shared_session_before_admission(self) -> None:
        import scripts.pnsctl as pnsctl

        order: list[str] = []

        class FakeSession:
            def __init__(self, **kwargs):
                order.append("session_init")

            def __enter__(self):
                order.append("session_enter")
                return self

            def __exit__(self, exc_type, exc, tb):
                order.append("session_exit")
                return False

        with patch.object(pnsctl, "BLUESTACKS_FLOW_IDS", ("FLOW-X",)):
            with patch.object(
                pnsctl,
                "_load_bluestacks_flow_registry",
                return_value={"FLOW-X": {"runner": "runner-x"}},
            ):
                with patch.dict(pnsctl._BLUESTACKS_FLOW_RUNNERS, {"runner-x": lambda q, l: "ok"}):
                    with patch(
                        "scripts.navigation_development_boundary.NavigationDevelopmentSession",
                        FakeSession,
                    ):
                        with patch.object(
                            pnsctl,
                            "_load_flow_delivery_state",
                            side_effect=lambda: (
                                order.append("admission")
                                or (
                                    {
                                        "active_flow_id": "FLOW-X",
                                        "flows": [
                                            {
                                                "flow_id": "FLOW-X",
                                                "last_completed_stage": "live_execution",
                                            }
                                        ],
                                    },
                                    {"workflow": "pns-flow-delivery"},
                                )
                            ),
                        ):
                            result = pnsctl.bluestacks_run_flow("FLOW-X", live=True)
        self.assertEqual(result, "ok")
        self.assertEqual(order[0], "session_init")
        self.assertEqual(order[1], "session_enter")
        self.assertIn("admission", order)
        self.assertLess(order.index("session_enter"), order.index("admission"))


if __name__ == "__main__":
    unittest.main()
