from __future__ import annotations

from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from safe_action_core import SafetyStore
from safe_action_core.models import TransportResult
from safe_action_core.resource_effect_authority import ResourceFenceError
from safe_action_core.store import LeaseError
from scripts import navigation_development_boundary as boundary
from scripts import resource_item_authorization as authorization
from scripts import daily_resource_item_bluestacks as resource_route
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.navigation_development_boundary import DevelopmentSession
from tasks.runtime_identity import (
    derive_resource_runtime_identity,
    derive_static_utc_reset,
    resource_fixed_runtime_binding,
)


def _resource_identity():
    binding = resource_fixed_runtime_binding()
    authority, reset_policy = authorization.load_resource_daily_reset_authority()
    now = datetime(2026, 8, 19, 10, tzinfo=timezone.utc)
    reset = derive_static_utc_reset(now)
    payload = {
        "reset_identity_id": reset.reset_identity_id,
        "deadline_identity": reset.reset_identity_id,
        "reset_deadline_identity": reset.reset_identity_id,
        "reset_start_utc": reset.reset_start_text,
        "reset_deadline_utc": reset.reset_deadline_text,
        "normalized_deadline_utc": reset.reset_deadline_text,
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
    return identity, payload


def _frame(path: Path) -> CapturedNativeFrame:
    png = b"\x89PNG\r\n\x1a\nresource-item-test-frame"
    return CapturedNativeFrame(
        frame=np.full((1280, 800, 3), 20, dtype=np.uint8),
        png=png,
        sha256=hashlib.sha256(png).hexdigest(),
        captured_monotonic=time.monotonic(),
        path=path,
    )


class ResourceItemAuthorizationTests(unittest.TestCase):
    def test_resource_identity_is_session_local_static_utc_and_authority_bound(self):
        fixed = datetime(2026, 8, 20, 0, 0, 1, tzinfo=timezone.utc)
        authority, reset_policy = authorization.load_resource_daily_reset_authority()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with DevelopmentSession(
                    owner="resource-static-identity-owner",
                    invocation_id="resource-static-identity-invocation",
                    session_directory=root / "session",
                    max_inputs=1,
                ) as session:
                    identity, payload = authorization.produce_resource_runtime_identity(
                        session=session,
                        wall_clock=lambda: fixed,
                        return_deadline_evidence=True,
                    )
        self.assertEqual(identity.assurance.value, "fixed_runtime_binding_static_utc_reset")
        self.assertEqual(identity.reset_id, "reset-deadline:2026-08-21T00:00:00Z")
        self.assertEqual(payload["reset_start_utc"], "2026-08-20T00:00:00Z")
        self.assertNotIn("daily_frame", payload)
        self.assertNotIn("machine_observed", payload)
        self.assertEqual(payload["product_authority_revision"], authority["authority_revision"])
        self.assertEqual(payload["product_authority_digest"], authority["authority_digest"])
        self.assertEqual(payload["product_policy_id"], reset_policy["policy_id"])
        self.assertIn("session-invocation:resource-static-identity-invocation", identity.evidence_refs)

    def test_resource_deadline_evidence_rejects_stale_authority_binding(self):
        _identity, payload = _resource_identity()
        for field, replacement_value in (
            ("product_authority_revision", "flow-delivery-product-authority-v2-r1"),
            ("product_authority_digest", "0" * 64),
            ("product_policy_id", "wrong-policy"),
            ("reset_policy_id", "wrong-policy"),
        ):
            with self.subTest(field=field):
                changed = dict(payload)
                changed[field] = replacement_value
                with self.assertRaises(authorization.ResourceItemAuthorizationError):
                    authorization.resource_deadline_evidence(changed)

    def test_reset_and_authorization_window_block_before_admitted_store_open(self):
        identity, payload = _resource_identity()
        deadline = datetime.fromisoformat(payload["reset_deadline_utc"].replace("Z", "+00:00"))
        for label, current in (
            ("at-reset", deadline),
            ("after-reset", deadline + timedelta(seconds=1)),
            ("inside-safety-margin", deadline - timedelta(seconds=authorization.RESOURCE_AUTHORIZATION_SAFETY_MARGIN_SECONDS)),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                store_open = Mock(side_effect=AssertionError("store must not open"))
                with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"), patch.object(
                    authorization, "open_admitted_resource_store", store_open
                ):
                    with DevelopmentSession(
                        owner="resource-window-owner",
                        invocation_id=f"resource-window-{label}",
                        session_directory=root / "session",
                        max_inputs=1,
                    ) as session:
                        with self.assertRaisesRegex(
                            authorization.ResourceItemAuthorizationError,
                            "before Resource SafetyStore open",
                        ):
                            authorization.build_resource_runtime_components(
                                session=session,
                                verified_identity=identity,
                                deadline_payload=payload,
                                store_path=root / "actions.sqlite3",
                                store_factory=lambda path: SafetyStore(path),
                                wall_clock=lambda: current,
                            )
                        self.assertEqual(session.input_count, 0)
                store_open.assert_not_called()

    def test_admitted_resource_store_rejects_missing_and_v3_without_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "missing.sqlite3"
            factory_calls: list[Path] = []

            def factory(path: Path):
                factory_calls.append(path)
                return SafetyStore(path)

            with self.assertRaises(authorization.ResourceItemAuthorizationError):
                authorization.open_admitted_resource_store(store_path=missing, store_factory=factory)
            self.assertEqual(factory_calls, [])

            v3 = root / "v3.sqlite3"
            seed = SafetyStore(v3)
            seed.close()
            db = sqlite3.connect(v3)
            db.execute("UPDATE schema_version SET version=3 WHERE singleton=1")
            db.commit()
            db.close()
            with self.assertRaises(authorization.ResourceItemAuthorizationError):
                authorization.open_admitted_resource_store(store_path=v3, store_factory=factory)
            self.assertEqual(factory_calls, [])
            verify = sqlite3.connect(v3)
            try:
                self.assertEqual(
                    verify.execute("SELECT version FROM schema_version WHERE singleton=1").fetchone()[0],
                    3,
                )
            finally:
                verify.close()

    def test_retained_resource_frame_requires_digest_and_contained_relative_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            frame_path = session / "frames" / "source.png"
            frame_path.parent.mkdir(parents=True)
            frame_path.write_bytes(b"retained resource evidence")
            digest = hashlib.sha256(frame_path.read_bytes()).hexdigest()
            good = {"path": "frames/source.png", "sha256": digest}
            self.assertEqual(authorization._bound_retained_frame(session, good), frame_path)
            self.assertIsNone(
                authorization._bound_retained_frame(session, {"path": good["path"], "sha256": "0" * 64})
            )
            self.assertIsNone(
                authorization._bound_retained_frame(session, {"path": "../source.png", "sha256": digest})
            )
            self.assertIsNone(
                authorization._bound_retained_frame(session, {"path": str(frame_path), "sha256": digest})
            )

    def test_unknown_transport_is_reserved_and_observe_only_reconcile_is_idempotent(self):
        identity, payload = _resource_identity()
        now = datetime.fromisoformat(payload["evaluated_utc"].replace("Z", "+00:00")) + timedelta(seconds=1)

        class Inner:
            execute = True
            frame_max_age_seconds = 30.0
            input_count = 0
            session = Path("inner-session")

            def __init__(self):
                self.dispatch_calls = 0

            def dispatch_prepared_resource_item_use(self, *_args, **_kwargs):
                self.dispatch_calls += 1
                return TransportResult(False, "NOT_SENT")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "actions.sqlite3"
            seed = SafetyStore(store_path)
            seed.close()
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "runtime-lock.sqlite3"), boundary.RuntimeInputLock(
                owner="automation-service", invocation_id="canonical-service-invocation",
            ) as input_lock:
                with DevelopmentSession(
                    owner="resource-effect-owner",
                    invocation_id="resource-effect-invocation",
                    session_directory=root / "session",
                    max_inputs=10,
                    runtime_input_lock=input_lock,
                    checkpoint=lambda: input_lock.assert_held(
                        "automation-service", "canonical-service-invocation",
                    ),
                ) as session:
                    components = authorization.build_resource_runtime_components(
                        session=session,
                        verified_identity=identity,
                        deadline_payload=payload,
                        store_path=store_path,
                        store_factory=lambda path: SafetyStore(path),
                        wall_clock=lambda: now,
                    )
                    try:
                        inner = Inner()
                        runtime = components["runtime_factory"](inner)
                        source = _frame(root / "source.png")
                        bundle = runtime._prepare(source, (100, 100, 140, 140), authorization.ITEM_USE_ACTION_KEY)
                        runtime._prepared = bundle.prepared
                        runtime._request = bundle.request
                        runtime._capability = bundle.capability
                        runtime._preparation_used = True
                        self.assertEqual(
                            bundle.request.observation.frame_sha256,
                            bundle.prepared.fence.immediate_before_sha256,
                        )
                        for field, value in (
                            ("occurrence_id", f"{bundle.prepared.occurrence_id}:mutated"),
                            ("attempt_id", f"{bundle.prepared.attempt_id}:mutated"),
                            ("reservation_id", f"{bundle.prepared.reservation_id}:mutated"),
                            (
                                "reservation_state_revision",
                                bundle.prepared.reservation_state_revision + 1,
                            ),
                        ):
                            with self.subTest(fence_field=field):
                                mutated = replace(
                                    bundle.prepared,
                                    fence=replace(bundle.prepared.fence, **{field: value}),
                                )
                                with self.assertRaises(ResourceFenceError):
                                    components["authority"].cancel_prepared_resource_effect(
                                        mutated,
                                        controller_lease=components["controller_lease"],
                                        runtime_lock=session.runtime_input_lock,
                                        reason="resource_authorization_expired",
                                        now=time.monotonic(),
                                    )
                                self.assertIsNone(
                                    components["authority"].get_resource_transport(
                                        bundle.prepared.reservation_id
                                    )
                                )
                                self.assertEqual(inner.dispatch_calls, 0)
                        result = runtime.dispatch_one_food_use(
                            source,
                            target_roi=(100, 100, 140, 140),
                            action_key=authorization.ITEM_USE_ACTION_KEY,
                        )
                        self.assertEqual(result.transport_code, "NOT_SENT")
                        self.assertEqual(inner.dispatch_calls, 1)
                        outcome = components["authority"].get_resource_transport_outcome(
                            bundle.prepared.reservation_id
                        )
                        self.assertIsNotNone(outcome)
                        self.assertEqual(outcome["state"], "TRANSPORT_UNKNOWN")
                        self.assertEqual(outcome["adapter_invoked"], 1)
                        reservation = components["store"].connection.execute(
                            "SELECT state FROM resource_reservations WHERE reservation_id=?",
                            (bundle.prepared.reservation_id,),
                        ).fetchone()[0]
                        self.assertEqual(reservation, "TRANSPORT_UNKNOWN")
                        evidence = {
                            "effect_state": "EFFECT_CONFIRMED",
                            "before_owned_quantity": 10,
                            "after_owned_quantity": 9,
                            "evidence_refs": ("test:owned-item-decrement",),
                        }
                        for _ in range(2):
                            components["authority"].reconcile_resource_effect_observe_only(
                                bundle.prepared.reservation_id,
                                evidence,
                                now=time.monotonic(),
                            )
                        self.assertEqual(
                            components["store"].get_action(bundle.prepared.action_id)["final_status"],
                            "confirmed",
                        )
                        self.assertFalse(components["store"].has_action_block())
                        self.assertIsNotNone(
                            components["store"].connection.execute(
                                "SELECT 1 FROM resource_occurrences WHERE occurrence_id=?",
                                (bundle.prepared.occurrence_id,),
                            ).fetchone()
                        )
                        with self.assertRaises(Exception):
                            runtime._prepare(source, (100, 100, 140, 140), authorization.ITEM_USE_ACTION_KEY)
                    finally:
                        authorization.release_resource_runtime_components(components)


    def test_unresolved_use_stays_blocked_after_runtime_restart(self):
        identity, payload = _resource_identity()
        now = datetime.fromisoformat(payload["evaluated_utc"].replace("Z", "+00:00")) + timedelta(seconds=1)

        class Inner:
            execute = True
            frame_max_age_seconds = 30.0
            input_count = 0
            session = Path("inner-session")

            def __init__(self):
                self.dispatch_calls = 0

            def dispatch_prepared_resource_item_use(self, *_args, **_kwargs):
                self.dispatch_calls += 1
                return TransportResult(False, "NOT_SENT")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "actions.sqlite3"
            seed = SafetyStore(store_path)
            seed.close()
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "runtime-lock.sqlite3"):
                with DevelopmentSession(
                    owner="resource-restart-first",
                    invocation_id="resource-restart-first",
                    session_directory=root / "first-session",
                    max_inputs=10,
                ) as first:
                    components = authorization.build_resource_runtime_components(
                        session=first,
                        verified_identity=identity,
                        deadline_payload=payload,
                        store_path=store_path,
                        store_factory=lambda path: SafetyStore(path),
                        wall_clock=lambda: now,
                    )
                    try:
                        inner = Inner()
                        runtime = components["runtime_factory"](inner)
                        source = _frame(root / "first.png")
                        bundle = runtime._prepare(
                            source, (100, 100, 140, 140), authorization.ITEM_USE_ACTION_KEY
                        )
                        runtime._prepared = bundle.prepared
                        runtime._request = bundle.request
                        runtime._capability = bundle.capability
                        runtime._preparation_used = True
                        runtime.dispatch_one_food_use(
                            source,
                            target_roi=(100, 100, 140, 140),
                            action_key=authorization.ITEM_USE_ACTION_KEY,
                        )
                        self.assertEqual(inner.dispatch_calls, 1)
                    finally:
                        authorization.release_resource_runtime_components(components)

                with DevelopmentSession(
                    owner="resource-restart-second",
                    invocation_id="resource-restart-second",
                    session_directory=root / "second-session",
                    max_inputs=10,
                ) as second:
                    with self.assertRaises(LeaseError):
                        authorization.build_resource_runtime_components(
                            session=second,
                            verified_identity=identity,
                            deadline_payload=payload,
                            store_path=store_path,
                            store_factory=lambda path: SafetyStore(path),
                            wall_clock=lambda: now,
                        )
                    self.assertEqual(second.input_count, 0)

    def test_service_use_resamples_utc_after_navigation_and_cancels_before_transport(self):
        from automation_service.recruitment import recruitment_reset

        deadline = datetime(2026, 8, 20, tzinfo=timezone.utc)
        for label, started, use_time in (
            ("reset-margin", deadline - timedelta(seconds=10), deadline - timedelta(seconds=2)),
            ("reset-crossed", deadline - timedelta(seconds=10), deadline + timedelta(seconds=1)),
            (
                "authorization-expired",
                deadline - timedelta(hours=2),
                deadline - timedelta(hours=2) + timedelta(
                    seconds=authorization.RESOURCE_AUTHORIZATION_FRESHNESS_SECONDS,
                ),
            ),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                current = [started]
                with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                    with DevelopmentSession(
                        owner="resource-service-window",
                        invocation_id=f"resource-service-{label}",
                        session_directory=root / "session",
                        max_inputs=1,
                    ) as session, closing(SafetyStore(root / "actions.sqlite3")) as store:
                        binding = resource_fixed_runtime_binding()
                        inner = SimpleNamespace(
                            execute=True,
                            frame_max_age_seconds=30.0,
                            input_count=0,
                            action_keys=set(),
                            events=session.session_directory / "events.jsonl",
                            session=session.session_directory,
                            dispatch_calls=0,
                        )

                        def transport(*_args, **_kwargs):
                            inner.dispatch_calls += 1
                            return TransportResult(False, "NOT_SENT")

                        inner.dispatch_prepared_resource_item_use = transport
                        context = SimpleNamespace(
                            identity=SimpleNamespace(
                                account_id=binding.account_id,
                                server_id=binding.server_id,
                                reset_id=recruitment_reset(started.timestamp()),
                            ),
                            session=session,
                            action_store=store,
                            runtime=inner,
                            occurrence_key=f"service-window-{label}",
                            utc_clock=lambda: current[0].timestamp(),
                            validate_identity=lambda: None,
                            accounting=lambda: SimpleNamespace(
                                verified=True, input_count=0,
                                session_input_count=0, runtime_input_count=0,
                            ),
                        )

                        def delayed_use(runtime, _session):
                            # Exercise the real typed preparation, policy, SQLite
                            # reservation and Use seam after navigation has elapsed.
                            current[0] = use_time
                            runtime.dispatch_one_food_use(
                                _frame(root / "immediate-before.png"),
                                target_roi=(100, 100, 140, 140),
                                action_key=authorization.ITEM_USE_ACTION_KEY,
                            )
                            return {"item_use_transport_calls": inner.dispatch_calls}

                        with patch.object(resource_route, "run_daily_resource_item", delayed_use):
                            result = resource_route._run_service_native_route(context, {})
                        self.assertEqual(inner.dispatch_calls, 0)
                        self.assertEqual(session.input_count, 0)
                        self.assertEqual(result["item_use_transport_calls"], 0)
                        self.assertEqual(result["committed_action_count"], 0)
                        self.assertEqual(result["reservation_state"], "CLOSED")
                        self.assertEqual(result["journal_status"], "cancelled")
                        self.assertEqual(
                            store.connection.execute(
                                "SELECT state FROM resource_occurrences WHERE occurrence_id=?",
                                (result["resource_occurrence_id"],),
                            ).fetchone()[0],
                            "BLOCKED",
                        )
                        self.assertIsNone(store.connection.execute(
                            "SELECT 1 FROM resource_transport_facts",
                        ).fetchone())

    def test_resource_authorization_window_rejects_naive_times(self):
        deadline = datetime(2026, 8, 20, 11, tzinfo=timezone.utc)
        with self.assertRaises(authorization.ResourceAuthorizationWindowError):
            authorization.ResourceAuthorizationWindow(
                reset_deadline_utc=datetime(2026, 8, 20, 11),
                authorization_expires_utc=deadline,
            )
        window = authorization.ResourceAuthorizationWindow(
            reset_deadline_utc=deadline,
            authorization_expires_utc=deadline,
        )
        with self.assertRaises(authorization.ResourceAuthorizationWindowError):
            window.require_current(datetime(2026, 8, 20, 10, 0, 1))


if __name__ == "__main__":
    unittest.main()
