from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import shutil
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from safe_action_core import SafetyStore
from safe_action_core.models import TransportResult
from safe_action_core.resource_effect_authority import (
    ResourceFenceError,
    ResourceOccurrenceIdentity,
    ResourceResetIdentity,
)
from scripts import daily_row_claim_bluestacks as daily
from scripts import navigation_development_boundary as boundary
from scripts import daily_resource_item_bluestacks as route
from scripts import flow_delivery_daily_resource_item_bluestacks as delivery
from scripts import pnsctl
from scripts.evidence_hygiene import sha256_stream
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.navigation_development_boundary import DevelopmentSession
from tasks.runtime_identity import (
    FixedRuntimeBinding,
    ResourceIdentityEvidence,
    RuntimeIdentityConfiguration,
    derive_fixed_runtime_binding,
    produce_resource_runtime_identity,
)


REPO = Path(__file__).resolve().parents[1]
LIVE_FRAMES = (
    REPO
    / ".local-captures"
    / "development-sessions"
    / "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION-20260819T042658331966Z"
    / "runtime"
    / "daily-resource-item-20260819T042658970087Z-20260819T042659055847Z"
    / "frames"
)


def _digest(path: Path) -> str:
    digest, _size = sha256_stream(path)
    return digest


def _frame_ref(path: Path) -> dict[str, object]:
    return {"path": path.as_posix(), "sha256": _digest(path)}


def _copy_into(session: Path, source: Path, name: str) -> Path:
    target = session / "frames" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def _write_blank_native(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = np.zeros((1280, 800, 3), dtype=np.uint8)
    cv2.imwrite(str(path), image)
    return path


class DailyResourceItemDeliveryTests(unittest.TestCase):
    def _resource_identity(self):
        binding = pnsctl._resource_fixed_runtime_binding()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        deadline = now + timedelta(hours=6)
        deadline_utc = deadline.isoformat().replace("+00:00", "Z")
        observed_utc = now.isoformat().replace("+00:00", "Z")
        expires_utc = (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        deadline_identity = f"reset-deadline:{deadline_utc}"
        deadline_evidence = {
            "displayed_timer": "06:00:00",
            "reset_timer_seconds": 21600,
            "observed_utc": observed_utc,
            "normalized_deadline_utc": deadline_utc,
            "deadline_identity": deadline_identity,
            "machine_observed": True,
            "daily_frame": {
                "path": "test-frame.png",
                "sha256": "0" * 64,
                "captured_utc": observed_utc,
                "observed_utc": observed_utc,
            },
            "tolerance_seconds": 2,
            "recurrence_class": "daily_reset",
        }
        base = ResourceIdentityEvidence(
            account_id=binding.account_id,
            server_id=binding.server_id,
            reset_id=deadline_identity,
            evidence_refs=("test:account-server-reset",),
            observed_utc=observed_utc,
            expires_utc=expires_utc,
            content_digest="0" * 64,
            runtime_scope=binding.runtime_scope,
            runtime_binding_digest=binding.binding_digest,
        )
        evidence = replace(base, content_digest=base.computed_digest())
        identity = produce_resource_runtime_identity(
            RuntimeIdentityConfiguration(
                binding.runtime_scope,
                binding.account_id,
                binding.server_id,
                deadline_identity,
            ),
            evidence,
            deadline_evidence,
            now,
            binding,
        )
        return identity, deadline_evidence

    def _produce_identity_session(
        self,
        capture_root: Path,
        *,
        selected_daily: bool = True,
        reset_matches: bool = True,
        reset_seconds: int = 21600,
        expect_failure: bool = False,
    ) -> tuple[dict[str, object], Path, str, list[tuple[tuple[int, ...], object, object]]]:
        fixed_now = datetime.now(timezone.utc).replace(microsecond=0)
        deadline = fixed_now + timedelta(seconds=reset_seconds)
        deadline_utc = deadline.isoformat().replace("+00:00", "Z")
        derived_reset_id = f"reset-deadline:{deadline_utc}"
        configured_reset_id = (
            derived_reset_id
            if reset_matches
            else "reset-deadline:2026-08-20T19:00:00Z"
        )
        frame = np.full((1280, 800, 3), (20, 40, 60), dtype=np.uint8)
        encoded_ok, encoded = cv2.imencode(".png", frame)
        self.assertTrue(encoded_ok)
        frame_bytes = encoded.tobytes()
        frame_digest = hashlib.sha256(frame_bytes).hexdigest()
        recognizer_calls: list[tuple[tuple[int, ...], object, object]] = []

        class FakeRecognizer:
            def recognize_daily_claim(
                self,
                image: np.ndarray,
                *,
                game_day_id=None,
                observed_utc=None,
            ):
                recognizer_calls.append((tuple(image.shape), game_day_id, observed_utc))
                observed = observed_utc.astimezone(timezone.utc)
                observed_text = observed.isoformat().replace("+00:00", "Z")
                deadline_text = (
                    observed + timedelta(seconds=reset_seconds)
                ).isoformat().replace("+00:00", "Z")
                visual = {
                    "selected_daily": selected_daily,
                    "runtime_profile_id": daily.BLUESTACKS_RUNTIME_PROFILE_ID,
                    "reset_timer": str(timedelta(seconds=reset_seconds)),
                    "reset_timer_seconds": reset_seconds,
                    "reset_observed_utc": observed_text,
                    "reset_deadline_utc": deadline_text,
                    "reset_deadline_identity": (
                        f"reset-deadline:{deadline_text}"
                        if reset_matches
                        else f"wrong-reset:{deadline_text}"
                    ),
                    "reset_deadline_tolerance_seconds": 2,
                }
                return daily.FrameRecognition(
                    state=(
                        daily.DAILY_SELECTED_STATE
                        if selected_daily
                        else daily.UNKNOWN_STATE
                    ),
                    recognized=selected_daily,
                    visual_evidence=visual,
                )

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_now if tz is None else fixed_now.astimezone(tz)

        observation = {
            "device_state": "device",
            "foreground_package": pnsctl.PACKAGE,
            "native_width": 800,
            "native_height": 1280,
            "frame_sha256": frame_digest,
        }
        invocation = (
            "resource-identity-observe-"
            + fixed_now.strftime("%Y%m%dT%H%M%S%fZ")
        )
        session_directory = capture_root / invocation
        with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", capture_root / "lock.sqlite3"):
            with patch.object(pnsctl, "DEVELOPMENT_SESSION_ROOT", capture_root):
                with patch.object(pnsctl, "datetime", FixedDateTime):
                    with patch.object(
                        pnsctl,
                        "_development_runtime_observation",
                        return_value=(observation, frame_bytes),
                    ) as runtime_observation:
                        with patch.object(
                            daily,
                            "DailyRowClaimRecognizer",
                            return_value=FakeRecognizer(),
                        ):
                            try:
                                output = json.loads(
                                    pnsctl.development_session_resource_identity_observe()
                                )
                            except pnsctl.OperatorError:
                                if not expect_failure:
                                    raise
                                output = {}
                            self.assertEqual(runtime_observation.call_count, 1)
        return output, session_directory, configured_reset_id, recognizer_calls

    def test_resource_identity_receipt_clips_ttl_to_near_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            output, _session, _reset_id, _calls = self._produce_identity_session(
                Path(tmp),
                reset_seconds=30,
            )
            receipt = json.loads(
                Path(str(output["receipt_path"])).read_text(encoding="utf-8")
            )
        self.assertEqual(
            receipt["expires_utc"],
            receipt["current_reset_deadline_evidence"]["normalized_deadline_utc"],
        )

    def test_resource_identity_observation_rejects_too_close_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            output, _session, _reset_id, calls = self._produce_identity_session(
                Path(tmp),
                reset_seconds=1,
                expect_failure=True,
            )
        self.assertEqual(output, {})
        self.assertEqual(len(calls), 1)

    def test_resource_reset_boundary_denies_before_store_open(self):
        identity, deadline_evidence = self._resource_identity()
        observed = datetime.fromisoformat(
            deadline_evidence["observed_utc"].replace("Z", "+00:00")
        )
        deadline = datetime.fromisoformat(
            deadline_evidence["normalized_deadline_utc"].replace("Z", "+00:00")
        )
        initial_evaluation = observed + timedelta(seconds=1)
        for label, current in (
            ("exact-reset", deadline),
            ("after-reset", deadline + timedelta(seconds=1)),
            (
                "safety-margin",
                deadline
                - timedelta(
                    seconds=delivery.RESOURCE_DISPATCH_SAFETY_MARGIN_SECONDS
                ),
            ),
        ):
            with self.subTest(label=label):
                expired_payload = dict(
                    deadline_evidence,
                    _evaluated_utc=initial_evaluation.isoformat().replace(
                        "+00:00", "Z"
                    ),
                )
                store_open = Mock(side_effect=AssertionError("store must not open"))
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    with patch.object(
                        boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"
                    ):
                        with patch.object(pnsctl, "_open_admitted_resource_store", store_open):
                            with DevelopmentSession(
                                owner="pnsctl-reset-boundary-owner",
                                invocation_id=f"pnsctl-reset-boundary-{label}",
                                session_directory=root / "session",
                                max_inputs=1,
                            ) as session:
                                with self.assertRaisesRegex(
                                    pnsctl.OperatorError,
                                    "before Resource SafetyStore open",
                                ):
                                    pnsctl._build_resource_runtime_components(
                                        session=session,
                                        verified_identity=identity,
                                        deadline_payload=expired_payload,
                                        store_path=root / "actions.sqlite3",
                                        store_factory=lambda path: SafetyStore(path),
                                        wall_clock=lambda: current,
                                    )
                                self.assertEqual(session.input_count, 0)
                store_open.assert_not_called()

    def test_resource_dispatch_window_rejects_naive_timestamps(self):
        observed = datetime(2026, 8, 20, 10, tzinfo=timezone.utc)
        deadline = observed + timedelta(hours=1)
        window = delivery.ResourceDispatchWindow(
            reset_deadline_utc=deadline,
            receipt_expires_utc=deadline,
        )
        with self.assertRaises(delivery.ResourceDispatchWindowError):
            window.require_current(datetime(2026, 8, 20, 10, 0, 1))
        with self.assertRaises(delivery.ResourceDispatchWindowError):
            delivery.ResourceDispatchWindow(
                reset_deadline_utc=datetime(2026, 8, 20, 11),
                receipt_expires_utc=deadline,
            )

    def test_resource_dispatch_window_denies_exact_and_margin_boundaries(self):
        observed = datetime(2026, 8, 20, 10, tzinfo=timezone.utc)
        deadline = observed + timedelta(hours=1)
        window = delivery.ResourceDispatchWindow(
            reset_deadline_utc=deadline,
            receipt_expires_utc=deadline,
        )
        for current in (
            deadline,
            deadline - window.safety_margin,
        ):
            with self.subTest(current=current):
                with self.assertRaises(delivery.ResourceDispatchWindowError):
                    window.require_current(current)
        self.assertEqual(
            window.require_current(
                deadline - window.safety_margin - timedelta(microseconds=1)
            ),
            deadline - window.safety_margin - timedelta(microseconds=1),
        )

    def test_pnsctl_builds_resource_bundle_inside_same_session_lock(self):
        identity, deadline_evidence = self._resource_identity()
        dispatch_now = datetime.fromisoformat(
            deadline_evidence["observed_utc"].replace("Z", "+00:00")
        ) + timedelta(seconds=10)

        class Inner:
            execute = True
            frame_max_age_seconds = 30.0
            input_count = 0
            session = Path("inner-session")

            def __init__(self):
                self.dispatch_calls = 0
                self.result = None

            def dispatch_prepared_resource_item_use(self, *args, **kwargs):
                self.dispatch_calls += 1
                if self.result is None:
                    raise AssertionError("wrong-frame regression must stop before native dispatch")
                return self.result

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "actions.sqlite3"
            seed = SafetyStore(store_path)
            seed.close()
            lock_path = root / "runtime-lock.sqlite3"
            session_path = root / "session"
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", lock_path):
                with DevelopmentSession(
                    owner="pnsctl-test-owner",
                    invocation_id="pnsctl-test-invocation",
                    session_directory=session_path,
                    max_inputs=10,
                ) as session:
                    components = pnsctl._build_resource_runtime_components(
                        session=session,
                        verified_identity=identity,
                        deadline_payload=deadline_evidence,
                        store_path=store_path,
                        store_factory=lambda path: SafetyStore(path),
                        wall_clock=lambda: dispatch_now,
                    )
                    inner = Inner()
                    runtime = components["runtime_factory"](inner)
                    self.assertIs(runtime._runtime_lock, session.runtime_input_lock)
                    self.assertEqual(
                        components["controller_lease"]["owner_id"],
                        session.owner,
                    )
                    frame_bytes = b"\x89PNG\r\n\x1a\nresource-frame"
                    frame = np.full((1280, 800, 3), 20, dtype=np.uint8)
                    source = CapturedNativeFrame(
                        frame=frame,
                        png=frame_bytes,
                        sha256=hashlib.sha256(frame_bytes).hexdigest(),
                        captured_monotonic=time.monotonic(),
                        path=root / "source.png",
                    )
                    bundle = runtime._prepare(
                        source,
                        (100, 100, 140, 140),
                        delivery.ITEM_USE_ACTION_KEY,
                    )
                    runtime._prepared = bundle.prepared
                    runtime._request = bundle.request
                    runtime._capability = bundle.capability
                    runtime._preparation_used = True
                    self.assertEqual(
                        bundle.request.observation.frame_sha256,
                        bundle.prepared.fence.immediate_before_sha256,
                    )
                    self.assertEqual(
                        bundle.request.effect_dispatch_fence,
                        bundle.prepared.fence,
                    )
                    self.assertEqual(
                        bundle.prepared.fence.runtime_invocation_id,
                        session.invocation_id,
                    )
                    db = components["store"].connection
                    claim_id = db.execute(
                        """SELECT claim_id FROM resource_attempt_claims
                           WHERE attempt_id=? AND occurrence_id=? AND reservation_id=?""",
                        (
                            bundle.prepared.attempt_id,
                            bundle.prepared.occurrence_id,
                            bundle.prepared.reservation_id,
                        ),
                    ).fetchone()[0]

                    def resource_state():
                        def rows(query, parameters):
                            return tuple(
                                tuple(row)
                                for row in db.execute(query, parameters).fetchall()
                            )

                        return {
                            "reservation": rows(
                                "SELECT * FROM resource_reservations WHERE reservation_id=?",
                                (bundle.prepared.reservation_id,),
                            ),
                            "attempt": rows(
                                """SELECT * FROM resource_attempts
                                   WHERE attempt_id=? AND occurrence_id=?""",
                                (
                                    bundle.prepared.attempt_id,
                                    bundle.prepared.occurrence_id,
                                ),
                            ),
                            "claim": rows(
                                "SELECT * FROM resource_attempt_claims WHERE claim_id=?",
                                (claim_id,),
                            ),
                            "occurrence": rows(
                                "SELECT * FROM resource_occurrences WHERE occurrence_id=?",
                                (bundle.prepared.occurrence_id,),
                            ),
                            "action": rows(
                                "SELECT * FROM actions WHERE action_id=? AND action_key=?",
                                (
                                    bundle.prepared.action_id,
                                    bundle.prepared.action_key,
                                ),
                            ),
                            "transport_facts": rows(
                                "SELECT * FROM resource_transport_facts WHERE reservation_id=?",
                                (bundle.prepared.reservation_id,),
                            ),
                            "transport_outcomes": rows(
                                "SELECT * FROM resource_transport_outcomes WHERE reservation_id=?",
                                (bundle.prepared.reservation_id,),
                            ),
                        }

                    before_fence_mutations = resource_state()
                    for fence_field, replacement in (
                        (
                            "occurrence_id",
                            f"{bundle.prepared.occurrence_id}:mutated",
                        ),
                        ("attempt_id", f"{bundle.prepared.attempt_id}:mutated"),
                        (
                            "reservation_id",
                            f"{bundle.prepared.reservation_id}:mutated",
                        ),
                        (
                            "reservation_state_revision",
                            bundle.prepared.reservation_state_revision + 1,
                        ),
                    ):
                        with self.subTest(fence_field=fence_field):
                            mutated_fence = replace(
                                bundle.prepared.fence,
                                **{fence_field: replacement},
                            )
                            mutated_prepared = replace(
                                bundle.prepared,
                                fence=mutated_fence,
                            )
                            with self.assertRaises(ResourceFenceError):
                                components["authority"].cancel_prepared_resource_effect(
                                    mutated_prepared,
                                    controller_lease=components["controller_lease"],
                                    runtime_lock=session.runtime_input_lock,
                                    reason="reset_dispatch_window_expired",
                                    now=time.monotonic(),
                                )
                            self.assertEqual(resource_state(), before_fence_mutations)
                            self.assertEqual(inner.dispatch_calls, 0)
                    wrong_png = b"\x89PNG\r\n\x1awrong-frame"
                    wrong = CapturedNativeFrame(
                        frame=frame.copy(),
                        png=wrong_png,
                        sha256=hashlib.sha256(wrong_png).hexdigest(),
                        captured_monotonic=time.monotonic(),
                        path=root / "wrong.png",
                    )
                    with self.assertRaisesRegex(RuntimeError, "source frame"):
                        runtime.dispatch_one_food_use(
                            wrong,
                            target_roi=(100, 100, 140, 140),
                            action_key=delivery.ITEM_USE_ACTION_KEY,
                        )
                    self.assertEqual(inner.dispatch_calls, 0)
                    self.assertIsNone(
                        components["authority"].get_resource_transport(
                            bundle.prepared.reservation_id
                        )
                    )
                    self.assertIsNone(
                        components["authority"].get_resource_transport_outcome(
                            bundle.prepared.reservation_id
                        )
                    )
                    inner.result = TransportResult(False, "NOT_SENT")
                    result = runtime.dispatch_one_food_use(
                        source,
                        target_roi=(100, 100, 140, 140),
                        action_key=delivery.ITEM_USE_ACTION_KEY,
                    )
                    self.assertEqual(result.transport_code, "NOT_SENT")
                    self.assertEqual(inner.dispatch_calls, 1)
                    outcome = components["authority"].get_resource_transport_outcome(
                        bundle.prepared.reservation_id
                    )
                    self.assertIsNotNone(outcome)
                    assert outcome is not None
                    self.assertEqual(outcome["state"], "TRANSPORT_UNKNOWN")
                    self.assertEqual(outcome["adapter_invoked"], 1)
                    self.assertNotEqual(outcome["state"], "RELEASED_NOT_SENT")
                    reservation_state = components["store"].connection.execute(
                        "SELECT state FROM resource_reservations WHERE reservation_id=?",
                        (bundle.prepared.reservation_id,),
                    ).fetchone()[0]
                    self.assertEqual(reservation_state, "TRANSPORT_UNKNOWN")
                    effect_evidence = {
                        "effect_state": "EFFECT_CONFIRMED",
                        "before_owned_quantity": 10,
                        "after_owned_quantity": 9,
                        "evidence_refs": ("test:confirmed-resource-effect",),
                    }
                    components["authority"].reconcile_resource_effect_observe_only(
                        bundle.prepared.reservation_id,
                        effect_evidence,
                        now=time.monotonic(),
                    )
                    self.assertEqual(
                        components["store"].get_action(bundle.prepared.action_id)[
                            "final_status"
                        ],
                        "confirmed",
                    )
                    self.assertFalse(components["store"].has_action_block())
                    components["authority"].reconcile_resource_effect_observe_only(
                        bundle.prepared.reservation_id,
                        effect_evidence,
                        now=time.monotonic(),
                    )
                    self.assertEqual(
                        components["store"].get_action(bundle.prepared.action_id)[
                            "final_status"
                        ],
                        "confirmed",
                    )
                    self.assertIsNotNone(
                        components["store"].connection.execute(
                            "SELECT 1 FROM resource_occurrences"
                        ).fetchone()
                    )
                    with self.assertRaises(Exception):
                        runtime._prepare(
                            source,
                            (100, 100, 140, 140),
                            delivery.ITEM_USE_ACTION_KEY,
                        )
                    components["authority"].release_resource_controller_lease(
                        session.owner,
                        components["controller_lease"]["controller_token"],
                        time.monotonic(),
                    )
                    components["store"].close()

    def test_resource_dispatch_boundary_denies_before_transport_intent(self):
        identity, deadline_evidence = self._resource_identity()
        observed = datetime.fromisoformat(
            deadline_evidence["observed_utc"].replace("Z", "+00:00")
        )
        deadline = datetime.fromisoformat(
            deadline_evidence["normalized_deadline_utc"].replace("Z", "+00:00")
        )
        wall_clock_values = iter((observed + timedelta(seconds=10), deadline))

        class Inner:
            execute = True
            frame_max_age_seconds = 30.0
            input_count = 0
            session = Path("inner-session")

            def __init__(self):
                self.dispatch_calls = 0

            def dispatch_prepared_resource_item_use(self, *args, **kwargs):
                self.dispatch_calls += 1
                raise AssertionError("native adapter must not be invoked")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "actions.sqlite3"
            seed = SafetyStore(store_path)
            seed.close()
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with DevelopmentSession(
                    owner="pnsctl-dispatch-boundary-owner",
                    invocation_id="pnsctl-dispatch-boundary-invocation",
                    session_directory=root / "session",
                    max_inputs=10,
                ) as session:
                    components = pnsctl._build_resource_runtime_components(
                        session=session,
                        verified_identity=identity,
                        deadline_payload=deadline_evidence,
                        store_path=store_path,
                        store_factory=lambda path: SafetyStore(path),
                        wall_clock=lambda: next(wall_clock_values),
                    )
                    inner = Inner()
                    runtime = components["runtime_factory"](inner)
                    frame_bytes = b"\x89PNG\r\n\x1a\nresource-frame"
                    frame = np.full((1280, 800, 3), 20, dtype=np.uint8)
                    source = CapturedNativeFrame(
                        frame=frame,
                        png=frame_bytes,
                        sha256=hashlib.sha256(frame_bytes).hexdigest(),
                        captured_monotonic=time.monotonic(),
                        path=root / "source.png",
                    )
                    bundle = runtime._prepare(
                        source,
                        (100, 100, 140, 140),
                        delivery.ITEM_USE_ACTION_KEY,
                    )
                    runtime._prepared = bundle.prepared
                    runtime._request = bundle.request
                    runtime._capability = bundle.capability
                    runtime._preparation_used = True
                    with self.assertRaisesRegex(RuntimeError, "safety margin"):
                        runtime.dispatch_one_food_use(
                            source,
                            target_roi=(100, 100, 140, 140),
                            action_key=delivery.ITEM_USE_ACTION_KEY,
                        )
                    self.assertEqual(inner.dispatch_calls, 0)
                    self.assertIsNone(
                        components["authority"].get_resource_transport(
                            bundle.prepared.reservation_id
                        )
                    )
                    self.assertIsNone(
                        components["authority"].get_resource_transport_outcome(
                            bundle.prepared.reservation_id
                        )
                    )
                    reservation_state = components["store"].connection.execute(
                        "SELECT state FROM resource_reservations WHERE reservation_id=?",
                        (bundle.prepared.reservation_id,),
                    ).fetchone()[0]
                    self.assertEqual(reservation_state, "CLOSED")
                    self.assertEqual(
                        components["store"].connection.execute(
                            "SELECT state FROM resource_attempts WHERE attempt_id=?",
                            (bundle.prepared.attempt_id,),
                        ).fetchone()[0],
                        "ABANDONED",
                    )
                    self.assertEqual(
                        components["store"].connection.execute(
                            """SELECT state FROM resource_attempt_claims
                               WHERE attempt_id=? AND reservation_id=?""",
                            (
                                bundle.prepared.attempt_id,
                                bundle.prepared.reservation_id,
                            ),
                        ).fetchone()[0],
                        "RELEASED",
                    )
                    self.assertEqual(
                        components["store"].connection.execute(
                            "SELECT state FROM resource_occurrences WHERE occurrence_id=?",
                            (bundle.prepared.occurrence_id,),
                        ).fetchone()[0],
                        "BLOCKED",
                    )
                    self.assertEqual(
                        components["store"].get_action(bundle.prepared.action_id)["final_status"],
                        "cancelled",
                    )
                    transition_payloads = [
                        json.loads(row[0])
                        for row in components["store"].connection.execute(
                            """SELECT payload_json FROM resource_transition_history
                               WHERE entity_id IN (?,?,?,?)""",
                            (
                                bundle.prepared.reservation_id,
                                bundle.prepared.attempt_id,
                                bundle.prepared.occurrence_id,
                                components["store"].connection.execute(
                                    """SELECT claim_id FROM resource_attempt_claims
                                       WHERE attempt_id=? AND reservation_id=?""",
                                    (
                                        bundle.prepared.attempt_id,
                                        bundle.prepared.reservation_id,
                                    ),
                                ).fetchone()[0],
                            ),
                        ).fetchall()
                    ]
                    self.assertTrue(
                        any(
                            payload["payload"].get("reason")
                            == "reset_dispatch_window_expired"
                            and payload["payload"].get("adapter_invoked") is False
                            and payload["payload"].get("transport_intent_absent") is True
                            for payload in transition_payloads
                        )
                    )
                    repeated = components["authority"].cancel_prepared_resource_effect(
                        bundle.prepared,
                        controller_lease=components["controller_lease"],
                        runtime_lock=session.runtime_input_lock,
                        reason="reset_dispatch_window_expired",
                        now=time.monotonic(),
                    )
                    self.assertTrue(repeated["idempotent"])
                    stale = replace(
                        bundle.prepared,
                        fence=replace(
                            bundle.prepared.fence,
                            immediate_before_sha256="0" * 64,
                        ),
                    )
                    with self.assertRaises(ResourceFenceError):
                        components["authority"].cancel_prepared_resource_effect(
                            stale,
                            controller_lease=components["controller_lease"],
                            runtime_lock=session.runtime_input_lock,
                            reason="reset_dispatch_window_expired",
                            now=time.monotonic(),
                        )
                    binding = pnsctl._resource_fixed_runtime_binding()
                    next_reset = ResourceResetIdentity(
                        "reset-deadline:next",
                        binding.account_id,
                        binding.server_id,
                        binding.runtime_scope,
                        "2026-08-21T00:00:00Z",
                        "2026-08-22T00:00:00Z",
                        observed_at=time.monotonic(),
                        evidence_refs=("test:d-plus-1",),
                    )
                    components["authority"].append_reset_identity(next_reset)
                    next_occurrence = components["authority"].create_resource_occurrence(
                        ResourceOccurrenceIdentity(
                            binding.account_id,
                            binding.server_id,
                            "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION",
                            next_reset.reset_identity_id,
                        )
                    )
                    next_claim = components["authority"].claim_resource_attempt(
                        next_occurrence["occurrence_id"],
                        session.owner,
                        now=time.monotonic(),
                    )
                    self.assertEqual(next_claim.state, "ACTIVE")
                    components["authority"].release_resource_controller_lease(
                        session.owner,
                        components["controller_lease"]["controller_token"],
                        time.monotonic(),
                    )
                    components["store"].close()

    def test_pnsctl_resource_store_rejects_missing_or_v3_without_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "missing.sqlite3"
            factory_calls: list[Path] = []

            def factory(path: Path):
                factory_calls.append(path)
                return SafetyStore(path)

            with self.assertRaises(pnsctl.OperatorError):
                pnsctl._open_admitted_resource_store(
                    store_path=missing,
                    store_factory=factory,
                )
            self.assertEqual(factory_calls, [])

            v3 = root / "v3.sqlite3"
            seed = SafetyStore(v3)
            seed.close()
            db = __import__("sqlite3").connect(v3)
            db.execute("UPDATE schema_version SET version=3 WHERE singleton=1")
            db.commit()
            db.close()
            with self.assertRaises(pnsctl.OperatorError):
                pnsctl._open_admitted_resource_store(
                    store_path=v3,
                    store_factory=factory,
                )
            self.assertEqual(factory_calls, [])
            verify = __import__("sqlite3").connect(v3)
            self.assertEqual(
                verify.execute(
                    "SELECT version FROM schema_version WHERE singleton=1"
                ).fetchone()[0],
                3,
            )
            verify.close()

    def test_development_session_real_resource_branch_cleans_up_on_navigation_block(self):
        seen: dict[str, object] = {}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture_root = root / "captures"
            (
                producer_output,
                identity_session,
                reset_id,
                producer_recognizer_calls,
            ) = self._produce_identity_session(capture_root)
            receipt_path = Path(str(producer_output["receipt_path"]))
            receipt_hash_before = _digest(receipt_path)
            frame_path = identity_session / "source.png"
            frame_hash_before = _digest(frame_path)
            summary_path = identity_session / "summary.json"
            summary_hash_before = _digest(summary_path)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            deadline_payload = receipt["current_reset_deadline_evidence"]
            frame_observed_utc = str(deadline_payload["observed_utc"])
            frame = np.full((1280, 800, 3), (5, 15, 25), dtype=np.uint8)
            source_ok, source_encoded = cv2.imencode(".png", frame)
            self.assertTrue(source_ok)
            source_bytes = source_encoded.tobytes()
            source_digest = hashlib.sha256(source_bytes).hexdigest()
            session_directory = capture_root / "resource-run"
            store_path = root / "actions.sqlite3"
            seed = SafetyStore(store_path)
            seed.close()
            opened_stores: list[SafetyStore] = []

            def store_factory(path: Path):
                store = SafetyStore(path)
                opened_stores.append(store)
                return store

            def runner(queue, runtime_context, *, live=False):
                del queue, live
                seen.update(runtime_context)
                self.assertTrue(callable(runtime_context["resource_runtime_factory"]))
                self.assertEqual(
                    runtime_context["resource_deadline_evidence"]["daily_frame"]["path"],
                    "source.png",
                )
                runtime_identity = runtime_context["resource_runtime_identity"]
                binding = pnsctl._resource_fixed_runtime_binding()
                self.assertEqual(runtime_identity.runtime_scope, binding.runtime_scope)
                self.assertEqual(runtime_identity.account_id, binding.account_id)
                self.assertEqual(runtime_identity.server_id, binding.server_id)
                self.assertNotEqual(runtime_identity.account_id, "test-account")
                self.assertNotEqual(runtime_identity.server_id, "test-server")
                self.assertIn(
                    f"producer-session:{identity_session.name}",
                    runtime_identity.evidence_refs,
                )
                self.assertNotEqual(
                    runtime_context["development_session"].session_directory,
                    identity_session,
                )
                return json.dumps(
                    {
                        "status": "blocked",
                        "reason": "navigation target unavailable",
                        "session_directory": "",
                    }
                )

            class ResourceIdentityRecognizer:
                def recognize_daily_claim(
                    self,
                    image: np.ndarray,
                    *,
                    game_day_id=None,
                    observed_utc=None,
                ):
                    del image
                    self.calls.append((tuple((1280, 800, 3)), game_day_id, observed_utc))
                    return daily.FrameRecognition(
                        state=daily.DAILY_SELECTED_STATE,
                        recognized=True,
                        visual_evidence={
                            "selected_daily": True,
                            "runtime_profile_id": daily.BLUESTACKS_RUNTIME_PROFILE_ID,
                            "reset_deadline_identity": deadline_payload[
                                "deadline_identity"
                            ],
                            "reset_deadline_utc": deadline_payload[
                                "normalized_deadline_utc"
                            ],
                            "reset_observed_utc": deadline_payload["observed_utc"],
                            "reset_timer_seconds": deadline_payload[
                                "reset_timer_seconds"
                            ],
                        },
                    )

                def __init__(self):
                    self.calls: list[tuple[tuple[int, ...], object, object]] = []

            recognizer = ResourceIdentityRecognizer()

            def development_observation():
                return (
                    {
                        "device_state": "device",
                        "screen_state": "HOME_CANONICAL",
                        "foreground_package": pnsctl.PACKAGE,
                        "native_width": 800,
                        "native_height": 1280,
                        "frame_sha256": source_digest,
                    },
                    source_bytes,
                )

            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with patch.object(pnsctl, "DEVELOPMENT_SESSION_ROOT", capture_root):
                    with patch.object(
                        pnsctl,
                        "_development_session_directory",
                        return_value=session_directory,
                    ):
                        with patch.object(
                            daily,
                            "DailyRowClaimRecognizer",
                            return_value=recognizer,
                        ):
                            with patch.object(
                                pnsctl,
                                "_development_runtime_observation",
                                side_effect=development_observation,
                            ):
                                with patch.object(
                                    pnsctl,
                                    "_load_bluestacks_flow_registry",
                                    return_value={
                                        delivery.FLOW_ID: {"runner": "resource-runner"}
                                    },
                                ):
                                    with patch.dict(
                                        pnsctl._BLUESTACKS_FLOW_RUNNERS,
                                        {"resource-runner": runner},
                                    ):
                                        result = json.loads(
                                            pnsctl.development_session_run_flow(
                                                delivery.FLOW_ID,
                                                live=True,
                                                yes=True,
                                                max_inputs=10,
                                                runtime_scope="test-scope",
                                                account_id="test-account",
                                                server_id="test-server",
                                                reset_id=reset_id,
                                                identity_evidence=receipt_path,
                                                _resource_store_path=store_path,
                                                _resource_store_factory=store_factory,
                                            )
                                        )
            self.assertEqual(result["status"], "blocked")
            self.assertIn("resource_runtime_factory", seen)
            self.assertEqual(
                seen["development_session"].session_directory,
                session_directory,
            )
            self.assertTrue((session_directory / "source.png").is_file())
            self.assertEqual(_digest(session_directory / "source.png"), source_digest)
            self.assertEqual(
                producer_recognizer_calls[0][0],
                (1280, 800, 3),
            )
            self.assertEqual(
                recognizer.calls,
                [
                    (
                        (1280, 800, 3),
                        None,
                        datetime.fromisoformat(
                            frame_observed_utc.replace("Z", "+00:00")
                        ),
                    )
                ],
            )
            self.assertEqual(_digest(frame_path), frame_hash_before)
            self.assertEqual(_digest(receipt_path), receipt_hash_before)
            self.assertEqual(_digest(summary_path), summary_hash_before)
            self.assertEqual(len(opened_stores), 1)
            with self.assertRaises(sqlite3.ProgrammingError):
                opened_stores[0].connection.execute("SELECT 1")
            verify = sqlite3.connect(store_path)
            self.assertIsNotNone(
                verify.execute(
                    "SELECT released_at FROM controller_lease WHERE singleton=1"
                ).fetchone()[0]
            )
            verify.close()

    def test_resource_identity_producer_writes_authenticated_zero_input_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            capture_root = Path(tmp) / "captures"
            output, session, reset_id, recognizer_calls = self._produce_identity_session(
                capture_root
            )
            receipt_path = Path(str(output["receipt_path"]))
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            summary = json.loads(
                (session / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                receipt_path.name,
                pnsctl.RESOURCE_IDENTITY_RECEIPT_FILENAME,
            )
            self.assertEqual(
                receipt["producer_kind"],
                pnsctl.RESOURCE_IDENTITY_PRODUCER_KIND,
            )
            self.assertEqual(
                receipt["producer_version"],
                pnsctl.RESOURCE_IDENTITY_PRODUCER_VERSION,
            )
            self.assertEqual(receipt["producer_owner"], pnsctl.RESOURCE_IDENTITY_PRODUCER_OWNER)
            self.assertEqual(receipt["producer_invocation_id"], session.name)
            self.assertEqual(receipt["producer_session_id"], session.name)
            binding = pnsctl._resource_fixed_runtime_binding()
            self.assertEqual(receipt["runtime_scope"], binding.runtime_scope)
            self.assertEqual(receipt["account_id"], binding.account_id)
            self.assertEqual(receipt["server_id"], binding.server_id)
            self.assertEqual(receipt["runtime_binding"], binding.as_dict())
            self.assertEqual(
                receipt["identity_semantics"],
                "fixed_runtime_binding_plus_observed_daily_reset",
            )
            self.assertEqual(
                receipt["assurance"],
                "fixed_runtime_binding_reset_observed",
            )
            self.assertEqual(receipt["reset_id"], reset_id)
            self.assertEqual(summary["status"], "observed")
            self.assertEqual(summary["owner"], pnsctl.RESOURCE_IDENTITY_PRODUCER_OWNER)
            self.assertEqual(summary["invocation_id"], session.name)
            self.assertEqual(summary["input_count"], 0)
            self.assertEqual(summary["action_count"], 0)
            self.assertEqual(summary["max_inputs"], 0)
            self.assertTrue(summary["ownership_released"])
            self.assertFalse(summary["lifecycle_state_created"])
            self.assertEqual(output["input_count"], 0)
            self.assertEqual(output["action_count"], 0)
            self.assertFalse(output["dispatch"])
            self.assertFalse((Path(tmp) / "actions.sqlite3").exists())
            frame = session / "source.png"
            self.assertEqual(receipt["frame"]["path"], "source.png")
            self.assertEqual(receipt["frame"]["sha256"], _digest(frame))
            evidence = ResourceIdentityEvidence(
                **receipt["resource_identity_evidence"]
            )
            self.assertEqual(evidence.reset_id, reset_id)
            self.assertEqual(evidence.content_digest, evidence.computed_digest())
            self.assertEqual(receipt["self_digest"], evidence.computed_digest())
            self.assertEqual(
                receipt["receipt_digest"],
                pnsctl._resource_identity_receipt_digest(receipt),
            )
            self.assertEqual(
                recognizer_calls[0][2],
                datetime.fromisoformat(
                    receipt["observed_utc"].replace("Z", "+00:00")
                ),
            )

    def test_resource_identity_producer_fails_closed_without_authoritative_receipt(self):
        for selected_daily, reset_matches in ((False, True), (True, False)):
            with self.subTest(selected_daily=selected_daily, reset_matches=reset_matches):
                with tempfile.TemporaryDirectory() as tmp:
                    capture_root = Path(tmp) / "captures"
                    _output, session, _reset_id, _calls = self._produce_identity_session(
                        capture_root,
                        selected_daily=selected_daily,
                        reset_matches=reset_matches,
                        expect_failure=True,
                    )
                    summary = json.loads(
                        (session / "summary.json").read_text(encoding="utf-8")
                    )
                    self.assertEqual(summary["status"], "failed")
                    self.assertEqual(summary["input_count"], 0)
                    self.assertEqual(summary["action_count"], 0)
                    self.assertTrue(summary["ownership_released"])
                    self.assertFalse(
                        (session / pnsctl.RESOURCE_IDENTITY_RECEIPT_FILENAME).exists()
                    )

    def test_resource_identity_consumer_rejects_missing_or_tampered_authentication(self):
        cases = (
            ("missing-summary", "missing_summary", None),
            ("wrong-owner", "summary", ("owner", "wrong-owner")),
            ("wrong-status", "summary", ("status", "failed")),
            ("wrong-invocation", "summary", ("invocation_id", "wrong")),
            ("nonzero-input", "summary", ("input_count", 1)),
            ("nonzero-action", "summary", ("action_count", 1)),
            ("tampered-summary-terminal", "summary", ("terminal_at", "tampered")),
            ("tampered-producer-owner", "producer", ("owner", "wrong-owner")),
            ("tampered-producer-invocation", "producer", ("invocation_id", "wrong")),
        )
        for label, artifact, change in cases:
            with self.subTest(case=label):
                with tempfile.TemporaryDirectory() as tmp:
                    capture_root = Path(tmp) / "captures"
                    output, session, _reset_id, _calls = self._produce_identity_session(
                        capture_root
                    )
                    receipt_path = Path(str(output["receipt_path"]))
                    if artifact == "missing_summary":
                        (session / "summary.json").unlink()
                    elif artifact == "summary":
                        summary_path = session / "summary.json"
                        summary = json.loads(summary_path.read_text(encoding="utf-8"))
                        assert change is not None
                        summary[change[0]] = change[1]
                        summary_path.write_text(
                            json.dumps(summary, sort_keys=True) + "\n",
                            encoding="utf-8",
                        )
                    else:
                        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                        assert change is not None
                        receipt["producer"][change[0]] = change[1]
                        receipt_path.write_text(
                            json.dumps(receipt, sort_keys=True) + "\n",
                            encoding="utf-8",
                        )
                    with patch.object(pnsctl, "DEVELOPMENT_SESSION_ROOT", capture_root):
                        with self.assertRaises(pnsctl.OperatorError):
                            pnsctl._load_resource_identity_payload(receipt_path)

    def test_resource_identity_binding_mismatch_fails_before_store_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture_root = root / "captures"
            output, _identity_session, _reset_id, _calls = self._produce_identity_session(
                capture_root
            )
            receipt_path = Path(str(output["receipt_path"]))
            current_session = root / "current-resource-session"
            current_session.mkdir()

            with patch.object(pnsctl, "DEVELOPMENT_SESSION_ROOT", capture_root):
                with patch.object(pnsctl, "BLUESTACKS_SERIAL", "emulator-5556"):
                    with patch.object(
                        pnsctl,
                        "_open_admitted_resource_store",
                        side_effect=AssertionError("store must not open"),
                    ):
                        with self.assertRaisesRegex(
                            pnsctl.OperatorError,
                            "fixed serial/profile/package/login-slot binding",
                        ):
                            pnsctl._produce_resource_runtime_identity(
                                identity_evidence=receipt_path,
                                session=current_session,
                            )

    def test_resource_identity_parser_dispatches_without_runtime_access(self):
        argv = [
            "development-session",
            "resource-identity-observe",
        ]
        with patch.object(
            pnsctl,
            "development_session_resource_identity_observe",
            return_value=json.dumps({"status": "observed"}),
        ) as operation:
            with patch("builtins.print") as printer:
                self.assertEqual(pnsctl.main(argv), 0)
        operation.assert_called_once_with()
        printer.assert_called_once_with('{"status": "observed"}')

    def test_resource_identity_rejects_receipt_outside_fixed_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture_root = root / "captures"
            capture_root.mkdir()
            outside = root / "outside-identity.json"
            outside.write_text("{}", encoding="utf-8")
            with patch.object(pnsctl, "DEVELOPMENT_SESSION_ROOT", capture_root):
                with self.assertRaisesRegex(
                    pnsctl.OperatorError,
                    "beneath the fixed capture root",
                ):
                    pnsctl._load_resource_identity_payload(outside)

    def test_resource_identity_rejects_frame_escaping_prior_receipt_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            identity_session = root / "identity-session"
            identity_session.mkdir()
            outside = root / "outside-daily.png"
            frame = _write_blank_native(outside)
            now = datetime.now(timezone.utc).replace(microsecond=0)
            timestamp = now.isoformat().replace("+00:00", "Z")
            frame_payload = {
                "path": "../outside-daily.png",
                "sha256": _digest(frame),
                "captured_utc": timestamp,
                "observed_utc": timestamp,
            }
            deadline_payload = {
                "daily_frame": frame_payload,
                "observed_utc": timestamp,
            }
            with self.assertRaisesRegex(
                pnsctl.OperatorError,
                "traversal|escapes the session directory",
            ):
                pnsctl._resource_identity_frame_proof(
                    session=identity_session,
                    evidence_payload={"observed_utc": timestamp},
                    deadline_payload=deadline_payload,
                )

    def test_authoritative_budgets_agree_across_active_sources(self):
        contract = json.loads(
            (
                REPO
                / "tasks"
                / "gameplay_flow_contracts"
                / "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION.json"
            ).read_text(encoding="utf-8")
        )
        profile = json.loads(
            (REPO / "tasks" / "flow_delivery_validation_profiles.json").read_text(
                encoding="utf-8"
            )
        )["flow_profiles"][delivery.FLOW_ID]
        self.assertEqual(route.MAX_ROUTE_INPUTS, 10)
        self.assertEqual(route.MAX_RESOURCE_LIST_SWIPES, 6)
        self.assertEqual(delivery.MAX_INPUTS, route.MAX_ROUTE_INPUTS)
        self.assertEqual(
            delivery.MAX_RESOURCE_LIST_SWIPES, route.MAX_RESOURCE_LIST_SWIPES
        )
        self.assertEqual(
            pnsctl._CONDUCT_DEFAULT_MAX_INPUTS[delivery.FLOW_ID],
            route.MAX_ROUTE_INPUTS,
        )
        self.assertEqual(
            contract["navigation_input_authorization"]["maximum_inputs"],
            route.MAX_ROUTE_INPUTS,
        )
        self.assertEqual(
            contract["navigation_input_authorization"]["maximum_resource_list_swipes"],
            route.MAX_RESOURCE_LIST_SWIPES,
        )
        self.assertEqual(profile["maximum_inputs"], route.MAX_ROUTE_INPUTS)
        self.assertEqual(
            profile["maximum_resource_list_swipes"], route.MAX_RESOURCE_LIST_SWIPES
        )

    def test_pnsctl_has_fixed_runner_validator_and_recovery_bindings(self):
        self.assertIs(
            pnsctl._BLUESTACKS_FLOW_RUNNERS[delivery.RUNNER_ID],
            delivery.run_daily_resource_item,
        )
        self.assertIs(
            pnsctl._BLUESTACKS_EVIDENCE_VALIDATORS[delivery.VALIDATOR_ID],
            delivery.verify_daily_resource_item,
        )
        self.assertIs(
            pnsctl._BLUESTACKS_RECOVERY_HANDLERS[delivery.RECOVERY_ID],
            delivery.recover_daily_resource_item,
        )
        self.assertEqual(delivery.MAX_INPUTS, 10)
        self.assertEqual(delivery.MAX_RESOURCE_LIST_SWIPES, 6)

    def test_frame_binding_rejects_wrong_hash_escape_and_outside_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            frame = _write_blank_native(session / "frames" / "home.png")
            good = {"path": "frames/home.png", "sha256": _digest(frame)}
            self.assertIsNotNone(delivery._bound_retained_frame(session, good))

            wrong = {"path": "frames/home.png", "sha256": "a" * 64}
            self.assertIsNone(delivery._bound_retained_frame(session, wrong))

            missing = {"path": "frames/missing.png", "sha256": good["sha256"]}
            self.assertIsNone(delivery._bound_retained_frame(session, missing))

            escape = {"path": "../frames/home.png", "sha256": good["sha256"]}
            self.assertIsNone(delivery._bound_retained_frame(session, escape))

            outside = Path(tmp).parent / "outside-home.png"
            _write_blank_native(outside)
            absolute = {"path": str(outside), "sha256": _digest(outside)}
            self.assertIsNone(delivery._bound_retained_frame(session, absolute))

    def test_verifier_accepts_retained_live_frames_with_real_digests(self):
        before_src = LIVE_FRAMES / "0007-daily-resource-item:use-1k-food-immediate-before.png"
        after_src = LIVE_FRAMES / "0009-daily-resource-item-use-settled.png"
        home_src = LIVE_FRAMES / "0013-daily-resource-item-return-home-settled-final.png"
        if not (before_src.is_file() and after_src.is_file() and home_src.is_file()):
            self.skipTest("retained live Daily Resource Item frames are unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            before = _copy_into(session, before_src, "item-before.png")
            after = _copy_into(session, after_src, "item-after.png")
            home = _copy_into(session, home_src, "home.png")
            (session / "events.jsonl").write_text(
                json.dumps(
                    {
                        "type": "dispatch",
                        "execute": True,
                        "action_key": delivery.ITEM_USE_ACTION_KEY,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            verified = delivery.verify_daily_resource_item(
                {
                    "result": {
                        "status": "completed",
                        "item_use_transport_calls": 1,
                        "resource_delta_verified": True,
                        "terminal_home_verified": True,
                        "terminal_runtime_state": "recognized_home",
                        "events_path": "events.jsonl",
                        "production_registration": "NOT_REGISTERED",
                        "scheduler_enabled": False,
                        "semantic_evidence": {
                            "before_owned_quantity": 129680,
                            "after_owned_quantity": 129679,
                            "before_food_resource": None,
                            "after_food_resource": None,
                            "item_before_frame": {
                                "path": "frames/item-before.png",
                                "sha256": _digest(before),
                            },
                            "item_after_frame": {
                                "path": "frames/item-after.png",
                                "sha256": _digest(after),
                            },
                            "terminal_home_frame": {
                                "path": "frames/home.png",
                                "sha256": _digest(home),
                            },
                        },
                    },
                    "session_directory": str(session),
                },
                {},
                {},
            )
        self.assertEqual(verified["status"], "verified")
        self.assertEqual(verified["owned_before_rederived"], 129680)
        self.assertEqual(verified["owned_after_rederived"], 129679)
        self.assertTrue(verified["terminal_home_rerecognized"])
        self.assertEqual(verified["production_registration"], "NOT_REGISTERED")
        self.assertFalse(verified["scheduler_enabled"])

    def test_dry_run_has_zero_transport_and_ten_input_ceiling(self):
        payload = json.loads(
            delivery.run_daily_resource_item(
                {},
                {"max_inputs": 10},
                live=False,
            )
        )
        self.assertEqual(payload["status"], "dry_run")
        self.assertFalse(payload["dispatch"])
        self.assertEqual(payload["input_count"], 0)
        self.assertEqual(payload["max_inputs"], 10)
        self.assertEqual(payload["max_resource_list_swipes"], 6)
        self.assertEqual(payload["item_use_transport_calls"], 0)
        self.assertFalse(payload["scheduler_enabled"])

    def test_invalid_input_ceiling_fails_closed(self):
        with self.assertRaises(Exception):
            delivery.run_daily_resource_item({}, {"max_inputs": 13}, live=False)
        with self.assertRaises(Exception):
            delivery.run_daily_resource_item({}, {"max_inputs": 12}, live=False)

    def test_incomplete_result_requires_evidence(self):
        result = delivery.verify_daily_resource_item(
            {
                "result": {
                    "status": "completed",
                    "item_use_transport_calls": 1,
                    "resource_delta_verified": False,
                    "terminal_home_verified": True,
                },
                "session_directory": "session",
            },
            {},
            {},
        )
        self.assertEqual(result["status"], "evidence_required")

    def test_verifier_rejects_boolean_only_and_bad_event_counts(self):
        before_src = LIVE_FRAMES / "0007-daily-resource-item:use-1k-food-immediate-before.png"
        after_src = LIVE_FRAMES / "0009-daily-resource-item-use-settled.png"
        home_src = LIVE_FRAMES / "0013-daily-resource-item-return-home-settled-final.png"
        if not (before_src.is_file() and after_src.is_file() and home_src.is_file()):
            self.skipTest("retained live Daily Resource Item frames are unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            before = _copy_into(session, before_src, "item-before.png")
            after = _copy_into(session, after_src, "item-after.png")
            home = _copy_into(session, home_src, "home.png")
            semantic = {
                "before_owned_quantity": 129680,
                "after_owned_quantity": 129679,
                "item_before_frame": {
                    "path": "frames/item-before.png",
                    "sha256": _digest(before),
                },
                "item_after_frame": {
                    "path": "frames/item-after.png",
                    "sha256": _digest(after),
                },
                "terminal_home_frame": {
                    "path": "frames/home.png",
                    "sha256": _digest(home),
                },
            }
            base = {
                "status": "completed",
                "item_use_transport_calls": 1,
                "resource_delta_verified": True,
                "terminal_home_verified": True,
                "terminal_runtime_state": "recognized_home",
                "events_path": "events.jsonl",
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
                "semantic_evidence": semantic,
            }

            def verify(result: dict) -> str:
                return delivery.verify_daily_resource_item(
                    {"result": result, "session_directory": str(session)},
                    {},
                    {},
                )["status"]

            (session / "events.jsonl").write_text("", encoding="utf-8")
            self.assertEqual(verify(dict(base)), "evidence_required")

            (session / "events.jsonl").write_text(
                "\n".join(
                    json.dumps(
                        {
                            "type": "dispatch",
                            "execute": True,
                            "action_key": delivery.ITEM_USE_ACTION_KEY,
                        }
                    )
                    for _ in range(2)
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(verify(dict(base)), "evidence_required")

            (session / "events.jsonl").write_text(
                json.dumps(
                    {
                        "type": "dispatch",
                        "execute": True,
                        "action_key": delivery.ITEM_USE_ACTION_KEY,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            bad_delta = dict(base)
            bad_delta["semantic_evidence"] = {
                **semantic,
                "before_owned_quantity": 10,
                "after_owned_quantity": 8,
            }
            self.assertEqual(verify(bad_delta), "evidence_required")

            wrong_before = dict(base)
            wrong_before["semantic_evidence"] = {
                **semantic,
                "item_before_frame": {
                    "path": "frames/item-before.png",
                    "sha256": "a" * 64,
                },
            }
            self.assertEqual(verify(wrong_before), "evidence_required")

            wrong_after = dict(base)
            wrong_after["semantic_evidence"] = {
                **semantic,
                "item_after_frame": {
                    "path": "frames/item-after.png",
                    "sha256": "b" * 64,
                },
            }
            self.assertEqual(verify(wrong_after), "evidence_required")

            wrong_home = dict(base)
            wrong_home["semantic_evidence"] = {
                **semantic,
                "terminal_home_frame": {
                    "path": "frames/home.png",
                    "sha256": "c" * 64,
                },
            }
            self.assertEqual(verify(wrong_home), "evidence_required")

            missing_home = dict(base)
            missing_home["semantic_evidence"] = {
                **semantic,
                "terminal_home_frame": None,
            }
            self.assertEqual(verify(missing_home), "evidence_required")

            escaped = dict(base)
            escaped["semantic_evidence"] = {
                **semantic,
                "terminal_home_frame": {
                    "path": "../frames/home.png",
                    "sha256": _digest(home),
                },
            }
            self.assertEqual(verify(escaped), "evidence_required")

            # Non-Home pixels with claimed recognized_home flags.
            blank_home = _write_blank_native(session / "frames" / "blank-home.png")
            non_home = dict(base)
            non_home["semantic_evidence"] = {
                **semantic,
                "terminal_home_frame": {
                    "path": "frames/blank-home.png",
                    "sha256": _digest(blank_home),
                },
            }
            self.assertEqual(verify(non_home), "evidence_required")


if __name__ == "__main__":
    unittest.main()
