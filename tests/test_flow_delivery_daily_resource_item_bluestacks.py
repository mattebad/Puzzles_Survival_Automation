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
from scripts.navigation_development_boundary import (
    DevelopmentInitialObservation,
    DevelopmentSession,
)
from tasks.runtime_identity import (
    derive_fixed_runtime_binding,
    derive_resource_runtime_identity,
    derive_static_utc_reset,
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
            with patch.object(delivery.LocalBlueStacksRuntime, "connect") as connect:
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
                                max_inputs=10,
                            )
                        },
                    ),
                ):
                    with self.subTest(label=label), self.assertRaises(pnsctl.OperatorError):
                        delivery.run_daily_resource_item(
                            {}, {**lease, "max_inputs": 10}, live=True
                        )
                connect.assert_not_called()

            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with DevelopmentSession(
                    owner=f"pnsctl-development-session:{delivery.FLOW_ID}",
                    invocation_id="bound",
                    session_directory=root / "bound",
                    max_inputs=10,
                ) as session:
                    digest = hashlib.sha256(b"initial").hexdigest()
                    bound = DevelopmentInitialObservation(
                        {"frame_sha256": digest}, digest, invocation_id=session.invocation_id
                    )
                    session.set_initial_observation(bound)
                    base = {
                        "development_session": session,
                        "initial_frame_sha256": digest,
                        "max_inputs": 10,
                    }
                    for label, observation in (
                        ("missing-observation", None),
                        (
                            "mismatched-observation",
                            DevelopmentInitialObservation(
                                {"frame_sha256": digest}, digest, invocation_id=session.invocation_id
                            ),
                        ),
                    ):
                        with self.subTest(label=label):
                            lease = dict(base)
                            if observation is not None:
                                lease["initial_observation"] = observation
                            with patch.object(
                                delivery.LocalBlueStacksRuntime, "connect"
                            ) as connect:
                                with self.assertRaises(pnsctl.OperatorError):
                                    delivery.run_daily_resource_item({}, lease, live=True)
                            connect.assert_not_called()

    def _resource_identity(self):
        binding = pnsctl._resource_fixed_runtime_binding()
        authority, reset_policy = pnsctl._load_resource_daily_reset_authority()
        now = datetime(2026, 8, 19, 10, tzinfo=timezone.utc)
        window = derive_static_utc_reset(now)
        deadline_evidence = {
            "reset_identity_id": window.reset_identity_id,
            "deadline_identity": window.reset_identity_id,
            "reset_deadline_identity": window.reset_identity_id,
            "reset_start_utc": window.reset_start_text,
            "reset_deadline_utc": window.reset_deadline_text,
            "normalized_deadline_utc": window.reset_deadline_text,
            "evaluated_utc": now.isoformat().replace("+00:00", "Z"),
            "_evaluated_utc": now.isoformat().replace("+00:00", "Z"),
            "authorization_expires_utc": "2026-08-19T10:10:00Z",
            "recurrence_class": "daily_reset",
            "recurrence_interval_seconds": 86400,
            "recurrence_interval_hours": 24,
            "reset_timezone": reset_policy["timezone"],
            "reset_time": reset_policy["reset_time"],
            "product_authority_revision": authority["authority_revision"],
            "product_authority_digest": authority["authority_digest"],
            "product_policy_id": reset_policy["policy_id"],
            "reset_policy_id": reset_policy["policy_id"],
            "identity_semantics": "fixed_runtime_binding_plus_static_utc_reset",
            "assurance": "fixed_runtime_binding_static_utc_reset",
        }
        identity = derive_resource_runtime_identity(
            binding,
            now,
            evidence_refs=("test:fixed-binding", "test:static-utc-reset"),
        )
        return identity, deadline_evidence

    def test_resource_reset_boundary_denies_before_store_open(self):
        identity, deadline_evidence = self._resource_identity()
        observed = datetime.fromisoformat(
            deadline_evidence["evaluated_utc"].replace("Z", "+00:00")
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
                    seconds=delivery.RESOURCE_AUTHORIZATION_SAFETY_MARGIN_SECONDS
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

    def test_resource_identity_is_session_local_and_static_utc(self):
        fixed = datetime(2026, 8, 20, 0, 0, 1, tzinfo=timezone.utc)
        authority, reset_policy = pnsctl._load_resource_daily_reset_authority()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with DevelopmentSession(
                    owner="resource-static-identity-owner",
                    invocation_id="resource-static-identity-invocation",
                    session_directory=root / "session",
                    max_inputs=1,
                ) as session:
                    identity, payload = pnsctl._produce_resource_runtime_identity(
                        session=session,
                        wall_clock=lambda: fixed,
                        return_deadline_evidence=True,
                    )
                    self.assertEqual(
                        identity.assurance.value,
                        "fixed_runtime_binding_static_utc_reset",
                    )
                    self.assertEqual(
                        identity.reset_id,
                        "reset-deadline:2026-08-21T00:00:00Z",
                    )
                    self.assertEqual(
                        payload["reset_start_utc"],
                        "2026-08-20T00:00:00Z",
                    )
                    self.assertNotIn("daily_frame", payload)
                    self.assertNotIn("machine_observed", payload)
                    self.assertEqual(
                        payload["product_authority_revision"],
                        authority["authority_revision"],
                    )
                    self.assertEqual(
                        payload["product_authority_digest"],
                        authority["authority_digest"],
                    )
                    self.assertEqual(
                        payload["product_policy_id"],
                        reset_policy["policy_id"],
                    )
                    self.assertIn(
                        f"product-authority-revision:{authority['authority_revision']}",
                        identity.evidence_refs,
                    )
                    self.assertIn(
                        f"product-authority-digest:{authority['authority_digest']}",
                        identity.evidence_refs,
                    )
                    self.assertIn(
                        f"product-policy-id:{reset_policy['policy_id']}",
                        identity.evidence_refs,
                    )
                    self.assertIn(
                        "session-invocation:resource-static-identity-invocation",
                        identity.evidence_refs,
                    )

    def test_resource_deadline_payload_rejects_stale_authority_binding(self):
        _identity, payload = self._resource_identity()
        for field, replacement in (
            ("product_authority_revision", "flow-delivery-product-authority-v2-r1"),
            ("product_authority_digest", "0" * 64),
            ("product_policy_id", "wrong-policy"),
            ("reset_policy_id", "wrong-policy"),
        ):
            with self.subTest(field=field):
                changed = dict(payload)
                changed[field] = replacement
                with self.assertRaises(pnsctl.OperatorError):
                    pnsctl._resource_deadline_evidence(changed)

    def test_resource_identity_observation_command_is_removed(self):
        with self.assertRaises(SystemExit):
            pnsctl.parser().parse_args(
                ["development-session", "resource-identity-observe"]
            )

    def test_resource_conduct_skips_identity_receipt_and_observe_prestep(self):
        framing = {
            "intent_match": True,
            "no_documented_unsafe_input": True,
            "no_manual_only_precondition": True,
            "consequential_actions_enumerated": True,
            "durable_knowledge_consulted": True,
        }
        with tempfile.TemporaryDirectory() as tmp:
            run = Mock(
                return_value=json.dumps(
                    {
                        "status": "blocked",
                        "flow_id": delivery.FLOW_ID,
                        "runtime_session_directory": "",
                        "reason": "offline test",
                    }
                )
            )
            with patch.object(
                pnsctl,
                "development_session_observe",
                side_effect=AssertionError("Resource conduct must not observe first"),
            ) as observe:
                with patch.object(pnsctl, "development_session_run_flow", run):
                    with patch.object(
                        pnsctl,
                        "_conductor_live_summary",
                        return_value=(
                            {
                                "status": "blocked",
                                "flow_id": delivery.FLOW_ID,
                                "reason": "offline test",
                            },
                            {},
                        ),
                    ):
                        pnsctl.conduct_flow(
                            delivery.FLOW_ID,
                            live=True,
                            yes=True,
                            state_root=Path(tmp),
                            framing=framing,
                        )
            observe.assert_not_called()
            self.assertNotIn("identity_evidence", run.call_args.kwargs)

    def test_direct_resource_run_flow_ignores_identity_evidence_path(self):
        poisoned = Path("C:/poisoned-resource-identity-receipt.json")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            produced_identity = Mock()
            produced_evidence = {
                "reset_identity_id": "reset-deadline:2026-08-20T00:00:00Z"
            }

            def runner(queue_context, runtime_context, *, live):
                self.assertTrue(live)
                self.assertIs(runtime_context["resource_runtime_identity"], produced_identity)
                return json.dumps(
                    {
                        "status": "observed",
                        "flow_id": delivery.FLOW_ID,
                        "session_directory": "",
                    }
                )

            with patch.object(
                boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"
            ), patch.object(
                pnsctl, "_development_session_directory", return_value=root / "session"
            ), patch.object(
                pnsctl, "_checkpoint_hashes", return_value={}
            ), patch.object(
                pnsctl,
                "_development_runtime_observation",
                return_value=({"source_state": "RESOURCES_1K_FOOD_READY"}, b"png"),
            ), patch.object(
                pnsctl,
                "_produce_resource_runtime_identity",
                return_value=(produced_identity, produced_evidence),
            ) as produce, patch.object(
                pnsctl, "_build_resource_runtime_components", return_value=None
            ) as build, patch.object(
                pnsctl,
                "_nova_supervised_identity",
                side_effect=AssertionError("Resource must not load Nova identity evidence"),
            ) as nova_loader, patch.object(
                pnsctl,
                "_load_bluestacks_flow_registry",
                return_value={delivery.FLOW_ID: {"runner": "resource-test-runner"}},
            ), patch.dict(
                pnsctl._BLUESTACKS_FLOW_RUNNERS,
                {"resource-test-runner": runner},
                clear=True,
            ):
                output = pnsctl.development_session_run_flow(
                    delivery.FLOW_ID,
                    live=True,
                    yes=True,
                    max_inputs=1,
                    identity_evidence=poisoned,
                    _resource_wall_clock=lambda: datetime(
                        2026, 8, 19, 10, tzinfo=timezone.utc
                    ),
                )

            payload = json.loads(output)
            self.assertEqual(payload["status"], "observed")
            produce.assert_called_once()
            build.assert_called_once()
            nova_loader.assert_not_called()

    def test_resource_authorization_window_rejects_naive_timestamps(self):
        observed = datetime(2026, 8, 20, 10, tzinfo=timezone.utc)
        deadline = observed + timedelta(hours=1)
        window = delivery.ResourceAuthorizationWindow(
            reset_deadline_utc=deadline,
            authorization_expires_utc=deadline,
        )
        with self.assertRaises(delivery.ResourceAuthorizationWindowError):
            window.require_current(datetime(2026, 8, 20, 10, 0, 1))
        with self.assertRaises(delivery.ResourceAuthorizationWindowError):
            delivery.ResourceAuthorizationWindow(
                reset_deadline_utc=datetime(2026, 8, 20, 11),
                authorization_expires_utc=deadline,
            )

    def test_resource_authorization_window_denies_exact_and_margin_boundaries(self):
        observed = datetime(2026, 8, 20, 10, tzinfo=timezone.utc)
        deadline = observed + timedelta(hours=1)
        window = delivery.ResourceAuthorizationWindow(
            reset_deadline_utc=deadline,
            authorization_expires_utc=deadline,
        )
        for current in (
            deadline,
            deadline - window.safety_margin,
        ):
            with self.subTest(current=current):
                with self.assertRaises(delivery.ResourceAuthorizationWindowError):
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
            deadline_evidence["evaluated_utc"].replace("Z", "+00:00")
        ) + timedelta(seconds=1)

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
                                    reason="resource_authorization_expired",
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
            deadline_evidence["evaluated_utc"].replace("Z", "+00:00")
        )
        deadline = datetime.fromisoformat(
            deadline_evidence["normalized_deadline_utc"].replace("Z", "+00:00")
        )
        wall_clock_values = iter(
            (observed + timedelta(seconds=1), observed + timedelta(minutes=10))
        )

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
                            == "resource_authorization_expired"
                            and payload["payload"].get("adapter_invoked") is False
                            and payload["payload"].get("transport_intent_absent") is True
                            for payload in transition_payloads
                        )
                    )
                    repeated = components["authority"].cancel_prepared_resource_effect(
                        bundle.prepared,
                        controller_lease=components["controller_lease"],
                        runtime_lock=session.runtime_input_lock,
                        reason="resource_authorization_expired",
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
                            reason="resource_authorization_expired",
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
